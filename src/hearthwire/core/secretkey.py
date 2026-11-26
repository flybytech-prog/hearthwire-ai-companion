"""Secret Service key slot for the encrypted Chat folder, app mode only (task 014).

In app mode (``HEARTHWIRE_FRONTEND=app``) the unlock method ``wallet`` means
the session keyring through libsecret's ``secret-tool`` instead of KDE Wallet
(``walletkey.py``, the Plasma widget's, never touched here). The slot is a copy
of ``gocryptfs.conf`` at ``$XDG_DATA_HOME/hearthwire/vault-keys/secret-service.conf``
whose master key is wrapped with a random 256-bit key (``openssl rand -hex
32``, 64 hex digits) kept in the keyring item ``application hearthwire item
encrypted-chat-folder``. A (re-)setup stages its new key in the item
``encrypted-chat-folder.new`` and moves it to the real one only after the new
slot is keyed (``vault.py``).

That key never passes through this process. openssl writes it into a pipe;
``secret-tool lookup`` writes it into a pipe or, as gocryptfs's ``-extpass``
program, straight into gocryptfs. This module holds pipe fds only. It asks
the kernel how many bytes wait in a pipe (``FIONREAD``) and moves exactly
``KEY_LENGTH`` of them on to a fresh pipe with ``os.splice`` (kernel to
kernel), which drops the trailing LF unread. It never reads a key fd. The only
captured output is that of the ``busctl`` queries in ``_query()``: a boolean
and object paths, all non-secret. ``keyring_storage()`` reads the keyring's
``default`` file (a name) and at most 32 header bytes of one ``.keyring``
file, never anything after them.

Measured in the Omarchy lab VM (task 014 R0 and R0b, 2026-11-25; gnome-keyring
51.1, libsecret 0.21.8.2, gcr-4 4.4.1, gocryptfs 2.6.1, systemd busctl):

- ``secret-tool store`` keeps its stdin exactly, a trailing LF included, and
  accepts an empty stdin (exit 0, an empty secret is stored), so a key is
  handed to it only after the pipe was counted. A second store with the same
  attributes replaces the item (SearchItems still finds one).
- ``secret-tool lookup`` adds no LF into a pipe. In R0 it gave a stored LF
  back; in R0b it trimmed it in every state. So the key is stored without a
  LF and a lookup's answer is accepted with or without one: gocryptfs strips
  one trailing LF from both ``-extpass`` output and ``-passwd`` stdin, so the
  key opens the slot either way.
- A missing item: lookup and clear exit 1, nothing on stdout or stderr. A bad
  or missing bus: secret-tool and busctl exit 1, nothing on stdout, the
  message on stderr only. So a failing ``-extpass`` gives gocryptfs an empty
  stdout and a non-zero exit, and gocryptfs refuses the mount (exit 9).
- ``Locked`` prints ``b true`` or ``b false``. ``SearchItems`` prints
  ``aoao <n> <paths> <m> <paths>``: unlocked items first, then locked ones; a
  locked collection lists our item in the second group, so both count.
- Without a ``default`` alias, ``Locked`` fails (exit 1) while a lookup still
  works. A stopped gnome-keyring is started again by D-Bus activation, and
  starts locked even with a plain keyring.
- A plain (passwordless) keyring that is locked is unlocked silently by a
  lookup, in 0 s, with no prompt. A locked encrypted keyring shows the gcr
  prompt (on Hyprland too); Esc makes the lookup exit 1 with an empty stdout.
- The Omarchy default keyring is ``Default_keyring``, a plaintext
  ``[keyring]`` file named in ``keyrings/default``. A keyring the daemon made
  itself with ``--unlock`` is ``login.keyring`` (binary ``GnomeKeyring``
  header) and no ``default`` file is written; the default alias is then
  ``login``.
- There is no per-application access control: any program running as the
  user can read the item while the collection is unlocked, and anyone who can
  read a plain keyring file can read it at any time.
"""

from __future__ import annotations

import array
import fcntl
import os
import re
import select
import shutil
import stat
import subprocess
import termios
import time
from collections.abc import Sequence
from typing import Optional

