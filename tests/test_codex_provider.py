import base64
import fcntl
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from conftest import fixture
from hearthwire.core.auth import CodexAuthStore, SecretToolStore
from hearthwire.core.environment import LoginShellEnvironment
from hearthwire.core.http import HttpResponse
from hearthwire.core.locking import credential_lock, lock_directory
from hearthwire.core.model import FailureKind, ProviderStatus
from hearthwire.providers.codex import (
    CLIENT_ID,
    REFRESH_URL,
    USAGE_URL,
    CodexProvider,
)


NOW = datetime(2027, 1, 15, tzinfo=timezone.utc)


def _jwt(expiration):
    def segment(value):
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{segment({'alg': 'none'})}.{segment({'exp': expiration})}."


def _store():
    return CodexAuthStore(
        LoginShellEnvironment(environ={"PATH": "/usr/bin"}),
        secret_store=SecretToolStore(executable=""),
        now=lambda: NOW,
    )


def _credentials(path=None):
    store = _store()
    credentials = store.load_file(path or fixture("codex_auth.json"))
    credentials.last_refresh = None
    return credentials, store


def _response(status=200, body=None, headers=None):
    value = (
        json.loads(fixture("codex_usage.json").read_text())
        if body is None
        else body
    )
    return HttpResponse(
        status=status,
        body=json.dumps(value).encode(),
        headers={key.lower(): item for key, item in (headers or {}).items()},
    )


def test_codex_fetch_maps_windows_plan_and_flex_balance():
    credentials, store = _credentials()
    usage = CodexProvider(
        creds=credentials,
        auth_store=store,
        getter=lambda *args, **kwargs: _response(),
        now=lambda: NOW,
    ).fetch()

    assert usage.status == ProviderStatus.OK
    assert usage.plan == "Pro 20x"
    assert {window.kind: window.used_percent for window in usage.windows} == {
        "session": 67,
        "weekly": 31,
        "spark": 101.4,
        "spark_weekly": 22,
    }
    assert usage.billing_usage.kind == "flex_credit_balance"
    assert usage.billing_usage.remaining_credits == 820
    assert usage.billing_usage.usd_value == 32.8


def test_codex_sets_account_header():
    credentials, store = _credentials()
    captured = {}

    def getter(url, headers, timeout=15.0):
        captured["url"] = url
        captured["headers"] = headers
        return _response()

    CodexProvider(
        creds=credentials,
        auth_store=store,
        getter=getter,
        now=lambda: NOW,
    ).fetch()
    assert captured["url"] == USAGE_URL
    assert captured["headers"]["Authorization"] == "Bearer cx-acc-1"
    assert captured["headers"]["ChatGPT-Account-Id"] == "acct-uuid-1"


def test_codex_falls_back_to_percent_headers():
    credentials, store = _credentials()
    response = _response(
        body={
            "rate_limit": {
                "primary_window": {"limit_window_seconds": 18_000},
                "secondary_window": {"limit_window_seconds": 604_800},
            }
        },
        headers={
            "X-Codex-Primary-Used-Percent": "17.25",
            "x-codex-secondary-used-percent": "68",
        },
    )
    usage = CodexProvider(
        creds=credentials,
        auth_store=store,
        getter=lambda *args, **kwargs: response,
        now=lambda: NOW,
    ).fetch()
    assert [window.used_percent for window in usage.windows] == [17.25, 68]


