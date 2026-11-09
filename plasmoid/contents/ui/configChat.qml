import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasmoid
import "ChatSites.js" as ChatSites
import "OllamaChat.js" as OllamaChat

KCM.SimpleKCM {
    id: page

    // Every key is declared so the config dialog can map all of them.
    property string cfg_trackedProviders:
        "[\"claude\",\"codex\",\"cursor\",\"antigravity\",\"copilot\",\"devin\",\"grok\"]"
    property string cfg_trackedProvidersDefault:
        "[\"claude\",\"codex\",\"cursor\",\"antigravity\",\"copilot\",\"devin\",\"grok\"]"
    property string cfg_providerMetrics: "{}"
    property string cfg_providerMetricsDefault: "{}"
    property string cfg_usageMode: "remaining"
    property string cfg_usageModeDefault: "remaining"
    property int cfg_refreshInterval: 300
    property int cfg_refreshIntervalDefault: 300
    property int cfg_configSchemaVersion: 2
    property int cfg_configSchemaVersionDefault: 2
    property bool cfg_initialSetupComplete: false
    property bool cfg_initialSetupCompleteDefault: false
    property string cfg_chatSites:
        "[\"claude\",\"chatgpt\",\"grok\",\"gemini\",\"copilot\",\"mscopilot\"]"
    property string cfg_chatSitesDefault:
        "[\"claude\",\"chatgpt\",\"grok\",\"gemini\",\"copilot\",\"mscopilot\"]"
    property string cfg_chatDefaultSite: "claude"
    property string cfg_chatDefaultSiteDefault: "claude"
    property string cfg_chatCustomUrls: "{}"
    property string cfg_chatCustomUrlsDefault: "{}"
    property string cfg_chatSignInStorage: "memory"
    property string cfg_chatSignInStorageDefault: "memory"
    // Written only by main.qml; kept in step so Apply never writes back an
    // old value.
    property int cfg_chatProfileGeneration: 0
    property int cfg_chatProfileGenerationDefault: 0
    property int cfg_chatAutoLockMinutes: 0
    property int cfg_chatAutoLockMinutesDefault: 0
    property string cfg_chatVaultUnlock: "passphrase"
    property string cfg_chatVaultUnlockDefault: "passphrase"
    property bool cfg_chatKeepOpen: false
    property bool cfg_chatKeepOpenDefault: false
    property string cfg_chatOllamaUrl: "http://127.0.0.1:11434"
    property string cfg_chatOllamaUrlDefault: "http://127.0.0.1:11434"
    property string cfg_popupDefaultTab: "chat"
    property string cfg_popupDefaultTabDefault: "chat"
    property bool cfg_showUsageTab: true
    property bool cfg_showUsageTabDefault: true
    property bool cfg_showChatTab: true
    property bool cfg_showChatTabDefault: true
    property string cfg_popupSize: "normal"
    property string cfg_popupSizeDefault: "normal"
    property bool cfg_tooltipShowsUsage: true
    property bool cfg_tooltipShowsUsageDefault: true
    property string cfg_tooltipMetrics: ""
    property string cfg_tooltipMetricsDefault: ""
    property string cfg_shortcutOpens: "popup"
    property string cfg_shortcutOpensDefault: "popup"
    // Written only by main.qml (zoom keys, Ctrl+wheel); kept in step so
    // Apply never writes back an old value.
    property string cfg_chatSiteZoom: "{}"
    property string cfg_chatSiteZoomDefault: "{}"
    property bool cfg_alertLowEnabled: false
    property bool cfg_alertLowEnabledDefault: false
    property int cfg_alertLowPercent: 20
    property int cfg_alertLowPercentDefault: 20
    property bool cfg_alertResetEnabled: false
    property bool cfg_alertResetEnabledDefault: false
    property string cfg_providerOrder: ""
    property string cfg_providerOrderDefault: ""
    property bool cfg_usageCompact: false
    property bool cfg_usageCompactDefault: false
    property int cfg_usageWarnPercent: 60
    property int cfg_usageWarnPercentDefault: 60
    property int cfg_usageCriticalPercent: 85
    property int cfg_usageCriticalPercentDefault: 85
    property string cfg_usageNormalColor: ""
    property string cfg_usageNormalColorDefault: ""
    property string cfg_usageWarnColor: ""
    property string cfg_usageWarnColorDefault: ""
    property string cfg_usageCriticalColor: ""
    property string cfg_usageCriticalColorDefault: ""
    property string cfg_panelRing: "auto"
    property string cfg_panelRingDefault: "auto"
    property string cfg_middleClickOpens: "refresh"
    property string cfg_middleClickOpensDefault: "refresh"
    property bool cfg_usageHistoryEnabled: false
    property bool cfg_usageHistoryEnabledDefault: false

    // Page-local only; the advanced section always starts collapsed.
    property bool showAdvanced: false

    // main.qml may move to a new generation or store a zoom while this page
    // is open.
    Connections {
        target: Plasmoid.configuration
        function onValueChanged(key, value) {
            if (key === "chatProfileGeneration")
                page.cfg_chatProfileGeneration = value
            else if (key === "chatSiteZoom")
                page.cfg_chatSiteZoom = value
        }
    }

    // Web sites, then the built-in Ollama chat when it is on.
    readonly property var enabledSites: OllamaChat.menuEntries(
        ChatSites.enabledSites(page.cfg_chatSites), page.cfg_chatSites)
    readonly property var enabledIds: page.enabledSites.map(function (site) { return site.id })

    function setEnabled(siteId, enabled) {
        var ids = OllamaChat.allSiteIds(ChatSites.siteIds()).filter(function (id) {
            return id === siteId ? enabled : page.enabledIds.indexOf(id) >= 0
        })
        page.cfg_chatSites = JSON.stringify(ids)
        if (ids.indexOf(page.cfg_chatDefaultSite) < 0 && ids.length > 0)
            page.cfg_chatDefaultSite = ids[0]
    }

    // Saved custom address of one site, "" when it uses the built-in one.
    function savedCustomUrl(siteId) {
        var map = ChatSites.parseCustomUrls(page.cfg_chatCustomUrls)
        return Object.prototype.hasOwnProperty.call(map, siteId) ? map[siteId] : ""
    }

    // Only valid or empty addresses are ever written; "" removes the entry.
    function setCustomUrl(siteId, url) {
        var map = ChatSites.parseCustomUrls(page.cfg_chatCustomUrls)
        if (url === "")
            delete map[siteId]
        else
            map[siteId] = url
        page.cfg_chatCustomUrls = ChatSites.serializeCustomUrls(map)
    }

    function customUrlError(siteId, code) {
        switch (code) {
        case "":
            return ""
        case "too-long":
            return i18n("This address is too long.")
        case "whitespace":
            return i18n("Addresses can't contain spaces or line breaks.")
        case "userinfo":
            return i18n("Addresses with a user name or password aren't allowed.")
        case "scheme":
            return ChatSites.byId(siteId) && ChatSites.byId(siteId).local === true
                ? i18n("Use an address that starts with https:// or http://.")
                : i18n("Use an address that starts with https://.")
        case "http-not-loopback":
            return i18n("http is allowed only for this computer. Use https or an SSH tunnel.")
        case "loopback-not-allowed":
            return i18n("Addresses on this computer are allowed only for Local.")
        default:
            return i18n("This isn't a valid web address.")
        }
    }

    function ollamaAddressError(code) {
        switch (code) {
        case "":
            return ""
        case "too-long":
            return i18n("This address is too long.")
        case "whitespace":
            return i18n("Addresses can't contain spaces or line breaks.")
        case "userinfo":
            return i18n("Addresses with a user name or password aren't allowed.")
        case "scheme":
            return i18n("Use an address that starts with http://.")
        case "not-loopback":
            return i18n("Only this computer is allowed: 127.0.0.1, localhost or [::1].")
        case "port-missing":
            return i18n("Add the port, for example http://127.0.0.1:11434.")
        case "port-range":
            return i18n("The port must be between 1 and 65535.")
        case "path":
            return i18n("Use only the address and port, without a path.")
        default:
            return i18n("This isn't a valid address.")
        }
    }

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Kirigami.Heading {
                level: 2
                text: i18n("Chat sites")
            }
            Kirigami.ContextualHelpButton {
                toolTipText: i18n("Sites open in a private, in-memory browser profile unless Stay signed in is on (General). The widget never reads or changes the pages and sends nothing to the developer. Microphone, camera, screen sharing, notifications, location and clipboard reading are always denied. Downloads ask first and go to your Downloads folder. Links to other websites open in your browser. Text you copy may be kept by your clipboard manager. Each open site uses roughly 200–500 MB of memory.")
            }
        }

        Repeater {
            model: ChatSites.sites.concat([OllamaChat.ENTRY])

            delegate: RowLayout {
                id: siteRow
                required property var modelData
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                QQC2.CheckBox {
                    id: siteCheck
                    checked: page.enabledIds.indexOf(siteRow.modelData.id) >= 0
                    onToggled: page.setEnabled(siteRow.modelData.id, checked)
                }
                Kirigami.Icon {
                    source: Qt.resolvedUrl("../images/" + siteRow.modelData.icon)
                    Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                    Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                    isMask: true
                    color: Kirigami.Theme.textColor
                }
                QQC2.Label {
                    text: siteRow.modelData.native === true
                        ? i18n("%1 (built-in chat with Ollama on this computer)", siteRow.modelData.name)
                        : siteRow.modelData.name
                    elide: Text.ElideRight
                    Layout.fillWidth: false
                    Layout.maximumWidth: implicitWidth
                    MouseArea {
                        anchors.fill: parent
                        onClicked: page.setEnabled(siteRow.modelData.id, !siteCheck.checked)
                    }
                }
                Kirigami.ContextualHelpButton {
                    visible: siteRow.modelData.native === true
                    toolTipText: i18n("The conversation is kept in memory only and goes to the Ollama server on this computer, nowhere else. Clear also unloads the models it used. Cloud models are hidden. Before sending, Hearthwire checks that the Ollama port belongs to you or to the system, never to another user. Hearthwire never starts Ollama.")
                }
                Item {
                    Layout.fillWidth: true
                }
            }
        }

        Kirigami.FormLayout {
            Layout.fillWidth: true

            QQC2.ComboBox {
                Kirigami.FormData.label: i18n("Open first:")
                enabled: page.enabledSites.length > 0
                model: page.enabledSites
                textRole: "name"
                valueRole: "id"
                currentIndex: Math.max(0, page.enabledIds.indexOf(
                    ChatSites.initialSite(page.enabledIds, page.cfg_chatDefaultSite)
                ))
                onActivated: page.cfg_chatDefaultSite = currentValue
            }
        }

        QQC2.Label {
            Layout.fillWidth: true
            visible: page.enabledSites.length === 0
            text: i18n("The Chat tab is hidden while no site is enabled.")
            wrapMode: Text.WordWrap
            opacity: 0.72
        }
        QQC2.Label {
            Layout.fillWidth: true
            visible: !page.cfg_showChatTab
            text: i18n("The Chat tab is hidden in General.")
            wrapMode: Text.WordWrap
            opacity: 0.72
        }

        Kirigami.Separator {
            Layout.fillWidth: true
        }

        QQC2.CheckBox {
            text: i18n("Show advanced settings")
            checked: page.showAdvanced
            onToggled: page.showAdvanced = checked
        }

        ColumnLayout {
            Layout.fillWidth: true
            visible: page.showAdvanced
            spacing: Kirigami.Units.largeSpacing

            RowLayout {
                spacing: Kirigami.Units.smallSpacing
                Kirigami.Heading {
                    level: 2
                    text: i18n("Custom addresses")
                }
                Kirigami.ContextualHelpButton {
                    toolTipText: i18n("Leave a field empty to use the built-in address. Addresses are saved in your Plasma configuration file: don't put passwords, tokens or other secrets in them.")
                }
            }

            Repeater {
                model: ChatSites.sites

                delegate: ColumnLayout {
                    id: urlRow
                    required property var modelData
                    // Validation code of the text in the field; "" when valid.
                    property string errorCode: ""
                    // Saved value this row last saw or wrote.
                    property string savedUrl: ""
                    // Saved value when the page opened or when it last changed
                    // elsewhere (Defaults); written back while the text is invalid.
                    property string savedBaseline: ""
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    function load(saved) {
                        urlRow.savedBaseline = saved
                        urlRow.savedUrl = saved
                        urlRow.errorCode = ""
                        if (urlField.text.trim() !== saved)
                            urlField.text = saved
                    }

                    function syncFromConfig() {
                        // Our own writes and other rows' writes leave this
                        // row's saved value as last seen; keep the field as is.
                        var saved = page.savedCustomUrl(urlRow.modelData.id)
                        if (saved !== urlRow.savedUrl)
                            urlRow.load(saved)
                    }

                    function edit(text) {
                        var persist = ChatSites.customUrlToPersist(
                            urlRow.modelData.id, text, urlRow.savedBaseline)
                        urlRow.errorCode = persist.error
                        urlRow.savedUrl = persist.url
                        page.setCustomUrl(urlRow.modelData.id, persist.url)
                    }

                    Component.onCompleted: urlRow.load(page.savedCustomUrl(urlRow.modelData.id))

                    Connections {
                        target: page
                        function onCfg_chatCustomUrlsChanged() {
                            urlRow.syncFromConfig()
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing
                        QQC2.Label {
                            text: urlRow.modelData.name
                            elide: Text.ElideRight
                        }
                        Kirigami.ContextualHelpButton {
                            visible: urlRow.modelData.local === true
                            toolTipText: i18n("http is allowed only for this computer (localhost, 127.0.0.1, [::1]). For a server on another machine use https or an SSH tunnel.")
                        }
                        Item {
                            Layout.fillWidth: true
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing

                        QQC2.TextField {
                            id: urlField
                            Layout.fillWidth: true
                            placeholderText: urlRow.modelData.url
                            inputMethodHints: Qt.ImhUrlCharactersOnly | Qt.ImhNoPredictiveText
                                | Qt.ImhNoAutoUppercase
                            Accessible.name: i18n("Address for %1", urlRow.modelData.name)
                            onTextEdited: urlRow.edit(urlField.text)
                        }
                        QQC2.ToolButton {
                            icon.name: "edit-undo"
                            display: QQC2.AbstractButton.IconOnly
                            text: i18n("Use the built-in address")
                            enabled: urlField.text !== ""
                            onClicked: {
                                urlField.text = ""
                                urlRow.edit("")
                            }
                            QQC2.ToolTip.text: text
                            QQC2.ToolTip.visible: hovered
                        }
                    }

                    QQC2.Label {
                        Layout.fillWidth: true
                        visible: urlRow.errorCode !== ""
                        wrapMode: Text.WordWrap
                        color: Kirigami.Theme.negativeTextColor
                        text: page.customUrlError(urlRow.modelData.id, urlRow.errorCode)
                    }

                }
            }

            ColumnLayout {
                id: ollamaRow
                // Validation code of the text in the field; "" when valid.
                property string errorCode: ""
                // Saved value this row last saw or wrote.
                property string savedAddress: ""
                // Saved value when the page opened or when it last changed
                // elsewhere (Defaults); written back while the text is invalid.
                property string savedBaseline: ""
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                function load(saved) {
                    ollamaRow.savedBaseline = saved
                    ollamaRow.savedAddress = saved
                    var checked = OllamaChat.validateAddress(saved)
                    ollamaRow.errorCode = checked.error
                    // The default shows as the placeholder.
                    var shown = saved === OllamaChat.DEFAULT_ADDRESS ? "" : saved
                    if (ollamaField.text.trim() !== shown)
                        ollamaField.text = shown
                }

                function syncFromConfig() {
                    if (page.cfg_chatOllamaUrl !== ollamaRow.savedAddress)
                        ollamaRow.load(page.cfg_chatOllamaUrl)
                }

                // Only a valid address (or the default) is ever written.
                function edit(text) {
                    var persist = OllamaChat.addressToPersist(text, ollamaRow.savedBaseline)
                    ollamaRow.errorCode = persist.error
                    ollamaRow.savedAddress = persist.address
                    page.cfg_chatOllamaUrl = persist.address
                }

                Component.onCompleted: ollamaRow.load(page.cfg_chatOllamaUrl)

                Connections {
                    target: page
                    function onCfg_chatOllamaUrlChanged() {
                        ollamaRow.syncFromConfig()
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing
                    QQC2.Label {
                        text: i18n("Ollama address")
                        elide: Text.ElideRight
                    }
                    Kirigami.ContextualHelpButton {
                        toolTipText: i18n("Only this computer: http:// with 127.0.0.1, localhost or [::1] and a port. Leave empty for the default, http://127.0.0.1:11434.")
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    QQC2.TextField {
                        id: ollamaField
                        objectName: "ollamaAddressField"
                        Layout.fillWidth: true
                        placeholderText: OllamaChat.DEFAULT_ADDRESS
                        maximumLength: OllamaChat.MAX_ADDRESS_LENGTH * 2
                        inputMethodHints: Qt.ImhUrlCharactersOnly | Qt.ImhNoPredictiveText
                            | Qt.ImhNoAutoUppercase
                        Accessible.name: i18n("Ollama address")
                        onTextEdited: ollamaRow.edit(ollamaField.text)
                    }
                    QQC2.ToolButton {
                        icon.name: "edit-undo"
                        display: QQC2.AbstractButton.IconOnly
                        text: i18n("Use the default address")
                        enabled: ollamaField.text !== ""
                        onClicked: {
                            ollamaField.text = ""
                            ollamaRow.edit("")
                        }
                        QQC2.ToolTip.text: text
                        QQC2.ToolTip.visible: hovered
                    }
                }

                QQC2.Label {
                    objectName: "ollamaAddressError"
                    Layout.fillWidth: true
                    visible: ollamaRow.errorCode !== ""
                    wrapMode: Text.WordWrap
                    color: Kirigami.Theme.negativeTextColor
                    text: page.ollamaAddressError(ollamaRow.errorCode)
                }

            }
        }
    }
}
