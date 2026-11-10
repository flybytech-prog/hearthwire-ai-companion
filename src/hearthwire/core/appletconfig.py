"""Read one widget's applied settings from Plasma's own rc file (audit fix M1).

``--settings-backup export --applet N`` used to get the settings in argv,
where every local user can read them through /proc. Now the helper reads
them itself, read only, from

    $XDG_CONFIG_HOME (when absolute, else ~/.config)/
        plasma-org.kde.plasma.desktop-appletsrc     the desktop and panels
        plasmawindowedrc                            plasmawindowed, tried only
                                                    when the first file is
                                                    missing or has no such widget

group ``[Containments][C][Applets][N][Configuration][General]``, where the
widget ``[Containments][C][Applets][N]`` must say ``plugin=<our id>``. C is
any containment; N must name exactly one widget in the file (two are
``applet-not-found``: nothing is guessed). A key that is not there takes its
``main.xml`` default from ``CONFIG_ENTRIES`` (kept equal to main.xml by
tests/test_applet_config_sync.py), so the result is what the widget applies.

Values are decoded exactly as KConfig decodes them (``\\s \\t \\n \\r \\\\ \\xHH``;
``\\;`` and ``\\,`` stay as written). Keys with a suffix such as a locale
(``key[de]``) or ``[$e]`` (shell expansion) are ignored, never trusted. A
value that is not UTF-8, or a Bool or Int in a spelling KConfig does not
write, is ``UNREADABLE``: the backup drops and counts it.

The rc file is opened without following links and must be a regular file of
ours of at most ``MAX_RC_BYTES``; it is never written.
"""

from __future__ import annotations

import errno
import os
import re
import stat
from collections.abc import Iterable, Mapping
from typing import Optional

from .webdata import HelperError, _close, _descriptors, open_base

APPLETSRC = "plasma-org.kde.plasma.desktop-appletsrc"
WINDOWED_RC = "plasmawindowedrc"
RC_FILES = (APPLETSRC, WINDOWED_RC)
PLUGIN = "io.github.flybytechprog.hearthwire"
# A desktop with many widgets stays far below this; a bigger file is refused.
MAX_RC_BYTES = 4 * 1024 * 1024

# Every main.xml entry of group General: name -> (type, default). Bool, Int and
# String are the only types main.xml uses.
CONFIG_ENTRIES: dict[str, tuple[str, object]] = {
    "trackedProviders": ("String", '["claude","codex","cursor","antigravity","copilot","devin","grok"]'),
    "providerMetrics": ("String", "{}"),
    "usageMode": ("String", "remaining"),
    "refreshInterval": ("Int", 300),
    "configSchemaVersion": ("Int", 2),
    "initialSetupComplete": ("Bool", False),
    "chatSites": ("String", '["claude","chatgpt","grok","gemini","copilot","mscopilot"]'),
    "chatDefaultSite": ("String", "claude"),
    "chatCustomUrls": ("String", "{}"),
    "chatSignInStorage": ("String", "memory"),
    "chatProfileGeneration": ("Int", 0),
    "chatAutoLockMinutes": ("Int", 0),
    "chatVaultUnlock": ("String", "passphrase"),
    "chatKeepOpen": ("Bool", False),
    "chatOllamaUrl": ("String", "http://127.0.0.1:11434"),
    "popupDefaultTab": ("String", "chat"),
    "showUsageTab": ("Bool", True),
    "showChatTab": ("Bool", True),
    "popupSize": ("String", "normal"),
    "tooltipShowsUsage": ("Bool", True),
    "tooltipMetrics": ("String", ""),
    "shortcutOpens": ("String", "popup"),
    "chatSiteZoom": ("String", "{}"),
    "alertLowEnabled": ("Bool", False),
    "alertLowPercent": ("Int", 20),
    "alertResetEnabled": ("Bool", False),
    "providerOrder": ("String", ""),
    "usageCompact": ("Bool", False),
    "usageWarnPercent": ("Int", 60),
    "usageCriticalPercent": ("Int", 85),
    "usageNormalColor": ("String", ""),
    "usageWarnColor": ("String", ""),
    "usageCriticalColor": ("String", ""),
    "panelRing": ("String", "auto"),
    "middleClickOpens": ("String", "refresh"),
    "usageHistoryEnabled": ("Bool", False),
    "usageHistoryClearOwed": ("Bool", False),
}


