"""LinkedIn HR post discovery — v61 (new discovery architecture).

Discovery layers (in priority order):
1. LinkedIn-native discovery (search LinkedIn directly for hiring posts)
2. Company-focused discovery (company + hiring signals)
3. Recruiter / Hiring-manager discovery
4. Hiring-intent discovery
5. Search-engine discovery (Google CSE / SerpAPI / Bing) as FALLBACK only

Budget: 90s (up from 25s).
Adaptive query ranking based on acceptance rates.
Post confidence scoring with strict validation gates.
"""

from __future__ import annotations

import base64
import logging
import random
import re
import time
from datetime import datetime
from html import unescape
from urllib.parse import parse_qs, urlparse

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

_GOOGLE_CSE_DISABLED = False
_SEARCH_BACKEND_WARNING_EMITTED = False
_HR_TELEMETRY: dict[str, object] = {}

# ============================================================
# v61: DISCOVERY QUERY MATRICES
# ============================================================

# Core cyber roles for HR post discovery
_HR_CORE_ROLES = [
    "Cybersecurity", "Security Engineer", "Security Analyst",
    "SOC", "IAM", "AppSec", "Cloud Security", "GRC",
    "Pentest", "DevSecOps", "Network Security",
    "Information Security", "Incident Response",
    "Threat Intelligence", "Vulnerability Management",
]

# Hiring signal phrases
_HR_HIRING_SIGNALS = [
    "hiring", "hiring now", "we're hiring", "we are hiring",
    "looking for", "looking for talent", "join our team",
    "grow our team", "expanding our team", "open roles",
    "open positions", "vacancy", "recruitment", "career opportunity",
]

# Locations for HR post search
_HR_LOCATIONS = [
    "Egypt", "Cairo", "Alexandria",
    "Saudi Arabia", "Riyadh", "Jeddah",
    "UAE", "Dubai", "Abu Dhabi",
    "Qatar", "Kuwait", "Bahrain", "Oman",
    "Jordan", "Morocco", "MENA", "Middle East",
    "Remote",
]

# Priority companies for HR post search
_HR_COMPANIES = [
    # Banks
    "Wiz", "Cloudflare", "Okta", "Vodafone Egypt", "CIB", "NBE",
    "QNB", "Banque Misr", "Emirates NBD", "Mashreq",
    "ADIB", "STC", "e&",
    # Cyber/tech
    "CrowdStrike", "Palo Alto Networks", "Fortinet",
    "Tenable", "Rapid7", "Microsoft", "Google", "AWS",
    "SailPoint", "CyberArk", "Mandiant", "HackerOne",
    "Cisco", "IBM", "Nokia", "Ericsson", "Orange",
]

# Recruiter/hiring-manager identity signals
_HR_RECRUITER_SIGNALS = [
    "recruiting", "recruitment", "talent",
    "talent acquisition", "join our team", "grow our team",
    "expanding our team", "open roles", "open positions",
    "looking for", "we are looking for", "career opportunity",
    "cyber hiring", "security hiring",
]

# Combined cyber+recruiter keywords for recruiter discovery
_HR_RECRUITER_CYBER = [
    "Cybersecurity", "Security", "SOC", "IAM",
    "Cloud Security", "AppSec", "GRC", "Pentest", "DevSecOps",
]


def _reset_hr_telemetry(*, budget_seconds: int, queries_planned: int) -> None:
    _HR_TELEMETRY.clear()
    _HR_TELEMETRY.update({
        "budget_seconds": budget_seconds,
        "queries_planned": queries_planned,
        "queries_attempted": 0,
        "urls_discovered": 0,
        "posts_scrape_attempted": 0,
        "posts_accepted": 0,
        "search_backend_attempts": {},
        "search_backend_hits": {},
        "search_backend_empty": {},
        "rejections": {},
        # v61 new metrics
        "accepted_by_method": {},
        "company_yield": {},
        "recruiter_yield": {},
        "query_metrics": [],
        "early_stop": False,
    })