from . import termination, walletkey
from .webdata import HelperError, _close, data_base, open_base, open_child_dir

# =====================================================================================
# secret-tool / busctl / openssl CONTRACT. Names, argv shapes and timeouts live here.
# =====================================================================================

TOOL = "secret-tool"
BUSCTL = "busctl"
KEYGEN_TOOL = walletkey.KEYGEN_TOOL
# Both are needed for the method; without either it is "unavailable".
TOOLS = (TOOL, BUSCTL)
# Reported in a status reply's "missing" (libsecret -> secret-tool). busctl comes
# with systemd and is never listed. openssl is listed by vault.status after these.
REPORTED = (TOOL,)

APPLICATION = "hearthwire"
ITEM = "encrypted-chat-folder"
# A re-setup stages its new key here and moves it to ITEM only after the new
# slot is keyed, so a failed re-setup leaves the working slot and item alone.
ITEM_NEW = ITEM + ".new"
ITEMS = (ITEM, ITEM_NEW)
# One argv element: "--label=" and the label together.
LABEL = "Hearthwire encrypted chat folder"

KEYS_DIR = walletkey.KEYS_DIR
SLOT_FILE = "secret-service.conf"
# The copy being keyed (gocryptfs also writes "<config>.tmp" next to it).
SLOT_NEW = SLOT_FILE + ".new"
# The previous slot while a re-setup swaps the new one in (restored on failure).
SLOT_OLD = SLOT_FILE + ".old"
SLOT_NAMES = (SLOT_FILE, SLOT_OLD, SLOT_NEW)

# ``openssl rand -hex 32``: 64 hex digits and one LF. Exactly KEY_LENGTH bytes
# go to a store; a lookup may answer with or without the LF.
KEY_LENGTH = 64
_KEY_COUNTS = (KEY_LENGTH, KEY_LENGTH + 1)

# busctl's own D-Bus call timeout (seconds, in its argv); the process gets a
# little more so busctl can report it.
BUS_TIMEOUT = 2
QUERY_TIMEOUT = BUS_TIMEOUT + 1.0
# secret-tool store / lookup / clear may wait on the gcr unlock prompt.
PROMPT_TIMEOUT = 120.0
# The automatic (app start) lookup must never prompt: R0 S5 measured 0 s for a locked
# plain keyring, so anything longer is a prompt or a stuck provider (wallet-closed).
AUTO_LOOKUP_TIMEOUT = 10.0
_KEYGEN_TIMEOUT = 10.0
_MAX_QUERY_OUTPUT = 4096

SECRETS_SERVICE = "org.freedesktop.secrets"
SECRETS_PATH = "/org/freedesktop/secrets"
DEFAULT_ALIAS = "/org/freedesktop/secrets/aliases/default"
COLLECTION_INTERFACE = "org.freedesktop.Secret.Collection"
SERVICE_INTERFACE = "org.freedesktop.Secret.Service"


def attributes(item: str) -> list[str]:
    return ["application", APPLICATION, "item", item]


def store_argv(secret_tool: str, item: str) -> list[str]:
    return [secret_tool, "store", "--label=" + LABEL, *attributes(item)]


def lookup_argv(secret_tool: str, item: str = ITEM) -> list[str]:
    """No word starts with a dash: it is also gocryptfs's ``-extpass`` (dash duplication)."""
    return [secret_tool, "lookup", *attributes(item)]


def clear_argv(secret_tool: str, item: str) -> list[str]:
    return [secret_tool, "clear", *attributes(item)]


def _busctl(busctl: str) -> list[str]:
    return [busctl, "--user", f"--timeout={BUS_TIMEOUT}"]


def locked_argv(busctl: str) -> list[str]:
    return [*_busctl(busctl), "get-property", SECRETS_SERVICE, DEFAULT_ALIAS, COLLECTION_INTERFACE, "Locked"]


def search_argv(busctl: str, item: str) -> list[str]:
    """Object paths only. Never ``secret-tool search``: it prints the secrets."""
    return [*_busctl(busctl), "call", SECRETS_SERVICE, SECRETS_PATH, SERVICE_INTERFACE, "SearchItems",
            "a{ss}", "2", *attributes(item)]


