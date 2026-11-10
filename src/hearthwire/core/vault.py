"""Passphrase-encrypted folder for the Chat tab's saved sign-ins (gocryptfs).

Layout: the cipher directory is ``$XDG_DATA_HOME/hearthwire/vault/`` and the
plaintext view is mounted at ``$XDG_RUNTIME_DIR/hearthwire/vault/`` (tmpfs, so
anything written after an unmount lands in RAM, never on disk).

The passphrase never passes through this process. gocryptfs runs kdialog
itself (``-extpass``) and reads the answer from kdialog's stdout. Changing the
passphrase hands the second kdialog's stdout to gocryptfs's stdin through a
pipe whose ends this process only holds, never reads. Every child gets an
argv list with no shell and stdin/stdout/stderr on /dev/null. The exceptions
are those pipe ends and the version line of ``gocryptfs -version``. Streams
must be /dev/null: the gocryptfs daemon keeps whatever it inherited until
unmount, so a pipe would block its reader (Plasma's DataSource) for hours.

A mount is trusted only after ``/proc/self/mountinfo`` shows our gocryptfs
mount of our cipher directory, owned by us and without ``allow_other``.
Replies are short state or error codes: never paths, names or counts.

Besides the passphrase (``gocryptfs.conf``, always kept as the recovery slot)
the folder may have a KDE Wallet key slot, ``vault-keys/wallet.conf``: a copy
of ``gocryptfs.conf`` re-keyed with ``gocryptfs -passwd -config`` to a random
key kept in the wallet (``walletkey.py``). That key, too, only ever moves
between children through pipes this process never reads.
"""

from __future__ import annotations

import errno
import fcntl
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import walletkey
from .webdata import (
    APP_DIR,
    PRIVATE_MODE,
    WEB_DIR,
    HelperError,
    _close,
    _descriptors,
    _require_safe_rmtree,
    data_base,
    open_base,
    open_child_dir,
    remove_entry,
)

OPERATIONS = (
    "status", "create", "unlock", "lock", "change-passphrase", "destroy",
    "add-key", "remove-key", "auto-unlock",
)
# Unlock methods (--method); add-key and remove-key take only "wallet".
METHODS = ("passphrase", "wallet")
METHOD_OPERATIONS = ("unlock", "add-key", "remove-key")
KEYS_DIR = walletkey.KEYS_DIR
VAULT_DIR = "vault"
LOCK_FILE = "vault.lock"
# Holds only the first -passwd dialog's exit status (see extpass_relay.py).
PASSWD_MARKER = "passwd.status"
RELAY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extpass_relay.py")
CONF_FILE = "gocryptfs.conf"
MOUNTINFO = "/proc/self/mountinfo"
# Non-interactive operations give up on a held lock after this long ("busy").
LOCK_TIMEOUT = 5.0
_POLL_INTERVAL = 0.1
_TOOL_TIMEOUT = 30.0
_WOULD_BLOCK = {errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES}


# =====================================================================================
# gocryptfs CONTRACT, measured against gocryptfs 2.6.1 (spike SP2, 2026-10-31). Flags,
# argv framing, exit codes, the -passwd flow and the mountpoint mode live in this block
# and nowhere else.
# =====================================================================================

# Tools that must all be found on PATH. "gocryptfs-v2" is reported when gocryptfs
# exists but `gocryptfs -version` does not say v2 or later.
TOOLS = ("gocryptfs", "kdialog", "fusermount3")
VERSION_ARGS = ("-version",)
VERSION_PREFIX = b"gocryptfs v"
MINIMUM_MAJOR = 2

# The bare mountpoint must be 0700 when mounting: fusermount3 refuses 0500 (exit 19,
# "no write access") and 0300 (exit 10). It is reset to 0700 under the vault lock right
# before each mount and sealed to 0500 after every unmount, so nothing can write into
# the tmpfs directory while the folder is locked.
MOUNTPOINT_MODE = 0o700
SEALED_MODE = 0o500

# Fixed English kdialog prompts (D26). None may start with "-".
TITLE = "Hearthwire"
PROMPT_CREATE = (
    "Choose a passphrase for the Hearthwire encrypted chat folder. "
    "If you forget it, the saved chat data cannot be recovered."
)
PROMPT_UNLOCK = "Enter the passphrase for the Hearthwire encrypted chat folder."
PROMPT_CURRENT = "Enter the current passphrase for the Hearthwire encrypted chat folder."
PROMPT_NEW = "Choose a new passphrase for the Hearthwire encrypted chat folder."

# Allow-list of the dash arguments each gocryptfs phase may pass, checked before every
# run; everything else (key material, -ko/-o mount options, -fsname, debug output,
# ...) is refused. "-version" is only ever the sole argument. "-config" is accepted
# only with the one key-slot path the caller computed (see _check_argv).
PHASE_FLAGS = {
    "init": frozenset({"-init", "-q", "-extpass"}),
    "mount": frozenset({"-q", "-nosyslog", "-extpass", "-config"}),
    "passwd": frozenset({"-passwd", "-q", "-extpass", "-config"}),
}
# Positional arguments (absolute paths) per phase: the cipher dir, plus the mountpoint.
PHASE_POSITIONALS = {"init": 1, "mount": 2, "passwd": 1}

# gocryptfs exit code -> error code, per operation; anything unlisted gets the
# operation's fallback. Measured: 12 wrong passphrase; 9 cancelled, and also an
# empty passphrase (22 was never seen, so empty is reported as "cancelled");
# 10 mountpoint missing, not empty or unreadable; 6 cipher dir missing, or on
# -init not empty / already initialised (extpass not called); 11 no
# gocryptfs.conf; 19 fusermount3 refused, or already mounted ("busy" when a
# mount is present afterwards, see _mount).
#
# With the wallet slot (spike KS1): mounting with -config wallet.conf and kwallet-query
# as extpass, 9 means the extpass failed (any kwallet-query error or an empty value:
# denied, cancelled, locked, no entry) and 12 that the wallet's value does not fit
# the slot; 11 is a missing slot file. Re-keying the copy (-passwd -config), 24 is
# gocryptfs's own "<config>.tmp" being in the way (it writes that, fsyncs and
# renames over the copy).
EXIT_CODES = {
    "init": {6: "exists", 9: "cancelled"},
    "mount": {6: "absent", 9: "cancelled", 10: "mount-failed", 11: "absent", 12: "wrong-passphrase",
              19: "mount-failed"},
    "passwd": {6: "absent", 9: "cancelled", 11: "absent", 12: "wrong-passphrase"},
    "wallet-mount": {6: "absent", 9: "wallet-failed", 10: "mount-failed", 11: "not-set-up",
                     12: "wallet-mismatch", 19: "mount-failed"},
    "wallet-passwd": {6: "absent", 9: "cancelled", 11: "absent", 12: "wrong-passphrase",
                      24: "wallet-write-failed"},
}
EXIT_FALLBACK = {"init": "init-failed", "mount": "mount-failed", "passwd": "os-error",
                 "wallet-mount": "mount-failed", "wallet-passwd": "wallet-write-failed"}
EXIT_ALREADY_MOUNTED = 19

# gocryptfs -passwd calls extpass ONCE, for the old passphrase (with stdin on
# /dev/null), then reads the new one as a single line from its own stdin; no
# confirmation, a second line is ignored. A wrong old passphrase exits 12 without
# reading stdin; an empty or closed stdin exits 9. So the old one comes from
# kdialog --password through extpass_relay.py, and only after that dialog has
# exited does kdialog --newpassword start, writing into gocryptfs's stdin.
# After a correct-looking first answer gocryptfs still needs a moment to check it:
# wait this long for an early exit (wrong passphrase) before opening the second
# dialog; a later exit closes that dialog again.
PASSWD_GRACE = 1.0

