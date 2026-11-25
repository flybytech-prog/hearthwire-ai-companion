#!/usr/bin/env python3
"""ctest: the synced plasmoid and QML tests in the build tree name no KDE module.

An independent check of what sync_plasmoid.py and sync_qml_tests.py wrote:
no line (whole-line // comments aside) names org.kde anywhere, except
Plasma's own settings file name in a message; every string import is a
bare <Name>.js of the same folder or the synced folder (or one of its .js
files); a .js file has no .import; the synced Host.js is exactly APP_HOST
(the app's text, written by sync_plasmoid.py; kept here on its own so the
two can't drift together); the synced LinkOut.js is exactly the reviewed
bytes (LINK_OUT_SHA256, task 013; pinned here on its own as well). Stdlib
only; reads, never writes.
Usage: check_synced.py <synced folder> [<qml tests folder>]
"""

import hashlib
import re
import sys
from pathlib import Path

APPLETSRC = "plasma-org.kde.plasma.desktop-appletsrc"
KDE = re.compile(r"\borg\.kde\.")
STRING_IMPORT = re.compile(r"\bimport\s+[\"']([^\"']*)")
APP_HOST = (
    b".pragma library\n"
    b"// Which front end runs these files: false in the Plasma widget. The\n"
    b"// hearthwire-hyprland app's build (app/tools/sync_plasmoid.py) writes this\n"
    b"// file with \"var isApp = true\" instead; nothing else may change here.\n"
    b"var isApp = true\n"
)

# The synced LinkOut.js (the one chat-link opener, synced unchanged).
LINK_OUT_SHA256 = "6d788c93ae5e207d7a8bcc466ff7b57fd6a8290f602ba011d4a916374d2f8d11"


def link_out_problems(synced):
    link_out = synced / "LinkOut.js"
    if link_out.is_symlink() or not link_out.is_file():
        return ["LinkOut.js: missing"]
    if hashlib.sha256(link_out.read_bytes()).hexdigest() != LINK_OUT_SHA256:
        return ["LinkOut.js: not the reviewed bytes"]
    return []


def host_problems(synced):
    host = synced / "Host.js"
    if host.is_symlink() or not host.is_file():
        return ["Host.js: missing"]
    if host.read_bytes() != APP_HOST:
        return ["Host.js: not the app's text (var isApp = true)"]
    return []


def problems(folder, synced):
    found = []
    for path in sorted(folder.iterdir()):
        if path.suffix not in (".qml", ".js"):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            where = "%s:%d" % (path.name, number)
            if line.lstrip().startswith("//"):
                continue
            if KDE.search(line.replace(APPLETSRC, "")):
                found.append(where + ": names org.kde")
            if path.suffix == ".js" and re.match(r"\s*\.import\b", line):
                found.append(where + ": .import")
            for target in STRING_IMPORT.findall(line):
                if re.fullmatch(r"\w+\.js", target) and (folder / target).is_file():
                    continue
                resolved = (folder / target).resolve()
                if resolved == synced or (resolved.parent == synced and re.fullmatch(r"\w+\.js", resolved.name)
                                          and resolved.is_file()):
                    continue
                found.append(where + ": string import " + target)
    return found


def main(argv):
    if len(argv) < 2:
        print(__doc__.splitlines()[-1], file=sys.stderr)
        return 2
    synced = Path(argv[1]).resolve()
    found = host_problems(synced) + link_out_problems(synced)
    for folder in argv[1:]:
        found += problems(Path(folder).resolve(), synced)
    for line in found:
        print(line)
    print("%d problem(s)" % len(found))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
