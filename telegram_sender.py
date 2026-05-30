"""
Telegram message formatting and multi-topic sending.
KEY FEATURE: balanced per-channel sending with per-channel dedup.
Format: matches reference telegram_sender exactly.
"""

import re
import time
import logging
import requests
from datetime import datetime, timedelta
from models import Job, _flatten_tags
from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_GROUP_ID, TELEGRAM_SEND_DELAY,
    CHANNELS, get_topic_thread_id,
    DAILY_SEND_HOURS, MAX_JOBS_PER_CHANNEL,
    TELEGRAM_RETRY_MAX_ATTEMPTS, TELEGRAM_RETRY_BASE_DELAY_SECONDS,
    TELEGRAM_RETRY_DRAIN_LIMIT,
)
from database import JobsDB, get_db
from job_intelligence import (
    classify_domain as classify_intelligence_domain,
    classify_geo,
    classify_level as classify_intelligence_level,
    classify_role as classify_intelligence_role,
    is_remote_job as intelligence_is_remote_job,
    is_true_security_internship,
)

log = logging.getLogger(__name__)


# 
#  Geo Helpers
# 

def _is_egypt_job(job):
    return classify_geo(job) == "egypt"

def _is_gulf_job(job):
    return classify_geo(job) in {"ksa", "gulf_other"}

def _is_remote_job(job):
    return intelligence_is_remote_job(job)


def _is_true_internship_job(job) -> bool:
    """Strict internship check to avoid leaking generic jobs into internships channel."""
    return is_true_security_internship(job)


# 
#  Routing � which channels gets this job
# 

def _channel_priority(ch_key: str) -> int:
    """
    Returns priority rank for a channel key.
    Lower number = higher specificity = wins when a job matches multiple channels.
    Specialty topic channels beat geo channels beat catch-all.
    
    FIXED v38: internships now has lowest topic priority (3) � it only receives
    jobs that didn't match any specific domain channel. This prevents a
    "Junior Penetration Tester" from appearing in both pentest AND internships.
    """
    PRIORITY = {
        # Most specific specialty topics first (level 1)
        "networksec":  1,
        "pentest":     1,
        "soc":         1,
        "appsec":      1,
        "cloudsec":    1,
        "grc":         1,
        # Broad specialty (level 2)
        "seceng":      2,
        # Catch-all topic � only gets jobs that didn't match anything above (level 3)
        "internships": 3,
        # Geo channels (level 4 � separate pool, not competing with topics)
        "egypt":       4,
        "gulf":        4,
        "remote":      4,
    }
    return PRIORITY.get(ch_key, 5)


def route_job(job):
    """
    Route a job to channels � v29 model:

    GEO channels  (egypt / gulf / remote): based on location only.
    TOPIC channels (soc / grc / pentest / ...): based on keywords only.

    A job CAN and SHOULD appear in BOTH a geo channel AND a topic channel.
    Example: "GRC Analyst in Cairo"  egypt + grc 

    Within topic channels, if a job matches multiple topics, it goes to the
    HIGHEST-priority (most specific) one only to avoid topic channel flooding.
    Within geo channels, a job goes to exactly one geo channel.
    """
    # Geo routing: one geo lane only. Egypt wins, then Gulf, then true remote.
    geo_result = []
    geo = classify_geo(job)
    if geo == "egypt":
        geo_result = ["egypt"]
    elif geo in {"ksa", "gulf_other"}:
        geo_result = ["gulf"]
    elif geo == "remote" or _is_remote_job(job):
        geo_result = ["remote"]

    # Topic routing: exactly one specialty topic when the central classifier is confident.
    topic_result = []
    topic_channel = _topic_channel_for_job(job, "")
    if topic_channel and topic_channel in CHANNELS:
        topic_result = [topic_channel]

    return geo_result + topic_result


def _topic_channel_for_job(job, searchable: str) -> str | None:
    """Choose one specialty channel using the same domain model as formatting."""
    if _is_true_internship_job(job):
        return "internships"
    decision = classify_intelligence_role(job)
    return decision.channel_key or None


def _post_telegram_payload(payload: dict) -> tuple[bool, int, str, int | None]:
    """
    Returns: (success, status_code, error_text, retry_after_seconds)
    """
    try:
        resp = requests.post(
            "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendMessage",
            json=payload,
            timeout=10,
        )
        if resp.status_code == 200:
            return True, 200, "", None
        retry_after = None
        if resp.status_code == 429:
            try:
                data = resp.json()
                retry_after = int((data.get("parameters") or {}).get("retry_after") or 0) or None
            except Exception:
                retry_after = None
        return False, resp.status_code, (resp.text or "")[:300], retry_after
    except Exception as exc:
        return False, 0, str(exc), None


