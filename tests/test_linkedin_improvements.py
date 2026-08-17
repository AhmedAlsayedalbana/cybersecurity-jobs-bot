import importlib
import os
import inspect
import unittest
from unittest.mock import patch

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
    def test_hr_search_uses_public_fallback_after_api_backends_return_nothing(self):
        post_url = "https://www.linkedin.com/feed/update/urn:li:activity:7341234567890123456/"
        bing_html = f'<html><li class="b_algo"><a href="{post_url}">Hiring</a></li></html>'
        with patch.object(hr_scraper, "GOOGLE_CSE_API_KEY", ""), \
             patch.object(hr_scraper, "GOOGLE_CSE_CX", ""), \
             patch.object(hr_scraper, "SERPAPI_KEY", ""), \
             patch.object(hr_scraper, "get_text", return_value=bing_html):
            found = hr_scraper._search_urls('site:linkedin.com/posts "#hiring" cybersecurity Egypt')

        self.assertEqual(found, [(normalize_linkedin_url(post_url), "bing_html")])

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
            source_backend="serpapi",
            company="Unknown",
        )
        self.assertLess(hiring_score, config.HR_HIRING_THRESHOLD)
        self.assertLess(confidence, config.HR_CONFIDENCE_THRESHOLD)

    def test_hr_post_accepts_arab_location_with_cv_email(self):
        post_url = "https://www.linkedin.com/feed/update/urn:li:activity:7341234567890123456/"
        html = (
            '<html><meta property="og:description" content="We are hiring SOC Analyst in Amman, Jordan. '
            'Send CV to hiring@arabsec.example.com."><meta property="article:published_time" '
            'content="2026-08-15T09:00:00Z">' + (" " * 600) + "</html>"
        )
        with patch.object(hr_scraper, "get_text", return_value=html):
            post = hr_scraper._scrape_linkedin_post(post_url, "google_cse")

        self.assertIsNotNone(post)
        assert post is not None
        self.assertEqual(post["geo_hint"], "arab")
        self.assertFalse(post["is_remote"])
        self.assertEqual(post["apply_info"]["email"], "hiring@arabsec.example.com")

    def test_hr_post_rejects_a_post_without_application_method(self):
        post_url = "https://www.linkedin.com/feed/update/urn:li:activity:7341234567890123456/"
        html = (
            '<html><meta property="og:description" content="We are hiring SOC Analyst in Cairo, Egypt. '
            'Urgent hiring for our security team."><meta property="article:published_time" '
            'content="2026-08-15T09:00:00Z">' + (" " * 600) + "</html>"
        )
        with patch.object(hr_scraper, "get_text", return_value=html):
            post = hr_scraper._scrape_linkedin_post(post_url, "google_cse")

        self.assertIsNone(post)

    def test_hr_search_plan_rotates_arab_locations(self):
        first = hr_scraper._search_queries(rotation_slot=0)
        second = hr_scraper._search_queries(rotation_slot=1)

        # v61: native queries = 10 Egypt + 3 Arab + 1 Remote = 14
        self.assertGreaterEqual(len(first), 10)
        # Arab locations should rotate between runs
        first_locs = [q for q in first if "Saudi Arabia" in q or "Kuwait" in q]
        second_locs = [q for q in second if "Saudi Arabia" in q or "Kuwait" in q]
        self.assertTrue(any("SOC" in q for q in first))
        self.assertTrue(any("penetration tester" in q.lower() for q in first))

    def test_linkedin_budget_reserves_hr_post_finalization_window(self):
        # v61: budget is now 1800 + 90 = 1890
        self.assertEqual(hr_scraper.config.LINKEDIN_TOTAL_BUDGET_SECONDS, 1890)
        from sources.linkedin_unified import _jobs_budget_seconds

        self.assertEqual(_jobs_budget_seconds(), 1795)

    def test_hr_card_links_to_the_original_post_not_the_embedded_apply_link(self):
        from telegram_sender import format_hr_post_message

        post_url = "https://www.linkedin.com/feed/update/urn:li:activity:7341234567890123456/"
        job = Job(
            title="SOC Analyst",
            company="ArabSec",
            location="Amman, Jordan",
            url=post_url,
            source="linkedin_hr_post",
            source_key="linkedin_hr_posts",
            content_type="hr_post",
            description="EMAIL:cv@arabsec.example.com APPLY_LINK:https://apply.example.com/soc",
        )
        message = format_hr_post_message(job)

        self.assertIn(f'<a href="{job.canonical_url}">🚀 Open Original Post →</a>', message)
        self.assertNotIn('href="https://apply.example.com/soc"', message)


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
