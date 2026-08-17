"""Blind Telegram review sampling and human-labelled filter metrics."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from html import escape
import hashlib
import json
import logging
import random
import time
from typing import Iterable

import requests

import config
from database import JobsDB
from models import CyberVerdict, Job

log = logging.getLogger(__name__)


def _country(job: Job) -> str:
    text = (job.location or "").lower()
    if any(item in text for item in ("egypt", "cairo", "giza", "alexandria", "مصر", "القاهرة")):
        return "egypt"
    if any(item in text for item in config.ARAB_PATTERNS):
        return "arab"
    return "remote_or_other"


def _score_band(job: Job) -> str:
    value = float(getattr(job, "cyber_probability", 0.0) or 0.0)
    if value >= 0.82:
        return "0.82-1.00"
    if value >= 0.70:
        return "0.70-0.81"
    if value >= 0.60:
        return "0.60-0.69"
    if value >= 0.45:
        return "0.45-0.59"
    return "0.00-0.44"


def _stratum(job: Job) -> tuple[str, str, str, str, str, str]:
    return (
        (getattr(job, "source_key", "") or job.source or "unknown").lower(),
        _country(job),
        (job.company or "unknown").lower(),
        getattr(job, "cyber_verdict", CyberVerdict.NON_CYBER.value),
        _score_band(job),
        (getattr(job, "filter_reason", "") or "unknown").lower(),
    )


def _sample_stratified(rows: list[Job], quota: int, seed: str) -> list[tuple[Job, int]]:
    """Diverse first, proportional afterwards; no source/company monoculture."""
    if quota <= 0 or not rows:
        return []
    groups: dict[tuple[str, ...], list[Job]] = defaultdict(list)
    for row in rows:
        groups[_stratum(row)].append(row)

    rng = random.Random(seed)
    selected: list[Job] = []
    source_count: dict[str, int] = defaultdict(int)
    company_count: dict[str, int] = defaultdict(int)
    per_group_cap = max(1, quota // 4)
    # Cover available strata once before filling proportional remainder.
    ordered_groups = list(groups.items())
    rng.shuffle(ordered_groups)
    for key, candidates in ordered_groups:
        if len(selected) >= quota:
            break
        if source_count[key[0]] >= per_group_cap or company_count[key[2]] >= per_group_cap:
            continue
        picked = candidates[rng.randrange(len(candidates))]
        selected.append(picked)
        source_count[key[0]] += 1
        company_count[key[2]] += 1

    pool = [row for rows_for_key in groups.values() for row in rows_for_key]
    rng.shuffle(pool)
    for row in pool:
        if len(selected) >= quota:
            break
        key = _stratum(row)
        if source_count[key[0]] >= per_group_cap or company_count[key[2]] >= per_group_cap:
            continue
        if any(existing.dedup_key == row.dedup_key for existing in selected):
            continue
        selected.append(row)
        source_count[key[0]] += 1
        company_count[key[2]] += 1

    # If the available population cannot satisfy the diversity caps (for
    # example a small run with one valid Egyptian source), still use the rest
    # of the quota rather than silently shrinking the evaluation sample.
    # Diversity was already guaranteed first; this is only a capacity fallback.
    if len(selected) < quota:
        for row in pool:
            if len(selected) >= quota:
                break
            if any(existing.dedup_key == row.dedup_key for existing in selected):
                continue
            selected.append(row)

    # ``population_size`` is the inverse-probability weight for the stratum,
    # not merely its raw size.  This lets the human-label metrics estimate the
    # full filtered population even though the reviewer sees a diverse sample.
    selected_per_stratum: dict[tuple[str, ...], int] = defaultdict(int)
    for row in selected:
        selected_per_stratum[_stratum(row)] += 1
    return [
        (row, max(1.0, len(groups[_stratum(row)]) / selected_per_stratum[_stratum(row)]))
        for row in selected
    ]


def build_review_sample(confirmed: Iterable[Job], likely: Iterable[Job], rejected: Iterable[Job], run_id: str) -> list[tuple[Job, int]]:
    rejected_rows = list(rejected)
    borderline = [row for row in rejected_rows if 0.45 <= float(getattr(row, "cyber_probability", 0.0) or 0.0) < config.CYBER_LIKELY_MIN_PROB]
    random_rejects = [row for row in rejected_rows if row not in borderline]
    quotas = (20, 20, 30, 10)
    samples: list[tuple[Job, int]] = []
    for label, rows, quota in (
        ("confirmed", list(confirmed), quotas[0]),
        ("likely", list(likely), quotas[1]),
        ("borderline", borderline, quotas[2]),
        ("random", random_rejects, quotas[3]),
    ):
        samples.extend(_sample_stratified(rows, quota, f"{run_id}:{label}"))
    return samples[:config.REVIEW_SAMPLE_SIZE]


def _review_message(job: Job) -> str:
    # Deliberately omit prediction, probability, and filter reason.
    description = escape(job.description or "")[:500]
    url = escape(job.canonical_url or job.url or "", quote=True)
    return "\n".join([
        "<b>Blind cyber-role review</b>",
        f"<b>Title:</b> {escape(job.title or 'Unknown')}",
        f"<b>Company:</b> {escape(job.company or 'Unknown')}",
        f"<b>Location:</b> {escape(job.location or 'Unknown')}",
        f"<b>Source:</b> {escape(getattr(job, 'source_key', '') or job.source or 'Unknown')}",
        f"<b>Details:</b> {description or 'No description extracted'}",
        f'<a href="{url}">Open source</a>' if url else "",
    ])


def queue_review_samples(
    db: JobsDB, confirmed: list[Job], likely: list[Job], rejected: list[Job], run_id: str,
    budget_seconds: float = 12.0,
) -> int:
    if not config.TOPIC_REVIEW or not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return 0
    queued = 0
    deadline = time.monotonic() + max(0.0, budget_seconds)
    for job, population_size in build_review_sample(confirmed, likely, rejected, run_id):
        timeout = min(4.0, deadline - time.monotonic())
        if timeout <= 0:
            log.info("Review sample queue stopped at its %ss budget.", budget_seconds)
            break
        token = hashlib.sha256(f"{run_id}|{job.dedup_key}|{job.cyber_verdict}".encode()).hexdigest()[:18]
        stratum = _stratum(job)
        db.create_review_sample(
            token=token, run_id=run_id, dedup_key=job.dedup_key,
            predicted_verdict=job.cyber_verdict or CyberVerdict.NON_CYBER.value,
            score_band=_score_band(job), stratum_json=json.dumps(stratum),
            title=job.title, company=job.company, location=job.location,
            source=getattr(job, "source_key", "") or job.source,
            reason=getattr(job, "filter_reason", ""), description_short=job.description or "",
            population_size=population_size,
        )
        reply_markup = {
            "inline_keyboard": [[
                {"text": "✅ Cyber", "callback_data": f"rv:{token}:y"},
                {"text": "❌ Not cyber", "callback_data": f"rv:{token}:n"},
                {"text": "⏭ Skip", "callback_data": f"rv:{token}:s"},
            ]]
        }
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": config.TELEGRAM_CHAT_ID, "message_thread_id": config.TOPIC_REVIEW,
                      "text": _review_message(job), "parse_mode": "HTML", "reply_markup": reply_markup},
                timeout=max(0.2, timeout),
            )
            if response.ok:
                queued += 1
        except requests.RequestException:
            break
    return queued


def poll_review_updates(db: JobsDB) -> int:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_REVIEWER_IDS:
        return 0
    offset = db.get_telegram_update_offset()
    try:
        response = requests.get(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates",
            params={"offset": offset, "timeout": 0, "allowed_updates": json.dumps(["callback_query"])},
            timeout=8,
        )
        payload = response.json() if response.ok else {}
    except (requests.RequestException, ValueError):
        return 0
    accepted = 0
    for update in payload.get("result", []):
        update_id = int(update.get("update_id", 0))
        db.set_telegram_update_offset(update_id + 1)
        callback = update.get("callback_query") or {}
        data = str(callback.get("data", ""))
        actor = int((callback.get("from") or {}).get("id", 0) or 0)
        if actor not in config.TELEGRAM_REVIEWER_IDS or not data.startswith("rv:"):
            continue
        parts = data.split(":")
        if len(parts) != 3 or parts[2] not in {"y", "n", "s"}:
            continue
        token, choice = parts[1], parts[2]
        if choice != "s" and db.record_review_label(token, choice == "y", actor):
            sample = db.get_review_sample(token)
            if sample:
                db.record_training_sample(
                    dedup_key=sample["dedup_key"], title=sample["title"], company=sample["company"],
                    location=sample["location"], source=sample["source"], content_type="job_listing",
                    description_short=sample["description_short"], accepted=choice == "y",
                    reason="telegram_human_review", label_source="human_verified",
                )
            accepted += 1
        try:
            requests.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
                json={"callback_query_id": callback.get("id", ""), "text": "Saved" if choice != "s" else "Skipped"},
                timeout=4,
            )
        except requests.RequestException:
            pass
    return accepted


def record_metrics(db: JobsDB, run_id: str) -> dict:
    current_run = db.get_review_metrics(run_id)
    metrics = db.get_review_metrics()
    metrics["current_run"] = current_run
    db.save_run_metrics(run_id, json.dumps(metrics, sort_keys=True))
    return metrics


def make_run_id() -> str:
    return datetime.now().strftime("%Y%m%dT%H%M%S")
