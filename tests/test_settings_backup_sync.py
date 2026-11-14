"""The settings backup's key lists stay in step everywhere they are written down.

core/settingsbackup.py decides what a backup holds. main.xml, SettingsBackup.js
and configGeneral.qml each repeat part of that, so a setting added in one place
and forgotten in another would silently leave a backup, or let an import set
something it must not. An export reads the applied settings from Plasma's rc
file (core/appletconfig.py), so the export side is checked on the helper:
its export asks the rc reader for exactly BACKUP_KEYS, with the defaults of
CONFIG_ENTRIES (tied to main.xml by tests/test_applet_config_sync.py). Only
that export runs here, against a temporary folder; the rest reads the files.
"""

import ast
import json
import re
from pathlib import Path

import pytest

from hearthwire.core import settingsbackup, webdata
from hearthwire.core.appletconfig import CONFIG_ENTRIES, applied_from
from hearthwire.core.settingsbackup import BACKUP_KEYS, EXCLUDED_KEYS

ROOT = Path(__file__).resolve().parent.parent
MAIN_XML = ROOT / "plasmoid" / "contents" / "config" / "main.xml"
UI = ROOT / "plasmoid" / "contents" / "ui"
SETTINGS_BACKUP_JS = UI / "SettingsBackup.js"
CONFIG_GENERAL = UI / "configGeneral.qml"
SETTINGS_BACKUP_PY = Path(settingsbackup.__file__)


def read(path):
    return path.read_text(encoding="utf-8")


def mutated(path, old, new):
    raw = read(path)
    assert old in raw, f"proof fixture out of date: {old!r} not in {path.name}"
    return raw.replace(old, new, 1)


def main_xml_keys(xml):
    return re.findall(r'<entry name="(\w+)"', xml)


def js_list(code, name):
    match = re.search(rf"^var {name} = \[(.*?)^\]", code, re.DOTALL | re.MULTILINE)
    assert match, f"{SETTINGS_BACKUP_JS.name}: var {name} is missing"
    return re.findall(r'"(\w+)"', match.group(1))


def function_body(code, signature):
    """The text of a top-level QML function or JS function, by its closing brace's indent."""
    match = re.search(rf"^( *)function {signature} \{{\n", code, re.MULTILINE)
    assert match, f"function {signature} is missing"
    end = code.index(f"\n{match.group(1)}}}\n", match.end())
    return code[match.end():end]


def coverage_problems(backup, excluded, xml_keys):
    problems = []
    for name, keys in (("BACKUP_KEYS", backup), ("EXCLUDED_KEYS", excluded), ("main.xml", xml_keys)):
        if len(set(keys)) != len(keys):
            problems.append(f"{name} has duplicates")
    overlap = set(backup) & set(excluded)
    if overlap:
        problems.append(f"in both lists: {sorted(overlap)}")
    missing = set(xml_keys) - set(backup) - set(excluded)
    if missing:
        problems.append(f"in main.xml but in neither list: {sorted(missing)}")
    stale = (set(backup) | set(excluded)) - set(xml_keys)
    if stale:
        problems.append(f"listed but not in main.xml: {sorted(stale)}")
    return problems


def widget_list_problems(code, backup, excluded):
    problems = []
    if js_list(code, "BACKUP_KEYS") != list(backup):
        problems.append("SettingsBackup.js BACKUP_KEYS differs from the helper's")
    if js_list(code, "EXCLUDED_KEYS") != list(excluded):
        problems.append("SettingsBackup.js EXCLUDED_KEYS differs from the helper's")
    return problems


def applied_problems(qml, backup):
    body = function_body(qml, r"applyBackup\(\)")
    assigned = re.findall(r"\bcfg_(\w+)\s*=(?!=)", body)
    problems = []
    if sorted(assigned) != sorted(backup):
        problems.append(f"applyBackup assigns {sorted(set(assigned) ^ set(backup))} differently from BACKUP_KEYS")
    for key in backup:
        if not re.search(rf"^\s*if \(values\.{key} !== undefined\) page\.cfg_{key} = values\.{key}$", body, re.MULTILINE):
            problems.append(f"applyBackup has no explicit line for {key}")
    return problems