keygen_argv = walletkey.keygen_argv


# =====================================================================================
# End of the contract.
# =====================================================================================


def is_lookup_argv(values: Sequence[str]) -> bool:
    """The exact ``secret-tool lookup`` of ITEM (never ITEM_NEW): the only extpass."""
    values = list(values)
    return (
        len(values) == 6 and all(isinstance(value, str) for value in values)
        and os.path.isabs(values[0]) and os.path.basename(values[0]) == TOOL
        and values == lookup_argv(values[0])
    )


def check_argv(argv: Sequence[str]) -> None:
    """Refuse any secret-tool, busctl or openssl argv outside the contract."""
    argv = list(argv)
    if not argv or not all(isinstance(item, str) for item in argv) or not os.path.isabs(argv[0]):
        raise HelperError("os-error")
    tool = os.path.basename(argv[0])
    if tool == KEYGEN_TOOL:
        allowed = [keygen_argv(argv[0])]
    elif tool == TOOL:
        allowed = [shape(argv[0], item) for shape in (store_argv, lookup_argv, clear_argv) for item in ITEMS]
    elif tool == BUSCTL:
        allowed = [locked_argv(argv[0]), *(search_argv(argv[0], item) for item in ITEMS)]
    else:
        allowed = []
    if argv not in allowed:
        raise HelperError("os-error")


# --- tools --------------------------------------------------------------------------------------


def find_tools() -> tuple[dict[str, str], tuple[str, ...]]:
    """Absolute paths of secret-tool, busctl and openssl; the missing ``TOOLS``.

    A tool found only through a relative PATH entry counts as missing.
    """
    found: dict[str, str] = {}
    for name in (*TOOLS, KEYGEN_TOOL):
        path = shutil.which(name)
        if path and os.path.isabs(path):
            found[name] = path
    return found, tuple(name for name in TOOLS if name not in found)


# --- children -----------------------------------------------------------------------------------


def _read_answer(child: subprocess.Popen, deadline: float) -> Optional[bytes]:
    """At most ``_MAX_QUERY_OUTPUT`` bytes of a busctl answer; None for more, or at the deadline.

    Reads one byte past the cap and stops there: the rest is never read, so an
    oversized answer costs no memory (the caller stops the child).
    """
    descriptor = child.stdout.fileno()
    data = b""
    while len(data) <= _MAX_QUERY_OUTPUT:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([descriptor], [], [], remaining)[0]:
            return None
        chunk = os.read(descriptor, _MAX_QUERY_OUTPUT + 1 - len(data))
        if not chunk:
            return data
        data += chunk
    return None


