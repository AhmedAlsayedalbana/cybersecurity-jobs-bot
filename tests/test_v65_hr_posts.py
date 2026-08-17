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
        mock.patch.object(hr, "GOOGLE_CSE_API_KEY", "fake-key"),
        mock.patch.object(hr, "GOOGLE_CSE_CX", "fake-cx"),
        mock.patch.object(hr, "SERPAPI_KEY", "fake-serpapi"),
    )


def _empty_http_contexts():
    """All backends get mocked to return empty results with truthy creds."""
    return [
        mock.patch.object(hr, "get_json", return_value=None),
        mock.patch.object(hr, "get_text", return_value=None),
    ] + list(_truthy_creds())


def _reset_module_state() -> None:
    hr._GOOGLE_CSE_DISABLED = False
    hr._cse_backoff_until = 0.0
    hr._cse_backoff_count = 0
    hr._backend_cooldown_until.clear()
    hr._backend_empty_cooldown.clear()
    hr._backend_empty_streak.clear()
    hr._SEARCH_BACKEND_WARNING_EMITTED = False


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
        hr._search_via_google_cse("cybersecurity hiring cairo")
        hr._search_via_serpapi("cybersecurity hiring cairo")
        hr._search_via_bing_html("cybersecurity hiring cairo")

    for _, kwargs in get_json.call_args_list + get_text.call_args_list:
        phase_names.append(kwargs.get("budget_phase"))

    assert phase_names, "at least one backend call should have been made"
    assert all(p == "linkedin_hr" for p in phase_names), (
        f"HR backends must use the dedicated phase; got {phase_names}"
    )


