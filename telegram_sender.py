"""
Telegram message formatting and multi-topic sending — V12 (Professional System)
"""

import time
import logging
import requests
from datetime import datetime, timedelta
import config
from models import Job

log = logging.getLogger(__name__)

def _is_egypt_job(job):
    loc = (job.location or "").lower()
    return any(p in loc for p in config.EGYPT_PATTERNS)

def _is_gulf_job(job):
    loc = (job.location or "").lower()
    return any(p in loc for p in config.GULF_PATTERNS)

def _is_remote_job(job):
    if job.is_remote:
        return True
    combined = (job.title + " " + job.location + " " + job.job_type).lower()
    return any(p in combined for p in config.REMOTE_PATTERNS)

def route_job(job):
    channels = []
    searchable = (job.title + " " + job.company + " " + job.description).lower()

    for key, ch in config.CHANNELS.items():
        match_type = ch.get("match", "")

        if match_type == "GEO_EGYPT":
            if _is_egypt_job(job):
                channels.append(key)
        elif match_type == "GEO_GULF":
            if _is_gulf_job(job):
                channels.append(key)
        elif match_type == "REMOTE":
            if _is_remote_job(job) and not _is_egypt_job(job) and not _is_gulf_job(job):
                channels.append(key)
        elif "keywords" in ch:
            if any(kw.lower() in searchable for kw in ch["keywords"]):
                channels.append(key)

    return channels

def _escape(text):
    if not text: return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def format_job_message(job):
    from scoring import score_job
    score = score_job(job)
    
    title = _escape(job.title)
    company = _escape(job.company)
    location = _escape(job.location)
    
    # Smart location flag
    loc_flag = "📍"
    if "Egypt" in location: loc_flag = "🇪🇬"
    elif "Gulf" in location or "Saudi" in location or "UAE" in location: loc_flag = "🌙"
    elif job.is_remote: loc_flag = "🌍"

    # Score stars
    stars = "⭐"
    if score >= 40: stars = "⭐⭐⭐⭐⭐"
    elif score >= 30: stars = "⭐⭐⭐⭐"
    elif score >= 20: stars = "⭐⭐⭐"
    elif score >= 15: stars = "⭐⭐"

    lines = [
        f"<b>{stars} {title}</b>",
        "",
        f"🏢 <b>Company:</b> {company}",
        f"{loc_flag} <b>Location:</b> {location}",
        f"🔗 <b>Source:</b> {job.source.title()}",
        "",
        f'<a href="{job.url}">🚀 Apply Now</a>',
    ]
    
    return "\n".join(lines)

def send_jobs(jobs):
    total_sent = 0
    channel_queues = {key: [] for key in config.CHANNELS.keys()}

    for job in jobs:
        routed_channels = route_job(job)
        for ch_key in routed_channels:
            if ch_key in channel_queues:
                channel_queues[ch_key].append(job)

    for ch_key, ch_jobs in channel_queues.items():
        thread_id = config.get_topic_thread_id(ch_key)
        if not thread_id or not ch_jobs:
            continue

        sent_this_channel = 0
        for job in ch_jobs[:10]: # Max 10 per channel
            message = format_job_message(job)
            
            payload = {
                "chat_id": config.TELEGRAM_GROUP_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "message_thread_id": thread_id
            }
            
            try:
                resp = requests.post(
                    f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                    json=payload, timeout=10
                )
                if resp.status_code == 200:
                    sent_this_channel += 1
                    total_sent += 1
                time.sleep(config.TELEGRAM_SEND_DELAY)
            except:
                continue
                
        if sent_this_channel > 0:
            log.info(f"📨 Channel [{ch_key}]: sent {sent_this_channel} jobs")

    return total_sent
