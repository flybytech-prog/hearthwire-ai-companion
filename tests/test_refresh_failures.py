"""Refresh-endpoint outages must not look like a sign-out."""

import base64
import fcntl
import json
import os
from datetime import timedelta

import pytest

from hearthwire.core.auth import SecretToolStore
from hearthwire.core.locking import credential_lock, lock_directory
from hearthwire.core.model import FailureKind, ProviderStatus
from hearthwire.providers.cursor import (
    ACCESS_KEY,
    MEMBERSHIP_KEY,
    PLAN_URL,
    REFRESH_KEY,
    REFRESH_URL as CURSOR_REFRESH_URL,
    USAGE_URL as CURSOR_USAGE_URL,
    CursorAuthStore,
    CursorProvider,
)
from hearthwire.providers.grok import GrokProvider

from test_additional_providers import (
    GROK_EXPIRED,
    GROK_FRESH,
    NOW,
    _grok_getter,
    _grok_saved,
    _grok_store,
    _write_grok_file,
    create_state_database,
    environment,
    response,
)


GROK_SOON = (NOW + timedelta(minutes=2)).isoformat()


def _jwt(expires_at):
    def segment(value):
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{segment({'alg': 'none'})}.{segment({'exp': expires_at.timestamp()})}."


CURSOR_FRESH_JWT = _jwt(NOW + timedelta(days=1))
CURSOR_SOON_JWT = _jwt(NOW + timedelta(minutes=2))
CURSOR_EXPIRED_JWT = _jwt(NOW - timedelta(minutes=1))

CURSOR_USAGE = {
    "enabled": True,
    "billingCycleEnd": "2027-02-01T00:00:00Z",
    "planUsage": {"totalPercentUsed": 25},
}


def _cursor_provider(tmp_path, monkeypatch, access, refresh_poster, usage=None):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    config = tmp_path / "config"
    create_state_database(config / "Cursor/User/globalStorage/state.vscdb", {
        ACCESS_KEY: access,
        REFRESH_KEY: "cursor-refresh",
        MEMBERSHIP_KEY: "pro",
    })
    store = CursorAuthStore(
        environment({"XDG_CONFIG_HOME": str(config)}),
        secret_store=SecretToolStore(executable=""),
        now=lambda: NOW,
    )
    calls = {"refresh": [], "usage": []}
    usage_responses = list(usage or [])

    def poster(url, body, headers, timeout=15.0):
        if url == CURSOR_REFRESH_URL:
            calls["refresh"].append(body["refresh_token"])
            return refresh_poster()
        if url == PLAN_URL:
            return response({"planInfo": {"planName": "Pro"}})
        assert url == CURSOR_USAGE_URL
        calls["usage"].append(headers["Authorization"])
        if usage_responses:
            return usage_responses.pop(0)
        return response(CURSOR_USAGE)

    provider = CursorProvider(auth_store=store, poster=poster, now=lambda: NOW)
    return provider, calls


def _raise():
    raise OSError("network down")


def test_cursor_refresh_server_error_is_transient(tmp_path, monkeypatch):
    provider, calls = _cursor_provider(
        tmp_path, monkeypatch, "not-a-jwt", lambda: response({}, status=503),
    )
    usage = provider.fetch()
    assert usage.status == ProviderStatus.ERROR
    assert usage.failure_kind == FailureKind.TRANSIENT
    assert usage.error_message == "Cursor could not refresh its session."
    assert calls["refresh"] == ["cursor-refresh"]


def test_cursor_refresh_429_is_rate_limited_with_retry_after(tmp_path, monkeypatch):
    provider, _ = _cursor_provider(
        tmp_path, monkeypatch, "not-a-jwt",
        lambda: response({}, status=429, headers={"Retry-After": "120"}),
    )
    usage = provider.fetch()
    assert usage.status == ProviderStatus.RATE_LIMITED
    assert usage.failure_kind == FailureKind.RATE_LIMITED
    assert usage.retry_at == NOW + timedelta(seconds=120)


def test_cursor_refresh_network_error_is_transient(tmp_path, monkeypatch):
    provider, _ = _cursor_provider(tmp_path, monkeypatch, "not-a-jwt", _raise)
    usage = provider.fetch()
    assert usage.failure_kind == FailureKind.TRANSIENT


@pytest.mark.parametrize("refresh", [
    lambda: response({"error": "invalid_grant"}, status=400),
    lambda: response({"access_token": "new-access", "shouldLogout": True}),
])
def test_cursor_refused_refresh_is_signed_out(tmp_path, monkeypatch, refresh):
    provider, _ = _cursor_provider(tmp_path, monkeypatch, "not-a-jwt", refresh)
    usage = provider.fetch()
    assert usage.status == ProviderStatus.UNAUTHENTICATED
    assert usage.failure_kind == FailureKind.AUTHENTICATION


