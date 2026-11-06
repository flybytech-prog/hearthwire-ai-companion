"""Grok usage rate limits and unreadable auth files."""

import json
from datetime import timedelta

import pytest

from hearthwire.core.model import FailureKind, ProviderStatus
from hearthwire.providers.grok import SETTINGS_URL, USAGE_URL, GrokProvider

from test_additional_providers import (
    GROK_EXPIRED,
    GROK_FRESH,
    NOW,
    _grok_store,
    _write_grok_file,
    response,
)


def _no_network(*args, **kwargs):
    raise AssertionError("no request may be sent")


def _provider(path, monkeypatch, getter=_no_network, poster=_no_network, store=None):
    return GrokProvider(
        auth_store=store or _grok_store(path, monkeypatch),
        getter=getter,
        form_poster=poster,
        now=lambda: NOW,
    )


def test_usage_429_is_rate_limited_with_retry_after(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    _write_grok_file(path, "old-access", "old-refresh", GROK_FRESH)
    urls = []

    def getter(url, headers, timeout=15.0):
        urls.append(url)
        return response({}, status=429, headers={"Retry-After": "120"})

    usage = _provider(path, monkeypatch, getter=getter).fetch()
    assert usage.status == ProviderStatus.RATE_LIMITED
    assert usage.failure_kind == FailureKind.RATE_LIMITED
    assert usage.error_message == "Grok is rate limited. Try again later."
    assert usage.retry_at == NOW + timedelta(seconds=120)
    assert urls == [USAGE_URL]
    assert SETTINGS_URL not in urls


def test_usage_429_without_retry_after_defaults_to_five_minutes():
    usage = GrokProvider.map(response({}, status=429), None, NOW)
    assert usage.status == ProviderStatus.RATE_LIMITED
    assert usage.retry_at == NOW + timedelta(minutes=5)


@pytest.mark.parametrize("contents", [None, "", "  \n", "[]", '{"other": {"no": "key"}}'])
def test_missing_or_empty_auth_file_is_signed_out(tmp_path, monkeypatch, contents):
    path = tmp_path / "auth.json"
    if contents is not None:
        path.write_text(contents, encoding="utf-8")
    usage = _provider(path, monkeypatch).fetch()
    assert usage.status == ProviderStatus.UNAUTHENTICATED
    assert usage.failure_kind == FailureKind.AUTHENTICATION


@pytest.mark.parametrize("write", [
    lambda path: path.write_bytes(b'{"user::id": {"key": "\xff\xfe-not-utf8"}}'),
    lambda path: path.write_text('{"user::id": {"key": "secret-access"', encoding="utf-8"),
    lambda path: path.mkdir(),
])
def test_unreadable_auth_file_is_storage(tmp_path, monkeypatch, write):
    path = tmp_path / "auth.json"
    write(path)
    provider = _provider(path, monkeypatch)
    usage = provider.fetch()
    assert usage.status == ProviderStatus.ERROR
    assert usage.failure_kind == FailureKind.STORAGE
    assert usage.error_message == "Grok sign-in data could not be read."
    assert "secret" not in usage.error_message
    assert provider.is_configured()


def test_auth_file_corrupted_before_refresh_is_storage_without_posting(
    tmp_path, monkeypatch,
):
    path = tmp_path / "auth.json"
    _write_grok_file(path, "old-access", "old-refresh", GROK_EXPIRED)
    store = _grok_store(path, monkeypatch)
    original_load = store.load_candidates

    def load_then_corrupt():
        loaded = original_load()
        path.write_bytes(b"\xff\xfe")
        return loaded

    monkeypatch.setattr(store, "load_candidates", load_then_corrupt)
    usage = _provider(path, monkeypatch, store=store).fetch()
    assert usage.failure_kind == FailureKind.STORAGE


def test_auth_file_deleted_before_refresh_is_signed_out(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    _write_grok_file(path, "old-access", "old-refresh", GROK_EXPIRED)
    store = _grok_store(path, monkeypatch)
    original_load = store.load_candidates

    def load_then_delete():
        loaded = original_load()
        path.unlink()
        return loaded

    monkeypatch.setattr(store, "load_candidates", load_then_delete)
    usage = _provider(path, monkeypatch, store=store).fetch()
    assert usage.status == ProviderStatus.UNAUTHENTICATED


def test_auth_file_corrupted_before_retry_after_rejection_is_storage(
    tmp_path, monkeypatch,
):
    path = tmp_path / "auth.json"
    _write_grok_file(path, "old-access", "old-refresh", GROK_FRESH)

    def getter(url, headers, timeout=15.0):
        path.write_text("{not json", encoding="utf-8")
        return response({}, status=401)

    usage = _provider(path, monkeypatch, getter=getter).fetch()
    assert usage.failure_kind == FailureKind.STORAGE
    assert json.dumps(usage.error_message).count("not json") == 0


def test_grok_identifies_as_hearthwire(tmp_path, monkeypatch):
    from hearthwire import __version__

    path = tmp_path / "auth.json"
    _write_grok_file(path, "old-access", "old-refresh", GROK_FRESH)
    agents = []

    def getter(url, headers, timeout=15.0):
        agents.append(headers["User-Agent"])
        return response({}, status=429, headers={"Retry-After": "120"})

    _provider(path, monkeypatch, getter=getter).fetch()
    assert agents == [f"Hearthwire/{__version__}"]
