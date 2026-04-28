"""
LinkedIn HR Post Hunter — v34 (NEW MODULE)
==========================================
هذا الملف مسؤول عن "صيد" منشورات HR الشخصية على LinkedIn
التي تسبق الإعلانات الرسمية وتتيح تواصلاً مباشراً.

STRATEGY:
  المرحلة 1 — The Dragnet:
    البحث عن "عبارات التوظيف" (Hiring Phrases) بدلاً من المسميات فقط.
    نغطي: أنماط الكتابة + الهاشتاجات + طلبات التواصل المباشر.

  المرحلة 2 — AI Extraction:
    استخدام Claude API (claude-haiku) لاستخراج بيانات منظمة
    من النص الخام للمنشور → JSON مع role, company, work_model, highlights.

  المرحلة 3 — Rich Formatting:
    تمييز هذه الوظائف بـ source="linkedin_hr_post" ليعطيها
    telegram_sender قالب عرض خاص (format_hr_post_message).

COST CONTROL:
  - يستخدم claude-haiku-4-5 (الأسرع والأرخص في عائلة Claude 4)
  - max_tokens=400 لكل منشور
  - فلتر 7 أيام يمنع معالجة منشورات قديمة
  - cache_seen_snippets يمنع إعادة معالجة نفس النص

ANTI-BLOCK:
  - random.uniform delays بين كل طلب
  - User-Agent rotation عبر http_utils
  - حد أقصى 25 منشور لكل run
"""

import logging
import os
import re
import time
import json
import random
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional

from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────────
MAX_POSTS_PER_RUN = 25          # حد أقصى للمنشورات في كل run
MAX_BUDGET_SECS   = 5 * 60     # 5 دقائق budget
POST_MAX_AGE_DAYS = 7           # تجاهل المنشورات أكثر من 7 أيام
AI_MAX_TOKENS     = 400         # حد رموز Claude لكل منشور
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL   = "claude-haiku-4-5-20251001"  # الأسرع والأرخص

# ─── Hiring Phrase Patterns ───────────────────────────────────
# ثلاث فئات من أنماط البحث كما وردت في خطة التطوير
DRAGNET_QUERIES = [
    # ── Hiring Phrase Patterns (English) ─────────────────────
    'site:linkedin.com/posts "we\'re hiring" "cybersecurity" "Egypt"',
    'site:linkedin.com/posts "looking for" "SOC analyst" "Egypt"',
    'site:linkedin.com/posts "join our team" "security" "Cairo"',
    'site:linkedin.com/posts "we are hiring" "penetration" "Egypt"',
    'site:linkedin.com/posts "open position" "cybersecurity" "Egypt"',
    'site:linkedin.com/posts "hiring now" "security engineer" "Egypt"',
    'site:linkedin.com/posts "immediate opening" "infosec" "Egypt"',
    # ── Direct Outreach Patterns ──────────────────────────────
    'site:linkedin.com/posts "drop your CV" "cybersecurity"',
    'site:linkedin.com/posts "DM me" "security engineer" "Egypt"',
    'site:linkedin.com/posts "send your resume" "SOC" "Egypt"',
    'site:linkedin.com/posts "reach out" "penetration tester" "Egypt"',
    'site:linkedin.com/posts "connect with me" "security" "Cairo"',
    # ── Hashtag Patterns ─────────────────────────────────────
    'site:linkedin.com/posts "#hiring #cybersecurity" "Egypt"',
    'site:linkedin.com/posts "#jobopportunity" "security" "Egypt"',
    'site:linkedin.com/posts "#egyptjobs" "cybersecurity"',
    'site:linkedin.com/posts "#ksajobs" "cybersecurity"',
    'site:linkedin.com/posts "#hiring" "SOC analyst" "Saudi Arabia"',
    'site:linkedin.com/posts "#hiring" "security" "Dubai"',
    # ── Arabic Patterns ───────────────────────────────────────
    'site:linkedin.com/posts "نحن نوظف" "أمن" "مصر"',
    'site:linkedin.com/posts "فرصة عمل" "أمن سيبراني" "مصر"',
    'site:linkedin.com/posts "مطلوب" "أمن معلومات" "القاهرة"',
    'site:linkedin.com/posts "تقديم" "اختبار اختراق" "السعودية"',
]

