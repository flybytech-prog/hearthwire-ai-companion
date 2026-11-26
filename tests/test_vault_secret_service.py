"""Task 014: the encrypted Chat folder's Secret Service unlock in app mode (vault.py + secretkey.py).

Reuses test_vault's stubs (gocryptfs, fusermount3, the askpass of
test_vault_app_mode) and test_secretkey's secret-tool, busctl and openssl
stubs: a JSON "keyring" of dummy values under tmp_path, the measured answer
formats of R0/R0b, logs with sha256 hashes and lengths only. The stub
gocryptfs keeps the hash of the key it got on ``-passwd -config`` stdin in the
slot copy and, when mounting with ``-config``, compares it with the hash of
its extpass output (one trailing LF trimmed), like the measured gocryptfs: 9
when the extpass fails, 12 when the key does not fit. No real keyring, bus or
prompt is ever used, and the host's keyring files are never read.
"""

import ast
import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from hearthwire.core import frontend, secretkey, vault
from test_frontend import mutant
from test_secretkey import ENCRYPTED, ReadSpy, install_keyring_stubs, keyrings
from test_vault import extpass_values, reply
from test_vault_app_mode import AppStubs, _copy, mutants
from test_vault_signals import Case, stop_problems

VAULT_PY = Path(vault.__file__)
ITEM, NEW = secretkey.ITEM, secretkey.ITEM_NEW
SET_UP = {"ok": True, "state": "locked", "wallet": "set-up", "keyring": "secret-service"}


class KeyringStubs(AppStubs):
    def __init__(self, root, monkeypatch, runtime):
        super().__init__(root, monkeypatch, runtime)
        install_keyring_stubs(self.bin)
        self.keyring = root / "keyring.json"
        monkeypatch.setenv("STUB_KEYRING", str(self.keyring))
        Path(os.path.realpath(self.data)).mkdir(parents=True, exist_ok=True)

    @property
    def keys(self):
        return Path(os.path.realpath(self.data)) / "hearthwire" / "vault-keys"

    @property
    def slot(self):
        return self.keys / "secret-service.conf"

    def items(self):
        return json.loads(self.keyring.read_text()) if self.keyring.exists() else {}

    def storage(self, kind):
        """The keyring files gnome-keyring would have under XDG_DATA_HOME."""
        home = Path(os.path.realpath(self.data))
        if kind == "plain":
            keyrings(home)
        elif kind == "encrypted":
            keyrings(home, default="login\n", name="login", content=ENCRYPTED)

    def tools(self, *names):
        return [call["tool"] for call in self.calls() if not names or call["tool"] in names]

    def unset(self, *names):
        for name in names:
            self.monkeypatch.delenv(name, raising=False)


@pytest.fixture
def stubs(tmp_path, monkeypatch, _private_runtime_dir):
    return KeyringStubs(tmp_path, monkeypatch, _private_runtime_dir)


def enrolled(stubs, capsys):
    stubs.make_locked()
    assert reply("add-key", capsys) == {"ok": True}
    stubs.log.write_text("")


def secret_calls(stubs):
    return [call for call in stubs.calls() if call["tool"] in ("secret-tool", "openssl")]


def step(call):
    if call["tool"] == "secret-tool":
        return f"{call['argv'][0]} {call['item']}"
    return call["tool"]


def snapshot(stubs):
    return stubs.slot.read_bytes(), os.lstat(stubs.slot).st_ino, stubs.items()[ITEM]


# --- status ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["plain", "encrypted", "unknown"])
def test_app_status_reports_the_keyring_and_its_storage(stubs, capsys, kind):
    stubs.make_locked()
    stubs.storage(kind)
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "off",
                                       "keyring": "secret-service", "keyringStorage": kind}
    # Only the Locked query ran: no lookup, no prompt.
    assert [call["argv"][2] for call in stubs.calls()] == ["get-property"]


def test_app_status_set_up_after_add_key_and_while_unlocked(stubs, capsys):
    enrolled(stubs, capsys)
    stubs.storage("plain")
    assert reply("status", capsys) == {**SET_UP, "keyringStorage": "plain"}
    assert reply("unlock", capsys, "--method", "wallet") == {"ok": True}
    assert reply("status", capsys) == {**SET_UP, "state": "unlocked", "keyringStorage": "plain"}


@pytest.mark.parametrize(("removed", "settings", "wallet", "missing"), [
    (("secret-tool",), {}, "unavailable", ["secret-tool"]),
    (("busctl",), {}, "unavailable", None),  # busctl is never listed (systemd).
    (("openssl",), {}, "off", ["openssl"]),  # Only set-up and removal need it.
    (("secret-tool", "openssl"), {}, "unavailable", ["secret-tool", "openssl"]),
    ((), {"STUB_SS_LOCKED": "fail"}, "unavailable", None),  # No default collection (R0 S4).
    ((), {"STUB_SS_BUS": "bad"}, "unavailable", None),  # No bus (R0b).
    ((), {"STUB_SS_LOCKED_RAW": "s false"}, "unavailable", None),
    ((), {"STUB_SS_LOCKED": "true"}, "off", None),
])
def test_app_status_wallet_and_missing(stubs, capsys, removed, settings, wallet, missing):
    stubs.make_locked()
    for name in removed:
        stubs.remove(name)
    stubs.env(**settings)
    expected = {"ok": True, "state": "locked", "wallet": wallet, "keyring": "secret-service",
                "keyringStorage": "unknown", **({"missing": missing} if missing else {})}
    assert reply("status", capsys) == expected
    if "secret-tool" in removed or "busctl" in removed:
        assert stubs.calls() == []


def test_app_status_without_a_folder_has_no_keyring_fields(stubs, capsys):
    assert reply("status", capsys) == {"ok": True, "state": "absent"}
    stubs.remove("gocryptfs")
    assert reply("status", capsys) == {"ok": True, "state": "unavailable", "missing": ["gocryptfs"]}
    assert stubs.calls() == []


