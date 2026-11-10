"""Settings backup for Settings → General → Backup (round 4 idea 8, plan D71, D74).

One fixed file, no file dialog::

    $XDG_CONFIG_HOME (when absolute, else ~/.config)/
        hearthwire/                  0700, created only by export
            settings-backup.json     0600, replaced atomically

    {"format":"hearthwire-settings","version":1,"config_schema":3,
     "exported_at":"YYYY-MM-DDTHH:MM:SSZ","settings":{...}}

``export`` gets the widget's settings as lowercase hex of a UTF-8 JSON object
(so no quoting reaches argv) and ``import`` hands the checked settings back.
Both run the same ``validate_settings``: only BACKUP_KEYS, each checked
strictly against what the widget itself would store; anything unknown or odd
is dropped and counted. Sign-in, vault, zoom and history settings are never
in a backup (EXCLUDED_KEYS). Replies hold codes, counts, the timestamp and,
for import, the checked settings; never a path.
"""

from __future__ import annotations

import errno
import json
import math
import os
import re
import stat
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .catalog import CATALOG_BY_ID, PROVIDER_CATALOG, PROVIDER_IDS
from .webdata import APP_DIR, PRIVATE_MODE, HelperError, _close, _descriptors, open_base, open_child_dir

OPERATIONS = ("status", "export", "import")
FORMAT = "hearthwire-settings"
FORMAT_VERSION = 1
CONFIG_SCHEMA = 3
BACKUP_FILE = "settings-backup.json"
FILE_MODE = 0o600
MAX_FILE_BYTES = 64 * 1024
MAX_DATA_HEX = 131072
MAX_STRING_CHARS = 4096
# chatCustomUrls holds up to seven addresses of 2048 characters each.
MAX_CUSTOM_URLS_CHARS = 32768

# Codes the plasmoid knows for --settings-backup; anything else is os-error.
ERRORS = frozenset({
    "absent", "invalid", "unsupported", "too-large", "bad-data", "symlink", "not-owned", "unsafe-mode", "legacy-data",
    "os-error",
})

# Saved and restored. main.xml keys plus the round-4 panelRing and middleClickOpens.
BACKUP_KEYS = (
    "trackedProviders", "providerMetrics", "providerOrder", "usageMode", "refreshInterval",
    "tooltipShowsUsage", "tooltipMetrics", "usageCompact",
    "usageWarnPercent", "usageCriticalPercent",
    "usageNormalColor", "usageWarnColor", "usageCriticalColor",
    "alertLowEnabled", "alertResetEnabled", "alertLowPercent",
    "chatSites", "chatDefaultSite", "chatOllamaUrl", "chatKeepOpen",
    "showUsageTab", "showChatTab", "popupDefaultTab", "popupSize", "shortcutOpens",
    "panelRing", "middleClickOpens",
    "chatCustomUrls",  # D74
)
# Never saved, never restored: sign-ins, the encrypted folder, per-site zoom,
# schema and first-run state, and the history opt-in (D70) with its owed delete.
EXCLUDED_KEYS = (
    "chatSignInStorage", "chatProfileGeneration", "chatAutoLockMinutes",
    "chatVaultUnlock", "chatSiteZoom", "configSchemaVersion",
    "initialSetupComplete", "usageHistoryEnabled", "usageHistoryClearOwed",
)

# Chat sites as in plasmoid/contents/ui/ChatSites.js (``sites``) and the
# built-in Ollama entry (OllamaChat.js ``ENTRY.id``).
WEB_SITE_IDS = ("claude", "chatgpt", "grok", "gemini", "copilot", "mscopilot", "local")
LOCAL_SITE_IDS = frozenset({"local"})
OLLAMA_SITE_ID = "ollama"
CHAT_SITE_IDS = WEB_SITE_IDS + (OLLAMA_SITE_ID,)

