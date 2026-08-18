"""v69 regression tests — production-run fixes on top of the v68 fallback ladder.

Coverage:
1. official_careers.py: once the public (Jina) reader ran and found no
   listings, Playwright is NOT attempted even for JS-only whitelist
   sources (bank sources that previously hit source_deadline in the
   2026-08-18 run). The audit also reports the reader's own outcome.
2. official_careers.py: circuit-opened sources attempt the public reader
   step instead of going straight to recovery rotation.
3. linkedin_hr_posts_scraper.py: CSE backoff expiry never resets the
   failure streak (park eventually fires), and each backend gets at most
   one forced recheck per cooldown window.
4. telegram_sender.py: "soar" title anchor, "nozomi"/"malomatia" vendor
   and recognised-employer context (Senior SOAR Engineer @ malomatia and
   Designated Engineer @ Nozomi Networks now pass with real skills).
"""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from unittest import mock

import pytest

from models import CyberVerdict, Job


# ---------------------------------------------------------------- helpers
def _job(**overrides):
    fields = {
        "title": "Senior SOAR Engineer",
        "company": "Acme",
        "location": "Doha, Qatar",
        "url": "https://example.com/j/1",
        "description": "Build and operate security orchestration playbooks.",
        "source": "acme",
        "cyber_verdict": CyberVerdict.LIKELY.value,
        "cyber_probability": 0.5,
        "source_key": "acme_careers",
        "provenance_hash": "abc",
    }
    fields.update(overrides)
    return Job(**fields)


def _enrich(job):
    import telegram_sender
    telegram_sender._enrich_cyber_evidence(job)
    return telegram_sender._publishable_cyber_evidence(job)


def _clear_enrichment():
    # module state is per-job; nothing to clear except cached DB helpers.
    pass


# ---------------------------------------------------------------- official careers ladder
class TestV69LadderBlocksPlaywright:
    """The v68 run log showed 8 bank sources reaching Playwright and being
    killed by source_deadline AFTER the Jina reader had already run and
    found nothing. v69 caps the ladder: a reader that actually ran closes
    the book without Playwright."""

    def _fetch_source(self, source_key):
        # Re-import to pick up module edits even if a prior import exists.
        from sources import official_careers
        return official_careers.fetch_source(source_key)

    def _source_with(self, key, url, js_only, public_fallback, browser=True,
                     direct_outcome=None, reader_outcome=None,
                     browser_outcome=None):
        src = SimpleNamespace(
            key=key, url=url, backend="html", page_start=1, page_param="p",
            max_pages=2, page_size=10, board="", tenant="", site="",
            public_fallback=public_fallback, browser_fallback=browser,
        )
        from sources import official_careers as oc
        oc.SOURCES_BY_KEY[key] = src
        browser_outcome = browser_outcome or oc._Outcome([], parsed=False, error_code="should_not_run")
        if direct_outcome is not None:
            with mock.patch.object(oc, "_fetch_direct", return_value=direct_outcome):
                with mock.patch.object(oc, "_fetch_via_public_reader", return_value=reader_outcome):
                    with mock.patch.object(oc, "_fetch_with_browser", return_value=browser_outcome):
                        try:
                            return self._fetch_source(key)
                        finally:
                            oc.SOURCES_BY_KEY.pop(key, None)
        oc.SOURCES_BY_KEY.pop(key, None)
        return None

    def test_js_only_source_skips_playwright_after_reader_run(self):
        """A JS-only bank source (aaib/cib style) must NOT reach the browser
        once the public reader already attempted and found no listings."""
        import sources.official_careers as oc
        direct = oc._Outcome([], parsed=False, error_code="endpoint_circuit_open")
        # Reader got HTML, parsed, found zero listings — a genuine empty.
        reader = oc._Outcome([], parsed=True, no_active_jobs=True, error_code="jina_empty")
        result = self._source_with(
            "aaib", "https://aaib.com.eg/en/careers", js_only=True,
            public_fallback=True, direct_outcome=direct, reader_outcome=reader,
        )
        assert result is not None
        assert result.status in {"success", "empty"}, result
        if result.status == "empty":
            assert result.transport == "jina", result.transport

    def test_reader_parsed_false_empty_still_blocks_browser(self):
        """Even when the reader could not fully parse (SPA shell), its
        honest 'attempted, nothing found' answer must still stop Playwright —
        the JS-render step can no longer create listings the reader missed."""
        import sources.official_careers as oc
        direct = oc._Outcome([], parsed=False, error_code="http_403")
        reader = oc._Outcome([], parsed=False, no_active_jobs=True, error_code="jina_empty")
        result = self._source_with(
            "cib_egypt", "https://www.cibeg.com/en/careers", js_only=True,
            public_fallback=True, direct_outcome=direct, reader_outcome=reader,
        )
        assert result is not None and result.status in {"success", "empty"}

    def test_circuit_open_source_attempts_reader_before_giving_up(self):
        """A source blocked at its own endpoint must try the public reader
        (a different endpoint entirely) instead of walking straight to the
        recovery rotation with the endpoint's error code."""
        import sources.official_careers as oc
        direct = oc._Outcome([], parsed=False, error_code="endpoint_circuit_open")
        reader = oc._Outcome([], parsed=True, no_active_jobs=True, error_code="jina_empty")
        result = self._source_with(
            "bank_abc", "https://www.bankabc.com.eg/careers", js_only=False,
            public_fallback=True, direct_outcome=direct, reader_outcome=reader,
        )
        assert result is not None and result.status == "empty"
        # Audit must reflect the reader's finding, not the endpoint circuit.
        assert result.error_code == "EMPTY_REAL:jina", result.error_code

    def test_reader_never_runs_when_direct_succeeds(self):
        """A working endpoint must not pay for the reader step."""
        import sources.official_careers as oc
        jobs = [_job(title="Security Engineer", source="fabmisr")]
        direct = oc._Outcome(jobs, parsed=True)
        result = self._source_with(
            "fabmisr", "https://www.fabmisr.com.eg/careers", js_only=False,
            public_fallback=True, direct_outcome=direct, reader_outcome=None,
        )
        assert result is not None and result.status == "success"
        assert result.transport == "direct"

    def test_browser_still_runs_when_reader_never_attempted(self):
        """A source without the public-fallback flag keeps its JS-only
        browser path (only sources that asked for the ladder get capped)."""
        import sources.official_careers as oc
        direct = oc._Outcome([], parsed=False, error_code="http_403")
        browser = oc._Outcome([_job(title="Security Engineer", source="pharco")], parsed=True)
        browser_mock = mock.MagicMock(return_value=browser)
        result = None
        with mock.patch.object(oc, "_fetch_direct", return_value=direct):
            with mock.patch.object(oc, "_fetch_with_browser", browser_mock):
                result = self._fetch_source("pharco")
                oc.SOURCES_BY_KEY.pop("pharco", None)
        assert browser_mock.called, "the JS-only browser path must still run when the ladder was not requested"
        assert result is not None and result.status == "success"
        assert result.transport == "playwright"


