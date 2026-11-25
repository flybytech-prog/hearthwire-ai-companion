#!/usr/bin/env python3
"""ctest: nothing in the app's own code or QML can open a URL or start a program.

decision-1 Q2 (task 012 R4): the About page's links are copy-only, and the
app starts only the helper, only through ProcessRunner. Task 013 (user
decision Q1 = B) amends it by exactly one file: the synced LinkOut.js, the
plasmoid's one Qt.openUrlExternally (a chat link the user confirmed), is
allowed as long as it is exactly the reviewed bytes (LINK_OUT_SHA256) and
sits directly in the folder given as --synced. Anything else that opens a
URL (another file, LinkOut.js anywhere else or under another name, or a
LinkOut.js with any other bytes) is still found; a changed LinkOut.js in
the synced folder is a problem even when it opens nothing.
This scans every regular file under the folders given (app/src, app/qml,
the synced plasmoid), whatever its suffix (.mjs, .cc, .in, ... included),
for the ways out:
- URL openers: Qt.openUrlExternally and any other "openUrl" (also
  QPlatformServices::openUrl), QDesktopServices, QPlatformServices or
  platformIntegration(), KIO's OpenUrlJob and launcher jobs;
- names put together at run time: a quoted piece ending in "Externally",
  "UrlExternally", bracket access on the Qt object (Qt["..."]) and Qt handed
  to a variable or a call (an alias for bracket access later);
- the desktop portal and file manager over D-Bus: org.freedesktop.portal
  (also split as "portal.Desktop" or "freedesktop/portal"), OpenURI, a
  quoted "OpenFile", org.freedesktop.FileManager1;
- programs: xdg-open, kde-open, gio open/launch, gtk-launch, exo-open,
  kioclient, startDetached, system(), popen(), wordexp(), fork(), vfork(),
  clone(), every exec*() (execl/lp/le/v/ve/vp/vpe/veat, fexecve) and
  posix_spawn/posix_spawnp, and QProcess or KProcess anywhere but the one
  runner, matched by exact path: app/src/ProcessRunner.cpp and its header
  (QProcess is part of the runner's declaration).
- a file that is not UTF-8 text, or a symlink, is a problem too (not
  scanned, so not trusted).
Whole-line // comments count too (a commented-out call is still a reason to
look).

This is a tripwire, not a guarantee (review-7 I5): it is lexical, so a
name built from single characters, a C++ alias of QProcess's base class or
a call through a library it doesn't know would pass. Review stays the real
control; this only catches the plain and the usual split forms early.
Stdlib only; reads, never writes (--self-test writes only in its own
temporary folder and removes it).
Usage: check_no_opener.py <folder>... [--synced <synced plasmoid folder>] | --self-test
"""

import hashlib
import re
import sys
import tempfile
from pathlib import Path

BANNED = re.compile(
    r"openUrl|UrlExternally|[\"'`][A-Za-z_]*Externally[\"'`]"
    r"|QDesktopServices|QPlatformServices|platformIntegration|QGuiApplicationPrivate"
    r"|OpenUrlJob|ApplicationLauncherJob|CommandLauncherJob"
    r"|\bQt\s*\[|[=(,:]\s*Qt\s*(?:[;,)\]}]|$)"
    r"|org\.freedesktop\.portal|portal\.Desktop|freedesktop/portal|\bOpenURI\b|[\"'`]OpenFile[\"'`]"
    r"|FileManager1"
    r"|xdg-open|kde-open|gio\s+(?:open|launch)|gtk-launch|exo-open|kioclient|startDetached"
    r"|\b(?:execl|execlp|execle|execv|execve|execvp|execvpe|execveat|fexecve|fork|vfork|clone|clone3"
    r"|posix_spawn|posix_spawnp|popen|wordexp)\s*\("
    r"|(?<!QRandomGenerator::)\bsystem\s*\(")
# The way to LinkOut.js (task 013 F1): the opener's name, the two ChatWebView
# functions that reach it and any assignment to its pending address. Only
# the synced ChatWebView.qml and LinkOut.js (directly in --synced, by exact
# name) may hold them; a caller of acceptExternal() is also the synced
# ChatView.qml (the prompt's Open button).
GATE = re.compile(
    r"\bLinkOut\b|\bopenHttps\s*\(|\bacceptExternal\s*\("
    r"|\bexternalUrl\s*(?:<<|>>|[-+*/|&^%])?=(?!=)"
    # a QML binding (start of a statement or block, with or without "property <type>"),
    # not the "? x.externalUrl : y" of a condition
    r"|(?:^|[{;])\s*(?:(?:readonly\s+|required\s+)?property\s+[\w.<>]+\s+)?externalUrl\s*:(?!:)")
