"""Task 011: reading the hearthwire-hyprland app's settings.json for a backup (core/appconfig.py).

Every file is a fixture under tmp_path; the real config folder is never read.
Each refusal (link, owner, size, mode, type, format) is checked in its own
folder by ``reader_problems``, and every proof runs the same cases against a
mutated copy of appconfig.py, which must then miss at least one.
"""

import json
import os
import stat
from pathlib import Path

import pytest

from conftest import fixture
from hearthwire import cli
from hearthwire.core import appconfig, appletconfig, frontend
from hearthwire.core import settingsbackup as backup
from hearthwire.core.appletconfig import UNREADABLE
from hearthwire.core.webdata import HelperError
from test_frontend import mutant

KEYS = list(appletconfig.CONFIG_ENTRIES)
DEFAULTS = {key: default for key, (_, default) in appletconfig.CONFIG_ENTRIES.items()}
APP_ID = frontend.APP_APPLET_ID
NOW = 1_790_000_000


@pytest.fixture
def config(tmp_path, monkeypatch):
    """HOME and every XDG base inside tmp_path; returns the config base."""
    for name, folder in (("HOME", "home"), ("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config")):
        (tmp_path / folder).mkdir()
        monkeypatch.setenv(name, str(tmp_path / folder))
    return tmp_path / "config"


def document(settings=None, **overrides):
    result = {"format": "hearthwire-app-settings", "version": 1, "settings": {} if settings is None else settings,
              "app": {"background": False, "agentsPanel": False, "tray": False}}
    result.update(overrides)
    return result


def write_app(base, content, *, mode=0o600, folder_mode=0o700):
    folder = Path(base) / "hearthwire-hyprland"
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(folder_mode)
    path = folder / "settings.json"
    if isinstance(content, dict):
        content = json.dumps(content)
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    path.chmod(mode)
    return path


def applied(base, keys=None, module=appconfig):
    try:
        return module.applied_settings(KEYS if keys is None else keys, str(base))
    except HelperError as error:
        return error.code
    except Exception as error:  # noqa: BLE001 - a mutant may fail any way; that is a miss too.
        return f"raised {type(error).__name__}"


# --- what is read ------------------------------------------------------------------------------------


def test_an_empty_settings_object_is_every_default(config):
    write_app(config, document())
    assert applied(config) == DEFAULTS


def test_values_of_the_right_type_are_taken(config):
    settings = {"usageMode": "used", "refreshInterval": 900, "alertLowEnabled": True,
                "chatCustomUrls": '{"local":"http://localhost:8080/"}', "usageWarnPercent": -2**31,
                "usageCriticalPercent": 2**31 - 1, "tooltipMetrics": ""}
    write_app(config, document(settings))
    assert applied(config) == {**DEFAULTS, **settings}


@pytest.mark.parametrize(("key", "value"), [
    ("refreshInterval", True), ("refreshInterval", 300.0), ("refreshInterval", "300"), ("refreshInterval", None),
    ("refreshInterval", 2**31), ("refreshInterval", -2**31 - 1), ("refreshInterval", [300]),
    ("alertLowEnabled", 1), ("alertLowEnabled", "true"), ("alertLowEnabled", None), ("alertLowEnabled", 0),
    ("usageMode", 5), ("usageMode", True), ("usageMode", None), ("usageMode", ["used"]), ("usageMode", {"a": 1}),
])
def test_a_value_of_the_wrong_type_is_unreadable(config, key, value):
    write_app(config, document({key: value}))
    assert applied(config) == {**DEFAULTS, key: UNREADABLE}


def test_unknown_keys_and_the_app_object_are_never_read(config):
    write_app(config, document({"someFutureKey": "x", "background": True},
                               app={"background": True, "agentsPanel": True, "tray": True, "other": 1}))
    result = applied(config)
    assert result == DEFAULTS
    assert not {"someFutureKey", "background", "agentsPanel", "tray"} & set(result)


def test_only_the_asked_keys_are_returned(config):
    write_app(config, document({"usageMode": "used", "chatSignInStorage": "encrypted"}))
    assert applied(config, ["usageMode"]) == {"usageMode": "used"}


def test_the_app_object_is_optional(config):
    raw = document({"usageMode": "used"})
    del raw["app"]
    write_app(config, raw)
    assert applied(config)["usageMode"] == "used"