def test_codex_proactive_refresh_uses_exact_source_and_persists(tmp_path):
    path = tmp_path / "auth.json"
    document = json.loads(fixture("codex_auth.json").read_text())
    document["tokens"]["access_token"] = _jwt(NOW.timestamp() + 60)
    document["tokens"]["refresh_token"] = "refresh +&"
    document["last_refresh"] = None
    path.write_text(json.dumps(document), encoding="utf-8")

    store = _store()
    credentials = store.load_file(path)
    refresh_calls = []
    request_headers = []

    def poster(url, data, headers, timeout=15.0):
        refresh_calls.append((url, data, headers))
        return _response(200, {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "id_token": "new-id",
        })

    def getter(url, headers, timeout=15.0):
        request_headers.append(headers)
        return _response()

    usage = CodexProvider(
        creds=credentials,
        auth_store=store,
        getter=getter,
        form_poster=poster,
        now=lambda: NOW,
    ).fetch()

    assert usage.status == ProviderStatus.OK
    assert refresh_calls[0][0] == REFRESH_URL
    assert ("client_id", CLIENT_ID) in refresh_calls[0][1]
    assert ("refresh_token", "refresh +&") in refresh_calls[0][1]
    assert request_headers[0]["ChatGPT-Account-Id"] == "acct-uuid-1"
    saved = json.loads(path.read_text())
    assert saved["tokens"]["access_token"] == "new-access"
    assert saved["tokens"]["refresh_token"] == "new-refresh"
    assert saved["tokens"]["id_token"] == "new-id"


def test_codex_api_key_only_never_calls_usage(tmp_path):
    path = tmp_path / "auth.json"
    path.write_text('{"OPENAI_API_KEY":"sk-test"}', encoding="utf-8")
    store = _store()
    credentials = store.load_file(path)

    def forbidden(*args, **kwargs):
        raise AssertionError("usage endpoint must not be called")

    usage = CodexProvider(
        creds=credentials,
        auth_store=store,
        getter=forbidden,
        now=lambda: NOW,
    ).fetch()
    assert usage.status == ProviderStatus.UNAUTHENTICATED
    assert usage.error_message == "Usage not available for API key."


def test_codex_known_refresh_failure_is_authentication_error():
    credentials, store = _credentials()
    credentials.access_token = _jwt(NOW.timestamp() + 60)
    usage = CodexProvider(
        creds=credentials,
        auth_store=store,
        form_poster=lambda *args, **kwargs: _response(
            400,
            {"error": {"code": "refresh_token_reused"}},
        ),
        now=lambda: NOW,
    ).fetch()
    assert usage.status == ProviderStatus.UNAUTHENTICATED
    assert "Token conflict" in usage.error_message


def test_codex_429_reports_retry_without_persisting_backend_cooldown():
    credentials, store = _credentials()
    calls = 0

    def getter(*args, **kwargs):
        nonlocal calls
        calls += 1
        return _response(429, {}, {"Retry-After": "60"})

    provider = CodexProvider(
        creds=credentials,
        auth_store=store,
        getter=getter,
        now=lambda: NOW,
    )
    first = provider.fetch()
    second = provider.fetch()
    assert first.status == ProviderStatus.RATE_LIMITED
    assert first.retry_at == NOW + timedelta(seconds=60)
    assert second.status == ProviderStatus.RATE_LIMITED
    assert calls == 2


def test_codex_unconfigured_is_unauthenticated():
    usage = CodexProvider(
        creds=None,
    ).fetch()
    assert usage.status == ProviderStatus.UNAUTHENTICATED


EXPIRING = _jwt(NOW.timestamp() + 60)
FRESH = _jwt(NOW.timestamp() + 3600)
ROTATED = _jwt(NOW.timestamp() + 7200)


def _write_codex_file(path, access, refresh):
    document = json.loads(fixture("codex_auth.json").read_text())
    document["tokens"]["access_token"] = access
    document["tokens"]["refresh_token"] = refresh
    document["last_refresh"] = None
    path.write_text(json.dumps(document), encoding="utf-8")


def _saved_codex_tokens(path):
    tokens = json.loads(path.read_text())["tokens"]
    return tokens["access_token"], tokens["refresh_token"]


def _form_value(data, name):
    return next(value for key, value in data if key == name)


def _bearer_getter(seen):
    def getter(url, headers, timeout=15.0):
        seen.append(headers["Authorization"])
        return _response()

    return getter


