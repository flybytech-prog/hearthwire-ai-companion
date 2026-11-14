"""Settings backup for Settings → General → Backup (round 4 idea 8, plan D71, D74).

One fixed file, no file dialog::

    $XDG_CONFIG_HOME (when absolute, else ~/.config)/
        hearthwire/                  0700, created only by export
            settings-backup.json     0600, replaced atomically

    {"format":"hearthwire-settings","version":1,"config_schema":3,
     "exported_at":"YYYY-MM-DDTHH:MM:SSZ","settings":{...}}

``export --applet N`` reads widget N's applied settings itself from Plasma's
rc file (core/appletconfig.py), so nothing the user typed ever reaches argv
(audit M1), and ``import`` hands the checked settings back. Both run the
same ``validate_settings``: only BACKUP_KEYS, each checked
strictly against what the widget itself would store; anything unknown or odd
is dropped and counted. Sign-in, vault, zoom and history settings are never
in a backup (EXCLUDED_KEYS). Replies hold codes, counts, the timestamp and,
for import, the checked settings; never a path.

Task 005: the sites the user added (``chatUserSites``, ids ``user-`` and 8 hex
digits) and the site order (``chatSiteOrder``) are in the backup, so the file
may be up to 512 KiB. A second, cross-key pass lets ``chatSites``,
``chatSiteOrder``, ``chatDefaultSite`` and ``middleClickOpens`` name an added
id only when the same settings keep a valid ``chatUserSites`` holding it; any
other added id drops that whole setting.

Task 006: an added site may also be a server on this computer (localhost,
127.0.0.1, [::1]) or a home-network IP literal, over http or https. The keys
and the format are unchanged; only the set of valid addresses grew
(user_site_url_error, the same codes and order as ChatSites.js).
"""

from __future__ import annotations

import bisect
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

from .appletconfig import applied_settings
from .catalog import CATALOG_BY_ID, PROVIDER_CATALOG, PROVIDER_IDS
from .jsondepth import check_depth
from .webdata import APP_DIR, PRIVATE_MODE, HelperError, _close, _descriptors, open_base, open_child_dir

OPERATIONS = ("status", "export", "import")
FORMAT = "hearthwire-settings"
FORMAT_VERSION = 1
CONFIG_SCHEMA = 3
BACKUP_FILE = "settings-backup.json"
FILE_MODE = 0o600
# 200 added sites with 40-unit names and 2048-character addresses fit (task 005).
MAX_FILE_BYTES = 512 * 1024
MAX_STRING_CHARS = 4096
# Arrays and objects nest at most 2 deep, both in the document (document >
# settings) and in the JSON a setting holds (metric map > list); 4 leaves room.
# Checked before json.loads, whatever the interpreter's recursion handling.
MAX_JSON_DEPTH = 4
# chatCustomUrls holds up to seven addresses of 2048 characters each.
MAX_CUSTOM_URLS_CHARS = 32768