def _compute_retry_delay(attempts: int, retry_after: int | None = None) -> int:
    if retry_after and retry_after > 0:
        return min(600, max(10, retry_after + 2))
    base = max(10, TELEGRAM_RETRY_BASE_DELAY_SECONDS)
    return min(900, base * (2 ** max(0, attempts)))


def _drain_retry_queue(db: JobsDB) -> int:
    sent = 0
    for row in db.get_due_telegram_retries(limit=TELEGRAM_RETRY_DRAIN_LIMIT):
        payload = row.get("payload") or {}
        ok, status, err, retry_after = _post_telegram_payload(payload)
        if ok:
            db.mark_telegram_retry_sent(row["id"])
            sent += 1
            time.sleep(0.7)
            continue
        delay = _compute_retry_delay(row.get("attempts", 0), retry_after=retry_after)
        # Hard fail on non-transient errors (4xx except rate-limit).
        hard_fail = status in {400, 401, 403, 404}
        db.mark_telegram_retry_attempt(
            row["id"],
            error=f"status={status} {err}".strip(),
            delay_seconds=delay,
            force_fail=hard_fail,
        )
    return sent


def _domain_affinity_score(job, ch_key: str) -> int:
    """
    Score how well a job matches a topic channel for smart fallback ordering.
    Used only when a channel has no direct-match jobs.

    Returns:
        3  — job domain exactly matches the channel
        2  — job is broad seceng / general cyber
        1  — any other accepted cyber job
        0  — internship channel (never use random fallback)
    """
    if ch_key == "internships":
        return 0
    job_domain = classify_intelligence_domain(job)
    if job_domain == ch_key:
        return 3
    if job_domain == "seceng":
        return 2
    return 1


# ---------------------------------------------------------------------------
# Channel→Domain affinity map for smart fallback
# Defines which domain classifications are "close enough" to fill a channel
# when there are no direct-match jobs.
# ---------------------------------------------------------------------------
_CHANNEL_DOMAIN_AFFINITY: dict[str, list[str]] = {
    "soc":       ["soc", "seceng"],
    "pentest":   ["pentest", "seceng"],
    "appsec":    ["appsec", "seceng"],
    "cloudsec":  ["cloudsec", "seceng", "networksec"],
    "networksec":["networksec", "seceng", "cloudsec"],
    "grc":       ["grc", "seceng"],
    "seceng":    ["seceng", "soc", "appsec", "cloudsec", "networksec", "grc", "pentest"],
    # internships: NEVER use fallback — only true internship jobs
}


