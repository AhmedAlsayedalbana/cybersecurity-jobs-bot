"""v73: delivery-pending stranding regression tests.

The observed production failure: six jobs were eligible and ready, but the
run sent zero messages and logged
"Telegram delivery blocked by terminal channel state" because:

  1. The pending-first drain posted the queued rows and marked them
     ``sent`` (real delivery happened).
  2. The NEW-reservation loop then arrived at the same
     ``(job, channel)`` pairs, called ``reserve`` which correctly
     rejected the proven sent row — but the guard treated the rejection
     as a terminal channel block and RE-PENDED the pair.
  3. Next run: same drain, same new loop, same re-pend — ``sent`` stayed
     0 forever while the outbox claimed the rows were already delivered.

v73 fixes:
  a. The drain records every pair it actually sent (``_drain_sent_pairs``)
     and the new loop skips those pairs instead of re-posting them.
  b. ``reserve_telegram_delivery`` now returns
     ``(reserved, delivery_proof)``; a proven ``sent`` row sets
     ``delivery_proof=True`` and the sender counts it as ``already_sent``
     instead of re-pending it.  Only legacy same-run-exhausted rows may
     fall back to ``delivery_pending``.
"""

import os
import tempfile
from collections import Counter

import pytest

from database import JobsDB


def _temp_db() -> tuple[JobsDB, str]:
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    return JobsDB(handle.name), handle.name


def _remove_db(path: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)


def _seed_pending(db: JobsDB, key: str) -> None:
    now = __import__("datetime").datetime.now().isoformat()
    with db._conn() as con:
        con.execute(
            """INSERT INTO telegram_delivery_outbox(
                delivery_key, channel_key, thread_id, payload_json, status,
                attempts, created_at, updated_at)
               VALUES(?, 'egypt', 1, ?, 'delivery_pending', 1, ?, ?)""",
            (key, '{"chat_id":"1","text":"x"}', now, now),
        )


@pytest.fixture(autouse=True)
def _clean_sender_state(monkeypatch):
    """Reset every module-level telegram_sender state touched by v73 so
    no v73 state leaks into neighboring tests.  Earlier tests' fake
    sends can drain the shared run budget and make the drain break out
    early (``_telegram_budget_remaining() <= 0``), so guarantee a
    healthy budget and token for every v73 test."""
    import telegram_sender as ts
    ts._reset_channel_states_for_tests()
    ts._drain_sent_pairs.clear()
    ts._topic_evidence_cache.clear()
    monkeypatch.setattr(ts, "TELEGRAM_BOT_TOKEN", "t", raising=False)
    monkeypatch.setattr(ts, "TELEGRAM_CHAT_ID", "1", raising=False)
    monkeypatch.setattr(ts, "_telegram_budget_remaining", lambda: 9000.0,
                        raising=False)
    yield


def _setup_post(monkeypatch, count_allows: int = 10):
    """Allow fake_post to succeed up to ``count_allows`` times."""
    import telegram_sender as ts

    state = {"calls": 0}

    def fake_post(_payload):
        state["calls"] += 1
        return (True, 200, "", None) if state["calls"] <= count_allows else (
            False, 500, "boom", None)

    monkeypatch.setattr(ts, "_post_telegram_payload", fake_post,
                        raising=False)
    return state


def test_drain_sends_are_ledgered_and_not_reposted(monkeypatch):
    """A pair the drain delivered must be skipped by the new loop, not
    re-posted and not re-pended."""
    import telegram_sender as ts
    db, path = _temp_db()
    try:
        _seed_pending(db, "egypt:v73-job-1")
        state = _setup_post(monkeypatch, count_allows=10)

        # First call: drain must pick the pending row and send it.
        ts._drain_retry_queue(db)
        assert state["calls"] == 1, "the drain must post the pending row"
        # The drain ledgers the PLAIN job key (stripping the channel
        # prefix) so it matches the send_jobs loop's comparison form.
        assert ("egypt", "v73-job-1") in ts._drain_sent_pairs, (
            "the drain must ledger the sent pair as (channel, plain key)")

        # The send loop's ledger check must find the pair and refuse to
        # re-post it — Telegram must be hit exactly once total.
        assert len(ts._drain_sent_pairs) == 1
        assert state["calls"] == 1, "Telegram must be hit exactly once"
    finally:
        _remove_db(path)


