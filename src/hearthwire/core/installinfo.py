"""``hearthwire --install-info``: which Hearthwire copies are installed where.

A script install (``pip install --user``, ``kpackagetool6 -i``) puts the helper
in the user site-packages and the widget in ``$XDG_DATA_HOME/plasma/plasmoids``.
Both win over a system package, so an older script copy keeps running after
the package is installed. The widget asks this once at start to say so, and
to pick the package names of the distribution for its install hints.

Read only: no package is imported (``PathFinder.find_spec`` per directory),
nothing is written or started, no network is used. The reply holds fixed
words and booleans only, never a path, version or file text.
"""

from __future__ import annotations

import os
import re
import site
import stat
import sys
from collections.abc import Iterable
from importlib.machinery import PathFinder
from pathlib import Path

INSTALL_INFO_VERSION = 1
PACKAGE = "hearthwire"
PLUGIN_ID = "io.github.flybytechprog.hearthwire"
# The package directory of the running helper (src/hearthwire or site-packages/hearthwire).
PACKAGE_DIRECTORY = Path(__file__).resolve().parent.parent

# /etc/os-release, and only when it does not exist /usr/lib/os-release (os-release(5)).
OS_RELEASE_PATHS = ("/etc/os-release", "/usr/lib/os-release")
# The file (after following links) must be inside one of these.
OS_RELEASE_ROOTS = ("/etc", "/usr/lib")
MAX_OS_RELEASE_BYTES = 64 * 1024
DEFAULT_DATA_DIRS = ("/usr/local/share", "/usr/share")

HELPER_PLACES = ("user", "system", "other")
DISTROS = ("arch", "fedora", "debian", "other")
# ID first, then each ID_LIKE word in order; the first known word wins.
DISTRO_IDS = {
    "arch": "arch", "cachyos": "arch", "manjaro": "arch", "endeavouros": "arch",
    "fedora": "fedora",
    "debian": "debian", "ubuntu": "debian", "kubuntu": "debian", "neon": "debian",
}

_ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)")
_UNQUOTED = re.compile(r"[^\s\"'\\`$]*")
_ESCAPE = re.compile(r"\\.")
# os-release(5): ID and the ID_LIKE words are lower-case a-z, 0-9, ".", "_" and "-".
_ID_WORD = re.compile(r"[a-z0-9._-]+")


def run() -> dict[str, object]:
    user_site, system_sites = site_directories()
    user_data, system_data = data_directories()
    return {
        "ok": True,
        "install_info_version": INSTALL_INFO_VERSION,
        "helper": helper_place(PACKAGE_DIRECTORY, user_site, system_sites),
        "system_helper": any(has_package(directory) for directory in system_sites),
        "user_helper": user_site is not None and has_package(user_site),
        "user_plasmoid": user_data is not None and has_plasmoid(user_data),
        "system_plasmoid": any(has_plasmoid(directory) for directory in system_data),
        "distro": distro(),
    }


# --- the helper ---------------------------------------------------------------------------------


def _current_directory() -> str | None:
    try:
        return os.path.realpath(os.getcwd())
    except OSError:
        return None


def _usable(paths: Iterable[str]) -> list[str]:
    """Absolute paths, resolved, without duplicates; empty, relative and the current directory dropped."""
    current = _current_directory()
    result = []
    for path in paths:
        if not isinstance(path, str) or not path or not os.path.isabs(path):
            continue
        real = os.path.realpath(path)
        if real != current and real not in result:
            result.append(real)
    return result


def site_directories() -> tuple[str | None, list[str]]:
    """The user site directory and the system site directories.

    Taken from ``site`` whether or not they are on ``sys.path`` (``python3 -s``
    or a venv still sees the copies there). The system ones are those of the
    base interpreter, so a venv's own site-packages is not one of them.
    """
    users = _usable([site.getusersitepackages()])
    user = users[0] if users else None
    candidates = list(site.getsitepackages([sys.base_prefix, sys.base_exec_prefix]))
    if sys.prefix == sys.base_prefix:
        candidates += site.getsitepackages()
    return user, [directory for directory in _usable(candidates) if directory != user]