GATE_FILES = {"ChatWebView.qml", "LinkOut.js"}
GATE_ACCEPT_FILES = GATE_FILES | {"ChatView.qml"}
ACCEPT = re.compile(r"\bacceptExternal\s*\(")
PROCESS = re.compile(r"\b[QK]Process\b")
# The one place that starts a process (the helper, task 008 contract), by
# exact path: this script is app/tests/check_no_opener.py.
APP_SRC = Path(__file__).resolve().parent.parent / "src"
RUNNER = {APP_SRC / "ProcessRunner.cpp", APP_SRC / "ProcessRunner.h"}


# The one opener allowed (task 013 decision Q1 = B): the synced
# plasmoid's LinkOut.js, by exact place (directly in --synced) and exact
# bytes. Pinned here on its own, apart from sync_plasmoid.py's
# PLASMA_LINK_OUT (tests/test_app_sync.py checks the two agree).
LINK_OUT = "LinkOut.js"
LINK_OUT_SHA256 = "6d788c93ae5e207d7a8bcc466ff7b57fd6a8290f602ba011d4a916374d2f8d11"


def exempt(path):
    return path.resolve() in RUNNER


def reviewed_link_out(data):
    return hashlib.sha256(data).hexdigest() == LINK_OUT_SHA256


def problems(folder, synced=False):
    """Problems under folder; synced: it is the synced plasmoid, where the one LinkOut.js may open a URL."""
    found = []
    link_out = (folder / LINK_OUT).resolve() if synced else None

    def gate_allowed(path, text):
        """Whether the GATE words are fine in this file (exact name, directly in the synced folder)."""
        if not synced or path.parent.resolve() != folder.resolve():
            return False
        if path.name in GATE_FILES:
            return True
        return path.name in GATE_ACCEPT_FILES and not GATE.search(ACCEPT.sub("", text))

    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            found.append("%s: a symlink (not followed)" % path)
            continue
        if not path.is_file():
            continue
        data = path.read_bytes()
        if link_out is not None and path.resolve() == link_out:
            if reviewed_link_out(data):
                continue
            found.append("%s: not the reviewed LinkOut.js (only its exact bytes may open a URL)" % path)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            found.append("%s: not UTF-8 text (not scanned)" % path)
            continue
        gated = not gate_allowed(path, text)
        for number, line in enumerate(text.splitlines(), 1):
            where = "%s:%d" % (path, number)
            match = GATE.search(line) if gated else None
            if match:
                found.append(where + ": " + match.group(0).strip() + " (only the synced ChatWebView.qml and LinkOut.js)")
            match = BANNED.search(line)
            if match:
                found.append(where + ": " + match.group(0).strip())
            if PROCESS.search(line) and not exempt(path):
                found.append(where + ": QProcess/KProcess outside ProcessRunner")
    return found


def scan(folders, synced=None):
    """Problems in folders and (with the LinkOut.js exception) in the synced folder."""
    found = []
    targets = [(folder, False) for folder in folders]
    if synced is not None:
        targets.append((synced, True))
    for folder, is_synced in targets:
        path = Path(folder)
        if path.is_symlink() or not path.is_dir():
            found.append(folder + ": not a folder")
            continue
        found += problems(path, is_synced)
    return found


