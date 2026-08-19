"""v72+v74: Hidden Jobs / Multi-Signal Discovery — detect hiring signals
that are NOT published as explicit job listings, then verify them through an
official search chain so every delivered item is either a VERIFIED JOB (real
application URL) or a clearly-labeled HIRING SIGNAL.

Signal sources:
  - LinkedIn recruiter / employee posts ("We're growing our security team")
  - Company hiring announcements and "Join our team" / "We're hiring" posts
  - Engineering blog hiring sections
  - University career pages and career fairs
  - Recruitment agency posts
  - v74: official company careers pages ("We're hiring" sections)
  - v74: GitHub company pages / engineering blogs / agency listings

Pipeline per signal:
    Post detected → company identified → role inferred →
    official careers search → LinkedIn jobs search → ATS/form search →
    application URL found?  → VERIFIED JOB (normal delivery)
    application URL NOT found? → HIRING SIGNAL (distinct card style)

Gates never relax: a hiring signal must still carry cyber intent evidence
and a valid region before it is delivered in ANY form.

This module is deliberately standalone: it consumes raw text posts, and
produces either Job instances (verified) or HiringSignal records (unverified).
It NEVER bypasses the classifier, the evidence gate, or the routing rules.
"""
import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# ── Signal detection ──────────────────────────────────────────────────────

# Hiring intent phrasing BEYOND the generic HR-post list: team-growth and
# expansion wording that employees/recruiters use when NO job listing exists.
_TEAM_GROWTH_SIGNALS = (
    "we're growing our", "we are growing our", "growing our team",
    "growing our security", "expanding our security", "security team is growing",
    "join our security team", "security team is hiring", "our team is expanding",
    "looking for security", "we need security", "hiring security",
    "open headcount", "new security roles", "building a security team",
    "scaling our security", "security openings", "security vacancies",
)

_UNPUBLISHED_ROLE_SIGNALS = (
    "soc", "security engineer", "security analyst", "cybersecurity", "cyber",
    "information security", "pentest", "red team", "appsec", "cloud security",
    "grc", "incident response", "threat", "vulnerability", "devsecops",
    "security specialist", "it security", "infosec", "ciso", "security lead",
    "security manager", "security architect", "security researcher",
)


@dataclass
class HiringSignal:
    """An unverified hiring signal — no application URL exists yet."""
    source_text: str
    company: str
    inferred_title: str
    region_hint: str = ""
    url: str = ""
    signal_source: str = ""          # e.g. linkedin_recruiter, company_announcement
    verified: bool = False

    @property
    def display_title(self) -> str:
        return f"{self.inferred_title} — {self.company}"


@dataclass
class SignalVerificationResult:
    """Outcome of running a HiringSignal through the verification chain."""
    signal: "HiringSignal"
    verified_job: object | None = None   # populated when an application URL is found
    chain_results: dict[str, dict] = field(default_factory=dict)
    decision: str = ""                    # "verified_job" | "hiring_signal"

    @property
    def is_verified_job(self) -> bool:
        return self.decision == "verified_job" and self.verified_job is not None


def _detect_company(text: str) -> str:
    """Infer the hiring company from the post text.

    Order of evidence: explicit "at <Company>" / "@Company" mention → first
    capitalized candidate after a hiring anchor → empty (unverifiable).
    """
    hits = re.findall(
        r"(?:\bat\b|\B@|team\s+at)\s*([A-Z][A-Za-z0-9&'\.\-]{2,40})", text,
    )
    for name in hits:
        name = name.strip().rstrip(".,;:")
        if not name.lower().startswith(("the ", "join ", "we ")):
            return name
    m = re.search(r"at\s+([A-Z][A-Za-z0-9&'\.\-]{2,40})\b", text)
    if m:
        return m.group(1)
    m = re.match(r"([A-Z][A-Za-z0-9&'\.\-]{2,20})\s+(?:is\s+hiring|are\s+hiring)", text)
    if m:
        return m.group(1)
    return ""


