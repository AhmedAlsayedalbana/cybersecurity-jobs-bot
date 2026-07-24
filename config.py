"""
Configuration for Cybersecurity Jobs Telegram Bot.
Specialized 100% for Cybersecurity roles.
Priority: Egypt   Remote   Gulf (optional)
"""

import os

# ── Load .env automatically when running locally ──────────────────────────────
# In GitHub Actions the secrets are injected directly; the .env file is only
# needed for local development.  We attempt to load it silently so the bot
# works out-of-the-box after `cp .env.example .env` + filling in your values.
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=False)
except ImportError:
    pass  # python-dotenv not installed — env vars must be set manually
# ─────────────────────────────────────────────────────────────────────────────


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _optional_int(name: str) -> int | None:
    raw = os.getenv(name, "")
    try:
        return int(raw) if raw.strip() else None
    except ValueError:
        return None


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
# v56: accept either secret name. Some deployments (and the v54 branch this
# was merged with) name the repo secret TELEGRAM_GROUP_ID instead of
# TELEGRAM_CHAT_ID — rather than forcing a rename, both are read here and
# TELEGRAM_CHAT_ID wins if both happen to be set.
TELEGRAM_CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID", "") or os.getenv("TELEGRAM_GROUP_ID", "")
TELEGRAM_SEND_DELAY = 3  # seconds between messages
HEALTH_REPORT_CHAT_ID = os.getenv("HEALTH_REPORT_CHAT_ID", "") or TELEGRAM_CHAT_ID

