"""LinkedIn HR post discovery with scoring and confidence gates."""

from __future__ import annotations

import logging
import random
import re
import time
import urllib.parse
from datetime import datetime
from html import unescape

import config
from config import (
    GOOGLE_CSE_API_KEY,
    GOOGLE_CSE_CX,
    HR_CONFIDENCE_THRESHOLD,
    HR_HIRING_THRESHOLD,
    LI_HR_POST_BUDGET_SECONDS,
    SERPAPI_KEY,
)
from linkedin_url_utils import (
    extract_linkedin_post_id,
    is_valid_linkedin_canonical,
    normalize_linkedin_url,
)
from models import Job
from sources.http_utils import get_json, get_text

log = logging.getLogger(__name__)

MAX_BUDGET_SECS = LI_HR_POST_BUDGET_SECONDS
_GOOGLE_CSE_DISABLED = False
_SERPAPI_DISABLED = False

SEARCH_QUERIES = [
    # Egypt (EN + AR)
    'site:linkedin.com/posts "#hiring" "cybersecurity" Egypt',
    'site:linkedin.com/posts "#hiring" "SOC analyst" Egypt',
    'site:linkedin.com/posts "#hiring" "information security" Egypt',
    'site:linkedin.com/posts "#hiring" "security engineer" Egypt',
    'site:linkedin.com/posts "#hiring" "GRC" Egypt',
    'site:linkedin.com/posts "#hiring" "Ø£Ù…Ù† Ø³ÙŠØ¨Ø±Ø§Ù†ÙŠ" Egypt',
    'site:linkedin.com/in/ "#hiring" "cybersecurity" Egypt',
    'site:linkedin.com/in/ "we are hiring" "SOC analyst" Egypt',
    # Gulf
    'site:linkedin.com/posts "#hiring" "cybersecurity" "Saudi Arabia"',
    'site:linkedin.com/posts "#hiring" "SOC analyst" UAE Dubai',
    'site:linkedin.com/posts "#hiring" "cybersecurity" Kuwait',
    'site:linkedin.com/in/ "#hiring" "information security" "Saudi Arabia"',
]

HIRING_SIGNALS = {
    "#hiring": 5,
    "we are hiring": 5,
    "hiring now": 5,
    "urgent hiring": 8,
    "vacancy": 4,
    "open role": 4,
    "join our team": 3,
    "looking for": 4,
    "send cv": 5,
    "apply now": 4,
    "Ù†Ø­Ù† Ø¨ØµØ¯Ø¯ Ø§Ù„ØªÙˆØ¸ÙŠÙ": 4,
    "Ù…Ø·Ù„ÙˆØ¨": 3,
    "ÙØ±ØµØ© Ø¹Ù…Ù„": 3,
    "Ø£Ø±Ø³Ù„ Ø§Ù„Ø³ÙŠØ±Ø© Ø§Ù„Ø°Ø§ØªÙŠØ©": 4,
}

ROLE_SIGNALS = {
    "soc analyst": 7,
    "soc engineer": 7,
    "security operations center": 7,
    "incident response": 6,
    "dfir": 6,
    "threat intelligence": 6,
    "penetration tester": 7,
    "red team": 6,
    "appsec": 6,
    "application security": 6,
    "cloud security": 6,
    "grc": 6,
    "network security": 6,
    "security engineer": 7,
    "cybersecurity specialist": 6,
    "cybersecurity": 5,
    "information security": 5,
    "Ø£Ù…Ù† Ø³ÙŠØ¨Ø±Ø§Ù†ÙŠ": 5,
    "Ø£Ù…Ù† Ù…Ø¹Ù„ÙˆÙ…Ø§Øª": 5,
}

LOCATION_SIGNALS = {
    "egypt": 3,
    "cairo": 3,
    "alexandria": 3,
    "saudi": 3,
    "riyadh": 3,
    "uae": 3,
    "dubai": 3,
    "kuwait": 3,
    "qatar": 3,
    "giza": 3,
    "alexandria": 3,
    "jeddah": 3,
    "abu dhabi": 3,
    "doha": 3,
}

SOURCE_QUALITY_BONUS = {
    "google_cse": 2,
    "serpapi": 1,
    "duckduckgo": 0,
}

