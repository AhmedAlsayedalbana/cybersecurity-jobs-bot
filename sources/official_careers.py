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
    CareerSource("telecom_egypt", "WE (Telecom Egypt) Careers", "Telecom Egypt", "egypt", "html", "https://te.eg/wps/portal/te/Personal/Careers", "egypt", page_param="page", browser_fallback=True),
    CareerSource("banque_misr", "Banque Misr Careers", "Banque Misr", "egypt", "html", "https://www.banquemisr.com/en/careers", "egypt", page_param="page", browser_fallback=True),
    CareerSource("nbe", "National Bank of Egypt Careers", "National Bank of Egypt", "egypt", "html", "https://www.nbe.com.eg/NBE/E/#/EN/Employment", "egypt", page_param="page", browser_fallback=True),
    CareerSource("cib_egypt", "CIB Careers", "Commercial International Bank", "egypt", "html", "https://www.cibeg.com/en/careers", "egypt", page_param="page", browser_fallback=True),
    CareerSource("qnb_egypt", "QNB Egypt Careers", "QNB Egypt", "egypt", "html", "https://www.qnb.com/sites/qnb/qnbegypt/page/en/encareers.html", "egypt", page_param="page", browser_fallback=True),
    CareerSource("banque_du_caire", "Banque du Caire Careers", "Banque du Caire", "egypt", "html", "https://www.bdc.com.eg/bdcwebsite/personal/careers.html", "egypt", page_param="page", browser_fallback=True),
    CareerSource("valeo_egypt", "Valeo Egypt Careers", "Valeo", "egypt", "workday", "https://valeo.wd3.myworkdayjobs.com/en-US/valeo_jobs", "egypt", tenant="valeo", site="valeo_jobs"),
    CareerSource("ibm_egypt", "IBM Egypt Careers", "IBM", "egypt", "html", "https://www.ibm.com/careers/search", "egypt", page_param="page"),
    CareerSource("microsoft_egypt", "Microsoft Egypt Careers", "Microsoft", "egypt", "eightfold", "https://apply.careers.microsoft.com/careers", "egypt", page_param="page"),
    CareerSource("siemens_egypt", "Siemens Egypt Careers", "Siemens", "egypt", "html", "https://jobs.siemens.com/en_US/externaljobs/SearchJobs", "egypt", page_param="page"),
    # ── Egypt blocked-source fallbacks ─────────────────────────────────────
    CareerSource("cib_egypt_wd", "CIB Careers (Workday)", "Commercial International Bank", "egypt", "workday", "https://cibeg.wd1.myworkdayjobs.com/en-US/cib_jobs", "egypt", tenant="cibeg", site="cib_jobs"),
    CareerSource("nbe_html", "NBE Careers (HTML)", "National Bank of Egypt", "egypt", "html", "https://www.nbe.com.eg/en/Pages/Default.aspx", "egypt", page_param="page"),
    CareerSource("we_jina", "WE Telecom Egypt (Alt)", "Telecom Egypt", "egypt", "html", "https://te.eg/wps/portal/te/Personal/Careers/!ut/p/z1/", "egypt", page_param="page", browser_fallback=True),
    CareerSource("qnb_global", "QNB Global Careers", "QNB Egypt", "egypt", "html", "https://careers.qnb.com/", "egypt", page_param="page", browser_fallback=True),
    # ── Egypt banking sector ────────────────────────────────────────────────
    CareerSource("aaib", "AAIB Careers", "Arab African International Bank", "egypt", "html", "https://aaib.com.eg/en/careers", "egypt", page_param="page", browser_fallback=True),
    CareerSource("credit_agricole_egypt", "Crédit Agricole Egypt Careers", "Crédit Agricole Egypt", "egypt", "html", "https://www.ca-egypt.com/en/careers", "egypt", page_param="page", browser_fallback=True),
    CareerSource("hsbc_egypt", "HSBC Egypt Careers", "HSBC Egypt", "egypt", "html", "https://www.hsbc.com/careers", "egypt", page_param="page"),
    CareerSource("adib_egypt", "ADIB Egypt Careers", "Abu Dhabi Islamic Bank Egypt", "egypt", "html", "https://www.adib.com.eg/careers", "egypt", page_param="page", browser_fallback=True),
    CareerSource("fabmisr", "FABMISR Careers", "FABMISR", "egypt", "html", "https://www.fabmisr.com.eg/careers", "egypt", page_param="page", browser_fallback=True),
    CareerSource("hdb", "HDB Careers", "Housing and Development Bank", "egypt", "html", "https://www.hdb-egypt.com/careers", "egypt", page_param="page", browser_fallback=True),
    CareerSource("emirates_nbd_egypt", "Emirates NBD Egypt Careers", "Emirates NBD Egypt", "egypt", "html", "https://www.emiratesnbd.com/egypt/careers", "egypt", page_param="page", browser_fallback=True),
    CareerSource("mashreq_egypt", "Mashreq Egypt Careers", "Mashreq Egypt", "egypt", "html", "https://www.mashreq.com/egypt/careers", "egypt", page_param="page", browser_fallback=True),
    CareerSource("al_baraka_bank", "Al Baraka Bank Careers", "Al Baraka Bank", "egypt", "html", "https://www.albarakabank.com.eg/careers", "egypt", page_param="page", browser_fallback=True),
    CareerSource("bank_abc", "Bank ABC Careers", "Bank ABC", "egypt", "html", "https://www.bankabc.com.eg/careers", "egypt", page_param="page", browser_fallback=True),
    CareerSource("saib", "SAIB Careers", "SAIB", "egypt", "html", "https://www.saib.com.eg/careers", "egypt", page_param="page", browser_fallback=True),
    CareerSource("bank_nxt", "Bank NXT Careers", "Bank NXT", "egypt", "html", "https://banknxt.com/careers", "egypt", page_param="page", browser_fallback=True),
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
    """Per-source cooperative ceiling, honoring the Egyptian priority budget."""
    if source.key in config.EGYPT_PRIORITY_SOURCE_KEYS:
        return float(config.EGYPT_PRIORITY_SOURCE_TIMEOUT_SECONDS)
    return float(config.PLAYWRIGHT_SOURCE_TIMEOUT_SECONDS)


