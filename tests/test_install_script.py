"""scripts/install.sh: the notification events file (plan R1 T1.3).

The install path runs against a copy of the script and its assets in
``tmp_path``, with stub ``python3``, ``kpackagetool6`` and ``qtpaths6`` first on
PATH, so it never runs pip, never touches the real widget and never writes
outside the test's own HOME (the script deletes ``<checkout>/build``, which
here is the copy's).
"""

import configparser
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
INSTALL_SCRIPT = ROOT / "scripts" / "install.sh"
NOTIFYRC = ROOT / "assets" / "hearthwire.notifyrc"
REQUIRED_QML = (
    "QtQuick/Layouts", "QtQuick/Dialogs", "QtCore", "org/kde/kirigami", "org/kde/kcmutils",
    "org/kde/plasma/plasma5support", "org/kde/plasma/components", "org/kde/plasma/extras",
    "org/kde/plasma/plasmoid",
)

# Answers exactly the python3 calls the install path makes (all with -P);
# anything else exits 97.
PYTHON_STUB = """#!/bin/sh
case "$*" in
    "-P -c "*) exit 0 ;;
    "-P -m pip --version") exit 0 ;;
    "-P -m pip show ai-usage-kde") exit 1 ;;
    "-P -m pip install "*) exit 0 ;;
    "-P -m hearthwire --version") echo 0.0-test ;;
    *) exit 97 ;;
esac
"""
KPACKAGETOOL_STUB = """#!/bin/sh
case "$1 $2 $3" in
    "-t Plasma/Applet -s") exit 1 ;;
    "-t Plasma/Applet -i") exit 0 ;;
    *) exit 97 ;;
esac
"""


def _stub(directory, name, text):
    path = directory / name
    path.write_text(text)
    path.chmod(0o755)


def _copied_project(tmp_path):
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    shutil.copy2(INSTALL_SCRIPT, project / "scripts" / "install.sh")
    shutil.copytree(ROOT / "assets", project / "assets")
    (project / "plasmoid").mkdir()
    return project


def run_install(tmp_path, *, xdg_data_home=None, python_stub=PYTHON_STUB, cwd=None):
    project = _copied_project(tmp_path)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    qml = tmp_path / "qml"
    for module in REQUIRED_QML + ("QtWebEngine",):
        (qml / module).mkdir(parents=True, exist_ok=True)
    stubs = tmp_path / "stub-bin"
    stubs.mkdir(exist_ok=True)
    _stub(stubs, "python3", python_stub)
    _stub(stubs, "kpackagetool6", KPACKAGETOOL_STUB)
    _stub(stubs, "qtpaths6", f"#!/bin/sh\necho '{qml}'\n")
    env = {"PATH": f"{stubs}:/usr/bin:/bin", "HOME": str(home)}
    if xdg_data_home is not None:
        env["XDG_DATA_HOME"] = str(xdg_data_home)
    completed = subprocess.run(
        ["sh", str(project / "scripts" / "install.sh")],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=60, check=False,
        cwd=cwd,
    )
    return completed, home


def test_notifyrc_declares_the_component_and_both_alert_events():
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(NOTIFYRC.read_text(encoding="utf-8"))
    assert {section: dict(parser[section]) for section in parser.sections()} == {
        "Global": {"IconName": "hearthwire", "Comment": "Hearthwire"},
        "Event/usageLow": {"Name": "Plan running low", "Action": "Popup"},
        "Event/usageReset": {"Name": "Plan reset", "Action": "Popup"},
    }


def test_install_script_passes_sh_n():
    completed = subprocess.run(["sh", "-n", str(INSTALL_SCRIPT)], capture_output=True, text=True, check=False)
    assert (completed.returncode, completed.stderr) == (0, "")


def test_every_python3_call_keeps_the_working_folder_off_sys_path():
    calls = re.findall(r"\bpython3 +-[^\n]*", INSTALL_SCRIPT.read_text(encoding="utf-8"))
    assert len(calls) >= 7
    assert [call for call in calls if not call.startswith("python3 -P ")] == []


