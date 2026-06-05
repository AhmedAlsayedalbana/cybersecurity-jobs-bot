"""
tests/test_migration_v2.py
===========================
Regression and unit tests for the Bot0 → Bot1 migration.

Run with:
    PYTHONDONTWRITEBYTECODE=1 ML_FILTER_ENABLED=0 python -m unittest tests.test_migration_v2

Test coverage:
    A. intelligence.geo — classify_geo, is_remote_job
    B. intelligence.seniority — classify_level, is_entry_level
    C. intelligence.domain — classify_domain
    D. intelligence.intent — classify_cyber_intent, hard_reject_reason
    E. intelligence.dedupe — job_fingerprint, fuzzy_match, are_duplicate_jobs
    F. intelligence.pool_builder — build_final_pool ratio enforcement
    G. Backward-compat — job_intelligence.py facade exports
    H. Source schema — new connectors emit correct field shapes
"""

from __future__ import annotations

import sys
import types
import unittest
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

# ---------------------------------------------------------------------------
# Minimal Job stub (avoids importing the full models.py + DB layer in tests)
# ---------------------------------------------------------------------------

@dataclass
class _Job:
    title: str = ""
    company: str = ""
    location: str = ""
    url: str = "https://example.com/job/1"
    source: str = "test"
    description: str = ""
    tags: list = field(default_factory=list)
    is_remote: bool = False
    job_type: str = ""
    salary: str = ""
    posted_date: Optional[datetime] = None
    geo_hint: str = ""
    original_source: str = ""
    source_key: str = ""
    origin_priority: int = 999
    dedup_key: str = ""


def _job(**kwargs) -> _Job:
    return _Job(**kwargs)


# ---------------------------------------------------------------------------
# A. Geo classification
# ---------------------------------------------------------------------------

class TestGeoClassification(unittest.TestCase):

    def _geo(self, **kwargs) -> str:
        from intelligence.geo import classify_geo
        return classify_geo(_job(**kwargs))

    def test_egypt_location(self):
        self.assertEqual(self._geo(location="Cairo, Egypt"), "egypt")

    def test_egypt_arabic_location(self):
        self.assertEqual(self._geo(location="القاهرة، مصر"), "egypt")

    def test_ksa_location(self):
        self.assertEqual(self._geo(location="Riyadh, Saudi Arabia"), "ksa")

    def test_uae_location(self):
        self.assertEqual(self._geo(location="Dubai, UAE"), "gulf_other")

    def test_remote_flag(self):
        self.assertEqual(self._geo(is_remote=True), "remote")

    def test_remote_pattern_in_location(self):
        self.assertEqual(self._geo(location="Remote / Worldwide"), "remote")

    def test_global_fallback(self):
        self.assertEqual(self._geo(location="London, UK"), "global")

    def test_geo_hint_egypt(self):
        self.assertEqual(self._geo(geo_hint="egypt", location=""), "egypt")

    def test_geo_hint_gulf_with_ksa_tag(self):
        from intelligence.geo import classify_geo
        job = _job(geo_hint="gulf", tags=["saudi", "riyadh"])
        self.assertEqual(classify_geo(job), "ksa")

    def test_description_fallback_egypt(self):
        self.assertEqual(
            self._geo(location="", description="Open to candidates in Egypt or remotely"),
            "egypt",
        )


# ---------------------------------------------------------------------------
# B. Seniority classification
# ---------------------------------------------------------------------------

class TestSeniorityClassification(unittest.TestCase):

    def _level(self, **kwargs) -> str:
        from intelligence.seniority import classify_level
        return classify_level(_job(**kwargs))

    def test_intern_title(self):
        self.assertEqual(self._level(title="Cybersecurity Intern"), "entry")

    def test_entry_level_title(self):
        self.assertEqual(self._level(title="Entry-Level SOC Analyst"), "entry")

    def test_junior_title(self):
        self.assertEqual(self._level(title="Junior Security Engineer"), "entry")

    def test_senior_title(self):
        self.assertEqual(self._level(title="Senior Penetration Tester"), "senior")

    def test_lead_title(self):
        self.assertEqual(self._level(title="Lead Security Architect"), "senior")

    def test_mid_title(self):
        self.assertEqual(self._level(title="Mid-Level GRC Analyst"), "mid")

    def test_open_fallback(self):
        self.assertEqual(self._level(title="Security Engineer"), "open")


# ---------------------------------------------------------------------------
# C. Domain classification
# ---------------------------------------------------------------------------

