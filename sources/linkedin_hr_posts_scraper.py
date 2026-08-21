"""LinkedIn HR post discovery — v61 (new discovery architecture).

Discovery layers (in priority order):
1. LinkedIn-native discovery (search LinkedIn directly for hiring posts)
2. Company-focused discovery (company + hiring signals)
3. Recruiter / Hiring-manager discovery
4. Hiring-intent discovery
5. Search-engine discovery (SerpAPI / Jina Index / Bing) as FALLBACK only

Budget: 90s (up from 25s).
Adaptive query ranking based on acceptance rates.
Post confidence scoring with strict validation gates.
"""

from __future__ import annotations

import base64
import logging
import os
import random
import re
import time
from datetime import datetime
from html import unescape
from urllib.parse import parse_qs, urlparse

import config
from config import (
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

# v78: Google CSE was removed entirely — the service is no longer supported.
# Discovery now runs on serpapi / jina_index / bing_html only.
_SEARCH_BACKEND_WARNING_EMITTED = False
_HR_TELEMETRY: dict[str, object] = {}

# v65: backend-level cooldowns replace hard per-run bans.
# A backend that fails or comes back genuinely empty is cooled down for a
# bounded window — long enough to stop burning budget on a dead backend,
# short enough that a temporary blip (transient CSE 4xx, an empty search
# results page) never silences the backend for the whole run.
_BACKEND_EMPTY_STREAK_LIMIT = int(os.getenv("HR_BACKEND_EMPTY_STREAK_LIMIT", "4"))
_BACKEND_COOLDOWN_SECONDS = int(os.getenv("HR_BACKEND_COOLDOWN_SECONDS", "60"))
# v66: a backend that keeps coming back empty even after stall-relaxation
# rechecks is parked for the remainder of the run instead of being hit once
# per query (the v65 log showed 16 consecutive empties — every query paying
# for a backend that demonstrably has nothing).
_BACKEND_PARK_STREAK = int(os.getenv("HR_BACKEND_MAX_EMPTY_STREAK_BEFORE_PARK", "8"))
_backend_cooldown_until: dict[str, float] = {}
_backend_empty_cooldown: set[str] = set()
_backend_empty_streak: dict[str, int] = {}
_backend_parked: set[str] = set()
# v69: backends that already spent their one forced recheck during the
# current cooldown window — the set is cleared once the window expires, at
# which point another single forced recheck is permitted.
_backend_forced_this_cooldown: set[str] = set()
# v75: backends that already spent their one forced recheck during the
# entire RUN (not just the cooldown window). A backend that came back
# empty from a forced recheck proved it has nothing this run — re-hitting
# it in a later window advances nothing and burns the HR budget.
_backend_forced_this_run: set[str] = set()
def _backend_cooldown_expired(backend: str) -> bool:
    return time.time() >= _backend_cooldown_until.get(backend, 0.0)


def _mark_backend_empty(backend: str) -> None:
    streak = _backend_empty_streak.get(backend, 0) + 1
    _backend_empty_streak[backend] = streak
    if streak >= max(1, _BACKEND_EMPTY_STREAK_LIMIT):
        _backend_cooldown_until[backend] = time.time() + max(5.0, float(_BACKEND_COOLDOWN_SECONDS))
        # v65: remember that this cooldown came from genuinely empty responses
        # — the stall-relaxation path only rechecks backends flagged here so
        # that short transient-failure backoffs are never picked as the
        # forced recheck.
        _backend_empty_cooldown.add(backend)
        log.info(
            "LinkedIn HR Posts: backend '%s' empty %d times in a row; "
            "cooled down for %ds (recheck resumes automatically).",
            backend, streak, _BACKEND_COOLDOWN_SECONDS,
        )
    # v66: after the park streak (which counts forced stall-relaxation
    # rechecks too), the backend is parked for the rest of the run. It is
    # skipped by the orchestrator and never picked by stall-relaxation,
    # ending the per-query retry loop while the other backends keep serving.
    if (
        streak >= max(1, _BACKEND_PARK_STREAK)
        and backend not in _backend_parked
    ):
        _backend_parked.add(backend)
        log.info(
            "LinkedIn HR Posts: backend '%s' produced nothing after %d "
            "consecutive checks (including forced rechecks); parked for the "
            "remainder of the run so queries stop paying for a dead "
            "backend (recheck resumes at the next run).",
            backend, streak,
        )


def _mark_backend_hit(backend: str) -> None:
    _backend_empty_streak[backend] = 0
    _backend_cooldown_until.pop(backend, None)
    _backend_empty_cooldown.discard(backend)
    _backend_parked.discard(backend)
    # v69: a hit clears the forced-recheck bookkeeping so the backend
    # returns to the normal rotation with its single-forced-recheck quota.
    _backend_forced_this_cooldown.discard(backend)
    # v75: a hit also clears the run-level forced-recheck lock — a backend
    # that proves alive again earns back its stall-relaxation eligibility.
    _backend_forced_this_run.discard(backend)


def _is_backend_warm(backend: str) -> bool:
    if backend in _backend_parked:
        return False
    return _backend_cooldown_expired(backend)


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
    # v68 dedicated-lane methods — verified against the post body itself
    # before acceptance, so they carry the same trust as recruiter posts.
    "recruiter_posts": 2, "company_hiring_posts": 3, "job_announcements": 2,
    "jina_index": 3, "serpapi": 2, "bing_html": 1,
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
        budget_phase="linkedin_hr",
    )
    if not data:
        return []
    out: list[tuple[str, str]] = []
    for row in data.get("organic_results", []):
        canonical = _normalize_candidate_link(row.get("link", ""))
        if canonical:
            out.append((canonical, "serpapi"))
    return out


