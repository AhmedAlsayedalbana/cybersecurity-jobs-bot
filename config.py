"""
Configuration for Cybersecurity Jobs Telegram Bot.
Specialized 100% for Cybersecurity roles.
Priority: Egypt 🇪🇬 → Remote 🌍 → Gulf (optional)
"""

import os

# ─── Telegram ───────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_GROUP_ID  = os.getenv("TELEGRAM_GROUP_ID", "")
TELEGRAM_SEND_DELAY = 3  # seconds between messages

# ─── Community Topics ────────────────────────────────────────
CHANNELS = {
    "general": {
        "thread_env": "TOPIC_GENERAL",
        "name": "🔐 All Cybersecurity Jobs",
        "match": "ALL",
    },
    "egypt": {
        "thread_env": "TOPIC_EGYPT",
        "name": "🇪🇬 Egypt Jobs",
        "match": "GEO_EGYPT",
    },
    "remote": {
        "thread_env": "TOPIC_REMOTE",
        "name": "🌍 Remote Jobs",
        "match": "REMOTE",
    },
    "pentest": {
        "thread_env": "TOPIC_PENTEST",
        "name": "🕵️ Penetration Testing & Red Team",
        "keywords": [
            "penetration tester", "penetration testing", "pen tester", "pen testing",
            "pentest", "pentesting", "ethical hacker", "ethical hacking",
            "red team", "red teamer", "red teaming", "offensive security",
            "bug bounty", "vulnerability researcher", "exploit developer",
            "exploit development", "oscp", "ceh", "gpen",
        ],
    },
    "soc": {
        "thread_env": "TOPIC_SOC",
        "name": "🖥️ SOC & Threat Analysis",
        "keywords": [
            "soc analyst", "soc engineer", "soc manager", "soc lead",
            "security operations center", "security operations",
            "threat analyst", "threat intelligence", "threat hunter", "threat hunting",
            "incident responder", "incident response", "ir analyst",
            "blue team", "cyber threat intelligence", "cti analyst",
            "dfir", "digital forensics", "malware analyst",
            "siem analyst", "security monitoring",
        ],
    },
    "appsec": {
        "thread_env": "TOPIC_APPSEC",
        "name": "🛡️ Application Security",
        "keywords": [
            "application security", "appsec", "app sec",
            "secure code review", "sast", "dast",
            "software security engineer", "devsecops", "dev sec ops",
            "product security", "web application security", "api security",
            "mobile app security", "static analysis", "dynamic analysis",
        ],
    },
    "cloudsec": {
        "thread_env": "TOPIC_CLOUDSEC",
        "name": "☁️ Cloud & Infrastructure Security",
        "keywords": [
            "cloud security", "cloud security engineer", "cloud security architect",
            "aws security", "azure security", "gcp security",
            "infrastructure security", "network security engineer", "firewall engineer",
            "zero trust", "identity access management", "iam engineer",
            "kubernetes security", "container security", "cspm", "cnapp",
        ],
    },
    "grc": {
        "thread_env": "TOPIC_GRC",
        "name": "📋 GRC & Compliance",
        "keywords": [
            "grc", "governance risk compliance", "risk analyst", "risk manager",
            "compliance analyst", "compliance manager",
            "information security manager", "isms", "iso 27001",
            "nist", "pci dss", "hipaa", "gdpr",
            "security auditor", "it auditor", "cyber auditor",
            "data protection officer", "privacy officer", "ciso",
            "third party risk", "cyber risk",
        ],
    },
    "seceng": {
        "thread_env": "TOPIC_SECENG",
        "name": "⚙️ Security Engineering",
        "keywords": [
            "security engineer", "cybersecurity engineer", "information security engineer",
            "security architect", "detection engineer", "detection engineering",
            "security automation", "cryptographer", "cryptography engineer",
            "pki engineer", "iam developer", "security platform engineer",
        ],
    },
    "internships": {
        "thread_env": "TOPIC_INTERNSHIPS",
        "name": "🎓 Internships & Entry Level",
        "keywords": [
            "intern", "internship", "trainee", "junior", "entry level",
            "entry-level", "fresh graduate", "fresh grad", "graduate program",
            "junior security", "soc intern", "security intern",
        ],
    },
}


def get_topic_thread_id(channel_key: str) -> int | None:
    """Get the topic thread_id from environment variable."""
    ch = CHANNELS.get(channel_key, {})
    env_var = ch.get("thread_env", "")
    val = os.getenv(env_var, "")
    if val:
        try:
            return int(val)
        except ValueError:
            return None
    return None