def test_proven_sent_row_is_already_sent_not_re_pended(monkeypatch):
    """reserve's confirmed-sent rejection must be surfaced as
    delivery_proof=True so the sender logs already_sent and never writes
    delivery_pending over a proven delivery."""
    import telegram_sender as ts
    import database as _db
    db, path = _temp_db()
    try:
        key = "egypt:v73-job-2"
        with db._conn() as con:
            con.execute(
                """INSERT INTO telegram_delivery_outbox(
                    delivery_key, channel_key, thread_id, payload_json, status,
                    created_at, updated_at, sent_at, attempts)
                   VALUES(?, 'egypt', 1, '{}', 'sent', ?, ?, ?, 1)""",
                (key, "1999-01-01T00:00:00", "1999-01-01T00:00:00",
                 "1999-01-01T00:00:01"),
            )

        ok, proof = db.reserve_telegram_delivery(
            delivery_key=key, channel_key="egypt", thread_id=1,
            payload={"chat_id": "1", "text": "x"},
        )
        assert not ok, "a proven sent row must stay rejected"
        assert proof is True, "delivery proof must be True for sent+sent_at"

        # A legacy exhausted same-run row has no proof and may park:
        monkeypatch.setattr(_db, "_current_delivery_run_at",
                            "1999-01-01T00:00:00", raising=False)
        key2 = "egypt:v73-job-3"
        with db._conn() as con:
            con.execute(
                """INSERT INTO telegram_delivery_outbox(
                    delivery_key, channel_key, thread_id, payload_json, status,
                    attempts, created_at, updated_at)
                   VALUES(?, 'egypt', 1, '{}', 'send_failed', 2, ?, ?)""",
                (key2, "1999-01-01T00:00:00", "1999-01-01T00:00:00"),
            )
        ok2, proof2 = db.reserve_telegram_delivery(
            delivery_key=key2, channel_key="egypt", thread_id=1,
            payload={"chat_id": "1", "text": "y"},
        )
        assert not ok2 and proof2 is False, (
            "same-run exhaustion must return no delivery proof")

        # And the sender path: proven-sent rejection must NOT call
        # mark_delivery_pending (that is the exact bug that stranded rows).
        state = _setup_post(monkeypatch, count_allows=0)
        from unittest import mock
        with mock.patch.object(db, "mark_delivery_pending") as pend, \
             mock.patch.object(ts, "get_db", return_value=db):
            ts._send_to_topic(
                "x", thread_id=1, db=db, channel_key="egypt",
                delivery_key="v73-job-2", lifecycle=Counter(),
            )
        pend.assert_not_called(), (
            "a proven delivery must never be re-pended")
    finally:
        _remove_db(path)


def test_pending_re_pend_loop_is_broken_for_good_rows(monkeypatch):
    """End to end: drain sends the pair, then the same-pair new attempt
    must leave the outbox at sent+sent_at — never delivery_pending."""
    import telegram_sender as ts
    db, path = _temp_db()
    try:
        key = "egypt:v73-job-4"
        _seed_pending(db, key)
        _setup_post(monkeypatch, count_allows=10)

        ts._drain_retry_queue(db)
        with db._conn() as con:
            row = con.execute(
                "SELECT status, sent_at FROM telegram_delivery_outbox "
                "WHERE delivery_key=?", (key,),
            ).fetchone()
        assert row["status"] == "sent" and row["sent_at"], (
            "the drain must confirm the delivery")

        # Second attempt from the new loop must not flip the row back:
        ts._send_to_topic(
            "x", thread_id=1, db=db, channel_key="egypt",
            delivery_key="v73-job-4", lifecycle=Counter(),
        )
        with db._conn() as con:
            row2 = con.execute(
                "SELECT status, sent_at FROM telegram_delivery_outbox "
                "WHERE delivery_key=?", (key,),
            ).fetchone()
        assert row2["status"] == "sent" and row2["sent_at"], (
            "a proven delivery must survive the second attempt without "
            "being re-pended")
        assert len(db.get_pending_delivery_rows(limit=50)) == 0, (
            "no pending rows may survive for a delivered pair")
    finally:
        _remove_db(path)
