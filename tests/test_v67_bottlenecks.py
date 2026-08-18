"""v67 regression tests — the 0-job bottleneck sources, evidence enrichment,
and pending-first delivery.

The 2026-08-17 run had 9 priority sources (NBE, Banque Misr, Banque du
Caire, CIB, QNB, AAIB, ADIB, WE, Bank NXT) finish with 0 jobs after
wasting the full 45s on a Playwright session that rendered pages with
nothing parseable.  v67 aborts such a session after
``PLAYWRIGHT_ABORT_AFTER_SECONDS`` (default 20s) and stops paying for
empty navigations, while a CYBER_LIKELY job with legitimate vendor or
description-level security evidence is enriched BEFORE the delivery
evidence gate re-evaluates it — the gate's threshold never moves.
"""
import json
import time
from unittest import mock

import pytest

pytest.importorskip("playwright")


# ---------------------------------------------------------------------------
# Test 1: abort-if-no-jobs — the Playwright pass stops paying for empty pages
# ---------------------------------------------------------------------------
def test_playwright_abort_if_no_jobs_returns_early(monkeypatch):
    from sources import official_careers as oc
    from sources.official_careers import CareerSource

    source = CareerSource(
        "nbe", "National Bank of Egypt", "National Bank of Egypt",
        "egypt", "html",
        "https://careers.nbe.com.eg", "egypt",
        page_param="page", max_pages=5, browser_fallback=True,
    )

    # Simulate a session that renders pages but never emits a job, and
    # takes 10 real-world seconds per navigation attempt.
    monkeypatch.setattr("sources.official_careers.config.PLAYWRIGHT_ABORT_AFTER_SECONDS", 20)
    monkeypatch.setattr(
        "sources.official_careers._page_url",
        lambda src, n: f"{src.url}/p{n}",
    )
    # No jobs, no parsed_any: parser sees an empty container and returns
    # (jobs=[], parsed=False), so every rendered page is "empty".
    monkeypatch.setattr(
        "sources.official_careers._jobs_from_html",
        lambda html, src, **kw: ([], False),
    )

    call_log: list[str] = []

    class FakePage:
        def __init__(self) -> None:
            self.navigations = 0

        def set_default_timeout(self, _ms: int) -> None:
            pass

        def goto(self, url: str, **_kw) -> None:
            call_log.append(url)
            self.navigations += 1
            # 10s per navigation — real Playwright cost on the blocked sites.
            time.sleep(10)

        def content(self) -> str:
            return "<div id='job-listing'></div>"

    class ChromiumLauncher:
        def launch(self, *a, **kw):
            return FakeBrowser()

    class FakeBrowser:
        def __init__(self) -> None:
            self.chromium = ChromiumLauncher()

        def new_page(self, *a, **kw):
            return FakePage()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def close(self):
            pass

    # sync_playwright is imported lazily inside the function from
    # playwright.sync_api, so patch the module-level name it resolves to.
    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright",
        lambda: FakeBrowser(),
        raising=False,
    )

    start = time.monotonic()
    result = oc._fetch_with_browser(source, budget_seconds=45.0)
    elapsed = time.monotonic() - start

    # Contract: the session must have aborted well before the 45s ceiling
    # (it renders empty pages — no reason to keep paying), must NOT have
    # walked all 5 pages, and must report the empty-page error code
    # without claiming active jobs.
    assert result.error_code == "official_page_empty", (
        f"expected abort with official_page_empty, got {result.error_code!r}"
    )
    assert result.no_active_jobs, "an empty abort must signal that the page has no active jobs"
    assert len(call_log) < 5, (
        f"session navigated {len(call_log)} pages despite never emitting a job"
    )
    # 2 navigations (20s) must abort before the 45s deadline, and the abort
    # window itself must be honored to within one navigation.
    assert elapsed < 45.0, f"session ran {elapsed:.1f}s — no early abort happened"
    assert elapsed < 30.0, (
        f"session ran {elapsed:.1f}s despite no jobs within the 20s abort window"
    )


