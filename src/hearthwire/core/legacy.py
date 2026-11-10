"""One-time move from the product's former name (Hearthside) to Hearthwire.

Only the installer runs this (``hearthwire --migrate status|run|applets|rollback``,
plan D1-D8); the widget never does. It is the only Python file that holds the
former name and plugin id, so a grep proves nothing else still uses them.

What moves, in reply order (categories):

- ``data``: ``$XDG_DATA_HOME/<old>`` becomes ``.../hearthwire`` by one rename(2):
  the encrypted folder, its key slots and the usage history, never copied.
- ``config``: ``$XDG_CONFIG_HOME/<old>`` (the settings backup) likewise.
- ``notifyrc``: the user's notification choices ``$XDG_CONFIG_HOME/<old>.notifyrc``;
  when the new file already exists it is kept and the old one dropped.
- ``cache``: the Antigravity token cache is deleted, not moved (D7).
- ``wallet-entry``: only when the moved folder has a wallet slot. The KDE Wallet
  key is copied from the old folder to ``Hearthwire`` pipe to pipe, proven by a
  real unlock, and only then removed from the old folder (D2). The empty old
  wallet folder stays (D8).
- ``applets``: with plasmashell stopped, ``plugin=<old id>`` lines directly under
  ``[Containments][N][Applets][M]`` get the new id, so every widget keeps its
  number M and with it its settings, shortcut and sign-ins (D1).

Every step is idempotent: a run that stopped half-way is finished by the next.
Names are opened one component at a time without following links and must be
ours; renames use directory fds and RENAME_NOREPLACE where libc has it;
nothing is ever deleted recursively. Replies hold category names and fixed
error codes only, never a path, count, name or key.
"""

from __future__ import annotations

import errno
import os
import re
import stat
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Optional

from . import vault, walletkey
from .appletconfig import read_rc
from .settingsbackup import config_base
from .usagehistory import HISTORY_DIR
from .webdata import APP_DIR, PRIVATE_MODE, HelperError, _close, _descriptors, data_base, open_base, open_child_dir

OPERATIONS = ("status", "run", "applets", "rollback")
CATEGORIES = ("data", "config", "notifyrc", "cache", "wallet-entry", "applets")
# What "run" does; "applets" is its own operation (plasmashell must be stopped).
RUN_CATEGORIES = CATEGORIES[:5]
ERRORS = ("not-locked", "busy", "symlink", "not-directory", "not-owned", "conflict", "plasma-running",
          "invalid", "os-error")

LEGACY_NAME = "hearthside"
LEGACY_PLUGIN = "io.github.flybytechprog.hearthside"
PLUGIN = "io.github.flybytechprog.hearthwire"
NOTIFYRC_SUFFIX = ".notifyrc"
APPLETSRC = "plasma-org.kde.plasma.desktop-appletsrc"
# Written once next to appletsrc before the first rewrite; the installer deletes
# it on a later run that finds the move complete (user decision Q4).
BACKUP_SUFFIX = ".hearthside-backup"
# The rewritten copy before it replaces appletsrc (never the old name: it is ours).
TEMPORARY_NAME = "." + APPLETSRC + ".hearthwire-migrate"
CACHE_FILE = "antigravity-auth.json"
# storage.atomic_write_private's temporary names for that file.
CACHE_TEMPORARY = re.compile(r"\.antigravity-auth\.json\.[0-9a-f]{32}\.tmp")
MAX_APPLETSRC = 16 * 1024 * 1024
PROC = "/proc"
PLASMASHELL = b"plasmashell"
RENAME_NOREPLACE = 1

_APPLET_HEADER = re.compile(rb"\[Containments\]\[[0-9]+\]\[Applets\]\[[0-9]+\]")
_GROUP_HEADER = re.compile(rb"(?:\[[^\[\]\n]*\])+")


class CategoryError(HelperError):
    """A failure of one category's step: the reply names the category too."""

    def __init__(self, code: str, category: str):
        super().__init__(code)
        self.category = category


@contextmanager
def _category(name: str) -> Iterator[None]:
    try:
        yield
    except CategoryError:
        raise
    except HelperError as error:
        raise CategoryError(error.code, name) from None
    except OSError:
        raise CategoryError("os-error", name) from None


