"""The one-time move from Hearthside to Hearthwire (core/legacy.py, plan R2).

Reuses test_vault's stubs: gocryptfs, kdialog, fusermount3, kwallet-query, qdbus6
and openssl are scripts in a private PATH, the "wallet" is a JSON file holding a
dummy marker key, and mounts are lines in a fake mountinfo. plasmashell is
looked for in a fake /proc. XDG_DATA_HOME, XDG_CONFIG_HOME, XDG_CACHE_HOME and
XDG_RUNTIME_DIR all point into tmp_path: no real home, bus, wallet, Plasma or
appletsrc is ever touched.
"""

import ast
import errno
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path

import pytest

from hearthwire import cli
from hearthwire.core import legacy, settingsbackup, usagehistory, vault, walletkey, webdata
from test_settingsbackup import GOOD, hexed
from test_vault import Stubs

SOURCE = Path(legacy.__file__)
OLD = "hearthside"
NEW = "hearthwire"
OLD_KEY = "Hearthside/encrypted-chat-folder"
OLD_STAGED = OLD_KEY + ".new"
NEW_KEY = "Hearthwire/encrypted-chat-folder"
NEW_STAGED = NEW_KEY + ".new"
# A dummy wallet value; it must never show up in a reply, a log line or a read().
MARKER_KEY = "5ec2e7" + "a1" * 29
OTHER_KEY = "0b" * 32
OLD_ID = b"io.github.flybytechprog.hearthside"
NEW_ID = b"io.github.flybytechprog.hearthwire"

APPLETSRC = (
    b"[ActionPlugins][0]\nRightButton;NoModifier=org.kde.contextmenu\n\n"
    b"[Containments][1]\nactivityId=\nformfactor=2\nplugin=org.kde.panel\n\n"
    b"[Containments][1][Applets][27]\nimmutability=1\nplugin=" + OLD_ID + b"\n\n"
    b"[Containments][1][Applets][27][Configuration][General]\nnote=plugin=" + OLD_ID + b"\n"
    b"plugin=" + OLD_ID + b"\n\n"
    b"[Containments][1][Applets][28]\nplugin=org.kde.plasma.digitalclock\n\n"
    b"[Containments][7][Applets][3]\n# plugin=" + OLD_ID + b"\nplugin=" + OLD_ID + b"\n"
    b"[ScreenMapping]\nitemsOnDisabledScreens=\xc3\xa4"
)
# Only the two plugin= lines directly under an [Applets][M] header change.
MIGRATED_APPLETSRC = (
    b"[ActionPlugins][0]\nRightButton;NoModifier=org.kde.contextmenu\n\n"
    b"[Containments][1]\nactivityId=\nformfactor=2\nplugin=org.kde.panel\n\n"
    b"[Containments][1][Applets][27]\nimmutability=1\nplugin=" + NEW_ID + b"\n\n"
    b"[Containments][1][Applets][27][Configuration][General]\nnote=plugin=" + OLD_ID + b"\n"
    b"plugin=" + OLD_ID + b"\n\n"
    b"[Containments][1][Applets][28]\nplugin=org.kde.plasma.digitalclock\n\n"
    b"[Containments][7][Applets][3]\n# plugin=" + OLD_ID + b"\nplugin=" + NEW_ID + b"\n"
    b"[ScreenMapping]\nitemsOnDisabledScreens=\xc3\xa4"
)
CACHE_TEMPORARY = ".antigravity-auth.json." + "ab" * 16 + ".tmp"


# Compares the two /dev/fd paths it inherited, like cmp -s, and logs no value.
CMP_STUB = r'''#!PYTHON
import json, os, sys
args = sys.argv[1:]
code = int(os.environ.get("STUB_CMP_EXIT", "-1"))
if code < 0:
    with open(args[1], "rb") as first, open(args[2], "rb") as second:
        code = 0 if first.read() == second.read() else 1
with open(os.environ["STUB_LOG"], "a") as handle:
    handle.write(json.dumps({"tool": "cmp", "argv": args, "exit": code}) + "\n")
sys.exit(code)
'''


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Home:
    """A private Hearthside install: data, config, cache, wallet and appletsrc."""

    def __init__(self, stubs, tmp_path, monkeypatch):
        self.stubs = stubs
        self.root = Path(os.path.realpath(tmp_path))
        self.data = Path(os.path.realpath(stubs.data))
        self.data.mkdir(parents=True, exist_ok=True)
        self.config = self.root / "config"
        self.cache = self.root / "cache"
        self.proc = self.root / "proc"
        for directory in (self.config, self.cache, self.proc):
            directory.mkdir()
        self.runtime = Path(os.path.realpath(stubs.runtime))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(self.config))
        monkeypatch.setenv("XDG_CACHE_HOME", str(self.cache))
        monkeypatch.setattr(legacy, "PROC", str(self.proc))
        # Never the real /run/user/<uid>.
        monkeypatch.setattr(vault, "DEFAULT_RUNTIME", str(self.root / "no-runtime-{uid}"))
        monkeypatch.setattr(walletkey, "QUERY_TIMEOUT", 5.0)
        (stubs.bin / "cmp").write_text(CMP_STUB.replace("PYTHON", sys.executable, 1))
        (stubs.bin / "cmp").chmod(0o755)

    @property
    def appletsrc(self):
        return self.config / "plasma-org.kde.plasma.desktop-appletsrc"

    @property
    def backup(self):
        return self.config / "plasma-org.kde.plasma.desktop-appletsrc.hearthside-backup"

    def wallet(self):
        return json.loads(self.stubs.wallet.read_text()) if self.stubs.wallet.exists() else {}

    def set_wallet(self, state):
        self.stubs.wallet.write_text(json.dumps(state))

    def slot_dir(self, name):
        return self.data / name / "vault-keys"

    def old_install(self, *, wallet=True, applets=APPLETSRC, key=MARKER_KEY):
        old = self.data / OLD
        (old / "vault").mkdir(parents=True, mode=0o700)
        old.chmod(0o700)
        (old / "vault" / "gocryptfs.conf").write_text("{}")
        (old / "usage-history").mkdir(mode=0o700)
        (old / "usage-history" / "history.json").write_text('{"history_version":1,"series":[]}')
        if wallet:
            self.slot_dir(OLD).mkdir(mode=0o700)
            slot = self.slot_dir(OLD) / "wallet.conf"
            # The stub gocryptfs opens this slot only with the key of this hash.
            slot.write_text(json.dumps({"key_sha": sha(key)}))
            slot.chmod(0o400)
            self.set_wallet({OLD_KEY: MARKER_KEY})
        settings = self.config / OLD
        settings.mkdir(mode=0o700)
        (settings / "settings-backup.json").write_text('{"format":"x"}')
        (settings / "settings-backup.json").chmod(0o600)
        (self.config / f"{OLD}.notifyrc").write_text("[Event/usageLow]\nAction=Popup|Sound\n")
        cache = self.cache / OLD
        cache.mkdir(mode=0o700)
        (cache / "antigravity-auth.json").write_text('{"access_token":"dummy"}')
        (cache / CACHE_TEMPORARY).write_text("{}")
        if applets is not None:
            self.appletsrc.write_bytes(applets)
            self.appletsrc.chmod(0o640)

    def plasma(self, comm="plasmashell", pid="4242"):
        directory = self.proc / pid
        directory.mkdir()
        (directory / "comm").write_text(comm + "\n")
        return directory

    def tree(self):
        """Every file and folder below data, config and cache: (kind, mode, bytes)."""
        result = {}
        for base in (self.data, self.config, self.cache):
            for path in sorted(base.rglob("*")):
                info = os.lstat(path)
                kind = "dir" if stat.S_ISDIR(info.st_mode) else "link" if stat.S_ISLNK(info.st_mode) else "file"
                content = path.read_bytes() if kind == "file" else b""
                result[str(path.relative_to(self.root))] = (kind, stat.S_IMODE(info.st_mode), content)
        return result

    def wallet_calls(self):
        return self.stubs.calls("kwallet-query") + self.stubs.calls("qdbus6")


