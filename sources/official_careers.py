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
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from models import Job
from sources.http_utils import get_json, get_text_result, post_json
from sources.marketplace_sources import SourceResult

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
    CareerSource("semgrep", "Semgrep Careers", "Semgrep", "core", "ashby", "https://jobs.ashbyhq.com/semgrep", "global", board="semgrep"),
    CareerSource("vanta", "Vanta Careers", "Vanta", "core", "ashby", "https://jobs.ashbyhq.com/vanta", "global", board="vanta"),
    CareerSource("weaviate", "Weaviate Careers", "Weaviate", "core", "ashby", "https://jobs.ashbyhq.com/weaviate", "global", board="weaviate"),
    CareerSource("bugcrowd", "Bugcrowd Careers", "Bugcrowd", "core", "greenhouse", "https://boards.greenhouse.io/bugcrowd", "global", board="bugcrowd"),
    CareerSource("cloudflare", "Cloudflare Careers", "Cloudflare", "core", "greenhouse", "https://boards.greenhouse.io/cloudflare", "global", board="cloudflare"),
    CareerSource("cato_networks", "Cato Networks Careers", "Cato Networks", "core", "greenhouse", "https://boards.greenhouse.io/catonetworks", "global", board="catonetworks"),
    CareerSource("mattermost", "Mattermost Careers", "Mattermost", "core", "greenhouse", "https://boards.greenhouse.io/mattermost", "global", board="mattermost"),
    CareerSource("sumo_logic", "Sumo Logic Careers", "Sumo Logic", "core", "greenhouse", "https://boards.greenhouse.io/sumologic", "global", board="sumologic"),
    CareerSource("cockroach_labs", "Cockroach Labs Careers", "Cockroach Labs", "core", "greenhouse", "https://boards.greenhouse.io/cockroachlabs", "global", board="cockroachlabs"),
    CareerSource("crowdstrike", "CrowdStrike Careers", "CrowdStrike", "core", "workday", "https://crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers", "global", tenant="crowdstrike", site="crowdstrikecareers"),
    CareerSource("palo_alto_networks", "Palo Alto Networks Careers", "Palo Alto Networks", "core", "workday", "https://paloaltonetworks.wd5.myworkdayjobs.com/en-US/panwexternalcareers", "global", tenant="paloaltonetworks", site="panwexternalcareers"),
    CareerSource("fortinet", "Fortinet Careers", "Fortinet", "core", "oracle_hcm", "https://edel.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001/jobs", "global", page_param="page"),
    CareerSource("rapid7", "Rapid7 Careers", "Rapid7", "core", "html", "https://careers.rapid7.com/jobs/search", "global", page_param="page"),
    CareerSource("watchguard", "WatchGuard Careers", "WatchGuard", "core", "lever", "https://jobs.lever.co/watchguard", "global", board="watchguard"),
    CareerSource("coalfire", "Coalfire Careers", "Coalfire", "core", "lever", "https://jobs.lever.co/coalfire", "global", board="coalfire"),
    CareerSource("palantir", "Palantir Careers", "Palantir", "core", "lever", "https://jobs.lever.co/palantir", "global", board="palantir"),
    CareerSource("lumin_digital", "Lumin Digital Careers", "Lumin Digital", "core", "lever", "https://jobs.lever.co/LuminDigital", "global", board="LuminDigital"),
    CareerSource("true_zero_technologies", "True Zero Technologies Careers", "True Zero Technologies", "core", "lever", "https://jobs.lever.co/truezerotech", "global", board="truezerotech"),
    CareerSource("tenable", "Tenable Careers", "Tenable", "core", "greenhouse", "https://boards.greenhouse.io/tenableinc", "global", board="tenableinc"),
    CareerSource("wiz", "Wiz Careers", "Wiz", "core", "greenhouse", "https://boards.greenhouse.io/wizinc", "global", board="wizinc"),
    CareerSource("check_point", "Check Point Careers", "Check Point", "core", "html", "https://careers.checkpoint.com/index.php?m=cpcareers&a=search", "global", page_param="page"),
    CareerSource("cisco", "Cisco Careers", "Cisco", "core", "phenom", "https://careers.cisco.com/global/en/search-results", "global", page_param="page"),
    CareerSource("google_careers", "Google Careers", "Google", "core", "html", "https://www.google.com/about/careers/applications/jobs/results/", "global", page_param="page"),
    CareerSource("microsoft_security", "Microsoft Security Careers", "Microsoft", "core", "eightfold", "https://apply.careers.microsoft.com/careers?query=security", "global", page_param="page"),
    CareerSource("amazon_aws", "Amazon AWS Careers", "Amazon Web Services", "core", "amazon", "https://www.amazon.jobs/en/search.json", "global", query="AWS"),
    CareerSource("mandiant_google_cloud_security", "Mandiant / Google Cloud Security Careers", "Google Cloud Security", "core", "html", "https://www.google.com/about/careers/applications/jobs/results/?q=Google%20Cloud%20Security", "global", page_param="page"),
    CareerSource("visa", "Visa Careers", "Visa", "core", "smartrecruiters", "https://jobs.smartrecruiters.com/Visa", "global", board="Visa"),
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


