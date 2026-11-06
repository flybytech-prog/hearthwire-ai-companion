from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from .. import __version__
from ..core.environment import LoginShellEnvironment
from ..core.http import HttpResponse, http_get, http_post_form
from ..core.locking import CredentialLockTimeout, credential_lock
from ..core.model import FailureKind, ProviderStatus, ProviderUsage, UsageWindow
from ..core.parsing import jwt_expiration, non_empty, number, provider_datetime, retry_datetime
from ..core.storage import atomic_write_private
from .base import errored, rate_limited, unauthenticated


PROVIDER_ID = "grok"
DISPLAY = "Grok"
ICON = "provider-grok.svg"
USAGE_URL = "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
SETTINGS_URL = "https://cli-chat-proxy.grok.com/v1/settings"
REFRESH_URL = "https://auth.x.ai/oauth2/token"
DEFAULT_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
WEEKLY_PERIOD = "USAGE_PERIOD_TYPE_WEEKLY"


class RefreshOutcome(Enum):
    REFRESHED = "refreshed"
    NOT_REFRESHED = "not_refreshed"
    # The file was deleted or emptied, or the account entry is gone.
    SOURCE_GONE = "source_gone"


class GrokCredentialsUnreadable(Exception):
    """The auth file exists but cannot be read or decoded.

    Carries no message on purpose: the cause may quote file contents.
    """


@dataclass
class GrokCredentials:
    document: dict
    entry_key: str
    entry: dict
    token: str
    path: Path
    raw_text: str


class GrokAuthStore:
    def __init__(
        self,
        environment: Optional[LoginShellEnvironment] = None,
        now: Optional[Callable[[], datetime]] = None,
    ):
        self.environment = environment or LoginShellEnvironment()
        self._now = now or (lambda: datetime.now(timezone.utc))

    def auth_path(self) -> Path:
        return Path.home() / ".grok" / "auth.json"

    def load_candidates(self) -> list[GrokCredentials]:
        """Usable account entries; empty when signed out.

        Raises GrokCredentialsUnreadable when the file exists but cannot be
        read or decoded.
        """
        return self._load_path(self.auth_path())

    def reload(self, credentials: GrokCredentials) -> Optional[GrokCredentials]:
        """Re-read the exact source file and return the same account entry.

        Returns None when the entry is gone; raises GrokCredentialsUnreadable
        when the file cannot be read or decoded.
        """
        for candidate in self._load_path(credentials.path):
            if candidate.entry_key == credentials.entry_key:
                return candidate
        return None

    @staticmethod
    def _load_path(path: Path) -> list[GrokCredentials]:
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except (OSError, UnicodeDecodeError):
            raise GrokCredentialsUnreadable() from None
        if not raw.strip():
            # An emptied file is a logout, not damage.
            return []
        try:
            root = json.loads(raw)
        except json.JSONDecodeError:
            raise GrokCredentialsUnreadable() from None
        if not isinstance(root, dict):
            return []
        candidates = []
        for entry_key, entry in root.items():
            token = non_empty(entry.get("key")) if isinstance(entry, dict) else None
            if token:
                candidates.append(GrokCredentials(
                    root,
                    entry_key,
                    copy.deepcopy(entry),
                    token,
                    path,
                    raw,
                ))
        return candidates

    def save(self, credentials: GrokCredentials) -> bool:
        document = copy.deepcopy(credentials.document)
        document[credentials.entry_key] = credentials.entry
        serialized = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False)
        saved = atomic_write_private(
            credentials.path,
            serialized,
            expected_text=credentials.raw_text,
        )
        if saved:
            credentials.document = document
            credentials.raw_text = serialized
        return saved

    def expiration(self, credentials: GrokCredentials) -> Optional[datetime]:
        return (
            jwt_expiration(credentials.token)
            or provider_datetime(credentials.entry.get("expires_at"))
            or provider_datetime(credentials.entry.get("expires"))
        )

    def needs_refresh(self, credentials: GrokCredentials) -> bool:
        expiration = self.expiration(credentials)
        return expiration is not None and (
            expiration - self._utc_now()
        ).total_seconds() <= 300

    def is_expired(self, credentials: GrokCredentials) -> bool:
        expiration = self.expiration(credentials)
        return expiration is not None and self._utc_now() >= expiration

    @staticmethod
    def refresh_token(credentials: GrokCredentials) -> Optional[str]:
        return (
            non_empty(credentials.entry.get("refresh_token"))
            or non_empty(credentials.entry.get("refresh"))
        )

    @staticmethod
    def client_id(credentials: GrokCredentials) -> str:
        explicit = non_empty(credentials.entry.get("oidc_client_id"))
        if explicit:
            return explicit
        suffix = credentials.entry_key.split("::")[-1].strip()
        return suffix or DEFAULT_CLIENT_ID

    def _utc_now(self) -> datetime:
        value = self._now()
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )


class GrokProvider:
    id = PROVIDER_ID
    display_name = DISPLAY

    def __init__(
        self,
        auth_store: Optional[GrokAuthStore] = None,
        getter: Callable[..., HttpResponse] = http_get,
        form_poster: Callable[..., HttpResponse] = http_post_form,
        now: Optional[Callable[[], datetime]] = None,
        lock_timeout: float = 30.0,
    ):
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._auth = auth_store or GrokAuthStore(now=self._now)
        self._get = getter
        self._post_form = form_poster
        self._lock_timeout = lock_timeout
        # Refresh tokens this instance already sent, mapped to the transient,
        # rate-limit, or storage failure that send produced (None otherwise).
        # Memory only; a refresh token is never sent twice.
        self._sent_refresh_tokens: dict[str, Optional[ProviderUsage]] = {}

    def is_configured(self) -> bool:
        try:
            return bool(self._auth.load_candidates())
        except GrokCredentialsUnreadable:
            return True

    def fetch(self) -> ProviderUsage:
        try:
            candidates = self._auth.load_candidates()
        except GrokCredentialsUnreadable:
            return self._storage_failure()
        if not candidates:
            return unauthenticated(
                PROVIDER_ID, DISPLAY, ICON,
                "Not logged in. Run `grok login`.",
            )
        saw_expired = False
        for credentials in candidates:
            if self._auth.needs_refresh(credentials):
                outcome, failure = self._refresh(credentials, rejected=False)
                if outcome is RefreshOutcome.SOURCE_GONE:
                    saw_expired = True
                    continue
                if outcome is not RefreshOutcome.REFRESHED:
                    if failure is not None and failure.failure_kind == FailureKind.STORAGE:
                        return failure
                    if self._auth.is_expired(credentials):
                        if failure is not None:
                            return failure
                        saw_expired = True
                        continue
                    # The access token is still valid: an early refresh that
                    # failed (or is blocked by another process) is not fatal.
            response = self._request(USAGE_URL, credentials.token)
            if response is None:
                continue
            if response.status in (401, 403):
                outcome, failure = self._refresh(credentials, rejected=True)
                if outcome is not RefreshOutcome.REFRESHED:
                    if failure is not None:
                        return failure
                    saw_expired = True
                    continue
                response = self._request(USAGE_URL, credentials.token)
                if response is None:
                    continue
            if response.status in (401, 403):
                saw_expired = True
                continue
            if not 200 <= response.status < 300:
                # Includes 429: don't spend another request on a throttled API.
                return self.map(response, None, self._utc_now())
            plan_response = self._request(SETTINGS_URL, credentials.token)
            return self.map(response, plan_response, self._utc_now())
        if saw_expired:
            return unauthenticated(
                PROVIDER_ID, DISPLAY, ICON,
                "Grok session expired. Run `grok login`.",
            )
        return errored(
            PROVIDER_ID, DISPLAY, ICON,
            "Grok could not be reached.",
            FailureKind.TRANSIENT,
        )

    def _request(self, url: str, token: str) -> Optional[HttpResponse]:
        try:
            return self._get(url, {
                "Authorization": f"Bearer {token}",
                "X-XAI-Token-Auth": "xai-grok-cli",
                "Accept": "application/json",
                "User-Agent": f"Hearthwire/{__version__}",
            })
        except Exception:
            return None

    def _refresh(
        self,
        credentials: GrokCredentials,
        *,
        rejected: bool,
    ) -> tuple[RefreshOutcome, Optional[ProviderUsage]]:
        try:
            with credential_lock(PROVIDER_ID, timeout=self._lock_timeout):
                return self._refresh_locked(credentials, rejected=rejected)
        except CredentialLockTimeout:
            return RefreshOutcome.NOT_REFRESHED, errored(
                PROVIDER_ID, DISPLAY, ICON,
                f"{DISPLAY} is being refreshed by another process. Try again shortly.",
                FailureKind.TRANSIENT,
            )

    def _refresh_locked(
        self,
        credentials: GrokCredentials,
        *,
        rejected: bool,
    ) -> tuple[RefreshOutcome, Optional[ProviderUsage]]:
        # Another process may have rotated the tokens while we waited.
        try:
            live = self._auth.reload(credentials)
        except GrokCredentialsUnreadable:
            # Nothing could be written back safely, so keep the token unspent.
            return RefreshOutcome.NOT_REFRESHED, self._storage_failure()
        if live is None:
            return RefreshOutcome.SOURCE_GONE, None
        token_changed = live.token != credentials.token
        changed = token_changed or (
            self._auth.refresh_token(live) != self._auth.refresh_token(credentials)
        )
        self._adopt(credentials, live)
        if changed:
            if not rejected and not self._auth.needs_refresh(credentials):
                return RefreshOutcome.REFRESHED, None
            if rejected and token_changed:
                return RefreshOutcome.REFRESHED, None

        refresh_token = self._auth.refresh_token(credentials)
        if refresh_token is None:
            return RefreshOutcome.NOT_REFRESHED, None
        if refresh_token in self._sent_refresh_tokens:
            return RefreshOutcome.NOT_REFRESHED, self._sent_refresh_tokens[refresh_token]
        self._sent_refresh_tokens[refresh_token] = None
        response = self._post_refresh(credentials, refresh_token)
        if isinstance(response, ProviderUsage):
            self._sent_refresh_tokens[refresh_token] = response
            return RefreshOutcome.NOT_REFRESHED, response
        if response is None:
            return RefreshOutcome.NOT_REFRESHED, None
        try:
            body = response.json()
        except (ValueError, UnicodeDecodeError):
            body = None
        access_token = non_empty(body.get("access_token")) if isinstance(body, dict) else None
        if access_token is None:
            return RefreshOutcome.NOT_REFRESHED, None
        credentials.token = access_token
        credentials.entry["key"] = access_token
        if token := non_empty(body.get("refresh_token")):
            credentials.entry["refresh_token"] = token
        if token := non_empty(body.get("id_token")):
            credentials.entry["id_token"] = token
        expires_in = number(body.get("expires_in"))
        expiration = (
            self._utc_now() + timedelta(seconds=expires_in)
            if expires_in is not None
            else jwt_expiration(access_token)
        )
        if expiration:
            credentials.entry["expires_at"] = expiration.isoformat()
        if not self._auth.save(credentials):
            # The old refresh token is spent; report the same failure again
            # instead of treating a later attempt as a sign-out.
            failure = errored(
                PROVIDER_ID, DISPLAY, ICON,
                "Grok credentials could not be updated.",
                FailureKind.STORAGE,
            )
            self._sent_refresh_tokens[refresh_token] = failure
            return RefreshOutcome.NOT_REFRESHED, failure
        return RefreshOutcome.REFRESHED, None

    def _post_refresh(
        self,
        credentials: GrokCredentials,
        refresh_token: str,
    ) -> HttpResponse | ProviderUsage | None:
        """Send one refresh request.

        Returns the 2xx response, a transient/rate-limit failure for outages,
        or None when the grant itself was refused.
        """
        try:
            response = self._post_form(
                REFRESH_URL,
                [
                    ("grant_type", "refresh_token"),
                    ("client_id", self._auth.client_id(credentials)),
                    ("refresh_token", refresh_token),
                ],
                {},
            )
        except Exception:
            return errored(
                PROVIDER_ID, DISPLAY, ICON,
                "Grok could not refresh its session.",
                FailureKind.TRANSIENT,
            )
        if response.status == 429:
            return rate_limited(
                PROVIDER_ID, DISPLAY, ICON,
                "Grok is rate limited. Try again later.",
                retry_datetime(response.header("retry-after"), self._utc_now()),
            )
        if response.status >= 500:
            return errored(
                PROVIDER_ID, DISPLAY, ICON,
                "Grok could not refresh its session.",
                FailureKind.TRANSIENT,
            )
        if not 200 <= response.status < 300:
            return None
        return response

    @staticmethod
    def _storage_failure() -> ProviderUsage:
        return errored(
            PROVIDER_ID, DISPLAY, ICON,
            "Grok sign-in data could not be read.",
            FailureKind.STORAGE,
        )

    @staticmethod
    def _adopt(credentials: GrokCredentials, live: GrokCredentials) -> None:
        credentials.token = live.token
        credentials.entry = live.entry
        credentials.document = live.document
        credentials.raw_text = live.raw_text

    @staticmethod
    def map(
        response: HttpResponse,
        plan_response: Optional[HttpResponse],
        now: datetime,
    ) -> ProviderUsage:
        if response.status == 429:
            return rate_limited(
                PROVIDER_ID, DISPLAY, ICON,
                "Grok is rate limited. Try again later.",
                retry_datetime(response.header("retry-after"), now),
            )
        if not 200 <= response.status < 300:
            return errored(
                PROVIDER_ID, DISPLAY, ICON,
                f"Grok usage request failed ({response.status}).",
                FailureKind.TRANSIENT if response.status >= 500 else FailureKind.INVALID_RESPONSE,
            )
        try:
            body = response.json()
        except (ValueError, UnicodeDecodeError):
            body = None
        config = body.get("config") if isinstance(body, dict) else None
        period = config.get("currentPeriod") if isinstance(config, dict) else None
        period_type = non_empty(period.get("type")) if isinstance(period, dict) else None
        reset = provider_datetime(period.get("end")) if isinstance(period, dict) else None
        if not isinstance(config, dict) or period_type is None or reset is None:
            return errored(
                PROVIDER_ID, DISPLAY, ICON,
                "Grok quota response changed.",
                FailureKind.INVALID_RESPONSE,
            )
        windows = []
        if period_type == WEEKLY_PERIOD:
            used = number(config.get("creditUsagePercent"))
            windows.append(UsageWindow(
                "Weekly",
                "weekly",
                min(max(used if used is not None else 0, 0), 100),
                reset,
            ))
        if not windows:
            return errored(
                PROVIDER_ID, DISPLAY, ICON,
                "Grok weekly quota is unavailable for this account.",
                FailureKind.INVALID_RESPONSE,
            )
        plan = None
        if plan_response is not None and 200 <= plan_response.status < 300:
            try:
                plan_body = plan_response.json()
                plan = (
                    non_empty(plan_body.get("subscription_tier_display"))
                    if isinstance(plan_body, dict)
                    else None
                )
            except (ValueError, UnicodeDecodeError):
                pass
        return ProviderUsage(
            provider_id=PROVIDER_ID,
            display_name=DISPLAY,
            icon=ICON,
            plan=plan,
            status=ProviderStatus.OK,
            error_message=None,
            windows=windows,
            last_updated=now,
        )

    def _utc_now(self) -> datetime:
        value = self._now()
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )
