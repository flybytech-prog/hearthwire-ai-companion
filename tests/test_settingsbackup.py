"""Settings backup (core/settingsbackup.py) and --settings-backup."""

import ast
import base64
import errno
import fcntl
import ipaddress
import json
import os
import random
import re
import shutil
import socket
import stat
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

from hearthwire import cli
from hearthwire.core import appletconfig, legacy
from hearthwire.core import settingsbackup as backup
from hearthwire.core.catalog import PROVIDER_CATALOG

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "plasmoid" / "contents" / "ui"
MAIN_XML = ROOT / "plasmoid" / "contents" / "config" / "main.xml"
SOURCE = Path(backup.__file__)
ROUND_4_KEYS = {"panelRing", "middleClickOpens", "usageHistoryEnabled"}
NOW = 1_793_923_829
STAMP = "2026-11-06T00:10:29Z"

GOOD = {
    "trackedProviders": '["claude","codex"]',
    "providerMetrics": '{"claude":["session","weekly"]}',
    "providerOrder": '["codex","claude"]',
    "usageMode": "used",
    "refreshInterval": 900,
    "tooltipShowsUsage": False,
    "tooltipMetrics": '{"codex":[],"claude":["weekly"]}',
    "usageCompact": True,
    "usageWarnPercent": 70,
    "usageCriticalPercent": 90,
    "usageNormalColor": "#00AAff",
    "usageWarnColor": "",
    "usageCriticalColor": "#ff0000",
    "alertLowEnabled": True,
    "alertResetEnabled": True,
    "alertLowPercent": 40,
    "chatSites": '["claude","ollama","local"]',
    "chatDefaultSite": "ollama",
    "chatOllamaUrl": "http://[::1]:11434",
    "chatKeepOpen": True,
    "showUsageTab": True,
    "showChatTab": False,
    "popupDefaultTab": "usage",
    "popupSize": "large",
    "shortcutOpens": "ollama",
    "panelRing": "codex.spark_weekly",
    "middleClickOpens": "mscopilot",
    "chatCustomUrls": '{"local":"http://localhost:8080/","claude":"https://claude.example.org/new?x=1"}',
    "chatUserSites": '[{"name":"Le Chat","url":"https://chat.example.org/chat","id":"user-3fa9c01b"}]',
    "chatSiteOrder": '["ollama","claude","local"]',
}
# What the checks keep of GOOD: canonical JSON (catalog order, added sites' keys
# in id, name, url order), lower-case colors.
GOOD_KEPT = dict(GOOD, usageNormalColor="#00aaff",
                 tooltipMetrics='{"claude":["weekly"],"codex":[]}',
                 chatCustomUrls='{"claude":"https://claude.example.org/new?x=1","local":"http://localhost:8080/"}',
                 chatUserSites='[{"id":"user-3fa9c01b","name":"Le Chat","url":"https://chat.example.org/chat"}]')


@pytest.fixture
def config(tmp_path, monkeypatch):
    """Every XDG base and HOME inside tmp_path; returns the backup folder path."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "home").mkdir()
    return tmp_path / "config" / "hearthwire"


APPLET = 7
DEFAULTS = {key: appletconfig.CONFIG_ENTRIES[key][1] for key in backup.BACKUP_KEYS}


def kconfig_text(value):
    """A value as KConfig writes it (KConfigIniBackend::stringToPrintable)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = (value.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r"))
    if text.startswith(" "):
        text = "\\s" + text[1:]
    if text.endswith(" "):
        text = text[:-1] + "\\s"
    return text


def write_rc(settings, *, applet=APPLET, name=appletconfig.APPLETSRC, raw_lines=()):
    """Widget ``applet``'s applied ``settings`` in a fixture rc file under $XDG_CONFIG_HOME."""
    base = Path(os.environ["XDG_CONFIG_HOME"])
    base.mkdir(parents=True, exist_ok=True)
    # plasmawindowedrc keeps the widget at the top level, the desktop file in a containment.
    group = f"[Applets][{applet}]" if name == appletconfig.WINDOWED_RC else f"[Containments][1][Applets][{applet}]"
    lines = [group, f"plugin={appletconfig.PLUGIN}", "", f"{group}[Configuration][General]"]
    lines += [f"{key}={kconfig_text(value)}" for key, value in settings.items()]
    lines += list(raw_lines)
    path = base / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def run(operation, applet=APPLET, now=NOW):
    try:
        if operation == "export":
            return backup.export(applet, clock=lambda: now)
        return backup.run(operation)
    except backup.HelperError as error:
        return {"ok": False, "error": error.code}


def exported(settings, **kwargs):
    write_rc(settings)
    return run("export", **kwargs)


def cli_reply(capsys, *argv):
    assert cli.main(list(argv)) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    return json.loads(captured.out)


def write_backup(folder, content, *, mode=0o600, folder_mode=0o700):
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(folder_mode)
    path = folder / "settings-backup.json"
    if isinstance(content, dict):
        content = json.dumps(content)
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    path.chmod(mode)
    return path


def document(settings=None, **overrides):
    result = {"format": "hearthwire-settings", "version": 1, "config_schema": 3,
              "exported_at": STAMP, "settings": GOOD if settings is None else settings}
    result.update(overrides)
    return result


# --- the key lists --------------------------------------------------------------------------------


def main_xml_keys():
    return set(re.findall(r'<entry name="([A-Za-z]+)"', MAIN_XML.read_text(encoding="utf-8")))


def test_backup_and_excluded_keys_cover_every_setting_once():
    backed, excluded = set(backup.BACKUP_KEYS), set(backup.EXCLUDED_KEYS)
    assert len(backed) == len(backup.BACKUP_KEYS) and len(excluded) == len(backup.EXCLUDED_KEYS)
    assert backed.isdisjoint(excluded)
    # Phase 3/4 add the round-4 keys to main.xml; until then they come on top.
    assert backed | excluded == main_xml_keys() | ROUND_4_KEYS


def test_the_decided_keys_are_on_the_right_side():
    assert "chatCustomUrls" in backup.BACKUP_KEYS  # D74
    assert "usageHistoryEnabled" in backup.EXCLUDED_KEYS  # D70: never set by import.
    for key in ("chatSignInStorage", "chatProfileGeneration", "chatAutoLockMinutes", "chatVaultUnlock",
                "chatSiteZoom", "configSchemaVersion", "initialSetupComplete", "chatProfileLayout",
                "chatPendingSiteClears"):
        assert key in backup.EXCLUDED_KEYS
    # Task 007: a restore never changes backup behavior.
    assert backup.EXCLUDED_KEYS[-2:] == ("backupAutoExport", "backupRestoreAt")
    assert not {"backupAutoExport", "backupRestoreAt"} & set(backup.BACKUP_KEYS)


def test_every_backup_key_has_a_rule():
    assert list(backup.RULES) == list(backup.BACKUP_KEYS)


def js_text(name):
    return (UI / name).read_text(encoding="utf-8")


def test_the_site_ids_match_chat_sites_js_and_the_ollama_entry():
    sites = js_text("ChatSites.js").split("var sites = [", 1)[1].split("\n]\n", 1)[0]
    assert tuple(re.findall(r'^        id: "([a-z]+)"', sites, re.M)) == backup.WEB_SITE_IDS
    blocks = sites.split("\n    {")[1:]
    local = tuple(re.search(r'id: "([a-z]+)"', block).group(1) for block in blocks if "local: true" in block)
    assert local == tuple(sorted(backup.LOCAL_SITE_IDS))
    assert re.search(r'id: "ollama"', js_text("OllamaChat.js"))
    assert re.search(r"var MAX_CUSTOM_URL_LENGTH = %d\n" % backup.MAX_CUSTOM_URL_LENGTH, js_text("ChatSites.js"))


def test_the_site_names_match_chat_sites_js_and_the_ollama_entry():
    sites = js_text("ChatSites.js").split("var sites = [", 1)[1].split("\n]\n", 1)[0]
    assert tuple(re.findall(r'^        name: "([^"\\]*)",?$', sites, re.M)) == backup.WEB_SITE_NAMES
    assert re.search(r'^    name: "%s",$' % backup.OLLAMA_SITE_NAME, js_text("OllamaChat.js"), re.M)


def js_list(text, name):
    match = re.search(r"var %s = \[([^\]]*)\]" % name, text)
    return tuple(json.loads("[" + match.group(1) + "]"))


def test_the_choices_match_the_widget():
    settings = js_text("SettingsLogic.js")
    assert js_list(settings, "POPUP_TABS") == backup.POPUP_TABS
    assert js_list(settings, "POPUP_SIZES") == backup.POPUP_SIZES
    assert js_list(settings, "SHORTCUT_TARGETS") == backup.SHORTCUT_TARGETS
    assert js_list(settings, "ALERT_PERCENTS") == backup.ALERT_PERCENTS
    assert js_list(js_text("UsageLogic.js"), "COLOR_PERCENTS") == backup.COLOR_PERCENTS
    general = js_text("configGeneral.qml").split("readonly property var refreshChoices: [", 1)[1].split("]", 1)[0]
    assert tuple(int(value) for value in re.findall(r"value: ([0-9]+)", general)) == backup.REFRESH_INTERVALS
    assert re.search(r'var DEFAULT_ADDRESS = "http://127\.0\.0\.1:11434"', js_text("OllamaChat.js"))


def test_ring_pairs_are_catalog_percentages():
    assert backup.RING_PAIRS == {f"{entry.provider_id}.{metric}" for entry in PROVIDER_CATALOG
                                 for metric in entry.supported_metrics if metric != "extra_usage"}


# --- validate_settings ----------------------------------------------------------------------------


def test_good_settings_are_kept_in_backup_key_order():
    kept, dropped = backup.validate_settings(GOOD)
    assert (kept, dropped) == (GOOD_KEPT, 0)
    assert list(kept) == list(backup.BACKUP_KEYS)


def test_unknown_and_excluded_keys_are_dropped_and_counted():
    value = dict(GOOD, chatSignInStorage="encrypted", usageHistoryEnabled=True, chatSiteZoom="{}",
                 configSchemaVersion=3, initialSetupComplete=True, somethingElse=1, __proto__="x")
    kept, dropped = backup.validate_settings(value)
    assert (kept, dropped) == (GOOD_KEPT, 7)


GOOD_VALUES = [
    ("trackedProviders", "[]"), ("trackedProviders", '["grok","devin","copilot","antigravity","cursor"]'),
    ("providerMetrics", "{}"), ("providerMetrics", '{"copilot":["chat"],"grok":[]}'),
    ("providerOrder", ""), ("providerOrder", "[]"),
    ("usageMode", "remaining"), ("refreshInterval", 60), ("refreshInterval", 3600),
    ("tooltipMetrics", ""), ("tooltipMetrics", "{}"),
    ("usageWarnPercent", 50), ("usageWarnPercent", 90), ("usageCriticalPercent", 55), ("usageCriticalPercent", 95),
    ("usageNormalColor", ""), ("alertLowPercent", 5), ("alertLowPercent", 50),
    ("chatSites", "[]"), ("chatSites", '["claude","chatgpt","grok","gemini","copilot","mscopilot","local","ollama"]'),
    ("chatDefaultSite", "local"), ("chatOllamaUrl", "http://127.0.0.1:11434"),
    ("chatOllamaUrl", "http://localhost:1"), ("chatOllamaUrl", "http://localhost:65535"),
    ("popupDefaultTab", "chat"), ("popupSize", "compact"), ("shortcutOpens", "popup"),
    ("panelRing", "off"), ("panelRing", "auto"), ("panelRing", "grok.weekly"),
    ("middleClickOpens", "refresh"), ("middleClickOpens", "usage"), ("middleClickOpens", "ollama"),
    ("middleClickOpens", "local"), ("chatCustomUrls", "{}"),
    ("chatCustomUrls", '{"gemini":"https://gemini.example.com:8443/app#x"}'),
    ("chatUserSites", "[]"), ("chatUserSites", " [ ] "),
    ("chatUserSites", '[{"id":"user-00000000","name":"A","url":"https://a.example.com"}]'),
    ("chatSiteOrder", ""), ("chatSiteOrder", "[]"), ("chatSiteOrder", '["ollama"]'),
    ("chatSiteOrder", '["ollama","local","mscopilot","copilot","gemini","grok","chatgpt","claude"]'),
]


@pytest.mark.parametrize(("key", "value"), GOOD_VALUES)
def test_good_values_are_kept(key, value):
    kept, dropped = backup.validate_settings({key: value})
    assert (list(kept), dropped) == ([key], 0)


BAD_VALUES = [
    ("trackedProviders", ""), ("trackedProviders", "{}"), ("trackedProviders", '["claude","claude"]'),
    ("trackedProviders", '["nobody"]'), ("trackedProviders", '["Claude"]'), ("trackedProviders", "[1]"),
    ("trackedProviders", '["claude"'), ("trackedProviders", ["claude"]), ("trackedProviders", '[NaN]'),
    ("providerMetrics", "[]"), ("providerMetrics", '{"claude":["spark"]}'), ("providerMetrics", '{"nobody":[]}'),
    ("providerMetrics", '{"claude":"session"}'), ("providerMetrics", '{"claude":["session","session"]}'),
    ("providerMetrics", '{"claude":[],"claude":["weekly"]}'), ("providerMetrics", ""),
    ("providerOrder", '["claude","claude"]'), ("providerOrder", "null"),
    ("usageMode", "left"), ("usageMode", ""), ("usageMode", True),
    ("refreshInterval", 301), ("refreshInterval", "300"), ("refreshInterval", 300.0), ("refreshInterval", True),
    ("refreshInterval", None),
    ("tooltipShowsUsage", 1), ("tooltipShowsUsage", "true"), ("tooltipShowsUsage", None),
    ("tooltipMetrics", "[]"), ("tooltipMetrics", '{"claude":["extra"]}'),
    ("usageWarnPercent", 95), ("usageWarnPercent", 45), ("usageWarnPercent", 62), ("usageWarnPercent", True),
    ("usageCriticalPercent", 50), ("usageCriticalPercent", 100),
    ("usageNormalColor", "red"), ("usageNormalColor", "#fff"), ("usageNormalColor", "#00aaff00"),
    ("usageNormalColor", "00aaff"), ("usageNormalColor", "#00aafg"), ("usageNormalColor", "#00aaff\n"),
    ("alertLowEnabled", 0), ("alertLowPercent", 35), ("alertLowPercent", 0), ("alertLowPercent", False),
    ("chatSites", '["claude","nope"]'), ("chatSites", '["ollama","ollama"]'), ("chatSites", '"claude"'),
    ("chatDefaultSite", ""), ("chatDefaultSite", "nope"), ("chatDefaultSite", "Claude"),
    ("chatOllamaUrl", ""), ("chatOllamaUrl", "http://127.0.0.1:11434/"), ("chatOllamaUrl", "http://127.0.0.2:11434"),
    ("chatOllamaUrl", "https://localhost:11434"), ("chatOllamaUrl", "http://localhost"),
    ("chatOllamaUrl", "http://localhost:0"), ("chatOllamaUrl", "http://localhost:65536"),
    ("chatOllamaUrl", "http://localhost:011434"), ("chatOllamaUrl", "http://LOCALHOST:11434"),
    ("chatOllamaUrl", "http://example.com:11434"), ("chatOllamaUrl", "http://user@localhost:11434"),
    ("chatKeepOpen", "false"), ("showUsageTab", 1), ("showChatTab", None),
    ("popupDefaultTab", "ollama"), ("popupSize", "huge"), ("shortcutOpens", "refresh"),
    ("panelRing", ""), ("panelRing", "claude.extra_usage"), ("panelRing", "claude.spark"), ("panelRing", "claude"),
    ("panelRing", "Auto"), ("middleClickOpens", "popup"), ("middleClickOpens", ""), ("middleClickOpens", "chat"),
    ("chatCustomUrls", ""), ("chatCustomUrls", "[]"), ("chatCustomUrls", '{"ollama":"https://a.example.com/"}'),
    ("chatCustomUrls", '{"nope":"https://a.example.com/"}'), ("chatCustomUrls", '{"claude":""}'),
    ("chatCustomUrls", '{"claude":1}'), ("chatCustomUrls", '{"claude":"http://claude.ai/"}'),
    ("chatCustomUrls", '{"claude":"https://a.example.com/","chatgpt":"https://user:pw@chatgpt.com/"}'),
    ("chatCustomUrls", '{"claude":"https://a.example.com/","claude":"https://b.example.com/"}'),
    ("chatCustomUrls", '{"claude":"https://a.example.com/\\u0085"}'),
    ("chatCustomUrls", '{"claude":"https://a.example.com/\\u0000"}'),
    ("chatCustomUrls", '{"claude":"https://a.example.com/\\ud800"}'),
    ("chatCustomUrls", {"claude": "https://a.example.com/"}),
]


@pytest.mark.parametrize(("key", "value"), BAD_VALUES)
def test_bad_values_are_dropped_and_counted(key, value):
    assert backup.validate_settings({key: value}) == ({}, 1)


@pytest.mark.parametrize("key", [key for key in backup.BACKUP_KEYS if isinstance(GOOD[key], str)])
def test_strings_with_controls_or_over_4096_characters_are_dropped(key):
    for bad in ("\x00", "\x1b", "\x7f", "\x85", "\x9f", "\ud800"):
        assert backup.validate_settings({key: GOOD[key] + bad}) == ({}, 1)
    if key not in ("chatCustomUrls", "chatUserSites"):
        assert backup.validate_settings({key: GOOD[key] + " " * (4097 - len(GOOD[key]))}) == ({}, 1)


def test_chat_custom_urls_hold_seven_long_addresses():
    long_path = "https://a.example.com/" + "x" * (2048 - len("https://a.example.com/"))
    value = json.dumps({site: long_path for site in backup.WEB_SITE_IDS}, separators=(",", ":"))
    assert len(value) > 4096
    assert backup.validate_settings({"chatCustomUrls": value}) == ({"chatCustomUrls": value}, 0)
    too_long = value.replace(long_path, long_path + "x", 1)
    assert backup.validate_settings({"chatCustomUrls": too_long}) == ({}, 1)


# --- chatCustomUrls: the ChatSites.js port --------------------------------------------------------

URL_CASES = [
    ("claude", ""), ("claude", "https://claude.ai/new"), ("claude", "HTTPS://Claude.AI/new"),
    ("claude", "https://claude.ai:443/"), ("claude", "https://claude.ai:0/"), ("claude", "https://claude.ai:65536/"),
    ("claude", "https://claude.ai:00443/"), ("claude", "https://claude.ai:/"), ("claude", "https://claude.ai./x"),
    ("claude", "http://claude.ai/"), ("claude", "ftp://claude.ai/"), ("claude", "javascript:alert(1)"),
    ("claude", "claude.ai"), ("claude", "//claude.ai/"), ("claude", "https:claude.ai"), ("claude", "https:///x"),
    ("claude", "https://user@claude.ai/"), ("claude", "https://a:b@claude.ai/"), ("claude", "https://claude.ai/@x"),
    ("claude", "https://claude.ai\\@evil.com/"), ("claude", "https://cla%75de.ai/"), ("claude", "https://.claude.ai/"),
    ("claude", "https://claude..ai/"), ("claude", "https://claude_ai/"), ("claude", "https://[::1]/"),
    ("claude", "https://[::2]/"), ("claude", "https://localhost/"), ("claude", "https://LOCALHOST./"),
    ("claude", "https://a.localhost/"), ("claude", "https://a.localhost.localdomain/"),
    ("claude", "https://ip6-localhost/"), ("claude", "https://intranet/"), ("claude", "https://127.0.0.1/"),
    ("claude", "https://127.1/"), ("claude", "https://0x7f000001/"), ("claude", "https://017700000001/"),
    ("claude", "https://0x7f.1/"), ("claude", "https://0/"), ("claude", "https://0.0.0.0/"),
    ("claude", "https://10.0.0.1/"), ("claude", "https://1.2.3.4/"), ("claude", "https://1.2.3.256/"),
    ("claude", "https://1.2.3.08/"), ("claude", "https://256.1.1.1/"), ("claude", "https://1.2.3.4.5/"),
    ("claude", "https://example.123/"), ("claude", "https://example.0x/"), ("claude", "https://example.com1/"),
    ("claude", "https://claude.ai/ x"), ("claude", "https://claude.ai/\u00a0"), ("claude", "https://claude.ai/\u2028"),
    ("claude", "https://claude.ai/\ufeff"), ("claude", "https://claude.ai/\u3000"), ("claude", "https://claude.ai/\t"),
    ("claude", "https://claude.ai/\u0085"), ("claude", "https://claude.ai/ü"), ("claude", "https://clüde.ai/"),
    ("claude", "https://claude.ai/" + "a" * 2029), ("claude", "https://claude.ai/" + "a" * 2030),
    ("claude", "https://claude.ai/" + "😀" * 1014 + "a"), ("claude", "https://claude.ai/" + "😀" * 1015),
    ("claude", "https://claude.ai?q=1"), ("claude", "https://claude.ai#frag"), ("claude", "https://claude.ai/\"'<>"),
    ("local", "http://localhost:3000/"), ("local", "http://127.0.0.1/"), ("local", "http://[::1]:8080/x"),
    ("local", "http://127.0.0.2/"), ("local", "http://example.com/"), ("local", "https://localhost/"),
    ("local", "https://example.com/"), ("local", "http://localhost./"), ("local", "http://user@localhost/"),
    ("ollama", "https://example.com/"), ("nope", "https://example.com/"),
]


@pytest.mark.parametrize(("site", "url", "code"), [
    ("claude", "", ""), ("claude", "https://claude.ai/new", ""), ("claude", "http://claude.ai/", "scheme"),
    ("claude", "https://user@claude.ai/", "userinfo"), ("claude", "https://claude.ai/ x", "whitespace"),
    ("claude", "https://claude.ai/\u00a0", "whitespace"), ("claude", "claude.ai", "malformed"),
    ("claude", "https://127.1/", "loopback-not-allowed"), ("claude", "https://intranet/", "loopback-not-allowed"),
    ("claude", "https://1.2.3.08/", "loopback-not-allowed"), ("claude", "https://10.0.0.1/", ""),
    ("claude", "https://claude.ai/" + "a" * 2030, ""), ("claude", "https://claude.ai/" + "a" * 2031, "too-long"),
    # JS .length counts UTF-16 units: an emoji is two.
    ("claude", "https://claude.ai/" + "😀" * 1015, ""), ("claude", "https://claude.ai/" + "😀" * 1015 + "a", "too-long"),
    ("local", "http://localhost:3000/", ""), ("local", "http://127.0.0.2/", "http-not-loopback"),
    ("ollama", "https://example.com/", "unknown-site"),
])
def test_custom_url_codes(site, url, code):
    assert backup.custom_url_error(site, url) == code


PARITY_QML = """import QtQuick
import QtTest
import "ChatSites.js" as ChatSites

TestCase {
    name: "Parity"
    function test_dump() {
        var cases = %s
        var codes = cases.map(function (item) {
            return ChatSites.validateCustomUrl(item[0], item[1]).error
        })
        console.log("PARITY " + JSON.stringify(codes))
    }
}
"""


def chat_sites_js_results(tmp_path, qml, raw=False):
    """What ``qml`` (a TestCase that logs ``PARITY <json>``) prints against the widget's ChatSites.js.

    Skipped without qmltestrunner or QtTest.
    """
    runner = shutil.which("qmltestrunner", path="/usr/lib/qt6/bin:/usr/bin:/bin")
    if runner is None:
        pytest.skip("qmltestrunner is not installed")
    for script in UI.glob("*.js"):  # ChatSites.js and the scripts it imports.
        shutil.copy2(script, tmp_path / script.name)
    (tmp_path / "tst_parity.qml").write_text(qml, encoding="utf-8")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "LANG": "C.UTF-8", "QT_QPA_PLATFORM": "offscreen",
           "XDG_RUNTIME_DIR": str(tmp_path), "TMPDIR": str(tmp_path)}
    completed = subprocess.run([runner, "-input", str(tmp_path / "tst_parity.qml")], env=env, cwd=tmp_path,
                               capture_output=True, text=True, timeout=120, check=False)
    output = completed.stdout + completed.stderr
    match = re.search(r"PARITY (\[.*\])", output)
    if match is None and "module \"QtTest\" is not installed" in output:
        pytest.skip("QtTest is not installed")
    assert match is not None, output[-4000:]
    return output if raw else json.loads(match.group(1))


