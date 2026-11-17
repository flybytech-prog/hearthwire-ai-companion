"""Task 011: the helper's app mode (core/frontend.py and its use in cli.py).

The front end comes only from HEARTHWIRE_FRONTEND, never from argv; a bad
value runs nothing. The app's reserved applet id is refused in Plasma mode
and is the only id app mode takes. hearthwire-askpass is used only at its
fixed path and only while root alone could have put it there.

Every rule has a proof: the same check run against a mutated copy of the
module (``mutant``) must fail. Nothing here touches the real home, bus or
/usr: the XDG bases are under tmp_path and askpass_path gets a fake lstat.
"""

import ast
import json
import os
import re
import stat
import sys
import types
from pathlib import Path

import pytest

from hearthwire import cli
from hearthwire.core import frontend, legacy, settingsbackup, usagehistory, webdata

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_PY = Path(frontend.__file__)
CLI_PY = Path(cli.__file__)
SETTINGS_BACKUP_PY = Path(settingsbackup.__file__)
APP_ID = frontend.APP_APPLET_ID


def mutant(module, old, new):
    """A fresh copy of ``module`` with ``old`` replaced by ``new`` once (the proof that a check bites).

    It is never put in sys.modules, so nothing else ever imports it.
    """
    path = Path(module.__file__)
    source = path.read_text(encoding="utf-8")
    assert old in source, f"proof fixture out of date: {old!r} not in {path.name}"
    copy = types.ModuleType(module.__name__ + "_mutant")
    copy.__file__ = str(path)
    copy.__package__ = module.__package__
    sys.modules[copy.__name__] = copy  # dataclasses look their module up while the class is made.
    try:
        exec(compile(source.replace(old, new, 1), str(path), "exec"), copy.__dict__)
    finally:
        del sys.modules[copy.__name__]
    return copy


@pytest.fixture
def homes(tmp_path, monkeypatch):
    """HOME and every XDG base inside tmp_path."""
    for name, folder in (("HOME", "home"), ("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config"),
                         ("XDG_STATE_HOME", "state")):
        (tmp_path / folder).mkdir()
        monkeypatch.setenv(name, str(tmp_path / folder))
    return tmp_path


def cli_run(capsys, *argv, expected_exit=0):
    assert cli.main(list(argv)) == expected_exit
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    return json.loads(captured.out)


def tree(root):
    return sorted(str(path.relative_to(root)) for path in Path(root).rglob("*"))


# --- the switch ------------------------------------------------------------------------------------


def mode_problems(module):
    problems = []
    for environ, expected in (({}, "plasma"), ({"HEARTHWIRE_FRONTEND": "plasma"}, "plasma"),
                              ({"HEARTHWIRE_FRONTEND": "app"}, "app")):
        try:
            if module.mode(environ) != expected:
                problems.append(f"{environ} is {expected}")
        except webdata.HelperError:
            problems.append(f"{environ} is {expected}, not an error")
    for value in ("", "App", "APP", "app ", " app", "plasma\n", "kde", "omarchy", "hyprland", "1", "app\x00"):
        try:
            module.mode({"HEARTHWIRE_FRONTEND": value})
        except webdata.HelperError as error:
            if error.code != "bad-frontend":
                problems.append(f"{value!r}: {error.code}")
        else:
            problems.append(f"{value!r} is bad-frontend")
    return problems


def test_the_front_end_is_unset_plasma_or_app_and_nothing_else():
    assert mode_problems(frontend) == []


def test_mode_reads_the_process_environment_by_default(monkeypatch):
    assert frontend.mode() == "plasma"
    monkeypatch.setenv("HEARTHWIRE_FRONTEND", "app")
    assert frontend.mode() == "app" and frontend.is_app()
    monkeypatch.setenv("HEARTHWIRE_FRONTEND", "x")
    with pytest.raises(webdata.HelperError):
        frontend.mode()


@pytest.mark.parametrize(("old", "new"), [
    ("    if value is None or value == PLASMA:\n", "    if value is None or value != APP:\n"),
    ("    if value is None or value == PLASMA:\n", "    if not value or value == PLASMA:\n"),
    ("    if value == APP:\n", "    if value.strip().lower() == APP:\n"),
    ('    raise HelperError("bad-frontend")\n', "    return PLASMA\n"),
    ('APP = "app"\n', 'APP = "App"\n'),
])
def test_proof_the_switch_rule_catches(old, new):
    assert mode_problems(mutant(frontend, old, new))