# ─── Role normalization (reused from linkedin_posts.py) ──────
_ROLE_MAP = [
    (["soc analyst", "security operations analyst"],          "SOC Analyst"),
    (["soc engineer", "security operations engineer"],        "SOC Engineer"),
    (["siem", "security monitoring"],                         "SIEM / Security Monitoring"),
    (["threat intel", "threat intelligence", "cti"],          "Threat Intelligence Analyst"),
    (["threat hunter", "threat hunting"],                     "Threat Hunter"),
    (["incident resp", "ir analyst", "dfir"],                 "Incident Response / DFIR"),
    (["malware analyst", "malware researcher", "reverse eng"],"Malware Analyst"),
    (["penetration tester", "pen tester", "pentester"],       "Penetration Tester"),
    (["red team", "red teamer"],                              "Red Team Engineer"),
    (["ethical hack", "bug bounty"],                          "Ethical Hacker / Bug Bounty"),
    (["appsec", "application security"],                      "Application Security Engineer"),
    (["devsecops", "dev sec ops"],                            "DevSecOps Engineer"),
    (["cloud security", "aws security", "azure security"],    "Cloud Security Engineer"),
    (["network security", "firewall"],                        "Network Security Engineer"),
    (["grc", "governance risk", "compliance", "iso 27001"],   "GRC / Compliance Analyst"),
    (["ciso", "chief information security"],                  "CISO"),
    (["security architect"],                                  "Security Architect"),
    (["security engineer", "cybersecurity engineer"],         "Security Engineer"),
    (["intern", "trainee", "fresh grad", "junior security"],  "Security Intern / Junior"),
    (["cybersecurity", "cyber security", "infosec"],          "Cybersecurity Specialist"),
    (["security analyst", "security specialist"],             "Security Analyst"),
    # Arabic
    (["أمن سيبراني", "الأمن السيبراني"],                    "Cybersecurity Specialist"),
    (["أمن معلومات", "أمن المعلومات"],                      "Information Security Analyst"),
    (["اختبار اختراق"],                                      "Penetration Tester"),
    (["محلل أمن"],                                           "Security Analyst"),
    (["مهندس أمن"],                                          "Security Engineer"),
]


def _normalize_role(raw: str) -> str:
    """Normalize raw title to canonical cybersecurity role."""
    t = raw.lower()
    for kws, canonical in _ROLE_MAP:
        if any(k in t for k in kws):
            return canonical
    return raw.strip().title()