_ROLE_MAP = [
    (["soc analyst", "security operations analyst"], "SOC Analyst"),
    (["soc engineer", "security operations engineer"], "SOC Engineer"),
    (["threat intel", "threat intelligence", "cti"], "Threat Intelligence Analyst"),
    (["incident resp", "ir analyst", "dfir"], "Incident Response / DFIR"),
    (["penetration tester", "pen tester", "pentester"], "Penetration Tester"),
    (["red team"], "Red Team Engineer"),
    (["appsec", "application security"], "Application Security Engineer"),
    (["cloud security", "aws security", "azure security"], "Cloud Security Engineer"),
    (["network security"], "Network Security Engineer"),
    (["grc", "governance risk", "compliance", "iso 27001"], "GRC / Compliance Analyst"),
    (["security engineer", "cybersecurity engineer"], "Security Engineer"),
    (["intern", "trainee", "fresh grad", "junior"], "Security Intern / Junior"),
    (["cybersecurity", "cyber security", "infosec"], "Cybersecurity Specialist"),
    (["security analyst", "security specialist"], "Security Analyst"),
]


def _match_title(raw: str) -> str:
    text = (raw or "").lower()
    for keywords, canonical in _ROLE_MAP:
        if any(term in text for term in keywords):
            return canonical
    return (raw or "Cybersecurity Role").strip().title()


def _detect_location(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ["egypt", "cairo", "giza", "alexandria"]):
        return "Egypt"
    if any(k in t for k in ["saudi", "riyadh", "jeddah", "ksa"]):
        return "Saudi Arabia"
    if any(k in t for k in ["uae", "dubai", "abu dhabi"]):
        return "UAE"
    if "kuwait" in t:
        return "Kuwait"
    if any(k in t for k in ["qatar", "doha"]):
        return "Qatar"
    return "Unknown"


def _extract_company_from_post(text: str) -> str:
    for sep in ["|", "@", " at ", " - "]:
        if sep in text:
            parts = text.split(sep)
            if len(parts) >= 2:
                candidate = parts[-1].strip()
                if 3 < len(candidate) < 80:
                    return candidate
    return "Unknown"


def _extract_apply_info(text: str) -> dict:
    info: dict[str, str] = {}
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}", text)
    if email_match:
        info["email"] = email_match.group(0)

    wa_match = re.search(r"\+?[\d\s\-()]{10,20}", text)
    if wa_match and any(k in text.lower() for k in ["whatsapp", "wp:", "wa:"]):
        info["whatsapp"] = wa_match.group(0).strip()

    link_match = re.search(r'https?://[^\s<>"\']+', text)
    if link_match and "linkedin.com" not in link_match.group(0):
        info["apply_link"] = link_match.group(0)
    return info


def _build_description(raw_text: str, apply_info: dict) -> str:
    lines: list[str] = []
    if raw_text:
        lines.append(raw_text[:300].replace("\n", " ").strip())
    if apply_info.get("email"):
        lines.append(f"EMAIL:{apply_info['email']}")
    if apply_info.get("whatsapp"):
        lines.append(f"WHATSAPP:{apply_info['whatsapp']}")
    if apply_info.get("apply_link"):
        lines.append(f"APPLY_LINK:{apply_info['apply_link']}")
    return "\n".join(lines)


def _score_signal_map(text: str, weights: dict[str, int]) -> tuple[int, list[str]]:
    lowered = text.lower()
    score = 0
    hits: list[str] = []
    for phrase, weight in weights.items():
        if phrase in lowered:
            score += weight
            hits.append(phrase)
    return score, hits