def test_cse_failure_is_transistent_backoff_not_a_run_wide_ban():
    """A single CSE failure must not silence the primary backend forever."""
    _reset_module_state()

    # One transient failure → bounded backoff, NOT permanent disable.
    with mock.patch.object(hr, "GOOGLE_CSE_API_KEY", "fake-key"), \
         mock.patch.object(hr, "GOOGLE_CSE_CX", "fake-cx"), \
         mock.patch.object(hr, "get_json", return_value=None):
        urls = hr._search_via_google_cse("security analyst cairo")
    assert urls == []
    assert hr._cse_backoff_until > time.time(), "backoff window should be set"
    assert hr._cse_backoff_until - time.time() <= 135, (
        "backoff must stay bounded (≤ 120s + jitter)"
    )

    # Queries inside the backoff window skip CSE quickly (no HTTP call).
    with mock.patch.object(hr, "get_json") as get_json:
        get_json.side_effect = RuntimeError("must not be called during backoff")
        assert hr._search_via_google_cse("iam hiring") == []

    # After the window expires, CSE returns to the rotation automatically —
    # even while _GOOGLE_CSE_DISABLED flag is still technically True.
    hr._GOOGLE_CSE_DISABLED = True
    hr._cse_backoff_until = time.time() - 1.0
    # Backoff expiry must also release the shared cooldown map entry — the
    # orchestrator's warm check reads the same map, otherwise CSE would
    # stay skipped forever even after its own backoff expired.
    hr._backend_cooldown_until.pop("google_cse", None)
    call_made = False

    def _succeed(url, **kw):
        nonlocal call_made
        call_made = True
        return {"items": [{"link": "https://www.linkedin.com/posts/jane-doe-123456_activity-6978573042819072000-xYz"}]}

    with mock.patch.object(hr, "GOOGLE_CSE_API_KEY", "fake-key"), \
         mock.patch.object(hr, "GOOGLE_CSE_CX", "fake-cx"), \
         mock.patch.object(hr, "get_json", side_effect=_succeed):
        urls = hr._search_via_google_cse("soc analyst cairo")
    assert call_made, "CSE must retry after backoff expiry"
    assert len(urls) == 1 and urls[0][1] == "google_cse"
    assert hr._cse_backoff_until == 0.0, "a healthy response clears the backoff"
    assert hr._GOOGLE_CSE_DISABLED is False

    # A healthy response restores the shared cooldown map too.
    assert hr._backend_cooldown_until.get("google_cse", 0.0) == 0.0


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
        assert hr.GOOGLE_CSE_API_KEY == "fake-key", "CSE creds patch must be live"
        for i in range(6):  # exceeds the default empty streak limit (4)
            urls = hr._search_urls_fallback("pentest hiring")
            if urls != []:
                print(f"loop {i}: unexpected urls={urls}", "cooldown=", hr._backend_cooldown_until)
            assert urls == [], f"iteration {i} returned {urls}"
    finally:
        for ctx in reversed(contexts):
            ctx.__exit__(None, None, None)

    # All three backends should now be in cooldown.
    for backend in ("google_cse", "serpapi", "bing_html"):
        assert hr._backend_cooldown_until.get(backend, 0.0) > time.time(), (
            f"{backend} should be cooled down after empty streak"
        )

    # But the NEXT query must still make at least one real HTTP call: the
    # stall-relaxation path forces the warmest cooled backend open.
    call_counts = {"google_cse": 0, "serpapi": 0, "bing_html": 0}

    # v65: the orchestrator routes by function __name__, so the wrappers
    # must preserve the original names — a plain side_effect mock has no
    # __name__ (AttributeError), so we wrap the real functions instead.
    originals = {
        "google_cse": hr._search_via_google_cse,
        "serpapi": hr._search_via_serpapi,
        "bing_html": hr._search_via_bing_html,
    }

    def _counting(name, fn):
        def wrapper(query):
            call_counts[name] += 1
            return fn(query)
        wrapper.__name__ = fn.__name__
        return wrapper

    # The relaxed backend must be the warmest one ELIGIBLE for forced
    # rechecks — backends whose cooldown came from genuinely empty
    # responses.  CSE's short transient-failure backoff is deliberately
    # excluded (re-hitting a known-failing API endpoint advances nothing).
    # Computed BEFORE the recheck: the forced call resets the relaxed
    # backend's cooldown to a fresher value, which would flip the min.
    warmest = min(
        (b for b in ("google_cse", "serpapi", "bing_html")
         if b in hr._backend_empty_cooldown),
        key=lambda b: hr._backend_cooldown_until.get(b, 0.0),
    )

    with mock.patch.object(hr, "_search_via_google_cse", new=_counting("google_cse", originals["google_cse"])), \
         mock.patch.object(hr, "_search_via_serpapi", new=_counting("serpapi", originals["serpapi"])), \
         mock.patch.object(hr, "_search_via_bing_html", new=_counting("bing_html", originals["bing_html"])):
        hr._search_urls_fallback("cloud security hiring")

    # At least the relaxed backend got one forced recheck call.
    total_forced = sum(call_counts.values())
    assert total_forced >= 1, (
        "orchestrator must force one recheck when every backend is cooled"
    )
    assert call_counts[warmest] >= 1, (
        f"the warmest backend ({warmest}) should be the one force-rechecked"
    )

    # A hit must clear the cooldown so the backend returns immediately.
    _reset_module_state()
    # Put every backend in cooldown so the orchestrator's stall-relaxation
    # path reaches serpapi as the warmest candidate (earliest cooldown).
    hr._backend_empty_streak["serpapi"] = hr._BACKEND_EMPTY_STREAK_LIMIT
    hr._backend_cooldown_until["serpapi"] = time.time() + 1000.0
    hr._backend_cooldown_until["google_cse"] = time.time() + 2000.0
    hr._backend_cooldown_until["bing_html"] = time.time() + 2000.0
    # The warmest backend must carry the empty-cooldown flag so it is
    # eligible for the forced recheck.
    hr._backend_empty_cooldown.add("serpapi")

    # v65: mock all three backends (name-preserving wrappers) — the
    # orchestrator iterates every backend in the rotation, so a mock
    # without __name__ on any one of them crashes the lookup.
    def _empty_any(query):
        return []
    _empty_any.__name__ = "_search_via_google_cse"

    def _hit(query):
        return [("https://www.linkedin.com/posts/jane-doe-123456_activity-6978573042819072000-xYz", "serpapi")]
    _hit.__name__ = "_search_via_serpapi"

    def _empty_bing(query):
        return []
    _empty_bing.__name__ = "_search_via_bing_html"

    with mock.patch.object(hr, "_search_via_google_cse", new=_empty_any), \
         mock.patch.object(hr, "_search_via_serpapi", new=_hit), \
         mock.patch.object(hr, "_search_via_bing_html", new=_empty_bing):
        urls = hr._search_urls_fallback("incident response hiring")
    print("hit urls:", urls, "cooldown:", hr._backend_cooldown_until)
    assert urls and urls[0][1] == "serpapi", f"expected a serpapi hit, got {urls}"
    serpapi_until = hr._backend_cooldown_until.get("serpapi", 0.0)
    assert serpapi_until == 0.0 or serpapi_until < time.time(), (
        "a real hit must clear the backend cooldown"
    )
