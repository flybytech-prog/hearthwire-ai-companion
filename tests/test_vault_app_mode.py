"""Task 011: the encrypted chat folder in app mode (HEARTHWIRE_FRONTEND=app).

The passphrase dialog is hearthwire-askpass at its one fixed path, and only
while root alone could have put it there; kdialog is never used in app mode,
and the Plasma widget's KDE Wallet slot is never used or changed there.
Plasma mode is unchanged. Task 014: in app mode the method ``wallet`` is the
Secret Service (test_vault_secret_service.py); here no secret-tool is
installed, so it is missing-tool and status says so. The stub tools of test_vault.py are the only
programs that run; the askpass stub lives outside PATH and is made to look
root's only through a fake lstat given to frontend.askpass_path.
"""

import ast
import json
import os
import stat
import sys
import types
from pathlib import Path

import pytest

from hearthwire.core import frontend, secretkey, vault, walletkey, webdata
from test_frontend import mutant
from test_secretkey import install_keyring_stubs
from test_vault import STUB, Stubs, extpass_values, reply, without_extpass

VAULT_PY = Path(vault.__file__)
REAL_ASKPASS_PATH = frontend.askpass_path
# Task 014: app-mode status fields when no secret-tool is installed and no keyring file exists.
NO_KEYRING = {"keyring": "secret-service", "keyringStorage": "unknown", "missing": ["secret-tool"]}


def root_owned(program):
    """A fake lstat that reports ``program`` and every folder above it as root's 0755."""
    chain = {str(program)}
    folder = os.path.dirname(str(program))
    while True:
        chain.add(folder)
        if folder == "/":
            break
        folder = os.path.dirname(folder)

    def lstat(path):
        if path not in chain:
            raise FileNotFoundError(path)
        kind = stat.S_IFREG if path == str(program) else stat.S_IFDIR
        return os.stat_result((kind | 0o755, 1, 1, 1, 0, 0, 1, 0, 0, 0))

    return lstat


class AppStubs(Stubs):
    def __init__(self, root, monkeypatch, runtime):
        super().__init__(root, monkeypatch, runtime)
        self.lib = root / "lib" / "hearthwire-hyprland"
        self.lib.mkdir(parents=True)
        self.askpass = self.lib / "hearthwire-askpass"
        self.askpass.write_text(STUB.format(python=sys.executable))
        self.askpass.chmod(0o755)
        monkeypatch.setattr(frontend, "ASKPASS_PATH", str(self.askpass))
        self.trust(True)
        monkeypatch.setenv("HEARTHWIRE_FRONTEND", "app")

    def trust(self, trusted):
        """Whether the askpass stub passes the root-owner check (the real check, with a fake lstat)."""
        lstat = root_owned(self.askpass) if trusted else None
        self.monkeypatch.setattr(frontend, "askpass_path", lambda lstat_=None: REAL_ASKPASS_PATH(lstat))

    def plasma(self):
        self.monkeypatch.delenv("HEARTHWIRE_FRONTEND")

    def wallet_slot(self):
        keys = Path(os.path.realpath(self.data)) / "hearthwire" / "vault-keys"
        keys.mkdir(parents=True, mode=0o700, exist_ok=True)
        slot = keys / "wallet.conf"
        slot.write_text('{"key_sha": "0"}')
        slot.chmod(0o400)
        return slot


@pytest.fixture
def stubs(tmp_path, monkeypatch, _private_runtime_dir):
    return AppStubs(tmp_path, monkeypatch, _private_runtime_dir)


def dialog_calls(stubs):
    return [call for call in stubs.calls() if call["tool"] in ("kdialog", "hearthwire-askpass")]


# --- the dialog ----------------------------------------------------------------------------------------


def test_app_create_and_unlock_use_only_the_fixed_askpass(stubs, capsys):
    stubs.env(STUB_RUN_EXTPASS=1)
    assert reply("create", capsys) == {"ok": True}
    init, mount = stubs.calls("gocryptfs")
    askpass = str(stubs.askpass)
    assert without_extpass(init["argv"]) == ["-init", "-q", str(stubs.cipher)]
    assert extpass_values(init["argv"]) == [askpass, "--title", "Hearthwire", "--newpassword", vault.PROMPT_CREATE]
    assert extpass_values(mount["argv"]) == [askpass, "--title", "Hearthwire", "--password", vault.PROMPT_UNLOCK]
    assert [call["tool"] for call in dialog_calls(stubs)] == ["hearthwire-askpass", "hearthwire-askpass"]
    assert stubs.calls("kdialog") == []
    assert reply("status", capsys) == {"ok": True, "state": "unlocked", "wallet": "unavailable", **NO_KEYRING}


def test_app_change_passphrase_runs_askpass_for_both_dialogs(stubs, capsys):
    stubs.make_locked()
    assert reply("change-passphrase", capsys) == {"ok": True}
    (passwd,) = stubs.calls("gocryptfs")
    marker = str(stubs.mountpoint.parent / vault.PASSWD_MARKER)
    assert extpass_values(passwd["argv"]) == [
        sys.executable, vault.RELAY, marker,
        str(stubs.askpass), "--title", "Hearthwire", "--password", vault.PROMPT_CURRENT,
    ]
    assert passwd["new_received"] is True
    old, new = stubs.calls("hearthwire-askpass")
    assert old["argv"] == ["--title", "Hearthwire", "--password", vault.PROMPT_CURRENT]
    assert new["argv"] == ["--title", "Hearthwire", "--newpassword", vault.PROMPT_NEW]
    assert new["fds"] == ["/dev/null", passwd["fds"][0], "/dev/null"]
    assert stubs.calls("kdialog") == []