def _compute_confidence(
    *,
    title: str,
    raw_text: str,
    location: str,
    apply_info: dict,
    source_backend: str,
    company: str,
) -> tuple[int, int, list[str]]:
    combined = f"{title}\n{raw_text}\n{location}".lower()

    hiring_score, hiring_hits = _score_signal_map(combined, HIRING_SIGNALS)
    role_score, role_hits = _score_signal_map(combined, ROLE_SIGNALS)
    location_score, location_hits = _score_signal_map(combined, LOCATION_SIGNALS)

    contact_score = 0
    if apply_info.get("email"):
        contact_score += 3
    if apply_info.get("whatsapp"):
        contact_score += 2
    if apply_info.get("apply_link"):
        contact_score += 2

    source_bonus = SOURCE_QUALITY_BONUS.get(source_backend, 0)
    penalties = 0

    title_lower = (title or "").strip().lower()
    if len(title_lower) < 5:
        penalties += 3
    if title_lower in {"hiring", "vacancy", "job opening"}:
        penalties += 4
    if company == "Unknown":
        penalties += 2
    if hiring_score == 0:
        penalties += 3
    if role_score == 0:
        penalties += 4
    if title_lower in {"security role", "cybersecurity role"}:
        penalties += 3

    confidence = hiring_score + role_score + location_score + contact_score + source_bonus - penalties
    debug_hits = hiring_hits + role_hits + location_hits
    return hiring_score, confidence, debug_hits


def _normalize_candidate_link(url: str) -> str:
    canonical = normalize_linkedin_url(url)
    if not canonical:
        return ""
    if not is_valid_linkedin_canonical(canonical):
        return ""
    return canonical


def _search_via_google_cse(query: str) -> list[tuple[str, str]]:
    global _GOOGLE_CSE_DISABLED
    if _GOOGLE_CSE_DISABLED:
        return []
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_CX:
        return []
    params = {
        "key": GOOGLE_CSE_API_KEY,
        "cx": GOOGLE_CSE_CX,
        "q": query,
        "num": "10",
        "dateRestrict": "d2",
    }
    data = get_json("https://www.googleapis.com/customsearch/v1", params=params, max_retries=1)
    if not data:
        _GOOGLE_CSE_DISABLED = True
        log.warning("LinkedIn HR Posts: Google CSE unavailable/blocked; disabled for this run.")
        return []
    out: list[tuple[str, str]] = []
    for item in data.get("items", []):
        canonical = _normalize_candidate_link(item.get("link", ""))
        if canonical:
            out.append((canonical, "google_cse"))
    return out


def _search_via_serpapi(query: str) -> list[tuple[str, str]]:
    global _SERPAPI_DISABLED
    if _SERPAPI_DISABLED:
        return []
    if not SERPAPI_KEY:
        return []
    params = {
        "q": query,
        "api_key": SERPAPI_KEY,
        "engine": "google",
        "num": "10",
        "gl": "eg",
        "hl": "en",
        "tbs": "qdr:d2",
    }
    data = get_json("https://serpapi.com/search", params=params, max_retries=0)
    if not data:
        _SERPAPI_DISABLED = True
        log.warning("LinkedIn HR Posts: SerpAPI unavailable/rate-limited; disabled for this run.")
        return []
    out: list[tuple[str, str]] = []
    for row in data.get("organic_results", []):
        canonical = _normalize_candidate_link(row.get("link", ""))
        if canonical:
            out.append((canonical, "serpapi"))
    return out


def _search_via_duckduckgo(query: str) -> list[tuple[str, str]]:
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    html = get_text(url, headers=headers, timeout=8, max_retries=1)
    if not html:
        return []

    found: list[str] = re.findall(r'href="(https?://[^"]+linkedin\.com[^"]+)"', html)
    encoded = re.findall(r"uddg=(https?%3A%2F%2F[^&\"]+linkedin[^&\"]+)", html)
    for item in encoded:
        found.append(urllib.parse.unquote(item))

    out: list[tuple[str, str]] = []
    for raw in found:
        canonical = _normalize_candidate_link(unescape(raw))
        if canonical:
            out.append((canonical, "duckduckgo"))
    return out


def _search_urls(query: str) -> list[tuple[str, str]]:
    for search_fn in (_search_via_google_cse, _search_via_serpapi, _search_via_duckduckgo):
        urls = search_fn(query)
        if urls:
            return urls
    return []