def _clean_html(html: str) -> str:
    """Strip HTML tags and decode common entities."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')
    return re.sub(r"\s+", " ", text).strip()


def _is_recent(snippet: str) -> bool:
    """
    Heuristic: reject snippets that mention dates older than POST_MAX_AGE_DAYS.
    LinkedIn Google snippets often contain '3 weeks ago', '2 months ago' etc.
    """
    old_patterns = [
        r"\b(\d+)\s+(?:months?|weeks?)\s+ago",
        r"\b(\d+[wmMW])\b",
    ]
    for pat in old_patterns:
        m = re.search(pat, snippet, re.IGNORECASE)
        if m:
            val = m.group(1)
            # weeks > 1 or any months = too old
            if "month" in m.group(0).lower():
                return False
            weeks = int(re.sub(r"\D", "", val) or 0)
            if weeks > 1:
                return False
    return True


# ─── AI Analysis via Claude API ──────────────────────────────

def _analyze_with_ai(raw_snippet: str, url: str) -> Optional[dict]:
    """
    استخدام Claude Haiku لتحويل النص الخام → JSON منظم.

    يعيد dict بالمفاتيح:
      role, company, location, work_model, highlights, requirements,
      poster_name, is_hr_post (bool)

    يعيد None عند الفشل أو إذا لم يكن منشور توظيف حقيقي.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        log.debug("AI analysis skipped — ANTHROPIC_API_KEY not set")
        return None

    prompt = f"""You are a recruitment data extraction AI specialized in cybersecurity jobs.

Analyze the following LinkedIn post snippet and extract structured hiring information.

SNIPPET:
{raw_snippet[:800]}

POST URL: {url}

Rules:
1. Only extract if this is a REAL job posting (not a course ad, generic article, or spam).
2. Return ONLY valid JSON — no markdown, no explanation, no backticks.
3. If it is NOT a job posting, return: {{"is_hr_post": false}}
4. work_model must be one of: "Remote", "Hybrid", "On-site", "Unknown"
5. highlights and requirements must be SHORT bullet strings (max 8 words each), max 4 items each.
6. poster_name: extract the HR/recruiter name if visible in the text, else null.

JSON schema:
{{
  "is_hr_post": true,
  "role": "<canonical job title>",
  "company": "<company name or null>",
  "location": "<city, country or null>",
  "work_model": "Remote|Hybrid|On-site|Unknown",
  "highlights": ["<responsibility 1>", "..."],
  "requirements": ["<requirement 1>", "..."],
  "poster_name": "<name or null>"
}}"""

    try:
        import urllib.request
        payload = json.dumps({
            "model": ANTHROPIC_MODEL,
            "max_tokens": AI_MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()

        req = urllib.request.Request(
            ANTHROPIC_API_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        content_blocks = data.get("content", [])
        raw_text = "".join(
            b.get("text", "") for b in content_blocks if b.get("type") == "text"
        ).strip()

        # Strip accidental markdown fences
        raw_text = re.sub(r"^```(?:json)?|```$", "", raw_text, flags=re.MULTILINE).strip()

        parsed = json.loads(raw_text)
        if not parsed.get("is_hr_post", False):
            return None
        return parsed

    except Exception as e:
        log.debug(f"AI analysis failed for snippet: {e}")
        return None


# ─── Google Search Dragnet ───────────────────────────────────

def _fetch_hr_posts_via_google() -> list[Job]:
    """
    المرحلة 1: The Dragnet — البحث في Google عن منشورات HR على LinkedIn.
    المرحلة 2: AI Extraction — تحليل كل snippet بـ Claude Haiku.
    """
    jobs: list[Job] = []
    seen_snippets: set[str] = set()
    start_time = time.time()
    post_count = 0

    for query in DRAGNET_QUERIES:
        if time.time() - start_time > MAX_BUDGET_SECS:
            log.warning("HR Hunter: budget exhausted early")
            break
        if post_count >= MAX_POSTS_PER_RUN:
            log.info(f"HR Hunter: reached max posts limit ({MAX_POSTS_PER_RUN})")
            break

        encoded = urllib.parse.quote_plus(query)
        # tbs=qdr:w → past week only | num=8 → top 8 results
        search_url = (
            f"https://www.google.com/search"
            f"?q={encoded}&num=8&tbs=qdr:w&hl=en&gl=eg"
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        }

        html = get_text(search_url, headers=headers)
        if not html:
            time.sleep(random.uniform(3, 5))
            continue

        # ── Extract LinkedIn post URLs ────────────────────────
        li_urls = re.findall(
            r'https://(?:www\.)?linkedin\.com/posts/[^\s"&<>]+',
            html,
        )
        # Also catch /pulse/ and /feed/update/ patterns
        li_urls += re.findall(
            r'https://(?:www\.)?linkedin\.com/(?:pulse|feed/update)/[^\s"&<>]+',
            html,
        )
        li_urls = list(dict.fromkeys(li_urls))  # deduplicate preserving order

        # ── Extract Google snippets ───────────────────────────
        # Google renders snippets in various div classes
        snippet_patterns = [
            r'<div[^>]*class="[^"]*(?:VwiC3b|s3v9rd|st|IsZvec)[^"]*"[^>]*>(.*?)</div>',
            r'<span[^>]*class="[^"]*aCOpRe[^"]*"[^>]*>(.*?)</span>',
        ]
        raw_snippets = []
        for pat in snippet_patterns:
            raw_snippets.extend(re.findall(pat, html, re.DOTALL))

        for i, raw in enumerate(raw_snippets):
            if post_count >= MAX_POSTS_PER_RUN:
                break

            snippet = _clean_html(raw).strip()
            if len(snippet) < 30:
                continue

            # Deduplicate by snippet fingerprint (first 80 chars)
            fingerprint = snippet[:80].lower()
            if fingerprint in seen_snippets:
                continue
            seen_snippets.add(fingerprint)

            # Freshness heuristic
            if not _is_recent(snippet):
                log.debug(f"HR Hunter: skipping old post snippet: {snippet[:60]}")
                continue

            # Must contain a hiring signal
            hiring_signals = [
                "hiring", "we're hiring", "looking for", "join our team",
                "open position", "drop your cv", "dm me", "send your resume",
                "نوظف", "فرصة عمل", "مطلوب", "#hiring", "#jobopportunity",
            ]
            if not any(sig in snippet.lower() for sig in hiring_signals):
                continue

            # Pick the most relevant URL
            post_url = li_urls[i] if i < len(li_urls) else (
                li_urls[0] if li_urls else
                f"https://www.linkedin.com/search/results/content/?keywords={encoded}"
            )

            # ── AI Analysis (المرحلة 2) ───────────────────────
            ai_data = _analyze_with_ai(snippet, post_url)

            if ai_data:
                # AI succeeded — use structured data
                role      = _normalize_role(ai_data.get("role") or "")
                company   = ai_data.get("company") or "Unknown"
                location  = ai_data.get("location") or _infer_location_from_query(query)
                work_model = ai_data.get("work_model", "Unknown")
                highlights = ai_data.get("highlights", [])
                reqs       = ai_data.get("requirements", [])
                poster     = ai_data.get("poster_name") or ""

                if not role:
                    role = _infer_role_from_text(snippet)
                if not role:
                    continue

                desc_parts = []
                if highlights:
                    desc_parts.append("Responsibilities: " + "; ".join(highlights))
                if reqs:
                    desc_parts.append("Requirements: " + "; ".join(reqs))
                description = " | ".join(desc_parts)[:500]

                tags = ["linkedin_hr_post", "hiring-phrase", "ai-analyzed"]
                if work_model.lower() == "remote":
                    tags.append("remote")
                elif work_model.lower() == "hybrid":
                    tags.append("hybrid")
                if poster:
                    tags.append(f"poster:{poster[:30]}")

                jobs.append(Job(
                    title=role,
                    company=company,
                    location=location,
                    url=post_url,
                    source="linkedin_hr_post",
                    original_source=f"LinkedIn HR Post — {poster}" if poster else "LinkedIn HR Post",
                    description=description,
                    tags=tags,
                    is_remote=(work_model.lower() == "remote"),
                    job_type=work_model if work_model != "Unknown" else "",
                ))
                post_count += 1
                log.debug(f"HR Hunter [AI]: {role} @ {company} — {location}")

            else:
                # AI not available or rejected — fallback heuristic extraction
                fallback_job = _heuristic_extract(snippet, post_url, query)
                if fallback_job:
                    jobs.append(fallback_job)
                    post_count += 1
                    log.debug(f"HR Hunter [heuristic]: {fallback_job.title}")

        time.sleep(random.uniform(3.5, 6.0))  # Google rate limit

    log.info(f"LinkedIn HR Hunter: found {len(jobs)} HR posts")
    return jobs


# ─── Heuristic Fallback (when AI not available) ──────────────

def _heuristic_extract(snippet: str, url: str, query: str) -> Optional[Job]:
    """
    Fallback extraction without AI.
    يحاول استخراج المعلومات الأساسية بالـ regex عند عدم توفر ANTHROPIC_API_KEY.
    """
    # Try to extract job title
    title_patterns = [
        r"(?:hiring|looking for|seeking|vacancy for|open role|open position)[:\s]+([A-Z][^.!?]{5,60})",
        r"(?:join\s+(?:our|us)\s+as\s+(?:a\s+|an\s+)?)([\w\s]{5,50}?)(?:\.|,|!)",
        r"(?:we need\s+(?:a\s+)?)([\w\s]{5,50}?)(?:\.|,|!)",
    ]
    title = ""
    for pat in title_patterns:
        m = re.search(pat, snippet, re.IGNORECASE)
        if m:
            title = m.group(1).strip()
            break

    if not title:
        title = _infer_role_from_text(snippet)

    if not title:
        return None

    location = _infer_location_from_query(query)
    is_remote = bool(re.search(r"\b(?:remote|fully remote|work from home)\b", snippet, re.IGNORECASE))
    work_model = "Remote" if is_remote else ""
    if re.search(r"\bhybrid\b", snippet, re.IGNORECASE):
        work_model = "Hybrid"

    return Job(
        title=_normalize_role(title),
        company="Unknown",
        location=location,
        url=url,
        source="linkedin_hr_post",
        original_source="LinkedIn HR Post",
        description=snippet[:400],
        tags=["linkedin_hr_post", "hiring-phrase", "heuristic"],
        is_remote=is_remote,
        job_type=work_model,
    )


def _infer_role_from_text(text: str) -> str:
    """Try to match a known role from raw text."""
    t = text.lower()
    for kws, canonical in _ROLE_MAP:
        if any(k in t for k in kws):
            return canonical
    return ""


def _infer_location_from_query(query: str) -> str:
    """Derive location label from the search query string."""
    q = query.lower()
    if "saudi" in q or "riyadh" in q or "jeddah" in q or "ksajobs" in q:
        return "Saudi Arabia"
    if "dubai" in q or "uae" in q or "abu dhabi" in q:
        return "UAE"
    if "qatar" in q or "doha" in q:
        return "Qatar"
    if "egypt" in q or "cairo" in q or "مصر" in q or "egyptjobs" in q:
        return "Egypt"
    return "Egypt"  # default: assume Egypt if unspecified


# ─── Public Entry Point ───────────────────────────────────────

def fetch_linkedin_hr_hunter() -> list[Job]:
    """
    Main entry point — called from sources/__init__.py.
    Combines Dragnet + AI Extraction in one pass.
    """
    try:
        return _fetch_hr_posts_via_google()
    except Exception as e:
        log.warning(f"LinkedIn HR Hunter failed entirely: {e}")
        return []
