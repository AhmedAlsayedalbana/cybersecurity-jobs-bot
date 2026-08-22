"""Official public career-site connectors.

Every entry in :data:`OFFICIAL_SOURCES` represents one named public source.
The connector intentionally retrieves *active jobs*, not a keyword-filtered
subset; the bot's existing cybersecurity filter remains the single filtering
authority.  The module uses public endpoints only and never needs an account,
cookie, API key, or paid proxy.

The catalogue favours a documented/public ATS response (Greenhouse, Workday,
Ashby, Amazon Jobs) and then uses embedded structured data from the official
career page.  Browser rendering is a last-resort fallback for portals that
block an ordinary HTTP client or expose their jobs only after JavaScript runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
import json
import logging
import os
import re
import threading
import time
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from models import Job
import config
from sources.http_utils import get_json, get_text_result, post_json
from sources.marketplace_sources import SourceResult
from run_budget import source_remaining

# CareerSource keys whose official page is a JavaScript SPA: the HTML client
# reliably returns zero listings, and a Playwright render is the only real
# way to read the portal. Everything else stays endpoint-only — a browser
# render on an endpoint that already answered is noise, never supply.
_JS_ONLY_SOURCE_KEYS: frozenset[str] = frozenset({
    "nbe", "we_jina", "qnb_egypt", "cib_egypt", "banque_misr",
    "banque_du_caire", "aaib", "adib_egypt", "etisalat_egypt",
    "emirates_nbd_egypt", "mashreq_egypt", "bank_nxt", "itida",
    "smart_village", "pharco", "raya",
})

log = logging.getLogger(__name__)

_SCRIPT_RE = re.compile(
    r"<script[^>]+(?:type=[\"'](?:application/ld\+json|application/json)[\"']|id=[\"']__NEXT_DATA__[\"'])[^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
_ANCHOR_RE = re.compile(
    r"<a\b[^>]*?href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_JOB_LINK_RE = re.compile(r"(?i)(?:/job(?:s)?/|job[_-]?id=|requisition|vacanc|position|opening)")
_SKIP_TITLES = {
    "search jobs", "search all jobs", "view all jobs", "view jobs", "job alerts",
    "create job alert", "apply now", "learn more", "read more", "show more",
    "all jobs", "careers", "career opportunities", "jobs",
}
_BROWSER_LOCK = threading.BoundedSemaphore(1)


@dataclass(frozen=True, slots=True)
class CareerSource:
    """One public career source and the facts needed to call it."""

    key: str
    name: str
    company: str
    lane: str
    backend: str
    url: str
    geo_hint: str = ""
    board: str = ""
    tenant: str = ""
    site: str = ""
    page_param: str = ""
    page_start: int = 1
    page_size: int = 50
    query: str = ""
    browser_fallback: bool = False
    # v68: cheap public-reader (Jina) rescue step for sources whose client
    # IP keeps getting blocked or timing out while the public reader sees
    # the page fine.  Only the sources that actually showed a
    # blocked/timeout/empty failure pattern get it enabled — enabling it
    # everywhere would add per-source latency on portals that never fail.
    public_fallback: bool = False
    # Hard safety cap on HTML pagination. Without this, a source whose page
    # content never repeats (e.g. a JS-rendered SPA returning slightly
    # different noise per page instead of real listings, or a search query
    # that legitimately matches thousands of results) can loop indefinitely,
    # burning the run's entire time budget and proxy quota on one source.
    # 2026-07-21 incident: mandiant_google_cloud_security walked all the way
    # to page=3187 (~41 minutes) before a proxy 402 finally stopped it.
    max_pages: int = 5


# Keep source keys stable and one-to-one with the user-visible source.  A
# shared company portal (Google and Microsoft) still gets independent entries
# when it represents a different requested source.
OFFICIAL_SOURCES: tuple[CareerSource, ...] = (
    # Egypt job boards and company careers
    CareerSource("forasna", "Forasna", "Forasna", "egypt", "html", "https://forasna.com/job/search", "egypt", page_param="page"),
    CareerSource("shaghalni", "Shaghalni", "Shaghalni", "egypt", "html", "https://shaghalni.com/hiring-center/jobs", "egypt", page_param="page"),
    CareerSource("vodafone_egypt", "Vodafone Egypt Careers", "Vodafone Egypt", "egypt", "successfactors", "https://opportunities.vodafone.com/search/", "egypt", page_param="start"),
    CareerSource("orange_egypt", "Orange Egypt Careers", "Orange Egypt", "egypt", "phenom", "https://orange.jobs/gb/en/search-results", "egypt", page_param="page"),
    CareerSource("telecom_egypt", "WE (Telecom Egypt) Careers", "Telecom Egypt", "egypt", "html", "https://te.eg/wps/portal/te/Personal/Careers", "egypt", page_param="page", browser_fallback=True, public_fallback=True),
    CareerSource("banque_misr", "Banque Misr Careers", "Banque Misr", "egypt", "html", "https://www.banquemisr.com/en/careers", "egypt", page_param="page", browser_fallback=True, public_fallback=True),
    CareerSource("nbe", "National Bank of Egypt Careers", "National Bank of Egypt", "egypt", "html", "https://www.nbe.com.eg/NBE/E/#/EN/Employment", "egypt", page_param="page", browser_fallback=True, public_fallback=True),
    CareerSource("cib_egypt", "CIB Careers", "Commercial International Bank", "egypt", "html", "https://www.cibeg.com/en/careers", "egypt", page_param="page", browser_fallback=True, public_fallback=True),
    CareerSource("qnb_egypt", "QNB Egypt Careers", "QNB Egypt", "egypt", "html", "https://www.qnb.com/sites/qnb/qnbegypt/page/en/encareers.html", "egypt", page_param="page", browser_fallback=True, public_fallback=True),
    CareerSource("banque_du_caire", "Banque du Caire Careers", "Banque du Caire", "egypt", "html", "https://www.bdc.com.eg/bdcwebsite/personal/careers.html", "egypt", page_param="page", browser_fallback=True, public_fallback=True),
    CareerSource("valeo_egypt", "Valeo Egypt Careers", "Valeo", "egypt", "workday", "https://valeo.wd3.myworkdayjobs.com/en-US/valeo_jobs", "egypt", tenant="valeo", site="valeo_jobs"),
    CareerSource("ibm_egypt", "IBM Egypt Careers", "IBM", "egypt", "html", "https://www.ibm.com/careers/search", "egypt", page_param="page"),
    CareerSource("microsoft_egypt", "Microsoft Egypt Careers", "Microsoft", "egypt", "eightfold", "https://apply.careers.microsoft.com/careers", "egypt", page_param="page"),
    CareerSource("siemens_egypt", "Siemens Egypt Careers", "Siemens", "egypt", "html", "https://jobs.siemens.com/en_US/externaljobs/SearchJobs", "egypt", page_param="page"),
    # ── Egypt blocked-source fallbacks ─────────────────────────────────────
    CareerSource("cib_egypt_wd", "CIB Careers (Workday)", "Commercial International Bank", "egypt", "workday", "https://cibeg.wd1.myworkdayjobs.com/en-US/cib_jobs", "egypt", tenant="cibeg", site="cib_jobs"),
    CareerSource("nbe_html", "NBE Careers (HTML)", "National Bank of Egypt", "egypt", "html", "https://www.nbe.com.eg/en/Pages/Default.aspx", "egypt", page_param="page", public_fallback=True),
    CareerSource("we_jina", "WE Telecom Egypt (Alt)", "Telecom Egypt", "egypt", "html", "https://te.eg/wps/portal/te/Personal/Careers/!ut/p/z1/", "egypt", page_param="page", browser_fallback=True, public_fallback=True),
    CareerSource("qnb_global", "QNB Global Careers", "QNB Egypt", "egypt", "html", "https://careers.qnb.com/", "egypt", page_param="page", browser_fallback=True, public_fallback=True),
    # ── Egypt banking sector ────────────────────────────────────────────────
    CareerSource("aaib", "AAIB Careers", "Arab African International Bank", "egypt", "html", "https://aaib.com.eg/en/careers", "egypt", page_param="page", browser_fallback=True, public_fallback=True),
    CareerSource("credit_agricole_egypt", "Crédit Agricole Egypt Careers", "Crédit Agricole Egypt", "egypt", "html", "https://www.ca-egypt.com/en/careers", "egypt", page_param="page", browser_fallback=True, public_fallback=True),
    CareerSource("hsbc_egypt", "HSBC Egypt Careers", "HSBC Egypt", "egypt", "html", "https://www.hsbc.com/careers", "egypt", page_param="page", public_fallback=True),
    CareerSource("adib_egypt", "ADIB Egypt Careers", "Abu Dhabi Islamic Bank Egypt", "egypt", "html", "https://www.adib.com.eg/careers", "egypt", page_param="page", browser_fallback=True, public_fallback=True),
    CareerSource("fabmisr", "FABMISR Careers", "FABMISR", "egypt", "html", "https://www.fabmisr.com.eg/careers", "egypt", page_param="page", browser_fallback=True, public_fallback=True),
    CareerSource("hdb", "HDB Careers", "Housing and Development Bank", "egypt", "html", "https://www.hdb-egypt.com/careers", "egypt", page_param="page", browser_fallback=True, public_fallback=True),
    CareerSource("emirates_nbd_egypt", "Emirates NBD Egypt Careers", "Emirates NBD Egypt", "egypt", "html", "https://www.emiratesnbd.com/egypt/careers", "egypt", page_param="page", browser_fallback=True, public_fallback=True),
    CareerSource("mashreq_egypt", "Mashreq Egypt Careers", "Mashreq Egypt", "egypt", "html", "https://www.mashreq.com/egypt/careers", "egypt", page_param="page", browser_fallback=True, public_fallback=True),
    CareerSource("al_baraka_bank", "Al Baraka Bank Careers", "Al Baraka Bank", "egypt", "html", "https://www.albarakabank.com.eg/careers", "egypt", page_param="page", browser_fallback=True, public_fallback=True),
    CareerSource("bank_abc", "Bank ABC Careers", "Bank ABC", "egypt", "html", "https://www.bankabc.com.eg/careers", "egypt", page_param="page", browser_fallback=True, public_fallback=True),
    CareerSource("saib", "SAIB Careers", "SAIB", "egypt", "html", "https://www.saib.com.eg/careers", "egypt", page_param="page", browser_fallback=True, public_fallback=True),
    CareerSource("bank_nxt", "Bank NXT Careers", "Bank NXT", "egypt", "html", "https://banknxt.com/careers", "egypt", page_param="page", browser_fallback=True, public_fallback=True),
    # ── Egypt telecom / digital sector ─────────────────────────────────────
    CareerSource("raya", "Raya Careers", "Raya", "egypt", "html", "https://www.raya.com.eg/careers", "egypt", page_param="page", browser_fallback=True),
    CareerSource("vois", "VOIS Careers", "VOIS (Vodafone Intelligent Solutions)", "egypt", "html", "https://vois.com.eg/careers", "egypt", page_param="page", browser_fallback=True),
    CareerSource("etisalat_egypt", "e& Egypt Careers", "e& Egypt", "egypt", "html", "https://careers.etisalat.com.eg", "egypt", page_param="page", browser_fallback=True),
    # ── Egypt IT / software / cloud ─────────────────────────────────────────
    CareerSource("itida", "ITIDA Careers", "ITIDA", "egypt", "html", "https://www.itida.gov.eg/careers", "egypt", page_param="page", browser_fallback=True),
    CareerSource("smart_village", "Smart Village Careers", "Smart Village", "egypt", "html", "https://www.smart-village.com/careers", "egypt", page_param="page", browser_fallback=True),
    # ── Egypt cybersecurity ─────────────────────────────────────────────────
    CareerSource("cybershield", "CyberShield Careers", "CyberShield", "egypt", "html", "https://www.cybershield.com.eg/careers", "egypt", page_param="page", browser_fallback=True),
    CareerSource("eset_egypt", "ESET Egypt Careers", "ESET Egypt", "egypt", "html", "https://www.eset.com.eg/careers", "egypt", page_param="page", browser_fallback=True),
    # ── Egypt consulting (Big Four) ────────────────────────────────────────
    CareerSource("pwc_egypt", "PwC Egypt Careers", "PwC Egypt", "egypt", "html", "https://www.pwc.com.eg/careers", "egypt", page_param="page", browser_fallback=True),
    CareerSource("deloitte_egypt", "Deloitte Egypt Careers", "Deloitte Egypt", "egypt", "html", "https://www2.deloitte.com/eg/careers", "egypt", page_param="page"),
    CareerSource("ey_egypt", "EY Egypt Careers", "EY Egypt", "egypt", "html", "https://www.ey.com/eg/careers", "egypt", page_param="page"),
    CareerSource("kpmg_egypt", "KPMG Egypt Careers", "KPMG Egypt", "egypt", "html", "https://www.kpmg.com.eg/careers", "egypt", page_param="page", browser_fallback=True),
    # ── Egypt engineering / manufacturing ───────────────────────────────────
    CareerSource("orascom_construction", "Orascom Construction Careers", "Orascom Construction", "egypt", "html", "https://www.orascom.com/careers", "egypt", page_param="page", browser_fallback=True),
    CareerSource("elsewedy_electric", "Elsewedy Electric Careers", "Elsewedy Electric", "egypt", "html", "https://www.elsewedy.com/careers", "egypt", page_param="page", browser_fallback=True),
    # ── Egypt pharma / healthcare ───────────────────────────────────────────
    CareerSource("pharco", "Pharco Careers", "Pharco", "egypt", "html", "https://www.pharco.com/careers", "egypt", page_param="page", browser_fallback=True),
    # Gulf job boards
    CareerSource("naukrigulf", "NaukriGulf", "NaukriGulf", "gulf", "html", "https://www.naukrigulf.com/jobs", "gulf", page_param="pageNo"),
    CareerSource("jobzella", "Jobzella", "Jobzella", "gulf", "html", "https://www.jobzella.com/jobs", "gulf", page_param="page"),
    CareerSource("dubizzle", "Dubizzle Jobs", "Dubizzle", "gulf", "html", "https://dubizzle.com/jobs/", "gulf", page_param="page", browser_fallback=True),
    CareerSource("laimoon", "Laimoon", "Laimoon", "gulf", "html", "https://www.laimoon.com/uae/jobs", "gulf", page_param="page", browser_fallback=True),
    # Saudi Arabia
    CareerSource("stc_ksa", "STC Careers", "STC Saudi Arabia", "gulf", "successfactors", "https://careers.stc.com.sa/search/", "gulf", page_param="start"),
    CareerSource("aramco", "Saudi Aramco Careers", "Saudi Aramco", "gulf", "html", "https://careers.aramco.com/job-search-results/", "gulf", page_param="page"),
    CareerSource("sabic", "SABIC Careers", "SABIC", "gulf", "successfactors", "https://jobs.sabic.com/search/", "gulf", page_param="start"),
    CareerSource("neom", "NEOM Careers", "NEOM", "gulf", "eightfold", "https://careers.neom.com/careers", "gulf", page_param="page"),
    CareerSource("qiddiya", "Qiddiya Careers", "Qiddiya", "gulf", "html", "https://qiddiya.com/en/careers/", "gulf", page_param="page", browser_fallback=True),
    CareerSource("elm", "Elm Company Careers", "Elm", "gulf", "successfactors", "https://career.elm.sa/elm", "gulf", page_param="start"),
    # Qatar / UAE
    CareerSource("qatarenergy", "QatarEnergy Careers", "QatarEnergy", "gulf", "saphcm", "https://careerportal.qatarenergy.qa/jobs", "gulf", page_param="page"),
    CareerSource("ooredoo", "Ooredoo Careers", "Ooredoo", "gulf", "successfactors", "https://careers.ooredoo.com/search/", "gulf", page_param="start"),
    CareerSource("etisalat_uae", "e& (Etisalat) Careers", "Etisalat by e&", "gulf", "html", "https://careers.etisalat.ae/en/index.html", "gulf", page_param="page", browser_fallback=True),
    CareerSource("emirates_group", "Emirates Group Careers", "Emirates Group", "gulf", "avature", "https://www.emiratesgroupcareers.com/search-and-apply/", "gulf", page_param="page"),
    CareerSource("flydubai", "FlyDubai Careers", "flydubai", "gulf", "icims", "https://careers-flydubai.icims.com/jobs/search?ss=1", "gulf", page_param="page"),
    # Cybersecurity and global vendor careers
    CareerSource("hackerone", "HackerOne Careers", "HackerOne", "core", "ashby", "https://jobs.ashbyhq.com/hackerone", "global", board="hackerone"),
    CareerSource("bugcrowd", "Bugcrowd Careers", "Bugcrowd", "core", "greenhouse", "https://boards.greenhouse.io/bugcrowd", "global", board="bugcrowd"),
    CareerSource("cloudflare", "Cloudflare Careers", "Cloudflare", "core", "greenhouse", "https://boards.greenhouse.io/cloudflare", "global", board="cloudflare"),
    CareerSource("crowdstrike", "CrowdStrike Careers", "CrowdStrike", "core", "workday", "https://crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers", "global", tenant="crowdstrike", site="crowdstrikecareers"),
    CareerSource("palo_alto_networks", "Palo Alto Networks Careers", "Palo Alto Networks", "core", "workday", "https://paloaltonetworks.wd5.myworkdayjobs.com/en-US/panwexternalcareers", "global", tenant="paloaltonetworks", site="panwexternalcareers"),
    CareerSource("fortinet", "Fortinet Careers", "Fortinet", "core", "oracle_hcm", "https://edel.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001/jobs", "global", page_param="page"),
    CareerSource("rapid7", "Rapid7 Careers", "Rapid7", "core", "html", "https://careers.rapid7.com/jobs/search", "global", page_param="page"),
    CareerSource("tenable", "Tenable Careers", "Tenable", "core", "greenhouse", "https://boards.greenhouse.io/tenableinc", "global", board="tenableinc"),
    CareerSource("wiz", "Wiz Careers", "Wiz", "core", "greenhouse", "https://boards.greenhouse.io/wizinc", "global", board="wizinc"),
    CareerSource("check_point", "Check Point Careers", "Check Point", "core", "html", "https://careers.checkpoint.com/index.php?m=cpcareers&a=search", "global", page_param="page"),
    CareerSource("cisco", "Cisco Careers", "Cisco", "core", "phenom", "https://careers.cisco.com/global/en/search-results", "global", page_param="page"),
    CareerSource("google_careers", "Google Careers", "Google", "core", "html", "https://www.google.com/about/careers/applications/jobs/results/", "global", page_param="page", max_pages=3),
    CareerSource("microsoft_security", "Microsoft Security Careers", "Microsoft", "core", "eightfold", "https://apply.careers.microsoft.com/careers?query=security", "global", page_param="page"),
    CareerSource("amazon_aws", "Amazon AWS Careers", "Amazon Web Services", "core", "amazon", "https://www.amazon.jobs/en/search.json", "global", query="AWS"),
    CareerSource("mandiant_google_cloud_security", "Mandiant / Google Cloud Security Careers", "Google Cloud Security", "core", "html", "https://www.google.com/about/careers/applications/jobs/results/?q=Google%20Cloud%20Security", "global", page_param="page", max_pages=3),
)

SOURCES_BY_KEY = {source.key: source for source in OFFICIAL_SOURCES}
OFFICIAL_SOURCE_KEYS = frozenset(SOURCES_BY_KEY)


@dataclass(slots=True)
class _Outcome:
    jobs: list[Job]
    parsed: bool = False
    no_active_jobs: bool = False
    error_code: str = ""
    raw_html: str = ""


def fetcher_for(source_key: str) -> Callable[[], SourceResult]:
    """Return a registry-compatible, zero-argument named-source fetcher."""

    def _fetch() -> SourceResult:
        return fetch_source(source_key)

    _fetch.__name__ = f"fetch_{source_key}"
    return _fetch


_ZERO_JOBS_BLOCKED_CODES = frozenset({"http_403", "http_401", "http_429", "http_407", "proxy_402", "proxy_407"})
_ZERO_JOBS_TIMEOUT_CODES = frozenset({"timeout", "connectionerror", "connecttimeout", "readtimeout", "proxy_error"})


def _classify_zero_jobs_reason(error_code: str, parsed: bool, no_active_jobs: bool) -> str:
    """Return a structured zero-jobs audit reason code."""
    if no_active_jobs:
        return "EMPTY_REAL"
    if not error_code:
        return "PARSE_CHANGED" if parsed else "BLOCKED"
    lower = error_code.lower()
    if any(lower.endswith(c) or lower == c for c in _ZERO_JOBS_BLOCKED_CODES):
        return "BLOCKED"
    if any(lower.endswith(c) or lower == c for c in _ZERO_JOBS_TIMEOUT_CODES):
        return "TIMEOUT"
    if parsed:
        return "PARSE_CHANGED"
    return "BLOCKED"


def _source_budget_seconds(source: CareerSource) -> float:
    """Per-source cooperative ceiling.

    v64: the ceiling covers a fast cascade, never a long wait.  Egyptian
    priority sources get a dedicated cap that stays short enough that a
    failing bank can never drain the run budget; the generic 40s cap is also
    respected because priority still cannot exceed the shared ceiling plus
    one small buffer.
    """
    is_priority = source.key in config.EGYPT_PRIORITY_SOURCE_KEYS
    if is_priority:
        # 45s total: official endpoint/search (fast) + lightweight HTML + one
        # short JS-only Playwright pass.  A failing bank stops losing time
        # after this, and the orchestrator's own wait_for deadline (same cap)
        # then moves on to the next source immediately.
        return min(float(config.EGYPT_PRIORITY_SOURCE_TIMEOUT_SECONDS), 45.0)
    return float(config.PLAYWRIGHT_SOURCE_TIMEOUT_SECONDS)


# v64 per-attempt caps: a failing route in the cascade must give up fast —
# ``connecttimeout`` on a dead portal is retried once with the same short
# cap, never held open until the source deadline burns away.
_FAST_ATTEMPT_TIMEOUT_SECONDS = float(os.getenv("CAREERS_FAST_ATTEMPT_TIMEOUT_SECONDS", "8"))
_FAST_ATTEMPT_SECOND_CAP_SECONDS = float(os.getenv("CAREERS_FAST_ATTEMPT_SECOND_CAP_SECONDS", "10"))
# v70: when a proven-failing source (public_fallback) asks for the last-
# resort browser step ONLY because the public reader itself could not
# answer, the browser gets one FAST attempt — never the full source
# deadline. The reader's failure is a weak signal (maybe a transient
# Jina outage), so a quick JS-render check is fair; a long wait is not.
_FAST_BROWSER_CAP_SECONDS = float(os.getenv("CAREERS_FAST_BROWSER_CAP_SECONDS", "15"))


def _source_direct_budget_seconds(source: CareerSource) -> float:
    """v76: maximum wall-clock the DIRECT step may consume before the
    fallback ladder gets the rest.  Previously _DIRECT_ATTEMPT_CAP was
    defined but never enforced, which let a hanging Egyptian portal burn
    the entire source deadline (30s) so the recovery ladder was never
    reached — the exact failure seen for AAIB/ADIB/Banque Misr/ITIDA.
    A failing bank must not spend its whole budget on one portal; the
    ladder and the (rare) browser step keep the remainder."""
    return max(2.0, _DIRECT_ATTEMPT_CAP * _source_budget_seconds(source))


def _fetch_direct_with_cap(source: CareerSource, *, direct_budget_seconds: float) -> _Outcome:
    """_fetch_direct but stopped by wall-clock so the fallback ladder is
    guaranteed a chance.  Uses a lightweight elapsed-time check plus an
    absolute ceiling on the first page: when the first page itself hangs
    for longer than the budget, pagination stops immediately."""
    if source.backend not in ("greenhouse", "workday", "ashby", "amazon"):
        # HTML page sources: each page costs ~8-10s, so the loop stops
        # pagination at this wall-clock cap and the fallback ladder
        # (alt endpoints + public reader) keeps the rest of the budget.
        outcome = _fetch_html_pages(source, budget_seconds=direct_budget_seconds)
        return outcome
    return _fetch_direct(source)


def fetch_source(source_key: str) -> SourceResult:
    """Fetch one official source and report an honest health status.

    Official endpoint/API comes FIRST.  Playwright is reserved for sources
    whose careers page is genuinely JavaScript-only: a SPA that an HTTP
    client cannot parse and whose anchor links do not carry job postings.
    A portal that answered the endpoint with real content is never given a
    browser fallback — that is a duplicate scan, not a rescue.
    """
    source = SOURCES_BY_KEY[source_key]
    outcome = _fetch_direct_with_cap(source, direct_budget_seconds=_source_direct_budget_seconds(source))
    if outcome.jobs:
        return SourceResult(
            jobs=outcome.jobs,
            status="success",
            transport="direct",
            attempted_urls=(source.url,),
        )
    if outcome.no_active_jobs:
        reason = _classify_zero_jobs_reason(outcome.error_code, outcome.parsed, outcome.no_active_jobs)
        log.info("%s: zero-jobs audit reason=%s error_code=%s", source_key, reason, outcome.error_code or "-")
        return SourceResult(
            status="empty",
            transport="direct",
            error_code=f"{reason}:{outcome.error_code}" if outcome.error_code and reason != "EMPTY_REAL" else reason,
            attempted_urls=(source.url,),
        )

    # v68 per-source fallback ladder: before the browser is ever touched, a
    # source whose direct endpoint answered nothing real gets two cheap
    # public-reading steps — an embedded structured-data extraction from a
    # lightweight HTML GET (ld+json / __NEXT_DATA__, at most a few seconds)
    # and then the Jina public reader (a shared proxy that often sees what a
    # blocked client cannot). Playwright stays reserved for sources that are
    # actually JS-only and only after both cheaper steps returned nothing.
    ladder_outcome = None
    ladder_was_attempted = False
    if not outcome.jobs and (not outcome.no_active_jobs or outcome.error_code == "direct_budget_capped"):
        if outcome.parsed and _SCRIPT_RE.search(outcome.raw_html or ""):
            page_jobs, _ = _jobs_from_html(outcome.raw_html or "", source, base_url=source.url)
            if page_jobs:
                return SourceResult(jobs=page_jobs, status="success", transport="embedded_json", attempted_urls=(source.url,))
        # jina_result is None until the public reader actually runs — the
        # js_only/budget logic below must work for sources that never touch
        # the ladder (non-public_fallback) without an UnboundLocalError.
        jina_result = None
        ladder_was_attempted = False
        if source.public_fallback:
            # v69: the reader attempt is remembered even when it found
            # nothing — a non-None reader outcome means the public ladder
            # WAS attempted, and its honest no-listings answer is allowed
            # to close the book on this run without burning Playwright.
            # v70: ladder_was_attempted records the attempt for the fast-
            # browser cap below (flag declared above; set True here).
            ladder_was_attempted = True
            jina_result = _fetch_via_public_reader(source)
            if jina_result is not None and jina_result.jobs:
                return SourceResult(jobs=jina_result.jobs, status="success", transport="jina", attempted_urls=(source.url,))
            if jina_result is not None and jina_result.no_active_jobs:
                return SourceResult(status="empty", transport="jina", error_code="EMPTY_REAL:jina", attempted_urls=(source.url,))
            # v69: an honest reader answer that found nothing closes the book
            # without Playwright — but only when the reader actually READ
            # (parsed) or explicitly declared no listings. A reader that
            # FAILED to answer (jina_unavailable / too_large / parse_failed)
            # is not evidence of anything; a temporary reader outage must
            # never floor every JS-only bank, so the browser door stays
            # open for genuinely JS-only sources while the audit still
            # remembers the reader attempt.
            if jina_result is not None and (jina_result.parsed or jina_result.no_active_jobs):
                ladder_outcome = jina_result

    # Playwright is permitted only when the source is actually JS-only. An
    # endpoint that parsed real structure (parsed=True) but exposed no
    # listings genuinely has none — re-rendering the same page in a browser
    # cannot create jobs, and only burns budget. Same when the endpoint
    # already returned a hard HTTP failure: the portal is blocking clients,
    # and JS-render does not bypass server-side blocks.
    # v69: the public reader's no-listings answer is exhaustive evidence —
    # it reads the page through a pool that is not subject to the source's
    # own client-side blocks, so Playwright is skipped whenever the reader
    # actually ran (even with parsed=False): a JS-render of the same page
    # cannot create listings the reader did not see. A reader that FAILED
    # (jina_unavailable / jina_timeout — the reader itself could not answer)
    # is not evidence of anything: a temporary Jina outage must never floor
    # every JS-only bank, so an unsuccessful reader attempt leaves the
    # browser step available for genuinely JS-only sources.
    js_only = (
        source_key in _JS_ONLY_SOURCE_KEYS
        and not outcome.parsed
        and ladder_outcome is None
    )

    # v74: Egyptian recovery ladder — after the standard ladder answered
    # nothing, sources with registered alternative surfaces get two cheap
    # additional reads per URL: a direct GET (a DIFFERENT netloc is not the
    # same endpoint the circuit marked open) and then the public reader on
    # that URL.  This rescues the blocked-bank pattern from the run log
    # where the careers page itself answered nothing but the jobs live on
    # a sibling search UI.  Runs BEFORE the browser step so an honest
    # recovery answer (parsed=True or no listings found) can close the book
    # without burning any Playwright budget.
    ladder_steps: list[str] = ["direct"]
    if outcome.parsed and _SCRIPT_RE.search(outcome.raw_html or ""):
        ladder_steps.append("embedded_json")
    if ladder_was_attempted:
        ladder_steps.append("jina")
    recovery_outcomes: list[_Outcome] = []
    if not outcome.jobs and not outcome.no_active_jobs:
        for alt_url in _EGYPT_RECOVERY_URLS.get(source_key, ()):
            if not alt_url:
                continue
            # Direct GET of the alternate URL (cheap, may differ in netloc
            # from the blocked endpoint so it survives circuit-open).
            alt_direct = _Outcome([], parsed=False, error_code="")
            try:
                alt_result = get_text_result(alt_url, timeout=int(_FAST_ATTEMPT_TIMEOUT_SECONDS), max_retries=1)
                if alt_result.text:
                    alt_page_jobs, alt_parsed = _jobs_from_html(alt_result.text, source, base_url=alt_url)
                    alt_direct = _Outcome(alt_page_jobs, parsed=alt_parsed, no_active_jobs=alt_parsed and not alt_page_jobs)
                    if not alt_page_jobs and alt_parsed:
                        pass  # page read but no postings — fall through to reader
                    elif not alt_result.text:
                        alt_direct = _Outcome([], error_code=alt_result.error_code or "official_page_unavailable")
                else:
                    alt_direct = _Outcome([], error_code=alt_result.error_code or "official_page_unavailable")
            except Exception as exc:  # pragma: no cover - transport never blocks
                log.debug("%s: recovery direct on %s failed: %s", source_key, alt_url, exc)
                alt_direct = _Outcome([], error_code="recovery_transport_failed")
            if alt_direct.jobs:
                return SourceResult(
                    jobs=alt_direct.jobs, status="success", transport="alt_endpoint",
                    attempted_urls=(source.url, alt_url), ladder_steps=tuple(ladder_steps + ["alt_endpoint"]),
                )
            if alt_direct.no_active_jobs:
                recovery_outcomes.append(alt_direct)
                ladder_steps.append("alt_endpoint")
                continue
            # The alternate URL through the public reader — a different page
            # through a different IP pool than either the blocked endpoint
            # or the careers-page reader.
            reader_outcome = _fetch_via_public_reader_url(source, alt_url)
            if reader_outcome is not None and reader_outcome.jobs:
                return SourceResult(
                    jobs=reader_outcome.jobs, status="success", transport="jina_alt_endpoint",
                    attempted_urls=(source.url, alt_url), ladder_steps=tuple(ladder_steps + ["reader_alt"]),
                )
            if reader_outcome is not None and (reader_outcome.parsed or reader_outcome.no_active_jobs):
                recovery_outcomes.append(reader_outcome)
                ladder_steps.append("reader_alt")
            elif reader_outcome is not None:
                ladder_steps.append("reader_alt")
    # Pick the most recent recovery evidence for the final audit line so the
    # log shows where the honest no-listings verdict came from.
    if not outcome.jobs and recovery_outcomes and not any(o.jobs for o in recovery_outcomes):
        honest = any(o.no_active_jobs or o.parsed for o in recovery_outcomes)
        if honest:
            outcome = recovery_outcomes[-1]

    if source.browser_fallback and js_only and ladder_outcome is None:
        # v70: a proven-failing source only reaches the browser here when
        # the public reader could not answer — give it one fast attempt
        # instead of the full source deadline. An honest reader answer
        # (empty or parsed) already closed the book above; only an
        # unanswered reader leaves this door open, and even then the
        # source pays at most the fast cap.
        ladder_answered = jina_result is not None and (jina_result.parsed or jina_result.no_active_jobs)
        # v74: if the recovery ladder already produced honest evidence
        # (parsed=True or no_active_jobs), Playwright cannot create jobs
        # the reader already failed to see — skip it entirely.
        if any(o.parsed or o.no_active_jobs for o in recovery_outcomes):
            ladder_answered = True
            ladder_outcome = recovery_outcomes[-1]
        # v70: a proven-failing source (public_fallback) only reaches the
        # browser because the reader could not answer — it gets one FAST
        # attempt, never the full source deadline. An honest reader answer
        # already closed the book above; a source without the ladder
        # (healthy transport) keeps its normal JS-only budget.
        if source.public_fallback and ladder_was_attempted and not ladder_answered:
            browser_budget = min(_source_budget_seconds(source), _FAST_BROWSER_CAP_SECONDS)
        else:
            browser_budget = _source_budget_seconds(source)
        browser_outcome = _fetch_with_browser(source, budget_seconds=browser_budget)
        if browser_outcome.jobs:
            return SourceResult(
                jobs=browser_outcome.jobs,
                status="success",
                transport="playwright",
                attempted_urls=(source.url,),
            )
        if browser_outcome.no_active_jobs:
            reason = _classify_zero_jobs_reason(browser_outcome.error_code, browser_outcome.parsed, browser_outcome.no_active_jobs)
            log.info("%s: zero-jobs audit (playwright) reason=%s error_code=%s", source_key, reason, browser_outcome.error_code or "-")
            return SourceResult(
                status="empty",
                transport="playwright",
                error_code=f"{reason}:{browser_outcome.error_code}" if browser_outcome.error_code and reason != "EMPTY_REAL" else reason,
                attempted_urls=(source.url,),
            )
        if browser_outcome.error_code:
            outcome = browser_outcome
    # v69: when the ladder attempted public reading but nothing rescued the
    # source, the audit must say so (EMPTY_REAL or the reader's own code)
    # instead of recycling the original endpoint error — the endpoint may
    # have been merely transiently blocked while the reader already saw the
    # real page and found no listings.
    elif ladder_outcome is not None and ladder_outcome.error_code:
        outcome = ladder_outcome

    reason = _classify_zero_jobs_reason(outcome.error_code, outcome.parsed, False)
    log.info("%s: zero-jobs audit reason=%s error_code=%s parsed=%s", source_key, reason, outcome.error_code or "-", outcome.parsed)
    status = "parse_changed" if outcome.parsed else "blocked"
    return SourceResult(
        status=status,
        transport="direct",
        error_code=f"{reason}:{outcome.error_code}" if outcome.error_code else reason,
        attempted_urls=(source.url,),
        ladder_steps=tuple(ladder_steps),
    )


# v68 public-reader (Jina) cascade: capped, cached, and strictly cheaper
# than Playwright — the reader's own 8s timeout plus a small retry is the
# whole budget, so a failing reader never consumes a source's deadline.
_JINA_READER_URL_TEMPLATE = "https://r.jina.ai/{url}"
_JINA_PUBLIC_READER_HEADERS = {
    "Accept": "text/html",
    "X-Locale": "en",
}
_PUBLIC_READER_ATTEMPT_TIMEOUT_SECONDS = float(
    os.getenv("CAREERS_READER_TIMEOUT_SECONDS", "8")
)

# v74: per-source recovery ladder — Egyptian sources whose direct endpoint,
# embedded JSON, and careers-page reader ALL answered nothing get a second
# public-reader pass against alternative URLs that are known to expose the
# same jobs through a different surface (Workday search UIs, alternate
# careers paths).  The Jina reader sits in a different IP pool from the
# bot's exit, so an endpoint marked circuit-open for direct HTTP is NOT
# circuit-open for the reader — this is the rescue path the blocked banks
# (al_baraka, hdb, bank_abc, cib_egypt_wd, saib, vois, cybershield,
# elsewedy_electric, dubizzle) actually need.  URLs are tried in order;
# direct GET first (cheap when the netloc differs from the blocked one),
# then the Jina reader of the same URL.
_EGYPT_RECOVERY_URLS: dict[str, list[str]] = {
    # Workday Egyptian tenants: their public search UI (not the JSON API)
    "cib_egypt_wd": ["https://cibeg.wd1.myworkdayjobs.com/en-US/search", "https://cibeg.wd1.myworkdayjobs.com/en-US/cib_jobs"],
    "valeo_egypt": ["https://valeo.wd3.myworkdayjobs.com/en-US/search", "https://valeo.wd3.myworkdayjobs.com/en-US/valeo_jobs"],
    # Blocked Egyptian bank portals with an alternate careers surface
    "telecom_egypt": ["https://te.eg/wps/portal/te/Personal/Careers/jobs"],
    "banque_misr": ["https://www.banquemisr.com/en/careers/current-vacancies", "https://careers.banquemisr.com", "https://www.linkedin.com/company/banque-misr/jobs/"],
    "aaib": ["https://aaib.com.eg/en/careers/current-vacancies", "https://www.linkedin.com/company/aaibegypt/jobs/"],
    "adib_egypt": ["https://www.adib.com.eg/en/careers", "https://www.linkedin.com/company/adibegypt/jobs/"],
    "cib_egypt": ["https://www.cibeg.com/en/careers/our-openings", "https://www.cibeg.com/en/careers/apply", "https://www.linkedin.com/company/cibegypt/jobs/"],
    "qnb_egypt": ["https://www.qnb.com/en/group/careers", "https://www.linkedin.com/company/qnb-al-ahli/jobs/"],
    "banque_du_caire": ["https://www.bdc.com.eg/bdcwebsite/personal/careers.html/jobs", "https://www.linkedin.com/company/banque-du-caire/jobs/"],
    "bank_nxt": ["https://banknxt.com/careers/openings", "https://www.linkedin.com/company/banknxt/jobs/"],
    "emirates_nbd_egypt": ["https://www.emiratesnbd.com/en/egypt/careers", "https://www.linkedin.com/company/emirates-nbd/jobs/"],
    "hsbc_egypt": ["https://www.hsbc.com/en-eg/careers", "https://www.linkedin.com/company/hsbc/jobs/"],
    "mashreq_egypt": ["https://www.mashreq.com/egypt/careers/jobs", "https://www.linkedin.com/company/mashreq/jobs/"],
    "al_baraka_bank": ["https://www.albarakabank.com.eg/en/careers", "https://www.albarakabank.com.eg/careers", "https://www.linkedin.com/company/al-baraka-bank-egypt/jobs/"],
    "hdb": ["https://www.hdb-egypt.com/en/careers", "https://www.linkedin.com/company/housing-&-development-bank/jobs/"],
    "bank_abc": ["https://www.bankabc.com.eg/en/careers", "https://www.linkedin.com/company/bank-abc-in-egypt/jobs/"],
    "saib": ["https://www.saib.com.eg/en/careers", "https://www.linkedin.com/company/saib-bank/jobs/"],
    "vois": ["https://vois.com.eg/en/careers", "https://www.linkedin.com/company/vois/jobs/"],
    "cybershield": ["https://www.cybershield.com.eg/en/careers"],
    "etisalat_egypt": ["https://careers.etisalat.com.eg/jobs", "https://www.etisalat.com.eg/en/careers.html", "https://www.linkedin.com/company/etisalat-egypt/jobs/"],
    "itida": ["https://www.itida.gov.eg/en/careers/jobs", "https://www.linkedin.com/company/itida/jobs/"],
    "smart_village": ["https://www.smart-village.com/en/careers/jobs"],
    "we_jina": ["https://te.eg/wps/portal/te/Personal/Careers", "https://www.linkedin.com/company/telecom-egypt/jobs/"],
    "raya": ["https://www.raya.com.eg/en/careers/jobs", "https://www.linkedin.com/company/raya/jobs/"],
    "nbe": ["https://www.nbe.com.eg/en/Pages/Default.aspx/careers", "https://www.linkedin.com/company/national-bank-of-egypt/jobs/"],
    # Non-Egyptian sources the user flagged with the same block pattern
    "dubizzle": ["https://dubizzle.com/jobs/search/"],
    "elsewedy_electric": ["https://www.elsewedy.com/en/careers", "https://careers.elsewedy.com"],
    "qiddiya": ["https://qiddiya.com/en/careers/jobs"],
    "oracle_hcm": [],  # never registered — placeholder kept explicit
}

# v74: share of a source's budget the DIRECT step may consume before the
# fallback ladder gets the rest.  A failing bank must not spend its whole
# 45s on a portal that will never answer; env CAREERS_DIRECT_ATTEMPT_CAP=0.3
# means "up to 30% direct, the remainder is reserved for the ladder and the
# (rarely-reached) browser step."  Kept configurable because the user
# explicitly forbids raising timeouts as the fix.
_DIRECT_ATTEMPT_CAP = float(os.getenv("CAREERS_DIRECT_ATTEMPT_CAP", "0.3"))


def _fetch_via_public_reader_url(source: CareerSource, url: str) -> _Outcome | None:
    """v74: public-reader pass against an arbitrary alternate URL (not the
    source's canonical careers page).  Same reader contract as
    ``_fetch_via_public_reader``: returns ``None`` only when the reader step
    could not be attempted at all; an empty/honest answer is an ``_Outcome``."""
    reader_url = _JINA_READER_URL_TEMPLATE.format(url=url)
    html: str | None = None
    try:
        html = get_text(
            reader_url, headers=_JINA_PUBLIC_READER_HEADERS,
            timeout=int(_PUBLIC_READER_ATTEMPT_TIMEOUT_SECONDS),
            max_retries=1,
        )
    except Exception as exc:  # pragma: no cover - escalates instead
        log.debug("%s: recovery reader transport failed on %s: %s", source.key, url, exc)
        return _Outcome([], error_code="jina_unavailable")
    if not html:
        return _Outcome([], error_code="jina_unavailable")
    if len(html) > 5 * 1024 * 1024:
        return _Outcome([], parsed=False, error_code="jina_too_large")
    try:
        page_jobs, parsed = _jobs_from_html(html, source, base_url=url)
    except Exception as exc:  # pragma: no cover
        log.debug("%s: recovery reader parse failed on %s: %s", source.key, url, exc)
        return _Outcome([], parsed=False, error_code="jina_parse_failed")
    if page_jobs:
        return _Outcome(_dedupe_jobs(page_jobs), parsed=parsed)
    return _Outcome([], parsed=parsed, no_active_jobs=parsed and not page_jobs, error_code="jina_empty")


def _fetch_via_public_reader(source: CareerSource) -> _Outcome | None:
    """v68: read the source's official page through the public Jina reader as
    the middle step of the fallback ladder (endpoint → embedded JSON →
    public reader → browser).  The reader is what the blocked-client
    sources in the v68 diagnosis actually needed: the same page that times
    out or resets for the bot's exit IP often resolves cleanly for the
    reader's pool.  Failures here are silent — the caller escalates to the
    browser step or reports the source honestly.

    Returns ``None`` when the reader step could not be attempted at all
    (never happened), so ``fetch_source`` can distinguish "tried and empty"
    from "not tried".
    """
    reader_url = _JINA_READER_URL_TEMPLATE.format(url=source.url)
    html: str | None = None
    try:
        html = get_text(
            reader_url, headers=_JINA_PUBLIC_READER_HEADERS,
            timeout=int(_PUBLIC_READER_ATTEMPT_TIMEOUT_SECONDS),
            max_retries=1,
        )
    except Exception as exc:  # pragma: no cover - defensive; escalates instead
        log.debug("%s: public reader transport failed: %s", source.key, exc)
        return _Outcome([], error_code="jina_unavailable")
    if not html:
        return _Outcome([], error_code="jina_unavailable")
    if len(html) > 5 * 1024 * 1024:
        # A reader response that grew past a sane page size is noise, not
        # rescue — skip extraction and report honestly.
        return _Outcome([], parsed=False, error_code="jina_too_large")
    try:
        page_jobs, parsed = _jobs_from_html(html, source, base_url=source.url)
    except Exception as exc:  # pragma: no cover - parse failures never block
        log.debug("%s: public reader parse failed: %s", source.key, exc)
        return _Outcome([], parsed=False, error_code="jina_parse_failed")
    if page_jobs:
        return _Outcome(_dedupe_jobs(page_jobs), parsed=parsed)
    return _Outcome([], parsed=parsed, no_active_jobs=parsed and not page_jobs,
                    error_code="jina_empty")


def _fetch_direct(source: CareerSource) -> _Outcome:
    if source.backend == "greenhouse":
        return _fetch_greenhouse(source)
    if source.backend == "workday":
        return _fetch_workday(source)
    if source.backend == "ashby":
        return _fetch_ashby(source)
    if source.backend == "amazon":
        return _fetch_amazon(source)
    return _fetch_html_pages(source)


def _fetch_greenhouse(source: CareerSource) -> _Outcome:
    data = get_json(f"https://api.greenhouse.io/v1/boards/{source.board}/jobs?content=true", timeout=40)
    if not isinstance(data, dict) or "jobs" not in data:
        return _Outcome([], error_code="greenhouse_unavailable")
    rows = data.get("jobs")
    if not isinstance(rows, list):
        return _Outcome([], parsed=True, error_code="greenhouse_shape_changed")
    jobs = _dedupe_jobs(_jobs_from_payload(rows, source))
    return _Outcome(jobs, parsed=True, no_active_jobs=not rows)


def _workday_endpoint(source: CareerSource) -> str:
    parsed = urlparse(source.url)
    return f"{parsed.scheme}://{parsed.netloc}/wday/cxs/{source.tenant}/{source.site}/jobs"


def _fetch_workday(source: CareerSource) -> _Outcome:
    endpoint = _workday_endpoint(source)
    offset = 0
    all_jobs: list[Job] = []
    parsed_any = False
    total: int | None = None
    while True:
        data = post_json(
            endpoint,
            payload={"appliedFacets": {}, "limit": source.page_size, "offset": offset, "searchText": ""},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=60,
        )
        if not isinstance(data, dict):
            return _Outcome(_dedupe_jobs(all_jobs), parsed=parsed_any, error_code="workday_unavailable")
        rows = data.get("jobPostings")
        if not isinstance(rows, list):
            return _Outcome(_dedupe_jobs(all_jobs), parsed=True, error_code="workday_shape_changed")
        parsed_any = True
        if total is None:
            value = data.get("total")
            total = value if isinstance(value, int) and value >= 0 else None
        all_jobs.extend(_jobs_from_payload(rows, source, base_url=source.url))
        offset += len(rows)
        if not rows or len(rows) < source.page_size or (total is not None and offset >= total):
            break
    return _Outcome(_dedupe_jobs(all_jobs), parsed=parsed_any, no_active_jobs=parsed_any and not all_jobs)


def _fetch_ashby(source: CareerSource) -> _Outcome:
    # Ashby exposes a public board payload.  Some installations disable this
    # endpoint; in that case the official board page remains the fallback.
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{source.board}", timeout=40)
    if isinstance(data, dict):
        rows = data.get("jobs") or data.get("jobPostings")
        if isinstance(rows, list):
            jobs = _dedupe_jobs(_jobs_from_payload(rows, source, base_url=source.url))
            return _Outcome(jobs, parsed=True, no_active_jobs=not rows)
    return _fetch_html_pages(source)


def _fetch_amazon(source: CareerSource) -> _Outcome:
    page = 1
    all_jobs: list[Job] = []
    parsed_any = False
    while True:
        data = get_json(
            source.url,
            params={"base_query": source.query, "loc_query": "", "result_limit": 100, "page": page, "sort": "recent"},
            timeout=60,
        )
        if not isinstance(data, dict):
            return _Outcome(_dedupe_jobs(all_jobs), parsed=parsed_any, error_code="amazon_unavailable")
        rows = data.get("jobs")
        if not isinstance(rows, list):
            return _Outcome(_dedupe_jobs(all_jobs), parsed=True, error_code="amazon_shape_changed")
        parsed_any = True
        all_jobs.extend(_jobs_from_payload(rows, source, base_url="https://www.amazon.jobs"))
        if not rows or len(rows) < 100:
            break
        page += 1
    return _Outcome(_dedupe_jobs(all_jobs), parsed=parsed_any, no_active_jobs=parsed_any and not all_jobs)


def _page_url(source: CareerSource, page: int) -> str:
    if not source.page_param or page == source.page_start:
        return source.url
    parsed = urlparse(source.url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params[source.page_param] = str(page)
    return urlunparse(parsed._replace(query=urlencode(params)))


def _fetch_html_pages(source: CareerSource, budget_seconds: float | None = None) -> _Outcome:
    page = source.page_start
    all_jobs: list[Job] = []
    parsed_any = False
    raw_html: str = ""
    seen_page_fingerprints: set[tuple[str, ...]] = set()

    # v64: transport errors (connection refused/reset, dead portal) stop the
    # page loop immediately after one short retry with the same short cap —
    # keeping the socket open at the default 25s per page is what let
    # connectionerror pileups burn 20-60s on dead banks in the 2026-08-17
    # runs.  Content that arrives stays paginated as before.
    page_transport_failures = 0
    t0 = time.monotonic()
    while True:
        if budget_seconds is not None and (time.monotonic() - t0) >= budget_seconds:
            # v76: the direct page loop stopped at its wall-clock cap so
            # the fallback ladder (alt endpoints + public reader) keeps
            # the rest of the source budget instead of timing out entirely.
            log.debug("%s: direct page loop capped at %.1fs, ladder takes over", source.key, budget_seconds)
            return _Outcome(_dedupe_jobs(all_jobs), parsed=parsed_any, error_code="direct_budget_capped", raw_html=raw_html)
        result = get_text_result(_page_url(source, page), timeout=int(_FAST_ATTEMPT_TIMEOUT_SECONDS), max_retries=1)
        if result.text and page == source.page_start:
            # v68: keep the first page's raw HTML so the fallback ladder can
            # re-extract embedded structured data (ld+json / __NEXT_DATA__)
            # before escalating to the public reader.
            raw_html = raw_html or result.text
        if not result.text:
            page_transport_failures += 1
            if page_transport_failures > 1:
                return _Outcome(_dedupe_jobs(all_jobs), parsed=parsed_any, error_code=result.error_code or "official_page_unavailable")
            if page > source.page_start:
                # First page answered (parsed already happened); a later
                # page failing to connect does not invalidate the jobs we
                # already have, but it also does not deserve a long retry.
                return _Outcome(_dedupe_jobs(all_jobs), parsed=parsed_any, error_code=result.error_code or "official_page_unavailable")
            result = get_text_result(_page_url(source, page), timeout=int(_FAST_ATTEMPT_SECOND_CAP_SECONDS), max_retries=1)
        if not result.text:
            return _Outcome(_dedupe_jobs(all_jobs), parsed=parsed_any, error_code=result.error_code or "official_page_unavailable")
        page_jobs, parsed = _jobs_from_html(result.text, source, base_url=source.url)
        parsed_any = parsed_any or parsed
        fingerprint = tuple(sorted(job.url_id or job.unique_id for job in page_jobs))
        if fingerprint in seen_page_fingerprints:
            break
        seen_page_fingerprints.add(fingerprint)
        all_jobs.extend(page_jobs)
        if not source.page_param or not page_jobs:
            break
        if page - source.page_start + 1 >= source.max_pages:
            log.info(
                "%s: hit max_pages=%d safety cap, stopping pagination",
                source.key, source.max_pages,
            )
            break
        page += 1

    jobs = _dedupe_jobs(all_jobs)
    return _Outcome(jobs, parsed=parsed_any, no_active_jobs=parsed_any and not jobs, raw_html=raw_html)


def _fetch_with_browser(source: CareerSource, *, budget_seconds: float | None = None) -> _Outcome:
    """Render only after a direct public-data request failed.

    The import and browser startup are deliberately lazy so normal JSON/ATS
    connectors do not pay a browser cost.  ``budget_seconds`` is the
    per-source ceiling the browser render borrows — Egyptian priority
    sources get a dedicated 90s ceiling so a JS-only careers SPA is never
    killed by the generic 40s playwright cap.
    """
    budget_seconds = budget_seconds or _source_budget_seconds(source)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _Outcome([], error_code="playwright_unavailable")

    with _BROWSER_LOCK:
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page(locale="en-US")
                    page_number = source.page_start
                    start_at = time.monotonic()
                    all_jobs: list[Job] = []
                    parsed_any = False
                    page_fingerprints: set[tuple[str, ...]] = set()
                    # v64: every Playwright navigation is capped at 15s per
                    # page regardless of the source's total ceiling — a bank
                    # SPA that cannot finish its JS bundle in 15s will not
                    # finish it in 60s either, and the 15s cap is what cut
                    # the observed 46-89s per failed bank down to a fixed
                    # known cost.  Startup time still counts against the
                    # source's own ceiling.
                    # v67: abort-if-no-jobs — if the session has produced no
                    # usable job within PLAYWRIGHT_ABORT_AFTER_SECONDS,
                    # stop navigating.  The site clearly renders a page but
                    # no parseable listings; letting it run to the 45s
                    # deadline is pure budget waste (this is exactly what
                    # produced 13 source_deadline results in the 2026-08-17
                    # run).  Jobs emitted BEFORE the abort are still kept.
                    abort_after_seconds = config.PLAYWRIGHT_ABORT_AFTER_SECONDS
                    first_job_emitted_at: float | None = None
                    page.set_default_timeout(15000)
                    while True:
                        # Keep every JS navigation inside the source's own
                        # ceiling.  A direct attempt may already have
                        # consumed part of that ceiling, so never let a
                        # browser fallback borrow time from later sources.
                        local_remaining = budget_seconds - (time.monotonic() - start_at)
                        remaining_seconds = min(local_remaining, source_remaining())
                        if remaining_seconds <= 0.05:
                            return _Outcome(
                                _dedupe_jobs(all_jobs), parsed=parsed_any,
                                error_code="playwright_source_deadline",
                            )
                        page.goto(
                            _page_url(source, page_number),
                            wait_until="networkidle",
                            timeout=max(50, min(15000, int(remaining_seconds * 1000))),
                        )
                        html = page.content()
                        jobs, parsed = _jobs_from_html(html, source, base_url=source.url)
                        parsed_any = parsed_any or parsed
                        if jobs and first_job_emitted_at is None:
                            first_job_emitted_at = time.monotonic() - start_at
                        fingerprint = tuple(sorted(job.url_id or job.unique_id for job in jobs))
                        if fingerprint in page_fingerprints:
                            break
                        page_fingerprints.add(fingerprint)
                        all_jobs.extend(jobs)
                        if not source.page_param or not jobs:
                            # v67: first page rendered with nothing parseable —
                            # if no job has been emitted within the abort
                            # window the session is done; do not keep paying
                            # for empty navigations.
                            elapsed_since_start = time.monotonic() - start_at
                            if first_job_emitted_at is None and elapsed_since_start >= abort_after_seconds:
                                log.info(
                                    "%s: no usable job within %.0fs of browser "
                                    "session (%.0fs elapsed) — aborting the "
                                    "Playwright pass early (kept %d partial jobs)",
                                    source.key, abort_after_seconds,
                                    elapsed_since_start, len(all_jobs),
                                )
                                if all_jobs:
                                    return _Outcome(
                                        _dedupe_jobs(all_jobs), parsed=parsed_any,
                                        no_active_jobs=False,
                                    )
                                return _Outcome(
                                    [], parsed=parsed_any, no_active_jobs=parsed_any,
                                    error_code="official_page_empty",
                                )
                            break
                        if page_number - source.page_start + 1 >= source.max_pages:
                            log.info(
                                "%s: hit max_pages=%d safety cap, stopping pagination",
                                source.key, source.max_pages,
                            )
                            break
                        page_number += 1
                finally:
                    browser.close()
        except Exception as exc:  # Browser failures are reported, never hidden.
            log.info("%s browser fallback unavailable: %s", source.key, type(exc).__name__)
            return _Outcome([], error_code=f"playwright_{type(exc).__name__.lower()}")
    jobs = _dedupe_jobs(all_jobs)
    # v67: a Playwright session that finishes with zero jobs and zero parse
    # evidence is a known-empty source — report it explicitly instead of a
    # silent success (silent-zero is exactly how the 9 bottleneck banks hid
    # behind deadline-less runs in 2026-08-17).
    if not jobs:
        if parsed_any:
            return _Outcome([], parsed=parsed_any, no_active_jobs=True)
        return _Outcome(
            [], parsed=False, no_active_jobs=True,
            error_code="official_page_empty",
        )
    return _Outcome(jobs, parsed=parsed_any, no_active_jobs=False)


def _jobs_from_html(html: str, source: CareerSource, *, base_url: str) -> tuple[list[Job], bool]:
    jobs: list[Job] = []
    parsed = False
    for raw in _SCRIPT_RE.findall(html):
        raw = unescape(raw).strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        parsed = True
        jobs.extend(_jobs_from_payload(payload, source, base_url=base_url))

    # Some official job portals render only cards.  This narrow fallback only
    # accepts job-detail links, avoiding navigation and marketing links.
    if not jobs:
        anchors = _jobs_from_job_anchors(html, source, base_url)
        if anchors:
            parsed = True
            jobs.extend(anchors)
    return _dedupe_jobs(jobs), parsed


def _jobs_from_job_anchors(html: str, source: CareerSource, base_url: str) -> list[Job]:
    jobs: list[Job] = []
    for href, raw_title in _ANCHOR_RE.findall(html):
        if not _JOB_LINK_RE.search(href):
            continue
        title = _clean_text(raw_title)
        if len(title) < 4 or len(title) > 240 or title.lower() in _SKIP_TITLES:
            continue
        jobs.append(_make_job(source, title=title, url=urljoin(base_url, unescape(href))))
    return jobs


def _jobs_from_payload(payload: Any, source: CareerSource, *, base_url: str = "") -> list[Job]:
    jobs: list[Job] = []
    seen_objects: set[int] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            marker = id(value)
            if marker in seen_objects:
                return
            seen_objects.add(marker)
            job = _job_from_mapping(value, source, base_url)
            if job is not None:
                jobs.append(job)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    return jobs


def _job_from_mapping(row: dict[str, Any], source: CareerSource, base_url: str) -> Job | None:
    kind = row.get("@type")
    is_job_posting = kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind)
    title = _value(row, "title", "jobTitle", "displayName", "requisitionTitle", "job_title")
    if not title and is_job_posting:
        title = _value(row, "name")
    if not title or len(title) > 240 or title.lower() in _SKIP_TITLES:
        return None

    raw_url = _value(row, "absolute_url", "url", "externalUrl", "applyUrl", "jobUrl", "job_path", "jobPath", "detailUrl", "externalPath")
    identifier = _value(row, "id", "jobId", "jobReqId", "requisitionId", "identifier", "bulletFields")
    location = _location_from(row)
    # A generic title/name alone is not evidence of a posting.  JSON-LD
    # JobPosting is explicit; other records need an identifier, location, or
    # application URL.
    if not is_job_posting and not (raw_url or identifier or location):
        return None
    if raw_url:
        url = urljoin(base_url or source.url, raw_url)
    elif identifier:
        url = _identifier_url(source, identifier)
    else:
        return None

    company = _company_from(row) or source.company
    description = _value(row, "description", "jobDescription", "content", "summary")
    posted_date = _parse_date(_value(row, "datePosted", "postedDate", "postedOn", "posted_at", "updated_at", "updatedAt", "createdAt", "publishedDate"))
    return _make_job(
        source,
        title=title,
        company=company,
        location=location,
        url=url,
        description=description,
        posted_date=posted_date,
    )


def _identifier_url(source: CareerSource, identifier: str) -> str:
    if source.backend == "greenhouse":
        return f"https://boards.greenhouse.io/{source.board}/jobs/{identifier}"
    if source.backend == "amazon":
        return f"https://www.amazon.jobs/en/jobs/{identifier}"
    return f"{source.url.rstrip('/')}/job/{identifier}"


def _value(row: dict[str, Any], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if isinstance(value, str):
            clean = _clean_text(value)
            if clean:
                return clean
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, dict):
            nested = _value(value, "name", "label", "value", "text")
            if nested:
                return nested
        if isinstance(value, list):
            values = [_clean_text(str(item)) for item in value if isinstance(item, (str, int, float))]
            if values:
                return ", ".join(values)
    return ""


def _company_from(row: dict[str, Any]) -> str:
    value = row.get("hiringOrganization") or row.get("company") or row.get("companyName")
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, dict):
        return _value(value, "name", "displayName")
    return ""


def _location_from(row: dict[str, Any]) -> str:
    value = row.get("jobLocation") or row.get("location") or row.get("locationsText") or row.get("locationName") or row.get("location_name")
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, list):
        values = [_location_from({"location": item}) for item in value]
        return ", ".join(v for v in values if v)
    if isinstance(value, dict):
        address = value.get("address")
        if isinstance(address, dict):
            parts = [_value(address, "addressLocality"), _value(address, "addressRegion"), _value(address, "addressCountry")]
            place = ", ".join(part for part in parts if part)
            if place:
                return place
        return _value(value, "name", "displayName", "label", "city")
    return ""


def _make_job(
    source: CareerSource,
    *,
    title: str,
    url: str,
    company: str | None = None,
    location: str = "",
    description: str = "",
    posted_date: datetime | None = None,
) -> Job:
    location = _clean_text(location) or _default_location(source)
    description = _clean_text(description)
    text = f"{title} {location} {description}".lower()
    return Job(
        title=_clean_text(title),
        company=_clean_text(company or source.company),
        location=location,
        url=url,
        source=source.key,
        source_key=source.key,
        original_source=f"{source.name} (official careers)",
        posted_date=posted_date,
        description=description,
        tags=["official_careers", source.backend, source.key],
        is_remote="remote" in text or "work from home" in text,
        extraction_method=f"official:{source.backend}",
        geo_hint=source.geo_hint,
    )


def _default_location(source: CareerSource) -> str:
    if source.geo_hint == "egypt":
        return "Egypt"
    if source.geo_hint == "gulf":
        return "Saudi Arabia / Gulf"
    return "Global"


def _parse_date(raw: str) -> datetime | None:
    raw = _clean_text(raw)
    if not raw:
        return None
    try:
        value = raw.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        pass
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw[:10], pattern)
        except ValueError:
            continue
    return None


def _clean_text(value: str) -> str:
    text = unescape(value or "")
    text = _TAG_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def _dedupe_jobs(jobs: Iterable[Job]) -> list[Job]:
    unique: list[Job] = []
    seen: set[str] = set()
    for job in jobs:
        if not job.title or not job.url or not job.company:
            continue
        key = job.url_id or job.unique_id
        if key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique
