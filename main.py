"""
Cybersecurity Jobs Bot — Main entry point — v45
Pipeline: fetch (ASYNC) → filter → dedup (3-layer) → score → tier-select → send.

v45 CHANGES (Bot0 → Bot1 migration):
   intelligence/ sub-package (geo, seniority, domain, intent, pool_builder, dedupe)
   greenhouse_expanded source (Big Tech + SaaS + Lever security vendors)
   gulf_monster source (Monster Gulf RSS — UAE + KSA)
   jsearch_enhanced source (JSearch Egypt + Gulf + Remote merged)
   _build_final_pool() now delegates to intelligence.pool_builder (testable)
   Backward-compat: all existing callers unchanged
"""

import os
import asyncio
import inspect
import json
import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import config
from sources import SourceSpec, get_source_specs
from models import CyberVerdict, classify_jobs
from dedup import load_seen_ids, save_seen_ids, deduplicate, mark_as_seen, deduplicate_sent, smart_expire
import database
from database import JobsDB, get_db, set_delivery_run_at
from telegram_sender import send_jobs, send_test_canary, format_hiring_signal_message
from sources.hiring_signal_discovery import (
    detect_hiring_signal, verify_signal, HiringSignal, SignalVerificationResult,
    get_v72_signal_telemetry, _reset_v72_telemetry,
)
from scoring import score_job_int as score_job, diversity_rerank
from ai_filter import classify_job as ai_classify_job, batch_classify_borderline
from intelligence import (
    classify_delivery_geo,
    classify_geo,
    is_entry_level,
    is_remote_job,
)
from intelligence.pool_builder import build_final_pool as _pool_builder_impl

# Legacy import kept for any call-sites that still use job_intelligence directly
from job_intelligence import is_linkedin_job
from sources.http_utils import get_http_metrics, get_proxy_status, reset_http_run_state
from sources.marketplace_sources import SourceResult
from run_budget import (
    remaining as budget_remaining,
    snapshot as budget_snapshot,
    source_deadline,
    start_phase,
    start_run,
)
from sources.linkedin_unified import get_linkedin_telemetry
import egypt_funnel  # v74: Egypt/Arab delivery funnel tracker
from review_workflow import make_run_id, poll_review_updates, queue_review_samples, record_metrics

# ── v72: Hidden Jobs Discovery helpers ─────────────────────────────────────

def _mine_hiring_signals(pool: list) -> list[HiringSignal]:
    """Scan accepted HR posts in the pool for hiring signals that carry
    cyber intent and an identifiable company, skipping any signal already
    represented by a verified job elsewhere in the pool."""
    signals: list[HiringSignal] = []
    seen_candidates: set[tuple[str, str]] = set()
    pool_companies_roles: set[tuple[str, str]] = {
        ((getattr(j, "company", "") or "").lower(),
         (getattr(j, "title", "") or "").lower())
        for j in pool if getattr(j, "content_type", "") == "hr_post"
    }
    for job in pool:
        if (getattr(job, "content_type", "") or "").lower() != "hr_post":
            continue
        text = f"{job.title} {job.description or ''}"
        if not text.strip():
            continue
        signal = detect_hiring_signal(text)
        if signal is None:
            continue
        signal.signal_source = "linkedin_hr_post"
        candidate = (signal.company.lower(), signal.inferred_title.lower())
        if candidate in seen_candidates:
            continue
        if candidate in pool_companies_roles:
            # A verified listing for the same company/role already made the
            # pool — prefer the real listing over the duplicate signal.
            continue
        seen_candidates.add(candidate)
        signals.append(signal)
    return signals


def _mine_careers_page_signals() -> list[HiringSignal]:
    """v74: mine hiring-announcement signals from official Egyptian careers
    pages through the Phase-3 recovery ladder (direct GET → Jina reader).

    Why this lane exists: the v74 diagnosis showed Egyptian sources failing
    with circuit-open/timeout BEFORE they could surface jobs — but several
    of those same pages still carry a public \"We're hiring\" / careers
    announcement block that names security headcount even when the listing
    feed is empty or unreachable. The announcement is a signal, not a job:
    it still has to pass the cyber intent, region and dedup rules downstream.

    The lane is deliberately cheap and bounded: at most two pages (10s cap
    each, matching the HR Posts read cap), tried through the same ladder
    steps already validated in Phase 3 — the careers pipeline never spins
    up Playwright for signal mining, and a page the ladder could not read
    is silently skipped rather than retried.
    """
    from sources.hiring_signal_discovery import extract_careers_page_signals
    # Self-contained import: the recovery map may exist under any name in
    # older official_careers snapshots, and the Jina reader constants are
    # inlined here so this lane never crashes when the deployed copy of
    # official_careers.py is outdated (no hidden dependency breakage).
    from sources import official_careers as _oc
    _EGYPT_RECOVERY_URLS = (
        getattr(_oc, "_EGYPT_RECOVERY_URLS", None)
        or getattr(_oc, "_EGYPT_ALT_ENDPOINTS", None)
        or {}
    )
    _JINA_READER_URL_TEMPLATE = "https://r.jina.ai/{url}"
    _JINA_PUBLIC_READER_HEADERS = {
        "Accept": "text/html",
        "X-Locale": "en",
        "User-Agent": "Mozilla/5.0 (compatible; CyberJobsBot/1.0)",
    }
    from sources.http_utils import get_text

    if not getattr(config, "ENABLE_CAREERS_PAGE_SIGNALS", True):
        return []
    # Priority = the user-flagged Egyptian sources; skip sources the
    # recovery map knows nothing about — unknown URLs would be noise.
    priority_keys = [
        "cib_egypt", "qnb_egypt", "aaib", "adib_egypt", "banque_misr",
        "banque_du_caire", "mashreq_egypt", "bank_nxt", "itida",
        "nbe", "saib", "raya", "smart_village", "telecom_egypt",
    ]
    sources: list[tuple[str, str]] = []
    for key in priority_keys:
        urls = list(_EGYPT_RECOVERY_URLS.get(key) or [])
        if urls:
            sources.append((key, urls[0]))
    if not sources:
        return []
    # Only the first two read-able pages get the signal scan; the lane must
    # not consume the hiring-signals budget the HR-Posts ladder needs.
    budget_left = budget_remaining()
    signals: list[HiringSignal] = []
    fetched = 0
    for key, url in sources[:2]:
        if budget_left is not None and budget_left < 10:
            break
        page_text = _read_careers_page(key, url, get_text)
        if not page_text:
            continue
        fetched += 1
        signals += extract_careers_page_signals(page_text, key, url)
    if fetched:
        log.info(
            "📡 v74 careers-page signals: %d pages read, %d announcement "
            "signals found", fetched, len(signals),
        )
    return signals


def _read_careers_page(key: str, url: str, get_text_fn) -> str | None:
    """v74: lightweight page read following the Phase-3 ladder — direct GET
    first, then the public Jina reader (a different IP pool from the bot's
    exit, so a circuit-open portal can still answer).  Short cap, single
    retry class: a careers page that does not answer quickly is a skip, not
    a budget sink.

    Returns the page text (tags collapsed to spaces) or ``None``.
    """
    import re as _re
    # Fully self-contained constants: never depend on module-level names
    # that may be missing from an older deployed snapshot of main.py.
    _reader_url_template = "https://r.jina.ai/{url}"
    _reader_headers = {
        "Accept": "text/html",
        "X-Locale": "en",
        "User-Agent": "Mozilla/5.0 (compatible; CyberJobsBot/1.0)",
    }
    html: str | None = None
    try:
        html = get_text_fn(url, timeout=8, max_retries=1)
    except Exception:  # noqa: BLE001 — the reader step is the rescue path
        pass
    if not html:
        from urllib.parse import quote as _quote
        reader_url = _reader_url_template.format(url=_quote(url))
        try:
            html = get_text_fn(
                reader_url, headers=_reader_headers,
                timeout=8, max_retries=0,
            )
        except Exception as exc:  # noqa: BLE001 — honest skip
            log.debug("v74 careers signal page unreadable [%s]: %s", key, exc)
            return None
    if not html:
        return None
    if len(html) > 2 * 1024 * 1024:
        return None
    text = _re.sub(r"(?is)<script.*?</script>", " ", html)
    text = _re.sub(r"(?is)<style.*?</style>", " ", text)
    text = _TAG_RE.sub(" ", unescape(text))
    text = _SPACE_RE.sub(" ", text)
    return text.strip()


# Reused tag/whitespace helpers (official_careers defines the same pair).
_TAG_RE = __import__("re").compile(r"<[^>]+>")
_SPACE_RE = __import__("re").compile(r"\s+")
import html as html_lib
from html import unescape


_AGENCY_SUFFIX_TOKENS = (
    "agency", "agencies", "recruitment", "recruiters", "recruiting",
    "staffing", "placements", "resourcing", "executive search",
    "talent acquisition", "hr solutions", "talent solutions", "hr group",
)


def _detect_recruiter(job) -> str:
    """v76 (spec point 6): recognise staffing agencies / recruiters so the
    card separates them from the real employer.  Detection is deliberately
    conservative: only an explicit agency/recruiting name pattern in the
    company field sets the recruiter, so ordinary company names are never
    split.  Returns the recruiter name or "" when nothing is known."""
    import re as _re
    company = str(getattr(job, "company", "") or "").strip()
    if not company:
        return ""
    lower = company.lower()
    is_agency = any(lower.endswith(t) for t in _AGENCY_SUFFIX_TOKENS) or \
        any((" " + t) in (" " + lower) for t in _AGENCY_SUFFIX_TOKENS
            if t.startswith(("talent", "executive", "hr ", "placements")))
    if not is_agency:
        return ""
    # The card shows the real employer only when the listing itself names
    # one (e.g. "Client: X", "on behalf of X").  We never guess an employer;
    # if none is named, the agency name stays on the employer line as the
    # verified poster, and the recruiter field still records the identity.
    text = f"{job.title or ''} {job.description or ''}".lower()
    for pattern in (
        r"client:\s*([\w\s&.,'-]{2,40})",
        r"on behalf of ([\w\s&.,'-]{2,40})",
        r"for ([\w\s&.,'-]{2,40})\b",
    ):
        match = _re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return company


