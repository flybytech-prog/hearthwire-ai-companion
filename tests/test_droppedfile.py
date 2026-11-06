"""Dropped text files (core/droppedfile.py) and --read-dropped."""

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from hearthwire import cli
from hearthwire.core import droppedfile

SOURCE = Path(droppedfile.__file__)


def hexpath(path):
    return os.fsencode(str(path)).hex()


def dropped(capsys, path):
    assert cli.main(["--read-dropped", hexpath(path)]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    return json.loads(captured.out)


def test_reads_a_text_file(tmp_path, capsys):
    path = tmp_path / "notes – ünïcode.txt"
    text = "Line one\nzwei – drei\n" * 400
    path.write_text(text)
    assert dropped(capsys, path) == {"ok": True, "text": text}


def test_the_reply_never_holds_the_path(tmp_path, capsys):
    path = tmp_path / "secret-name.txt"
    path.write_text("hello")
    assert cli.main(["--read-dropped", hexpath(path)]) == 0
    out = capsys.readouterr().out
    assert "secret-name" not in out and str(tmp_path) not in out
    assert cli.main(["--read-dropped", hexpath(tmp_path / "missing-name.txt")]) == 0
    out = capsys.readouterr().out
    assert out == '{"ok":false,"error":"absent"}\n'


@pytest.mark.parametrize(("size", "error"), [(32000, None), (32001, "too-long"), (131072, "too-long"),
                                             (131073, "too-large"), (10 * 1024 * 1024, "too-large")])
def test_size_and_length_caps(tmp_path, capsys, size, error):
    path = tmp_path / "f.txt"
    path.write_text("a" * size)
    expected = {"ok": True, "text": "a" * size} if error is None else {"ok": False, "error": error}
    assert dropped(capsys, path) == expected


def test_multibyte_text_counts_characters(tmp_path, capsys):
    path = tmp_path / "f.txt"
    path.write_text("€" * 32000)  # 96000 bytes, 32000 characters.
    assert dropped(capsys, path) == {"ok": True, "text": "€" * 32000}


@pytest.mark.parametrize("content", [b"\xff\xfe\x00binary", b"abc\x00def", b"\xc3", b"\xed\xa0\x80"])
def test_binary_is_not_text(tmp_path, capsys, content):
    path = tmp_path / "b.bin"
    path.write_bytes(content)
    assert dropped(capsys, path) == {"ok": False, "error": "not-text"}


def test_symlinks_are_refused_even_to_text(tmp_path, capsys):
    real = tmp_path / "real.txt"
    real.write_text("fine")
    link = tmp_path / "link.txt"
    link.symlink_to(real)
    assert dropped(capsys, link) == {"ok": False, "error": "not-file"}
    environ = tmp_path / "environ.txt"
    environ.symlink_to("/proc/self/environ")
    assert dropped(capsys, environ) == {"ok": False, "error": "not-file"}


@pytest.mark.parametrize("path", ["/proc/self/environ", "/proc/self/status", "/sys/kernel/mm/transparent_hugepage/enabled",
                                  "/dev/null", "/dev/zero"])
def test_proc_sys_and_devices_are_refused(capsys, path):
    if not os.path.exists(path):
        pytest.skip("not on this system")
    assert dropped(capsys, path) == {"ok": False, "error": "not-file"}


def test_a_fifo_is_refused_without_blocking(tmp_path):
    fifo = tmp_path / "pipe.txt"
    os.mkfifo(fifo)
    src = Path(__file__).resolve().parent.parent / "src"
    completed = subprocess.run(
        [sys.executable, "-P", "-m", "hearthwire", "--read-dropped", hexpath(fifo)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, check=False,
        env={**os.environ, "PYTHONPATH": str(src), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert (completed.returncode, completed.stderr) == (0, "")
    assert completed.stdout == '{"ok":false,"error":"not-file"}\n'


def test_directories_empty_files_missing_and_unreadable(tmp_path, capsys):
    assert dropped(capsys, tmp_path) == {"ok": False, "error": "not-file"}
    (tmp_path / "empty.txt").write_text("")
    assert dropped(capsys, tmp_path / "empty.txt") == {"ok": False, "error": "not-file"}
    assert dropped(capsys, tmp_path / "nope" / "x.txt") == {"ok": False, "error": "absent"}
    (tmp_path / "plain").write_text("x")
    assert dropped(capsys, tmp_path / "plain" / "x.txt") == {"ok": False, "error": "absent"}
    locked = tmp_path / "locked.txt"
    locked.write_text("secret")
    locked.chmod(0)
    try:
        if os.getuid() != 0:
            assert dropped(capsys, locked) == {"ok": False, "error": "unreadable"}
    finally:
        locked.chmod(0o600)


def test_a_file_swapped_after_the_check_is_refused(tmp_path, capsys, monkeypatch):
    path = tmp_path / "a.txt"
    path.write_text("first")
    other = tmp_path / "b.txt"
    other.write_text("second")
    real_open = os.open

    def swapping_open(target, flags, *args, **kwargs):
        if os.fsdecode(target) == str(path):  # Not the mountinfo read.
            os.replace(other, path)
        return real_open(target, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swapping_open)
    assert dropped(capsys, path) == {"ok": False, "error": "not-file"}


@pytest.mark.parametrize(
    "value",
    ["", "2F746d70", "2f7", "zz", "2f 74", "746d70", "2f0074", "2f" * 4097, "-2f", "0x2f", "2f\n"],
)
def test_hex_argument_rules(capsys, value):
    with pytest.raises(SystemExit) as raised:
        cli.main(["--read-dropped", value])
    assert raised.value.code == 2
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("extra", [["--vault", "status"], ["--json"], ["--port-owner", "1"],
                                   ["--web-data", "purge"], ["--store", "encrypted"], ["--method", "wallet"]])
def test_read_dropped_stands_alone(capsys, extra):
    with pytest.raises(SystemExit) as raised:
        cli.main(["--read-dropped", "2f", *extra])
    assert raised.value.code == 2
    assert capsys.readouterr().out == ""


def test_hex_limit_is_8192_characters():
    assert droppedfile.decode_path("2f" + "61" * 4095) == b"/" + b"a" * 4095
    assert droppedfile.decode_path("2f" + "61" * 4096) is None


def test_unexpected_errors_are_a_bare_code(tmp_path, capsys, monkeypatch):
    def boom(path):
        raise RuntimeError(f"secret {path}")

    monkeypatch.setattr(droppedfile, "read_text", boom)
    path = tmp_path / "x.txt"
    path.write_text("x")
    assert dropped(capsys, path) == {"ok": False, "error": "os-error"}


def test_droppedfile_runs_nothing_writes_nothing_prints_nothing():
    code = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(code)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert not node.level, "no relative imports"
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "errno", "os", "re", "stat", "typing"}, imported
    for pattern in (r"(?<![\w.])print\s*\(", r"\bsubprocess\b", r"\bos\.(write|unlink|remove|rename|mkdir|system|popen|spawn|exec)",
                    r"\bO_(WRONLY|RDWR|CREAT|TRUNC|APPEND)\b", r"(?<![\w.])open\s*\(", r"\bsys\."):
        assert not re.search(pattern, code), pattern
    for flag in ("O_RDONLY", "O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC"):
        assert flag in code


# --- filesystem type from mountinfo (a fake mountinfo file; real efivars are never read) -------


def _line(device, mountpoint, fstype, mount_id=30):
    major, minor = os.major(device), os.minor(device)
    point = os.fsencode(str(mountpoint)).replace(b" ", b"\\040").decode("utf-8", "surrogateescape")
    return f"{mount_id} 1 {major}:{minor} / {point} rw,relatime shared:1 - {fstype} none rw\n"


@pytest.fixture
def fake_mountinfo(tmp_path, monkeypatch):
    info = tmp_path / "mountinfo"
    monkeypatch.setattr(droppedfile, "MOUNTINFO", str(info))
    return info


def _text_file(tmp_path, name="notes.txt"):
    folder = tmp_path / "files"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_text("hello")
    return path


@pytest.mark.parametrize("fstype", sorted(droppedfile.PSEUDO_FILESYSTEMS))
def test_every_pseudo_filesystem_type_is_refused_by_device(tmp_path, capsys, fake_mountinfo, fstype):
    path = _text_file(tmp_path)
    device = os.stat(path).st_dev
    fake_mountinfo.write_text(_line(1, "/", "ext4", 1) + _line(device, "/sys/firmware/efi/efivars", fstype))
    assert dropped(capsys, path) == {"ok": False, "error": "not-file"}


def test_an_ordinary_filesystem_is_read(tmp_path, capsys, fake_mountinfo):
    path = _text_file(tmp_path)
    fake_mountinfo.write_text(_line(os.stat(path).st_dev, "/", "ext4"))
    assert dropped(capsys, path) == {"ok": True, "text": "hello"}


def test_a_bind_mount_of_a_pseudo_filesystem_is_refused(tmp_path, capsys, fake_mountinfo):
    # Same device twice: one line says ext4, the other efivarfs. Any pseudo type refuses.
    path = _text_file(tmp_path)
    device = os.stat(path).st_dev
    fake_mountinfo.write_text(_line(device, "/", "ext4", 1) + _line(device, str(tmp_path), "efivarfs", 2))
    assert dropped(capsys, path) == {"ok": False, "error": "not-file"}


def test_an_unknown_device_uses_the_longest_mount_point(tmp_path, capsys, fake_mountinfo):
    path = _text_file(tmp_path)
    other = os.makedev(4095, 4095)  # No real device; the file's own is not listed.
    folder = os.path.realpath(path.parent)
    fake_mountinfo.write_text(_line(other, "/", "ext4", 1) + _line(other, folder, "efivarfs", 2))
    assert dropped(capsys, path) == {"ok": False, "error": "not-file"}
    fake_mountinfo.write_text(_line(other, "/", "efivarfs", 1) + _line(other, folder, "btrfs", 2)
                              + _line(other, folder + "-sibling", "sysfs", 3))
    assert dropped(capsys, path) == {"ok": True, "text": "hello"}


def test_a_mount_point_with_a_space_is_unescaped(tmp_path, capsys, fake_mountinfo):
    folder = tmp_path / "with space"
    folder.mkdir()
    path = folder / "x.txt"
    path.write_text("hello")
    other = os.makedev(4095, 4095)
    fake_mountinfo.write_text(_line(other, "/", "ext4", 1) + _line(other, os.path.realpath(folder), "debugfs", 2))
    assert dropped(capsys, path) == {"ok": False, "error": "not-file"}


@pytest.mark.parametrize("content", [None, "", "garbage without fields\n", "1 2 x:y / / rw - ext4 a rw\n"])
def test_unreadable_or_useless_mountinfo_fails_closed(tmp_path, capsys, fake_mountinfo, content):
    path = _text_file(tmp_path)
    if content is not None:
        fake_mountinfo.write_text(content)
    assert dropped(capsys, path) == {"ok": False, "error": "os-error"}


def test_no_matching_mount_fails_closed(tmp_path, capsys, fake_mountinfo):
    path = _text_file(tmp_path)
    fake_mountinfo.write_text(_line(os.makedev(4095, 4095), "/nonexistent-root-elsewhere", "ext4"))
    assert dropped(capsys, path) == {"ok": False, "error": "os-error"}


def test_a_pseudo_file_is_never_opened(tmp_path, capsys, fake_mountinfo, monkeypatch):
    path = _text_file(tmp_path)
    fake_mountinfo.write_text(_line(os.stat(path).st_dev, "/", "efivarfs"))
    real_open = os.open
    opened = []

    def recording_open(target, flags, *args, **kwargs):
        opened.append(os.fsdecode(target))
        return real_open(target, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", recording_open)
    assert dropped(capsys, path) == {"ok": False, "error": "not-file"}
    assert opened == [str(fake_mountinfo)]


def test_the_real_mountinfo_allows_a_normal_file_and_refuses_sysfs(tmp_path, capsys):
    path = _text_file(tmp_path)
    assert dropped(capsys, path) == {"ok": True, "text": "hello"}
    sysfs = "/sys/kernel/mm/transparent_hugepage/enabled"
    if os.path.exists(sysfs):
        assert dropped(capsys, sysfs) == {"ok": False, "error": "not-file"}