def test_plasma_status_never_has_keyring_fields_and_runs_no_secret_service_tool(stubs, capsys):
    stubs.plasma()
    stubs.make_locked()
    stubs.storage("plain")
    stubs.slot.parent.mkdir(parents=True, mode=0o700)
    stubs.slot.write_text("{}")
    stubs.slot.chmod(0o400)
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "off"}
    assert stubs.tools("secret-tool", "busctl") == []


# --- set-up (add-key) -----------------------------------------------------------------------------------


def test_add_key_moves_the_key_fd_to_fd_and_unlock_uses_it(stubs, capsys):
    stubs.make_locked()
    conf = (stubs.cipher / "gocryptfs.conf").read_bytes()
    assert reply("add-key", capsys) == {"ok": True}
    calls = stubs.calls()
    assert [step(call) for call in calls if call["tool"] in ("secret-tool", "openssl")] == [
        "openssl", f"store {NEW}", f"lookup {NEW}", f"lookup {NEW}", f"store {ITEM}",
        "openssl", f"store {NEW}", f"clear {NEW}"]
    keygen, stage, read, copy_read, copy_write, *_ = secret_calls(stubs)
    (passwd,) = [call for call in calls if call["tool"] == "gocryptfs" and "-passwd" in call["argv"]]
    # Pipes only, never a file or a terminal; stderr always /dev/null.
    assert keygen["fds"][0] == "/dev/null" and keygen["fds"][1].startswith("pipe:")
    for call in (stage, copy_write):
        assert call["fds"][0].startswith("pipe:") and call["fds"][1:] == ["/dev/null"] * 2
    for call in (read, copy_read):
        assert call["fds"][0] == "/dev/null" and call["fds"][1].startswith("pipe:") and call["fds"][2] == "/dev/null"
    assert passwd["fds"][0].startswith("pipe:") and passwd["fds"][1:] == ["/dev/null"] * 2
    # Stored without the LF (R0b), 64 hex digits; the same key all the way.
    stored = stubs.items()[ITEM]
    assert len(stored) == 64 and all(c in "0123456789abcdef" for c in stored)
    assert [(call["length"], call["lf"]) for call in (stage, copy_write)] == [(64, False), (64, False)]
    digest = hashlib.sha256(stored.encode()).hexdigest()
    assert stage["sha"] == read["sha"] == passwd["stdin_sha"] == copy_read["sha"] == copy_write["sha"] == digest
    assert keygen["length"] == 65 and NEW not in stubs.items()
    # The current passphrase comes from the askpass; -config is the copy.
    assert extpass_values(passwd["argv"])[0] == str(stubs.askpass)
    assert passwd["argv"][passwd["argv"].index("-config") + 1] == str(stubs.keys / "secret-service.conf.new")
    assert sorted(os.listdir(stubs.keys)) == ["secret-service.conf"]
    assert stat.S_IMODE(os.lstat(stubs.slot).st_mode) == 0o400
    assert stat.S_IMODE(os.lstat(stubs.keys).st_mode) == 0o700
    assert (stubs.cipher / "gocryptfs.conf").read_bytes() == conf
    assert stubs.tools("kdialog", "kwallet-query", "qdbus6") == []

    stubs.log.write_text("")
    assert reply("unlock", capsys, "--method", "wallet") == {"ok": True}
    (mount,) = stubs.calls("gocryptfs")
    assert mount["argv"][:4] == ["-q", "-nosyslog", "-config", str(stubs.slot)]
    assert extpass_values(mount["argv"]) == [str(stubs.bin / "secret-tool"), "lookup", "application", "hearthwire",
                                             "item", ITEM]
    assert mount["fds"] == ["/dev/null"] * 3 and mount["extpass_sha"] == digest
    assert stubs.tools("hearthwire-askpass", "kdialog", "kwallet-query", "qdbus6") == []


def test_add_key_works_while_unlocked_and_replaces_the_key(stubs, capsys):
    enrolled(stubs, capsys)
    first = stubs.items()[ITEM]
    assert reply("unlock", capsys) == {"ok": True}
    assert reply("add-key", capsys) == {"ok": True}
    assert stubs.items()[ITEM] != first and sorted(stubs.items()) == [ITEM]
    assert reply("lock", capsys) == {"ok": True}
    assert reply("unlock", capsys, "--method", "wallet") == {"ok": True}


@pytest.mark.parametrize(("settings", "error", "staged_left"), [
    ({"STUB_PASSWD_EXIT": 12}, "wrong-passphrase", False),
    ({"STUB_KDIALOG_EXIT": 1}, "cancelled", False),
    ({"STUB_PASSWD_EXIT": 24}, "wallet-write-failed", False),
    ({"STUB_SS_STORE_FAIL_ITEM": NEW}, "wallet-write-failed", False),
    ({"STUB_OPENSSL_EXIT": 1}, "wallet-write-failed", False),
    # A lookup that failed is not tried again (it may prompt): the next set-up or removal clears it.
    ({"STUB_SS_LOOKUP_FAIL_ITEM": NEW}, "wallet-failed", True),
    ({"STUB_SS_LOCKED": "fail"}, "wallet-disabled", False),
    ({"STUB_SS_BUS": "bad"}, "wallet-disabled", False),
])
def test_a_failed_first_set_up_leaves_no_slot(stubs, capsys, settings, error, staged_left):
    stubs.make_locked()
    stubs.env(**settings)
    assert reply("add-key", capsys) == {"ok": False, "error": error}
    assert not stubs.keys.exists() or os.listdir(stubs.keys) == []
    assert ITEM not in stubs.items()
    assert (NEW in stubs.items()) is staged_left
    if staged_left:
        stubs.unset(*settings)
        assert reply("remove-key", capsys) == {"ok": True}
        assert stubs.items() == {}


@pytest.mark.parametrize("output", ["empty", "short", "long"])
def test_set_up_never_stores_or_uses_an_empty_or_odd_key(stubs, capsys, output):
    stubs.make_locked()
    stubs.env(STUB_OPENSSL_OUTPUT=output)
    assert reply("add-key", capsys) == {"ok": False, "error": "wallet-write-failed"}
    assert stubs.tools("secret-tool") == [] and stubs.calls("gocryptfs") == []
    assert stubs.items() == {} and os.listdir(stubs.keys) == []


