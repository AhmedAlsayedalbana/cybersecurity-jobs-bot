"""
Shared HTTP helpers with session reuse, timeouts, and error handling.

Features:
  - Standard session for normal sites
  - SSL-tolerant session for Egyptian gov sites (many have broken certs)
  - Short timeout (8s) for gov sites — don't wait 15s for dead servers
  - Exponential backoff retry for 429 rate-limit responses
"""

import logging
import time
import requests
import urllib3
from config import REQUEST_TIMEOUT

log = logging.getLogger(__name__)

# Suppress SSL warnings for gov sites (they have self-signed / expired certs)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# ── Standard session ──────────────────────────────────────────
_session = requests.Session()
_session.headers.update({
    "User-Agent": _DEFAULT_UA,
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
})

# ── SSL-tolerant session for Egyptian gov sites ───────────────
_gov_session = requests.Session()
_gov_session.verify = False          # skip SSL verification
_gov_session.headers.update({
    "User-Agent": _DEFAULT_UA,
    "Accept": "text/html, */*",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
})

GOV_TIMEOUT = 8   # Egyptian gov sites time out constantly — fail fast


def _is_gov_url(url: str) -> bool:
    """
    Detect government / regional institution URLs that need
    SSL-tolerant session + short timeout.
    Covers: Egyptian gov, Saudi gov, UAE gov, Qatar gov.
    """
    gov_patterns = [
        # Egypt
        ".gov.eg", ".sci.eg", ".egcert.eg",
        "egcert.eg", "itida.gov", "nti.sci",
        "mcit.gov", "ntra.gov", "tiec.gov",
        "depi.gov", "iti.gov", "svholding.com.eg",
        # Saudi Arabia
        ".gov.sa", "nca.gov.sa", "citc.gov.sa",
        "sdaia.gov.sa", "qcert.org",
        # UAE
        ".gov.ae", "uaecybersecurity.gov",
        "tdra.gov.ae",
        # Qatar / Kuwait / Bahrain / Oman
        ".gov.qa", ".gov.kw", ".gov.bh", ".gov.om",
        "bahrainedb.com", "qcert.org",
    ]
    return any(p in url for p in gov_patterns)


def _request_with_retry(method, url, *, session, params=None, headers=None,
                         json=None, timeout=REQUEST_TIMEOUT,
                         max_retries=2, backoff=5):
    """
    Execute a request with exponential backoff on 429 responses.
    Returns Response or None.
    """
    for attempt in range(max_retries + 1):
        try:
            resp = session.request(
                method, url,
                params=params, headers=headers, json=json,
                timeout=timeout,
            )
            if resp.status_code == 429:
                wait = backoff * (2 ** attempt)
                log.warning(
                    f"429 rate-limit on {url} — waiting {wait}s "
                    f"(attempt {attempt+1}/{max_retries+1})"
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            if attempt < max_retries:
                time.sleep(backoff * (attempt + 1))
            else:
                raise e
    return None


def get_json(url: str, params: dict = None, headers: dict = None,
             timeout: int = REQUEST_TIMEOUT) -> dict | list | None:
    """GET request returning parsed JSON, or None on error."""
    sess = _gov_session if _is_gov_url(url) else _session
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
        log.warning(f"JSON parse error for {url}: {e}")
        return None


def post_json(url: str, payload: dict = None, headers: dict = None,
              timeout: int = REQUEST_TIMEOUT) -> dict | list | None:
    """POST request with JSON body, returning parsed JSON or None."""
    sess = _gov_session if _is_gov_url(url) else _session
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
        log.warning(f"JSON parse error for {url}: {e}")
        return None


def get_text(url: str, params: dict = None, headers: dict = None,
             timeout: int = REQUEST_TIMEOUT) -> str | None:
    """GET request returning raw text, or None on error."""
    sess = _gov_session if _is_gov_url(url) else _session
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