def test_cursor_rejected_token_then_refresh_outage_is_transient(tmp_path, monkeypatch):
    provider, calls = _cursor_provider(
        tmp_path, monkeypatch, CURSOR_FRESH_JWT,
        lambda: response({}, status=503),
        usage=[response({}, status=401)],
    )
    usage = provider.fetch()
    assert usage.failure_kind == FailureKind.TRANSIENT
    assert calls["refresh"] == ["cursor-refresh"]


def test_cursor_soon_expiring_token_survives_refresh_outage(tmp_path, monkeypatch):
    provider, calls = _cursor_provider(
        tmp_path, monkeypatch, CURSOR_SOON_JWT, lambda: response({}, status=503),
    )
    usage = provider.fetch()
    assert usage.status == ProviderStatus.OK
    assert calls["refresh"] == ["cursor-refresh"]
    assert calls["usage"] == [f"Bearer {CURSOR_SOON_JWT}"]


def test_cursor_soon_expiring_token_survives_rate_limited_refresh(tmp_path, monkeypatch):
    provider, _ = _cursor_provider(
        tmp_path, monkeypatch, CURSOR_SOON_JWT,
        lambda: response({}, status=429, headers={"Retry-After": "60"}),
    )
    assert provider.fetch().status == ProviderStatus.OK


def test_cursor_expired_token_reports_refresh_outage(tmp_path, monkeypatch):
    provider, calls = _cursor_provider(
        tmp_path, monkeypatch, CURSOR_EXPIRED_JWT, lambda: response({}, status=503),
    )
    usage = provider.fetch()
    assert usage.failure_kind == FailureKind.TRANSIENT
    assert calls["usage"] == []


def test_cursor_soon_token_rejected_after_failed_refresh_does_not_resend(
    tmp_path, monkeypatch,
):
    provider, calls = _cursor_provider(
        tmp_path, monkeypatch, CURSOR_SOON_JWT,
        lambda: response({}, status=503),
        usage=[response({}, status=401), response({}, status=401)],
    )
    first = provider.fetch()
    second = provider.fetch()
    for usage in (first, second):
        assert usage.failure_kind == FailureKind.TRANSIENT
    assert calls["refresh"] == ["cursor-refresh"]


def test_cursor_soon_token_refused_refresh_is_signed_out(tmp_path, monkeypatch):
    # Only outages fall through; a refused grant means the session is gone.
    provider, calls = _cursor_provider(
        tmp_path, monkeypatch, CURSOR_SOON_JWT,
        lambda: response({"error": "invalid_grant"}, status=400),
    )
    usage = provider.fetch()
    assert usage.status == ProviderStatus.UNAUTHENTICATED
    assert calls["refresh"] == ["cursor-refresh"]
    assert calls["usage"] == []


def test_cursor_successful_refresh_is_used_for_usage(tmp_path, monkeypatch):
    provider, calls = _cursor_provider(
        tmp_path, monkeypatch, CURSOR_EXPIRED_JWT,
        lambda: response({"access_token": CURSOR_FRESH_JWT}),
    )
    usage = provider.fetch()
    assert usage.status == ProviderStatus.OK
    assert calls["usage"] == [f"Bearer {CURSOR_FRESH_JWT}"]


def _grok_provider(path, monkeypatch, poster, getter=None, **kwargs):
    seen = []
    provider = GrokProvider(
        auth_store=_grok_store(path, monkeypatch),
        getter=getter or _grok_getter(seen),
        form_poster=poster,
        now=lambda: NOW,
        **kwargs,
    )
    return provider, seen


def _recording_poster(posts, reply):
    def poster(url, data, headers, timeout=15.0):
        posts.append(dict(data)["refresh_token"])
        return reply()

    return poster


def _no_post(*args, **kwargs):
    raise AssertionError("refresh must not be sent")