def test_an_empty_staged_key_never_reaches_gocryptfs(stubs, capsys):
    stubs.make_locked()
    stubs.env(STUB_SS_LOOKUP_EMPTY=NEW)
    assert reply("add-key", capsys) == {"ok": False, "error": "wallet-failed"}
    assert [call for call in stubs.calls("gocryptfs") if "-passwd" in call["argv"]] == []
    assert os.listdir(stubs.keys) == []


@pytest.mark.parametrize(("settings", "error", "staged_left"), [
    ({"STUB_KDIALOG_EXIT": 1}, "cancelled", False),
    ({"STUB_PASSWD_EXIT": 12}, "wrong-passphrase", False),
    ({"STUB_PASSWD_EXIT": 24}, "wallet-write-failed", False),
    ({"STUB_OPENSSL_EXIT": 1}, "wallet-write-failed", False),
    ({"STUB_SS_STORE_FAIL_ITEM": NEW}, "wallet-write-failed", False),
    ({"STUB_SS_LOOKUP_FAIL_ITEM": NEW}, "wallet-failed", True),
    # The swap itself fails: the new slot goes back, the old one is restored.
    ({"STUB_SS_STORE_FAIL_ITEM": ITEM}, "wallet-write-failed", False),
])
def test_a_failed_re_setup_leaves_the_working_slot_and_item(stubs, capsys, settings, error, staged_left):
    enrolled(stubs, capsys)
    before = snapshot(stubs)
    stubs.env(**settings)
    assert reply("add-key", capsys) == {"ok": False, "error": error}
    assert snapshot(stubs) == before
    assert sorted(os.listdir(stubs.keys)) == ["secret-service.conf"]
    assert (NEW in stubs.items()) is staged_left
    stubs.unset(*settings)
    assert reply("status", capsys)["wallet"] == "set-up"
    assert reply("unlock", capsys, "--method", "wallet") == {"ok": True}


ROLLBACK_MUTATIONS = {
    "no rollback": ("        # Roll back: the old slot and item keep working.\n        try:\n"
                    "            _rename(keys, names.file, names.new)\n            if had_old:\n"
                    "                _rename(keys, names.old, names.file)\n",
                    "        # Roll back: the old slot and item keep working.\n        try:\n            pass\n"
                    "            if False:\n                pass\n"),
    "the old slot not restored": ("            if had_old:\n                _rename(keys, names.old, names.file)\n",
                                  "            if False:\n                pass\n"),
}


def rollback_problems(module, stubs, capsys):
    """A re-setup whose copy into the real item fails leaves the old slot and item working."""
    enrolled(stubs, capsys)
    before = snapshot(stubs)
    stubs.env(STUB_SS_STORE_FAIL_ITEM=ITEM)
    problems = []
    result = module.run("add-key", method="wallet")
    if result != {"ok": False, "error": "wallet-write-failed"}:
        problems.append(f"the reply is {result}")
    stubs.unset("STUB_SS_STORE_FAIL_ITEM")
    if not stubs.slot.exists() or snapshot(stubs) != before:
        problems.append("the old slot or item changed")
    if module.run("unlock", method="wallet") != {"ok": True}:
        problems.append("the old slot no longer opens the folder")
    return problems


def test_the_rollback_rule_holds(stubs, capsys):
    assert rollback_problems(vault, stubs, capsys) == []


@pytest.mark.parametrize("name", sorted(ROLLBACK_MUTATIONS))
def test_proof_the_rollback_rule_catches(stubs, capsys, name):
    assert rollback_problems(_copy(mutant(vault, *ROLLBACK_MUTATIONS[name])), stubs, capsys)


def test_add_key_refuses_without_a_folder_or_tools(stubs, capsys):
    assert reply("add-key", capsys) == {"ok": False, "error": "absent"}
    stubs.make_locked()
    for name in ("openssl", "secret-tool"):
        stubs.remove(name)
        assert reply("add-key", capsys) == {"ok": False, "error": "missing-tool"}
    assert stubs.calls() == []


# --- removal ----------------------------------------------------------------------------------------------


def test_remove_key_clears_its_slot_and_items_and_keeps_the_widgets_slot(stubs, capsys):
    enrolled(stubs, capsys)
    widget = stubs.wallet_slot()
    before = widget.read_bytes()
    (stubs.keys / "secret-service.conf.old").write_text("{}")
    items = stubs.items()
    items[NEW] = "9" * 64  # Left by an interrupted set-up.
    stubs.keyring.write_text(json.dumps(items))
    assert reply("remove-key", capsys) == {"ok": True}
    assert sorted(os.listdir(stubs.keys)) == ["wallet.conf"] and widget.read_bytes() == before
    assert stubs.items() == {}
    # Each item is overwritten with a fresh random value before it is cleared.
    assert [step(call) for call in secret_calls(stubs)] == [
        "openssl", f"store {ITEM}", f"clear {ITEM}", "openssl", f"store {NEW}", f"clear {NEW}"]
    assert reply("status", capsys)["wallet"] == "off"
    assert reply("remove-key", capsys) == {"ok": True}  # Nothing left: still fine.


def test_remove_key_reports_an_item_it_could_not_clear(stubs, capsys):
    enrolled(stubs, capsys)
    stubs.env(STUB_SS_CLEAR_KEEPS=1)
    assert reply("remove-key", capsys) == {"ok": False, "error": "wallet-failed"}
    assert not stubs.slot.exists()  # The slot goes first in every case.
    stubs.env(STUB_SS_CLEAR_KEEPS="", STUB_SS_LOCKED="fail")
    assert reply("remove-key", capsys) == {"ok": False, "error": "wallet-disabled"}


def test_remove_key_without_openssl_skips_the_overwrite(stubs, capsys):
    enrolled(stubs, capsys)
    stubs.remove("openssl")
    assert reply("remove-key", capsys) == {"ok": True}
    assert [step(call) for call in secret_calls(stubs)] == [f"clear {ITEM}"] and stubs.items() == {}