@pytest.fixture
def home(tmp_path, monkeypatch, _private_runtime_dir):
    stubs = Stubs(tmp_path, monkeypatch, _private_runtime_dir)
    return Home(stubs, tmp_path, monkeypatch)


def migrate(operation, capsys):
    assert cli.main(["--migrate", operation]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    return json.loads(captured.out)


def full_migration(home, capsys):
    assert migrate("run", capsys) == {
        "ok": True, "migrated": ["data", "config", "notifyrc", "cache", "wallet-entry"], "pending": ["applets"]}
    assert migrate("applets", capsys) == {"ok": True, "migrated": ["applets"], "pending": []}


def assert_migrated(home, *, wallet=True):
    """The end state of a complete move."""
    assert not (home.data / OLD).exists() and not (home.config / OLD).exists()
    assert not (home.cache / OLD).exists() and not (home.config / f"{OLD}.notifyrc").exists()
    new = home.data / NEW
    assert stat.S_IMODE(os.lstat(new).st_mode) == 0o700
    assert (new / "vault" / "gocryptfs.conf").read_text() == "{}"
    assert (new / "usage-history" / "history.json").exists()
    assert stat.S_IMODE(os.lstat(home.config / NEW).st_mode) == 0o700
    assert (home.config / NEW / "settings-backup.json").read_text() == '{"format":"x"}'
    assert stat.S_IMODE(os.lstat(home.config / NEW / "settings-backup.json").st_mode) == 0o600
    assert (home.config / f"{NEW}.notifyrc").read_text() == "[Event/usageLow]\nAction=Popup|Sound\n"
    assert home.appletsrc.read_bytes() == MIGRATED_APPLETSRC
    assert stat.S_IMODE(os.lstat(home.appletsrc).st_mode) == 0o640
    assert home.backup.read_bytes() == APPLETSRC
    assert stat.S_IMODE(os.lstat(home.backup).st_mode) == 0o600
    assert not (home.config / legacy.TEMPORARY_NAME).exists()
    if wallet:
        assert stat.S_IMODE(os.lstat(home.slot_dir(NEW) / "wallet.conf").st_mode) == 0o400
        assert home.wallet() == {NEW_KEY: MARKER_KEY}
    assert not home.stubs.mounted()


# --- status --------------------------------------------------------------------------------


def test_status_with_nothing_to_move_runs_no_tool(home, capsys):
    assert migrate("status", capsys) == {"ok": True, "pending": [], "present": []}
    assert home.stubs.calls(skip_version=False) == []


def test_status_lists_every_pending_category(home, capsys):
    home.old_install()
    assert migrate("status", capsys) == {
        "ok": True, "pending": ["data", "config", "notifyrc", "cache", "wallet-entry", "applets"], "present": []}
    # Read only: nothing moved, no copy, no unlock.
    assert (home.data / OLD).is_dir() and home.appletsrc.read_bytes() == APPLETSRC
    assert home.stubs.calls("gocryptfs") == [] and home.stubs.calls("kwallet-query") == []
    assert home.wallet() == {OLD_KEY: MARKER_KEY}


def test_without_a_wallet_slot_there_is_not_one_wallet_call(home, capsys):
    """Rule L4: an old entry without a slot of this folder is not ours to move."""
    home.old_install(wallet=False)
    home.set_wallet({OLD_KEY: MARKER_KEY})
    assert migrate("status", capsys)["pending"] == ["data", "config", "notifyrc", "cache", "applets"]
    assert migrate("run", capsys) == {
        "ok": True, "migrated": ["data", "config", "notifyrc", "cache"], "pending": ["applets"]}
    assert home.wallet_calls() == []
    assert home.wallet() == {OLD_KEY: MARKER_KEY}


def test_a_stray_old_slot_name_that_is_not_a_regular_file_is_no_slot(home, capsys):
    home.old_install(wallet=False)
    home.slot_dir(OLD).mkdir()
    (home.slot_dir(OLD) / "wallet.conf").mkdir()
    home.set_wallet({OLD_KEY: MARKER_KEY})
    assert "wallet-entry" not in migrate("status", capsys)["pending"]
    assert home.wallet_calls() == []


def test_status_reports_present_categories_after_the_move(home, capsys):
    home.old_install()
    full_migration(home, capsys)
    assert migrate("status", capsys) == {
        "ok": True, "pending": [], "present": ["data", "config", "notifyrc", "wallet-entry", "applets"]}


# --- run ----------------------------------------------------------------------------------------


def test_run_moves_everything_and_the_wallet_key_fd_to_fd(home, capsys):
    home.old_install()
    full_migration(home, capsys)
    assert_migrated(home)
    reads = [call for call in home.stubs.calls("kwallet-query") if "--read-password" in call["argv"]]
    writes = [call for call in home.stubs.calls("kwallet-query") if "--write-password" in call["argv"]]
    # Copied from the old folder into the new one, through a pipe; then the
    # proof unlock read the new entry through gocryptfs's extpass.
    assert reads[0]["argv"] == ["--folder", "Hearthside", "--read-password", "encrypted-chat-folder", "kdewallet"]
    assert writes[0]["argv"] == ["--folder", "Hearthwire", "--write-password", "encrypted-chat-folder", "kdewallet"]
    assert reads[0]["fds"][1].startswith("pipe:") and writes[0]["fds"][0].startswith("pipe:")
    assert reads[0]["fds"][0] == writes[0]["fds"][1] == "/dev/null"
    assert reads[0]["sha"] == writes[0]["sha"] == sha(MARKER_KEY)
    (mount,) = [call for call in home.stubs.calls("gocryptfs")]
    assert mount["config"] == str(home.slot_dir(NEW) / "wallet.conf")
    assert mount["extpass_sha"] == sha(MARKER_KEY)
    assert home.stubs.calls("fusermount3")[0]["argv"][0] == "-u"
    assert home.stubs.calls("kdialog") == [] and home.stubs.calls("openssl") == []
    # removeEntry only in the old folder; never removeFolder.
    removes = [call["argv"][3:] for call in home.stubs.calls("qdbus6") if call["argv"][2].endswith(".removeEntry")]
    assert removes == [["7", "Hearthside", "encrypted-chat-folder", "Hearthwire"]]
    assert not any("removeFolder" in " ".join(call["argv"]) for call in home.stubs.calls("qdbus6"))


def test_run_and_applets_are_idempotent(home, capsys):
    home.old_install()
    full_migration(home, capsys)
    home.stubs.log.write_text("")
    assert migrate("run", capsys) == {"ok": True, "migrated": [], "pending": []}
    assert migrate("applets", capsys) == {"ok": True, "migrated": [], "pending": []}
    assert_migrated(home)
    assert home.stubs.calls("gocryptfs") == [] and home.stubs.calls("kwallet-query") == []


def test_run_refuses_while_plasmashell_runs_and_changes_nothing(home, capsys):
    home.old_install()
    home.plasma()
    before = home.tree()
    assert migrate("run", capsys) == {"ok": False, "error": "plasma-running"}
    assert migrate("applets", capsys) == {"ok": False, "error": "plasma-running", "category": "applets"}
    assert home.tree() == before and home.wallet() == {OLD_KEY: MARKER_KEY}


def test_a_wallet_entry_that_does_not_open_the_slot_is_pending_and_its_copy_removed(home, capsys):
    home.old_install(key=OTHER_KEY)
    assert migrate("run", capsys) == {
        "ok": True, "migrated": ["data", "config", "notifyrc", "cache"], "pending": ["wallet-entry", "applets"]}
    # The unlock failed, so the copy went again and the old entry stays.
    assert OLD_KEY in home.wallet() and NEW_KEY not in home.wallet()
    assert home.wallet()[OLD_KEY] == MARKER_KEY
    assert not home.stubs.mounted()
    assert migrate("status", capsys)["pending"] == ["wallet-entry", "applets"]


def test_a_cancelled_wallet_read_is_pending(home, capsys):
    home.old_install()
    home.stubs.env(STUB_KWALLET_READ_EXIT=1)
    reply = migrate("run", capsys)
    assert reply["pending"] == ["wallet-entry", "applets"] and "wallet-entry" not in reply["migrated"]
    assert home.wallet() == {OLD_KEY: MARKER_KEY}
    home.stubs.env(STUB_KWALLET_READ_EXIT=0)
    assert migrate("run", capsys) == {"ok": True, "migrated": ["wallet-entry"], "pending": ["applets"]}
    assert home.wallet() == {NEW_KEY: MARKER_KEY}


def test_a_new_entry_that_already_opens_the_slot_is_kept_without_a_copy(home, capsys):
    home.old_install()
    home.set_wallet({OLD_KEY: MARKER_KEY, NEW_KEY: MARKER_KEY})
    migrate("run", capsys)
    writes = [call for call in home.stubs.calls("kwallet-query") if "--write-password" in call["argv"]]
    assert writes == []
    assert home.wallet() == {NEW_KEY: MARKER_KEY}


def test_a_new_entry_that_does_not_fit_is_replaced_by_the_old_one(home, capsys):
    home.old_install()
    home.set_wallet({OLD_KEY: MARKER_KEY, NEW_KEY: OTHER_KEY})
    assert "wallet-entry" in migrate("run", capsys)["migrated"]
    assert home.wallet() == {NEW_KEY: MARKER_KEY}


def test_the_old_staging_entry_goes_too(home, capsys):
    home.old_install()
    home.set_wallet({OLD_KEY: MARKER_KEY, OLD_STAGED: OTHER_KEY})
    assert "wallet-entry" in migrate("run", capsys)["migrated"]
    assert home.wallet() == {NEW_KEY: MARKER_KEY}


def test_a_lone_old_staging_entry_stays_and_is_not_reported(home, capsys):
    """It proves nothing about the slot, so it is neither deleted nor "migrated"."""
    home.old_install()
    home.set_wallet({NEW_KEY: MARKER_KEY, OLD_STAGED: OTHER_KEY})
    assert migrate("run", capsys) == {
        "ok": True, "migrated": ["data", "config", "notifyrc", "cache"], "pending": ["applets"]}
    assert home.wallet() == {NEW_KEY: MARKER_KEY, OLD_STAGED: OTHER_KEY}
    assert home.stubs.calls("gocryptfs") == []
    assert "wallet-entry" not in migrate("status", capsys)["pending"]


@pytest.mark.parametrize("settings", [{"STUB_WALLET_ENABLED": "false"}, {"STUB_QDBUS_EXIT": "1"}])
def test_an_unreachable_wallet_leaves_the_entry_pending(home, capsys, settings):
    home.old_install()
    home.stubs.env(**settings)
    reply = migrate("run", capsys)
    assert reply["migrated"] == ["data", "config", "notifyrc", "cache"]
    assert reply["pending"] == ["wallet-entry", "applets"]
    assert home.wallet() == {OLD_KEY: MARKER_KEY}
    assert home.stubs.calls("gocryptfs") == []


def test_missing_wallet_tools_leave_the_entry_pending(home, capsys):
    home.old_install()
    home.stubs.remove("kwallet-query")
    assert migrate("run", capsys)["pending"] == ["wallet-entry", "applets"]
    assert home.wallet() == {OLD_KEY: MARKER_KEY}


# --- refusals -------------------------------------------------------------------------------------


def _mount_line(home, mountpoint, source):
    with open(home.stubs.mountinfo, "a") as handle:
        handle.write(f"901 30 0:99 / {mountpoint} rw - fuse.gocryptfs {source} rw,user_id={os.getuid()}\n")


@pytest.mark.parametrize("name", [OLD, NEW])
@pytest.mark.parametrize("operation", ["status", "run", "applets", "rollback"])
def test_a_mounted_vault_of_either_name_is_not_locked(home, capsys, name, operation):
    home.old_install()
    _mount_line(home, home.runtime / name / "vault", home.data / name / "vault")
    before = home.tree()
    assert migrate(operation, capsys) == {"ok": False, "error": "not-locked"}
    assert home.tree() == before and home.wallet() == {OLD_KEY: MARKER_KEY}


def test_status_refuses_a_mounted_vault_when_only_the_applets_are_left(home, capsys):
    home.appletsrc.write_bytes(APPLETSRC)
    _mount_line(home, home.runtime / NEW / "vault", home.data / NEW / "vault")
    assert migrate("status", capsys) == {"ok": False, "error": "not-locked"}
    assert home.appletsrc.read_bytes() == APPLETSRC and not home.backup.exists()


def test_a_finished_move_lets_a_reinstall_run_with_the_vault_unlocked(home, capsys):
    home.old_install()
    full_migration(home, capsys)
    _mount_line(home, home.runtime / NEW / "vault", home.data / NEW / "vault")
    assert migrate("status", capsys)["pending"] == []


def test_a_mount_of_the_old_cipher_dir_elsewhere_is_not_locked(home, capsys):
    home.old_install()
    _mount_line(home, home.root / "elsewhere", home.data / OLD / "vault")
    assert migrate("run", capsys) == {"ok": False, "error": "not-locked"}


@pytest.mark.parametrize("name", [OLD, NEW])
def test_a_held_vault_lock_of_either_name_is_busy(home, capsys, name):
    home.old_install()
    directory = home.runtime / name
    directory.mkdir(mode=0o700, exist_ok=True)
    descriptor = os.open(directory / "vault.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        before = home.tree()
        assert migrate("status", capsys) == {"ok": False, "error": "busy"}
        assert migrate("run", capsys) == {"ok": False, "error": "busy"}
        assert migrate("applets", capsys) == {"ok": False, "error": "busy"}
        assert home.tree() == before
    finally:
        os.close(descriptor)


def test_locks_are_taken_old_then_new(home, monkeypatch, capsys):
    home.old_install()
    order = []
    real = vault.vault_lock

    def spy(ctx, **kwargs):
        order.append(kwargs.get("app_dir", vault.APP_DIR))
        return real(ctx, **kwargs)

    monkeypatch.setattr(vault, "vault_lock", spy)
    migrate("run", capsys)
    assert order[:2] == [OLD, NEW]


@pytest.mark.parametrize("kind", ["data", "config"])
def test_both_names_holding_data_is_a_conflict_and_nothing_changes(home, capsys, kind):
    home.old_install()
    base = home.data if kind == "data" else home.config
    (base / NEW).mkdir()
    (base / NEW / "keep").write_text("mine")
    before = home.tree()
    assert migrate("status", capsys) == {"ok": False, "error": "conflict", "category": kind}
    assert migrate("run", capsys) == {"ok": False, "error": "conflict", "category": kind}
    assert migrate("rollback", capsys) == {"ok": False, "error": "conflict", "category": kind}
    assert home.tree() == before and home.wallet() == {OLD_KEY: MARKER_KEY}


def test_an_empty_new_folder_is_replaced_not_merged(home, capsys):
    home.old_install()
    (home.data / NEW).mkdir()
    (home.config / NEW).mkdir()
    full_migration(home, capsys)
    assert_migrated(home)


def test_notifyrc_under_both_names_keeps_the_new_one(home, capsys):
    home.old_install()
    (home.config / f"{NEW}.notifyrc").write_text("[Event/usageReset]\nAction=\n")
    migrate("run", capsys)
    assert (home.config / f"{NEW}.notifyrc").read_text() == "[Event/usageReset]\nAction=\n"
    assert not (home.config / f"{OLD}.notifyrc").exists()


@pytest.mark.parametrize("target", ["data", "config", "cache", "notifyrc", "vault-keys"])
def test_symlinks_are_refused_never_followed(home, capsys, tmp_path, target):
    home.old_install()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "precious").write_text("keep")
    path = {"data": home.data / OLD, "config": home.config / OLD, "cache": home.cache / OLD,
            "notifyrc": home.config / f"{OLD}.notifyrc", "vault-keys": home.slot_dir(OLD)}[target]
    os.chmod(path, 0o700)
    for child in sorted(path.rglob("*"), reverse=True) if path.is_dir() else ():
        child.chmod(0o700)
        child.rmdir() if child.is_dir() else child.unlink()
    path.rmdir() if path.is_dir() else path.unlink()
    path.symlink_to(elsewhere)
    category = "wallet-entry" if target == "vault-keys" else target
    assert migrate("status", capsys) == {"ok": False, "error": "symlink", "category": category}
    assert migrate("run", capsys) == {"ok": False, "error": "symlink", "category": category}
    assert sorted(os.listdir(elsewhere)) == ["precious"] and path.is_symlink()


def test_a_file_where_the_data_folder_should_be_is_not_directory(home, capsys):
    (home.data / OLD).write_text("")
    assert migrate("run", capsys) == {"ok": False, "error": "not-directory", "category": "data"}


def test_foreign_files_in_the_old_cache_stay(home, capsys):
    home.old_install()
    (home.cache / OLD / "someone-elses").write_text("keep")
    assert "cache" in migrate("run", capsys)["migrated"]
    assert os.listdir(home.cache / OLD) == ["someone-elses"]
    assert "cache" not in migrate("status", capsys)["pending"]


def test_no_runtime_dir_is_os_error(home, capsys, monkeypatch):
    home.old_install()
    monkeypatch.setattr(vault, "_purge_runtimes", lambda environ: [])
    assert migrate("run", capsys) == {"ok": False, "error": "os-error"}
    assert (home.data / OLD).is_dir()


# --- renames ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("with_renameat2", [True, False])
def test_rename_never_replaces_an_existing_target(tmp_path, monkeypatch, with_renameat2):
    if not with_renameat2:
        monkeypatch.setattr(legacy, "_renameat2", None)
        monkeypatch.setattr(legacy, "_renameat2_loaded", True)
    elif legacy._noreplace() is None:
        pytest.skip("libc has no renameat2")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").write_text("keep")
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(webdata.HelperError) as raised:
            legacy._rename(descriptor, "a", "b")
        assert raised.value.code == "conflict"
        assert (tmp_path / "b").read_text() == "keep" and (tmp_path / "a").is_dir()
        legacy._rename(descriptor, "a", "c")
        assert (tmp_path / "c").is_dir() and not (tmp_path / "a").exists()
    finally:
        os.close(descriptor)


def test_the_whole_move_works_without_renameat2(home, capsys, monkeypatch):
    monkeypatch.setattr(legacy, "_renameat2", None)
    monkeypatch.setattr(legacy, "_renameat2_loaded", True)
    home.old_install()
    full_migration(home, capsys)
    assert_migrated(home)


def test_libc_renameat2_is_used_when_present(home, capsys, monkeypatch):
    calls = []
    real = legacy._noreplace()
    if real is None:
        pytest.skip("libc has no renameat2")

    def spy(*arguments):
        calls.append(arguments[1:4:2] + (arguments[4],))
        return real(*arguments)

    monkeypatch.setattr(legacy, "_renameat2", spy)
    home.old_install()
    migrate("run", capsys)
    assert (b"hearthside", b"hearthwire", legacy.RENAME_NOREPLACE) in calls


# --- fault injection: stop between steps, then run again ---------------------------------------------


def _fail_once(monkeypatch, owner, name, error=None, *, after=0):
    real = getattr(owner, name)
    state = {"calls": 0}

    def wrapper(*arguments, **keywords):
        state["calls"] += 1
        if state["calls"] == after + 1:
            raise error or webdata.HelperError("os-error")
        return real(*arguments, **keywords)

    monkeypatch.setattr(owner, name, wrapper)


FAULTS = {
    # (owner, function, calls that pass first, the reply of the faulty run)
    "data": (legacy, "_rename", 0, {"ok": False, "error": "os-error", "category": "data"}),
    "config": (legacy, "_move_directory", 1, {"ok": False, "error": "os-error", "category": "config"}),
    "notifyrc": (legacy, "_move_file", 0, {"ok": False, "error": "os-error", "category": "notifyrc"}),
    "cache": (legacy, "_clear_cache", 0, {"ok": False, "error": "os-error", "category": "cache"}),
    "wallet-copy": (walletkey, "copy_entry", 0, None),
    "wallet-proof": (vault, "verify_wallet_slot", 0, None),
    "wallet-remove": (walletkey, "remove_legacy_entry", 0, None),
    "slot-check": (legacy, "_slot_in", 2, {"ok": False, "error": "os-error", "category": "wallet-entry"}),
}


@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_a_run_stopped_at_any_step_is_finished_by_the_next(home, capsys, monkeypatch, fault):
    owner, name, after, expected = FAULTS[fault]
    home.old_install()
    with monkeypatch.context() as patch:
        _fail_once(patch, owner, name, after=after)
        reply = migrate("run", capsys)
    if expected is None:
        assert reply["ok"] is True and "wallet-entry" in reply["pending"], reply
        assert OLD_KEY in home.wallet()
    else:
        assert reply == expected
    assert not home.stubs.mounted()
    assert migrate("run", capsys)["pending"] == ["applets"]
    assert migrate("applets", capsys) == {"ok": True, "migrated": ["applets"], "pending": []}
    assert_migrated(home)


def test_applets_stopped_before_the_replace_is_finished_by_the_next(home, capsys, monkeypatch):
    home.old_install()
    migrate("run", capsys)
    with monkeypatch.context() as patch:
        patch.setattr(legacy.os, "rename", lambda *a, **k: (_ for _ in ()).throw(OSError(errno.EIO, "x")))
        assert migrate("applets", capsys) == {"ok": False, "error": "os-error", "category": "applets"}
    assert home.appletsrc.read_bytes() == APPLETSRC
    assert not (home.config / legacy.TEMPORARY_NAME).exists()
    assert home.backup.read_bytes() == APPLETSRC
    assert migrate("applets", capsys) == {"ok": True, "migrated": ["applets"], "pending": []}
    assert_migrated(home)


def test_a_leftover_temporary_copy_is_replaced(home, capsys):
    home.old_install()
    (home.config / legacy.TEMPORARY_NAME).write_text("stale")
    full_migration(home, capsys)
    assert_migrated(home)


# --- applets ----------------------------------------------------------------------------------------


def test_applets_rewrite_is_exact_and_byte_preserving():
    rewritten, found_old, found_new = legacy.rewrite_applets(APPLETSRC, legacy.LEGACY_PLUGIN, legacy.PLUGIN)
    assert (rewritten, found_old, found_new) == (MIGRATED_APPLETSRC, 2, 0)
    assert legacy.rewrite_applets(rewritten, legacy.LEGACY_PLUGIN, legacy.PLUGIN) == (MIGRATED_APPLETSRC, 0, 2)
    back, found, _ = legacy.rewrite_applets(rewritten, legacy.PLUGIN, legacy.LEGACY_PLUGIN)
    assert (back, found) == (APPLETSRC, 2)


def test_crlf_lines_elsewhere_are_kept_byte_for_byte():
    content = b"[General]\r\nkey=value\r\n[Containments][1][Applets][2]\nplugin=" + OLD_ID + b"\n"
    rewritten, found, _ = legacy.rewrite_applets(content, legacy.LEGACY_PLUGIN, legacy.PLUGIN)
    assert found == 1 and rewritten == content.replace(OLD_ID, NEW_ID)


@pytest.mark.parametrize("content", [
    b"[Containments][1][Applets][2]\nplugin = " + OLD_ID + b"\n",
    b"[Containments][1][Applets][2]\nplugin=" + OLD_ID + b" \n",
    b"[Containments][1][Applets][2]\n plugin=" + OLD_ID + b"\n",
    b"[Containments][1][Applets][2]\nplugin=" + OLD_ID + b"\r\n",
    b" [Containments][1][Applets][2]\nplugin=" + OLD_ID + b"\n",
    b"[Containments][1][Applets][2\nplugin=" + OLD_ID + b"\n",
    b"[Containments][1]x[Applets][2]\nplugin=" + OLD_ID + b"\n",
    b"[Containments][1][Applets][2]\nplugin=" + OLD_ID + b"\n\0",
    b"[Containments][1][Applets][2]\nplugin=" + OLD_ID + b"\n\xff\n",
])
def test_malformed_appletsrc_is_invalid_and_unchanged(home, capsys, content):
    home.appletsrc.write_bytes(content)
    assert migrate("status", capsys) == {"ok": False, "error": "invalid", "category": "applets"}
    assert migrate("applets", capsys) == {"ok": False, "error": "invalid", "category": "applets"}
    assert home.appletsrc.read_bytes() == content
    assert not home.backup.exists()


def test_the_first_backup_is_kept(home, capsys):
    home.old_install()
    home.backup.write_bytes(b"first")
    home.backup.chmod(0o600)
    full_migration(home, capsys)
    assert home.backup.read_bytes() == b"first"


@pytest.mark.parametrize("target", ["appletsrc", "backup"])
def test_appletsrc_and_backup_symlinks_are_refused(home, capsys, tmp_path, target):
    home.old_install()
    real = tmp_path / "real-appletsrc"
    real.write_bytes(APPLETSRC)
    path = home.appletsrc if target == "appletsrc" else home.backup
    if path.exists():
        path.unlink()
    path.symlink_to(real)
    migrate("run", capsys)
    assert migrate("applets", capsys) == {"ok": False, "error": "symlink", "category": "applets"}
    assert real.read_bytes() == APPLETSRC and path.is_symlink()


def test_plasmashell_starting_before_the_replace_stops_it(home, capsys, monkeypatch):
    home.old_install()
    migrate("run", capsys)
    answers = iter([False, True])
    monkeypatch.setattr(legacy, "plasma_running", lambda proc=None: next(answers))
    assert migrate("applets", capsys) == {"ok": False, "error": "plasma-running", "category": "applets"}
    assert home.appletsrc.read_bytes() == APPLETSRC
    assert not (home.config / legacy.TEMPORARY_NAME).exists()


def test_an_appletsrc_changed_meanwhile_is_not_replaced(home, capsys, monkeypatch):
    home.old_install()
    migrate("run", capsys)
    real = legacy._write_new

    def racing(parent, name, content, mode):
        real(parent, name, content, mode)
        if name == legacy.TEMPORARY_NAME:
            home.appletsrc.write_bytes(APPLETSRC + b"\n[New]\n")

    monkeypatch.setattr(legacy, "_write_new", racing)
    assert migrate("applets", capsys) == {"ok": False, "error": "os-error", "category": "applets"}
    assert home.appletsrc.read_bytes() == APPLETSRC + b"\n[New]\n"


def test_no_appletsrc_is_nothing_to_do(home, capsys):
    assert migrate("applets", capsys) == {"ok": True, "migrated": [], "pending": []}


# --- plasmashell in /proc ---------------------------------------------------------------------------


def test_plasmashell_detection_reads_comm_of_our_processes(home, monkeypatch):
    assert legacy.plasma_running() is False
    home.plasma(comm="kwin_wayland", pid="10")
    (home.proc / "self").mkdir()
    (home.proc / "self" / "comm").write_text("plasmashell\n")
    (home.proc / "11").mkdir()  # Gone meanwhile: no comm.
    assert legacy.plasma_running() is False
    home.plasma(pid="12")
    assert legacy.plasma_running() is True
    # Another user's plasmashell does not count.
    monkeypatch.setattr(legacy.os, "getuid", lambda: os.geteuid() + 1)
    assert legacy.plasma_running() is False


def test_unreadable_proc_is_os_error(home, monkeypatch, capsys):
    home.old_install()
    monkeypatch.setattr(legacy, "PROC", str(home.root / "no-proc"))
    assert migrate("run", capsys) == {"ok": False, "error": "os-error"}
    assert (home.data / OLD).is_dir()


# --- rollback ----------------------------------------------------------------------------------------


def test_rollback_round_trip_restores_everything_but_the_cache(home, capsys):
    home.old_install()
    before = {path: value for path, value in home.tree().items() if not path.startswith("cache")}
    full_migration(home, capsys)
    assert migrate("rollback", capsys) == {
        "ok": True, "restored": ["data", "config", "notifyrc", "wallet-entry", "applets"], "pending": []}
    after = {path: value for path, value in home.tree().items()
             if not path.startswith("cache") and not path.endswith(".hearthside-backup")}
    assert after == before
    assert home.wallet() == {OLD_KEY: MARKER_KEY}
    assert migrate("status", capsys)["pending"] == ["data", "config", "notifyrc", "wallet-entry", "applets"]
    # And forward again.
    assert migrate("run", capsys)["migrated"] == ["data", "config", "notifyrc", "wallet-entry"]
    assert migrate("applets", capsys)["migrated"] == ["applets"]
    assert_migrated(home)


def test_rollback_is_idempotent_and_needs_plasma_stopped(home, capsys):
    home.old_install()
    full_migration(home, capsys)
    home.plasma()
    before = home.tree()
    assert migrate("rollback", capsys) == {"ok": False, "error": "plasma-running"}
    assert home.tree() == before
    (home.proc / "4242" / "comm").unlink()
    migrate("rollback", capsys)
    assert migrate("rollback", capsys) == {"ok": True, "restored": [], "pending": []}


def test_rollback_with_a_failing_wallet_copy_reports_pending(home, capsys):
    home.old_install()
    full_migration(home, capsys)
    home.stubs.env(STUB_KWALLET_WRITE_EXIT=1)
    reply = migrate("rollback", capsys)
    assert reply["pending"] == ["wallet-entry"] and "wallet-entry" not in reply["restored"]
    assert home.wallet()[NEW_KEY] == MARKER_KEY


def test_rollback_without_a_slot_makes_no_wallet_call(home, capsys):
    home.old_install(wallet=False)
    migrate("run", capsys)
    migrate("applets", capsys)
    home.stubs.log.write_text("")
    assert migrate("rollback", capsys)["restored"] == ["data", "config", "notifyrc", "applets"]
    assert home.wallet_calls() == []


# --- D5: the new helper refuses while old data waits -----------------------------------------------


def test_legacy_data_present_is_any_entry_under_the_old_name(home):
    assert legacy.legacy_data_present() is False
    (home.data / OLD).symlink_to(home.root / "missing")
    assert legacy.legacy_data_present() is True


# --- output and secrets ------------------------------------------------------------------------------


def test_replies_never_contain_a_path_the_name_or_the_key(home, capsys, tmp_path):
    outputs = []
    home.old_install()
    home.plasma()
    for operation in ("status", "run", "applets", "rollback"):
        assert cli.main(["--migrate", operation]) == 0
        captured = capsys.readouterr()
        outputs.append(captured.out + captured.err)
    (home.proc / "4242" / "comm").unlink()
    for operation in ("status", "run", "applets", "status", "rollback", "status", "run"):
        assert cli.main(["--migrate", operation]) == 0
        captured = capsys.readouterr()
        outputs.append(captured.out + captured.err)
    text = "".join(outputs)
    assert "/" not in text and str(tmp_path) not in text
    assert MARKER_KEY not in text and sha(MARKER_KEY) not in text
    assert "kdewallet" not in text and "earth" not in text.lower()
    for reply in map(json.loads, text.splitlines()):
        assert set(reply) <= {"ok", "error", "category", "pending", "present", "migrated", "restored"}
        assert reply.get("error", "os-error") in legacy.ERRORS
        for key in ("pending", "present", "migrated", "restored"):
            assert set(reply.get(key, [])) <= set(legacy.CATEGORIES)
    # The stubs never log a value either (only its hash).
    assert MARKER_KEY not in home.stubs.log.read_text()


def test_python_never_reads_the_key(home, capsys, monkeypatch):
    seen = []
    real_read = os.read

    def spy_read(fd, size):
        data = real_read(fd, size)
        seen.append(data)
        return data

    monkeypatch.setattr(os, "read", spy_read)
    home.old_install()
    full_migration(home, capsys)
    migrate("rollback", capsys)
    assert seen  # appletsrc is read with os.read
    assert not any(MARKER_KEY.encode() in data for data in seen)


def test_an_unexpected_exception_is_a_bare_code(home, capsys, monkeypatch):
    monkeypatch.setattr(legacy, "_survey", lambda environ: 1 / 0)
    assert migrate("status", capsys) == {"ok": False, "error": "os-error"}


def test_unknown_helper_codes_become_os_error(home, capsys, monkeypatch):
    def fail(environ):
        raise webdata.HelperError("no-runtime-dir")

    monkeypatch.setattr(legacy, "_survey", fail)
    assert migrate("status", capsys) == {"ok": False, "error": "os-error"}


@pytest.mark.parametrize("argv", [
    ["--migrate", "move"], ["--migrate"], ["--migrate", "run", "--json"], ["--migrate", "run", "--vault", "status"],
    ["--migrate", "status", "--applet", "1"], ["--migrate", "run", "--web-data", "purge"],
])
def test_migrate_stands_alone(home, capsys, argv):
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 2
    assert capsys.readouterr().out == ""


def test_operations_and_categories_are_the_documented_ones():
    assert legacy.OPERATIONS == ("status", "run", "applets", "rollback")
    assert legacy.CATEGORIES == ("data", "config", "notifyrc", "cache", "wallet-entry", "applets")
    assert legacy.ERRORS == ("not-locked", "busy", "symlink", "not-directory", "not-owned", "conflict",
                             "plasma-running", "invalid", "os-error")


# --- static rules ------------------------------------------------------------------------------------


def test_legacy_source_rules():
    code = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] in sys.stdlib_module_names for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            assert (node.module or "").split(".")[0] in sys.stdlib_module_names
    # Never recursive deletes, shells, prints or captured child output; children
    # run only through walletkey and vault.
    for pattern in (r"\brmtree\b", r"\bshutil\b", r"\bsubprocess\b", r"(?<![\w.])print\s*\(", r"\bos\.system\b",
                    r"\bos\.popen\b", r"\bremove_entry\(\s*(?:data|app|base|parent)", r"\bos\.removedirs\b",
                    r"\bsys\.std(out|err)\b"):
        assert not re.search(pattern, code), pattern
    # Every rename goes through _rename (NOREPLACE) except the appletsrc replace.
    renames = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute) and node.func.attr in ("rename", "replace")
               and isinstance(node.func.value, ast.Name) and node.func.value.id == "os"]
    assert len(renames) == 2


