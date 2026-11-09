"""KDE Wallet key slot for the encrypted Chat folder (see ``vault.py``).

The wallet slot is a copy of ``gocryptfs.conf`` at
``$XDG_DATA_HOME/hearthwire/vault-keys/wallet.conf`` whose master key is
wrapped with a random 256-bit key (``openssl rand -hex 32``) kept in the
user's KDE Wallet, folder ``Hearthwire``, entry ``encrypted-chat-folder``.
A (re-)setup stages its new key in ``encrypted-chat-folder.new`` and moves it
to the real entry only after the new slot is keyed (``vault.add_key``).

That key never passes through this process. ``openssl`` writes it straight
into ``kwallet-query -w`` through a pipe; ``kwallet-query -r`` writes it
straight into ``gocryptfs -passwd`` or ``kwallet-query -w`` (through a pipe)
or into gocryptfs as its ``-extpass`` program. This module holds only pipe fds and never reads them.
The only captured output is that of the ``qdbus6`` queries in ``_query()``:
booleans, the wallet's name and a wallet handle, all non-secret.

Measured with kwallet 6.31.0 over ksecretd (Plasma 6.8, spikes W1–W5 and the
user's session on 2026-11-03):

- ``-w`` reads the whole stdin and strips one trailing LF; ``-r`` prints the
  value plus one LF. Both print their *errors on stdout* with exit 4 (missing
  entry or folder) or 1 (wallet not found, disabled, no Secret Service), so
  every exit status is checked before a slot is kept.
- A locked wallet makes ``-r``/``-w`` and ``open`` block on ksecretd's own
  password prompt, and every kwalletd6 call blocks while it is pending, so all
  queries have short timeouts and prompting calls an overall cap.
- ``isOpen`` is false right after a PAM unlock; the Secret Service ``Locked``
  property of the wallet's collection tells the real state without a prompt.
- There is no per-application access control: any program running as the user
  can read the entry while the wallet is unlocked.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from typing import Optional

from .webdata import HelperError, _close

# =====================================================================================
# kwallet-query / qdbus6 / openssl CONTRACT. Names, argv shapes and timeouts live here.
# =====================================================================================

# Reported in a status reply's "missing" when absent (kwallet -> kwallet-query,
# qt6-tools -> qdbus6). openssl is needed only to set up or remove the key.
TOOLS = ("kwallet-query", "qdbus6")
KEYGEN_TOOL = "openssl"
# Only the migration's rollback uses it; without it the copy counts as unproven.
COMPARE_TOOL = "cmp"
FOLDER = "Hearthwire"
ENTRY = "encrypted-chat-folder"
# A re-setup stages its new key here and moves it to ENTRY only after the new
# slot is keyed, so a failed re-setup leaves the working slot and entry alone.
ENTRY_NEW = ENTRY + ".new"
ENTRIES = (ENTRY, ENTRY_NEW)
APP_ID = "Hearthwire"
# The folder of the product's former name. Only the installer's one-time
# migration (core/legacy.py) uses it: kwallet-query may read or write ENTRY
# there, and qdbus6 may ask keyDoesNotExist or call removeEntry for ENTRIES.
# The folder itself is never removed (removeFolder is not in KWALLET_METHODS).
LEGACY_FOLDER = "Hearthside"

KEYS_DIR = "vault-keys"
SLOT_FILE = "wallet.conf"
# The copy being keyed; gocryptfs itself writes "<config>.tmp" next to it (exit 24
# when that already exists), so both are cleared before and after.
SLOT_NEW = "wallet.conf.new"
# The previous slot while a re-setup swaps the new one in (restored on failure).
SLOT_OLD = "wallet.conf.old"
GOCRYPTFS_TEMPORARY_SUFFIX = ".tmp"
# gocryptfs always rewrites a config file as 0400 (spike KS1 #2).
SLOT_MODE = 0o400

# localWallet must look like a wallet name; never a leading dash (it would be an
# option to kwallet-query, and gocryptfs duplicates single dashes in -extpass).
WALLET_NAME = re.compile(r"[A-Za-z0-9._ -]{1,64}")
# A Secret Service collection object path element for a wallet name.
_PATH_ELEMENT = re.compile(r"[A-Za-z0-9_]{1,64}")

QUERY_TIMEOUT = 2.0
# Calls that may show KWallet's own password prompt (wallet locked).
PROMPT_TIMEOUT = 120.0
_MAX_QUERY_OUTPUT = 4096

KWALLETD_SERVICE = "org.kde.kwalletd6"
KWALLETD_PATH = "/modules/kwalletd6"
KWALLET_INTERFACE = "org.kde.KWallet."
SECRETS_SERVICE = "org.freedesktop.secrets"
SECRETS_DEFAULT_ALIAS = "/org/freedesktop/secrets/aliases/default"
SECRETS_COLLECTION = "/org/freedesktop/secrets/collection/"
# KWallet methods this helper may call, with their argument count.
KWALLET_METHODS = {
    "isEnabled": 0,
    "localWallet": 0,
    "keyDoesNotExist": 3,
    "open": 3,
    "removeEntry": 4,
    "close": 3,
}
SECRETS_PROPERTIES = ("Label", "Locked")


def keygen_argv(openssl: str) -> list[str]:
    return [openssl, "rand", "-hex", "32"]


def write_argv(kwallet_query: str, wallet: str, entry: str = ENTRY, folder: str = FOLDER) -> list[str]:
    return [kwallet_query, "--folder", folder, "--write-password", entry, wallet]


def read_argv(kwallet_query: str, wallet: str, entry: str = ENTRY, folder: str = FOLDER) -> list[str]:
    """Long option names only: gocryptfs turns ``-f`` into ``--f`` in -extpass."""
    return [kwallet_query, "--folder", folder, "--read-password", entry, wallet]


def compare_argv(cmp_tool: str, first: int, second: int) -> list[str]:
    """``cmp -s`` of two inherited pipe read ends; only its exit status is used."""
    return [cmp_tool, "-s", f"/dev/fd/{first}", f"/dev/fd/{second}"]


def kwallet_argv(qdbus: str, method: str, *arguments: str) -> list[str]:
    return [qdbus, KWALLETD_SERVICE, KWALLETD_PATH, KWALLET_INTERFACE + method, *arguments]


def secrets_argv(qdbus: str, path: str, prop: str) -> list[str]:
    return [qdbus, SECRETS_SERVICE, path, prop]


# =====================================================================================
# End of the contract.
# =====================================================================================


def valid_wallet(name: object) -> bool:
    return isinstance(name, str) and WALLET_NAME.fullmatch(name) is not None and not name.startswith("-")


def _secrets_path(path: str) -> bool:
    if path == SECRETS_DEFAULT_ALIAS:
        return True
    return path.startswith(SECRETS_COLLECTION) and _PATH_ELEMENT.fullmatch(path[len(SECRETS_COLLECTION):]) is not None


def is_read_argv(values: Sequence[str]) -> bool:
    """The exact ``kwallet-query -r`` of ENTRY in FOLDER (never LEGACY_FOLDER): the only extpass."""
    values = list(values)
    return (
        len(values) == 6 and os.path.isabs(values[0]) and os.path.basename(values[0]) == "kwallet-query"
        and values == read_argv(values[0], values[5]) and valid_wallet(values[5])
    )


def check_argv(argv: Sequence[str]) -> None:
    """Refuse any kwallet-query, qdbus6 or openssl argv outside the contract."""
    argv = list(argv)
    if not argv or not os.path.isabs(argv[0]) or not all(isinstance(item, str) for item in argv):
        raise HelperError("os-error")
    tool = os.path.basename(argv[0])
    if tool == "openssl":
        if argv != keygen_argv(argv[0]):
            raise HelperError("os-error")
    elif tool == COMPARE_TOOL:
        if len(argv) != 4 or argv[1] != "-s" or not all(re.fullmatch(r"/dev/fd/[0-9]{1,10}", path) for path in argv[2:]):
            raise HelperError("os-error")
    elif tool == "kwallet-query":
        if len(argv) != 6 or not valid_wallet(argv[5]) or argv not in [
                *(shape(argv[0], argv[5], entry) for shape in (read_argv, write_argv) for entry in ENTRIES),
                *(shape(argv[0], argv[5], ENTRY, LEGACY_FOLDER) for shape in (read_argv, write_argv))]:
            raise HelperError("os-error")
    elif tool == "qdbus6":
        if len(argv) < 4:
            raise HelperError("os-error")
        if argv[1] == KWALLETD_SERVICE:
            method = argv[3][len(KWALLET_INTERFACE):] if argv[3].startswith(KWALLET_INTERFACE) else ""
            arguments = argv[4:]
            if (argv[2] != KWALLETD_PATH or method not in KWALLET_METHODS
                    or len(arguments) != KWALLET_METHODS[method]):
                raise HelperError("os-error")
            if method in ("keyDoesNotExist", "open") and not valid_wallet(arguments[0]):
                raise HelperError("os-error")
            if method == "keyDoesNotExist" and arguments[1:] not in (
                    [folder, entry] for folder in (FOLDER, LEGACY_FOLDER) for entry in ENTRIES):
                raise HelperError("os-error")
            if method == "open" and arguments[1:] != ["0", APP_ID]:
                raise HelperError("os-error")
            if method in ("removeEntry", "close") and not re.fullmatch(r"[0-9]{1,10}", arguments[0]):
                raise HelperError("os-error")
            if method == "removeEntry" and arguments[1:] not in (
                    [folder, entry, APP_ID] for folder in (FOLDER, LEGACY_FOLDER) for entry in ENTRIES):
                raise HelperError("os-error")
            if method == "close" and arguments[1:] != ["false", APP_ID]:
                raise HelperError("os-error")
        elif argv[1] == SECRETS_SERVICE:
            if len(argv) != 4 or not _secrets_path(argv[2]) or argv[3] not in SECRETS_PROPERTIES:
                raise HelperError("os-error")
        else:
            raise HelperError("os-error")
    else:
        raise HelperError("os-error")


# --- tools --------------------------------------------------------------------------------------


def find_tools() -> tuple[dict[str, str], tuple[str, ...]]:
    """Absolute paths of kwallet-query, qdbus6 and openssl; the missing ``TOOLS``.

    A tool found only through a relative PATH entry counts as missing.
    """
    found: dict[str, str] = {}
    for name in (*TOOLS, KEYGEN_TOOL, COMPARE_TOOL):
        path = shutil.which(name)
        if path and os.path.isabs(path):
            found[name] = path
    return found, tuple(name for name in TOOLS if name not in found)


# --- children -----------------------------------------------------------------------------------


def _query(argv: Sequence[str], timeout: Optional[float] = None) -> Optional[str]:
    """One qdbus6 call; its stripped stdout, or None on any failure.

    The only place in this module that captures output. qdbus6 answers here
    are booleans, the wallet name or an integer handle, never key material.
    """
    check_argv(argv)
    if os.path.basename(argv[0]) != "qdbus6":
        raise HelperError("os-error")
    try:
        completed = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            timeout=QUERY_TIMEOUT if timeout is None else timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if completed.returncode != 0 or len(completed.stdout) > _MAX_QUERY_OUTPUT:
        return None
    try:
        return completed.stdout.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None


def _spawn(argv: Sequence[str], *, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL) -> subprocess.Popen:
    """Start one child: argv list, no shell, stderr on /dev/null, output never read."""
    check_argv(argv)
    try:
        return subprocess.Popen(
            list(argv),
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError:
        raise HelperError("missing-tool") from None


def _finish(child: subprocess.Popen, timeout: float) -> Optional[int]:
    """The child's exit code, or None when it had to be killed after ``timeout``."""
    try:
        return child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
        return None