def detect_hiring_signal(text: str) -> HiringSignal | None:
    """Return a HiringSignal when the text looks like an unpublished hiring
    signal for a security role at an identifiable company, else None."""
    lowered = text.lower()
    has_growth = any(s in lowered for s in _TEAM_GROWTH_SIGNALS)
    has_role = any(s in lowered for s in _UNPUBLISHED_ROLE_SIGNALS)
    company = _detect_company(text)
    if not (has_growth and has_role and company):
        return None
    return HiringSignal(
        source_text=text,
        company=company,
        inferred_title=_infer_role_title(lowered, company),
        region_hint="",
        url="",
    )


def _infer_role_title(lowered: str, company: str) -> str:
    """Pick the most specific security-role keyword as an inferred title."""
    for kw in ("soc analyst", "pentest", "red team", "security engineer",
               "security analyst", "cloud security", "appsec", "devsecops",
               "incident response", "vulnerability", "grc", "security lead",
               "security architect", "infosec", "cybersecurity", "security"):
        if kw in lowered:
            return kw.title().replace("Pentest", "Penetration Testing")
    return "Security Role"


# ── Verification chain ────────────────────────────────────────────────────

def _build_company_careers_queries(company: str) -> list[dict]:
    """Ordered verification searches: official careers search first, then
    LinkedIn jobs search, then ATS/form search.  The same query shapes
    already validated by the HR Posts discovery lanes are reused."""
    return [
        {"query": f"{company} careers security jobs site:careers.*",
         "kind": "careers_search", "label": "careers search engine"},
        {"query": f"site:linkedin.com/jobs {company} security",
         "kind": "linkedin_jobs", "label": "LinkedIn jobs search"},
        {"query": f"{company} security jobs apply",
         "kind": "ats_apply", "label": "ATS/application search"},
    ]


def verify_signal(signal: HiringSignal, *, search_fn=None,
                  job_builder=None) -> SignalVerificationResult:
    """Run a HiringSignal through the official verification ladder.

    ``search_fn`` is a callable (query_spec: dict) -> list[(url, title)] that
    the caller wires to the existing search backends.  It stays injectable
    so the discovery layer never imports search internals directly and
    tests can stub it.

    ``job_builder`` is a callable (url, title, company) -> Job | None used to
    convert a found URL into a verified job.  When None the result only
    records the verified URL without producing a Job.
    """
    from models import Job  # noqa: F401 (only needed for type check; builder builds it)

    result = SignalVerificationResult(signal=signal)
    for spec in _build_company_careers_queries(signal.company):
        if not search_fn:
            break
        try:
            hits = search_fn(spec) or []
        except Exception as exc:  # one backend failing must not kill the chain
            log.debug("v72 verification backend [%s] failed: %s", spec["kind"], exc)
            hits = []
        result.chain_results[spec["kind"]] = {"hits": len(hits),
                                              "query": spec["query"]}
        if not hits:
            continue
        url, title = hits[0]
        if not url:
            continue
        result.signal.url = url
        result.signal.verified = True
        if job_builder:
            try:
                job = job_builder(url, title, signal.company)
            except Exception:
                job = None
            if job is not None:
                job.title = title or signal.inferred_title
                job.company = signal.company
                job.source_key = getattr(job, "source_key", "") or "linkedin_hr_posts"
                job.source = getattr(job, "source", "") or "linkedin"
                job.tags = list(getattr(job, "tags", []) or []) + [
                    f"v72_signal:{signal.signal_source or 'unpublished'}",
                    "v72_verified_signal",
                ]
                if signal.region_hint:
                    job.geo_hint = signal.region_hint
                job.content_type = "job_listing"
                job.verified_by_signal = True
                result.verified_job = job
                result.decision = "verified_job"
                log.info(
                    "v72 Hidden Jobs Discovery: %s — signal verified to a real "
                    "application URL via %s → VERIFIED JOB [%s]",
                    signal.display_title, spec["kind"], url[:110],
                )
                _TELEMETRY["signals_verified_job"] += 1
                return result
        else:
            result.decision = "verified_job"
            _TELEMETRY["signals_verified_job"] += 1
            return result
    result.decision = "hiring_signal"
    log.info(
        "v72 Hidden Jobs Discovery: %s — no application URL found after the "
        "full chain → HIRING SIGNAL (distinct card, no apply link)",
        signal.display_title,
    )
    _TELEMETRY["signals_emitted_hiring_signal"] += 1
    return result


# ── Telemetry ─────────────────────────────────────────────────────────────

