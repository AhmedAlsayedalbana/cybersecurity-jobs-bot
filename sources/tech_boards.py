"""
Tech Boards — Security roles at major tech companies via Greenhouse API.

REMOVED (dead / 403):
  ❌ The Muse — 0 results always
  ❌ Indeed RSS — 403 Forbidden always
  ❌ shopify, notion, hashicorp Greenhouse slugs — 404

CONFIRMED WORKING slugs only:
  ✅ stripe, airbnb, lyft, dropbox, squarespace, asana, figma,
     mongodb, datadog, cloudflare, fastly
"""

import logging
from models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
    )
}

SEC_KEYWORDS = [
    "security", "cyber", "soc", "pentest", "penetration", "grc",
    "forensic", "dfir", "malware", "threat", "vulnerability",
]

def _is_sec(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in SEC_KEYWORDS)


# ── Greenhouse Big Tech Security Teams ───────────────────────
# Only slugs confirmed working (others return 404)
BIG_TECH_GREENHOUSE = [
    ("stripe",       "Stripe"),
    ("airbnb",       "Airbnb"),
    ("lyft",         "Lyft"),
    ("dropbox",      "Dropbox"),
    ("squarespace",  "Squarespace"),
    ("asana",        "Asana"),
    ("figma",        "Figma"),
    ("mongodb",      "MongoDB"),
    ("datadog",      "Datadog"),
    ("cloudflare",   "Cloudflare"),
    ("fastly",       "Fastly"),
    # v30 additions
    ("hubspot",      "HubSpot"),
    ("zendesk",      "Zendesk"),
    ("box",          "Box"),
    ("twitch",       "Twitch"),
    ("elastic",      "Elastic"),
    ("databricks",   "Databricks"),
    ("gitlab",       "GitLab"),
    ("okta",         "Okta"),
]

def _fetch_big_tech_greenhouse():
    jobs = []
    for slug, name in BIG_TECH_GREENHOUSE:
        url  = f"https://api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
        data = get_json(url, headers=_H)
        if not data or "jobs" not in data:
            continue
        for item in data["jobs"]:
            title = item.get("title", "")
            if not _is_sec(title):
                continue
            loc      = item.get("location", {})
            location = loc.get("name", "") if isinstance(loc, dict) else ""
            is_remote = "remote" in location.lower()
            jobs.append(Job(
                title=title, company=name,
                location=location or "Not specified",
                url=item.get("absolute_url", ""),
                source="greenhouse_tech", tags=[name.lower()],
                is_remote=is_remote, original_source=name,
            ))
    log.info(f"Big Tech Greenhouse: {len(jobs)} jobs")
    return jobs


def fetch_tech_boards():
    """Fetch security roles from big tech company Greenhouse boards."""
    jobs = []
    try:
        jobs.extend(_fetch_big_tech_greenhouse())
    except Exception as e:
        log.warning(f"tech_boards: _fetch_big_tech_greenhouse failed: {e}")
    return jobs
