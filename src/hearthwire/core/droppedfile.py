"""Read one text file dropped on the Chat tab (``--read-dropped HEX``, plan D63).

QML cannot read files, so for a single local ``file://`` drop it passes the
path's UTF-8 bytes hex-encoded (argv holds only ``[0-9a-f]``, nothing a shell
or argparse could misread). The reply is the file's text, never its path.

Only small regular text files are read: the last path component may not be a
symlink (``O_NOFOLLOW``), FIFOs, devices and directories are refused before
anything is opened (and ``O_NONBLOCK`` keeps a swapped-in FIFO from blocking),
and the size must be 1..131072 bytes, which also refuses ``/proc`` files
(they report size 0). Files on kernel pseudo-filesystems (proc, sysfs,
efivarfs, debugfs, ...) are refused by filesystem type, looked up in
``/proc/self/mountinfo`` before the file is opened; when mountinfo cannot be
read or names no filesystem for the file, nothing is read. The text must be
strict UTF-8 without
NUL characters and at most 32000 characters. Runs no program, writes nothing.
"""

from __future__ import annotations

import errno
import os
import re
import stat
from typing import Optional

MAX_BYTES = 131072
MAX_CHARS = 32000
MAX_HEX = 8192
HEX_PATH = re.compile(r"(?:[0-9a-f]{2}){1,%d}" % (MAX_HEX // 2))

_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOCTTY


class DropError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def decode_path(value: str) -> Optional[bytes]:
    """The absolute path bytes from lowercase hex, or None when it is not one."""
    if not isinstance(value, str) or HEX_PATH.fullmatch(value) is None:
        return None
    path = bytes.fromhex(value)
    if not path.startswith(b"/") or b"\x00" in path:
        return None
    return path


def _open_error(error: OSError) -> DropError:
    if error.errno in (errno.ENOENT, errno.ENOTDIR):
        return DropError("absent")
    if error.errno in (errno.EACCES, errno.EPERM):
        return DropError("unreadable")
    if error.errno == errno.ELOOP:
        return DropError("not-file")
    return DropError("os-error")


# Kernel interfaces, never user files: sysfs attributes report size 4096,
# efivarfs variables their real size, so the size check alone is not enough.
PSEUDO_FILESYSTEMS = frozenset({
    "proc", "sysfs", "efivarfs", "securityfs", "pstore", "debugfs", "tracefs", "cgroup", "cgroup2",
    "bpf", "configfs", "fusectl", "devpts", "mqueue", "hugetlbfs", "binfmt_misc", "autofs",
    "rpc_pipefs", "nsfs",
})
MOUNTINFO = "/proc/self/mountinfo"
MAX_MOUNTINFO = 16 * 1024 * 1024


def _read_mountinfo() -> bytes:
    """``/proc/self/mountinfo``; DropError (os-error) when it cannot be read whole."""
    try:
        descriptor = os.open(MOUNTINFO, os.O_RDONLY | os.O_CLOEXEC | os.O_NOCTTY)
    except OSError:
        raise DropError("os-error") from None
    try:
        chunks = []
        size = 0
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_MOUNTINFO:
                raise DropError("os-error")
            chunks.append(chunk)
    except OSError:
        raise DropError("os-error") from None
    finally:
        os.close(descriptor)
    return b"".join(chunks)


def _unescape(field: bytes) -> bytes:
    """Undo the kernel's octal escapes (``\\040`` space and the like)."""
    return re.sub(rb"\\([0-7]{3})", lambda match: bytes([int(match.group(1), 8) & 0xFF]), field)


def _mounts(text: bytes) -> list[tuple[int, int, bytes, str]]:
    """(major, minor, mount point, filesystem type) per mountinfo line."""
    mounts = []
    for line in text.splitlines():
        fields = line.split(b" ")
        try:
            separator = fields.index(b"-", 6)
            major, minor = (int(part) for part in fields[2].split(b":"))
        except ValueError:
            continue
        if len(fields) <= separator + 1:
            continue
        fstype = fields[separator + 1].decode("ascii", "replace")
        mounts.append((major, minor, _unescape(fields[4]), fstype))
    return mounts


def _under(path: bytes, mountpoint: bytes) -> bool:
    return mountpoint == b"/" or path == mountpoint or path.startswith(mountpoint.rstrip(b"/") + b"/")


def _filesystem_types(path: bytes, device: int) -> set[str]:
    """The filesystem type(s) the file is on.

    Every mount of the file's device number (bind mounts share it). A device
    no mount line names (a btrfs subvolume, say) falls back to the mount with
    the longest mount point above the file's real path. Fails closed: no
    mountinfo or no matching mount is DropError (os-error).
    """
    mounts = _mounts(_read_mountinfo())
    if not mounts:
        raise DropError("os-error")
    by_device = {fstype for major, minor, _point, fstype in mounts
                 if (major, minor) == (os.major(device), os.minor(device))}
    if by_device:
        return by_device
    real = os.path.realpath(path)
    best: Optional[tuple[int, str]] = None
    for _major, _minor, point, fstype in mounts:
        if _under(real, point) and (best is None or len(point) >= best[0]):
            best = (len(point), fstype)
    if best is None:
        raise DropError("os-error")
    return {best[1]}


def _check_size(info: os.stat_result) -> None:
    if not stat.S_ISREG(info.st_mode) or info.st_size == 0:
        raise DropError("not-file")
    if info.st_size > MAX_BYTES:
        raise DropError("too-large")


def _check_filesystem(path: bytes, info: os.stat_result) -> None:
    if _filesystem_types(path, info.st_dev) & PSEUDO_FILESYSTEMS:
        raise DropError("not-file")


def read_text(path: bytes) -> str:
    try:
        before = os.lstat(path)
    except OSError as error:
        raise _open_error(error) from None
    if stat.S_ISLNK(before.st_mode):
        raise DropError("not-file")
    _check_size(before)
    # Before the open: opening some debugfs or sysfs files has side effects.
    # The open below must then be the same file (device and inode).
    _check_filesystem(path, before)
    try:
        descriptor = os.open(path, _FLAGS)
    except OSError as error:
        raise _open_error(error) from None
    try:
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino):
            raise DropError("not-file")  # Swapped between the check and the open.
        _check_size(info)
        data = b""
        # One byte more than the size: a file that grew meanwhile is refused.
        while len(data) <= info.st_size:
            chunk = os.read(descriptor, info.st_size + 1 - len(data))
            if not chunk:
                break
            data += chunk
    except OSError as error:
        raise _open_error(error) from None
    finally:
        os.close(descriptor)
    if len(data) > info.st_size or len(data) > MAX_BYTES:
        raise DropError("too-large")
    if not data:
        raise DropError("not-file")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise DropError("not-text") from None
    if "\x00" in text:
        raise DropError("not-text")
    if len(text) > MAX_CHARS:
        raise DropError("too-long")
    return text


def run(value: str) -> dict[str, object]:
    """CLI entry: ``{"ok":true,"text":...}`` or a bare error code."""
    path = decode_path(value)
    if path is None:
        return {"ok": False, "error": "not-file"}
    try:
        return {"ok": True, "text": read_text(path)}
    except DropError as error:
        return {"ok": False, "error": error.code}
    except OSError:
        return {"ok": False, "error": "os-error"}


__all__ = ["MAX_BYTES", "MAX_CHARS", "decode_path", "read_text", "run"]