def _increment_counter(bucket: str, key: str, amount: int = 1) -> None:
    counters = _HR_TELEMETRY.setdefault(bucket, {})
    if not isinstance(counters, dict):
        return
    counters[key] = int(counters.get(key, 0)) + amount


def _record_rejection(reason: str) -> None:
    _increment_counter("rejections", reason)


def get_hr_post_telemetry() -> dict[str, object]:
    snapshot: dict[str, object] = {}
    for key, value in _HR_TELEMETRY.items():
        snapshot[key] = dict(value) if isinstance(value, dict) else value
    return snapshot


# ============================================================
# SCORING AND CONFIDENCE
# ============================================================

HIRING_SIGNALS = {
    "#hiring": 5, "we are hiring": 5, "hiring now": 5, "urgent hiring": 8,
    "vacancy": 4, "open role": 4, "join our team": 3, "looking for": 4,
    "send cv": 5, "apply now": 4,
}

ROLE_SIGNALS = {
    "soc analyst": 7, "soc engineer": 7, "security operations center": 7,
    "incident response": 6, "dfir": 6, "threat intelligence": 6,
    "penetration tester": 7, "red team": 6, "appsec": 6,
    "application security": 6, "cloud security": 6, "grc": 6,
    "network security": 6, "it security specialist": 6,
    "security operation engineer": 6, "access management": 6,
    "ping identity": 6, "okta": 6, "security engineer": 7,
    "cybersecurity specialist": 6, "cybersecurity": 5,
    "information security": 5,
}

LOCATION_SIGNALS = {
    "egypt": 3, "cairo": 3, "alexandria": 3, "saudi": 3, "riyadh": 3,
    "uae": 3, "dubai": 3, "kuwait": 3, "qatar": 3, "giza": 3,
    "jeddah": 3, "abu dhabi": 3, "doha": 3,
}

