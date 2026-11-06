from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable, Optional

from ..core.auth import (
    CLAUDE_CLIENT_ID,
    CLAUDE_REFRESH_SCOPES,
    CLAUDE_REFRESH_URL,
    ClaudeAuthStore,
    ClaudeCredentials,
    signed_out_file,
)
from ..core.http import HttpResponse, http_get, http_post_json
from ..core.locking import CredentialLockTimeout, credential_lock
from ..core.model import BillingUsage, FailureKind, ProviderStatus, ProviderUsage, UsageWindow
from ..core.parsing import (
    cents_to_dollars,
    non_empty,
    number,
    provider_datetime,
    retry_datetime,
    title_case_identifier,
)
from .base import errored, rate_limited, unauthenticated


USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_CODE_VERSION = "2.1.69"
ICON = "provider-claude.svg"
DISPLAY = "Claude Code"
PROVIDER_ID = "claude"


def _plan_label(credentials: ClaudeCredentials) -> Optional[str]:
    raw = non_empty(credentials.subscription_type)
    if raw is None:
        return None
    base = title_case_identifier(raw)
    match = re.search(r"\d+x", credentials.rate_limit_tier)
    return f"{base} {match.group(0)}" if match else base


class ClaudeProvider:
    id = PROVIDER_ID
    display_name = DISPLAY

    def __init__(
        self,
        creds: Optional[ClaudeCredentials] = None,
        getter: Callable[..., HttpResponse] = http_get,
        json_poster: Callable[..., HttpResponse] = http_post_json,
        auth_store: Optional[ClaudeAuthStore] = None,
        now: Optional[Callable[[], datetime]] = None,
        lock_timeout: float = 30.0,
    ):
        self._creds = creds
        self._get = getter
        self._post_json = json_poster
        self._auth_store = auth_store or ClaudeAuthStore()
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._lock_timeout = lock_timeout
        # Refresh tokens this instance already sent; kept in memory only.
        self._sent_refresh_tokens: set[str] = set()

    def is_configured(self) -> bool:
        return self._creds is not None

    def fetch(self) -> ProviderUsage:
        if self._creds is None:
            return self._not_logged_in()
        return self._fetch(self._creds)

    def _fetch(self, credentials: ClaudeCredentials) -> ProviderUsage:
        if not self._auth_store.has_usage_scope(credentials):
            return unauthenticated(
                PROVIDER_ID,
                DISPLAY,
                ICON,
                "Re-login for live usage. Run `claude` and sign in again.",
            )

        now = self._utc_now()

        if credentials.is_expired(now_ms=int(now.timestamp() * 1000)):
            credentials, failure = self._refresh(credentials, rejected=False)
            if failure is not None:
                return failure
            assert credentials is not None
            self._creds = credentials

        response, failure = self._send_usage(credentials.access_token)
        if failure is not None:
            return failure
        assert response is not None

        if response.status in (401, 403):
            if not credentials.refresh_token:
                return unauthenticated(
                    PROVIDER_ID,
                    DISPLAY,
                    ICON,
                    "Token expired. Run `claude` to log in again.",
                )
            credentials, failure = self._refresh(credentials, rejected=True)
            if failure is not None:
                return failure
            assert credentials is not None
            self._creds = credentials
            response, failure = self._send_usage(credentials.access_token)
            if failure is not None:
                return failure
            assert response is not None
            if response.status in (401, 403):
                return unauthenticated(
                    PROVIDER_ID,
                    DISPLAY,
                    ICON,
                    "Token expired. Run `claude` to log in again.",
                )

        if response.status == 429:
            retry_at = retry_datetime(response.header("retry-after"), self._utc_now())
            return rate_limited(
                PROVIDER_ID,
                DISPLAY,
                ICON,
                "Claude is rate limited. Try again later.",
                retry_at,
            )
        if not 200 <= response.status < 300:
            return errored(
                PROVIDER_ID,
                DISPLAY,
                ICON,
                f"Claude usage request failed ({response.status}).",
                (
                    FailureKind.TRANSIENT
                    if response.status >= 500
                    else FailureKind.INVALID_RESPONSE
                ),
            )
        try:
            data = response.json()
        except (ValueError, UnicodeDecodeError):
            return errored(
                PROVIDER_ID, DISPLAY, ICON,
                "Claude returned unreadable usage data.",
                FailureKind.INVALID_RESPONSE,
            )
        if not isinstance(data, dict):
            return errored(
                PROVIDER_ID, DISPLAY, ICON,
                "Claude returned unreadable usage data.",
                FailureKind.INVALID_RESPONSE,
            )

        self._creds = credentials
        return self._map(data, credentials)

    def _refresh(
        self,
        credentials: ClaudeCredentials,
        *,
        rejected: bool,
    ) -> tuple[Optional[ClaudeCredentials], Optional[ProviderUsage]]:
        try:
            with credential_lock(PROVIDER_ID, timeout=self._lock_timeout):
                return self._refresh_locked(credentials, rejected=rejected)
        except CredentialLockTimeout:
            return None, errored(
                PROVIDER_ID,
                DISPLAY,
                ICON,
                f"{DISPLAY} is being refreshed by another process. Try again shortly.",
                FailureKind.TRANSIENT,
            )

    def _refresh_locked(
        self,
        credentials: ClaudeCredentials,
        *,
        rejected: bool,
    ) -> tuple[Optional[ClaudeCredentials], Optional[ProviderUsage]]:
        # Another process may have rotated the tokens while we waited.
        if credentials.source is not None:
            live = self._auth_store.reload(credentials)
            if live is None:
                # Logged out elsewhere, or unreadable; either way a rotated
                # token could not be stored, so keep the refresh token unspent.
                if signed_out_file(credentials.source.path):
                    return None, self._not_logged_in()
                return None, self._storage_failure()
            if (
                live.access_token != credentials.access_token
                or live.refresh_token != credentials.refresh_token
            ):
                now_ms = int(self._utc_now().timestamp() * 1000)
                if not rejected and not live.is_expired(now_ms=now_ms):
                    return live, None
                if rejected and live.access_token != credentials.access_token:
                    return live, None
            credentials = live

        refresh_token = non_empty(credentials.refresh_token)
        if refresh_token is None or refresh_token in self._sent_refresh_tokens:
            return None, unauthenticated(
                PROVIDER_ID,
                DISPLAY,
                ICON,
                "Session expired. Run `claude` to log in again.",
            )
        self._sent_refresh_tokens.add(refresh_token)
        try:
            response = self._post_json(
                CLAUDE_REFRESH_URL,
                {
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": CLAUDE_CLIENT_ID,
                    "scope": CLAUDE_REFRESH_SCOPES,
                },
                {"Accept": "application/json"},
            )
        except Exception:
            return None, errored(PROVIDER_ID, DISPLAY, ICON, "Claude could not be reached.")

        if response.status in (400, 401):
            code = None
            try:
                body = response.json()
                if isinstance(body, dict):
                    code = non_empty(body.get("error")) or non_empty(body.get("error_description"))
            except (ValueError, UnicodeDecodeError):
                pass
            if code == "invalid_grant":
                return None, unauthenticated(
                    PROVIDER_ID,
                    DISPLAY,
                    ICON,
                    "Session expired. Run `claude` to log in again.",
                )
            return None, errored(
                PROVIDER_ID,
                DISPLAY,
                ICON,
                f"Claude token refresh failed ({response.status}).",
            )
        if not 200 <= response.status < 300:
            return None, errored(
                PROVIDER_ID,
                DISPLAY,
                ICON,
                f"Claude token refresh failed ({response.status}).",
            )
        try:
            body = response.json()
        except (ValueError, UnicodeDecodeError):
            body = None
        access_token = non_empty(body.get("access_token")) if isinstance(body, dict) else None
        if access_token is None:
            return None, errored(
                PROVIDER_ID, DISPLAY, ICON, "Claude returned an invalid refreshed token.",
            )
        expires_in = number(body.get("expires_in")) if isinstance(body, dict) else None
        updated = replace(
            credentials,
            access_token=access_token,
            refresh_token=(
                non_empty(body.get("refresh_token"))
                if isinstance(body, dict)
                else None
            ) or credentials.refresh_token,
            expires_at_ms=(
                self._utc_now().timestamp() * 1000 + expires_in * 1000
                if expires_in is not None
                else credentials.expires_at_ms
            ),
        )
        if credentials.source is not None and not self._auth_store.save(updated):
            # The refresh token is spent; never reload and POST again.
            return None, self._storage_failure()
        return updated, None

    @staticmethod
    def _not_logged_in() -> ProviderUsage:
        return unauthenticated(
            PROVIDER_ID,
            DISPLAY,
            ICON,
            "Not logged in. Run `claude` to authenticate.",
        )

    @staticmethod
    def _storage_failure() -> ProviderUsage:
        return errored(
            PROVIDER_ID,
            DISPLAY,
            ICON,
            f"{DISPLAY} credentials could not be updated.",
            FailureKind.STORAGE,
        )

    def _send_usage(
        self,
        access_token: str,
    ) -> tuple[Optional[HttpResponse], Optional[ProviderUsage]]:
        headers = {
            "Authorization": f"Bearer {access_token.strip()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": f"claude-code/{CLAUDE_CODE_VERSION}",
        }
        try:
            return self._get(USAGE_URL, headers=headers), None
        except Exception:
            return None, errored(PROVIDER_ID, DISPLAY, ICON, "Claude could not be reached.")

    def _map(
        self,
        data: dict,
        credentials: ClaudeCredentials,
    ) -> ProviderUsage:
        windows: list[UsageWindow] = []

        def add(value, kind: str, caption: str) -> None:
            if not isinstance(value, dict):
                return
            used = number(value.get("utilization"))
            if used is None:
                return
            windows.append(UsageWindow(
                caption=caption,
                kind=kind,
                used_percent=used,
                resets_at=provider_datetime(value.get("resets_at")),
            ))

        add(data.get("five_hour"), "session", "Session · 5h")
        add(data.get("seven_day"), "weekly", "Weekly · 7d")
        add(data.get("seven_day_sonnet"), "sonnet", "Sonnet")

        limits = data.get("limits")
        if isinstance(limits, list):
            for raw_limit in limits:
                if not isinstance(raw_limit, dict) or raw_limit.get("kind") != "weekly_scoped":
                    continue
                scope = raw_limit.get("scope")
                model = scope.get("model") if isinstance(scope, dict) else None
                if not isinstance(model, dict) or model.get("display_name") != "Fable":
                    continue
                used = number(raw_limit.get("percent"))
                if used is not None:
                    windows.append(UsageWindow(
                        caption="Fable",
                        kind="fable",
                        used_percent=used,
                        resets_at=provider_datetime(raw_limit.get("resets_at")),
                    ))
                break

        billing_usage = None
        extra = data.get("extra_usage")
        if isinstance(extra, dict) and extra.get("is_enabled") is True:
            used_cents = number(extra.get("used_credits"))
            if used_cents is not None:
                used_amount = cents_to_dollars(used_cents)
                limit_cents = number(extra.get("monthly_limit"))
                if limit_cents is not None and limit_cents > 0:
                    billing_usage = BillingUsage.bounded_spend(
                        used_amount,
                        cents_to_dollars(limit_cents),
                    )
                elif used_amount > 0:
                    billing_usage = BillingUsage.unbounded_spend(used_amount)

        return ProviderUsage(
            provider_id=PROVIDER_ID,
            display_name=DISPLAY,
            icon=ICON,
            plan=_plan_label(credentials),
            status=ProviderStatus.OK,
            error_message=None,
            windows=windows,
            billing_usage=billing_usage,
            last_updated=self._utc_now(),
            retry_at=None,
        )

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
