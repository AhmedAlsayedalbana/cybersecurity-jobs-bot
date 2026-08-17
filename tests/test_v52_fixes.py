"""
tests/test_v52_fixes.py — Regression tests for every bug fixed in v52.

Each test is named after the exact job title that was falsely rejected or
falsely rescued in the production run logged on 2026-06-02.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_job(title: str, description: str = "", location: str = "remote",
              company: str = "Acme Security Inc.", url: str = "https://example.com/job/1"):
    """Return a minimal mock Job that the filter functions accept."""
    from models import Job
    j = Job(
        title=title,
        company=company,
        location=location,
        url=url,
        description=description,
        source="test",
    )
    return j


def _accept(title: str, description: str = "") -> bool:
    from intelligence.intent import classify_cyber_intent
    job = _make_job(title, description)
    result = classify_cyber_intent(job)
    return result.accept


def _reject_reason(title: str, description: str = "") -> str | None:
    from intelligence.intent import hard_reject_reason
    return hard_reject_reason(_make_job(title, description))


# ===========================================================================
# BUG 1 — Missing standalone cybersec titles in DOMAIN_PATTERNS
# ===========================================================================

class TestMissingStandaloneTitles:
    """
    These common job titles were falsely rejected in production with
    reject_no_cyber_signal or reject_borderline_without_strong_anchor.
    All should now be accepted directly via domain classification.
    """

    def test_security_analyst_accepted(self):
        """'Security Analyst' is the most common cybersec job title — must pass."""
        assert _accept("Security Analyst"), "Security Analyst must not be rejected"

    def test_cybersecurity_analyst_accepted(self):
        assert _accept("Cybersecurity Analyst")

    def test_cyber_analyst_accepted(self):
        assert _accept("Cyber Analyst")

    def test_information_security_analyst_accepted(self):
        assert _accept("Information Security Analyst")

    def test_security_researcher_accepted(self):
        """Production log: ' AI Security Researcher' → reject_borderline_without_strong_anchor"""
        assert _accept("Security Researcher")

    def test_ai_security_researcher_accepted(self):
        assert _accept("AI Security Researcher")

    def test_ml_security_researcher_accepted(self):
        assert _accept("ML Security Researcher")

    def test_threat_intelligence_researcher_accepted(self):
        """
        Production log: 'Threat Intelligence Researcher (Cloud)' → reject_no_cyber_signal.
        This was a double bug: (a) title not in DOMAIN_PATTERNS, and (b) 'threat'
        not in the borderline-detection word list.
        """
        assert _accept("Threat Intelligence Researcher (Cloud)")
        assert _accept("Threat Intelligence Researcher")

    def test_threat_researcher_accepted(self):
        assert _accept("Threat Researcher")

    def test_phishing_analyst_accepted(self):
        """
        'Phishing Analyst-SkillBridge Intern' logged as reject_no_cyber_signal.
        'phishing' was not in domain patterns OR borderline detection.
        """
        assert _accept("Phishing Analyst")
        assert _accept("Phishing Analyst-SkillBridge Intern")


# ===========================================================================
# BUG 2 — GENERIC_TECH_REJECTS false positives
# ===========================================================================

class TestGenericTechRejectsFalsePositives:
    """
    Titles that contain a generic tech term (e.g. 'program manager', 'supply
    chain') but in a clearly security-related context were wrongly blocked.
    """

    def test_security_program_manager_not_hard_rejected(self):
        """
        Production: 'Security Program Manager' → reject_generic_tech_title at p=0.96.
        The CYBER_TITLE_OVERRIDE_PATTERNS now includes 'security program'.
        """
        assert _reject_reason("Security Program Manager") is None, (
            "Security Program Manager must not be hard-rejected"
        )

    def test_security_program_manager_accepted_end_to_end(self):
        assert _accept("Security Program Manager")

    def test_cybersecurity_program_manager_accepted(self):
        assert _accept("Cybersecurity Program Manager")

    def test_security_project_manager_accepted(self):
        assert _accept("Security Project Manager")

    def test_software_supply_chain_security_not_hard_rejected(self):
        """
        Production: 'Engineering Manager, Software Supply Chain Security:
        Pipeline Security' → reject_generic_tech_title.
        'supply chain' alone was too broad in GENERIC_TECH_REJECTS.
        """
        title = "Engineering Manager, Software Supply Chain Security: Pipeline Security"
        assert _reject_reason(title) is None, (
            "Supply chain SECURITY title must not be hard-rejected"
        )

    def test_supply_chain_security_accepted(self):
        assert _accept("Supply Chain Security Engineer")
        assert _accept("Software Supply Chain Security Manager")

    def test_bare_supply_chain_manager_still_rejected(self):
        """
        Non-security supply chain roles must still be blocked.
        We replaced 'supply chain' with more specific logistics patterns.
        """
        assert not _accept("Supply Chain Manager",
                           description="Manage procurement and logistics operations.")

    def test_security_engineering_manager_accepted(self):
        assert _accept("Security Engineering Manager")

    def test_security_governance_manager_accepted(self):
        assert _accept("Security Governance Manager")


# ===========================================================================
# BUG 3 — Borderline detection missing threat / malware / forensic keywords
# ===========================================================================

class TestBorderlineDetectionKeywords:
    """
    Titles containing 'threat', 'malware', 'forensic', 'phishing', or
    'vulnerability' should at minimum reach the borderline/ML path rather than
    receiving an immediate reject_no_cyber_signal.
    """

    def test_threat_in_title_not_no_cyber_signal(self):
        from intelligence.intent import classify_cyber_intent
        result = classify_cyber_intent(_make_job("Threat Researcher"))
        # After the fix the title matches DOMAIN_PATTERNS directly (accept=True).
        # Before the fix it was reject_no_cyber_signal.
        assert result.accept or result.reason_code != "reject_no_cyber_signal", (
            f"'Threat Researcher' must not be reject_no_cyber_signal, got {result.reason_code}"
        )

    def test_malware_title_at_least_borderline(self):
        from intelligence.intent import classify_cyber_intent
        result = classify_cyber_intent(_make_job("Malware Reverse Engineer"))
        assert result.accept or result.reason_code != "reject_no_cyber_signal"

    def test_forensic_title_at_least_borderline(self):
        from intelligence.intent import classify_cyber_intent
        result = classify_cyber_intent(_make_job("Digital Forensic Analyst"))
        assert result.accept or result.reason_code != "reject_no_cyber_signal"


# ===========================================================================
# BUG 4 — ML rescue anchors missing key terms
# ===========================================================================

class TestMLRescueAnchors:
    """
    The _STRONG_ML_RESCUE_ANCHORS set is used by _has_any_cyber_anchor() to
    decide whether ML rescue is allowed.  Terms added in v52 must be present.
    """

    def test_security_researcher_in_anchors(self):
        from models import _STRONG_ML_RESCUE_ANCHORS
        assert "security researcher" in _STRONG_ML_RESCUE_ANCHORS

    def test_threat_intelligence_researcher_in_anchors(self):
        from models import _STRONG_ML_RESCUE_ANCHORS
        assert "threat intelligence researcher" in _STRONG_ML_RESCUE_ANCHORS

    def test_threat_intelligence_in_anchors(self):
        from models import _STRONG_ML_RESCUE_ANCHORS
        assert "threat intelligence" in _STRONG_ML_RESCUE_ANCHORS

    def test_phishing_analyst_in_anchors(self):
        from models import _STRONG_ML_RESCUE_ANCHORS
        assert "phishing analyst" in _STRONG_ML_RESCUE_ANCHORS

    def test_supply_chain_security_in_anchors(self):
        from models import _STRONG_ML_RESCUE_ANCHORS
        assert "supply chain security" in _STRONG_ML_RESCUE_ANCHORS

    def test_security_program_in_anchors(self):
        from models import _STRONG_ML_RESCUE_ANCHORS
        assert "security program" in _STRONG_ML_RESCUE_ANCHORS


# ===========================================================================
# BUG 5 — CYBER_TITLE_OVERRIDE_PATTERNS too narrow
# ===========================================================================

class TestCyberTitleOverridePatterns:
    """
    CYBER_TITLE_OVERRIDE_PATTERNS is checked by _has_cyber_override() to skip
    the GENERIC_TECH_REJECTS gate.  v52 added security-prefixed compound terms.
    """

    def test_security_program_in_override_patterns(self):
        from intelligence.patterns import CYBER_TITLE_OVERRIDE_PATTERNS
        assert "security program" in CYBER_TITLE_OVERRIDE_PATTERNS

    def test_supply_chain_security_in_override_patterns(self):
        from intelligence.patterns import CYBER_TITLE_OVERRIDE_PATTERNS
        assert "supply chain security" in CYBER_TITLE_OVERRIDE_PATTERNS

    def test_software_supply_chain_in_override_patterns(self):
        from intelligence.patterns import CYBER_TITLE_OVERRIDE_PATTERNS
        assert "software supply chain" in CYBER_TITLE_OVERRIDE_PATTERNS

    def test_security_engineering_in_override_patterns(self):
        from intelligence.patterns import CYBER_TITLE_OVERRIDE_PATTERNS
        assert "security engineering" in CYBER_TITLE_OVERRIDE_PATTERNS

    def test_security_governance_in_override_patterns(self):
        from intelligence.patterns import CYBER_TITLE_OVERRIDE_PATTERNS
        assert "security governance" in CYBER_TITLE_OVERRIDE_PATTERNS


# ===========================================================================
# BUG 6 — supply chain removed from GENERIC_TECH_REJECTS bare list
# ===========================================================================

class TestSupplyChainNotInBareRejects:
    """
    Bare 'supply chain' must no longer appear in GENERIC_TECH_REJECTS.
    It has been replaced by more specific logistics-only patterns.
    """

    def test_bare_supply_chain_not_in_generic_rejects(self):
        from intelligence.patterns import GENERIC_TECH_REJECTS
        assert "supply chain" not in GENERIC_TECH_REJECTS, (
            "'supply chain' must be replaced with specific logistics variants"
        )

    def test_specific_logistics_patterns_present(self):
        from intelligence.patterns import GENERIC_TECH_REJECTS
        assert "supply chain manager" in GENERIC_TECH_REJECTS
        assert "supply chain coordinator" in GENERIC_TECH_REJECTS


# ===========================================================================
# BUG 7 — smart_expire was a complete no-op
# ===========================================================================

class TestSmartExpire:
    """
    smart_expire(seen, 0) must actually shrink seen_dict so that a
    follow-up deduplicate() call has a real chance of recovering jobs.
    """

    def test_smart_expire_no_op_when_new_jobs_found(self):
        from dedup import smart_expire
        seen = {"a": 1.0, "b": 2.0, "c": 3.0}
        result = smart_expire(seen, new_jobs_count=3)
        assert result == seen, "Must be a no-op when new_jobs_count > 0"

    def test_smart_expire_shrinks_seen_when_zero_new_jobs(self):
        from dedup import smart_expire
        seen = {str(i): float(i) for i in range(10)}
        result = smart_expire(seen, new_jobs_count=0)
        assert len(result) < len(seen), (
            "smart_expire must remove oldest entries when 0 new jobs found"
        )

    def test_smart_expire_removes_oldest_entries(self):
        from dedup import smart_expire
        # Give each entry a distinct timestamp; oldest = smallest value
        seen = {"old_1": 1.0, "old_2": 2.0, "recent_1": 100.0, "recent_2": 200.0,
                "recent_3": 300.0}
        result = smart_expire(seen, new_jobs_count=0)
        # At least one of the oldest entries should be gone
        assert "old_1" not in result or "old_2" not in result, (
            "smart_expire must drop the oldest entries first"
        )
        # Recent entries must survive
        assert "recent_3" in result

    def test_smart_expire_empty_dict_safe(self):
        from dedup import smart_expire
        result = smart_expire({}, new_jobs_count=0)
        assert result == {}


# ===========================================================================
# BUG 8 — Proxy pool: score floor and score recovery after ban expiry
# ===========================================================================

@pytest.mark.skip(
    reason=(
        "v55 removed proxy support entirely by design — sources/http_utils.py "
        "is now direct-only (no _ProxyPool). See MERGE_NOTES.md / README for "
        "the v55 'public sources only, direct connection' policy. These tests "
        "regress against v52 architecture and no longer apply."
    )
)
class TestProxyPoolFixes:
    """
    v52 fixed three proxy pool issues:
      • Reduced cooldown times (30 min → 15 min for 403)
      • Added SCORE_FLOOR so proxies never drop to 0
      • Added score recovery when ban expires

    Kept (skipped, not deleted) as a historical record — re-enable only if
    proxy support is reintroduced.
    """

    def _fresh_pool(self, proxy_urls: list[str]):
        from sources.http_utils import _ProxyPool
        pool = _ProxyPool.__new__(_ProxyPool)
        import threading
        pool._lock = threading.Lock()
        pool._proxies = proxy_urls
        pool._banned = {}
        pool._scores = {p: pool.SCORE_INIT for p in proxy_urls}
        pool._sticky = {}
        return pool

    def test_score_floor_enforced_after_multiple_bans(self):
        pool = self._fresh_pool(["proxy1"])
        # Ban three times — score must never drop below SCORE_FLOOR
        pool.ban("proxy1", reason="403")
        pool.ban("proxy1", reason="403")
        pool.ban("proxy1", reason="403")
        assert pool._scores["proxy1"] >= pool.SCORE_FLOOR

    def test_score_recovers_when_ban_expires(self):
        pool = self._fresh_pool(["proxy1"])
        # Simulate a heavy ban bringing score near floor
        pool._scores["proxy1"] = pool.SCORE_FLOOR
        # Manually set ban to expired
        pool._banned["proxy1"] = time.time() - 1
        # Calling _available() triggers recovery
        pool._available()
        assert pool._scores["proxy1"] >= 20.0, (
            "Expired ban must restore score to at least 20"
        )

    def test_cooldown_403_reduced(self):
        from sources.http_utils import _ProxyPool
        assert _ProxyPool.COOLDOWN_403 <= 900, (
            "COOLDOWN_403 must be ≤ 15 min; was 30 min (caused pool exhaustion)"
        )

    def test_cooldown_429_reduced(self):
        from sources.http_utils import _ProxyPool
        assert _ProxyPool.COOLDOWN_429 <= 300, (
            "COOLDOWN_429 must be ≤ 5 min; was 10 min"
        )

    def test_success_boost_positive(self):
        """report_success must always increase score, never decrease it."""
        pool = self._fresh_pool(["proxy1"])
        pool._scores["proxy1"] = 40.0
        pool.report_success("proxy1", elapsed_ms=1000)
        assert pool._scores["proxy1"] > 40.0


# ===========================================================================
# BUG 9 — LLM classifier model string alignment
# ===========================================================================

class TestLLMModelString:
    """
    Both ai_filter.py and intelligence/llm_classifier.py must use the same
    current Claude Haiku model string.
    """

    def test_llm_classifier_uses_claude_haiku_4_5(self):
        import ast, pathlib
        src = pathlib.Path("intelligence/llm_classifier.py").read_text(encoding="utf-8")
        assert "claude-haiku-4-5-20251001" in src, (
            "llm_classifier.py must default to claude-haiku-4-5-20251001"
        )

    def test_ai_filter_uses_claude_haiku_4_5(self):
        import pathlib
        src = pathlib.Path("ai_filter.py").read_text(encoding="utf-8")
        assert "claude-haiku-4-5-20251001" in src


# ===========================================================================
# BUG 10 — False positives that must remain rejected
# ===========================================================================

class TestExistingRejectsStillWork:
    """
    Ensure the new permissive patterns didn't break hard rejects for
    obviously non-cybersec roles.
    """

    def test_logistics_supply_chain_manager_rejected(self):
        assert not _accept(
            "Supply Chain Manager",
            description="Oversee procurement, logistics and warehouse operations."
        )

    def test_sales_account_executive_rejected(self):
        assert not _accept("Account Executive, Enterprise - Carolinas")

    def test_software_engineer_rejected(self):
        assert not _accept("Senior Software Engineer, Backend")

    def test_social_media_manager_rejected(self):
        assert not _accept("Senior Social Media Manager")

    def test_security_guard_still_rejected(self):
        assert not _accept("Security Guard", description="Patrol premises at night.")

    def test_credit_risk_analyst_rejected(self):
        assert not _accept(
            "Credit Risk Analyst",
            description="Assess creditworthiness and financial risk for lending portfolio."
        )

    def test_devops_engineer_rejected(self):
        assert not _accept(
            "DevOps Engineer",
            description="Manage CI/CD pipelines and Kubernetes clusters."
        )
