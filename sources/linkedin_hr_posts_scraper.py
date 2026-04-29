"""
LinkedIn HR Posts Scraper — v1
===============================
يجيب منشورات HR على LinkedIn زي اللي في الصورة:
  "We're #Hiring — SOC Analyst | Instant Software Solutions"
  "Send CV to hr.malak8@gmail.com | WhatsApp: +20 10..."

الاستراتيجية:
  1. Google search (SerpAPI إذا موجود، وإلا DuckDuckGo HTML fallback)
     لكلمات مثل: site:linkedin.com/posts "#hiring" "cybersecurity" Egypt
  2. استخراج URLs من النتائج
  3. Scrape كل URL لاستخراج:
       - العنوان / الدور
       - اسم الشركة
       - طريقة التقديم (إيميل / WhatsApp / رابط)
  4. تحويلها لـ Job objects بـ source="linkedin_hr_post"
     حتى telegram_sender يعرضها بقالب منشورات HR الخاص

ملاحظة: هذه المنشورات مختلفة عن الوظائف الرسمية على LinkedIn Jobs API.
"""

import logging
import os
import re
import time
import random
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
MAX_BUDGET_SECS = 4 * 60  # 4 دقائق حد أقصى

# ── الكلمات المفتاحية للبحث ───────────────────────────────────

SEARCH_QUERIES = [
    # مصر — عربي
    'site:linkedin.com/posts "#hiring" "cybersecurity" Egypt',
    'site:linkedin.com/posts "#hiring" "SOC analyst" Egypt',
    'site:linkedin.com/posts "#hiring" "penetration" Egypt',
    'site:linkedin.com/posts "#hiring" "information security" Egypt',
    'site:linkedin.com/posts "#hiring" "أمن سيبراني" مصر',
    'site:linkedin.com/posts "#hiring" "GRC" Egypt',
    'site:linkedin.com/posts "#hiring" "security engineer" Egypt',
    # الخليج
    'site:linkedin.com/posts "#hiring" "cybersecurity" "Saudi Arabia"',
    'site:linkedin.com/posts "#hiring" "SOC" UAE Dubai',
    'site:linkedin.com/posts "#hiring" "cybersecurity" Kuwait',
]

# ── Role mapping لتصنيف العنوان ──────────────────────────────

_ROLE_MAP = [
    (["soc analyst", "security operations analyst"],           "SOC Analyst"),
    (["soc engineer", "security operations engineer"],         "SOC Engineer"),
    (["siem", "security monitoring"],                          "SIEM / Security Monitoring"),
    (["threat intel", "threat intelligence", "cti"],           "Threat Intelligence Analyst"),
    (["threat hunter"],                                        "Threat Hunter"),
    (["incident resp", "ir analyst", "dfir"],                  "Incident Response / DFIR"),
    (["malware analyst", "reverse eng"],                       "Malware Analyst"),
    (["penetration tester", "pen tester", "pentester"],        "Penetration Tester"),
    (["red team"],                                             "Red Team Engineer"),
    (["ethical hack", "bug bounty"],                           "Ethical Hacker / Bug Bounty"),
    (["appsec", "application security"],                       "Application Security Engineer"),
    (["devsecops"],                                            "DevSecOps Engineer"),
    (["cloud security", "aws security", "azure security"],     "Cloud Security Engineer"),
    (["network security", "firewall"],                         "Network Security Engineer"),
    (["grc", "governance risk", "compliance", "iso 27001"],    "GRC / Compliance Analyst"),
    (["ciso"],                                                 "CISO"),
    (["security architect"],                                   "Security Architect"),
    (["security engineer", "cybersecurity engineer"],          "Security Engineer"),
    (["intern", "trainee", "fresh grad", "junior"],            "Security Intern / Junior"),
    (["cybersecurity", "cyber security", "infosec"],           "Cybersecurity Specialist"),
    (["security analyst", "security specialist"],              "Security Analyst"),
    (["أمن سيبراني", "أمن معلومات"],                          "Cybersecurity Specialist"),
]

def _match_title(raw: str) -> str:
    t = raw.lower()
    for kws, canonical in _ROLE_MAP:
        if any(k in t for k in kws):
            return canonical
    return raw.strip().title()


