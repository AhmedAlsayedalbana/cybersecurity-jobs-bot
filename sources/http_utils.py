"""
Shared HTTP helpers with session reuse, timeouts, and error handling.

V16 fix:
  - LinkedIn Guest API now returns HTTP 400 unless a valid CSRF token
    is included in every request.
  - Added _bootstrap_linkedin() which visits the public LinkedIn jobs
    page once at startup, captures the JSESSIONID cookie (used as the
    CSRF token) and stores it for all subsequent calls.
  - All LinkedIn requests now include Csrf-Token / X-Li-Lang headers.
  - Rotating User-Agent pool retained.
  - Per-domain rate tracking retained.
  - Gov session: short timeout (8s), SSL-tolerant.
"""

import logging
import re
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

# ── LinkedIn session — bootstrapped with real CSRF token ──────
_linkedin_session = requests.Session()
_linkedin_session.headers.update({
    "User-Agent": _DEFAULT_UA,
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
})

_linkedin_csrf_token: str = "ajax:0123456789"
_linkedin_bootstrapped: bool = False


def _bootstrap_linkedin():
    """
    Visit LinkedIn's public jobs page to collect real cookies and CSRF token.
    LinkedIn Guest API returns HTTP 400 without a valid CSRF token.
    Must be called once before the first API request.
    """
    global _linkedin_csrf_token, _linkedin_bootstrapped

    if _linkedin_bootstrapped:
        return

    bootstrap_urls = [
        "https://www.linkedin.com/jobs/search/?keywords=cybersecurity&location=Egypt",
        "https://www.linkedin.com/jobs/search/?keywords=cybersecurity",
    ]

    for url in bootstrap_urls:
        try:
            resp = _linkedin_session.get(
                url,
                headers={
                    "User-Agent": _random_ua(),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Upgrade-Insecure-Requests": "1",
                },
                timeout=15,
                allow_redirects=True,
            )

            # JSESSIONID cookie value IS the CSRF token on LinkedIn
            csrf = _linkedin_session.cookies.get("JSESSIONID", "")
            if csrf:
                csrf = csrf.strip('"')
            if csrf:
                _linkedin_csrf_token = csrf
                log.info(f"LinkedIn bootstrap OK (JSESSIONID): {csrf[:20]}…")
                _linkedin_bootstrapped = True
                break

            # Fallback: extract from HTML
            m = re.search(r'"csrfToken"\s*:\s*"([^"]+)"', resp.text)
            if not m:
                m = re.search(r'name="csrf-token"\s+content="([^"]+)"', resp.text)
            if m:
                _linkedin_csrf_token = m.group(1)
                log.info(f"LinkedIn bootstrap OK (HTML): {_linkedin_csrf_token[:20]}…")
                _linkedin_bootstrapped = True
                break

            log.debug(f"LinkedIn bootstrap: no CSRF from {url} (status={resp.status_code})")
            time.sleep(random.uniform(3, 6))

        except Exception as e:
            log.debug(f"LinkedIn bootstrap failed ({url}): {e}")
            time.sleep(random.uniform(2, 4))

    if not _linkedin_bootstrapped:
        log.warning("LinkedIn bootstrap: no CSRF obtained — using fallback token")
        _linkedin_bootstrapped = True  # mark done to avoid infinite loops

    # Apply CSRF to session headers
    _linkedin_session.headers.update({
        "Csrf-Token": _linkedin_csrf_token,
        "X-Li-Lang": "en_US",
        "X-Requested-With": "XMLHttpRequest",
        "x-restli-protocol-version": "2.0.0",
        "Referer": "https://www.linkedin.com/jobs/search/",
    })

    time.sleep(random.uniform(2, 4))


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
_LINKEDIN_MIN_INTERVAL = 4.0   # v28: raised from 2.0 — reduces rate-limit hits


def _get_domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc
    except Exception:
        return url


def _throttle_domain(url: str):
    domain = _get_domain(url)
    if "linkedin.com" in domain:
        now = time.time()
        last = _domain_last_req.get(domain, 0)
        elapsed = now - last
        if elapsed < _LINKEDIN_MIN_INTERVAL:
            wait = _LINKEDIN_MIN_INTERVAL - elapsed + random.uniform(1.0, 3.0)
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
    """Execute a request with exponential backoff + jitter on 429/400."""
    if _is_linkedin_url(url):
        _bootstrap_linkedin()

    _throttle_domain(url)

    for attempt in range(max_retries + 1):
        if _is_linkedin_url(url) and attempt > 0:
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
                log.warning(f"429 rate-limit on {url} — waiting {wait:.1f}s (attempt {attempt+1}/{max_retries+1})")
                time.sleep(wait)
                _domain_last_req[_get_domain(url)] = time.time()
                continue

            # HTTP 400 on LinkedIn = bad/expired CSRF token → re-bootstrap
            if resp.status_code == 400 and _is_linkedin_url(url):
                if attempt < max_retries:
                    global _linkedin_bootstrapped
                    _linkedin_bootstrapped = False
                    log.warning(f"HTTP 400 on LinkedIn (bad CSRF) — re-bootstrapping (attempt {attempt+1})")
                    _bootstrap_linkedin()
                    time.sleep(random.uniform(3, 7))
                    continue
                else:
                    log.warning(f"HTTP 400 for {url} — giving up after {max_retries} retries")
                    return None

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
