"""KDE Wallet unlock for the encrypted Chat folder (core/walletkey.py, vault.py R3).

Reuses test_vault's stubs: gocryptfs, kdialog, fusermount3, kwallet-query, qdbus6
and openssl are scripts in a private PATH. The stub wallet is a JSON file with
dummy values; the stubs log sha256 hashes only. The stub gocryptfs keeps the
hash of the key it was given on ``-passwd -config`` stdin inside the slot copy
and, when mounting with ``-config``, compares it with the hash of its extpass
output, exactly like the measured gocryptfs: 9 when the extpass fails, 12 when
the key does not fit. A real wallet, bus or dialog is never used (conftest points
D-Bus at a socket that does not exist).
"""

import ast
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from hearthside import cli
from hearthside.core import vault, walletkey, webdata
from test_vault import Stubs, _stale, reply, vault_argv  # noqa: F401  (fixture helpers)

SOURCE = Path(walletkey.__file__)
VAULT_SOURCE = Path(vault.__file__)
KEY = "Hearthside/encrypted-chat-folder"


@pytest.fixture
def stubs(tmp_path, monkeypatch, _private_runtime_dir):
    result = Stubs(tmp_path, monkeypatch, _private_runtime_dir)
    monkeypatch.setattr(walletkey, "QUERY_TIMEOUT", 5.0)
    return result


def keys_dir(stubs):
    return Path(os.path.realpath(stubs.data)) / "hearthside" / "vault-keys"


def slot(stubs):
    return keys_dir(stubs) / "wallet.conf"


def wallet_state(stubs):
    return json.loads(stubs.wallet.read_text()) if stubs.wallet.exists() else {}


def unlock_wallet(capsys):
    return reply("unlock", capsys, "--method", "wallet")


def tools_called(stubs, *, without=("qdbus6",)):
    return [call["tool"] for call in stubs.calls() if call["tool"] not in without]


def enrolled(stubs, capsys):
    stubs.make_locked()
    assert reply("add-key", capsys) == {"ok": True}
    stubs.log.write_text("")


# --- set-up (add-key) ---------------------------------------------------------------------


def test_add_key_moves_the_key_fd_to_fd_and_unlock_uses_it(stubs, capsys):
    stubs.make_locked()
    conf_before = (stubs.cipher / "gocryptfs.conf").read_bytes()
    assert reply("add-key", capsys) == {"ok": True}
    calls = stubs.calls()
    kq = [call for call in calls if call["tool"] in ("openssl", "kwallet-query")]
    (passwd,) = [call for call in calls if call["tool"] == "gocryptfs" and "-passwd" in call["argv"]]
    steps = [(call["tool"], "w" if "--write-password" in call["argv"] else "r" if call["tool"] != "openssl" else "",
              call.get("entry", "")) for call in kq]
    new, real = "encrypted-chat-folder.new", "encrypted-chat-folder"
    # Staged key, re-keyed slot, then the key moved to the real entry, then the
    # staging entry overwritten (and deleted).
    assert steps == [("openssl", "", ""), ("kwallet-query", "w", new), ("kwallet-query", "r", new),
                     ("kwallet-query", "r", new), ("kwallet-query", "w", real),
                     ("openssl", "", ""), ("kwallet-query", "w", new)]
    openssl, stage, read, copy_read, copy_write = kq[0], kq[1], kq[2], kq[3], kq[4]
    # Pipes only, never a file or a terminal; stderr always /dev/null.
    assert openssl["fds"][1].startswith("pipe:") and openssl["fds"][0] == "/dev/null"
    for call in (stage, copy_write):
        assert call["fds"][0].startswith("pipe:") and call["fds"][1:] == ["/dev/null"] * 2
    for call in (read, copy_read):
        assert call["fds"][1].startswith("pipe:") and call["fds"][0] == "/dev/null" and call["fds"][2] == "/dev/null"
    assert passwd["fds"][0].startswith("pipe:") and passwd["fds"][1:] == ["/dev/null"] * 2
    # The same key went openssl -> staging entry -> gocryptfs stdin -> real entry.
    stored = wallet_state(stubs)[KEY]
    assert re.fullmatch(r"[0-9a-f]{64}", stored)
    assert KEY + ".new" not in wallet_state(stubs)
    digest = hashlib.sha256(stored.encode()).hexdigest()
    assert stage["sha"] == read["sha"] == passwd["stdin_sha"] == copy_read["sha"] == copy_write["sha"] == digest
    assert hashlib.sha256((stored + "\n").encode()).hexdigest() == openssl["sha"]
    assert kq[6]["sha"] != digest
    # argv: long options, our folder, entry and the wallet's name; -config is the copy.
    assert copy_write["argv"] == ["--folder", "Hearthside", "--write-password", real, "kdewallet"]
    assert read["argv"] == ["--folder", "Hearthside", "--read-password", new, "kdewallet"]
    config = passwd["argv"][passwd["argv"].index("-config") + 1]
    assert config == str(keys_dir(stubs) / "wallet.conf.new")
    assert stat.S_IMODE(os.lstat(slot(stubs)).st_mode) == 0o400
    assert stat.S_IMODE(os.lstat(keys_dir(stubs)).st_mode) == 0o700
    assert sorted(os.listdir(keys_dir(stubs))) == ["wallet.conf"]
    # The passphrase slot is never touched.
    assert (stubs.cipher / "gocryptfs.conf").read_bytes() == conf_before
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "set-up"}

    stubs.log.write_text("")
    assert unlock_wallet(capsys) == {"ok": True}
    (mount,) = stubs.calls("gocryptfs")
    assert mount["argv"][:4] == ["-q", "-nosyslog", "-config", str(slot(stubs))]
    assert [mount["argv"][i + 1] for i, a in enumerate(mount["argv"]) if a == "-extpass"] == [
        str(stubs.bin / "kwallet-query"), "--folder", "Hearthside", "--read-password", "encrypted-chat-folder",
        "kdewallet"]
    assert mount["fds"] == ["/dev/null"] * 3
    assert mount["extpass_sha"] == digest
    assert stubs.calls("kdialog") == []
    assert reply("status", capsys) == {"ok": True, "state": "unlocked", "wallet": "set-up"}


