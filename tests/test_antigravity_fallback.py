"""Antigravity summary fallback, Cloud Code rate limits, and refresh outages."""

import os
from datetime import timedelta

import pytest

from hearthwire.core.auth import SecretToolStore
from hearthwire.core.model import FailureKind, ProviderStatus
from hearthwire.providers.antigravity import (
    CLOUD_BASES,
    MODELS_PATH,
    PLAN_PATH,
    REFRESH_URL,
    SUMMARY_PATH,
    AntigravityAuthStore,
    AntigravityCredentials,
    AntigravityOAuthClient,
    AntigravityProvider,
)

from test_additional_providers import NOW, environment, response


DAILY, PROD = CLOUD_BASES

UNKNOWN_BUCKETS = {
    "response": {
        "groups": [{
            "buckets": [
                {"bucketId": "future-bucket", "remainingFraction": 0.4},
            ]
        }]
    }
}

LEGACY_MODELS = {
    "models": {
        "gemini": {
            "displayName": "Gemini 3 Pro",
            "quotaInfo": {"remainingFraction": 0.75},
        },
        "claude": {
            "displayName": "Claude Sonnet",
            "quotaInfo": {"remainingFraction": 0.5},
        },
    }
}


class StubAuthStore:
    def __init__(self, access="stub-access", refresh="stub-refresh"):
        self.environment = environment()
        self.credentials = AntigravityCredentials(access, refresh, None)
        self.cached = []

    def load(self):
        return self.credentials

    def usable_access_token(self, credentials):
        return credentials.access_token

    def cache(self, access_token, expires_in, refresh_token):
        self.cached.append(access_token)
        return True


class StubOAuthClientStore:
    def load(self):
        return AntigravityOAuthClient("stub-client", "stub-client-secret-value")


def _provider(routes, auth=None, form_poster=None):
    """routes maps full URL -> response (or a list consumed in order)."""
    seen = []

    def post_json(url, body, headers, timeout=15.0):
        seen.append(url)
        reply = routes.get(url, response({}, status=404))
        if isinstance(reply, list):
            reply = reply.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def no_refresh(*args, **kwargs):
        raise AssertionError("refresh must not be sent")

    provider = AntigravityProvider(
        auth_store=auth or StubAuthStore(),
        oauth_client_store=StubOAuthClientStore(),
        json_poster=post_json,
        form_poster=form_poster or no_refresh,
        now=lambda: NOW,
    )
    return provider, seen


def test_summary_with_only_unknown_buckets_maps_to_none():
    assert AntigravityProvider._map_summary(response(UNKNOWN_BUCKETS), "Pro", NOW) is None


def test_unknown_summary_buckets_fall_back_to_available_models():
    provider, seen = _provider({
        DAILY + SUMMARY_PATH: response(UNKNOWN_BUCKETS),
        DAILY + PLAN_PATH: response({"paidTier": {"name": "g1-pro-tier"}}),
        DAILY + MODELS_PATH: response(LEGACY_MODELS),
    })
    usage = provider.fetch()
    assert usage.status == ProviderStatus.OK
    assert usage.plan == "Pro"
    assert {item.kind: item.used_percent for item in usage.windows} == {
        "session": 25,
        "claude_pool": 50,
    }
    assert DAILY + MODELS_PATH in seen


def test_summary_429_on_both_hosts_is_rate_limited_without_more_calls():
    provider, seen = _provider({
        DAILY + SUMMARY_PATH: response({}, status=429, headers={"Retry-After": "120"}),
        PROD + SUMMARY_PATH: response({}, status=429, headers={"Retry-After": "300"}),
    })
    usage = provider.fetch()
    assert usage.status == ProviderStatus.RATE_LIMITED
    assert usage.failure_kind == FailureKind.RATE_LIMITED
    assert usage.error_message == "Antigravity is rate limited. Try again later."
    assert usage.retry_at == NOW + timedelta(seconds=120)
    assert seen == [DAILY + SUMMARY_PATH, PROD + SUMMARY_PATH]


@pytest.mark.parametrize("first,second", [
    (response({}, status=429, headers={"Retry-After": "60"}), response({}, status=503)),
    (response({}, status=503), response({}, status=429, headers={"Retry-After": "60"})),
    (OSError("network down"), response({}, status=429, headers={"Retry-After": "60"})),
])
def test_one_host_429_and_the_other_down_is_rate_limited(first, second):
    provider, seen = _provider({
        DAILY + SUMMARY_PATH: first,
        PROD + SUMMARY_PATH: second,
    })
    usage = provider.fetch()
    assert usage.status == ProviderStatus.RATE_LIMITED
    assert usage.retry_at == NOW + timedelta(seconds=60)
    assert all(SUMMARY_PATH in url for url in seen)


def test_429_then_success_on_the_next_host_is_used():
    provider, _ = _provider({
        DAILY + SUMMARY_PATH: response({}, status=429),
        PROD + SUMMARY_PATH: response({
            "response": {"groups": [{"buckets": [
                {"bucketId": "gemini-5h", "remainingFraction": 0.9},
            ]}]}
        }),
    })
    usage = provider.fetch()
    assert usage.status == ProviderStatus.OK
    assert usage.windows[0].used_percent == 10


