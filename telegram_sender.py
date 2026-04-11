"""
Telegram message formatting and multi-topic sending.
Elite version (UI + Smart Formatting + Entry Focus).
"""

import time
import logging
import requests
from models import Job, _flatten_tags
from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_GROUP_ID, TELEGRAM_SEND_DELAY,
    CHANNELS, get_topic_thread_id,
    EGYPT_PATTERNS, GULF_PATTERNS, REMOTE_PATTERNS,
)

log = logging.getLogger(__name__)
TELEGRAM_API = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN


# ─────────────────────────────────────────────────────────────
# 🔎 Routing
# ─────────────────────────────────────────────────────────────

def _is_egypt_job(job: Job) -> bool:
    loc = (job.location or "").lower()
    return any(p in loc for p in EGYPT_PATTERNS)


def _is_gulf_job(job: Job) -> bool:
    loc = (job.location or "").lower()
    return any(p in loc for p in GULF_PATTERNS)


def _is_remote_job(job: Job) -> bool:
    if job.is_remote:
        return True
    combined = (job.title + " " + job.location + " " + job.job_type).lower()
    return any(p in combined for p in REMOTE_PATTERNS)


def route_job(job: Job) -> list:
    channels = []
    tags_str = _flatten_tags(job.tags)
    searchable = (job.title + " " + job.company + " " + tags_str).lower()

    for key, ch in CHANNELS.items():
        match_type = ch.get("match", "")

        if match_type == "GEO_EGYPT":
            if _is_egypt_job(job):
                channels.append(key)

        elif match_type == "GEO_GULF":
            if _is_gulf_job(job) and not _is_egypt_job(job):
                channels.append(key)

        elif match_type == "REMOTE":
            if _is_remote_job(job) and not _is_egypt_job(job):
                channels.append(key)

        elif "keywords" in ch:
            if any(kw.lower() in searchable for kw in ch["keywords"]):
                channels.append(key)

    return channels


# ─────────────────────────────────────────────────────────────
# ✨ Message Formatting
# ─────────────────────────────────────────────────────────────

def _escape(text) -> str:
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _detect_level(text: str) -> str:
    if any(k in text for k in ["intern", "junior", "trainee", "entry"]):
        return "🟢 Entry-Level"
    if any(k in text for k in ["senior", "lead", "manager", "principal"]):
        return "🔴 Senior"
    return "🔥 Mid-Level"


def _detect_domain(text: str) -> str:
    if "soc" in text:
        return "🖥️ SOC / Blue Team"
    if "pentest" in text or "penetration" in text:
        return "🕵️ Pentest / Red Team"
    if "cloud" in text:
        return "☁️ Cloud Security"
    if "appsec" in text or "application security" in text:
        return "🛡️ Application Security"
    if "grc" in text or "compliance" in text:
        return "📋 GRC / Compliance"
    if "dfir" in text or "forensic" in text:
        return "🔬 DFIR / Forensics"
    return "🔐 Cybersecurity"


def _location(job: Job) -> str:
    if _is_egypt_job(job):
        return "🇪🇬 Egypt"
    if _is_gulf_job(job):
        return "🌙 Gulf"
    if _is_remote_job(job):
        return "🌍 Remote"
    return _escape(job.location)


def _extract_skills(text: str) -> str:
    skill_map = {
        "siem": "SIEM", "splunk": "Splunk", "qradar": "QRadar",
        "sentinel": "Sentinel", "aws": "AWS", "azure": "Azure",
        "incident": "Incident Response", "threat": "Threat Intel",
        "pentest": "Pentest", "burp": "Burp Suite",
        "nessus": "Nessus", "metasploit": "Metasploit",
        "iso 27001": "ISO 27001", "nist": "NIST", "grc": "GRC",
    }
    found = [label for kw, label in skill_map.items() if kw in text]
    return " | ".join(found[:3]) if found else "General Security"


def format_job_message(job: Job) -> str:
    from scoring import score_job
    score = score_job(job)

    text = (job.title + " " + job.description + " " + _flatten_tags(job.tags)).lower()

    level    = _detect_level(text)
    domain   = _detect_domain(text)
    location = _location(job)
    skills   = _extract_skills(text)

    title   = _escape(job.title)
    company = _escape(job.company) if job.company else "Unknown"

    # Trim URL for display
    display_url = job.url[:55] + "..." if len(job.url) > 55 else job.url

    message = (
        level + " <b>" + title + "</b>\n"
        "\n"
        "🏢 " + company + "\n"
        "📍 " + location + "\n"
        "🎯 " + domain + "\n"
        "⭐ Score: " + str(score) + "\n"
        "\n"
        "🧠 Skills: " + skills + "\n"
        "\n"
        '🔗 <b>Apply Now:</b>\n'
        '<a href="' + job.url + '">' + _escape(display_url) + "</a>"
    )

    return message.strip()


# ─────────────────────────────────────────────────────────────
# 📤 Sending
# ─────────────────────────────────────────────────────────────

def _send_to_topic(message: str, thread_id=None) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_GROUP_ID:
        log.warning("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_GROUP_ID")
        return False

    payload = {
        "chat_id": TELEGRAM_GROUP_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    if thread_id:
        payload["message_thread_id"] = thread_id

    try:
        resp = requests.post(
            "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendMessage",
            json=payload,
            timeout=10,
        )

        if resp.status_code == 200:
            return True

        log.error("Telegram error " + str(resp.status_code) + ": " + resp.text[:200])
        return False

    except Exception as e:
        log.error("Telegram request failed: " + str(e))
        return False


def send_job(job: Job) -> dict:
    results = {}
    topics = route_job(job)

    if not topics:
        return results

    message = format_job_message(job)

    for topic_key in topics:
        thread_id = get_topic_thread_id(topic_key)

        if not thread_id:
            continue

        success = _send_to_topic(message, thread_id)
        results[topic_key] = success

        time.sleep(0.5)

    return results


def send_jobs(jobs: list) -> int:
    total = 0

    for job in jobs:
        res = send_job(job)
        total += sum(1 for v in res.values() if v)
        time.sleep(TELEGRAM_SEND_DELAY)

    return total
