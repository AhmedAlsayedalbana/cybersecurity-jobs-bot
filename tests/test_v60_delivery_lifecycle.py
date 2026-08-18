"""Regression coverage for v60 delivery, parser, timeout, and telemetry work."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import os
import tempfile

import pytest

from database import JobsDB


def _temp_db() -> tuple[JobsDB, str]:
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    return JobsDB(handle.name), handle.name


def _remove_db(path: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        candidate = path + suffix
        if os.path.exists(candidate):
            os.remove(candidate)


def test_reserved_is_not_sent_and_delivery_is_channel_scoped():
    db, path = _temp_db()
    try:
        payload = {"chat_id": "1", "text": "test"}
        # v73: reserve now returns (reserved, delivery_proof); [0] is the
        # legacy boolean semantics.
        assert db.reserve_telegram_delivery(
            delivery_key="egypt:job-1", channel_key="egypt", thread_id=1, payload=payload,
        )[0]
        # An interrupted reservation must resume; it must not suppress a job.
        assert db.reserve_telegram_delivery(
            delivery_key="egypt:job-1", channel_key="egypt", thread_id=1, payload=payload,
        )[0]
        db.mark_telegram_delivery("egypt:job-1", status="sent")
        assert not db.reserve_telegram_delivery(
            delivery_key="egypt:job-1", channel_key="egypt", thread_id=1, payload=payload,
        )[0]
        # Same job ID is independent in another destination channel.
        assert db.reserve_telegram_delivery(
            delivery_key="soc:job-1", channel_key="soc", thread_id=2, payload=payload,
        )[0]
    finally:
        _remove_db(path)


def test_send_failed_has_exactly_one_retry_budget():
    import database
    db, path = _temp_db()
    try:
        payload = {"chat_id": "1", "text": "test"}
        key = "remote:job-2"
        # Anchor every reservation in this test to "now" so the same-run
        # exhaustion semantics are exercised end to end.
        database.set_delivery_run_at("1999-01-01T00:00:00")
        try:
            assert db.reserve_telegram_delivery(
                delivery_key=key, channel_key="remote", thread_id=1, payload=payload,
            )[0]
            db.mark_telegram_delivery(key, status="send_failed", error="503")
            assert db.reserve_telegram_delivery(
                delivery_key=key, channel_key="remote", thread_id=1, payload=payload,
            )[0]
            db.mark_telegram_delivery(key, status="send_failed", error="503")
            # Within the same run, an exhausted pair is suppressed once more.
            assert not db.reserve_telegram_delivery(
                delivery_key=key, channel_key="remote", thread_id=1, payload=payload,
            )[0]
        finally:
            database.set_delivery_run_at(None)
    finally:
        _remove_db(path)


def test_retry_exhausted_row_recovers_in_a_new_run():
    """v62: a legacy ``send_failed`` row with exhausted retries must never
    block the first real send when the reservation arrives in a new run."""
    import database
    db, path = _temp_db()
    try:
        payload = {"chat_id": "1", "text": "test"}
        key = "remote:job-legacy"
        # Simulate a row left over from a previous run: exhausted retries,
        # created before the current run anchor.
        with db._conn() as con:
            con.execute(
                """INSERT INTO telegram_delivery_outbox(
                    delivery_key, channel_key, thread_id, payload_json, status,
                    created_at, updated_at, sent_at, attempts
                ) VALUES(?,?,?,?, 'send_failed', ?, ?, NULL, 2)""",
                (key, "remote", 1, "{}", "1999-01-01T00:00:00", "1999-01-01T00:00:00"),
            )
        # The new run anchors after the legacy row.
        database.set_delivery_run_at("2000-01-01T00:00:00")
        try:
            assert db.reserve_telegram_delivery(
                delivery_key=key, channel_key="remote", thread_id=1, payload=payload,
            )[0]
            with db._conn() as con:
                row = con.execute(
                    "SELECT status, attempts FROM telegram_delivery_outbox "
                    "WHERE delivery_key=?", (key,),
                ).fetchone()
            assert row["status"] == "reserved"
            assert row["attempts"] == 0
        finally:
            database.set_delivery_run_at(None)
    finally:
        _remove_db(path)


def test_cyber_confirmed_passes_delivery_without_evidence(monkeypatch):
    """v62: CYBER_CONFIRMED with a valid location and identity never re-
    rejects at delivery for conflicting evidence; CYBER_LIKELY still must
    demonstrate publish-grade cyber evidence."""
    import telegram_sender
    from models import Job, CyberVerdict

    def make_job(title: str, verdict: str, tags=None):
        return Job(
            title=title,
            company="Acme",
            url=f"https://example.com/{title.replace(' ', '-')}",
            source="linkedin_jobs",
            location="Cairo, Egypt",
            tags=tags or [],
            description="",
            content_type="",
            cyber_verdict=verdict,
        )

    job_confirmed = make_job("Sr Analyst, IT Infrastructure", CyberVerdict.CONFIRMED.value)
    # No explicit title evidence, no skill tags: the delivery evidence gate
    # would normally return insufficient_cyber_evidence for this title.
    assert telegram_sender._telegram_ineligibility_reason(job_confirmed) is None

    job_likely = make_job("Solutions Engineer", CyberVerdict.LIKELY.value)
    assert telegram_sender._telegram_ineligibility_reason(job_likely) == "insufficient_cyber_evidence"

    job_likely_with_skills = make_job(
        "Solutions Engineer", CyberVerdict.LIKELY.value,
        tags=["SIEM", "incident response", "EDR"],
    )
    assert telegram_sender._telegram_ineligibility_reason(job_likely_with_skills) is None


def test_deadline_timeout_never_quarantines_a_source():
    """v63: a run-phase budget deadline (source_timeout) is the
    orchestrator's wall clock, not the source's own failure — it must never
    compound into quarantine or failure streaks, otherwise a slow run strands
    healthy sources for 3 hours."""
    db, path = _temp_db()
    try:
        for _ in range(6):
            db.update_source_health_state(
                "aaib", success=False, jobs_count=0, error_code="source_timeout",
                auto_disable_threshold=4, quarantine_minutes=180,
                deadline_timeout=True, is_priority_source=True,
            )
        assert db.can_run_source("aaib")
        with db._conn() as con:
            row = con.execute(
                "SELECT failure_streak, quarantined_until FROM source_health_state "
                "WHERE source_key='aaib'"
            ).fetchone()
        assert not row["quarantined_until"]

        # A genuine transport failure still compounds normally.
        for _ in range(4):
            db.update_source_health_state(
                "some_bank", success=False, jobs_count=0, error_code="http_403",
                auto_disable_threshold=4, quarantine_minutes=180,
            )
        assert not db.can_run_source("some_bank")
    finally:
        _remove_db(path)


def test_priority_source_real_failures_do_not_quarantine():
    """v63: Egyptian priority sources keep attempting across genuine transient
    failures (their 90s budget already grants a fair full attempt per run).
    Only explicit operator quarantine (``quarantined_until`` set outside this
    path) can disable them."""
    db, path = _temp_db()
    try:
        for _ in range(10):
            db.update_source_health_state(
                "nbe", success=False, jobs_count=0, error_code="playwright_error",
                auto_disable_threshold=4, quarantine_minutes=180,
                is_priority_source=True,
            )
        assert db.can_run_source("nbe")
        with db._conn() as con:
            row = con.execute(
                "SELECT quarantined_until FROM source_health_state "
                "WHERE source_key='nbe'"
            ).fetchone()
        assert not row["quarantined_until"]
    finally:
        _remove_db(path)


def test_send_failed_is_retried_once_then_recorded_sent(monkeypatch):
    import telegram_sender

    db, path = _temp_db()
    attempts = []
    try:
        monkeypatch.setattr(telegram_sender, "TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setattr(telegram_sender, "TELEGRAM_CHAT_ID", "1")

        def post_once_then_succeed(_payload):
            attempts.append(True)
            return (False, 503, "temporary", None) if len(attempts) == 1 else (True, 200, "", None)

        monkeypatch.setattr(telegram_sender, "_post_telegram_payload", post_once_then_succeed)
        lifecycle: Counter[str] = Counter()
        assert telegram_sender._send_to_topic(
            "message", thread_id=1, db=db, channel_key="egypt", delivery_key="job-3",
            lifecycle=lifecycle,
        )
        assert len(attempts) == 2
        assert lifecycle == Counter(reserved=1, sent=1)
        with db._conn() as con:
            row = con.execute(
                "SELECT status, sent_at, attempts FROM telegram_delivery_outbox "
                "WHERE delivery_key='egypt:job-3'"
            ).fetchone()
        assert row["status"] == "sent"
        assert row["sent_at"]
        assert row["attempts"] == 2
    finally:
        _remove_db(path)


@pytest.mark.parametrize(
    "spec_key",
    ("wuzzuf", "bayt", "gulftalent", "tanqeeb", "akhtaboot", "upwork", "mostaql", "freelancer"),
)
def test_important_marketplace_parsers_accept_current_json_field_variants(spec_key):
    from sources.marketplace_sources import SPECS_BY_KEY, _parse

    spec = SPECS_BY_KEY[spec_key]
    content = (
        '{"results":[{"jobTitle":"Cybersecurity Analyst",'
        '"detail_url":"/jobs/cybersecurity-analyst-123",'
        f'"publishedAt":"{datetime.now().isoformat(timespec="seconds")}",'
        '"shortDescription":"SIEM and incident response security role"}]}'
    )
    jobs = _parse(content, spec, spec.urls[0], "direct")
    assert len(jobs) == 1
    assert jobs[0].source_key == spec_key


def test_reachable_unparsed_marketplace_is_parse_changed_not_healthy(monkeypatch):
    import sources.marketplace_sources as marketplace

    class TextResult:
        text = "<html><body>new client markup</body></html>"

    monkeypatch.setattr(marketplace, "get_text_result", lambda *_args, **_kwargs: TextResult())
    monkeypatch.setattr(marketplace, "_fetch_via_jina", lambda _url: "No recognisable public cards")

    result = marketplace.fetch_marketplace("wuzzuf")

    assert result.status == "parse_changed"
    assert result.error_code == "wuzzuf_parser_unrecognized"


def test_source_timeout_classes_leave_linkedin_budget_untouched():
    import config
    from sources.source_registry import get_source_specs

    specs = {spec.key: spec for spec in get_source_specs()}
    assert specs["wuzzuf"].source_timeout_seconds is None
    assert specs["ibm_egypt"].source_timeout_seconds == config.CAREERS_API_SOURCE_TIMEOUT_SECONDS
    # v62: Egyptian priority sources carry a dedicated budget so the shared
    # playwright cap can never kill a JS-only careers render there.
    if "cib_egypt" in config.EGYPT_PRIORITY_SOURCE_KEYS:
        assert specs["cib_egypt"].source_timeout_seconds == config.EGYPT_PRIORITY_SOURCE_TIMEOUT_SECONDS
    else:
        assert specs["cib_egypt"].source_timeout_seconds == config.PLAYWRIGHT_SOURCE_TIMEOUT_SECONDS
    assert specs["linkedin_unified"].source_timeout_seconds is None
