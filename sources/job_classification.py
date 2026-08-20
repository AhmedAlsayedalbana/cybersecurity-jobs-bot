"""
Canonical job classification and evidence — v76

Rules (from the user's data-quality spec; fix-only, no new features):

1. primary_category is derived from TITLE + DESCRIPTION + TAGS with
   evidence strings.  One keyword can never be enough for Pentest.
2. Pentest / Red Team requires offensive-security evidence (multiple
   signals or an explicit offensive title).
3. Security Engineer => Security Engineering unless offensive evidence.
4. skills_with_evidence only contains strings found verbatim in the job's
   OWN source content (title/description/tags).  Never from queries,
   classifier vocabulary, company profiles, or category names.
5. No invented values: unknown category confidence 0.0, no skills,
   no employer guess, no status guess.
"""

from dataclasses import dataclass, field
import re
import logging

log = logging.getLogger(__name__)

# Ordered specificity: more specific domains first.  Each (category,
# evidence_regex, kind) entry is tested against the job text.  ``kind``
# marks where the evidence must appear for the evidence string to be
# credible: title-only evidence scores higher than body text.
CATEGORY_RULES = [
    # Offensive / Pentest — strict.  A single mention of "SIEM" etc. is
    # NEVER enough; the rule list below deliberately excludes defensive
    # keywords.
    ("Pentest / Red Team",
     r"(penetration\s+test|pentest|offensive\s+security|red\s+team|exploit|ethical\s+hack|bug\s+bounty|adversarial)",
     "offensive"),
    ("GRC / Risk & Compliance",
     r"(compliance|governance|risk\s+(and\s+|&\s+)?analysis|risk assessment|audit|iso\s*27001|pci|grc|gdpr|policy)",
     "governance"),
    ("AppSec",
     r"(application\s+security|appsec|owasp|sast|dast|secure\s+code|code\s+review|devsecops|vulnerability\s+(?:(?:assessment|management))|secure\s+development)",
     "appsec"),
    ("Cloud Security",
     r"(cloud\s+security|aws\s+security|azure\s+security|gcp\s+security|cspm|csp|cloud\s+posture)",
     "cloud"),
    ("Network Security",
     r"(network\s+security|firewall|fortinet|fortigate|palo\s+alto|cisco.*security|ids|ips|vlan|vpn\s+engineer)",
     "network"),
    ("IAM / Access Security",
     r"(identity\s+(?:and\s+|&\s+)?access|iam|pam|privileged\s+access|sailpoint|okta|identity\s+(?:security|management|protection))",
     "identity"),
    ("SOC / Threat / Incident Response",
     r"(soc|security\s+operations|incident\s+response|siem|threat\s+(?:intel|hunt|hunting)|edr|xdr|detection|monitoring|cybersecurity\s+analyst)",
     "defense"),
    ("Security Engineering",
     r"(security\s+(?:engineer|architect|specialist|consultant|program)|infosec|information\s+security|cybersecurity|cyber\s+security|blue\s+team)",
     "defense"),
]

# Offense-only evidence tokens (defensive keywords excluded on purpose)
_OFFENSIVE_TOKENS = re.compile(
    r"(penetration\s+test|pentest|pentester|offensive\s+security|red\s+team|exploit(?:ation)?|ethical\s+hack|bug\s+bounty|adversarial\s+simulation)",
    re.IGNORECASE,
)

