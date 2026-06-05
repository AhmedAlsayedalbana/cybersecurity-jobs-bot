"""
Hybrid AI Filter — Ultimate v50+
=================================
Layer 0: Persistent cache (title-level MD5 hash)
Layer 1: Fast false-positive exclusion (physical security, sales, HR, etc.)
Layer 2: Expanded modern cybersec title patterns (Arabic + English)
Layer 3: Context-aware semantic scoring (tools, frameworks, certs)
Layer 4: Anthropic Claude API — borderline cases only (batched, rate-limited)

Fixes included vs v42/AKM:
- False Negatives: Trust & Safety, Platform Integrity, Zero Trust Architect
- False Positives: Cloud Infra Eng, Platform Reliability Eng, Network Team Lead

AT-AKM Merge: this is the definitive standalone implementation.
The intelligence/ compatibility wrapper (old ai_filter.py) is superseded by this.
"""

import os
import re
import json
import logging
import hashlib
import time
from functools import lru_cache
from typing import Optional

import config

log = logging.getLogger(__name__)

# ── Layer 2: Modern cybersec titles missed by keyword filter ──────────────────
MODERN_CYBERSEC_TITLES = [
    # Trust & Safety / Abuse
    "trust and safety", "trust & safety", "abuse analyst", "abuse prevention",
    "abuse engineer", "content integrity", "platform integrity",
    "platform trust", "policy enforcement", "online safety",
    # Cyber Defense variants
    "cyber defense", "cyber defence", "cyberdefense",
    "security automation", "security orchestration",
    "zero trust architect", "zero trust engineer",
    # Detection & Response
    "detection engineer", "detection and response", "detection & response",
    "hunt analyst", "threat hunt", "soc engineer",
    # Offensive
    "offensive security", "adversarial simulation",
    "purple team", "purple teamer",
    # Identity
    "identity security", "identity protection",
    "privileged access", "pam engineer", "pam analyst",
    # Privacy/Data Security (cybersec-adjacent)
    "data security analyst", "data security engineer",
    "privacy engineer", "security privacy",
    # Cloud Security variants
    "cloud protection", "cloud defense",
    "container security", "kubernetes security",
    "infrastructure security",
    # Arabic modern titles
    "أمن سيبراني", "أمن معلومات", "اختبار اختراق",
    "أمن شبكات", "محلل أمن", "مهندس أمن",
    "أمن المعلومات", "حماية المعلومات", "اختبار الاختراق",
    # v51 false negatives observed in production logs.
    "it security analyst", "it security engineer",
    "sase", "sase engineer", "sase architect", "sase subject matter expert",
    "identity and access", "identity access management",
    "dns security", "endpoint security",
    "security technical architect",
    "product security manager", "product security engineer",
    "security incident response",
    "security compliance analyst", "security regulatory",
    "insider risk", "insider threat",
    "cleared vulnerability", "vulnerability research engineer",
]
MODERN_CYBERSEC_TITLES = config.sanitize_keywords(MODERN_CYBERSEC_TITLES, min_len=2)

# ── Layer 1: False positive exclusion ────────────────────────────────────────
# Titles with "security" that are NOT cybersecurity
FALSE_POSITIVE_PATTERNS = [
    # Physical/Corporate security
    r"\bsecurity guard\b", r"\bsecurity officer\b(?!.*cyber|.*info|.*network)",
    r"\bsecurity supervisor\b", r"\bsecurity patrol\b",
    r"\bloss prevention\b", r"\bevent security\b", r"\bbuilding security\b",
    r"\bphysical security\b(?!.*cyber|.*architect)",
    # Sales/Business
    r"\bsecurity sales\b", r"\bsales.*security\b",
    r"\bsecurity account\b", r"\bsecurity customer\b",
    # Infrastructure (non-cyber)
    r"\bcloud infrastructure\b(?!.*security)",
    r"\bsite reliability\b(?!.*security)",
    r"\bplatform reliability\b(?!.*security)",
    r"\bnetwork administrator\b(?!.*security)",
    # Generic IT support
    r"\bit support\b(?!.*security)", r"\bhelp desk\b",
    r"\bdesktop support\b",
    # Generic management/IT titles with no cyber signal (v44 additions)
    r"\bnetwork team leader\b",
    r"\bwan management\b",
    r"\bprofessional, information technology\b",
    r"\bmanaging consultant.*strategy.*transformation\b",
    r"\bmanaging consultant.*digital transformation\b",
    r"\bsenior consultant.*technology risk\b(?!.*cyber|.*security)",
    r"\bcabin crew\b", r"\bstudent marketeer\b", r"\blead generation\b",
    r"\breal estate\b", r"\bhuman resources assistant\b",
    r"\boperations hse\b", r"\bfire life safety\b",
    r"\baviation security\b(?!.*cyber|.*info)",
]