# --- unlock and auto-unlock --------------------------------------------------------------------------------


@pytest.mark.parametrize(("locked", "kind", "result"), [
    ("false", "encrypted", {"ok": True}),
    ("false", "unknown", {"ok": True}),
    ("false", "plain", {"ok": True}),
    # A plain keyring is unlocked silently by the lookup (R0 S5, R0b): no prompt, so it goes on.
    ("true", "plain", {"ok": True}),
    ("true", "encrypted", {"ok": False, "error": "wallet-closed"}),
    ("true", "unknown", {"ok": False, "error": "wallet-closed"}),
    ("fail", "plain", {"ok": False, "error": "wallet-disabled"}),
])
def test_auto_unlock_never_prompts_at_app_start(stubs, capsys, locked, kind, result):
    enrolled(stubs, capsys)
    stubs.storage(kind)
    stubs.env(STUB_SS_LOCKED=locked)
    assert reply("auto-unlock", capsys) == result
    if result["ok"]:
        assert stubs.mounted() and [step(call) for call in stubs.calls("secret-tool")] == [f"lookup {ITEM}"]
    else:
        # Nothing but the Locked query ran: no lookup, no gocryptfs, so no prompt.
        assert [(call["tool"], call["argv"][2]) for call in stubs.calls()] == [("busctl", "get-property")]
        assert not stubs.mounted()


def auto_unlock_problems(module, stubs, capsys):
    enrolled(stubs, capsys)
    problems = []
    # (Locked, storage, expected error or None, extra stub settings, busctl methods that may run)
    rows = (("true", "encrypted", "wallet-closed", {}, ["get-property"]),
            ("true", "unknown", "wallet-closed", {}, ["get-property"]),
            ("true", "plain", None, {}, None),
            # The item sits in another collection (encrypted, or another provider's): never looked up.
            ("true", "plain", "wallet-closed", {"STUB_SS_COLLECTION": "/org/freedesktop/secrets/collection/other"},
             ["get-property", "call"]))
    for locked, kind, expected, extra, methods in rows:
        stubs.log.write_text("")
        home = Path(os.path.realpath(stubs.data)) / "keyrings"
        if home.exists():
            for entry in home.iterdir():
                entry.unlink()
            home.rmdir()
        stubs.storage(kind)
        stubs.unset("STUB_SS_COLLECTION")
        stubs.env(STUB_SS_LOCKED=locked, **extra)
        result = module.run("auto-unlock")
        if expected is None:
            if result != {"ok": True}:
                problems.append(f"a locked plain keyring gives {result}")
            module.run("lock")
            continue
        if result != {"ok": False, "error": expected}:
            problems.append(f"{kind} {extra}: {result}")
        ran = [(call["tool"], call["argv"][2]) for call in stubs.calls()]
        if ran != [("busctl", method) for method in methods]:
            problems.append(f"{kind} {extra}: ran {[step(call) for call in stubs.calls()]}")
    stubs.unset("STUB_SS_COLLECTION")
    return problems


def test_the_auto_unlock_rule_holds(stubs, capsys):
    assert auto_unlock_problems(vault, stubs, capsys) == []


SHORTCUT = '''    if shortcut:
        name, storage = secretkey.keyring_default(environ)
        if storage != "plain":
'''
AUTO_UNLOCK_MUTATIONS = {
    "any storage goes on": (SHORTCUT, SHORTCUT.replace('storage != "plain"', 'storage == "x"')),
    "unknown taken for plain": (SHORTCUT, SHORTCUT.replace('storage != "plain"', 'storage not in ("plain", "unknown")')),
    "the lock ignored": ("    shortcut = automatic and locked is not False\n", "    shortcut = automatic and locked is None\n"),
    "auto-unlock as a manual one": ("    return _keyring_unlock(ctx, environ, automatic=True)\n",
                                    "    return _keyring_unlock(ctx, environ)\n"),
    "plain never goes on": (SHORTCUT, SHORTCUT.replace('storage != "plain"', "True")),
    "the item asked first": ("    shortcut = automatic and locked is not False\n",
                             "    secretkey.item_paths(ctx.keyring_tools[secretkey.BUSCTL])\n"
                             "    shortcut = automatic and locked is not False\n"),
    "another collection goes on": ("        if not all(path.startswith(prefix) for path in paths):\n",
                                   "        if False:\n"),
    "any collection prefix": ("        prefix = secretkey.collection_path(name or \"\") + \"/\"\n",
                              "        prefix = \"/org/freedesktop/secrets/collection/\"\n"),
}


@pytest.mark.parametrize("name", sorted(AUTO_UNLOCK_MUTATIONS))
def test_proof_the_auto_unlock_rule_catches(stubs, capsys, name):
    assert auto_unlock_problems(_copy(mutant(vault, *AUTO_UNLOCK_MUTATIONS[name])), stubs, capsys)


def blocked_auto_unlock_problems(module, stubs, capsys, tmp_path, monkeypatch):
    """A lookup that waits (a prompt, a stuck provider) at app start: wallet-closed within the short bound."""
    import time
    enrolled(stubs, capsys)
    stubs.storage("plain")
    pids = tmp_path / "pids"
    pids.mkdir()
    stubs.env(STUB_SS_LOCKED="true", STUB_SS_BLOCK=f"lookup:{ITEM}", STUB_SS_SLEEP=60, STUB_PIDS=pids)
    monkeypatch.setattr(secretkey, "AUTO_LOOKUP_TIMEOUT", 1.0)
    problems = []
    started = time.monotonic()
    result = module.run("auto-unlock")
    if result != {"ok": False, "error": "wallet-closed"}:
        problems.append(f"the reply is {result}")
    if time.monotonic() - started > secretkey.AUTO_LOOKUP_TIMEOUT + 2.5:
        problems.append("it waited past the short bound")
    if stubs.mounted():
        problems.append("something is mounted")
    for entry in pids.iterdir():
        try:
            os.kill(int(entry.name.rsplit("-", 1)[1]), 0)
            problems.append("secret-tool is still running")
        except ProcessLookupError:
            pass
    return problems