def test_add_key_works_while_unlocked(stubs, capsys):
    stubs.make_locked()
    assert reply("unlock", capsys) == {"ok": True}
    assert reply("add-key", capsys) == {"ok": True}
    assert reply("status", capsys) == {"ok": True, "state": "unlocked", "wallet": "set-up"}
    assert reply("lock", capsys) == {"ok": True}
    assert unlock_wallet(capsys) == {"ok": True}


@pytest.mark.parametrize("state", ["absent", "damaged"])
def test_add_key_needs_a_folder(stubs, capsys, state):
    if state == "damaged":
        stubs.cipher.mkdir(parents=True)
        (stubs.cipher / "stray").write_text("")
    assert reply("add-key", capsys) == {"ok": False, "error": state}
    assert tools_called(stubs) == []
    assert not keys_dir(stubs).exists()


@pytest.mark.parametrize(
    ("settings", "error", "entry_left"),
    [
        ({"STUB_PASSWD_EXIT": 12}, "wrong-passphrase", False),
        ({"STUB_KDIALOG_EXIT": 1}, "cancelled", False),
        ({"STUB_PASSWD_EXIT": 24}, "wallet-write-failed", False),
        ({"STUB_PASSWD_EXIT": 6}, "absent", False),
        ({"STUB_PASSWD_EXIT": 77}, "wallet-write-failed", False),
    ],
)
def test_add_key_failure_after_the_key_was_written_cleans_up(stubs, capsys, settings, error, entry_left):
    stubs.make_locked()
    stubs.env(**settings)
    assert reply("add-key", capsys) == {"ok": False, "error": error}
    assert os.listdir(keys_dir(stubs)) == []
    assert (KEY in wallet_state(stubs)) is entry_left
    # The entry was overwritten with a fresh value before it was removed.
    writes = [call for call in stubs.calls("kwallet-query") if "--write-password" in call["argv"]]
    assert len(writes) == 2 and writes[0]["sha"] != writes[1]["sha"]
    assert reply("status", capsys)["wallet"] == "off"


def test_add_key_never_feeds_a_failed_read_to_gocryptfs(stubs, capsys):
    # kwallet-query prints its error on stdout: that pipe must never reach gocryptfs.
    stubs.make_locked()
    stubs.env(STUB_KWALLET_READ_EXIT=4)
    assert reply("add-key", capsys) == {"ok": False, "error": "wallet-failed"}
    assert [call for call in stubs.calls("gocryptfs") if "-passwd" in call["argv"]] == []
    assert os.listdir(keys_dir(stubs)) == []


@pytest.mark.parametrize(
    ("settings", "error"),
    [({"STUB_KWALLET_WRITE_EXIT": 1}, "wallet-failed"), ({"STUB_OPENSSL_EXIT": 1}, "wallet-write-failed")],
)
def test_add_key_stops_when_the_key_cannot_be_stored(stubs, capsys, settings, error):
    stubs.make_locked()
    stubs.env(**settings)
    assert reply("add-key", capsys) == {"ok": False, "error": error}
    assert stubs.calls("gocryptfs") == []
    assert [call for call in stubs.calls("kwallet-query") if "--read-password" in call["argv"]] == []
    assert os.listdir(keys_dir(stubs)) == []


def test_add_key_times_out_on_an_unanswered_wallet_prompt(stubs, capsys, monkeypatch):
    stubs.make_locked()
    monkeypatch.setattr(walletkey, "PROMPT_TIMEOUT", 0.3)
    stubs.env(STUB_KWALLET_SLEEP=5)
    assert reply("add-key", capsys) == {"ok": False, "error": "wallet-failed"}
    assert stubs.calls("gocryptfs") == []
    assert os.listdir(keys_dir(stubs)) == []


@pytest.mark.parametrize(
    ("settings", "error"),
    [({"STUB_WALLET_ENABLED": "false"}, "wallet-disabled"), ({"STUB_WALLET_ENABLED": "maybe"}, "wallet-failed"),
     ({"STUB_QDBUS_EXIT": 1}, "wallet-failed"), ({"STUB_WALLET_NAME": "-x"}, "wallet-failed"),
     ({"STUB_WALLET_NAME": "a/b"}, "wallet-failed"), ({"STUB_WALLET_NAME": "x" * 65}, "wallet-failed")],
)
def test_add_key_preflight(stubs, capsys, settings, error):
    stubs.make_locked()
    stubs.env(**settings)
    assert reply("add-key", capsys) == {"ok": False, "error": error}
    assert tools_called(stubs) == []


def test_qdbus_timeouts_are_wallet_failed(stubs, capsys, monkeypatch):
    stubs.make_locked()
    monkeypatch.setattr(walletkey, "QUERY_TIMEOUT", 0.3)
    stubs.env(STUB_QDBUS_SLEEP=5)
    assert reply("add-key", capsys) == {"ok": False, "error": "wallet-failed"}
    assert unlock_wallet(capsys) == {"ok": False, "error": "wallet-failed"}
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "unavailable"}


def test_add_key_clears_leftovers_and_replaces_an_old_slot(stubs, capsys):
    enrolled(stubs, capsys)
    old_inode = os.lstat(slot(stubs)).st_ino
    old_value = wallet_state(stubs)[KEY]
    (keys_dir(stubs) / "wallet.conf.new.tmp").symlink_to(stubs.root / "nowhere")
    (keys_dir(stubs) / "wallet.conf.new").write_text("junk")
    assert reply("add-key", capsys) == {"ok": True}
    assert os.lstat(slot(stubs)).st_ino != old_inode
    assert wallet_state(stubs)[KEY] != old_value
    assert sorted(os.listdir(keys_dir(stubs))) == ["wallet.conf"]
    assert not (stubs.root / "nowhere").exists()
    assert unlock_wallet(capsys) == {"ok": True}


def test_symlinked_vault_keys_is_refused(stubs, capsys, tmp_path):
    stubs.make_locked()
    target = tmp_path / "elsewhere"
    target.mkdir()
    keys_dir(stubs).parent.mkdir(parents=True, exist_ok=True)
    keys_dir(stubs).symlink_to(target)
    assert reply("add-key", capsys) == {"ok": False, "error": "symlink"}
    assert unlock_wallet(capsys) == {"ok": False, "error": "symlink"}
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "off"}
    assert reply("remove-key", capsys) == {"ok": False, "error": "symlink"}
    assert list(target.iterdir()) == []
    assert stubs.calls("gocryptfs") == []


