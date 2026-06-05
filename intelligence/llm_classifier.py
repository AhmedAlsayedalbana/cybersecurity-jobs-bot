"""
intelligence/llm_classifier.py
===============================
Optional LLM-based borderline classification.

• Called only for jobs that pass all keyword gates but lack a strong anchor.
• Results are cached to disk — identical jobs are never re-classified.
• Provider-agnostic: OpenAI or Anthropic, resolved via env vars + config.

Public API:
    classify_borderline_with_llm(job) → bool | None
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import urllib.request
from typing import Any

import config
from intelligence._text import job_description, job_tags, job_title

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _llm_enabled() -> bool:
    if not getattr(config, "LLM_CLASSIFIER_ENABLED", True):
        return False
    provider = getattr(config, "LLM_CLASSIFIER_PROVIDER", "auto")
    if provider in {"openai", "auto"} and os.getenv("OPENAI_API_KEY"):
        return True
    if provider in {"anthropic", "auto"} and os.getenv("ANTHROPIC_API_KEY"):
        return True
    return False


def _cache_path() -> str:
    return getattr(config, "LLM_CLASSIFIER_CACHE_PATH", "llm_classifier_cache.json")


def _cache_key(job: Any) -> str:
    raw = "|".join([job_title(job), job_description(job, limit=160), job_tags(job)])
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:24]


def _load_cache() -> dict[str, bool]:
    try:
        with open(_cache_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(cache: dict[str, bool]) -> None:
    try:
        with open(_cache_path(), "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=True, sort_keys=True)
    except Exception as exc:
        log.debug("Could not save LLM classifier cache: %s", exc)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(job: Any) -> str:
    return (
        "Classify whether this job is primarily a cybersecurity role. "
        "Reject sales, customer success, generic IT support, physical security, "
        "credit/business risk, and generic solutions architect roles unless the role "
        "has clear hands-on cybersecurity, GRC, SOC, pentest, AppSec, cloud security, "
        "network security, or security engineering responsibility. "
        'Return only JSON: {"is_cybersecurity": true|false}.\n\n'
        f"Title: {getattr(job, 'title', '')}\n"
        f"Company: {getattr(job, 'company', '')}\n"
        f"Location: {getattr(job, 'location', '')}\n"
        f"Tags: {job_tags(job)}\n"
        f"Description: {job_description(job, limit=700)}"
    )


# ---------------------------------------------------------------------------
# Provider callers
# ---------------------------------------------------------------------------

def _call_openai(job: Any) -> bool | None:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return None
    model = getattr(config, "LLM_CLASSIFIER_MODEL", "") or "gpt-4o-mini"
    payload = {
        "model": model,
        "input": _build_prompt(job),
        "text": {"format": {"type": "json_object"}},
        "max_output_tokens": 80,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    text = data.get("output_text") or ""
    if not text:
        chunks = []
        for item in data.get("output", []) or []:
            for content in item.get("content", []) or []:
                if content.get("text"):
                    chunks.append(content["text"])
        text = "\n".join(chunks)
    parsed = json.loads(re.sub(r"```json|```", "", text).strip())
    return bool(parsed.get("is_cybersecurity"))


def _call_anthropic(job: Any) -> bool | None:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    model = getattr(config, "LLM_CLASSIFIER_MODEL", "") or "claude-haiku-4-5-20251001"
    payload = {
        "model": model,
        "max_tokens": 80,
        "messages": [{"role": "user", "content": _build_prompt(job)}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    text = "".join(
        item.get("text", "") for item in (data.get("content") or [])
    )
    parsed = json.loads(re.sub(r"```json|```", "", text).strip())
    return bool(parsed.get("is_cybersecurity"))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def classify_borderline_with_llm(job: Any) -> bool | None:
    """Return True/False classification or None if LLM is unavailable/disabled."""
    if not _llm_enabled():
        return None

    cache = _load_cache()
    key = _cache_key(job)
    if key in cache:
        return bool(cache[key])

    provider = getattr(config, "LLM_CLASSIFIER_PROVIDER", "auto")
    callers = []
    if provider in {"openai", "auto"}:
        callers.append(_call_openai)
    if provider in {"anthropic", "auto"}:
        callers.append(_call_anthropic)

    for caller in callers:
        try:
            result = caller(job)
        except Exception as exc:
            log.warning("[LLM Classifier] %s failed: %s", caller.__name__, exc)
            result = None
        if result is not None:
            cache[key] = bool(result)
            _save_cache(cache)
            return bool(result)

    return None