def test_an_untrusted_askpass_is_missing_and_kdialog_never_stands_in(stubs, capsys):
    stubs.trust(False)
    assert reply("status", capsys) == {"ok": True, "state": "unavailable", "missing": ["hearthwire-askpass"]}
    for operation in ("create", "unlock", "change-passphrase"):
        assert reply(operation, capsys) == {"ok": False, "error": "missing-tool"}, operation
    assert stubs.calls("gocryptfs") == [] and dialog_calls(stubs) == []


def test_an_askpass_on_path_is_never_used(stubs, capsys, monkeypatch):
    """Only the fixed path counts: a hearthwire-askpass on PATH is ignored."""
    stubs.install("hearthwire-askpass")
    monkeypatch.setattr(frontend, "ASKPASS_PATH", str(stubs.root / "nowhere" / "hearthwire-askpass"))
    stubs.trust(True)
    assert reply("status", capsys)["missing"] == ["hearthwire-askpass"]
    assert reply("create", capsys) == {"ok": False, "error": "missing-tool"}
    assert dialog_calls(stubs) == []


def test_the_real_check_refuses_a_user_owned_askpass(stubs, capsys, monkeypatch):
    monkeypatch.setattr(frontend, "askpass_path", REAL_ASKPASS_PATH)
    assert reply("status", capsys)["missing"] == ["hearthwire-askpass"]


def test_app_mode_lists_every_missing_tool_by_its_own_name(stubs, capsys):
    stubs.trust(False)
    for name in ("gocryptfs", "kdialog", "fusermount3"):
        stubs.remove(name)
    assert reply("status", capsys) == {"ok": True, "state": "unavailable",
                                       "missing": ["gocryptfs", "hearthwire-askpass", "fusermount3"]}


def test_plasma_mode_still_uses_kdialog_even_with_a_trusted_askpass(stubs, capsys):
    stubs.plasma()
    stubs.env(STUB_RUN_EXTPASS=1)
    assert reply("create", capsys) == {"ok": True}
    init, mount = stubs.calls("gocryptfs")
    assert extpass_values(init["argv"])[0] == extpass_values(mount["argv"])[0] == str(stubs.bin / "kdialog")
    assert stubs.calls("hearthwire-askpass") == []
    assert reply("status", capsys) == {"ok": True, "state": "unlocked", "wallet": "off"}


def test_plasma_mode_without_kdialog_reports_kdialog(stubs, capsys):
    stubs.plasma()
    stubs.remove("kdialog")
    assert reply("status", capsys) == {"ok": True, "state": "unavailable", "missing": ["kdialog"]}


# --- the KDE Wallet slot is the Plasma widget's ----------------------------------------------------------


@pytest.mark.parametrize("argv", [("add-key",), ("remove-key",), ("auto-unlock",), ("unlock", "--method", "wallet")])
def test_app_mode_never_uses_or_changes_the_wallet_slot(stubs, capsys, argv):
    """The widget's wallet.conf stays and no KDE Wallet tool runs; without secret-tool
    the Secret Service method is missing-tool (task 014)."""
    stubs.make_locked()
    slot = stubs.wallet_slot()
    before = slot.read_bytes()
    operation, *extra = argv
    assert reply(operation, capsys, *extra) == {"ok": False, "error": "missing-tool"}
    assert slot.read_bytes() == before
    assert stubs.calls() == []
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "unavailable", **NO_KEYRING}
    assert [call["tool"] for call in stubs.calls()] == []


def test_app_status_runs_no_wallet_tool(stubs, capsys):
    stubs.make_locked()
    stubs.wallet_slot()
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "unavailable", **NO_KEYRING}
    assert stubs.calls() == []


def test_a_wallet_slot_is_not_a_secret_service_slot(stubs, capsys):
    """With the Secret Service there, the widget's wallet.conf still reads as no slot."""
    install_keyring_stubs(stubs.bin)
    stubs.env(STUB_KEYRING=stubs.root / "keyring.json")
    stubs.make_locked()
    stubs.wallet_slot()
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "off",
                                       "keyring": "secret-service", "keyringStorage": "unknown"}
    assert [call["tool"] for call in stubs.calls()] == ["busctl"]
    assert reply("unlock", capsys, "--method", "wallet") == {"ok": False, "error": "not-set-up"}


def test_app_passphrase_unlock_still_works_with_a_wallet_slot_there(stubs, capsys):
    stubs.make_locked()
    stubs.wallet_slot()
    assert reply("unlock", capsys) == {"ok": True}
    (mount,) = stubs.calls("gocryptfs")
    assert extpass_values(mount["argv"])[0] == str(stubs.askpass)
    assert "-config" not in mount["argv"]


# --- rules on the module itself, with proofs -------------------------------------------------------------