def test_a_blocked_lookup_at_app_start_is_wallet_closed_within_the_short_bound(stubs, capsys, tmp_path, monkeypatch):
    assert blocked_auto_unlock_problems(vault, stubs, capsys, tmp_path, monkeypatch) == []


@pytest.mark.parametrize("name", ["the long bound", "wallet-failed"])
def test_proof_the_short_bound_rule_catches(stubs, capsys, tmp_path, monkeypatch, name):
    old = ('timeout=secretkey.AUTO_LOOKUP_TIMEOUT if automatic else secretkey.PROMPT_TIMEOUT,',
           'timeout=secretkey.PROMPT_TIMEOUT if automatic else secretkey.PROMPT_TIMEOUT,') if name == "the long bound" \
        else ('timeout_error="wallet-closed" if automatic else "wallet-failed"', 'timeout_error="wallet-failed"')
    copy = _copy(mutant(vault, *old))
    if name == "the long bound":
        # Without the bound the 120 s wait would end this test: end the wait after 5 s instead.
        monkeypatch.setattr(secretkey, "PROMPT_TIMEOUT", 5.0)
    assert blocked_auto_unlock_problems(copy, stubs, capsys, tmp_path, monkeypatch)


def test_a_manual_unlock_keeps_the_long_bound(stubs, capsys, monkeypatch):
    """The short bound is for app start only: a manual unlock may wait on a prompt."""
    enrolled(stubs, capsys)
    stubs.env(STUB_SS_BLOCK=f"lookup:{ITEM}", STUB_SS_SLEEP=2)
    monkeypatch.setattr(secretkey, "AUTO_LOOKUP_TIMEOUT", 0.5)
    assert reply("unlock", capsys, "--method", "wallet") == {"ok": True}
    assert stubs.mounted()


def test_a_manual_unlock_may_prompt(stubs, capsys):
    """Unlock --method wallet goes on while locked: the gcr prompt is the user's choice then."""
    enrolled(stubs, capsys)
    stubs.storage("encrypted")
    stubs.env(STUB_SS_LOCKED="true")
    assert reply("unlock", capsys, "--method", "wallet") == {"ok": True}
    assert [step(call) for call in stubs.calls("secret-tool")] == [f"lookup {ITEM}"]


@pytest.mark.parametrize(("settings", "error"), [
    ({"STUB_SS_LOOKUP_FAIL_ITEM": ITEM}, "wallet-failed"),  # Cancelled prompt: exit 1, empty (R0 S6) -> 9.
    ({"STUB_SS_SEARCH": "fail"}, "wallet-failed"),
    ({"STUB_SS_SEARCH": "junk"}, "wallet-failed"),
    ({"STUB_SS_LOCKED": "fail"}, "wallet-disabled"),
    ({"STUB_SS_BUS": "bad"}, "wallet-disabled"),
])
def test_unlock_failures(stubs, capsys, settings, error):
    enrolled(stubs, capsys)
    stubs.env(**settings)
    assert reply("unlock", capsys, "--method", "wallet") == {"ok": False, "error": error}
    assert not stubs.mounted()
    if stubs.mountpoint.exists():
        assert stubs.mountpoint_mode() == vault.SEALED_MODE


def test_unlock_without_a_slot_is_not_set_up(stubs, capsys):
    stubs.make_locked()
    assert reply("unlock", capsys, "--method", "wallet") == {"ok": False, "error": "not-set-up"}
    assert reply("auto-unlock", capsys) == {"ok": False, "error": "not-set-up"}
    assert stubs.tools("secret-tool", "gocryptfs") == []


def test_unlock_needs_the_item_and_its_key(stubs, capsys):
    enrolled(stubs, capsys)
    stubs.keyring.write_text("{}")
    assert reply("unlock", capsys, "--method", "wallet") == {"ok": False, "error": "not-set-up"}
    assert stubs.calls("gocryptfs") == []
    stubs.keyring.write_text(json.dumps({ITEM: "0" * 64}))  # Someone else's value: it does not fit.
    assert reply("unlock", capsys, "--method", "wallet") == {"ok": False, "error": "wallet-mismatch"}
    assert not stubs.mounted()


@pytest.mark.parametrize("variant", ["link", "mode", "directory"])
def test_an_odd_slot_is_not_set_up(stubs, capsys, tmp_path, variant):
    enrolled(stubs, capsys)
    if variant == "link":
        target = tmp_path / "elsewhere.conf"
        target.write_bytes(stubs.slot.read_bytes())
        stubs.slot.unlink()
        stubs.slot.symlink_to(target)
    elif variant == "mode":
        stubs.slot.chmod(0o600)
    else:
        stubs.slot.unlink()
        stubs.slot.mkdir()
    assert reply("status", capsys)["wallet"] == "off"
    assert reply("unlock", capsys, "--method", "wallet") == {"ok": False, "error": "not-set-up"}
    assert stubs.calls("gocryptfs") == []


# --- destroy ---------------------------------------------------------------------------------------------


def destroy_problems(module, stubs, *, expect_cleared):
    problems = []
    items = stubs.items()
    result = module.run("destroy")
    if result != {"ok": True}:
        problems.append(f"the reply is {result}")
    if stubs.cipher.exists() or stubs.keys.exists():
        problems.append("files are left")
    cleared = stubs.items() == {} and items != {}
    if cleared != expect_cleared:
        problems.append("the items were cleared" if cleared else "the items stay")
    if not expect_cleared and stubs.tools("secret-tool", "openssl"):
        problems.append(f"ran {stubs.tools('secret-tool', 'openssl')}")
    return problems


def test_destroy_clears_the_items_when_the_folder_had_a_slot(stubs, capsys):
    enrolled(stubs, capsys)
    assert destroy_problems(vault, stubs, expect_cleared=True) == []
    assert [step(call) for call in secret_calls(stubs)] == ["openssl", f"store {ITEM}", f"clear {ITEM}"]


