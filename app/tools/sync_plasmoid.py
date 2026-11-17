#!/usr/bin/env python3
"""Copies the plasmoid's QML and JS into the app's build tree (task 012).

Only whole import lines of the KDE modules in IMPORTS change; they point at
the app's private Hearthwire.Compat.* stand-ins instead (aliases kept).
Everything else, every .js file included, is copied byte for byte.

The sync stops (SyncError), so nothing of KDE's can slip into the app:
- on an org.kde import it does not know;
- on any other line that still names org.kde.* (an indented, versioned or
  ';'-joined import, a Qt.createQmlObject string, a .js ".import"), except
  whole-line // comments and the KNOWN_TEXT below;
- on a string import (import "...") other than one of the plasmoid's own
  .js files by its bare name, and on any .js ".import".
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


def sync(source, dest, exclude=()):
    source = Path(source).resolve()
    dest = Path(dest).resolve()
    if dest == source or source in dest.parents:
        raise SyncError("--dest must be outside the plasmoid folder")
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    pairs = plan(source)
    js_names = {name for path, name in pairs if path.suffix == ".js" and path.parent.name == "ui"}
    for path, name in pairs:
        if name in exclude:
            continue
        data = path.read_bytes()
        if path.suffix == ".qml":
            data = rewrite_qml(data.decode("utf-8"), js_names).encode("utf-8")
        elif path.suffix == ".js":
            check_js(data.decode("utf-8"))
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