def module_problems(module, stubs):
    problems = []
    stubs.trust(True)
    found, missing = module._find_tools(frontend.APP)
    if found.get("kdialog") != str(stubs.askpass) or "hearthwire-askpass" in missing:
        problems.append("app mode does not take the trusted askpass")
    stubs.install("hearthwire-askpass")  # On PATH too: must make no difference.
    stubs.trust(False)
    found, missing = module._find_tools(frontend.APP)
    if "kdialog" in found or "hearthwire-askpass" not in missing:
        problems.append("app mode takes an untrusted or PATH askpass, or kdialog")
    stubs.remove("hearthwire-askpass")
    stubs.trust(True)
    found, _ = module._find_tools(frontend.PLASMA)
    if found.get("kdialog") != str(stubs.bin / "kdialog"):
        problems.append("plasma mode does not take kdialog from PATH")
    ctx = module.context({**os.environ, "HEARTHWIRE_FRONTEND": "app"})
    if ctx.wallet_tools or ctx.mode != frontend.APP or not ctx.wallet_missing:
        problems.append("app mode looks up KDE Wallet tools")
    # Task 014: the Secret Service tools are looked up in app mode only.
    install_keyring_stubs(stubs.bin, openssl=False)
    if set(module.context({**os.environ, "HEARTHWIRE_FRONTEND": "app"}).keyring_tools) != {
            "secret-tool", "busctl", "openssl"}:
        problems.append("app mode does not look up the Secret Service tools")
    if module.context({**os.environ, "HEARTHWIRE_FRONTEND": "plasma"}).keyring_tools:
        problems.append("plasma mode looks up the Secret Service tools")
    for name in ("secret-tool", "busctl"):
        stubs.remove(name)
    try:
        module._no_app_wallet(ctx)
        problems.append("app mode may use the wallet slot")
    except webdata.HelperError as error:
        if error.code != "wallet-disabled":
            problems.append(f"the wallet refusal is {error.code}")
    askpass = str(stubs.askpass)
    elsewhere = str(stubs.bin / "hearthwire-askpass")
    kdialog = "/usr/bin/kdialog"
    gocryptfs = str(stubs.bin / "gocryptfs")
    python = sys.executable
    # Each front end takes only its own dialog (fix round 1, I2): app mode the
    # askpass at its fixed path, Plasma mode an absolute kdialog.
    shapes = {
        "askpass": askpass, "askpass elsewhere": elsewhere, "a relative askpass": "hearthwire-askpass",
        "kdialog": kdialog, "a relative kdialog": "kdialog", "a shell": "/bin/sh",
    }
    own = {frontend.APP: "askpass", frontend.PLASMA: "kdialog"}
    for current in (frontend.APP, frontend.PLASMA):
        for shape, dialog in shapes.items():
            cases = {
                "the new dialog": module.new_passphrase_argv(dialog),
                "extpass": module.mount_argv(gocryptfs, dialog, "/c", "/m"),
                "init extpass": module.init_argv(gocryptfs, dialog, "/c"),
                "the relay's dialog": module.passwd_argv(gocryptfs, python, "/m", dialog, "/c"),
            }
            for name, argv in cases.items():
                if name == "the new dialog" and not os.path.isabs(dialog):
                    continue  # argv[0] must be absolute in any mode: not this rule.
                try:
                    module._check_argv(argv, mode=current)
                    accepted = True
                except webdata.HelperError:
                    accepted = False
                if accepted != (shape == own[current]):
                    problems.append(f"{current} mode {'takes' if accepted else 'refuses'} {shape} as {name}")
        try:
            module._check_argv([gocryptfs, "-passwd", "-q", *module.extpass_args(python, module.RELAY, "/m"), "/c"],
                               mode=current)
            problems.append(f"{current} mode takes a relay running nothing")
        except webdata.HelperError:
            pass
    try:
        module._check_argv(module.new_passphrase_argv(kdialog))
    except webdata.HelperError:
        problems.append("the default mode is not Plasma's")
    return problems


def test_the_vault_rules_hold(stubs):
    assert module_problems(vault, stubs) == []


VAULT_MUTATIONS = {
    "app mode looks on PATH": ("        if name == DIALOG and mode == frontend.APP:\n", "        if False:\n"),
    "a PATH askpass as fallback": ("            path = frontend.askpass_path()\n",
                                   "            path = frontend.askpass_path() or shutil.which(frontend.ASKPASS_NAME)\n"),
    "kdialog as fallback": ("            path = frontend.askpass_path()\n",
                            '            path = frontend.askpass_path() or shutil.which("kdialog")\n'),
    "askpass anywhere": ("        return name == frontend.ASKPASS_NAME and program == frontend.ASKPASS_PATH\n",
                         "        return name == frontend.ASKPASS_NAME and os.path.isabs(program)\n"),
    "askpass anywhere, even relative": ("        return name == frontend.ASKPASS_NAME and program == frontend.ASKPASS_PATH\n",
                                        "        return name == frontend.ASKPASS_NAME\n"),
    "any relay dialog": (" and os.path.isabs(values[0]) and _is_dialog(values[3], mode)):\n",
                         " and os.path.isabs(values[0])):\n"),
    "the new dialog unchecked": ("        if not _is_dialog(argv[0], mode) or arguments != new_passphrase_argv(argv[0])[1:]:\n",
                                 "        if arguments != new_passphrase_argv(argv[0])[1:]:\n"),
    # Fix round 1 (I2): each mode takes only its own dialog.
    "kdialog in app mode": ("        return name == frontend.ASKPASS_NAME and program == frontend.ASKPASS_PATH\n",
                            "        return program == frontend.ASKPASS_PATH or (name == 'kdialog' and os.path.isabs(program))\n"),
    "askpass in Plasma mode": ('    return name == "kdialog" and os.path.isabs(program)\n',
                               '    return name == "kdialog" and os.path.isabs(program) or program == frontend.ASKPASS_PATH\n'),
    "the mode ignored": ("    if mode == frontend.APP:\n        return name == frontend.ASKPASS_NAME",
                         "    if False:\n        return name == frontend.ASKPASS_NAME"),
    "both dialogs in both modes": ("    if mode == frontend.APP:\n        return name == frontend.ASKPASS_NAME",
                                   "    if name != 'kdialog':\n        return name == frontend.ASKPASS_NAME"),
    "extpass checked as Plasma's": ("    _check_extpass(extpass, mode)\n", "    _check_extpass(extpass, frontend.PLASMA)\n"),
    "the relay's dialog checked as Plasma's": (" and _is_dialog(values[3], mode)):\n",
                                               " and _is_dialog(values[3], frontend.PLASMA)):\n"),
    "gocryptfs checked as Plasma's": ("        _check_gocryptfs_argv(arguments, config, mode)\n",
                                      "        _check_gocryptfs_argv(arguments, config, frontend.PLASMA)\n"),
    "the default mode app": ("config: Optional[str] = None, mode: str = frontend.PLASMA) -> None:\n",
                             "config: Optional[str] = None, mode: str = frontend.APP) -> None:\n"),
    "wallet tools in app mode": ("    if mode == frontend.APP:\n        # No KDE Wallet", "    if False:\n        # No KDE Wallet"),
    "no wallet refusal": ("    if ctx.mode != frontend.PLASMA:\n        raise HelperError(\"wallet-disabled\")\n",
                          "    if False:\n        raise HelperError(\"wallet-disabled\")\n"),
    "the mode not kept": ("        mode=mode,\n        keyring_tools=keyring_tools,\n", "        keyring_tools=keyring_tools,\n"),
    "keyring tools in Plasma mode": ("    if mode == frontend.APP and find_tools:\n        # Task 014",
                                     "    if find_tools:\n        # Task 014"),
    "no keyring tools in app mode": ("        keyring_tools, keyring_missing = secretkey.find_tools()\n",
                                     "        keyring_tools, keyring_missing = {}, secretkey.TOOLS\n"),
}


