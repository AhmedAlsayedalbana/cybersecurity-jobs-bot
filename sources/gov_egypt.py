"""
Egyptian Government & Official Institutions — Career Pages Scraper
Covers:
  - EG-CERT, ITIDA, ITI, MCIT, NTI, NTRA, DEPI, NCSC, TIEC
  - CBE, Banks, Major SOEs
  - Smart Village, Egypt ICT Trust Fund
  - Ministry of Finance IT, CAOA
"""

import logging
import re
import xml.etree.ElementTree as ET
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
}

# ─── Helper: Generic HTML career page scraper ────────────────

def _scrape_career_page(url, org_name, source_key, location="Egypt"):
    """Scrape a simple HTML careers page for job listings."""
    jobs = []
    html = get_text(url, headers=HEADERS)
    if not html:
        return jobs

    # Try to find job titles via common HTML patterns
    patterns = [
        r'<h[2-4][^>]*>([^<]{10,120}(?:security|cyber|network|analyst|engineer|specialist|officer|مهندس|محلل|أمن)[^<]{0,80})</h[2-4]>',
        r'<a[^>]*href=["\']([^"\']*(?:job|career|vacancy|position|وظيفة)[^"\']*)["\'][^>]*>([^<]{10,100})</a>',
        r'(?:وظيفة|فرصة عمل|مطلوب)[:\s]*([^\n<]{10,100})',
    ]

    found_titles = set()
    for pat in patterns:
        matches = re.findall(pat, html, re.IGNORECASE)
        for m in matches:
            title = m if isinstance(m, str) else (m[1] if len(m) > 1 else m[0])
            title = re.sub(r'<[^>]+>', '', title).strip()
            if title and title not in found_titles and len(title) > 8:
                found_titles.add(title)
                jobs.append(Job(
                    title=title,
                    company=org_name,
                    location=location,
                    url=url,
                    source=source_key,
                    tags=[org_name, "government", "egypt"],
                    is_remote=False,
                ))
    return jobs


# ─── EG-CERT ──────────────────────────────────────────────────
def _fetch_egcert():
    jobs = []
    urls = [
        "https://www.egcert.eg/careers/",
        "https://www.egcert.eg/ar/careers/",
    ]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "EG-CERT", "egcert"))

    # Also check their news/announcements for job postings
    news_url = "https://www.egcert.eg/feed/"
    xml = get_text(news_url, headers=HEADERS)
    if xml:
        try:
            root = ET.fromstring(xml)
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "").strip()
                desc  = item.findtext("description", "") or ""
                if not title or not link:
                    continue
                combined = (title + " " + desc).lower()
                if any(k in combined for k in ["وظيفة", "مطلوب", "career", "job", "hiring", "vacancy", "تعيين"]):
                    jobs.append(Job(
                        title=title, company="EG-CERT",
                        location="Egypt", url=link,
                        source="egcert", tags=["egcert", "government"],
                        is_remote=False,
                    ))
        except ET.ParseError:
            pass

    log.info("EG-CERT: " + str(len(jobs)) + " jobs")
    return jobs


# ─── ITIDA ────────────────────────────────────────────────────
def _fetch_itida():
    jobs = []
    urls = [
        "https://itida.gov.eg/English/Programs/Pages/Careers.aspx",
        "https://itida.gov.eg/Arabic/Programs/Pages/Careers.aspx",
        "https://itida.gov.eg/careers",
    ]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "ITIDA", "itida"))

    # ITIDA RSS/News
    feed = get_text("https://itida.gov.eg/feed", headers=HEADERS)
    if feed:
        try:
            root = ET.fromstring(feed)
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link", "").strip()
                desc  = item.findtext("description", "") or ""
                combined = (title + " " + desc).lower()
                if any(k in combined for k in ["وظيفة", "career", "job", "hiring", "vacancy", "program", "برنامج"]):
                    jobs.append(Job(
                        title=title, company="ITIDA",
                        location="Egypt", url=link,
                        source="itida", tags=["itida", "government"],
                        is_remote=False,
                    ))
        except ET.ParseError:
            pass

    log.info("ITIDA: " + str(len(jobs)) + " jobs")
    return jobs


