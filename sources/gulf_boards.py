"""
Gulf Job Boards — Monster Gulf RSS only.

REMOVED (all return 403 or 404):
  ❌ GulfTalent — 403 Forbidden
  ❌ Saudi Greenhouse slugs (neom, saudiaramco, stc, elm) — 404
  ❌ Bayt Gulf — 403 Forbidden
  ❌ Naukrigulf Gulf — timeout

CONFIRMED WORKING:
  ✅ Monster Gulf RSS feeds
"""

import logging
import re
import xml.etree.ElementTree as ET
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}


def _fetch_monster_gulf():
    jobs = []
    seen = set()
    feeds = [
        "https://www.monstergulf.com/en-ae/jobs/cybersecurity?format=rss",
        "https://www.monstergulf.com/en-sa/jobs/cybersecurity?format=rss",
        "https://www.monstergulf.com/en-ae/jobs/information-security?format=rss",
    ]
    for url in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        try:
            xml_clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', xml)
            root = ET.fromstring(xml_clean)
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "").strip()
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                jobs.append(Job(
                    title=title, company="Monster Gulf",
                    location="Gulf", url=link,
                    source="monstergulf", tags=["monstergulf", "gulf"],
                ))
        except ET.ParseError:
            pass
    log.info(f"Monster Gulf: {len(jobs)} jobs")
    return jobs


def fetch_gulf_boards():
    """Fetch Gulf cybersecurity jobs from Monster Gulf RSS."""
    all_jobs = []
    try:
        all_jobs.extend(_fetch_monster_gulf())
    except Exception as e:
        log.warning(f"gulf_boards: _fetch_monster_gulf failed: {e}")
    return all_jobs