def test_bad_frontend_runs_nothing_and_exits_2(homes, capsys, monkeypatch):
    monkeypatch.setenv("HEARTHWIRE_FRONTEND", "nonsense")
    for argv in (["--catalog"], ["--detect"], ["--vault", "status"], ["--settings-backup", "status"],
                 ["--usage-history", "record", "--applet", "3", "--sample", "claude.session=5"],
                 ["--web-data", "purge"], ["--install-info"]):
        assert cli_run(capsys, *argv, expected_exit=2) == {"ok": False, "error": "bad-frontend"}
    assert tree(homes) == ["config", "data", "home", "state"]


def test_bad_frontend_never_echoes_the_value(capsys, monkeypatch):
    monkeypatch.setenv("HEARTHWIRE_FRONTEND", "secret-looking-value")
    assert cli.main(["--catalog"]) == 2
    captured = capsys.readouterr()
    assert "secret-looking-value" not in captured.out + captured.err


def test_usage_errors_stay_usage_errors_whatever_the_front_end(capsys, monkeypatch):
    monkeypatch.setenv("HEARTHWIRE_FRONTEND", "nonsense")
    with pytest.raises(SystemExit) as raised:
        cli.main(["--vault", "nope"])
    assert raised.value.code == 2
    assert capsys.readouterr().out == ""


# --- env never from argv ------------------------------------------------------------------------------