# A planted module writes a marker; the safe fake pip (on PYTHONPATH, which -P
# keeps) answers the installer's pip calls and imports json like real pip does.
PLANTED = "open({marker!r}, 'a').write({name!r} + '\\n')\nraise SystemExit(0)\n"
FAKE_PIP = """import json, sys
args = sys.argv[1:]
with open({log!r}, "a") as handle:
    handle.write(json.dumps(args) + "\\n")
sys.exit(1 if args[:1] == ["show"] else 0)
"""


def test_modules_planted_in_the_working_folder_never_run(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    marker = tmp_path / "planted-ran"
    for name in ("pip", "json"):
        (work / f"{name}.py").write_text(PLANTED.format(marker=str(marker), name=name))
    fake = tmp_path / "fake-site" / "pip"
    fake.mkdir(parents=True)
    (fake / "__init__.py").write_text("")
    pip_log = tmp_path / "pip-calls"
    (fake / "__main__.py").write_text(FAKE_PIP.format(log=str(pip_log)))
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "PYTHONPATH": str(fake.parent),
           "PYTHONDONTWRITEBYTECODE": "1"}
    # The plant works: without -P the working folder's pip.py runs.
    subprocess.run([sys.executable, "-m", "pip", "--version"], cwd=work, env=env,
                   stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=False)
    assert marker.read_text() == "pip\n"
    marker.unlink()
    # The real interpreter, with the fake pip on PYTHONPATH; only the final
    # "hearthwire --version" is answered by the stub (the copy has no src/).
    wrapper = (
        "#!/bin/sh\n"
        'if [ "$*" = "-P -m hearthwire --version" ]; then echo 0.0-test; exit 0; fi\n'
        f"PYTHONPATH='{fake.parent}' PYTHONDONTWRITEBYTECODE=1 exec '{sys.executable}' \"$@\"\n"
    )
    completed, _ = run_install(tmp_path, python_stub=wrapper, cwd=work)
    assert completed.returncode == 0, completed.stderr
    assert not marker.exists()
    calls = [line for line in pip_log.read_text().splitlines()]
    assert calls[:2] == ['["--version"]', '["show", "ai-usage-kde"]']
    assert calls[2].startswith('["install", "--user"')
    assert len(calls) == 3


def test_install_copies_the_notifyrc_with_mode_0644(tmp_path):
    completed, home = run_install(tmp_path)
    assert completed.returncode == 0, completed.stderr
    installed = home / ".local" / "share" / "knotifications6" / "hearthwire.notifyrc"
    assert installed.read_bytes() == NOTIFYRC.read_bytes()
    assert stat.S_IMODE(installed.stat().st_mode) == 0o644
    assert not installed.is_symlink()


def test_install_honours_xdg_data_home(tmp_path):
    data = tmp_path / "data"
    completed, home = run_install(tmp_path, xdg_data_home=data)
    assert completed.returncode == 0, completed.stderr
    assert (data / "knotifications6" / "hearthwire.notifyrc").read_bytes() == NOTIFYRC.read_bytes()
    assert not (home / ".local" / "share" / "knotifications6").exists()