@pytest.mark.parametrize("name", sorted(VAULT_MUTATIONS))
def test_proof_the_vault_rule_catches(stubs, name):
    assert module_problems(mutant(vault, *VAULT_MUTATIONS[name]), stubs)


# Each wallet operation sends app mode to its Secret Service twin before it touches
# anything (task 014), and then still refuses app mode itself: the first statements
# after ``ctx = context(environ)`` (unlock: the first of its wallet branches).
WALLET_ENTRIES = {"add_key": "_keyring_add_key(ctx, environ)", "remove_key": "_keyring_remove_key(ctx)",
                  "auto_unlock": "_keyring_auto_unlock(ctx, environ)"}


def wallet_guard_problems(source):
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    problems = []
    for name, twin in WALLET_ENTRIES.items():
        body = [statement for statement in functions[name].body
                if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))]
        if [ast.unparse(statement) for statement in body[:3]] != [
                "ctx = context(environ)", f"if ctx.mode == frontend.APP:\n    return {twin}", "_no_app_wallet(ctx)"]:
            problems.append(f"{name} sends app mode to the Secret Service first, then refuses it")
    unlock = functions["unlock"]
    branches = [node for node in ast.walk(unlock) if isinstance(node, ast.If) and "'wallet'" in ast.unparse(node.test)]
    tests = [ast.unparse(node.test) for node in branches]
    if (tests[:2] != ["method == 'wallet' and ctx.mode == frontend.APP", "method == 'wallet'"]
            or ast.unparse(branches[0].body[0]) != "return _keyring_unlock(ctx, environ)"
            or ast.unparse(branches[1].body[0]) != "_no_app_wallet(ctx)"):
        problems.append("unlock --method wallet sends app mode to the Secret Service, then refuses it")
    # purge (fix round 1, M1): the mode is asked first, before anything is
    # deleted, and app mode returns before any wallet tool is looked up.
    purge = functions["_purge_tree"].body
    if not purge or ast.unparse(purge[0]) != "app_mode = frontend.mode(environ) == frontend.APP":
        problems.append("purge asks the mode first")
    stop = [index for index, statement in enumerate(purge) if isinstance(statement, ast.If)
            and ast.unparse(statement.test) == "app_mode" and ast.unparse(statement.body[-1]) == "return present"]
    wallet = [index for index, statement in enumerate(purge) if "walletkey." in ast.unparse(statement)]
    if not stop or not wallet or stop[0] > wallet[0] or any(
            "walletkey." in ast.unparse(statement) for statement in purge[:stop[0]]):
        problems.append("purge stops in app mode before any wallet tool")
    if "secretkey." in ast.unparse(functions["_purge_tree"]):
        problems.append("purge runs a Secret Service tool")
    # destroy (task 011b, N2; task 014): every wallet call sits under its own
    # Plasma-mode check, every Secret Service call under its own app-mode check.
    destroy = functions["destroy"]
    for module, guard_test in (("walletkey.", "had_slot and ctx.mode == frontend.PLASMA"),
                               ("secretkey.", "had_keyring_slot and ctx.mode == frontend.APP")):
        guards = [node for node in ast.walk(destroy) if isinstance(node, ast.If) and ast.unparse(node.test) == guard_test]
        guarded = {id(node) for guard in guards for statement in guard.body for node in ast.walk(statement)}
        calls = [node for node in ast.walk(destroy) if isinstance(node, ast.Call)
                 and ast.unparse(node.func).startswith(module)]
        if not guards or not calls or any(id(node) not in guarded for node in calls):
            problems.append(f"destroy runs {module[:-1]} only under {guard_test}")
    guard = functions.get("_no_app_wallet")
    if guard is None or "if ctx.mode != frontend.PLASMA: raise HelperError('wallet-disabled')" not in " ".join(
            ast.unparse(guard).split()):
        problems.append("_no_app_wallet refuses every mode but Plasma")
    # The Secret Service twins and their helpers never reach a KDE Wallet call.
    for name in [node for node in functions if node.startswith(("_keyring", "_unlock_with_keyring",
                                                                 "_commit_keyring", "_drop_staged_item"))]:
        if "walletkey." in ast.unparse(functions[name]).replace("walletkey.GOCRYPTFS_TEMPORARY_SUFFIX", ""):
            problems.append(f"{name} calls walletkey")
    return problems


