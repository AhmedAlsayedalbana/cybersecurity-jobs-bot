"""HTTP client shared by every source — v56 (merged edition).

Base behaviour is direct-only, exactly like v55: a request either reaches the
target directly, gets rendered through the Reader fallback elsewhere in the
codebase, or is reported as unavailable.  On top of that, this version adds an
**optional** rotating-proxy layer ported from the v54 branch:

  * If the `PROXIES` env var is unset/empty, nothing changes — every request
    goes out directly, exactly like before.
  * If `PROXIES` is set (comma-separated `scheme://user:pass@host:port` list),
    a thread-safe pool with health scoring, banning/cooldowns and per-domain
    stickiness is used to pick a proxy for each request.
  * Any caller can force a direct connection regardless of the pool via
    `use_proxy=False` — this replaces the old pattern of hand-rolling a
    second, unmonitored `requests.Session()` inside a source module (which
    used to bypass retries, rate limiting and metrics entirely).

No proxy credentials or hostnames are ever logged in full.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import random
import threading
import time
from collections import defaultdict
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import requests

from config import REQUEST_TIMEOUT

log = logging.getLogger(__name__)

_DEFAULT_HEADERS = {
    "User-Agent": "CybersecurityJobsBot/56 (+public-job-discovery)",
    "Accept": "application/json, text/html, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}
_LINKEDIN_HEADERS = {
    **_DEFAULT_HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _new_session(headers: dict[str, str] | None = None) -> requests.Session:
    session = requests.Session()
    # Do not inherit HTTP(S)_PROXY from a runner or developer shell — proxy
    # usage is opt-in and controlled exclusively through the PROXIES env var
    # and the _ProxyPool below.
    session.trust_env = False
    session.headers.update(headers or _DEFAULT_HEADERS)
    return session


_session = _new_session()
_thread_local = threading.local()
_last_request: dict[str, float] = defaultdict(float)
_domain_lock = threading.Lock()
_metrics_lock = threading.Lock()
_metrics = {"requests": 0, "429": 0, "403": 0, "errors": 0}
_MIN_DOMAIN_INTERVAL_SECONDS = 0.35


# ── Proxy pool (opt-in, ported from v54 with health scoring kept intact) ────

class _ProxyPool:
    """Thread-safe proxy pool with health scoring and per-domain stickiness.

    Disabled automatically (self._proxies == []) unless PROXIES is set, in
    which case every method below is a no-op and callers fall back to a
    direct connection exactly like v55 did.
    """

    COOLDOWN_429 = 300   # 5 min — 429s are usually a short-lived rate limit
    COOLDOWN_403 = 900   # 15 min — 403s are a firmer, longer-lived block
    COOLDOWN_ERR = 90    # 90 sec — plain connection errors
    SCORE_FLOOR = 5.0    # proxies never drop to 0 / become unselectable
    SCORE_INIT = 50.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Public ATS APIs are more reliable over a direct connection. A stale
        # proxy previously converted every request into a 402 before it reached
        # the target, so proxy routing is now an explicit opt-in.
        enabled = os.environ.get("ENABLE_PROXY_POOL", "").strip().lower() in {"1", "true", "yes", "on"}
        raw = os.environ.get("PROXIES", "").strip() if enabled else ""
        self._proxies: list[str] = [p.strip() for p in raw.split(",") if p.strip()]
        self._banned: dict[str, float] = {}
        self._scores: dict[str, float] = {p: self.SCORE_INIT for p in self._proxies}
        self._sticky: dict[str, str] = {}

        if self._proxies:
            log.info("ProxyPool: %d proxies loaded.", len(self._proxies))
        else:
            log.info("ProxyPool: no PROXIES configured — direct connection mode.")

    @property
    def enabled(self) -> bool:
        return bool(self._proxies)

    def _available(self) -> list[str]:
        now = time.time()
        # Partially restore score on ban expiry so a proxy banned twice
        # doesn't permanently sink to 0 and vanish from the pool.
        expired = {k for k, v in self._banned.items() if v <= now}
        for p in expired:
            self._scores[p] = max(self._scores.get(p, 0.0), 20.0)
        self._banned = {k: v for k, v in self._banned.items() if v > now}
        return [p for p in self._proxies if p not in self._banned]

    def get(self, host: str = "", sticky: bool = False) -> dict[str, str] | None:
        if not self._proxies:
            return None
        with self._lock:
            available = self._available()
            if not available:
                return None

            if sticky and host:
                thread_key = f"{threading.current_thread().ident}:{host}"
                cached = self._sticky.get(thread_key)
                if cached in available:
                    return {"http": cached, "https": cached}

            scores = [max(self._scores.get(p, 50.0), 1.0) for p in available]
            total = sum(scores)
            probs = [s / total for s in scores]

            rand = random.random()
            cumulative = 0.0
            selected = available[0]
            for proxy, prob in zip(available, probs):
                cumulative += prob
                if rand <= cumulative:
                    selected = proxy
                    break

            if sticky and host:
                self._sticky[f"{threading.current_thread().ident}:{host}"] = selected

            return {"http": selected, "https": selected}

    def report_success(self, proxy_url: str, elapsed_ms: float = 0.0) -> None:
        with self._lock:
            if proxy_url not in self._scores:
                return
            boost = 1.0 if elapsed_ms < 3000 else -0.5
            self._scores[proxy_url] = min(100.0, self._scores[proxy_url] + boost)

    def ban(self, proxy_url: str, reason: str = "429") -> None:
        with self._lock:
            if reason == "403":
                cooldown, penalty = self.COOLDOWN_403, 30.0
            elif reason == "429":
                cooldown, penalty = self.COOLDOWN_429, 10.0
            else:
                cooldown, penalty = self.COOLDOWN_ERR, 5.0

            self._banned[proxy_url] = time.time() + cooldown
            self._scores[proxy_url] = max(
                self.SCORE_FLOOR, self._scores.get(proxy_url, self.SCORE_INIT) - penalty,
            )
            stale_keys = [k for k, v in self._sticky.items() if v == proxy_url]
            for key in stale_keys:
                del self._sticky[key]

            log.debug("ProxyPool: banned proxy (reason=%s, cooldown=%ss)", reason, cooldown)

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


def _proxy_url_of(proxy_dict: dict[str, str] | None) -> str | None:
    if proxy_dict:
        return proxy_dict.get("https") or proxy_dict.get("http")
    return None


def get_proxy_status() -> dict:
    """Snapshot of proxy pool health for the health report / DB logging."""
    return _proxy_pool.status()


@dataclass(frozen=True, slots=True)
class HttpTextResult:
    text: str | None
    status_code: int | None
    error_code: str = ""
    retry_after_seconds: int | None = None


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _wait_for_domain(url: str) -> None:
    domain = _domain(url)
    with _domain_lock:
        elapsed = time.monotonic() - _last_request[domain]
        if elapsed < _MIN_DOMAIN_INTERVAL_SECONDS:
            time.sleep(_MIN_DOMAIN_INTERVAL_SECONDS - elapsed)
        _last_request[domain] = time.monotonic()


def _retry_after(response: requests.Response) -> int | None:
    raw = (response.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        try:
            return max(0, int((parsedate_to_datetime(raw).timestamp() - time.time())))
        except (TypeError, ValueError, OverflowError):
            return None


def _get_linkedin_session() -> requests.Session:
    """Return a direct LinkedIn session; LI_AT remains optional user auth."""
    if not hasattr(_thread_local, "linkedin_session"):
        session = _new_session(_LINKEDIN_HEADERS)
        cookie = os.getenv("LI_AT", "").strip()
        if cookie:
            session.cookies.set("li_at", cookie, domain=".linkedin.com")
        _thread_local.linkedin_session = session
        _thread_local.linkedin_bootstrapped = False
    return _thread_local.linkedin_session


def _bootstrap_linkedin() -> None:
    """Best-effort direct bootstrap kept for legacy LinkedIn fetchers."""
    if getattr(_thread_local, "linkedin_bootstrapped", False):
        return
    session = _get_linkedin_session()
    proxy = _proxy_pool.get(host="linkedin.com", sticky=True)
    if proxy:
        session.proxies.update(proxy)
    try:
        _wait_for_domain("https://www.linkedin.com")
        response = session.get(
            "https://www.linkedin.com/jobs/search/?keywords=cybersecurity&location=Egypt",
            timeout=min(REQUEST_TIMEOUT, 15),
            allow_redirects=True,
        )
        csrf = (session.cookies.get("JSESSIONID") or "").strip('"')
        if csrf:
            session.headers["Csrf-Token"] = csrf
        if response.status_code in {401, 403, 429} and proxy:
            reason = "403" if response.status_code in (401, 403) else "429"
            _proxy_pool.ban(_proxy_url_of(proxy), reason=reason)
            session.proxies.clear()
            log.info("LinkedIn direct bootstrap returned HTTP %s", response.status_code)
    except requests.RequestException as exc:
        log.debug("LinkedIn direct bootstrap failed: %s", exc)
    finally:
        _thread_local.linkedin_bootstrapped = True


def _is_linkedin_url(url: str) -> bool:
    return "linkedin.com" in _domain(url)


def _is_direct_url(url: str) -> bool:
    """Compatibility helper: every request is direct unless routed via proxy."""
    return bool(urlparse(url).scheme)


def _request_with_retry(
    method: str,
    url: str,
    *,
    session: requests.Session,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    json: dict[str, Any] | None = None,
    timeout: int = REQUEST_TIMEOUT,
    max_retries: int = 2,
    use_proxy: bool = True,
) -> requests.Response | None:
    if _is_linkedin_url(url):
        _bootstrap_linkedin()

    domain = _domain(url)
    proxy: dict[str, str] | None = None
    if use_proxy and _proxy_pool.enabled and not _is_linkedin_url(url):
        proxy = _proxy_pool.get(host=domain)

    for attempt in range(max_retries + 1):
        _wait_for_domain(url)
        t0 = time.monotonic()
        try:
            with _metrics_lock:
                _metrics["requests"] += 1
            response = session.request(
                method,
                url,
                params=params,
                headers=headers,
                json=json,
                timeout=timeout,
                allow_redirects=True,
                proxies=proxy or {},
            )
        except requests.exceptions.ProxyError as exc:
            with _metrics_lock:
                _metrics["errors"] += 1
            proxy_url = _proxy_url_of(proxy)
            if proxy_url:
                err = str(exc).lower()
                reason = "403" if ("407" in err or "proxy authentication" in err) else "conn_error"
                _proxy_pool.ban(proxy_url, reason=reason)
                proxy = _proxy_pool.get(host=domain) if use_proxy else None
            if attempt >= max_retries:
                log.warning("HTTP %s %s failed (proxy error): %s", method, url[:120], exc)
                return None
            time.sleep(random.uniform(0.3, min(4.0, 0.8 * (2 ** attempt))))
            continue
        except requests.RequestException as exc:
            with _metrics_lock:
                _metrics["errors"] += 1
            if attempt >= max_retries:
                log.warning("HTTP %s %s failed: %s", method, url[:120], exc)
                return None
            time.sleep(random.uniform(0.3, min(4.0, 0.8 * (2 ** attempt))))
            continue

        elapsed_ms = (time.monotonic() - t0) * 1000

        if response.status_code == 429:
            with _metrics_lock:
                _metrics["429"] += 1
            proxy_url = _proxy_url_of(proxy)
            if proxy_url:
                _proxy_pool.ban(proxy_url, reason="429")
                proxy = _proxy_pool.get(host=domain) if use_proxy else None
            if attempt < max_retries:
                wait = _retry_after(response)
                time.sleep(min(60, wait if wait is not None else 1 + attempt))
                continue
            return None

        if response.status_code == 403:
            with _metrics_lock:
                _metrics["403"] += 1
            proxy_url = _proxy_url_of(proxy)
            if proxy_url:
                # A 403 while routed through the pool is often proxy-specific
                # (that IP got flagged) rather than a hard block on the URL —
                # retry with a fresh proxy before giving up.
                _proxy_pool.ban(proxy_url, reason="403")
                proxy = _proxy_pool.get(host=domain) if use_proxy else None
                if attempt < max_retries:
                    time.sleep(random.uniform(0.5, min(4.0, 0.8 * (2 ** attempt))))
                    continue
            return None

        if response.status_code == 407:
            # Proxy authentication required — proxy misconfigured/expired.
            with _metrics_lock:
                _metrics["403"] += 1
            proxy_url = _proxy_url_of(proxy)
            if proxy_url:
                _proxy_pool.ban(proxy_url, reason="403")
                proxy = _proxy_pool.get(host=domain) if use_proxy else None
            if attempt < max_retries:
                continue
            return None

        if response.status_code >= 500 and attempt < max_retries:
            time.sleep(random.uniform(0.3, min(4.0, 0.8 * (2 ** attempt))))
            continue

        try:
            response.raise_for_status()
        except requests.RequestException:
            with _metrics_lock:
                _metrics["errors"] += 1
            return None

        if proxy:
            _proxy_pool.report_success(_proxy_url_of(proxy), elapsed_ms)
        return response
    return None


def get_text_result(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = REQUEST_TIMEOUT,
    max_retries: int = 2,
    use_proxy: bool = True,
) -> HttpTextResult:
    session = _get_linkedin_session() if _is_linkedin_url(url) else _session
    response = _request_with_retry(
        "GET", url, session=session, params=params, headers=headers,
        timeout=timeout, max_retries=max_retries, use_proxy=use_proxy,
    )
    if response is None:
        return HttpTextResult(None, None, "transport_or_rejected")
    return HttpTextResult(response.text, response.status_code)


def get_text(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = REQUEST_TIMEOUT,
    max_retries: int = 2,
    use_proxy: bool = True,
) -> str | None:
    return get_text_result(
        url, params=params, headers=headers, timeout=timeout,
        max_retries=max_retries, use_proxy=use_proxy,
    ).text


def get_json(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = REQUEST_TIMEOUT,
    max_retries: int = 2,
    use_proxy: bool = True,
) -> dict | list | None:
    session = _get_linkedin_session() if _is_linkedin_url(url) else _session
    response = _request_with_retry(
        "GET", url, session=session, params=params, headers=headers,
        timeout=timeout, max_retries=max_retries, use_proxy=use_proxy,
    )
    if response is None:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def post_json(
    url: str,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = REQUEST_TIMEOUT,
    max_retries: int = 2,
    use_proxy: bool = True,
) -> dict | list | None:
    response = _request_with_retry(
        "POST", url, session=_session, headers=headers, json=payload,
        timeout=timeout, max_retries=max_retries, use_proxy=use_proxy,
    )
    if response is None:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def get_http_metrics() -> dict[str, int]:
    with _metrics_lock:
        return dict(_metrics)
