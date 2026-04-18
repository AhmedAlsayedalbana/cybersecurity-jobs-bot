"""
Himalayas — DISABLED: HTTP 403 on all endpoints, 0 jobs every run.
Kept as stub to avoid import errors.
"""
import logging
log = logging.getLogger(__name__)

def fetch_himalayas() -> list:
    log.info("Himalayas: skipped (403 confirmed dead)")
    return []