# Telegram topic thread IDs - None means the topic is not configured.
TOPIC_EGYPT = _optional_int("TOPIC_EGYPT")
TOPIC_GULF = _optional_int("TOPIC_GULF")
TOPIC_REMOTE = _optional_int("TOPIC_REMOTE")
TOPIC_SOC = _optional_int("TOPIC_SOC")
TOPIC_PENTEST = _optional_int("TOPIC_PENTEST")
TOPIC_APPSEC = _optional_int("TOPIC_APPSEC")
TOPIC_CLOUDSEC = _optional_int("TOPIC_CLOUDSEC")
TOPIC_GRC = _optional_int("TOPIC_GRC")
TOPIC_SECENG = _optional_int("TOPIC_SECENG")
TOPIC_NETWORKSEC = _optional_int("TOPIC_NETWORKSEC")
TOPIC_INTERNSHIPS = _optional_int("TOPIC_INTERNSHIPS")
# Isolated topic used by the optional delivery canary.  It is never a routing
# destination for real jobs.
TOPIC_TEST = _optional_int("TOPIC_TEST")

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
            "malware analysis", "reverse engineering", "ctf",
            " ", " ", " ", " ",
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
            " soc", " soc", "  ", " ",
            " ", " ", " ",
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
            " ", " ", "  ",
        ],
    },
    "cloudsec": {
        "thread_env": "TOPIC_CLOUDSEC",
        "name": " Cloud & Infrastructure Security",
        "keywords": [
            "cloud security", "cloud security engineer", "cloud security architect",
            "aws security", "azure security", "gcp security",
            "infrastructure security",
            "zero trust", "identity access management", "iam engineer",
            "kubernetes security", "container security", "cspm", "cnapp",
            "wiz", "prisma cloud", "cloud native security",
            " ", "  ", "  ",
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
            "  ", " ", " ",
            "", " ", " 27001",
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
            " ", "  ", " ", "  ",
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
            "  ", "  ", "  ",
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
    return _optional_int(env_var) if env_var else None


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
# v54: raised to 3 days per explicit requirement — jobs older than 72h are
# NEVER sent to any channel. linkedin, freelance, Egyptian boards, and all
# other sources respect this gate. send_jobs() reuses this same value
# (MAX_JOB_AGE_HOURS) for its runtime gate on posted_date, so both layers
# are always in sync.
MAX_JOB_AGE_DAYS = int(os.getenv("MAX_JOB_AGE_DAYS", "3"))   # ← v54: hard 3-day stale gate
MAX_JOB_AGE_HOURS = int(os.getenv("MAX_JOB_AGE_HOURS", str(MAX_JOB_AGE_DAYS * 24)))
LINKEDIN_SOURCE_BUDGET_SECONDS = int(os.getenv("LINKEDIN_SOURCE_BUDGET_SECONDS", "120"))
# ✅ v47: Raised from 180 → 240s — the full query plan (CORE+GULF+EXPANSION) needs
# ~118s for page fetches + ~50s for detail pages at 0.55 RPS, so 180s was consistently
# being hit. 240s provides enough headroom while still capping runaway sessions.
# v54: the v53 query plan (56 queries × up to 4 pages) was running strictly
# sequentially and consistently blew through the 300s budget, returning only
# ~25 partial jobs per run — starving LinkedIn's 80% send-share requirement.
# Fix: LINKEDIN_QUERY_CONCURRENCY now lets several queries run in parallel
# (see sources/linkedin_unified.py), and the budget/concurrency were raised
# to give that parallel run room to actually finish the full query plan.
# v54.1: the July 19 20:16 run confirms the fix works (25 → 154 jobs) but
# still hits the hard timeout before finishing the plan. Total run time was
# only ~15 of the 55 minutes GitHub Actions allows, so there's headroom to
# push further.
LINKEDIN_TOTAL_BUDGET_SECONDS = int(os.getenv("LINKEDIN_TOTAL_BUDGET_SECONDS", "600"))
LINKEDIN_RATE_MAX_RPS = float(os.getenv("LINKEDIN_RATE_MAX_RPS", "0.65"))              # v53: 0.65 rps (was 0.55)
LINKEDIN_MAX_CONCURRENCY = int(os.getenv("LINKEDIN_MAX_CONCURRENCY", "8"))             # v54: 8 (was 5)
LINKEDIN_QUERY_CONCURRENCY = int(os.getenv("LINKEDIN_QUERY_CONCURRENCY", "6"))
LINKEDIN_PAGES_PER_QUERY = int(os.getenv("LINKEDIN_PAGES_PER_QUERY", "4"))
LINKEDIN_DETAILS_PER_QUERY = int(os.getenv("LINKEDIN_DETAILS_PER_QUERY", "6"))
LI_PRIMARY_BUDGET_SECONDS = int(
    os.getenv("LI_PRIMARY_BUDGET_SECONDS", str(LINKEDIN_SOURCE_BUDGET_SECONDS))
)
LI_HR_POST_BUDGET_SECONDS = int(
    os.getenv("LI_HR_POST_BUDGET_SECONDS", str(LINKEDIN_SOURCE_BUDGET_SECONDS))
)
# v54: raised 48h → 168h (7 days) — a job must never be re-sent to the SAME
# channel/group within one week. This directly drives was_sent_to_channel_recently()
# in database.py, used by telegram_sender.send_jobs() for per-channel dedup.
DAILY_SEND_HOURS = int(os.getenv("DAILY_SEND_HOURS", "168"))     # ← v54: 7-day no-repeat-per-channel window
GLOBAL_DEDUP_HOURS = int(os.getenv("GLOBAL_DEDUP_HOURS", "168"))  # ← v54: matches 7-day window
HR_HIRING_THRESHOLD = int(os.getenv("HR_HIRING_THRESHOLD", "8"))
HR_CONFIDENCE_THRESHOLD = int(os.getenv("HR_CONFIDENCE_THRESHOLD", "12"))
ENABLE_STRICT_HR_POSTS_ONLY = _env_bool("ENABLE_STRICT_HR_POSTS_ONLY", True)
# SCORE_THRESHOLD v38: raised to 14 to ensure jobs have REAL tech match.
# Egypt location bonus = 8pts. A job needs at least 6pts of tech signals (e.g. 1-2 specific tools)
# to pass. This prevents "General Security" / no-context jobs from being posted.
SCORE_THRESHOLD  = 14
TARGET_JOBS_PER_CHANNEL = int(os.getenv("TARGET_JOBS_PER_CHANNEL", "10"))   # ✅ v46: raised from 5 → 10
MAX_JOBS_PER_CHANNEL = int(os.getenv("MAX_JOBS_PER_CHANNEL", str(TARGET_JOBS_PER_CHANNEL)))
MIN_POOL_SIZE = int(os.getenv("MIN_POOL_SIZE", "5"))
REQUEST_TIMEOUT  = 10
SEED_MODE_ENV    = "SEED_MODE"
# v55 strict publishing controls.  A candidate must be a public job/client
# project, have a canonical URL and a verifiable posted date before it can be
# published.  DRY_RUN performs the whole pipeline except Telegram delivery.
STRICT_PUBLIC_ONLY = _env_bool("STRICT_PUBLIC_ONLY", True)
DRY_RUN = _env_bool("DRY_RUN", False)
TELEGRAM_CANARY = _env_bool("TELEGRAM_CANARY", False)
ML_FILTER_ENABLED = _env_bool("ML_FILTER_ENABLED", True)
ML_MIN_PROB = float(os.getenv("ML_MIN_PROB", "0.75"))
ML_MODEL_PATH = os.getenv("ML_MODEL_PATH", "ml_models/cybersec_title_model.joblib")
ENABLE_LOCAL_ML_RETRAIN = _env_bool("ENABLE_LOCAL_ML_RETRAIN", False)
# v56: passively logs accept/reject decisions as label_source="automatic"
# training samples (merged in from the v54 branch). This is purely a data
# collection toggle — it can NEVER move by itself into an active retrain,
# because ml_filter.maybe_retrain_from_db() only ever reads rows with
# label_source="human_verified". Disable if you don't want the extra
# writes to job_training_samples at all.
ENABLE_TRAINING_DATA_COLLECTION = _env_bool("ENABLE_TRAINING_DATA_COLLECTION", True)
LLM_CLASSIFIER_ENABLED = _env_bool("LLM_CLASSIFIER_ENABLED", True)   # Use Claude for borderline cases
LLM_CLASSIFIER_PROVIDER = os.getenv("LLM_CLASSIFIER_PROVIDER", "auto").strip().lower()
LLM_CLASSIFIER_MODEL = os.getenv("LLM_CLASSIFIER_MODEL", "").strip()
LLM_CLASSIFIER_CACHE_PATH = os.getenv("LLM_CLASSIFIER_CACHE_PATH", "llm_classifier_cache.json")
ENTRY_LEVEL_TARGET_RATIO = float(os.getenv("ENTRY_LEVEL_TARGET_RATIO", "0.60"))
# LinkedIn is capped at 60% of the selected send pool; the remaining 40% is
# reserved for verified public ATS, Egyptian and contract/remote sources.
LINKEDIN_POOL_CAP_RATIO = float(os.getenv("LINKEDIN_POOL_CAP_RATIO", "0.60"))
NON_LINKEDIN_POOL_FLOOR_RATIO = float(os.getenv("NON_LINKEDIN_POOL_FLOOR_RATIO", "0.40"))

# Secondary (non-LinkedIn) source keys allowed to fill the protected 40%.
# Anything outside this set is low-priority filler only.
APPROVED_SECONDARY_SOURCE_KEYS = {
    "wuzzuf", "bayt", "akhtaboot", "gulftalent", "tanqeeb", "egytech_fyi",
    "upwork", "freelancer", "mostaql", "contra", "peopleperhour", "guru", "workana",
    # v56: registered alongside the other sources during the merge, but was
    # missing from this set — meaning it was being treated as low-priority
    # filler (Phase 4) instead of counting toward the protected ~20%
    # non-LinkedIn floor (Phase 1) like the rest of the Egyptian boards.
    "wazzif",
    # Official public ATS APIs: Greenhouse, Lever, Ashby and SmartRecruiters.
    "greenhouse_cybersec", "greenhouse_expanded", "expanded_sources", "tech_boards",
    "hackerone", "semgrep", "vanta", "weaviate", "bugcrowd", "cloudflare",
    "cato_networks", "mattermost", "sumo_logic", "cockroach_labs", "tenable", "wiz",
    "watchguard", "coalfire", "palantir", "lumin_digital", "true_zero_technologies",
    "visa", "jsearch_enhanced",
    # Direct, free remote/contract feeds with canonical URLs and dates.
    "remotive_security", "remoteok_security", "wwr_security", "arbeitnow_security",
}
LINKEDIN_ASYNC_MAX_CONCURRENCY = int(os.getenv("LINKEDIN_ASYNC_MAX_CONCURRENCY", "14"))
TELEGRAM_RETRY_MAX_ATTEMPTS = int(os.getenv("TELEGRAM_RETRY_MAX_ATTEMPTS", "6"))
TELEGRAM_RETRY_BASE_DELAY_SECONDS = int(os.getenv("TELEGRAM_RETRY_BASE_DELAY_SECONDS", "45"))
TELEGRAM_RETRY_DRAIN_LIMIT = int(os.getenv("TELEGRAM_RETRY_DRAIN_LIMIT", "25"))
SOURCE_HEALTH_MIN_SUCCESS = int(os.getenv("SOURCE_HEALTH_MIN_SUCCESS", "1"))
# ✅ v47: Lowered from 4 → 3 consecutive failures to auto-disable dead sources faster.
# Sources like MENA Boards, Jobzella, NaukriGulf return 0 jobs consistently — this
# reduces wasted time waiting on dead endpoints each run.
SOURCE_AUTO_DISABLE_THRESHOLD = int(os.getenv("SOURCE_AUTO_DISABLE_THRESHOLD", "3"))
# ✅ v47: Raised quarantine from 180 → 360 min (6h) — aligns with the 4h run schedule
# so a failed source is retried after the NEXT run completes, not mid-session.
SOURCE_QUARANTINE_MINUTES = int(os.getenv("SOURCE_QUARANTINE_MINUTES", "360"))
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
ENABLE_SOURCE_LINKEDIN_HR_POSTS = _env_bool("ENABLE_SOURCE_LINKEDIN_HR_POSTS", False)
ENABLE_SOURCE_REMOTIVE_SECURITY = _env_bool("ENABLE_SOURCE_REMOTIVE_SECURITY", True)
ENABLE_SOURCE_REMOTEOK_SECURITY = _env_bool("ENABLE_SOURCE_REMOTEOK_SECURITY", True)
ENABLE_SOURCE_WWR_SECURITY = _env_bool("ENABLE_SOURCE_WWR_SECURITY", True)
ENABLE_SOURCE_ARBEITNOW_SECURITY = _env_bool("ENABLE_SOURCE_ARBEITNOW_SECURITY", True)
# WAF/session-bound HTML marketplaces are diagnostic-only.  They are retained
# for troubleshooting but are not allowed to add repeated blocked/zero rows to
# a normal run.  The public API/RSS sources above replace their main role.
ENABLE_LEGACY_MARKETPLACE_SOURCES = _env_bool("ENABLE_LEGACY_MARKETPLACE_SOURCES", False)
ENABLE_SOURCE_WUZZUF = _env_bool("ENABLE_SOURCE_WUZZUF", True)

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
    "wuzzuf_rss":     "Wuzzuf RSS",
    "bayt_egypt":     "Bayt Egypt",
    "egytech_fyi":    "EgyTech.fyi",
    "forasna":        "Forasna",
    "bayt":           "Bayt.com",
    "gulftalent":     "GulfTalent Direct",
    "jobzella":       "Jobzella Gulf",
    "naukrigulf":     "NaukriGulf",
    "drjobpro":       "Dr.Job Pro",
    "akhtaboot":      "Akhtaboot",
    "wazzif":         "Wazzif (وظف)",
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
    "expanded_sources": "AKM Expanded Sources",
    "tech_boards": "AKM Tech Boards",
    "gulf_boards": "AKM Monster Gulf RSS",
    "linkedin_api": "AKM JSearch LinkedIn API",
    "remotive_security": "Remotive",
    "remoteok_security": "RemoteOK",
    "wwr_security": "We Work Remotely",
    "arbeitnow_security": "Arbeitnow",
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
ENABLE_SOURCE_EXPANDED            = _env_bool("ENABLE_SOURCE_EXPANDED", True)
ENABLE_SOURCE_TECH_BOARDS         = _env_bool("ENABLE_SOURCE_TECH_BOARDS", True)
ENABLE_SOURCE_GULF_BOARDS         = _env_bool("ENABLE_SOURCE_GULF_BOARDS", False)
ENABLE_SOURCE_LINKEDIN_API        = _env_bool("ENABLE_SOURCE_LINKEDIN_API", False)

GREENHOUSE_EXPANDED_TIMEOUT_SEC = int(os.getenv("GREENHOUSE_EXPANDED_TIMEOUT_SEC", "480"))
JSEARCH_PAGES_LOCAL             = int(os.getenv("JSEARCH_PAGES_LOCAL", "1"))
JSEARCH_PAGES_REMOTE            = int(os.getenv("JSEARCH_PAGES_REMOTE", "1"))

# ── v47: Source flags ─────────────────────────────────────────────────────
ENABLE_SOURCE_LINKEDIN_EXTENDED = False     # deprecated — queries merged into linkedin_unified
ENABLE_JINA_SCRAPER             = _env_bool("ENABLE_JINA_SCRAPER", True)
# The legacy aggregate overlaps the dedicated strict marketplace connectors.
# Keep it opt-in so Wazzif/Akhtaboot/Tanqeeb are never fetched twice.
ENABLE_SOURCE_MENA_BOARDS       = _env_bool("ENABLE_SOURCE_MENA_BOARDS", False)
# v56: Wazzif (وظف) is registered on its own — it does not overlap
# mena_boards.py (see source_registry.py) so it is safe to leave on by default.
ENABLE_SOURCE_WAZZIF            = _env_bool("ENABLE_SOURCE_WAZZIF", True)
LINKEDIN_EXTENDED_MAX_JOBS      = int(os.getenv("LINKEDIN_EXTENDED_MAX_JOBS", "10"))

# ── v56: Optional rotating-proxy pool (merged in from the v54 branch) ──────
# Every HTTP call in sources/http_utils.py stays direct-only unless both
# ENABLE_PROXY_POOL=true and PROXIES are set. Format: comma-separated
# "scheme://user:pass@host:port" entries. Leave the flag false for public
# ATS APIs and feeds.
#   PROXIES=http://user:pass@1.2.3.4:8000,http://user:pass@5.6.7.8:8000
# sources/regional_boards.py explicitly opts individual calls out of the pool
# (use_proxy=False) for boards that reject proxied traffic.
