from __future__ import annotations

import errno
import fcntl
import os
import stat
import tempfile
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Optional

from .catalog import PROVIDER_IDS


_POLL_INTERVAL = 0.1
_WOULD_BLOCK = {errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES}


class CredentialLockTimeout(Exception):
    """Another process held the provider credential lock for too long."""


def lock_directory(environ: Optional[Mapping[str, str]] = None) -> Path:
    values = os.environ if environ is None else environ
    runtime = values.get("XDG_RUNTIME_DIR") or ""
    if runtime and os.path.isabs(runtime) and os.path.isdir(runtime):
        return Path(runtime) / "hearthwire"
    return Path(tempfile.gettempdir()) / f"hearthwire-{os.getuid()}"


def _private_directory(directory: Path) -> bool:
    try:
        os.mkdir(directory, 0o700)
    except FileExistsError:
        pass
    except OSError:
        return False
    try:
        info = os.lstat(directory)
    except OSError:
        return False
    return (
        stat.S_ISDIR(info.st_mode)
        and not stat.S_ISLNK(info.st_mode)
        and info.st_uid == os.getuid()
        and info.st_mode & 0o077 == 0
    )


def _open_lock_file(provider_id: str, environ: Optional[Mapping[str, str]]) -> int:
    """Return a descriptor for the lock file, or -1 when locking is unavailable."""
    directory = lock_directory(environ)
    if not _private_directory(directory):
        return -1
    flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(directory / f"{provider_id}.lock", flags, 0o600)
    except OSError:
        return -1
    try:
        info = os.fstat(descriptor)
    except OSError:
        os.close(descriptor)
        return -1
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        os.close(descriptor)
        return -1
    return descriptor


@contextmanager
def credential_lock(
    provider_id: str,
    *,
    timeout: float = 30.0,
    environ: Optional[Mapping[str, str]] = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> Iterator[None]:
    """Serialize credential refreshes for one provider across processes.

    The lock file stays empty; only its advisory ``flock`` matters. When the
    lock directory or file cannot be created safely, the body still runs
    without a lock, and compare-before-write remains the last line of defense.
    """
    if provider_id not in PROVIDER_IDS:
        raise ValueError("Unsupported provider for credential lock.")
    descriptor = _open_lock_file(provider_id, environ)
    if descriptor < 0:
        yield
        return

    locked = False
    try:
        deadline = monotonic() + timeout
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError as error:
                if error.errno not in _WOULD_BLOCK:
                    break
            if monotonic() >= deadline:
                raise CredentialLockTimeout()
            sleep(_POLL_INTERVAL)
        yield
    finally:
        if locked:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(descriptor)