@pytest.mark.parametrize(("old", "new"), [
    ("        os.rmdir(LEGACY_NAME, dir_fd=parent)\n", "        import shutil\n        shutil.rmtree(LEGACY_NAME)\n"),
    ("    _rename(parent, source, target)\n    moved", "    os.rename(source, target)\n    moved"),
    ("    return \"migrated\"\n", "    print(wallet)\n    return \"migrated\"\n"),
])
def test_proof_legacy_source_rules_catch(old, new, monkeypatch, tmp_path):
    code = SOURCE.read_text(encoding="utf-8")
    assert old in code
    mutated = tmp_path / "legacy.py"
    mutated.write_text(code.replace(old, new, 1))
    monkeypatch.setattr(sys.modules[__name__], "SOURCE", mutated)
    with pytest.raises(AssertionError):
        test_legacy_source_rules()


# --- R4 audit -----------------------------------------------------------------------------------------


def _replace_with_link(path, target):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()
    path.symlink_to(target)


def _foreign(monkeypatch, name):
    """``name`` looks like another user's, for every no-follow lookup by directory fd."""
    real = os.stat

    def fake(path, *arguments, **keywords):
        info = real(path, *arguments, **keywords)
        if path == name and keywords.get("dir_fd") is not None:
            values = list(info)
            values[4] = os.getuid() + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(os, "stat", fake)


