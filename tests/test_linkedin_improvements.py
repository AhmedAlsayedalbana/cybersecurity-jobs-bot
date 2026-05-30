import importlib
import os
import inspect
import unittest

import config
from linkedin_url_utils import (
    extract_linkedin_post_id,
    is_valid_linkedin_canonical,
    normalize_linkedin_url,
)
from models import Job
from sources import linkedin_hr_posts_scraper as hr_scraper
from sources import http_utils


class LinkedInUrlNormalizationTests(unittest.TestCase):
    def test_jobs_view_url_strips_tracking(self):
        raw = "https://www.linkedin.com/jobs/view/1234567890/?trk=foo#fragment"
        self.assertEqual(normalize_linkedin_url(raw), "https://www.linkedin.com/jobs/view/1234567890/")

    def test_mobile_url_is_normalized(self):
        raw = "https://m.linkedin.com/jobs/view/9988776655/?utm_source=test"
        self.assertEqual(normalize_linkedin_url(raw), "https://www.linkedin.com/jobs/view/9988776655/")

    def test_collections_url_promotes_current_job_id(self):
        raw = (
            "https://www.linkedin.com/jobs/collections/recommended/"
            "?currentJobId=777888999&trackingId=abc"
        )
        self.assertEqual(normalize_linkedin_url(raw), "https://www.linkedin.com/jobs/view/777888999/")

    def test_post_and_activity_urls_remain_canonical(self):
        post = "https://www.linkedin.com/posts/someone_soc-analyst-activity-7341234567890123456-abc?trk=foo"
        activity = "https://www.linkedin.com/feed/update/urn:li:activity:7341234567890123456/?utm=bar"
        self.assertTrue(is_valid_linkedin_canonical(normalize_linkedin_url(post)))
        self.assertTrue(is_valid_linkedin_canonical(normalize_linkedin_url(activity)))

    def test_invalid_linkedin_path_rejected(self):
        raw = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=soc"
        self.assertFalse(is_valid_linkedin_canonical(normalize_linkedin_url(raw)))

    def test_job_url_id_prefers_linkedin_ids(self):
        job = Job(
            title="SOC Analyst",
            company="Acme",
            location="Cairo, Egypt",
            url="https://www.linkedin.com/jobs/view/1234567890/?trk=foo",
            source="linkedin",
        )
        self.assertEqual(job.url_id, "li_job_1234567890")

        post_job = Job(
            title="SOC Analyst",
            company="Acme",
            location="Cairo, Egypt",
            url="https://www.linkedin.com/feed/update/urn:li:activity:7341234567890123456/?foo=bar",
            source="linkedin_hr_post",
        )
        self.assertEqual(post_job.url_id, "li_post_7341234567890123456")
        self.assertEqual(extract_linkedin_post_id(post_job.canonical_url), "7341234567890123456")


class HrConfidenceTests(unittest.TestCase):
    def test_high_confidence_post_passes_thresholds(self):
        hiring_score, confidence, _ = hr_scraper._compute_confidence(
            title="SOC Analyst",
            raw_text=(
                "We are hiring SOC analyst in Cairo, Egypt. Urgent hiring. "
                "Send CV to sec@example.com and WhatsApp +201001234567."
            ),
            location="Egypt",
            apply_info={"email": "sec@example.com", "whatsapp": "+201001234567"},
            source_backend="google_cse",
            company="Acme Security",
        )
        self.assertGreaterEqual(hiring_score, config.HR_HIRING_THRESHOLD)
        self.assertGreaterEqual(confidence, config.HR_CONFIDENCE_THRESHOLD)

    def test_low_signal_post_fails_thresholds(self):
        hiring_score, confidence, _ = hr_scraper._compute_confidence(
            title="Security Role",
            raw_text="General update about our office culture and events.",
            location="Egypt",
            apply_info={},
            source_backend="duckduckgo",
            company="Unknown",
        )
        self.assertLess(hiring_score, config.HR_HIRING_THRESHOLD)
        self.assertLess(confidence, config.HR_CONFIDENCE_THRESHOLD)


class DirectBypassTests(unittest.TestCase):
    def test_direct_hosts_bypass_proxy_pool(self):
        self.assertTrue(http_utils._is_direct_url("https://serpapi.com/search"))
        self.assertTrue(http_utils._is_direct_url("https://www.googleapis.com/customsearch/v1"))
        self.assertTrue(http_utils._is_direct_url("https://api.rapidapi.com/some-endpoint"))


class SourceRegistryTests(unittest.TestCase):
    def test_priority_registry_contains_linkedin_unified(self):
        import sources
        importlib.reload(sources)
        names = [name for name, _ in sources.ALL_FETCHERS]
        self.assertIn("LinkedIn Unified", names)

    def test_linkedin_source_is_async_fetcher(self):
        import sources
        importlib.reload(sources)
        mapping = {name: fn for name, fn in sources.ALL_FETCHERS}
        self.assertIn("LinkedIn Unified", mapping)
        self.assertTrue(inspect.iscoroutinefunction(mapping["LinkedIn Unified"]))

    def test_registry_sources_are_no_login(self):
        from sources.source_registry import get_source_specs
        specs = get_source_specs()
        self.assertTrue(all(not s.requires_login for s in specs))


if __name__ == "__main__":
    unittest.main()