@pytest.mark.parametrize("problem", ["mode-0644", "mode-0600", "symlink", "directory"])
def test_only_a_0400_regular_slot_counts(stubs, capsys, tmp_path, problem):
    enrolled(stubs, capsys)
    path = slot(stubs)
    if problem.startswith("mode"):
        path.chmod(int(problem[-4:], 8))
    else:
        content = path.read_bytes()
        path.unlink()
        if problem == "symlink":
            (tmp_path / "real.conf").write_bytes(content)
            (tmp_path / "real.conf").chmod(0o400)
            path.symlink_to(tmp_path / "real.conf")
        else:
            path.mkdir()
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "off"}
    assert unlock_wallet(capsys) == {"ok": False, "error": "not-set-up"}
    assert stubs.calls("gocryptfs") == []


# --- unlock --method wallet ---------------------------------------------------------------


def test_unlock_wallet_without_a_slot_is_not_set_up(stubs, capsys):
    stubs.make_locked()
    assert unlock_wallet(capsys) == {"ok": False, "error": "not-set-up"}
    assert tools_called(stubs) == []


def test_unlock_wallet_without_the_entry_is_not_set_up(stubs, capsys):
    enrolled(stubs, capsys)
    stubs.wallet.write_text("{}")
    assert unlock_wallet(capsys) == {"ok": False, "error": "not-set-up"}
    assert tools_called(stubs) == []


def test_unlock_wallet_with_a_changed_entry_is_a_mismatch(stubs, capsys):
    enrolled(stubs, capsys)
    stubs.wallet.write_text(json.dumps({KEY: "0" * 64}))
    assert unlock_wallet(capsys) == {"ok": False, "error": "wallet-mismatch"}
    assert not stubs.mounted()
    assert stubs.mountpoint_mode() == vault.SEALED_MODE


def test_unlock_wallet_read_failure_is_wallet_failed(stubs, capsys):
    enrolled(stubs, capsys)
    stubs.env(STUB_KWALLET_READ_EXIT=1)
    assert unlock_wallet(capsys) == {"ok": False, "error": "wallet-failed"}
    assert not stubs.mounted()


def test_unlock_wallet_times_out(stubs, capsys, monkeypatch):
    enrolled(stubs, capsys)
    monkeypatch.setattr(walletkey, "PROMPT_TIMEOUT", 0.3)
    stubs.env(STUB_KWALLET_SLEEP=5)
    assert unlock_wallet(capsys) == {"ok": False, "error": "wallet-failed"}
    assert not stubs.mounted()


@pytest.mark.parametrize(
    ("code", "error"),
    [(9, "wallet-failed"), (12, "wallet-mismatch"), (11, "not-set-up"), (10, "mount-failed"), (6, "absent"),
     (19, "mount-failed"), (55, "mount-failed")],
)
def test_wallet_mount_exit_codes(stubs, capsys, code, error):
    enrolled(stubs, capsys)
    stubs.env(STUB_MOUNT_EXIT=code)
    assert unlock_wallet(capsys) == {"ok": False, "error": error}


def test_unlock_wallet_does_not_need_kdialog(stubs, capsys):
    enrolled(stubs, capsys)
    stubs.remove("kdialog")
    assert unlock_wallet(capsys) == {"ok": True}


@pytest.mark.parametrize("name", ["kwallet-query", "qdbus6"])
def test_unlock_wallet_needs_the_wallet_tools(stubs, capsys, name):
    enrolled(stubs, capsys)
    stubs.remove(name)
    assert unlock_wallet(capsys) == {"ok": False, "error": "missing-tool"}
    assert reply("auto-unlock", capsys) == {"ok": False, "error": "missing-tool"}
    assert stubs.calls("gocryptfs") == []


def test_unlock_without_method_still_uses_the_passphrase(stubs, capsys):
    enrolled(stubs, capsys)
    assert reply("unlock", capsys, "--method", "passphrase") == {"ok": True}
    assert len(stubs.calls("kdialog")) == 0  # The stub kdialog runs as gocryptfs's extpass.
    (mount,) = stubs.calls("gocryptfs")
    assert "-config" not in mount["argv"]


# --- auto-unlock ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "settings",
    [{"STUB_WALLET_LOCKED": "true"}, {"STUB_WALLET_LOCKED": "odd"},
     # Label mismatch and a name that cannot be a collection path: unknown = closed.
     {"STUB_ALIAS_LABEL": "other", "STUB_WALLET_NAME": "my wallet"}],
)
def test_auto_unlock_with_the_wallet_closed_runs_nothing_but_queries(stubs, capsys, settings):
    enrolled(stubs, capsys)
    stubs.env(**settings)
    assert reply("auto-unlock", capsys) == {"ok": False, "error": "wallet-closed"}
    assert tools_called(stubs) == []
    assert not stubs.mounted()
    queried = [call["argv"] for call in stubs.calls("qdbus6")]
    assert all(argv[0] in ("org.kde.kwalletd6", "org.freedesktop.secrets") for argv in queried)
    assert not any(argv[2].endswith((".open", ".isOpen")) for argv in queried)


def test_auto_unlock_with_the_wallet_open_mounts_silently(stubs, capsys):
    enrolled(stubs, capsys)
    assert reply("auto-unlock", capsys) == {"ok": True}
    assert stubs.calls("kdialog") == []
    assert stubs.mounted()
    locked = [call["argv"] for call in stubs.calls("qdbus6") if call["argv"][2] == "Locked"]
    assert locked == [["org.freedesktop.secrets", "/org/freedesktop/secrets/aliases/default", "Locked"]]
    # Already unlocked: nothing runs.
    stubs.log.write_text("")
    assert reply("auto-unlock", capsys) == {"ok": True}
    assert stubs.calls() == []


def test_auto_unlock_falls_back_to_the_collection_path(stubs, capsys):
    enrolled(stubs, capsys)
    stubs.env(STUB_ALIAS_LABEL="other")
    assert reply("auto-unlock", capsys) == {"ok": True}
    locked = [call["argv"] for call in stubs.calls("qdbus6") if call["argv"][2] == "Locked"]
    assert locked == [["org.freedesktop.secrets", "/org/freedesktop/secrets/collection/kdewallet", "Locked"]]