def _precious(root):
    directory = root / "precious"
    directory.mkdir()
    (directory / "file").write_text("keep")
    return directory


# M1: nothing is rewritten before everything has been checked.
@pytest.mark.parametrize(("name", "reply"), [
    ("conflict", {"ok": False, "error": "conflict", "category": "data"}),
    ("cache-link", {"ok": False, "error": "symlink", "category": "cache"}),
])
def test_applets_checks_everything_before_rewriting(home, capsys, tmp_path, name, reply):
    home.old_install()
    if name == "conflict":
        (home.data / NEW).mkdir()
        (home.data / NEW / "keep").write_text("mine")
    else:
        _replace_with_link(home.cache / OLD / "antigravity-auth.json", _precious(tmp_path) / "file")
    before = home.tree()
    assert migrate("applets", capsys) == reply
    assert home.tree() == before and not home.backup.exists()


def test_applets_reports_what_is_left_without_a_second_survey(home, capsys, monkeypatch):
    home.old_install()
    migrate("run", capsys)
    real, calls = legacy._survey, []
    monkeypatch.setattr(legacy, "_survey", lambda environ: calls.append(1) or real(environ))
    assert migrate("applets", capsys) == {"ok": True, "migrated": ["applets"], "pending": []}
    assert len(calls) == 1