def test_the_settings_file_is_only_ever_read(config):
    path = write_app(config, fixture("app-settings.json").read_bytes())
    before = (path.read_bytes(), os.stat(path).st_mtime_ns, os.stat(path).st_ino, stat.S_IMODE(os.stat(path).st_mode))
    applied(config)
    after = (path.read_bytes(), os.stat(path).st_mtime_ns, os.stat(path).st_ino, stat.S_IMODE(os.stat(path).st_mode))
    assert before == after
    assert sorted(p.name for p in path.parent.iterdir()) == ["settings.json"]


def test_the_cap_is_one_mebibyte_as_the_writer_has_it():
    assert appconfig.MAX_FILE_BYTES == 1024 * 1024
    assert appconfig.APP_DIR == "hearthwire-hyprland" and appconfig.SETTINGS_FILE == "settings.json"


# --- refusals: every case in its own folder ----------------------------------------------------------


def _valid(base, **kwargs):
    return write_app(base, document({"usageMode": "used"}), **kwargs)


def _file_link(base, monkeypatch):
    real = base.parent / "elsewhere.json"
    real.write_text(json.dumps(document({"usageMode": "used"})))
    real.chmod(0o600)
    folder = base / "hearthwire-hyprland"
    folder.mkdir(parents=True, mode=0o700)
    (folder / "settings.json").symlink_to(real)


def _folder_link(base, monkeypatch):
    real = base.parent / "elsewhere"
    _valid(real)
    base.mkdir(parents=True, exist_ok=True)
    (base / "hearthwire-hyprland").symlink_to(real / "hearthwire-hyprland")


def _foreign_file(base, monkeypatch):
    _valid(base)
    real_fstat, uid = os.fstat, os.getuid()

    def foreign(descriptor, *args):
        info = real_fstat(descriptor, *args)
        if stat.S_ISREG(info.st_mode):
            values = list(info)
            values[stat.ST_UID] = uid + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(os, "fstat", foreign)


def _foreign_folder(base, monkeypatch):
    _valid(base)
    real_stat, uid = os.stat, os.getuid()

    def foreign(path, *args, **kwargs):
        info = real_stat(path, *args, **kwargs)
        if path == "hearthwire-hyprland":
            values = list(info)
            values[stat.ST_UID] = uid + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(os, "stat", foreign)


def _foreign_base(base, monkeypatch):
    _valid(base)
    monkeypatch.setattr(os, "getuid", lambda: os.geteuid() + 1)


def _too_large(base, monkeypatch):
    text = json.dumps(document({"usageMode": "used"}))
    _valid(base)
    write_app(base, text + " " * (appconfig.MAX_FILE_BYTES + 1 - len(text)))


def _reported_too_large(base, monkeypatch):
    _valid(base)
    real_fstat = os.fstat

    def big(descriptor, *args):
        info = real_fstat(descriptor, *args)
        if not stat.S_ISREG(info.st_mode):
            return info
        values = list(info)
        values[stat.ST_SIZE] = appconfig.MAX_FILE_BYTES + 1
        return os.stat_result(values)

    monkeypatch.setattr(os, "fstat", big)


def _directory(base, monkeypatch):
    (base / "hearthwire-hyprland" / "settings.json").mkdir(parents=True)
    (base / "hearthwire-hyprland").chmod(0o700)


def _fifo(base, monkeypatch):
    (base / "hearthwire-hyprland").mkdir(parents=True, mode=0o700)
    os.mkfifo(base / "hearthwire-hyprland" / "settings.json")


def _folder_is_a_file(base, monkeypatch):
    base.mkdir(parents=True)
    (base / "hearthwire-hyprland").write_text("{}")


