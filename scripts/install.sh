#!/bin/sh
set -eu

script_directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_directory=$(CDPATH= cd -- "$script_directory/.." && pwd)
restart_plasma=false
uninstall_web_data=false

# One option at most: --uninstall-web-data only deletes data, it never installs.
case "$#:${1:-}" in
    0:) ;;
    1:--restart-plasma) restart_plasma=true ;;
    1:--uninstall-web-data) uninstall_web_data=true ;;
    *)
        echo "Usage: $0 [--restart-plasma | --uninstall-web-data]" >&2
        exit 2
        ;;
esac

# Delete the Chat tab's encrypted folder, which holds every saved chat sign-in
# (there is no unencrypted copy). The helper from this checkout does the work
# (the installed one may be older or gone): it refuses symlinks, never follows
# links, refuses while the encrypted folder is mounted, and replies with
# category names only. It also deletes the folder's KDE Wallet unlock slot and,
# only when that slot was there and the wallet holds it, the key in the wallet
# (which may show KWallet's own password prompt if the wallet is locked).
if [ "$uninstall_web_data" = true ]; then
    if ! command -v python3 >/dev/null 2>&1; then
        echo "Required command not found: python3" >&2
        exit 1
    fi
    # -P (Python 3.11+, which Hearthwire requires) keeps the working folder off
    # sys.path, so a stray json.py there is never imported; PYTHONPATH points
    # at this checkout instead.
    if ! reply=$(PYTHONPATH="$project_directory/src" PYTHONDONTWRITEBYTECODE=1 python3 -P -m hearthwire --web-data purge </dev/null); then
        echo "Could not run the Hearthwire helper. Nothing was deleted." >&2
        exit 1
    fi
    # The opt-in usage history goes too, once the sign-in data is gone. The
    # helper refuses symlinks and replies {"ok":true} also when there is none.
    clear_usage_history() {
        if ! history_reply=$(PYTHONPATH="$project_directory/src" PYTHONDONTWRITEBYTECODE=1 python3 -P -m hearthwire --usage-history clear </dev/null) \
            || [ "$history_reply" != '{"ok":true}' ]; then
            echo "Deleted the Hearthwire chat sign-in data, but could not delete the usage history (the folder hearthwire/usage-history in ${XDG_DATA_HOME:-$HOME/.local/share}). Delete it by hand." >&2
            exit 1
        fi
    }
    # The usage alert events file and the app and settings icons go too, but
    # only once the data is gone. rm unlinks a symlink, never its target.
    remove_installed_files() {
        rm -f -- "${XDG_DATA_HOME:-$HOME/.local/share}/knotifications6/hearthwire.notifyrc"
        uninstall_icons="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
        rm -f -- "$uninstall_icons/hearthwire.svg" \
            "$uninstall_icons/hearthwire-settings-general.svg" \
            "$uninstall_icons/hearthwire-settings-ai.svg" \
            "$uninstall_icons/hearthwire-settings-chat.svg"
    }
    case "$reply" in
        '{"ok":true,"removed":[]}')
            clear_usage_history
            remove_installed_files
            echo "No Hearthwire chat sign-in data found."
            ;;
        '{"ok":true,"removed":["'*'"]}')
            # Categories, in this order: vault, vault-keys, wallet-entry.
            clear_usage_history
            remove_installed_files
            case "$reply" in *'"vault"'*) echo "Deleted: encrypted chat folder (saved chat sign-ins)." ;; esac
            case "$reply" in *'"vault-keys"'*) echo "Deleted: KDE Wallet unlock slot of the encrypted chat folder." ;; esac
            case "$reply" in *'"wallet-entry"'*) echo "Deleted: the encrypted chat folder's key in KDE Wallet." ;; esac
            ;;
        '{"ok":false,"error":"wallet-failed"}')
            echo "Deleted the Hearthwire chat files, but could not remove the encrypted chat folder's key from KDE Wallet (folder Hearthwire, entry encrypted-chat-folder). Remove it in KWalletManager." >&2
            exit 1
            ;;
        '{"ok":false,"error":"not-locked"}')
            echo "Lock the encrypted folder in Hearthwire first, then run this again. Nothing was deleted." >&2
            exit 1
            ;;
        '{"ok":false,"error":"busy"}')
            echo "Hearthwire is using the encrypted folder right now. Try again in a moment. Nothing was deleted." >&2
            exit 1
            ;;
        '{"ok":false,"error":"symlink"}')
            echo "A Hearthwire data folder is a symbolic link; refusing to delete through it. Nothing was deleted." >&2
            exit 1
            ;;
        '{"ok":false,"error":"not-directory"}'|'{"ok":false,"error":"not-owned"}')
            echo "A Hearthwire data folder is not a folder you own; refusing to delete it. Nothing was deleted." >&2
            exit 1
            ;;
        *)
            echo "Could not delete Hearthwire chat sign-in data. Some of it may remain." >&2
            exit 1
            ;;
    esac
    exit 0