def test_the_port_gives_the_same_codes_as_chat_sites_js(tmp_path):
    """Runs the widget's own validateCustomUrl on every case (skipped without qmltestrunner)."""
    codes = chat_sites_js_results(tmp_path, PARITY_QML % json.dumps(URL_CASES))
    assert [backup.custom_url_error(site, url) for site, url in URL_CASES] == codes


# --- chatUserSites and chatSiteOrder: the ChatSites.js port (task 005) ----------------------------

# (name, the other added sites' names, code). Lengths count UTF-16 units, as JS .length.
NAME_CASES = [
    ("Le Chat", (), ""), ("A", (), ""), ("Le Chat (beta) #1", (), ""), ("Claude2", (), ""), ("Mistral", ("Other",), ""),
    ("a" * 40, (), ""), ("a" * 41, (), "name-too-long"),
    ("\U0001f600" * 20, (), "name-chars"), ("a" + "\U0001f600" * 19, (), ""), ("\U0001f600" * 20 + "a", (), "name-too-long"), ("a" + "\U0001f600" * 20, (), "name-too-long"),
    ("\u00e9" * 40, (), ""), ("e\u0301" * 20, (), ""), ("e\u0301" * 20 + "x", (), "name-too-long"),
    ("\u4e2d" * 40, (), ""), ("\u4e2d" * 41, (), "name-too-long"),
    ("", (), "name-empty"), (" ", (), "name-empty"), ("\t\n", (), "name-empty"), ("\u3000\ufeff\u00a0", (), "name-empty"),
    ("\u2028\u2029", (), "name-empty"), (" " * 41, (), "name-empty"),
    (" Le Chat", (), "name-chars"), ("Le Chat ", (), "name-chars"), ("Le Chat\u00a0", (), "name-chars"),
    ("\ufeffLe Chat", (), "name-chars"), ("Le Chat\u2029", (), "name-chars"), ("Le Chat\n", (), "name-chars"),
    (" " + "a" * 40, (), "name-too-long"),
    ("Le\u3000Chat", (), ""), ("Le\u00a0Chat", (), ""), ("Le\tChat", (), "name-chars"),
    ("Le\x00Chat", (), "name-chars"), ("Le\x1bChat", (), "name-chars"), ("Le\x7fChat", (), "name-chars"),
    ("Le\x85Chat", (), "name-chars"), ("Le\x9fChat", (), "name-chars"),
    # Qt's trim also strips U+0085 (review I-3): alone it is empty, at an end untrimmed.
    ("\x85", (), "name-empty"), ("Le Chat\x85", (), "name-chars"),
    ("Le\ud800Chat", (), "name-chars"), ("Le\udc00Chat", (), "name-chars"), ("Le Chat\ud83d", (), "name-chars"),
    ("<b>x</b>", (), "name-chars"), ("a&b", (), "name-chars"), ("a>b", (), "name-chars"), ("a<b", (), "name-chars"),
    ("a\"b'c", (), ""), ("a/b\\c", (), ""),
    # Invisible and bidi formatting (M3), every listed point and range end.
    *[("Le" + chr(point) + "Chat", (), "name-chars") for point in (
        0x00AD, 0x061C, 0x180E, 0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2028, 0x2029, 0x202A, 0x202B, 0x202C,
        0x202D, 0x202E, 0x2060, 0x2061, 0x2062, 0x2063, 0x2064, 0x2066, 0x2067, 0x2068, 0x2069, 0xFEFF)],
    ("Le\u200aChat", (), ""), ("Le\u2030Chat", (), ""),
    # Round 2 (SEC M-1): every Default_Ignorable_Code_Point, U+FFF9-FFFB and U+2800, each range end.
    *[("Le" + chr(point) + "Chat", (), "name-chars") for point in (
        0x034F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x180B, 0x180F, 0x2065, 0x206A, 0x206F, 0x2800, 0x3164,
        0xFE00, 0xFE0F, 0xFFA0, 0xFFF0, 0xFFF8, 0xFFF9, 0xFFFB, 0x1BCA0, 0x1BCA3, 0x1D173, 0x1D17A,
        0xE0000, 0xE0001, 0xE0020, 0xE007F, 0xE0100, 0xE01EF, 0xE0FFF)],
    ("Le\u180aChat", (), ""), ("Le\u2070Chat", (), ""), ("Le\u27ffChat", (), ""), ("Le\u2801Chat", (), ""),
    ("Le\ufdffChat", (), ""), ("Le\ufe10Chat", (), ""), ("Le\ufffcChat", (), ""), ("Le\U0001d172Chat", (), ""),
    ("Le\U0001d17bChat", (), ""), ("Le\U000e1000Chat", (), ""),
    # The SEC M-1 look-alikes: a built-in name plus an invisible character.
    *[("Claude" + chr(point), (), "name-chars") for point in (0x034F, 0xE0020, 0xFE0F, 0x17B4, 0x180B, 0x3164,
                                                              0x115F, 0x1160, 0x2800, 0xE0001, 0xFFF9)],
    ("\u3164", (), "name-chars"), ("\u2800\u2800", (), "name-chars"), ("\u115f\u1160", (), "name-chars"),
    ("\U000e0041\U000e0042", (), "name-chars"), ("\u200b", (), "name-chars"),
    # At least one letter or digit (Unicode L* or N*).
    ("!!!", (), "name-chars"), ("-", (), "name-chars"), ("\U0001f916", (), "name-chars"), ("\u2603 \u2604", (), "name-chars"),
    ("1", (), ""), ("\u0661", (), ""), ("\u2460", (), ""), ("\u216b", (), ""), ("\u00e9", (), ""), ("\u4e2d", (), ""),
    ("\U0001d400", (), ""), ("!\u05d0", (), ""), ("\U0001f916 Bot", (), ""), ("#1", (), ""),
    ("\u0301", (), "name-chars"), ("e\u0301", (), ""),
    # Round 3 (SEC I-5): every Cf (format) and Co (private-use) character, also outside
    # Default_Ignorable; their neighbours stay allowed.
    *[("Le" + chr(point) + "Chat", (), "name-chars") for point in (
        0x0600, 0x0605, 0x06DD, 0x070F, 0x0890, 0x0891, 0x08E2, 0x110BD, 0x110CD, 0x13430, 0x1343F,
        0xE000, 0xF8FF, 0xF0000, 0xFFFFD, 0x100000, 0x10FFFD)],
    *[("Claude" + chr(point), (), "name-chars") for point in (0x070F, 0x0600, 0xE000)],
    ("Le\u0606Chat", (), ""), ("Le\u06deChat", (), ""), ("Le\u070eChat", (), ""), ("Le\u08e3Chat", (), ""),
    ("Le\uf900Chat", (), ""), ("Le\U00013440Chat", (), ""), ("Le\U000ffffeChat", (), ""),
    # Unassigned (Cn) code points are not checked: they render as a box.
    ("Le\u0378Chat", (), ""), ("Le\U0002fffeChat", (), ""), ("Le\U000e0080Chat", (), "name-chars"),
    # Taken: a built-in name, Ollama or another added site, in any case.
    ("Claude", (), "name-taken"), ("claude", (), "name-taken"), ("CHATGPT", (), "name-taken"),
    ("grok", (), "name-taken"), ("Gemini", (), "name-taken"), ("github copilot", (), "name-taken"),
    ("Microsoft COPILOT", (), "name-taken"), ("Local web UI (open webui)", (), "name-taken"),
    ("Ollama", (), "name-taken"), ("OLLAMA", (), "name-taken"), ("Copilot", (), ""), ("Local web UI", (), ""),
    ("Mistral", ("mistral",), "name-taken"), ("mistral", ("Other", "MISTRAL"), "name-taken"),
    ("\u00c4", ("\u00e4",), "name-taken"), ("\u0130", ("i\u0307",), "name-taken"),
    # Qt's JS engine lowers per code point (no final-sigma rule), and so does the port.
    ("\u03a3\u0391\u03a3", ("\u03c3\u03b1\u03c2",), ""), ("\u03a3\u0391\u03a3", ("\u03c3\u03b1\u03c3",), "name-taken"),
    ("Claude ", (), "name-chars"),
]

