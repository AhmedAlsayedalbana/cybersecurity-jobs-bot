"""
Shared HTTP helpers with session reuse, timeouts, and error handling.

V17 additions (Proxy Rotation):
  - Added _ProxyPool class: rotates through a list of HTTP/SOCKS5 proxies,
    auto-bans proxies that trigger 429/403, re-admits them after COOLDOWN_SEC.
  - LinkedIn session now pulls a fresh proxy on every bootstrap call.
  - _request_with_retry() passes the current proxy to each request.
  - PROXIES env var: comma-separated list of proxy URLs (see README).
    Example: http://user:pass@host:port,socks5://user:pass@host2:port2
  - Falls back to direct connection automatically if PROXIES is empty or all banned.

V16 retained:
  - LinkedIn Guest API CSRF token via JSESSIONID cookie.
  - _bootstrap_linkedin() per-thread.
  - Rotating User-Agent pool.
  - Per-domain rate tracking.
  - Gov session: short timeout (8s), SSL-tolerant.
"""

import logging
import os
import re
import time
import random
import threading
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


# ══════════════════════════════════════════════════════════════
# ── Proxy Pool ────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════

class _ProxyPool:
    """
    Thread-safe rotating proxy pool.

    Load proxies from the PROXIES environment variable:
      PROXIES=http://u:p@host1:8080,socks5://u:p@host2:1080

    Behaviour:
      - get() returns a requests-style dict  {"http": url, "https": url}
        or None if the pool is empty / all proxies are cooling down.
      - ban(url) parks a proxy for COOLDOWN_SEC seconds (e.g. after 429).
      - Uses round-robin with jitter so concurrent threads don't always
        pick the same proxy.
    """
    COOLDOWN_SEC = 300   # 5 minutes before a banned proxy is retried

    def __init__(self):
        self._lock = threading.Lock()
        raw = os.environ.get("PROXIES", "").strip()
        self._proxies: list[str] = [p.strip() for p in raw.split(",") if p.strip()]
        self._banned: dict[str, float] = {}   # url → ban_until timestamp
        self._index = 0

        if self._proxies:
            log.info(f"ProxyPool: loaded {len(self._proxies)} proxy/proxies.")
        else:
            log.info("ProxyPool: no proxies configured — using direct connection.")

    def _available(self) -> list[str]:
        """Return proxies not currently banned."""
        now = time.time()
        # Lift expired bans
        self._banned = {k: v for k, v in self._banned.items() if v > now}
        return [p for p in self._proxies if p not in self._banned]

    def get(self) -> dict | None:
        """Return next available proxy dict, or None for direct connection."""
        with self._lock:
            available = self._available()
            if not available:
                return None   # direct connection fallback
            # Round-robin with wrap-around
            self._index = self._index % len(available)
            proxy_url = available[self._index]
            self._index += 1
            return {"http": proxy_url, "https": proxy_url}

    def ban(self, proxy_url: str):
        """Temporarily ban a proxy after a rate-limit or auth error."""
        with self._lock:
            until = time.time() + self.COOLDOWN_SEC
            self._banned[proxy_url] = until
            log.warning(f"ProxyPool: banned {proxy_url[:40]}… for {self.COOLDOWN_SEC}s")

    @property
    def enabled(self) -> bool:
        return bool(self._proxies)


_proxy_pool = _ProxyPool()


def _current_proxy_url(proxy_dict: dict | None) -> str | None:
    """Extract the URL string from a proxy dict for ban purposes."""
    if proxy_dict:
        return proxy_dict.get("https") or proxy_dict.get("http")
    return None


# ══════════════════════════════════════════════════════════════
# ── Sessions ──────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════

# ── Standard session ──────────────────────────────────────────
_session = requests.Session()
_session.headers.update({
    "User-Agent": _DEFAULT_UA,
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
})

# ── LinkedIn session — thread-local to avoid race conditions ──
_linkedin_local = threading.local()