def has_package(directory: str) -> bool:
    """A regular ``hearthwire`` package in ``directory``, found without importing it."""
    try:
        spec = PathFinder.find_spec(PACKAGE, [directory])
    except (ImportError, OSError, ValueError):
        return False
    return spec is not None and spec.origin is not None and spec.submodule_search_locations is not None


def helper_place(package_directory: Path, user_site: str | None, system_sites: list[str]) -> str:
    """``user``, ``system`` or ``other`` (a checkout, a venv, a PYTHONPATH entry...)."""
    parent = os.path.realpath(package_directory.parent)
    if user_site is not None and parent == user_site:
        return "user"
    if parent in system_sites:
        return "system"
    return "other"


# --- the widget ---------------------------------------------------------------------------------


def data_directories() -> tuple[str | None, list[str]]:
    """$XDG_DATA_HOME (default ~/.local/share) and $XDG_DATA_DIRS (default
    /usr/local/share:/usr/share), absolute entries only. A data dir that is the
    data home itself is not a system one."""
    environment = os.environ
    value = environment.get("XDG_DATA_HOME", "")
    if not os.path.isabs(value):
        home = environment.get("HOME", "")
        value = os.path.join(home, ".local", "share") if os.path.isabs(home) else ""
    homes = _usable([value])
    user = homes[0] if homes else None
    entries = [entry for entry in environment.get("XDG_DATA_DIRS", "").split(":") if os.path.isabs(entry)]
    system = _usable(entries or DEFAULT_DATA_DIRS)
    return user, [directory for directory in system if directory != user]


def has_plasmoid(data_directory: str) -> bool:
    path = os.path.join(data_directory, "plasma", "plasmoids", PLUGIN_ID, "metadata.json")
    try:
        return stat.S_ISREG(os.stat(path).st_mode)
    except (OSError, ValueError):
        return False


# --- the distribution ---------------------------------------------------------------------------


def _inside_roots(real: str) -> bool:
    for root in OS_RELEASE_ROOTS:
        resolved = os.path.realpath(root)
        if real.startswith(resolved.rstrip("/") + "/"):
            return True
    return False


def read_os_release() -> bytes | None:
    """The first os-release file that exists; None if it is refused or unreadable.

    Links are followed only to a file inside /etc or /usr/lib; it must be a
    regular file of at most 64 KiB.
    """
    for path in OS_RELEASE_PATHS:
        real = os.path.realpath(path)
        if not _inside_roots(real):
            return None
        try:
            descriptor = os.open(real, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC)
        except FileNotFoundError:
            continue
        except OSError:
            return None
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                return None
            chunks = []
            size = 0
            while size <= MAX_OS_RELEASE_BYTES:
                chunk = os.read(descriptor, MAX_OS_RELEASE_BYTES + 1 - size)
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
        except OSError:
            return None
        finally:
            os.close(descriptor)
        if size > MAX_OS_RELEASE_BYTES:
            return None
        return b"".join(chunks)
    return None


def parse_os_release(data: bytes) -> dict[str, str] | None:
    """KEY=value lines, comments and blank lines; quotes stripped. Anything
    else (not UTF-8, a NUL, any other line) refuses the whole file."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if "\0" in text:
        return None
    values = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ASSIGNMENT.fullmatch(line)
        if match is None:
            return None
        key, value = match.groups()
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            quote, value = value[0], value[1:-1]
            # Inside double quotes a quote must be escaped; single quotes have no escapes.
            unescaped = _ESCAPE.sub("", value) if quote == '"' else value
            if quote in unescaped or (quote == '"' and unescaped.endswith("\\")):
                return None
        elif not _UNQUOTED.fullmatch(value):
            return None
        values[key] = value
    return values


def distro_family(values: dict[str, str]) -> str:
    words = [values.get("ID", "")] + values.get("ID_LIKE", "").split()
    for word in words:
        if _ID_WORD.fullmatch(word) and word in DISTRO_IDS:
            return DISTRO_IDS[word]
    return "other"


def distro() -> str:
    data = read_os_release()
    values = parse_os_release(data) if data is not None else None
    return distro_family(values) if values is not None else "other"