# Lock: plain `fusermount3 -u`, never -z. WebEngine releases its files about a
# second after the chat profile is destroyed (SP1), so a busy unmount is retried
# after these delays, then reported as "busy". The lazy unmount of plan D24 stays
# an unimplemented fallback: SP1 showed it is not needed, and the helper cannot
# tell its own widget's leftover files from another widget's live chat.
UNMOUNT_RETRY_DELAYS = (0.5, 1.0)


def extpass_args(program: str, *arguments: str) -> list[str]:
    """``-extpass <arg>`` for the program and each of its arguments.

    Each argument is its own argv element. Because there are several, gocryptfs
    does not split them on spaces. gocryptfs turns every single-dash argument
    into a double-dash one ("dash duplication"), so a value like ``-X`` would
    arrive as ``--X``; such values are refused.
    """
    result = []
    for argument in (program, *arguments):
        if _single_dash(argument):
            raise HelperError("os-error")
        result += ["-extpass", argument]
    return result


def _single_dash(argument: str) -> bool:
    return argument.startswith("-") and not argument.startswith("--")


def init_argv(gocryptfs: str, kdialog: str, cipher: str) -> list[str]:
    # Without -q, -init prints the master key on stdout; -q silences it and stdout is
    # /dev/null anyway (D22).
    return [gocryptfs, "-init", "-q", *extpass_args(kdialog, "--title", TITLE, "--newpassword", PROMPT_CREATE), cipher]


def mount_argv(gocryptfs: str, kdialog: str, cipher: str, mountpoint: str) -> list[str]:
    return [
        gocryptfs, "-q", "-nosyslog",
        *extpass_args(kdialog, "--title", TITLE, "--password", PROMPT_UNLOCK),
        cipher, mountpoint,
    ]


def passwd_argv(gocryptfs: str, python: str, marker: str, kdialog: str, cipher: str) -> list[str]:
    """``gocryptfs -passwd``; its extpass is the relay running the old-passphrase dialog."""
    relay = extpass_args(python, RELAY, marker, kdialog, "--title", TITLE, "--password", PROMPT_CURRENT)
    return [gocryptfs, "-passwd", "-q", *relay, cipher]


def wallet_mount_argv(gocryptfs: str, kwallet_query: str, wallet: str, config: str, cipher: str,
                      mountpoint: str) -> list[str]:
    """Mount with the wallet slot; gocryptfs runs ``kwallet-query -r`` itself (no dialog of ours)."""
    return [
        gocryptfs, "-q", "-nosyslog", "-config", config,
        *extpass_args(*walletkey.read_argv(kwallet_query, wallet)),
        cipher, mountpoint,
    ]


def wallet_passwd_argv(gocryptfs: str, kdialog: str, config: str, cipher: str) -> list[str]:
    """Re-key the slot copy: the old passphrase via kdialog, the new key on stdin (a pipe)."""
    return [
        gocryptfs, "-passwd", "-q", "-config", config,
        *extpass_args(kdialog, "--title", TITLE, "--password", PROMPT_CURRENT),
        cipher,
    ]


def new_passphrase_argv(kdialog: str) -> list[str]:
    """The second -passwd dialog; its stdout is gocryptfs's stdin."""
    return [kdialog, "--title", TITLE, "--newpassword", PROMPT_NEW]


def unmount_argv(fusermount: str, mountpoint: str) -> list[str]:
    return [fusermount, "-u", mountpoint]


def exit_error(phase: str, code: int) -> str:
    return EXIT_CODES[phase].get(code, EXIT_FALLBACK[phase])


# =====================================================================================
# End of the gocryptfs contract.
# =====================================================================================


@dataclass(frozen=True)
class Context:
    tools: dict[str, str]
    missing: tuple[str, ...]
    data_base: str
    cipher: str
    runtime: str
    mountpoint: str
    # kwallet-query, qdbus6 and openssl when found; the missing walletkey.TOOLS.
    wallet_tools: dict[str, str] = field(default_factory=dict)
    wallet_missing: tuple[str, ...] = ()

    @property
    def slot(self) -> str:
        return os.path.join(self.data_base, APP_DIR, KEYS_DIR, walletkey.SLOT_FILE)

    @property
    def new_slot(self) -> str:
        return os.path.join(self.data_base, APP_DIR, KEYS_DIR, walletkey.SLOT_NEW)


@dataclass(frozen=True)
class MountEntry:
    mountpoint: str
    mount_options: tuple[str, ...]
    fstype: str
    source: str
    super_options: tuple[str, ...]


# --- children ---------------------------------------------------------------------------


def _gocryptfs_phase(arguments: Sequence[str]) -> str:
    if "-init" in arguments:
        return "init"
    if "-passwd" in arguments:
        return "passwd"
    return "mount"


def _check_extpass(values: Sequence[str]) -> None:
    """The extpass program is kdialog, the relay, or exactly ``kwallet-query -r``."""
    if not values:
        return
    program = os.path.basename(values[0])
    if program == "kwallet-query":
        if not walletkey.is_read_argv(values):
            raise HelperError("os-error")
    elif program == "kdialog":
        if not os.path.isabs(values[0]):
            raise HelperError("os-error")
    elif not (len(values) > 1 and values[1] == RELAY and os.path.isabs(values[0])):
        raise HelperError("os-error")


def _check_gocryptfs_argv(arguments: Sequence[str], config: Optional[str]) -> None:
    if list(arguments) == list(VERSION_ARGS):
        return
    phase = _gocryptfs_phase(arguments)
    allowed = PHASE_FLAGS[phase]
    positionals = 0
    configs = 0
    extpass = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        index += 1
        if argument == "-extpass":
            # A dialog argument (a path or prompt), not a gocryptfs flag; it must not
            # start with a single dash (dash duplication).
            if index >= len(arguments) or _single_dash(arguments[index]):
                raise HelperError("os-error")
            extpass.append(arguments[index])
            index += 1
            continue
        if argument.startswith("-"):
            if argument not in allowed:
                raise HelperError("os-error")
            if argument == "-config":
                # Only the key-slot path the caller computed and checked.
                if config is None or index >= len(arguments) or arguments[index] != config:
                    raise HelperError("os-error")
                configs += 1
                index += 1
            continue
        if not os.path.isabs(argument):
            raise HelperError("os-error")
        positionals += 1
    if positionals != PHASE_POSITIONALS[phase] or configs > 1:
        raise HelperError("os-error")
    _check_extpass(extpass)


def _check_argv(argv: Sequence[str], *, config: Optional[str] = None) -> None:
    """Refuse any child argv that is not one of the contract's shapes (defence in depth).

    gocryptfs gets only its phase's allow-listed flags; fusermount3 only ``-u
    <mountpoint>``; kdialog only the new-passphrase dialog (the other dialogs run
    as ``-extpass`` values). No argument outside an ``-extpass`` value may
    contain ``allow_``, wherever it sits.
    """
    if not argv or not os.path.isabs(argv[0]):
        raise HelperError("os-error")
    tool = os.path.basename(argv[0])
    arguments = list(argv[1:])
    plain = []
    index = 0
    while index < len(arguments):
        if arguments[index] == "-extpass" and tool == "gocryptfs":
            index += 2
            continue
        plain.append(arguments[index])
        index += 1
    if any("allow_" in argument for argument in plain):
        raise HelperError("os-error")
    if tool == "gocryptfs":
        _check_gocryptfs_argv(arguments, config)
    elif tool == "fusermount3":
        if len(arguments) != 2 or arguments[0] != "-u" or not os.path.isabs(arguments[1]):
            raise HelperError("os-error")
    elif tool == "kdialog":
        if arguments != new_passphrase_argv(argv[0])[1:]:
            raise HelperError("os-error")
    elif tool in ("kwallet-query", *walletkey.QDBUS_NAMES, "openssl"):
        walletkey.check_argv(argv)
    else:
        raise HelperError("os-error")