REFRESH_INTERVALS = (60, 300, 900, 1800, 3600)            # configGeneral.qml refreshChoices
COLOR_PERCENTS = tuple(range(50, 100, 5))                 # UsageLogic.js COLOR_PERCENTS
WARN_PERCENTS = COLOR_PERCENTS[:-1]
CRITICAL_PERCENTS = COLOR_PERCENTS[1:]
ALERT_PERCENTS = (5, 10, 15, 20, 25, 30, 40, 50)          # SettingsLogic.js ALERT_PERCENTS
USAGE_MODES = ("remaining", "used")
POPUP_TABS = ("chat", "usage")                            # SettingsLogic.js POPUP_TABS
POPUP_SIZES = ("compact", "normal", "large")              # SettingsLogic.js POPUP_SIZES
SHORTCUT_TARGETS = ("popup", "chat", "ollama", "usage")   # SettingsLogic.js SHORTCUT_TARGETS
MIDDLE_CLICK_TARGETS = ("refresh", "usage", OLLAMA_SITE_ID) + WEB_SITE_IDS
RING_PAIRS = frozenset(
    f"{entry.provider_id}.{metric}"
    for entry in PROVIDER_CATALOG
    for metric in entry.supported_metrics
    if metric != "extra_usage"
)

_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f\ud800-\udfff]")
_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
_OLLAMA_ADDRESS = re.compile(r"http://(127\.0\.0\.1|localhost|\[::1\]):([1-9][0-9]{0,4})")
_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_STAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_HEX = re.compile(r"(?:[0-9a-f]{2})+")

_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOCTTY
_CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


class _Bad(Exception):
    """A value that is dropped."""


# --- strict JSON --------------------------------------------------------------------------------------


def _no_duplicates(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _no_constant(name: str) -> object:
    raise ValueError("NaN or Infinity")


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("non-finite number")  # 1e999
    return value


def strict_loads(text: str) -> object:
    """``json.loads`` that refuses NaN, Infinity, overflowing floats and duplicate keys.

    Raises ValueError for any of those and for malformed or too deeply nested JSON.
    """
    try:
        return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant,
                          parse_float=_finite_float)
    except RecursionError:
        raise ValueError("too deeply nested") from None


def _dumps(value: object) -> str:
    """As JSON.stringify writes it: compact, non-ASCII kept."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


# --- chatCustomUrls: a port of ChatSites.js -----------------------------------------------------------

MAX_CUSTOM_URL_LENGTH = 2048  # ChatSites.js MAX_CUSTOM_URL_LENGTH, in UTF-16 units like JS .length
# JavaScript's \s: WhiteSpace and LineTerminator (ECMA-262), not Python's.
_JS_SPACE = "\t\n\v\f\r    -     　﻿"
_URL_FORBIDDEN = re.compile("[" + _JS_SPACE + "\x00-\x1f\x7f]")
_AUTHORITY_FORBIDDEN = re.compile("[@\\\\%" + _JS_SPACE + "]")
_SCHEME_PREFIX = re.compile(r"([A-Za-z][A-Za-z0-9+.\-]*):")
_AUTHORITY_PREFIX = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://([^/?#]*)")
_SCHEME_REST = re.compile(r"([A-Za-z][A-Za-z0-9+.\-]*):(.*)")
_BRACKET_AUTHORITY = re.compile(r"(\[::1\])(?::([0-9]{1,5}))?")
_HOST_AUTHORITY = re.compile(r"([A-Za-z0-9.\-]+)(?::([0-9]{1,5}))?")
_LOCAL_NAMES = ("localhost.localdomain", "ip6-localhost", "ip6-loopback")


def _utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def normalize_host(host: str) -> str:
    """ChatSites.js normalizeHost: lower case, one trailing dot removed."""
    normalized = host.lower()
    return normalized[:-1] if normalized.endswith(".") else normalized


def is_loopback_host(host: str) -> bool:
    """ChatSites.js isLoopbackHost."""
    return normalize_host(host) in ("localhost", "127.0.0.1", "[::1]")


def ipv4_value(host: str) -> int:
    """ChatSites.js ipv4Value: an IPv4 literal in any browser form, -1 when it can't be one."""
    parts = host.split(".")
    if len(parts) > 4:
        return -1
    numbers = []
    for part in parts:
        if re.fullmatch(r"0x[0-9a-f]*", part):
            number = int(part[2:], 16) if len(part) > 2 else 0
        elif re.fullmatch(r"0[0-7]+", part):
            number = int(part[1:], 8)
        elif re.fullmatch(r"0|[1-9][0-9]*", part):
            number = int(part, 10)
        else:
            return -1
        numbers.append(number)
    value = 0
    for number in numbers[:-1]:
        if number > 255:
            return -1
        value = value * 256 + number
    room = 256 ** (5 - len(numbers))
    if numbers[-1] >= room:
        return -1
    return value * room + numbers[-1]


