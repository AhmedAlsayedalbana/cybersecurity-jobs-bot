"""
Configuration for Cybersecurity Jobs Telegram Bot.
Specialized 100% for Cybersecurity roles.
Priority: Egypt 🇪🇬 → Gulf 🌙 → Remote 🌍
"""

import os

# ─── Telegram ───────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_GROUP_ID  = os.getenv("TELEGRAM_GROUP_ID", "")
TELEGRAM_SEND_DELAY = 2  # Optimized delay

# ─── Community Topics ────────────────────────────────────────
CHANNELS = {
    "egypt": {
        "thread_env": "TOPIC_EGYPT",
        "name": "🇪🇬 Egypt Jobs",
        "match": "GEO_EGYPT",
    },
    "gulf": {
        "thread_env": "TOPIC_GULF",
        "name": "🌙 Gulf Jobs (KSA/UAE/Qatar/Kuwait)",
        "match": "GEO_GULF",
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
            "infrastructure security", "network security engineer", "firewall engineer",
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
    "egypt", "مصر", "egyptian",
    "cairo", "القاهرة", "new cairo", "nasr city", "مدينة نصر",
    "maadi", "المعادي", "heliopolis", "مصر الجديدة", "dokki", "الدقي",
    "mohandessin", "المهندسين", "zamalek", "الزمالك",
    "6th of october", "6 october", "smart village", "العبور",
    "new capital", "العاصمة الإدارية", "obour", "شبرا",
    "ain shams", "عين شمس", "shoubra", "المرج", "el marg",
    "15th of may", "15 مايو", "badr city", "مدينة بدر",
    "giza", "الجيزة", "6th october", "sheikh zayed", "الشيخ زايد",
    "october city", "hadayek october", "al haram", "الهرم",
    "imbaba", "إمبابة", "bulaq", "بولاق",
    "alexandria", "الإسكندرية", "alex", "smouha", "سموحة",
    "miami", "ميامي اسكندرية", "sidi bishr", "سيدي بشر",
    "agami", "العجمي", "montazah", "المنتزه",
    "mansoura", "المنصورة", "tanta", "طنطا",
    "zagazig", "الزقازيق", "benha", "بنها",
    "damanhour", "دمنهور", "menouf", "منوف",
    "kafr el sheikh", "كفر الشيخ", "shibin", "شبين",
    "mit ghamr", "meet ghamr", "dakahlia", "الدقهلية",
    "sharqia", "الشرقية", "gharbiya", "الغربية",
    "monufia", "المنوفية", "beheira", "البحيرة",
    "port said", "بورسعيد", "suez", "السويس",
    "ismailia", "الإسماعيلية", "ismailiya",
    "assiut", "أسيوط", "aswan", "أسوان", "luxor", "الأقصر",
    "sohag", "سوهاج", "qena", "قنا", "minya", "المنيا",
    "beni suef", "بني سويف", "fayoum", "الفيوم",
    "hurghada", "الغردقة", "sharm el sheikh", "شرم الشيخ",
    "el gouna", "الجونة", "ain sokhna", "العين السخنة",
    "dahab", "دهب", "marsa alam", "مرسى علم",
    "new alamein", "العلمين الجديدة", "new assiut", "أسيوط الجديدة",
    "new sohag", "new mansoura", "المنصورة الجديدة",
    "10th of ramadan", "العاشر من رمضان",
    "damietta", "دمياط", "qalyubia", "القليوبية", "faiyum", "الفيوم",
}

GULF_PATTERNS = {
    "saudi arabia", "saudi", "ksa", "السعودية", "المملكة العربية السعودية",
    "riyadh", "الرياض", "jeddah", "جدة", "dammam", "الدمام",
    "khobar", "الخبر", "dhahran", "الظهران", "neom", "نيوم",
    "mecca", "مكة", "medina", "المدينة", "jubail", "الجبيل",
    "yanbu", "ينبع", "tabuk", "تبوك", "abha", "أبها",
    "khamis mushait", "خميس مشيط", "taif", "الطائف",
    "hail", "حائل", "najran", "نجران", "jizan", "جازان",
    "uae", "united arab emirates", "الإمارات", "dubai", "دبي",
    "abu dhabi", "أبوظبي", "sharjah", "الشارقة", "ajman", "عجمان",
    "ras al khaimah", "رأس الخيمة", "fujairah", "الفجيرة",
    "umm al quwain", "أم القيوين", "al ain", "العين",
    "kuwait", "الكويت", "kuwait city", "مدينة الكويت",
    "hawalli", "حولي", "salmiya", "السالمية", "ahmadi", "الأحمدي",
    "qatar", "قطر", "doha", "الدوحة", "al wakra", "الوكرة",
    "lusail", "لوسيل", "al khor", "الخور",
    "bahrain", "البحرين", "manama", "المنامة",
    "muharraq", "المحرق", "riffa", "الرفاع",
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
EXCLUDE_KEYWORDS = [
    "sales", "marketing", "recruiter", "hr manager", "accountant",
    "customer service", "receptionist", "driver", "chef", "nurse",
    "civil engineer", "mechanical engineer", "electrical engineer",
    "physician", "teacher", "professor", "legal counsel",
    "business development", "sales manager", "marketing manager",
]

# ─── Performance & Limits ────────────────────────────────────
REQUEST_TIMEOUT = 15
MAX_JOBS_PER_RUN = 20
SCORE_THRESHOLD = 15  # Minimum score to be sent

# ─── Egypt Private Sector Companies ──────────────────────────
EG_PRIVATE_COMPANIES = [
    "CIB Egypt", "National Bank of Egypt", "Banque Misr", "QNB Alahli",
    "HSBC Egypt", "Alex Bank", "Arab African International Bank",
    "Vodafone Egypt", "Orange Egypt", "Etisalat Egypt", "Telecom Egypt",
    "Fawry", "Paymob", "Vezeeta", "Khazna", "Kashier", "Valify",
    "Raya", "ITWorx", "Xceed", "Valeo Egypt", "Dell Technologies Egypt",
    "IBM Egypt", "Microsoft Egypt", "Oracle Egypt", "Amazon Egypt",
    "Instabug", "Swvl", "Breadfast", "Trella", "MaxAB",
]