UNREADABLE_CASES = {
    "the file a symlink": _file_link,
    "the folder a symlink": _folder_link,
    "the file someone else's": _foreign_file,
    "the folder someone else's": _foreign_folder,
    "the config base someone else's": _foreign_base,
    "the file over 1 MiB": _too_large,
    "the file reported over 1 MiB": _reported_too_large,
    "the file a directory": _directory,
    "the file a fifo": _fifo,
    "the folder a file": _folder_is_a_file,
    "the file group-writable": lambda base, monkeypatch: _valid(base, mode=0o620),
    "the file other-writable": lambda base, monkeypatch: _valid(base, mode=0o602),
    "the folder group-writable": lambda base, monkeypatch: _valid(base, folder_mode=0o770),
    "the folder other-writable": lambda base, monkeypatch: _valid(base, folder_mode=0o703),
    # Fix round 1 (L4): 0600 / 0700 or stricter, so no group or other read either.
    "the file group-readable": lambda base, monkeypatch: _valid(base, mode=0o640),
    "the file other-readable": lambda base, monkeypatch: _valid(base, mode=0o604),
    "the file 0644": lambda base, monkeypatch: _valid(base, mode=0o644),
    "the file executable by its owner": lambda base, monkeypatch: _valid(base, mode=0o700),
    "the file group-executable": lambda base, monkeypatch: _valid(base, mode=0o610),
    "the folder group-readable": lambda base, monkeypatch: _valid(base, folder_mode=0o740),
    "the folder other-readable": lambda base, monkeypatch: _valid(base, folder_mode=0o704),
    "the folder 0755": lambda base, monkeypatch: _valid(base, folder_mode=0o755),
    "the folder group-searchable": lambda base, monkeypatch: _valid(base, folder_mode=0o710),
    "the folder other-searchable": lambda base, monkeypatch: _valid(base, folder_mode=0o701),
}

BAD_DATA_CASES = {
    "no config base": lambda base: None,
    "no folder": lambda base: base.mkdir(parents=True, exist_ok=True),
    "no file": lambda base: (base / "hearthwire-hyprland").mkdir(parents=True, mode=0o700),
    "empty": lambda base: write_app(base, b""),
    "not JSON": lambda base: write_app(base, "{"),
    "not UTF-8": lambda base: write_app(base, b'{"format":"\xff"}'),
    "a list": lambda base: write_app(base, "[]"),
    "a duplicate key": lambda base: write_app(
        base, '{"format":"hearthwire-app-settings","version":1,"settings":{},"settings":{}}'),
    "a duplicate setting": lambda base: write_app(
        base, '{"format":"hearthwire-app-settings","version":1,"settings":{"usageMode":"a","usageMode":"b"}}'),
    "NaN": lambda base: write_app(base, '{"format":"hearthwire-app-settings","version":1,"settings":{"x":NaN}}'),
    "too deep": lambda base: write_app(base, json.dumps(document({"x": [[[[[1]]]]]}))),
    "another format": lambda base: write_app(base, document(format="hearthwire-settings")),
    "version 2": lambda base: write_app(base, document(version=2)),
    "version true": lambda base: write_app(base, document(version=True)),
    "version text": lambda base: write_app(base, document(version="1")),
    "version 1.0": lambda base: write_app(base, document(version=1.0)),
    "settings a list": lambda base: write_app(base, document(settings=[])),
    "settings missing": lambda base: write_app(base, {"format": "hearthwire-app-settings", "version": 1}),
    "app a list": lambda base: write_app(base, document(app=[])),
    "an unknown top-level key": lambda base: write_app(base, document(extra=1)),
    "format missing": lambda base: write_app(base, {"version": 1, "settings": {}}),
}


def reader_problems(module, root, monkeypatch):
    """Names of the cases ``module`` does not answer as planned."""
    problems = []
    for index, (name, setup) in enumerate(UNREADABLE_CASES.items()):
        base = root / f"u{index}" / "config"
        base.parent.mkdir(parents=True)
        with monkeypatch.context() as patched:
            setup(base, patched)
            result = applied(base, module=module)
        if result != "settings-unreadable":
            problems.append(f"{name}: {result if isinstance(result, str) else 'read'}")
    for index, (name, setup) in enumerate(BAD_DATA_CASES.items()):
        base = root / f"b{index}" / "config"
        base.parent.mkdir(parents=True)
        setup(base)
        result = applied(base, module=module)
        if result != "bad-data":
            problems.append(f"{name}: {result if isinstance(result, str) else 'read'}")
    for index, (file_mode, folder_mode) in enumerate(((0o600, 0o700), (0o400, 0o700), (0o600, 0o2700))):
        base = root / f"good{index}" / "config"
        _valid(base, mode=file_mode, folder_mode=folder_mode)
        if applied(base, module=module) != {**DEFAULTS, "usageMode": "used"}:
            problems.append(f"a good file ({file_mode:o} in {folder_mode:o}) is not read")
    return problems