def send_jobs(jobs):
    """
    Send jobs to Telegram channels — v47 rules:

    - A job appears in at most 1 GEO channel + at most 1 TOPIC channel.
    - Each lane has its own DAILY_SEND_HOURS dedup window.
    - MAX_JOBS_PER_CHANNEL = 10 per run.
    - v47 FIX: Smart domain-affinity fallback — a channel with no direct-match
      jobs receives only jobs whose domain is related to that channel.
      The 'internships' channel NEVER uses fallback: it only sends true internships.
    - Jobs sorted by score desc — best jobs go first.
    """
    from scoring import score_job_int, score_job

    total_sent = 0
    channel_summary = {}

    GEO_CHANNELS   = ["remote", "egypt", "gulf"]
    TOPIC_CHANNELS = [k for k in CHANNELS.keys() if k not in GEO_CHANNELS]
    send_order     = GEO_CHANNELS + TOPIC_CHANNELS

    active = [k for k in send_order if get_topic_thread_id(k)]
    missing = [k for k in send_order if not get_topic_thread_id(k)]
    log.info(f" Active channels ({len(active)}): {', '.join(active)}")
    if missing:
        log.warning(f"  Missing thread IDs for: {', '.join(missing)} — skipping those")

    # Sort jobs by score
    jobs_scored = sorted(jobs, key=lambda j: -score_job_int(j))

    # Build per-channel queues (primary routing — exact domain match)
    channel_queues = {key: [] for key in CHANNELS.keys()}
    for job in jobs_scored:
        for ch_key in route_job(job):
            if ch_key in channel_queues:
                channel_queues[ch_key].append(job)

    # v47 Smart Fallback: for topic channels with no direct-match jobs,
    # fill with domain-related jobs only (never random / unrelated jobs).
    # The 'internships' channel is EXCLUDED from fallback entirely.
    for ch_key in TOPIC_CHANNELS:
        if not get_topic_thread_id(ch_key):
            continue
        if channel_queues[ch_key]:
            continue
        log.info(f" [{ch_key}] strict routing: 0 direct role matches; no fallback used")
        continue
        if ch_key == "internships":
            # Internships channel must stay empty if no true internship jobs exist.
            log.info(f" [{ch_key}] No true internship/entry-level jobs — channel skipped (correct)")
            continue

        affinity_domains = _CHANNEL_DOMAIN_AFFINITY.get(ch_key, [])
        if not affinity_domains:
            continue

        # Cache domain per job to avoid repeated classification calls
        def _job_domain(j, _cache={}):  # noqa: B006
            jid = id(j)
            if jid not in _cache:
                _cache[jid] = classify_intelligence_domain(j)
            return _cache[jid]

        # Collect jobs whose domain is in the affinity list, ordered by affinity rank then score
        fallback = sorted(
            [j for j in jobs_scored if _job_domain(j) in affinity_domains],
            key=lambda j: (
                # Primary: affinity rank (lower index = better match)
                affinity_domains.index(_job_domain(j))
                if _job_domain(j) in affinity_domains
                else 99,
                # Secondary: score descending
                -score_job_int(j),
            ),
        )
        if fallback:
            channel_queues[ch_key] = fallback[:20]
            domains_found = list(dict.fromkeys(
                _job_domain(j) for j in fallback[:5]
            ))
            log.info(
                f" [{ch_key}] No direct-match jobs — using {len(fallback[:20])} "
                f"domain-affinity fallback jobs (domains: {', '.join(d for d in domains_found if d)})"
            )
        else:
            log.info(f" [{ch_key}] No direct-match or affinity jobs — channel skipped")

    limit = MAX_JOBS_PER_CHANNEL
    sent_records = []
    db = get_db()
    retried_sent = _drain_retry_queue(db)
    if retried_sent:
        log.info(f" Retry queue: resent {retried_sent} pending Telegram message(s)")
    channel_cursors = {k: 0 for k in send_order}
    channel_titles_sent = {k: set() for k in send_order}
    channel_dedup_sent = {k: set() for k in send_order}
    channel_summary = {k: 0 for k in send_order}

    for ch_key in send_order:
        if not get_topic_thread_id(ch_key):
            continue
        if not channel_queues.get(ch_key):
            ch_name = CHANNELS.get(ch_key, {}).get("name", ch_key)
            log.info(f" [{ch_key}] {ch_name}: 0 matching jobs this run")

    # Round-robin send loop for fair per-channel distribution.
    while True:
        progress = False
        for ch_key in send_order:
            thread_id = get_topic_thread_id(ch_key)
            if not thread_id:
                continue
            if channel_summary[ch_key] >= limit:
                continue
            queue = channel_queues.get(ch_key, [])
            if not queue:
                continue

            is_geo = ch_key in GEO_CHANNELS
            lane = "geo" if is_geo else "topic"
            sent_job = False

            while channel_cursors[ch_key] < len(queue):
                job = queue[channel_cursors[ch_key]]
                channel_cursors[ch_key] += 1

                title_key = re.sub(r"\s+", " ", (job.title or "").strip().lower())
                url_id = getattr(job, "url_id", "")
                job_dedup_key = getattr(job, "dedup_key", "") or url_id or job.url or job.unique_id

                if title_key and title_key in channel_titles_sent[ch_key]:
                    continue
                if job_dedup_key in channel_dedup_sent[ch_key]:
                    continue

                if db.was_sent_to_channel_recently(
                    job_key=job.unique_id,
                    url_id=url_id,
                    channel_key=ch_key,
                    dedup_key=job_dedup_key,
                    hours=DAILY_SEND_HOURS,
                ):
                    continue

                message = format_job_message(job)
                success = _send_to_topic(
                    message,
                    thread_id=thread_id,
                    db=db,
                    channel_key=ch_key,
                )
                if not success:
                    continue

                channel_summary[ch_key] += 1
                total_sent += 1
                sent_records.append((job, lane, ch_key))
                channel_dedup_sent[ch_key].add(job_dedup_key)
                if title_key:
                    channel_titles_sent[ch_key].add(title_key)
                role = classify_intelligence_role(job)
                routing_reason = "geo_location" if is_geo else "strict_role_match"
                log.info(
                    f"   [{ch_key}] {channel_summary[ch_key]}/{limit} "
                    f"role={role.role_key or '-'} topic={role.channel_key or '-'} "
                    f"reason={routing_reason} ✓ {job.title[:50]}"
                )
                time.sleep(TELEGRAM_SEND_DELAY)
                progress = True
                sent_job = True
                break

            if not sent_job and channel_cursors[ch_key] >= len(queue):
                continue

        if not progress:
            break

    for ch_key in send_order:
        if not get_topic_thread_id(ch_key):
            continue
        ch_name = CHANNELS.get(ch_key, {}).get("name", ch_key)
        sent_this_ch = channel_summary.get(ch_key, 0)
        if sent_this_ch > 0:
            log.info(f" Channel [{ch_key}] {ch_name}: sent {sent_this_ch} jobs")
        elif channel_queues.get(ch_key):
            log.info(f" Channel [{ch_key}] {ch_name}: 0 sent (all filtered/deduped)")

    log.info("=" * 40)
    log.info(" Per-Channel Summary:")
    for k, v in channel_summary.items():
        ch_name = CHANNELS.get(k, {}).get("name", k)
        bar = "✅" if v > 0 else "⚪"
        log.info(f"   {bar} {ch_name}: {v} jobs")
    log.info("=" * 40)

    return total_sent, sent_records


