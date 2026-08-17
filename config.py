"""
Configuration for Cybersecurity Jobs Telegram Bot.
Specialized 100% for Cybersecurity roles.
Location policy: physical/hybrid Egypt or any Arab country; explicit Remote worldwide.
Delivery order: confirmed cyber evidence, freshness, then the requested source order.
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
# Private review topic used for blind human labels.  It is deliberately not a
# routing destination for public job posts.
TOPIC_REVIEW = _optional_int("TOPIC_REVIEW")
TELEGRAM_REVIEWER_IDS = frozenset(
    int(value) for value in os.getenv("TELEGRAM_REVIEWER_IDS", "").split(",")
    if value.strip().isdigit()
)

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
        # Keep the key and environment variable for backwards compatibility
        # with the already-configured Telegram topic. The public channel is
        # now the full Arab region, not the former KSA/UAE/Kuwait subset.
        "name": " Arab Jobs",
        "match": "GEO_ARAB",
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

ARAB_PATTERNS = {
    # Arabian Peninsula / Gulf
    "saudi arabia", "saudi", "ksa", "riyadh", "jeddah", "dammam",
    "khobar", "dhahran", "neom", "mecca", "makkah", "medina", "madinah",
    "jubail", "yanbu", "tabuk", "abha", "khamis mushait", "taif", "hail",
    "najran", "jizan", "السعودية", "الرياض", "جدة",
    "uae", "united arab emirates", "dubai", "abu dhabi", "sharjah", "ajman",
    "ras al khaimah", "fujairah", "umm al quwain", "al ain", "الإمارات", "دبي", "أبو ظبي",
    "qatar", "doha", "al wakra", "lusail", "al khor", "قطر", "الدوحة",
    "kuwait", "kuwait city", "hawalli", "salmiya", "ahmadi", "الكويت",
    "bahrain", "manama", "muharraq", "riffa", "البحرين", "المنامة",
    "oman", "muscat", "sohar", "salalah", "nizwa", "عمان", "مسقط",
    "yemen", "sanaa", "aden", "اليمن", "صنعاء", "عدن",
    # Levant and Iraq
    "jordan", "amman", "irbid", "zarqa", "الأردن", "إربد",
    "lebanon", "beirut", "tripoli lebanon", "لبنان", "بيروت",
    "syria", "damascus", "aleppo", "homs", "سوريا", "دمشق", "حلب",
    "iraq", "baghdad", "erbil", "basra", "العراق", "بغداد", "أربيل", "البصرة",
    "palestine", "ramallah", "gaza", "west bank", "فلسطين", "رام الله", "غزة",
    # North and East Africa
    "libya", "tripoli libya", "benghazi", "ليبيا", "طرابلس", "بنغازي",
    "tunisia", "tunis", "sfax", "تونس", "صفاقس",
    "algeria", "algiers", "oran", "الجزائر", "وهران",
    "morocco", "rabat", "casablanca", "marrakesh", "المغرب", "الرباط", "الدار البيضاء",
    "mauritania", "nouakchott", "موريتانيا", "نواكشوط",
    "sudan", "khartoum", "السودان", "الخرطوم",
    "somalia", "mogadishu", "الصومال", "مقديشو",
    "djibouti", "جيبوتي",
    "comoros", "moroni", "جزر القمر", "موروني",
}

# Sanitize pattern sets: remove empty strings and whitespace-only entries
# (these can be encoding artifacts that would otherwise match every string).
EGYPT_PATTERNS = set(sanitize_keywords(EGYPT_PATTERNS, min_len=2))
ARAB_PATTERNS = set(sanitize_keywords(ARAB_PATTERNS, min_len=2))
# Legacy readers still use this symbol and legacy connectors still emit a
# ``gulf`` geo hint. It deliberately points to the complete Arab-region set.
GULF_PATTERNS = ARAB_PATTERNS

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

# Source precedence is centralised so fetch metadata, pool selection, and
# Telegram queues all agree. Lower values are preferred. Keys without a
# dedicated connector are included now so a later connector gets this rank.
SOURCE_PRIORITY_BY_KEY = {
    # LinkedIn — always first
    "linkedin": 10, "linkedin_unified": 10, "linkedin_li_at": 10,
    "linkedin_hiring": 10, "linkedin_hr_hunter": 10, "linkedin_hr_post": 10,
    "linkedin_egypt_arabic": 10, "linkedin_egypt_companies": 10,
    "linkedin_gulf_companies": 10, "linkedin_arab": 10,
    # Official company careers, then direct ATS boards
    "company_careers": 20, "greenhouse_cybersec": 30,
    "greenhouse_expanded": 30, "greenhouse": 30, "lever": 30,
    "lever_expanded": 30,
    # General and regional job boards
    "indeed": 40, "bayt": 50, "gulftalent": 60, "naukrigulf": 70,
    "qureos": 80,
    # Egyptian / Arab boards
    "wuzzuf": 90, "forasna": 100, "tanqeeb": 110, "akhtaboot": 120,
    "wazzif": 130, "jobzella": 140, "shaghalni": 150,
    # Freelance platforms
    "upwork": 160, "freelancer": 170, "mostaql": 180, "khamsat": 190,
    "contra": 200, "peopleperhour": 210, "guru": 220, "workana": 230,
    "fiverr": 240, "toptal": 250,
    # Discovery / remote boards
    "glassdoor": 260, "wellfound": 270, "remoteok": 280, "remotive": 290,
    "wwr": 300, "workingnomads": 300,
    "hackernews": 310, "hacker_news": 310, "github": 320,
    "reddit": 330, "discord": 330, "reddit_discord": 330,
    "telegram_channels": 340,
}


def source_priority(source_key: str, default: int = 999) -> int:
    """Return the requested source rank without changing LinkedIn limits."""
    return SOURCE_PRIORITY_BY_KEY.get((source_key or "").strip().lower(), default)


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
TOTAL_RUN_BUDGET_SECONDS = int(os.getenv("TOTAL_RUN_BUDGET_SECONDS", "2400"))
# These are overlapping ceilings controlled by the single run deadline.  They
# must not be added together when estimating end-to-end runtime.
OTHER_SOURCES_BUDGET_SECONDS = int(os.getenv("OTHER_SOURCES_BUDGET_SECONDS", "180"))
# A single non-LinkedIn connector may not consume the shared 180s phase.  The
# deadline covers its direct attempt and every permitted fallback together.
# Per-connector ceilings.  LinkedIn has its own separately configured budget
# and is intentionally not governed by these values.
# - Fast public HTTP boards: 15 seconds
# - Official careers / ATS APIs: 30 seconds
# - JS-only browser fallback: 40 seconds maximum for the whole source
DIRECT_SOURCE_TIMEOUT_SECONDS = int(os.getenv("DIRECT_SOURCE_TIMEOUT_SECONDS", "15"))
CAREERS_API_SOURCE_TIMEOUT_SECONDS = int(os.getenv("CAREERS_API_SOURCE_TIMEOUT_SECONDS", "30"))
PLAYWRIGHT_SOURCE_TIMEOUT_SECONDS = int(os.getenv("PLAYWRIGHT_SOURCE_TIMEOUT_SECONDS", "40"))
PLAYWRIGHT_NAVIGATION_TIMEOUT_MS = int(os.getenv("PLAYWRIGHT_NAVIGATION_TIMEOUT_MS", "40000"))
# The registry currently contains roughly 70 independent connectors.  This is
# deliberately above that count so a slow early source cannot leave a later
# source (for example CIB blocking Amazon) waiting for a thread slot.
SOURCE_FETCH_MAX_WORKERS = int(os.getenv("SOURCE_FETCH_MAX_WORKERS", "80"))
FALLBACK_BUDGET_SECONDS = int(os.getenv("FALLBACK_BUDGET_SECONDS", "30"))
FILTERING_BUDGET_SECONDS = int(os.getenv("FILTERING_BUDGET_SECONDS", "90"))
# A small delivery extension lets a healthy, already-qualified queue finish
# fairly. It changes no cyber filter, channel cap, or dedup rule.
TELEGRAM_BUDGET_SECONDS = int(os.getenv("TELEGRAM_BUDGET_SECONDS", "180"))
# v61: 2x LinkedIn capacity — budget raised to ~1800s for jobs, 90s for HR.
# Query lanes: ~70-75 with curated high-yield combinations.
# Page/detail caps scaled proportionally to budget.
LINKEDIN_JOBS_BUDGET_SECONDS = int(os.getenv("LINKEDIN_JOBS_BUDGET_SECONDS", "1800"))
LINKEDIN_HR_POSTS_BUDGET_SECONDS = int(os.getenv("LINKEDIN_HR_POSTS_BUDGET_SECONDS", "90"))
LINKEDIN_TOTAL_BUDGET_SECONDS = LINKEDIN_JOBS_BUDGET_SECONDS + LINKEDIN_HR_POSTS_BUDGET_SECONDS
# v61: 72 query lanes (up from 36).  Budget doubled so more lanes can complete.
LINKEDIN_MAX_QUERIES_PER_RUN = int(os.getenv("LINKEDIN_MAX_QUERIES_PER_RUN", "75"))
# Pages per query kept at 9 for high-priority, 4-6 for rotating lanes.
LINKEDIN_MAX_PAGES_PER_QUERY = int(os.getenv("LINKEDIN_MAX_PAGES_PER_QUERY", "9"))
# v61: 600 pages/run (2x old cap) to match doubled budget.
LINKEDIN_MAX_PAGES_PER_RUN = int(os.getenv("LINKEDIN_MAX_PAGES_PER_RUN", "600"))
# v61: 1200 details/run (2x old cap).
LINKEDIN_MAX_DETAILS_PER_RUN = int(os.getenv("LINKEDIN_MAX_DETAILS_PER_RUN", "1200"))
# Rate kept safe — we run more queries in parallel but actual RPS is unchanged.
LINKEDIN_RATE_MAX_RPS = float(os.getenv("LINKEDIN_RATE_MAX_RPS", "0.65"))
# v61: 10 concurrent detail fetchers (was 8) for better throughput within RPS.
LINKEDIN_MAX_CONCURRENCY = int(os.getenv("LINKEDIN_MAX_CONCURRENCY", "10"))
# v61: 8 concurrent query lanes (was 6) — more lanes active simultaneously.
LINKEDIN_QUERY_CONCURRENCY = int(os.getenv("LINKEDIN_QUERY_CONCURRENCY", "8"))
LI_PRIMARY_BUDGET_SECONDS = int(
    os.getenv("LI_PRIMARY_BUDGET_SECONDS", str(LINKEDIN_SOURCE_BUDGET_SECONDS))
)
LI_HR_POST_BUDGET_SECONDS = int(os.getenv("LI_HR_POST_BUDGET_SECONDS", str(LINKEDIN_HR_POSTS_BUDGET_SECONDS)))
# Logs are intentionally sampled so a large batch remains readable, while a
# small withheld set (such as the three in the observed run) is shown in full.
RECENCY_AUDIT_SAMPLES_PER_BUCKET = int(os.getenv("RECENCY_AUDIT_SAMPLES_PER_BUCKET", "3"))
DELIVERY_WITHHELD_LOG_LIMIT = int(os.getenv("DELIVERY_WITHHELD_LOG_LIMIT", "8"))
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
ML_MODEL_MANIFEST_PATH = os.getenv("ML_MODEL_MANIFEST_PATH", "ml_models/cybersec_title_model.manifest.json")
ML_FEATURE_SCHEMA_VERSION = "cyber-job-features-v1"
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
# LinkedIn remains first within the fresh-first source ordering.  The normal
# cap is deliberately generous: when trusted secondary supply is scarce, we
# should not discard fresh verified LinkedIn vacancies just to manufacture a
# source mix.
LINKEDIN_POOL_CAP_RATIO = float(os.getenv("LINKEDIN_POOL_CAP_RATIO", "0.80"))
# Tiny pools are a different case: with only a handful of jobs, a 50/50 split
# keeps a single source from hiding every other discovery channel.  This does
# not affect normal production pools.
SMALL_POOL_DIVERSITY_MAX_SIZE = int(os.getenv("SMALL_POOL_DIVERSITY_MAX_SIZE", "10"))
SMALL_POOL_LINKEDIN_CAP_RATIO = float(os.getenv("SMALL_POOL_LINKEDIN_CAP_RATIO", "0.50"))
NON_LINKEDIN_POOL_FLOOR_RATIO = float(os.getenv("NON_LINKEDIN_POOL_FLOOR_RATIO", "0.20"))

# Secondary (non-LinkedIn) source_keys allowed to fill the protected minimum
# and the remaining capacity once the LinkedIn cap is reached.
# Anything NOT in this set (Greenhouse, Jina/Bayt-Gulf, Telegram, Reddit,
# JSearch, MENA/Gulf boards, etc.) is treated as low-priority filler only —
# it is used to top up the pool if, and only if, LinkedIn + approved
# secondary sources can't reach MIN_POOL_SIZE on their own.
APPROVED_SECONDARY_SOURCE_KEYS = {
    "wuzzuf", "bayt", "akhtaboot", "gulftalent", "tanqeeb", "egytech_fyi",
    "upwork", "freelancer", "mostaql", "contra", "peopleperhour", "guru", "workana",
    # v56: registered alongside the other sources during the merge, but was
    # missing from this set — meaning it was being treated as low-priority
    # filler (Phase 4) instead of counting toward the protected ~20%
    # non-LinkedIn floor (Phase 1) like the rest of the Egyptian boards.
    "wazzif",
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
# A few quarantined public sources are sampled each run for recovery.  This
# avoids silently losing a site for hours after a transient block or markup
# deployment, while preserving the circuit breaker for the full source set.
QUARANTINED_SOURCE_PROBE_LIMIT = int(os.getenv("QUARANTINED_SOURCE_PROBE_LIMIT", "4"))
ENABLE_SOURCE_PRIORITY_GATING = _env_bool("ENABLE_SOURCE_PRIORITY_GATING", True)

# ── v62 Egyptian priority execution budget ─────────────────────────────
# These official careers connectors are the highest-value non-LinkedIn
# supply for the Egypt channel.  They get a dedicated, per-source ceiling
# (separate from the generic 40s playwright cap) so Playwright is never
# killed by the shared source_deadline before a full careers-page render
# can complete, and they get execution budget across runs (health probes
# and quarantine exemptions) so they are not silently starved.
EGYPT_PRIORITY_SOURCE_KEYS = {
    # Banks
    "nbe", "banque_misr", "banque_du_caire", "cib_egypt", "cib_egypt_wd",
    "qnb_egypt", "qnb_global", "aaib", "adib_egypt", "saib", "bank_nxt",
    "fabmisr", "hdb", "emirates_nbd_egypt", "mashreq_egypt", "al_baraka_bank",
    "bank_abc", "credit_agricole_egypt", "hsbc_egypt",
    # Telecom / digital
    "telecom_egypt", "we_jina", "etisalat_egypt", "vodafone_egypt",
    "orange_egypt", "vois", "raya",
    # IT / infrastructure / industry / pharma
    "itida", "smart_village", "elsewedy_electric", "pharco",
    "orascom_construction",
}
# v64: per-source ceiling for Egyptian priority careers connectors.
# Covers the official endpoint attempt and, only when truly needed, one
# short JS-only Playwright pass.  Never below the generic playwright cap.
# A failing Egyptian bank must never consume more than this per run; the
# orchestrator's own deadline enforces the same cap.
EGYPT_PRIORITY_SOURCE_TIMEOUT_SECONDS = float(
    os.getenv("EGYPT_PRIORITY_SOURCE_TIMEOUT_SECONDS", "45")
)

ENABLE_EGYPT_PRIORITY_SOURCES = _env_bool("ENABLE_EGYPT_PRIORITY_SOURCES", True)
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
    from sources.egypt_employer_registry import validate_employer_registry
    validate_employer_registry()

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
ENABLE_SOURCE_ARAB_CAREERS       = _env_bool("ENABLE_SOURCE_ARAB_CAREERS", True)
ENABLE_SOURCE_RECRUITMENT       = _env_bool("ENABLE_SOURCE_RECRUITMENT", True)
LINKEDIN_EXTENDED_MAX_JOBS      = int(os.getenv("LINKEDIN_EXTENDED_MAX_JOBS", "10"))

# Cyber verdict and human-review controls.  LIKELY is a maximum fill policy:
# confirmed candidates are always selected first and are never displaced.
CYBER_LIKELY_MIN_PROB = float(os.getenv("CYBER_LIKELY_MIN_PROB", "0.60"))
CYBER_LIKELY_MAX_SHARE = float(os.getenv("CYBER_LIKELY_MAX_SHARE", "0.25"))
REVIEW_SAMPLE_SIZE = int(os.getenv("REVIEW_SAMPLE_SIZE", "80"))

# ── v56: Optional rotating-proxy pool (merged in from the v54 branch) ──────
# Every HTTP call in sources/http_utils.py stays direct-only unless PROXIES
# is set. Format: comma-separated "scheme://user:pass@host:port" entries.
# Leave unset to keep the exact v55 direct-only behaviour.
#   PROXIES=http://user:pass@1.2.3.4:8000,http://user:pass@5.6.7.8:8000
# No extra flag is needed to "turn it on" — presence of PROXIES is the
# switch. sources/regional_boards.py explicitly opts individual calls out of
# the pool (use_proxy=False) for boards that reject proxied traffic.

# ── v66: recovery scheduling separation ──────────────────────────────────────
# A source enters the sparse recovery rotation ONLY on real transport-level
# failures (blocked / repeated timeout / parser failure / circuit-open) and
# NEVER simply because it was not executed in the current run. Proven-yield
# sources that fetched jobs recently are protected from parking.
RECOVERY_RECENT_YIELD_MEMORY_DAYS: int = 7
RECOVERY_RECENT_YIELD_MIN_JOBS: int = 1
# v66: graduated cooldown after consecutive failures:
#   1 failure  → recheck next run
#   2 failures → every 2 runs
#   3+ failures → every 3..5 runs (capped at 5)
RECOVERY_GRADUATED_COOLDOWN: bool = True
# v66: an HR search backend that stays empty after this many consecutive
# checks (including forced stall-relaxation rechecks) is parked for the
# remainder of the run instead of being rechecked every query.
HR_BACKEND_MAX_EMPTY_STREAK_BEFORE_PARK: int = 8
# v66: a job that reaches the Telegram send loop eligible and routed but is
# blocked by a terminal channel state is recorded as delivery_pending so it
# is retried next run — never silently dropped and never counted as success.
TELEGRAM_DELIVERY_PENDING_ON_TERMINAL_STATE: bool = True
