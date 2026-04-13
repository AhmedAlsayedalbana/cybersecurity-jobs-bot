"""
Cybersecurity Boards Aggregator — V12 (Professional System)
Optimized for high-quality security sources with silent error handling.
"""

import logging
import re
import xml.etree.ElementTree as ET
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

def _is_sec(text):
    if not text: return False
    keywords = ["security", "cyber", "analyst", "pentest", "soc", "infosec", "grc"]
    return any(k in text.lower() for k in keywords)

def _fetch_cybersecjobs():
    jobs = []
    for url in ["https://cybersecjobs.com/feed/", "https://cybersecjobs.com/category/remote/feed/"]:
        try:
            xml = get_text(url, headers=_H)
            if not xml: continue
            root = ET.fromstring(re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', xml))
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link", "").strip()
                if not title or not link: continue
                jobs.append(Job(
                    title=title, company="CyberSecJobs",
                    location="Remote" if "remote" in title.lower() else "Global",
                    url=link, source="cybersecjobs",
                    tags=["cybersecjobs"], is_remote="remote" in title.lower(),
                ))
        except: continue
    return jobs

def _fetch_bugcrowd():
    jobs = []
    try:
        data = get_json("https://api.greenhouse.io/v1/boards/bugcrowd/jobs?content=true", headers=_H)
        if not data or "jobs" not in data: return jobs
        for item in data["jobs"]:
            loc = item.get("location", {})
            location = loc.get("name", "Remote") if isinstance(loc, dict) else "Remote"
            jobs.append(Job(
                title=item.get("title", ""), company="Bugcrowd",
                location=location, url=item.get("absolute_url", ""),
                source="bugcrowd", tags=["bugcrowd", "bug bounty"],
                is_remote="remote" in location.lower(),
            ))
    except: pass
    return jobs

GREENHOUSE_COMPANIES = [
    ("snyk", "Snyk"), ("wiz", "Wiz"), ("lacework", "Lacework"), ("huntress", "Huntress"),
    ("drata", "Drata"), ("vanta", "Vanta"), ("axonius", "Axonius"), ("orca", "Orca Security"),
    ("abnormalsecurity", "Abnormal Security"), ("crowdstrike", "CrowdStrike"),
    ("sentinelone", "SentinelOne"), ("paloaltonetworks", "Palo Alto Networks"),
    ("rapid7", "Rapid7"), ("tenable", "Tenable"), ("exabeam", "Exabeam"),
    ("secureworks", "Secureworks"), ("elastic", "Elastic"), ("cybereason", "Cybereason"),
]

def _fetch_greenhouse():
    jobs = []
    for slug, name in GREENHOUSE_COMPANIES:
        try:
            url = f"https://api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
            data = get_json(url, headers=_H)
            if not data or "jobs" not in data: continue
            for item in data["jobs"]:
                title = item.get("title", "")
                if not _is_sec(title): continue
                loc = item.get("location", {})
                location = loc.get("name", "Remote") if isinstance(loc, dict) else "Remote"
                jobs.append(Job(
                    title=title, company=name, location=location,
                    url=item.get("absolute_url", ""), source="greenhouse",
                    tags=[name.lower()], is_remote="remote" in location.lower(),
                ))
        except: continue
    return jobs

LEVER_COMPANIES = [
    ("cloudflare", "Cloudflare"), ("1password", "1Password"), ("bitwarden", "Bitwarden"),
    ("securityscorecard", "SecurityScorecard"), ("cyberark", "CyberArk"),
    ("recordedfuture", "Recorded Future"), ("intigriti", "Intigriti"), ("detectify", "Detectify"),
]

def _fetch_lever():
    jobs = []
    for cid, name in LEVER_COMPANIES:
        try:
            url = f"https://api.lever.co/v0/postings/{cid}?mode=json"
            data = get_json(url, headers=_H)
            if not data or not isinstance(data, list): continue
            for item in data:
                title = item.get("text", "")
                if not _is_sec(title): continue
                cats = item.get("categories", {}) or {}
                location = cats.get("location", "Remote")
                jobs.append(Job(
                    title=title, company=name, location=location,
                    url=item.get("hostedUrl", ""), source="lever",
                    tags=[name.lower()], is_remote="remote" in location.lower(),
                ))
        except: continue
    return jobs

def fetch_cybersec_boards():
    all_jobs = []
    for fetcher in [_fetch_cybersecjobs, _fetch_bugcrowd, _fetch_greenhouse, _fetch_lever]:
        try:
            all_jobs.extend(fetcher())
        except: pass
    return all_jobs
