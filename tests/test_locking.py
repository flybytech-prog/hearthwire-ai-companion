import fcntl
import os
import stat

import pytest

from hearthwire.core import locking
from hearthwire.core.locking import (
    CredentialLockTimeout,
    credential_lock,
    lock_directory,
)


def test_lock_creates_private_directory_and_empty_file(_private_runtime_dir):
    with credential_lock("claude"):
        directory = _private_runtime_dir / "hearthwire"
        lock_file = directory / "claude.lock"
        assert stat.S_IMODE(os.lstat(directory).st_mode) == 0o700
        assert stat.S_IMODE(os.lstat(lock_file).st_mode) == 0o600
    assert lock_file.read_bytes() == b""


def test_lock_falls_back_to_per_user_temp_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(locking.tempfile, "gettempdir", lambda: str(tmp_path))
    expected = tmp_path / f"hearthwire-{os.getuid()}"
    assert lock_directory() == expected
    with credential_lock("codex"):
        assert (expected / "codex.lock").exists()
    assert stat.S_IMODE(os.lstat(expected).st_mode) == 0o700


def test_relative_runtime_dir_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(locking.tempfile, "gettempdir", lambda: str(tmp_path))
    assert lock_directory({"XDG_RUNTIME_DIR": "relative/run"}) == (
        tmp_path / f"hearthwire-{os.getuid()}"
    )


def test_world_writable_lock_directory_is_best_effort(_private_runtime_dir):
    directory = _private_runtime_dir / "hearthwire"
    directory.mkdir(mode=0o700)
    directory.chmod(0o777)
    ran = False
    with credential_lock("grok"):
        ran = True
    assert ran
    assert not (directory / "grok.lock").exists()


def test_symlinked_lock_directory_is_best_effort(_private_runtime_dir, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir(mode=0o700)
    (_private_runtime_dir / "hearthwire").symlink_to(target)
    ran = False
    with credential_lock("grok"):
        ran = True
    assert ran
    assert not (target / "grok.lock").exists()


def test_lock_times_out_while_another_descriptor_holds_it(_private_runtime_dir):
    with credential_lock("claude"):
        pass
    path = _private_runtime_dir / "hearthwire" / "claude.lock"
    holder = os.open(path, os.O_RDWR)
    fcntl.flock(holder, fcntl.LOCK_EX)
    clock = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    try:
        with pytest.raises(CredentialLockTimeout):
            with credential_lock(
                "claude",
                timeout=1.0,
                sleep=sleep,
                monotonic=lambda: clock[0],
            ):
                pytest.fail("lock body must not run")
    finally:
        os.close(holder)
    assert sleeps and all(item == pytest.approx(0.1) for item in sleeps)
    assert clock[0] >= 1.0

    with credential_lock("claude", timeout=0.0):
        pass


def test_lock_is_released_after_exception(_private_runtime_dir):
    with pytest.raises(RuntimeError):
        with credential_lock("devin"):
            raise RuntimeError("body failed")
    with credential_lock("devin", timeout=0.0):
        pass


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError):
        with credential_lock("../../etc/passwd"):
            pass
