"""The settings backup's key lists stay in step everywhere they are written down.

core/settingsbackup.py decides what a backup holds. main.xml, SettingsBackup.js
and configGeneral.qml each repeat part of that, so a setting added in one place
and forgotten in another would silently leave a backup, or let an import set
something it must not. These tests read the real files; nothing is run.
"""

import re
from pathlib import Path

import pytest

from hearthwire.core.settingsbackup import BACKUP_KEYS, EXCLUDED_KEYS

ROOT = Path(__file__).resolve().parent.parent
MAIN_XML = ROOT / "plasmoid" / "contents" / "config" / "main.xml"
UI = ROOT / "plasmoid" / "contents" / "ui"
SETTINGS_BACKUP_JS = UI / "SettingsBackup.js"
CONFIG_GENERAL = UI / "configGeneral.qml"


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


def exported_problems(qml, backup):
    body = function_body(qml, r"backupSettings\(\)")
    pairs = re.findall(r"^\s*(\w+): page\.cfg_(\w+),?$", body, re.MULTILINE)
    problems = [f"backupSettings maps {key} to cfg_{source}" for key, source in pairs if key != source]
    if [key for key, _ in pairs] != list(backup):
        problems.append("backupSettings must list exactly BACKUP_KEYS, in order")
    return problems


def checked_problems(code, backup):
    body = function_body(code, r"checkedValue\(key, value, tools\)")
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


def test_every_backup_key_is_exported_by_the_page():
    problems = exported_problems(read(CONFIG_GENERAL), BACKUP_KEYS)
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


EXPORT_LINE = "            chatCustomUrls: page.cfg_chatCustomUrls\n"


@pytest.mark.parametrize(("old", "new"), [
    ("            middleClickOpens: page.cfg_middleClickOpens,\n", ""),
    ("            middleClickOpens: page.cfg_middleClickOpens,\n", "            middleClickOpens: page.cfg_panelRing,\n"),
    (EXPORT_LINE, "            chatCustomUrls: page.cfg_chatCustomUrls,\n            chatSiteZoom: page.cfg_chatSiteZoom\n"),
])
def test_proof_exported_rule_catches(old, new):
    assert exported_problems(mutated(CONFIG_GENERAL, old, new), BACKUP_KEYS)


@pytest.mark.parametrize(("old", "new"), [
    ('    case "panelRing":\n', '    case "panelRing2":\n'),
    ('    case "panelRing":\n', '    case "usageHistoryEnabled":\n        return bool(value)\n    case "panelRing":\n'),
])
def test_proof_checked_rule_catches(old, new):
    assert checked_problems(mutated(SETTINGS_BACKUP_JS, old, new), BACKUP_KEYS)