def _boolean(answer: Optional[str]) -> Optional[bool]:
    return {"true": True, "false": False}.get(answer or "")


# --- queries --------------------------------------------------------------------------------------


def is_enabled(qdbus: str) -> Optional[bool]:
    return _boolean(_query(kwallet_argv(qdbus, "isEnabled")))


def local_wallet(qdbus: str) -> Optional[str]:
    name = _query(kwallet_argv(qdbus, "localWallet"))
    return name if valid_wallet(name) else None


def key_missing(qdbus: str, wallet: str, entry: str = ENTRY, folder: str = FOLDER) -> Optional[bool]:
    """True when there is no entry (answers while locked, without a prompt)."""
    return _boolean(_query(kwallet_argv(qdbus, "keyDoesNotExist", wallet, folder, entry)))


def wallet_locked(qdbus: str, wallet: str) -> Optional[bool]:
    """The Secret Service ``Locked`` property of the wallet's collection.

    The default alias is used when its ``Label`` is the wallet's name; else the
    collection path, when the name can be one. None when unknown.
    """
    path = None
    if _query(secrets_argv(qdbus, SECRETS_DEFAULT_ALIAS, "Label")) == wallet:
        path = SECRETS_DEFAULT_ALIAS
    elif _PATH_ELEMENT.fullmatch(wallet):
        path = SECRETS_COLLECTION + wallet
    if path is None:
        return None
    return _boolean(_query(secrets_argv(qdbus, path, "Locked")))


