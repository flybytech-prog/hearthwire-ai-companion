import base64
import fcntl
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone

import pytest

from hearthwire.core.auth import SecretToolStore
from hearthwire.core.environment import LoginShellEnvironment
from hearthwire.core.http import HttpResponse
from hearthwire.core.locking import credential_lock, lock_directory
from hearthwire.core.model import FailureKind, ProviderStatus
from hearthwire.core.sqlite_store import SQLiteStateStore
from hearthwire.providers.antigravity import (
    AntigravityAuthStore,
    AntigravityCredentials,
    AntigravityOAuthClientStore,
    AntigravityProvider,
)
from hearthwire.providers.copilot import CopilotAuthStore, CopilotProvider
from hearthwire.providers.cursor import (
    ACCESS_KEY,
    MEMBERSHIP_KEY,
    REFRESH_KEY,
    CursorAuthStore,
    CursorProvider,
)
from hearthwire.providers.devin import DevinAuthStore, DevinProvider
from hearthwire.providers.grok import SETTINGS_URL, USAGE_URL, GrokAuthStore, GrokProvider


NOW = datetime(2027, 1, 15, tzinfo=timezone.utc)


def response(body, status=200, headers=None):
    return HttpResponse(
        status=status,
        body=json.dumps(body).encode(),
        headers={key.lower(): value for key, value in (headers or {}).items()},
    )


def environment(values=None):
    return LoginShellEnvironment(
        environ={"PATH": "/usr/bin", **(values or {})},
    )


def create_state_database(path, values):
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)"
        )
        connection.executemany(
            "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
            values.items(),
        )


def test_cursor_sqlite_auth_and_compare_and_swap(tmp_path):
    config = tmp_path / "config"
    path = config / "Cursor/User/globalStorage/state.vscdb"
    create_state_database(path, {
        ACCESS_KEY: "old-access",
        REFRESH_KEY: "refresh-token",
        MEMBERSHIP_KEY: "pro",
    })
    store = CursorAuthStore(
        environment({"XDG_CONFIG_HOME": str(config)}),
        secret_store=SecretToolStore(executable=""),
    )
    credentials = store.load()
    assert credentials.access_token == "old-access"
    assert credentials.refresh_token == "refresh-token"
    assert store.save_access_token(credentials, "new-access")
    assert SQLiteStateStore().read(path, ACCESS_KEY) == "new-access"
    assert not store.save_access_token(credentials, "must-not-overwrite")


def test_cursor_mapper_matches_total_auto_api_and_plan():
    usage = response({
        "enabled": True,
        "billingCycleEnd": "2027-02-01T00:00:00Z",
        "planUsage": {
            "totalSpend": 25,
            "limit": 100,
            "autoPercentUsed": 30,
            "apiPercentUsed": 40,
        },
    })
    plan = response({"planInfo": {"planName": "Pro"}})
    mapped = CursorProvider.map(usage, plan, NOW)
    assert mapped.status == ProviderStatus.OK
    assert mapped.plan == "Pro"
    assert {item.kind: item.used_percent for item in mapped.windows} == {
        "total_usage": 25,
        "auto_usage": 30,
        "api_usage": 40,
    }


def test_antigravity_decodes_go_keyring_and_private_cache(tmp_path):
    payload = json.dumps({
        "tokens": {
            "access_token": "expired-access",
            "refresh_token": "refresh-secret",
            "expires_at": "2020-01-01T00:00:00Z",
        }
    }).encode()
    encoded = "go-keyring-base64:" + base64.b64encode(payload).decode()
    credentials = AntigravityAuthStore.decode(encoded)
    assert credentials.refresh_token == "refresh-secret"

    store = AntigravityAuthStore(
        environment({"XDG_CACHE_HOME": str(tmp_path)}),
        secret_store=SecretToolStore(executable=""),
        now=lambda: NOW,
    )
    assert store.cache("derived-access", 3600, credentials.refresh_token)
    text = store.cache_path().read_text()
    assert "refresh-secret" not in text
    assert os.stat(store.cache_path()).st_mode & 0o777 == 0o600
    assert store.usable_access_token(AntigravityCredentials(
        None, credentials.refresh_token, None
    )) == "derived-access"


