"""
intelligence/_text.py
=====================
Internal text normalization helpers.  Not part of the public API.
Import only from within the intelligence package.
"""

from __future__ import annotations

import re
from typing import Any


def flatten_tags(tags: Any) -> str:
    if not tags:
        return ""
    if isinstance(tags, list):
        flat: list[str] = []
        for item in tags:
            if isinstance(item, dict):
                flat.append(str(item.get("name", item.get("label", ""))))
            elif isinstance(item, list):
                flat.extend(str(x) for x in item)
            else:
                flat.append(str(item))
        return " ".join(flat)
    return str(tags)


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def job_title(job: Any) -> str:
    return norm(getattr(job, "title", "") or "")


def job_description(job: Any, limit: int = 1200) -> str:
    return norm((getattr(job, "description", "") or "")[:limit])


def job_tags(job: Any) -> str:
    return norm(flatten_tags(getattr(job, "tags", None)))


def job_full_text(job: Any, desc_limit: int = 1200) -> str:
    return norm(" ".join([
        getattr(job, "title", "") or "",
        getattr(job, "company", "") or "",
        getattr(job, "location", "") or "",
        getattr(job, "job_type", "") or "",
        flatten_tags(getattr(job, "tags", None)),
        (getattr(job, "description", "") or "")[:desc_limit],
    ]))


def phrase_match(phrase: str, text: str) -> bool:
    phrase = norm(phrase)
    text = norm(text)
    if not phrase or not text:
        return False
    try:
        escaped = re.escape(phrase).replace(r"\ ", r"[\s\-_/&]+")
        return bool(re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text))
    except re.error:
        return phrase in text


def has_any(patterns: list[str] | set[str] | frozenset[str], text: str) -> bool:
    return any(phrase_match(p, text) for p in patterns)


def count_hits(patterns: list[str] | set[str] | frozenset[str], text: str) -> int:
    return sum(1 for p in patterns if phrase_match(p, text))
