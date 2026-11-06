#!/bin/sh
# Runtime tests of the real ChatWebView.qml in Qt WebEngine against a hostile
# fake chat site.
#
#   tests/webengine/run.sh [UI_DIR]
#
# UI_DIR (default: plasmoid/contents/ui of this checkout) is copied to a
# fresh work folder, so a mutated copy can be tested the same way.
#
# Isolation: everything runs under `env -i` (no session bus, display or
# runtime dir of the desktop) inside `unshare -r -n -m`: an own user, network
# and mount namespace with only loopback, a private /etc/hosts that maps the
# test names to 127.0.0.1 / ::1, and private resolv.conf and nsswitch.conf,
# so no name lookup or request leaves the machine. The certificate is made
# here and lives only in the work folder.
#
# Exit 0 with "SKIP: ..." when a needed tool or user namespaces are missing;
# exit 1 when a test fails.
set -u

if [ "${1:-}" = "--inner" ]; then
    WORK=$2
    RUNNER=$3
    TREE=$WORK/tree
    HERE=$TREE/tests/webengine
    ip link set lo up || exit 1
    mkdir -p "$WORK/etc" "$WORK/home" "$WORK/run"
    chmod 700 "$WORK/run"
    cat > "$WORK/etc/hosts" <<'HOSTS'
127.0.0.1 localhost claude.ai localhost.localdomain app.localhost app.localhost.localdomain victimhost
::1 ip6-localhost ip6-loopback
HOSTS
    echo "nameserver 127.0.0.1" > "$WORK/etc/resolv.conf"
    printf 'passwd: files\ngroup: files\nhosts: files\n' > "$WORK/etc/nsswitch.conf"
    # A container without network may have no resolv.conf or nsswitch.conf
    # (nothing to replace then); /etc/hosts is always needed.
    for name in hosts resolv.conf nsswitch.conf; do
        [ -e "/etc/$name" ] || { [ "$name" = hosts ] && { echo "FAIL: no /etc/hosts"; exit 1; }; continue; }
        mount --bind "$WORK/etc/$name" "/etc/$name" || { echo "FAIL: cannot replace /etc/$name"; exit 1; }
    done
    openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 2 \
        -subj "/CN=claude.ai" -keyout "$WORK/key.pem" -out "$WORK/cert.pem" \
        -addext "subjectAltName=DNS:claude.ai,DNS:localhost,DNS:victimhost,IP:127.0.0.1" \
        >/dev/null 2>&1 || { echo "FAIL: openssl could not make a certificate"; exit 1; }
    : > "$WORK/hits.log"
    status=0
    server=""

    start_server() {
        rm -f "$WORK/ready"
        python3 -I "$HERE/server.py" "$WORK" &
        server=$!
        tries=0
        while [ ! -f "$WORK/ready" ]; do
            tries=$((tries + 1))
            if [ $tries -gt 100 ] || ! kill -0 "$server" 2>/dev/null; then
                echo "FAIL: the fake servers did not start"
                exit 1
            fi
            sleep 0.1
        done
    }

    stop_server() {
        kill "$server" 2>/dev/null
        wait "$server" 2>/dev/null
    }

    # phase NAME TEST_FILE CHROMIUM_FLAGS
    phase() {
        start_server
        rm -rf "$WORK/home" && mkdir -p "$WORK/home"
        env -i HOME="$WORK/home" PATH=/usr/bin:/bin LANG=C.UTF-8 \
            XDG_RUNTIME_DIR="$WORK/run" XDG_CONFIG_HOME="$WORK/home/.config" \
            XDG_DATA_HOME="$WORK/home/.local/share" XDG_CACHE_HOME="$WORK/home/.cache" \
            QT_QPA_PLATFORM=offscreen QTWEBENGINE_DISABLE_SANDBOX=1 \
            QTWEBENGINE_CHROMIUM_FLAGS="$3" \
            timeout 240 "$RUNNER" -input "$HERE/$2" > "$WORK/$1.out" 2>&1
        code=$?
        stop_server
        grep -E "^(PASS|FAIL!|SKIP|XFAIL|XPASS) |^   Loc:|^   Actual|^   Expected|^Totals" "$WORK/$1.out"
        if [ $code -ne 0 ] || ! grep -q "^Totals: [1-9][0-9]* passed, 0 failed" "$WORK/$1.out"; then
            echo "FAIL: $1 (qmltestrunner exit $code; full output in $WORK/$1.out)"
            status=1
        fi
        # Nothing of a private profile may stay on disk.
        stored=$(find "$WORK/home" \( -name QtWebEngine -o -name Cookies -o -name "Local Storage" \
            -o -name IndexedDB \) 2>/dev/null)
        if [ -n "$stored" ]; then
            echo "FAIL: $1 left site data on disk: $stored"
            status=1
        fi
    }

    # The hostile page: the certificate is accepted by Chromium itself here,
    # so the page loads and its requests reach ChatWebView's handlers.
    phase hostile tst_hostile_page.qml "--ignore-certificate-errors"
    # The same site without that flag: ChatWebView must refuse it.
    phase certificate tst_untrusted_certificate.qml ""
    if grep -q "^victim " "$WORK/hits.log"; then
        echo "FAIL: the service on this computer was reached:"
        grep "^victim " "$WORK/hits.log"
        status=1
    fi
    [ $status -eq 0 ] && echo "webengine runtime tests: PASS"
    exit $status
fi

skip() {
    echo "SKIP: $*"
    exit 0
}

HERE=$(cd "$(dirname "$0")" && pwd)
UI=${1:-$HERE/../../plasmoid/contents/ui}
[ -f "$UI/ChatWebView.qml" ] || { echo "FAIL: no ChatWebView.qml in $UI"; exit 1; }
for tool in unshare openssl python3 ip mount timeout; do
    command -v "$tool" >/dev/null 2>&1 || skip "$tool is not available"
done
RUNNER=/usr/lib/qt6/bin/qmltestrunner
[ -x "$RUNNER" ] || RUNNER=$(command -v qmltestrunner 2>/dev/null) || skip "qmltestrunner is not available"
unshare -r -n -m true 2>/dev/null || skip "unshare -r -n -m is not permitted here"

WORK=$(mktemp -d "${TMPDIR:-/tmp}/hearthwire-webengine.XXXXXX") || exit 1
mkdir -p "$WORK/tree/plasmoid/contents" "$WORK/tree/tests"
cp -r "$UI" "$WORK/tree/plasmoid/contents/ui"
cp -r "$HERE" "$WORK/tree/tests/webengine"
env -i HOME="$WORK/home" PATH=/usr/bin:/bin LANG=C.UTF-8 \
    unshare -r -n -m /bin/sh "$WORK/tree/tests/webengine/run.sh" --inner "$WORK" "$RUNNER"
status=$?
[ "${HEARTHWIRE_WEBENGINE_KEEP:-}" = "1" ] && echo "work folder: $WORK" || rm -rf "$WORK"
exit $status