class TestDomainClassification(unittest.TestCase):

    def _domain(self, **kwargs):
        from intelligence.domain import classify_domain
        return classify_domain(_job(**kwargs))

    def test_pentest(self):
        self.assertEqual(self._domain(title="Penetration Tester"), "pentest")

    def test_soc(self):
        self.assertEqual(self._domain(title="SOC Analyst Tier 2"), "soc")

    def test_grc(self):
        self.assertEqual(self._domain(title="GRC Analyst ISO 27001"), "grc")

    def test_cloudsec(self):
        self.assertEqual(self._domain(title="Cloud Security Engineer"), "cloudsec")

    def test_appsec(self):
        self.assertEqual(self._domain(title="Application Security Engineer"), "appsec")

    def test_internship(self):
        d = self._domain(title="Cybersecurity Intern", description="cybersecurity soc malware")
        self.assertEqual(d, "internships")

    def test_none_for_generic(self):
        self.assertIsNone(self._domain(title="Software Engineer"))


# ---------------------------------------------------------------------------
# D. Cyber intent classification & hard rejects
# ---------------------------------------------------------------------------

class TestCyberIntent(unittest.TestCase):

    def _intent(self, **kwargs):
        from intelligence.intent import classify_cyber_intent
        return classify_cyber_intent(_job(**kwargs), use_llm=False)

    def _reject(self, **kwargs):
        from intelligence.intent import hard_reject_reason
        return hard_reject_reason(_job(**kwargs))

    # Accept cases
    def test_accept_pentest_title(self):
        d = self._intent(title="Penetration Tester", description="OSCP ethical hacking red team")
        self.assertTrue(d.accept)

    def test_accept_soc_analyst(self):
        d = self._intent(title="SOC Analyst", description="siem splunk incident response blue team")
        self.assertTrue(d.accept)

    def test_accept_broad_cyber_title(self):
        d = self._intent(title="Cybersecurity Manager")
        self.assertTrue(d.accept)

    def test_accept_v51_false_negative_titles(self):
        titles = [
            "IT Security Analyst",
            "SASE Subject Matter Expert",
            "DNS & Endpoint Security Advisor",
            "Security Technical Architect",
            "Product Security Engineering Manager",
            "Cleared Vulnerability Research Engineer",
            "Manager, Engineering (Identity and Access Management)",
        ]
        for title in titles:
            with self.subTest(title=title):
                d = self._intent(title=title)
                self.assertTrue(d.accept, d.reason_code)

    # Reject cases
    def test_reject_sales(self):
        d = self._intent(title="Account Executive - Cybersecurity Sales")
        self.assertFalse(d.accept)

    def test_reject_physical_security(self):
        d = self._intent(title="Security Guard Night Shift")
        self.assertFalse(d.accept)

    def test_reject_credit_risk(self):
        d = self._intent(title="Credit Risk Analyst")
        self.assertFalse(d.accept)

    def test_reject_generic_support(self):
        d = self._intent(title="Help Desk Support Specialist")
        self.assertFalse(d.accept)

    def test_reject_software_engineer(self):
        d = self._intent(title="Software Engineer Backend Python")
        self.assertFalse(d.accept)

    def test_hard_reject_security_guard(self):
        self.assertIsNotNone(self._reject(title="Security Officer Warehouse"))

    def test_hard_reject_returns_none_for_cyber(self):
        self.assertIsNone(self._reject(title="SOC Analyst"))


# ---------------------------------------------------------------------------
# E. Deduplication helpers
# ---------------------------------------------------------------------------

class TestDedupeHelpers(unittest.TestCase):

    def test_exact_url_match(self):
        from intelligence.dedupe import are_duplicate_jobs
        a = _job(url="https://example.com/jobs/123", title="SOC Analyst", company="Acme")
        b = _job(url="https://example.com/jobs/123", title="SOC Analyst", company="Acme")
        self.assertTrue(are_duplicate_jobs(a, b))

    def test_url_tracking_param_stripped(self):
        from intelligence.dedupe import normalize_url
        u1 = normalize_url("https://jobs.example.com/123?utm_source=linkedin&trk=abc")
        u2 = normalize_url("https://jobs.example.com/123")
        self.assertEqual(u1, u2)

    def test_fuzzy_match_same_job_different_source(self):
        from intelligence.dedupe import are_duplicate_jobs
        a = _job(title="Senior SOC Analyst",  company="Acme Corp", location="Cairo, Egypt")
        b = _job(title="Senior SOC Analyst",  company="Acme",      location="Cairo")
        self.assertTrue(are_duplicate_jobs(a, b))

    def test_no_duplicate_different_roles(self):
        from intelligence.dedupe import are_duplicate_jobs
        a = _job(title="Penetration Tester", company="Sec Co",  location="Dubai")
        b = _job(title="GRC Analyst",        company="Sec Co",  location="Dubai")
        self.assertFalse(are_duplicate_jobs(a, b))

    def test_fingerprint_stable(self):
        from intelligence.dedupe import job_fingerprint
        j = _job(title="Cloud Security Engineer - 3", company="Big Corp Ltd", location="Riyadh, Saudi Arabia")
        fp = job_fingerprint(j)
        self.assertIn("cloud security engineer", fp)
        self.assertNotIn("3", fp)   # trailing number stripped


