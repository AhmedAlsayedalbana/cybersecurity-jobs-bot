"""No-third-party regression checks for delivery precision."""

from __future__ import annotations

from datetime import datetime, timedelta
import unittest

from intelligence.domain import has_channel_evidence
from intelligence.geo import classify_delivery_geo, classify_geo, is_remote_job
from intelligence.pool_builder import build_final_pool, freshness_sort_key
from models import CyberVerdict, Job, classify_jobs, passes_geo_filter
from telegram_sender import _is_telegram_eligible, route_job


def _job(title="Cybersecurity Engineer", *, location="Cairo, Egypt", description="Build security controls and threat detection.", is_remote=False, geo_hint="", posted_date=None):
    job = Job(
        title=title,
        company="Acme",
        location=location,
        url=f"https://example.com/{title.lower().replace(' ', '-')}-{location.lower().replace(' ', '-')}",
        source="linkedin_unified",
        source_key="linkedin_unified",
        description=description,
        is_remote=is_remote,
        geo_hint=geo_hint,
        posted_date=posted_date or datetime.now(),
    )
    job.cyber_verdict = CyberVerdict.CONFIRMED.value
    return job


class DeliveryPrecisionTests(unittest.TestCase):
    def test_remote_beats_egypt_employer_location(self):
        job = _job(title="Cyber Security Analyst (Remote)", location="Cairo, Egypt")
        self.assertTrue(is_remote_job(job))
        self.assertEqual(classify_geo(job), "remote")
        self.assertIn("remote", route_job(job))
        self.assertNotIn("egypt", route_job(job))

    def test_global_physical_job_cannot_borrow_query_location(self):
        job = _job(location="London, United Kingdom", geo_hint="egypt")
        self.assertEqual(classify_geo(job), "global")
        self.assertFalse(passes_geo_filter(job))
        self.assertFalse(_is_telegram_eligible(job))

    def test_hybrid_global_job_is_not_remote(self):
        job = _job(location="Berlin, Germany", is_remote=True)
        job.job_type = "Hybrid"
        self.assertFalse(is_remote_job(job))
        self.assertEqual(classify_geo(job), "global")
        self.assertFalse(passes_geo_filter(job))

    def test_unknown_physical_location_cannot_use_query_hint(self):
        job = _job(location="Not specified", geo_hint="arab")
        self.assertEqual(classify_geo(job), "arab")
        self.assertEqual(classify_delivery_geo(job), "global")
        self.assertFalse(passes_geo_filter(job))

    def test_training_post_does_not_become_soc_vacancy(self):
        job = _job(
            title="Undergrad Cybersecurity Instructor",
            location="Riyadh, Saudi Arabia",
            description="Teach SOC analysis, SIEM monitoring, threat hunting, and incident response.",
        )
        self.assertFalse(has_channel_evidence(job, "soc"))
        self.assertEqual(route_job(job), ["gulf"])

    def test_freshness_precedes_source_rank(self):
        import config

        now = datetime.now()
        old_linkedin = _job(posted_date=now - timedelta(hours=20))
        old_linkedin.origin_priority = 10
        fresh_board = _job(posted_date=now - timedelta(minutes=15))
        fresh_board.source = fresh_board.source_key = "wuzzuf"
        fresh_board.origin_priority = 90
        self.assertLess(freshness_sort_key(fresh_board, now=now), freshness_sort_key(old_linkedin, now=now))

        saved = (config.MAX_JOBS_PER_RUN, config.SCORE_THRESHOLD, config.NON_LINKEDIN_POOL_FLOOR_RATIO, config.ENTRY_LEVEL_TARGET_RATIO, config.LINKEDIN_POOL_CAP_RATIO)
        try:
            config.MAX_JOBS_PER_RUN, config.SCORE_THRESHOLD = 2, 0
            config.NON_LINKEDIN_POOL_FLOOR_RATIO = 0.0
            config.ENTRY_LEVEL_TARGET_RATIO = 0.0
            config.LINKEDIN_POOL_CAP_RATIO = 1.0
            pool = build_final_pool([old_linkedin, fresh_board], score_fn=lambda _: 20)
        finally:
            (config.MAX_JOBS_PER_RUN, config.SCORE_THRESHOLD, config.NON_LINKEDIN_POOL_FLOOR_RATIO, config.ENTRY_LEVEL_TARGET_RATIO, config.LINKEDIN_POOL_CAP_RATIO) = saved
        self.assertIs(pool[0], fresh_board)

    def test_fast_gate_blocks_generic_cloud_commercial_role_before_ml(self):
        import config

        job = _job(
            title="Deal Desk Analyst",
            description="Negotiate cloud contracts using AWS and Python.",
        )
        job.source = job.source_key = "test"
        saved = config.ML_FILTER_ENABLED
        try:
            config.ML_FILTER_ENABLED = False
            accepted, rejected = classify_jobs([job])
        finally:
            config.ML_FILTER_ENABLED = saved

        self.assertEqual(accepted, [])
        self.assertEqual(rejected, [job])
        self.assertEqual(job.filter_reason, "reject_fast_no_cyber_signal")


if __name__ == "__main__":
    unittest.main()