# (address, code, class), checked in the order of the 006 plan section 3.3. Valid
# addresses have code "" and their class; refused ones code and class "".
P, L, V = "public", "loopback", "private"
USER_URL_CASES = [
    ("https://chat.example.org/chat", "", P), ("https://a.example.com", "", P), ("HTTPS://A.Example.COM:8443/x?q=1#f", "", P),
    ("https://nas.local/", "", P), ("https://nas.lan", "", P), ("https://example.com1/", "", P), ("https://a.example.com./", "", P),
    ("https://a.example.com/@x", "", P), ("https://a.example.com/%41'~!$()*,;=", "", P), ("https://xn--mnchen-3ya.example/", "", P),
    ("", "url-empty", ""),
    ("https://a.example.com/" + "a" * 2026, "", P), ("https://a.example.com/" + "a" * 2027, "too-long", ""),
    ("https://a.example.com/" + "\U0001f600" * 1014, "too-long", ""),
    ("https://a.example.com/ x", "whitespace", ""), ("https://a.example.com/\t", "whitespace", ""),
    ("https://a.example.com/ ", "whitespace", ""), ("https://a.example.com/ ", "whitespace", ""),
    ("https://a.example.com/　", "whitespace", ""), ("https://a.example.com/﻿", "whitespace", ""),
    ("https://a.example.com/\x00", "whitespace", ""), ("https://a.example.com/\x7f", "whitespace", ""),
    (" https://a.example.com/", "whitespace", ""), ("https://user@a.example.com/ ", "whitespace", ""),
    ("https://a.example.com/\x85", "url-chars", ""), ("https://a.example.com/ü", "url-chars", ""),
    ("https://exämple.com/", "url-chars", ""), ("https://a.example.com/\U0001f600", "url-chars", ""),
    ("https://a.example.com/​", "url-chars", ""), ("https://a.example.com/‮", "url-chars", ""),
    ("https://a.example.com/\ud800", "url-chars", ""), ("https://user@a.example.com/ü", "url-chars", ""),
    *[("https://a.example.com/" + char, "url-chars", "") for char in '"\\<>`{}|^'],
    ("https://user@a.example.com/", "userinfo", ""), ("https://a:b@a.example.com/", "userinfo", ""),
    ("http://user@a.example.com/", "userinfo", ""), ("ftp://user@a.example.com/", "userinfo", ""),
    ("https://@a.example.com/", "userinfo", ""), ("http://user@localhost:3000/", "userinfo", ""),
    ("http://x@[fd00::1]/", "userinfo", ""),
    ("a.example.com", "malformed", ""), ("//a.example.com/", "malformed", ""), ("1https://a.example.com/", "malformed", ""),
    ("localhost:3000", "scheme", ""), ("192.168.1.20:3000", "malformed", ""),
    # 006: http is no longer refused at the scheme step; only DNS names are refused over http.
    ("http://a.example.com/", "http-not-allowed", ""), ("HTTP://a.example.com/", "http-not-allowed", ""),
    ("http://localhost/", "", L), ("http:x", "malformed", ""), ("http:/x", "malformed", ""), ("http://", "malformed", ""),
    ("ftp://a.example.com/", "scheme", ""), ("javascript:alert(1)", "scheme", ""), ("data:text/html,x", "scheme", ""),
    ("about:blank", "scheme", ""), ("file:///etc/passwd", "scheme", ""), ("httpss://a.example.com/", "scheme", ""),
    ("ws://localhost:3000/", "scheme", ""), ("ftp://192.168.1.20/", "scheme", ""),
    ("https:a.example.com", "malformed", ""), ("https:///x", "malformed", ""), ("https://", "malformed", ""),
    ("https://[fd00::1]/", "", V), ("https://[::2]/", "ip-literal", ""), ("https://a_b.example.com/", "malformed", ""),
    ("https://a.example.com%2f/", "malformed", ""), ("https://.a.example.com/", "malformed", ""),
    ("https://a..example.com/", "malformed", ""), ("https://a.example.com:0/", "malformed", ""),
    ("https://a.example.com:65536/", "malformed", ""), ("https://a.example.com:/", "malformed", ""),
    # Step 9: this computer, only as localhost, 127.0.0.1 or [::1], http or https, any port.
    ("https://[::1]/", "", L), ("https://localhost/", "", L), ("https://127.0.0.1/", "", L),
    ("http://localhost:3000/", "", L), ("https://localhost:8443/", "", L), ("http://127.0.0.1:8080/", "", L),
    ("http://[::1]:8080/", "", L), ("https://[::1]:1/", "", L), ("HTTP://LOCALHOST:3000/", "", L),
    ("http://Localhost/", "", L), ("http://localhost:080/", "", L), ("https://localhost:443/", "", L),
    ("http://localhost:65535/x?y#z", "", L), ("http://localhost:0/", "malformed", ""),
    ("http://localhost:65536/", "malformed", ""), ("http://localhost:/", "malformed", ""),
    # Step 10: every other spelling of this computer. Dotless names are this computer too.
    ("https://LOCALHOST./", "loopback-not-allowed", ""), ("http://localhost./", "loopback-not-allowed", ""),
    ("https://intranet/", "loopback-not-allowed", ""), ("http://nas/", "loopback-not-allowed", ""),
    ("https://a.localhost/", "loopback-not-allowed", ""), ("http://a.localhost/", "loopback-not-allowed", ""),
    ("https://a.localhost.localdomain/", "loopback-not-allowed", ""), ("http://localhost.localdomain/", "loopback-not-allowed", ""),
    ("https://ip6-loopback/", "loopback-not-allowed", ""), ("http://ip6-localhost/", "loopback-not-allowed", ""),
    ("https://127.1/", "loopback-not-allowed", ""), ("http://127.1/", "loopback-not-allowed", ""),
    ("http://127.0.0.2/", "loopback-not-allowed", ""), ("https://127.255.255.255/", "loopback-not-allowed", ""),
    ("http://127.0.0.1./", "loopback-not-allowed", ""), ("https://0x7f000001/", "loopback-not-allowed", ""),
    ("https://017700000001/", "loopback-not-allowed", ""), ("https://0x7f.1/", "loopback-not-allowed", ""),
    ("https://0/", "loopback-not-allowed", ""), ("https://0.0.0.0/", "loopback-not-allowed", ""),
    ("http://0.0.0.0:3000/", "loopback-not-allowed", ""),
    ("https://1.2.3.256/", "loopback-not-allowed", ""), ("https://1.2.3.08/", "loopback-not-allowed", ""),
    ("https://1.2.3.4.5/", "loopback-not-allowed", ""), ("https://example.0x/", "loopback-not-allowed", ""),
    ("https://example.123/", "loopback-not-allowed", ""), ("https://0x08080808/", "loopback-not-allowed", ""),
    ("https://134744072/", "loopback-not-allowed", ""), ("http://3232235777/", "loopback-not-allowed", ""),
    ("http://192.168.1.256/", "loopback-not-allowed", ""),
    # Step 11: IPv4 literals. The edges of each private range, link-local, and the rest.
    ("http://10.0.0.0/", "", V), ("http://10.255.255.255/", "", V), ("https://10.0.0.1/", "", V),
    ("http://9.255.255.255/", "ip-literal", ""), ("http://11.0.0.0/", "ip-literal", ""),
    ("http://172.15.255.255/", "ip-literal", ""), ("http://172.16.0.0/", "", V), ("https://172.16.0.1/", "", V),
    ("http://172.31.255.255/", "", V), ("http://172.32.0.0/", "ip-literal", ""),
    ("http://192.167.255.255/", "ip-literal", ""), ("http://192.168.0.0/", "", V),
    ("https://192.168.1.1/", "", V), ("http://192.168.255.255/", "", V), ("http://192.169.0.0/", "ip-literal", ""),
    ("http://192.168.1.20:3000/", "", V), ("https://10.0.0.5/", "", V),
    ("https://169.254.169.254/", "link-local", ""), ("http://169.254.169.254/", "link-local", ""),
    ("http://169.254.0.0/", "link-local", ""), ("http://169.253.255.255/", "ip-literal", ""),
    ("http://169.255.0.0/", "ip-literal", ""),
    ("http://100.64.0.1/", "ip-literal", ""), ("https://100.127.255.255/", "ip-literal", ""),
    ("https://1.2.3.4/", "ip-literal", ""), ("http://8.8.8.8/", "ip-literal", ""), ("https://8.8.8.8/", "ip-literal", ""),
    ("http://255.255.255.255/", "ip-literal", ""), ("http://224.0.0.1/", "ip-literal", ""),
    ("http://0.1.2.3/", "ip-literal", ""),
    # Non-canonical IPv4: refused with ip-form, whatever the range.
    ("http://192.168.1.020/", "ip-form", ""), ("http://0xc0.168.1.1/", "ip-form", ""),
    ("http://192.168.1/", "ip-form", ""), ("http://192.168.1.1./", "ip-form", ""),
    ("http://192.168.01.1/", "ip-form", ""), ("http://192.168.1.0x1/", "ip-form", ""),
    ("http://10.1/", "ip-form", ""), ("https://10.1/", "ip-form", ""), ("https://8.8.8.8./", "ip-form", ""),
    ("https://0x8.0x8.0x8.0x8/", "ip-form", ""), ("https://8.8.2056/", "ip-form", ""),
    ("https://0xa.0.0.1:8443/", "ip-form", ""), ("http://010.0.0.1/", "ip-form", ""),
    ("http://169.254.169.0254/", "ip-form", ""),
    # Step 12: bracketed IPv6 literals other than [::1].
    ("http://[fd00::1]/", "", V), ("http://[FD00::1]/", "", V), ("http://[fd00::20]:3000/", "", V),
    ("http://[fd00:0:0:0:0:0:0:1]/", "ip-form", ""), ("http://[fd00::0:1]/", "ip-form", ""),
    ("http://[fd00:0:1:1:1:1:1:1]/", "", V), ("http://[fd00::1:1:1:1:1:1]/", "ip-form", ""),
    ("http://[fd00:1:0:0:1:0:0:1]/", "ip-form", ""), ("http://[fd00:1::1:0:0:1]/", "", V),
    ("http://[fd00:1:0:0:1::1]/", "ip-form", ""),
    ("http://[fd00:0:0:1:0:0:0:1]/", "ip-form", ""), ("http://[fd00:0:0:1::1]/", "", V),
    ("http://[fd00::1:0:0:0:1]/", "ip-form", ""),
    ("http://[fd00::1:0:0:1:1]/", "", V), ("http://[fd00:0:0:1::1:1]/", "ip-form", ""),
    ("http://[fd00:0000::1]/", "ip-form", ""), ("http://[fd00::01]/", "ip-form", ""),
    ("http://[fc00::]/", "", V), ("http://[fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff]/", "", V),
    ("http://[FDFF:FFFF:FFFF:FFFF:FFFF:FFFF:FFFF:FFFF]:65535/", "", V), ("http://[fbff::1]/", "ip-literal", ""),
    ("http://[fe00::1]/", "ip-literal", ""),
    ("http://[fe80::1]/", "link-local", ""), ("https://[febf::1]/", "link-local", ""), ("http://[fec0::1]/", "ip-literal", ""),
    # Round 2 (SEC LOW-1): fd00:ec2::/32 is the cloud (AWS) IPv6 metadata range, refused as link-local.
    ("http://[fd00:ec2::254]/", "link-local", ""), ("https://[fd00:ec2::254]/", "link-local", ""),
    ("http://[fd00:ec2::]/", "link-local", ""), ("http://[fd00:ec2:ffff:ffff:ffff:ffff:ffff:ffff]:8080/", "link-local", ""),
    ("http://[FD00:EC2::254]/", "link-local", ""), ("http://[fd00:0ec2::254]/", "ip-form", ""),
    ("http://[fd00:ec1:ffff:ffff:ffff:ffff:ffff:ffff]/", "", V), ("http://[fd00:ec3::1]/", "", V),
    ("http://[fd01:ec2::1]/", "", V), ("http://[fd00::ec2]/", "", V),
    ("http://[fe80::1%25eth0]/", "malformed", ""), ("http://[fe80::1%eth0]/", "malformed", ""),
    ("http://[2001:db8::1]/", "ip-literal", ""), ("https://[2606:4700::1111]/", "ip-literal", ""),
    ("http://[::ffff:192.168.1.1]/", "malformed", ""), ("http://[::ffff:c0a8:101]/", "ip-literal", ""),
    ("http://[::192.168.1.1]/", "malformed", ""), ("http://[::]/", "ip-literal", ""), ("http://[ff02::1]/", "ip-literal", ""),
    ("http://[0:0:0:0:0:0:0:1]/", "ip-form", ""), ("http://[::01]/", "ip-form", ""), ("http://[0::1]/", "ip-form", ""),
    ("http://[::1]./", "malformed", ""), ("http://[::1]x/", "malformed", ""),
    # Not an IPv6 address at all, but only hex and colons: ip-form, like any other odd literal.
    ("http://[fd00::1::2]/", "ip-form", ""), ("http://[fd000::1]/", "ip-form", ""), ("http://[1:2:3:4:5:6:7:8:9]/", "ip-form", ""),
    ("http://[fd00:1:2:3:4:5:6:7::]/", "ip-form", ""), ("http://[:fd00::1]/", "ip-form", ""), ("http://[fd00::1:]/", "ip-form", ""),
    ("http://[:::]/", "ip-form", ""), ("http://[fd00]/", "ip-form", ""), ("http://[fd00:1:2:3:4:5:6]/", "ip-form", ""),
    ("http://[fd00:0000:0000:0000:0000:0000:0000:0001]/", "ip-form", ""),
    ("http://[fd00:00000:0000:0000:0000:0000:0000:0001]/", "malformed", ""),
    ("http://[]/", "malformed", ""), ("http://[:]/", "malformed", ""), ("http://[fd00::g]/", "malformed", ""),
    ("http://[fd00::1/", "malformed", ""), ("http://fd00::1/", "malformed", ""), ("http://[[fd00::1]]/", "malformed", ""),
    ("http://[fd00::1]:/", "malformed", ""),
    # Ports, explicit or by default, on each class.
    ("http://192.168.1.20:0/", "malformed", ""), ("http://192.168.1.20:65536/", "malformed", ""),
    ("http://192.168.1.20:1/", "", V), ("http://192.168.1.20:65535/", "", V), ("http://192.168.1.20:80/", "", V),
    ("https://192.168.1.20:443/", "", V), ("http://192.168.1.20:00080/", "", V), ("http://192.168.1.20:123456/", "malformed", ""),
    ("http://[fd00::1]:0/", "malformed", ""), ("http://[fd00::1]:65536/", "malformed", ""),
    ("http://[fd00::1]:1/", "", V), ("http://[fd00::1]:65535/", "", V), ("http://[::1]:65536/", "malformed", ""),
    # Step 13: names. http only for this computer and home-network IP literals.
    ("http://nas.local/", "http-not-allowed", ""), ("http://nas.local", "http-not-allowed", ""),
    ("http://nas.lan/", "http-not-allowed", ""), ("https://nas.local", "", P), ("http://example.com:8080/", "http-not-allowed", ""),
    ("http://a.example.com./", "http-not-allowed", ""), ("http://192.168.1.20.nip.io/", "http-not-allowed", ""),
    ("https://192.168.1.20.nip.io/", "", P),
]


@pytest.mark.parametrize(("name", "others", "code"), NAME_CASES)
def test_user_site_name_codes(name, others, code):
    assert backup.user_site_name_error(name, others) == code


@pytest.mark.parametrize(("url", "code", "kind"), USER_URL_CASES)
def test_user_site_url_codes(url, code, kind):
    assert backup.user_site_url_error(url) == code
    assert backup.address_class(url) == kind
    assert (code == "") == (kind != "")


def test_the_user_site_lists_have_no_repeated_case():
    assert len({(name, others) for name, others, _ in NAME_CASES}) == len(NAME_CASES)
    assert len({url for url, _, _ in USER_URL_CASES}) == len(USER_URL_CASES)


def category_ranges(categories):
    """Comma-separated "start-end" hex ranges of the code points in ``categories`` (prefixes)."""
    ranges, start = [], None
    for point in range(0x110000):
        inside = unicodedata.category(chr(point)).startswith(categories)
        if inside and start is None:
            start = point
        elif not inside and start is not None:
            ranges.append((start, point - 1))
            start = None
    if start is not None:
        ranges.append((start, 0x10FFFF))
    return ",".join(f"{low:x}" if low == high else f"{low:x}-{high:x}" for low, high in ranges)


def test_the_category_tables_are_unicode_16():
    """FORMAT_PRIVATE_RANGES is Cf + Co and LETTER_DIGIT_RANGES L* + N*, as Unicode 16.0 has them."""
    if unicodedata.unidata_version != "16.0.0":
        pytest.skip(f"this Python has Unicode {unicodedata.unidata_version}; the tables are Unicode 16.0.0")
    assert backup.FORMAT_PRIVATE_RANGES == category_ranges(("Cf", "Co"))
    assert backup.LETTER_DIGIT_RANGES == category_ranges(("L", "N"))


def js_ranges(name):
    match = re.search(rf'^var {name} =\n((?:    "[^"]*"(?: \+)?\n)+)', js_text("ChatSites.js"), re.M)
    assert match, f"ChatSites.js: var {name} is missing"
    return "".join(re.findall(r'"([^"]*)"', match.group(1)))


@pytest.mark.parametrize("name", ["FORMAT_PRIVATE_RANGES", "LETTER_DIGIT_RANGES"])
def test_the_category_tables_match_chat_sites_js(name):
    """One table for both ports, so the helper and the widget can't drift (SEC I-5)."""
    assert js_ranges(name) == getattr(backup, name)


def test_the_name_rule_uses_the_tables_not_the_runtime():
    text = SOURCE.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(?:import|from)\s+unicodedata\b|\bunicodedata\s*\.", text, re.M)


USER_SITE_PARITY_QML = """import QtQuick
import QtTest
import "ChatSites.js" as ChatSites

TestCase {
    name: "UserSiteParity"
    function code(result) {
        return typeof result === "string" ? result : result.error
    }
    function test_dump() {
        var names = %s
        var urls = %s
        var results = names.map(function (item) {
            var others = item[1].map(function (name, index) {
                return { id: "user-0000000" + index, name: name, url: "https://other.example.com/" }
            })
            return code(ChatSites.userSiteNameError(item[0], others))
        }).concat(urls.map(function (url) {
            return code(ChatSites.userSiteUrlError(url))
        })).concat(urls.map(function (url) {
            return ChatSites.addressClass(url)
        }))
        console.log("PARITY " + JSON.stringify(results))
    }
}
"""


def test_the_user_site_port_gives_the_same_codes_as_chat_sites_js(tmp_path):
    """userSiteNameError (others as added-site entries), userSiteUrlError and addressClass, case by case."""
    names = [[name, list(others)] for name, others, _ in NAME_CASES]
    urls = [url for url, _, _ in USER_URL_CASES]
    results = chat_sites_js_results(tmp_path, USER_SITE_PARITY_QML % (json.dumps(names), json.dumps(urls)))
    expected = ([backup.user_site_name_error(name, others) for name, others, _ in NAME_CASES]
                + [backup.user_site_url_error(url) for url in urls] + [backup.address_class(url) for url in urls])
    assert results == expected


# --- task 006: canonical literals, the wide parser and the address fuzz ---------------------------

@pytest.mark.parametrize(("host", "canonical"), [
    ("192.168.1.20", True), ("0.0.0.0", True), ("255.255.255.255", True), ("10.0.0.1", True),
    ("192.168.1.020", False), ("192.168.01.1", False), ("0xc0.168.1.1", False), ("3232235777", False),
    ("192.168.1", False), ("127.1", False), ("192.168.1.1.", False), ("192.168.1.256", False),
    ("1.2.3.4.5", False), ("1000.1.1.1", False), ("00.1.1.1", False), ("", False), ("a.b.c.d", False),
])
def test_canonical_ipv4(host, canonical):
    assert backup.canonical_ipv4(host) is canonical


