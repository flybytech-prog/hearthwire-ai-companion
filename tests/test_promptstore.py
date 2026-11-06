"""Saved prompts and personas (core/promptstore.py) and the --prompts CLI.

A fake verified gocryptfs mount (as in test_webdata) and a stub kdialog that
prints STUB_TEXT_FILE's bytes are the only things used: no real dialog runs.
The stub also records whether the vault lock was free while it was open.
"""

import ast
import fcntl
import json
import os
import re
import stat
import sys
from pathlib import Path

import pytest

from hearthwire import cli
from hearthwire.core import promptstore, vault
from test_webdata import _fake_mount

SOURCE = Path(promptstore.__file__)

KDIALOG = r'''#!PYTHON
import fcntl, json, os, sys, time
env = os.environ


def target(fd):
    try:
        return os.readlink(f"/proc/self/fd/{fd}")
    except OSError:
        return "closed"


lock_free = None
try:
    descriptor = os.open(env["STUB_LOCK"], os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_free = True
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError:
        lock_free = False
    os.close(descriptor)
except OSError:
    pass
if env.get("STUB_UNMOUNT"):
    open(env["STUB_MOUNTINFO"], "w").close()
with open(env["STUB_LOG"], "a") as handle:
    handle.write(json.dumps({"argv": sys.argv[1:], "fds": [target(0), target(1), target(2)],
                             "lock_free": lock_free}) + "\n")
code = int(env.get("STUB_EXIT", "0"))
if code == 0:
    with open(env["STUB_TEXT_FILE"], "rb") as handle:
        sys.stdout.buffer.write(handle.read())
sys.exit(code)
'''


class Library:
    def __init__(self, tmp_path, monkeypatch, runtime):
        self.tmp = tmp_path
        self.data = tmp_path / "data"
        monkeypatch.setenv("XDG_DATA_HOME", str(self.data))
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.kdialog = self.bin / "kdialog"
        self.kdialog.write_text(KDIALOG.replace("PYTHON", sys.executable, 1))
        self.kdialog.chmod(0o755)
        monkeypatch.setenv("PATH", str(self.bin))
        self.log = tmp_path / "kdialog.log"
        self.log.write_text("")
        self.text_file = tmp_path / "text"
        monkeypatch.setenv("STUB_LOG", str(self.log))
        monkeypatch.setenv("STUB_TEXT_FILE", str(self.text_file))
        self.monkeypatch = monkeypatch
        self.cipher = Path(os.path.realpath(self.data)) / "hearthwire" / "vault"
        self.mountpoint = Path(os.path.realpath(runtime)) / "hearthwire" / "vault"
        self.mountinfo = tmp_path / "mountinfo"
        monkeypatch.setenv("STUB_MOUNTINFO", str(self.mountinfo))
        monkeypatch.setenv("STUB_LOCK", str(self.mountpoint.parent / "vault.lock"))
        self.monkeypatch.setattr(vault, "MOUNTINFO", str(self.mountinfo))
        self.mountinfo.write_text("")

    def mount(self):
        self.cipher.mkdir(parents=True, mode=0o700, exist_ok=True)
        _fake_mount(self.monkeypatch, self.mountinfo, self.cipher, self.mountpoint)
        (self.mountpoint.parent / "vault.lock").touch()

    @property
    def folder(self):
        return self.mountpoint / "library"

    def answer(self, text, code=0):
        self.text_file.write_bytes(text if isinstance(text, bytes) else text.encode())
        self.monkeypatch.setenv("STUB_EXIT", str(code))

    def dialogs(self):
        return [json.loads(line) for line in self.log.read_text().splitlines() if line]


@pytest.fixture
def lib(tmp_path, monkeypatch, _private_runtime_dir):
    return Library(tmp_path, monkeypatch, _private_runtime_dir)


@pytest.fixture
def mounted(lib):
    lib.mount()
    return lib