@pytest.mark.parametrize(("setup", "error"), [("none", "absent"), ("folder", "not-set-up")])
def test_auto_unlock_without_a_slot(stubs, capsys, setup, error):
    if setup == "folder":
        stubs.make_locked()
    assert reply("auto-unlock", capsys) == {"ok": False, "error": error}
    assert tools_called(stubs) == []


def test_auto_unlock_never_waits_for_the_vault_lock(stubs, capsys, monkeypatch):
    import fcntl

    enrolled(stubs, capsys)
    holder = os.open(stubs.mountpoint.parent / "vault.lock", os.O_RDWR)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX)
        assert reply("auto-unlock", capsys) == {"ok": False, "error": "busy"}
    finally:
        os.close(holder)


# --- status ----------------------------------------------------------------------------------


def test_status_wallet_field(stubs, capsys):
    assert reply("status", capsys) == {"ok": True, "state": "absent"}
    stubs.make_locked()
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "off"}
    stubs.env(STUB_WALLET_ENABLED="false")
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "unavailable"}
    stubs.remove("kwallet-query")
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "unavailable",
                                       "missing": ["kwallet-query"]}
    stubs.remove("qdbus6")
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "unavailable",
                                       "missing": ["kwallet-query", "qdbus6"]}
    stubs.remove("openssl")
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "unavailable",
                                       "missing": ["kwallet-query", "qdbus6", "openssl"]}
    # Core tools missing: only those are listed, no wallet field.
    stubs.remove("gocryptfs")
    assert reply("status", capsys) == {"ok": True, "state": "unavailable", "missing": ["gocryptfs"]}


def test_status_never_needs_openssl(stubs, capsys):
    enrolled(stubs, capsys)
    stubs.remove("openssl")
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "set-up", "missing": ["openssl"]}
    assert unlock_wallet(capsys) == {"ok": True}
    assert reply("add-key", capsys) == {"ok": False, "error": "missing-tool"}
    assert reply("lock", capsys) == {"ok": True}
    # remove-key needs no openssl: the overwrite is skipped, the entry still goes.
    stubs.log.write_text("")
    assert reply("remove-key", capsys) == {"ok": True}
    assert KEY not in wallet_state(stubs) and not slot(stubs).exists()
    assert [call for call in stubs.calls("kwallet-query") if "--write-password" in call["argv"]] == []
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "off", "missing": ["openssl"]}


# --- remove-key, destroy, purge ---------------------------------------------------------------


def test_remove_key_deletes_slot_then_overwrites_and_deletes_the_entry(stubs, capsys):
    enrolled(stubs, capsys)
    old = wallet_state(stubs)[KEY]
    assert reply("remove-key", capsys) == {"ok": True}
    assert not slot(stubs).exists()
    assert KEY not in wallet_state(stubs)
    calls = stubs.calls()
    (write,) = [call for call in calls if call["tool"] == "kwallet-query"]
    assert "--write-password" in write["argv"] and write["sha"] != hashlib.sha256(old.encode()).hexdigest()
    methods = [call["argv"][2].rsplit(".", 1)[-1] for call in calls if call["tool"] == "qdbus6"]
    at = methods.index("open")
    assert methods[at:at + 4] == ["open", "removeEntry", "close", "keyDoesNotExist"]
    # The staging entry is checked too (there is none here).
    assert [call["argv"][5] for call in calls if call["tool"] == "qdbus6"
            and call["argv"][2].endswith("keyDoesNotExist")][-1] == "encrypted-chat-folder.new"
    (remove,) = [call["argv"] for call in calls if call["tool"] == "qdbus6" and call["argv"][2].endswith("removeEntry")]
    assert remove[3:] == ["7", "Hearthside", "encrypted-chat-folder", "Hearthside"]
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "off"}
    # Again: nothing left, nothing written.
    stubs.log.write_text("")
    assert reply("remove-key", capsys) == {"ok": True}
    assert tools_called(stubs) == []


def test_remove_key_reports_an_entry_it_could_not_delete(stubs, capsys):
    enrolled(stubs, capsys)
    stubs.env(STUB_REMOVE_KEEPS=1)
    assert reply("remove-key", capsys) == {"ok": False, "error": "wallet-failed"}
    assert not slot(stubs).exists()


def test_remove_key_with_the_wallet_disabled_still_removes_the_slot(stubs, capsys):
    enrolled(stubs, capsys)
    stubs.env(STUB_WALLET_ENABLED="false")
    assert reply("remove-key", capsys) == {"ok": False, "error": "wallet-disabled"}
    assert not slot(stubs).exists()
    assert tools_called(stubs) == []


def test_destroy_removes_vault_keys_and_the_entry(stubs, capsys):
    enrolled(stubs, capsys)
    assert reply("destroy", capsys) == {"ok": True}
    assert not keys_dir(stubs).exists() and not stubs.cipher.exists()
    assert KEY not in wallet_state(stubs)
    # Nothing in the wallet: no write, no prompt.
    stubs.log.write_text("")
    assert reply("destroy", capsys) == {"ok": True}
    assert tools_called(stubs) == []


def test_destroy_reports_a_remaining_entry_after_deleting_the_files(stubs, capsys):
    enrolled(stubs, capsys)
    stubs.env(STUB_REMOVE_KEEPS=1)
    assert reply("destroy", capsys) == {"ok": False, "error": "wallet-failed"}
    assert not keys_dir(stubs).exists() and not stubs.cipher.exists()


def test_create_drops_a_stale_slot(stubs, capsys):
    keys_dir(stubs).mkdir(parents=True)
    (keys_dir(stubs) / "wallet.conf").write_text("old")
    assert reply("create", capsys) == {"ok": True}
    assert not keys_dir(stubs).exists()