@pytest.mark.parametrize(("text", "serialized"), [
    ("fd00::1", "fd00::1"), ("FD00::1", "fd00::1"), ("fd00:0:0:0:0:0:0:1", "fd00::1"), ("fd00::0:1", "fd00::1"),
    ("fd00:0:1:1:1:1:1:1", "fd00:0:1:1:1:1:1:1"), ("fd00::1:1:1:1:1:1", "fd00:0:1:1:1:1:1:1"),
    ("fd00:1:0:0:1:0:0:1", "fd00:1::1:0:0:1"), ("fd00:0:0:1:0:0:0:1", "fd00:0:0:1::1"),
    ("::", "::"), ("::1", "::1"), ("0:0:0:0:0:0:0:0", "::"), ("1::", "1::"), ("1:0:0:0:0:0:0:0", "1::"),
    ("0001:00:0:0:0:0:0:000a", "1::a"), ("fc00::", "fc00::"), ("1:2:3:4:5:6:7:8", "1:2:3:4:5:6:7:8"),
    ("::ffff:c0a8:101", "::ffff:c0a8:101"),  # WHATWG keeps hex; Python 3.13+ ipaddress would write dots.
    ("", ""), (":", ""), (":::", ""), ("1::2::3", ""), ("12345::", ""), ("1:2:3:4:5:6:7", ""),
    ("1:2:3:4:5:6:7:8:9", ""), ("1:2:3:4:5:6:7:8::", ""), (":1::", ""), ("::1:", ""), ("g::", ""),
    ("::1.2.3.4", ""), ("fe80::1%eth0", ""),
    # Brackets are optional and kept as given, as ChatSites.js canonicalIpv6 does (006 phase 2).
    ("[fd00::1]", "[fd00::1]"), ("[FD00:0::1]", "[fd00::1]"), ("[::]", "[::]"), ("[fd00::1", ""), ("fd00::1]", ""),
    ("[]", ""), ("[", ""), ("[[fd00::1]]", ""),
])
def test_canonical_ipv6(text, serialized):
    assert backup.canonical_ipv6(text) == serialized


def random_groups(rng, first=None):
    """8 IPv6 groups, mostly 0 or small, so every compression case comes up."""
    groups = [rng.choice((0, 0, 0, 1, 2, 0xA, 0xFF, 0x100, rng.randrange(0x10000))) for _ in range(8)]
    if first is not None:
        groups[0] = first
    return groups


def test_canonical_ipv6_matches_ipaddress():
    """Few hundred 8-group values: the module's serialization is ipaddress's (outside ::ffff:0:0/96)."""
    rng = random.Random(60061)
    checked = 0
    for _ in range(600):
        groups = random_groups(rng)
        address = ipaddress.IPv6Address(":".join(format(group, "x") for group in groups))
        if address.ipv4_mapped is not None:
            continue
        assert backup.canonical_ipv6(address.exploded) == address.compressed, address.exploded
        assert backup.canonical_ipv6(address.compressed) == address.compressed
        checked += 1
    assert checked > 500


IPV6_FIRST_GROUPS = (0xFD00, 0xFC00, 0xFDFF, 0xFBFF, 0xFE00, 0xFE80, 0xFEBF, 0xFEC0, 0xFF02, 0x2001, 0x0)


def ipv6_spellings(rng, groups):
    """Ways to write ``groups``: canonical, upper case, full, zero-padded, wrong compressions."""
    words = [format(group, "x") for group in groups]
    canonical = backup.canonical_ipv6(":".join(words))
    spellings = {canonical, canonical.upper(), ":".join(words), ":".join(format(group, "04x") for group in groups)}
    zeros = [index for index, group in enumerate(groups) if group == 0]
    for index in zeros:  # Compress a single zero group, or a run that isn't the first longest.
        end = index
        while end < 8 and groups[end] == 0:
            end += 1
        for stop in range(index + 1, end + 1):
            spellings.add(":".join(words[:index]) + "::" + ":".join(words[stop:]))
    spellings.add(canonical.replace("::", ":0::", 1) if "::" in canonical and canonical != "::" else canonical + ":")
    return sorted(spellings, key=lambda text: (len(text), text))[:rng.randint(4, 8)]


def ipv6_expected(literal):
    """(code, class) for ``[literal]`` from ipaddress, independent of the module."""
    try:
        address = ipaddress.IPv6Address(literal)
    except ValueError:
        return ("ip-form", "")
    if address.ipv4_mapped is not None:
        return None  # Python 3.13+ writes these with dots; test_canonical_ipv6 pins them.
    if literal.lower() != address.compressed:
        return ("ip-form", "")
    if address == ipaddress.IPv6Address("::1"):
        return ("", "loopback")
    if address in ipaddress.IPv6Network("fe80::/10") or address in ipaddress.IPv6Network("fd00:ec2::/32"):
        return ("link-local", "")
    if address in ipaddress.IPv6Network("fc00::/7"):
        return ("", "private")
    return ("ip-literal", "")


def test_ipv6_addresses_get_the_code_ipaddress_gives():
    rng = random.Random(60062)
    for index in range(400):
        groups = random_groups(rng, rng.choice(IPV6_FIRST_GROUPS))
        if index % 8 == 0:  # Around the metadata range (LOW-1): fd00:ec2::/32 and its neighbours.
            groups[:2] = [0xFD00, rng.choice((0x0EC1, 0x0EC2, 0x0EC2, 0x0EC3))]
        for literal in ipv6_spellings(rng, groups):
            url = f"{rng.choice(('http', 'https'))}://[{literal}]/"
            if len(literal) > 39:
                assert backup.user_site_url_error(url) == "malformed", url
                continue
            expected = ipv6_expected(literal)
            if expected is None:
                continue
            assert (backup.user_site_url_error(url), backup.address_class(url)) == expected, url


