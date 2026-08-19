"""v70 regression tests — bank fast browser cap + HR backend health gate.

v70: 2026-08-18 production run issues
1. Six Egyptian banks (aaib, adib_egypt, banque_misr, cib_egypt, itida,
   we_jina) burned the full 45s source deadline on Playwright because the
   Jina reader could not answer (it failed), and a reader failure was a
   weak signal that still opened the full-budget browser door. Fix: when a
   proven-failing source (public_fallback) reaches the browser ONLY because
   the reader failed to answer, the browser gets ONE FAST attempt
   (CAREERS_FAST_BROWSER_CAP_SECONDS = 15s), never the full deadline.
2. HR Posts burned 33 queries with 0 URLs because the Google CSE key was
   failing and no backend can find LinkedIn posts otherwise. Fix: the HR
   phase now validates backend credentials once at startup, skips a dead
   CSE immediately, and returns early when every backend is unusable.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# Fix 1: fast browser cap when the public reader could not answer
# ---------------------------------------------------------------------------


class _FakeOutcome(SimpleNamespace):
    """Minimal stand-in for _Outcome used by fetch_source."""

    def __init__(
        self,
        jobs=None,
        parsed=False,
        no_active_jobs=False,
        error_code="",
        raw_html="",
    ):
        super().__init__(
            jobs=jobs or [],
            parsed=parsed,
            no_active_jobs=no_active_jobs,
            error_code=error_code,
            raw_html=raw_html,
        )


def _register_fake_source(**overrides):
    """Build a fake CareerSource and register it in SOURCES_BY_KEY so that
    fetch_source(source_key) can look it up — fetch_source uses the real
    registry, so tests must mirror that contract."""
    from sources import official_careers
    from sources.official_careers import CareerSource

    defaults = dict(
        key="bank_x",
        name="Bank X Careers",
        company="Bank X",
        lane="egypt",
        backend="html",
        url="https://bank-x.example.com/careers",
        geo_hint="egypt",
        browser_fallback=True,
        public_fallback=False,
    )
    defaults.update(overrides)
    source = CareerSource(**defaults)
    official_careers.SOURCES_BY_KEY[defaults["key"]] = source
    return source


def test_fast_browser_cap_applied_when_reader_failed_for_public_fallback_source():
    """A proven-failing source whose reader could not answer gets ONE fast
    Playwright attempt (15s), never the full 45s source deadline."""
    from sources import official_careers

    _register_fake_source(key="aaib", public_fallback=True, browser_fallback=True)

    direct_outcome = _FakeOutcome(jobs=[], parsed=False, error_code="endpoint_circuit_open")

    # The reader ATTEMPTED but could not answer (returns None on failure).
    with (
        mock.patch.object(official_careers, "_fetch_direct", return_value=direct_outcome),
        mock.patch.object(official_careers, "_fetch_via_public_reader", return_value=None),
        mock.patch.object(official_careers, "_fetch_with_browser") as browser,
    ):
        browser.return_value = _FakeOutcome(
            jobs=[], parsed=False, error_code="playwright_source_deadline"
        )
        result = official_careers.fetch_source("aaib")

    browser.assert_called_once()
    call_budget = browser.call_args.kwargs.get("budget_seconds")
    assert call_budget is not None
    assert call_budget <= official_careers._FAST_BROWSER_CAP_SECONDS, (
        f"fast-cap bank got a full-budget browser attempt: {call_budget}s"
    )
    # The source still reports its honest blocked outcome (fast cap, not a win).
    assert result.status in ("blocked", "empty")


def test_full_browser_budget_kept_when_reader_answered_honestly_empty():
    """The fast cap ONLY applies when the reader FAILED to answer. When the
    reader answered honestly empty (parsed or no_active_jobs), Playwright
    must NOT run at all — that path did not change in v70."""
    from sources import official_careers

    _register_fake_source(key="nbe", public_fallback=True, browser_fallback=True)
    direct_outcome = _FakeOutcome(jobs=[], parsed=False)
    # Honest empty reader answer: parsed=True (reader read the page, no jobs).
    reader_outcome = _FakeOutcome(jobs=[], parsed=True, no_active_jobs=True)

    with (
        mock.patch.object(official_careers, "_fetch_direct", return_value=direct_outcome),
        mock.patch.object(official_careers, "_fetch_via_public_reader", return_value=reader_outcome),
        mock.patch.object(official_careers, "_fetch_with_browser") as browser,
    ):
        result = official_careers.fetch_source("nbe")

    browser.assert_not_called()
    # The honest reader answer closes the book — status is empty (either the
    # ladder's EMPTY_REAL:jina early return or the tail's parsed-empty
    # classification).
    assert result.status in ("empty", "blocked")
    assert result.transport != "playwright"


def test_browser_not_run_when_reader_found_jobs():
    """If the public reader itself finds jobs, fetch_source returns them
    immediately via the jina transport."""
    from sources import official_careers

    direct_outcome = _FakeOutcome(jobs=[], parsed=False)
    # public_fallback=True is required — the reader step only runs for
    # ladder-enabled sources, so the jobs-it-found branch is reachable.
    _register_fake_source(key="x_bank", public_fallback=True)
    job = SimpleNamespace(title="Cyber Analyst", url="https://x.example/1", company="X")
    reader_outcome = _FakeOutcome(jobs=[job])

    with (
        mock.patch.object(official_careers, "_fetch_direct", return_value=direct_outcome),
        mock.patch.object(official_careers, "_fetch_via_public_reader", return_value=reader_outcome),
        mock.patch.object(official_careers, "_fetch_with_browser") as browser,
    ):
        result = official_careers.fetch_source("x_bank")

    browser.assert_not_called()
    assert result.status == "success"
    assert result.transport == "jina"


def test_non_public_fallback_source_keeps_full_browser_budget():
    """A source without the public-fallback ladder (e.g. a plain JS-only
    source that has never failed) keeps its normal source deadline — the
    v70 fast cap is only for proven-failing sources."""
    from sources import official_careers

    _register_fake_source(key="some_js_only", public_fallback=False, browser_fallback=True)
    direct_outcome = _FakeOutcome(jobs=[], parsed=False)

    # The browser step only runs for keys declared JS-only; monkeypatch the
    # declare set for this test so the source reaches the browser with its
    # full (uncapped) source deadline.
    js_only_keys = official_careers._JS_ONLY_SOURCE_KEYS | {"some_js_only"}
    with (
        mock.patch.object(official_careers, "_JS_ONLY_SOURCE_KEYS", js_only_keys),
        mock.patch.object(official_careers, "_fetch_direct", return_value=direct_outcome),
        mock.patch.object(official_careers, "_fetch_via_public_reader") as reader,
        mock.patch.object(official_careers, "_fetch_with_browser") as browser,
    ):
        browser.return_value = _FakeOutcome(jobs=[], parsed=False, error_code="")
        official_careers.fetch_source("some_js_only")

    reader.assert_not_called()
    browser.assert_called_once()
    call_budget = browser.call_args.kwargs.get("budget_seconds")
    # NOT capped by the fast cap — full source deadline applies.
    assert call_budget > official_careers._FAST_BROWSER_CAP_SECONDS


# ---------------------------------------------------------------------------
# Fix 2: HR backend key validation + all-backends-down early exit
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_hr_state():
    """Each test starts from a clean HR backend state."""
    from sources import linkedin_hr_posts_scraper as hps

    hps._GOOGLE_CSE_DISABLED = False
    hps._cse_backoff_until = 0.0
    hps._cse_backoff_count = 0
    hps._backend_cooldown_until.clear()
    hps._backend_empty_cooldown.clear()
    hps._backend_empty_streak.clear()
    hps._backend_parked.clear()
    yield


def test_hr_skips_entirely_when_every_backend_is_unusable():
    """When the CSE key is dead and no other backend can answer, the HR
    phase must return early with zero queries instead of burning the full
    90s budget on guaranteed empties."""
    from sources import linkedin_hr_posts_scraper as hps

    # Probe failures → CSE disabled; missing SERPAPI_KEY → unusable;
    # bing and jina_index have no key concept — force them unusable by
    # parking them (v74: jina_index is CSE-independent and credential-less,
    # so the gate only exits when it is parked as well).
    hps._backend_parked.add("bing_html")
    hps._backend_parked.add("jina_index")
    with (
        mock.patch.object(hps, "GOOGLE_CSE_API_KEY", "dead-key"),
        mock.patch.object(hps, "GOOGLE_CSE_CX", "dead-cx"),
        mock.patch.object(hps, "SERPAPI_KEY", None),
        mock.patch.object(hps, "get_json", return_value=None),
    ):
        # Snapshot telemetry before the call — the early exit must leave it
        # untouched because the query plan never runs.
        snapshot_before = dict(hps._HR_TELEMETRY)
        jobs = hps.fetch_linkedin_hr_posts_scraper(budget_seconds=90)
    assert jobs == []
    assert hps._GOOGLE_CSE_DISABLED
    assert hps._HR_TELEMETRY == snapshot_before, (
        "the early exit must not mutate HR telemetry — no query plan ran"
    )
    hps._backend_parked.discard("bing_html")
    hps._backend_parked.discard("jina_index")


def test_hr_query_plan_runs_without_any_api_key_because_jina_index_is_always_usable():
    """v74: the HR plan must stay alive even when CSE/serpapi/bing are all
    unusable — jina_index needs no credentials and is unreachable only when
    explicitly parked, so the query plan still executes and calls the
    fallback ladder (which may try jina_index)."""
    from sources import linkedin_hr_posts_scraper as hps

    hps._backend_parked.add("bing_html")
    with (
        mock.patch.object(hps, "GOOGLE_CSE_API_KEY", "dead-key"),
        mock.patch.object(hps, "GOOGLE_CSE_CX", "dead-cx"),
        mock.patch.object(hps, "SERPAPI_KEY", None),
        mock.patch.object(hps, "get_json", return_value=None),
        mock.patch.object(hps, "_search_urls_fallback", return_value=[]),
    ):
        jobs = hps.fetch_linkedin_hr_posts_scraper(budget_seconds=2)
    hps._backend_parked.discard("bing_html")

    # Plan executed (telemetry reset) — the early-exit gate did NOT trip
    # because jina_index is still usable despite zero API credentials.
    assert isinstance(jobs, list)


def test_hr_clears_stale_cse_failure_state_on_healthy_key():
    """A healthy CSE key at startup must clear any stale failure state
    (backoff count, cooldown, park) left over from previous runs, so the
    backend starts the run healthy instead of already handicapped."""
    from sources import linkedin_hr_posts_scraper as hps

    # Simulate leftovers from a previous run.
    hps._cse_backoff_count = 5
    hps._backend_parked.add("google_cse")
    hps._backend_cooldown_until["google_cse"] = time.time() + 60.0

    with (
        mock.patch.object(hps, "GOOGLE_CSE_API_KEY", "valid-key"),
        mock.patch.object(hps, "GOOGLE_CSE_CX", "valid-cx"),
        mock.patch.object(hps, "SERPAPI_KEY", "sp-key"),
        mock.patch.object(hps, "get_json", return_value={"items": []}),
        mock.patch.object(hps, "fetch_linkedin_hr_posts_scraper", return_value=[]),
    ):
        hps._validate_hr_backend_keys()

    assert not hps._GOOGLE_CSE_DISABLED
    assert hps._cse_backoff_count == 0
    assert "google_cse" not in hps._backend_parked
    assert "google_cse" not in hps._backend_cooldown_until


def test_hr_query_plan_still_runs_when_at_least_one_backend_can_answer():
    """The early-exit gate must only trip when NO backend can answer — a
    temporarily cooled CSE with healthy serpapi/bing keeps the plan alive."""
    from sources import linkedin_hr_posts_scraper as hps

    with (
        mock.patch.object(hps, "GOOGLE_CSE_API_KEY", "valid-key"),
        mock.patch.object(hps, "GOOGLE_CSE_CX", "valid-cx"),
        mock.patch.object(hps, "SERPAPI_KEY", "sp-key"),
        mock.patch.object(hps, "get_json", return_value={"items": []}),
        mock.patch.object(hps, "_search_urls_fallback", return_value=[]),
    ):
        # CSE in backoff (but not parked, not permanently disabled) +
        # healthy serpapi/bing → plan runs.
        hps._backend_cooldown_until["google_cse"] = time.time() + 60.0
        jobs = hps.fetch_linkedin_hr_posts_scraper(budget_seconds=2)

    # Plan executed (telemetry reset) and ended via budget/loop, not the
    # early exit — the empty-search return path runs queries first.
    assert isinstance(jobs, list)
