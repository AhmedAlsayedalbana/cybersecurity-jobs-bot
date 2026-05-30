"""
Configuration for Cybersecurity Jobs Telegram Bot.
Specialized 100% for Cybersecurity roles.
Priority: Egypt   Remote   Gulf (optional)
"""

import os


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def sanitize_keywords(values, *, min_len: int = 2, lowercase: bool = True) -> list[str]:
    """
    Remove empty/whitespace/noise keywords and return a stable de-duplicated list.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        if raw is None:
            continue
        token = str(raw).strip()
        if not token:
            continue
        token_norm = token.lower() if lowercase else token
        if len(token_norm) < max(1, min_len):
            continue
        if token_norm in seen:
            continue
        seen.add(token_norm)
        out.append(token_norm)
    return out


def validate_keyword_sets(named_sets: dict[str, object], *, min_len: int = 2) -> None:
    """
    Fail fast if any keyword set contains unsafe tokens (empty/whitespace/too short).
    """
    violations: list[str] = []
    for set_name, container in (named_sets or {}).items():
        if isinstance(container, dict):
            items = list(container.keys())
        else:
            items = list(container or [])
        for item in items:
            token = str(item)
            if not token.strip():
                violations.append(f"{set_name}: contains empty/whitespace token")
                break
            if len(token.strip()) < max(1, min_len):
                violations.append(f"{set_name}: short token '{token}'")
                break
    if violations:
        raise ValueError("Unsafe keyword configuration: " + "; ".join(violations))

#  Telegram 
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_GROUP_ID  = os.getenv("TELEGRAM_GROUP_ID", "")
TELEGRAM_SEND_DELAY = 3  # seconds between messages

#  Community Topics 
CHANNELS = {
    
    "egypt": {
        "thread_env": "TOPIC_EGYPT",
        "name": " Egypt Jobs",
        "match": "GEO_EGYPT",
    },
    "remote": {
        "thread_env": "TOPIC_REMOTE",
        "name": " Remote Jobs",
        "match": "REMOTE",
    },
    "pentest": {
        "thread_env": "TOPIC_PENTEST",
        "name": " Penetration Testing & Red Team",
        "keywords": [
            "penetration tester", "penetration testing", "pen tester", "pen testing",
            "pentest", "pentesting", "ethical hacker", "ethical hacking",
            "red team", "red teamer", "red teaming", "offensive security",
            "bug bounty", "vulnerability researcher", "exploit developer",
            "exploit development", "oscp", "ceh", "gpen", "offensive-security",
            "ctf",
        ],
    },
    "soc": {
        "thread_env": "TOPIC_SOC",
        "name": " SOC & Threat Analysis",
        "keywords": [
            "soc analyst", "soc engineer", "soc manager", "soc lead",
            "security operations center", "security operations",
            "threat analyst", "threat intelligence", "threat hunter", "threat hunting",
            "incident responder", "incident response", "ir analyst",
            "blue team", "cyber threat intelligence", "cti analyst",
            "dfir", "digital forensics", "malware analyst",
            "siem analyst", "security monitoring", "splunk", "qradar", "sentinel",
            "edr", "xdr", "mdr", "threat detection",
        ],
    },
    "appsec": {
        "thread_env": "TOPIC_APPSEC",
        "name": " Application Security",
        "keywords": [
            "application security", "appsec", "app sec",
            "secure code review", "sast", "dast",
            "software security engineer", "devsecops", "dev sec ops",
            "product security", "web application security", "api security",
            "mobile app security", "static analysis", "dynamic analysis",
            "owasp", "burp suite", "checkmarx", "snyk",
        ],
    },
    "cloudsec": {
        "thread_env": "TOPIC_CLOUDSEC",
        "name": " Cloud & Infrastructure Security",
        "keywords": [
            "cloud security", "cloud security engineer", "cloud security architect",
            "aws security", "azure security", "gcp security",
            "kubernetes security", "container security", "cspm", "cnapp",
            "wiz", "prisma cloud", "cloud native security",
        ],
    },
    "grc": {
        "thread_env": "TOPIC_GRC",
        "name": " GRC & Compliance",
        "keywords": [
            "grc", "governance risk compliance", "risk analyst", "risk manager",
            "compliance analyst", "compliance manager",
            "information security manager", "isms", "iso 27001",
            "nist", "pci dss", "hipaa", "gdpr",
            "security auditor", "it auditor", "cyber auditor",
            "data protection officer", "privacy officer", "ciso",
            "third party risk", "cyber risk", "security policy",
        ],
    },
    "seceng": {
        "thread_env": "TOPIC_SECENG",
        "name": " Security Engineering",
        "keywords": [
            "security engineer", "cybersecurity engineer", "information security engineer",
            "security architect", "detection engineer", "detection engineering",
            "security automation", "cryptographer", "cryptography engineer",
            "pki engineer", "iam developer", "security platform engineer",
            "security tools developer", "python security",
            "iam engineer", "identity engineer", "identity and access management",
            "pam engineer", "privileged access management",
            "vulnerability management", "security technical architect",
        ],
    },
    "networksec": {
        "thread_env": "TOPIC_NETWORKSEC",
        "name": " Network Security Engineer",
        "keywords": [
            "network security engineer", "network security analyst",
            "network security architect", "network security manager",
            "network security specialist", "network security consultant",
            "firewall engineer", "firewall administrator", "firewall analyst",
            "ids engineer", "ips engineer", "ids/ips", "intrusion detection",
            "intrusion prevention", "network defense", "perimeter security",
            "vpn engineer", "vpn administrator", "sdwan security", "sd-wan security",
            "palo alto networks", "fortinet engineer", "cisco security engineer",
            "checkpoint engineer", "juniper security",
            "network access control", "nac engineer", "packet analysis",
            "network forensics", "traffic analysis",
            "ddos protection", "ddos mitigation", "waf engineer",
            "web application firewall",
        ],
    },
    "gulf": {
        "thread_env": "TOPIC_GULF",
        "name": " Gulf Jobs (KSA/UAE/Kuwait)",
        "match": "GEO_GULF",
    },
    "internships": {
        "thread_env": "TOPIC_INTERNSHIPS",
        "name": " Internships & Entry Level",
        # FIXED: Only cyber-specific intern/junior keywords � avoids catching
        # generic IT/engineering internships that slip past the cyber filter.
        # "intern" alone is too broad � must be paired with a security domain word.
        "keywords": [
            "security intern", "cybersecurity intern", "cyber intern",
            "soc intern", "security trainee", "cybersecurity trainee",
            "junior security", "junior cybersecurity", "junior soc",
            "junior penetration", "junior pentest", "junior grc",
            "entry level security", "entry level cybersecurity", "entry-level security",
            "graduate security", "graduate cybersecurity",
            "security graduate", "cybersecurity graduate",
            "security fresh", "security scholarship", "security bootcamp",
        ],
    },
}

# Sanitize all channel keyword lists at import time.
for _channel_cfg in CHANNELS.values():
    if isinstance(_channel_cfg, dict) and "keywords" in _channel_cfg:
        _channel_cfg["keywords"] = sanitize_keywords(_channel_cfg.get("keywords", []), min_len=2)


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


#  API Keys 
RAPIDAPI_KEY     = os.getenv("RAPIDAPI_KEY", "")
ADZUNA_APP_ID    = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY   = os.getenv("ADZUNA_APP_KEY", "")
FINDWORK_API_KEY = os.getenv("FINDWORK_API_KEY", "")
JOOBLE_API_KEY   = os.getenv("JOOBLE_API_KEY", "")
REED_API_KEY     = os.getenv("REED_API_KEY", "")
SERPAPI_KEY      = os.getenv("SERPAPI_KEY", "")
GOOGLE_CSE_API_KEY = os.getenv("GOOGLE_CSE_API_KEY", "")
GOOGLE_CSE_CX      = os.getenv("GOOGLE_CSE_CX", "")

#  Geo Patterns 
EGYPT_PATTERNS = {
    # General
    "egypt", "", "egyptian",
    # Cairo & districts
    "cairo", "", "new cairo", "nasr city", " ",
    "maadi", "", "heliopolis", " ", "dokki", "",
    "mohandessin", "", "zamalek", "",
    "6th of october", "6 october", "smart village", "",
    "new capital", " ", "obour", "",
    "ain shams", " ", "shoubra", "", "el marg",
    "15th of may", "15 ", "badr city", " ",
    # Giza & surroundings
    "giza", "", "6th october", "sheikh zayed", " ",
    "october city", "hadayek october", "al haram", "",
    "imbaba", "", "bulaq", "",
    # Alexandria
    "alexandria", "", "alex", "smouha", "",
    "miami", " ", "sidi bishr", " ",
    "agami", "", "montazah", "",
    # Nile Delta
    "mansoura", "", "tanta", "",
    "zagazig", "", "benha", "",
    "damanhour", "", "menouf", "",
    "kafr el sheikh", " ", "shibin", "",
    "mit ghamr", "meet ghamr", "dakahlia", "",
    "sharqia", "", "gharbiya", "",
    "monufia", "", "beheira", "",
    # Canal Zone
    "port said", "", "suez", "",
    "ismailia", "", "ismailiya",
    # Upper Egypt
    "assiut", "", "aswan", "", "luxor", "",
    "sohag", "", "qena", "", "minya", "",
    "beni suef", " ", "fayoum", "",
    # Red Sea & Sinai
    "hurghada", "", "sharm el sheikh", " ",
    "el gouna", "", "ain sokhna", " ",
    "dahab", "", "marsa alam", " ",
    # New Cities
    "new alamein", " ", "new assiut", " ",
    "new sohag", "new mansoura", " ",
    "10th of ramadan", "  ",
}

GULF_PATTERNS = {
    # Saudi Arabia
    "saudi arabia", "saudi", "ksa", "", "  ",
    "riyadh", "", "jeddah", "", "dammam", "",
    "khobar", "", "dhahran", "", "neom", "",
    "mecca", "", "medina", "", "jubail", "",
    "yanbu", "", "tabuk", "", "abha", "",
    "khamis mushait", " ", "taif", "",
    "hail", "", "najran", "", "jizan", "",
    # UAE
    "uae", "united arab emirates", "", "dubai", "",
    "abu dhabi", "", "sharjah", "", "ajman", "",
    "ras al khaimah", " ", "fujairah", "",
    "umm al quwain", " ", "al ain", "",
    # Kuwait
    "kuwait", "", "kuwait city", " ",
    "hawalli", "", "salmiya", "", "ahmadi", "",
    # Qatar
    "qatar", "", "doha", "", "al wakra", "",
    "lusail", "", "al khor", "",
    # Bahrain
    "bahrain", "", "manama", "",
    "muharraq", "", "riffa", "",
    # Oman
    "oman", "", "muscat", "", "sohar", "",
    "salalah", "", "nizwa", "",
}

# Sanitize pattern sets: remove empty strings and whitespace-only entries
# (these can be encoding artifacts that would otherwise match every string).
EGYPT_PATTERNS = set(sanitize_keywords(EGYPT_PATTERNS, min_len=2))
GULF_PATTERNS = set(sanitize_keywords(GULF_PATTERNS, min_len=2))
EGYPT_PATTERNS.update({"مصر", "القاهرة", "الجيزة", "الإسكندرية", "اسكندرية"})
GULF_PATTERNS.update({
    "السعودية", "الرياض", "جدة", "الإمارات", "الامارات", "دبي",
    "أبو ظبي", "ابو ظبي", "قطر", "الكويت", "البحرين", "عمان",
})

REMOTE_PATTERNS = {
    "remote", "anywhere", "worldwide", "work from home", "wfh",
    "distributed", "global", "fully remote", "100% remote",
    "remote-friendly", "location independent", " ",
}
REMOTE_PATTERNS = set(sanitize_keywords(REMOTE_PATTERNS, min_len=2))

#  Cybersecurity Include Keywords 
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
    "identity and access management", "identity access management",
    "iam", "pam", "privileged access management",
    "vulnerability management", "vulnerability analyst",
    "security technical architect", "xsiam consultant",
    "ot security", "ics security", "scada security",
    "security intern", "cybersecurity intern", "cyber intern",
    "soc intern", "security trainee", "security graduate",
]
INCLUDE_KEYWORDS = sanitize_keywords(INCLUDE_KEYWORDS, min_len=2)

#  Exclude Keywords (title-based) 
# Reduced strictness: removed broad terms like 'support', 'sales', 'hr' 
# that might be part of a legitimate security title (e.g., "Security Support Engineer")
EXCLUDE_KEYWORDS = [
    "mechanical engineer", "electrical engineer", "civil engineer",
    "chemical engineer", "structural engineer", "hardware engineer",
    "frontend developer", "frontend engineer", "backend developer",
    "backend engineer", "full stack developer", "fullstack developer",
    "mobile developer", "flutter developer", "android developer",
    "ios developer", "react developer", "angular developer",
    "vue developer", "wordpress developer", "shopify developer",
    "graphic designer", "ui designer", "ux designer", "ui/ux",
    "recruiter", "talent acquisition", "hr manager", "human resources",
    "financial analyst", "accountant", "bookkeeper",
    "office manager", "administrative assistant",
    "supply chain", "logistics coordinator",
    "marketing manager", "digital marketing", "social media manager",
    "content writer", "copywriter", "seo specialist",
    "real estate", "insurance agent",
    "nurse", "physician", "pharmacist", "dental", "clinical",
    "medical coder", "veterinary",
    # Security Guard / Physical Security (bypass WEAK_TERMS false-positive in Egypt filter)
    "security guard", "physical security", "loss prevention",
    "security supervisor", "building security", "event security",
]
EXCLUDE_KEYWORDS = sanitize_keywords(EXCLUDE_KEYWORDS, min_len=2)

#  Emoji Map 
EMOJI_MAP = {
    "penetration": "", "pentest": "",
    "red team": "", "ethical hack": "",
    "bug bounty": "", "exploit": "",
    "offensive": "", "oscp": "",
    "soc analyst": "", "soc engineer": "",
    "threat hunt": "", "threat intel": "",
    "incident response": "", "blue team": "",
    "malware": "", "forensic": "", "dfir": "",
    "application security": "", "appsec": "",
    "devsecops": "", "product security": "",
    "cloud security": "", "aws security": "", "azure security": "",
    "network security": "", "firewall": "", "zero trust": "",
    "compliance": "", "grc": "", "risk analyst": "",
    "auditor": "", "iso 27001": "", "ciso": "",
    "privacy": "", "detection engineer": "",
    "security architect": "", "cryptograph": "",
    "senior": "", "junior": "", "lead": "",
    "principal": "", "staff": "", "intern": "",
    "architect": "", "manager": "",
    "remote": "",
    "egypt": "", "": "", "cairo": "",
    "saudi": "", "riyadh": "", "jeddah": "",
    "dubai": "", "uae": "",
    "security": "", "cyber": "",
}
EMOJI_MAP = {
    k: v for k, v in EMOJI_MAP.items()
    if sanitize_keywords([k], min_len=2)
}

DEFAULT_EMOJI = ""

#  Source Display Names 
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
    "linkedin_li_at": "LinkedIn Authenticated",
    "linkedin_hiring": "LinkedIn #Hiring",
    "linkedin_hr_hunter": "LinkedIn HR Search Jobs",
    "linkedin_hr_post": "LinkedIn HR Post",
    "adzuna":        "Adzuna",
    "findwork":      "Findwork",
    "jooble":        "Jooble",
    "reed":          "Reed",
    "infosec_jobs":  "InfoSec-Jobs",
    "cybersecjobs":  "CyberSecJobs",
    "clearancejobs": "ClearanceJobs",
    "isaca":         "ISACA",
    "isc2":          "(ISC)�",
    "securityjobs":  "SecurityJobs.net",
    "dice":          "Dice",
    "bugcrowd":      "Bugcrowd",
    "hackerone":     "HackerOne",
    "greenhouse":    None,
    "lever":         None,
}

#  Misc 
SEEN_JOBS_FILE   = "seen_jobs.json"
MAX_JOBS_PER_RUN = int(os.getenv("MAX_JOBS_PER_RUN", "260"))
# MAX_JOB_AGE_DAYS: hard-block threshold for truly stale jobs.
# NOTE: scoring.py applies a graduated penalty BEFORE this threshold:
#   5d  -4pts, 7d  -6pts, 10d+  -8pts. This hard block is a safety net only.
# main.py uses this value as the hard-block threshold.
# Default tightened to 2d (48h) to enforce strict freshness.
MAX_JOB_AGE_DAYS = int(os.getenv("MAX_JOB_AGE_DAYS", "2"))
MAX_JOB_AGE_HOURS = int(os.getenv("MAX_JOB_AGE_HOURS", str(MAX_JOB_AGE_DAYS * 24)))
LINKEDIN_SOURCE_BUDGET_SECONDS = int(os.getenv("LINKEDIN_SOURCE_BUDGET_SECONDS", "120"))
LINKEDIN_TOTAL_BUDGET_SECONDS = int(os.getenv("LINKEDIN_TOTAL_BUDGET_SECONDS", "1500"))
LINKEDIN_COMPANY_SEARCH_BUDGET_SECONDS = int(os.getenv("LINKEDIN_COMPANY_SEARCH_BUDGET_SECONDS", "180"))
LINKEDIN_RATE_MAX_RPS = float(os.getenv("LINKEDIN_RATE_MAX_RPS", "0.55"))
LINKEDIN_MAX_CONCURRENCY = int(os.getenv("LINKEDIN_MAX_CONCURRENCY", "4"))
LI_PRIMARY_BUDGET_SECONDS = int(
    os.getenv("LI_PRIMARY_BUDGET_SECONDS", str(LINKEDIN_SOURCE_BUDGET_SECONDS))
)
LI_HR_POST_BUDGET_SECONDS = int(
    os.getenv("LI_HR_POST_BUDGET_SECONDS", str(LINKEDIN_SOURCE_BUDGET_SECONDS))
)
DAILY_SEND_HOURS = int(os.getenv("DAILY_SEND_HOURS", "5"))      # ✅ v46: matches cron every-5h schedule
GLOBAL_DEDUP_HOURS = int(os.getenv("GLOBAL_DEDUP_HOURS", "5"))  # ✅ v46: prevent re-sending same job within same window
HR_HIRING_THRESHOLD = int(os.getenv("HR_HIRING_THRESHOLD", "8"))
HR_CONFIDENCE_THRESHOLD = int(os.getenv("HR_CONFIDENCE_THRESHOLD", "12"))
ENABLE_STRICT_HR_POSTS_ONLY = _env_bool("ENABLE_STRICT_HR_POSTS_ONLY", True)
# SCORE_THRESHOLD v38: raised to 14 to ensure jobs have REAL tech match.
# Egypt location bonus = 8pts. A job needs at least 6pts of tech signals (e.g. 1-2 specific tools)
# to pass. This prevents "General Security" / no-context jobs from being posted.
SCORE_THRESHOLD  = 14
TARGET_JOBS_PER_CHANNEL = int(os.getenv("TARGET_JOBS_PER_CHANNEL", "10"))   # ✅ v46: raised from 5 → 10
MAX_JOBS_PER_CHANNEL = int(os.getenv("MAX_JOBS_PER_CHANNEL", str(TARGET_JOBS_PER_CHANNEL)))
REQUEST_TIMEOUT  = 10
SEED_MODE_ENV    = "SEED_MODE"
ML_FILTER_ENABLED = _env_bool("ML_FILTER_ENABLED", True)
ML_MIN_PROB = float(os.getenv("ML_MIN_PROB", "0.75"))
ML_MODEL_PATH = os.getenv("ML_MODEL_PATH", "ml_models/cybersec_title_model.joblib")
LLM_CLASSIFIER_ENABLED = _env_bool("LLM_CLASSIFIER_ENABLED", True)
LLM_CLASSIFIER_PROVIDER = os.getenv("LLM_CLASSIFIER_PROVIDER", "auto").strip().lower()
LLM_CLASSIFIER_MODEL = os.getenv("LLM_CLASSIFIER_MODEL", "").strip()
LLM_CLASSIFIER_CACHE_PATH = os.getenv("LLM_CLASSIFIER_CACHE_PATH", "llm_classifier_cache.json")
ENTRY_LEVEL_TARGET_RATIO = float(os.getenv("ENTRY_LEVEL_TARGET_RATIO", "0.60"))
LINKEDIN_POOL_CAP_RATIO = float(os.getenv("LINKEDIN_POOL_CAP_RATIO", "0.50"))
NON_LINKEDIN_POOL_FLOOR_RATIO = float(os.getenv("NON_LINKEDIN_POOL_FLOOR_RATIO", "0.30"))
LINKEDIN_ASYNC_MAX_CONCURRENCY = int(os.getenv("LINKEDIN_ASYNC_MAX_CONCURRENCY", "14"))
TELEGRAM_RETRY_MAX_ATTEMPTS = int(os.getenv("TELEGRAM_RETRY_MAX_ATTEMPTS", "6"))
TELEGRAM_RETRY_BASE_DELAY_SECONDS = int(os.getenv("TELEGRAM_RETRY_BASE_DELAY_SECONDS", "45"))
TELEGRAM_RETRY_DRAIN_LIMIT = int(os.getenv("TELEGRAM_RETRY_DRAIN_LIMIT", "25"))
SOURCE_HEALTH_MIN_SUCCESS = int(os.getenv("SOURCE_HEALTH_MIN_SUCCESS", "1"))
SOURCE_AUTO_DISABLE_THRESHOLD = int(os.getenv("SOURCE_AUTO_DISABLE_THRESHOLD", "4"))
SOURCE_QUARANTINE_MINUTES = int(os.getenv("SOURCE_QUARANTINE_MINUTES", "180"))
ENABLE_SOURCE_PRIORITY_GATING = _env_bool("ENABLE_SOURCE_PRIORITY_GATING", True)
ALLOW_API_KEY_SOURCES = _env_bool("ALLOW_API_KEY_SOURCES", True)
ENABLE_UNSTABLE_SOURCES = _env_bool("ENABLE_UNSTABLE_SOURCES", False)
LOCAL_ML_RETRAIN_EVERY_N_RUNS = int(os.getenv("LOCAL_ML_RETRAIN_EVERY_N_RUNS", "8"))
LOCAL_ML_MIN_SAMPLES = int(os.getenv("LOCAL_ML_MIN_SAMPLES", "250"))
LOCAL_ML_DATASET_DAYS = int(os.getenv("LOCAL_ML_DATASET_DAYS", "60"))

# Optional source toggles.
ENABLE_SOURCE_JSEARCH = _env_bool("ENABLE_SOURCE_JSEARCH", True)
# Disabled by default because these sources frequently return 0 in production runs.
ENABLE_SOURCE_LINKEDIN_EGYPT_ARABIC = _env_bool("ENABLE_SOURCE_LINKEDIN_EGYPT_ARABIC", True)
ENABLE_SOURCE_EGYPT_COMPANIES = _env_bool("ENABLE_SOURCE_EGYPT_COMPANIES", False)
ENABLE_SOURCE_LINKEDIN_HR_HUNTER = _env_bool("ENABLE_SOURCE_LINKEDIN_HR_HUNTER", True)
ENABLE_SOURCE_LINKEDIN_POSTS = _env_bool("ENABLE_SOURCE_LINKEDIN_POSTS", True)
ENABLE_SOURCE_LINKEDIN_HR_POSTS = _env_bool("ENABLE_SOURCE_LINKEDIN_HR_POSTS", True)
ENABLE_SOURCE_REMOTIVE = _env_bool("ENABLE_SOURCE_REMOTIVE", False)
ENABLE_SOURCE_ARBEITNOW = _env_bool("ENABLE_SOURCE_ARBEITNOW", False)
ENABLE_SOURCE_WWR = _env_bool("ENABLE_SOURCE_WWR", False)
ENABLE_SOURCE_WUZZUF = _env_bool("ENABLE_SOURCE_WUZZUF", True)
ENABLE_SOURCE_FREELANCER = _env_bool("ENABLE_SOURCE_FREELANCER", True)
ENABLE_SOURCE_MOSTAQL = _env_bool("ENABLE_SOURCE_MOSTAQL", True)

#  New Sources 
SOURCE_DISPLAY.update({
    "egcert":         "EG-CERT",
    "itida":          "ITIDA",
    "iti":            "ITI Egypt",
    "depi":           "DEPI Egypt",
    "nti":            "NTI Egypt",
    "ntra":           "NTRA",
    "mcit":           "MCIT",
    "tiec":           "TIEC",
    "cbe":            "Central Bank Egypt",
    "wuzzuf":         "Wuzzuf",
    "forasna":        "Forasna",
    "bayt":           "Bayt.com",
    "naukrigulf":     "NaukriGulf",
    "drjobpro":       "Dr.Job Pro",
    "akhtaboot":      "Akhtaboot",
    "nca_ksa":        "NCA Saudi Arabia",
    "citc_ksa":       "CITC KSA",
    "sdaia":          "SDAIA",
    "aramco":         "Saudi Aramco",
    "neom":           "NEOM",
    "g42":            "G42 UAE",
    "qcert":          "QCERT Qatar",
    "tanqeeb":        "Tanqeeb",
    "mena_boards":    "MENA Boards",
    "google_jobs":    "Google Jobs",
    "adzuna_mena":    "Adzuna MENA",
    "linkedin_egypt_companies": "LinkedIn (EG Companies)",
    "linkedin_gulf_companies":  "LinkedIn (Gulf Companies)",
    "linkedin_hr_post": "LinkedIn HR Post",
    "linkedin_egypt_arabic": "LinkedIn Egypt Arabic",
    "stc_ksa":        "STC Saudi Arabia",
    "tdra_uae":       "TDRA UAE",
    "etisalat_uae":   "e& UAE",
    "freelancer":     "Freelancer",
    "mostaql":        "Mostaql",
    "upwork":         "Upwork",
    "fiverr":         "Fiverr",
    "reddit_discord": "Reddit / Discord",
    "telegram_channel": "Telegram Channels",
    "company_careers": "Company Career Pages",
    "google_intel":   "Google Search Intelligence",
    "indeed":         "Indeed",
    "linkedin_unified": "LinkedIn Unified Engine",
})


KEYWORD_SETS_FOR_VALIDATION = {
    "channel_keywords": [kw for ch in CHANNELS.values() for kw in ch.get("keywords", [])],
    "egypt_patterns": EGYPT_PATTERNS,
    "gulf_patterns": GULF_PATTERNS,
    "remote_patterns": REMOTE_PATTERNS,
    "include_keywords": INCLUDE_KEYWORDS,
    "exclude_keywords": EXCLUDE_KEYWORDS,
    "emoji_map_keys": EMOJI_MAP,
}


def run_startup_validations() -> None:
    validate_keyword_sets(KEYWORD_SETS_FOR_VALIDATION, min_len=2)

# ── v45 Migration: New source feature flags ──────────────────────────────
# LLM_CLASSIFIER_* vars already defined above (lines 490-493) — not repeated here.
ENABLE_SOURCE_GREENHOUSE_EXPANDED = _env_bool("ENABLE_SOURCE_GREENHOUSE_EXPANDED", True)
ENABLE_SOURCE_GULF_MONSTER        = False   # disabled — 0 jobs on every run (feed dead)
ENABLE_SOURCE_JSEARCH_ENHANCED    = _env_bool("ENABLE_SOURCE_JSEARCH_ENHANCED", True)

GREENHOUSE_EXPANDED_TIMEOUT_SEC = int(os.getenv("GREENHOUSE_EXPANDED_TIMEOUT_SEC", "480"))
JSEARCH_PAGES_LOCAL             = int(os.getenv("JSEARCH_PAGES_LOCAL", "1"))
JSEARCH_PAGES_REMOTE            = int(os.getenv("JSEARCH_PAGES_REMOTE", "1"))

# ── v47: Source flags ─────────────────────────────────────────────────────
ENABLE_SOURCE_LINKEDIN_EXTENDED = False     # deprecated — queries merged into linkedin_unified
ENABLE_JINA_SCRAPER             = _env_bool("ENABLE_JINA_SCRAPER", True)
ENABLE_SOURCE_MENA_BOARDS       = _env_bool("ENABLE_SOURCE_MENA_BOARDS", True)
LINKEDIN_EXTENDED_MAX_JOBS      = int(os.getenv("LINKEDIN_EXTENDED_MAX_JOBS", "10"))
