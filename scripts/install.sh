#!/bin/sh
set -eu

script_directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_directory=$(CDPATH= cd -- "$script_directory/.." && pwd)
restart_plasma=false
uninstall_web_data=false
rollback=false
remove_script_install=false

# --uninstall-web-data only deletes data, it never installs. --rollback-hearthwire
# undoes the one-time migration (see below); --remove-script-install removes
# this script's copy so a package is used. --restart-plasma may follow either.
case "$#:${1:-}:${2:-}" in
    0::) ;;
    1:--restart-plasma:) restart_plasma=true ;;
    1:--uninstall-web-data:) uninstall_web_data=true ;;
    1:--rollback-hearthwire:) rollback=true ;;
    2:--rollback-hearthwire:--restart-plasma) rollback=true; restart_plasma=true ;;
    1:--remove-script-install:) remove_script_install=true ;;
    2:--remove-script-install:--restart-plasma) remove_script_install=true; restart_plasma=true ;;
    *)
        echo "Usage: $0 [--restart-plasma | --uninstall-web-data | --rollback-hearthwire [--restart-plasma] | --remove-script-install [--restart-plasma]]" >&2
        exit 2
        ;;
esac

case "${XDG_CONFIG_HOME:-}" in
    /*) config_home=$XDG_CONFIG_HOME ;;
    *) config_home=$HOME/.config ;;
esac
# Like XDG_CONFIG_HOME above, and as Qt and kpackagetool6 read it: an
# absolute $XDG_DATA_HOME, else ~/.local/share (a relative one would put the
# icons under the working folder).
case "${XDG_DATA_HOME:-}" in
    /*) data_home=$XDG_DATA_HOME ;;
    *) data_home=$HOME/.local/share ;;
esac
icon_directory="$data_home/icons/hicolor/scalable/apps"
notifyrc_directory="$data_home/knotifications6"
# Where kpackagetool6 (without -g) keeps this user's widget. kpackagetool6 -s
# also finds a system package in /usr/share, so whether this user has a copy
# is decided by this folder alone (install: -u or -i; rollback and
# --remove-script-install: remove only this copy).
user_data_home=$data_home
user_plasmoid="$user_data_home/plasma/plasmoids/io.github.flybytechprog.hearthwire"

# The helper from this checkout, never an installed one (it may be older or
# gone). -P (Python 3.11+, which Hearthwire requires) keeps the working folder
# off sys.path, so a stray json.py there is never imported; PYTHONPATH points
# at this checkout instead. Its replies are fixed JSON: codes and category
# names only.
helper() {
    PYTHONPATH="$project_directory/src" PYTHONDONTWRITEBYTECODE=1 python3 -P -m hearthwire "$@" </dev/null
}

# Plasma is stopped only for the one-time move below, and an EXIT trap always
# starts it again, also when a step fails or the script is interrupted.
plasma_stopped=false
plasma_by_systemd=false
start_plasma() {
    if [ "$plasma_stopped" = true ]; then
        plasma_stopped=false
        if [ "$plasma_by_systemd" = true ]; then
            systemctl --user start plasma-plasmashell.service >/dev/null 2>&1 || kstart plasmashell >/dev/null 2>&1 || true
        else
            kstart plasmashell >/dev/null 2>&1 || true
        fi
    fi
}
stop_plasma() {
    trap 'start_plasma' EXIT
    trap 'exit 130' INT TERM HUP
    plasma_stopped=true
    if systemctl --user is-active plasma-plasmashell.service >/dev/null 2>&1; then
        plasma_by_systemd=true
        systemctl --user stop plasma-plasmashell.service >/dev/null 2>&1 || true
    else
        kquitapp6 plasmashell >/dev/null 2>&1 || true
    fi
}
plasma_started_again() {
    start_plasma
    trap - EXIT INT TERM HUP
}
# --restart-plasma after the files changed: reload the running Plasma.
restart_plasma_session() {
    if systemctl --user is-active plasma-plasmashell.service >/dev/null 2>&1; then
        systemctl --user restart plasma-plasmashell.service
    else
        kquitapp6 plasmashell >/dev/null 2>&1 || true
        kstart plasmashell >/dev/null 2>&1
    fi
}

# Ask before stopping Plasma, unless --restart-plasma said yes already. Without
# a terminal there is nobody to ask: stop with nothing changed.
confirm_plasma_stop() {
    [ "$restart_plasma" = true ] && return 0
    if [ -t 0 ] && [ -t 1 ]; then
        printf '%s [y/N] ' "$1 This stops Plasma for a moment and starts it again. Continue?"
        read -r answer || answer=""
        case "$answer" in
            y|Y|yes|Yes|YES) return 0 ;;
        esac
        echo "Nothing was changed." >&2
        exit 1
    fi
    echo "$1 This stops Plasma for a moment, so run this again with --restart-plasma. Nothing was changed." >&2
    exit 1
}

# >>> legacy-migration: the one-time move from Hearthside (plan R2, D1-D8)
# One fixed message per --migrate error code; $2 says what happened to the rest.
migration_error() {
    case "$1" in
        *'"error":"not-locked"'*)
            # Each helper locks only its own name's mount; the other one replies ok.
            # Forward, a run killed during the wallet proof leaves the new name mounted.
            if [ "$rollback" = true ]; then
                echo "Lock the encrypted chat folder first: run PYTHONPATH=\"$project_directory/src\" python3 -P -m hearthwire --vault lock, then run this again. $2" >&2
            else
                echo "Lock the encrypted chat folder in the old Hearthside widget's Chat tab, or run python3 -P -m hearthside --vault lock; after an interrupted install, run PYTHONPATH=\"$project_directory/src\" python3 -P -m hearthwire --vault lock instead. Then run this again. $2" >&2
            fi
            ;;
        *'"error":"busy"'*)
            echo "The encrypted chat folder is in use right now. Try again in a moment. $2" >&2 ;;
        *'"error":"conflict","category":"data"'*)
            echo "Both a hearthside and a hearthwire folder exist in $data_home; refusing to merge them. Move the one you do not need away, then run this again. $2" >&2 ;;
        *'"error":"conflict","category":"config"'*)
            echo "Both a hearthside and a hearthwire folder exist in $config_home; refusing to merge them. Move the one you do not need away, then run this again. $2" >&2 ;;
        *'"error":"conflict"'*)
            echo "Hearthside and Hearthwire files are both present; refusing to merge them. $2" >&2 ;;
        *'"error":"symlink"'*)
            echo "A Hearthside or Hearthwire file or folder is a symbolic link; refusing to move through it. $2" >&2 ;;
        *'"error":"not-directory"'*|*'"error":"not-owned"'*)
            echo "A Hearthside or Hearthwire file or folder is not the kind expected or not yours; refusing to move it. $2" >&2 ;;
        *'"error":"invalid"'*)
            echo "The Plasma panel layout file could not be read safely, so it was not changed. $2" >&2 ;;
        *'"error":"plasma-running"'*)
            echo "Plasma did not stop. $2" >&2 ;;
        *)
            echo "Could not move the Hearthside data to Hearthwire. $2" >&2 ;;
    esac
}

# The helper's plasma-running reply, bare or with one of its category names
# (the applets step adds its own); nothing else counts.
is_plasma_running_reply() {
    case "$1" in
        '{"ok":false,"error":"plasma-running"}') return 0 ;;
        '{"ok":false,"error":"plasma-running","category":"'*'"}')
            reply_category=${1#'{"ok":false,"error":"plasma-running","category":"'}
            case "${reply_category%'"}'}" in
                data|config|notifyrc|cache|wallet-entry|applets) return 0 ;;
            esac
            ;;
    esac
    return 1
}

# One --migrate step while Plasma stops; plasma-running is retried for ~10 s.
migrate_step() {
    attempts=0
    while :; do
        if ! step_reply=$(helper --migrate "$1"); then
            step_reply=""
            break
        fi
        is_plasma_running_reply "$step_reply" || break
        attempts=$((attempts + 1))
        [ "$attempts" -lt 20 ] || break
        sleep 0.5
    done
}
# <<< legacy-migration

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
    # The opt-in usage history of every widget goes too, once the sign-in data
    # is gone. The helper refuses symlinks and replies {"ok":true} also when
    # there is none.
    clear_usage_history() {
        if ! history_reply=$(PYTHONPATH="$project_directory/src" PYTHONDONTWRITEBYTECODE=1 python3 -P -m hearthwire --usage-history clear --all </dev/null) \
            || [ "$history_reply" != '{"ok":true}' ]; then
            echo "Deleted the Hearthwire chat sign-in data, but could not delete the usage history (the folder hearthwire/usage-history in ${XDG_DATA_HOME:-$HOME/.local/share}). Delete it by hand." >&2
            exit 1
        fi
    }
    # The usage alert events file and the app and settings icons go too, but
    # only once the data is gone. rm unlinks a symlink, never its target.
    remove_installed_files() {
        rm -f -- "$notifyrc_directory/hearthwire.notifyrc"
        rm -f -- "$icon_directory/hearthwire.svg" \
            "$icon_directory/hearthwire-settings-general.svg" \
            "$icon_directory/hearthwire-settings-ai.svg" \
            "$icon_directory/hearthwire-settings-chat.svg"
    }
    # The settings backup holds no sign-ins and is kept on purpose; say where.
    report_kept_backup() {
        backup_file="$config_home/hearthwire/settings-backup.json"
        if [ -e "$backup_file" ] || [ -L "$backup_file" ]; then
            echo "Kept: your settings backup ($backup_file). Delete it by hand if you don't want it."
        fi
    }
    case "$reply" in
        '{"ok":true,"removed":[]}')
            clear_usage_history
            remove_installed_files
            echo "No Hearthwire chat sign-in data found."
            report_kept_backup
            ;;
        '{"ok":true,"removed":["'*'"]}')
            # Categories, in this order: vault, vault-keys, wallet-entry.
            clear_usage_history
            remove_installed_files
            case "$reply" in *'"vault"'*) echo "Deleted: encrypted chat folder (saved chat sign-ins)." ;; esac
            case "$reply" in *'"vault-keys"'*) echo "Deleted: KDE Wallet unlock slot of the encrypted chat folder." ;; esac
            case "$reply" in *'"wallet-entry"'*) echo "Deleted: the encrypted chat folder's key in KDE Wallet." ;; esac
            report_kept_backup
            ;;
        '{"ok":false,"error":"wallet-failed"}')
            echo "Deleted the Hearthwire chat files, but could not remove the encrypted chat folder's key from KDE Wallet (folder Hearthwire, entry encrypted-chat-folder). Remove it in KWalletManager." >&2
            exit 1
            ;;
        '{"ok":false,"error":"not-locked"}')
            echo "Lock the encrypted folder in Hearthwire first, then run this again. Nothing was deleted." >&2
            exit 1
            ;;
        # >>> legacy-migration
        '{"ok":false,"error":"legacy-data"}')
            echo "Your Hearthside data has not been moved to Hearthwire yet. Run ./scripts/install.sh first, then this again. Nothing was deleted." >&2
            exit 1
            ;;
        # <<< legacy-migration
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

# Remove what this script installs in your home folder, so a Hearthwire
# package (which those copies hide) is used: the helper in the Python user
# site (pip install --user), the widget in $XDG_DATA_HOME/plasma/plasmoids
# (kpackagetool6 -i), and the copied icons and usage alert events file. Your
# data stays: usage history, settings backup, the encrypted chat folder with
# its sign-ins and KDE Wallet key, ~/.config/hearthwire, ~/.local/share/hearthwire,
# your notification choices and widget settings. Nothing outside your home
# folder is touched and nothing runs with sudo. Running it again is harmless.
if [ "$remove_script_install" = true ]; then
    if [ "$(id -u)" = 0 ]; then
        echo "Run this as your own user, not as root: it removes only what this script installed in your home folder. Nothing was removed." >&2
        exit 1
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        echo "Required command not found: python3. Nothing was removed." >&2
        exit 1
    fi
    case "$user_data_home" in
        /*) ;;
        *)
            echo "HOME is not an absolute path. Nothing was removed." >&2
            exit 1
            ;;
    esac
    user_icon_directory="$user_data_home/icons/hicolor/scalable/apps"
    # The helper from this checkout says whether a package is installed
    # (fixed words and booleans only; read only, no network).
    if ! install_info=$(helper --install-info); then
        install_info=""
    fi
    case "$install_info" in
        '{"ok":true,"install_info_version":1,'*'"system_helper":true,'*'"system_plasmoid":true,'*) ;;
        *)
            echo "Warning: no Hearthwire package was found. After this, Hearthwire is gone until you install the package for your system (see \"Install from a package\" in README.md) or run ./scripts/install.sh again."
            ;;
    esac
    removed_any=false
    # The helper: only a copy in the Python user site, and only when pip
    # resolves the name to exactly that copy, never a system one.
    user_site=$(python3 -P -c 'import site; print(site.getusersitepackages())' </dev/null 2>/dev/null) || user_site=""
    case "$user_site" in
        /*) ;;
        *) user_site="" ;;
    esac
    user_helper_present() {
        [ -n "$user_site" ] || return 1
        for entry in "$user_site/hearthwire" "$user_site"/hearthwire-*.dist-info; do
            if [ -e "$entry" ] || [ -L "$entry" ]; then
                return 0
            fi
        done
        return 1
    }
    if user_helper_present; then
        pip_location=$(python3 -P -m pip show hearthwire </dev/null 2>/dev/null | sed -n 's/^Location: //p') || pip_location=""
        if [ "$pip_location" = "$user_site" ] \
            && python3 -P -m pip uninstall -y --break-system-packages hearthwire </dev/null >/dev/null 2>&1 \
            && ! user_helper_present; then
            echo "Removed: the Hearthwire helper in your Python user site ($user_site)."
            removed_any=true
        else
            echo "Could not remove the Hearthwire helper in your Python user site with pip. Remove $user_site/hearthwire and $user_site/hearthwire-*.dist-info by hand." >&2
            exit 1
        fi
    fi
    # The widget: that one folder (or a link in its place, never its target).
    if [ -L "$user_plasmoid" ]; then
        rm -f -- "$user_plasmoid"
        echo "Removed: the link to the Hearthwire widget ($user_plasmoid)."
        removed_any=true
    elif [ -d "$user_plasmoid" ]; then
        if [ ! -O "$user_plasmoid" ]; then
            echo "The Hearthwire widget folder $user_plasmoid is not yours; it was left in place." >&2
            exit 1
        fi
        rm -rf -- "$user_plasmoid"
        echo "Removed: the Hearthwire widget ($user_plasmoid)."
        removed_any=true
    elif [ -e "$user_plasmoid" ]; then
        echo "$user_plasmoid is not a folder; it was left in place." >&2
        exit 1
    fi
    # The icons and the usage alert events file this script copies (rm unlinks
    # a symlink, never its target). Your notification choices live in
    # ~/.config/hearthwire.notifyrc and stay.
    for installed_file in "$user_icon_directory/hearthwire.svg" \
        "$user_icon_directory/hearthwire-settings-general.svg" \
        "$user_icon_directory/hearthwire-settings-ai.svg" \
        "$user_icon_directory/hearthwire-settings-chat.svg" \
        "$user_data_home/knotifications6/hearthwire.notifyrc"; do
        if [ -e "$installed_file" ] || [ -L "$installed_file" ]; then
            rm -f -- "$installed_file"
            echo "Removed: $installed_file"
            removed_any=true
        fi
    done
    if [ "$removed_any" = false ]; then
        echo "No script install of Hearthwire found in your home folder; nothing was removed."
    fi
    echo "Kept: your Hearthwire data and settings (usage history, settings backup, encrypted chat folder and sign-ins, widget settings)."
    if [ "$removed_any" = true ]; then
        if [ "$restart_plasma" = true ]; then
            restart_plasma_session
        else
            echo "Restart Plasma so the widget from the package is used: log out and in, or run systemctl --user restart plasma-plasmashell.service"
        fi
    fi
    exit 0
fi

# >>> legacy-migration: --rollback-hearthwire
# Undo the move from Hearthside: the data, settings, notification choices,
# KDE Wallet key and widgets go back to the Hearthside names, then this
# release is uninstalled. The helper refuses (nothing changed) while a vault is
# mounted or in use, or when both names hold data; it answers plasma-running
# only after those checks passed, so Plasma is stopped only when it can work.
if [ "$rollback" = true ]; then
    for executable in python3 kpackagetool6; do
        if ! command -v "$executable" >/dev/null 2>&1; then
            echo "Required command not found: $executable" >&2
            exit 1
        fi
    done
    if ! step_reply=$(helper --migrate rollback); then
        step_reply=""
    fi
    if is_plasma_running_reply "$step_reply"; then
        confirm_plasma_stop "Going back to Hearthside renames your Hearthwire widgets in the panel layout."
        stop_plasma
        migrate_step rollback
    fi
    case "$step_reply" in
        '{"ok":true,"restored":['*) ;;
        *)
            migration_error "$step_reply" "Nothing more was changed; run this again once that is fixed."
            exit 1
            ;;
    esac
    if python3 -P -m pip show hearthwire >/dev/null 2>&1; then
        python3 -P -m pip uninstall -y --break-system-packages hearthwire >/dev/null 2>&1 \
            || echo "Could not remove the hearthwire helper with pip; remove it by hand." >&2
    fi
    # Only this user's copy; a system package stays (see user_plasmoid).
    if [ -d "$user_plasmoid" ]; then
        kpackagetool6 -t Plasma/Applet -r io.github.flybytechprog.hearthwire >/dev/null 2>&1 \
            || echo "Could not remove the Hearthwire widget package; remove it by hand." >&2
    fi
    rm -f -- "$icon_directory/hearthwire.svg" \
        "$icon_directory/hearthwire-settings-general.svg" \
        "$icon_directory/hearthwire-settings-ai.svg" \
        "$icon_directory/hearthwire-settings-chat.svg" \
        "$notifyrc_directory/hearthwire.notifyrc"
    plasma_started_again
    case "$step_reply" in
        *'"pending":["wallet-entry"]'*)
            echo "The KDE Wallet key of the encrypted chat folder could not be moved back (the wallet may be locked). Unlock with the passphrase still works." >&2 ;;
    esac
    echo "Hearthwire was rolled back to the Hearthside names and uninstalled."
    echo "To use Hearthside again, check out tag hearthside-final and run its install.sh"
    exit 0
fi
# <<< legacy-migration

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

# >>> legacy-migration: what is left to move from Hearthside (read only)
# Checked before anything is installed or changed: a mounted or busy vault,
# or data under both names, stops the script here with nothing changed.
if ! migration_reply=$(helper --migrate status); then
    echo "Could not run the Hearthwire helper from this checkout. Nothing was changed." >&2
    exit 1
fi
migration_wallet_only=false
case "$migration_reply" in
    '{"ok":true,"pending":[],"present":['*) migration_pending=false ;;
    # Only the KDE Wallet entry is left: nothing Plasma holds, so no stop.
    '{"ok":true,"pending":["wallet-entry"],"present":['*)
        migration_pending=false
        migration_wallet_only=true
        ;;
    '{"ok":true,"pending":["'*) migration_pending=true ;;
    *)
        migration_error "$migration_reply" "Nothing was changed."
        exit 1
        ;;
esac
# User decision Q4: the panel layout backup from the move is deleted by the
# next successful install that finds the move complete (the wallet entry too)
# and the widgets already using the new id.
applets_backup="$config_home/plasma-org.kde.plasma.desktop-appletsrc.hearthside-backup"
remove_applets_backup=false
if [ "$migration_pending" = false ] && [ "$migration_wallet_only" = false ]; then
    case "$migration_reply" in
        *'"present":['*'"applets"'*) remove_applets_backup=true ;;
    esac
fi
if [ "$migration_pending" = true ]; then
    confirm_plasma_stop "Your Hearthside data, settings and widgets will be moved to Hearthwire (they keep their settings and sign-ins)."
fi
# <<< legacy-migration

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
        "QtQuick/Shapes:qt6-declarative" \
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

# >>> legacy-migration: move from Hearthside, then remove the old install
# Plasma is stopped (it rewrites its panel layout on exit), the helper moves
# the data and then the widgets' plugin id; finished steps are never repeated.
migration_wallet_pending=false
migration_moved_applets=false
# Wallet entry only: try it with Plasma running; if the wallet still does not
# answer, or the folder is unlocked, the install goes on and a note says so.
if [ "$migration_wallet_only" = true ]; then
    migration_wallet_pending=true
    if step_reply=$(helper --migrate run); then
        case "$step_reply" in
            '{"ok":true,"migrated":["wallet-entry"],"pending":[]}') migration_wallet_pending=false ;;
        esac
    fi
fi
if [ "$migration_pending" = true ]; then
    stop_plasma
    migrate_step run
    case "$step_reply" in
        '{"ok":true,"migrated":['*) ;;
        *)
            migration_error "$step_reply" "Plasma is started again. Finished steps are kept; run this again once that is fixed."
            exit 1
            ;;
    esac
    case "$step_reply" in *'"pending":['*'"wallet-entry"'*) migration_wallet_pending=true ;; esac
    migrate_step applets
    case "$step_reply" in
        *'"pending":['*'"applets"'*)
            migration_error '' "Plasma is started again. Your widgets were not changed; run this again."
            exit 1
            ;;
        '{"ok":true,"migrated":["applets"]'*) migration_moved_applets=true ;;
        '{"ok":true,"migrated":[]'*) ;;
        *)
            migration_error "$step_reply" "Plasma is started again. Your widgets were not changed; run this again once that is fixed."
            exit 1
            ;;
    esac
fi
if python3 -P -m pip show hearthside >/dev/null 2>&1; then
    if ! python3 -P -m pip uninstall -y --break-system-packages hearthside; then
        echo "Could not remove the old hearthside helper (it may be installed system-wide). Remove it manually, then run this script again." >&2
        exit 1
    fi
fi
if kpackagetool6 -t Plasma/Applet -s io.github.flybytechprog.hearthside >/dev/null 2>&1; then
    if ! kpackagetool6 -t Plasma/Applet -r io.github.flybytechprog.hearthside; then
        echo "Could not remove the old Hearthside widget package (it may be installed system-wide). Remove it manually, then run this script again." >&2
        exit 1
    fi
fi
# rm unlinks a symlink, never its target.
rm -f -- "$icon_directory/hearthside.svg" \
    "$icon_directory/hearthside-settings-general.svg" \
    "$icon_directory/hearthside-settings-ai.svg" \
    "$icon_directory/hearthside-settings-chat.svg" \
    "$notifyrc_directory/hearthside.notifyrc"
# <<< legacy-migration

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

# -u only over this user's own copy: with only a system package, -s finds it
# too, and -u then fails half-way (see user_plasmoid).
if [ -d "$user_plasmoid" ]; then
    kpackagetool6 -t Plasma/Applet -u "$project_directory/plasmoid"
else
    kpackagetool6 -t Plasma/Applet -i "$project_directory/plasmoid"
fi

# Full-color app icon for the widget list and Settings → About (metadata "Icon": "hearthwire").
mkdir -p -- "$icon_directory"
# Unlinked first, like the notifyrc below, so a symlink is replaced, never followed.
rm -f -- "$icon_directory/hearthwire.svg"
cp -- "$project_directory/assets/hearthwire.svg" "$icon_directory/hearthwire.svg"
# Settings page icons (config.qml), single color: Plasma recolors them to
# the theme like its own icons. Unlinked first too.
for settings_icon in general ai chat; do
    rm -f -- "$icon_directory/hearthwire-settings-$settings_icon.svg"
    cp -- "$project_directory/assets/hearthwire-settings-$settings_icon.svg" \
        "$icon_directory/hearthwire-settings-$settings_icon.svg"
done

# Usage alert events (System Settings → Notifications → Hearthwire). The old
# file is unlinked first, so a symlink in its place is replaced, never followed.
mkdir -p -- "$notifyrc_directory"
rm -f -- "$notifyrc_directory/hearthwire.notifyrc"
cp -- "$project_directory/assets/hearthwire.notifyrc" "$notifyrc_directory/hearthwire.notifyrc"
chmod 0644 -- "$notifyrc_directory/hearthwire.notifyrc"

if [ "$plasma_stopped" = true ]; then
    plasma_started_again
elif [ "$restart_plasma" = true ]; then
    restart_plasma_session
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
# >>> legacy-migration: report the move; delete the old layout backup (Q4)
if [ "$migration_pending" = true ]; then
    echo "Moved your Hearthside data, settings and widgets to Hearthwire."
    if [ "$migration_moved_applets" = true ]; then
        echo "A backup of your panel layout from before the move was saved as $applets_backup; the next successful run of this installer deletes it."
    fi
    echo "You may delete the empty Hearthside folder in KWalletManager."
fi
if [ "$migration_wallet_pending" = true ]; then
    echo "KDE Wallet wasn't available; run the installer again later to finish moving its entry."
fi
# Only an owned regular file, never through a symlink (rm unlinks a link itself).
if [ "$remove_applets_backup" = true ] && [ -f "$applets_backup" ] && [ ! -L "$applets_backup" ] && [ -O "$applets_backup" ]; then
    if rm -f -- "$applets_backup"; then
        echo "Deleted the panel layout backup from the move to Hearthwire (no longer needed)."
    fi
fi
# <<< legacy-migration