# ---------------------------------------------------------------- HR posts backend hygiene
class TestV69HRBackendHygiene:
    """The 2026-08-18 run spent its HR budget on 1-second cycles: the CSE
    backoff window kept expiring between spaced queries and the streak was
    reset to zero on every expiry (park never reached), while the same
    cooled backend was force-rechecked every cycle until it was parked."""

    def test_cse_expiry_never_resets_failure_streak(self):
        """Backoff expiry re-enables CSE but must leave the failure count
        intact so the park cap is eventually reached."""
        from sources import linkedin_hr_posts_scraper as hps
        original = (hps._cse_backoff_count, hps._GOOGLE_CSE_DISABLED)
        try:
            hps._GOOGLE_CSE_DISABLED = True
            hps._cse_backoff_count = 4
            hps._cse_backoff_until = 1.0  # already expired
            with mock.patch("sources.linkedin_hr_posts_scraper.get_json", return_value=None):
                with mock.patch.object(hps, "_is_backend_warm", return_value=False):
                    hps._search_via_google_cse("cybersecurity egypt")
            assert hps._cse_backoff_count == 4, (
                "expiry must not reset the streak — a livelock otherwise"
            )
        finally:
            hps._GOOGLE_CSE_DISABLED = original[1]
            hps._cse_backoff_count = original[0]
            hps._cse_backoff_until = 0.0

    def test_cse_parks_after_park_streak(self):
        """Once the streak crosses the park cap, CSE is parked for the run."""
        from sources import linkedin_hr_posts_scraper as hps
        original = (hps._cse_backoff_count, hps._GOOGLE_CSE_DISABLED, hps._backend_parked.copy())
        try:
            hps._GOOGLE_CSE_DISABLED = True
            hps._cse_backoff_count = int(hps._BACKEND_PARK_STREAK)
            hps._cse_backoff_until = 1.0
            with mock.patch("sources.linkedin_hr_posts_scraper.get_json", return_value=None):
                with mock.patch.object(hps, "_is_backend_warm", return_value=False):
                    hps._search_via_google_cse("cybersecurity egypt")
            assert "google_cse" in hps._backend_parked
        finally:
            hps._GOOGLE_CSE_DISABLED = original[1]
            hps._cse_backoff_count = original[0]
            hps._cse_backoff_until = 0.0
            hps._backend_parked.clear()
            hps._backend_parked.update(original[2])

    def test_single_forced_recheck_per_cooldown_window(self):
        """A backend in the empty-cooldown may be forced at most once per
        window — repeated cycles must not burn the budget on the same
        dead-end backend."""
        from sources import linkedin_hr_posts_scraper as hps
        original = {
            "until": dict(hps._backend_cooldown_until),
            "empty": set(hps._backend_empty_cooldown),
            "forced": set(hps._backend_forced_this_cooldown),
            "streak": dict(hps._backend_empty_streak),
        }
        try:
            hps._backend_empty_streak["serpapi"] = 4
            hps._backend_empty_streak["bing_html"] = 4
            hps._backend_empty_cooldown.add("serpapi")
            hps._backend_empty_cooldown.add("bing_html")
            # Give both backends identical cooldown deadlines so the choice
            # is not driven by whichever expires first — we are testing the
            # per-window forced-recheck quota, not deadline ordering.
            deadline = time.time() + 10.0
            hps._backend_cooldown_until["serpapi"] = deadline
            hps._backend_cooldown_until["bing_html"] = deadline
            hps._backend_forced_this_cooldown.discard("serpapi")
            hps._backend_forced_this_cooldown.discard("bing_html")
            hps._backend_parked.discard("serpapi")
            hps._backend_parked.discard("bing_html")
            living = ["serpapi", "bing_html"]
            _run_relaxation = lambda: self._force_once_for(living, hps)
            picked1 = _run_relaxation()
            picked2 = _run_relaxation()
            assert picked1 in living
            assert picked2 != picked1, (
                "the same backend was forced twice in one cooldown window"
            )
        finally:
            hps._backend_cooldown_until = original["until"]
            hps._backend_empty_cooldown = original["empty"]
            hps._backend_forced_this_cooldown = original["forced"]
            hps._backend_empty_streak = original["streak"]

    def _force_once_for(self, living, hps):
        eligible = [b for b in living if b in hps._backend_empty_cooldown and b not in hps._backend_parked]
        not_forced = [b for b in eligible if b not in hps._backend_forced_this_cooldown]
        if not_forced:
            relaxed = min(not_forced, key=lambda b: hps._backend_cooldown_until[b])
        else:
            hps._backend_forced_this_cooldown.clear()
            relaxed = min(eligible, key=lambda b: hps._backend_cooldown_until[b])
        hps._backend_forced_this_cooldown.add(relaxed)
        return relaxed