NON_CYBER_ROLE_PATTERNS = [
    r"\blegal counsel\b", r"\blegal specialist\b", r"\bcontract specialist\b",
    r"\bcontract manager\b", r"\blegal advisor\b", r"\bcorporate counsel\b",
    r"\battorney\b", r"\bparalegal\b", r"\blegal\s*&\s*contract\b",
    r"\baccount manager\b", r"\baccount executive\b", r"\bsales manager\b",
    r"\bbusiness development\b", r"\benterprise sales\b", r"\bregional sales\b",
    r"\bsales engineer\b",
]

CONTEXTUAL_NON_CYBER_ROLE_PATTERNS = [
    r"\bprogram manager\b", r"\bproject manager\b", r"\bdelivery manager\b",
    r"\bscrum master\b", r"\bagile coach\b",
    r"\bfinancial controller\b", r"\btreasury manager\b", r"\bbudget analyst\b",
    r"\binternal auditor\b", r"\baudit manager\b", r"\bauditor\b",
    r"\bcontinuous monitoring\b",
]

CYBER_TITLE_OVERRIDES = [
    "security", "cyber", "cybersecurity", "infosec", "information security",
    "it auditor", "it audit", "grc", "soc", "pentest", "penetration",
    "privacy", "data protection", "iso 27001", "nist",
]

# ── Layer 3: Context signals that confirm cybersecurity ───────────────────────
CYBER_CONTEXT_SIGNALS = [
    # Tools
    "siem", "soc", "edr", "xdr", "splunk", "qradar", "sentinel", "crowdstrike",
    "defender", "palo alto", "fortinet", "wireshark", "metasploit", "burp suite",
    "nessus", "qualys", "rapid7", "tenable",
    # Frameworks
    "mitre att&ck", "nist", "iso 27001", "pci dss", "gdpr", "soc 2",
    "zero trust", "cis controls", "owasp", "cvss",
    # Concepts
    "threat intelligence", "incident response", "vulnerability management",
    "penetration testing", "red team", "blue team", "purple team",
    "malware analysis", "digital forensics", "threat hunting",
    "security operations", "identity access management",
    "endpoint protection", "network security", "application security",
    # Certs mentioned in job desc
    "cissp", "ceh", "oscp", "cism", "comptia security", "giac",
]

_TITLE_TECH_GUARDS = {
    "soc", "siem", "dfir", "pentest", "penetration", "appsec", "devsecops",
    "incident response", "threat intelligence", "network security", "cloud security",
    "identity", "iam", "forensics", "malware", "zero trust", "grc", "iso 27001",
    "vulnerability", "security engineer", "security analyst", "security architect",
    "it security", "information security", "sase", "ztna", "endpoint security",
    "dns security", "product security", "security incident response", "dlp",
}

# ── Layer 0: Persistent cache for Claude API calls ────────────────────────────
_api_cache: dict[str, bool] = {}
_CACHE_FILE = "/tmp/ai_filter_cache.json"


def _load_cache():
    global _api_cache
    try:
        if os.path.exists(_CACHE_FILE):
            with open(_CACHE_FILE) as f:
                _api_cache = json.load(f)
    except Exception:
        _api_cache = {}


def _save_cache():
    try:
        with open(_CACHE_FILE, "w") as f:
            json.dump(_api_cache, f)
    except Exception:
        pass


_load_cache()


def _title_key(title: str) -> str:
    return hashlib.md5(title.lower().strip().encode()).hexdigest()[:12]


# ── Layer 2 helpers ───────────────────────────────────────────────────────────

def _check_modern_title(title_lower: str) -> Optional[bool]:
    """Layer 2: Check expanded modern cybersec title patterns."""
    for pattern in MODERN_CYBERSEC_TITLES:
        if pattern in title_lower:
            return True
    return None


def _check_false_positive(title_lower: str, desc_lower: str = "") -> bool:
    """Layer 1: Return True if this is a FALSE POSITIVE (not cybersec)."""
    if any(re.search(pattern, title_lower) for pattern in NON_CYBER_ROLE_PATTERNS):
        return True
    if not any(sig in title_lower for sig in CYBER_TITLE_OVERRIDES):
        if any(re.search(pattern, title_lower) for pattern in CONTEXTUAL_NON_CYBER_ROLE_PATTERNS):
            return True

    full = title_lower + " " + desc_lower[:200]
    for pattern in FALSE_POSITIVE_PATTERNS:
        if re.search(pattern, full):
            # Double-check: if description has strong cyber signals, override FP
            if any(sig in desc_lower for sig in CYBER_CONTEXT_SIGNALS[:10]):
                return False
            return True
    return False


def _context_score(title_lower: str, desc_lower: str, tags_lower: str) -> int:
    """Layer 3: Count how many cyber context signals are present."""
    full = f"{title_lower} {desc_lower[:500]} {tags_lower}"
    return sum(1 for sig in CYBER_CONTEXT_SIGNALS if sig in full)