def _run(argv: Sequence[str], *, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
         timeout: Optional[float] = None, config: Optional[str] = None,
         timeout_error: str = "os-error") -> int:
    """Run one child: argv list, no shell, stderr always on /dev/null."""
    _check_argv(argv, config=config)
    try:
        completed = subprocess.run(
            list(argv),
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise HelperError(timeout_error) from None
    except OSError:
        raise HelperError("missing-tool") from None
    return completed.returncode


def _spawn(argv: Sequence[str], *, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
           env: Optional[Mapping[str, str]] = None) -> subprocess.Popen:
    """Start one child without waiting: argv list, no shell, stderr on /dev/null."""
    _check_argv(argv)
    try:
        return subprocess.Popen(
            list(argv),
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            env=None if env is None else dict(env),
        )
    except OSError:
        raise HelperError("missing-tool") from None


def relay_environment(environ: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    """The environment for ``gocryptfs -passwd``, inherited by the Python relay.

    gocryptfs starts the relay as a plain script, so no ``-I``: every ``PYTHON*``
    variable is dropped (no PYTHONPATH, PYTHONSTARTUP, PYTHONHOME, ...), the
    user site directory stays off ``sys.path`` and so does the script's own
    directory (``PYTHONSAFEPATH``, Python 3.11+).
    """
    values = os.environ if environ is None else environ
    clean = {key: value for key, value in values.items() if not key.startswith("PYTHON")}
    clean["PYTHONNOUSERSITE"] = "1"
    clean["PYTHONSAFEPATH"] = "1"
    return clean


def _stop(child: subprocess.Popen) -> None:
    """Close a dialog that is no longer wanted; reap it either way."""
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=_TOOL_TIMEOUT)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def _gocryptfs_major(gocryptfs: str) -> int:
    """Major version from ``gocryptfs -version`` (0 when unknown).

    The version line is read from a private pipe; it holds no user data.
    """
    reader, writer = os.pipe()
    try:
        try:
            code = _run([gocryptfs, *VERSION_ARGS], stdout=writer, timeout=_TOOL_TIMEOUT)
        finally:
            os.close(writer)
            writer = -1
        if code != 0:
            return 0
        os.set_blocking(reader, False)
        try:
            head = os.read(reader, 256)
        except BlockingIOError:
            return 0
    except HelperError:
        return 0
    finally:
        _close(reader)
        _close(writer)
    if not head.startswith(VERSION_PREFIX):
        return 0
    digits = head[len(VERSION_PREFIX):].split(b".", 1)[0]
    return int(digits) if digits.isdigit() else 0


def _find_tools() -> tuple[dict[str, str], tuple[str, ...]]:
    found: dict[str, str] = {}
    missing: list[str] = []
    for name in TOOLS:
        path = shutil.which(name)
        if path and os.path.isabs(path):
            found[name] = path
        else:
            missing.append(name)
        # A relative PATH entry gives a relative result: treated as not found above.
        if name == "gocryptfs" and name in found and _gocryptfs_major(found[name]) < MINIMUM_MAJOR:
            missing.append("gocryptfs-v2")
    return found, tuple(missing)


# --- paths --------------------------------------------------------------------------------


def runtime_dir(environ: Optional[Mapping[str, str]] = None) -> str:
    """``$XDG_RUNTIME_DIR`` when it is absolute, a real directory, ours and 0700."""
    values = os.environ if environ is None else environ
    value = values.get("XDG_RUNTIME_DIR") or ""
    if not value or not os.path.isabs(value):
        raise HelperError("no-runtime-dir")
    try:
        info = os.lstat(value)
    except OSError:
        raise HelperError("no-runtime-dir") from None
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise HelperError("no-runtime-dir")
    return os.path.realpath(value)


def context(environ: Optional[Mapping[str, str]] = None, *, find_tools: bool = True) -> Context:
    tools, missing = _find_tools() if find_tools else ({}, ())
    wallet_tools, wallet_missing = walletkey.find_tools() if find_tools else ({}, ())
    runtime = runtime_dir(environ)
    base = os.path.realpath(data_base(environ))
    return Context(
        tools=tools,
        missing=missing,
        data_base=base,
        cipher=os.path.join(base, APP_DIR, VAULT_DIR),
        runtime=runtime,
        mountpoint=os.path.join(runtime, APP_DIR, VAULT_DIR),
        wallet_tools=wallet_tools,
        wallet_missing=wallet_missing,
    )


def _require_tools(ctx: Context, *names: str) -> None:
    wanted = names or TOOLS
    if any(name not in ctx.tools for name in wanted) or (
        "gocryptfs" in wanted and "gocryptfs-v2" in ctx.missing
    ):
        raise HelperError("missing-tool")


# --- lock -----------------------------------------------------------------------------------


@contextmanager
def _runtime_app_dir(ctx: Context, app_dir: str = APP_DIR) -> Iterator[int]:
    with _descriptors() as opened:
        runtime = open_base(ctx.runtime, create=False)
        if runtime is None:
            raise HelperError("no-runtime-dir")
        opened.append(runtime)
        app = open_child_dir(runtime, app_dir, create=True)
        opened.append(app)
        yield app


@contextmanager
def vault_lock(
    ctx: Context,
    *,
    wait: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    app_dir: str = APP_DIR,
) -> Iterator[int]:
    """Hold ``$XDG_RUNTIME_DIR/hearthwire/vault.lock``; yields that directory's fd.

    With ``wait`` it blocks as long as needed (an unlock dialog may be open in
    another widget); otherwise a lock held past ``LOCK_TIMEOUT`` gives "busy".
    ``app_dir`` is only for the installer's migration (core/legacy.py), which
    also holds the former name's lock.
    """
    with _runtime_app_dir(ctx, app_dir) as app:
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            descriptor = os.open(LOCK_FILE, flags, 0o600, dir_fd=app)
        except OSError as error:
            raise (HelperError("symlink") if error.errno == errno.ELOOP else HelperError("os-error")) from None
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise HelperError("not-directory" if stat.S_ISDIR(info.st_mode) else "os-error")
            if info.st_uid != os.getuid():
                raise HelperError("not-owned")
            if wait:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            else:
                deadline = monotonic() + LOCK_TIMEOUT
                while True:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError as error:
                        if error.errno not in _WOULD_BLOCK:
                            raise HelperError("os-error") from None
                    if monotonic() >= deadline:
                        raise HelperError("busy")
                    sleep(_POLL_INTERVAL)
            yield app
        finally:
            _close(descriptor)


# --- mountinfo -----------------------------------------------------------------------------


def _unescape(field: str) -> str:
    """Undo the kernel's octal escapes (``\\040`` space, ``\\011``, ``\\012``, ``\\134``)."""
    out = []
    index = 0
    while index < len(field):
        chunk = field[index:index + 4]
        if len(chunk) == 4 and chunk[0] == "\\" and all(c in "01234567" for c in chunk[1:]):
            out.append(chr(int(chunk[1:], 8)))
            index += 4
        else:
            out.append(field[index])
            index += 1
    return "".join(out)


def parse_mountinfo(text: str) -> list[MountEntry]:
    entries = []
    for line in text.splitlines():
        fields = line.split(" ")
        try:
            separator = fields.index("-", 6)
        except ValueError:
            continue
        if len(fields) < separator + 4:
            continue
        entries.append(MountEntry(
            mountpoint=_unescape(fields[4]),
            mount_options=tuple(fields[5].split(",")),
            fstype=fields[separator + 1],
            source=_unescape(fields[separator + 2]),
            super_options=tuple(fields[separator + 3].split(",")),
        ))
    return entries


def mount_entry(mountpoint: str) -> Optional[MountEntry]:
    """The top-most mount at ``mountpoint``, or None."""
    try:
        with open(MOUNTINFO, encoding="utf-8", errors="surrogateescape") as handle:
            text = handle.read()
    except OSError:
        raise HelperError("os-error") from None
    found = None
    for entry in parse_mountinfo(text):
        if entry.mountpoint == mountpoint:
            found = entry
    return found


def entry_is_ours(entry: MountEntry, ctx: Context) -> bool:
    options = set(entry.super_options) | set(entry.mount_options)
    return (
        entry.fstype == "fuse.gocryptfs"
        and entry.source == ctx.cipher
        and f"user_id={os.getuid()}" in entry.super_options
        and not any(option.split("=", 1)[0] in {"allow_other", "allow_root"} for option in options)
    )


def _open_mount_root(app: int) -> int:
    """Open the mountpoint below ``app``; raises OSError (ENOTCONN when stale)."""
    return os.open(VAULT_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=app)


def _same_device(root: os.stat_result, parent: os.stat_result) -> bool:
    return root.st_dev == parent.st_dev


def _verified_root(ctx: Context, app: int, entry: MountEntry) -> int:
    """An fd for the mount root after every check passed; else not-verified."""
    if not entry_is_ours(entry, ctx):
        raise HelperError("not-verified")
    try:
        root = _open_mount_root(app)
    except OSError as error:
        if error.errno == errno.ENOTCONN:
            raise HelperError("stale-mount") from None
        raise HelperError("not-verified") from None
    try:
        info = os.fstat(root)
        parent = os.fstat(app)
    except OSError:
        _close(root)
        raise HelperError("not-verified") from None
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or _same_device(info, parent)
    ):
        _close(root)
        raise HelperError("not-verified")
    return root


