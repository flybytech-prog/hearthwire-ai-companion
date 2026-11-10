# Fedora KDE. Source0 is `git archive` of the release tag, made by
# packaging/source-archive.sh (rpmbuild -ba with _sourcedir pointing at it).
# No scriptlets: installing only adds files, and removing the package never
# touches anything in a home folder (sign-ins, history, backups stay).

%global plugin io.github.flybytechprog.hearthwire

Name:           hearthwire
Version:        1.0.0
Release:        1%{?dist}
Summary:        AI companion for KDE Plasma 6 with AI usage meters and AI chats

License:        MIT
URL:            https://github.com/flybytech-prog/hearthwire-ai-companion
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel >= 3.11
BuildRequires:  pyproject-rpm-macros
BuildRequires:  python3-pip
BuildRequires:  python3-setuptools

Requires:       python3 >= 3.11
Requires:       plasma-workspace >= 6.0
# The plasmoid is QML, so rpm cannot find what it needs by itself. These are
# the QML modules it imports, by the qt6qml() names Fedora's packages provide
# (libplasma, plasma5support, kf6-kirigami, kf6-kcmutils, kf6-knotifications
# and qt6-qtdeclarative on Fedora 43 and 44). Naming libplasma itself is an
# rpmlint error (explicit-lib-dependency).
Requires:       qt6qml(org.kde.plasma.components)
Requires:       qt6qml(org.kde.plasma.configuration)
Requires:       qt6qml(org.kde.plasma.core)
Requires:       qt6qml(org.kde.plasma.extras)
Requires:       qt6qml(org.kde.plasma.plasmoid)
Requires:       qt6qml(org.kde.plasma.plasma5support)
Requires:       qt6qml(org.kde.kirigami)
Requires:       qt6qml(org.kde.kcmutils)
Requires:       qt6qml(org.kde.notification)
Requires:       qt6qml(QtCore)
Requires:       qt6qml(QtQuick)
Requires:       qt6qml(QtQuick.Controls)
Requires:       qt6qml(QtQuick.Dialogs)
Requires:       qt6qml(QtQuick.Layouts)
Requires:       qt6qml(QtQuick.Shapes)
Requires:       qt6qml(QtQuick.Window)
# The Chat tab (AI chat web sites): qt6-qtwebengine.
Recommends:     qt6qml(QtWebEngine)
# Stay signed in (encrypted chat sign-ins).
Suggests:       gocryptfs
Suggests:       fuse3
Suggests:       kdialog
# Unlock with KDE Wallet: kwallet-query, qdbus (Fedora's qt6-qttools installs
# it as qdbus-qt6, which the helper looks for after qdbus6) and openssl.
Suggests:       kf6-kwallet
Suggests:       qt6-qttools
Suggests:       openssl
# Providers that keep their sign-in in Secret Service (secret-tool).
Suggests:       libsecret
# The built-in Ollama chat.
Suggests:       ollama

%description
Hearthwire sits in the KDE Plasma 6 panel. Its Chat tab opens AI chat sites
(Claude, ChatGPT, Grok, Gemini, GitHub Copilot, Microsoft Copilot, a local web
UI) or a built-in chat with local Ollama models, private by default. Its Usage
tab shows how much of each AI coding plan is left (Claude Code, Codex, Cursor,
Antigravity, GitHub Copilot, Devin, Grok), read by a small Python helper that
uses only the standard library.

%prep
%autosetup -n %{name}-%{version}

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files -l hearthwire

# The plasmoid, system-wide (what kpackagetool6 -i does per user).
install -d %{buildroot}%{_datadir}/plasma/plasmoids/%{plugin}
cp -r --no-preserve=mode,ownership plasmoid/. %{buildroot}%{_datadir}/plasma/plasmoids/%{plugin}/
find %{buildroot}%{_datadir}/plasma/plasmoids/%{plugin} -type d -exec chmod 0755 {} +
find %{buildroot}%{_datadir}/plasma/plasmoids/%{plugin} -type f -exec chmod 0644 {} +

# App icon, settings page icons, and the usage alert events.
for icon in hearthwire hearthwire-settings-general hearthwire-settings-ai hearthwire-settings-chat; do
    install -Dpm 0644 assets/$icon.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/$icon.svg
done
install -Dpm 0644 assets/hearthwire.notifyrc %{buildroot}%{_datadir}/knotifications6/hearthwire.notifyrc

%check
# The test suite is not in the source archive; the release workflow runs it.
# __main__ is left out: importing it runs the helper.
%pyproject_check_import -e hearthwire.__main__

%files -f %{pyproject_files}
%doc README.md
%{_bindir}/hearthwire
%{_datadir}/plasma/plasmoids/%{plugin}/
%{_datadir}/icons/hicolor/scalable/apps/hearthwire.svg
%{_datadir}/icons/hicolor/scalable/apps/hearthwire-settings-general.svg
%{_datadir}/icons/hicolor/scalable/apps/hearthwire-settings-ai.svg
%{_datadir}/icons/hicolor/scalable/apps/hearthwire-settings-chat.svg
%{_datadir}/knotifications6/hearthwire.notifyrc

%changelog
* Tue Nov 10 2026 flybytech-prog <104578369+flybytech-prog@users.noreply.github.com> - 1.0.0-1
- First packaged release
