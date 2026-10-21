"""Auth negotiation, re-negotiation, retries, rate limiting and key redaction."""

from __future__ import annotations

import logging

import pytest
import requests

from movemelbourne.collect.client import AuthError, FeedClient, RateLimiter
from movemelbourne.utils.logging import RedactingFilter, redact

KEY = "abcdef0123456789secret"


class FakeResponse:
    def __init__(self, status: int, content: bytes = b"") -> None:
        self.status_code = status
        self.content = content


class FakeSession:
    """Accepts only one auth style; records what each call sent."""

    def __init__(self, accept: str, statuses: list[int] | None = None) -> None:
        self.accept = accept
        self.headers: dict = {}
        self.calls: list[dict] = []
        self.statuses = statuses or []

    def get(self, url, timeout=None, headers=None, params=None):
        self.calls.append({"url": url, "headers": headers or {}, "params": params or {}})
        if self.statuses:
            return FakeResponse(self.statuses.pop(0), b"payload")
        sent = (
            "ocp_header"
            if "Ocp-Apim-Subscription-Key" in (headers or {})
            else "keyid_header"
            if "KeyID" in (headers or {})
            else "query_param"
        )
        return FakeResponse(200 if sent == self.accept else 401, b"payload")


def make_client(session) -> FeedClient:
    limiter = RateLimiter(max_calls=1000, sleep=lambda s: None)
    return FeedClient(KEY, "https://example.test/v1", session=session, limiter=limiter)


def test_negotiates_falls_back_to_keyid_and_caches():
    session = FakeSession(accept="keyid_header")
    client = make_client(session)
    result = client.fetch("tram", "trip-updates")
    assert result.auth_method == "keyid_header" and result.content == b"payload"
    assert len(session.calls) == 2  # ocp rejected, KeyID accepted
    client.fetch("tram", "vehicle-positions")
    assert len(session.calls) == 3  # cached method used directly
    assert client.auth_cache == {"tram": "keyid_header"}


def test_query_param_is_last_resort():
    session = FakeSession(accept="query_param")
    result = make_client(session).fetch("metro", "trip-updates")
    assert result.auth_method == "query_param"
    assert session.calls[-1]["params"] == {"subscription-key": KEY}


def test_all_methods_rejected_raises_auth_error():
    session = FakeSession(accept="none")
    with pytest.raises(AuthError):
        make_client(session).fetch("metro", "trip-updates")


def test_renegotiates_when_cached_method_starts_failing():
    session = FakeSession(accept="ocp_header")
    client = make_client(session)
    client.fetch("metro", "trip-updates")
    session.accept = "keyid_header"
    assert client.fetch("metro", "trip-updates").auth_method == "keyid_header"


def test_retries_on_503_then_succeeds(monkeypatch):
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda s: None)
    session = FakeSession(accept="ocp_header", statuses=[503, 200])
    assert make_client(session).fetch("metro", "trip-updates").status == 200
    assert len(session.calls) == 2


def test_non_200_after_negotiation_raises():
    session = FakeSession(accept="ocp_header", statuses=[404])
    with pytest.raises(requests.HTTPError):
        make_client(session).fetch("metro", "nope")


def test_connection_error_message_is_redacted(monkeypatch):
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda s: None)

    class Boom(FakeSession):
        def get(self, url, **kw):
            raise requests.ConnectionError(f"failed {url}?subscription-key={KEY}")

    with pytest.raises(requests.ConnectionError) as info:
        make_client(Boom("x")).fetch("metro", "trip-updates")
    assert KEY not in str(info.value)


def test_rate_limiter_blocks_after_max_calls():
    now = [0.0]
    slept: list[float] = []

    def fake_sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    limiter = RateLimiter(max_calls=2, period_s=60, clock=lambda: now[0], sleep=fake_sleep)
    limiter.acquire("metro")
    limiter.acquire("metro")
    limiter.acquire("tram")  # separate budget per mode
    assert slept == []
    limiter.acquire("metro")
    assert slept and slept[0] == pytest.approx(60.01)


def test_redact_masks_registered_key_and_query_param(caplog):
    client = make_client(FakeSession(accept="ocp_header"))
    assert client  # registering happens in the constructor
    assert redact(f"token {KEY} leaked") == "token *** leaked"
    assert redact("https://x/y?subscription-key=zzz&a=1") == "https://x/y?subscription-key=***&a=1"
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "key=%s", (KEY,), None)
    RedactingFilter().filter(record)
    assert KEY not in record.getMessage()


def test_missing_key_is_rejected():
    with pytest.raises(ValueError):
        FeedClient("", "https://example.test")