def test_purge_removes_vault_keys_and_the_entry(stubs, capsys, monkeypatch, tmp_path):
    enrolled(stubs, capsys)
    monkeypatch.setattr(vault, "DEFAULT_RUNTIME", str(tmp_path / "none-{uid}"))
    assert cli.main(["--web-data", "purge"]) == 0
    assert capsys.readouterr().out == '{"ok":true,"removed":["vault","vault-keys","wallet-entry"]}\n'
    assert KEY not in wallet_state(stubs)
    assert not (Path(os.path.realpath(stubs.data)) / "hearthside").exists()
    assert cli.main(["--web-data", "purge"]) == 0
    assert capsys.readouterr().out == '{"ok":true,"removed":[]}\n'


def test_purge_without_wallet_tools_only_deletes_files(stubs, capsys, monkeypatch, tmp_path):
    enrolled(stubs, capsys)
    monkeypatch.setattr(vault, "DEFAULT_RUNTIME", str(tmp_path / "none-{uid}"))
    stubs.remove("qdbus6")
    assert cli.main(["--web-data", "purge"]) == 0
    assert capsys.readouterr().out == '{"ok":true,"removed":["vault","vault-keys"]}\n'
    assert tools_called(stubs, without=()) == []


def test_purge_reports_a_remaining_entry(stubs, capsys, monkeypatch, tmp_path):
    enrolled(stubs, capsys)
    monkeypatch.setattr(vault, "DEFAULT_RUNTIME", str(tmp_path / "none-{uid}"))
    stubs.env(STUB_REMOVE_KEEPS=1)
    assert cli.main(["--web-data", "purge"]) == 0
    assert capsys.readouterr().out == '{"ok":false,"error":"wallet-failed"}\n'
    assert not stubs.cipher.exists()


def _install_purge(tmp_path, stubs, reply_text):
    """Run install.sh --uninstall-web-data with a python3 that prints ``reply_text`` for the purge
    (and {"ok":true} for the --usage-history clear that follows a successful one)."""
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "python3").write_text(
        "#!/bin/sh\n"
        "case \"$*\" in *'--usage-history clear') echo '{\"ok\":true}'; exit 0 ;; esac\n"
        f"printf '%s\\n' '{reply_text}'\n"
    )
    (shim / "python3").chmod(0o755)
    script = Path(__file__).resolve().parent.parent / "scripts" / "install.sh"
    return subprocess.run(["sh", str(script), "--uninstall-web-data"], capture_output=True, text=True,
                          env={"PATH": f"{shim}:/usr/bin:/bin", "HOME": str(tmp_path)}, timeout=30, check=False)


def test_install_script_names_every_purge_category(stubs, tmp_path):
    done = _install_purge(tmp_path, stubs, '{"ok":true,"removed":["vault","vault-keys","wallet-entry"]}')
    assert done.returncode == 0 and done.stderr == ""
    assert done.stdout.splitlines() == [
        "Deleted: encrypted chat folder (saved chat sign-ins).",
        "Deleted: KDE Wallet unlock slot of the encrypted chat folder.",
        "Deleted: the encrypted chat folder's key in KDE Wallet.",
    ]


def test_install_script_reports_a_remaining_wallet_entry(stubs, tmp_path):
    done = _install_purge(tmp_path, stubs, '{"ok":false,"error":"wallet-failed"}')
    assert done.returncode == 1 and done.stdout == ""
    assert "KDE Wallet" in done.stderr


# --- CLI ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [["--vault", "add-key"], ["--vault", "remove-key"], ["--vault", "add-key", "--method", "passphrase"],
     ["--vault", "status", "--method", "wallet"], ["--vault", "auto-unlock", "--method", "wallet"],
     ["--vault", "lock", "--method", "passphrase"], ["--method", "wallet"], ["--vault", "unlock", "--method", "fido2"],
     ["--vault", "unlock", "--method", "wallet", "--prompts", "list"]],
)
def test_method_rules(stubs, capsys, argv):
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 2
    assert capsys.readouterr().out == ""
    assert stubs.calls(skip_version=False) == []


def test_output_never_contains_a_path_or_the_key(stubs, capsys, tmp_path, monkeypatch):
    outputs = []
    stubs.make_locked()
    for operation, extra in (("add-key", ()), ("status", ()), ("unlock", ("--method", "wallet")), ("lock", ()),
                             ("auto-unlock", ()), ("lock", ()), ("remove-key", ()), ("add-key", ()),
                             ("destroy", ())):
        assert cli.main([*vault_argv(operation), *extra]) == 0
        captured = capsys.readouterr()
        outputs.append(captured.out + captured.err)
    stubs.make_locked()
    stubs.env(STUB_KWALLET_READ_EXIT=4, STUB_PASSWD_EXIT=12)
    for operation in ("add-key", "remove-key", "auto-unlock"):
        cli.main(vault_argv(operation))
        captured = capsys.readouterr()
        outputs.append(captured.out + captured.err)
    text = "".join(outputs)
    assert str(tmp_path) not in text and "/" not in text
    assert "kdewallet" not in text and "Hearthside" not in text
    for line in stubs.log.read_text().splitlines():
        record = json.loads(line)
        for value in (record.get("sha"), record.get("stdin_sha")):
            if value:
                assert value not in text


def test_python_never_reads_the_key(stubs, capsys, monkeypatch):
    seen = []
    real_read, real_pread = os.read, os.pread

    def spy_read(fd, size):
        data = real_read(fd, size)
        seen.append(data)
        return data

    def spy_pread(fd, size, offset):
        data = real_pread(fd, size, offset)
        seen.append(data)
        return data

    real_readv, real_preadv = os.readv, os.preadv

    def spy_readv(fd, buffers):
        count = real_readv(fd, buffers)
        seen.extend(bytes(buffer) for buffer in buffers)
        return count

    def spy_preadv(fd, buffers, offset, *flags):
        count = real_preadv(fd, buffers, offset, *flags)
        seen.extend(bytes(buffer) for buffer in buffers)
        return count

    monkeypatch.setattr(os, "read", spy_read)
    monkeypatch.setattr(os, "pread", spy_pread)
    monkeypatch.setattr(os, "readv", spy_readv)
    monkeypatch.setattr(os, "preadv", spy_preadv)
    stubs.make_locked()
    keys = []
    assert reply("add-key", capsys) == {"ok": True}
    keys.append(wallet_state(stubs)[KEY].encode())
    assert reply("auto-unlock", capsys) == {"ok": True}
    assert reply("add-key", capsys) == {"ok": True}  # Re-setup while unlocked (staged, then swapped).
    keys.append(wallet_state(stubs)[KEY].encode())
    assert reply("lock", capsys) == {"ok": True}
    assert reply("unlock", capsys, "--method", "wallet") == {"ok": True}
    assert reply("lock", capsys) == {"ok": True}
    assert reply("remove-key", capsys) == {"ok": True}
    assert keys[0] != keys[1]
    assert not any(key in data for data in seen for key in keys)


