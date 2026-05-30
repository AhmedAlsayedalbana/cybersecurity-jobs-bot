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
    # STRICT: must have both "security/cyber" AND "intern/trainee/graduate".
    # Never match generic "intern" alone.
    "internships": [
        "cybersecurity intern", "cyber security intern", "security internship",
        "soc intern", "security trainee", "cybersecurity trainee",
        "information security trainee", "security graduate", "cybersecurity graduate",
        "entry-level cybersecurity", "entry level cybersecurity",
        "junior security analyst", "junior soc analyst",
        "junior penetration tester", "junior pentest",
    ],

    # ── Penetration Testing / Red Team ────────────────────────────────────────
    "pentest": [
        "penetration tester", "penetration testing", "pen tester", "pentester",
        "pentest", "red team", "red teamer", "red teaming",
        "offensive security", "offensive security analyst",
        "ethical hacker", "ethical hacking",
        "bug bounty", "vulnerability researcher", "exploit developer",
        "exploit development", "oscp", "gpen", "ctf",
    ],

    # ── SOC / Blue Team ───────────────────────────────────────────────────────
    "soc": [
        "soc analyst", "soc engineer", "soc manager", "soc lead",
        "soc operations",                              # ← FIX: "SOC Operations Specialist"
        "security operations center", "security operations analyst",
        "security operations engineer",
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
    ],

    # ── Application Security / DevSecOps ─────────────────────────────────────
    "appsec": [
        "application security", "appsec", "app sec",
        "devsecops", "dev sec ops", "devsec",
        "product security engineer", "product security analyst",
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
        "risk and compliance", "risk & compliance",
        "information security risk",
        "information security manager",    # ← FIX: common GRC leadership title
        "isms", "vcrm", "tprm",
        "ciso", "deputy ciso", "vp information security",
    ],

    # ── Security Engineering ──────────────────────────────────────────────────
    # FIXED: removed overly broad terms: "security consultant", "security specialist",
    # "security manager" — these match too many non-seceng roles.
    # Kept precise engineering/architecture titles only.
    "seceng": [
        "security engineer", "cybersecurity engineer",
        "information security engineer",
        "security architect", "cybersecurity architect",
        "security architecture engineer",
        "security automation engineer", "security automation",
        "security platform engineer", "security tools developer",
        "security software engineer",
        "iam engineer", "identity security engineer",
        "identity and access management engineer",
        "privileged access management", "pam engineer",
        "pki engineer", "cryptography engineer",
        "zero trust engineer", "zero trust architect",
        "detection engineering", "security detection engineer",
        "security operations engineer",  # engineering focus (not SOC analyst)
        "soc engineer",                  # engineering role within SOC
        "devsecops engineer",            # engineering focus (not AppSec analyst)
    ],
}

# ---------------------------------------------------------------------------
# Canonical cybersecurity role taxonomy
# ---------------------------------------------------------------------------