fi

for executable in python3 kpackagetool6; do
    if ! command -v "$executable" >/dev/null 2>&1; then
        echo "Required command not found: $executable" >&2
        exit 1
    fi
done

# Required: Python 3.11+ with pip (the helper is stdlib only, pip installs it).
# Every python3 call runs with -P, so the working folder is never on sys.path:
# a pip.py or json.py where the script is run from is never imported. (An
# older Python rejects -P, which fails the version check as it should.)
if ! python3 -P -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "Hearthwire needs Python 3.11 or newer." >&2
    exit 1
fi
if ! python3 -P -m pip --version >/dev/null 2>&1; then
    echo "Required Python module not found: pip (Arch: sudo pacman -S --needed python-pip)" >&2
    exit 1
fi

# Offer to install missing Arch packages, only when run in a terminal. pacman
# itself asks for the password through sudo; nothing is installed without a "y".
can_offer_install() {
    [ -t 0 ] && [ -t 1 ] && command -v pacman >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1
}
offer_install() {
    question=$1
    shift
    can_offer_install || return 1
    printf '%s [y/N] ' "$question"
    read -r answer || return 1
    case "$answer" in
        y|Y|yes|Yes|YES) sudo pacman -S --needed -- "$@" ;;
        *) return 1 ;;
    esac
}

# QML modules the widget imports. Plasma, Kirigami and Qt Quick are required;
# the Chat tab needs Qt WebEngine (without it the widget shows a hint instead).
qml_directory=$(qtpaths6 --query QT_INSTALL_QML 2>/dev/null || true)
[ -n "$qml_directory" ] || qml_directory=/usr/lib/qt6/qml
missing_required_packages() {
    missing=""
    for entry in \
        "QtQuick/Layouts:qt6-declarative" \
        "QtQuick/Dialogs:qt6-declarative" \
        "QtCore:qt6-declarative" \
        "org/kde/kirigami:kirigami" \
        "org/kde/kcmutils:kcmutils" \
        "org/kde/plasma/plasma5support:plasma5support" \
        "org/kde/plasma/components:libplasma" \
        "org/kde/plasma/extras:libplasma" \
        "org/kde/plasma/plasmoid:libplasma"; do
        if [ ! -d "$qml_directory/${entry%%:*}" ]; then
            missing="$missing ${entry##*:}"
        fi
    done
    [ -n "$missing" ] && printf '%s\n' $missing | sort -u | tr '\n' ' '
    return 0
}
packages=$(missing_required_packages)
if [ -n "$packages" ]; then
    echo "Hearthwire needs these packages: $packages" >&2
    # shellcheck disable=SC2086
    if offer_install "Install them now with sudo pacman?" $packages; then
        packages=$(missing_required_packages)
    fi
    if [ -n "$packages" ]; then
        echo "Required QML modules are missing. Arch: sudo pacman -S --needed $packages" >&2
        exit 1
    fi
fi

# Optional features: offer each one, install Hearthwire either way.
if [ ! -d "$qml_directory/QtWebEngine" ]; then
    echo "The Chat tab (AI chat web sites) needs Qt WebEngine (package qt6-webengine)."
    offer_install "Install qt6-webengine now with sudo pacman?" qt6-webengine || true
fi
missing_vault_packages() {
    missing=""
    command -v gocryptfs >/dev/null 2>&1 || missing="$missing gocryptfs"
    command -v kdialog >/dev/null 2>&1 || missing="$missing kdialog"
    command -v fusermount3 >/dev/null 2>&1 || missing="$missing fuse3"
    printf '%s' "${missing# }"
}
packages=$(missing_vault_packages)
if [ -n "$packages" ]; then
    echo "\"Stay signed in\" (encrypted chat sign-ins) needs: $packages"
    # shellcheck disable=SC2086
    offer_install "Install them now with sudo pacman?" $packages || true
fi

optional_notes=""
if [ ! -d "$qml_directory/QtWebEngine" ]; then
    optional_notes="${optional_notes}  Chat tab (web sites): sudo pacman -S --needed qt6-webengine\n"
