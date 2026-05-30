"""LinkedIn company-name search source for MENA cybersecurity roles.

This source intentionally avoids f_C company slugs. It searches LinkedIn by
company name + cybersecurity role + location, which is more resilient when
LinkedIn changes company identifiers.
"""

from __future__ import annotations

import logging
import time

import config
from models import Job
from sources.linkedin_common import FRESH_TPR, linkedin_get_text
from sources.linkedin_unified import (
    DETAIL_URL,
    SEARCH_URL,
    _extract_job_ids,
    _geo_hint_from_query_location,
    _parse_detail,
)

log = logging.getLogger(__name__)

SOURCE_KEY = "linkedin_company_search"

COMPANY_TARGETS: list[tuple[str, str]] = [
    ("CyberTalents", "Egypt"),
    ("Nile Bits Cybersecurity", "Egypt"),
    ("Telecom Egypt", "Egypt"),
    ("Vodafone Egypt", "Egypt"),
    ("Orange Egypt", "Egypt"),
    ("CIB Egypt", "Egypt"),
    ("National Bank of Egypt", "Egypt"),
    ("Central Bank of Egypt", "Egypt"),
    ("National Cybersecurity Authority", "Saudi Arabia"),
    ("stc", "Saudi Arabia"),
    ("SITE", "Saudi Arabia"),
    ("Elm", "Saudi Arabia"),
    ("Mobily", "Saudi Arabia"),
    ("Al Rajhi Bank", "Saudi Arabia"),
    ("Saudi National Bank", "Saudi Arabia"),
    ("UAE Cyber Security Council", "United Arab Emirates"),
    ("e&", "United Arab Emirates"),
    ("du", "United Arab Emirates"),
    ("G42", "United Arab Emirates"),
    ("First Abu Dhabi Bank", "United Arab Emirates"),
    ("ADCB", "United Arab Emirates"),
    ("QNB", "Qatar"),
    ("Ooredoo", "Qatar"),
    ("National Bank of Kuwait", "Kuwait"),
    ("Bank Muscat", "Oman"),
    ("Bank ABC", "Bahrain"),
]

ROLE_TARGETS: list[str] = [
    "cybersecurity",
    "information security",
    "SOC analyst",
    "GRC analyst",
    "cloud security",
    "application security",
    "IAM security",
    "vulnerability management",
    "penetration tester",
]


def fetch_linkedin_company_search() -> list[Job]:
    budget_seconds = int(getattr(config, "LINKEDIN_COMPANY_SEARCH_BUDGET_SECONDS", 180))
    start = time.time()
    jobs: list[Job] = []
    seen_ids: set[str] = set()

    for company, location in COMPANY_TARGETS:
        if time.time() - start > budget_seconds:
            log.info("LinkedIn company search: budget exhausted at %d jobs", len(jobs))
            break
        for role in ROLE_TARGETS[:4]:
            if time.time() - start > budget_seconds:
                break
            params = {
                "keywords": f"{company} {role}",
                "location": location,
                "start": "0",
                "count": "15",
                "f_TPR": FRESH_TPR,
            }
            html = linkedin_get_text(SEARCH_URL, params=params)
            if not html:
                continue
            for job_id in _extract_job_ids(html)[:8]:
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)
                detail_html = linkedin_get_text(DETAIL_URL.format(job_id=job_id))
                if not detail_html:
                    continue
                job = _parse_detail(
                    detail_html,
                    job_id=job_id,
                    source_key=SOURCE_KEY,
                    origin_priority=18,
                    geo_hint=_geo_hint_from_query_location(location),
                )
                if not isinstance(job, Job):
                    continue
                job.source = SOURCE_KEY
                job.original_source = f"LinkedIn company search: {company}"
                job.tags = list(dict.fromkeys((job.tags or []) + ["linkedin", "company-search", company.lower()]))
                jobs.append(job)
            time.sleep(0.8)

    log.info("LinkedIn company search: %d jobs", len(jobs))
    return jobs
