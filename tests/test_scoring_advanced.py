"""
test_scoring_advanced.py
========================
Advanced scoring tests merged from AKM — covers Bayesian freshness,
ML bonus, diversity rerank, and edge cases.
"""
import sys
import os
import math
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Job
from scoring import (
    score_job,
    score_job_int,
    diversity_rerank,
    sort_by_location_priority,
    _freshness_score,
    WEIGHTS,
    phrase_match,
)


def _make_job(**kwargs) -> Job:
    defaults = dict(
        title="Security Analyst",
        company="CyberCorp",
        location="Cairo, Egypt",
        url="https://example.com/job",
        source="linkedin",
    )
    defaults.update(kwargs)
    return Job(**defaults)


class TestPhraseMatch(unittest.TestCase):
    def test_exact_match(self):
        self.assertTrue(phrase_match("soc analyst", "junior soc analyst role"))

    def test_hyphen_variant(self):
        self.assertTrue(phrase_match("cloud security", "cloud-security engineer"))

    def test_no_partial_match(self):
        # 'ids' should not match 'considers'
        self.assertFalse(phrase_match("ids", "considers security posture"))

    def test_slash_variant(self):
        self.assertTrue(phrase_match("cloud security", "cloud/security"))


class TestFreshnessScore(unittest.TestCase):
    def test_brand_new_job(self):
        score, label = _freshness_score(datetime.now() - timedelta(hours=1))
        self.assertGreaterEqual(score, 5)

    def test_day_old(self):
        score, _ = _freshness_score(datetime.now() - timedelta(hours=24))
        self.assertGreater(score, 0)

    def test_very_stale(self):
        score, _ = _freshness_score(datetime.now() - timedelta(days=12))
        self.assertEqual(score, WEIGHTS["fresh_floor"])

    def test_none_date(self):
        score, label = _freshness_score(None)
        self.assertEqual(score, 0)
        self.assertEqual(label, "")


class TestLocationScoring(unittest.TestCase):
    def test_egypt_gets_bonus(self):
        job = _make_job(location="Cairo, Egypt")
        score, reasons = score_job(job)
        self.assertTrue(any("Egypt" in r for r in reasons))

    def test_gulf_gets_bonus(self):
        job = _make_job(location="Dubai, UAE")
        score, reasons = score_job(job)
        self.assertTrue(any("Gulf" in r for r in reasons))

    def test_remote_bonus(self):
        job = _make_job(location="Remote", is_remote=True)
        score, reasons = score_job(job)
        self.assertTrue(any("remote" in r for r in reasons))

    def test_global_onsite_gets_penalty(self):
        job = _make_job(location="London, UK", is_remote=False)
        score, reasons = score_job(job)
        # Should have global onsite penalty applied
        self.assertTrue(any("global" in r.lower() for r in reasons))


class TestTechScoring(unittest.TestCase):
    def test_soc_title_scores_high(self):
        job = _make_job(title="SOC Analyst", location="Cairo, Egypt")
        score, reasons = score_job(job)
        self.assertTrue(any("tech" in r for r in reasons))

    def test_pentest_title_scores_high(self):
        job = _make_job(title="Penetration Tester", location="Cairo, Egypt")
        score, _ = score_job(job)
        self.assertGreater(score, 15)

    def test_non_cyber_title_penalized(self):
        job = _make_job(title="Security Guard", location="Cairo, Egypt")
        score, reasons = score_job(job)
        self.assertTrue(any("non-cyber" in r for r in reasons))


class TestDiversityRerank(unittest.TestCase):
    def test_same_company_penalized(self):
        jobs = [
            (_make_job(company="MegaCorp", title=f"SOC Analyst {i}"), 20, [])
            for i in range(4)
        ]
        reranked = diversity_rerank(jobs, max_per_company=2)
        # Third and fourth MegaCorp jobs should have lower effective score
        scores = [item[1] for item in reranked]
        # Should still be sorted
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_diverse_companies_not_penalized(self):
        jobs = [
            (_make_job(company=f"Company{i}"), 20, [])
            for i in range(5)
        ]
        reranked = diversity_rerank(jobs, max_per_title=10)
        # All scores should remain 20 (no duplicate penalty)
        self.assertTrue(all(item[1] == 20 for item in reranked))


class TestSortByLocationPriority(unittest.TestCase):
    def test_egypt_before_gulf_before_global(self):
        jobs = [
            (_make_job(location="London"), 20),
            (_make_job(location="Dubai, UAE"), 18),
            (_make_job(location="Cairo, Egypt"), 15),
        ]
        sorted_jobs = sort_by_location_priority(jobs)
        locs = [item[0].location for item in sorted_jobs]
        self.assertEqual(locs[0], "Cairo, Egypt")
        self.assertEqual(locs[1], "Dubai, UAE")

    def test_same_region_sorted_by_score(self):
        jobs = [
            (_make_job(location="Cairo, Egypt"), 10),
            (_make_job(location="Alexandria, Egypt"), 25),
        ]
        sorted_jobs = sort_by_location_priority(jobs)
        self.assertEqual(sorted_jobs[0][1], 25)


class TestScoreExplainability(unittest.TestCase):
    def test_score_job_returns_tuple(self):
        job = _make_job()
        result = score_job(job)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], int)
        self.assertIsInstance(result[1], list)

    def test_score_job_int_returns_int(self):
        job = _make_job()
        result = score_job_int(job)
        self.assertIsInstance(result, int)

    def test_no_url_penalty(self):
        job = _make_job(url="")
        _, reasons = score_job(job)
        self.assertTrue(any("no URL" in r for r in reasons))

    def test_clearance_penalty(self):
        job = _make_job(
            description="Must hold TS/SCI clearance to apply for this role."
        )
        _, reasons = score_job(job)
        self.assertTrue(any("clearance" in r for r in reasons))


class TestDocumentationSync(unittest.TestCase):
    def test_readme_weights_match_code(self):
        import pathlib
        import re

        readme = pathlib.Path("README.md").read_text(encoding="utf-8")
        egypt_match = re.search(r"Egypt location\s*\|\s*\*\*\+(\d+)\*\*", readme)
        gulf_match = re.search(r"Gulf location\s*\|\s*\*\*\+(\d+)\*\*", readme)
        self.assertIsNotNone(egypt_match, "README must document Egypt score")
        self.assertIsNotNone(gulf_match, "README must document Gulf score")
        self.assertEqual(int(egypt_match.group(1)), WEIGHTS["egypt"])
        self.assertEqual(int(gulf_match.group(1)), WEIGHTS["gulf"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