def is_local_address(host: str) -> bool:
    """ChatSites.js isLocalAddress: everything the browser would send to this computer."""
    normalized = normalize_host(host)
    if normalized == "":
        return False
    if (is_loopback_host(normalized) or "." not in normalized or normalized in _LOCAL_NAMES
            or normalized.endswith(".localhost") or normalized.endswith(".localhost.localdomain")):
        return True
    if not re.fullmatch(r"0x[0-9a-f]*|[0-9]+", normalized.split(".")[-1]):
        return False
    value = ipv4_value(normalized)
    return value < 0 or value == 0 or value // 16777216 == 127


def parse_url(text: str) -> Optional[tuple[str, str, str]]:
    """ChatSites.js parseUrl: (scheme, host, port) or None when malformed."""
    match = _SCHEME_REST.fullmatch(text)
    if match is None:
        return None
    scheme, rest = match.group(1).lower(), match.group(2)
    if scheme not in ("https", "http"):
        return (scheme, "", "")
    if not rest.startswith("//"):
        return None
    authority = re.split(r"[/?#]", rest[2:])[0]
    if authority == "" or _AUTHORITY_FORBIDDEN.search(authority):
        return None
    if authority.startswith("["):
        bracket = _BRACKET_AUTHORITY.fullmatch(authority)
        if bracket is None:
            return None
        host, port = bracket.group(1), bracket.group(2)
    else:
        plain = _HOST_AUTHORITY.fullmatch(authority)
        if plain is None:
            return None
        host, port = plain.group(1).lower(), plain.group(2)
        if host.startswith(".") or ".." in host:
            return None
    if port is None:
        port = ""
    else:
        number = int(port, 10)
        if number < 1 or number > 65535:
            return None
        port = str(number)
    return (scheme, host, port)


def custom_url_error(site_id: str, value: str) -> str:
    """ChatSites.js validateCustomUrl: "" when valid (or empty), else its error code."""
    if site_id not in WEB_SITE_IDS:
        return "unknown-site"
    if value == "":
        return ""
    if _utf16_length(value) > MAX_CUSTOM_URL_LENGTH:
        return "too-long"
    if _URL_FORBIDDEN.search(value):
        return "whitespace"
    authority = _AUTHORITY_PREFIX.match(value)
    if authority is not None and "@" in authority.group(1):
        return "userinfo"
    scheme_match = _SCHEME_PREFIX.match(value)
    if scheme_match is None:
        return "malformed"
    scheme = scheme_match.group(1).lower()
    local = site_id in LOCAL_SITE_IDS
    if scheme != "https" and not (scheme == "http" and local):
        return "scheme"
    parsed = parse_url(value)
    if parsed is None or parsed[1] == "":
        return "malformed"
    if parsed[0] == "http" and not is_loopback_host(parsed[1]):
        return "http-not-loopback"
    if not local and is_local_address(parsed[1]):
        return "loopback-not-allowed"
    return ""


# --- per-key rules ------------------------------------------------------------------------------------


def _text(value: object, limit: int = MAX_STRING_CHARS) -> str:
    """A string of at most ``limit`` characters without C0/C1 controls or lone surrogates."""
    if not isinstance(value, str) or len(value) > limit or _CONTROL.search(value):
        raise _Bad()
    return value


def _choice(options: tuple) -> Callable[[object], object]:
    def check(value: object) -> object:
        if isinstance(value, str):
            _text(value)
        elif type(value) is not int:  # bool is never an int here.
            raise _Bad()
        if value not in options:
            raise _Bad()
        return value
    return check


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise _Bad()
    return value


def _embedded(value: object, limit: int = MAX_STRING_CHARS) -> object:
    """The JSON a String setting holds, parsed strictly."""
    try:
        return strict_loads(_text(value, limit))
    except ValueError:
        raise _Bad() from None


def _id_list(value: object, known: tuple[str, ...]) -> list[str]:
    if not isinstance(value, list) or len(value) != len(set(map(repr, value))):
        raise _Bad()
    for item in value:
        if not isinstance(item, str) or item not in known:
            raise _Bad()
    return value


def _provider_list(value: object) -> str:
    """trackedProviders: a JSON array of catalog provider ids, none twice."""
    return _dumps(_id_list(_embedded(value), PROVIDER_IDS))


