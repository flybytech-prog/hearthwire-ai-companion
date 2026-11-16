"""Task 011: the encrypted chat folder in app mode (HEARTHWIRE_FRONTEND=app).

The passphrase dialog is hearthwire-askpass at its one fixed path, and only
while root alone could have put it there; kdialog is never used in app mode,
and the Plasma widget's KDE Wallet slot is never used or changed there.
Plasma mode is unchanged. The stub tools of test_vault.py are the only
programs that run; the askpass stub lives outside PATH and is made to look
root's only through a fake lstat given to frontend.askpass_path.
"""

import ast
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from hearthwire.core import frontend, vault, webdata
from test_frontend import mutant
from test_vault import STUB, Stubs, extpass_values, reply, without_extpass

VAULT_PY = Path(vault.__file__)
REAL_ASKPASS_PATH = frontend.askpass_path


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
    assert reply("status", capsys) == {"ok": True, "state": "unlocked", "wallet": "unavailable"}


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
    stubs.make_locked()
    slot = stubs.wallet_slot()
    before = slot.read_bytes()
    operation, *extra = argv
    assert reply(operation, capsys, *extra) == {"ok": False, "error": "wallet-disabled"}
    assert slot.read_bytes() == before
    assert [call for call in stubs.calls() if call["tool"] != "gocryptfs"] == []
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "unavailable"}
    assert [call["tool"] for call in stubs.calls()] == []


def test_app_status_runs_no_wallet_tool(stubs, capsys):
    stubs.make_locked()
    stubs.wallet_slot()
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "unavailable"}
    assert stubs.calls() == []


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
    "the mode not kept": ("        mode=mode,\n    )\n", "    )\n"),
}


@pytest.mark.parametrize("name", sorted(VAULT_MUTATIONS))
def test_proof_the_vault_rule_catches(stubs, name):
    assert module_problems(mutant(vault, *VAULT_MUTATIONS[name]), stubs)


# Each wallet operation refuses app mode before it touches anything: the first
# statement after ``ctx = context(environ)`` (unlock: the first in its wallet branch).
WALLET_ENTRIES = ("add_key", "remove_key", "auto_unlock")


def wallet_guard_problems(source):
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    problems = []
    for name in WALLET_ENTRIES:
        body = [statement for statement in functions[name].body
                if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))]
        if [ast.unparse(statement) for statement in body[:2]] != ["ctx = context(environ)", "_no_app_wallet(ctx)"]:
            problems.append(f"{name} refuses app mode first")
    unlock = functions["unlock"]
    branches = [node for node in ast.walk(unlock) if isinstance(node, ast.If) and ast.unparse(node.test) == "method == 'wallet'"]
    if not branches or ast.unparse(branches[0].body[0]) != "_no_app_wallet(ctx)":
        problems.append("unlock --method wallet refuses app mode first")
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
    guard = functions.get("_no_app_wallet")
    if guard is None or "if ctx.mode != frontend.PLASMA: raise HelperError('wallet-disabled')" not in " ".join(
            ast.unparse(guard).split()):
        problems.append("_no_app_wallet refuses every mode but Plasma")
    return problems


def test_every_wallet_operation_refuses_app_mode_first():
    assert wallet_guard_problems(VAULT_PY.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(("old", "new"), [
    ("    ctx = context(environ)\n    _no_app_wallet(ctx)\n    with vault_lock(ctx, wait=True):\n",
     "    ctx = context(environ)\n    with vault_lock(ctx, wait=True):\n"),
    ("    ctx = context(environ)\n    _no_app_wallet(ctx)\n    with vault_lock(ctx, wait=True):\n        with _keys_dir(",
     "    ctx = context(environ)\n    with vault_lock(ctx, wait=True):\n        _no_app_wallet(ctx)\n        with _keys_dir("),
    ("    ctx = context(environ)\n    _no_app_wallet(ctx)\n    _require_tools(ctx, \"gocryptfs\", \"kdialog\")\n",
     "    ctx = context(environ)\n    _require_tools(ctx, \"gocryptfs\", \"kdialog\")\n"),
    ("    ctx = context(environ)\n    _no_app_wallet(ctx)\n    _require_tools(ctx, \"gocryptfs\", \"fusermount3\")\n",
     "    ctx = context(environ)\n    _require_tools(ctx, \"gocryptfs\", \"fusermount3\")\n"),
    ("    if method == \"wallet\":\n        _no_app_wallet(ctx)\n", "    if method == \"wallet\":\n"),
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
])
def test_proof_the_wallet_guard_rule_catches(old, new):
    source = VAULT_PY.read_text(encoding="utf-8")
    assert old in source
    assert wallet_guard_problems(source.replace(old, new, 1))


def test_remove_key_in_app_mode_keeps_the_slot_end_to_end(stubs, capsys):
    """The guard rule's reason: remove-key deletes the slot before it looks for wallet tools."""
    stubs.make_locked()
    slot = stubs.wallet_slot()
    copy = mutant(vault, "    ctx = context(environ)\n    _no_app_wallet(ctx)\n    with vault_lock(ctx, wait=True):\n",
                  "    ctx = context(environ)\n    with vault_lock(ctx, wait=True):\n")
    for name in ("MOUNTINFO", "_same_device", "LOCK_TIMEOUT"):
        setattr(copy, name, getattr(vault, name))
    assert vault.run("remove-key", method="wallet") == {"ok": False, "error": "wallet-disabled"}
    assert slot.exists()
    copy.run("remove-key", method="wallet")
    assert not slot.exists()  # Without the guard the Plasma widget's slot is gone.


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
    "init without the mode": ('ctx.tools["kdialog"], ctx.cipher), mode=ctx.mode)\n', 'ctx.tools["kdialog"], ctx.cipher))\n'),
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