def preflight(tools: dict[str, str]) -> str:
    """The wallet's name when it is enabled; else wallet-disabled / wallet-failed."""
    qdbus = tools.get("qdbus6")
    if qdbus is None or "kwallet-query" not in tools:
        raise HelperError("missing-tool")
    enabled = is_enabled(qdbus)
    if enabled is False:
        raise HelperError("wallet-disabled")
    if enabled is None:
        raise HelperError("wallet-failed")
    wallet = local_wallet(qdbus)
    if wallet is None:
        raise HelperError("wallet-failed")
    return wallet


# --- key plumbing (fds only) ------------------------------------------------------------------------


def write_new_key(tools: dict[str, str], wallet: str, *, entry: str = ENTRY,
                  timeout: Optional[float] = None) -> None:
    """``openssl rand -hex 32 | kwallet-query -w <entry>``; both must exit 0.

    The key goes from openssl's stdout to kwallet-query's stdin through a pipe
    this process only holds. A kwallet-query failure or timeout is
    wallet-failed; an openssl failure wallet-write-failed. When openssl failed
    but kwallet-query stored what it got (an empty value, W1), that entry is
    deleted again.
    """
    openssl, kwallet_query = tools.get(KEYGEN_TOOL), tools.get("kwallet-query")
    if openssl is None or kwallet_query is None:
        raise HelperError("missing-tool")
    reader, writer = os.pipe()
    keygen: Optional[subprocess.Popen] = None
    store: Optional[subprocess.Popen] = None
    try:
        # openssl first: if kwallet-query started first and openssl could not, the
        # closed pipe would store an empty value (W1).
        keygen = _spawn(keygen_argv(openssl), stdout=writer)
        os.close(writer)
        writer = -1
        store = _spawn(write_argv(kwallet_query, wallet, entry), stdin=reader)
        os.close(reader)
        reader = -1
        keygen_code = _finish(keygen, QUERY_TIMEOUT * 5)
        store_code = _finish(store, PROMPT_TIMEOUT if timeout is None else timeout)
    finally:
        _close(reader)
        _close(writer)
        for child in (keygen, store):
            if child is not None and child.poll() is None:
                child.kill()
                child.wait()
    if store_code != 0:
        raise HelperError("wallet-failed")
    if keygen_code != 0:
        qdbus = tools.get("qdbus6")
        if qdbus is not None:
            _delete_entry(qdbus, wallet, entry, PROMPT_TIMEOUT if timeout is None else timeout)
        raise HelperError("wallet-write-failed")


