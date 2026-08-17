"""
Unified LinkedIn engine — v61 (2x capacity).

Goals:
- ~70-75 query lanes with curated high-yield search matrix.
- Budget ~1800s for jobs + 90s for HR posts.
- Company-focused, title-variation, skill-based, Arabic, and remote discovery.
- Query rotation across CORE / HIGH_VALUE / SPECIALTY / COMPANY / ARABIC / SKILLS / REMOTE.
- Central rate limiting + circuit breaker preserved.
- Unique jobs focus: canonicalize queries, dedup metrics, query yield tracking.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

import config
from linkedin_url_utils import extract_linkedin_post_id
from models import Job, extract_salary_from_text
from sources.linkedin_common import FRESH_TPR
from sources.linkedin_hr_posts_scraper import (
    fetch_linkedin_hr_posts_scraper,
    get_hr_post_telemetry,
)
from sources.egypt_employer_registry import linkedin_employer_queries

log = logging.getLogger(__name__)

_LINKEDIN_PARTIAL_RESULTS: list[Job] = []
_LINKEDIN_TELEMETRY: dict[str, object] = {}
_LINKEDIN_MANAGED_TASKS: set[asyncio.Task] = set()


def get_linkedin_telemetry() -> dict[str, object]:
    """Immutable-by-convention snapshot used by the run health report."""
    return dict(_LINKEDIN_TELEMETRY)


def _create_linkedin_task(coro) -> asyncio.Task:
    """Create a LinkedIn child task that shutdown code can always await."""
    task = asyncio.create_task(coro)
    _LINKEDIN_MANAGED_TASKS.add(task)
    task.add_done_callback(_LINKEDIN_MANAGED_TASKS.discard)
    return task


async def _shutdown_linkedin_tasks(
    tasks: list[asyncio.Task], telemetry: dict[str, object], *, report: bool = False
) -> None:
    """Cancel and join unfinished LinkedIn tasks before their loop can close."""
    pending = [task for task in set(tasks) if not task.done()]
    before = len(pending)
    telemetry["pending_tasks_before"] = int(telemetry.get("pending_tasks_before", 0)) + before
    if pending:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    after = sum(1 for task in tasks if not task.done())
    telemetry["cancelled_tasks"] = int(telemetry.get("cancelled_tasks", 0)) + before
    telemetry["pending_tasks_after"] = after
    if report or before:
        log.info(
            "LinkedIn shutdown: pending_tasks_before=%d cancelled_tasks=%d pending_tasks_after=%d",
            before,
            before,
            after,
        )


def _geo_hint_from_query_location(query_location: str) -> str:
    """
    Derive a discovery geo_hint from the LinkedIn query location string.
    Returns: "egypt" | "arab" | "global" | ""
    """
    if not query_location:
        return ""
    loc = query_location.lower()
    _eg = {p for p in config.EGYPT_PATTERNS if p.strip()}
    _arab = {p for p in config.ARAB_PATTERNS if p.strip()}
    if any(x in loc for x in _eg):
        return "egypt"
    if any(x in loc for x in _arab):
        return "arab"
    return "global"


SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

try:
    import aiohttp
except Exception:  # pragma: no cover
    aiohttp = None


@dataclass(slots=True)
class QuerySpec:
    keywords: str
    location: str = ""
    remote: bool = False
    pages: tuple[int, ...] = (0, 25, 50)
    priority: int = 100
    source_key: str = "linkedin_jobs"
    lane_type: str = "core"  # core, high_value, specialty, company, arabic, skills, remote


def _canonicalize_query(keywords: str, location: str = "", remote: bool = False) -> str:
    """Produce a stable canonical string for query dedup tracking."""
    parts = [keywords.lower().strip()]
    if remote:
        parts.append("remote")
    elif location:
        parts.append(location.lower().strip())
    return "|".join(parts)


def _expanded_pages(query: QuerySpec) -> tuple[int, ...]:
    """Extend a query's pagination only up to its controlled cap."""
    pages = list(dict.fromkeys(query.pages))
    page_cap = max(1, config.LINKEDIN_MAX_PAGES_PER_QUERY)
    next_start = (max(pages) + 25) if pages else 0
    while len(pages) < page_cap:
        pages.append(next_start)
        next_start += 25
    return tuple(pages)


# ============================================================
# v61: MULTI-DIMENSIONAL SEARCH MATRIX
# ============================================================

# --- A) Core Cyber Keywords ---
_CORE_CYBER = [
    "cybersecurity", "cyber security", "information security", "infosec",
    "SOC", "security operations", "security analyst", "security engineer",
    "security architect", "incident response", "threat intelligence",
    "threat hunting", "vulnerability management", "penetration testing",
    "pentest", "ethical hacking", "red team", "application security",
    "AppSec", "cloud security", "network security", "IAM",
    "identity and access management", "IGA", "GRC", "DevSecOps",
    "OT security", "detection engineering", "security monitoring",
]

# --- B) Specialty Roles ---
_SPECIALTY_ROLES = [
    "SOC Analyst", "SOC Engineer", "Security Operations Engineer",
    "Incident Response", "Threat Hunter", "Threat Intelligence Analyst",
    "Vulnerability Analyst", "Vulnerability Management",
    "Penetration Tester", "Red Team",
    "Application Security Engineer", "Product Security",
    "Cloud Security Engineer", "Cloud Security Architect",
    "Network Security Engineer", "Security Architect",
    "IAM Engineer", "IAM Analyst", "IGA Engineer",
    "PAM Engineer", "Access Management",
    "Okta", "Ping Identity", "CyberArk",
    "SailPoint", "Microsoft Entra",
    "GRC Analyst", "IT Risk Cyber", "Security Compliance",
    "DevSecOps Security", "DevSecOps Engineer",
    "Container Security", "Kubernetes Security",
    "OT/ICS Security", "OT Cybersecurity",
]

# --- C) Seniority Levels ---
_SENIORITY = [
    "Junior", "Entry Level", "Associate", "Mid-Level", "Senior",
    "Lead", "Principal", "Staff", "Manager", "Director", "Head", "Architect",
]

# --- Egypt Locations ---
_EGYPT_LOCATIONS = [
    "Egypt", "Cairo", "Giza", "Alexandria",
    "New Cairo", "6th of October", "Smart Village",
]