# --- argv guard ---------------------------------------------------------------------------------


KQ = "/usr/bin/kwallet-query"
QD = "/usr/bin/qdbus6"


def test_argv_guard_accepts_the_contract_shapes():
    for argv in (
        walletkey.keygen_argv("/usr/bin/openssl"),
        walletkey.write_argv(KQ, "kdewallet"), walletkey.read_argv(KQ, "my wallet.1"),
        walletkey.kwallet_argv(QD, "isEnabled"), walletkey.kwallet_argv(QD, "localWallet"),
        walletkey.kwallet_argv(QD, "keyDoesNotExist", "kdewallet", "Hearthside", "encrypted-chat-folder"),
        walletkey.kwallet_argv(QD, "open", "kdewallet", "0", "Hearthside"),
        walletkey.kwallet_argv(QD, "removeEntry", "12", "Hearthside", "encrypted-chat-folder", "Hearthside"),
        walletkey.kwallet_argv(QD, "close", "12", "false", "Hearthside"),
        walletkey.secrets_argv(QD, "/org/freedesktop/secrets/aliases/default", "Label"),
        walletkey.secrets_argv(QD, "/org/freedesktop/secrets/collection/kdewallet", "Locked"),
    ):
        walletkey.check_argv(argv)
        vault._check_argv(argv)


@pytest.mark.parametrize(
    "argv",
    [["/usr/bin/openssl", "rand", "-hex", "16"], ["/usr/bin/openssl", "rand", "-out", "/x", "32"],
     ["openssl", "rand", "-hex", "32"], [KQ, "--folder", "Hearthside", "--read-password", "other", "kdewallet"],
     [KQ, "-f", "Hearthside", "-r", "encrypted-chat-folder", "kdewallet"],
     [KQ, "--folder", "Hearthside", "--read-password", "encrypted-chat-folder", "-v"],
     [KQ, "--folder", "Hearthside", "--list-entries", "kdewallet"], [KQ, "kdewallet"],
     [QD, "org.kde.kwalletd6", "/modules/kwalletd6", "org.kde.KWallet.readPassword", "1", "a", "b", "c"],
     [QD, "org.kde.kwalletd6", "/modules/kwalletd6", "org.kde.KWallet.removeFolder", "1", "Hearthside", "x"],
     [QD, "org.kde.kwalletd6", "/modules/kwalletd6", "org.kde.KWallet.isEnabled", "x"],
     [QD, "org.kde.kwalletd6", "/other", "org.kde.KWallet.isEnabled"],
     [QD, "org.kde.kwalletd6", "/modules/kwalletd6", "org.kde.KWallet.removeEntry", "1", "Other", "x", "Hearthside"],
     [QD, "org.kde.kwalletd6", "/modules/kwalletd6", "org.kde.KWallet.close", "1", "true", "Hearthside"],
     [QD, "org.kde.kwalletd6", "/modules/kwalletd6", "org.kde.KWallet.open", "-x", "0", "Hearthside"],
     [QD, "org.freedesktop.secrets", "/org/freedesktop/secrets/collection/a/b", "Locked"],
     [QD, "org.freedesktop.secrets", "/org/freedesktop/secrets/aliases/default", "Unlock"],
     [QD, "org.freedesktop.Notifications"], ["/bin/sh", "-c", "kwallet-query"]],
)
def test_argv_guard_refuses_other_shapes(argv):
    with pytest.raises(webdata.HelperError):
        walletkey.check_argv(argv)


def test_extpass_may_only_be_the_exact_wallet_read():
    cipher, mountpoint, config = "/d/hearthside/vault", "/r/hearthside/vault", "/d/hearthside/vault-keys/wallet.conf"
    good = vault.wallet_mount_argv("/usr/bin/gocryptfs", KQ, "kdewallet", config, cipher, mountpoint)
    vault._check_argv(good, config=config)
    for extpass in ([KQ, "--folder", "Hearthside", "--write-password", "encrypted-chat-folder", "kdewallet"],
                    [KQ, "--folder", "Other", "--read-password", "encrypted-chat-folder", "kdewallet"],
                    ["/usr/bin/cat", "/etc/passwd"], ["relative/kdialog", "--password", "x"]):
        argv = ["/usr/bin/gocryptfs", "-q", "-nosyslog", "-config", config,
                *[item for value in extpass for item in ("-extpass", value)], cipher, mountpoint]
        with pytest.raises(webdata.HelperError):
            vault._check_argv(argv, config=config)
    with pytest.raises(webdata.HelperError):
        vault._check_argv([*good[:5], "-config", config, *good[5:]], config=config)


# --- static rules -------------------------------------------------------------------------------


def _calls_in(tree, names):
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call) and (
        (isinstance(node.func, ast.Attribute) and node.func.attr in names)
        or (isinstance(node.func, ast.Name) and node.func.id in names))]


def test_walletkey_source_rules():
    code = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(code)
    # Standard library only.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] in sys.stdlib_module_names for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            assert (node.module or "").split(".")[0] in sys.stdlib_module_names
    for pattern in (r"\bshell\s*=", r"(?<![\w.])print\s*\(", r"\bcapture_output\b", r"\bcheck_output\b",
                    r"\bos\.system\b", r"\bos\.popen\b", r"\bgetoutput\b", r"\.read\(", r"\bos\.read\b",
                    r"\bcommunicate\b", r"\bsys\.std(out|err)\b", r"\bos\.p?readv\b",
                    r"\b(?:stdin|stdout|stderr)\s*=\s*-\s*1\b", r"\bos\.fdopen\b", r"(?<![\w.])open\s*\("):
        assert not re.search(pattern, code), pattern
    # subprocess.PIPE only inside _query (the qdbus6 answers).
    for function in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)):
        uses_pipe = any(isinstance(node, ast.Attribute) and node.attr == "PIPE" for node in ast.walk(function))
        assert uses_pipe == (function.name == "_query"), function.name
    assert code.count("PIPE") == 1


