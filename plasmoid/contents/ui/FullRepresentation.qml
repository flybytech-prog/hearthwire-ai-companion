import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import QtQuick.Window
import org.kde.plasma.plasmoid
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.extras as PlasmaExtras
import org.kde.kirigami as Kirigami
import "ChatSites.js" as ChatSites
import "SettingsLogic.js" as SettingsLogic

PlasmaExtras.Representation {
    id: full

    // Settings → General → Show tabs; Chat also needs an enabled site.
    readonly property bool chatAvailable: root.chatShown
    readonly property bool onChat: full.chatAvailable && root.shownTab === "chat"
    // The built-in Ollama chat is shown instead of the web chat.
    readonly property bool onOllama: full.onChat && root.chatSiteId === "ollama"
    // Split view is on and actually shown (it stays on across tab switches).
    readonly property bool splitShown: root.chatSplit && full.onChat && !full.onOllama
    readonly property var popupSize: ChatSites.popupSize(
        // Split view gets a wider popup, so both sites fit.
        full.splitShown ? "split" : full.onChat ? "chat" : "usage",
        Kirigami.Units.gridUnit,
        // The popup's own screen, not the whole virtual desktop.
        Screen.width,
        Screen.height,
        root.popupScale
    )

    // A theme icon name, else fallbackName: Hearthwire's own icons are only
    // in the theme after install.sh, not after a plain kpackagetool6 install.
    component IconChoice: Kirigami.Icon {
        required property string fallbackName
        readonly property string name: status === Kirigami.Icon.Error ? fallbackName : String(source)
        visible: false
        fallback: ""
    }

    // The chat site picker (fixed catalog names and icons).
    component SitePicker: PlasmaComponents.ComboBox {
        id: sitePicker
        Layout.fillWidth: true
        Layout.minimumWidth: Kirigami.Units.gridUnit * 5
        textRole: "name"
        valueRole: "id"

        delegate: PlasmaComponents.ItemDelegate {
            id: siteDelegate
            required property var modelData
            required property int index
            width: ListView.view ? ListView.view.width : implicitWidth
            highlighted: sitePicker.highlightedIndex === siteDelegate.index
            contentItem: RowLayout {
                spacing: Kirigami.Units.smallSpacing
                Kirigami.Icon {
                    source: Qt.resolvedUrl("../images/" + siteDelegate.modelData.icon)
                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                    Layout.preferredHeight: Kirigami.Units.iconSizes.small
                    isMask: true
                    color: Kirigami.Theme.textColor
                }
                PlasmaComponents.Label {
                    Layout.fillWidth: true
                    textFormat: Text.PlainText
                    text: siteDelegate.modelData.name
                    elide: Text.ElideRight
                }
            }
        }
    }

    // Ollama's model picker; model names come from the server, so its
    // delegate shows them as plain text only.
    component ModelPicker: PlasmaComponents.ComboBox {
        id: picker
        Layout.fillWidth: true
        Layout.minimumWidth: Kirigami.Units.gridUnit * 5
        enabled: ollamaView.modelList.length > 0
        model: ollamaView.modelList
        textRole: "name"
        valueRole: "name"
        displayText: picker.currentIndex >= 0 ? picker.currentText : i18n("No model")

        delegate: PlasmaComponents.ItemDelegate {
            id: modelDelegate
            required property var modelData
            required property int index
            width: ListView.view ? ListView.view.width : implicitWidth
            highlighted: picker.highlightedIndex === modelDelegate.index
            contentItem: RowLayout {
                spacing: Kirigami.Units.smallSpacing
                PlasmaComponents.Label {
                    Layout.fillWidth: true
                    textFormat: Text.PlainText
                    text: modelDelegate.modelData.name
                    elide: Text.ElideRight
                }
                PlasmaComponents.Label {
                    textFormat: Text.PlainText
                    visible: text !== ""
                    text: modelDelegate.modelData.parameterSize
                    opacity: 0.6
                }
            }
        }
    }

    // Text dropped on the panel icon (main.qml) goes into Ollama's message
    // box; it is never sent from there.
    function takePendingDrop() {
        if (root.pendingDrop === "")
            return
        var text = root.pendingDrop
        root.pendingDrop = ""
        ollamaView.takeDrop(text)
    }

    function takePendingDropError() {
        if (root.pendingDropError === "")
            return
        var code = root.pendingDropError
        root.pendingDropError = ""
        ollamaView.dropFailed(code)
    }

    // The prompt library panel is open (runtime only).
    property bool showPrompts: false

    Component.onCompleted: {
        full.takePendingDrop()
        full.takePendingDropError()
        // Size changed before the first open, or opened before this item
        // existed: once the popup window is there.
        Qt.callLater(full.catchUp)
    }
    // The popup window can come later than this item.
    Window.onWindowChanged: full.catchUp()

    // Only while open and laid out, so the window's padding is right; a
    // closed popup catches up when it opens (onExpandedChanged).
    function catchUp() {
        if (!root.expanded || full.width <= 0)
            return
        if (root.popupSizePending)
            full.applyPopupSize()
        full.fitSplit(full.splitShown)
    }

    Layout.minimumWidth: Kirigami.Units.gridUnit * 18
    Layout.minimumHeight: Kirigami.Units.gridUnit * 15
    Layout.preferredWidth: full.popupSize.width
    Layout.preferredHeight: full.popupSize.height

    // Split view widens the popup window; hiding split (Split off, another
    // tab, Ollama) puts it back to the width it had before. Plasma keeps the
    // popup at the size it last closed at, so the preferred size above only
    // counts the first time the popup opens.
    // Only the panel popup (an AppletPopup) is resized, never a desktop view.
    property int widthBeforeSplit: 0
    // The popup was open this session (fitSplit's first-open repair).
    property bool openedOnce: false

    // Settings → General → Size: resize the panel popup to the new size
    // (Plasma would otherwise keep the size it last closed at). With split
    // on it gets the split width, and turning split off goes to the new
    // Chat width.
    function applyPopupSize() {
        var popup = full.Window.window
        if (!popup || String(popup).indexOf("AppletPopup") < 0)
            return
        root.popupSizePending = false
        var paddingWidth = Math.max(0, popup.width - full.width)
        var paddingHeight = Math.max(0, popup.height - full.height)
        var split = full.splitShown
        var size = ChatSites.popupSize(split ? "split" : full.onChat ? "chat" : "usage",
            Kirigami.Units.gridUnit, Screen.width, Screen.height, root.popupScale)
        full.widthBeforeSplit = split
            ? ChatSites.popupSize("chat", Kirigami.Units.gridUnit, Screen.width, Screen.height,
                                  root.popupScale).width + paddingWidth
            : 0
        popup.width = size.width + paddingWidth
        popup.height = size.height + paddingHeight
    }

    // The width decisions are ChatSites.splitWidthStep's. On the first open
    // of the session it also repairs a width Plasma saved at split width
    // (closing hides the window, and saves its size, before narrowing).
    // A window not laid out yet has an odd padding: then nothing widens and
    // the first open isn't used up; it is tried once more, later.
    function fitSplit(on, retried) {
        var popup = full.Window.window
        if (!popup || String(popup).indexOf("AppletPopup") < 0)
            return
        var size = function (tab) {
            return ChatSites.popupSize(tab, Kirigami.Units.gridUnit, Screen.width, Screen.height,
                                       root.popupScale).width
        }
        var step = ChatSites.splitWidthStep({
            show: on === true,
            popupWidth: popup.width,
            padding: popup.width - full.width,
            maxPadding: Kirigami.Units.gridUnit * 4,
            splitWidth: size("split"),
            normalWidth: size(full.onChat ? "chat" : "usage"),
            before: full.widthBeforeSplit,
            repair: root.expanded && !full.openedOnce && !full.splitShown
        })
        if (step.wait === true) {
            if (retried !== true)
                Qt.callLater(full.fitSplitAgain)
            return
        }
        if (root.expanded)
            full.openedOnce = true
        full.widthBeforeSplit = step.before
        if (step.width > 0)
            popup.width = step.width
    }

    // fitSplit's one retry, for the state by then.
    function fitSplitAgain() {
        full.fitSplit(root.expanded && full.splitShown, true)
    }

    onSplitShownChanged: full.fitSplit(root.expanded && full.splitShown)

    Connections {
        target: root
        function onPopupSizePendingChanged() {
            if (root.popupSizePending)
                full.applyPopupSize()
        }
        function onExpandedChanged() {
            // Closing narrows the popup; opening with split shown widens it
            // again. The first open also checks the saved width.
            if (full.splitShown || full.widthBeforeSplit > 0 || (root.expanded && !full.openedOnce))
                full.fitSplit(root.expanded && full.splitShown)
            if (root.expanded && root.popupSizePending)
                full.applyPopupSize()
            if (root.expanded && full.onOllama)
                ollamaView.focusLater()
            else if (root.expanded && full.onChat)
                chatView.focusLater()
        }
        // The keyboard shortcut opened Ollama's message box.
        function onOllamaFocusRequested() {
            ollamaView.focusLater()
        }
        function onPendingDropChanged() {
            full.takePendingDrop()
        }
        function onPendingDropErrorChanged() {
            full.takePendingDropError()
        }
        // A hidden Chat tab keeps no web view or saved sign-ins open.
        function onChatShownChanged() {
            if (!root.chatShown)
                chatView.stop()
        }
    }

    header: PlasmaExtras.PlasmoidHeading {
        ColumnLayout {
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing

            RowLayout {
                Layout.fillWidth: true

                Kirigami.Heading {
                    Layout.fillWidth: true
                    visible: !tabBar.visible
                    level: 2
                    text: i18n("Hearthwire")
                    elide: Text.ElideRight
                }
                PlasmaComponents.TabBar {
                    id: tabBar
                    Layout.fillWidth: true
                    visible: full.chatAvailable && root.usageShown

                    Binding on currentIndex {
                        value: full.onChat ? 0 : 1
                    }

                    PlasmaComponents.TabButton {
                        text: i18n("Chat")
                        // Hearthwire's icons, as in Settings (install.sh).
                        icon.name: chatIcon.name
                        onClicked: root.popupTab = "chat"
                        IconChoice {
                            id: chatIcon
                            source: "hearthwire-settings-chat"
                            fallbackName: "dialog-messages"
                        }
                    }
                    PlasmaComponents.TabButton {
                        text: i18n("Usage")
                        icon.name: usageIcon.name
                        onClicked: root.popupTab = "usage"
                        IconChoice {
                            id: usageIcon
                            source: "hearthwire-settings-ai"
                            fallbackName: "speedometer"
                        }
                    }
                }
                PlasmaComponents.ToolButton {
                    icon.name: settingsIcon.name
                    display: QQC2.AbstractButton.IconOnly
                    onClicked: Plasmoid.internalAction("configure").trigger()
                    QQC2.ToolTip.text: i18n("Configure…")
                    QQC2.ToolTip.visible: hovered
                    IconChoice {
                        id: settingsIcon
                        source: "hearthwire-settings-general"
                        fallbackName: "configure"
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                visible: !full.onChat

                PlasmaComponents.Label {
                    Layout.fillWidth: true
                    text: i18n("Show")
                    opacity: 0.65
                }
                QQC2.Button {
                    text: i18n("Left")
                    checkable: true
                    checked: root.usageMode === "remaining"
                    onClicked: root.setUsageMode("remaining")
                }
                QQC2.Button {
                    text: i18n("Used")
                    checkable: true
                    checked: root.usageMode === "used"
                    onClicked: root.setUsageMode("used")
                }
                // Hides the popup; chat pages and conversations stay as they are.
                PlasmaComponents.ToolButton {
                    icon.name: "window-minimize"
                    display: QQC2.AbstractButton.IconOnly
                    onClicked: root.expanded = false
                    QQC2.ToolTip.text: i18n("Minimize")
                    QQC2.ToolTip.visible: hovered
                }
            }

            RowLayout {
                Layout.fillWidth: true
                visible: full.onChat
                spacing: Kirigami.Units.smallSpacing

                SitePicker {
                    id: siteCombo
                    model: root.chatSites
                    currentIndex: root.chatSiteIds.indexOf(root.chatSiteId)
                    onActivated: root.chatSiteId = currentValue
                }
                // Split view: the site of the second pane.
                SitePicker {
                    id: siteComboB
                    objectName: "siteComboB"
                    visible: !full.onOllama && root.chatSplit
                    model: root.chatSplitSites
                    currentIndex: root.chatSplitSites.map(function (site) { return site.id }).indexOf(root.chatSiteIdB)
                    onActivated: root.chatSiteIdB = currentValue
                    Accessible.name: i18n("Second site")
                }
                ModelPicker {
                    id: modelCombo
                    visible: full.onOllama
                    currentIndex: ollamaView.modelIndex
                    onActivated: ollamaView.selectModel(currentValue)
                    Accessible.name: i18n("Model")
                }
                // Compare: model B, answering after A.
                ModelPicker {
                    id: modelComboB
                    objectName: "modelComboB"
                    visible: full.onOllama && ollamaView.comparing
                    currentIndex: ollamaView.modelIndexB
                    onActivated: ollamaView.selectModelB(currentValue)
                    Accessible.name: i18n("Second model")
                }
                PlasmaComponents.ToolButton {
                    icon.name: "view-refresh"
                    display: QQC2.AbstractButton.IconOnly
                    visible: full.onOllama
                    enabled: !ollamaView.busy
                    onClicked: ollamaView.reloadModels()
                    QQC2.ToolTip.text: i18n("Reload models")
                    QQC2.ToolTip.visible: hovered
                }
                PlasmaComponents.ToolButton {
                    objectName: "promptsButton"
                    icon.name: "bookmarks"
                    display: QQC2.AbstractButton.IconOnly
                    checked: full.showPrompts
                    text: i18n("Prompts")
                    onClicked: full.showPrompts = !full.showPrompts
                    QQC2.ToolTip.text: text
                    QQC2.ToolTip.visible: hovered
                }
                PlasmaComponents.ToolButton {
                    objectName: "personaButton"
                    icon.name: "user-identity"
                    display: QQC2.AbstractButton.IconOnly
                    visible: full.onOllama
                    checked: ollamaView.editingPersona
                    text: i18n("Personality")
                    onClicked: ollamaView.editingPersona = !ollamaView.editingPersona
                    QQC2.ToolTip.text: text
                    QQC2.ToolTip.visible: hovered
                }
                PlasmaComponents.ToolButton {
                    objectName: "compareButton"
                    icon.name: "view-split-left-right"
                    display: QQC2.AbstractButton.IconOnly
                    visible: full.onOllama
                    enabled: !ollamaView.busy
                    checked: ollamaView.comparing
                    text: i18n("Compare two models")
                    onClicked: ollamaView.setComparing(!ollamaView.comparing)
                    QQC2.ToolTip.text: text
                    QQC2.ToolTip.visible: hovered
                }
                // Split view: a second site next to the first (runtime only).
                PlasmaComponents.ToolButton {
                    objectName: "splitButton"
                    icon.name: "view-split-left-right"
                    display: QQC2.AbstractButton.IconOnly
                    visible: !full.onOllama
                    // Needs at least two enabled web sites.
                    enabled: root.chatSplit || root.chatSplitSites.length >= 2
                    checked: root.chatSplit
                    text: i18n("Split")
                    onClicked: root.setChatSplit(!root.chatSplit)
                    QQC2.ToolTip.text: enabled ? i18n("Show two sites side by side")
                        : i18n("Enable a second chat site in Settings → Chat to use split view")
                    QQC2.ToolTip.visible: hovered
                }
                PlasmaComponents.ToolButton {
                    icon.name: "go-previous"
                    display: QQC2.AbstractButton.IconOnly
                    visible: !full.onOllama
                    enabled: chatView.canGoBack
                    onClicked: chatView.goBack()
                    QQC2.ToolTip.text: i18n("Back")
                    QQC2.ToolTip.visible: hovered
                }
                PlasmaComponents.ToolButton {
                    icon.name: "view-refresh"
                    display: QQC2.AbstractButton.IconOnly
                    visible: !full.onOllama
                    enabled: chatView.available
                    onClicked: chatView.reload()
                    QQC2.ToolTip.text: i18n("Reload page")
                    QQC2.ToolTip.visible: hovered
                }
                PlasmaComponents.ToolButton {
                    icon.name: "go-home"
                    display: QQC2.AbstractButton.IconOnly
                    visible: !full.onOllama
                    enabled: chatView.available
                    onClicked: chatView.home()
                    QQC2.ToolTip.text: i18n("Home")
                    QQC2.ToolTip.visible: hovered
                }
                PlasmaComponents.ToolButton {
                    icon.name: "internet-web-browser"
                    display: QQC2.AbstractButton.IconOnly
                    visible: !full.onOllama
                    enabled: chatView.canOpenExternally
                    onClicked: chatView.openExternally()
                    QQC2.ToolTip.text: i18n("Open in browser")
                    QQC2.ToolTip.visible: hovered
                }
                PlasmaComponents.ToolButton {
                    icon.name: "window-minimize"
                    display: QQC2.AbstractButton.IconOnly
                    onClicked: root.expanded = false
                    QQC2.ToolTip.text: i18n("Minimize")
                    QQC2.ToolTip.visible: hovered
                }
                PlasmaComponents.ToolButton {
                    icon.name: "object-locked"
                    display: QQC2.AbstractButton.IconOnly
                    visible: !full.onOllama && chatView.persistentActive
                    onClicked: chatView.lockSaved()
                    QQC2.ToolTip.text: i18n("Lock saved sign-ins")
                    QQC2.ToolTip.visible: hovered
                }
                PlasmaComponents.ToolButton {
                    icon.name: "edit-clear-history"
                    display: QQC2.AbstractButton.IconOnly
                    visible: !full.onOllama
                    enabled: chatView.available
                    onClicked: chatView.confirmingClear = true
                    QQC2.ToolTip.text: i18n("Clear chat data")
                    QQC2.ToolTip.visible: hovered
                }
                PlasmaComponents.ToolButton {
                    icon.name: "edit-clear-history"
                    display: QQC2.AbstractButton.IconOnly
                    visible: full.onOllama
                    enabled: ollamaView.hasConversation
                    onClicked: ollamaView.confirmingClear = true
                    QQC2.ToolTip.text: i18n("Clear conversation")
                    QQC2.ToolTip.visible: hovered
                }
            }
        }
    }

    contentItem: ColumnLayout {
        spacing: 0

        // Saved and this session's prompts, over either chat.
        PromptLibraryPanel {
            id: libraryPanel
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.largeSpacing
            visible: full.onChat && full.showPrompts
            items: root.promptItems
            saved: root.libraryState === "ready"
            libraryState: root.libraryState
            error: root.libraryError
            encryptedMode: root.chatStorageMode === "encrypted"
            forOllama: full.onOllama
            busy: root.libraryOp !== "" || root.libraryQueue.length > 0
            onUseRequested: (text) => ollamaView.insertPrompt(text)
            onPersonaRequested: (entry) => {
                ollamaView.editingPersona = true
                ollamaView.choosePersona(entry)
            }
            onAddRequested: (kind) => root.libraryRequest("add", { kind: kind })
            onReplaceRequested: (id) => root.libraryRequest("replace", { id: id })
            onRemoveRequested: (id) => root.libraryRequest("remove", { id: id })
            onSessionAddRequested: (kind, text) => root.addSessionItem(kind, text)
            onSessionRemoveRequested: (id) => root.removeSessionItem(id)
            onCloseRequested: full.showPrompts = false
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: full.onChat ? 0 : 1
            // No tab's content paints over the header and its tab bar.
            clip: true

            StackLayout {
                currentIndex: root.chatSiteId === "ollama" ? 1 : 0

                ChatView {
                    id: chatView
                    siteIds: root.chatWebSiteIds
                    siteId: root.chatWebSiteId
                    customUrls: root.chatCustomUrls
                    appletId: Math.max(0, root.chatAppletId)
                    // Only while the popup is open and a web site is shown, so no
                    // web engine starts early or for Ollama alone.
                    current: full.onChat && root.expanded && root.chatSiteId !== "ollama"
                    storageMode: root.chatStorageMode
                    storageReady: root.chatStorageReady
                    storagePath: root.chatProfilePath
                    profileName: root.chatProfileName
                    card: root.chatCard
                    missingTools: root.chatVaultMissing
                    installDistro: root.installDistro
                    unlockMethod: root.chatUnlockMethod
                    walletChosen: root.chatUnlockSetting === "wallet" && root.chatVaultWallet !== "unavailable"
                walletNotApplied: root.chatWalletNotApplied
                    storageNotice: root.chatStorageNotice
                    autoLockMinutes: root.chatAutoLockMinutes
                    storageBusy: root.chatStorageBusy || root.chatDialogOpen
                    zoomMap: root.chatZoom
                    onStorageRequest: (action) => root.chatStorageRequest(action)
                    splitActive: root.chatSplit
                    siteIdB: root.chatSiteIdB
                    // The pane in use (split view: the one last focused).
                    onZoomRequested: (direction) => root.stepSiteZoom(chatView.zoomSiteId, direction)
                    onSiteZoomRequested: (siteId, factor) => root.setSiteZoom(siteId, factor)
                }

                OllamaChatView {
                    id: ollamaView
                    current: full.onOllama && root.expanded
                    siteEnabled: root.chatShown && root.chatSiteIds.indexOf("ollama") >= 0
                    address: root.chatOllamaAddress
                    appletId: Math.max(0, root.chatAppletId)
                    textScale: SettingsLogic.zoomFor(root.chatZoom, "ollama")
                    libraryItems: root.promptItems
                    libraryPersonas: root.libraryPersonas
                    libraryReady: root.libraryState === "ready"
                libraryOpen: root.libraryAvailable
                    onZoomRequested: (direction) => root.stepSiteZoom("ollama", direction)
                    onFileDropped: (hex) => root.readDroppedFile(hex)
                    onPersonaDefaultChosen: (model, id) => root.libraryRequest("set-persona",
                        { model: model, id: id > 0 ? id : null })
                }
            }

            UsageView {}
        }
    }

    Binding {
        target: root
        property: "chatDialogOpen"
        // Also while a helper passphrase window or the library's text window
        // (kdialog) is open, so the popup stays.
        value: chatView.dialogOpen || root.chatVaultPrompting
            || root.libraryOp === "add" || root.libraryOp === "replace"
    }

    footer: Item {
        visible: !full.onChat
        implicitHeight: footerRow.implicitHeight + Kirigami.Units.smallSpacing * 2

        Kirigami.Separator {
            anchors {
                left: parent.left
                right: parent.right
                top: parent.top
            }
        }
        RowLayout {
            id: footerRow
            anchors {
                fill: parent
                leftMargin: Kirigami.Units.largeSpacing
                rightMargin: Kirigami.Units.largeSpacing
                topMargin: Kirigami.Units.smallSpacing
                bottomMargin: Kirigami.Units.smallSpacing
            }
            // The update time and Refresh sit at the top of the Usage tab.
            Item {
                Layout.fillWidth: true
            }
            PlasmaComponents.Label {
                textFormat: Text.PlainText
                text: root.usageMode === "used" ? i18n("Used") : i18n("Left")
                opacity: 0.6
                font: Kirigami.Theme.smallFont
            }
        }
    }
}