def ipv4_expected(host):
    """(code, class) for a canonical dotted quad from ipaddress, independent of the module."""
    address = ipaddress.IPv4Address(host)
    if host in ("127.0.0.1",):
        return ("", "loopback")
    if address in ipaddress.IPv4Network("127.0.0.0/8") or address in ipaddress.IPv4Network("0.0.0.0/32"):
        return ("loopback-not-allowed", "")
    if address in ipaddress.IPv4Network("169.254.0.0/16"):
        return ("link-local", "")
    if any(address in ipaddress.IPv4Network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
        return ("", "private")
    return ("ip-literal", "")


IPV4_EDGES = (0, 1, 9, 10, 11, 99, 100, 126, 127, 128, 168, 169, 171, 172, 173, 191, 192, 193, 223, 224, 254, 255)
IPV4_SECOND = (0, 1, 15, 16, 17, 30, 31, 32, 63, 64, 127, 128, 167, 168, 169, 253, 254, 255)


def random_quad(rng):
    return [rng.choice(IPV4_EDGES), rng.choice(IPV4_SECOND), rng.choice((0, 1, 20, 255, rng.randrange(256))),
            rng.choice((0, 1, 20, 254, 255, rng.randrange(256)))]


def test_dotted_quads_get_the_code_ipaddress_gives():
    rng = random.Random(60063)
    for _ in range(2000):
        host = ".".join(map(str, random_quad(rng)))
        url = f"{rng.choice(('http', 'https'))}://{host}:{rng.randint(1, 65535)}/"
        assert (backup.user_site_url_error(url), backup.address_class(url)) == ipv4_expected(host), url


def ipv4_spellings(rng, quad):
    """A dotted quad and the other forms a browser reads as the same address."""
    value = (quad[0] << 24) | (quad[1] << 16) | (quad[2] << 8) | quad[3]
    return [
        ".".join(map(str, quad)), ".".join(map(str, quad)) + ".",
        ".".join(f"0{part:o}" if part and rng.random() < 0.5 else str(part) for part in quad),
        ".".join(hex(part) if rng.random() < 0.5 else str(part) for part in quad),
        f"{quad[0]}.{quad[1]}.{(quad[2] << 8) | quad[3]}", f"{quad[0]}.{value & 0xFFFFFF}", str(value), hex(value),
        ".".join(map(str, quad[:3])) + ".0" + str(quad[3]),
    ]


URL_FUZZ_NAMES = ("a.example.com", "nas.local", "nas.lan", "nas", "intranet", "localhost", "LocalHost", "localhost.",
                  "a.localhost", "localhost.localdomain", "ip6-localhost", "192.168.1.20.nip.io", "example.123",
                  "example.0x", "xn--mnchen-3ya.example", "a_b.example.com", "a..b.example.com", ".example.com")
URL_FUZZ_PORTS = ("", "", "", ":0", ":1", ":80", ":443", ":3000", ":8080", ":65535", ":65536", ":00080", ":", ":999999")
URL_FUZZ_SCHEMES = ("http", "https", "http", "https", "HTTP", "Https", "ftp", "ws")
URL_FUZZ_TAILS = ("/", "", "/chat?x=1#y", "?q", "#f", "/a/b")


def url_fuzz_cases():
    """Seeded added-site addresses: every class, IPv4 and IPv6 spellings, ports and schemes."""
    rng = random.Random(6006)
    hosts = list(URL_FUZZ_NAMES) + ["127.0.0.1", "[::1]", "[::1]", "127.0.0.2", "0.0.0.0", "[::]"]
    for _ in range(250):
        hosts.extend(ipv4_spellings(rng, random_quad(rng)))
    for _ in range(250):
        hosts.extend(f"[{literal}]" for literal in ipv6_spellings(rng, random_groups(rng, rng.choice(IPV6_FIRST_GROUPS))))
    hosts.extend(("[fe80::1%25eth0]", "[::ffff:192.168.1.1]", "[fd00::1", "fd00::1]", "[]", "[fd00::g]", "[:]"))
    metadata = random.Random(60065)  # Round 2 (LOW-1): fd00:ec2::/32 and its neighbours, its own seed.
    for _ in range(40):
        groups = random_groups(metadata, 0xFD00)
        groups[1] = metadata.choice((0x0EC1, 0x0EC2, 0x0EC2, 0x0EC3))
        hosts.extend(f"[{literal}]" for literal in ipv6_spellings(metadata, groups))
    cases = []
    for host in hosts:
        for _ in range(8 if host in URL_FUZZ_NAMES else 2):
            cases.append(rng.choice(URL_FUZZ_SCHEMES) + "://" + host + rng.choice(URL_FUZZ_PORTS)
                         + rng.choice(URL_FUZZ_TAILS))
    return list(dict.fromkeys(cases))


def test_the_url_fuzz_covers_every_code_and_class():
    cases = url_fuzz_cases()
    assert len(cases) > 4000
    seen = {backup.user_site_url_error(url) for url in cases} | {backup.address_class(url) for url in cases}
    assert seen >= {"", "public", "loopback", "private", "scheme", "malformed", "loopback-not-allowed",
                    "ip-form", "link-local", "ip-literal", "http-not-allowed"}, seen


URL_FUZZ_QML = """import QtQuick
import QtTest
import "ChatSites.js" as ChatSites

TestCase {
    name: "UrlFuzz"
    function code(result) {
        return typeof result === "string" ? result : result.error
    }
    function test_dump() {
        var urls = %s
        console.log("PARITY " + JSON.stringify(urls.map(function (url) {
            return [code(ChatSites.userSiteUrlError(url)), ChatSites.addressClass(url)]
        })))
    }
}
"""


def test_the_url_fuzz_gives_the_same_codes_and_classes_as_chat_sites_js(tmp_path):
    """Thousands of seeded addresses (006 classes, IPv6 spellings, ports) through both ports."""
    cases = url_fuzz_cases()
    results = chat_sites_js_results(tmp_path, URL_FUZZ_QML % json.dumps(cases))
    differences = [(url, found, [backup.user_site_url_error(url), backup.address_class(url)])
                   for url, found in zip(cases, results)
                   if found != [backup.user_site_url_error(url), backup.address_class(url)]]
    assert len(results) == len(cases)
    assert differences == [], differences[:40]


HELPER_PARITY_QML = """import QtQuick
import QtTest
import "ChatSites.js" as ChatSites
import "ChatSitesGolden.js" as Golden

TestCase {
    name: "HelperParity"
    function shape(parsed) {
        return parsed === null ? null : [parsed.scheme, parsed.host, parsed.port]
    }
    function test_dump() {
        var urls = Golden.ADDRESSES.concat(%s)
        var literals = %s
        console.log("PARITY " + JSON.stringify([
            Golden.ADDRESSES.length,
            urls.map(function (url) { return [shape(ChatSites.parseUrl(url)), shape(ChatSites.parseUserUrl(url))] }),
            literals.map(function (text) { return [ChatSites.canonicalIpv6(text), ChatSites.canonicalIpv4(text)] })
        ]))
    }
}
"""


def golden_addresses():
    """ChatSitesGolden.js ADDRESSES (005's recorded built-in table), read from the file."""
    text = (ROOT / "tests" / "qml" / "ChatSitesGolden.js").read_text(encoding="utf-8")
    block = re.search(r"(?ms)^var ADDRESSES = \[\n(.*?)^\]", text)
    assert block, "ChatSitesGolden.js: var ADDRESSES is missing"
    return json.loads("[" + block.group(1).rstrip().rstrip(",") + "]")


def helper_literals():
    """IPv4 and IPv6 literal texts, bare and bracketed, for the canonical helpers."""
    rng = random.Random(60064)
    literals = []
    for _ in range(300):
        for literal in ipv6_spellings(rng, random_groups(rng, rng.choice(IPV6_FIRST_GROUPS))):
            literals += [literal, "[" + literal + "]", literal.upper()]
    for _ in range(300):
        literals += ipv4_spellings(rng, random_quad(rng))
    literals += ["", "[", "]", "[]", "[[::1]]", "[::1", "::1]", "::ffff:1.2.3.4", "1::2::3", ":::", "g::", "0x7f.1"]
    return list(dict.fromkeys(literals))


def test_the_parsers_and_canonical_helpers_match_chat_sites_js(tmp_path):
    """parseUrl, parseUserUrl, canonicalIpv6 and canonicalIpv4, value by value, against the Python port.

    006 phase 2 (hostOf decision, condition a): for every address whose authority
    isn't bracketed, the wide parser gives exactly what parseUrl gives, in both
    ports, over the golden table's addresses and the whole fuzz corpus.
    """
    shutil.copy2(ROOT / "tests" / "qml" / "ChatSitesGolden.js", tmp_path / "ChatSitesGolden.js")
    fuzz = url_fuzz_cases() + [url for url, _, _ in USER_URL_CASES]
    literals = helper_literals()
    count, parsed, canonical = chat_sites_js_results(tmp_path, HELPER_PARITY_QML % (json.dumps(fuzz), json.dumps(literals)))
    urls = golden_addresses() + fuzz
    assert count == len(golden_addresses()) > 50 and len(parsed) == len(urls)
    shape = (lambda found: None if found is None else list(found))
    differences, bracketless = [], 0
    for url, (narrow, wide) in zip(urls, parsed):
        expected = [shape(backup.parse_url(url)), shape(backup.parse_user_url(url))]
        if [narrow, wide] != expected:
            differences.append((url, [narrow, wide], expected))
        match = re.match(r"[A-Za-z][A-Za-z0-9+.\-]*://([^/?#]*)", url)
        if not (match and match.group(1).startswith("[")):
            bracketless += 1
            if wide != narrow:
                differences.append((url, "wide parser differs from parseUrl", narrow, wide))
        elif narrow is not None and wide != narrow:
            differences.append((url, "[::1] read differently", narrow, wide))
    assert bracketless > 3000
    for text, found in zip(literals, canonical):
        if found != [backup.canonical_ipv6(text), backup.canonical_ipv4(text)]:
            differences.append((text, found, [backup.canonical_ipv6(text), backup.canonical_ipv4(text)]))
    assert differences == [], differences[:40]


def test_the_wide_parser_reads_every_non_bracketed_address_as_parse_url():
    """Condition (a) on the Python side, without qmltestrunner."""
    for url in golden_addresses() + url_fuzz_cases() + [url for url, _, _ in USER_URL_CASES]:
        match = re.match(r"[A-Za-z][A-Za-z0-9+.\-]*://([^/?#]*)", url)
        narrow = backup.parse_url(url)
        if not (match and match.group(1).startswith("[")) or narrow is not None:
            assert backup.parse_user_url(url) == narrow, url


def test_parse_url_still_reads_only_the_loopback_bracket():
    """Built-ins keep the narrow parser (006 M-A); only added sites read other IPv6 literals."""
    assert backup.parse_url("http://[fd00::1]:3000/") is None
    assert backup.parse_url("https://[FD00::1]/") is None
    assert backup.parse_url("http://[::1]:8080/") == ("http", "[::1]", "8080")
    assert backup.parse_user_url("http://[FD00::1]:03000/x") == ("http", "[fd00::1]", "3000")
    assert backup.parse_user_url("https://[::1]") == ("https", "[::1]", "")
    assert backup.parse_user_url("HTTP://NAS.Example:80/") == ("http", "nas.example", "80")
    assert backup.parse_user_url("ftp://x/") == ("ftp", "", "")
    for url in ("http://[fd00::1%25e]/", "http://[::ffff:1.2.3.4]/", "http://[" + "0" * 40 + "]/", "http://[a]/",
                "http://[fd00::1]:0/", "http://x@[fd00::1]/", "http:[fd00::1]"):
        assert backup.parse_user_url(url) is None, url
    assert backup.custom_url_error("local", "http://[fd00::1]:3000/") == "malformed"
    assert backup.custom_url_error("claude", "https://[fd00::1]/") == "malformed"
    assert backup.custom_url_error("local", "http://192.168.1.20:3000/") == "http-not-loopback"


NAME_FUZZ_QML = """import QtQuick
import QtTest
import "ChatSites.js" as ChatSites

TestCase {
    name: "NameFuzz"
    function test_dump() {
        var ranges = %s
        var letters = { "": "o", "name-empty": "e", "name-too-long": "l", "name-chars": "c", "name-taken": "t" }
        var code = function (result) {
            var text = typeof result === "string" ? result : result.error
            return Object.prototype.hasOwnProperty.call(letters, text) ? letters[text] : "?"
        }
        var out = []
        for (var range = 0; range < ranges.length; range++) {
            for (var point = ranges[range][0]; point <= ranges[range][1]; point++) {
                var character = String.fromCodePoint(point)
                out.push(code(ChatSites.userSiteNameError(character, [])))
                out.push(code(ChatSites.userSiteNameError("Le" + character + "Chat", [])))
            }
        }
        // Qt cuts a log line at 2 MiB: the codes go out in numbered chunks.
        var text = out.join("")
        var chunks = 0
        for (var at = 0; at < text.length; at += 65536)
            console.log("FUZZ " + chunks++ + " " + text.slice(at, at + 65536))
        console.log("PARITY " + JSON.stringify([chunks]))
    }
}
"""
# The BMP (surrogates included, as lone ones), the astral Default_Ignorable
# ranges and astral letters, digits, symbols and emoji around them.
# Round 3: every code point, U+0000 to U+10FFFF (surrogates as lone ones). Both
# ports read categories from the same Unicode 16.0 tables, so nothing is skipped.
NAME_FUZZ_RANGES = [[0, 0x10FFFF]]
NAME_FUZZ_LETTERS = {"": "o", "name-empty": "e", "name-too-long": "l", "name-chars": "c", "name-taken": "t"}


def test_the_name_rule_agrees_with_chat_sites_js_on_every_code_point(tmp_path):
    """Each code point alone and inside "Le…Chat": the same code from both ports."""
    output = chat_sites_js_results(tmp_path, NAME_FUZZ_QML % json.dumps(NAME_FUZZ_RANGES), raw=True)
    chunks = int(re.search(r"PARITY \[(\d+)\]", output).group(1))
    found = dict(re.findall(r"FUZZ (\d+) ([a-z?]+)", output))
    assert sorted(map(int, found)) == list(range(chunks))
    results = "".join(found[str(index)] for index in range(chunks))
    points = [point for start, end in NAME_FUZZ_RANGES for point in range(start, end + 1)]
    assert len(results) == 2 * len(points)
    differences = []
    for index, point in enumerate(points):
        character = chr(point)
        for offset, name in ((0, character), (1, "Le" + character + "Chat")):
            expected = NAME_FUZZ_LETTERS[backup.user_site_name_error(name)]
            if results[2 * index + offset] != expected:
                differences.append((hex(point), offset, results[2 * index + offset], expected))
    assert differences == [], differences[:40]


SITE_A = {"id": "user-3fa9c01b", "name": "Le Chat", "url": "https://chat.example.org/chat"}
SITE_B = {"id": "user-00ff00aa", "name": "\u00dcn\u00efcode \U0001f600", "url": "https://b.example.net/x?y=1"}


def user_sites(*entries):
    """A chatUserSites value as the widget writes it (JSON.stringify)."""
    return json.dumps(list(entries), ensure_ascii=False, separators=(",", ":"))


def numbered_site(index):
    return {"id": f"user-{index:08x}", "name": f"Site {index}", "url": f"https://s{index}.example.com/"}


def test_user_sites_are_kept_in_key_order_with_non_ascii_kept():
    text = '[{"url":"https://b.example.net/x?y=1","id":"user-00ff00aa","name":"\\u00dcn\\u00efcode \\ud83d\\ude00"},' \
           ' {"id":"user-3fa9c01b","url":"https://chat.example.org/chat","name":"Le Chat"}]'
    kept, dropped = backup.validate_settings({"chatUserSites": text})
    assert (kept, dropped) == ({"chatUserSites": user_sites(SITE_B, SITE_A)}, 0)
    assert "\U0001f600" in kept["chatUserSites"]
    assert backup.user_site_ids(kept["chatUserSites"]) == ("user-00ff00aa", "user-3fa9c01b")


def entry_with(**changes):
    return dict(SITE_A, **changes)


BAD_USER_SITES = [
    "", "{}", "null", '"x"', "1", '{"id":"user-3fa9c01b","name":"Le Chat","url":"https://chat.example.org/chat"}',
    "[null]", "[[]]", '["user-3fa9c01b"]', "[", '[{"id":"user-3fa9c01b"}]',
    *[user_sites(dict(SITE_A, **{key: value})) for key, value in (
        ("local", False), ("local", True), ("local_kind", "public"), ("site_hosts", []), ("auth_hosts", []),
        ("icon", ""), ("user", True), ("exact_hosts", []), ("default_on", True), ("Id", "user-3fa9c01b"))],
    *[user_sites({key: value for key, value in SITE_A.items() if key != missing}) for missing in ("id", "name", "url")],
    *[user_sites(entry_with(id=bad)) for bad in (
        "user-3FA9C01B", "user-3fa9c01", "user-3fa9c01bb", "USER-3fa9c01b", "user_3fa9c01b", "claude", "ollama",
        "user-3fa9c01g", " user-3fa9c01b", "user-3fa9c01b\n", "", 1, None, ["user-3fa9c01b"])],
    user_sites(SITE_A, entry_with(name="Other")),                                   # the same id twice
    user_sites(SITE_A, dict(SITE_B, name="le chat")),                               # the same name, other case
    user_sites(SITE_A, dict(SITE_B, name="LE CHAT")),
    *[user_sites(entry_with(name=name)) for name, others, code in NAME_CASES if code and not others],
    *[user_sites(entry_with(url=url)) for url, code, _ in USER_URL_CASES if code],
    user_sites(entry_with(name=1)), user_sites(entry_with(name=None)), user_sites(entry_with(url=["https://a.example.com/"])),
    '[{"id":"user-3fa9c01b","name":"Le Chat","url":"https://chat.example.org/chat","id":"user-3fa9c01c"}]',
    '[{"id":"user-3fa9c01b","name":"Le Chat","url":"https://chat.example.org/chat"}' + "\x00]",
    [SITE_A], {"sites": [SITE_A]},
]


@pytest.mark.parametrize("value", BAD_USER_SITES)
def test_a_bad_user_site_entry_drops_the_whole_setting(value):
    assert backup.validate_settings({"chatUserSites": value}) == ({}, 1)


def test_200_user_sites_are_kept_and_201_dropped():
    sites = [numbered_site(index) for index in range(201)]
    assert backup.validate_settings({"chatUserSites": user_sites(*sites[:200])}) == \
        ({"chatUserSites": user_sites(*sites[:200])}, 0)
    assert backup.validate_settings({"chatUserSites": user_sites(*sites)}) == ({}, 1)


def test_the_user_sites_char_cap_counts_utf16_units():
    assert backup.MAX_USER_SITES_CHARS == 458752
    emoji = entry_with(name="a" + "\U0001f600" * 19)
    compact = user_sites(emoji)
    room = backup.MAX_USER_SITES_CHARS - len(compact.encode("utf-16-le")) // 2
    at_cap = "[" + " " * room + compact[1:]
    assert backup.validate_settings({"chatUserSites": at_cap}) == ({"chatUserSites": compact}, 0)
    over = "[ " + " " * room + compact[1:]
    assert len(over) < backup.MAX_USER_SITES_CHARS  # Python counts the emoji once, JS .length twice.
    assert backup.validate_settings({"chatUserSites": over}) == ({}, 1)


def test_the_longest_user_sites_stay_under_the_char_cap():
    sites = [{"id": f"user-{index:08x}", "name": chr(0x4E00 + index) + '"' * 39,
              "url": "https://a.example.com/" + "a" * 2026} for index in range(200)]
    value = user_sites(*sites)
    assert len(value.encode("utf-16-le")) // 2 <= backup.MAX_USER_SITES_CHARS
    assert backup.validate_settings({"chatUserSites": value}) == ({"chatUserSites": value}, 0)


SITE_ORDER_CASES = [
    ("", ""), ("[]", "[]"), (" [ \"ollama\" ] ", '["ollama"]'), ('["local","claude"]', '["local","claude"]'),
    ('["claude","claude"]', None), ('["nope"]', None), ('["Claude"]', None), ('["user-deadbeef"]', None),
    ('["refresh"]', None), ('["usage"]', None), ("{}", None), ("null", None), ('"claude"', None), ("[1]", None),
    ("[", None), (["claude"], None), (None, None),
]


@pytest.mark.parametrize(("value", "kept"), SITE_ORDER_CASES)
def test_site_order_values(value, kept):
    expected = ({"chatSiteOrder": kept}, 0) if kept is not None else ({}, 1)
    assert backup.validate_settings({"chatSiteOrder": value}) == expected


# --- the cross-key check (task 005) ---------------------------------------------------------------

A_ID, B_ID = SITE_A["id"], SITE_B["id"]
CROSS_KEY_VALUES = {
    "chatSites": (f'["claude","{A_ID}","ollama"]', f'["claude","{B_ID}"]'),
    "chatSiteOrder": (f'["{A_ID}","ollama","claude"]', f'["{B_ID}"]'),
    "chatDefaultSite": (A_ID, B_ID),
    "middleClickOpens": (A_ID, B_ID),
}


@pytest.mark.parametrize("key", sorted(CROSS_KEY_VALUES))
def test_an_added_id_is_kept_with_its_site(key):
    known, _ = CROSS_KEY_VALUES[key]
    kept, dropped = backup.validate_settings({"chatUserSites": user_sites(SITE_A), key: known})
    assert (kept, dropped) == ({key: known, "chatUserSites": user_sites(SITE_A)}, 0)
    assert list(kept) == [name for name in backup.BACKUP_KEYS if name in kept]


@pytest.mark.parametrize("key", sorted(CROSS_KEY_VALUES))
def test_an_unknown_added_id_drops_that_setting(key):
    _, unknown = CROSS_KEY_VALUES[key]
    assert backup.validate_settings({"chatUserSites": user_sites(SITE_A), key: unknown}) == \
        ({"chatUserSites": user_sites(SITE_A)}, 1)
    assert backup.validate_settings({key: unknown}) == ({}, 1)                # no chatUserSites at all


@pytest.mark.parametrize("key", sorted(CROSS_KEY_VALUES))
def test_a_dropped_user_sites_drops_what_names_its_ids(key):
    known, _ = CROSS_KEY_VALUES[key]
    bad = user_sites(SITE_A, entry_with(name="Other"))                       # a repeated id
    assert backup.validate_settings({"chatUserSites": bad, key: known}) == ({}, 2)


def test_every_reference_goes_with_a_dropped_user_sites_and_built_ins_stay():
    references = {key: known for key, (known, _) in CROSS_KEY_VALUES.items()}
    value = dict(GOOD, chatUserSites=user_sites(dict(SITE_A, local=True)), **references)
    kept, dropped = backup.validate_settings(value)
    assert dropped == 5
    assert kept == {key: item for key, item in GOOD_KEPT.items() if key not in references and key != "chatUserSites"}
    built_in = dict(GOOD, chatUserSites=user_sites(dict(SITE_A, local=True)))
    assert backup.validate_settings(built_in) == (
        {key: item for key, item in GOOD_KEPT.items() if key != "chatUserSites"}, 1)


def test_the_cross_key_check_uses_only_the_kept_ids():
    # B's id is in the file but B's entry is bad: only A's id may be named.
    value = {"chatUserSites": user_sites(SITE_A, dict(SITE_B, url="http://b.example.net/")),
             "chatSites": f'["{A_ID}"]'}
    assert backup.validate_settings(value) == ({}, 2)
    good = {"chatUserSites": user_sites(SITE_A, SITE_B), "chatSites": f'["{B_ID}","{A_ID}"]',
            "chatSiteOrder": f'["{B_ID}"]', "chatDefaultSite": B_ID, "middleClickOpens": A_ID}
    assert backup.validate_settings(good) == ({key: good[key] for key in backup.BACKUP_KEYS if key in good}, 0)


def test_200_added_ids_fit_in_chat_sites_and_site_order():
    sites = [numbered_site(index) for index in range(200)]
    ids = list(backup.CHAT_SITE_IDS) + [site["id"] for site in sites]
    listed = json.dumps(ids, separators=(",", ":"))
    assert len(listed) <= backup.MAX_STRING_CHARS
    value = {"chatUserSites": user_sites(*sites), "chatSites": listed, "chatSiteOrder": listed}
    assert backup.validate_settings(value) == ({key: value[key] for key in backup.BACKUP_KEYS if key in value}, 0)
    assert backup.MAX_USER_SITES + len(backup.WEB_SITE_IDS) == backup.MAX_USER_SITES + 7


# --- the worst case: 200 added sites at their longest (task 005) ----------------------------------


def longest_settings():
    """Every backup key at its longest (each value valid, so nothing is dropped)."""
    sites = [{"id": f"user-{index:08x}", "name": chr(0x4E00 + index) + "\u4e2d" * 39,
              "url": f"https://s{index:03d}.example.com/" + "a" * (2048 - len("https://s000.example.com/"))}
             for index in range(200)]
    added = [site["id"] for site in sites]
    custom = {site: ("http://localhost:65535/" if site in backup.LOCAL_SITE_IDS else "https://a.example.com/")
              for site in backup.WEB_SITE_IDS}
    custom = {site: url + "a" * (2048 - len(url)) for site, url in custom.items()}
    metrics = {entry.provider_id: list(entry.supported_metrics) for entry in PROVIDER_CATALOG}
    ring = max(backup.RING_PAIRS, key=len)
    settings = {
        "trackedProviders": json.dumps(list(backup.PROVIDER_IDS), separators=(",", ":")),
        "providerMetrics": json.dumps(metrics, separators=(",", ":")),
        "providerOrder": json.dumps(list(backup.PROVIDER_IDS), separators=(",", ":")),
        "usageMode": "remaining", "refreshInterval": 3600, "tooltipShowsUsage": False,
        "tooltipMetrics": json.dumps(metrics, separators=(",", ":")), "usageCompact": False,
        "usageWarnPercent": 90, "usageCriticalPercent": 95,
        "usageNormalColor": "#aaaaaa", "usageWarnColor": "#bbbbbb", "usageCriticalColor": "#cccccc",
        "alertLowEnabled": False, "alertResetEnabled": False, "alertLowPercent": 50,
        "chatSites": json.dumps(list(backup.CHAT_SITE_IDS) + added, separators=(",", ":")),
        "chatDefaultSite": added[-1], "chatOllamaUrl": "http://127.0.0.1:65535", "chatKeepOpen": False,
        "showUsageTab": False, "showChatTab": False, "popupDefaultTab": "usage", "popupSize": "compact",
        "shortcutOpens": "ollama", "panelRing": ring, "middleClickOpens": added[-1],
        "chatCustomUrls": json.dumps(custom, separators=(",", ":")),
        "chatUserSites": user_sites(*sites),
        "chatSiteOrder": json.dumps(added + list(reversed(backup.CHAT_SITE_IDS)), separators=(",", ":")),
    }
    assert list(settings) == list(backup.BACKUP_KEYS)
    return settings


def test_the_longest_settings_export_fits_512_kib_and_import(config, capsys):
    settings = longest_settings()
    assert exported(settings) == {"ok": True, "saved": len(backup.BACKUP_KEYS), "dropped": 0}
    path = config / "settings-backup.json"
    size = path.stat().st_size
    assert 400 * 1024 < size <= backup.MAX_FILE_BYTES
    assert run("import") == {"ok": True, "exported_at": STAMP, "settings": settings, "dropped": 0,
                             "origin": "this-computer"}
    # Task 007: format 2 (sha256 and signature) still leaves room under the cap.
    assert backup.MAX_FILE_BYTES - size >= 16 * 1024, backup.MAX_FILE_BYTES - size
    # The widget's reply cap (SettingsBackup.MAX_REPLY_CHARS, UTF-16 units) holds the import reply.
    assert cli.main(["--settings-backup", "import"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["settings"] == settings
    assert len(out.encode("utf-16-le")) // 2 <= backup.MAX_FILE_BYTES + 1024
    # Padded to the limit it still imports; one byte more is too large.
    data = path.read_bytes()
    path.write_bytes(data[:-1] + b" " * (backup.MAX_FILE_BYTES - size) + b"\n")
    assert path.stat().st_size == backup.MAX_FILE_BYTES
    assert run("import")["settings"] == settings
    assert run("import")["origin"] == "this-computer"  # Whitespace isn't part of the canonical form.
    path.write_bytes(data[:-1] + b" " * (backup.MAX_FILE_BYTES + 1 - size) + b"\n")
    assert run("import") == {"ok": False, "error": "too-large"}
    assert run("status") == {"ok": False, "error": "too-large"}


def test_added_sites_round_trip_through_the_rc_file(config):
    settings = {"chatUserSites": user_sites(SITE_A, SITE_B), "chatSites": f'["{B_ID}","claude"]',
                "chatSiteOrder": f'["{B_ID}","{A_ID}"]', "chatDefaultSite": A_ID, "middleClickOpens": B_ID}
    assert exported(settings)["dropped"] == 0
    imported = run("import")["settings"]
    assert {key: imported[key] for key in settings} == settings
    assert "\U0001f600" in (config / "settings-backup.json").read_text(encoding="utf-8")


# Task 006: a server on this computer and two home-network devices (IPv4 and IPv6).
LOCAL_SITES = (
    {"id": "user-0000aa01", "name": "My server", "url": "http://localhost:3000/"},
    {"id": "user-0000aa02", "name": "NAS chat", "url": "http://192.168.1.20:3000/"},
    {"id": "user-0000aa03", "name": "Box v6", "url": "http://[fd00::20]:3000/"},
)


def test_user_sites_keep_loopback_and_private_entries_over_http_and_https():
    https = ({"id": "user-0000aa04", "name": "TLS box", "url": "https://10.0.0.5/"},
             {"id": "user-0000aa05", "name": "Dev", "url": "https://127.0.0.1:8443/"},
             {"id": "user-0000aa06", "name": "Dev6", "url": "http://[::1]:8080/"})
    value = user_sites(SITE_A, *LOCAL_SITES, *https)
    assert backup.validate_settings({"chatUserSites": value}) == ({"chatUserSites": value}, 0)
    assert [backup.address_class(site["url"]) for site in (SITE_A, *LOCAL_SITES, *https)] == \
        ["public", "loopback", "private", "private", "private", "loopback", "loopback"]


@pytest.mark.parametrize("url", ["http://nas.local/", "http://192.168.1.020/", "http://[fd00:0::20]/",
                                 "http://169.254.169.254/", "http://[fe80::1]/", "http://100.64.0.1/",
                                 "http://127.0.0.2/", "http://[2001:db8::1]/", "http://[fe80::1%25eth0]/"])
def test_one_refused_local_entry_drops_the_whole_user_sites(url):
    value = user_sites(*LOCAL_SITES, entry_with(url=url))
    assert backup.validate_settings({"chatUserSites": value}) == ({}, 1)


def test_the_longest_ipv6_entries_stay_under_the_char_cap():
    """A 39-character IPv6 literal with a port still fits the 2048 URL cap; 200 of them fit the setting."""
    head = "http://[fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff]:65535/"
    sites = [{"id": f"user-{index:08x}", "name": chr(0x4E00 + index) + '"' * 39,
              "url": head + "a" * (2048 - len(head))} for index in range(200)]
    assert backup.address_class(sites[0]["url"]) == "private"
    assert backup.user_site_url_error(sites[0]["url"] + "a") == "too-long"
    value = user_sites(*sites)
    assert len(value.encode("utf-16-le")) // 2 <= backup.MAX_USER_SITES_CHARS
    assert backup.validate_settings({"chatUserSites": value}) == ({"chatUserSites": value}, 0)


def test_local_added_sites_round_trip_through_export_and_import(config):
    ids = [site["id"] for site in LOCAL_SITES]
    settings = {"chatUserSites": user_sites(*LOCAL_SITES), "chatSites": json.dumps(["claude", *ids], separators=(",", ":")),
                "chatSiteOrder": json.dumps([ids[2], ids[0]], separators=(",", ":")),
                "chatDefaultSite": ids[1], "middleClickOpens": ids[2]}
    assert exported(settings) == {"ok": True, "saved": len(backup.BACKUP_KEYS), "dropped": 0}
    reply = run("import")
    assert reply["ok"] is True and reply["dropped"] == 0
    assert {key: reply["settings"][key] for key in settings} == settings
    # Codes, counts and the origin word, nothing else.
    assert set(reply) == {"ok", "exported_at", "settings", "dropped", "origin"}
    assert reply["origin"] == "this-computer"


# --- strict JSON ----------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ['{"a":NaN}', '{"a":Infinity}', '{"a":-Infinity}', '{"a":1e999}',
                                  '{"a":1,"a":2}', '{"a":{"b":1,"b":1}}', "[" * 100000 + "]" * 100000,
                                  '{"a":' + "1" * 5000 + "}", "{", ""])
def test_strict_loads_refuses(text):
    with pytest.raises(ValueError):
        backup.strict_loads(text)


# --- export ---------------------------------------------------------------------------------------


def test_export_writes_a_private_file_atomically(config):
    assert exported(dict(GOOD, chatSignInStorage="encrypted", usageHistoryEnabled=True)) == \
        {"ok": True, "saved": len(GOOD), "dropped": 0}
    assert stat.S_IMODE(config.stat().st_mode) == 0o700
    path = config / "settings-backup.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert os.listdir(config) == ["settings-backup.json"]
    written = json.loads(path.read_text())
    assert list(written) == ["format", "version", "config_schema", "exported_at", "settings", "sha256", "signature"]
    assert {key: written[key] for key in backup.CONTENT_KEYS} == document(GOOD_KEPT, version=2)
    assert path.read_text().endswith("}\n")
    assert "chatSignInStorage" not in path.read_text()


def test_export_status_import_round_trip(config):
    exported(GOOD)
    assert run("status") == {"ok": True, "exists": True, "exported_at": STAMP}
    assert run("import") == {"ok": True, "exported_at": STAMP, "settings": GOOD_KEPT, "dropped": 0,
                             "origin": "this-computer"}
    # Exporting what import gave keeps it unchanged.
    before = (config / "settings-backup.json").read_bytes()
    exported(GOOD_KEPT)
    assert (config / "settings-backup.json").read_bytes() == before


def test_export_replaces_the_old_backup(config):
    exported(GOOD)
    old = os.stat(config / "settings-backup.json").st_ino
    assert exported({"usageMode": "remaining"}, now=NOW + 60)["saved"] == len(backup.BACKUP_KEYS)
    assert os.stat(config / "settings-backup.json").st_ino != old
    assert run("import")["settings"] == dict(DEFAULTS, usageMode="remaining")
    assert run("import")["exported_at"] == "2026-11-06T00:11:29Z"


def test_export_tightens_a_safe_folder_to_0700(config):
    config.mkdir(parents=True)
    config.chmod(0o755)
    assert exported(GOOD)["ok"] is True
    assert stat.S_IMODE(config.stat().st_mode) == 0o700


def test_export_never_writes_a_file_import_would_refuse(config, monkeypatch):
    monkeypatch.setattr(backup, "MAX_FILE_BYTES", 200)
    assert exported(GOOD) == {"ok": False, "error": "too-large"}
    assert not config.exists()


def test_export_refuses_a_symlinked_folder_or_file(config, tmp_path):
    write_rc(GOOD)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    config.symlink_to(elsewhere)
    assert run("export") == {"ok": False, "error": "symlink"}
    assert os.listdir(elsewhere) == []
    config.unlink()
    config.mkdir(mode=0o700)
    target = tmp_path / "precious"
    target.write_text("keep")
    (config / "settings-backup.json").symlink_to(target)
    assert run("export") == {"ok": False, "error": "symlink"}
    assert target.read_text() == "keep"


@pytest.mark.parametrize("mode", [0o770, 0o702, 0o777])
def test_an_unsafe_folder_is_refused(config, mode):
    write_backup(config, document(), folder_mode=mode)
    for operation in ("status", "import"):
        assert run(operation) == {"ok": False, "error": "unsafe-mode"}
    assert exported(GOOD) == {"ok": False, "error": "unsafe-mode"}
    assert stat.S_IMODE(config.stat().st_mode) == mode


def test_a_failed_export_leaves_the_old_backup_and_no_temporary(config, monkeypatch):
    exported(GOOD)
    before = (config / "settings-backup.json").read_bytes()

    def failing_fsync(descriptor):
        raise OSError(5, "I/O")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    assert exported({"usageMode": "remaining"}) == {"ok": False, "error": "os-error"}
    assert (config / "settings-backup.json").read_bytes() == before
    assert os.listdir(config) == ["settings-backup.json"]


# --- export reads the applied settings (audit M1) -------------------------------------------------


def test_export_of_an_untouched_widget_saves_every_default(config):
    assert exported({}) == {"ok": True, "saved": len(backup.BACKUP_KEYS), "dropped": 0}
    assert run("import")["settings"] == DEFAULTS


def test_export_reads_the_sanitized_fixture(config, tmp_path):
    rc = tmp_path / "config" / appletconfig.APPLETSRC
    rc.parent.mkdir()
    rc.write_bytes((Path(__file__).parent / "fixtures" / "plasma-appletsrc").read_bytes())
    assert run("export", applet=21) == {"ok": True, "saved": len(backup.BACKUP_KEYS), "dropped": 0}
    assert run("import")["settings"] == dict(
        DEFAULTS,
        chatCustomUrls='{"claude":"https://claude.example.org/new?q=1;x","local":"http://localhost:8080/"}',
        chatDefaultSite="local", chatSites='["claude","local","ollama"]', panelRing="codex.weekly",
        refreshInterval=900, tooltipShowsUsage=False, usageWarnColor="#aa0000",
    )
    text = (config / "settings-backup.json").read_text()
    for excluded in ("chatSignInStorage", "usageHistoryEnabled", "initialSetupComplete", "configSchemaVersion"):
        assert excluded not in text


def test_export_decodes_kconfig_escapes_before_checking(config):
    write_rc({}, raw_lines=['chatCustomUrls={"claude":"https://claude.example.org\\x2fnew"}',
                            "chatOllamaUrl=http://localhost:\\x311434"])
    assert run("export")["dropped"] == 0
    settings = run("import")["settings"]
    assert settings["chatCustomUrls"] == '{"claude":"https://claude.example.org/new"}'
    assert settings["chatOllamaUrl"] == "http://localhost:11434"  # The x31 escape is "1".


def test_export_drops_and_counts_what_the_widget_would_not_store(config):
    write_rc({"usageMode": "nope", "refreshInterval": 301, "panelRing": "claude.extra_usage"},
             raw_lines=["usageCompact=maybe", "chatDefaultSite=\\xff", "alertLowPercent=0x10"])
    reply = run("export")
    assert reply == {"ok": True, "saved": len(backup.BACKUP_KEYS) - 6, "dropped": 6}
    settings = run("import")["settings"]
    for key in ("usageMode", "refreshInterval", "panelRing", "usageCompact", "chatDefaultSite", "alertLowPercent"):
        assert key not in settings


def test_export_with_nothing_valid_is_bad_data_and_writes_nothing(config, tmp_path):
    write_rc({key: "nope" for key in backup.BACKUP_KEYS})
    assert run("export") == {"ok": False, "error": "bad-data"}
    assert not config.exists()


def test_export_ignores_suffixed_keys(config):
    write_rc({}, raw_lines=["usageMode[$e]=used", "usageMode[de]=used", "chatCustomUrls[$e]={}"])
    assert run("export")["ok"] is True
    settings = run("import")["settings"]
    assert (settings["usageMode"], settings["chatCustomUrls"]) == ("remaining", "{}")


def test_export_reads_only_its_own_widget(config):
    write_rc({"usageMode": "used"}, applet=8)
    assert run("export") == {"ok": False, "error": "applet-not-found"}
    assert run("export", applet=8)["ok"] is True
    assert run("import")["settings"]["usageMode"] == "used"


@pytest.mark.parametrize("applet", [0, -1, True, "7", None])
def test_export_refuses_an_odd_applet_id(config, applet):
    write_rc(GOOD)
    assert run("export", applet=applet) == {"ok": False, "error": "applet-not-found"}
    assert not config.exists()


def test_export_refuses_two_widgets_with_the_id(config):
    path = write_rc(GOOD)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"[Containments][9][Applets][{APPLET}]\nplugin={appletconfig.PLUGIN}\n")
    assert run("export") == {"ok": False, "error": "applet-not-found"}
    assert not config.exists()


