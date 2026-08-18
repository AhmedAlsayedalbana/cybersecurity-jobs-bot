"""
Telegram message formatting and multi-topic sending.
KEY FEATURE: balanced per-channel sending with per-channel dedup.
Format: matches reference telegram_sender exactly.
"""

import re
import time
import logging
import requests
import config
from collections import Counter
from datetime import datetime, timedelta
from models import CyberVerdict, Job, _flatten_tags
from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_SEND_DELAY,
    CHANNELS, get_topic_thread_id,
    DAILY_SEND_HOURS, MAX_JOBS_PER_CHANNEL,
    TELEGRAM_RETRY_MAX_ATTEMPTS, TELEGRAM_RETRY_BASE_DELAY_SECONDS,
    TELEGRAM_RETRY_DRAIN_LIMIT,
)
from database import JobsDB, get_db
from intelligence.pool_builder import freshness_sort_key
from run_budget import cap_timeout, remaining as budget_remaining
from job_intelligence import (
    classify_domain as classify_intelligence_domain,
    classify_delivery_geo,
    classify_level as classify_intelligence_level,
    has_channel_evidence,
    is_remote_job as intelligence_is_remote_job,
    is_true_security_internship,
    resolve_delivery_location,
    validate_location_for_channel,
)

log = logging.getLogger(__name__)


# 
#  Geo Helpers
# 

def _is_egypt_job(job):
    return classify_delivery_geo(job) == "egypt"

def _is_arab_region_job(job):
    return classify_delivery_geo(job) == "arab"

def _is_remote_job(job):
    return intelligence_is_remote_job(job)


def _is_true_internship_job(job) -> bool:
    """Strict internship check to avoid leaking generic jobs into internships channel."""
    return is_true_security_internship(job)


def _delivery_identity(job) -> str:
    """Exact posting identity used for every delivery-dedup decision."""
    url_id = getattr(job, "url_id", "") or ""
    if url_id:
        return url_id
    canonical = getattr(job, "canonical_url", "") or getattr(job, "url", "") or ""
    return re.sub(r"[?#].*$", "", canonical.lower().rstrip("/"))


_TITLE_CYBER_EVIDENCE = (
    "vulnerability management", "identity and access management", "identity & access",
    "identity governance", "security operations", "penetration testing", "pentest",
    "red team", "application security", "appsec", "incident response",
    "threat intelligence", "threat hunting", "security engineering",
    "network security", "cloud security", "devsecops", "security architecture",
    "detection engineering", "security monitoring", "security analyst",
    "security engineer", "vulnerability research", "cybersecurity", "cyber security",
    "information security", "infosec", r"\biam\b", r"\biga\b", r"\bsoc\b",
)
_CYBER_SKILL_EVIDENCE = (
    "iam", "iga", "saviynt", "okta", "ping identity", "cyberark", "sailpoint",
    "siem", "splunk", "qradar", "sentinel", "edr", "xdr", "cspm", "cnapp",
    "cwpp", "burp", "nmap", "metasploit", "oscp", "sast", "dast", "owasp",
)


def _proven_employer_context(employer: str, source_key: str) -> bool:
    """v68: is this employer already proven to post publishable cyber roles
    for this bot?  Two paths, cheapest first:

    1. Word-bounded recognised security-discipline token in the employer
       name (``F5`` matches ``f5``; ``RSA`` matches ``rsa``; incidental
       substrings like ``RSA`` inside ``Marsala`` do not).
    2. Historical proof: the bot has already accepted jobs whose employer
       matches this one and whose source key is identical or the employer
       appears in the accepted posting's URL — that is evidence the
       employer's own career pages carry security workforce.

    Empty-company jobs and employers without any historical acceptance
    return False — a bare job noun from an unknown company stays below the
    LIKELY evidence gate, exactly as the v62 contract requires.
    """
    if not employer:
        return False
    recognised_security_employers = (
        "f5", "rsa", "wiz", "check point", "checkpoint", "fortinet",
        "palo alto", "crowdstrike", "cloudflare", "proofpoint", "tenable",
        "rapid7", "mandiant", "dragos", "claroty", "abnormal", "tessian",
        "veracode", "synack", "intigriti", "darktrace", "cybereason",
        # v69: Nozomi Networks — industrial/OT security vendor whose entire
        # engineering workforce builds ICS/OT security tooling.
        "nozomi", "malomatia",
    )
    employer_l = employer.lower()
    if any(re.search(r"(?<!\w)" + re.escape(t) + r"(?![\w.-])", employer_l)
           for t in recognised_security_employers):
        return True
    try:
        db = get_db()
        # Same source + same employer already produced accepted cyber roles;
        # the lookup is a cheap index equality scan and errors are never a
        # delivery blocker.
        with db._conn() as con:
            (count,) = con.execute(
                "SELECT COUNT(*) FROM jobs WHERE LOWER(company)=? "
                "AND LOWER(source_key)=? AND cyber_verdict=? "
                "AND is_published=1",
                (employer_l, source_key, CyberVerdict.CONFIRMED.value),
            ).fetchone()
        return bool(count and count > 0)
    except Exception as exc:  # pragma: no cover - DB failures never block delivery
        log.debug("proven_employer_context lookup failed: %s", exc)
        return False


