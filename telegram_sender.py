"""
Telegram message formatting and multi-topic sending.
KEY FEATURE: 10 jobs per channel per run, no duplicates across channels.
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
    MAX_JOBS_PER_CHANNEL,
)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# 🔎 Geo Helpers
# ─────────────────────────────────────────────────────────────

def _is_egypt_job(job):
    loc = (job.location or "").lower()
    return any(p in loc for p in EGYPT_PATTERNS)

def _is_gulf_job(job):
    loc = (job.location or "").lower()
    return any(p in loc for p in GULF_PATTERNS)

def _is_remote_job(job):
    if job.is_remote:
        return True
    combined = (job.title + " " + job.location + " " + job.job_type).lower()
    return any(p in combined for p in REMOTE_PATTERNS)


# ─────────────────────────────────────────────────────────────
# 🔎 Routing — which channels gets this job
# ─────────────────────────────────────────────────────────────

def route_job(job):
    channels = []
    tags_str = _flatten_tags(job.tags)
    searchable = (job.title + " " + job.company + " " + tags_str + " " + job.description).lower()

    for key, ch in CHANNELS.items():
        match_type = ch.get("match", "")

        if match_type == "GEO_EGYPT":
            if _is_egypt_job(job):
                channels.append(key)

        elif match_type == "GEO_GULF":
            if _is_gulf_job(job) and not _is_egypt_job(job):
                channels.append(key)

        elif match_type == "REMOTE":
            if _is_remote_job(job) and not _is_egypt_job(job) and not _is_gulf_job(job):
                channels.append(key)

        elif "keywords" in ch:
            if any(kw.lower() in searchable for kw in ch["keywords"]):
                channels.append(key)

    return channels


# ─────────────────────────────────────────────────────────────
# ✨ Message Formatting
# ─────────────────────────────────────────────────────────────

def _escape(text):
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _detect_level(text):
    if any(k in text for k in ["intern", "junior", "trainee", "entry", "fresh grad", "graduate"]):
        return "Entry-Level"
    if any(k in text for k in ["senior", "lead", "manager", "principal", "head", "director"]):
        return "Senior"
    if any(k in text for k in ["mid", "intermediate", "associate"]):
        return "Mid-Level"
    return "Open"

def _detect_domain(text):
    if any(k in text for k in ["soc", "security operations", "blue team", "dfir", "siem"]):
        return "SOC / Blue Team"
    if any(k in text for k in ["pentest", "penetration", "red team", "ethical hack", "bug bounty", "offensive"]):
        return "Penetration Testing / Red Team"
    if any(k in text for k in ["cloud security", "aws security", "azure security", "gcp security"]):
        return "Cloud Security"
    if any(k in text for k in ["appsec", "application security", "devsecops", "sast", "dast"]):
        return "AppSec / DevSecOps"
    if any(k in text for k in ["grc", "compliance", "iso 27001", "auditor", "risk"]):
        return "GRC / Compliance"
    if any(k in text for k in ["dfir", "forensic", "malware", "reverse engineering"]):
        return "DFIR / Forensics"
    if any(k in text for k in ["network security", "firewall", "ids", "ips", "zero trust"]):
        return "Network Security"
    if any(k in text for k in ["training", "program", "track", "course", "scholarship"]):
        return "Training / Program"
    return "Cybersecurity"

def _detect_location_flag(job):
    if _is_egypt_job(job):
        loc = (job.location or "").lower()
        if "cairo" in loc or "القاهرة" in loc:
            return "🇪🇬 Cairo, Egypt"
        if "alex" in loc or "الإسكندرية" in loc:
            return "🇪🇬 Alexandria, Egypt"
        return "🇪🇬 Egypt"
    if _is_gulf_job(job):
        loc = (job.location or "").lower()
        if "saudi" in loc or "ksa" in loc or "riyadh" in loc or "jeddah" in loc:
            return "🇸🇦 Saudi Arabia"
        if "dubai" in loc or "uae" in loc or "abu dhabi" in loc:
            return "🇦🇪 UAE"
        if "qatar" in loc or "doha" in loc:
            return "🇶🇦 Qatar"
        if "kuwait" in loc:
            return "🇰🇼 Kuwait"
        if "bahrain" in loc:
            return "🇧🇭 Bahrain"
        if "oman" in loc or "muscat" in loc:
            return "🇴🇲 Oman"
        return "🌙 Gulf"
    if _is_remote_job(job):
        return "🌍 Remote / Worldwide"
    return "📍 " + _escape(job.location or "Unknown")

def _freshness_badge(job):
    if not job.posted_date:
        return ""
    diff = datetime.now() - job.posted_date
    if diff < timedelta(hours=6):
        return "[NEW]"
    if diff < timedelta(hours=24):
        return "[Today]"
    return ""

def _extract_skills(text):
    skill_map = {
        "siem": "SIEM", "splunk": "Splunk", "qradar": "QRadar",
        "sentinel": "Sentinel", "aws": "AWS", "azure": "Azure",
        "gcp": "GCP", "incident": "IR", "threat": "Threat Intel",
        "pentest": "Pentest", "burp": "Burp Suite", "nessus": "Nessus",
        "metasploit": "Metasploit", "iso 27001": "ISO 27001",
        "nist": "NIST", "grc": "GRC", "pci": "PCI-DSS",
        "crowdstrike": "CrowdStrike", "defender": "MS Defender",
        "wireshark": "Wireshark", "oscp": "OSCP", "cissp": "CISSP",
        "ceh": "CEH", "python": "Python", "soc": "SOC",
    }
    found = [label for kw, label in skill_map.items() if kw in text]
    return ", ".join(found[:5]) if found else "General Security"

def _score_label(score):
    if score >= 18:
        return "High Priority"
    if score >= 11:
        return "Good Match"
    if score >= 5:
        return "Relevant"
    return "Listed"

def format_job_message(job):
    from scoring import score_job
    score = score_job(job)

    text = (job.title + " " + job.description + " " + _flatten_tags(job.tags)).lower()

    level    = _detect_level(text)
    domain   = _detect_domain(text)
    location = _detect_location_flag(job)
    skills   = _extract_skills(text)
    fresh    = _freshness_badge(job)
    match    = _score_label(score)

    title   = _escape(job.title)
    company = _escape(job.company) if job.company else "Unknown"
    source  = _escape(job.display_source or job.source or "")

    is_hiring_post = job.source == "linkedin_hiring"

    # ── Header ──
    if is_hiring_post:
        header = f"<b>{title}</b>"
        if fresh:
            header = fresh.strip() + "  " + header
    else:
        header = f"<b>{title}</b>"
        if fresh:
            header = fresh.strip() + "  " + header

    # ── Build lines ──
    lines = [header, ""]

    if is_hiring_post:
        # Show the original raw title the person posted with
        raw_label = _escape(job.original_source or "")
        if raw_label and raw_label != f"#Hiring — {job.title}":
            lines.append(f"Posted as:  {raw_label}")

    lines += [
        f"Company:    {company}",
        f"Location:   {location}",
        f"Domain:     {domain}",
        f"Level:      {level}",
        f"Skills:     {skills}",
        f"Relevance:  {match}",
    ]

    if job.salary:
        lines.append(f"Salary:     {_escape(str(job.salary))}")

    if job.job_type:
        lines.append(f"Type:       {_escape(job.job_type)}")

    if is_hiring_post:
        lines.append(f"Via:        LinkedIn #Hiring Post")
    elif source:
        lines.append(f"Source:     {source}")

    lines += [
        "",
        f'<a href="{job.url}">Apply Now</a>',
    ]

    return "\n".join(lines).strip()


# ─────────────────────────────────────────────────────────────
# 📤 Sending — 10 jobs per channel, no cross-channel duplicates
# ─────────────────────────────────────────────────────────────

def _send_to_topic(message, thread_id=None):
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


def send_jobs(jobs):
    """
    Send jobs to Telegram channels.
    Each channel gets MAX_JOBS_PER_CHANNEL unique jobs.
    A job is sent to at most ONE channel to avoid cross-channel duplicates.
    Priority order: GEO channels first (egypt, gulf, remote), then topic channels.
    """
    total_sent = 0

    # Track which jobs have been sent (by URL) across ALL channels
    globally_sent_urls = set()

    # Build per-channel queues
    channel_queues = {key: [] for key in CHANNELS.keys()}

    for job in jobs:
        routed_channels = route_job(job)
        for ch_key in routed_channels:
            if ch_key in channel_queues:
                channel_queues[ch_key].append(job)

    # Send in priority order: geo channels first, then topic channels
    GEO_CHANNELS = ["egypt", "gulf", "remote"]
    TOPIC_CHANNELS = [k for k in CHANNELS.keys() if k not in GEO_CHANNELS]
    send_order = GEO_CHANNELS + TOPIC_CHANNELS

    limit = MAX_JOBS_PER_CHANNEL

    for ch_key in send_order:
        if ch_key not in channel_queues:
            continue

        ch_jobs = channel_queues[ch_key]
        thread_id = get_topic_thread_id(ch_key)
        if not thread_id or not ch_jobs:
            continue

        sent_this_channel = 0

        for job in ch_jobs:
            if sent_this_channel >= limit:
                break
            # Skip if already sent to any channel
            if job.url in globally_sent_urls:
                continue

            message = format_job_message(job)
            success = _send_to_topic(message, thread_id)

            if success:
                sent_this_channel += 1
                total_sent += 1
                globally_sent_urls.add(job.url)
                log.info(
                    "  ✅ [" + ch_key + "] " +
                    str(sent_this_channel) + "/" + str(limit) +
                    " — " + job.title[:50]
                )

            time.sleep(TELEGRAM_SEND_DELAY)

        if sent_this_channel > 0:
            log.info("📨 Channel [" + ch_key + "]: sent " + str(sent_this_channel) + " jobs")

    return total_sent

    return total_sent
"""
Telegram message formatting and multi-topic sending.
KEY FEATURE: 10 jobs per channel per run, no duplicates across channels.
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
    MAX_JOBS_PER_CHANNEL,
)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# 🔎 Geo Helpers
# ─────────────────────────────────────────────────────────────