def export_call_problems(source):
    """settingsbackup.py reads the rc file once, in export(), for exactly BACKUP_KEYS."""
    tree = ast.parse(source)
    calls = [(function.name, node) for function in ast.walk(tree) if isinstance(function, ast.FunctionDef)
             for node in ast.walk(function)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "applied_settings"]
    if len(calls) != 1:
        return [f"applied_settings must be called once, found {len(calls)}"]
    function, call = calls[0]
    problems = [] if function == "export" else [f"applied_settings is called by {function}(), not export()"]
    if len(call.args) != 3 or call.keywords or not (isinstance(call.args[1], ast.Name) and call.args[1].id == "BACKUP_KEYS"):
        problems.append(f"export must read applied_settings(applet, BACKUP_KEYS, ...), found {ast.unparse(call)}")
    return problems


def export_read_problems(asked, saved, backup):
    problems = []
    if asked != [list(backup)]:
        problems.append(f"export must ask the rc reader once for BACKUP_KEYS, asked {asked}")
    if saved != list(backup):
        problems.append(f"a widget at its defaults must export every BACKUP_KEY, saved {saved}")
    return problems


def run_export(monkeypatch, tmp_path):
    """Export widget 7 at its defaults; the rc reader is replaced by CONFIG_ENTRIES."""
    asked = []

    def fake_applied_settings(applet, keys, config_base):
        assert applet == 7
        asked.append(list(keys))
        return applied_from({}, keys)

    monkeypatch.setattr(settingsbackup, "applied_settings", fake_applied_settings)
    config = tmp_path / "config"
    config.mkdir(mode=0o700)
    # XDG_DATA_HOME too: export makes the backup key there (task 007), never in the real home.
    environ = {"XDG_CONFIG_HOME": str(config), "XDG_DATA_HOME": str(tmp_path / "data"), "HOME": str(tmp_path)}
    reply = settingsbackup.export(7, environ, clock=lambda: 1_793_923_829)
    assert reply["ok"] is True
    document = json.loads((config / "hearthwire" / "settings-backup.json").read_text(encoding="utf-8"))
    return asked, list(document["settings"])


def checked_problems(code, backup):
    body = function_body(code, r"checkedValue\(key, value, tools(?:, \w+)?\)")  # task 005 adds the added ids
    cases = re.findall(r'^\s*case "(\w+)":$', body, re.MULTILINE)
    return [] if sorted(cases) == sorted(backup) else [
        f"checkedValue cases differ from BACKUP_KEYS: {sorted(set(cases) ^ set(backup))}"]


def test_backup_and_excluded_keys_equal_every_main_xml_key_without_overlap():
    problems = coverage_problems(BACKUP_KEYS, EXCLUDED_KEYS, main_xml_keys(read(MAIN_XML)))
    assert not problems, problems


def test_widget_key_lists_match_the_helper():
    problems = widget_list_problems(read(SETTINGS_BACKUP_JS), BACKUP_KEYS, EXCLUDED_KEYS)
    assert not problems, problems


def test_every_backup_key_is_assigned_in_apply_backup():
    problems = applied_problems(read(CONFIG_GENERAL), BACKUP_KEYS)
    assert not problems, problems


def default_table_problems(backup, excluded, table):
    """A key the rc file lacks takes its default from the table: every listed key needs one."""
    listed = set(backup) | set(excluded)
    return ([f"no default for {sorted(listed - set(table))}"] if listed - set(table) else []) + \
        ([f"in the table but in neither list: {sorted(set(table) - listed)}"] if set(table) - listed else [])


def test_every_backup_and_excluded_key_has_a_default_in_the_helper_table():
    problems = default_table_problems(BACKUP_KEYS, EXCLUDED_KEYS, CONFIG_ENTRIES)
    assert not problems, problems


def test_the_helper_export_reads_exactly_the_backup_keys():
    problems = export_call_problems(SETTINGS_BACKUP_PY.read_text(encoding="utf-8"))
    assert not problems, problems


def test_an_export_at_the_defaults_saves_every_backup_key(monkeypatch, tmp_path):
    asked, saved = run_export(monkeypatch, tmp_path)
    problems = export_read_problems(asked, saved, BACKUP_KEYS)
    assert not problems, problems


def test_every_backup_key_is_checked_by_the_widget():
    problems = checked_problems(read(SETTINGS_BACKUP_JS), BACKUP_KEYS)
    assert not problems, problems


# --- proofs: each rule fails on a violating copy of the real data -----------------------