def _escape(text):
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

_DOMAIN_LABELS = {
    "soc": "SOC / Blue Team",
    "pentest": "Penetration Testing / Red Team",
    "cloudsec": "Cloud Security",
    "appsec": "AppSec / DevSecOps",
    "networksec": "Network Security",
    "grc": "GRC / Compliance",
    "seceng": "Security Engineering",
    "internships": "Training / Program",
}

_LEVEL_LABELS = {
    "entry": "Entry-Level",
    "mid": "Mid-Level",
    "senior": "Senior",
    "open": "Open",
}


def _domain_label(job) -> str:
    return _DOMAIN_LABELS.get(classify_intelligence_domain(job), "Cybersecurity")


def _level_label(job) -> str:
    return _LEVEL_LABELS.get(classify_intelligence_level(job), "Open")


def _detect_level(text):
    if re.search(r"\b(?:intern|internship|junior|trainee|entry[-\s]?level|fresh grad|graduate)\b", text):
        return "Entry-Level"
    if re.search(r"\b(?:senior|sr\.?|lead|manager|principal|head|director|vp|chief)\b", text):
        return "Senior"
    if re.search(r"\b(?:mid|intermediate|associate)\b", text):
        return "Mid-Level"
    return "Open"

def _detect_domain(text):
    """
    Classify job domain. Uses word-boundary matching to reduce false positives.
    KEY RULE: title signals beat description signals.
    Network Security checked BEFORE GRC to avoid "nist" in desc hijacking network roles.
    """
    import re as _re
    def has(kws):
        return any(_re.search(r'\b' + _re.escape(k) + r'\b', text) for k in kws)

    #  Physical / non-cyber security � detected FIRST 
    if has(["security guard", "security officer", "physical security",
            "loss prevention", "event security", "building security",
            "security supervisor", "security patrol"]):
        if not has(["cyber", "information security", "infosec", "soc", "siem",
                    "network security", "cloud security", "penetration", "malware"]):
            return "Physical Security"

    # Most-specific title signals first
    if has(["soc analyst", "soc engineer", "soc manager", "security operations center",
            "security operations", "blue team", "threat detection", "security monitoring",
            "siem analyst", "threat hunter", "cyber defense",
            # BO/L1/L2/L3 tiers in security context
            "bo l1", "bo l2", "bo l3", "l1 security", "l2 security", "l3 security",
            "tier 1 security", "tier 2 security", "tier 3 security"]):
        return "SOC / Blue Team"
    if has(["pentest", "penetration test", "penetration tester", "red team",
            "ethical hack", "bug bounty", "offensive security", "exploit"]):
        return "Penetration Testing / Red Team"
    if has(["cloud security", "aws security", "azure security", "gcp security",
            "cloud native security", "cspm", "cnapp", "kubernetes security"]):
        return "Cloud Security"
    if has(["appsec", "application security", "devsecops", "sast", "dast", "owasp",
            "secure code", "product security"]):
        return "AppSec / DevSecOps"
    if has(["dfir", "digital forensics", "malware analyst", "malware analysis",
            "reverse engineer", "incident response analyst", "incident response engineer"]):
        return "DFIR / Forensics"
    # Network Security BEFORE GRC — "nist" keyword in description shouldn't override
    if has(["network security engineer", "network security analyst", "network security manager",
            "firewall engineer", "firewall administrator", "firewall specialist",
            "network defense", "waf engineer", "ddos", "vpn engineer",
            "zero trust", "palo alto", "fortinet", "cisco security",
            "intrusion detection", "intrusion prevention", "ids engineer", "ips engineer",
            # FIX v43: WiFi/Wireless roles misclassified → now go to networksec
            "wifi security", "wireless security", "wi-fi security",
            "wifi & firewall", "wifi and firewall", "wireless & firewall",
            # FIX v43: OT/ICS security
            "ot security", "ics security", "scada security", "operational technology security",
            # FIX v43: Vendor-specific security roles
            "palo alto expert", "palo alto engineer", "palo alto specialist",
            "fortinet engineer", "fortinet specialist", "fortinet expert",
            "checkpoint engineer", "checkpoint specialist",
            "network security architect", "network security specialist",
            "network & security", "network and security"]):
        return "Network Security"
    # GRC � only when title/tags actually indicate it
    if has(["grc analyst", "grc manager", "grc engineer", "compliance analyst",
            "compliance manager", "risk analyst", "risk manager", "security auditor",
            "it auditor", "iso 27001 lead", "nist framework", "data protection officer",
            "data protection manager", "data protection specialist", "data protection",
            "governance risk", "pci dss analyst", "gdpr officer", "privacy officer",
            "privacy manager", "senior manager data protection"]):
        return "GRC / Compliance"
    if has(["ciso", "security manager", "security director", "security lead",
            "head of security", "vp security", "chief security",
            "cybersecurity manager", "cybersecurity director"]):
        return "Security Management"
    if has(["security architect", "security architecture"]):
        return "Security Architecture"
    if has(["iam engineer", "identity access management", "pki engineer", "privileged access"]):
        return "IAM / Identity Security"
    if has(["security internship", "security trainee", "junior security", "security graduate",
            "internship cybersecurity", "scholarship security", "bootcamp security"]):
        return "Training / Program"
    # Broad fallbacks � only reached when no specific domain matched
    if has(["soc", "siem", "splunk", "qradar", "sentinel"]):
        return "SOC / Blue Team"
    if has(["network security", "firewall"]):
        return "Network Security"
    if has(["threat intel", "threat intelligence", "cti"]):
        return "DFIR / Forensics"
    if has(["grc", "iso 27001", "compliance", "nist", "auditor"]):
        return "GRC / Compliance"
    return "Cybersecurity"