def _scrape_linkedin_post(url: str, backend: str) -> dict | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ar,en;q=0.9",
    }
    html = get_text(url, headers=headers)
    if not html or len(html) < 500:
        return None

    raw_text = ""
    og_desc = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"', html)
    if og_desc:
        raw_text = og_desc.group(1)
    else:
        article = re.search(r"<article[^>]*>(.*?)</article>", html, re.DOTALL)
        if article:
            raw_text = re.sub(r"<[^>]+>", " ", article.group(1))

    raw_text = unescape(raw_text).strip()
    if len(raw_text) < 20:
        return None

    title = ""
    m = re.search(r"(?:hiring|#hiring)[:\s�-]+([^\n.!?|]{5,80})", raw_text, re.IGNORECASE)
    if m:
        title = m.group(1).strip()
    if not title:
        m2 = re.search(r"([A-Za-z0-9+/&\-\s]{5,60})\s*[|@]\s*([A-Za-z0-9&\-\s]{3,60})", raw_text)
        if m2:
            title = m2.group(1).strip()
    if not title:
        first = raw_text.split("\n", 1)[0].strip()
        title = first[:80] if len(first) > 5 else "Cybersecurity Role"

    company = _extract_company_from_post(raw_text)
    location = _detect_location(raw_text)
    apply_info = _extract_apply_info(raw_text)

    hiring_score, confidence, signal_hits = _compute_confidence(
        title=title,
        raw_text=raw_text,
        location=location,
        apply_info=apply_info,
        source_backend=backend,
        company=company,
    )

    if hiring_score < HR_HIRING_THRESHOLD or confidence < HR_CONFIDENCE_THRESHOLD:
        log.debug(
            "HR post rejected: hiring=%s confidence=%s threshold=(%s,%s) url=%s hits=%s",
            hiring_score,
            confidence,
            HR_HIRING_THRESHOLD,
            HR_CONFIDENCE_THRESHOLD,
            url,
            ", ".join(signal_hits[:8]),
        )
        return None

    posted_date = None
    date_match = re.search(
        r'(?:datePublished|article:published_time)"?\s*(?:content=|:)\s*"([^"]+)"',
        html,
    )
    if date_match:
        try:
            posted_date = datetime.fromisoformat(date_match.group(1).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            posted_date = None

    log.debug(
        "HR post accepted: hiring=%s confidence=%s url=%s",
        hiring_score,
        confidence,
        url,
    )

    return {
        "title": title,
        "company": company,
        "location": location,
        "raw_text": raw_text,
        "apply_info": apply_info,
        "posted_date": posted_date,
        "url": url,
        "backend": backend,
        "hiring_score": hiring_score,
        "confidence": confidence,
    }


def fetch_linkedin_hr_posts_scraper() -> list[Job]:
    jobs: list[Job] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    start = time.time()

    for query in SEARCH_QUERIES:
        if time.time() - start > MAX_BUDGET_SECS:
            log.info("linkedin_hr_posts_scraper: budget exhausted early")
            break

        urls = _search_urls(query)
        if not urls:
            time.sleep(random.uniform(0.8, 1.6))
            continue

        for canonical_url, backend in urls:
            if canonical_url in seen_urls:
                continue
            seen_urls.add(canonical_url)

            try:
                data = _scrape_linkedin_post(canonical_url, backend)
            except Exception as exc:
                log.debug(f"Failed to scrape {canonical_url}: {exc}")
                continue

            if not data:
                continue

            canonical_title = _match_title(data["title"])
            fingerprint = f"{canonical_title}||{data['company']}"
            if fingerprint in seen_titles:
                continue
            seen_titles.add(fingerprint)

            post_id = extract_linkedin_post_id(data["url"])
            if config.ENABLE_STRICT_HR_POSTS_ONLY and not post_id:
                continue

            description = _build_description(data["raw_text"], data["apply_info"])
            jobs.append(
                Job(
                    title=canonical_title,
                    company=data["company"],
                    location=data["location"],
                    url=data["url"],
                    source="linkedin_hr_post",
                    original_source=f"LinkedIn HR Post � {data['backend']}",
                    description=description,
                    tags=[
                        "linkedin",
                        "hr-post",
                        "hiring-post",
                        f"hiring_score:{data['hiring_score']}",
                        f"confidence:{data['confidence']}",
                        data["location"].split(",")[0].lower().replace(" ", "-"),
                    ],
                    is_remote=False,
                    posted_date=data.get("posted_date"),
                    source_key="linkedin_hr_posts",
                    content_type="hr_post" if post_id else "job_listing",
                    origin_priority=5,
                )
            )
            time.sleep(random.uniform(0.8, 1.8))

        time.sleep(random.uniform(1.2, 2.5))

    log.info(f"LinkedIn HR Posts Scraper: {len(jobs)} HR posts found")
    return jobs