@pytest.mark.parametrize(("backup", "excluded", "extra_xml"), [
    (BACKUP_KEYS[1:], EXCLUDED_KEYS, ()),                                 # a key in neither list
    (BACKUP_KEYS, EXCLUDED_KEYS[1:], ()),
    (BACKUP_KEYS + (EXCLUDED_KEYS[0],), EXCLUDED_KEYS, ()),               # in both lists
    (BACKUP_KEYS + ("gone",), EXCLUDED_KEYS, ()),                         # listed, not in main.xml
    (BACKUP_KEYS, EXCLUDED_KEYS + ("gone",), ()),
    (BACKUP_KEYS + (BACKUP_KEYS[0],), EXCLUDED_KEYS, ()),                 # listed twice
    (BACKUP_KEYS, EXCLUDED_KEYS, ("usageBrandNew",)),                     # a new setting in no list
])
def test_proof_coverage_rule_catches(backup, excluded, extra_xml):
    assert coverage_problems(backup, excluded, main_xml_keys(read(MAIN_XML)) + list(extra_xml))


# Task 004: main.qml's migration marker and the site clears still owed are
# per-computer state, so a backup never carries them.
SITE_ISOLATION_KEYS = {"chatProfileLayout": ("Int", 0), "chatPendingSiteClears": ("String", "")}


def site_isolation_key_problems(backup, excluded, table, xml_keys):
    problems = []
    for key, entry in SITE_ISOLATION_KEYS.items():
        if key in backup or key not in excluded:
            problems.append(f"{key} must be in EXCLUDED_KEYS only")
        if table.get(key) != entry:
            problems.append(f"{key} must default to {entry!r}")
        if key not in xml_keys:
            problems.append(f"{key} missing from main.xml")
    return problems


def test_site_isolation_keys_are_never_backed_up():
    problems = site_isolation_key_problems(BACKUP_KEYS, EXCLUDED_KEYS, CONFIG_ENTRIES, main_xml_keys(read(MAIN_XML)))
    assert not problems, problems


@pytest.mark.parametrize("key", sorted(SITE_ISOLATION_KEYS))
def test_proof_site_isolation_key_rule_catches(key):
    xml_keys = set(main_xml_keys(read(MAIN_XML)))
    excluded = tuple(name for name in EXCLUDED_KEYS if name != key)
    assert site_isolation_key_problems(BACKUP_KEYS + (key,), excluded, CONFIG_ENTRIES, xml_keys)
    assert site_isolation_key_problems(BACKUP_KEYS, EXCLUDED_KEYS, dict(CONFIG_ENTRIES, **{key: ("String", "x")}),
                                       xml_keys)
    assert site_isolation_key_problems(BACKUP_KEYS, EXCLUDED_KEYS, CONFIG_ENTRIES, xml_keys - {key})


def test_proof_main_xml_keys_are_read_from_entries():
    xml = mutated(MAIN_XML, '<entry name="panelRing"', '<entry name="panelRingRenamed"')
    assert coverage_problems(BACKUP_KEYS, EXCLUDED_KEYS, main_xml_keys(xml))


@pytest.mark.parametrize(("old", "new"), [
    ('"panelRing", "middleClickOpens", "chatCustomUrls"', '"panelRing", "chatCustomUrls"'),
    ('"panelRing", "middleClickOpens", "chatCustomUrls"', '"panelRing", "chatCustomUrls", "middleClickOpens"'),
    ('"initialSetupComplete", "usageHistoryEnabled", "usageHistoryClearOwed"', '"initialSetupComplete", "usageHistoryEnabled"'),
    ('"chatVaultUnlock", "chatSiteZoom", "configSchemaVersion",', '"chatVaultUnlock", "configSchemaVersion",'),
])
def test_proof_widget_list_rule_catches(old, new):
    assert widget_list_problems(mutated(SETTINGS_BACKUP_JS, old, new), BACKUP_KEYS, EXCLUDED_KEYS)


APPLY_LINE = "        if (values.chatCustomUrls !== undefined) page.cfg_chatCustomUrls = values.chatCustomUrls\n"