def _enrich_cyber_evidence(job):
    """v67: build structured evidence from the job's own payload before the
    gate re-evaluates it.  Only legitimate, verifiable signals are added —
    security skills found in the description, a security-product vendor
    domain on the company name/URL, or a security context already attached
    by upstream enrichment.  The gate's thresholds are untouched: enrichment
    feeds the existing evidence codes, it never invents a new pass path,
    and NON_CYBER rows never benefit from it (the caller is the LIKELY
    evidence check)."""
    title = (getattr(job, "title", "") or "").lower()
    description = (getattr(job, "description", "") or "").lower()
    company = (getattr(job, "company", "") or "").lower()
    url = (getattr(job, "url", "") or "").lower()
    text = f"{title} {description} {company} {url}"

    if not text.strip():
        return

    # Security skills buried in the description still prove a cyber role —
    # but only when the title is already security-adjacent, otherwise a
    # generic IT role mentioning "siem" in boilerplate would walk in.
    # v69: "soar" (security orchestration, automation and response) is a
    # first-class cyber discipline in the title — "Senior SOAR Engineer" is
    # a security role even without another cyber keyword anywhere in the
    # posting.
    security_adjacent_title = any(
        anchor in title for anchor in (
            "security", "cyber", "infosec", "iam", "iga", "soc", "pentest",
            "appsec", "sec", "ciso", "grc", "fraud", "risk analyst",
            "threat", "incident", "compliance analyst", "soar",
        )
    )
    # Vendor/company context from well-known security product companies
    # (their job pages are by construction a security context).  v68: tokens
    # are matched word-bounded on the employer name only — a bare substring
    # match (e.g. "f5" inside "affable") would let incidental text bypass
    # the LIKELY evidence gate, which the v62 contract forbids.
    vendor_domains = (
        "crowdstrike", "paloaltonetworks", "palo alto", "fortinet",
        "checkpoint", "zscaler", "proofpoint", "mandiant", "trendmicro",
        "trend micro", "sophos", "kaspersky", "tenable", "qualys",
        "rapid7", "tanium", "dragos", "recordedfuture", "recorded future",
        "fireeye", "sentinelone", "cybereason", "darktrace",
        "cloudflare", "wiz.io", "wiz security", "bugcrowd", "hackerone",
        "intigriti", "synack", "veracode", "imperva", "f5.com", "f5 networks", "f5",
        "cyberark", "sailpoint", "saviynt", "okta", "pingidentity",
        "cybershield", "vulncheck", "abnormal", "tessian", "claroty",
        "rsa security", "rsa", "f5 networks f5",
        # v69: Nozomi Networks — industrial/OT security vendor (ICS
        # visibility and threat detection for critical infrastructure).
        "nozomi",
    )
    # Employer-context anchors: a bank/telecom/enterprise title that names an
    # infrastructure or platform discipline is publish-grade when a real
    # security skill appears in the description — v68 closes the gap where a
    # truncated listing ("Solutions Engineer @ F5", "AI Architect, AI4ALL @
    # Valeo") was rejected only because the snippet lacked an explicit
    # cyber keyword while the employer identity already supplies it.
    employer_context_tokens = (
        "cloud", "network", "infrastructure", "ai architect", "platform",
        "integration", "solution architect", "solutions engineer",
    )
    # Vendor context is only conclusive when the vendor's OWN identity is
    # present — its domain in the posting URL, or its full token in the
    # employer name (word-bounded). A bare substring in any text would let
    # incidental mentions (e.g. an "RSA Security" hiring-company string)
    # bypass the LIKELY evidence gate, which the v62 contract forbids.
    url_domain = ""
    try:
        url_domain = (url.split("://", 1)[-1].split("/", 1)[0] or "").lower()
    except Exception:
        url_domain = ""
    # Word-bounded on the employer name only; the URL matches contain the
    # vendor token inside its own domain (e.g. "f5.com" in
    # "careers.f5.com").  Short tokens like "f5"/"rsa" are only conclusive
    # when they are a standalone employer word, never a substring.
    has_vendor_context = bool(url_domain) and any(
        v in url_domain for v in vendor_domains if v and "." in v
    ) or any(
        re.search(r"(?<!\w)" + re.escape(v) + r"(?![\w.-])", company)
        for v in vendor_domains if v and company
    )
    # v68 employer-context evidence: a security-adjacent discipline title
    # from an employer whose other postings already proved cyber yield, or
    # from a recognised security-discipline employer, plus a real skill in
    # the description, is a verified security context — not a keyword
    # guess.  This is what lets truncated bank/company listings pass when
    # the listing text itself lacks explicit cyber keywords.
    security_adjacent_title = security_adjacent_title or any(
        anchor in title for anchor in employer_context_tokens
    )

    # Security skills buried in the description still prove a cyber role —
    # but only when the title is already security-adjacent, otherwise a
    # generic IT role mentioning "siem" in boilerplate would walk in.
    description_skills = [
        signal for signal in ("siem", "edr", "xdr", "mdr", "splunk",
                              "qradar", "sentinel", "ids", "ips",
                              "firewall", "waf", "vpn", "soc analyst",
                              "penetration", "red team", "vulnerability",
                              "incident response", "threat intelligence",
                              "threat hunting", "forensics", "malware",
                              "cryptography", "pki", "zero trust", "iam",
                              "iga", "saviynt", "sailpoint", "cyberark",
                              "okta", "burp", "metasploit", "nmap",
                              "oscp", "ceh", "sast", "dast", "owasp",
                              "cspm", "cnapp", "cwpp", "iso 27001",
                              "nist", "pci dss", "grc", "audit analyst",
                              "security architecture", "cloud security",
                              "devsecops", "fraud analyst", "cyber fraud",
                              "appsec", "cloud architecture",
                              "cloud infrastructure",
                              # v69: SOAR-discipline signals — "orchestration"
                              # (playbook engineering) and "soc automation"
                              # are first-class cyber security work; paired
                              # with a security-adjacent title they prove a
                              # cyber role ("Senior SOAR Engineer").
                              "orchestration", "soc automation")
        if signal in description and not (signal in title and title == signal)
    ]

    # v68: employer-context verification — the employer is either a
    # recognised security-discipline company (word-bounded token in the
    # employer name or its own domain on the URL) or an employer whose
    # other postings already proved cyber yield for this bot (querying the
    # jobs table, cheapest proof available).  Combined with an
    # infrastructure/platform-adjacent title and a real security skill in
    # the description, this is publish-grade evidence that the truncated
    # listing itself lacks.
    employer_security_context = has_vendor_context
    employer_context_title = any(anchor in title for anchor in employer_context_tokens)
    if not employer_security_context and employer_context_title and description_skills:
        employer_key = (company or "").strip()
        source_key = (getattr(job, "source_key", "") or "").lower()
        proven_employers = _proven_employer_context(employer_key, source_key)
        if proven_employers:
            employer_security_context = True

    existing_evidence = getattr(job, "_cyber_evidence", None)
    enriched: dict[str, object] = {
        "security_adjacent_title": security_adjacent_title,
        "vendor_security_context": has_vendor_context,
        "employer_security_context": employer_security_context,
        "description_security_skills": description_skills,
        "had_existing_evidence": bool(existing_evidence),
    }
    setattr(job, "_cyber_enrichment", enriched)
    if not existing_evidence:
        # Preserve any upstream evidence; enrichment is additive only.
        setattr(job, "_cyber_evidence", enriched)


def _publishable_cyber_evidence(job) -> tuple[str, tuple[str, ...]]:
    """Return an auditable evidence code without widening the Cyber verdict gate.

    Generic job nouns (Engineer/Analyst/Consultant/Support/Solutions) never
    count on their own.  A title carrying an explicit security domain does.
    """
    title = (getattr(job, "title", "") or "").lower()
    tags = _flatten_tags(getattr(job, "tags", [])).lower()
    description = (getattr(job, "description", "") or "").lower()
    domain = classify_intelligence_domain(job)

    for anchor in _TITLE_CYBER_EVIDENCE:
        if anchor.startswith("\\b"):
            if re.search(anchor, title):
                return "title_cyber_evidence", ()
        elif anchor in title:
            return "title_cyber_evidence", ()
    if domain and has_channel_evidence(job, domain):
        return "title_cyber_evidence", ()
    if any(anchor in tags for anchor in _CYBER_SKILL_EVIDENCE):
        return "skill_cyber_evidence", ()
    # v67: enrichment evidence — the job's own payload supplies security
    # context without touching the gate's threshold.  A security-product
    # vendor (CrowdStrike, Wiz, Bugcrowd ...) by construction runs a
    # security workforce, and a security-adjacent title with real security
    # skills in the description is a publish-grade role.  Generic IT nouns
    # without either signal still fail the gate exactly as before.
    enrichment = getattr(job, "_cyber_enrichment", None) or {}
    # v68: vendor identity alone never carries a role — a "Sales Operations
    # Analyst" at a security vendor is still a non-cyber role, so the vendor
    # context pass requires a technical title with a substantial description.
    # v67's CrowdStrike-style rule (a genuine security vendor's workforce
    # role clears the gate) is preserved for engineering/architecture titles
    # whose description reads like real engineering work; the v62 contract
    # (a bare job noun from any company stays below the gate) still holds
    # for business/support nouns.
    vendor_technical_title = bool(
        enrichment.get("vendor_security_context")
        and any(t in title for t in (
            "engineer", "architect", "developer", "technical", "researcher",
            "analyst", "programmer", "scientist", "specialist", "operator",
        ))
        and len((getattr(job, "description", "") or "").strip()) >= 30
    )
    if enrichment.get("vendor_security_context") and (
        (enrichment.get("security_adjacent_title") and enrichment.get("description_security_skills"))
        or vendor_technical_title
    ):
        return "enriched_vendor_security_context", ()
    # v68: employer-context evidence — a security-adjacent discipline title
    # (cloud/network/infrastructure/platform/solutions engineer, AI
    # architect) from an employer whose other postings already proved cyber
    # yield, or from a recognised security-discipline employer, together
    # with a real security skill in the description, is publish-grade.
    # The title noun alone still fails the gate exactly as the v62
    # contract requires.
    if enrichment.get("employer_security_context") and enrichment.get("security_adjacent_title") and enrichment.get("description_security_skills"):
        return "enriched_employer_context", ()
    if enrichment.get("security_adjacent_title") and enrichment.get("description_security_skills"):
        return "enriched_title_and_description_skills", ()
    # Description evidence needs a separately security-specific title/context;
    # this preserves the block on generic Solutions/Support roles that merely
    # discuss a cloud-security product.
    if any(anchor in description for anchor in _CYBER_SKILL_EVIDENCE) and any(
        anchor in title for anchor in ("security", "cyber", "iam", "iga", "soc", "pentest", "appsec")
    ):
        return "description_cyber_evidence", ()
    source_key = (getattr(job, "source_key", "") or getattr(job, "source", "") or "").lower()
    content_type = (getattr(job, "content_type", "") or "").lower()
    if content_type == "security_job_listing" or source_key.startswith("cybersecurity_"):
        return "source_cyber_evidence", ()
    return "insufficient_cyber_evidence", ("explicit_title_or_domain", "cyber_skill", "verified_security_context")


def _has_publishable_cyber_evidence(job) -> bool:
    return _publishable_cyber_evidence(job)[0] != "insufficient_cyber_evidence"


