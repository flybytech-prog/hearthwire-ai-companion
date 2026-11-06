import fcntl
import json
import os
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from conftest import fixture
from hearthwire.core.auth import (
    CLAUDE_REFRESH_SCOPES,
    CLAUDE_REFRESH_URL,
    ClaudeAuthStore,
)
from hearthwire.core.environment import LoginShellEnvironment
from hearthwire.core.http import HttpResponse
from hearthwire.core.locking import credential_lock, lock_directory
from hearthwire.core.model import FailureKind, ProviderStatus
from hearthwire.providers.claude import ClaudeProvider, USAGE_URL


NOW = datetime(2027, 1, 15, tzinfo=timezone.utc)


def _credentials(path=None):
    store = ClaudeAuthStore(LoginShellEnvironment(environ={"PATH": "/usr/bin"}))
    return store.load(path or fixture("claude_credentials.json")), store


def _response(status=200, body=None, headers=None):
    value = (
        json.loads(fixture("claude_usage.json").read_text())
        if body is None
        else body
    )
    return HttpResponse(
        status=status,
        body=json.dumps(value).encode(),
        headers={key.lower(): item for key, item in (headers or {}).items()},
    )


def test_claude_fetch_maps_current_windows_plan_and_billing():
    credentials, store = _credentials()
    provider = ClaudeProvider(
        creds=credentials,
        auth_store=store,
        getter=lambda *args, **kwargs: _response(),
        now=lambda: NOW,
    )

    usage = provider.fetch()

    assert usage.status == ProviderStatus.OK
    assert usage.plan == "Max 20x"
    assert {window.kind: window.used_percent for window in usage.windows} == {
        "session": 42,
        "weekly": 18,
        "sonnet": 55,
        "fable": 73,
    }
    assert usage.billing_usage.kind == "bounded_spend"
    assert usage.billing_usage.used_amount == 5
    assert usage.billing_usage.limit_amount == 10


def test_claude_fetch_sets_required_headers():
    credentials, store = _credentials()
    captured = {}

    def getter(url, headers, timeout=15.0):
        captured["url"] = url
        captured["headers"] = headers
        return _response()

    ClaudeProvider(
        creds=credentials,
        auth_store=store,
        getter=getter,
        now=lambda: NOW,
    ).fetch()

    assert captured["url"] == USAGE_URL
    assert captured["headers"]["Authorization"] == "Bearer acc-123"
    assert captured["headers"]["anthropic-beta"] == "oauth-2025-04-20"
    assert captured["headers"]["User-Agent"] == "claude-code/2.1.69"


def test_claude_rejects_known_missing_profile_scope_without_network():
    credentials, store = _credentials()
    credentials = replace(credentials, scopes=("user:inference",))

    def forbidden(*args, **kwargs):
        raise AssertionError("usage endpoint must not be called")

    usage = ClaudeProvider(
        creds=credentials,
        auth_store=store,
        getter=forbidden,
        now=lambda: NOW,
    ).fetch()
    assert usage.status == ProviderStatus.UNAUTHENTICATED
    assert "Re-login" in usage.error_message


def test_claude_retries_401_and_persists_rotated_credentials(tmp_path):
    path = tmp_path / ".credentials.json"
    path.write_text(fixture("claude_credentials.json").read_text(), encoding="utf-8")
    credentials, store = _credentials(path)
    usage_responses = [_response(401, {}), _response()]
    usage_urls = []
    refresh_calls = []

    def getter(url, headers, timeout=15.0):
        usage_urls.append(url)
        return usage_responses.pop(0)

    def poster(url, data, headers, timeout=15.0):
        refresh_calls.append((url, data, headers))
        return _response(200, {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        })

    usage = ClaudeProvider(
        creds=credentials,
        auth_store=store,
        getter=getter,
        json_poster=poster,
        now=lambda: NOW,
    ).fetch()

    assert usage.status == ProviderStatus.OK
    assert usage_urls == [USAGE_URL, USAGE_URL]
    assert refresh_calls[0][0] == CLAUDE_REFRESH_URL
    assert refresh_calls[0][1]["scope"] == CLAUDE_REFRESH_SCOPES
    saved = json.loads(path.read_text())
    assert saved["claudeAiOauth"]["accessToken"] == "new-access"
    assert saved["claudeAiOauth"]["refreshToken"] == "new-refresh"


def test_claude_429_reports_retry_without_persisting_backend_cooldown():
    credentials, store = _credentials()
    calls = 0

    def getter(*args, **kwargs):
        nonlocal calls
        calls += 1
        return _response(429, {}, {"Retry-After": "120"})

    provider = ClaudeProvider(
        creds=credentials,
        auth_store=store,
        getter=getter,
        now=lambda: NOW,
    )
    first = provider.fetch()
    second = provider.fetch()

    assert first.status == ProviderStatus.RATE_LIMITED
    assert first.retry_at == NOW + timedelta(seconds=120)
    assert second.status == ProviderStatus.RATE_LIMITED
    assert calls == 2