# ─── API Keys ────────────────────────────────────────────────
RAPIDAPI_KEY     = os.getenv("RAPIDAPI_KEY", "")
ADZUNA_APP_ID    = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY   = os.getenv("ADZUNA_APP_KEY", "")
FINDWORK_API_KEY = os.getenv("FINDWORK_API_KEY", "")
JOOBLE_API_KEY   = os.getenv("JOOBLE_API_KEY", "")
REED_API_KEY     = os.getenv("REED_API_KEY", "")

# ─── Geo Patterns ────────────────────────────────────────────
EGYPT_PATTERNS = {
    "egypt", "مصر", "cairo", "القاهرة", "alexandria", "الإسكندرية",
    "giza", "الجيزة", "mansoura", "المنصورة", "tanta", "طنطا",
    "port said", "بورسعيد", "suez", "السويس", "ismailia", "الإسماعيلية",
    "new cairo", "6th of october", "smart village", "new capital",
    "العاصمة الإدارية", "nasr city", "مدينة نصر",
    "maadi", "المعادي", "heliopolis", "مصر الجديدة", "dokki", "الدقي",
    "mohandessin", "المهندسين", "zamalek", "الزمالك",
    "hurghada", "الغردقة", "sharm el sheikh", "شرم الشيخ",
}

GULF_PATTERNS = {
    # Saudi Arabia
    "saudi arabia", "saudi", "ksa", "السعودية", "المملكة العربية السعودية",
    "riyadh", "الرياض", "jeddah", "جدة", "dammam", "الدمام",
    "khobar", "الخبر", "dhahran", "الظهران", "neom", "نيوم",
    "mecca", "مكة", "medina", "المدينة",
    # UAE
    "uae", "united arab emirates", "الإمارات", "dubai", "دبي",
    "abu dhabi", "أبوظبي", "sharjah", "الشارقة", "ajman", "عجمان",
    # Kuwait / Qatar / Bahrain / Oman
    "kuwait", "الكويت", "qatar", "قطر", "doha", "الدوحة",
    "bahrain", "البحرين", "manama", "المنامة",
    "oman", "عُمان", "muscat", "مسقط",
}

REMOTE_PATTERNS = {
    "remote", "anywhere", "worldwide", "work from home", "wfh",
    "distributed", "global", "fully remote", "100% remote",
    "remote-friendly", "location independent", "عن بعد",
}

# ─── Cybersecurity Include Keywords ──────────────────────────
INCLUDE_KEYWORDS = [
    "cybersecurity", "cyber security", "information security", "infosec",
    "security engineer", "security analyst", "security architect",
    "security manager", "security specialist", "security consultant",
    "security researcher", "security developer", "security officer",
    "security administrator", "security lead", "security operations",
    "cyber analyst", "cyber engineer",
    "penetration tester", "penetration testing", "pen tester", "pen testing",
    "pentest", "pentesting", "ethical hacker", "ethical hacking",
    "red team", "red teamer", "red teaming", "offensive security",
    "bug bounty", "vulnerability researcher", "exploit developer",
    "oscp", "ceh", "gpen",
    "soc analyst", "soc engineer", "soc manager",
    "threat analyst", "threat intelligence", "threat hunter", "threat hunting",
    "incident responder", "incident response", "ir analyst",
    "blue team", "cyber threat intelligence", "cti analyst",
    "dfir", "digital forensics", "malware analyst",
    "siem analyst", "security monitoring",
    "application security", "appsec", "devsecops", "dev sec ops",
    "product security", "secure code review", "sast", "dast",
    "software security", "web application security", "api security",
    "cloud security", "aws security", "azure security", "gcp security",
    "infrastructure security", "network security engineer",
    "firewall engineer", "zero trust", "identity access management",
    "kubernetes security", "container security", "cspm", "cnapp",
    "grc", "governance risk compliance", "risk analyst", "risk manager",
    "compliance analyst", "compliance manager",
    "information security manager", "iso 27001",
    "security auditor", "it auditor", "cyber auditor",
    "data protection officer", "privacy officer", "ciso",
    "digital forensics", "forensic analyst", "forensic investigator",
    "malware analyst", "malware reverse engineer", "reverse engineer",
    "reverse engineering", "malware researcher",
    "detection engineer", "detection engineering",
    "security automation", "cryptographer", "cryptography engineer",
    "pki engineer",
    "security intern", "cybersecurity intern", "cyber intern",
    "soc intern", "security trainee", "security graduate",
]

