"""The widget's install hints name the packages the packaging files suggest.

ChatStorage.js ``TOOL_PACKAGES`` maps each tool the Chat tab can report
missing (``MISSING_TOOLS`` for Stay signed in, ``WALLET_TOOLS`` for Unlock
with KDE Wallet) to a package per distro family. Those names must be exactly
the optional packages of packaging/arch/PKGBUILD (optdepends),
packaging/fedora/hearthwire.spec (Suggests) and packaging/debian/control
(Suggests), apart from the ones for features the widget never reports as a
missing tool. A difference in either direction fails.
"""

import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
CHAT_STORAGE_JS = ROOT / "plasmoid" / "contents" / "ui" / "ChatStorage.js"
PKGBUILD = ROOT / "packaging" / "arch" / "PKGBUILD"
SPEC = ROOT / "packaging" / "fedora" / "hearthwire.spec"
CONTROL = ROOT / "packaging" / "debian" / "control"
FAMILIES = ("arch", "fedora", "debian")
# Optional packages for features that are not a missing-tool hint: the Chat
# tab's Qt WebEngine, Secret Service sign-ins (secret-tool) and Ollama. Each
# must really be suggested, so a stale entry here fails too.
NOT_TOOL_HINTS = {
    "arch": {"qt6-webengine", "libsecret", "ollama"},
    "fedora": {"libsecret", "ollama"},
    "debian": {"libsecret-tools"},
}


def _js_literal(text, name, opener):
    """The JSON-compatible literal of ``var name = ...`` (strings in double quotes, no comments)."""
    match = re.search(rf"(?m)^var {name} = (?={re.escape(opener)})", text)
    assert match, f"var {name} not found in ChatStorage.js"
    closer = {"{": "}", "[": "]"}[opener]
    depth = 0
    for index in range(match.end(), len(text)):
        if text[index] == opener:
            depth += 1
        elif text[index] == closer:
            depth -= 1
            if depth == 0:
                return json.loads(text[match.end():index + 1])
    raise AssertionError(f"var {name} is not closed")


def widget_tables(text):
    tools = _js_literal(text, "MISSING_TOOLS", "[") + _js_literal(text, "WALLET_TOOLS", "[")
    return tools, _js_literal(text, "TOOL_PACKAGES", "{")


def arch_optional(text):
    block = re.search(r"(?ms)^optdepends=\((.*?)^\)", text)
    assert block, "optdepends not found in PKGBUILD"
    names = []
    for line in block.group(1).splitlines():
        if line.strip():
            entry = re.fullmatch(r"\s*'([a-z0-9][a-z0-9.+_-]*): [^']+'\s*", line)
            assert entry, f"unexpected optdepends line {line!r}"
            names.append(entry.group(1))
    return names


def fedora_optional(text):
    return re.findall(r"(?m)^Suggests:[ \t]+(\S+)[ \t]*$", text)


def debian_optional(text):
    field = re.search(r"(?m)^Suggests:[ \t]*\n((?:[ \t]+\S.*\n?)+)", text)
    assert field, "Suggests not found in debian/control"
    names = [item.strip() for item in field.group(1).replace("\n", " ").split(",") if item.strip()]
    for name in names:
        assert re.fullmatch(r"[a-z0-9][a-z0-9.+-]*", name), f"unexpected Suggests entry {name!r}"
    return names


def sync_problems(storage, pkgbuild, spec, control):
    tools, tables = widget_tables(storage)
    problems = []
    if sorted(tables) != sorted(FAMILIES + ("other",)):
        problems.append(f"TOOL_PACKAGES families must be {sorted(FAMILIES + ('other',))}, got {sorted(tables)}")
    for family, table in tables.items():
        if sorted(table) != sorted(tools):
            problems.append(f"TOOL_PACKAGES.{family} must have exactly the tools {sorted(tools)}, got {sorted(table)}")
    suggested = {"arch": arch_optional(pkgbuild), "fedora": fedora_optional(spec), "debian": debian_optional(control)}
    for family in FAMILIES:
        packaged = set(suggested[family])
        stale = NOT_TOOL_HINTS[family] - packaged
        if stale:
            problems.append(f"{family}: {sorted(stale)} are listed as non-hint packages but not suggested")
        hinted = {package for tool, package in tables.get(family, {}).items() if tool in tools}
        expected = packaged - NOT_TOOL_HINTS[family]
        if hinted - expected:
            problems.append(f"{family}: the widget names {sorted(hinted - expected)}, which the package doesn't suggest")
        if expected - hinted:
            problems.append(f"{family}: the package suggests {sorted(expected - hinted)}, which no widget hint names")
    return problems


