"""
Shared HTTP helpers with session reuse, timeouts, and error handling.

V15 improvements:
  - Rotating User-Agent pool to reduce LinkedIn 429 rate-limits
  - Random jitter on all sleeps to avoid burst detection
  - Per-domain rate tracking to space out requests
  - Gov session: short timeout (8s), SSL-tolerant
  - Rate-limit (429): exponential backoff with jitter, 4 attempts
  - Separate LinkedIn session with browser-like headers
"""

import logging
import time
import random
import requests
import urllib3
from config import REQUEST_TIMEOUT

log = logging.getLogger(__name__)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Rotating User-Agent Pool ──────────────────────────────────
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

def _random_ua() -> str:
    return random.choice(_USER_AGENTS)

_DEFAULT_UA = _USER_AGENTS[0]

# ── Standard session ──────────────────────────────────────────
_session = requests.Session()
_session.headers.update({
    "User-Agent": _DEFAULT_UA,
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
})

# ── LinkedIn-specific session with full browser fingerprint ───
_linkedin_session = requests.Session()
_linkedin_session.headers.update({
    "User-Agent": _DEFAULT_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Referer": "https://www.linkedin.com/jobs/search/",
})
# Seed session with a guest visit first (sets JSESSIONID-like cookies)
# This simulates a real browser visiting LinkedIn before calling the API
_linkedin_session.cookies.set("lang", "v=2&lang=en-us", domain=".linkedin.com")
_linkedin_session.cookies.set("bcookie", '"v=2&' + "a1b2c3d4-e5f6-7890-abcd-ef1234567890" + '"', domain=".linkedin.com")
_linkedin_session.cookies.set("bscookie", '"v=1&' + "20240101000000abcdef1234567890abcdef" + '"', domain=".linkedin.com")

# ── SSL-tolerant session for gov sites ────────────────────────
_gov_session = requests.Session()
_gov_session.verify = False
_gov_session.headers.update({
    "User-Agent": _DEFAULT_UA,
    "Accept": "text/html, */*",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
})

GOV_TIMEOUT = 8

# ── Per-domain last request time tracker (rate spacing) ───────
_domain_last_req: dict = {}
_LINKEDIN_MIN_INTERVAL = 1.5  # minimum seconds between LinkedIn requests


def _get_domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc
    except Exception:
        return url


def _throttle_domain(url: str):
    """Sleep if we've hit this domain too recently."""
    domain = _get_domain(url)
    if "linkedin.com" in domain:
        now = time.time()
        last = _domain_last_req.get(domain, 0)
        elapsed = now - last
        if elapsed < _LINKEDIN_MIN_INTERVAL:
            wait = _LINKEDIN_MIN_INTERVAL - elapsed + random.uniform(0.3, 1.2)
            time.sleep(wait)
    _domain_last_req[domain] = time.time()


def _is_linkedin_url(url: str) -> bool:
    return "linkedin.com" in url


def _is_gov_url(url: str) -> bool:
    gov_patterns = [
        ".gov.eg", ".sci.eg", ".egcert.eg",
        "egcert.eg", "itida.gov", "nti.sci",
        "mcit.gov", "ntra.gov", "tiec.gov",
        "depi.gov", "iti.gov", "svholding.com.eg",
        ".gov.sa", "nca.gov.sa", "citc.gov.sa",
        "sdaia.gov.sa", "qcert.org",
        ".gov.ae", "uaecybersecurity.gov", "tdra.gov.ae",
        ".gov.qa", ".gov.kw", ".gov.bh", ".gov.om",
    ]
    return any(p in url for p in gov_patterns)


def _request_with_retry(method, url, *, session, params=None, headers=None,
                         json=None, timeout=REQUEST_TIMEOUT,
                         max_retries=4, backoff=5):
    """Execute a request with exponential backoff + jitter on 429."""
    # Throttle per domain before sending
    _throttle_domain(url)

    for attempt in range(max_retries + 1):
        # Rotate UA on each retry for LinkedIn
        if _is_linkedin_url(url) and attempt > 0:
            if session.headers:
                session.headers.update({"User-Agent": _random_ua()})

        try:
            resp = session.request(
                method, url,
                params=params, headers=headers, json=json,
                timeout=timeout,
            )
            if resp.status_code == 429:
                jitter = random.uniform(1, 3)
                wait = backoff * (2 ** attempt) + jitter
                log.warning(
                    f"429 rate-limit on {url} — waiting {wait:.1f}s "
                    f"(attempt {attempt+1}/{max_retries+1})"
                )
                time.sleep(wait)
                _domain_last_req[_get_domain(url)] = time.time()
                continue
            # 403 on LinkedIn — back off and retry (block is often temporary)
            if resp.status_code == 403 and _is_linkedin_url(url):
                jitter = random.uniform(2, 5)
                wait = backoff * (attempt + 1) + jitter
                log.warning(f"HTTP 403 for {url} — waiting {wait:.1f}s before retry")
                time.sleep(wait)
                if session.headers:
                    session.headers.update({"User-Agent": _random_ua()})
                continue
            # Don't retry on other 4xx errors
            if 400 <= resp.status_code < 500:
                log.warning(f"HTTP {resp.status_code} for {url} — skipping")
                return None
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            if attempt < max_retries:
                wait = backoff * (attempt + 1) + random.uniform(0, 2)
                time.sleep(wait)
            else:
                raise e
    return None


def get_json(url: str, params: dict = None, headers: dict = None,
             timeout: int = REQUEST_TIMEOUT) -> dict | list | None:
    if _is_linkedin_url(url):
        sess = _linkedin_session
    elif _is_gov_url(url):
        sess = _gov_session
    else:
        sess = _session
    t = GOV_TIMEOUT if _is_gov_url(url) else timeout
    try:
        resp = _request_with_retry("GET", url, session=sess,
                                   params=params, headers=headers, timeout=t)
        if resp is None:
            return None
        return resp.json()
    except requests.RequestException as e:
        log.warning(f"GET {url} failed: {e}")
        return None
    except ValueError as e:
        log.debug(f"JSON parse error for {url}: {e}")
        return None


def post_json(url: str, payload: dict = None, headers: dict = None,
              timeout: int = REQUEST_TIMEOUT) -> dict | list | None:
    if _is_gov_url(url):
        sess = _gov_session
    else:
        sess = _session
    t = GOV_TIMEOUT if _is_gov_url(url) else timeout
    try:
        resp = _request_with_retry("POST", url, session=sess,
                                   headers=headers, json=payload, timeout=t)
        if resp is None:
            return None
        return resp.json()
    except requests.RequestException as e:
        log.warning(f"POST {url} failed: {e}")
        return None
    except ValueError as e:
        log.debug(f"JSON parse error for {url}: {e}")
        return None


def get_text(url: str, params: dict = None, headers: dict = None,
             timeout: int = REQUEST_TIMEOUT) -> str | None:
    if _is_linkedin_url(url):
        sess = _linkedin_session
    elif _is_gov_url(url):
        sess = _gov_session
    else:
        sess = _session
    t = GOV_TIMEOUT if _is_gov_url(url) else timeout
    try:
        resp = _request_with_retry("GET", url, session=sess,
                                   params=params, headers=headers, timeout=t)
        if resp is None:
            return None
        return resp.text
    except requests.RequestException as e:
        log.warning(f"GET text {url} failed: {e}")
        return None