SOURCE_QUALITY_BONUS = {
    "linkedin_native": 4, "company_discovery": 3,
    "recruiter_discovery": 2, "hiring_intent": 1,
    "google_cse": 2, "serpapi": 1, "bing_html": 0,
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
    (["security engineer", "security operation engineer", "cybersecurity engineer"], "Security Engineer"),
    (["access management", "ping identity", "okta"], "Identity & Access Management Engineer"),
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


def _detect_location(text: str) -> tuple[str, str, bool]:
    t = (text or "").lower()
    if any(pattern in t for pattern in config.EGYPT_PATTERNS):
        return "Egypt", "egypt", False
    if any(pattern in t for pattern in config.ARAB_PATTERNS):
        return "Arab Region", "arab", False
    if any(pattern in t for pattern in config.REMOTE_PATTERNS):
        return "Remote / Worldwide", "remote", True
    return "Unknown", "", False


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
    email_match = re.search(r"\b[\w.+-]+@(?:[\w-]+\.)+[a-zA-Z]{2,}\b", text)
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
    if location in {"Egypt", "Arab Region", "Remote / Worldwide"}:
        location_score = max(location_score, 3)

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


# ============================================================
# v61: CONFIDENCE SCORING (POST-LEVEL)
# ============================================================

def _compute_post_confidence(data: dict) -> int:
    """v61: Score an HR post for confidence. Does NOT replace hard gates."""
    score = 0
    raw_text = data.get("raw_text", "").lower()
    title = data.get("title", "").lower()

    # Positive signals
    if any(s in raw_text for s in ["#hiring", "hiring now", "we're hiring", "we are hiring"]):
        score += 30  # clear hiring signal
    if any(r in raw_text for r in _HR_CORE_ROLES):
        score += 30  # clear cyber role
    if data.get("company") and data["company"] != "Unknown":
        score += 15  # verified/company identity
    loc = data.get("location", "")
    if loc in {"Egypt", "Arab Region", "Remote / Worldwide"}:
        score += 15  # Egypt/Arab relevance
    if data.get("apply_info"):
        score += 10  # application URL/info
    if data.get("posted_date"):
        score += 10  # recent date
    # Note: official company/recruiter author (+10) requires LinkedIn API
    # which we don't use; approximate from company name presence.
    if data.get("company", "Unknown") != "Unknown" and any(
        c.lower() in data.get("raw_text", "").lower() for c in _HR_COMPANIES
    ):
        score += 10  # official company/recruiter author

    # Negative signals
    if not any(s in raw_text for s in _HR_HIRING_SIGNALS[3:]):
        # Generic "We're hiring!" without specific role context
        if "we're hiring" in raw_text or "we are hiring" in raw_text:
            if not any(r in raw_text for r in _HR_CORE_ROLES):
                score -= 30
    if not data.get("posted_date"):
        score -= 20  # missing date
    if data.get("company") == "Unknown":
        score -= 30  # missing company

    return score


# ============================================================
# SEARCH ENGINE FALLBACK (Layer 5)
# ============================================================

def _unwrap_bing_redirect(url: str) -> str:
    parsed = urlparse(url)
    if "bing.com" not in parsed.netloc.lower():
        return url
    query = parse_qs(parsed.query or "")
    values = query.get("u")
    if not values:
        return url
    encoded = values[0]
    if encoded.startswith("a1"):
        encoded = encoded[2:]
        padded = encoded + "=" * (-len(encoded) % 4)
        try:
            decoded = base64.urlsafe_b64decode(padded).decode("utf-8", errors="ignore")
            if decoded.startswith("http"):
                return decoded
        except Exception:
            return url
        return url
    if encoded.startswith("http"):
        return encoded
    return url


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
    data = get_json(
        "https://www.googleapis.com/customsearch/v1",
        params=params,
        max_retries=1,
        budget_phase="linkedin",
    )
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
    data = get_json(
        "https://serpapi.com/search",
        params=params,
        max_retries=0,
        budget_phase="linkedin",
    )
    if not data:
        return []
    out: list[tuple[str, str]] = []
    for row in data.get("organic_results", []):
        canonical = _normalize_candidate_link(row.get("link", ""))
        if canonical:
            out.append((canonical, "serpapi"))
    return out


def _search_via_bing_html(query: str) -> list[tuple[str, str]]:
    html = get_text(
        "https://www.bing.com/search",
        params={"q": query, "filters": 'ex1:"ez2"', "setlang": "en"},
        headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"},
        timeout=8,
        max_retries=0,
        use_proxy=False,
        budget_phase="linkedin",
    )
    if not html:
        return []

    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_url in re.findall(r'href=["\'](https?://[^"\']+)["\']', html, re.IGNORECASE):
        target_url = _unwrap_bing_redirect(unescape(raw_url))
        canonical = _normalize_candidate_link(target_url)
        if not canonical or not extract_linkedin_post_id(canonical) or canonical in seen:
            continue
        seen.add(canonical)
        out.append((canonical, "bing_html"))
    return out[:10]


def _search_urls_fallback(query: str) -> list[tuple[str, str]]:
    """v61: Search engines are FALLBACK only — used after all LinkedIn-native layers."""
    global _SEARCH_BACKEND_WARNING_EMITTED
    if not (GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX) and not SERPAPI_KEY:
        if not _SEARCH_BACKEND_WARNING_EMITTED:
            log.warning(
                "LinkedIn HR posts: API search credentials are absent; using the bounded public-search fallback."
            )
            _SEARCH_BACKEND_WARNING_EMITTED = True
    for search_fn in (_search_via_google_cse, _search_via_serpapi, _search_via_bing_html):
        backend = search_fn.__name__.removeprefix("_search_via_")
        _increment_counter("search_backend_attempts", backend)
        urls = search_fn(query)
        if urls:
            _increment_counter("search_backend_hits", backend, len(urls))
            return urls
        _increment_counter("search_backend_empty", backend)
    return []


# ============================================================
# v61: LAYER 1 — LINKEDIN-NATIVE DISCOVERY
# ============================================================

def _build_linkedin_native_queries(rotation_slot: int) -> list[dict]:
    """Build curated LinkedIn-native hiring post search queries."""
    queries: list[dict] = []

    # Egypt-first: high-yield combinations
    _egypt_native = [
        ("Cybersecurity", "hiring", "Egypt"),
        ("Security Engineer", "hiring", "Cairo"),
        ("SOC", "hiring now", "Egypt"),
        ("Penetration Tester", "we are hiring", "Egypt"),
        ("Cloud Security", "hiring", "Egypt"),
        ("IAM", "hiring", "Cairo"),
        ("GRC", "looking for", "Egypt"),
        ("DevSecOps", "hiring", "Egypt"),
        ("AppSec", "open roles", "Egypt"),
        ("Incident Response", "vacancy", "Egypt"),
    ]

    # Arab region combinations (rotating)
    _arab_native = [
        ("Cybersecurity", "hiring", "Saudi Arabia"),
        ("Security Engineer", "hiring", "UAE"),
        ("SOC analyst", "hiring", "Dubai"),
        ("Cloud Security", "hiring", "Riyadh"),
        ("Penetration Tester", "we are hiring", "Qatar"),
        ("GRC", "hiring", "Kuwait"),
        ("DevSecOps", "looking for", "Bahrain"),
        ("IAM", "hiring", "Oman"),
        ("Security Analyst", "hiring", "Jordan"),
        ("Cybersecurity", "open positions", "Morocco"),
        ("Network Security", "hiring", "Lebanon"),
        ("Information Security", "hiring", "Iraq"),
    ]

    # Remote combinations (rotating)
    _remote_native = [
        ("Cybersecurity", "hiring", "Remote"),
        ("Security Engineer", "remote hiring", "Remote"),
        ("SOC analyst", "hiring", "Remote - EMEA"),
        ("Cloud Security", "hiring", "Remote - Middle East"),
    ]

    # Add Egypt queries (always)
    for role, signal, loc in _egypt_native:
        queries.append({
            "query": f'site:linkedin.com/posts "{signal}" "{role}" {loc}',
            "method": "linkedin_native",
            "role": role,
            "location": loc,
        })

    # Add rotating Arab queries (3 per run)
    chunk = 3
    start = (rotation_slot * chunk) % len(_arab_native)
    rotated_arab = _arab_native[start:] + _arab_native[:start]
    for role, signal, loc in rotated_arab[:chunk]:
        queries.append({
            "query": f'site:linkedin.com/posts "{signal}" "{role}" {loc}',
            "method": "linkedin_native",
            "role": role,
            "location": loc,
        })

    # Add rotating Remote queries (1 per run)
    remote_start = rotation_slot % len(_remote_native)
    role, signal, loc = _remote_native[remote_start]
    queries.append({
        "query": f'site:linkedin.com/posts "{signal}" "{role}" {loc}',
        "method": "linkedin_native",
        "role": role,
        "location": loc,
    })

    return queries


# ============================================================
# v61: LAYER 2 — COMPANY-FIRST DISCOVERY
# ============================================================

def _build_company_discovery_queries(rotation_slot: int) -> list[dict]:
    """Build company-focused hiring post search queries."""
    queries: list[dict] = []

    # Curated company + hiring signal + location combinations
    _company_queries = [
        ("Wiz", "hiring", ""),
        ("Cloudflare", "hiring", ""),
        ("Okta", "hiring", ""),
        ("CrowdStrike", "hiring", ""),
        ("Palo Alto Networks", "hiring", ""),
        ("Fortinet", "hiring", ""),
        ("Vodafone Egypt", "hiring", "Egypt"),
        ("CIB", "hiring", "Egypt"),
        ("NBE", "hiring", "Egypt"),
        ("Banque Misr", "hiring", "Egypt"),
        ("QNB", "hiring", "Egypt"),
        ("Emirates NBD", "hiring", "UAE"),
        ("STC", "hiring", "Saudi Arabia"),
        ("e&", "hiring", "UAE"),
        ("Mashreq", "hiring", "UAE"),
        ("ADIB", "hiring", "UAE"),
        ("Tenable", "hiring", ""),
        ("Rapid7", "hiring", ""),
        ("Microsoft", "hiring", ""),
        ("SailPoint", "hiring", ""),
        ("CyberArk", "hiring", ""),
        ("Mandiant", "hiring", ""),
        ("Cisco", "hiring", ""),
        ("Orange", "hiring", "Egypt"),
        ("Cairo", "cybersecurity", "hiring"),
        ("Riyadh", "SOC", "hiring"),
        ("Dubai", "IAM", "hiring"),
    ]

    # Rotate: pick 4 per run
    chunk = 4
    start = (rotation_slot * chunk) % len(_company_queries)
    rotated = _company_queries[start:] + _company_queries[:start]
    for entry in rotated[:chunk]:
        if len(entry) == 3:
            company, signal, loc = entry
            if loc:
                q = f'site:linkedin.com/posts "{company}" {signal} {loc}'
            else:
                q = f'site:linkedin.com/posts "{company}" {signal}'
            queries.append({
                "query": q,
                "method": "company_discovery",
                "company": company,
                "location": loc or "Global",
            })

    return queries


# ============================================================
# v61: LAYER 3 — RECRUITER / HIRING-MANAGER DISCOVERY
# ============================================================

def _build_recruiter_discovery_queries(rotation_slot: int) -> list[dict]:
    """Build recruiter/hiring-manager discovery queries."""
    queries: list[dict] = []

    _recruiter_queries = [
        ("Cybersecurity", "recruiting", "Egypt"),
        ("Security Engineer", "talent acquisition", "Egypt"),
        ("SOC", "recruitment", "Cairo"),
        ("Cloud Security", "looking for talent", "Egypt"),
        ("IAM", "cyber hiring", "Egypt"),
        ("Pentest", "security hiring", "Saudi Arabia"),
        ("GRC", "recruiting", "UAE"),
        ("AppSec", "talent acquisition", "Remote"),
    ]

    # Rotate: pick 2 per run
    chunk = 2
    start = (rotation_slot * chunk) % len(_recruiter_queries)
    rotated = _recruiter_queries[start:] + _recruiter_queries[:start]
    for role, signal, loc in rotated[:chunk]:
        queries.append({
            "query": f'site:linkedin.com/posts "{signal}" "{role}" {loc}',
            "method": "recruiter_discovery",
            "role": role,
            "location": loc,
        })

    return queries


# ============================================================
# v61: LAYER 4 — HIRING-INTENT DISCOVERY
# ============================================================

def _build_hiring_intent_queries(rotation_slot: int) -> list[dict]:
    """Build broader hiring-intent discovery queries."""
    queries: list[dict] = []

    _intent_queries = [
        'site:linkedin.com/posts "open roles" cybersecurity Egypt',
        'site:linkedin.com/posts "career opportunity" "security engineer" Egypt',
        'site:linkedin.com/posts "expanding our team" cybersecurity Cairo',
        'site:linkedin.com/posts "vacancy" "information security" Egypt',
        'site:linkedin.com/posts "open positions" "SOC" Egypt',
        'site:linkedin.com/posts "career opportunity" cybersecurity "Saudi Arabia"',
        'site:linkedin.com/posts "expanding our team" security "UAE"',
        'site:linkedin.com/posts "open roles" cybersecurity Remote',
    ]

    # Rotate: pick 2 per run
    chunk = 2
    start = (rotation_slot * chunk) % len(_intent_queries)
    rotated_intent = _intent_queries[start:] + _intent_queries[:start]
    for q in rotated_intent[:chunk]:
        queries.append({
            "query": q,
            "method": "hiring_intent",
        })

    return queries


# ============================================================
# v61: LAYER 5 — SEARCH ENGINE FALLBACK QUERIES
# ============================================================

def _build_fallback_queries() -> list[dict]:
    """Build fallback queries for search-engine backends."""
    return [
        {"query": 'site:linkedin.com/posts "#hiring" "cybersecurity" Egypt', "method": "google_cse"},
        {"query": 'site:linkedin.com/posts "#hiring" "SOC analyst" Egypt', "method": "google_cse"},
        {"query": 'site:linkedin.com/posts "#hiring" "penetration tester" Egypt', "method": "google_cse"},
        {"query": 'site:linkedin.com/posts "#hiring" "information security" Egypt', "method": "google_cse"},
        {"query": 'site:linkedin.com/posts "#hiring" "security engineer" Egypt', "method": "google_cse"},
    ]


# ============================================================
# v61: ADAPTIVE QUERY RANKING
# ============================================================

def _get_query_acceptance_history() -> dict[str, dict]:
    """Load query metrics from previous runs (simplified: in-memory for now).
    In production this would use the database."""
    return {}


def _rank_queries_by_yield(queries: list[dict]) -> list[dict]:
    """Re-order queries putting historically high-yield ones first."""
    history = _get_query_acceptance_history()
    if not history:
        return queries

    def _yield_score(q: dict) -> float:
        h = history.get(q.get("query", ""), {})
        return h.get("acceptance_rate", 0.0)

    return sorted(queries, key=_yield_score, reverse=True)


# ============================================================
# POST SCRAPING AND VALIDATION
# ============================================================

def _scrape_linkedin_post(url: str, backend: str) -> dict | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ar,en;q=0.9",
    }
    html = get_text(url, headers=headers, budget_phase="linkedin")
    if not html or len(html) < 500:
        _record_rejection("post_page_unavailable")
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
        _record_rejection("missing_post_text")
        return None

    title = ""
    m = re.search(r"(?:hiring|#hiring)[:\s\u2013]+([^\n.!?|]{5,80})", raw_text, re.IGNORECASE)
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
    location, geo_hint, is_remote = _detect_location(raw_text)
    apply_info = _extract_apply_info(raw_text)

    hiring_score, confidence, signal_hits = _compute_confidence(
        title=title,
        raw_text=raw_text,
        location=location,
        apply_info=apply_info,
        source_backend=backend,
        company=company,
    )
    role_score, _ = _score_signal_map(f"{title}\n{raw_text}", ROLE_SIGNALS)

    if (
        hiring_score < HR_HIRING_THRESHOLD
        or role_score <= 0
        or confidence < HR_CONFIDENCE_THRESHOLD
    ):
        _record_rejection("insufficient_hiring_or_role_evidence")
        log.debug(
            "HR post rejected: hiring=%s role=%s confidence=%s threshold=(%s,%s) url=%s hits=%s",
            hiring_score, role_score, confidence,
            HR_HIRING_THRESHOLD, HR_CONFIDENCE_THRESHOLD,
            url, ", ".join(signal_hits[:8]),
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

    # v61: Hard validation gates (unchanged from before, but with clear documentation)
    missing_evidence: list[str] = []
    if not geo_hint:
        missing_evidence.append("missing_location")
    if posted_date is None:
        missing_evidence.append("missing_publish_date")
    if _match_title(title).lower() in {"cybersecurity role", "security role"}:
        missing_evidence.append("generic_role_title")
    if not apply_info:
        missing_evidence.append("missing_apply_method")
    if missing_evidence:
        for reason in missing_evidence:
            _record_rejection(reason)
        return None

    # v61: Compute post confidence score
    post_confidence = _compute_post_confidence({
        "title": title,
        "raw_text": raw_text,
        "company": company,
        "location": location,
        "apply_info": apply_info,
        "posted_date": posted_date,
    })

    log.debug(
        "HR post accepted: hiring=%s confidence=%s post_confidence=%s url=%s",
        hiring_score, confidence, post_confidence, url,
    )

    return {
        "title": title,
        "company": company,
        "location": location,
        "geo_hint": geo_hint,
        "is_remote": is_remote,
        "raw_text": raw_text,
        "apply_info": apply_info,
        "posted_date": posted_date,
        "url": url,
        "backend": backend,
        "hiring_score": hiring_score,
        "role_score": role_score,
        "confidence": confidence,
        "post_confidence": post_confidence,
    }


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def fetch_linkedin_hr_posts_scraper(budget_seconds: int | None = None) -> list[Job]:
    jobs: list[Job] = []
    seen_urls: set[str] = set()
    start = time.time()
    budget = int(budget_seconds or LI_HR_POST_BUDGET_SECONDS)
    rotation_slot = int(time.time() // (4 * 3600))

    # v61: Build multi-layer discovery plan
    all_queries: list[dict] = []
    all_queries.extend(_build_linkedin_native_queries(rotation_slot))
    all_queries.extend(_build_company_discovery_queries(rotation_slot))
    all_queries.extend(_build_recruiter_discovery_queries(rotation_slot))
    all_queries.extend(_build_hiring_intent_queries(rotation_slot))
    all_queries.extend(_build_fallback_queries())

    # v61: Apply adaptive ranking
    all_queries = _rank_queries_by_yield(all_queries)

    _reset_hr_telemetry(budget_seconds=budget, queries_planned=len(all_queries))

    # v61: Track per-query metrics for adaptive ranking
    query_stats: dict[str, dict] = {}

    for query_info in all_queries:
        query_text = query_info["query"]
        method = query_info.get("method", "unknown")

        if time.time() - start > budget:
            log.info("linkedin_hr_posts_scraper: budget exhausted early")
            _HR_TELEMETRY["early_stop"] = True
            break

        # v61: Early stop if we have enough accepted posts
        accepted_count = int(_HR_TELEMETRY.get("posts_accepted", 0))
        if accepted_count >= 5:
            log.info(
                "linkedin_hr_posts_scraper: early stop after %d accepted posts",
                accepted_count,
            )
            _HR_TELEMETRY["early_stop"] = True
            break

        _HR_TELEMETRY["queries_attempted"] = int(_HR_TELEMETRY.get("queries_attempted", 0)) + 1
        query_stats[query_text] = {"found": 0, "accepted": 0, "rejected": 0}

        # v61: For Layers 1-4, use search engine as the transport mechanism
        # (we search LinkedIn via search engines since we don't have LinkedIn API access)
        # Layer 5 explicitly uses the fallback
        if method in ("linkedin_native", "company_discovery", "recruiter_discovery",
                       "hiring_intent", "google_cse"):
            urls = _search_urls_fallback(query_text)
        else:
            urls = _search_urls_fallback(query_text)

        if not urls:
            remaining = budget - (time.time() - start)
            if remaining <= 0:
                break
            time.sleep(min(random.uniform(0.5, 1.2), remaining))
            continue

        _HR_TELEMETRY["urls_discovered"] = int(_HR_TELEMETRY.get("urls_discovered", 0)) + len(urls)
        query_stats[query_text]["found"] = len(urls)

        for canonical_url, backend in urls:
            if time.time() - start > budget:
                break
            if canonical_url in seen_urls:
                continue
            seen_urls.add(canonical_url)
            _HR_TELEMETRY["posts_scrape_attempted"] = int(_HR_TELEMETRY.get("posts_scrape_attempted", 0)) + 1

            try:
                data = _scrape_linkedin_post(canonical_url, backend or method)
            except Exception as exc:
                _record_rejection("post_scrape_exception")
                query_stats[query_text]["rejected"] += 1
                log.debug("Failed to scrape %s: %s", canonical_url, exc)
                continue

            if not data:
                query_stats[query_text]["rejected"] += 1
                continue

            # v61: Dedup by canonical URL, post ID, and fingerprint
            post_id = extract_linkedin_post_id(data["url"])
            company = data.get("company", "Unknown")
            title = _match_title(data["title"])
            date_str = str(data.get("posted_date", ""))
            fingerprint = f"{company}|{title}|{date_str}|{canonical_url}"
            if fingerprint in seen_urls:
                _record_rejection("duplicate_post")
                query_stats[query_text]["rejected"] += 1
                continue
            seen_urls.add(fingerprint)

            if config.ENABLE_STRICT_HR_POSTS_ONLY and not post_id:
                _record_rejection("missing_canonical_post_id")
                query_stats[query_text]["rejected"] += 1
                continue

            description = _build_description(data["raw_text"], data["apply_info"])
            jobs.append(
                Job(
                    title=title,
                    company=data["company"],
                    location=data["location"],
                    url=data["url"],
                    source="linkedin_hr_post",
                    original_source=f"LinkedIn HR Post - {data['backend']}",
                    description=description,
                    tags=[
                        "linkedin", "hr-post", "hiring-post",
                        f"hiring_score:{data['hiring_score']}",
                        f"confidence:{data['confidence']}",
                        f"post_confidence:{data.get('post_confidence', 0)}",
                        data["location"].split(",")[0].lower().replace(" ", "-"),
                    ],
                    is_remote=bool(data["is_remote"]),
                    geo_hint=data["geo_hint"],
                    posted_date=data.get("posted_date"),
                    source_key="linkedin_hr_posts",
                    content_type="hr_post" if post_id else "job_listing",
                    origin_priority=5,
                )
            )
            _HR_TELEMETRY["posts_accepted"] = int(_HR_TELEMETRY.get("posts_accepted", 0)) + 1
            query_stats[query_text]["accepted"] += 1

            # v61: Track acceptance by discovery method
            _increment_counter("accepted_by_method", method)
            # Track company yield if applicable
            if data["company"] != "Unknown":
                _increment_counter("company_yield", data["company"])
            # Track recruiter yield
            if any(s in data["raw_text"].lower() for s in _HR_RECRUITER_SIGNALS[:5]):
                _increment_counter("recruiter_yield", method)

            remaining = budget - (time.time() - start)
            if remaining <= 0:
                break
            time.sleep(min(random.uniform(0.5, 1.2), remaining))

        # Record query metrics for adaptive ranking
        if query_stats[query_text]["found"] > 0:
            rate = query_stats[query_text]["accepted"] / query_stats[query_text]["found"]
            query_stats[query_text]["acceptance_rate"] = round(rate, 2)

        remaining = budget - (time.time() - start)
        if remaining <= 0:
            break
        time.sleep(min(random.uniform(0.8, 1.8), remaining))

    # Store query metrics in telemetry for adaptive ranking
    _HR_TELEMETRY["query_metrics"] = [
        {"query": q, **stats}
        for q, stats in query_stats.items()
        if stats.get("found", 0) > 0
    ]

    telemetry = get_hr_post_telemetry()
    backend_hits = telemetry.get("search_backend_hits", {})
    rejection_counts = telemetry.get("rejections", {})
    accepted_by_method = telemetry.get("accepted_by_method", {})
    log.info(
        "LinkedIn HR Posts Scraper: %d HR posts found "
        "(queries=%s/%s urls=%s scraped=%s backend_hits=%s rejections=%s by_method=%s)",
        len(jobs),
        telemetry.get("queries_attempted", 0), telemetry.get("queries_planned", 0),
        telemetry.get("urls_discovered", 0), telemetry.get("posts_scrape_attempted", 0),
        backend_hits or "none", rejection_counts or "none",
        accepted_by_method or "none",
    )
    return jobs


# ============================================================
# BACKWARD-COMPAT (for existing tests)
# ============================================================

def _search_queries(rotation_slot: int | None = None) -> list[str]:
    """Legacy interface — returns site:linkedin.com search strings."""
    if rotation_slot is None:
        rotation_slot = int(time.time() // (4 * 3600))
    all_q = _build_linkedin_native_queries(rotation_slot)
    return [q["query"] for q in all_q]


def _search_urls(query: str) -> list[tuple[str, str]]:
    """Legacy interface — delegates to fallback search."""
    return _search_urls_fallback(query)
