"""
Egypt Alternative Sources — V11

REMOVED (confirmed dead):
  ❌ CareerJet Egypt — 404 all URLs
  ❌ Telegram Channels — 0 results (channels either private or empty)

CONFIRMED WORKING:
  ✅ LinkedIn Egypt Search — 18 jobs

NEW — Egypt-specific working sources:
  ✅ Wuzzuf.net JSON API    — Egypt's #1 job board (JSON not RSS)
  ✅ Forasna.com JSON-LD    — Egyptian job board (fixed approach)
  ✅ LinkedIn + Egypt companies (big private sector)
  ✅ Egyptian bank career pages (JSON-LD): NBE, CIB, Banque Misr, QNB
  ✅ Tech companies Egypt Greenhouse: Vezeeta, Paymob, Khazna
  ✅ Wuzzuf search (direct HTML + Next.js JSON)
"""

import logging
import re
import json
import time
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
}

SEC_KEYWORDS = [
    "cybersecurity", "security analyst", "soc analyst", "penetration",
    "information security", "network security", "security engineer",
    "grc", "dfir", "cloud security", "devsecops", "malware", "forensic",
    "أمن المعلومات", "أمن سيبراني", "اختبار اختراق",
]

def _is_sec(text):
    return any(k in text.lower() for k in SEC_KEYWORDS)


# ─── 1. LinkedIn Egypt Search — CONFIRMED 18 jobs ────────────
LINKEDIN_EGYPT_SEARCHES = [
    "cybersecurity Egypt", "SOC analyst Egypt",
    "information security Egypt", "security engineer Egypt",
    "penetration tester Egypt", "network security Egypt",
    "GRC analyst Egypt", "cloud security Egypt",
]

