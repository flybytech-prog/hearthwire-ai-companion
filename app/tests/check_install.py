"""Checks the app's install layout and .desktop file (task 012 R3.3).

  check_install.py --stage DIR      DIR (a DESTDIR staging of
                                    `cmake --install --prefix /usr`) holds
                                    exactly usr/bin/hearthwire-hyprland (0755)
                                    and usr/share/applications/
                                    hearthwire-hyprland.desktop (0644)
  check_install.py --desktop FILE   the .desktop file's keys (the fallback
                                    when desktop-file-validate is missing)
  check_install.py --readelf READELF --runpath FILE...
                                    no RPATH/RUNPATH entry of the ELF files
                                    is empty, relative or uses $ORIGIN (or
                                    any other $ token); --stage with
                                    --readelf checks the staged binary too
                                    (review-6-security LOW-1)

Run with python3 -I; stdlib only. Exit 0 = good, 1 = a problem (printed).
"""

import argparse
import os
import re
import stat
import subprocess
import sys

APP_ID = "hearthwire-hyprland"
EXPECTED_FILES = {
    "usr/bin/" + APP_ID: 0o755,
    "usr/share/applications/" + APP_ID + ".desktop": 0o644,
}
EXPECTED_KEYS = {
    "Type": "Application",
    "Name": "Hearthwire",
    "GenericName": "AI usage and chat",
    "Comment": "AI subscription usage and chat sites",
    "Exec": APP_ID,
    "Icon": "hearthwire",
    "Terminal": "false",
    "Categories": "Utility;",
    "StartupNotify": "true",
    "StartupWMClass": APP_ID,
    "SingleMainWindow": "true",
}


RUNPATH_LINE = re.compile(r"\((RPATH|RUNPATH)\)\s+Library (?:rpath|runpath): \[(.*)\]$")


def runpath_problems(entries, kind, name):
    """Problems of one RPATH/RUNPATH value, split on ':'."""
    problems = []
    parts = entries.split(":")
    empty = parts.count("")
    if empty:
        problems.append("%s: %s has %d empty entr%s (the current folder)" % (name, kind, empty, "y" if empty == 1 else "ies"))
    for entry in parts:
        if entry == "":
            continue
        if "$" in entry:
            problems.append("%s: %s entry %r uses a $ token" % (name, kind, entry))
        elif not entry.startswith("/"):
            problems.append("%s: %s entry %r is relative" % (name, kind, entry))
    return problems


def check_runpath(readelf, path):
    name = os.path.basename(path)
    if not os.path.isabs(readelf):
        return ["readelf must be an absolute path"]
    try:
        result = subprocess.run(
            [readelf, "-d", "-W", path],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return ["%s: readelf did not run (%s)" % (name, type(error).__name__)]
    output = result.stdout.decode("utf-8", "replace")
    if result.returncode != 0 or "Dynamic section at offset" not in output:
        return ["%s: readelf found no dynamic section (exit %d)" % (name, result.returncode)]
    problems = []
    for line in output.splitlines():
        match = RUNPATH_LINE.search(line.strip())
        if match:
            problems += runpath_problems(match.group(2), match.group(1), name)
        elif "(RPATH)" in line or "(RUNPATH)" in line:
            problems.append("%s: unreadable %s line" % (name, "RPATH/RUNPATH"))
    return problems


def check_stage(root):
    problems = []
    found = {}
    for folder, dirs, files in os.walk(root):
        for name in files + [d for d in dirs if os.path.islink(os.path.join(folder, d))]:
            path = os.path.join(folder, name)
            info = os.lstat(path)
            found[os.path.relpath(path, root)] = info
    if sorted(found) != sorted(EXPECTED_FILES):
        problems.append("installed files: %s, expected %s" % (sorted(found), sorted(EXPECTED_FILES)))
    for rel, mode in EXPECTED_FILES.items():
        info = found.get(rel)
        if info is None:
            continue
        if not stat.S_ISREG(info.st_mode):
            problems.append("%s is not a regular file" % rel)
        if stat.S_IMODE(info.st_mode) != mode:
            problems.append("%s has mode %o, expected %o" % (rel, stat.S_IMODE(info.st_mode), mode))
    desktop = os.path.join(root, "usr/share/applications/" + APP_ID + ".desktop")
    if os.path.isfile(desktop):
        problems += check_desktop(desktop)
    return problems


def check_desktop(path):
    problems = []
    if os.path.basename(path) != APP_ID + ".desktop":
        problems.append("the file name must be %s.desktop (the app id and desktop-entry hint)" % APP_ID)
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    if not lines or lines[0] != "[Desktop Entry]":
        problems.append("the first line must be [Desktop Entry]")
    keys = {}
    for line in lines[1:]:
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            problems.append("only one group is allowed (no Actions): %s" % line)
            continue
        key, sep, value = line.partition("=")
        if not sep:
            problems.append("not a key=value line: %r" % line)
            continue
        if key in keys:
            problems.append("key twice: %s" % key)
        keys[key] = value
    if keys != EXPECTED_KEYS:
        problems.append("keys %r, expected %r" % (keys, EXPECTED_KEYS))
    return problems


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--stage")
    group.add_argument("--desktop")
    group.add_argument("--runpath", nargs="+")
    parser.add_argument("--readelf")
    args = parser.parse_args()
    if args.runpath and not args.readelf:
        parser.error("--runpath needs --readelf")
    if args.stage:
        problems = check_stage(args.stage)
        if args.readelf:
            problems += check_runpath(args.readelf, os.path.join(args.stage, "usr/bin/" + APP_ID))
    elif args.runpath:
        problems = []
        for path in args.runpath:
            problems += check_runpath(args.readelf, path)
    else:
        problems = check_desktop(args.desktop)
    for problem in problems:
        print("FAIL: " + problem)
    if not problems:
        print("OK")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