def _texts():
    return tuple(path.read_text(encoding="utf-8") for path in (CHAT_STORAGE_JS, PKGBUILD, SPEC, CONTROL))


def test_tool_packages_match_the_packaging_files():
    assert sync_problems(*_texts()) == []


def test_the_tables_cover_every_tool_the_widget_reports():
    tools, tables = widget_tables(CHAT_STORAGE_JS.read_text(encoding="utf-8"))
    assert tools == ["gocryptfs", "gocryptfs-v2", "kdialog", "fusermount3", "kwallet-query", "qdbus6", "openssl"]
    assert all(set(table) == set(tools) for table in tables.values())


MUTATIONS = [
    # The widget names a package the packaging doesn't suggest.
    (0, '"kwallet-query": "kwallet",', '"kwallet-query": "kwallet6",'),
    (0, '"qdbus6": "qt6-qttools",', '"qdbus6": "qdbus-qt6",'),
    (0, '"qdbus6": "qdbus-qt6",', '"qdbus6": "qt6-tools",'),
    # A tool without a package, or an extra entry.
    (0, '        "openssl": "openssl"\n    },\n    "fedora"', '        "x": "openssl"\n    },\n    "fedora"'),
    (0, '"fusermount3": "fuse3",\n        "kwallet-query": "kwallet6"',
     '"fusermount3": "fuse3",\n        "secret-tool": "libsecret-tools",\n        "kwallet-query": "kwallet6"'),
    (0, 'var WALLET_TOOLS = ["kwallet-query", "qdbus6", "openssl"]',
     'var WALLET_TOOLS = ["kwallet-query", "qdbus6", "openssl", "secret-tool"]'),
    (0, '    "debian": {', '    "ubuntu": {'),
    # The packaging suggests a tool package no hint names, or drops one a hint names.
    (1, "  'openssl: setting up Unlock with KDE Wallet'\n", ""),
    (1, "  'qt6-tools: Unlock with KDE Wallet (qdbus6)'", "  'qt6-qttools: Unlock with KDE Wallet (qdbus6)'"),
    (1, "  'kdialog: Stay signed in (passphrase prompts)'\n",
     "  'kdialog: Stay signed in (passphrase prompts)'\n  'zenity: Stay signed in (passphrase prompts)'\n"),
    (1, "  'ollama: built-in Ollama chat (or ollama-cuda / ollama-rocm)'\n", ""),
    (2, "Suggests:       fuse3\n", ""),
    (2, "Suggests:       kf6-kwallet\n", "Suggests:       kf6-kwallet\nSuggests:       kwalletmanager\n"),
    (2, "Suggests:       libsecret\n", ""),
    (3, " qdbus-qt6,\n", ""),
    (3, " kwallet6,\n libsecret-tools,", " kwallet6,\n qt6-tools-dev-tools,\n libsecret-tools,"),
    (3, " libsecret-tools,\n", ""),
]


@pytest.mark.parametrize(("index", "old", "new"), MUTATIONS, ids=[f"{index}:{n}" for n, (index, _, _) in enumerate(MUTATIONS)])
def test_proof_a_mismatch_in_either_direction_fails(index, old, new):
    texts = list(_texts())
    assert texts[index].count(old) == 1, f"proof fixture out of date: {old!r}"
    texts[index] = texts[index].replace(old, new)
    assert sync_problems(*texts)