def test_codex_concurrent_instances_send_one_refresh(tmp_path):
    path = tmp_path / "auth.json"
    _write_codex_file(path, EXPIRING, "old-refresh")
    posts = []
    entered = threading.Event()
    release = threading.Event()

    def poster(url, data, headers, timeout=15.0):
        posts.append(_form_value(data, "refresh_token"))
        entered.set()
        assert release.wait(5)
        return _response(200, {"access_token": ROTATED, "refresh_token": "new-refresh"})

    seen = []
    results = {}
    providers = {}
    for name in ("first", "second"):
        store = _store()
        providers[name] = CodexProvider(
            creds=store.load_file(path),
            auth_store=store,
            getter=_bearer_getter(seen),
            form_poster=poster,
            now=lambda: NOW,
        )

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
    assert seen == [f"Bearer {ROTATED}", f"Bearer {ROTATED}"]
    assert _saved_codex_tokens(path) == (ROTATED, "new-refresh")


def test_codex_uses_tokens_rotated_before_lock_without_posting(tmp_path):
    path = tmp_path / "auth.json"
    _write_codex_file(path, EXPIRING, "old-refresh")
    store = _store()
    credentials = store.load_file(path)
    _write_codex_file(path, FRESH, "cli-refresh")

    def poster(*args, **kwargs):
        raise AssertionError("refresh must not be sent")

    seen = []
    usage = CodexProvider(
        creds=credentials,
        auth_store=store,
        getter=_bearer_getter(seen),
        form_poster=poster,
        now=lambda: NOW,
    ).fetch()
    assert usage.status == ProviderStatus.OK
    assert seen == [f"Bearer {FRESH}"]


def test_codex_failed_save_is_storage_error_after_one_post(tmp_path):
    path = tmp_path / "auth.json"
    _write_codex_file(path, EXPIRING, "old-refresh")
    store = _store()
    credentials = store.load_file(path)
    posts = []

    def poster(url, data, headers, timeout=15.0):
        posts.append(_form_value(data, "refresh_token"))
        # An external CLI (which does not take our lock) rewrites the file.
        _write_codex_file(path, EXPIRING, "cli-refresh")
        return _response(200, {"access_token": ROTATED, "refresh_token": "new-refresh"})

    def getter(*args, **kwargs):
        raise AssertionError("usage must not be requested")

    usage = CodexProvider(
        creds=credentials,
        auth_store=store,
        getter=getter,
        form_poster=poster,
        now=lambda: NOW,
    ).fetch()
    assert usage.status == ProviderStatus.ERROR
    assert usage.failure_kind == FailureKind.STORAGE
    assert usage.error_message == "Codex credentials could not be updated."
    assert posts == ["old-refresh"]
    assert _saved_codex_tokens(path) == (EXPIRING, "cli-refresh")


def test_codex_lock_timeout_is_transient_without_posting(tmp_path):
    path = tmp_path / "auth.json"
    _write_codex_file(path, EXPIRING, "old-refresh")
    store = _store()
    credentials = store.load_file(path)
    with credential_lock("codex"):
        pass
    holder = os.open(lock_directory() / "codex.lock", os.O_RDWR)
    fcntl.flock(holder, fcntl.LOCK_EX)

    def poster(*args, **kwargs):
        raise AssertionError("refresh must not be sent")

    try:
        usage = CodexProvider(
            creds=credentials,
            auth_store=store,
            form_poster=poster,
            now=lambda: NOW,
            lock_timeout=0.2,
        ).fetch()
    finally:
        os.close(holder)
    assert usage.status == ProviderStatus.ERROR
    assert usage.failure_kind == FailureKind.TRANSIENT
    assert "being refreshed by another process" in usage.error_message