@pytest.mark.parametrize("name", ["secret-service.conf.old", "secret-service.conf.new"])
def test_destroy_counts_a_staged_or_old_slot(stubs, capsys, name):
    enrolled(stubs, capsys)
    stubs.slot.rename(stubs.keys / name)
    assert destroy_problems(vault, stubs, expect_cleared=True) == []


def without_a_slot(stubs, capsys):
    """Items from elsewhere (another XDG_DATA_HOME), and here only the widget's wallet.conf."""
    enrolled(stubs, capsys)
    stubs.slot.unlink()
    stubs.wallet_slot()


def test_destroy_without_a_slot_leaves_the_keyring_alone(stubs, capsys):
    without_a_slot(stubs, capsys)
    assert destroy_problems(vault, stubs, expect_cleared=False) == []
    assert stubs.tools("secret-tool", "busctl", "kwallet-query", "qdbus6") == []


DESTROY_MUTATIONS = {
    "always cleared": ("                had_keyring_slot = _app_holds_wallet_slot(data_app, KEYRING_SLOT)\n",
                       "                had_keyring_slot = True\n"),
    "the wallet slot counts": ("                had_keyring_slot = _app_holds_wallet_slot(data_app, KEYRING_SLOT)\n",
                               "                had_keyring_slot = _app_holds_wallet_slot(data_app)\n"),
}


@pytest.mark.parametrize("name", sorted(DESTROY_MUTATIONS))
def test_proof_the_destroy_rule_catches(stubs, capsys, name):
    without_a_slot(stubs, capsys)
    assert destroy_problems(_copy(mutant(vault, *DESTROY_MUTATIONS[name])), stubs, expect_cleared=False)


def test_proof_destroy_needs_its_clear(stubs, capsys):
    enrolled(stubs, capsys)
    copy = _copy(mutant(vault, "        if had_keyring_slot and ctx.mode == frontend.APP:\n",
                        "        if had_keyring_slot and ctx.mode == 'x':\n"))
    assert destroy_problems(copy, stubs, expect_cleared=True)


def forget_destroy_problems(module, stubs):
    """A slot exists: SearchItems decides, not the Locked query; no answer at all is wallet-failed."""
    problems = []
    stubs.env(STUB_SS_LOCKED="fail")  # No default alias (R0 S4): SearchItems still answers.
    result = module.run("destroy")
    if result != {"ok": True} or stubs.items() != {}:
        problems.append(f"with Locked failing: {result}, items {sorted(stubs.items())}")
    return problems


def test_destroy_clears_the_items_when_the_locked_query_fails(stubs, capsys):
    enrolled(stubs, capsys)
    assert forget_destroy_problems(vault, stubs) == []


def test_destroy_without_any_answer_is_wallet_failed(stubs, capsys):
    enrolled(stubs, capsys)
    stubs.env(STUB_SS_BUS="bad")
    assert reply("destroy", capsys) == {"ok": False, "error": "wallet-failed"}
    assert not stubs.cipher.exists() and not stubs.keys.exists()  # The files went first.


def test_proof_destroy_needs_the_search_to_decide(stubs, capsys):
    enrolled(stubs, capsys)
    copy = _copy(mutant(secretkey, "    states = [item_exists(busctl, item) for item in ITEMS]\n",
                        "    if collection_locked(busctl) is None:\n        return False\n"
                        "    states = [item_exists(busctl, item) for item in ITEMS]\n"))
    original = vault.secretkey
    vault.secretkey = copy
    try:
        assert forget_destroy_problems(vault, stubs)
    finally:
        vault.secretkey = original


def test_destroy_deletes_the_files_first_and_reports_a_leftover_item(stubs, capsys):
    enrolled(stubs, capsys)
    stubs.env(STUB_SS_CLEAR_KEEPS=1)
    assert reply("destroy", capsys) == {"ok": False, "error": "wallet-failed"}
    assert not stubs.cipher.exists() and not stubs.keys.exists()


def test_plasma_destroy_and_purge_leave_the_apps_items(stubs, capsys, monkeypatch, tmp_path):
    enrolled(stubs, capsys)
    items = stubs.items()
    stubs.plasma()
    assert reply("destroy", capsys) == {"ok": True}
    assert stubs.items() == items and stubs.tools("secret-tool", "busctl") == []
    monkeypatch.setenv("HEARTHWIRE_FRONTEND", "app")
    enrolled(stubs, capsys)
    items = stubs.items()
    monkeypatch.setattr(vault, "DEFAULT_RUNTIME", str(tmp_path / "none-{uid}"))
    # App-mode purge too (plan: only destroy clears the app's items).
    assert vault.purge() == {"ok": True, "removed": ["vault", "vault-keys"]}
    assert stubs.items() == items and stubs.tools("secret-tool", "busctl") == []


# --- each mode runs only its own tools (task 014) ----------------------------------------------------------

PLASMA_FLOW = [("add-key",), ("unlock", "--method", "wallet"), ("lock",), ("auto-unlock",), ("status",),
               ("remove-key",), ("add-key",), ("lock",), ("destroy",)]
APP_FLOW = [("add-key",), ("unlock", "--method", "wallet"), ("lock",), ("auto-unlock",), ("status",), ("lock",),
            ("remove-key",), ("add-key",), ("destroy",)]