def test_every_wallet_operation_sends_app_mode_to_the_secret_service_first():
    assert wallet_guard_problems(VAULT_PY.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(("old", "new"), [
    # remove-key: the Secret Service branch, then the refusal.
    ("    ctx = context(environ)\n    if ctx.mode == frontend.APP:\n        return _keyring_remove_key(ctx)\n",
     "    ctx = context(environ)\n"),
    ("    ctx = context(environ)\n    if ctx.mode == frontend.APP:\n        return _keyring_remove_key(ctx)\n"
     "    _no_app_wallet(ctx)\n", "    ctx = context(environ)\n    if ctx.mode == frontend.APP:\n"
     "        return _keyring_remove_key(ctx)\n"),
    ("    _no_app_wallet(ctx)\n    with vault_lock(ctx, wait=True):\n        with _keys_dir(",
     "    with vault_lock(ctx, wait=True):\n        _no_app_wallet(ctx)\n        with _keys_dir("),
    # add-key and auto-unlock.
    ("        return _keyring_add_key(ctx, environ)\n    _no_app_wallet(ctx)\n",
     "        return _keyring_add_key(ctx, environ)\n"),
    ("    if ctx.mode == frontend.APP:\n        return _keyring_add_key(ctx, environ)\n", ""),
    ("    if ctx.mode == frontend.APP:\n        return _keyring_auto_unlock(ctx, environ)\n", ""),
    ("        return _keyring_auto_unlock(ctx, environ)\n    _no_app_wallet(ctx)\n",
     "        return _keyring_auto_unlock(ctx, environ)\n"),
    # unlock.
    ("    if method == \"wallet\":\n        _no_app_wallet(ctx)\n", "    if method == \"wallet\":\n"),
    ("    if method == \"wallet\" and ctx.mode == frontend.APP:\n        return _keyring_unlock(ctx, environ)\n", ""),
    ("    if ctx.mode != frontend.PLASMA:\n        raise HelperError(\"wallet-disabled\")\n",
     "    if ctx.mode == 'x':\n        raise HelperError(\"wallet-disabled\")\n"),
    # purge (fix round 1, M1)
    ("    if app_mode:\n        # Task 011: no wallet tool", "    if False:\n        # Task 011: no wallet tool"),
    ("    app_mode = frontend.mode(environ) == frontend.APP\n", "    app_mode = False\n"),
    ("    app_mode = frontend.mode(environ) == frontend.APP\n    base_path = data_base(environ)\n",
     "    base_path = data_base(environ)\n    app_mode = frontend.mode(environ) == frontend.APP\n"),
    ("    if not had_slot:\n        return present\n    if app_mode:\n",
     "    tools, _missing = walletkey.find_tools()\n    if not had_slot:\n        return present\n    if app_mode:\n"),
    ("        return present\n    tools, _missing = walletkey.find_tools()\n",
     "        pass\n    tools, _missing = walletkey.find_tools()\n"),
    ("    if not had_slot:\n        return present\n    if app_mode:\n",
     "    secretkey.find_tools()\n    if not had_slot:\n        return present\n    if app_mode:\n"),
    # destroy (task 011b, N2; task 014)
    ("        if had_slot and ctx.mode == frontend.PLASMA:\n", "        if had_slot:\n"),
    ("        if had_slot and ctx.mode == frontend.PLASMA:\n", "        if had_slot or ctx.mode == frontend.PLASMA:\n"),
    ("        if had_slot and ctx.mode == frontend.PLASMA:\n", "        if had_slot and ctx.mode == frontend.APP:\n"),
    ("        remove_entry(app, VAULT_DIR)\n        if had_slot and",
     "        remove_entry(app, VAULT_DIR)\n        walletkey.find_tools()\n        if had_slot and"),
    ("        if had_keyring_slot and ctx.mode == frontend.APP:\n", "        if had_keyring_slot:\n"),
    ("        if had_keyring_slot and ctx.mode == frontend.APP:\n", "        if ctx.mode == frontend.APP:\n"),
    ("        remove_entry(app, VAULT_DIR)\n        if had_slot and",
     "        remove_entry(app, VAULT_DIR)\n        secretkey.find_tools()\n        if had_slot and"),
    # A twin reaching KDE Wallet.
    ("        _keyring_preflight(ctx)\n        secretkey.remove_items(ctx.keyring_tools)\n",
     "        _keyring_preflight(ctx)\n        walletkey.forget(ctx.wallet_tools)\n"
     "        secretkey.remove_items(ctx.keyring_tools)\n"),
])
def test_proof_the_wallet_guard_rule_catches(old, new):
    source = VAULT_PY.read_text(encoding="utf-8")
    assert old in source
    assert wallet_guard_problems(source.replace(old, new, 1))


NO_TWIN = ("    ctx = context(environ)\n    if ctx.mode == frontend.APP:\n        return _keyring_remove_key(ctx)\n",
           "    ctx = context(environ)\n")
NO_REFUSAL = ("        return _keyring_remove_key(ctx)\n    _no_app_wallet(ctx)\n    with vault_lock(ctx, wait=True):\n",
              "        return _keyring_remove_key(ctx)\n    with vault_lock(ctx, wait=True):\n")
NO_REFUSAL_ONLY = ("    _no_app_wallet(ctx)\n    with vault_lock(ctx, wait=True):\n        with _keys_dir(",
                   "    with vault_lock(ctx, wait=True):\n        with _keys_dir(")
TWIN_REMOVES_THE_WALLET_SLOT = ("                _remove_slot(keys, KEYRING_SLOT)\n", "                _remove_slot(keys)\n")


def test_remove_key_in_app_mode_keeps_the_slot_end_to_end(stubs, capsys):
    """The guard rule's reason: the Plasma remove-key deletes the slot before it looks for
    wallet tools, and the app's twin must delete only its own slot files."""
    stubs.make_locked()
    slot = stubs.wallet_slot()
    assert vault.run("remove-key", method="wallet") == {"ok": False, "error": "missing-tool"}
    assert slot.exists()
    for pairs in ((NO_TWIN,), (NO_REFUSAL,)):
        _copy(mutants(vault, *pairs)).run("remove-key", method="wallet")
        assert slot.exists(), pairs  # One of the two checks is still there.
    _copy(mutants(vault, NO_TWIN, NO_REFUSAL_ONLY)).run("remove-key", method="wallet")
    assert not slot.exists()  # Without both the Plasma widget's slot is gone.
    stubs.wallet_slot()
    _copy(mutants(vault, TWIN_REMOVES_THE_WALLET_SLOT)).run("remove-key", method="wallet")
    assert not slot.exists()  # A twin using the default slot names would delete it too.


# --- every call site passes the mode (fix round 1, I2) ---------------------------------------------------


def _copy(module):
    """``module`` with the attributes the stubs patched on the real vault."""
    for name in ("MOUNTINFO", "_same_device", "LOCK_TIMEOUT"):
        setattr(module, name, getattr(vault, name))
    return module


def app_flow_problems(module, stubs):
    """create, lock, unlock and change-passphrase in app mode, each through the askpass only."""
    stubs.env(STUB_RUN_EXTPASS=1)
    problems = []
    for operation in ("create", "lock", "unlock", "lock", "change-passphrase"):
        result = module.run(operation)
        if result != {"ok": True}:
            problems.append(f"{operation}: {result}")
    if stubs.calls("kdialog"):
        problems.append("kdialog ran")
    return problems


def test_the_app_flow_runs_through_the_askpass(stubs):
    assert app_flow_problems(vault, stubs) == []


CALL_SITE_MUTATIONS = {
    "init without the mode": ('ctx.tools["kdialog"], ctx.cipher), mode=ctx.mode,\n', 'ctx.tools["kdialog"], ctx.cipher),\n'),
    "mount without the mode": ("ctx.cipher, ctx.mountpoint),\n                    mode=ctx.mode)\n",
                               "ctx.cipher, ctx.mountpoint))\n"),
    "passwd argv checked as Plasma's": ("    _check_argv(argv, mode=ctx.mode)\n    _clear_marker(app)\n",
                                        "    _check_argv(argv)\n    _clear_marker(app)\n"),
    "the relay spawned as Plasma's": ("env=relay_environment(), mode=ctx.mode)\n", "env=relay_environment())\n"),
    "the new dialog spawned as Plasma's": ('stdout=writer, mode=ctx.mode)\n', "stdout=writer)\n"),
    "_run ignores its mode": ("    _check_argv(argv, config=config, mode=mode)\n", "    _check_argv(argv, config=config)\n"),
    "_spawn ignores its mode": ("    _check_argv(argv, mode=mode)\n    try:\n        return subprocess.Popen(",
                                "    _check_argv(argv)\n    try:\n        return subprocess.Popen("),
}


@pytest.mark.parametrize("name", sorted(CALL_SITE_MUTATIONS))
def test_proof_the_call_site_rule_catches(stubs, name):
    assert app_flow_problems(_copy(mutant(vault, *CALL_SITE_MUTATIONS[name])), stubs)


# --- purge leaves the widget's wallet entry (fix round 1, M1) ---------------------------------------------

WALLET_KEY = "Hearthwire/encrypted-chat-folder"


def enrolled_by_the_widget(stubs, capsys, monkeypatch, tmp_path):
    """A wallet slot and entry the Plasma widget set up; then the app runs, with only stub tools."""
    monkeypatch.setattr(vault, "DEFAULT_RUNTIME", str(tmp_path / "none-{uid}"))
    stubs.plasma()
    stubs.make_locked()
    assert reply("add-key", capsys) == {"ok": True}
    monkeypatch.setenv("HEARTHWIRE_FRONTEND", "app")
    stubs.log.write_text("")
    return json.loads(stubs.wallet.read_text())[WALLET_KEY]


def purge_problems(purge, stubs, entry):
    problems = []
    result = purge()
    if result != {"ok": True, "removed": ["vault", "vault-keys"]}:
        problems.append(f"the reply is {result}")
    if stubs.calls():
        problems.append(f"ran {[call['tool'] for call in stubs.calls()]}")
    if json.loads(stubs.wallet.read_text()).get(WALLET_KEY) != entry:
        problems.append("the widget's wallet entry changed")
    if stubs.cipher.exists():
        problems.append("the encrypted folder is still there")
    return problems


def test_app_purge_runs_no_wallet_tool_and_keeps_the_widgets_entry(stubs, capsys, monkeypatch, tmp_path):
    entry = enrolled_by_the_widget(stubs, capsys, monkeypatch, tmp_path)
    assert cli_purge(capsys) == {"ok": True, "removed": ["vault", "vault-keys"]}
    assert stubs.calls() == []
    assert json.loads(stubs.wallet.read_text())[WALLET_KEY] == entry


def cli_purge(capsys):
    from hearthwire import cli

    assert cli.main(["--web-data", "purge"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def test_app_purge_rule_holds(stubs, capsys, monkeypatch, tmp_path):
    entry = enrolled_by_the_widget(stubs, capsys, monkeypatch, tmp_path)
    assert purge_problems(vault.purge, stubs, entry) == []


PURGE_MUTATIONS = {
    "no app-mode stop": ("    if app_mode:\n        # Task 011: no wallet tool", "    if False:\n        # Task 011: no wallet tool"),
    "the mode never asked": ("    app_mode = frontend.mode(environ) == frontend.APP\n", "    app_mode = False\n"),
    "the mode compared to Plasma": ("    app_mode = frontend.mode(environ) == frontend.APP\n",
                                    "    app_mode = frontend.mode(environ) == frontend.PLASMA\n"),
}


@pytest.mark.parametrize("name", sorted(PURGE_MUTATIONS))
def test_proof_the_purge_rule_catches(stubs, capsys, monkeypatch, tmp_path, name):
    entry = enrolled_by_the_widget(stubs, capsys, monkeypatch, tmp_path)
    copy = _copy(mutant(vault, *PURGE_MUTATIONS[name]))
    copy.DEFAULT_RUNTIME = vault.DEFAULT_RUNTIME
    assert purge_problems(copy.purge, stubs, entry)


def test_plasma_purge_still_forgets_the_entry(stubs, capsys, monkeypatch, tmp_path):
    enrolled_by_the_widget(stubs, capsys, monkeypatch, tmp_path)
    stubs.plasma()
    assert cli_purge(capsys) == {"ok": True, "removed": ["vault", "vault-keys", "wallet-entry"]}
    assert WALLET_KEY not in json.loads(stubs.wallet.read_text())


# --- each mode's own tools only (task 011b, N1; task 014) -----------------------------------------------

WALLET = "kdewallet"
BOTH = (frontend.PLASMA, frontend.APP)


def wallet_argv_problems(module, stubs):
    """_check_argv takes the KDE Wallet tools' argv (and the kwallet-query extpass) in Plasma
    mode only, the Secret Service tools' argv (and the secret-tool extpass) in app mode
    only, and openssl's one shape in both."""
    gocryptfs = str(stubs.bin / "gocryptfs")
    kwallet_query = "/usr/bin/kwallet-query"
    secret_tool, busctl = "/usr/bin/secret-tool", "/usr/bin/busctl"
    slot = "/d/hearthwire/vault-keys/wallet.conf"
    keyring_slot = "/d/hearthwire/vault-keys/secret-service.conf"
    plasma, app = (frontend.PLASMA,), (frontend.APP,)
    cases = {
        "openssl rand": (walletkey.keygen_argv("/usr/bin/openssl"), None, BOTH),
        "kwallet-query read": (walletkey.read_argv(kwallet_query, WALLET), None, plasma),
        "kwallet-query write": (walletkey.write_argv(kwallet_query, WALLET), None, plasma),
        "qdbus6 isEnabled": (walletkey.kwallet_argv("/usr/bin/qdbus6", "isEnabled"), None, plasma),
        "qdbus-qt6 localWallet": (walletkey.kwallet_argv("/usr/bin/qdbus-qt6", "localWallet"), None, plasma),
        "qdbus6 Secret Service": (walletkey.secrets_argv("/usr/bin/qdbus6", walletkey.SECRETS_DEFAULT_ALIAS,
                                                         "Locked"), None, plasma),
        "the kwallet-query extpass": (module.wallet_mount_argv(gocryptfs, kwallet_query, WALLET, slot, "/c", "/m"),
                                      slot, plasma),
        "secret-tool store": (secretkey.store_argv(secret_tool, secretkey.ITEM_NEW), None, app),
        "secret-tool lookup": (secretkey.lookup_argv(secret_tool), None, app),
        "secret-tool clear": (secretkey.clear_argv(secret_tool, secretkey.ITEM), None, app),
        "busctl Locked": (secretkey.locked_argv(busctl), None, app),
        "busctl SearchItems": (secretkey.search_argv(busctl, secretkey.ITEM), None, app),
        "the secret-tool extpass": (module.keyring_mount_argv(gocryptfs, secret_tool, keyring_slot, "/c", "/m"),
                                    keyring_slot, app),
        # Never, in either mode.
        "secret-tool search": ([secret_tool, "search", *secretkey.attributes(secretkey.ITEM)], None, ()),
        "the staging item as extpass": (
            [gocryptfs, "-q", "-nosyslog", "-config", keyring_slot,
             *module.extpass_args(*secretkey.lookup_argv(secret_tool, secretkey.ITEM_NEW)), "/c", "/m"],
            keyring_slot, ()),
        "a store as extpass": (
            [gocryptfs, "-q", "-nosyslog", "-config", keyring_slot,
             *module.extpass_args(*secretkey.store_argv(secret_tool, secretkey.ITEM)), "/c", "/m"], keyring_slot, ()),
        "the secret-tool extpass with another -config": (
            module.keyring_mount_argv(gocryptfs, secret_tool, keyring_slot, "/c", "/m"), slot, ()),
    }
    problems = []
    for current in BOTH:
        for name, (argv, config, modes) in cases.items():
            try:
                module._check_argv(argv, config=config, mode=current)
                accepted = True
            except webdata.HelperError:
                accepted = False
            if accepted != (current in modes):
                problems.append(f"{current} mode {'takes' if accepted else 'refuses'} {name}")
    return problems


def test_each_mode_takes_only_its_own_tools_argv(stubs):
    assert wallet_argv_problems(vault, stubs) == []


WALLET_ARGV_MUTATIONS = {
    "wallet tools in any mode": ("        if mode != frontend.PLASMA:\n            raise HelperError(\"os-error\")\n"
                                 "        walletkey.check_argv(argv)\n", "        walletkey.check_argv(argv)\n"),
    "wallet tools in app mode only": ("        if mode != frontend.PLASMA:\n            raise HelperError(\"os-error\")\n"
                                      "        walletkey.check_argv(argv)\n",
                                      "        if mode == frontend.PLASMA:\n            raise HelperError(\"os-error\")\n"
                                      "        walletkey.check_argv(argv)\n"),
    "the kwallet-query extpass in any mode": ("        if mode != frontend.PLASMA or not walletkey.is_read_argv(values):\n",
                                              "        if not walletkey.is_read_argv(values):\n"),
    "keyring tools in any mode": ("        if mode != frontend.APP:\n            raise HelperError(\"os-error\")\n"
                                  "        secretkey.check_argv(argv)\n", "        secretkey.check_argv(argv)\n"),
    "keyring tools in Plasma mode only": ("        if mode != frontend.APP:\n            raise HelperError(\"os-error\")\n"
                                          "        secretkey.check_argv(argv)\n",
                                          "        if mode == frontend.APP:\n            raise HelperError(\"os-error\")\n"
                                          "        secretkey.check_argv(argv)\n"),
    "keyring tools unchecked": ("        secretkey.check_argv(argv)\n    elif tool == walletkey.KEYGEN_TOOL:",
                                "        pass\n    elif tool == walletkey.KEYGEN_TOOL:"),
    "the secret-tool extpass in any mode": ("        if mode != frontend.APP or not secretkey.is_lookup_argv(values):\n",
                                            "        if not secretkey.is_lookup_argv(values):\n"),
    "any secret-tool extpass in app mode": ("        if mode != frontend.APP or not secretkey.is_lookup_argv(values):\n",
                                            "        if mode != frontend.APP:\n"),
    "openssl in Plasma mode only": ("    elif tool == walletkey.KEYGEN_TOOL:\n        walletkey.check_argv(argv)\n",
                                    "    elif tool == walletkey.KEYGEN_TOOL:\n        if mode != frontend.PLASMA:\n"
                                    "            raise HelperError(\"os-error\")\n        walletkey.check_argv(argv)\n"),
}


@pytest.mark.parametrize("name", sorted(WALLET_ARGV_MUTATIONS))
def test_proof_the_wallet_argv_rule_catches(stubs, name):
    assert wallet_argv_problems(mutant(vault, *WALLET_ARGV_MUTATIONS[name]), stubs)


# --- destroy leaves the widget's wallet entry by its own check (task 011b, N2) ---------------------------

# context() gives app mode no wallet tools; with that switched off, destroy's
# own check must still keep the widget's entry.
NO_CONTEXT_GAP = ("    if mode == frontend.APP:\n        # No KDE Wallet", "    if False:\n        # No KDE Wallet")
NO_DESTROY_CHECK = ("        if had_slot and ctx.mode == frontend.PLASMA:\n            walletkey.forget(",
                    "        if had_slot:\n            walletkey.forget(")


def mutants(module, *pairs):
    """``module`` with every (old, new) pair applied once, in order."""
    path = Path(module.__file__)
    source = path.read_text(encoding="utf-8")
    for old, new in pairs:
        assert old in source, f"proof fixture out of date: {old!r} not in {path.name}"
        source = source.replace(old, new, 1)
    copy = types.ModuleType(module.__name__ + "_mutant")
    copy.__file__ = str(path)
    copy.__package__ = module.__package__
    sys.modules[copy.__name__] = copy
    try:
        exec(compile(source, str(path), "exec"), copy.__dict__)
    finally:
        del sys.modules[copy.__name__]
    return copy


def destroy_problems(module, stubs, entry):
    problems = []
    result = module.run("destroy")
    if result != {"ok": True}:
        problems.append(f"the reply is {result}")
    if stubs.calls():
        problems.append(f"ran {[call['tool'] for call in stubs.calls()]}")
    if json.loads(stubs.wallet.read_text()).get(WALLET_KEY) != entry:
        problems.append("the widget's wallet entry changed")
    if stubs.cipher.exists():
        problems.append("the encrypted folder is still there")
    return problems


def test_app_destroy_runs_no_wallet_tool_and_keeps_the_widgets_entry(stubs, capsys, monkeypatch, tmp_path):
    entry = enrolled_by_the_widget(stubs, capsys, monkeypatch, tmp_path)
    assert destroy_problems(vault, stubs, entry) == []


def test_app_destroy_keeps_the_entry_even_with_wallet_tools_in_its_context(stubs, capsys, monkeypatch, tmp_path):
    entry = enrolled_by_the_widget(stubs, capsys, monkeypatch, tmp_path)
    assert destroy_problems(_copy(mutants(vault, NO_CONTEXT_GAP)), stubs, entry) == []


def test_proof_the_destroy_rule_catches(stubs, capsys, monkeypatch, tmp_path):
    entry = enrolled_by_the_widget(stubs, capsys, monkeypatch, tmp_path)
    assert destroy_problems(_copy(mutants(vault, NO_CONTEXT_GAP, NO_DESTROY_CHECK)), stubs, entry)


def test_plasma_destroy_still_forgets_the_entry(stubs, capsys, monkeypatch, tmp_path):
    enrolled_by_the_widget(stubs, capsys, monkeypatch, tmp_path)
    stubs.plasma()
    assert reply("destroy", capsys) == {"ok": True}
    assert WALLET_KEY not in json.loads(stubs.wallet.read_text())