@pytest.mark.parametrize(("old", "new"), [
    (APPLY_LINE, ""),
    (APPLY_LINE, "        page.cfg_chatCustomUrls = values.chatCustomUrls\n"),
    (APPLY_LINE, "        if (values.chatCustomUrls !== undefined) page.cfg_chatCustomUrls = values.chatSites\n"),
    (APPLY_LINE, APPLY_LINE + "        if (values.chatSiteZoom !== undefined) page.cfg_chatSiteZoom = values.chatSiteZoom\n"),
    (APPLY_LINE, APPLY_LINE + "        page.cfg_chatCustomUrls = \"{}\"\n"),
])
def test_proof_applied_rule_catches(old, new):
    assert applied_problems(mutated(CONFIG_GENERAL, old, new), BACKUP_KEYS)


EXPORT_CALL = "applied_settings(applet, BACKUP_KEYS, config_base(environ))"


@pytest.mark.parametrize("new", [
    "applied_settings(applet, BACKUP_KEYS + EXCLUDED_KEYS, config_base(environ))",
    "applied_settings(applet, EXCLUDED_KEYS, config_base(environ))",
    "applied_settings(applet, tuple(CONFIG_ENTRIES), config_base(environ))",
    "applied_settings(applet, keys=BACKUP_KEYS, config_base=config_base(environ))",
    "dict(applied_settings(applet, BACKUP_KEYS, config_base(environ)), "
    "**applied_settings(applet, (\"chatSiteZoom\",), config_base(environ)))",
])
def test_proof_export_call_rule_catches(new):
    source = SETTINGS_BACKUP_PY.read_text(encoding="utf-8")
    assert source.count(EXPORT_CALL) == 1, "proof fixture out of date"
    assert export_call_problems(source.replace(EXPORT_CALL, new))


def test_proof_export_call_outside_export_is_caught():
    source = SETTINGS_BACKUP_PY.read_text(encoding="utf-8")
    moved = source.replace(EXPORT_CALL, "{}", 1) + "\n\ndef leak(applet):\n    return " + EXPORT_CALL + "\n"
    assert export_call_problems(moved)


@pytest.mark.parametrize(("asked", "saved"), [
    ([list(BACKUP_KEYS) + ["chatSiteZoom"]], list(BACKUP_KEYS)),
    ([list(BACKUP_KEYS[1:])], list(BACKUP_KEYS[1:])),
    ([list(BACKUP_KEYS), list(BACKUP_KEYS)], list(BACKUP_KEYS)),
    ([list(BACKUP_KEYS)], list(BACKUP_KEYS) + ["usageHistoryEnabled"]),
    ([list(BACKUP_KEYS)], list(BACKUP_KEYS[:-1])),
])
def test_proof_export_read_rule_catches(asked, saved):
    assert export_read_problems(asked, saved, BACKUP_KEYS)


@pytest.mark.parametrize("table", [
    {key: value for key, value in CONFIG_ENTRIES.items() if key != "chatCustomUrls"},
    {key: value for key, value in CONFIG_ENTRIES.items() if key != "usageHistoryClearOwed"},
    {key: value for key, value in CONFIG_ENTRIES.items() if key != "chatProfileLayout"},
    {key: value for key, value in CONFIG_ENTRIES.items() if key != "chatPendingSiteClears"},
    dict(CONFIG_ENTRIES, usageBrandNew=("String", "")),
])
def test_proof_default_table_rule_catches(table):
    assert default_table_problems(BACKUP_KEYS, EXCLUDED_KEYS, table)


@pytest.mark.parametrize(("old", "new"), [
    ('    case "panelRing":\n', '    case "panelRing2":\n'),
    ('    case "panelRing":\n', '    case "usageHistoryEnabled":\n        return bool(value)\n    case "panelRing":\n'),
])
def test_proof_checked_rule_catches(old, new):
    assert checked_problems(mutated(SETTINGS_BACKUP_JS, old, new), BACKUP_KEYS)


# --- task 005: added sites and the site order ---------------------------------------------------

CHAT_SITES_JS = UI / "ChatSites.js"
CHAT_STORAGE_JS = UI / "ChatStorage.js"
# Both are in the backup, at the end of BACKUP_KEYS, and main.qml never writes them.
SITE_TABLE_KEYS = {"chatUserSites": ("String", "[]"), "chatSiteOrder": ("String", "")}


def js_number(code, name):
    """The value of ``var NAME = <integer>`` or ``<integer> + <integer>`` / ``<integer> * <integer>``."""
    match = re.search(rf"^var {name} = ([0-9]+(?: [+*] [0-9]+)?)$", code, re.MULTILINE)
    if match is None:
        return None
    left, operator, right = (match.group(1).split(" ") + ["+", "0"])[:3]
    return int(left) + int(right) if operator == "+" else int(left) * int(right)


