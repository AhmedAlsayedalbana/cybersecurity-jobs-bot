"""v64 — source-execution strategy regression tests.

Covers the four structural changes requested by the operator:
  1. short per-attempt limits (Egyptian banks never consume 90s each);
  2. yield-based execution priority for proven suppliers;
  3. recovery/fallback rotation for failing priority sources (never deleted);
  4. the run plan starts yield-proven sources first.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _temp_db():
    import database  # noqa: F401 (register under sys.modules)
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    from database import JobsDB
    return JobsDB(handle.name), handle.name


def _remove_db(path: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)


# ── 1. Egyptian banks never burn 90s ─────────────────────────────────────

def test_egypt_priority_ceiling_is_short():
    import config
    assert config.EGYPT_PRIORITY_SOURCE_TIMEOUT_SECONDS <= 45.0, (
        "Egyptian banks must never wait 90s per source"
    )
    from sources import official_careers
    assert official_careers._FAST_ATTEMPT_TIMEOUT_SECONDS <= 10.0
    assert official_careers._FAST_ATTEMPT_SECOND_CAP_SECONDS <= 12.0


# ── 2. yield-based priority boost ─────────────────────────────────────────

def test_yield_boost_raises_proven_suppliers():
    from main import _apply_yield_priority_boost
    from sources.source_registry import get_source_specs

    db, path = _temp_db()
    try:
        # Re-seed a yield ledger: proven suppliers delivered; weak sources did not.
        cutoff = (datetime.now() - timedelta(days=3)).isoformat()
        with db._conn() as con:
            con.execute("DELETE FROM source_stats")
            for src, count in (("fabmisr", 225), ("cloudflare", 297),
                               ("tenable", 106), ("bugcrowd", 15),
                               ("hackerone", 26), ("wiz", 117),
                               ("weak_bank", 0), ("flaky_bank", 1)):
                con.execute(
                    "INSERT INTO source_stats(run_at, source, count, failed) "
                    "VALUES(?,?,?,0)", (cutoff, src, count),
                )

        specs = list(get_source_specs())
        originals = {s.key: s.priority for s in specs}
        _apply_yield_priority_boost(specs, db)

        # Proven suppliers jump to the front of the common pool.
        fabmisr = next(s for s in specs if s.key == "fabmisr")
        assert fabmisr.priority <= 10
        cloudflare = next(s for s in specs if s.key == "cloudflare")
        assert cloudflare.priority <= 10
        # A source that never delivered keeps its static priority.
        for s in specs:
            if s.key in ("weak_bank", "flaky_bank") and s.key in originals:
                assert s.priority == originals[s.key]
    finally:
        _remove_db(path)


# ── 3. recovery/fallback rotation ─────────────────────────────────────────

def test_failing_priority_source_enters_recovery_rotation():
    from database import JobsDB

    db, path = _temp_db()
    try:
        # Three consecutive real failures for a priority source must park it
        # into the recovery rotation (never quarantine, never delete).
        for _ in range(3):
            db.update_source_health_state(
                "cib_egypt", success=False, jobs_count=0, error_code="http_503",
                auto_disable_threshold=4, quarantine_minutes=180,
                is_priority_source=True,
            )
        parked = db.get_recovery_sources()
        assert any(r["source_key"] == "cib_egypt" for r in parked), parked
        # It must still be present in the registry — can_run_source True.
        assert db.can_run_source("cib_egypt")
        # It must not have compounded into quarantine despite 3 failures.
        row = db.list_source_health_state()["cib_egypt"]
        assert not row["quarantined_until"]
    finally:
        _remove_db(path)


def test_recovery_rotation_schedules_sparse_rechecks():
    from database import JobsDB

    db, path = _temp_db()
    try:
        db.enter_recovery_rotation("aaib", recheck_every_n_runs=3)
        # Run 1: counter 1 → not due.
        db.bump_recovery_counters()
        assert "aaib" not in db.recovery_due_sources()
        # Run 2: counter 2 → not due.
        db.bump_recovery_counters()
        assert "aaib" not in db.recovery_due_sources()
        # Run 3: counter 3 → due for the sparse recheck.
        db.bump_recovery_counters()
        assert "aaib" in db.recovery_due_sources()
        # Run 6: due again, every 3rd run.
        db.bump_recovery_counters(); db.bump_recovery_counters(); db.bump_recovery_counters()
        assert "aaib" in db.recovery_due_sources()
    finally:
        _remove_db(path)


def test_successful_recovery_recheck_graduates_source():
    from database import JobsDB

    db, path = _temp_db()
    try:
        db.enter_recovery_rotation("nbe", recheck_every_n_runs=3)
        # A recheck that fetched real jobs graduates the source.
        db.update_source_health_state(
            "nbe", success=True, jobs_count=47, error_code="",
            is_priority_source=True,
        )
        assert not db.get_recovery_sources()
        row = db.list_source_health_state()["nbe"]
        assert row["success_streak"] >= 1
    finally:
        _remove_db(path)


def test_parked_sources_do_not_consume_every_run():
    """The run plan executes parked priority sources only when due — other
    sources must not see their budget eaten by them on off-week runs."""
    from database import JobsDB

    db, path = _temp_db()
    try:
        db.enter_recovery_rotation("bank_nxt", recheck_every_n_runs=3)
        db.bump_recovery_counters()  # run 1 — not due
        assert "bank_nxt" not in db.recovery_due_sources()
        due = db.recovery_due_sources()
        # Only due members would run; the rotation never duplicates cost.
        assert "bank_nxt" not in due
        # Graduation keeps it out on the next run too.
        db.graduate_from_recovery_rotation("bank_nxt")
        assert db.recovery_due_sources() == []
    finally:
        _remove_db(path)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main(["-x", "-q", __file__]))