# --- Arab Country Locations ---
_ARAB_LOCATIONS = [
    "Saudi Arabia", "Riyadh", "Jeddah", "Dammam",
    "UAE", "Dubai", "Abu Dhabi",
    "Qatar", "Doha", "Kuwait", "Kuwait City",
    "Bahrain", "Manama", "Oman", "Muscat",
    "Jordan", "Amman", "Lebanon", "Beirut",
    "Morocco", "Casablanca", "Rabat",
    "Tunisia", "Algeria", "Iraq",
]

# --- Remote Patterns ---
_REMOTE_LOCATIONS = [
    "Remote", "Worldwide", "Work from anywhere",
    "Remote - EMEA", "Remote - Middle East",
]

# --- D) Title Variations ---
_TITLE_VARIATIONS = [
    "Security Engineer", "Cybersecurity Engineer", "Information Security Engineer",
    "Security Analyst", "Cybersecurity Analyst", "SOC Analyst", "SOC Engineer",
    "Security Operations Engineer", "Cyber Defense Engineer",
    "IAM Engineer", "Identity Engineer", "Access Management Engineer",
    "IGA Engineer", "Application Security Engineer", "AppSec Engineer",
    "Product Security Engineer", "Cloud Security Engineer",
    "Cloud Security Architect", "Network Security Engineer",
    "Pentest Engineer", "Penetration Tester", "Red Team Engineer",
    "GRC Analyst", "Cyber Risk Analyst", "Security Compliance Analyst",
    "Security Architect", "Cybersecurity Architect",
]

# --- E) Skill-based Discovery ---
_SKILL_KEYWORDS = [
    "AWS security", "Azure security", "GCP security",
    "SIEM", "Splunk", "Sentinel", "QRadar",
    "CrowdStrike", "Defender", "EDR", "XDR", "SOAR",
    "Palo Alto", "Fortinet", "F5", "Zscaler",
    "Okta", "Ping", "CyberArk", "SailPoint", "Entra",
    "Kubernetes", "Docker", "Terraform",
    "Python security", "Burp Suite", "Nmap", "Metasploit", "Wireshark",
    "SAST", "DAST", "SCA", "WAF", "IDS", "IPS", "DLP", "PAM", "IAM",
    "Zero Trust",
]

# --- F) Arabic Discovery ---
_ARABIC_QUERIES = [
    "أمن سيبراني", "الأمن السيبراني", "أمن المعلومات",
    "أمن الشبكات", "مهندس أمن", "مهندس أمن سيبراني",
    "محلل أمن", "مركز عمليات الأمن",
    "اختبار اختراق", "الهوية وإدارة الوصول",
    "أمن التطبيقات", "أمن سحابي",
]

# --- G) Priority Companies ---
_COMPANY_NAMES = {
    # Banks
    "banks": [
        "NBE", "Banque Misr", "CIB", "QNB", "Banque du Caire",
        "AlexBank", "AAIB", "Cr\u00e9dit Agricole", "HSBC",
        "ADIB", "FABMISR", "HDB", "Emirates NBD", "Mashreq",
        "AIB", "Bank ABC", "EBank", "MIDBANK", "SAIB",
        "Al Baraka", "Faisal", "KFH", "Bank NXT",
    ],
    # Telecom / Digital
    "telecom": [
        "WE", "Vodafone", "VOIS", "Orange", "Orange Business",
        "e&", "Raya", "Nokia", "Ericsson", "Huawei", "IBM", "Cisco",
    ],
    # Cyber / Technology
    "cyber_tech": [
        "Wiz", "Cloudflare", "Tenable", "Rapid7", "CrowdStrike",
        "Palo Alto Networks", "Fortinet", "Microsoft", "Google", "AWS",
        "Oracle", "Okta", "CyberArk", "SailPoint", "Ping Identity",
        "Mandiant", "HackerOne", "Bugcrowd",
    ],
    # Public / Critical
    "public": [
        "MCIT", "ITIDA", "NTRA", "NTI", "TIEC",
        "Egypt Post", "EBC",
    ],
}

# Flatten all company names for iteration
_ALL_COMPANIES = []
for _sector, _names in _COMPANY_NAMES.items():
    for _name in _names:
        _ALL_COMPANIES.append((_name, _sector))


# ============================================================
# CURATED HIGH-YIELD QUERY LANE GENERATION
# ============================================================

def _build_core_lanes() -> list[QuerySpec]:
    """CORE lanes: run every execution. Highest-priority Egypt queries."""
    lanes: list[QuerySpec] = []
    p = 10
    # Top Egypt queries — multiple pages for highest-yield keywords
    for kw in ["cybersecurity", "SOC analyst", "security engineer", "penetration tester",
               "information security", "GRC analyst", "cybersecurity intern",
               "application security", "threat intelligence", "devsecops",
               "cloud security", "network security", "security operations",
               "incident response", "vulnerability management"]:
        pages = (0, 25, 50, 75) if p <= 16 else (0, 25, 50)
        lanes.append(QuerySpec(kw, "Cairo, Egypt", pages=pages, priority=p, lane_type="core"))
        p += 1
    # Egypt-wide for broader coverage
    for kw in ["IAM", "security analyst", "access management", "SOC",
               "security architect", "cyber security", "infosec"]:
        lanes.append(QuerySpec(kw, "Egypt", pages=(0, 25), priority=p, lane_type="core"))
        p += 1
    return lanes


def _build_high_value_lanes() -> list[QuerySpec]:
    """HIGH_VALUE lanes: run every execution or rotating. Egypt + Arab focus."""
    lanes: list[QuerySpec] = []
    p = 40
    # Additional Egypt roles
    for kw, loc in [
        ("Cybersecurity Engineer", "Cairo, Egypt"),
        ("Information Security Engineer", "Egypt"),
        ("Security Operations Engineer", "Egypt"),
        ("Threat Hunter", "Egypt"),
        ("Vulnerability Analyst", "Egypt"),
        ("Cloud Security Engineer", "Egypt"),
        ("DevSecOps Engineer", "Egypt"),
        ("Network Security Engineer", "Egypt"),
        ("Security Architect", "Egypt"),
        ("GRC Analyst", "Cairo, Egypt"),
        ("Cyber Risk Analyst", "Egypt"),
        ("Security Compliance Analyst", "Egypt"),
        ("IAM Engineer", "Egypt"),
        ("Okta", "Egypt"),
        ("CyberArk", "Egypt"),
        ("SailPoint", "Egypt"),
    ]:
        lanes.append(QuerySpec(kw, loc, pages=(0, 25), priority=p, lane_type="high_value"))
        p += 1
    # Governorates
    for kw, loc in [
        ("cybersecurity", "Alexandria, Egypt"),
        ("information security", "Giza, Egypt"),
        ("security engineer", "New Cairo, Egypt"),
        ("cybersecurity", "6th of October, Egypt"),
    ]:
        lanes.append(QuerySpec(kw, loc, pages=(0,), priority=p, lane_type="high_value"))
        p += 1
    return lanes