def fetch_source(source_key: str) -> SourceResult:
    """Fetch one official source and report an honest health status."""
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
        return SourceResult(
            status="empty",
            transport="direct",
            error_code="no_active_jobs",
            attempted_urls=(source.url,),
        )

    if source.browser_fallback:
        browser_outcome = _fetch_with_browser(source)
        if browser_outcome.jobs:
            return SourceResult(
                jobs=browser_outcome.jobs,
                status="success",
                transport="playwright",
                attempted_urls=(source.url,),
            )
        if browser_outcome.no_active_jobs:
            return SourceResult(
                status="empty",
                transport="playwright",
                error_code="no_active_jobs",
                attempted_urls=(source.url,),
            )
        if browser_outcome.error_code:
            outcome = browser_outcome

    status = "parse_changed" if outcome.parsed else "blocked"
    return SourceResult(
        status=status,
        transport="direct",
        error_code=outcome.error_code or status,
        attempted_urls=(source.url,),
    )


def _fetch_direct(source: CareerSource) -> _Outcome:
    if source.backend == "greenhouse":
        return _fetch_greenhouse(source)
    if source.backend == "workday":
        return _fetch_workday(source)
    if source.backend == "ashby":
        return _fetch_ashby(source)
    if source.backend == "lever":
        return _fetch_lever(source)
    if source.backend == "smartrecruiters":
        return _fetch_smartrecruiters(source)
    if source.backend == "amazon":
        return _fetch_amazon(source)
    return _fetch_html_pages(source)


def _fetch_greenhouse(source: CareerSource) -> _Outcome:
    data = get_json(
        f"https://boards-api.greenhouse.io/v1/boards/{source.board}/jobs?content=true",
        timeout=20,
        use_proxy=False,
    )
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
            use_proxy=False,
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
    data = get_json(
        f"https://api.ashbyhq.com/posting-api/job-board/{source.board}?includeCompensation=true",
        timeout=20,
        use_proxy=False,
    )
    if isinstance(data, dict):
        rows = data.get("jobs") or data.get("jobPostings")
        if isinstance(rows, list):
            jobs = _dedupe_jobs(_jobs_from_ashby(rows, source))
            return _Outcome(jobs, parsed=True, no_active_jobs=not rows)
    return _fetch_html_pages(source)


def _fetch_lever(source: CareerSource) -> _Outcome:
    """Fetch published postings from Lever's public postings API."""
    data = get_json(
        f"https://api.lever.co/v0/postings/{source.board}?mode=json",
        timeout=20,
        use_proxy=False,
    )
    if not isinstance(data, list):
        return _Outcome([], error_code="lever_unavailable")
    jobs = _dedupe_jobs(_jobs_from_lever(data, source))
    return _Outcome(jobs, parsed=True, no_active_jobs=not data)


