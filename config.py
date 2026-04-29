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
            "exploit development", "oscp", "ceh", "gpen", "offensive-security",
            "malware analysis", "reverse engineering", "ctf",
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
            "siem analyst", "security monitoring", "splunk", "qradar", "sentinel",
            "edr", "xdr", "mdr", "threat detection",
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
            "owasp", "burp suite", "checkmarx", "snyk",
        ],
    },
    "cloudsec": {
        "thread_env": "TOPIC_CLOUDSEC",
        "name": "☁️ Cloud & Infrastructure Security",
        "keywords": [
            "cloud security", "cloud security engineer", "cloud security architect",
            "aws security", "azure security", "gcp security",
            "infrastructure security",
            "zero trust", "identity access management", "iam engineer",
            "kubernetes security", "container security", "cspm", "cnapp",
            "wiz", "prisma cloud", "cloud native security",
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
            "third party risk", "cyber risk", "security policy",
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
            "security tools developer", "python security",
        ],
    },
    "networksec": {
        "thread_env": "TOPIC_NETWORKSEC",
        "name": "🌐 Network Security Engineer",
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
        "name": "🌙 Gulf Jobs (KSA/UAE/Kuwait)",
        "match": "GEO_GULF",
    },
    "internships": {
        "thread_env": "TOPIC_INTERNSHIPS",
        "name": "🎓 Internships & Entry Level",
        "keywords": [
            "intern", "internship", "trainee", "junior", "entry level",
            "entry-level", "fresh graduate", "fresh grad", "graduate program",
            "junior security", "soc intern", "security intern", "0-1 years", "0-2 years",
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
SERPAPI_KEY      = os.getenv("SERPAPI_KEY", "")

# ─── Geo Patterns ────────────────────────────────────────────
EGYPT_PATTERNS = {
    # General
    "egypt", "مصر", "egyptian",
    # Cairo & districts
    "cairo", "القاهرة", "new cairo", "nasr city", "مدينة نصر",
    "maadi", "المعادي", "heliopolis", "مصر الجديدة", "dokki", "الدقي",
    "mohandessin", "المهندسين", "zamalek", "الزمالك",
    "6th of october", "6 october", "smart village", "العبور",
    "new capital", "العاصمة الإدارية", "obour", "شبرا",
    "ain shams", "عين شمس", "shoubra", "المرج", "el marg",
    "15th of may", "15 مايو", "badr city", "مدينة بدر",
    # Giza & surroundings
    "giza", "الجيزة", "6th october", "sheikh zayed", "الشيخ زايد",
    "october city", "hadayek october", "al haram", "الهرم",
    "imbaba", "إمبابة", "bulaq", "بولاق",
    # Alexandria
    "alexandria", "الإسكندرية", "alex", "smouha", "سموحة",
    "miami", "ميامي اسكندرية", "sidi bishr", "سيدي بشر",
    "agami", "العجمي", "montazah", "المنتزه",
    # Nile Delta
    "mansoura", "المنصورة", "tanta", "طنطا",
    "zagazig", "الزقازيق", "benha", "بنها",
    "damanhour", "دمنهور", "menouf", "منوف",
    "kafr el sheikh", "كفر الشيخ", "shibin", "شبين",
    "mit ghamr", "meet ghamr", "dakahlia", "الدقهلية",
    "sharqia", "الشرقية", "gharbiya", "الغربية",
    "monufia", "المنوفية", "beheira", "البحيرة",
    # Canal Zone
    "port said", "بورسعيد", "suez", "السويس",
    "ismailia", "الإسماعيلية", "ismailiya",
    # Upper Egypt
    "assiut", "أسيوط", "aswan", "أسوان", "luxor", "الأقصر",
    "sohag", "سوهاج", "qena", "قنا", "minya", "المنيا",
    "beni suef", "بني سويف", "fayoum", "الفيوم",
    # Red Sea & Sinai
    "hurghada", "الغردقة", "sharm el sheikh", "شرم الشيخ",
    "el gouna", "الجونة", "ain sokhna", "العين السخنة",
    "dahab", "دهب", "marsa alam", "مرسى علم",
    # New Cities
    "new alamein", "العلمين الجديدة", "new assiut", "أسيوط الجديدة",
    "new sohag", "new mansoura", "المنصورة الجديدة",
    "10th of ramadan", "العاشر من رمضان",
}

GULF_PATTERNS = {
    # Saudi Arabia
    "saudi arabia", "saudi", "ksa", "السعودية", "المملكة العربية السعودية",
    "riyadh", "الرياض", "jeddah", "جدة", "dammam", "الدمام",
    "khobar", "الخبر", "dhahran", "الظهران", "neom", "نيوم",
    "mecca", "مكة", "medina", "المدينة", "jubail", "الجبيل",
    "yanbu", "ينبع", "tabuk", "تبوك", "abha", "أبها",
    "khamis mushait", "خميس مشيط", "taif", "الطائف",
    "hail", "حائل", "najran", "نجران", "jizan", "جازان",
    # UAE
    "uae", "united arab emirates", "الإمارات", "dubai", "دبي",
    "abu dhabi", "أبوظبي", "sharjah", "الشارقة", "ajman", "عجمان",
    "ras al khaimah", "رأس الخيمة", "fujairah", "الفجيرة",
    "umm al quwain", "أم القيوين", "al ain", "العين",
    # Kuwait
    "kuwait", "الكويت", "kuwait city", "مدينة الكويت",
    "hawalli", "حولي", "salmiya", "السالمية", "ahmadi", "الأحمدي",
    # Qatar
    "qatar", "قطر", "doha", "الدوحة", "al wakra", "الوكرة",
    "lusail", "لوسيل", "al khor", "الخور",
    # Bahrain
    "bahrain", "البحرين", "manama", "المنامة",
    "muharraq", "المحرق", "riffa", "الرفاع",
    # Oman
    "oman", "عُمان", "muscat", "مسقط", "sohar", "صحار",
    "salalah", "صلالة", "nizwa", "نزوى",
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
    "linkedin_hiring": "LinkedIn #Hiring",
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
MAX_JOBS_PER_RUN = 200
SCORE_THRESHOLD  = 12   # V35: raised to 12 — requires real tech match, not just location bonus
MAX_JOBS_PER_CHANNEL = 7   # V33: raised from 5 — ensures all channels receive enough jobs
REQUEST_TIMEOUT  = 10
SEED_MODE_ENV    = "SEED_MODE"

# ─── New Sources ──────────────────────────────────────────────
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
    "google_jobs":    "Google Jobs",
    "adzuna_mena":    "Adzuna MENA",
    "linkedin_egypt_companies": "LinkedIn (EG Companies)",
    "linkedin_gulf_companies":  "LinkedIn (Gulf Companies)",
    "stc_ksa":        "STC Saudi Arabia",
    "tdra_uae":       "TDRA UAE",
    "etisalat_uae":   "e& UAE",
})