def _build_specialty_lanes(rotation_slot: int) -> list[QuerySpec]:
    """SPECIALTY lanes: rotate between runs. Seniority + niche roles."""
    lanes: list[QuerySpec] = []
    p = 60
    # Curated seniority combinations (NOT full Cartesian product)
    _seniority_combos = [
        ("Senior Security Engineer", "Egypt"),
        ("Junior Cybersecurity Analyst", "Egypt"),
        ("Senior SOC Analyst", "Cairo, Egypt"),
        ("Lead Security Engineer", "Egypt"),
        ("Entry Level Security Analyst", "Egypt"),
        ("Principal Security Architect", "Remote"),
        ("Senior Penetration Tester", "Egypt"),
        ("Cloud Security Architect", "Egypt"),
        ("Staff Security Engineer", "Remote"),
        ("Mid-Level GRC Analyst", "Egypt"),
        ("Senior IAM Engineer", "Egypt"),
        ("Director Cybersecurity", "Saudi Arabia"),
        ("Senior DevSecOps Engineer", "Egypt"),
        ("Cybersecurity Manager", "UAE"),
        ("Security Consultant", "Egypt"),
        ("Malware Analyst", "Egypt"),
        ("Digital Forensics", "Egypt"),
        ("Security Auditor", "Egypt"),
        ("Detection Engineer", "Egypt"),
        ("Container Security", "Egypt"),
        ("Kubernetes Security", "Egypt"),
        ("Product Security Engineer", "Egypt"),
        ("OT Cybersecurity", "Saudi Arabia"),
        ("Red Team Engineer", "Egypt"),
    ]
    # Rotate: pick a slice based on rotation_slot
    chunk_size = 6
    start = (rotation_slot * chunk_size) % len(_seniority_combos)
    rotated = _seniority_combos[start:] + _seniority_combos[:start]
    for kw, loc in rotated[:chunk_size]:
        remote = loc == "Remote"
        lanes.append(QuerySpec(
            kw, "" if remote else loc,
            pages=(0,),
            priority=p,
            remote=remote,
            source_key="linkedin_remote" if remote else "linkedin_jobs",
            lane_type="specialty",
        ))
        p += 1
    return lanes


def _build_company_lanes(rotation_slot: int) -> list[QuerySpec]:
    """COMPANY lanes: search by company name + cyber keywords. Rotating by priority."""
    lanes: list[QuerySpec] = []
    p = 80
    # Curated company+role combinations for Egypt
    _company_queries_egypt = [
        ("Vodafone Egypt", "cybersecurity"),
        ("Vodafone Egypt", "security engineer"),
        ("CIB", "information security"),
        ("NBE", "cybersecurity"),
        ("Banque Misr", "security analyst"),
        ("QNB", "cyber security"),
        ("Orange Egypt", "security engineer"),
        ("WE", "cybersecurity"),
        ("IBM", "security engineer"),
        ("Cisco", "cybersecurity"),
        ("Microsoft", "security engineer"),
        ("Oracle", "cloud security"),
    ]
    _company_queries_arab = [
        ("Emirates NBD", "cybersecurity"),
        ("Mashreq", "information security"),
        ("ADIB", "security analyst"),
        ("STC", "cybersecurity"),
        ("e&", "security engineer"),
        ("FABMISR", "GRC analyst"),
    ]
    _company_queries_cyber = [
        ("CrowdStrike", "security engineer"),
        ("Palo Alto Networks", "cloud security"),
        ("Fortinet", "security engineer"),
        ("Tenable", "vulnerability management"),
        ("Rapid7", "SOC analyst"),
        ("Cloudflare", "security engineer"),
        ("Wiz", "cloud security"),
        ("SailPoint", "IAM engineer"),
        ("Okta", "identity and access management"),
        ("CyberArk", "PAM engineer"),
        ("Mandiant", "incident response"),
        ("HackerOne", "penetration tester"),
    ]
    all_company_queries = _company_queries_egypt + _company_queries_arab + _company_queries_cyber
    chunk_size = 8
    start = (rotation_slot * chunk_size) % len(all_company_queries)
    rotated = all_company_queries[start:] + all_company_queries[:start]
    for company, role in rotated[:chunk_size]:
        kw = f'"{company}" {role}'
        lanes.append(QuerySpec(kw, pages=(0,), priority=p, lane_type="company", source_key="linkedin_company"))
        p += 1
    return lanes


def _build_arabic_lanes(rotation_slot: int) -> list[QuerySpec]:
    """ARABIC lanes: rotating Arabic/English queries for Egypt and Arab region."""
    lanes: list[QuerySpec] = []
    p = 100
    # Arabic Egypt queries (rotate 4 per run)
    _arabic_egypt = [
        ("أمن سيبراني", "مصر"),
        ("أمن معلومات", "مصر"),
        ("مهندس أمن سيبراني", "مصر"),
        ("محلل أمن", "مصر"),
        ("اختبار اختراق", "مصر"),
        ("أمن الشبكات", "مصر"),
        ("مركز عمليات الأمن", "مصر"),
        ("الهوية وإدارة الوصول", "مصر"),
        ("أمن التطبيقات", "مصر"),
        ("أمن سحابي", "مصر"),
        ("الأمن السيبراني", "القاهرة"),
        ("مهندس أمن", "مصر"),
    ]
    chunk_size = 4
    start = (rotation_slot * chunk_size) % len(_arabic_egypt)
    rotated = _arabic_egypt[start:] + _arabic_egypt[:start]
    for kw, loc in rotated[:chunk_size]:
        lanes.append(QuerySpec(kw, loc, pages=(0,), priority=p, lane_type="arabic", source_key="linkedin_arabic"))
        p += 1
    return lanes


