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
        assert db.reserve_telegram_delivery(
            delivery_key="egypt:job-1", channel_key="egypt", thread_id=1, payload=payload,
        )
        # An interrupted reservation must resume; it must not suppress a job.
        assert db.reserve_telegram_delivery(
            delivery_key="egypt:job-1", channel_key="egypt", thread_id=1, payload=payload,
        )
        db.mark_telegram_delivery("egypt:job-1", status="sent")
        assert not db.reserve_telegram_delivery(
            delivery_key="egypt:job-1", channel_key="egypt", thread_id=1, payload=payload,
        )
        # Same job ID is independent in another destination channel.
        assert db.reserve_telegram_delivery(
            delivery_key="soc:job-1", channel_key="soc", thread_id=2, payload=payload,
        )
    finally:
        _remove_db(path)


def test_send_failed_has_exactly_one_retry_budget():
    db, path = _temp_db()
    try:
        payload = {"chat_id": "1", "text": "test"}
        key = "remote:job-2"
        assert db.reserve_telegram_delivery(
            delivery_key=key, channel_key="remote", thread_id=1, payload=payload,
        )
        db.mark_telegram_delivery(key, status="send_failed", error="503")
        assert db.reserve_telegram_delivery(
            delivery_key=key, channel_key="remote", thread_id=1, payload=payload,
        )
        db.mark_telegram_delivery(key, status="send_failed", error="503")
        assert not db.reserve_telegram_delivery(
            delivery_key=key, channel_key="remote", thread_id=1, payload=payload,
        )
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
    assert specs["cib_egypt"].source_timeout_seconds == config.PLAYWRIGHT_SOURCE_TIMEOUT_SECONDS
    assert specs["linkedin_unified"].source_timeout_seconds is None