def test_the_reader_refuses_links_strangers_big_files_and_other_formats(tmp_path, monkeypatch):
    assert reader_problems(appconfig, tmp_path, monkeypatch) == []


# Follows links and checks nothing, but stays non-blocking (a FIFO case must not hang the run).
FOLLOWING_READ = ('(lambda fd: (os.read(fd, 1 << 22), os.fstat(fd)))'
                  '(os.open(os.path.join(config_base, APP_DIR, SETTINGS_FILE), os.O_RDONLY | os.O_NONBLOCK))')
READER_MUTATIONS = {
    "the file opened following links, unchecked":
        ("            current = read_rc(directory, SETTINGS_FILE, MAX_FILE_BYTES)\n",
         f"            current = {FOLLOWING_READ}\n"),
    "the folder opened following links":
        ("            directory = open_child_dir(base, APP_DIR, create=False)\n",
         "            directory = os.open(os.path.join(config_base, APP_DIR), os.O_RDONLY | os.O_DIRECTORY)\n"),
    "a bigger cap": ("MAX_FILE_BYTES = 1024 * 1024\n", "MAX_FILE_BYTES = 4 * 1024 * 1024\n"),
    "no cap": ("            current = read_rc(directory, SETTINGS_FILE, MAX_FILE_BYTES)\n",
               "            current = read_rc(directory, SETTINGS_FILE, 1 << 40)\n"),
    "the folder mode unchecked": ("        if _too_open(folder_mode, FOLDER_MODE_MAX):\n", "        if False:\n"),
    "the file mode unchecked": ("        if _too_open(info.st_mode, FILE_MODE_MAX):\n", "        if False:\n"),
    "the folder held to the file's rule": ("        if _too_open(folder_mode, FOLDER_MODE_MAX):\n",
                                           "        if _too_open(folder_mode, FILE_MODE_MAX):\n"),
    "the file held to the folder's rule": ("        if _too_open(info.st_mode, FILE_MODE_MAX):\n",
                                           "        if _too_open(info.st_mode, FOLDER_MODE_MAX):\n"),
    "file group write allowed": ("FILE_MODE_MAX = 0o600\n", "FILE_MODE_MAX = 0o620\n"),
    "file other write allowed": ("FILE_MODE_MAX = 0o600\n", "FILE_MODE_MAX = 0o602\n"),
    "file group read allowed": ("FILE_MODE_MAX = 0o600\n", "FILE_MODE_MAX = 0o640\n"),
    "file other read allowed": ("FILE_MODE_MAX = 0o600\n", "FILE_MODE_MAX = 0o604\n"),
    "file 0644 allowed": ("FILE_MODE_MAX = 0o600\n", "FILE_MODE_MAX = 0o644\n"),
    "folder group write allowed": ("FOLDER_MODE_MAX = 0o700\n", "FOLDER_MODE_MAX = 0o770\n"),
    "folder other write allowed": ("FOLDER_MODE_MAX = 0o700\n", "FOLDER_MODE_MAX = 0o703\n"),
    "folder group read allowed": ("FOLDER_MODE_MAX = 0o700\n", "FOLDER_MODE_MAX = 0o750\n"),
    "folder other read allowed": ("FOLDER_MODE_MAX = 0o700\n", "FOLDER_MODE_MAX = 0o705\n"),
    "only write bits checked (round 1)": ("    return bool(mode & 0o777 & ~allowed)\n",
                                          "    return bool(mode & 0o022)\n"),
    "set-id bits counted (a setgid parent refused)": ("    return bool(mode & 0o777 & ~allowed)\n",
                                                       "    return bool(mode & 0o7777 & ~allowed)\n"),
    "refusals become bad-data":
        ('    return HelperError("os-error" if error.code == "os-error" else "settings-unreadable")\n',
         '    return HelperError("bad-data")\n'),
    "a missing file becomes defaults": ("        if current is None:\n            raise HelperError(\"bad-data\")\n",
                                        "        if current is None:\n            return dict(DEFAULTS)\n"),
    "any version": ('    if document["format"] != FORMAT or type(document["version"]) is not int '
                    'or document["version"] != VERSION:\n',
                    '    if document["format"] != FORMAT:\n'),
    "a boolean version": ('type(document["version"]) is not int', 'not isinstance(document["version"], int)'),
    "extra top-level keys": ("            or not set(document) <= set(REQUIRED_KEYS + OPTIONAL_KEYS):\n",
                             "            or False:\n"),
    "plain json.loads": ("        document = strict_loads(data.decode(\"utf-8\"))\n",
                         "        document = __import__(\"json\").loads(data.decode(\"utf-8\"))\n"),
}


