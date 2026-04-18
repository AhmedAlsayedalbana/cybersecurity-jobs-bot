"""Himalayas — remote jobs. API /search returns 403 now, using public RSS + HTML."""

import logging
import re
import json
import xml.etree.ElementTree as ET
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

_H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
}

SEC_KW = [
    "security", "cyber", "soc", "pentest", "penetration", "infosec",
    "grc", "dfir", "malware", "threat", "forensic", "appsec", "devsecops",
    "vulnerability", "red team", "blue team", "detection",
]

def _is_sec(t): return any(k in t.lower() for k in SEC_KW)


def fetch_himalayas() -> list:
    """Fetch cybersecurity jobs from Himalayas via API v2 + RSS fallback."""
    jobs = []
    seen = set()

    # Try new API endpoint
    searches = [
        "cybersecurity", "security engineer", "SOC analyst",
        "penetration tester", "information security", "devsecops",
        "cloud security", "incident response", "threat intelligence",
    ]
    for q in searches:
        data = get_json(f"https://himalayas.app/jobs/api?query={q}&limit=20", headers=_H)
        if not data:
            continue
        for item in (data.get("jobs") or []):
            title = item.get("title", "")
            url   = item.get("applicationLink") or f"https://himalayas.app/jobs/{item.get('slug','')}"
            if not title or url in seen or not _is_sec(title):
                continue
            seen.add(url)
            jobs.append(Job(
                title=title,
                company=item.get("companyName", ""),
                location=item.get("location", "Remote"),
                url=url, source="himalayas",
                tags=item.get("categories", []) or [],
                is_remote=True,
            ))

    # RSS fallback
    if not jobs:
        rss_url = "https://himalayas.app/jobs/rss"
        xml = get_text(rss_url, headers=_H)
        if xml:
            try:
                root = ET.fromstring(re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', xml))
                for item in root.findall(".//item"):
                    title = (item.findtext("title") or "").strip()
                    link  = (item.findtext("link") or "").strip()
                    desc  = re.sub(r'<[^>]+>', ' ', item.findtext("description") or "").strip()[:200]
                    if not title or not link or link in seen:
                        continue
                    if not _is_sec(title + " " + desc):
                        continue
                    seen.add(link)
                    jobs.append(Job(
                        title=title, company="Himalayas",
                        location="Remote", url=link,
                        source="himalayas", is_remote=True,
                        tags=["remote", "himalayas"],
                    ))
            except ET.ParseError:
                pass

    log.info(f"Himalayas: fetched {len(jobs)} jobs.")
    return jobs