def _query(argv: Sequence[str]) -> Optional[str]:
    """One busctl call; its stripped stdout, or None on any failure.

    The only place in this module that captures output. busctl answers here
    are a boolean or object paths, never key material. At most
    ``_MAX_QUERY_OUTPUT`` + 1 bytes are read; more than that stops the child's
    process group and is refused.
    """
    check_argv(argv)
    if os.path.basename(argv[0]) != BUSCTL:
        raise HelperError("os-error")
    deadline = time.monotonic() + QUERY_TIMEOUT
    try:
        child = subprocess.Popen(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            process_group=0,
        )
    except OSError:
        return None
    try:
        data = _read_answer(child, deadline)
        if data is None:
            return None
        try:
            code = child.wait(timeout=max(deadline - time.monotonic(), 0.0))
        except subprocess.TimeoutExpired:
            return None
        if code != 0:
            return None
        return data.decode("utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    finally:
        termination.stop(child, grace=0.0)
        child.stdout.close()


def _spawn(argv: Sequence[str], *, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
           after_stop: bool = False) -> subprocess.Popen:
    """Start one child: argv list, no shell, stderr on /dev/null, output never read.

    Its own process group (task 011c), so termination.stop reaches what it
    starts. Nothing new starts after a stop signal (task 011d), except a
    ``clear`` with ``after_stop`` (the cleanup itself).
    """
    check_argv(argv)
    if not after_stop:
        termination.check()
    try:
        return subprocess.Popen(
            list(argv),
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            process_group=0,
        )
    except OSError:
        raise HelperError("missing-tool") from None


def _finish(child: subprocess.Popen, timeout: float, *, settling: bool = False,
            interruptible: bool = True) -> Optional[int]:
    """The child's exit code, or None when it had to be stopped after ``timeout``.

    secret-tool may wait for the gcr prompt, so a stop signal ends the wait
    (termination.Stopped); the caller's ``finally`` stops the child.
    ``settling`` (task 011d): a store that is already writing is let finish
    after a stop signal, up to termination.FINISH_TIMEOUT, before Stopped.
    """
    try:
        code = termination.wait(child, timeout, interruptible=interruptible)
    except termination.Stopped:
        if not settling:
            raise
        code = termination.wait(child, termination.FINISH_TIMEOUT, interruptible=False)
        if code is None:
            raise
    if code is None:
        termination.stop(child, grace=0.0)
    return code


def _waiting(descriptor: int) -> int:
    """How many bytes wait in a pipe (FIONREAD); the bytes themselves stay unread."""
    count = array.array("i", [0])
    fcntl.ioctl(descriptor, termios.FIONREAD, count, True)
    return count[0]


def _key_pipe(source: int) -> int:
    """A fresh pipe holding exactly the first KEY_LENGTH bytes of ``source``.

    ``source`` is a pipe whose writer has exited, holding ``openssl rand -hex
    32`` output or a lookup's answer: KEY_LENGTH bytes, maybe one LF after
    them. Anything else (an empty answer, R0 S2) is refused. ``os.splice``
    moves the bytes kernel to kernel; whatever follows (the LF) is dropped
    with ``source``, unread. Raises OSError or HelperError (callers map both).
    """
    if _waiting(source) not in _KEY_COUNTS:
        raise HelperError("os-error")
    reader, writer = os.pipe()
    try:
        moved = 0
        while moved < KEY_LENGTH:
            count = os.splice(source, writer, KEY_LENGTH - moved)
            if count <= 0:
                raise HelperError("os-error")
            moved += count
    except BaseException:
        _close(reader)
        raise
    finally:
        _close(writer)
    return reader


# --- queries --------------------------------------------------------------------------------------


def collection_locked(busctl: str) -> Optional[bool]:
    """The default collection's ``Locked`` property; None when it does not answer
    (no Secret Service, no default alias, a timeout). Never prompts."""
    return {"b true": True, "b false": False}.get(_query(locked_argv(busctl)) or "")


_ITEM_PATH = re.compile(r'"/org/freedesktop/secrets/collection/[A-Za-z0-9_]{1,255}/[A-Za-z0-9_]{1,255}"')
COLLECTIONS_PATH = SECRETS_PATH + "/collection/"


def _item_paths(answer: Optional[str]) -> Optional[list[str]]:
    """Object paths (unquoted) in a SearchItems reply ``aoao <n> <paths> <m> <paths>``, both groups; None if malformed."""
    words = (answer or "").split()
    if not words or words[0] != "aoao":
        return None
    index, found = 1, []
    for _group in range(2):
        if index >= len(words) or not re.fullmatch(r"[0-9]{1,4}", words[index]):
            return None
        count = int(words[index])
        paths = words[index + 1:index + 1 + count]
        if len(paths) != count or not all(_ITEM_PATH.fullmatch(path) for path in paths):
            return None
        index += 1 + count
        found.extend(path[1:-1] for path in paths)
    return found if index == len(words) else None


def _count_items(answer: Optional[str]) -> Optional[int]:
    paths = _item_paths(answer)
    return None if paths is None else len(paths)


def item_paths(busctl: str, item: str = ITEM) -> Optional[list[str]]:
    """The item's object paths (locked or not, without a prompt); None when unknown."""
    return _item_paths(_query(search_argv(busctl, item)))


def collection_path(name: str) -> str:
    """A collection's object path as libsecret and busctl show it: every byte
    outside [A-Za-z0-9] is ``_`` and two hex digits (``_`` itself is ``_5f``)."""
    escaped = "".join(char if char.isascii() and char.isalnum() else "_%02x" % ord(char) for char in name)
    return COLLECTIONS_PATH + escaped


def item_exists(busctl: str, item: str = ITEM) -> Optional[bool]:
    """True when the item is there, locked or not (answers without a prompt); None when unknown."""
    paths = item_paths(busctl, item)
    return None if paths is None else len(paths) > 0


# --- key plumbing (fds only) ------------------------------------------------------------------------


def store_new_key(tools: dict[str, str], item: str, *, timeout: Optional[float] = None) -> None:
    """``openssl rand -hex 32`` into a pipe, then exactly its 64 hex digits into
    ``secret-tool store <item>``; both must exit 0, else wallet-write-failed.

    openssl must have exited 0 and its pipe must hold the key before the
    store starts: secret-tool would store an empty secret from a closed pipe
    (R0 S2). The trailing LF is never stored (R0b).
    """
    openssl, secret_tool = tools.get(KEYGEN_TOOL), tools.get(TOOL)
    if openssl is None or secret_tool is None:
        raise HelperError("missing-tool")
    reader, writer = os.pipe()
    keygen: Optional[subprocess.Popen] = None
    store: Optional[subprocess.Popen] = None
    key = -1
    try:
        keygen = _spawn(keygen_argv(openssl), stdout=writer)
        os.close(writer)
        writer = -1
        keygen_code = _finish(keygen, _KEYGEN_TIMEOUT)
        if keygen_code != 0:
            raise HelperError("wallet-write-failed")
        try:
            key = _key_pipe(reader)
        except (HelperError, OSError):
            raise HelperError("wallet-write-failed") from None
        _close(reader)
        reader = -1
        store = _spawn(store_argv(secret_tool, item), stdin=key)
        os.close(key)
        key = -1
        store_code = _finish(store, PROMPT_TIMEOUT if timeout is None else timeout)
    finally:
        _close(reader)
        _close(writer)
        _close(key)
        for child in (keygen, store):
            if child is not None:
                termination.stop(child)
    if store_code != 0:
        raise HelperError("wallet-write-failed")


def lookup_into_pipe(secret_tool: str, item: str = ITEM, *, timeout: Optional[float] = None) -> int:
    """Run ``secret-tool lookup <item>`` into a fresh pipe; returns a pipe holding the key.

    The value waits in the kernel pipe buffer until the caller hands the read
    end on (to ``gocryptfs -passwd``, or to a store). A non-zero exit, a
    timeout or an answer that is not a key is wallet-failed: such a pipe is
    never handed on.
    """
    reader, writer = os.pipe()
    child: Optional[subprocess.Popen] = None
    try:
        child = _spawn(lookup_argv(secret_tool, item), stdout=writer)
        os.close(writer)
        writer = -1
        code = _finish(child, PROMPT_TIMEOUT if timeout is None else timeout)
        if code != 0:
            raise HelperError("wallet-failed")
        try:
            return _key_pipe(reader)
        except (HelperError, OSError):
            raise HelperError("wallet-failed") from None
    finally:
        _close(reader)
        _close(writer)
        if child is not None:
            termination.stop(child)


def copy_item(tools: dict[str, str], source: str, target: str, *, timeout: Optional[float] = None,
              settling: bool = False) -> None:
    """``secret-tool lookup <source>`` into a pipe, and only after it exited 0 (with a key)
    that pipe into ``secret-tool store <target>`` (which must exit 0). Never read here.

    A failed lookup is wallet-failed, a failed store wallet-write-failed.
    ``settling`` (task 011d): a stop signal while the store runs lets it
    finish (bounded), as the slot's commit needs; one before it started still
    raises Stopped.
    """
    secret_tool = tools.get(TOOL)
    if secret_tool is None:
        raise HelperError("missing-tool")
    timeout = PROMPT_TIMEOUT if timeout is None else timeout
    reader = lookup_into_pipe(secret_tool, source, timeout=timeout)
    store: Optional[subprocess.Popen] = None
    try:
        store = _spawn(store_argv(secret_tool, target), stdin=reader)
        os.close(reader)
        reader = -1
        code = _finish(store, timeout, settling=settling)
    finally:
        _close(reader)
        if store is not None:
            termination.stop(store)
    if code != 0:
        raise HelperError("wallet-write-failed")


def _clear(secret_tool: str, item: str, timeout: float) -> None:
    """``secret-tool clear <item>``; its exit status says nothing (1 for a missing
    item and for a failure alike, R0 S2), the caller asks SearchItems afterwards.

    After a stop signal (task 011c) it still runs, without waiting for one
    more: it is the cleanup.
    """
    after_stop = termination.requested()
    child = _spawn(clear_argv(secret_tool, item), after_stop=after_stop)
    try:
        if after_stop:
            _finish(child, termination.FINISH_TIMEOUT, interruptible=False)
        else:
            _finish(child, timeout)
    finally:
        termination.stop(child)


def clear_item(tools: dict[str, str], item: str, *, timeout: Optional[float] = None) -> None:
    """Overwrite the item with a fresh random value (when openssl is there), then clear it.

    Only for an item that exists (a store would create it). Raises
    wallet-failed (or missing-tool) when it may remain. After a stop signal
    the overwrite is skipped and the clear still runs.
    """
    secret_tool, busctl = tools.get(TOOL), tools.get(BUSCTL)
    if secret_tool is None or busctl is None:
        raise HelperError("missing-tool")
    timeout = PROMPT_TIMEOUT if timeout is None else timeout
    if KEYGEN_TOOL in tools and not termination.requested():
        try:
            store_new_key(tools, item, timeout=timeout)
        except (HelperError, termination.Stopped):
            pass  # Best effort: the value is unusable once the item is gone, cleared below.
    try:
        _clear(secret_tool, item, timeout)
    except termination.Stopped:
        # Stopped while the clear waited (a prompt): once more, without waiting for a stop.
        _clear(secret_tool, item, timeout)
    if item_exists(busctl, item) is not False:
        raise HelperError("wallet-failed")


def remove_items(tools: dict[str, str]) -> bool:
    """Clear the real and the staging item where present; True when one was cleared.

    Raises wallet-failed when an item may remain or its state is unknown.
    """
    busctl = tools.get(BUSCTL)
    if busctl is None or TOOL not in tools:
        raise HelperError("missing-tool")
    removed = failed = False
    for item in ITEMS:
        exists = item_exists(busctl, item)
        if exists is None:
            failed = True
            continue
        if not exists:
            continue
        try:
            clear_item(tools, item)
            removed = True
        except HelperError:
            failed = True
    if failed:
        raise HelperError("wallet-failed")
    return removed


def forget(tools: dict[str, str]) -> bool:
    """Clear our items; True when one was cleared.

    Used by destroy in app mode, only when the folder had a Secret Service
    slot. Missing tools or no item is nothing to do. The decision is
    SearchItems alone (it works with no default alias, R0 S4). When the
    Secret Service gives no answer at all, or an item could not be cleared,
    wallet-failed.
    """
    busctl = tools.get(BUSCTL)
    if busctl is None or TOOL not in tools:
        return False
    states = [item_exists(busctl, item) for item in ITEMS]
    if all(state is None for state in states):
        raise HelperError("wallet-failed")
    if all(state is False for state in states):
        return False
    return remove_items(tools)


# --- is the keyring stored encrypted? -------------------------------------------------------------------

KEYRINGS_DIR = "keyrings"
DEFAULT_FILE = "default"
# gnome-keyring's default keyring when it wrote no ``default`` file (R0 S6).
FALLBACK_KEYRING = "login"
KEYRING_SUFFIX = ".keyring"
_MAX_DEFAULT_SIZE = 256
KEYRING_NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}")
HEADER_SIZE = 32
PLAIN_HEADER = b"[keyring]"
ENCRYPTED_HEADER = b"GnomeKeyring\n\r\0\n"
STORAGE = ("plain", "encrypted", "unknown")
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC | getattr(os, "O_NOCTTY", 0)


