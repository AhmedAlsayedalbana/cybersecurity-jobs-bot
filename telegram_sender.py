"""
Telegram message formatting and multi-topic sending.
Routes each job to the correct topic(s) in the supergroup.
Optimized for "Elite Pro" engagement.
"""

import time
import logging
import requests
from datetime import datetime, timedelta
from models import Job, _flatten_tags
from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_GROUP_ID, TELEGRAM_SEND_DELAY,
    CHANNELS, get_topic_thread_id,
    EGYPT_PATTERNS, GULF_PATTERNS, REMOTE_PATTERNS,
)

log = logging.getLogger(__name__)
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


# ─── Topic Routing ────────────────────────────────────────────

def _is_egypt_job(job: Job) -> bool:
    loc = job.location.lower()
    return any(p in loc for p in EGYPT_PATTERNS)


def _is_gulf_job(job: Job) -> bool:
    loc = job.location.lower()
    return any(p in loc for p in GULF_PATTERNS)


def _is_remote_job(job: Job) -> bool:
    if job.is_remote:
        return True
    combined = f"{job.title} {job.location} {job.job_type}".lower()
    return any(p in combined for p in REMOTE_PATTERNS)


def route_job(job: Job) -> list[str]:
    """
    Determine which topics this job should be sent to.
    Returns list of channel keys.
    """
    channels = []
    tags_str = _flatten_tags(job.tags)
    searchable = f"{job.title} {job.company} {tags_str}".lower()

    for key, ch in CHANNELS.items():
        match_type = ch.get("match", "")

        if match_type == "ALL":
            channels.append(key)
        elif match_type == "GEO_EGYPT":
            if _is_egypt_job(job):
                channels.append(key)
        elif match_type == "GEO_GULF":
            if _is_gulf_job(job) and not _is_egypt_job(job):
                channels.append(key)
        elif match_type == "REMOTE":
            if _is_remote_job(job) and not _is_egypt_job(job):
                channels.append(key)
        elif "keywords" in ch:
            kws = ch["keywords"]
            if any(kw.lower() in searchable for kw in kws):
                channels.append(key)

    return channels


# ─── Message Formatting ───────────────────────────────────────

def _escape_html(text) -> str:
    if text is None:
        return ""
    if isinstance(text, list):
        text = ", ".join(str(t) for t in text)
    text = str(text)
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )


def _location_badge(job: Job) -> str:
    """Return a geo badge string for the message."""
    if _is_egypt_job(job):
        return "Cairo, Egypt 🇪🇬"
    if _is_gulf_job(job):
        return "Gulf Region 🌙"
    if _is_remote_job(job):
        return "Remote 🌍"
    return _escape_html(job.location) if job.location else "Not specified"


def format_job_message(job: Job) -> str:
    from scoring import score_job
    score = score_job(job)
    
    title  = _escape_html(job.title)
    company = _escape_html(job.company) if job.company else "Unknown"
    badge   = _location_badge(job)

    # 1. Hooking First Line: Title
    first_line = f"🔥 <b>{title}</b>"
    
    # 2. Build Message - Elite Pro Format
    lines = [
        first_line,
        "",
        f"🏢 {company}",
        f"📍 {badge}",
        f"⭐ {score}",
        "",
    ]

    # 3. Smart Tech Focus (SIEM | Splunk | IR)
    tech_focus = []
    text = f"{job.title} {job.description} {_flatten_tags(job.tags)}".lower()
    
    # High-value tech detection
    tech_map = {
        "siem": "SIEM", "splunk": "Splunk", "qradar": "QRadar",
        "aws security": "AWS Security", "azure security": "Azure Security",
        "cloud security": "Cloud Security", "incident response": "Incident Response",
        "pentest": "Pentest", "soc": "SOC", "grc": "GRC", "appsec": "AppSec"
    }
    
    for kw, display in tech_map.items():
        if kw in text:
            tech_focus.append(display)
    
    if tech_focus:
        lines.append("🧠 " + " | ".join(tech_focus[:3]))
        lines.append("")

    lines.append(f'🔗 <b>Apply:</b>')
    lines.append(f'<a href="{job.url}">{job.url[:40]}...</a>')

    return "\n".join(lines)


# ─── Sending ──────────────────────────────────────────────────

def _send_to_topic(message: str, thread_id: int | None = None) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_GROUP_ID:
        return False

    payload = {
        "chat_id": TELEGRAM_GROUP_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if thread_id is not None:
        payload["message_thread_id"] = thread_id

    try:
        resp = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json=payload,
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        if resp.status_code == 429:
            retry_after = resp.json().get("parameters", {}).get("retry_after", 5)
            log.warning(f"Rate limited. Sleeping for {retry_after}s")
            time.sleep(retry_after)
            return _send_to_topic(message, thread_id)
            
        log.error(f"Telegram error {resp.status_code} (thread={thread_id}): {resp.text[:200]}")
        return False
    except requests.RequestException as e:
        log.error(f"Telegram request failed (thread={thread_id}): {e}")
        return False


def send_job(job: Job) -> dict:
    """Route and send a job to all matching topics. Returns {topic_key: bool}."""
    target_topics = route_job(job)
    results = {}

    if not target_topics:
        log.debug(f"No matching topics for: {job.title}")
        return results

    message = format_job_message(job)

    for topic_key in target_topics:
        thread_id = get_topic_thread_id(topic_key)
        if thread_id is None:
            continue  # topic not configured — skip silently

        topic_name = CHANNELS[topic_key]["name"]
        success = _send_to_topic(message, thread_id)
        results[topic_key] = success

        if success:
            log.info(f"  ✓ Sent to {topic_name}: {job.title[:60]}")
        else:
            log.warning(f"  ✗ Failed {topic_name}: {job.title[:60]}")

        time.sleep(0.5)

    return results


def send_jobs(jobs: list[Job]) -> int:
    """Send multiple jobs to their matching topics. Returns total sent count."""
    total_sent = 0
    topic_stats: dict[str, int] = {}

    for i, job in enumerate(jobs):
        results = send_job(job)
        for t_key, success in results.items():
            topic_stats.setdefault(t_key, 0)
            if success:
                topic_stats[t_key] += 1
                total_sent += 1

        if i < len(jobs) - 1:
            time.sleep(TELEGRAM_SEND_DELAY)

    if topic_stats:
        log.info("📊 Send summary:")
        for t_key, count in sorted(topic_stats.items()):
            t_name = CHANNELS.get(t_key, {}).get("name", t_key)
            log.info(f"  {t_name}: {count} jobs")

    return total_sent
