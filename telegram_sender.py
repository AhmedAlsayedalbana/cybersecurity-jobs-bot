"""
Telegram message formatting and multi-topic sending.
KEY FEATURE: 10 jobs per channel per run, no duplicates across channels.
Format: matches reference telegram_sender exactly.
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

def _channel_priority(ch_key: str) -> int:
    """
    Returns priority rank for a channel key.
    Lower number = higher specificity = wins when a job matches multiple channels.
    Specialty topic channels beat geo channels beat catch-all.
    """
    PRIORITY = {
        # Most specific specialty topics first
        "networksec":  1,
        "pentest":     1,
        "soc":         1,
        "appsec":      1,
        "cloudsec":    1,
        "grc":         1,
        "seceng":      2,   # broad — loses to the above
        "internships": 2,   # broad — loses to specific topics
        # Geo channels
        "egypt":       3,
        "gulf":        3,
        "remote":      3,
    }
    return PRIORITY.get(ch_key, 5)


def route_job(job):
    """
    Route a job to channels.

    Rules (v28):
    - A job is routed to ALL matching channels it qualifies for.
    - BUT at the topic level, if a job matches a high-priority topic AND a lower-priority
      one (e.g. 'network security engineer' matches both networksec AND seceng),
      the lower-priority match is dropped to avoid duplicates.
    - GEO channels (egypt, gulf, remote) are independent from topic channels.
    - A job CAN appear in one GEO channel + one TOPIC channel max.
    """
    tags_str   = _flatten_tags(job.tags)
    searchable = (job.title + " " + job.company + " " + tags_str + " " + job.description).lower()

    geo_match   = []
    topic_match = []

    GEO_CHANNELS = {"egypt", "gulf", "remote"}

    for key, ch in CHANNELS.items():
        match_type = ch.get("match", "")

        if match_type == "GEO_EGYPT":
            if _is_egypt_job(job):
                geo_match.append(key)

        elif match_type == "GEO_GULF":
            if _is_gulf_job(job) and not _is_egypt_job(job):
                geo_match.append(key)

        elif match_type == "REMOTE":
            if _is_remote_job(job) and not _is_egypt_job(job) and not _is_gulf_job(job):
                geo_match.append(key)

        elif "keywords" in ch:
            if any(kw.lower() in searchable for kw in ch["keywords"]):
                topic_match.append(key)

    # Among topic channels: keep only the highest-priority match(es).
    # If multiple channels share the same priority level, keep all of them.
    if topic_match:
        best_priority = min(_channel_priority(k) for k in topic_match)
        topic_match   = [k for k in topic_match if _channel_priority(k) == best_priority]

    # A job goes to at most 1 geo + 1 topic channel.
    # Geo: pick the first match (egypt > gulf > remote by send_order).
    geo_result   = geo_match[:1]
    topic_result = topic_match[:1]

    return geo_result + topic_result


def send_jobs(jobs):
    """
    Send jobs to Telegram channels.
    Each channel gets up to MAX_JOBS_PER_CHANNEL (5) jobs per run.

    v28 Rules:
    - STRICT global dedup: once a job URL is sent to ANY channel, it is NEVER
      sent again to any other channel in the same run.
    - Each job appears in at most 1 geo channel + 1 topic channel (enforced by route_job).
    - Jobs are sorted by score desc before sending — highest score sent first.
    - Within a channel, no duplicate URLs.
    """
    from scoring import score_job

    total_sent = 0
    channel_summary = {}

    GEO_CHANNELS   = ["egypt", "gulf", "remote"]
    TOPIC_CHANNELS = [k for k in CHANNELS.keys() if k not in GEO_CHANNELS]
    send_order     = GEO_CHANNELS + TOPIC_CHANNELS

    active  = [k for k in send_order if get_topic_thread_id(k)]
    missing = [k for k in send_order if not get_topic_thread_id(k)]
    log.info(f"📢 Active channels ({len(active)}): {', '.join(active)}")
    if missing:
        log.warning(f"⚠️  Missing thread IDs for: {', '.join(missing)} — skipping those")

    # Sort all jobs by score descending so best jobs go first
    jobs_scored = sorted(jobs, key=lambda j: -score_job(j))

    # Build per-channel queues (already filtered to best topic match by route_job)
    channel_queues = {key: [] for key in CHANNELS.keys()}
    for job in jobs_scored:
        for ch_key in route_job(job):
            if ch_key in channel_queues:
                channel_queues[ch_key].append(job)

    limit = MAX_JOBS_PER_CHANNEL
    global_sent_urls = set()   # STRICT: no URL sent twice across all channels

    for ch_key in send_order:
        ch_jobs   = channel_queues.get(ch_key, [])
        thread_id = get_topic_thread_id(ch_key)

        if not thread_id:
            continue

        ch_name = CHANNELS.get(ch_key, {}).get("name", ch_key)

        if not ch_jobs:
            log.info(f"📭 [{ch_key}] {ch_name}: 0 matching jobs this run")
            channel_summary[ch_key] = 0
            continue

        sent_this_ch = 0

        for job in ch_jobs:
            if sent_this_ch >= limit:
                break
            if job.url in global_sent_urls:   # already sent somewhere — skip
                continue

            message = format_job_message(job)
            success = _send_to_topic(message, thread_id)

            if success:
                sent_this_ch     += 1
                total_sent       += 1
                global_sent_urls.add(job.url)
                log.info(f"  ✅ [{ch_key}] {sent_this_ch}/{limit} — {job.title[:50]}")

            time.sleep(TELEGRAM_SEND_DELAY)

        channel_summary[ch_key] = sent_this_ch
        if sent_this_ch > 0:
            log.info(f"📨 Channel [{ch_key}] {ch_name}: sent {sent_this_ch} jobs")
        else:
            log.info(f"📭 Channel [{ch_key}] {ch_name}: 0 sent (all filtered/deduped)")

    log.info("=" * 40)
    log.info("📊 Per-Channel Summary:")
    for k, v in channel_summary.items():
        ch_name = CHANNELS.get(k, {}).get("name", k)
        bar = "✅" if v > 0 else "⬜"
        log.info(f"   {bar} {ch_name}: {v} jobs")
    log.info("=" * 40)

    return total_sent, global_sent_urls


# ─────────────────────────────────────────────────────────────
# ✨ Message Formatting — matches reference format exactly
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

def _match_bar(score: int) -> str:
    if score >= 18:
        return "🟢🟢🟢🟢🟢  Excellent"
    if score >= 14:
        return "🟢🟢🟢🟢⚪  Strong"
    if score >= 11:
        return "🟢🟢🟢⚪⚪  Good"
    if score >= 7:
        return "🟡🟡⚪⚪⚪  Relevant"
    return "🔵⚪⚪⚪⚪  Listed"

def _domain_emoji(domain: str) -> str:
    mapping = {
        "SOC / Blue Team":               "🖥️",
        "Penetration Testing / Red Team": "🕵️",
        "Cloud Security":                "☁️",
        "AppSec / DevSecOps":            "🛡️",
        "GRC / Compliance":              "📋",
        "DFIR / Forensics":              "🔬",
        "Network Security":              "🌐",
        "Training / Program":            "🎓",
        "Cybersecurity":                 "🔐",
    }
    return mapping.get(domain, "🔐")

def _level_emoji(level: str) -> str:
    return {"Entry-Level": "🌱", "Mid-Level": "⚙️", "Senior": "👨‍💻", "Open": "🔍"}.get(level, "🔍")


def format_job_message(job):
    from scoring import score_job
    score = score_job(job)

    text = (job.title + " " + job.description + " " + _flatten_tags(job.tags)).lower()

    level    = _detect_level(text)
    domain   = _detect_domain(text)
    location = _detect_location_flag(job)
    skills   = _extract_skills(text)
    fresh    = _freshness_badge(job)

    title   = _escape(job.title)
    company = _escape(job.company) if job.company else "Unknown"
    source  = _escape(getattr(job, "display_source", None) or job.source or "")

    is_hiring_post = job.source == "linkedin_hiring"
    is_internship  = any(k in text for k in ["intern", "trainee", "fresh grad", "graduate program"])

    d_emoji = _domain_emoji(domain)
    l_emoji = _level_emoji(level)

    lines = []

    # ── Badge row (only if exists) ────────────────────────────
    badges = []
    if fresh == "[NEW]":
        badges.append("🆕 NEW")
    elif fresh == "[Today]":
        badges.append("📅 Today")
    if is_internship:
        badges.append("🎓 Internship")
    if is_hiring_post:
        badges.append("📢 #Hiring")
    if badges:
        lines.append(f"<b>{'  ·  '.join(badges)}</b>")
        lines.append("")

    # ── Title ─────────────────────────────────────────────────
    lines.append(f"{d_emoji}  <b>{title}</b>")
    lines.append("")

    # ── Company & Location ────────────────────────────────────
    lines.append(f"🏢  <b>{company}</b>")
    lines.append(f"📍  {location}")
    lines.append("")

    # ── Role Details ──────────────────────────────────────────
    lines.append(f"<b>━━ Role Details</b>")
    lines.append(f"{l_emoji}  {level}   {d_emoji}  {domain}")
    if job.job_type:
        lines.append(f"📄  {_escape(job.job_type)}")
    if job.salary:
        lines.append(f"💰  {_escape(str(job.salary))}")
    lines.append("")

    # ── Skills ────────────────────────────────────────────────
    lines.append(f"<b>━━ Key Skills</b>")
    lines.append(f"⚡  {skills}")
    lines.append("")

    # ── Match Strength — bar + score ─────────────────────────
    lines.append(f"<b>━━ Match Strength</b>")
    lines.append(f"   {_match_bar(score)}  <b>({score})</b>")
    lines.append("")

    # ── Source ────────────────────────────────────────────────
    if is_hiring_post:
        raw_label = _escape(job.original_source or "")
        lines.append(f"📢  <i>{'Posted via: ' + raw_label if raw_label else 'Via LinkedIn #Hiring'}</i>")
    elif source:
        lines.append(f"🌐  <i>Source: {source}</i>")

    lines.append("")

    # ── Apply + short bottom separator ───────────────────────
    lines.append(f'<a href="{job.url}">🚀  Apply Now  →</a>')
    lines.append(f"<code>{'─' * 14}</code>")

    return "\n".join(lines).strip()


# ─────────────────────────────────────────────────────────────
# 📤 Sending — per channel, no cross-channel duplicates
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




