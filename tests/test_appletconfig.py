"""Reading one widget's applied settings from Plasma's rc file (core/appletconfig.py, audit M1).

Every rc file here is a fixture under tmp_path; the real one is never read.
"""

import ast
import os
import stat
from pathlib import Path

import pytest

from conftest import fixture
from hearthwire.core import appletconfig, legacy
from hearthwire.core.appletconfig import UNREADABLE, decode_value
from hearthwire.core.settingsbackup import BACKUP_KEYS
from hearthwire.core.webdata import HelperError

SOURCE = Path(appletconfig.__file__)
DEFAULTS = {key: default for key, (_, default) in appletconfig.CONFIG_ENTRIES.items()}
APPLET = 21


@pytest.fixture
def config(tmp_path, monkeypatch):
    """HOME and every XDG base inside tmp_path; returns the (made) config folder."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "home").mkdir()
    (tmp_path / "config").mkdir()
    return tmp_path / "config"


def widget(general=None, *, containment=2, applet=APPLET, plugin=appletconfig.PLUGIN, extra=""):
    """rc text of one widget: its group, then its General group with ``general`` lines.

    ``containment=None`` is the top-level form plasmawindowedrc really uses.
    """
    group = f"[Applets][{applet}]" if containment is None else f"[Containments][{containment}][Applets][{applet}]"
    text = f"{group}\nimmutability=1\n"
    if plugin is not None:
        text += f"plugin={plugin}\n"
    if general is not None:
        text += f"\n{group}[Configuration][General]\n"
        text += "".join(f"{line}\n" for line in general)
    return text + extra


def write_rc(config, text, name=appletconfig.APPLETSRC):
    path = config / name
    path.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
    path.chmod(0o600)
    return path


def applied(applet=APPLET, keys=None, config=None):
    try:
        return appletconfig.applied_settings(applet, list(keys or appletconfig.CONFIG_ENTRIES),
                                             str(config) if config else os.environ["XDG_CONFIG_HOME"])
    except HelperError as error:
        return error.code


# --- KConfig value escapes ------------------------------------------------------------------------


@pytest.mark.parametrize(("raw", "decoded"), [
    (b"plain", b"plain"),
    (b"", b""),
    (b"\\s", b" "),
    (b"\\sa\\s", b" a "),
    (b"a\\tb\\nc\\rd", b"a\tb\nc\rd"),
    (b"a\\\\b", b"a\\b"),
    (b"a\\\\sb", b"a\\sb"),           # An escaped backslash, then a plain s.
    (b"\\\\\\\\", b"\\\\"),
    (b"a\\;b\\,c", b"a\\;b\\,c"),      # Kept as written (list separators).
    (b"\\x41\\x2f\\x2F", b"A//"),
    (b"\\x00", b"\x00"),
    (b"\\xc3\\xbc", "ü".encode()),
    (b"\\xZZ", b"xZZ"),               # A bad hex escape gives x.
    (b"\\x4", b"x4"),
    (b"\\x", b"x"),
    (b"\\q", b"\\q"),                 # Any other escape keeps its backslash.
    (b"end\\", b"end\\"),             # So does a backslash at the end.
    (b"\\x41\\x", b"Ax"),
])
def test_values_are_decoded_exactly_as_kconfig_does(raw, decoded):
    assert decode_value(raw) == decoded


@pytest.mark.parametrize(("kind", "raw", "value"), [
    ("String", b"", ""), ("String", b"\\s x \\s", "  x  "), ("String", "ü".encode(), "ü"),
    ("String", b"\\xff", UNREADABLE), ("String", b"\xc3", UNREADABLE),
    ("Int", b"300", 300), ("Int", b"-5", -5), ("Int", b"+7", 7), ("Int", b"0", 0),
    ("Int", b"", UNREADABLE), ("Int", b"3.0", UNREADABLE), ("Int", b"0x10", UNREADABLE),
    ("Int", b"1_000", UNREADABLE), ("Int", "٣".encode(), UNREADABLE), ("Int", b"12345678901", UNREADABLE),
    ("Bool", b"true", True), ("Bool", b"TRUE", True), ("Bool", b"on", True), ("Bool", b"yes", True),
    ("Bool", b"1", True), ("Bool", b"false", False), ("Bool", b"Off", False), ("Bool", b"no", False),
    ("Bool", b"0", False), ("Bool", b"", UNREADABLE), ("Bool", b"maybe", UNREADABLE), ("Bool", b"2", UNREADABLE),
])
def test_values_take_their_main_xml_type(kind, raw, value):
    result = appletconfig.typed_value(kind, raw)
    if value is UNREADABLE:
        assert result is UNREADABLE
    else:
        assert (result, type(result)) == (value, type(value))


# --- finding the widget ---------------------------------------------------------------------------


def test_the_sanitized_fixture_reads_as_the_widget_applies_it(config):
    write_rc(config, fixture("plasma-appletsrc").read_bytes())
    assert applied() == dict(
        DEFAULTS,
        chatCustomUrls='{"claude":"https://claude.example.org/new?q=1;x","local":"http://localhost:8080/"}',
        chatDefaultSite="local", chatSignInStorage="encrypted", chatSites='["claude","local","ollama"]',
        configSchemaVersion=3, initialSetupComplete=True, panelRing="codex.weekly", refreshInterval=900,
        tooltipShowsUsage=False, usageHistoryEnabled=True, usageWarnColor="#AA0000",
    )


def test_keys_with_a_locale_or_expansion_suffix_are_ignored(config):
    write_rc(config, widget(["usageMode[de]=used", "usageMode[$e]=used", "usageCompact[$i]=true",
                             "panelRing[en_US]=off", "panelRing [$e]=off"]))
    result = applied()
    assert (result["usageMode"], result["usageCompact"], result["panelRing"]) == ("remaining", False, "auto")
    write_rc(config, widget(["usageMode[$e]=$(touch /tmp/never)", "usageMode=used"]))
    assert applied()["usageMode"] == "used"


def test_absent_keys_take_the_main_xml_default(config):
    write_rc(config, widget(["usageMode=used"]))
    assert applied() == dict(DEFAULTS, usageMode="used")


def test_a_widget_without_a_general_group_has_every_default(config):
    write_rc(config, widget(None, extra="[Containments][2][Applets][21][Configuration]\nPreloadWeight=1\n"))
    assert applied() == DEFAULTS


def test_another_widgets_general_group_is_not_read(config):
    text = widget(["usageMode=used"], applet=22) + "\n" + widget(None)
    write_rc(config, text)
    assert applied() == DEFAULTS
    assert applied(22)["usageMode"] == "used"


def test_lines_are_trimmed_comments_skipped_and_the_last_line_wins(config):
    text = widget(["  usageMode = used  ", "# panelRing=off", "refreshInterval=60", "no equals sign",
                   "refreshInterval=900", "=orphan"])
    text += "\n[Containments][2][Applets][21][Configuration][General]\nusageCompact=true\r\n"
    write_rc(config, text)
    result = applied()
    assert (result["usageMode"], result["panelRing"], result["refreshInterval"], result["usageCompact"]) == \
        ("used", "auto", 900, True)


def test_a_malformed_header_starts_a_group_nobody_reads(config):
    text = widget(["usageMode=used"]) + "[Containments][2][Applets][21][Configuration][General\npanelRing=off\n"
    write_rc(config, text)
    assert applied()["panelRing"] == "auto"


def test_the_containment_does_not_matter(config):
    write_rc(config, widget(["usageMode=used"], containment=999))
    assert applied()["usageMode"] == "used"


@pytest.mark.parametrize("text", [
    widget(["usageMode=used"]) + widget(["usageMode=remaining"], containment=3),
    widget(["usageMode=used"]) + widget(None, containment=3, plugin="org.kde.plasma.clock"),
    widget(["usageMode=used"]) + widget(None, applet="021"),
    widget(["usageMode=used"], applet="0021") + widget(None, containment=7, applet="21"),
    # Only a Configuration group under a second containment counts too.
    widget(["usageMode=used"]) + "[Containments][3][Applets][21][Configuration][General]\nusageMode=x\n",
])
def test_two_widgets_with_the_id_are_refused(config, text):
    write_rc(config, text)
    assert applied() == "applet-not-found"


def test_the_same_group_twice_is_one_widget(config):
    write_rc(config, widget(["usageMode=used"]) + widget(["panelRing=off"]))
    result = applied()
    assert (result["usageMode"], result["panelRing"]) == ("used", "off")


def test_leading_zeros_name_the_same_widget(config):
    write_rc(config, widget(["usageMode=used"], applet="0021"))
    assert applied()["usageMode"] == "used"


@pytest.mark.parametrize("text", [
    "",
    widget(["usageMode=used"], applet=22),
    widget(["usageMode=used"], applet=210),
    widget(["usageMode=used"], plugin="org.kde.plasma.clock"),
    widget(["usageMode=used"], plugin=None),
    widget(["usageMode=used"], plugin=appletconfig.PLUGIN + "x"),
    widget(["usageMode=used"], plugin=legacy.LEGACY_PLUGIN),
    # The plugin must be in the widget's own group, not a subgroup.
    widget(["usageMode=used", "plugin=" + appletconfig.PLUGIN], plugin=None),
    "[Containments][2][Applets][21][Configuration][General]\nusageMode=used\n",
    "[Applets][21]\nplugin=%s\n[Applets][21][Configuration][General]\nusageMode=used\n" % appletconfig.PLUGIN,
])
def test_a_missing_or_foreign_widget_is_not_found(config, text):
    write_rc(config, text)
    assert applied() == "applet-not-found"


def test_a_plugin_line_may_use_escapes(config):
    write_rc(config, widget(["usageMode=used"], plugin=appletconfig.PLUGIN.replace(".", "\\x2e", 1)))
    assert applied()["usageMode"] == "used"


def test_no_rc_file_or_no_config_folder_is_not_found(config, tmp_path):
    assert applied() == "applet-not-found"
    assert applied(config=tmp_path / "nowhere") == "applet-not-found"
    assert not (tmp_path / "nowhere").exists()


def test_a_value_that_is_not_utf8_is_unreadable(config):
    write_rc(config, widget(["usageMode=used"]).encode() + b"chatDefaultSite=\xff\npanelRing=\\xfe\n")
    result = applied()
    assert result["chatDefaultSite"] is UNREADABLE and result["panelRing"] is UNREADABLE
    assert result["usageMode"] == "used"


def test_other_groups_may_hold_any_bytes(config):
    write_rc(config, b"[Other]\nx=\xff\x00\n[Bad \xff]\n" + widget(["usageMode=used"]).encode())
    assert applied()["usageMode"] == "used"


def test_only_the_asked_keys_are_returned(config):
    write_rc(config, widget(["usageMode=used", "chatSignInStorage=encrypted"]))
    result = applied(keys=BACKUP_KEYS)
    assert list(result) == list(BACKUP_KEYS) and "chatSignInStorage" not in result


# --- the windowed fallback ------------------------------------------------------------------------


def windowed(general=None, **kwargs):
    """plasmawindowedrc text of one widget, at the top level as plasmawindowed writes it."""
    return widget(general, containment=None, **kwargs)


# Sanitized from a fresh plasmawindowed run in the lab (widget 4, no containment prefix).
REAL_WINDOWED_RC = f"""[$Version]
update_info=plasma_to_plasmawindowed.upd

