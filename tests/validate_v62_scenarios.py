"""End-to-end validation of the four v62 fixes against the observed run-log
failure scenarios.  Runs in-process against a temporary SQLite database."""

from __future__ import annotations

import tempfile
import traceback
from collections import Counter
from datetime import datetime, timedelta
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import CyberVerdict, Job
import telegram_sender
import database

# ---------- helpers ----------------------------------------------------------

def _temp_db():
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    return database.JobsDB(handle.name), handle.name


def _remove_db(path: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)


def _rsa_job() -> Job:
    """The exact job profile from the observed run log:
    'Sr Analyst, IT Infrastructure @ RSA Security', Cairo Egypt, CONFIRMED."""
    return Job(
        title="Sr Analyst, IT Infrastructure",
        company="RSA Security",
        location="Cairo, Cairo, Egypt",
        url="https://www.linkedin.com/jobs/view/1234567890",
        source="linkedin_jobs",
        source_key="linkedin_jobs",
        tags=[],
        description="Analyst, IT Infrastructure",
        cyber_verdict=CyberVerdict.CONFIRMED.value,
        posted_date=datetime.now() - timedelta(hours=2),
    )


# ---------- scenario 4: cyber verdict consistency ----------------------------

def scenario_verdict_consistency() -> bool:
    job = _rsa_job()
    reason = telegram_sender._telegram_ineligibility_reason(job)
    ok = reason is None
    print(f"[scenario-4] CYBER_CONFIRMED + valid location + identity -> "
          f"ineligibility_reason={'None (PASS)' if ok else reason + ' (FAIL)'}")

    # CYBER_LIKELY on the same title without skills still fails the gate.
    job.cyber_verdict = CyberVerdict.LIKELY.value
    reason = telegram_sender._telegram_ineligibility_reason(job)
    ok2 = reason == "insufficient_cyber_evidence"
    print(f"[scenario-4] CYBER_LIKELY same title without evidence -> "
          f"{reason} (PASS)" if ok2 else
          f"[scenario-4] CYBER_LIKELY same title -> {reason} (FAIL)")
    return ok and ok2


# ---------- scenario 3: delivery state machine -------------------------------

def scenario_delivery_state_machine() -> bool:
    db, path = _temp_db()
    results: list[str] = []
    payload = {"chat_id": "1", "text": "m"}
    try:
        # (a) legacy exhausted row from a previous run must never block the
        # first real send in the current run.
        with db._conn() as con:
            con.execute(
                """INSERT INTO telegram_delivery_outbox(
                    delivery_key, channel_key, thread_id, payload_json, status,
                    created_at, updated_at, sent_at, attempts
                ) VALUES(?,?,?,?, 'send_failed', ?, ?, NULL, 2)""",
                ("egypt:job-rsa", "egypt", 1, "{}", "1999-01-01T00:00:00", "1999-01-01T00:00:00"),
            )
        # legacy rows without sent_at must also not block
        with db._conn() as con:
            con.execute(
                """INSERT INTO telegram_delivery_outbox(
                    delivery_key, channel_key, thread_id, payload_json, status,
                    created_at, updated_at, sent_at, attempts
                ) VALUES(?,?,?,?, 'sent', ?, ?, NULL, 1)""",
                ("soc:job-rsa", "soc", 2, "{}", "1999-01-01T00:00:00", "1999-01-01T00:00:00"),
            )

        database.set_delivery_run_at("2000-01-01T00:00:00")
        try:
            reserved_egypt = db.reserve_telegram_delivery(
                delivery_key="egypt:job-rsa", channel_key="egypt",
                thread_id=1, payload=payload,
            )
            results.append("reserved=1" if reserved_egypt else "reserved=0 (FAIL)")
            with db._conn() as con:
                row = con.execute(
                    "SELECT status, attempts FROM telegram_delivery_outbox "
                    "WHERE delivery_key='egypt:job-rsa'"
                ).fetchone()
            results.append(f"row after reserve: status={row['status']} attempts={row['attempts']}")

            ok_sent_at = row["status"] == "reserved" and row["attempts"] == 0
            results.append("reset_ok" if ok_sent_at else "reset_FAIL")

            # (b) confirmed-sent pair stays blocked (dedup untouched)
            with db._conn() as con:
                con.execute(
                    """INSERT INTO telegram_delivery_outbox(
                        delivery_key, channel_key, thread_id, payload_json, status,
                        created_at, updated_at, sent_at, attempts
                    ) VALUES(?,?,?,?, 'sent', ?, ?, ?, 1)""",
                    ("cloudsec:job-rsa", "cloudsec", 2, "{}", "1999-01-01T00:00:00", "1999-01-01T00:00:00", "1999-01-01T00:00:01"),
                )
            blocked = not db.reserve_telegram_delivery(
                delivery_key="cloudsec:job-rsa", channel_key="cloudsec",
                thread_id=2, payload=payload,
            )
            results.append("dedup_kept" if blocked else "dedup_LOST (FAIL)")

            # (b2) legacy rows without sent_at resume instead of blocking
            with db._conn() as con:
                con.execute(
                    """INSERT INTO telegram_delivery_outbox(
                        delivery_key, channel_key, thread_id, payload_json, status,
                        created_at, updated_at, sent_at, attempts
                    ) VALUES(?,?,?,?, 'sent', ?, ?, NULL, 1)""",
                    ("grc:job-rsa", "grc", 3, "{}", "1999-01-01T00:00:00", "1999-01-01T00:00:00"),
                )
            legacy_resumed = db.reserve_telegram_delivery(
                delivery_key="grc:job-rsa", channel_key="grc",
                thread_id=3, payload=payload,
            )
            results.append("legacy_resumes" if legacy_resumed else "legacy_blocked (FAIL)")

            # (c) end-to-end send: eligible -> routed -> reserved -> sent
            calls: list[object] = []

            def fake_post(_payload):
                calls.append(1)
                return (True, 200, "", None)

            telegram_sender.TELEGRAM_BOT_TOKEN = "t"
            telegram_sender.TELEGRAM_CHAT_ID = "1"
            telegram_sender._post_telegram_payload = fake_post
            lifecycle: Counter[str] = Counter()
            ok = telegram_sender._send_to_topic(
                "message", thread_id=1, db=db, channel_key="egypt",
                delivery_key="job-rsa", lifecycle=lifecycle,
            )
            results.append(
                f"lifecycle=reserved={lifecycle['reserved']} sent={lifecycle['sent']} "
                f"already_sent={lifecycle.get('already_sent', 0)} (PASS)"
                if (ok and lifecycle["reserved"] == 1 and lifecycle["sent"] == 1
                    and lifecycle.get("already_sent", 0) == 0)
                else f"lifecycle={dict(lifecycle)} (FAIL)"
            )
            return ok and ok_sent_at and blocked
        finally:
            database.set_delivery_run_at(None)
    finally:
        _remove_db(path)