def test_export_without_any_rc_file_is_applet_not_found(config, tmp_path):
    assert run("export") == {"ok": False, "error": "applet-not-found"}
    assert not (tmp_path / "config").exists()


def test_export_falls_back_to_plasmawindowed(config):
    write_rc({"usageMode": "used"}, name=appletconfig.WINDOWED_RC)
    assert run("export")["ok"] is True
    assert run("import")["settings"]["usageMode"] == "used"


def test_export_falls_back_to_plasmawindowed_past_another_plugin_with_the_id(config):
    # The lab case: widget 4 of plasmawindowed, and the desktop's widget 4 is the pager.
    desktop = write_rc({"usageMode": "remaining"})
    desktop.write_text(desktop.read_text().replace(appletconfig.PLUGIN, "org.kde.plasma.pager"))
    write_rc({"usageMode": "used"}, name=appletconfig.WINDOWED_RC)
    assert run("export")["ok"] is True
    assert run("import")["settings"]["usageMode"] == "used"


def test_export_refuses_a_symlinked_rc_file_and_writes_nothing(config, tmp_path):
    real = write_rc(GOOD)
    moved = tmp_path / "elsewhere-appletsrc"
    real.rename(moved)
    real.symlink_to(moved)
    assert run("export") == {"ok": False, "error": "settings-unreadable"}
    assert not config.exists()


def test_export_never_changes_the_rc_file(config):
    path = write_rc(GOOD)
    before = (path.read_bytes(), os.stat(path).st_mtime_ns, os.stat(path).st_ino, stat.S_IMODE(os.stat(path).st_mode))
    assert run("export")["ok"] is True
    assert (path.read_bytes(), os.stat(path).st_mtime_ns, os.stat(path).st_ino,
            stat.S_IMODE(os.stat(path).st_mode)) == before


def test_export_removes_stale_temporaries_first(config, monkeypatch):
    exported(GOOD)
    stale = ["settings-backup.json.0123456789abcdef.tmp", "settings-backup.json.fedcba9876543210.tmp"]
    for name in stale:
        (config / name).write_text("half a backup")
    keep = ["settings-backup.json.short.tmp", "other.json.0123456789abcdef.tmp", "notes"]
    for name in keep:
        (config / name).write_text("not ours")
    removed_before_write = []
    real_open = os.open

    def watching_open(name, flags, *args, **kwargs):
        if str(name).startswith("settings-backup.json.") and flags & os.O_CREAT:
            removed_before_write.append(all(not (config / item).exists() for item in stale))
        return real_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", watching_open)
    assert exported(GOOD)["ok"] is True
    assert removed_before_write == [True]
    assert sorted(os.listdir(config)) == sorted(keep + ["settings-backup.json"])


def test_a_stale_temporary_that_is_a_symlink_is_unlinked_not_followed(config, tmp_path):
    exported(GOOD)
    target = tmp_path / "precious"
    target.write_text("keep")
    (config / "settings-backup.json.0123456789abcdef.tmp").symlink_to(target)
    assert exported(GOOD)["ok"] is True
    assert target.read_text() == "keep"
    assert os.listdir(config) == ["settings-backup.json"]


def test_status_and_import_leave_stale_temporaries_alone(config):
    exported(GOOD)
    (config / "settings-backup.json.0123456789abcdef.tmp").write_text("x")
    assert run("status")["ok"] is True and run("import")["ok"] is True
    assert (config / "settings-backup.json.0123456789abcdef.tmp").exists()


# --- status and import ----------------------------------------------------------------------------


def test_nothing_there_is_absent_and_creates_nothing(config, tmp_path):
    assert run("status") == {"ok": True, "exists": False}
    assert run("import") == {"ok": False, "error": "absent"}
    assert not (tmp_path / "config").exists()
    config.mkdir(parents=True, mode=0o700)
    assert run("status") == {"ok": True, "exists": False}
    assert os.listdir(config) == []


def test_import_drops_and_counts_odd_settings(config):
    write_backup(config, document(dict(GOOD, usageMode="nope", chatSignInStorage="encrypted",
                                       usageHistoryEnabled=True)))
    reply = run("import")
    assert reply["settings"] == {key: value for key, value in GOOD_KEPT.items() if key != "usageMode"}
    assert reply["dropped"] == 3


@pytest.mark.parametrize(("content", "error"), [
    ("", "invalid"), ("not json", "invalid"), (b"\xff", "invalid"), ("[]", "invalid"),
    (document(format="other"), "invalid"), (document(version=3), "unsupported"),
    (document(version=0), "unsupported"),
    (document(config_schema=2), "unsupported"), (document(config_schema=4), "unsupported"),
    (document(version="1"), "invalid"), (document(version=True), "invalid"), (document(version=1.0), "invalid"),
    (document(exported_at="2026-11-06 00:10:29Z"), "invalid"), (document(exported_at="2026-13-06T00:10:29Z"), "invalid"),
    (document(exported_at=1), "invalid"), (document(settings=[]), "invalid"), (document(extra=1), "invalid"),
    ('{"format":"hearthwire-settings","version":1,"config_schema":3,"exported_at":"%s","settings":{},'
     '"settings":{}}' % STAMP, "invalid"),
    ('{"format":"hearthwire-settings","version":1,"config_schema":3,"exported_at":"%s",'
     '"settings":{"refreshInterval":NaN}}' % STAMP, "invalid"),
])
def test_bad_files_are_refused(config, content, error):
    write_backup(config, content)
    assert run("import") == {"ok": False, "error": error}
    assert run("status") == {"ok": False, "error": error}


def test_a_missing_top_level_key_is_invalid(config):
    content = document()
    del content["exported_at"]
    write_backup(config, content)
    assert run("import") == {"ok": False, "error": "invalid"}


def test_a_file_over_512_kib_is_too_large(config):
    assert backup.MAX_FILE_BYTES == 512 * 1024  # Task 005: 200 added sites fit.
    text = json.dumps(document())
    write_backup(config, text + " " * (backup.MAX_FILE_BYTES - len(text)))
    assert run("import")["ok"] is True
    write_backup(config, text + " " * (backup.MAX_FILE_BYTES + 1 - len(text)))
    assert run("import") == {"ok": False, "error": "too-large"}


@pytest.mark.parametrize("mode", [0o620, 0o602, 0o666])
def test_a_group_or_other_writable_file_is_unsafe(config, mode):
    write_backup(config, document(), mode=mode)
    assert run("import") == {"ok": False, "error": "unsafe-mode"}
    assert run("status") == {"ok": False, "error": "unsafe-mode"}


def test_a_readable_file_is_still_accepted(config):
    write_backup(config, document(), mode=0o644)
    assert run("import")["ok"] is True


def test_a_symlinked_file_or_folder_is_refused(config, tmp_path):
    real = tmp_path / "real"
    write_backup(real, document())
    config.parent.mkdir(parents=True)
    config.symlink_to(real)
    assert run("import") == {"ok": False, "error": "symlink"}
    config.unlink()
    config.mkdir(mode=0o700)
    (config / "settings-backup.json").symlink_to(real / "settings-backup.json")
    assert run("import") == {"ok": False, "error": "symlink"}
    assert run("status") == {"ok": False, "error": "symlink"}