def _detect_location_flag(job):
    if _is_egypt_job(job):
        loc = (job.location or "").lower()
        if "cairo" in loc:
            return " Cairo, Egypt"
        if "alex" in loc:
            return " Alexandria, Egypt"
        return " Egypt"
    if _is_gulf_job(job):
        loc = (job.location or "").lower()
        if "saudi" in loc or "ksa" in loc or "riyadh" in loc or "jeddah" in loc:
            return " Saudi Arabia"
        if "dubai" in loc or "uae" in loc or "abu dhabi" in loc:
            return " UAE"
        if "qatar" in loc or "doha" in loc:
            return " Qatar"
        if "kuwait" in loc:
            return " Kuwait"
        if "bahrain" in loc:
            return " Bahrain"
        if "oman" in loc or "muscat" in loc:
            return " Oman"
        return " Gulf"
    if _is_remote_job(job):
        return " Remote / Worldwide"
    return " " + _escape(job.location or "Unknown")

def _freshness_badge(job):
    if not job.posted_date:
        return ""
    diff = datetime.now() - job.posted_date
    if diff < timedelta(hours=6):
        return "[NEW]"
    if diff < timedelta(hours=24):
        return "[Today]"
    return ""

def _extract_skills(text):
    skill_map = {
        "siem": "SIEM", "splunk": "Splunk", "qradar": "QRadar",
        "sentinel": "Sentinel", "aws": "AWS", "azure": "Azure",
        "gcp": "GCP", "incident": "IR", "threat": "Threat Intel",
        "pentest": "Pentest", "burp": "Burp Suite", "nessus": "Nessus",
        "metasploit": "Metasploit", "iso 27001": "ISO 27001",
        "nist": "NIST", "grc": "GRC", "pci": "PCI-DSS",
        "crowdstrike": "CrowdStrike", "defender": "MS Defender",
        "wireshark": "Wireshark", "oscp": "OSCP", "cissp": "CISSP",
        "ceh": "CEH", "python": "Python", "soc": "SOC",
    }
    found = [label for kw, label in skill_map.items() if kw in text]
    return ", ".join(found[:5]) if found else "General Security"