def _build_skills_lanes(rotation_slot: int) -> list[QuerySpec]:
    """SKILLS lanes: rotating skill-based discovery as secondary signal."""
    lanes: list[QuerySpec] = []
    p = 110
    _skill_queries = [
        ("Splunk", "Egypt"), ("SIEM", "Egypt"),
        ("Sentinel", "Egypt"), ("CrowdStrike", "Egypt"),
        ("EDR", "Egypt"), ("Palo Alto", "Egypt"),
        ("Fortinet", "Egypt"), ("Zscaler", "Egypt"),
        ("Okta", "Egypt"), ("CyberArk", "Egypt"),
        ("SailPoint", "Egypt"), ("Kubernetes security", "Egypt"),
        ("AWS security", "Egypt"), ("Azure security", "Egypt"),
        ("Terraform security", "Egypt"), ("Burp Suite", "Egypt"),
        ("Nmap", "Egypt"), ("Wireshark", "Egypt"),
        ("WAF", "Egypt"), ("Zero Trust", "Egypt"),
    ]
    chunk_size = 4
    start = (rotation_slot * chunk_size) % len(_skill_queries)
    rotated = _skill_queries[start:] + _skill_queries[:start]
    for kw, loc in rotated[:chunk_size]:
        lanes.append(QuerySpec(kw, loc, pages=(0,), priority=p, lane_type="skills"))
        p += 1
    return lanes


def _build_remote_lanes(rotation_slot: int) -> list[QuerySpec]:
    """REMOTE lanes: rotating remote cyber queries."""
    lanes: list[QuerySpec] = []
    p = 120
    _remote_queries = [
        "cybersecurity engineer", "SOC analyst", "application security",
        "GRC analyst", "threat intelligence analyst", "penetration tester",
        "cloud security engineer", "devsecops engineer", "security researcher",
        "security architect", "incident response", "IAM engineer",
        "red team engineer", "network security engineer", "detection engineer",
        "vulnerability analyst", "security operations engineer",
    ]
    chunk_size = 4
    start = (rotation_slot * chunk_size) % len(_remote_queries)
    rotated = _remote_queries[start:] + _remote_queries[:start]
    for kw in rotated[:chunk_size]:
        lanes.append(QuerySpec(kw, remote=True, pages=(0, 25), priority=p,
                              source_key="linkedin_remote", lane_type="remote"))
        p += 1
    return lanes


def _build_arab_focus_lanes(rotation_slot: int) -> list[QuerySpec]:
    """Arab-region lanes: rotating across countries with core cyber keywords."""
    lanes: list[QuerySpec] = []
    p = 30
    _arab_keywords = ["SOC analyst", "penetration tester", "cybersecurity",
                      "security engineer", "cloud security", "GRC analyst",
                      "incident response", "devsecops"]
    lane_count = 5
    start = (rotation_slot * lane_count) % len(_ARAB_LOCATIONS)
    locations = [
        _ARAB_LOCATIONS[(start + offset) % len(_ARAB_LOCATIONS)]
        for offset in range(lane_count)
    ]
    for offset, (kw, loc) in enumerate(zip(_arab_keywords[:lane_count], locations)):
        lanes.append(QuerySpec(
            kw, loc, pages=(0,), priority=p + offset,
            source_key="linkedin_arab", lane_type="core",  # Arab focus is part of core
        ))
    return lanes


# ============================================================
# v62: YIELD-BASED LANE PRIORITIZATION
# ============================================================

# In-memory yield history: canonical_query -> {unique, dup, runs}
_LANE_YIELD_HISTORY: dict[str, dict] = {}


def _load_lane_yield_history() -> dict[str, dict]:
    """Load yield history from previous runs (in-memory cross-run persistence).
    For now, this is populated at the end of each run from telemetry."""
    return dict(_LANE_YIELD_HISTORY)


def _save_lane_yield_history(telemetry: dict) -> None:
    """Update yield history from current run's telemetry."""
    global _LANE_YIELD_HISTORY
    for cq, yield_data in telemetry.get("query_yield", {}).items():
        if cq not in _LANE_YIELD_HISTORY:
            _LANE_YIELD_HISTORY[cq] = {"unique": 0, "dup": 0, "runs": 0}
        if isinstance(yield_data, dict):
            _LANE_YIELD_HISTORY[cq]["unique"] += yield_data.get("unique", 0)
            _LANE_YIELD_HISTORY[cq]["dup"] += yield_data.get("dup", 0)
        else:
            # Legacy: yield_data was an int (unique count only)
            _LANE_YIELD_HISTORY[cq]["unique"] += int(yield_data)
        _LANE_YIELD_HISTORY[cq]["runs"] += 1


def _compute_lane_score(spec: QuerySpec, yield_history: dict[str, dict]) -> float:
    """Score a lane for priority ordering. Higher = run sooner.

    Factors:
    - CORE lanes get a base bonus (never demoted below rotating)
    - Historical unique_jobs yield gets positive weight
    - Historical duplicate ratio gets negative weight
    - Exploration bonus: lanes never seen get a small bonus to encourage discovery
    """
    cq = _canonicalize_query(spec.keywords, spec.location, spec.remote)
    history = yield_history.get(cq)

    # Base priority from QuerySpec
    base = 100 - min(spec.priority, 99)

    # CORE lane bonus — always run these first
    if spec.lane_type == "core":
        base += 50
    elif spec.lane_type == "high_value":
        base += 20
    elif spec.lane_type == "company":
        base += 10

    if not history:
        # Never seen — exploration bonus (moderate, not too high)
        base += 5
        return base

    runs = max(1, history.get("runs", 1))
    unique = history.get("unique", 0)
    dup = history.get("dup", 0)
    avg_unique = unique / runs
    avg_dup = dup / runs

    # Positive yield: lanes that produce unique jobs get higher priority
    if avg_unique > 5:
        base += 30
    elif avg_unique > 2:
        base += 15
    elif avg_unique > 0:
        base += 5
    else:
        # Zero-yield lanes get a small penalty (but not removed — exploration)
        base -= 10

    # Duplicate penalty: lanes with high dup/unique ratio get demoted
    if avg_unique > 0:
        dup_ratio = avg_dup / avg_unique
        if dup_ratio > 5:
            base -= 25  # Heavy duplicate lane — strong demotion
        elif dup_ratio > 3:
            base -= 15  # Moderate duplicate lane
        elif dup_ratio > 1.5:
            base -= 5   # Mild duplicate lane
    elif avg_dup > 10:
        # Zero unique but many duplicates — pure waste
        base -= 20

    return base