def _is_egypt_job(job):
    loc = (job.location or "").lower()
    return any(p in loc for p in EGYPT_PATTERNS)

def _is_gulf_job(job):
    loc = (job.location or "").lower()
    return any(p in loc for p in GULF_PATTERNS)

def _is_remote_job(job):
    if job.is_remote:
        return True
    combined = (job.title + " " + job.location + " " + job.job_type).lower()
    return any(p in combined for p in REMOTE_PATTERNS)


# ─────────────────────────────────────────────────────────────
# 🔎 Routing — which channels gets this job
# ─────────────────────────────────────────────────────────────

def route_job(job):
    channels = []
    tags_str = _flatten_tags(job.tags)
    searchable = (job.title + " " + job.company + " " + tags_str + " " + job.description).lower()

    for key, ch in CHANNELS.items():
        match_type = ch.get("match", "")

        if match_type == "GEO_EGYPT":
            if _is_egypt_job(job):
                channels.append(key)

        elif match_type == "GEO_GULF":
            if _is_gulf_job(job) and not _is_egypt_job(job):
                channels.append(key)

        elif match_type == "REMOTE":
            if _is_remote_job(job) and not _is_egypt_job(job) and not _is_gulf_job(job):
                channels.append(key)

        elif "keywords" in ch:
            if any(kw.lower() in searchable for kw in ch["keywords"]):
                channels.append(key)

    return channels