def valid_keyring_name(name: object) -> bool:
    return (isinstance(name, str) and KEYRING_NAME.fullmatch(name) is not None
            and not name.startswith((".", "-")))


def _open_own_file(directory: int, name: str) -> int:
    """``name`` below ``directory``: no link followed, a regular file of ours; raises OSError otherwise."""
    descriptor = os.open(name, _FILE_FLAGS, dir_fd=directory)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise OSError("not a regular file of ours")
    except BaseException:
        _close(descriptor)
        raise
    return descriptor


def _default_name(keyrings: int) -> Optional[str]:
    """The keyring named in ``keyrings/default`` (one trailing LF stripped);
    FALLBACK_KEYRING when there is no such file; None when anything is off."""
    try:
        descriptor = _open_own_file(keyrings, DEFAULT_FILE)
    except FileNotFoundError:
        return FALLBACK_KEYRING
    except OSError:
        return None
    try:
        if os.fstat(descriptor).st_size > _MAX_DEFAULT_SIZE:
            return None
        content = os.read(descriptor, _MAX_DEFAULT_SIZE + 1)
    except OSError:
        return None
    finally:
        _close(descriptor)
    if len(content) > _MAX_DEFAULT_SIZE:
        return None
    if content.endswith(b"\n"):
        content = content[:-1]
    try:
        name = content.decode("ascii")
    except UnicodeDecodeError:
        return None
    return name if valid_keyring_name(name) else None