def cache_base(environ: Optional[Mapping[str, str]] = None) -> str:
    """``$XDG_CACHE_HOME`` when it is absolute, else ``~/.cache``."""
    values = os.environ if environ is None else environ
    configured = values.get("XDG_CACHE_HOME") or ""
    if configured and os.path.isabs(configured):
        return configured
    return str(Path.home() / ".cache")


def legacy_data_present(environ: Optional[Mapping[str, str]] = None) -> bool:
    """The former name's data folder exists (anything there counts; plan D5)."""
    try:
        os.lstat(os.path.join(data_base(environ), LEGACY_NAME))
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def refuse_legacy_data(environ: Optional[Mapping[str, str]] = None) -> None:
    """legacy-data while the former name's data folder exists.

    For helpers that would otherwise create the new folder before the
    installer has moved the old one, which would then be a conflict.
    """
    if legacy_data_present(environ):
        raise HelperError("legacy-data")


# --- file system ---------------------------------------------------------------------------------


def _entry(parent: int, name: str, *, directory: bool) -> Optional[os.stat_result]:
    """lstat of ``name`` below ``parent``; None when missing. Symlinks, the wrong
    kind of file and other users' files are refused."""
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError:
        raise HelperError("os-error") from None
    if stat.S_ISLNK(info.st_mode):
        raise HelperError("symlink")
    if stat.S_ISDIR(info.st_mode) != directory or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        raise HelperError("not-directory")
    if info.st_uid != os.getuid():
        raise HelperError("not-owned")
    return info


def _directory_state(parent: int, name: str) -> str:
    """"absent", "empty" or "full" for a directory of ours below ``parent``."""
    descriptor = open_child_dir(parent, name, create=False)
    if descriptor is None:
        return "absent"
    try:
        return "full" if os.listdir(descriptor) else "empty"
    except OSError:
        raise HelperError("os-error") from None
    finally:
        _close(descriptor)


def _load_renameat2() -> Optional[Callable[..., int]]:
    try:
        import ctypes

        function = ctypes.CDLL(None, use_errno=True).renameat2
    except (ImportError, OSError, AttributeError):
        return None
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    return function


_renameat2: Optional[Callable[..., int]] = None
_renameat2_loaded = False


def _noreplace() -> Optional[Callable[..., int]]:
    global _renameat2, _renameat2_loaded
    if not _renameat2_loaded:
        _renameat2 = _load_renameat2()
        _renameat2_loaded = True
    return _renameat2


