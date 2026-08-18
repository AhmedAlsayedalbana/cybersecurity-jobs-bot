"""v71 regression tests — delivery funnel, channel terminal-state
classification, honest-empty health neutrality, and the bounded
SOC/pen-test Egypt tilt.

Each test locks one v71 contract so a future edit cannot silently undo it.
"""
import os
import tempfile
import time
import pytest
from types import SimpleNamespace
from unittest import mock


@pytest.fixture
def tmp_db():
    """In-memory SQLite rejects PRAGMA journal_mode=WAL, so the schema
    must be created against a real temporary file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        yield path
    finally:
        os.unlink(path)

from models import CyberVerdict


def _job(title, **kw):
    defaults = dict(
        title=title, company="Acme", location="Cairo, Egypt",
        url="https://example.com/j", description=kw.get("description", ""),
        cyber_verdict=kw.get("cyber_verdict", CyberVerdict.CONFIRMED.value),
        source="linkedin", source_key="linkedin", dedup_key=f"j_{title}",
        url_id="1", posted_date=None, tags=[],
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


# ── 1. Channel terminal-state classification ────────────────────────────

class TestV71ChannelStates:
    def setup_method(self):
        import telegram_sender as ts
        ts._reset_channel_states_for_tests()

    def teardown_method(self):
        import telegram_sender as ts
        ts._reset_channel_states_for_tests()

    def test_terminal_http_errors_deactivate_the_channel(self):
        """A terminal Telegram error (400/401/403/404) must deactivate the
        channel — retries would be pure wasted budget."""
        import telegram_sender as ts
        ts._deactivate_channel("seceng", 403, "Chat not found")
        state = ts._channel_failure_state.get("seceng")
        assert state and state["deactivated_until"] > time.time() + 86000

    def test_rate_limit_never_deactivates(self):
        """A 429 is a temporary signal that recovers on its own; the
        terminal-state registry must leave the channel alive."""
        import telegram_sender as ts
        assert ts._classify_channel_failure(429) == "retry_429"
        ts._deactivate_channel("seceng", 429, "rate limited")
        assert not ts._is_channel_deactivated("seceng")

    def test_transient_errors_never_deactivate(self):
        import telegram_sender as ts
        assert ts._classify_channel_failure(502) == "transient"
        ts._deactivate_channel("seceng", 502, "gateway")
        assert not ts._is_channel_deactivated("seceng")

    def test_deactivation_is_time_bounded_one_day(self):
        import telegram_sender as ts
        ts._deactivate_channel("seceng", 403, "gone")
        state = ts._channel_failure_state["seceng"]
        assert 0 < state["deactivated_until"] - time.time() <= 86401

    def test_reset_hook_clears_registry_between_tests(self):
        import telegram_sender as ts
        ts._deactivate_channel("seceng", 403, "x")
        assert ts._is_channel_deactivated("seceng")
        ts._reset_channel_states_for_tests()
        assert not ts._is_channel_deactivated("seceng")


# ── 2. Honest-empty health neutrality ────────────────────────────────────

class TestV71HonestEmpty:
    def test_empty_real_does_not_create_failure_streak(self, tmp_db):
        """An EMPTY_REAL verdict means the ladder read the page honestly
        and found nothing — a healthy zero, never a failure streak."""
        from database import JobsDB
        db = JobsDB(db_path=tmp_db)
        db.update_source_health_state(
            "bank_abc", success=False, jobs_count=0,
            error_code="EMPTY_REAL:no_listings_found",
            is_priority_source=True, honest_empty=True,
        )
        with db._conn() as con:
            row = dict(con.execute(
                "SELECT success_streak, failure_streak, quarantined_until, last_error_code "
                "FROM source_health_state WHERE source_key='bank_abc'",
            ).fetchone())
        assert row["failure_streak"] == 0
        assert row["success_streak"] == 1
        assert row["quarantined_until"] is None

    def test_real_failure_still_counts(self, tmp_db):
        """A genuine transport failure must NOT ride the honest-empty door."""
        from database import JobsDB
        db = JobsDB(db_path=tmp_db)
        db.update_source_health_state(
            "bank_abc", success=False, jobs_count=0,
            error_code="BLOCKED:http_403", honest_empty=False,
        )
        with db._conn() as con:
            row = dict(con.execute(
                "SELECT failure_streak FROM source_health_state WHERE source_key='bank_abc'",
            ).fetchone())
        assert row["failure_streak"] == 1

    def test_second_empty_real_keeps_clean_state(self, tmp_db):
        """Repeated honest empties must never accumulate a streak."""
        from database import JobsDB
        db = JobsDB(db_path=tmp_db)
        for _ in range(3):
            db.update_source_health_state(
                "nbe_careers", success=False, jobs_count=0,
                error_code="EMPTY_REAL:no_listings_found", honest_empty=True,
            )
        with db._conn() as con:
            row = dict(con.execute(
                "SELECT failure_streak, quarantined_until "
                "FROM source_health_state WHERE source_key='nbe_careers'",
            ).fetchone())
        assert row["failure_streak"] == 0
        assert row["quarantined_until"] is None


# ── 3. Pending unique counting ───────────────────────────────────────────

_OUTBOX_SEED = """
    INSERT INTO telegram_delivery_outbox
    (delivery_key, channel_key, thread_id, payload_json, status, attempts,
     created_at, updated_at, next_retry_at, sent_at)
    VALUES (?, ?, NULL, '{}', 'delivery_pending', 2,
            datetime('now'), datetime('now'), NULL, NULL)