# ─────────────────────────────────────────────────────────────
# ✨ Message Formatting
# ─────────────────────────────────────────────────────────────

def _escape(text):
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _detect_level(text):
    if any(k in text for k in ["intern", "junior", "trainee", "entry", "fresh grad", "graduate"]):
        return "🟢 Entry-Level"
    if any(k in text for k in ["senior", "lead", "manager", "principal", "head", "director"]):
        return "🔴 Senior"
    if any(k in text for k in ["mid", "intermediate", "associate"]):
        return "🟡 Mid-Level"
    return "🔵 Open-Level"

def _detect_domain(text):
    if any(k in text for k in ["soc", "security operations", "blue team", "dfir", "siem"]):
        return "🖥️ SOC / Blue Team"
    if any(k in text for k in ["pentest", "penetration", "red team", "ethical hack", "bug bounty", "offensive"]):
        return "🕵️ Pentest / Red Team"
    if any(k in text for k in ["cloud security", "aws security", "azure security", "gcp security"]):
        return "☁️ Cloud Security"
    if any(k in text for k in ["appsec", "application security", "devsecops", "sast", "dast"]):
        return "🛡️ AppSec / DevSecOps"
    if any(k in text for k in ["grc", "compliance", "iso 27001", "auditor", "risk"]):
        return "📋 GRC / Compliance"
    if any(k in text for k in ["dfir", "forensic", "malware", "reverse engineering"]):
        return "🔬 DFIR / Forensics"
    if any(k in text for k in ["network security", "firewall", "ids", "ips", "zero trust"]):
        return "🌐 Network Security"
    if any(k in text for k in ["training", "program", "track", "course", "scholarship", "منحة"]):
        return "🎓 Training / Program"
    return "🔐 Cybersecurity"

def _detect_location_flag(job):
    if _is_egypt_job(job):
        loc = (job.location or "").lower()
        if "cairo" in loc or "القاهرة" in loc:
            return "🇪🇬 Cairo, Egypt"
        if "alex" in loc or "الإسكندرية" in loc:
            return "🇪🇬 Alexandria, Egypt"
        return "🇪🇬 Egypt"
    if _is_gulf_job(job):
        loc = (job.location or "").lower()
        if "saudi" in loc or "ksa" in loc or "riyadh" in loc or "jeddah" in loc:
            return "🇸🇦 Saudi Arabia"
        if "dubai" in loc or "uae" in loc or "abu dhabi" in loc:
            return "🇦🇪 UAE"
        if "qatar" in loc or "doha" in loc:
            return "🇶🇦 Qatar"
        if "kuwait" in loc:
            return "🇰🇼 Kuwait"
        if "bahrain" in loc:
            return "🇧🇭 Bahrain"
        if "oman" in loc or "muscat" in loc:
            return "🇴🇲 Oman"
        return "🌙 Gulf"
    if _is_remote_job(job):
        return "🌍 Remote / Worldwide"
    return "📍 " + _escape(job.location or "Unknown")

