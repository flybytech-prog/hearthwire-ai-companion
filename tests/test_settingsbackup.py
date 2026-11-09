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
}
# What the checks keep of GOOD: canonical JSON (catalog order), lower-case colors.
GOOD_KEPT = dict(GOOD, usageNormalColor="#00aaff",
                 tooltipMetrics='{"claude":["weekly"],"codex":[]}',
                 chatCustomUrls='{"claude":"https://claude.example.org/new?x=1","local":"http://localhost:8080/"}')


@pytest.fixture
def config(tmp_path, monkeypatch):
    """Every XDG base and HOME inside tmp_path; returns the backup folder path."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "home").mkdir()
    return tmp_path / "config" / "hearthwire"


def hexed(value):
    text = value if isinstance(value, str) else json.dumps(value)
    return text.encode("utf-8").hex()


def run(operation, data=None, now=NOW):
    try:
        if operation == "export":
            return backup.export(data, clock=lambda: now)
        return backup.run(operation)
    except backup.HelperError as error:
        return {"ok": False, "error": error.code}


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
                "chatSiteZoom", "configSchemaVersion", "initialSetupComplete"):
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
    if key not in ("chatCustomUrls",):
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


def test_the_port_gives_the_same_codes_as_chat_sites_js(tmp_path):
    """Runs the widget's own validateCustomUrl on every case (skipped without qmltestrunner)."""
    runner = shutil.which("qmltestrunner", path="/usr/lib/qt6/bin:/usr/bin:/bin")
    if runner is None:
        pytest.skip("qmltestrunner is not installed")
    shutil.copy2(UI / "ChatSites.js", tmp_path / "ChatSites.js")
    (tmp_path / "tst_parity.qml").write_text(PARITY_QML % json.dumps(URL_CASES), encoding="utf-8")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "LANG": "C.UTF-8", "QT_QPA_PLATFORM": "offscreen",
           "XDG_RUNTIME_DIR": str(tmp_path), "TMPDIR": str(tmp_path)}
    completed = subprocess.run([runner, "-input", str(tmp_path / "tst_parity.qml")], env=env, cwd=tmp_path,
                               capture_output=True, text=True, timeout=120, check=False)
    output = completed.stdout + completed.stderr
    match = re.search(r"PARITY (\[.*\])", output)
    if match is None and "module \"QtTest\" is not installed" in output:
        pytest.skip("QtTest is not installed")
    assert match is not None, output
    assert [backup.custom_url_error(site, url) for site, url in URL_CASES] == json.loads(match.group(1))


# --- strict JSON ----------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ['{"a":NaN}', '{"a":Infinity}', '{"a":-Infinity}', '{"a":1e999}',
                                  '{"a":1,"a":2}', '{"a":{"b":1,"b":1}}', "[" * 100000 + "]" * 100000,
                                  '{"a":' + "1" * 5000 + "}", "{", ""])
def test_strict_loads_refuses(text):
    with pytest.raises(ValueError):
        backup.strict_loads(text)


# --- export ---------------------------------------------------------------------------------------


def test_export_writes_a_private_file_atomically(config):
    assert run("export", hexed(dict(GOOD, chatSignInStorage="encrypted"))) == \
        {"ok": True, "saved": len(GOOD), "dropped": 1}
    assert stat.S_IMODE(config.stat().st_mode) == 0o700
    path = config / "settings-backup.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert os.listdir(config) == ["settings-backup.json"]
    assert json.loads(path.read_text()) == document(GOOD_KEPT)
    assert path.read_text().endswith("}\n")
    assert "chatSignInStorage" not in path.read_text()


def test_export_status_import_round_trip(config):
    run("export", hexed(GOOD))
    assert run("status") == {"ok": True, "exists": True, "exported_at": STAMP}
    assert run("import") == {"ok": True, "exported_at": STAMP, "settings": GOOD_KEPT, "dropped": 0}
    # Exporting what import gave keeps it unchanged.
    before = (config / "settings-backup.json").read_bytes()
    run("export", hexed(GOOD_KEPT))
    assert (config / "settings-backup.json").read_bytes() == before


def test_export_replaces_the_old_backup(config):
    run("export", hexed(GOOD))
    old = os.stat(config / "settings-backup.json").st_ino
    assert run("export", hexed({"usageMode": "remaining"}), now=NOW + 60)["saved"] == 1
    assert os.stat(config / "settings-backup.json").st_ino != old
    assert run("import")["settings"] == {"usageMode": "remaining"}
    assert run("import")["exported_at"] == "2026-11-06T00:11:29Z"


def test_export_tightens_a_safe_folder_to_0700(config):
    config.mkdir(parents=True)
    config.chmod(0o755)
    assert run("export", hexed(GOOD))["ok"] is True
    assert stat.S_IMODE(config.stat().st_mode) == 0o700