def _enrich_canonical_record(jobs: list) -> None:
    """v76: attach the canonical record (primary_category + category evidence
    + source-backed skills + recruiter identity) to every job.  This is the
    single enrichment point — telegram_sender formats from these fields only
    and never re-extracts keywords, so no skill/category/employer can be
    invented downstream (spec point 15)."""
    from sources.job_classification import (
        classify_category, extract_skills_with_evidence,
    )
    for job in jobs:
        try:
            verdict = classify_category(job)
            job.primary_category = verdict.primary_category
            job.category_confidence = verdict.confidence
            job.category_evidence = verdict.evidence
            job.secondary_categories = verdict.secondary_categories
            job.skills_with_evidence = extract_skills_with_evidence(job)
            # v76 (spec point 6): keep recruiter/agency identity separate from
            # the hiring employer on the card; only set when a recruiter
            # pattern is actually detected — never guessed.
            if not getattr(job, "recruiter_name", ""):
                try:
                    detected = _detect_recruiter(job)
                    if detected:
                        job.recruiter_name = detected
                except Exception:  # noqa: BLE001 — enrichment never breaks
                    pass
        except Exception as exc:  # noqa: BLE001 — defaults stay empty
            log.debug("v76 canonical enrichment skipped: %s", exc)


def _v72_verification_search_fn(spec: dict) -> list[tuple[str, str]]:
    """Wire the HR Posts backend ladder to the verification chain, in
    descending order of trust: CSE → SerpAPI → Bing.  Each backend keeps its
    own park/streak state from the HR Posts run, so a backend already parked
    for that run is silently skipped (one backend's failure must not cost the
    bot a fresh request cap)."""
    from sources.linkedin_hr_posts_scraper import (
        _search_via_google_cse, _search_via_serpapi, _search_via_bing_html,
    )
    query = spec.get("query", "")
    ladder = [
        ("google_cse", _search_via_google_cse),
        ("serpapi", _search_via_serpapi),
        ("bing", _search_via_bing_html),
    ]
    targets = {"careers_search": ladder, "linkedin_jobs": ladder,
               "ats_apply": ladder}
    for _backend, fn in targets.get(spec.get("kind", ""), ladder):
        try:
            hits = fn(query)
            if hits:
                return hits[:5]
        except Exception:  # noqa: BLE001 — continue down the ladder
            pass
    return []


def _v72_job_builder(url: str, title: str, company: str):
    """Convert a found application URL into a pool-grade Job.  Title and
    description stay empty-by-design: the candidate must re-pass the cyber
    classifier and evidence gate downstream — the discovery layer never
    hands a bare URL a free pass."""
    from models import Job
    return Job(
        title="", company=company, location="", url=url, source="linkedin",
        source_key="linkedin_hr_posts", description="",
        content_type="job_listing", verified_by_signal=False,
    )


def _discover_hidden_jobs(pool: list, *, dry_run: bool = False
                          ) -> tuple[list, list[SignalVerificationResult]]:
    """Run Hidden Jobs Discovery within its own bounded budget: detect
    signals, verify each through the official chain, and split outcomes
    into verified jobs (returned for pool merge) and hiring signals
    (returned for distinct-card delivery)."""
    if not getattr(config, "ENABLE_HIRING_SIGNALS_DISCOVERY", True):
        return [], []
    candidates = _mine_hiring_signals(pool)
    # v74: careers-page announcement lane — same candidate pool, distinct
    # lane tag, merged into the HR-post candidates so one verification
    # budget and one gate chain serve both surfaces.
    candidates += _mine_careers_page_signals()
    if not candidates:
        return [], []
    _TELEMETRY_LOCAL = __import__("sources.hiring_signal_discovery",
                                  fromlist=["_TELEMETRY"])._TELEMETRY
    verified_jobs: list = []
    signals: list[SignalVerificationResult] = []
    start_phase("hiring_signals", getattr(config, "HIRING_SIGNALS_BUDGET_SECONDS", 150))
    log.info("📡 v72 Hidden Jobs Discovery: %d candidate signals; verifying…", len(candidates))
    try:
        for signal in candidates:
            _TELEMETRY_LOCAL["signals_detected"] += 1
            try:
                with source_deadline(60):
                    outcome = verify_signal(
                        signal,
                        search_fn=_v72_verification_search_fn,
                        job_builder=None if dry_run else _v72_job_builder,
                    )
            except Exception as exc:  # verification never kills the run
                log.debug("v72 signal verification failed: %s", exc)
                continue
            if outcome.is_verified_job:
                if not dry_run and outcome.verified_job is not None:
                    verified_jobs.append(outcome.verified_job)
            else:
                signals.append(outcome)
    finally:
        log.info(
            "📡 v72 discovery done: %d verified jobs merged, %d hiring signals "
            "to deliver", len(verified_jobs), len(signals),
        )
    return verified_jobs, signals


def _deliver_hiring_signals(outcomes: list[SignalVerificationResult]) -> int:
    """Deliver HIRING SIGNAL cards to matching channels: per-signal GEO
    routing (Egypt / Arab / remote) with per-channel caps and run-wide
    dedup, inside the telegram budget window."""
    from config import (
        CHANNELS, MAX_JOBS_PER_CHANNEL, HIRING_SIGNALS_PER_CHANNEL,
        HIRING_SIGNAL_DEDUP_HOURS,
    )
    from config import EGYPT_PATTERNS, ARAB_PATTERNS
    from telegram_sender import format_hiring_signal_message
    from intelligence.geo import classify_delivery_geo as _classify_geo

    db = get_db()
    sent = 0
    channel_counts: Counter[str] = Counter()
    for outcome in outcomes:
        signal = outcome.signal
        lowered = f"{signal.source_text} {signal.region_hint}".lower()
        geo = "egypt" if any(p in lowered for p in EGYPT_PATTERNS) else (
            "gulf" if any(p in lowered for p in ARAB_PATTERNS) else "remote")
        for channel_key in (geo, "remote"):
            if channel_key not in CHANNELS:
                continue
            if channel_counts[channel_key] >= HIRING_SIGNALS_PER_CHANNEL:
                continue
            # Per-channel cap: signals never flood a channel (2/run default).
            if channel_counts[channel_key] >= MAX_JOBS_PER_CHANNEL:
                continue
            signal_key = ("signal:" + (signal.company or "unknown").lower()
                          + ":" + signal.inferred_title.lower())
            if db.was_signal_sent_recently(signal_key, channel_key,
                                           HIRING_SIGNAL_DEDUP_HOURS):
                continue
            thread_id = get_topic_thread_id(channel_key)
            try:
                with source_deadline(20):
                    ok = _send_signal_card(
                        db, channel_key, signal_key, format_hiring_signal_message(signal),
                        thread_id=thread_id,
                    )
                if ok:
                    db.record_sent_signal(signal_key, channel_key)
                    sent += 1
                    channel_counts[channel_key] += 1
                    log.info(
                        "📡 HIRING SIGNAL delivered [%s/%s]: %s",
                        channel_key, signal.company, signal.inferred_title,
                    )
                    break  # one channel per signal is enough
            except Exception as exc:  # one signal failure must not stop the rest
                log.debug("v72 signal delivery failed: %s", exc)
    return sent


def _send_signal_card(db, channel_key: str, signal_key: str, message: str,
                      thread_id=None) -> bool:
    """Send a single HIRING SIGNAL card using the same outbox guarantees as
    normal jobs (retry queue, terminal-status classification)."""
    from telegram_sender import send_test_canary
    import requests
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if thread_id:
        payload["message_thread_id"] = thread_id
    for attempt in range(3):
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                json=payload, timeout=20,
            )
            if resp.status_code == 200:
                return True
            if resp.status_code in (403, 404, 400, 401):
                return False  # terminal — never retry the channel for this
            if resp.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            return False
        except requests.RequestException:
            time.sleep(1 * (attempt + 1))
    return False


def _log_v72_signal_summary(verified_jobs, hiring_signals) -> None:
    """Emit the end-of-run 📡 Hidden Jobs Discovery summary line."""
    try:
        t = get_v72_signal_telemetry()
    except Exception:
        return
    lanes = " ".join(
        f"{k}={v}" for k, v in t.items() if k.startswith("signals_detected_") and v
    )
    log.info(
        "📡 v72 Hidden Jobs Discovery: detected=%d verified_jobs=%d "
        "hiring_signals=%d%s",
        t["signals_detected"], t["signals_verified_job"],
        t["signals_emitted_hiring_signal"],
        f" [{lanes}]" if lanes else "",
    )


# ── Logging setup ──────────────────────────────────────────────────────────
_log_format = os.getenv("LOG_FORMAT", "text")
if _log_format == "json":
    import json as _json

    class _JsonFormatter(logging.Formatter):
        def format(self, record):
            d = {
                "ts":     self.formatTime(record, datefmt="%H:%M:%S"),
                "level":  record.levelname,
                "logger": record.name,
                "msg":    record.getMessage(),
            }
            if record.exc_info:
                d["exc"] = self.formatException(record.exc_info)
            return _json.dumps(d, ensure_ascii=False)

    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
else:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

log = logging.getLogger("main")


# ── Pool builder ───────────────────────────────────────────────────────────

def _build_final_pool(jobs: list, *, telemetry: dict | None = None) -> list:
    """Delegate to intelligence.pool_builder — single source of truth for pool logic."""
    return _pool_builder_impl(jobs, score_fn=score_job, telemetry=telemetry)