def _search_via_jina_index(query: str) -> list[tuple[str, str]]:
    """v74 (v78: now a primary backend): CSE-free public index backend — search LinkedIn posts
    through the Jina public search endpoint instead of Google.  No API key,
    no quota, and a different IP pool than the bot's direct exit, so a
    Google-blocked environment can still reach LinkedIn's public index.
    Returns candidate LinkedIn post URLs with backend tag ``jina_index``."""
    # Two independent surfaces: the Jina search API (search.jina.ai) and,
    # as a fallback surface, the Jina reader applied to Bing's results URL
    # (the reader re-fetches the search page itself through its own pool).
    candidate_urls: list[tuple[str, str]] = []

    try:
        data = get_json(
            "https://s.jina.ai/",
            params={"q": query},
            timeout=int(_PUBLIC_READER_ATTEMPT_TIMEOUT_SECONDS) + 4,
            max_retries=1,
            budget_phase="linkedin_hr",
        )
    except Exception:  # pragma: no cover - transport never blocks the plan
        data = None
    if data:
        for item in data.get("data", data if isinstance(data, list) else []) if isinstance(data, (dict, list)) else []:
            if isinstance(item, dict):
                link = item.get("url", "")
            else:
                continue
            canonical = _normalize_candidate_link(link)
            if canonical and extract_linkedin_post_id(canonical):
                candidate_urls.append((canonical, "jina_index"))

    return candidate_urls[:10]