def _provider_order(value: object) -> str:
    """providerOrder: "" (catalog order) or a JSON array of catalog provider ids."""
    if _text(value) == "":
        return ""
    return _provider_list(value)


def _metric_map(value: object) -> str:
    """providerMetrics / tooltipMetrics: {providerId: [metricIds of that provider]}."""
    parsed = _embedded(value)
    if not isinstance(parsed, dict):
        raise _Bad()
    result = {}
    for provider_id in PROVIDER_IDS:  # Catalog order, as the widget writes it.
        if provider_id in parsed:
            result[provider_id] = _id_list(parsed[provider_id], CATALOG_BY_ID[provider_id].supported_metrics)
    if len(result) != len(parsed):
        raise _Bad()
    return _dumps(result)


def _tooltip_metrics(value: object) -> str:
    """tooltipMetrics: "" (same as the Usage tab) or a metric map."""
    if _text(value) == "":
        return ""
    return _metric_map(value)


def _color(value: object) -> str:
    """A color: "" (the theme default) or #rrggbb, stored in lower case."""
    text = _text(value)
    if text == "":
        return ""
    if not _COLOR.fullmatch(text):
        raise _Bad()
    return text.lower()


def _chat_sites(value: object) -> str:
    """chatSites: a JSON array of chat site ids (web sites and ollama), none twice."""
    return _dumps(_id_list(_embedded(value), CHAT_SITE_IDS))


def _ollama_address(value: object) -> str:
    """chatOllamaUrl: the normalized loopback address OllamaChat.validateAddress stores."""
    match = _OLLAMA_ADDRESS.fullmatch(_text(value))
    if match is None or int(match.group(2)) > 65535:
        raise _Bad()
    return value  # type: ignore[return-value]


def _panel_ring(value: object) -> str:
    """panelRing: off, auto or a catalog provider.metric pair (not extra_usage)."""
    text = _text(value)
    if text not in ("off", "auto") and text not in RING_PAIRS:
        raise _Bad()
    return text


def _custom_urls(value: object) -> str:
    """chatCustomUrls (D74): {webSiteId: address}, every address valid and non-empty.

    The same JSON shape and URL rules as ChatSites.filterCustomUrls /
    validateCustomUrl, but strict: one odd entry drops the whole setting.
    """
    parsed = _embedded(value, MAX_CUSTOM_URLS_CHARS)
    if not isinstance(parsed, dict):
        raise _Bad()
    result = {}
    for site_id in WEB_SITE_IDS:
        if site_id not in parsed:
            continue
        url = _text(parsed[site_id], MAX_CUSTOM_URL_LENGTH)
        if url == "" or custom_url_error(site_id, url) != "":
            raise _Bad()
        result[site_id] = url
    if len(result) != len(parsed):
        raise _Bad()
    return _dumps(result)


RULES: dict[str, Callable[[object], object]] = {
    "trackedProviders": _provider_list,
    "providerMetrics": _metric_map,
    "providerOrder": _provider_order,
    "usageMode": _choice(USAGE_MODES),
    "refreshInterval": _choice(REFRESH_INTERVALS),
    "tooltipShowsUsage": _boolean,
    "tooltipMetrics": _tooltip_metrics,
    "usageCompact": _boolean,
    "usageWarnPercent": _choice(WARN_PERCENTS),
    "usageCriticalPercent": _choice(CRITICAL_PERCENTS),
    "usageNormalColor": _color,
    "usageWarnColor": _color,
    "usageCriticalColor": _color,
    "alertLowEnabled": _boolean,
    "alertResetEnabled": _boolean,
    "alertLowPercent": _choice(ALERT_PERCENTS),
    "chatSites": _chat_sites,
    "chatDefaultSite": _choice(CHAT_SITE_IDS),
    "chatOllamaUrl": _ollama_address,
    "chatKeepOpen": _boolean,
    "showUsageTab": _boolean,
    "showChatTab": _boolean,
    "popupDefaultTab": _choice(POPUP_TABS),
    "popupSize": _choice(POPUP_SIZES),
    "shortcutOpens": _choice(SHORTCUT_TARGETS),
    "panelRing": _panel_ring,
    "middleClickOpens": _choice(MIDDLE_CLICK_TARGETS),
    "chatCustomUrls": _custom_urls,
}