def argv_switch_problems(cli_source, frontend_source):
    """No option names the front end or the prompt, cli never writes the environment and asks
    frontend.mode() without arguments, and frontend.py never looks at argv."""
    problems = []
    tree = ast.parse(cli_source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
            flags = [arg.value for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str)]
            if any(re.search(r"(?i)front|askpass|^--app\b|hypr|omarchy", flag) for flag in flags):
                problems.append(f"cli option {flags} could choose the front end")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and (
                node.func.attr in {"putenv", "unsetenv"} or (
                    node.func.attr in {"setdefault", "update", "pop", "popitem", "clear"}
                    and "environ" in ast.unparse(node.func.value))):
            problems.append(f"cli.py:{node.lineno} writes the environment")
        if isinstance(node, (ast.Subscript, ast.Attribute)) and isinstance(getattr(node, "ctx", None), (ast.Store, ast.Del)) \
                and "environ" in ast.unparse(node):
            problems.append(f"cli.py:{node.lineno} writes the environment")
        if isinstance(node, ast.Call) and ast.unparse(node.func) in {"frontend.mode", "frontend.is_app",
                                                                     "frontend.check_applet"}:
            if ast.unparse(node.func) == "frontend.mode" and (node.args or node.keywords):
                problems.append(f"cli.py:{node.lineno} frontend.mode() takes nothing from argv")
            elif ast.unparse(node.func) != "frontend.mode":
                problems.append(f"cli.py:{node.lineno} asks the front end only through frontend.mode()")
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and ast.unparse(node.func) == "frontend.mode"]
    if len(calls) != 1:
        problems.append(f"cli.py asks frontend.mode() exactly once, found {len(calls)}")
    for node in ast.walk(ast.parse(frontend_source)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            if any(name.split(".")[0] in {"sys", "argparse", "subprocess"} for name in names):
                problems.append(f"frontend.py:{node.lineno} imports {names}")
        if isinstance(node, ast.Attribute) and node.attr in {"argv", "orig_argv", "putenv", "environb"}:
            problems.append(f"frontend.py:{node.lineno} uses .{node.attr}")
        if isinstance(node, ast.Name) and node.id in {"argv", "open", "eval", "exec", "__import__"}:
            problems.append(f"frontend.py:{node.lineno} uses {node.id}")
    return problems


def test_argv_never_chooses_the_front_end():
    assert argv_switch_problems(CLI_PY.read_text(encoding="utf-8"), FRONTEND_PY.read_text(encoding="utf-8")) == []


def test_no_option_chooses_the_front_end(capsys):
    for argv in (["--frontend", "app", "--catalog"], ["--frontend=app", "--catalog"], ["--app", "--catalog"],
                 ["--askpass", "/tmp/x", "--catalog"]):
        with pytest.raises(SystemExit) as raised:
            cli.main(argv)
        assert raised.value.code == 2
    assert capsys.readouterr().out == ""


ARGV_MUTATIONS = [
    (CLI_PY, '    result.add_argument("--version", action="version", version=__version__)\n',
     '    result.add_argument("--frontend", choices=("plasma", "app"))\n'
     '    result.add_argument("--version", action="version", version=__version__)\n'),
    (CLI_PY, "        return frontend.mode()\n", '        return frontend.mode({"HEARTHWIRE_FRONTEND": "app"})\n'),
    (CLI_PY, "    current = _frontend()\n",
     '    os.environ["HEARTHWIRE_FRONTEND"] = "app"\n    current = _frontend()\n'),
    (CLI_PY, "    current = _frontend()\n", '    os.putenv("HEARTHWIRE_FRONTEND", "app")\n    current = _frontend()\n'),
    (CLI_PY, "    current = _frontend()\n",
     '    os.environ.setdefault("HEARTHWIRE_FRONTEND", "app")\n    current = _frontend()\n'),
    (CLI_PY, "    current = _frontend()\n", "    current = frontend.APP if frontend.is_app() else _frontend()\n"),
    (FRONTEND_PY, "import os\n", "import os\nimport sys\n"),
    (FRONTEND_PY, "    value = values.get(VARIABLE)\n",
     "    value = values.get(VARIABLE) or __import__(\"sys\").argv[-1]\n"),
]


@pytest.mark.parametrize(("path", "old", "new"), ARGV_MUTATIONS)
def test_proof_the_argv_rule_catches(path, old, new):
    sources = {CLI_PY: CLI_PY.read_text(encoding="utf-8"), FRONTEND_PY: FRONTEND_PY.read_text(encoding="utf-8")}
    assert old in sources[path]
    sources[path] = sources[path].replace(old, new, 1)
    assert argv_switch_problems(sources[CLI_PY], sources[FRONTEND_PY])


# --- the reserved id, both ways -----------------------------------------------------------------------


def test_the_reserved_id_is_two_to_the_31():
    assert frontend.APP_APPLET_ID == 2147483648 == cli.MAX_INT_ARGUMENT == usagehistory.MAX_APPLET


def applet_problems(module):
    problems = []
    for applet in (1, 7, 2147483647, APP_ID - 1):
        if module.applet_allowed(applet, "app"):
            problems.append(f"app mode takes {applet}")
        if not module.applet_allowed(applet, "plasma"):
            problems.append(f"plasma mode refuses {applet}")
    if not module.applet_allowed(APP_ID, "app"):
        problems.append("app mode refuses its id")
    if module.applet_allowed(APP_ID, "plasma"):
        problems.append("plasma mode takes the app's id")
    return problems


def test_the_id_rule_both_ways():
    assert applet_problems(frontend) == []


@pytest.mark.parametrize(("old", "new"), [
    ("        return applet == APP_APPLET_ID\n", "        return True\n"),
    ("        return applet == APP_APPLET_ID\n", "        return applet >= 1\n"),
    ("    return applet != APP_APPLET_ID\n", "    return True\n"),
    ("    if current == APP:\n", "    if current == PLASMA:\n"),
    ("APP_APPLET_ID = 2**31\n", "APP_APPLET_ID = 2**31 - 1\n"),
])
def test_proof_the_id_rule_catches(old, new):
    assert applet_problems(mutant(frontend, old, new))


# Every --applet command, with a Plasma id and the app's.
APPLET_COMMANDS = [
    ["--usage-history", "read", "--applet", "{id}"],
    ["--usage-history", "record", "--applet", "{id}", "--sample", "claude.session=5"],
    ["--usage-history", "clear", "--applet", "{id}"],
    ["--settings-backup", "status", "--applet", "{id}"],
    ["--settings-backup", "export", "--applet", "{id}"],
    ["--settings-backup", "import", "--applet", "{id}"],
    ["--web-data", "prepare", "--store", "encrypted", "--applet", "{id}", "--generation", "0"],
    ["--web-data", "prune", "--store", "encrypted", "--applet", "{id}", "--generation", "0", "--known", "claude"],
    ["--web-data", "remove-site", "--store", "encrypted", "--applet", "{id}", "--generation", "0", "--site", "claude"],
    ["--web-data", "remove", "--store", "encrypted", "--applet", "{id}"],
]


def refused_ids(main, capsys, homes, monkeypatch):
    """[(front end, command, id)] that main() did NOT refuse as applet-not-found, or that left files."""
    found = []
    for current, refused in (("plasma", APP_ID), ("app", 7), ("app", 1), ("app", 2147483647)):
        if current == "app":
            monkeypatch.setenv("HEARTHWIRE_FRONTEND", "app")
        else:
            monkeypatch.delenv("HEARTHWIRE_FRONTEND", raising=False)
        for command in APPLET_COMMANDS:
            argv = [part.format(id=refused) for part in command]
            assert main(argv) == 0
            out = json.loads(capsys.readouterr().out)
            if out != {"ok": False, "error": "applet-not-found"} or tree(homes) != ["config", "data", "home", "state"]:
                found.append((current, command[1], refused))
    return found


def test_each_front_end_refuses_the_others_ids(homes, capsys, monkeypatch):
    assert refused_ids(cli.main, capsys, homes, monkeypatch) == []


def test_each_front_end_takes_its_own_ids(homes, capsys, monkeypatch):
    sample = ["--sample", "claude.session=5"]
    assert cli_run(capsys, "--usage-history", "record", "--applet", "7", *sample)["ok"] is True
    monkeypatch.setenv("HEARTHWIRE_FRONTEND", "app")
    assert cli_run(capsys, "--usage-history", "record", "--applet", str(APP_ID), *sample)["ok"] is True
    files = sorted(path.name for path in (homes / "data" / "hearthwire" / "usage-history").iterdir())
    assert files == ["applet-2147483648.json", "applet-7.json", "history.lock"]
    assert cli_run(capsys, "--settings-backup", "status", "--applet", str(APP_ID)) == {"ok": True, "exists": False}


@pytest.mark.parametrize(("old", "new"), [
    ("    elif args.applet is not None and not frontend.applet_allowed(args.applet, current):\n",
     "    elif False:\n"),
    ("    elif args.applet is not None and not frontend.applet_allowed(args.applet, current):\n",
     "    elif args.applet is not None and not frontend.applet_allowed(args.applet, frontend.PLASMA):\n"),
    ("    elif args.applet is not None and not frontend.applet_allowed(args.applet, current):\n",
     "    elif args.usage_history is None and args.applet is not None and not frontend.applet_allowed(args.applet, current):\n"),
])
def test_proof_the_cli_id_rule_catches(homes, capsys, monkeypatch, old, new):
    cli_layer_only(monkeypatch)
    assert refused_ids(mutant(cli, old, new).main, capsys, homes, monkeypatch)


def cli_layer_only(monkeypatch):
    """Turn the modules' own id checks off, so a proof shows what cli.py alone refuses."""
    def allow(*args, **kwargs):
        return None

    monkeypatch.setattr(frontend, "check_applet", allow)  # webdata imports it when run.
    monkeypatch.setattr(usagehistory, "check_applet", allow)
    monkeypatch.setattr(usagehistory, "is_app", lambda environ=None: False)
    monkeypatch.setattr(settingsbackup, "check_applet", allow)


# --- the modules refuse the other front end's id by themselves (fix round 1, I1) ---------------------


def module_id_problems(history, web, homes, monkeypatch):
    """usagehistory.run and webdata.run refuse the other front end's ids without cli.py."""
    problems = []
    for current, refused in (("plasma", APP_ID), ("app", 7), ("app", 2147483647)):
        if current == "app":
            monkeypatch.setenv("HEARTHWIRE_FRONTEND", "app")
        else:
            monkeypatch.delenv("HEARTHWIRE_FRONTEND", raising=False)
        calls = {
            "history read": lambda: history.run("read", applet=refused),
            "history record": lambda: history.run("record", applet=refused, sample="claude.session=5"),
            "history clear": lambda: history.run("clear", applet=refused),
            "web-data prepare": lambda: web.run("prepare", "encrypted", refused, generation=0),
            "web-data remove": lambda: web.run("remove", "encrypted", refused),
        }
        for name, call in calls.items():
            try:
                result = call()
            except Exception as error:  # noqa: BLE001 - a mutant may fail any way; that is a miss too.
                result = f"raised {type(error).__name__}"
            if result != {"ok": False, "error": "applet-not-found"}:
                problems.append(f"{current} {name} {refused}: {result}")
    if tree(homes) != ["config", "data", "home", "state"]:
        problems.append(f"files made: {tree(homes)}")
    return problems


def test_usage_history_and_web_data_refuse_the_other_ids_by_themselves(homes, monkeypatch):
    assert module_id_problems(usagehistory, webdata, homes, monkeypatch) == []


def test_a_bad_front_end_reaches_no_module_either(homes, monkeypatch):
    monkeypatch.setenv("HEARTHWIRE_FRONTEND", "nonsense")
    assert usagehistory.run("read", applet=7) == {"ok": False, "error": "bad-frontend"}
    assert usagehistory.run("clear", every_applet=True) == {"ok": False, "error": "bad-frontend"}
    assert webdata.run("remove", "encrypted", 7) == {"ok": False, "error": "bad-frontend"}
    assert tree(homes) == ["config", "data", "home", "state"]


@pytest.mark.parametrize(("module", "old", "new"), [
    (usagehistory, "            check_applet(applet, environ)  # type: ignore[arg-type]\n", "            pass\n"),
    (webdata, "        check_applet(applet, environ)\n", "        pass\n"),
])
def test_proof_the_module_id_rule_catches(homes, monkeypatch, module, old, new):
    copy = mutant(module, old, new)
    history, web = (copy, webdata) if module is usagehistory else (usagehistory, copy)
    assert module_id_problems(history, web, homes, monkeypatch)


# --- --migrate and --usage-history clear --all in app mode (fix round 1, L1 and L3) ---------------------


def migrate_problems(main, capsys, homes, monkeypatch):
    """App mode refuses --migrate with bad-frontend and exit 2, before legacy.py runs; Plasma mode runs it."""
    problems = []
    ran = []
    monkeypatch.setattr(cli.legacy, "run_operation", lambda operation, environ=None: ran.append(operation) or {"ok": True})
    monkeypatch.setenv("HEARTHWIRE_FRONTEND", "app")
    for operation in cli.legacy.OPERATIONS:
        code = main(["--migrate", operation])
        out = capsys.readouterr().out
        if code != 2 or out != '{"ok":false,"error":"bad-frontend"}\n':
            problems.append(f"app --migrate {operation}: {code} {out.strip()}")
    if ran:
        problems.append(f"legacy ran {ran} in app mode")
    monkeypatch.delenv("HEARTHWIRE_FRONTEND")
    if main(["--migrate", "status"]) != 0 or json.loads(capsys.readouterr().out) != {"ok": True} or ran != ["status"]:
        problems.append("plasma --migrate status does not run")
    if tree(homes) != ["config", "data", "home", "state"]:
        problems.append(f"files made: {tree(homes)}")
    return problems


def test_app_mode_never_migrates(homes, capsys, monkeypatch):
    assert migrate_problems(cli.main, capsys, homes, monkeypatch) == []


@pytest.mark.parametrize(("old", "new"), [
    ("    refused = current is None or (current == frontend.APP and args.migrate is not None)\n",
     "    refused = current is None\n"),
    ("    refused = current is None or (current == frontend.APP and args.migrate is not None)\n",
     "    refused = current is None or (current == frontend.PLASMA and args.migrate is not None)\n"),
    ("    if refused:\n        return 2\n", "    if current is None:\n        return 2\n"),
])
def test_proof_the_migrate_rule_catches(homes, capsys, monkeypatch, old, new):
    assert migrate_problems(mutant(cli, old, new).main, capsys, homes, monkeypatch)


# legacy.run_operation refuses app mode by itself (task 011b, N3): with cli.py's
# own refusal switched off, --migrate still reaches no handler outside Plasma mode.
CLI_REFUSAL_OFF = ("    refused = current is None or (current == frontend.APP and args.migrate is not None)\n",
                   "    refused = False\n")


def legacy_problems(module, call, homes, monkeypatch):
    """App mode and a bad value are bad-frontend before any handler runs; Plasma mode runs it."""
    problems = []
    ran = []
    for operation in module.OPERATIONS:
        monkeypatch.setitem(module._HANDLERS, operation,
                            lambda environ=None, operation=operation: ran.append(operation) or {"ok": True})
    for value in ("app", "nonsense", ""):
        monkeypatch.setenv("HEARTHWIRE_FRONTEND", value)
        for operation in module.OPERATIONS:
            try:
                result = call(operation)
            except Exception as error:  # noqa: BLE001 - a mutant may fail any way; that is a miss too.
                result = f"raised {type(error).__name__}"
            if result != {"ok": False, "error": "bad-frontend"}:
                problems.append(f"{value!r} --migrate {operation}: {result}")
    if ran:
        problems.append(f"legacy ran {ran} outside Plasma mode")
    for value in (None, "plasma"):
        if value is None:
            monkeypatch.delenv("HEARTHWIRE_FRONTEND")
        else:
            monkeypatch.setenv("HEARTHWIRE_FRONTEND", value)
        ran.clear()
        if call("status") != {"ok": True} or ran != ["status"]:
            problems.append(f"plasma ({value!r}) --migrate status does not run")
    if tree(homes) != ["config", "data", "home", "state"]:
        problems.append(f"files made: {tree(homes)}")
    return problems


def through_cli_alone(module, capsys):
    """cli.main without its own --migrate refusal, running ``module`` as legacy."""
    copy = mutant(cli, *CLI_REFUSAL_OFF)
    copy.legacy = module

    def call(operation):
        assert copy.main(["--migrate", operation]) == 0
        return json.loads(capsys.readouterr().out)

    return call


def test_legacy_refuses_app_mode_by_itself(homes, monkeypatch):
    assert legacy_problems(legacy, legacy.run_operation, homes, monkeypatch) == []


def legacy_environ_problems(module, homes, monkeypatch):
    """run_operation asks the front end of its ``environ`` argument, not of os.environ (review-3 L1)."""
    problems = []
    ran = []
    for operation in module.OPERATIONS:
        monkeypatch.setitem(module._HANDLERS, operation,
                            lambda environ=None, operation=operation: ran.append(operation) or {"ok": True})
    monkeypatch.delenv("HEARTHWIRE_FRONTEND", raising=False)
    for value in ("app", "nonsense", ""):
        for operation in module.OPERATIONS:
            try:
                result = module.run_operation(operation, {"HEARTHWIRE_FRONTEND": value})
            except Exception as error:  # noqa: BLE001 - a mutant may fail any way; that is a miss too.
                result = f"raised {type(error).__name__}"
            if result != {"ok": False, "error": "bad-frontend"}:
                problems.append(f"environ {value!r} --migrate {operation}: {result}")
    if ran:
        problems.append(f"legacy ran {ran} for an app or bad environ")
    monkeypatch.setenv("HEARTHWIRE_FRONTEND", "app")
    for environ in ({}, {"HEARTHWIRE_FRONTEND": "plasma"}):
        ran.clear()
        if module.run_operation("status", environ) != {"ok": True} or ran != ["status"]:
            problems.append(f"a Plasma environ {environ} does not run status")
    if tree(homes) != ["config", "data", "home", "state"]:
        problems.append(f"files made: {tree(homes)}")
    return problems


def test_legacy_asks_its_environ_argument(homes, monkeypatch):
    assert legacy_environ_problems(legacy, homes, monkeypatch) == []


def test_proof_the_legacy_environ_rule_catches(homes, monkeypatch):
    # mutant() asserts that the patch applies to legacy.py.
    copy = mutant(legacy, "        current: Optional[str] = frontend.mode(environ)\n",
                  "        current: Optional[str] = frontend.mode()\n")
    assert legacy_environ_problems(copy, homes, monkeypatch)


def test_legacy_refuses_app_mode_without_the_cli_layer(homes, capsys, monkeypatch):
    assert legacy_problems(legacy, through_cli_alone(legacy, capsys), homes, monkeypatch) == []


LEGACY_MUTATIONS = {
    "no module refusal": ('    if current != frontend.PLASMA:\n        return {"ok": False, "error": "bad-frontend"}\n', ""),
    "only app mode refused": ("    if current != frontend.PLASMA:\n        return {\"ok\": False",
                              "    if current == frontend.APP:\n        return {\"ok\": False"),
    "a bad value taken as Plasma": ("    except HelperError:\n        current = None\n    if current",
                                    "    except HelperError:\n        current = frontend.PLASMA\n    if current"),
    "refused after the handler": ("    try:\n        current: Optional[str] = frontend.mode(environ)\n",
                                  "    handler(environ)\n    try:\n        current: Optional[str] = frontend.mode(environ)\n"),
}


@pytest.mark.parametrize("name", sorted(LEGACY_MUTATIONS))
def test_proof_the_legacy_rule_catches(homes, capsys, monkeypatch, name):
    copy = mutant(legacy, *LEGACY_MUTATIONS[name])
    assert legacy_problems(copy, copy.run_operation, homes, monkeypatch)
    assert legacy_problems(copy, through_cli_alone(copy, capsys), homes, monkeypatch)


def clear_all_problems(main, capsys, homes, monkeypatch):
    """App mode refuses clear --all; a widget's applet-7.json survives; Plasma mode still clears every file."""
    problems = []
    sample = ["--sample", "claude.session=5"]
    history = homes / "data" / "hearthwire" / "usage-history"
    assert cli_run(capsys, "--usage-history", "record", "--applet", "7", *sample)["ok"] is True
    monkeypatch.setenv("HEARTHWIRE_FRONTEND", "app")
    assert cli_run(capsys, "--usage-history", "record", "--applet", str(APP_ID), *sample)["ok"] is True
    main(["--usage-history", "clear", "--all"])
    if json.loads(capsys.readouterr().out) != {"ok": False, "error": "applet-not-found"}:
        problems.append("app mode clear --all is not applet-not-found")
    names = sorted(path.name for path in history.iterdir()) if history.exists() else []
    if "applet-7.json" not in names or "applet-2147483648.json" not in names:
        problems.append(f"app mode clear --all deleted history: {names}")
    if main(["--usage-history", "clear", "--applet", str(APP_ID)]) != 0 or \
            json.loads(capsys.readouterr().out).get("ok") is not True:
        problems.append("app mode cannot clear its own history")
    names = sorted(path.name for path in history.iterdir()) if history.exists() else []
    if "applet-2147483648.json" in names or "applet-7.json" not in names:
        problems.append(f"clear --applet {APP_ID} left {names}")
    monkeypatch.delenv("HEARTHWIRE_FRONTEND")
    main(["--usage-history", "clear", "--all"])
    if json.loads(capsys.readouterr().out).get("ok") is not True or (
            history.exists() and any(path.name.startswith("applet-") for path in history.iterdir())):
        problems.append("plasma clear --all does not clear")
    return problems


def test_app_mode_never_clears_every_widgets_history(homes, capsys, monkeypatch):
    assert clear_all_problems(cli.main, capsys, homes, monkeypatch) == []


@pytest.mark.parametrize(("old", "new"), [
    ("    elif current == frontend.APP and args.all_applets:\n", "    elif False:\n"),
    ("    elif current == frontend.APP and args.all_applets:\n", "    elif current == frontend.PLASMA and args.all_applets:\n"),
])
def test_proof_the_cli_clear_all_rule_catches(homes, capsys, monkeypatch, old, new):
    cli_layer_only(monkeypatch)  # Else usagehistory.run's own check hides the cli gap.
    assert clear_all_problems(mutant(cli, old, new).main, capsys, homes, monkeypatch)


def module_clear_all_problems(history, homes, monkeypatch):
    """usagehistory.run refuses clear --all in app mode by itself (not only through cli.py)."""
    problems = []
    assert usagehistory.run("record", applet=7, sample="claude.session=5")["ok"] is True
    monkeypatch.setenv("HEARTHWIRE_FRONTEND", "app")
    if history.run("clear", every_applet=True) != {"ok": False, "error": "applet-not-found"}:
        problems.append("app mode clear --all is not applet-not-found")
    if not (homes / "data" / "hearthwire" / "usage-history" / "applet-7.json").exists():
        problems.append("the widget's history is gone")
    return problems


def test_usage_history_refuses_clear_all_in_app_mode_by_itself(homes, monkeypatch):
    assert module_clear_all_problems(usagehistory, homes, monkeypatch) == []


def test_proof_the_module_clear_all_rule_catches(homes, monkeypatch):
    copy = mutant(usagehistory, '            if is_app(environ):\n                raise HelperError("applet-not-found")\n',
                  "            pass\n")
    assert module_clear_all_problems(copy, homes, monkeypatch)
