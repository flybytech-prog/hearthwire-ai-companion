"""Read the hearthwire-hyprland app's applied settings for a backup (task 011).

The app keeps its settings in its own file instead of Plasma's rc files::

    $XDG_CONFIG_HOME (when absolute, else ~/.config)/
        hearthwire-hyprland/         0700, written only by the app
            settings.json            0600, replaced atomically by the app

    {"format":"hearthwire-app-settings","version":1,
     "settings":{"<main.xml key>": <Bool|Int|String as in main.xml>, ...},
     "app":{"background":false,"agentsPanel":false,"tray":false}}

``--settings-backup export --applet 2147483648`` (app mode only) reads it
here, read only, under the same rules as core/appletconfig.py and stricter:
the folder and the file are opened without following links and must be ours;
the folder's permission bits must be 0700 or stricter and the file's 0600 or
stricter (no group or other bit at all, not even read); and the file must be
a regular file of at most ``MAX_FILE_BYTES``; anything else is
``settings-unreadable``. A
missing folder or file, or a file that is not exactly this format, is
``bad-data`` (an export never replaces a backup with defaults). The JSON is
read with settingsbackup.strict_loads (no duplicate keys, NaN, Infinity or
deep nesting).

Only the main.xml keys of ``appletconfig.CONFIG_ENTRIES`` are read (kept
equal to main.xml by tests/test_app_config_sync.py): a key that is not there
takes its main.xml default, an unknown key is ignored, and a value of the
wrong JSON type (a Bool must be true/false, an Int a 32-bit integer, a String
a string) is ``UNREADABLE``, which the backup drops and counts. The ``app``
object (background, Agents panel, tray) is never read into a backup.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

from .appletconfig import CONFIG_ENTRIES, UNREADABLE, read_rc
from .frontend import APP_NAME
from .webdata import HelperError, _descriptors, open_base, open_child_dir

APP_DIR = APP_NAME
SETTINGS_FILE = "settings.json"
FORMAT = "hearthwire-app-settings"
VERSION = 1
# The app's writer refuses to save more than this.
MAX_FILE_BYTES = 1024 * 1024
REQUIRED_KEYS = ("format", "version", "settings")
OPTIONAL_KEYS = ("app",)
INT_MIN = -(2**31)
INT_MAX = 2**31 - 1

# Permission bits the app's writer sets; any bit beyond them (a group or
# other read included) is settings-unreadable. Set-id and sticky bits are not
# permission bits (a setgid parent passes its bit to a new folder).
FOLDER_MODE_MAX = 0o700
FILE_MODE_MAX = 0o600


def _too_open(mode: int, allowed: int) -> bool:
    """Any permission bit of ``mode`` beyond ``allowed``."""
    return bool(mode & 0o777 & ~allowed)


def typed_value(kind: str, value: object) -> object:
    """``value`` when it has main.xml ``kind``'s JSON type, else UNREADABLE."""
    if kind == "Bool":
        return value if type(value) is bool else UNREADABLE
    if kind == "Int":
        return value if type(value) is int and INT_MIN <= value <= INT_MAX else UNREADABLE
    if kind == "String":
        return value if type(value) is str else UNREADABLE
    return UNREADABLE


def parse_document(data: bytes) -> dict[str, object]:
    """The ``settings`` object of a settings.json's bytes; ``bad-data`` unless it is exactly the format."""
    from .settingsbackup import strict_loads  # Imported here: settingsbackup builds on this module.

    try:
        document = strict_loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise HelperError("bad-data") from None
    if not isinstance(document, dict) or not set(REQUIRED_KEYS) <= set(document) \
            or not set(document) <= set(REQUIRED_KEYS + OPTIONAL_KEYS):
        raise HelperError("bad-data")
    if document["format"] != FORMAT or type(document["version"]) is not int or document["version"] != VERSION:
        raise HelperError("bad-data")
    if not isinstance(document["settings"], dict) or not isinstance(document.get("app", {}), dict):
        raise HelperError("bad-data")
    return document["settings"]


def applied_from(settings: Mapping[str, object], keys: Iterable[str]) -> dict[str, object]:
    """``keys`` (each a CONFIG_ENTRIES name) as the app applies them."""
    result: dict[str, object] = {}
    for key in keys:
        kind, default = CONFIG_ENTRIES[key]
        result[key] = typed_value(kind, settings[key]) if key in settings else default
    return result


def _unreadable(error: HelperError) -> HelperError:
    return HelperError("os-error" if error.code == "os-error" else "settings-unreadable")


def applied_settings(keys: Iterable[str], config_base: str) -> dict[str, object]:
    """The app's applied value of each of ``keys``, read from ``<config_base>/hearthwire-hyprland/settings.json``.

    ``bad-data`` when the folder or file is missing or the file is not the
    format; ``settings-unreadable`` when a link, not ours, not a regular file
    or directory, more open than 0700 (folder) or 0600 (file), or too large; ``os-error``
    otherwise. Never writes anything.
    """
    with _descriptors() as opened:
        try:
            base = open_base(config_base, create=False)
        except HelperError as error:
            raise _unreadable(error) from None
        if base is None:
            raise HelperError("bad-data")
        opened.append(base)
        try:
            directory = open_child_dir(base, APP_DIR, create=False)
        except HelperError as error:
            raise _unreadable(error) from None
        if directory is None:
            raise HelperError("bad-data")
        opened.append(directory)
        try:
            folder_mode = os.fstat(directory).st_mode
        except OSError:
            raise HelperError("os-error") from None
        if _too_open(folder_mode, FOLDER_MODE_MAX):
            raise HelperError("settings-unreadable")
        try:
            current = read_rc(directory, SETTINGS_FILE, MAX_FILE_BYTES)
        except HelperError as error:
            raise _unreadable(error) from None
        if current is None:
            raise HelperError("bad-data")
        data, info = current
        if _too_open(info.st_mode, FILE_MODE_MAX):
            raise HelperError("settings-unreadable")
    return applied_from(parse_document(data), keys)


__all__ = ["APP_DIR", "FILE_MODE_MAX", "FOLDER_MODE_MAX", "FORMAT", "MAX_FILE_BYTES", "SETTINGS_FILE", "VERSION",
           "applied_settings", "parse_document", "typed_value"]