# ---------------------------------------------------------------------------
# F. Pool builder ratio enforcement
# ---------------------------------------------------------------------------

class TestPoolBuilder(unittest.TestCase):

    def _make_jobs(self, n_linkedin: int, n_other: int, n_entry: int) -> list:
        jobs = []
        for i in range(n_linkedin):
            jobs.append(_job(
                title="SOC Analyst",
                company=f"LinkedIn Co {i}",
                location="Egypt",
                url=f"https://linkedin.com/jobs/{i}",
                source="linkedin_unified",
                source_key="linkedin_unified",
                description="cybersecurity soc siem blue team incident response",
            ))
        for i in range(n_other):
            jobs.append(_job(
                title="Security Engineer",
                company=f"Other Co {i}",
                location="Egypt",
                url=f"https://wuzzuf.net/jobs/{i}",
                source="wuzzuf",
                source_key="wuzzuf",
                description="cybersecurity network security firewall palo alto",
            ))
        for i in range(n_entry):
            jobs.append(_job(
                title="Cybersecurity Intern",
                company=f"Intern Co {i}",
                location="Remote / Worldwide",
                url=f"https://example.com/intern/{i}",
                source="greenhouse_expanded",
                source_key="greenhouse_expanded",
                description="cybersecurity intern soc malware internship entry-level",
                is_remote=True,
            ))
        return jobs

    def _score(self, job) -> int:
        """Simple scoring stub: always returns 20 (above threshold=14)."""
        return 20

    def test_non_linkedin_floor(self):
        """Non-LinkedIn sources must fill NON_LINKEDIN_POOL_FLOOR_RATIO of pool."""
        import config
        from intelligence.pool_builder import build_final_pool

        jobs = self._make_jobs(n_linkedin=50, n_other=20, n_entry=0)
        pool = build_final_pool(jobs, self._score)
        non_li = sum(1 for j in pool if "linkedin" not in j.source)
        floor = int(len(pool) * config.NON_LINKEDIN_POOL_FLOOR_RATIO)
        self.assertGreaterEqual(non_li, floor)

    def test_linkedin_cap_enforced(self):
        """LinkedIn jobs must not exceed LINKEDIN_POOL_CAP_RATIO of pool."""
        import config
        from intelligence.pool_builder import build_final_pool

        jobs = self._make_jobs(n_linkedin=100, n_other=5, n_entry=0)
        pool = build_final_pool(jobs, self._score)
        li_count = sum(1 for j in pool if "linkedin" in j.source)
        cap = round(len(pool) * config.LINKEDIN_POOL_CAP_RATIO)
        self.assertLessEqual(li_count, cap + 1)   # ±1 rounding tolerance

    def test_stale_jobs_excluded(self):
        """Jobs older than MAX_JOB_AGE_DAYS must be excluded."""
        import config
        from intelligence.pool_builder import build_final_pool

        old_date = datetime.now() - timedelta(days=config.MAX_JOB_AGE_DAYS + 1)
        stale = _job(
            title="SOC Analyst stale",
            description="cybersecurity soc siem",
            url="https://example.com/stale",
            posted_date=old_date,
        )
        fresh = _job(
            title="SOC Analyst fresh",
            description="cybersecurity soc siem",
            url="https://example.com/fresh",
            posted_date=datetime.now(),
        )
        pool = build_final_pool([stale, fresh], self._score)
        urls = [j.url for j in pool]
        self.assertNotIn("https://example.com/stale", urls)
        self.assertIn("https://example.com/fresh", urls)

    def test_min_pool_size_relaxes_linkedin_cap(self):
        import config
        from intelligence.pool_builder import build_final_pool

        jobs = self._make_jobs(n_linkedin=config.MIN_POOL_SIZE, n_other=0, n_entry=0)
        pool = build_final_pool(jobs, self._score)
        self.assertGreaterEqual(len(pool), config.MIN_POOL_SIZE)