def validate_settings(value: Mapping[str, object]) -> tuple[dict[str, object], int]:
    """(kept settings in BACKUP_KEYS order, number dropped).

    The one check for export input and the import file. Unknown and excluded
    keys are dropped, and so is a known key with a value the widget would not
    store; both count in the number dropped.
    """
    kept: dict[str, object] = {}
    for key in BACKUP_KEYS:
        if key not in value:
            continue
        try:
            kept[key] = RULES[key](value[key])
        except _Bad:
            continue
    return kept, len(value) - len(kept)


# --- the file -----------------------------------------------------------------------------------------


def config_base(environ: Optional[Mapping[str, str]] = None) -> str:
    """``$XDG_CONFIG_HOME`` when it is absolute, else ``~/.config``."""
    values = os.environ if environ is None else environ
    configured = values.get("XDG_CONFIG_HOME") or ""
    if configured and os.path.isabs(configured):
        return configured
    return str(Path.home() / ".config")


def _unsafe(mode: int) -> bool:
    return bool(stat.S_IMODE(mode) & 0o022)


def _backup_directory(environ: Optional[Mapping[str, str]], opened: list[int], *, create: bool) -> Optional[int]:
    """``<config>/hearthwire``: never a symlink, ours, not group- or other-writable.

    Only ``create`` (export) makes it (0700) or tightens a safe one to 0700,
    and never while the previous version's data waits for the installer (the
    new folder would then be a conflict).
    """
    if create:
        from .legacy import refuse_legacy_data  # Imported here: legacy itself builds on this module.

        refuse_legacy_data(environ)
    base = open_base(config_base(environ), create=create)
    if base is None:
        return None
    opened.append(base)
    directory = open_child_dir(base, APP_DIR, create=False)
    if directory is None:
        if not create:
            return None
        directory = open_child_dir(base, APP_DIR, create=True)
        if directory is None:
            raise HelperError("os-error")
        opened.append(directory)
        return directory
    opened.append(directory)
    try:
        info = os.fstat(directory)
        if _unsafe(info.st_mode):
            raise HelperError("unsafe-mode")
        if create and stat.S_IMODE(info.st_mode) != PRIVATE_MODE:
            os.fchmod(directory, PRIVATE_MODE)
    except OSError:
        raise HelperError("os-error") from None
    return directory


def _read_file(directory: int) -> bytes:
    try:
        descriptor = os.open(BACKUP_FILE, _READ_FLAGS, dir_fd=directory)
    except FileNotFoundError:
        raise HelperError("absent") from None
    except OSError as error:
        raise HelperError("symlink" if error.errno == errno.ELOOP else "os-error") from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise HelperError("invalid")
        if info.st_uid != os.getuid():
            raise HelperError("not-owned")
        if _unsafe(info.st_mode):
            raise HelperError("unsafe-mode")
        if info.st_size > MAX_FILE_BYTES:
            raise HelperError("too-large")
        data = b""
        while len(data) <= MAX_FILE_BYTES:
            chunk = os.pread(descriptor, MAX_FILE_BYTES + 1 - len(data), len(data))
            if not chunk:
                break
            data += chunk
        if len(data) > MAX_FILE_BYTES:
            raise HelperError("too-large")
        return data
    except OSError:
        raise HelperError("os-error") from None
    finally:
        _close(descriptor)