@pytest.mark.parametrize("old_mode", [0o600, 0o666])
def test_install_replaces_an_old_copy_and_resets_its_mode(tmp_path, old_mode):
    directory = tmp_path / "home" / ".local" / "share" / "knotifications6"
    directory.mkdir(parents=True)
    (directory / "hearthwire.notifyrc").write_text("[Global]\n")
    (directory / "hearthwire.notifyrc").chmod(old_mode)
    completed, _ = run_install(tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert (directory / "hearthwire.notifyrc").read_bytes() == NOTIFYRC.read_bytes()
    assert stat.S_IMODE((directory / "hearthwire.notifyrc").stat().st_mode) == 0o644


def test_install_replaces_a_settings_icon_symlink_instead_of_writing_through_it(tmp_path):
    target = tmp_path / "precious"
    target.write_text("keep")
    directory = tmp_path / "home" / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps"
    directory.mkdir(parents=True)
    (directory / "hearthwire-settings-general.svg").symlink_to(target)
    completed, _ = run_install(tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert target.read_text() == "keep"
    assert not (directory / "hearthwire-settings-general.svg").is_symlink()
    assert (directory / "hearthwire-settings-general.svg").read_bytes() == \
        (ROOT / "assets" / "hearthwire-settings-general.svg").read_bytes()


def test_install_replaces_an_app_icon_symlink_instead_of_writing_through_it(tmp_path):
    target = tmp_path / "precious"
    target.write_text("keep")
    directory = tmp_path / "home" / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps"
    directory.mkdir(parents=True)
    (directory / "hearthwire.svg").symlink_to(target)
    completed, _ = run_install(tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert target.read_text() == "keep"
    assert not (directory / "hearthwire.svg").is_symlink()
    assert (directory / "hearthwire.svg").read_bytes() == (ROOT / "assets" / "hearthwire.svg").read_bytes()


def test_install_replaces_a_symlink_instead_of_writing_through_it(tmp_path):
    target = tmp_path / "precious"
    target.write_text("keep")
    directory = tmp_path / "home" / ".local" / "share" / "knotifications6"
    directory.mkdir(parents=True)
    (directory / "hearthwire.notifyrc").symlink_to(target)
    completed, _ = run_install(tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert target.read_text() == "keep"
    assert not (directory / "hearthwire.notifyrc").is_symlink()
    assert (directory / "hearthwire.notifyrc").read_bytes() == NOTIFYRC.read_bytes()


def test_install_writes_only_the_icons_and_the_notifyrc_under_home(tmp_path):
    completed, home = run_install(tmp_path)
    assert completed.returncode == 0, completed.stderr
    written = sorted(path.relative_to(home).as_posix() for path in home.rglob("*") if path.is_file())
    assert written == [
        ".local/share/icons/hicolor/scalable/apps/hearthwire-settings-ai.svg",
        ".local/share/icons/hicolor/scalable/apps/hearthwire-settings-chat.svg",
        ".local/share/icons/hicolor/scalable/apps/hearthwire-settings-general.svg",
        ".local/share/icons/hicolor/scalable/apps/hearthwire.svg",
        ".local/share/knotifications6/hearthwire.notifyrc",
    ]
    assert sorted(os.listdir(tmp_path / "project")) == ["assets", "plasmoid", "scripts"]


# --- --uninstall-web-data: the icons ------------------------------------------------------------

ICON_NAMES = ("hearthwire.svg", "hearthwire-settings-general.svg", "hearthwire-settings-ai.svg",
              "hearthwire-settings-chat.svg")


HISTORY_CLEARED = '{"ok":true}'


def run_uninstall(tmp_path, reply_text, history_reply=HISTORY_CLEARED, *, extra_env=None):
    """--uninstall-web-data with a python3 stub: ``reply_text`` answers --web-data purge,
    ``history_reply`` answers --usage-history clear; every call is logged to tmp_path/helper-calls."""
    project = _copied_project(tmp_path)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    stubs = tmp_path / "stub-bin"
    stubs.mkdir(exist_ok=True)
    log = tmp_path / "helper-calls"
    _stub(stubs, "python3", (
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> '{log}'\n"
        'case "$*" in\n'
        f"    '-P -m hearthwire --web-data purge') printf '%s\\n' '{reply_text}' ;;\n"
        f"    '-P -m hearthwire --usage-history clear') printf '%s\\n' '{history_reply}' ;;\n"
        "    *) exit 97 ;;\n"
        "esac\n"
    ))
    env = {"PATH": f"{stubs}:/usr/bin:/bin", "HOME": str(home)}
    env.update(extra_env or {})
    return subprocess.run(
        ["sh", str(project / "scripts" / "install.sh"), "--uninstall-web-data"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        env=env, timeout=60, check=False,
    )


def helper_calls(tmp_path):
    log = tmp_path / "helper-calls"
    return log.read_text().splitlines() if log.exists() else []


def _icon_directory(tmp_path):
    directory = tmp_path / "home" / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@pytest.mark.parametrize("reply_text", ['{"ok":true,"removed":[]}', '{"ok":true,"removed":["vault"]}'])
def test_uninstall_web_data_removes_the_icons_and_nothing_else(tmp_path, reply_text):
    directory = _icon_directory(tmp_path)
    for name in ICON_NAMES:
        (directory / name).write_text("<svg/>")
    neighbour = directory / "hearthwire-other.svg"
    neighbour.write_text("keep")
    completed = run_uninstall(tmp_path, reply_text)
    assert (completed.returncode, completed.stderr) == (0, "")
    assert sorted(os.listdir(directory)) == ["hearthwire-other.svg"]
    assert neighbour.read_text() == "keep"


def test_uninstall_web_data_removes_icon_symlinks_not_their_targets(tmp_path):
    directory = _icon_directory(tmp_path)
    targets = []
    for name in ICON_NAMES:
        target = tmp_path / f"precious-{name}"
        target.write_text("keep")
        (directory / name).symlink_to(target)
        targets.append(target)
    completed = run_uninstall(tmp_path, '{"ok":true,"removed":[]}')
    assert (completed.returncode, completed.stderr) == (0, "")
    assert os.listdir(directory) == []
    assert [target.read_text() for target in targets] == ["keep"] * len(ICON_NAMES)


def test_uninstall_web_data_keeps_the_icons_when_nothing_was_deleted(tmp_path):
    directory = _icon_directory(tmp_path)
    for name in ICON_NAMES:
        (directory / name).write_text("<svg/>")
    completed = run_uninstall(tmp_path, '{"ok":false,"error":"not-locked"}')
    assert completed.returncode == 1
    assert sorted(os.listdir(directory)) == sorted(ICON_NAMES)


# --- --uninstall-web-data: the usage history ----------------------------------------------------


@pytest.mark.parametrize("reply_text", ['{"ok":true,"removed":[]}', '{"ok":true,"removed":["vault"]}'])
def test_uninstall_web_data_clears_the_usage_history_after_the_purge(tmp_path, reply_text):
    completed = run_uninstall(tmp_path, reply_text)
    assert (completed.returncode, completed.stderr) == (0, "")
    assert helper_calls(tmp_path) == ["-P -m hearthwire --web-data purge", "-P -m hearthwire --usage-history clear"]


@pytest.mark.parametrize("reply_text", ['{"ok":false,"error":"not-locked"}', '{"ok":false,"error":"busy"}',
                                        '{"ok":false,"error":"symlink"}', "garbage"])
def test_uninstall_web_data_keeps_the_history_when_the_purge_failed(tmp_path, reply_text):
    completed = run_uninstall(tmp_path, reply_text)
    assert completed.returncode == 1
    assert helper_calls(tmp_path) == ["-P -m hearthwire --web-data purge"]


@pytest.mark.parametrize("history_reply", ['{"ok":false,"error":"busy"}', '{"ok":false,"error":"symlink"}',
                                           '{"ok":true,"x":1}', ""])
def test_uninstall_web_data_fails_and_keeps_the_icons_when_the_history_stays(tmp_path, history_reply):
    directory = _icon_directory(tmp_path)
    for name in ICON_NAMES:
        (directory / name).write_text("<svg/>")
    completed = run_uninstall(tmp_path, '{"ok":true,"removed":[]}', history_reply)
    assert completed.returncode == 1
    assert "usage history" in completed.stderr
    assert sorted(os.listdir(directory)) == sorted(ICON_NAMES)


def test_uninstall_web_data_really_deletes_the_history_folder(tmp_path):
    """The real helper from the copied checkout clears it; only the purge is stubbed."""
    project = _copied_project(tmp_path)
    shutil.copytree(ROOT / "src", project / "src", ignore=shutil.ignore_patterns("__pycache__"))
    home = tmp_path / "home"
    data = tmp_path / "data"
    history = data / "hearthwire" / "usage-history"
    history.mkdir(parents=True)
    (history / "history.json").write_text('{"history_version":1,"series":[]}')
    (history / "history.lock").write_text("")
    home.mkdir()
    stubs = tmp_path / "stub-bin"
    stubs.mkdir()
    _stub(stubs, "python3", (
        "#!/bin/sh\n"
        'if [ "$*" = "-P -m hearthwire --web-data purge" ]; then echo \'{"ok":true,"removed":[]}\'; exit 0; fi\n'
        f"exec '{sys.executable}' \"$@\"\n"
    ))
    completed = subprocess.run(
        ["sh", str(project / "scripts" / "install.sh"), "--uninstall-web-data"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, check=False,
        env={"PATH": f"{stubs}:/usr/bin:/bin", "HOME": str(home), "XDG_DATA_HOME": str(data)},
    )
    assert (completed.returncode, completed.stderr) == (0, "")
    assert not history.exists()
    assert (data / "hearthwire").is_dir()
