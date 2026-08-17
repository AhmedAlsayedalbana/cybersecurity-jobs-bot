"""Public, policy-aware connectors for freelance marketplaces and MENA boards.

Only public client projects and public job listings are eligible.  The module
deliberately reports a capability status for services that cannot expose a
public client feed instead of turning seller profiles into fake job adverts.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import html as html_lib
import json
import logging
import re
import threading
import time
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

from models import Job
from sources.http_utils import get_text_result

log = logging.getLogger(__name__)

_SECURITY_TERMS = (
    "cybersecurity", "cyber security", "information security", "infosec",
    "penetration", "pentest", "red team", "blue team", "soc", "siem",
    "security engineer", "security analyst", "appsec", "devsecops",
    "cloud security", "network security", "vulnerability", "threat",
    "incident response", "امن سيبراني", "الأمن السيبراني", "امن المعلومات",
    "أمن المعلومات", "اختبار اختراق", "اختراق", "حماية الشبكات",
)
_DATE_ISO_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})(?:[T\s]([0-2]\d:[0-5]\d(?::[0-5]\d)?))?")
_RELATIVE_RE = re.compile(
    r"\b(\d{1,3})\s*(minute|minutes|min|hour|hours|hr|hrs|day|days|week|weeks)\s+ago\b",
    re.IGNORECASE,
)
_AR_RELATIVE_RE = re.compile(r"منذ\s*(\d{1,3})?\s*(دقيقة|دقائق|ساعة|ساعات|يوم|أيام|اسبوع|أسبوع|أسابيع)")
_SCRIPT_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_ANCHOR_RE = re.compile(
    r'<a[^>]+(?:href|data-href)=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]{4,180})\]\(((?:https?://|/)[^\s)]+)\)")
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(slots=True)
class SourceResult:
    jobs: list[Job] = field(default_factory=list)
    status: str = "success"  # success | empty | blocked | parse_changed | no_public_client_feed
    transport: str = "direct"  # direct | jina | none
    error_code: str = ""
    attempted_urls: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MarketplaceSpec:
    key: str
    name: str
    urls: tuple[str, ...]
    content_type: str
    geo_hint: str
    priority: int
    supports_public_client_feed: bool = True


PUBLIC_SPECS: tuple[MarketplaceSpec, ...] = (
    MarketplaceSpec("upwork", "Upwork", ("https://www.upwork.com/nx/search/jobs/?q=cybersecurity",), "client_project", "remote", 20),
    MarketplaceSpec("freelancer", "Freelancer", ("https://www.freelancer.com/jobs/cyber-security/",), "client_project", "remote", 20),
    MarketplaceSpec("mostaql", "Mostaql", ("https://mostaql.com/projects?category=information-technology&query=cybersecurity",), "client_project", "remote", 20),
    MarketplaceSpec("contra", "Contra", ("https://contra.com/jobs?search=cybersecurity",), "client_project", "remote", 20),
    MarketplaceSpec("peopleperhour", "PeoplePerHour", ("https://www.peopleperhour.com/freelance-cyber-security-jobs",), "client_project", "remote", 20),
    MarketplaceSpec("guru", "Guru", ("https://www.guru.com/m/find/freelance-jobs/cyber-security/",), "client_project", "remote", 20),
    MarketplaceSpec("workana", "Workana", ("https://www.workana.com/en/jobs?query=cybersecurity",), "client_project", "remote", 20),
    MarketplaceSpec("wuzzuf", "Wuzzuf", ("https://wuzzuf.net/a/Cybersecurity-Jobs-in-Egypt?start=0",), "job_listing", "egypt", 15),
    MarketplaceSpec("bayt", "Bayt", ("https://www.bayt.com/en/egypt/jobs/cyber-security-jobs/", "https://www.bayt.com/en/saudi-arabia/jobs/cyber-security-jobs/"), "job_listing", "egypt", 17),
    MarketplaceSpec("gulftalent", "GulfTalent", ("https://www.gulftalent.com/jobs/cybersecurity",), "job_listing", "gulf", 18),
    MarketplaceSpec("tanqeeb", "Tanqeeb", ("https://www.tanqeeb.com/en/s/cyber-security-jobs",), "job_listing", "gulf", 19),
    MarketplaceSpec("akhtaboot", "Akhtaboot", ("https://www.akhtaboot.com/en/egypt/jobs/search?keywords=cybersecurity",), "job_listing", "egypt", 19),
)
RESTRICTED_SPECS: tuple[MarketplaceSpec, ...] = (
    MarketplaceSpec("fiverr", "Fiverr", (), "service_offer", "remote", 20, False),
    MarketplaceSpec("khamsat", "Khamsat", (), "service_offer", "remote", 20, False),
    MarketplaceSpec("toptal", "Toptal", (), "service_offer", "remote", 20, False),
)
SPECS_BY_KEY = {spec.key: spec for spec in (*PUBLIC_SPECS, *RESTRICTED_SPECS)}
_TARGET_PARSER_KEYS = frozenset({
    "wuzzuf", "tanqeeb", "upwork", "freelancer", "akhtaboot",
    "mostaql", "gulftalent", "bayt", "contra", "guru",
})


@dataclass(frozen=True, slots=True)
class _TargetListing:
    """A public listing with the fields needed for trustworthy delivery."""

    title: str
    url: str
    description: str
    posted: datetime
    company: str = ""
    location: str = ""
    job_id: str = ""


@dataclass(slots=True)
class _TargetParseOutcome:
    jobs: list[Job] = field(default_factory=list)
    recognizable_listings: int = 0
    incomplete_security_listings: int = 0
    explicit_empty: bool = False
    cards_found: int = 0
    cards_parsed: int = 0
    cards_rejected: int = 0
    parse_success_rate: float = 0.0


class _JinaLimiter:
    """Process-wide rolling limiter below the anonymous Reader quota."""

    def __init__(self, limit: int = 12, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._times: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._times and now - self._times[0] >= self.window_seconds:
                    self._times.popleft()
                if len(self._times) < self.limit:
                    self._times.append(now)
                    return
                wait = self.window_seconds - (now - self._times[0])
            time.sleep(max(0.01, wait))


_jina_limiter = _JinaLimiter()


def _clean(value: Any) -> str:
    plain = _TAG_RE.sub(" ", html_lib.unescape(str(value or "")))
    return re.sub(r"\s+", " ", plain).strip()


def _is_security(text: str) -> bool:
    lowered = (text or "").lower()
    return any(term in lowered for term in _SECURITY_TERMS)


def _parse_posted_date(text: str) -> datetime | None:
    candidate = _clean(text)
    iso = _DATE_ISO_RE.search(candidate)
    if iso:
        try:
            return datetime.fromisoformat(" ".join(part for part in iso.groups() if part))
        except ValueError:
            pass
    relative = _RELATIVE_RE.search(candidate)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2).lower()
        hours = amount / 60 if unit.startswith("min") else amount if unit.startswith("h") else amount * 24 if unit.startswith("day") else amount * 24 * 7
        return datetime.now() - timedelta(hours=hours)
    ar_relative = _AR_RELATIVE_RE.search(candidate)
    if ar_relative:
        amount = int(ar_relative.group(1) or 1)
        unit = ar_relative.group(2)
        hours = amount / 60 if "دقيق" in unit else amount if "ساع" in unit else amount * 24 if "يوم" in unit else amount * 24 * 7
        return datetime.now() - timedelta(hours=hours)
    return None


def _flatten_json(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _flatten_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _flatten_json(child)


def _normalise_url(url: str, base_url: str) -> str:
    url = _clean(url)
    if not url:
        return ""
    result = urljoin(base_url, url)
    parsed = urlparse(result)
    if parsed.scheme not in {"http", "https"}:
        return ""
    base_host = urlparse(base_url).netloc.lower().removeprefix("www.")
    host = parsed.netloc.lower().removeprefix("www.")
    return result if host == base_host else ""


def _candidate_from_record(record: dict[str, Any], spec: MarketplaceSpec, base_url: str) -> tuple[str, str, str, datetime | None] | None:
    record_type = " ".join(str(part) for part in (record.get("@type"), record.get("type"), record.get("kind")) if part)
    if "service" in record_type.lower() or "product" in record_type.lower():
        return None
    title = _clean(
        record.get("title") or record.get("name") or record.get("headline")
        or record.get("jobTitle") or record.get("position") or record.get("projectTitle")
    )
    raw_url = next((
        record.get(key) for key in (
            "url", "link", "jobUrl", "applyUrl", "detailUrl", "detail_url",
            "job_url", "absolute_url", "canonicalUrl", "seo_url",
        ) if record.get(key)
    ), "")
    url = _normalise_url(raw_url, base_url)
    description = _clean(
        record.get("description") or record.get("summary") or record.get("snippet")
        or record.get("shortDescription") or record.get("excerpt")
    )
    posted = _parse_posted_date(str(next((
        record.get(key) for key in (
            "datePosted", "publishedAt", "createdAt", "postedAt", "posted_at",
            "publish_date", "published_date", "date",
        ) if record.get(key)
    ), description)))
    if not title or not url or not posted or not _is_security(f"{title} {description}"):
        return None
    return title, url, description[:800], posted


def _record_text(record: dict[str, Any], *keys: str) -> str:
    """Read a text field while accepting the current nested board schemas."""
    for key in keys:
        value = record.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("title") or value.get("label") or value.get("value")
        if isinstance(value, list):
            value = ", ".join(_clean(item.get("name") if isinstance(item, dict) else item) for item in value)
        text = _clean(value)
        if text:
            return text
    return ""


def _record_company(record: dict[str, Any]) -> str:
    return _record_text(record, "company", "companyName", "employer", "employerName", "client", "clientName", "hiringOrganization")


def _record_location(record: dict[str, Any]) -> str:
    location = _record_text(
        record, "location", "locationName", "workLocation", "city", "cityName",
        "country", "countryName", "address",
    )
    if not location and record.get("remote") is True:
        return "Remote"
    return location


def _record_job_id(record: dict[str, Any], url: str) -> str:
    for key in ("jobId", "job_id", "id", "uid", "projectId", "project_id", "ciphertext"):
        value = _clean(record.get(key))
        if value:
            return value[:120]
    match = re.search(r"(?:jobs?|projects?)/(?:view/)?([^/?#]+)", url, re.IGNORECASE)
    return match.group(1)[:120] if match else ""


def _target_candidate_from_record(
    record: dict[str, Any], spec: MarketplaceSpec, base_url: str
) -> tuple[_TargetListing | None, bool, bool]:
    """Parse a current JSON/JSON-LD listing and retain provider fields."""
    record_type = _clean(" ".join(str(record.get(key, "")) for key in ("@type", "type", "kind"))).lower()
    if "service" in record_type or "product" in record_type:
        return None, False, False
    title = _record_text(record, "title", "name", "headline", "jobTitle", "position", "projectTitle")
    raw_url = _record_text(
        record, "url", "link", "jobUrl", "applyUrl", "detailUrl", "detail_url",
        "job_url", "absolute_url", "canonicalUrl", "seo_url",
    )
    url = _normalise_url(raw_url, base_url)
    description = _record_text(record, "description", "summary", "snippet", "shortDescription", "excerpt")
    recognizable = bool(title and url)
    is_security = _is_security(f"{title} {description}")
    posted_raw = _record_text(
        record, "datePosted", "publishedAt", "createdAt", "postedAt", "posted_at",
        "publish_date", "published_date", "date",
    )
    posted = _parse_posted_date(posted_raw or description)
    if not recognizable or not is_security or not posted:
        return None, recognizable, bool(recognizable and is_security)
    return _TargetListing(
        title=title,
        url=url,
        description=description[:800],
        posted=posted,
        company=_record_company(record),
        location=_record_location(record),
        job_id=_record_job_id(record, url),
    ), True, False


def _target_url_looks_like_listing(url: str, spec_key: str) -> bool:
    path = urlparse(url).path.lower()
    if spec_key == "freelancer":
        return "/projects/" in path or "/jobs/" in path
    if spec_key == "upwork":
        return "/jobs/" in path
    return "/jobs/" in path or "/job/" in path


def _context_field(context: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        match = re.search(rf"(?:^|[|\\n])\\s*{re.escape(label)}\\s*[:\-]\s*([^|\\n]{{2,120}})", context, re.IGNORECASE)
        if match:
            return _clean(match.group(1))
    return ""


def _target_link_records(content: str, spec: MarketplaceSpec, base_url: str, *, markdown: bool) -> tuple[list[_TargetListing], int, int]:
    rows: list[_TargetListing] = []
    recognizable = 0
    incomplete_security = 0
    if markdown:
        links = ((title, url, content[max(0, match.start() - 280): match.end() + 520]) for match in _MARKDOWN_LINK_RE.finditer(content) for title, url in [match.groups()])
    else:
        links = ((title, url, content[max(0, match.start() - 280): match.end() + 520]) for match in _ANCHOR_RE.finditer(content) for url, title in [match.groups()])
    for raw_title, raw_url, context in links:
        title = _clean(raw_title)
        url = _normalise_url(raw_url, base_url)
        if not title or not url or len(title) > 180 or not _target_url_looks_like_listing(url, spec.key):
            continue
        recognizable += 1
        is_security = _is_security(f"{title} {context}")
        posted = _parse_posted_date(context)
        if not is_security:
            continue
        if not posted:
            incomplete_security += 1
            continue
        rows.append(_TargetListing(
            title=title,
            url=url,
            description=_clean(context)[:800],
            posted=posted,
            company=_context_field(context, ("Company", "Employer", "Client", "الشركة")),
            location=_context_field(context, ("Location", "City", "Country", "الموقع", "المدينة")),
            job_id=_record_job_id({}, url),
        ))
    return rows, recognizable, incomplete_security


def _target_content_is_blocked(content: str) -> bool:
    lowered = (content or "").lower()
    return any(marker in lowered for marker in (
        "just a moment", "performing security verification", "captcha", "cf-chl-",
        "403 forbidden", "access denied", "parked domain", "godaddy",
    ))


def _target_content_is_explicitly_empty(content: str) -> bool:
    lowered = (content or "").lower()
    return any(marker in lowered for marker in (
        "no jobs found", "no job found", "no results found", "there are no jobs",
        "لا توجد وظائف", "لا يوجد وظائف", "لا توجد نتائج",
    ))


def _extract_json_records(content: str, spec: MarketplaceSpec, base_url: str) -> list[tuple[str, str, str, datetime]]:
    out: list[tuple[str, str, str, datetime]] = []
    blobs = list(_SCRIPT_RE.findall(content))
    # Several current board endpoints return a JSON document directly rather
    # than embedding it in a script tag.  Treat it as the same public record
    # shape; this keeps parser drift visible without pretending an empty page
    # was a healthy source.
    stripped = content.strip()
    if stripped.startswith(("{", "[")):
        blobs.append(stripped)
    next_data = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', content, re.IGNORECASE | re.DOTALL)
    if next_data:
        blobs.append(next_data.group(1))
    for blob in blobs:
        try:
            data = json.loads(html_lib.unescape(blob).strip())
        except (TypeError, ValueError):
            continue
        for record in _flatten_json(data):
            candidate = _candidate_from_record(record, spec, base_url)
            if candidate:
                out.append(candidate)  # type: ignore[arg-type]
    return out


def _parse_target(content: str, spec: MarketplaceSpec, base_url: str, transport: str) -> _TargetParseOutcome:
    outcome = _TargetParseOutcome(explicit_empty=_target_content_is_explicitly_empty(content))
    rows: list[_TargetListing] = []
    blobs = list(_SCRIPT_RE.findall(content))
    stripped = content.strip()
    if stripped.startswith(("{", "[")):
        blobs.append(stripped)
    next_data = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', content, re.IGNORECASE | re.DOTALL)
    if next_data:
        blobs.append(next_data.group(1))
    for blob in blobs:
        try:
            data = json.loads(html_lib.unescape(blob).strip())
        except (TypeError, ValueError):
            continue
        for record in _flatten_json(data):
            candidate, recognizable, incomplete = _target_candidate_from_record(record, spec, base_url)
            outcome.recognizable_listings += int(recognizable)
            outcome.incomplete_security_listings += int(incomplete)
            if candidate:
                rows.append(candidate)
    link_rows, recognizable, incomplete = _target_link_records(content, spec, base_url, markdown=transport == "jina")
    rows.extend(link_rows)
    outcome.recognizable_listings += recognizable
    outcome.incomplete_security_listings += incomplete
    outcome.jobs = _to_jobs(rows, spec, transport)
    return outcome


def _extract_links(content: str, spec: MarketplaceSpec, base_url: str, *, markdown: bool) -> list[tuple[str, str, str, datetime]]:
    out: list[tuple[str, str, str, datetime]] = []
    if markdown:
        links = ((title, url, content[max(0, match.start() - 220): match.end() + 420]) for match in _MARKDOWN_LINK_RE.finditer(content) for title, url in [match.groups()])
    else:
        links = ((title, url, content[max(0, match.start() - 220): match.end() + 420]) for match in _ANCHOR_RE.finditer(content) for url, title in [match.groups()])
    for raw_title, raw_url, context in links:
        title = _clean(raw_title)
        url = _normalise_url(raw_url, base_url)
        posted = _parse_posted_date(context)
        if not title or not url or not posted or len(title) > 180 or not _is_security(f"{title} {context}"):
            continue
        out.append((title, url, _clean(context)[:800], posted))
    return out


def _to_jobs(rows: Iterable[tuple[str, str, str, datetime] | _TargetListing], spec: MarketplaceSpec, transport: str) -> list[Job]:
    jobs: list[Job] = []
    seen: set[str] = set()
    for row in rows:
        if isinstance(row, _TargetListing):
            title, url, description, posted = row.title, row.url, row.description, row.posted
            company = row.company or (f"{spec.name} Client" if spec.content_type == "client_project" else spec.name)
            location = row.location or ("Remote" if spec.geo_hint == "remote" else ("Egypt" if spec.geo_hint == "egypt" else "Gulf"))
            job_id = row.job_id
        else:
            title, url, description, posted = row
            company = f"{spec.name} Client" if spec.content_type == "client_project" else spec.name
            location = "Remote" if spec.geo_hint == "remote" else ("Egypt" if spec.geo_hint == "egypt" else "Gulf")
            job_id = ""
        canonical = url.split("#", 1)[0]
        if canonical in seen:
            continue
        seen.add(canonical)
        digest = hashlib.sha256(f"{title}|{canonical}|{posted.isoformat()}".encode("utf-8")).hexdigest()[:20]
        job = Job(
            title=title,
            company=company,
            location=location,
            url=canonical,
            source=spec.key,
            source_key=spec.key,
            content_type=spec.content_type,
            origin_priority=spec.priority,
            geo_hint=spec.geo_hint,
            is_remote=spec.geo_hint == "remote",
            job_type="Freelance" if spec.content_type == "client_project" else "",
            original_source=spec.name,
            posted_date=posted,
            description=description,
            tags=[spec.key, spec.content_type, f"transport:{transport}", "public_verified", *( [f"job_id:{job_id}"] if job_id else [] )],
            extraction_method=f"{transport}:structured_or_card",
            provenance_hash=digest,
        )
        jobs.append(job)
    return jobs


def _parse(content: str, spec: MarketplaceSpec, base_url: str, transport: str) -> list[Job]:
    if spec.key in _TARGET_PARSER_KEYS:
        return _parse_target(content, spec, base_url, transport).jobs
    rows = _extract_json_records(content, spec, base_url)
    if not rows:
        rows = _extract_links(content, spec, base_url, markdown=transport == "jina")
    return _to_jobs(rows, spec, transport)


def _fetch_via_jina(url: str) -> str | None:
    _jina_limiter.acquire()
    result = get_text_result(
        f"https://r.jina.ai/{url}",
        headers={
            "Accept": "text/markdown, text/plain, */*",
            "X-Respond-With": "markdown",
            "X-Engine": "browser",
            "X-Cache-Tolerance": "300",
            "X-Max-Tokens": "12000",
        },
        timeout=25,
        max_retries=1,
    )
    return result.text


def fetch_marketplace(spec_key: str) -> SourceResult:
    spec = SPECS_BY_KEY[spec_key]
    if not spec.supports_public_client_feed:
        return SourceResult(status="no_public_client_feed", transport="none", error_code="policy_public_only")

    attempted: list[str] = []
    parsed_any = False
    target_recognizable = 0
    target_incomplete_security = 0
    target_explicit_empty = False
    target_blocked = False
    for url in spec.urls:
        attempted.append(url)
        direct = get_text_result(url, timeout=15, max_retries=1)
        if direct.text:
            if spec.key in _TARGET_PARSER_KEYS and _target_content_is_blocked(direct.text):
                target_blocked = True
            elif spec.key in _TARGET_PARSER_KEYS:
                parsed_any = True
                outcome = _parse_target(direct.text, spec, url, "direct")
                target_recognizable += outcome.recognizable_listings
                target_incomplete_security += outcome.incomplete_security_listings
                target_explicit_empty = target_explicit_empty or outcome.explicit_empty
                if outcome.jobs:
                    return SourceResult(outcome.jobs, "success", "direct", attempted_urls=tuple(attempted))
            else:
                parsed_any = True
                jobs = _parse(direct.text, spec, url, "direct")
                if jobs:
                    return SourceResult(jobs, "success", "direct", attempted_urls=tuple(attempted))
        jina = _fetch_via_jina(url)
        if jina:
            if spec.key in _TARGET_PARSER_KEYS and _target_content_is_blocked(jina):
                target_blocked = True
            elif spec.key in _TARGET_PARSER_KEYS:
                parsed_any = True
                outcome = _parse_target(jina, spec, url, "jina")
                target_recognizable += outcome.recognizable_listings
                target_incomplete_security += outcome.incomplete_security_listings
                target_explicit_empty = target_explicit_empty or outcome.explicit_empty
                if outcome.jobs:
                    return SourceResult(outcome.jobs, "success", "jina", attempted_urls=tuple(attempted))
            else:
                parsed_any = True
                jobs = _parse(jina, spec, url, "jina")
                if jobs:
                    return SourceResult(jobs, "success", "jina", attempted_urls=tuple(attempted))

    if spec.key in _TARGET_PARSER_KEYS:
        if target_recognizable or target_explicit_empty:
            return SourceResult(
                status="empty", transport="jina" if parsed_any else "direct",
                error_code="no_matching_security_listings",
                attempted_urls=tuple(attempted),
            )
        if target_incomplete_security or parsed_any:
            return SourceResult(
                status="parse_changed", transport="jina" if parsed_any else "direct",
                error_code=f"{spec.key}_parser_unrecognized",
                attempted_urls=tuple(attempted),
            )
        if target_blocked:
            return SourceResult(
                status="blocked", transport="direct", error_code=f"{spec.key}_blocked",
                attempted_urls=tuple(attempted),
            )

    status = "parse_changed" if parsed_any else "blocked"
    # A reachable page with zero recognised public cards is a parser failure,
    # never a healthy empty source.  The platform-specific code makes the
    # health report actionable (Wuzzuf/Bayt/... rather than generic "0").
    error_code = f"{spec.key}_parser_unrecognized" if parsed_any else f"{spec.key}_unreachable"
    return SourceResult(
        status=status,
        transport="jina" if parsed_any else "direct",
        error_code=error_code,
        attempted_urls=tuple(attempted),
    )


def fetcher_for(spec_key: str):
    """Build a named zero-argument fetcher compatible with SourceSpec."""
    def _fetch() -> SourceResult:
        return fetch_marketplace(spec_key)
    _fetch.__name__ = f"fetch_{spec_key}"
    return _fetch