def _sort_plan_by_yield(plan: list[QuerySpec], yield_history: dict[str, dict]) -> list[QuerySpec]:
    """Sort query plan by yield score while preserving lane-type diversity.

    Strategy: interleave high-yield and exploration lanes so we don't
    starve any lane type. CORE lanes always come first in their group.
    """
    scored = [(q, _compute_lane_score(q, yield_history)) for q in plan]
    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)

    # Group by lane_type to ensure diversity
    type_groups: dict[str, list[tuple[QuerySpec, float]]] = {}
    for spec, score in scored:
        lt = spec.lane_type
        if lt not in type_groups:
            type_groups[lt] = []
        type_groups[lt].append((spec, score))

    # Interleave: take one from each type group in round-robin fashion
    # Order groups by their best score
    group_order = sorted(type_groups.keys(), key=lambda t: max(s for _, s in type_groups[t]), reverse=True)
    result: list[QuerySpec] = []
    iterators = {t: iter(type_groups[t]) for t in group_order}
    while iterators:
        to_remove = []
        for t in group_order:
            it = iterators[t]
            try:
                result.append(next(it)[0])
            except StopIteration:
                to_remove.append(t)
        for t in to_remove:
            del iterators[t]
            group_order.remove(t)

    return result


def _build_query_plan(rotation_slot: int) -> list[QuerySpec]:
    """Build the full query plan with all lane types.

    Ensures every lane type (including skills and remote) is represented
    by splitting high_value into always-on and rotating halves.
    v62: Applies yield-based prioritization from historical telemetry.
    """
    # Load yield history from previous runs
    yield_history = _load_lane_yield_history()

    # 1. CORE: always on — Egypt highest-yield + Arab focus rotation
    core = _build_core_lanes()
    arab_focus = _build_arab_focus_lanes(rotation_slot)

    # 2. HIGH_VALUE: split — first half always-on, second half rotating
    high_value_all = _build_high_value_lanes()
    hv_split = len(high_value_all) // 2
    high_value_fixed = high_value_all[:hv_split]
    high_value_rotating = high_value_all[hv_split:]

    # 3. EMPLOYER QUERIES: from egypt_employer_registry
    employer_queries = [
        QuerySpec(keywords, "Egypt", pages=(0,), priority=priority, source_key=source_key, lane_type="company")
        for keywords, source_key, priority in linkedin_employer_queries()
    ]

    # 4. ROTATING LANES (all lane types get a share)
    specialty = _build_specialty_lanes(rotation_slot)
    company = _build_company_lanes(rotation_slot)
    arabic = _build_arabic_lanes(rotation_slot)
    skills = _build_skills_lanes(rotation_slot)
    remote = _build_remote_lanes(rotation_slot)

    # Always-on: core + arab_focus + half high_value + employer
    always_on = core[:4] + arab_focus + core[4:] + high_value_fixed + employer_queries

    # Rotating pool: skills, remote, arabic first (guaranteed), then others
    rotating_pool = skills + remote + arabic + high_value_rotating + specialty + company

    max_queries = max(1, config.LINKEDIN_MAX_QUERIES_PER_RUN)
    if len(always_on) >= max_queries:
        plan = always_on[:max_queries]
    else:
        remaining = max_queries - len(always_on)
        rotation = rotation_slot % max(1, len(rotating_pool))
        rotated_pool = rotating_pool[rotation:] + rotating_pool[:rotation]
        plan = always_on + rotated_pool[:remaining]

    # v62: Apply yield-based reordering
    plan = _sort_plan_by_yield(plan, yield_history)

    return plan


class _RateLimiter:
    def __init__(self, max_rps: float):
        self._interval = max(0.0, 1.0 / max(0.05, max_rps))
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if now < self._next_allowed:
                await asyncio.sleep(self._next_allowed - now)
            self._next_allowed = time.monotonic() + self._interval + random.uniform(0.05, 0.25)


def _extract_job_ids(html: str) -> list[str]:
    ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
    if not ids:
        ids = re.findall(r'"jobPostingId":(\d+)', html)
    if not ids:
        ids = re.findall(r"/jobs/view/(\d+)/", html)
    out: list[str] = []
    seen: set[str] = set()
    for jid in ids:
        if jid in seen:
            continue
        seen.add(jid)
        out.append(jid)
    return out


def _clean_html_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _extract(pattern: str, html: str, default: str = "") -> str:
    m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else default


def _extract_posted_date(html: str) -> datetime | None:
    lowered = (html or "").lower()
    m = re.search(r"(\d{1,2})\s*(minute|minutes|min|hour|hours|hr|day|days|d|week|weeks|w|month|months)\s+ago", lowered)
    if not m:
        return None
    amount = int(m.group(1))
    unit = m.group(2)
    now = datetime.now()
    if unit.startswith("min"):
        return now - timedelta(minutes=amount)
    if unit.startswith("hour") or unit == "hr":
        return now - timedelta(hours=amount)
    if unit.startswith("day") or unit == "d":
        return now - timedelta(days=amount)
    if unit.startswith("week") or unit == "w":
        return now - timedelta(weeks=amount)
    if unit.startswith("month"):
        return now - timedelta(days=amount * 30)
    return None


def _parse_detail(html: str, job_id: str, source_key: str, origin_priority: int, geo_hint: str = "") -> Job | None:
    title = _clean_html_text(_extract(r'<h2[^>]*class="[^"]*top-card-layout__title[^"]*"[^>]*>(.*?)</h2>', html))
    if not title:
        title = _clean_html_text(_extract(r"<title>(.*?)</title>", html))
        title = re.sub(r"\s*\|\s*LinkedIn.*", "", title).strip()
    if not title:
        return None

    company = _clean_html_text(_extract(r'<a[^>]*class="[^"]*topcard__org-name-link[^"]*"[^>]*>(.*?)</a>', html))
    if not company:
        company = _clean_html_text(_extract(r'<span[^>]*class="[^"]*topcard__flavor[^"]*"[^>]*>(.*?)</span>', html))
    location = _clean_html_text(_extract(r'<span[^>]*class="[^"]*topcard__flavor--bullet[^"]*"[^>]*>(.*?)</span>', html))
    desc_raw = _extract(r'<div[^>]*class="[^"]*(?:description|show-more-less-html)[^"]*"[^>]*>(.*?)</div>', html)
    description = _clean_html_text(desc_raw)[:1400]
    posted_date = _extract_posted_date(html)
    is_remote = bool(re.search(r"\bremote\b", f"{location} {description}", re.IGNORECASE))

    return Job(
        title=title,
        company=company or "Unknown",
        location=location or "Not specified",
        url=f"https://www.linkedin.com/jobs/view/{job_id}/",
        source="linkedin_unified",
        source_key=source_key,
        salary=extract_salary_from_text(f"{title} {description}"),
        tags=["linkedin", "unified"],
        is_remote=is_remote,
        description=description,
        posted_date=posted_date,
        content_type="job_listing",
        origin_priority=origin_priority,
        geo_hint=geo_hint,
    )