def read_key_into_pipe(kwallet_query: str, wallet: str, *, entry: str = ENTRY, folder: str = FOLDER,
                       timeout: Optional[float] = None) -> int:
    """Run ``kwallet-query -r <entry>`` into a fresh pipe; returns the pipe's read end.

    The value (65 bytes) waits in the kernel pipe buffer until the caller hands
    the read end on (to gocryptfs, or to ``kwallet-query -w``). kwallet-query
    prints errors on stdout too, so a non-zero exit or a timeout closes the
    pipe and is wallet-failed: such a pipe is never handed on.
    """
    reader, writer = os.pipe()
    child: Optional[subprocess.Popen] = None
    try:
        child = _spawn(read_argv(kwallet_query, wallet, entry, folder), stdout=writer)
        os.close(writer)
        writer = -1
        code = _finish(child, PROMPT_TIMEOUT if timeout is None else timeout)
    except BaseException:
        _close(reader)
        raise
    finally:
        _close(writer)
        if child is not None and child.poll() is None:
            child.kill()
            child.wait()
    if code != 0:
        _close(reader)
        raise HelperError("wallet-failed")
    return reader


def copy_entry(tools: dict[str, str], wallet: str, source: str, target: str, *,
               source_folder: str = FOLDER, target_folder: str = FOLDER,
               timeout: Optional[float] = None) -> None:
    """``kwallet-query -r <source>`` into a pipe, and only after it exited 0 that pipe
    into ``kwallet-query -w <target>`` (which must exit 0). Never read here.

    The folders differ only for the installer's migration (LEGACY_FOLDER to
    FOLDER) and its rollback (the reverse).
    """
    kwallet_query = tools.get("kwallet-query")
    if kwallet_query is None:
        raise HelperError("missing-tool")
    reader = read_key_into_pipe(kwallet_query, wallet, entry=source, folder=source_folder, timeout=timeout)
    store: Optional[subprocess.Popen] = None
    try:
        store = _spawn(write_argv(kwallet_query, wallet, target, target_folder), stdin=reader)
        os.close(reader)
        reader = -1
        code = _finish(store, PROMPT_TIMEOUT if timeout is None else timeout)
    finally:
        _close(reader)
        if store is not None and store.poll() is None:
            store.kill()
            store.wait()
    if code != 0:
        raise HelperError("wallet-failed")