def _telegram_ineligibility_reason(job) -> str | None:
    """Explain the hard delivery gate without exposing a bypass path.

    The verdict and the evidence gate are now one consistent contract:

    * ``CYBER_CONFIRMED`` was already approved by the classifier with full
      anchor evidence. Re-applying the delivery evidence gate to such a job
      produced contradictory outcomes (confirmed upstream, rejected at
      delivery for the same role), which hid real vacancies from the
      channel. With a valid delivery location and an exact posting
      identity, ``CYBER_CONFIRMED`` is final — delivery trusts it.
    * ``CYBER_LIKELY`` remains below the confirmation threshold, so it is
      still required to demonstrate publish-grade domain evidence at
      delivery through the existing ``_publishable_cyber_evidence`` gate.
    """
    verdict = getattr(job, "cyber_verdict", "")
    if verdict not in {CyberVerdict.CONFIRMED.value, CyberVerdict.LIKELY.value}:
        return "non_cyber_or_unclassified"
    location = resolve_delivery_location(job)
    if not location.eligible:
        return location.reason_code
    if not _delivery_identity(job):
        return "missing_exact_posting_identity"
    # v62 verdict consistency: a confirmed classification is never rejected
    # again by a conflicting delivery-level evidence gate. Likelies keep the
    # full evidence requirement.
    if verdict == CyberVerdict.CONFIRMED.value:
        return None
    # v67: enrich the job's own payload (title/description/company/URL
    # vendor context) before the evidence gate re-evaluates it.  Thresholds
    # are unchanged — enrichment only supplies legitimate signals the gate
    # already knew how to accept.
    _enrich_cyber_evidence(job)
    evidence, _ = _publishable_cyber_evidence(job)
    if evidence == "insufficient_cyber_evidence":
        return evidence
    return None