# --self-test: each row is a file that must be found; CLEAN must not be.
ROWS = [
    ("mjs module", "c.mjs", "export function go(u) { Qt.openUrlExternally(u) }\n"),
    ("cjs script", "c.cjs", "Qt.openUrlExternally(u)\n"),
    ("unknown suffix", "c.weird", "Qt.openUrlExternally(u)\n"),
    ("split name, openUrl piece", "a.qml", "Item { function go(u) { Qt[\"openUrl\" + \"Externally\"](u) } }\n"),
    ("split name, UrlExternally piece", "a.js", "var f = \"open\" + \"UrlExternally\"\n"),
    ("split name, quoted Externally piece", "a.js", "var f = \"openU\"; f += 'rlExternally'\n"),
    ("split name, openUrl and two more pieces", "a.js", "var f = \"openUrl\" + \"Ext\" + \"ernally\"\n"),
    ("openUrl alone", "s.cpp", "services->openUrl(u);\n"),
    ("bracket access on Qt", "a.js", "var f = Qt [name]\n"),
    ("Qt aliased", "a.js", "var q = Qt;\n"),
    ("Qt handed to a call", "a.js", "run(Qt, name)\n"),
    ("QPlatformServices", "s.cpp", "QGuiApplicationPrivate::platformIntegration()->services()->openUrl(u);\n"),
    ("QPlatformServices by name", "s.h", "#include <qpa/qplatformservices.h>\nQPlatformServices *s;\n"),
    ("QDesktopServices", "e.cpp", "QDesktopServices::openUrl(u);\n"),
    ("KIO OpenUrlJob", "k.cpp", "auto *job = new KIO::OpenUrlJob(u);\n"),
    ("fork", "f.cpp", "pid_t pid = fork();\n"),
    ("vfork", "f.cpp", "pid_t pid = ::vfork ();\n"),
    ("clone", "f.cpp", "clone(fn, stack, flags, arg);\n"),
    ("execvpe", "x.cpp", "execvpe(\"prog\", argv, envp);\n"),
    ("execle", "x.cpp", "execle(\"/bin/prog\", \"prog\", nullptr, envp);\n"),
    ("execveat", "x.cpp", "execveat(fd, \"\", argv, envp, AT_EMPTY_PATH);\n"),
    ("fexecve", "x.cpp", "fexecve(fd, argv, envp);\n"),
    ("execv", "x.cc", "execv(path, argv);\n"),
    ("posix_spawn", "x.cxx", "posix_spawn(&pid, path, nullptr, nullptr, argv, envp);\n"),
    ("posix_spawnp", "x.hpp", "posix_spawnp(&pid, \"prog\", nullptr, nullptr, argv, envp);\n"),
    ("popen", "x.cpp", "FILE *f = popen(\"prog\", \"r\");\n"),
    ("system", "x.cpp", "std::system(\"prog\");\n"),
    ("wordexp", "x.cpp", "wordexp(\"$(prog)\", &w, 0);\n"),
    ("startDetached", "x.cpp", "Runner::startDetached(\"prog\");\n"),
    ("xdg-open", "x.js", "var p = \"xdg-open\"\n"),
    ("kde-open", "x.js", "var p = \"kde-open5\"\n"),
    ("gio open", "x.sh", "gio open \"$1\"\n"),
    ("gtk-launch", "x.sh", "gtk-launch app\n"),
    ("OpenURI portal", "p.cpp",
     "QDBusMessage::createMethodCall(\"org.freedesktop.portal.Desktop\", \"/org/freedesktop/portal/desktop\",\n"
     "    \"org.freedesktop.portal.OpenURI\", \"OpenURI\");\n"),
    ("OpenURI portal, split service", "p.cpp", "QString s = QStringLiteral(\"org.freedesktop.\") + \"portal.Desktop\";\n"),
    ("OpenURI method alone", "p.cpp", "call(\"OpenURI\");\n"),
    ("portal OpenFile", "p.cpp", "call(QStringLiteral(\"OpenFile\"));\n"),
    ("FileManager1", "p.cpp", "QString s = \"org.freedesktop.FileManager1\";\n"),
    ("QProcess", "q.cpp", "QProcess p;\n"),
    ("KProcess", "q.cpp", "KProcess p;\n"),
    ("QProcess in a ProcessRunner.cpp elsewhere", "sub/ProcessRunner.cpp", "QProcess p;\n"),
    ("QProcess in a src/ProcessRunner.cpp elsewhere", "src/ProcessRunner.cpp", "QProcess p;\n"),
    ("LinkOut import", "e.qml", "import \"qrc:/qt/qml/Hearthwire/Plasmoid/LinkOut.js\" as Out\n"),
    ("LinkOut.open call", "e.js", "LinkOut.open(url)\n"),
    ("openHttps call", "e.qml", "Item { function f(w) { w.openHttps(\"https://y.example/\") } }\n"),
    ("acceptExternal call", "e.qml", "Item { function f(w) { w.acceptExternal() } }\n"),
    ("externalUrl assigned", "e.qml", "Item { function f(w) { w.externalUrl = \"https://x.example/\" } }\n"),
    ("externalUrl bound", "e.qml", "Item { externalUrl: \"https://x.example/\" }\n"),
    ("externalUrl bound after a brace", "e.qml", "Item { id: x; externalUrl: \"https://x.example/\" }\n"),
    ("property externalUrl", "e.qml", "Item { property string externalUrl: \"\" }\n"),
    ("externalUrl +=", "e.js", "w.externalUrl += \"x\"\n"),
    ("auditor Evil.qml", "Evil.qml",
     "import QtQuick\nimport \"qrc:/qt/qml/Hearthwire/Plasmoid/LinkOut.js\" as Out\n"
     "Item { Component.onCompleted: Out.open(\"http://127.0.0.1:9/x\") ; function f(w) { "
     "w.externalUrl = \"https://x.example/\"; w.acceptExternal(); w.openHttps(\"https://y.example/\") } }\n"),
    ("commented-out call", "c.qml", "// Qt.openUrlExternally(u)\n"),
    ("in a .in template", "AboutInfo.h.in", "#define X QDesktopServices\n"),
]
CLEAN = {
    "ok.qml": "Item {\n    readonly property bool canOpenExternally: false\n"
              "    function openExternally() { Qt.callLater(go) }\n    property var t: Qt.rgba(0, 0, 0, 1)\n}\n",
    "ok.js": ".pragma library\nvar isApp = false\nfunction f(a) { return a.qtName }\n",
    "ok.cpp": "#include <QRandomGenerator>\nquint32 r = QRandomGenerator::system()->generate();\n"
              "Qt::AlignmentFlag a = Qt::AlignLeft;\nauto c = Qt::DirectConnection;\n"
              "void forkLater();\nint execCount = 0;\n",
    "ok.mjs": "export const qt = 1\n",
    "ok3.qml": "Item { readonly property string url: web ? web.externalUrl : \"\"\n    visible: web.externalUrl !== \"\" }\n",
    "ok2.qml": "Item { property bool x: chatView.web.externalUrl !== \"\"; property var o: externalUrlText }\n",
    "ok.xml": "<entry name=\"openOnStart\" type=\"Bool\"/>\n",
}