def test_claude_invalid_grant_is_authentication_failure():
    credentials, store = _credentials()
    credentials = replace(credentials, expires_at_ms=0)
    usage = ClaudeProvider(
        creds=credentials,
        auth_store=store,
        json_poster=lambda *args, **kwargs: _response(
            400,
            {"error": "invalid_grant"},
        ),
        now=lambda: NOW,
    ).fetch()
    assert usage.status == ProviderStatus.UNAUTHENTICATED
    assert "Session expired" in usage.error_message


def test_claude_unconfigured_is_unauthenticated():
    usage = ClaudeProvider(
        creds=None,
    ).fetch()
    assert usage.status == ProviderStatus.UNAUTHENTICATED


def _write_claude_file(path, access, refresh, expires_at_ms):
    document = json.loads(fixture("claude_credentials.json").read_text())
    document["claudeAiOauth"].update({
        "accessToken": access,
        "refreshToken": refresh,
        "expiresAt": expires_at_ms,
    })
    path.write_text(json.dumps(document), encoding="utf-8")


def _saved_tokens(path):
    oauth = json.loads(path.read_text())["claudeAiOauth"]
    return oauth["accessToken"], oauth["refreshToken"]


def _bearer_getter(seen):
    def getter(url, headers, timeout=15.0):
        seen.append(headers["Authorization"])
        return _response()

    return getter


def test_claude_concurrent_instances_send_one_refresh(tmp_path):
    path = tmp_path / ".credentials.json"
    _write_claude_file(path, "old-access", "old-refresh", 0)
    first_credentials, first_store = _credentials(path)
    second_credentials, second_store = _credentials(path)
    posts = []
    entered = threading.Event()
    release = threading.Event()

    def poster(url, data, headers, timeout=15.0):
        posts.append(data["refresh_token"])
        entered.set()
        assert release.wait(5)
        return _response(200, {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        })

    seen = []
    results = {}
    providers = {
        name: ClaudeProvider(
            creds=credentials,
            auth_store=store,
            getter=_bearer_getter(seen),
            json_poster=poster,
            now=lambda: NOW,
        )
        for name, credentials, store in (
            ("first", first_credentials, first_store),
            ("second", second_credentials, second_store),
        )
    }

    def run(name):
        results[name] = providers[name].fetch()

    first = threading.Thread(target=run, args=("first",))
    first.start()
    assert entered.wait(5)
    second = threading.Thread(target=run, args=("second",))
    second.start()
    time.sleep(0.2)
    release.set()
    first.join(5)
    second.join(5)

    assert posts == ["old-refresh"]
    assert results["first"].status == ProviderStatus.OK
    assert results["second"].status == ProviderStatus.OK
    assert seen == ["Bearer new-access", "Bearer new-access"]
    assert _saved_tokens(path) == ("new-access", "new-refresh")


def test_claude_uses_tokens_rotated_before_lock_without_posting(tmp_path):
    path = tmp_path / ".credentials.json"
    _write_claude_file(path, "old-access", "old-refresh", 0)
    credentials, store = _credentials(path)
    future_ms = (NOW.timestamp() + 3600) * 1000
    _write_claude_file(path, "cli-access", "cli-refresh", future_ms)

    def poster(*args, **kwargs):
        raise AssertionError("refresh must not be sent")

    seen = []
    usage = ClaudeProvider(
        creds=credentials,
        auth_store=store,
        getter=_bearer_getter(seen),
        json_poster=poster,
        now=lambda: NOW,
    ).fetch()
    assert usage.status == ProviderStatus.OK
    assert seen == ["Bearer cli-access"]


def test_claude_401_adopts_access_token_rotated_elsewhere(tmp_path):
    path = tmp_path / ".credentials.json"
    future_ms = (NOW.timestamp() + 3600) * 1000
    _write_claude_file(path, "old-access", "old-refresh", future_ms)
    credentials, store = _credentials(path)
    _write_claude_file(path, "cli-access", "cli-refresh", future_ms)
    responses = [_response(401, {}), _response()]
    seen = []

    def getter(url, headers, timeout=15.0):
        seen.append(headers["Authorization"])
        return responses.pop(0)

    def poster(*args, **kwargs):
        raise AssertionError("refresh must not be sent")

    usage = ClaudeProvider(
        creds=credentials,
        auth_store=store,
        getter=getter,
        json_poster=poster,
        now=lambda: NOW,
    ).fetch()
    assert usage.status == ProviderStatus.OK
    assert seen == ["Bearer old-access", "Bearer cli-access"]