def _match_bar(score: int) -> str:
    """Returns green dot bar + label for the match strength line."""
    if score >= 18:
        return "🟢🟢🟢🟢🟢 Excellent"
    if score >= 14:
        return "🟢🟢🟢🟢⚪ Strong"
    if score >= 11:
        return "🟢🟢🟢⚪⚪ Good"
    if score >= 7:
        return "🟢🟢⚪⚪⚪ Relevant"
    return "🟢⚪⚪⚪⚪ Listed"

def _domain_emoji(domain: str) -> str:
    mapping = {
        "SOC / Blue Team":               "",
        "Penetration Testing / Red Team": "",
        "Cloud Security":                "",
        "AppSec / DevSecOps":            "",
        "GRC / Compliance":              "",
        "DFIR / Forensics":              "",
        "Network Security":              "",
        "Security Management":           "",
        "Security Architecture":         "",
        "IAM / Identity Security":       "",
        "Training / Program":            "",
        "Cybersecurity":                 "",
        "Physical Security":             "",
    }
    return mapping.get(domain, "")

def _level_emoji(level: str) -> str:
    return {"Entry-Level": "", "Mid-Level": "", "Senior": "", "Open": ""}.get(level, "")


def _parse_hr_post_fields(job) -> dict:
    """
    Parse structured fields embedded in the description of an HR post.
    Description format (set by linkedin_hr_hunter.py):
      "Responsibilities: X; Y | Requirements: A; B"
    Also reads job_type for work_model and tags for poster name.
    """
    desc = job.description or ""
    highlights: list[str] = []
    requirements: list[str] = []
    apply_email = ""
    apply_whatsapp = ""
    apply_link = ""

    # Extract responsibilities
    resp_match = re.search(r"Responsibilities?:\s*([^|]+)", desc, re.IGNORECASE)
    if resp_match:
        highlights = [s.strip() for s in resp_match.group(1).split(";") if s.strip()]

    # Extract requirements
    req_match = re.search(r"Requirements?:\s*([^|]+)", desc, re.IGNORECASE)
    if req_match:
        requirements = [s.strip() for s in req_match.group(1).split(";") if s.strip()]

    email_match = re.search(r"EMAIL:([^\s]+@[^\s]+)", desc, re.IGNORECASE)
    if email_match:
        apply_email = email_match.group(1).strip()
    whatsapp_match = re.search(r"WHATSAPP:([+\d\s\-()]+)", desc, re.IGNORECASE)
    if whatsapp_match:
        apply_whatsapp = whatsapp_match.group(1).strip()
    link_match = re.search(r"APPLY_LINK:(https?://\S+)", desc, re.IGNORECASE)
    if link_match:
        apply_link = link_match.group(1).strip()

    # Poster name from tags (format: "poster:Name")
    poster = ""
    for tag in (job.tags or []):
        if isinstance(tag, str) and tag.startswith("poster:"):
            poster = tag[7:].strip()
            break

    # Fallback: try original_source
    if not poster:
        orig = getattr(job, "original_source", "") or ""
        if " � " in orig:
            poster = orig.split(" � ", 1)[1].strip()

    work_model = getattr(job, "job_type", "") or ""

    return {
        "highlights": highlights,
        "requirements": requirements,
        "poster": poster,
        "work_model": work_model,
        "apply_email": apply_email,
        "apply_whatsapp": apply_whatsapp,
        "apply_link": apply_link,
    }


def _work_model_badge(work_model: str) -> str:
    """Return emoji badge for work model."""
    wm = work_model.lower()
    if "remote" in wm:
        return " Remote"
    if "hybrid" in wm:
        return " Hybrid"
    if "on-site" in wm or "onsite" in wm:
        return " On-site"
    return ""