_TELEMETRY = {
    "signals_detected": 0,
    "signals_verified_job": 0,
    "signals_emitted_hiring_signal": 0,
    # v74: per-lane counters — each discovery lane reports separately so
    # the run log shows exactly which signal surface is producing value.
    "signals_detected_linkedin": 0,
    "signals_detected_careers_page": 0,
    "signals_detected_engineering_blog": 0,
    "signals_detected_university": 0,
    "signals_detected_agency": 0,
}


def get_v72_signal_telemetry() -> dict[str, int]:
    return dict(_TELEMETRY)


def _reset_v72_telemetry() -> None:
    for key in _TELEMETRY:
        _TELEMETRY[key] = 0


# ── v74: source-tagged detection ──────────────────────────────────────────

def detect_signals_from_text_list(
    texts: list[str],
    *,
    lane: str = "linkedin",
) -> list[HiringSignal]:
    """v74: detect hiring signals across a batch of raw texts and tag each
    one with its discovery lane.  ``lane`` must be one of the telemetry
    lane names (linkedin, careers_page, engineering_blog, university,
    agency) — an unknown lane falls back to ``linkedin`` so telemetry keys
    never drift at runtime.

    The core three-condition rule (growth phrasing + security role +
    identifiable company) is preserved from v72 — tagging does not relax
    any gate.  Returns all signals found; the caller decides which ones to
    verify against its budget.
    """
    if lane not in ("linkedin", "careers_page", "engineering_blog",
                    "university", "agency"):
        lane = "linkedin"
    found: list[HiringSignal] = []
    for text in texts:
        signal = detect_hiring_signal(text)
        if signal is None:
            continue
        signal.signal_source = lane
        found.append(signal)
        _TELEMETRY["signals_detected"] += 1
        _TELEMETRY[f"signals_detected_{lane}"] += 1
    return found


# ── v74: company careers-page signal mining ───────────────────────────────

# Careers pages announce openings in body text rather than structured
# listings. These anchors match both English and Arabic announcement voice
# ("انضم لفريقنا", "وظائف شاغرة") so a page that contains neither a job
# listing nor an announcement produces nothing — no false positives.
_CAREERS_PAGE_ANNOUNCERS = (
    "we are hiring", "we're hiring", "join our team", "join us", "openings",
    "vacancies", "open positions", "careers", "hiring now", "new roles",
    "growing our team", "expanding our team", "انضم لفريقنا", "وظائف شاغرة",
    "توظيف", "انضم الينا", "فرص وظيفية",
)


def extract_careers_page_signals(
    page_text: str,
    company: str,
    careers_url: str = "",
) -> list[HiringSignal]:
    """v74: scan an official company careers page for hiring announcements
    that are NOT structured job listings.  Each signal carries its own
    inferred security role and the ``careers_page`` lane tag.

    A careers page may mention security roles in an announcement section
    ("We're growing our security team — join us") even when the page
    itself lists no jobs yet. Those moments are exactly the unpublished
    headcount the pipeline should follow up on.

    Returns at most two signals per page: one per distinct announcement
    block, so a single careers page never floods the verification budget.
    """
    if not (page_text and company):
        return []
    lowered = page_text.lower()
    has_role = any(s in lowered for s in _UNPUBLISHED_ROLE_SIGNALS)
    if not has_role:
        return []
    # Split on paragraph boundaries so each announcement block is judged
    # independently; a block must contain an announcement anchor AND a
    # security role to qualify — the same three-condition discipline as
    # detect_hiring_signal, applied per block.
    blocks = re.split(r"\n{2,}|\r\n{2,}|(?<=\.)\s{2,}", page_text)
    signals: list[HiringSignal] = []
    for block in blocks:
        if len(signals) >= 2:
            break
        block_lowered = block.lower()
        if not any(a in block_lowered for a in _CAREERS_PAGE_ANNOUNCERS):
            continue
        if not any(s in block_lowered for s in _UNPUBLISHED_ROLE_SIGNALS):
            continue
        signals.append(HiringSignal(
            source_text=block.strip(),
            company=company,
            inferred_title=_infer_role_title(block_lowered, company),
            region_hint="",
            url=careers_url,
            signal_source="careers_page",
        ))
        _TELEMETRY["signals_detected"] += 1
        _TELEMETRY["signals_detected_careers_page"] += 1
    return signals