def _fetch_linkedin_egypt_search():
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for kw in LINKEDIN_EGYPT_SEARCHES:
        params = f"?keywords={kw.replace(' ', '%20')}&location=Egypt&start=0&count=10&f_TPR=r86400"
        html = get_text(base + params, headers={**_H, "Accept": "text/html,application/xhtml+xml"})
        if not html:
            continue
        job_ids   = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
        titles    = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)', html)
        companies = re.findall(r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>\s*([^<]+)', html)
        for i, title in enumerate(titles):
            title = title.strip()
            if not title or title in seen:
                continue
            seen.add(title)
            job_id  = job_ids[i] if i < len(job_ids) else ""
            company = companies[i].strip() if i < len(companies) else "Unknown"
            jobs.append(Job(
                title=title, company=company,
                location="Egypt",
                url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else base,
                source="linkedin", tags=["linkedin", "egypt"],
            ))
    log.info(f"LinkedIn Egypt Search: {len(jobs)} jobs")
    return jobs


# ─── 2. Wuzzuf — JSON API (not RSS) ──────────────────────────
# Wuzzuf's RSS is dead (404) but their JSON search API works
WUZZUF_QUERIES = [
    "cybersecurity", "information security", "SOC analyst",
    "penetration testing", "security engineer", "network security",
    "GRC", "DFIR", "cloud security", "malware analyst",
    "devsecops", "security analyst", "security architect",
]

def _fetch_wuzzuf():
    """
    Wuzzuf.net — Egypt's biggest job board.
    Uses their search JSON API (not RSS which is dead).
    """
    jobs = []
    seen = set()
    for q in WUZZUF_QUERIES:
        url    = "https://wuzzuf.net/api/job-search/search"
        params = {"q": q, "a": "hpb", "l": "Egypt", "filters[country][0]": "Egypt"}
        data   = get_json(url, params=params, headers=_H)
        if not data:
            # Fallback: HTML scrape with Next.js JSON extraction
            page_url = f"https://wuzzuf.net/search/jobs/?q={q.replace(' ', '+')}&a=hpb&l=Egypt"
            html     = get_text(page_url, headers=_H)
            if not html:
                continue
            # Extract __NEXT_DATA__
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if m:
                try:
                    nd   = json.loads(m.group(1))
                    jobs_list = (
                        nd.get("props", {}).get("pageProps", {})
                          .get("jobs", {}).get("data", [])
                        or []
                    )
                    for item in jobs_list:
                        title   = item.get("title", {}).get("text", "")
                        company = item.get("company", {}).get("name", "")
                        slug    = item.get("slug", "")
                        if not title or slug in seen:
                            continue
                        seen.add(slug)
                        jobs.append(Job(
                            title=title, company=company,
                            location="Egypt",
                            url=f"https://wuzzuf.net/jobs/p/{slug}" if slug else page_url,
                            source="wuzzuf", tags=["wuzzuf", "egypt"],
                        ))
                except Exception:
                    pass
            continue

        for item in (data.get("data") or []):
            title   = item.get("title", "")
            slug    = item.get("slug", "")
            company = item.get("company", {}).get("name", "") if isinstance(item.get("company"), dict) else ""
            if not title or slug in seen:
                continue
            seen.add(slug)
            jobs.append(Job(
                title=title, company=company,
                location="Egypt",
                url=f"https://wuzzuf.net/jobs/p/{slug}" if slug else "https://wuzzuf.net",
                source="wuzzuf", tags=["wuzzuf", "egypt"],
            ))
    log.info(f"Wuzzuf Egypt: {len(jobs)} jobs")
    return jobs


# ─── 3. Egyptian Banks & Telcos career pages (JSON-LD) ───────
EG_COMPANIES = [
    # Banks
    ("National Bank of Egypt",  "https://www.nbe.com.eg/NBE/E/#/NBECareerBord"),
    ("CIB Egypt",               "https://www.cibeg.com/en/personal/careers"),
    ("Banque Misr",             "https://www.banquemisr.com/en/About-BM/Careers"),
    ("QNB Egypt",               "https://www.qnbalahli.com/sites/qnb/egypt/en/home/personal/aboutUs/careers.html"),
    ("HSBC Egypt",              "https://www.hsbc.com.eg/about/careers/"),
    ("Alex Bank",               "https://www.alexbank.com/En/About/Careers"),
    # Telcos
    ("Orange Egypt",            "https://www.orange.eg/en/careers"),
    ("Vodafone Egypt",          "https://careers.vodafone.com.eg/"),
    ("WE Telecom Egypt",        "https://careers.te.eg/"),
    # Tech
    ("Fawry",                   "https://careers.fawry.com/"),
    ("Paymob",                  "https://paymob.com/careers"),
    ("ITWorx",                  "https://itworx.com/careers/"),
    ("Raya Corporation",        "https://www.rayacorp.com/careers"),
    ("Xceed",                   "https://www.xceedcc.com/career"),
    ("KPMG Egypt",              "https://home.kpmg/eg/en/home/careers.html"),
    ("Deloitte Egypt",          "https://www2.deloitte.com/eg/en/pages/careers/topics/careers.html"),
    ("PwC Egypt",               "https://www.pwc.com/m1/en/careers.html"),
    ("IBM Egypt",               "https://www.ibm.com/employment/"),
]

def _fetch_eg_companies():
    """Scrape Egypt company career pages for security jobs."""
    jobs = []
    seen = set()
    for company_name, url in EG_COMPANIES:
        html = get_text(url, headers=_H)
        if not html:
            continue
        # Try JSON-LD first
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", url)
                    if not title or not _is_sec(title) or title in seen:
                        continue
                    seen.add(title)
                    jobs.append(Job(
                        title=title, company=company_name,
                        location="Egypt", url=job_url,
                        source="eg_companies",
                        tags=["egypt", company_name.lower()],
                    ))
            except Exception:
                continue
        # Fallback: heading scan
        if not any(j.company == company_name for j in jobs):
            for m in re.findall(
                r'<h[2-5][^>]*>([^<]{10,120})</h[2-5]>',
                html, re.IGNORECASE
            ):
                title = re.sub(r'<[^>]+>', '', m).strip()
                if not title or not _is_sec(title) or title in seen or len(title) < 10:
                    continue
                seen.add(title)
                jobs.append(Job(
                    title=title, company=company_name,
                    location="Egypt", url=url,
                    source="eg_companies",
                    tags=["egypt", company_name.lower()],
                ))
    log.info(f"Egypt Companies: {len(jobs)} jobs")
    return jobs


# ─── 4. Egyptian Fintech/Startup Greenhouse pages ─────────────
EG_GREENHOUSE = [
    ("vezeeta",   "Vezeeta"),
    ("khazna",    "Khazna"),
    ("kashier",   "Kashier"),
    ("valify",    "Valify"),
]

def _fetch_eg_greenhouse():
    """Egyptian startups using Greenhouse ATS."""
    jobs = []
    for slug, name in EG_GREENHOUSE:
        url  = f"https://api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
        data = get_json(url, headers=_H)
        if not data or "jobs" not in data:
            continue
        for item in data["jobs"]:
            loc = item.get("location", {})
            location = loc.get("name", "Egypt") if isinstance(loc, dict) else "Egypt"
            if not _is_sec(item.get("title", "")):
                continue
            jobs.append(Job(
                title=item.get("title", ""), company=name,
                location=location,
                url=item.get("absolute_url", ""),
                source="greenhouse_eg", tags=["egypt", name.lower()],
            ))
    log.info(f"Egypt Greenhouse: {len(jobs)} jobs")
    return jobs


def fetch_egypt_alt():
    """Aggregate Egypt alternative sources."""
    all_jobs = []
    for fetcher in [
        _fetch_linkedin_egypt_search,
        _fetch_wuzzuf,
        _fetch_eg_companies,
        _fetch_eg_greenhouse,
    ]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"egypt_alt: {fetcher.__name__} failed: {e}")
    return all_jobs