def _freshness_bucket(job, *, now: datetime) -> str:
    """Return an audit-only freshness bucket without changing delivery policy."""
    posted = getattr(job, "posted_date", None)
    if not posted:
        return "unknown"
    try:
        if getattr(posted, "tzinfo", None) is not None:
            from datetime import timezone
            posted = posted.astimezone(timezone.utc).replace(tzinfo=None)
        age_hours = max(0.0, (now - posted).total_seconds() / 3600.0)
    except (TypeError, ValueError, OverflowError, AttributeError):
        return "unknown"
    if age_hours < 24:
        return "<24h"
    if age_hours < 48:
        return "24-48h"
    if age_hours < 72:
        return "48-72h"
    return "72h+"


def _log_source_run_telemetry(source_reports: dict[str, dict]) -> None:
    """Emit compact, run-level timeout and parser-drift results."""
    timeouts = [
        (key, row) for key, row in source_reports.items()
        if row.get("status") == "timeout" or row.get("source_timeout")
    ]
    parse_changed = [
        (key, row) for key, row in source_reports.items()
        if row.get("status") == "parse_changed"
    ]
    timeout_detail = ", ".join(
        f"{key}(budget={row.get('source_budget_seconds')}s used={row.get('source_used_seconds')}s)"
        for key, row in timeouts
    ) or "none"
    parser_detail = ", ".join(
        f"{key}({row.get('error_code') or 'parser_unrecognized'})"
        for key, row in parse_changed
    ) or "none"
    log.info("⏱ Source timeout results: count=%d [%s]", len(timeouts), timeout_detail)
    log.info("🧩 Parser parse_changed results: count=%d [%s]", len(parse_changed), parser_detail)


def _log_pre_pool_telemetry(jobs: list, rejections: Counter) -> None:
    """Log candidate age and every requested rejection reason before pooling."""
    freshness = Counter(_freshness_bucket(job, now=datetime.now()) for job in jobs)
    for reason in (
        "stale", "duplicate", "location", "non_cyber", "insufficient_evidence",
        "channel_mismatch", "score_below_threshold", "capacity", "source_priority", "already_sent",
    ):
        rejections.setdefault(reason, 0)
    log.info(
        "🕒 Pre-pool freshness: <24h=%d 24-48h=%d 48-72h=%d 72h+=%d unknown=%d",
        freshness["<24h"], freshness["24-48h"], freshness["48-72h"],
        freshness["72h+"], freshness["unknown"],
    )
    log.info(
        "🚫 Pool rejection reasons: %s",
        " ".join(f"{reason}={rejections[reason]}" for reason in (
            "stale", "duplicate", "location", "non_cyber", "insufficient_evidence",
            "channel_mismatch", "score_below_threshold", "capacity", "source_priority", "already_sent",
        )),
    )


def _recency_age_label(job, *, now: datetime) -> str:
    """Human-readable, non-mutating age evidence for the recency audit log."""
    posted = getattr(job, "posted_date", None)
    if not posted:
        return "posted=missing"
    try:
        if getattr(posted, "tzinfo", None) is not None:
            from datetime import timezone
            posted = posted.astimezone(timezone.utc).replace(tzinfo=None)
        age_hours = (now - posted).total_seconds() / 3600.0
        if age_hours < -0.1:
            return f"posted={posted.isoformat(timespec='minutes')} age=future({abs(age_hours):.1f}h)"
        return f"posted={posted.isoformat(timespec='minutes')} age={max(0.0, age_hours):.1f}h"
    except (TypeError, ValueError, OverflowError, AttributeError):
        return "posted=unparseable"


def _log_recency_audit(rejected_jobs: list) -> None:
    """Explain exactly why strict freshness removed delivery candidates.

    This is audit telemetry only: it never rescues, alters, or reclassifies a
    rejected job.  LinkedIn has its own source row, making bad/missing date
    extraction immediately visible in the normal run log.
    """
    if not rejected_jobs:
        return
    now = datetime.now()
    reasons = Counter(str(getattr(job, "filter_reason", "unknown")) for job in rejected_jobs)
    by_source: dict[str, list] = {}
    for job in rejected_jobs:
        source = (getattr(job, "source_key", "") or getattr(job, "source", "") or "unknown").strip()
        by_source.setdefault(source, []).append(job)

    reason_text = ", ".join(f"{reason}={count}" for reason, count in sorted(reasons.items()))
    log.info("🕒 Recency audit: rejected=%d reasons=[%s]", len(rejected_jobs), reason_text)

    sample_limit = max(1, config.RECENCY_AUDIT_SAMPLES_PER_BUCKET)
    for source, rows in sorted(by_source.items(), key=lambda item: (-len(item[1]), item[0])):
        source_reasons = Counter(str(getattr(job, "filter_reason", "unknown")) for job in rows)
        samples = []
        for job in rows[:sample_limit]:
            title = (getattr(job, "title", "") or "Unknown title").replace("\n", " ")[:58]
            company = (getattr(job, "company", "") or "Unknown company").replace("\n", " ")[:36]
            samples.append(
                f"{title} @ {company} ({_recency_age_label(job, now=now)}; "
                f"{getattr(job, 'filter_reason', 'unknown')})"
            )
        source_reason_text = ", ".join(
            f"{reason}={count}" for reason, count in sorted(source_reasons.items())
        )
        log.info(
            "🕒 Recency audit [%s]: rejected=%d reasons=[%s] samples=[%s]",
            source, len(rows), source_reason_text, " | ".join(samples),
        )


# ── v64 yield-based execution priority ─────────────────────────────────────

# Connectors that demonstrably supply unique, fresh cyber jobs — the observed
# run confirmed FABMISR, Vodafone Egypt, QNB Global, Greenhouse, Cloudflare,
# Wiz, Tenable, Bugcrowd, and HackerOne, and the dynamic boost rewards any
# connector that keeps delivering the same way.  Static registry priority is
# preserved; this only nudges proven suppliers higher inside the run plan.
_YIELD_BOOST_MIN_RECENT_JOBS = int(os.getenv("YIELD_BOOST_MIN_RECENT_JOBS", "3"))
_YIELD_BOOST_MEMORY_DAYS = int(os.getenv(
    "YIELD_BOOST_MEMORY_DAYS", str(getattr(database, "MEMORY_DAYS", 5))
))
_YIELD_PROVEN_SOURCE_KEYS = {
    "fabmisr", "vodafone_egypt", "qnb_global", "greenhouse_bigtech",
    "greenhouse_expanded", "greenhouse_cybersec", "cloudflare",
    "wiz", "tenable", "bugcrowd", "hackerone",
    "github_security", "telegram_channels", "forasna",
}


def _apply_yield_priority_boost(specs: list["SourceSpec"], db: JobsDB) -> None:
    """Boost registry priority for connectors with proven recent yield.

    Read from ``source_stats`` (the durable per-run yield ledger): any source
    whose total recent successful-job count is at least
    ``_YIELD_BOOST_MIN_RECENT_JOBS`` over the last ``_YIELD_BOOST_MEMORY_DAYS``
    days has its spec priority improved by up to 12 slots.  Order remains
    deterministic and the boost is capped so LinkedIn/HR lanes are untouched.
    """
    try:
        memory_days = max(1, _YIELD_BOOST_MEMORY_DAYS)
        cutoff = (datetime.now() - timedelta(days=memory_days)).isoformat()
        yields: dict[str, int] = {}
        with db._conn() as con:  # type: ignore[attr-defined]
            rows = con.execute(
                "SELECT source, SUM(count) AS total FROM source_stats "
                "WHERE run_at >= ? AND failed = 0 GROUP BY source",
                (cutoff,),
            ).fetchall()
        for row in rows:
            yields[row["source"]] = int(row["total"] or 0)

        boosted = 0
        for spec in specs:
            total = yields.get(spec.key) or yields.get(spec.name) or 0
            if total < max(1, _YIELD_BOOST_MIN_RECENT_JOBS):
                continue
            static = spec.priority
            proven = spec.key in _YIELD_PROVEN_SOURCE_KEYS
            # Proven suppliers jump to the front of the common-pool rotation;
            # other proven-yield sources get a moderate lift.
            target = 10 if proven else min(static, 20)
            if target < static:
                spec.priority = target
                boosted += 1
        if boosted:
            log.info("[v64] yield boost applied to %d proven source(s)", boosted)
    except Exception as exc:  # noqa: BLE001 — never let yield stats break the run
        log.warning("[v64] yield priority boost skipped: %s", exc)


# ── Source health gating ───────────────────────────────────────────────────

def _source_enabled_by_health(spec: SourceSpec, db: JobsDB) -> bool:
    if not config.ENABLE_SOURCE_PRIORITY_GATING:
        return True
    return db.can_run_source(spec.key, min_success=config.SOURCE_HEALTH_MIN_SUCCESS)


# ── Async fetch layer ──────────────────────────────────────────────────────

def _source_timeout_seconds(spec: SourceSpec) -> float | None:
    """Return an independent ceiling for one non-LinkedIn source.

    LinkedIn deliberately keeps its separate 895–925 second budget. Every
    other connector—including all fallback work—gets one short ceiling.
    """
    if spec.key == "linkedin_unified":
        return None
    value = getattr(spec, "source_timeout_seconds", None)
    if value is None:
        value = config.DIRECT_SOURCE_TIMEOUT_SECONDS
    return max(0.01, float(value))


