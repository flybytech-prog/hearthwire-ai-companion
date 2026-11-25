#!/usr/bin/env python3
"""Copies the plasmoid's QML and JS into the app's build tree (task 012).

Only whole import lines of the KDE modules in IMPORTS change; they point at
the app's private Hearthwire.Compat.* stand-ins instead (aliases kept).
Everything else is copied byte for byte, every .js file too except
ui/Host.js.

The sync stops (SyncError), so nothing of KDE's can slip into the app:
- on an org.kde import it does not know;
- on any other line that still names org.kde.* (an indented, versioned or
  ';'-joined import, a Qt.createQmlObject string, a .js ".import"), except
  whole-line // comments and the KNOWN_TEXT below;
- on a string import (import "...") other than one of the plasmoid's own
  .js files by its bare name, and on any .js ".import";
- when ui/Host.js is missing, left out or not exactly PLASMA_HOST;
- when ui/LinkOut.js is missing, left out or not exactly PLASMA_LINK_OUT.
The one file that changes beyond import lines is ui/Host.js: the app gets
APP_HOST (`var isApp = true`), a fixed text, never anything derived from
the source (task 012 R4 P2a).
ui/LinkOut.js holds the plasmoid's one Qt.openUrlExternally (a chat link
the user confirmed, task 013): the app takes it unchanged, but only as the
exact reviewed bytes, so app/tests/check_no_opener.py can allow that one
file and nothing else.
Stdlib only; writes only into --dest.
"""

import argparse
import re
import sys
from pathlib import Path

# KDE module -> app stand-in. Never an org.kde.* name on the app side.
IMPORTS = {
    "org.kde.kirigami": "Hearthwire.Compat.Kirigami",
    "org.kde.plasma.components": "Hearthwire.Compat.PlasmaComponents",
    "org.kde.plasma.extras": "Hearthwire.Compat.PlasmaExtras",
    "org.kde.plasma.plasmoid": "Hearthwire.Compat.Plasmoid",
    "org.kde.plasma.plasma5support": "Hearthwire.Compat.Plasma5Support",
    "org.kde.plasma.core": "Hearthwire.Compat.PlasmaCore",
    "org.kde.kcmutils": "Hearthwire.Compat.KCMUtils",
    "org.kde.notification": "Hearthwire.Compat.Notification",
    "org.kde.plasma.configuration": "Hearthwire.Compat.Configuration",
}

# Source (relative to the plasmoid's contents/) -> name in --dest. config.qml
# sits next to the pages so its relative "configGeneral.qml" sources resolve.
EXTRA_FILES = {
    "config/config.qml": "config.qml",
    "config/main.xml": "main.xml",
}

IMPORT_LINE = re.compile(r"^import\s+([A-Za-z_][\w.]*)(\s+as\s+[A-Za-z_]\w*)?\s*$")
# A KDE name anywhere in a line, and any string import (also mid-line).
KDE_NAME = re.compile(r"\borg\.kde\b")
# (import"x" needs no space; "import's" in a message is not one).
STRING_IMPORT = re.compile(r"\bimport\s+[\"']|(?:^|[\s;{])import\"")
STRING_IMPORT_LINE = re.compile(r'^import\s+"([^"\\]*)"(\s+as\s+[A-Za-z_]\w*)?\s*$')
JS_NAME = re.compile(r"[A-Za-z_]\w*\.js")
# Text that names org.kde but can't import anything: Plasma's own settings
# file, named in a configGeneral.qml message.
KNOWN_TEXT = ("plasma-org.kde.plasma.desktop-appletsrc",)

# ui/Host.js: which front end runs the pages. The plasmoid's must be exactly
# PLASMA_HOST; the app's copy is exactly APP_HOST.
HOST_JS = "Host.js"
PLASMA_HOST = (
    b".pragma library\n"
    b"// Which front end runs these files: false in the Plasma widget. The\n"
    b"// hearthwire-hyprland app's build (app/tools/sync_plasmoid.py) writes this\n"
    b"// file with \"var isApp = true\" instead; nothing else may change here.\n"
    b"var isApp = false\n"
)
APP_HOST = PLASMA_HOST[: -len(b"false\n")] + b"true\n"

# ui/LinkOut.js: the one place a chat link opens in the system browser. The
# reviewed bytes, synced unchanged; any other text stops the sync. The same
# file's sha256 is pinned on its own in app/tests/check_no_opener.py and
# check_synced.py (tests/test_app_sync.py checks the three agree).
LINK_OUT_JS = "LinkOut.js"
PLASMA_LINK_OUT = (
    b".pragma library\n"
    b"// Where a link the user chose goes: the system browser, through Qt. Only\n"
    b"// ChatWebView calls it, and only for an https address the user confirmed.\n"
    b"// The Plasma widget and the hearthwire-hyprland app use this same file\n"
    b"// unchanged (the app build refuses any other bytes).\n"
    b"function open(url) { Qt.openUrlExternally(url) }\n"
)


class SyncError(Exception):
    pass


def _shown(body):
    return body.strip()[:120]


