"""Verified public API/RSS connectors for remote, contract and freelance work.

These feeds are deliberately separate from the HTML marketplace connector.
They use documented/public machine-readable endpoints and retain the source
date and canonical URL required by the strict publisher.  The jobs are remote
roles; jobs explicitly marked contract/freelance are labelled accordingly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import html
import logging
import re
from typing import Any, Iterable
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

from models import Job
from sources.http_utils import get_json, get_text_result
from sources.marketplace_sources import SourceResult

log = logging.getLogger(__name__)

REMOTIVE_URL = "https://remotive.com/api/remote-jobs"
REMOTEOK_URL = "https://remoteok.com/api"
WWR_RSS_URL = "https://weworkremotely.com/remote-jobs.rss"
ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"

_SECURITY_RE = re.compile(
    r"\b(?:cyber\s*security|information\s+security|infosec|soc|siem|"
    r"iam|identity\s*(?:&|and)?\s*access|application\s+security|appsec|"
    r"devsecops|cloud\s+security|network\s+security|penetration|pentest|"
    r"red\s+team|blue\s+team|threat\s+(?:intel(?:ligence)?|hunter)|"
    r"incident\s+response|vulnerability|grc|governance.{0,25}risk)\b",
    re.IGNORECASE,
)
_CONTRACT_RE = re.compile(
    r"\b(?:contract(?:or|ing)?|freelance|consult(?:ant|ing)|temporary|part[ -]?time)\b",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", html.unescape(str(value or "")))).strip()


def _as_naive(value: Any) -> datetime | None:
    """Return a trustworthy, UTC-naive publication date or None."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        try:
            timestamp = float(value)
            # A few feeds use milliseconds, most use Unix seconds.
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)
        except (OverflowError, OSError, TypeError, ValueError):
            return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _is_security(*parts: Any) -> bool:
    return bool(_SECURITY_RE.search(" ".join(_clean(part) for part in parts)))


def _job_type(raw_type: Any, *parts: Any) -> str:
    text = " ".join([_clean(raw_type), *(_clean(part) for part in parts)])
    if _CONTRACT_RE.search(text):
        return "Contract / Freelance"
    return _clean(raw_type).replace("_", " ").title()


def _make_job(
    *,
    source: str,
    original_source: str,
    title: Any,
    company: Any,
    location: Any,
    url: Any,
    posted_date: datetime | None,
    description: Any = "",
    tags: Iterable[Any] = (),
    raw_type: Any = "",
    origin_priority: int,
) -> Job | None:
    title_text, url_text = _clean(title), _clean(url)
    description_text = _clean(description)
    if not title_text or not url_text or not posted_date:
        return None
    if not _is_security(title_text, description_text, *tags):
        return None
    digest = hashlib.sha256(
        f"{source}|{url_text}|{posted_date.isoformat()}".encode("utf-8")
    ).hexdigest()[:20]
    source_tags = [source, "public_api", "remote"] + [
        _clean(tag) for tag in tags if _clean(tag)
    ]
    job_type = _job_type(raw_type, title_text, description_text, *source_tags)
    if job_type == "Contract / Freelance":
        source_tags.append("contract_freelance")
    return Job(
        title=title_text,
        company=_clean(company) or original_source,
        location=_clean(location) or "Remote",
        url=url_text,
        source=source,
        source_key=source,
        content_type="job_listing",
        origin_priority=origin_priority,
        geo_hint="global",
        is_remote=True,
        job_type=job_type,
        original_source=original_source,
        posted_date=posted_date,
        description=description_text[:2000],
        tags=source_tags,
        extraction_method="public_api_or_rss",
        provenance_hash=digest,
    )


def _result_from_jobs(jobs: list[Job], *, transport: str, endpoint: str, available: bool) -> SourceResult:
    if not available:
        return SourceResult(status="blocked", transport=transport, error_code="public_endpoint_unavailable", attempted_urls=(endpoint,))
    return SourceResult(
        jobs=jobs,
        status="success" if jobs else "empty",
        transport=transport,
        attempted_urls=(endpoint,),
    )