def test_models_429_after_unusable_summary_is_rate_limited():
    provider, _ = _provider({
        DAILY + SUMMARY_PATH: response(UNKNOWN_BUCKETS),
        DAILY + MODELS_PATH: response({}, status=429, headers={"Retry-After": "30"}),
        PROD + MODELS_PATH: response({}, status=503),
    })
    usage = provider.fetch()
    assert usage.status == ProviderStatus.RATE_LIMITED
    assert usage.retry_at == NOW + timedelta(seconds=30)


def test_summary_and_models_down_everywhere_is_transient():
    down = response({}, status=503)
    provider, _ = _provider({
        DAILY + SUMMARY_PATH: down,
        PROD + SUMMARY_PATH: down,
        DAILY + MODELS_PATH: down,
        PROD + MODELS_PATH: down,
    })
    usage = provider.fetch()
    assert usage.status == ProviderStatus.ERROR
    assert usage.failure_kind == FailureKind.TRANSIENT
    assert usage.error_message == "Antigravity could not be reached."


def _refresh_poster(posts, reply):
    def post_form(url, fields, headers, timeout=15.0):
        assert url == REFRESH_URL
        posts.append(dict(fields)["refresh_token"])
        if isinstance(reply, Exception):
            raise reply
        return reply

    return post_form


@pytest.mark.parametrize("reply,kind", [
    (response({}, status=503), FailureKind.TRANSIENT),
    (OSError("network down"), FailureKind.TRANSIENT),
    (response({}, status=429, headers={"Retry-After": "45"}), FailureKind.RATE_LIMITED),
])
def test_refresh_outage_is_not_a_sign_out(reply, kind):
    auth = StubAuthStore(access=None)
    posts = []
    provider, seen = _provider({}, auth=auth, form_poster=_refresh_poster(posts, reply))
    usage = provider.fetch()
    assert usage.failure_kind == kind
    if kind == FailureKind.RATE_LIMITED:
        assert usage.status == ProviderStatus.RATE_LIMITED
        assert usage.retry_at == NOW + timedelta(seconds=45)
    else:
        assert usage.error_message == "Antigravity could not refresh its session."
    assert posts == ["stub-refresh"]
    assert seen == []
    assert auth.cached == []


def test_refused_refresh_grant_is_signed_out():
    auth = StubAuthStore(access=None)
    provider, _ = _provider(
        {},
        auth=auth,
        form_poster=_refresh_poster([], response({"error": "invalid_grant"}, status=400)),
    )
    usage = provider.fetch()
    assert usage.status == ProviderStatus.UNAUTHENTICATED
    assert auth.cached == []


def test_rejected_token_then_refresh_outage_is_transient():
    posts = []
    provider, _ = _provider(
        {DAILY + SUMMARY_PATH: response({}, status=401)},
        form_poster=_refresh_poster(posts, response({}, status=502)),
    )
    usage = provider.fetch()
    assert usage.failure_kind == FailureKind.TRANSIENT
    assert posts == ["stub-refresh"]


def test_fresh_token_rejected_again_does_not_resend_refresh():
    auth = StubAuthStore(access=None)
    posts = []
    provider, seen = _provider(
        {DAILY + SUMMARY_PATH: response({}, status=401)},
        auth=auth,
        form_poster=_refresh_poster(
            posts, response({"access_token": "derived-access", "expires_in": 3600}),
        ),
    )
    usage = provider.fetch()
    assert usage.status == ProviderStatus.UNAUTHENTICATED
    assert posts == ["stub-refresh"]
    assert seen == [DAILY + SUMMARY_PATH]


def test_refresh_outage_leaves_derived_cache_alone_and_success_writes_0600(tmp_path):
    store = AntigravityAuthStore(
        environment({"XDG_CACHE_HOME": str(tmp_path)}),
        secret_store=SecretToolStore(executable=""),
        now=lambda: NOW,
    )
    store.load = lambda: AntigravityCredentials(None, "stub-refresh", None)
    provider = AntigravityProvider(
        auth_store=store,
        oauth_client_store=StubOAuthClientStore(),
        json_poster=lambda *args, **kwargs: response({}, status=503),
        form_poster=_refresh_poster([], response({}, status=503)),
        now=lambda: NOW,
    )
    assert provider.fetch().failure_kind == FailureKind.TRANSIENT
    assert not store.cache_path().exists()

    provider = AntigravityProvider(
        auth_store=store,
        oauth_client_store=StubOAuthClientStore(),
        json_poster=lambda *args, **kwargs: response({}, status=503),
        form_poster=_refresh_poster(
            [], response({"access_token": "derived-access", "expires_in": 3600}),
        ),
        now=lambda: NOW,
    )
    assert provider.fetch().failure_kind == FailureKind.TRANSIENT
    text = store.cache_path().read_text()
    assert "stub-refresh" not in text
    assert os.stat(store.cache_path()).st_mode & 0o777 == 0o600