def prompts(capsys, *argv):
    assert cli.main(["--prompts", *argv]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    return json.loads(captured.out)


def add(capsys, lib, text, kind="prompt"):
    lib.answer(text)
    return prompts(capsys, "add", "--kind", kind)


def mode(path):
    return stat.S_IMODE(os.lstat(path).st_mode)


# --- locked and unverified ------------------------------------------------------------------


@pytest.mark.parametrize("argv", [["list"], ["add", "--kind", "prompt"], ["replace", "--id", "1"],
                                  ["remove", "--id", "1"], ["set-persona", "--model", "llama3", "--none"]])
def test_every_command_needs_the_unlocked_folder(lib, capsys, argv):
    assert prompts(capsys, *argv) == {"ok": False, "error": "locked"}
    assert lib.dialogs() == []
    assert not (lib.data / "hearthwire" / "library").exists()
    assert not lib.folder.exists()


def test_a_foreign_mount_is_not_verified(lib, capsys):
    lib.mount()
    lib.mountinfo.write_text(lib.mountinfo.read_text().replace("fuse.gocryptfs", "fuse.other"))
    assert prompts(capsys, "list") == {"ok": False, "error": "not-verified"}
    assert prompts(capsys, "add", "--kind", "prompt") == {"ok": False, "error": "not-verified"}
    assert lib.dialogs() == []


# --- add, list, replace, remove -----------------------------------------------------------------


def test_add_writes_through_kdialog_stdout_into_the_mount(mounted, capsys):
    assert add(capsys, mounted, "Summarise this:\nplease\n") == {"ok": True, "id": 1}
    (dialog,) = mounted.dialogs()
    assert dialog["argv"] == ["--title", "Hearthwire", "--textinputbox", promptstore.LABELS["prompt"]]
    assert dialog["fds"][0] == "/dev/null" and dialog["fds"][2] == "/dev/null"
    assert re.fullmatch(re.escape(str(mounted.folder)) + r"/pending-[0-9]+-[0-9a-f]{16}\.tmp", dialog["fds"][1])
    # The vault lock is not held while the dialog is open.
    assert dialog["lock_free"] is True
    assert mode(mounted.folder) == 0o700
    assert mode(mounted.folder / "prompt-1.txt") == 0o600
    assert sorted(os.listdir(mounted.folder)) == ["prompt-1.txt"]
    assert prompts(capsys, "list") == {
        "ok": True, "items": [{"id": 1, "kind": "prompt", "text": "Summarise this:\nplease"}], "personas": {}}
    # Nothing outside the mount.
    assert sorted(os.listdir(mounted.data / "hearthwire")) == ["vault"]


def test_personas_ids_and_defaults(mounted, capsys):
    assert add(capsys, mounted, "p1\n") == {"ok": True, "id": 1}
    assert add(capsys, mounted, "You are terse.\n", "persona") == {"ok": True, "id": 2}
    assert mounted.dialogs()[1]["argv"][-1] == promptstore.LABELS["persona"]
    assert prompts(capsys, "set-persona", "--model", "llama3:latest", "--id", "2") == {"ok": True}
    assert prompts(capsys, "set-persona", "--model", "hf.co/x/y+z", "--id", "2") == {"ok": True}
    assert prompts(capsys, "set-persona", "--model", "llama3:latest", "--id", "1") == {"ok": False, "error": "absent"}
    assert prompts(capsys, "set-persona", "--model", "llama3:latest", "--id", "9") == {"ok": False, "error": "absent"}
    listed = prompts(capsys, "list")
    assert listed["items"] == [{"id": 1, "kind": "prompt", "text": "p1"},
                               {"id": 2, "kind": "persona", "text": "You are terse."}]
    assert listed["personas"] == {"hf.co/x/y+z": 2, "llama3:latest": 2}
    assert mode(mounted.folder / "personas.json") == 0o600
    assert prompts(capsys, "set-persona", "--model", "llama3:latest", "--none") == {"ok": True}
    assert prompts(capsys, "list")["personas"] == {"hf.co/x/y+z": 2}
    # Removing a persona drops every default pointing at it.
    assert prompts(capsys, "remove", "--id", "2") == {"ok": True}
    assert prompts(capsys, "list") == {"ok": True, "items": [{"id": 1, "kind": "prompt", "text": "p1"}],
                                       "personas": {}}
    # Ids are never reused below the highest one in use.
    assert add(capsys, mounted, "p3") == {"ok": True, "id": 2}
    assert prompts(capsys, "remove", "--id", "1") == {"ok": True}
    assert add(capsys, mounted, "p4") == {"ok": True, "id": 3}


def test_replace_keeps_the_id_and_kind(mounted, capsys):
    add(capsys, mounted, "old")
    mounted.answer("new text\n")
    assert prompts(capsys, "replace", "--id", "1") == {"ok": True, "id": 1}
    assert prompts(capsys, "list")["items"] == [{"id": 1, "kind": "prompt", "text": "new text"}]
    assert prompts(capsys, "replace", "--id", "5") == {"ok": False, "error": "absent"}
    assert prompts(capsys, "remove", "--id", "5") == {"ok": False, "error": "absent"}
    assert len(mounted.dialogs()) == 2


def test_replace_a_persona_uses_the_persona_cap(mounted, capsys):
    add(capsys, mounted, "short", "persona")
    mounted.answer("x" * 8001)
    assert prompts(capsys, "replace", "--id", "1") == {"ok": False, "error": "too-long"}
    assert prompts(capsys, "list")["items"][0]["text"] == "short"


@pytest.mark.parametrize(
    ("text", "code", "kind", "error"),
    [("anything", 1, "prompt", "cancelled"), ("", 0, "prompt", "cancelled"), ("\n", 0, "prompt", "cancelled"),
     (" \n\t\n", 0, "prompt", "cancelled"), ("x", 2, "prompt", "os-error"),
     ("x" * 32001, 0, "prompt", "too-long"), ("é" * 32001 + "\n", 0, "prompt", "too-long"),
     ("x" * 8001, 0, "persona", "too-long"), (b"\xff\xfe bad", 0, "prompt", "not-text"),
     ("a\x00b", 0, "prompt", "not-text"), (b"x" * (32000 * 4 + 2), 0, "prompt", "too-long")],
)
def test_add_refusals_leave_nothing(mounted, capsys, text, code, kind, error):
    mounted.answer(text, code)
    assert prompts(capsys, "add", "--kind", kind) == {"ok": False, "error": error}
    assert os.listdir(mounted.folder) == []


@pytest.mark.parametrize(("kind", "chars"), [("prompt", 32000), ("persona", 8000)])
def test_the_caps_themselves_are_allowed(mounted, capsys, kind, chars):
    assert add(capsys, mounted, "€" * chars + "\n", kind) == {"ok": True, "id": 1}
    assert prompts(capsys, "list")["items"][0]["text"] == "€" * chars


def test_the_library_holds_at_most_100_items(mounted, capsys):
    mounted.folder.mkdir(mode=0o700)
    for item in range(1, 101):
        (mounted.folder / f"prompt-{item}.txt").write_text(f"p{item}")
    assert add(capsys, mounted, "one more") == {"ok": False, "error": "full"}
    assert mounted.dialogs() == []
    assert len(prompts(capsys, "list")["items"]) == 100


def test_unmounted_while_the_dialog_was_open(mounted, capsys):
    mounted.monkeypatch.setenv("STUB_UNMOUNT", "1")
    assert add(capsys, mounted, "text") == {"ok": False, "error": "locked"}
    assert os.listdir(mounted.folder) == []


def test_stale_pending_files_are_cleared(mounted, capsys):
    mounted.folder.mkdir(mode=0o700)
    (mounted.folder / "pending-999999999-0123456789abcdef.tmp").write_text("old")
    live = mounted.folder / f"pending-{os.getpid()}-0123456789abcdef.tmp"
    live.write_text("busy")
    assert add(capsys, mounted, "x") == {"ok": True, "id": 1}
    assert sorted(os.listdir(mounted.folder)) == [live.name, "prompt-1.txt"]


def test_missing_kdialog(mounted, capsys):
    mounted.kdialog.unlink()
    assert prompts(capsys, "add", "--kind", "prompt") == {"ok": False, "error": "missing-tool"}


# --- what list trusts ------------------------------------------------------------------------------


def test_list_skips_odd_entries(mounted, capsys, tmp_path):
    mounted.folder.mkdir(mode=0o700)
    secret = tmp_path / "secret.txt"
    secret.write_text("outside")
    (mounted.folder / "prompt-1.txt").symlink_to(secret)
    os.mkfifo(mounted.folder / "prompt-2.txt")
    (mounted.folder / "prompt-3.txt").write_bytes(b"\xff")
    (mounted.folder / "prompt-4.txt").write_text("x" * 32001)
    (mounted.folder / "prompt-05.txt").write_text("leading zero")
    (mounted.folder / "prompt-0.txt").write_text("zero")
    (mounted.folder / "note.txt").write_text("other")
    (mounted.folder / "persona-6.txt").mkdir()
    (mounted.folder / "prompt-7.txt").write_text("fine")
    (mounted.folder / "personas.json").write_text(json.dumps(
        {"llama3": 7, "-bad": 7, "ok": "7", "x": 1, "y": True}))
    assert prompts(capsys, "list") == {"ok": True, "items": [{"id": 7, "kind": "prompt", "text": "fine"}],
                                       "personas": {}}


@pytest.mark.parametrize("content", ["not json", "[1]", "\xff"])
def test_a_broken_personas_file_is_empty(mounted, capsys, content):
    add(capsys, mounted, "you", "persona")
    (mounted.folder / "personas.json").write_bytes(content.encode("latin-1"))
    assert prompts(capsys, "list")["personas"] == {}
    assert prompts(capsys, "set-persona", "--model", "m", "--id", "1") == {"ok": True}
    assert prompts(capsys, "list")["personas"] == {"m": 1}


def test_a_symlinked_library_is_refused(mounted, capsys, tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    mounted.folder.symlink_to(target)
    assert prompts(capsys, "list") == {"ok": False, "error": "os-error"}
    assert prompts(capsys, "add", "--kind", "prompt") == {"ok": False, "error": "os-error"}
    assert list(target.iterdir()) == []


def test_output_never_contains_a_path(mounted, capsys, tmp_path):
    texts = []
    for argv, text in ((["add", "--kind", "prompt"], "hello"), (["list"], ""), (["replace", "--id", "1"], "bye"),
                       (["set-persona", "--model", "m", "--none"], ""), (["remove", "--id", "1"], ""),
                       (["remove", "--id", "1"], "")):
        mounted.answer(text)
        assert cli.main(["--prompts", *argv]) == 0
        captured = capsys.readouterr()
        texts.append(captured.out + captured.err)
    joined = "".join(texts)
    assert str(tmp_path) not in joined and "/" not in joined and "pending" not in joined


# --- CLI -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [["--prompts", "add"], ["--prompts", "add", "--kind", "other"], ["--prompts", "list", "--kind", "prompt"],
     ["--prompts", "list", "--id", "1"], ["--prompts", "replace"], ["--prompts", "remove", "--id", "0"],
     ["--prompts", "remove", "--id", "-1"], ["--prompts", "remove", "--id", "2147483649"],
     ["--prompts", "remove", "--id", "1", "--model", "m"], ["--prompts", "set-persona", "--model", "m"],
     ["--prompts", "set-persona", "--model", "m", "--id", "1", "--none"],
     ["--prompts", "set-persona", "--id", "1"], ["--prompts", "set-persona", "--model", "-m", "--none"],
     ["--prompts", "set-persona", "--model", "a b", "--none"], ["--prompts", "set-persona", "--model", "x" * 201,
                                                                "--none"],
     ["--prompts", "list", "--none"], ["--kind", "prompt"], ["--id", "1"], ["--model", "m"], ["--none"],
     ["--prompts", "list", "--vault", "status"], ["--prompts", "list", "--catalog"],
     ["--prompts", "list", "--applet", "1"], ["--prompts", "list", "--port-owner", "11434"],
     ["--prompts", "list", "--read-dropped", "2f"], ["--prompts", "list", "--web-data", "purge"]],
)
def test_prompts_cli_rejects_bad_arguments(lib, capsys, argv):
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 2
    assert capsys.readouterr().out == ""
    assert lib.dialogs() == []


# --- static rules ------------------------------------------------------------------------------------


def test_promptstore_is_stdlib_only_and_never_prints_or_uses_a_shell():
    code = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] in sys.stdlib_module_names for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            assert (node.module or "").split(".")[0] in sys.stdlib_module_names
    for pattern in (r"\bshell\s*=", r"(?<![\w.])print\s*\(", r"\bPIPE\b", r"\bcapture_output\b",
                    r"\bcheck_output\b", r"\bos\.system\b", r"\bos\.popen\b", r"\bsys\.std(out|err)\b",
                    r"\blogging\b"):
        assert not re.search(pattern, code), pattern
    # The dialog argv carries only fixed words: no initial text.
    assert promptstore.dialog_argv("/k", "prompt") == ["/k", "--title", "Hearthwire", "--textinputbox",
                                                       promptstore.LABELS["prompt"]]
    assert not any(label.startswith("-") for label in promptstore.LABELS.values())