def fetch_remotive_security() -> SourceResult:
    """Fetch the public Remotive search API with one low-rate security query."""
    data = get_json(REMOTIVE_URL, params={"search": "security", "limit": 100}, use_proxy=False)
    rows = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return _result_from_jobs([], transport="direct", endpoint=REMOTIVE_URL, available=False)
    jobs: list[Job] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        job = _make_job(
            source="remotive_security",
            original_source="Remotive",
            title=item.get("title"),
            company=item.get("company_name"),
            location=item.get("candidate_required_location"),
            url=item.get("url"),
            posted_date=_as_naive(item.get("publication_date") or item.get("created_at")),
            description=item.get("description"),
            tags=[item.get("category", "")],
            raw_type=item.get("job_type"),
            origin_priority=27,
        )
        if job:
            jobs.append(job)
    return _result_from_jobs(jobs, transport="direct", endpoint=REMOTIVE_URL, available=True)


def fetch_remoteok_security() -> SourceResult:
    """Fetch RemoteOK's public JSON feed and retain dated security roles."""
    data = get_json(REMOTEOK_URL, headers={"User-Agent": "CybersecurityJobsBot/57"}, use_proxy=False)
    if not isinstance(data, list):
        return _result_from_jobs([], transport="direct", endpoint=REMOTEOK_URL, available=False)
    jobs: list[Job] = []
    for item in data:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        url = _clean(item.get("url"))
        if url and url.startswith("/"):
            url = urljoin("https://remoteok.com", url)
        if not url:
            url = f"https://remoteok.com/remote-jobs/{item.get('id')}"
        tags = item.get("tags") if isinstance(item.get("tags"), list) else []
        job = _make_job(
            source="remoteok_security",
            original_source="RemoteOK",
            title=item.get("position"),
            company=item.get("company"),
            location=item.get("location"),
            url=url,
            posted_date=_as_naive(item.get("epoch") or item.get("date")),
            description=item.get("description"),
            tags=tags,
            raw_type=item.get("job_type") or item.get("employment_type"),
            origin_priority=28,
        )
        if job:
            jobs.append(job)
    return _result_from_jobs(jobs, transport="direct", endpoint=REMOTEOK_URL, available=True)


def fetch_wwr_security() -> SourceResult:
    """Fetch the official We Work Remotely RSS feed once and filter locally."""
    response = get_text_result(WWR_RSS_URL, timeout=20, max_retries=1, use_proxy=False)
    if not response.text:
        return _result_from_jobs([], transport="rss", endpoint=WWR_RSS_URL, available=False)
    try:
        root = ET.fromstring(response.text)
    except ET.ParseError:
        return SourceResult(status="parse_changed", transport="rss", error_code="invalid_rss", attempted_urls=(WWR_RSS_URL,))

    jobs: list[Job] = []
    for item in root.findall(".//item"):
        title_raw = _clean(item.findtext("title", ""))
        company, title = (title_raw.split(": ", 1) + [""])[:2] if ": " in title_raw else ("", title_raw)
        description = item.findtext("description", "")
        job = _make_job(
            source="wwr_security",
            original_source="We Work Remotely",
            title=title,
            company=company,
            location="Remote",
            url=item.findtext("link", ""),
            posted_date=_as_naive(item.findtext("pubDate", "")),
            description=description,
            tags=[item.findtext("category", "")],
            raw_type="",
            origin_priority=29,
        )
        if job:
            jobs.append(job)
    return _result_from_jobs(jobs, transport="rss", endpoint=WWR_RSS_URL, available=True)


def fetch_arbeitnow_security() -> SourceResult:
    """Fetch Arbeitnow's free API and retain remote, dated security roles."""
    data = get_json(ARBEITNOW_URL, use_proxy=False)
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return _result_from_jobs([], transport="direct", endpoint=ARBEITNOW_URL, available=False)
    jobs: list[Job] = []
    for item in rows:
        if not isinstance(item, dict) or not item.get("remote"):
            continue
        tags = item.get("tags") if isinstance(item.get("tags"), list) else []
        job = _make_job(
            source="arbeitnow_security",
            original_source="Arbeitnow",
            title=item.get("title"),
            company=item.get("company_name"),
            location=item.get("location") or "Remote",
            url=item.get("url"),
            posted_date=_as_naive(item.get("created_at")),
            description=item.get("description"),
            tags=tags,
            raw_type=item.get("job_type"),
            origin_priority=30,
        )
        if job:
            jobs.append(job)
    return _result_from_jobs(jobs, transport="direct", endpoint=ARBEITNOW_URL, available=True)