def _check_target(directory: int) -> None:
    """Export never replaces a symlink or someone else's file."""
    try:
        info = os.stat(BACKUP_FILE, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError:
        raise HelperError("os-error") from None
    if stat.S_ISLNK(info.st_mode):
        raise HelperError("symlink")
    if not stat.S_ISREG(info.st_mode):
        raise HelperError("os-error")
    if info.st_uid != os.getuid():
        raise HelperError("not-owned")


def _unlink(directory: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=directory)
    except OSError:
        pass


def _write_file(directory: int, data: bytes) -> None:
    """Replace the backup atomically: O_EXCL temporary (0600), fsync, rename, fsync dir."""
    temporary = f"{BACKUP_FILE}.{os.urandom(8).hex()}.tmp"
    try:
        descriptor = os.open(temporary, _CREATE_FLAGS, FILE_MODE, dir_fd=directory)
    except OSError:
        raise HelperError("os-error") from None
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view):]
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != FILE_MODE:
            os.fchmod(descriptor, FILE_MODE)
        os.fsync(descriptor)
        os.replace(temporary, BACKUP_FILE, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    except OSError:
        _unlink(directory, temporary)
        raise HelperError("os-error") from None
    finally:
        _close(descriptor)


def _valid_stamp(value: object) -> bool:
    if not isinstance(value, str) or not _STAMP.fullmatch(value):
        return False
    try:
        datetime.strptime(value, _STAMP_FORMAT)
    except ValueError:
        return False
    return True


def parse_document(data: bytes) -> tuple[str, dict[str, object], int]:
    """(exported_at, checked settings, number dropped) of a backup file's bytes."""
    try:
        document = strict_loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise HelperError("invalid") from None
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise HelperError("invalid")
    for key, expected in (("version", FORMAT_VERSION), ("config_schema", CONFIG_SCHEMA)):
        if type(document.get(key)) is not int:
            raise HelperError("invalid")
        if document[key] != expected:
            raise HelperError("unsupported")
    if set(document) != {"format", "version", "config_schema", "exported_at", "settings"}:
        raise HelperError("invalid")
    if not _valid_stamp(document["exported_at"]) or not isinstance(document["settings"], dict):
        raise HelperError("invalid")
    settings, dropped = validate_settings(document["settings"])
    return document["exported_at"], settings, dropped


def decode_data(value: object) -> dict[str, object]:
    """The settings object export got as lowercase hex of UTF-8 JSON; else bad-data."""
    if not isinstance(value, str) or len(value) > MAX_DATA_HEX or not _HEX.fullmatch(value):
        raise HelperError("bad-data")
    try:
        parsed = strict_loads(bytes.fromhex(value).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise HelperError("bad-data") from None
    if not isinstance(parsed, dict):
        raise HelperError("bad-data")
    return parsed


def encode_document(settings: dict[str, object], exported_at: str) -> bytes:
    document = {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "config_schema": CONFIG_SCHEMA,
        "exported_at": exported_at,
        "settings": settings,
    }
    return (_dumps(document) + "\n").encode("utf-8")


# --- operations ---------------------------------------------------------------------------------------


def _load(environ: Optional[Mapping[str, str]]) -> tuple[str, dict[str, object], int]:
    with _descriptors() as opened:
        directory = _backup_directory(environ, opened, create=False)
        if directory is None:
            raise HelperError("absent")
        data = _read_file(directory)
    return parse_document(data)


def status(environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    """Whether a valid backup is there, and when it was made; creates nothing."""
    try:
        exported_at, _, _ = _load(environ)
    except HelperError as error:
        if error.code == "absent":
            return {"ok": True, "exists": False}
        raise
    return {"ok": True, "exists": True, "exported_at": exported_at}


def export(
    data: object,
    environ: Optional[Mapping[str, str]] = None,
    *,
    clock: Callable[[], float] = time.time,
) -> dict[str, object]:
    """Check the widget's settings and replace the backup with them."""
    settings, dropped = validate_settings(decode_data(data))
    if not settings:
        raise HelperError("bad-data")  # Never replace a backup with nothing.
    encoded = encode_document(settings, time.strftime(_STAMP_FORMAT, time.gmtime(int(clock()))))
    if len(encoded) > MAX_FILE_BYTES:
        raise HelperError("too-large")
    with _descriptors() as opened:
        directory = _backup_directory(environ, opened, create=True)
        if directory is None:
            raise HelperError("os-error")
        _check_target(directory)
        _write_file(directory, encoded)
    return {"ok": True, "saved": len(settings), "dropped": dropped}


def import_settings(environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    """The backup's checked settings; the widget applies them only after Replace and Apply."""
    exported_at, settings, dropped = _load(environ)
    return {"ok": True, "exported_at": exported_at, "settings": settings, "dropped": dropped}


def run(
    operation: str,
    *,
    data: Optional[str] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> dict[str, object]:
    """CLI entry: a reply that never carries a path."""
    try:
        if operation == "status":
            return status(environ)
        if operation == "export":
            return export(data, environ)
        if operation == "import":
            return import_settings(environ)
        raise ValueError("Unsupported settings backup operation.")
    except HelperError as error:
        return {"ok": False, "error": error.code if error.code in ERRORS else "os-error"}
    except OSError:
        return {"ok": False, "error": "os-error"}


__all__ = ["BACKUP_KEYS", "EXCLUDED_KEYS", "OPERATIONS", "run", "validate_settings"]
