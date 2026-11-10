"""Static checks for the Chat tab's privacy policy (docs/privacy.md, "Chat tab").

The Chat tab hosts provider websites in Qt WebEngine inside plasmashell. Its
top constraint is that nothing the user enters reaches disk, logs, argv, env
or the plasmoid config. These tests scan the plasmoid sources for the rules
that keep it that way. Comments are stripped before searching, so a comment
that names a forbidden API cannot fail a test, while real code still does.
String literals are kept: a forbidden name inside a string (for example in
``Qt.createQmlObject``) is still a real use.
"""

import ast
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from hearthwire.core.settingsbackup import BACKUP_KEYS, EXCLUDED_KEYS


PLASMOID = Path(__file__).resolve().parent.parent / "plasmoid"
CONTENTS = PLASMOID / "contents"
UI = CONTENTS / "ui"
MAIN_XML = CONTENTS / "config" / "main.xml"
CHAT_SITES_JS = UI / "ChatSites.js"
CHAT_STORAGE_JS = UI / "ChatStorage.js"
CHAT_WEB_VIEW = UI / "ChatWebView.qml"
CHAT_VIEW = UI / "ChatView.qml"
FULL_REPRESENTATION = UI / "FullRepresentation.qml"
MAIN_QML = UI / "main.qml"
CONFIG_QML = CONTENTS / "config" / "config.qml"
# Settings pages in dialog order: General (popup, usage display, privacy),
# AI Usage (providers), Chat (sites, addresses).
CONFIG_PAGES = (UI / "configGeneral.qml", UI / "configUsage.qml", UI / "configChat.qml")
SETTINGS_LOGIC_JS = UI / "SettingsLogic.js"
OLLAMA_CHAT_JS = UI / "OllamaChat.js"
INSTALL_INFO_JS = UI / "InstallInfo.js"
OLLAMA_CHAT_VIEW = UI / "OllamaChatView.qml"
COMPACT_REPRESENTATION = UI / "CompactRepresentation.qml"
PROMPT_LIBRARY_JS = UI / "PromptLibrary.js"
PROMPT_LIBRARY_PANEL = UI / "PromptLibraryPanel.qml"
SRC = PLASMOID.parent / "src" / "hearthwire"
PORT_OWNER_PY = SRC / "core" / "portowner.py"
CLI_PY = SRC / "cli.py"
# Files of the built-in Ollama chat that are written in later plan phases.
# Rules about them skip while the file does not exist and enforce once it does.
PHASED_FILES = {"OllamaChat.js": "T1", "OllamaChatView.qml": "T4"}
# Chat files that may read the plasmoid config but never write it. Only the
# settings pages persist chat values (and main.qml the profile generation).
CHAT_CONFIG_READ_ONLY_FILES = (
    "ChatSites.js", "ChatStorage.js", "ChatView.qml", "ChatWebView.qml", "FullRepresentation.qml",
    "OllamaChat.js", "OllamaChatView.qml",
    # Plan R2 (drops on the panel icon) and R4 (prompt library).
    "CompactRepresentation.qml", "PromptLibrary.js", "PromptLibraryPanel.qml",
)
KCFG_NS = "{http://www.kde.org/standards/kcfg/1.0}"

EXPECTED_SITE_IDS = ["claude", "chatgpt", "grok", "gemini", "copilot", "mscopilot", "local"]
# Sites enabled for a fresh widget. Local is off until the user turns it on.
EXPECTED_DEFAULT_SITE_IDS = ["claude", "chatgpt", "grok", "gemini", "copilot", "mscopilot"]
LOCAL_SITE_ID = "local"
# Name, type and exact default of every persisted chat key.
CHAT_CONFIG_KEYS = {
    "chatSites": ("String", None),
    "chatDefaultSite": ("String", None),
    "chatCustomUrls": ("String", "{}"),
    "chatSignInStorage": ("String", "memory"),
    "chatProfileGeneration": ("Int", "0"),
    # Lock automatically, in minutes; 0 = never.
    "chatAutoLockMinutes": ("Int", "0"),
    # Keep the popup open when clicking elsewhere.
    "chatKeepOpen": ("Bool", "false"),
    # Per-site zoom, JSON {siteId: factor}; written only by main.qml (plan R1).
    "chatSiteZoom": ("String", "{}"),
    # Unlock with: passphrase | wallet (plan R3); written only by configGeneral.qml.
    "chatVaultUnlock": ("String", "passphrase"),
}
# The Ollama address (plan T4). Expected once main.xml has it or the Ollama
# view exists, so it can neither be half-added nor forgotten.
OLLAMA_CONFIG_KEYS = {"chatOllamaUrl": ("String", "http://127.0.0.1:11434")}
# Keys that existed before the Chat tab. Anything else in main.xml would be a
# new persisted value; the Chat tab may only persist the keys above.
PRE_CHAT_CONFIG_KEYS = {
    "trackedProviders", "providerMetrics", "usageMode",
    "refreshInterval", "configSchemaVersion", "initialSetupComplete",
}
# Settings → General → Popup / Usage, with exact type and default.
GENERAL_CONFIG_KEYS = {
    "popupDefaultTab": ("String", "chat"),
    "showUsageTab": ("Bool", "true"),
    "showChatTab": ("Bool", "true"),
    "popupSize": ("String", "normal"),
    "tooltipShowsUsage": ("Bool", "true"),
    # The hover tooltip's reset times and its own readings ("" = same as Usage).
    "tooltipMetrics": ("String", ""),
    # Usage tab: provider order ("" = catalog order), compact rows, bar colors.
    "providerOrder": ("String", ""),
    "usageCompact": ("Bool", "false"),
    "usageWarnPercent": ("Int", "60"),
    "usageCriticalPercent": ("Int", "85"),
    "usageNormalColor": ("String", ""),
    "usageWarnColor": ("String", ""),
    "usageCriticalColor": ("String", ""),
    # Plan R1: what the global shortcut opens, and the usage alerts.
    "shortcutOpens": ("String", "popup"),
    "alertLowEnabled": ("Bool", "false"),
    "alertLowPercent": ("Int", "20"),
    "alertResetEnabled": ("Bool", "false"),
    # Round 4: the panel ring, the middle-click and the opt-in usage history.
    # usageHistoryClearOwed: a turned-off history still has to be deleted.
    "panelRing": ("String", "auto"),
    "middleClickOpens": ("String", "refresh"),
    "usageHistoryEnabled": ("Bool", "false"),
    "usageHistoryClearOwed": ("Bool", "false"),
}

# Characters after which a "/" starts a regex literal rather than division.
_REGEX_PRECEDERS = set("(,=:[!&|?{};+-*%<>~^")
_REGEX_KEYWORDS = ("return", "typeof", "case", "do", "else", "in", "of", "void", "new", "delete")


def _strip_comments(source, blank_strings=False):
    """Replace // and /* */ comments in QML/JS with spaces.

    String, template and regex literals are skipped so "https://..." is not
    mistaken for a comment. Newlines and offsets are preserved, so positions
    and line numbers in the result match the original file. With
    ``blank_strings`` the contents of string literals are blanked too, which
    makes brace matching safe.
    """
    out = list(source)
    length = len(source)
    index = 0
    last_significant = ""

    def blank(start, end, keep_delimiters=False):
        lo, hi = (start + 1, end - 1) if keep_delimiters else (start, end)
        for pos in range(lo, hi):
            if out[pos] != "\n":
                out[pos] = " "

    def regex_allowed():
        if last_significant == "" or last_significant in _REGEX_PRECEDERS:
            return True
        tail = "".join(source[max(0, index - 8):index]).rstrip()
        return any(
            tail.endswith(word) and (len(tail) == len(word) or not (tail[-len(word) - 1].isalnum() or tail[-len(word) - 1] == "_"))
            for word in _REGEX_KEYWORDS
        )

    while index < length:
        char = source[index]
        nxt = source[index + 1] if index + 1 < length else ""
        if char == "/" and nxt == "/":
            end = source.find("\n", index)
            end = length if end == -1 else end
            blank(index, end)
            index = end
            continue
        if char == "/" and nxt == "*":
            end = source.find("*/", index + 2)
            end = length if end == -1 else end + 2
            blank(index, end)
            index = end
            continue
        if char in "\"'`":
            end = index + 1
            while end < length and source[end] != char:
                if source[end] == "\\":
                    end += 1
                elif source[end] == "\n" and char != "`":
                    break
                end += 1
            end = min(end + 1, length)
            if blank_strings:
                blank(index, end, keep_delimiters=True)
            last_significant = char
            index = end
            continue
        if char == "/" and regex_allowed():
            end = index + 1
            in_class = False
            while end < length and source[end] != "\n":
                current = source[end]
                if current == "\\":
                    end += 2
                    continue
                if current == "[":
                    in_class = True
                elif current == "]":
                    in_class = False
                elif current == "/" and not in_class:
                    break
                end += 1
            if end < length and source[end] == "/":
                end += 1
                while end < length and source[end].isalpha():
                    end += 1
                if blank_strings:
                    blank(index, end, keep_delimiters=True)
                last_significant = "/"
                index = end
                continue
        if not char.isspace():
            last_significant = char
        index += 1
    return "".join(out)


def _read_code(path):
    assert path.is_file(), f"{path.relative_to(PLASMOID.parent)} is missing"
    return _strip_comments(path.read_text(encoding="utf-8"))


def _require_phased(path):
    """Skip a rule about a not-yet-written Ollama file; enforce once it exists."""
    if path.name in PHASED_FILES and not path.is_file():
        pytest.skip(f"{path.name} is not written yet (plan task {PHASED_FILES[path.name]}); "
                    "this rule enforces as soon as the file exists")


def _line_of(text, offset):
    return text.count("\n", 0, offset) + 1


def _hits(pattern, text):
    return [_line_of(text, match.start()) for match in re.finditer(pattern, text)]


def _rel(path):
    return path.relative_to(PLASMOID.parent).as_posix()


def _code_files():
    return sorted(
        path for path in PLASMOID.rglob("*")
        if path.is_file() and path.suffix in {".qml", ".js"}
    )


def _text_files():
    return sorted(
        path for path in PLASMOID.rglob("*")
        if path.is_file() and path.suffix in {".json", ".xml", ".desktop"}
    )


def _blocks(code, opener):
    """Yield the text of each ``opener`` block, e.g. ``WebEngineProfile {``.

    ``opener`` is a regex that must end at the opening brace or at a handler
    colon followed by a function/arrow/brace body.
    """
    blanked = _strip_comments(code, blank_strings=True)
    for match in re.finditer(opener, blanked):
        start = blanked.find("{", match.end() - 1)
        if start == -1:
            continue
        depth = 0
        for index in range(start, len(blanked)):
            if blanked[index] == "{":
                depth += 1
            elif blanked[index] == "}":
                depth -= 1
                if depth == 0:
                    yield match.start(), code[start:index + 1]
                    break


def _sites_literal(source):
    match = re.search(r"\b(?:var|let|const)\s+sites\s*=\s*\[", source)
    assert match, "ChatSites.js must declare `var sites = [ ... ]` as an array literal"
    start = match.end() - 1
    blanked = _strip_comments(source, blank_strings=True)
    depth = 0
    for index in range(start, len(blanked)):
        if blanked[index] in "[{":
            depth += 1
        elif blanked[index] in "]}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError("ChatSites.js: unterminated `sites` array literal")


def _chat_site_ids():
    literal = _sites_literal(_read_code(CHAT_SITES_JS))
    # Only top-level site objects: the id key directly follows "{" or ",".
    return re.findall(r"""[{,]\s*["']?id["']?\s*:\s*["']([^"']+)["']""", literal)


def _site_objects(literal):
    """Return the source text of each top-level ``{ ... }`` in the sites array."""
    blanked = _strip_comments(literal, blank_strings=True)
    objects = []
    depth = 0
    start = -1
    for index, char in enumerate(blanked):
        if char in "[{":
            depth += 1
            if char == "{" and depth == 2:
                start = index
        elif char in "]}":
            if char == "}" and depth == 2:
                objects.append(literal[start:index + 1])
            depth -= 1
    return objects


def _site_key(site, key):
    """The string literal value of a top-level ``key`` in one site object, or None."""
    match = re.search(rf"""[{{,]\s*["']?{key}["']?\s*:\s*["']([^"']*)["']""", site)
    return match.group(1) if match else None


def _chat_sites():
    literal = _sites_literal(_read_code(CHAT_SITES_JS))
    sites = {}
    for site in _site_objects(literal):
        site_id = _site_key(site, "id")
        assert site_id, f"{_rel(CHAT_SITES_JS)}: every site object needs a literal id"
        sites[site_id] = site
    return sites


def _key_hits(site, key, allowed):
    """Snippets where ``key`` is set to anything other than the ``allowed`` literal."""
    return re.findall(rf"""[{{,]\s*["']?{key}["']?\s*:(?!\s*{allowed}\b)\s*[^,\n}}]*""", site)


def _main_xml_entries():
    assert MAIN_XML.is_file(), f"{_rel(MAIN_XML)} is missing"
    root = ET.parse(MAIN_XML).getroot()
    entries = {}
    for group in root.iter(f"{KCFG_NS}group"):
        for entry in group.iter(f"{KCFG_NS}entry"):
            default = entry.find(f"{KCFG_NS}default")
            entries[entry.get("name")] = {
                "group": group.get("name"),
                "type": entry.get("type"),
                "default": None if default is None else default.text,
            }
    return entries


# --- the comment stripper itself -------------------------------------------


def test_strip_comments_removes_comments_but_keeps_code_and_strings():
    source = (
        "// storageName: \"x\"\n"
        "/* runJavaScript(\"a\")\n console.log(1) */\n"
        "property string u: \"https://claude.ai/new\" // trailing console.log\n"
        "var r = /\\s*QtWebEngine\\/\\S+/g; var q = /[/]\"/;\n"
        "view.runJavaScript(\"1\")\n"
        "storageName: \"real\"\n"
    )
    stripped = _strip_comments(source)
    assert len(stripped) == len(source)
    assert stripped.count("\n") == source.count("\n")
    assert "\"https://claude.ai/new\"" in stripped
    assert "console" not in stripped
    assert _hits(r"\brunJavaScript\b", stripped) == [6]
    assert _hits(r"\bstorageName\b", stripped) == [7]


# --- imports ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("module_pattern", "module"),
    [(r"QtWebEngine", "QtWebEngine"), (r"QtQuick\.Dialogs", "QtQuick.Dialogs")],
)
def test_webengine_and_dialogs_are_imported_only_by_chat_web_view(module_pattern, module):
    pattern = rf"\bimport\s+{module_pattern}\b"
    offenders = [
        f"{_rel(path)}:{line}"
        for path in _code_files() if path != CHAT_WEB_VIEW
        # configUsage.qml's color boxes: only a ColorDialog (_color_dialog_problems).
        and not _dialogs_exempt(module, path)
        for line in _hits(pattern, _read_code(path))
    ]
    assert not offenders, f"{module} may only be imported by ChatWebView.qml; found in {offenders}"
    assert _hits(pattern, _read_code(CHAT_WEB_VIEW)), f"{_rel(CHAT_WEB_VIEW)} must import {module}"


def _dialogs_exempt(module, path):
    """Only the real configUsage.qml (full path, not any file of that name)."""
    return module == "QtQuick.Dialogs" and path == CONFIG_USAGE


@pytest.mark.parametrize("path", [
    UI / "sub" / "configUsage.qml",
    CONTENTS / "configUsage.qml",
    UI / "configChat.qml",
], ids=lambda path: _rel(path))
def test_proof_dialogs_exemption_is_the_one_path(path):
    assert not _dialogs_exempt("QtQuick.Dialogs", path)
    assert _dialogs_exempt("QtQuick.Dialogs", CONFIG_USAGE)
    assert not _dialogs_exempt("QtWebEngine", CONFIG_USAGE)


# AI Provider Settings' color boxes use Qt's ColorDialog, which only hands
# back a color: configUsage.qml imports QtQuick.Dialogs once, as QtDialogs,
# declares exactly one dialog, a ColorDialog, and no file, folder or message
# dialog; it saves only through setUsageColor, always opaque (opaqueColor).
# The dialog sets nothing else: no options (so no alpha), no other handler.
DIALOG_TYPES = r"\bQtDialogs\s*\.\s*(\w+)\s*\{"
COLOR_DIALOG_MEMBERS = ("id", "title", "selectedColor", "onAccepted")
COLOR_DIALOG_ACCEPTED = "page.setUsageColor(colorChoice.level, page.opaqueColor(selectedColor))"


def _color_dialog_problems(code):
    problems = []
    imports = _hits(r"(?m)^\s*import\s+QtQuick\.Dialogs\b.*$", code)
    if len(imports) != 1 or len(_hits(r"(?m)^\s*import\s+QtQuick\.Dialogs\s+as\s+QtDialogs\s*$", code)) != 1:
        problems.append("import QtQuick.Dialogs once, as QtDialogs")
    if _hits(r"\b(?:FileDialog|FolderDialog|MessageDialog|FontDialog)\b", code):
        problems.append("only a ColorDialog is allowed")
    dialogs = re.findall(DIALOG_TYPES, code)
    if dialogs != ["ColorDialog"]:
        problems.append(f"exactly one QtDialogs.ColorDialog, found {dialogs}")
    for start, body in _blocks(code, r"\bQtDialogs\s*\.\s*ColorDialog\s*\{"):
        accepted = re.findall(r"(?m)^\s*onAccepted\s*:\s*(.+)$", body)
        if accepted != [COLOR_DIALOG_ACCEPTED]:
            problems.append(f"line {_line_of(code, start)}: the ColorDialog only calls page.setUsageColor")
        top = _top_level_raw(body)
        members = re.findall(r"(?m)^\s*([A-Za-z_][\w.]*)\s*:", top)
        # Anything at the top level that is not "name: value" (a child, a
        # function, a property declaration) is a member too.
        others = [line.strip() for line in top.splitlines()
                  if line.strip() and not re.match(r"\s*[A-Za-z_][\w.]*\s*:", line)]
        if sorted(members) != sorted(COLOR_DIALOG_MEMBERS) or others:
            problems.append(f"line {_line_of(code, start)}: the ColorDialog may only set "
                            f"{', '.join(COLOR_DIALOG_MEMBERS)}; found {members + others}")
    if not re.search(r"\bfunction\s+opaqueColor\s*\(\s*color\s*\)\s*\{\s*return\s+String\s*\(\s*"
                     r"Qt\s*\.\s*rgba\s*\(\s*color\.r\s*,\s*color\.g\s*,\s*color\.b\s*,\s*1\s*\)\s*\)\s*\}",
                     code):
        problems.append("opaqueColor(color) must return String(Qt.rgba(color.r, color.g, color.b, 1))")
    return problems


def test_settings_color_dialog_is_only_a_color_dialog():
    problems = _color_dialog_problems(_read_code(CONFIG_USAGE))
    assert not problems, f"{_rel(CONFIG_USAGE)}: {problems}"


@pytest.mark.parametrize(("old", "new"), [
    ("import QtQuick.Dialogs as QtDialogs\n", "import QtQuick.Dialogs as QtDialogs\nimport QtQuick.Dialogs\n"),
    ("        QtDialogs.ColorDialog {\n", "        QtDialogs.FileDialog {\n"),
    ("        QtDialogs.ColorDialog {\n", "        QtDialogs.FolderDialog {}\n        QtDialogs.ColorDialog {\n"),
    (f"            onAccepted: {COLOR_DIALOG_ACCEPTED}\n",
     "            onAccepted: page.cfg_usageNormalColor = String(selectedColor)\n"),
    (f"            onAccepted: {COLOR_DIALOG_ACCEPTED}\n",
     f"            onAccepted: {{ {COLOR_DIALOG_ACCEPTED}; Qt.openUrlExternally(\"x\") }}\n"),
    # The color as the dialog gave it (translucent: saved as "").
    (f"            onAccepted: {COLOR_DIALOG_ACCEPTED}\n",
     "            onAccepted: page.setUsageColor(colorChoice.level, String(selectedColor))\n"),
    # Other members of the dialog.
    (f"            onAccepted: {COLOR_DIALOG_ACCEPTED}\n",
     f"            onAccepted: {COLOR_DIALOG_ACCEPTED}\n            onRejected: page.cfg_usageNormalColor = \"\"\n"),
    (f"            onAccepted: {COLOR_DIALOG_ACCEPTED}\n",
     f"            onAccepted: {COLOR_DIALOG_ACCEPTED}\n            options: QtDialogs.ColorDialog.ShowAlphaChannel\n"),
    (f"            onAccepted: {COLOR_DIALOG_ACCEPTED}\n",
     f"            onAccepted: {COLOR_DIALOG_ACCEPTED}\n            onSelectedColorChanged: Qt.openUrlExternally(\"x\")\n"),
    (f"            onAccepted: {COLOR_DIALOG_ACCEPTED}\n",
     f"            onAccepted: {COLOR_DIALOG_ACCEPTED}\n            Component.onCompleted: open()\n"),
    (f"            onAccepted: {COLOR_DIALOG_ACCEPTED}\n",
     f"            onAccepted: {COLOR_DIALOG_ACCEPTED}\n            function f() {{ return 1 }}\n"),
    (f"            onAccepted: {COLOR_DIALOG_ACCEPTED}\n",
     f"            onAccepted: {COLOR_DIALOG_ACCEPTED}\n            property string x: \"\"\n"),
    ("            title: i18n(\"Choose a color\")\n",
     "            title: i18n(\"Choose a color\")\n            title: \"x\"\n"),
    ("            selectedColor: colorChoice.shown\n", ""),
    # The helper must keep the color opaque.
    ("        return String(Qt.rgba(color.r, color.g, color.b, 1))\n",
     "        return String(Qt.rgba(color.r, color.g, color.b, color.a))\n"),
    ("        return String(Qt.rgba(color.r, color.g, color.b, 1))\n", "        return String(color)\n"),
    ("    function setThresholds(warn, critical) {\n",
     "    function f() { return QtDialogs.MessageDialog }\n    function setThresholds(warn, critical) {\n"),
])
def test_proof_color_dialog_rule_catches(old, new):
    assert _color_dialog_problems(_mutated(CONFIG_USAGE, old, new))


# No QML is built from strings or loaded by URL at runtime: no
# Qt.createQmlObject or Qt.createComponent anywhere in the plasmoid. Loading a
# file stays in the places that do it today: ChatView.qml's one
# webLoader.setSource(chatView.webSource, ...) (and its Loader, with no source
# binding) and OllamaChatView.qml's block Loader, which only picks one of its
# own Components (sourceComponent).
DYNAMIC_LOADERS = {"ChatView.qml": 1, "OllamaChatView.qml": 1}


def _dynamic_creation_offenders(sources):
    offenders = []
    for name, code in sources.items():
        base = Path(name).name
        for line in _hits(r"\b(?:createQmlObject|createComponent)\b", code):
            offenders.append(f"{name}:{line}: Qt.createQmlObject/createComponent")
        set_sources = _hits(r"\bsetSource\s*\(", code)
        allowed = _hits(r"\bwebLoader\s*\.\s*setSource\s*\(\s*chatView\s*\.\s*webSource\s*,", code)
        if base == "ChatView.qml":
            if len(set_sources) > 1 or set_sources != allowed:
                offenders.append(f"{name}:{set_sources}: only webLoader.setSource(chatView.webSource, ...)")
        elif set_sources:
            offenders.append(f"{name}:{set_sources}: setSource()")
        loaders = list(_blocks(code, r"(?<![\w.])Loader\s*\{"))
        if len(loaders) > DYNAMIC_LOADERS.get(base, 0):
            offenders.append(f"{name}: {len(loaders)} Loader(s)")
        for start, body in loaders:
            top = _top_level_raw(body)
            if re.search(r"(?m)^\s*source\s*:", top):
                offenders.append(f"{name}:{_line_of(code, start)}: Loader with a source")
            if base == "OllamaChatView.qml" and not re.search(r"(?m)^\s*sourceComponent\s*:", top):
                offenders.append(f"{name}:{_line_of(code, start)}: the block Loader picks a sourceComponent")
            if base == "ChatView.qml" and not re.search(r"(?m)^\s*id\s*:\s*webLoader\s*$", top):
                offenders.append(f"{name}:{_line_of(code, start)}: the one Loader is webLoader")
        for line in _hits(r"\.\s*source\s*=(?!=)", code):
            offenders.append(f"{name}:{line}: assigns a source")
    return offenders


def test_no_qml_is_created_at_runtime_outside_the_known_loaders():
    offenders = _dynamic_creation_offenders(_all_code())
    assert not offenders, f"runtime QML creation outside the known Loaders: {offenders}"


@pytest.mark.parametrize(("target", "snippet"), [
    (FULL_REPRESENTATION, "    function f() { return Qt.createQmlObject(\"import QtQuick; Item {}\", full) }\n"),
    (MAIN_QML, "    function f() { return Qt.createComponent(\"ChatView.qml\") }\n"),
    (MAIN_QML, "    function f() { return Qt . createComponent (\"x.qml\") }\n"),
    (CHAT_SITES_JS, "    var c = Qt.createComponent(\"x.qml\")\n"),
    (UI / "configGeneral.qml", "    property var f: Qt[\"createQmlObject\"]\n"),
    (FULL_REPRESENTATION, "    Loader { source: \"ChatWebView.qml\" }\n"),
    (FULL_REPRESENTATION, "    Loader { id: l }\n    function f() { l.setSource(\"x.qml\", {}) }\n"),
    (FULL_REPRESENTATION, "    Loader { id: l }\n    function f() { l.source = \"x.qml\" }\n"),
    (CHAT_VIEW, "    function f() { webLoader.setSource(\"x.qml\", {}) }\n"),
    (CHAT_VIEW, "    function f() { webLoader.setSource(chatView.webSource, {}) }\n"),
    (CHAT_VIEW, "    function f() { webLoader.source = \"x.qml\" }\n"),
    (CHAT_VIEW, "    Loader { sourceComponent: null }\n"),
    (OLLAMA_CHAT_VIEW, "    function f() { blockLoader.setSource(\"x.qml\") }\n"),
    (OLLAMA_CHAT_VIEW, "    Loader { sourceComponent: null }\n"),
])
def test_proof_dynamic_creation_rule_catches(target, snippet):
    sources = _all_code()
    sources[_rel(target)] = _appended(target, snippet)
    assert _dynamic_creation_offenders(sources)


@pytest.mark.parametrize(("path", "old", "new"), [
    (CHAT_VIEW, "            id: webLoader\n", "            id: webLoader\n            source: chatView.webSource\n"),
    (CHAT_VIEW, "            id: webLoader\n", "            id: otherLoader\n"),
    (OLLAMA_CHAT_VIEW, "                                    sourceComponent: segment.code ? codeBlock\n",
     "                                    source: \"Reply.qml\"\n"
     "                                    property var x: segment.code ? codeBlock\n"),
    # Only the sourceComponent line goes: the block Loader must still pick one.
    (OLLAMA_CHAT_VIEW, "sourceComponent: segment.code ? codeBlock\n", "property var x: segment.code ? codeBlock\n"),
])
def test_proof_dynamic_creation_rule_catches_loader_changes(path, old, new):
    sources = _all_code()
    sources[_rel(path)] = _mutated(path, old, new)
    assert _dynamic_creation_offenders(sources)


def test_chat_sites_js_has_no_imports():
    code = _read_code(CHAT_SITES_JS)
    lines = _hits(r"(?m)^\s*(?:\.import\b|import\b)", code) + _hits(r"\bQt\.include\s*\(", code)
    assert not lines, f"{_rel(CHAT_SITES_JS)} must stay a pure library without imports; lines {lines}"


# --- the one profile: private by default, saved sign-ins only behind the gate ---------
#
# Rule checkers take source text so the "proof" tests below can feed them a
# violating copy of the real file and show that each rule really fails.

# Bindings of the profile, exactly, in this order (spike result 7: the paths
# before storageName and offTheRecord last, else Qt creates a stray folder
# under plasmashell's own data directory).
PROFILE_BINDINGS = (
    ("persistentStoragePath", r'chatWeb\.staySignedIn\s*\?\s*chatWeb\.storagePath\s*:\s*""'),
    ("cachePath", r'chatWeb\.staySignedIn\s*\?\s*chatWeb\.storagePath\s*:\s*""'),
    ("storageName", r'chatWeb\.staySignedIn\s*\?\s*chatWeb\.profileName\s*:\s*""'),
    ("httpCacheType", r"WebEngineProfile\.MemoryHttpCache"),
    ("persistentCookiesPolicy",
     r"chatWeb\.staySignedIn\s*\?\s*WebEngineProfile\.AllowPersistentCookies"
     r"\s*:\s*WebEngineProfile\.NoPersistentCookies"),
    ("persistentPermissionsPolicy", r"WebEngineProfile\.PersistentPermissionsPolicy\.AskEveryTime"),
    ("spellCheckEnabled", r"false"),
    ("offTheRecord", r"!\s*chatWeb\.staySignedIn"),
)
# Names that may appear only once each, inside the profile block.
PROFILE_ONLY_NAMES = ("storageName", "persistentStoragePath", "cachePath", "offTheRecord",
                      "AllowPersistentCookies")

FORBIDDEN_STORAGE = {
    "offTheRecord: false": r"\boffTheRecord\s*:\s*false\b",
    "defaultProfile": r"\bdefaultProfile\b",
    "ForcePersistentCookies": r"\bForcePersistentCookies\b",
    "DiskHttpCache": r"\bDiskHttpCache\b",
    "WebEngineProfilePrototype": r"\bWebEngineProfilePrototype\b",
    # A live switch of a profile crashes Qt WebEngine (spike result 6).
    "live profile assignment": r"\.\s*(?:offTheRecord|storageName|persistentStoragePath|cachePath"
                               r"|persistentCookiesPolicy|httpCacheType)\s*=(?!=)",
}


def _profile_problems(code):
    profiles = list(_blocks(code, r"\bWebEngineProfile\s*\{"))
    if len(profiles) != 1:
        return [f"exactly one WebEngineProfile expected, found {len(profiles)}"]
    _, body = profiles[0]
    inner = _strip_comments(body[1:-1], blank_strings=True)
    # Top-level property bindings only (depth 0 inside the block), handlers skipped.
    names = []
    depth = 0
    for line_start in [0] + [m.end() for m in re.finditer(r"\n", inner)]:
        line = inner[line_start:inner.find("\n", line_start) if "\n" in inner[line_start:] else len(inner)]
        if depth == 0:
            match = re.match(r"\s*(\w+)\s*:", line)
            if match and not match.group(1).startswith("on") and match.group(1) != "id":
                names.append(match.group(1))
        depth += line.count("{") - line.count("}")
    problems = []
    expected = [name for name, _ in PROFILE_BINDINGS]
    if names != expected:
        problems.append(f"profile bindings must be exactly {expected} in that order, got {names}")
    for name, value in PROFILE_BINDINGS:
        found = re.findall(rf"(?m)^\s*{name}\s*:\s*((?:[^\n]|\n\s*[?:])+)", body)
        if len(found) != 1 or not re.fullmatch(rf"\s*{value}\s*", found[0]):
            problems.append(f"{name} must be exactly `{value}`, got {found}")
    for name in PROFILE_ONLY_NAMES:
        total = len(_hits(rf"\b{name}\b", code))
        inside = len(_hits(rf"\b{name}\b", body))
        if total != inside or inside != 1:
            problems.append(f"{name} must appear once, inside the profile block ({inside} inside, {total} total)")
    return problems


def test_chat_web_view_declares_one_profile_in_the_safe_order():
    problems = _profile_problems(_read_code(CHAT_WEB_VIEW))
    assert not problems, f"{_rel(CHAT_WEB_VIEW)}: {problems}"


def _storage_offenders(sources):
    return [
        f"{name}:{line} {rule}"
        for name, code in sources.items()
        for rule, pattern in FORBIDDEN_STORAGE.items()
        for line in _hits(pattern, code)
    ] + [
        f"{name}:{line} {word}"
        for name, code in sources.items() if not name.endswith("ChatWebView.qml")
        for word in PROFILE_ONLY_NAMES
        for line in _hits(rf"\b{word}\b", code)
    ]


def _all_code():
    return {_rel(path): _read_code(path) for path in _code_files()}


def test_no_plasmoid_file_uses_forbidden_webengine_storage():
    offenders = _storage_offenders(_all_code())
    assert not offenders, f"forbidden or out-of-place WebEngine storage: {offenders}"


def _web_view_inputs_problems(code):
    problems = []
    for name, kind, default in (("staySignedIn", "bool", "false"),
                                ("storagePath", "string", '""'),
                                ("profileName", "string", '""')):
        declared = re.findall(rf"(?m)^\s*property\s+(\w+)\s+{name}\s*:\s*(.+?)\s*$", code)
        if declared != [(kind, default)]:
            problems.append(f"`property {kind} {name}: {default}` expected once, got {declared}")
        assigned = _hits(rf"(?<![\w.]){name}\s*=(?!=)|\.\s*{name}\s*=(?!=)", code)
        if assigned:
            problems.append(f"{name} must never be assigned inside ChatWebView (lines {assigned})")
    return problems


def test_chat_web_view_profile_inputs_default_to_private():
    problems = _web_view_inputs_problems(_read_code(CHAT_WEB_VIEW))
    assert not problems, f"{_rel(CHAT_WEB_VIEW)}: {problems}"


# ChatView is the only place that hands the profile inputs to ChatWebView,
# and only through the Loader's initial properties.
CHAT_VIEW_GATE = (
    r'readonly\s+property\s+bool\s+encrypted\s*:\s*'
    r'ChatStorage\.normalizeMode\(\s*chatView\.storageMode\s*\)\s*===\s*"encrypted"',
    r'readonly\s+property\s+bool\s+persistentReady\s*:\s*chatView\.encrypted\s*&&\s*'
    r'chatView\.storageReady\s*&&\s*chatView\.storagePath\s*!==\s*""\s*&&\s*'
    r'chatView\.profileName\s*!==\s*""',
    r"staySignedIn\s*:\s*chatView\.persistentReady\s*,",
    r'storagePath\s*:\s*chatView\.persistentReady\s*\?\s*chatView\.storagePath\s*:\s*""',
    r'profileName\s*:\s*chatView\.persistentReady\s*\?\s*chatView\.profileName\s*:\s*""',
    r'property\s+url\s+webSource\s*:\s*Qt\.resolvedUrl\(\s*"ChatWebView\.qml"\s*\)',
)


def _chat_view_gate_problems(code):
    problems = [f"missing `{pattern}`" for pattern in CHAT_VIEW_GATE if len(re.findall(pattern, code)) != 1]
    if len(_hits(r"\bstaySignedIn\s*:", code)) != 1:
        problems.append("staySignedIn may be set exactly once (in setSource)")
    if len(_hits(r"\bwebLoader\.setSource\s*\(\s*chatView\.webSource\s*,", code)) != 1 \
            or len(_hits(r"\bsetSource\s*\(", code)) != 1:
        problems.append("the web view must be created by exactly one webLoader.setSource(chatView.webSource, ...)")
    loaders = [body for _, body in _blocks(code, r"\bLoader\s*\{")]
    if len(loaders) != 1 or not re.search(r"\bactive\s*:\s*false\b", loaders[0]) \
            or re.search(r"\b(?:source|sourceComponent)\s*:", loaders[0]):
        problems.append("the one Loader must start `active: false` with no source binding")
    return problems


def test_persistent_profile_only_behind_the_verified_gate():
    problems = _chat_view_gate_problems(_read_code(CHAT_VIEW))
    assert not problems, f"{_rel(CHAT_VIEW)}: {problems}"


def _stay_signed_in_elsewhere(sources):
    return [
        f"{name}:{line}"
        for name, code in sources.items()
        if not name.endswith(("ChatView.qml", "ChatWebView.qml"))
        for line in _hits(r"\bstaySignedIn\s*[:=](?!=)", code)
    ]


def test_stay_signed_in_is_set_only_by_chat_view():
    offenders = _stay_signed_in_elsewhere(_all_code())
    assert not offenders, f"staySignedIn may only be set by ChatView.qml: {offenders}"


# main.qml: ready only when the helper reported the folder unlocked and said
# ok to prepare for this exact generation.
MAIN_READY = (
    r'readonly\s+property\s+bool\s+chatStorageReady\s*:\s*root\.chatStorageMode\s*===\s*"encrypted"\s*'
    r'&&\s*root\.chatVaultState\s*===\s*"unlocked"\s*&&\s*!root\.chatVaultHold\s*'
    r'&&\s*root\.chatPreparedGeneration\s*===\s*root\.chatGeneration\s*'
    r'&&\s*root\.chatProfilePath\s*!==\s*""\s*&&\s*root\.chatProfileName\s*!==\s*""'
)


def _main_ready_problems(code, full_representation):
    problems = []
    if len(re.findall(MAIN_READY, code)) != 1:
        problems.append("chatStorageReady must keep the exact verified-unlocked gate")
    if not re.search(
            r'readonly\s+property\s+string\s+chatStorageMode\s*:\s*'
            r'ChatStorage\.normalizeMode\(\s*Plasmoid\.configuration\.chatSignInStorage\s*\)', code):
        problems.append("chatStorageMode must be ChatStorage.normalizeMode(chatSignInStorage)")
    granted = [match for match in re.finditer(r"\bchatPreparedGeneration\s*=(?!=)(?!\s*-1\b)", code)]
    if len(granted) != 1:
        problems.append(f"chatPreparedGeneration may be set to a generation exactly once, got {len(granted)}")
    else:
        before = code[max(0, granted[0].start() - 400):granted[0].start()]
        if 'case "prepare"' not in before or not re.search(r"if\s*\(\s*reply\.ok\s*&&", before):
            problems.append("chatPreparedGeneration may only be granted in the prepare reply after reply.ok")
    if len(_hits(r"(?m)\bstorageReady\s*:\s*root\.chatStorageReady\s*$", full_representation)) != 1:
        problems.append("FullRepresentation must pass storageReady: root.chatStorageReady")
    if _hits(r"\bstorageReady\s*:", full_representation) != _hits(r"\bstorageReady\s*:\s*root\.chatStorageReady\b",
                                                                   full_representation):
        problems.append("storageReady may only be bound to root.chatStorageReady")
    return problems


def test_main_grants_saved_sign_ins_only_after_a_verified_prepare():
    problems = _main_ready_problems(_read_code(MAIN_QML), _read_code(FULL_REPRESENTATION))
    assert not problems, f"{_rel(MAIN_QML)}: {problems}"


def test_every_web_view_uses_the_chat_profile():
    code = _read_code(CHAT_WEB_VIEW)
    views = _hits(r"\bWebEngineView\s*\{", code)
    bindings = re.findall(r"\bprofile\s*:\s*([\w.]+)", code)
    wrong = [value for value in bindings if value != "chatProfile"]
    assert views, f"{_rel(CHAT_WEB_VIEW)} declares no WebEngineView"
    assert not wrong, f"{_rel(CHAT_WEB_VIEW)}: every `profile:` must be chatProfile, got {wrong}"
    assert len(bindings) >= len(views), (
        f"{_rel(CHAT_WEB_VIEW)}: {len(views)} WebEngineView declarations (lines {views}) "
        f"but only {len(bindings)} `profile: chatProfile` bindings"
    )


def test_chat_starts_only_in_the_open_popup():
    # A web view built while Plasma preloads the closed popup stays blank, and
    # no web engine should start before Chat is actually shown.
    # With the Ollama view, the web chat must also stay off while Ollama is shown.
    problems = _chat_view_current_problems(_read_code(FULL_REPRESENTATION), OLLAMA_CHAT_VIEW.is_file())
    assert not problems, f"{_rel(FULL_REPRESENTATION)}: {problems}"


CHAT_VIEW_CURRENT = r"(?m)^\s*current\s*:\s*full\.onChat\s*&&\s*root\.expanded\s*$"
CHAT_VIEW_CURRENT_OLLAMA = (
    r'(?m)^\s*current\s*:\s*full\.onChat\s*&&\s*root\.expanded\s*&&\s*root\.chatSiteId\s*!==\s*"ollama"\s*$'
)


def _chat_view_current_problems(code, with_ollama):
    plain = len(_hits(CHAT_VIEW_CURRENT, code))
    gated = len(_hits(CHAT_VIEW_CURRENT_OLLAMA, code))
    if with_ollama and (gated != 1 or plain):
        return ['ChatView must get `current: full.onChat && root.expanded && root.chatSiteId !== "ollama"`']
    if not with_ollama and plain + gated != 1:
        return ["ChatView must get `current: full.onChat && root.expanded`"]
    return []


@pytest.mark.parametrize(("with_ollama", "old", "new"), [
    (False, "current: full.onChat && root.expanded", "current: full.onChat"),
    (True, 'current: full.onChat && root.expanded && root.chatSiteId !== "ollama"',
     "current: full.onChat && root.expanded"),
    (True, 'current: full.onChat && root.expanded && root.chatSiteId !== "ollama"',
     'current: full.onChat && root.expanded && root.chatSiteId === "ollama"'),
])
def test_proof_chat_view_current_rule_catches(with_ollama, old, new):
    assert _chat_view_current_problems(_mutated(FULL_REPRESENTATION, old, new), with_ollama)


# --- helper commands: built only in ChatStorage.js -------------------------------------

HELPER_FLAGS = ("--vault", "--web-data", "--store", "--applet", "--generation", "--keep")


# --applet also names the widget in history and backup commands: there it
# may appear only inside the one builder of UsageHistory.js or SettingsBackup.js.
APPLET_FLAG_BUILDERS = {"UsageHistory.js": "historyCommand", "SettingsBackup.js": "backupCommand"}


def _helper_flag_offenders(sources):
    offenders = []
    for name, code in sources.items():
        if name.endswith("ChatStorage.js"):
            continue
        builder = APPLET_FLAG_BUILDERS.get(name.rsplit("/", 1)[-1])
        spans = _block_spans(code, rf"\bfunction\s+{builder}\s*\([^)]*\)\s*\{{") if builder else []
        for flag in HELPER_FLAGS:
            for match in re.finditer(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", code):
                if flag == "--applet" and len(spans) == 1 and spans[0][0] <= match.start() < spans[0][1]:
                    continue
                offenders.append(f"{name}:{_line_of(code, match.start())} {flag}")
    return offenders


def test_helper_flags_appear_only_in_chat_storage_js():
    offenders = _helper_flag_offenders(_all_code())
    assert not offenders, f"helper commands must be built by ChatStorage.js only: {offenders}"


def _chat_storage_problems(raw):
    code = _strip_comments(raw)
    problems = []
    if not re.match(r"\s*\.pragma\s+library\b", code):
        problems.append("must start with .pragma library")
    if _hits(r"(?m)^\s*(?:\.import\b|import\b)", code) + _hits(r"\bQt\.include\s*\(", code):
        problems.append("must not import anything")
    # The only store is the encrypted one; no plaintext profile folder exists.
    if _hits(r"""["']folder["']""", code):
        problems.append('must not name the old "folder" store')
    if re.findall(r"--store\s+(\w+)", code) != ["encrypted"]:
        problems.append("--store must be the literal `--store encrypted`, once")
    ops = re.search(r"VAULT_OPERATIONS\s*=\s*\[([^\]]*)\]", code)
    allowed = ('"status", "create", "unlock", "lock", "change-passphrase", "destroy", '
               '"add-key", "remove-key", "auto-unlock"')
    if not ops or re.sub(r"\s+", " ", ops.group(1)).strip() != allowed:
        problems.append(f"VAULT_OPERATIONS must be exactly [{allowed}]")
    # Every argv value is validated: no raw concatenation of op or numbers
    # other than through the checked branches.
    if _hits(r"\beval\s*\(|\bFunction\s*\(", code):
        problems.append("no eval")
    return problems


def test_chat_storage_js_is_a_pure_strict_command_builder():
    problems = _chat_storage_problems(CHAT_STORAGE_JS.read_text(encoding="utf-8"))
    assert not problems, f"{_rel(CHAT_STORAGE_JS)}: {problems}"


def _web_data_store_offenders(sources):
    return [
        f"{name}:{_line_of(code, match.start())}"
        for name, code in sources.items()
        for match in re.finditer(r"(?<!function )\bwebDataCommand\s*\(\s*([^,]*),\s*([^,]*),", code)
        if match.group(2).strip() != '"encrypted"'
    ]


def test_web_data_commands_always_use_the_encrypted_store():
    offenders = _web_data_store_offenders(_all_code())
    assert not offenders, f'webDataCommand must be called with the literal store "encrypted": {offenders}'


def _helper_stderr_offenders(sources):
    offenders = []
    for name, code in sources.items():
        for start, body in _blocks(code, r"\bPlasma5Support\.DataSource\s*\{"):
            if re.search(r"\bid\s*:\s*(?:storageSource|vaultSource)\b", body) and re.search(r"stderr", body):
                offenders.append(f"{name}:{_line_of(code, start)}")
    return offenders


def test_storage_helper_replies_never_read_stderr():
    offenders = _helper_stderr_offenders(_all_code())
    assert not offenders, f"storage helper DataSources must only read stdout's known words: {offenders}"


# --- secrets and dangerous gocryptfs options never appear in plasmoid/ ------------------

# Anywhere, strings included: the plasmoid never handles key material or
# gives gocryptfs options; purge exists only for install.sh.
FORBIDDEN_WORDS = {
    "purge": r"(?i)purge",
    "extpass": r"(?i)extpass",
    "passfile": r"(?i)passfile",
    "masterkey": r"(?i)masterkey",
    "allow_other": r"(?i)allow_other",
    "allow_root": r"(?i)allow_root",
    "plaintextnames": r"(?i)plaintextnames",
    "echoMode": r"\bechoMode\b",
    "PasswordField": r"\bPasswordField\b",
    "TextInput.Password": r"\bTextInput\s*\.\s*Password\b",
}


def _all_text():
    return {
        _rel(path): (_read_code(path) if path.suffix in {".qml", ".js"} else path.read_text(encoding="utf-8"))
        for path in sorted(PLASMOID.rglob("*")) if path.is_file() and path.suffix in {".qml", ".js", ".json", ".xml", ".desktop"}
    }


def _forbidden_word_offenders(sources):
    return [
        f"{name}:{line} {word}"
        for name, code in sources.items()
        for word, pattern in FORBIDDEN_WORDS.items()
        for line in _hits(pattern, code)
    ]


def test_plasmoid_never_names_key_material_or_unsafe_options():
    offenders = _forbidden_word_offenders(_all_text())
    assert not offenders, f"forbidden in plasmoid/: {offenders}"


def _secret_identifier_offenders(sources):
    # Code with strings blanked: a passphrase never has a property, variable
    # or field. (User-facing text like "Change passphrase…" is a string.)
    return [
        f"{name}:{line}"
        for name, code in sources.items() if name.endswith((".qml", ".js"))
        for line in _hits(r"(?i)pass(?:phrase|word)", _strip_comments(code, blank_strings=True))
    ]


def test_no_code_identifier_holds_a_passphrase():
    offenders = _secret_identifier_offenders(_all_text())
    assert not offenders, f"no identifier may name a passphrase or password: {offenders}"


def _shown_path_offenders(sources):
    return [
        f"{name}:{line}"
        for name, code in sources.items() if name.endswith(".qml")
        for line in _hits(r"\b(?:text|placeholderText|ToolTip\.text)\s*:[^\n]*\b(?:storagePath|chatProfilePath|"
                          r"profileName|chatProfileName|StandardPaths)\b", code)
    ]


def test_profile_path_is_never_shown():
    offenders = _shown_path_offenders(_all_code())
    assert not offenders, f"the profile path or name must never be shown: {offenders}"


# --- proof: every rule above fails on a violating copy of the real file ----------------


def _mutated(path, old, new):
    raw = path.read_text(encoding="utf-8")
    assert old in raw, f"proof fixture out of date: {old!r} not in {_rel(path)}"
    return _strip_comments(raw.replace(old, new, 1))


PROFILE_MUTATIONS = {
    "offTheRecord first": (
        "        persistentStoragePath: chatWeb.staySignedIn",
        "        offTheRecord: !chatWeb.staySignedIn\n        persistentStoragePath: chatWeb.staySignedIn",
    ),
    "storageName before paths": (
        "        persistentStoragePath: chatWeb.staySignedIn ? chatWeb.storagePath : \"\"\n",
        "        storageName: \"x\"\n        persistentStoragePath: chatWeb.staySignedIn ? chatWeb.storagePath : \"\"\n",
    ),
    "always persistent": ("offTheRecord: !chatWeb.staySignedIn", "offTheRecord: false"),
    "path without gate": ("cachePath: chatWeb.staySignedIn ? chatWeb.storagePath : \"\"",
                          "cachePath: chatWeb.storagePath"),
    "disk cache": ("WebEngineProfile.MemoryHttpCache", "WebEngineProfile.DiskHttpCache"),
    "forced cookies": ("WebEngineProfile.AllowPersistentCookies", "WebEngineProfile.ForcePersistentCookies"),
    "second profile": ("    WebEngineProfile {\n", "    WebEngineProfile { id: other }\n    WebEngineProfile {\n"),
}


@pytest.mark.parametrize("name", sorted(PROFILE_MUTATIONS))
def test_proof_profile_rule_catches(name):
    code = _mutated(CHAT_WEB_VIEW, *PROFILE_MUTATIONS[name])
    assert _profile_problems(code) or _storage_offenders({"ChatWebView.qml": code})


def test_proof_live_profile_switch_is_caught():
    code = _mutated(CHAT_WEB_VIEW, "    function goBack() {", "    function flip() { chatProfile.offTheRecord = false }\n    function goBack() {")
    assert _storage_offenders({"ChatWebView.qml": code})


def test_proof_profile_names_outside_chat_web_view_are_caught():
    code = _mutated(CHAT_VIEW, "    spacing: 0\n", "    spacing: 0\n    property string storageName: \"\"\n")
    assert _storage_offenders({"ChatView.qml": code})


@pytest.mark.parametrize("old,new", [
    ("    property bool staySignedIn: false", "    property bool staySignedIn: true"),
    ("    property string storagePath: \"\"", "    property string storagePath: \"/tmp/x\""),
    ("    function goBack() {", "    function goBack() {\n        chatWeb.staySignedIn = true"),
])
def test_proof_web_view_inputs_rule_catches(old, new):
    assert _web_view_inputs_problems(_mutated(CHAT_WEB_VIEW, old, new))


@pytest.mark.parametrize("old,new", [
    ("staySignedIn: chatView.persistentReady,", "staySignedIn: chatView.storageReady,"),
    ("chatView.encrypted && chatView.storageReady", "chatView.storageReady"),
    ("&& chatView.storagePath !== \"\" && chatView.profileName !== \"\"", ""),
    ("            active: false\n", "            active: chatView.started\n            source: \"ChatWebView.qml\"\n"),
    ("    function start() {", "    function hack() { webLoader.setSource(\"ChatWebView.qml\", {}) }\n    function start() {"),
])
def test_proof_chat_view_gate_rule_catches(old, new):
    assert _chat_view_gate_problems(_mutated(CHAT_VIEW, old, new))


def test_proof_stay_signed_in_elsewhere_is_caught():
    code = _mutated(FULL_REPRESENTATION, "            storageReady: root.chatStorageReady",
                    "            storageReady: root.chatStorageReady\n            Component.onCompleted: web.staySignedIn = true")
    assert _stay_signed_in_elsewhere({"FullRepresentation.qml": code})


@pytest.mark.parametrize("old,new", [
    ("&& root.chatVaultState === \"unlocked\"\n", "\n"),
    ("                root.chatPreparedGeneration = root.chatGeneration\n",
     "                root.chatPreparedGeneration = root.chatGeneration\n"
     "            root.chatPreparedGeneration = root.chatGeneration\n"),
    ("if (reply.ok && root.chatOpGeneration", "if (root.chatOpGeneration"),
])
def test_proof_main_ready_rule_catches(old, new):
    assert _main_ready_problems(_mutated(MAIN_QML, old, new), _read_code(FULL_REPRESENTATION))


def test_proof_full_representation_ready_binding_is_caught():
    code = _mutated(FULL_REPRESENTATION, "storageReady: root.chatStorageReady", "storageReady: true")
    assert _main_ready_problems(_read_code(MAIN_QML), code)


def test_proof_helper_flag_outside_chat_storage_is_caught():
    code = _mutated(MAIN_QML, "    function chatNext() {",
                    "    function x() { return \"python3 -P -m hearthwire --vault status\" }\n    function chatNext() {")
    assert _helper_flag_offenders({"main.qml": code})


@pytest.mark.parametrize(("path", "old", "new"), [
    (MAIN_QML, "    function chatNext() {", '    function x() { return " --applet " + Plasmoid.id }\n    function chatNext() {'),
    (UI / "UsageHistory.js", "function validApplet(value) {",
     'function appletArg(applet) { return " --applet " + applet }\nfunction validApplet(value) {'),
    (UI / "UsageHistory.js", "function validApplet(value) {",
     'function historyCommand(op) { return " --applet " + op }\nfunction validApplet(value) {'),
    (UI / "SettingsBackup.js", '" --applet " + applet', '" --applet " + applet + " --store encrypted"'),
    (UI / "SettingsBackup.js", '" --applet " + applet', '" --applet " + applet + " --keep 1"'),
    (UI / "configGeneral.qml", "    function backupStatusText() {\n",
     '    function g() { return "x --applet 1" }\n    function backupStatusText() {\n'),
])
def test_proof_applet_flag_outside_the_builders_is_caught(path, old, new):
    assert _helper_flag_offenders(_sources_with(path, old, new))


@pytest.mark.parametrize("old,new", [
    (".pragma library", ""),
    ("var MODES", "import QtQuick as Q\nvar MODES"),
    ("store !== \"encrypted\"", "store !== \"encrypted\" && store !== \"folder\""),
    ('"remove-key", "auto-unlock"]', '"remove-key", "auto-unlock", "purge"]'),
    ('"remove-key", "auto-unlock"]', '"remove-key"]'),
])
def test_proof_chat_storage_rule_catches(old, new):
    raw = CHAT_STORAGE_JS.read_text(encoding="utf-8")
    assert old in raw
    assert _chat_storage_problems(raw.replace(old, new, 1))


def test_proof_plaintext_store_call_is_caught():
    code = _mutated(MAIN_QML, 'ChatStorage.webDataCommand("prepare", "encrypted",',
                    'ChatStorage.webDataCommand("prepare", root.chatStorageMode,')
    assert _web_data_store_offenders({"main.qml": code})


def test_proof_stderr_in_storage_source_is_caught():
    code = _mutated(MAIN_QML, "            storageSource.disconnectSource(source)\n",
                    "            storageSource.disconnectSource(source)\n            var e = data[\"stderr\"]\n")
    assert _helper_stderr_offenders({"main.qml": code})


@pytest.mark.parametrize("snippet", [
    "var a = \"--web-data purge\"",
    "var a = \"-passfile\"",
    "var a = \"-masterkey=1\"",
    "var a = \"-allow_other\"",
    "var a = \"-plaintextnames\"",
    "var a = \"-extpass=kdialog\"",
    "echoMode: TextInput.Password",
    "Kirigami.PasswordField {}",
])
def test_proof_forbidden_word_is_caught(snippet):
    assert _forbidden_word_offenders({"x.qml": snippet})


@pytest.mark.parametrize("snippet", ["property string passphrase: \"\"", "var userPassword = 1"])
def test_proof_secret_identifier_is_caught(snippet):
    assert _secret_identifier_offenders({"x.qml": snippet})


def test_proof_shown_path_is_caught():
    assert _shown_path_offenders({"x.qml": "    text: chatView.storagePath\n"})


# --- handlers and settings ------------------------------------------------------


def _handler_bodies(code, signal):
    return list(_blocks(code, rf"\b{signal}\s*:\s*(?:function\s*\([^)]*\)\s*|\([^)]*\)\s*=>\s*|\w+\s*=>\s*)?\{{"))


def test_console_messages_are_swallowed_by_an_empty_handler():
    code = _read_code(CHAT_WEB_VIEW)
    views = _hits(r"\bWebEngineView\s*\{", code)
    handlers = _handler_bodies(code, "onJavaScriptConsoleMessage")
    assert handlers, f"{_rel(CHAT_WEB_VIEW)} must define an onJavaScriptConsoleMessage handler"
    assert len(handlers) >= len(views), (
        f"{_rel(CHAT_WEB_VIEW)}: {len(views)} WebEngineView declarations but only "
        f"{len(handlers)} onJavaScriptConsoleMessage handlers; page logs would reach the journal"
    )
    non_empty = [_line_of(code, start) for start, body in handlers if body[1:-1].strip()]
    assert not non_empty, (
        f"{_rel(CHAT_WEB_VIEW)}: onJavaScriptConsoleMessage handlers must be empty; lines {non_empty}"
    )


def test_permission_requests_are_always_denied():
    code = _read_code(CHAT_WEB_VIEW)
    handlers = _handler_bodies(code, "onPermissionRequested")
    assert handlers, f"{_rel(CHAT_WEB_VIEW)} must define an onPermissionRequested handler"
    without_deny = [_line_of(code, start) for start, body in handlers if not re.search(r"\.deny\s*\(", body)]
    assert not without_deny, (
        f"{_rel(CHAT_WEB_VIEW)}: onPermissionRequested must call permission.deny(); lines {without_deny}"
    )
    grants = _hits(r"\.grant\s*\(", code) + _hits(r"\bgrantFeaturePermission\s*\([^)]*\btrue\b", code)
    assert not grants, f"{_rel(CHAT_WEB_VIEW)} must never grant a site permission; lines {grants}"


@pytest.mark.parametrize(
    "setting",
    [
        "javascriptCanAccessClipboard",
        "javascriptCanPaste",
        "screenCaptureEnabled",
        "localContentCanAccessFileUrls",
        "allowRunningInsecureContent",
    ],
)
def test_privacy_sensitive_settings_are_disabled(setting):
    code = _read_code(CHAT_WEB_VIEW)
    assert _hits(rf"\b{setting}\s*:\s*false\b", code), f"{_rel(CHAT_WEB_VIEW)} must set {setting}: false"
    enabled = _hits(rf"\b{setting}\s*:(?!\s*false\b)", code)
    assert not enabled, f"{_rel(CHAT_WEB_VIEW)} must not set {setting} to anything but false; lines {enabled}"


# --- no page access, no env, no logging -------------------------------------------


FORBIDDEN_ANYWHERE = {
    "runJavaScript": r"\brunJavaScript\b",
    "userScripts": r"\buserScripts\b",
    "WebEngineScript": r"\bWebEngineScript\b",
    "webChannel": r"\bwebChannel\b",
    "QtWebChannel": r"\bQtWebChannel\b",
    "QTWEBENGINE": r"QTWEBENGINE",
}


@pytest.mark.parametrize("name", sorted(FORBIDDEN_ANYWHERE))
def test_plasmoid_never_reads_or_injects_into_pages(name):
    pattern = FORBIDDEN_ANYWHERE[name]
    offenders = [
        f"{_rel(path)}:{line}"
        for path in _code_files()
        for line in _hits(pattern, _read_code(path))
    ] + [
        f"{_rel(path)}:{line}"
        for path in _text_files()
        for line in _hits(pattern, path.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"{name} is forbidden anywhere in plasmoid/; found at {offenders}"


def _log_offenders(sources):
    return [
        f"{name}:{line}"
        for name, code in sources.items()
        for line in _hits(r"\bconsole\b", code) + _hits(r"(?<![\w.])print\s*\(", code)
    ]


def test_plasmoid_never_logs():
    offenders = _log_offenders(_all_code())
    assert not offenders, f"plasmoid code must not log (console.* or print()): {offenders}"


def test_proof_logging_is_caught():
    code = _mutated(MAIN_QML, "    function chatNext() {", "    function chatNext() {\n        console.warn(1)")
    assert _log_offenders({"main.qml": code})


# --- user agent: Firefox only on Google sign-in, never set inside a request ---------
#
# Setting the profile's user agent from inside a navigation request aborts Qt
# WebEngine (experiment 2026-11-01), so it is written only by applyUserAgent,
# which navigation handling may call only through Qt.callLater, plus the one
# initial assignment when the item is created.

USER_AGENT_WRITE = r"\b(?:httpUserAgent|clientHints\s*\.\s*\w+)\s*=(?!=)"


def _block_spans(code, opener):
    spans = []
    for start, body in _blocks(code, opener):
        offset = code.index(body, start)
        spans.append((offset, offset + len(body)))
    return spans


def _without_deferred(body):
    """``body`` with the contents of every ``Qt.callLater(function ...)`` blanked."""
    blanked = body
    for start, inner in _blocks(body, r"\bQt\.callLater\s*\(\s*function\s*\([^)]*\)\s*\{"):
        offset = body.index(inner, start)
        blanked = blanked[:offset] + " " * len(inner) + blanked[offset + len(inner):]
    return blanked


def _user_agent_problems(code):
    problems = []
    allowed = _block_spans(code, r"\bfunction\s+applyUserAgent\s*\([^)]*\)\s*\{")
    if len(allowed) != 1:
        return [f"exactly one applyUserAgent function expected, found {len(allowed)}"]
    # The one initial assignment, when the item is created.
    initial = [
        match.start(1) for match in re.finditer(
            r"(?m)^\s*chatProfile\.(httpUserAgent)\s*=\s*chatWeb\.baseUserAgent\s*$", code)
    ]
    for match in re.finditer(USER_AGENT_WRITE, code):
        inside = any(lo <= match.start() < hi for lo, hi in allowed)
        if not inside and match.start() not in initial:
            problems.append(f"user agent or client hints written outside applyUserAgent (line {_line_of(code, match.start())})")
    if len(initial) != 1:
        problems.append(f"exactly one initial `chatProfile.httpUserAgent = chatWeb.baseUserAgent` expected, found {len(initial)}")
    synchronous = [
        body for opener in (r"\bfunction\s+checkUserAgent\s*\([^)]*\)\s*\{",)
        for _, body in _blocks(code, opener)
    ] + [body for _, body in _handler_bodies(code, "onNavigationRequested")]
    if not synchronous:
        problems.append("navigation handling (onNavigationRequested / checkUserAgent) not found")
    for body in synchronous:
        rest = _without_deferred(body)
        if re.search(r"\bapplyUserAgent\s*\(|" + USER_AGENT_WRITE, rest):
            problems.append("navigation handling may switch the user agent only through Qt.callLater")
    return problems


def test_user_agent_is_switched_only_outside_navigation_requests():
    problems = _user_agent_problems(_read_code(CHAT_WEB_VIEW))
    assert not problems, f"{_rel(CHAT_WEB_VIEW)}: {problems}"


USER_AGENT_MUTATIONS = {
    "sync switch in request": (
        "                request.reject()\n                page.userAgentRetry = url\n",
        "                chatWeb.applyUserAgent(ChatSites.GOOGLE_SIGNIN_UA)\n"
        "                request.reject()\n                page.userAgentRetry = url\n",
    ),
    "direct write elsewhere": (
        "    function syncUserAgent() {\n",
        "    function syncUserAgent() {\n        chatProfile.httpUserAgent = \"x\"\n",
    ),
    "hints written elsewhere": (
        "    function syncUserAgent() {\n",
        "    function syncUserAgent() {\n        chatProfile.clientHints.isAllClientHintsEnabled = true\n",
    ),
}


@pytest.mark.parametrize("name", sorted(USER_AGENT_MUTATIONS))
def test_proof_user_agent_rule_catches(name):
    assert _user_agent_problems(_mutated(CHAT_WEB_VIEW, *USER_AGENT_MUTATIONS[name]))


def test_firefox_user_agent_is_declared_only_in_chat_sites_js():
    offenders = [
        f"{_rel(path)}:{line}"
        for path in _code_files() if path != CHAT_SITES_JS
        for line in _hits(r"Firefox/|Gecko/\d", _read_code(path))
    ]
    assert not offenders, f"the Google sign-in user agent belongs in ChatSites.js only: {offenders}"
    assert len(_hits(r"Gecko/\d+ Firefox/", _read_code(CHAT_SITES_JS))) == 1


# --- persisted configuration ------------------------------------------------------


def _chat_config_keys():
    """The chat key set: chatOllamaUrl joins once main.xml has it or the Ollama view exists."""
    keys = dict(CHAT_CONFIG_KEYS)
    if OLLAMA_CHAT_VIEW.is_file() or set(OLLAMA_CONFIG_KEYS) & set(_main_xml_entries()):
        keys.update(OLLAMA_CONFIG_KEYS)
    return keys


def _unexpected_main_xml_keys(entries):
    return set(entries) - set(_chat_config_keys()) - PRE_CHAT_CONFIG_KEYS - set(GENERAL_CONFIG_KEYS)


def test_main_xml_adds_only_the_chat_keys():
    entries = _main_xml_entries()
    expected = _chat_config_keys()
    chat_keys = {name for name in entries if name.lower().startswith("chat")}
    assert chat_keys == set(expected), (
        f"{_rel(MAIN_XML)} chat entries must be exactly {sorted(expected)}, got {sorted(chat_keys)}"
    )
    unexpected = _unexpected_main_xml_keys(entries)
    assert not unexpected, f"{_rel(MAIN_XML)} has new persisted keys besides the chat ones: {sorted(unexpected)}"
    for key, (kind, default) in sorted(expected.items()):
        assert entries[key]["group"] == "General", f"{_rel(MAIN_XML)}: {key} must be in group General"
        assert entries[key]["type"] == kind, f"{_rel(MAIN_XML)}: {key} must have type {kind}"
        if default is not None:
            assert entries[key]["default"] == default, (
                f"{_rel(MAIN_XML)}: {key} default must be exactly {default!r}, got {entries[key]['default']!r}"
            )


@pytest.mark.parametrize("filename", CHAT_CONFIG_READ_ONLY_FILES)
def test_chat_files_never_write_the_plasmoid_config(filename):
    path = UI / filename
    _require_phased(path)
    code = _read_code(path)
    config = r"\b[Pp]lasmoid\s*\.\s*configuration"
    member = r"(?:\s*\.\s*\w+|\s*\[[^\]]*\])"
    lines = (
        # Plain or compound assignment: x = v, x += v, x ??= v (not ==).
        _hits(rf"{config}{member}+\s*(?:[-+*/%&|^]|\*\*|<<|>>>?|&&|\|\||\?\?)?=(?!=)", code)
        # Increment and decrement on either side.
        + _hits(rf"{config}{member}+\s*(?:\+\+|--)", code)
        + _hits(rf"(?:\+\+|--)\s*{config}", code)
        # The config object itself handed around, e.g. `var c = Plasmoid.configuration`.
        + _hits(rf"{config}(?!\s*[.\[])", code)
    )
    assert not lines, f"{_rel(path)} must never write Plasmoid.configuration; lines {sorted(set(lines))}"


@pytest.mark.parametrize("key", ["usageHistoryCache", "panelRingColor", "middleClickOpensTwo", "usageHistoryClearOwedAt"])
def test_proof_unlisted_main_xml_key_is_caught(key):
    entries = dict(_main_xml_entries())
    entries[key] = {"group": "General", "type": "String", "default": ""}
    assert _unexpected_main_xml_keys(entries) == {key}


# The chat keys main.qml may write: the profile generation and the zoom map
# (the zoom map only from zoomWriteTimer, see _zoom_write_problems).
MAIN_WRITABLE_CHAT_KEYS = {"chatProfileGeneration", "chatSiteZoom"}


def _main_config_write_offenders(code):
    """main.qml may write chatProfileGeneration and chatSiteZoom and no other chat key."""
    return [
        f"{_line_of(code, match.start())} {match.group(1)}"
        for match in re.finditer(r"\bPlasmoid\s*\.\s*configuration\s*\.\s*(chat\w*)\s*(?:[-+*/%&|^]|\?\?)?=(?!=)", code)
        if match.group(1) not in MAIN_WRITABLE_CHAT_KEYS
    ] + [
        str(line) for line in _hits(r"\bPlasmoid\s*\.\s*configuration\s*\[", code)
    ]


def test_main_writes_only_the_profile_generation_and_zoom_chat_keys():
    offenders = _main_config_write_offenders(_read_code(MAIN_QML))
    assert not offenders, (
        f"{_rel(MAIN_QML)} may only write {sorted(MAIN_WRITABLE_CHAT_KEYS)} among chat keys: {offenders}"
    )


def test_proof_main_chat_config_write_is_caught():
    code = _mutated(MAIN_QML, "    function chatNext() {",
                    "    function x() { Plasmoid.configuration.chatSignInStorage = \"encrypted\" }\n    function chatNext() {")
    assert _main_config_write_offenders(code)


@pytest.mark.parametrize("page", CONFIG_PAGES, ids=lambda path: path.name)
def test_config_pages_declare_every_chat_key_and_never_write_config(page):
    code = _read_code(page)
    expected = _chat_config_keys()
    for key, (kind, default) in expected.items():
        qml_type = {"String": "string", "Int": "int", "Bool": "bool"}[kind]
        for name in (f"cfg_{key}", f"cfg_{key}Default"):
            declared = re.findall(rf"(?m)^\s*property\s+(\w+)\s+{name}\s*:\s*(.+)$", code)
            assert len(declared) == 1 and declared[0][0] == qml_type, (
                f"{_rel(page)} must declare `property {qml_type} {name}` once, got {declared}"
            )
    literals = {"chatSignInStorage": '"memory"', "chatProfileGeneration": "0", "chatAutoLockMinutes": "0",
                "chatKeepOpen": "false", "chatSiteZoom": '"{}"', "chatVaultUnlock": '"passphrase"'}
    if "chatOllamaUrl" in expected:
        literals["chatOllamaUrl"] = f'"{OLLAMA_CONFIG_KEYS["chatOllamaUrl"][1]}"'
    for key, literal in literals.items():
        for name in (f"cfg_{key}", f"cfg_{key}Default"):
            value = re.findall(rf"(?m)^\s*property\s+\w+\s+{name}\s*:\s*(.+?)\s*$", code)
            assert value == [literal], f"{_rel(page)}: {name} must default to {literal}, got {value}"
    writes = _hits(r"\bPlasmoid\s*\.\s*configuration\s*(?:\.\s*\w+|\[[^\]]*\])\s*=(?!=)", code)
    assert not writes, f"{_rel(page)} must write cfg_ properties, never Plasmoid.configuration; lines {writes}"
    gen_writes = [
        line for line in _hits(r"\bcfg_chatProfileGeneration\s*=(?!=)", code)
    ]
    assert len(gen_writes) <= 1, f"{_rel(page)}: cfg_chatProfileGeneration may only be synced from the config"


# --- settings pages: General, AI Usage, Chat ----------------------------------------


def _general_key_problems(entries):
    problems = []
    for key, (kind, default) in sorted(GENERAL_CONFIG_KEYS.items()):
        if key not in entries:
            problems.append(f"{_rel(MAIN_XML)} is missing {key}")
            continue
        # An empty <default></default> parses as None: it is the "" default.
        entry = dict(entries[key], default=entries[key]["default"] or "")
        if entry != {"group": "General", "type": kind, "default": default}:
            problems.append(f"{_rel(MAIN_XML)}: {key} must be {kind} {default!r} in group General, got {entries[key]}")
    return problems


def test_general_keys_have_their_exact_type_and_default():
    problems = _general_key_problems(_main_xml_entries())
    assert not problems, problems


@pytest.mark.parametrize(("key", "field", "value"), [
    ("usageHistoryEnabled", "default", "true"),
    ("usageHistoryEnabled", "type", "String"),
    ("usageHistoryClearOwed", "default", "true"),
    ("panelRing", "default", "off"),
    ("middleClickOpens", "default", "usage"),
    ("middleClickOpens", "group", "Chat"),
])
def test_proof_round_4_key_type_and_default_are_pinned(key, field, value):
    entries = dict(_main_xml_entries())
    entries[key] = dict(entries[key], **{field: value})
    assert _general_key_problems(entries)


def test_config_qml_lists_the_pages_in_order():
    code = _read_code(CONFIG_QML)
    sources = re.findall(r'\bsource\s*:\s*"([^"]+)"', code)
    assert sources == [page.name for page in CONFIG_PAGES], (
        f"{_rel(CONFIG_QML)} must list {[page.name for page in CONFIG_PAGES]}, got {sources}"
    )
    for page in CONFIG_PAGES:
        assert page.is_file(), f"{_rel(page)} is missing"


_QML_TYPES = {"String": "string", "Int": "int", "Bool": "bool"}


def _page_key_problems(code, entries):
    """Each page declares cfg_<key> and cfg_<key>Default once, with the kcfg type, for every key."""
    problems = []
    for key, entry in sorted(entries.items()):
        qml_type = _QML_TYPES[entry["type"]]
        for name in (f"cfg_{key}", f"cfg_{key}Default"):
            declared = re.findall(rf"(?m)^\s*property\s+(\w+)\s+{name}\s*:", code)
            if declared != [qml_type]:
                problems.append(f"{name}: want `property {qml_type}` once, got {declared}")
    return problems


@pytest.mark.parametrize("page", CONFIG_PAGES, ids=lambda path: path.name)
def test_config_pages_declare_every_key(page):
    code = _read_code(page)
    problems = _page_key_problems(code, _main_xml_entries())
    for key, (kind, default) in GENERAL_CONFIG_KEYS.items():
        literal = f'"{default}"' if kind == "String" else default
        for name in (f"cfg_{key}", f"cfg_{key}Default"):
            value = re.findall(rf"(?m)^\s*property\s+\w+\s+{name}\s*:\s*(.+?)\s*$", code)
            if value != [literal]:
                problems.append(f"{name} must default to {literal}, got {value}")
    assert not problems, f"{_rel(page)}: {problems}"


def test_proof_missing_page_key_is_caught():
    code = _mutated(CONFIG_PAGES[0], '    property string cfg_popupSize: "normal"\n', "")
    assert _page_key_problems(code, _main_xml_entries())


# Keys main.qml may write: the profile generation, the schema and first-run
# flags, the normalized refresh interval, the popup's Left/Used buttons and
# the debounced per-site zoom map, and (only in the one-time schema 2 -> 3
# migration, see _main_migration_problems) the two reading choices.
MAIN_WRITABLE_KEYS = {
    "chatProfileGeneration", "configSchemaVersion", "initialSetupComplete", "refreshInterval", "usageMode",
    "chatSiteZoom", "tooltipMetrics", "providerMetrics", "usageHistoryClearOwed",
}


def _main_written_keys(code):
    return {
        match.group(1)
        for match in re.finditer(r"\bPlasmoid\s*\.\s*configuration\s*\.\s*(\w+)\s*(?:[-+*/%&|^]|\?\?)?=(?!=)", code)
    }


def test_main_writes_only_its_own_keys():
    written = _main_written_keys(_read_code(MAIN_QML))
    assert written <= MAIN_WRITABLE_KEYS, f"{_rel(MAIN_QML)} writes {sorted(written - MAIN_WRITABLE_KEYS)}"


def test_proof_main_general_key_write_is_caught():
    code = _mutated(MAIN_QML, "    function chatNext() {",
                    "    function x() { Plasmoid.configuration.showChatTab = true }\n    function chatNext() {")
    assert _main_written_keys(code) - MAIN_WRITABLE_KEYS


@pytest.mark.parametrize("key", ["usageHistoryEnabled", "panelRing", "middleClickOpens", "usageMode2", "chatSites"])
def test_proof_main_round_4_key_write_is_caught(key):
    code = _mutated(MAIN_QML, "    function chatNext() {",
                    f"    function x() {{ Plasmoid.configuration.{key} = \"\" }}\n    function chatNext() {{")
    assert _main_written_keys(code) - MAIN_WRITABLE_KEYS == {key}


def _shortcut_offenders(sources):
    # The shortcut lives only in Plasma's own Keyboard Shortcuts tab.
    return [
        f"{name}:{line}"
        for name, code in sources.items()
        for pattern in (r"\bglobalShortcut\b", r"\bKeySequenceItem\b", r"\borg\.kde\.kquickcontrols\b")
        for line in _hits(pattern, code)
    ]


def test_no_page_sets_the_keyboard_shortcut():
    offenders = _shortcut_offenders(_all_code())
    assert not offenders, f"the keyboard shortcut belongs to Plasma's Keyboard Shortcuts tab: {offenders}"


def test_proof_shortcut_field_is_caught():
    assert _shortcut_offenders({"configGeneral.qml": "function saveConfig() { Plasmoid.globalShortcut = k }"})


def _privacy_page_problems(sources):
    """Stay signed in, its confirmation and the encrypted-folder helper live on the General page only."""
    problems = []
    general = "plasmoid/contents/ui/configGeneral.qml"
    for name, code in sources.items():
        if name == general:
            continue
        if _hits(r"\bcfg_chatSignInStorage\s*=(?!=)", code):
            problems.append(f"{name}: writes cfg_chatSignInStorage")
        if _hits(r"\bid\s*:\s*vaultSource\b", code):
            problems.append(f"{name}: declares vaultSource")
        if name != "plasmoid/contents/ui/main.qml" and _hits(r"\bChatStorage\s*\.\s*vaultCommand\s*\(", code):
            problems.append(f"{name}: builds a vault command")
    code = sources.get(general, "")
    if len(_hits(r"\bid\s*:\s*vaultSource\b", code)) != 1:
        problems.append("configGeneral.qml must declare vaultSource once")
    if not re.search(r"confirmingOff\s*=\s*false\s*\n\s*page\.cfg_chatSignInStorage\s*=\s*\"memory\"", code):
        problems.append("configGeneral.qml: Off is applied only from the Turn off and delete confirmation")
    return problems


def test_privacy_settings_live_on_the_general_page():
    problems = _privacy_page_problems(_all_code())
    assert not problems, problems


def test_proof_privacy_page_rule_catches():
    sources = _all_code()
    sources["plasmoid/contents/ui/configChat.qml"] += "\nfunction f() { page.cfg_chatSignInStorage = \"memory\" }\n"
    assert _privacy_page_problems(sources)


# Hidden tabs: no usage helper without Usage, no chat view or Ollama without Chat.
HIDDEN_TAB_RULES = {
    "main.qml": (
        (r"readonly\s+property\s+var\s+popupTabs\s*:\s*SettingsLogic\.visibleTabs\(\s*"
         r"Plasmoid\.configuration\.showUsageTab\s*,\s*Plasmoid\.configuration\.showChatTab\s*,\s*"
         r"root\.chatSiteIds\.length\s*>\s*0\s*\)", "popupTabs from SettingsLogic.visibleTabs"),
        (r"readonly\s+property\s+bool\s+chatShown\s*:\s*root\.popupTabs\.chat\s*\n", "chatShown"),
        (r"readonly\s+property\s+bool\s+usageShown\s*:\s*root\.popupTabs\.usage\s*\n", "usageShown"),
        (r"function\s+refresh\s*\(\s*\)\s*\{\s*if\s*\(\s*!\s*root\.usageShown\s*\)\s*return\b",
         "refresh() returns at once while Usage is hidden"),
        (r"interval\s*:\s*root\.refreshInterval\s*\*\s*1000\s*\n\s*running\s*:\s*root\.usageShown\s*\n",
         "the refresh timer runs only while Usage is shown"),
        (r"toolTipSubText\s*:\s*\{\s*if\s*\(\s*!\s*root\.usageShown\s*\|\|\s*!\s*root\.tooltipShowsUsage\s*\)\s*"
         r"return\s*\"\"", "the tooltip shows only the name without Usage"),
    ),
    "FullRepresentation.qml": (
        (r"readonly\s+property\s+bool\s+chatAvailable\s*:\s*root\.chatShown\s*\n", "chatAvailable: root.chatShown"),
        (r"function\s+onChatShownChanged\s*\(\s*\)\s*\{\s*if\s*\(\s*!\s*root\.chatShown\s*\)\s*chatView\.stop\(\)",
         "hiding Chat stops the chat view"),
        (r"siteEnabled\s*:\s*root\.chatShown\s*&&\s*root\.chatSiteIds\.indexOf\(\"ollama\"\)\s*>=\s*0\s*\n",
         "Ollama is enabled only while Chat is shown"),
    ),
}


def _hidden_tab_problems(sources):
    problems = []
    for name, rules in HIDDEN_TAB_RULES.items():
        for pattern, what in rules:
            if len(re.findall(pattern, sources[name])) != 1:
                problems.append(f"{name}: {what}")
    return problems


def test_hidden_tabs_start_nothing():
    sources = {"main.qml": _read_code(MAIN_QML), "FullRepresentation.qml": _read_code(FULL_REPRESENTATION)}
    problems = _hidden_tab_problems(sources)
    assert not problems, problems


@pytest.mark.parametrize(("target", "old", "new"), [
    (MAIN_QML, "        if (!root.usageShown)\n            return\n        var providerIds", "        var providerIds"),
    # The newline keeps the tooltip clock's `running: root.usageShown && ...` out of it.
    (MAIN_QML, "        running: root.usageShown\n", "        running: true\n"),
    (MAIN_QML, "    readonly property bool chatShown: root.popupTabs.chat", "    readonly property bool chatShown: true"),
    (FULL_REPRESENTATION, "readonly property bool chatAvailable: root.chatShown",
     "readonly property bool chatAvailable: root.chatSiteIds.length > 0"),
    (FULL_REPRESENTATION, "                chatView.stop()", "                chatView.focusLater()"),
    (FULL_REPRESENTATION, 'siteEnabled: root.chatShown && root.chatSiteIds.indexOf("ollama") >= 0',
     'siteEnabled: root.chatSiteIds.indexOf("ollama") >= 0'),
])
def test_proof_hidden_tab_rule_catches(target, old, new):
    sources = {"main.qml": _read_code(MAIN_QML), "FullRepresentation.qml": _read_code(FULL_REPRESENTATION)}
    sources[target.name] = _mutated(target, old, new)
    assert _hidden_tab_problems(sources)


def test_settings_logic_js_is_a_pure_library():
    code = _read_code(SETTINGS_LOGIC_JS)
    assert re.match(r"\s*\.pragma\s+library\b", code), "SettingsLogic.js must start with .pragma library"
    for pattern in (r"\.import\b", r"\bQt\s*\.", r"\bXMLHttpRequest\b", r"\bconsole\b", r"\bPlasmoid\b"):
        assert not _hits(pattern, code), f"{_rel(SETTINGS_LOGIC_JS)} must stay pure: {pattern}"


# "?" hints: fixed text only, never something read from the helper or a site.
HELP_TEXT = r"\btoolTipText\s*:\s*(.*)"


def _help_hint_problems(code):
    return [
        f"line {_line_of(code, match.start())}: {match.group(1).strip()[:60]}"
        for match in re.finditer(HELP_TEXT, code)
        if not re.fullmatch(r'i18n\("(?:[^"\\]|\\.)*"\)', match.group(1).strip())
    ]


@pytest.mark.parametrize("page", CONFIG_PAGES, ids=lambda path: path.name)
def test_help_hints_show_fixed_text_only(page):
    code = _read_code(page)
    assert _hits(r"\bKirigami\.ContextualHelpButton\s*\{", code), f"{_rel(page)} has no help hints"
    problems = _help_hint_problems(code)
    assert not problems, f"{_rel(page)}: {problems}"


def test_proof_help_hint_rule_catches():
    assert _help_hint_problems("Kirigami.ContextualHelpButton { toolTipText: page.statusMessage }")
    assert _help_hint_problems('Kirigami.ContextualHelpButton { toolTipText: i18n("a %1", x) }')


def test_usage_page_has_no_about_block():
    code = _read_code(UI / "configUsage.qml")
    for word in ("Remove Widget", "internalAction", "metaData.version", 'i18n("About")'):
        assert word not in code, f"configUsage.qml must not have the About block: {word}"


# --- locking: the profile is closed before the folder is unmounted ---------------


def _lock_wait_problems(code):
    """Every queued lock follows a wait step; the wait lasts at least 1 s.

    Destroying the saved profile writes its newest cookies and site storage
    (cookie flush spike, 2026-11-01); the helper must not unmount before.
    """
    problems = []
    for match in re.finditer(r"\bchatEnqueue\s*\(\s*\[([^\]]*)\]", code):
        steps = re.findall(r'"([\w-]+)"', match.group(1))
        for index, step in enumerate(steps):
            if step in ("lock", "leave-lock") and not any(
                    earlier in ("wait", "leave-wait") for earlier in steps[:index]):
                problems.append(f"{_line_of(code, match.start())}: {step} without an earlier wait")
    timers = [body for _, body in _blocks(code, r"\bTimer\s*\{") if re.search(r"\bid\s*:\s*chatWaitTimer\b", body)]
    intervals = re.findall(r"\binterval\s*:\s*(\d+)\s*$", timers[0], re.M) if len(timers) == 1 else []
    if len(intervals) != 1 or int(intervals[0]) < 1000:
        problems.append("chatWaitTimer must exist once with a literal interval of at least 1000 ms")
    return problems


def test_every_lock_waits_for_the_profile_to_close():
    problems = _lock_wait_problems(_read_code(MAIN_QML))
    assert not problems, f"{_rel(MAIN_QML)}: {problems}"


@pytest.mark.parametrize(("old", "new"), [
    ('root.chatAutoLocking = true\n            root.chatVaultHold = true\n            root.chatVaultError = ""\n'
     '            root.chatPreparedGeneration = -1\n            root.chatEnqueue(["wait", "lock"])',
     'root.chatAutoLocking = true\n            root.chatVaultHold = true\n            root.chatVaultError = ""\n'
     '            root.chatPreparedGeneration = -1\n            root.chatEnqueue(["lock"])'),
    ('["leave-wait", "leave-remove", "leave-lock"', '["leave-remove", "leave-lock"'),
    ("        id: chatWaitTimer\n        interval: 1000", "        id: chatWaitTimer\n        interval: 200"),
])
def test_proof_lock_wait_rule_catches(old, new):
    assert _lock_wait_problems(_mutated(MAIN_QML, old, new))


# --- popup: closes on click elsewhere unless Keep open is set ---------------------

HIDE_ON_DEACTIVATE = (
    r"(?m)^\s*hideOnWindowDeactivate\s*:\s*!\s*Plasmoid\.configuration\.chatKeepOpen\s*&&\s*!\s*root\.chatDialogOpen\s*$"
)


def _popup_problems(sources):
    problems = []
    main = sources.get("main.qml", "")
    if len(_hits(HIDE_ON_DEACTIVATE, main)) != 1 or len(_hits(r"\bhideOnWindowDeactivate\s*:", main)) != 1:
        problems.append("main.qml: hideOnWindowDeactivate must be `!Plasmoid.configuration.chatKeepOpen && !root.chatDialogOpen`")
    for name, code in sources.items():
        # The transient pin and the panel provider list are gone for good.
        for word in ("chatPinned", "window-pin", "panelProviders", "compactGroups"):
            if _hits(rf"\b{re.escape(word)}\b", code):
                problems.append(f"{name}: {word}")
    return problems


def _ui_sources():
    return {path.name: _read_code(path) for path in _code_files()}


def test_popup_stays_open_only_by_the_setting_or_a_dialog():
    problems = _popup_problems(_ui_sources())
    assert not problems, problems


@pytest.mark.parametrize(("old", "new"), [
    ("hideOnWindowDeactivate: !Plasmoid.configuration.chatKeepOpen && !root.chatDialogOpen",
     "hideOnWindowDeactivate: !root.chatPinned && !root.chatDialogOpen"),
    ("hideOnWindowDeactivate: !Plasmoid.configuration.chatKeepOpen && !root.chatDialogOpen",
     "hideOnWindowDeactivate: false"),
])
def test_proof_popup_rule_catches(old, new):
    sources = _ui_sources()
    sources["main.qml"] = _mutated(MAIN_QML, old, new)
    assert _popup_problems(sources)


def test_proof_panel_provider_list_is_caught():
    sources = _ui_sources()
    sources["main.qml"] = sources["main.qml"] + "\nreadonly property var panelProviders: []\n"
    assert _popup_problems(sources)


def test_chat_sites_js_declares_the_expected_sites_in_order():
    site_ids = _chat_site_ids()
    assert site_ids == EXPECTED_SITE_IDS, (
        f"{_rel(CHAT_SITES_JS)} site ids must be {EXPECTED_SITE_IDS} in that order, got {site_ids}"
    )
    assert list(_chat_sites()) == EXPECTED_SITE_IDS, (
        f"{_rel(CHAT_SITES_JS)}: every top-level site object must have a literal id"
    )


def test_chat_sites_default_is_the_default_on_sites_in_order():
    entries = _main_xml_entries()
    assert "chatSites" in entries, f"{_rel(MAIN_XML)} has no chatSites entry"
    raw_default = entries["chatSites"]["default"]
    try:
        configured = json.loads(raw_default or "")
    except json.JSONDecodeError as error:
        raise AssertionError(f"{_rel(MAIN_XML)}: chatSites default is not JSON: {error}") from None
    assert configured == EXPECTED_DEFAULT_SITE_IDS, (
        f"{_rel(MAIN_XML)} chatSites default {configured} must be {EXPECTED_DEFAULT_SITE_IDS} (no {LOCAL_SITE_ID})"
    )
    default_on = [
        site_id for site_id, site in _chat_sites().items()
        if not re.search(r"""[{,]\s*["']?default_on["']?\s*:\s*false\b""", site)
    ]
    assert default_on == EXPECTED_DEFAULT_SITE_IDS, (
        f"{_rel(CHAT_SITES_JS)}: sites without default_on: false must be {EXPECTED_DEFAULT_SITE_IDS}, got {default_on}"
    )


def test_local_site_is_off_by_default_and_the_only_local_site():
    sites = _chat_sites()
    assert LOCAL_SITE_ID in sites, f"{_rel(CHAT_SITES_JS)} has no {LOCAL_SITE_ID} site"
    local = sites[LOCAL_SITE_ID]
    assert re.search(r"""[{,]\s*["']?default_on["']?\s*:\s*false\s*[,}\n]""", local), (
        f"{_rel(CHAT_SITES_JS)}: the {LOCAL_SITE_ID} site must say literally `default_on: false`"
    )
    assert re.search(r"""[{,]\s*["']?local["']?\s*:\s*true\s*[,}\n]""", local), (
        f"{_rel(CHAT_SITES_JS)}: the {LOCAL_SITE_ID} site must say literally `local: true`"
    )
    others = {
        site_id: _key_hits(site, "local", "false") + _key_hits(site, "default_on", "true")
        for site_id, site in sites.items() if site_id != LOCAL_SITE_ID
    }
    offenders = {site_id: hits for site_id, hits in others.items() if hits}
    assert not offenders, (
        f"{_rel(CHAT_SITES_JS)}: only {LOCAL_SITE_ID} may set `local` (other than false) "
        f"or `default_on` (other than true): {offenders}"
    )


_LOCAL_HTTP_URL = re.compile(r"http://(?:localhost|127\.0\.0\.1)(?::\d{1,5})?(?:/|$)")


def test_site_urls_are_https_except_the_local_loopback_site():
    wrong = {}
    for site_id, site in _chat_sites().items():
        url = _site_key(site, "url")
        if url is None:
            wrong[site_id] = "no literal url"
        elif site_id == LOCAL_SITE_ID:
            if not _LOCAL_HTTP_URL.match(url):
                wrong[site_id] = url
        elif not url.startswith("https://"):
            wrong[site_id] = url
    assert not wrong, (
        f"{_rel(CHAT_SITES_JS)}: site urls must be https:// (only {LOCAL_SITE_ID} may use "
        f"http://localhost or http://127.0.0.1): {wrong}"
    )


def test_chat_default_site_default_is_a_known_site():
    entries = _main_xml_entries()
    assert "chatDefaultSite" in entries, f"{_rel(MAIN_XML)} has no chatDefaultSite entry"
    default = (entries["chatDefaultSite"]["default"] or "").strip()
    assert default == "claude", f"{_rel(MAIN_XML)}: chatDefaultSite default must be claude, got {default!r}"
    assert default in _chat_site_ids(), f"{_rel(MAIN_XML)}: chatDefaultSite {default!r} is not in ChatSites.js"


# --- built-in Ollama chat (plan "Policy rules" P1-P11) -----------------------------
#
# OllamaChat.js (T1) and OllamaChatView.qml (T4) arrive in later phases. Each
# rule about them skips while its file is missing and enforces once it exists.
# Rule checkers take source text; the proofs feed them a violating copy of the
# real file when it exists, else of the small compliant sample below, so the
# proofs run in every phase.

# A minimal view that follows every rule. Used only when the real view is
# missing, and kept here (not in plasmoid/) so it never counts as plasmoid code.
SAMPLE_OLLAMA_VIEW = """\
import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasma5support as Plasma5Support
import "OllamaChat.js" as OllamaChat

Item {
    id: ollamaView
    property var createRequest: function () { return new XMLHttpRequest() }
    property var runOwnerCheck: function (command) { ownerSource.connectSource(command) }

    function loadTags(address) {
        var xhr = ollamaView.createRequest()
        xhr.open("GET", OllamaChat.endpoint(address, "tags"))
        xhr.send()
    }
    function sendChat(address, body) {
        var xhr = ollamaView.createRequest()
        xhr.open("POST", OllamaChat.endpoint(address, "chat"))
        xhr.setRequestHeader("Content-Type", "application/json")
        xhr.send(body)
        confirm.open()
    }
    Plasma5Support.DataSource {
        id: ownerSource
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            ownerSource.disconnectSource(source)
            ollamaView.ownerDone(OllamaChat.parseOwnerReply(data["exit code"], data["stdout"]))
        }
    }
    QQC2.Label {
        text: i18n("Ollama isn't running.")
        textFormat: Text.PlainText
    }
    Kirigami.Heading { text: i18n("Ollama"); textFormat: Text.PlainText }
    TextEdit {
        readOnly: true
        textFormat: TextEdit.PlainText
        text: "reply"
    }
    QQC2.TextArea {
        id: input
        textFormat: TextEdit.PlainText
        Kirigami.SpellCheck.enabled: false
        inputMethodHints: Qt.ImhNoPredictiveText | Qt.ImhSensitiveData
    }
}
"""
SAMPLE_OLLAMA_JS = """\
.pragma library

var DEFAULT_ADDRESS = "http://127.0.0.1:11434"

function ownerCommand(port, run, applet) {
    return "env HEARTHWIRE_RUN=" + run + " HEARTHWIRE_APPLET=" + applet
        + " python3 -P -m hearthwire --port-owner " + port
}
"""


def _ollama_source(path, sample):
    """The real file when it exists, else the compliant sample (for proofs)."""
    return path.read_text(encoding="utf-8") if path.is_file() else sample


def _mutated_source(path, sample, old, new):
    raw = _ollama_source(path, sample)
    assert old in raw, f"proof fixture out of date: {old!r} not in {path.name}"
    return _strip_comments(raw.replace(old, new, 1))


def _inserted_view(snippet):
    """The view (real or sample) with ``snippet`` added as the root item's first child."""
    raw = _ollama_source(OLLAMA_CHAT_VIEW, SAMPLE_OLLAMA_VIEW)
    blanked = _strip_comments(raw, blank_strings=True)
    match = re.search(r"(?m)^[A-Za-z_][\w.]*\s*\{", blanked)
    assert match, "the view has no root item"
    end = match.end()
    return _strip_comments(raw[:end] + "\n" + snippet + "\n" + raw[end:])


def _inserted_js(snippet):
    raw = _ollama_source(OLLAMA_CHAT_JS, SAMPLE_OLLAMA_JS)
    head, sep, tail = raw.partition(".pragma library\n")
    assert sep, "OllamaChat.js must start with .pragma library"
    return head + sep + snippet + "\n" + tail


def test_ollama_samples_follow_every_rule():
    # The proofs below are only meaningful if the unmutated inputs pass.
    view = _strip_comments(SAMPLE_OLLAMA_VIEW)
    assert not _ollama_js_problems(SAMPLE_OLLAMA_JS)
    assert not _ollama_request_problems(view)
    assert not _plain_text_problems(view)
    assert not _input_privacy_problems(view)
    assert not _port_owner_flag_problems({"OllamaChatView.qml": view,
                                          "OllamaChat.js": _strip_comments(SAMPLE_OLLAMA_JS)})
    assert not _seam_problems({"OllamaChatView.qml": view}, view_present=True)
    assert not _xhr_offenders({"OllamaChatView.qml": view})
    assert not _ollama_storage_offenders({"OllamaChatView.qml": view,
                                          "OllamaChat.js": _strip_comments(SAMPLE_OLLAMA_JS)})


# P1 OllamaChat.js is a pure library: no imports, no requests, no Qt, no logs, no storage.

OLLAMA_JS_FORBIDDEN = {
    "XMLHttpRequest": r"\bXMLHttpRequest\b",
    "Qt.": r"\bQt\s*\.",
    "console": r"\bconsole\b",
    "LocalStorage": r"\bLocalStorage\b",
    "openDatabaseSync": r"\bopenDatabaseSync\b",
    "eval": r"\beval\s*\(|\bFunction\s*\(",
}


def _ollama_js_problems(raw):
    code = _strip_comments(raw)
    problems = []
    if not re.match(r"\s*\.pragma\s+library\b", code):
        problems.append("must start with .pragma library")
    imports = _hits(r"(?m)^\s*(?:\.import\b|import\b)", code) + _hits(r"\bQt\.include\s*\(", code)
    if imports:
        problems.append(f"must not import anything (lines {imports})")
    for name, pattern in OLLAMA_JS_FORBIDDEN.items():
        lines = _hits(pattern, code)
        if lines:
            problems.append(f"must not use {name} (lines {lines})")
    return problems


def test_ollama_chat_js_is_a_pure_library():
    _require_phased(OLLAMA_CHAT_JS)
    problems = _ollama_js_problems(OLLAMA_CHAT_JS.read_text(encoding="utf-8"))
    assert not problems, f"{_rel(OLLAMA_CHAT_JS)}: {problems}"


@pytest.mark.parametrize("snippet", [
    "import QtQuick 2.15",
    ".import \"ChatSites.js\" as ChatSites",
    "Qt.include(\"x.js\")",
    "function get(u) { var x = new XMLHttpRequest(); return x }",
    "function open(u) { Qt.openUrlExternally(u) }",
    "function log(t) { console.log(t) }",
    "var db = LocalStorage.openDatabaseSync(\"x\", \"1\", \"x\", 1)",
    "var f = eval(\"1\")",
])
def test_proof_ollama_chat_js_rule_catches(snippet):
    assert _ollama_js_problems(_inserted_js(snippet))


def test_proof_ollama_chat_js_needs_pragma():
    assert _ollama_js_problems(_ollama_source(OLLAMA_CHAT_JS, SAMPLE_OLLAMA_JS).replace(".pragma library", "", 1))


# P2 XMLHttpRequest only in OllamaChatView.qml, and there only as the createRequest default.

CREATE_REQUEST_DECLARATION = (
    r"(?m)^[ \t]*property\s+var\s+createRequest\s*:\s*function\s*\(\s*\)\s*\{\s*"
    r"return\s+new\s+XMLHttpRequest\s*\(\s*\)\s*;?\s*\}\s*$"
)


def _xhr_offenders(sources):
    offenders = []
    for name, code in sources.items():
        lines = _hits(r"\bXMLHttpRequest\b", code)
        if not name.endswith("OllamaChatView.qml"):
            offenders += [f"{name}:{line}" for line in lines]
        elif lines != _hits(CREATE_REQUEST_DECLARATION, code) or len(lines) > 1:
            offenders.append(f"{name}: XMLHttpRequest only once, as "
                             "`property var createRequest: function () { return new XMLHttpRequest() }`")
    return offenders


def test_xml_http_request_only_in_the_ollama_view():
    offenders = _xhr_offenders(_all_code())
    assert not offenders, f"XMLHttpRequest belongs to OllamaChatView.qml only: {offenders}"


def test_proof_xml_http_request_elsewhere_is_caught():
    code = _mutated(MAIN_QML, "    function chatNext() {",
                    "    function x() { return new XMLHttpRequest() }\n    function chatNext() {")
    assert _xhr_offenders({"main.qml": code})


def test_proof_second_xml_http_request_in_view_is_caught():
    view = _inserted_view("    function raw() { return new XMLHttpRequest() }")
    assert _xhr_offenders({"OllamaChatView.qml": view})


# P3 Requests go only to OllamaChat.endpoint() with GET or POST and one JSON header.

def _ollama_request_problems(code):
    problems = []
    for match in re.finditer(r"\.\s*open\s*\((?!\s*\))", code):
        if not re.match(r"\.\s*open\s*\(\s*\"(?:GET|POST)\"\s*,\s*OllamaChat\.endpoint\s*\(", code[match.start():]):
            problems.append(f'line {_line_of(code, match.start())}: .open( must be .open("GET"|"POST", '
                            "OllamaChat.endpoint(...)")
    for pattern, rule in (
            (r"""\[\s*["']open["']\s*\]""", "no indirect open"),
            (r"""\[\s*["']setRequestHeader["']\s*\]""", "no indirect setRequestHeader"),
            (r"\bwithCredentials\b", "no withCredentials"),
            (r"(?i)\bauthorization\b", "no Authorization header"),
            (r"(?i)\bcookie", "no cookies")):
        lines = _hits(pattern, code)
        if lines:
            problems.append(f"{rule} (lines {lines})")
    for match in re.finditer(r"\bsetRequestHeader\s*\(", code):
        if not re.match(r'setRequestHeader\s*\(\s*"Content-Type"\s*,\s*"application/json"\s*\)',
                        code[match.start():]):
            problems.append(f'line {_line_of(code, match.start())}: only setRequestHeader("Content-Type", '
                            '"application/json")')
    return problems


def test_ollama_view_requests_only_the_ollama_endpoints():
    _require_phased(OLLAMA_CHAT_VIEW)
    problems = _ollama_request_problems(_read_code(OLLAMA_CHAT_VIEW))
    assert not problems, f"{_rel(OLLAMA_CHAT_VIEW)}: {problems}"


@pytest.mark.parametrize("snippet", [
    '    function a(x) { x.open("PUT", OllamaChat.endpoint(ollamaView.address, "chat")) }',
    '    function a(x) { x.open("GET", ollamaView.address + "/api/tags") }',
    '    function a(x, m) { x.open(m, OllamaChat.endpoint(ollamaView.address, "chat")) }',
    '    function a(x) { x.open("GET", "http://127.0.0.1:11434/api/tags") }',
    '    function a(x) { x["open"]("GET", "http://evil.example/") }',
    '    function a(x) { x.setRequestHeader("Authorization", "Bearer t") }',
    '    function a(x) { x.setRequestHeader("Content-Type", "text/plain") }',
    '    function a(x, h) { x.setRequestHeader(h, "application/json") }',
    '    function a(x) { x.setRequestHeader("Cookie", "a=b") }',
    '    function a(x) { x.withCredentials = true }',
])
def test_proof_ollama_request_rule_catches(snippet):
    assert _ollama_request_problems(_inserted_view(snippet))


# P4 Model output is untrusted: every text element is PlainText, no rich text, links or images.

TEXT_ELEMENT = r"(?<![\w.])(?:[A-Za-z_]\w*\s*\.\s*)?(?:Text|Label|TextEdit|TextArea|Heading|SelectableLabel)\s*\{"
PLAIN_TEXT_FORMAT = r"(?:^|[\n;])\s*textFormat\s*:\s*(?:Text|TextEdit)\s*\.\s*PlainText\s*(?=;|\n|$)"
RICH_TEXT_BANS = {
    "RichText": r"\bRichText\b",
    "StyledText": r"\bStyledText\b",
    "MarkdownText": r"\bMarkdownText\b",
    "AutoText": r"\bAutoText\b",
    "onLinkActivated": r"\bonLinkActivated\b",
    "linkActivated": r"\blinkActivated\b",
    "openUrlExternally": r"\bopenUrlExternally\b",
    "baseUrl": r"\bbaseUrl\b",
    "Image {": r"(?<![\w.])(?:[A-Za-z_]\w*\s*\.\s*)?(?:Image|AnimatedImage|BorderImage)\s*\{",
    "non-plain textFormat": r"\btextFormat\s*(?::|=(?!=))(?!\s*(?:Text|TextEdit)\s*\.\s*PlainText\b)",
}


def _top_level(body):
    """The bindings of one ``{ ... }`` block with nested blocks and strings blanked."""
    blanked = _strip_comments(body, blank_strings=True)
    out = []
    depth = 0
    for char in blanked:
        if char == "{":
            depth += 1
            out.append(" ")
        elif char == "}":
            depth -= 1
            out.append(" ")
        else:
            out.append(char if depth == 1 or char == "\n" else " ")
    return "".join(out)


def _plain_text_problems(code):
    # TextField (a TextInput) has no textFormat and always shows plain text.
    problems = []
    elements = list(_blocks(code, TEXT_ELEMENT))
    for start, body in elements:
        if len(re.findall(PLAIN_TEXT_FORMAT, _top_level(body))) != 1:
            problems.append(f"line {_line_of(code, start)}: text element without "
                            "`textFormat: Text.PlainText` (or TextEdit.PlainText)")
    for name, pattern in RICH_TEXT_BANS.items():
        lines = _hits(pattern, code)
        if lines:
            problems.append(f"{name} is forbidden (lines {lines})")
    return problems


def test_ollama_view_shows_everything_as_plain_text():
    _require_phased(OLLAMA_CHAT_VIEW)
    code = _read_code(OLLAMA_CHAT_VIEW)
    problems = _plain_text_problems(code)
    assert list(_blocks(code, TEXT_ELEMENT)), f"{_rel(OLLAMA_CHAT_VIEW)}: no text elements found"
    assert not problems, f"{_rel(OLLAMA_CHAT_VIEW)}: {problems}"


@pytest.mark.parametrize("snippet", [
    "    Text { text: \"reply\" }",
    "    QQC2.Label {\n        text: \"reply\"\n    }",
    "    Kirigami.Heading { text: \"h\" }",
    "    Kirigami.SelectableLabel { text: \"r\" }",
    "    TextEdit { readOnly: true; text: \"r\"; textFormat: TextEdit.MarkdownText }",
    "    Text { text: \"r\"; textFormat: Text.AutoText }",
    "    Text { text: \"r\"; textFormat: Text.RichText }",
    "    Text { text: \"r\"; textFormat: Text.StyledText }",
    "    Text {\n        text: \"r\"\n        Text { textFormat: Text.PlainText }\n    }",
    "    Text { textFormat: Text.PlainText; onLinkActivated: (link) => Qt.openUrlExternally(link) }",
    "    TextEdit { textFormat: TextEdit.PlainText; baseUrl: \"http://127.0.0.1/\" }",
    "    Image { source: \"http://127.0.0.1:9/x\" }",
    "    function f(t) { t.textFormat = Text.RichText }",
])
def test_proof_plain_text_rule_catches(snippet):
    assert _plain_text_problems(_inserted_view(snippet))


# P4 also covers the model picker in FullRepresentation.qml: model names come
# from the server, so its delegate shows them as plain text only.

MODEL_COMBO = r"(?<![\w.])(?:[A-Za-z_]\w*\s*\.\s*)?ComboBox\s*\{"
MODEL_COMBO_MODEL = r"(?:^|[\n;])\s*model\s*:\s*ollamaView\s*\.\s*modelList\s*(?=;|\n|$)"


def _model_picker_problems(code):
    pickers = [(start, body) for start, body in _blocks(code, MODEL_COMBO)
               if re.search(MODEL_COMBO_MODEL, _top_level(body))]
    if len(pickers) != 1:
        return [f"exactly one ComboBox with `model: ollamaView.modelList`, found {len(pickers)}"]
    start, body = pickers[0]
    line = _line_of(code, start)
    top = _top_level(body)
    problems = []
    if not re.search(r"(?:^|[\n;])\s*delegate\s*:", top):
        problems.append(f"line {line}: the model picker needs its own delegate (the style's shows AutoText)")
    if re.search(r"(?:^|[\n;])\s*contentItem\s*:", top):
        problems.append(f"line {line}: the model picker must keep the style's contentItem (a TextField)")
    if not list(_blocks(body, TEXT_ELEMENT)):
        problems.append(f"line {line}: no text elements in the model picker delegate")
    problems += [f"model picker (from line {line}): {problem}" for problem in _plain_text_problems(body)]
    return problems


def test_model_picker_shows_model_names_as_plain_text():
    _require_phased(OLLAMA_CHAT_VIEW)
    problems = _model_picker_problems(_read_code(FULL_REPRESENTATION))
    assert not problems, f"{_rel(FULL_REPRESENTATION)}: {problems}"


@pytest.mark.parametrize(("old", "new"), [
    ("textFormat: Text.PlainText\n                    text: modelDelegate.modelData.name",
     "text: modelDelegate.modelData.name"),
    ("textFormat: Text.PlainText\n                    visible: text !== \"\"",
     "textFormat: Text.StyledText\n                    visible: text !== \"\""),
    ("        delegate: PlasmaComponents.ItemDelegate {\n            id: modelDelegate",
     "        property Component unused: PlasmaComponents.ItemDelegate {\n"
     "            id: modelDelegate"),
    ("        model: ollamaView.modelList\n",
     "        model: ollamaView.modelList\n        contentItem: Text { text: \"x\"; "
     "textFormat: Text.PlainText }\n"),
    ("        model: ollamaView.modelList\n", "        model: ollamaView.models\n"),
])
def test_proof_model_picker_rule_catches(old, new):
    assert _model_picker_problems(_mutated(FULL_REPRESENTATION, old, new))


# P5 The input never feeds spell checkers or IME learning.

EDITABLE_ELEMENT = r"(?<![\w.])(?:[A-Za-z_]\w*\s*\.\s*)?(?:TextArea|TextField|TextEdit|TextInput)\s*\{"


def _input_privacy_problems(code):
    problems = []
    inputs = [
        (start, _top_level(body)) for start, body in _blocks(code, EDITABLE_ELEMENT)
        if not re.search(r"(?:^|[\n;])\s*readOnly\s*:\s*true\s*(?=;|\n|$)", _top_level(body))
    ]
    if not inputs:
        problems.append("no editable input found")
    for start, top in inputs:
        line = _line_of(code, start)
        if not re.search(r"(?:^|[\n;])\s*Kirigami\.SpellCheck\.enabled\s*:\s*false\s*(?=;|\n|$)", top):
            problems.append(f"line {line}: the input needs `Kirigami.SpellCheck.enabled: false`")
        hints = re.findall(r"(?:^|[\n;])\s*inputMethodHints\s*:\s*([^;\n]+)", top)
        if len(hints) != 1 or not all(re.search(rf"\bQt\.{flag}\b", hints[0])
                                      for flag in ("ImhNoPredictiveText", "ImhSensitiveData")) \
                or re.search(r"[&~^]", hints[0]):
            problems.append(f"line {line}: inputMethodHints must include Qt.ImhNoPredictiveText | Qt.ImhSensitiveData")
    for pattern, rule in ((r"\bSpellCheck\s*\.\s*enabled\s*(?::|=(?!=))(?!\s*false\b)", "spell check on"),
                          (r"\binputMethodHints\s*=(?!=)", "inputMethodHints changed at runtime")):
        lines = _hits(pattern, code)
        if lines:
            problems.append(f"{rule} (lines {lines})")
    return problems


def test_ollama_input_disables_spell_check_and_ime_learning():
    _require_phased(OLLAMA_CHAT_VIEW)
    problems = _input_privacy_problems(_read_code(OLLAMA_CHAT_VIEW))
    assert not problems, f"{_rel(OLLAMA_CHAT_VIEW)}: {problems}"


@pytest.mark.parametrize("snippet", [
    "    QQC2.TextArea { textFormat: TextEdit.PlainText }",
    "    QQC2.TextField { Kirigami.SpellCheck.enabled: false }",
    "    QQC2.TextArea {\n        textFormat: TextEdit.PlainText\n        Kirigami.SpellCheck.enabled: false\n"
    "        inputMethodHints: Qt.ImhNoPredictiveText\n    }",
    "    QQC2.TextArea {\n        textFormat: TextEdit.PlainText\n        Kirigami.SpellCheck.enabled: true\n"
    "        inputMethodHints: Qt.ImhNoPredictiveText | Qt.ImhSensitiveData\n    }",
    "    function f() { input.inputMethodHints = Qt.ImhNone }",
])
def test_proof_input_privacy_rule_catches(snippet):
    assert _input_privacy_problems(_inserted_view(snippet))


def test_proof_input_without_any_editable_is_caught():
    assert _input_privacy_problems(_strip_comments("Item {\n    Text { textFormat: Text.PlainText }\n}\n"))


# P6 (config) lives in the persisted-configuration rules above: both Ollama
# files are in CHAT_CONFIG_READ_ONLY_FILES and chatOllamaUrl joins the key set.

def test_proof_ollama_view_config_write_is_caught():
    view = _inserted_view("    function f() { Plasmoid.configuration.chatOllamaUrl = \"http://127.0.0.1:1\" }")
    config = r"\b[Pp]lasmoid\s*\.\s*configuration(?:\s*\.\s*\w+|\s*\[[^\]]*\])+\s*=(?!=)"
    assert _hits(config, view)


def test_proof_ollama_key_with_a_different_default_is_caught():
    # The config page rule compares the declared literal with this exact text.
    assert OLLAMA_CONFIG_KEYS == {"chatOllamaUrl": ("String", "http://127.0.0.1:11434")}
    page = _strip_comments(
        'property string cfg_chatOllamaUrl: "http://0.0.0.0:11434"\n'
        'property string cfg_chatOllamaUrlDefault: "http://127.0.0.1:11434"\n')
    values = [re.findall(rf"(?m)^\s*property\s+\w+\s+{name}\s*:\s*(.+?)\s*$", page)
              for name in ("cfg_chatOllamaUrl", "cfg_chatOllamaUrlDefault")]
    assert values[0] != ['"http://127.0.0.1:11434"'] and values[1] == ['"http://127.0.0.1:11434"']


# P7 The owner check command is built only by OllamaChat.js; its reply is stdout only.

OWNER_COMMAND = (
    r'"env HEARTHWIRE_RUN="\s*\+\s*\w+\s*\+\s*" HEARTHWIRE_APPLET="\s*\+\s*\w+\s*'
    r'\+\s*" python3 -P -m hearthwire --port-owner "\s*\+\s*\w+'
)
OTHER_HELPER_FLAGS = ("--json", "--providers", "--catalog", "--detect") + HELPER_FLAGS


def _port_owner_flag_problems(sources):
    problems = [
        f"{name}:{line} --port-owner outside OllamaChat.js"
        for name, code in sources.items() if not name.endswith("OllamaChat.js")
        for line in _hits(r"(?<![\w-])--port-owner(?![\w-])", code)
    ]
    for name, code in sources.items():
        if name.endswith("OllamaChat.js"):
            if len(_hits(r"--port-owner", code)) != 1 or len(re.findall(OWNER_COMMAND, code)) != 1:
                problems.append(f"{name}: --port-owner once, as `\"env HEARTHWIRE_RUN=\" + run + "
                                "\" HEARTHWIRE_APPLET=\" + applet + \" python3 -P -m hearthwire --port-owner \" + port`")
            problems += [f"{name}:{line} {flag}" for flag in OTHER_HELPER_FLAGS
                         for line in _hits(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", code)]
        if name.endswith(("OllamaChatView.qml", "LocalOwnerCheck.qml")):
            problems += [f"{name}:{line} stderr" for line in _hits(r"\bstderr\b", code)]
    return problems


def test_port_owner_command_is_built_only_by_ollama_chat_js():
    _require_phased(OLLAMA_CHAT_JS)
    problems = _port_owner_flag_problems(_all_code())
    assert not problems, f"port owner check: {problems}"


@pytest.mark.parametrize("target,old,new", [
    ("js", " python3 -P -m hearthwire --port-owner ", " python3 -P -m hearthwire --port-owner --json "),
    ("js", '" HEARTHWIRE_APPLET=" + applet\n', '""\n'),
    ("js", "--port-owner", "--port-owne"),
])
def test_proof_port_owner_command_rule_catches(target, old, new):
    js = _mutated_source(OLLAMA_CHAT_JS, SAMPLE_OLLAMA_JS, old, new)
    assert _port_owner_flag_problems({"OllamaChat.js": js})


@pytest.mark.parametrize("snippet", [
    '    readonly property string cmd: "python3 -P -m hearthwire --port-owner 11434"',
    '    function f(data) { return data["stderr"] }',
])
def test_proof_port_owner_view_rule_catches(snippet):
    assert _port_owner_flag_problems({"OllamaChatView.qml": _inserted_view(snippet)})


def test_proof_port_owner_flag_in_main_is_caught():
    code = _mutated(MAIN_QML, "    function chatNext() {",
                    "    function x() { return \"python3 -P -m hearthwire --port-owner 1\" }\n    function chatNext() {")
    assert _port_owner_flag_problems({"main.qml": code})


# P8 No storage APIs anywhere; no PUT/DELETE or file: URLs in the Ollama files.

PLASMOID_STORAGE_BANS = {
    "LocalStorage": r"\bLocalStorage\b",
    "openDatabaseSync": r"\bopenDatabaseSync\b",
    "Settings {": r"\bSettings\s*\{",
    "Qt.labs.settings": r"\bQt\s*\.\s*labs\s*\.\s*settings\b",
    "FileIO": r"\bFileIO\b",
}
OLLAMA_FILE_BANS = {
    "PUT/DELETE/PATCH": r"""(?i)["']\s*(?:PUT|DELETE|PATCH)\s*["']""",
    "file: URL": r"(?i)\bfile:",
}


def _ollama_storage_offenders(sources):
    return [
        f"{name}:{line} {rule}"
        for name, code in sources.items()
        for rule, pattern in PLASMOID_STORAGE_BANS.items()
        for line in _hits(pattern, code)
    ] + [
        f"{name}:{line} {rule}"
        for name, code in sources.items() if name.endswith(("OllamaChat.js", "OllamaChatView.qml"))
        for rule, pattern in OLLAMA_FILE_BANS.items()
        for line in _hits(pattern, code)
    ]


def test_plasmoid_never_uses_local_storage_or_settings_files():
    offenders = _ollama_storage_offenders(_all_code())
    assert not offenders, f"forbidden storage in plasmoid/: {offenders}"


@pytest.mark.parametrize("name,snippet", [
    ("main.qml", "import QtQuick.LocalStorage"),
    ("main.qml", "var db = openDatabaseSync(\"x\", \"1\", \"x\", 1)"),
    ("main.qml", "Settings { property string last: \"\" }"),
    ("main.qml", "QtCore.Settings { category: \"x\" }"),
    ("main.qml", "import Qt.labs.settings"),
    ("main.qml", "FileIO { id: f }"),
    ("OllamaChatView.qml", "x.open(\"PUT\", OllamaChat.endpoint(a, \"chat\"))"),
    ("OllamaChat.js", "var LOG = \"file:///tmp/ollama.log\""),
])
def test_proof_storage_rule_catches(name, snippet):
    assert _ollama_storage_offenders({name: _strip_comments(snippet)})


# P9 The test seams are set only by tests.

SEAMS = ("createRequest", "runOwnerCheck")
# The files that declare each seam (once, as `property var <seam>: ...`).
SEAM_OWNERS = {
    "createRequest": ("OllamaChatView.qml",),
    "runOwnerCheck": ("OllamaChatView.qml", "LocalOwnerCheck.qml"),
}


def _seam_problems(sources, view_present):
    problems = []
    for name, code in sources.items():
        for seam in SEAMS:
            problems += [f"{name}:{line} {seam} assigned" for line in _hits(rf"\b{seam}\s*=(?!=)", code)]
            declarations = _hits(rf"(?m)^[ \t]*property\s+var\s+{seam}\s*:", code)
            bindings = _hits(rf"(?<![\w.]){seam}\s*:", code)
            if not name.endswith(SEAM_OWNERS[seam]):
                problems += [f"{name}:{line} {seam} bound" for line in bindings]
            elif bindings != declarations or len(declarations) != 1:
                problems.append(f"{name}: {seam} must be declared once (`property var {seam}: ...`) "
                                "and never bound elsewhere")
    if view_present and not any(name.endswith("OllamaChatView.qml") for name in sources):
        problems.append("OllamaChatView.qml is missing")
    return problems


def test_ollama_test_seams_are_never_set_in_the_plasmoid():
    # Enforced in every phase for the other files; the view's own
    # declarations are checked once it exists.
    sources = _all_code()
    problems = _seam_problems(sources, view_present=OLLAMA_CHAT_VIEW.is_file())
    assert not problems, f"createRequest/runOwnerCheck are for tests only: {problems}"


@pytest.mark.parametrize("name,snippet", [
    ("FullRepresentation.qml", "OllamaChatView { createRequest: function () { return null } }"),
    ("FullRepresentation.qml", "ollamaView.runOwnerCheck = function (c) {}"),
    ("main.qml", "Component.onCompleted: view.createRequest = null"),
    ("ChatWebView.qml", "LocalOwnerCheck { runOwnerCheck: function (c) {} }"),
    ("LocalOwnerCheck.qml", "    property var createRequest: null"),
])
def test_proof_seam_rule_catches_outside_the_view(name, snippet):
    assert _seam_problems({name: _strip_comments(snippet)}, view_present=False)


@pytest.mark.parametrize("snippet", [
    "    property var createRequest: null",
    "    function f() { ollamaView.runOwnerCheck = function (c) {} }",
])
def test_proof_seam_rule_catches_inside_the_view(snippet):
    assert _seam_problems({"OllamaChatView.qml": _inserted_view(snippet)}, view_present=True)


# P10 The port owner helper reads /proc only and prints nothing itself.

NETWORK_MODULES = {
    "socket", "http", "urllib", "subprocess", "ssl", "asyncio", "selectors", "socketserver",
    "ftplib", "smtplib", "imaplib", "poplib", "xmlrpc", "multiprocessing", "ctypes", "importlib",
    "webbrowser", "shutil",
}
PROCESS_CALLS = {"system", "popen", "fork", "forkpty", "posix_spawn", "posix_spawnp"}


def _port_owner_module_problems(source):
    tree = ast.parse(source)
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                problems.append(f"line {node.lineno}: no relative imports")
                continue
            names = [node.module or ""]
        else:
            names = []
        for module in names:
            top = module.split(".")[0]
            if top not in sys.stdlib_module_names or top in NETWORK_MODULES:
                problems.append(f"line {node.lineno}: import {module} is not allowed")
        if isinstance(node, ast.Name) and node.id in {"print", "__import__", "eval", "exec", "open"}:
            problems.append(f"line {node.lineno}: {node.id} is not allowed")
        if isinstance(node, ast.Attribute) and (
                node.attr in PROCESS_CALLS or node.attr.startswith(("exec", "spawn"))
                or node.attr in {"write_text", "write_bytes", "unlink", "mkdir"}):
            problems.append(f"line {node.lineno}: .{node.attr} is not allowed")
    return problems


def _cli_print_problems(source):
    tree = ast.parse(source)
    prints = [node for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print"]
    writes = [node for node in ast.walk(tree)
              if isinstance(node, ast.Attribute) and node.attr in {"stdout", "stderr"}]
    problems = []
    if len(prints) != 1:
        problems.append(f"exactly one print() expected, found {len(prints)}")
    else:
        call = prints[0]
        dumps = call.args[0] if len(call.args) == 1 else None
        if call.keywords or not (isinstance(dumps, ast.Call) and isinstance(dumps.func, ast.Attribute)
                                 and dumps.func.attr == "dumps" and isinstance(dumps.func.value, ast.Name)
                                 and dumps.func.value.id == "json"):
            problems.append("the one print() must be print(json.dumps(payload, ...))")
    if writes:
        problems.append(f"no direct sys.stdout/sys.stderr use (lines {[node.lineno for node in writes]})")
    return problems


def test_port_owner_module_is_stdlib_only_and_offline():
    problems = _port_owner_module_problems(PORT_OWNER_PY.read_text(encoding="utf-8"))
    assert not problems, f"{PORT_OWNER_PY.relative_to(PLASMOID.parent)}: {problems}"


def test_cli_prints_exactly_one_json_object():
    problems = _cli_print_problems(CLI_PY.read_text(encoding="utf-8"))
    assert not problems, f"{CLI_PY.relative_to(PLASMOID.parent)}: {problems}"


@pytest.mark.parametrize("old,new", [
    ("import ipaddress\n", "import ipaddress\nimport socket\n"),
    ("import ipaddress\n", "import ipaddress\nfrom urllib import request\n"),
    ("import ipaddress\n", "import ipaddress\nimport subprocess\n"),
    ("import ipaddress\n", "import ipaddress\nimport http.client\n"),
    ("import ipaddress\n", "import ipaddress\nimport requests\n"),
    ("import ipaddress\n", "import ipaddress\nfrom . import http\n"),
    ("    return frozenset(trusted)\n", "    print(trusted)\n    return frozenset(trusted)\n"),
    ("    return frozenset(trusted)\n", "    os.system(\"ss -ltn\")\n    return frozenset(trusted)\n"),
])
def test_proof_port_owner_module_rule_catches(old, new):
    raw = PORT_OWNER_PY.read_text(encoding="utf-8")
    assert old in raw
    assert _port_owner_module_problems(raw.replace(old, new, 1))


@pytest.mark.parametrize("old,new", [
    ("    return 0\n\n\ndef _helper_reply", "    print(payload)\n    return 0\n\n\ndef _helper_reply"),
    ('print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))', "print(payload)"),
    ("    return 0\n\n\ndef _helper_reply", "    sys.stdout.write(\"\\n\")\n    return 0\n\n\ndef _helper_reply"),
])
def test_proof_cli_print_rule_catches(old, new):
    raw = CLI_PY.read_text(encoding="utf-8")
    assert old in raw
    assert _cli_print_problems(raw.replace(old, new, 1))


# P11 Ollama is not a web site: the ChatSites.js `sites` literal stays the seven web ids.

def _site_ids_problems(source):
    literal = _sites_literal(_strip_comments(source))
    ids = re.findall(r"""[{,]\s*["']?id["']?\s*:\s*["']([^"']+)["']""", literal)
    # Labels may name Ollama (the Local site fronts it); ids may not.
    if ids != EXPECTED_SITE_IDS or "ollama" in ids:
        return [f"site ids must stay {EXPECTED_SITE_IDS}, got {ids}"]
    return []


def test_chat_sites_literal_has_no_ollama_entry():
    problems = _site_ids_problems(CHAT_SITES_JS.read_text(encoding="utf-8"))
    assert not problems, f"{_rel(CHAT_SITES_JS)}: {problems}"


def test_proof_ollama_site_in_chat_sites_is_caught():
    raw = CHAT_SITES_JS.read_text(encoding="utf-8")
    old = "        id: \"local\",\n"
    assert old in raw
    assert _site_ids_problems(raw.replace(old, "        id: \"ollama\",\n", 1))
    blanked = _strip_comments(raw, blank_strings=True)
    end = _sites_literal(raw)
    start = raw.index(end)
    tail = start + len(end) - 1
    assert blanked[tail] == "]"
    added = raw[:tail] + "    { id: \"ollama\", name: \"Ollama\", url: \"http://127.0.0.1:11434\" },\n" + raw[tail:]
    assert _site_ids_problems(added)


# P12 The owner check gates every request. The functions that send, and the
# one that takes the check's result, are reached only along the gate:
# ownerSource.onNewData (parsed stdout) → ownerDone → afterOwnerCheck →
# probeVersion / startChat / unloadModels; checkOwner and checkTimer may end
# a check (fail closed) through afterOwnerCheck too.

OWNER_GATE_CALLERS = {
    "runOwnerCheck": {"checkOwner"},
    "ownerDone": {"ownerSource.onNewData"},
    "afterOwnerCheck": {"checkOwner", "ownerDone", "checkTimer.onTriggered"},
    "probeVersion": {"afterOwnerCheck"},
    "listModels": {"probeVersion"},
    "fetch": {"probeVersion", "listModels"},
    "startChat": {"afterOwnerCheck"},
    "unloadModels": {"afterOwnerCheck"},
}
OWNER_GATE_HANDLERS = (
    ("ownerSource.onNewData", r"(?<![\w.])(?:[A-Za-z_]\w*\s*\.\s*)?DataSource\s*\{", "ownerSource", "onNewData"),
    ("checkTimer.onTriggered", r"(?<![\w.])Timer\s*\{", "checkTimer", "onTriggered"),
)
OWNER_DONE_CALL = (
    r'ollamaView\s*\.\s*ownerDone\s*\(\s*source\s*,\s*OllamaChat\s*\.\s*parseOwnerReply\s*\(\s*'
    r'data\s*\[\s*"exit code"\s*\]\s*,\s*data\s*\[\s*"stdout"\s*\]\s*\)\s*\)'
)
RUN_OWNER_CHECK_DEFAULT = (
    r"(?m)^[ \t]*property\s+var\s+runOwnerCheck\s*:\s*function\s*\(\s*command\s*\)\s*\{\s*"
    r"ownerSource\s*\.\s*connectSource\s*\(\s*command\s*\)\s*;?\s*\}\s*$"
)


def _brace_end(blanked, start):
    """The offset just past the block whose ``{`` is at ``start``."""
    depth = 0
    for index in range(start, len(blanked)):
        if blanked[index] == "{":
            depth += 1
        elif blanked[index] == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return len(blanked)


def _handler_spans(blanked, opener, object_id, handler):
    """Spans of ``handler`` at the top level of each ``opener`` block with ``id: object_id``."""
    spans = []
    for match in re.finditer(opener, blanked):
        start = blanked.find("{", match.end() - 1)
        body = blanked[start:_brace_end(blanked, start)]
        top = _top_level(body)
        if not re.search(rf"(?:^|[\n;])\s*id\s*:\s*{object_id}\s*(?=;|\n|$)", top):
            continue
        for found in re.finditer(rf"\b{handler}\s*:\s*(?:\([^)]*\)\s*=>\s*)?\{{", body):
            if top[found.start()] != " ":
                brace = start + found.end() - 1
                spans.append((brace, _brace_end(blanked, brace)))
    return spans


def _owner_gate_problems(code):
    blanked = _strip_comments(code, blank_strings=True)
    problems = []
    spans = []
    definitions = {}
    for match in re.finditer(r"\bfunction\s+([A-Za-z_]\w*)\s*\([^)]*\)\s*\{", blanked):
        spans.append((match.start(), _brace_end(blanked, match.end() - 1), match.group(1)))
        definitions.setdefault(match.group(1), []).append(match.start(1))
    for label, opener, object_id, handler in OWNER_GATE_HANDLERS:
        found = _handler_spans(blanked, opener, object_id, handler)
        if len(found) != 1:
            problems.append(f"{label}: expected exactly one such handler, found {len(found)}")
        spans += [(start, end, label) for start, end in found]

    def caller(offset):
        around = [span for span in spans if span[0] <= offset < span[1]]
        return min(around, key=lambda span: span[1] - span[0])[2] if around else None

    for name, allowed in OWNER_GATE_CALLERS.items():
        defined = definitions.get(name, [])
        if name != "runOwnerCheck" and len(defined) != 1:
            problems.append(f"`function {name}(` must be defined exactly once, found {len(defined)}")
        calls = 0
        for match in re.finditer(rf"(?<![\w$]){name}(?![\w$])", blanked):
            line = _line_of(code, match.start())
            if match.start() in defined:
                continue
            if name == "runOwnerCheck" and re.search(r"\bproperty\s+var\s+$",
                                                     blanked[blanked.rfind("\n", 0, match.start()) + 1:match.start()]):
                continue
            if not re.match(r"\s*\(", blanked[match.end():]):
                problems.append(f"line {line}: {name} may only be called directly, not passed around")
                continue
            calls += 1
            where = caller(match.start())
            if where not in allowed:
                problems.append(f"line {line}: {name}() called from {where or 'outside any function'}; "
                                f"only from {sorted(allowed)}")
        if calls == 0:
            problems.append(f"{name}() is never called along the gate")
    names = "|".join(OWNER_GATE_CALLERS)
    for line in _hits(rf"""["'`]\s*(?:{names})\s*["'`]""", code):
        problems.append(f"line {line}: a gate function named in a string (indirect call)")
    for start, end in _handler_spans(blanked, *OWNER_GATE_HANDLERS[0][1:]):
        if len(re.findall(OWNER_DONE_CALL, code[start:end])) != 1:
            problems.append("ownerSource.onNewData must call ollamaView.ownerDone(source, "
                            'OllamaChat.parseOwnerReply(data["exit code"], data["stdout"]))')
    if len(_hits(RUN_OWNER_CHECK_DEFAULT, code)) != 1:
        problems.append("runOwnerCheck must default to `function (command) { ownerSource.connectSource(command) }`")
    if len(_hits(r"\bconnectSource\s*\(", blanked)) != 1:
        problems.append("connectSource( only once, in the runOwnerCheck default")
    return problems


def test_owner_check_gates_every_request():
    _require_phased(OLLAMA_CHAT_VIEW)
    problems = _owner_gate_problems(_read_code(OLLAMA_CHAT_VIEW))
    assert not problems, f"{_rel(OLLAMA_CHAT_VIEW)}: {problems}"


@pytest.mark.parametrize(("old", "new"), [
    # A reply that wasn't parsed from the helper's stdout.
    ('ollamaView.ownerDone(source, OllamaChat.parseOwnerReply(data["exit code"], data["stdout"]))',
     'ollamaView.ownerDone(source, { ok: true, owner: "self" })'),
    # ownerDone from anywhere else.
    ("        ollamaView.focusLater()\n    }\n    onSiteEnabledChanged: {",
     "        ollamaView.focusLater()\n        ollamaView.ownerDone(ollamaView.ownerSourceName, null)\n"
     "    }\n    onSiteEnabledChanged: {"),
    # Skipping the check.
    ('        ollamaView.checkOwner("send")\n', '        ollamaView.afterOwnerCheck("send", "")\n'),
    ('        ollamaView.checkOwner("send")\n', "        ollamaView.startChat()\n"),
    ('        ollamaView.checkOwner("load")\n', "        ollamaView.probeVersion()\n"),
    ('            ollamaView.checkOwner("unload")\n', "            ollamaView.unloadModels(names)\n"),
    ("            ollamaView.load()\n    }\n\n    // --- requests",
     "            ollamaView.fetch(\"tags\", function () {})\n    }\n\n    // --- requests"),
    # A check that times out somewhere else must not reach afterOwnerCheck.
    ("        id: checkTimer\n", "        id: ownerTimer\n"),
    # The default seam must run the real helper.
    ("function (command) { ownerSource.connectSource(command) }",
     'function (command) { ollamaView.ownerDone(command, { ok: true, owner: "self" }) }'),
])
def test_proof_owner_gate_rule_catches(old, new):
    assert _owner_gate_problems(_mutated(OLLAMA_CHAT_VIEW, old, new))


@pytest.mark.parametrize("snippet", [
    "    function later() { Qt.callLater(ollamaView.startChat) }",
    "    function later() { ollamaView[\"startChat\"]() }",
    "    function startChat() {}",
    "    function sneak() { ollamaView.unloadModels([\"llama3:latest\"]) }",
    "    Component.onCompleted: ollamaView.probeVersion()",
    "    function again(c) { ownerSource.connectSource(c) }",
])
def test_proof_owner_gate_rule_catches_insertions(snippet):
    assert _owner_gate_problems(_inserted_view(snippet))


# --- security audit 2026-11-02 ---------------------------------------------------------

USAGE_VIEW = UI / "UsageView.qml"
CONFIG_USAGE = UI / "configUsage.qml"
LOCAL_OWNER_CHECK = UI / "LocalOwnerCheck.qml"

# L1 Helper and provider text (names, plans, captions, errors, amounts) is
# shown as plain text only: AutoText would load <img src=...> from a provider
# reply. Every text element in these files either shows one fixed i18n
# literal or sets `textFormat: Text.PlainText`. Kirigami.InlineMessage and
# PlaceholderMessage read their text as rich text and expose no textFormat,
# so their `text:`/`explanation:` may only be fixed literals.

USAGE_TOOLTIP = UI / "UsageTooltip.qml"
HELPER_TEXT_FILES = (USAGE_VIEW, CONFIG_USAGE, FULL_REPRESENTATION, USAGE_TOOLTIP)
MESSAGE_ELEMENT = r"(?<![\w.])(?:[A-Za-z_]\w*\s*\.\s*)?(?:InlineMessage|PlaceholderMessage)\s*\{"
HELPER_TEXT_BANS = {name: RICH_TEXT_BANS[name] for name in (
    "RichText", "StyledText", "MarkdownText", "AutoText", "onLinkActivated", "linkActivated",
    "non-plain textFormat")}


def _literal_binding(top, key):
    return re.search(rf'(?:^|[\n;])\s*{key}\s*:\s*i18n\(\s*"[^"]*"\s*\)\s*(?=;|\n|$)', top)


def _helper_text_problems(code):
    problems = []
    for start, body in _blocks(code, TEXT_ELEMENT):
        top = _top_level(body)
        if not re.search(r"(?:^|[\n;])\s*text\s*:", top) or _literal_binding(top, "text"):
            continue
        if len(re.findall(PLAIN_TEXT_FORMAT, top)) != 1:
            problems.append(f"line {_line_of(code, start)}: text element showing data without "
                            "`textFormat: Text.PlainText`")
    for start, body in _blocks(code, MESSAGE_ELEMENT):
        top = _top_level(body)
        for key in ("text", "explanation"):
            if re.search(rf"(?:^|[\n;])\s*{key}\s*:", top) and not _literal_binding(top, key):
                problems.append(f"line {_line_of(code, start)}: {key} of a message element "
                                "(rich text) must be a fixed i18n literal")
    for name, pattern in HELPER_TEXT_BANS.items():
        lines = _hits(pattern, code)
        if lines:
            problems.append(f"{name} is forbidden (lines {lines})")
    return problems


def _tooltip_format_problems(code):
    if len(_hits(r"(?m)^    toolTipTextFormat\s*:\s*Text\s*\.\s*PlainText\s*$", code)) != 1:
        return ["main.qml must set `toolTipTextFormat: Text.PlainText` once on the PlasmoidItem"]
    return []


@pytest.mark.parametrize("path", HELPER_TEXT_FILES, ids=lambda path: path.name)
def test_helper_text_is_shown_as_plain_text(path):
    code = _read_code(path)
    assert list(_blocks(code, TEXT_ELEMENT)), f"{_rel(path)}: no text elements found"
    problems = _helper_text_problems(code)
    assert not problems, f"{_rel(path)}: {problems}"


def test_tooltip_is_plain_text():
    assert not _tooltip_format_problems(_read_code(MAIN_QML))


@pytest.mark.parametrize(("path", "old", "new"), [
    (USAGE_VIEW, "textFormat: Text.PlainText\n                            text: UsageLogic.shownText(providerSection.modelData.plan)",
     "text: UsageLogic.shownText(providerSection.modelData.plan)"),
    (USAGE_VIEW, "textFormat: Text.PlainText\n                            text: UsageLogic.shownText(providerSection.modelData.plan)",
     "textFormat: Text.StyledText\n                            text: UsageLogic.shownText(providerSection.modelData.plan)"),
    (USAGE_VIEW, "textFormat: Text.PlainText\n                            text: UsageLogic.shownText(providerSection.modelData.display_name)",
     "text: UsageLogic.shownText(providerSection.modelData.display_name)"),
    (USAGE_VIEW, "textFormat: Text.PlainText\n                                wrapMode: Text.Wrap\n"
                 "                                text: usage.failureText(",
     "wrapMode: Text.Wrap\n                                text: usage.failureText("),
    (USAGE_VIEW, "textFormat: Text.PlainText\n                                            text: UsageLogic.shownText(quotaCard.modelData.caption)",
     "text: UsageLogic.shownText(quotaCard.modelData.caption)"),
    (USAGE_VIEW, "textFormat: Text.PlainText\n                                    text: usage.billingValue(",
     "text: usage.billingValue("),
    (USAGE_VIEW, '        text: i18n("Couldn\'t load usage")\n',
     '        text: i18n("Couldn\'t load usage")\n        explanation: root.lastError\n'),
    (USAGE_VIEW, "                    // Like a Kirigami.InlineMessage, whose label reads rich text.\n",
     "                    Kirigami.InlineMessage { text: usage.failureText(providerSection.modelData, 0) }\n"),
    (CONFIG_USAGE, "textFormat: Text.PlainText\n                            text: page.providerStatus(",
     "text: page.providerStatus("),
    (FULL_REPRESENTATION, "textFormat: Text.PlainText\n                    text: siteDelegate.modelData.name",
     "text: siteDelegate.modelData.name"),
    (USAGE_TOOLTIP, "                    textFormat: Text.PlainText\n                    font.bold: true\n",
     "                    font.bold: true\n"),
    (USAGE_TOOLTIP, "                    textFormat: Text.PlainText\n                    font.bold: true\n",
     "                    textFormat: Text.StyledText\n                    font.bold: true\n"),
    (USAGE_TOOLTIP, "                            textFormat: Text.PlainText\n                            opacity: 0.75\n",
     "                            opacity: 0.75\n"),
    (USAGE_TOOLTIP, "                            textFormat: Text.PlainText\n                            horizontalAlignment",
     "                            textFormat: Text.RichText\n                            horizontalAlignment"),
    (USAGE_TOOLTIP, "            textFormat: Text.PlainText\n            text: tip.title\n",
     "            text: tip.title\n"),
])
def test_proof_helper_text_rule_catches(path, old, new):
    assert _helper_text_problems(_mutated(path, old, new))


@pytest.mark.parametrize("new", ["", "    toolTipTextFormat: Text.AutoText\n"])
def test_proof_tooltip_format_rule_catches(new):
    code = _mutated(MAIN_QML, "    toolTipTextFormat: Text.PlainText\n", new)
    assert _tooltip_format_problems(code)


# M2 Local web UI pages on this computer load only after the helper's port
# owner check said self or system: the Local view is created only after a
# good check, every main-frame navigation of a Local page to this computer is
# rejected unless it carries the one-shot pass of a good check for exactly its
# address, and a bad answer passes nothing. LocalOwnerCheck.qml runs the
# check with OllamaChat.ownerCommand (the --port-owner literal stays in
# OllamaChat.js, see P7) and reads stdout only.

NAV_HANDLER = r"\bonNavigationRequested\s*:\s*\(\s*request\s*\)\s*=>\s*\{"
OWNER_FINISHED_HANDLER = (
    r"(?m)^\s*onFinished\s*:\s*\(\s*port\s*,\s*problem\s*\)\s*=>\s*"
    r"chatWeb\s*\.\s*localOwnerFinished\s*\(\s*port\s*,\s*problem\s*\)\s*$"
)


def _function_body(code, name):
    bodies = [body for _, body in _blocks(code, rf"\bfunction\s+{name}\s*\([^)]*\)\s*\{{")]
    return bodies[0] if len(bodies) == 1 else None


def _local_gate_problems(web, check):
    problems = []
    handlers = [body for _, body in _blocks(web, NAV_HANDLER)]
    if len(handlers) != 1:
        return [f"ChatWebView.qml: expected one onNavigationRequested handler, found {len(handlers)}"]
    nav = handlers[0]
    gate = re.search(r"ChatSites\s*\.\s*localOwnerGate\s*\(\s*\{([^}]*)\}\s*\)", nav)
    if len(re.findall(r"\blocalOwnerGate\s*\(", nav)) != 1 or not gate:
        problems.append("onNavigationRequested must call ChatSites.localOwnerGate({...}) once")
    else:
        fields = gate.group(1)
        for field in (r"url\s*:\s*url\b", r"siteId\s*:\s*page\s*\.\s*site\b",
                      r"pass\s*:\s*page\s*\.\s*ownerPass\b", r"customUrls\s*:\s*chatWeb\s*\.\s*customUrls\b"):
            if not re.search(field, fields):
                problems.append(f"localOwnerGate argument needs `{field}`")
        rest = nav[gate.end():]
        check_branch = re.search(r'if\s*\(\s*gate\s*===\s*"check"\s*\)\s*\{\s*request\s*\.\s*reject\s*\(\s*\)\s*'
                                 r'chatWeb\s*\.\s*checkLocalOwner\s*\(\s*page\s*,\s*url\s*,[^;]*?\breturn\b', rest, re.S)
        agent = re.search(r"page\s*\.\s*checkUserAgent\s*\(\s*request\s*\)", rest)
        if not check_branch or not agent or check_branch.start() > agent.start():
            problems.append('a "check" gate must reject the request and run checkLocalOwner(page, url, ...) '
                            "before anything else lets the navigation go on")
        if re.search(r"\.\s*checkUserAgent\s*\(", nav[:gate.start()]):
            problems.append("checkUserAgent must come after the owner gate")
    # The pass is only ever handed out after a good check.
    for match in re.finditer(r"\bownerPass\s*=(?!=)\s*([^\n;]*)", web):
        value = match.group(1).strip()
        if value in ('""', "chatWeb.localCreatePass", "pending.url"):
            continue
        problems.append(f"line {_line_of(web, match.start())}: ownerPass may only be set to \"\", "
                        "chatWeb.localCreatePass or pending.url")
    finished = _function_body(web, "localOwnerFinished")
    if finished is None:
        problems.append("`function localOwnerFinished(` must be defined once")
    else:
        bad = re.search(r'if\s*\(\s*problem\s*!==\s*""\s*\)\s*\{[^{}]*\breturn\b[^{}]*\}', finished)
        grants = [m.start() for m in re.finditer(
            r"\bownerPass\s*=\s*pending\.url|\blocalCreatePass\s*=\s*pending\.url|visitedSites\s*\.\s*append"
            r"|\bview\s*\.\s*url\s*=", finished)]
        if not bad or not grants or min(grants) < bad.end():
            problems.append('localOwnerFinished must return on `if (problem !== "")` before it creates, '
                            "passes or loads anything")
    for match in re.finditer(r"\bownerPass\s*=\s*pending\.url|\blocalCreatePass\s*=(?!=)(?!\s*"")", web):
        if finished is None or web.find(finished) > match.start() or match.start() > web.find(finished) + len(finished):
            problems.append(f"line {_line_of(web, match.start())}: a pass is granted outside localOwnerFinished")
    sync = _function_body(web, "syncViews") or ""
    appends = len(re.findall(r"visitedSites\s*\.\s*append\s*\(", web))
    guarded = re.search(r"ChatSites\s*\.\s*localOwnerPort\s*\([^)]*\)\s*===\s*0\s*\)\s*"
                        r"visitedSites\s*\.\s*append\s*\(", sync)
    if appends != 2 or not guarded or len(re.findall(r"visitedSites\s*\.\s*append\s*\(", sync)) != 1:
        problems.append("visitedSites.append only in syncViews behind `localOwnerPort(...) === 0` "
                        "and in localOwnerFinished")
    if len(_hits(OWNER_FINISHED_HANDLER, web)) != 1 or len(re.findall(r"\blocalOwnerFinished\s*\(", web)) != 2:
        problems.append("localOwnerFinished is reached only from "
                        "`onFinished: (port, problem) => chatWeb.localOwnerFinished(port, problem)`")
    windows = [body for _, body in _blocks(web, r"\bonNewWindowRequested\s*:\s*\(\s*request\s*\)\s*=>\s*\{")]
    if len(windows) != 1 or not re.search(r'verdict\s*===\s*"overlay"\s*&&\s*ChatSites\s*\.\s*localOwnerPort\s*\(',
                                          windows[0]):
        problems.append("onNewWindowRequested must drop Local windows that start on this computer")
    # LocalOwnerCheck.qml
    blanked = _strip_comments(check, blank_strings=True)
    if len(_hits(r"(?m)^[ \t]*property\s+var\s+runOwnerCheck\s*:\s*function\s*\(\s*command\s*\)\s*\{\s*"
                 r"ownerSource\s*\.\s*connectSource\s*\(\s*command\s*\)\s*;?\s*\}\s*$", check)) != 1 \
            or len(_hits(r"\bconnectSource\s*\(", blanked)) != 1:
        problems.append("LocalOwnerCheck.qml: runOwnerCheck must default to "
                        "`function (command) { ownerSource.connectSource(command) }`, the only connectSource")
    if len(re.findall(r'ownerCheck\s*\.\s*ownerDone\s*\(\s*source\s*,\s*OllamaChat\s*\.\s*parseOwnerReply\s*\(\s*'
                      r'data\s*\[\s*"exit code"\s*\]\s*,\s*data\s*\[\s*"stdout"\s*\]\s*\)\s*\)', check)) != 1 \
            or len(re.findall(r"\bownerDone\s*\(", check)) != 2:
        problems.append("LocalOwnerCheck.qml: ownerDone only from onNewData with parseOwnerReply(exit code, stdout)")
    if len(re.findall(r"\bOllamaChat\s*\.\s*ownerCommand\s*\(", check)) != 1:
        problems.append("LocalOwnerCheck.qml: the command comes from OllamaChat.ownerCommand, once")
    good = 0
    for match in re.finditer(r"\bownerCheck\s*\.\s*finished\s*\(([^\n]*)\)\s*$", check, re.M):
        args = match.group(1)
        if re.fullmatch(r"\s*ownerCheck\s*\.\s*port\s*,\s*OllamaChat\s*\.\s*ownerProblem\s*\(\s*reply\s*\)\s*", args):
            good += 1
        elif not re.fullmatch(r'\s*(?:ownerCheck\s*\.\s*)?port\s*,\s*"owner-unknown"\s*', args):
            problems.append(f"LocalOwnerCheck.qml:{_line_of(check, match.start())}: finished() other than "
                            'OllamaChat.ownerProblem(reply) or "owner-unknown"')
    if good != 1 or len(re.findall(r"\bfinished\s*\(", blanked)) != len(re.findall(
            r"\bownerCheck\s*\.\s*finished\s*\(", blanked)) + 1:
        problems.append("LocalOwnerCheck.qml: finished(port, OllamaChat.ownerProblem(reply)) exactly once")
    return problems


def _ollama_owner_problem_problems(js):
    body = _function_body(js, "ownerProblem")
    if body is None:
        return ["OllamaChat.js: `function ownerProblem(` must be defined once"]
    if re.findall(r'return\s+""', body) or len(re.findall(r'""', body)) != 1 \
            or not re.search(r'return\s+trusted\s*\(\s*reply\s*\.\s*owner\s*\)\s*\?\s*""\s*:\s*"owner-unknown"', body):
        return ['OllamaChat.ownerProblem may return "" only through trusted(reply.owner)']
    return []


def test_local_web_ui_loads_only_after_a_good_owner_check():
    problems = _local_gate_problems(_read_code(CHAT_WEB_VIEW), _read_code(LOCAL_OWNER_CHECK))
    problems += _ollama_owner_problem_problems(_read_code(OLLAMA_CHAT_JS))
    assert not problems, problems


LOCAL_GATE_MUTATIONS = [
    (CHAT_WEB_VIEW, 'if (gate === "check") {', "if (false) {"),
    (CHAT_WEB_VIEW, "pass: page.ownerPass", "pass: url"),
    (CHAT_WEB_VIEW, "                    if (gate !== \"skip\")\n                        page.ownerPass = \"\"\n",
     "                    page.ownerPass = url\n"),
    (CHAT_WEB_VIEW, "                    var url = request.url.toString()\n",
     "                    var url = request.url.toString()\n                    page.checkUserAgent(request)\n"),
    (CHAT_WEB_VIEW, '        if (problem !== "") {', '        if (problem === "other") {'),
    (CHAT_WEB_VIEW, "                                           url: home }) === 0)\n",
     "                                           url: home }) >= 0)\n"),
    (CHAT_WEB_VIEW, "onFinished: (port, problem) => chatWeb.localOwnerFinished(port, problem)",
     'onFinished: (port, problem) => chatWeb.localOwnerFinished(port, "")'),
    (CHAT_WEB_VIEW, "    function retryLocalOwner() {\n",
     "    function retryLocalOwner() {\n        chatWeb.localOwnerFinished(chatWeb.localOwnerPort, \"\")\n"),
    (CHAT_WEB_VIEW, "    function retryLocalOwner() {\n",
     "    function retryLocalOwner() {\n        visitedSites.append({ site: \"local\" })\n"),
    (CHAT_WEB_VIEW, "                if (verdict === \"overlay\" && ChatSites.localOwnerPort({",
     "                if (false && ChatSites.localOwnerPort({"),
    (LOCAL_OWNER_CHECK, 'ownerCheck.ownerDone(source, OllamaChat.parseOwnerReply(data["exit code"], data["stdout"]))',
     'ownerCheck.ownerDone(source, { ok: true, owner: "self" })'),
    (LOCAL_OWNER_CHECK, 'ownerCheck.finished(ownerCheck.port, "owner-unknown")', 'ownerCheck.finished(ownerCheck.port, "")'),
    (LOCAL_OWNER_CHECK, "ownerCheck.finished(ownerCheck.port, OllamaChat.ownerProblem(reply))",
     'ownerCheck.finished(ownerCheck.port, "")'),
    (LOCAL_OWNER_CHECK, "function (command) { ownerSource.connectSource(command) }",
     'function (command) { ownerCheck.ownerDone(command, { ok: true, owner: "self" }) }'),
    (LOCAL_OWNER_CHECK, "OllamaChat.ownerCommand(port,", '"python3 -P -m hearthwire --port-owner " + port + ('),
]


@pytest.mark.parametrize(("path", "old", "new"), LOCAL_GATE_MUTATIONS,
                         ids=[f"{path.name}:{index}" for index, (path, _, _) in enumerate(LOCAL_GATE_MUTATIONS)])
def test_proof_local_gate_rule_catches(path, old, new):
    web = _mutated(path, old, new) if path == CHAT_WEB_VIEW else _read_code(CHAT_WEB_VIEW)
    check = _mutated(path, old, new) if path == LOCAL_OWNER_CHECK else _read_code(LOCAL_OWNER_CHECK)
    assert _local_gate_problems(web, check) or _port_owner_flag_problems({"LocalOwnerCheck.qml": check})


def test_proof_local_owner_check_stderr_is_caught():
    check = _mutated(LOCAL_OWNER_CHECK, '            ownerSource.disconnectSource(source)\n',
                     '            ownerSource.disconnectSource(source)\n            var e = data["stderr"]\n')
    assert _port_owner_flag_problems({"LocalOwnerCheck.qml": check})


@pytest.mark.parametrize(("old", "new"), [
    ('return trusted(reply.owner) ? "" : "owner-unknown"', 'return ""'),
    ('    if (reply.owner === "other")\n        return "other"\n', '    if (reply.owner === "other")\n        return ""\n'),
])
def test_proof_owner_problem_rule_catches(old, new):
    assert _ollama_owner_problem_problems(_mutated(OLLAMA_CHAT_JS, old, new))


# L2 A page that left its site shows a persistent notice with the host, as
# plain text, and a way home. The host comes from ChatSites.offSiteHost
# (ASCII only), and is never put into a rich-text message element.

def _off_site_problems(web, view):
    problems = []
    if len(re.findall(r"ChatSites\s*\.\s*offSiteHost\s*\(\s*\{[^}]*url\s*:\s*chatWeb\s*\.\s*activeView\s*\.\s*url"
                      r"\s*\.\s*toString\s*\(\s*\)", web)) != 1:
        problems.append("ChatWebView.offSite must come from ChatSites.offSiteHost({... url: activeView.url})")
    labels = [(start, body) for start, body in _blocks(view, TEXT_ELEMENT) if re.search(r"\binfo\s*\.\s*host\b", body)]
    if not labels:
        problems.append("ChatView.qml: no label shows the off-site host")
    for start, body in labels:
        if len(re.findall(PLAIN_TEXT_FORMAT, _top_level(body))) != 1:
            problems.append(f"ChatView.qml:{_line_of(view, start)}: the off-site host must be PlainText")
    for start, body in _blocks(view, MESSAGE_ELEMENT):
        if re.search(r"\binfo\s*\.\s*host\b|\boffSite\b", body):
            problems.append(f"ChatView.qml:{_line_of(view, start)}: the off-site host in a rich-text message")
    notices = [body for _, body in _blocks(view, r"(?<![\w.])Rectangle\s*\{") if 'objectName: "offSiteNotice"' in body]
    if len(notices) != 1 or not re.search(r"onClicked\s*:\s*chatView\s*\.\s*home\s*\(\s*\)", notices[0]) \
            or not re.search(r"visible\s*:[^\n]*\binfo\s*\.\s*off\s*===\s*true", notices[0]):
        problems.append("ChatView.qml: one offSiteNotice, shown while info.off, with a Back (home) button")
    return problems


def test_off_site_notice_shows_the_host_as_plain_text():
    problems = _off_site_problems(_read_code(CHAT_WEB_VIEW), _read_code(CHAT_VIEW))
    assert not problems, problems


OFF_SITE_LABEL = "                textFormat: Text.PlainText\n                wrapMode: Text.Wrap\n"


@pytest.mark.parametrize(("old", "new"), [
    (OFF_SITE_LABEL, "                wrapMode: Text.Wrap\n"),
    (OFF_SITE_LABEL, "                textFormat: Text.StyledText\n                wrapMode: Text.Wrap\n"),
    ("                onClicked: chatView.home()\n            }\n        }\n    }",
     "                onClicked: {}\n            }\n        }\n    }"),
    ("    Kirigami.InlineMessage {\n        Layout.fillWidth: true\n        visible: !!chatView.web && chatView.web.pendingDownloadName",
     "    Kirigami.InlineMessage { text: offSiteNotice.info.host }\n"
     "    Kirigami.InlineMessage {\n        Layout.fillWidth: true\n        visible: !!chatView.web && chatView.web.pendingDownloadName"),
    ("visible: !!chatView.web && info.off === true", "visible: !!chatView.web"),
])
def test_proof_off_site_rule_catches(old, new):
    assert _off_site_problems(_read_code(CHAT_WEB_VIEW), _mutated(CHAT_VIEW, old, new))


def test_proof_off_site_source_rule_catches():
    web = _mutated(CHAT_WEB_VIEW, "url: chatWeb.activeView.url.toString()\n        })",
                   "url: \"\"\n        })")
    assert _off_site_problems(web, _read_code(CHAT_VIEW))


# L3 Hidden direction and zero-width characters in Ollama replies and in
# download names are shown as visible markers (OllamaChat.revealHidden), and
# Copy copies the marked text that is shown, never the hidden characters.

CODE_BLOCK_PUSH = (r'result\s*\.\s*push\s*\(\s*\{\s*kind\s*:\s*"code"\s*,\s*'
                   r'text\s*:\s*revealHidden\s*\(\s*parts\s*\[\s*index\s*\]\s*\.\s*text\s*\)\s*,')
TEXT_BLOCK_SPANS = r'\bspans\s*\(\s*revealHidden\s*\(\s*block\s*\.\s*lines\s*\.\s*join\s*\(\s*"\\n"\s*\)\s*\)\s*\)'


def _hidden_chars_problems(ollama_view, chat_view, ollama_js):
    problems = []
    # OllamaChat.blocks: code blocks through revealHidden, all other text
    # through textBlocks, whose every block is built by textBlock, whose
    # spans come from revealHidden.
    blocks = _function_body(ollama_js, "blocks") or ""
    if len(re.findall(r"\brevealHidden\s*\(", blocks)) != 1 or len(re.findall(CODE_BLOCK_PUSH, blocks)) != 1:
        problems.append("OllamaChat.blocks must pass every code block through revealHidden")
    if len(re.findall(r"\.\s*push\s*\(", blocks)) != 1 or \
            len(re.findall(r"=\s*result\s*\.\s*concat\s*\(\s*textBlocks\s*\(\s*parts\s*\[\s*index\s*\]\s*\.\s*text\s*\)\s*\)",
                           blocks)) != 1:
        problems.append("OllamaChat.blocks may only add code blocks and textBlocks(parts[index].text)")
    text_blocks = _function_body(ollama_js, "textBlocks") or ""
    pushes = re.findall(r"(\w+)\s*\.\s*push\s*\(([^)\n]*)\)?", text_blocks)
    if not text_blocks or any(target == "result" and not argument.startswith("textBlock(current")
                              for target, argument in pushes) \
            or len(re.findall(r"\bresult\s*\.\s*push\s*\(\s*textBlock\s*\(\s*current\s*\)\s*\)", text_blocks)) != 1 \
            or re.search(r"\bresult\s*(?:\[|=(?!=)|\.\s*(?:concat|unshift|splice)\b)", text_blocks.split("\n", 2)[-1]):
        problems.append("OllamaChat.textBlocks may only add textBlock(current)")
    text_block = _function_body(ollama_js, "textBlock") or ""
    if len(re.findall(TEXT_BLOCK_SPANS, text_block)) != 1 or len(re.findall(r"\bspans\s*:", text_block)) != 1:
        problems.append("OllamaChat.textBlock must build spans from revealHidden(block.lines.join(\"\\n\"))")
    # The view shows only OllamaChat.blocks(message.body).
    if len(re.findall(r"\bOllamaChat\s*\.\s*blocks\s*\(\s*message\s*\.\s*body\s*\)", ollama_view)) != 1 \
            or len(re.findall(r"\bblocks\s*\(", ollama_view)) != 1:
        problems.append("OllamaChatView.qml must show replies through OllamaChat.blocks(message.body) once")
    for match in re.finditer(r"\bcopyText\s*\(([^\n]*)\)\s*$", ollama_view, re.M):
        args = match.group(1).strip()
        if args in ("segment.content", "OllamaChat.revealHidden(message.body)") or args == "text":
            continue
        problems.append(f"OllamaChatView.qml:{_line_of(ollama_view, match.start())}: copyText({args}) "
                        "must copy revealed text")
    if 'objectName: "hiddenCharsNote"' not in ollama_view:
        problems.append("OllamaChatView.qml: a reply with hidden characters needs its note")
    name = _function_body(chat_view, "plainName") or ""
    if not re.search(r"var\s+text\s*=\s*OllamaChat\s*\.\s*revealHidden\s*\(", name):
        problems.append("ChatView.plainName must start with OllamaChat.revealHidden")
    return problems


def test_hidden_characters_are_shown_and_copied_marked():
    problems = _hidden_chars_problems(_read_code(OLLAMA_CHAT_VIEW), _read_code(CHAT_VIEW), _read_code(OLLAMA_CHAT_JS))
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (OLLAMA_CHAT_VIEW, "onClicked: ollamaView.copyText(OllamaChat.revealHidden(message.body))",
     "onClicked: ollamaView.copyText(message.body)"),
    (OLLAMA_CHAT_JS, "text: revealHidden(parts[index].text),", "text: parts[index].text,"),
    (OLLAMA_CHAT_JS, 'spans: spans(revealHidden(block.lines.join("\\n")))', 'spans: spans(block.lines.join("\\n"))'),
    (OLLAMA_CHAT_JS, "result = result.concat(textBlocks(parts[index].text))",
     'result.push({ kind: "paragraph", spans: spans(parts[index].text) })'),
    (OLLAMA_CHAT_JS, "            result.push(textBlock(current))",
     "            result.push(current.kind === \"x\" ? current : textBlock(current))"),
    (OLLAMA_CHAT_JS, "    flush()\n    return result\n}",
     "    flush()\n    result.push({ kind: \"paragraph\", spans: spans(text) })\n    return result\n}"),
    (OLLAMA_CHAT_VIEW, "OllamaChat.blocks(message.body)", "OllamaChat.segments(message.body)"),
    (OLLAMA_CHAT_VIEW, 'objectName: "hiddenCharsNote"', 'objectName: "note"'),
    (CHAT_VIEW, "var text = OllamaChat.revealHidden(String(name || \"\"))", "var text = String(name || \"\")"),
])
def test_proof_hidden_chars_rule_catches(path, old, new):
    sources = [_mutated(item, old, new) if item == path else _read_code(item)
               for item in (OLLAMA_CHAT_VIEW, CHAT_VIEW, OLLAMA_CHAT_JS)]
    assert _hidden_chars_problems(*sources)


# N1 A page never opens the system browser by itself. Qt.openUrlExternally
# appears only in ChatWebView.openExternally (the toolbar's Open in browser,
# for a page of the current site) and ChatWebView.acceptExternal (Open on the
# "Open <host> in your browser?" prompt). Page-driven navigations and windows
# only call askExternal, which keeps one prompt at a time and rate limits.
# Open and Open in browser are reached only from a button click.

def _external_open_problems(sources):
    problems = []
    web_name = _rel(CHAT_WEB_VIEW)
    web = sources.get(web_name, "")
    opens = [(name, match.start()) for name, code in sources.items()
             for match in re.finditer(r"\bopenUrlExternally\b", code)]
    allowed = []
    for function in ("openExternally", "acceptExternal"):
        body = _function_body(web, function)
        if body is None:
            problems.append(f"ChatWebView.qml: `function {function}(` must be defined once")
            continue
        start = web.find(body)
        allowed.append((start, start + len(body)))
        if len(re.findall(r"\bQt\s*\.\s*openUrlExternally\s*\(", body)) != 1:
            problems.append(f"ChatWebView.{function} must call Qt.openUrlExternally once")
    for name, offset in opens:
        if name != web_name or not any(low <= offset < high for low, high in allowed):
            problems.append(f"{name}:{_line_of(sources[name], offset)}: openUrlExternally outside "
                            "ChatWebView.openExternally / acceptExternal")
    opener = _function_body(web, "openExternally") or ""
    if not re.match(r"\{\s*if\s*\(\s*chatWeb\s*\.\s*canOpenExternally\s*\)\s*Qt\s*\.\s*openUrlExternally\s*\(",
                    opener):
        problems.append("ChatWebView.openExternally must open only `if (chatWeb.canOpenExternally)`")
    accept = _function_body(web, "acceptExternal") or ""
    if not re.search(r"chatWeb\s*\.\s*clearExternal\s*\(\s*\)\s*if\s*\(\s*ChatSites\s*\.\s*isHttpsUrl\s*\(\s*url\s*\)"
                     r"\s*\)\s*Qt\s*\.\s*openUrlExternally\s*\(\s*url\s*\)", accept):
        problems.append("ChatWebView.acceptExternal must clear the prompt, then open only an https url")
    ask = _function_body(web, "askExternal") or ""
    if not re.search(r'chatWeb\s*\.\s*externalUrl\s*!==\s*""\s*\|\|\s*now\s*<\s*chatWeb\s*\.\s*externalQuietUntil', ask) \
            or not re.search(r"chatWeb\s*\.\s*externalQuietUntil\s*=\s*now\s*\+\s*chatWeb\s*\.\s*externalPromptGap", ask) \
            or not re.search(r'if\s*\(\s*host\s*===\s*""\s*\)\s*return', ask):
        problems.append("ChatWebView.askExternal must drop requests while one waits, during the quiet time "
                        "and without a host, and start the quiet time")
    clear = _function_body(web, "clearExternal") or ""
    if not re.search(r"chatWeb\s*\.\s*externalQuietUntil\s*=\s*Date\s*\.\s*now\s*\(\s*\)\s*\+\s*"
                     r"chatWeb\s*\.\s*externalPromptGap", clear):
        problems.append("ChatWebView.clearExternal must start the quiet time")
    # The page-driven paths only ask.
    navs = [body for _, body in _blocks(web, NAV_HANDLER)]
    if len(navs) != 1 or not re.search(r'if\s*\(\s*verdict\s*===\s*"external"\s*\)\s*'
                                       r"chatWeb\s*\.\s*askExternal\s*\(\s*request\s*\.\s*url\s*\.\s*toString\s*\(\s*\)\s*\)",
                                       navs[0] if navs else ""):
        problems.append('onNavigationRequested: an "external" verdict must only call chatWeb.askExternal(...)')
    windows = [body for _, body in _blocks(web, r"\bonNewWindowRequested\s*:\s*\(\s*request\s*\)\s*=>\s*\{")]
    if len(windows) != 1 or not re.search(r"request\s*\.\s*userInitiated\s*&&\s*ChatSites\s*\.\s*isHttpsUrl\s*\(\s*url\s*\)"
                                          r"\s*\)\s*chatWeb\s*\.\s*askExternal\s*\(\s*url\s*\)",
                                          windows[0] if windows else ""):
        problems.append("onNewWindowRequested: only a clicked https window may call chatWeb.askExternal(url)")
    # Open and the toolbar button are only ever a click away.
    accepts = [(name, match.start()) for name, code in sources.items()
               for match in re.finditer(r"\bacceptExternal\s*\(", code)]
    view_name = _rel(CHAT_VIEW)
    view = sources.get(view_name, "")
    good_accepts = [(name, offset) for name, offset in accepts
                    if name == view_name and re.match(r"acceptExternal\s*\(\s*\)", view[offset:])
                    and re.search(r"onClicked\s*:\s*chatView\s*\.\s*web\s*\.\s*$", view[:offset].splitlines()[-1] + "")]
    defined = [(name, offset) for name, offset in accepts
               if name == web_name and re.search(r"\bfunction\s+$", web[:offset])]
    if len(good_accepts) != 1 or len(accepts) != len(good_accepts) + len(defined) or len(defined) != 1:
        problems.append("acceptExternal is called only from one `onClicked: chatView.web.acceptExternal()` in ChatView")
    prompts = [body for _, body in _blocks(view, r"(?<![\w.])Rectangle\s*\{") if 'objectName: "externalPrompt"' in body]
    if len(prompts) != 1 or "acceptExternal" not in prompts[0] \
            or not re.search(r"onClicked\s*:\s*chatView\s*\.\s*web\s*\.\s*clearExternal\s*\(\s*\)", prompts[0]):
        problems.append("ChatView.qml: one externalPrompt with Open (acceptExternal) and Cancel (clearExternal)")
    for name, code in sources.items():
        for match in re.finditer(r"\bopenExternally\s*\(", code):
            line = code[:match.end()].splitlines()[-1]
            if re.search(r"\bfunction\s+openExternally\s*\($", line):
                continue
            if name == _rel(FULL_REPRESENTATION) and re.search(r"onClicked\s*:\s*chatView\s*\.\s*openExternally\s*\($", line):
                continue
            body = _function_body(view, "openExternally") or ""
            if name == view_name and re.search(r"chatView\s*\.\s*web\s*\.\s*openExternally\s*\($", line) \
                    and body and view.find(body) <= match.start() < view.find(body) + len(body):
                continue
            problems.append(f"{name}:{_line_of(code, match.start())}: openExternally() outside the toolbar click")
    labels = [(start, body) for start, body in _blocks(view, TEXT_ELEMENT)
              if re.search(r"\bexternal(?:Host|Url)\b|\bexternalPrompt\s*\.\s*host\b", body)]
    if not labels:
        problems.append("ChatView.qml: no label names the host of the browser prompt")
    for start, body in labels:
        if len(re.findall(PLAIN_TEXT_FORMAT, _top_level(body))) != 1:
            problems.append(f"ChatView.qml:{_line_of(view, start)}: the browser prompt host must be PlainText")
    for start, body in _blocks(view, MESSAGE_ELEMENT):
        if re.search(r"\bexternal(?:Host|Url)\b|\bexternalPrompt\b", body):
            problems.append(f"ChatView.qml:{_line_of(view, start)}: the browser prompt in a rich-text message")
    return problems


def test_pages_only_ask_to_open_the_browser():
    problems = _external_open_problems(_all_code())
    assert not problems, problems


EXTERNAL_MUTATIONS = [
    (CHAT_WEB_VIEW, "chatWeb.askExternal(request.url.toString())", "Qt.openUrlExternally(request.url)"),
    (CHAT_WEB_VIEW, "chatWeb.askExternal(url)", "Qt.openUrlExternally(url)"),
    (CHAT_WEB_VIEW, "        chatWeb.externalUrl = url\n    }",
     "        chatWeb.externalUrl = url\n        chatWeb.acceptExternal()\n    }"),
    (CHAT_WEB_VIEW, '        if (chatWeb.externalUrl !== "" || now < chatWeb.externalQuietUntil',
     "        if (now < chatWeb.externalQuietUntil"),
    (CHAT_WEB_VIEW, "        chatWeb.externalQuietUntil = now + chatWeb.externalPromptGap\n", ""),
    (CHAT_WEB_VIEW, '        if (host === "")\n            return\n', ""),
    (CHAT_WEB_VIEW, "        chatWeb.externalQuietUntil = Date.now() + chatWeb.externalPromptGap\n", ""),
    (CHAT_WEB_VIEW, "        if (ChatSites.isHttpsUrl(url))\n            Qt.openUrlExternally(url)",
     "        Qt.openUrlExternally(url)"),
    (CHAT_WEB_VIEW, "        if (chatWeb.canOpenExternally)\n            Qt.openUrlExternally(chatWeb.activeView.url)",
     "        Qt.openUrlExternally(chatWeb.activeView.url)"),
    (CHAT_WEB_VIEW, "        chatWeb.syncViews()\n    }\n\n    Component.onDestruction",
     "        chatWeb.syncViews()\n        chatWeb.acceptExternal()\n    }\n\n    Component.onDestruction"),
    (CHAT_WEB_VIEW, "                         && ChatSites.isHttpsUrl(url))\n                    chatWeb.askExternal(url)",
     "                         && ChatSites.isHttpsUrl(url))\n                    chatWeb.acceptExternal(url)"),
    (CHAT_WEB_VIEW, "                else if (verdict !== \"block\" && request.userInitiated\n",
     "                else if (verdict !== \"block\"\n"),
    (CHAT_VIEW, "onClicked: chatView.web.clearExternal()", "onClicked: chatView.web.acceptExternal()"),
    (CHAT_VIEW, "onClicked: chatView.web.acceptExternal()", "onClicked: {}"),
    (CHAT_VIEW, "        if (chatView.web)\n            chatView.web.openExternally()",
     "        if (chatView.web)\n            chatView.web.openExternally()\n        chatView.web.acceptExternal()"),
    (CHAT_VIEW, "    function focusView() {\n", "    function focusView() {\n        chatView.web.openExternally()\n"),
    (CHAT_VIEW, '                objectName: "externalText"\n                Layout.fillWidth: true\n'
                "                textFormat: Text.PlainText\n",
     '                objectName: "externalText"\n                Layout.fillWidth: true\n'),
    (CHAT_VIEW, "    Kirigami.InlineMessage {\n        Layout.fillWidth: true\n        visible: !!chatView.web && chatView.web.pendingDownloadName",
     "    Kirigami.InlineMessage { text: chatView.web.externalHost }\n"
     "    Kirigami.InlineMessage {\n        Layout.fillWidth: true\n        visible: !!chatView.web && chatView.web.pendingDownloadName"),
    (FULL_REPRESENTATION, "onClicked: chatView.openExternally()", "onClicked: Qt.openUrlExternally(\"https://x.example/\")"),
    (USAGE_VIEW, "import QtQuick\n", "import QtQuick\n// x\n"),
]


@pytest.mark.parametrize(("path", "old", "new"), EXTERNAL_MUTATIONS,
                         ids=[f"{path.name}:{index}" for index, (path, _, _) in enumerate(EXTERNAL_MUTATIONS)])
def test_proof_external_open_rule_catches(path, old, new):
    sources = _all_code()
    sources[_rel(path)] = _mutated(path, old, new)
    if path == USAGE_VIEW:
        # A new browser call anywhere else.
        sources[_rel(path)] += "\nfunction leak(u) { Qt.openUrlExternally(u) }\n"
    assert _external_open_problems(sources)


# N4 A "Send the form again" pass is good for ownerPassLifetime (10 s) only:
# each grant stamps ownerPassExpires, the gate drops an expired pass before
# it is used, and Dismiss, any problem and the timer clear every pass.

def _owner_pass_expiry_problems(web, view):
    problems = []
    if not re.search(r"(?m)^\s*property\s+int\s+ownerPassLifetime\s*:\s*10000\s*$", web):
        problems.append("ChatWebView.qml: `property int ownerPassLifetime: 10000`")
    grants = list(re.finditer(r"\b(\w+)\s*\.\s*ownerPass\s*=\s*(pending\.url|chatWeb\.localCreatePass)\b", web))
    if len(grants) != 2:
        problems.append("ChatWebView.qml: expected two pass grants (pending.url, localCreatePass)")
    for match in grants:
        stamp = rf"\s*{match.group(1)}\s*\.\s*ownerPassExpires\s*=\s*Date\s*\.\s*now\s*\(\s*\)\s*\+\s*chatWeb\s*\.\s*ownerPassLifetime\b"
        if not re.match(stamp, web[match.end():]):
            problems.append(f"line {_line_of(web, match.start())}: a pass grant must be followed by its expiry stamp")
    navs = [body for _, body in _blocks(web, NAV_HANDLER)]
    nav = navs[0] if len(navs) == 1 else ""
    expiry = re.search(r'if\s*\(\s*Date\s*\.\s*now\s*\(\s*\)\s*>=\s*page\s*\.\s*ownerPassExpires\s*\)\s*'
                       r'page\s*\.\s*ownerPass\s*=\s*""', nav)
    gate = re.search(r"\blocalOwnerGate\s*\(", nav)
    if not expiry or not gate or expiry.start() > gate.start():
        problems.append("onNavigationRequested must drop an expired pass before localOwnerGate")
    for function in ("blankLocalViews", "dismissLocalOwner"):
        if not re.search(r"chatWeb\s*\.\s*clearOwnerPasses\s*\(\s*\)", _function_body(web, function) or ""):
            problems.append(f"ChatWebView.{function} must call clearOwnerPasses()")
    clear = _function_body(web, "clearOwnerPasses") or ""
    if not re.search(r'views\s*\[\s*index\s*\]\s*\.\s*ownerPass\s*=\s*""', clear) \
            or not re.search(r'chatWeb\s*\.\s*localCreatePass\s*=\s*""', clear):
        problems.append("ChatWebView.clearOwnerPasses must clear every view's pass and the create pass")
    timers = [body for _, body in _blocks(web, r"(?<![\w.])Timer\s*\{") if "id: ownerPassTimer" in body]
    if len(timers) != 1 or not re.search(r"interval\s*:\s*chatWeb\s*\.\s*ownerPassLifetime", timers[0]) \
            or "clearOwnerPasses" not in timers[0] or "dismissLocalOwner" not in timers[0]:
        problems.append("ChatWebView.qml: ownerPassTimer (ownerPassLifetime) must clear the passes")
    if not re.search(r"ownerPass\s*=\s*pending\s*\.\s*url\s*view\s*\.\s*ownerPassExpires[^\n]*\n\s*ownerPassTimer\s*\.\s*restart\s*\(\s*\)",
                     web):
        problems.append("localOwnerFinished must restart ownerPassTimer with each pass")
    if len(re.findall(r"onTriggered\s*:\s*chatView\s*\.\s*web\s*\.\s*dismissLocalOwner\s*\(\s*\)", view)) != 1 \
            or re.search(r"\blocalOwnerProblem\s*=(?!=)", view):
        problems.append("ChatView.qml: Dismiss must call chatView.web.dismissLocalOwner(), never set the problem")
    return problems


def test_owner_pass_expires_and_ends_on_dismiss():
    problems = _owner_pass_expiry_problems(_read_code(CHAT_WEB_VIEW), _read_code(CHAT_VIEW))
    assert not problems, problems


OWNER_PASS_MUTATIONS = [
    (CHAT_WEB_VIEW, "property int ownerPassLifetime: 10000", "property int ownerPassLifetime: 600000"),
    (CHAT_WEB_VIEW, "        view.ownerPassExpires = Date.now() + chatWeb.ownerPassLifetime\n", ""),
    (CHAT_WEB_VIEW, "                    page.ownerPassExpires = Date.now() + chatWeb.ownerPassLifetime\n", ""),
    (CHAT_WEB_VIEW, "                    if (Date.now() >= page.ownerPassExpires)\n                        page.ownerPass = \"\"\n", ""),
    (CHAT_WEB_VIEW, "    function blankLocalViews() {\n        chatWeb.clearOwnerPasses()\n",
     "    function blankLocalViews() {\n"),
    (CHAT_WEB_VIEW, "    function dismissLocalOwner() {\n        chatWeb.clearOwnerPasses()\n",
     "    function dismissLocalOwner() {\n"),
    (CHAT_WEB_VIEW, "            views[index].ownerPass = \"\"\n", ""),
    (CHAT_WEB_VIEW, "        interval: chatWeb.ownerPassLifetime\n", "        interval: 3600000\n"),
    (CHAT_WEB_VIEW, "        ownerPassTimer.restart()\n", ""),
    (CHAT_VIEW, "onTriggered: chatView.web.dismissLocalOwner()", "onTriggered: chatView.web.localOwnerProblem = \"\""),
]


@pytest.mark.parametrize(("path", "old", "new"), OWNER_PASS_MUTATIONS,
                         ids=[f"{path.name}:{index}" for index, (path, _, _) in enumerate(OWNER_PASS_MUTATIONS)])
def test_proof_owner_pass_rule_catches(path, old, new):
    web = _mutated(path, old, new) if path == CHAT_WEB_VIEW else _read_code(CHAT_WEB_VIEW)
    view = _mutated(path, old, new) if path == CHAT_VIEW else _read_code(CHAT_VIEW)
    assert _owner_pass_expiry_problems(web, view)


# N5 The sign-in window's title always names a host (ChatSites.overlayHost):
# its own, or while it is blank the opener's. It is plain text and never the
# bare, trusted-looking "Sign-in window".

def _overlay_title_problems(web):
    problems = []
    if not re.search(r"ChatSites\s*\.\s*overlayHost\s*\(\s*\{\s*url\s*:\s*chatWeb\s*\.\s*overlayView\s*\.\s*url"
                     r"\s*\.\s*toString\s*\(\s*\)\s*,\s*openerUrl\s*:\s*chatWeb\s*\.\s*overlayView\s*\.\s*openerUrl\s*\}", web):
        problems.append("ChatWebView.overlayTitle must come from ChatSites.overlayHost({url, openerUrl})")
    if len(re.findall(r"chatWeb\s*\.\s*openOverlay\s*\(\s*request\s*,\s*page\s*\.\s*site\s*,\s*"
                      r"page\s*\.\s*url\s*\.\s*toString\s*\(\s*\)\s*\)", web)) != 1:
        problems.append("onNewWindowRequested must hand the opener's address to openOverlay")
    labels = [body for _, body in _blocks(web, TEXT_ELEMENT) if 'objectName: "overlayTitle"' in body]
    if len(labels) != 1:
        return problems + ["ChatWebView.qml: one overlayTitle label"]
    label = labels[0]
    if len(re.findall(PLAIN_TEXT_FORMAT, _top_level(label))) != 1:
        problems.append("the sign-in window title must be PlainText")
    texts = re.findall(r'i18n\s*\(\s*"([^"]*)"', label)
    if not texts or any("%1" not in text and "unknown" not in text for text in texts):
        problems.append(f"every sign-in window title must name a host or say it is unknown: {texts}")
    if re.search(r'i18n\s*\(\s*"Sign-in window"\s*\)', web):
        problems.append('ChatWebView.qml: the bare "Sign-in window" title is gone')
    return problems


def test_sign_in_window_title_names_a_host():
    problems = _overlay_title_problems(_read_code(CHAT_WEB_VIEW))
    assert not problems, problems


@pytest.mark.parametrize(("old", "new"), [
    ('? i18n("Sign-in window: %1", chatWeb.overlayTitle.host)', '? i18n("Sign-in window")'),
    (": i18n(\"Window opened by an unknown page\")", ": i18n(\"Sign-in\")"),
    ("chatWeb.openOverlay(request, page.site, page.url.toString())", "chatWeb.openOverlay(request, page.site, \"\")"),
    ('                    objectName: "overlayTitle"\n                    Layout.fillWidth: true\n'
     "                    textFormat: Text.PlainText\n",
     '                    objectName: "overlayTitle"\n                    Layout.fillWidth: true\n'),
    ("            openerUrl: chatWeb.overlayView.openerUrl\n", "            openerUrl: \"\"\n"),
])
def test_proof_overlay_title_rule_catches(old, new):
    assert _overlay_title_problems(_mutated(CHAT_WEB_VIEW, old, new))


# N2 HIDDEN_CHARS (OllamaChat.js) covers every listed hidden, control and
# format character, keeps tab and line feed, is a /gu expression and
# hexCode names astral code points (codePointAt).

HIDDEN_REQUIRED = [
    (0x0000, 0x0008), (0x000B, 0x001F), (0x007F, 0x009F), (0x00AD, 0x00AD), (0x034F, 0x034F),
    (0x061C, 0x061C), (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180E, 0x180E), (0x200B, 0x200F),
    (0x2028, 0x2029), (0x202A, 0x202E), (0x2060, 0x2064), (0x2066, 0x2069), (0x206A, 0x206F),
    (0x3164, 0x3164), (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF), (0xFFA0, 0xFFA0), (0xFFF9, 0xFFFB),
    (0x1BCA0, 0x1BCA3), (0x1D173, 0x1D17A), (0xE0000, 0xE007F), (0xE0100, 0xE01EF),
]
HIDDEN_KEPT = [0x09, 0x0A, 0x20, 0x41, 0xA0, 0xE9, 0x05D0, 0x0627, 0x2065, 0x1F600, 0x2764]


def _js_class_to_python(parts):
    out = []
    for part in parts:
        text = re.sub(r"\\u\{([0-9a-fA-F]{1,6})\}", lambda m: "\\U" + m.group(1).rjust(8, "0"), part)
        if re.search(r"\\(?![uU])|\\u(?![0-9a-fA-F]{4})|\\U(?![0-9a-fA-F]{8})", text):
            return None
        out.append(text)
    return "[" + "".join(out) + "]"


def _hidden_regex_problems(js):
    problems = []
    ranges = re.search(r"\bvar\s+HIDDEN_RANGES\s*=\s*\[([^\]]*)\]", js)
    built = re.findall(r'\bvar\s+HIDDEN_CHARS\s*=\s*new\s+RegExp\s*\(\s*"\["\s*\+\s*HIDDEN_RANGES\s*\.\s*join\s*\(\s*""\s*\)'
                       r'\s*\+\s*"\]"\s*,\s*"([a-z]*)"\s*\)', js)
    if not ranges or len(built) != 1 or len(re.findall(r"\bHIDDEN_CHARS\s*=", js)) != 1:
        return ['OllamaChat.js: `var HIDDEN_CHARS = new RegExp("[" + HIDDEN_RANGES.join("") + "]", "gu")` once']
    if sorted(built[0]) != ["g", "u"]:
        problems.append(f'HIDDEN_CHARS flags must be "gu", not "{built[0]}"')
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', ranges.group(1))
    # Each JS string "\\u0000-\\u0008" holds the regex text \u0000-\u0008.
    source = _js_class_to_python([part.replace("\\\\", "\\") for part in parts])
    if source is None:
        return problems + ["HIDDEN_RANGES may hold only \\uXXXX and \\u{X} escapes"]
    pattern = re.compile(source)
    for low, high in HIDDEN_REQUIRED:
        missing = [point for point in range(low, high + 1) if not pattern.fullmatch(chr(point))]
        if missing:
            problems.append(f"HIDDEN_CHARS misses U+{missing[0]:04X} (range U+{low:04X}-U+{high:04X})")
    for point in HIDDEN_KEPT:
        if pattern.fullmatch(chr(point)):
            problems.append(f"HIDDEN_CHARS must not mark U+{point:04X}")
    hex_code = _function_body(js, "hexCode") or ""
    if not re.search(r"\bcodePointAt\s*\(\s*0\s*\)", hex_code) or "charCodeAt" in hex_code:
        problems.append("OllamaChat.hexCode must use codePointAt(0)")
    reveal = _function_body(js, "revealHidden") or ""
    if not re.search(r"\.\s*replace\s*\(\s*HIDDEN_CHARS\s*,", reveal):
        problems.append("OllamaChat.revealHidden must replace HIDDEN_CHARS")
    if not re.search(r"return\s+typeof\s+text\s*===\s*\"string\"\s*&&\s*revealHidden\s*\(\s*text\s*\)\s*!==\s*text",
                     _function_body(js, "hasHidden") or ""):
        problems.append("OllamaChat.hasHidden must be `revealHidden(text) !== text`")
    return problems


def test_hidden_chars_regex_covers_every_listed_range():
    problems = _hidden_regex_problems(_read_code(OLLAMA_CHAT_JS))
    assert not problems, problems


@pytest.mark.parametrize(("old", "new"), [
    ('"\\\\u000b-\\\\u001f"', '"\\\\u000b-\\\\u000c"'),            # drops CR and ESC
    ('"\\\\u{e0000}-\\\\u{e007f}", ', ""),                         # drops the tag characters
    ('"\\\\u0000-\\\\u0008"', '"\\\\u0000-\\\\u000a"'),            # marks tab and line feed
    ('"\\\\u00ad", ', ""),
    ('"\\\\u2028\\\\u2029", ', ""),
    ('"\\\\u{e0100}-\\\\u{e01ef}"', '"\\\\u{e0100}-\\\\u{e01e0}"'),
    ('HIDDEN_RANGES.join("") + "]", "gu")', 'HIDDEN_RANGES.join("") + "]", "g")'),
    ("character.codePointAt(0)", "character.charCodeAt(0)"),
    ("return typeof text === \"string\" && revealHidden(text) !== text",
     "return typeof text === \"string\" && text.search(HIDDEN_CHARS) >= 0"),
])
def test_proof_hidden_chars_regex_rule_catches(old, new):
    assert _hidden_regex_problems(_mutated(OLLAMA_CHAT_JS, old, new))


# N3 Every helper the plasmoid starts runs as `python3 -P -m hearthwire`
# (-P: no working folder on the module path), RefreshGate.js included. The
# one exception is InstallInfo.command, which adds -s (no user site) so the
# system package answers --install-info even when an older home-folder copy
# would not: that exact string, once, in that function only.

INSTALL_INFO_LAUNCH = '" python3 -P -s -m hearthwire --install-info"'
INSTALL_INFO_COMMAND = r"\bfunction\s+command\s*\([^)]*\)\s*\{"


def _install_info_launch_spans(name, code):
    """Offsets of the allowed ``-P -s`` launch; problems if it is anywhere else or twice."""
    spans, problems = [], []
    found = [match.start() for match in re.finditer(re.escape(INSTALL_INFO_LAUNCH), code)]
    if _base(name) == INSTALL_INFO_JS.name:
        bodies = _block_spans(code, INSTALL_INFO_COMMAND)
        inside = [start for start in found for low, high in bodies if low <= start < high]
        if len(bodies) != 1 or len(inside) > 1:
            problems.append(f"{name}: one function command(), with {INSTALL_INFO_LAUNCH} at most once")
        else:
            spans = [(start, start + len(INSTALL_INFO_LAUNCH)) for start in inside]
    return spans, problems


def _helper_launch_problems(sources):
    problems = []
    for name, code in sources.items():
        allowed, extra = _install_info_launch_spans(name, code)
        problems += extra
        for match in re.finditer(r"\bpython[0-9.]*\b|-m\s+hearthwire\b|\bhearthwire\s+--", code):
            if any(low <= match.start() < high for low, high in allowed):
                continue
            text = match.group(0)
            if text.startswith("python"):
                if not re.compile(r"python3 -P -m hearthwire(?![\w.])").match(code, match.start()):
                    problems.append(f"{name}:{_line_of(code, match.start())}: helper not started as "
                                    "`python3 -P -m hearthwire`")
            elif text.startswith("-m"):
                if code[max(0, match.start() - len("python3 -P ")):match.start()] != "python3 -P ":
                    problems.append(f"{name}:{_line_of(code, match.start())}: `-m hearthwire` without `python3 -P`")
            elif not code[:match.start()].endswith("python3 -P -m "):
                problems.append(f"{name}:{_line_of(code, match.start())}: hearthwire started without "
                                "`python3 -P -m`")
    return problems


def test_every_helper_launch_uses_python3_dash_p():
    problems = _helper_launch_problems(_all_code())
    assert not problems, problems


REFRESH_GATE_JS = UI / "RefreshGate.js"


@pytest.mark.parametrize(("path", "old", "new"), [
    (REFRESH_GATE_JS, " python3 -P -m hearthwire --json", " python3 -m hearthwire --json"),
    (REFRESH_GATE_JS, " python3 -P -m hearthwire --json", " python3 -P -m hearthwire.cli --json"),
    (UI / "configUsage.qml", '"python3 -P -m hearthwire --detect"', '"python -m hearthwire --detect"'),
    (UI / "configUsage.qml", '"python3 -P -m hearthwire --detect"', '"python3 -I -m hearthwire --detect"'),
    (UI / "configUsage.qml", '"python3 -P -m hearthwire --detect"', '"hearthwire --detect"'),
    (CHAT_STORAGE_JS, ' python3 -P -m hearthwire"', ' /usr/bin/python3 -m hearthwire"'),
    (OLLAMA_CHAT_JS, " python3 -P -m hearthwire --port-owner ", " python3 -m  hearthwire --port-owner "),
    # The -P -s exception: only that exact launch, only --install-info, only in InstallInfo.command.
    (INSTALL_INFO_JS, " python3 -P -s -m hearthwire --install-info", " python3 -s -m hearthwire --install-info"),
    (INSTALL_INFO_JS, " python3 -P -s -m hearthwire --install-info", " python3 -s -P -m hearthwire --install-info"),
    (INSTALL_INFO_JS, " python3 -P -s -m hearthwire --install-info", " python3 -P -s -I -m hearthwire --install-info"),
    (INSTALL_INFO_JS, " python3 -P -s -m hearthwire --install-info", " python3 -P -I -m hearthwire --install-info"),
    (INSTALL_INFO_JS, " python3 -P -s -m hearthwire --install-info", " python3 -P -s -m hearthwire --json"),
    (INSTALL_INFO_JS, " python3 -P -s -m hearthwire --install-info", " python3 -P -s -m hearthwire.cli --install-info"),
    (INSTALL_INFO_JS, " python3 -P -s -m hearthwire --install-info", " python3 -P -s -m hearthwire --install-info --json"),
    (INSTALL_INFO_JS, " python3 -P -s -m hearthwire --install-info", " python3 -P -s  -m hearthwire --install-info"),
    (INSTALL_INFO_JS, "function isShadowed(info) {",
     'function again() { return "env x" + " python3 -P -s -m hearthwire --install-info" }\nfunction isShadowed(info) {'),
    (INSTALL_INFO_JS, '    return "env HEARTHWIRE_RUN="',
     '    var other = " python3 -P -s -m hearthwire --install-info"\n    return "env HEARTHWIRE_RUN="'),
    (CHAT_STORAGE_JS, ' python3 -P -m hearthwire"', ' python3 -P -s -m hearthwire"'),
    (OLLAMA_CHAT_JS, " python3 -P -m hearthwire --port-owner ", " python3 -P -s -m hearthwire --port-owner "),
    (MAIN_QML, "        var command = InstallInfo.command(",
     '        var shadow = " python3 -P -s -m hearthwire --install-info"\n        var command = InstallInfo.command('),
])
def test_proof_helper_launch_rule_catches(path, old, new):
    sources = _all_code()
    sources[_rel(path)] = _mutated(path, old, new)
    assert _helper_launch_problems(sources)


# --- R1: shortcut target, per-site zoom, usage alerts (plan T1.3) ----------------------
#
# R1 adds one chat key (chatSiteZoom) that main.qml writes, a Plasma activation
# handler, and usage alerts through org.kde.notification. The rules below keep
# each of those in its one allowed place.

ALERT_LOGIC_JS = UI / "AlertLogic.js"
NOTIFYRC = PLASMOID.parent / "assets" / "hearthwire.notifyrc"
ZOOM_WRITE = (r"\bPlasmoid\s*\.\s*configuration\s*\.\s*chatSiteZoom\s*"
              r"(?:(?P<op>(?:[-+*/%&|^]|\*\*|<<|>>>?|&&|\|\||\?\?)=|\+\+|--)|(?P<eq>=(?!=)))")
ZOOM_VALUE = re.compile(r"\s*SettingsLogic\s*\.\s*zoomMapToPersist\s*\(")
ZOOM_TIMER_ID = re.compile(r"(?m)^\s*id\s*:\s*zoomWriteTimer\s*$")
TRIGGERED_HANDLER = r"\bonTriggered\s*:\s*(?:function\s*\([^)]*\)\s*|\([^)]*\)\s*=>\s*)?\{"
# Only the two chat views may declare keyboard shortcuts (zoom keys).
KEY_SHORTCUT_FILES = ("ChatView.qml", "OllamaChatView.qml")


def _appended(path, snippet):
    """The real ``path`` with ``snippet`` inserted before its root item's closing brace."""
    raw = path.read_text(encoding="utf-8")
    cut = raw.rindex("}")
    return _strip_comments(raw[:cut] + snippet + raw[cut:])


def _main_and_others(sources):
    main = sources.get(_rel(MAIN_QML), "")
    others = {name: code for name, code in sources.items() if name != _rel(MAIN_QML)}
    return main, others


def _zoom_timer_handler_spans(code):
    spans = []
    for start, end in _block_spans(code, r"\bTimer\s*\{"):
        body = code[start:end]
        if ZOOM_TIMER_ID.search(body):
            spans += [(start + s, start + e) for s, e in _block_spans(body, TRIGGERED_HANDLER)]
    return spans


# S1: a settings page that is open while main.qml stores a zoom takes the new
# value, so Apply cannot write an old map back. This exact sync is the only
# assignment to cfg_chatSiteZoom a page may make.
CONFIG_CONNECTIONS_TARGET = re.compile(r"(?m)^\s*target\s*:\s*Plasmoid\s*\.\s*configuration\s*$")
VALUE_CHANGED_HANDLER = r"\bfunction\s+onValueChanged\s*\(\s*key\s*,\s*value\s*\)\s*\{"
ZOOM_SYNC = re.compile(r'\bif\s*\(\s*key\s*===\s*"chatSiteZoom"\s*\)\s*'
                       r"(page\s*\.\s*cfg_chatSiteZoom\s*=\s*value)[ \t]*(?=\n|\}|$)")


def _zoom_sync_offsets(code):
    """Offsets of the allowed `page.cfg_chatSiteZoom = value` syncs in ``code``."""
    offsets = []
    for start, end in _block_spans(code, r"\bConnections\s*\{"):
        if not CONFIG_CONNECTIONS_TARGET.search(code, start, end):
            continue
        for h_start, h_end in _block_spans(code[start:end], VALUE_CHANGED_HANDLER):
            for match in ZOOM_SYNC.finditer(code, start + h_start, start + h_end):
                offsets.append(match.start(1))
    return offsets


def _zoom_sync_problems(code):
    """A page declaring cfg_chatSiteZoom syncs it exactly once, in the S1 form."""
    if not re.search(r"(?m)^\s*property\s+\w+\s+cfg_chatSiteZoom\s*:", code):
        return []
    offsets = _zoom_sync_offsets(code)
    return [] if len(offsets) == 1 else [f"want one S1 chatSiteZoom sync, got {len(offsets)}"]


def _zoom_write_problems(sources):
    """chatSiteZoom is written once, in main.qml's zoomWriteTimer handler, as `= SettingsLogic.zoomMapToPersist(`.

    Pages may only take the stored value back in the S1 sync (``_zoom_sync_offsets``).
    """
    main, others = _main_and_others(sources)
    problems = []
    for name, code in others.items():
        allowed = set(_zoom_sync_offsets(code))
        problems += [f"{name}:{line} writes chatSiteZoom"
                     for line in _hits(r"\bconfiguration\s*(?:\.\s*chatSiteZoom|\[[^\]]*chatSiteZoom[^\]]*\])"
                                       r"\s*(?:[-+*/%&|^]|\?\?)?=(?!=)", code)]
        problems += [f"{name}:{_line_of(code, match.start())} assigns cfg_chatSiteZoom outside the S1 sync"
                     for match in re.finditer(r"(?:\bpage\s*\.\s*)?\bcfg_chatSiteZoom\s*"
                                              r"(?:[-+*/%&|^]|\?\?)?=(?!=)|\bcfg_chatSiteZoom\s*(?:\+\+|--)", code)
                     if match.start() not in allowed]
    handlers = _zoom_timer_handler_spans(main)
    writes = list(re.finditer(ZOOM_WRITE, main))
    if len(writes) != 1:
        problems.append(f"main.qml: want exactly one chatSiteZoom write, got {len(writes)}")
    for match in writes:
        line = _line_of(main, match.start())
        if match.group("op") or not ZOOM_VALUE.match(main, match.end()):
            problems.append(f"main.qml:{line}: chatSiteZoom must be written as `= SettingsLogic.zoomMapToPersist(`")
        if not any(start <= match.start() < end for start, end in handlers):
            problems.append(f"main.qml:{line}: chatSiteZoom written outside the zoomWriteTimer onTriggered handler")
    return problems


def test_chat_site_zoom_is_written_only_by_the_zoom_write_timer():
    problems = _zoom_write_problems(_all_code())
    assert not problems, problems


ZOOM_WRITE_LINE = "Plasmoid.configuration.chatSiteZoom = SettingsLogic.zoomMapToPersist("


@pytest.mark.parametrize(("old", "new"), [
    (ZOOM_WRITE_LINE, "Plasmoid.configuration.chatSiteZoom = JSON.stringify("),
    (ZOOM_WRITE_LINE, "Plasmoid.configuration.chatSiteZoom += SettingsLogic.zoomMapToPersist("),
    (ZOOM_WRITE_LINE, "void (SettingsLogic.zoomMapToPersist("),
    ("id: zoomWriteTimer", "id: otherTimer"),
])
def test_proof_zoom_write_rule_catches(old, new):
    sources = _all_code()
    sources[_rel(MAIN_QML)] = _mutated(MAIN_QML, old, new)
    assert _zoom_write_problems(sources)


def test_proof_zoom_write_outside_the_timer_is_caught():
    sources = _all_code()
    sources[_rel(MAIN_QML)] = _mutated(
        MAIN_QML, "    function chatNext() {",
        "    function chatNext() {\n        Plasmoid.configuration.chatSiteZoom = SettingsLogic.zoomMapToPersist({}, \"x\", 1)",
    )
    assert _zoom_write_problems(sources)


@pytest.mark.parametrize(("path", "snippet"), [
    (CHAT_VIEW, "    function z() { Plasmoid.configuration.chatSiteZoom = \"{}\" }\n"),
    (CHAT_VIEW, "    function z() { Plasmoid.configuration[\"chatSiteZoom\"] = \"{}\" }\n"),
    (CONFIG_PAGES[0], "    function z() { cfg_chatSiteZoom = \"{}\" }\n"),
    *[(page, "    function z() { page.cfg_chatSiteZoom = \"{}\" }\n") for page in CONFIG_PAGES],
    (CONFIG_PAGES[1], "    Component.onCompleted: page.cfg_chatSiteZoom = value\n"),
])
def test_proof_zoom_write_in_another_file_is_caught(path, snippet):
    sources = _all_code()
    sources[_rel(path)] = _appended(path, snippet)
    assert _zoom_write_problems(sources)


def _activation_problems(sources):
    """`activationTogglesExpanded: false` once, in main.qml, and the name nowhere else."""
    main, others = _main_and_others(sources)
    problems = [f"{name}:{line}" for name, code in others.items()
                for line in _hits(r"\bactivationTogglesExpanded\b", code)]
    every = _hits(r"\bactivationTogglesExpanded\b", main)
    wanted = _hits(r"(?m)^\s*activationTogglesExpanded\s*:\s*false\s*$", main)
    if len(every) != 1 or len(wanted) != 1:
        problems.append(f"main.qml: want `activationTogglesExpanded: false` exactly once, got lines {every}")
    return problems


def test_activation_toggles_expanded_is_off_once_in_main():
    problems = _activation_problems(_all_code())
    assert not problems, problems


@pytest.mark.parametrize(("old", "new"), [
    ("activationTogglesExpanded: false", "activationTogglesExpanded: true"),
    ("activationTogglesExpanded: false", "activationTogglesExpanded: !false"),
    ("activationTogglesExpanded: false", "activationTogglesExpanded: false\n    activationTogglesExpanded: false"),
    ("activationTogglesExpanded: false", "id: notIt"),
])
def test_proof_activation_rule_catches(old, new):
    sources = _all_code()
    sources[_rel(MAIN_QML)] = _mutated(MAIN_QML, old, new)
    assert _activation_problems(sources)


def test_proof_activation_flag_elsewhere_is_caught():
    sources = _all_code()
    sources[_rel(FULL_REPRESENTATION)] = _appended(
        FULL_REPRESENTATION, "    function f() { Plasmoid.activationTogglesExpanded = true }\n")
    assert _activation_problems(sources)


def _notification_import_problems(sources):
    """org.kde.notification (and Notification items) only in main.qml, imported once."""
    main, others = _main_and_others(sources)
    problems = [
        f"{name}:{line}"
        for name, code in others.items()
        for pattern in (r"\borg\s*\.\s*kde\s*\.\s*notification\b", r"\bNotification\s*\{")
        for line in _hits(pattern, code)
    ]
    imports = _hits(r"(?m)^\s*import\s+org\.kde\.notification\b", main)
    if len(imports) != 1:
        problems.append(f"main.qml: want one `import org.kde.notification`, got lines {imports}")
    return problems


def test_notifications_are_imported_only_by_main():
    problems = _notification_import_problems(_all_code())
    assert not problems, problems


@pytest.mark.parametrize("path", [FULL_REPRESENTATION, CHAT_VIEW, UI / "UsageView.qml"], ids=lambda p: p.name)
def test_proof_notification_import_elsewhere_is_caught(path):
    sources = _all_code()
    sources[_rel(path)] = _mutated(path, "import QtQuick\n", "import QtQuick\nimport org.kde.notification\n")
    assert _notification_import_problems(sources)


def test_proof_missing_notification_import_is_caught():
    sources = _all_code()
    sources[_rel(MAIN_QML)] = re.sub(r"(?m)^\s*import\s+org\.kde\.notification\b.*$", "", sources[_rel(MAIN_QML)])
    assert _notification_import_problems(sources)


def _call_spans(code, opener):
    """(start, end) of each parenthesized argument list whose ``opener`` regex ends at "("."""
    blanked = _strip_comments(code, blank_strings=True)
    spans = []
    for match in re.finditer(opener, blanked):
        depth = 0
        for index in range(match.end() - 1, len(blanked)):
            if blanked[index] == "(":
                depth += 1
            elif blanked[index] == ")":
                depth -= 1
                if depth == 0:
                    spans.append((match.end(), index))
                    break
    return spans


def _expression_end(blanked, start):
    """End of the expression at ``start``: a depth-0 comma, semicolon, newline or closing bracket."""
    depth = 0
    for index in range(start, len(blanked)):
        char = blanked[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                return index
            depth -= 1
        elif depth == 0 and char in ",;\n":
            return index
    return len(blanked)


def _only_i18n(blanked, start, end):
    """``blanked[start:end]`` is `i18n(...)` or `cond ? <only_i18n> : <only_i18n>`."""
    while start < end and blanked[start].isspace():
        start += 1
    while end > start and blanked[end - 1].isspace():
        end -= 1
    depth, question, pending = 0, None, 0
    for index in range(start, end):
        char = blanked[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif depth == 0 and char == "?":
            question = index if question is None else question
            pending += 1
        elif depth == 0 and char == ":" and pending:
            pending -= 1
            if pending == 0:   # the ":" of the outermost ternary; the condition may be anything
                return _only_i18n(blanked, question + 1, index) and _only_i18n(blanked, index + 1, end)
    call = re.compile(r"i18n\s*\(").match(blanked, start)
    if not call:
        return False
    depth = 0
    for index in range(call.end() - 1, end):
        depth += blanked[index] == "("
        depth -= blanked[index] == ")"
        if depth == 0:
            return index == end - 1   # the call's own ")" ends the expression: nothing appended
    return False


def _notification_text_problems(code):
    """Notification title/text come only from i18n(, in items, createObject maps and assignments."""
    blanked = _strip_comments(code, blank_strings=True)
    problems = []
    places = [(start, end, r"(?m)(?:^|[{;])\s*(title|text)\s*:") for start, end
              in _block_spans(code, r"\bNotification\s*\{")]
    places += [(start, end, r"\b(title|text)\s*:") for start, end in _call_spans(code, r"\.\s*createObject\s*\(")]
    places += [(0, len(code), r"\.\s*(title|text)\s*=(?!=)")]
    for start, end, pattern in places:
        for match in re.compile(pattern).finditer(blanked, start, end):
            if not _only_i18n(blanked, match.end(), _expression_end(blanked, match.end())):
                problems.append(f"main.qml:{_line_of(code, match.start())}: {match.group(1)} not only from i18n(")
    return problems


def test_notification_title_and_text_come_only_from_i18n():
    code = _read_code(MAIN_QML)
    assert _block_spans(code, r"\bNotification\s*\{"), f"{_rel(MAIN_QML)} declares no Notification item"
    problems = _notification_text_problems(code)
    assert not problems, problems


@pytest.mark.parametrize("snippet", [
    "Notification {\n    title: i18n(\"%1 is running low\", name)\n    text: i18n(\"%1: %2% left\", m, n)\n}",
    "Notification { title: i18n(\"a\"); text: i18n(\"b (%1)\", f(x, [1, 2])) }",
    "function f(c, a) { c.createObject(root, {eventId: \"usageLow\", title: a.low ? i18n(\"x\") : i18n(\"y\"),"
    " text: i18n(\"%1\", a.left)}) }",
    "function f(n, a) { n.text = a.x ? i18n(\"x\") : a.y ? i18n(\"y\") : i18n(\"z\"); n.sendEvent() }",
])
def test_notification_text_rule_accepts_i18n_forms(snippet):
    assert _notification_text_problems(_strip_comments(snippet)) == []


@pytest.mark.parametrize("snippet", [
    "Notification { title: alert.name; text: i18n(\"x\") }",
    "Notification { title: i18n(\"x\"); text: alert.metric }",
    "Notification {\n        text: \"%1 left\".arg(n)\n    }",
    "function f(c, a) { c.createObject(root, {title: a.name, text: i18n(\"x\")}) }",
    "function f(c, a) { c.createObject(root, {title: i18n(\"x\"), text: a.metric}) }",
    "function f(n, a) { n.title = a.name }",
    "function f(n, a) { n.text = i18nd(\"x\", a) }",
    "function f(n, a) { n.text = a.low ? i18n(\"x\") : a.name }",
    "function f(n, a) { n.title = i18n(\"x\") + a.name }",
    "function f(c, a) { c.createObject(root, {title: a.low ? a.name : i18n(\"x\")}) }",
])
def test_proof_notification_text_rule_catches(snippet):
    code = _mutated(MAIN_QML, "    function chatNext() {", f"    {snippet}\n    function chatNext() {{")
    assert _notification_text_problems(code)


NOTIFICATION_BANNED = {
    "NotificationAction": r"\bNotification(?:Reply)?Action\b",
    "urls": r"\burls\s*:|\.\s*urls\s*=(?!=)",
}
NOTIFICATION_BLOCK_BANNED = r"(?m)(?:^|[{;])\s*(?:actions|defaultAction|replyAction)\s*:"


def _notification_extra_problems(sources):
    """No `urls:` and no actions: an alert is text only, nothing to click or open."""
    main, _ = _main_and_others(sources)
    problems = [
        f"{name}:{line} {word}"
        for name, code in sources.items()
        for word, pattern in NOTIFICATION_BANNED.items()
        if word == "NotificationAction" or "org.kde.notification" in code or name == _rel(MAIN_QML)
        for line in _hits(pattern, code)
    ]
    for start, end in _block_spans(main, r"\bNotification\s*\{"):
        for match in re.compile(NOTIFICATION_BLOCK_BANNED).finditer(main, start, end):
            problems.append(f"main.qml:{_line_of(main, match.start())} notification action")
    return problems


def test_notifications_have_no_urls_or_actions():
    problems = _notification_extra_problems(_all_code())
    assert not problems, problems


@pytest.mark.parametrize(("target", "snippet"), [
    (MAIN_QML, "    function f(c) { c.createObject(root, {urls: [\"file:///tmp\"]}) }\n"),
    (MAIN_QML, "    function f(n) { n.urls = [] }\n"),
    (MAIN_QML, "    NotificationAction { text: i18n(\"Open\") }\n"),
    (MAIN_QML, "    Notification { actions: [] }\n"),
    (MAIN_QML, "    Notification {\n        defaultAction: null\n    }\n"),
    (CHAT_VIEW, "    property var a: NotificationAction {}\n"),
])
def test_proof_notification_extra_rule_catches(target, snippet):
    sources = _all_code()
    sources[_rel(target)] = _appended(target, snippet)
    assert _notification_extra_problems(sources)


def _notifyrc_events():
    text = NOTIFYRC.read_text(encoding="utf-8")
    return set(re.findall(r"(?m)^\[Event/(\w+)\]\s*$", text))


def test_alerts_use_the_installed_notifyrc_events():
    code = _read_code(MAIN_QML)
    components = re.findall(r"\bcomponentName\s*[:=]\s*([^;\n,}]+)", code)
    assert components and all(value.strip() == '"hearthwire"' for value in components), (
        f"{_rel(MAIN_QML)}: componentName must be \"hearthwire\" (assets/hearthwire.notifyrc), got {components}"
    )
    used = set(re.findall(r'"(usage[A-Z]\w*)"', code))
    assert used == _notifyrc_events() == {"usageLow", "usageReset"}, (
        f"{_rel(MAIN_QML)} event ids {sorted(used)} must match assets/hearthwire.notifyrc {sorted(_notifyrc_events())}"
    )


ALERT_LOGIC_FORBIDDEN = {
    "import": r"(?m)^\s*\.?import\b",
    "Qt.": r"\bQt\s*\.",
    "console": r"\bconsole\b",
    "XMLHttpRequest": r"\bXMLHttpRequest\b",
    "Plasmoid": r"\bPlasmoid\b",
}


def _alert_logic_problems(code):
    problems = [] if re.match(r"\s*\.pragma\s+library\b", code) else ["must start with .pragma library"]
    return problems + [f"{word} at line {line}" for word, pattern in ALERT_LOGIC_FORBIDDEN.items()
                       for line in _hits(pattern, code)]


def test_alert_logic_js_is_a_pure_library():
    problems = _alert_logic_problems(_read_code(ALERT_LOGIC_JS))
    assert not problems, f"{_rel(ALERT_LOGIC_JS)}: {problems}"


@pytest.mark.parametrize("snippet", [
    '.import "SnapshotLogic.js" as SnapshotLogic',
    "function f() { return Qt.formatDateTime(new Date()) }",
    "function f() { console.log(1) }",
    "function f() { return new XMLHttpRequest() }",
    "function f() { return Plasmoid.configuration }",
])
def test_proof_alert_logic_rule_catches(snippet):
    assert _alert_logic_problems(_read_code(ALERT_LOGIC_JS) + "\n" + snippet + "\n")


def test_proof_alert_logic_needs_pragma():
    code = re.sub(r"^\s*\.pragma\s+library\b", "", _read_code(ALERT_LOGIC_JS), count=1)
    assert _alert_logic_problems(code)


def _key_shortcut_offenders(sources):
    """Shortcut items and StandardKey only in the two chat views."""
    return [
        f"{name}:{line}"
        for name, code in sources.items() if Path(name).name not in KEY_SHORTCUT_FILES
        for pattern in (r"\bShortcut\s*\{", r"\bStandardKey\b")
        for line in _hits(pattern, code)
    ]


def test_keyboard_shortcuts_live_only_in_the_chat_views():
    offenders = _key_shortcut_offenders(_all_code())
    assert not offenders, f"Shortcut/StandardKey only in {KEY_SHORTCUT_FILES}: {offenders}"


@pytest.mark.parametrize(("target", "snippet"), [
    (MAIN_QML, "    Shortcut { sequence: \"Ctrl+0\" }\n"),
    (FULL_REPRESENTATION, "    Shortcut {\n        sequences: [StandardKey.ZoomIn]\n    }\n"),
    (CHAT_WEB_VIEW, "    property var k: StandardKey.ZoomOut\n"),
    (UI / "configGeneral.qml", "    function f() { return Qt.createQmlObject(\"Shortcut { }\", page) }\n"),
])
def test_proof_key_shortcut_rule_catches(target, snippet):
    sources = _all_code()
    sources[_rel(target)] = _appended(target, snippet)
    assert _key_shortcut_offenders(sources)


ZOOM_SYNC_TEXT = 'else if (key === "chatSiteZoom")\n                page.cfg_chatSiteZoom = value'


@pytest.mark.parametrize("page", CONFIG_PAGES, ids=lambda path: path.name)
def test_config_pages_take_the_stored_zoom_back(page):
    problems = _zoom_sync_problems(_read_code(page))
    assert not problems, f"{_rel(page)}: {problems}"


@pytest.mark.parametrize("page", CONFIG_PAGES, ids=lambda path: path.name)
@pytest.mark.parametrize("new", [
    "",                                                                         # sync removed
    'else if (key === "chatSiteZoom")\n                page.cfg_chatSiteZoom = "{}"',
    'else if (key === "chatSiteZoom")\n                page.cfg_chatSiteZoom = value + ""',
    'else if (key === "chatProfileGeneration")\n                page.cfg_chatSiteZoom = value',
    'else if (key === "chatSiteZoom")\n                page.cfg_chatSiteZoom = value\n'
    '            if (key === "chatSiteZoom")\n                page.cfg_chatSiteZoom = value',
], ids=["removed", "literal", "appended", "other-key", "twice"])
def test_proof_zoom_sync_rule_catches(page, new):
    code = _mutated(page, ZOOM_SYNC_TEXT, new)
    sources = _all_code()
    sources[_rel(page)] = code
    assert _zoom_sync_problems(code) or _zoom_write_problems(sources)


def test_proof_zoom_sync_outside_the_config_connections_is_caught():
    page = CONFIG_PAGES[0]
    code = _mutated(page, "target: Plasmoid.configuration\n", "target: page\n")
    assert _zoom_sync_problems(code)


# S3: the alert Notification gets catalog names and a clamped whole number
# only, never helper or site text. Its title/text are i18n( (rule above).
ALERT_ARGUMENTS = {
    "reset": re.compile(r'alert\s*\.\s*kind\s*===\s*"reset"'),
    "providerName": re.compile(r"descriptor\s*\.\s*display_name"),
    "metricName": re.compile(r"root\s*\.\s*markupSafe\s*\(\s*metric\s*\.\s*title\s*\)"),
}
# percentLeft: a Math.* expression over alert.left and number literals.
PERCENT_LEFT_WORDS = {"Math", "max", "min", "round", "floor", "ceil", "trunc", "Number", "alert", "left"}


def _object_entries(blanked, start, end):
    """(key, value start, value end) for each top-level entry of the object literal in blanked[start:end]."""
    open_brace = blanked.find("{", start, end)
    if open_brace == -1 or blanked[start:open_brace].strip(" \t\n,") != "root":
        return None
    entries, depth, entry_start = [], 0, open_brace + 1
    for index in range(open_brace + 1, end):
        char = blanked[index]
        if char in "([{":
            depth += 1
        elif char in ")]}" and depth:
            depth -= 1
        elif depth == 0 and char in ",}":
            text = blanked[entry_start:index]
            if text.strip():
                match = re.match(r"\s*(\w+)\s*:", text)
                if not match:
                    return None
                entries.append((match.group(1), entry_start + match.end(), index))
            entry_start = index + 1
            if char == "}":
                if blanked[index + 1:end].strip():
                    return None
                return entries
    return None


def _alert_argument_problems(code):
    blanked = _strip_comments(code, blank_strings=True)
    calls = _call_spans(code, r"\balertNotification\s*\.\s*createObject\s*\(")
    if len(calls) != 1:
        return [f"want one alertNotification.createObject call, got {len(calls)}"]
    entries = _object_entries(blanked, *calls[0])
    if entries is None:
        return ["alertNotification.createObject must be (root, { ... }) with plain key: value entries"]
    problems = []
    keys = [key for key, _, _ in entries]
    if sorted(keys) != sorted([*ALERT_ARGUMENTS, "percentLeft"]):
        problems.append(f"keys must be exactly {sorted([*ALERT_ARGUMENTS, 'percentLeft'])}, got {keys}")
    for key, start, end in entries:
        value = code[start:end].strip()
        if key in ALERT_ARGUMENTS and not ALERT_ARGUMENTS[key].fullmatch(value):
            problems.append(f"{key}: {value!r}")
        elif key == "percentLeft":
            words = set(re.findall(r"[A-Za-z_]\w*", value))
            if (not re.match(r"Math\s*\.\s*\w+\s*\(", value) or not words <= PERCENT_LEFT_WORDS
                    or re.search(r"[\"'`]", value)):
                problems.append(f"percentLeft must be a Math.* expression over alert.left: {value!r}")
    return problems


def test_alert_notification_arguments_are_pinned():
    problems = _alert_argument_problems(_read_code(MAIN_QML))
    assert not problems, f"{_rel(MAIN_QML)}: {problems}"


@pytest.mark.parametrize(("old", "new"), [
    ("providerName: descriptor.display_name", "providerName: root.lastError"),
    ("providerName: descriptor.display_name", "providerName: descriptor.display_name + root.lastError"),
    ("metricName: root.markupSafe(metric.title)", "metricName: metric.title"),
    ("metricName: root.markupSafe(metric.title)", "metricName: root.markupSafe(root.lastError)"),
    ('reset: alert.kind === "reset"', "reset: true"),
    ("percentLeft: Math.max(", "percentLeft: root.lastError, x: Math.max("),
    ("percentLeft: Math.max(0, Math.min(100, Math.round(Number(alert.left) || 0)))", "percentLeft: alert.left"),
    ("percentLeft: Math.max(0, Math.min(100, Math.round(Number(alert.left) || 0)))",
     "percentLeft: Math.round(root.lastError.length)"),
    ("percentLeft: Math.max(0, Math.min(100, Math.round(Number(alert.left) || 0)))",
     'percentLeft: Math.round(Number(alert.left) || "x")'),
    ('reset: alert.kind === "reset",', 'reset: alert.kind === "reset",\n            title: i18n("x"),'),
    ("alertNotification.createObject(root, {", "alertNotification.createObject(root, root.lastArgs || {"),
])
def test_proof_alert_argument_rule_catches(old, new):
    assert _alert_argument_problems(_mutated(MAIN_QML, old, new))


def test_proof_second_alert_create_is_caught():
    code = _mutated(MAIN_QML, "    function setUsageMode(mode) {",
                    "    function x() { alertNotification.createObject(root, {}) }\n    function setUsageMode(mode) {")
    assert _alert_argument_problems(code)


# --- R2: personas, formatting, compare, text drops (plan T2.3) ---------------------------

# Rule checkers take {relative path: comment-stripped code}; the proofs feed
# them the real sources with one file mutated (_sources_with).


def _base(name):
    return name.rsplit("/", 1)[-1]


def _sources_with(path, old=None, new=None, snippet=None):
    """All plasmoid code, with ``path`` mutated (``old`` -> ``new``) or ``snippet`` appended."""
    sources = _all_code()
    if snippet is not None:
        sources[_rel(path)] = _appended(path, snippet)
    elif old is not None:
        sources[_rel(path)] = _mutated(path, old, new)
    return sources


def _mutated_in_function(path, function, old, new):
    """``path`` with ``old`` replaced by ``new`` inside ``function <name>(`` only."""
    raw = path.read_text(encoding="utf-8")
    bodies = list(_blocks(raw, rf"\bfunction\s+{function}\s*\([^)]*\)\s*\{{"))
    assert len(bodies) == 1, f"proof fixture out of date: function {function} in {_rel(path)}"
    start, _ = bodies[0]
    brace = raw.index("{", start)
    end = _brace_end(_strip_comments(raw, blank_strings=True), brace)
    body = raw[brace:end]
    assert old in body, f"proof fixture out of date: {old!r} not in {function}()"
    return _strip_comments(raw[:brace] + body.replace(old, new, 1) + raw[end:])


def _top_level_raw(body):
    """Like _top_level, but the top-level text keeps its string literals."""
    blanked = _strip_comments(body, blank_strings=True)
    out = []
    depth = 0
    for raw, char in zip(body, blanked):
        if char == "{":
            depth += 1
            out.append(" ")
        elif char == "}":
            depth -= 1
            out.append(" ")
        else:
            out.append(raw if depth == 1 or char == "\n" else " ")
    return "".join(out)


def _mutated_in_block(path, opener, anchor, old, new):
    """``path`` with ``old`` replaced inside the one ``opener`` block that holds ``anchor``."""
    raw = path.read_text(encoding="utf-8")
    blanked = _strip_comments(raw, blank_strings=True)
    found = []
    for match in re.finditer(opener, blanked):
        brace = blanked.find("{", match.end() - 1)
        end = _brace_end(blanked, brace)
        top = _top_level_raw(_strip_comments(raw[brace:end]))
        if re.search(rf"(?:^|[\n;])\s*{re.escape(anchor)}\s*(?=;|\n|$)", top):
            found.append((brace, end))
    assert len(found) == 1, f"proof fixture out of date: {anchor!r} in {_rel(path)} ({len(found)} blocks)"
    brace, end = found[0]
    body = raw[brace:end]
    assert old in body, f"proof fixture out of date: {old!r} not in the {anchor!r} block"
    return _strip_comments(raw[:brace] + body.replace(old, new, 1) + raw[end:])


# R2-1 The system role is sent once, by chatRequestBody, for the personality;
# ROLES (what a transcript row may be) stays user/assistant. The port owner
# word "system" (OWNERS, trusted) and the --install-info contract list
# (InstallInfo.js HELPERS) are the only other "system" literals.

SYSTEM_LITERAL = r"""["'`]system["'`]"""
SYSTEM_ALLOWED = {
    "chatRequestBody": r'^\s*clean\.push\(\{ role: "system", content: system \}\)\s*$',
    "OWNERS": r'^var OWNERS = \["none", "self", "system", "other"\]\s*$',
    "trusted": r'^\s*return owner === "self" \|\| owner === "system"\s*$',
    "HELPERS": r'^var HELPERS = \["user", "system", "other"\]\s*$',
}
# The one file each allowed line may be in; top-level lists need no function.
SYSTEM_FILES = {"chatRequestBody": "OllamaChat.js", "OWNERS": "OllamaChat.js", "trusted": "OllamaChat.js",
                "HELPERS": "InstallInfo.js"}
SYSTEM_TOP_LEVEL = {"OWNERS", "HELPERS"}


def _system_role_problems(sources):
    problems = []
    seen = {key: 0 for key in SYSTEM_ALLOWED}
    for name, code in sources.items():
        js = _base(name) == "OllamaChat.js"
        bodies = {key: _function_body(code, key) or "" for key in ("chatRequestBody", "trusted")} if js else {}
        for match in re.finditer(SYSTEM_LITERAL, code):
            line_start = code.rfind("\n", 0, match.start()) + 1
            line = code[line_start:code.find("\n", match.start())]
            kind = next((key for key, pattern in SYSTEM_ALLOWED.items() if re.match(pattern, line)), None)
            inside = kind in SYSTEM_TOP_LEVEL or (kind in bodies and line in bodies[kind])
            if kind is None or _base(name) != SYSTEM_FILES[kind] or not inside:
                problems.append(f"{name}:{_line_of(code, match.start())}: \"system\" only as the port owner "
                                "word, chatRequestBody's personality or the InstallInfo.HELPERS list")
            else:
                seen[kind] += 1
        if js:
            roles = re.findall(r"(?m)^var ROLES = (\[[^\]\n]*\])\s*$", code)
            if roles != ['["user", "assistant"]']:
                problems.append(f"{name}: ROLES must stay [\"user\", \"assistant\"], got {roles}")
            body = bodies["chatRequestBody"]
            dynamic = re.findall(r"\brole\s*:\s*([^,}\n]+)", body)
            if sorted(item.strip() for item in dynamic) != ['"system"', "message.role"] or \
                    not re.search(r"ROLES\s*\.\s*indexOf\s*\(\s*message\s*\.\s*role\s*\)\s*<\s*0", body):
                problems.append(f"{name}: chatRequestBody sends message.role only after the ROLES check")
            if len(re.findall(r"\brole\s*:", code)) != 2:
                problems.append(f"{name}: role: only in chatRequestBody")
    if seen != {key: 1 for key in SYSTEM_ALLOWED}:
        problems.append(f"\"system\" literals expected once each in {sorted(SYSTEM_ALLOWED)}, got {seen}")
    return problems


def test_system_role_only_for_the_personality():
    problems = _system_role_problems(_all_code())
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (OLLAMA_CHAT_VIEW, '        history.push({ role: "user", content: prompt })',
     '        history.push({ role: "system", content: "x" })\n        history.push({ role: "user", content: prompt })'),
    (OLLAMA_CHAT_JS, 'var ROLES = ["user", "assistant"]', 'var ROLES = ["user", "assistant", "system"]'),
    (OLLAMA_CHAT_JS, "        clean.push({ role: message.role, content: message.content })",
     "        clean.push({ role: message.role, content: message.content })\n"
     '        clean.push({ role: "system", content: system })'),
    (OLLAMA_CHAT_JS, "function unloadRequestBody(model) {",
     'function sneak(s) { return { role: "system", content: s } }\nfunction unloadRequestBody(model) {'),
    (OLLAMA_CHAT_JS, "ROLES.indexOf(message.role) < 0", "typeof message.role !== \"string\""),
    (OLLAMA_CHAT_JS, "        clean.push({ role: message.role, content: message.content })",
     "        clean.push({ role: message.author, content: message.content })"),
    # The InstallInfo.HELPERS exception covers that one exact line, in that one file.
    (INSTALL_INFO_JS, 'var HELPERS = ["user", "system", "other"]', 'var HELPERS = ["user", "system", "other", "system"]'),
    (INSTALL_INFO_JS, 'var HELPERS = ["user", "system", "other"]', 'var HELPERS = ["user", "other"].concat(["system"])'),
    (INSTALL_INFO_JS, 'var HELPERS = ["user", "system", "other"]', 'var HELPERS = ["user", "system", "other"]\nvar ROLE = "system"'),
    (INSTALL_INFO_JS, 'var HELPERS = ["user", "system", "other"]',
     'var HELPERS = ["user", "system", "other"]\nvar HELPERS = ["user", "system", "other"]'),
    (INSTALL_INFO_JS, 'var HELPERS = ["user", "system", "other"]', "var HELPERS = ['user', 'system', 'other']"),
    (INSTALL_INFO_JS, "    if (!info || typeof info !== \"object\")\n        return false\n",
     "    if (!info || typeof info !== \"object\")\n        return false\n    if (info.helper === \"system\")\n        return false\n"),
    (INSTALL_INFO_JS, "    if (!info || typeof info !== \"object\")\n        return false\n",
     "    if (!info || typeof info !== \"object\")\n        return false\n    var HELPERS = [\"user\", \"system\", \"other\"]\n"),
    (CHAT_STORAGE_JS, 'var MODES = ["memory", "encrypted"]', 'var MODES = ["memory", "encrypted"]\nvar HELPERS = ["user", "system", "other"]'),
    (OLLAMA_CHAT_JS, 'var ROLES = ["user", "assistant"]', 'var ROLES = ["user", "assistant"]\nvar HELPERS = ["user", "system", "other"]'),
    (MAIN_QML, "    property var installInfo: InstallInfo.unknown()",
     "    property var installInfo: InstallInfo.unknown()\n    readonly property bool sys: root.installInfo.helper === \"system\""),
])
def test_proof_system_role_rule_catches(path, old, new):
    assert _system_role_problems(_sources_with(path, old, new))


# R2-2 Reply blocks (OllamaChat.blocks) are shown only by OllamaChatView.qml,
# which has no image, link or external-open sink at all (P4 bans them there);
# OllamaChat.js cannot open anything (P1: no Qt.).

BLOCK_SINKS = {
    "Image": r"(?<![\w.])(?:[A-Za-z_]\w*\s*\.\s*)?(?:Image|AnimatedImage|BorderImage)\s*\{",
    "openUrlExternally": r"\bopenUrlExternally\b",
    "onLinkActivated": r"\b(?:on)?[Ll]inkActivated\b",
    "hoveredLink": r"\bhoveredLink\b|\blinkAt\b",
}


def _blocks_sink_problems(sources):
    problems = []
    for name, code in sources.items():
        calls = _hits(r"(?<![\w$])blocks\s*\(", code)
        if _base(name) == "OllamaChat.js":
            continue
        if _base(name) != "OllamaChatView.qml":
            problems += [f"{name}:{line}: OllamaChat.blocks may only be used by OllamaChatView.qml" for line in calls]
            continue
        if len(calls) != 1 or len(re.findall(r"\bOllamaChat\.blocks\(message\.body\)", code)) != 1:
            problems.append(f"{name}: OllamaChat.blocks(message.body) once")
        for sink, pattern in BLOCK_SINKS.items():
            problems += [f"{name}:{line}: {sink} where reply blocks are shown" for line in _hits(pattern, code)]
    return problems


def test_reply_blocks_never_reach_images_links_or_the_browser():
    problems = _blocks_sink_problems(_all_code())
    assert not problems, problems


@pytest.mark.parametrize(("path", "snippet"), [
    (OLLAMA_CHAT_VIEW, "\n    Image { source: OllamaChat.blocks(\"x\")[0].text }\n"),
    (OLLAMA_CHAT_VIEW, "\n    function open(b) { Qt.openUrlExternally(b.text) }\n"),
    (OLLAMA_CHAT_VIEW, "\n    Text { textFormat: Text.PlainText; onLinkActivated: (l) => console.log(l) }\n"),
    (FULL_REPRESENTATION, "\n    readonly property var shown: OllamaChat.blocks(\"x\")\n"),
])
def test_proof_blocks_sink_rule_catches(path, snippet):
    assert _blocks_sink_problems(_sources_with(path, snippet=snippet))


# R2-3 / R4 P4 covers every text element of the Ollama view and of the prompt
# library panel; the new reply delegates are pinned so they cannot move out
# of the checked files.

P4_FILES = (OLLAMA_CHAT_VIEW, PROMPT_LIBRARY_PANEL)
# (file, an anchor at the top level of the text element): the reply's plain
# TextEdit and word Text (ReplyParagraph), heading, list marker, code, the
# hidden-characters note, and the library's item text and notes.
P4_PINNED = (
    (OLLAMA_CHAT_VIEW, "id: plainText"),
    (OLLAMA_CHAT_VIEW, "id: wordText"),
    (OLLAMA_CHAT_VIEW, "font: ollamaView.headingFont(segment.block.level)"),
    (OLLAMA_CHAT_VIEW, "horizontalAlignment: Text.AlignRight"),
    (OLLAMA_CHAT_VIEW, "id: codeText"),
    (OLLAMA_CHAT_VIEW, 'objectName: "hiddenCharsNote"'),
    (OLLAMA_CHAT_VIEW, "visible: ollamaView.personaTooLong"),
    (PROMPT_LIBRARY_PANEL, 'objectName: "libraryItemText"'),
    (PROMPT_LIBRARY_PANEL, 'objectName: "libraryNote"'),
    (PROMPT_LIBRARY_PANEL, 'objectName: "copiedNote"'),
    (PROMPT_LIBRARY_PANEL, "id: copyHelper"),
)


def _pinned_plain_text_problems(code, anchors):
    problems = []
    tops = [(start, _top_level(body), _top_level_raw(body)) for start, body in _blocks(code, TEXT_ELEMENT)]
    for anchor in anchors:
        holders = [(start, top) for start, top, raw in tops
                   if re.search(rf"(?:^|[\n;])\s*{re.escape(anchor)}\s*(?=;|\n|$)", raw)]
        if len(holders) != 1:
            problems.append(f"{anchor!r} must be in exactly one text element, found {len(holders)}")
        elif len(re.findall(PLAIN_TEXT_FORMAT, holders[0][1])) != 1:
            problems.append(f"line {_line_of(code, holders[0][0])}: {anchor!r} needs textFormat PlainText")
    return problems


@pytest.mark.parametrize("path", P4_FILES, ids=lambda path: path.name)
def test_p4_files_show_everything_as_plain_text(path):
    code = _read_code(path)
    problems = _plain_text_problems(code) + _pinned_plain_text_problems(
        code, [anchor for owner, anchor in P4_PINNED if owner == path])
    assert not problems, f"{_rel(path)}: {problems}"


@pytest.mark.parametrize(("path", "anchor", "old", "new"), [
    (OLLAMA_CHAT_VIEW, "id: plainText", "textFormat: TextEdit.PlainText\n", ""),
    (OLLAMA_CHAT_VIEW, "id: wordText", "textFormat: Text.PlainText", "textFormat: Text.StyledText"),
    (OLLAMA_CHAT_VIEW, "font: ollamaView.headingFont(segment.block.level)", "textFormat: Text.PlainText\n", ""),
    (OLLAMA_CHAT_VIEW, "horizontalAlignment: Text.AlignRight", "textFormat: Text.PlainText\n", ""),
    (OLLAMA_CHAT_VIEW, "id: codeText", "textFormat: TextEdit.PlainText", "textFormat: TextEdit.MarkdownText"),
    (OLLAMA_CHAT_VIEW, 'objectName: "hiddenCharsNote"', 'objectName: "hiddenCharsNote"', 'objectName: "x"'),
    (PROMPT_LIBRARY_PANEL, 'objectName: "libraryItemText"', "textFormat: Text.PlainText\n", ""),
    (PROMPT_LIBRARY_PANEL, 'objectName: "copiedNote"', "textFormat: Text.PlainText", "textFormat: Text.AutoText"),
])
def test_proof_p4_pinned_rule_catches(path, anchor, old, new):
    code = _mutated_in_block(path, TEXT_ELEMENT, anchor, old, new)
    assert _plain_text_problems(code) + _pinned_plain_text_problems(
        code, [item for owner, item in P4_PINNED if owner == path])


def test_proof_p4_panel_rule_catches_rich_text():
    code = _appended(PROMPT_LIBRARY_PANEL, "\n    QQC2.Label { text: panel.items[0].text }\n")
    assert _plain_text_problems(code)


# R2-4 / R4 P5 covers every editable input, pinned: the Ollama message box and
# personality box, and the library's session box.

P5_FILES = {
    OLLAMA_CHAT_VIEW: ("id: input", "id: personaInput"),
    PROMPT_LIBRARY_PANEL: ('objectName: "sessionLibraryInput"',),
}


def _pinned_input_problems(code, anchors):
    problems = _input_privacy_problems(code)
    tops = [_top_level_raw(body) for _, body in _blocks(code, EDITABLE_ELEMENT)]
    for anchor in anchors:
        if len([top for top in tops if re.search(rf"(?:^|[\n;])\s*{re.escape(anchor)}\s*(?=;|\n|$)", top)]) != 1:
            problems.append(f"{anchor!r} must be one editable input checked by P5")
    return problems


@pytest.mark.parametrize("path", P5_FILES, ids=lambda path: path.name)
def test_p5_inputs_never_feed_spell_check_or_ime_learning(path):
    problems = _pinned_input_problems(_read_code(path), P5_FILES[path])
    assert not problems, f"{_rel(path)}: {problems}"


@pytest.mark.parametrize(("path", "anchor", "old", "new"), [
    (OLLAMA_CHAT_VIEW, "id: personaInput", "Kirigami.SpellCheck.enabled: false\n", ""),
    (OLLAMA_CHAT_VIEW, "id: personaInput", "Qt.ImhNoPredictiveText | Qt.ImhSensitiveData", "Qt.ImhNone"),
    (OLLAMA_CHAT_VIEW, "id: personaInput", "id: personaInput", "id: otherInput"),
    (PROMPT_LIBRARY_PANEL, 'objectName: "sessionLibraryInput"', "Kirigami.SpellCheck.enabled: false",
     "Kirigami.SpellCheck.enabled: true"),
    (PROMPT_LIBRARY_PANEL, 'objectName: "sessionLibraryInput"', "inputMethodHints: Qt.ImhNoPredictiveText | Qt.ImhSensitiveData\n", ""),
])
def test_proof_p5_pinned_rule_catches(path, anchor, old, new):
    assert _pinned_input_problems(_mutated_in_block(path, EDITABLE_ELEMENT, anchor, old, new), P5_FILES[path])


# R2-5 Drops: DropArea only on the panel icon (CompactRepresentation.qml) and
# as the view's one `component TextDropArea: DropArea {`. No drop path ever
# sends: the drop handlers and the functions they reach never call a send.

DROP_FUNCTIONS = {
    "OllamaChatView.qml": ("textDropped", "takeDrop", "dropFailed"),
    "main.qml": ("dropToOllama", "dropFileToOllama", "readDroppedFile", "droppedDone"),
    "FullRepresentation.qml": ("takePendingDrop", "takePendingDropError"),
}
# Any reference, not only a call: `Qt.callLater(ollamaView.send)` or a stored
# function would send later. A `name:` binding (an object key) is not one.
SEND_CALL = r"(?<![\w$])(?:send|startChat|checkOwner|regenerate|afterOwnerCheck|libraryRequest|sendChat)\b(?!\s*:)"
DROPPED_HANDLER = r"\bonDropped\s*:\s*(?:\([^)]*\)\s*=>\s*|function\s*\([^)]*\)\s*)?\{"


def _drop_problems(sources):
    problems = []
    for name, code in sources.items():
        base = _base(name)
        hits = _hits(r"\bDropArea\b", code)
        if base == "CompactRepresentation.qml":
            if hits != _hits(r"(?m)^[ \t]*DropArea\s*\{", code) or len(hits) != 1:
                problems.append(f"{name}: one plain `DropArea {{` on the icon")
        elif base == "OllamaChatView.qml":
            if hits != _hits(r"(?m)^[ \t]*component TextDropArea: DropArea \{", code) or len(hits) != 1:
                problems.append(f"{name}: DropArea only as `component TextDropArea: DropArea {{`")
        else:
            problems += [f"{name}:{line}: DropArea only on the icon and in the Ollama view" for line in hits]
        bodies = [(f"onDropped (line {_line_of(code, start)})", body) for start, body in _blocks(code, DROPPED_HANDLER)]
        for function in DROP_FUNCTIONS.get(base, ()):
            body = _function_body(code, function)
            if body is None:
                problems.append(f"{name}: function {function}( must exist once")
            bodies.append((function, body or ""))
        for label, body in bodies:
            for line in _hits(SEND_CALL, _strip_comments(body, blank_strings=True)):
                problems.append(f"{name}: {label} reaches a send (body line {line}); drops never send")
    handlers = sum(len(list(_blocks(code, DROPPED_HANDLER))) for code in sources.values())
    if handlers != 2:
        problems.append(f"exactly two onDropped handlers (icon and TextDropArea), found {handlers}")
    return problems


def test_drops_live_in_two_places_and_never_send():
    problems = _drop_problems(_all_code())
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new", "snippet"), [
    (FULL_REPRESENTATION, None, None, "\n    DropArea { anchors.fill: parent }\n"),
    (OLLAMA_CHAT_VIEW, None, None, "\n    DropArea { onDropped: (drop) => ollamaView.takeDrop(drop.text) }\n"),
    (OLLAMA_CHAT_VIEW, "        ollamaView.takeDrop(text)\n        return true",
     "        ollamaView.takeDrop(text)\n        ollamaView.send()\n        return true", None),
    (OLLAMA_CHAT_VIEW, "        ollamaView.focusLater()\n    }\n\n    // From the drop areas",
     "        ollamaView.startChat()\n    }\n\n    // From the drop areas", None),
    (MAIN_QML, "            root.pendingDrop = reply.text\n",
     "            root.pendingDrop = reply.text\n            root.libraryRequest(\"list\")\n", None),
    (COMPACT_REPRESENTATION, "                root.dropToOllama(drop.text)\n",
     "                root.dropToOllama(drop.text)\n                ollamaView.send()\n", None),
    (FULL_REPRESENTATION, "        ollamaView.takeDrop(text)\n",
     "        ollamaView.takeDrop(text)\n        ollamaView.checkOwner(\"send\")\n", None),
    # Deferred sends (review S2).
    (OLLAMA_CHAT_VIEW, "        ollamaView.focusLater()\n    }\n\n    // From the drop areas",
     "        Qt.callLater(ollamaView.send)\n    }\n\n    // From the drop areas", None),
    (OLLAMA_CHAT_VIEW, "        ollamaView.focusLater()\n    }\n\n    // From the drop areas",
     "        Qt.callLater(function(){ollamaView.send()})\n    }\n\n    // From the drop areas", None),
    (MAIN_QML, "            root.pendingDrop = reply.text\n",
     "            root.pendingDrop = reply.text\n            Qt.callLater(root.libraryRequest, \"list\")\n", None),
    (COMPACT_REPRESENTATION, "                root.dropToOllama(drop.text)\n",
     "                root.dropToOllama(drop.text)\n                var later = ollamaView.startChat\n", None),
])
def test_proof_drop_rule_catches(path, old, new, snippet):
    assert _drop_problems(_sources_with(path, old, new, snippet))


# R2-6 P12: Send, Regenerate and Compare's second request all go through the
# owner check (the gate rule above, with these insertions proved too).

@pytest.mark.parametrize(("function", "old", "new"), [
    ("finishChat", 'ollamaView.checkOwner("send")', "ollamaView.startChat()"),
    ("regenerate", 'ollamaView.checkOwner("send")', "ollamaView.startChat()"),
    ("send", 'ollamaView.checkOwner("send")', "ollamaView.startChat()"),
])
def test_proof_owner_gate_rule_catches_every_send_path(function, old, new):
    assert _owner_gate_problems(_mutated_in_function(OLLAMA_CHAT_VIEW, function, old, new))


# --- R3: KDE Wallet unlock (plan T3.2) ----------------------------------------------------

WALLET_LITERAL = r"kwallet-query|qdbus6|openssl"
FIDO_LITERAL = r"(?i)fido2-"


def _js_literal_span(code, opener):
    """(start, end) of the bracketed literal that ``opener`` (ending at [ or {) starts."""
    match = re.search(opener, code)
    if not match:
        return None
    blanked = _strip_comments(code, blank_strings=True)
    start = match.end() - 1
    pairs = {"[": "]", "{": "}"}
    depth = 0
    for index in range(start, len(blanked)):
        if blanked[index] == blanked[start]:
            depth += 1
        elif blanked[index] == pairs[blanked[start]]:
            depth -= 1
            if depth == 0:
                return start, index + 1
    return None


def _wallet_literal_problems(sources):
    problems = []
    for name, code in sources.items():
        problems += [f"{name}:{line}: fido2- is not used" for line in _hits(FIDO_LITERAL, code)]
        hits = [match.start() for match in re.finditer(WALLET_LITERAL, code)]
        if _base(name) != "ChatStorage.js":
            problems += [f"{name}:{_line_of(code, hit)}: wallet tool names only in ChatStorage.js" for hit in hits]
            continue
        spans = [_js_literal_span(code, r"(?m)^var WALLET_TOOLS = \["), _js_literal_span(code, r"(?m)^var TOOL_PACKAGES = \{")]
        if None in spans:
            problems.append(f"{name}: WALLET_TOOLS and TOOL_PACKAGES must be literals")
            continue
        for hit in hits:
            if not any(start <= hit < end for start, end in spans):
                problems.append(f"{name}:{_line_of(code, hit)}: wallet tool names only in WALLET_TOOLS and TOOL_PACKAGES")
        tools = code[spans[0][0]:spans[0][1]]
        if re.sub(r"\s+", " ", tools) != '["kwallet-query", "qdbus6", "openssl"]':
            problems.append(f"{name}: WALLET_TOOLS must be exactly [\"kwallet-query\", \"qdbus6\", \"openssl\"]")
    return problems


def test_wallet_tool_names_only_in_chat_storage_lists():
    problems = _wallet_literal_problems({**_all_code(), **{name: text for name, text in _all_text().items()
                                                            if not name.endswith((".qml", ".js"))}})
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new", "snippet"), [
    (MAIN_QML, None, None, '\n    readonly property string tool: "kwallet-query"\n'),
    (UI / "configGeneral.qml", None, None, '\n    readonly property string hint: i18n("Run qdbus6 to check")\n'),
    (CHAT_STORAGE_JS, None, None, '\nvar READ = "kwallet-query --folder Hearthwire --read-password x"\n'),
    (CHAT_STORAGE_JS, '"qdbus6", "openssl"]', '"qdbus6", "openssl", "secret-tool"]', None),
    (OLLAMA_CHAT_JS, None, None, '\nvar KEY = "fido2-assert"\n'),
])
def test_proof_wallet_literal_rule_catches(path, old, new, snippet):
    sources = _sources_with(path, old, new, snippet) if path.suffix == ".qml" or old is not None else _all_code()
    if path.suffix == ".js" and snippet is not None:
        sources[_rel(path)] = _strip_comments(path.read_text(encoding="utf-8") + snippet)
    assert _wallet_literal_problems(sources)


def _method_flag_problems(sources):
    problems = []
    for name, code in sources.items():
        hits = _hits(r"(?<![\w-])--method(?![\w-])", code)
        if _base(name) != "ChatStorage.js":
            problems += [f"{name}:{line}: --method only in ChatStorage.vaultCommand" for line in hits]
            continue
        body = _function_body(code, "vaultCommand") or ""
        inside = len(re.findall(r"(?<![\w-])--method(?![\w-])", body))
        if inside != len(hits) or inside == 0:
            problems.append(f"{name}: --method only inside vaultCommand")
        if re.findall(r'"\s*--method\s+(\w+)"', body) != ["wallet", "wallet"]:
            problems.append(f"{name}: vaultCommand appends only the literal \" --method wallet\"")
    return problems


def test_method_flag_is_built_only_by_vault_command():
    problems = _method_flag_problems(_all_code())
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (MAIN_QML, "    function chatNext() {",
     '    function x() { return "--vault unlock --method wallet" }\n    function chatNext() {'),
    (CHAT_STORAGE_JS, "function stepMethod(step) {", 'function stepMethod(step) {\n    var f = " --method "'),
    (CHAT_STORAGE_JS, 'return method === "wallet" ? command + " --method wallet" : command',
     'return command + " --method " + method'),
])
def test_proof_method_flag_rule_catches(path, old, new):
    assert _method_flag_problems(_sources_with(path, old, new))


AUTO_UNLOCK_ENQUEUE = (r'if\s*\(\s*root\.chatStorageMode\s*===\s*"encrypted"\s*&&\s*root\.chatUnlockSetting\s*===\s*'
                       r'"wallet"\s*\)\s*root\.chatEnqueue\s*\(\s*\[\s*"status"\s*,\s*"auto-unlock"\s*\]\s*\)')
COMPLETED_HANDLER = r"\bComponent\.onCompleted\s*:\s*\{"


def _auto_unlock_problems(sources):
    problems = []
    for name, code in sources.items():
        base = _base(name)
        hits = [match.start() for match in re.finditer(r"""["']auto-unlock["']""", code)]
        if base == "ChatStorage.js":
            continue
        if base not in ("main.qml", "ChatView.qml"):
            problems += [f"{name}:{_line_of(code, hit)}: auto-unlock only from main.qml at start" for hit in hits]
            continue
        allowed = [match.start(1) for match in re.finditer(r"""\bcase\s+("auto-unlock")\s*:""", code)]
        allowed += [match.start(1) for match in re.finditer(r"""\broot\.chatOp\s*===\s*("auto-unlock")""", code)]
        if base == "main.qml":
            enqueues = list(re.finditer(AUTO_UNLOCK_ENQUEUE, code))
            completed = [(start, start + len(body)) for start, body in _blocks(code, COMPLETED_HANDLER)
                         if re.match(r"\s*Component", code[code.rfind("\n", 0, start) + 1:])
                         and code[code.rfind("\n", 0, start) + 1:start].strip() == ""
                         and len(code[code.rfind("\n", 0, start) + 1:start]) == 4]
            if len(enqueues) != 1 or len(completed) != 1 or not (
                    completed[0][0] <= enqueues[0].start() < completed[0][1]):
                problems.append(f"{name}: auto-unlock is enqueued once, in the root Component.onCompleted, "
                                "behind the encrypted + wallet gate")
            allowed += [match.start() + match.group(0).rindex('"auto-unlock"') for match in enqueues]
        for hit in hits:
            if hit not in allowed:
                problems.append(f"{name}:{_line_of(code, hit)}: auto-unlock only enqueued at start")
        if re.search(r"""\bvaultCommand\s*\(\s*["']auto-unlock""", code):
            problems.append(f"{name}: auto-unlock never runs outside the step queue")
    return problems


def test_auto_unlock_is_queued_only_at_plasma_start():
    problems = _auto_unlock_problems(_all_code())
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (MAIN_QML, 'if (root.chatStorageMode === "encrypted" && root.chatUnlockSetting === "wallet")\n'
               '            root.chatEnqueue(["status", "auto-unlock"])',
     'root.chatEnqueue(["status", "auto-unlock"])'),
    (MAIN_QML, '            root.chatEnqueue(["status", "unlock-wallet"])', '            root.chatEnqueue(["status", "auto-unlock"])'),
    (MAIN_QML, '            root.chatEnqueue([action])\n', '            root.chatEnqueue(["auto-unlock"])\n'),
    (UI / "configGeneral.qml", 'page.runVault("add-key", "wallet")', 'page.runVault("auto-unlock")'),
    (CHAT_VIEW, 'case "auto-unlock":', 'case "auto-unlock": root.chatEnqueue(["auto-unlock"])'),
])
def test_proof_auto_unlock_rule_catches(path, old, new):
    assert _auto_unlock_problems(_sources_with(path, old, new))


def test_proof_auto_unlock_outside_on_completed_is_caught():
    code = _mutated(MAIN_QML, "    function chatNext() {",
                    "    function later() {\n"
                    '        if (root.chatStorageMode === "encrypted" && root.chatUnlockSetting === "wallet")\n'
                    '            root.chatEnqueue(["status", "auto-unlock"])\n    }\n    function chatNext() {')
    assert _auto_unlock_problems({**_all_code(), _rel(MAIN_QML): code})


UNLOCK_WRITE = r"\bcfg_chatVaultUnlock\s*=(?!=)"
UNLOCK_WALLET_WRITE = r'if\s*\(\s*reply\.ok\s*&&\s*op\s*===\s*"add-key"\s*\)\s*page\.cfg_chatVaultUnlock\s*=\s*"wallet"'
# Review M1: a slot the helper reports as set up is chosen again without add-key,
# only in `function useWalletSlot()` behind this guard.
UNLOCK_SLOT_WRITE = r'if\s*\(\s*page\.vaultWallet\s*===\s*"set-up"\s*\)\s*page\.cfg_chatVaultUnlock\s*=\s*"wallet"'


def _vault_unlock_key_problems(sources):
    problems = []
    for name, code in sources.items():
        base = _base(name)
        writes = list(re.finditer(rf"\b(\w+)\s*\.\s*cfg_chatVaultUnlock\s*=(?!=)\s*([^\n;]*)", code))
        bare = _hits(UNLOCK_WRITE, code)
        if len(bare) != len(writes):
            problems.append(f"{name}: cfg_chatVaultUnlock is written only as page.cfg_chatVaultUnlock")
        if base != "configGeneral.qml":
            problems += [f"{name}:{_line_of(code, match.start())}: only configGeneral.qml sets chatVaultUnlock"
                         for match in writes]
        else:
            values = [(match.group(1), match.group(2).strip()) for match in writes]
            if not values or any(value not in (("page", '"passphrase"'), ("page", '"wallet"')) for value in values):
                problems.append(f"{name}: page.cfg_chatVaultUnlock = \"passphrase\" or \"wallet\" only, got {values}")
            wallet = [value for value in values if value[1] == '"wallet"']
            slot_body = _function_body(code, "useWalletSlot") or ""
            if len(wallet) != 2 or len(re.findall(UNLOCK_WALLET_WRITE, code)) != 1 \
                    or len(re.findall(UNLOCK_SLOT_WRITE, code)) != 1 or len(re.findall(UNLOCK_SLOT_WRITE, slot_body)) != 1 \
                    or len(re.findall(r"\bcfg_chatVaultUnlock\s*=(?!=)", slot_body)) != 1:
                problems.append(f"{name}: \"wallet\" is chosen only inside if (reply.ok && op === \"add-key\") "
                                "and in useWalletSlot() behind if (page.vaultWallet === \"set-up\")")
        reads = list(re.finditer(r"\bPlasmoid\s*\.\s*configuration\s*\.\s*chatVaultUnlock\b", code))
        if base == "main.qml":
            good = re.findall(r"\bChatStorage\s*\.\s*normalizeUnlockMethod\s*\(\s*Plasmoid\s*\.\s*configuration"
                              r"\s*\.\s*chatVaultUnlock\s*\)", code)
            if len(reads) != 1 or len(good) != 1:
                problems.append(f"{name}: reads chatVaultUnlock only through ChatStorage.normalizeUnlockMethod(")
        elif reads:
            problems.append(f"{name}: only main.qml reads Plasmoid.configuration.chatVaultUnlock")
    return problems


def test_vault_unlock_setting_is_written_only_by_the_general_page():
    problems = _vault_unlock_key_problems(_all_code())
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (UI / "configGeneral.qml", '        if (reply.ok && op === "add-key")\n            page.cfg_chatVaultUnlock = "wallet"',
     '        if (op === "add-key")\n            page.cfg_chatVaultUnlock = "wallet"'),
    (UI / "configGeneral.qml", '            page.cfg_chatVaultUnlock = "passphrase"\n        }',
     '            page.cfg_chatVaultUnlock = "wallet"\n        }'),
    # Review M1: the useWalletSlot guard removed or weakened, or a write elsewhere.
    (UI / "configGeneral.qml", '        if (page.vaultWallet === "set-up")\n            page.cfg_chatVaultUnlock = "wallet"',
     '        page.cfg_chatVaultUnlock = "wallet"'),
    (UI / "configGeneral.qml", '        if (page.vaultWallet === "set-up")\n            page.cfg_chatVaultUnlock = "wallet"',
     '        if (page.vaultWallet !== "")\n            page.cfg_chatVaultUnlock = "wallet"'),
    (UI / "configGeneral.qml", "    function runVault(op, method) {\n",
     '    function runVault(op, method) {\n        page.cfg_chatVaultUnlock = "wallet"\n'),
    (UI / "configGeneral.qml", "    function runVault(op, method) {\n",
     '    function runVault(op, method) {\n        if (page.vaultWallet === "set-up")\n'
     '            page.cfg_chatVaultUnlock = "wallet"\n'),
    (UI / "configGeneral.qml", '            page.cfg_chatVaultUnlock = "passphrase"\n        }',
     '            page.cfg_chatVaultUnlock = method\n        }'),
    (UI / "configChat.qml", '    property string cfg_chatVaultUnlockDefault: "passphrase"\n',
     '    property string cfg_chatVaultUnlockDefault: "passphrase"\n'
     '    Component.onCompleted: page.cfg_chatVaultUnlock = "wallet"\n'),
    (MAIN_QML, "ChatStorage.normalizeUnlockMethod(Plasmoid.configuration.chatVaultUnlock)",
     "Plasmoid.configuration.chatVaultUnlock"),
    (MAIN_QML, "    function chatNext() {",
     "    function x() { Plasmoid.configuration.chatVaultUnlock = \"wallet\" }\n    function chatNext() {"),
    (FULL_REPRESENTATION, "    property bool showPrompts: false\n",
     "    property bool showPrompts: false\n    readonly property string m: Plasmoid.configuration.chatVaultUnlock\n"),
])
def test_proof_vault_unlock_key_rule_catches(path, old, new):
    sources = _sources_with(path, old, new)
    problems = _vault_unlock_key_problems(sources)
    if path == MAIN_QML and "= \"wallet\"" in new:
        problems += _main_config_write_offenders(sources[_rel(MAIN_QML)])
    assert problems


def test_proof_vault_unlock_key_in_the_key_set():
    assert "chatVaultUnlock" in _chat_config_keys()
    code = _mutated(UI / "configUsage.qml", '    property string cfg_chatVaultUnlockDefault: "passphrase"\n', "")
    assert not re.findall(r"(?m)^\s*property\s+string\s+cfg_chatVaultUnlockDefault\s*:", code)


# --- R4: prompt library and dropped files (plan T4.2) ------------------------------------

PROMPT_FLAGS = ("--prompts", "--read-dropped", "--kind", "--id", "--model", "--none")


def _prompt_flag_problems(sources):
    problems = []
    for name, code in sources.items():
        if _base(name) == "PromptLibrary.js":
            continue
        for flag in PROMPT_FLAGS:
            problems += [f"{name}:{line}: {flag} only in PromptLibrary.js"
                         for line in _hits(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", code)]
    return problems


def _prompt_library_js_problems(raw):
    problems = _ollama_js_problems(raw)
    code = _strip_comments(raw)
    for pattern, rule in ((r"\bPlasmoid\b", "Plasmoid"), (r"\bconfiguration\b", "configuration"),
                          (r"\bopenUrlExternally\b", "openUrlExternally")):
        lines = _hits(pattern, code)
        if lines:
            problems.append(f"must not use {rule} (lines {lines})")
    return problems


def test_prompt_flags_only_in_prompt_library_js():
    problems = _prompt_flag_problems(_all_code())
    assert not problems, problems


def test_prompt_library_js_is_a_pure_library():
    problems = _prompt_library_js_problems(PROMPT_LIBRARY_JS.read_text(encoding="utf-8"))
    assert not problems, f"{_rel(PROMPT_LIBRARY_JS)}: {problems}"


@pytest.mark.parametrize("snippet", [
    '    readonly property string c: "python3 -P -m hearthwire --prompts list"\n',
    '    readonly property string c: "--read-dropped 2f"\n',
    '    readonly property string c: " --model " + "x"\n',
])
def test_proof_prompt_flag_rule_catches(snippet):
    assert _prompt_flag_problems(_sources_with(MAIN_QML, snippet=snippet))


@pytest.mark.parametrize("snippet", [
    "import QtQuick 2.15", ".import \"ChatStorage.js\" as ChatStorage", "function f() { return Qt.platform }",
    "function f(t) { console.log(t) }", "function f() { return new XMLHttpRequest() }",
    "function f() { return Plasmoid.configuration.chatSites }",
])
def test_proof_prompt_library_js_rule_catches(snippet):
    raw = PROMPT_LIBRARY_JS.read_text(encoding="utf-8")
    assert _prompt_library_js_problems(raw.replace(".pragma library\n", ".pragma library\n" + snippet + "\n", 1))
    assert _prompt_library_js_problems(raw.replace(".pragma library", "", 1))


# Dropped data: only drop.hasText/hasUrls/text, drop.urls.length and the one
# PromptLibrary.hexPath(drop.urls[0]) in each of the two onDropped handlers.
DROP_DATA_BANS = {
    "drop.html": r"\b(?:drop|drag)\s*\.\s*html\b",
    "getDataAsString": r"\bgetDataAsString\b",
    "getDataAsArrayBuffer": r"\bgetDataAsArrayBuffer\b",
    "formats": r"\b(?:drop|drag)\s*\.\s*formats\b",
    "source": r"\b(?:drop|drag)\s*\.\s*source\b",
    "drag.urls": r"\bdrag\s*\.\s*urls\b",
}
HEX_PATH_CALL = r"\bPromptLibrary\.hexPath\(drop\.urls\[0\]\)"


def _drop_data_problems(sources):
    problems = []
    for name, code in sources.items():
        for rule, pattern in DROP_DATA_BANS.items():
            problems += [f"{name}:{line}: {rule} is not read" for line in _hits(pattern, code)]
        indexed = [match.start() + match.group(0).index("urls")
                   for match in re.finditer(r"\b(?:drop|drag)\s*\.\s*urls\b(?!\s*\.\s*length\b)", code)]
        allowed = []
        for start, body in _blocks(code, DROPPED_HANDLER):
            brace = code.index("{", start)
            calls = [brace + match.start() + len("PromptLibrary.hexPath(drop.")
                     for match in re.finditer(HEX_PATH_CALL, body)]
            assert all(code[call:call + 4] == "urls" for call in calls)
            if len(calls) != 1 and _base(name) in ("CompactRepresentation.qml", "OllamaChatView.qml"):
                problems.append(f"{name}:{_line_of(code, start)}: onDropped reads a file only as "
                                "PromptLibrary.hexPath(drop.urls[0])")
            allowed += calls
        for hit in indexed:
            if hit not in allowed:
                problems.append(f"{name}:{_line_of(code, hit)}: drop.urls only as .length and "
                                "PromptLibrary.hexPath(drop.urls[0])")
        if _base(name) not in ("CompactRepresentation.qml", "OllamaChatView.qml") and _hits(r"\bhexPath\s*\(", code) \
                and _base(name) != "PromptLibrary.js":
            problems.append(f"{name}: hexPath only in the two drop handlers")
    return problems


def test_dropped_data_is_read_only_as_text_or_one_hex_path():
    problems = _drop_data_problems(_all_code())
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (COMPACT_REPRESENTATION, "PromptLibrary.hexPath(drop.urls[0])", "String(drop.urls[0])"),
    (COMPACT_REPRESENTATION, "PromptLibrary.hexPath(drop.urls[0])", "PromptLibrary.hexPath(drop.urls[1])"),
    (OLLAMA_CHAT_VIEW, "drop.hasText ? drop.text : \"\"", "drop.hasHtml ? drop.html : \"\""),
    (OLLAMA_CHAT_VIEW, "drop.hasText ? drop.text : \"\"", "drop.getDataAsString(\"text/html\")"),
    (OLLAMA_CHAT_VIEW, "drop.hasText ? drop.text : \"\"", "drop.getDataAsArrayBuffer(\"image/png\")"),
    (OLLAMA_CHAT_VIEW, "            if (drag.hasText || drag.hasUrls)",
     "            if (drag.urls[0] || drag.hasText || drag.hasUrls)"),
    (MAIN_QML, "    function chatNext() {",
     "    function f(d) { return PromptLibrary.hexPath(d.urls[0]) }\n    function chatNext() {"),
])
def test_proof_drop_data_rule_catches(path, old, new):
    assert _drop_data_problems(_sources_with(path, old, new))


# The two helper DataSources of R4: connected once each, from main.qml, and
# reading only stdout and the exit code.
LIBRARY_SOURCES = ("librarySource", "droppedSource")


def _library_source_problems(sources):
    problems = []
    for name, code in sources.items():
        for source in LIBRARY_SOURCES:
            calls = _hits(rf"\b{source}\s*\.\s*connectSource\s*\(", code)
            if _base(name) != "main.qml":
                problems += [f"{name}:{line}: {source} is used only in main.qml" for line in _hits(rf"\b{source}\b", code)]
                continue
            if len(calls) != 1:
                problems.append(f"{name}: {source}.connectSource( exactly once, found {len(calls)}")
            blanked = _strip_comments(code, blank_strings=True)
            spans = _handler_spans(blanked, r"(?<![\w.])(?:[A-Za-z_]\w*\s*\.\s*)?DataSource\s*\{", source, "onNewData")
            if len(spans) != 1:
                problems.append(f"{name}: {source} needs exactly one onNewData")
                continue
            body = code[spans[0][0]:spans[0][1]]
            keys = re.findall(r"\bdata\s*\[\s*\"([^\"]*)\"\s*\]", body)
            if sorted(set(keys)) != ["exit code", "stdout"] or re.search(r"\bdata\s*(?:\.|\[\s*[^\"\s])", body) \
                    or re.search(r"stderr", body):
                problems.append(f"{name}: {source}.onNewData reads only data[\"exit code\"] and data[\"stdout\"]")
    return problems


def test_library_sources_read_only_stdout_and_exit_code():
    problems = _library_source_problems(_all_code())
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (MAIN_QML, 'root.libraryFinish(root.libraryOp, data["exit code"], data["stdout"])',
     'root.libraryFinish(root.libraryOp, data["exit code"], data["stderr"])'),
    (MAIN_QML, 'root.droppedDone(PromptLibrary.parseDropped(data["exit code"], data["stdout"]))',
     'root.droppedDone(PromptLibrary.parseDropped(0, data.stdout))'),
    (MAIN_QML, "        librarySource.connectSource(command)\n",
     "        librarySource.connectSource(command)\n        librarySource.connectSource(command)\n"),
    (FULL_REPRESENTATION, "    property bool showPrompts: false\n",
     "    property bool showPrompts: false\n    function x(c) { droppedSource.connectSource(c) }\n"),
])
def test_proof_library_source_rule_catches(path, old, new):
    assert _library_source_problems(_sources_with(path, old, new))


# Clipboard: `.copy()` only inside a `function copyText(`, which is called
# only from an onClicked handler (a user click).
CLICK_HANDLER = r"\bonClicked\s*:\s*(?:\([^)]*\)\s*=>\s*|function\s*\([^)]*\)\s*)?"


def _click_spans(code):
    blanked = _strip_comments(code, blank_strings=True)
    spans = []
    for match in re.finditer(CLICK_HANDLER, blanked):
        if blanked[match.end():match.end() + 1] == "{":
            spans.append((match.end(), _brace_end(blanked, match.end())))
        else:
            end = blanked.find("\n", match.end())
            spans.append((match.end(), len(blanked) if end == -1 else end))
    return spans


def _clipboard_problems(sources):
    problems = []
    for name, code in sources.items():
        blanked = _strip_comments(code, blank_strings=True)
        functions = [(start, start + len(body)) for start, body in _blocks(code, r"\bfunction\s+copyText\s*\([^)]*\)\s*\{")]
        for match in re.finditer(r"\.\s*copy\s*\(\s*\)", blanked):
            if not any(start <= match.start() < end for start, end in functions):
                problems.append(f"{name}:{_line_of(code, match.start())}: .copy() only inside function copyText")
        for pattern in (r"\bQt\s*\.\s*application\s*\.\s*clipboard\b", r"\bClipboard\s*\.", r"\bsetClipboard\w*\s*\("):
            problems += [f"{name}:{line}: no other clipboard API" for line in _hits(pattern, blanked)]
        clicks = _click_spans(code)
        for match in re.finditer(r"(?<![\w$])copyText(?![\w$])", blanked):
            if re.search(r"\bfunction\s+$", blanked[max(0, match.start() - 12):match.start()]):
                continue
            if not re.match(r"\s*\(", blanked[match.end():]):
                problems.append(f"{name}:{_line_of(code, match.start())}: copyText may only be called directly")
            elif not any(start <= match.start() < end for start, end in clicks):
                problems.append(f"{name}:{_line_of(code, match.start())}: copyText only from onClicked")
    return problems


def test_clipboard_copies_only_on_a_click():
    problems = _clipboard_problems(_all_code())
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (PROMPT_LIBRARY_PANEL, "    function remove(entry) {\n",
     "    function remove(entry) {\n        panel.copyText(entry.text)\n"),
    (PROMPT_LIBRARY_PANEL, "        panel.copied = true\n", "        panel.copied = true\n        copyHelper.copy()\n"
                                                           "    }\n    function again() {\n        copyHelper.copy()\n"),
    (OLLAMA_CHAT_VIEW, "        ollamaView.focusLater()\n    }\n\n    // From the drop areas",
     "        ollamaView.copyText(text)\n    }\n\n    // From the drop areas"),
    (OLLAMA_CHAT_VIEW, "onClicked: ollamaView.copyText(segment.content)",
     "onPressed: ollamaView.copyText(segment.content)"),
    (FULL_REPRESENTATION, "    property bool showPrompts: false\n",
     "    property bool showPrompts: false\n    Component.onCompleted: Qt.callLater(ollamaView.copyText, \"x\")\n"),
])
def test_proof_clipboard_rule_catches(path, old, new):
    assert _clipboard_problems(_sources_with(path, old, new))


# Library text never meets the configuration: PromptLibrary.js and
# PromptLibraryPanel.qml do not touch Plasmoid at all (they are also in
# CHAT_CONFIG_READ_ONLY_FILES and, for the panel, the P4/P5 lists above).

def _library_config_problems(sources):
    return [
        f"{name}:{line}: the prompt library never touches Plasmoid"
        for name, code in sources.items() if _base(name) in ("PromptLibrary.js", "PromptLibraryPanel.qml")
        for line in _hits(r"\bPlasmoid\b|\bplasmoid\b", code)
    ]


def test_prompt_library_never_touches_the_configuration():
    assert {"PromptLibrary.js", "PromptLibraryPanel.qml"} <= set(CHAT_CONFIG_READ_ONLY_FILES)
    assert PROMPT_LIBRARY_PANEL in P4_FILES and PROMPT_LIBRARY_PANEL in P5_FILES
    problems = _library_config_problems(_all_code())
    assert not problems, problems


@pytest.mark.parametrize("path", [PROMPT_LIBRARY_PANEL, PROMPT_LIBRARY_JS])
def test_proof_library_config_rule_catches(path):
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".js":
        code = _strip_comments(raw + "\nfunction f() { return Plasmoid.configuration.chatSites }\n")
    else:
        code = _appended(path, "\n    readonly property string s: Plasmoid.configuration.chatSites\n")
    assert _library_config_problems({_rel(path): code})


# set-persona is requested only by FullRepresentation's onPersonaDefaultChosen.
SET_PERSONA_HANDLER = (r'\bonPersonaDefaultChosen\s*:\s*\(\s*model\s*,\s*id\s*\)\s*=>\s*root\.libraryRequest\s*\(\s*'
                       r'"set-persona"\s*,')


def _set_persona_problems(sources):
    problems = []
    for name, code in sources.items():
        hits = _hits(r"""["']set-persona["']""", code)
        if _base(name) == "PromptLibrary.js":
            continue
        if _base(name) != "FullRepresentation.qml":
            problems += [f"{name}:{line}: set-persona only from onPersonaDefaultChosen" for line in hits]
        elif len(hits) != 1 or _hits(SET_PERSONA_HANDLER, code) != hits:
            problems.append(f"{name}: set-persona once, as onPersonaDefaultChosen: (model, id) => "
                            "root.libraryRequest(\"set-persona\", ...)")
    return problems


def test_set_persona_only_from_the_persona_default_handler():
    problems = _set_persona_problems(_all_code())
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (MAIN_QML, "    function chatNext() {",
     '    function x() { root.libraryRequest("set-persona", { model: "m", id: 1 }) }\n    function chatNext() {'),
    (FULL_REPRESENTATION, "onPersonaDefaultChosen: (model, id) =>", "onModelNameChanged: (model, id) =>"),
    (OLLAMA_CHAT_VIEW, "    signal personaDefaultChosen(string model, int id)\n",
     "    signal personaDefaultChosen(string model, int id)\n    readonly property string op: \"set-persona\"\n"),
])
def test_proof_set_persona_rule_catches(path, old, new):
    assert _set_persona_problems(_sources_with(path, old, new))


# Split view: pane b is more Repeater entries in the one shared profile. Every
# view is created through the two owner-gated appends with its pane, a Local
# view per pane only after that pane's owner check, pane b views go when split
# is off, a sign-in window covers its opener's pane, and the one WebEngineView
# stays inside pageComponent.
SPLIT_SYNC_APPEND = (r"ChatSites\s*\.\s*localOwnerPort\s*\(\s*\{\s*siteId\s*:\s*wanted\s*,\s*customUrls\s*:\s*"
                     r"chatWeb\s*\.\s*customUrls\s*,\s*url\s*:\s*home\s*\}\s*\)\s*===\s*0\s*\)\s*"
                     r"visitedSites\s*\.\s*append\s*\(\s*\{\s*site\s*:\s*wanted\s*,\s*pane\s*:\s*pane\s*\}\s*\)")
SPLIT_FINISHED_APPEND = (r'visitedSites\s*\.\s*append\s*\(\s*\{\s*site\s*:\s*"local"\s*,\s*'
                         r"pane\s*:\s*pending\s*\.\s*pane\s*\}\s*\)")
SPLIT_CREATE_GATE = (r"\belse\s+if\s*\(\s*!\s*chatWeb\s*\.\s*ownerPending\s*\)\s*"
                     r"chatWeb\s*\.\s*checkLocalOwner\s*\(\s*null\s*,\s*home\s*,\s*false\s*,\s*true\s*,\s*pane\s*\)")
SPLIT_REMOVE = (r"\bif\s*\(\s*chatWeb\s*\.\s*siteIds\s*\.\s*indexOf\s*\(\s*entry\s*\.\s*site\s*\)\s*<\s*0\s*\|\|\s*"
                r'\(\s*entry\s*\.\s*pane\s*===\s*"b"\s*&&\s*!\s*chatWeb\s*\.\s*splitActive\s*\)\s*\)\s*\{')
SPLIT_OVERLAY_OPEN = (r"\bchatWeb\s*\.\s*overlayPane\s*=\s*page\s*\.\s*pane\s*;?\s*"
                      r"chatWeb\s*\.\s*openOverlay\s*\(\s*request\s*,\s*page\s*\.\s*site\s*,\s*"
                      r"page\s*\.\s*url\s*\.\s*toString\s*\(\s*\)\s*\)")
SPLIT_CREATE_OBJECT = r"\bvar\s+view\s*=\s*pageComponent\s*\.\s*createObject\s*\(\s*overlayContent\s*,\s*\{([^}]*)\}"
SPLIT_NAV_CHECK = (r"\bchatWeb\s*\.\s*checkLocalOwner\s*\(\s*page\s*,\s*url\s*,\s*request\s*\.\s*navigationType\s*"
                   r"===\s*WebEngineNavigationRequest\s*\.\s*FormSubmittedNavigation\s*,\s*false\s*,\s*"
                   r"page\s*\.\s*pane\s*\)")
SPLIT_ACTIVE_VIEW = (r"(?m)^\s*readonly\s+property\s+var\s+activeView\s*:\s*chatWeb\s*\.\s*overlayActive\s*\?\s*"
                     r"chatWeb\s*\.\s*overlayView\s*:\s*chatWeb\s*\.\s*paneView\s*$")
SPLIT_OVERLAY_ACTIVE = (r"(?m)^\s*readonly\s+property\s+bool\s+overlayActive\s*:\s*chatWeb\s*\.\s*overlayView\s*"
                        r"!==\s*null\s*&&\s*chatWeb\s*\.\s*overlayPane\s*===\s*chatWeb\s*\.\s*activePane\s*$")
SPLIT_LOCAL_SITE = (r'(?m)^\s*readonly\s+property\s+bool\s+localSite\s*:\s*chatView\s*\.\s*siteId\s*===\s*"local"\s*'
                    r"\|\|\s*\(\s*!!\s*chatView\s*\.\s*web\s*&&\s*chatView\s*\.\s*web\s*\.\s*splitShown\s*===\s*true"
                    r'\s*&&\s*chatView\s*\.\s*siteIdB\s*===\s*"local"\s*\)\s*$')
SPLIT_OWNER_MESSAGE_VISIBLE = r'(?m)^\s*visible\s*:\s*chatView\s*\.\s*localSite\s*&&\s*code\s*!==\s*""\s*$'


def _split_view_problems(web, view):
    problems = []
    sync = _function_body(web, "syncViews") or ""
    finished = _function_body(web, "localOwnerFinished") or ""
    # 1. Exactly two appends, each with its pane, in their owner-gated places.
    appends = list(re.finditer(r"visitedSites\s*\.\s*append\s*\(", web))
    if len(appends) != 2 or len(re.findall(SPLIT_SYNC_APPEND, sync)) != 1 \
            or len(re.findall(SPLIT_FINISHED_APPEND, finished)) != 1:
        problems.append("visitedSites.append exactly twice: `{ site: wanted, pane: pane }` in syncViews behind "
                        "`localOwnerPort({ siteId: wanted, ... url: home }) === 0` and "
                        "`{ site: \"local\", pane: pending.pane }` in localOwnerFinished")
    for match in appends:
        literal = re.match(r"visitedSites\s*\.\s*append\s*\(\s*\{([^}]*)\}", web[match.start():])
        if not literal or not re.search(r"\bpane\s*:", literal.group(1)):
            problems.append(f"line {_line_of(web, match.start())}: every visitedSites.append carries `pane:`")
    # 2. A Local view is created only after its own check, one check at a time.
    if len(re.findall(r"\bcheckLocalOwner\s*\(", sync)) != 1 or len(re.findall(SPLIT_CREATE_GATE, sync)) != 1:
        problems.append("syncViews runs checkLocalOwner(null, home, false, true, pane) only behind "
                        "`else if (!chatWeb.ownerPending)`")
    # 3. Pane b views go once split is off.
    if len(re.findall(SPLIT_REMOVE, sync)) != 1:
        problems.append("syncViews must drop entries of disabled sites and every pane b entry when split is off")
    # 4. A sign-in window covers its opener's pane; one createObject, one WebEngineView.
    assignments = _hits(r"\boverlayPane\s*=(?!=)", web)
    if len(assignments) != 1 or len(re.findall(SPLIT_OVERLAY_OPEN, web)) != 1 \
            or len(re.findall(r"\bopenOverlay\s*\(", web)) != 2:
        problems.append("overlayPane is set only as `chatWeb.overlayPane = page.pane` right before the one "
                        "chatWeb.openOverlay(request, page.site, page.url.toString())")
    created = re.search(SPLIT_CREATE_OBJECT, web)
    if len(re.findall(r"\bcreateObject\s*\(", web)) != 1 or not created \
            or not re.search(r"\bpane\s*:\s*chatWeb\s*\.\s*overlayPane\s*,", created.group(1)) \
            or not re.search(r"\bisOverlay\s*:\s*true\s*,", created.group(1)):
        problems.append("pageComponent.createObject only once, in openOverlay, with "
                        "`pane: chatWeb.overlayPane` and `isOverlay: true`")
    components = [body for _, body in _blocks(web, r"\bComponent\s*\{")
                  if re.search(r"(?m)^\s*id\s*:\s*pageComponent\s*$", body)]
    if len(_hits(r"\bWebEngineView\s*\{", web)) != 1 or len(components) != 1 \
            or len(_hits(r"\bWebEngineView\s*\{", components[0])) != 1:
        problems.append("exactly one `WebEngineView {`, inside the pageComponent Component")
    # 5. The navigation gate checks for the page's own pane.
    nav = [body for _, body in _blocks(web, NAV_HANDLER)]
    if len(nav) != 1 or len(re.findall(SPLIT_NAV_CHECK, nav[0])) != 1 \
            or len(re.findall(r"\bcheckLocalOwner\s*\(", web)) != 3:
        problems.append("onNavigationRequested passes page.pane: checkLocalOwner(page, url, ..., false, page.pane)")
    # 7. The toolbar acts on a sign-in window only when it covers the active pane.
    if len(_hits(SPLIT_ACTIVE_VIEW, web)) != 1 or len(_hits(r"\bproperty\s+var\s+activeView\b", web)) != 1:
        problems.append("activeView: chatWeb.overlayActive ? chatWeb.overlayView : chatWeb.paneView")
    if len(_hits(SPLIT_OVERLAY_ACTIVE, web)) != 1 or len(_hits(r"\bproperty\s+bool\s+overlayActive\b", web)) != 1:
        problems.append("overlayActive: chatWeb.overlayView !== null && chatWeb.overlayPane === chatWeb.activePane")
    # 6. ChatView.qml: the owner message shows for a Local site in either pane.
    if len(_hits(SPLIT_LOCAL_SITE, view)) != 1 or len(_hits(r"\bproperty\s+bool\s+localSite\b", view)) != 1:
        problems.append("ChatView.qml: localSite must cover pane a and a shown pane b")
    messages = [body for _, body in _blocks(view, r"\bKirigami\s*\.\s*InlineMessage\s*\{")
                if re.search(r"(?m)^\s*id\s*:\s*localOwnerMessage\s*$", body)]
    first_visible = re.search(r"(?m)^\s*visible\s*:", messages[0]) if len(messages) == 1 else None
    if not first_visible or not re.match(SPLIT_OWNER_MESSAGE_VISIBLE, messages[0][first_visible.start():]):
        problems.append("ChatView.qml: localOwnerMessage keeps `visible: chatView.localSite && code !== \"\"`")
    return problems


def test_split_view_panes_share_the_gated_views():
    problems = _split_view_problems(_read_code(CHAT_WEB_VIEW), _read_code(CHAT_VIEW))
    assert not problems, problems


SPLIT_MUTATIONS = [
    (CHAT_WEB_VIEW, "visitedSites.append({ site: wanted, pane: pane })", "visitedSites.append({ site: wanted })"),
    (CHAT_WEB_VIEW, 'visitedSites.append({ site: "local", pane: pending.pane })',
     'visitedSites.append({ site: "local" })'),
    (CHAT_WEB_VIEW, "visitedSites.append({ site: wanted, pane: pane })",
     'visitedSites.append({ site: wanted, pane: "b" })'),
    (CHAT_WEB_VIEW, 'visitedSites.append({ site: "local", pane: pending.pane })',
     'visitedSites.append({ site: "local", pane: "b" })'),
    (CHAT_WEB_VIEW, "    function retryLocalOwner() {\n",
     "    function retryLocalOwner() {\n        visitedSites.append({ site: chatWeb.siteIdB, pane: \"b\" })\n"),
    (CHAT_WEB_VIEW, "            else if (!chatWeb.ownerPending)\n", "            else\n"),
    (CHAT_WEB_VIEW, '(chatWeb.siteIds.indexOf(entry.site) < 0 || (entry.pane === "b" && !chatWeb.splitActive)) {',
     "(chatWeb.siteIds.indexOf(entry.site) < 0) {"),
    (CHAT_WEB_VIEW, "chatWeb.overlayPane = page.pane", 'chatWeb.overlayPane = "a"'),
    (CHAT_WEB_VIEW, "    function retryLocalOwner() {\n",
     "    function retryLocalOwner() {\n        pageComponent.createObject(paneAreaB, { site: \"local\", pane: \"b\" })\n"),
    (CHAT_WEB_VIEW, "    ListModel {\n        id: visitedSites\n",
     "    WebEngineView { profile: chatProfile }\n    ListModel {\n        id: visitedSites\n"),
    (CHAT_WEB_VIEW, "=== WebEngineNavigationRequest.FormSubmittedNavigation, false, page.pane)",
     "=== WebEngineNavigationRequest.FormSubmittedNavigation, false)"),
    (CHAT_WEB_VIEW, "activeView: chatWeb.overlayActive ? chatWeb.overlayView : chatWeb.paneView",
     "activeView: chatWeb.overlayView || chatWeb.paneView"),
    (CHAT_WEB_VIEW, "chatWeb.overlayView !== null && chatWeb.overlayPane === chatWeb.activePane",
     "chatWeb.overlayView !== null"),
    (CHAT_VIEW, 'chatView.siteId === "local"\n'
     '        || (!!chatView.web && chatView.web.splitShown === true && chatView.siteIdB === "local")',
     'chatView.zoomSiteId === "local"'),
    (CHAT_VIEW, 'visible: chatView.localSite && code !== ""', 'visible: code !== ""'),
]


@pytest.mark.parametrize(("path", "old", "new"), SPLIT_MUTATIONS,
                         ids=[f"{path.name}:{index}" for index, (path, _, _) in enumerate(SPLIT_MUTATIONS)])
def test_proof_split_view_rule_catches(path, old, new):
    web = _mutated(path, old, new) if path == CHAT_WEB_VIEW else _read_code(CHAT_WEB_VIEW)
    view = _mutated(path, old, new) if path == CHAT_VIEW else _read_code(CHAT_VIEW)
    assert _split_view_problems(web, view)


# Usage and hover tooltip settings: only configUsage.qml writes them, each
# through its own checkbox or helper function; main.qml and the other pages
# only read them.
TOOLTIP_LOGIC_JS = UI / "TooltipLogic.js"
USAGE_LOGIC_JS = UI / "UsageLogic.js"
CONFIG_GENERAL = CONFIG_PAGES[0]
# key -> objectName of the CheckBox whose onToggled writes it, or the helper
# functions that may write it (each of them must).
USAGE_PAGE_WRITERS = {
    "tooltipShowsUsage": "tooltipUsageChoice",
    "usageCompact": "usageCompactChoice",
    "tooltipMetrics": ("setTooltipSame", "setTooltipMetric"),
    "providerMetrics": ("setMetric",),
    "providerOrder": ("moveProvider",),
    "usageWarnPercent": ("setThresholds",),
    "usageCriticalPercent": ("setThresholds",),
    "usageNormalColor": ("setUsageColor",),
    "usageWarnColor": ("setUsageColor",),
    "usageCriticalColor": ("setUsageColor",),
}
_USAGE_KEYS = "|".join(USAGE_PAGE_WRITERS)
# main.qml rewrites these once, in migrateUsageMetrics().
MIGRATED_KEYS = ("tooltipMetrics", "providerMetrics")
USAGE_KEY_WRITE = (rf"\b(?:cfg_)?({_USAGE_KEYS})\s*"
                   r"(?:\+\+|--|(?:[-+*/%&|^]|\*\*|<<|>>>?|&&|\|\||\?\?)?=(?!=))")
USAGE_CONFIG_WRITE = (rf"\b[Pp]lasmoid\s*\.\s*configuration\s*\.\s*({_USAGE_KEYS})\s*"
                      r"(?:\+\+|--|(?:[-+*/%&|^]|\?\?)?=(?!=))")


def _is_apply_backup_line(code, at, key):
    """Whether offset ``at`` is on applyBackup's own line for ``key``, in the one applyBackup."""
    spans = _block_spans(code, r"\bfunction\s+applyBackup\s*\(\s*\)\s*\{")
    if len(spans) != 1 or not spans[0][0] <= at < spans[0][1]:
        return False
    line = code[code.rfind("\n", 0, at) + 1:code.find("\n", at)]
    return re.fullmatch(rf"\s*if\s*\(\s*values\s*\.\s*{key}\s*!==\s*undefined\s*\)\s*"
                        rf"page\s*\.\s*cfg_{key}\s*=\s*values\s*\.\s*{key}\s*", line) is not None


def _usage_writer_problems(sources):
    problems = []
    for name, code in sources.items():
        hits = [(match.start(), match.group(1))
                for pattern in (USAGE_KEY_WRITE, USAGE_CONFIG_WRITE) for match in re.finditer(pattern, code)]
        if _base(name) == CONFIG_GENERAL.name and _hits(r"\bTooltipLogic\b", code):
            problems.append(f"{name}: the tooltip settings moved to configUsage.qml; no TooltipLogic here")
        if _base(name) == MAIN_QML.name:
            # The schema 2 -> 3 migration; its exact form is pinned by _main_migration_problems.
            migration = _block_spans(code, r"\bfunction\s+migrateUsageMetrics\s*\(\s*\)\s*\{")
            hits = [(at, key) for at, key in hits
                    if not (key in MIGRATED_KEYS and len(migration) == 1
                            and migration[0][0] <= at < migration[0][1])]
        if _base(name) == CONFIG_GENERAL.name:
            # Import: Replace sets each value by its own line of applyBackup.
            hits = [(at, key) for at, key in hits if not _is_apply_backup_line(code, at, key)]
        if _base(name) != CONFIG_USAGE.name:
            problems += sorted({f"{name}:{_line_of(code, at)}: only configUsage.qml writes {key}" for at, key in hits})
            continue
        boxes = {}
        for start, body in _blocks(code, r"\bQQC2\s*\.\s*CheckBox\s*\{"):
            label = re.search(r'(?m)^\s*objectName\s*:\s*"(\w+)"\s*$', body)
            if label:
                boxes.setdefault(label.group(1), []).append((start, start + len(body)))
        for key, writer in USAGE_PAGE_WRITERS.items():
            at_key = [at for at, hit in hits if hit == key]
            if isinstance(writer, str):
                good = _hits(rf"(?m)^\s*onToggled\s*:\s*page\s*\.\s*cfg_{key}\s*=\s*checked\s*$", code)
                spans = boxes.get(writer, [])
                if len(spans) != 1 or len(at_key) != 1 or len(good) != 1 \
                        or not spans[0][0] <= at_key[0] < spans[0][1] or _line_of(code, at_key[0]) != good[0]:
                    problems.append(f"{name}: cfg_{key} only as `onToggled: page.cfg_{key} = checked` "
                                    f"in the {writer} CheckBox")
                continue
            helpers = [span for helper in writer
                       for span in _block_spans(code, rf"\bfunction\s+{helper}\s*\([^)]*\)\s*\{{")]
            if len(helpers) != len(writer):
                problems.append(f"{name}: {', '.join(writer)} must each be defined once")
            for at in at_key:
                if not any(start <= at < end for start, end in helpers):
                    problems.append(f"{name}:{_line_of(code, at)}: cfg_{key} is written only in {', '.join(writer)}")
            for start, end in helpers:
                if not any(start <= at < end for at in at_key):
                    problems.append(f"{name}:{_line_of(code, start)}: {', '.join(writer)} must write cfg_{key}")
    return problems


def test_usage_and_tooltip_settings_are_written_only_by_the_usage_page():
    problems = _usage_writer_problems(_all_code())
    assert not problems, problems


USAGE_WRITER_MUTATIONS = [
    (CONFIG_USAGE, "                        onToggled: page.cfg_tooltipShowsUsage = checked\n",
                   "                        onToggled: page.cfg_usageCompact = checked\n"),
    (CONFIG_USAGE, "onToggled: page.cfg_tooltipShowsUsage = checked", "onToggled: page.cfg_tooltipShowsUsage = true"),
    (CONFIG_USAGE, "onToggled: page.cfg_usageCompact = checked", "onToggled: page.cfg_usageCompact = !checked"),
    (CONFIG_USAGE, 'objectName: "usageCompactChoice"', 'objectName: "usageDenseChoice"'),
    (CONFIG_USAGE, "onToggled: page.setTooltipSame(checked)", 'onToggled: page.cfg_tooltipMetrics = ""'),
    (CONFIG_USAGE, "    function setTooltipSame(same) {\n",
     "    function clear() { page.cfg_tooltipShowsUsage = false }\n    function setTooltipSame(same) {\n"),
    (CONFIG_USAGE, "    function lastShownMetric(providerId, metricId) {\n",
     "    function reset() { page.cfg_providerMetrics = \"{}\" }\n    function lastShownMetric(providerId, metricId) {\n"),
    (CONFIG_USAGE, "        page.cfg_providerMetrics = JSON.stringify(metrics)\n", "\n"),
    (CONFIG_USAGE, "    function setThresholds(warn, critical) {\n",
     "    function setOrder() { page.cfg_providerOrder = \"\" }\n    function setThresholds(warn, critical) {\n"),
    (CONFIG_USAGE, "        page.cfg_usageCriticalPercent = next.critical\n", "\n"),
    (CONFIG_USAGE, "            page.cfg_usageWarnColor = value\n", "            page.cfg_usageNormalColor = value\n"),
    (CONFIG_USAGE, "    function setThresholds(warn, critical) {\n",
     "    function paint() { page.cfg_usageCriticalColor = \"#ff0000\" }\n    function setThresholds(warn, critical) {\n"),
    (CONFIG_GENERAL, "    property string cfg_usageNormalColorDefault: \"\"\n",
     "    property string cfg_usageNormalColorDefault: \"\"\n    function f() { page.cfg_usageNormalColor = \"#000000\" }\n"),
    (MAIN_QML, "    function chatNext() {",
     "    function x() { Plasmoid.configuration.usageWarnColor = \"\" }\n    function chatNext() {"),
    (CONFIG_USAGE, "    function moveProvider(providerId, direction) {\n",
     "    function warn() { page.cfg_usageWarnPercent++ }\n    function moveProvider(providerId, direction) {\n"),
    (CONFIG_GENERAL, "    property bool cfg_usageCompactDefault: false\n",
     "    property bool cfg_usageCompactDefault: false\n    function f() { page.cfg_usageCompact = true }\n"),
    (CONFIG_GENERAL, "if (values.usageCompact !== undefined) page.cfg_usageCompact = values.usageCompact",
     "if (values.usageCompact !== undefined) page.cfg_usageCompact = true"),
    (CONFIG_GENERAL, "if (values.usageCompact !== undefined) page.cfg_usageCompact = values.usageCompact",
     "if (values.usageCompact !== undefined) page.cfg_usageCompact = values.usageMode"),
    (CONFIG_GENERAL, "if (values.usageCompact !== undefined) page.cfg_usageCompact = values.usageCompact",
     "page.cfg_usageCompact = values.usageCompact"),
    (CONFIG_GENERAL, '        page.backupMessage = "applied"\n',
     '        page.cfg_tooltipMetrics = ""\n        page.backupMessage = "applied"\n'),
    (CONFIG_GENERAL, "    function backupStatusText() {\n",
     "    function applyBackup() { }\n    function backupStatusText() {\n"),
    (CONFIG_GENERAL, "    property bool cfg_tooltipShowsUsageDefault: true\n",
     "    property bool cfg_tooltipShowsUsageDefault: true\n    function f() { page.cfg_tooltipShowsUsage = false }\n"),
    (CONFIG_GENERAL, 'import "SettingsLogic.js" as SettingsLogic\n',
     'import "SettingsLogic.js" as SettingsLogic\nimport "TooltipLogic.js" as TooltipLogic\n'),
    (UI / "configChat.qml", "    property bool cfg_tooltipShowsUsageDefault: true\n",
     "    property bool cfg_tooltipShowsUsageDefault: true\n    function f() { page.cfg_tooltipShowsUsage = false }\n"),
    (UI / "configChat.qml", "    property string cfg_providerOrderDefault: \"\"\n",
     "    property string cfg_providerOrderDefault: \"\"\n    function f() { page.cfg_providerOrder = \"[]\" }\n"),
    (MAIN_QML, "    function chatNext() {",
     "    function x() { Plasmoid.configuration.tooltipMetrics = \"\" }\n    function chatNext() {"),
    (MAIN_QML, "    function chatNext() {",
     "    function x() { Plasmoid.configuration.providerMetrics = \"{}\" }\n    function chatNext() {"),
    (MAIN_QML, "    function chatNext() {",
     "    function x() { Plasmoid.configuration.providerOrder = \"\" }\n    function chatNext() {"),
    (MAIN_QML, "    function chatNext() {",
     "    function x() { Plasmoid.configuration.usageWarnPercent = 1 }\n    function chatNext() {"),
    (MAIN_QML, "    function chatNext() {",
     "    function x() { Plasmoid.configuration.usageCompact = true }\n    function chatNext() {"),
    (MAIN_QML, "    function chatNext() {", "    function x() { root.usageCriticalPercent = 1 }\n    function chatNext() {"),
    (USAGE_VIEW, "            onClicked: root.refresh()\n",
     "            onClicked: { Plasmoid.configuration.usageCompact = true; root.refresh() }\n"),
]


@pytest.mark.parametrize(("path", "old", "new"), USAGE_WRITER_MUTATIONS,
                         ids=[f"{path.name}:{index}" for index, (path, _, _) in enumerate(USAGE_WRITER_MUTATIONS)])
def test_proof_usage_writer_rule_catches(path, old, new):
    assert _usage_writer_problems(_sources_with(path, old, new))


# providerMetrics now defaults to "{}" (every reading shown) in main.xml and on every page.
def _provider_metrics_default_problems(entries, pages):
    problems = []
    if entries.get("providerMetrics") != {"group": "General", "type": "String", "default": "{}"}:
        problems.append(f"{_rel(MAIN_XML)}: providerMetrics must be String \"{{}}\", got {entries.get('providerMetrics')}")
    for name, code in pages.items():
        for prop in ("cfg_providerMetrics", "cfg_providerMetricsDefault"):
            value = re.findall(rf"(?m)^\s*property\s+(\w+)\s+{prop}\s*:\s*(.+?)\s*$", code)
            if value != [("string", '"{}"')]:
                problems.append(f"{name}: `property string {prop}: \"{{}}\"` once, got {value}")
    return problems


def test_provider_metrics_defaults_to_an_empty_object():
    problems = _provider_metrics_default_problems(
        _main_xml_entries(), {page.name: _read_code(page) for page in CONFIG_PAGES})
    assert not problems, problems


@pytest.mark.parametrize("page", CONFIG_PAGES, ids=lambda path: path.name)
@pytest.mark.parametrize("new", ['"{\\"claude\\": [\\"weekly\\"]}"', '""'])
def test_proof_provider_metrics_default_rule_catches(page, new):
    pages = {other.name: _read_code(other) for other in CONFIG_PAGES}
    pages[page.name] = _mutated(page, 'property string cfg_providerMetricsDefault: "{}"',
                                f"property string cfg_providerMetricsDefault: {new}")
    assert _provider_metrics_default_problems(_main_xml_entries(), pages)


def test_proof_provider_metrics_xml_default_is_caught():
    entries = _main_xml_entries()
    entries["providerMetrics"] = dict(entries["providerMetrics"], default='{"claude": ["weekly"]}')
    assert _provider_metrics_default_problems(entries, {})


def test_usage_logic_js_is_a_pure_library():
    problems = _alert_logic_problems(_read_code(USAGE_LOGIC_JS))
    assert not problems, f"{_rel(USAGE_LOGIC_JS)}: {problems}"


@pytest.mark.parametrize("snippet", [
    '.import "SnapshotLogic.js" as SnapshotLogic',
    "function f() { return Qt.formatDateTime(new Date()) }",
    "function f() { console.log(1) }",
    "function f() { return new XMLHttpRequest() }",
    "function f() { return Plasmoid.configuration.providerOrder }",
])
def test_proof_usage_logic_rule_catches(snippet):
    assert _alert_logic_problems(_read_code(USAGE_LOGIC_JS) + "\n" + snippet + "\n")


def test_proof_usage_logic_needs_pragma():
    code = re.sub(r"^\s*\.pragma\s+library\b", "", _read_code(USAGE_LOGIC_JS), count=1)
    assert _alert_logic_problems(code)


# The Usage tab's Refresh button only asks main.qml for a refresh (which
# itself returns at once while Usage is hidden), and the "Updated" line
# next to it is plain text.
USAGE_REFRESH_CLICK = r"(?m)^\s*onClicked\s*:\s*root\s*\.\s*refresh\s*\(\s*\)\s*$"


def _usage_refresh_problems(code):
    problems = []
    buttons = [body for _, body in _blocks(code, r"\bPlasmaComponents\s*\.\s*ToolButton\s*\{")
               if re.search(r'(?m)^\s*objectName\s*:\s*"usageRefreshButton"\s*$', body)]
    if len(buttons) != 1:
        return [f"UsageView.qml: one usageRefreshButton ToolButton, found {len(buttons)}"]
    button = _strip_comments(buttons[0], blank_strings=True)
    calls = re.findall(r"([\w.]+)\s*\(", button)
    if len(_hits(USAGE_REFRESH_CLICK, buttons[0])) != 1 or len(_hits(r"\bon[A-Z]\w*\s*:", button)) != 1 \
            or sorted(calls) != ["i18n", "root.refresh"]:
        problems.append("UsageView.qml: usageRefreshButton does only `onClicked: root.refresh()`")
    if len(re.findall(r"\brefresh\s*\(", code)) != 1:
        problems.append("UsageView.qml: root.refresh() only from usageRefreshButton")
    labels = [_top_level(body) for _, body in _blocks(code, TEXT_ELEMENT)
              if re.search(r'(?m)^\s*objectName\s*:\s*"usageUpdatedLabel"\s*$', body)]
    if len(labels) != 1 or len(re.findall(PLAIN_TEXT_FORMAT, labels[0])) != 1:
        problems.append("UsageView.qml: usageUpdatedLabel must be one label with `textFormat: Text.PlainText`")
    return problems


def test_usage_refresh_button_only_refreshes():
    problems = _usage_refresh_problems(_read_code(USAGE_VIEW))
    assert not problems, problems


@pytest.mark.parametrize(("old", "new"), [
    ("            onClicked: root.refresh()\n", "            onClicked: { root.refreshInFlight = true; root.refresh() }\n"),
    ("            onClicked: root.refresh()\n", "            onClicked: root.refresh()\n            onPressed: root.chatNext()\n"),
    ("            onClicked: root.refresh()\n", "            onClicked: Qt.openUrlExternally(\"https://example.invalid\")\n"),
    ('            objectName: "usageRefreshButton"\n', '            objectName: "refreshButton"\n'),
    ("            textFormat: Text.PlainText\n            text: usage.updatedText(",
     "            textFormat: Text.StyledText\n            text: usage.updatedText("),
    ("            textFormat: Text.PlainText\n            text: usage.updatedText(", "            text: usage.updatedText("),
])
def test_proof_usage_refresh_rule_catches(old, new):
    assert _usage_refresh_problems(_mutated(USAGE_VIEW, old, new))


def test_tooltip_logic_js_is_a_pure_library():
    problems = _alert_logic_problems(_read_code(TOOLTIP_LOGIC_JS))
    assert not problems, f"{_rel(TOOLTIP_LOGIC_JS)}: {problems}"


@pytest.mark.parametrize("snippet", [
    '.import "SnapshotLogic.js" as SnapshotLogic',
    "function f() { return Qt.formatDateTime(new Date()) }",
    "function f() { console.log(1) }",
    "function f() { return new XMLHttpRequest() }",
    "function f() { return Plasmoid.configuration.tooltipMetrics }",
])
def test_proof_tooltip_logic_rule_catches(snippet):
    assert _alert_logic_problems(_read_code(TOOLTIP_LOGIC_JS) + "\n" + snippet + "\n")


def test_proof_tooltip_logic_needs_pragma():
    code = re.sub(r"^\s*\.pragma\s+library\b", "", _read_code(TOOLTIP_LOGIC_JS), count=1)
    assert _alert_logic_problems(code)


# The hover popup shows no reset times, so it has no clock of its own.
def test_hover_popup_has_no_reset_clock():
    sources = _all_code()
    problems = [f"{name}:{line}" for name, code in sources.items()
                for line in _hits(r"\b(?:tooltipNowMs|tooltipShowsReset|resetPhrase)\b", code)]
    assert not problems, f"the hover popup's reset times were removed; found {problems}"


# Settings schema 2 -> 3 runs once: main.qml migrates the reading choices
# only for a set-up widget still below 3, then stamps 3. main.xml and every
# page keep the default 2 (a default of 3 would skip the migration for
# upgrading users), and a page only ever stamps 3, never 2 (2 would run the
# migration again and wipe the Usage tab choices).
MIGRATION_CALL = (r"\bif\s*\(\s*Plasmoid\s*\.\s*configuration\s*\.\s*initialSetupComplete\s*&&\s*"
                  r"Number\s*\(\s*Plasmoid\s*\.\s*configuration\s*\.\s*configSchemaVersion\s*\)\s*<\s*3\s*\)\s*"
                  r"root\s*\.\s*migrateUsageMetrics\s*\(\s*\)\s*;?\s*"
                  r"if\s*\(\s*Plasmoid\s*\.\s*configuration\s*\.\s*configSchemaVersion\s*!==\s*3\s*\)\s*"
                  r"Plasmoid\s*\.\s*configuration\s*\.\s*configSchemaVersion\s*=\s*3\b")
ON_COMPLETED = r"\bComponent\s*\.\s*onCompleted\s*:\s*\{"


def _main_migration_problems(sources):
    problems = []
    for name, code in sources.items():
        if _base(name) != MAIN_QML.name and re.search(r"\bmigrateUsageMetrics\b", code):
            problems.append(f"{name}: migrateUsageMetrics belongs to main.qml")
    main = sources[_rel(MAIN_QML)]
    body = _function_body(main, "migrateUsageMetrics")
    if body is None:
        return problems + ["main.qml: `function migrateUsageMetrics(` must be defined once"]
    if len(re.findall(r"\bvar\s+next\s*=\s*UsageLogic\s*\.\s*migratedUsageMetrics\s*\(", body)) != 1:
        problems.append("main.qml: migrateUsageMetrics takes its values from UsageLogic.migratedUsageMetrics")
    for key in MIGRATED_KEYS:
        writes = _hits(rf"\bPlasmoid\s*\.\s*configuration\s*\.\s*{key}\s*(?:\+\+|--|(?:[-+*/%&|^]|\?\?)?=(?!=))", main)
        good = _hits(rf"\bif\s*\(\s*Plasmoid\s*\.\s*configuration\s*\.\s*{key}\s*!==\s*next\s*\.\s*{key}\s*\)\s*"
                     rf"Plasmoid\s*\.\s*configuration\s*\.\s*{key}\s*=\s*next\s*\.\s*{key}\s*;?\s*(?m:$)", body)
        if len(writes) != 1 or len(good) != 1 or len(_hits(rf"\bconfiguration\s*\.\s*{key}\s*=(?!=)", body)) != 1:
            problems.append(f"main.qml: {key} is written once, as `Plasmoid.configuration.{key} = next.{key}` "
                            "in migrateUsageMetrics")
    completed = [body for _, body in _blocks(main, ON_COMPLETED)]
    if len(re.findall(r"\bmigrateUsageMetrics\s*\(", main)) != 2 or len(completed) != 1 \
            or len(re.findall(MIGRATION_CALL, completed[0])) != 1:
        problems.append("main.qml: migrateUsageMetrics() runs once, from Component.onCompleted, under "
                        "`initialSetupComplete && Number(configSchemaVersion) < 3`, right before stamping 3")
    if len(_hits(r"\bconfiguration\s*\.\s*configSchemaVersion\s*=(?!=)", main)) != 1:
        problems.append("main.qml: configSchemaVersion is written only as the stamp to 3")
    return problems


def test_main_migrates_usage_metrics_once():
    problems = _main_migration_problems(_all_code())
    assert not problems, problems


MIGRATION_MUTATIONS = [
    (MAIN_QML, "    function chatNext() {",
     "    function x() { Plasmoid.configuration.providerMetrics = \"{}\" }\n    function chatNext() {"),
    (MAIN_QML, "    function chatNext() {",
     "    function x() { Plasmoid.configuration.tooltipMetrics = \"\" }\n    function chatNext() {"),
    (MAIN_QML, " && Number(Plasmoid.configuration.configSchemaVersion) < 3)\n            root.migrateUsageMetrics()",
     ")\n            root.migrateUsageMetrics()"),
    (MAIN_QML, "Number(Plasmoid.configuration.configSchemaVersion) < 3)", "Number(Plasmoid.configuration.configSchemaVersion) < 4)"),
    (MAIN_QML, "        if (Plasmoid.configuration.initialSetupComplete && Number(",
     "        root.migrateUsageMetrics()\n        if (Plasmoid.configuration.initialSetupComplete && Number("),
    (MAIN_QML, "    function chatNext() {", "    function x() { root.migrateUsageMetrics() }\n    function chatNext() {"),
    (MAIN_QML, "Plasmoid.configuration.tooltipMetrics = next.tooltipMetrics", 'Plasmoid.configuration.tooltipMetrics = ""'),
    (MAIN_QML, "Plasmoid.configuration.providerMetrics = next.providerMetrics",
     'Plasmoid.configuration.providerMetrics = "{}"'),
    (MAIN_QML, "Plasmoid.configuration.providerMetrics = next.providerMetrics",
     "Plasmoid.configuration.providerMetrics = next.tooltipMetrics"),
    (MAIN_QML, "            Plasmoid.configuration.providerMetrics = next.providerMetrics\n",
     "            Plasmoid.configuration.providerMetrics = next.providerMetrics\n"
     "        Plasmoid.configuration.providerMetrics = next.providerMetrics\n"),
    (MAIN_QML, "UsageLogic.migratedUsageMetrics(", "UsageLogic.normalizeOrder("),
    (MAIN_QML, "        if (Plasmoid.configuration.configSchemaVersion !== 3)\n"
     "            Plasmoid.configuration.configSchemaVersion = 3\n", ""),
    (MAIN_QML, "    function chatNext() {",
     "    function x() { Plasmoid.configuration.configSchemaVersion = 2 }\n    function chatNext() {"),
    (CONFIG_USAGE, "        page.cfg_configSchemaVersion = 3\n",
     "        page.cfg_configSchemaVersion = 3\n        root.migrateUsageMetrics()\n"),
]


@pytest.mark.parametrize(("path", "old", "new"), MIGRATION_MUTATIONS,
                         ids=[f"{path.name}:{index}" for index, (path, _, _) in enumerate(MIGRATION_MUTATIONS)])
def test_proof_main_migration_rule_catches(path, old, new):
    assert _main_migration_problems(_sources_with(path, old, new))


def _schema_version_problems(entries, sources):
    problems = []
    if entries.get("configSchemaVersion") != {"group": "General", "type": "Int", "default": "2"}:
        problems.append(f"{_rel(MAIN_XML)}: configSchemaVersion must stay Int 2, got {entries.get('configSchemaVersion')}")
    for name, code in sources.items():
        if _base(name) in {page.name for page in CONFIG_PAGES}:
            for prop in ("cfg_configSchemaVersion", "cfg_configSchemaVersionDefault"):
                value = re.findall(rf"(?m)^\s*property\s+(\w+)\s+{prop}\s*:\s*(.+?)\s*$", code)
                if value != [("int", "2")]:
                    problems.append(f"{name}: `property int {prop}: 2` once, got {value}")
        writes = [match.start() for match in re.finditer(
            r"\bcfg_configSchemaVersion\s*(?:\+\+|--|(?:[-+*/%&|^]|\?\?)?=(?!=))", code)]
        if _base(name) != CONFIG_USAGE.name:
            problems += [f"{name}:{_line_of(code, at)}: only configUsage.qml stamps cfg_configSchemaVersion"
                         for at in writes]
            continue
        completed = _block_spans(code, ON_COMPLETED)
        good = _hits(r"(?m)^[ \t]*page\s*\.\s*cfg_configSchemaVersion\s*=\s*3\s*;?\s*$", code)
        if len(writes) != 1 or len(completed) != 1 or len(good) != 1 \
                or not completed[0][0] <= writes[0] < completed[0][1] or _line_of(code, writes[0]) != good[0]:
            problems.append(f"{name}: cfg_configSchemaVersion only as `page.cfg_configSchemaVersion = 3` "
                            "in Component.onCompleted (never 2)")
    return problems


def test_schema_version_defaults_to_2_and_pages_stamp_only_3():
    problems = _schema_version_problems(_main_xml_entries(), _all_code())
    assert not problems, problems


SCHEMA_VERSION_MUTATIONS = [
    (CONFIG_USAGE, "        page.cfg_configSchemaVersion = 3\n", "        page.cfg_configSchemaVersion = 2\n"),
    (CONFIG_USAGE, "        page.cfg_configSchemaVersion = 3\n", ""),
    (CONFIG_USAGE, "    function detectProviders() {\n",
     "    function reset() { page.cfg_configSchemaVersion = 3 }\n    function detectProviders() {\n"),
    (CONFIG_USAGE, "    property int cfg_configSchemaVersionDefault: 2\n", "    property int cfg_configSchemaVersionDefault: 3\n"),
    (CONFIG_USAGE, "    property int cfg_configSchemaVersion: 2\n", "    property int cfg_configSchemaVersion: 3\n"),
    (CONFIG_PAGES[0], "    property int cfg_configSchemaVersion: 2\n", "    property int cfg_configSchemaVersion: 3\n"),
    (UI / "configChat.qml", "    property int cfg_configSchemaVersionDefault: 2\n",
     "    property int cfg_configSchemaVersionDefault: 3\n"),
    (UI / "configChat.qml", "    property int cfg_configSchemaVersionDefault: 2\n",
     "    property int cfg_configSchemaVersionDefault: 2\n    function f() { page.cfg_configSchemaVersion = 2 }\n"),
]


@pytest.mark.parametrize(("path", "old", "new"), SCHEMA_VERSION_MUTATIONS,
                         ids=[f"{path.name}:{index}" for index, (path, _, _) in enumerate(SCHEMA_VERSION_MUTATIONS)])
def test_proof_schema_version_rule_catches(path, old, new):
    assert _schema_version_problems(_main_xml_entries(), _sources_with(path, old, new))


def test_proof_schema_version_xml_default_3_is_caught():
    entries = _main_xml_entries()
    entries["configSchemaVersion"] = dict(entries["configSchemaVersion"], default="3")
    assert _schema_version_problems(entries, {})


# --- M1 (pentest 2026-11-05): no dynamic names, no accepts, pinned handlers ---
#
# Earlier rules looked for names such as `.grant(` or `offTheRecord: false`,
# so `permission["gr" + "ant"]()`, `error.acceptCertificate()`, `page.settings.
# javascriptCanPaste = true` or an extra `|| verdict === "block"` passed. These
# rules close that: in the files that can reach a web page or its profile no
# member is picked by a computed name (only the listed loop-index uses of
# local arrays); names of trusted members can't be built from strings; the
# accepting calls exist only where the user saves a download; no pinned
# setting or profile property is ever assigned; and the four security
# handlers have exactly their reviewed shape.

# Files that hold the web view or reach it (ChatView.web, FullRepresentation's
# chatView). Nothing else can touch a WebEngine object.
WEBENGINE_FILES = (CHAT_WEB_VIEW, CHAT_VIEW, FULL_REPRESENTATION)
# The only computed member accesses: (receiver, key) of local arrays indexed by
# a loop counter, and the pair entries panes[index][0] / [1].
COMPUTED_ACCESS_ALLOWED = {
    "ChatWebView.qml": {("views", "index"), ("panes", "index"), ("files", "index"), ("panes", "at"),
                        ("panes[index]", "0"), ("panes[index]", "1")},
}
# Receivers and counters above are only ever set like this (normalized lines).
COMPUTED_NAMES = ("views", "panes", "files", "index", "at")
COMPUTED_NAME_SETTERS = (
    r"var views = chatWeb\.viewList\(\)",
    r"var views = \[\]",
    r'var panes = \[\["a", chatWeb\.siteId\], \["b", chatWeb\.splitActive \? chatWeb\.siteIdB : ""\]\]',
    r'var panes = chatWeb\.splitActive \? \["a", "b"\] : \["a"\]',
    r"var files = uploadDialog\.selectedFiles",
    r"for \(var index = 0; index < (?:views\.length|panes\.length|pages\.count|files\.length); index\+\+\)(?: \{)?",
    r"for \(var index = visitedSites\.count - 1; index >= 0; index--\) \{",
    r"for \(var at = 0; at < panes\.length; at\+\+\) \{",
    r"for \(var at = item; at; at = at\.parent\) \{",
)
_JS_KEYWORDS_BEFORE_ARRAY = {"return", "typeof", "in", "of", "case", "else", "do", "void", "new", "delete",
                             "yield", "await", "instanceof", "throw"}
WEBENGINE_DYNAMIC_BANS = {
    "eval": r"\beval\b",
    "Reflect": r"\bReflect\b",
    "Function constructor": r"\bFunction\b",
    "with statement": r"\bwith\s*\(",
    "Object property writers": r"\bObject\s*\.\s*(?:assign|defineProperty|defineProperties|setPrototypeOf|fromEntries)\b",
    "Proxy": r"\bProxy\b",
}
# WebEngine settings and profile properties: declared once, never assigned.
PINNED_SETTINGS = ("screenCaptureEnabled", "pluginsEnabled", "dnsPrefetchEnabled", "navigateOnDropEnabled",
                   "localContentCanAccessFileUrls", "allowRunningInsecureContent",
                   "javascriptCanAccessClipboard", "javascriptCanPaste", "focusOnNavigationEnabled",
                   "unknownUrlSchemePolicy")
PINNED_PROFILE = tuple(name for name, _ in PROFILE_BINDINGS)
PERMISSION_HANDLER = "{ permission.deny() }"
CERTIFICATE_HANDLER = "{ error.rejectCertificate() }"
DOWNLOAD_HANDLER = (
    "{ if (download.isSavePageDownload || chatWeb.pendingDownload !== null) { download.cancel() return } "
    "chatWeb.pendingDownload = download chatWeb.pendingDownloadName = download.downloadFileName "
    "var source = download.view && typeof download.view.site === \"string\" "
    "? ChatSites.byId(download.view.site) : null "
    "chatWeb.pendingDownloadSite = source ? source.name : \"\" downloadTimeout.restart() }"
)
SAVE_DOWNLOAD = ("{ var download = chatWeb.pendingDownload chatWeb.clearPendingDownload() "
                 "if (download) download.accept() }")
NAV_HEAD = (
    "{ var verdict = ChatSites.classifyNavigation({ url: request.url.toString(), "
    "isMainFrame: request.isMainFrame, linkClicked: request.navigationType "
    "=== WebEngineNavigationRequest.LinkClickedNavigation, siteId: page.site, "
    "customUrls: chatWeb.customUrls }) if (verdict === \"allow\") {"
)
NAV_TAIL = " request.reject() if (verdict === \"external\") chatWeb.askExternal(request.url.toString()) }"


def _normalized(text):
    return re.sub(r"\s+", " ", text).strip()


def _computed_access_problems(name, code):
    """Computed member access, computed object keys and setters of the allowed names."""
    problems = []
    blanked = _strip_comments(code, blank_strings=True)
    allowed = COMPUTED_ACCESS_ALLOWED.get(_base(name), set())
    for match in re.finditer(r"\[", blanked):
        start = match.start()
        before = blanked[:start].rstrip()
        end = start
        depth = 0
        for end in range(start, len(blanked)):
            if blanked[end] == "[":
                depth += 1
            elif blanked[end] == "]":
                depth -= 1
                if depth == 0:
                    break
        key = code[start + 1:end].strip()
        last = before[-1:] if before else ""
        word = re.search(r"[\w$]+$", before)
        access = last in (")", "]") or (word is not None and word.group(0) not in _JS_KEYWORDS_BEFORE_ARRAY
                                        and not word.group(0).isdigit())
        line = _line_of(code, start)
        if not access:
            if last in ("{", ",") and re.match(r"\s*:", blanked[end + 1:]):
                problems.append(f"{name}:{line}: computed object key [{key}]")
            continue
        if last == "]":
            receiver = re.search(r"([\w$]+)\s*\[\s*([\w$]+)\s*\]$", before)
            receiver = f"{receiver.group(1)}[{receiver.group(2)}]" if receiver else "?"
            dotted = re.search(r"\.\s*[\w$]+\s*\[\s*[\w$]+\s*\]$", before) is not None
        elif last == ")":
            receiver, dotted = "(...)", True
        else:
            receiver = word.group(0)
            dotted = re.search(r"\.\s*[\w$]+$", before) is not None
        if dotted or (receiver, key) not in allowed:
            problems.append(f"{name}:{line}: computed member access {receiver}[{key}]")
    # The allowed receivers and counters are set only as pinned.
    setter = r"(?<![\w$.])(?:views|panes|files|index|at)\s*(?:=(?!=)|\+\+|--|[-+*/%&|^]=|<<=|>>>?=)" \
             r"|(?:\+\+|--)\s*(?:index|at)\b"
    lines = sorted({_line_of(blanked, hit.start()) for hit in re.finditer(setter, blanked)})
    code_lines = code.splitlines()
    for line in lines:
        text = _normalized(code_lines[line - 1])
        if not any(re.fullmatch(pattern, text) for pattern in COMPUTED_NAME_SETTERS):
            problems.append(f"{name}:{line}: index/receiver name set outside the pinned loops: {text}")
    names = "|".join(COMPUTED_NAMES)
    for line in _hits(rf"(?<![\w$.])(?:{names})\s+(?:in|of)\b", blanked):
        problems.append(f"{name}:{line}: for-in/of over a pinned name")
    for params in re.finditer(r"(?:\bfunction\b\s*[\w$]*\s*\(([^)]*)\)|\(([^)]*)\)\s*=>|\bcatch\s*\(([^)]*)\))",
                              blanked):
        listed = params.group(1) or params.group(2) or params.group(3) or ""
        if re.search(rf"(?<![\w$])(?:{names})(?![\w$])", listed):
            problems.append(f"{name}:{_line_of(blanked, params.start())}: parameter named like a pinned name")
    return problems


def _dynamic_name_problems(sources):
    problems = []
    for path in WEBENGINE_FILES:
        name = _rel(path)
        code = sources.get(name, "")
        problems += _computed_access_problems(name, code)
        for rule, pattern in WEBENGINE_DYNAMIC_BANS.items():
            problems += [f"{name}:{line}: {rule}" for line in _hits(pattern, code)]
        problems += [f"{name}:{line}: template literal" for line in _hits(r"`", code)]
        # Names must not be built from pieces of strings.
        literal = r"""(?:"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')"""
        problems += [f"{name}:{line}: string literals concatenated"
                     for line in _hits(rf"{literal}\s*\+\s*{literal}", code)]
    return problems


def _accept_problems(sources):
    problems = []
    for name, code in sources.items():
        problems += [f"{name}:{line}: acceptCertificate" for line in _hits(r"acceptCertificate", code)]
    web_name = _rel(CHAT_WEB_VIEW)
    web = sources.get(web_name, "")
    save = _function_body(web, "saveDownload")
    if save is None or _normalized(save) != SAVE_DOWNLOAD:
        problems.append(f"ChatWebView.saveDownload must be exactly `{SAVE_DOWNLOAD}`")
    for path in WEBENGINE_FILES:
        name = _rel(path)
        code = sources.get(name, "")
        for match in re.finditer(r"\.\s*accept\b", code):
            inside = save is not None and name == web_name and web.find(save) <= match.start() < web.find(save) + len(save)
            if not inside:
                problems.append(f"{name}:{_line_of(code, match.start())}: .accept outside saveDownload")
    calls = [(name, match.start()) for name, code in sources.items()
             for match in re.finditer(r"\bsaveDownload\b", code)]
    view = sources.get(_rel(CHAT_VIEW), "")
    good = [(name, offset) for name, offset in calls
            if name == _rel(CHAT_VIEW)
            and re.search(r"(?m)^\s*onTriggered\s*:\s*chatView\s*\.\s*web\s*\.\s*$", view[:offset].splitlines()[-1] + "\n"[:0])
            and re.match(r"saveDownload\s*\(\s*\)\s*$", view[offset:].split("\n", 1)[0])]
    defined = [(name, offset) for name, offset in calls
               if name == web_name and re.search(r"\bfunction\s+$", web[:offset])]
    if len(good) != 1 or len(defined) != 1 or len(calls) != 2:
        problems.append("saveDownload is defined once and called only by `onTriggered: chatView.web.saveDownload()`")
    return problems


def _pinned_assignment_problems(sources):
    problems = []
    names = "|".join(PINNED_SETTINGS + PINNED_PROFILE)
    for name, code in sources.items():
        problems += [f"{name}:{line}: assigns a pinned WebEngine property"
                     for line in _hits(rf"\b(?:{names})\s*(?:=(?!=)|[-+*/%&|^]=|\+\+|--)", code)]
    web = sources.get(_rel(CHAT_WEB_VIEW), "")
    for setting in PINNED_SETTINGS:
        if len(_hits(rf"\b{setting}\b", web)) != 1 or len(_hits(rf"(?m)^\s*settings\s*\.\s*{setting}\s*:", web)) != 1:
            problems.append(f"ChatWebView.qml: {setting} must appear once, as its `settings.{setting}:` binding")
        for name, code in sources.items():
            if name != _rel(CHAT_WEB_VIEW) and _hits(rf"\b{setting}\b", code):
                problems.append(f"{name}: names the WebEngine setting {setting}")
    for prop in PINNED_PROFILE:
        if len(_hits(rf"\b{prop}\b", web)) != 1:
            problems.append(f"ChatWebView.qml: {prop} must appear once, inside the profile block")
    return problems


def _security_handler_problems(web):
    problems = []
    for signal, expected in (("onPermissionRequested", PERMISSION_HANDLER),
                             ("onCertificateError", CERTIFICATE_HANDLER)):
        bodies = [body for _, body in _handler_bodies(web, signal)]
        if [_normalized(body) for body in bodies] != [expected]:
            problems.append(f"{signal} must be exactly `{expected}` once, got {[_normalized(b) for b in bodies]}")
    downloads = [body for _, body in _handler_bodies(web, "onDownloadRequested")]
    if [_normalized(body) for body in downloads] != [_normalized(DOWNLOAD_HANDLER)]:
        problems.append("onDownloadRequested must keep the download pending (exact reviewed body)")
    navs = [body for _, body in _blocks(web, NAV_HANDLER)]
    if len(navs) != 1:
        return problems + [f"exactly one onNavigationRequested handler, found {len(navs)}"]
    body = navs[0]
    blanked = _strip_comments(body, blank_strings=True)
    opener = re.search(r'if\s*\(\s*verdict\s*===\s*"allow"\s*\)\s*\{', body)
    if not opener:
        return problems + ['onNavigationRequested must test `if (verdict === "allow") {` literally']
    brace = opener.end() - 1
    end = _brace_end(blanked, brace)
    head, allow, tail = body[:brace + 1], body[brace + 1:end - 1], body[end:]
    if _normalized(head) != NAV_HEAD:
        problems.append(f"onNavigationRequested must start exactly `{NAV_HEAD}`, got `{_normalized(head)}`")
    if _normalized(" " + tail) != _normalized(NAV_TAIL):
        problems.append(f"onNavigationRequested must reject every other verdict: `...}}{NAV_TAIL}`, "
                        f"got `{_normalized(tail)}`")
    if re.search(r"\bverdict\b", allow):
        problems.append("onNavigationRequested: the allow branch must not look at verdict again")
    if not re.search(r"\breturn\s*$", allow.rstrip()):
        problems.append("onNavigationRequested: the allow branch must end with return")
    return problems


def _m1_problems(sources):
    web = sources.get(_rel(CHAT_WEB_VIEW), "")
    return (_dynamic_name_problems(sources) + _accept_problems(sources)
            + _pinned_assignment_problems(sources) + _security_handler_problems(web))


def test_webengine_files_use_no_computed_names():
    problems = _dynamic_name_problems(_all_code())
    assert not problems, problems


def test_certificates_and_downloads_are_never_accepted_by_code():
    problems = _accept_problems(_all_code())
    assert not problems, problems


def test_pinned_webengine_properties_are_never_assigned():
    problems = _pinned_assignment_problems(_all_code())
    assert not problems, problems


def test_security_handlers_have_their_reviewed_shape():
    problems = _security_handler_problems(_read_code(CHAT_WEB_VIEW))
    assert not problems, problems


# Each case is one way around the rules; the first seven are the pentest's
# bypasses that passed the whole suite before (2026-11-05).
M1_MUTATIONS = [
    # 1 grant
    (CHAT_WEB_VIEW, "                permission.deny()\n",
     "                if (permission.permissionType < 0) permission.deny(); else permission[\"gr\" + \"ant\"]()\n"),
    # 2 cert
    (CHAT_WEB_VIEW, "error.rejectCertificate()", "error.acceptCertificate()"),
    # 3 nav
    (CHAT_WEB_VIEW, 'if (verdict === "allow") {', 'if (verdict === "allow" || verdict === "block") {'),
    # 4 download
    (CHAT_WEB_VIEW, "            chatWeb.pendingDownload = download\n", "            download.accept()\n"),
    # 5 runjs2
    (CHAT_WEB_VIEW, "            onLoadingChanged: (loadingInfo) => {\n",
     "            onLoadingChanged: (loadingInfo) => {\n"
     "                if (loadingInfo.status === WebEngineLoadingInfo.LoadSucceededStatus)\n"
     "                    page[\"runJava\" + \"Script\"](\"document.cookie\", function (c) { chatWeb.externalHost = String(c) })\n"),
    # 6 clipboard
    (CHAT_WEB_VIEW, "                page.homeUrl = ChatSites.homeUrl(page.site, chatWeb.customUrls)\n",
     "                page.homeUrl = ChatSites.homeUrl(page.site, chatWeb.customUrls)\n"
     "                page.settings.javascriptCanAccessClipboard = true\n"
     "                page.settings.javascriptCanPaste = true\n"
     "                page.settings.localContentCanAccessFileUrls = true\n"),
    # 7 offrecord2
    (CHAT_WEB_VIEW, "        chatWeb.syncViews()\n    }\n\n    Component.onDestruction",
     "        chatWeb.syncViews()\n        chatProfile[\"persistentCookies\" + \"Policy\"] = 2\n"
     "        chatProfile[\"offThe\" + \"Record\"] = false\n    }\n\n    Component.onDestruction"),
    # computed names in other spellings and files
    (CHAT_WEB_VIEW, "                permission.deny()\n",
     "                var name = \"grant\"\n                permission[name]()\n"),
    (CHAT_WEB_VIEW, "                permission.deny()\n", "                permission.deny()\n                (permission)[\"grant\"]()\n"),
    (CHAT_WEB_VIEW, "                permission.deny()\n",
     "                permission.deny()\n                var p = { [\"gr\" + \"ant\"]: 1 }\n"),
    (CHAT_WEB_VIEW, "            if (views[index] !== view)", "            if (views[index + 0] !== view)"),
    (CHAT_WEB_VIEW, "            if (views[index] !== view)", "            if (chatWeb.views[index] !== view)"),
    (CHAT_WEB_VIEW, "        var views = chatWeb.viewList()\n        var urls = []",
     "        var views = chatProfile\n        var urls = []"),
    (CHAT_WEB_VIEW, "        for (var index = 0; index < views.length; index++) {\n            if (views[index] !== view)",
     "        for (var index = \"offTheRecord\"; index < views.length; index++) {\n            if (views[index] !== view)"),
    (CHAT_WEB_VIEW, "                permission.deny()\n",
     "                permission.deny()\n                for (var index in permission) {}\n"),
    (CHAT_WEB_VIEW, "    function viewFor(siteId, pane) {", "    function viewFor(siteId, pane, index) {"),
    (CHAT_WEB_VIEW, "                permission.deny()\n", "                permission.deny()\n                eval(\"1\")\n"),
    (CHAT_WEB_VIEW, "                permission.deny()\n",
     "                permission.deny()\n                Reflect.get(permission, \"deny\")\n"),
    (CHAT_WEB_VIEW, "                page.homeUrl = ChatSites.homeUrl(page.site, chatWeb.customUrls)\n",
     "                page.homeUrl = ChatSites.homeUrl(page.site, chatWeb.customUrls)\n"
     "                Object.assign(page.settings, { pluginsEnabled: true })\n"),
    (CHAT_WEB_VIEW, "                permission.deny()\n",
     "                permission.deny()\n                var f = new Function(\"p\", \"p.deny()\")\n"),
    (CHAT_WEB_VIEW, "                permission.deny()\n", "                permission.deny()\n                var t = `x`\n"),
    (CHAT_WEB_VIEW, "                permission.deny()\n", "                permission.deny()\n                var s = \"gr\" + 'ant'\n"),
    (CHAT_VIEW, "onTriggered: chatView.web.cancelDownload()", "onTriggered: chatView.web[\"saveDownload\"]()"),
    (FULL_REPRESENTATION, "onClicked: chatView.openExternally()", "onClicked: chatView[\"web\"].saveDownload()"),
    # accepting calls
    (CHAT_WEB_VIEW, "                request.reject()\n                if (verdict === \"external\")",
     "                request.accept()\n                if (verdict === \"external\")"),
    (CHAT_WEB_VIEW, "            downloadTimeout.restart()\n        }",
     "            downloadTimeout.restart()\n            Qt.callLater(download.accept)\n        }"),
    (CHAT_WEB_VIEW, "            downloadTimeout.restart()\n        }",
     "            downloadTimeout.restart()\n            chatWeb.saveDownload()\n        }"),
    (CHAT_WEB_VIEW, "        if (download)\n            download.accept()\n    }",
     "        download.accept()\n    }"),
    (CHAT_VIEW, "onTriggered: chatView.web.cancelDownload()", "onTriggered: chatView.web.saveDownload()"),
    (MAIN_QML, "    function chatNext() {", "    property string x: \"acceptCertificate\"\n    function chatNext() {"),
    # pinned properties
    (CHAT_WEB_VIEW, "                page.homeUrl = ChatSites.homeUrl(page.site, chatWeb.customUrls)\n",
     "                page.homeUrl = ChatSites.homeUrl(page.site, chatWeb.customUrls)\n"
     "                var s = page.settings\n                s.pluginsEnabled = true\n"),
    (CHAT_WEB_VIEW, "        chatWeb.syncViews()\n    }\n\n    Component.onDestruction",
     "        chatWeb.syncViews()\n        chatProfile.persistentPermissionsPolicy = 0\n    }\n\n    Component.onDestruction"),
    (CHAT_WEB_VIEW, "        chatWeb.syncViews()\n    }\n\n    Component.onDestruction",
     "        chatWeb.syncViews()\n        chatProfile.spellCheckEnabled = true\n    }\n\n    Component.onDestruction"),
    (CHAT_WEB_VIEW, "            settings.focusOnNavigationEnabled: false\n",
     "            settings.focusOnNavigationEnabled: false\n            settings.javascriptCanPaste: true\n"),
    (CHAT_VIEW, "onTriggered: chatView.web.cancelDownload()",
     "onTriggered: chatView.web.currentView.settings.pluginsEnabled = true"),
    # handler shapes
    (CHAT_WEB_VIEW, '                if (verdict === "allow") {',
     '                if (verdict === "block")\n                    return\n                if (verdict === "allow") {'),
    (CHAT_WEB_VIEW, 'if (verdict === "allow") {', 'if ("allow" === verdict) {'),
    (CHAT_WEB_VIEW, 'if (verdict === "allow") {', 'if (verdict == "allow") {'),
    (CHAT_WEB_VIEW, "                request.reject()\n                if (verdict === \"external\")",
     "                if (verdict === \"external\")"),
    (CHAT_WEB_VIEW, "                    page.checkUserAgent(request)\n                    return\n",
     "                    page.checkUserAgent(request)\n                    return\n                    if (verdict) {}\n"),
    (CHAT_WEB_VIEW, "                permission.deny()\n", "                if (permission.isValid)\n                    permission.deny()\n"),
    (CHAT_WEB_VIEW, "                error.rejectCertificate()\n", "                error.defer()\n"),
    (CHAT_WEB_VIEW, "            if (download.isSavePageDownload || chatWeb.pendingDownload !== null) {",
     "            if (chatWeb.pendingDownload !== null) {"),
]


@pytest.mark.parametrize(("path", "old", "new"), M1_MUTATIONS,
                         ids=[f"{path.name}:{index}" for index, (path, _, _) in enumerate(M1_MUTATIONS)])
def test_proof_m1_rules_catch(path, old, new):
    assert _m1_problems(_sources_with(path, old, new))


# The seven pentest bypasses, each caught by the rule meant for it.
@pytest.mark.parametrize(("index", "checker"), [
    (0, _dynamic_name_problems), (1, _accept_problems),
    (2, lambda sources: _security_handler_problems(sources[_rel(CHAT_WEB_VIEW)])),
    (3, _accept_problems), (4, _dynamic_name_problems), (5, _pinned_assignment_problems),
    (6, _dynamic_name_problems),
])
def test_proof_pentest_bypass_caught_by_its_rule(index, checker):
    path, old, new = M1_MUTATIONS[index]
    assert checker(_sources_with(path, old, new))


# --- L1: a sign-in window opens only for a click ------------------------------
#
# ChatWebView hands request.userInitiated to ChatSites.classifyNewWindow,
# which returns "overlay" only when it is exactly true; script-opened windows
# are blocked (dropped, as other blocked windows).

NEW_WINDOW_HANDLER = r"\bonNewWindowRequested\s*:\s*\(\s*request\s*\)\s*=>\s*\{"
NEW_WINDOW_CLICK = r"\buserInitiated\s*:\s*request\s*\.\s*userInitiated\s*===\s*true\s*,"
OVERLAY_ON_CLICK = r'\bclicked\s*\?\s*"overlay"\s*:\s*"block"'


def _new_window_click_problems(web, sites):
    problems = []
    windows = [body for _, body in _blocks(web, NEW_WINDOW_HANDLER)]
    if len(windows) != 1 or len(re.findall(NEW_WINDOW_CLICK, windows[0])) != 1 \
            or len(_hits(r"\buserInitiated\s*:", web)) != 1:
        problems.append("onNewWindowRequested must pass `userInitiated: request.userInitiated === true,` "
                        "to ChatSites.classifyNewWindow, once")
    body = _function_body(sites, "classifyNewWindow")
    if body is None:
        return problems + ["ChatSites.js: function classifyNewWindow( must be defined once"]
    if len(re.findall(r"\bvar\s+clicked\s*=\s*info\s*\.\s*userInitiated\s*===\s*true\s*$", body, re.M)) != 1 \
            or len(re.findall(r"\bclicked\s*=", body)) != 1:
        problems.append("classifyNewWindow: `var clicked = info.userInitiated === true`, set once")
    overlays = len(re.findall(r'"overlay"', body))
    if overlays == 0 or overlays != len(re.findall(OVERLAY_ON_CLICK, body)):
        problems.append('classifyNewWindow returns "overlay" only as `clicked ? "overlay" : "block"`')
    return problems


def test_sign_in_window_opens_only_for_a_click():
    problems = _new_window_click_problems(_read_code(CHAT_WEB_VIEW), _read_code(CHAT_SITES_JS))
    assert not problems, problems


NEW_WINDOW_CLICK_MUTATIONS = [
    (CHAT_WEB_VIEW, "                    userInitiated: request.userInitiated === true,\n", ""),
    (CHAT_WEB_VIEW, "userInitiated: request.userInitiated === true,", "userInitiated: true,"),
    (CHAT_WEB_VIEW, "userInitiated: request.userInitiated === true,", "userInitiated: request.userInitiated || true,"),
    (CHAT_SITES_JS, '        return clicked ? "overlay" : "block"\n    if (!https)',
     '        return "overlay"\n    if (!https)'),
    (CHAT_SITES_JS, '        return clicked ? "overlay" : "block"\n    return "external"',
     '        return "overlay"\n    return "external"'),
    (CHAT_SITES_JS, "    var clicked = info.userInitiated === true\n", "    var clicked = true\n"),
    (CHAT_SITES_JS, "    var clicked = info.userInitiated === true\n",
     "    var clicked = info.userInitiated !== false\n"),
    (CHAT_SITES_JS, "    var clicked = info.userInitiated === true\n",
     "    var clicked = info.userInitiated === true\n    clicked = true\n"),
    (CHAT_SITES_JS, '        return clicked ? "overlay" : "block"\n    if (!https)',
     '        return clicked ? "overlay" : "overlay"\n    if (!https)'),
]


@pytest.mark.parametrize(("path", "old", "new"), NEW_WINDOW_CLICK_MUTATIONS,
                         ids=[f"{path.name}:{index}" for index, (path, _, _) in enumerate(NEW_WINDOW_CLICK_MUTATIONS)])
def test_proof_new_window_click_rule_catches(path, old, new):
    web = _mutated(path, old, new) if path == CHAT_WEB_VIEW else _read_code(CHAT_WEB_VIEW)
    sites = _mutated(path, old, new) if path == CHAT_SITES_JS else _read_code(CHAT_SITES_JS)
    assert _new_window_click_problems(web, sites)


# --- Delete with the wallet entry left behind --------------------------------
#
# `--vault destroy` replying wallet-failed means the folder is gone but its
# KDE Wallet entry stayed; a retry would report ok without touching the
# wallet. The General page says so with its own fixed message instead of
# "Try again".

DESTROY_WALLET_MAP = (r'\belse\s+if\s*\(\s*op\s*===\s*"destroy"\s*&&\s*reply\s*\.\s*error\s*===\s*"wallet-failed"\s*\)'
                      r'\s*page\s*\.\s*vaultMessage\s*=\s*"deleted-wallet-left"')
DESTROY_WALLET_TEXT = (
    'case "deleted-wallet-left": return i18n("The encrypted folder was deleted, but its key could not be '
    'removed from KDE Wallet (folder Hearthwire, entry encrypted-chat-folder). Remove it in KWalletManager.")'
)


def _destroy_wallet_message_problems(code):
    problems = []
    finish = _function_body(code, "finishVault") or ""
    if len(re.findall(DESTROY_WALLET_MAP, finish)) != 1:
        problems.append('finishVault maps a destroy that replied wallet-failed to "deleted-wallet-left"')
    text = _function_body(code, "vaultText") or ""
    if _normalized(text).count(DESTROY_WALLET_TEXT) != 1:
        problems.append(f"vaultText must have `{DESTROY_WALLET_TEXT}`")
    if 'return i18n("KDE Wallet didn\'t answer or was cancelled. Try again.")' not in _normalized(text):
        problems.append("vaultText keeps the wallet-failed text for every other action")
    return problems


def test_destroy_names_the_wallet_entry_it_left():
    problems = _destroy_wallet_message_problems(_read_code(CONFIG_GENERAL))
    assert not problems, problems


@pytest.mark.parametrize(("old", "new"), [
    ('        else if (op === "destroy" && reply.error === "wallet-failed")\n'
     '            page.vaultMessage = "deleted-wallet-left"\n', ""),
    ('op === "destroy" && reply.error === "wallet-failed"', 'op === "remove-key" && reply.error === "wallet-failed"'),
    ('page.vaultMessage = "deleted-wallet-left"', 'page.vaultMessage = "wallet-failed"'),
    ("(folder Hearthwire, entry encrypted-chat-folder)", "(folder Hearthwire)"),
    ('            return i18n("KDE Wallet didn\'t answer or was cancelled. Try again.")\n',
     '            return i18n("The encrypted folder was deleted.")\n'),
])
def test_proof_destroy_wallet_message_rule_catches(old, new):
    assert _destroy_wallet_message_problems(_mutated(CONFIG_GENERAL, old, new))


# RN1 The rename to Hearthwire leaves no trace of the old name in the
# plasmoid: no old product, module or path name and no old plugin id in any
# QML/JS file, comments included. The old name is spelled in pieces here so
# the repository-wide stale-name search stays clean.

OLD_NAME = "hearth" + "side"
OLD_PLUGIN_ID = "io.github.flybytechprog." + OLD_NAME


def _old_name_offenders(sources):
    return [
        f"{name}:{line} {rule}"
        for name, text in sources.items()
        for rule, pattern in (("old plugin id", re.escape(OLD_PLUGIN_ID)),
                              ("old name", rf"(?i){OLD_NAME}"))
        for line in _hits(pattern, text)
    ]


def test_plasmoid_code_has_no_old_name_or_plugin_id():
    sources = {_rel(path): path.read_text(encoding="utf-8") for path in _code_files()}
    offenders = _old_name_offenders(sources)
    assert not offenders, f"the old name is still in plasmoid/: {offenders}"


@pytest.mark.parametrize(("name", "snippet"), [
    ("main.qml", 'readonly property string cmd: "python3 -P -m ' + OLD_NAME + ' --json"'),
    ("main.qml", "// " + OLD_NAME.capitalize() + " shows usage here"),
    ("RefreshGate.js", 'var ID = "' + OLD_PLUGIN_ID + '"'),
    ("ChatStorage.js", 'var ENV = "env ' + OLD_NAME.upper() + '_RUN=1"'),
])
def test_proof_old_name_rule_catches(name, snippet):
    assert _old_name_offenders({name: snippet})


# RN2 Only the installer migrates (plan D4): no QML/JS file ever starts the
# helper with --migrate.

MIGRATE_FLAG = r"--migrate\b"


def _migrate_offenders(sources):
    return [f"{name}:{line} --migrate" for name, code in sources.items() for line in _hits(MIGRATE_FLAG, code)]


def test_plasmoid_never_runs_the_migration():
    offenders = _migrate_offenders(_all_code())
    assert not offenders, f"the widget must not migrate (the installer does): {offenders}"


@pytest.mark.parametrize(("name", "snippet"), [
    ("main.qml", 'readonly property string cmd: "python3 -P -m hearthwire --migrate run"'),
    ("configGeneral.qml", 'executable.connectSource("python3 -P -m hearthwire " + "--migrate status")'),
    ("RefreshGate.js", "var M = ' --migrate=applets'"),
])
def test_proof_migrate_rule_catches(name, snippet):
    assert _migrate_offenders({name: _strip_comments(snippet)})


# --- LOW-2 (pentest 2026-11-05): exact settings values, no other settings, WebAuthn cancelled ---
#
# The M1 rules pin that each listed setting is bound once and never assigned,
# but not its value, and a new `settings.X: true` binding for an unlisted
# setting (say localContentCanAccessRemoteUrls) passed. Now every `settings`
# token in the WebEngine files must be one of these exact bindings in
# ChatWebView.qml, and the passkey (WebAuthn) request is always cancelled.

PINNED_SETTING_VALUES = {
    "screenCaptureEnabled": "false",
    "pluginsEnabled": "false",
    "dnsPrefetchEnabled": "false",
    "navigateOnDropEnabled": "false",
    "localContentCanAccessFileUrls": "false",
    "allowRunningInsecureContent": "false",
    "javascriptCanAccessClipboard": "false",
    "javascriptCanPaste": "false",
    "focusOnNavigationEnabled": "false",
    "unknownUrlSchemePolicy": "WebEngineSettings.DisallowUnknownUrlSchemes",
}
PINNED_SETTING_LINES = tuple(f"settings.{name}: {value}" for name, value in PINNED_SETTING_VALUES.items())


def test_pinned_setting_values_cover_exactly_the_pinned_settings():
    assert tuple(PINNED_SETTING_VALUES) == PINNED_SETTINGS


def _settings_problems(sources):
    """Every `settings` / `WebEngineSettings` token is one of the pinned binding lines."""
    problems = []
    web_name = _rel(CHAT_WEB_VIEW)
    for path in WEBENGINE_FILES:
        name = _rel(path)
        code = sources.get(name, "")
        blanked = _strip_comments(code, blank_strings=True)
        lines = code.splitlines()
        for match in re.finditer(r"\b(?:WebEngine)?[Ss]ettings\b", blanked):
            line = _line_of(blanked, match.start())
            text = _normalized(lines[line - 1])
            if name != web_name or text not in PINNED_SETTING_LINES:
                problems.append(f"{name}:{line}: WebEngine setting outside the pinned bindings: `{text}`")
    web_lines = [_normalized(line) for line in sources.get(web_name, "").splitlines()]
    for expected in PINNED_SETTING_LINES:
        if web_lines.count(expected) != 1:
            problems.append(f"ChatWebView.qml must bind `{expected}` exactly once")
    return problems


def _webauth_problems(sources):
    """One handler, in ChatWebView.qml; the signal is named nowhere else, so
    neither a Connections block nor `.webAuthUxRequested.connect` can add one."""
    web_name = _rel(CHAT_WEB_VIEW)
    web = sources.get(web_name, "")
    bodies = [body for _, body in _handler_bodies(web, "onWebAuthUxRequested")]
    if len(bodies) != 1:
        return [f"exactly one onWebAuthUxRequested handler, found {len(bodies)}"]
    body = _normalized(bodies[0])
    problems = [f"{name}:{_line_of(code, match.start())}: `{match.group(0)}` outside the one handler"
                for name, code in sources.items()
                for match in re.finditer(r"\b(?:on)?[Ww]ebAuthUxRequested\b", code)
                if (name, match.group(0)) != (web_name, "onWebAuthUxRequested")]
    if len(_hits(r"\bonWebAuthUxRequested\b", web)) != 1:
        problems.append("ChatWebView.qml may name onWebAuthUxRequested only for the one handler")
    if not body.startswith("{ request.cancel() "):
        problems.append(f"onWebAuthUxRequested must start with `request.cancel()`, got `{body}`")
    if len(_hits(r"\brequest\b", body)) != 1:
        problems.append("onWebAuthUxRequested may use request only for request.cancel()")
    return problems


def test_webengine_settings_are_exactly_the_pinned_bindings():
    problems = _settings_problems(_all_code())
    assert not problems, problems


def test_passkey_requests_are_always_cancelled():
    problems = _webauth_problems(_all_code())
    assert not problems, problems


LOW2_SETTINGS_MUTATIONS = [
    (CHAT_WEB_VIEW, "WebEngineSettings.DisallowUnknownUrlSchemes", "WebEngineSettings.AllowAllUnknownUrlSchemes"),
    (CHAT_WEB_VIEW, "WebEngineSettings.DisallowUnknownUrlSchemes",
     "WebEngineSettings.AllowUnknownUrlSchemesFromUserInteraction"),
    (CHAT_WEB_VIEW, "            settings.unknownUrlSchemePolicy: WebEngineSettings.DisallowUnknownUrlSchemes\n", ""),
    (CHAT_WEB_VIEW, "            settings.focusOnNavigationEnabled: false\n",
     "            settings.focusOnNavigationEnabled: false\n            settings.localContentCanAccessRemoteUrls: true\n"),
    (CHAT_WEB_VIEW, "            settings.pluginsEnabled: false\n", "            settings.pluginsEnabled: true\n"),
    (CHAT_WEB_VIEW, "            settings.pluginsEnabled: false\n",
     "            settings.pluginsEnabled: false || chatWeb.staySignedIn\n"),
    (CHAT_WEB_VIEW, "            settings.focusOnNavigationEnabled: false\n",
     "            settings.focusOnNavigationEnabled: false\n            settings { javascriptEnabled: true }\n"),
    (CHAT_WEB_VIEW, "            settings.focusOnNavigationEnabled: false\n",
     "            settings.focusOnNavigationEnabled: false\n            settings.autoLoadImages: false\n"),
    (CHAT_VIEW, "onTriggered: chatView.web.cancelDownload()",
     "onTriggered: chatView.web.currentView.settings.localContentCanAccessRemoteUrls = true"),
    (FULL_REPRESENTATION, "onClicked: chatView.openExternally()",
     "onClicked: chatView.web.currentView.settings.unknownUrlSchemePolicy = WebEngineSettings.AllowAllUnknownUrlSchemes"),
]


@pytest.mark.parametrize(("path", "old", "new"), LOW2_SETTINGS_MUTATIONS,
                         ids=[f"{path.name}:{index}" for index, (path, _, _) in enumerate(LOW2_SETTINGS_MUTATIONS)])
def test_proof_settings_rule_catches(path, old, new):
    assert _settings_problems(_sources_with(path, old, new))


LOW2_WEBAUTH_MUTATIONS = [
    ("                request.cancel()\n                chatWeb.passkeyNotice = true\n",
     "                chatWeb.passkeyNotice = true\n"),
    ("                request.cancel()\n                chatWeb.passkeyNotice = true\n",
     "                chatWeb.passkeyNotice = true\n                request.cancel()\n"),
    ("                request.cancel()\n                chatWeb.passkeyNotice = true\n",
     "                if (chatWeb.passkeyNotice)\n                    request.cancel()\n"),
    ("                request.cancel()\n                chatWeb.passkeyNotice = true\n",
     "                request.cancel()\n                request.retry()\n"),
    ("            onWebAuthUxRequested: (request) => {\n",
     "            onWebAuthUxRequested: (request) => {}\n            onWebAuthUxRequested: (request) => {\n"),
]


@pytest.mark.parametrize(("old", "new"), LOW2_WEBAUTH_MUTATIONS)
def test_proof_webauth_rule_catches(old, new):
    assert _webauth_problems(_sources_with(CHAT_WEB_VIEW, old, new))


LOW2_WEBAUTH_SECOND_HANDLERS = [
    (CHAT_WEB_VIEW, "            onWebAuthUxRequested: (request) => {\n",
     "            Connections {\n                target: page\n"
     "                function onWebAuthUxRequested(request) { request.retry() }\n            }\n"
     "            onWebAuthUxRequested: (request) => {\n"),
    (CHAT_WEB_VIEW, "            onWebAuthUxRequested: (request) => {\n",
     "            Component.onCompleted: page.webAuthUxRequested.connect(function (r) { r.retry() })\n"
     "            onWebAuthUxRequested: (request) => {\n"),
    (CHAT_VIEW, "onTriggered: chatView.web.cancelDownload()",
     "onTriggered: chatView.web.currentView.webAuthUxRequested.connect(chatView.web.saveDownload)"),
    (FULL_REPRESENTATION, "onClicked: chatView.openExternally()",
     "onClicked: chatView.web.currentView.webAuthUxRequested.connect(chatView.openExternally)"),
]


@pytest.mark.parametrize(("path", "old", "new"), LOW2_WEBAUTH_SECOND_HANDLERS,
                         ids=[f"{path.name}:{index}" for index, (path, _, _) in enumerate(LOW2_WEBAUTH_SECOND_HANDLERS)])
def test_proof_a_second_webauth_handler_is_caught(path, old, new):
    assert _webauth_problems(_sources_with(path, old, new))


# --- Round 4, phase 1a: hover popup, provider accent, next reset ------------------------

PROVIDER_ACCENT_JS = UI / "ProviderAccent.js"
RECTANGLE = r"(?<![\w.])Rectangle\s*\{"


def _code_pattern(literal):
    """``literal`` code as a regex: any spacing between tokens, whole words at the ends."""
    tokens = re.findall(r"\w+|[^\w\s]", literal)
    lead = r"(?<![\w.])" if re.match(r"\w", literal) else ""
    tail = r"(?!\w)" if re.search(r"\w$", literal) else ""
    return lead + r"\s*".join(re.escape(token) for token in tokens) + tail


def _pin_problems(code, pins, where):
    """Each of ``pins`` (literal code) must appear in ``code`` exactly once."""
    problems = []
    for literal in pins:
        count = len(_hits(_code_pattern(literal), code))
        if count != 1:
            problems.append(f"{where}: {literal!r} must appear exactly once, found {count}")
    return problems


def _squeezed(text):
    return re.sub(r"\s+", " ", text).strip()


def _named_elements(code, opener, name):
    """The ``opener`` blocks whose own top-level objectName is the literal ``name``."""
    return [(start, body) for start, body in _blocks(code, opener)
            if re.search(rf'(?:^|[\n;])\s*objectName\s*:\s*"{name}"\s*(?=;|\n|$)', _top_level_raw(body))]


def _text_binding(body):
    match = re.search(r"(?:^|[\n;])\s*text\s*:\s*([^\n;]+)", _top_level_raw(body))
    return match.group(1).strip() if match else None


def _returns(body):
    return [value.strip() for value in re.findall(r"\breturn\s+([^\n]*)", body)]


# Anything in the hover popup or the accent code that could reach the network
# or a file, load a picture, or open a link.
DISPLAY_ACCESS_BANS = {
    "XMLHttpRequest": r"\bXMLHttpRequest\b",
    "Qt file or network call": r"\bQt\s*\.\s*(?:openUrlExternally|resolvedUrl|include|createQmlObject|createComponent)\b",
    "helper or engine": r"\b(?:Plasma5Support|DataSource|executable|WebEngine\w*|FileDialog|FolderDialog|FolderListModel)\b",
    "Loader": r"(?<![\w.])Loader\s*\{",
    "picture element": r"(?<![\w.])(?:[A-Za-z_]\w*\s*\.\s*)?(?:Image|AnimatedImage|BorderImage|Icon)\s*\{",
    "source binding": r"(?:^|[\n;{])\s*source\s*:",
    "URL literal": r"""["'`]\s*(?:https?|ftp|file|data|qrc)\s*:""",
    "HTML literal": r"<\s*(?:img|a\s+href)\b",
}


def _access_problems(code):
    return [f"{name} at line {line}" for name, pattern in DISPLAY_ACCESS_BANS.items()
            for line in _hits(pattern, code)]


# 1a hover popup: every text element is PlainText and shows one of the four
# strings main.qml hands in; no pictures, links, files or network.

TOOLTIP_IMPORTS = [
    "QtQuick", "QtQuick.Layouts", "org.kde.kirigami as Kirigami",
    "org.kde.plasma.components as PlasmaComponents",
]
TOOLTIP_TEXTS = ["reading.modelData.title", "reading.modelData.value", "section.modelData.name", "tip.title"]


def _usage_tooltip_problems(code):
    problems = _plain_text_problems(code) + _access_problems(code)
    imports = sorted(re.findall(r"(?m)^\s*import\s+(.*?)\s*$", code))
    if imports != TOOLTIP_IMPORTS:
        problems.append(f"imports must stay {TOOLTIP_IMPORTS}, found {imports}")
    texts = sorted(_text_binding(body) or "" for _, body in _blocks(code, TEXT_ELEMENT))
    if texts != TOOLTIP_TEXTS:
        problems.append(f"the text elements must show exactly {TOOLTIP_TEXTS}, found {texts}")
    return problems


def test_hover_popup_shows_only_the_given_strings_as_plain_text():
    problems = _usage_tooltip_problems(_read_code(USAGE_TOOLTIP))
    assert not problems, f"{_rel(USAGE_TOOLTIP)}: {problems}"


@pytest.mark.parametrize("snippet", [
    "    Text { text: tip.title; textFormat: Text.RichText }\n",
    "    Text { text: tip.title; textFormat: Text.StyledText }\n",
    "    Text { text: tip.title }\n",
    '    Text { textFormat: Text.PlainText; text: "x" }\n',
    '    Image { source: "https://example.invalid/x.png" }\n',
    '    Kirigami.Icon { source: "speedometer" }\n',
    "    Text { textFormat: Text.PlainText; onLinkActivated: (link) => Qt.openUrlExternally(link) }\n",
    "    function f() { return new XMLHttpRequest() }\n",
    '    function f() { return Qt.resolvedUrl("x") }\n',
    '    Loader { active: false }\n',
])
def test_proof_hover_popup_rule_catches_additions(snippet):
    assert _usage_tooltip_problems(_appended(USAGE_TOOLTIP, snippet))


@pytest.mark.parametrize(("old", "new"), [
    ("text: reading.modelData.value", "text: reading.modelData.caption"),
    ("text: section.modelData.name", "text: section.modelData.plan"),
    ("text: tip.title", 'text: "<img src=x>"'),
    ("textFormat: Text.PlainText\n                    font.bold: true", "font.bold: true"),
    ("import QtQuick.Layouts\n", "import QtQuick.Layouts\nimport QtNetwork\n"),
])
def test_proof_hover_popup_rule_catches_changes(old, new):
    assert _usage_tooltip_problems(_mutated(USAGE_TOOLTIP, old, new))


# 1a hover popup, main.qml side: names and titles come from the catalog, values
# are numbers the widget formats, and the level goes through TooltipLogic. The
# one exception is the error line: toolTipSubText can show the helper's last
# stderr line (root.lastError), PlainText through toolTipTextFormat and cut to
# length by UsageLogic.shownText.

MAIN_TOOLTIP_SECTIONS = r"\breadonly\s+property\s+var\s+tooltipSections\s*:\s*\{"
MAIN_TOOLTIP_SUBTEXT = r"(?<![\w.])toolTipSubText\s*:\s*\{"
MAIN_USAGE_TOOLTIP = r"\bproperty\s+Item\s+usageTooltip\s*:\s*UsageTooltip\s*\{"
MAIN_TOOLTIP_SECTION_PINS = (
    "var metric = Catalog.metric(group.provider_id, metricId)",
    "title: metric.title",
    "value: root.tooltipValue(reading)",
    'level: reading && reading.type === "percentage" ? UsageLogic.usageLevel(reading.raw_used, root.usageThresholds) : ""',
    "groups.push({name: group.descriptor.display_name, items: items})",
    "return TooltipLogic.tooltipSections(groups)",
)
MAIN_TOOLTIP_SUBTEXT_RETURNS = ['""', 'i18n("Error: %1", UsageLogic.shownText(root.lastError))', 'i18n("Loading…")',
                                'i18n("No usage to show.")', '""']
# What a provider reply carries as text, as opposed to numbers.
TOOLTIP_REPLY_TEXT = r"\b(?:caption|error_message|plan|status|modelData)\b|(?<!descriptor)\s*\.\s*display_name\b"


def _one_block(code, opener):
    bodies = [body for _, body in _blocks(code, opener)]
    return bodies[0] if len(bodies) == 1 else None


def _reading_value_problems(code):
    problems = []
    for name in ("tooltipValue", "formatReading"):
        body = _function_body(code, name)
        if body is None:
            problems.append(f"exactly one function {name}() expected")
            continue
        members = set(re.findall(r"\breading\s*\.\s*(\w+)", body)) - {"type", "value"}
        if members:
            problems.append(f"{name}() may read only reading.type and reading.value, found {sorted(members)}")
        if re.search(r"\breturn\s+reading\s*(?:;|\n|$)", body):
            problems.append(f"{name}() must not return the reading itself")
        for match in re.finditer(r"\breading\s*\.\s*value\b", body):
            if not re.search(r"(?:\bMath\s*\.\s*round|\bNumber)\s*\(\s*$", body[:match.start()]):
                problems.append(f"{name}(): reading.value must pass through Math.round() or Number()")
    return problems


def _main_tooltip_problems(code, sources=None):
    sections = _one_block(code, MAIN_TOOLTIP_SECTIONS)
    subtext = _one_block(code, MAIN_TOOLTIP_SUBTEXT)
    usage_tooltip = _one_block(code, MAIN_USAGE_TOOLTIP)
    groups = _function_body(code, "tooltipProviderGroups")
    if None in (sections, subtext, usage_tooltip, groups):
        return ["main.qml needs one tooltipSections, toolTipSubText, usageTooltip and tooltipProviderGroups()"]
    problems = _pin_problems(sections, MAIN_TOOLTIP_SECTION_PINS, "tooltipSections")
    problems += _pin_problems(groups, ("var descriptor = Catalog.byId(providerId)", "descriptor: descriptor"),
                              "tooltipProviderGroups()")
    problems += [f"tooltipSections: provider text at line {line}" for line in _hits(TOOLTIP_REPLY_TEXT, sections)]
    problems += _reading_value_problems(code)
    if _returns(subtext) != MAIN_TOOLTIP_SUBTEXT_RETURNS:
        problems.append(f"toolTipSubText must return exactly {MAIN_TOOLTIP_SUBTEXT_RETURNS}, found {_returns(subtext)}")
    top = _top_level_raw(usage_tooltip)
    problems += _pin_problems(top, ('title: i18n("Hearthwire")', "sections: root.tooltipSections"), "usageTooltip")
    if re.search(r"(?:^|[\n;])\s*text\s*:", top):
        problems.append("usageTooltip must not bind text")
    problems += _pin_problems(code, ('toolTipMainText: i18n("Hearthwire")',
                                     "toolTipItem: root.tooltipSections.length > 0 ? root.usageTooltip : null"),
                              "main.qml")
    for block in (sections, subtext, usage_tooltip):
        problems += _access_problems(block)
    uses = [name for name, text in (sources or {}).items() for _ in _hits(r"(?<![\w.])UsageTooltip\s*\{", text)]
    if sources is not None and len(uses) != 1:
        problems.append(f"UsageTooltip must be created once, by main.qml; found {uses}")
    return problems


def test_hover_popup_text_comes_from_the_catalog_and_the_widget():
    problems = _main_tooltip_problems(_read_code(MAIN_QML), _all_code())
    assert not problems, f"{_rel(MAIN_QML)}: {problems}"


@pytest.mark.parametrize(("old", "new"), [
    ("title: metric.title,", "title: reading.caption,"),
    ("value: root.tooltipValue(reading),", "value: reading.caption,"),
    ("return TooltipLogic.tooltipSections(groups)", "return groups"),
    ("{name: group.descriptor.display_name, items: items}", "{name: group.provider.display_name, items: items}"),
    ('? UsageLogic.usageLevel(reading.raw_used, root.usageThresholds) : ""', '? reading.raw_level : ""'),
    ("var metric = Catalog.metric(group.provider_id, metricId)", "var metric = group.provider.windows[metricId]"),
    ('        title: i18n("Hearthwire")\n        sections: root.tooltipSections\n',
     "        title: root.lastError\n        sections: root.tooltipSections\n"),
    ("        sections: root.tooltipSections\n", "        sections: root.snapshot.providers\n"),
    ("        sections: root.tooltipSections\n", "        sections: root.tooltipSections\n        text: root.lastError\n"),
    ("        sections: root.tooltipSections\n",
     '        sections: root.tooltipSections\n        Image { source: "https://example.invalid/x.png" }\n'),
    ('return i18n("No usage to show.")', "return root.lastError"),
    ('return i18n("Error: %1", UsageLogic.shownText(root.lastError))', 'return i18n("Error: %1", root.lastError)'),
    ('return i18n("Loading…")', "return root.snapshot.plan"),
    ("toolTipItem: root.tooltipSections.length > 0 ? root.usageTooltip : null", "toolTipItem: root.usageTooltip"),
    ("            return root.formatReading(reading)\n", "            return reading.caption\n"),
    ("return String(Math.round(reading.value))", "return String(reading.value)"),
    ('return Math.round(reading.value) + "%"', 'return reading.value + "%"'),
    ("        var groups = []\n", "        var groups = []\n        var request = new XMLHttpRequest()\n"),
])
def test_proof_main_tooltip_rule_catches(old, new):
    assert _main_tooltip_problems(_mutated(MAIN_QML, old, new))


def test_proof_main_tooltip_rule_needs_catalog_descriptors():
    code = _mutated_in_function(MAIN_QML, "tooltipProviderGroups", "var descriptor = Catalog.byId(providerId)",
                                "var descriptor = shown[index]")
    assert _main_tooltip_problems(code)


def test_proof_second_usage_tooltip_is_caught():
    sources = _sources_with(FULL_REPRESENTATION, snippet="\n    UsageTooltip { }\n")
    assert _main_tooltip_problems(_read_code(MAIN_QML), sources)


# 1a hover popup, TooltipLogic side: plain strings out, and the dot takes only
# normal | warning | critical | "" (anything else is cleared by readingLevel).

READING_LEVEL_BODY = '{ return level === "normal" || level === "warning" || level === "critical" ? level : "" }'
LEVEL_COLOR_BODY = ('{ if (level === "critical") return tip.criticalColor if (level === "warning") '
                    'return tip.warningColor if (level === "normal") return tip.normalColor return "transparent" }')
TOOLTIP_SECTION_PINS = (
    'name: String(group.name || "")',
    'title: String(entry.title || "")',
    'value: String(entry.value || "")',
    "level: readingLevel(entry.level)",
)


def _tooltip_level_problems(view, logic):
    problems = _access_problems(logic)
    dots = _named_elements(view, RECTANGLE, "tooltipReadingDot")
    if len(dots) != 1:
        problems.append(f"exactly one Rectangle tooltipReadingDot expected, found {len(dots)}")
    else:
        top = _top_level_raw(dots[0][1])
        problems += _pin_problems(top, ("color: tip.levelColor(reading.modelData.level)",), "tooltipReadingDot")
        if len(_hits(r"(?:^|[\n;])\s*color\s*:", top)) != 1:
            problems.append("tooltipReadingDot must bind its color once")
    if len(_hits(r"\btip\s*\.\s*levelColor\b", view)) != 1:
        problems.append("only tooltipReadingDot may call tip.levelColor")
    color = _function_body(view, "levelColor")
    if color is None or _squeezed(color) != LEVEL_COLOR_BODY:
        problems.append(f"levelColor must stay {LEVEL_COLOR_BODY}")
    level = _function_body(logic, "readingLevel")
    if level is None or _squeezed(level) != READING_LEVEL_BODY:
        problems.append(f"readingLevel must stay {READING_LEVEL_BODY}")
    sections = _function_body(logic, "tooltipSections")
    if sections is None:
        problems.append("exactly one function tooltipSections() expected")
    else:
        problems += _pin_problems(sections, TOOLTIP_SECTION_PINS, "tooltipSections()")
    return problems


def test_hover_popup_dot_takes_only_known_levels():
    problems = _tooltip_level_problems(_read_code(USAGE_TOOLTIP), _read_code(TOOLTIP_LOGIC_JS))
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (USAGE_TOOLTIP, "color: tip.levelColor(reading.modelData.level)", "color: reading.modelData.level"),
    (USAGE_TOOLTIP, 'objectName: "tooltipReadingDot"', 'objectName: "tooltipDot"'),
    (USAGE_TOOLTIP, 'return "transparent"', "return level"),
    (USAGE_TOOLTIP, 'if (level === "warning")', 'if (level === "warning" || level === "stale")'),
    (TOOLTIP_LOGIC_JS, 'level === "critical" ? level : ""', 'level === "critical" ? level : String(level)'),
    (TOOLTIP_LOGIC_JS, 'level === "normal" || level === "warning"', 'level === "normal" || level === "stale"'),
    (TOOLTIP_LOGIC_JS, "level: readingLevel(entry.level)", 'level: String(entry.level || "")'),
    (TOOLTIP_LOGIC_JS, 'value: String(entry.value || ""),', "value: entry.value,"),
    (TOOLTIP_LOGIC_JS, 'name: String(group.name || ""),', "name: group.name,"),
    (TOOLTIP_LOGIC_JS, "function readingLevel(level) {",
     "function reach() { return new XMLHttpRequest() }\nfunction readingLevel(level) {"),
])
def test_proof_hover_popup_level_rule_catches(path, old, new):
    view = _mutated(path, old, new) if path == USAGE_TOOLTIP else _read_code(USAGE_TOOLTIP)
    logic = _mutated(path, old, new) if path == TOOLTIP_LOGIC_JS else _read_code(TOOLTIP_LOGIC_JS)
    assert _tooltip_level_problems(view, logic)


# 1a accent: a pure library whose only results are "#rrggbb" or "", and a
# decorative strip that shows nothing else.

ACCENT_ENTRY = r'\w+\s*:\s*\{\s*light\s*:\s*"#[0-9a-f]{6}"\s*,\s*dark\s*:\s*"#[0-9a-f]{6}"\s*\}'
ACCENT_TABLE = rf"\{{\s*{ACCENT_ENTRY}(?:\s*,\s*{ACCENT_ENTRY})*\s*\}}"
ACCENT_RETURNS = ['""', '""', "luminance < 0.5 ? pair.dark : pair.light"]
ACCENT_GUARD = 'typeof providerId !== "string" || !Object.prototype.hasOwnProperty.call(ACCENTS, providerId)'
ACCENT_STRINGS = {"", "string", "number"}
ACCENT_BINDING = ("readonly property string accent: ProviderAccent.accentFor(providerSection.modelData.provider_id, "
                  "Kirigami.Theme.backgroundColor.r, Kirigami.Theme.backgroundColor.g, Kirigami.Theme.backgroundColor.b)")
ACCENT_STRIP_PINS = (
    'visible: providerSection.accent !== ""',
    'color: providerSection.accent !== "" ? providerSection.accent : "transparent"',
)


def _provider_accent_problems(code):
    problems = _alert_logic_problems(code) + _access_problems(code)
    table = _one_block(code, r"\bvar\s+ACCENTS\s*=\s*\{")
    if table is None:
        return problems + ["exactly one `var ACCENTS = {...}` expected"]
    if not re.fullmatch(ACCENT_TABLE, table):
        problems.append('ACCENTS must hold only {light: "#rrggbb", dark: "#rrggbb"} literals')
    others = [text for text in re.findall(r'"([^"\n]*)"', code)
              if text not in ACCENT_STRINGS and not re.fullmatch(r"#[0-9a-f]{6}", text)]
    if others or _hits(r"['`]", code):
        problems.append(f"no other string literals are allowed, found {others}")
    body = _function_body(code, "accentFor")
    if body is None:
        return problems + ["exactly one function accentFor() expected"]
    if _returns(body) != ACCENT_RETURNS:
        problems.append(f"accentFor() must return exactly {ACCENT_RETURNS}, found {_returns(body)}")
    problems += _pin_problems(body, (ACCENT_GUARD,), "accentFor()")
    return problems


def _accent_strip_problems(code):
    problems = _pin_problems(code, (ACCENT_BINDING,), "UsageView.qml")
    if len(_hits(r"\bProviderAccent\s*\.\s*(?!js\b)", code)) != 1:
        problems.append("ProviderAccent may be used only by the accent binding")
    if _hits(r"\baccent\s*=(?!=)", code):
        problems.append("nothing may assign accent")
    strips = _named_elements(code, RECTANGLE, "providerAccent")
    if len(strips) != 1:
        return problems + [f"exactly one Rectangle providerAccent expected, found {len(strips)}"]
    body = strips[0][1]
    top = _top_level_raw(body)
    problems += _pin_problems(top, ACCENT_STRIP_PINS, "providerAccent")
    if _hits(r"(?<![\w.])[A-Z][\w.]*\s*\{", body):
        problems.append("providerAccent must have no child elements")
    if re.search(r"(?:^|[\n;])\s*(?:text|source)\s*:", top):
        problems.append("providerAccent is decorative: no text or source")
    return problems


def test_provider_accent_is_a_pure_library_of_hex_colors():
    problems = _provider_accent_problems(_read_code(PROVIDER_ACCENT_JS))
    assert not problems, f"{_rel(PROVIDER_ACCENT_JS)}: {problems}"


def test_provider_accent_strip_is_decorative():
    problems = _accent_strip_problems(_read_code(USAGE_VIEW))
    assert not problems, f"{_rel(USAGE_VIEW)}: {problems}"


@pytest.mark.parametrize(("old", "new"), [
    (".pragma library\n", ""),
    ('claude: {light: "#b4532a"', 'claude: {light: "https://example.invalid/x"'),
    ('claude: {light: "#b4532a"', 'claude: {light: "#B4532A"'),
    ('dark: "#e8926f"}', 'dark: "#e8926f80"}'),
    ('grok: {light: "#4d4d4d", dark: "#c4c4c4"}', 'grok: {light: "#4d4d4d", dark: "#c4c4c4", name: "Grok"}'),
    ("return luminance < 0.5 ? pair.dark : pair.light", "return providerId"),
    ("return luminance < 0.5 ? pair.dark : pair.light", 'return "url(x)"'),
    ("!Object.prototype.hasOwnProperty.call(ACCENTS, providerId)", "!ACCENTS[providerId]"),
    ("function channel(value) {", "function reach() { return new XMLHttpRequest() }\nfunction channel(value) {"),
    ("function channel(value) {", 'function reach() { return Qt.resolvedUrl("x") }\nfunction channel(value) {'),
    ("function channel(value) {", '.import "UsageLogic.js" as UsageLogic\nfunction channel(value) {'),
])
def test_proof_provider_accent_rule_catches(old, new):
    assert _provider_accent_problems(_mutated(PROVIDER_ACCENT_JS, old, new))


@pytest.mark.parametrize(("old", "new"), [
    ('objectName: "providerAccent"', 'objectName: "accentStrip"'),
    ('color: providerSection.accent !== "" ? providerSection.accent : "transparent"',
     "color: providerSection.modelData.color"),
    ('visible: providerSection.accent !== ""\n', ""),
    ('                            objectName: "providerAccent"\n',
     '                            objectName: "providerAccent"\n                            '
     'Image { source: "https://example.invalid/x.png" }\n'),
    ('                            objectName: "providerAccent"\n',
     '                            objectName: "providerAccent"\n'
     "                            property string text: providerSection.modelData.plan\n"
     "                            Text { text: providerSection.modelData.plan }\n"),
    ("ProviderAccent.accentFor(\n                        providerSection.modelData.provider_id,",
     "ProviderAccent.accentFor(\n                        providerSection.modelData.display_name,"),
    ('    function billingTitle(billing) {',
     '    function other() { return ProviderAccent.ACCENTS }\n    function billingTitle(billing) {'),
])
def test_proof_accent_strip_rule_catches(old, new):
    assert _accent_strip_problems(_mutated(USAGE_VIEW, old, new))


# 1a next reset: PlainText, and its names are the catalog's, never the helper's.

NEXT_RESET_TEXT = "UsageLogic.shownText(usage.nextResetText(root.shownProviders, usage.nowMs))"
NEXT_RESET_PINS = (
    "var descriptor = providerData ? Catalog.byId(providerData.provider_id) : null",
    "var metric = Catalog.metric(descriptor.provider_id, windows[windowIndex].kind)",
    "entries.push({resetsAtMs: target, provider: descriptor.display_name, metric: metric.title})",
    "var next = UsageLogic.nextReset(entries, nowMs)",
    "next.provider, next.metric, usage.countdownText(UsageLogic.shortCountdown(next.resetsAtMs, nowMs))",
    'i18nc("@label soonest reset: provider, reading, time left", "Next reset: %1 %2 in %3",',
)
NEXT_RESET_BANS = {
    "helper caption": r"\bcaption\b",
    "helper text": r"\b(?:plan|error_message|status|modelData)\b",
    "provider field": r"\bproviderData\s*\.\s*(?!provider_id\b|windows\b)\w+",
    "window field": r"\bwindows\s*\[\s*windowIndex\s*\]\s*\.\s*(?!kind\b|resets_at\b)\w+",
    "name not from the catalog": r"(?<!descriptor)\s*\.\s*display_name\b",
}


def _next_reset_problems(code):
    labels = _named_elements(code, TEXT_ELEMENT, "usageNextResetLabel")
    if len(labels) != 1:
        return [f"exactly one text element usageNextResetLabel expected, found {len(labels)}"]
    start, body = labels[0]
    problems = []
    if len(re.findall(PLAIN_TEXT_FORMAT, _top_level(body))) != 1:
        problems.append(f"line {_line_of(code, start)}: usageNextResetLabel needs textFormat PlainText")
    if _text_binding(body) != NEXT_RESET_TEXT:
        problems.append(f"usageNextResetLabel must show {NEXT_RESET_TEXT}, found {_text_binding(body)}")
    next_reset = _function_body(code, "nextResetText")
    countdown = _function_body(code, "countdownText")
    if next_reset is None or countdown is None:
        return problems + ["exactly one nextResetText() and countdownText() expected"]
    problems += _pin_problems(next_reset, NEXT_RESET_PINS, "nextResetText()")
    problems += [f"nextResetText(): {name} at line {line}" for name, pattern in NEXT_RESET_BANS.items()
                 for line in _hits(pattern, next_reset)]
    extra = set(re.findall(r"\bparts\s*\.\s*(\w+)", countdown)) - {"days", "hours", "minutes"}
    if extra:
        problems.append(f"countdownText() may read only numbers, found {sorted(extra)}")
    return problems


def test_next_reset_label_is_plain_text_with_catalog_names():
    problems = _next_reset_problems(_read_code(USAGE_VIEW))
    assert not problems, f"{_rel(USAGE_VIEW)}: {problems}"


@pytest.mark.parametrize(("old", "new"), [
    ('objectName: "usageNextResetLabel"', 'objectName: "nextResetLabel"'),
    ("        textFormat: Text.PlainText\n        text: UsageLogic.shownText(usage.nextResetText(",
     "        text: UsageLogic.shownText(usage.nextResetText("),
    ("        textFormat: Text.PlainText\n        text: UsageLogic.shownText(usage.nextResetText(",
     "        textFormat: Text.RichText\n        text: UsageLogic.shownText(usage.nextResetText("),
    ("text: UsageLogic.shownText(usage.nextResetText(root.shownProviders, usage.nowMs))",
     "text: UsageLogic.shownText(root.lastError)"),
    ("provider: descriptor.display_name, metric: metric.title",
     "provider: providerData.display_name, metric: metric.title"),
    ("provider: descriptor.display_name, metric: metric.title",
     "provider: descriptor.display_name, metric: windows[windowIndex].caption"),
    ("var descriptor = providerData ? Catalog.byId(providerData.provider_id) : null",
     "var descriptor = providerData"),
    ("var metric = Catalog.metric(descriptor.provider_id, windows[windowIndex].kind)",
     "var metric = windows[windowIndex]"),
    ("next.provider, next.metric,", "next.provider, providerData.plan,"),
    ("if (parts.minutes > 0)", "if (parts.caption)"),
])
def test_proof_next_reset_rule_catches(old, new):
    assert _next_reset_problems(_mutated(USAGE_VIEW, old, new))


# --- Round 4, phase 1b: Ollama bubbles ---------------------------------------------------

# The bubbles restyled the transcript only. Text stays plain and read-only (the
# user's message, the reply's paragraphs and code are read-only TextEdits; word
# runs and headings are Text), and the scrolling and the rest of the view keep
# working. Most of the plan's "Must not change" items are properties, functions
# or ids rather than objectNames, so those are pinned by their declarations.

BARE_TEXT_EDIT = r"(?<![\w.])TextEdit\s*\{"
READ_ONLY_TRUE = r"(?:^|[\n;])\s*readOnly\s*:\s*true\s*(?=;|\n|$)"
OLLAMA_BUBBLE_TEXTS = ("id: userText", "id: plainText", "id: wordText", "id: codeText",
                       "font: ollamaView.headingFont(segment.block.level)")
USER_BUBBLE_TEXT = 'message.mine ? message.body : ""'


def _ollama_bubble_problems(code):
    problems = _pinned_plain_text_problems(code, OLLAMA_BUBBLE_TEXTS)
    edits = list(_blocks(code, BARE_TEXT_EDIT))
    if not edits:
        problems.append("no TextEdit found")
    for start, body in edits:
        if len(re.findall(READ_ONLY_TRUE, _top_level(body))) != 1:
            problems.append(f"line {_line_of(code, start)}: every TextEdit here must be `readOnly: true`")
    bubbles = _named_elements(code, RECTANGLE, "userBubble")
    if len(bubbles) != 1:
        return problems + [f"exactly one Rectangle userBubble expected, found {len(bubbles)}"]
    texts = list(_blocks(bubbles[0][1], TEXT_ELEMENT))
    if len(texts) != 1 or _text_binding(texts[0][1]) != USER_BUBBLE_TEXT:
        problems.append(f"the user bubble must hold one text element showing {USER_BUBBLE_TEXT}")
    return problems


def test_ollama_bubbles_keep_plain_read_only_text():
    problems = _ollama_bubble_problems(_read_code(OLLAMA_CHAT_VIEW))
    assert not problems, f"{_rel(OLLAMA_CHAT_VIEW)}: {problems}"


@pytest.mark.parametrize(("anchor", "old", "new"), [
    ("id: userText", "textFormat: TextEdit.PlainText\n", ""),
    ("id: userText", "textFormat: TextEdit.PlainText", "textFormat: TextEdit.RichText"),
    ("id: userText", "readOnly: true", "readOnly: false"),
    ("id: userText", "readOnly: true\n", ""),
    ("id: userText", 'text: message.mine ? message.body : ""', "text: message.body + root.lastError"),
    ("id: plainText", "readOnly: true", "readOnly: false"),
    ("id: plainText", "textFormat: TextEdit.PlainText", "textFormat: TextEdit.MarkdownText"),
    ("id: codeText", "readOnly: true\n", ""),
    ("id: codeText", "textFormat: TextEdit.PlainText\n", ""),
    ("id: wordText", "textFormat: Text.PlainText", "textFormat: Text.StyledText"),
])
def test_proof_ollama_bubble_rule_catches(anchor, old, new):
    assert _ollama_bubble_problems(_mutated_in_block(OLLAMA_CHAT_VIEW, TEXT_ELEMENT, anchor, old, new))


def test_proof_ollama_bubble_rule_catches_a_second_user_text():
    code = _mutated(OLLAMA_CHAT_VIEW, '                            objectName: "userBubble"\n',
                    '                            objectName: "userBubble"\n'
                    "                            Text { textFormat: Text.PlainText; text: message.body }\n")
    assert _ollama_bubble_problems(code)


OLLAMA_OBJECT_NAMES = (
    "clearConfirm", "personaPanel", "personaForA", "personaForB", "personaPicker", "personaInput",
    "compareHint", "problemText", "problemHint", "problemDetail", "retryButton", "inputScroll",
    "ollamaInput", "inputWheelZoom", "sendButton", "replyWords", "paneModel", "personaLine",
    "transcript", "transcriptB", "transcriptBar", "transcriptBarB", "transcriptWheel",
    "userBubble", "editButton", "replyBubble", "hiddenCharsNote", "regenerateButton",
    "backToBottom", "backToBottomB",
)
OLLAMA_MUST_KEEP = {
    "follow": "property bool follow: true",
    "held": "readonly property bool held: list.moving || bar.pressed || wheelSettle.running",
    "pin": "function pin() { if (pane.follow && !pane.held) pane.scrollToEnd()",
    "released": "function released() { pane.follow = pane.sentWhileHeld || pane.atBottom()",
    "released-on-held": "onHeldChanged: { if (!pane.held) pane.released()",
    "wheelSettle": "id: wheelSettle",
    "wheelSettle-restart": "wheelSettle.restart()",
    "transcript-zoom": ("if (wheel.modifiers & Qt.ControlModifier) { wheel.accepted = true "
                        "ollamaView.wheelZoom(wheel) } else { pane.wheeled(wheel) }"),
    "input-zoom": "onWheel: (wheel) => ollamaView.wheelZoom(wheel)",
    "back-to-bottom": 'i18n("Back to bottom")',
    "new-messages": 'i18n("New messages")',
    "back-to-bottom-click": "onClicked: pane.followBottom()",
    "drops": "component TextDropArea: DropArea {",
    "compare": "property bool comparing: false",
    "compare-toggle": "ollamaView.comparing = on === true",
    "compare-queue": 'ollamaView.queuedPrompt = ollamaView.comparing ? input.text : ""',
    "textScale": "property real textScale: 1.0",
    "textScale-pixels": "Math.round(base.pixelSize * ollamaView.textScale)",
    "textScale-points": "spec.pointSize = base.pointSize * ollamaView.textScale",
}
OLLAMA_DROP_TARGETS = 2
# The view, the panes area, the pane, the transcript and the boxes clip; never fewer.
OLLAMA_MIN_CLIPS = 7
TRANSCRIPT_ELEMENT = r"(?<![\w.])ListView\s*\{"


def _ollama_must_keep_problems(code):
    problems = []
    names = [name for binding in re.findall(r"\bobjectName\s*:\s*([^\n]*)", code)
             for name in re.findall(r'"(\w+)"', binding)]
    for name in OLLAMA_OBJECT_NAMES:
        if names.count(name) != 1:
            problems.append(f"objectName:{name}: must be set exactly once, found {names.count(name)}")
    for key, literal in OLLAMA_MUST_KEEP.items():
        count = len(_hits(_code_pattern(literal), code))
        if count != 1:
            problems.append(f"{key}: {literal!r} must appear exactly once, found {count}")
    drops = len(_hits(r"(?<![\w.])TextDropArea\s*\{", code))
    if drops != OLLAMA_DROP_TARGETS:
        problems.append(f"drop-targets: {OLLAMA_DROP_TARGETS} TextDropArea items expected, found {drops}")
    clips = len(_hits(r"(?m)^\s*clip\s*:\s*true\s*$", code))
    if clips < OLLAMA_MIN_CLIPS:
        problems.append(f"clip: at least {OLLAMA_MIN_CLIPS} `clip: true` expected, found {clips}")
    transcripts = [body for _, body in _blocks(code, TRANSCRIPT_ELEMENT)
                   if re.search(r'(?m)^\s*objectName\s*:[^\n]*"transcript"', _top_level_raw(body))]
    if len(transcripts) != 1 or not re.search(r"(?m)^\s*clip\s*:\s*true\s*$", _top_level(transcripts[0])):
        problems.append("transcript-clip: the transcript ListView must clip")
    return problems


def test_ollama_view_keeps_its_scrolling_compare_and_object_names():
    problems = _ollama_must_keep_problems(_read_code(OLLAMA_CHAT_VIEW))
    assert not problems, f"{_rel(OLLAMA_CHAT_VIEW)}: {problems}"


@pytest.mark.parametrize("name", OLLAMA_OBJECT_NAMES)
def test_proof_ollama_object_name_rule_catches(name):
    code = _mutated(OLLAMA_CHAT_VIEW, f'"{name}"', f'"{name}Renamed"')
    assert any(problem.startswith(f"objectName:{name}:") for problem in _ollama_must_keep_problems(code))


@pytest.mark.parametrize(("key", "old", "new"), [
    ("follow", "property bool follow: true", "property bool follow: false"),
    ("held", "list.moving || bar.pressed || wheelSettle.running", "list.moving || bar.pressed"),
    ("pin", "if (pane.follow && !pane.held)\n", "if (pane.follow)\n"),
    ("released", "pane.follow = pane.sentWhileHeld || pane.atBottom()", "pane.follow = true"),
    ("released-on-held", "                pane.released()\n", "                pane.pin()\n"),
    ("wheelSettle", "id: wheelSettle", "id: wheelWait"),
    ("wheelSettle-restart", "wheelSettle.restart()", "wheelSettle.start()"),
    ("transcript-zoom", "                                ollamaView.wheelZoom(wheel)\n",
     "                                pane.wheeled(wheel)\n"),
    ("input-zoom", "onWheel: (wheel) => ollamaView.wheelZoom(wheel)", "onWheel: (wheel) => {}"),
    ("back-to-bottom", 'i18n("Back to bottom")', 'i18n("Jump down")'),
    ("new-messages", 'i18n("New messages")', 'i18n("New text")'),
    ("back-to-bottom-click", "onClicked: pane.followBottom()", "onClicked: pane.scrollToEnd()"),
    ("drops", "component TextDropArea: DropArea {", "component TextDropArea: Item {"),
    ("drop-targets", "        TextDropArea {\n            anchors.fill: parent\n        }\n", ""),
    ("compare", "property bool comparing: false", "property bool comparing: true"),
    ("compare-toggle", "ollamaView.comparing = on === true", "ollamaView.comparing = false"),
    ("compare-queue", 'ollamaView.queuedPrompt = ollamaView.comparing ? input.text : ""',
     'ollamaView.queuedPrompt = ""'),
    ("textScale", "property real textScale: 1.0", "property real textScale: 2.0"),
    ("textScale-pixels", "Math.round(base.pixelSize * ollamaView.textScale)", "Math.round(base.pixelSize)"),
    ("textScale-points", "spec.pointSize = base.pointSize * ollamaView.textScale", "spec.pointSize = base.pointSize"),
    ("clip", "    clip: true\n\n    function scaledFont", "\n    function scaledFont"),
    ("transcript-clip", "                    clip: true\n", ""),
])
def test_proof_ollama_must_keep_rule_catches(key, old, new):
    problems = _ollama_must_keep_problems(_mutated(OLLAMA_CHAT_VIEW, old, new))
    assert any(problem.startswith(f"{key}:") for problem in problems), problems


# --- Round 4, phase 3: panel ring, middle-click, color preview ----------------------------

USAGE_RING = UI / "UsageRing.qml"
SETTINGS_BACKUP_JS = UI / "SettingsBackup.js"
USAGE_HISTORY_JS = UI / "UsageHistory.js"
CONFIG_CHAT = UI / "configChat.qml"
RING_IMPORTS = ["QtQuick", "QtQuick.Shapes"]
RING_ELEMENTS = {"Shape", "ShapePath", "PathAngleArc"}
RING_BANS = {
    "text": r"\b(?:text|textFormat|i18nc?|i18np)\b",
    "outside state": r"\b(?:Plasmoid|Kirigami|root|XMLHttpRequest|console)\b",
    "dynamic creation": r"\b(?:Loader|Repeater|Component)\b",
}


def _usage_ring_problems(code):
    problems = _access_problems(code)
    imports = sorted(re.findall(r"(?m)^\s*import\s+(.*?)\s*$", code))
    if imports != RING_IMPORTS:
        problems.append(f"imports must stay {RING_IMPORTS}, found {imports}")
    blanked = _strip_comments(code, blank_strings=True)
    elements = set(re.findall(r"(?<![\w.])([A-Z][\w.]*)\s*\{", blanked))
    if elements != RING_ELEMENTS:
        problems.append(f"elements must be exactly {sorted(RING_ELEMENTS)}, found {sorted(elements)}")
    problems += [f"{name} at line {line}" for name, pattern in RING_BANS.items() for line in _hits(pattern, blanked)]
    others = [text for text in re.findall(r'"([^"\n]*)"', code) if text != "transparent"]
    if others:
        problems.append(f"no string literal but \"transparent\" is allowed, found {others}")
    return problems


def test_usage_ring_only_draws():
    problems = _usage_ring_problems(_read_code(USAGE_RING))
    assert not problems, f"{_rel(USAGE_RING)}: {problems}"


@pytest.mark.parametrize("snippet", [
    '    Text { text: "62%" }\n',
    '    Image { source: "https://example.invalid/x.png" }\n',
    "    Canvas { }\n",
    "    function f() { return new XMLHttpRequest() }\n",
    '    function f() { return Qt.resolvedUrl("x") }\n',
    "    readonly property string mode: Plasmoid.configuration.panelRing\n",
    "    readonly property color theme: Kirigami.Theme.textColor\n",
    '    property string label: "62%"\n',
    "    Loader { }\n",
])
def test_proof_usage_ring_rule_catches(snippet):
    assert _usage_ring_problems(_appended(USAGE_RING, snippet))


@pytest.mark.parametrize(("old", "new"), [
    ("import QtQuick.Shapes\n", "import QtQuick.Shapes\nimport QtQuick.Controls\n"),
    ("import QtQuick.Shapes\n", 'import QtQuick.Shapes\nimport "UsageLogic.js" as UsageLogic\n'),
    ("import QtQuick\n", "import QtNetwork\n"),
])
def test_proof_usage_ring_import_rule_catches(old, new):
    assert _usage_ring_problems(_mutated(USAGE_RING, old, new))


COMPACT_CLICK = r"\bonClicked\s*:\s*\(\s*mouse\s*\)\s*=>\s*\{"
COMPACT_CLICK_BODY = "{ if (mouse.button === Qt.MiddleButton) root.middleClick() else root.expanded = !root.expanded }"


def _compact_click_problems(compact, main):
    problems = []
    clicks = [body for _, body in _blocks(compact, COMPACT_CLICK)]
    if len(clicks) != 1 or _squeezed(clicks[0]) != COMPACT_CLICK_BODY:
        problems.append(f"onClicked must be exactly {COMPACT_CLICK_BODY}")
    if len(_hits(r"\bmiddleClick\b", compact)) != 1:
        problems.append("CompactRepresentation.qml may name middleClick only in that branch")
    body = _function_body(main, "middleClick")
    if body is None:
        problems.append("main.qml needs exactly one function middleClick()")
    elif _hits(r"\b[Pp]lasmoid\s*\.\s*configuration\b", body):
        problems.append("middleClick() must not touch the configuration")
    return problems


def test_middle_button_runs_exactly_middle_click():
    problems = _compact_click_problems(_read_code(COMPACT_REPRESENTATION), _read_code(MAIN_QML))
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (COMPACT_REPRESENTATION, "            root.middleClick()\n", "            root.refresh()\n"),
    (COMPACT_REPRESENTATION, "            root.middleClick()\n",
     "        {\n            root.middleClick()\n            root.refresh()\n        }\n"),
    (COMPACT_REPRESENTATION, "mouse.button === Qt.MiddleButton", "mouse.button === Qt.RightButton"),
    (COMPACT_REPRESENTATION, "            root.expanded = !root.expanded\n", "            root.middleClick()\n"),
    (COMPACT_REPRESENTATION, "    hoverEnabled: true\n",
     "    hoverEnabled: true\n    onPressAndHold: root.middleClick()\n"),
    (MAIN_QML, "    function middleClick() {\n",
     '    function middleClick() {\n        Plasmoid.configuration.popupDefaultTab = "usage"\n'),
    (MAIN_QML, "    function middleClick() {\n", "    function middleKlick() {\n"),
])
def test_proof_compact_click_rule_catches(path, old, new):
    compact = _mutated(path, old, new) if path == COMPACT_REPRESENTATION else _read_code(COMPACT_REPRESENTATION)
    main = _mutated(path, old, new) if path == MAIN_QML else _read_code(MAIN_QML)
    assert _compact_click_problems(compact, main)


# Config contract: who may write each round-4 key.

WRITE_OPERATOR = r"\s*(?:\+\+|--|(?:[-+*/%&|^]|\*\*|<<|>>>?|&&|\|\||\?\?)?=(?!=))"


def _key_writes(code, keys):
    """(offset, key) of each write of ``keys`` as cfg_key or Plasmoid.configuration.key."""
    names = "|".join(keys)
    return [(match.start(), match.group(1)) for match in re.finditer(
        rf"\b(?:cfg_|[Pp]lasmoid\s*\.\s*configuration\s*\.\s*)({names})\b{WRITE_OPERATOR}", code)]


def _line_at(code, at):
    return code[code.rfind("\n", 0, at) + 1:code.find("\n", at)].strip()


def _single_element_top(code, opener, name):
    elements = _named_elements(code, opener, name)
    return _top_level_raw(elements[0][1]) if len(elements) == 1 else None


COMBO_BOX = r"\bQQC2\s*\.\s*ComboBox\s*\{"
CHECK_BOX = r"\bQQC2\s*\.\s*CheckBox\s*\{"
PANEL_RING_WRITE = "page.cfg_panelRing = value"
MIDDLE_CLICK_WRITE = "onActivated: page.cfg_middleClickOpens = currentValue"
PANEL_RING_CALL = "onActivated: page.setPanelRing(currentValue)"


def _ring_click_writer_problems(sources):
    problems = []
    for name, code in sources.items():
        base = _base(name)
        for at, key in _key_writes(code, ("panelRing", "middleClickOpens")):
            if base == CONFIG_GENERAL.name and _is_apply_backup_line(code, at, key):
                continue
            if key == "panelRing" and base == CONFIG_USAGE.name and _line_at(code, at) == PANEL_RING_WRITE:
                body = _function_body(code, "setPanelRing")
                if body is not None and len(_key_writes(body, (key,))) == 1:
                    continue
            if key == "middleClickOpens" and base == CONFIG_GENERAL.name and _line_at(code, at) == MIDDLE_CLICK_WRITE:
                continue
            problems.append(f"{name}:{_line_of(code, at)}: {key} is written only where the Config contract says")
    usage = sources.get(_rel(CONFIG_USAGE), "")
    general = sources.get(_rel(CONFIG_GENERAL), "")
    ring_top = _single_element_top(usage, COMBO_BOX, "panelRingChoice")
    if ring_top is None or _pin_problems(ring_top, (PANEL_RING_CALL,), "panelRingChoice"):
        problems.append(f"the panelRingChoice ComboBox must have {PANEL_RING_CALL!r}")
    if len(_hits(r"\bsetPanelRing\s*\(", usage)) != 2:
        problems.append("setPanelRing is defined once and called only by panelRingChoice")
    click_top = _single_element_top(general, COMBO_BOX, "middleClickChoice")
    if click_top is None or _pin_problems(click_top, (MIDDLE_CLICK_WRITE,), "middleClickChoice"):
        problems.append(f"the middleClickChoice ComboBox must have {MIDDLE_CLICK_WRITE!r}")
    return problems


def test_ring_and_middle_click_are_written_only_where_the_contract_says():
    problems = _ring_click_writer_problems(_all_code())
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (MAIN_QML, "    function chatNext() {", '    function x() { Plasmoid.configuration.panelRing = "off" }\n    function chatNext() {'),
    (MAIN_QML, "    function chatNext() {",
     '    function x() { Plasmoid.configuration.middleClickOpens = "usage" }\n    function chatNext() {'),
    (CONFIG_CHAT, "    property string cfg_panelRingDefault: \"auto\"\n",
     "    property string cfg_panelRingDefault: \"auto\"\n    function f() { page.cfg_panelRing = \"off\" }\n"),
    (CONFIG_USAGE, "    function setPanelRing(value) {\n",
     "    function g() { page.cfg_middleClickOpens = \"usage\" }\n    function setPanelRing(value) {\n"),
    (CONFIG_USAGE, "    function setPanelRing(value) {\n",
     "    function g() { page.cfg_panelRing = \"off\" }\n    function setPanelRing(value) {\n"),
    (CONFIG_USAGE, "        page.cfg_panelRing = value\n", "        page.cfg_panelRing = \"off\"\n"),
    (CONFIG_USAGE, "onActivated: page.setPanelRing(currentValue)", "onActivated: page.cfg_panelRing = currentValue"),
    (CONFIG_USAGE, "        page.cfg_panelRing = value\n", "        page.cfg_panelRing = value\n        page.setPanelRing(value)\n"),
    (CONFIG_GENERAL, "onActivated: page.cfg_middleClickOpens = currentValue",
     'onActivated: page.cfg_middleClickOpens = "refresh"'),
    (CONFIG_GENERAL, "    function backupStatusText() {\n",
     '    function g() { page.cfg_panelRing = "off" }\n    function backupStatusText() {\n'),
    (CONFIG_GENERAL, "if (values.panelRing !== undefined) page.cfg_panelRing = values.panelRing",
     "if (values.panelRing !== undefined) page.cfg_panelRing = values.usageMode"),
])
def test_proof_ring_and_middle_click_writer_rule_catches(path, old, new):
    assert _ring_click_writer_problems(_sources_with(path, old, new))


def _middle_click_shortcut_problems(sources, settings_logic):
    """The middle-click is a mouse action: nothing of it reaches the keyboard shortcut."""
    problems = [f"shortcut field at {place}" for place in _shortcut_offenders(sources)]
    compact = sources.get(_rel(COMPACT_REPRESENTATION), "")
    main = sources.get(_rel(MAIN_QML), "")
    if _hits(r"(?i)shortcut", compact):
        problems.append("CompactRepresentation.qml must not touch the shortcut")
    click = _function_body(main, "middleClick")
    plan = _function_body(settings_logic, "middleClickPlan")
    if click is None or plan is None:
        return problems + ["exactly one middleClick() and middleClickPlan() expected"]
    if _hits(r"(?i)shortcut", click) or _hits(r"(?i)shortcut", plan):
        problems.append("the middle-click must not use the shortcut's state or plan")
    problems += _pin_problems(main, ("activationTogglesExpanded: false",
                                     "function onActivated() { root.openFromShortcut() }"), "main.qml")
    if _hits(r"\bmiddleClick\b", _function_body(main, "openFromShortcut") or ""):
        problems.append("the shortcut must not run the middle-click")
    return problems


def test_middle_click_adds_nothing_to_the_keyboard_shortcut():
    problems = _middle_click_shortcut_problems(_all_code(), _read_code(SETTINGS_LOGIC_JS))
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (CONFIG_GENERAL, 'import "SettingsLogic.js" as SettingsLogic\n',
     'import "SettingsLogic.js" as SettingsLogic\nimport org.kde.kquickcontrols\n'),
    (COMPACT_REPRESENTATION, "            root.middleClick()\n", "            root.openFromShortcut()\n"),
    (MAIN_QML, "    function middleClick() {\n", "    function middleClick() {\n        root.shortcutOpen = true\n"),
    (MAIN_QML, "activationTogglesExpanded: false", "activationTogglesExpanded: true"),
    (MAIN_QML, "    function openFromShortcut() {\n", "    function openFromShortcut() {\n        root.middleClick()\n"),
    (MAIN_QML, "            root.openFromShortcut()\n", "            root.middleClick()\n"),
    (SETTINGS_LOGIC_JS, "function middleClickPlan(target, state) {\n",
     "function middleClickPlan(target, state) {\n    target = normalizeShortcutTarget(target)\n"),
])
def test_proof_middle_click_shortcut_rule_catches(path, old, new):
    settings_logic = _mutated(path, old, new) if path == SETTINGS_LOGIC_JS else _read_code(SETTINGS_LOGIC_JS)
    sources = _sources_with(path, old, new)
    assert _middle_click_shortcut_problems(sources, settings_logic)


# The color preview is plain text. It reads the page's cfg_ values, the numbers
# derived from them and, for a level with no color chosen, the theme's color
# (fallbackColor). Nothing from the saved configuration or the helper.

PREVIEW_PAGE_MEMBERS = {"previewColor", "levelName", "thresholds", "cfg_usageMode"}
PREVIEW_DATA_MEMBERS = {"level", "shown"}
PREVIEW_BANS = {
    "saved configuration or helper data": r"\b(?:Plasmoid|root|snapshot|Catalog|DataSource)\b",
}
PREVIEW_COLOR_READS = {"cfg_usageNormalColor", "cfg_usageWarnColor", "cfg_usageCriticalColor", "fallbackColor"}
FALLBACK_COLOR_READS = {"cfg_usageWarnColor"}
PREVIEW_THRESHOLDS = ("readonly property var thresholds: UsageLogic.normalizeThresholds("
                      "page.cfg_usageWarnPercent, page.cfg_usageCriticalPercent)")


def _preview_members(body):
    return set(re.findall(r"\bpage\s*\.\s*(\w+)", _strip_comments(body, blank_strings=True)))


def _color_preview_problems(code):
    previews = _named_elements(code, r"(?<![\w.])ColumnLayout\s*\{", "usagePreview")
    if len(previews) != 1:
        return [f"exactly one ColumnLayout usagePreview expected, found {len(previews)}"]
    body = previews[0][1]
    problems = _plain_text_problems(body) + _access_problems(body)
    if not list(_blocks(body, TEXT_ELEMENT)):
        problems.append("the preview has no text element")
    extra = _preview_members(body) - PREVIEW_PAGE_MEMBERS
    if extra:
        problems.append(f"the preview may read only {sorted(PREVIEW_PAGE_MEMBERS)}, found {sorted(extra)}")
    data = set(re.findall(r"\bmodelData\s*\.\s*(\w+)", body)) - PREVIEW_DATA_MEMBERS
    if data:
        problems.append(f"the preview's samples have only {sorted(PREVIEW_DATA_MEMBERS)}, found {sorted(data)}")
    problems += [f"{name} at line {line}" for name, pattern in PREVIEW_BANS.items() for line in _hits(pattern, body)]
    problems += _pin_problems(code, (PREVIEW_THRESHOLDS,), "configUsage.qml")
    problems += _pin_problems(body, ("model: UsageLogic.levelSamples(page.thresholds, page.cfg_usageMode)",), "usagePreview")
    for function, allowed in (("previewColor", PREVIEW_COLOR_READS), ("fallbackColor", FALLBACK_COLOR_READS)):
        function_body = _function_body(code, function)
        if function_body is None:
            problems.append(f"exactly one function {function}() expected")
            continue
        extra = _preview_members(function_body) - allowed
        if extra:
            problems.append(f"{function}() may read only {sorted(allowed)}, found {sorted(extra)}")
        problems += [f"{function}(): {name} at line {line}" for name, pattern in PREVIEW_BANS.items()
                     for line in _hits(pattern, function_body)]
    return problems


def test_color_preview_is_plain_text_and_reads_the_page_only():
    problems = _color_preview_problems(_read_code(CONFIG_USAGE))
    assert not problems, f"{_rel(CONFIG_USAGE)}: {problems}"


@pytest.mark.parametrize(("old", "new"), [
    ('objectName: "usagePreview"', 'objectName: "colorPreview"'),
    ('objectName: "previewLabel_" + sampleRow.modelData.level\n                                textFormat: Text.PlainText\n',
     'objectName: "previewLabel_" + sampleRow.modelData.level\n'),
    ('objectName: "previewLabel_" + sampleRow.modelData.level\n                                textFormat: Text.PlainText\n',
     'objectName: "previewLabel_" + sampleRow.modelData.level\n                                textFormat: Text.RichText\n'),
    ("model: UsageLogic.levelSamples(page.thresholds, page.cfg_usageMode)",
     "model: UsageLogic.levelSamples(root.usageThresholds, page.cfg_usageMode)"),
    ("page.previewColor(sampleRow.modelData.level, Kirigami.Theme)", "Plasmoid.configuration.usageNormalColor"),
    ("page.previewColor(sampleRow.modelData.level, Kirigami.Theme)", "page.providerStatus(sampleRow.modelData.level)"),
    ("page.levelName(sampleRow.modelData.level)", "sampleRow.modelData.caption"),
    ('var chosen = UsageLogic.normalizeColor(level === "normal" ? page.cfg_usageNormalColor',
     'var chosen = UsageLogic.normalizeColor(level === "normal" ? Plasmoid.configuration.usageNormalColor'),
    ('var chosen = UsageLogic.normalizeColor(level === "normal" ? page.cfg_usageNormalColor',
     'var chosen = UsageLogic.normalizeColor(level === "normal" ? page.shownColors.normal'),
    ('UsageLogic.effectiveCriticalColor("", page.cfg_usageWarnColor)', 'UsageLogic.effectiveCriticalColor("", page.shownColors.warning)'),
    ('                    Kirigami.FormData.label: i18n("Preview:")\n',
     '                    Kirigami.FormData.label: i18n("Preview:")\n'
     '                    Image { source: "https://example.invalid/x.png" }\n'),
    ('                    Kirigami.FormData.label: i18n("Preview:")\n',
     '                    Kirigami.FormData.label: i18n("Preview:")\n'
     "                    QQC2.Label { text: page.cfg_usageWarnColor }\n"),
])
def test_proof_color_preview_rule_catches(old, new):
    assert _color_preview_problems(_mutated(CONFIG_USAGE, old, new))


# --- Round 4, phase 4: usage history (opt-in, D70) ----------------------------------------

HISTORY_CHOICE_WRITE = "onToggled: page.cfg_usageHistoryEnabled = checked"


def _js_string_list(code, name):
    match = re.search(rf"\bvar\s+{name}\s*=\s*\[(.*?)\]", code, re.DOTALL)
    return re.findall(r'"([^"\n]*)"', match.group(1)) if match else None


def _usage_history_enabled_problems(sources, entries, backup_keys, excluded_keys):
    problems = []
    writes = [(name, at) for name, code in sources.items() for at, _ in _key_writes(code, ("usageHistoryEnabled",))]
    general_name = _rel(CONFIG_GENERAL)
    general = sources.get(general_name, "")
    if len(writes) != 1 or writes[0][0] != general_name or _line_at(general, writes[0][1]) != HISTORY_CHOICE_WRITE:
        problems.append(f"usageHistoryEnabled is written only by {HISTORY_CHOICE_WRITE!r}, found "
                        f"{[(name, _line_of(sources[name], at)) for name, at in writes]}")
    top = _single_element_top(general, CHECK_BOX, "usageHistoryChoice")
    if top is None or _pin_problems(top, (HISTORY_CHOICE_WRITE,), "usageHistoryChoice"):
        problems.append(f"the usageHistoryChoice CheckBox must have {HISTORY_CHOICE_WRITE!r}")
    privacy = general.find('Kirigami.FormData.label: i18n("Privacy")')
    backup = general.find('Kirigami.FormData.label: i18n("Backup")')
    choice = general.find('objectName: "usageHistoryChoice"')
    if not 0 <= privacy < choice < backup:
        problems.append("usageHistoryChoice belongs in the Privacy section")
    entry = entries.get("usageHistoryEnabled", {})
    if entry.get("type") != "Bool" or entry.get("default") != "false":
        problems.append(f"usageHistoryEnabled must be Bool, default false; got {entry}")
    if "usageHistoryEnabled" not in excluded_keys or "usageHistoryEnabled" in backup_keys:
        problems.append("usageHistoryEnabled must be in EXCLUDED_KEYS and not in BACKUP_KEYS")
    apply_body = _function_body(general, "applyBackup")
    if apply_body is None or _hits(r"\busageHistoryEnabled\b", apply_body):
        problems.append("applyBackup must never name usageHistoryEnabled")
    library = sources.get(_rel(SETTINGS_BACKUP_JS), "")
    if "usageHistoryEnabled" not in (_js_string_list(library, "EXCLUDED_KEYS") or []):
        problems.append("SettingsBackup.js must list usageHistoryEnabled in EXCLUDED_KEYS")
    if _hits(r"\busageHistoryEnabled\b", _function_body(library, "checkedValue") or ""):
        problems.append("checkedValue must not accept usageHistoryEnabled")
    return problems


def test_usage_history_is_opt_in_and_never_imported():
    problems = _usage_history_enabled_problems(_all_code(), _main_xml_entries(), BACKUP_KEYS, EXCLUDED_KEYS)
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (CONFIG_GENERAL, HISTORY_CHOICE_WRITE, "onToggled: page.cfg_usageHistoryEnabled = true"),
    (CONFIG_GENERAL, 'objectName: "usageHistoryChoice"', 'objectName: "historyChoice"'),
    (CONFIG_GENERAL, '        page.backupMessage = "applied"\n',
     '        if (values.usageHistoryEnabled !== undefined) page.cfg_usageHistoryEnabled = values.usageHistoryEnabled\n'
     '        page.backupMessage = "applied"\n'),
    (CONFIG_GENERAL, "    function backupStatusText() {\n",
     "    function g() { page.cfg_usageHistoryEnabled = true }\n    function backupStatusText() {\n"),
    (CONFIG_USAGE, "    function setPanelRing(value) {\n",
     "    function g() { page.cfg_usageHistoryEnabled = true }\n    function setPanelRing(value) {\n"),
    (MAIN_QML, "    function chatNext() {",
     "    function x() { Plasmoid.configuration.usageHistoryEnabled = true }\n    function chatNext() {"),
    (SETTINGS_BACKUP_JS, '"initialSetupComplete", "usageHistoryEnabled", ', '"initialSetupComplete", '),
    (SETTINGS_BACKUP_JS, '    case "panelRing":\n', '    case "usageHistoryEnabled":\n        return bool(value)\n    case "panelRing":\n'),
])
def test_proof_usage_history_enabled_rule_catches(path, old, new):
    assert _usage_history_enabled_problems(_sources_with(path, old, new), _main_xml_entries(), BACKUP_KEYS, EXCLUDED_KEYS)


def test_proof_usage_history_placement_is_caught():
    code = _read_code(CONFIG_GENERAL)
    moved = code.replace('Kirigami.FormData.label: i18n("Privacy")', 'Kirigami.FormData.label: i18n("Other")', 1)
    sources = dict(_all_code(), **{_rel(CONFIG_GENERAL): moved})
    assert _usage_history_enabled_problems(sources, _main_xml_entries(), BACKUP_KEYS, EXCLUDED_KEYS)


@pytest.mark.parametrize(("field", "value"), [("default", "true"), ("type", "String")])
def test_proof_usage_history_default_is_caught(field, value):
    entries = dict(_main_xml_entries())
    entries["usageHistoryEnabled"] = dict(entries["usageHistoryEnabled"], **{field: value})
    assert _usage_history_enabled_problems(_all_code(), entries, BACKUP_KEYS, EXCLUDED_KEYS)


@pytest.mark.parametrize(("backup_keys", "excluded_keys"), [
    (BACKUP_KEYS + ("usageHistoryEnabled",), EXCLUDED_KEYS),
    (BACKUP_KEYS, tuple(key for key in EXCLUDED_KEYS if key != "usageHistoryEnabled")),
])
def test_proof_usage_history_key_lists_are_checked(backup_keys, excluded_keys):
    assert _usage_history_enabled_problems(_all_code(), _main_xml_entries(), backup_keys, excluded_keys)


# usageHistoryClearOwed: main.qml alone stores it; the pages only keep their
# copy in step with what main.qml stored, as they do for the profile generation.

OWED_MIRROR = 'else if (key === "usageHistoryClearOwed") page.cfg_usageHistoryClearOwed = value'


def _clear_owed_writer_problems(sources):
    problems = []
    written = False
    for name, code in sources.items():
        base = _base(name)
        for at, _ in _key_writes(code, ("usageHistoryClearOwed",)):
            line = _line_at(code, at)
            if base == MAIN_QML.name and line.startswith("Plasmoid.configuration."):
                written = True
                continue
            if any(base == page.name for page in CONFIG_PAGES) and line == "page.cfg_usageHistoryClearOwed = value":
                continue
            problems.append(f"{name}:{_line_of(code, at)}: only main.qml stores usageHistoryClearOwed")
        if any(base == page.name for page in CONFIG_PAGES):
            problems += _pin_problems(code, (OWED_MIRROR,), name)
    if not written:
        problems.append("main.qml must store usageHistoryClearOwed")
    return problems


def test_only_main_stores_the_owed_history_delete():
    problems = _clear_owed_writer_problems(_all_code())
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (CONFIG_GENERAL, "    function backupStatusText() {\n",
     "    function g() { page.cfg_usageHistoryClearOwed = false }\n    function backupStatusText() {\n"),
    (CONFIG_GENERAL, '        page.backupMessage = "applied"\n',
     '        page.cfg_usageHistoryClearOwed = false\n        page.backupMessage = "applied"\n'),
    (CONFIG_USAGE, "    function setPanelRing(value) {\n",
     "    function g() { Plasmoid.configuration.usageHistoryClearOwed = false }\n    function setPanelRing(value) {\n"),
    (CONFIG_CHAT, '            else if (key === "usageHistoryClearOwed")\n                page.cfg_usageHistoryClearOwed = value\n', ""),
    (USAGE_VIEW, "            onClicked: root.refresh()\n",
     "            onClicked: { Plasmoid.configuration.usageHistoryClearOwed = false; root.refresh() }\n"),
])
def test_proof_clear_owed_writer_rule_catches(path, old, new):
    assert _clear_owed_writer_problems(_sources_with(path, old, new))


HISTORY_LIBRARY_PINS = (
    "var ID_PATTERN = /^[a-z_]{1,32}$/",
    "var SAMPLE_PATTERN = /^[a-z_]{1,32}\\.[a-z_]{1,32}=(100|[1-9]?[0-9])$/",
    "var MAX_APPLET = 2147483648",
)
HISTORY_VALID_APPLET_BODY = "{ return isInt(value) && value >= 1 && value <= MAX_APPLET }"
HISTORY_COMMAND_BODY = (
    '{ if (OPERATIONS.indexOf(op) < 0 || !isInt(run) || run < 0 || !validApplet(applet)) return "" '
    'var command = "env HEARTHWIRE_RUN=" + run + " python3 -P -m hearthwire --usage-history " + op '
    '+ " --applet " + applet '
    'if (op !== "record") return command '
    'return validSample(sample) ? command + " --sample " + sample : "" }'
)
HISTORY_SAMPLE_PINS = (
    "var pairs = catalogPairs(catalog)",
    'items.push(pairs[index] + "=" + Math.round(Math.max(0, Math.min(100, reading.used_percent))))',
    "var parts = pairs[index].split(\".\")",
    'if (!provider || provider.status !== "ok" || provider.stale === true || !Array.isArray(provider.windows))',
)
HISTORY_VALID_SAMPLE_PINS = (
    'if (typeof sample !== "string" || sample === "") return false',
    "items.every(function (item) { return SAMPLE_PATTERN.test(item) })",
)
HISTORY_OPERATIONS = ["read", "record", "clear"]


def _history_library_problems(code):
    problems = _alert_logic_problems(code) + _access_problems(code)
    if _js_string_list(code, "OPERATIONS") != HISTORY_OPERATIONS:
        problems.append(f"OPERATIONS must stay {HISTORY_OPERATIONS}")
    problems += _pin_problems(code, HISTORY_LIBRARY_PINS, "UsageHistory.js")
    command = _function_body(code, "historyCommand")
    sample = _function_body(code, "sampleArg")
    valid = _function_body(code, "validSample")
    if None in (command, sample, valid):
        return problems + ["exactly one historyCommand(), sampleArg() and validSample() expected"]
    if _squeezed(command) != HISTORY_COMMAND_BODY:
        problems.append(f"historyCommand must stay {HISTORY_COMMAND_BODY}")
    applet = _function_body(code, "validApplet")
    if applet is None or _squeezed(applet) != HISTORY_VALID_APPLET_BODY:
        problems.append(f"validApplet must stay {HISTORY_VALID_APPLET_BODY}")
    problems += _pin_problems(sample, HISTORY_SAMPLE_PINS, "sampleArg()")
    problems += _pin_problems(valid, HISTORY_VALID_SAMPLE_PINS, "validSample()")
    return problems


def test_usage_history_js_is_pure_and_builds_checked_commands():
    problems = _history_library_problems(_read_code(USAGE_HISTORY_JS))
    assert not problems, f"{_rel(USAGE_HISTORY_JS)}: {problems}"


@pytest.mark.parametrize(("old", "new"), [
    (".pragma library\n", ""),
    ("function isInt(value) {", "function reach() { return new XMLHttpRequest() }\nfunction isInt(value) {"),
    ("function isInt(value) {", 'function reach() { return Qt.resolvedUrl("x") }\nfunction isInt(value) {'),
    ("function isInt(value) {", "function logged(value) { console.log(value) }\nfunction isInt(value) {"),
    ("function isInt(value) {", "function saved() { return Plasmoid.configuration.panelRing }\nfunction isInt(value) {"),
    ('var OPERATIONS = ["read", "record", "clear"]', 'var OPERATIONS = ["read", "record", "clear", "dump"]'),
    ("/^[a-z_]{1,32}\\.[a-z_]{1,32}=(100|[1-9]?[0-9])$/", "/^.*$/"),
    ("var ID_PATTERN = /^[a-z_]{1,32}$/", "var ID_PATTERN = /^.+$/"),
    ('return validSample(sample) ? command + " --sample " + sample : ""', 'return command + " --sample " + sample'),
    ("if (OPERATIONS.indexOf(op) < 0 || !isInt(run) || run < 0 || !validApplet(applet))",
     "if (!isInt(run) || run < 0 || !validApplet(applet))"),
    ("if (OPERATIONS.indexOf(op) < 0 || !isInt(run) || run < 0 || !validApplet(applet))",
     "if (OPERATIONS.indexOf(op) < 0 || !validApplet(applet))"),
    ("if (OPERATIONS.indexOf(op) < 0 || !isInt(run) || run < 0 || !validApplet(applet))",
     "if (OPERATIONS.indexOf(op) < 0 || !isInt(run) || run < 0)"),
    ('+ " --applet " + applet\n    if (op !== "record")', '\n    if (op !== "record")'),
    ("return isInt(value) && value >= 1 && value <= MAX_APPLET", "return value !== undefined"),
    ("return isInt(value) && value >= 1 && value <= MAX_APPLET", "return isInt(value) && value <= MAX_APPLET"),
    ("var MAX_APPLET = 2147483648", "var MAX_APPLET = Infinity"),
    ('" python3 -P -m hearthwire --usage-history "', '" python3 -m hearthwire --usage-history "'),
    ('items.push(pairs[index] + "=" + Math.round(Math.max(0, Math.min(100, reading.used_percent))))',
     'items.push(provider.provider_id + "." + reading.kind + "=" + reading.used_percent)'),
    ('items.push(pairs[index] + "=" + Math.round(Math.max(0, Math.min(100, reading.used_percent))))',
     'items.push(pairs[index] + "=" + reading.used_percent)'),
    ("    var pairs = catalogPairs(catalog)\n    var items = []", "    var pairs = list.map(function (p) { return p.provider_id })\n    var items = []"),
    ("return items.length <= MAX_PAIRS && items.every(function (item) { return SAMPLE_PATTERN.test(item) })",
     "return items.length <= MAX_PAIRS"),
])
def test_proof_history_library_rule_catches(old, new):
    assert _history_library_problems(_mutated(USAGE_HISTORY_JS, old, new))


HISTORY_FLAG = r"--usage-history\b"
HISTORY_COMMAND_CALLS = {
    MAIN_QML.name: "UsageHistory.historyCommand(job.op, root.historyRun, Plasmoid.id, job.sample)",
    CONFIG_GENERAL.name: 'UsageHistory.historyCommand("clear", page.historyClearRun, Plasmoid.id)',
}
# Reads: the first one (historyStart) and one each time the popup opens (historyReread).
HISTORY_REQUEST_ARGS = {'"read"': 2, '"record", sample': 1}
HISTORY_REQUEST_ALLOWED = {'"read"', '"record", sample', '"clear"'}
HISTORY_MAIN_PINS = (
    "var sample = UsageHistory.sampleArg(tracked, Catalog.providers)",
    "historySource.connectSource(command)",
    "readonly property bool historyAppletOk: UsageHistory.validApplet(Plasmoid.id)",
)
HISTORY_REQUEST_BODY = ('{ if (!root.historyAppletOk) return '
                        'root.historyQueue = root.historyQueue.concat([{ op: op, sample: sample || "" }]) '
                        'Qt.callLater(root.historyNext) }')


def _history_command_problems(sources):
    problems = []
    for name, code in sources.items():
        base = _base(name)
        flags = _hits(HISTORY_FLAG, code)
        if (base == USAGE_HISTORY_JS.name and len(flags) != 1) or (base != USAGE_HISTORY_JS.name and flags):
            problems.append(f"{name}: --usage-history belongs to historyCommand only (lines {flags})")
        calls = _hits(r"\bhistoryCommand\s*\(", code)
        if base == USAGE_HISTORY_JS.name:
            if len(calls) != 1:
                problems.append(f"{name}: historyCommand is defined once, and not called here")
        elif base in HISTORY_COMMAND_CALLS:
            if len(calls) != 1:
                problems.append(f"{name}: one historyCommand call expected, found {len(calls)}")
            problems += _pin_problems(code, (HISTORY_COMMAND_CALLS[base],), name)
        elif calls:
            problems.append(f"{name}: must not build a history command (lines {calls})")
    main = sources.get(_rel(MAIN_QML), "")
    general = sources.get(_rel(CONFIG_GENERAL), "")
    problems += _pin_problems(main, HISTORY_MAIN_PINS, "main.qml")
    request = _function_body(main, "historyRequest")
    if request is None or _squeezed(request) != HISTORY_REQUEST_BODY:
        problems.append(f"historyRequest must stay {HISTORY_REQUEST_BODY}")
    problems += _pin_problems(general, ("historyClearSource.connectSource(command)",), "configGeneral.qml")
    args = re.findall(r"\bhistoryRequest\s*\(\s*([^()\n]*?)\s*\)", main)
    args = [_squeezed(value) for value in args if value != "op, sample"]
    unknown = sorted(set(args) - HISTORY_REQUEST_ALLOWED)
    if unknown:
        problems.append(f"historyRequest may be called only with {sorted(HISTORY_REQUEST_ALLOWED)}, found {unknown}")
    for value, count in HISTORY_REQUEST_ARGS.items():
        if args.count(value) != count:
            problems.append(f"historyRequest({value}) expected {count} time(s), found {args.count(value)}")
    source_blocks = [(main, "historySource"), (general, "historyClearSource")]
    for code, source in source_blocks:
        for _, body in _blocks(code, r"\bPlasma5Support\s*\.\s*DataSource\s*\{"):
            if re.search(rf"(?:^|[\n;])\s*id\s*:\s*{source}\b", _top_level_raw(body)) and _hits(r"\bstderr\b", body):
                problems.append(f"{source} must read stdout only")
    return problems


def test_history_commands_are_built_only_from_checked_values():
    problems = _history_command_problems(_all_code())
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (MAIN_QML, "UsageHistory.historyCommand(job.op, root.historyRun, Plasmoid.id, job.sample)",
     "UsageHistory.historyCommand(job.op, root.historyRun, Plasmoid.id, root.snapshot.plan)"),
    (MAIN_QML, "UsageHistory.historyCommand(job.op, root.historyRun, Plasmoid.id, job.sample)",
     "UsageHistory.historyCommand(job.op, root.historyRun, root.chatAppletId, job.sample)"),
    (MAIN_QML, "UsageHistory.validApplet(Plasmoid.id)", "UsageHistory.validApplet(root.chatAppletId)"),
    (MAIN_QML, "        if (!root.historyAppletOk)\n            return\n        root.historyQueue = root.historyQueue.concat(",
     "        root.historyQueue = root.historyQueue.concat("),
    (MAIN_QML, '{ op: op, sample: sample || "" }', '{ op: op, sample: sample || Plasmoid.configuration.chatSites }'),
    (MAIN_QML, "UsageHistory.sampleArg(tracked, Catalog.providers)", "UsageHistory.sampleArg(tracked, root.snapshot.catalog)"),
    (MAIN_QML, 'root.historyRequest("record", sample)', 'root.historyRequest("record", tracked[0].plan)'),
    (MAIN_QML, "    function chatNext() {",
     '    function x() { historySource.connectSource("python3 -m hearthwire --usage-history read") }\n    function chatNext() {'),
    (MAIN_QML, "    function chatNext() {",
     '    function x() { root.historyRequest("record", root.lastError) }\n    function chatNext() {'),
    (MAIN_QML, 'root.historyFinish(root.historyOp, data["exit code"], data["stdout"])',
     'root.historyFinish(root.historyOp, data["exit code"], data["stderr"])'),
    (CONFIG_GENERAL, 'UsageHistory.historyCommand("clear", page.historyClearRun, Plasmoid.id)',
     'UsageHistory.historyCommand(page.cfg_usageMode, page.historyClearRun, Plasmoid.id)'),
    (CONFIG_GENERAL, 'UsageHistory.historyCommand("clear", page.historyClearRun, Plasmoid.id)',
     'UsageHistory.historyCommand("clear", page.historyClearRun, page.vaultApplet)'),
    (CONFIG_GENERAL, 'var reply = UsageHistory.parseReply("clear", data["exit code"], data["stdout"], Catalog.providers)',
     'var reply = UsageHistory.parseReply("clear", data["exit code"], data["stderr"], Catalog.providers)'),
    (CONFIG_USAGE, "    function setPanelRing(value) {\n",
     '    function g() { return UsageHistory.historyCommand("read", 1) }\n    function setPanelRing(value) {\n'),
])
def test_proof_history_command_rule_catches(path, old, new):
    assert _history_command_problems(_sources_with(path, old, new))


HISTORY_RECORD_GUARD = "{ if (!root.usageHistoryEnabled || !root.usageShown) return "
HISTORY_START_BODY = ('{ if (root.usageHistoryEnabled && root.usageShown && !root.historyReadDone) { '
                      'root.historyReadDone = true root.historyRequest("read") } }')
HISTORY_REREAD_GUARD = ('{ if (!root.usageHistoryEnabled || !root.usageShown || !root.historyReadDone '
                        '|| root.historyOp === "read" ')
HISTORY_OFF_PINS = (
    "root.historyQueue = []",
    'root.historyRequest("clear")',
)


def _history_guard_problems(code):
    record = _function_body(code, "historyRecord")
    start = _function_body(code, "historyStart")
    finish = _function_body(code, "historyFinish")
    if None in (record, start, finish):
        return ["exactly one historyRecord(), historyStart() and historyFinish() expected"]
    problems = []
    if not _squeezed(record).startswith(HISTORY_RECORD_GUARD):
        problems.append(f"historyRecord must start with {HISTORY_RECORD_GUARD}")
    if len(_hits(_code_pattern('root.historyRequest("record", sample)'), record)) != 1:
        problems.append("the record request belongs to historyRecord")
    if _squeezed(start) != HISTORY_START_BODY:
        problems.append(f"historyStart must stay {HISTORY_START_BODY}")
    reread = _function_body(code, "historyReread")
    if reread is None or not _squeezed(reread).startswith(HISTORY_REREAD_GUARD) \
            or _squeezed(reread).count('root.historyRequest("read")') != 1:
        problems.append(f"historyReread must start with {HISTORY_REREAD_GUARD} and ask for one read")
    reads = [at for at in _hits(_code_pattern('root.historyRequest("read")'), code)]
    if len(reads) != 2:
        problems.append("a read is asked for only by historyStart and historyReread")
    problems += _pin_problems(finish, ("} else if (root.usageHistoryEnabled) {",), "historyFinish()")
    handlers = [body for _, body in _blocks(code, r"(?<![\w.])onUsageHistoryEnabledChanged\s*:\s*\{")]
    if len(handlers) != 1:
        return problems + ["exactly one onUsageHistoryEnabledChanged expected"]
    tail = handlers[0][handlers[0].find("root.historyStart()"):]
    if "return" not in tail or tail.find("return") > tail.find("root.historyQueue"):
        problems.append("while turning on, the handler must stop before the off branch")
    problems += _pin_problems(tail, HISTORY_OFF_PINS, "the off branch")
    drop = tail.find("root.historyQueue = []")
    if drop > tail.find('root.historyRequest("clear")'):
        problems.append("turning off must drop the queued steps before asking for the clear")
    problems += _pin_problems(code, ("root.historyRecord(payload.providers)",), "main.qml")
    if len(_hits(r"\bhistoryRecord\s*\(", code)) != 2:
        problems.append("historyRecord is defined once and called once, after a good snapshot")
    return problems


def test_no_history_read_or_record_runs_while_disabled():
    problems = _history_guard_problems(_read_code(MAIN_QML))
    assert not problems, f"{_rel(MAIN_QML)}: {problems}"


@pytest.mark.parametrize(("old", "new"), [
    ("        if (!root.usageHistoryEnabled || !root.usageShown)\n            return\n        var now = Date.now()\n",
     "        var now = Date.now()\n"),
    ("if (!root.usageHistoryEnabled || !root.usageShown)", "if (!root.usageShown)"),
    ("if (root.usageHistoryEnabled && root.usageShown && !root.historyReadDone) {", "if (root.usageShown && !root.historyReadDone) {"),
    ('            root.historyRequest("read")\n', '            root.historyRequest("read")\n            root.historyRequest("read")\n'),
    ("} else if (root.usageHistoryEnabled) {", "} else {"),
    ("if (!root.usageHistoryEnabled || !root.usageShown || !root.historyReadDone",
     "if (!root.usageShown || !root.historyReadDone"),
    ("    function historyReread() {\n", "    function historyReread() {\n        root.historyRequest(\"read\")\n"),
    ("    function chatNext() {", '    function x() { root.historyRequest("read") }\n    function chatNext() {'),
    ('        root.historyQueue = []\n        root.historyRequest("clear")\n', '        root.historyRequest("clear")\n'),
    ('        root.historyQueue = []\n        root.historyRequest("clear")\n', '        root.historyRequest("clear")\n        root.historyQueue = []\n'),
    ("            root.historyStart()\n            return\n", "            root.historyStart()\n"),
    ("        root.historyRecord(payload.providers)\n", "        root.historyRecord(root.snapshot.providers)\n"),
    ("    function chatNext() {", "    function x() { root.historyRecord([]) }\n    function chatNext() {"),
])
def test_proof_history_guard_rule_catches(old, new):
    assert _history_guard_problems(_mutated(MAIN_QML, old, new))


SPARKLINE_BANS = {
    "canvas text": r"\b(?:fillText|strokeText|measureText|font)\b",
    "canvas image": r"\b(?:drawImage|loadImage|unloadImage|isImageLoaded|isImageError|createPattern|createImageData|getImageData|putImageData)\b",
    "canvas file": r"\.\s*(?:save|toDataURL|grabToImage)\s*\(",
    "text element": TEXT_ELEMENT,
}
SPARKLINE_PINS = (
    "readonly property var points: root.historyPoints(providerSection.modelData.provider_id, quotaCard.modelData.kind)",
    "UsageHistory.sparkSegments(sparkline.points, root.historyNow, root.usageMode,",
    "Accessible.ignored: true",
)


def _sparkline_problems(code, sources):
    canvases = _named_elements(code, r"(?<![\w.])Canvas\s*\{", "usageSparkline")
    if len(canvases) != 1:
        return [f"exactly one Canvas usageSparkline expected, found {len(canvases)}"]
    body = canvases[0][1]
    problems = _access_problems(body)
    problems += [f"{name} at line {line}" for name, pattern in SPARKLINE_BANS.items() for line in _hits(pattern, body)]
    if re.search(r"(?:^|[\n;])\s*text\s*:", _top_level_raw(body)):
        problems.append("the sparkline must not bind text")
    problems += _pin_problems(body, SPARKLINE_PINS, "usageSparkline")
    others = [f"{name}:{line}" for name, text in sources.items()
              for line in _hits(r"(?<![\w.])Canvas\s*\{", text)]
    if len(others) != 1:
        problems.append(f"the sparkline is the only Canvas, found {others}")
    return problems


def test_sparkline_draws_only_lines():
    problems = _sparkline_problems(_read_code(USAGE_VIEW), _all_code())
    assert not problems, f"{_rel(USAGE_VIEW)}: {problems}"


@pytest.mark.parametrize(("path", "old", "new"), [
    (USAGE_VIEW, 'objectName: "usageSparkline"', 'objectName: "sparkline"'),
    (USAGE_VIEW, "                                            context.reset()\n",
     '                                            context.fillText("62%", 0, 0)\n'),
    (USAGE_VIEW, "                                            context.reset()\n",
     '                                            context.font = "12px sans"\n'),
    (USAGE_VIEW, "                                            context.reset()\n",
     '                                            context.drawImage("https://example.invalid/x.png", 0, 0)\n'),
    (USAGE_VIEW, "                                            context.reset()\n",
     '                                            sparkline.loadImage("file:///tmp/x.png")\n'),
    (USAGE_VIEW, "                                            context.reset()\n",
     '                                            sparkline.save("/tmp/x.png")\n'),
    (USAGE_VIEW, "                                        Accessible.ignored: true\n",
     "                                        Accessible.ignored: true\n"
     "                                        Text { text: quotaCard.modelData.caption; textFormat: Text.PlainText }\n"),
    (USAGE_VIEW, "root.historyPoints(\n                                            providerSection.modelData.provider_id,",
     "root.historyPoints(\n                                            providerSection.modelData.display_name,"),
    (FULL_REPRESENTATION, "    function ", "    Canvas { }\n    function "),
])
def test_proof_sparkline_rule_catches(path, old, new):
    sources = _sources_with(path, old, new)
    assert _sparkline_problems(sources[_rel(USAGE_VIEW)], sources)


LEGACY_DATA_TEXT = ("Saved sign-ins from the previous version haven't been moved yet. "
                    "Run the installer again with --restart-plasma.")
FIXED_RETURN = r'i18n\("[^"\n]*"\)'
REPLY_ERROR_CHECK = "ERRORS.indexOf(reply.error) >= 0 ? { ok: false, error: reply.error } :"
HISTORY_NOTICE = (
    'readonly property string historyNotice: !root.historyAppletOk '
    '&& (root.usageHistoryEnabled || Plasmoid.configuration.usageHistoryClearOwed === true) '
    '? i18n("This widget couldn\'t be identified, so its usage history can\'t be used.") '
    ': root.historyClearFailed '
    '? i18n("The usage history couldn\'t be deleted. Use Delete usage history in Settings → General → Privacy.") '
    f': root.historyError === "legacy-data" ? i18n("{LEGACY_DATA_TEXT}") : ""'
)
HISTORY_ERROR_FORMS = (
    r'property\s+string\s+historyError\s*:\s*""',
    r'root\s*\.\s*historyError\s*===\s*"legacy-data"',
    r'root\s*\.\s*historyError\s*=\s*reply\s*\.\s*error\s*$',
    r'root\s*\.\s*historyError\s*=\s*""\s*$',
)
HISTORY_CLEAR_STATE_FORMS = (
    r'property\s+string\s+historyClearState\s*:\s*""',
    r'page\s*\.\s*historyClearState\s*(?:===|!==)\s*"\w+"',
    r'page\s*\.\s*historyClearState\s*=\s*"(?:busy|no-applet)"\s*$',
    r'page\s*\.\s*historyClearState\s*=\s*reply\s*\.\s*ok\s*\?\s*"ok"\s*:\s*reply\s*\.\s*error\s*$',
    r'page\s*\.\s*historyClearText\s*\(\s*page\s*\.\s*historyClearState\s*\)',
)


def _fixed_text_problems(body, name, also=()):
    return [f"{name}() may return only fixed text, found {value}" for value in _returns(body)
            if value != '""' and not re.fullmatch(FIXED_RETURN, value) and value not in also]


def _case_returns(body, case):
    """The return of ``case "...":`` in a switch, through any stacked cases."""
    match = re.search(rf'case\s*"{case}"\s*:\s*(?:case\s*"[\w-]+"\s*:\s*)*return\s+([^\n]*)', body)
    return match.group(1).strip() if match else None


def _unknown_mentions(code, word, forms):
    problems = []
    for match in re.finditer(rf"\b{word}\b", code):
        line = code[code.rfind("\n", 0, match.start()) + 1:code.find("\n", match.start())]
        if not any(re.search(form, line) for form in forms):
            problems.append(f"line {_line_of(code, match.start())}: unexpected use of {word}")
    return problems


def _plain_label_problems(code, opener, name, text):
    labels = _named_elements(code, opener, name)
    if len(labels) != 1:
        return [f"exactly one text element {name} expected, found {len(labels)}"]
    problems = []
    if len(re.findall(PLAIN_TEXT_FORMAT, _top_level(labels[0][1]))) != 1:
        problems.append(f"{name} needs textFormat PlainText")
    if text is not None and _text_binding(labels[0][1]) != text:
        problems.append(f"{name} must show {text}, found {_text_binding(labels[0][1])}")
    return problems


def _history_message_problems(main, general, view, library):
    problems = _pin_problems(main, (HISTORY_NOTICE,), "main.qml")
    problems += _unknown_mentions(main, "historyError", HISTORY_ERROR_FORMS)
    problems += _unknown_mentions(general, "historyClearState", HISTORY_CLEAR_STATE_FORMS)
    problems += _plain_label_problems(view, TEXT_ELEMENT, "usageHistoryNotice", "root.historyNotice")
    problems += _plain_label_problems(general, TEXT_ELEMENT, "usageHistoryStatus", "page.historyClearText(page.historyClearState)")
    problems += _plain_label_problems(general, TEXT_ELEMENT, "usageHistoryExplanation", None)
    problems += _plain_label_problems(general, TEXT_ELEMENT, "usageHistoryOwedNotice", None)
    body = _function_body(general, "historyClearText")
    if body is None:
        return problems + ["exactly one function historyClearText() expected"]
    problems += _fixed_text_problems(body, "historyClearText")
    if not re.fullmatch(FIXED_RETURN, _case_returns(body, "no-applet") or ""):
        problems.append("historyClearText must map no-applet to a fixed message")
    parse = _function_body(library, "parseReply")
    if parse is None:
        return problems + ["exactly one function parseReply() expected"]
    problems += _pin_problems(parse, (REPLY_ERROR_CHECK,), "UsageHistory.parseReply()")
    return problems


def test_history_messages_are_fixed_text():
    problems = _history_message_problems(_read_code(MAIN_QML), _read_code(CONFIG_GENERAL),
                                         _read_code(USAGE_VIEW), _read_code(USAGE_HISTORY_JS))
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (MAIN_QML, ': root.historyError === "legacy-data"\n', ': root.historyError !== ""\n'),
    (MAIN_QML, "        ? i18n(\"The usage history couldn't be deleted. Use Delete usage history in Settings → General → Privacy.\")\n",
     "        ? root.historyError\n"),
    (MAIN_QML, "    function chatNext() {", "    function x() { root.lastError = root.historyError }\n    function chatNext() {"),
    (MAIN_QML, "                root.historyError = reply.error\n", '                root.historyError = data["stderr"]\n'),
    (USAGE_VIEW, "        text: root.historyNotice\n", "        text: root.historyError\n"),
    (USAGE_VIEW, "        textFormat: Text.PlainText\n        text: root.historyNotice\n", "        text: root.historyNotice\n"),
    (CONFIG_GENERAL, "text: page.historyClearText(page.historyClearState)", "text: page.historyClearState"),
    (CONFIG_GENERAL, 'return i18n("Couldn\'t delete the usage history. Try again in a moment.")', "return state"),
    (CONFIG_GENERAL, 'return i18n("Usage history deleted.")', 'return i18n("Deleted: %1", state)'),
    (CONFIG_GENERAL, '        case "no-applet":\n            return i18n("This widget couldn\'t be identified, so its usage history can\'t be deleted.")\n',
     ""),
    (CONFIG_GENERAL, 'return i18n("This widget couldn\'t be identified, so its usage history can\'t be deleted.")',
     "return state"),
    (CONFIG_GENERAL, 'page.historyClearState = "no-applet"', "page.historyClearState = command"),
    (MAIN_QML, '? i18n("This widget couldn\'t be identified, so its usage history can\'t be used.")',
     "? root.historyError"),
    (CONFIG_GENERAL, 'page.historyClearState = reply.ok ? "ok" : reply.error', 'page.historyClearState = data["stdout"]'),
    (USAGE_HISTORY_JS, "&& ERRORS.indexOf(reply.error) >= 0 ? { ok: false, error: reply.error } : invalid", "? { ok: false, error: reply.error } : invalid"),
])
def test_proof_history_message_rule_catches(path, old, new):
    versions = {target: _mutated(path, old, new) if path == target else _read_code(target)
                for target in (MAIN_QML, CONFIG_GENERAL, USAGE_VIEW, USAGE_HISTORY_JS)}
    assert _history_message_problems(*versions.values())


# --- Round 4, phase 6: settings backup ----------------------------------------------------

BACKUP_LIBRARY_PINS = (
    "var STAMP_PATTERN = /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/",
    "var MAX_APPLET = 2147483648",
)
BACKUP_VALID_APPLET_BODY = "{ return isCount(value) && value >= 1 && value <= MAX_APPLET }"
BACKUP_COMMAND_BODY = (
    '{ if (OPERATIONS.indexOf(op) < 0 || !isCount(run) || !validApplet(applet)) return "" '
    'return "env HEARTHWIRE_RUN=" + run + " python3 -P -m hearthwire --settings-backup " + op '
    '+ " --applet " + applet }'
)
BACKUP_OPERATIONS = ["status", "export", "import"]
# The page's own definition (op) and the three fixed steps; an export sends nothing more.
BACKUP_RUN_ARGS = {'"status"', '"import"', '"export"', "op"}


def _backup_library_problems(code):
    problems = _alert_logic_problems(code) + _access_problems(code)
    if _js_string_list(code, "OPERATIONS") != BACKUP_OPERATIONS:
        problems.append(f"OPERATIONS must stay {BACKUP_OPERATIONS}")
    problems += _pin_problems(code, BACKUP_LIBRARY_PINS, "SettingsBackup.js")
    command = _function_body(code, "backupCommand")
    applet = _function_body(code, "validApplet")
    if None in (command, applet):
        return problems + ["exactly one backupCommand() and validApplet() expected"]
    if _squeezed(command) != BACKUP_COMMAND_BODY:
        problems.append(f"backupCommand must stay {BACKUP_COMMAND_BODY}")
    if _squeezed(applet) != BACKUP_VALID_APPLET_BODY:
        problems.append(f"validApplet must stay {BACKUP_VALID_APPLET_BODY}")
    return problems


def test_settings_backup_js_is_pure_and_builds_checked_commands():
    problems = _backup_library_problems(_read_code(SETTINGS_BACKUP_JS))
    assert not problems, f"{_rel(SETTINGS_BACKUP_JS)}: {problems}"


@pytest.mark.parametrize(("old", "new"), [
    (".pragma library\n", ""),
    ("function isObject(value) {", "function reach() { return new XMLHttpRequest() }\nfunction isObject(value) {"),
    ("function isObject(value) {", 'function reach() { return Qt.resolvedUrl("x") }\nfunction isObject(value) {'),
    ("function isObject(value) {", "function logged(value) { console.log(value) }\nfunction isObject(value) {"),
    ('var OPERATIONS = ["status", "export", "import"]', 'var OPERATIONS = ["status", "export", "import", "path"]'),
    ("if (OPERATIONS.indexOf(op) < 0 || !isCount(run) || !validApplet(applet))",
     "if (!isCount(run) || !validApplet(applet))"),
    ("if (OPERATIONS.indexOf(op) < 0 || !isCount(run) || !validApplet(applet))",
     "if (OPERATIONS.indexOf(op) < 0 || !validApplet(applet))"),
    ("if (OPERATIONS.indexOf(op) < 0 || !isCount(run) || !validApplet(applet))",
     "if (OPERATIONS.indexOf(op) < 0 || !isCount(run))"),
    ('" python3 -P -m hearthwire --settings-backup "', '" python3 -m hearthwire --settings-backup "'),
    ('+ op + " --applet " + applet\n}', '+ op + " --applet " + applet + " --path /tmp/x"\n}'),
    ("return isCount(value) && value >= 1 && value <= MAX_APPLET", "return isCount(value)"),
    ("var MAX_APPLET = 2147483648", "var MAX_APPLET = 9007199254740991"),
])
def test_proof_backup_library_rule_catches(old, new):
    assert _backup_library_problems(_mutated(SETTINGS_BACKUP_JS, old, new))


def _backup_command_problems(sources):
    problems = []
    for name, code in sources.items():
        base = _base(name)
        flags = _hits(r"--settings-backup\b", code)
        if (base == SETTINGS_BACKUP_JS.name and len(flags) != 1) or (base != SETTINGS_BACKUP_JS.name and flags):
            problems.append(f"{name}: --settings-backup belongs to backupCommand only (lines {flags})")
        calls = _hits(r"\bbackupCommand\s*\(", code)
        expected = 1 if base in (SETTINGS_BACKUP_JS.name, CONFIG_GENERAL.name) else 0
        if len(calls) != expected:
            problems.append(f"{name}: {expected} backupCommand mention(s) expected, found {calls}")
    general = sources.get(_rel(CONFIG_GENERAL), "")
    problems += _pin_problems(general, ("SettingsBackup.backupCommand(op, page.backupRun, Plasmoid.id)",
                                        "backupSource.connectSource(command)"), "configGeneral.qml")
    args = {_squeezed(value) for value in re.findall(r"\brunBackup\s*\(([^\n]*)\)\s*(?:\{)?\s*$", general, re.MULTILINE)}
    if args != BACKUP_RUN_ARGS:
        problems.append(f"runBackup may be used only as {sorted(BACKUP_RUN_ARGS)}, found {sorted(args)}")
    for _, body in _blocks(general, r"\bPlasma5Support\s*\.\s*DataSource\s*\{"):
        if re.search(r"(?:^|[\n;])\s*id\s*:\s*backupSource\b", _top_level_raw(body)) and _hits(r"\bstderr\b", body):
            problems.append("backupSource must read stdout only")
    return problems


def test_backup_commands_are_built_only_by_the_library():
    problems = _backup_command_problems(_all_code())
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (CONFIG_GENERAL, "SettingsBackup.backupCommand(op, page.backupRun, Plasmoid.id)",
     "SettingsBackup.backupCommand(op, page.backupRun, page.cfg_chatSites)"),
    (CONFIG_GENERAL, "SettingsBackup.backupCommand(op, page.backupRun, Plasmoid.id)",
     "SettingsBackup.backupCommand(op, page.backupRun, page.vaultApplet)"),
    (CONFIG_GENERAL, 'page.runBackup("export")', 'page.runBackup("export", page.cfg_chatCustomUrls)'),
    (CONFIG_GENERAL, "    function runBackup(op) {", "    function runBackup(op, data) {"),
    (CONFIG_GENERAL, 'page.runBackup("import")', "page.runBackup(page.backupMessage)"),
    (CONFIG_GENERAL, "    function backupStatusText() {\n",
     '    function g() { backupSource.connectSource("python3 -m hearthwire --settings-backup status") }\n    function backupStatusText() {\n'),
    (CONFIG_GENERAL, 'SettingsBackup.parseReply(page.backupOp, data["exit code"], data["stdout"])',
     'SettingsBackup.parseReply(page.backupOp, data["exit code"], data["stderr"])'),
    (CONFIG_USAGE, "    function setPanelRing(value) {\n",
     '    function g() { return SettingsBackup.backupCommand("status", 1) }\n    function setPanelRing(value) {\n'),
])
def test_proof_backup_command_rule_catches(path, old, new):
    assert _backup_command_problems(_sources_with(path, old, new))


APPLY_BACKUP_DYNAMIC = r"\bpage\s*\[|\bfor\s*\(|\bforEach\b|\bObject\s*\.|\beval\b"


def _apply_backup_problems(sources, excluded_keys):
    problems = []
    general_name = _rel(CONFIG_GENERAL)
    for name, code in sources.items():
        mentions = _hits(r"\bapplyBackup\b", code)
        if name != general_name and mentions:
            problems.append(f"{name}: only configGeneral.qml may name applyBackup (lines {mentions})")
    general = sources.get(general_name, "")
    if len(_hits(r"\bapplyBackup\b", general)) != 2:
        problems.append("applyBackup is defined once and called once")
    body = _function_body(general, "applyBackup")
    if body is None:
        return problems + ["exactly one function applyBackup() expected"]
    confirms = _named_elements(general, r"\bKirigami\s*\.\s*InlineMessage\s*\{", "backupImportConfirm")
    actions = [] if len(confirms) != 1 else [
        top for _, action in _blocks(confirms[0][1], r"\bKirigami\s*\.\s*Action\s*\{")
        for top in [_top_level_raw(action)]
        if re.search(r"(?:^|[\n;])\s*onTriggered\s*:\s*page\s*\.\s*applyBackup\s*\(\s*\)\s*(?=;|\n|$)", top)
    ]
    if len(actions) != 1 or not re.search(r'(?:^|[\n;])\s*text\s*:\s*i18n\(\s*"Replace"\s*\)', actions[0]):
        problems.append("applyBackup is called only by the Replace action of backupImportConfirm")
    if _hits(APPLY_BACKUP_DYNAMIC, body):
        problems.append("applyBackup must assign each key by its own line, with no loop or computed name")
    for match in re.finditer(rf"\bcfg_(\w+)\b{WRITE_OPERATOR}", body):
        key = match.group(1)
        line = _line_at(body, match.start())
        if key in excluded_keys:
            problems.append(f"applyBackup must never assign excluded key {key}")
        if not re.fullmatch(rf"if\s*\(\s*values\s*\.\s*{key}\s*!==\s*undefined\s*\)\s*"
                            rf"page\s*\.\s*cfg_{key}\s*=\s*values\s*\.\s*{key}", line):
            problems.append(f"applyBackup: {key} must be assigned by its explicit line, found {line!r}")
    return problems


def test_apply_backup_runs_only_from_replace_and_never_assigns_excluded_keys():
    problems = _apply_backup_problems(_all_code(), EXCLUDED_KEYS)
    assert not problems, problems


APPLY_END = '        page.backupMessage = "applied"\n'


@pytest.mark.parametrize("key", EXCLUDED_KEYS)
def test_proof_apply_backup_excluded_key_is_caught(key):
    new = f"        if (values.{key} !== undefined) page.cfg_{key} = values.{key}\n" + APPLY_END
    problems = _apply_backup_problems(_sources_with(CONFIG_GENERAL, APPLY_END, new), EXCLUDED_KEYS)
    assert any(f"excluded key {key}" in problem for problem in problems), problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (CONFIG_GENERAL, "onTriggered: page.applyBackup()", "onTriggered: page.exportBackup()"),
    (CONFIG_GENERAL, "    onCfg_chatSignInStorageChanged: page.syncSignInChoice()\n",
     "    onCfg_chatSignInStorageChanged: page.applyBackup()\n"),
    (CONFIG_GENERAL, "    function backupStatusText() {\n",
     "    function applyBackup() { }\n    function backupStatusText() {\n"),
    (CONFIG_GENERAL, '                    text: i18n("Replace")\n                    icon.name: "document-import"\n',
     '                    text: i18n("Apply now")\n                    icon.name: "document-import"\n'),
    (CONFIG_GENERAL, 'objectName: "backupImportConfirm"', 'objectName: "backupConfirm"'),
    (CONFIG_GENERAL, "        var values = plan.settings\n",
     "        var values = plan.settings\n        Object.keys(values).forEach(function (key) { page[\"cfg_\" + key] = values[key] })\n"),
    (CONFIG_GENERAL, "if (values.usageMode !== undefined) page.cfg_usageMode = values.usageMode",
     "page.cfg_usageMode = values.usageMode"),
    (CONFIG_USAGE, "    function setPanelRing(value) {\n", "    function applyBackup() { }\n    function setPanelRing(value) {\n"),
])
def test_proof_apply_backup_rule_catches(path, old, new):
    assert _apply_backup_problems(_sources_with(path, old, new), EXCLUDED_KEYS)


def test_proof_apply_backup_uses_the_helper_excluded_list():
    assert _apply_backup_problems(_all_code(), EXCLUDED_KEYS + ("usageMode",))


FILE_PICKER = r"\bQtQuick\s*\.\s*Dialogs\b|\bQt\s*\.\s*labs\s*\.\s*platform\b|\b(?:FileDialog|FolderDialog)\b"


def _file_picker_offenders(code):
    return _hits(FILE_PICKER, code)


def test_settings_general_page_has_no_file_picker():
    offenders = _file_picker_offenders(_read_code(CONFIG_GENERAL))
    assert not offenders, f"{_rel(CONFIG_GENERAL)}: the backup path is fixed by the helper; lines {offenders}"


@pytest.mark.parametrize(("old", "new"), [
    ("import QtQuick.Layouts\n", "import QtQuick.Layouts\nimport QtQuick.Dialogs\n"),
    ("import QtQuick.Layouts\n", "import QtQuick.Layouts\nimport QtQuick.Dialogs as QtDialogs\n"),
    ("import QtQuick.Layouts\n", "import QtQuick.Layouts\nimport Qt.labs.platform\n"),
    ("    QQC2.ButtonGroup {\n", "    FileDialog { }\n    QQC2.ButtonGroup {\n"),
    ("    QQC2.ButtonGroup {\n", "    QtDialogs.FolderDialog { }\n    QQC2.ButtonGroup {\n"),
])
def test_proof_file_picker_rule_catches(old, new):
    assert _file_picker_offenders(_mutated(CONFIG_GENERAL, old, new))


BACKUP_STATUS_RETURNS = ('i18n("Last backup: %1", SettingsBackup.shownStamp(page.backupExportedAt))',
                         "page.backupText(page.backupState)")
SHOWN_STAMP_BODY = '{ return validStamp(value) ? value.replace("T", " ").replace("Z", " UTC") : "" }'
BACKUP_PLAN_ARGS = "page.backupPlan ? page.backupPlan.applied : 0, SettingsBackup.shownStamp(page.backupExportedAt))"
# Counts in replies are whole numbers; the export and import replies keep only them.
BACKUP_COUNT_PINS = (
    "isCount(reply.saved) && reply.saved > 0 && isCount(reply.dropped) "
    "? { ok: true, saved: reply.saved, dropped: reply.dropped } : bad",
    "&& isObject(reply.settings) && isCount(reply.dropped) "
    "? { ok: true, exportedAt: reply.exported_at, settings: reply.settings, dropped: reply.dropped } : bad",
)
BACKUP_LABELS = {
    "backupStatus": "page.backupStatusText()",
    "backupMessage": "page.backupText(page.backupMessage)",
    "backupDroppedCount": 'i18n("Settings left out: %1", page.backupDropped)',
    "backupExplanation": None,
    "backupPlanLabel": None,
    "backupAddressChanges": "page.addressChangeText(page.backupAddressChanges)",
}
# The helper's new codes (export reads Plasma's file) and the page's own.
BACKUP_NEW_CODES = ("applet-not-found", "settings-unreadable", "no-applet")


def _backup_message_problems(general, library):
    problems = []
    for name, text in BACKUP_LABELS.items():
        problems += _plain_label_problems(general, TEXT_ELEMENT, name, text)
    text = _function_body(general, "backupText")
    status = _function_body(general, "backupStatusText")
    if None in (text, status):
        return problems + ["exactly one backupText() and backupStatusText() expected"]
    problems += _fixed_text_problems(text, "backupText")
    problems += _fixed_text_problems(status, "backupStatusText", BACKUP_STATUS_RETURNS)
    if _case_returns(text, "legacy-data") != f'i18n("{LEGACY_DATA_TEXT}")':
        problems.append("backupText must map legacy-data to the fixed message")
    for code in BACKUP_NEW_CODES:
        if not re.fullmatch(FIXED_RETURN, _case_returns(text, code) or ""):
            problems.append(f"backupText must map {code} to a fixed message")
    plan = _single_element_top(general, TEXT_ELEMENT, "backupPlanLabel")
    if plan is None or _pin_problems(plan, (BACKUP_PLAN_ARGS,), "backupPlanLabel"):
        problems.append(f"backupPlanLabel must show only {BACKUP_PLAN_ARGS}")
    stamp = _function_body(library, "shownStamp")
    parse = _function_body(library, "parseReply")
    if None in (stamp, parse):
        return problems + ["exactly one shownStamp() and parseReply() expected"]
    if _squeezed(stamp) != SHOWN_STAMP_BODY:
        problems.append(f"shownStamp must stay {SHOWN_STAMP_BODY}")
    problems += _pin_problems(parse, (REPLY_ERROR_CHECK,) + BACKUP_COUNT_PINS, "SettingsBackup.parseReply()")
    return problems


def test_backup_messages_are_fixed_text_by_code():
    problems = _backup_message_problems(_read_code(CONFIG_GENERAL), _read_code(SETTINGS_BACKUP_JS))
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (CONFIG_GENERAL, 'return i18n("Something went wrong with the backup. Nothing was changed.")', "return code"),
    (CONFIG_GENERAL, 'return i18n("Backup saved.")', 'return i18n("Saved: %1", code)'),
    (CONFIG_GENERAL, '        case "legacy-data":\n            return i18n("Saved sign-ins from the previous version haven\'t been moved yet. Run the installer again with --restart-plasma.")\n',
     ""),
    (CONFIG_GENERAL, '        case "applet-not-found":\n', ""),
    (CONFIG_GENERAL, 'return i18n("This widget\'s applied settings weren\'t found. Press Apply, then try again. Nothing was changed.")',
     "return code"),
    (CONFIG_GENERAL, '        case "settings-unreadable":\n', '        case "settings-unreadable-old":\n'),
    (CONFIG_GENERAL, 'return i18n("This widget couldn\'t be identified, so the backup can\'t be used. Nothing was changed.")',
     'return i18n("No widget %1", Plasmoid.id)'),
    (CONFIG_GENERAL, "text: page.addressChangeText(page.backupAddressChanges)", "text: page.backupAddressChanges.join(\"\\n\")"),
    (CONFIG_GENERAL, 'objectName: "backupAddressChanges"\n            Layout.fillWidth: true\n            visible: page.confirmingImport && text !== ""\n            wrapMode: Text.Wrap\n            textFormat: Text.PlainText\n',
     'objectName: "backupAddressChanges"\n            Layout.fillWidth: true\n            visible: page.confirmingImport && text !== ""\n            wrapMode: Text.Wrap\n            textFormat: Text.AutoText\n'),
    (CONFIG_GENERAL, "SettingsBackup.shownStamp(page.backupExportedAt))\n        case", "page.backupExportedAt)\n        case"),
    (CONFIG_GENERAL, "            return page.backupText(page.backupState)\n", "            return page.backupState\n"),
    (CONFIG_GENERAL, "text: page.backupText(page.backupMessage)", "text: page.backupMessage"),
    (CONFIG_GENERAL, 'objectName: "backupMessage"\n            Layout.fillWidth: true\n            visible: text !== ""\n            wrapMode: Text.WordWrap\n            textFormat: Text.PlainText\n',
     'objectName: "backupMessage"\n            Layout.fillWidth: true\n            visible: text !== ""\n            wrapMode: Text.WordWrap\n'),
    (CONFIG_GENERAL, 'text: i18n("Settings left out: %1", page.backupDropped)', 'text: i18n("Settings left out: %1", page.backupMessage)'),
    (CONFIG_GENERAL, "page.backupPlan ? page.backupPlan.applied : 0, SettingsBackup.shownStamp(page.backupExportedAt))",
     "page.backupPlan ? page.backupPlan.settings.chatSites : 0, SettingsBackup.shownStamp(page.backupExportedAt))"),
    (SETTINGS_BACKUP_JS, 'return validStamp(value) ? value.replace("T", " ").replace("Z", " UTC") : ""', "return value"),
    (SETTINGS_BACKUP_JS, "&& ERRORS.indexOf(reply.error) >= 0 ? { ok: false, error: reply.error } : bad",
     "? { ok: false, error: reply.error } : bad"),
    (SETTINGS_BACKUP_JS, "&& isCount(reply.dropped) ? { ok: true, saved: reply.saved",
     "? { ok: true, saved: reply.saved"),
    (SETTINGS_BACKUP_JS, "&& isObject(reply.settings) && isCount(reply.dropped)", "&& isObject(reply.settings)"),
    (SETTINGS_BACKUP_JS, "dropped: reply.dropped } : bad\n    }", "dropped: reply.dropped, raw: stdout } : bad\n    }"),
])
def test_proof_backup_message_rule_catches(path, old, new):
    general = _mutated(path, old, new) if path == CONFIG_GENERAL else _read_code(CONFIG_GENERAL)
    library = _mutated(path, old, new) if path == SETTINGS_BACKUP_JS else _read_code(SETTINGS_BACKUP_JS)
    assert _backup_message_problems(general, library)


# --- Round 4, audit fix batch: import address changes, M1 guard ---------------------------

# I3: Replace first lists the chat addresses it would change. Addresses come
# from the backup file, so each is capped by UsageLogic.shownText and shown
# as plain text, never opened.

ADDRESS_CHANGE_PAGE_PINS = (
    "page.backupAddressChanges = SettingsBackup.addressChanges(",
    "shownText: UsageLogic.shownText",
    "list.slice(0, SettingsBackup.MAX_SHOWN_CHANGES).forEach(function (change) {",
    "var site = change.id === SettingsBackup.OLLAMA_ID ? null : ChatSites.byId(change.id)",
    'var name = site ? site.name : i18n("Ollama")',
    'lines.push(i18nc("a chat address: site, old address, new address", "%1: %2 → %3", name, change.from, change.to))',
)
ADDRESS_CHANGE_LIBRARY_PINS = (
    "var MAX_SHOWN_CHANGES = 8",
    "result.push({id: id, from: tools.shownText(from), to: tools.shownText(to)})",
    "result.push({id: OLLAMA_ID, from: tools.shownText(now.chatOllamaUrl), to: tools.shownText(next.chatOllamaUrl)})",
)
ADDRESS_CHANGE_FORMS = (
    r"property\s+var\s+backupAddressChanges\s*:\s*\[\s*\]",
    r"page\s*\.\s*backupAddressChanges\s*=\s*\[\s*\]\s*$",
    r"page\s*\.\s*backupAddressChanges\s*=\s*SettingsBackup\s*\.\s*addressChanges\s*\(\s*$",
    r'objectName\s*:\s*"backupAddressChanges"',
    r"page\s*\.\s*addressChangeText\s*\(\s*page\s*\.\s*backupAddressChanges\s*\)",
)


def _address_change_problems(general, library):
    problems = _plain_label_problems(general, TEXT_ELEMENT, "backupAddressChanges",
                                     "page.addressChangeText(page.backupAddressChanges)")
    problems += _pin_problems(general, ADDRESS_CHANGE_PAGE_PINS, "configGeneral.qml")
    problems += _unknown_mentions(general, "backupAddressChanges", ADDRESS_CHANGE_FORMS)
    text = _function_body(general, "addressChangeText")
    changes = _function_body(library, "addressChanges")
    if None in (text, changes):
        return problems + ["exactly one addressChangeText() and addressChanges() expected"]
    if set(_returns(text)) != {'""', 'lines.join("\\n")'}:
        problems.append(f"addressChangeText may return only \"\" or the joined lines, found {_returns(text)}")
    extra = set(re.findall(r"\bchange\s*\.\s*(\w+)", text)) - {"id", "from", "to"}
    if extra:
        problems.append(f"addressChangeText may read only change.id, from and to, found {sorted(extra)}")
    if len(_hits(r"\blines\s*\.\s*push\s*\(", text)) != 2:
        problems.append("addressChangeText pushes one line per change and one count line")
    problems += _pin_problems(library, ADDRESS_CHANGE_LIBRARY_PINS, "SettingsBackup.js")
    if len(_hits(r"\bresult\s*\.\s*push\s*\(", changes)) != 2:
        problems.append("addressChanges adds entries only through its two capped pushes")
    return problems


def test_import_address_changes_are_plain_and_capped():
    problems = _address_change_problems(_read_code(CONFIG_GENERAL), _read_code(SETTINGS_BACKUP_JS))
    assert not problems, problems


@pytest.mark.parametrize(("path", "old", "new"), [
    (CONFIG_GENERAL, "shownText: UsageLogic.shownText", "shownText: function (text) { return text }"),
    (CONFIG_GENERAL, "list.slice(0, SettingsBackup.MAX_SHOWN_CHANGES)", "list"),
    (CONFIG_GENERAL, "name, change.from, change.to))", "name, change.raw, change.to))"),
    (CONFIG_GENERAL, 'var name = site ? site.name : i18n("Ollama")', 'var name = change.name'),
    (CONFIG_GENERAL, '        return lines.join("\\n")\n', '        return lines.join("<br>")\n'),
    (CONFIG_GENERAL, "        page.backupPlan = plan\n",
     "        page.backupPlan = plan\n        page.backupAddressChanges = reply.settings.chatCustomUrls\n"),
    (CONFIG_GENERAL, "            textFormat: Text.PlainText\n            text: page.addressChangeText(page.backupAddressChanges)\n",
     "            textFormat: Text.RichText\n            text: page.addressChangeText(page.backupAddressChanges)\n"),
    (SETTINGS_BACKUP_JS, "from: tools.shownText(from), to: tools.shownText(to)", "from: from, to: tools.shownText(to)"),
    (SETTINGS_BACKUP_JS, "to: tools.shownText(next.chatOllamaUrl)", "to: next.chatOllamaUrl"),
    (SETTINGS_BACKUP_JS, "var MAX_SHOWN_CHANGES = 8", "var MAX_SHOWN_CHANGES = 1000"),
    (SETTINGS_BACKUP_JS, "    return result\n}\n", "    result.push({id: \"x\", from: \"\", to: next.chatCustomUrls})\n    return result\n}\n"),
])
def test_proof_address_change_rule_catches(path, old, new):
    general = _mutated(path, old, new) if path == CONFIG_GENERAL else _read_code(CONFIG_GENERAL)
    library = _mutated(path, old, new) if path == SETTINGS_BACKUP_JS else _read_code(SETTINGS_BACKUP_JS)
    assert _address_change_problems(general, library)


# M1 regression guard: no history or backup command carries settings data.
# Export used to send the settings (custom chat addresses included) as hex in
# argv, readable by every local user in /proc. Now a command is built only by
# its library builder, from fixed text, a known operation, two whole numbers
# (run and widget id) and, for a history record, a sample of catalog ids and
# percentages. The checks below close each way around that: other code in the
# builder, other arguments to it, a changed command before it is run, another
# command sent to the same source, and the old export helpers.

BUILDER_RULES = {
    USAGE_HISTORY_JS: (
        "function historyCommand(op, run, applet, sample) {", "historyCommand",
        {"if", "return", "var", "OPERATIONS", "indexOf", "op", "isInt", "run", "validApplet", "applet",
         "command", "validSample", "sample"},
        {"", "env HEARTHWIRE_RUN=", " python3 -P -m hearthwire --usage-history ", " --applet ", "record", " --sample "},
    ),
    SETTINGS_BACKUP_JS: (
        "function backupCommand(op, run, applet) {", "backupCommand",
        {"if", "return", "OPERATIONS", "indexOf", "op", "isCount", "run", "validApplet", "applet"},
        {"", "env HEARTHWIRE_RUN=", " python3 -P -m hearthwire --settings-backup ", " --applet "},
    ),
}
BUILDER_CALLS = {
    "historyCommand": {"job.op, root.historyRun, Plasmoid.id, job.sample",
                       '"clear", page.historyClearRun, Plasmoid.id'},
    "backupCommand": {"op, page.backupRun, Plasmoid.id"},
}
# (file, function, source id, the command line) of each place a command runs.
COMMAND_SINKS = (
    (MAIN_QML, "historyNext", "historySource",
     "var command = UsageHistory.historyCommand(job.op, root.historyRun, Plasmoid.id, job.sample)"),
    (CONFIG_GENERAL, "clearHistory", "historyClearSource",
     'var command = UsageHistory.historyCommand("clear", page.historyClearRun, Plasmoid.id)'),
    (CONFIG_GENERAL, "runBackup", "backupSource",
     "var command = SettingsBackup.backupCommand(op, page.backupRun, Plasmoid.id)"),
)
SETTINGS_PAYLOAD_BANS = {
    "--data": r"--data\b",
    "old export helper": r"\b(?:exportPayload|hexUtf8|HEX_PATTERN|MAX_DATA_HEX|backupSettings)\b",
}
SINK_BANS = r"\bcfg_\w+|\bPlasmoid\s*\.\s*configuration\b|\bJSON\b|\bencodeURI\w*|\btoString\b|\bbtoa\b|\bsnapshot\b"
QUEUE_FORMS = (
    r"property\s+var\s+historyQueue\s*:\s*\[\s*\]",
    r"root\s*\.\s*historyQueue\s*=\s*root\s*\.\s*historyQueue\s*\.\s*concat\s*\(\s*\[\s*\{\s*op\s*:\s*op\s*,\s*"
    r'sample\s*:\s*sample\s*\|\|\s*""\s*\}\s*\]\s*\)\s*$',
    r"root\s*\.\s*historyQueue\s*\.\s*length\s*===\s*0",
    r"var\s+job\s*=\s*root\s*\.\s*historyQueue\s*\[\s*0\s*\]\s*$",
    r"root\s*\.\s*historyQueue\s*=\s*root\s*\.\s*historyQueue\s*\.\s*slice\s*\(\s*1\s*\)\s*$",
    r"root\s*\.\s*historyQueue\s*=\s*\[\s*\]\s*$",
    r'root\s*\.\s*historyQueue\s*\.\s*some\s*\(\s*function\s*\(\s*job\s*\)\s*\{\s*return\s+job\s*\.\s*op\s*===\s*"\w+"\s*\}\s*\)',
)


def _builder_problems(path, code, rule=None):
    signature, name, identifiers, literals = rule or BUILDER_RULES[path]
    problems = _pin_problems(code, (signature,), path.name)
    body = _function_body(code, name)
    if body is None:
        return problems + [f"{path.name}: exactly one {name}() expected"]
    blanked = _strip_comments(body, blank_strings=True)
    extra = set(re.findall(r"[A-Za-z_$][\w$]*", blanked)) - identifiers
    if extra:
        problems.append(f"{name}() may use only {sorted(identifiers)}, found {sorted(extra)}")
    strings = set(re.findall(r'"([^"\n]*)"', body))
    if strings - literals or _hits(r"['`]", body):
        problems.append(f"{name}() may hold only the literals {sorted(literals)}, found {sorted(strings - literals)}")
    return problems


def _settings_in_command_problems(sources):
    problems = []
    for name, code in sources.items():
        problems += [f"{name}:{line}: {ban}" for ban, pattern in SETTINGS_PAYLOAD_BANS.items()
                     for line in _hits(pattern, code)]
        for builder, allowed in BUILDER_CALLS.items():
            calls = _hits(rf"\.\s*{builder}\s*\(", code)
            args = [_squeezed(value) for value in re.findall(rf"\.\s*{builder}\s*\(([^()]*)\)", code)]
            if len(args) != len(calls) or set(args) - allowed:
                problems.append(f"{name}: {builder} may be called only as {sorted(allowed)}, found {args or calls}")
    for path in BUILDER_RULES:
        problems += _builder_problems(path, sources.get(_rel(path), ""))
    for path, function, source, line in COMMAND_SINKS:
        code = sources.get(_rel(path), "")
        body = _function_body(code, function)
        if body is None:
            problems.append(f"{path.name}: exactly one {function}() expected")
            continue
        problems += _pin_problems(body, (line, f"{source}.connectSource(command)"), f"{path.name} {function}()")
        if len(_hits(rf"\bcommand\b{WRITE_OPERATOR}", body)) != 1:
            problems.append(f"{path.name} {function}(): command is set once, by its builder")
        problems += [f"{path.name} {function}(): {match} must not be near a command"
                     for match in re.findall(SINK_BANS, body)]
        if len(_hits(rf"\b{source}\s*\.\s*connectSource\s*\(", code)) != 1:
            problems.append(f"{path.name}: {source} runs a command only in {function}()")
        if _hits(rf"\b{source}\s*\.\s*connectedSources\b", code):
            problems.append(f"{path.name}: {source}'s sources are set only by connectSource")
        tops = [_top_level_raw(body) for _, body in _blocks(code, r"\bPlasma5Support\s*\.\s*DataSource\s*\{")
                if re.search(rf"(?:^|[\n;])\s*id\s*:\s*{source}\b", _top_level_raw(body))]
        if len(tops) != 1 or not re.search(r"(?:^|[\n;])\s*connectedSources\s*:\s*\[\s*\]\s*(?=;|\n|$)", tops[0]):
            problems.append(f"{path.name}: {source} must start with `connectedSources: []`")
    main = sources.get(_rel(MAIN_QML), "")
    problems += _unknown_mentions(main, "historyQueue", QUEUE_FORMS)
    record = _function_body(main, "historyRecord") or ""
    if len(_hits(r"\bsample\b" + WRITE_OPERATOR, record)) != 1:
        problems.append("historyRecord sets its sample once, from UsageHistory.sampleArg")
    return problems


def test_no_history_or_backup_command_carries_settings_data():
    problems = _settings_in_command_problems(_all_code())
    assert not problems, problems


SETTINGS_ARGV_MUTATIONS = [
    # The builders.
    (SETTINGS_BACKUP_JS, '+ op + " --applet " + applet\n}', '+ op + " --applet " + applet + " --data " + data\n}'),
    (SETTINGS_BACKUP_JS, '+ op + " --applet " + applet\n}', '+ op + " --applet " + applet + " " + JSON.stringify(op)\n}'),
    (SETTINGS_BACKUP_JS, "function backupCommand(op, run, applet) {", "function backupCommand(op, run, applet, settings) {"),
    (SETTINGS_BACKUP_JS, '" --applet " + applet\n}', '" --applet " + applet + " https://example.invalid"\n}'),
    (USAGE_HISTORY_JS, 'command + " --sample " + sample', 'command + " --sample " + encodeURIComponent(sample)'),
    (USAGE_HISTORY_JS, '+ " --applet " + applet\n    if', "+ ' --applet ' + applet\n    if"),
    (USAGE_HISTORY_JS, "function historyCommand(op, run, applet, sample) {",
     "function historyCommand(op, run, applet, sample, extra) {"),
    # Other arguments to a builder.
    (MAIN_QML, "Plasmoid.id, job.sample)", "Plasmoid.id, JSON.stringify(Plasmoid.configuration))"),
    (MAIN_QML, "Plasmoid.id, job.sample)", "Plasmoid.id, job.sample + Plasmoid.configuration.chatSites)"),
    (CONFIG_GENERAL, "SettingsBackup.backupCommand(op, page.backupRun, Plasmoid.id)",
     "SettingsBackup.backupCommand(op, page.backupRun, Plasmoid.id) + \" --data \" + page.cfg_chatCustomUrls"),
    (CONFIG_GENERAL, 'UsageHistory.historyCommand("clear", page.historyClearRun, Plasmoid.id)',
     'UsageHistory.historyCommand("clear", page.historyClearRun, Plasmoid.id, page.cfg_chatSites)'),
    # A changed command, or another one, before it runs.
    (CONFIG_GENERAL, "        page.backupOp = op\n",
     '        command += " " + page.cfg_chatCustomUrls\n        page.backupOp = op\n'),
    (CONFIG_GENERAL, "        page.backupOp = op\n",
     '        command = command + " --da" + "ta " + page.cfg_chatSites\n        page.backupOp = op\n'),
    (CONFIG_GENERAL, "backupSource.connectSource(command)", "backupSource.connectSource(command + \" \" + page.cfg_chatSites)"),
    (CONFIG_GENERAL, "historyClearSource.connectSource(command)", "historyClearSource.connectSource(page.cfg_chatCustomUrls)"),
    (CONFIG_GENERAL, "    function backupStatusText() {\n",
     "    function g() { backupSource.connectSource(\"env x \" + page.cfg_chatCustomUrls) }\n    function backupStatusText() {\n"),
    (CONFIG_GENERAL, '        id: backupSource\n        engine: "executable"\n        connectedSources: []\n',
     '        id: backupSource\n        engine: "executable"\n        connectedSources: [page.cfg_chatCustomUrls]\n'),
    (CONFIG_GENERAL, "    function backupStatusText() {\n",
     "    function g() { backupSource.connectedSources = [page.cfg_chatSites] }\n    function backupStatusText() {\n"),
    (MAIN_QML, "        historySource.connectSource(command)\n",
     "        historySource.connectSource(command + Plasmoid.configuration.chatSites)\n"),
    (MAIN_QML, "        root.historyQueue = root.historyQueue.slice(1)\n",
     "        root.historyQueue = root.historyQueue.slice(1).concat([{op: \"record\", sample: Plasmoid.configuration.chatSites}])\n"),
    (MAIN_QML, "        if (sample === \"\")\n", "        sample += Plasmoid.configuration.chatSites\n        if (sample === \"\")\n"),
    # The old export helpers.
    (SETTINGS_BACKUP_JS, "function validApplet(value) {", "function exportPayload(settings) { return \"\" }\nfunction validApplet(value) {"),
    (CONFIG_GENERAL, "    function backupStatusText() {\n", "    function backupSettings() { return {} }\n    function backupStatusText() {\n"),
    (CONFIG_GENERAL, "    function backupStatusText() {\n", '    function g() { return "--data" }\n    function backupStatusText() {\n'),
]


@pytest.mark.parametrize(("path", "old", "new"), SETTINGS_ARGV_MUTATIONS,
                         ids=[f"{path.name}:{index}" for index, (path, _, _) in enumerate(SETTINGS_ARGV_MUTATIONS)])
def test_proof_settings_in_command_rule_catches(path, old, new):
    assert _settings_in_command_problems(_sources_with(path, old, new))



# --- install hints (plan install-hints) ------------------------------------------------------------
#
# I1 The --install-info command is built only by InstallInfo.command, from
# fixed text, the run number and the applet id (both checked integers), and
# runs once per widget start (main.qml) and once per settings page open
# (configGeneral.qml) through the usual fixed-command pattern: a guard flag,
# the builder, connectSource(command) on its own DataSource, and a reply read
# only through InstallInfo.parseReply from the exit code and stdout. Only the
# checked words of that reply (shadowed, distro) are used.

INSTALL_INFO_FLAG = r"--install-info\b"
INSTALL_INFO_BUILDER = (
    "function command(run, applet) {", "command",
    {"if", "return", "validInt", "run", "applet"},
    {"", "env HEARTHWIRE_RUN=", " HEARTHWIRE_APPLET=", " python3 -P -s -m hearthwire --install-info"},
)
INSTALL_INFO_VALID_INT = ('return typeof value === "number" && Number.isInteger(value) && value >= 0 '
                          "&& value <= 2147483648")
# file -> (the page or widget id, the one builder call)
INSTALL_INFO_CALLERS = {
    MAIN_QML.name: ("root", "InstallInfo.command(ChatStorage.firstRun(Date.now(), Math.random()), "
                            "Math.max(0, root.chatAppletId))"),
    CONFIG_GENERAL.name: ("page", "InstallInfo.command(ChatStorage.firstRun(Date.now(), Math.random()), "
                                  "page.vaultApplet)"),
}
INSTALL_INFO_PARSE = 'InstallInfo.parseReply(data["exit code"], data["stdout"])'


def _install_info_forms(owner):
    """Every line that may mention installInfo, installInfoAsked or installInfoSourceName."""
    o = re.escape(owner)
    return {
        "installInfo": (
            r"^\s*property var installInfo: InstallInfo\.unknown\(\)\s*$",
            rf'^\s*{o}\.installInfo = InstallInfo\.parseReply\(data\["exit code"\], data\["stdout"\]\)\s*$',
            rf"\b{o}\.installInfo\.shadowed === true\b",
            rf"\bChatStorage\.installDistro\({o}\.installInfo\.distro\)",
        ),
        "installInfoAsked": (
            r"^\s*property bool installInfoAsked: false\s*$",
            rf"^\s*if \({o}\.installInfoAsked\)\s*$",
            rf"^\s*{o}\.installInfoAsked = true\s*$",
        ),
        "installInfoSourceName": (
            r'^\s*property string installInfoSourceName: ""\s*$',
            rf"^\s*{o}\.installInfoSourceName = command\s*$",
            rf"^\s*if \(source !== {o}\.installInfoSourceName\)\s*$",
            rf'^\s*{o}\.installInfoSourceName = ""\s*$',
        ),
    }


def _install_info_caller_problems(name, code, owner, call):
    problems = []
    where = f"{name} checkInstall()"
    body = _function_body(code, "checkInstall")
    if body is None:
        return [f"{name}: exactly one checkInstall() expected"]
    problems += _pin_problems(body, (
        f"if ({owner}.installInfoAsked) return", f"{owner}.installInfoAsked = true", f"var command = {call}",
        'if (command === "") return', f"{owner}.installInfoSourceName = command",
        "installInfoSource.connectSource(command)"), where)
    if len(_hits(rf"\bcommand\b{WRITE_OPERATOR}", body)) != 1:
        problems.append(f"{where}: command is set once, by InstallInfo.command")
    problems += [f"{where}: {match} must not be near the command" for match in re.findall(SINK_BANS, body)]
    if len(_squeezed(_strip_comments(body, blank_strings=True)).split(";")) > 1 or _hits(r"['`]", body):
        problems.append(f"{where}: no other statements or strings")
    # Once per start: defined once, called once, from Component.onCompleted.
    if len(_hits(r"\bcheckInstall\s*\(", code)) != 2:
        problems.append(f"{name}: checkInstall() is called once")
    completed = [body for _, body in _blocks(code, r"\bComponent\s*\.\s*onCompleted\s*:\s*\{")]
    if len(completed) != 1 or len(_hits(rf"(?m)^\s*{owner}\s*\.\s*checkInstall\s*\(\s*\)\s*$", completed[0])) != 1:
        problems.append(f"{name}: checkInstall() runs from Component.onCompleted")
    # Its own source, started only here, reading only the exit code and stdout.
    if len(_hits(r"\binstallInfoSource\s*\.\s*connectSource\s*\(", code)) != 1:
        problems.append(f"{name}: installInfoSource runs a command only in checkInstall()")
    if _hits(r"\binstallInfoSource\s*\.\s*connectedSources\b", code):
        problems.append(f"{name}: installInfoSource's sources are set only by connectSource")
    sources = [body for _, body in _blocks(code, r"\bPlasma5Support\s*\.\s*DataSource\s*\{")
               if re.search(r"(?:^|[\n;])\s*id\s*:\s*installInfoSource\b", _top_level_raw(body))]
    if len(sources) != 1:
        problems.append(f"{name}: one installInfoSource DataSource expected, found {len(sources)}")
    else:
        top = _top_level_raw(sources[0])
        problems += _pin_problems(top, ('engine: "executable"', "connectedSources: []"), f"{name} installInfoSource")
        problems += _pin_problems(sources[0], (INSTALL_INFO_PARSE, "installInfoSource.disconnectSource(source)"),
                                  f"{name} installInfoSource")
        if _hits(r"\bstderr\b", sources[0]):
            problems.append(f"{name}: installInfoSource must read stdout only")
    for word, forms in _install_info_forms(owner).items():
        problems += [f"{name}: {problem}" for problem in _unknown_mentions(code, word, forms)]
    return problems


def _install_info_command_problems(sources):
    problems = []
    for name, code in sources.items():
        base = _base(name)
        flags = _hits(INSTALL_INFO_FLAG, code)
        uses = _hits(r"\bInstallInfo\s*\.\s*command\b", code)
        if base == INSTALL_INFO_JS.name:
            body = _function_body(code, "command") or ""
            if len(flags) != 1 or len(_hits(INSTALL_INFO_FLAG, body)) != 1:
                problems.append(f"{name}: --install-info belongs to command() only (lines {flags})")
            if len(_hits(r"\bcommand\s*\(", code)) != 1:
                problems.append(f"{name}: command() is defined once, and not called here")
            problems += _builder_problems(INSTALL_INFO_JS, code, INSTALL_INFO_BUILDER)
            problems += _pin_problems(body, ('if (!validInt(run) || !validInt(applet)) return ""',), f"{name} command()")
            valid = _function_body(code, "validInt")
            if valid is None or _squeezed(valid.strip()[1:-1]) != INSTALL_INFO_VALID_INT:
                problems.append(f"{name}: validInt must stay {INSTALL_INFO_VALID_INT}")
        elif flags:
            problems.append(f"{name}: --install-info belongs to InstallInfo.command only (lines {flags})")
        if base in INSTALL_INFO_CALLERS:
            owner, call = INSTALL_INFO_CALLERS[base]
            if len(uses) != 1:
                problems.append(f"{name}: one InstallInfo.command call expected, found {len(uses)}")
            problems += _install_info_caller_problems(name, code, owner, call)
        elif uses:
            problems.append(f"{name}: must not build the install-info command (lines {uses})")
    for base in INSTALL_INFO_CALLERS:
        if not any(_base(name) == base for name in sources):
            problems.append(f"{base} is missing")
    return problems


def test_install_info_command_is_built_only_from_checked_values():
    problems = _install_info_command_problems(_all_code())
    assert not problems, problems


INSTALL_INFO_COMMAND_MUTATIONS = [
    # The builder.
    (INSTALL_INFO_JS, ' --install-info"', ' --install-info --json"'),
    (INSTALL_INFO_JS, "function command(run, applet) {", "function command(run, applet, extra) {"),
    (INSTALL_INFO_JS, "    if (!validInt(run) || !validInt(applet))\n        return \"\"\n", ""),
    (INSTALL_INFO_JS, '" HEARTHWIRE_APPLET=" + applet', '" HEARTHWIRE_APPLET=" + String(applet)'),
    (INSTALL_INFO_JS, '" HEARTHWIRE_APPLET=" + applet', "' HEARTHWIRE_APPLET=' + applet"),
    (INSTALL_INFO_JS, '" HEARTHWIRE_APPLET=" + applet', '" HEARTHWIRE_APPLET=" + applet + " x"'),
    (INSTALL_INFO_JS, "value <= 2147483648", "value <= 1e300"),
    (INSTALL_INFO_JS, 'typeof value === "number" && ', ""),
    (INSTALL_INFO_JS, "function isShadowed(info) {",
     'function again() { return "python3 -P -m hearthwire --install-info" }\nfunction isShadowed(info) {'),
    (INSTALL_INFO_JS, "function unknown() {", "function rerun() { return command(1, 1) }\nfunction unknown() {"),
    # The callers.
    (MAIN_QML, "Math.random()),\n                                          Math.max(0, root.chatAppletId))",
     "Math.random()),\n                                          Plasmoid.configuration.chatSites)"),
    (MAIN_QML, "        var command = InstallInfo.command(ChatStorage.firstRun(Date.now(), Math.random()),",
     "        var command = InstallInfo.command(root.chatOpRun,"),
    (CONFIG_GENERAL, "page.vaultApplet)\n        if (command", "page.cfg_chatCustomUrls)\n        if (command"),
    (CONFIG_GENERAL, "        page.installInfoSourceName = command\n",
     "        command += \" \" + page.cfg_chatSites\n        page.installInfoSourceName = command\n"),
    (CONFIG_GENERAL, "        installInfoSource.connectSource(command)\n",
     "        installInfoSource.connectSource(command + page.installInfo.helper)\n"),
    (MAIN_QML, "        installInfoSource.connectSource(command)\n",
     "        installInfoSource.connectSource(command)\n        installInfoSource.connectSource(command)\n"),
    (MAIN_QML, "        if (root.installInfoAsked)\n            return\n", ""),
    (MAIN_QML, "        root.checkInstall()\n", "        root.checkInstall()\n        root.checkInstall()\n"),
    (MAIN_QML, "    function droppedDone(reply) {",
     "    function again() { root.installInfoAsked = false; root.checkInstall() }\n    function droppedDone(reply) {"),
    (CONFIG_GENERAL, "        page.checkInstall()\n", ""),
    (CONFIG_GENERAL, "    function checkInstall() {",
     "    function redo() { var command = InstallInfo.command(1, 1) }\n    function checkInstall() {"),
    (MAIN_QML, "    function droppedDone(reply) {",
     '    function x() { usageSource.connectSource("python3 -P -m hearthwire --install-info") }\n    function droppedDone(reply) {'),
    (UI / "UsageView.qml", "        visible: root.installShadowed\n",
     "        visible: root.installShadowed\n        property string c: InstallInfo.command(1, 1)\n"),
    # The reply.
    (MAIN_QML, 'root.installInfo = InstallInfo.parseReply(data["exit code"], data["stdout"])',
     'root.installInfo = InstallInfo.parseReply(data["exit code"], data["stderr"])'),
    (CONFIG_GENERAL, 'page.installInfo = InstallInfo.parseReply(data["exit code"], data["stdout"])',
     'page.installInfo = JSON.parse(data["stdout"])'),
    (MAIN_QML, "    readonly property bool installShadowed: root.installInfo.shadowed === true",
     "    readonly property bool installShadowed: root.installInfo.shadowed === true\n"
     "    readonly property string installWhere: root.installInfo.helper"),
    (MAIN_QML, '        id: installInfoSource\n        engine: "executable"\n        connectedSources: []\n',
     '        id: installInfoSource\n        engine: "executable"\n        connectedSources: [root.installInfoSourceName]\n'),
]


@pytest.mark.parametrize(("path", "old", "new"), INSTALL_INFO_COMMAND_MUTATIONS,
                         ids=[f"{path.name}:{index}" for index, (path, _, _) in enumerate(INSTALL_INFO_COMMAND_MUTATIONS)])
def test_proof_install_info_command_rule_catches(path, old, new):
    assert _install_info_command_problems(_sources_with(path, old, new))


# I2 The shadowed notices are fixed i18n text with nothing clickable: the
# Settings → General notice (a Kirigami.InlineMessage, which reads its text as
# rich text and has no textFormat, so its literal may hold no markup
# characters), the Usage tab's PlainText label, and a read-only field that
# shows the fixed remedy for copying. None of them has a handler, an action
# or a child; none can run a command.

INSTALL_NOTICE_REMEDY = "./scripts/install.sh --remove-script-install"
REMOVE_SCRIPT_COMMAND = f'readonly property string removeScriptCommand: "{INSTALL_NOTICE_REMEDY}"'
TEXT_FIELD = r"(?<![\w.])(?:[A-Za-z_]\w*\s*\.\s*)?TextField\s*\{"
NOTICE_LITERAL = r'(?:^|[\n;])\s*text\s*:\s*i18n\(\s*"([^"\\<>&]*)"\s*\)\s*(?=;|\n|$)'
CLICK_BANS = r"\bon[A-Z]\w*\s*:|\bactions\s*:|\bAction\b|\bMouseArea\b|\b\w*Handler\b|\blink\w*\b|\bconnectSource\b"


def _quiet_element_problems(code, opener, name, visible):
    elements = _named_elements(code, opener, name)
    if len(elements) != 1:
        return [f"exactly one {name} expected, found {len(elements)}"]
    body = elements[0][1]
    blanked = _strip_comments(body, blank_strings=True)
    problems = []
    if blanked.count("{") != 1:
        problems.append(f"{name} may have no child elements or blocks")
    if _hits(CLICK_BANS, blanked):
        problems.append(f"{name} may have no handler, action, link or command")
    problems += _pin_problems(_top_level_raw(body), (f"visible: {visible}",), name)
    return problems


def _notice_text_problems(body, name):
    match = re.search(NOTICE_LITERAL, _top_level_raw(body))
    if match is None or len(re.findall(r"(?:^|[\n;])\s*text\s*:", _top_level(body))) != 1:
        return [f"{name} text must be one fixed i18n literal without markup characters"]
    if INSTALL_NOTICE_REMEDY not in match.group(1) or "kept" not in match.group(1):
        return [f"{name} must name {INSTALL_NOTICE_REMEDY} and say the data is kept"]
    return []


def _install_notice_problems(general, view):
    problems = []
    notice = _named_elements(general, MESSAGE_ELEMENT, "installShadowedNotice")
    problems += _quiet_element_problems(general, MESSAGE_ELEMENT, "installShadowedNotice",
                                        "page.installInfo.shadowed === true")
    if len(notice) == 1:
        problems += _notice_text_problems(notice[0][1], "installShadowedNotice")
    field = _named_elements(general, TEXT_FIELD, "installShadowedCommand")
    problems += _quiet_element_problems(general, TEXT_FIELD, "installShadowedCommand",
                                        "page.installInfo.shadowed === true")
    if len(field) == 1:
        top = _top_level_raw(field[0][1])
        problems += _pin_problems(top, ("readOnly: true", "text: page.removeScriptCommand"), "installShadowedCommand")
        if len(re.findall(r"(?:^|[\n;])\s*(?:readOnly|text)\s*:", top)) != 2:
            problems.append("installShadowedCommand: readOnly and text are bound once each")
    problems += _pin_problems(general, (REMOVE_SCRIPT_COMMAND,), "configGeneral.qml")
    if len(_hits(r"\bremoveScriptCommand\b", general)) != 2 or _hits(r"\bremoveScriptCommand\b", view):
        problems.append("removeScriptCommand is declared once and shown only by installShadowedCommand")
    label = _named_elements(view, TEXT_ELEMENT, "usageInstallNotice")
    problems += _plain_label_problems(view, TEXT_ELEMENT, "usageInstallNotice", None)
    problems += _quiet_element_problems(view, TEXT_ELEMENT, "usageInstallNotice", "root.installShadowed")
    if len(label) == 1:
        problems += _notice_text_problems(label[0][1], "usageInstallNotice")
    return problems


def test_install_notices_are_fixed_text_with_nothing_to_click():
    problems = _install_notice_problems(_read_code(CONFIG_GENERAL), _read_code(USAGE_VIEW))
    assert not problems, problems


INSTALL_NOTICE_MUTATIONS = [
    (CONFIG_GENERAL, '            objectName: "installShadowedNotice"\n',
     '            objectName: "installShadowedNotice"\n            onLinkActivated: (link) => Qt.openUrlExternally(link)\n'),
    (CONFIG_GENERAL, '            objectName: "installShadowedNotice"\n',
     '            objectName: "installShadowedNotice"\n            actions: [Kirigami.Action { text: "Fix"; onTriggered: page.runBackup("status") }]\n'),
    (CONFIG_GENERAL, "text: i18n(\"An older script install of Hearthwire",
     "text: i18n(\"<a href='x'>An older</a> script install of Hearthwire"),
    (CONFIG_GENERAL, "text: i18n(\"An older script install of Hearthwire", "text: page.removeScriptCommand + i18n(\"An older script install of Hearthwire"),
    (CONFIG_GENERAL, "then restart Plasma. Your settings, usage history and saved sign-ins are kept.",
     "then restart Plasma."),
    (CONFIG_GENERAL, '            objectName: "installShadowedCommand"\n',
     '            objectName: "installShadowedCommand"\n            onAccepted: page.runVault("status")\n'),
    (CONFIG_GENERAL, "            readOnly: true\n            selectByMouse: true\n            text: page.removeScriptCommand\n",
     "            readOnly: false\n            selectByMouse: true\n            text: page.removeScriptCommand\n"),
    (CONFIG_GENERAL, "            readOnly: true\n            selectByMouse: true\n            text: page.removeScriptCommand\n",
     "            selectByMouse: true\n            text: page.removeScriptCommand\n"),
    (CONFIG_GENERAL, "            text: page.removeScriptCommand\n",
     "            text: page.removeScriptCommand\n            MouseArea { anchors.fill: parent; onClicked: page.runVault(\"status\") }\n"),
    (CONFIG_GENERAL, REMOVE_SCRIPT_COMMAND, REMOVE_SCRIPT_COMMAND.replace("install.sh", "install.sh --restart-plasma")),
    (CONFIG_GENERAL, "            text: page.removeScriptCommand\n", "            text: page.installInfo.helper\n"),
    (CONFIG_GENERAL, "            text: page.removeScriptCommand\n",
     "            text: page.removeScriptCommand\n            readOnly: true\n"),
    (USAGE_VIEW, "        textFormat: Text.PlainText\n        text: i18n(\"An older script install is running",
     "        textFormat: Text.StyledText\n        text: i18n(\"An older script install is running"),
    (USAGE_VIEW, "        textFormat: Text.PlainText\n        text: i18n(\"An older script install is running",
     "        text: i18n(\"An older script install is running"),
    (USAGE_VIEW, "        visible: root.installShadowed\n",
     "        visible: root.installShadowed\n        TapHandler { onTapped: root.refresh() }\n"),
    (USAGE_VIEW, 'objectName: "usageInstallNotice"', 'objectName: "usageInstallNoticeX"'),
    (USAGE_VIEW, "        visible: root.installShadowed\n", "        visible: true\n"),
]


@pytest.mark.parametrize(("path", "old", "new"), INSTALL_NOTICE_MUTATIONS,
                         ids=[f"{path.name}:{index}" for index, (path, _, _) in enumerate(INSTALL_NOTICE_MUTATIONS)])
def test_proof_install_notice_rule_catches(path, old, new):
    general = _mutated(path, old, new) if path == CONFIG_GENERAL else _read_code(CONFIG_GENERAL)
    view = _mutated(path, old, new) if path == USAGE_VIEW else _read_code(USAGE_VIEW)
    assert _install_notice_problems(general, view)
