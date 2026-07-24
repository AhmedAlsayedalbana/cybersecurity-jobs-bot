"""
database.py � SQLite backend v41 (Enhanced)

IMPROVEMENTS v41:
   Persistent fuzzy fingerprints in DB (cross-run dedup � not just batch)
   proxy_stats table � track proxy health across runs
   MEMORY_DAYS configurable via env var
   WAL mode for better concurrent write performance
   Graceful schema migration (adds new columns without breaking)
"""

import sqlite3
import logging
import os
import json
from datetime import datetime, timedelta
from contextlib import contextmanager

log = logging.getLogger(__name__)

DB_PATH     = "jobs_bot.db"
MEMORY_DAYS = int(os.environ.get("MEMORY_DAYS", "5"))
DAILY_SEND_HOURS = int(os.environ.get("DAILY_SEND_HOURS", "24"))


class JobsDB:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _conn(self):
        con = sqlite3.connect(self.db_path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")   # better concurrent writes
        con.execute("PRAGMA synchronous=NORMAL")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _init_db(self):
        # Step 1: create tables (executescript uses its own implicit transactions)
        with self._conn() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_key     TEXT    NOT NULL UNIQUE,
                    url_id      TEXT,
                    title       TEXT,
                    company     TEXT,
                    location    TEXT,
                    source      TEXT,
                    source_key  TEXT,
                    content_type TEXT DEFAULT 'job_listing',
                    origin_priority INTEGER DEFAULT 999,
                    seen_at     TEXT    NOT NULL,
                    sent        INTEGER DEFAULT 0,
                    geo_sent_at TEXT,
                    topic_sent_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_key    ON jobs(job_key);
                CREATE INDEX IF NOT EXISTS idx_jobs_url    ON jobs(url_id);
                CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
                CREATE INDEX IF NOT EXISTS idx_jobs_seen   ON jobs(seen_at);

                CREATE TABLE IF NOT EXISTS source_stats (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_at     TEXT NOT NULL,
                    source     TEXT NOT NULL,
                    count      INTEGER,
                    failed     INTEGER DEFAULT 0,
                    elapsed_ms INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_stats_run ON source_stats(run_at);

                CREATE TABLE IF NOT EXISTS source_health_state (
                    source_key TEXT PRIMARY KEY,
                    success_streak INTEGER NOT NULL DEFAULT 0,
                    failure_streak INTEGER NOT NULL DEFAULT 0,
                    total_runs INTEGER NOT NULL DEFAULT 0,
                    total_success INTEGER NOT NULL DEFAULT 0,
                    total_failures INTEGER NOT NULL DEFAULT 0,
                    last_error_code TEXT,
                    last_run_at TEXT,
                    quarantined_until TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_source_health_quarantine
                    ON source_health_state(quarantined_until);

                CREATE TABLE IF NOT EXISTS source_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_at TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    transport TEXT NOT NULL,
                    jobs_count INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    elapsed_ms INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_source_attempts_run
                    ON source_attempts(source_key, run_at);

                CREATE TABLE IF NOT EXISTS proxy_stats (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_at     TEXT NOT NULL,
                    proxy_url  TEXT NOT NULL,
                    score      REAL,
                    banned     INTEGER DEFAULT 0,
                    ban_reason TEXT
                );

                CREATE TABLE IF NOT EXISTS sent_events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_key     TEXT NOT NULL,
                    url_id      TEXT,
                    dedup_key   TEXT,
                    channel_key TEXT NOT NULL,
                    lane        TEXT NOT NULL,
                    sent_at     TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sent_events_time
                    ON sent_events(sent_at);
                CREATE INDEX IF NOT EXISTS idx_sent_events_channel
                    ON sent_events(channel_key, sent_at);
                CREATE INDEX IF NOT EXISTS idx_sent_events_dedup
                    ON sent_events(dedup_key, sent_at);

                CREATE TABLE IF NOT EXISTS telegram_retry_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_key TEXT NOT NULL,
                    thread_id INTEGER,
                    payload_json TEXT NOT NULL,
                    last_error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 6,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    next_retry_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_retry_due
                    ON telegram_retry_queue(status, next_retry_at);

                CREATE TABLE IF NOT EXISTS telegram_delivery_outbox (
                    delivery_key TEXT PRIMARY KEY,
                    channel_key TEXT NOT NULL,
                    thread_id INTEGER,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'reserved',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    next_retry_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_delivery_outbox_due
                    ON telegram_delivery_outbox(status, next_retry_at);

                CREATE TABLE IF NOT EXISTS job_training_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dedup_key TEXT,
                    title TEXT NOT NULL,
                    company TEXT,
                    location TEXT,
                    source TEXT,
                    content_type TEXT,
                    description_short TEXT,
                    accepted INTEGER NOT NULL,
                    reason TEXT,
                    label_source TEXT NOT NULL DEFAULT 'automatic',
                    collected_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_training_collected
                    ON job_training_samples(collected_at);
                CREATE INDEX IF NOT EXISTS idx_training_accepted
                    ON job_training_samples(accepted);
            """)

        # Step 2: schema migrations � separate connection, outside executescript
        con = sqlite3.connect(self.db_path)
        try:
            # add fingerprint column (v41 upgrade)
            try:
                con.execute("ALTER TABLE jobs ADD COLUMN fingerprint TEXT")
                con.commit()
                log.info("[DB] Migrated: added fingerprint column to jobs table.")
            except sqlite3.OperationalError:
                pass  # column already exists

            # add fingerprint index if missing
            try:
                con.execute("CREATE INDEX IF NOT EXISTS idx_jobs_fp ON jobs(fingerprint)")
                con.commit()
            except sqlite3.OperationalError:
                pass

            for col in ("geo_sent_at", "topic_sent_at"):
                try:
                    con.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT")
                    con.commit()
                    log.info(f"[DB] Migrated: added {col} column to jobs table.")
                except sqlite3.OperationalError:
                    pass

            for col, ddl in (
                ("source_key", "TEXT"),
                ("content_type", "TEXT DEFAULT 'job_listing'"),
                ("origin_priority", "INTEGER DEFAULT 999"),
            ):
                try:
                    con.execute(f"ALTER TABLE jobs ADD COLUMN {col} {ddl}")
                    con.commit()
                    log.info(f"[DB] Migrated: added {col} column to jobs table.")
                except sqlite3.OperationalError:
                    pass

            try:
                con.execute("ALTER TABLE job_training_samples ADD COLUMN label_source TEXT NOT NULL DEFAULT 'automatic'")
                con.commit()
            except sqlite3.OperationalError:
                pass

            con.executescript("""
                CREATE TABLE IF NOT EXISTS source_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_at TEXT NOT NULL, source_key TEXT NOT NULL,
                    status TEXT NOT NULL, transport TEXT NOT NULL,
                    jobs_count INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT, elapsed_ms INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_source_attempts_run
                    ON source_attempts(source_key, run_at);
                CREATE TABLE IF NOT EXISTS telegram_delivery_outbox (
                    delivery_key TEXT PRIMARY KEY, channel_key TEXT NOT NULL,
                    thread_id INTEGER, payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'reserved', attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    next_retry_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_delivery_outbox_due
                    ON telegram_delivery_outbox(status, next_retry_at);
            """)
            con.commit()

            for idx, col in (
                ("idx_jobs_geo_sent", "geo_sent_at"),
                ("idx_jobs_topic_sent", "topic_sent_at"),
                ("idx_jobs_source_key", "source_key"),
            ):
                try:
                    con.execute(f"CREATE INDEX IF NOT EXISTS {idx} ON jobs({col})")
                    con.commit()
                except sqlite3.OperationalError:
                    pass

            # Migrate new tables for DBs created before merged6
            new_tables = [
                """CREATE TABLE IF NOT EXISTS source_health_state (
                    source_key TEXT PRIMARY KEY,
                    success_streak INTEGER NOT NULL DEFAULT 0,
                    failure_streak INTEGER NOT NULL DEFAULT 0,
                    total_runs INTEGER NOT NULL DEFAULT 0,
                    total_success INTEGER NOT NULL DEFAULT 0,
                    total_failures INTEGER NOT NULL DEFAULT 0,
                    last_error_code TEXT,
                    last_run_at TEXT,
                    quarantined_until TEXT
                )""",
                """CREATE INDEX IF NOT EXISTS idx_source_health_quarantine
                    ON source_health_state(quarantined_until)""",
                """CREATE TABLE IF NOT EXISTS job_training_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dedup_key TEXT, title TEXT NOT NULL, company TEXT,
                    location TEXT, source TEXT, content_type TEXT,
                    description_short TEXT, accepted INTEGER NOT NULL,
                    reason TEXT, collected_at TEXT NOT NULL
                )""",
                "CREATE INDEX IF NOT EXISTS idx_training_collected ON job_training_samples(collected_at)",
                "CREATE INDEX IF NOT EXISTS idx_training_accepted ON job_training_samples(accepted)",
                """CREATE TABLE IF NOT EXISTS sent_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_key TEXT NOT NULL, url_id TEXT, dedup_key TEXT,
                    channel_key TEXT NOT NULL, lane TEXT NOT NULL, sent_at TEXT NOT NULL
                )""",
                "CREATE INDEX IF NOT EXISTS idx_sent_events_time ON sent_events(sent_at)",
                "CREATE INDEX IF NOT EXISTS idx_sent_events_channel ON sent_events(channel_key, sent_at)",
                "CREATE INDEX IF NOT EXISTS idx_sent_events_dedup ON sent_events(dedup_key, sent_at)",
                """CREATE TABLE IF NOT EXISTS telegram_retry_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_key TEXT NOT NULL, thread_id INTEGER,
                    payload_json TEXT NOT NULL, last_error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 6,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    next_retry_at TEXT NOT NULL
                )""",
                "CREATE INDEX IF NOT EXISTS idx_retry_due ON telegram_retry_queue(status, next_retry_at)",
            ]
            for stmt in new_tables:
                try:
                    con.execute(stmt)
                    con.commit()
                except sqlite3.OperationalError:
                    pass

            # enable WAL mode for better concurrent performance
            con.execute("PRAGMA journal_mode=WAL")
            con.commit()
        finally:
            con.close()

        log.info(f"[DB] Initialized: {self.db_path} (WAL mode, MEMORY_DAYS={MEMORY_DAYS})")

    def is_seen(self, job_key: str, url_id: str = "") -> bool:
        with self._conn() as con:
            row = con.execute(
                "SELECT 1 FROM jobs WHERE job_key=? OR (url_id != '' AND url_id=?) LIMIT 1",
                (job_key, url_id or "")
            ).fetchone()
            return row is not None

    def was_sent_recently(self, job_key: str, url_id: str = "",
                          lane: str = "any", hours: int = None) -> bool:
        """Return True if this job was sent to the requested lane recently."""
        hours = hours or DAILY_SEND_HOURS
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        lane = (lane or "any").lower()

        if lane == "geo":
            sent_clause = "geo_sent_at IS NOT NULL AND geo_sent_at > ?"
            params = (job_key, url_id or "", cutoff)
        elif lane == "topic":
            sent_clause = "topic_sent_at IS NOT NULL AND topic_sent_at > ?"
            params = (job_key, url_id or "", cutoff)
        else:
            sent_clause = """(
                (geo_sent_at IS NOT NULL AND geo_sent_at > ?)
                OR (topic_sent_at IS NOT NULL AND topic_sent_at > ?)
                OR (sent = 1 AND seen_at > ?)
            )"""
            params = (job_key, url_id or "", cutoff, cutoff, cutoff)

        with self._conn() as con:
            row = con.execute(f"""
                SELECT 1 FROM jobs
                WHERE (job_key=? OR (url_id != '' AND url_id=?))
                  AND {sent_clause}
                LIMIT 1
            """, params).fetchone()
            return row is not None

    def was_sent_to_channel_recently(
        self, job_key: str, url_id: str = "", channel_key: str = "",
        dedup_key: str = "", hours: int = None
    ) -> bool:
        """Channel-aware dedup window: prevent resending same job to same channel."""
        if not channel_key:
            return False
        hours = hours or DAILY_SEND_HOURS
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        with self._conn() as con:
            row = con.execute("""
                SELECT 1 FROM sent_events
                WHERE channel_key = ?
                  AND sent_at > ?
                  AND (
                    job_key = ?
                    OR (? != '' AND url_id = ?)
                    OR (? != '' AND dedup_key = ?)
                  )
                LIMIT 1
            """, (
                channel_key, cutoff, job_key,
                url_id or "", url_id or "",
                dedup_key or "", dedup_key or "",
            )).fetchone()
            return row is not None

    def was_sent_globally_recently(
        self,
        job_key: str,
        url_id: str = "",
        dedup_key: str = "",
        hours: int = None,
    ) -> bool:
        """Strict lock: prevent same job from being sent to any channel in the window."""
        hours = hours or DAILY_SEND_HOURS
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        with self._conn() as con:
            row = con.execute("""
                SELECT 1 FROM sent_events
                WHERE sent_at > ?
                  AND (
                    job_key = ?
                    OR (? != '' AND url_id = ?)
                    OR (? != '' AND dedup_key = ?)
                  )
                LIMIT 1
            """, (
                cutoff,
                job_key,
                url_id or "", url_id or "",
                dedup_key or "", dedup_key or "",
            )).fetchone()
            return row is not None

    def get_recent_fingerprints(self, days: int = None) -> list[str]:
        """Return all fingerprints from the last N days for persistent fuzzy dedup."""
        days = days or MEMORY_DAYS
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._conn() as con:
            rows = con.execute(
                "SELECT fingerprint FROM jobs WHERE fingerprint IS NOT NULL AND seen_at > ?",
                (cutoff,)
            ).fetchall()
        return [r["fingerprint"] for r in rows if r["fingerprint"]]

    def get_recent_sent_fingerprints(self, hours: int = None) -> list[str]:
        """Return fingerprints for jobs sent recently, not merely seen."""
        hours = hours or DAILY_SEND_HOURS
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        with self._conn() as con:
            rows = con.execute("""
                SELECT fingerprint FROM jobs
                WHERE fingerprint IS NOT NULL
                  AND (
                    (geo_sent_at IS NOT NULL AND geo_sent_at > ?)
                    OR (topic_sent_at IS NOT NULL AND topic_sent_at > ?)
                    OR (sent = 1 AND seen_at > ?)
                  )
            """, (cutoff, cutoff, cutoff)).fetchall()
        return [r["fingerprint"] for r in rows if r["fingerprint"]]

    def mark_seen(self, job_key: str, url_id: str = "", fingerprint: str = "",
                  title: str = "", company: str = "", location: str = "",
                  source: str = "", sent: bool = False,
                  source_key: str = "", content_type: str = "job_listing",
                  origin_priority: int = 999):
        now = datetime.now().isoformat()
        with self._conn() as con:
            con.execute("""
                INSERT INTO jobs(
                    job_key, url_id, fingerprint, title, company, location,
                    source, source_key, content_type, origin_priority, seen_at, sent
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(job_key) DO UPDATE SET
                    seen_at     = excluded.seen_at,
                    sent        = CASE WHEN jobs.sent = 1 THEN 1 ELSE excluded.sent END,
                    fingerprint = COALESCE(excluded.fingerprint, jobs.fingerprint),
                    title       = COALESCE(excluded.title, jobs.title),
                    company     = COALESCE(excluded.company, jobs.company),
                    location    = COALESCE(excluded.location, jobs.location),
                    source      = COALESCE(excluded.source, jobs.source),
                    source_key  = COALESCE(excluded.source_key, jobs.source_key),
                    content_type = COALESCE(excluded.content_type, jobs.content_type),
                    origin_priority = COALESCE(excluded.origin_priority, jobs.origin_priority)
            """, (
                job_key,
                url_id or "",
                fingerprint or "",
                title,
                company,
                location,
                source,
                source_key or "",
                content_type or "job_listing",
                int(origin_priority or 999),
                now,
                int(sent),
            ))

    def bulk_mark_seen(self, job_keys: list[str]) -> None:
        """Mark legacy JSON seen IDs as migrated, without treating them as sent."""
        if not job_keys:
            return
        now = datetime.now().isoformat()
        with self._conn() as con:
            con.executemany(
                """
                INSERT OR IGNORE INTO jobs(job_key, seen_at, sent)
                VALUES(?, ?, 0)
                """,
                [(str(key), now) for key in job_keys if str(key).strip()],
            )

    def load_seen_ids(self, window_hours: int) -> dict:
        """Load recently sent IDs from SQLite for cross-run dedup."""
        cutoff = (datetime.now() - timedelta(hours=window_hours)).isoformat()
        with self._conn() as con:
            rows = con.execute("""
                SELECT job_key,
                       url_id,
                       COALESCE(topic_sent_at, geo_sent_at, seen_at) AS sent_at
                FROM jobs
                WHERE (geo_sent_at IS NOT NULL AND geo_sent_at > ?)
                   OR (topic_sent_at IS NOT NULL AND topic_sent_at > ?)
                   OR (sent = 1 AND seen_at > ?)
            """, (cutoff, cutoff, cutoff)).fetchall()
        seen: dict[str, str] = {}
        for row in rows:
            if row["job_key"]:
                seen[row["job_key"]] = row["sent_at"]
            if row["url_id"]:
                seen[row["url_id"]] = row["sent_at"]
        return seen

    def mark_sent(self, job_key: str, url_id: str = "", fingerprint: str = "",
                  title: str = "", company: str = "", location: str = "",
                  source: str = "", lane: str = "topic",
                  source_key: str = "", content_type: str = "job_listing",
                  origin_priority: int = 999):
        now = datetime.now().isoformat()
        geo_sent_at = now if lane == "geo" else None
        topic_sent_at = now if lane == "topic" else None

        with self._conn() as con:
            con.execute("""
                INSERT INTO jobs(
                    job_key, url_id, fingerprint, title, company, location,
                    source, source_key, content_type, origin_priority,
                    seen_at, sent, geo_sent_at, topic_sent_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(job_key) DO UPDATE SET
                    seen_at       = excluded.seen_at,
                    sent          = 1,
                    fingerprint   = COALESCE(excluded.fingerprint, jobs.fingerprint),
                    title         = COALESCE(excluded.title, jobs.title),
                    company       = COALESCE(excluded.company, jobs.company),
                    location      = COALESCE(excluded.location, jobs.location),
                    source        = COALESCE(excluded.source, jobs.source),
                    source_key    = COALESCE(excluded.source_key, jobs.source_key),
                    content_type  = COALESCE(excluded.content_type, jobs.content_type),
                    origin_priority = COALESCE(excluded.origin_priority, jobs.origin_priority),
                    geo_sent_at   = COALESCE(excluded.geo_sent_at, jobs.geo_sent_at),
                    topic_sent_at = COALESCE(excluded.topic_sent_at, jobs.topic_sent_at)
            """, (
                job_key, url_id or "", fingerprint or "", title, company, location,
                source, source_key or "", content_type or "job_listing", int(origin_priority or 999),
                now, 1, geo_sent_at, topic_sent_at
            ))

    def record_sent_event(self, job_key: str, url_id: str = "", channel_key: str = "",
                          lane: str = "topic", dedup_key: str = ""):
        """Persist channel-level send events used for strict 24h per-channel dedup."""
        if not channel_key:
            return
        now = datetime.now().isoformat()
        with self._conn() as con:
            con.execute("""
                INSERT INTO sent_events(job_key, url_id, dedup_key, channel_key, lane, sent_at)
                VALUES(?,?,?,?,?,?)
            """, (job_key, url_id or "", dedup_key or "", channel_key, lane, now))

    def cleanup_old(self, days: int = None):
        days = days or MEMORY_DAYS
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._conn() as con:
            result = con.execute("DELETE FROM jobs WHERE seen_at < ? AND sent = 0", (cutoff,))
            deleted_unsent = result.rowcount
            # Keep sent jobs longer (30 days) for analytics
            result2 = con.execute(
                "DELETE FROM jobs WHERE seen_at < ? AND sent = 1",
                ((datetime.now() - timedelta(days=30)).isoformat(),)
            )
            con.execute(
                "DELETE FROM sent_events WHERE sent_at < ?",
                ((datetime.now() - timedelta(days=30)).isoformat(),)
            )
            con.execute(
                "DELETE FROM telegram_retry_queue WHERE updated_at < ? AND status IN ('sent', 'failed')",
                ((datetime.now() - timedelta(days=14)).isoformat(),)
            )
            # v54: job_training_samples was the real source of the near-100MB
            # database, not source_stats/proxy_stats. main.py logs a row here
            # for essentially every fetched job every run (~5,800 rows/run in
            # the July 19 20:16 run), so even a modest run cadence adds up
            # fast. Cut retention 120 → 30 days, and add a hard row-count cap
            # (most-recent 50,000) as a ceiling regardless of date, so a
            # sudden spike in run frequency or fetch volume can't blow the
            # budget back out. 50,000 rows comfortably covers the 12,000
            # samples the local ML retrain actually uses.
            result_train = con.execute(
                "DELETE FROM job_training_samples WHERE collected_at < ?",
                ((datetime.now() - timedelta(days=30)).isoformat(),)
            )
            con.execute(
                """
                DELETE FROM job_training_samples WHERE id NOT IN (
                    SELECT id FROM job_training_samples
                    ORDER BY collected_at DESC LIMIT 50000
                )
                """
            )
            # v54: source_stats/proxy_stats were NEVER pruned before — every run
            # (every 4h) inserted ~24 + N rows forever. Over months this was the
            # main driver behind jobs_bot.db crossing GitHub's 100MB push limit
            # and failing the "Save jobs database to data branch" CI step.
            stats_cutoff = (datetime.now() - timedelta(days=14)).isoformat()
            result_src = con.execute(
                "DELETE FROM source_stats WHERE run_at < ?", (stats_cutoff,)
            )
            result_proxy = con.execute(
                "DELETE FROM proxy_stats WHERE run_at < ?", (stats_cutoff,)
            )
            log.info(
                f"[DB] Cleanup: removed {deleted_unsent} unseen + {result2.rowcount} old sent jobs "
                f"+ {result_train.rowcount} training samples "
                f"+ {result_src.rowcount} source_stats + {result_proxy.rowcount} proxy_stats rows."
            )
        # VACUUM must run outside a transaction — reclaims disk space freed by
        # the DELETEs above (SQLite does NOT shrink the file automatically).
        try:
            with self._conn() as con:
                con.execute("VACUUM")
            log.info("[DB] VACUUM complete — file size reclaimed.")
        except Exception as exc:
            log.warning(f"[DB] VACUUM failed (non-fatal): {exc}")

    def enqueue_telegram_retry(
        self,
        *,
        channel_key: str,
        thread_id: int | None,
        payload: dict,
        error: str,
        max_attempts: int = 6,
        delay_seconds: int = 45,
    ):
        now = datetime.now()
        next_retry = now + timedelta(seconds=max(0, delay_seconds))
        payload_text = json.dumps(payload, ensure_ascii=False)
        with self._conn() as con:
            con.execute("""
                INSERT INTO telegram_retry_queue(
                    channel_key, thread_id, payload_json, last_error,
                    attempts, max_attempts, status, created_at, updated_at, next_retry_at
                ) VALUES(?,?,?,?,0,?,'pending',?,?,?)
            """, (
                channel_key,
                thread_id,
                payload_text,
                (error or "")[:500],
                int(max_attempts),
                now.isoformat(),
                now.isoformat(),
                next_retry.isoformat(),
            ))

    def get_due_telegram_retries(self, limit: int = 25) -> list[dict]:
        now = datetime.now().isoformat()
        with self._conn() as con:
            rows = con.execute("""
                SELECT id, channel_key, thread_id, payload_json, attempts, max_attempts
                FROM telegram_retry_queue
                WHERE status = 'pending'
                  AND next_retry_at <= ?
                  AND attempts < max_attempts
                ORDER BY next_retry_at ASC, id ASC
                LIMIT ?
            """, (now, int(limit))).fetchall()
        out: list[dict] = []
        for r in rows:
            try:
                payload = json.loads(r["payload_json"])
            except Exception:
                payload = {}
            out.append({
                "id": r["id"],
                "channel_key": r["channel_key"],
                "thread_id": r["thread_id"],
                "payload": payload,
                "attempts": r["attempts"],
                "max_attempts": r["max_attempts"],
            })
        return out

    def mark_telegram_retry_sent(self, retry_id: int):
        now = datetime.now().isoformat()
        with self._conn() as con:
            con.execute("""
                UPDATE telegram_retry_queue
                SET status='sent', updated_at=?
                WHERE id=?
            """, (now, int(retry_id)))

    def mark_telegram_retry_attempt(
        self,
        retry_id: int,
        *,
        error: str,
        delay_seconds: int = 60,
        force_fail: bool = False,
    ):
        now = datetime.now()
        with self._conn() as con:
            row = con.execute(
                "SELECT attempts, max_attempts FROM telegram_retry_queue WHERE id=?",
                (int(retry_id),),
            ).fetchone()
            if not row:
                return
            attempts = int(row["attempts"]) + 1
            max_attempts = int(row["max_attempts"])
            status = "failed" if force_fail or attempts >= max_attempts else "pending"
            next_retry = now + timedelta(seconds=max(10, int(delay_seconds)))
            con.execute("""
                UPDATE telegram_retry_queue
                SET attempts=?, last_error=?, status=?, updated_at=?, next_retry_at=?
                WHERE id=?
            """, (
                attempts,
                (error or "")[:500],
                status,
                now.isoformat(),
                next_retry.isoformat(),
                int(retry_id),
            ))

    def import_seen_dict(self, data: dict):
        now = datetime.now().isoformat()
        with self._conn() as con:
            for key, ts in data.items():
                seen_at = ts if isinstance(ts, str) else now
                con.execute("""
                    INSERT OR IGNORE INTO jobs(job_key, seen_at)
                    VALUES(?, ?)
                """, (key, seen_at))

    def to_seen_dict(self) -> dict:
        cutoff = (datetime.now() - timedelta(days=MEMORY_DAYS)).isoformat()
        with self._conn() as con:
            rows = con.execute(
                "SELECT job_key, seen_at FROM jobs WHERE seen_at > ?", (cutoff,)
            ).fetchall()
        return {r["job_key"]: r["seen_at"] for r in rows}

    def to_recent_sent_dict(self, hours: int = None) -> dict:
        hours = hours or DAILY_SEND_HOURS
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        with self._conn() as con:
            rows = con.execute("""
                SELECT job_key,
                       COALESCE(topic_sent_at, geo_sent_at, seen_at) AS sent_at
                FROM jobs
                WHERE (geo_sent_at IS NOT NULL AND geo_sent_at > ?)
                   OR (topic_sent_at IS NOT NULL AND topic_sent_at > ?)
                   OR (sent = 1 AND seen_at > ?)
            """, (cutoff, cutoff, cutoff)).fetchall()
        return {r["job_key"]: r["sent_at"] for r in rows}

    def save_source_stats(self, stats: dict):
        now = datetime.now().isoformat()
        with self._conn() as con:
            for source, value in stats.items():
                if value == "FAILED":
                    con.execute(
                        "INSERT INTO source_stats(run_at, source, count, failed) VALUES(?,?,NULL,1)",
                        (now, source)
                    )
                else:
                    con.execute(
                        "INSERT INTO source_stats(run_at, source, count, failed) VALUES(?,?,?,0)",
                        (now, source, int(value))
                    )

    def record_source_attempt(self, *, source_key: str, status: str, transport: str,
                              jobs_count: int, error_code: str = "", elapsed_ms: int = 0) -> None:
        with self._conn() as con:
            con.execute(
                """INSERT INTO source_attempts(
                    run_at, source_key, status, transport, jobs_count, error_code, elapsed_ms
                ) VALUES(?,?,?,?,?,?,?)""",
                (
                    datetime.now().isoformat(), source_key, status, transport,
                    int(jobs_count), (error_code or "")[:120], int(elapsed_ms),
                ),
            )

    def reserve_telegram_delivery(self, *, delivery_key: str, channel_key: str,
                                  thread_id: int | None, payload: dict) -> bool:
        """Atomically reserve a channel/job delivery before a network call."""
        now = datetime.now().isoformat()
        with self._conn() as con:
            result = con.execute(
                """INSERT INTO telegram_delivery_outbox(
                    delivery_key, channel_key, thread_id, payload_json, status,
                    created_at, updated_at
                ) VALUES(?,?,?,?, 'reserved', ?, ?)
                ON CONFLICT(delivery_key) DO NOTHING""",
                (delivery_key, channel_key, thread_id, json.dumps(payload, ensure_ascii=False), now, now),
            )
            return bool(result.rowcount)

    def mark_telegram_delivery(self, delivery_key: str, *, status: str,
                               error: str = "", delay_seconds: int | None = None) -> None:
        now = datetime.now()
        next_retry = None if delay_seconds is None else (now + timedelta(seconds=max(1, int(delay_seconds)))).isoformat()
        with self._conn() as con:
            con.execute(
                """UPDATE telegram_delivery_outbox
                SET status=?, attempts=attempts + 1, last_error=?, updated_at=?, next_retry_at=?
                WHERE delivery_key=?""",
                (status, (error or "")[:500], now.isoformat(), next_retry, delivery_key),
            )

    def get_due_safe_delivery_retries(self, limit: int = 25) -> list[dict]:
        now = datetime.now().isoformat()
        with self._conn() as con:
            rows = con.execute(
                """SELECT delivery_key, channel_key, thread_id, payload_json, attempts
                FROM telegram_delivery_outbox
                WHERE status='retry_429' AND next_retry_at <= ?
                ORDER BY next_retry_at ASC LIMIT ?""",
                (now, int(limit)),
            ).fetchall()
        result: list[dict] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, ValueError):
                payload = {}
            result.append({**dict(row), "payload": payload})
        return result

    def save_proxy_stats(self, proxy_status: dict):
        """Save proxy pool health snapshot."""
        if not proxy_status:
            return
        now = datetime.now().isoformat()
        with self._conn() as con:
            con.execute(
                "INSERT INTO proxy_stats(run_at, proxy_url, score, banned) VALUES(?,?,?,?)",
                (now, "pool_summary",
                 proxy_status.get("avg_score", 0),
                 proxy_status.get("banned", 0))
            )

    def get_source_health(self, days: int = 7) -> list[dict]:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._conn() as con:
            rows = con.execute("""
                SELECT source,
                       COUNT(*) as runs,
                       SUM(failed) as failures,
                       AVG(CASE WHEN failed=0 THEN count ELSE NULL END) as avg_jobs
                FROM source_stats
                WHERE run_at > ?
                GROUP BY source
                ORDER BY avg_jobs DESC NULLS LAST
            """, (cutoff,)).fetchall()
        return [dict(r) for r in rows]

    def update_source_health_state(
        self,
        source_key: str,
        *,
        success: bool,
        jobs_count: int = 0,
        error_code: str = "",
        auto_disable_threshold: int = 4,
        quarantine_minutes: int = 180,
    ) -> None:
        now = datetime.now()
        now_iso = now.isoformat()
        with self._conn() as con:
            row = con.execute(
                "SELECT * FROM source_health_state WHERE source_key=?",
                (source_key,),
            ).fetchone()
            if row is None:
                con.execute(
                    """
                    INSERT INTO source_health_state(
                        source_key, success_streak, failure_streak,
                        total_runs, total_success, total_failures,
                        last_error_code, last_run_at, quarantined_until
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        source_key,
                        1 if success else 0,
                        0 if success else 1,
                        1,
                        1 if success else 0,
                        0 if success else 1,
                        "" if success else (error_code or "failed"),
                        now_iso,
                        None,
                    ),
                )
                return

            success_streak = int(row["success_streak"] or 0)
            failure_streak = int(row["failure_streak"] or 0)
            total_runs = int(row["total_runs"] or 0) + 1
            total_success = int(row["total_success"] or 0)
            total_failures = int(row["total_failures"] or 0)
            quarantined_until = row["quarantined_until"]

            if success:
                success_streak += 1
                failure_streak = 0
                total_success += 1
                if jobs_count > 0:
                    quarantined_until = None
            else:
                success_streak = 0
                failure_streak += 1
                total_failures += 1
                if failure_streak >= max(1, auto_disable_threshold):
                    quarantined_until = (
                        now + timedelta(minutes=max(1, quarantine_minutes))
                    ).isoformat()

            con.execute(
                """
                UPDATE source_health_state
                SET success_streak=?, failure_streak=?, total_runs=?, total_success=?,
                    total_failures=?, last_error_code=?, last_run_at=?, quarantined_until=?
                WHERE source_key=?
                """,
                (
                    success_streak,
                    failure_streak,
                    total_runs,
                    total_success,
                    total_failures,
                    "" if success else (error_code or "failed"),
                    now_iso,
                    quarantined_until,
                    source_key,
                ),
            )

    def can_run_source(self, source_key: str, *, min_success: int = 1) -> bool:
        with self._conn() as con:
            row = con.execute(
                "SELECT success_streak, quarantined_until FROM source_health_state WHERE source_key=?",
                (source_key,),
            ).fetchone()
        if row is None:
            return True
        quarantined_until = row["quarantined_until"]
        if quarantined_until:
            try:
                if datetime.fromisoformat(quarantined_until) > datetime.now():
                    return False
            except ValueError:
                pass
        success_streak = int(row["success_streak"] or 0)
        return success_streak >= max(0, min_success) or success_streak == 0

    def list_source_health_state(self) -> dict[str, dict]:
        with self._conn() as con:
            rows = con.execute("SELECT * FROM source_health_state").fetchall()
        out: dict[str, dict] = {}
        for row in rows:
            out[row["source_key"]] = dict(row)
        return out

    def record_training_sample(
        self,
        *,
        dedup_key: str,
        title: str,
        company: str,
        location: str,
        source: str,
        content_type: str,
        description_short: str,
        accepted: bool,
        reason: str = "",
        label_source: str = "automatic",
    ) -> None:
        with self._conn() as con:
            con.execute(
                """
                INSERT INTO job_training_samples(
                    dedup_key, title, company, location, source, content_type,
                    description_short, accepted, reason, label_source, collected_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    dedup_key or "",
                    title or "",
                    company or "",
                    location or "",
                    source or "",
                    content_type or "job_listing",
                    (description_short or "")[:800],
                    1 if accepted else 0,
                    (reason or "")[:200],
                    (label_source or "automatic")[:40],
                    datetime.now().isoformat(),
                ),
            )

    def get_training_samples(self, *, days: int = 60, limit: int = 5000,
                             label_source: str | None = None) -> list[dict]:
        cutoff = (datetime.now() - timedelta(days=max(1, days))).isoformat()
        with self._conn() as con:
            rows = con.execute(
                """
                SELECT dedup_key, title, company, location, source, content_type,
                       description_short, accepted, reason, label_source, collected_at
                FROM job_training_samples
                WHERE collected_at > ?
                  AND (? IS NULL OR label_source = ?)
                ORDER BY id DESC
                LIMIT ?
                """,
                (cutoff, label_source, label_source, int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    def cleanup_training_samples(self, *, days: int = 120) -> int:
        cutoff = (datetime.now() - timedelta(days=max(1, days))).isoformat()
        with self._conn() as con:
            result = con.execute(
                "DELETE FROM job_training_samples WHERE collected_at < ?",
                (cutoff,),
            )
        return int(result.rowcount or 0)

    def get_stats_summary(self) -> dict:
        with self._conn() as con:
            total_seen = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            total_sent = con.execute("SELECT COUNT(*) FROM jobs WHERE sent=1").fetchone()[0]
        return {"total_seen": total_seen, "total_sent": total_sent}


# ── Singleton accessor ────────────────────────────────────────────────────────
# Use get_db() everywhere instead of JobsDB() to avoid x40+ _init_db() calls.
_singleton: "JobsDB | None" = None


def get_db(db_path: str = DB_PATH) -> "JobsDB":
    """Return the process-wide JobsDB singleton (creates it on first call)."""
    global _singleton
    if _singleton is None or _singleton.db_path != db_path:
        _singleton = JobsDB(db_path)
    return _singleton
