"""scripts/install.sh: the notification events file (plan R1 T1.3) and the
one-time migration to the new name (plan R2).

The install path runs against a copy of the script and its assets in
``tmp_path``, with stub ``python3``, ``kpackagetool6``, ``qtpaths6``,
``systemctl``, ``kquitapp6`` and ``kstart`` first on PATH, so it never runs
pip, never stops or starts the real Plasma, never touches the real widget and
never writes outside the test's own HOME (the script deletes
``<checkout>/build``, which here is the copy's).
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
# >>> legacy-migration
OLD_PIP_PACKAGE = "hearthside"
# <<< legacy-migration

# Answers exactly the python3 calls the install path makes (all with -P);
# anything else exits 97.
PYTHON_STUB = """#!/bin/sh
case "$*" in
    "-P -c "*) exit 0 ;;
    "-P -m pip --version") exit 0 ;;
    "-P -m pip show "*) exit 1 ;;
    "-P -m pip install "*) exit 0 ;;
    "-P -m hearthwire --version") echo 0.0-test ;;
    "-P -m hearthwire --migrate status") echo '{"ok":true,"pending":[],"present":[]}' ;;
    *) exit 97 ;;
esac
"""
# Plasma must never be stopped or started by a test: these fail loudly.
PLASMA_STUB = "#!/bin/sh\necho \"unexpected $0 $*\" >&2\nexit 98\n"
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
    for name in ("systemctl", "kquitapp6", "kstart"):
        _stub(stubs, name, PLASMA_STUB)
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
        'if [ "$*" = "-P -m hearthwire --migrate status" ]; then echo \'{"ok":true,"pending":[],"present":[]}\'; exit 0; fi\n'
        f"PYTHONPATH='{fake.parent}' PYTHONDONTWRITEBYTECODE=1 exec '{sys.executable}' \"$@\"\n"
    )
    completed, _ = run_install(tmp_path, python_stub=wrapper, cwd=work)
    assert completed.returncode == 0, completed.stderr
    assert not marker.exists()
    calls = [line for line in pip_log.read_text().splitlines()]
    assert calls[:3] == ['["--version"]', f'["show", "{OLD_PIP_PACKAGE}"]', '["show", "ai-usage-kde"]']
    assert calls[3].startswith('["install", "--user"')
    assert len(calls) == 4


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


# >>> legacy-migration: the one-time move from Hearthside (plan R2) ---------------------------------

# A scripted helper: "--migrate OP" prints replies/OP.<n> for its n-th call (else
# replies/OP). pip, kpackagetool6, systemctl, kquitapp6 and kstart only log; a
# package counts as installed while state/pip-<name> or state/pkg-<id> exists.
FLOW_PYTHON = r"""#!/bin/sh
last=""
for argument in "$@"; do last=$argument; done
case "$*" in
    "-P -m hearthwire --migrate "*) printf 'helper %s PYTHONPATH=%s\n' "$last" "${PYTHONPATH:-}" >> "$FLOW_LOG" ;;
    "-P -m pip "*) printf 'pip %s\n' "$(shift 3; echo "$*")" >> "$FLOW_LOG" ;;
esac
case "$*" in
    "-P -c "*) exit 0 ;;
    "-P -m pip --version") exit 0 ;;
    "-P -m pip show "*) [ -e "$FLOW_STATE/pip-$last" ] ;;
    "-P -m pip uninstall "*) rm -f "$FLOW_STATE/pip-$last" ;;
    "-P -m pip install "*) exit "${FLOW_PIP_INSTALL_EXIT:-0}" ;;
    "-P -m hearthwire --version") echo 0.0-test ;;
    "-P -m hearthwire --migrate "*)
        op=$last
        n=$(cat "$FLOW_STATE/count-$op" 2>/dev/null || echo 0)
        n=$((n + 1))
        echo "$n" > "$FLOW_STATE/count-$op"
        if [ -e "$FLOW_REPLIES/$op.$n" ]; then cat "$FLOW_REPLIES/$op.$n"; else cat "$FLOW_REPLIES/$op"; fi
        ;;
    *) exit 97 ;;
esac
"""
FLOW_KPACKAGETOOL = r"""#!/bin/sh
printf 'kpackagetool6 %s %s\n' "$3" "${4##*/}" >> "$FLOW_LOG"
case "$3" in
    -s) [ -e "$FLOW_STATE/pkg-$4" ] ;;
    -r) rm -f "$FLOW_STATE/pkg-$4" ;;
    *) exit 0 ;;