def _has_min_technical_signal(title_lower: str, desc_lower: str, tags_lower: str, min_hits: int = 1) -> bool:
    full = f"{title_lower} {desc_lower[:500]} {tags_lower}"
    title_hits = sum(1 for sig in _TITLE_TECH_GUARDS if sig in title_lower)
    full_hits = sum(1 for sig in CYBER_CONTEXT_SIGNALS if sig in full)
    return (title_hits + full_hits) >= min_hits


# ── Layer 4: Claude API (borderline cases only) ───────────────────────────────

def _classify_via_api(titles_batch: list[str]) -> dict[str, bool]:
    """
    Layer 4: Call Anthropic Claude Haiku API for borderline cases.
    Batched (max 20 titles per call) to minimize API cost.
    Only runs when ANTHROPIC_API_KEY is set (available in GitHub Actions).
    Results are cached to /tmp/ai_filter_cache.json to avoid re-classifying.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {}

    # Filter out already-cached titles
    uncached = [t for t in titles_batch if _title_key(t) not in _api_cache]
    if not uncached:
        return {t: _api_cache[_title_key(t)] for t in titles_batch if _title_key(t) in _api_cache}

    try:
        import urllib.request
        prompt = (
            "Classify each job title: is it primarily a cybersecurity role? "
            "Respond ONLY with a JSON object mapping title to true/false. "
            "No explanation.\n\nTitles:\n"
            + "\n".join(f'- "{t}"' for t in uncached[:20])
        )

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps({
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}]
            }).encode(),
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            text = data["content"][0]["text"]
            # Strip markdown fences if present
            text = re.sub(r"```json|```", "", text).strip()
            result = json.loads(text)

        # Cache results persistently
        for title, is_cyber in result.items():
            key = _title_key(title)
            _api_cache[key] = bool(is_cyber)
        _save_cache()

        log.info(f"[AI Filter] Classified {len(result)} borderline titles via Claude API")
        return result

    except Exception as e:
        log.warning(f"[AI Filter] API call failed: {e}")
        return {}


# ── Public API ────────────────────────────────────────────────────────────────

def classify_job(title: str, description: str = "", tags: str = "") -> tuple[bool | None, str]:
    """
    Main classification function.
    Returns (is_cybersec: bool | None, reason: str)
    
    None = borderline (queue for Layer 4 API if available)
    True = accept
    False = reject

    Layers:
    1. False positive exclusion (fast regex)
    2. Modern cybersec title patterns (keyword match)
    3. Context scoring (semantic signals)
    4. Claude Haiku API (borderline only, batched)
    """
    tl = title.lower().strip()
    dl = description.lower()[:1000]
    tagl = tags.lower() if isinstance(tags, str) else " ".join(str(t) for t in tags).lower()

    # Layer 1: Hard false positive exclusion
    if _check_false_positive(tl, dl):
        return False, "false_positive_pattern"

    # Layer 2: Modern cybersec title
    modern = _check_modern_title(tl)
    if modern is True:
        if _has_min_technical_signal(tl, dl, tagl, min_hits=1):
            return True, "modern_title_match"
        return None, "borderline:modern_without_technical_context"

    # Layer 3: Context scoring
    ctx_score = _context_score(tl, dl, tagl)
    if ctx_score >= 3:
        return True, f"context_signals:{ctx_score}"
    if ctx_score >= 1:
        return None, f"borderline:ctx={ctx_score}"

    return None, "no_signal"


def batch_classify_borderline(jobs: list) -> dict:
    """
    Takes a list of Job objects marked as borderline.
    Returns dict of job.unique_id → bool
    Uses Claude Haiku API if ANTHROPIC_API_KEY is set.
    Falls back to intelligence.classify_cyber_intent for offline mode.
    """
    # Try API path first
    if os.getenv("ANTHROPIC_API_KEY"):
        borderline_titles = list({
            job.title for job in jobs
            if hasattr(job, "title") and len(job.title) > 5
        })

        if not borderline_titles:
            return {}

        log.info(f"[AI Filter] Sending {len(borderline_titles)} borderline titles to Claude API...")
        api_results = _classify_via_api(borderline_titles)

        result = {}
        for job in jobs:
            if job.title in api_results:
                result[getattr(job, "unique_id", getattr(job, "url", ""))] = api_results[job.title]
        return result

    # Offline fallback: route through intelligence package
    try:
        from intelligence import classify_cyber_intent
        from intelligence._text import flatten_tags

        results: dict[str, bool] = {}
        for job in jobs:
            tags = flatten_tags(getattr(job, "tags", []) or [])
            decision = classify_cyber_intent(job)
            if decision is not None:
                uid = getattr(job, "unique_id", getattr(job, "url", ""))
                results[uid] = bool(decision.accept)
        return results
    except ImportError:
        return {}
