"""
intelligence/patterns.py
========================
Single source of truth for all keyword and regex patterns used across
the intelligence pipeline. No logic lives here — only constants.

Rules:
  • Add / remove keywords here.
  • All other modules import from this module; they must NOT define patterns locally.
  • Patterns that require config values (e.g. EGYPT_PATTERNS from config.py) are
    imported at call-site from config, not re-declared here.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Geo patterns (static / independent of config)
# ---------------------------------------------------------------------------

KSA_PATTERNS: frozenset[str] = frozenset({
    "saudi", "saudi arabia", "ksa", "riyadh", "jeddah", "dammam",
    "khobar", "mecca", "makkah", "madinah", "medina", "neom",
})

GULF_OTHER_PATTERNS: frozenset[str] = frozenset({
    "uae", "united arab emirates", "dubai", "abu dhabi", "sharjah",
    "qatar", "doha", "kuwait", "kuwait city", "bahrain", "manama",
    "oman", "muscat",
})

# ---------------------------------------------------------------------------
# Domain keyword groups
# ---------------------------------------------------------------------------

DOMAIN_PATTERNS: dict[str, list[str]] = {
    # ── Internships ───────────────────────────────────────────────────────────
    # STRICT: must have both "security/cyber" AND "intern/trainee/graduate/junior".
    # Never match generic "intern" alone.
    "internships": [
        # Compound intern/trainee keywords
        "cybersecurity intern", "cyber security intern", "security internship",
        "cybersecurity internship", "cyber intern",
        "soc intern", "security trainee", "cybersecurity trainee",
        "information security trainee", "security graduate", "cybersecurity graduate",
        "cyber security graduate", "security scholarship",
        # Entry-level compound keywords
        "entry-level cybersecurity", "entry level cybersecurity",
        "entry-level security", "entry level security",
        "entry level cyber", "entry-level cyber",
        # Junior-specific compound keywords
        "junior security analyst", "junior soc analyst",
        "junior penetration tester", "junior pentest",
        "junior cybersecurity", "junior cyber security",
        "junior information security", "junior infosec",
        "junior security engineer", "junior security specialist",
        # Fresh grad / new grad
        "fresh graduate security", "graduate security program",
        "new grad cybersecurity", "new grad security",
    ],

    # ── Penetration Testing / Red Team ────────────────────────────────────────
    "pentest": [
        "penetration tester", "penetration testing", "pen tester", "pentester",
        "pentest", "red team", "red teamer", "red teaming",
        "offensive security", "offensive security analyst",
        "ethical hacker", "ethical hacking",
        "bug bounty", "vulnerability researcher", "exploit developer",
        "exploit development", "oscp", "gpen", "ctf",
        "اختبار اختراق", "مختبر اختراق", "مهندس اختبار اختراق",
    ],

    # ── SOC / Blue Team ───────────────────────────────────────────────────────
    "soc": [
        # ✅ v55: bare "security analyst" / "cyber analyst" / "phishing analyst"
        # were falsely rejected — they are the most common cybersec titles.
        "security analyst", "cyber analyst", "phishing analyst",
        "soc analyst", "soc engineer", "soc manager", "soc lead",
        "soc operations",                              # ← FIX: "SOC Operations Specialist"
        "security operations center", "security operations analyst",
        "security operations engineer",
        # ✅ v47: CSOC = Cyber Security Operations Center — was silently failing
        "csoc analyst", "csoc engineer", "csoc manager", "csoc",
        "siem analyst", "siem administrator", "siem engineer",
        "threat analyst", "threat hunter", "threat hunting",
        "incident response analyst", "incident response engineer",
        "incident responder", "ir analyst",
        "blue team", "blue teamer",
        "dfir", "digital forensics", "malware analyst",
        "detection engineer", "detection and response",
        "global soc", "cyber defense analyst", "cyber defence analyst",
        "cyber threat intelligence", "cti analyst",
        "threat intelligence analyst", "threat intelligence engineer",
        "threat intelligence researcher", "threat researcher",
        "security researcher", "vulnerability researcher",
        "malware researcher", "cyber threat researcher",
        # ✅ v47: Embedded detection / insider threat
        "embedded detection analyst", "insider threat analyst",
        "security monitoring analyst", "edr analyst",
        "محلل soc", "محلل مركز العمليات الأمنية", "محلل عمليات الأمن",
        "محلل أمن سيبراني", "محلل الأمن السيبراني",
    ],

    # ── Application Security / DevSecOps ─────────────────────────────────────
    "appsec": [
        "application security", "appsec", "app sec",
        "devsecops", "dev sec ops", "devsec",
        "product security", "product security engineer", "product security analyst",
        "product security manager", "application security manager",
        "secure code review", "secure coding",
        "sast", "dast", "iast",
        "api security engineer", "api security analyst",
        "software security engineer", "software security analyst",
        "mobile app security", "web application security",
        "owasp", "burp suite", "checkmarx", "snyk",
    ],

    # ── Cloud & Infrastructure Security ──────────────────────────────────────
    # FIXED: removed "infrastructure security" — too ambiguous, grabbed network jobs.
    # "cloud & infrastructure" / "cloud and infrastructure" go here (cloud-first).
    # Pure "infrastructure security" (without cloud) goes to networksec.
    "cloudsec": [
        "cloud security", "cloud security engineer", "cloud security analyst",
        "cloud security architect", "cloud security consultant",
        "aws security", "azure security", "gcp security",
        "sase", "ztna", "zero trust network access",
        "kubernetes security", "container security",
        "cspm", "cnapp", "ciem",
        "cloud native security", "cloud posture",
        "cloud infrastructure security",
        "cloud and infrastructure security",   # ← FIX: "Cloud & Infrastructure Security Analyst"
        "cloud & infrastructure security",     # ← FIX
        "wiz", "prisma cloud", "lacework",
    ],

    # ── Network Security ──────────────────────────────────────────────────────
    # FIXED: added "network and infrastructure security" / "network & infrastructure"
    # to capture those titles correctly here instead of cloudsec.
    "networksec": [
        "network security engineer", "network security analyst",
        "network security architect", "network security manager",
        "network security specialist", "network security consultant",
        "network and infrastructure security", "network & infrastructure security",
        "infrastructure security engineer", "infrastructure security analyst",
        "firewall engineer", "firewall administrator", "firewall analyst",
        "ids engineer", "ips engineer", "ids/ips",
        "intrusion detection", "intrusion prevention",
        "vpn engineer", "vpn administrator",
        "network defense", "network defence",
        "perimeter security",
        "palo alto networks engineer", "fortinet engineer",
        "cisco security engineer", "checkpoint engineer",
        "sdwan security", "sd-wan security",
        "network access control", "nac engineer",
        "dns security", "dns and endpoint security",
        "packet analysis", "network forensics", "traffic analysis",
        "ddos protection", "ddos mitigation",
        "waf engineer", "web application firewall engineer",
        "ot security", "ics security", "scada security",
        "industrial security",
    ],

    # ── GRC / Compliance ──────────────────────────────────────────────────────
    "grc": [
        "grc", "grc analyst", "grc manager", "grc consultant",
        "governance risk compliance", "governance risk",
        "it governance", "information security governance",
        "information security governance and risk",
        "compliance analyst", "compliance manager", "compliance officer",
        "security auditor", "it auditor", "cyber auditor",
        "iso 27001", "nist", "pci dss", "hipaa", "gdpr",
        "data protection officer", "privacy officer", "privacy manager",
        "third party risk", "vendor risk", "cyber risk analyst",
        "cyber risk manager", "security policy analyst",
        "security policy manager",
        "security compliance", "security regulatory",
        "data loss prevention", "dlp", "insider risk", "insider threat",
        "risk and compliance", "risk & compliance",
        "information security risk",
        "information security manager",    # ← FIX: common GRC leadership title
        "isms", "vcrm", "tprm",
        "ciso", "deputy ciso", "vp information security",
        # ✅ v55: governance-titled leadership roles
        "security governance", "security governance manager",
        "information security governance manager",
    ],

    # ── Security Engineering ──────────────────────────────────────────────────
    # FIXED: removed overly broad terms: "security consultant", "security specialist",
    # "security manager" — these match too many non-seceng roles.
    # Kept precise engineering/architecture titles only.
    "seceng": [
        "security engineer", "cybersecurity engineer",
        "it security analyst", "it security engineer",
        "information security engineer",
        "security architect", "cybersecurity architect", "security technical architect",
        "security architecture engineer",
        "security automation engineer", "security automation",
        "security platform engineer", "security tools developer",
        "security software engineer",
        "trust and safety", "trust & safety", "abuse analyst",
        "abuse engineer", "abuse prevention", "content integrity",
        "platform integrity", "platform trust", "policy enforcement",
        "online safety", "privacy engineer", "data security engineer",
        "data security analyst", "purple team", "purple teamer",
        "iam engineer", "identity security engineer",
        "identity and access", "identity access management",
        "identity and access management", "identity and access management engineer",
        "privileged access management", "pam engineer",
        "pki engineer", "cryptography engineer",
        "sase engineer", "sase architect", "sase subject matter expert",
        "zero trust engineer", "zero trust architect",
        "endpoint security", "edr", "xdr",
        "detection engineering", "security detection engineer",
        "security incident response", "sirt", "csirt",
        "vulnerability research", "cve",
        "security operations engineer",  # engineering focus (not SOC analyst)
        "soc engineer",                  # engineering role within SOC
        "devsecops engineer",            # engineering focus (not AppSec analyst)
        # ✅ v47: Software Supply Chain Security (GitLab SSCS team)
        "software supply chain security", "supply chain security",
        "sscs", "ai governance", "ai security",
        # ✅ v47: Workload & cloud security engineering
        "cloud workload security", "security analytics",
        "behavioral security", "security data",
        # ✅ v47: Security business/program roles
        "security business enablement", "security program manager",
        # ✅ v55: bare "security engineering" / "security project manager"
        "security engineering", "security engineering manager",
        "security project manager",
        # ✅ v47: Staff-level security platform engineers
        "security platform and data", "security platform",
        "مهندس أمن سيبراني", "مهندس الأمن السيبراني", "مهندس أمن المعلومات",
        "أمن المعلومات", "الأمن السيبراني",
    ],
}

# Flat list of all strong title signals (excluding ambiguous standards)
STRONG_TITLE_PATTERNS: list[str] = [
    pattern
    for domain_patterns in DOMAIN_PATTERNS.values()
    for pattern in domain_patterns
    if pattern not in {"nist", "gdpr", "pci dss", "owasp"}
]

# Broad context hits (title + description)
CYBER_CONTEXT_PATTERNS: list[str] = sorted(set(STRONG_TITLE_PATTERNS + [
    "cybersecurity", "cyber security", "information security", "infosec",
    "threat intelligence researcher", "threat researcher", "security researcher",
    "security monitoring", "vulnerability management", "edr", "xdr",
    "iam", "pam", "identity and access", "identity access management",
    "sase", "ztna", "zero trust", "endpoint security", "dns security",
    "product security", "application security", "security architecture",
    "security incident response", "sirt", "csirt", "cve",
    "security compliance", "security regulatory", "dlp", "data loss prevention",
    "insider risk", "insider threat", "it security",
    "splunk", "qradar", "sentinel", "crowdstrike", "defender",
    "metasploit", "burp", "nessus", "qualys", "tenable",
    "mitre", "cis controls", "encryption", "hardening", "phishing",
    "cissp", "cism", "ceh", "security+",
    "أمن سيبراني", "الأمن السيبراني", "أمن المعلومات", "اختبار اختراق",
]))

# ---------------------------------------------------------------------------
# Hard-reject keyword groups
# ---------------------------------------------------------------------------

COMMERCIAL_HARD_REJECTS: list[str] = [
    "business development", "sales account", "account executive",
    "account manager", "sales manager", "sales engineer", "pre-sales",
    "presales", "customer success", "customer support", "client manager",
    "marketing", "copywriter", "content writer", "recruiter",
    "talent acquisition", "human resources", "hr assistant",
    "legal counsel", "legal specialist", "contract specialist",
    "contract manager", "legal advisor", "corporate counsel",
    "attorney", "paralegal", "legal & contract",
    # ✅ v46: additional commercial false-positives seen in logs
    "sales director", "regional sales", "channel sales",
    "inside sales", "enterprise sales", "solution sales",
    "customer service", "service desk", "call center",
    "customer experience", "client success",
]

PHYSICAL_HARD_REJECTS: list[str] = [
    "security guard", "security officer", "security supervisor",
    "security agent", "physical security", "loss prevention",
    "event security", "building security", "aviation security",
    "fire safety", "security systems",
    # ✅ v46: additional physical-security false-positives
    "security patrol", "site security", "safety officer",
    "safety engineer", "fire marshal", "security screener",
    "access control officer", "surveillance officer",
]

BUSINESS_RISK_REJECTS: list[str] = [
    "credit risk", "business risk", "retail risk", "financial risk",
    "market risk", "operational risk", "enterprise risk",
    "risk specialist", "risk consultant",
    # ✅ v46: additional business/finance false-positives
    "investment analyst", "portfolio manager", "financial advisor",
    "insurance analyst", "actuarial", "loan officer",
    "budget analyst", "quantity surveyor", "procurement",
    "financial controller", "treasury manager", "internal auditor",
    "audit manager", "auditor", "continuous monitoring",
]

GENERIC_TECH_REJECTS: list[str] = [
    "application support", "technical support", "help desk", "helpdesk",
    "desktop support", "system administrator", "network administrator",
    "salesforce administrator", "software engineer", "backend engineer",
    "frontend engineer", "full stack", "machine learning engineer",
    "product manager", "program manager", "project manager",
    "solutions architect", "solution architect", "business analyst",
    "delivery manager", "scrum master", "agile coach",
    # ✅ v46: additional generic-tech false-positives seen in logs
    "data entry", "data analyst", "database administrator",
    "database developer", "mysql developer", "wordpress developer",
    "shopify developer", "mobile developer", "android developer",
    "ios developer", "ui developer", "ux designer", "graphic designer",
    "interior designer", "mechanical engineer", "electrical engineer",
    "civil engineer", "structural engineer", "chemical engineer",
    "nurse", "physician", "pharmacist", "medical", "clinical",
    "logistics coordinator", "warehouse",
    "delivery driver", "food delivery", "last mile delivery",  # ✅ v47: was "delivery" — too broad, caught "Continuous Delivery"
    "operations manager",
    "lab technician", "quality assurance engineer",
    "real estate", "property manager",
    "network team leader", "wan management",
    "professional, information technology",
    "managing consultant strategy transformation",
    "managing consultant digital transformation",
    "cabin crew", "student marketeer", "lead generation",
    # ✅ v47: "supply chain" removed — too broad, caught "Software Supply Chain Security" (GitLab SSCS team)
    # Use more specific rejects below:
    "supply chain analyst", "supply chain coordinator", "supply chain manager",
    "logistics manager", "procurement manager",
]

# ---------------------------------------------------------------------------
# Seniority regexes (compiled once at import time)
# ---------------------------------------------------------------------------

ENTRY_RE: re.Pattern = re.compile(
    r"\b(?:intern|internship|trainee|graduate|fresh grad|fresh graduate|new grad|"
    r"entry[-\s]?level|0-1 years?|0-2 years?|1-2 years?)\b",
    re.IGNORECASE,
)

JUNIOR_RE: re.Pattern = re.compile(r"\bjunior\b", re.IGNORECASE)

MID_RE: re.Pattern = re.compile(
    r"\b(?:mid|middle|intermediate|associate)\b", re.IGNORECASE
)

SENIOR_RE: re.Pattern = re.compile(
    r"\b(?:senior|sr\.?|lead|manager|principal|staff|head|director|vp|chief|ciso)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Cyber override patterns (used in hard_reject overrides)
# ---------------------------------------------------------------------------

CYBER_RISK_OVERRIDE_PATTERNS: list[str] = [
    "cyber risk", "third party risk", "information security risk",
    "technology risk cyber", "security risk", "grc", "iso 27001",
    "security compliance", "security regulatory", "insider risk",
    "data loss prevention", "dlp",
]

CYBER_TITLE_OVERRIDE_PATTERNS: list[str] = [
    "security architect", "cloud security architect", "network security architect",
    "application security", "devsecops", "security operations",
    "soc", "siem", "penetration", "pentest", "incident response",
    "it security", "information security", "identity and access",
    "identity access management", "privileged access", "pam",
    "sase", "ztna", "zero trust", "endpoint security", "dns security",
    "product security", "security technical architect", "vulnerability research",
    "security incident response", "sirt", "csirt",
    # ✅ v47: Security-prefixed technical roles blocked by GENERIC_TECH_REJECTS
    # e.g. "Security Software Engineer", "Security Program Manager"
    "security software engineer", "security backend engineer",
    "security program manager", "security platform engineer",
    "security product manager", "security engineering manager",
    "security data engineer", "security machine learning",
    # ✅ v55: bare compound terms (without a manager/engineer suffix)
    "security program", "security engineering", "security governance",
    "software supply chain",
    # ✅ v47: Role-suffix context that makes a title clearly security-focused
    "corporate security", "detection and response", "behavioral security",
    "message security", "security products", "security privacy",
    "cloud workload security", "supply chain security",
    "software supply chain security",
    "security analytics", "security analytics infrastructure",
    "security business enablement",
    # ✅ v47: AI + security compound titles
    "ai security", "ai security researcher", "genai security",
    # ✅ v47: Trust & Safety (has meaningful overlap with security roles)
    "trust and safety", "trust & safety",
]

# Security title prefix bypass — titles starting with these strings are NOT
# subject to GENERIC_TECH_REJECTS even if the suffix is a generic tech role.
# e.g. "Security Software Engineer II" starts with "security " → bypass.
SECURITY_TITLE_PREFIXES: tuple[str, ...] = (
    "security ",
    "cybersecurity ",
    "cyber security ",
    "information security ",
    "appsec ",
    "devsecops ",
    "infosec ",
)