async def _fetch_text(
    session: "aiohttp.ClientSession",
    limiter: _RateLimiter,
    url: str,
    *,
    params: dict | None = None,
    max_retries: int = 0,
    circuit_state: dict | None = None,
    deadline_ts: float | None = None,
) -> str | None:
    if deadline_ts is not None and time.time() >= deadline_ts:
        return None
    if circuit_state and circuit_state.get("open_until", 0.0) > time.time():
        await asyncio.sleep(0.4)
        return None

    for attempt in range(max_retries + 1):
        await limiter.acquire()
        if deadline_ts is not None and time.time() >= deadline_ts:
            return None
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 429:
                    if circuit_state is not None:
                        circuit_state["429"] = int(circuit_state.get("429", 0)) + 1
                        if circuit_state["429"] >= 5:
                            circuit_state["open_until"] = time.time() + 30
                            circuit_state["429"] = 0
                    await asyncio.sleep((2 ** attempt) + random.uniform(0.2, 1.0))
                    continue
                if resp.status >= 400:
                    if resp.status == 403:
                        return None
                    await asyncio.sleep((2 ** attempt) + random.uniform(0.1, 0.6))
                    continue
                text = await resp.text()
                if text and len(text) > 120:
                    return text
        except Exception:
            if attempt >= max_retries:
                return None
        await asyncio.sleep((2 ** attempt) + random.uniform(0.2, 0.8))
    return None


def _strict_filter_hr_posts(items: list[Job]) -> list[Job]:
    out: list[Job] = []
    for job in items:
        canonical = job.canonical_url
        post_id = extract_linkedin_post_id(canonical)
        if not post_id:
            continue
        job.source = "linkedin_unified"
        job.source_key = "linkedin_hr_posts"
        job.content_type = "hr_post"
        job.origin_priority = 5
        out.append(job)
    return out


