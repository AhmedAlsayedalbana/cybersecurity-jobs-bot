"""Arab world company careers — non-LinkedIn direct fetching.

Fetches from major Arab company career pages using the Jina Reader
approach (``r.jina.ai``) to obtain markdown, then extracts security-
related job listings.

Countries covered: Saudi Arabia, UAE, Qatar, Kuwait, Bahrain, Oman,
Jordan, Morocco.
"""

from __future__ import annotations

import logging
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

_ARAB_COMPANY_SPECS = [
    # Saudi Arabia
    {"key": "stc_careers", "name": "STC Careers",
     "url": "https://careers.stc.com.sa", "country": "Saudi Arabia", "geo_hint": "arab"},
    {"key": "aramco_careers", "name": "Saudi Aramco Careers",
     "url": "https://careers.aramco.com", "country": "Saudi Arabia", "geo_hint": "arab"},
    {"key": "sabic_careers", "name": "SABIC Careers",
     "url": "https://www.sabic.com/careers", "country": "Saudi Arabia", "geo_hint": "arab"},
    # UAE
    {"key": "adnoc_careers", "name": "ADNOC Careers",
     "url": "https://careers.adnoc.ae", "country": "UAE", "geo_hint": "arab"},
    {"key": "emirates_nbd_careers", "name": "Emirates NBD Careers",
     "url": "https://www.emiratesnbd.com/careers", "country": "UAE", "geo_hint": "arab"},
    {"key": "du_careers", "name": "du (E& UAE) Careers",
     "url": "https://careers.du.ae", "country": "UAE", "geo_hint": "arab"},
    # Qatar
    {"key": "qnb_careers_qa", "name": "QNB Qatar Careers",
     "url": "https://www.qnb.com/careers", "country": "Qatar", "geo_hint": "arab"},
    {"key": "qatar_energy_careers", "name": "QatarEnergy Careers",
     "url": "https://www.qatarenergy.com/careers", "country": "Qatar", "geo_hint": "arab"},
    # Kuwait
    {"key": "kpc_careers", "name": "Kuwait Petroleum Careers",
     "url": "https://www.kpc.com.kw/careers", "country": "Kuwait", "geo_hint": "arab"},
    # Bahrain
    {"key": "batelco_careers", "name": "Batelco Careers",
     "url": "https://www.batelco.com/careers", "country": "Bahrain", "geo_hint": "arab"},
    # Oman
    {"key": "omantel_careers", "name": "Omantel Careers",
     "url": "https://www.omantel.om/careers", "country": "Oman", "geo_hint": "arab"},
    # Jordan
    {"key": "orange_jo_careers", "name": "Orange Jordan Careers",
     "url": "https://careers.orange.jo", "country": "Jordan", "geo_hint": "arab"},
    # Morocco
    {"key": "maroc_telecom_careers", "name": "Maroc Telecom Careers",
     "url": "https://www.iam.ma/fr/particuliers/emploi", "country": "Morocco", "geo_hint": "arab"},
]

_SECURITY_TERMS = (
    "cybersecurity", "cyber security", "information security", "infosec",
    "soc analyst", "security engineer", "penetration tester", "pentest",
    "appsec", "application security", "cloud security", "network security",
    "grc", "governance", "compliance", "iam", "identity", "vulnerability",
    "incident response", "threat intelligence", "security operations",
    "security analyst", "it security", "data protection", "ciso",
)


def _parse_arab_careers_markdown(markdown: str, spec: dict) -> list[dict]:
    """Extract security job listings from Jina markdown."""
    jobs: list[dict] = []
    lines = markdown.split("\n")
    current: dict | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped or len(stripped) < 5:
            continue
        # Skip navigation noise
        if any(skip in stripped.lower() for skip in [
            "sign in", "privacy", "cookies", "terms", "home", "about",
            "contact", "language", "linkedin", "twitter", "facebook",
        ]):
            if current and current.get("title"):
                _maybe_add_job(current, jobs)
                current = None
            continue
        # Check if line contains security keywords
        has_security = any(term in stripped.lower() for term in _SECURITY_TERMS)
        if has_security and 10 < len(stripped) < 100:
            if current and current.get("title"):
                _maybe_add_job(current, jobs)
            current = {
                "title": stripped,
                "company": spec["name"],
                "location": spec.get("country", ""),
                "url": spec["url"],
                "description": stripped,
                "source_key": spec["key"],
            }
        elif current and not stripped.startswith("http"):
            # Additional info for current job
            if len(stripped) > len(current.get("description", "")):
                current["description"] = stripped
    if current and current.get("title"):
        _maybe_add_job(current, jobs)
    return jobs


def _maybe_add_job(job: dict, jobs: list) -> None:
    """Add job if it looks valid."""
    title = job.get("title", "")
    if title and len(title) > 10 and any(term in title.lower() for term in _SECURITY_TERMS):
        jobs.append(job)


def fetch_arab_careers() -> list[Job]:
    """Fetch cybersecurity jobs from Arab company career pages."""
    jobs: list[Job] = []
    for spec in _ARAB_COMPANY_SPECS:
        try:
            jina_url = f"https://r.jina.ai/{spec['url']}"
            markdown = get_text(
                jina_url,
                headers={"Accept": "text/markdown", "X-Respond-With": "markdown"},
                timeout=12,
                budget_phase="other_sources",
            )
            if not markdown or len(markdown) < 100:
                log.debug(" Arab careers %s: no content", spec["key"])
                continue
            parsed = _parse_arab_careers_markdown(markdown, spec)
            for j in parsed:
                jobs.append(Job(
                    title=j.get("title", ""),
                    company=j.get("company", "Unknown"),
                    location=spec.get("country", ""),
                    url=j.get("url", spec["url"]),
                    source="arab_careers",
                    source_key=spec["key"],
                    description=j.get("description", ""),
                    tags=["arab", "company_careers", spec["geo_hint"]],
                    geo_hint=spec["geo_hint"],
                    origin_priority=45,
                ))
            if parsed:
                log.info(
                    " Arab careers %s: %d candidates from %s",
                    spec["key"], len(parsed), spec["country"],
                )
        except Exception as exc:
            log.debug(" Arab careers %s: error %s", spec["key"], exc)
    return jobs