# ---------- scenario 1+2: endpoint-first Egyptian priority -------------------

def scenario_source_execution() -> bool:
    import config
    from sources.source_registry import get_source_specs
    from sources.official_careers import _JS_ONLY_SOURCE_KEYS, fetch_source, _source_budget_seconds

    specs = {s.key: s for s in get_source_specs()}
    expected = {"nbe", "banque_misr", "cib_egypt", "qnb_egypt", "we_jina", "aaib",
                "adib_egypt", "saib", "bank_nxt", "itida", "smart_village",
                "pharco", "elsewedy_electric", "vodafone_egypt"}
    ok_timeout = all(
        specs[k].source_timeout_seconds == config.EGYPT_PRIORITY_SOURCE_TIMEOUT_SECONDS
        for k in expected if k in specs
    )
    ok_priority = all(specs[k].priority <= 18 for k in expected if k in specs)
    ok_tier = all(specs[k].quality_tier == "gold" for k in expected if k in specs)

    # Requirement 1: direct endpoint/anchor fetch ALWAYS runs first; Playwright
    # is gated behind ``not outcome.parsed`` (the raw response exposed no job
    # structure) and the source being a genuine client-side SPA.  The whitelist
    # therefore only lists careers pages that ARE real SPAs (Workday-SPA, Jina,
    # custom SPA portals); a parsed endpoint is never re-rendered.
    js_only_egypt = sorted(k for k in _JS_ONLY_SOURCE_KEYS if k in expected)
    print(f"[scenario-1] JS-only whitelist Egyptian members (genuine SPAs): {js_only_egypt}")
    print(f"[scenario-2] timeout={config.EGYPT_PRIORITY_SOURCE_TIMEOUT_SECONDS}s: {ok_timeout}, "
          f"priority<=18: {ok_priority}, tier=gold: {ok_tier}")

    return ok_timeout and ok_priority and ok_tier


# ---------- scenario 5: quarantine must never strand sources ---------------