def _record_source_timeout(
    spec: SourceSpec, stats: dict, db: JobsDB, reports: dict[str, dict], elapsed_ms: int,
) -> None:
    """Record a deadline outcome without assuming a test double is a JobsDB."""
    ceiling = _source_timeout_seconds(spec)
    stats[spec.key] = 0
    reports[spec.key] = {
        "status": "timeout", "health": "degraded", "transport": "none", "jobs": 0,
        "error_code": "source_timeout", "elapsed_ms": elapsed_ms,
        "source_budget_seconds": ceiling, "source_used_seconds": round(elapsed_ms / 1000, 3),
        "source_timeout": True, "fallback_used": False, "circuit_open": False,
        "cancelled_by_source_deadline": True, "cancelled_by_global_deadline": False,
    }
    if hasattr(db, "record_source_attempt"):
        db.record_source_attempt(
            source_key=spec.key, status="timeout", transport="none", jobs_count=0,
            error_code="source_timeout", elapsed_ms=elapsed_ms,
        )
    if hasattr(db, "update_source_health_state"):
        # v63/v64: ``source_timeout`` here is the orchestrator's deadline
        # firing, not the source's own transport failure — it must never
        # strand the source in quarantine.  Egyptian priority sources keep
        # their short dedicated attempt (45s ceiling) without auto-disable.
        is_egypt = spec.key in (config.EGYPT_PRIORITY_SOURCE_KEYS or set())
        db.update_source_health_state(
            spec.key, success=False, jobs_count=0, error_code="source_timeout",
            auto_disable_threshold=config.SOURCE_AUTO_DISABLE_THRESHOLD,
            quarantine_minutes=config.SOURCE_QUARANTINE_MINUTES,
            deadline_timeout=True,
            is_priority_source=is_egypt,
        )


async def _fetch_with_source_deadline(
    spec: SourceSpec, stats: dict, db: JobsDB, reports: dict[str, dict],
) -> list:
    """Isolate a source so a slow browser/fallback cannot starve peers."""
    t0 = time.monotonic()
    ceiling = _source_timeout_seconds(spec)
    if ceiling is None:
        return await _fetch_one(spec, stats, db, reports)
    try:
        return await asyncio.wait_for(_fetch_one(spec, stats, db, reports), timeout=ceiling)
    except asyncio.TimeoutError:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        _record_source_timeout(spec, stats, db, reports, elapsed_ms)
        log.warning(
            "    %s: 0 jobs [timeout/source_deadline budget=%.1fs used=%.1fs]",
            spec.name, ceiling, elapsed_ms / 1000,
        )
        return []


def _is_priority_source(spec: SourceSpec) -> bool:
    return spec.key in (config.EGYPT_PRIORITY_SOURCE_KEYS or set())


async def _fetch_one(spec: SourceSpec, stats: dict, db: JobsDB, reports: dict[str, dict]) -> list:
    name = spec.name
    is_egypt_priority = _is_priority_source(spec)
    fetcher = spec.fetcher
    t0 = time.time()
    try:
        if inspect.iscoroutinefunction(fetcher):
            raw_result = await fetcher()
        else:
            # ``wait_for`` can cancel the awaiter but cannot terminate a
            # synchronous thread.  Give the worker its own cooperative source
            # deadline so shared HTTP calls and source pagination stop too.
            ceiling = _source_timeout_seconds(spec)
            def _run_sync_fetcher():
                if ceiling is None:
                    return fetcher()
                with source_deadline(ceiling):
                    return fetcher()
            raw_result = await asyncio.to_thread(_run_sync_fetcher)
        result = raw_result if isinstance(raw_result, SourceResult) else SourceResult(jobs=list(raw_result or []))
        jobs = result.jobs
        elapsed = int((time.time() - t0) * 1000)
        stats[spec.key] = len(jobs)
        # An optional connector without its user-supplied API credential is
        # not a failed endpoint and must never be quarantined.  It is visible
        # as ``not_configured`` so the run log explains the zero precisely.
        source_reachable = result.status in {
            "success", "empty", "no_public_client_feed", "not_configured",
            # Parser drift is operationally degraded, but the endpoint did
            # answer. Keep observing it instead of immediately quarantining
            # a public source that may recover after a short rollout.
            "parse_changed",
        }
        # v71: the ladder's honest-empty verdict (the reader ran the full
        # attempt chain and read the page with no listings) is a healthy
        # zero — the detection lives here so the health verdict and the
        # health-state update both honor it.
        honest_empty = bool(
            result.status == "empty" and (result.error_code or "").startswith("EMPTY_REAL"),
        )
        if result.status == "not_configured":
            health = "not_configured"
        elif result.status == "parse_changed":
            health = "degraded"
        elif source_reachable and result.transport in {"direct", "none"}:
            health = "healthy"
        else:
            # v71: an honest empty read the page end-to-end and found
            # nothing — that is a healthy verdict, not degradation.
            if honest_empty:
                health = "healthy"
            elif source_reachable:
                health = "degraded"
            else:
                health = "blocked"
        reports[spec.key] = {
            "status": result.status, "health": health, "transport": result.transport,
            "jobs": len(jobs), "error_code": result.error_code, "elapsed_ms": elapsed,
            "source_budget_seconds": _source_timeout_seconds(spec),
            "source_used_seconds": round(elapsed / 1000, 3),
            "source_timeout": False,
            "fallback_used": result.transport in {"jina", "playwright"},
            "circuit_open": "circuit_open" in (result.error_code or ""),
            "cancelled_by_source_deadline": False,
            "cancelled_by_global_deadline": False,
        }
        empty_reason = result.error_code or result.status
        db.record_source_attempt(
            source_key=spec.key, status=result.status, transport=result.transport,
            jobs_count=len(jobs), error_code=result.error_code, elapsed_ms=elapsed,
        )
        db.update_source_health_state(
            spec.key,
            success=source_reachable,
            jobs_count=len(jobs),
            error_code="" if (source_reachable or honest_empty) else empty_reason,
            auto_disable_threshold=config.SOURCE_AUTO_DISABLE_THRESHOLD,
            quarantine_minutes=config.SOURCE_QUARANTINE_MINUTES,
            # v64: priority sources with real failures enter the recovery
            # rotation instead of degrading silently forever.
            # v71: an honest empty is healthy — never a failure streak.
            is_priority_source=is_egypt_priority,
            honest_empty=honest_empty,
        )
        reason = f" reason={result.error_code}" if result.error_code else ""
        log.info(
            "    %s: %d jobs [%s/%s%s] (%dms)",
            name, len(jobs), result.status, result.transport, reason, elapsed,
        )
        return jobs
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        log.error(f"    {name} failed ({elapsed}ms): {e}")
        stats[spec.key] = "FAILED"
        reports[spec.key] = {
            "status": "failed", "health": "blocked", "transport": "direct",
            "jobs": 0, "error_code": type(e).__name__, "elapsed_ms": elapsed,
            "source_budget_seconds": _source_timeout_seconds(spec),
            "source_used_seconds": round(elapsed / 1000, 3),
            "source_timeout": False, "fallback_used": False, "circuit_open": False,
            "cancelled_by_source_deadline": False, "cancelled_by_global_deadline": False,
        }
        db.record_source_attempt(
            source_key=spec.key, status="failed", transport="direct",
            jobs_count=0, error_code=type(e).__name__, elapsed_ms=elapsed,
        )
        db.update_source_health_state(
            spec.key,
            success=False,
            jobs_count=0,
            error_code=type(e).__name__,
            auto_disable_threshold=config.SOURCE_AUTO_DISABLE_THRESHOLD,
            quarantine_minutes=config.SOURCE_QUARANTINE_MINUTES,
            # v64: same recovery-rotation treatment for unexpected crashes.
            is_priority_source=is_egypt_priority,
        )
        return []