ROLE_TAXONOMY: dict[str, dict[str, object]] = {
    "soc": {
        "parent": "blue_team",
        "channel": "soc",
        "patterns": [
            "soc analyst", "soc engineer", "soc manager", "soc lead",
            "security operations center", "security operations analyst",
            "security operations engineer", "security monitoring analyst",
            "security monitoring engineer", "siem analyst", "siem engineer",
            "siem administrator", "l1 soc", "l2 soc", "l3 soc",
        ],
    },
    "blue_team": {
        "parent": "blue_team",
        "channel": "soc",
        "patterns": [
            "blue team", "blue teamer", "cyber defense analyst",
            "cyber defence analyst", "cyber defense engineer",
            "detection and response", "managed detection response", "mdr analyst",
        ],
    },
    "threat_intel": {
        "parent": "blue_team",
        "channel": "soc",
        "patterns": [
            "threat intelligence", "threat intelligence analyst",
            "threat intelligence engineer", "cyber threat intelligence",
            "cti analyst", "cti engineer", "threat analyst", "threat hunter",
            "threat hunting",
        ],
    },
    "incident_response": {
        "parent": "blue_team",
        "channel": "soc",
        "patterns": [
            "incident response", "incident response analyst",
            "incident response engineer", "incident responder", "ir analyst",
        ],
    },
    "dfir": {
        "parent": "blue_team",
        "channel": "soc",
        "patterns": [
            "dfir", "digital forensics", "digital forensic",
            "forensic analyst", "forensic investigator", "malware analyst",
            "malware analysis", "malware reverse engineer",
        ],
    },
    "detection_engineering": {
        "parent": "blue_team",
        "channel": "soc",
        "patterns": [
            "detection engineer", "detection engineering",
            "security detection engineer", "detection content engineer",
            "detection logic", "sigma rules", "yara rules",
        ],
    },
    "pentest": {
        "parent": "red_team",
        "channel": "pentest",
        "patterns": [
            "penetration tester", "penetration testing", "pen tester",
            "pentester", "pentest", "red team", "red teamer", "red teaming",
            "offensive security", "offensive security analyst",
            "ethical hacker", "ethical hacking", "bug bounty",
            "vulnerability researcher", "exploit developer",
            "exploit development", "oscp", "gpen", "ctf",
        ],
    },
    "appsec": {
        "parent": "application_security",
        "channel": "appsec",
        "patterns": [
            "application security", "appsec", "app sec", "secure code review",
            "secure coding", "sast", "dast", "iast", "owasp",
            "api security", "api security engineer", "web application security",
            "mobile app security", "burp suite", "checkmarx", "snyk",
        ],
    },
    "product_security": {
        "parent": "application_security",
        "channel": "appsec",
        "patterns": [
            "product security", "product security engineer",
            "product security analyst", "software security engineer",
            "software security analyst",
        ],
    },
    "devsecops": {
        "parent": "application_security",
        "channel": "appsec",
        "patterns": [
            "devsecops", "dev sec ops", "devsec", "devsecops engineer",
            "pipeline security", "ci/cd security", "container security engineer",
        ],
    },
    "cloudsec": {
        "parent": "cloud_security",
        "channel": "cloudsec",
        "patterns": [
            "cloud security", "cloud security engineer", "cloud security analyst",
            "cloud security architect", "cloud security consultant",
            "aws security", "azure security", "gcp security",
            "kubernetes security", "container security", "cspm", "cnapp",
            "ciem", "cloud native security", "cloud posture",
            "cloud infrastructure security", "cloud and infrastructure security",
            "cloud & infrastructure security", "wiz", "prisma cloud", "lacework",
        ],
    },
    "networksec": {
        "parent": "network_security",
        "channel": "networksec",
        "patterns": [
            "network security", "network security engineer",
            "network security analyst", "network security architect",
            "network security manager", "network security specialist",
            "network security consultant", "network and infrastructure security",
            "network & infrastructure security", "infrastructure security engineer",
            "infrastructure security analyst", "firewall engineer",
            "firewall administrator", "firewall analyst", "ids engineer",
            "ips engineer", "ids/ips", "intrusion detection",
            "intrusion prevention", "vpn engineer", "vpn administrator",
            "network defense", "perimeter security", "palo alto",
            "fortinet", "checkpoint", "cisco security", "sdwan security",
            "sd-wan security", "network access control", "nac engineer",
            "packet analysis", "network forensics", "traffic analysis",
            "ddos protection", "ddos mitigation", "waf engineer",
            "web application firewall",
        ],
    },
    "ot_ics": {
        "parent": "network_security",
        "channel": "networksec",
        "patterns": [
            "ot security", "ics security", "scada security",
            "operational technology security", "industrial security",
        ],
    },
    "grc": {
        "parent": "governance_risk_compliance",
        "channel": "grc",
        "patterns": [
            "grc", "grc analyst", "grc manager", "grc consultant",
            "governance risk compliance", "governance risk",
            "information security governance",
            "information security governance and risk",
            "it governance", "isms", "security policy",
        ],
    },
    "risk_management": {
        "parent": "governance_risk_compliance",
        "channel": "grc",
        "patterns": [
            "cyber risk", "cyber risk analyst", "cyber risk manager",
            "information security risk", "third party risk", "vendor risk",
            "tprm", "vcrm", "technology risk cyber",
        ],
    },
    "compliance": {
        "parent": "governance_risk_compliance",
        "channel": "grc",
        "patterns": [
            "compliance analyst", "compliance manager", "compliance officer",
            "iso 27001", "nist", "pci dss", "hipaa", "gdpr",
            "privacy officer", "privacy manager", "data protection officer",
        ],
    },
    "audit": {
        "parent": "governance_risk_compliance",
        "channel": "grc",
        "patterns": [
            "security auditor", "it auditor", "cyber auditor",
            "information security audit", "technology audit",
        ],
    },
    "iam": {
        "parent": "security_engineering",
        "channel": "seceng",
        "patterns": [
            "iam", "iam engineer", "iam analyst", "identity security engineer",
            "identity engineer", "identity and access management",
            "identity access management", "identity and access specialist",
            "identity access specialist", "access management engineer",
            "sailpoint", "okta engineer", "entra id", "azure ad",
        ],
    },
    "pam": {
        "parent": "security_engineering",
        "channel": "seceng",
        "patterns": [
            "pam", "pam engineer", "privileged access management",
            "privileged access", "cyberark", "beyondtrust",
        ],
    },
    "vulnerability_management": {
        "parent": "security_engineering",
        "channel": "seceng",
        "patterns": [
            "vulnerability management", "vulnerability management analyst",
            "vulnerability management engineer", "vulnerability analyst",
            "vulnerability assessment", "vulnerability remediation",
            "nessus", "qualys", "tenable",
        ],
    },
    "security_architecture": {
        "parent": "security_engineering",
        "channel": "seceng",
        "patterns": [
            "security architect", "cybersecurity architect",
            "information security architect", "security architecture",
            "zero trust architect", "zero trust engineer",
        ],
    },
    "security_engineering": {
        "parent": "security_engineering",
        "channel": "seceng",
        "patterns": [
            "security engineer", "cybersecurity engineer",
            "information security engineer", "security platform engineer",
            "security software engineer", "security tools developer",
            "pki engineer", "cryptography engineer", "cryptographer",
            "ai security analyst", "emerging tech security analyst",
        ],
    },
    "security_automation": {
        "parent": "security_engineering",
        "channel": "seceng",
        "patterns": [
            "security automation", "security automation engineer",
            "soar engineer", "security orchestration", "python security",
        ],
    },
    "technical_security_consulting": {
        "parent": "security_engineering",
        "channel": "seceng",
        "patterns": [
            "cybersecurity consultant", "security consultant",
            "security technical architect", "xsiam consultant",
            "cybersecurity presales architect",
            "presales cybersecurity architect",
            "pre-sales cybersecurity architect",
        ],
    },
}