def format_hr_post_message(job) -> str:
    """
        HR  LinkedIn.
    v42 FIX:    HR Post       .
     : linkedin_hr_hunter  jobs   jobs API
       HR posts �     jobs   badge .
    """
    from scoring import score_job_int

    score    = score_job_int(job)
    text     = (job.title + " " + job.description + " " + _flatten_tags(job.tags)).lower()
    domain   = _domain_label(job)
    location = _detect_location_flag(job)
    d_emoji  = _domain_emoji(domain)
    level    = _level_label(job)
    l_emoji  = _level_emoji(level)
    skills   = _extract_skills(text)
    fresh    = _freshness_badge(job)
    post_fields = _parse_hr_post_fields(job)

    title   = _escape(job.title)
    company = _escape(job.company) if job.company and job.company != "Unknown" else ""

    #     original_source  tags
    poster = ""
    for tag in (job.tags or []):
        if isinstance(tag, str) and tag.startswith("poster:"):
            poster = tag[7:].strip()
            break
    if not poster:
        orig = getattr(job, "original_source", "") or ""
        if " � " in orig:
            poster = orig.split(" � ", 1)[1].strip()

    lines = []

    #  Header 
    badges = []
    if fresh == "[NEW]":
        badges.insert(0, " NEW")
    elif fresh == "[Today]":
        badges.insert(0, " Today")
    if badges:
        lines.append(f"<b>{'  �  '.join(badges)}</b>")
        lines.append("")

    #  Role Title 
    lines.append(f"{d_emoji}  <b>{title}</b>")
    lines.append("")

    #  Company & Poster 
    if company:
        lines.append(f"  <b>{company}</b>")
    if poster:
        lines.append(f"  <i>Posted by: {poster}</i>")
    lines.append(f"  {location}")
    lines.append("")

    #  Role Details 
    lines.append(f"<b> Role Details</b>")
    lines.append(f"{l_emoji}  {level}   {d_emoji}  {domain}")
    if job.job_type:
        lines.append(f"  {_escape(job.job_type)}")
    if job.salary:
        lines.append(f"  {_escape(str(job.salary))}")
    lines.append("")

    #  Key Skills 
    lines.append(f"<b> Key Skills</b>")
    lines.append(f"  {skills}")
    lines.append("")

    #  Match Strength 
    lines.append("<b> Match Strength</b>")
    lines.append(f"   {_match_bar(score)}  <b>({score})</b>")
    lines.append("")

    #  Apply CTA 
    apply_url = job.canonical_url or job.url
    if post_fields.get("apply_email"):
        lines.append(f"  <code>{_escape(post_fields['apply_email'])}</code>")
    if post_fields.get("apply_whatsapp"):
        lines.append(f"  <code>{_escape(post_fields['apply_whatsapp'])}</code>")
    if post_fields.get("apply_link"):
        lines.append(f'<a href="{_escape(post_fields["apply_link"])}">  Apply Link  </a>')
    lines.append(f'<a href="{_escape(apply_url)}">  View Post &amp; Apply Directly  </a>')
    lines.append(f"<code>{'' * 14}</code>")

    return "\n".join(lines).strip()