def mode_tool_problems(module, stubs, mode):
    """A whole flow in one mode; the other mode's tools must never run."""
    if mode == frontend.PLASMA:
        stubs.plasma()
    stubs.make_locked()
    stubs.storage("plain")
    # The other mode's slot and secret are there too: a tempting leftover.
    if mode == frontend.PLASMA:
        stubs.slot.parent.mkdir(parents=True, mode=0o700)
        stubs.slot.write_text("{}")
        stubs.slot.chmod(0o400)
        stubs.keyring.write_text(json.dumps({ITEM: "5" * 64}))
    else:
        stubs.wallet_slot()
        stubs.wallet.write_text(json.dumps({"Hearthwire/encrypted-chat-folder": "6" * 64}))
    problems = []
    for operation, *extra in (PLASMA_FLOW if mode == frontend.PLASMA else APP_FLOW):
        result = module.run(operation, method=extra[1] if extra else ("wallet" if operation.endswith("-key") else None))
        if result.get("ok") is not True:
            problems.append(f"{operation}: {result}")
    foreign = ("secret-tool", "busctl") if mode == frontend.PLASMA else ("kwallet-query", "qdbus6", "kdialog")
    ran = stubs.tools(*foreign)
    if ran:
        problems.append(f"{mode} mode ran {sorted(set(ran))}")
    own = ("kwallet-query", "qdbus6") if mode == frontend.PLASMA else ("secret-tool", "busctl")
    if not stubs.tools(*own):
        problems.append(f"{mode} mode ran none of its own tools")
    return problems


@pytest.mark.parametrize("mode", [frontend.PLASMA, frontend.APP])
def test_each_mode_runs_only_its_own_tools(stubs, mode):
    assert mode_tool_problems(vault, stubs, mode) == []


NO_CONTEXT_GAP = ("    if mode == frontend.APP:\n        # No KDE Wallet", "    if False:\n        # No KDE Wallet")
KEYRING_IN_PLASMA = ("    if mode == frontend.APP and find_tools:\n        # Task 014",
                     "    if find_tools:\n        # Task 014")
MODE_MUTATIONS = {
    "plasma unlock goes to the keyring": (frontend.PLASMA, [
        KEYRING_IN_PLASMA, ('    if method == "wallet" and ctx.mode == frontend.APP:\n', '    if method == "wallet":\n')]),
    "plasma add-key goes to the keyring": (frontend.PLASMA, [
        KEYRING_IN_PLASMA, ("    if ctx.mode == frontend.APP:\n        return _keyring_add_key(ctx, environ)\n",
                            "    if True:\n        return _keyring_add_key(ctx, environ)\n")]),
    "plasma destroy clears the keyring": (frontend.PLASMA, [
        KEYRING_IN_PLASMA, ("        if had_keyring_slot and ctx.mode == frontend.APP:\n", "        if had_keyring_slot:\n")]),
    "app unlock goes to KDE Wallet": (frontend.APP, [
        NO_CONTEXT_GAP, ('    if method == "wallet" and ctx.mode == frontend.APP:\n', '    if False:\n'),
        ('    if method == "wallet":\n        _no_app_wallet(ctx)\n', '    if method == "wallet":\n        pass\n')]),
    "app status asks KDE Wallet": (frontend.APP, [
        NO_CONTEXT_GAP, ("    if state in (\"locked\", \"unlocked\") and ctx.mode == frontend.APP:\n",
                         "    if False:\n")]),
}


@pytest.mark.parametrize("name", sorted(MODE_MUTATIONS))
def test_proof_the_mode_rule_catches(stubs, name):
    mode, pairs = MODE_MUTATIONS[name]
    if mode == frontend.APP:
        # The flow gets past the KDE Wallet preflight only with these tools there (they are, as stubs).
        assert (stubs.bin / "qdbus6").exists() and (stubs.bin / "kwallet-query").exists()
    assert mode_tool_problems(_copy(mutants(vault, *pairs)), stubs, mode)


# --- the key never passes through the helper ---------------------------------------------------------------

KEYRING_FUNCTIONS = ("_keyring_status", "_keyring_add_key", "_keyring_remove_key", "_keyring_unlock",
                     "_unlock_with_keyring", "_commit_keyring_slot", "_drop_staged_item", "_keyring_preflight")


def test_vault_keyring_paths_never_read_or_capture():
    tree = ast.parse(VAULT_PY.read_text(encoding="utf-8"))
    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    for name in KEYRING_FUNCTIONS:
        calls = [node for node in ast.walk(functions[name]) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and node.func.attr in ("read", "pread", "readline", "readv", "communicate", "check_output", "splice")]
        assert not calls, name
        assert "PIPE" not in ast.unparse(functions[name]), name


def test_no_key_read_at_run_time(stubs, capsys, monkeypatch):
    """os.read spied during a whole set-up, unlock and removal: the helper's own code never reads a pipe."""
    stubs.make_locked()
    spy = ReadSpy(monkeypatch)
    for operation, *extra in (("add-key",), ("unlock", "--method", "wallet"), ("lock",), ("add-key",),
                              ("remove-key",)):
        assert vault.run(operation, method=extra[1] if extra else ("wallet" if operation.endswith("-key") else None)
                         ) == {"ok": True}, operation
    assert spy.pipe_reads() == []
    # The spy sees the helper's own reads: gocryptfs -version's line, read from a pipe (no key).
    assert any(call[2] and call[4] == "_gocryptfs_major" for call in spy.calls)


def test_proof_the_run_time_spy_sees_a_key_read(stubs, capsys, monkeypatch):
    stubs.make_locked()
    copy = mutant(vault, "                    code = _run(argv, stdin=reader, config=ctx.keyring_new_slot, mode=ctx.mode)\n",
                  "                    os.read(reader, 1)\n"
                  "                    code = _run(argv, stdin=reader, config=ctx.keyring_new_slot, mode=ctx.mode)\n")
    spy = ReadSpy(monkeypatch)
    _copy(copy).run("add-key", method="wallet")
    assert spy.pipe_reads()


# --- stop signals while secret-tool waits (as on the gcr prompt) --------------------------------------------

ADD_KEY = ["--vault", "add-key", "--method", "wallet"]
UNLOCK = ["--vault", "unlock", "--method", "wallet"]
SHORT_FINISH = ("hearthwire.core.termination", "FINISH_TIMEOUT = 10.0\n", "FINISH_TIMEOUT = 0.5\n")


@pytest.fixture
def case(tmp_path, _private_runtime_dir):
    made = Case(tmp_path, _private_runtime_dir)
    install_keyring_stubs(made.bin)
    made.keyring = tmp_path / "keyring.json"
    yield made
    made.cleanup()