_OFFENSIVE_TITLE_RE = re.compile(
    r"(penetration\s+test|pentest|pentester|offensive\s+security|red\s+team|ethical\s+hack)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class CategoryVerdict:
    primary_category: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    secondary_categories: list[str] = field(default_factory=list)


def _job_text(job) -> str:
    """Title + description + flattened tags from the job's OWN content."""
    tags = job.tags if isinstance(job.tags, list) else []
    flat = " ".join(str(t) for t in tags if not isinstance(t, (dict, list)))
    return f"{job.title or ''} {job.description or ''} {flat}".lower()


def _evidence_for(rule_regex: str, text: str) -> list[str]:
    pattern = re.compile(rule_regex, re.IGNORECASE)
    return [m.group(0) for m in pattern.finditer(text)][:6]


def classify_category(job) -> CategoryVerdict:
    """v76: evidence-based primary category.  Returns a CategoryVerdict.

    The primary category is the domain with the strongest TITLE-level
    evidence; body-only evidence can still win if no title signal exists.
    A category whose evidence contains no offense token can never be
    Pentest / Red Team.  Confidence grows with title evidence and with
    the number of independent signals, capped at 0.95 for title matches.
    """
    text = _job_text(job)
    title_lower = (job.title or "").lower()
    scored: list[tuple[float, str, list[str]]] = []

    for category, regex, kind in CATEGORY_RULES:
        ev = _evidence_for(regex, text)
        if not ev:
            continue
        in_title = bool(re.search(regex, title_lower))
        base = 0.80 if in_title else 0.45
        n_signals = min(len(set(m.split()[0] for m in ev)), 4)
        conf = min(0.95, base + 0.05 * n_signals + (0.10 if in_title else 0.0))
        # Pentest guard: without offense evidence the category can never be
        # Pentest — single defensive keywords (SIEM/SOC/Fortinet/IAM) are
        # explicitly excluded by the rule table above.
        if category == "Pentest / Red Team" and not _OFFENSIVE_TOKENS.search(text):
            continue
        scored.append((conf, category, ev))

    if not scored:
        return CategoryVerdict("Security Engineering", 0.0, [], [])

    scored.sort(key=lambda t: -t[0])
    primary_conf, primary_cat, primary_ev = scored[0]

    # v76 guard (spec points 2/14): a Pentest primary category can only win
    # when the job's OWN CONTENT (description/tags) carries offensive
    # evidence.  A title-only offensive signal (e.g. a bare "Penetration
    # Tester" title whose description is purely defensive — SIEM, firewall,
    # monitoring) may never promote the role to Pentest: title tokens alone
    # are exactly the single-keyword case the spec bans.  The title still
    # raises confidence when body evidence exists.
    body_text = f"{job.description or ''} {' '.join(str(t) for t in (job.tags or []))}".lower()
    if primary_cat == "Pentest / Red Team" and not _OFFENSIVE_TOKENS.search(body_text):
        # Demote to the strongest defensive domain present; Security
        # Engineering is the honest fallback.
        defensive = [(conf, cat, ev) for conf, cat, ev in scored
                     if cat != "Pentest / Red Team"]
        if defensive:
            primary_conf, primary_cat, primary_ev = defensive[0]
        else:
            primary_cat = "Security Engineering"
            primary_conf = 0.0
            primary_ev = []

    # Secondary = next distinct domain with real evidence (affinity only)
    secondaries = [c for _, c, _ in scored[1:3] if c != primary_cat]

    return CategoryVerdict(primary_cat, round(primary_conf, 2),
                           [f"{kind}: {m}" for m in primary_ev][:6],
                           secondaries)


# ── Source-backed skills ─────────────────────────────────────────

_SKILL_PATTERNS = [
    ("SIEM", r"\bsiem\b"),
    ("Splunk", r"\bsplunk\b"),
    ("QRadar", r"\bqradar\b"),
    ("Sentinel", r"\bmicrosoft\s+sentinel\b|\bsentinel\b(?!\s+(health|dental))"),
    ("Firewall", r"\bfirewall(?:s)?\b"),
    ("Fortinet", r"\bfortinet\b|\bfortigate\b"),
    ("Palo Alto", r"\bpalo\s+alto\b"),
    ("Cisco", r"\bcisco\b"),
    ("CrowdStrike", r"\bcrowdstrike\b|\bfalcon\b(?=\s+(?:endpoint|agent|edr))"),
    ("EDR", r"\bedr\b"),
    ("XDR", r"\bxdr\b"),
    ("IAM", r"\biam\b|\bidentity\s+(?:and\s+|&\s+)?access\b"),
    ("SailPoint", r"\bsailpoint\b"),
    ("Okta", r"\bokta\b"),
    ("AWS", r"\baws\b"),
    ("Azure", r"\bazure\b"),
    ("GCP", r"\bgcp\b"),
    ("Burp Suite", r"\bburp\s+(suite|professional|community)\b"),
    ("Metasploit", r"\bmetasploit\b"),
    ("OWASP", r"\bowasp\b"),
    ("Python", r"\bpython\b"),
    ("Bash", r"\bbash\b"),
    ("Linux", r"\blinux\b"),
    ("Incident Response", r"\bincident\s+response\b"),
    ("Threat Hunting", r"\bthreat\s+hunt(?:ing)?\b"),
    ("Vulnerability Assessment", r"\bvulnerability\s+assessment\b"),
    ("Penetration Testing", r"\bpenetration\s+(?:test(?:ing)?|tests?)\b|\bpentest(?:ing)?\b"),
    ("Compliance", r"\b(?:compliance|iso\s*27001|pci|soc\s*2|gdpr)\b"),
    ("Forensics", r"\b(?:forensic|dfir)\b"),
    ("DLP", r"\bdlp\b"),
    ("MITRE ATT&CK", r"\bmitre\b|\batt&ck\b"),
    ("Arabic Security Roles", r"أمن\s+(?:المعلومات|السيبراني|شبكات)|اختبار\s+اختراق"),
]
_SKILL_RES = [(name, re.compile(regex, re.IGNORECASE)) for name, regex in _SKILL_PATTERNS]


def extract_skills_with_evidence(job, max_skills: int = 6) -> dict[str, list[str]]:
    """v76: skills ONLY from the job's own content (title/description/tags).

    Never consults queries, classifier vocabulary, company profiles,
    metadata, or category names.  Unknown skills are never invented.
    Returns {skill_name: [evidence strings]}.
    """
    text = _job_text(job)
    result: dict[str, list[str]] = {}
    for name, pattern in _SKILL_RES:
        matches = [m.group(0) for m in pattern.finditer(text)][:2]
        if matches:
            result[name] = [m for m in matches]
        if len(result) >= max_skills:
            break
    return result


def normalize_category_for_routing(category: str) -> str:
    return category or "Security Engineering"


__all__ = [
    "CategoryVerdict",
    "classify_category",
    "extract_skills_with_evidence",
    "normalize_category_for_routing",
]
