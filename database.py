"""
database.py — SQLite backend for the cybersecurity jobs bot.

Replaces seen_jobs.json with a proper SQLite database.

Tables:
  jobs        — all jobs ever seen (dedup + history)
  source_stats — per-run stats for health monitoring

Usage:
  from database import JobsDB
  db = JobsDB()
  db.is_seen("title|company")
  db.mark_seen(job)
  db.save_source_stats({"LinkedIn": 25, "Wuzzuf": "FAILED"})
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)

DB_PATH = "jobs_bot.db"
MEMORY_DAYS = 7


class JobsDB:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _conn(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _init_db(self):
        with self._conn() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_key     TEXT    NOT NULL UNIQUE,   -- unique_id (title|company)
                    url_id      TEXT,                      -- clean url
                    title       TEXT,
                    company     TEXT,
                    location    TEXT,
                    source      TEXT,
                    seen_at     TEXT    NOT NULL,          -- ISO timestamp
                    sent        INTEGER DEFAULT 0          -- 1 if actually sent
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_key    ON jobs(job_key);
                CREATE INDEX IF NOT EXISTS idx_jobs_url    ON jobs(url_id);
                CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
                CREATE INDEX IF NOT EXISTS idx_jobs_seen   ON jobs(seen_at);

                CREATE TABLE IF NOT EXISTS source_stats (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_at     TEXT NOT NULL,
                    source     TEXT NOT NULL,
                    count      INTEGER,      -- NULL if failed
                    failed     INTEGER DEFAULT 0,
                    elapsed_ms INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_stats_run ON source_stats(run_at);
            """)
        log.info(f"[DB] Initialized: {self.db_path}")

    # ── Dedup interface (drop-in for dedup.py dict) ───────────

    def is_seen(self, job_key: str, url_id: str = "") -> bool:
        with self._conn() as con:
            row = con.execute(
                "SELECT 1 FROM jobs WHERE job_key=? OR (url_id != '' AND url_id=?) LIMIT 1",
                (job_key, url_id or "")
            ).fetchone()
            return row is not None

    def mark_seen(self, job_key: str, url_id: str = "", title: str = "",
                  company: str = "", location: str = "", source: str = "",
                  sent: bool = False):
        now = datetime.now().isoformat()
        with self._conn() as con:
            con.execute("""
                INSERT INTO jobs(job_key, url_id, title, company, location, source, seen_at, sent)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(job_key) DO UPDATE SET
                    seen_at = excluded.seen_at,
                    sent    = excluded.sent
            """, (job_key, url_id or "", title, company, location, source, now, int(sent)))

    def mark_sent(self, job_key: str):
        with self._conn() as con:
            con.execute("UPDATE jobs SET sent=1 WHERE job_key=?", (job_key,))

    def cleanup_old(self, days: int = MEMORY_DAYS):
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._conn() as con:
            deleted = con.execute(
                "DELETE FROM jobs WHERE seen_at < ?", (cutoff,)
            ).rowcount
        if deleted:
            log.info(f"[DB] Cleaned {deleted} old job records (>{days}d).")

    # ── Load/export dict (backward compat with dedup.py) ──────

    def to_seen_dict(self) -> dict:
        """Export as {job_key: iso_timestamp} for dedup.py compatibility."""
        with self._conn() as con:
            rows = con.execute("SELECT job_key, seen_at FROM jobs").fetchall()
        return {r["job_key"]: r["seen_at"] for r in rows}

    def import_seen_dict(self, seen: dict):
        """Bulk-import from old seen_jobs.json format."""
        now = datetime.now().isoformat()
        with self._conn() as con:
            for job_key, ts in seen.items():
                con.execute("""
                    INSERT OR IGNORE INTO jobs(job_key, seen_at)
                    VALUES(?,?)
                """, (job_key, ts or now))
        log.info(f"[DB] Imported {len(seen)} records from JSON.")

    # ── Source health stats ────────────────────────────────────

    def save_source_stats(self, stats: dict, run_at: str = None):
        """
        stats = {"LinkedIn": 25, "Wuzzuf": "FAILED", ...}
        """
        run_at = run_at or datetime.now().isoformat()
        with self._conn() as con:
            for source, result in stats.items():
                if result == "FAILED":
                    con.execute("""
                        INSERT INTO source_stats(run_at, source, failed)
                        VALUES(?,?,1)
                    """, (run_at, source))
                else:
                    con.execute("""
                        INSERT INTO source_stats(run_at, source, count, failed)
                        VALUES(?,?,?,0)
                    """, (run_at, source, int(result)))

    def get_source_health(self, days: int = 7) -> list[dict]:
        """Return per-source success rate over last N days."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._conn() as con:
            rows = con.execute("""
                SELECT
                    source,
                    COUNT(*) as runs,
                    SUM(CASE WHEN failed=0 THEN 1 ELSE 0 END) as successes,
                    SUM(CASE WHEN failed=1 THEN 1 ELSE 0 END) as failures,
                    AVG(CASE WHEN failed=0 THEN count ELSE NULL END) as avg_jobs
                FROM source_stats
                WHERE run_at > ?
                GROUP BY source
                ORDER BY failures DESC, avg_jobs ASC
            """, (cutoff,)).fetchall()
        return [dict(r) for r in rows]

    def get_stats_summary(self) -> dict:
        """Quick DB summary for logging."""
        with self._conn() as con:
            total  = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            sent   = con.execute("SELECT COUNT(*) FROM jobs WHERE sent=1").fetchone()[0]
            by_src = con.execute("""
                SELECT source, COUNT(*) as n FROM jobs
                WHERE source != ''
                GROUP BY source ORDER BY n DESC LIMIT 10
            """).fetchall()
        return {
            "total_seen": total,
            "total_sent": sent,
            "top_sources": {r["source"]: r["n"] for r in by_src},
        }
