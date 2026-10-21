"""HTTP client for the Transport Victoria GTFS-Realtime API.

Three responsibilities:

1. **Auth negotiation (ADR-008).** DTP's documents disagree on how the key is sent, so the client
   tries each configured method in order on the first call per mode, caches the winner, and
   re-negotiates once if a cached method later starts returning 401/403.
2. **Rate limiting.** A per-mode sliding-window limiter keeps us far under the published limit.
3. **Resilience.** Exponential backoff with jitter on 429/5xx and connection errors; every error
   message is redacted so the key never leaks into logs.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from movemelbourne.utils.logging import redact, register_secret

logger = logging.getLogger(__name__)

AUTH_METHODS = ("ocp_header", "keyid_header", "query_param")
_AUTH_FAILURE = {401, 403}
_RETRYABLE = {429, 500, 502, 503, 504}


class AuthError(RuntimeError):
    """Every configured auth method was rejected for a mode."""


class RetryableHTTPError(RuntimeError):
    """A 429/5xx response worth retrying."""


@dataclass
class FetchResult:
    """Outcome of one successful feed poll."""

    mode: str
    feed: str
    status: int
    content: bytes
    auth_method: str
    elapsed_s: float
    fetched_at: float

    @property
    def n_bytes(self) -> int:
        return len(self.content)


@dataclass
class RateLimiter:
    """Sliding-window limiter: at most ``max_calls`` per ``period_s`` per key."""

    max_calls: int
    period_s: float = 60.0
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _calls: dict[str, deque[float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def acquire(self, key: str) -> None:
        """Block until a call for ``key`` is allowed, then record it."""
        while True:
            with self._lock:
                now = self.clock()
                window = self._calls.setdefault(key, deque())
                while window and now - window[0] >= self.period_s:
                    window.popleft()
                if len(window) < self.max_calls:
                    window.append(now)
                    return
                wait = self.period_s - (now - window[0]) + 0.01
            logger.debug("rate limiter: %s waiting %.1fs", key, wait)
            self.sleep(wait)


class FeedClient:
    """Fetch GTFS-Realtime protobuf payloads with auth negotiation and rate limiting."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        *,
        auth_methods: Sequence[str] = AUTH_METHODS,
        max_calls_per_min: int = 6,
        connect_timeout_s: float = 10,
        read_timeout_s: float = 30,
        session: requests.Session | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("TVOD_API_KEY is not set (see .env.example)")
        unknown = set(auth_methods) - set(AUTH_METHODS)
        if unknown:
            raise ValueError(f"Unknown auth methods: {sorted(unknown)}")
        register_secret(api_key)
        self._key = api_key
        self.base_url = base_url.rstrip("/")
        self.auth_methods = tuple(auth_methods)
        self.timeout = (connect_timeout_s, read_timeout_s)
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/x-protobuf, application/octet-stream, */*",
                "User-Agent": "MoveMelbourne/0.1 (portfolio research; github.com/KarthikReddy-Tanigundala)",
            }
        )
        self.limiter = limiter or RateLimiter(max_calls=max_calls_per_min)
        self.auth_cache: dict[str, str] = {}

    def url(self, mode: str, feed: str) -> str:
        """Endpoint URL without credentials (safe to log)."""
        return f"{self.base_url}/{mode}/{feed}"

    def _request_kwargs(self, method: str) -> dict:
        if method == "ocp_header":
            return {"headers": {"Ocp-Apim-Subscription-Key": self._key}}
        if method == "keyid_header":
            return {"headers": {"KeyID": self._key}}
        return {"params": {"subscription-key": self._key}}

    @retry(
        retry=retry_if_exception_type(
            (RetryableHTTPError, requests.ConnectionError, requests.Timeout)
        ),
        wait=wait_random_exponential(multiplier=2, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _get(self, mode: str, feed: str, method: str) -> requests.Response:
        self.limiter.acquire(mode)
        try:
            response = self.session.get(
                self.url(mode, feed), timeout=self.timeout, **self._request_kwargs(method)
            )
        except requests.RequestException as exc:
            # requests puts the full URL (including a query-param key) into exception text.
            raise type(exc)(redact(str(exc))) from None
        if response.status_code in _RETRYABLE:
            logger.warning("%s/%s HTTP %s, will retry", mode, feed, response.status_code)
            raise RetryableHTTPError(f"{mode}/{feed} HTTP {response.status_code}")
        return response

    def _negotiate(self, mode: str, feed: str) -> tuple[requests.Response, str]:
        last_status = None
        for method in self.auth_methods:
            response = self._get(mode, feed, method)
            if response.status_code not in _AUTH_FAILURE:
                logger.info(
                    "auth negotiated for %s: %s (HTTP %s)", mode, method, response.status_code
                )
                self.auth_cache[mode] = method
                return response, method
            last_status = response.status_code
            logger.info("auth method %s rejected for %s (HTTP %s)", method, mode, last_status)
        raise AuthError(f"All auth methods rejected for mode={mode} (last HTTP {last_status})")

    def fetch(self, mode: str, feed: str) -> FetchResult:
        """Fetch one feed. Raises on auth failure or a non-200 after retries."""
        started = time.monotonic()
        method = self.auth_cache.get(mode)
        if method is None:
            response, method = self._negotiate(mode, feed)
        else:
            response = self._get(mode, feed, method)
            if response.status_code in _AUTH_FAILURE:
                logger.warning(
                    "cached auth %s for %s now HTTP %s; re-negotiating",
                    method,
                    mode,
                    response.status_code,
                )
                self.auth_cache.pop(mode, None)
                response, method = self._negotiate(mode, feed)
        if response.status_code != 200:
            raise requests.HTTPError(f"{mode}/{feed} HTTP {response.status_code}")
        return FetchResult(
            mode=mode,
            feed=feed,
            status=response.status_code,
            content=response.content,
            auth_method=method,
            elapsed_s=round(time.monotonic() - started, 3),
            fetched_at=time.time(),
        )