def check_line(body, string_import_ok=None):
    """SyncError for a line that is kept as it is but names org.kde or imports a file.

    ``string_import_ok(target)`` says whether ``import "<target>"`` (a whole
    line) is allowed; None allows none.
    """
    if body.lstrip().startswith("//"):
        return
    text = body
    for known in KNOWN_TEXT:
        text = text.replace(known, "")
    if KDE_NAME.search(text):
        raise SyncError("a KDE name outside an allowlisted import line: " + _shown(body))
    if STRING_IMPORT.search(body):
        match = STRING_IMPORT_LINE.match(body)
        if match is None or string_import_ok is None or not string_import_ok(match.group(1)):
            raise SyncError("string import not allowed: " + _shown(body))


def rewrite_line(line, string_import_ok=None):
    """The rewritten import line, or the line itself when it is not one (after check_line)."""
    body = line.rstrip("\n")
    match = IMPORT_LINE.match(body)
    if match is not None:
        module = match.group(1)
        if module in IMPORTS:
            newline = line[len(body):]
            return "import " + IMPORTS[module] + (match.group(2) or "") + newline
        if module.startswith("org.kde."):
            raise SyncError("unknown KDE import: " + module)
    check_line(body, string_import_ok)
    return line


def rewrite_qml(text, js_names=()):
    """The QML text with its KDE imports rewritten; ``js_names``: the .js files a string import may name."""
    names = frozenset(js_names)

    def allowed(target):
        return JS_NAME.fullmatch(target) is not None and target in names

    return "".join(rewrite_line(line, allowed) for line in text.splitlines(keepends=True))


def check_js(text):
    """SyncError for a .js file that names org.kde or imports anything (.import)."""
    for line in text.splitlines():
        check_line(line)
        if re.match(r"\s*\.import\b", line):
            raise SyncError(".import in a .js file: " + _shown(line))


def plan(source):
    """(source path, dest name) for every file the app takes from the plasmoid."""
    ui = source / "contents" / "ui"
    if not ui.is_dir():
        raise SyncError("not a plasmoid folder: " + str(source))
    pairs = []
    for path in sorted(ui.iterdir()):
        if path.is_file() and not path.is_symlink() and path.suffix in (".qml", ".js"):
            pairs.append((path, path.name))
    for relative, name in EXTRA_FILES.items():
        path = source / "contents" / relative
        if not path.is_file() or path.is_symlink():
            raise SyncError("missing: " + relative)
        pairs.append((path, name))
    return pairs


def host_js(data):
    """APP_HOST for the plasmoid's Host.js bytes; SyncError unless they are exactly PLASMA_HOST."""
    if data != PLASMA_HOST:
        raise SyncError("ui/" + HOST_JS + " is not the expected file (only its exact text is synced)")
    return APP_HOST


def link_out_js(data):
    """The plasmoid's LinkOut.js bytes as they are; SyncError unless they are exactly PLASMA_LINK_OUT."""
    if data != PLASMA_LINK_OUT:
        raise SyncError("ui/" + LINK_OUT_JS + " is not the reviewed file (only its exact text is synced)")
    return data


# The ui/ files that must be there, exactly as pinned, and can't be left out.
PINNED = {HOST_JS: host_js, LINK_OUT_JS: link_out_js}


def sync(source, dest, exclude=()):
    source = Path(source).resolve()
    dest = Path(dest).resolve()
    if dest == source or source in dest.parents:
        raise SyncError("--dest must be outside the plasmoid folder")
    pairs = plan(source)
    # Checked before anything is written.
    for pinned, check in PINNED.items():
        found = [path for path, name in pairs if name == pinned and path.parent.name == "ui"]
        if not found:
            raise SyncError("missing: ui/" + pinned)
        if pinned in exclude:
            raise SyncError(pinned + " can't be left out")
        check(found[0].read_bytes())
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    js_names = {name for path, name in pairs if path.suffix == ".js" and path.parent.name == "ui"}
    for path, name in pairs:
        if name in exclude:
            continue
        data = path.read_bytes()
        if path.suffix == ".qml":
            data = rewrite_qml(data.decode("utf-8"), js_names).encode("utf-8")
        elif path.suffix == ".js":
            check_js(data.decode("utf-8"))
            if name in PINNED:
                data = PINNED[name](data)
        target = dest / name
        # Rewrite only on a change, so the build doesn't redo unchanged files.
        if not target.is_file() or target.read_bytes() != data:
            target.write_bytes(data)
        written.append(name)
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, help="the plasmoid/ folder")
    parser.add_argument("--dest", required=True, help="output folder in the build tree")
    parser.add_argument("--exclude", action="append", default=[], help="file name to leave out")
    parser.add_argument("--list", action="store_true", help="print the written names, one per line")
    args = parser.parse_args(argv)
    try:
        names = sync(args.source, args.dest, set(args.exclude))
    except (SyncError, OSError, UnicodeDecodeError) as error:
        print("sync_plasmoid: " + str(error), file=sys.stderr)
        return 1
    if args.list:
        print("\n".join(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