@pytest.mark.parametrize("data", [
    "", "0", "zz", "7B7D", "7b7d0", " 7b7d", hexed("{}"), hexed("[]"), hexed('"x"'), hexed("null"),
    hexed('{"usageMode":NaN}'), hexed('{"usageMode":"used","usageMode":"used"}'), "ff" * 4, hexed("{"),
    hexed({"bogus": 1}), hexed({"usageMode": "nope"}), "7b" + "20" * 65535 + "7d",
])
def test_export_refuses_bad_data_and_writes_nothing(config, tmp_path, data):
    assert run("export", data) == {"ok": False, "error": "bad-data"}
    assert not (tmp_path / "config").exists()


def test_export_data_may_be_exactly_131072_hex_characters(config):
    text = json.dumps({"usageMode": "used"})
    padded = text[:-1] + " " * (65536 - len(text)) + "}"
    assert len(hexed(padded)) == 131072
    assert run("export", hexed(padded))["ok"] is True


def test_export_never_writes_a_file_import_would_refuse(config, monkeypatch):
    monkeypatch.setattr(backup, "MAX_FILE_BYTES", 200)
    assert run("export", hexed(GOOD)) == {"ok": False, "error": "too-large"}
    assert not config.exists()


def test_export_refuses_a_symlinked_folder_or_file(config, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "config").mkdir()
    config.symlink_to(elsewhere)
    assert run("export", hexed(GOOD)) == {"ok": False, "error": "symlink"}
    assert os.listdir(elsewhere) == []
    config.unlink()
    config.mkdir(mode=0o700)
    target = tmp_path / "precious"
    target.write_text("keep")
    (config / "settings-backup.json").symlink_to(target)
    assert run("export", hexed(GOOD)) == {"ok": False, "error": "symlink"}
    assert target.read_text() == "keep"


@pytest.mark.parametrize("mode", [0o770, 0o702, 0o777])
def test_an_unsafe_folder_is_refused(config, mode):
    write_backup(config, document(), folder_mode=mode)
    for operation in ("status", "import"):
        assert run(operation) == {"ok": False, "error": "unsafe-mode"}
    assert run("export", hexed(GOOD)) == {"ok": False, "error": "unsafe-mode"}
    assert stat.S_IMODE(config.stat().st_mode) == mode


def test_a_failed_export_leaves_the_old_backup_and_no_temporary(config, monkeypatch):
    run("export", hexed(GOOD))
    before = (config / "settings-backup.json").read_bytes()

    def failing_fsync(descriptor):
        raise OSError(5, "I/O")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    assert run("export", hexed({"usageMode": "remaining"})) == {"ok": False, "error": "os-error"}
    assert (config / "settings-backup.json").read_bytes() == before
    assert os.listdir(config) == ["settings-backup.json"]


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


def test_a_file_over_64_kib_is_too_large(config):
    text = json.dumps(document())
    write_backup(config, text + " " * (65536 - len(text)))
    assert run("import")["ok"] is True
    write_backup(config, text + " " * (65537 - len(text)))
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
    reply = cli_reply(capsys, "--settings-backup", "export", "--data", hexed(GOOD))
    assert reply == {"ok": True, "saved": len(GOOD), "dropped": 0}
    status = cli_reply(capsys, "--settings-backup", "status")
    assert status["exists"] is True and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", status["exported_at"])
    imported = cli_reply(capsys, "--settings-backup", "import")
    assert imported["settings"] == GOOD_KEPT and imported["dropped"] == 0


def test_cli_replies_never_hold_a_path(config, capsys, tmp_path):
    config.parent.mkdir(parents=True)
    config.write_text("x")
    for argv in (["status"], ["import"], ["export", "--data", hexed(GOOD)], ["export", "--data", "zz"]):
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
    ["--settings-backup", "export", "--data", "7b7d", "--sample", "claude.session=1"],
])
def test_cli_argument_rules_exit_2(config, capsys, argv):
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 2
    assert capsys.readouterr().out == ""


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
            assert node.module in ("catalog", "webdata", "legacy"), node.module  # legacy: only legacy-data
    assert imported <= {"__future__", "collections", "datetime", "errno", "json", "math", "os", "pathlib", "re",
                        "stat", "time", "typing"}, imported
    for banned in ("socket", "http", "urllib", "ssl", "subprocess"):
        assert banned not in imported


def test_the_catalog_import_is_read_only():
    text = SOURCE.read_text(encoding="utf-8")
    assert "from .catalog import CATALOG_BY_ID, PROVIDER_CATALOG, PROVIDER_IDS" in text
    assert not re.search(r"\b(PROVIDER_CATALOG|CATALOG_BY_ID|PROVIDER_IDS)\s*(\[[^\]]*\])?\s*=[^=]", text)
