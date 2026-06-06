"""
Job data model and filtering logic — v27

Geo rules:
  - Egypt:  all jobs pass (onsite + remote)
  - Remote: pass
  - Gulf:   pass
  - Rest:   remote only

v27 IMPROVEMENTS:
  - Title fast-path: if title contains a security pattern → pass immediately
    (fixes false negatives for "Security Program Manager", "Security Assurance Analyst" etc.)
  - linkedin_hiring source is lenient (posts have minimal context)
  - Egypt/Gulf: any "security" or "cyber" in title = pass
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timedelta
import config
import logging
import re
from job_intelligence import (
    classify_cyber_intent,
    classify_domain as classify_intelligence_domain,
    classify_geo as classify_intelligence_geo,
    classify_level as classify_intelligence_level,
    hard_reject_reason,
    has_strong_cyber_anchor,
    is_remote_job as intelligence_is_remote_job,
)
from linkedin_url_utils import (
    canonicalize_job_url,
    extract_linkedin_job_id,
    extract_linkedin_post_id,
    is_linkedin_source,
    is_valid_linkedin_canonical,
)

logger = logging.getLogger(__name__)


STRICT_RECENCY_SOURCES = {
    "linkedin",
    "linkedin_unified",
    "linkedin_li_at",
    "linkedin_hiring",
    "linkedin_posts",
    "linkedin_hr_post",
    "linkedin_egypt_arabic",
    "google_jobs",
    "google_intel",
    "freelancer",
    "mostaql",
    "khamsat",
    "fiverr",
    "upwork",
    # MENA boards stamp posted_date=now() so this is just a safety net
    "akhtaboot",
    "drjobpro",
    "forasna",
    "tanqeeb",
    "mena_boards",
    "jina_scraper",
}


def _flatten_tags(tags) -> str:
    if not tags:
        return ""
    flat = []
    for item in tags:
        if isinstance(item, list):
            flat.extend(str(i) for i in item)
        elif isinstance(item, dict):
            flat.append(str(item.get("name", item.get("label", ""))))
        else:
            flat.append(str(item))
    return " ".join(flat)


def _normalize_title_for_id(text: str) -> str:
    normalized = (text or "").lower().strip()
    normalized = re.sub(r"\s*[-–—]{1,2}\s*\d{1,3}\s*$", "", normalized)
    normalized = re.sub(r"\(\s*\d{1,3}\s*\)$", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


_SALARY_CODES = r"(?:USD|EUR|GBP|EGP|SAR|AED|QAR|KWD|BHD|OMR)"
_SALARY_SIGNS = r"(?:\$|€|£)"
_SALARY_UNIT = r"(?:hour|hr|day|week|month|mo|year|yr)"
_SALARY_RANGE_RE = re.compile(
    rf"(?i)\b(?:salary|compensation|pay|budget)?\s*[:\-]?\s*"
    rf"({_SALARY_SIGNS}|{_SALARY_CODES})\s*\d[\d,]*(?:\.\d+)?\s*"
    rf"(?:-|to|–)\s*"
    rf"(?:({_SALARY_SIGNS}|{_SALARY_CODES})\s*)?\d[\d,]*(?:\.\d+)?"
    rf"(?:\s*(?:/|per)\s*({_SALARY_UNIT}))?"
)
_SALARY_SINGLE_RE = re.compile(
    rf"(?i)\b(?:salary|compensation|pay|budget)?\s*[:\-]?\s*"
    rf"({_SALARY_SIGNS}|{_SALARY_CODES})\s*\d[\d,]*(?:\.\d+)?\+?"
    rf"(?:\s*(?:/|per)\s*({_SALARY_UNIT}))?"
)
_SALARY_TRAILING_CODE_RE = re.compile(
    rf"(?i)\b\d[\d,]*(?:\.\d+)?\s*(?:-|to|–)\s*\d[\d,]*(?:\.\d+)?\s*({_SALARY_CODES})"
    rf"(?:\s*(?:/|per)\s*({_SALARY_UNIT}))?"
)
_SALARY_SHORT_RATE_RE = re.compile(
    rf"(?i)\b({_SALARY_SIGNS})\s*\d[\d,]*(?:\.\d+)?\s*/\s*({_SALARY_UNIT})\b"
)


def extract_salary_from_text(text: str) -> str:
    """Extract a compact salary string from free text."""
    if not text:
        return ""
    raw = re.sub(r"\s+", " ", text).strip()
    for pattern in (_SALARY_RANGE_RE, _SALARY_SINGLE_RE, _SALARY_TRAILING_CODE_RE, _SALARY_SHORT_RATE_RE):
        m = pattern.search(raw)
        if m:
            return re.sub(r"\s+", " ", m.group(0)).strip(" .,:;|")
    return ""


@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str
    source: str
    salary: str = ""
    job_type: str = ""
    tags: list = field(default_factory=list)
    is_remote: bool = False
    original_source: str = ""
    posted_date: Optional[datetime] = None
    description: str = ""
    content_type: str = "job_listing"   # job_listing | hr_post
    origin_priority: int = 999
    source_key: str = ""
    # geo_hint: authoritative region derived from the search query that fetched this job.
    # Values: "egypt" | "gulf" | "global" | "" (unknown).
    # Set by scrapers that know their search geography (e.g. LinkedIn unified queries).
    # Used by classifier as a reliable tiebreaker ONLY when job.location is ambiguous.
    geo_hint: str = ""

    @property
    def unique_id(self) -> str:
        title_norm   = _normalize_title_for_id(self.title)
        company_norm = self.company.lower().strip()
        for noise in ["inc", "inc.", "ltd", "ltd.", "llc", "corp",
                      "corporation", "co.", "company", "gmbh", "ag", "sa", "pvt"]:
            company_norm = company_norm.replace(noise, "").strip()
        company_norm = re.sub(r"\s+", " ", company_norm)
        return f"{title_norm}|{company_norm}"

    @property
    def url_id(self) -> str:
        if not self.url:
            return ""
        # FIXED v38: Extract LinkedIn job ID if present — strongest dedup key.
        # /jobs/view/1234567890/ → "li_job_1234567890"
        # This ensures the same job fetched by 4 different LinkedIn fetchers
        # (linkedin, linkedin_hiring, linkedin_posts, linkedin_hr_hunter)
        # is always recognized as a duplicate, even if company/title differ slightly.
        canonical = self.canonical_url
        if not canonical:
            return ""
        job_id = extract_linkedin_job_id(canonical)
        if job_id:
            return f"li_job_{job_id}"
        post_id = extract_linkedin_post_id(canonical)
        if post_id:
            return f"li_post_{post_id}"
        return canonical.rstrip("/").lower()

    @property
    def canonical_url(self) -> str:
        return canonicalize_job_url(self.url)

    @property
    def display_source(self) -> str:
        if self.original_source:
            return self.original_source
        return config.SOURCE_DISPLAY.get(self.source, self.source.title())

    @property
    def dedup_key(self) -> str:
        return self.url_id or self.canonical_url or self.unique_id

    @property
    def is_hr_post(self) -> bool:
        return (self.content_type or "").lower() == "hr_post"

    @property
    def emoji(self) -> str:
        text = f"{self.title} {self.location} {_flatten_tags(self.tags)}".lower()
        for keyword, em in config.EMOJI_MAP.items():
            if keyword in text:
                return em
        return config.DEFAULT_EMOJI


@dataclass(slots=True)
class FilterDecision:
    accept: bool
    reason_code: str


# ── Geo helpers ───────────────────────────────────────────────

def _is_in_egypt(location: str) -> bool:
    loc = location.lower().strip()
    return any(p in loc for p in config.EGYPT_PATTERNS)

def _is_in_gulf(location: str) -> bool:
    loc = location.lower().strip()
    return any(p in loc for p in config.GULF_PATTERNS)

def _is_remote(job: "Job") -> bool:
    if job.is_remote:
        return True
    combined = f"{job.title} {job.location} {job.job_type} {_flatten_tags(job.tags)}".lower()
    return any(p in combined for p in config.REMOTE_PATTERNS)


_AGE_MINUTES_RE = re.compile(r"\b(\d{1,3})\s*(?:minute|minutes|min|mins|m)\s*ago\b", re.IGNORECASE)
_AGE_HOURS_RE = re.compile(r"\b(\d{1,3})\s*(?:hour|hours|hr|hrs|h)\s*ago\b", re.IGNORECASE)
_AGE_DAYS_RE = re.compile(r"\b(\d{1,3})\s*(?:day|days|d)\s*ago\b", re.IGNORECASE)
_AGE_WEEKS_RE = re.compile(r"\b(\d{1,2})\s*(?:week|weeks|w)\s*ago\b", re.IGNORECASE)


def _extract_age_hours_from_text(text: str) -> float | None:
    lowered = (text or "").lower()
    if not lowered:
        return None
    m = _AGE_MINUTES_RE.search(lowered)
    if m:
        return int(m.group(1)) / 60.0
    m = _AGE_HOURS_RE.search(lowered)
    if m:
        return float(int(m.group(1)))
    m = _AGE_DAYS_RE.search(lowered)
    if m:
        return float(int(m.group(1)) * 24)
    m = _AGE_WEEKS_RE.search(lowered)
    if m:
        return float(int(m.group(1)) * 24 * 7)
    return None


def _job_source_key(job: "Job") -> str:
    return ((getattr(job, "source_key", "") or getattr(job, "source", "") or "").strip().lower())


def is_recent_enough(
    job: "Job",
    *,
    max_age_hours: int = 48,
    strict_sources: set[str] | None = None,
) -> tuple[bool, str]:
    """
    True only for jobs strictly fresher than max_age_hours.
    For strict sources (LinkedIn/Google/Freelance), unknown age is rejected.
    """
    strict_sources = strict_sources or STRICT_RECENCY_SOURCES
    now = datetime.now()
    source_key = _job_source_key(job)
    is_strict_source = source_key in strict_sources or any(
        source_key.startswith(prefix) for prefix in ("linkedin", "google", "freelance")
    )

    posted = getattr(job, "posted_date", None)
    if posted:
        # Normalize timezone: strip tzinfo so naive - naive subtraction always works
        if getattr(posted, "tzinfo", None) is not None:
            from datetime import timezone
            posted = posted.astimezone(timezone.utc).replace(tzinfo=None)
        age_hours = (now - posted).total_seconds() / 3600.0
        if age_hours >= max_age_hours:
            return False, "reject_stale_posted_date"
        return True, "accept_recent_posted_date"

    age_text = " ".join([
        getattr(job, "title", "") or "",
        getattr(job, "description", "") or "",
        _flatten_tags(getattr(job, "tags", []) or []),
    ])
    inferred_hours = _extract_age_hours_from_text(age_text)
    if inferred_hours is not None:
        if inferred_hours >= max_age_hours:
            return False, "reject_stale_relative_age"
        return True, "accept_recent_relative_age"

    if is_strict_source:
        return False, "reject_unknown_age_strict_source"
    return True, "accept_unknown_age_non_strict_source"


# ── Classification patterns ───────────────────────────────────

# If the JOB TITLE ALONE contains one of these → it's definitely a cyber job.
# No description needed. Fixes false negatives for titles with no tags/description.
SECURITY_TITLE_PATTERNS = [
    "security analyst", "security engineer", "security specialist",
    "security consultant", "security manager", "security architect",
    "security officer", "security administrator", "security lead",
    "security researcher", "security operations", "security auditor",
    "security assurance", "security program", "security governance",
    "cybersecurity", "cyber security", "infosec", "information security",
    "soc analyst", "soc engineer", "soc manager", "soc lead", "soc specialist",
    "penetration tester", "pen tester", "pentester", "pentest",
    "penetration test", "penetration testing",
    "ethical hacker", "bug bounty", "red team", "blue team",
    "threat analyst", "threat hunter", "threat intelligence",
    "incident response", "incident responder", "dfir",
    "malware analyst", "malware researcher",
    "grc analyst", "grc specialist", "grc manager", "grc consultant",
    "appsec", "application security", "devsecops",
    "cloud security", "network security engineer",
    "vulnerability analyst", "vulnerability researcher", "vulnerability manager",
    "digital forensics", "forensic analyst", "detection engineer",
    # Detection & Response
    "detection & response", "detection and response",
    "detection & mitigation", "endpoint detection",
    "edr engineer", "edr analyst",
    # Identity & Access
    "identity and access management", "iam analyst", "iam specialist",
    "sailpoint", "privileged access", "access management",
    # ── v42: Modern cybersec titles ──────────────────────────────────────────
    # Trust & Safety / Abuse / Platform
    "trust and safety", "trust & safety",
    "abuse analyst", "abuse engineer", "abuse prevention",
    "platform integrity", "content integrity",
    "online safety engineer", "online safety analyst",
    # Cyber Defense variants
    "cyber defense", "cyber defence", "cyberdefense",
    "security automation", "security orchestration",
    "zero trust", "zero-trust",
    # Offensive variants
    "offensive security", "adversarial simulation",
    "purple team", "purple teamer",
    # Identity / PAM
    "identity security", "identity protection",
    "pam engineer", "pam analyst", "pam specialist",
    "privileged identity", "privileged access management",
    # Privacy-adjacent
    "data security analyst", "data security engineer",
    "privacy engineer", "security privacy",
    # Infrastructure Security
    "infrastructure security", "container security",
    "kubernetes security", "platform security",
    # Arabic — expanded
    "أمن معلومات", "أمن سيبراني", "اختبار اختراق", "أمن شبكات",
    "محلل أمن", "مهندس أمن", "متخصص أمن",
    "هوية الأمن", "الأمن السيبراني", "إدارة هوية",
    "الأمن السيبراني", "فريق أزرق", "فريق أحمر",
]

# Core roles — checked against full text (title + description + tags)
CORE_ROLES = [
    "soc analyst", "soc engineer", "security operations engineer",
    "security operations analyst", "security operations center",
    "penetration tester", "pentester", "pentest", "penetration test", "penetration testing",
    "appsec", "application security", "cloud security",
    "incident response", "incident responder",
    "threat intelligence", "threat hunter", "threat hunting", "threat analyst",
    "cyber threat intelligence", "cti analyst",
    "dfir", "digital forensics",
    "security architect", "ciso", "grc", "compliance analyst",
    "vulnerability", "ethical hacker", "blue team", "red team", "devsecops",
    "forensics", "malware", "cyber security", "cybersecurity", "infosec",
    "information security", "detection engineer", "security operations",
    "offensive security", "bug bounty", "exploit",
    "iam engineer", "identity access", "pki engineer", "cryptograph",
    "security consultant", "security specialist", "security officer",
    "security administrator", "security manager", "security lead",
    "security analyst", "security engineer", "security researcher",
    "security auditor", "it auditor", "data protection officer",
    "data protection manager", "data protection specialist", "data protection",
    # SOC tier roles (BO = Back Office, L1/L2/L3 = tier levels in SOC context)
    "bo l1 engineer", "bo l2 engineer", "bo l3 engineer",
    "engineer - security", "analyst - security", "manager - security",
]

WEAK_TERMS = ["security", "cyber", "protection", "defense"]

NON_TECH_CYBER_TITLES = [
    "business development", "sales", "account executive", "account manager",
    "customer success", "customer support", "marketing", "copywriter",
    "content writer", "recruiter", "talent acquisition", "hr ",
]

TECHNICAL_TITLE_ANCHORS = [
    "analyst", "engineer", "architect", "consultant", "specialist", "manager",
    "soc", "siem", "grc", "pentest", "penetration", "red team", "blue team",
    "incident", "dfir", "malware", "appsec", "devsecops", "cloud security",
    "network security", "information security", "cybersecurity", "infosec",
]


def _word_match(keyword: str, text: str) -> bool:
    kw = keyword.lower().strip()
    if " " in kw:
        return kw in text
    return bool(re.search(r"\b" + re.escape(kw) + r"\b", text))


def is_cybersec_job(job: "Job") -> bool:
    decision = classify_cyber_intent(job, use_llm=True)
    setattr(job, "cyber_intent_reason", decision.reason_code)
    setattr(job, "cyber_intent_confidence", decision.confidence)
    domain = classify_intelligence_domain(job)
    level = classify_intelligence_level(job)
    geo = classify_intelligence_geo(job)
    setattr(job, "cyber_domain", domain or "")
    setattr(job, "career_level", level)
    setattr(job, "geo_class", geo)
    if not decision.accept:
        logger.info(f"Job excluded ({decision.reason_code}): {job.title}")
    return decision.accept


def passes_geo_filter(job: "Job") -> bool:
    """
    v42: تحسين الفلترة الجغرافية
    - كل مصادر LinkedIn تعدي (الـ query بيحدد الموقع)
    - إضافة Remotive/Arbeitnow/WWR كـ remote-only sources
    - تحسين detection للمدن المصرية والخليجية
    """
    geo = classify_intelligence_geo(job)
    if geo in ("egypt", "ksa", "gulf_other", "remote"):
        return True

    geo_hint = (getattr(job, "geo_hint", "") or "").lower()
    if geo_hint in ("egypt", "gulf"):
        return True

    # Free APIs are global remote-friendly
    if job.source in ("remotive", "arbeitnow", "wwr", "jsearch_api"):
        if intelligence_is_remote_job(job) or _is_in_egypt(job.location) or _is_in_gulf(job.location):
            return True

    return False


_STRONG_ML_RESCUE_ANCHORS = {
    "cybersecurity", "cyber security", "information security", "infosec",
    "security engineer", "security analyst", "security architect", "security operations",
    "soc", "siem", "dfir", "incident response", "threat intelligence", "threat hunting",
    "grc", "iso 27001", "nist", "pci dss",
    "pentest", "penetration", "red team", "blue team", "offensive security",
    "application security", "appsec", "devsecops",
    "cloud security", "network security", "vulnerability", "malware",
    "iam", "identity and access", "identity access", "zero trust",
    "privileged access", "pam", "identity and access management",
    "sase", "ztna", "zero trust network access",
    "endpoint security", "dns security", "dns and endpoint security", "edr", "xdr",
    "product security", "security architecture", "security technical architect",
    "security governance", "security compliance", "security regulatory",
    "security incident response", "sirt", "csirt",
    "vulnerability research", "cve",
    "insider risk", "insider threat", "data loss prevention", "dlp",
    "it security", "information security", "infosec",
    "ot security", "ics security",
}

_ML_RESCUE_TITLE_BLOCKERS = {
    # Commercial
    "audio transcription", "transcription specialist", "investment analyst",
    "sales director", "sales manager", "business development", "account executive",
    "customer service", "claims assistant", "store manager", "marketing",
    "human resources", "recruitment", "front end", "frontend", "full stack",
    "software engineer", "software developer", "project manager",
    "interior designer", "mysql database developer", "database developer",
    "budget analyst", "quantity surveyor", "call center",
    # ✅ v46: false positives seen in logs
    "devops engineer", "site reliability", "cloud engineer", "infrastructure engineer",
    "data engineer", "data scientist", "machine learning engineer", "ml engineer",
    "backend engineer", "backend developer", "ios engineer", "android engineer",
    "rail telecommunication", "telecom engineer", "network engineer",
    "it manager", "it director", "head of information technology",
    "head of it", "it support", "system administrator", "sysadmin",
    "solutions engineer", "field engineer", "implementation engineer",
    "erp", "oracle", "sap", "salesforce", "sharepoint",
    # ✅ v46: block fake/test job titles
    "gilfoyle", "bertram", "silicon valley", "new hire:", "🎭",
}


def _count_cyber_anchor_hits(text: str) -> int:
    lowered = (text or "").lower()
    return sum(1 for anchor in _STRONG_ML_RESCUE_ANCHORS if anchor in lowered)


def _has_any_cyber_anchor(text: str) -> bool:
    return _count_cyber_anchor_hits(text) > 0


def _ml_rescue_guard(job: "Job", ml_prob: float = 1.0) -> tuple[bool, str]:
    """
    Guardrail before ML rescue:
      - block clearly non-cyber titles
      - require strong cyber anchors in title/context

    ✅ v47: Security-prefix bypass — titles starting with "security ", "cybersecurity ",
    etc. are not blocked by hard_reject_reason even if the suffix matches a generic tech
    term (e.g. "Security Software Engineer" → "software engineer" in GENERIC_TECH_REJECTS).
    This is now consistent with the fix in intelligence/intent.py hard_reject_reason().
    """
    full = " ".join([job.title or "", job.description or "", _flatten_tags(job.tags)])
    reject_reason = hard_reject_reason(job)
    if reject_reason:
        # Only block on hard_reject if it's NOT a security-prefixed title that was
        # misclassified by the generic-tech check. The intent.py fix already handles
        # this for the keyword filter; we mirror it here for defense-in-depth.
        title_lower = (job.title or "").lower()
        _SEC_PREFIXES = (
            "security ", "cybersecurity ", "cyber security ",
            "information security ", "appsec ", "devsecops ", "infosec ",
        )
        is_sec_prefixed = any(title_lower.startswith(p) for p in _SEC_PREFIXES)
        if not is_sec_prefixed or reject_reason not in (
            "reject_generic_tech_title", "reject_generic_solutions_architect"
        ):
            return False, reject_reason
    if has_strong_cyber_anchor(job) or _has_any_cyber_anchor(full):
        return True, "accept_ml_guard_central_anchor"
    if ml_prob > 0.85 and not _has_any_cyber_anchor(job.title):
        return False, "reject_ml_guard_missing_cyber_anchor"
    return False, "reject_ml_guard_missing_cyber_anchor"


def filter_jobs(jobs: list["Job"]) -> list["Job"]:
    """
    Local hybrid filter:
    Pass 1: deterministic cyber rules (title/context).
    Pass 2: local ML triage (hard_reject / candidate / high_confidence).
    """
    try:
        from ml_filter import triage_job
        ml_available = True
    except ImportError:
        ml_available = False

    accepted: list[Job] = []
    rejected: list[Job] = []

    for job in jobs:
        decision = FilterDecision(accept=False, reason_code="reject_unknown")
        canonical_url = canonicalize_job_url(job.url)
        if not job.title or not canonical_url:
            decision.reason_code = "reject_missing_title_or_url"
            setattr(job, "filter_reason", decision.reason_code)
            rejected.append(job)
            continue
        job.url = canonical_url

        # ✅ v46: Reject fake/garbage/nav titles early
        _title_lower = (job.title or "").lower().strip()
        _GARBAGE_TITLE_SIGNALS = [
            "title: just a moment",   # Cloudflare challenge pages
            "just a moment...",
            "🎭",                      # Fake Silicon Valley job generator
            "gilfoyle", "bertram gilfoyle",
            "new hire:", "new hire ",
            "jobs in uae", "jobs in saudi", "jobs in qatar",
            "jobs in dubai", "jobs in riyadh", "jobs in doha",
            "jobs in oman", "jobs in bahrain", "jobs in muscat",
            "search jobs", "popular search",
            "by country", "by city", "by category",
            "login", "sign in", "sign up",
            "cybersecjobs.io",
            "daily news digest",
            "add daily trend",
            "update safety",
        ]
        if any(sig in _title_lower for sig in _GARBAGE_TITLE_SIGNALS):
            decision.reason_code = "reject_garbage_title"
            setattr(job, "filter_reason", decision.reason_code)
            rejected.append(job)
            continue

        # ✅ v46: Reject titles that are clearly URL fragments or markdown links
        if _title_lower.startswith("[![") or _title_lower.startswith("http") or \
           (_title_lower.startswith("*") and "jobs" in _title_lower and "naukrigulf" in (job.url or "").lower()):
            decision.reason_code = "reject_nav_or_url_fragment"
            setattr(job, "filter_reason", decision.reason_code)
            rejected.append(job)
            continue

        if is_linkedin_source(job.source) and not is_valid_linkedin_canonical(job.url):
            logger.debug(f"Dropped LinkedIn job with invalid canonical URL: {job.url}")
            decision.reason_code = "reject_invalid_linkedin_url"
            setattr(job, "filter_reason", decision.reason_code)
            rejected.append(job)
            continue

        if not passes_geo_filter(job):
            decision.reason_code = "reject_geo_filter"
            setattr(job, "filter_reason", decision.reason_code)
            rejected.append(job)
            continue

        recent_ok, recent_reason = is_recent_enough(
            job,
            max_age_hours=config.MAX_JOB_AGE_HOURS,
            strict_sources=STRICT_RECENCY_SOURCES,
        )
        if not recent_ok:
            decision.reason_code = recent_reason
            setattr(job, "filter_reason", decision.reason_code)
            rejected.append(job)
            continue

        if not (job.salary or "").strip():
            salary_text = " ".join([
                job.title or "",
                job.description or "",
                _flatten_tags(job.tags),
            ])
            extracted_salary = extract_salary_from_text(salary_text)
            if extracted_salary:
                job.salary = extracted_salary

        keyword_result = is_cybersec_job(job)

        triage_label = "candidate"
        ml_prob = 0.5
        if config.ML_FILTER_ENABLED and ml_available:
            triage_label, ml_prob, _ = triage_job(job)
            if isinstance(job.tags, list):
                job.tags.append(f"ml_prob:{ml_prob:.2f}")
                job.tags.append(f"ml_label:{triage_label}")
                domain = getattr(job, "cyber_domain", "") or classify_intelligence_domain(job) or ""
                level = getattr(job, "career_level", "") or classify_intelligence_level(job)
                geo = getattr(job, "geo_class", "") or classify_intelligence_geo(job)
                if domain:
                    job.tags.append(f"cyber_domain:{domain}")
                job.tags.append(f"career_level:{level}")
                job.tags.append(f"geo_class:{geo}")

        if keyword_result:
            if triage_label == "hard_reject" and ml_prob < 0.35:
                decision.reason_code = "reject_keyword_ml_hard"
                setattr(job, "filter_reason", decision.reason_code)
                rejected.append(job)
                continue
            intent_reason = getattr(job, "cyber_intent_reason", "") or "accept_keyword_rule"
            decision = FilterDecision(True, intent_reason)
            setattr(job, "filter_reason", decision.reason_code)
            accepted.append(job)
            continue

        if config.ML_FILTER_ENABLED and ml_available:
            if triage_label == "high_confidence":
                guard_ok, guard_reason = _ml_rescue_guard(job, ml_prob)
                min_high = max(0.90, config.ML_MIN_PROB + 0.15)
                if guard_ok and ml_prob >= min_high:
                    logger.info(f"[ML Filter] High-confidence rescue: {job.title} (p={ml_prob:.2f})")
                    decision = FilterDecision(True, "accept_ml_high_confidence")
                    setattr(job, "filter_reason", decision.reason_code)
                    accepted.append(job)
                    continue
                logger.info(f"[ML Filter] Rescue blocked: {job.title} ({guard_reason}, p={ml_prob:.2f})")

            if triage_label == "candidate":
                guard_ok, guard_reason = _ml_rescue_guard(job, ml_prob)
                min_candidate = max(0.95, config.ML_MIN_PROB + 0.20)
                if guard_ok and ml_prob >= min_candidate:
                    logger.info(f"[ML Filter] Candidate rescue: {job.title} (p={ml_prob:.2f})")
                    decision = FilterDecision(True, "accept_ml_candidate")
                    setattr(job, "filter_reason", decision.reason_code)
                    accepted.append(job)
                    continue
                logger.info(f"[ML Filter] Candidate blocked: {job.title} ({guard_reason}, p={ml_prob:.2f})")

        decision.reason_code = "reject_no_strong_cyber_signal"
        setattr(job, "filter_reason", decision.reason_code)
        rejected.append(job)

    filtered = accepted
    rescued = sum(1 for j in filtered if str(getattr(j, "filter_reason", "")).startswith("accept_ml_"))
    logger.info(
        f"Filtered {len(jobs)} jobs down to {len(filtered)}"
        + (f" (ML rescued {rescued} anchored borderline titles)" if rescued > 0 else "")
    )
    return filtered
