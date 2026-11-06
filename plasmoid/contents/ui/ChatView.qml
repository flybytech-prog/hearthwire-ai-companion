import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.extras as PlasmaExtras
import org.kde.kirigami as Kirigami
import "ChatStorage.js" as ChatStorage
import "OllamaChat.js" as OllamaChat

// Chat tab body. Qt WebEngine is only reached through the Loader below, so
// the widget keeps working (with a hint) when the module is missing, and no
// web engine starts until the Chat tab is first shown.
//
// With "Stay signed in" the web view waits behind a card until main.qml has
// verified the encrypted folder is unlocked and prepared this widget's
// profile folder. The profile kind is fixed when the view is created; any
// change destroys the view and builds a new one.
ColumnLayout {
    id: chatView

    property var siteIds: []
    property string siteId: ""
    // Validated {siteId: url} custom addresses; runtime only.
    property var customUrls: ({})
    // True while the Chat tab is shown in the open popup.
    property bool current: false
    // Only makes the Local owner check's helper source name unique.
    property int appletId: 0

    // Saved sign-ins, all runtime state owned by main.qml.
    property string storageMode: "memory"
    // main.qml: the helper verified the unlocked folder and prepared it.
    property bool storageReady: false
    property string storagePath: ""
    property string profileName: ""
    property var card: ({view: "web", message: ""})
    property var missingTools: []
    // "wallet" when Unlock uses KDE Wallet (chosen and set up), else "passphrase".
    property string unlockMethod: "passphrase"
    // KDE Wallet is chosen in the settings and usable: its key can be set up
    // again from the card.
    property bool walletChosen: false
    // A KDE Wallet key is set up, but Passphrase is chosen (the settings
    // were closed without Apply): said on the card, never used.
    property bool walletNotApplied: false
    // Message code shown in memory mode too (e.g. the old folder is in use).
    property string storageNotice: ""
    // Lock automatically (minutes, 0 = never) and whether main.qml is running
    // a helper step or waiting for a passphrase.
    property int autoLockMinutes: 0
    property bool storageBusy: false
    // Overridable by tests only.
    property url webSource: Qt.resolvedUrl("ChatWebView.qml")
    // Per-site zoom {siteId: factor}, owned by main.qml.
    property var zoomMap: ({})
    // Split view (runtime only): a second pane shows siteIdB.
    property bool splitActive: false
    property string siteIdB: ""

    // create, unlock, private, lock, auto-lock, retry, held-open, clear-saved,
    // open, recheck, dismiss-notice, saved-session
    signal storageRequest(string action)
    // Ctrl+= / Ctrl+- / Ctrl+0 on the site shown: +1, -1 or 0 (reset).
    signal zoomRequested(int direction)
    // Ctrl+wheel in a page: store factor (a ZOOM_STEPS value) for siteId.
    signal siteZoomRequested(string siteId, real factor)

    property bool started: false
    property bool clearing: false
    property bool confirmingClear: false
    // Inline confirmation on the damaged-folder card.
    property bool confirmingDelete: false
    // Profile the current web view was built with; "" when there is none.
    property string builtProfile: ""

    readonly property bool encrypted: ChatStorage.normalizeMode(chatView.storageMode) === "encrypted"
    // The only way to a persistent profile: encrypted mode, a verified and
    // prepared folder, and a real path and name.
    readonly property bool persistentReady: chatView.encrypted && chatView.storageReady
        && chatView.storagePath !== "" && chatView.profileName !== ""
    readonly property string profileKey: chatView.persistentReady
        ? "saved:" + chatView.profileName : "private"
    readonly property bool webWanted: chatView.started && !chatView.clearing
        && chatView.card.view === "web"
    readonly property var web: webLoader.status === Loader.Ready ? webLoader.item : null
    readonly property bool persistentActive: !!chatView.web && chatView.web.staySignedIn === true
    readonly property bool available: chatView.web !== null
    readonly property bool dialogOpen: !!chatView.web && chatView.web.dialogOpen
    readonly property bool canGoBack: !!chatView.web && chatView.web.canGoBack
    readonly property bool canOpenExternally: !!chatView.web && chatView.web.canOpenExternally
    // The site of the pane the user works in (the zoom keys act on it).
    readonly property string zoomSiteId: chatView.web && typeof chatView.web.activeSiteId === "string"
        ? chatView.web.activeSiteId : chatView.siteId
    // Local web UI is shown in either pane: its owner problems and load
    // failures are said whichever pane has the focus.
    readonly property bool localSite: chatView.siteId === "local"
        || (!!chatView.web && chatView.web.splitShown === true && chatView.siteIdB === "local")
    // Split is on but the popup is too narrow for two pages side by side.
    readonly property bool splitHint: chatView.splitActive && !!chatView.web && chatView.web.splitShown === false
    // Idle = the saved web chat is open but not shown (popup closed, Usage or
    // Ollama shown). idleSince is the wall-clock time it was last shown, so
    // time asleep counts too; 0 while not idle.
    readonly property bool autoLockArmed: chatView.persistentActive && !chatView.current
        && ChatStorage.autoLockInterval(chatView.autoLockMinutes) > 0
    property double idleSince: 0
    // The idle time ran out while main.qml was busy: lock once it is done.
    property bool autoLockDue: false

    spacing: 0

    function goBack() {
        if (chatView.web)
            chatView.web.goBack()
    }

    function reload() {
        if (chatView.web)
            chatView.web.reload()
    }

    function home() {
        if (chatView.web)
            chatView.web.home()
    }

    function openExternally() {
        if (chatView.web)
            chatView.web.openExternally()
    }

    function focusView() {
        if (chatView.web && chatView.current)
            chatView.web.focusView()
    }

    function focusLater() {
        Qt.callLater(chatView.focusView)
    }

    // Destroying the view tree destroys the off-the-record profile with it,
    // which drops every cookie, cache entry and site storage of all sites.
    // With saved sign-ins main.qml also deletes the profile folder and locks.
    function clearChatData() {
        chatView.confirmingClear = false
        var saved = chatView.persistentActive
        if (chatView.web) {
            chatView.web.cancelDownload()
            chatView.web.closeOverlay()
        }
        chatView.clearing = true
        chatView.syncLoader()
        if (saved)
            chatView.storageRequest("clear-saved")
        gc()
        Qt.callLater(chatView.finishClear)
    }

    function lockSaved() {
        if (!chatView.persistentActive)
            return
        if (chatView.web) {
            chatView.web.cancelDownload()
            chatView.web.closeOverlay()
        }
        chatView.storageRequest("lock")
    }

    // Settings → General hid the Chat tab: saved sign-ins are locked as with
    // Lock (Lock automatically lives here) and the web view is dropped.
    // Showing Chat again starts afresh.
    function stop() {
        if (!chatView.started)
            return
        if (chatView.web) {
            chatView.web.cancelDownload()
            chatView.web.closeOverlay()
        }
        if (chatView.persistentActive)
            chatView.storageRequest("lock")
        chatView.started = false
        chatView.confirmingClear = false
        chatView.confirmingDelete = false
        chatView.syncLoader()
        gc()
    }

    function restartIdle() {
        chatView.autoLockDue = false
        chatView.idleSince = chatView.autoLockArmed ? Date.now() : 0
    }

    function checkIdle() {
        var step = ChatStorage.autoLockStep({
            armed: chatView.autoLockArmed,
            minutes: chatView.autoLockMinutes,
            idleSince: chatView.idleSince,
            now: Date.now(),
            busy: chatView.storageBusy || chatView.dialogOpen
        })
        switch (step) {
        case "restart":
            chatView.restartIdle()
            break
        case "wait":
            chatView.autoLockDue = true
            break
        case "lock":
            // Same as the Lock button; main.qml retries a busy folder later.
            chatView.autoLockDue = false
            chatView.web.cancelDownload()
            chatView.web.closeOverlay()
            chatView.storageRequest("auto-lock")
            break
        }
    }

    // Creates, keeps or destroys the web view so it always matches
    // webWanted and profileKey. A different profile is never applied to a
    // live view: the old one is destroyed first and the new one built a
    // moment later.
    function syncLoader() {
        if (!chatView.webWanted) {
            if (webLoader.active) {
                webLoader.active = false
                chatView.builtProfile = ""
            }
            return
        }
        if (webLoader.active) {
            if (chatView.builtProfile === chatView.profileKey)
                return
            webLoader.active = false
            chatView.builtProfile = ""
            gc()
            Qt.callLater(chatView.syncLoader)
            return
        }
        chatView.builtProfile = chatView.profileKey
        webLoader.setSource(chatView.webSource, {
            staySignedIn: chatView.persistentReady,
            storagePath: chatView.persistentReady ? chatView.storagePath : "",
            profileName: chatView.persistentReady ? chatView.profileName : ""
        })
        webLoader.active = true
    }

    function finishClear() {
        gc()
        chatView.clearing = false
        chatView.focusLater()
    }

    // Untrusted file names are shown as plain text, with hidden and control
    // characters made visible (⟦U+202E⟧), so "invoice⟦U+202E⟧fdp.exe" can't
    // pass for a PDF. Long names are shortened in the middle: the end with
    // the real (last) extension always stays.
    function plainName(name) {
        var text = OllamaChat.revealHidden(String(name || ""))
        var dot = text.lastIndexOf(".")
        var tail = Math.min(59, Math.max(28, dot >= 0 ? text.length - dot : 0))
        var head = text.slice(0, 59 - tail)
        var end = text.slice(text.length - tail)
        // Never split a surrogate pair at either cut.
        if (/[\ud800-\udbff]$/.test(head))
            head = head.slice(0, -1)
        if (/^[\udc00-\udfff]/.test(end))
            end = end.slice(1)
        if (text.length > 60)
            text = head + "…" + end
        return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    }

    function storageText(code) {
        switch (code) {
        case "status":
            return i18n("Checking the encrypted folder…")
        case "create":
            return i18n("Creating the encrypted folder… Answer the passphrase window.")
        case "unlock":
            return i18n("Unlocking… Answer the passphrase window.")
        case "unlock-wallet":
            return i18n("Unlocking with KDE Wallet… If KDE Wallet asks for its password, answer its window.")
        case "auto-unlock":
            return i18n("Unlocking with KDE Wallet…")
        case "add-key":
            return i18n("Setting up KDE Wallet… Answer the passphrase window.")
        case "not-set-up":
            return i18n("KDE Wallet has no key for the encrypted folder. Set it up again, or use your passphrase.")
        case "wallet-mismatch":
            return i18n("The key in KDE Wallet no longer opens the encrypted folder. Set it up again, or use your passphrase.")
        case "wallet-disabled":
            return i18n("KDE Wallet is turned off. Use your passphrase instead.")
        case "wallet-failed":
            return i18n("Couldn't get the key from KDE Wallet. Use your passphrase instead.")
        case "wallet-write-failed":
            return i18n("Couldn't save the key in KDE Wallet. Use your passphrase.")
        case "wait":
        case "lock":
            return i18n("Locking the encrypted folder…")
        case "prepare":
        case "keep":
            return i18n("Opening your saved sign-ins…")
        case "remove":
        case "destroy":
            return i18n("Deleting saved sign-ins…")
        case "wrong-passphrase":
            return i18n("Wrong passphrase. Try again.")
        case "busy":
            return i18n("The encrypted folder is busy, perhaps used by another Hearthwire widget. Try again in a moment.")
        case "lock-busy":
            return i18n("The encrypted folder is still in use, perhaps by another Hearthwire widget. It was not locked.")
        case "missing-tool":
            return i18n("A required tool is missing. Install gocryptfs and try again.")
        case "exists":
            return i18n("An encrypted folder already exists. Unlock it instead.")
        case "mount-failed":
            return i18n("Couldn't open the encrypted folder safely.")
        case "prepare-failed":
            return i18n("Couldn't prepare your saved sign-ins.")
        case "remove-failed":
            return i18n("Couldn't delete the saved sign-ins. The encrypted folder was locked anyway.")
        case "cleared":
            return i18n("Chat data cleared. The encrypted folder is locked.")
        case "auto-locked":
            return i18n("Locked automatically.")
        case "damaged":
            return i18n("The encrypted folder is damaged and can't be opened.")
        case "delete-failed":
            return i18n("Couldn't delete the encrypted folder because it is still in use. Close Chat in other Hearthwire widgets, then delete it in Settings → Chat → Advanced.")
        case "":
            return ""
        default:
            return i18n("Something went wrong with the encrypted folder.")
        }
    }

    // Fixed texts only; the Local address is never shown, only its port.
    function localOwnerText(code, port) {
        switch (code) {
        case "":
            return ""
        case "other":
            return i18n("Another user's program is using port %1. Hearthwire won't load anything from it.", port)
        case "not-running":
            return i18n("Nothing is using port %1. Is your local chat server running?", port)
        case "resend":
            return i18n("Checked the program on port %1. Send the form again.", port)
        default:
            return i18n("Couldn't check which program is using port %1. Nothing was loaded.", port)
        }
    }

    function start() {
        if (chatView.started)
            return
        chatView.started = true
        chatView.storageRequest("open")
    }

    onCurrentChanged: {
        if (chatView.current) {
            chatView.start()
            chatView.focusLater()
        }
    }
    onWebWantedChanged: chatView.syncLoader()
    onProfileKeyChanged: chatView.syncLoader()
    onAutoLockArmedChanged: chatView.restartIdle()
    onAutoLockMinutesChanged: chatView.restartIdle()
    onStorageBusyChanged: {
        if (!chatView.storageBusy && chatView.autoLockDue)
            Qt.callLater(chatView.checkIdle)
    }

    // The popup may be created with Chat already shown: start right away.
    Component.onCompleted: {
        if (chatView.current) {
            chatView.start()
            chatView.focusLater()
        }
        chatView.syncLoader()
    }

    // Zoom keys, also while the page has the focus. Ctrl+wheel is Chromium's
    // own; ChatWebView reports it through siteZoomRequested.
    Shortcut {
        sequences: [StandardKey.ZoomIn, "Ctrl+="]
        enabled: chatView.current && chatView.available
        onActivated: chatView.zoomRequested(1)
    }
    Shortcut {
        sequences: [StandardKey.ZoomOut]
        enabled: chatView.current && chatView.available
        onActivated: chatView.zoomRequested(-1)
    }
    Shortcut {
        sequence: "Ctrl+0"
        enabled: chatView.current && chatView.available
        onActivated: chatView.zoomRequested(0)
    }

    Timer {
        id: idleTimer
        interval: Math.max(1000, ChatStorage.autoLockCheckInterval(chatView.autoLockMinutes))
        repeat: true
        running: chatView.autoLockArmed
        onTriggered: chatView.checkIdle()
    }

    Connections {
        target: chatView.web
        ignoreUnknownSignals: true
        function onSiteZoomRequested(siteId, factor) {
            chatView.siteZoomRequested(siteId, factor)
        }
        // A failing page may mean the folder went away: let main.qml check.
        function onPageFailedChanged() {
            if (chatView.web && chatView.web.pageFailed && chatView.persistentActive)
                chatView.storageRequest("recheck")
        }
    }

    PlasmaComponents.ProgressBar {
        Layout.fillWidth: true
        Layout.preferredHeight: Math.round(Kirigami.Units.smallSpacing / 2) || 1
        visible: !!chatView.web && chatView.web.loading
        from: 0
        to: 1
        value: chatView.web ? chatView.web.loadProgress : 0
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        visible: chatView.confirmingClear
        type: Kirigami.MessageType.Warning
        text: chatView.persistentActive
            ? i18n("Clear chat data? This signs you out of all chat sites, deletes your saved sign-ins and locks the encrypted folder.")
            : i18n("Clear chat data? This signs you out of all chat sites.")
        actions: [
            Kirigami.Action {
                text: i18n("Clear")
                icon.name: "edit-clear-history"
                onTriggered: chatView.clearChatData()
            },
            Kirigami.Action {
                text: i18n("Cancel")
                icon.name: "dialog-cancel"
                onTriggered: chatView.confirmingClear = false
            }
        ]
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        visible: chatView.storageNotice !== ""
        type: Kirigami.MessageType.Warning
        text: chatView.storageText(chatView.storageNotice)
        actions: [
            Kirigami.Action {
                text: i18n("Dismiss")
                icon.name: "dialog-close"
                onTriggered: chatView.storageRequest("dismiss-notice")
            }
        ]
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        visible: chatView.started && chatView.encrypted && !chatView.persistentReady
            && chatView.card.view === "web"
        type: Kirigami.MessageType.Information
        text: i18n("Private session: sign-ins won't be saved this time.")
        actions: [
            Kirigami.Action {
                text: i18n("Use saved sign-ins…")
                icon.name: "unlock"
                onTriggered: chatView.storageRequest("saved-session")
            }
        ]
    }

    Kirigami.InlineMessage {
        objectName: "splitHint"
        Layout.fillWidth: true
        visible: chatView.splitHint && chatView.card.view === "web"
        type: Kirigami.MessageType.Information
        text: i18n("Use the Large popup size for split view")
    }

    Kirigami.InlineMessage {
        id: localOwnerMessage
        objectName: "localOwnerMessage"
        Layout.fillWidth: true
        readonly property string code: chatView.web ? chatView.web.localOwnerProblem : ""
        visible: chatView.localSite && code !== ""
        type: code === "resend" ? Kirigami.MessageType.Information
            : code === "not-running" ? Kirigami.MessageType.Warning
            : Kirigami.MessageType.Error
        text: chatView.localOwnerText(code, chatView.web ? chatView.web.localOwnerPort : 0)
        actions: [
            Kirigami.Action {
                visible: localOwnerMessage.code !== "resend"
                text: i18n("Retry")
                icon.name: "view-refresh"
                onTriggered: chatView.web.retryLocalOwner()
            },
            Kirigami.Action {
                visible: localOwnerMessage.code === "resend"
                text: i18n("Dismiss")
                icon.name: "dialog-close"
                onTriggered: chatView.web.dismissLocalOwner()
            }
        ]
    }

    // The page has left the site: a script, redirect or form took it to a
    // host outside the site's own, sign-in and custom hosts. The host is
    // ASCII only (look-alike letters show as xn--) and plain text.
    Rectangle {
        id: offSiteNotice
        objectName: "offSiteNotice"
        Layout.fillWidth: true
        readonly property var info: chatView.web ? chatView.web.offSite : ({off: false, host: ""})
        visible: !!chatView.web && info.off === true
        implicitHeight: offSiteRow.implicitHeight + Kirigami.Units.smallSpacing * 2
        color: Kirigami.Theme.neutralBackgroundColor
        border.color: Kirigami.Theme.neutralTextColor
        border.width: 1
        radius: Kirigami.Units.cornerRadius

        RowLayout {
            id: offSiteRow
            anchors {
                left: parent.left
                right: parent.right
                verticalCenter: parent.verticalCenter
                leftMargin: Kirigami.Units.largeSpacing
                rightMargin: Kirigami.Units.smallSpacing
            }
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: "security-medium"
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Kirigami.Units.iconSizes.small
            }
            PlasmaComponents.Label {
                objectName: "offSiteText"
                Layout.fillWidth: true
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                text: offSiteNotice.info.host !== ""
                    ? i18n("You are on %1 — not %2", offSiteNotice.info.host,
                        chatView.web ? chatView.web.activeSiteName : "")
                    : i18n("You are on another site — not %1",
                        chatView.web ? chatView.web.activeSiteName : "")
            }
            PlasmaComponents.ToolButton {
                objectName: "offSiteBack"
                icon.name: "go-home"
                text: i18n("Back to %1", chatView.web ? chatView.web.activeSiteName : "")
                onClicked: chatView.home()
            }
        }
    }

    // A page asked to open an address in the system browser. Nothing opens
    // until Open is clicked; the host is ASCII and plain text.
    Rectangle {
        id: externalPrompt
        objectName: "externalPrompt"
        Layout.fillWidth: true
        readonly property string host: chatView.web ? chatView.web.externalHost : ""
        visible: !!chatView.web && chatView.web.externalUrl !== "" && host !== ""
        implicitHeight: externalRow.implicitHeight + Kirigami.Units.smallSpacing * 2
        color: Kirigami.Theme.neutralBackgroundColor
        border.color: Kirigami.Theme.neutralTextColor
        border.width: 1
        radius: Kirigami.Units.cornerRadius

        RowLayout {
            id: externalRow
            anchors {
                left: parent.left
                right: parent.right
                verticalCenter: parent.verticalCenter
                leftMargin: Kirigami.Units.largeSpacing
                rightMargin: Kirigami.Units.smallSpacing
            }
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: "internet-web-browser"
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Kirigami.Units.iconSizes.small
            }
            PlasmaComponents.Label {
                objectName: "externalText"
                Layout.fillWidth: true
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                text: i18n("Open %1 in your browser?", externalPrompt.host)
            }
            PlasmaComponents.ToolButton {
                objectName: "externalOpen"
                icon.name: "internet-web-browser"
                text: i18n("Open")
                onClicked: chatView.web.acceptExternal()
            }
            PlasmaComponents.ToolButton {
                objectName: "externalCancel"
                icon.name: "dialog-cancel"
                text: i18n("Cancel")
                onClicked: chatView.web.clearExternal()
            }
        }
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        visible: !!chatView.web && chatView.web.pendingDownloadName !== ""
        type: Kirigami.MessageType.Information
        // Wrapped in <p> so the escaped name is always read as rich text.
        // The site (a fixed catalog name, escaped too) says which pane's
        // page asked.
        readonly property string source: chatView.web && chatView.web.pendingDownloadSite
            ? String(chatView.web.pendingDownloadSite).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            : ""
        text: "<p>" + (source !== ""
            ? i18n("Save \"%1\" from %2 to Downloads?",
                chatView.plainName(chatView.web ? chatView.web.pendingDownloadName : ""), source)
            : i18n("Save \"%1\" to Downloads?",
                chatView.plainName(chatView.web ? chatView.web.pendingDownloadName : ""))) + "</p>"
        actions: [
            Kirigami.Action {
                text: i18n("Save")
                icon.name: "document-save"
                onTriggered: chatView.web.saveDownload()
            },
            Kirigami.Action {
                text: i18n("Cancel")
                icon.name: "dialog-cancel"
                onTriggered: chatView.web.cancelDownload()
            }
        ]
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        visible: !!chatView.web && chatView.web.passkeyNotice
        type: Kirigami.MessageType.Information
        text: i18n("Passkeys aren't supported here; choose another sign-in method.")
        actions: [
            Kirigami.Action {
                text: i18n("Dismiss")
                icon.name: "dialog-close"
                onTriggered: chatView.web.passkeyNotice = false
            }
        ]
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        visible: !!chatView.web && chatView.web.pageCrashed
        type: Kirigami.MessageType.Error
        text: i18n("Page crashed")
        actions: [
            Kirigami.Action {
                text: i18n("Reload")
                icon.name: "view-refresh"
                onTriggered: chatView.reload()
            }
        ]
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        visible: !!chatView.web && chatView.web.pageFailed && !chatView.web.pageCrashed
        type: Kirigami.MessageType.Warning
        // The local address itself is never shown here.
        text: chatView.localSite
            ? i18n("Couldn't load. Is your local chat server running? You can change its address in Settings → Chat → Advanced.")
            : i18n("Couldn't load this page.")
        actions: [
            Kirigami.Action {
                text: i18n("Retry")
                icon.name: "view-refresh"
                onTriggered: chatView.reload()
            }
        ]
    }

    Item {
        Layout.fillWidth: true
        Layout.fillHeight: true

        // Only syncLoader() activates this, always through setSource() with
        // the profile as initial properties.
        Loader {
            id: webLoader
            anchors.fill: parent
            active: false
            onLoaded: {
                // customUrls first: the first page load must already use them.
                webLoader.item.appletId = Qt.binding(function () { return chatView.appletId })
                webLoader.item.customUrls = Qt.binding(function () { return chatView.customUrls })
                webLoader.item.zoomMap = Qt.binding(function () { return chatView.zoomMap })
                webLoader.item.siteIds = Qt.binding(function () { return chatView.siteIds })
                webLoader.item.siteId = Qt.binding(function () { return chatView.siteId })
                webLoader.item.siteIdB = Qt.binding(function () { return chatView.siteIdB })
                webLoader.item.splitActive = Qt.binding(function () { return chatView.splitActive })
                chatView.focusLater()
            }
        }

        PlasmaExtras.PlaceholderMessage {
            anchors.centerIn: parent
            width: parent.width - Kirigami.Units.gridUnit * 2
            visible: webLoader.status === Loader.Error && chatView.card.view === "web"
            iconName: "dialog-messages"
            text: i18n("Chat needs Qt WebEngine 6.8 or newer and Qt Quick Dialogs (packages qt6-webengine, qt6-declarative)")
        }

        // Stay signed in: shown instead of the web view until the encrypted
        // folder is unlocked, or the user picks a private session.
        ColumnLayout {
            id: storageCard
            objectName: "storageCard"
            anchors.centerIn: parent
            width: Math.min(parent.width - Kirigami.Units.gridUnit * 2, Kirigami.Units.gridUnit * 26)
            visible: chatView.started && chatView.card.view !== "web"
            spacing: Kirigami.Units.largeSpacing

            readonly property string view: chatView.card.view
            readonly property string message: chatView.storageText(chatView.card.message)

            onViewChanged: chatView.confirmingDelete = false

            PlasmaComponents.BusyIndicator {
                Layout.alignment: Qt.AlignHCenter
                visible: storageCard.view === "busy"
                running: visible
            }
            Kirigami.Icon {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: Kirigami.Units.iconSizes.huge
                Layout.preferredHeight: Kirigami.Units.iconSizes.huge
                visible: storageCard.view !== "busy"
                source: storageCard.view === "install" || storageCard.view === "damaged"
                    ? "dialog-warning" : "object-locked"
            }
            Kirigami.Heading {
                Layout.fillWidth: true
                level: 3
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                visible: storageCard.view !== "busy"
                text: {
                    switch (storageCard.view) {
                    case "create":
                        return i18n("Stay signed in")
                    case "unlock":
                        return i18n("Your saved sign-ins are locked")
                    case "install":
                        return i18n("Stay signed in needs gocryptfs")
                    case "held":
                        return i18n("The encrypted folder is still open")
                    case "damaged":
                        return i18n("The encrypted folder is damaged")
                    default:
                        return i18n("Saved sign-ins aren't available")
                    }
                }
            }
            PlasmaComponents.Label {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                text: {
                    switch (storageCard.view) {
                    case "busy":
                        return storageCard.message
                    case "create":
                        return i18n("Your sign-ins are kept in an encrypted folder. You choose its passphrase now and enter it once per Plasma session. If you forget it, the saved data can't be recovered.")
                    case "unlock":
                        return chatView.unlockMethod === "wallet"
                            ? i18n("Open them with KDE Wallet for this Plasma session.")
                            : i18n("Enter your passphrase to open them for this Plasma session.")
                    case "install":
                        return i18n("The encrypted folder for saved sign-ins needs some tools that aren't installed. Install them with this command, then check again:")
                    case "damaged":
                        return i18n("The encrypted folder is damaged and can't be opened. Delete it to start again with a new one; the sign-ins saved in it are lost.")
                    default:
                        return ""
                    }
                }
                visible: text !== ""
            }
            QQC2.TextField {
                Layout.fillWidth: true
                visible: storageCard.view === "install"
                readOnly: true
                selectByMouse: true
                horizontalAlignment: Text.AlignHCenter
                text: ChatStorage.installCommand(chatView.missingTools)
            }
            PlasmaComponents.Label {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                visible: storageCard.view !== "busy" && storageCard.message !== ""
                color: chatView.card.message === "cleared" || chatView.card.message === "auto-locked"
                    ? Kirigami.Theme.textColor : Kirigami.Theme.negativeTextColor
                text: storageCard.message
            }
            ColumnLayout {
                Layout.alignment: Qt.AlignHCenter
                visible: storageCard.view !== "busy"
                spacing: Kirigami.Units.smallSpacing

                PlasmaComponents.Button {
                    Layout.fillWidth: true
                    visible: storageCard.view === "create"
                    icon.name: "folder-locked"
                    text: i18n("Create encrypted folder…")
                    onClicked: chatView.storageRequest("create")
                }
                PlasmaComponents.Label {
                    objectName: "walletNotAppliedNote"
                    Layout.fillWidth: true
                    visible: storageCard.view === "unlock" && chatView.walletNotApplied
                    wrapMode: Text.WordWrap
                    textFormat: Text.PlainText
                    horizontalAlignment: Text.AlignHCenter
                    opacity: 0.72
                    text: i18n("A KDE Wallet key is set up but not applied. Apply KDE Wallet under Settings → General → Privacy to use it, or remove the key there.")
                }
                PlasmaComponents.Button {
                    objectName: "unlockButton"
                    Layout.fillWidth: true
                    visible: storageCard.view === "unlock"
                    icon.name: "unlock"
                    text: chatView.unlockMethod === "wallet" ? i18n("Unlock with KDE Wallet")
                        : chatView.card.message === "wrong-passphrase" ? i18n("Try again…") : i18n("Unlock…")
                    onClicked: chatView.storageRequest("unlock")
                }
                // The passphrase always works, also when the wallet doesn't (D47).
                PlasmaComponents.Button {
                    objectName: "unlockPassphraseButton"
                    Layout.fillWidth: true
                    visible: storageCard.view === "unlock" && chatView.unlockMethod === "wallet"
                    icon.name: "dialog-password"
                    text: i18n("Use passphrase instead…")
                    onClicked: chatView.storageRequest("unlock-passphrase")
                }
                PlasmaComponents.Button {
                    objectName: "walletSetupButton"
                    Layout.fillWidth: true
                    visible: storageCard.view === "unlock" && chatView.walletChosen
                        && (chatView.card.message === "wallet-mismatch" || chatView.card.message === "not-set-up")
                    icon.name: "configure"
                    text: i18n("Set up KDE Wallet again…")
                    onClicked: chatView.storageRequest("wallet-setup")
                }
                PlasmaComponents.Button {
                    Layout.fillWidth: true
                    visible: storageCard.view === "held"
                    icon.name: "object-locked"
                    text: i18n("Try locking again")
                    onClicked: chatView.storageRequest("lock")
                }
                PlasmaComponents.Button {
                    Layout.fillWidth: true
                    visible: storageCard.view === "held"
                    icon.name: "dialog-messages"
                    text: i18n("Keep using saved sign-ins")
                    onClicked: chatView.storageRequest("saved-session")
                }
                PlasmaComponents.Button {
                    objectName: "deleteDamagedButton"
                    Layout.fillWidth: true
                    visible: storageCard.view === "damaged" && !chatView.confirmingDelete
                    icon.name: "edit-delete"
                    text: i18n("Delete encrypted folder…")
                    onClicked: chatView.confirmingDelete = true
                }
                Kirigami.InlineMessage {
                    objectName: "deleteDamagedConfirm"
                    Layout.fillWidth: true
                    visible: storageCard.view === "damaged" && chatView.confirmingDelete
                    type: Kirigami.MessageType.Warning
                    text: i18n("Delete the encrypted folder? Every sign-in saved in it is lost, for all Hearthwire widgets. This can't be undone.")
                    actions: [
                        Kirigami.Action {
                            text: i18n("Delete")
                            icon.name: "edit-delete"
                            onTriggered: {
                                chatView.confirmingDelete = false
                                chatView.storageRequest("delete-damaged")
                            }
                        },
                        Kirigami.Action {
                            text: i18n("Cancel")
                            icon.name: "dialog-cancel"
                            onTriggered: chatView.confirmingDelete = false
                        }
                    ]
                }
                PlasmaComponents.Button {
                    Layout.fillWidth: true
                    visible: storageCard.view === "retry" || storageCard.view === "install"
                    icon.name: "view-refresh"
                    text: storageCard.view === "install" ? i18n("Check again") : i18n("Try again")
                    onClicked: chatView.storageRequest("retry")
                }
                PlasmaComponents.Button {
                    Layout.fillWidth: true
                    icon.name: "view-private"
                    text: i18n("Use a private session this time")
                    onClicked: chatView.storageRequest("private")
                }
            }
        }
    }
}