def entries_equal(tools: dict[str, str], wallet: str, first_folder: str, second_folder: str, *,
                  entry: str = ENTRY, timeout: Optional[float] = None) -> bool:
    """True when ``entry`` holds the same bytes in both folders.

    Each ``kwallet-query -r`` runs into its own pipe, and ``cmp`` inherits the
    two read ends: this process holds them and never reads, and only cmp's
    exit status comes back. Anything else (a missing tool, a cancelled
    prompt, a difference) is False.
    """
    kwallet_query, compare = tools.get("kwallet-query"), tools.get(COMPARE_TOOL)
    if kwallet_query is None or compare is None:
        return False
    first = second = -1
    try:
        first = read_key_into_pipe(kwallet_query, wallet, entry=entry, folder=first_folder, timeout=timeout)
        second = read_key_into_pipe(kwallet_query, wallet, entry=entry, folder=second_folder, timeout=timeout)
        argv = compare_argv(compare, first, second)
        check_argv(argv)
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            pass_fds=(first, second),
            timeout=QUERY_TIMEOUT * 5,
            check=False,
        )
    except (HelperError, subprocess.TimeoutExpired, OSError):
        return False
    finally:
        _close(first)
        _close(second)
    return completed.returncode == 0


def _delete_entry(qdbus: str, wallet: str, entry: str, timeout: float, folder: str = FOLDER) -> bool:
    """``removeEntry`` through kwalletd6; True when the entry is gone afterwards."""
    handle = _query(kwallet_argv(qdbus, "open", wallet, "0", APP_ID), timeout)
    if handle is None or not re.fullmatch(r"[0-9]{1,10}", handle):
        return False
    try:
        _query(kwallet_argv(qdbus, "removeEntry", handle, folder, entry, APP_ID), timeout)
    finally:
        _query(kwallet_argv(qdbus, "close", handle, "false", APP_ID))
    return key_missing(qdbus, wallet, entry, folder) is True