# The plasmoid's own LinkOut.js (the reviewed bytes, when it is unchanged).
PLASMOID_LINK_OUT = APP_SRC.parent.parent / "plasmoid" / "contents" / "ui" / LINK_OUT
LINK_OUT_ROWS = 20


def link_out_rows(base):
    """The LinkOut.js exception both ways: allowed only as the exact bytes, directly in --synced."""
    failures = []
    reviewed = PLASMOID_LINK_OUT.read_bytes() if PLASMOID_LINK_OUT.is_file() else b""
    if not reviewed_link_out(reviewed):
        return ["the plasmoid's LinkOut.js is not the pinned bytes (LINK_OUT_SHA256)"]

    def folder(name, files):
        path = base / name
        for relative, data in files.items():
            (path / relative).parent.mkdir(parents=True, exist_ok=True)
            (path / relative).write_bytes(data)
        return path

    good = folder("lo-good", {LINK_OUT: reviewed, "Page.qml": b"Item {}\n"})
    if scan([], str(good)) != []:
        failures.append("the reviewed LinkOut.js in --synced is flagged: " + "; ".join(scan([], str(good))))
    if main(["check", "--synced", str(good)]) != 0:
        failures.append("main() --synced exit code for the reviewed LinkOut.js")
    # Each of these must be found.
    caught = [
        ("the reviewed bytes, folder not given as --synced", [str(good)], None),
        ("the reviewed bytes below --synced", [], folder("lo-sub", {"sub/" + LINK_OUT: reviewed})),
        ("the reviewed bytes under another name", [], folder("lo-name", {"Opener.js": reviewed})),
        ("a line added", [], folder("lo-added", {LINK_OUT: reviewed + b"function again(u) { Qt.openUrlExternally(u) }\n"})),
        ("a trailing newline", [], folder("lo-newline", {LINK_OUT: reviewed + b"\n"})),
        ("changed to open nothing", [], folder("lo-nothing", {LINK_OUT: reviewed.replace(b"Qt.openUrlExternally(url)", b"")})),
        ("another synced file opens a URL", [], folder("lo-other", {LINK_OUT: reviewed,
                                                                    "ChatWebView.qml": b"Item { function f(u) { Qt.openUrlExternally(u) } }\n"})),
    ]
    for name, folders, synced in caught:
        if not scan(folders, None if synced is None else str(synced)):
            failures.append("not caught: LinkOut.js, " + name)
    other = scan([], str(base / "lo-other"))
    if len(other) != 1 or "ChatWebView.qml:1" not in other[0]:
        failures.append("LinkOut.js exception reaches another file: " + "; ".join(other))
    # The gate words (LinkOut, openHttps, acceptExternal, externalUrl =): fine in
    # the synced ChatWebView.qml and LinkOut.js only, directly in --synced.
    words = b'import "LinkOut.js" as LinkOut\nItem { property string externalUrl: ""; function openHttps(u) { LinkOut.open(u) }\n function acceptExternal() { externalUrl = "" } }\n'
    gate_ok = folder("gate-ok", {LINK_OUT: reviewed, "ChatWebView.qml": words,
                                 "ChatView.qml": b"Item { onClicked: chatView.web.acceptExternal() }\n"})
    if scan([], str(gate_ok)):
        failures.append("the gate words in the synced ChatWebView.qml/ChatView.qml are flagged: " + "; ".join(scan([], str(gate_ok))))
    gate_caught = [
        ("ChatWebView.qml, folder not given as --synced", [str(gate_ok)], None),
        ("ChatWebView.qml below --synced", [], folder("gate-sub", {LINK_OUT: reviewed, "sub/ChatWebView.qml": words})),
        ("another synced file", [], folder("gate-other", {LINK_OUT: reviewed, "Evil.qml": words})),
        ("ChatWebView.qml under a lower-case name", [], folder("gate-case", {LINK_OUT: reviewed, "chatwebview.qml": words})),
        ("ChatView.qml opens through openHttps", [], folder("gate-cv1", {LINK_OUT: reviewed,
                                                                         "ChatView.qml": b"Item { function f(w) { w.openHttps(u) } }\n"})),
        ("ChatView.qml assigns externalUrl", [], folder("gate-cv2", {LINK_OUT: reviewed,
                                                                     "ChatView.qml": b"Item { function f(w) { w.externalUrl = u; w.acceptExternal() } }\n"})),
        ("ChatView.qml imports LinkOut", [], folder("gate-cv3", {LINK_OUT: reviewed,
                                                                 "ChatView.qml": b'import "LinkOut.js" as Out\n'})),
        ("acceptExternal in a synced Other.qml", [], folder("gate-cv4", {LINK_OUT: reviewed,
                                                                         "Other.qml": b"Item { onClicked: w.acceptExternal() }\n"})),
    ]
    for name, folders, synced in gate_caught:
        if not scan(folders, None if synced is None else str(synced)):
            failures.append("not caught: gate words, " + name)
    link = base / "lo-link"
    link.mkdir()
    (link / LINK_OUT).symlink_to(good / LINK_OUT)
    if not scan([], str(link)):
        failures.append("not caught: LinkOut.js, a symlink to the reviewed bytes")
    return failures