# ---------------------------------------------------------------------------
# G. Backward-compat facade (job_intelligence.py)
# ---------------------------------------------------------------------------

class TestBackwardCompat(unittest.TestCase):

    def test_classify_geo_import(self):
        from job_intelligence import classify_geo
        result = classify_geo(_job(location="Cairo, Egypt"))
        self.assertEqual(result, "egypt")

    def test_classify_cyber_intent_import(self):
        from job_intelligence import classify_cyber_intent
        d = classify_cyber_intent(_job(title="SOC Analyst", description="siem soc blue team"), use_llm=False)
        self.assertTrue(d.accept)

    def test_is_linkedin_job_import(self):
        from job_intelligence import is_linkedin_job
        li = _job(source="linkedin_unified", source_key="linkedin_unified")
        other = _job(source="wuzzuf", source_key="wuzzuf")
        self.assertTrue(is_linkedin_job(li))
        self.assertFalse(is_linkedin_job(other))

    def test_is_entry_level_import(self):
        from job_intelligence import is_entry_level
        self.assertTrue(is_entry_level(_job(title="Cybersecurity Intern")))
        self.assertFalse(is_entry_level(_job(title="Senior Security Engineer")))


# ---------------------------------------------------------------------------
# H. Source schema validation
# ---------------------------------------------------------------------------

class TestSourceSchema(unittest.TestCase):
    """Verify new connectors return objects with required fields."""

    REQUIRED_FIELDS = [
        "title", "company", "location", "url", "source",
        "description", "is_remote",
    ]

    def _check_schema(self, jobs: list, source_name: str):
        self.assertIsInstance(jobs, list, f"{source_name}: must return list")
        for job in jobs[:5]:   # check first 5 only
            for field_name in self.REQUIRED_FIELDS:
                self.assertTrue(
                    hasattr(job, field_name),
                    f"{source_name}: job missing field '{field_name}'",
                )

    def test_greenhouse_expanded_schema(self):
        """Stub: verify field shape without hitting the network."""
        from sources.greenhouse_expanded import _fetch_greenhouse_board, BoardEntry
        # Create a mock that returns a synthetic Greenhouse API response
        import unittest.mock as mock

        fake_data = {
            "jobs": [
                {
                    "title": "Security Engineer",
                    "absolute_url": "https://boards.greenhouse.io/stripe/jobs/999",
                    "location": {"name": "Remote"},
                    "updated_at": "2026-05-28T10:00:00Z",
                }
            ]
        }
        with mock.patch("sources.greenhouse_expanded.get_json", return_value=fake_data):
            jobs = _fetch_greenhouse_board(BoardEntry("stripe", "Stripe"))
        self._check_schema(jobs, "greenhouse_expanded")

    def test_gulf_monster_schema(self):
        """Stub: verify Monster Gulf RSS parser returns correct schema."""
        from sources.gulf_monster import _FeedSpec, _fetch_feed

        fake_rss = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Cybersecurity Analyst</title>
    <link>https://www.monstergulf.com/jobs/12345</link>
    <description>Security analyst role in Dubai</description>
    <pubDate>Wed, 28 May 2026 10:00:00 +0000</pubDate>
  </item>
</channel></rss>"""

        import unittest.mock as mock
        spec = _FeedSpec("https://test.example.com/rss", "gulf")
        with mock.patch("sources.gulf_monster.get_text", return_value=fake_rss):
            jobs = _fetch_feed(spec, set())
        self._check_schema(jobs, "gulf_monster")

    def test_jsearch_enhanced_schema(self):
        """Stub: verify JSearch parser emits correct schema."""
        from sources.jsearch_enhanced import _items_to_jobs, _SearchSpec

        fake_items = [
            {
                "job_id": "abc123",
                "job_title": "SOC Analyst",
                "employer_name": "SecureCo",
                "job_city": "Cairo",
                "job_country": "Egypt",
                "job_apply_link": "https://linkedin.com/jobs/111",
                "job_description": "Security operations center analyst",
                "job_is_remote": False,
                "job_employment_type": "FULLTIME",
                "apply_options": [],
            }
        ]
        jobs = _items_to_jobs(fake_items, "egypt")
        self._check_schema(jobs, "jsearch_enhanced")


if __name__ == "__main__":
    unittest.main(verbosity=2)