@pytest.mark.parametrize("name", sorted(READER_MUTATIONS))
def test_proof_the_reader_rule_catches(tmp_path, monkeypatch, name):
    old, new = READER_MUTATIONS[name]
    copy = mutant(appconfig, old, new)
    copy.DEFAULTS = DEFAULTS
    assert reader_problems(copy, tmp_path, monkeypatch)


def type_problems(module):
    problems = []
    for kind, good, bad in (("Bool", (True, False), (0, 1, "true", None, 1.0)),
                            ("Int", (0, -1, 2**31 - 1, -2**31), (True, False, 1.0, "1", None, 2**31, -2**31 - 1)),
                            ("String", ("", "x"), (1, True, None, ["x"], {"x": 1}))):
        problems += [f"{kind} refuses {value!r}" for value in good if module.typed_value(kind, value) is UNREADABLE]
        problems += [f"{kind} takes {value!r}" for value in bad if module.typed_value(kind, value) is not UNREADABLE]
    if module.typed_value("Double", 1.0) is not UNREADABLE:
        problems.append("an unknown kind is read")
    return problems


def test_values_are_taken_only_with_their_main_xml_type():
    assert type_problems(appconfig) == []


@pytest.mark.parametrize(("old", "new"), [
    ("        return value if type(value) is bool else UNREADABLE\n",
     "        return value if isinstance(value, (bool, int)) else UNREADABLE\n"),
    ("        return value if type(value) is int and INT_MIN <= value <= INT_MAX else UNREADABLE\n",
     "        return value if isinstance(value, int) and INT_MIN <= value <= INT_MAX else UNREADABLE\n"),
    ("        return value if type(value) is int and INT_MIN <= value <= INT_MAX else UNREADABLE\n",
     "        return value if type(value) is int else UNREADABLE\n"),
    ("        return value if type(value) is str else UNREADABLE\n", "        return value\n"),
    ("    return UNREADABLE\n\n\ndef parse_document", "    return value\n\n\ndef parse_document"),
])
def test_proof_the_type_rule_catches(old, new):
    assert type_problems(mutant(appconfig, old, new))


# --- export in app mode ------------------------------------------------------------------------------


def app_mode(monkeypatch):
    monkeypatch.setenv("HEARTHWIRE_FRONTEND", "app")


def cli_reply(capsys, *argv):
    assert cli.main(list(argv)) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    return json.loads(captured.out)


def test_app_export_and_import_round_trip_the_sanitized_fixture(config, capsys, monkeypatch):
    app_mode(monkeypatch)
    write_app(config, fixture("app-settings.json").read_bytes())
    out = cli_reply(capsys, "--settings-backup", "export", "--applet", str(APP_ID))
    assert out["ok"] is True and out["saved"] == len(backup.BACKUP_KEYS)
    restored = cli_reply(capsys, "--settings-backup", "import")
    assert restored["ok"] is True and restored["origin"] == "this-computer" and restored["dropped"] == 0
    settings = restored["settings"]
    assert settings["usageMode"] == "used" and settings["refreshInterval"] == 900
    assert settings["chatUserSites"] == '[{"id":"user-3fa9c01b","name":"Le Chat","url":"https://chat.example.org/chat"}]'
    assert settings["chatSites"] == '["claude","chatgpt","user-3fa9c01b"]'
    # Never in a backup: sign-ins, vault, schema, backup behavior, the app's own switches, unknown keys.
    for key in (*backup.EXCLUDED_KEYS, "background", "agentsPanel", "tray", "someFutureKey"):
        assert key not in settings, key
    # The backup file is the same format the Plasma widget writes and reads.
    saved = json.loads((config / "hearthwire" / "settings-backup.json").read_text())
    assert saved["format"] == "hearthwire-settings" and saved["version"] == 2