def test_codex_never_sends_the_same_refresh_token_twice(tmp_path):
    path = tmp_path / "auth.json"
    _write_codex_file(path, FRESH, "old-refresh")
    store = _store()
    posts = []

    def poster(url, data, headers, timeout=15.0):
        posts.append(_form_value(data, "refresh_token"))
        return _response(503, {})

    file_credentials = store.load_file(path)
    # The same login reachable twice (e.g. file and keyring copies).
    duplicate = store.load_file(path)
    provider = CodexProvider(
        creds=[file_credentials, duplicate],
        auth_store=store,
        getter=lambda *args, **kwargs: _response(401, {}),
        form_poster=poster,
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


def _refuse_usage(*args, **kwargs):
    raise AssertionError("usage must not be requested")


def _codex_refresh_after(path, mutate):
    _write_codex_file(path, EXPIRING, "old-refresh")
    store = _store()
    credentials = store.load_file(path)
    mutate(path)
    posts = []
    usage = CodexProvider(
        creds=credentials,
        auth_store=store,
        getter=_refuse_usage,
        form_poster=_refuse_post(posts),
        now=lambda: NOW,
    ).fetch()
    return usage, posts


def test_codex_logout_before_refresh_is_not_logged_in(tmp_path):
    usage, posts = _codex_refresh_after(tmp_path / "auth.json", lambda path: path.unlink())
    assert usage.status == ProviderStatus.UNAUTHENTICATED
    assert usage.failure_kind == FailureKind.AUTHENTICATION
    assert usage.error_message == "Not logged in. Run `codex` to authenticate."
    assert posts == []


def test_codex_unreadable_file_at_reread_is_storage_error(tmp_path):
    usage, posts = _codex_refresh_after(
        tmp_path / "auth.json",
        lambda path: path.write_bytes(b"\xff\xfe not utf-8"),
    )
    assert usage.status == ProviderStatus.ERROR
    assert usage.failure_kind == FailureKind.STORAGE
    assert posts == []


def test_codex_switch_to_api_key_before_refresh_sends_nothing(tmp_path):
    usage, posts = _codex_refresh_after(
        tmp_path / "auth.json",
        lambda path: path.write_text('{"OPENAI_API_KEY":"sk-test"}', encoding="utf-8"),
    )
    assert usage.status == ProviderStatus.UNAUTHENTICATED
    assert usage.error_message == "Usage not available for API key."
    assert posts == []


def test_codex_keyring_lookup_failure_at_reread_is_storage_error(tmp_path):
    import subprocess
    from types import SimpleNamespace

    document = json.loads(fixture("codex_auth.json").read_text())
    document["tokens"]["access_token"] = EXPIRING
    lookups = []

    def runner(args, **kwargs):
        lookups.append(args[1])
        if len(lookups) > 1:
            raise subprocess.TimeoutExpired(args, 5)
        return SimpleNamespace(returncode=0, stdout=json.dumps(document), stderr="")

    store = CodexAuthStore(
        LoginShellEnvironment(environ={"PATH": "/usr/bin", "CODEX_HOME": str(tmp_path)}),
        secret_store=SecretToolStore(executable="/usr/bin/secret-tool", runner=runner),
        now=lambda: NOW,
    )
    credentials = store.load_keyring()
    posts = []
    usage = CodexProvider(
        creds=credentials,
        auth_store=store,
        getter=_refuse_usage,
        form_poster=_refuse_post(posts),
        now=lambda: NOW,
    ).fetch()
    assert usage.status == ProviderStatus.ERROR
    assert usage.failure_kind == FailureKind.STORAGE
    assert posts == []


def test_codex_identifies_as_hearthwire():
    from hearthwire import __version__

    credentials, store = _credentials()
    captured = {}

    def getter(url, headers, timeout=15.0):
        captured["headers"] = headers
        return _response()

    CodexProvider(
        creds=credentials,
        auth_store=store,
        getter=getter,
        now=lambda: NOW,
    ).fetch()
    assert captured["headers"]["User-Agent"] == f"Hearthwire/{__version__}"