# ─── ITI ──────────────────────────────────────────────────────
def _fetch_iti():
    jobs = []
    urls = [
        "https://www.iti.gov.eg/ITI/Careers",
        "https://www.iti.gov.eg/ITI/Programs",
        "https://iti.gov.eg/careers",
    ]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "ITI", "iti"))

    # ITI Programs — treat training programs as opportunities
    programs_url = "https://www.iti.gov.eg/ITI/Programs"
    html = get_text(programs_url, headers=HEADERS)
    if html:
        program_matches = re.findall(
            r'(?:Cybersecurity|Information Security|Network Security|Digital|Security)[^<\n]{0,60}(?:Program|Track|Course|Diploma)',
            html, re.IGNORECASE
        )
        for match in program_matches[:5]:
            jobs.append(Job(
                title="[Program] " + match.strip(),
                company="ITI",
                location="Egypt",
                url=programs_url,
                source="iti",
                tags=["iti", "training", "program", "egypt"],
                is_remote=False,
            ))

    log.info("ITI: " + str(len(jobs)) + " jobs")
    return jobs


# ─── DEPI (Digital Egypt Pioneers Initiative) ────────────────
def _fetch_depi():
    jobs = []
    urls = [
        "https://depi.gov.eg/",
        "https://depi.gov.eg/tracks",
        "https://depi.gov.eg/cybersecurity",
    ]
    for url in urls:
        html = get_text(url, headers=HEADERS)
        if not html:
            continue
        # Look for cybersecurity tracks
        tracks = re.findall(
            r'(?:Cybersecurity|Security|Ethical Hack|SOC|Pentest|Network Security)[^<\n]{0,80}(?:Track|Course|Program|Initiative)',
            html, re.IGNORECASE
        )
        for t in set(tracks[:5]):
            jobs.append(Job(
                title="[DEPI Track] " + t.strip(),
                company="DEPI - Digital Egypt Pioneers",
                location="Egypt",
                url=url,
                source="depi",
                tags=["depi", "training", "scholarship", "egypt"],
                is_remote=True,
            ))

    # Check for job postings at DEPI
    jobs.extend(_scrape_career_page("https://depi.gov.eg/careers", "DEPI", "depi"))

    log.info("DEPI: " + str(len(jobs)) + " jobs")
    return jobs


# ─── NTI (National Telecom Institute) ────────────────────────
def _fetch_nti():
    jobs = []
    urls = [
        "https://www.nti.sci.eg/en/careers",
        "https://www.nti.sci.eg/careers",
        "https://nti.sci.eg/jobs",
    ]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "NTI", "nti"))

    # NTI training courses
    courses_url = "https://www.nti.sci.eg/en/training"
    html = get_text(courses_url, headers=HEADERS)
    if html:
        courses = re.findall(
            r'(?:Cybersecurity|Security|CEH|CISSP|CompTIA|Network\+|Ethical|SOC|Pentest)[^<\n]{0,60}',
            html, re.IGNORECASE
        )
        for c in set(courses[:5]):
            jobs.append(Job(
                title="[NTI Course] " + c.strip(),
                company="NTI",
                location="Egypt",
                url=courses_url,
                source="nti",
                tags=["nti", "training", "certification", "egypt"],
                is_remote=False,
            ))

    log.info("NTI: " + str(len(jobs)) + " jobs")
    return jobs


# ─── NTRA ────────────────────────────────────────────────────
def _fetch_ntra():
    jobs = []
    urls = [
        "https://www.tra.gov.eg/en/about-ntra/careers/",
        "https://www.tra.gov.eg/careers",
    ]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "NTRA", "ntra"))
    log.info("NTRA: " + str(len(jobs)) + " jobs")
    return jobs


# ─── MCIT ────────────────────────────────────────────────────
def _fetch_mcit():
    jobs = []
    urls = [
        "https://mcit.gov.eg/en/Careers",
        "https://mcit.gov.eg/ar/Careers",
    ]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "MCIT", "mcit"))
    log.info("MCIT: " + str(len(jobs)) + " jobs")
    return jobs