def remove_entry(tools: dict[str, str], wallet: str, *, entry: str = ENTRY,
                 timeout: Optional[float] = None) -> None:
    """Overwrite the entry with a fresh random value (when openssl is there), then
    delete it through kwalletd6.

    Raises wallet-failed (or missing-tool) when the entry may remain.
    """
    qdbus = tools.get("qdbus6")
    if qdbus is None:
        raise HelperError("missing-tool")
    timeout = PROMPT_TIMEOUT if timeout is None else timeout
    if KEYGEN_TOOL in tools:
        try:
            write_new_key(tools, wallet, entry=entry, timeout=timeout)
        except HelperError:
            pass  # Best effort: the value is unusable once the entry is gone, deleted below.
    if not _delete_entry(qdbus, wallet, entry, timeout):
        raise HelperError("wallet-failed")


def remove_legacy_entry(tools: dict[str, str], wallet: str, entry: str, *,
                        timeout: Optional[float] = None) -> None:
    """Delete ``entry`` from LEGACY_FOLDER through kwalletd6 (no overwrite: nothing
    is ever written there except by a rollback). Raises wallet-failed when it may remain."""
    qdbus = tools.get("qdbus6")
    if qdbus is None:
        raise HelperError("missing-tool")
    if not _delete_entry(qdbus, wallet, entry, PROMPT_TIMEOUT if timeout is None else timeout, LEGACY_FOLDER):
        raise HelperError("wallet-failed")


def remove_entries(tools: dict[str, str], wallet: str) -> bool:
    """Remove the real and the staging entry where present; True when one was removed.

    Raises wallet-failed when an entry may remain or its state is unknown.
    """
    qdbus = tools["qdbus6"]
    removed = failed = False
    for entry in ENTRIES:
        missing = key_missing(qdbus, wallet, entry)
        if missing is None:
            failed = True
            continue
        if missing:
            continue
        try:
            remove_entry(tools, wallet, entry=entry)
            removed = True
        except HelperError:
            failed = True
    if failed:
        raise HelperError("wallet-failed")
    return removed


def forget(tools: dict[str, str]) -> bool:
    """Remove the wallet entries when the wallet is reachable; True when one was removed.

    Used by destroy and purge. No entry, missing tools or a disabled or
    unreachable wallet is nothing to do; an entry that could not be removed
    raises wallet-failed. openssl is not needed (the overwrite is skipped).
    """
    qdbus = tools.get("qdbus6")
    if qdbus is None or "kwallet-query" not in tools:
        return False
    if is_enabled(qdbus) is not True:
        return False
    wallet = local_wallet(qdbus)
    if wallet is None:
        return False
    if all(key_missing(qdbus, wallet, entry) is not False for entry in ENTRIES):
        return False
    return remove_entries(tools, wallet)


__all__ = [
    "ENTRIES", "ENTRY", "ENTRY_NEW", "FOLDER", "KEYS_DIR", "LEGACY_FOLDER", "SLOT_FILE", "SLOT_NEW", "SLOT_OLD", "TOOLS",
    "check_argv", "compare_argv", "copy_entry", "entries_equal", "find_tools", "forget", "preflight", "read_argv", "read_key_into_pipe",
    "remove_entries", "remove_entry", "remove_legacy_entry", "wallet_locked", "write_new_key",
]
