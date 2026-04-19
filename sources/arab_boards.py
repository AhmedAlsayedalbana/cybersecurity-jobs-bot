"""
Arab Job Boards — DISABLED v28

All sources confirmed dead from logs:
  ❌ Bayt RSS       — HTTP 403 always
  ❌ Akhtaboot      — 0 jobs (returns no JSON-LD, HTML changes)
  ❌ Tanqeeb        — HTTP 403 always
  ❌ DrJobPro       — HTTP 404 always

Kept as stub to preserve import compatibility.
"""
import logging
log = logging.getLogger(__name__)

def fetch_arab_boards() -> list:
    log.debug("Arab Boards: all sources dead — skipped")
    return []