def test_vault_wallet_paths_never_read_or_capture():
    tree = ast.parse(VAULT_SOURCE.read_text(encoding="utf-8"))
    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    for name in ("add_key", "remove_key", "auto_unlock", "_unlock_with_wallet", "_mount", "_commit_slot", "_seal_new_slot"):
        assert not _calls_in(functions[name], {"read", "pread", "readline", "communicate", "check_output"}), name


@pytest.mark.parametrize("old,new", [
    ("            stdin=stdin,\n            stdout=stdout,\n", "            stdin=stdin,\n            stdout=subprocess.PIPE,\n"),
    ("    if code != 0:\n        _close(reader)", "    print(os.read(reader, 99))\n    if code != 0:\n        _close(reader)"),
    ("            stdin=stdin,\n            stdout=stdout,\n", "            stdin=stdin,\n            stdout=-1,\n"),
    ("    if code != 0:\n        _close(reader)",
     "    os.readv(reader, [bytearray(65)])\n    if code != 0:\n        _close(reader)"),
    ("    if code != 0:\n        _close(reader)",
     "    os.preadv(reader, [bytearray(65)], 0)\n    if code != 0:\n        _close(reader)"),
    ("    if code != 0:\n        _close(reader)",
     "    os.fdopen(reader).readline()\n    if code != 0:\n        _close(reader)"),
])
def test_proof_walletkey_source_rules_catch(old, new, monkeypatch, tmp_path):
    code = SOURCE.read_text(encoding="utf-8")
    assert old in code
    mutated = tmp_path / "walletkey.py"
    mutated.write_text(code.replace(old, new, 1))
    monkeypatch.setattr(sys.modules[__name__], "SOURCE", mutated)
    with pytest.raises(AssertionError):
        test_walletkey_source_rules()


# --- re-setup is staged (review S4), removal without openssl (N1), N2 ---------------------------

NEW_KEY = KEY + ".new"


def _slot_snapshot(stubs):
    return slot(stubs).read_bytes(), os.lstat(slot(stubs)).st_ino, wallet_state(stubs)[KEY]


@pytest.mark.parametrize(
    ("settings", "error", "staged_left"),
    [
        ({"STUB_KDIALOG_EXIT": 1}, "cancelled", False),
        ({"STUB_PASSWD_EXIT": 12}, "wrong-passphrase", False),
        ({"STUB_PASSWD_EXIT": 24}, "wallet-write-failed", False),
        ({"STUB_OPENSSL_EXIT": 1}, "wallet-write-failed", False),
        ({"STUB_KWALLET_WRITE_FAIL_ENTRY": "encrypted-chat-folder.new"}, "wallet-failed", False),
        ({"STUB_KWALLET_READ_FAIL_ENTRY": "encrypted-chat-folder.new"}, "wallet-failed", True),
        # The swap itself fails: the new slot goes back, the old one is restored.
        ({"STUB_KWALLET_WRITE_FAIL_ENTRY": "encrypted-chat-folder"}, "wallet-failed", True),
    ],
)
def test_a_failed_re_setup_leaves_the_working_slot(stubs, capsys, settings, error, staged_left):
    enrolled(stubs, capsys)
    before = _slot_snapshot(stubs)
    stubs.env(**settings)
    assert reply("add-key", capsys) == {"ok": False, "error": error}
    assert _slot_snapshot(stubs) == before
    assert sorted(os.listdir(keys_dir(stubs))) == ["wallet.conf"]
    assert (NEW_KEY in wallet_state(stubs)) is staged_left
    for name in settings:
        stubs.monkeypatch.delenv(name)
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "set-up"}
    assert unlock_wallet(capsys) == {"ok": True}
    if staged_left:
        # The next removal also clears the staging entry.
        assert reply("lock", capsys) == {"ok": True}
        assert reply("remove-key", capsys) == {"ok": True}
        assert wallet_state(stubs) == {}


def test_a_failed_first_set_up_leaves_no_slot(stubs, capsys):
    stubs.make_locked()
    stubs.env(STUB_KWALLET_WRITE_FAIL_ENTRY="encrypted-chat-folder")
    assert reply("add-key", capsys) == {"ok": False, "error": "wallet-failed"}
    assert os.listdir(keys_dir(stubs)) == []
    assert KEY not in wallet_state(stubs)
    assert reply("status", capsys)["wallet"] == "off"


def test_a_successful_re_setup_replaces_slot_and_entry(stubs, capsys):
    enrolled(stubs, capsys)
    before = _slot_snapshot(stubs)
    (keys_dir(stubs) / "wallet.conf.old").write_text("left by an interrupted swap")
    assert reply("add-key", capsys) == {"ok": True}
    after = _slot_snapshot(stubs)
    assert after[1] != before[1] and after[2] != before[2]
    assert sorted(os.listdir(keys_dir(stubs))) == ["wallet.conf"]
    assert NEW_KEY not in wallet_state(stubs)
    assert unlock_wallet(capsys) == {"ok": True}


def test_openssl_failing_after_kwallet_query_stored_removes_the_empty_entry(stubs, capsys):
    stubs.make_locked()
    stubs.env(STUB_OPENSSL_EXIT=1)
    assert reply("add-key", capsys) == {"ok": False, "error": "wallet-write-failed"}
    (write,) = [call for call in stubs.calls("kwallet-query") if "--write-password" in call["argv"]]
    assert write["sha"] == hashlib.sha256(b"").hexdigest()  # kwallet-query stored an empty value (W1)...
    assert wallet_state(stubs) == {}  # ...which is deleted again.
    removes = [call["argv"] for call in stubs.calls("qdbus6") if call["argv"][2].endswith("removeEntry")]
    assert [argv[5] for argv in removes] == ["encrypted-chat-folder.new"]