def _freshness_badge(job):
    if not job.posted_date:
        return ""
    diff = datetime.now() - job.posted_date
    if diff < timedelta(hours=6):
        return " 🔥 NEW"
    if diff < timedelta(hours=24):
        return " ⚡ Today"
    return ""

def _extract_skills(text):
    skill_map = {
        "siem": "SIEM", "splunk": "Splunk", "qradar": "QRadar",
        "sentinel": "Sentinel", "aws": "AWS", "azure": "Azure",
        "gcp": "GCP", "incident": "IR", "threat": "Threat Intel",
        "pentest": "Pentest", "burp": "Burp Suite", "nessus": "Nessus",
        "metasploit": "Metasploit", "iso 27001": "ISO 27001",
        "nist": "NIST", "grc": "GRC", "pci": "PCI-DSS",
        "crowdstrike": "CrowdStrike", "defender": "MS Defender",
        "wireshark": "Wireshark", "oscp": "OSCP", "cissp": "CISSP",
        "ceh": "CEH", "python": "Python", "soc": "SOC",
    }
    found = [label for kw, label in skill_map.items() if kw in text]
    return " | ".join(found[:4]) if found else "General Security"

def _score_label(score):
    if score >= 20:
        return "⭐⭐⭐ Priority"
    if score >= 12:
        return "⭐⭐ Good Match"
    if score >= 6:
        return "⭐ Relevant"
    return "📌 Listed"

def format_job_message(job):
    from scoring import score_job
    score = score_job(job)

    text = (job.title + " " + job.description + " " + _flatten_tags(job.tags)).lower()

    level    = _detect_level(text)
    domain   = _detect_domain(text)
    location = _detect_location_flag(job)
    skills   = _extract_skills(text)
    fresh    = _freshness_badge(job)
    match    = _score_label(score)

    title   = _escape(job.title)
    company = _escape(job.company) if job.company else "Unknown"
    source  = _escape(job.display_source or job.source or "")

    display_url = job.url[:60] + "..." if len(job.url) > 60 else job.url

    lines = [
        level + fresh + "  <b>" + title + "</b>",
        "",
        "🏢 " + company,
        "📍 " + location,
        "🎯 " + domain,
        "🧠 " + skills,
        "📊 " + match,
    ]

    if job.salary:
        lines.append("💰 " + _escape(str(job.salary)))

    if source:
        lines.append("🔗 via " + source)

    lines += [
        "",
        '<a href="' + job.url + '">👆 Apply Now</a>',
    ]

    return "\n".join(lines).strip()


# ─────────────────────────────────────────────────────────────
# 📤 Sending — 10 jobs per channel, no cross-channel duplicates
# ─────────────────────────────────────────────────────────────

def _send_to_topic(message, thread_id=None):
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


def send_jobs(jobs):
    """
    Send jobs to Telegram channels.
    Each channel gets MAX_JOBS_PER_CHANNEL (10) unique jobs.
    A job can appear in multiple channels (e.g., Egypt channel + SOC channel).
    Tracks sent jobs per channel to avoid duplicates within a channel.
    """
    total_sent = 0

    # Build per-channel queues
    channel_queues = {key: [] for key in CHANNELS.keys()}

    for job in jobs:
        routed_channels = route_job(job)
        for ch_key in routed_channels:
            if ch_key in channel_queues:
                channel_queues[ch_key].append(job)

    # Send up to MAX_JOBS_PER_CHANNEL per channel
    limit = MAX_JOBS_PER_CHANNEL

    for ch_key, ch_jobs in channel_queues.items():
        thread_id = get_topic_thread_id(ch_key)
        if not thread_id:
            continue

        if not ch_jobs:
            continue

        sent_this_channel = 0
        seen_urls_this_channel = set()

        for job in ch_jobs:
            if sent_this_channel >= limit:
                break
            if job.url in seen_urls_this_channel:
                continue

            message = format_job_message(job)
            success = _send_to_topic(message, thread_id)

            if success:
                sent_this_channel += 1
                total_sent += 1
                seen_urls_this_channel.add(job.url)
                log.info(
                    "  ✅ [" + ch_key + "] " +
                    str(sent_this_channel) + "/" + str(limit) +
                    " — " + job.title[:50]
                )

            time.sleep(TELEGRAM_SEND_DELAY)

        if sent_this_channel > 0:
            log.info("📨 Channel [" + ch_key + "]: sent " + str(sent_this_channel) + " jobs")

    return total_sent