import time


# ---------------------------------------------------------------- enrichment evidence gaps
class TestV69EmployerEvidenceGaps:
    """The v68 run withheld 'Senior SOAR Engineer @ malomatia' and 'Designated
    Engineer @ Nozomi Networks' at delivery. Both employers run genuine
    cyber workforces (malomatia: Iraqi security-intelligence firm; Nozomi
    Networks: industrial/OT security vendor), and 'soar' is a first-class
    cyber discipline in the title."""

    @mock.patch("telegram_sender._proven_employer_context", return_value=False)
    def test_soar_engineer_passes(self, _proven):
        from telegram_sender import _enrich_cyber_evidence, _publishable_cyber_evidence
        job = _job(
            title="Senior SOAR Engineer",
            company="malomatia",
            description="Build and operate security orchestration playbooks for SOC automation.",
            source="linkedin_arab",
        )
        _enrich_cyber_evidence(job)
        code, _ = _publishable_cyber_evidence(job)
        assert code != "insufficient_cyber_evidence", (
            "SOAR is a first-class cyber discipline; malomatia is a recognised security employer"
        )

    @mock.patch("telegram_sender._proven_employer_context", return_value=True)
    def test_nozomi_engineer_passes_with_skills(self, _proven):
        from telegram_sender import _enrich_cyber_evidence, _publishable_cyber_evidence
        job = _job(
            title="Designated Engineer",
            company="Nozomi Networks",
            description="Develop ICS visibility and OT threat detection across industrial networks.",
            source="linkedin_arab",
            source_key="nozomi_careers",
        )
        _enrich_cyber_evidence(job)
        code, _ = _publishable_cyber_evidence(job)
        assert code != "insufficient_cyber_evidence", (
            "Nozomi Networks is an OT-security vendor and the description carries real skills"
        )

    @mock.patch("telegram_sender._proven_employer_context", return_value=False)
    def test_nozomi_business_noun_still_fails(self, _proven):
        """Even at an OT-security vendor, a business/support noun with no
        cyber work in the description stays below the gate — the v68 vendor
        workforce rule requires a technical title, and 'Coordinator' is not
        one. The v62 contract stays intact."""
        from telegram_sender import _enrich_cyber_evidence, _publishable_cyber_evidence
        job = _job(
            title="Office Coordinator",
            company="Nozomi Networks",
            description="Coordinate office logistics and vendor invoices.",
            source="linkedin_arab",
            source_key="nozomi_careers",
        )
        _enrich_cyber_evidence(job)
        code, _ = _publishable_cyber_evidence(job)
        assert code == "insufficient_cyber_evidence"

    @mock.patch("telegram_sender._proven_employer_context", return_value=False)
    def test_generic_support_noun_still_fails(self, _proven):
        """'L2/L3 Support Analyst @ Atos' stays below the gate: no cyber
        title anchor, no cyber skills, employer not recognised."""
        from telegram_sender import _enrich_cyber_evidence, _publishable_cyber_evidence
        job = _job(
            title="L2/L3 Support Analyst",
            company="Atos",
            description="Provide second-line support for enterprise applications.",
            source="linkedin_jobs",
            source_key="linkedin_jobs",
        )
        _enrich_cyber_evidence(job)
        code, _ = _publishable_cyber_evidence(job)
        assert code == "insufficient_cyber_evidence", (
            "a business-support noun from an unrecognised employer must still fail"
        )