# M2: the fixed children of the folder about to move.
CHILDREN = [("vault", "data"), ("usage-history", "data"), ("vault-keys/wallet.conf", "wallet-entry"),
            ("vault-keys/wallet.conf.old", "wallet-entry"), ("vault-keys/wallet.conf.new", "wallet-entry")]


@pytest.mark.parametrize(("child", "category"), CHILDREN)
@pytest.mark.parametrize("operation", ["status", "run", "applets"])
def test_a_symlinked_child_of_the_old_folder_refuses(home, capsys, tmp_path, child, category, operation):
    home.old_install()
    target = _precious(tmp_path)
    _replace_with_link(home.data / OLD / child, target)
    before = home.tree()
    assert migrate(operation, capsys) == {"ok": False, "error": "symlink", "category": category}
    assert home.tree() == before and (target / "file").read_text() == "keep"
    assert home.wallet() == {OLD_KEY: MARKER_KEY} and home.wallet_calls() == []


@pytest.mark.parametrize(("child", "category"), CHILDREN[:3])
def test_a_foreign_child_of_the_old_folder_refuses(home, capsys, monkeypatch, child, category):
    home.old_install()
    before = home.tree()
    _foreign(monkeypatch, child.rsplit("/", 1)[-1])
    assert migrate("run", capsys) == {"ok": False, "error": "not-owned", "category": category}
    assert home.tree() == before and home.wallet_calls() == []