def _get_linkedin_session() -> requests.Session:
    """Return this thread's LinkedIn session, creating it if needed."""
    if not hasattr(_linkedin_local, "session") or _linkedin_local.session is None:
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": _DEFAULT_UA,
            "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        })
        _linkedin_local.session = sess
        _linkedin_local.csrf_token = "ajax:0123456789"
        _linkedin_local.bootstrapped = False
        _linkedin_local.active_proxy = None   # V17: track proxy used at bootstrap
    return _linkedin_local.session


def _get_linkedin_csrf() -> str:
    _get_linkedin_session()
    return _linkedin_local.csrf_token


def _set_linkedin_csrf(token: str):
    _get_linkedin_session()
    _linkedin_local.csrf_token = token


def _is_linkedin_bootstrapped() -> bool:
    _get_linkedin_session()
    return _linkedin_local.bootstrapped


def _set_linkedin_bootstrapped(value: bool):
    _get_linkedin_session()
    _linkedin_local.bootstrapped = value


# Keep module-level aliases for any external code that references them directly
_linkedin_session: requests.Session = None
_linkedin_csrf_token: str = "ajax:0123456789"
_linkedin_bootstrapped: bool = False


def _bootstrap_linkedin():
    """
    Visit LinkedIn's public jobs page to collect real cookies and CSRF token.
    LinkedIn Guest API returns HTTP 400 without a valid CSRF token.
    Must be called once per thread before the first API request.
    Thread-safe: each thread manages its own session via threading.local().

    V17: Picks a proxy from _proxy_pool and stores it on the thread-local
    so that all subsequent requests from this thread use the same proxy
    (keeps the session/cookie consistent with the bootstrap IP).
    """
    if _is_linkedin_bootstrapped():
        return

    sess = _get_linkedin_session()

    # V17: choose a proxy for this bootstrap session
    proxy = _proxy_pool.get()
    _linkedin_local.active_proxy = proxy
    if proxy:
        sess.proxies.update(proxy)
        log.info(f"LinkedIn bootstrap: using proxy {list(proxy.values())[0][:40]}… [thread={threading.current_thread().name}]")
    else:
        sess.proxies.clear()
        log.info(f"LinkedIn bootstrap: direct connection [thread={threading.current_thread().name}]")

    bootstrap_urls = [
        "https://www.linkedin.com/jobs/search/?keywords=cybersecurity&location=Egypt",
        "https://www.linkedin.com/jobs/search/?keywords=cybersecurity",
    ]

    for url in bootstrap_urls:
        try:
            resp = sess.get(
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

            # Ban proxy if LinkedIn immediately rejects it
            if resp.status_code in (429, 403) and proxy:
                _proxy_pool.ban(_current_proxy_url(proxy))
                # Try again without proxy
                _linkedin_local.active_proxy = None
                sess.proxies.clear()
                log.warning("LinkedIn bootstrap: proxy rejected, falling back to direct.")

            csrf = sess.cookies.get("JSESSIONID", "")
            if csrf:
                csrf = csrf.strip('"')
            if csrf:
                _set_linkedin_csrf(csrf)
                masked = csrf[:4] + "****" + csrf[-4:] if len(csrf) > 8 else "****"
                log.info(f"LinkedIn bootstrap OK (JSESSIONID): {masked} [thread={threading.current_thread().name}]")
                _set_linkedin_bootstrapped(True)
                break

            m = re.search(r'"csrfToken"\s*:\s*"([^"]+)"', resp.text)
            if not m:
                m = re.search(r'name="csrf-token"\s+content="([^"]+)"', resp.text)
            if m:
                _set_linkedin_csrf(m.group(1))
                log.info(f"LinkedIn bootstrap OK (HTML): {_get_linkedin_csrf()[:20]}… [thread={threading.current_thread().name}]")
                _set_linkedin_bootstrapped(True)
                break

            log.debug(f"LinkedIn bootstrap: no CSRF from {url} (status={resp.status_code})")
            time.sleep(random.uniform(3, 6))

        except Exception as e:
            log.debug(f"LinkedIn bootstrap failed ({url}): {e}")
            time.sleep(random.uniform(2, 4))

    if not _is_linkedin_bootstrapped():
        log.warning("LinkedIn bootstrap: no CSRF obtained — using fallback token")
        _set_linkedin_bootstrapped(True)

    sess.headers.update({
        "Csrf-Token": _get_linkedin_csrf(),
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
_LINKEDIN_MIN_INTERVAL = 4.0


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


# v37: Sites that MUST bypass proxy — proxy blocks them or causes 404/403
# These connect directly regardless of PROXIES setting
_DIRECT_DOMAINS = [
    "wuzzuf.net",        # 404 via proxy
    "remotive.com",      # sometimes blocked via proxy
    "arbeitnow.com",     # clean public API — no need for proxy
    "weworkremotely.com", # RSS feed — no need for proxy
]

def _is_direct_url(url: str) -> bool:
    """Returns True if the URL should bypass proxies and connect directly."""
    return any(d in url for d in _DIRECT_DOMAINS)


def _request_with_retry(method, url, *, session, params=None, headers=None,
                         json=None, timeout=REQUEST_TIMEOUT,
                         max_retries=4, backoff=5):
    """Execute a request with exponential backoff + jitter on 429/400.

    V17: For LinkedIn requests, the proxy is already baked into the session
    by _bootstrap_linkedin(). For non-LinkedIn requests we inject a fresh
    proxy per-request so different searches naturally rotate IPs.
    """
    if _is_linkedin_url(url):
        _bootstrap_linkedin()

    _throttle_domain(url)

    # V17: inject proxy for non-LinkedIn, non-gov requests
    # v37: also skip proxy for _DIRECT_DOMAINS (wuzzuf, remotive, etc.)
    request_proxy = None
    if (not _is_linkedin_url(url) and not _is_gov_url(url)
            and not _is_direct_url(url) and _proxy_pool.enabled):
        request_proxy = _proxy_pool.get()

    for attempt in range(max_retries + 1):
        if _is_linkedin_url(url) and attempt > 0:
            session.headers.update({"User-Agent": _random_ua()})

        try:
            kwargs = dict(
                params=params,
                headers=headers,
                json=json,
                timeout=timeout,
            )
            # Only pass proxies= if we have one (avoids overriding LinkedIn session proxy)
            if request_proxy and not _is_linkedin_url(url):
                kwargs["proxies"] = request_proxy

            resp = session.request(method, url, **kwargs)

            if resp.status_code == 429:
                # Ban the proxy that caused the rate-limit (if any)
                if _is_linkedin_url(url) and hasattr(_linkedin_local, "active_proxy") and _linkedin_local.active_proxy:
                    _proxy_pool.ban(_current_proxy_url(_linkedin_local.active_proxy))
                    _linkedin_local.active_proxy = None
                    _set_linkedin_bootstrapped(False)  # force re-bootstrap with new proxy
                elif request_proxy:
                    _proxy_pool.ban(_current_proxy_url(request_proxy))
                    request_proxy = _proxy_pool.get()  # get next available proxy

                jitter = random.uniform(1, 3)
                wait = backoff * (2 ** attempt) + jitter
                short_url = url[:80] + "…" if len(url) > 80 else url
                log.warning(f"429 rate-limit on {short_url} — waiting {wait:.1f}s (attempt {attempt+1}/{max_retries+1})")
                time.sleep(wait)
                _domain_last_req[_get_domain(url)] = time.time()
                continue

            if resp.status_code == 400 and _is_linkedin_url(url):
                if attempt < max_retries:
                    _set_linkedin_bootstrapped(False)
                    log.warning(f"HTTP 400 on LinkedIn (bad CSRF) — re-bootstrapping (attempt {attempt+1}) [thread={threading.current_thread().name}]")
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
             timeout: int = REQUEST_TIMEOUT, max_retries: int = 4) -> dict | list | None:
    if _is_linkedin_url(url):
        sess = _get_linkedin_session()
    elif _is_gov_url(url):
        sess = _gov_session
    else:
        sess = _session
    t = GOV_TIMEOUT if _is_gov_url(url) else timeout
    try:
        resp = _request_with_retry("GET", url, session=sess,
                                   params=params, headers=headers, timeout=t,
                                   max_retries=max_retries)
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
        sess = _get_linkedin_session()
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