def test_antigravity_loads_oauth_client_from_installed_bundle(tmp_path):
    client_id = "123-example" + ".apps.googleusercontent.com"
    client_secret = "fake-" + "oauth-client-secret"
    bundle = tmp_path / "main.js"
    bundle.write_text(
        'module="platform/cloudCode/common/oauthClient.js";'
        f'client="{client_id}",secret="{client_secret}",scopes=[]'
    )

    store = AntigravityOAuthClientStore(paths=(bundle,))
    client = store.load()

    assert client is not None
    assert client.client_id == client_id
    assert client.client_secret == client_secret


def test_antigravity_refresh_uses_installed_oauth_client(tmp_path):
    client_id = "123-example" + ".apps.googleusercontent.com"
    client_secret = "fake-" + "oauth-client-secret"
    bundle = tmp_path / "main.js"
    bundle.write_text(
        'module="platform/cloudCode/common/oauthClient.js";'
        f'client="{client_id}",secret="{client_secret}"'
    )
    calls = []

    def post_form(url, fields, headers):
        calls.append((url, fields, headers))
        return response({"access_token": "fresh-access", "expires_in": 3600})

    auth = AntigravityAuthStore(
        environment({"XDG_CACHE_HOME": str(tmp_path)}),
        secret_store=SecretToolStore(executable=""),
        now=lambda: NOW,
    )
    provider = AntigravityProvider(
        auth_store=auth,
        oauth_client_store=AntigravityOAuthClientStore(paths=(bundle,)),
        form_poster=post_form,
        now=lambda: NOW,
    )

    assert provider._refresh("refresh-token") == "fresh-access"
    assert ("client_id", client_id) in calls[0][1]
    assert ("client_secret", client_secret) in calls[0][1]


def test_antigravity_summary_maps_four_quota_buckets():
    summary = response({
        "response": {
            "groups": [{
                "buckets": [
                    {"bucketId": "gemini-5h", "remainingFraction": 0.7},
                    {"bucketId": "gemini-weekly", "remainingFraction": 0.8},
                    {"bucketId": "3p-5h", "remainingFraction": 0.6},
                    {"bucketId": "3p-weekly", "remainingFraction": 0.5},
                ]
            }]
        }
    })
    mapped = AntigravityProvider._map_summary(summary, "Pro", NOW)
    assert mapped.plan == "Pro"
    assert {item.kind: item.used_percent for item in mapped.windows} == {
        "session": 30,
        "weekly": 20,
        "claude_pool": 40,
        "claude_pool_weekly": 50,
    }


def test_copilot_auth_source_order_and_mapper(tmp_path):
    config = tmp_path / "config"
    path = config / "github-copilot/apps.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "github.com": {"oauth_token": "editor-token"}
    }))
    store = CopilotAuthStore(
        environment({"XDG_CONFIG_HOME": str(config)}),
        SecretToolStore(executable=""),
    )
    assert store.load_token() == "editor-token"

    mapped = CopilotProvider.map(response({
        "copilot_plan": "individual_pro",
        "quota_reset_date": "2027-02-01",
        "quota_snapshots": {
            "premium_interactions": {
                "entitlement": 1000,
                "remaining": 750,
                "percent_remaining": 75,
            },
            "chat": {"unlimited": True, "entitlement": -1},
        },
    }), NOW)
    assert mapped.status == ProviderStatus.OK
    assert mapped.plan == "Individual Pro"
    assert [(item.kind, item.used_percent) for item in mapped.windows] == [
        ("credits", 25)
    ]


def test_devin_toml_and_quota_mapper(tmp_path):
    data = tmp_path / "data"
    path = data / "devin/credentials.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        'windsurf_api_key = "devin-key"\n'
        'api_server_url = "https://example.test/"\n'
    )
    store = DevinAuthStore(environment({"XDG_DATA_HOME": str(data)}))
    credentials = store.load_file()
    assert credentials.api_key == "devin-key"
    assert credentials.server_url == "https://example.test"

    mapped = DevinProvider.map(response({
        "userStatus": {
            "planStatus": {
                "dailyQuotaRemainingPercent": 90,
                "weeklyQuotaRemainingPercent": 55,
                "dailyQuotaResetAtUnix": 1_800_000_000,
                "weeklyQuotaResetAtUnix": 1_800_100_000,
                "planInfo": {"planName": "Teams", "hideDailyQuota": False},
            }
        }
    }), NOW)
    assert mapped.plan == "Teams"
    assert {item.kind: item.used_percent for item in mapped.windows} == {
        "daily": 10,
        "weekly": 45,
    }