def test_playwright_abort_keeps_partial_jobs(monkeypatch):
    """Jobs emitted BEFORE the abort must be kept — the abort discards
    navigation budget, never work already done."""
    from sources import official_careers as oc
    from sources.official_careers import CareerSource
    from models import Job

    source = CareerSource(
        "cib", "Commercial International Bank", "Commercial International Bank",
        "egypt", "html",
        "https://careers.cibeg.com", "egypt",
        page_param="page", max_pages=5, browser_fallback=True,
    )
    monkeypatch.setattr("sources.official_careers.config.PLAYWRIGHT_ABORT_AFTER_SECONDS", 20)
    monkeypatch.setattr(
        "sources.official_careers._page_url",
        lambda src, n: f"{src.url}/p{n}",
    )

    call_log: list[str] = []

    class FakePage:
        def __init__(self) -> None:
            self.navigations = 0

        def set_default_timeout(self, _ms: int) -> None:
            pass

        def goto(self, url: str, **_kw) -> None:
            call_log.append(url)
            self.navigations += 1
            time.sleep(10)

        def content(self) -> str:
            return "<div id='job-listing'></div>"

    first_job = Job(
        title="SOC Analyst II", company="CIB", location="Cairo, Egypt",
        url="https://careers.cibeg.com/job/123", source="cib",
        posted_date=None, extraction_method="", provenance_hash="", geo_hint="",
    )

    def fake_jobs_from_html(html, src, **kw):
        if len(call_log) == 1:
            # First page: one real job.  The loop records
            # first_job_emitted_at and keeps navigating.
            return [first_job], True
        return [], False

    monkeypatch.setattr(
        "sources.official_careers._jobs_from_html", fake_jobs_from_html,
    )

    class ChromiumLauncher:
        def launch(self, *a, **kw):
            return FakeBrowser()

    class FakeBrowser:
        def __init__(self) -> None:
            self.chromium = ChromiumLauncher()

        def new_page(self, *a, **kw):
            return FakePage()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def close(self):
            pass

    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright", lambda: FakeBrowser(),
        raising=False,
    )

    result = oc._fetch_with_browser(source, budget_seconds=45.0)
    # Partial work is preserved even though the session aborted:
    assert result.jobs == [first_job], "partial jobs emitted before the abort were lost"
    assert result.error_code == "", (
        f"partial success must not carry an error code, got {result.error_code!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: pending-first delivery — queued senders go out before new jobs
# ---------------------------------------------------------------------------
def _pending_row_payload(title: str, company: str) -> dict:
    return {"job": {"title": title, "company": company}}


def _patch_telegram_sender(monkeypatch):
    import telegram_sender as ts
    monkeypatch.setattr(ts, "TELEGRAM_BOT_TOKEN", "test-token", raising=False)
    monkeypatch.setattr(ts, "TELEGRAM_CHAT_ID", "test-chat-id", raising=False)
    monkeypatch.setattr(ts.config, "DRY_RUN", False, raising=False)
    monkeypatch.setattr(ts.config, "MAX_JOBS_PER_CHANNEL", 10, raising=False)
    monkeypatch.setattr(ts.config, "MAX_JOB_AGE_DAYS", 7, raising=False)
    monkeypatch.setattr(ts.config, "MAX_JOB_AGE_HOURS", 72 * 24 * 7, raising=False)
    monkeypatch.setattr(ts.config, "DAILY_SEND_HOURS", 0, raising=False)
    monkeypatch.setattr(ts.config, "CYBER_LIKELY_MAX_SHARE", 1.0, raising=False)
    monkeypatch.setattr(ts.config, "TELEGRAM_SEND_DELAY", 0.0, raising=False)
    monkeypatch.setattr(
        ts, "_post_telegram_payload",
        lambda payload: (True, 200, "", None), raising=False,
    )
    monkeypatch.setattr(
        ts, "get_topic_thread_id", lambda ch: 1, raising=False,
    )
    monkeypatch.setattr(
        ts, "get_channel_evidence_for",
        lambda job, ch: (True, "geo"), raising=False,
    )
    # Give the run an unlimited clock so the budget never blocks a send.
    # The sender reads the budget through run_budget.budget_remaining, so
    # patch that function directly (its "remaining" name differs).
    import run_budget
    monkeypatch.setattr(
        run_budget, "budget_remaining",
        lambda phase=None: float("inf"), raising=False,
    )
    monkeypatch.setattr(
        ts, "_telegram_budget_remaining",
        lambda: float("inf"), raising=False,
    )


def test_pending_first_delivery_order(tmp_path, monkeypatch):
    """A ``delivery_pending`` row queued by the previous run must be
    attempted BEFORE any new reservation this run builds — and each of the
    two stages must be visible in its own telemetry counter."""
    import telegram_sender as ts
    from telegram_sender import send_jobs
    from database import JobsDB, set_delivery_run_at
    from models import Job, CyberVerdict

    _patch_telegram_sender(monkeypatch)

    db = JobsDB(str(tmp_path / "db.sqlite"))
    # Direct attribute assignment — telegram_sender imports get_db at module
    # level, and the string-form setattr failed silently under raising=False.
    ts.get_db = lambda: db

    with db._conn() as con:
        con.execute(
            """INSERT INTO telegram_delivery_outbox(
                   delivery_key, channel_key, thread_id, payload_json, status,
                   created_at, updated_at, sent_at)
               VALUES(?, ?, ?, ?, 'delivery_pending', ?, ?, NULL)""",
            (
                "pending-old-1", "egypt_cyber", 1,
                json.dumps(_pending_row_payload("Pending SOC Analyst", "Old Bank")),
                "2026-08-16T05:00:00", "2026-08-16T05:00:00",
            ),
        )
        con.commit()

    set_delivery_run_at("2026-08-18T05:00:00")
    call_order: list[str] = []
    monkeypatch.setattr(
        ts, "_post_telegram_payload",
        lambda payload: (
            call_order.append(payload.get("job", {}).get("title", "?")),
            True,
            200,
            "",
            None,
        )[-1] if False else (True, 200, "", None),
        raising=False,
    )
    # Record the order via the payload directly.
    payload_log: list[dict] = []

    def record_payload(payload):
        payload_log.append(payload)
        return True, 200, "", None

    monkeypatch.setattr(ts, "_post_telegram_payload", record_payload, raising=False)

    job = Job(
        title="Cloud Security Engineer", company="Vodafone Egypt",
        location="Cairo, Egypt", url="https://careers.vodafone.com/1",
        source="vodafone_eg", posted_date=None, extraction_method="",
        provenance_hash="", geo_hint="",
        cyber_verdict=CyberVerdict.CONFIRMED.value, cyber_probability=0.9,
    )

    send_jobs([job], dry_run=False)
    try:
        set_delivery_run_at(None)
    except Exception:
        pass

    # The pending sender from the previous run went out first — its queued
    # payload keeps the original {"job": {...}} shape, while the send loop
    # posts carry formatted HTML under "text".
    titles = [
        (p.get("job") or {}).get("title") if p.get("job") else p.get("text", "")
        for p in payload_log
    ]
    assert titles and titles[0] == "Pending SOC Analyst", (
        f"pending-first ordering broken: first call was {titles[:1]}"
    )
    assert any("Cloud Security Engineer" in t for t in titles), (
        f"the new eligible job never posted: {titles}"
    )


def test_pending_delivery_telemetry_counters(tmp_path, monkeypatch, caplog):
    """The pending row must be consumed (status advanced to sent) and the
    new job sent — queued senders never masquerade as new wins, and each
    stage gets its own telemetry field."""
    import logging
    caplog.set_level(logging.INFO, logger="telegram_sender")
    import telegram_sender as ts
    from telegram_sender import send_jobs
    from database import JobsDB, set_delivery_run_at
    from models import Job, CyberVerdict

    _patch_telegram_sender(monkeypatch)

    db = JobsDB(str(tmp_path / "db.sqlite"))
    ts.get_db = lambda: db

    with db._conn() as con:
        con.execute(
            """INSERT INTO telegram_delivery_outbox(
                   delivery_key, channel_key, thread_id, payload_json, status,
                   created_at, updated_at, sent_at)
               VALUES(?, ?, ?, ?, 'delivery_pending', ?, ?, NULL)""",
            (
                "pending-old-2", "egypt_cyber", 1,
                json.dumps(_pending_row_payload("Old Pending GRC", "X")),
                "2026-08-16T05:00:00", "2026-08-16T05:00:00",
            ),
        )
        con.commit()

    set_delivery_run_at("2026-08-18T05:00:00")
    job = Job(
        title="SOC Analyst", company="Acme", location="Cairo, Egypt",
        url="https://acme.example/2", source="acme",
        posted_date=None, extraction_method="", provenance_hash="",
        geo_hint="", cyber_verdict=CyberVerdict.CONFIRMED.value,
        cyber_probability=0.9,
    )

    send_jobs([job], dry_run=False)
    try:
        set_delivery_run_at(None)
    except Exception:
        pass

    with db._conn() as con:
        row = con.execute(
            "SELECT status FROM telegram_delivery_outbox "
            "WHERE delivery_key LIKE '%pending-old-2'",
        ).fetchone()
        new_job_row = con.execute(
            "SELECT status FROM telegram_delivery_outbox "
            "WHERE payload_json LIKE '%SOC Analyst%'",
        ).fetchone()
    assert row and row[0] == "sent", (
        f"pending row was not sent, still {row[0] if row else 'missing'}"
    )
    assert new_job_row and new_job_row[0] == "sent", (
        f"new eligible job was not sent, status {new_job_row[0] if new_job_row else 'missing'}"
    )

    # The lifecycle summary log must report the pending-first stage:
    # pending_before >= 1, at least one pending resend, and new_sent >= 1.
    lifecycle_log = next(
        (r for r in caplog.record_tuples
         if r[0] == "telegram_sender" and "delivery lifecycle" in r[2]),
        None,
    )
    assert lifecycle_log is not None, "lifecycle summary log never emitted"
    text = lifecycle_log[2]
    assert "pending_before=1" in text, text
    assert "pending_sent=1" in text, text
    assert "new_sent=1" in text, text


# ---------------------------------------------------------------------------
# Test 3: evidence enrichment raises LIKELY jobs with real context,
# and leaves the gate's threshold untouched for generic roles
# ---------------------------------------------------------------------------
def test_evidence_enrichment_preserves_gate(monkeypatch):
    from telegram_sender import _telegram_ineligibility_reason, _enrich_cyber_evidence
    from models import Job, CyberVerdict
    import telegram_sender as ts

    monkeypatch.setattr(
        ts, "resolve_delivery_location",
        lambda job: type("L", (), {"eligible": True, "reason_code": None})(),
        raising=False,
    )
    monkeypatch.setattr(
        ts, "_delivery_identity", lambda job: True, raising=False,
    )

    def make(title: str, description: str, company: str, verdict: str) -> Job:
        return Job(
            title=title, company=company, location="Cairo, Egypt",
            url="https://example.com/j", source="test",
            posted_date=None, extraction_method="", provenance_hash="",
            geo_hint="", cyber_verdict=verdict, cyber_probability=0.7,
            description=description,
        )

    # 1. Generic IT role: enrichment finds nothing publish-grade — still gated.
    generic_it = make(
        "Software Support Engineer",
        "Support our flagship SIEM appliance, resolve customer tickets, "
        "maintain documentation.",  # mentions siem in boilerplate
        "Generic Software Co", CyberVerdict.LIKELY.value,
    )
    _enrich_cyber_evidence(generic_it)
    assert _telegram_ineligibility_reason(generic_it) == "insufficient_cyber_evidence", (
        "generic IT roles mentioning security products in boilerplate must stay gated"
    )

    # 2. Security vendor workforce: the company IS the security context — passes.
    vendor_role = make(
        "Senior Software Engineer",
        "Build distributed detection pipelines at scale.",
        "CrowdStrike", CyberVerdict.LIKELY.value,
    )
    _enrich_cyber_evidence(vendor_role)
    assert _telegram_ineligibility_reason(vendor_role) is None, (
        "a genuine security vendor's workforce role must clear the enriched gate"
    )

    # 3. Security-adjacent title + real security skills in the description — passes.
    skilled_role = make(
        "Cloud Security Engineer",
        "Design CWPP/CNAPP posture controls, tune SIEM detections, "
        "lead incident response playbooks.",
        "Acme Bank", CyberVerdict.LIKELY.value,
    )
    _enrich_cyber_evidence(skilled_role)
    assert _telegram_ineligibility_reason(skilled_role) is None, (
        "a security title with real security skills in the description must clear the gate"
    )

    # 4. NON_CYBER never benefits from enrichment — stays rejected.
    non_cyber = make(
        "ERP Administrator",
        "Configure user provisioning, run reports, manage inventory.",
        "Acme", CyberVerdict.NON_CYBER.value,
    )
    _enrich_cyber_evidence(non_cyber)
    assert _telegram_ineligibility_reason(non_cyber) == "non_cyber_or_unclassified", (
        "NON_CYBER rows must never pass delivery, enriched or not"
    )

    # 5. CONFIRMED untouched — enrichment is irrelevant to it.
    confirmed = make(
        "Penetration Tester",
        "Run adversary simulations.",
        "Acme", CyberVerdict.CONFIRMED.value,
    )
    assert _telegram_ineligibility_reason(confirmed) is None


def test_enrichment_does_not_widen_skill_only_roles(monkeypatch):
    """A non-security title must not pass just because its description
    lists security tools — enrichment requires a security-adjacent title
    OR a security-vendor context, never skills alone."""
    from telegram_sender import _telegram_ineligibility_reason, _enrich_cyber_evidence
    from models import Job, CyberVerdict
    import telegram_sender as ts

    monkeypatch.setattr(
        ts, "resolve_delivery_location",
        lambda job: type("L", (), {"eligible": True, "reason_code": None})(),
        raising=False,
    )
    monkeypatch.setattr(
        ts, "_delivery_identity", lambda job: True, raising=False,
    )

    skills_only = Job(
        title="Full Stack Developer",
        company="Acme", location="Cairo, Egypt",
        url="https://example.com/dev", source="test",
        posted_date=None, extraction_method="", provenance_hash="", geo_hint="",
        cyber_verdict=CyberVerdict.LIKELY.value, cyber_probability=0.7,
        description=(
            "Build web apps. Nice to have: Splunk dashboards, OWASP "
            "compliance, firewall rule audits, and SOC monitoring tooling."
        ),
    )
    _enrich_cyber_evidence(skills_only)
    assert _telegram_ineligibility_reason(skills_only) == "insufficient_cyber_evidence", (
        "generic titles listing security skills in boilerplate must stay gated"
    )