def _header_class(keyrings: int, name: str) -> str:
    """One read of at most HEADER_SIZE bytes of ``<name>.keyring``; the rest is never read."""
    try:
        descriptor = _open_own_file(keyrings, name + KEYRING_SUFFIX)
    except OSError:
        return "unknown"
    try:
        head = os.read(descriptor, HEADER_SIZE)
    except OSError:
        return "unknown"
    finally:
        _close(descriptor)
    if head.startswith(PLAIN_HEADER):
        return "plain"
    if head.startswith(ENCRYPTED_HEADER):
        return "encrypted"
    return "unknown"


def keyring_default(environ=None) -> tuple[Optional[str], str]:
    """(default keyring name or None, "plain" | "encrypted" | "unknown"): how gnome-keyring stores it on disk.

    The base is ``$XDG_DATA_HOME`` when absolute, else ``~/.local/share`` (it
    may be a link, it must be ours); ``keyrings/`` must be a real directory of
    ours. Anything odd is "unknown" (the UI warns then, too). It describes
    gnome-keyring's files: another Secret Service (KeePassXC, ksecretd) with a
    stale gnome file left may be misdescribed (plan risk, documented).
    """
    keyrings = base = None
    try:
        base = open_base(data_base(environ), create=False)
        if base is None:
            return None, "unknown"
        keyrings = open_child_dir(base, KEYRINGS_DIR, create=False)
        if keyrings is None:
            return None, "unknown"
        name = _default_name(keyrings)
        if name is None:
            return None, "unknown"
        return name, _header_class(keyrings, name)
    except (HelperError, OSError):
        return None, "unknown"
    finally:
        _close(keyrings)
        _close(base)


def keyring_storage(environ=None) -> str:
    """"plain", "encrypted" or "unknown" (see ``keyring_default``)."""
    return keyring_default(environ)[1]


__all__ = [
    "AUTO_LOOKUP_TIMEOUT", "BUSCTL", "ITEM", "ITEM_NEW", "ITEMS", "KEY_LENGTH", "LABEL", "REPORTED", "SLOT_FILE", "SLOT_NAMES", "SLOT_NEW",
    "SLOT_OLD", "STORAGE", "TOOL", "TOOLS",
    "check_argv", "clear_argv", "clear_item", "collection_locked", "collection_path", "copy_item", "find_tools", "forget",
    "is_lookup_argv", "item_exists", "item_paths", "keyring_default", "keyring_storage", "locked_argv", "lookup_argv", "lookup_into_pipe",
    "remove_items", "search_argv", "store_argv", "store_new_key",
]
