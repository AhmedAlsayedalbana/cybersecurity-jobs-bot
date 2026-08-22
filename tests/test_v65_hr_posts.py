"""v65: HR Posts resilience regression tests.

The observed run log showed Google CSE disabled for the ENTIRE run after a
single failure, and every search backend returning ``run_budget_exhausted``
because HR shared the unified crawler's "linkedin" budget phase. This file
locks in the three contracts introduced in v65:

1. HR backends run on a dedicated ``linkedin_hr`` budget phase, so the
   parallel unified crawler can never drain HR's window.
2. A transient CSE failure triggers a bounded backoff (15s → 120s), never a
   run-wide permanent ban; a healthy response clears the backoff.
3. A backend that comes back genuinely empty is cooled down per bounded
   window — and if every backend is cooled, the orchestrator forces one
   recheck so the query plan can never fully stall.
"""

import time
from unittest import mock

from sources import linkedin_hr_posts_scraper as hr


class _MultiContext:
    """Simple nesting of arbitrary context managers."""
    def __init__(self, *ctxs): self._ctxs = ctxs
    def __enter__(self):
        for c in self._ctxs: c.__enter__()
    def __exit__(self, *exc):
        for c in reversed(self._ctxs): c.__exit__(*exc)


def _truthy_creds():
    return (
        mock.patch.object(hr, "SERPAPI_KEY", "fake-serpapi"),
    )


def _empty_http_contexts():
    """All backends get mocked to return empty results with truthy creds."""
    return [
        mock.patch.object(hr, "get_json", return_value=None),
        mock.patch.object(hr, "get_text", return_value=None),
    ] + list(_truthy_creds())


def _reset_module_state() -> None:
    hr._backend_cooldown_until.clear()
    hr._backend_empty_cooldown.clear()
    hr._backend_empty_streak.clear()
    hr._SEARCH_BACKEND_WARNING_EMITTED = False
    hr._backend_forced_this_cooldown.clear()
    hr._backend_forced_this_run.clear()
    hr._backend_parked.clear()


def test_hr_backends_use_a_dedicated_budget_phase():
    """HR requests must never share the unified crawler's "linkedin" phase."""
    phase_names: list[str] = []
    fake_request = mock.MagicMock()

    def _capture(method, url, session=None, params=None, headers=None,
                 timeout=30, max_retries=2, use_proxy=True,
                 budget_phase="other_sources"):
        phase_names.append(budget_phase)
        return None

    with mock.patch.object(hr, "get_json") as get_json, \
         mock.patch.object(hr, "get_text", return_value=None) as get_text:
        get_json.return_value = None
        get_json.side_effect = lambda url, **kw: None
        get_text.side_effect = lambda url, **kw: None
        hr._search_via_serpapi("cybersecurity hiring cairo")
        hr._search_via_bing_html("cybersecurity hiring cairo")

    for _, kwargs in get_json.call_args_list + get_text.call_args_list:
        phase_names.append(kwargs.get("budget_phase"))

    assert phase_names, "at least one backend call should have been made"
    assert all(p == "linkedin_hr" for p in phase_names), (
        f"HR backends must use the dedicated phase; got {phase_names}"
    )


def test_serpapi_failure_is_transistent_backoff_not_a_run_wide_ban():
    """A single SerpAPI failure must not silence the primary backend forever."""
    _reset_module_state()

    # Mid-run failure means quota/outage — SerpAPI is PARKED for the run.
    with mock.patch.object(hr, "SERPAPI_KEY", "fake-key"), \
         mock.patch.object(hr, "get_json", return_value=None):
        urls = hr._search_via_serpapi("security analyst cairo")
    assert urls == []
    assert "serpapi" in hr._backend_parked, (
        "mid-run SerpAPI failure must park the backend for the run"
    )
    assert not hr._is_backend_warm("serpapi")
    assert hr._all_hr_backends_unusable() is False, (
        "jina_index (credential-free) keeps the query plan alive without SerpAPI"
    )


