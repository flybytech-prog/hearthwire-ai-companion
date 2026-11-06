import json
from datetime import datetime, timedelta, timezone

from hearthwire.core.parsing import (
    decode_json_with_hex_fallback,
    jwt_expiration,
    number,
    provider_datetime,
    retry_datetime,
)


def test_json_hex_fallback_and_number_rules():
    payload = '{"tokens":{"access_token":"abc"}}'
    assert decode_json_with_hex_fallback(payload)["tokens"]["access_token"] == "abc"
    assert decode_json_with_hex_fallback(payload.encode().hex())["tokens"]["access_token"] == "abc"
    assert decode_json_with_hex_fallback("not-json") is None
    assert number(True) is None
    assert number("17.25") == 17.25


def test_provider_datetime_accepts_iso_epoch_seconds_and_milliseconds():
    assert provider_datetime("2027-01-15T12:00:00.123456").tzinfo == timezone.utc
    assert provider_datetime("2027-01-15 12:00:00 UTC").tzinfo == timezone.utc
    assert provider_datetime(1_800_100_000) == datetime.fromtimestamp(
        1_800_100_000,
        tz=timezone.utc,
    )
    assert provider_datetime(1_800_200_000_000) == datetime.fromtimestamp(
        1_800_200_000,
        tz=timezone.utc,
    )


def test_retry_after_and_jwt_expiration():
    now = datetime(2027, 1, 15, tzinfo=timezone.utc)
    assert (retry_datetime("120", now) - now).total_seconds() == 120
    assert (retry_datetime(None, now) - now).total_seconds() == 300

    header = _segment({"alg": "none"})
    payload = _segment({"exp": now.timestamp() + 60})
    assert jwt_expiration(f"{header}.{payload}.") == datetime.fromtimestamp(
        now.timestamp() + 60,
        tz=timezone.utc,
    )


def test_retry_after_is_clamped_to_a_day_and_never_raises():
    now = datetime(2027, 1, 15, tzinfo=timezone.utc)
    day = timedelta(hours=24)
    for value in ("inf", "1e20", "Fri, 31 Dec 9999 23:59:59 GMT", "86401"):
        assert retry_datetime(value, now) - now == day, value
    for value in ("-5", "-inf", "Wed, 21 Oct 2015 07:28:00 GMT"):
        assert retry_datetime(value, now) == now, value
    for value in ("nan", None, "", "   ", "garbage", "Fri, 99 Foo"):
        assert retry_datetime(value, now) - now == timedelta(minutes=5), value
    assert retry_datetime("120", now) - now == timedelta(seconds=120)
    assert retry_datetime(
        "Fri, 15 Jan 2027 00:10:00 GMT",
        now,
    ) - now == timedelta(minutes=10)


def _segment(value):
    import base64

    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")