def fetch_source(source_key: str) -> SourceResult:
    """Fetch one official source and report an honest health status.

    Official endpoint/API comes FIRST.  Playwright is reserved for sources
    whose careers page is genuinely JavaScript-only: a SPA that an HTTP
    client cannot parse and whose anchor links do not carry job postings.
    A portal that answered the endpoint with real content is never given a
    browser fallback — that is a duplicate scan, not a rescue.
    """
    source = SOURCES_BY_KEY[source_key]
    outcome = _fetch_direct(source)
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

    # Playwright is permitted only when the source is actually JS-only. An
    # endpoint that parsed real structure (parsed=True) but exposed no
    # listings genuinely has none — re-rendering the same page in a browser
    # cannot create jobs, and only burns budget. Same when the endpoint
    # already returned a hard HTTP failure: the portal is blocking clients,
    # and JS-render does not bypass server-side blocks.
    js_only = (
        source_key in _JS_ONLY_SOURCE_KEYS
        and not outcome.parsed
    )
    if source.browser_fallback and js_only:
        browser_outcome = _fetch_with_browser(source, budget_seconds=_source_budget_seconds(source))
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

    reason = _classify_zero_jobs_reason(outcome.error_code, outcome.parsed, False)
    log.info("%s: zero-jobs audit reason=%s error_code=%s parsed=%s", source_key, reason, outcome.error_code or "-", outcome.parsed)
    status = "parse_changed" if outcome.parsed else "blocked"
    return SourceResult(
        status=status,
        transport="direct",
        error_code=f"{reason}:{outcome.error_code}" if outcome.error_code else reason,
        attempted_urls=(source.url,),
    )


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
    data = get_json(f"https://api.greenhouse.io/v1/boards/{source.board}/jobs?content=true", timeout=20)
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
            timeout=30,
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
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{source.board}", timeout=20)
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
            timeout=30,
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


def _fetch_html_pages(source: CareerSource) -> _Outcome:
    page = source.page_start
    all_jobs: list[Job] = []
    parsed_any = False
    seen_page_fingerprints: set[tuple[str, ...]] = set()

    while True:
        result = get_text_result(_page_url(source, page), timeout=25, max_retries=2)
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
    return _Outcome(jobs, parsed=parsed_any, no_active_jobs=parsed_any and not jobs)


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
                    while True:
                        # Keep every JS navigation inside the source's own
                        # ceiling (generic 40s, Egyptian priority 90s).  A
                        # direct attempt may already have consumed part of
                        # that ceiling, so never let a browser fallback
                        # borrow time from later sources.
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
                            timeout=max(50, min(
                                config.PLAYWRIGHT_NAVIGATION_TIMEOUT_MS,
                                int(remaining_seconds * 1000),
                            )),
                        )
                        html = page.content()
                        jobs, parsed = _jobs_from_html(html, source, base_url=source.url)
                        parsed_any = parsed_any or parsed
                        fingerprint = tuple(sorted(job.url_id or job.unique_id for job in jobs))
                        if fingerprint in page_fingerprints:
                            break
                        page_fingerprints.add(fingerprint)
                        all_jobs.extend(jobs)
                        if not source.page_param or not jobs:
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
    return _Outcome(jobs, parsed=parsed_any, no_active_jobs=parsed_any and not jobs)


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
