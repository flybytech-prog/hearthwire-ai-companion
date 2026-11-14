"""The helper takes only full option names (006 SEC INFO-A), and every caller spells them out.

argparse would otherwise read `--addr` as `--address` or `--port-own` as
`--port-owner`. The widget's commands and the install and packaging scripts
are scanned for every helper option they use; each must be a full name.
"""

import re
from pathlib import Path

import pytest

from hearthwire import cli
from hearthwire.core import portowner

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "plasmoid" / "contents" / "ui"
SCRIPT_DIRS = (ROOT / "scripts", ROOT / "packaging")
# Options the widget's texts name that belong to other programs, not the helper.
FOREIGN_OPTIONS = {
    "--needed": "pacman -S --needed, in the install hint for Arch",
    "--remove-script-install": "scripts/install.sh, named in the update notice",
    "--restart-plasma": "scripts/install.sh, named in the update notice",
}
_OPTION = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")
_STRING = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'')


def helper_options():
    return {option for action in cli.parser()._actions for option in action.option_strings if option.startswith("--")}


def widget_options():
    """{option: [file:line]} for every --name inside a string literal of the widget's code."""
    found = {}
    for path in sorted(UI.glob("*.qml")) + sorted(UI.glob("*.js")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for literal in _STRING.findall(line):
                for option in _OPTION.findall(literal):
                    found.setdefault(option, []).append(f"{path.name}:{number}")
    return found


def script_options():
    """{option: [file:line]} for every --name after `-m hearthwire` in the scripts and packaging."""
    found = {}
    for folder in SCRIPT_DIRS:
        for path in sorted(item for item in folder.rglob("*") if item.is_file()):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                for command in re.findall(r"-m\s+hearthwire\b([^;|&)\n]*)", line):
                    for option in _OPTION.findall(command):
                        found.setdefault(option, []).append(f"{path.relative_to(ROOT)}:{number}")
    return found


def test_the_widget_sends_only_full_option_names():
    found = widget_options()
    # The helper commands are there: the scan sees them.
    assert {"--port-owner", "--address", "--web-data", "--vault", "--settings-backup", "--usage-history",
            "--install-info", "--read-dropped", "--prompts"} <= set(found)
    unknown = {option: where for option, where in found.items()
               if option not in helper_options() and option not in FOREIGN_OPTIONS}
    assert unknown == {}


def test_the_scripts_call_the_helper_with_full_option_names():
    found = script_options()
    assert {"--catalog", "--usage-history", "--web-data", "--vault", "--version"} <= set(found)
    unknown = {option: where for option, where in found.items() if option not in helper_options()}
    assert unknown == {}


def test_the_foreign_options_are_not_helper_options():
    assert not set(FOREIGN_OPTIONS) & helper_options()


@pytest.mark.parametrize("argv", [
    ["--port-owner", "3000", "--addr", "192.168.1.20"], ["--port-own", "3000"], ["--port", "3000"],
    ["--port-owner", "3000", "--address=192.168.1.20", "--add", "10.0.0.1"], ["--det"], ["--cat"], ["--js"],
    ["--install"], ["--settings", "status"], ["--usage", "read", "--applet", "1"], ["--vau", "status"],
    ["--web", "purge"], ["--read", "00"], ["--prom", "list"], ["--provider=claude"],
])
def test_an_abbreviated_option_exits_2_and_runs_nothing(monkeypatch, capsys, argv):
    monkeypatch.setattr(portowner, "run", lambda *args, **kwargs: pytest.fail("must not run"))
    monkeypatch.setattr(cli, "collect_snapshot", lambda **kwargs: pytest.fail("must not collect"))
    monkeypatch.setattr(cli, "catalog_snapshot", lambda: pytest.fail("must not print the catalog"))
    monkeypatch.setattr(cli, "detect_snapshot", lambda: pytest.fail("must not detect"))
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unrecognized arguments" in captured.err


def test_every_abbreviation_here_would_have_matched_one_option():
    """So the test above shows allow_abbrev=False at work, not unknown words."""
    options = helper_options()
    for word in ("--addr", "--port-own", "--det", "--cat", "--js", "--install", "--settings", "--usage", "--vau",
                 "--web", "--read", "--prom", "--provider"):
        assert len([option for option in options if option.startswith(word)]) == 1, word


def test_full_names_and_the_equals_form_still_work(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(portowner, "run", lambda *args, **kwargs: seen.append((args, kwargs)) or {"ok": True, "owner": "none"})
    for argv in (["--port-owner", "3000"], ["--port-owner=3000", "--address=192.168.1.20"]):
        assert cli.main(argv) == 0
    assert seen == [((3000,), {}), ((3000,), {"address": "192.168.1.20"})]
    capsys.readouterr()