def _is_telegram_eligible(job) -> bool:
    """Enforce the cyber-verdict gate before any Telegram routing.

    ``NON_CYBER`` and unclassified rows are never delivery candidates. Every
    accepted verdict must also demonstrate publish-grade cyber-role evidence,
    so a generic support, solutions, commercial, or ERP-admin role cannot
    enter a geographic channel merely through classifier affinity.
    """
    return _telegram_ineligibility_reason(job) is None


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
    Route a job to channels — v50 model:

    GEO channels  (egypt / arab / remote): based on location only.
    TOPIC channels (soc / grc / pentest / ...): based on keywords only.

    A job CAN and SHOULD appear in BOTH a geo channel AND ONE topic channel.
    Example: "GRC Analyst in Cairo" → egypt + grc

    INTERNSHIP ROUTING: True internship jobs go to BOTH their geo channel AND
    the internships topic channel (instead of a specialty domain channel).
    Within topic channels, a job goes to exactly ONE channel.
    """
    # Geo routing: one geo lane only. ``classify_delivery_geo`` gives explicit
    # remote work precedence over an employer's Egypt/Arab office address.
    geo_result = []
    geo = classify_delivery_geo(job)
    if geo == "egypt":
        geo_result = ["egypt"]
    elif geo == "arab":
        geo_result = ["gulf"]
    elif geo == "remote":
        geo_result = ["remote"]

    # Topic routing: exactly one specialty topic.
    topic_result = []
    topic_channel = _topic_channel_for_job(job, "")
    if topic_channel and topic_channel in CHANNELS:
        topic_result = [topic_channel]

    # Final router safety check.  The sender repeats it immediately before
    # enqueue and send so future fallback code cannot bypass this decision.
    return [
        channel for channel in (geo_result + topic_result)
        if validate_location_for_channel(job, channel)[0]
    ]


def _topic_channel_for_job(job, searchable: str) -> str | None:
    """Choose one specialty channel only when the role proves cyber relevance."""
    domain = classify_intelligence_domain(job)
    if domain and has_channel_evidence(job, domain):
        return domain
    if domain:
        log.debug(
            "Topic route withheld (description-only or generic evidence): domain=%s title=%s",
            domain,
            getattr(job, "title", ""),
        )
    return None


def _telegram_budget_remaining() -> float:
    """Return telegram send budget with global spillover.

    When the dedicated telegram sub-budget is exhausted but global run
    budget remains, allow sending to continue using the global budget.
    This ensures all routed jobs are sent even if the sub-budget is too low.
    """
    tg_left = budget_remaining("telegram")
    if tg_left > 0:
        return tg_left
    # Telegram sub-budget exhausted — check global remaining
    global_left = budget_remaining()  # total run remaining
    if global_left > 5:  # 5s safety margin
        return global_left
    return 0.0


def _post_telegram_payload(payload: dict) -> tuple[bool, int, str, int | None]:
    """
    Returns: (success, status_code, error_text, retry_after_seconds)
    """
    if _telegram_budget_remaining() <= 0:
        return False, 0, "telegram_budget_exhausted", None
    try:
        resp = requests.post(
            "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendMessage",
            json=payload,
            timeout=cap_timeout(10, phase="telegram"),
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


# v71: per-channel failure registry — a Telegram channel can fail for two
# very different reasons.  A ``429`` rate-limit is TEMPORARY and recovers
# on its own; a ``403 chat not found`` / ``400 deactivated chat`` is
# TERMINAL (the bot was removed or the chat no longer exists) and any
# retry is pure wasted budget.  Mixing the two made a single bad channel
# eat the whole pending queue every run, so they are now classified
# explicitly and handled separately.
_TERMINAL_TELEGRAM_STATUSES: tuple[int, ...] = (400, 401, 403, 404)
_channel_failure_state: dict[str, dict] = {}
_CHANNEL_DEACTIVATED_LOGGED: set[str] = set()

def _classify_channel_failure(status: int) -> str:
    """v71: classify a Telegram send failure for the channel registry."""
    if status == 429:
        return "retry_429"
    if status in _TERMINAL_TELEGRAM_STATUSES:
        return "terminal"
    return "transient"

def _is_channel_deactivated(ch_key: str) -> bool:
    """v71: whether a channel is currently deactivated by terminal errors."""
    state = _channel_failure_state.get(ch_key)
    if not state:
        return False
    return (state.get("deactivated_until", 0) or 0.0) > time.time()

def _deactivate_channel(ch_key: str, status: int, err: str) -> None:
    """v71: mark a channel deactivated after terminal Telegram errors and
    park it for one day; the row-level pending mechanism keeps draining
    every OTHER channel, so one dead chat can never strand the pipeline."""
    import datetime as _dt
    # 429 is a rate-limit signal handled by the row-level retry_429 path
    # with backoff — it must NEVER park the channel.  Only terminal 400/401/
    # 403/404 and genuinely hard failures reach the deactivation registry.
    if _classify_channel_failure(status) != "terminal":
        return  # 429/backoff and transient errors never park a channel
    state = _channel_failure_state.setdefault(ch_key, {
        "hard_errors": 0, "deactivated_until": 0.0, "terminal_reason": "",
    })
    state["hard_errors"] += 1
    state["terminal_reason"] = f"status={status} {err}".strip()[:200]
    state["deactivated_until"] = time.time() + 86400.0
    if ch_key not in _CHANNEL_DEACTIVATED_LOGGED:
        _CHANNEL_DEACTIVATED_LOGGED.add(ch_key)
        log.warning(
            "v71 Telegram channel [%s] deactivated for 24h: terminal error "
            "(HTTP %s). Retries suppressed to protect the delivery budget; "
            "other channels keep draining normally.", ch_key, status,
        )

_topic_evidence_cache: dict = {}

# v73: pairs the pending-first drain actually sent during THIS run.
# {(channel_key, delivery_key)} — the new-reservation loop consults it so a
# pair that was just delivered by the drain is never re-posted (which would
# then be recorded as "blocked by terminal channel state" and silently
# re-pended, stranding proven deliveries forever).
_drain_sent_pairs: set[tuple[str, str]] = set()

def _reset_channel_states_for_tests() -> None:
    """v71: test-only hook to clear the module-level channel registry."""
    _channel_failure_state.clear()
    _CHANNEL_DEACTIVATED_LOGGED.clear()

def _drain_retry_queue(db: JobsDB) -> int:
    """v67: drain ALL queued pending sends (v66 ``delivery_pending`` rows
    queued when a terminal channel state blocked a new eligible candidate,
    plus ``retry_429`` rate-limited rows) BEFORE new reservations are
    processed — pending senders are the most stale and the most deserving.
    Returns the number of pairs that actually succeeded."""
    sent = 0
    for row in db.get_pending_delivery_rows(limit=TELEGRAM_RETRY_DRAIN_LIMIT):
        if _telegram_budget_remaining() <= 0:
            break
        ch_key = row.get("channel_key") or ""
        # v71: a channel deactivated by terminal Telegram errors never
        # re-enters the drain loop — its pending rows wait out the park
        # window instead of burning the run's send budget.
        if ch_key and _is_channel_deactivated(ch_key):
            continue
        payload = row.get("payload") or {}
        ok, status, err, retry_after = _post_telegram_payload(payload)
        if ok:
            db.mark_telegram_delivery(row["delivery_key"], status="sent")
            sent += 1
            # v73: ledger entry so the new-reservation loop does not treat
            # this pair as "blocked by terminal channel state" and re-pend
            # a delivery whose success has just been proven.  The new loop
            # passes ``delivery_key=job_dedup_key`` (the plain key) and
            # ``channel_key=ch_key`` separately — the ledger therefore
            # stores the plain key.  Pending rows carry the prefixed form
            # (``channel:job``) because ``_send_to_topic`` stamps the full
            # ``delivery_id`` when queuing, so strip the channel prefix
            # here to match what the new loop compares against.
            dk = row.get("delivery_key", "") or ""
            if ch_key and dk.startswith(ch_key + ":"):
                dk = dk[len(ch_key) + 1:]
            _drain_sent_pairs.add((ch_key, dk))
            time.sleep(0.7)
            continue
        failure_kind = _classify_channel_failure(status)
        if failure_kind == "terminal":
            if ch_key:
                _deactivate_channel(ch_key, status, err)
            # A terminal error can never recover by retrying the same
            # chat — confirm the failure once on the outbox row so the
            # lifecycle stays auditable and stop burning budget on it.
            db.mark_telegram_delivery(
                row["delivery_key"], status="send_failed",
                error=f"TERMINAL:{status} {err}".strip()[:500],
            )
            continue
        if status == 429:
            db.mark_telegram_delivery(
                row["delivery_key"], status="retry_429",
                error=f"status={status} {err}".strip(),
                delay_seconds=_compute_retry_delay(row.get("attempts", 0), retry_after=retry_after),
            )
        else:
            db.mark_telegram_delivery(
                row["delivery_key"], status="send_failed",
                error=f"status={status} {err}".strip(),
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
    # A channel is filled only by its proven specialty. Generic SecEng cannot
    # stand in for CloudSec/AppSec/etc.; it has its own channel. Geo + topic
    # cross-posting remains intentional and is unaffected.
    "soc":       ["soc"],
    "pentest":   ["pentest"],
    "appsec":    ["appsec"],
    "cloudsec":  ["cloudsec"],
    "networksec":["networksec"],
    "grc":       ["grc"],
    "seceng":    ["seceng"],
    # internships: NEVER use fallback — only true internship jobs
}


def send_jobs(jobs, *, dry_run: bool = False):
    """
    Send jobs to Telegram channels — v50 rules:

    KEY GUARANTEES:
    - NON_CYBER and unclassified jobs never enter a Telegram queue.
    - CYBER_LIKELY jobs require publish-grade domain evidence before routing.
    - CYBER_CONFIRMED jobs with a valid location and posting identity pass
      delivery without a second evidence evaluation (v62 consistency).
    - A job appears in at most 1 GEO channel + at most 1 TOPIC channel (NEVER repeated).
    - Jobs older than config.MAX_JOB_AGE_DAYS (default 3 days / 72h) are
      HARD-BLOCKED from sending, regardless of source.
    - A job is never re-sent to the SAME channel within config.DAILY_SEND_HOURS
      (default 168h / 7 days) — see database.was_sent_to_channel_recently().
    - Source priority order within each channel: LinkedIn → Egyptian boards → Freelance → others.
    - Fallback jobs (affinity-based) are tracked globally: once a job is used as fallback
      in ONE topic channel, it CANNOT be reused in any other topic channel.
    - Internships channel ONLY receives true internship/junior security jobs.
    - MAX_JOBS_PER_CHANNEL = 10 per run.
    """
    from scoring import score_job_int
    from datetime import datetime, timedelta
    import config as _cfg

    # ── Hard stale gate — kept in sync with config.MAX_JOB_AGE_DAYS ─────────
    SEND_STALE_HOURS = int(getattr(_cfg, "MAX_JOB_AGE_HOURS", 72))  # jobs older than this are never sent
    now = datetime.now()

    def _is_too_old_to_send(job) -> bool:
        """Block jobs older than 48 hours from being sent to any channel."""
        posted = getattr(job, "posted_date", None)
        if posted:
            if getattr(posted, "tzinfo", None) is not None:
                from datetime import timezone
                posted = posted.astimezone(timezone.utc).replace(tzinfo=None)
            return (now - posted) > timedelta(hours=SEND_STALE_HOURS)
        # No date → treat as fresh (pass through)
        return False

    # ── Source priority key (lower = higher priority in channel queue) ──────
    # LinkedIn: 10, Wuzzuf/Egyptian: 15-22, Freelance: 20-22, Others: 30+
    def _source_priority_key(job) -> int:
        return int(getattr(job, "origin_priority", 999) or 999)

    total_sent = 0
    channel_summary = {}
    # Counters are explicit about the delivery unit: routed/reserved/sent/
    # failed are exact ``(job_id, channel)`` pairs.  This makes a clean
    # four-route run auditable as four reservations and four sends.
    delivery_lifecycle: Counter[str] = Counter(
        # v71: every lifecycle event has its own named counter so the
        # end-of-delivery funnel is exact, not inferred from differences.
        {k: 0 for k in (
            "eligible", "routed", "reserved", "sent", "would_send",
            "already_sent", "channel_mismatch", "channel_deactivated",
            "delivery_pending", "failed", "new_sent", "pending_sent",
            "pending_retried", "pending_before",
        )}
    )

    GEO_CHANNELS   = ["remote", "egypt", "gulf"]
    TOPIC_CHANNELS = [k for k in CHANNELS.keys() if k not in GEO_CHANNELS]
    send_order     = GEO_CHANNELS + TOPIC_CHANNELS

    active = list(send_order) if dry_run else [k for k in send_order if get_topic_thread_id(k)]
    missing = [] if dry_run else [k for k in send_order if not get_topic_thread_id(k)]
    log.info(f" Active channels ({len(active)}): {', '.join(active)}")
    if missing:
        log.warning(f"  Missing thread IDs for: {', '.join(missing)} — skipping those")

    # ── Sort: quality verdict → freshness → requested source order → score ──
    # A just-posted role must never sit behind an older one merely because its
    # source has a higher historic priority.  Unknown dates remain last.
    def _verdict_rank(job) -> int:
        return 1 if getattr(job, "cyber_verdict", "") == "CYBER_LIKELY" else 0

    def _freshness_key(job):
        bucket, age = freshness_sort_key(job, now=now)
        # Freshness is still exact inside the published buckets: a 15-minute
        # board job must not sit behind a 20-hour LinkedIn job. LinkedIn breaks
        # otherwise comparable freshness ties without letting old roles win.
        return (bucket, age, _source_priority_key(job))

    # v71: small delivery-order tilt for SOC / pen-testing roles located in
    # Egypt.  This ONLY changes the position of already-eligible jobs inside
    # their channel queues — no gate is relaxed, and the tilt is a bounded
    # rank bonus (2 places in the sort tuple) so confirmed and fresh jobs
    # always remain ahead of it.
    # v71: domain cache to avoid repeated classification per job during the
    # sort — a job must never be re-classified between the sort and the
    # per-channel routing, so the same cached value is used everywhere.
    _domain_cache: dict[int, str | None] = {}
    def _job_domain(j) -> str | None:
        jid = id(j)
        if jid not in _domain_cache:
            _domain_cache[jid] = classify_intelligence_domain(j)
        return _domain_cache[jid]
    def _soc_pentest_egypt_tilt(job) -> int:
        if _job_domain(job) not in ("soc", "pentest"):
            return 0
        location = resolve_delivery_location(job)
        if location.location_type == "remote":
            return 0
        country = (location.normalized_country or "").lower()
        return 2 if country == "egypt" else 0

    eligibility_reasons: Counter[str] = Counter()
    location_telemetry: Counter[str] = Counter()
    withheld_examples: list[tuple[str, str, str, str]] = []
    eligible_jobs = []
    for job in jobs:
        reason = _telegram_ineligibility_reason(job)
        location = resolve_delivery_location(job)
        location_telemetry[location.reason_code] += 1
        if reason:
            eligibility_reasons[reason] += 1
            title = (getattr(job, "title", "") or "Unknown title").replace("\n", " ")[:70]
            company = (getattr(job, "company", "") or "Unknown company").replace("\n", " ")[:45]
            evidence, missing_evidence = _publishable_cyber_evidence(job)
            detail = (
                f"location={getattr(job, 'location', '')!s:.45} type={location.location_type} "
                f"country={location.normalized_country or '-'} verdict={getattr(job, 'cyber_verdict', '') or '-'} "
                f"source={getattr(job, 'source_key', '') or getattr(job, 'source', '') or '-'} "
                f"score={score_job_int(job)} evidence={evidence}"
            )
            if missing_evidence:
                detail += f" missing={','.join(missing_evidence)}"
            withheld_examples.append((title, company, reason, detail))
        else:
            eligible_jobs.append(job)
    withheld = len(jobs) - len(eligible_jobs)
    if withheld:
        breakdown = ", ".join(
            f"{reason}={count}" for reason, count in sorted(eligibility_reasons.items())
        )
        log.info(
            " Delivery cyber gate: eligible=%d withheld=%d [%s].",
            len(eligible_jobs), withheld, breakdown,
        )
        example_limit = max(1, int(getattr(config, "DELIVERY_WITHHELD_LOG_LIMIT", 8)))
        examples = " | ".join(
            f"{title} @ {company} — {reason} [{detail}]"
            for title, company, reason, detail in withheld_examples[:example_limit]
        )
        suffix = " (truncated)" if len(withheld_examples) > example_limit else ""
        log.info(" Delivery withheld details: %s%s", examples, suffix)
    log.info(
        " Location delivery telemetry: accepted=%d rejected=%d unknown=%d "
        "physical_outside_region=%d hybrid_outside_region=%d remote_worldwide=%d",
        len(eligible_jobs),
        len(jobs) - len(eligible_jobs),
        location_telemetry["unknown_location"],
        location_telemetry["physical_outside_region"],
        location_telemetry["hybrid_outside_region"],
        location_telemetry["remote_worldwide"],
    )

    jobs_scored = sorted(
        eligible_jobs,
        key=lambda j: (
            _verdict_rank(j), _freshness_key(j), _source_priority_key(j),
            # v71: SOC/pen-test Egypt roles get a bounded ordering bonus so
            # they surface earlier in every matched channel; it never moves
            # a job across a verdict/freshness boundary.
            -(_soc_pentest_egypt_tilt(j) + score_job_int(j)),
        ),
    )
    tilted = sum(1 for j in jobs_scored if _soc_pentest_egypt_tilt(j) > 0)
    if tilted:
        log.info(
            " 🎯 v71 SOC/PenTest Egypt tilt: %d role(s) re-ordered to surface "
            "earlier in delivery — gates unchanged.", tilted,
        )
    _topic_evidence_cache.clear()

    # ── Pre-compute domain classifications for all scored jobs ──────────────
    # (the shared cache was defined before the tilt so sort and routing use
    # the exact same per-job domain — v71, no re-classification drift.)
    for j in jobs_scored:
        _job_domain(j)

    # ── Build per-channel queues (primary routing — exact domain match) ─────
    channel_queues: dict[str, list] = {key: [] for key in CHANNELS.keys()}
    channel_match_reasons: Counter[str] = Counter()
    delivery_location_blocks: list[str] = []
    for job in jobs_scored:
        for ch_key in route_job(job):
            allowed, location = validate_location_for_channel(job, ch_key)
            if not allowed:
                delivery_location_blocks.append(
                    f"{getattr(job, 'title', '')[:55]} channel={ch_key} "
                    f"type={location.location_type} country={location.normalized_country or '-'} "
                    f"reason={location.reason_code}"
                )
                continue
            if ch_key in channel_queues:
                channel_queues[ch_key].append(job)
                channel_match_reasons[
                    "remote_match" if ch_key == "remote"
                    else "location_match" if ch_key in GEO_CHANNELS
                    else "specialization_match"
                ] += 1
    routed_identities = {
        _delivery_identity(job)
        for queue in channel_queues.values()
        for job in queue
        if _delivery_identity(job)
    }
    queue_summary = ", ".join(
        f"{key}={len(channel_queues[key])}" for key in send_order
    )
    log.info(
        " Channel matching: eligible=%d routed=%d unrouted=%d queues=[%s] reasons=[%s] location_blocked_at_delivery=%d",
        len(eligible_jobs), len(routed_identities),
        len(eligible_jobs) - len(routed_identities), queue_summary,
        ", ".join(f"{key}={value}" for key, value in sorted(channel_match_reasons.items())),
        len(delivery_location_blocks),
    )
    delivery_lifecycle["eligible"] = len(eligible_jobs)
    delivery_lifecycle["channel_mismatch"] = max(0, len(eligible_jobs) - len(routed_identities))
    if delivery_location_blocks:
        log.warning(" location_blocked_at_delivery: %s", " | ".join(delivery_location_blocks[:8]))

    # ── Smart Fallback: STRICT one-job-one-channel enforcement ─────────────
    # Track which jobs are already claimed by a direct-match queue.
    # A fallback job may only be used in ONE topic channel.
    direct_claimed: set[str] = set()
    for ch_key in TOPIC_CHANNELS:
        for job in channel_queues.get(ch_key, []):
            key = _delivery_identity(job)
            if key:
                direct_claimed.add(key)

    # fallback_globally_claimed tracks jobs used as fallback across all topic channels
    fallback_globally_claimed: set[str] = set()

    for ch_key in TOPIC_CHANNELS:
        if not dry_run and not get_topic_thread_id(ch_key):
            continue
        if channel_queues[ch_key]:
            continue  # has direct-match jobs — no fallback needed

        if ch_key == "internships":
            log.info(f" [{ch_key}] No true internship/entry-level jobs — channel skipped (correct)")
            continue

        affinity_domains = _CHANNEL_DOMAIN_AFFINITY.get(ch_key, [])
        if not affinity_domains:
            continue

        # Candidates: must be in affinity domain, NOT already claimed by another channel
        candidates = []
        for j in jobs_scored:
            jkey = _delivery_identity(j)
            if jkey in direct_claimed or jkey in fallback_globally_claimed:
                continue  # already used elsewhere — skip
            domain = _job_domain(j)
            if domain in affinity_domains and has_channel_evidence(j, ch_key):
                candidates.append(j)

        fallback = sorted(
            candidates,
            key=lambda j: (
                affinity_domains.index(_job_domain(j))
                if _job_domain(j) in affinity_domains else 99,
                _freshness_key(j),
                _source_priority_key(j),   # LinkedIn first within fallback
                -score_job_int(j),
            ),
        )[:20]

        if fallback:
            channel_queues[ch_key] = fallback
            # Claim these jobs so no other topic channel uses the same ones
            for j in fallback:
                jkey = _delivery_identity(j)
                if jkey:
                    fallback_globally_claimed.add(jkey)
            domains_found = list(dict.fromkeys(_job_domain(j) for j in fallback[:5]))
            log.info(
                f" [{ch_key}] No direct-match jobs — using {len(fallback)} "
                f"domain-affinity fallback jobs (domains: {', '.join(d for d in domains_found if d)})"
            )
        else:
            log.info(f" [{ch_key}] No direct-match or affinity jobs — channel skipped")

    # Include the fallback queues as well: this is the exact number of
    # independently deliverable ``(job_id, channel)`` pairs, before ordinary
    # capacity/dedup checks.  It intentionally matches sent on an error-free,
    # uncapped run rather than hiding cross-posting behind identity counts.
    delivery_lifecycle["routed"] = sum(len(queue) for queue in channel_queues.values())

    # ── Global topic dedup: prevents same job in >1 topic channel ──────────
    # Once a job (dedup_key) is sent to any topic channel, it's locked for all others.
    topic_globally_sent: set[str] = set()

    limit = MAX_JOBS_PER_CHANNEL
    sent_records = []
    db = get_db()
    # v67: pending-FIRST delivery — queued senders from earlier runs
    # (delivery_pending/retry_429) go out before any new reservation this
    # run builds, so a candidate the channel state previously blocked is
    # visibly retried instead of sitting behind fresh jobs.
    # v73: the drain ledger is per-run — every send_jobs invocation starts
    # from a clean ledger; only this run's drain sends count as
    # already-handled pairs in the new-reservation loop below.
    _drain_sent_pairs.clear()
    # v71: pending counting is split into the channel-delivery dimension
    # (raw rows) and the candidate dimension (distinct jobs).  A single job
    # can legitimately be pending on several channels, and lumping the two
    # numbers together made a healthy queue look like a growing backlog.
    pending_before = 0 if dry_run else len(db.get_pending_delivery_rows(limit=TELEGRAM_RETRY_DRAIN_LIMIT))
    delivery_lifecycle["pending_before"] = pending_before
    pending_unique_before = 0 if dry_run else db.count_pending_unique_jobs()
    delivery_lifecycle["pending_unique_before"] = pending_unique_before
    retried_sent = 0 if dry_run else _drain_retry_queue(db)
    delivery_lifecycle["drain_sent"] = retried_sent
    pending_retried = min(pending_before, retried_sent) if pending_before else 0
    delivery_lifecycle["pending_retried"] = pending_retried
    if pending_before:
        log.info(
            f" Pending-first delivery: {pending_before} queued send(s) across "
            f"{pending_unique_before} unique job(s) from earlier run(s) — "
            f"{retried_sent} resent now (pending rows are drained BEFORE "
            f"new reservations this run)"
        )
    channel_cursors = {k: 0 for k in send_order}
    channel_dedup_sent = {k: set() for k in send_order}
    channel_summary = {k: 0 for k in send_order}
    likely_sent = {k: 0 for k in send_order}
    likely_limit = max(0, int(limit * max(0.0, min(1.0, config.CYBER_LIKELY_MAX_SHARE))))

    for ch_key in send_order:
        if not dry_run and not get_topic_thread_id(ch_key):
            continue
        if not channel_queues.get(ch_key):
            ch_name = CHANNELS.get(ch_key, {}).get("name", ch_key)
            log.info(f" [{ch_key}] {ch_name}: 0 matching jobs this run")

    stale_skipped_total = 0

    # Round-robin send loop for fair per-channel distribution.
    while True:
        if _telegram_budget_remaining() <= 0:
            log.warning("Telegram send budget exhausted (including global spillover); remaining channel queues will wait for the next run.")
            break
        progress = False
        for ch_key in send_order:
            thread_id = get_topic_thread_id(ch_key)
            if not thread_id and not dry_run:
                continue
            if dry_run:
                thread_id = thread_id or 0
            if channel_summary[ch_key] >= limit:
                continue
            queue = channel_queues.get(ch_key, [])
            if not queue:
                continue

            # v73: pairs the drain already delivered this run count against
            # this channel's capacity and dedup so a just-sent job cannot be
            # re-posted, and the channel cap reflects the drain's work.
            drained_here = {
                dk for ck, dk in _drain_sent_pairs if ck == ch_key
            }
            channel_dedup_sent[ch_key].update(drained_here)
            channel_summary[ch_key] += len(drained_here)

            is_geo = ch_key in GEO_CHANNELS
            is_topic = not is_geo
            lane = "geo" if is_geo else "topic"
            sent_job = False

            # v71: a channel deactivated by terminal Telegram errors is
            # skipped at the routing layer too — its queue is not silently
            # drained into a dead chat; the jobs stay on the other
            # (healthy) routes of that pool.
            if not dry_run and _is_channel_deactivated(ch_key):
                delivery_lifecycle["channel_deactivated"] += 1
                continue

            while channel_cursors[ch_key] < len(queue):
                job = queue[channel_cursors[ch_key]]
                channel_cursors[ch_key] += 1

                # Defense in depth: a fallback or future queue change must
                # never bypass the cyber-verdict gate.
                if not _is_telegram_eligible(job):
                    continue
                allowed, location = validate_location_for_channel(job, ch_key)
                if not allowed:
                    log.warning(
                        " location_blocked_at_delivery: title=%s channel=%s type=%s country=%s reason=%s",
                        getattr(job, "title", "")[:70], ch_key, location.location_type,
                        location.normalized_country or "-", location.reason_code,
                    )
                    continue

                is_likely = getattr(job, "cyber_verdict", "") == "CYBER_LIKELY"
                # The likely cap is an upper bound on *remaining* capacity,
                # never a target and never a reservation that displaces a
                # confirmed candidate.  Queue ordering guarantees confirmed
                # items are exhausted first.
                if is_likely and likely_sent[ch_key] >= likely_limit:
                    continue

                # ── 2-day stale gate ─────────────────────────────────────
                if _is_too_old_to_send(job):
                    stale_skipped_total += 1
                    continue

                url_id = getattr(job, "url_id", "")
                job_dedup_key = _delivery_identity(job)

                # ── v71 TOPIC-channel evidence audit ─────────────────────
                # A topic channel is a specialist audience: a generic
                # role ("insufficient_cyber_evidence") that survived the
                # global geo routes must NOT land there on the strength of
                # the job's channel routing alone.  The job stays alive in
                # its geo routes and any other matched channels — only the
                # weak-affinity topic entry is blocked.
                if is_topic:
                    ev_key = getattr(job, "dedup_key", "") or id(job)
                    if ev_key not in _topic_evidence_cache:
                        _enrich_cyber_evidence(job)
                        _topic_evidence_cache[ev_key] = _publishable_cyber_evidence(job)[0]
                    if _topic_evidence_cache[ev_key] == "insufficient_cyber_evidence":
                        delivery_lifecycle["channel_mismatch"] += 1
                        log.info(
                            " 🔒 [v71] %s blocked on %s: no publish-grade cyber evidence "
                            "(title=%s) — kept on other matched channels.",
                            ch_key, lane, getattr(job, "title", "")[:60],
                        )
                        continue

                # ── Per-channel dedup ────────────────────────────────────
                if job_dedup_key in channel_dedup_sent[ch_key]:
                    continue

                # ── Cross-topic global dedup (CORE FIX) ─────────────────
                # A job may appear in ONE geo + ONE topic only.
                # Within topic channels: never repeat across channels.
                if is_topic and job_dedup_key in topic_globally_sent:
                    continue

                if db.was_sent_to_channel_recently(
                    job_key=job_dedup_key,
                    url_id=url_id,
                    channel_key=ch_key,
                    dedup_key=job_dedup_key,
                    hours=DAILY_SEND_HOURS,
                ):
                    delivery_lifecycle["already_sent"] += 1
                    continue

                message = format_job_message(job)

                # v73: a pair the pending-first drain already delivered this
                # run must never be re-posted — reserve would see the
                # proven sent row, return False, and the legacy guard would
                # then RE-PEND the pair, stranding it forever.  Skip it
                # cleanly and count it alongside the drain's work.
                if (ch_key, job_dedup_key) in _drain_sent_pairs:
                    delivery_lifecycle["drain_sent"] += 1
                    continue

                if dry_run:
                    # Preview follows the full router but does not reserve,
                    # post, or mutate the outbox.
                    delivery_lifecycle["would_send"] += 1
                    success = True
                else:
                    success = _send_to_topic(
                        message,
                        thread_id=thread_id,
                        db=db,
                        channel_key=ch_key,
                        delivery_key=job_dedup_key,
                        lifecycle=delivery_lifecycle,
                    )
                if not success:
                    continue

                channel_summary[ch_key] += 1
                if is_likely:
                    likely_sent[ch_key] += 1
                total_sent += 1
                sent_records.append((job, lane, ch_key))
                channel_dedup_sent[ch_key].add(job_dedup_key)
                # Lock this job from all other topic channels
                if is_topic and job_dedup_key:
                    topic_globally_sent.add(job_dedup_key)

                # Log source type for visibility
                src_priority = _source_priority_key(job)
                src_tag = (
                    "LI" if src_priority <= 12 else
                    "EG" if src_priority <= 22 else
                    "FL" if src_priority <= 25 else
                    "SRC"
                )
                log.info(
                    f"   [{'DRY_RUN ' if dry_run else ''}{ch_key}] {channel_summary[ch_key]}/{limit} ✓ "
                    f"[{src_tag}] {job.title[:45]}"
                )
                if not dry_run:
                    time.sleep(min(TELEGRAM_SEND_DELAY, max(0.0, _telegram_budget_remaining())))
                progress = True
                sent_job = True
                break

            if not sent_job and channel_cursors[ch_key] >= len(queue):
                continue

        if not progress:
            break

    if stale_skipped_total:
        log.info(f" ⏰ Stale gate: skipped {stale_skipped_total} job(s) older than {SEND_STALE_HOURS}h")

    # v67: pending telemetry — which of the sent pairs came from the
    # pending-first drain (old queued senders) versus new reservations this run.
    pending_sent = min(pending_retried, retried_sent)
    new_sent = max(0, total_sent - pending_sent)
    delivery_lifecycle["pending_sent"] = pending_sent
    delivery_lifecycle["new_sent"] = new_sent

    freshness = Counter()
    for job, _, _ in sent_records:
        posted = getattr(job, "posted_date", None)
        if not posted:
            freshness["unknown"] += 1
            continue
        try:
            if getattr(posted, "tzinfo", None) is not None:
                from datetime import timezone
                posted = posted.astimezone(timezone.utc).replace(tzinfo=None)
            age_hours = max(0.0, (now - posted).total_seconds() / 3600)
        except (TypeError, ValueError, OverflowError):
            freshness["unknown"] += 1
            continue
        freshness[
            "under_24h" if age_hours < 24 else
            "under_48h" if age_hours < 48 else
            "under_72h" if age_hours < 72 else "older"
        ] += 1
    if sent_records:
        log.info(
            " Freshness sent: <24h=%d 24-48h=%d 48-72h=%d older=%d unknown=%d",
            freshness["under_24h"], freshness["under_48h"], freshness["under_72h"],
            freshness["older"], freshness["unknown"],
        )

    for ch_key in send_order:
        if not dry_run and not get_topic_thread_id(ch_key):
            continue
        ch_name = CHANNELS.get(ch_key, {}).get("name", ch_key)
        sent_this_ch = channel_summary.get(ch_key, 0)
        if sent_this_ch > 0:
            log.info(f" Channel [{ch_key}] {ch_name}: sent {sent_this_ch} jobs")
        elif channel_queues.get(ch_key):
            log.info(f" Channel [{ch_key}] {ch_name}: 0 sent (all filtered/deduped/stale)")

    log.info("=" * 40)
    log.info(" Per-Channel Summary:")
    for k, v in channel_summary.items():
        ch_name = CHANNELS.get(k, {}).get("name", k)
        bar = "✅" if v > 0 else "⚪"
        log.info(f"   {bar} {ch_name}: {v} jobs")
    log.info("=" * 40)
    pending_after = 0 if dry_run else db.count_pending_delivery_rows()
    pending_unique_after = 0 if dry_run else db.count_pending_unique_jobs()
    delivery_lifecycle["pending_after"] = pending_after
    delivery_lifecycle["pending_unique_after"] = pending_unique_after

    log.info(
        " Telegram delivery lifecycle: eligible=%d routed=%d reserved=%d sent=%d failed=%d channel_mismatch=%d channel_deactivated=%d already_sent=%d delivery_pending=%d pending_before=%d pending_unique_before=%d pending_retried=%d pending_sent=%d new_sent=%d pending_after=%d pending_unique_after=%d%s",
        delivery_lifecycle["eligible"], delivery_lifecycle["routed"],
        delivery_lifecycle["reserved"], delivery_lifecycle["sent"],
        delivery_lifecycle["failed"], delivery_lifecycle["channel_mismatch"],
        delivery_lifecycle["channel_deactivated"],
        delivery_lifecycle["already_sent"],
        delivery_lifecycle["delivery_pending"],
        delivery_lifecycle["pending_before"], delivery_lifecycle["pending_unique_before"],
        delivery_lifecycle["pending_retried"],
        delivery_lifecycle["pending_sent"], delivery_lifecycle["new_sent"],
        pending_after, pending_unique_after,
        f" would_send={delivery_lifecycle['would_send']}" if dry_run else "",
    )

    return total_sent, sent_records


def _escape(text):
    if not text:
        return ""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))

_DOMAIN_LABELS = {
    "soc": "SOC / Blue Team",
    "pentest": "Penetration Testing / Red Team",
    "cloudsec": "Cloud & Infrastructure Security",
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


def _display_level(job) -> str:
    """Use a helpful neutral default when a standard IC role omits seniority."""
    level = _level_label(job)
    if level != "Open":
        return level
    title = (getattr(job, "title", "") or "").lower()
    if re.search(r"\b(engineer|analyst|specialist|consultant|administrator|developer)\b", title):
        return "Mid-Level"
    return level


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
    if _is_arab_region_job(job):
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
        return " Arab Region"
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


def _posted_label(job) -> str:
    """Render a compact, human-readable age without exposing raw datetimes."""
    posted = getattr(job, "posted_date", None)
    if not posted:
        return "Recently"
    try:
        if getattr(posted, "tzinfo", None) is not None:
            from datetime import timezone

            posted = posted.astimezone(timezone.utc).replace(tzinfo=None)
        seconds = max(0, int((datetime.now() - posted).total_seconds()))
    except (TypeError, ValueError, OverflowError):
        return "Recently"
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def _display_location(job) -> str:
    """Keep the source location intact while normalising remote separators."""
    raw = re.sub(r"\s+", " ", (getattr(job, "location", "") or "").strip())
    if not raw and _is_remote_job(job):
        return "Remote · Worldwide"
    if raw:
        raw = raw.replace(" / ", " · ").replace(" - ", " · ")
        return _escape(raw)
    return "Unknown"


# Keep the source visible to subscribers without exposing internal scraper keys.
_SOURCE_LABELS = {
    "linkedin": "LinkedIn",
    "indeed": "Indeed",
    "greenhouse": "Greenhouse / Direct ATS",
    "lever": "Lever / Direct ATS",
    "company_careers": "Official Company Careers",
    "official_careers": "Official Company Careers",
    "wuzzuf": "Wuzzuf",
    "forasna": "Forasna",
    "tanqeeb": "Tanqeeb",
    "akhtaboot": "Akhtaboot",
    "wazzif": "Wazzif",
    "jobzella": "Jobzella",
    "shaghalni": "Shaghalni",
    "bayt": "Bayt",
    "gulftalent": "GulfTalent",
    "naukrigulf": "Naukrigulf",
    "qureos": "Qureos",
    "upwork": "Upwork",
    "freelancer": "Freelancer",
    "mostaql": "Mostaql",
    "khamsat": "Khamsat",
    "fiverr": "Fiverr",
    "remoteok": "RemoteOK",
    "remotive": "Remotive",
    "we_work_remotely": "We Work Remotely",
    "wellfound": "Wellfound",
    "glassdoor": "Glassdoor",
}


def _source_label(job) -> str:
    """Return a subscriber-facing source name from a source key or source name."""
    raw_key = str(getattr(job, "source_key", "") or "").strip().lower()
    raw_source = str(getattr(job, "source", "") or "").strip()
    combined = f"{raw_key} {raw_source.lower()}"

    # LinkedIn has several internal fetcher keys, all of which should display
    # as the single familiar source name.
    if "linkedin" in combined:
        return "LinkedIn"

    for key, label in _SOURCE_LABELS.items():
        if key in combined:
            return label

    fallback = raw_source or raw_key or "Job board"
    fallback = re.sub(r"[_-]+", " ", fallback)
    fallback = re.sub(r"\s+", " ", fallback).strip()
    return fallback.title()

def _extract_skills(text):
    skill_map = (
        ("ping identity", "Ping Identity"), ("ping", "Ping Identity"), ("okta", "Okta"),
        ("identity security", "Identity Security"), ("identity and access", "Identity & Access"),
        ("identity access", "Identity & Access"), ("access management", "IAM"), ("iam", "IAM"),
        ("aws", "AWS"), ("azure", "Azure"), ("gcp", "GCP"),
        ("threat intelligence", "Threat Intelligence"), ("threat intel", "Threat Intelligence"),
        ("siem", "SIEM"), ("splunk", "Splunk"), ("qradar", "QRadar"),
        ("sentinel", "Microsoft Sentinel"), ("incident response", "Incident Response"),
        ("pentest", "Pentest"), ("burp", "Burp Suite"), ("nessus", "Nessus"),
        ("metasploit", "Metasploit"), ("iso 27001", "ISO 27001"),
        ("nist", "NIST"), ("grc", "GRC"), ("pci", "PCI-DSS"),
        ("crowdstrike", "CrowdStrike"), ("defender", "Microsoft Defender"),
        ("wireshark", "Wireshark"), ("oscp", "OSCP"), ("cissp", "CISSP"),
        ("python", "Python"), ("kubernetes", "Kubernetes"),
    )
    found: list[str] = []
    for keyword, label in skill_map:
        if keyword in text and label not in found:
            found.append(label)
    return " · ".join(found[:5]) if found else "Cybersecurity"


def _domain_header_icon(domain: str) -> str:
    return {
        "Cloud & Infrastructure Security": "☁️",
        "SOC / Blue Team": "🛰️",
        "Penetration Testing / Red Team": "🎯",
        "AppSec / DevSecOps": "🔒",
        "Network Security": "🌐",
        "GRC / Compliance": "📋",
        "Training / Program": "🎓",
    }.get(domain, "🛡️")

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


def format_hiring_signal_message(signal) -> str:
    """v72: Format a HIRING SIGNAL card — distinct from a job card, with no
    apply link (the verification chain found no application URL).  The
    employer identity, inferred role and the signal snippet are shown so
    readers can act on the signal themselves, and the card is explicitly
    labeled as a signal, never as a verified listing."""
    company = _escape(signal.company) if signal.company else "Company"
    role = _escape(signal.inferred_title)
    snippet = _escape((signal.source_text or "").strip()[:220])
    lines = [
        "📡 <b>HIRING SIGNAL — role not yet published</b>",
        "",
        f"🏢 <b>{company}</b>",
        f"🎯 Inferred role: <b>{role}</b>",
        "",
        f"💬 “{snippet}”",
        "",
        "🔎 Verified through the official search chain — no public",
        "application URL was found, so this team is likely still",
        "building the role.  Follow the company's careers page.",
    ]
    if getattr(signal, "signal_source", ""):
        lines.append(f"🌐 Signal source: <b>{_escape(str(signal.signal_source))}</b>")
    return "\n".join(lines).strip()


def format_hr_post_message(job) -> str:
    """Format an evidence-backed LinkedIn hiring post in the same card style."""
    text = (job.title + " " + job.description + " " + _flatten_tags(job.tags)).lower()
    domain = _domain_label(job)
    level = _display_level(job)
    skills = _extract_skills(text)
    post_fields = _parse_hr_post_fields(job)

    title = _escape(job.title)
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

    employment = [level]
    if post_fields.get("work_model"):
        employment.append(_escape(post_fields["work_model"]))

    lines = [
        f"{_domain_header_icon(domain)} <b>{domain}</b>",
        "",
        f"📢 <b>{title}</b>",
        "",
        f"🏢 <b>{company or 'Hiring company'}</b>",
        f"📍 {_display_location(job)}",
        f"🕒 Posted: {_posted_label(job)}",
        f"💼 {' · '.join(employment)}",
    ]
    if poster:
        lines.append(f"👤 Posted by: {_escape(poster)}")
    if job.salary:
        lines.append(f"💰 {_escape(str(job.salary))}")
    if skills:
        lines.extend(["", f"⚙️ {skills}"])
    if post_fields.get("apply_email"):
        lines.append(f"✉️ <code>{_escape(post_fields['apply_email'])}</code>")
    if post_fields.get("apply_whatsapp"):
        lines.append(f"📱 <code>{_escape(post_fields['apply_whatsapp'])}</code>")

    # HR cards always point to the original LinkedIn post.  An external form
    # mentioned inside the post must never replace the source-post link.
    post_url = job.canonical_url or job.url
    if post_url:
        lines.extend([
            "",
            f"🌐 Source: <b>{_escape(_source_label(job))}</b>",
            f'<a href="{_escape(post_url)}">🚀 Open Original Post →</a>',
        ])

    return "\n".join(lines).strip()


def format_job_message(job):
    """Format a compact, professional HTML card for a standard job listing."""
    # HR posts retain their dedicated evidence/contact template.
    if (getattr(job, "content_type", "") or "").lower() == "hr_post":
        return format_hr_post_message(job)

    text = (job.title + " " + job.description + " " + _flatten_tags(job.tags)).lower()
    level = _display_level(job)
    domain = _domain_label(job)
    skills = _extract_skills(text)
    title = _escape(job.title)
    company = _escape(job.company) if job.company else "Unknown"
    employment = [level]
    if job.job_type:
        employment.append(_escape(job.job_type))

    lines = [
        f"{_domain_header_icon(domain)} <b>{domain}</b>",
        "",
        f"🔐 <b>{title}</b>",
        "",
        f"🏢 <b>{company}</b>",
        f"📍 {_display_location(job)}",
        f"🕒 Posted: {_posted_label(job)}",
        f"💼 {' · '.join(employment)}",
    ]
    if job.salary:
        lines.append(f"💰 {_escape(str(job.salary))}")
    if skills:
        lines.extend(["", f"⚙️ {skills}"])

    apply_url = job.canonical_url or job.url
    if apply_url:
        lines.extend([
            "",
            f"🌐 Source: <b>{_escape(_source_label(job))}</b>",
            f'<a href="{_escape(apply_url)}">🚀 Apply Now →</a>',
        ])
    # v72: Personal Opportunity Score — ranking layer on top of the card.
    # Rendered for every candidate that cleared all gates; it never relaxes
    # any gate, and the config flag can disable it without code changes.
    if getattr(config, "OPPORTUNITY_SCORE_ENABLED", True):
        try:
            from opportunity_score import (
                compute_opportunity_score, format_opportunity_block,
            )
            breakdown = compute_opportunity_score(job)
            if breakdown.total > 0:
                lines.append("")
                lines.append(format_opportunity_block(breakdown))
        except Exception:  # scoring display must never break delivery
            log.debug("v72 opportunity score render skipped", exc_info=True)
    return "\n".join(lines).strip()


# 
#  Sending � per channel, no cross-channel duplicates
# 

_missing_token_warned: bool = False  # warn once per process, not once per call


def _send_to_topic(message, thread_id=None, db: JobsDB | None = None, channel_key: str = "",
                   delivery_key: str = "", lifecycle: Counter[str] | None = None):
    global _missing_token_warned
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        if not _missing_token_warned:
            log.warning(
                "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID — "
                "set them in your .env file (local) or GitHub Secrets (CI). "
                "No messages will be sent this run."
            )
            _missing_token_warned = True
        if lifecycle is not None:
            lifecycle["failed"] += 1
        return False

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if thread_id:
        payload["message_thread_id"] = thread_id

    delivery_id = f"{channel_key}:{delivery_key}" if channel_key and delivery_key else ""
    if db and delivery_id:
        reserved, delivery_proof = db.reserve_telegram_delivery(
            delivery_key=delivery_id, channel_key=channel_key,
            thread_id=thread_id, payload=payload,
        )
        if not reserved:
            # v73: ``reserve_telegram_delivery`` now distinguishes the two
            # rejections.  ``delivery_proof=True`` means the outbox holds a
            # CONFIRMED sent row (status='sent' with sent_at) — the message
            # WAS delivered, so re-posting is forbidden AND the pair must
            # NEVER be re-pended: the previous guard overwrote proven
            # deliveries back to ``delivery_pending``, stranding them in a
            # loop where every run sent the message then queued the pair
            # again (sent=0 forever).  ``delivery_proof=False`` is a legacy
            # same-run retry-exhausted row: the v66 safety net keeps it
            # visible as ``delivery_pending`` for the next run's retry.
            if delivery_proof:
                log.info(
                    "Telegram delivery already sent for [%s] (proof on "
                    "outbox row) — pair skipped, not re-posted, not "
                    "re-pended.", channel_key,
                )
                if lifecycle is not None:
                    lifecycle["already_sent"] += 1
            else:
                pending_logged = False
                if (
                    config.TELEGRAM_DELIVERY_PENDING_ON_TERMINAL_STATE
                    and delivery_id
                    and hasattr(db, "mark_delivery_pending")
                    and lifecycle is not None
                ):
                    try:
                        db.mark_delivery_pending(delivery_id)
                        pending_logged = True
                    except Exception:
                        pending_logged = False
                if pending_logged:
                    log.info(
                        "Telegram delivery blocked by terminal channel "
                        "state for [%s]; candidate queued as "
                        "delivery_pending for the next run (never silently "
                        "dropped).", channel_key,
                    )
                    lifecycle["delivery_pending"] += 1
                else:
                    log.info(
                        "Telegram delivery already sent/retry-exhausted "
                        "for [%s]", channel_key,
                    )
                    lifecycle["already_sent"] += 1
            return False
        if lifecycle is not None:
            lifecycle["reserved"] += 1

    ok, status, err, retry_after = _post_telegram_payload(payload)
    if ok:
        if db and delivery_id:
            db.mark_telegram_delivery(delivery_id, status="sent")
        if lifecycle is not None:
            lifecycle["sent"] += 1
        return True

    log.error("Telegram error " + str(status) + ": " + (err or "unknown error"))
    if db and delivery_id:
        if status == 429:
            db.mark_telegram_delivery(
                delivery_id, status="retry_429", error=f"status={status} {err}".strip(),
                delay_seconds=_compute_retry_delay(0, retry_after=retry_after),
            )
            log.warning("Queued known-safe Telegram 429 retry for [%s]", channel_key)
            if lifecycle is not None:
                lifecycle["failed"] += 1
            return False

        # A SEND_FAILED row gets exactly one in-process retry.  The outbox
        # records each real network call, so a later run can safely resume a
        # crash-reserved row without confusing RESERVED with SENT.
        db.mark_telegram_delivery(
            delivery_id, status="send_failed", error=f"status={status} {err}".strip(),
        )
        log.warning("Retrying Telegram SEND_FAILED once for [%s]", channel_key)
        ok, retry_status, retry_err, _ = _post_telegram_payload(payload)
        if ok:
            db.mark_telegram_delivery(delivery_id, status="sent")
            if lifecycle is not None:
                lifecycle["sent"] += 1
            return True
        log.error(
            "Telegram retry error %s: %s", retry_status, retry_err or "unknown error",
        )
        db.mark_telegram_delivery(
            delivery_id, status="send_failed",
            error=f"status={retry_status} {retry_err}".strip(),
        )
    if lifecycle is not None:
        lifecycle["failed"] += 1
    return False


def send_test_canary() -> bool:
    """Send an opt-in delivery canary to TOPIC_TEST, never to a live route."""
    if not config.TELEGRAM_CANARY:
        return False
    if not config.TOPIC_TEST:
        log.warning("TELEGRAM_CANARY=true but TOPIC_TEST is not configured")
        return False
    day_key = datetime.utcnow().strftime("%Y-%m-%d")
    return _send_to_topic(
        "<b>Cybersecurity Jobs Bot</b>\nDelivery canary succeeded.",
        thread_id=config.TOPIC_TEST,
        db=get_db(),
        channel_key="test_canary",
        delivery_key=day_key,
    )