def self_test():
    failures = []
    with tempfile.TemporaryDirectory(prefix="hw-no-opener-") as scratch:
        base = Path(scratch)
        for index, (name, file, text) in enumerate(ROWS):
            folder = base / ("row%02d" % index)
            target = folder / file
            target.parent.mkdir(parents=True)
            target.write_text(text, encoding="utf-8")
            if not scan([str(folder)]):
                failures.append("not caught: " + name)
        # Not text, and a symlink: neither is scanned, both are problems.
        binary = base / "binary"
        binary.mkdir()
        (binary / "x.bin").write_bytes(b"\xff\xfe\x00openUrl")
        if not scan([str(binary)]):
            failures.append("not caught: a file that isn't UTF-8")
        link = base / "link"
        link.mkdir()
        (link / "l.qml").symlink_to(base / "clean")
        if not scan([str(link)]):
            failures.append("not caught: a symlink")
        if scan([str(base / "missing")]) != [str(base / "missing") + ": not a folder"]:
            failures.append("not caught: a missing folder")
        # The control: nothing found, and main() agrees on both sides.
        clean = base / "clean"
        clean.mkdir()
        for file, text in CLEAN.items():
            (clean / file).write_text(text, encoding="utf-8")
        found = scan([str(clean)])
        if found:
            failures.append("clean control flagged: " + "; ".join(found))
        if main(["check", str(clean)]) != 0 or main(["check", str(base / "row00")]) != 1:
            failures.append("main() exit codes")
        # The exemption is the real runner's path only.
        if not exempt(APP_SRC / "ProcessRunner.cpp") or exempt(clean / "ProcessRunner.cpp"):
            failures.append("ProcessRunner exemption is not path-exact")
        failures += link_out_rows(base)
    for line in failures:
        print(line)
    print("self-test: %d row(s), %d failure(s)" % (len(ROWS) + 5 + LINK_OUT_ROWS, len(failures)))
    return 1 if failures else 0


def main(argv):
    if len(argv) == 2 and argv[1] == "--self-test":
        return self_test()
    folders = list(argv[1:])
    synced = None
    if "--synced" in folders:
        index = folders.index("--synced")
        if index + 1 >= len(folders) or folders.count("--synced") != 1:
            print(__doc__.splitlines()[-1], file=sys.stderr)
            return 2
        synced = folders[index + 1]
        del folders[index:index + 2]
    if not folders and synced is None:
        print(__doc__.splitlines()[-1], file=sys.stderr)
        return 2
    found = scan(folders, synced)
    for line in found:
        print(line)
    print("%d problem(s)" % len(found))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
