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
from datetime import datetime
import config
import logging
import re

logger = logging.getLogger(__name__)


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

    @property
    def unique_id(self) -> str:
        title_norm   = self.title.lower().strip()
        company_norm = self.company.lower().strip()
        for noise in ["inc", "inc.", "ltd", "ltd.", "llc", "corp",
                      "corporation", "co.", "company", "gmbh", "ag", "sa", "pvt"]:
            company_norm = company_norm.replace(noise, "").strip()
        return f"{title_norm}|{company_norm}"

    @property
    def url_id(self) -> str:
        if self.url:
            clean = self.url.split("?utm")[0].split("&utm")[0]
            return clean.rstrip("/").lower()
        return ""

    @property
    def display_source(self) -> str:
        if self.original_source:
            return self.original_source
        return config.SOURCE_DISPLAY.get(self.source, self.source.title())

    @property
    def emoji(self) -> str:
        text = f"{self.title} {self.location} {_flatten_tags(self.tags)}".lower()
        for keyword, em in config.EMOJI_MAP.items():
            if keyword in text:
                return em
        return config.DEFAULT_EMOJI


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
    # Arabic — expanded
    "أمن معلومات", "أمن سيبراني", "اختبار اختراق", "أمن شبكات",
    "محلل أمن", "مهندس أمن", "متخصص أمن",
    "هوية الأمن", "الأمن السيبراني", "إدارة هوية",
]

# Core roles — checked against full text (title + description + tags)
CORE_ROLES = [
    "soc analyst", "soc engineer", "security operations engineer",
    "security operations analyst", "security operations center",
    "penetration tester", "pentester", "pentest",
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
]

WEAK_TERMS = ["security", "cyber", "protection", "defense"]


def _word_match(keyword: str, text: str) -> bool:
    kw = keyword.lower().strip()
    if " " in kw:
        return kw in text
    return bool(re.search(r"\b" + re.escape(kw) + r"\b", text))


def is_cybersec_job(job: "Job") -> bool:
    title_lower = job.title.lower().strip()
    text = f"{job.title} {job.description} {_flatten_tags(job.tags)}".lower()

    # Step 0: Title blacklist
    for kw in config.EXCLUDE_KEYWORDS:
        if _word_match(kw, title_lower):
            if any(role in title_lower for role in ["security", "cyber", "soc", "pentest", "infosec"]):
                continue
            logger.info(f"Job excluded (Blacklisted keyword in title): {job.title}")
            return False

    # Step 1: Title fast-path (no description needed)
    for pattern in SECURITY_TITLE_PATTERNS:
        if pattern in title_lower:
            return True

    # Step 2: Core roles in full text
    if any(role in text for role in CORE_ROLES):
        return True

    # Step 3: Weak signals + technical context
    if any(term in text for term in WEAK_TERMS):
        strong_context = [
            "siem", "soc", "edr", "xdr", "pentest", "vulnerability", "firewall",
            "ids", "ips", "threat", "splunk", "qradar", "sentinel",
            "crowdstrike", "defender", "wireshark", "metasploit", "burp", "owasp",
            "iso 27001", "nist", "cis", "iam", "pki", "encryption",
            "hardening", "zero trust", "cspm", "cnapp", "devsecops", "appsec",
            "malware", "forensic", "dfir", "incident", "phishing",
        ]
        if any(ctx in text for ctx in strong_context):
            return True

        # Egypt/Gulf: any "security" or "cyber" in title = pass (local market)
        if _is_in_egypt(job.location) or _is_in_gulf(job.location):
            if any(term in title_lower for term in ["security", "cyber", "حماية", "أمن"]):
                return True

        # LinkedIn sources: short posts with minimal context — be lenient
        if job.source in ("linkedin_hiring", "linkedin_posts", "linkedin_hr", "linkedin", "linkedin_hr_post"):
            if any(term in title_lower for term in ["security", "cyber", "soc", "grc", "network security"]):
                return True

    logger.info(f"Job excluded (No strong cyber context): {job.title}")
    return False


def passes_geo_filter(job: "Job") -> bool:
    remote_only_sources = {
        "remotive", "remoteok", "wwr", "workingnomads", "findwork", "reed",
        "himalayas", "jobicy", "arbeitnow",
    }
    if _is_in_egypt(job.location):
        return True
    if job.source in remote_only_sources:
        return True
    if job.source == "linkedin_hiring":
        return True  # location unreliable for hiring posts
    if job.source == "linkedin_hr_post":
        return True  # HR posts: location derived from search query, always valid
    if _is_remote(job):
        return True
    if _is_in_gulf(job.location):
        return True
    return False


def filter_jobs(jobs: list["Job"]) -> list["Job"]:
    filtered = []
    for job in jobs:
        if not job.title or not job.url:
            continue
        if not is_cybersec_job(job):
            continue
        if not passes_geo_filter(job):
            continue
        filtered.append(job)
    logger.info(f"Filtered {len(jobs)} jobs down to {len(filtered)}")
    return filtered
