"""
test_ai_filter.py
=================
Tests for the 4-layer hybrid AI filter (AKM contribution).
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_filter import (
    classify_job,
    _check_false_positive,
    _check_modern_title,
    _context_score,
    _has_min_technical_signal,
)


class TestFalsePositiveExclusion(unittest.TestCase):
    def test_security_guard_excluded(self):
        is_cyber, reason = classify_job("Security Guard")
        self.assertFalse(is_cyber)

    def test_sales_engineer_excluded(self):
        is_cyber, reason = classify_job("Sales Engineer", "security products sales")
        self.assertFalse(is_cyber)

    def test_help_desk_excluded(self):
        is_cyber, reason = classify_job("Help Desk Support Specialist")
        self.assertFalse(is_cyber)

    def test_legal_counsel_excluded(self):
        is_cyber, reason = classify_job("Legal Counsel")
        self.assertFalse(is_cyber)


class TestModernTitleDetection(unittest.TestCase):
    def test_trust_and_safety_detected(self):
        result = _check_modern_title("trust and safety analyst")
        self.assertTrue(result)

    def test_zero_trust_engineer_detected(self):
        result = _check_modern_title("zero trust engineer")
        self.assertTrue(result)

    def test_detection_engineer_detected(self):
        result = _check_modern_title("detection engineer")
        self.assertTrue(result)

    def test_purple_team_detected(self):
        result = _check_modern_title("purple teamer")
        self.assertTrue(result)


class TestContextScoring(unittest.TestCase):
    def test_high_context_score(self):
        desc = "Experience with SIEM, EDR, incident response, MITRE ATT&CK, threat hunting"
        score = _context_score("security analyst", desc, "splunk soc")
        self.assertGreaterEqual(score, 3)

    def test_low_context_score(self):
        score = _context_score("software engineer", "build mobile apps", "flutter react")
        self.assertEqual(score, 0)


class TestClassifyJob(unittest.TestCase):
    def test_soc_analyst_accepted(self):
        is_cyber, reason = classify_job(
            "SOC Analyst",
            "Monitor SIEM alerts, incident response, threat hunting with Splunk"
        )
        # Should be True or None (borderline), NOT False
        self.assertNotEqual(is_cyber, False)

    def test_physical_security_rejected(self):
        is_cyber, reason = classify_job(
            "Building Security Officer",
            "Guard the premises and check IDs at the gate"
        )
        self.assertFalse(is_cyber)

    def test_appsec_engineer_accepted(self):
        is_cyber, reason = classify_job(
            "Application Security Engineer",
            "Perform SAST, DAST, code review, OWASP top 10, DevSecOps"
        )
        self.assertNotEqual(is_cyber, False)

    def test_cloud_infra_without_security_rejected(self):
        is_cyber, reason = classify_job(
            "Cloud Infrastructure Engineer",
            "Manage AWS EC2, RDS, load balancers, Terraform deployments"
        )
        self.assertFalse(is_cyber)

    def test_arabic_title_detected(self):
        is_cyber, reason = classify_job("مهندس أمن سيبراني", "اختبار اختراق وأمن شبكات")
        self.assertNotEqual(is_cyber, False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