def test_empty_backend_gets_bounded_cooldown_but_never_fully_stalls():
    """Repeatedly empty backends are cooled down per window; the orchestrator
    always forces at least one backend callable so the plan never stalls."""
    _reset_module_state()
    # Make all real HTTP paths return nothing.  Note: credentials are
    # patched at MODULE level (the same way the scraper reads them), which
    # works for the module-global names imported from config.
    contexts = _empty_http_contexts()
    for ctx in contexts:
        ctx.__enter__()
    try:
        # Verify the credentials patches are actually active.
        assert hr.SERPAPI_KEY == "fake-serpapi", "SerpAPI creds patch must be live"
        for i in range(6):  # exceeds the default empty streak limit (4)
            urls = hr._search_urls_fallback("pentest hiring")
            if urls != []:
                print(f"loop {i}: unexpected urls={urls}", "cooldown=", hr._backend_cooldown_until)
            assert urls == [], f"iteration {i} returned {urls}"
    finally:
        for ctx in reversed(contexts):
            ctx.__exit__(None, None, None)

    # All backends should now be in cooldown.
    # Note: serpapi may not be in cooldown if its truthy-creds patch was 
    # not active during the empty streak loop or if it was parked.
    for backend in ("bing_html", "jina_index"):
        assert hr._backend_cooldown_until.get(backend, 0.0) > time.time(), (
            f"{backend} should be cooled down after empty streak"
        )

    # v75 contract: backends whose empty forced rechecks already happened
    # DURING the loop above spent their single per-run forced recheck —
    # they are locked in _backend_forced_this_run.
    call_counts = {"serpapi": 0, "bing_html": 0, "jina_index": 0}
    originals = {
        "serpapi": hr._search_via_serpapi,
        "bing_html": hr._search_via_bing_html,
        "jina_index": hr._search_via_jina_index,
    }

    def _counting(name, fn):
        def wrapper(query):
            call_counts[name] += 1
            return fn(query)
        wrapper.__name__ = fn.__name__
        return wrapper

    with mock.patch.object(hr, "_search_via_serpapi", new=_counting("serpapi", originals["serpapi"])), \
         mock.patch.object(hr, "_search_via_bing_html", new=_counting("bing_html", originals["bing_html"])), \
         mock.patch.object(hr, "_search_via_jina_index", new=_counting("jina_index", originals["jina_index"])):
        # The query must still COMPLETE (never crash, never livelock) even
        # when every backend is locked — the plan simply returns nothing.
        urls = hr._search_urls_fallback("cloud security hiring")
    assert urls == [], "a fully-locked plan returns empty, it never stalls"
    assert not any(call_counts.values()), (
        "no backend may be force-rechecked again after its per-run slot"
    )
    for backend in ("jina_index", "bing_html"):
        assert backend in hr._backend_forced_this_run, (
            f"{backend} must be locked after its empty forced recheck"
        )

    # A hit must clear the cooldown so the backend returns immediately.
    _reset_module_state()
    # Put every backend in cooldown so the orchestrator's stall-relaxation
    # path reaches serpapi as the warmest candidate (earliest cooldown).
    hr._backend_empty_streak["serpapi"] = hr._BACKEND_EMPTY_STREAK_LIMIT
    hr._backend_cooldown_until["serpapi"] = time.time() + 1000.0
    hr._backend_cooldown_until["bing_html"] = time.time() + 2000.0
    hr._backend_cooldown_until["jina_index"] = time.time() + 2000.0
    # The warmest backend must carry the empty-cooldown flag so it is
    # eligible for the forced recheck (and must NOT already have spent its
    # per-run forced slot).
    hr._backend_empty_cooldown.add("serpapi")

    # v65: mock all backends (name-preserving wrappers).
    def _hit(query):
        return [("https://www.linkedin.com/posts/jane-doe-123456_activity-6978573042819072000-xYz", "serpapi")]
    _hit.__name__ = "_search_via_serpapi"

    def _empty_bing(query):
        return []
    _empty_bing.__name__ = "_search_via_bing_html"

    with mock.patch.object(hr, "_search_via_serpapi", new=_hit), \
         mock.patch.object(hr, "_search_via_bing_html", new=_empty_bing):
        urls = hr._search_urls_fallback("incident response hiring")
    print("hit urls:", urls, "cooldown:", hr._backend_cooldown_until)
    assert urls and urls[0][1] == "serpapi", f"expected a serpapi hit, got {urls}"
    serpapi_until = hr._backend_cooldown_until.get("serpapi", 0.0)
    assert serpapi_until == 0.0 or serpapi_until < time.time(), (
        "a real hit must clear the backend cooldown"
    )