# ─── TIEC ────────────────────────────────────────────────────
def _fetch_tiec():
    jobs = []
    urls = [
        "https://tiec.gov.eg/en/careers",
        "https://tiec.gov.eg/jobs",
    ]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "TIEC", "tiec"))
    log.info("TIEC: " + str(len(jobs)) + " jobs")
    return jobs


# ─── CBE (Central Bank Egypt) ────────────────────────────────
def _fetch_cbe():
    jobs = []
    urls = [
        "https://www.cbe.org.eg/en/careers",
        "https://www.cbe.org.eg/careers",
    ]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "Central Bank of Egypt", "cbe"))
    log.info("CBE: " + str(len(jobs)) + " jobs")
    return jobs


# ─── Egypt ICT Trust Fund / Smart Village ─────────────────────
def _fetch_smart_village():
    jobs = []
    urls = [
        "https://www.smartvillage.com.eg/careers",
        "https://www.smartvillage.com.eg/jobs",
    ]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "Smart Village Egypt", "smart_village"))
    log.info("Smart Village: " + str(len(jobs)) + " jobs")
    return jobs


# ─── Egyptian Banks IT Security Jobs ─────────────────────────
EGYPT_BANKS = [
    ("https://www.cib.eg/en/careers", "CIB Egypt", "cib_egypt"),
    ("https://www.banquemisr.com/en/careers", "Banque Misr", "banque_misr"),
    ("https://www.nbe.com.eg/NBE/careers", "National Bank of Egypt", "nbe"),
    ("https://careers.alexbank.com", "Alex Bank", "alex_bank"),
    ("https://www.hsbc.com.eg/careers", "HSBC Egypt", "hsbc_egypt"),
    ("https://www.qnbalahli.com/sites/qnb/EgyptEnglish/page/careers.html", "QNB Egypt", "qnb_egypt"),
]

def _fetch_egypt_banks():
    jobs = []
    for url, name, key in EGYPT_BANKS:
        fetched = _scrape_career_page(url, name, key)
        jobs.extend(fetched)
    log.info("Egypt Banks: " + str(len(jobs)) + " jobs")
    return jobs


# ─── Egyptian Telecom & Tech Companies ───────────────────────
EGYPT_TECH_COMPANIES = [
    ("https://www.vodafone.com.eg/careers", "Vodafone Egypt", "vodafone_eg"),
    ("https://careers.orange.eg", "Orange Egypt", "orange_eg"),
    ("https://www.te.eg/careers", "Telecom Egypt (WE)", "telecom_egypt"),
    ("https://www.rayacorp.com/careers", "Raya Corporation", "raya"),
    ("https://fawry.com/careers", "Fawry", "fawry"),
    ("https://www.paymob.com/careers", "Paymob", "paymob"),
    ("https://careers.ibm.com/job?&location=Egypt", "IBM Egypt", "ibm_egypt"),
    ("https://jobs.cisco.com/jobs/SearchJobs/?locationStr=Egypt", "Cisco Egypt", "cisco_egypt"),
    ("https://www.huawei.com/en/careers?country=egypt", "Huawei Egypt", "huawei_egypt"),
    ("https://careers.microsoft.com/v2/global/en/search?lc=Egypt", "Microsoft Egypt", "microsoft_egypt"),
]

def _fetch_egypt_tech():
    jobs = []
    for url, name, key in EGYPT_TECH_COMPANIES:
        fetched = _scrape_career_page(url, name, key)
        jobs.extend(fetched)
    log.info("Egypt Tech Companies: " + str(len(jobs)) + " jobs")
    return jobs


# ─── Egypt Cybersecurity Firms ───────────────────────────────
EGYPT_CYBER_FIRMS = [
    ("https://www.help.ag/careers", "Help AG Egypt", "helpag_egypt"),
    ("https://eg.kpmg.com/en/home/careers.html", "KPMG Egypt", "kpmg_egypt"),
    ("https://www2.deloitte.com/eg/en/careers.html", "Deloitte Egypt", "deloitte_egypt"),
    ("https://www.ey.com/en_eg/careers", "EY Egypt", "ey_egypt"),
    ("https://www.pwc.com/m1/en/careers/egypt.html", "PwC Egypt", "pwc_egypt"),
]