ROLE_CLASSIFICATION_ORDER: list[str] = [
    "pentest",
    "appsec",
    "product_security",
    "devsecops",
    "cloudsec",
    "networksec",
    "ot_ics",
    "grc",
    "risk_management",
    "compliance",
    "audit",
    "soc",
    "blue_team",
    "threat_intel",
    "incident_response",
    "dfir",
    "detection_engineering",
    "iam",
    "pam",
    "vulnerability_management",
    "security_architecture",
    "security_automation",
    "technical_security_consulting",
    "security_engineering",
]

for _role_spec in ROLE_TAXONOMY.values():
    _channel = str(_role_spec["channel"])
    _patterns = list(_role_spec["patterns"])
    _bucket = DOMAIN_PATTERNS.setdefault(_channel, [])
    for _pattern in _patterns:
        if _pattern not in _bucket:
            _bucket.append(_pattern)

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
    "security monitoring", "vulnerability management", "edr", "xdr",
    "splunk", "qradar", "sentinel", "crowdstrike", "defender",
    "metasploit", "burp", "nessus", "qualys", "tenable",
    "mitre", "cis controls", "encryption", "hardening", "phishing",
    "cissp", "cism", "ceh", "security+",
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
]

GENERIC_TECH_REJECTS: list[str] = [
    "application support", "technical support", "help desk", "helpdesk",
    "desktop support", "system administrator", "network administrator",
    "salesforce administrator", "software engineer", "backend engineer",
    "frontend engineer", "full stack", "machine learning engineer",
    "product manager", "program manager", "project manager",
    "solutions architect", "solution architect", "business analyst",
    # ✅ v46: additional generic-tech false-positives seen in logs
    "data entry", "data analyst", "database administrator",
    "database developer", "mysql developer", "wordpress developer",
    "shopify developer", "mobile developer", "android developer",
    "ios developer", "ui developer", "ux designer", "graphic designer",
    "interior designer", "mechanical engineer", "electrical engineer",
    "civil engineer", "structural engineer", "chemical engineer",
    "nurse", "physician", "pharmacist", "medical", "clinical",
    "logistics coordinator", "supply chain", "warehouse",
    "driver", "delivery", "operations manager",
    "lab technician", "quality assurance engineer",
    "real estate", "property manager",
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
]

CYBER_TITLE_OVERRIDE_PATTERNS: list[str] = [
    "security architect", "cloud security architect", "network security architect",
    "application security", "devsecops", "security operations",
    "soc", "siem", "penetration", "pentest", "incident response",
    "identity and access management", "identity access management", "iam",
    "pam", "privileged access management", "vulnerability management",
    "security technical architect", "cybersecurity architect",
]