def _rename(parent: int, source: str, target: str) -> None:
    """Rename within ``parent`` without ever replacing ``target`` (conflict if it exists).

    renameat2(RENAME_NOREPLACE) when libc has it and the file system supports
    it; else an lstat check right before a plain dir-fd rename.
    """
    function = _noreplace()
    if function is not None:
        import ctypes

        if function(parent, os.fsencode(source), parent, os.fsencode(target), RENAME_NOREPLACE) == 0:
            return
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise HelperError("conflict")
        if code not in (errno.EINVAL, errno.ENOSYS):
            raise HelperError("os-error")
    try:
        os.stat(target, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        pass
    except OSError:
        raise HelperError("os-error") from None
    else:
        raise HelperError("conflict")
    try:
        os.rename(source, target, src_dir_fd=parent, dst_dir_fd=parent)
    except OSError:
        raise HelperError("os-error") from None


def _sync(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    except OSError:
        pass


def _refuse_link_or_foreign(parent: int, name: str) -> None:
    """A missing ``name`` is fine; a symlink or another user's entry is refused."""
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError:
        raise HelperError("os-error") from None
    if stat.S_ISLNK(info.st_mode):
        raise HelperError("symlink")
    if info.st_uid != os.getuid():
        raise HelperError("not-owned")


def _check_data_children(data: Optional[int], name: str) -> None:
    """Walk the fixed children of the data folder about to move, without following links.

    A rename would carry a planted link or another user's folder along, so
    these refuse before anything changes.
    """
    if data is None:
        return
    with _descriptors() as opened:
        with _category("data"):
            app = open_child_dir(data, name, create=False)
            if app is None:
                return
            opened.append(app)
            for child in (vault.VAULT_DIR, HISTORY_DIR):
                _refuse_link_or_foreign(app, child)
        with _category("wallet-entry"):
            keys = open_child_dir(app, walletkey.KEYS_DIR, create=False)
            if keys is None:
                return
            opened.append(keys)
            for slot in (walletkey.SLOT_FILE, walletkey.SLOT_OLD, walletkey.SLOT_NEW):
                _refuse_link_or_foreign(keys, slot)


def _check_directory_move(parent: Optional[int], source: str, target: str) -> bool:
    """True when ``source`` is there to move; conflict when ``target`` holds anything."""
    if parent is None or _directory_state(parent, source) == "absent":
        return False
    if _directory_state(parent, target) == "full":
        raise HelperError("conflict")
    return True


def _move_directory(parent: Optional[int], source: str, target: str) -> bool:
    """Rename a whole directory (never merged); an empty ``target`` is removed first."""
    if not _check_directory_move(parent, source, target):
        return False
    assert parent is not None
    if _directory_state(parent, target) == "empty":
        try:
            os.rmdir(target, dir_fd=parent)
        except OSError:
            raise HelperError("conflict") from None
    _rename(parent, source, target)
    moved = open_child_dir(parent, target, create=False)
    if moved is None:
        raise HelperError("os-error")
    try:
        if stat.S_IMODE(os.fstat(moved).st_mode) != PRIVATE_MODE:
            os.fchmod(moved, PRIVATE_MODE)
    except OSError:
        raise HelperError("os-error") from None
    finally:
        _close(moved)
    _sync(parent)
    return True


def _move_file(parent: Optional[int], source: str, target: str) -> bool:
    """Rename a regular file; when ``target`` exists it is kept and ``source`` dropped."""
    if parent is None or _entry(parent, source, directory=False) is None:
        return False
    if _entry(parent, target, directory=False) is not None:
        try:
            os.unlink(source, dir_fd=parent)
        except FileNotFoundError:
            pass
        except OSError:
            raise HelperError("os-error") from None
    else:
        _rename(parent, source, target)
    _sync(parent)
    return True


def _cache_names(cache: int) -> list[str]:
    try:
        return [name for name in os.listdir(cache) if name == CACHE_FILE or CACHE_TEMPORARY.fullmatch(name)]
    except OSError:
        raise HelperError("os-error") from None


def _cache_pending(parent: Optional[int]) -> bool:
    """The old cache folder still holds the token cache (or is empty).

    Each file about to be deleted is checked here, so the step cannot fail
    after the data has moved.
    """
    if parent is None:
        return False
    cache = open_child_dir(parent, LEGACY_NAME, create=False)
    if cache is None:
        return False
    try:
        names = _cache_names(cache)
        for name in names:
            _entry(cache, name, directory=False)
        return bool(names) or not os.listdir(cache)
    except OSError:
        raise HelperError("os-error") from None
    finally:
        _close(cache)


def _clear_cache(parent: Optional[int]) -> bool:
    """Delete the token cache and its temporary files, then the folder if empty.

    Anything else in that folder is not ours to delete and stays.
    """
    if not _cache_pending(parent):
        return False
    assert parent is not None
    cache = open_child_dir(parent, LEGACY_NAME, create=False)
    if cache is None:
        return False
    try:
        for name in _cache_names(cache):
            if _entry(cache, name, directory=False) is not None:
                try:
                    os.unlink(name, dir_fd=cache)
                except FileNotFoundError:
                    pass
    except OSError:
        raise HelperError("os-error") from None
    finally:
        _close(cache)
    try:
        os.rmdir(LEGACY_NAME, dir_fd=parent)
    except OSError:
        pass  # Not empty: someone else's files stay.
    _sync(parent)
    return True


@contextmanager
def _bases(environ: Optional[Mapping[str, str]]) -> Iterator[dict[str, Optional[int]]]:
    """Open the data, config and cache bases (None where missing)."""
    with _descriptors() as opened:
        bases: dict[str, Optional[int]] = {}
        for key, path in (("data", data_base(environ)), ("config", config_base(environ)),
                          ("cache", cache_base(environ))):
            descriptor = open_base(path, create=False)
            if descriptor is not None:
                opened.append(descriptor)
            bases[key] = descriptor
        yield bases


# --- plasmashell -----------------------------------------------------------------------------------


def plasma_running(proc: Optional[str] = None) -> bool:
    """A plasmashell process of this user exists (``/proc/<pid>/comm``)."""
    root = PROC if proc is None else proc
    uid = os.getuid()
    try:
        names = os.listdir(root)
    except OSError:
        raise HelperError("os-error") from None
    for name in names:
        if not name.isdigit():
            continue
        try:
            if os.stat(os.path.join(root, name)).st_uid != uid:
                continue
            with open(os.path.join(root, name, "comm"), "rb") as handle:
                comm = handle.read(64)
        except OSError:
            continue  # Gone meanwhile.
        if comm.rstrip(b"\n") == PLASMASHELL:
            return True
    return False


def _refuse_plasma() -> None:
    if plasma_running():
        raise HelperError("plasma-running")


# --- appletsrc ------------------------------------------------------------------------------------------


def rewrite_applets(content: bytes, old: str, new: str) -> tuple[bytes, int, int]:
    """Replace ``plugin=<old>`` lines directly under ``[Containments][N][Applets][M]``.

    Returns the new bytes and how many ``old`` and ``new`` lines were found
    there. Every other byte stays as it was. Input that is not UTF-8 text,
    holds NUL, has a malformed group header, or a ``plugin`` line of an applet
    group that names either id in any other spelling is invalid: no guessing.
    """
    if b"\0" in content:
        raise HelperError("invalid")
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        raise HelperError("invalid") from None
    old_line, new_line = b"plugin=" + old.encode(), b"plugin=" + new.encode()
    ids = {old.encode(), new.encode()}
    lines = content.split(b"\n")
    in_applet = False
    found_old = found_new = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(b"["):
            if not _GROUP_HEADER.fullmatch(stripped):
                raise HelperError("invalid")
            in_applet = _APPLET_HEADER.fullmatch(stripped) is not None
            if in_applet and stripped != line:
                raise HelperError("invalid")
            continue
        if not in_applet:
            continue
        if line == old_line:
            lines[index] = new_line
            found_old += 1
        elif line == new_line:
            found_new += 1
        else:
            key, separator, value = line.partition(b"=")
            if separator and key.strip() == b"plugin" and value.strip() in ids:
                raise HelperError("invalid")
    return b"\n".join(lines), found_old, found_new


def _read_applets(config: int) -> Optional[tuple[bytes, os.stat_result]]:
    """appletsrc's bytes and the fstat of the descriptor they were read from."""
    return read_rc(config, APPLETSRC, MAX_APPLETSRC)


def _write_new(parent: int, name: str, content: bytes, mode: int) -> None:
    """Create ``name`` (O_EXCL, no-follow), write, set ``mode``, fsync."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(name, flags, 0o600, dir_fd=parent)
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        _close(descriptor)


def _write_backup(config: int, content: bytes) -> None:
    """``<appletsrc>.hearthside-backup`` (0600): written once, an existing one is kept."""
    name = APPLETSRC + BACKUP_SUFFIX
    if _entry(config, name, directory=False) is not None:
        return
    try:
        _write_new(config, name, content, 0o600)
    except FileExistsError:
        if _entry(config, name, directory=False) is None:
            raise HelperError("os-error") from None
    except OSError:
        raise HelperError("os-error") from None


def _drop_temporary(config: int) -> None:
    try:
        info = os.stat(TEMPORARY_NAME, dir_fd=config, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError:
        raise HelperError("os-error") from None
    if stat.S_ISDIR(info.st_mode):
        raise HelperError("not-directory")
    try:
        os.unlink(TEMPORARY_NAME, dir_fd=config)
    except FileNotFoundError:
        pass
    except OSError:
        raise HelperError("os-error") from None


def _applets_state(config: Optional[int]) -> tuple[bool, bool]:
    """(old id present, new id present) in appletsrc; read only."""
    if config is None:
        return False, False
    current = _read_applets(config)
    if current is None:
        return False, False
    _, found_old, found_new = rewrite_applets(current[0], LEGACY_PLUGIN, PLUGIN)
    return found_old > 0, found_new > 0


def _switch_applets(config: Optional[int], old: str, new: str, *, backup: bool = True) -> bool:
    """Rewrite appletsrc from ``old`` to ``new`` while plasmashell is stopped.

    Backup first (the forward move only: the backup means "the layout before
    the move", which a copy taken by a rollback would not be), then the
    rewritten copy is written next to it and renamed over appletsrc (same
    mode), after checking again that plasmashell is still stopped and
    appletsrc is still the file that was read.
    """
    if config is None:
        return False
    _refuse_plasma()
    current = _read_applets(config)
    if current is None:
        return False
    content, info = current
    rewritten, found_old, _ = rewrite_applets(content, old, new)
    if not found_old:
        return False
    if backup:
        _write_backup(config, content)
    _drop_temporary(config)
    try:
        _write_new(config, TEMPORARY_NAME, rewritten, stat.S_IMODE(info.st_mode))
    except OSError:
        _drop_temporary(config)
        raise HelperError("os-error") from None
    try:
        _refuse_plasma()
        now = os.stat(APPLETSRC, dir_fd=config, follow_symlinks=False)
        if (now.st_dev, now.st_ino, now.st_size, now.st_mtime_ns) != (
                info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns):
            raise HelperError("os-error")
        os.rename(TEMPORARY_NAME, APPLETSRC, src_dir_fd=config, dst_dir_fd=config)
    except (HelperError, OSError) as error:
        _drop_temporary(config)
        if isinstance(error, HelperError):
            raise
        raise HelperError("os-error") from None
    _sync(config)
    return True


# --- KDE Wallet --------------------------------------------------------------------------------------


def _slot_in(base: Optional[int], name: str) -> bool:
    """``<base>/<name>/vault-keys/wallet.conf`` is a regular file of ours (rule L4).

    A symlink or another user's file there is refused, so it can never lead to
    a wallet call.
    """
    if base is None:
        return False
    with _descriptors() as opened:
        app = open_child_dir(base, name, create=False)
        if app is None:
            return False
        opened.append(app)
        keys = open_child_dir(app, walletkey.KEYS_DIR, create=False)
        if keys is None:
            return False
        opened.append(keys)
        try:
            info = os.stat(walletkey.SLOT_FILE, dir_fd=keys, follow_symlinks=False)
        except FileNotFoundError:
            return False
        except OSError:
            raise HelperError("os-error") from None
        if stat.S_ISLNK(info.st_mode):
            raise HelperError("symlink")
        if info.st_uid != os.getuid():
            raise HelperError("not-owned")
        return stat.S_ISREG(info.st_mode)


def _open_wallet(tools: dict[str, str]) -> Optional[str]:
    """The wallet's name when the wallet tools are there and it is enabled."""
    qdbus = tools.get("qdbus6")
    if qdbus is None or "kwallet-query" not in tools:
        return None
    if walletkey.is_enabled(qdbus) is not True:
        return None
    return walletkey.local_wallet(qdbus)


def _wallet_status(slot: bool) -> tuple[bool, bool]:
    """(pending, present) for the wallet entry; no wallet call at all without a slot."""
    if not slot:
        return False, False
    tools, _missing = walletkey.find_tools()
    wallet = _open_wallet(tools)
    if wallet is None:
        return True, False
    # Only the real entry counts: a lone old staging entry is nothing to move.
    missing = walletkey.key_missing(tools["qdbus6"], wallet, walletkey.ENTRY, walletkey.LEGACY_FOLDER)
    present = walletkey.key_missing(tools["qdbus6"], wallet) is False
    return missing is not True, present


def _drop_copy(tools: dict[str, str], wallet: str) -> None:
    """Remove a new-folder entry that did not open the slot (best effort)."""
    try:
        if walletkey.key_missing(tools["qdbus6"], wallet) is not True:
            walletkey.remove_entry(tools, wallet)
    except HelperError:
        pass


def _migrate_wallet(ctx: vault.Context, app: int, slot: bool) -> str:
    """"migrated", "pending" or "none" (nothing to move, or no slot: no wallet call).

    1. A new entry that already opens the slot is kept; else the old entry is
       copied over it (kwallet-query -r into a pipe, then -w from it).
    2. The copy is proven by mounting with the wallet slot, then unmounted.
    3. Only then the old entry and the old staging entry are removed. When
       the proof fails the new copy is removed again and the step is pending.

    A staging entry without a real old entry proves nothing and stays.
    """
    if not slot:
        return "none"
    tools = ctx.wallet_tools
    if any(name not in ctx.tools for name in ("gocryptfs", "fusermount3")):
        return "pending"
    wallet = _open_wallet(tools)
    if wallet is None:
        return "pending"
    qdbus = tools["qdbus6"]
    old = walletkey.key_missing(qdbus, wallet, walletkey.ENTRY, walletkey.LEGACY_FOLDER)
    if old is None:
        return "pending"
    if old:
        return "none"
    old_staged = walletkey.key_missing(qdbus, wallet, walletkey.ENTRY_NEW, walletkey.LEGACY_FOLDER)
    new = walletkey.key_missing(qdbus, wallet)
    if old_staged is None or new is None:
        return "pending"
    verified = new is False and vault.verify_wallet_slot(ctx, app, wallet)
    if not verified:
        try:
            walletkey.copy_entry(tools, wallet, walletkey.ENTRY, walletkey.ENTRY,
                                 source_folder=walletkey.LEGACY_FOLDER)
            verified = vault.verify_wallet_slot(ctx, app, wallet)
        except HelperError:
            verified = False
        if not verified:
            _drop_copy(tools, wallet)
            return "pending"
    try:
        walletkey.remove_legacy_entry(tools, wallet, walletkey.ENTRY)
        if not old_staged:
            walletkey.remove_legacy_entry(tools, wallet, walletkey.ENTRY_NEW)
    except HelperError:
        return "pending"
    return "migrated"


def _restore_wallet(ctx: vault.Context, slot: bool) -> str:
    """Rollback: "restored", "pending" or "none".

    The new entry (it fits the slot that moves back with the data) is copied
    into the old folder pipe to pipe, and removed only after a byte comparison
    of the two entries proved the copy. Without that proof both stay and the
    step is pending, so a later rollback can finish it. A real unlock cannot
    prove it: gocryptfs may only ever read the new folder. A staging entry
    without a real entry stays too.
    """
    if not slot:
        return "none"
    tools = ctx.wallet_tools
    wallet = _open_wallet(tools)
    if wallet is None:
        return "pending"
    qdbus = tools["qdbus6"]
    new = walletkey.key_missing(qdbus, wallet)
    if new is None:
        return "pending"
    if new:
        return "none"
    staged = walletkey.key_missing(qdbus, wallet, walletkey.ENTRY_NEW)
    if staged is None:
        return "pending"
    try:
        walletkey.copy_entry(tools, wallet, walletkey.ENTRY, walletkey.ENTRY,
                             target_folder=walletkey.LEGACY_FOLDER)
        if not walletkey.entries_equal(tools, wallet, walletkey.FOLDER, walletkey.LEGACY_FOLDER):
            return "pending"
        walletkey.remove_entry(tools, wallet)
        if not staged:
            walletkey.remove_entry(tools, wallet, entry=walletkey.ENTRY_NEW)
    except HelperError:
        return "pending"
    return "restored"


# --- locks ---------------------------------------------------------------------------------------------


NAMES = (LEGACY_NAME, APP_DIR)


@contextmanager
def _locked(environ: Optional[Mapping[str, str]], *, find_tools: bool) -> Iterator[tuple[vault.Context, int]]:
    """Refuse while any vault (old or new name) is mounted; hold the old, then the new
    vault lock. Yields the vault context and the new lock directory's fd."""
    if vault.mounted_any(environ, NAMES):
        raise HelperError("not-locked")
    runtimes = vault._purge_runtimes(environ)
    if not runtimes:
        raise HelperError("os-error")
    values = os.environ if environ is None else environ
    ctx = vault.context({**values, "XDG_RUNTIME_DIR": runtimes[0]}, find_tools=find_tools)
    with vault.vault_lock(ctx, app_dir=LEGACY_NAME):
        with vault.vault_lock(ctx) as app:
            if vault.mounted_any(environ, NAMES):
                raise HelperError("not-locked")
            yield ctx, app


# --- operations ------------------------------------------------------------------------------------------


def _ordered(names: Sequence[str]) -> list[str]:
    return [name for name in CATEGORIES if name in names]


def _check_applets_paths(config: Optional[int]) -> None:
    """The backup and temporary names the appletsrc step will use are usable."""
    assert config is not None
    for name in (APPLETSRC + BACKUP_SUFFIX, TEMPORARY_NAME):
        _entry(config, name, directory=False)


def _file_pending(bases: dict[str, Optional[int]]) -> list[str]:
    """data, config, notifyrc and cache that still have to move; conflict where both exist."""
    pending = []
    with _category("data"):
        if _check_directory_move(bases["data"], LEGACY_NAME, APP_DIR):
            pending.append("data")
    _check_data_children(bases["data"], LEGACY_NAME)
    with _category("config"):
        if _check_directory_move(bases["config"], LEGACY_NAME, APP_DIR):
            pending.append("config")
    with _category("notifyrc"):
        config = bases["config"]
        if config is not None and _entry(config, LEGACY_NAME + NOTIFYRC_SUFFIX, directory=False) is not None:
            _entry(config, APP_DIR + NOTIFYRC_SUFFIX, directory=False)
            pending.append("notifyrc")
    with _category("cache"):
        if _cache_pending(bases["cache"]):
            pending.append("cache")
    with _category("applets"):
        if _applets_state(bases["config"])[0]:
            _check_applets_paths(bases["config"])
    return pending


def _file_present(bases: dict[str, Optional[int]]) -> list[str]:
    present = []
    for name, base in (("data", bases["data"]), ("config", bases["config"])):
        with _category(name):
            if base is not None and _directory_state(base, APP_DIR) != "absent":
                present.append(name)
    with _category("notifyrc"):
        config = bases["config"]
        if config is not None and _entry(config, APP_DIR + NOTIFYRC_SUFFIX, directory=False) is not None:
            present.append("notifyrc")
    return present


def _slot(bases: dict[str, Optional[int]]) -> bool:
    """The wallet slot of the folder being moved: still under the old name, or moved."""
    with _category("wallet-entry"):
        return _slot_in(bases["data"], LEGACY_NAME) or _slot_in(bases["data"], APP_DIR)


def _survey(environ: Optional[Mapping[str, str]]) -> tuple[list[str], list[str]]:
    with _bases(environ) as bases:
        pending = _file_pending(bases)
        present = _file_present(bases)
        slot = _slot(bases)
        with _category("applets"):
            old_applets, new_applets = _applets_state(bases["config"])
    with _category("wallet-entry"):
        wallet_pending, wallet_present = _wallet_status(slot)
    pending += ["wallet-entry"] * wallet_pending + ["applets"] * old_applets
    present += ["wallet-entry"] * wallet_present + ["applets"] * new_applets
    return _ordered(pending), _ordered(present)


def status(environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    """What is still to move ("pending") and what already uses the new name ("present").

    Read only. With work left it also refuses a mounted vault (not-locked), a
    held vault lock (busy) and data or config under both names (conflict), so
    the installer can stop before changing anything. With nothing left, or
    only the wallet entry (the wallet may stay unavailable for a long time), a
    mounted vault is fine: an ordinary reinstall needs no lock.
    """
    pending, present = _survey(environ)
    if any(name != "wallet-entry" for name in pending):
        with _locked(environ, find_tools=False):
            with _bases(environ) as bases:
                _file_pending(bases)
    return {"ok": True, "pending": pending, "present": present}


def run(environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    """Move data, config, notifyrc, cache and the wallet entry.

    plasmashell must be stopped unless only the wallet entry is left: a running
    widget can only recreate the old folders.
    """
    pending, _ = _survey(environ)
    if not any(name in RUN_CATEGORIES for name in pending):
        return {"ok": True, "migrated": [], "pending": pending}
    migrated: list[str] = []
    with _locked(environ, find_tools=True) as (ctx, app):
        with _bases(environ) as bases:
            # Everything that can refuse does so before anything changes.
            if _file_pending(bases):
                _refuse_plasma()
            with _category("data"):
                if _move_directory(bases["data"], LEGACY_NAME, APP_DIR):
                    migrated.append("data")
            with _category("config"):
                if _move_directory(bases["config"], LEGACY_NAME, APP_DIR):
                    migrated.append("config")
            with _category("notifyrc"):
                if _move_file(bases["config"], LEGACY_NAME + NOTIFYRC_SUFFIX, APP_DIR + NOTIFYRC_SUFFIX):
                    migrated.append("notifyrc")
            with _category("cache"):
                if _clear_cache(bases["cache"]):
                    migrated.append("cache")
            with _category("wallet-entry"):
                slot = _slot_in(bases["data"], APP_DIR) and not _slot_in(bases["data"], LEGACY_NAME)
                if _migrate_wallet(ctx, app, slot) == "migrated":
                    migrated.append("wallet-entry")
    pending, _ = _survey(environ)
    return {"ok": True, "migrated": _ordered(migrated), "pending": pending}


def applets(environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    """Give every widget of the old id the new one (plasmashell must be stopped).

    Everything is surveyed first, under the locks, so a refusal changes nothing
    and no error can follow a rewrite.
    """
    with _locked(environ, find_tools=False):
        pending, _ = _survey(environ)
        with _bases(environ) as bases:
            with _category("applets"):
                changed = _switch_applets(bases["config"], LEGACY_PLUGIN, PLUGIN)
    return {"ok": True, "migrated": ["applets"] if changed else [],
            "pending": [name for name in pending if name != "applets"]}


def rollback(environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    """The exact inverse of run and applets, for going back to the former release.

    The token cache is not restored (it is rebuilt on demand). "pending" lists
    what could not be restored (only ever the wallet entry).
    """
    restored: list[str] = []
    pending: list[str] = []
    with _locked(environ, find_tools=True) as (ctx, _app):
        with _bases(environ) as bases:
            with _category("data"):
                _check_directory_move(bases["data"], APP_DIR, LEGACY_NAME)
            _check_data_children(bases["data"], APP_DIR)
            with _category("config"):
                _check_directory_move(bases["config"], APP_DIR, LEGACY_NAME)
            with _category("notifyrc"):
                if bases["config"] is not None:
                    _entry(bases["config"], APP_DIR + NOTIFYRC_SUFFIX, directory=False)
                    _entry(bases["config"], LEGACY_NAME + NOTIFYRC_SUFFIX, directory=False)
            with _category("applets"):
                if _applets_state(bases["config"])[1]:
                    _entry(bases["config"], TEMPORARY_NAME, directory=False)
            _refuse_plasma()
            with _category("wallet-entry"):
                # Either name: an earlier rollback may have moved the data but kept the entry.
                slot = _slot_in(bases["data"], APP_DIR) or _slot_in(bases["data"], LEGACY_NAME)
                outcome = _restore_wallet(ctx, slot)
                if outcome != "none":
                    (restored if outcome == "restored" else pending).append("wallet-entry")
            with _category("notifyrc"):
                if _move_file(bases["config"], APP_DIR + NOTIFYRC_SUFFIX, LEGACY_NAME + NOTIFYRC_SUFFIX):
                    restored.append("notifyrc")
            with _category("config"):
                if _move_directory(bases["config"], APP_DIR, LEGACY_NAME):
                    restored.append("config")
            with _category("data"):
                if _move_directory(bases["data"], APP_DIR, LEGACY_NAME):
                    restored.append("data")
            with _category("applets"):
                if _switch_applets(bases["config"], PLUGIN, LEGACY_PLUGIN, backup=False):
                    restored.append("applets")
    return {"ok": True, "restored": _ordered(restored), "pending": _ordered(pending)}


_HANDLERS: dict[str, Callable[[Optional[Mapping[str, str]]], dict[str, object]]] = {
    "status": status,
    "run": run,
    "applets": applets,
    "rollback": rollback,
}


def run_operation(operation: str, environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    """CLI entry: category names and fixed error codes only."""
    handler = _HANDLERS.get(operation)
    if handler is None:
        raise ValueError("Unsupported migrate operation.")
    try:
        return handler(environ)
    except HelperError as error:
        code = error.code if error.code in ERRORS else "os-error"
        reply: dict[str, object] = {"ok": False, "error": code}
        category = getattr(error, "category", None)
        if category in CATEGORIES:
            reply["category"] = category
        return reply
    except OSError:
        return {"ok": False, "error": "os-error"}


__all__ = ["CATEGORIES", "ERRORS", "OPERATIONS", "legacy_data_present", "plasma_running", "refuse_legacy_data",
           "rewrite_applets",
           "run_operation"]