def _fetch_egypt_cyber_firms():
    jobs = []
    for url, name, key in EGYPT_CYBER_FIRMS:
        fetched = _scrape_career_page(url, name, key)
        jobs.extend(fetched)
    log.info("Egypt Cyber Firms: " + str(len(jobs)) + " jobs")
    return jobs


# ─── LinkedIn: Egyptian Government & Major Companies ─────────
EGYPT_LINKEDIN_COMPANIES = [
    # Government / Official
    "eg-cert", "itida", "iti-egypt", "mcit-egypt", "nti-egypt",
    "tiec", "depi-egypt", "smart-village",
    # Telecom
    "vodafone-egypt", "orange-egypt", "telecom-egypt",
    # Banks
    "commercial-international-bank-egypt-cib", "banque-misr",
    "national-bank-of-egypt", "qnb-egypt",
    # Tech
    "raya-holding", "fawry", "paymob", "ibm", "cisco",
    "huawei", "microsoft", "dell-technologies",
    # Cyber
    "help-ag", "kpmg", "deloitte", "ey", "pwc",
]

def _fetch_egypt_linkedin_companies():
    """Fetch job listings directly from Egyptian company LinkedIn pages."""
    from sources.http_utils import get_text
    import time

    jobs = []
    seen_ids = set()

    SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

    for company_slug in EGYPT_LINKEDIN_COMPANIES:
        params = {
            "f_C": company_slug,
            "keywords": "security",
            "start": "0",
            "count": "10",
        }
        try:
            import re as _re
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
            url = (
                "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                "?keywords=security&f_C=" + company_slug + "&start=0&count=10"
            )
            html = get_text(url, headers=headers)
            if not html:
                continue

            job_ids = _re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
            if not job_ids:
                job_ids = _re.findall(r'/jobs/view/(\d+)/', html)

            for job_id in job_ids[:5]:
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                detail_html = get_text(
                    "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/" + job_id,
                    headers=headers,
                )
                if not detail_html:
                    continue

                def clean(text):
                    return _re.sub(r'<[^>]+>', '', text).strip()

                def extract(pat, default=""):
                    m = _re.search(pat, detail_html, _re.DOTALL)
                    return clean(m.group(1)) if m else default

                title = extract(r'<h2[^>]*class="[^"]*top-card-layout__title[^"]*"[^>]*>(.*?)</h2>')
                if not title:
                    title = extract(r'<title>(.*?)</title>')
                    title = _re.sub(r'\s*\|\s*LinkedIn.*', '', title).strip()

                company = extract(r'<a[^>]*class="[^"]*topcard__org-name-link[^"]*"[^>]*>(.*?)</a>')
                location = extract(r'<span[^>]*class="[^"]*topcard__flavor--bullet[^"]*"[^>]*>(.*?)</span>')

                if not title:
                    continue

                jobs.append(Job(
                    title=title,
                    company=company or company_slug.replace("-", " ").title(),
                    location=location or "Egypt",
                    url="https://www.linkedin.com/jobs/view/" + job_id + "/",
                    source="linkedin_egypt_companies",
                    tags=["linkedin", "egypt", company_slug],
                    is_remote="remote" in (location or "").lower(),
                ))
                time.sleep(0.3)

        except Exception as e:
            log.debug("LinkedIn company " + company_slug + " failed: " + str(e))
            continue

    log.info("LinkedIn Egypt Companies: " + str(len(jobs)) + " jobs")
    return jobs


# ─── Aggregate ────────────────────────────────────────────────
def fetch_gov_egypt():
    """Fetch from all Egyptian government and official sources."""
    all_jobs = []
    fetchers = [
        _fetch_egcert,
        _fetch_itida,
        _fetch_iti,
        _fetch_depi,
        _fetch_nti,
        _fetch_ntra,
        _fetch_mcit,
        _fetch_tiec,
        _fetch_cbe,
        _fetch_smart_village,
        _fetch_egypt_banks,
        _fetch_egypt_tech,
        _fetch_egypt_cyber_firms,
        _fetch_egypt_linkedin_companies,
    ]
    for fn in fetchers:
        try:
            all_jobs.extend(fn())
        except Exception as e:
            log.warning("gov_egypt sub-fetcher " + fn.__name__ + " failed: " + str(e))
    return all_jobs