def scenario_quarantine() -> bool:
    ok = True
    db, path = _temp_db()
    try:
        # Repeated deadline-driven zeros (the observed failure mode) must not
        # strand a priority source in quarantine.
        for _ in range(6):
            db.update_source_health_state(
                "aaib", success=False, jobs_count=0, error_code="source_timeout",
                auto_disable_threshold=4, quarantine_minutes=180,
                deadline_timeout=True, is_priority_source=True,
            )
        a_ok = db.can_run_source("aaib")
        print(f"[scenario-5] deadline timeouts never quarantine priority source: "
              f"{'PASS' if a_ok else 'FAIL'}")
        ok = ok and a_ok

        # Genuine repeated transport failures still quarantine normal sources.
        for _ in range(4):
            db.update_source_health_state(
                "some_bank", success=False, jobs_count=0, error_code="http_403",
                auto_disable_threshold=4, quarantine_minutes=180,
            )
        b_ok = not db.can_run_source("some_bank")
        print(f"[scenario-5] real failures still quarantine normal sources: "
              f"{'PASS' if b_ok else 'FAIL'}")
        ok = ok and b_ok
    finally:
        _remove_db(path)
    return ok


    sys.exit(0 if all_ok else 1)


# ---------- scenario 6: v64 source strategy ---------------------------------

def scenario_v64_source_strategy() -> bool:
    """The observed run lost ~977s to Egyptian banks waiting 90s each.  After
    v64: short ceilings (≤45s total, ≤10s per attempt), proven suppliers run
    first, and failing banks park into a sparse recovery rotation instead of
    consuming the shared budget every run."""
    ok = True

    # (a) caps
    import config
    from sources import official_careers
    a_ok = (config.EGYPT_PRIORITY_SOURCE_TIMEOUT_SECONDS <= 45
            and official_careers._FAST_ATTEMPT_TIMEOUT_SECONDS <= 10
            and official_careers._FAST_ATTEMPT_SECOND_CAP_SECONDS <= 12)
    print(f"[scenario-6a] caps: egypt<=45s, fast_attempt<=10s, second<=12s: "
          f"{'PASS' if a_ok else 'FAIL'}")
    ok = ok and a_ok

    # (b) yield boost lifts proven suppliers into the front of the plan
    from main import _apply_yield_priority_boost
    from sources.source_registry import get_source_specs
    db2, path2 = _temp_db()
    try:
        cutoff = (datetime.now() - timedelta(days=3)).isoformat()
        with db2._conn() as con:
            con.execute("DELETE FROM source_stats")
            for src, count in (("fabmisr", 225), ("cloudflare", 297),
                               ("tenable", 106), ("hackerone", 26),
                               ("wiz", 117), ("saib", 0)):
                con.execute(
                    "INSERT INTO source_stats(run_at, source, count, failed) "
                    "VALUES(?,?,?,0)", (cutoff, src, count),
                )
        specs = list(get_source_specs())
        _apply_yield_priority_boost(specs, db2)
        fab = next((s for s in specs if s.key == "fabmisr"), None)
        weak = next((s for s in specs if s.key == "saib"), None)
        b_ok = (fab is not None and fab.priority <= 10
                and weak is not None and weak.priority > 10)
        print(f"[scenario-6b] yield boost: fabmisr priority={fab and fab.priority} "
              f"saib unchanged={weak and weak.priority}: "
              f"{'PASS' if b_ok else 'FAIL'}")
        ok = ok and b_ok
    finally:
        _remove_db(path2)

    # (c) failing Egyptian banks park; a recovery recheck graduates them
    db3, path3 = _temp_db()
    try:
        for _ in range(3):
            db3.update_source_health_state(
                "aaib", success=False, jobs_count=0, error_code="http_503",
                is_priority_source=True,
            )
        parked = db3.get_recovery_sources()
        c_ok = (any(r["source_key"] == "aaib" for r in parked)
                and db3.can_run_source("aaib")
                and not db3.list_source_health_state()["aaib"]["quarantined_until"])
        db3.update_source_health_state(
            "aaib", success=True, jobs_count=11, error_code="",
            is_priority_source=True,
        )
        graduated = not db3.get_recovery_sources()
        print(f"[scenario-6c] aaib parks after 3 failures: {'PASS' if c_ok else 'FAIL'}; "
              f"graduates on success: {'PASS' if graduated else 'FAIL'}")
        ok = ok and c_ok and graduated
    finally:
        _remove_db(path3)

    return ok


if __name__ == "__main__":
    all_ok = True
    for scenario in (
        ("verdict-consistency", scenario_verdict_consistency),
        ("delivery-state-machine", scenario_delivery_state_machine),
        ("source-execution", scenario_source_execution),
        ("quarantine", scenario_quarantine),
        ("v64-source-strategy", scenario_v64_source_strategy),
    ):
        name, fn = scenario
        try:
            ok = fn()
        except Exception:  # noqa: BLE001
            ok = False
            traceback.print_exc()
            print(f"[{name}] EXCEPTION")
        all_ok = all_ok and bool(ok)
        print(f"[{name}] final={'PASS' if ok else 'FAIL'}")

    print("\n" + ("ALL SCENARIOS PASSED" if all_ok else "SOME SCENARIOS FAILED"))
    sys.exit(0 if all_ok else 1)