def test_a_directory_in_place_of_the_file_is_invalid(config):
    (config / "settings-backup.json").mkdir(parents=True)
    config.chmod(0o700)
    assert run("import") == {"ok": False, "error": "invalid"}


def test_someone_elses_file_is_refused(config, monkeypatch):
    write_backup(config, document())
    real_getuid = os.getuid
    real_fstat = os.fstat

    def foreign_fstat(descriptor, *args):
        info = real_fstat(descriptor, *args)
        if stat.S_ISREG(info.st_mode):
            values = list(info)
            values[stat.ST_UID] = real_getuid() + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(os, "fstat", foreign_fstat)
    assert run("import") == {"ok": False, "error": "not-owned"}


def test_someone_elses_folder_is_refused(config, monkeypatch):
    write_backup(config, document())
    monkeypatch.setattr(os, "getuid", lambda: os.geteuid() + 1)
    assert run("import") == {"ok": False, "error": "not-owned"}


def test_xdg_config_home_must_be_absolute(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/config")
    assert backup.config_base() == str(tmp_path / "home" / ".config")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert backup.config_base() == str(tmp_path / "xdg")
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert backup.config_base() == str(tmp_path / "home" / ".config")


# --- backup identity: format 2, the key, origin (task 007) ---------------------------------------

KEY = bytes(range(32))
OTHER_KEY = bytes(range(100, 132))
CONTENT_KEYS = ["format", "version", "config_schema", "exported_at", "settings"]
FILE_KEYS = CONTENT_KEYS + ["sha256", "signature"]
# The golden vector (plan §8.1): fixed key and document, fixed bytes and digests.
# Checked once against openssl (sha256sum; dgst -sha256 -mac HMAC) when written.
GOLDEN_SETTINGS = {"usageMode": "used", "refreshInterval": 300, "chatKeepOpen": True,
                   "chatUserSites": user_sites(SITE_B)}
GOLDEN_CANONICAL = (
    '{"config_schema":3,"exported_at":"2026-11-06T00:10:29Z","format":"hearthwire-settings",'
    '"settings":{"chatKeepOpen":true,"chatUserSites":"[{\\"id\\":\\"user-00ff00aa\\",'
    '\\"name\\":\\"Ünïcode \U0001f600\\",\\"url\\":\\"https://b.example.net/x?y=1\\"}]",'
    '"refreshInterval":300,"usageMode":"used"},"version":2}'
).encode("utf-8")
GOLDEN_SHA256 = "a657a668276e3d25cc16834f654e79b49409be1946d40b5cbce8d34de61e39fb"
GOLDEN_SIGNATURE = "2bc75862457d36fe1881a938c501bc1e055ff0ee2904c7412377e9705232d86a"


def data_folder():
    return Path(os.environ["XDG_DATA_HOME"]) / "hearthwire"


def key_path():
    return data_folder() / "backup-key"


def install_key(key=KEY, *, mode=0o600, folder_mode=0o700):
    data_folder().mkdir(parents=True, exist_ok=True)
    data_folder().chmod(folder_mode)
    key_path().write_bytes(key)
    key_path().chmod(mode)
    return key_path()


def signed(settings=None, *, key=KEY, **overrides):
    """A version 2 document, its digests computed here with ``key``."""
    content = document(settings, **dict({"version": 2}, **overrides))
    body = backup.canonical(content)
    return dict(content, sha256=backup.content_sha256(body), signature=backup.content_signature(key, body))


def key_forms(key):
    """Every way the key could leak: raw, hex in both cases, base64 and base64url."""
    return [key, key.hex().encode(), key.hex().upper().encode(), base64.b64encode(key),
            base64.urlsafe_b64encode(key), base64.b64encode(key).rstrip(b"=")]


def test_the_golden_vector():
    content = document(GOLDEN_SETTINGS, version=2)
    assert backup.canonical(content) == GOLDEN_CANONICAL
    assert backup.content_sha256(GOLDEN_CANONICAL) == GOLDEN_SHA256
    assert backup.content_signature(KEY, GOLDEN_CANONICAL) == GOLDEN_SIGNATURE
    assert backup.SIGN_CONTEXT == b"hearthwire-settings-backup\x00"
    # The file itself: content keys in order, then the two digests, compact, one newline.
    assert backup.encode_document(GOLDEN_SETTINGS, STAMP, KEY) == (
        '{"format":"hearthwire-settings","version":2,"config_schema":3,"exported_at":"%s","settings":%s,'
        '"sha256":"%s","signature":"%s"}\n' % (STAMP, json.dumps(GOLDEN_SETTINGS, ensure_ascii=False,
                                                                 separators=(",", ":")),
                                                GOLDEN_SHA256, GOLDEN_SIGNATURE)).encode("utf-8")


def test_export_writes_format_2_signed_with_a_new_private_key(config):
    assert not data_folder().exists()
    assert exported(GOOD)["ok"] is True
    assert stat.S_IMODE(data_folder().stat().st_mode) == 0o700
    info = key_path().lstat()
    assert stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size == 32
    assert os.listdir(data_folder()) == ["backup-key"]
    key = key_path().read_bytes()
    written = json.loads((config / "settings-backup.json").read_text(encoding="utf-8"))
    assert list(written) == FILE_KEYS and written["version"] == 2
    body = backup.canonical(written)
    assert written["sha256"] == backup.content_sha256(body)
    assert written["signature"] == backup.content_signature(key, body)
    # A second export reuses the key, untouched.
    assert exported(GOOD, now=NOW + 60)["ok"] is True
    assert key_path().read_bytes() == key and key_path().lstat().st_ino == info.st_ino
    assert run("import")["origin"] == "this-computer"


def test_the_key_is_0600_whatever_the_umask(config):
    write_rc(GOOD)
    old = os.umask(0)
    try:
        assert run("export")["ok"] is True
    finally:
        os.umask(old)
    assert stat.S_IMODE(key_path().stat().st_mode) == 0o600
    assert stat.S_IMODE(data_folder().stat().st_mode) == 0o700


def test_the_key_is_made_through_an_exclusive_temporary_and_a_link(config, monkeypatch):
    write_rc(GOOD)
    opened, linked = [], []
    real_open, real_link = os.open, os.link

    def watching_open(name, flags, *args, **kwargs):
        if str(name).startswith("backup-key"):
            opened.append((str(name), flags, args))
        return real_open(name, flags, *args, **kwargs)

    def watching_link(source, target, *args, **kwargs):
        linked.append((source, target, kwargs))
        return real_link(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "open", watching_open)
    monkeypatch.setattr(os, "link", watching_link)
    assert run("export")["ok"] is True
    reads = [entry for entry in opened if not entry[1] & os.O_CREAT]
    creates = [entry for entry in opened if entry[1] & os.O_CREAT]
    assert [name for name, _, _ in reads] == ["backup-key"]  # Looked for first, never created by that name.
    assert len(creates) == 1
    name, flags, args = creates[0]
    assert re.fullmatch(r"backup-key\.[0-9a-f]{16}\.tmp", name)
    assert flags & os.O_EXCL and flags & os.O_NOFOLLOW and args[0] == 0o600
    assert [(source, target) for source, target, _ in linked] == [(name, "backup-key")]
    assert linked[0][2]["follow_symlinks"] is False
    assert os.listdir(data_folder()) == ["backup-key"]  # The temporary is gone.


def test_a_key_made_by_another_export_at_link_time_is_used_not_replaced(config, monkeypatch):
    write_rc(GOOD)
    real_link = os.link

    def racing_link(source, target, *args, **kwargs):
        install_key(OTHER_KEY)  # Another widget's export won the race.
        return real_link(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "link", racing_link)
    assert run("export")["ok"] is True
    assert key_path().read_bytes() == OTHER_KEY
    assert os.listdir(data_folder()) == ["backup-key"]
    written = json.loads((config / "settings-backup.json").read_text(encoding="utf-8"))
    assert written["signature"] == backup.content_signature(OTHER_KEY, backup.canonical(written))
    monkeypatch.setattr(os, "link", real_link)
    assert run("import")["origin"] == "this-computer"


def test_stale_key_temporaries_are_removed_and_a_symlinked_one_is_unlinked(config, tmp_path):
    install_key()
    target = tmp_path / "precious"
    target.write_bytes(b"keep")
    (data_folder() / "backup-key.0123456789abcdef.tmp").write_bytes(b"half")
    (data_folder() / "backup-key.fedcba9876543210.tmp").symlink_to(target)
    keep = ["backup-key.short.tmp", "backup-key.0123456789ABCDEF.tmp", "vault-keys", "notes"]
    for name in keep:
        (data_folder() / name).write_text("not ours")
    assert exported(GOOD)["ok"] is True
    assert sorted(os.listdir(data_folder())) == sorted(keep + ["backup-key"])
    assert target.read_bytes() == b"keep"
    assert key_path().read_bytes() == KEY


# Round 2, LOW-1: exports lock both folders, so one never deletes another's live temporary.
CONCURRENT_EXPORTER = """
import collections, os, sys, time
from hearthwire.core import settingsbackup
go = sys.argv[2]
while not os.path.exists(go):
    time.sleep(0.001)
codes = collections.Counter()
for _ in range(int(sys.argv[1])):
    reply = settingsbackup.run("export", applet=7)
    codes["ok" if reply.get("ok") is True else reply.get("error")] += 1
print(dict(codes))
"""


def test_four_concurrent_exporters_never_fail(config, tmp_path):
    """The auditor's race: 4 processes x 150 exports from a fresh folder, the key made in the race."""
    write_rc(GOOD)
    go = tmp_path / "go"
    env = {"PATH": "/usr/bin:/bin", "HOME": os.environ["HOME"], "XDG_CONFIG_HOME": os.environ["XDG_CONFIG_HOME"],
           "XDG_DATA_HOME": os.environ["XDG_DATA_HOME"], "TMPDIR": str(tmp_path),
           "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    workers = [subprocess.Popen([sys.executable, "-c", CONCURRENT_EXPORTER, "150", str(go)], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
    go.touch()
    results = [worker.communicate(timeout=300) for worker in workers]
    assert [(out.strip(), err) for out, err in results] == [("{'ok': 150}", "")] * 4
    assert os.listdir(data_folder()) == ["backup-key"]
    assert os.listdir(config) == ["settings-backup.json"]
    assert run("import")["origin"] == "this-computer"


def hold_lock(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    return descriptor


@pytest.mark.parametrize("folder", ["backup", "key"])
def test_a_live_export_temporary_is_never_deleted(config, monkeypatch, folder):
    exported(GOOD)
    before = (config / "settings-backup.json").read_bytes()
    where = config if folder == "backup" else data_folder()
    live = where / ("settings-backup.json.0123456789abcdef.tmp" if folder == "backup"
                    else "backup-key.0123456789abcdef.tmp")
    live.write_bytes(b"another export, still writing")
    monkeypatch.setattr(backup, "LOCK_WAIT_SECONDS", 0.2)
    descriptor = hold_lock(where)  # That export holds the folder.
    try:
        assert exported(GOOD, now=NOW + 60) == {"ok": False, "error": "os-error"}
        assert live.read_bytes() == b"another export, still writing"
        assert (config / "settings-backup.json").read_bytes() == before
    finally:
        os.close(descriptor)
    # Once no export holds the folder, what is left is a dead export's and goes.
    assert exported(GOOD, now=NOW + 60)["ok"] is True
    assert not live.exists()


def test_import_waits_for_a_key_being_made_then_says_other(config, monkeypatch):
    exported(GOOD)
    monkeypatch.setattr(backup, "LOCK_WAIT_SECONDS", 0.2)
    descriptor = hold_lock(data_folder())
    try:
        assert run("import")["origin"] == "other"
        assert run("status")["ok"] is True  # status never touches the key or its lock.
    finally:
        os.close(descriptor)
    assert run("import")["origin"] == "this-computer"


def test_import_takes_the_key_lock_shared(config, monkeypatch):
    exported(GOOD)
    taken = []
    real_flock = fcntl.flock

    def watching_flock(descriptor, operation):
        taken.append(operation & ~fcntl.LOCK_NB)
        return real_flock(descriptor, operation)

    monkeypatch.setattr(fcntl, "flock", watching_flock)
    assert run("import")["origin"] == "this-computer"
    assert taken == [fcntl.LOCK_SH]
    taken.clear()
    assert exported(GOOD)["ok"] is True
    assert taken == [fcntl.LOCK_EX, fcntl.LOCK_EX]  # The backup folder, then the key folder.


def test_key_material_never_reaches_the_file_a_reply_or_the_cli(config, capsys):
    write_rc(GOOD)
    outputs = []
    for argv in (["export", "--applet", "7"], ["status"], ["import"], ["export", "--applet", "7"]):
        assert cli.main(["--settings-backup", *argv]) == 0
        captured = capsys.readouterr()
        assert json.loads(captured.out)["ok"] is True
        outputs += [captured.out.encode("utf-8"), captured.err.encode("utf-8")]
    key = key_path().read_bytes()
    outputs.append((config / "settings-backup.json").read_bytes())
    outputs += [value.encode("utf-8", "surrogateescape") for value in os.environ.values()]
    for form in key_forms(key):
        for output in outputs:
            assert form not in output
    assert b"backup-key" not in b"".join(outputs[:-len(os.environ)])


def test_a_reindented_or_reordered_file_is_still_this_computers(config):
    exported(GOOD)
    path = config / "settings-backup.json"
    written = json.loads(path.read_text(encoding="utf-8"))
    for text in (json.dumps(written, indent=4), json.dumps(dict(reversed(list(written.items()))), indent="\t"),
                 json.dumps(dict(written, settings=dict(reversed(list(written["settings"].items())))))):
        path.write_text(text, encoding="utf-8")
        assert run("import") == {"ok": True, "exported_at": STAMP, "settings": GOOD_KEPT, "dropped": 0,
                                 "origin": "this-computer"}


def test_a_lone_surrogate_escape_is_invalid(config):
    install_key()
    text = json.dumps(signed()).replace('"used"', '"\\ud800"', 1)
    assert '"\\ud800"' in text
    write_backup(config, text)
    assert run("import") == {"ok": False, "error": "invalid"}
    assert run("status") == {"ok": False, "error": "invalid"}


def test_one_changed_character_is_damaged_for_status_and_import(config):
    exported(GOOD)
    path = config / "settings-backup.json"
    text = path.read_text(encoding="utf-8")
    assert '"usageMode":"used"' in text
    path.write_text(text.replace('"usageMode":"used"', '"usageMode":"usee"', 1), encoding="utf-8")
    assert run("import") == {"ok": False, "error": "damaged"}
    assert run("status") == {"ok": False, "error": "damaged"}


def test_a_damaged_file_is_refused_before_the_key_is_read(config, monkeypatch):
    install_key()
    write_backup(config, dict(signed(), sha256="0" * 64))
    looked = []
    monkeypatch.setattr(backup, "_import_key", lambda environ: looked.append(1))
    assert run("import") == {"ok": False, "error": "damaged"}
    assert looked == []


def test_status_never_reads_the_key(config, monkeypatch):
    exported(GOOD)

    def refuse(*args, **kwargs):
        raise AssertionError("status read the key")

    for name in ("_signing_key", "_import_key", "_read_key", "_key_directory"):
        monkeypatch.setattr(backup, name, refuse)
    assert run("status") == {"ok": True, "exists": True, "exported_at": STAMP}


def test_a_checksum_recomputed_without_the_key_is_other(config):
    exported(GOOD)
    path = config / "settings-backup.json"
    written = json.loads(path.read_text(encoding="utf-8"))
    written["settings"]["usageMode"] = "remaining"
    written["sha256"] = backup.content_sha256(backup.canonical(written))
    path.write_text(json.dumps(written), encoding="utf-8")
    reply = run("import")
    assert reply["origin"] == "other" and reply["settings"]["usageMode"] == "remaining"


def test_another_key_is_other(config):
    install_key()
    write_backup(config, signed(key=OTHER_KEY))
    assert run("import")["origin"] == "other"


def test_without_a_key_import_says_other_and_makes_none(config):
    exported(GOOD)
    key_path().unlink()
    assert run("import") == {"ok": True, "exported_at": STAMP, "settings": GOOD_KEPT, "dropped": 0,
                             "origin": "other"}
    assert os.listdir(data_folder()) == []


def test_status_and_import_never_make_the_data_folder_or_the_key(config):
    write_backup(config, signed())
    assert run("status")["ok"] is True
    assert run("import")["origin"] == "other"
    write_backup(config, document())
    assert run("import")["origin"] == "unsigned"
    assert not Path(os.environ["XDG_DATA_HOME"]).exists()


def make_unusable(kind, tmp_path):
    if kind == "symlink":
        real = tmp_path / "real-key"
        real.write_bytes(KEY)  # Even the right key is not read through a link.
        real.chmod(0o600)
        data_folder().mkdir(parents=True, mode=0o700)
        key_path().symlink_to(real)
    elif kind == "directory":
        key_path().mkdir(parents=True, mode=0o700)
        data_folder().chmod(0o700)
    elif kind == "fifo":
        data_folder().mkdir(parents=True, mode=0o700)
        os.mkfifo(key_path(), 0o600)
    elif kind == "folder-symlink":
        real = tmp_path / "real-data"
        real.mkdir(mode=0o700)
        (real / "backup-key").write_bytes(KEY)
        (real / "backup-key").chmod(0o600)
        data_folder().parent.mkdir(parents=True)
        data_folder().symlink_to(real)
    elif kind == "socket":
        data_folder().mkdir(parents=True, mode=0o700)
        here = os.getcwd()
        os.chdir(data_folder())  # A relative name: tmp_path may be longer than sun_path.
        try:
            try:
                with socket.socket(socket.AF_UNIX) as listener:
                    listener.bind("backup-key")
            except PermissionError:
                pytest.skip("this sandbox refuses unix sockets; ENXIO is also covered by the errno test")
        finally:
            os.chdir(here)
    elif kind == "hardlink":
        install_key()
        os.link(key_path(), tmp_path / "copied-key")  # INFO-2: a second name outside the folder.
    elif kind.startswith("folder-"):
        install_key(folder_mode=int(kind[len("folder-"):], 8))
    elif kind.startswith("mode-"):
        install_key(mode=int(kind[len("mode-"):], 8))
    else:
        install_key(KEY[:31] if kind == "short" else KEY + b"!")


def snapshot(path):
    info = os.lstat(path)
    content = path.read_bytes() if stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) & 0o400 else None
    return info.st_mode, info.st_ino, info.st_nlink, content


UNUSABLE = ["symlink", "directory", "fifo", "short", "long", "mode-644", "mode-640", "mode-604", "mode-620",
            "folder-770", "folder-702", "folder-777", "folder-symlink",
            "mode-000", "socket", "hardlink"]  # round 2: INFO-1 (EACCES, ENXIO) and INFO-2


@pytest.mark.parametrize("kind", UNUSABLE)
def test_an_unusable_key_is_other_on_import_and_refused_by_export(config, tmp_path, kind):
    if kind == "mode-000" and os.geteuid() == 0:
        pytest.skip("root reads a mode-0000 file")
    make_unusable(kind, tmp_path)
    write_backup(config, signed())
    before_key, before_folder = snapshot(key_path()), snapshot(data_folder())
    before_file = (config / "settings-backup.json").read_bytes()
    assert run("import")["origin"] == "other"
    assert exported(GOOD) == {"ok": False, "error": "key-unusable"}
    # Nothing replaced or repaired (M-5), and the old backup stays.
    assert snapshot(key_path()) == before_key and snapshot(data_folder()) == before_folder
    assert (config / "settings-backup.json").read_bytes() == before_file
    assert sorted(os.listdir(data_folder())) == ["backup-key"]


@pytest.mark.parametrize(("number", "code"), [
    (errno.EACCES, "key-unusable"), (errno.ENXIO, "key-unusable"), (errno.EISDIR, "key-unusable"),
    (errno.ELOOP, "key-unusable"), (errno.EIO, "os-error"), (errno.EMFILE, "os-error"),
])
def test_key_open_errors_are_classified(config, monkeypatch, number, code):
    install_key()
    write_rc(GOOD)
    real_open = os.open

    def failing_open(name, flags, *args, **kwargs):
        if name == "backup-key":
            raise OSError(number, os.strerror(number))
        return real_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", failing_open)
    assert run("export") == {"ok": False, "error": code}
    write_backup(config, signed())
    assert run("import")["origin"] == "other"


def test_someone_elses_key_is_unusable(config, monkeypatch):
    install_key()
    write_backup(config, signed())
    real_fstat = os.fstat

    def foreign_key(descriptor, *args):
        info = real_fstat(descriptor, *args)
        if stat.S_ISREG(info.st_mode) and info.st_size == 32:
            values = list(info)
            values[stat.ST_UID] = os.getuid() + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(os, "fstat", foreign_key)
    assert run("import")["origin"] == "other"
    write_rc(GOOD)
    assert run("export") == {"ok": False, "error": "key-unusable"}
    monkeypatch.setattr(os, "fstat", real_fstat)
    assert key_path().read_bytes() == KEY


def test_a_version_1_file_is_unsigned_with_the_same_settings(config):
    install_key()
    write_backup(config, document(dict(GOOD, usageMode="nope")))
    old = run("import")
    write_backup(config, signed(dict(GOOD, usageMode="nope")))
    new = run("import")
    assert old.pop("origin") == "unsigned" and new.pop("origin") == "this-computer"
    assert old == new and old["dropped"] == 1


@pytest.mark.parametrize("change", [
    lambda d: d.pop("signature"),
    lambda d: d.pop("sha256"),
    lambda d: d.update(sha256=d["sha256"].upper()),
    lambda d: d.update(signature=d["signature"].upper()),
    lambda d: d.update(sha256=d["sha256"][:63]),
    lambda d: d.update(signature=d["signature"] + "0"),
    lambda d: d.update(signature=" " + d["signature"][1:]),
    lambda d: d.update(sha256=d["sha256"][:63] + "\n"),
    lambda d: d.update(signature=None),
    lambda d: d.update(sha256=int("1" * 64)),
    lambda d: d.update(extra="1"),
    lambda d: d.update(version=1),  # A version 1 file carrying both fields.
    lambda d: (d.update(version=1), d.pop("signature")),
    lambda d: (d.update(version=1), d.pop("sha256")),
])
def test_odd_identity_fields_are_invalid(config, change):
    install_key()
    content = signed()
    change(content)
    write_backup(config, content)
    assert run("import") == {"ok": False, "error": "invalid"}
    assert run("status") == {"ok": False, "error": "invalid"}


def test_export_while_old_data_waits_makes_nothing_in_the_data_folder(config):
    write_rc(GOOD)
    base = Path(os.environ["XDG_DATA_HOME"])
    (base / legacy.LEGACY_NAME).mkdir(parents=True)
    assert run("export") == {"ok": False, "error": "legacy-data"}
    assert os.listdir(base) == [legacy.LEGACY_NAME] and not config.exists()


def test_a_relative_xdg_data_home_falls_back_to_the_home_folder(config, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", "relative/data")
    assert exported(GOOD)["ok"] is True
    assert (tmp_path / "home" / ".local" / "share" / "hearthwire" / "backup-key").stat().st_size == 32
    assert not (tmp_path / "relative").exists()


def test_a_too_large_export_makes_no_key(config, monkeypatch):
    monkeypatch.setattr(backup, "MAX_FILE_BYTES", 200)
    assert exported(GOOD) == {"ok": False, "error": "too-large"}
    assert not Path(os.environ["XDG_DATA_HOME"]).exists()


# --- identity source pins, each with a mutation proof ----------------------------------------------


def module_function(tree, name):
    return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)


def digest_compare_problems(source):
    """Both digest checks use hmac.compare_digest, the checksum first; no ==/!= on a digest."""
    tree = ast.parse(source)
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
            text = ast.unparse(node)
            if re.search(r"sha256|signature|digest", text):
                problems.append(f"== or != on a digest: {text}")
    parse = module_function(tree, "parse_document")
    calls = [node for node in ast.walk(parse) if isinstance(node, ast.Call)
             and ast.unparse(node.func) == "hmac.compare_digest"]
    wanted = {"hmac.compare_digest(content_sha256(content), document['sha256'])",
              "hmac.compare_digest(content_signature(key, content), document['signature'])"}
    if {ast.unparse(call) for call in calls} != wanted or len(calls) != 2:
        problems.append(f"parse_document must compare with {sorted(wanted)}")
        return problems
    by_text = {ast.unparse(call): call.lineno for call in calls}
    key_reads = [node.lineno for node in ast.walk(parse) if isinstance(node, ast.Call)
                 and ast.unparse(node.func) == "signing_key"]
    damaged = [node.lineno for node in ast.walk(parse) if isinstance(node, ast.Raise)
               and "damaged" in ast.unparse(node)]
    checksum = by_text["hmac.compare_digest(content_sha256(content), document['sha256'])"]
    signature = by_text["hmac.compare_digest(content_signature(key, content), document['signature'])"]
    if len(damaged) != 1 or not checksum <= damaged[0] < min(key_reads + [signature]):
        problems.append("the checksum must be checked (and refused as damaged) before the key or the HMAC")
    return problems


def key_source_problems(source):
    """secrets.token_bytes(KEY_BYTES) in _create_key is the only key source; KEY_BYTES is 32."""
    tree = ast.parse(source)
    problems = []
    sources = [(node.lineno, ast.unparse(node)) for node in ast.walk(tree) if isinstance(node, ast.Call)
               and re.fullmatch(r"(os\.urandom|secrets\.\w+|random\.\w+|os\.getrandom)", ast.unparse(node.func))]
    create = module_function(tree, "_create_key")
    inside = {(node.lineno, ast.unparse(node)) for node in ast.walk(create) if isinstance(node, ast.Call)}
    key_sources = [text for line, text in sources if (line, text) in inside and not text.startswith("secrets.token_hex(8)")]
    if key_sources != ["secrets.token_bytes(KEY_BYTES)"]:
        problems.append(f"_create_key must take the key from secrets.token_bytes(KEY_BYTES), found {key_sources}")
    if [text for _, text in sources].count("secrets.token_bytes(KEY_BYTES)") != 1:
        problems.append("secrets.token_bytes(KEY_BYTES) must appear exactly once")
    if not re.search(r"^KEY_BYTES = 32$", source, re.MULTILINE):
        problems.append("KEY_BYTES must be 32")
    return problems


def sign_context_problems(source):
    tree = ast.parse(source)
    body = module_function(tree, "content_signature")
    calls = [ast.unparse(node) for node in ast.walk(body) if isinstance(node, ast.Call)
             and ast.unparse(node.func) == "hmac.new"]
    problems = [] if calls == ["hmac.new(key, SIGN_CONTEXT + content, hashlib.sha256)"] else [
        f"content_signature must be hmac.new(key, SIGN_CONTEXT + content, hashlib.sha256), found {calls}"]
    if 'SIGN_CONTEXT = b"hearthwire-settings-backup\\x00"' not in source:
        problems.append("SIGN_CONTEXT changed")
    return problems


def test_digests_are_compared_in_constant_time_checksum_first():
    problems = digest_compare_problems(SOURCE.read_text(encoding="utf-8"))
    assert not problems, problems


def test_the_key_comes_only_from_secrets_token_bytes_32():
    problems = key_source_problems(SOURCE.read_text(encoding="utf-8"))
    assert not problems, problems


def test_the_signature_has_its_context():
    problems = sign_context_problems(SOURCE.read_text(encoding="utf-8"))
    assert not problems, problems


def source_mutated(old, new):
    text = SOURCE.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"proof fixture out of date: {old!r}"
    return text.replace(old, new)


CHECKSUM_LINE = 'if not hmac.compare_digest(content_sha256(content), document["sha256"]):'
SIGNATURE_LINE = 'hmac.compare_digest(content_signature(key, content), document["signature"])'
CHECKSUM_BLOCK = ("        " + CHECKSUM_LINE + "\n"
                  '            raise HelperError("damaged")  # M-4: refused, not a warning.\n')
KEY_READ = "        key = signing_key() if signing_key is not None else None\n"
HMAC_BLOCK = (KEY_READ + '        origin = "other"\n'
              "        if key is not None and " + SIGNATURE_LINE + ":\n"
              '            origin = "this-computer"\n')


@pytest.mark.parametrize(("old", "new"), [
    (CHECKSUM_LINE, 'if content_sha256(content) != document["sha256"]:'),
    (SIGNATURE_LINE, 'content_signature(key, content) == document["signature"]'),
    (SIGNATURE_LINE, 'hmac.compare_digest(content_signature(key, content), document["sha256"])'),
    (CHECKSUM_BLOCK + HMAC_BLOCK, HMAC_BLOCK + CHECKSUM_BLOCK),       # HMAC checked before the checksum
    (CHECKSUM_BLOCK + KEY_READ, KEY_READ + CHECKSUM_BLOCK),           # key read before the checksum
])
def test_proof_digest_compare_rule_catches(old, new):
    assert digest_compare_problems(source_mutated(old, new))


@pytest.mark.parametrize(("old", "new"), [
    ("key = secrets.token_bytes(KEY_BYTES)", "key = os.urandom(16)"),
    ("key = secrets.token_bytes(KEY_BYTES)", "key = os.urandom(KEY_BYTES)"),
    ("key = secrets.token_bytes(KEY_BYTES)", "key = secrets.token_bytes(16)"),
    ("KEY_BYTES = 32\n", "KEY_BYTES = 16\n"),
])
def test_proof_key_source_rule_catches(old, new):
    assert key_source_problems(source_mutated(old, new))


@pytest.mark.parametrize(("old", "new"), [
    ("hmac.new(key, SIGN_CONTEXT + content, hashlib.sha256)", "hmac.new(key, content, hashlib.sha256)"),
    ("hmac.new(key, SIGN_CONTEXT + content, hashlib.sha256)", "hmac.new(key, content + SIGN_CONTEXT, hashlib.sha256)"),
    ('SIGN_CONTEXT = b"hearthwire-settings-backup\\x00"', 'SIGN_CONTEXT = b""'),
])
def test_proof_sign_context_rule_catches(old, new):
    assert sign_context_problems(source_mutated(old, new))


# --- the CLI --------------------------------------------------------------------------------------


def test_cli_round_trip(config, capsys):
    assert cli_reply(capsys, "--settings-backup", "status") == {"ok": True, "exists": False}
    write_rc(GOOD)
    reply = cli_reply(capsys, "--settings-backup", "export", "--applet", "7")
    assert reply == {"ok": True, "saved": len(GOOD), "dropped": 0}
    status = cli_reply(capsys, "--settings-backup", "status")
    assert status["exists"] is True and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", status["exported_at"])
    imported = cli_reply(capsys, "--settings-backup", "import")
    assert imported["settings"] == GOOD_KEPT and imported["dropped"] == 0
    # The widget passes its id to every backup command; status and import ignore it.
    assert cli_reply(capsys, "--settings-backup", "status", "--applet", "7") == status
    assert cli_reply(capsys, "--settings-backup", "import", "--applet", "99") == imported
    assert cli_reply(capsys, "--settings-backup", "export", "--applet", "99") == \
        {"ok": False, "error": "applet-not-found"}


def test_cli_replies_never_hold_a_path(config, capsys, tmp_path):
    write_rc(GOOD)
    config.write_text("x")
    for argv in (["status"], ["import"], ["export", "--applet", "7"], ["export", "--applet", "8"]):
        assert cli.main(["--settings-backup", *argv]) == 0
        captured = capsys.readouterr()
        assert str(tmp_path) not in captured.out and captured.err == "" and "Traceback" not in captured.out
        assert json.loads(captured.out)["ok"] is False


def test_cli_turns_any_surprise_into_os_error(config, capsys, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError(str(config))

    monkeypatch.setattr(backup, "status", boom)
    assert cli_reply(capsys, "--settings-backup", "status") == {"ok": False, "error": "os-error"}


@pytest.mark.parametrize("argv", [
    ["--settings-backup", "export"],
    ["--settings-backup", "status", "--data", "7b7d"],
    ["--settings-backup", "import", "--data", "7b7d"],
    ["--data", "7b7d"],
    ["--settings-backup", "nope"],
    ["--settings-backup", "status", "--json"],
    ["--settings-backup", "status", "--detect"],
    ["--settings-backup", "status", "--store", "encrypted"],
    ["--settings-backup", "status", "--prompts", "list"],
    ["--settings-backup", "status", "--read-dropped", "2f61"],
    ["--settings-backup", "export", "--applet", "7", "--sample", "claude.session=1"],
    ["--settings-backup", "export", "--applet", "7", "--generation", "1"],
    ["--settings-backup", "export", "--applet", "7", "--usage-history", "read"],
    ["--settings-backup", "export", "--applet", "7", "--all"],
    # Audit M1: --data is refused in every form, with or without --applet.
    ["--settings-backup", "export", "--data", "7b7d"],
    ["--settings-backup", "export", "--applet", "7", "--data", "7b7d"],
    ["--settings-backup", "export", "--applet", "7", "--data="],
    ["--settings-backup", "export", "--applet", "7", "--dat", "7b7d"],
    ["--settings-backup", "export", "--applet", "0"],
    ["--settings-backup", "export", "--applet", "-1"],
    ["--settings-backup", "export", "--applet", "2147483649"],
    ["--settings-backup", "export", "--applet", "x"],
    ["--settings-backup", "status", "--applet", "0"],
])
def test_cli_argument_rules_exit_2(config, capsys, argv):
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 2
    assert capsys.readouterr().out == ""


def test_a_refused_data_argument_is_never_echoed(config, capsys):
    secret = '{"chatCustomUrls":"{\\"claude\\":\\"https://private.example.org/\\"}"}'.encode().hex()
    for argv in (["--settings-backup", "export", "--applet", "7", "--data", secret], ["--data", secret]):
        with pytest.raises(SystemExit) as raised:
            cli.main(argv)
        assert raised.value.code == 2
        captured = capsys.readouterr()
        assert captured.out == "" and secret not in captured.err and "--data" in captured.err
    assert not config.exists()


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
            # legacy: only legacy-data; appletconfig: the applied settings; jsondepth: the depth limit.
            assert node.module in ("appletconfig", "catalog", "jsondepth", "webdata", "legacy"), node.module
    assert imported <= {"__future__", "collections", "datetime", "errno", "json", "math", "os", "pathlib", "re",
                        "stat", "time", "typing", "bisect", "hashlib", "hmac", "secrets", "fcntl"}, imported
    for banned in ("socket", "http", "urllib", "ssl", "subprocess"):
        assert banned not in imported


def test_the_catalog_import_is_read_only():
    text = SOURCE.read_text(encoding="utf-8")
    assert "from .catalog import CATALOG_BY_ID, PROVIDER_CATALOG, PROVIDER_IDS" in text
    assert not re.search(r"\b(PROVIDER_CATALOG|CATALOG_BY_ID|PROVIDER_IDS)\s*(\[[^\]]*\])?\s*=[^=]", text)