def test_grok_soon_without_refresh_token_uses_current_token(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    path.write_text(json.dumps({
        "user::client-id": {"key": "old-access", "expires_at": GROK_SOON},
    }), encoding="utf-8")
    provider, seen = _grok_provider(path, monkeypatch, _no_post)
    usage = provider.fetch()
    assert usage.status == ProviderStatus.OK
    assert seen == ["Bearer old-access"]


@pytest.mark.parametrize("status", [503, 400])
def test_grok_soon_refresh_failure_uses_current_token(tmp_path, monkeypatch, status):
    path = tmp_path / "auth.json"
    _write_grok_file(path, "old-access", "old-refresh", GROK_SOON)
    posts = []
    provider, seen = _grok_provider(
        path, monkeypatch,
        _recording_poster(posts, lambda: response({}, status=status)),
    )
    usage = provider.fetch()
    assert usage.status == ProviderStatus.OK
    assert posts == ["old-refresh"]
    assert seen == ["Bearer old-access"]
    assert _grok_saved(path) == ("old-access", "old-refresh")


def test_grok_soon_with_lock_held_uses_current_token(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    _write_grok_file(path, "old-access", "old-refresh", GROK_SOON)
    with credential_lock("grok"):
        pass
    holder = os.open(lock_directory() / "grok.lock", os.O_RDWR)
    fcntl.flock(holder, fcntl.LOCK_EX)
    try:
        provider, seen = _grok_provider(path, monkeypatch, _no_post, lock_timeout=0.2)
        usage = provider.fetch()
    finally:
        os.close(holder)
    assert usage.status == ProviderStatus.OK
    assert seen == ["Bearer old-access"]


def test_grok_expired_refresh_outage_is_transient(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    _write_grok_file(path, "old-access", "old-refresh", GROK_EXPIRED)
    posts = []
    provider, seen = _grok_provider(
        path, monkeypatch,
        _recording_poster(posts, lambda: response({}, status=503)),
    )
    usage = provider.fetch()
    assert usage.status == ProviderStatus.ERROR
    assert usage.failure_kind == FailureKind.TRANSIENT
    assert usage.error_message == "Grok could not refresh its session."
    assert posts == ["old-refresh"]
    assert seen == []


def test_grok_expired_refresh_network_error_is_transient(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    _write_grok_file(path, "old-access", "old-refresh", GROK_EXPIRED)

    def poster(*args, **kwargs):
        raise OSError("network down")

    provider, _ = _grok_provider(path, monkeypatch, poster)
    assert provider.fetch().failure_kind == FailureKind.TRANSIENT


def test_grok_expired_refresh_429_is_rate_limited(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    _write_grok_file(path, "old-access", "old-refresh", GROK_EXPIRED)
    provider, _ = _grok_provider(
        path, monkeypatch,
        _recording_poster(
            [], lambda: response({}, status=429, headers={"Retry-After": "90"}),
        ),
    )
    usage = provider.fetch()
    assert usage.status == ProviderStatus.RATE_LIMITED
    assert usage.failure_kind == FailureKind.RATE_LIMITED
    assert usage.retry_at == NOW + timedelta(seconds=90)


def test_grok_expired_without_refresh_token_is_signed_out(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    path.write_text(json.dumps({
        "user::client-id": {"key": "old-access", "expires_at": GROK_EXPIRED},
    }), encoding="utf-8")
    provider, seen = _grok_provider(path, monkeypatch, _no_post)
    usage = provider.fetch()
    assert usage.status == ProviderStatus.UNAUTHENTICATED
    assert seen == []


def test_grok_rejected_token_with_refused_refresh_is_signed_out_once(
    tmp_path, monkeypatch,
):
    path = tmp_path / "auth.json"
    _write_grok_file(path, "old-access", "old-refresh", GROK_FRESH)
    posts = []
    provider, _ = _grok_provider(
        path, monkeypatch,
        _recording_poster(posts, lambda: response({"error": "invalid_grant"}, status=400)),
        getter=lambda *args, **kwargs: response({}, status=401),
    )
    first = provider.fetch()
    second = provider.fetch()
    assert first.status == ProviderStatus.UNAUTHENTICATED
    assert second.status == ProviderStatus.UNAUTHENTICATED
    assert posts == ["old-refresh"]


def test_grok_failed_save_repeats_storage_without_resending(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    _write_grok_file(path, "old-access", "old-refresh", GROK_EXPIRED)
    posts = []
    store = _grok_store(path, monkeypatch)
    monkeypatch.setattr(store, "save", lambda credentials: False)
    provider = GrokProvider(
        auth_store=store,
        getter=_no_post,
        form_poster=_recording_poster(posts, lambda: response({
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        })),
        now=lambda: NOW,
    )
    first = provider.fetch()
    second = provider.fetch()
    for usage in (first, second):
        assert usage.status == ProviderStatus.ERROR
        assert usage.failure_kind == FailureKind.STORAGE
        assert usage.error_message == "Grok credentials could not be updated."
    assert posts == ["old-refresh"]
    assert _grok_saved(path) == ("old-access", "old-refresh")
