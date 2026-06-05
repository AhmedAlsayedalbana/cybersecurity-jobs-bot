"""
Shared HTTP helpers � v40 (Anti-Ban Edition)

MAJOR IMPROVEMENTS v40:
   LinkedIn li_at Cookie Auth � uses real session cookie for Guest API
     Set LI_AT env var to your li_at cookie value for authenticated requests
   Full jitter backoff (AWS-style) � avoids thundering herd on proxy pool
   Proxy health scoring � penalize slow/blocking proxies, prefer fast healthy ones
   Proxy session stickiness � same thread always uses same proxy per host
   Browser-like TLS fingerprint via ordered headers
   LinkedIn cookie re-auth � auto-refreshes CSRF when 400/401 hit
   Graduated cooldowns: 429=3min, 403=10min, conn_error=1min
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

_USER_AGENTS = [
    # Chrome 135 � Windows (  � May 2025)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.7049.85 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    # Chrome 135 � macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_3_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    # Firefox 137 � Windows & macOS
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) Gecko/20100101 Firefox/137.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.7; rv:137.0) Gecko/20100101 Firefox/137.0",
    # Safari 18 � macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.4 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_3_2) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.4 Safari/605.1.15",
    # Edge 135 � Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0",
    # Chrome 135 � Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
]

_ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-US,en;q=0.9,ar;q=0.8",
    "en-GB,en;q=0.9",
    "en-US,en;q=0.8,ar-EG;q=0.6,ar;q=0.4",
    "en-US,en;q=0.9,fr;q=0.7",
]

def _random_ua() -> str:
    return random.choice(_USER_AGENTS)

def _random_accept_lang() -> str:
    return random.choice(_ACCEPT_LANGUAGES)


class _ProxyPool:
    """Thread-safe proxy pool with health scoring and session stickiness."""
    # v52 FIX: Reduced cooldowns — 403/429 from LinkedIn are usually ephemeral
    # IP bans that clear within minutes, not hours.  Previous values (30 min for
    # 403, 10 min for 429) caused cascading pool exhaustion under normal load.
    COOLDOWN_429  = 300   # 5 min  (was 10 min)
    COOLDOWN_403  = 900   # 15 min (was 30 min)
    COOLDOWN_ERR  = 90    # 90 sec (was 2 min)
    # v52 FIX: Minimum score floor.  Previously proxies could reach 0 and
    # effectively become invisible in weighted selection even after unbanning.
    SCORE_FLOOR   = 5.0
    SCORE_INIT    = 50.0

    def __init__(self):
        self._lock  = threading.Lock()
        raw = os.environ.get("PROXIES", "").strip()
        self._proxies: list[str] = [p.strip() for p in raw.split(",") if p.strip()]
        self._banned:  dict[str, float] = {}
        self._scores:  dict[str, float] = {p: self.SCORE_INIT for p in self._proxies}
        self._sticky:  dict[str, str] = {}

        if self._proxies:
            log.info(f"ProxyPool v40: {len(self._proxies)} proxies loaded.")
        else:
            log.info("ProxyPool v40: no proxies — direct connection mode.")

    def _available(self) -> list[str]:
        now = time.time()
        # When a ban expires, partially restore the proxy's score so it can
        # compete again.  Without this, a proxy banned twice drops to ~0 and
        # never recovers, causing permanent pool shrinkage.
        expired = {k for k, v in self._banned.items() if v <= now}
        for p in expired:
            self._scores[p] = max(self._scores.get(p, 0.0), 20.0)  # floor recovery
        self._banned = {k: v for k, v in self._banned.items() if v > now}
        return [p for p in self._proxies if p not in self._banned]

    def get(self, host: str = "", sticky: bool = False) -> dict | None:
        with self._lock:
            available = self._available()
            if not available:
                return None

            if sticky and host:
                thread_key = f"{threading.current_thread().ident}:{host}"
                if thread_key in self._sticky and self._sticky[thread_key] in available:
                    p = self._sticky[thread_key]
                    return {"http": p, "https": p}

            scores = [max(self._scores.get(p, 50.0), 1.0) for p in available]
            total  = sum(scores)
            probs  = [s / total for s in scores]

            rand = random.random()
            cumulative = 0.0
            selected = available[0]
            for p, prob in zip(available, probs):
                cumulative += prob
                if rand <= cumulative:
                    selected = p
                    break

            if sticky and host:
                thread_key = f"{threading.current_thread().ident}:{host}"
                self._sticky[thread_key] = selected

            return {"http": selected, "https": selected}

    def report_success(self, proxy_url: str, elapsed_ms: float = 0):
        with self._lock:
            if proxy_url not in self._scores:
                return
            boost = 1.0 if elapsed_ms < 3000 else -0.5
            self._scores[proxy_url] = min(100.0, self._scores[proxy_url] + boost)

    def ban(self, proxy_url: str, reason: str = "429"):
        with self._lock:
            if reason == "403":
                cooldown, penalty = self.COOLDOWN_403, 30.0
            elif reason == "429":
                cooldown, penalty = self.COOLDOWN_429, 10.0
            else:
                cooldown, penalty = self.COOLDOWN_ERR, 5.0

            self._banned[proxy_url] = time.time() + cooldown
            # v52 FIX: use SCORE_FLOOR so proxies remain selectable after cooldown
            self._scores[proxy_url] = max(
                self.SCORE_FLOOR,
                self._scores.get(proxy_url, self.SCORE_INIT) - penalty,
            )

            to_remove = [k for k, v in self._sticky.items() if v == proxy_url]
            for k in to_remove:
                del self._sticky[k]

            log.debug(
                f"ProxyPool: banned {proxy_url[:40]}� "
                f"reason={reason} cooldown={cooldown}s score={self._scores[proxy_url]:.0f}"
            )

    @property
    def enabled(self) -> bool:
        return bool(self._proxies)

    def status(self) -> dict:
        with self._lock:
            available = self._available()
            return {
                "total": len(self._proxies),
                "available": len(available),
                "banned": len(self._proxies) - len(available),
                "avg_score": (sum(self._scores.values()) / len(self._scores) if self._scores else 0),
            }


_proxy_pool = _ProxyPool()

_http_metrics_lock = threading.Lock()
_http_metrics = {
    "requests": 0,
    "429": 0,
    "403": 0,
    "errors": 0,
}


def _current_proxy_url(proxy_dict: dict | None) -> str | None:
    if proxy_dict:
        return proxy_dict.get("https") or proxy_dict.get("http")
    return None


#  LinkedIn Session 
_LI_AT_COOKIE    = os.environ.get("LI_AT", "").strip()
_LI_CSRF_FALLBACK = "ajax:0123456789"

_linkedin_local = threading.local()


def _get_linkedin_session() -> requests.Session:
    if not hasattr(_linkedin_local, "session") or _linkedin_local.session is None:
        sess = requests.Session()
        sess.headers.update({
            "User-Agent":                 _random_ua(),
            "Accept":                     "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language":            _random_accept_lang(),
            "Accept-Encoding":            "gzip, deflate, br",
            "Connection":                 "keep-alive",
            "Upgrade-Insecure-Requests":  "1",
        })

        if _LI_AT_COOKIE:
            sess.cookies.set("li_at", _LI_AT_COOKIE, domain=".linkedin.com")
            sess.cookies.set("JSESSIONID", f'"{_LI_CSRF_FALLBACK}"', domain=".linkedin.com")
            _linkedin_local.csrf_token   = _LI_CSRF_FALLBACK
            _linkedin_local.bootstrapped = True
            log.info("LinkedIn: using li_at cookie auth (authenticated mode).")
        else:
            _linkedin_local.csrf_token   = _LI_CSRF_FALLBACK
            _linkedin_local.bootstrapped = False

        _linkedin_local.session      = sess
        _linkedin_local.active_proxy = None
    return _linkedin_local.session


def _get_linkedin_csrf() -> str:
    _get_linkedin_session()
    return getattr(_linkedin_local, "csrf_token", _LI_CSRF_FALLBACK)


def _set_linkedin_csrf(token: str):
    _get_linkedin_session()
    _linkedin_local.csrf_token = token


def _is_linkedin_bootstrapped() -> bool:
    _get_linkedin_session()
    return getattr(_linkedin_local, "bootstrapped", False)


def _set_linkedin_bootstrapped(value: bool):
    _get_linkedin_session()
    _linkedin_local.bootstrapped = value


def _bootstrap_linkedin():
    if _is_linkedin_bootstrapped():
        return

    if _LI_AT_COOKIE:
        _set_linkedin_bootstrapped(True)
        return

    sess = _get_linkedin_session()

    # Use sticky proxy so all requests in this session use same IP
    proxy = _proxy_pool.get(host="linkedin.com", sticky=True)
    _linkedin_local.active_proxy = proxy

    if proxy:
        sess.proxies.update(proxy)
        log.info(f"LinkedIn bootstrap: using proxy {list(proxy.values())[0][:40]}� [thread={threading.current_thread().name}]")
    else:
        sess.proxies.clear()
        log.info(f"LinkedIn bootstrap: direct connection [thread={threading.current_thread().name}]")

    bootstrap_urls = [
        "https://www.linkedin.com/jobs/search/?keywords=cybersecurity&location=Egypt&f_TPR=r86400",
        "https://www.linkedin.com/jobs/cybersecurity-jobs/",
        "https://www.linkedin.com/jobs/search/?keywords=security+analyst",
    ]

    for url in bootstrap_urls:
        try:
            sess.headers.update({
                "User-Agent":      _random_ua(),
                "Accept-Language": _random_accept_lang(),
            })

            resp = sess.get(url, timeout=20, allow_redirects=True)

            if resp.status_code in (429, 403):
                if proxy:
                    reason = "429" if resp.status_code == 429 else "403"
                    _proxy_pool.ban(_current_proxy_url(proxy), reason=reason)
                    _linkedin_local.active_proxy = None
                    sess.proxies.clear()
                    log.warning(f"LinkedIn bootstrap: proxy rejected ({resp.status_code}), falling back to direct.")
                break

            csrf = sess.cookies.get("JSESSIONID", "")
            if csrf:
                csrf = csrf.strip('"')
            if csrf and csrf.startswith("ajax:"):
                _set_linkedin_csrf(csrf)
                masked = csrf[:8] + "****" + csrf[-4:] if len(csrf) > 12 else "****"
                log.info(f"LinkedIn bootstrap OK (JSESSIONID): {masked} [thread={threading.current_thread().name}]")
                _set_linkedin_bootstrapped(True)
                break

            m = re.search(r'"csrfToken"\s*:\s*"([^"]+)"', resp.text)
            if not m:
                m = re.search(r'name="csrf-token"\s+content="([^"]+)"', resp.text)
            if m:
                _set_linkedin_csrf(m.group(1))
                log.info(f"LinkedIn bootstrap OK (HTML csrf): {_get_linkedin_csrf()[:20]}�")
                _set_linkedin_bootstrapped(True)
                break

            log.debug(f"LinkedIn bootstrap: no CSRF from {url} (status={resp.status_code})")
            time.sleep(random.uniform(2, 5))

        except Exception as e:
            log.debug(f"LinkedIn bootstrap error ({url}): {e}")
            time.sleep(random.uniform(2, 4))

    if not _is_linkedin_bootstrapped():
        log.warning("LinkedIn bootstrap: no CSRF � using fallback token")
        _set_linkedin_bootstrapped(True)

    sess.headers.update({
        "Csrf-Token":                 _get_linkedin_csrf(),
        "X-Li-Lang":                  "en_US",
        "X-Requested-With":           "XMLHttpRequest",
        "x-restli-protocol-version":  "2.0.0",
        "Referer":                    "https://www.linkedin.com/jobs/search/",
        "Origin":                     "https://www.linkedin.com",
    })

    time.sleep(random.uniform(1.5, 3.5))


#  Standard sessions 
_gov_session = requests.Session()
_gov_session.verify = False
_gov_session.headers.update({
    "User-Agent":      _USER_AGENTS[0],
    "Accept":          "text/html, */*",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
})

_session = requests.Session()
_session.headers.update({
    "User-Agent":      _USER_AGENTS[0],
    "Accept":          "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
})

# Direct session � no proxy, for external API services (SerpAPI, RapidAPI, etc.)
# These services authenticate via API key; routing through proxies causes
# "Proxy Authentication Required" errors and wastes proxy quota.
_direct_session = requests.Session()
_direct_session.headers.update({
    "User-Agent":      _USER_AGENTS[0],
    "Accept":          "application/json",
    "Accept-Language": "en-US,en;q=0.9",
})

_DIRECT_HOSTS = frozenset({
    "serpapi.com",
    "rapidapi.com",
    "api.rapidapi.com",
    "www.googleapis.com",
    "googleapis.com",
    "wuzzuf.net",
    "remotive.com",
    "arbeitnow.com",
    "weworkremotely.com",
    "remoteok.com",
    "himalayas.app",
    "freelancer.com",
    "mostaql.com",
    "t.me",
    "telegram.org",
    "api.telegram.org",
})


def _is_direct_url(url: str) -> bool:
    """Returns True for hosts that must bypass the proxy pool."""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        return host in _DIRECT_HOSTS or any(host.endswith("." + d) for d in _DIRECT_HOSTS)
    except Exception:
        return False


GOV_TIMEOUT = 10

_domain_last_req: dict = {}
_domain_lock = threading.Lock()
_LINKEDIN_MIN_INTERVAL = 3.0


def _get_domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc
    except Exception:
        return url


def _throttle_domain(url: str):
    domain = _get_domain(url)
    if "linkedin.com" not in domain:
        return
    with _domain_lock:
        now  = time.time()
        last = _domain_last_req.get(domain, 0)
        elapsed = now - last
        if elapsed < _LINKEDIN_MIN_INTERVAL:
            wait = _LINKEDIN_MIN_INTERVAL - elapsed + random.uniform(0.5, 3.0)
            time.sleep(wait)
        _domain_last_req[domain] = time.time()


def _is_linkedin_url(url: str) -> bool:
    return "linkedin.com" in url


def _is_gov_url(url: str) -> bool:
    gov_patterns = [
        ".gov.eg", ".sci.eg", ".egcert.eg",
        "egcert.eg", "itida.gov", "nti.sci", "mcit.gov", "ntra.gov",
        "tiec.gov", "depi.gov", "iti.gov", "svholding.com.eg",
        ".gov.sa", "nca.gov.sa", "citc.gov.sa", "sdaia.gov.sa", "qcert.org",
        ".gov.ae", "uaecybersecurity.gov", "tdra.gov.ae",
        ".gov.qa", ".gov.kw", ".gov.bh", ".gov.om",
    ]
    return any(p in url for p in gov_patterns)


def _full_jitter_backoff(attempt: int, base: float = 2.0, cap: float = 60.0) -> float:
    """AWS-style full jitter: avoids thundering herd."""
    return random.uniform(0, min(cap, base * (2 ** attempt)))


def _request_with_retry(method, url, *, session, params=None, headers=None,
                         json=None, timeout=REQUEST_TIMEOUT,
                         max_retries=4, backoff=2.0):
    if _is_linkedin_url(url):
        _bootstrap_linkedin()

    _throttle_domain(url)

    is_li  = _is_linkedin_url(url)
    is_gov = _is_gov_url(url)
    is_dir = _is_direct_url(url)

    request_proxy = None
    if not is_li and not is_gov and not is_dir and _proxy_pool.enabled:
        request_proxy = _proxy_pool.get()

    for attempt in range(max_retries + 1):
        if is_li and attempt > 0:
            session.headers.update({
                "User-Agent":      _random_ua(),
                "Accept-Language": _random_accept_lang(),
            })

        t_start = time.time()
        try:
            with _http_metrics_lock:
                _http_metrics["requests"] += 1
            kwargs: dict = {"params": params, "headers": headers, "json": json, "timeout": timeout}
            if request_proxy and not is_li:
                kwargs["proxies"] = request_proxy

            resp = session.request(method, url, **kwargs)
            elapsed_ms = (time.time() - t_start) * 1000

            if resp.status_code == 429:
                with _http_metrics_lock:
                    _http_metrics["429"] += 1
                proxy_url = (
                    _current_proxy_url(getattr(_linkedin_local, "active_proxy", None))
                    if is_li else _current_proxy_url(request_proxy)
                )
                if proxy_url:
                    _proxy_pool.ban(proxy_url, reason="429")
                    if is_li:
                        _linkedin_local.active_proxy = None
                        _set_linkedin_bootstrapped(False)
                    else:
                        request_proxy = _proxy_pool.get()

                wait = _full_jitter_backoff(attempt, base=backoff, cap=120.0)
                short_url = url[:80] + "�" if len(url) > 80 else url
                log.warning(f"429 on {short_url} � wait {wait:.1f}s (attempt {attempt+1}/{max_retries+1})")
                time.sleep(wait)
                _domain_last_req[_get_domain(url)] = time.time()
                continue

            if resp.status_code == 403:
                with _http_metrics_lock:
                    _http_metrics["403"] += 1
                proxy_url = (
                    _current_proxy_url(getattr(_linkedin_local, "active_proxy", None))
                    if is_li else _current_proxy_url(request_proxy)
                )
                if proxy_url:
                    _proxy_pool.ban(proxy_url, reason="403")
                    if is_li:
                        _linkedin_local.active_proxy = None
                        _set_linkedin_bootstrapped(False)
                if is_dir:
                    log.info(f"HTTP 403 for {url[:80]} � direct API rejected request, skipping")
                else:
                    log.warning(f"HTTP 403 for {url[:80]} � skipping")
                return None

            if resp.status_code == 400 and is_li:
                if attempt < max_retries:
                    _set_linkedin_bootstrapped(False)
                    log.warning(f"HTTP 400 on LinkedIn (bad CSRF) � re-bootstrapping (attempt {attempt+1}) [thread={threading.current_thread().name}]")
                    _bootstrap_linkedin()
                    time.sleep(random.uniform(3, 7))
                    continue
                else:
                    log.warning(f"HTTP 400 for {url} � giving up")
                    return None

            if resp.status_code == 407:
                # Proxy Authentication Required — proxy misconfigured/expired.
                # Ban with 403 penalty (10 min), then retry without proxy.
                with _http_metrics_lock:
                    _http_metrics["403"] += 1
                proxy_url = _current_proxy_url(request_proxy)
                if proxy_url:
                    _proxy_pool.ban(proxy_url, reason="403")
                    request_proxy = _proxy_pool.get()
                log.warning(f"HTTP 407 Proxy Auth Required for {url[:80]} — proxy banned")
                if attempt < max_retries:
                    continue
                return None

            
                log.warning(f"HTTP {resp.status_code} for {url} � skipping")
                return None

            resp.raise_for_status()

            if request_proxy:
                _proxy_pool.report_success(_current_proxy_url(request_proxy), elapsed_ms)

            return resp

        except requests.exceptions.ProxyError as e:
            with _http_metrics_lock:
                _http_metrics["errors"] += 1
            proxy_url = _current_proxy_url(request_proxy) if request_proxy else None
            err_str = str(e).lower()
            if proxy_url:
                # 407 = proxy auth failure → ban longer (same as 403 = 10 min)
                reason = "403" if ("407" in err_str or "proxy authentication" in err_str) else "conn_error"
                _proxy_pool.ban(proxy_url, reason=reason)
                request_proxy = _proxy_pool.get()
            if attempt < max_retries:
                time.sleep(_full_jitter_backoff(attempt, base=backoff))
            else:
                raise e

        except requests.RequestException as e:
            with _http_metrics_lock:
                _http_metrics["errors"] += 1
            if attempt < max_retries:
                time.sleep(_full_jitter_backoff(attempt, base=backoff))
            else:
                raise e

    return None


def get_json(url: str, params: dict = None, headers: dict = None,
             timeout: int = REQUEST_TIMEOUT, max_retries: int = 4) -> dict | list | None:
    if _is_linkedin_url(url):
        sess = _get_linkedin_session()
    elif _is_gov_url(url):
        sess = _gov_session
    elif _is_direct_url(url):
        # External API services (SerpAPI, RapidAPI) must bypass the proxy pool.
        # They use their own API-key auth; proxy auth headers cause 407 errors.
        sess = _direct_session
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
        log.debug(f"JSON parse error for {url}: {e}")
        return None


def get_text(url: str, params: dict = None, headers: dict = None,
             timeout: int = REQUEST_TIMEOUT, max_retries: int = 4) -> str | None:
    if _is_linkedin_url(url):
        sess = _get_linkedin_session()
    elif _is_gov_url(url):
        sess = _gov_session
    elif _is_direct_url(url):
        sess = _direct_session
    else:
        sess = _session
    t = GOV_TIMEOUT if _is_gov_url(url) else timeout
    try:
        resp = _request_with_retry("GET", url, session=sess,
                                   params=params, headers=headers, timeout=t,
                                   max_retries=max_retries)
        if resp is None:
            return None
        return resp.text
    except requests.RequestException as e:
        log.warning(f"GET text {url} failed: {e}")
        return None


def get_proxy_status() -> dict:
    return _proxy_pool.status()


def get_http_metrics() -> dict:
    with _http_metrics_lock:
        return dict(_http_metrics)