def test_a_foreign_vault_keys_folder_refuses(home, capsys, monkeypatch):
    home.old_install()
    before = home.tree()
    _foreign(monkeypatch, "vault-keys")
    assert migrate("status", capsys) == {"ok": False, "error": "not-owned", "category": "wallet-entry"}
    assert home.tree() == before and home.wallet_calls() == []


@pytest.mark.parametrize(("child", "category"), CHILDREN)
def test_rollback_walks_the_new_folder_the_same_way(home, capsys, tmp_path, child, category):
    home.old_install()
    full_migration(home, capsys)
    home.stubs.log.write_text("")
    _replace_with_link(home.data / NEW / child, _precious(tmp_path))
    before = home.tree()
    assert migrate("rollback", capsys) == {"ok": False, "error": "symlink", "category": category}
    assert home.tree() == before and home.wallet_calls() == []


def test_a_symlinked_slot_under_the_new_name_is_refused_without_a_wallet_call(home, capsys, tmp_path):
    home.old_install()
    full_migration(home, capsys)
    home.stubs.log.write_text("")
    _replace_with_link(home.slot_dir(NEW) / "wallet.conf", _precious(tmp_path) / "file")
    assert migrate("status", capsys) == {"ok": False, "error": "symlink", "category": "wallet-entry"}
    assert home.wallet_calls() == []