# Codes the plasmoid knows for --settings-backup; anything else is os-error.
# applet-not-found and settings-unreadable are export's: the widget's rc entry
# (core/appletconfig.py) is missing or ambiguous, or its rc file is unsafe to read.
ERRORS = frozenset({
    "absent", "invalid", "unsupported", "too-large", "bad-data", "symlink", "not-owned", "unsafe-mode", "legacy-data",
    "applet-not-found", "settings-unreadable", "os-error",
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
    "chatUserSites", "chatSiteOrder",  # task 005
)
# Never saved, never restored: sign-ins, the encrypted folder, per-site zoom,
# schema and first-run state, the history opt-in (D70) with its owed delete,
# the per-site profile migration marker and the site clears still owed after
# a failed delete (task 004, both written only by main.qml).
EXCLUDED_KEYS = (
    "chatSignInStorage", "chatProfileGeneration", "chatAutoLockMinutes",
    "chatVaultUnlock", "chatSiteZoom", "configSchemaVersion",
    "initialSetupComplete", "usageHistoryEnabled", "usageHistoryClearOwed",
    "chatProfileLayout", "chatPendingSiteClears",
)

# Chat sites as in plasmoid/contents/ui/ChatSites.js (``sites``) and the
# built-in Ollama entry (OllamaChat.js ``ENTRY.id``).
WEB_SITE_IDS = ("claude", "chatgpt", "grok", "gemini", "copilot", "mscopilot", "local")
LOCAL_SITE_IDS = frozenset({"local"})
OLLAMA_SITE_ID = "ollama"
CHAT_SITE_IDS = WEB_SITE_IDS + (OLLAMA_SITE_ID,)
# Their names, in the same order (ChatSites.js ``name``, OllamaChat.js ENTRY.name):
# an added site may not take one of them, in any case.
WEB_SITE_NAMES = ("Claude", "ChatGPT", "Grok", "Gemini", "GitHub Copilot", "Microsoft Copilot",
                  "Local web UI (Open WebUI)")
OLLAMA_SITE_NAME = "Ollama"

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
# _write_file's temporary names: what a crashed export left behind.
_TEMPORARY_NAME = re.compile(r"settings-backup\.json\.[0-9a-f]{16}\.tmp")

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

    Raises ValueError for any of those and for malformed JSON or JSON nested
    deeper than ``MAX_JSON_DEPTH`` (checked first, so deep text never reaches
    json.loads; RecursionError stays caught as a second line).
    """
    check_depth(text, MAX_JSON_DEPTH)
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
_USER_BRACKET_AUTHORITY = re.compile(r"\[([0-9A-Fa-f:]{2,39})\](?::([0-9]{1,5}))?")  # parse_user_url only
_CANONICAL_IPV4 = re.compile(r"(?:0|[1-9][0-9]{0,2})(?:\.(?:0|[1-9][0-9]{0,2})){3}")
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


def parse_user_url(text: str) -> Optional[tuple[str, str, str]]:
    """ChatSites.js parseUserUrl (task 006): parse_url plus any bracketed IPv6 literal.

    For added-site addresses only; built-ins keep the narrow parse_url. The
    bracket holds 2-39 characters of ``[0-9A-Fa-f:]`` (no dots, no zone id),
    returned lower-cased with its brackets. Whether it is a valid, canonical
    address is decided later (canonical_ipv6).
    """
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
        bracket = _USER_BRACKET_AUTHORITY.fullmatch(authority)
        if bracket is None:
            return None
        host, port = "[" + bracket.group(1).lower() + "]", bracket.group(2)
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


def canonical_ipv4(host: str) -> bool:
    """ChatSites.js canonicalIpv4: four parts of ``0|[1-9][0-9]{0,2}``, each at most 255.

    127.1, 0x7f.1, 010.0.0.1, 3232235777, 192.168.1.020 and a trailing dot are not canonical.
    """
    return _CANONICAL_IPV4.fullmatch(host) is not None and all(int(part) <= 255 for part in host.split("."))


def _ipv6_groups(text: str) -> Optional[list[int]]:
    """The 8 groups of an IPv6 address written in hex and colons only, None when it is not one."""
    if not re.fullmatch(r"[0-9a-f:]+", text) or text.count("::") > 1:
        return None
    if "::" in text:
        head, tail = text.split("::")
        left = head.split(":") if head else []
        right = tail.split(":") if tail else []
        if len(left) + len(right) > 7:
            return None
        parts = left + ["0"] * (8 - len(left) - len(right)) + right
    else:
        parts = text.split(":")
        if len(parts) != 8:
            return None
    if any(part == "" or len(part) > 4 for part in parts):
        return None
    return [int(part, 16) for part in parts]


def canonical_ipv6(text: str) -> str:
    """ChatSites.js canonicalIpv6: the WHATWG / Chromium serialization of ``text``, "" when invalid.

    ``text`` is the literal without brackets. Lower case, no leading zeros, and
    the first longest run of two or more zero groups written as ``::``. Not
    ipaddress: from Python 3.13 it writes ::ffff:0:0/96 with a dotted IPv4 tail,
    which no browser does. A literal is canonical when this equals its lower case.
    """
    groups = _ipv6_groups(text.lower())
    if groups is None:
        return ""
    start, length = -1, 1
    index = 0
    while index < 8:
        end = index
        while end < 8 and groups[end] == 0:
            end += 1
        if end - index > length:
            start, length = index, end - index
        index = max(end, index + 1)
    words = [format(group, "x") for group in groups]
    if start < 0:
        return ":".join(words)
    return ":".join(words[:start]) + "::" + ":".join(words[start + length:])


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


# --- chatUserSites: a port of ChatSites.js (task 005) -------------------------------------------------

MAX_USER_SITES = 200                  # ChatSites.js MAX_USER_SITES; + 7 built-ins = webdata.MAX_SITE_IDS
MAX_USER_SITES_CHARS = 448 * 1024     # ChatSites.js MAX_USER_SITES_CHARS, the stored text in UTF-16 units
MAX_USER_SITE_NAME = 40               # ChatSites.js MAX_USER_SITE_NAME, in UTF-16 units
USER_SITE_KEYS = ("id", "name", "url")  # Exactly these, written in this order.
_USER_SITE_ID = re.compile(r"user-[0-9a-f]{8}")
# String.prototype.trim as Qt's JS engine runs it: it also strips U+0085 (review I-3).
_JS_TRIM = re.compile("^[" + _JS_SPACE + "\\x85]+|[" + _JS_SPACE + "\\x85]+\\Z")
# Markup characters, and invisible or bidi formatting that could spoof the table or a prompt (M3,
# round 2 SEC M-1): every Default_Ignorable_Code_Point (U+00AD, U+034F, U+061C, U+115F-1160,
# U+17B4-17B5, U+180B-180F, U+200B-200F, U+202A-202E, U+2060-206F, U+3164, U+FE00-FE0F, U+FEFF,
# U+FFA0, U+FFF0-FFF8, U+1BCA0-1BCA3, U+1D173-1D17A, U+E0000-E0FFF), the interlinear annotation
# marks U+FFF9-FFFB, the blank Braille pattern U+2800, and U+2028-2029 (kept from 005 round 1).
_NAME_FORBIDDEN = re.compile(
    "[<>&\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u2028-\u202e"
    "\u2060-\u206f\u2800\u3164\ufe00-\ufe0f\ufeff\uffa0\ufff0-\ufffb"
    "\U0001bca0-\U0001bca3\U0001d173-\U0001d17a\U000e0000-\U000e0fff]")
# Steps 3 and 4 of userSiteUrlError: printable ASCII only, without the characters
# a browser would percent-encode or refuse.
_USER_URL_CHARS = re.compile(r'[^\x21-\x7e]|["\\<>`{}|^]')
_NUMERIC_LABEL = re.compile(r"0x[0-9a-f]*|[0-9]+")


# Round 3 (SEC I-5): the general-category tables both ports use, as comma-separated
# "start-end" hex ranges, generated once from Python 3.14's unicodedata (Unicode 16.0.0)
# and kept equal to ChatSites.js (tests/test_settingsbackup.py), so the helper and the
# widget read a name the same way whatever Unicode version either runtime has.
# Format (Cf) and private-use (Co) code points: never in a name.
FORMAT_PRIVATE_RANGES = (
    "ad,600-605,61c,6dd,70f,890-891,8e2,180e,200b-200f,202a-202e,2060-2064,2066-206f,e000-f8ff,feff,"
    "fff9-fffb,110bd,110cd,13430-1343f,1bca0-1bca3,1d173-1d17a,e0001,e0020-e007f,f0000-ffffd,"
    "100000-10fffd"
)
# Letters and digits (L*, N*): a name needs at least one.
LETTER_DIGIT_RANGES = (
    "30-39,41-5a,61-7a,aa,b2-b3,b5,b9-ba,bc-be,c0-d6,d8-f6,f8-2c1,2c6-2d1,2e0-2e4,2ec,2ee,370-374,"
    "376-377,37a-37d,37f,386,388-38a,38c,38e-3a1,3a3-3f5,3f7-481,48a-52f,531-556,559,560-588,5d0-5ea,"
    "5ef-5f2,620-64a,660-669,66e-66f,671-6d3,6d5,6e5-6e6,6ee-6fc,6ff,710,712-72f,74d-7a5,7b1,7c0-7ea,"
    "7f4-7f5,7fa,800-815,81a,824,828,840-858,860-86a,870-887,889-88e,8a0-8c9,904-939,93d,950,958-961,"
    "966-96f,971-980,985-98c,98f-990,993-9a8,9aa-9b0,9b2,9b6-9b9,9bd,9ce,9dc-9dd,9df-9e1,9e6-9f1,9f4-9f9,"
    "9fc,a05-a0a,a0f-a10,a13-a28,a2a-a30,a32-a33,a35-a36,a38-a39,a59-a5c,a5e,a66-a6f,a72-a74,a85-a8d,"
    "a8f-a91,a93-aa8,aaa-ab0,ab2-ab3,ab5-ab9,abd,ad0,ae0-ae1,ae6-aef,af9,b05-b0c,b0f-b10,b13-b28,b2a-b30,"
    "b32-b33,b35-b39,b3d,b5c-b5d,b5f-b61,b66-b6f,b71-b77,b83,b85-b8a,b8e-b90,b92-b95,b99-b9a,b9c,b9e-b9f,"
    "ba3-ba4,ba8-baa,bae-bb9,bd0,be6-bf2,c05-c0c,c0e-c10,c12-c28,c2a-c39,c3d,c58-c5a,c5d,c60-c61,c66-c6f,"
    "c78-c7e,c80,c85-c8c,c8e-c90,c92-ca8,caa-cb3,cb5-cb9,cbd,cdd-cde,ce0-ce1,ce6-cef,cf1-cf2,d04-d0c,"
    "d0e-d10,d12-d3a,d3d,d4e,d54-d56,d58-d61,d66-d78,d7a-d7f,d85-d96,d9a-db1,db3-dbb,dbd,dc0-dc6,de6-def,"
    "e01-e30,e32-e33,e40-e46,e50-e59,e81-e82,e84,e86-e8a,e8c-ea3,ea5,ea7-eb0,eb2-eb3,ebd,ec0-ec4,ec6,"
    "ed0-ed9,edc-edf,f00,f20-f33,f40-f47,f49-f6c,f88-f8c,1000-102a,103f-1049,1050-1055,105a-105d,1061,"
    "1065-1066,106e-1070,1075-1081,108e,1090-1099,10a0-10c5,10c7,10cd,10d0-10fa,10fc-1248,124a-124d,"
    "1250-1256,1258,125a-125d,1260-1288,128a-128d,1290-12b0,12b2-12b5,12b8-12be,12c0,12c2-12c5,12c8-12d6,"
    "12d8-1310,1312-1315,1318-135a,1369-137c,1380-138f,13a0-13f5,13f8-13fd,1401-166c,166f-167f,1681-169a,"
    "16a0-16ea,16ee-16f8,1700-1711,171f-1731,1740-1751,1760-176c,176e-1770,1780-17b3,17d7,17dc,17e0-17e9,"
    "17f0-17f9,1810-1819,1820-1878,1880-1884,1887-18a8,18aa,18b0-18f5,1900-191e,1946-196d,1970-1974,"
    "1980-19ab,19b0-19c9,19d0-19da,1a00-1a16,1a20-1a54,1a80-1a89,1a90-1a99,1aa7,1b05-1b33,1b45-1b4c,"
    "1b50-1b59,1b83-1ba0,1bae-1be5,1c00-1c23,1c40-1c49,1c4d-1c7d,1c80-1c8a,1c90-1cba,1cbd-1cbf,1ce9-1cec,"
    "1cee-1cf3,1cf5-1cf6,1cfa,1d00-1dbf,1e00-1f15,1f18-1f1d,1f20-1f45,1f48-1f4d,1f50-1f57,1f59,1f5b,1f5d,"
    "1f5f-1f7d,1f80-1fb4,1fb6-1fbc,1fbe,1fc2-1fc4,1fc6-1fcc,1fd0-1fd3,1fd6-1fdb,1fe0-1fec,1ff2-1ff4,"
    "1ff6-1ffc,2070-2071,2074-2079,207f-2089,2090-209c,2102,2107,210a-2113,2115,2119-211d,2124,2126,2128,"
    "212a-212d,212f-2139,213c-213f,2145-2149,214e,2150-2189,2460-249b,24ea-24ff,2776-2793,2c00-2ce4,"
    "2ceb-2cee,2cf2-2cf3,2cfd,2d00-2d25,2d27,2d2d,2d30-2d67,2d6f,2d80-2d96,2da0-2da6,2da8-2dae,2db0-2db6,"
    "2db8-2dbe,2dc0-2dc6,2dc8-2dce,2dd0-2dd6,2dd8-2dde,2e2f,3005-3007,3021-3029,3031-3035,3038-303c,"
    "3041-3096,309d-309f,30a1-30fa,30fc-30ff,3105-312f,3131-318e,3192-3195,31a0-31bf,31f0-31ff,3220-3229,"
    "3248-324f,3251-325f,3280-3289,32b1-32bf,3400-4dbf,4e00-a48c,a4d0-a4fd,a500-a60c,a610-a62b,a640-a66e,"
    "a67f-a69d,a6a0-a6ef,a717-a71f,a722-a788,a78b-a7cd,a7d0-a7d1,a7d3,a7d5-a7dc,a7f2-a801,a803-a805,"
    "a807-a80a,a80c-a822,a830-a835,a840-a873,a882-a8b3,a8d0-a8d9,a8f2-a8f7,a8fb,a8fd-a8fe,a900-a925,"
    "a930-a946,a960-a97c,a984-a9b2,a9cf-a9d9,a9e0-a9e4,a9e6-a9fe,aa00-aa28,aa40-aa42,aa44-aa4b,aa50-aa59,"
    "aa60-aa76,aa7a,aa7e-aaaf,aab1,aab5-aab6,aab9-aabd,aac0,aac2,aadb-aadd,aae0-aaea,aaf2-aaf4,ab01-ab06,"
    "ab09-ab0e,ab11-ab16,ab20-ab26,ab28-ab2e,ab30-ab5a,ab5c-ab69,ab70-abe2,abf0-abf9,ac00-d7a3,d7b0-d7c6,"
    "d7cb-d7fb,f900-fa6d,fa70-fad9,fb00-fb06,fb13-fb17,fb1d,fb1f-fb28,fb2a-fb36,fb38-fb3c,fb3e,fb40-fb41,"
    "fb43-fb44,fb46-fbb1,fbd3-fd3d,fd50-fd8f,fd92-fdc7,fdf0-fdfb,fe70-fe74,fe76-fefc,ff10-ff19,ff21-ff3a,"
    "ff41-ff5a,ff66-ffbe,ffc2-ffc7,ffca-ffcf,ffd2-ffd7,ffda-ffdc,10000-1000b,1000d-10026,10028-1003a,"
    "1003c-1003d,1003f-1004d,10050-1005d,10080-100fa,10107-10133,10140-10178,1018a-1018b,10280-1029c,"
    "102a0-102d0,102e1-102fb,10300-10323,1032d-1034a,10350-10375,10380-1039d,103a0-103c3,103c8-103cf,"
    "103d1-103d5,10400-1049d,104a0-104a9,104b0-104d3,104d8-104fb,10500-10527,10530-10563,10570-1057a,"
    "1057c-1058a,1058c-10592,10594-10595,10597-105a1,105a3-105b1,105b3-105b9,105bb-105bc,105c0-105f3,"
    "10600-10736,10740-10755,10760-10767,10780-10785,10787-107b0,107b2-107ba,10800-10805,10808,"
    "1080a-10835,10837-10838,1083c,1083f-10855,10858-10876,10879-1089e,108a7-108af,108e0-108f2,"
    "108f4-108f5,108fb-1091b,10920-10939,10980-109b7,109bc-109cf,109d2-10a00,10a10-10a13,10a15-10a17,"
    "10a19-10a35,10a40-10a48,10a60-10a7e,10a80-10a9f,10ac0-10ac7,10ac9-10ae4,10aeb-10aef,10b00-10b35,"
    "10b40-10b55,10b58-10b72,10b78-10b91,10ba9-10baf,10c00-10c48,10c80-10cb2,10cc0-10cf2,10cfa-10d23,"
    "10d30-10d39,10d40-10d65,10d6f-10d85,10e60-10e7e,10e80-10ea9,10eb0-10eb1,10ec2-10ec4,10f00-10f27,"
    "10f30-10f45,10f51-10f54,10f70-10f81,10fb0-10fcb,10fe0-10ff6,11003-11037,11052-1106f,11071-11072,"
    "11075,11083-110af,110d0-110e8,110f0-110f9,11103-11126,11136-1113f,11144,11147,11150-11172,11176,"
    "11183-111b2,111c1-111c4,111d0-111da,111dc,111e1-111f4,11200-11211,11213-1122b,1123f-11240,"
    "11280-11286,11288,1128a-1128d,1128f-1129d,1129f-112a8,112b0-112de,112f0-112f9,11305-1130c,"
    "1130f-11310,11313-11328,1132a-11330,11332-11333,11335-11339,1133d,11350,1135d-11361,11380-11389,"
    "1138b,1138e,11390-113b5,113b7,113d1,113d3,11400-11434,11447-1144a,11450-11459,1145f-11461,"
    "11480-114af,114c4-114c5,114c7,114d0-114d9,11580-115ae,115d8-115db,11600-1162f,11644,11650-11659,"
    "11680-116aa,116b8,116c0-116c9,116d0-116e3,11700-1171a,11730-1173b,11740-11746,11800-1182b,"
    "118a0-118f2,118ff-11906,11909,1190c-11913,11915-11916,11918-1192f,1193f,11941,11950-11959,"
    "119a0-119a7,119aa-119d0,119e1,119e3,11a00,11a0b-11a32,11a3a,11a50,11a5c-11a89,11a9d,11ab0-11af8,"
    "11bc0-11be0,11bf0-11bf9,11c00-11c08,11c0a-11c2e,11c40,11c50-11c6c,11c72-11c8f,11d00-11d06,"
    "11d08-11d09,11d0b-11d30,11d46,11d50-11d59,11d60-11d65,11d67-11d68,11d6a-11d89,11d98,11da0-11da9,"
    "11ee0-11ef2,11f02,11f04-11f10,11f12-11f33,11f50-11f59,11fb0,11fc0-11fd4,12000-12399,12400-1246e,"
    "12480-12543,12f90-12ff0,13000-1342f,13441-13446,13460-143fa,14400-14646,16100-1611d,16130-16139,"
    "16800-16a38,16a40-16a5e,16a60-16a69,16a70-16abe,16ac0-16ac9,16ad0-16aed,16b00-16b2f,16b40-16b43,"
    "16b50-16b59,16b5b-16b61,16b63-16b77,16b7d-16b8f,16d40-16d6c,16d70-16d79,16e40-16e96,16f00-16f4a,"
    "16f50,16f93-16f9f,16fe0-16fe1,16fe3,17000-187f7,18800-18cd5,18cff-18d08,1aff0-1aff3,1aff5-1affb,"
    "1affd-1affe,1b000-1b122,1b132,1b150-1b152,1b155,1b164-1b167,1b170-1b2fb,1bc00-1bc6a,1bc70-1bc7c,"
    "1bc80-1bc88,1bc90-1bc99,1ccf0-1ccf9,1d2c0-1d2d3,1d2e0-1d2f3,1d360-1d378,1d400-1d454,1d456-1d49c,"
    "1d49e-1d49f,1d4a2,1d4a5-1d4a6,1d4a9-1d4ac,1d4ae-1d4b9,1d4bb,1d4bd-1d4c3,1d4c5-1d505,1d507-1d50a,"
    "1d50d-1d514,1d516-1d51c,1d51e-1d539,1d53b-1d53e,1d540-1d544,1d546,1d54a-1d550,1d552-1d6a5,"
    "1d6a8-1d6c0,1d6c2-1d6da,1d6dc-1d6fa,1d6fc-1d714,1d716-1d734,1d736-1d74e,1d750-1d76e,1d770-1d788,"
    "1d78a-1d7a8,1d7aa-1d7c2,1d7c4-1d7cb,1d7ce-1d7ff,1df00-1df1e,1df25-1df2a,1e030-1e06d,1e100-1e12c,"
    "1e137-1e13d,1e140-1e149,1e14e,1e290-1e2ad,1e2c0-1e2eb,1e2f0-1e2f9,1e4d0-1e4eb,1e4f0-1e4f9,"
    "1e5d0-1e5ed,1e5f0-1e5fa,1e7e0-1e7e6,1e7e8-1e7eb,1e7ed-1e7ee,1e7f0-1e7fe,1e800-1e8c4,1e8c7-1e8cf,"
    "1e900-1e943,1e94b,1e950-1e959,1ec71-1ecab,1ecad-1ecaf,1ecb1-1ecb4,1ed01-1ed2d,1ed2f-1ed3d,"
    "1ee00-1ee03,1ee05-1ee1f,1ee21-1ee22,1ee24,1ee27,1ee29-1ee32,1ee34-1ee37,1ee39,1ee3b,1ee42,1ee47,"
    "1ee49,1ee4b,1ee4d-1ee4f,1ee51-1ee52,1ee54,1ee57,1ee59,1ee5b,1ee5d,1ee5f,1ee61-1ee62,1ee64,"
    "1ee67-1ee6a,1ee6c-1ee72,1ee74-1ee77,1ee79-1ee7c,1ee7e,1ee80-1ee89,1ee8b-1ee9b,1eea1-1eea3,"
    "1eea5-1eea9,1eeab-1eebb,1f100-1f10c,1fbf0-1fbf9,20000-2a6df,2a700-2b739,2b740-2b81d,2b820-2cea1,"
    "2ceb0-2ebe0,2ebf0-2ee5d,2f800-2fa1d,30000-3134a,31350-323af"
)


def _range_table(text: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """(starts, ends) of a ranges string such as "ad,600-605"."""
    pairs = [tuple(int(end, 16) for end in item.split("-")) for item in text.split(",")]
    return tuple(pair[0] for pair in pairs), tuple(pair[-1] for pair in pairs)


_FORMAT_PRIVATE = _range_table(FORMAT_PRIVATE_RANGES)
_LETTER_DIGIT = _range_table(LETTER_DIGIT_RANGES)


def _in_table(table: tuple[tuple[int, ...], tuple[int, ...]], point: int) -> bool:
    index = bisect.bisect_right(table[0], point) - 1
    return index >= 0 and point <= table[1][index]


def _js_lower(text: str) -> str:
    """String.prototype.toLowerCase as Qt's JS engine runs it: per code point, no final-sigma rule."""
    return "".join(character.lower() for character in text)


_TAKEN_NAMES = frozenset(_js_lower(name) for name in WEB_SITE_NAMES + (OLLAMA_SITE_NAME,))


def is_user_site_id(value: object) -> bool:
    """ChatSites.js isUserSiteId: ``user-`` and 8 lower-case hex digits."""
    return isinstance(value, str) and _USER_SITE_ID.fullmatch(value) is not None


def user_site_name_error(name: object, others: tuple[str, ...] = ()) -> str:
    """ChatSites.js userSiteNameError: "" when ``name`` may be stored, else its code.

    ``others`` are the names of the other added sites. The name is checked as
    stored, so leading or trailing whitespace is ``name-chars`` (the editor trims).
    name-chars also covers controls, lone surrogates, the _NAME_FORBIDDEN characters,
    any Cf or Co character, and a name without any letter or digit (L* or N*); the
    categories come from the FORMAT_PRIVATE_RANGES and LETTER_DIGIT_RANGES tables
    (Unicode 16.0), never from the running Python's Unicode database.
    Codes, first failure wins: name-empty, name-too-long, name-chars, name-taken.
    """
    if not isinstance(name, str) or _JS_TRIM.sub("", name) == "":
        return "name-empty"
    if _utf16_length(name) > MAX_USER_SITE_NAME:
        return "name-too-long"
    if _JS_TRIM.sub("", name) != name or _CONTROL.search(name) or _NAME_FORBIDDEN.search(name):
        return "name-chars"
    if any(_in_table(_FORMAT_PRIVATE, ord(character)) for character in name):
        return "name-chars"  # Format (Cf) or private-use (Co) characters (SEC I-5).
    if not any(_in_table(_LETTER_DIGIT, ord(character)) for character in name):
        return "name-chars"  # At least one letter or digit (Unicode 16.0 L* or N*).
    lowered = _js_lower(name)
    if lowered in _TAKEN_NAMES or any(lowered == _js_lower(other) for other in others):
        return "name-taken"
    return ""


def _user_site_check(url: object) -> tuple[str, str]:
    """(code, class) of an added site's address: ("", class) when valid, (code, "") when not.

    Task 006 plan section 3.3, first failure wins:
    1-6 url-empty, too-long, whitespace, url-chars, userinfo, malformed (no scheme);
    7 scheme (neither http nor https); 8 malformed (parse_user_url);
    9 localhost, 127.0.0.1 or [::1] exactly: loopback, http or https;
    10 anything else is_local_address counts as this computer (not a bracketed
       literal): loopback-not-allowed;
    11 an IPv4 literal (last label numeric or hex): ip-form when not canonical,
       link-local in 169.254/16, private in 10/8, 172.16/12 and 192.168/16, else ip-literal;
    12 a bracketed IPv6 literal: ip-form when not canonical (or not an address),
       link-local in fe80::/10, private in fc00::/7, else ip-literal;
    13 a DNS name: http-not-allowed over http, public over https.
    """
    if not isinstance(url, str) or url == "":
        return ("url-empty", "")
    if _utf16_length(url) > MAX_CUSTOM_URL_LENGTH:
        return ("too-long", "")
    if _URL_FORBIDDEN.search(url):
        return ("whitespace", "")
    if _USER_URL_CHARS.search(url):
        return ("url-chars", "")
    authority = _AUTHORITY_PREFIX.match(url)
    if authority is not None and "@" in authority.group(1):
        return ("userinfo", "")
    scheme_match = _SCHEME_PREFIX.match(url)
    if scheme_match is None:
        return ("malformed", "")
    if scheme_match.group(1).lower() not in ("http", "https"):
        return ("scheme", "")
    parsed = parse_user_url(url)
    if parsed is None or parsed[1] == "":
        return ("malformed", "")
    scheme, host = parsed[0], parsed[1]
    if host in ("localhost", "127.0.0.1", "[::1]"):
        return ("", "loopback")
    if host.startswith("["):
        literal = host[1:-1]
        if canonical_ipv6(literal) != literal:
            return ("ip-form", "")
        first = _ipv6_groups(literal)[0]  # type: ignore[index]  # canonical, so it parses.
        if first & 0xFFC0 == 0xFE80:
            return ("link-local", "")
        if first & 0xFE00 == 0xFC00:
            return ("", "private")
        return ("ip-literal", "")
    if is_local_address(host):
        return ("loopback-not-allowed", "")
    if _NUMERIC_LABEL.fullmatch(normalize_host(host).split(".")[-1]):
        if not canonical_ipv4(host):
            return ("ip-form", "")
        first, second = (int(part) for part in host.split(".")[:2])
        if first == 169 and second == 254:
            return ("link-local", "")
        if first == 10 or (first == 172 and 16 <= second <= 31) or (first == 192 and second == 168):
            return ("", "private")
        return ("ip-literal", "")
    if scheme == "http":
        return ("http-not-allowed", "")
    return ("", "public")


def user_site_url_error(url: object) -> str:
    """ChatSites.js userSiteUrlError: "" for an address an added site may have, else its code.

    Valid (task 006): https to a public DNS name; http or https to localhost,
    127.0.0.1 or [::1]; http or https to a canonical private IP literal
    (10/8, 172.16/12, 192.168/16, fc00::/7). Codes and their order: _user_site_check.
    """
    return _user_site_check(url)[0]


def address_class(url: object) -> str:
    """ChatSites.js addressClass: "public", "loopback", "private", or "" when the address is invalid.

    Derived from the address on every use and never stored (005 rule 3).
    """
    return _user_site_check(url)[1]


def user_site_ids(value: str) -> tuple[str, ...]:
    """The ids of a ``chatUserSites`` value that ``_user_sites`` kept."""
    return tuple(entry["id"] for entry in json.loads(value))


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


def _chat_sites(value: object, added: tuple[str, ...] = ()) -> str:
    """chatSites: a JSON array of chat site ids (web sites, ollama and the ``added`` ids), none twice."""
    return _dumps(_id_list(_embedded(value), CHAT_SITE_IDS + added))


def _site_order(value: object, added: tuple[str, ...] = ()) -> str:
    """chatSiteOrder: "" (the default order) or a JSON array of chat site ids, as chatSites."""
    if _text(value) == "":
        return ""
    return _chat_sites(value, added)


def _default_site(value: object, added: tuple[str, ...] = ()) -> object:
    """chatDefaultSite: one chat site id."""
    return _choice(CHAT_SITE_IDS + added)(value)


def _middle_click(value: object, added: tuple[str, ...] = ()) -> object:
    """middleClickOpens: refresh, usage, ollama or a web site id."""
    return _choice(MIDDLE_CLICK_TARGETS + added)(value)


def _user_sites(value: object) -> str:
    """chatUserSites (task 005): a JSON array of {id, name, url}, every entry valid.

    Strict, like _custom_urls: an extra or missing key (``local``, ``icon``,
    host lists...), a bad or repeated id, a name another site has, more than
    MAX_USER_SITES entries or more than MAX_USER_SITES_CHARS drops the whole
    setting. Written again with the keys in USER_SITE_KEYS order.
    """
    if not isinstance(value, str) or _utf16_length(value) > MAX_USER_SITES_CHARS:
        raise _Bad()
    parsed = _embedded(value, MAX_USER_SITES_CHARS)
    if not isinstance(parsed, list) or len(parsed) > MAX_USER_SITES:
        raise _Bad()
    result: list[dict[str, str]] = []
    for entry in parsed:
        if not isinstance(entry, dict) or set(entry) != set(USER_SITE_KEYS):
            raise _Bad()
        site_id, name, url = (entry[key] for key in USER_SITE_KEYS)
        if not is_user_site_id(site_id) or any(site["id"] == site_id for site in result):
            raise _Bad()
        if user_site_name_error(name, tuple(site["name"] for site in result)) != "":
            raise _Bad()
        if user_site_url_error(url) != "":
            raise _Bad()
        result.append({"id": site_id, "name": name, "url": url})
    text = _dumps(result)
    if _utf16_length(text) > MAX_USER_SITES_CHARS:
        raise _Bad()
    return text


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


# Called with one value; the SITE_KEYS rules also take the added ids (validate_settings).
RULES: dict[str, Callable[..., object]] = {
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
    "chatDefaultSite": _default_site,
    "chatOllamaUrl": _ollama_address,
    "chatKeepOpen": _boolean,
    "showUsageTab": _boolean,
    "showChatTab": _boolean,
    "popupDefaultTab": _choice(POPUP_TABS),
    "popupSize": _choice(POPUP_SIZES),
    "shortcutOpens": _choice(SHORTCUT_TARGETS),
    "panelRing": _panel_ring,
    "middleClickOpens": _middle_click,
    "chatCustomUrls": _custom_urls,
    "chatUserSites": _user_sites,
    "chatSiteOrder": _site_order,
}
# The settings that may name an added site: checked after chatUserSites, with its ids.
SITE_KEYS = ("chatSites", "chatDefaultSite", "middleClickOpens", "chatSiteOrder")


def validate_settings(value: Mapping[str, object]) -> tuple[dict[str, object], int]:
    """(kept settings in BACKUP_KEYS order, number dropped).

    The one check for the applied settings export read and for the import file. Unknown and excluded
    keys are dropped, and so is a known key with a value the widget would not
    store; both count in the number dropped.

    Two passes: every key on its own, then the SITE_KEYS, which may name only
    the added ids of the chatUserSites kept in the first pass (none when that
    key is absent or was dropped). Any other ``user-`` id drops that setting.
    """
    checked: dict[str, object] = {}
    for key in BACKUP_KEYS:
        if key not in value or key in SITE_KEYS:
            continue
        try:
            checked[key] = RULES[key](value[key])
        except _Bad:
            continue
    user_sites = checked.get("chatUserSites")
    added = user_site_ids(user_sites) if isinstance(user_sites, str) else ()
    for key in SITE_KEYS:
        if key not in value:
            continue
        try:
            checked[key] = RULES[key](value[key], added)
        except _Bad:
            continue
    kept = {key: checked[key] for key in BACKUP_KEYS if key in checked}
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


def _clear_stale_temporaries(directory: int) -> None:
    """Delete temporaries a crashed export left (audit I1); never follows a link."""
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        if _TEMPORARY_NAME.fullmatch(name):
            _unlink(directory, name)


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
    applet: int,
    environ: Optional[Mapping[str, str]] = None,
    *,
    clock: Callable[[], float] = time.time,
) -> dict[str, object]:
    """Replace the backup with widget ``applet``'s applied settings, checked.

    Only what Plasma has saved counts (press Apply first); a key the rc file
    lacks has its main.xml default. Read only on the rc file.
    """
    if type(applet) is not int or applet < 1:
        raise HelperError("applet-not-found")
    settings, dropped = validate_settings(applied_settings(applet, BACKUP_KEYS, config_base(environ)))
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
        _clear_stale_temporaries(directory)
        _write_file(directory, encoded)
    return {"ok": True, "saved": len(settings), "dropped": dropped}


def import_settings(environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    """The backup's checked settings; the widget applies them only after Replace and Apply."""
    exported_at, settings, dropped = _load(environ)
    return {"ok": True, "exported_at": exported_at, "settings": settings, "dropped": dropped}


def run(
    operation: str,
    *,
    applet: Optional[int] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> dict[str, object]:
    """CLI entry: a reply that never carries a path. ``applet`` is export's (others ignore it)."""
    try:
        if operation == "status":
            return status(environ)
        if operation == "export":
            if applet is None:
                raise ValueError("export needs an applet id.")
            return export(applet, environ)
        if operation == "import":
            return import_settings(environ)
        raise ValueError("Unsupported settings backup operation.")
    except HelperError as error:
        return {"ok": False, "error": error.code if error.code in ERRORS else "os-error"}
    except OSError:
        return {"ok": False, "error": "os-error"}


__all__ = ["BACKUP_KEYS", "EXCLUDED_KEYS", "OPERATIONS", "run", "validate_settings"]