def _search_via_bing_html(query: str) -> list[tuple[str, str]]:
    html = get_text(
        "https://www.bing.com/search",
        params={"q": query, "filters": 'ex1:"ez2"', "setlang": "en"},
        headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"},
        timeout=8,
        max_retries=0,
        use_proxy=False,
        budget_phase="linkedin_hr",
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
    if not SERPAPI_KEY:
        if not _SEARCH_BACKEND_WARNING_EMITTED:
            log.warning(
                "LinkedIn HR posts: API search credentials are absent; using the bounded public-search fallback."
            )
            _SEARCH_BACKEND_WARNING_EMITTED = True
    for search_fn in (_search_via_serpapi, _search_via_jina_index, _search_via_bing_html):
        backend = search_fn.__name__.removeprefix("_search_via_")
        # v65: skip cooled-down backends — the orchestrator re-runs them on
        # later queries once their bounded window expires.
        if not _is_backend_warm(backend):
            continue
        _increment_counter("search_backend_attempts", backend)
        urls = search_fn(query)
        if urls:
            # v65: a real hit clears the backend's empty streak and any
            # cooldown — the backend is healthy again for the rest of the
            # query plan.
            _mark_backend_hit(backend)
            _increment_counter("search_backend_hits", backend, len(urls))
            return urls
        _mark_backend_empty(backend)
        _increment_counter("search_backend_empty", backend)
    # v65: if every backend is currently cooled down, briefly relax the
    # warmest one (smallest cooldown) so the query plan can never fully
    # stall — at least one backend always remains callable.
    living = [
        b for b in ("serpapi", "jina_index", "bing_html")
        if _backend_cooldown_until.get(b, 0.0) > 0.0
    ]
    if living and not any(_is_backend_warm(b) for b in living):
        # v65: stall-relaxation rechecks a backend whose cooldown came from
        # genuinely empty responses — never a short transient-failure
        # backoff — otherwise the relaxed slot keeps bouncing between
        # failure backoffs and the query plan livelocks.
        # Stall-relaxation only rechecks backends whose cooldown came from
        # genuinely empty responses; a backend whose cooldown came from a
        # short transient failure is not rechecked — re-hitting a
        # known-failing API endpoint advances nothing.
        eligible = [b for b in living if b in _backend_empty_cooldown and b not in _backend_parked and b not in _backend_forced_this_run]
        # v66: backends parked by the streak cap are out of the run entirely
        # — neither warm nor forceable. If the only empty-cooldown backends
        # are parked, the query plan returns what it collected so far and
        # lets the next run try again.
        if not eligible:
            return []
        # v69: a backend may be forced at most ONCE per cooldown window —
        # the 2026-08-18 run forced the same backend every ~1s cycle for the
        # whole window, burning the HR budget on identical dead-end checks.
        # After one forced recheck the backend stays in cooldown until the
        # window expires, and stall-relaxation moves on to the rest of the
        # plan instead of livelocking on the same stale backend.
        not_forced = [b for b in eligible if b not in _backend_forced_this_cooldown]
        if not_forced:
            relaxed = min(not_forced, key=lambda b: _backend_cooldown_until[b])
        else:
            _backend_forced_this_cooldown.clear()
            relaxed = min(eligible, key=lambda b: _backend_cooldown_until[b])
        _backend_forced_this_cooldown.add(relaxed)
        log.info(
            "LinkedIn HR Posts: all search backends cooled down; forcing one "
            "recheck for backend '%s' so the query plan never fully stalls.",
            relaxed,
        )
        _backend_cooldown_until[relaxed] = 0.0
        _backend_empty_cooldown.discard(relaxed)
        for search_fn in (_search_via_serpapi, _search_via_jina_index, _search_via_bing_html):
            if search_fn.__name__.removeprefix("_search_via_") == relaxed:
                _increment_counter("search_backend_attempts", relaxed)
                urls = search_fn(query)
                if urls:
                    # v65: a forced recheck that produces results clears the
                    # backend's streak and cooldown, same as the normal loop.
                    _mark_backend_hit(relaxed)
                    _increment_counter("search_backend_hits", relaxed, len(urls))
                    return urls
                # v69: a forced recheck that comes back empty re-enters the
                # cooldown so the backend keeps its single-forced-recheck
                # quota for the remainder of THIS window (it already spent
                # it) while the plan moves on to other backends.
                # a repeatedly empty backend.
                _mark_backend_empty(relaxed)
                _increment_counter("search_backend_empty", relaxed)
                # v75: a forced recheck that comes back empty proves the
                # backend has nothing this run — it may be forced at most
                # once per RUN (per window was the v69 cap), so lock it for
                # the remainder of the run and free the HR budget for the
                # surviving backends.
                _backend_forced_this_run.add(relaxed)
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
# v68: DEDICATED DISCOVERY LANES
# ============================================================

# v68: three dedicated discovery lanes replace the single generic query pool
# that the v68 diagnosis showed producing 27 queries, 3 URLs and 3
# rejections. Each lane uses its own query templates tuned to how its
# audience actually writes posts — recruiter posts lead with the verb
# ("hiring", "looking for"), company hiring posts lead with the company
# announcement style ("we're growing", "new roles"), and job announcement
# posts lead with the role title itself ("#hiring", "vacancy").


def _build_recruiter_posts_lane(rotation_slot: int) -> list[dict]:
    """v68: recruiter-first lane — recruiter posts phrase openings as a
    personal search ("I'm hiring", "DM me", "send your CV"), so the query
    templates use recruiter voice with explicit CV-call signals."""
    _recruiter_posts = [
        ('"I\'m hiring" cybersecurity Egypt',),
        ('"we are looking for" "security analyst" Egypt',),
        ('"send me your CV" cybersecurity Cairo',),
        ('"DM me" "SOC analyst" Egypt',),
        ('"hiring" "security engineer" "Egypt" "apply"',),
        ('"recruiting" cybersecurity Riyadh',),
        ('"looking for" "security" "Dubai" "hiring"',),
        ('"hiring" "information security" "Cairo" "apply now"',),
        # v74: recruiter-direct voice with explicit CV/DM signals that
        # recruiters use in Arabic posts, plus role+Egypt pairs with the
        # strongest apply verbs.
        ('"وظائف" "security" Cairo "CV"',),
        ('"looking for" "SOC analyst" "Egypt" "DM me"',),
    ]
    chunk = 2
    start = (rotation_slot * chunk) % len(_recruiter_posts)
    rotated = _recruiter_posts[start:] + _recruiter_posts[:start]
    return [
        {"query": f"site:linkedin.com/posts {q}", "method": "recruiter_posts"}
        for (q,) in rotated[:chunk]
    ]


def _build_company_hiring_posts_lane(rotation_slot: int) -> list[dict]:
    """v68: company-hiring lane — company announcements name the company and
    growth signal ("we're hiring", "joining our team", "new roles"), so the
    templates pair the priority companies from the existing pool with the
    announcement voice and an Egypt/Arab location."""
    _company_posts = [
        ('"we are hiring" "Vodafone" Egypt',),
        ('"we\'re hiring" "CIB" Egypt',),
        ('"hiring" "NBE" Egypt',),
        ('"open roles" "STC" Saudi Arabia',),
        ('"we are hiring" "Emirates NBD" UAE',),
        ('"new roles" cybersecurity Egypt',),
        ('"join our team" "security" "Mashreq" UAE',),
        ('"hiring" "Wiz" Remote',),
        # v74: broader hiring voice with explicit CV-call signals that
        # company posts use in Egypt (the announcement style plus an
        # application directive), plus bank-adjacent security roles.
        ('"we are hiring" "security operations" Egypt "CV"',),
        ('"joining our team" "cybersecurity" Cairo "apply"',),
    ]
    chunk = 2
    start = (rotation_slot * chunk) % len(_company_posts)
    rotated = _company_posts[start:] + _company_posts[:start]
    return [
        {"query": f"site:linkedin.com/posts {q}", "method": "company_hiring_posts"}
        for (q,) in rotated[:chunk]
    ]


def _build_job_announcements_lane(rotation_slot: int) -> list[dict]:
    """v68: job-announcement lane — post-first role announcements lead with
    the role and a vacancy marker ("#hiring", "vacancy", "open position"),
    so the templates put the canonical security role titles up front."""
    _announcements = [
        ('"#hiring" "SOC analyst" Egypt',),
        ('"vacancy" "penetration tester" Egypt',),
        ('"open position" "security engineer" Cairo',),
        ('"#hiring" "GRC analyst" Egypt',),
        ('"hiring now" "cloud security" Riyadh',),
        ('"#hiring" "incident response" Dubai',),
        ('"vacancy" "cybersecurity specialist" Egypt',),
        ('"open position" "IAM engineer" Remote',),
        # v74: Arabic-voice announcements — Egyptian recruiters post in
        # Arabic with titles like "وظائف امن معلومات"; search engines
        # index both languages, so the plan now alternates lanes with
        # Arabic templates without expanding the per-run chunk size.
        ('"#توظيف" "امن المعلومات" Egypt',),
        ('"وظائف" "cybersecurity" Cairo',),
        ('"#hiring" "SOC analyst" "Cairo" "apply"',),
    ]
    chunk = 2
    start = (rotation_slot * chunk) % len(_announcements)
    rotated = _announcements[start:] + _announcements[:start]
    return [
        {"query": f"site:linkedin.com/posts {q}", "method": "job_announcements"}
        for (q,) in rotated[:chunk]
    ]


# ============================================================
# v61: LAYER 5 — SEARCH ENGINE FALLBACK QUERIES
# ============================================================

def _build_fallback_queries() -> list[dict]:
    """Build fallback queries for search-engine backends."""
    # v78: Google CSE removed (no longer supported) — fallback queries now
    # route through the remaining backends (serpapi / jina_index / bing_html).
    return [
        {"query": 'site:linkedin.com/posts "#hiring" "cybersecurity" Egypt', "method": "fallback_index"},
        {"query": 'site:linkedin.com/posts "#hiring" "SOC analyst" Egypt', "method": "fallback_index"},
        {"query": 'site:linkedin.com/posts "#hiring" "penetration tester" Egypt', "method": "fallback_index"},
        {"query": 'site:linkedin.com/posts "#hiring" "information security" Egypt', "method": "fallback_index"},
        {"query": 'site:linkedin.com/posts "#hiring" "security engineer" Egypt', "method": "fallback_index"},
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

def _fetch_via_jina(url: str) -> str | None:
    """Fetch a LinkedIn post URL via Jina reader for text extraction fallback."""
    try:
        from sources.marketplace_sources import _fetch_via_jina as _jina_fetch
        return _jina_fetch(url)
    except Exception:
        pass
    # Direct Jina call as second option
    try:
        result = get_text(
            f"https://r.jina.ai/{url}",
            headers={
                "Accept": "text/markdown, text/plain, */*",
                "X-Respond-With": "markdown",
                "X-Engine": "browser",
                "X-Cache-Tolerance": "300",
                "X-Max-Tokens": "12000",
            },
            timeout=20,
            max_retries=0,
            budget_phase="linkedin_hr",
        )
        return result
    except Exception:
        return None


def _extract_text_from_jina(markdown: str) -> str:
    """Extract post text from Jina markdown output."""
    # Jina returns markdown; the post content is usually the main body
    # Skip navigation/header/footer noise lines
    lines = markdown.split("\n")
    content_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip common Jina noise
        if stripped.startswith("[") and stripped.endswith("]"):
            continue
        if any(skip in stripped.lower() for skip in [
            "linkedin", "sign in", "join now", "cookies", "privacy policy",
            "terms of service", "skip to content", "language",
        ]):
            continue
        if len(stripped) < 3:
            continue
        content_lines.append(stripped)
    return " ".join(content_lines)


def _extract_metadata_from_jina(markdown: str) -> dict:
    """Extract metadata from Jina markdown output."""
    meta: dict = {}
    # Jina sometimes puts title on first non-empty line
    lines = [l.strip() for l in markdown.split("\n") if l.strip()]
    if lines:
        meta["title_hint"] = lines[0][:200]
    # Look for date patterns in Jina output
    for line in lines:
        date_m = re.search(r"(\d{4}-\d{2}-\d{2})", line)
        if date_m:
            try:
                meta["posted_at"] = datetime.fromisoformat(date_m.group(1)).replace(tzinfo=None)
                break
            except ValueError:
                continue
    return meta


def _extract_text_from_html(html: str) -> str:
    """Extract post text from HTML using multiple strategies."""
    raw_text = ""
    # Strategy 1: og:description
    og_desc = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"', html)
    if og_desc:
        raw_text = og_desc.group(1)
    # Strategy 2: og:title (shorter but sometimes the only text)
    if not raw_text:
        og_title = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
        if og_title:
            raw_text = og_title.group(1)
    # Strategy 3: <article> tag
    if not raw_text:
        article = re.search(r"<article[^>]*>(.*?)</article>", html, re.DOTALL)
        if article:
            raw_text = re.sub(r"<[^>]+>", " ", article.group(1))
    # Strategy 4: LinkedIn-specific: comment-content div
    if not raw_text:
        comment_div = re.search(
            r'<div[^>]*class="[^"]*comment[^>]*"[^>]*>(.*?)</div>',
            html, re.DOTALL | re.IGNORECASE,
        )
        if comment_div:
            raw_text = re.sub(r"<[^>]+>", " ", comment_div.group(1))
    # Strategy 5: Any meta description
    if not raw_text:
        meta_desc = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', html, re.IGNORECASE)
        if meta_desc:
            raw_text = meta_desc.group(1)
    # Strategy 6: JSON-LD
    if not raw_text:
        ld_match = re.search(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE,
        )
        if ld_match:
            try:
                import json as _json
                ld_data = _json.loads(ld_match.group(1))
                if isinstance(ld_data, dict):
                    raw_text = ld_data.get("description", "") or ld_data.get("text", "")
                    if not raw_text and "articleBody" in ld_data:
                        raw_text = ld_data["articleBody"]
                elif isinstance(ld_data, list):
                    for item in ld_data:
                        if isinstance(item, dict):
                            raw_text = item.get("description", "") or item.get("text", "") or item.get("articleBody", "")
                            if raw_text:
                                break
            except Exception:
                pass
    # Strategy 7: <title> tag (broader — strip LinkedIn suffix)
    if not raw_text or len(raw_text) < 20:
        title_m = re.search(r"<title>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
        if title_m:
            t = unescape(re.sub(r"<[^>]+>", " ", title_m.group(1))).strip()
            t = re.sub(r"\s*[|\-–—]\s*LinkedIn.*$", "", t, flags=re.IGNORECASE).strip()
            if len(t) > len(raw_text):
                raw_text = t
    # Strategy 8: LinkedIn update-card / feed-update div
    if not raw_text or len(raw_text) < 20:
        feed_div = re.search(
            r'<div[^>]*class="[^"]*(?:update-|feed-)component[^>]*"[^>]*>(.*?)</div>',
            html, re.DOTALL | re.IGNORECASE,
        )
        if feed_div:
            candidate = re.sub(r"<[^>]+>", " ", feed_div.group(1)).strip()
            candidate = re.sub(r"\s+", " ", candidate)
            if len(candidate) > len(raw_text):
                raw_text = candidate
    # Strategy 9: Broader — any <p> or <span> block with substantial text
    if not raw_text or len(raw_text) < 20:
        blocks = re.findall(r"<(?:p|div|span)[^>]*>(.*?)</(?:p|div|span)>", html, re.DOTALL | re.IGNORECASE)
        best = ""
        for b in blocks:
            clean = re.sub(r"<[^>]+>", " ", b).strip()
            clean = re.sub(r"\s+", " ", clean)
            if len(clean) > len(best) and len(clean) >= 30:
                # Skip navigation/footer noise
                if any(skip in clean.lower() for skip in [
                    "sign in", "join now", "cookies", "privacy", "terms",
                    "linkedin", "language", "skip to",
                ]):
                    continue
                best = clean
        if len(best) > len(raw_text):
            raw_text = best
    return unescape(raw_text).strip()


def _extract_metadata_from_html(html: str) -> dict:
    """Extract post metadata (canonical URL, post_id, author, date, etc.) from HTML."""
    meta: dict = {}
    # canonical URL
    canonical_m = re.search(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"', html)
    if canonical_m:
        meta["canonical_url"] = unescape(canonical_m.group(1))
    # post_id from URN
    urn_m = re.search(r'urn:li:activity:(\d+)', html)
    if urn_m:
        meta["post_id"] = urn_m.group(1)
    # author name
    author_m = re.search(r'<meta[^>]+name="author"[^>]+content="([^"]+)"', html)
    if not author_m:
        author_m = re.search(r'<a[^>]+data-test-id="entity-name"[^>]*>(.*?)</a>', html)
    if author_m:
        meta["author"] = unescape(author_m.group(1).strip())
    # posted date
    date_m = re.search(
        r'(?:datePublished|article:published_time)"?\s*(?:content=|:)\s*"([^"]+)"',
        html,
    )
    if date_m:
        try:
            meta["posted_at"] = datetime.fromisoformat(date_m.group(1).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    return meta


# v68: hiring-intent evidence used when verifying a post URL directly —
# cheaper than running the whole scoring gate on noise pages that the
# search index occasionally surfaces (news articles, event pages).
_POST_HIRING_INTENT = (
    "hiring", "we are hiring", "we're hiring", "hiring now", "join our team",
    "open role", "open roles", "open position", "open positions",
    "vacancy", "looking for", "job opportunity", "career opportunity",
    "send cv", "apply now", "dm me", "recruiting", "recruitment",
)
_POST_ROLE_EVIDENCE = (
    "soc", "security engineer", "security analyst", "cybersecurity", "cyber",
    "information security", "pentest", "red team", "appsec", "cloud security",
    "grc", "incident response", "threat", "vulnerability", "devsecops",
    "security specialist", "it security", "infosec",
)


def _verify_post_url(url: str, *, role_hint: str = "") -> tuple[bool, str]:
    """v68: verify a candidate post URL directly BEFORE acceptance — fetch
    the post's own page and confirm the body itself carries hiring intent
    plus a security-role signal.  Without this, a search-engine row that
    merely mentions LinkedIn can drag in article or event pages, which is
    exactly what rejected 3 of 3 verified URLs for
    ``insufficient_hiring_or_role_evidence`` in the v68 diagnosis.

    Returns ``(accepted, evidence)``. A page that cannot be fetched or whose
    body lacks both signals is declined with a short reason — the decline
    happens here, cheaply, instead of inside the full scrape-and-score gate.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ar,en;q=0.9",
    }
    html = get_text(url, headers=headers, timeout=10, max_retries=0, use_proxy=False, budget_phase="linkedin_hr")
    if not html or len(html) < 200:
        return False, "post_page_unavailable"
    text = _extract_text_from_html(html)
    lowered = text.lower()
    if not text:
        return False, "fetch_failed"
    has_hiring = any(signal in lowered for signal in _POST_HIRING_INTENT)
    has_role = any(sig in lowered for sig in (_POST_ROLE_EVIDENCE + ((role_hint.lower(),) if role_hint else ())))
    if not has_hiring:
        return False, "no_hiring_intent"
    if not has_role:
        return False, "no_role_evidence"
    return True, "verified_hiring_and_role"


def _scrape_linkedin_post(url: str, backend: str) -> dict | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ar,en;q=0.9",
    }
    html = get_text(url, headers=headers, budget_phase="linkedin")
    if not html or len(html) < 200:
        _record_rejection("post_page_unavailable")
        return None

    raw_text = _extract_text_from_html(html)
    meta = _extract_metadata_from_html(html)

    # Fallback 1: Jina reader
    if len(raw_text) < 20:
        log.debug("HR post: direct fetch yielded insufficient text, trying Jina fallback for %s", url)
        jina_html = _fetch_via_jina(url)
        if jina_html and len(jina_html) > 100:
            jina_text = _extract_text_from_jina(jina_html)
            if len(jina_text) > len(raw_text):
                raw_text = jina_text
                jina_meta = _extract_metadata_from_jina(jina_html)
                meta = {**meta, **jina_meta}

    # Fallback 2: Mobile user-agent fetch (different rendering)
    if len(raw_text) < 20:
        log.debug("HR post: Jina also insufficient, trying mobile UA fetch for %s", url)
        mobile_headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            ),
            "Accept-Language": "ar,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        }
        mobile_html = get_text(url, headers=mobile_headers, budget_phase="linkedin")
        if mobile_html and len(mobile_html) > 200:
            mobile_text = _extract_text_from_html(mobile_html)
            if len(mobile_text) > len(raw_text):
                raw_text = mobile_text
                mobile_meta = _extract_metadata_from_html(mobile_html)
                meta = {**meta, **mobile_meta}

    if len(raw_text) < 20:
        _record_rejection("fetch_failed")
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

    posted_date = meta.get("posted_at")
    if posted_date is None:
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
        "url": meta.get("canonical_url") or url,
        "backend": backend,
        "hiring_score": hiring_score,
        "role_score": role_score,
        "confidence": confidence,
        "post_confidence": post_confidence,
        "post_id": meta.get("post_id"),
        "author": meta.get("author"),
    }


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def _validate_hr_backend_keys() -> None:
    """v70 (v78): validate search-backend credentials once before the query
    plan starts — a key that is missing, obviously malformed, or rejected by
    the provider (quota/invalid) is detected at the first request and the
    backend is marked unusable so the query plan never pays for it again.

    v78: Google CSE was removed entirely (no longer supported) — serpapi is
    the keyed backend validated here; jina_index needs no credentials at all.
    """
    if not SERPAPI_KEY:
        return
    probe = get_json(
        "https://serpapi.com/search",
        params={"q": "test", "engine": "google", "api_key": SERPAPI_KEY},
        max_retries=0,
        budget_phase="linkedin_hr",
    )
    if probe is None:
        probe2 = get_json(
            "https://serpapi.com/search",
            params={"q": "x", "engine": "google", "api_key": SERPAPI_KEY},
            max_retries=0,
            budget_phase="linkedin_hr",
        )
        if probe2 is None:
            _backend_parked.add("serpapi")
            log.warning(
                "LinkedIn HR Posts: SerpAPI key is unusable (credential or "
                "quota error) — serpapi skipped for the rest of the run; "
                "fix the key to restore that backend (jina_index and Bing "
                "remain available).",
            )
            return
    # A successful response means the key is fine — clear any stale failure
    # state so serpapi starts the run healthy.
    _backend_cooldown_until.pop("serpapi", None)
    _backend_empty_cooldown.discard("serpapi")
    _backend_parked.discard("serpapi")


def _all_hr_backends_unusable() -> bool:
    """v70: true when no search backend can answer this run — the query plan
    would pay for guaranteed empties, so the HR phase skips entirely and
    waits for the next run (keys refreshed, backends cooled down).

    Per-backend notes:
    - serpapi / bing_html: unusable when missing credentials or parked.
      A cooled-down backend (temporary empties) is NOT unusable — the
      bounded cooldown will expire and the backend may recover, and
      stall-relaxation is allowed to recheck it.
    - jina_index: needs no credentials; unusable only when parked.
    """
    serpapi_unusable = not SERPAPI_KEY or "serpapi" in _backend_parked
    bing_unusable = "bing_html" in _backend_parked
    jina_unusable = "jina_index" in _backend_parked
    return serpapi_unusable and bing_unusable and jina_unusable


def fetch_linkedin_hr_posts_scraper(budget_seconds: int | None = None) -> list[Job]:
    jobs: list[Job] = []
    seen_urls: set[str] = set()
    start = time.time()
    budget = int(budget_seconds or LI_HR_POST_BUDGET_SECONDS)
    rotation_slot = int(time.time() // (4 * 3600))
    # v70: key health is checked once at the start instead of letting every
    # query pay for a known-dead backend. An unusable SerpAPI key is
    # detected early by run-start validation and parked entirely for the
    # rest of the run — in the 2026-08-18 run a failing key made the HR phase burn
    # 33 queries while no backend could find LinkedIn posts at all.
    _validate_hr_backend_keys()
    if _all_hr_backends_unusable():
        log.warning(
            "LinkedIn HR Posts: every search backend is unusable this run "
            "(keys missing or all parked); skipping the query plan so the "
            "HR budget is not spent on guaranteed empties (recheck at the "
            "next run).",
        )
        return []

    # v61: Build multi-layer discovery plan
    all_queries: list[dict] = []
    all_queries.extend(_build_linkedin_native_queries(rotation_slot))
    all_queries.extend(_build_company_discovery_queries(rotation_slot))
    all_queries.extend(_build_recruiter_discovery_queries(rotation_slot))
    all_queries.extend(_build_hiring_intent_queries(rotation_slot))
    # v68 dedicated lanes — rotated per-run so the three lanes keep the
    # query plan diverse without multiplying it into a long homogeneous list.
    all_queries.extend(_build_recruiter_posts_lane(rotation_slot))
    all_queries.extend(_build_company_hiring_posts_lane(rotation_slot))
    all_queries.extend(_build_job_announcements_lane(rotation_slot))
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
        # v78: every search-engine method (native layers + fallback) now
        # routes through the same backend ladder — Google CSE is gone.
        if method in ("linkedin_native", "company_discovery", "recruiter_discovery",
                       "hiring_intent", "fallback_index"):
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
                # v68: verify the post URL directly before paying the full
                # scrape-and-score cost — a body-level hiring + role check
                # filters out index artifacts (articles, event pages) that
                # the search backends occasionally return and that later
                # failed with insufficient_hiring_or_role_evidence.
                verified, evidence = _verify_post_url(canonical_url, role_hint="cybersecurity")
                if not verified:
                    _record_rejection(evidence)
                    query_stats[query_text]["rejected"] += 1
                    log.debug("HR post URL declined before scrape (%s): %s", evidence, canonical_url)
                    continue
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
