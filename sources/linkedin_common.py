"""Shared helpers for LinkedIn source fetchers."""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

import config
from sources.http_utils import get_text


FRESH_TPR = f"r{config.MAX_JOB_AGE_DAYS * 86400}"


def budget_left(start: float, budget_seconds: int | None = None) -> bool:
    budget = budget_seconds or config.LINKEDIN_SOURCE_BUDGET_SECONDS
    return time.time() - start <= budget


def linkedin_get_text(url: str, params: dict | None = None,
                      headers: dict | None = None) -> str | None:
    return get_text(url, params=params, headers=headers, timeout=8, max_retries=1)


def force_fresh_tpr(search: dict) -> dict:
    cloned = dict(search)
    cloned["f_TPR"] = FRESH_TPR
    return cloned


def parse_linkedin_posted_date(text: str) -> datetime | None:
    t = (text or "").lower()
    if not t:
        return None
    if any(x in t for x in ["just now", "hour", "hours", "today"]):
        return datetime.now()
    m = re.search(r"(\d+)\s*d", t)
    if m:
        return datetime.now() - timedelta(days=int(m.group(1)))
    m = re.search(r"(\d+)\s*w", t)
    if m:
        return datetime.now() - timedelta(weeks=int(m.group(1)))
    return None