def site_table_key_problems(backup, excluded, table, xml_keys):
    problems = []
    if tuple(backup[-2:]) != tuple(SITE_TABLE_KEYS):
        problems.append(f"BACKUP_KEYS must end with {list(SITE_TABLE_KEYS)}")
    for key, entry in SITE_TABLE_KEYS.items():
        if key in excluded:
            problems.append(f"{key} must not be excluded")
        if table.get(key) != entry:
            problems.append(f"{key} must default to {entry!r}")
    position = [key for key in xml_keys if key in SITE_TABLE_KEYS or key == "chatPendingSiteClears"]
    if position != ["chatPendingSiteClears", *SITE_TABLE_KEYS]:
        problems.append(f"main.xml must list {list(SITE_TABLE_KEYS)} right after chatPendingSiteClears, found {position}")
    elif xml_keys.index("chatSiteOrder") - xml_keys.index("chatPendingSiteClears") != 2:
        problems.append("main.xml: the site table keys must follow chatPendingSiteClears directly")
    return problems


def test_the_site_table_keys_are_backed_up_with_their_defaults():
    problems = site_table_key_problems(BACKUP_KEYS, EXCLUDED_KEYS, CONFIG_ENTRIES, main_xml_keys(read(MAIN_XML)))
    assert not problems, problems


def test_apply_backup_assigns_the_site_table_keys():
    body = function_body(read(CONFIG_GENERAL), r"applyBackup\(\)")
    for key in SITE_TABLE_KEYS:
        assert re.search(rf"^\s*if \(values\.{key} !== undefined\) page\.cfg_{key} = values\.{key}$", body, re.M), key


def cap_problems(backup_js, chat_sites_js, chat_storage_js):
    problems = []
    if js_number(backup_js, "MAX_REPLY_CHARS") != settingsbackup.MAX_FILE_BYTES + 1024:
        problems.append("SettingsBackup.js MAX_REPLY_CHARS must be MAX_FILE_BYTES + 1024")
    for name in ("MAX_USER_SITES", "MAX_USER_SITES_CHARS", "MAX_USER_SITE_NAME"):
        if js_number(chat_sites_js, name) != getattr(settingsbackup, name):
            problems.append(f"ChatSites.js {name} differs from the helper's")
    if js_number(chat_sites_js, "MAX_CUSTOM_URL_LENGTH") != settingsbackup.MAX_CUSTOM_URL_LENGTH:
        problems.append("ChatSites.js MAX_CUSTOM_URL_LENGTH differs from the helper's")
    ids = settingsbackup.MAX_USER_SITES + len(settingsbackup.WEB_SITE_IDS)
    if not ids == webdata.MAX_SITE_IDS == js_number(chat_storage_js, "MAX_SITE_IDS") == 207:
        problems.append("MAX_USER_SITES + 7 built-ins must equal webdata and ChatStorage.js MAX_SITE_IDS (207)")
    return problems


def test_the_caps_match_the_widget():
    problems = cap_problems(read(SETTINGS_BACKUP_JS), read(CHAT_SITES_JS), read(CHAT_STORAGE_JS))
    assert not problems, problems


@pytest.mark.parametrize(("backup", "excluded", "table", "xml_change"), [
    (BACKUP_KEYS[:-2] + ("chatSiteOrder", "chatUserSites"), EXCLUDED_KEYS, CONFIG_ENTRIES, None),
    (BACKUP_KEYS[:-1], EXCLUDED_KEYS + ("chatSiteOrder",), CONFIG_ENTRIES, None),
    (BACKUP_KEYS, EXCLUDED_KEYS, dict(CONFIG_ENTRIES, chatUserSites=("String", "")), None),
    (BACKUP_KEYS, EXCLUDED_KEYS, dict(CONFIG_ENTRIES, chatSiteOrder=("String", "[]")), None),
    (BACKUP_KEYS, EXCLUDED_KEYS, CONFIG_ENTRIES, ("chatUserSites", "chatProfileGeneration")),
    (BACKUP_KEYS, EXCLUDED_KEYS, CONFIG_ENTRIES, ("chatSiteOrder", "usageMode")),
])
def test_proof_site_table_key_rule_catches(backup, excluded, table, xml_change):
    xml_keys = main_xml_keys(read(MAIN_XML))
    if xml_change is not None:
        moved, before = xml_change
        xml_keys.remove(moved)
        xml_keys.insert(xml_keys.index(before), moved)
    assert site_table_key_problems(backup, excluded, table, xml_keys)


