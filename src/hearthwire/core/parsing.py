from __future__ import annotations

import base64
import json
import math
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional


def decode_json_with_hex_fallback(text: str) -> Optional[dict[str, Any]]:
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass

    encoded = text.strip()
    if encoded.lower().startswith("0x"):
        encoded = encoded[2:]
    if not encoded or len(encoded) % 2 or not all(c in "0123456789abcdefABCDEF" for c in encoded):
        return None
    try:
        value = json.loads(bytes.fromhex(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        try:
            result = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return result if math.isfinite(result) else None


def provider_datetime(value: Any) -> Optional[datetime]:
    numeric = number(value)
    if numeric is not None:
        seconds = numeric / 1000 if numeric > 10_000_000_000 else numeric
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith(" UTC"):
        normalized = normalized[:-4] + "Z"
    if re.match(r"^\d{4}-\d{2}-\d{2} ", normalized):
        normalized = normalized[:10] + "T" + normalized[11:]
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    if not re.search(r"([+-]\d{2}:\d{2})$", normalized):
        normalized += "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


MAX_RETRY_DELAY = timedelta(hours=24)
DEFAULT_RETRY_DELAY = timedelta(minutes=5)


def retry_datetime(value: Optional[str], now: datetime) -> datetime:
    """Turn a Retry-After header into a cooldown end clamped to [now, now + 24h]."""
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        return now + DEFAULT_RETRY_DELAY
    try:
        seconds = float(cleaned)
    except ValueError:
        seconds = None
    if seconds is not None:
        if math.isnan(seconds):
            return now + DEFAULT_RETRY_DELAY
        seconds = min(max(seconds, 0.0), MAX_RETRY_DELAY.total_seconds())
        return now + timedelta(seconds=seconds)
    try:
        parsed = parsedate_to_datetime(cleaned)
    except (TypeError, ValueError, OverflowError, IndexError):
        return now + DEFAULT_RETRY_DELAY
    if parsed is None:
        return now + DEFAULT_RETRY_DELAY
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        parsed = parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return now + MAX_RETRY_DELAY
    return min(max(parsed, now), now + MAX_RETRY_DELAY)


def jwt_expiration(token: str) -> Optional[datetime]:
    body = jwt_payload(token)
    return provider_datetime(body.get("exp")) if body is not None else None


def jwt_payload(token: str) -> Optional[dict[str, Any]]:
    segments = token.split(".")
    if len(segments) < 2:
        return None
    payload = segments[1]
    payload += "=" * ((4 - len(payload) % 4) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        body = json.loads(decoded)
    except (ValueError, UnicodeError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


def unwrap_go_keyring(value: Any) -> Optional[str]:
    text = non_empty(value)
    if text is None:
        return None
    prefix = "go-keyring-base64:"
    if text.startswith(prefix):
        try:
            text = base64.b64decode(text[len(prefix):]).decode("utf-8").strip()
        except (ValueError, UnicodeDecodeError):
            return None
    return text or None


def non_empty(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def title_case_identifier(value: str) -> str:
    return " ".join(
        part[:1].upper() + part[1:].lower()
        for part in value.replace("_", " ").split()
    )


def cents_to_dollars(cents: float) -> float:
    return math.floor(cents + 0.5) / 100