async def fetch_all_async(stats: dict, db: JobsDB, reports: dict[str, dict]) -> list:
    specs = list(get_source_specs())
    if not specs:
        return []
    log.info(f"✅ Priority fetch plan loaded: {len(specs)} source(s)")

    # v64: yield-based execution priority.  The registry's static priority is
    # now boosted for connectors that proved their yield recently (fresh +
    # unique cyber jobs across the last MEMORY_DAYS days).  The observed run
    # confirmed the proven suppliers — FABMISR, Vodafone Egypt, QNB Global,
    # Greenhouse, Cloudflare, Wiz, Tenable, Bugcrowd, HackerOne — and the
    # dynamic boost rewards exactly that behavior: the same sources, in the
    # same order, only when they keep delivering.
    _apply_yield_priority_boost(specs, db)

    # v64: failing priority sources enter the recovery/fallback rotation —
    # they stay registered and are rechecked on a sparse schedule instead of
    # consuming the shared budget every run.  Bump counters once per run
    # before computing who is due.
    if hasattr(db, "bump_recovery_counters"):
        db.bump_recovery_counters()
    recovery_due: set[str] = set()
    if hasattr(db, "recovery_due_sources"):
        recovery_due = set(db.recovery_due_sources())
    if recovery_due:
        log.info(
            "Recovery rotation due this run (%d): %s",
            len(recovery_due), ", ".join(sorted(recovery_due)),
        )

    normally_enabled = [s for s in specs if _source_enabled_by_health(s, db)]
    quarantined = [s for s in specs if s not in normally_enabled]
    probe_limit = max(0, config.QUARANTINED_SOURCE_PROBE_LIMIT)
    recovery_probes = sorted(quarantined, key=lambda spec: spec.priority)[:probe_limit]

    # v66: recovery scheduling is separated from health and yield. A source
    # sitting in the sparse recovery rotation that actually produced jobs
    # recently is a proven supplier — it graduates back into the main fetch
    # plan immediately, even if it was parked earlier for a transient
    # incident, and a source is never parked simply because it was not
    # executed in the current run.
    yield_pulled = 0
    if hasattr(db, "recent_source_yield") and hasattr(db, "graduate_from_recovery_rotation"):
        # v66: check every source currently parked in the rotation (due or
        # not) — the parked list in the log was the user-visible symptom.
        # A proven supplier must not appear there at all.
        parked_keys: set[str] = set()
        try:
            parked_keys = {r["source_key"] for r in db.get_recovery_sources() or []}
        except Exception:
            pass
        for spec in list(normally_enabled):
            if spec.key not in parked_keys:
                continue
            try:
                recent = db.recent_source_yield(spec.key)
            except Exception:
                continue
            if recent >= max(1, config.RECOVERY_RECENT_YIELD_MIN_JOBS):
                try:
                    db.graduate_from_recovery_rotation(spec.key)
                except Exception:
                    continue
                recovery_due.discard(spec.key)
                yield_pulled += 1
    if yield_pulled:
        log.info(
            "[v66] %d proven-yield source(s) pulled out of the recovery "
            "rotation back into the main fetch plan",
            yield_pulled,
        )

    # v64: recovery-rotation members (not quarantined — parked) run only when due.
    in_rotation = [s for s in normally_enabled if s.key in recovery_due]
    parked = [s for s in normally_enabled if s.key not in recovery_due]
    # v64: sort the run plan by priority so yield-proven and priority sources
    # start earlier — the shared phase budget and per-source cooperative
    # deadline both favor sources that begin first, and the proven suppliers
    # confirmed by the observed run (FABMISR, Vodafone, QNB Global,
    # Greenhouse, Cloudflare, Wiz, Tenable, Bugcrowd, HackerOne) must not
    # arrive late after the slow ones have eaten the budget.
    run_specs = sorted(parked + recovery_probes + in_rotation, key=lambda s: (s.priority, s.name))
    skipped = [s.name for s in quarantined if s not in recovery_probes]
    if skipped:
        log.warning(f"Quarantined sources ({len(skipped)}): {', '.join(skipped[:8])}")
    if recovery_probes:
        log.info(
            "Recovery probes for %d quarantined source(s): %s",
            len(recovery_probes), ", ".join(source.name for source in recovery_probes),
        )
    if parked:
        log.info(
            "Parked in recovery rotation this run (%d): %s",
            len(parked), ", ".join(s.name for s in parked[:10]),
        )

    all_jobs = []

    # LinkedIn has its own 15-minute ceiling while all other connectors share
    # a short, overlapping window. One slow source must never delay either
    # the LinkedIn report or the filtering/sending stages.
    start_phase("linkedin", config.LINKEDIN_TOTAL_BUDGET_SECONDS)
    tasks = [
        asyncio.create_task(_fetch_with_source_deadline(spec, stats, db, reports))
        for spec in run_specs
    ]
    task_specs = {task: spec for spec, task in zip(run_specs, tasks)}
    linkedin_tasks = [task for spec, task in zip(run_specs, tasks) if spec.key == "linkedin_unified"]
    other_tasks = [task for task in tasks if task not in linkedin_tasks]

    async def _collect(
        group: list[asyncio.Task], timeout: float, budget_name: str,
    ) -> dict[asyncio.Task, list]:
        if not group:
            return {}
        done, pending = await asyncio.wait(group, timeout=max(0.0, timeout))
        values: dict[asyncio.Task, list] = {}
        for task in done:
            if task.cancelled():
                values[task] = []
                continue
            try:
                values[task] = task.result()
            except Exception as exc:
                spec = task_specs[task]
                log.error("    %s collector failure: %s", spec.name, exc)
                values[task] = []
        for task in pending:
            task.cancel()
        if pending:
            names = [task_specs[task].name for task in pending]
            log.warning(
                "⏱ %s budget reached; cancelled %d pending source(s): %s",
                budget_name,
                len(names),
                ", ".join(names[:8]),
            )
            await asyncio.gather(*pending, return_exceptions=True)
            for task in pending:
                spec = task_specs[task]
                stats[spec.key] = 0
                reports[spec.key] = {
                    "status": "skipped_budget", "health": "skipped_budget", "transport": "none",
                    "jobs": 0, "error_code": f"{budget_name}_budget", "elapsed_ms": 0,
                    "source_budget_seconds": _source_timeout_seconds(spec), "source_used_seconds": 0,
                    "source_timeout": False, "fallback_used": False, "circuit_open": False,
                    "cancelled_by_source_deadline": False, "cancelled_by_global_deadline": True,
                }
        return values

    result_sets = await asyncio.gather(
        _collect(linkedin_tasks, budget_remaining("linkedin"), "linkedin"),
        _collect(other_tasks, budget_remaining("other_sources"), "other_sources"),
    )
    results_by_task = result_sets[0] | result_sets[1]
    results = []
    for spec, task in zip(run_specs, tasks):
        if task in results_by_task:
            results.append(results_by_task[task])
            continue
        stats[spec.key] = 0
        budget_name = "linkedin" if spec.key == "linkedin_unified" else "other_sources"
        reports[spec.key] = {
            "status": "skipped_budget", "health": "skipped_budget", "transport": "none",
            "jobs": 0, "error_code": f"{budget_name}_budget", "elapsed_ms": 0,
            "source_budget_seconds": _source_timeout_seconds(spec), "source_used_seconds": 0,
            "source_timeout": False, "fallback_used": False, "circuit_open": False,
            "cancelled_by_source_deadline": False, "cancelled_by_global_deadline": True,
        }
        results.append([])

    for spec, batch in zip(run_specs, results):
        # Stamp source metadata for downstream intelligence pipeline.
        for job in batch:
            if not getattr(job, "source_key", ""):
                job.source_key = spec.key
            # Always normalize to the shared source order. Individual
            # connectors may carry old priority values, but those values must
            # not override the user-facing LinkedIn-first policy.
            job.origin_priority = config.source_priority(
                getattr(job, "source_key", "") or getattr(job, "source", ""),
                default=spec.priority,
            )
            if not getattr(job, "content_type", ""):
                job.content_type = "job_listing"
            if not getattr(job, "source", ""):
                job.source = spec.key
        all_jobs.extend(batch)
    return all_jobs


def run_fetch_all(stats: dict, db: JobsDB, reports: dict[str, dict]) -> list:
    """Run fetch tasks without letting executor cleanup extend the run budget.

    Cancelling ``asyncio.to_thread`` cancels its awaiter, not a synchronous
    connector already inside a network call. ``asyncio.run`` then waits for
    the default executor during shutdown, which previously hid a 14-minute
    pause after LinkedIn had already completed. A per-run executor is shut
    down non-blockingly: late connector calls cannot delay filtering, metrics,
    or Telegram. The HTTP layer also observes the source-phase deadline.
    """
    executor = ThreadPoolExecutor(
        max_workers=max(1, config.SOURCE_FETCH_MAX_WORKERS),
        thread_name_prefix="source-fetch",
    )
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.set_default_executor(executor)
        return loop.run_until_complete(fetch_all_async(stats, db, reports))
    finally:
        # Deliberately do not call loop.shutdown_default_executor(): it waits
        # for synchronous source functions that have already exceeded budget.
        executor.shutdown(wait=False, cancel_futures=True)
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            loop.close()
            asyncio.set_event_loop(None)


# ── Health report ──────────────────────────────────────────────────────────

def _send_health_report(
    db: JobsDB,
    source_stats: dict,
    source_reports: dict[str, dict] | None = None,
    http_metrics: dict[str, int] | None = None,
    linkedin_telemetry: dict | None = None,
):
    chat_id = config.HEALTH_REPORT_CHAT_ID
    token = config.TELEGRAM_BOT_TOKEN
    if not token or not chat_id:
        return

    health = db.get_source_health(days=7)
    summary = db.get_stats_summary()

    lines = ["🔍 *Source Health Report*\n"]

    if source_reports:
        counts: dict[str, int] = {}
        for row in source_reports.values():
            counts[row.get("health", "blocked")] = counts.get(row.get("health", "blocked"), 0) + 1
        lines.append("*This run:* " + " | ".join([
            f"attempted={len(source_reports)}", f"healthy={counts.get('healthy', 0)}",
            f"degraded={counts.get('degraded', 0)}", f"blocked={counts.get('blocked', 0)}",
            f"not-configured={counts.get('not_configured', 0)}",
            f"skipped={counts.get('skipped_budget', 0)}",
        ]))

    if http_metrics:
        jina_fallbacks = sum(
            1 for row in (source_reports or {}).values() if row.get("transport") == "jina"
        )
        lines.extend([
            "\n*Proxy / HTTP:*",
            "requests={requests} | 402={p402} | 407={p407} | timeouts={timeouts}".format(
                requests=http_metrics.get("requests", 0), p402=http_metrics.get("402", 0),
                p407=http_metrics.get("407", 0), timeouts=http_metrics.get("timeouts", 0),
            ),
            "direct bypass={bypass} | Jina fallback={jina} | circuit-open={circuits}".format(
                bypass=http_metrics.get("direct_bypass", 0), jina=jina_fallbacks,
                circuits=http_metrics.get("circuit_open", 0) + http_metrics.get("endpoint_circuit_open", 0),
            ),
        ])

    if linkedin_telemetry:
        lines.extend([
            "\n*LinkedIn Jobs:*",
            "budget={budget}s | used={used}s | queries={completed}/{planned} | pages={pages} | details={details} | partial={partial} | stop={stop} | jobs={jobs} | pending_tasks_before={pending_before} | cancelled_tasks={cancelled} | pending_tasks_after={pending_after}".format(
                budget=linkedin_telemetry.get("jobs_budget_seconds", 0),
                used=linkedin_telemetry.get("jobs_used_seconds", 0),
                completed=linkedin_telemetry.get("queries_completed", linkedin_telemetry.get("queries", 0)),
                planned=linkedin_telemetry.get("queries_planned", linkedin_telemetry.get("queries", 0)),
                pages=linkedin_telemetry.get("pages", 0), details=linkedin_telemetry.get("details", 0),
                partial=linkedin_telemetry.get("partial", False),
                stop=linkedin_telemetry.get("stop_reason", "unknown"),
                jobs=linkedin_telemetry.get("jobs", 0),
                pending_before=linkedin_telemetry.get("pending_tasks_before", 0),
                cancelled=linkedin_telemetry.get("cancelled_tasks", 0),
                pending_after=linkedin_telemetry.get("pending_tasks_after", 0),
            ),
        ])

    failed_sources = [s for s, v in source_stats.items() if v == "FAILED"]
    if failed_sources:
        lines.append("❌ *Failed this run:*")
        for s in failed_sources:
            lines.append(f"  • {s}")
        lines.append("")

    lines.append("📊 *7-day stats:*")
    for row in health[:15]:
        icon = "✅" if row["failures"] == 0 else ("⚠️" if row["failures"] < row["runs"] else "❌")
        avg = f"{row['avg_jobs']:.0f}" if row["avg_jobs"] else "0"
        lines.append(f"  {icon} {row['source']}: {avg} avg jobs, {row['failures']} fails")

    lines.append(f"\n💾 DB: {summary['total_seen']} total seen | {summary['total_sent']} sent")

    text = "\n".join(lines)
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        log.info("✅ Health report sent to Telegram.")
    except Exception as e:
        log.warning(f"Health report failed: {e}")


# ── Main ───────────────────────────────────────────────────────────────────

def _migrate_seen_file_to_db(db: JobsDB, seen_file: str) -> None:
    """One-time migration from legacy seen_jobs.json to SQLite."""
    if not seen_file or not os.path.exists(seen_file):
        return
    try:
        with open(seen_file, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception as exc:
        log.warning("Legacy seen migration skipped: %s", exc)
        return

    if isinstance(raw, dict):
        keys = list(raw.keys())
    elif isinstance(raw, list):
        keys = [str(item) for item in raw]
    else:
        keys = []

    if keys:
        log.info("Migrating %d seen IDs from JSON file to SQLite...", len(keys))
        db.bulk_mark_seen(keys)
    try:
        os.replace(seen_file, seen_file + ".migrated")
        log.info("Migration complete - %s renamed to %s", seen_file, seen_file + ".migrated")
    except Exception as exc:
        log.warning("Legacy seen migration could not rename file: %s", exc)


def main():
    start_time = time.time()
    log.info("=" * 60)
    log.info("🚀 Bot Started at " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 60)
    config.run_startup_validations()
    start_run(config.TOTAL_RUN_BUDGET_SECONDS)
    start_phase("other_sources", config.OTHER_SOURCES_BUDGET_SECONDS)
    reset_http_run_state()

    stats = {"fetched": 0, "filtered": 0, "new": 0, "sent": 0, "sources": {}}
    source_reports: dict[str, dict] = {}
    db = get_db()
    run_id = make_run_id()
    reviewed_now = poll_review_updates(db)
    if reviewed_now:
        log.info("🧑‍⚖️ Applied %d trusted Telegram review label(s).", reviewed_now)

    # 1. Load seen IDs
    _migrate_seen_file_to_db(db, config.SEEN_JOBS_FILE)
    seen = load_seen_ids(config.SEEN_JOBS_FILE)

    # Seed mode: if DB is empty, mark seen without sending
    try:
        _db_check = get_db()
        _db_summary = _db_check.get_stats_summary()
        _db_has_history = _db_summary.get("total_seen", 0) > 0
    except Exception:
        _db_summary = {"total_seen": len(seen)}
        _db_has_history = len(seen) > 0

    is_seed = not config.DRY_RUN and (
        os.getenv(config.SEED_MODE_ENV, "").lower() in ("1", "true", "yes")
        or (len(seen) == 0 and not _db_has_history)
    )
    if config.DRY_RUN:
        log.info("🧪 DRY_RUN — full pool/routing preview; no Telegram or persistence.")
    elif is_seed:
        log.info("🌱 SEED MODE — no messages sent.")
    else:
        log.info(f"✅ NORMAL MODE — DB has {_db_summary.get('total_seen', '?')} seen jobs.")

    if config.TELEGRAM_CANARY and not config.DRY_RUN:
        send_test_canary()

    # 2. Fetch ALL sources (async, parallel)
    all_jobs = run_fetch_all(stats["sources"], db, source_reports)
    stats["fetched"] = len(all_jobs)
    log.info(f"📦 Total fetched: {stats['fetched']} jobs")
    _log_source_run_telemetry(source_reports)
    linkedin_telemetry = get_linkedin_telemetry()
    if linkedin_telemetry:
        log.info(
            "🔗 LinkedIn Jobs: budget=%ss used=%ss queries=%s/%s pages=%s details=%s partial=%s stop=%s jobs=%s unique_jobs=%s dup_jobs=%s pending_tasks_before=%s cancelled_tasks=%s pending_tasks_after=%s",
            linkedin_telemetry.get("jobs_budget_seconds"), linkedin_telemetry.get("jobs_used_seconds"),
            linkedin_telemetry.get("queries_completed", linkedin_telemetry.get("queries")),
            linkedin_telemetry.get("queries_planned", linkedin_telemetry.get("queries")),
            linkedin_telemetry.get("pages"), linkedin_telemetry.get("details"),
            linkedin_telemetry.get("partial"), linkedin_telemetry.get("stop_reason"),
            linkedin_telemetry.get("jobs"),
            linkedin_telemetry.get("unique_jobs", linkedin_telemetry.get("jobs")),
            linkedin_telemetry.get("duplicate_jobs", 0),
            linkedin_telemetry.get("pending_tasks_before", 0),
            linkedin_telemetry.get("cancelled_tasks", 0),
            linkedin_telemetry.get("pending_tasks_after", 0),
        )
        # v61: Log query type breakdown
        by_type = linkedin_telemetry.get("jobs_by_query_type", {})
        by_loc = linkedin_telemetry.get("jobs_by_location", {})
        by_src = linkedin_telemetry.get("jobs_by_source", {})
        uniq_q = linkedin_telemetry.get("unique_queries", 0)
        dup_q = linkedin_telemetry.get("duplicate_queries", 0)
        if by_type or by_loc or uniq_q:
            log.info(
                "📊 LinkedIn query diversity: unique_queries=%s dup_queries=%s by_type=%s by_location=%s by_source=%s",
                uniq_q, dup_q, by_type, by_loc, by_src,
            )
        log.info(
            "📢 LinkedIn HR: budget=%ss used=%ss discovered=%s accepted=%s rejected_evidence=%s "
            "queries=%s/%s urls=%s scraped=%s backend_hits=%s backend_empty=%s rejections=%s "
            "by_method=%s company_yield=%s recruiter_yield=%s",
            linkedin_telemetry.get("hr_budget_seconds"), linkedin_telemetry.get("hr_used_seconds"),
            linkedin_telemetry.get("hr_discovered"), linkedin_telemetry.get("hr_accepted"),
            linkedin_telemetry.get("hr_rejected_evidence"),
            linkedin_telemetry.get("hr_queries_attempted", 0),
            linkedin_telemetry.get("hr_queries_planned", 0),
            linkedin_telemetry.get("hr_urls_discovered", 0),
            linkedin_telemetry.get("hr_posts_scrape_attempted", 0),
            linkedin_telemetry.get("hr_search_backend_hits", {}),
            linkedin_telemetry.get("hr_search_backend_empty", {}),
            linkedin_telemetry.get("hr_rejections", {}),
            linkedin_telemetry.get("hr_accepted_by_method", {}),
            linkedin_telemetry.get("hr_company_yield", {}),
            linkedin_telemetry.get("hr_recruiter_yield", {}),
        )

    # Save source stats & proxy pool health to DB
    proxy_status = get_proxy_status()
    db.save_source_stats(stats["sources"])
    # v74: log Egypt/Arab funnels once per run (after send so sent counts).
    # The funnel object is created inside the filtering block (below); log it
    # there instead of here so it can never reference an unbound variable
    # when the run skips or errors out of the filtering phase.
    db.save_proxy_stats(proxy_status)
    if proxy_status.get("total", 0) > 0:
        log.info(
            "🌐 Proxy pool: %d/%d available | banned: %d | avg score: %.0f",
            proxy_status["available"], proxy_status["total"],
            proxy_status["banned"], proxy_status.get("avg_score", 0),
        )

    try:
        start_phase("filtering", config.FILTERING_BUDGET_SECONDS)
        # 3. Hard cyber gate, then physical/remote location gate. Dedup never
        # sees a NON_CYBER row or an out-of-scope physical location.
        # v74: Egypt/Arab pipeline funnel — tracks each job (by dedup key)
        # through every hard stage and records a single drop reason when it
        # falls out, so the Egypt delivery gap is always attributable.
        _egypt_funnel = egypt_funnel.EgyptPipelineFunnel()
        # v75: discovered = real jobs whose delivery geo is Egypt/Arab.
        for _funnel_geo, _funnel_set in egypt_funnel.stage_keys(
            egypt_funnel.geo_keys(all_jobs)
        ).items():
            _egypt_funnel.funnel_for(_funnel_geo).set_stage("discovered", len(_funnel_set))
        filtering_started = time.monotonic()
        filtered, rejected = classify_jobs(all_jobs)
        filtering_elapsed = time.monotonic() - filtering_started
        stats["filtered"] = len(filtered)
        # v76: canonical record — category evidence + source-backed skills are
        # attached to EVERY job immediately after classification (before the
        # location/recency/dedup gates) so downstream formatting and routing
        # never re-extract or invent values.
        _enrich_canonical_record(all_jobs)
        classified = [job for job in all_jobs if job.cyber_verdict in {
            CyberVerdict.CONFIRMED.value, CyberVerdict.LIKELY.value,
        }]
        confirmed = [job for job in classified if job.cyber_verdict == CyberVerdict.CONFIRMED.value]
        likely = [job for job in classified if job.cyber_verdict == CyberVerdict.LIKELY.value]
        non_cyber = [job for job in all_jobs if job.cyber_verdict == CyberVerdict.NON_CYBER.value]
        location_rejected = [job for job in rejected if getattr(job, "filter_reason", "") == "reject_geo_filter"]
        recency_rejected = [
            job for job in rejected
            if str(getattr(job, "filter_reason", "")).startswith("reject_stale_")
            or getattr(job, "filter_reason", "") == "reject_unknown_age_strict_source"
        ]
        cyber_candidates = len(confirmed) + len(likely)
        stats["cyber_candidates"] = cyber_candidates
        location_accepted = cyber_candidates - len(location_rejected)
        recency_accepted = location_accepted - len(recency_rejected)
        location_input_breakdown = Counter(classify_delivery_geo(job) for job in classified)
        location_accepted_breakdown = Counter(classify_delivery_geo(job) for job in filtered)
        # v75: record REAL stage counts from the pipeline-native job lists,
        # so the funnel can never show zeros while jobs genuinely passed.
        _funnel_classified = egypt_funnel.geo_keys(classified)
        for _funnel_geo, _funnel_set in egypt_funnel.stage_keys(_funnel_classified).items():
            _egypt_funnel.funnel_for(_funnel_geo).set_stage("cyber_candidate", len(_funnel_set))
        _funnel_location_ok = egypt_funnel.geo_keys(filtered)
        for _funnel_geo, _funnel_set in egypt_funnel.stage_keys(_funnel_location_ok).items():
            _egypt_funnel.funnel_for(_funnel_geo).set_stage("location_ok", len(_funnel_set))
        from intelligence.pool_builder import is_stale as _is_stale
        _funnel_fresh = egypt_funnel.geo_keys(
            [job for job in filtered if not _is_stale(job)]
        )
        for _funnel_geo, _funnel_set in egypt_funnel.stage_keys(_funnel_fresh).items():
            _egypt_funnel.funnel_for(_funnel_geo).set_stage("fresh", len(_funnel_set))
        log.info(
            "🔍 Cyber verdict stage: confirmed=%d likely=%d non_cyber=%d candidates=%d",
            len(confirmed), len(likely), len(non_cyber), cyber_candidates,
        )
        log.info(
            "📍 Location gate: input=%d [egypt=%d arab=%d remote=%d global=%d] "
            "accepted=%d [egypt=%d arab=%d remote=%d] rejected=%d "
            "(physical: Egypt/Arab only; remote: worldwide)",
            cyber_candidates,
            location_input_breakdown["egypt"], location_input_breakdown["arab"],
            location_input_breakdown["remote"], location_input_breakdown["global"],
            location_accepted,
            location_accepted_breakdown["egypt"], location_accepted_breakdown["arab"],
            location_accepted_breakdown["remote"], len(location_rejected),
        )
        log.info(
            "🕒 Recency gate: input=%d accepted=%d rejected=%d",
            location_accepted, recency_accepted, len(recency_rejected),
        )
        _log_recency_audit(recency_rejected)
        log.info(
            "⏱ Filtering: %.1fs (advisory phase budget=%ss)",
            filtering_elapsed, config.FILTERING_BUDGET_SECONDS,
        )
        if not config.DRY_RUN:
            review_queued = queue_review_samples(db, confirmed, likely, rejected, run_id)
            if review_queued:
                log.info("🧪 Queued %d blind Telegram review sample(s).", review_queued)
        metrics = record_metrics(db, run_id)
        log.info(
            "📐 Filter quality: reviewed=%s/%s coverage=%.1f%% TP=%.1f FP=%.1f TN=%.1f FN=%.1f precision=%s recall=%s",
            metrics["reviewed"], metrics["samples"], metrics["coverage"] * 100,
            metrics["tp"], metrics["fp"], metrics["tn"], metrics["fn"],
            "N/A" if metrics["precision"] is None else f"{metrics['precision']:.3f}",
            "N/A" if metrics["recall"] is None else f"{metrics['recall']:.3f}",
        )

        # Passively record accept/reject decisions as *unverified* training
        # samples (label_source="automatic"). This only feeds a dataset for
        # later human review — ml_filter.maybe_retrain_from_db() ignores
        # anything that isn't label_source="human_verified", so this alone
        # can never bias the live model. Skipped during DRY_RUN to keep dry
        # runs fully non-mutating.
        if config.ENABLE_TRAINING_DATA_COLLECTION and not config.DRY_RUN:
            filtered_keys = {j.dedup_key for j in filtered}
            train_seen: set[str] = set()
            for job in all_jobs:
                key = job.dedup_key
                if not key or key in train_seen:
                    continue
                train_seen.add(key)
                db.record_training_sample(
                    dedup_key=key,
                    title=job.title,
                    company=job.company,
                    location=job.location,
                    source=getattr(job, "source_key", "") or job.source,
                    content_type=getattr(job, "content_type", "job_listing"),
                    description_short=(job.description or "")[:500],
                    accepted=key in filtered_keys,
                    reason="filter_pass" if key in filtered_keys else "filter_reject",
                )
                if len(train_seen) >= 1600:
                    break

        # 4. Exact-identity dedup (canonical URL/provider job ID only)
        before_dedup = len(filtered)
        dedup_telemetry: Counter[str] = Counter()
        new_jobs = deduplicate(filtered, seen, telemetry=dedup_telemetry)

        # Hard stale gate (pool_builder handles scoring-based staleness)
        from intelligence.pool_builder import is_stale
        stale_count = sum(1 for j in new_jobs if is_stale(j))
        if stale_count:
            new_jobs = [j for j in new_jobs if not is_stale(j)]
            log.info(f"🗑 Dropped {stale_count} stale jobs (>{config.MAX_JOB_AGE_DAYS}d).")
        # v74: new-job stage — exact-identity dedup drop, no double count
        # (a job was either new, duplicate, or already dropped earlier).
        _funnel_new = egypt_funnel.geo_keys(new_jobs)
        for _funnel_geo, _funnel_set in egypt_funnel.stage_keys(_funnel_new).items():
            _egypt_funnel.funnel_for(_funnel_geo).set_stage("new_job", len(_funnel_set))

        stats["new"] = len(new_jobs)
        log.info(f"✨ New jobs: {stats['new']}")
        dedup_dropped = max(0, before_dedup - len(new_jobs) - stale_count)
        log.info(
            f"🔁 Dedup drop rate: {dedup_dropped}/{before_dedup} "
            f"({(dedup_dropped / max(1, before_dedup)) * 100:.1f}%)"
        )

        seen = smart_expire(seen, len(new_jobs))
        if len(new_jobs) == 0:
            new_jobs = deduplicate(filtered, seen)
            stats["new"] = len(new_jobs)
            if new_jobs:
                log.info(f"♻️ After smart_expire: {len(new_jobs)} new jobs recovered.")

        if is_seed:
            log.info(f"🌱 Seed: marking {len(new_jobs)} jobs seen")
            seen = mark_as_seen(new_jobs, seen)
        else:
            # 5. Build final pool (fresh-first, ratio-enforced, threshold-gated)
            #    Delegated to intelligence.pool_builder — tested independently.
            # Classifier-stage reasons are assigned once, in precedence order,
            # so the rejection totals are auditable and never double-count a
            # single input row as both NON_CYBER and insufficient evidence.
            classifier_rejections: Counter[str] = Counter()
            for job in rejected:
                reason = str(getattr(job, "filter_reason", ""))
                if reason.startswith("reject_stale_") or reason == "reject_unknown_age_strict_source":
                    classifier_rejections["stale"] += 1
                elif reason == "reject_geo_filter":
                    classifier_rejections["location"] += 1
                elif any(token in reason for token in (
                    "missing_", "low_confidence", "no_strong_cyber", "ml_guard",
                )):
                    classifier_rejections["insufficient_evidence"] += 1
                elif getattr(job, "cyber_verdict", "") == CyberVerdict.NON_CYBER.value:
                    classifier_rejections["non_cyber"] += 1
                else:
                    # Structural/content-type and hard-intent rejections are
                    # evidence failures for publication purposes.
                    classifier_rejections["insufficient_evidence"] += 1
            rejected_reasons = Counter({
                "stale": classifier_rejections["stale"] + stale_count,
                "duplicate": dedup_telemetry["duplicate"],
                "location": classifier_rejections["location"],
                "non_cyber": classifier_rejections["non_cyber"],
                "already_sent": dedup_telemetry["already_sent"],
                "insufficient_evidence": classifier_rejections["insufficient_evidence"],
                "channel_mismatch": 0,
                "score_below_threshold": 0,
                "capacity": 0,
                "source_priority": 0,
            })
            pool_telemetry: dict = {"rejections": rejected_reasons}
            # This is deliberately emitted before selection.  It gives every
            # run an auditable candidate-age snapshot without changing any
            # location, cyber, dedup, or source-priority rule.
            _log_pre_pool_telemetry(new_jobs, rejected_reasons)
            final_pool = _build_final_pool(new_jobs, telemetry=pool_telemetry)
            # v74: pool stage — dropped by fresh-first scoring/threshold/capacity.
            _funnel_pool = egypt_funnel.geo_keys(final_pool)
            for _funnel_geo, _funnel_set in egypt_funnel.stage_keys(_funnel_pool).items():
                _egypt_funnel.funnel_for(_funnel_geo).set_stage("in_pool", len(_funnel_set))
            log.info(
                "🚫 Pool selection rejection reasons: %s",
                " ".join(
                    f"{reason}={rejected_reasons[reason]}" for reason in (
                        "stale", "duplicate", "location", "non_cyber", "insufficient_evidence",
                        "channel_mismatch", "score_below_threshold", "capacity", "source_priority", "already_sent",
                    )
                ),
            )

            # Pool composition summary
            eg_count  = sum(1 for j in final_pool if classify_delivery_geo(j) == "egypt")
            arab_count = sum(1 for j in final_pool if classify_delivery_geo(j) == "arab")
            rem_count  = sum(1 for j in final_pool if classify_delivery_geo(j) == "remote")
            entry_count = sum(1 for j in final_pool if is_entry_level(j))
            linkedin_count = sum(1 for j in final_pool if is_linkedin_job(j))

            log.info(
                f"📊 Pool: {len(final_pool)} jobs"
                f" | EG:{eg_count} Arab:{arab_count}"
                f" Remote:{rem_count} Entry:{entry_count} LinkedIn:{linkedin_count}"
            )

            # 6. Send to Telegram, or run the same router in a non-mutating
            # preview so DRY_RUN validates every final delivery safeguard.
            if final_pool:
                # Telegram is a bounded protected phase: a completed pool
                # must still get its configured delivery window even when
                # upstream CPU-bound filtering exceeded the advisory total.
                # v62: anchor the outbox retry budget to this run so a
                # legacy exhausted row can never block the first real send.
                start_phase("telegram", config.TELEGRAM_BUDGET_SECONDS, protected=True)
                set_delivery_run_at(datetime.now().isoformat())
                # v71: defined before the branch so the funnel report can
                # always reference it, even when nothing is sent.
                sent_records = []
                # v72: Hidden Jobs Discovery — mine hiring signals from
                # accepted HR posts, verify through the official chain,
                # merge verified jobs into the pool BEFORE sending, and
                # deliver unverified signals as distinct HIRING SIGNAL cards.
                verified_signal_jobs, hiring_signals = _discover_hidden_jobs(
                    final_pool, dry_run=bool(config.DRY_RUN),
                )
                if verified_signal_jobs:
                    # Verified signal jobs carry a real application URL; they
                    # enter the same router, evidence gate and per-channel
                    # dedup as every other candidate — no gate relaxation.
                    final_pool = verified_signal_jobs + final_pool
                hiring_signals_sent = 0
                if hiring_signals and not config.DRY_RUN:
                    hiring_signals_sent = _deliver_hiring_signals(hiring_signals)

                if config.DRY_RUN:
                    preview_count, sent_records = send_jobs(final_pool, dry_run=True)
                    log.info("🧪 DRY_RUN routing preview: would_send=%d; Telegram and seen-state skipped.", preview_count)
                else:
                    log.info(
                        "📤 Sending to Telegram (reserved=%ss, global_remaining=%.1fs)...",
                        config.TELEGRAM_BUDGET_SECONDS, budget_remaining(),
                    )
                    sent_count, sent_records = send_jobs(final_pool)
                    stats["sent"] = sent_count
                    stats["hiring_signals_sent"] = hiring_signals_sent
                    log.info(f"✅ Total sent: {sent_count}")
                    # v75: routed/sent = REAL counts from the send loop.
                    # sent_records ONLY contains actually-posted pairs
                    # (proof-skips continue without appending, so prior-run
                    # sends are never double counted here).
                    # routed = posted-or-conflict-skipped in this run; since
                    # conflicts are skipped silently, routed = posted this run
                    # and any pool→routed gap is attributed to unrouted.
                    def _geo_for_send(job) -> str:
                        _g = classify_delivery_geo(job)
                        return "egypt" if _g == egypt_funnel.EGYPT_GEO else (
                            "arab" if _g == egypt_funnel.ARAB_GEO else "")
                    _v75_by_geo: dict[str, int] = {"egypt": 0, "arab": 0}
                    for _job, _lane, _ch in sent_records:
                        _g = _geo_for_send(_job)
                        if _g:
                            _v75_by_geo[_g] += 1
                    _v75_pool_by_geo = egypt_funnel.stage_keys(_funnel_pool)
                    for _funnel_geo in ("egypt", "arab"):
                        _f = _egypt_funnel.funnel_for(_funnel_geo)
                        _pool_geo_set = _v75_pool_by_geo.get(_funnel_geo, set())
                        _f.set_stage("delivery_eligible", len(_pool_geo_set))
                        _f.set_stage("routed", _v75_by_geo.get(_funnel_geo, 0))
                        _f.set_stage("sent", _v75_by_geo.get(_funnel_geo, 0))
                    _log_v72_signal_summary(verified_signal_jobs, hiring_signals)

            else:
                log.info("ℹ️ No qualifying jobs this run.")
                sent_records = []

            # v74: final funnel log — always after the send loop so routed/sent
            # counters are complete; guarded so telemetry never breaks delivery.
            if not config.DRY_RUN:
                try:
                    from egypt_funnel import log_funnel as _log_egypt_funnel
                    _log_egypt_funnel(_egypt_funnel, "EG/Arab funnel", log)
                except Exception as _exc:
                    log.warning("EG/Arab funnel log failed: %s", _exc)

            # v72: hidden-jobs discovery telemetry (reset per run).
            _log_v72_signal_summary(None, None)
            _reset_v72_telemetry()

            if config.ENABLE_TRAINING_DATA_COLLECTION:
                sent_keys = {j.dedup_key for j, _, _ in sent_records}
                for job in final_pool:
                    key = job.dedup_key
                    if not key or key in sent_keys:
                        continue
                    # Made it into the final pool but a channel/quota
                    # didn't pick it up — still a positive signal.
                    db.record_training_sample(
                        dedup_key=key,
                        title=job.title,
                        company=job.company,
                        location=job.location,
                        source=getattr(job, "source_key", "") or job.source,
                        content_type=getattr(job, "content_type", "job_listing"),
                        description_short=(job.description or "")[:500],
                        accepted=True,
                        reason="candidate_pool",
                    )

            # 7. Mark seen, dedup sent
            if not config.DRY_RUN:
                seen = mark_as_seen(new_jobs, seen)
                log.info(f"💾 Marked {len(new_jobs)} new jobs as seen.")
                if sent_records:
                    seen = deduplicate_sent(sent_records, seen)

            # 8. Morning health report
            http_metrics = get_http_metrics()
            if datetime.now().hour < 10 and not config.DRY_RUN:
                _send_health_report(
                    db, stats["sources"], source_reports, http_metrics, linkedin_telemetry,
                )
            if http_metrics:
                jina_fallbacks = sum(
                    1 for row in source_reports.values() if row.get("transport") == "jina"
                )
                log.info(
                    "🌐 HTTP telemetry:"
                    f" requests={http_metrics.get('requests', 0)}"
                    f" 429={http_metrics.get('429', 0)}"
                    f" 402={http_metrics.get('402', 0)}"
                    f" 407={http_metrics.get('407', 0)}"
                    f" timeouts={http_metrics.get('timeouts', 0)}"
                    f" bypass={http_metrics.get('direct_bypass', 0)}"
                    f" Jina fallback={jina_fallbacks}"
                    f" circuit-open={http_metrics.get('circuit_open', 0) + http_metrics.get('endpoint_circuit_open', 0)}"
                )

    except Exception as e:
        log.exception(f"❌ Error: {e}")

    finally:
        save_seen_ids(seen, config.SEEN_JOBS_FILE)
        elapsed = time.time() - start_time
        counts: dict[str, int] = {}
        for row in source_reports.values():
            counts[row.get("health", "blocked")] = counts.get(row.get("health", "blocked"), 0) + 1
        log.info("=" * 60)
        log.info(f"✅ DONE in {round(elapsed, 1)}s")
        log.info(
            "📡 Sources: attempted=%d healthy=%d degraded=%d blocked=%d not_configured=%d skipped_budget=%d",
            len(source_reports), counts.get("healthy", 0), counts.get("degraded", 0),
            counts.get("blocked", 0), counts.get("not_configured", 0), counts.get("skipped_budget", 0),
        )
        log.info("⏱ Run budget: %s", budget_snapshot())
        log.info(f"   Fetched:  {stats['fetched']}")
        log.info(f"   Filtered: {stats['filtered']}")
        log.info(f"   New:      {stats['new']}")
        log.info(f"   Sent:     {stats['sent']}")
        log.info(f"   Seen:     {len(seen)}")
        # v67: run success report — the headline numbers are the unique,
        # fresh, cyber jobs actually delivered (the goal), not the raw
        # fetch count.  ``delivery_pending`` exposes queued candidates the
        # channel state previously blocked, so operators can see they are
        # being retried instead of silently dropped.
        cyber_candidates = int(stats.get("cyber_candidates", 0))
        pending_now = 0
        if not config.DRY_RUN:
            try:
                pending_now = db.count_pending_delivery_rows()
            except Exception:
                pass
        egypt_health = sum(
            1 for k, row in source_reports.items()
            if k in config.EGYPT_PRIORITY_SOURCE_KEYS and row.get("health") == "healthy"
        )
        egypt_attempted = sum(
            1 for k in source_reports if k in config.EGYPT_PRIORITY_SOURCE_KEYS
        )
        job_yielders = sum(
            1 for row in source_reports.values() if int(row.get("jobs", 0) or 0) > 0
        )
        log.info("=" * 60)
        log.info("v67 Run success report:")
        log.info(
            f"   Sources: attempted={len(source_reports)} egypt_attempted={egypt_attempted} "
            f"egypt_healthy={egypt_health} yielders={job_yielders} "
            f"degraded={counts.get('degraded', 0)} blocked={counts.get('blocked', 0)}"
        )
        # v74: quality headline — the goal is UNIQUE FRESH CYBER jobs sent,
        # not raw fetch count; when sent == 0 the pending counters show
        # whether there was anything left undelivered to retry.
        _unique_fresh_cyber_sent = len({
            getattr(job, "dedup_key", "") for job, _lane, _ch in sent_records
        }) if sent_records else 0
        log.info(
            f"   Quality: cyber_candidates={cyber_candidates} "
            f"delivery_pending_now={pending_now} "
            f"sent={stats['sent']} unique_fresh_cyber_sent={_unique_fresh_cyber_sent} "
            f"goal=unique_fresh_cyber_over_raw_count"
        )
        # v71: the delivery funnel — exact per-stage counters the sender
        # accumulated.  The headline number that matters is
        # unique_fresh_cyber sent; every other counter exists so a drop at
        # any stage is diagnosable from the run log instead of guessed.
        _pending_unique = 0
        if not config.DRY_RUN:
            try:
                _pending_unique = db.count_pending_unique_jobs()
            except Exception:
                pass
        log.info(
            f"   📈 v71 delivery funnel: sent={stats['sent']} pending_rows={pending_now} "
            f"pending_unique_jobs={_pending_unique} "
            f"sent_records={len(sent_records)}"
        )
        log.info("=" * 60)


if __name__ == "__main__":
    main()


def _is_stale_job(job) -> bool:
    """Backward-compatible wrapper used by tests and older callers."""
    from intelligence.pool_builder import is_stale
    return is_stale(job)
