"""Fresh Arabic LinkedIn searches for Egypt cybersecurity roles."""

import logging
import re
import time

from models import Job
from sources.linkedin_common import FRESH_TPR, linkedin_get_text
from config import LINKEDIN_SOURCE_BUDGET_SECONDS

log = logging.getLogger(__name__)

JOBS_API = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

ARABIC_SEARCHES = [
    " ",
    " ",
    " SOC",
    " ",
    "  ",
    " ",
    "  ",
    "  ",
]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def fetch_linkedin_egypt_arabic() -> list[Job]:
    jobs: list[Job] = []
    seen_ids: set[str] = set()
    start = time.time()

    for keyword in ARABIC_SEARCHES:
        if time.time() - start > LINKEDIN_SOURCE_BUDGET_SECONDS:
            log.info("linkedin_egypt_arabic: 60s budget hit � stopping early")
            break

        params = {
            "keywords": keyword,
            "location": "Egypt",
            "start": "0",
            "count": "10",
            "f_TPR": FRESH_TPR,
            "sortBy": "DD",
        }
        html = linkedin_get_text(JOBS_API, params=params)
        if not html or len(html) < 200:
            time.sleep(0.8)
            continue

        blocks = re.findall(
            r'(<li>.*?data-entity-urn="urn:li:jobPosting:\d+".*?</li>)',
            html,
            re.DOTALL,
        )
        if not blocks:
            blocks = re.findall(r'(<div[^>]+base-search-card.*?</div>\s*</li>)', html, re.DOTALL)

        for block in blocks[:8]:
            job_id_m = re.search(r'urn:li:jobPosting:(\d+)', block)
            job_id = job_id_m.group(1) if job_id_m else ""
            if job_id and job_id in seen_ids:
                continue
            if job_id:
                seen_ids.add(job_id)

            title_m = re.search(r'base-search-card__title[^>]*>\s*(.*?)\s*</', block, re.DOTALL)
            company_m = re.search(r'base-search-card__subtitle[^>]*>.*?>(.*?)</a>', block, re.DOTALL)
            loc_m = re.search(r'job-search-card__location[^>]*>\s*(.*?)\s*</', block, re.DOTALL)

            title = _clean(title_m.group(1) if title_m else "")
            if not title:
                continue

            jobs.append(Job(
                title=title,
                company=_clean(company_m.group(1) if company_m else "") or "Unknown",
                location=_clean(loc_m.group(1) if loc_m else "") or "Egypt",
                url=f"https://www.linkedin.com/jobs/view/{job_id}/" if job_id else JOBS_API,
                source="linkedin_egypt_arabic",
                original_source=f"LinkedIn Arabic Egypt � {keyword}",
                tags=["linkedin", "egypt", "arabic", keyword],
                is_remote=False,
            ))

        time.sleep(0.8)

    log.info(f"LinkedIn Egypt Arabic: {len(jobs)} jobs")
    return jobs