def _detect_location(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["egypt", "cairo", "giza", "alexandria", "مصر", "القاهرة", "الإسكندرية"]):
        return "Egypt"
    if any(k in t for k in ["saudi", "riyadh", "jeddah", "ksa", "الرياض", "جدة", "السعودية"]):
        return "Saudi Arabia"
    if any(k in t for k in ["uae", "dubai", "abu dhabi", "الإمارات", "دبي"]):
        return "UAE"
    if any(k in t for k in ["kuwait", "الكويت"]):
        return "Kuwait"
    if any(k in t for k in ["qatar", "doha", "قطر"]):
        return "Qatar"
    if any(k in t for k in ["bahrain", "البحرين"]):
        return "Bahrain"
    if any(k in t for k in ["jordan", "amman", "الأردن"]):
        return "Jordan"
    return "Egypt"  # default — most HR posts in this bot are Egypt-focused


def _extract_company_from_post(text: str) -> str:
    """
    يحاول يستخرج اسم الشركة من نص المنشور.
    مثال: "SOC Analyst Instructor | Instant Software Solutions" → "Instant Software Solutions"
    """
    # Pattern: "Role | Company" أو "Role @ Company" أو "Role at Company"
    for sep in ["|", "@", " at ", " - "]:
        if sep in text:
            parts = text.split(sep)
            if len(parts) >= 2:
                company = parts[-1].strip()
                if 3 < len(company) < 80:
                    return company
    return "Unknown"


def _extract_apply_info(text: str) -> dict:
    """
    يستخرج طريقة التقديم من نص المنشور:
    - إيميل
    - WhatsApp
    - رابط تقديم
    """
    info = {}
    email_m = re.search(r'[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}', text)
    if email_m:
        info["email"] = email_m.group(0)
    wa_m = re.search(r'\+?[\d\s\-]{10,15}', text)
    if wa_m and any(k in text.lower() for k in ["whatsapp", "واتساب", "wp:", "wa:"]):
        info["whatsapp"] = wa_m.group(0).strip()
    link_m = re.search(r'https?://[^\s<>"]+', text)
    if link_m and "linkedin.com" not in link_m.group(0):
        info["apply_link"] = link_m.group(0)
    return info


def _build_description(raw_text: str, apply_info: dict) -> str:
    """يبني الـ description للوظيفة بحيث telegram_sender يعرضه صح."""
    lines = []
    if raw_text:
        # أول 300 حرف من النص الخام كـ preview
        preview = raw_text[:300].replace("\n", " ").strip()
        lines.append(preview)
    if apply_info.get("email"):
        lines.append(f"EMAIL:{apply_info['email']}")
    if apply_info.get("whatsapp"):
        lines.append(f"WHATSAPP:{apply_info['whatsapp']}")
    if apply_info.get("apply_link"):
        lines.append(f"APPLY_LINK:{apply_info['apply_link']}")
    return "\n".join(lines)


# ── SerpAPI Search ───────────────────────────────────────────

def _search_via_serpapi(query: str) -> list[str]:
    """يرجع قائمة URLs من SerpAPI."""
    if not SERPAPI_KEY:
        return []
    params = {
        "q": query,
        "api_key": SERPAPI_KEY,
        "engine": "google",
        "num": "10",
        "gl": "eg",
        "hl": "en",
    }
    try:
        data = get_json("https://serpapi.com/search", params=params, max_retries=0)
        if not data:
            return []
        results = data.get("organic_results", [])
        return [r.get("link", "") for r in results if "linkedin.com/posts" in r.get("link", "")]
    except Exception as e:
        log.debug(f"SerpAPI HR posts search failed: {e}")
        return []


def _search_via_duckduckgo(query: str) -> list[str]:
    """
    DuckDuckGo HTML fallback — بيعمل GET على /html/ ويستخرج URLs.
    لا يحتاج API key.
    """
    import urllib.parse
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        html = get_text(url, headers=headers)
        if not html:
            return []
        # استخراج روابط LinkedIn posts
        found = re.findall(r'href="(https://www\.linkedin\.com/posts/[^"&]+)"', html)
        # أحيانًا تكون مشفرة
        if not found:
            found = re.findall(r'uddg=(https?%3A%2F%2F[^&"]+linkedin[^&"]+)', html)
            found = [urllib.parse.unquote(u) for u in found if "linkedin.com/posts" in urllib.parse.unquote(u)]
        return list(dict.fromkeys(found))[:5]  # أول 5 روابط فريدة
    except Exception as e:
        log.debug(f"DuckDuckGo HR posts search failed: {e}")
        return []