async def _fetch_linkedin_unified_impl() -> list[Job]:
    global _LINKEDIN_PARTIAL_RESULTS, _LINKEDIN_TELEMETRY
    _LINKEDIN_MANAGED_TASKS.clear()
    budget_seconds = _jobs_budget_seconds()
    start_ts = time.time()
    all_jobs: list[Job] = []
    _LINKEDIN_PARTIAL_RESULTS = all_jobs

    # v61: Enhanced telemetry with query-type and dedup metrics
    telemetry: dict[str, object] = {
        "jobs_budget_seconds": budget_seconds, "jobs_used_seconds": 0.0,
        "hr_budget_seconds": config.LINKEDIN_HR_POSTS_BUDGET_SECONDS, "hr_used_seconds": 0.0,
        "queries": 0, "pages": 0, "details": 0, "partial": False,
        "jobs": 0, "hr_discovered": 0, "hr_accepted": 0, "hr_rejected_evidence": 0,
        "pending_tasks_before": 0, "cancelled_tasks": 0, "pending_tasks_after": 0,
        # v61 new metrics
        "queries_planned": 0, "queries_completed": 0, "query_empty_stops": 0,
        "stop_reasons": set(),
        "unique_jobs": 0, "duplicate_jobs": 0,
        "unique_queries": 0, "duplicate_queries": 0,
        "jobs_by_query_type": {},
        "jobs_by_location": {},
        "jobs_by_source": {},
        "query_yield": {},
    }
    _LINKEDIN_TELEMETRY = telemetry

    if aiohttp is None:
        return all_jobs

    # Start HR posts in parallel with jobs crawl.
    async def _fetch_hr_posts_with_timing() -> tuple[list[Job], float]:
        started = time.time()
        rows = await asyncio.to_thread(
            fetch_linkedin_hr_posts_scraper, config.LINKEDIN_HR_POSTS_BUDGET_SECONDS
        )
        return rows, round(time.time() - started, 3)

    hr_task: asyncio.Task[tuple[list[Job], float]] | None = None
    if config.ENABLE_SOURCE_LINKEDIN_HR_POSTS:
        hr_task = _create_linkedin_task(_fetch_hr_posts_with_timing())

    limiter = _RateLimiter(config.LINKEDIN_RATE_MAX_RPS)
    sem = asyncio.Semaphore(max(1, config.LINKEDIN_MAX_CONCURRENCY))
    circuit_state: dict[str, float | int] = {"429": 0, "open_until": 0.0}
    li_at = os.getenv("LI_AT", "").strip()
    cookies = {"li_at": li_at} if li_at else None
    if li_at:
        log.info("LinkedIn unified: LI_AT cookie detected (authenticated mode).")

    connector = aiohttp.TCPConnector(limit=max(4, config.LINKEDIN_MAX_CONCURRENCY * 2), ttl_dns_cache=300)
    timeout = aiohttp.ClientTimeout(total=16)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Referer": "https://www.linkedin.com/jobs/",
    }

    # v61: Build query plan with new search matrix
    rotation_slot = int(time.time() // (4 * 3600))
    plan = _build_query_plan(rotation_slot)

    # Track canonical queries for dedup metrics
    seen_canonical_queries: set[str] = set()
    for q in plan:
        cq = _canonicalize_query(q.keywords, q.location, q.remote)
        if cq in seen_canonical_queries:
            telemetry["duplicate_queries"] = int(telemetry.get("duplicate_queries", 0)) + 1
        else:
            seen_canonical_queries.add(cq)
            telemetry["unique_queries"] = int(telemetry.get("unique_queries", 0)) + 1

    seen_ids: set[str] = set()
    results_lock = asyncio.Lock()
    telemetry["queries"] = len(plan)
    telemetry["queries_planned"] = len(plan)
    telemetry["queries_completed"] = 0
    telemetry["query_empty_stops"] = 0
    telemetry["stop_reasons"] = set()

    # Log the new plan structure
    lane_type_counts: dict[str, int] = defaultdict(int)
    for q in plan:
        lane_type_counts[q.lane_type] += 1
    log.info(
        "LinkedIn Jobs plan: %d query lanes %s; up to %d pages/query, %d pages, %d details; budget=%ds",
        len(plan),
        dict(lane_type_counts),
        config.LINKEDIN_MAX_PAGES_PER_QUERY,
        config.LINKEDIN_MAX_PAGES_PER_RUN,
        config.LINKEDIN_MAX_DETAILS_PER_RUN,
        budget_seconds,
    )

    def _mark_stop(reason: str) -> None:
        telemetry["stop_reasons"].add(reason)

    deadline_ts = start_ts + budget_seconds
    query_sem = asyncio.Semaphore(max(1, config.LINKEDIN_QUERY_CONCURRENCY))

    async def _run_query(session: "aiohttp.ClientSession", query: QuerySpec) -> None:
        async with query_sem:
            try:
                if time.time() - start_ts > budget_seconds:
                    telemetry["partial"] = True
                    _mark_stop("jobs_budget")
                    return
                empty_page_streak = 0
                query_new = 0
                query_dup = 0
                for page_start in _expanded_pages(query):
                    if time.time() - start_ts > budget_seconds:
                        telemetry["partial"] = True
                        _mark_stop("jobs_budget")
                        break
                    async with results_lock:
                        if int(telemetry["pages"]) >= config.LINKEDIN_MAX_PAGES_PER_RUN:
                            telemetry["partial"] = True
                            _mark_stop("page_cap")
                            break
                        telemetry["pages"] = int(telemetry["pages"]) + 1
                    params = {
                        "keywords": query.keywords,
                        "start": str(page_start),
                        "count": "25",
                        "f_TPR": FRESH_TPR,
                    }
                    if query.location:
                        params["location"] = query.location
                    if query.remote:
                        params["f_WT"] = "2"

                    html = await _fetch_text(
                        session, limiter, SEARCH_URL, params=params,
                        max_retries=0, circuit_state=circuit_state,
                        deadline_ts=deadline_ts,
                    )
                    if not html:
                        if time.time() >= deadline_ts:
                            telemetry["partial"] = True
                            _mark_stop("jobs_budget")
                            break
                        continue

                    job_ids = _extract_job_ids(html)
                    if not job_ids:
                        empty_page_streak += 1
                        if empty_page_streak >= 2:
                            telemetry["query_empty_stops"] = int(telemetry["query_empty_stops"]) + 1
                            break
                        continue
                    empty_page_streak = 0

                    async with results_lock:
                        slots = max(0, config.LINKEDIN_MAX_DETAILS_PER_RUN - int(telemetry["details"]))
                        if slots <= 0:
                            telemetry["partial"] = True
                            _mark_stop("detail_cap")
                            return
                        new_ids = [jid for jid in job_ids if jid not in seen_ids][:slots]
                        dup_ids = [jid for jid in job_ids if jid in seen_ids]
                        for jid in new_ids:
                            seen_ids.add(jid)
                        telemetry["details"] = int(telemetry["details"]) + len(new_ids)
                        telemetry["duplicate_jobs"] = int(telemetry.get("duplicate_jobs", 0)) + len(dup_ids)
                        query_dup += len(dup_ids)

                    async def _load_one(job_id: str) -> Job | None:
                        async with sem:
                            detail_html = await _fetch_text(
                                session, limiter, DETAIL_URL.format(job_id=job_id),
                                max_retries=0, circuit_state=circuit_state,
                                deadline_ts=deadline_ts,
                            )
                            if not detail_html:
                                return None
                            return _parse_detail(
                                detail_html, job_id=job_id, source_key=query.source_key,
                                origin_priority=query.priority,
                                geo_hint=_geo_hint_from_query_location(query.location),
                            )

                    if new_ids:
                        detail_tasks = [_create_linkedin_task(_load_one(jid)) for jid in new_ids]
                        try:
                            rows = await asyncio.gather(*detail_tasks, return_exceptions=True)
                        finally:
                            await _shutdown_linkedin_tasks(detail_tasks, telemetry)
                        async with results_lock:
                            for row in rows:
                                if isinstance(row, Job):
                                    all_jobs.append(row)
                                    query_new += 1
                                    # v61: Track by query type, location, source
                                    lt = query.lane_type
                                    telemetry["jobs_by_query_type"][lt] = int(telemetry["jobs_by_query_type"].get(lt, 0)) + 1
                                    sk = query.source_key
                                    telemetry["jobs_by_source"][sk] = int(telemetry["jobs_by_source"].get(sk, 0)) + 1
                                    gh = _geo_hint_from_query_location(query.location)
                                    if gh:
                                        telemetry["jobs_by_location"][gh] = int(telemetry["jobs_by_location"].get(gh, 0)) + 1
                    await asyncio.sleep(random.uniform(0.12, 0.35))

                    # Deep zero-yield pagination is stopped per query
                    if page_start >= 50 and query_new < 4:
                        telemetry["query_empty_stops"] = int(telemetry["query_empty_stops"]) + 1
                        break
            finally:
                async with results_lock:
                    telemetry["queries_completed"] = int(telemetry["queries_completed"]) + 1
                    # v62: Track per-lane yield with unique/dup breakdown
                    cq = _canonicalize_query(query.keywords, query.location, query.remote)
                    telemetry["query_yield"][cq] = {"unique": query_new, "dup": query_dup}

    query_tasks: list[asyncio.Task] = []
    try:
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=headers,
            cookies=cookies,
        ) as session:
            query_tasks = [_create_linkedin_task(_run_query(session, query)) for query in plan]
            try:
                await asyncio.gather(*query_tasks, return_exceptions=True)
            finally:
                await _shutdown_linkedin_tasks(query_tasks, telemetry)
    finally:
        if not connector.closed:
            await connector.close()

    telemetry["jobs_used_seconds"] = round(time.time() - start_ts, 3)
    telemetry["jobs"] = len(all_jobs)
    telemetry["unique_jobs"] = len(seen_ids)
    if not telemetry["stop_reasons"]:
        _mark_stop("query_plan_complete")
    telemetry["stop_reason"] = ",".join(sorted(telemetry["stop_reasons"]))

    # Merge HR posts
    if hr_task:
        hr_raw: list[Job] = []
        if not hr_task.done():
            await _shutdown_linkedin_tasks([hr_task], telemetry, report=True)
            telemetry["partial"] = True
            log.warning("LinkedIn HR posts did not finish within their reserved window.")
        else:
            try:
                hr_raw, hr_elapsed = hr_task.result()
                telemetry["hr_used_seconds"] = hr_elapsed
            except Exception as exc:
                log.info("LinkedIn HR posts stopped: %s", type(exc).__name__)
                telemetry["partial"] = True
        hr_posts = _strict_filter_hr_posts(hr_raw)
        all_jobs.extend(hr_posts if config.ENABLE_STRICT_HR_POSTS_ONLY else hr_raw)
        telemetry["hr_discovered"] = len(hr_raw)
        telemetry["hr_accepted"] = len(hr_posts)
        telemetry["hr_rejected_evidence"] = max(0, len(hr_raw) - len(hr_posts))
        hr_telemetry = get_hr_post_telemetry()
        telemetry["hr_queries_planned"] = hr_telemetry.get("queries_planned", 0)
        telemetry["hr_queries_attempted"] = hr_telemetry.get("queries_attempted", 0)
        telemetry["hr_urls_discovered"] = hr_telemetry.get("urls_discovered", 0)
        telemetry["hr_posts_scrape_attempted"] = hr_telemetry.get("posts_scrape_attempted", 0)
        telemetry["hr_search_backend_hits"] = hr_telemetry.get("search_backend_hits", {})
        telemetry["hr_search_backend_empty"] = hr_telemetry.get("search_backend_empty", {})
        telemetry["hr_rejections"] = hr_telemetry.get("rejections", {})
        # v61: HR discovery method breakdown
        telemetry["hr_accepted_by_method"] = hr_telemetry.get("accepted_by_method", {})
        telemetry["hr_company_yield"] = hr_telemetry.get("company_yield", {})
        telemetry["hr_recruiter_yield"] = hr_telemetry.get("recruiter_yield", {})
    telemetry["jobs"] = len(all_jobs)
    _LINKEDIN_TELEMETRY = telemetry

    # v62: Compute yield_by_lane summary from query_yield
    yield_by_lane: dict[str, dict] = {}
    for cq, yield_data in telemetry.get("query_yield", {}).items():
        if isinstance(yield_data, dict):
            unique = yield_data.get("unique", 0)
            dup = yield_data.get("dup", 0)
        else:
            unique = int(yield_data)
            dup = 0
        # Derive lane_type from canonical query
        lane_type = "unknown"
        for q in plan:
            if _canonicalize_query(q.keywords, q.location, q.remote) == cq:
                lane_type = q.lane_type
                break
        if lane_type not in yield_by_lane:
            yield_by_lane[lane_type] = {"unique_jobs": 0, "duplicate_jobs": 0, "lanes": 0}
        yield_by_lane[lane_type]["unique_jobs"] += unique
        yield_by_lane[lane_type]["duplicate_jobs"] += dup
        yield_by_lane[lane_type]["lanes"] += 1
    telemetry["yield_by_lane"] = yield_by_lane

    # v62: Save yield history for next run's prioritization
    _save_lane_yield_history(telemetry)

    log.info("LinkedIn unified: collected %d jobs/posts total", len(all_jobs))
    return all_jobs


