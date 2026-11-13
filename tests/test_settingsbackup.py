"""Settings backup (core/settingsbackup.py) and --settings-backup."""

import ast
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from hearthwire import cli
from hearthwire.core import appletconfig
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


def chat_sites_js_results(tmp_path, qml):
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
    assert match is not None, output
    return json.loads(match.group(1))


def test_the_port_gives_the_same_codes_as_chat_sites_js(tmp_path):
    """Runs the widget's own validateCustomUrl on every case (skipped without qmltestrunner)."""
    codes = chat_sites_js_results(tmp_path, PARITY_QML % json.dumps(URL_CASES))
    assert [backup.custom_url_error(site, url) for site, url in URL_CASES] == codes


# --- chatUserSites and chatSiteOrder: the ChatSites.js port (task 005) ----------------------------

# (name, the other added sites' names, code). Lengths count UTF-16 units, as JS .length.
NAME_CASES = [
    ("Le Chat", (), ""), ("A", (), ""), ("Le Chat (beta) #1", (), ""), ("Claude2", (), ""), ("Mistral", ("Other",), ""),
    ("a" * 40, (), ""), ("a" * 41, (), "name-too-long"),
    ("\U0001f600" * 20, (), ""), ("\U0001f600" * 20 + "a", (), "name-too-long"), ("a" + "\U0001f600" * 20, (), "name-too-long"),
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
    ("Le\ud800Chat", (), "name-chars"), ("Le\udc00Chat", (), "name-chars"), ("Le Chat\ud83d", (), "name-chars"),
    ("<b>x</b>", (), "name-chars"), ("a&b", (), "name-chars"), ("a>b", (), "name-chars"), ("a<b", (), "name-chars"),
    ("a\"b'c", (), ""), ("a/b\\c", (), ""),
    # Invisible and bidi formatting (M3), every listed point and range end.
    *[("Le" + chr(point) + "Chat", (), "name-chars") for point in (
        0x00AD, 0x061C, 0x180E, 0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2028, 0x2029, 0x202A, 0x202B, 0x202C,
        0x202D, 0x202E, 0x2060, 0x2061, 0x2062, 0x2063, 0x2064, 0x2066, 0x2067, 0x2068, 0x2069, 0xFEFF)],
    ("Le\u200aChat", (), ""), ("Le\u2030Chat", (), ""), ("Le\u2065Chat", (), ""), ("Le\u206aChat", (), ""),
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

# (address, code), checked in the order of plan section 2.1.
USER_URL_CASES = [
    ("https://chat.example.org/chat", ""), ("https://a.example.com", ""), ("HTTPS://A.Example.COM:8443/x?q=1#f", ""),
    ("https://nas.local/", ""), ("https://nas.lan", ""), ("https://example.com1/", ""), ("https://a.example.com./", ""),
    ("https://a.example.com/@x", ""), ("https://a.example.com/%41'~!$()*,;=", ""), ("https://xn--mnchen-3ya.example/", ""),
    ("", "url-empty"),
    ("https://a.example.com/" + "a" * 2026, ""), ("https://a.example.com/" + "a" * 2027, "too-long"),
    ("https://a.example.com/" + "\U0001f600" * 1014, "too-long"),
    ("https://a.example.com/ x", "whitespace"), ("https://a.example.com/\t", "whitespace"),
    ("https://a.example.com/\u00a0", "whitespace"), ("https://a.example.com/\u2028", "whitespace"),
    ("https://a.example.com/\u3000", "whitespace"), ("https://a.example.com/\ufeff", "whitespace"),
    ("https://a.example.com/\x00", "whitespace"), ("https://a.example.com/\x7f", "whitespace"),
    (" https://a.example.com/", "whitespace"), ("https://user@a.example.com/ ", "whitespace"),
    ("https://a.example.com/\x85", "url-chars"), ("https://a.example.com/\u00fc", "url-chars"),
    ("https://ex\u00e4mple.com/", "url-chars"), ("https://a.example.com/\U0001f600", "url-chars"),
    ("https://a.example.com/\u200b", "url-chars"), ("https://a.example.com/\u202e", "url-chars"),
    ("https://a.example.com/\ud800", "url-chars"), ("https://user@a.example.com/\u00fc", "url-chars"),
    *[("https://a.example.com/" + char, "url-chars") for char in '"\\<>`{}|^'],
    ("https://user@a.example.com/", "userinfo"), ("https://a:b@a.example.com/", "userinfo"),
    ("http://user@a.example.com/", "userinfo"), ("ftp://user@a.example.com/", "userinfo"),
    ("https://@a.example.com/", "userinfo"),
    ("a.example.com", "malformed"), ("//a.example.com/", "malformed"), ("1https://a.example.com/", "malformed"),
    ("http://a.example.com/", "http-not-allowed"), ("HTTP://a.example.com/", "http-not-allowed"),
    ("http://localhost/", "http-not-allowed"), ("http:x", "http-not-allowed"),
    ("ftp://a.example.com/", "scheme"), ("javascript:alert(1)", "scheme"), ("data:text/html,x", "scheme"),
    ("about:blank", "scheme"), ("file:///etc/passwd", "scheme"), ("httpss://a.example.com/", "scheme"),
    ("https:a.example.com", "malformed"), ("https:///x", "malformed"), ("https://", "malformed"),
    ("https://[fd00::1]/", "malformed"), ("https://[::2]/", "malformed"), ("https://a_b.example.com/", "malformed"),
    ("https://a.example.com%2f/", "malformed"), ("https://.a.example.com/", "malformed"),
    ("https://a..example.com/", "malformed"), ("https://a.example.com:0/", "malformed"),
    ("https://a.example.com:65536/", "malformed"), ("https://a.example.com:/", "malformed"),
    ("https://[::1]/", "loopback-not-allowed"), ("https://localhost/", "loopback-not-allowed"),
    ("https://LOCALHOST./", "loopback-not-allowed"), ("https://intranet/", "loopback-not-allowed"),
    ("https://a.localhost/", "loopback-not-allowed"), ("https://a.localhost.localdomain/", "loopback-not-allowed"),
    ("https://ip6-loopback/", "loopback-not-allowed"), ("https://127.0.0.1/", "loopback-not-allowed"),
    ("https://127.1/", "loopback-not-allowed"), ("https://0x7f000001/", "loopback-not-allowed"),
    ("https://017700000001/", "loopback-not-allowed"), ("https://0x7f.1/", "loopback-not-allowed"),
    ("https://0/", "loopback-not-allowed"), ("https://0.0.0.0/", "loopback-not-allowed"),
    ("https://1.2.3.256/", "loopback-not-allowed"), ("https://1.2.3.08/", "loopback-not-allowed"),
    ("https://1.2.3.4.5/", "loopback-not-allowed"), ("https://example.0x/", "loopback-not-allowed"),
    ("https://example.123/", "loopback-not-allowed"), ("https://0x08080808/", "loopback-not-allowed"),
    ("https://134744072/", "loopback-not-allowed"),
    # M2: every IPv4 literal is refused in 005, private, link-local and public alike.
    ("https://10.0.0.1/", "ip-literal"), ("https://172.16.0.1/", "ip-literal"), ("https://192.168.1.1/", "ip-literal"),
    ("https://169.254.169.254/", "ip-literal"), ("https://1.2.3.4/", "ip-literal"), ("https://8.8.8.8./", "ip-literal"),
    ("https://0x8.0x8.0x8.0x8/", "ip-literal"), ("https://8.8.2056/", "ip-literal"), ("https://10.1/", "ip-literal"),
    ("https://0xa.0.0.1:8443/", "ip-literal"),
]


@pytest.mark.parametrize(("name", "others", "code"), NAME_CASES)
def test_user_site_name_codes(name, others, code):
    assert backup.user_site_name_error(name, others) == code


@pytest.mark.parametrize(("url", "code"), USER_URL_CASES)
def test_user_site_url_codes(url, code):
    assert backup.user_site_url_error(url) == code
    assert backup.address_class(url) == ("public" if code == "" else "")


def test_the_user_site_lists_have_no_repeated_case():
    assert len({(name, others) for name, others, _ in NAME_CASES}) == len(NAME_CASES)
    assert len({url for url, _ in USER_URL_CASES}) == len(USER_URL_CASES)


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
    urls = [url for url, _ in USER_URL_CASES]
    results = chat_sites_js_results(tmp_path, USER_SITE_PARITY_QML % (json.dumps(names), json.dumps(urls)))
    expected = ([backup.user_site_name_error(name, others) for name, others, _ in NAME_CASES]
                + [backup.user_site_url_error(url) for url in urls] + [backup.address_class(url) for url in urls])
    assert results == expected


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
    *[user_sites(entry_with(url=url)) for url, code in USER_URL_CASES if code],
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
    emoji = entry_with(name="\U0001f600" * 20)
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
    assert run("import") == {"ok": True, "exported_at": STAMP, "settings": settings, "dropped": 0}
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
    assert json.loads(path.read_text()) == document(GOOD_KEPT)
    assert path.read_text().endswith("}\n")
    assert "chatSignInStorage" not in path.read_text()


def test_export_status_import_round_trip(config):
    exported(GOOD)
    assert run("status") == {"ok": True, "exists": True, "exported_at": STAMP}
    assert run("import") == {"ok": True, "exported_at": STAMP, "settings": GOOD_KEPT, "dropped": 0}
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
    (document(format="other"), "invalid"), (document(version=2), "unsupported"),
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
                        "stat", "time", "typing"}, imported
    for banned in ("socket", "http", "urllib", "ssl", "subprocess"):
        assert banned not in imported


def test_the_catalog_import_is_read_only():
    text = SOURCE.read_text(encoding="utf-8")
    assert "from .catalog import CATALOG_BY_ID, PROVIDER_CATALOG, PROVIDER_IDS" in text
    assert not re.search(r"\b(PROVIDER_CATALOG|CATALOG_BY_ID|PROVIDER_IDS)\s*(\[[^\]]*\])?\s*=[^=]", text)