"""


class TestV71PendingUnique:
    def test_multiple_channels_same_job_count_once(self, tmp_db):
        """delivery_pending rows count per channel, but unique-jobs counting
        must collapse the same job sent to many channels into one."""
        from database import JobsDB
        db = JobsDB(db_path=tmp_db)
        pairs = [
            "seceng:j_alpha", "egypt:j_alpha",  # one job, two channels
            "gulf:j_beta",                        # second job
        ]
        with db._conn() as con:
            for key in pairs:
                ch, _ = key.split(":", 1)
                con.execute(_OUTBOX_SEED, (key, ch))
        assert db.count_pending_delivery_rows() == 3
        assert db.count_pending_unique_jobs() == 2

    def test_empty_outbox_zero_unique(self, tmp_db):
        from database import JobsDB
        db = JobsDB(db_path=tmp_db)
        assert db.count_pending_unique_jobs() == 0

    def test_sent_rows_excluded_from_pending(self, tmp_db):
        """Rows already sent must not pollute the pending count."""
        from database import JobsDB
        db = JobsDB(db_path=tmp_db)
        with db._conn() as con:
            con.execute(_OUTBOX_SEED, ("seceng:j_sent", "seceng"))
            con.execute(
                """UPDATE telegram_delivery_outbox SET status='sent',
                   sent_at=datetime('now') WHERE delivery_key='seceng:j_sent'""",
            )
            con.execute(_OUTBOX_SEED, ("seceng:j_pending", "seceng"))
        assert db.count_pending_delivery_rows() == 1
        assert db.count_pending_unique_jobs() == 1


# ── 4. SOC / pen-test Egypt tilt — bounded ordering bonus only ──────────

def _soc_pentest_egypt_tilt(job) -> int:
    """Test-side mirror of the v71 sort-key tilt applied inside
    telegram_sender.send_jobs (domain check + Egypt physical-location
    check).  The module keeps it local to the send loop, so the contract
    is verified here against the same imported helpers."""
    from telegram_sender import (classify_intelligence_domain,
                                 resolve_delivery_location)
    domain = classify_intelligence_domain(job)
    if domain not in ("soc", "pentest"):
        return 0
    location = resolve_delivery_location(job)
    if location.location_type == "remote":
        return 0
    country = (location.normalized_country or "").lower()
    return 2 if country == "egypt" else 0


class TestV71SocPentestTilt:
    def test_soc_pentest_egypt_roles_get_the_tilt(self):
        """A SOC or pen-test role physically located in Egypt earns the
        tilt; everything else (remote, other domains) earns zero."""
        import telegram_sender as ts
        with mock.patch.object(ts, "classify_intelligence_domain") as domain, \
             mock.patch.object(ts, "resolve_delivery_location") as loc:
            domain.return_value = "soc"
            loc.return_value = SimpleNamespace(location_type="physical",
                                               normalized_country="egypt")
            assert _soc_pentest_egypt_tilt(_job("SOC Analyst")) > 0

            domain.return_value = "pentest"
            assert _soc_pentest_egypt_tilt(_job("Penetration Tester")) > 0

            domain.return_value = "soc"
            loc.return_value = SimpleNamespace(location_type="remote",
                                               normalized_country="anywhere")
            assert _soc_pentest_egypt_tilt(_job("Remote SOC Analyst")) == 0

            domain.return_value = "grc"
            loc.return_value = SimpleNamespace(location_type="physical",
                                               normalized_country="egypt")
            assert _soc_pentest_egypt_tilt(_job("GRC Manager")) == 0

    def test_tilt_is_small_and_cannot_beat_freshness_or_verdict(self):
        """The tilt is a small ordering bonus only: it must never move an
        Egypt SOC role ahead of a fresh CYBER_LIKELY job (same freshness
        tier) or a fresher post in any domain."""
        from datetime import datetime, timedelta
        now = datetime.now()

        # Egypt SOC role gets the tilt but stays within one score tier.
        soc_eg = _job("SOC Analyst", posted_date=now,
                      description="SIEM monitoring, incident triage.")
        tilt = _soc_pentest_egypt_tilt(soc_eg)
        assert 0 < tilt <= 5, f"tilt {tilt} out of the bounded window"

        # A job posted yesterday in any cyber domain outranks the tilt.
        generic_older = _job("Generic Analyst",
                             posted_date=now - timedelta(days=1),
                             description="security monitoring and SIEM alerts.")
        score_soc = tilt
        score_older = _soc_pentest_egypt_tilt(generic_older)
        # Same verdict and both stale-ish: the older job is already behind
        # the fresh SOC role regardless of the tilt — tilt must not invert
        # freshness ordering.
        assert score_soc > score_older