def test_a_foreign_slot_under_the_new_name_is_refused_without_a_wallet_call(home, capsys, monkeypatch):
    home.old_install()
    full_migration(home, capsys)
    home.stubs.log.write_text("")
    _foreign(monkeypatch, "wallet.conf")
    assert migrate("status", capsys) == {"ok": False, "error": "not-owned", "category": "wallet-entry"}
    assert home.wallet_calls() == []


# L1: nothing can stop the run after the data has moved.
@pytest.mark.parametrize("name", ["antigravity-auth.json", CACHE_TEMPORARY])
def test_a_symlinked_cache_file_refuses_before_the_data_moves(home, capsys, tmp_path, name):
    home.old_install()
    _replace_with_link(home.cache / OLD / name, _precious(tmp_path) / "file")
    before = home.tree()
    assert migrate("status", capsys) == {"ok": False, "error": "symlink", "category": "cache"}
    assert migrate("run", capsys) == {"ok": False, "error": "symlink", "category": "cache"}
    assert home.tree() == before


def test_a_directory_named_like_the_cache_file_refuses_before_the_data_moves(home, capsys):
    home.old_install()
    (home.cache / OLD / "antigravity-auth.json").unlink()
    (home.cache / OLD / "antigravity-auth.json").mkdir()
    assert migrate("run", capsys) == {"ok": False, "error": "not-directory", "category": "cache"}
    assert (home.data / OLD).is_dir()


def test_a_symlinked_backup_refuses_before_the_data_moves(home, capsys, tmp_path):
    home.old_install()
    home.backup.symlink_to(_precious(tmp_path) / "file")
    before = home.tree()
    assert migrate("run", capsys) == {"ok": False, "error": "symlink", "category": "applets"}
    assert home.tree() == before


def test_a_directory_at_the_temporary_name_refuses_before_the_data_moves(home, capsys):
    home.old_install()
    (home.config / legacy.TEMPORARY_NAME).mkdir()
    assert migrate("run", capsys) == {"ok": False, "error": "not-directory", "category": "applets"}
    assert (home.data / OLD).is_dir()


def test_a_symlinked_backup_does_not_block_a_finished_move(home, capsys, tmp_path):
    home.old_install()
    full_migration(home, capsys)
    _replace_with_link(home.backup, _precious(tmp_path) / "file")
    assert migrate("status", capsys)["pending"] == []


def test_rollback_checks_the_backup_and_appletsrc_before_moving_anything(home, capsys, tmp_path):
    home.old_install()
    full_migration(home, capsys)
    _replace_with_link(home.backup, _precious(tmp_path) / "file")
    before = home.tree()
    assert migrate("rollback", capsys) == {"ok": False, "error": "symlink", "category": "applets"}
    assert home.tree() == before and home.wallet() == {NEW_KEY: MARKER_KEY}