@pytest.mark.parametrize("command", ["remove-key", "destroy", "purge"])
def test_every_removal_clears_a_leftover_staging_entry(stubs, capsys, monkeypatch, tmp_path, command):
    enrolled(stubs, capsys)
    state = wallet_state(stubs)
    state[NEW_KEY] = "0" * 64
    stubs.wallet.write_text(json.dumps(state))
    monkeypatch.setattr(vault, "DEFAULT_RUNTIME", str(tmp_path / "none-{uid}"))
    if command == "purge":
        assert cli.main(["--web-data", "purge"]) == 0
        assert capsys.readouterr().out == '{"ok":true,"removed":["vault","vault-keys","wallet-entry"]}\n'
    else:
        assert reply(command, capsys) == {"ok": True}
    assert wallet_state(stubs) == {}


def test_purge_without_a_slot_leaves_a_lone_staging_entry(stubs, capsys, monkeypatch, tmp_path):
    # The entry may belong to another data folder: without a slot here it is not ours.
    stubs.wallet.write_text(json.dumps({NEW_KEY: "0" * 64}))
    monkeypatch.setattr(vault, "DEFAULT_RUNTIME", str(tmp_path / "none-{uid}"))
    assert cli.main(["--web-data", "purge"]) == 0
    assert capsys.readouterr().out == '{"ok":true,"removed":[]}\n'
    assert wallet_state(stubs) == {NEW_KEY: "0" * 64}
    assert tools_called(stubs, without=()) == []


def _stray_keys_dir(stubs, tmp_path, kind):
    """vault-keys of this data folder without a wallet slot of ours."""
    keys = keys_dir(stubs)
    keys.mkdir(parents=True)
    if kind == "unrelated-file":
        (keys / "notes.txt").write_text("x")
    elif kind == "symlinked-slot":
        target = tmp_path / "elsewhere.conf"
        target.write_text("{}")
        (keys / "wallet.conf").symlink_to(target)
    elif kind == "directory-slot":
        (keys / "wallet.conf").mkdir()


STRAY = ("empty", "unrelated-file", "symlinked-slot", "directory-slot")


@pytest.mark.parametrize("kind", STRAY)
@pytest.mark.parametrize("command", ["destroy", "purge"])
def test_stray_vault_keys_leave_the_wallet_untouched(stubs, capsys, monkeypatch, tmp_path, kind, command):
    stubs.make_locked()
    stubs.wallet.write_text(json.dumps({KEY: "1" * 64, NEW_KEY: "0" * 64}))
    _stray_keys_dir(stubs, tmp_path, kind)
    stubs.log.write_text("")
    forgot = []
    monkeypatch.setattr(walletkey, "forget", lambda tools: forgot.append(tools) or True)
    monkeypatch.setattr(vault, "DEFAULT_RUNTIME", str(tmp_path / "none-{uid}"))
    if command == "purge":
        assert cli.main(["--web-data", "purge"]) == 0
        assert capsys.readouterr().out == '{"ok":true,"removed":["vault","vault-keys"]}\n'
    else:
        assert reply(command, capsys) == {"ok": True}
    assert forgot == []
    assert not keys_dir(stubs).exists() and not stubs.cipher.exists()
    assert wallet_state(stubs) == {KEY: "1" * 64, NEW_KEY: "0" * 64}
    assert tools_called(stubs, without=()) == []


@pytest.mark.parametrize("name", ["wallet.conf", "wallet.conf.old", "wallet.conf.new"])
@pytest.mark.parametrize("command", ["destroy", "purge"])
def test_a_slot_of_this_folder_makes_destroy_and_purge_forget(stubs, capsys, monkeypatch, tmp_path, name, command):
    stubs.make_locked()
    keys_dir(stubs).mkdir(parents=True)
    (keys_dir(stubs) / name).write_text("{}")
    (keys_dir(stubs) / name).chmod(0o400)
    forgot = []
    monkeypatch.setattr(walletkey, "forget", lambda tools: forgot.append(tools) or True)
    monkeypatch.setattr(vault, "DEFAULT_RUNTIME", str(tmp_path / "none-{uid}"))
    if command == "purge":
        assert cli.main(["--web-data", "purge"]) == 0
        assert capsys.readouterr().out == '{"ok":true,"removed":["vault","vault-keys","wallet-entry"]}\n'
    else:
        assert reply(command, capsys) == {"ok": True}
    assert len(forgot) == 1
    assert not keys_dir(stubs).exists()


def test_destroy_without_any_vault_keys_leaves_the_wallet_untouched(stubs, capsys, monkeypatch):
    stubs.make_locked()
    stubs.wallet.write_text(json.dumps({KEY: "1" * 64}))
    stubs.log.write_text("")
    monkeypatch.setattr(walletkey, "forget", lambda tools: pytest.fail("wallet asked"))
    assert reply("destroy", capsys) == {"ok": True}
    assert wallet_state(stubs) == {KEY: "1" * 64}
    assert tools_called(stubs, without=()) == []


@pytest.mark.parametrize("command", ["destroy", "purge"])
def test_destroy_and_purge_need_no_openssl(stubs, capsys, monkeypatch, tmp_path, command):
    enrolled(stubs, capsys)
    stubs.remove("openssl")
    monkeypatch.setattr(vault, "DEFAULT_RUNTIME", str(tmp_path / "none-{uid}"))
    if command == "purge":
        assert cli.main(["--web-data", "purge"]) == 0
        assert capsys.readouterr().out == '{"ok":true,"removed":["vault","vault-keys","wallet-entry"]}\n'
    else:
        assert reply(command, capsys) == {"ok": True}
    assert wallet_state(stubs) == {}
    assert [call for call in stubs.calls("kwallet-query") if "--write-password" in call["argv"]] == []


def test_staging_entry_never_reaches_gocryptfs_as_extpass():
    # The mount's extpass reads only the real entry; the staging one is never mounted with.
    staged = walletkey.read_argv(KQ, "kdewallet", walletkey.ENTRY_NEW)
    walletkey.check_argv(staged)
    assert not walletkey.is_read_argv(staged)
    cipher, mountpoint, config = "/d/hearthside/vault", "/r/hearthside/vault", "/d/hearthside/vault-keys/wallet.conf"
    argv = ["/usr/bin/gocryptfs", "-q", "-nosyslog", "-config", config,
            *[item for value in staged for item in ("-extpass", value)], cipher, mountpoint]
    with pytest.raises(webdata.HelperError):
        vault._check_argv(argv, config=config)