@pytest.mark.parametrize(("which", "name", "value"), [
    ("backup", "MAX_REPLY_CHARS", "65536 + 1024"),
    ("backup", "MAX_REPLY_CHARS", "524288"),
    ("backup", "MAX_REPLY_CHARS", "524288 + 1025"),
    ("sites", "MAX_USER_SITES", "201"),
    ("sites", "MAX_USER_SITES_CHARS", "448 * 1000"),
    ("sites", "MAX_USER_SITE_NAME", "41"),
    ("storage", "MAX_SITE_IDS", "208"),
])
def test_proof_cap_rule_catches(which, name, value):
    texts = {"backup": read(SETTINGS_BACKUP_JS), "sites": read(CHAT_SITES_JS), "storage": read(CHAT_STORAGE_JS)}
    # Write the value in whether or not the widget has the name yet (phase 1 runs in parallel).
    texts[which] = re.sub(rf"^var {name} = .*$", "", texts[which], flags=re.M) + f"\nvar {name} = {value}\n"
    assert cap_problems(texts["backup"], texts["sites"], texts["storage"])


def test_js_number_reads_the_forms_the_widget_uses():
    assert js_number("var A = 524288 + 1024\n", "A") == 525312
    assert js_number("var A = 448 * 1024\n", "A") == 458752
    assert js_number("var A = 207\n", "A") == 207
    assert js_number("var A = B + 1\n", "A") is None


# --- task 007: reply words, the same on both sides -----------------------------------------


def js_words(code, name):
    match = re.search(rf"^var {name} = \[(.*?)\]", code, re.DOTALL | re.MULTILINE)
    assert match, f"{SETTINGS_BACKUP_JS.name}: var {name} is missing"
    return re.findall(r'"([a-z-]+)"', match.group(1))


def reply_word_problems(code, errors, origins):
    """SettingsBackup.js ERRORS is the helper's ERRORS, ORIGINS its ORIGINS (same order)."""
    problems = []
    js_errors = js_words(code, "ERRORS")
    if len(set(js_errors)) != len(js_errors):
        problems.append("SettingsBackup.js ERRORS has duplicates")
    if set(js_errors) != set(errors):
        problems.append(f"ERRORS differ: {sorted(set(js_errors) ^ set(errors))}")
    if js_words(code, "ORIGINS") != list(origins):
        problems.append("SettingsBackup.js ORIGINS differs from the helper's")
    return problems


def test_the_error_codes_and_origins_match_the_widget():
    problems = reply_word_problems(read(SETTINGS_BACKUP_JS), settingsbackup.ERRORS, settingsbackup.ORIGINS)
    assert not problems, problems
    assert {"damaged", "key-unusable"} <= settingsbackup.ERRORS
    assert settingsbackup.ORIGINS == ("this-computer", "other", "unsigned")


@pytest.mark.parametrize(("old", "new", "errors", "origins"), [
    ('"damaged", ', "", settingsbackup.ERRORS, settingsbackup.ORIGINS),
    ('"key-unusable"', '"key-unusable", "bad-key"', settingsbackup.ERRORS, settingsbackup.ORIGINS),
    ('"key-unusable"', '"key-unusable", "damaged"', settingsbackup.ERRORS, settingsbackup.ORIGINS),
    ('"other", "unsigned"', '"unsigned", "other"', settingsbackup.ERRORS, settingsbackup.ORIGINS),
    ('"other", "unsigned"', '"other"', settingsbackup.ERRORS, settingsbackup.ORIGINS),
    ("", "", settingsbackup.ERRORS - {"key-unusable"}, settingsbackup.ORIGINS),
    ("", "", settingsbackup.ERRORS, settingsbackup.ORIGINS + ("elsewhere",)),
])
def test_proof_reply_word_rule_catches(old, new, errors, origins):
    code = mutated(SETTINGS_BACKUP_JS, old, new) if old else read(SETTINGS_BACKUP_JS)
    assert reply_word_problems(code, errors, origins)
