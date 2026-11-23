#!/usr/bin/env python3
"""ctest: nothing in the app's own code or QML can open a URL or start a program.

decision-1 Q2 (task 012 R4): the About page's links are copy-only, and the
app starts only the helper, only through ProcessRunner. This scans every
regular file under the folders given (app/src, app/qml, the synced
plasmoid), whatever its suffix (.mjs, .cc, .in, ... included), for the ways
out:
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
Usage: check_no_opener.py <folder>... | --self-test
"""

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
PROCESS = re.compile(r"\b[QK]Process\b")
# The one place that starts a process (the helper, task 008 contract), by
# exact path: this script is app/tests/check_no_opener.py.
APP_SRC = Path(__file__).resolve().parent.parent / "src"
RUNNER = {APP_SRC / "ProcessRunner.cpp", APP_SRC / "ProcessRunner.h"}


def exempt(path):
    return path.resolve() in RUNNER


def problems(folder):
    found = []
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            found.append("%s: a symlink (not followed)" % path)
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            found.append("%s: not UTF-8 text (not scanned)" % path)
            continue
        for number, line in enumerate(text.splitlines(), 1):
            where = "%s:%d" % (path, number)
            match = BANNED.search(line)
            if match:
                found.append(where + ": " + match.group(0).strip())
            if PROCESS.search(line) and not exempt(path):
                found.append(where + ": QProcess/KProcess outside ProcessRunner")
    return found


def scan(folders):
    found = []
    for folder in folders:
        path = Path(folder)
        if not path.is_dir():
            found.append(folder + ": not a folder")
            continue
        found += problems(path)
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
    "ok.xml": "<entry name=\"openOnStart\" type=\"Bool\"/>\n",
}


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
    for line in failures:
        print(line)
    print("self-test: %d row(s), %d failure(s)" % (len(ROWS) + 5, len(failures)))
    return 1 if failures else 0


def main(argv):
    if len(argv) == 2 and argv[1] == "--self-test":
        return self_test()
    if len(argv) < 2:
        print(__doc__.splitlines()[-1], file=sys.stderr)
        return 2
    found = scan(argv[1:])
    for line in found:
        print(line)
    print("%d problem(s)" % len(found))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
