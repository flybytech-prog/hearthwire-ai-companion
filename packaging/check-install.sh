#!/bin/sh
# After a package is installed in a fresh container: check that the plasmoid,
# icons, notification events and the helper landed where the widget expects
# them, and that the QML modules the widget imports are there. The helper runs
# with an empty environment and a throwaway HOME, only with options that use
# no network and read no credentials (--help, --version, --catalog).
#
# Usage: packaging/check-install.sh VERSION
# Optional features (Chat tab, Stay signed in, KDE Wallet unlock) are reported
# as warnings only, since a package only recommends or suggests them.
set -eu

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 VERSION" >&2
    exit 2
fi
version=$1
plugin=io.github.flybytechprog.hearthwire
plasmoid=/usr/share/plasma/plasmoids/$plugin
failures=0

fail() {
    echo "FAIL: $*" >&2
    failures=$((failures + 1))
}
pass() {
    echo "ok: $*"
}
warn() {
    # GitHub Actions shows these as annotations; elsewhere a plain line.
    echo "::warning::$*"
}

for file in metadata.json contents/ui/main.qml contents/config/main.xml contents/images/hearthwire.svg; do
    if [ -f "$plasmoid/$file" ]; then pass "$plasmoid/$file"; else fail "missing $plasmoid/$file"; fi
done
for icon in hearthwire hearthwire-settings-general hearthwire-settings-ai hearthwire-settings-chat; do
    path=/usr/share/icons/hicolor/scalable/apps/$icon.svg
    if [ -f "$path" ]; then pass "$path"; else fail "missing $path"; fi
done
if [ -f /usr/share/knotifications6/hearthwire.notifyrc ]; then
    pass /usr/share/knotifications6/hearthwire.notifyrc
else
    fail "missing /usr/share/knotifications6/hearthwire.notifyrc"
fi
if [ -n "$(find "$plasmoid" ! -perm -0444 -print -quit 2>/dev/null)" ]; then
    fail "a plasmoid file is not readable by everyone"
fi

# The helper, the way the widget starts it (python3 -P -m hearthwire), from an
# empty folder with an empty environment: it must come from the system
# install, not from a checkout or the user site.
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
mkdir -p -- "$scratch/home"
# Standard input stays the caller's: </dev/null unless a step pipes into it.
run_python() {
    (cd "$scratch" && env -i HOME="$scratch/home" PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONNOUSERSITE=1 \
        python3 -P "$@")
}
run_helper() {
    run_python "$@" </dev/null
}
if run_helper -m hearthwire --help >/dev/null; then pass "python3 -P -m hearthwire --help"; else fail "python3 -P -m hearthwire --help"; fi
helper_version=$(run_helper -m hearthwire --version || true)
if [ "$helper_version" = "$version" ]; then
    pass "helper version $helper_version"
else
    fail "helper version is '$helper_version', expected $version"
fi
location=$(run_helper -c 'import hearthwire; print(hearthwire.__file__)' || true)
case "$location" in
    /usr/lib/*) pass "helper module at $location" ;;
    *) fail "helper module at '$location', expected under /usr/lib" ;;
esac
catalog=$(run_helper -m hearthwire --catalog || true)
if printf '%s' "$catalog" | run_python -c 'import json, sys
reply = json.load(sys.stdin)
sys.exit(0 if isinstance(reply, dict) and reply else 1)' 2>/dev/null; then
    pass "hearthwire --catalog prints JSON"
else
    fail "hearthwire --catalog"
fi
entry_version=$(cd "$scratch" && env -i HOME="$scratch/home" PATH=/usr/bin:/bin hearthwire --version </dev/null || true)
if [ "$entry_version" = "$version" ]; then pass "/usr/bin/hearthwire"; else fail "hearthwire command: '$entry_version'"; fi

metadata_version=$(run_helper -c 'import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))["KPlugin"]
print(data["Id"], data["Version"])' "$plasmoid/metadata.json" || true)
if [ "$metadata_version" = "$plugin $version" ]; then
    pass "metadata.json: $metadata_version"
else
    fail "metadata.json says '$metadata_version', expected '$plugin $version'"
fi

# Plasma's own package tool finds the widget among the system-wide ones.
if command -v kpackagetool6 >/dev/null 2>&1; then
    if (cd "$scratch" && env -i HOME="$scratch/home" PATH=/usr/bin:/bin QT_QPA_PLATFORM=offscreen \
        kpackagetool6 --type Plasma/Applet --show "$plugin" >/dev/null 2>&1 </dev/null); then
        pass "kpackagetool6 --show $plugin"
    else
        fail "kpackagetool6 does not find $plugin"
    fi
else
    fail "kpackagetool6 not installed (should come with Plasma)"
fi

# The QML modules the widget imports (the same list as scripts/install.sh).
qml_directory=""
for candidate in /usr/lib/qt6/qml /usr/lib64/qt6/qml /usr/lib/x86_64-linux-gnu/qt6/qml; do
    if [ -d "$candidate/QtQuick" ]; then
        qml_directory=$candidate
        break
    fi
done
if [ -z "$qml_directory" ]; then
    fail "no Qt 6 QML folder found"
else
    for module in QtQuick/Layouts QtQuick/Shapes QtQuick/Dialogs QtQuick/Controls QtQuick/Window QtCore \
        org/kde/kirigami org/kde/kcmutils org/kde/notification org/kde/plasma/plasma5support \
        org/kde/plasma/components org/kde/plasma/extras org/kde/plasma/plasmoid org/kde/plasma/core \
        org/kde/plasma/configuration; do
        if [ -f "$qml_directory/$module/qmldir" ]; then pass "QML $module"; else fail "QML module $module missing"; fi
    done
    if [ -f "$qml_directory/QtWebEngine/qmldir" ]; then
        pass "QML QtWebEngine (Chat tab)"
    else
        warn "Qt WebEngine QML module not installed: the Chat tab shows an install hint"
    fi
fi

# Optional tools: a warning each, never a failure.
for tool in gocryptfs fusermount3 kdialog kwallet-query openssl secret-tool; do
    if command -v "$tool" >/dev/null 2>&1; then pass "optional $tool"; else warn "optional tool not installed: $tool"; fi
done
# The helper looks for qdbus6 first, then qdbus-qt6 (Fedora's name).
if command -v qdbus6 >/dev/null 2>&1; then
    pass "optional qdbus6"
elif command -v qdbus-qt6 >/dev/null 2>&1; then
    pass "optional qdbus6 (as qdbus-qt6)"
else
    warn "optional tool not installed: qdbus6 or qdbus-qt6"
fi

if [ "$failures" -ne 0 ]; then
    echo "$failures check(s) failed." >&2
    exit 1
fi
echo "Hearthwire $version is installed correctly."