# --- state ------------------------------------------------------------------------------------


def _cipher_state(ctx: Context) -> str:
    """"locked" (gocryptfs.conf is there), "absent" (no or an empty cipher dir) or "damaged".

    "damaged" is a cipher dir that holds files but no regular gocryptfs.conf:
    gocryptfs can neither open it nor -init it, only destroy can clear it.
    """
    with _descriptors() as opened:
        parent = open_base(ctx.data_base, create=False)
        if parent is None:
            return "absent"
        opened.append(parent)
        for name in (APP_DIR, VAULT_DIR):
            parent = open_child_dir(parent, name, create=False)
            if parent is None:
                return "absent"
            opened.append(parent)
        try:
            info = os.stat(CONF_FILE, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            info = None
        except OSError:
            raise HelperError("os-error") from None
        if info is not None and stat.S_ISLNK(info.st_mode):
            raise HelperError("symlink")
        if info is not None and stat.S_ISREG(info.st_mode):
            return "locked"
        try:
            empty = info is None and not os.listdir(parent)
        except OSError:
            raise HelperError("os-error") from None
        return "absent" if empty else "damaged"


def _unmount(ctx: Context) -> int:
    fusermount = ctx.tools.get("fusermount3")
    if fusermount is None:
        raise HelperError("missing-tool")
    return _run(unmount_argv(fusermount, ctx.mountpoint), timeout=_TOOL_TIMEOUT)


def _seal_mountpoint(ctx: Context, app: int) -> None:
    """Make the bare (unmounted) mountpoint 0500; best effort.

    Only when nothing is mounted there: a chmod on a live mount would change the
    encrypted folder's root instead.
    """
    try:
        if mount_entry(ctx.mountpoint) is not None:
            return
        descriptor = open_child_dir(app, VAULT_DIR, create=False)
    except HelperError:
        return
    if descriptor is None:
        return
    try:
        os.fchmod(descriptor, SEALED_MODE)
    except OSError:
        pass
    finally:
        _close(descriptor)


def _clean_stale(ctx: Context, app: int) -> None:
    """Unmount a dead gocryptfs mount (its daemon died with plasmashell)."""
    if "fusermount3" not in ctx.tools:
        raise HelperError("stale-mount")
    if _unmount(ctx) != 0 or mount_entry(ctx.mountpoint) is not None:
        raise HelperError("stale-mount")
    _seal_mountpoint(ctx, app)


def _is_stale(app: int) -> bool:
    try:
        descriptor = _open_mount_root(app)
    except OSError as error:
        return error.errno == errno.ENOTCONN
    _close(descriptor)
    return False


def settle(ctx: Context, app: int) -> str:
    """Current state ("absent", "locked", "unlocked", "damaged"), cleaning up a stale mount.

    Must run under ``vault_lock``. A mount that fails verification raises
    not-verified; nothing may use it.
    """
    entry = mount_entry(ctx.mountpoint)
    if entry is not None:
        if _is_stale(app):
            _clean_stale(ctx, app)
        else:
            _close(_verified_root(ctx, app, entry))
            return "unlocked"
    return _cipher_state(ctx)


@contextmanager
def verified_mount(environ: Optional[Mapping[str, str]] = None) -> Iterator[int]:
    """Yield an fd for the verified, unlocked mount root, holding the vault lock.

    Runs no tool: a stale or foreign mount is simply not-verified.
    """
    ctx = context(environ, find_tools=False)
    with vault_lock(ctx) as app:
        entry = mount_entry(ctx.mountpoint)
        if entry is None or _is_stale(app):
            raise HelperError("not-verified")
        root = _verified_root(ctx, app, entry)
        try:
            yield root
        finally:
            _close(root)


# --- operations --------------------------------------------------------------------------------


def _refuse_legacy_data(environ: Optional[Mapping[str, str]]) -> None:
    """legacy-data while the former name's data folder is still there (plan D5).

    Setting up, unlocking or purging now would create or use a second folder
    next to the one the installer still has to move; only the installer migrates.
    """
    from . import legacy  # Imported here: legacy itself builds on this module.

    if legacy.legacy_data_present(environ):
        raise HelperError("legacy-data")


def status(environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    ctx = context(environ)
    if ctx.missing:
        return {"ok": True, "state": "unavailable", "missing": list(ctx.missing)}
    with vault_lock(ctx) as app:
        state = settle(ctx, app)
        slot = _slot_present(ctx) if state in ("locked", "unlocked") else False
    reply: dict[str, object] = {"ok": True, "state": state}
    if state in ("locked", "unlocked"):
        # Outside the lock: a qdbus6 query may take up to its timeout.
        if ctx.wallet_missing:
            reply["wallet"] = "unavailable"
        elif walletkey.is_enabled(ctx.wallet_tools["qdbus6"]) is not True:
            reply["wallet"] = "unavailable"
        else:
            reply["wallet"] = "set-up" if slot else "off"
        # openssl is needed only to set up or remove the key, so it is listed but
        # never makes the wallet method unavailable.
        missing = [*ctx.wallet_missing,
                   *([walletkey.KEYGEN_TOOL] if walletkey.KEYGEN_TOOL not in ctx.wallet_tools else [])]
        if missing:
            reply["missing"] = missing
    return reply


# --- key slots (vault-keys/) ---------------------------------------------------------------------


@contextmanager
def _keys_dir(ctx: Context, *, create: bool) -> Iterator[Optional[int]]:
    """``$XDG_DATA_HOME/hearthwire/vault-keys`` (0700), opened without following links.

    Yields None when it (or a parent) does not exist and ``create`` is false.
    """
    with _descriptors() as opened:
        base = open_base(ctx.data_base, create=create)
        if base is None:
            yield None
            return
        opened.append(base)
        app = open_child_dir(base, APP_DIR, create=create)
        if app is None:
            yield None
            return
        opened.append(app)
        keys = open_child_dir(app, KEYS_DIR, create=create)
        if keys is not None:
            opened.append(keys)
        yield keys


def _slot_ready(keys: int) -> bool:
    """wallet.conf is a regular file of ours, mode 0400 (as gocryptfs writes it)."""
    try:
        info = os.stat(walletkey.SLOT_FILE, dir_fd=keys, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError:
        raise HelperError("os-error") from None
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == walletkey.SLOT_MODE
    )


def _slot_present(ctx: Context) -> bool:
    """For status: a usable wallet slot; anything odd in the way counts as none."""
    try:
        with _keys_dir(ctx, create=False) as keys:
            return keys is not None and _slot_ready(keys)
    except HelperError:
        return False


def _unlink(keys: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=keys)
    except FileNotFoundError:
        pass
    except IsADirectoryError:
        raise HelperError("not-directory") from None
    except OSError:
        raise HelperError("os-error") from None


def _clear_new_slot(keys: int) -> None:
    for name in (walletkey.SLOT_NEW, walletkey.SLOT_NEW + walletkey.GOCRYPTFS_TEMPORARY_SUFFIX):
        _unlink(keys, name)


def _remove_slot(keys: int) -> None:
    _clear_new_slot(keys)
    _unlink(keys, walletkey.SLOT_OLD)
    _unlink(keys, walletkey.SLOT_FILE)


_MAX_CONF_SIZE = 65536


def _copy_conf(ctx: Context, keys: int) -> None:
    """Copy ``gocryptfs.conf`` to ``vault-keys/wallet.conf.new`` (O_EXCL, 0600, fsynced).

    The conf holds the master key wrapped by the passphrase (gocryptfs keeps it
    0400 inside the 0700 cipher dir); the copy gets the same protection.
    """
    read_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    write_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    with _descriptors() as opened:
        parent = open_base(ctx.data_base, create=False)
        if parent is None:
            raise HelperError("absent")
        opened.append(parent)
        for name in (APP_DIR, VAULT_DIR):
            parent = open_child_dir(parent, name, create=False)
            if parent is None:
                raise HelperError("absent")
            opened.append(parent)
        try:
            source = os.open(CONF_FILE, read_flags, dir_fd=parent)
        except FileNotFoundError:
            raise HelperError("absent") from None
        except OSError as error:
            raise (HelperError("symlink") if error.errno == errno.ELOOP else HelperError("os-error")) from None
        opened.append(source)
        info = os.fstat(source)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > _MAX_CONF_SIZE:
            raise HelperError("os-error")
        content = b""
        while len(content) <= _MAX_CONF_SIZE:
            chunk = os.read(source, _MAX_CONF_SIZE + 1)
            if not chunk:
                break
            content += chunk
        if not content or len(content) > _MAX_CONF_SIZE:
            raise HelperError("os-error")
        try:
            target = os.open(walletkey.SLOT_NEW, write_flags, 0o600, dir_fd=keys)
        except OSError:
            raise HelperError("wallet-write-failed") from None
        opened.append(target)
        view = memoryview(content)
        while view:
            written = os.write(target, view)
            view = view[written:]
        os.fsync(target)


def _seal_new_slot(keys: int) -> None:
    """Make the re-keyed copy 0400 and fsync it (it stays wallet.conf.new)."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    try:
        descriptor = os.open(walletkey.SLOT_NEW, flags, dir_fd=keys)
    except OSError:
        raise HelperError("wallet-write-failed") from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size == 0:
            raise HelperError("wallet-write-failed")
        if stat.S_IMODE(info.st_mode) != walletkey.SLOT_MODE:
            os.fchmod(descriptor, walletkey.SLOT_MODE)
        os.fsync(descriptor)
    except OSError:
        raise HelperError("wallet-write-failed") from None
    finally:
        _close(descriptor)


def _slot_exists(keys: int) -> bool:
    try:
        os.stat(walletkey.SLOT_FILE, dir_fd=keys, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError:
        raise HelperError("os-error") from None
    return True


def _rename(keys: int, source: str, target: str) -> None:
    os.rename(source, target, src_dir_fd=keys, dst_dir_fd=keys)


def _commit_slot(ctx: Context, keys: int, wallet: str) -> None:
    """Swap the keyed copy and the staged key in; on failure put the old ones back.

    1. wallet.conf (if any) becomes wallet.conf.old, wallet.conf.new becomes
       wallet.conf.
    2. The staged key is copied to the real entry (kwallet-query -r into a
       pipe, then -w from it; never read here).
    3. Only then wallet.conf.old goes. If step 2 fails, the new slot goes back
       to wallet.conf.new and wallet.conf.old back to wallet.conf, so the old
       slot and entry keep working (unless kwallet-query -w changed the real
       entry before it failed).
    """
    _seal_new_slot(keys)
    had_old = _slot_exists(keys)
    try:
        if had_old:
            _rename(keys, walletkey.SLOT_FILE, walletkey.SLOT_OLD)
        _rename(keys, walletkey.SLOT_NEW, walletkey.SLOT_FILE)
        os.fsync(keys)
    except OSError:
        raise HelperError("wallet-write-failed") from None
    try:
        walletkey.copy_entry(ctx.wallet_tools, wallet, walletkey.ENTRY_NEW, walletkey.ENTRY)
    except HelperError:
        try:
            _rename(keys, walletkey.SLOT_FILE, walletkey.SLOT_NEW)
            if had_old:
                _rename(keys, walletkey.SLOT_OLD, walletkey.SLOT_FILE)
            os.fsync(keys)
        except OSError:
            pass
        raise
    _unlink(keys, walletkey.SLOT_OLD)
    try:
        os.fsync(keys)
    except OSError:
        pass


def _wallet_tools(ctx: Context, *, keygen: bool) -> None:
    if ctx.wallet_missing or (keygen and walletkey.KEYGEN_TOOL not in ctx.wallet_tools):
        raise HelperError("missing-tool")


def _drop_staged_entry(ctx: Context, wallet: str) -> None:
    """Delete the staging entry when it is there (best effort; never prompts while
    the wallet is unlocked)."""
    try:
        if walletkey.key_missing(ctx.wallet_tools["qdbus6"], wallet, walletkey.ENTRY_NEW) is False:
            walletkey.remove_entry(ctx.wallet_tools, wallet, entry=walletkey.ENTRY_NEW)
    except HelperError:
        pass


def add_key(environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    """Set up (or replace) the wallet slot; the folder may be locked or unlocked (D66).

    Everything is staged first, so a failed re-setup (Cancel, wrong passphrase,
    a wallet error) leaves a working slot and entry as they were:

    1. Copy gocryptfs.conf to vault-keys/wallet.conf.new.
    2. ``openssl rand -hex 32`` -> ``kwallet-query -w encrypted-chat-folder.new``.
    3. ``kwallet-query -r encrypted-chat-folder.new`` into a pipe; only after it
       exited 0 does that pipe become the stdin of ``gocryptfs -passwd -config
       wallet.conf.new``, whose extpass is the current-passphrase dialog.
    4. Every exit status 0: _commit_slot swaps the slot and the entry in.
    5. The staging entry is overwritten and deleted, on success and failure.
    """
    ctx = context(environ)
    _require_tools(ctx, "gocryptfs", "kdialog")
    _wallet_tools(ctx, keygen=True)
    _refuse_legacy_data(environ)
    with vault_lock(ctx, wait=True) as app:
        state = settle(ctx, app)
        if state in ("absent", "damaged"):
            raise HelperError(state)
        wallet = walletkey.preflight(ctx.wallet_tools)
        with _keys_dir(ctx, create=True) as keys:
            if keys is None:
                raise HelperError("os-error")
            _clear_new_slot(keys)
            if _slot_exists(keys):
                # Left by an interrupted swap: wallet.conf is the newer one.
                _unlink(keys, walletkey.SLOT_OLD)
            try:
                _copy_conf(ctx, keys)
            except (HelperError, OSError):
                _clear_new_slot(keys)
                raise
            try:
                walletkey.write_new_key(ctx.wallet_tools, wallet, entry=walletkey.ENTRY_NEW)
                reader = walletkey.read_key_into_pipe(ctx.wallet_tools["kwallet-query"], wallet,
                                                      entry=walletkey.ENTRY_NEW)
                try:
                    argv = wallet_passwd_argv(ctx.tools["gocryptfs"], ctx.tools["kdialog"], ctx.new_slot, ctx.cipher)
                    code = _run(argv, stdin=reader, config=ctx.new_slot)
                finally:
                    _close(reader)
                if code != 0:
                    raise HelperError(exit_error("wallet-passwd", code))
                _commit_slot(ctx, keys, wallet)
            except (HelperError, OSError) as error:
                _clear_new_slot(keys)
                # A wallet that did not answer is not asked again; a leftover
                # staging entry is removed by the next set-up or removal.
                if not (isinstance(error, HelperError) and error.code == "wallet-failed"):
                    _drop_staged_entry(ctx, wallet)
                raise
            _drop_staged_entry(ctx, wallet)
    return {"ok": True}


def remove_key(environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    """Delete the wallet slot, then overwrite and delete the wallet entry and any
    staging entry left by an interrupted set-up.

    The slot goes first in every case; an error after that means an entry may
    still be in the wallet (the reply says which: missing-tool, wallet-disabled,
    wallet-failed). openssl is not needed: without it the overwrite is skipped.
    """
    ctx = context(environ)
    with vault_lock(ctx, wait=True):
        with _keys_dir(ctx, create=False) as keys:
            if keys is not None:
                _remove_slot(keys)
        _wallet_tools(ctx, keygen=False)
        wallet = walletkey.preflight(ctx.wallet_tools)
        walletkey.remove_entries(ctx.wallet_tools, wallet)
    return {"ok": True}


def _unlock_with_wallet(ctx: Context, app: int, *, automatic: bool) -> None:
    """Pre-flight (non-secret qdbus6 answers only), then mount with the wallet slot.

    ``automatic`` (Plasma start): unless the Secret Service says the wallet's
    collection is unlocked, nothing more runs and the reply is wallet-closed,
    so there is never a password prompt at login.
    """
    wallet = walletkey.preflight(ctx.wallet_tools)
    with _keys_dir(ctx, create=False) as keys:
        if keys is None or not _slot_ready(keys):
            raise HelperError("not-set-up")
    qdbus = ctx.wallet_tools["qdbus6"]
    if automatic and walletkey.wallet_locked(qdbus, wallet) is not False:
        raise HelperError("wallet-closed")
    missing = walletkey.key_missing(qdbus, wallet)
    if missing is None:
        raise HelperError("wallet-failed")
    if missing:
        raise HelperError("not-set-up")
    _mount(ctx, app, wallet)


def auto_unlock(environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    ctx = context(environ)
    _require_tools(ctx, "gocryptfs", "fusermount3")
    _wallet_tools(ctx, keygen=False)
    _refuse_legacy_data(environ)
    with vault_lock(ctx) as app:
        state = settle(ctx, app)
        if state in ("absent", "damaged"):
            raise HelperError(state)
        if state == "locked":
            _unlock_with_wallet(ctx, app, automatic=True)
    return {"ok": True}


def verify_wallet_slot(ctx: Context, app: int, wallet: str) -> bool:
    """Mount with the wallet slot, then unmount again; True when both worked.

    For the installer's migration only (core/legacy.py), which already holds the
    vault lock (``app`` is its directory) and checked that nothing is mounted.
    It proves that the wallet entry opens this folder's slot: a real unlock,
    as the widget would do it. Any failure is False, never a reply of its own;
    raises os-error only when the folder stays mounted.
    """
    if settle(ctx, app) != "locked":
        return False
    try:
        with _keys_dir(ctx, create=False) as keys:
            if keys is None or not _slot_ready(keys):
                return False
        _mount(ctx, app, wallet)
    except HelperError:
        if mount_entry(ctx.mountpoint) is not None:
            _drop_mount(ctx, app)
            if mount_entry(ctx.mountpoint) is not None:
                raise HelperError("os-error") from None
        return False
    for delay in (*UNMOUNT_RETRY_DELAYS, None):
        if _unmount(ctx) == 0 and mount_entry(ctx.mountpoint) is None:
            _seal_mountpoint(ctx, app)
            return True
        if delay is None:
            break
        time.sleep(delay)
    raise HelperError("os-error")


# Leftovers the bare mountpoint may hold: profile folders a widget's chat created in
# the tmpfs directory after another widget locked the folder under it.
_LEFTOVER_PROFILE = re.compile(r"applet-(0|[1-9][0-9]*)-g(0|[1-9][0-9]*)")


def _leftover_profiles(mountpoint: int) -> Optional[list[str]]:
    """Names below ``web/`` when that is all the bare mountpoint holds, else None."""
    try:
        if os.listdir(mountpoint) != [WEB_DIR]:
            return None
        web = open_child_dir(mountpoint, WEB_DIR, create=False)
    except (HelperError, OSError):
        return None
    if web is None:
        return None
    try:
        names = os.listdir(web)
        for name in names:
            if _LEFTOVER_PROFILE.fullmatch(name) is None:
                return None
            info = os.stat(name, dir_fd=web, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                return None
    except OSError:
        return None
    finally:
        _close(web)
    return names


def _clear_leftovers(mountpoint: int) -> None:
    """Delete ``web/applet-*`` leftovers from the bare mountpoint; anything else: mount-failed.

    Runs under the vault lock with nothing mounted, so these are tmpfs files
    written after a lock, never the encrypted folder's contents. Every entry is
    checked before any is deleted; nothing is followed.
    """
    names = _leftover_profiles(mountpoint)
    if names is None:
        raise HelperError("mount-failed")
    _require_safe_rmtree()
    with _descriptors() as opened:
        web = open_child_dir(mountpoint, WEB_DIR, create=False)
        if web is None:
            raise HelperError("mount-failed")
        opened.append(web)
        for name in names:
            remove_entry(web, name)
    try:
        os.rmdir(WEB_DIR, dir_fd=mountpoint)
        if os.listdir(mountpoint):
            raise HelperError("mount-failed")
    except OSError:
        raise HelperError("mount-failed") from None


def _prepare_mountpoint(app: int) -> None:
    descriptor = open_child_dir(app, VAULT_DIR, create=True, mode=MOUNTPOINT_MODE)
    try:
        if os.listdir(descriptor):
            _clear_leftovers(descriptor)
    except OSError:
        raise HelperError("os-error") from None
    finally:
        _close(descriptor)


def _drop_mount(ctx: Context, app: int) -> None:
    """Unmount whatever came up after a failed or unverified mount; best effort."""
    try:
        if mount_entry(ctx.mountpoint) is None:
            _seal_mountpoint(ctx, app)
        elif _unmount(ctx) == 0:
            _seal_mountpoint(ctx, app)
    except HelperError:
        pass


def _mount(ctx: Context, app: int, wallet: Optional[str] = None) -> None:
    """Mount with the passphrase dialog, or with the wallet slot when ``wallet`` is given."""
    # Under the vault lock, right before mounting: 0700 (a sealed 0500 one is reset).
    _prepare_mountpoint(app)
    if wallet is None:
        phase = "mount"
        code = _run(mount_argv(ctx.tools["gocryptfs"], ctx.tools["kdialog"], ctx.cipher, ctx.mountpoint))
    else:
        phase = "wallet-mount"
        argv = wallet_mount_argv(ctx.tools["gocryptfs"], ctx.wallet_tools["kwallet-query"], wallet,
                                 ctx.slot, ctx.cipher, ctx.mountpoint)
        try:
            # kwallet-query may wait for KWallet's own password prompt.
            code = _run(argv, timeout=walletkey.PROMPT_TIMEOUT, config=ctx.slot, timeout_error="wallet-failed")
        except HelperError:
            _drop_mount(ctx, app)
            raise
    if code != 0:
        mounted = mount_entry(ctx.mountpoint) is not None
        if not mounted:
            _seal_mountpoint(ctx, app)
        if code == EXIT_ALREADY_MOUNTED and mounted:
            raise HelperError("busy")
        raise HelperError(exit_error(phase, code))
    entry = mount_entry(ctx.mountpoint)
    if entry is None:
        _seal_mountpoint(ctx, app)
        raise HelperError("mount-failed")
    try:
        _close(_verified_root(ctx, app, entry))
    except HelperError:
        # Never leave an unverified mount behind.
        try:
            if _unmount(ctx) == 0:
                _seal_mountpoint(ctx, app)
        except HelperError:
            pass
        raise HelperError("not-verified") from None


def _make_cipher_dir(ctx: Context) -> bool:
    """Create the empty cipher dir; True when this call created it."""
    with _descriptors() as opened:
        base = open_base(ctx.data_base, create=True)
        opened.append(base)
        app = open_child_dir(base, APP_DIR, create=True)
        opened.append(app)
        try:
            os.stat(VAULT_DIR, dir_fd=app, follow_symlinks=False)
            created = False
        except FileNotFoundError:
            created = True
        except OSError:
            raise HelperError("os-error") from None
        cipher = open_child_dir(app, VAULT_DIR, create=True)
        opened.append(cipher)
        return created


def _forget_cipher_dir(ctx: Context) -> None:
    """Remove the cipher dir again after a failed -init, only if still empty."""
    with _descriptors() as opened:
        base = open_base(ctx.data_base, create=False)
        if base is None:
            return
        opened.append(base)
        app = open_child_dir(base, APP_DIR, create=False)
        if app is None:
            return
        opened.append(app)
        try:
            os.rmdir(VAULT_DIR, dir_fd=app)
        except OSError:
            pass


def create(environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    ctx = context(environ)
    _require_tools(ctx)
    _refuse_legacy_data(environ)
    with vault_lock(ctx, wait=True) as app:
        state = settle(ctx, app)
        if state == "damaged":
            raise HelperError("damaged")
        if state != "absent":
            raise HelperError("exists")
        # A wallet slot left from an older folder could never open the new one.
        _remove_keys_dir(ctx)
        created = _make_cipher_dir(ctx)
        code = _run(init_argv(ctx.tools["gocryptfs"], ctx.tools["kdialog"], ctx.cipher))
        if code != 0:
            if created:
                _forget_cipher_dir(ctx)
            raise HelperError(exit_error("init", code))
        _mount(ctx, app)
    return {"ok": True}


def unlock(environ: Optional[Mapping[str, str]] = None, method: str = "passphrase") -> dict[str, object]:
    if method not in METHODS:
        raise ValueError("Unsupported unlock method.")
    ctx = context(environ)
    if method == "wallet":
        _require_tools(ctx, "gocryptfs", "fusermount3")
        _wallet_tools(ctx, keygen=False)
    else:
        _require_tools(ctx)
    _refuse_legacy_data(environ)
    with vault_lock(ctx, wait=True) as app:
        state = settle(ctx, app)
        if state in ("absent", "damaged"):
            raise HelperError(state)
        if state == "locked":
            if method == "wallet":
                _unlock_with_wallet(ctx, app, automatic=False)
            else:
                _mount(ctx, app)
    return {"ok": True}


def lock(environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    ctx = context(environ)
    with vault_lock(ctx) as app:
        entry = mount_entry(ctx.mountpoint)
        if entry is None:
            _seal_mountpoint(ctx, app)
            return {"ok": True}
        if _is_stale(app):
            _clean_stale(ctx, app)
            return {"ok": True}
        if not entry_is_ours(entry, ctx):
            raise HelperError("not-verified")
        for delay in (*UNMOUNT_RETRY_DELAYS, None):
            if _unmount(ctx) == 0 and mount_entry(ctx.mountpoint) is None:
                _seal_mountpoint(ctx, app)
                return {"ok": True}
            if delay is None:
                break
            time.sleep(delay)
        # Still in use (another widget's chat, open files): never forced.
        raise HelperError("busy")


def _clear_marker(app: int) -> None:
    for name in (PASSWD_MARKER, PASSWD_MARKER + ".tmp"):
        try:
            os.unlink(name, dir_fd=app)
        except FileNotFoundError:
            pass
        except OSError:
            raise HelperError("os-error") from None


def _read_marker(app: int) -> Optional[int]:
    """The first dialog's exit status once the relay published it, else None.

    The marker holds a number written by extpass_relay.py, never a passphrase.
    """
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    try:
        descriptor = os.open(PASSWD_MARKER, flags, dir_fd=app)
    except FileNotFoundError:
        return None
    except OSError:
        raise HelperError("os-error") from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise HelperError("os-error")
        head = os.read(descriptor, 8).strip()
    except OSError:
        raise HelperError("os-error") from None
    finally:
        _close(descriptor)
    return int(head) if head.isdigit() else None


def _first_dialog_status(app: int, child: subprocess.Popen) -> Optional[int]:
    """Wait for the old-passphrase dialog to exit; None when gocryptfs exited first."""
    while child.poll() is None:
        status = _read_marker(app)
        if status is not None:
            return status
        time.sleep(_POLL_INTERVAL)
    return None


def _exited_within(child: subprocess.Popen, seconds: float) -> bool:
    try:
        child.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        return False
    return True


def _passwd(ctx: Context, app: int) -> int:
    """Run ``gocryptfs -passwd``; returns its exit code.

    1. gocryptfs starts with stdin = the pipe's read end. Its extpass (the
       relay) shows kdialog --password; the old passphrase goes from kdialog's
       stdout to gocryptfs directly.
    2. Once the relay reports that dialog exited OK, and gocryptfs is still
       running after PASSWD_GRACE (it exits at once on a wrong passphrase),
       kdialog --newpassword starts with stdout = the pipe's write end.
    3. This process closes its copy of the write end, so a cancelled second
       dialog gives gocryptfs EOF (exit 9). It never reads the pipe.
    """
    python = sys.executable
    if not python or not os.path.isabs(python) or not os.path.isfile(RELAY):
        raise HelperError("missing-tool")
    marker = os.path.join(ctx.runtime, APP_DIR, PASSWD_MARKER)
    argv = passwd_argv(ctx.tools["gocryptfs"], python, marker, ctx.tools["kdialog"], ctx.cipher)
    _check_argv(argv)
    _clear_marker(app)
    reader, writer = os.pipe()
    child: Optional[subprocess.Popen] = None
    dialog: Optional[subprocess.Popen] = None
    try:
        child = _spawn(argv, stdin=reader, env=relay_environment())
        os.close(reader)
        reader = -1
        status = _first_dialog_status(app, child)
        if status == 0 and not _exited_within(child, PASSWD_GRACE):
            dialog = _spawn(new_passphrase_argv(ctx.tools["kdialog"]), stdout=writer)
        os.close(writer)
        writer = -1
        code = child.wait()
    finally:
        _close(reader)
        _close(writer)
        if dialog is not None:
            # gocryptfs is done (or failed early): a dialog still open is useless.
            _stop(dialog)
        if child is not None and child.poll() is None:
            child.kill()
            child.wait()
        _clear_marker(app)
    return code


def change_passphrase(environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    ctx = context(environ)
    _require_tools(ctx, "gocryptfs", "kdialog")
    with vault_lock(ctx, wait=True) as app:
        state = settle(ctx, app)
        if state in ("absent", "damaged"):
            raise HelperError(state)
        if state != "locked":
            raise HelperError("not-locked")
        code = _passwd(ctx, app)
        if code != 0:
            raise HelperError(exit_error("passwd", code))
    return {"ok": True}


def _holds_wallet_slot(keys: int) -> bool:
    """``keys`` (an opened vault-keys) holds a wallet slot file of ours: wallet.conf,
    or the wallet.conf.old / wallet.conf.new an interrupted set-up leaves.

    Only then does the wallet entry belong to this data folder; a stray or
    empty vault-keys (another XDG_DATA_HOME, a copied folder) does not, and
    destroy/purge then leave the wallet alone. Symlinks and files of other
    users do not count.
    """
    for name in (walletkey.SLOT_FILE, walletkey.SLOT_OLD, walletkey.SLOT_NEW):
        try:
            info = os.stat(name, dir_fd=keys, follow_symlinks=False)
        except OSError:
            continue
        if stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid():
            return True
    return False


def _app_holds_wallet_slot(data_app: int) -> bool:
    """For destroy: vault-keys below ``data_app`` holds a slot (anything odd: no)."""
    try:
        keys = open_child_dir(data_app, KEYS_DIR, create=False)
    except HelperError:
        return False
    if keys is None:
        return False
    try:
        return _holds_wallet_slot(keys)
    finally:
        _close(keys)


def _remove_keys_dir(ctx: Context) -> None:
    with _descriptors() as opened:
        base = open_base(ctx.data_base, create=False)
        data_app = None if base is None else open_child_dir(base, APP_DIR, create=False)
        opened.extend(fd for fd in (base, data_app) if fd is not None)
        if data_app is not None:
            remove_entry(data_app, KEYS_DIR)


def destroy(environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    """Delete the cipher dir, the key slots and the bare mountpoint, then the wallet entry.

    The wallet entry is removed only when this data folder had a wallet slot
    (checked before anything is deleted). The files go first; wallet-failed
    afterwards means only the wallet entry may remain (remove-key removes it).
    """
    ctx = context(environ)
    _require_safe_rmtree()
    with vault_lock(ctx) as app:
        if settle(ctx, app) == "unlocked":
            raise HelperError("not-locked")
        had_slot = False
        with _descriptors() as opened:
            base = open_base(ctx.data_base, create=False)
            data_app = None if base is None else open_child_dir(base, APP_DIR, create=False)
            opened.extend(fd for fd in (base, data_app) if fd is not None)
            if data_app is not None:
                had_slot = _app_holds_wallet_slot(data_app)
                remove_entry(data_app, VAULT_DIR)
                remove_entry(data_app, KEYS_DIR)
        # Not mounted (checked above), so this is the bare tmpfs mountpoint.
        remove_entry(app, VAULT_DIR)
        if had_slot:
            walletkey.forget(ctx.wallet_tools)
    return {"ok": True}


# --- purge (scripts/install.sh --uninstall-web-data) -------------------------------------------

# What purge may delete below $XDG_DATA_HOME/hearthwire, in reply order: the
# encrypted folder's ciphertext (saved sign-ins exist nowhere else; there is no
# unencrypted store) and its key slots. The wallet entry is reported after them.
PURGE_CATEGORIES = (VAULT_DIR, KEYS_DIR)
PURGE_WALLET_ENTRY = "wallet-entry"
# Where systemd puts XDG_RUNTIME_DIR; also checked when the variable is unset
# (e.g. install.sh run from a TTY), so a live mount is never missed.
DEFAULT_RUNTIME = "/run/user/{uid}"


def _purge_runtimes(environ: Optional[Mapping[str, str]]) -> list[str]:
    runtimes = []
    for values in (environ, {"XDG_RUNTIME_DIR": DEFAULT_RUNTIME.format(uid=os.getuid())}):
        try:
            runtime = runtime_dir(values)
        except HelperError:
            continue
        if runtime not in runtimes:
            runtimes.append(runtime)
    return runtimes


def mounted_any(environ: Optional[Mapping[str, str]] = None, app_dirs: Sequence[str] = (APP_DIR,)) -> bool:
    """Any mount (ours, foreign or stale) of a cipher dir or at a mountpoint of ``app_dirs``.

    Looks at every runtime dir purge would (``$XDG_RUNTIME_DIR`` and the
    systemd default) and at the data base as given and resolved. The
    installer's migration passes the former and the current name.
    """
    runtimes = _purge_runtimes(environ)
    base_path = data_base(environ)
    cipher_paths = {
        os.path.join(base, name, VAULT_DIR)
        for base in (base_path, os.path.realpath(base_path)) for name in app_dirs
    }
    mountpoints = {os.path.join(runtime, name, VAULT_DIR) for runtime in runtimes for name in app_dirs}
    return _vault_mounted(cipher_paths, mountpoints)


def _vault_mounted(cipher_paths: set[str], mountpoints: set[str]) -> bool:
    """Any mount (ours, foreign or stale) at our mountpoint or of our cipher dir."""
    try:
        with open(MOUNTINFO, encoding="utf-8", errors="surrogateescape") as handle:
            text = handle.read()
    except OSError:
        raise HelperError("os-error") from None
    return any(
        entry.mountpoint in mountpoints or entry.source in cipher_paths
        for entry in parse_mountinfo(text)
    )


def _purge_tree(environ: Optional[Mapping[str, str]], runtimes: list[str]) -> list[str]:
    base_path = data_base(environ)
    cipher_paths = {
        os.path.join(base, APP_DIR, VAULT_DIR) for base in (base_path, os.path.realpath(base_path))
    }
    mountpoints = {os.path.join(runtime, APP_DIR, VAULT_DIR) for runtime in runtimes}
    if _vault_mounted(cipher_paths, mountpoints):
        raise HelperError("not-locked")
    present: list[str] = []
    had_slot = False
    with _descriptors() as opened:
        base = open_base(base_path, create=False)
        app = None if base is None else open_child_dir(base, APP_DIR, create=False)
        opened.extend(fd for fd in (base, app) if fd is not None)
        # Check every category before deleting any: a symlink, file or foreign
        # directory in the way refuses the whole purge.
        for name in PURGE_CATEGORIES if app is not None else ():
            child = open_child_dir(app, name, create=False)
            if child is not None:
                try:
                    if name == KEYS_DIR:
                        had_slot = _holds_wallet_slot(child)
                finally:
                    _close(child)
                present.append(name)
        for name in present:
            remove_entry(app, name)
        if app is not None:
            try:
                os.rmdir(APP_DIR, dir_fd=base)
            except OSError:
                pass  # Not empty or already gone: leave it.
    # Last, so the files are gone even when the wallet cannot be reached; a
    # wallet-failed reply means only the entry may remain. Only a folder that
    # had a wallet slot owns the entry: without one the wallet is not touched.
    if not had_slot:
        return present
    tools, _missing = walletkey.find_tools()
    if walletkey.forget(tools):
        present.append(PURGE_WALLET_ENTRY)
    return present


def purge(environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    """Delete the encrypted folder (every saved chat sign-in is inside it) and its key slots.

    Refuses while anything is mounted at the vault mountpoint or from the
    cipher dir. Runs no tool except, when this folder had a wallet slot,
    kwallet-query and qdbus6 are there and the wallet holds our entry, the ones
    that overwrite and delete it. The
    reply names only the deleted categories.
    """
    try:
        _require_safe_rmtree()
        _refuse_legacy_data(environ)
        runtimes = _purge_runtimes(environ)
        if not runtimes:
            return {"ok": True, "removed": _purge_tree(environ, runtimes)}
        # Hold the vault lock so an unlock in another widget cannot race us.
        values = os.environ if environ is None else environ
        ctx = context({**values, "XDG_RUNTIME_DIR": runtimes[0]}, find_tools=False)
        with vault_lock(ctx):
            return {"ok": True, "removed": _purge_tree(environ, runtimes)}
    except HelperError as error:
        return {"ok": False, "error": error.code}
    except OSError:
        return {"ok": False, "error": "os-error"}


_HANDLERS: dict[str, Callable[[Optional[Mapping[str, str]]], dict[str, object]]] = {
    "status": status,
    "create": create,
    "unlock": unlock,
    "lock": lock,
    "change-passphrase": change_passphrase,
    "destroy": destroy,
    "add-key": add_key,
    "remove-key": remove_key,
    "auto-unlock": auto_unlock,
}


def run(
    operation: str,
    environ: Optional[Mapping[str, str]] = None,
    method: Optional[str] = None,
) -> dict[str, object]:
    """CLI entry: a reply object that never contains a path or name.

    ``method`` is only for unlock (passphrase|wallet, default passphrase) and
    add-key / remove-key (wallet only, the default).
    """
    handler = _HANDLERS.get(operation)
    if handler is None:
        raise ValueError("Unsupported vault operation.")
    if method is not None and (operation not in METHOD_OPERATIONS or method not in METHODS
                               or (operation != "unlock" and method != "wallet")):
        raise ValueError("Unsupported unlock method.")
    try:
        if operation == "unlock" and method is not None:
            return unlock(environ, method)
        return handler(environ)
    except HelperError as error:
        return {"ok": False, "error": error.code}
    except OSError:
        return {"ok": False, "error": "os-error"}


__all__ = ["METHODS", "OPERATIONS", "PRIVATE_MODE", "mounted_any", "purge", "run", "status", "verified_mount",
           "verify_wallet_slot"]