[Applets][4]
activityId=
formfactor=0
immutability=1
location=0
plugin={appletconfig.PLUGIN}

[Applets][4][Configuration]
PreloadWeight=0

[Applets][4][Configuration][General]
usageMode=used
panelRing=off
"""


def test_the_real_plasmawindowed_layout_is_read(config):
    write_rc(config, REAL_WINDOWED_RC, name=appletconfig.WINDOWED_RC)
    result = applied(4)
    assert (result["usageMode"], result["panelRing"], result["refreshInterval"]) == ("used", "off", 300)


def test_plasmawindowed_is_read_when_appletsrc_is_missing(config):
    write_rc(config, windowed(["usageMode=used"]), name=appletconfig.WINDOWED_RC)
    assert applied()["usageMode"] == "used"


def test_plasmawindowed_is_read_when_appletsrc_lacks_the_widget(config):
    write_rc(config, widget(["usageMode=remaining"], applet=22))
    write_rc(config, windowed(["usageMode=used"]), name=appletconfig.WINDOWED_RC)
    assert applied()["usageMode"] == "used"


@pytest.mark.parametrize("plugin", ["org.kde.plasma.pager", legacy.LEGACY_PLUGIN, None])
def test_plasmawindowed_is_read_when_the_id_in_appletsrc_is_another_plugin(config, plugin):
    # plasmawindowed ids are small, so the desktop often has another widget with the same id.
    write_rc(config, widget(["usageMode=remaining", "panelRing=claude.session"], plugin=plugin))
    write_rc(config, windowed(["usageMode=used"]), name=appletconfig.WINDOWED_RC)
    result = applied()
    assert (result["usageMode"], result["panelRing"]) == ("used", "auto")


def test_another_plugin_in_both_files_is_not_found(config):
    write_rc(config, widget(["usageMode=used"], plugin="org.kde.plasma.pager"))
    write_rc(config, windowed(["usageMode=used"], plugin="org.kde.plasma.pager"), name=appletconfig.WINDOWED_RC)
    assert applied() == "applet-not-found"


def test_plasmawindowed_may_still_use_the_containment_form(config):
    write_rc(config, widget(["usageMode=used"], containment=1), name=appletconfig.WINDOWED_RC)
    assert applied()["usageMode"] == "used"


def test_the_top_level_form_counts_only_in_plasmawindowed(config):
    write_rc(config, windowed(["usageMode=used"]))
    assert applied() == "applet-not-found"
    write_rc(config, windowed(["usageMode=remaining"]))
    write_rc(config, windowed(["usageMode=used"]), name=appletconfig.WINDOWED_RC)
    assert applied()["usageMode"] == "used"


def test_appletsrc_wins_when_it_has_the_widget(config):
    write_rc(config, widget(["usageMode=used"]))
    write_rc(config, windowed(["usageMode=remaining"]), name=appletconfig.WINDOWED_RC)
    assert applied()["usageMode"] == "used"


@pytest.mark.parametrize("text", [
    widget(["usageMode=used"]) + widget(None, containment=3),
    widget(["usageMode=used"]) + widget(None, containment=3, plugin="org.kde.plasma.pager"),
    widget(["usageMode=used"], plugin="org.kde.plasma.pager") + widget(None, applet="021"),
])
def test_two_widgets_in_appletsrc_are_not_resolved_by_the_windowed_file(config, text):
    write_rc(config, text)
    write_rc(config, windowed(["usageMode=remaining"]), name=appletconfig.WINDOWED_RC)
    assert applied() == "applet-not-found"


@pytest.mark.parametrize("text", [
    windowed(["usageMode=used"]) + windowed(None, applet=f"0{APPLET}"),
    windowed(["usageMode=used"]) + widget(None, containment=1),
    windowed(["usageMode=used"]) + "[Containments][1][Applets][21][Configuration][General]\nusageMode=x\n",
])
def test_two_widgets_in_the_windowed_file_are_refused(config, text):
    write_rc(config, text, name=appletconfig.WINDOWED_RC)
    assert applied() == "applet-not-found"


def test_an_unsafe_appletsrc_is_refused_without_falling_back(config, tmp_path):
    real = tmp_path / "real-appletsrc"
    real.write_text(widget(["usageMode=used"]))
    (config / appletconfig.APPLETSRC).symlink_to(real)
    write_rc(config, windowed(["usageMode=remaining"]), name=appletconfig.WINDOWED_RC)
    assert applied() == "settings-unreadable"


def test_an_unsafe_windowed_file_is_refused(config, tmp_path):
    real = tmp_path / "real-windowedrc"
    real.write_text(windowed(["usageMode=used"]))
    (config / appletconfig.WINDOWED_RC).symlink_to(real)
    assert applied() == "settings-unreadable"


def test_an_unsafe_windowed_file_is_refused_after_a_foreign_widget(config, tmp_path):
    write_rc(config, widget(["usageMode=remaining"], plugin="org.kde.plasma.pager"))
    real = tmp_path / "real-windowedrc"
    real.write_text(windowed(["usageMode=used"]))
    (config / appletconfig.WINDOWED_RC).symlink_to(real)
    assert applied() == "settings-unreadable"


# --- refusing an unsafe rc file -------------------------------------------------------------------


def test_a_symlinked_rc_file_is_refused(config, tmp_path):
    real = tmp_path / "real-appletsrc"
    real.write_text(widget(["usageMode=used"]))
    (config / appletconfig.APPLETSRC).symlink_to(real)
    assert applied() == "settings-unreadable"


def test_someone_elses_rc_file_is_refused(config, monkeypatch):
    write_rc(config, widget(["usageMode=used"]))
    real_fstat = os.fstat
    uid = os.getuid()

    def foreign_fstat(descriptor, *args):
        info = real_fstat(descriptor, *args)
        if stat.S_ISREG(info.st_mode):
            values = list(info)
            values[stat.ST_UID] = uid + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(os, "fstat", foreign_fstat)
    assert applied() == "settings-unreadable"


def test_someone_elses_config_folder_is_refused(config, monkeypatch):
    write_rc(config, widget(["usageMode=used"]))
    monkeypatch.setattr(os, "getuid", lambda: os.geteuid() + 1)
    assert applied() == "settings-unreadable"


def test_an_oversized_rc_file_is_refused(config, monkeypatch):
    text = widget(["usageMode=used"])
    monkeypatch.setattr(appletconfig, "MAX_RC_BYTES", len(text))
    write_rc(config, text)
    assert applied()["usageMode"] == "used"
    write_rc(config, text + "\n")
    assert applied() == "settings-unreadable"


def test_a_file_reported_over_the_cap_is_refused_before_reading(config, monkeypatch):
    write_rc(config, widget(["usageMode=used"]))
    real_fstat, read_calls = os.fstat, []
    real_read = os.read

    def big_fstat(descriptor, *args):
        info = real_fstat(descriptor, *args)
        if not stat.S_ISREG(info.st_mode):
            return info
        values = list(info)
        values[stat.ST_SIZE] = appletconfig.MAX_RC_BYTES + 1
        return os.stat_result(values)

    def watching_read(descriptor, count):
        read_calls.append(count)
        return real_read(descriptor, count)

    monkeypatch.setattr(os, "fstat", big_fstat)
    monkeypatch.setattr(os, "read", watching_read)
    assert applied() == "settings-unreadable"
    assert read_calls == []


def test_the_size_cap_is_four_mebibytes():
    assert appletconfig.MAX_RC_BYTES == 4 * 1024 * 1024


def test_a_file_that_grows_past_the_cap_while_read_is_refused(config, monkeypatch):
    text = widget(["usageMode=used"])
    write_rc(config, text)
    monkeypatch.setattr(appletconfig, "MAX_RC_BYTES", len(text) - 1)
    real_fstat = os.fstat

    def small_fstat(descriptor, *args):
        info = real_fstat(descriptor, *args)
        values = list(info)
        values[stat.ST_SIZE] = 1
        return os.stat_result(values)

    monkeypatch.setattr(os, "fstat", small_fstat)
    assert applied() == "settings-unreadable"


def test_a_directory_or_fifo_in_place_of_the_rc_file_is_refused(config):
    (config / appletconfig.APPLETSRC).mkdir()
    assert applied() == "settings-unreadable"
    (config / appletconfig.APPLETSRC).rmdir()
    os.mkfifo(config / appletconfig.APPLETSRC)  # Opened non-blocking: no writer needed.
    assert applied() == "settings-unreadable"


def test_the_rc_file_is_only_ever_read(config, monkeypatch):
    path = write_rc(config, fixture("plasma-appletsrc").read_bytes())
    before = (path.read_bytes(), os.stat(path).st_mtime_ns, os.stat(path).st_ino)
    flags_seen = []
    real_open = os.open

    def watching_open(name, flags, *args, **kwargs):
        flags_seen.append((str(name), flags))
        return real_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", watching_open)
    assert applied()["chatDefaultSite"] == "local"
    rc_opens = [flags for name, flags in flags_seen if name.endswith(appletconfig.APPLETSRC)]
    assert rc_opens and all(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC) == 0 for flags in rc_opens)
    assert all(flags & os.O_NOFOLLOW and flags & os.O_NONBLOCK for flags in rc_opens)
    assert (path.read_bytes(), os.stat(path).st_mtime_ns, os.stat(path).st_ino) == before
    assert sorted(os.listdir(config)) == [appletconfig.APPLETSRC]


def test_legacy_uses_the_same_reader_and_plugin_id():
    assert legacy.read_rc is appletconfig.read_rc
    assert legacy.PLUGIN == appletconfig.PLUGIN and legacy.APPLETSRC == appletconfig.APPLETSRC


# --- the module -----------------------------------------------------------------------------------


def test_the_module_imports_only_the_standard_library_and_no_network():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and not node.level:
            imported.add((node.module or "").split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            assert node.module == "webdata", node.module
    assert imported <= {"__future__", "collections", "errno", "os", "re", "stat", "typing"}, imported