def format_job_message(job):
    #  HR Post fast-path — use dedicated template
    if (getattr(job, "content_type", "") or "").lower() == "hr_post":
        return format_hr_post_message(job)

    from scoring import score_job_int
    score = score_job_int(job)

    text = (job.title + " " + job.description + " " + _flatten_tags(job.tags)).lower()

    level    = _level_label(job)
    domain   = _domain_label(job)
    location = _detect_location_flag(job)
    skills   = _extract_skills(text)
    fresh    = _freshness_badge(job)

    title   = _escape(job.title)
    company = _escape(job.company) if job.company else "Unknown"

    # Source display name — map internal source keys to human-readable names
    display_src = getattr(job, "display_source", None) or job.source or ""
    _src_map = {
        "linkedin": "LinkedIn", "linkedin_unified": "LinkedIn",
        "linkedin_li_at": "LinkedIn", "linkedin_hiring": "LinkedIn #Hiring",
        "linkedin_posts": "LinkedIn", "linkedin_hr_post": "LinkedIn",
        "linkedin_hr_hunter": "LinkedIn",
        "linkedin unified engine": "LinkedIn",
        "wuzzuf": "Wuzzuf", "bayt": "Bayt.com",
        "indeed": "Indeed", "glassdoor": "Glassdoor",
        "naukrigulf": "NaukriGulf", "gulf_expanded": "NaukriGulf",
        "freelancer": "Freelancer.com", "mostaql": "Mostaql",
        "telegram": "Telegram", "github": "GitHub",
        "google_jobs": "Google Jobs", "jsearch": "Google Jobs",
        "remoteok": "RemoteOK", "remotive": "Remotive",
    }
    source = _src_map.get((display_src or "").lower(), _escape(display_src)) if display_src else ""

    is_hiring_post = ((getattr(job, "content_type", "") or "").lower() == "hr_post") or getattr(job, "source", "") == "linkedin_hiring"
    hiring_poster = ""
    if is_hiring_post:
        orig = getattr(job, "original_source", "") or ""
        if orig.startswith("#Hiring") and "→" in orig:
            raw = orig.split("→", 1)[1].strip()
            if raw and raw.lower() != job.title.lower():
                hiring_poster = raw
    hiring_context = _escape(hiring_poster) if hiring_poster else ""
    # Check title ONLY (not description/tags) to avoid false "Internship" badges.
    # Also use word-boundary matching so "internal" / "internalize" don't trigger.
    import re as _re
    _title_lower = job.title.lower()
    _INTERN_TITLE_PATTERNS = [
        r"\bintern\b", r"\binternship\b", r"\btrainee\b",
        r"\bfresh grad\b", r"\bgraduate program\b",
    ]
    is_internship = _is_true_internship_job(job) or any(_re.search(p, _title_lower) for p in _INTERN_TITLE_PATTERNS)

    d_emoji = _domain_emoji(domain)
    l_emoji = _level_emoji(level)

    SEP = "━━"   # ━━  section separator — matches reference format

    lines = []

    # ── Header badge row (only when something to show) ──────
    header_parts = []
    if fresh == "[NEW]":
        header_parts.append("🆕 NEW")
    elif fresh == "[Today]":
        header_parts.append("🔔 Today")
    if is_internship:
        header_parts.append("🎓 Internship")
    if is_hiring_post:
        header_parts.append("📢 #Hiring")
    if header_parts:
        lines.append(f"<b>{' · '.join(header_parts)}</b>")

    # ── Title ────────────────────────────────────────────────
    lines.append(f"{d_emoji} <b>{title}</b>")

    # ── Company & Location ───────────────────────────────────
    lines.append(f"🏢 {company}  📍 {location}")

    # ── Role Details ─────────────────────────────────────────
    lines.append(f"{SEP} Role Details")
    role_line = f"{l_emoji} {level}  {d_emoji} {domain}"
    lines.append(role_line)
    if job.job_type:
        lines.append(f"💼 {_escape(job.job_type)}")
    if job.salary:
        lines.append(f"💰 {_escape(str(job.salary))}")

    # ── Key Skills ───────────────────────────────────────────
    lines.append(f"{SEP} Key Skills")
    lines.append(f"⚡ {skills}")

    # ── Match Strength ───────────────────────────────────────
    lines.append(f"{SEP} Match Strength")
    lines.append(f"{_match_bar(score)} ({score})")

    # ── Source ───────────────────────────────────────────────
    if is_hiring_post:
        lines.append(f"🌐 Source: LinkedIn #Hiring")
        if hiring_context:
            lines.append(f"📝 Original: {hiring_context}")
    elif source:
        lines.append(f"🌐 Source: {source}")

    # ── Apply CTA + bottom separator ────────────────────────
    apply_url = job.canonical_url or job.url
    lines.append(f'<a href="{_escape(apply_url)}">🚀 Apply Now →</a>')
    lines.append(f"<code>──────────────</code>")

    return "\n".join(lines).strip()


# 
#  Sending � per channel, no cross-channel duplicates
# 

def _send_to_topic(message, thread_id=None, db: JobsDB | None = None, channel_key: str = ""):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_GROUP_ID:
        log.warning("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_GROUP_ID")
        return False

    payload = {
        "chat_id": TELEGRAM_GROUP_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if thread_id:
        payload["message_thread_id"] = thread_id

    ok, status, err, retry_after = _post_telegram_payload(payload)
    if ok:
        return True

    log.error("Telegram error " + str(status) + ": " + (err or "unknown error"))
    transient = status in {0, 429, 500, 502, 503, 504}
    if transient and db and channel_key:
        delay = _compute_retry_delay(0, retry_after=retry_after)
        db.enqueue_telegram_retry(
            channel_key=channel_key,
            thread_id=thread_id,
            payload=payload,
            error=f"status={status} {err}".strip(),
            max_attempts=TELEGRAM_RETRY_MAX_ATTEMPTS,
            delay_seconds=delay,
        )
        log.warning(f"Queued message retry for [{channel_key}] after Telegram failure (status={status})")
    return False