def test_copilot_non_utf8_apps_json_falls_back_to_hosts_json(tmp_path):
    config = tmp_path / "config"
    folder = config / "github-copilot"
    folder.mkdir(parents=True)
    (folder / "apps.json").write_bytes(b"\xff\xfe not utf-8")
    (folder / "hosts.json").write_text(json.dumps({
        "github.com": {"oauth_token": "hosts-token"}
    }))
    store = CopilotAuthStore(
        environment({"XDG_CONFIG_HOME": str(config)}),
        SecretToolStore(executable=""),
    )
    assert store.load_token() == "hosts-token"


def test_devin_non_utf8_credentials_toml_is_skipped(tmp_path):
    data = tmp_path / "data"
    path = data / "devin/credentials.toml"
    path.parent.mkdir(parents=True)
    path.write_bytes(b'windsurf_api_key = "\xff\xfe"\n')
    store = DevinAuthStore(environment({
        "XDG_DATA_HOME": str(data),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
    }))
    assert store.load_file() is None
    assert store.load_candidates() == []
    usage = DevinProvider(auth_store=store).fetch()
    assert usage.status == ProviderStatus.UNAUTHENTICATED


def test_grok_source_aware_save_and_weekly_mapper(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    path.write_text(json.dumps({
        "user::client-id": {
            "key": "access",
            "refresh_token": "refresh",
            "expires_at": "2027-02-01T00:00:00Z",
        }
    }))
    store = GrokAuthStore(now=lambda: NOW)
    monkeypatch.setattr(store, "auth_path", lambda: path)
    credentials = store.load_candidates()[0]
    credentials.entry["key"] = "rotated"
    assert store.save(credentials)
    assert os.stat(path).st_mode & 0o777 == 0o600

    stale = store.load_candidates()[0]
    path.write_text('{"concurrent":{"key":"cli-won"}}')
    stale.entry["key"] = "must-not-win"
    assert not store.save(stale)

    mapped = GrokProvider.map(
        response({
            "config": {
                "currentPeriod": {
                    "type": "USAGE_PERIOD_TYPE_WEEKLY",
                    "end": "2027-02-01T00:00:00Z",
                },
                "creditUsagePercent": 36,
            }
        }),
        response({"subscription_tier_display": "SuperGrok"}),
        NOW,
    )
    assert mapped.status == ProviderStatus.OK
    assert mapped.plan == "SuperGrok"
    assert mapped.windows[0].kind == "weekly"
    assert mapped.windows[0].used_percent == 36


@pytest.mark.parametrize("status,kind", [
    (500, FailureKind.TRANSIENT),
    (400, FailureKind.INVALID_RESPONSE),
])
def test_new_provider_http_failures_are_classified(status, kind):
    mapped = CursorProvider.map(response({}, status=status), None, NOW)
    assert mapped.failure_kind == kind


GROK_EXPIRED = "2027-01-14T00:00:00+00:00"
GROK_FRESH = "2027-01-16T00:00:00+00:00"


def _write_grok_file(path, access, refresh, expires_at):
    path.write_text(json.dumps({
        "user::client-id": {
            "key": access,
            "refresh_token": refresh,
            "expires_at": expires_at,
        }
    }), encoding="utf-8")


def _grok_store(path, monkeypatch):
    store = GrokAuthStore(environment(), now=lambda: NOW)
    monkeypatch.setattr(store, "auth_path", lambda: path)
    return store


def _grok_getter(seen):
    def getter(url, headers, timeout=15.0):
        if url == SETTINGS_URL:
            return response({"subscription_tier_display": "SuperGrok"})
        assert url == USAGE_URL
        seen.append(headers["Authorization"])
        return response({
            "config": {
                "currentPeriod": {
                    "type": "USAGE_PERIOD_TYPE_WEEKLY",
                    "end": "2027-02-01T00:00:00Z",
                },
                "creditUsagePercent": 36,
            }
        })

    return getter


def _grok_saved(path):
    entry = json.loads(path.read_text())["user::client-id"]
    return entry["key"], entry["refresh_token"]


def test_grok_reload_returns_same_entry_from_exact_source(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    _write_grok_file(path, "old-access", "old-refresh", GROK_FRESH)
    store = _grok_store(path, monkeypatch)
    credentials = store.load_candidates()[0]
    _write_grok_file(path, "cli-access", "cli-refresh", GROK_FRESH)
    live = store.reload(credentials)
    assert live.entry_key == credentials.entry_key
    assert live.token == "cli-access"
    path.write_text('{"other::id":{"key":"x"}}', encoding="utf-8")
    assert store.reload(credentials) is None


def test_grok_concurrent_instances_send_one_refresh(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    _write_grok_file(path, "old-access", "old-refresh", GROK_EXPIRED)
    posts = []
    entered = threading.Event()
    release = threading.Event()

    def poster(url, data, headers, timeout=15.0):
        posts.append(dict(data)["refresh_token"])
        entered.set()
        assert release.wait(5)
        return response({
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        })

    seen = []
    results = {}
    providers = {
        name: GrokProvider(
            auth_store=_grok_store(path, monkeypatch),
            getter=_grok_getter(seen),
            form_poster=poster,
            now=lambda: NOW,
        )
        for name in ("first", "second")
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
    assert _grok_saved(path) == ("new-access", "new-refresh")


def test_grok_uses_tokens_rotated_before_lock_without_posting(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    _write_grok_file(path, "old-access", "old-refresh", GROK_EXPIRED)
    store = _grok_store(path, monkeypatch)
    original_load = store.load_candidates

    def load_then_rotate():
        loaded = original_load()
        _write_grok_file(path, "cli-access", "cli-refresh", GROK_FRESH)
        return loaded

    monkeypatch.setattr(store, "load_candidates", load_then_rotate)

    def poster(*args, **kwargs):
        raise AssertionError("refresh must not be sent")

    seen = []
    usage = GrokProvider(
        auth_store=store,
        getter=_grok_getter(seen),
        form_poster=poster,
        now=lambda: NOW,
    ).fetch()
    assert usage.status == ProviderStatus.OK
    assert seen == ["Bearer cli-access"]


def test_grok_failed_save_is_storage_error_after_one_post(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    _write_grok_file(path, "old-access", "old-refresh", GROK_EXPIRED)
    posts = []

    def poster(url, data, headers, timeout=15.0):
        posts.append(dict(data)["refresh_token"])
        # An external CLI (which does not take our lock) rewrites the file.
        _write_grok_file(path, "cli-access", "cli-refresh", GROK_EXPIRED)
        return response({
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        })

    def getter(*args, **kwargs):
        raise AssertionError("usage must not be requested")

    usage = GrokProvider(
        auth_store=_grok_store(path, monkeypatch),
        getter=getter,
        form_poster=poster,
        now=lambda: NOW,
    ).fetch()
    assert usage.failure_kind == FailureKind.STORAGE
    assert usage.error_message == "Grok credentials could not be updated."
    assert posts == ["old-refresh"]
    assert _grok_saved(path) == ("cli-access", "cli-refresh")


def test_grok_lock_timeout_is_transient_without_posting(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    _write_grok_file(path, "old-access", "old-refresh", GROK_EXPIRED)
    with credential_lock("grok"):
        pass
    holder = os.open(lock_directory() / "grok.lock", os.O_RDWR)
    fcntl.flock(holder, fcntl.LOCK_EX)

    def poster(*args, **kwargs):
        raise AssertionError("refresh must not be sent")

    try:
        usage = GrokProvider(
            auth_store=_grok_store(path, monkeypatch),
            form_poster=poster,
            now=lambda: NOW,
            lock_timeout=0.2,
        ).fetch()
    finally:
        os.close(holder)
    assert usage.status == ProviderStatus.ERROR
    assert usage.failure_kind == FailureKind.TRANSIENT
    assert "being refreshed by another process" in usage.error_message


def test_grok_never_sends_the_same_refresh_token_twice(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    _write_grok_file(path, "old-access", "old-refresh", GROK_FRESH)
    posts = []

    def poster(url, data, headers, timeout=15.0):
        posts.append(dict(data)["refresh_token"])
        return response({}, status=503)

    provider = GrokProvider(
        auth_store=_grok_store(path, monkeypatch),
        getter=lambda *args, **kwargs: response({}, status=401),
        form_poster=poster,
        now=lambda: NOW,
    )
    first = provider.fetch()
    second = provider.fetch()
    # A refresh outage is not a sign-out; the second fetch reports the same
    # failure without resending the refresh token.
    for usage in (first, second):
        assert usage.status == ProviderStatus.ERROR
        assert usage.failure_kind == FailureKind.TRANSIENT
    assert posts == ["old-refresh"]


def test_antigravity_cache_lives_under_hearthwire(tmp_path):
    environment = LoginShellEnvironment(environ={"XDG_CACHE_HOME": str(tmp_path / "cache")})
    store = AntigravityAuthStore(environment=environment, secret_store=SecretToolStore(executable=""))
    assert store.cache_path() == tmp_path / "cache" / "hearthwire" / "antigravity-auth.json"