# L2: the new entry stays until the old copy is proven.
def _cmp_order(home):
    return [call["tool"] for call in home.stubs.calls() if call["tool"] == "cmp"
            or (call["tool"] == "qdbus6" and call["argv"][2].endswith(".removeEntry"))]


def test_rollback_compares_before_it_removes_the_new_entry(home, capsys):
    home.old_install()
    full_migration(home, capsys)
    home.stubs.log.write_text("")
    assert "wallet-entry" in migrate("rollback", capsys)["restored"]
    assert _cmp_order(home) == ["cmp", "qdbus6"]
    assert home.wallet() == {OLD_KEY: MARKER_KEY}
    (read_new, read_old) = [call for call in home.stubs.calls("kwallet-query") if "--read-password" in call["argv"]][1:3]
    assert read_new["fds"][1].startswith("pipe:") and read_old["fds"][1].startswith("pipe:")
    assert (read_new["argv"][1], read_old["argv"][1]) == ("Hearthwire", "Hearthside")
    assert read_new["sha"] == read_old["sha"] == sha(MARKER_KEY)


@pytest.mark.parametrize("failure", ["differs", "no-cmp", "second-read-fails"])
def test_rollback_keeps_both_entries_without_proof(home, capsys, failure):
    home.old_install()
    full_migration(home, capsys)
    if failure == "differs":
        home.stubs.env(STUB_CMP_EXIT=1)
    elif failure == "no-cmp":
        home.stubs.remove("cmp")
    home.stubs.log.write_text("")
    if failure == "second-read-fails":
        real = walletkey.read_key_into_pipe
        calls = []

        def failing(*arguments, **keywords):
            calls.append(1)
            if len(calls) == 3:  # The copy's read, then the two reads of the proof.
                raise webdata.HelperError("wallet-failed")
            return real(*arguments, **keywords)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(walletkey, "read_key_into_pipe", failing)
            reply = migrate("rollback", capsys)
    else:
        reply = migrate("rollback", capsys)
    assert reply["pending"] == ["wallet-entry"] and "wallet-entry" not in reply["restored"]
    assert home.wallet() == {NEW_KEY: MARKER_KEY, OLD_KEY: MARKER_KEY}


def test_a_rollback_stopped_by_a_cancelled_dialog_is_finished_by_the_next(home, capsys):
    home.old_install()
    full_migration(home, capsys)
    home.stubs.env(STUB_KWALLET_READ_EXIT=1)
    reply = migrate("rollback", capsys)
    assert reply["pending"] == ["wallet-entry"] and "data" in reply["restored"]
    assert home.wallet() == {NEW_KEY: MARKER_KEY}
    # The slot has moved back with the data, and the entries decide.
    assert (home.slot_dir(OLD) / "wallet.conf").exists() and not (home.data / NEW).exists()
    home.stubs.env(STUB_KWALLET_READ_EXIT=0)
    assert migrate("rollback", capsys) == {"ok": True, "restored": ["wallet-entry"], "pending": []}
    assert home.wallet() == {OLD_KEY: MARKER_KEY}


def test_rollback_leaves_a_lone_new_staging_entry(home, capsys):
    home.old_install()
    full_migration(home, capsys)
    home.set_wallet({NEW_STAGED: OTHER_KEY})
    assert "wallet-entry" not in migrate("rollback", capsys)["restored"]
    assert home.wallet() == {NEW_STAGED: OTHER_KEY}


def test_rollback_removes_the_new_staging_entry_after_the_proof(home, capsys):
    home.old_install()
    full_migration(home, capsys)
    home.set_wallet({NEW_KEY: MARKER_KEY, NEW_STAGED: OTHER_KEY})
    assert "wallet-entry" in migrate("rollback", capsys)["restored"]
    assert home.wallet() == {OLD_KEY: MARKER_KEY}


@pytest.mark.skipif(not os.path.exists("/usr/bin/cmp"), reason="no cmp here")
@pytest.mark.parametrize(("other", "equal"), [(MARKER_KEY, True), (OTHER_KEY, False)])
def test_entries_equal_works_with_the_real_cmp_over_two_pipes(home, other, equal):
    (home.stubs.bin / "cmp").unlink()
    (home.stubs.bin / "cmp").symlink_to("/usr/bin/cmp")
    home.set_wallet({NEW_KEY: MARKER_KEY, OLD_KEY: other})
    tools, _ = walletkey.find_tools()
    assert walletkey.entries_equal(tools, "kdewallet", walletkey.FOLDER, walletkey.LEGACY_FOLDER) is equal


# L3: nothing creates the new folder while the old one waits.
@pytest.fixture
def waiting(home):
    (home.data / OLD).mkdir()
    return home


def test_recording_usage_refuses_while_old_data_waits(waiting):
    assert usagehistory.run("record", sample="claude.session=5") == {"ok": False, "error": "legacy-data"}
    assert not (waiting.data / NEW).exists()


def test_exporting_settings_refuses_while_old_data_waits(waiting):
    assert settingsbackup.run("export", data=hexed(GOOD)) == {"ok": False, "error": "legacy-data"}
    assert not (waiting.config / NEW).exists()


def test_reading_history_and_backup_status_still_work_while_old_data_waits(waiting):
    assert usagehistory.run("read")["ok"] is True
    assert settingsbackup.run("status")["ok"] is True
    assert not (waiting.data / NEW).exists() and not (waiting.config / NEW).exists()


def test_both_writers_work_once_the_old_data_has_moved(home):
    assert usagehistory.run("record", sample="claude.session=5")["ok"] is True
    assert settingsbackup.run("export", data=hexed(GOOD))["ok"] is True


# L5: only the wallet entry left never needs Plasma stopped.
def _only_wallet_left(home, capsys):
    home.old_install()
    home.stubs.env(STUB_WALLET_ENABLED="false")
    migrate("run", capsys)
    migrate("applets", capsys)
    assert migrate("status", capsys)["pending"] == ["wallet-entry"]


def test_a_wallet_only_status_ignores_a_mounted_vault(home, capsys):
    _only_wallet_left(home, capsys)
    _mount_line(home, home.runtime / NEW / "vault", home.data / NEW / "vault")
    assert migrate("status", capsys)["pending"] == ["wallet-entry"]


def test_a_wallet_only_run_does_not_need_plasma_stopped(home, capsys):
    _only_wallet_left(home, capsys)
    home.plasma()
    assert migrate("run", capsys) == {"ok": True, "migrated": [], "pending": ["wallet-entry"]}
    home.stubs.env(STUB_WALLET_ENABLED="true")
    assert migrate("run", capsys) == {"ok": True, "migrated": ["wallet-entry"], "pending": []}
    assert home.wallet() == {NEW_KEY: MARKER_KEY}


def test_a_wallet_and_applets_status_still_refuses_a_mounted_vault(home, capsys):
    home.appletsrc.write_bytes(APPLETSRC)
    home.slot_dir(NEW).mkdir(parents=True)
    (home.slot_dir(NEW) / "wallet.conf").write_text("{}")
    home.set_wallet({OLD_KEY: MARKER_KEY})
    _mount_line(home, home.runtime / NEW / "vault", home.data / NEW / "vault")
    assert migrate("status", capsys) == {"ok": False, "error": "not-locked"}