def _jobs_budget_seconds() -> int:
    """Keep enough of LinkedIn's fixed ceiling to merge the HR-post result."""
    hr_reserve = config.LINKEDIN_HR_POSTS_BUDGET_SECONDS + 5
    return min(
        config.LINKEDIN_JOBS_BUDGET_SECONDS,
        max(1, config.LINKEDIN_TOTAL_BUDGET_SECONDS - hr_reserve),
    )


async def fetch_linkedin_unified_async() -> list[Job]:
    budget = int(getattr(config, "LINKEDIN_TOTAL_BUDGET_SECONDS", 180))
    impl_task = _create_linkedin_task(_fetch_linkedin_unified_impl())
    try:
        return await asyncio.wait_for(asyncio.shield(impl_task), timeout=budget)
    except asyncio.TimeoutError:
        await _shutdown_linkedin_tasks(
            [impl_task, *_LINKEDIN_MANAGED_TASKS], _LINKEDIN_TELEMETRY, report=True
        )
        log.warning(
            "LinkedIn Unified: hard timeout after %ss - returning %d partial results",
            budget,
            len(_LINKEDIN_PARTIAL_RESULTS),
        )
        return list(_LINKEDIN_PARTIAL_RESULTS)
    except asyncio.CancelledError:
        await _shutdown_linkedin_tasks(
            [impl_task, *_LINKEDIN_MANAGED_TASKS], _LINKEDIN_TELEMETRY, report=True
        )
        raise
    finally:
        if not impl_task.done():
            await _shutdown_linkedin_tasks(
                [impl_task, *_LINKEDIN_MANAGED_TASKS], _LINKEDIN_TELEMETRY
            )


def fetch_linkedin_unified() -> list[Job]:
    if aiohttp is None:
        if not config.ENABLE_SOURCE_LINKEDIN_HR_POSTS:
            return []
        hr_raw = fetch_linkedin_hr_posts_scraper()
        hr_posts = _strict_filter_hr_posts(hr_raw)
        return hr_posts if config.ENABLE_STRICT_HR_POSTS_ONLY else hr_raw
    try:
        return asyncio.run(fetch_linkedin_unified_async())
    except RuntimeError:
        return []


# ============================================================
# BACKWARD-COMPAT ALIASES (for existing tests)
# ============================================================
ARAB_COUNTRY_LOCATIONS: tuple[str, ...] = tuple(_ARAB_LOCATIONS)
CORE_QUERIES: list[QuerySpec] = []  # v61: replaced by _build_query_plan()
EXPANSION_QUERIES: list[QuerySpec] = []  # v61: replaced by _build_query_plan()


def _arab_focus_queries(rotation_slot: int) -> list[QuerySpec]:
    """Backward-compat wrapper for tests — mimics old 5-lane SOC/Pentest-heavy plan."""
    old_keywords = ("SOC analyst", "penetration tester", "cybersecurity", "SOC analyst", "penetration tester")
    lane_count = len(old_keywords)
    start = (rotation_slot * lane_count) % len(_ARAB_LOCATIONS)
    locations = [
        _ARAB_LOCATIONS[(start + offset) % len(_ARAB_LOCATIONS)]
        for offset in range(lane_count)
    ]
    return [
        QuerySpec(keyword, location, pages=(0,), priority=27 + offset, source_key="linkedin_arab", lane_type="core")
        for offset, (keyword, location) in enumerate(zip(old_keywords, locations))
    ]

