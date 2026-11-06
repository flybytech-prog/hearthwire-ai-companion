from __future__ import annotations

import os
import stat
import uuid
from pathlib import Path
from typing import Optional


def atomic_write_private(
    path: Path,
    text: str,
    *,
    expected_text: Optional[str] = None,
) -> bool:
    """Atomically replace a private UTF-8 file if its contents are unchanged.

    When ``path`` is a symlink the write goes through to its final target so
    the link (e.g. a dotfiles-managed credential file) survives. The target
    must already exist as a regular file owned by the current user.
    """
    try:
        linked = path.is_symlink()
        target = Path(os.path.realpath(path)) if linked else path
        if linked:
            # Refuse dangling or looping links, non-files, and foreign files.
            info = os.stat(target)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                return False
        if expected_text is not None:
            current = target.read_text(encoding="utf-8")
            if current != expected_text:
                return False
        if not linked:
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except (OSError, UnicodeDecodeError):
        return False

    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
        return True
    except OSError:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except OSError:
            pass
        return False