def test_claude_failed_save_is_storage_error_after_one_post(tmp_path):
    path = tmp_path / ".credentials.json"
    _write_claude_file(path, "old-access", "old-refresh", 0)
    credentials, store = _credentials(path)
    posts = []

    def poster(url, data, headers, timeout=15.0):
        posts.append(data["refresh_token"])
        # An external CLI (which does not take our lock) rewrites the file.
        _write_claude_file(path, "cli-access", "cli-refresh", 0)
        return _response(200, {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        })

    def getter(*args, **kwargs):
        raise AssertionError("usage must not be requested")

    usage = ClaudeProvider(
        creds=credentials,
        auth_store=store,
        getter=getter,
        json_poster=poster,
        now=lambda: NOW,
    ).fetch()
    assert usage.status == ProviderStatus.ERROR
    assert usage.failure_kind == FailureKind.STORAGE
    assert usage.error_message == "Claude Code credentials could not be updated."
    assert posts == ["old-refresh"]
    assert _saved_tokens(path) == ("cli-access", "cli-refresh")


def test_claude_lock_timeout_is_transient_without_posting(tmp_path):
    path = tmp_path / ".credentials.json"
    _write_claude_file(path, "old-access", "old-refresh", 0)
    credentials, store = _credentials(path)
    with credential_lock("claude"):
        pass
    holder = os.open(lock_directory() / "claude.lock", os.O_RDWR)
    fcntl.flock(holder, fcntl.LOCK_EX)

    def poster(*args, **kwargs):
        raise AssertionError("refresh must not be sent")

    try:
        usage = ClaudeProvider(
            creds=credentials,
            auth_store=store,
            json_poster=poster,
            now=lambda: NOW,
            lock_timeout=0.2,
        ).fetch()
    finally:
        os.close(holder)
    assert usage.status == ProviderStatus.ERROR
    assert usage.failure_kind == FailureKind.TRANSIENT
    assert "being refreshed by another process" in usage.error_message


def test_claude_never_sends_the_same_refresh_token_twice(tmp_path):
    path = tmp_path / ".credentials.json"
    future_ms = (NOW.timestamp() + 3600) * 1000
    _write_claude_file(path, "old-access", "old-refresh", future_ms)
    credentials, store = _credentials(path)
    posts = []

    def poster(url, data, headers, timeout=15.0):
        posts.append(data["refresh_token"])
        return _response(503, {})

    provider = ClaudeProvider(
        creds=credentials,
        auth_store=store,
        getter=lambda *args, **kwargs: _response(401, {}),
        json_poster=poster,
        now=lambda: NOW,
    )
    first = provider.fetch()
    second = provider.fetch()
    assert first.failure_kind == FailureKind.TRANSIENT
    assert second.status == ProviderStatus.UNAUTHENTICATED
    assert posts == ["old-refresh"]


def _refuse_post(posts):
    def poster(url, data, headers, timeout=15.0):
        posts.append(data)
        raise AssertionError("refresh must not be sent")

    return poster


def _claude_refresh_after(path, mutate):
    _write_claude_file(path, "old-access", "old-refresh", 0)
    credentials, store = _credentials(path)
    mutate(path)
    posts = []
    usage = ClaudeProvider(
        creds=credentials,
        auth_store=store,
        getter=_refuse_usage,
        json_poster=_refuse_post(posts),
        now=lambda: NOW,
    ).fetch()
    return usage, posts


def _refuse_usage(*args, **kwargs):
    raise AssertionError("usage must not be requested")


def test_claude_logout_before_refresh_is_not_logged_in(tmp_path):
    usage, posts = _claude_refresh_after(
        tmp_path / ".credentials.json",
        lambda path: path.unlink(),
    )
    assert usage.status == ProviderStatus.UNAUTHENTICATED
    assert usage.failure_kind == FailureKind.AUTHENTICATION
    assert usage.error_message == "Not logged in. Run `claude` to authenticate."
    assert posts == []


def test_claude_logout_that_empties_the_file_is_not_logged_in(tmp_path):
    usage, posts = _claude_refresh_after(
        tmp_path / ".credentials.json",
        lambda path: path.write_text("{}", encoding="utf-8"),
    )
    assert usage.status == ProviderStatus.UNAUTHENTICATED
    assert posts == []


def test_claude_unreadable_file_at_reread_is_storage_error(tmp_path):
    usage, posts = _claude_refresh_after(
        tmp_path / ".credentials.json",
        lambda path: path.write_bytes(b"\xff\xfe not utf-8"),
    )
    assert usage.status == ProviderStatus.ERROR
    assert usage.failure_kind == FailureKind.STORAGE
    assert posts == []
