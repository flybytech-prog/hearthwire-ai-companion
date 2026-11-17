#!/usr/bin/env python3
"""Copies the plasmoid's QML tests (tests/qml) into the app's build tree (task 012).

The copies run under the app's stand-ins instead of KDE: import lines of
the KDE modules are rewritten exactly as sync_plasmoid.py does, and every
quoted relative path into the plasmoid's ui folder ("../../plasmoid/contents/ui",
in an import or a Loader source) points at the synced copy (--synced)
instead. Nothing else changes. Files named with --exclude (tests that need more than the app's
stand-ins, such as QtWebEngine) are left out. Stdlib only; writes only into
--dest.

As in sync_plasmoid.py, any other line naming org.kde stops the sync, and so
does a string import other than the plasmoid's ui folder, one of its .js
files ("../../plasmoid/contents/ui/<Name>.js") or a .js file of the tests
folder by its bare name.
"""

import argparse
import importlib.util
import os
import re
import sys
from pathlib import Path

PLASMOID_UI = "../../plasmoid/contents/ui"
UI_PATH = re.compile('"' + re.escape(PLASMOID_UI) + r'(?=[/"])')


def _sync_plasmoid():
    path = Path(__file__).resolve().parent / "sync_plasmoid.py"
    spec = importlib.util.spec_from_file_location("sync_plasmoid", path)
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


SYNC = _sync_plasmoid()
SyncError = SYNC.SyncError


def _allowed(synced, js_names):
    def allowed(target):
        if target == synced:
            return True
        if target.startswith(synced + "/"):
            return SYNC.JS_NAME.fullmatch(target[len(synced) + 1:]) is not None
        return SYNC.JS_NAME.fullmatch(target) is not None and target in js_names
    return allowed


def rewrite_line(line, synced, js_names=()):
    """The line with a KDE import or the plasmoid ui paths rewritten; ``js_names``: the tests' own .js files."""
    return SYNC.rewrite_line(UI_PATH.sub(lambda _match: '"' + synced, line), _allowed(synced, frozenset(js_names)))


def rewrite_qml(text, synced, js_names=()):
    return "".join(rewrite_line(line, synced, js_names) for line in text.splitlines(keepends=True))


def sync(source, dest, synced, exclude=()):
    source = Path(source).resolve()
    dest = Path(dest).resolve()
    synced = Path(synced).resolve()
    if dest == source or source in dest.parents:
        raise SyncError("--dest must be outside the tests folder")
    if not source.is_dir():
        raise SyncError("not a folder: " + str(source))
    dest.mkdir(parents=True, exist_ok=True)
    relative = os.path.relpath(synced, dest)
    files = [path for path in sorted(source.iterdir())
             if path.is_file() and not path.is_symlink() and path.suffix in (".qml", ".js") and path.name not in exclude]
    js_names = {path.name for path in files if path.suffix == ".js"}
    written = []
    for path in files:
        data = path.read_bytes()
        if path.suffix == ".qml":
            data = rewrite_qml(data.decode("utf-8"), relative, js_names).encode("utf-8")
        else:
            SYNC.check_js(data.decode("utf-8"))
        target = dest / path.name
        if not target.is_file() or target.read_bytes() != data:
            target.write_bytes(data)
        written.append(path.name)
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, help="the tests/qml folder")
    parser.add_argument("--dest", required=True, help="output folder in the build tree")
    parser.add_argument("--synced", required=True, help="the synced plasmoid folder (sync_plasmoid.py --dest)")
    parser.add_argument("--exclude", action="append", default=[], help="file name to leave out")
    parser.add_argument("--list", action="store_true", help="print the written names, one per line")
    args = parser.parse_args(argv)
    try:
        names = sync(args.source, args.dest, args.synced, set(args.exclude))
    except (SyncError, OSError, UnicodeDecodeError) as error:
        print("sync_qml_tests: " + str(error), file=sys.stderr)
        return 1
    if args.list:
        print("\n".join(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