def _items(case):
    return json.loads(case.keyring.read_text()) if case.keyring.exists() else {}


def _keys(case):
    return Path(os.path.realpath(case.data)) / "hearthwire" / "vault-keys"


def _waiting(case):
    return bool(case.alive("keyring"))


def _set_up(case):
    case.make_locked()
    assert case.run(ADD_KEY, app=True, STUB_DIALOG_SLEEP=0, STUB_KEYRING=case.keyring) == (0, '{"ok":true}\n', "")
    assert (_keys(case) / "secret-service.conf").exists() and ITEM in _items(case)


def first_set_up_stop_problems(case, block, mutations=()):
    """add-key's first set-up stopped while secret-tool waits (``block``: "<command>:<item>")."""
    case.make_locked()
    problems = stop_problems(case, ADD_KEY, ready=_waiting, mutations=mutations, app=True, STUB_DIALOG_SLEEP=0,
                             STUB_KEYRING=case.keyring, STUB_SS_BLOCK=block)
    keys = _keys(case)
    if keys.exists() and os.listdir(keys):
        problems.append(f"slot files are left: {sorted(os.listdir(keys))}")
    if _items(case):
        problems.append(f"items are left: {sorted(_items(case))}")
    return problems


@pytest.mark.parametrize("block", [f"store:{NEW}", f"lookup:{NEW}"])
def test_a_stop_while_secret_tool_waits_in_add_key(case, block):
    assert first_set_up_stop_problems(case, block) == []


def test_proof_the_secret_tool_wait_is_interruptible(case):
    assert first_set_up_stop_problems(case, f"store:{NEW}", [(
        "hearthwire.core.secretkey", "        code = termination.wait(child, timeout, interruptible=interruptible)\n",
        "        code = termination.wait(child, timeout, interruptible=False)\n")])


def test_proof_the_staged_item_is_cleared_after_a_stop(case):
    assert first_set_up_stop_problems(case, f"lookup:{NEW}", [(
        "hearthwire.core.vault",
        "            except (HelperError, OSError, termination.Stopped) as failure:\n",
        "            except (HelperError, OSError) as failure:\n")])


def test_a_stop_while_the_lookup_answers_the_unlock(case):
    """secret-tool is gocryptfs's extpass here, so it goes with gocryptfs's group."""
    _set_up(case)
    assert stop_problems(case, UNLOCK, ready=_waiting, app=True, STUB_KEYRING=case.keyring,
                         STUB_SS_BLOCK=f"lookup:{ITEM}") == []
    assert not case.mounted()


def resetup_problems(case, mutations=()):
    """Re-setup stopped while the staged key is copied to the real item and the store
    does not finish: the old slot and item come back."""
    _set_up(case)
    slot = _keys(case) / "secret-service.conf"
    inode, item = os.stat(slot).st_ino, _items(case)[ITEM]
    problems = stop_problems(case, ADD_KEY, ready=_waiting, mutations=[SHORT_FINISH, *mutations], app=True,
                             STUB_DIALOG_SLEEP=0, STUB_KEYRING=case.keyring, STUB_SS_BLOCK=f"store:{ITEM}")
    if not slot.exists() or os.stat(slot).st_ino != inode:
        problems.append("the old slot is not back")
    for name in ("secret-service.conf.old", "secret-service.conf.new"):
        if (_keys(case) / name).exists():
            problems.append(f"{name} is left")
    if _items(case).get(ITEM) != item:
        problems.append("the real item changed")
    if NEW in _items(case):
        problems.append("the staged item is left")
    return problems


def test_a_stop_while_the_slot_is_committed_rolls_back(case):
    assert resetup_problems(case) == []


def test_proof_the_commit_rollback_is_needed(case):
    assert resetup_problems(case, [("hearthwire.core.vault",
                                    "    except (HelperError, termination.Stopped):\n        # Roll back:",
                                    "    except HelperError:\n        # Roll back:")])


def commit_finish_problems(case, mutations=()):
    """A stop while the commit's store writes the real item: it finishes, the new slot stays."""
    _set_up(case)
    slot = _keys(case) / "secret-service.conf"
    inode, item = os.stat(slot).st_ino, _items(case)[ITEM]
    problems = stop_problems(case, ADD_KEY, ready=_waiting, mutations=mutations, app=True, expect=('{"ok":true}\n', 0),
                             STUB_DIALOG_SLEEP=0, STUB_KEYRING=case.keyring, STUB_SS_SLEEP=1.0,
                             STUB_SS_BLOCK=f"store:{ITEM}")
    if not slot.exists() or os.stat(slot).st_ino == inode:
        problems.append("the new slot is not in")
    if _items(case).get(ITEM) in (None, item):
        problems.append("the real item is not the new one")
    if NEW in _items(case):
        problems.append("the staged item is left")
    return problems


def test_a_stop_while_the_commit_writes_the_item_lets_it_finish(case):
    assert commit_finish_problems(case) == []


def test_proof_the_commit_store_is_let_finish(case):
    assert commit_finish_problems(case, [("hearthwire.core.vault", "secretkey.ITEM, settling=True)",
                                          "secretkey.ITEM, settling=False)")])


def test_a_stop_while_remove_key_overwrites_still_clears(case):
    _set_up(case)
    problems = stop_problems(case, ["--vault", "remove-key", "--method", "wallet"], ready=_waiting, app=True,
                             expect=('{"ok":true}\n', 0), STUB_KEYRING=case.keyring, STUB_SS_BLOCK=f"store:{ITEM}")
    assert problems == []
    assert _items(case) == {} and not (_keys(case) / "secret-service.conf").exists()


def test_without_a_signal_the_app_runs_are_unchanged(case):
    _set_up(case)
    assert case.run(UNLOCK, app=True, STUB_KEYRING=case.keyring) == (0, '{"ok":true}\n', "")
    assert case.mounted()
    assert case.run(["--vault", "lock"], app=True) == (0, '{"ok":true}\n', "")
    assert case.wait_for(lambda: not case.alive(), timeout=5)