def _fetch_smartrecruiters(source: CareerSource) -> _Outcome:
    """Fetch published postings from SmartRecruiters' public Posting API."""
    offset = 0
    all_jobs: list[Job] = []
    parsed_any = False
    total: int | None = None
    while True:
        data = get_json(
            f"https://api.smartrecruiters.com/v1/companies/{source.board}/postings",
            params={"limit": source.page_size, "offset": offset},
            timeout=20,
            use_proxy=False,
        )
        if not isinstance(data, dict):
            return _Outcome(_dedupe_jobs(all_jobs), parsed=parsed_any, error_code="smartrecruiters_unavailable")
        rows = data.get("content")
        if not isinstance(rows, list):
            return _Outcome(_dedupe_jobs(all_jobs), parsed=True, error_code="smartrecruiters_shape_changed")
        parsed_any = True
        if total is None:
            value = data.get("totalFound")
            total = value if isinstance(value, int) and value >= 0 else None
        all_jobs.extend(_jobs_from_smartrecruiters(rows, source))
        offset += len(rows)
        if not rows or len(rows) < source.page_size or (total is not None and offset >= total):
            break
    jobs = _dedupe_jobs(all_jobs)
    return _Outcome(jobs, parsed=parsed_any, no_active_jobs=parsed_any and not all_jobs)


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
        page += 1

    jobs = _dedupe_jobs(all_jobs)
    return _Outcome(jobs, parsed=parsed_any, no_active_jobs=parsed_any and not jobs)


def _fetch_with_browser(source: CareerSource) -> _Outcome:
    """Render only after a direct public-data request failed.

    The import and browser startup are deliberately lazy so normal JSON/ATS
    connectors do not pay a browser cost.
    """
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
                    all_jobs: list[Job] = []
                    parsed_any = False
                    page_fingerprints: set[tuple[str, ...]] = set()
                    while True:
                        page.goto(_page_url(source, page_number), wait_until="networkidle", timeout=60_000)
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


def _jobs_from_lever(rows: list[Any], source: CareerSource) -> list[Job]:
    jobs: list[Job] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        categories = row.get("categories") if isinstance(row.get("categories"), dict) else {}
        title = _clean_text(str(row.get("text") or ""))
        url = _clean_text(str(row.get("hostedUrl") or row.get("applyUrl") or ""))
        if not title or not url:
            continue
        location = _clean_text(str(categories.get("location") or ""))
        if not location:
            all_locations = categories.get("allLocations")
            if isinstance(all_locations, list):
                location = ", ".join(_clean_text(str(value)) for value in all_locations if value)
        posted = _parse_date_value(row.get("createdAt"))
        jobs.append(_make_job(
            source,
            title=title,
            url=url,
            location=location,
            description=str(row.get("descriptionPlain") or row.get("description") or ""),
            posted_date=posted,
        ))
    return jobs


def _jobs_from_ashby(rows: list[Any], source: CareerSource) -> list[Job]:
    jobs: list[Job] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = _clean_text(str(row.get("title") or ""))
        url = _clean_text(str(row.get("jobUrl") or row.get("applyUrl") or ""))
        if not title or not url:
            continue
        location = _clean_text(str(row.get("location") or ""))
        if bool(row.get("isRemote")) and "remote" not in location.lower():
            location = f"{location} / Remote".strip(" / ")
        jobs.append(_make_job(
            source,
            title=title,
            url=url,
            location=location,
            description=str(row.get("descriptionPlain") or row.get("descriptionHtml") or ""),
            posted_date=_parse_date_value(row.get("publishedAt")),
        ))
    return jobs


def _jobs_from_smartrecruiters(rows: list[Any], source: CareerSource) -> list[Job]:
    jobs: list[Job] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = _clean_text(str(row.get("name") or ""))
        identifier = _clean_text(str(row.get("id") or row.get("uuid") or ""))
        if not title or not identifier:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        url = f"https://jobs.smartrecruiters.com/{source.board}/{identifier}-{slug}"
        location_data = row.get("location") if isinstance(row.get("location"), dict) else {}
        location = _clean_text(str(location_data.get("fullLocation") or ""))
        if not location:
            location = ", ".join(
                _clean_text(str(location_data.get(key) or ""))
                for key in ("city", "region", "country")
                if location_data.get(key)
            )
        if bool(location_data.get("remote")) and "remote" not in location.lower():
            location = f"{location} / Remote".strip(" / ")
        jobs.append(_make_job(
            source,
            title=title,
            url=url,
            company=_company_from(row) or source.company,
            location=location,
            posted_date=_parse_date_value(row.get("releasedDate")),
        ))
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


def _parse_date_value(raw: Any) -> datetime | None:
    """Parse ATS timestamps represented either as ISO text or Unix milliseconds."""
    if isinstance(raw, (int, float)):
        try:
            seconds = float(raw) / 1000 if raw > 10_000_000_000 else float(raw)
            return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    return _parse_date(str(raw or ""))


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