# ─── Exclude Keywords (title-based) ──────────────────────────
EXCLUDE_KEYWORDS = [
    "mechanical engineer", "electrical engineer", "civil engineer",
    "chemical engineer", "structural engineer", "hardware engineer", "pcb",
    "frontend developer", "frontend engineer", "backend developer",
    "backend engineer", "full stack developer", "fullstack developer",
    "mobile developer", "flutter developer", "android developer",
    "ios developer", "react developer", "angular developer",
    "vue developer", "wordpress developer", "shopify developer",
    "data scientist", "machine learning engineer", "ml engineer",
    "ai engineer", "deep learning engineer",
    "graphic designer", "ui designer", "ux designer", "ui/ux",
    "recruiter", "talent acquisition", "hr manager", "human resources",
    "customer support", "customer service", "customer success",
    "financial analyst", "accountant", "bookkeeper",
    "office manager", "administrative assistant",
    "supply chain", "logistics coordinator",
    "sales representative", "sales executive", "account executive",
    "marketing manager", "digital marketing", "social media manager",
    "content writer", "copywriter", "seo specialist",
    "real estate", "insurance agent",
    "nurse", "physician", "pharmacist", "dental", "clinical",
    "medical coder", "veterinary",
    "sales", "hr", "human resources", "marketing", "account manager",
    "customer service", "support", "frontend", "backend", "fullstack",
    "full stack", "mobile developer", "graphic designer", "seo",
    "recruiter", "accountant", "nurse", "pharmacist",
    "devops", "data scientist", "data analyst", "machine learning", "ai engineer",
]

# ─── Emoji Map ────────────────────────────────────────────────
EMOJI_MAP = {
    "penetration": "🕵️", "pentest": "🕵️",
    "red team": "🔴", "ethical hack": "🕵️",
    "bug bounty": "💰", "exploit": "💣",
    "offensive": "⚔️", "oscp": "🎯",
    "soc analyst": "🖥️", "soc engineer": "🖥️",
    "threat hunt": "🎯", "threat intel": "🔍",
    "incident response": "🚨", "blue team": "🔵",
    "malware": "🦠", "forensic": "🔬", "dfir": "🔬",
    "application security": "🛡️", "appsec": "🛡️",
    "devsecops": "⚙️", "product security": "🛡️",
    "cloud security": "☁️", "aws security": "☁️", "azure security": "☁️",
    "network security": "🌐", "firewall": "🔥", "zero trust": "🔒",
    "compliance": "📋", "grc": "📋", "risk analyst": "⚖️",
    "auditor": "📋", "iso 27001": "📋", "ciso": "👔",
    "privacy": "🔏", "detection engineer": "🔎",
    "security architect": "🏗️", "cryptograph": "🔐",
    "senior": "👨‍💻", "junior": "🌱", "lead": "⭐",
    "principal": "⭐", "staff": "⭐", "intern": "🎓",
    "architect": "🏗️", "manager": "👔",
    "remote": "🌍",
    "egypt": "🇪🇬", "مصر": "🇪🇬", "cairo": "🇪🇬",
    "saudi": "🇸🇦", "riyadh": "🇸🇦", "jeddah": "🇸🇦",
    "dubai": "🇦🇪", "uae": "🇦🇪",
    "security": "🔒", "cyber": "🔐",
}

DEFAULT_EMOJI = "🔐"

# ─── Source Display Names ─────────────────────────────────────
SOURCE_DISPLAY = {
    "remotive":      "Remotive",
    "himalayas":     "Himalayas",
    "jobicy":        "Jobicy",
    "remoteok":      "RemoteOK",
    "arbeitnow":     "Arbeitnow",
    "wwr":           "We Work Remotely",
    "workingnomads": "Working Nomads",
    "jsearch":       None,
    "linkedin":      "LinkedIn",
    "adzuna":        "Adzuna",
    "findwork":      "Findwork",
    "jooble":        "Jooble",
    "reed":          "Reed",
    "infosec_jobs":  "InfoSec-Jobs",
    "cybersecjobs":  "CyberSecJobs",
    "clearancejobs": "ClearanceJobs",
    "isaca":         "ISACA",
    "isc2":          "(ISC)²",
    "securityjobs":  "SecurityJobs.net",
    "dice":          "Dice",
    "bugcrowd":      "Bugcrowd",
    "hackerone":     "HackerOne",
    "greenhouse":    None,
    "lever":         None,
}

# ─── Misc ─────────────────────────────────────────────────────
SEEN_JOBS_FILE   = "seen_jobs.json"
MAX_JOBS_PER_RUN = 15   # hard anti-spam cap per run
REQUEST_TIMEOUT  = 15
SEED_MODE_ENV    = "SEED_MODE"