def test_an_app_backup_restores_in_plasma_mode_and_back(config, capsys, monkeypatch):
    app_mode(monkeypatch)
    write_app(config, document({"usageMode": "used"}))
    assert cli_reply(capsys, "--settings-backup", "export", "--applet", str(APP_ID))["ok"] is True
    monkeypatch.delenv("HEARTHWIRE_FRONTEND")
    restored = cli_reply(capsys, "--settings-backup", "import")
    assert restored["settings"]["usageMode"] == "used" and restored["origin"] == "this-computer"


def test_app_export_of_wrong_types_drops_and_counts_them(config, capsys, monkeypatch):
    app_mode(monkeypatch)
    write_app(config, document({"usageMode": 5, "refreshInterval": "900", "alertLowEnabled": 1}))
    out = cli_reply(capsys, "--settings-backup", "export", "--applet", str(APP_ID))
    assert out == {"ok": True, "saved": len(backup.BACKUP_KEYS) - 3, "dropped": 3}


@pytest.mark.parametrize("case", ["no folder", "no file", "not JSON", "version 2", "an unknown top-level key"])
def test_app_export_without_a_valid_file_is_bad_data_and_writes_nothing(config, capsys, monkeypatch, case):
    app_mode(monkeypatch)
    BAD_DATA_CASES[case](config)
    assert cli_reply(capsys, "--settings-backup", "export", "--applet", str(APP_ID)) == {"ok": False, "error": "bad-data"}
    assert not (config / "hearthwire").exists()
    assert not (Path(os.environ["XDG_DATA_HOME"]) / "hearthwire").exists()


@pytest.mark.parametrize("case", ["the file a symlink", "the folder group-writable", "the file over 1 MiB",
                                  "the file 0644", "the folder 0755"])
def test_app_export_of_an_unsafe_file_is_settings_unreadable(config, capsys, monkeypatch, case):
    app_mode(monkeypatch)
    UNREADABLE_CASES[case](config, monkeypatch)
    reply = cli_reply(capsys, "--settings-backup", "export", "--applet", str(APP_ID))
    assert reply == {"ok": False, "error": "settings-unreadable"}
    assert not (config / "hearthwire").exists()


def test_app_mode_never_reads_plasmas_rc_files(config, capsys, monkeypatch):
    (config / appletconfig.APPLETSRC).write_text(
        f"[Containments][1][Applets][{APP_ID}]\nplugin={appletconfig.PLUGIN}\n\n"
        f"[Containments][1][Applets][{APP_ID}][Configuration][General]\nusageMode=used\n")
    app_mode(monkeypatch)
    assert cli_reply(capsys, "--settings-backup", "export", "--applet", str(APP_ID)) == {"ok": False, "error": "bad-data"}


def test_plasma_mode_never_reads_the_app_file(config, capsys):
    write_app(config, document({"usageMode": "used"}))
    assert cli_reply(capsys, "--settings-backup", "export", "--applet", "3") == {"ok": False, "error": "applet-not-found"}


def export_sources(module, config, monkeypatch):
    """refreshInterval of the backup each front end exports: the app file says 900, Plasma's rc file 60."""
    write_app(config, document({"refreshInterval": 900}))
    (config / appletconfig.APPLETSRC).write_text(
        f"[Containments][1][Applets][3]\nplugin={appletconfig.PLUGIN}\n\n"
        "[Containments][1][Applets][3][Configuration][General]\nrefreshInterval=60\n")
    found = []
    for current, applet in (("app", APP_ID), ("plasma", 3)):
        if current == "app":
            monkeypatch.setenv("HEARTHWIRE_FRONTEND", "app")
        else:
            monkeypatch.delenv("HEARTHWIRE_FRONTEND", raising=False)
        reply = module.run("export", applet=applet)
        found.append(backup.run("import")["settings"]["refreshInterval"] if reply["ok"] else reply["error"])
    return found


def test_each_front_end_exports_its_own_settings(config, monkeypatch):
    assert export_sources(backup, config, monkeypatch) == [900, 60]


@pytest.mark.parametrize(("old", "new"), [
    ("    if is_app(environ):\n        applied = app_settings(", "    if False:\n        applied = app_settings("),
    ("    if is_app(environ):\n        applied = app_settings(", "    if True:\n        applied = app_settings("),
    ("    if is_app(environ):\n        applied = app_settings(",
     "    if not is_app(environ):\n        applied = app_settings("),
])
def test_proof_the_export_source_rule_catches(config, monkeypatch, old, new):
    assert export_sources(mutant(backup, old, new), config, monkeypatch) != [900, 60]