class _Unreadable:
    """A value present in the rc file that cannot be taken as it is (fails every backup rule)."""

    def __repr__(self) -> str:
        return "UNREADABLE"


UNREADABLE = _Unreadable()

_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOCTTY
_GROUP_HEADER = re.compile(rb"(?:\[[^\[\]\n]*\])+")
_APPLET_GROUP = re.compile(rb"\[Containments\]\[([0-9]+)\]\[Applets\]\[([0-9]+)\]((?:\[[^\[\]\n]*\])*)")
_CONFIG_SUFFIX = b"[Configuration][General]"
_PLAIN_KEY = re.compile(rb"[A-Za-z0-9_.\-]+")
_HEX_DIGITS = b"0123456789abcdefABCDEF"
_INT_TEXT = re.compile(r"[+-]?[0-9]{1,10}")
_TRUE_WORDS = ("true", "on", "yes", "1")
_FALSE_WORDS = ("false", "off", "no", "0")  # KConfig's negatives.


# --- the file -----------------------------------------------------------------------------------


def read_rc(directory: int, name: str, max_bytes: int) -> Optional[tuple[bytes, os.stat_result]]:
    """The bytes of ``name`` below ``directory`` and the fstat of what was read; None when missing.

    Shared with legacy.py (the one-time appletsrc rewrite).

    Never follows a link (``symlink``); a directory is ``not-directory``,
    another non-regular file or one over ``max_bytes`` is ``invalid``, a
    file of someone else ``not-owned``. Opened read only and never changed.
    """
    try:
        descriptor = os.open(name, _READ_FLAGS, dir_fd=directory)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise HelperError("symlink" if error.errno == errno.ELOOP else "os-error") from None
    try:
        info = os.fstat(descriptor)
        if stat.S_ISDIR(info.st_mode):
            raise HelperError("not-directory")
        if not stat.S_ISREG(info.st_mode):
            raise HelperError("invalid")
        if info.st_uid != os.getuid():
            raise HelperError("not-owned")
        if info.st_size > max_bytes:
            raise HelperError("invalid")
        chunks = []
        size = 0
        while size <= max_bytes:
            chunk = os.read(descriptor, min(1 << 20, max_bytes + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > max_bytes:
            raise HelperError("invalid")
        return b"".join(chunks), info
    except OSError:
        raise HelperError("os-error") from None
    finally:
        _close(descriptor)


# --- KConfig syntax -----------------------------------------------------------------------------


def decode_value(raw: bytes) -> bytes:
    """KConfigIniBackend::printableToString, byte for byte.

    ``\\s`` space, ``\\t``, ``\\n``, ``\\r``, ``\\\\``, ``\\xHH`` one byte; ``\\;`` and
    ``\\,`` stay as written; a bad ``\\x`` gives ``x``; any other escape keeps
    its backslash, and so does a backslash at the end.
    """
    if b"\\" not in raw:
        return raw
    result = bytearray()
    index, length = 0, len(raw)
    while index < length:
        byte = raw[index:index + 1]
        if byte != b"\\":
            result += byte
            index += 1
            continue
        index += 1
        if index >= length:
            result += b"\\"
            break
        escaped = raw[index:index + 1]
        if escaped == b"s":
            result += b" "
        elif escaped == b"t":
            result += b"\t"
        elif escaped == b"n":
            result += b"\n"
        elif escaped == b"r":
            result += b"\r"
        elif escaped == b"\\":
            result += b"\\"
        elif escaped in (b";", b","):
            result += b"\\" + escaped
        elif escaped == b"x":
            digits = raw[index + 1:index + 3]
            if len(digits) == 2 and all(digit in _HEX_DIGITS for digit in digits):
                result.append(int(digits, 16))
                index += 2
            else:
                result += b"x"
        else:
            result += b"\\" + escaped
        index += 1
    return bytes(result)


def _groups(content: bytes) -> Iterable[tuple[Optional[bytes], bytes, bytes]]:
    """(group header or None, key, raw value) for each plain ``key=value`` line.

    Lines are trimmed like KConfig trims them; comments and lines without
    ``=`` are skipped; a malformed header starts a group nobody reads; keys
    with a suffix (``key[de]``, ``key[$e]``, ``key[$i]``) are left out.
    """
    group: Optional[bytes] = None
    for line in content.split(b"\n"):
        line = line.strip()
        if not line or line.startswith(b"#"):
            continue
        if line.startswith(b"["):
            group = line if _GROUP_HEADER.fullmatch(line) else None
            continue
        key, separator, value = line.partition(b"=")
        if not separator:
            continue
        key = key.strip()
        if not _PLAIN_KEY.fullmatch(key):
            continue
        yield group, key, value.strip()


def _same_id(text: bytes, applet: int) -> bool:
    """Plasma reads the group name as a number, so leading zeros name the same widget."""
    return (text.lstrip(b"0") or b"0") == str(applet).encode("ascii")


def find_applet(content: bytes, applet: int) -> Optional[dict[bytes, bytes]]:
    """The raw General entries of widget ``applet`` (last line wins), None when it isn't there.

    ``applet-not-found`` when two widgets of the file carry the id (in two
    containments, or spelled with leading zeros), or the one that does is
    not ours.
    """
    owners: set[tuple[bytes, bytes]] = set()
    plugin: Optional[bytes] = None
    entries: dict[bytes, bytes] = {}
    for line in content.split(b"\n"):
        line = line.strip()
        if line.startswith(b"[") and _GROUP_HEADER.fullmatch(line):
            match = _APPLET_GROUP.fullmatch(line)
            if match is not None and _same_id(match.group(2), applet):
                owners.add((match.group(1), match.group(2)))
    if not owners:
        return None
    if len(owners) > 1:
        raise HelperError("applet-not-found")
    for group, key, value in _groups(content):
        match = None if group is None else _APPLET_GROUP.fullmatch(group)
        if match is None or (match.group(1), match.group(2)) not in owners:
            continue
        if match.group(3) == b"" and key == b"plugin":
            plugin = decode_value(value)
        elif match.group(3) == _CONFIG_SUFFIX:
            entries[key] = value
    if plugin != PLUGIN.encode("ascii"):
        raise HelperError("applet-not-found")
    return entries


def typed_value(kind: str, raw: bytes) -> object:
    """The value KConfig would hand the widget for a main.xml ``kind``, or UNREADABLE."""
    try:
        text = decode_value(raw).decode("utf-8")
    except UnicodeDecodeError:
        return UNREADABLE
    if kind == "String":
        return text
    if kind == "Int":
        return int(text, 10) if _INT_TEXT.fullmatch(text) else UNREADABLE
    if kind == "Bool":
        lowered = text.lower()
        if lowered in _TRUE_WORDS:
            return True
        if lowered in _FALSE_WORDS:
            return False
        return UNREADABLE
    return UNREADABLE


def applied_from(entries: Mapping[bytes, bytes], keys: Iterable[str]) -> dict[str, object]:
    """``keys`` (each a CONFIG_ENTRIES name) as the widget applies them."""
    result: dict[str, object] = {}
    for key in keys:
        kind, default = CONFIG_ENTRIES[key]
        raw = entries.get(key.encode("ascii"))
        result[key] = default if raw is None else typed_value(kind, raw)
    return result


# --- the operation ------------------------------------------------------------------------------


def applied_settings(
    applet: int,
    keys: Iterable[str],
    config_base: str,
) -> dict[str, object]:
    """The applied value of each of ``keys`` for widget ``applet``.

    ``applet-not-found`` when no rc file has exactly one such widget of ours;
    ``settings-unreadable`` when an rc file is a symlink, not a regular file,
    someone else's, or too large; ``os-error`` otherwise.
    """
    with _descriptors() as opened:
        try:
            directory = open_base(config_base, create=False)
        except HelperError as error:
            raise HelperError("os-error" if error.code == "os-error" else "settings-unreadable") from None
        if directory is None:
            raise HelperError("applet-not-found")
        opened.append(directory)
        for name in RC_FILES:
            try:
                current = read_rc(directory, name, MAX_RC_BYTES)
            except HelperError as error:
                raise HelperError("os-error" if error.code == "os-error" else "settings-unreadable") from None
            if current is None:
                continue
            entries = find_applet(current[0], applet)
            if entries is not None:
                return applied_from(entries, keys)
    raise HelperError("applet-not-found")


__all__ = ["APPLETSRC", "CONFIG_ENTRIES", "PLUGIN", "RC_FILES", "UNREADABLE", "applied_settings",
           "decode_value", "find_applet", "read_rc"]
