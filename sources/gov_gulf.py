"""
Gulf Government & Major Institutions — Career Pages Scraper
Covers:
  Saudi: NCA, CITC, SDAIA, NCSC, SAMA, Saudi Aramco, STC, NEOM
  UAE: UAE Cyber Council, TDRA, G42, ADNOC, du, Etisalat (e&)
  Qatar: QCERT, Ooredoo, QNB, Qatar Foundation
  Kuwait, Bahrain, Oman: CERT + major telcos
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
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}


def _scrape_career_page(url, org_name, source_key, location):
    jobs = []
    html = get_text(url, headers=HEADERS)
    if not html:
        return jobs

    patterns = [
        r'<h[2-4][^>]*>([^<]{10,120}(?:security|cyber|network|analyst|engineer|specialist|officer|architect|consultant)[^<]{0,80})</h[2-4]>',
        r'(?:وظيفة|مطلوب|career|vacancy|position|opening)[:\s]*([^\n<]{10,100})',
    ]

    found = set()
    for pat in patterns:
        for m in re.findall(pat, html, re.IGNORECASE):
            title = re.sub(r'<[^>]+>', '', m).strip()
            if title and title not in found and len(title) > 8:
                found.add(title)
                jobs.append(Job(
                    title=title, company=org_name, location=location,
                    url=url, source=source_key,
                    tags=[org_name, "government", "gulf"],
                    is_remote=False,
                ))
    return jobs


# ═══════════════════════════════════════════════════════════════
# 🇸🇦 SAUDI ARABIA
# ═══════════════════════════════════════════════════════════════

def _fetch_nca_ksa():
    """National Cybersecurity Authority — Saudi Arabia."""
    jobs = []
    urls = [
        "https://nca.gov.sa/en/careers",
        "https://nca.gov.sa/careers",
        "https://nca.gov.sa/en/job-opportunities",
    ]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "NCA Saudi Arabia", "nca_ksa", "Saudi Arabia"))

    # NCA RSS/news feed
    feed = get_text("https://nca.gov.sa/en/feed", headers=HEADERS)
    if feed:
        try:
            root = ET.fromstring(feed)
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "").strip()
                desc  = item.findtext("description", "") or ""
                if any(k in (title + desc).lower() for k in ["job", "career", "vacancy", "وظيفة", "hiring"]):
                    jobs.append(Job(
                        title=title, company="NCA Saudi Arabia",
                        location="Saudi Arabia", url=link,
                        source="nca_ksa", tags=["nca", "government", "saudi"],
                        is_remote=False,
                    ))
        except ET.ParseError:
            pass

    log.info("NCA KSA: " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_citc_ksa():
    """Communications and Information Technology Commission — KSA."""
    jobs = []
    urls = ["https://www.citc.gov.sa/en/Careers/Pages/default.aspx"]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "CITC Saudi Arabia", "citc_ksa", "Saudi Arabia"))
    log.info("CITC KSA: " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_sdaia_ksa():
    """Saudi Data and Artificial Intelligence Authority."""
    jobs = []
    urls = [
        "https://sdaia.gov.sa/en/SDAIA/about/careers",
        "https://sdaia.gov.sa/careers",
    ]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "SDAIA", "sdaia", "Saudi Arabia"))
    log.info("SDAIA: " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_saudi_aramco():
    jobs = []
    # Aramco uses a careers portal
    urls = [
        "https://www.aramco.com/en/careers/search-and-apply?q=cybersecurity",
        "https://www.aramco.com/en/careers/search-and-apply?q=security+analyst",
        "https://www.aramco.com/en/careers/search-and-apply?q=information+security",
    ]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "Saudi Aramco", "aramco", "Saudi Arabia"))

    # Aramco Greenhouse ATS
    data = get_json("https://api.greenhouse.io/v1/boards/aramco/jobs?content=true", headers=HEADERS)
    if data and "jobs" in data:
        for item in data["jobs"]:
            location = item.get("location", {}).get("name", "Saudi Arabia")
            title = item.get("title", "")
            if any(k in title.lower() for k in ["security", "cyber", "network"]):
                jobs.append(Job(
                    title=title, company="Saudi Aramco",
                    location=location,
                    url=item.get("absolute_url", "https://www.aramco.com/careers"),
                    source="aramco", tags=["aramco", "saudi"],
                    is_remote=False,
                ))

    log.info("Saudi Aramco: " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_stc_ksa():
    jobs = []
    urls = [
        "https://www.stc.com.sa/en-us/PersonalSolutions/Pages/careers.aspx",
        "https://careers.stc.com.sa/",
    ]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "STC Saudi Arabia", "stc_ksa", "Saudi Arabia"))
    log.info("STC KSA: " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_neom():
    jobs = []
    urls = ["https://www.neom.com/en-us/careers"]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "NEOM", "neom", "Saudi Arabia"))

    # NEOM uses Greenhouse
    data = get_json("https://api.greenhouse.io/v1/boards/neom/jobs?content=true", headers=HEADERS)
    if data and "jobs" in data:
        for item in data["jobs"]:
            title = item.get("title", "")
            if any(k in title.lower() for k in ["security", "cyber", "network", "it"]):
                jobs.append(Job(
                    title=title, company="NEOM",
                    location="NEOM, Saudi Arabia",
                    url=item.get("absolute_url", "https://www.neom.com/careers"),
                    source="neom", tags=["neom", "saudi"],
                    is_remote=False,
                ))

    log.info("NEOM: " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_saudi_linkedin_companies():
    """LinkedIn company page scraping for top Saudi companies."""
    import time as _time

    SAUDI_COMPANIES = [
        "nca-saudi-arabia", "saudi-aramco", "stc-saudi-arabia",
        "mobily", "zain-ksa", "sabic", "saudi-telecom-company",
        "ncbe-saudi", "siemens-saudi-arabia", "huawei-saudi",
        "cisco-saudi-arabia", "ibm-saudi-arabia",
    ]

    jobs = []
    seen_ids = set()
    cyber_keywords = ["security", "cyber", "network", "soc", "pentest"]

    for company in SAUDI_COMPANIES:
        try:
            url = (
                "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                "?keywords=security&f_C=" + company + "&start=0&count=10"
            )
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            html = get_text(url, headers=headers)
            if not html:
                continue

            job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
            if not job_ids:
                job_ids = re.findall(r'/jobs/view/(\d+)/', html)

            for job_id in job_ids[:5]:
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                detail = get_text(
                    "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/" + job_id,
                    headers=headers,
                )
                if not detail:
                    continue

                def clean(t):
                    return re.sub(r'<[^>]+>', '', t).strip()

                def extract(pat, default=""):
                    m = re.search(pat, detail, re.DOTALL)
                    return clean(m.group(1)) if m else default

                title = extract(r'<h2[^>]*class="[^"]*top-card-layout__title[^"]*"[^>]*>(.*?)</h2>')
                if not title:
                    title = extract(r'<title>(.*?)</title>')
                    title = re.sub(r'\s*\|\s*LinkedIn.*', '', title).strip()

                if not title or not any(k in title.lower() for k in cyber_keywords):
                    continue

                company_name = extract(r'<a[^>]*class="[^"]*topcard__org-name-link[^"]*"[^>]*>(.*?)</a>')
                location = extract(r'<span[^>]*class="[^"]*topcard__flavor--bullet[^"]*"[^>]*>(.*?)</span>')

                jobs.append(Job(
                    title=title,
                    company=company_name or company.replace("-", " ").title(),
                    location=location or "Saudi Arabia",
                    url="https://www.linkedin.com/jobs/view/" + job_id + "/",
                    source="linkedin_gulf_companies",
                    tags=["linkedin", "saudi", company],
                    is_remote=False,
                ))
                _time.sleep(0.3)

        except Exception as e:
            log.debug("LinkedIn Saudi " + company + ": " + str(e))

    log.info("LinkedIn Saudi Companies: " + str(len(jobs)) + " jobs")
    return jobs


# ═══════════════════════════════════════════════════════════════
# 🇦🇪 UAE
# ═══════════════════════════════════════════════════════════════

def _fetch_uae_cyber_council():
    jobs = []
    urls = [
        "https://uaecybersecurity.gov.ae/en/careers",
        "https://uaecybersecurity.gov.ae/careers",
    ]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "UAE Cybersecurity Council", "uae_cyber_council", "UAE"))
    log.info("UAE Cyber Council: " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_tdra_uae():
    jobs = []
    urls = ["https://tdra.gov.ae/en/careers"]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "TDRA UAE", "tdra_uae", "UAE"))
    log.info("TDRA UAE: " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_g42():
    jobs = []
    # G42 uses Greenhouse
    data = get_json("https://api.greenhouse.io/v1/boards/g42/jobs?content=true", headers=HEADERS)
    if data and "jobs" in data:
        for item in data["jobs"]:
            title = item.get("title", "")
            if any(k in title.lower() for k in ["security", "cyber", "network", "cloud", "ai"]):
                location = item.get("location", {}).get("name", "Abu Dhabi, UAE")
                jobs.append(Job(
                    title=title, company="G42",
                    location=location,
                    url=item.get("absolute_url", "https://www.g42.ai/careers"),
                    source="g42", tags=["g42", "uae", "ai"],
                    is_remote=False,
                ))

    urls = ["https://www.g42.ai/careers"]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "G42", "g42", "UAE"))

    log.info("G42: " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_etisalat_uae():
    jobs = []
    urls = [
        "https://www.etisalat.ae/en/about/careers/",
        "https://careers.e.com/",
    ]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "e& (Etisalat)", "etisalat_uae", "UAE"))
    log.info("Etisalat UAE: " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_du_uae():
    jobs = []
    urls = ["https://www.du.ae/en/footer/careers"]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "du Telecom UAE", "du_uae", "UAE"))
    log.info("du UAE: " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_adnoc():
    jobs = []
    urls = ["https://www.adnoc.ae/en/careers"]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "ADNOC", "adnoc", "Abu Dhabi, UAE"))
    log.info("ADNOC: " + str(len(jobs)) + " jobs")
    return jobs


# ═══════════════════════════════════════════════════════════════
# 🇶🇦 QATAR
# ═══════════════════════════════════════════════════════════════

def _fetch_qcert():
    jobs = []
    urls = [
        "https://www.qcert.org/content/careers",
        "https://qcert.org/careers",
    ]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "QCERT Qatar", "qcert", "Qatar"))
    log.info("QCERT: " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_ooredoo_qatar():
    jobs = []
    urls = ["https://www.ooredoo.qa/portal/OoredooQatar/careers"]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "Ooredoo Qatar", "ooredoo_qa", "Qatar"))
    log.info("Ooredoo Qatar: " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_qatar_foundation():
    jobs = []
    data = get_json("https://api.greenhouse.io/v1/boards/qatarfoundation/jobs?content=true", headers=HEADERS)
    if data and "jobs" in data:
        for item in data["jobs"]:
            title = item.get("title", "")
            if any(k in title.lower() for k in ["security", "cyber", "network", "it", "data"]):
                jobs.append(Job(
                    title=title, company="Qatar Foundation",
                    location="Doha, Qatar",
                    url=item.get("absolute_url", "https://qf.org.qa/careers"),
                    source="qatar_foundation", tags=["qatar", "foundation"],
                    is_remote=False,
                ))
    log.info("Qatar Foundation: " + str(len(jobs)) + " jobs")
    return jobs


# ═══════════════════════════════════════════════════════════════
# 🇰🇼 Kuwait / 🇧🇭 Bahrain / 🇴🇲 Oman
# ═══════════════════════════════════════════════════════════════

def _fetch_zain_kuwait():
    jobs = []
    urls = ["https://www.zain.com/en/kuwait/about-us/careers/"]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "Zain Kuwait", "zain_kw", "Kuwait"))
    log.info("Zain Kuwait: " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_bahrain_edb():
    jobs = []
    urls = ["https://www.bahrainedb.com/careers/"]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "Bahrain EDB", "bahrain_edb", "Bahrain"))
    log.info("Bahrain EDB: " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_oman_cert():
    jobs = []
    urls = [
        "https://www.cert.gov.om/en/careers",
        "https://cert.gov.om/careers",
    ]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "Oman CERT", "oman_cert", "Oman"))
    log.info("Oman CERT: " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_omantel():
    jobs = []
    urls = ["https://www.omantel.om/en-us/about-us/careers"]
    for url in urls:
        jobs.extend(_scrape_career_page(url, "Omantel", "omantel", "Oman"))
    log.info("Omantel: " + str(len(jobs)) + " jobs")
    return jobs


# ═══════════════════════════════════════════════════════════════
# 🌍 Gulf LinkedIn Company Pages
# ═══════════════════════════════════════════════════════════════

GULF_LINKEDIN_COMPANIES = [
    # UAE
    "g42", "etisalat", "du-telecom", "adnoc", "emirates-nbd",
    "first-abu-dhabi-bank", "mashreq-bank",
    # Qatar
    "ooredoo", "qatar-foundation", "qnb-group", "qatar-airways",
    # Kuwait
    "zain", "nbk-national-bank-of-kuwait",
    # Bahrain
    "batelco", "gulf-air",
    # Oman
    "omantel", "bank-muscat",
]

def _fetch_gulf_linkedin_companies():
    import time as _time

    jobs = []
    seen_ids = set()
    cyber_keywords = ["security", "cyber", "network", "soc", "pentest", "cloud security"]

    for company in GULF_LINKEDIN_COMPANIES:
        try:
            url = (
                "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                "?keywords=security&f_C=" + company + "&start=0&count=10"
            )
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            html = get_text(url, headers=headers)
            if not html:
                continue

            job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
            if not job_ids:
                job_ids = re.findall(r'/jobs/view/(\d+)/', html)

            for job_id in job_ids[:5]:
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                detail = get_text(
                    "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/" + job_id,
                    headers=headers,
                )
                if not detail:
                    continue

                def clean(t):
                    return re.sub(r'<[^>]+>', '', t).strip()

                def extract(pat, default=""):
                    m = re.search(pat, detail, re.DOTALL)
                    return clean(m.group(1)) if m else default

                title = extract(r'<h2[^>]*class="[^"]*top-card-layout__title[^"]*"[^>]*>(.*?)</h2>')
                if not title:
                    title = extract(r'<title>(.*?)</title>')
                    title = re.sub(r'\s*\|\s*LinkedIn.*', '', title).strip()

                if not title or not any(k in title.lower() for k in cyber_keywords):
                    continue

                company_name = extract(r'<a[^>]*class="[^"]*topcard__org-name-link[^"]*"[^>]*>(.*?)</a>')
                location = extract(r'<span[^>]*class="[^"]*topcard__flavor--bullet[^"]*"[^>]*>(.*?)</span>')

                jobs.append(Job(
                    title=title,
                    company=company_name or company.replace("-", " ").title(),
                    location=location or "Gulf",
                    url="https://www.linkedin.com/jobs/view/" + job_id + "/",
                    source="linkedin_gulf_companies",
                    tags=["linkedin", "gulf", company],
                    is_remote=False,
                ))
                _time.sleep(0.3)

        except Exception as e:
            log.debug("LinkedIn Gulf " + company + ": " + str(e))

    log.info("LinkedIn Gulf Companies: " + str(len(jobs)) + " jobs")
    return jobs


# ═══════════════════════════════════════════════════════════════
# 🌐 Gulf Aggregator Job Boards
# ═══════════════════════════════════════════════════════════════

def _fetch_tanqeeb():
    """
    Tanqeeb — Gulf-focused job platform.
    Their API endpoint changed — use website search with JSON-LD extraction.
    """
    import json
    jobs = []
    seen = set()

    searches = [
        ("cybersecurity",     "saudi-arabia", "Saudi Arabia"),
        ("cybersecurity",     "united-arab-emirates", "UAE"),
        ("security-engineer", "saudi-arabia", "Saudi Arabia"),
        ("soc-analyst",       "united-arab-emirates", "UAE"),
        ("cybersecurity",     "qatar",        "Qatar"),
        ("cybersecurity",     "kuwait",       "Kuwait"),
        ("information-security", "egypt",     "Egypt"),
    ]

    for keyword, country, location_label in searches:
        url = f"https://www.tanqeeb.com/{keyword}-jobs-in-{country}"
        html = get_text(url, headers=HEADERS, timeout=10)
        if not html:
            continue

        # Extract JSON-LD job postings
        for block in re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title = item.get("title", "").strip()
                    link = item.get("url", url)
                    org = item.get("hiringOrganization", {})
                    company = org.get("name", "").strip() if isinstance(org, dict) else ""
                    if not title or link in seen:
                        continue
                    seen.add(link)
                    jobs.append(Job(
                        title=title, company=company or "Tanqeeb Employer",
                        location=location_label, url=link,
                        source="tanqeeb", tags=["tanqeeb", keyword],
                        is_remote=False,
                    ))
            except (json.JSONDecodeError, KeyError):
                continue

    log.info("Tanqeeb: " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_akhtaboot():
    """
    Akhtaboot — Jordan & Gulf job board.
    RSS URL pattern changed — use /en/jobs/search RSS.
    """
    import json
    jobs = []
    seen = set()

    searches = [
        ("cybersecurity",     "jordan",        "Jordan"),
        ("cybersecurity",     "saudi-arabia",  "Saudi Arabia"),
        ("cybersecurity",     "uae",           "UAE"),
        ("information-security", "uae",        "UAE"),
        ("soc-analyst",       "saudi-arabia",  "Saudi Arabia"),
        ("security-engineer", "uae",           "UAE"),
    ]

    for keyword, country, location_label in searches:
        # Akhtaboot search pages embed JSON-LD
        url = f"https://www.akhtaboot.com/en/jobs/{keyword}/{country}"
        html = get_text(url, headers=HEADERS, timeout=10)
        if not html:
            # Also try their RSS with the correct path
            rss = f"https://www.akhtaboot.com/rss/{keyword}-jobs/{country}"
            xml = get_text(rss, headers=HEADERS, timeout=8)
            if xml and xml.strip().startswith("<"):
                try:
                    root = ET.fromstring(xml)
                    for item in root.findall(".//item"):
                        title = item.findtext("title", "").strip()
                        link  = item.findtext("link",  "").strip()
                        if not title or not link or link in seen:
                            continue
                        seen.add(link)
                        jobs.append(Job(
                            title=title,
                            company=item.findtext("author", "").strip() or "Unknown",
                            location=location_label,
                            url=link, source="akhtaboot", tags=["akhtaboot"],
                            is_remote=False,
                        ))
                except ET.ParseError:
                    pass
            continue

        # Extract JSON-LD from page
        for block in re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title = item.get("title", "").strip()
                    link = item.get("url", url)
                    org = item.get("hiringOrganization", {})
                    company = org.get("name", "").strip() if isinstance(org, dict) else ""
                    if not title or link in seen:
                        continue
                    seen.add(link)
                    jobs.append(Job(
                        title=title, company=company or "Akhtaboot Employer",
                        location=location_label, url=link,
                        source="akhtaboot", tags=["akhtaboot"],
                        is_remote=False,
                    ))
            except (json.JSONDecodeError, KeyError):
                continue

    log.info("Akhtaboot: " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_gulfjobsmarket():
    """
    GulfJobsMarket — RSS feeds.
    Site times out often — use short timeout and skip silently.
    RSS URL pattern corrected.
    """
    jobs = []
    feeds = [
        ("https://www.gulfjobsmarket.com/cybersecurity-jobs-in-saudi-arabia/feed/", "Saudi Arabia"),
        ("https://www.gulfjobsmarket.com/cybersecurity-jobs-in-uae/feed/", "UAE"),
        ("https://www.gulfjobsmarket.com/information-security-jobs-in-uae/feed/", "UAE"),
        ("https://www.gulfjobsmarket.com/security-engineer-jobs-in-saudi-arabia/feed/", "Saudi Arabia"),
        ("https://www.gulfjobsmarket.com/cybersecurity-jobs-in-qatar/feed/", "Qatar"),
    ]
    for rss_url, location in feeds:
        xml = get_text(rss_url, headers=HEADERS, timeout=8)  # fail fast
        if not xml or not xml.strip().startswith("<"):
            continue
        try:
            root = ET.fromstring(xml)
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "").strip()
                if not title or not link:
                    continue
                jobs.append(Job(
                    title=title,
                    company=item.findtext("author", "").strip() or "Unknown",
                    location=location,
                    url=link, source="gulfjobsmarket", tags=["gulf"],
                    is_remote=False,
                ))
        except ET.ParseError:
            pass

    log.info("GulfJobsMarket: " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_drjobpro():
    """
    Dr.Job Pro — Arab job board covering Egypt + Gulf.
    RSS path /jobs/{kw}/{country}/rss gives 404.
    Use their search page with JSON-LD extraction instead.
    """
    import json
    jobs = []
    seen = set()

    searches = [
        ("cybersecurity",        "egypt",        "Egypt"),
        ("information-security", "egypt",        "Egypt"),
        ("cybersecurity",        "saudi-arabia", "Saudi Arabia"),
        ("soc-analyst",          "saudi-arabia", "Saudi Arabia"),
        ("cybersecurity",        "uae",          "UAE"),
        ("security-engineer",    "uae",          "UAE"),
    ]

    for keyword, country, location_label in searches:
        url = f"https://www.drjobpro.com/{keyword}-jobs-in-{country}"
        html = get_text(url, headers=HEADERS, timeout=10)
        if not html:
            continue

        for block in re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title = item.get("title", "").strip()
                    link = item.get("url", url)
                    org = item.get("hiringOrganization", {})
                    company = org.get("name", "").strip() if isinstance(org, dict) else ""
                    if not title or link in seen:
                        continue
                    seen.add(link)
                    jobs.append(Job(
                        title=title, company=company or "DrJobPro Employer",
                        location=location_label, url=link,
                        source="drjobpro", tags=["drjobpro"],
                        is_remote=False,
                    ))
            except (json.JSONDecodeError, KeyError):
                continue

    log.info("DrJobPro: " + str(len(jobs)) + " jobs")
    return jobs


# ═══════════════════════════════════════════════════════════════
# 🌍 Aggregate
# ═══════════════════════════════════════════════════════════════

def fetch_gov_gulf():
    """Fetch from all Gulf government, official, and aggregator sources."""
    all_jobs = []
    fetchers = [
        # Saudi
        _fetch_nca_ksa,
        _fetch_citc_ksa,
        _fetch_sdaia_ksa,
        _fetch_saudi_aramco,
        _fetch_stc_ksa,
        _fetch_neom,
        _fetch_saudi_linkedin_companies,
        # UAE
        _fetch_uae_cyber_council,
        _fetch_tdra_uae,
        _fetch_g42,
        _fetch_etisalat_uae,
        _fetch_du_uae,
        _fetch_adnoc,
        # Qatar
        _fetch_qcert,
        _fetch_ooredoo_qatar,
        _fetch_qatar_foundation,
        # Kuwait / Bahrain / Oman
        _fetch_zain_kuwait,
        _fetch_bahrain_edb,
        _fetch_oman_cert,
        _fetch_omantel,
        # Gulf LinkedIn
        _fetch_gulf_linkedin_companies,
        # Gulf Aggregators
        _fetch_tanqeeb,
        _fetch_akhtaboot,
        _fetch_gulfjobsmarket,
        _fetch_drjobpro,
    ]
    for fn in fetchers:
        try:
            all_jobs.extend(fn())
        except Exception as e:
            log.warning("gov_gulf sub-fetcher " + fn.__name__ + " failed: " + str(e))
    return all_jobs
