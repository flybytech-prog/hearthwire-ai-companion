"""Private folders for the Chat tab's opt-in saved sign-ins.

The plasmoid passes only an applet id and a profile generation. The helper
creates or deletes ``web/applet-<N>-g<G>/`` inside the verified gocryptfs mount
(store ``encrypted``, see ``vault.py``). There is no unencrypted store: Qt
WebEngine keeps cookies and site storage in plaintext, so a saved sign-in may
only ever live inside the encrypted folder. Every directory is opened one
component at a time relative to its parent's descriptor with ``O_NOFOLLOW``,
so a symlink planted anywhere in our part of the tree is refused rather than
followed. Results are short error codes only: never paths, names or counts.
"""

from __future__ import annotations

import errno
import os
import re
import shutil
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

# Only "encrypted"; --store stays so the CLI contract can grow later.
STORES = ("encrypted",)
APP_DIR = "hearthwire"
WEB_DIR = "web"
PRIVATE_MODE = 0o700

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class HelperError(Exception):
    """A failure reported to the plasmoid as ``{"ok":false,"error":code}``."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def profile_name(applet: int, generation: int) -> str:
    return f"applet-{applet}-g{generation}"


def _profile_pattern(applet: int) -> re.Pattern[str]:
    # Only names this helper creates: no leading zeros, nothing around them.
    return re.compile(rf"applet-{applet}-g(0|[1-9][0-9]*)")


def data_base(environ: Optional[Mapping[str, str]] = None) -> str:
    """``$XDG_DATA_HOME`` when it is absolute, else ``~/.local/share``."""
    values = os.environ if environ is None else environ
    configured = values.get("XDG_DATA_HOME") or ""
    if configured and os.path.isabs(configured):
        return configured
    return str(Path.home() / ".local" / "share")


def _close(descriptor: Optional[int]) -> None:
    if descriptor is not None and descriptor >= 0:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _open_error(error: OSError) -> HelperError:
    if error.errno == errno.ELOOP:
        return HelperError("symlink")
    if error.errno == errno.ENOTDIR:
        return HelperError("not-directory")
    return HelperError("os-error")


def open_base(base: str, *, create: bool) -> Optional[int]:
    """Open the user's data base directory, or None when it does not exist.

    The base itself is the user's own choice (it may be a symlink, e.g. on
    image-based systems), so it is followed; it must still be ours.
    """
    try:
        if create:
            os.makedirs(base, PRIVATE_MODE, exist_ok=True)
        descriptor = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except FileNotFoundError:
        if create:
            raise HelperError("os-error") from None
        return None
    except OSError as error:
        raise _open_error(error) from None
    try:
        info = os.fstat(descriptor)
    except OSError:
        _close(descriptor)
        raise HelperError("os-error") from None
    if info.st_uid != os.getuid():
        _close(descriptor)
        raise HelperError("not-owned")
    return descriptor


def open_child_dir(
    parent: int,
    name: str,
    *,
    create: bool,
    mode: int = PRIVATE_MODE,
) -> Optional[int]:
    """Open ``name`` below ``parent`` without following links.

    With ``create`` the directory is made (``mode``) when missing and an
    existing one is reset to ``mode``. Without it a missing directory gives
    None and nothing is changed. Symlinks, non-directories and directories
    owned by someone else are refused.
    """
    if create:
        try:
            os.mkdir(name, mode, dir_fd=parent)
        except FileExistsError:
            pass
        except OSError:
            raise HelperError("os-error") from None
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        if create:
            raise HelperError("os-error") from None
        return None
    except OSError:
        raise HelperError("os-error") from None
    if stat.S_ISLNK(info.st_mode):
        raise HelperError("symlink")
    if not stat.S_ISDIR(info.st_mode):
        raise HelperError("not-directory")
    if info.st_uid != os.getuid():
        raise HelperError("not-owned")
    try:
        descriptor = os.open(name, _DIR_FLAGS, dir_fd=parent)
    except OSError as error:
        raise _open_error(error) from None
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            # Swapped between the check and the open.
            raise HelperError("symlink")
        if opened.st_uid != os.getuid():
            raise HelperError("not-owned")
        if create and stat.S_IMODE(opened.st_mode) != mode:
            os.fchmod(descriptor, mode)
    except HelperError:
        _close(descriptor)
        raise
    except OSError:
        _close(descriptor)
        raise HelperError("os-error") from None
    return descriptor


@contextmanager
def _descriptors() -> Iterator[list[int]]:
    opened: list[int] = []
    try:
        yield opened
    finally:
        for descriptor in reversed(opened):
            _close(descriptor)


def _require_safe_rmtree() -> None:
    if not getattr(shutil.rmtree, "avoids_symlink_attacks", False):
        raise HelperError("os-error")


def remove_entry(parent: int, name: str) -> None:
    """Delete ``name`` below ``parent``; a symlink is unlinked, never followed."""
    _require_safe_rmtree()
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError:
        raise HelperError("os-error") from None
    try:
        if stat.S_ISDIR(info.st_mode):
            if info.st_uid != os.getuid():
                raise HelperError("not-owned")
            shutil.rmtree(name, dir_fd=parent)
        else:
            os.unlink(name, dir_fd=parent)
    except FileNotFoundError:
        return
    except OSError:
        raise HelperError("os-error") from None


def _remove_profiles(web: int, applet: int, keep: Optional[int]) -> None:
    pattern = _profile_pattern(applet)
    try:
        names = os.listdir(web)
    except OSError:
        raise HelperError("os-error") from None
    for name in sorted(names):
        match = pattern.fullmatch(name)
        if match is None:
            continue
        if keep is not None and int(match.group(1)) == keep:
            continue
        remove_entry(web, name)


# --- store "encrypted": <verified gocryptfs mount>/web ---------------------------------


def _prepare_encrypted(applet: int, generation: int, environ: Optional[Mapping[str, str]]) -> None:
    from . import vault

    with vault.verified_mount(environ) as root, _descriptors() as opened:
        parent = root
        for name in (WEB_DIR, profile_name(applet, generation)):
            parent = open_child_dir(parent, name, create=True)
            opened.append(parent)


def _remove_encrypted(applet: int, keep: Optional[int], environ: Optional[Mapping[str, str]]) -> None:
    from . import vault

    _require_safe_rmtree()
    with vault.verified_mount(environ) as root, _descriptors() as opened:
        web = open_child_dir(root, WEB_DIR, create=False)
        if web is None:
            return
        opened.append(web)
        _remove_profiles(web, applet, keep)


def prepare(
    store: str,
    applet: int,
    generation: int,
    environ: Optional[Mapping[str, str]] = None,
) -> None:
    """Create the private profile folder for one applet and generation."""
    if store != "encrypted":
        raise ValueError("Unsupported web data store.")
    _prepare_encrypted(applet, generation, environ)


def remove(
    store: str,
    applet: int,
    keep: Optional[int] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> None:
    """Delete one applet's profile folders except generation ``keep``.

    A missing tree counts as success; the folder must still be unlocked and
    verified.
    """
    if store != "encrypted":
        raise ValueError("Unsupported web data store.")
    _remove_encrypted(applet, keep, environ)


def run(
    operation: str,
    store: str,
    applet: int,
    generation: Optional[int] = None,
    keep: Optional[int] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> dict[str, object]:
    """CLI entry: a reply object that never contains a path or name."""
    try:
        if operation == "prepare":
            if generation is None:
                raise ValueError("prepare needs a generation.")
            prepare(store, applet, generation, environ)
        elif operation == "remove":
            remove(store, applet, keep, environ)
        else:
            raise ValueError("Unsupported web data operation.")
    except HelperError as error:
        return {"ok": False, "error": error.code}
    except OSError:
        return {"ok": False, "error": "os-error"}
    return {"ok": True}