esac
"""
FLOW_SYSTEMCTL = r"""#!/bin/sh
printf 'systemctl %s\n' "$*" >> "$FLOW_LOG"
case "$2" in
    is-active) [ -e "$FLOW_STATE/systemd" ] ;;
    *) exit 0 ;;
esac
"""
FLOW_LOGGER = "#!/bin/sh\nprintf '%s %s\\n' \"${0##*/}\" \"$*\" >> \"$FLOW_LOG\"\n"

NOTHING = '{"ok":true,"pending":[],"present":[]}'
PENDING = '{"ok":true,"pending":["data","config","notifyrc","cache","wallet-entry","applets"],"present":[]}'
RUN_DONE = '{"ok":true,"migrated":["data","config","notifyrc","cache","wallet-entry"],"pending":["applets"]}'
APPLETS_DONE = '{"ok":true,"migrated":["applets"],"pending":[]}'
COMPLETE = '{"ok":true,"pending":[],"present":["data","config","notifyrc","wallet-entry","applets"]}'
OLD_ID = "io.github.flybytechprog.hearthside"
NEW_ID = "io.github.flybytechprog.hearthwire"
OLD_FILES = ("icons/hicolor/scalable/apps/hearthside.svg",
             "icons/hicolor/scalable/apps/hearthside-settings-general.svg",
             "icons/hicolor/scalable/apps/hearthside-settings-ai.svg",
             "icons/hicolor/scalable/apps/hearthside-settings-chat.svg",
             "knotifications6/hearthside.notifyrc")
BACKUP = ".config/plasma-org.kde.plasma.desktop-appletsrc.hearthside-backup"


class Flow:
    def __init__(self, tmp_path):
        self.root = tmp_path
        self.project = _copied_project(tmp_path)
        self.home = tmp_path / "home"
        self.home.mkdir(exist_ok=True)
        self.state = tmp_path / "state"
        self.state.mkdir()
        self.replies = tmp_path / "replies"
        self.replies.mkdir()
        self.log = tmp_path / "flow.log"
        self.log.write_text("")
        qml = tmp_path / "qml"
        for module in REQUIRED_QML + ("QtWebEngine",):
            (qml / module).mkdir(parents=True, exist_ok=True)
        stubs = tmp_path / "stub-bin"
        stubs.mkdir(exist_ok=True)
        _stub(stubs, "python3", FLOW_PYTHON)
        _stub(stubs, "kpackagetool6", FLOW_KPACKAGETOOL)
        _stub(stubs, "systemctl", FLOW_SYSTEMCTL)
        _stub(stubs, "kquitapp6", FLOW_LOGGER)
        _stub(stubs, "kstart", FLOW_LOGGER)
        _stub(stubs, "qtpaths6", f"#!/bin/sh\necho '{qml}'\n")
        # Present, so no package offer ever asks; sudo and pacman would fail loudly.
        for name in ("gocryptfs", "kdialog", "fusermount3"):
            _stub(stubs, name, "#!/bin/sh\nexit 0\n")
        for name in ("sudo", "pacman"):
            _stub(stubs, name, PLASMA_STUB)
        self.env = {"PATH": f"{stubs}:/usr/bin:/bin", "HOME": str(self.home), "FLOW_LOG": str(self.log),
                    "FLOW_STATE": str(self.state), "FLOW_REPLIES": str(self.replies)}

    def reply(self, operation, text, call=None):
        (self.replies / (operation if call is None else f"{operation}.{call}")).write_text(text + "\n")

    def installed(self, *, pip=(), packages=()):
        for name in pip:
            (self.state / f"pip-{name}").write_text("")
        for name in packages:
            (self.state / f"pkg-{name}").write_text("")

    def old_files(self):
        for name in OLD_FILES:
            path = self.home / ".local" / "share" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("old")

    def run(self, *arguments, **extra):
        return subprocess.run(
            ["sh", str(self.project / "scripts" / "install.sh"), *arguments],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, env={**self.env, **extra},
            timeout=120, check=False,
        )

    def calls(self):
        return self.log.read_text().splitlines()

    def steps(self):
        """The calls that change something or matter for the order."""
        wanted = ("helper", "systemctl --user stop", "systemctl --user start", "kquitapp6", "kstart",
                  "pip uninstall", "pip install", "kpackagetool6 -r", "kpackagetool6 -i", "kpackagetool6 -u")
        return [call.split(" PYTHONPATH=")[0] for call in self.calls() if call.startswith(wanted)]


def test_every_helper_call_runs_from_the_checkout(tmp_path):
    flow = Flow(tmp_path)
    flow.reply("status", PENDING)
    flow.reply("run", RUN_DONE)
    flow.reply("applets", APPLETS_DONE)
    assert flow.run("--restart-plasma").returncode == 0
    helpers = [call for call in flow.calls() if call.startswith("helper ")]
    assert len(helpers) == 3
    assert all(call.endswith(f" PYTHONPATH={flow.project}/src") for call in helpers)
    script = INSTALL_SCRIPT.read_text(encoding="utf-8")
    assert re.findall(r"python3 -P -m hearthwire --migrate", script) == []


def test_nothing_to_move_never_stops_plasma(tmp_path):
    flow = Flow(tmp_path)
    flow.reply("status", NOTHING)
    completed = flow.run()
    assert completed.returncode == 0, completed.stderr
    assert flow.steps() == ["helper status", "pip install --user --upgrade --force-reinstall --break-system-packages "
                            f"{flow.project}", "kpackagetool6 -i plasmoid"]
    assert "Moved your Hearthside" not in completed.stdout


def test_a_pending_move_needs_restart_plasma_without_a_terminal(tmp_path):
    flow = Flow(tmp_path)
    flow.reply("status", PENDING)
    flow.installed(pip=["hearthside"], packages=[OLD_ID])
    flow.old_files()
    completed = flow.run()
    assert completed.returncode == 1
    assert "--restart-plasma" in completed.stderr and "Nothing was changed." in completed.stderr
    assert flow.steps() == ["helper status"]
    assert all((flow.home / ".local" / "share" / name).exists() for name in OLD_FILES)


@pytest.mark.parametrize("systemd", [True, False])
def test_the_move_runs_in_order_with_plasma_stopped(tmp_path, systemd):
    flow = Flow(tmp_path)
    if systemd:
        (flow.state / "systemd").write_text("")
    flow.reply("status", PENDING)
    flow.reply("run", RUN_DONE)
    flow.reply("applets", APPLETS_DONE)
    flow.installed(pip=["hearthside"], packages=[OLD_ID])
    flow.old_files()
    completed = flow.run("--restart-plasma")
    assert completed.returncode == 0, completed.stderr
    stop = ["systemctl --user stop plasma-plasmashell.service"] if systemd else ["kquitapp6 plasmashell"]
    start = ["systemctl --user start plasma-plasmashell.service"] if systemd else ["kstart plasmashell"]
    assert flow.steps() == [
        "helper status", *stop, "helper run", "helper applets",
        "pip uninstall -y --break-system-packages hearthside", f"kpackagetool6 -r {OLD_ID}",
        f"pip install --user --upgrade --force-reinstall --break-system-packages {flow.project}",
        "kpackagetool6 -i plasmoid", *start,
    ]
    assert not any((flow.home / ".local" / "share" / name).exists() for name in OLD_FILES)
    assert "Moved your Hearthside data, settings and widgets to Hearthwire." in completed.stdout
    assert "the next successful run of this installer deletes it" in completed.stdout
    assert "KDE Wallet key" not in completed.stdout


@pytest.mark.parametrize(("reply", "message"), [
    ('{"ok":false,"error":"not-locked"}', "Lock the encrypted chat folder"),
    ('{"ok":false,"error":"busy"}', "in use right now"),
    ('{"ok":false,"error":"conflict","category":"data"}', "hearthwire folder exist in"),
    ('{"ok":false,"error":"conflict","category":"config"}', "/.config; refusing to merge"),
    ('{"ok":false,"error":"symlink","category":"data"}', "symbolic link"),
    ('{"ok":false,"error":"invalid","category":"applets"}', "panel layout file"),
    ("garbage", "Could not move"),
])
def test_status_errors_stop_before_anything_changes(tmp_path, reply, message):
    flow = Flow(tmp_path)
    flow.reply("status", reply)
    flow.installed(pip=["hearthside"], packages=[OLD_ID])
    flow.old_files()
    completed = flow.run("--restart-plasma")
    assert completed.returncode == 1
    assert message in completed.stderr and "Nothing was changed." in completed.stderr
    assert flow.steps() == ["helper status"]
    assert all((flow.home / ".local" / "share" / name).exists() for name in OLD_FILES)


def test_a_failed_run_starts_plasma_again_and_installs_nothing(tmp_path):
    flow = Flow(tmp_path)
    (flow.state / "systemd").write_text("")
    flow.reply("status", PENDING)
    flow.reply("run", '{"ok":false,"error":"os-error","category":"config"}')
    flow.installed(pip=["hearthside"], packages=[OLD_ID])
    completed = flow.run("--restart-plasma")
    assert completed.returncode == 1
    assert "Finished steps are kept" in completed.stderr
    assert flow.steps() == ["helper status", "systemctl --user stop plasma-plasmashell.service", "helper run",
                            "systemctl --user start plasma-plasmashell.service"]


def test_failed_applets_start_plasma_again(tmp_path):
    flow = Flow(tmp_path)
    flow.reply("status", PENDING)
    flow.reply("run", RUN_DONE)
    flow.reply("applets", '{"ok":false,"error":"invalid","category":"applets"}')
    completed = flow.run("--restart-plasma")
    assert completed.returncode == 1
    assert "panel layout file" in completed.stderr
    assert flow.steps()[-1] == "kstart plasmashell"
    assert not any(step.startswith("pip install") for step in flow.steps())


def test_plasma_running_is_retried_until_plasmashell_is_gone(tmp_path):
    flow = Flow(tmp_path)
    flow.reply("status", PENDING)
    flow.reply("run", '{"ok":false,"error":"plasma-running"}', 1)
    flow.reply("run", '{"ok":false,"error":"plasma-running"}', 2)
    flow.reply("run", RUN_DONE)
    flow.reply("applets", APPLETS_DONE)
    completed = flow.run("--restart-plasma")
    assert completed.returncode == 0, completed.stderr
    assert [step for step in flow.steps() if step.startswith("helper")] == [
        "helper status", "helper run", "helper run", "helper run", "helper applets"]


def test_a_pending_wallet_key_is_reported(tmp_path):
    flow = Flow(tmp_path)
    flow.reply("status", PENDING)
    flow.reply("run", '{"ok":true,"migrated":["data","config","notifyrc","cache"],"pending":["wallet-entry","applets"]}')
    flow.reply("applets", '{"ok":true,"migrated":["applets"],"pending":["wallet-entry"]}')
    completed = flow.run("--restart-plasma")
    assert completed.returncode == 0, completed.stderr
    assert "could not be moved yet" in completed.stdout and "run this script again" in completed.stdout


# --- Q4: the appletsrc backup goes on the next successful install ------------------------------------


def _backup(flow, kind="file"):
    path = flow.home / BACKUP
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "file":
        path.write_text("[Containments][1][Applets][2]\nplugin=x\n")
    else:
        target = flow.root / "precious"
        target.write_text("keep")
        path.symlink_to(target)
    return path


def test_the_next_install_after_a_complete_move_deletes_the_backup(tmp_path):
    flow = Flow(tmp_path)
    flow.reply("status", COMPLETE)
    backup = _backup(flow)
    completed = flow.run()
    assert completed.returncode == 0, completed.stderr
    assert not backup.exists()
    assert "Deleted the panel layout backup" in completed.stdout
    assert flow.steps()[0] == "helper status" and "helper run" not in flow.steps()


@pytest.mark.parametrize("status", [
    PENDING, NOTHING, '{"ok":true,"pending":["wallet-entry"],"present":["data","applets"]}',
    '{"ok":true,"pending":[],"present":["data","config"]}',
])
def test_the_backup_stays_until_the_move_is_complete(tmp_path, status):
    flow = Flow(tmp_path)
    flow.reply("status", status)
    flow.reply("run", '{"ok":true,"migrated":[],"pending":["wallet-entry"]}')
    flow.reply("applets", '{"ok":true,"migrated":[],"pending":["wallet-entry"]}')
    backup = _backup(flow)
    completed = flow.run("--restart-plasma")
    assert completed.returncode == 0, completed.stderr
    assert backup.exists()


def test_the_backup_stays_when_the_install_fails(tmp_path):
    flow = Flow(tmp_path)
    flow.reply("status", COMPLETE)
    backup = _backup(flow)
    completed = flow.run(FLOW_PIP_INSTALL_EXIT="1")
    assert completed.returncode != 0
    assert backup.exists()


def test_a_symlinked_backup_is_never_followed_or_deleted(tmp_path):
    flow = Flow(tmp_path)
    flow.reply("status", COMPLETE)
    backup = _backup(flow, kind="symlink")
    completed = flow.run()
    assert completed.returncode == 0, completed.stderr
    assert backup.is_symlink() and (flow.root / "precious").read_text() == "keep"


def test_the_backup_rule_unlinks_only_an_owned_regular_file():
    script = INSTALL_SCRIPT.read_text(encoding="utf-8")
    (line,) = [line for line in script.splitlines() if '"$remove_applets_backup" = true' in line]
    assert '[ -f "$applets_backup" ] && [ ! -L "$applets_backup" ] && [ -O "$applets_backup" ]' in line


# --- --rollback-hearthwire -------------------------------------------------------------------------------


def test_rollback_restores_then_uninstalls_and_names_the_tag(tmp_path):
    flow = Flow(tmp_path)
    (flow.state / "systemd").write_text("")
    flow.reply("rollback", '{"ok":false,"error":"plasma-running"}', 1)
    flow.reply("rollback", '{"ok":true,"restored":["data","config","notifyrc","wallet-entry","applets"],"pending":[]}')
    flow.installed(pip=["hearthwire"], packages=[NEW_ID])
    icons = flow.home / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps"
    icons.mkdir(parents=True)
    for name in ICON_NAMES:
        (icons / name).write_text("<svg/>")
    completed = flow.run("--rollback-hearthwire", "--restart-plasma")
    assert completed.returncode == 0, completed.stderr
    assert flow.steps() == [
        "helper rollback", "systemctl --user stop plasma-plasmashell.service", "helper rollback",
        "pip uninstall -y --break-system-packages hearthwire", f"kpackagetool6 -r {NEW_ID}",
        "systemctl --user start plasma-plasmashell.service",
    ]
    assert os.listdir(icons) == []
    assert completed.stdout.splitlines()[-1] == "To use Hearthside again, check out tag hearthside-final and run its install.sh"


@pytest.mark.parametrize("reply", ['{"ok":false,"error":"not-locked"}', '{"ok":false,"error":"busy"}',
                                   '{"ok":false,"error":"conflict","category":"data"}', ""])
def test_rollback_refusals_stop_plasma_never(tmp_path, reply):
    flow = Flow(tmp_path)
    flow.reply("rollback", reply)
    flow.installed(pip=["hearthwire"], packages=[NEW_ID])
    completed = flow.run("--rollback-hearthwire", "--restart-plasma")
    assert completed.returncode == 1
    assert flow.steps() == ["helper rollback"]


def test_rollback_without_restart_plasma_and_no_terminal_changes_nothing(tmp_path):
    flow = Flow(tmp_path)
    flow.reply("rollback", '{"ok":false,"error":"plasma-running"}')
    completed = flow.run("--rollback-hearthwire")
    assert completed.returncode == 1 and "--restart-plasma" in completed.stderr
    assert flow.steps() == ["helper rollback"]


@pytest.mark.parametrize("argv", [["--rollback-hearthwire", "--uninstall-web-data"], ["--restart-plasma", "x"],
                                  ["--restart-plasma", "--rollback-hearthwire"]])
def test_install_script_usage(tmp_path, argv):
    flow = Flow(tmp_path)
    completed = flow.run(*argv)
    assert completed.returncode == 2 and "Usage:" in completed.stderr
    assert flow.calls() == []


def test_uninstall_web_data_refuses_while_old_data_waits(tmp_path):
    completed = run_uninstall(tmp_path, '{"ok":false,"error":"legacy-data"}')
    assert completed.returncode == 1
    assert "has not been moved to Hearthwire yet" in completed.stderr
    assert helper_calls(tmp_path) == ["-P -m hearthwire --web-data purge"]


@pytest.mark.parametrize(("answer", "code"), [("y", 0), ("n", 1), ("", 1)])
def test_in_a_terminal_the_move_asks_before_stopping_plasma(tmp_path, answer, code):
    import pty

    flow = Flow(tmp_path)
    flow.reply("status", PENDING)
    flow.reply("run", RUN_DONE)
    flow.reply("applets", APPLETS_DONE)
    master, slave = pty.openpty()
    try:
        child = subprocess.Popen(["sh", str(flow.project / "scripts" / "install.sh")], stdin=slave, stdout=slave,
                                 stderr=subprocess.PIPE, env=flow.env, close_fds=True)
        os.close(slave)
        slave = -1
        os.write(master, (answer + "\n").encode())
        output = b""
        while True:
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            output += chunk
        assert child.wait(timeout=120) == code
    finally:
        os.close(master)
        if slave >= 0:
            os.close(slave)
    assert b"stops Plasma for a moment and starts it again. Continue? [y/N]" in output
    stopped = "kquitapp6 plasmashell" in flow.steps()
    assert stopped == (code == 0)
# <<< legacy-migration