fi
packages=$(missing_vault_packages)
if [ -n "$packages" ]; then
    optional_notes="${optional_notes}  Stay signed in (encrypted folder): sudo pacman -S --needed $packages\n"
fi
if ! command -v ollama >/dev/null 2>&1; then
    optional_notes="${optional_notes}  Ollama chat: install Ollama (Arch: ollama, or ollama-cuda / ollama-rocm for GPUs), run sudo systemctl enable --now ollama, then ollama pull llama3\n"
fi

build_directory="$project_directory/build"
if [ -d "$build_directory" ]; then
    rm -rf -- "$build_directory"
fi

# Migrate from AI Usage: remove the old helper first, so the old and new
# helpers never refresh the same OAuth tokens under different lock directories.
migrated=false
if python3 -P -m pip show ai-usage-kde >/dev/null 2>&1; then
    if ! python3 -P -m pip uninstall -y --break-system-packages ai-usage-kde; then
        echo "Could not remove the old ai-usage-kde helper (it may be installed system-wide). Remove it manually, then run this script again." >&2
        exit 1
    fi
    migrated=true
fi

if kpackagetool6 -t Plasma/Applet -s com.bgn.aiusage >/dev/null 2>&1; then
    if ! kpackagetool6 -t Plasma/Applet -r com.bgn.aiusage; then
        echo "Could not remove the old com.bgn.aiusage widget (it may be installed system-wide). Remove it manually, then run this script again." >&2
        exit 1
    fi
    migrated=true
fi

# Delete only the files AI Usage is known to have written, never a symlink.
old_cache="${XDG_CACHE_HOME:-${HOME}/.cache}/ai-usage-kde"
if [ -d "$old_cache" ] && [ ! -L "$old_cache" ]; then
    rm -f -- "$old_cache/antigravity-auth.json" "$old_cache/retry-state.json"
    rmdir -- "$old_cache" 2>/dev/null || true
fi
# Old lock directories hold only empty lock files and are cleared at logout.

python3 -P -m pip install \
    --user \
    --upgrade \
    --force-reinstall \
    --break-system-packages \
    "$project_directory"

if kpackagetool6 -t Plasma/Applet -s io.github.flybytechprog.hearthwire >/dev/null 2>&1; then
    kpackagetool6 -t Plasma/Applet -u "$project_directory/plasmoid"
else
    kpackagetool6 -t Plasma/Applet -i "$project_directory/plasmoid"
fi

# Full-colour app icon for the widget list and Settings → About (metadata "Icon": "hearthwire").
icon_directory="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
mkdir -p -- "$icon_directory"
# Unlinked first, like the notifyrc below, so a symlink is replaced, never followed.
rm -f -- "$icon_directory/hearthwire.svg"
cp -- "$project_directory/assets/hearthwire.svg" "$icon_directory/hearthwire.svg"
# Settings page icons (config.qml), single colour: Plasma recolours them to
# the theme like its own icons. Unlinked first too.
for settings_icon in general ai chat; do
    rm -f -- "$icon_directory/hearthwire-settings-$settings_icon.svg"
    cp -- "$project_directory/assets/hearthwire-settings-$settings_icon.svg" \
        "$icon_directory/hearthwire-settings-$settings_icon.svg"
done

# Usage alert events (System Settings → Notifications → Hearthwire). The old
# file is unlinked first, so a symlink in its place is replaced, never followed.
notifyrc_directory="${XDG_DATA_HOME:-$HOME/.local/share}/knotifications6"
mkdir -p -- "$notifyrc_directory"
rm -f -- "$notifyrc_directory/hearthwire.notifyrc"
cp -- "$project_directory/assets/hearthwire.notifyrc" "$notifyrc_directory/hearthwire.notifyrc"
chmod 0644 -- "$notifyrc_directory/hearthwire.notifyrc"

if [ "$restart_plasma" = true ]; then
    if systemctl --user is-active plasma-plasmashell.service >/dev/null 2>&1; then
        systemctl --user restart plasma-plasmashell.service
    else
        kquitapp6 plasmashell >/dev/null 2>&1 || true
        kstart plasmashell >/dev/null 2>&1
    fi
fi

version=$(python3 -P -m hearthwire --version)
echo "Hearthwire ${version} installed."
if [ -n "$optional_notes" ]; then
    echo "Optional features not available yet:"
    printf '%b' "$optional_notes"
fi
if [ "$migrated" = true ]; then
    echo "Remove the old AI Usage widget from your panel if it is still there, then add Hearthwire via Add Widgets…"
fi