def _search_urls(query: str) -> list[str]:
    """يجرب SerpAPI أولاً، ثم DuckDuckGo كـ fallback."""
    if SERPAPI_KEY:
        urls = _search_via_serpapi(query)
        if urls:
            return urls
    return _search_via_duckduckgo(query)


# ── LinkedIn Post Scraper ────────────────────────────────────

def _scrape_linkedin_post(url: str) -> dict | None:
    """
    يعمل scrape لمنشور LinkedIn معين ويستخرج:
    - title (الدور الوظيفي)
    - company
    - location
    - apply_info (email / whatsapp / link)
    - raw_text (نص المنشور)
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ar,en;q=0.9",
    }
    html = get_text(url, headers=headers)
    if not html or len(html) < 500:
        return None

    # استخراج النص الخام من الـ og:description أو body
    raw_text = ""
    og_desc = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"', html)
    if og_desc:
        raw_text = og_desc.group(1)
    else:
        # fallback: استخراج النص من الـ article أو الـ post body
        body = re.search(r'<article[^>]*>(.*?)</article>', html, re.DOTALL)
        if body:
            raw_text = re.sub(r'<[^>]+>', ' ', body.group(1))
    raw_text = raw_text.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"').strip()

    if not raw_text or len(raw_text) < 20:
        return None

    # هل فيه كلمات وظيفة؟ (فلتر سريع)
    t = raw_text.lower()
    job_signals = ["hiring", "looking for", "we are looking", "join our", "send cv",
                   "vacancy", "opening", "opportunity", "نبحث", "مطلوب", "وظيفة", "توظيف"]
    if not any(k in t for k in job_signals):
        return None

    # استخراج العنوان الوظيفي
    title = ""
    # Pattern 1: "#Hiring — Title" أو "We're Hiring: Title"
    m = re.search(r'(?:hiring|#hiring)[:\s—-]+([^\n.!?|]{5,60})', raw_text, re.IGNORECASE)
    if m:
        title = m.group(1).strip()
    # Pattern 2: "Role | Company"
    if not title:
        m2 = re.search(r'([A-Za-z\s/]{5,50})\s*[|@]\s*([A-Za-z\s]{3,50})', raw_text)
        if m2:
            title = m2.group(1).strip()
    if not title:
        # خذ أول سطر كعنوان
        first_line = raw_text.split("\n")[0][:80].strip()
        title = first_line if len(first_line) > 5 else "Cybersecurity Role"

    company = _extract_company_from_post(raw_text)
    location = _detect_location(raw_text)
    apply_info = _extract_apply_info(raw_text)

    return {
        "title": title,
        "company": company,
        "location": location,
        "raw_text": raw_text,
        "apply_info": apply_info,
        "url": url,
    }


# ── Main Fetcher ─────────────────────────────────────────────

def fetch_linkedin_hr_posts_scraper() -> list[Job]:
    """
    يبحث عن منشورات HR على LinkedIn ويحولها لـ Job objects.
    """
    jobs: list[Job] = []
    seen_urls: set = set()
    seen_titles: set = set()
    start = time.time()

    for query in SEARCH_QUERIES:
        if time.time() - start > MAX_BUDGET_SECS:
            log.warning("linkedin_hr_posts_scraper: budget exhausted early")
            break

        urls = _search_urls(query)
        if not urls:
            time.sleep(random.uniform(1, 2))
            continue

        for url in urls:
            if url in seen_urls:
                continue
            seen_urls.add(url)

            try:
                data = _scrape_linkedin_post(url)
            except Exception as e:
                log.debug(f"Failed to scrape {url}: {e}")
                continue

            if not data:
                continue

            canonical_title = _match_title(data["title"])
            # تجنب تكرار نفس الدور من نفس الشركة
            fp = f"{canonical_title}||{data['company']}"
            if fp in seen_titles:
                continue
            seen_titles.add(fp)

            desc = _build_description(data["raw_text"], data["apply_info"])

            jobs.append(Job(
                title=canonical_title,
                company=data["company"],
                location=data["location"],
                url=url,
                source="linkedin_hr_post",
                original_source="LinkedIn HR Post — Google Search",
                description=desc,
                tags=["linkedin", "hr-post", "hiring-post",
                      data["location"].split(",")[0].lower().replace(" ", "-")],
                is_remote=False,
            ))
            time.sleep(random.uniform(1.5, 3))

        time.sleep(random.uniform(2, 4))

    log.info(f"LinkedIn HR Posts Scraper: {len(jobs)} HR posts found")
    return jobs
