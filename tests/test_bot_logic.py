import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

import config
from database import JobsDB
from main import _build_final_pool, _is_stale_job
from models import Job, is_cybersec_job, extract_salary_from_text, is_recent_enough, filter_jobs
from ml_filter import classify_cyber_probability
from telegram_sender import route_job
from unittest.mock import patch


class BotLogicTests(unittest.TestCase):
    def test_remote_job_routes_to_remote_and_topic(self):
        job = Job(
            title="SOC Analyst",
            company="Remotive Co",
            location="Anywhere",
            url="https://example.com/remote-soc",
            source="remotive",
            is_remote=True,
        )
        self.assertEqual(route_job(job), ["remote", "soc"])

    def test_egypt_soc_routes_to_egypt_and_soc(self):
        job = Job(
            title="Junior SOC Engineer",
            company="CairoSec",
            location="Cairo, Egypt",
            url="https://example.com/egypt-soc",
            source="linkedin",
        )
        self.assertEqual(route_job(job), ["egypt", "soc"])

    def test_gulf_pentest_routes_to_gulf_and_pentest(self):
        job = Job(
            title="Penetration Tester",
            company="RiyadhSec",
            location="Riyadh, Saudi Arabia",
            url="https://example.com/gulf-pentest",
            source="linkedin",
        )
        self.assertEqual(route_job(job), ["gulf", "pentest"])

    def test_daily_dedup_is_per_lane(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            db = JobsDB(db_path)
            job = Job("SOC Analyst", "Acme", "Remote", "https://example.com/a", "remotive")
            db.mark_sent(job.unique_id, job.url_id, title=job.title, company=job.company,
                         location=job.location, source=job.source, lane="geo")
            self.assertTrue(db.was_sent_recently(job.unique_id, job.url_id, "geo", 24))
            self.assertFalse(db.was_sent_recently(job.unique_id, job.url_id, "topic", 24))
            db.mark_sent(job.unique_id, job.url_id, title=job.title, company=job.company,
                         location=job.location, source=job.source, lane="topic")
            self.assertTrue(db.was_sent_recently(job.unique_id, job.url_id, "topic", 24))
        finally:
            for suffix in ("", "-wal", "-shm"):
                path = db_path + suffix
                if os.path.exists(path):
                    os.remove(path)

    def test_stale_job_is_blocked(self):
        job = Job(
            title="Security Engineer",
            company="OldCo",
            location="Egypt",
            url="https://example.com/old",
            source="linkedin",
            posted_date=datetime.now() - timedelta(days=8),
        )
        self.assertTrue(_is_stale_job(job))

    def test_stale_edge_47h_vs_48h(self):
        fresh = Job(
            title="SOC Analyst",
            company="Acme",
            location="Cairo, Egypt",
            url="https://example.com/fresh-47h",
            source="linkedin_unified",
            posted_date=datetime.now() - timedelta(hours=47),
        )
        stale = Job(
            title="SOC Analyst",
            company="Acme",
            location="Cairo, Egypt",
            url="https://example.com/stale-48h",
            source="linkedin_unified",
            posted_date=datetime.now() - timedelta(hours=48),
        )
        self.assertFalse(_is_stale_job(fresh))
        self.assertTrue(_is_stale_job(stale))
        self.assertTrue(is_recent_enough(fresh, max_age_hours=48)[0])
        self.assertFalse(is_recent_enough(stale, max_age_hours=48)[0])

    def test_business_development_cyber_is_not_technical_job(self):
        job = Job(
            title="Business Development Representative - Cybersecurity Sector",
            company="SalesCo",
            location="Egypt",
            url="https://example.com/bdr",
            source="linkedin",
        )
        self.assertFalse(is_cybersec_job(job))

    def test_channel_aware_dedup_blocks_same_channel_only(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            db = JobsDB(db_path)
            job = Job("GRC Analyst", "Acme", "Cairo, Egypt", "https://example.com/grc", "linkedin")
            db.record_sent_event(
                job_key=job.unique_id,
                url_id=job.url_id,
                channel_key="grc",
                lane="topic",
                dedup_key=job.url_id or job.unique_id,
            )
            self.assertTrue(db.was_sent_to_channel_recently(
                job.unique_id, job.url_id, "grc", job.url_id or job.unique_id, 24
            ))
            self.assertFalse(db.was_sent_to_channel_recently(
                job.unique_id, job.url_id, "egypt", job.url_id or job.unique_id, 24
            ))
            self.assertTrue(db.was_sent_globally_recently(
                job.unique_id, job.url_id, job.url_id or job.unique_id, 24
            ))
        finally:
            for suffix in ("", "-wal", "-shm"):
                path = db_path + suffix
                if os.path.exists(path):
                    os.remove(path)

    def test_non_security_intern_not_routed_to_internships(self):
        job = Job(
            title="Marketing Intern",
            company="Acme",
            location="Cairo, Egypt",
            url="https://example.com/marketing-intern",
            source="linkedin",
            description="Social media campaigns and market research.",
        )
        self.assertEqual(route_job(job), ["egypt"])

    def test_security_intern_routes_to_internships(self):
        job = Job(
            title="Cybersecurity Intern - SOC",
            company="Acme Sec",
            location="Cairo, Egypt",
            url="https://example.com/cyber-intern",
            source="linkedin",
            description="SOC monitoring, SIEM alerts, incident response support.",
        )
        routed = route_job(job)
        self.assertIn("egypt", routed)
        self.assertIn("internships", routed)

    def test_ml_rescue_guard_blocks_non_cyber_title(self):
        job = Job(
            title="Audio Transcription Specialist",
            company="Acme",
            location="Remote",
            url="https://example.com/transcription-role",
            source="linkedin_unified",
            description="Transcribe audio calls and maintain formatting quality.",
        )
        with patch("ml_filter.triage_job", return_value=("high_confidence", 0.99, ["ml_high_confidence"])):
            filtered = filter_jobs([job])
        self.assertEqual(len(filtered), 0)

    def test_smoke_pipeline_without_telegram_send(self):
        jobs = [
            Job(
                title="SOC Analyst",
                company="Acme",
                location="Cairo, Egypt",
                url="https://www.linkedin.com/jobs/view/4418556953/",
                source="linkedin_unified",
                description="SIEM monitoring, incident response, threat intelligence.",
                posted_date=datetime.now() - timedelta(hours=6),
            ),
            Job(
                title="Investment Analyst (Technology/AI Industry)",
                company="Bad Fit",
                location="Dubai, UAE",
                url="https://www.linkedin.com/jobs/view/4416880854/",
                source="linkedin_unified",
                description="Portfolio analysis and investor reporting.",
                posted_date=datetime.now() - timedelta(hours=6),
            ),
        ]
        filtered = filter_jobs(jobs)
        self.assertEqual(len(filtered), 1)
        routed = route_job(filtered[0])
        self.assertIn("egypt", routed)
        self.assertIn("soc", routed)

    def test_salary_extraction_regex(self):
        text = "Cybersecurity Intern role pays $19/hr with potential bonus."
        self.assertEqual(extract_salary_from_text(text), "$19/hr")

    def test_ml_physical_security_hard_block(self):
        job = Job(
            title="Security Agent",
            company="Airport Co",
            location="Cairo, Egypt",
            url="https://example.com/security-agent",
            source="linkedin",
        )
        proba, reasons = classify_cyber_probability(job)
        self.assertEqual(proba, 0.0)
        self.assertIn("physical_security_blocked", reasons)

    def test_telegram_retry_queue_roundtrip(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            db = JobsDB(db_path)
            payload = {
                "chat_id": "-100123",
                "text": "Test message",
                "parse_mode": "HTML",
            }
            db.enqueue_telegram_retry(
                channel_key="soc",
                thread_id=123,
                payload=payload,
                error="status=503",
                max_attempts=3,
                delay_seconds=0,
            )
            rows = db.get_due_telegram_retries(limit=5)
            self.assertEqual(len(rows), 1)
            rid = rows[0]["id"]
            db.mark_telegram_retry_attempt(rid, error="status=429", delay_seconds=1)
            rows2 = db.get_due_telegram_retries(limit=5)
            self.assertEqual(len(rows2), 0)
            db.mark_telegram_retry_sent(rid)
        finally:
            for suffix in ("", "-wal", "-shm"):
                path = db_path + suffix
                if os.path.exists(path):
                    os.remove(path)

    def test_credit_risk_consultant_is_rejected(self):
        job = Job(
            title="Managing Consultant - Credit Risk Specialist, Advisory",
            company="ConsultingCo",
            location="Cairo, Egypt",
            url="https://example.com/credit-risk",
            source="linkedin_unified",
            description="Credit risk models, portfolio analytics, and banking advisory.",
        )
        self.assertFalse(is_cybersec_job(job))

    def test_blockchain_application_support_has_no_topic_route(self):
        job = Job(
            title="Application Support Engineer - Blockchain Security",
            company="FintechCo",
            location="Riyadh, Saudi Arabia",
            url="https://example.com/blockchain-support",
            source="linkedin_unified",
            description="Support business applications and troubleshoot client tickets.",
        )
        self.assertFalse(is_cybersec_job(job))
        self.assertEqual(route_job(job), ["gulf"])

    def test_generic_solutions_architect_needs_security_context(self):
        generic = Job(
            title="Senior Solutions Architect",
            company="CloudCo",
            location="Dubai, UAE",
            url="https://example.com/solutions-architect",
            source="linkedin_unified",
            description="Design enterprise customer solutions and pre-sales architecture.",
        )
        security = Job(
            title="Senior Security Architect",
            company="CloudCo",
            location="Dubai, UAE",
            url="https://example.com/security-architect",
            source="linkedin_unified",
            description="Zero trust, IAM, cloud security architecture, and threat modeling.",
        )
        self.assertFalse(is_cybersec_job(generic))
        self.assertTrue(is_cybersec_job(security))

    def test_siem_analyst_routes_to_soc(self):
        job = Job(
            title="SIEM Analyst And Administrator",
            company="SecOpsCo",
            location="Dubai, UAE",
            url="https://example.com/siem",
            source="linkedin_unified",
            description="Splunk SIEM administration, alert triage, and incident response.",
        )
        self.assertTrue(is_cybersec_job(job))
        self.assertEqual(route_job(job), ["gulf", "soc"])

    def test_cybersecurity_intern_routes_to_internships(self):
        job = Job(
            title="Cybersecurity Intern",
            company="CairoSec",
            location="Cairo, Egypt",
            url="https://example.com/cybersecurity-internship",
            source="wuzzuf",
            description="SOC monitoring, SIEM alerts, and incident response training.",
        )
        self.assertEqual(route_job(job), ["egypt", "internships"])

    def test_balanced_pool_caps_linkedin_when_sources_exist(self):
        old_max = config.MAX_JOBS_PER_RUN
        old_threshold = config.SCORE_THRESHOLD
        try:
            config.MAX_JOBS_PER_RUN = 10
            config.SCORE_THRESHOLD = 0
            jobs = []
            for i in range(8):
                jobs.append(Job(
                    title=f"SOC Analyst {i}",
                    company=f"LinkedInCo{i}",
                    location="Cairo, Egypt",
                    url=f"https://www.linkedin.com/jobs/view/44{i:08d}/",
                    source="linkedin_unified",
                    description="SIEM monitoring, threat detection, and incident response.",
                    posted_date=datetime.now() - timedelta(hours=2),
                ))
            for i in range(6):
                jobs.append(Job(
                    title=f"Security Analyst {i}",
                    company=f"WuzzufCo{i}",
                    location="Cairo, Egypt",
                    url=f"https://example.com/wuzzuf-{i}",
                    source="wuzzuf",
                    description="Information security monitoring and vulnerability management.",
                    posted_date=datetime.now() - timedelta(hours=2),
                ))
            pool = _build_final_pool(jobs)
            linkedin_count = sum(1 for job in pool if "linkedin" in job.source)
            self.assertEqual(len(pool), 10)
            self.assertLessEqual(linkedin_count, 5)
        finally:
            config.MAX_JOBS_PER_RUN = old_max
            config.SCORE_THRESHOLD = old_threshold

    def test_balanced_pool_targets_entry_level_when_available(self):
        old_max = config.MAX_JOBS_PER_RUN
        old_threshold = config.SCORE_THRESHOLD
        try:
            config.MAX_JOBS_PER_RUN = 10
            config.SCORE_THRESHOLD = 0
            jobs = []
            for i in range(6):
                jobs.append(Job(
                    title=f"Junior SOC Analyst {i}",
                    company=f"EntryCo{i}",
                    location="Cairo, Egypt",
                    url=f"https://example.com/entry-{i}",
                    source="wuzzuf",
                    description="SIEM monitoring, incident response, and threat analysis.",
                    posted_date=datetime.now() - timedelta(hours=1),
                ))
            for i in range(4):
                jobs.append(Job(
                    title=f"Senior Security Engineer {i}",
                    company=f"SeniorCo{i}",
                    location="Cairo, Egypt",
                    url=f"https://example.com/senior-{i}",
                    source="wuzzuf",
                    description="Information security engineering and vulnerability management.",
                    posted_date=datetime.now() - timedelta(hours=1),
                ))
            pool = _build_final_pool(jobs)
            entry_count = sum(1 for job in pool if "junior" in job.title.lower())
            self.assertEqual(len(pool), 10)
            self.assertGreaterEqual(entry_count, 6)
        finally:
            config.MAX_JOBS_PER_RUN = old_max
            config.SCORE_THRESHOLD = old_threshold

    def test_pool_orders_egypt_then_saudi_then_other_gulf(self):
        old_max = config.MAX_JOBS_PER_RUN
        old_threshold = config.SCORE_THRESHOLD
        try:
            config.MAX_JOBS_PER_RUN = 4
            config.SCORE_THRESHOLD = 0
            jobs = [
                Job("Security Engineer UAE", "A", "Dubai, UAE", "https://example.com/uae", "wuzzuf",
                    description="Security engineering and vulnerability management.",
                    posted_date=datetime.now() - timedelta(hours=1)),
                Job("Security Engineer KSA", "B", "Riyadh, Saudi Arabia", "https://example.com/ksa", "wuzzuf",
                    description="Security engineering and vulnerability management.",
                    posted_date=datetime.now() - timedelta(hours=1)),
                Job("Security Engineer Egypt", "C", "Cairo, Egypt", "https://example.com/eg", "wuzzuf",
                    description="Security engineering and vulnerability management.",
                    posted_date=datetime.now() - timedelta(hours=1)),
                Job("Security Engineer Remote", "D", "Remote", "https://example.com/remote", "wuzzuf",
                    is_remote=True,
                    description="Security engineering and vulnerability management.",
                    posted_date=datetime.now() - timedelta(hours=1)),
            ]
            pool = _build_final_pool(jobs)
            self.assertEqual([job.location for job in pool[:3]], [
                "Cairo, Egypt",
                "Riyadh, Saudi Arabia",
                "Dubai, UAE",
            ])
        finally:
            config.MAX_JOBS_PER_RUN = old_max
            config.SCORE_THRESHOLD = old_threshold


if __name__ == "__main__":
    unittest.main()
