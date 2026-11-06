import QtQuick
import QtTest
import org.kde.kirigami as Kirigami
import "../../plasmoid/contents/ui"

// ChatView with a stub web view: when the web view starts and with which
// profile it is built. Qt WebEngine is never loaded here.
TestCase {
    id: testCase
    name: "ChatView"
    width: 400
    height: 400
    visible: true
    when: windowShown

    // Plasma injects i18n(); a stand-in that fills %1, %2...
    function i18n(text) {
        var result = text
        for (var index = 1; index < arguments.length; index++)
            result = result.replace("%" + index, String(arguments[index]))
        return result
    }

    property var requests: []
    property var builds: []
    // Read by a declared binding, like FullRepresentation's `current:`. A
    // binding that is already true at creation emits no change signal.
    property bool shownAtCreation: false

    Component {
        id: viewComponent
        ChatView {
            anchors.fill: parent
            current: testCase.shownAtCreation
            webSource: Qt.resolvedUrl("ChatWebStub.qml")
            onStorageRequest: (action) => testCase.requests.push(action)
            onWebChanged: {
                if (web)
                    testCase.builds.push({
                        staySignedIn: web.staySignedIn,
                        storagePath: web.storagePath,
                        profileName: web.profileName
                    })
            }
        }
    }

    function init() {
        testCase.shownAtCreation = false
        testCase.requests = []
        testCase.builds = []
    }

    function make(properties) {
        var view = createTemporaryObject(viewComponent, testCase, properties || {})
        verify(view !== null)
        return view
    }

    // The popup is created with Chat already shown: the page must load
    // without a tab switch.
    function test_startsWhenCurrentAtCreation() {
        testCase.shownAtCreation = true
        var view = make()
        verify(view.started)
        tryVerify(function () { return view.web !== null })
        compare(testCase.requests.indexOf("open") >= 0, true)
        compare(testCase.builds.length, 1)
        compare(testCase.builds[0].staySignedIn, false)
    }

    // Plasma may preload the popup while it is closed (current false, as
    // FullRepresentation passes `full.onChat && root.expanded`): no web view
    // may be built inside the hidden popup, only when it is first shown.
    function test_waitsUntilShown() {
        var view = make({current: false})
        wait(50)
        verify(!view.started)
        compare(view.web, null)
        view.current = true
        tryVerify(function () { return view.web !== null })
        compare(testCase.requests, ["open"])
    }

    // Settings → General hid the Chat tab: the web view goes, nothing comes
    // back until Chat is shown again, and that starts afresh.
    function test_stopDropsTheWebView() {
        var view = make({current: true})
        tryVerify(function () { return view.web !== null })
        view.current = false
        view.stop()
        verify(!view.started)
        compare(view.web, null)
        wait(50)
        compare(view.web, null)
        // No saved sign-ins were open: nothing to lock.
        compare(testCase.requests, ["open"])
        view.current = true
        tryVerify(function () { return view.web !== null })
        compare(testCase.requests, ["open", "open"])
    }

    function test_stopLocksSavedSignIns() {
        var view = make({
            current: true,
            storageMode: "encrypted",
            storageReady: true,
            storagePath: "/run/user/1/hearthwire/vault/web/applet-1-g0",
            profileName: "applet-1-g0",
            card: {view: "web", message: ""}
        })
        tryVerify(function () { return view.persistentActive })
        view.current = false
        view.stop()
        compare(view.web, null)
        compare(testCase.requests, ["open", "lock"])
    }

    function test_stopBeforeStartDoesNothing() {
        var view = make({current: false})
        view.stop()
        verify(!view.started)
        compare(testCase.requests, [])
    }

    function test_encryptedCardHidesWebUntilReady() {
        var view = make({
            current: true,
            storageMode: "encrypted",
            card: {view: "unlock", message: ""}
        })
        verify(view.started)
        wait(50)
        compare(view.web, null)
        var card = findChild(view, "storageCard")
        verify(card !== null)
        verify(card.visible)

        view.storagePath = "/run/user/1/hearthwire/vault/web/applet-1-g0"
        view.profileName = "applet-1-g0"
        view.storageReady = true
        view.card = {view: "web", message: ""}
        tryVerify(function () { return view.web !== null })
        compare(testCase.builds.length, 1)
        compare(testCase.builds[0], {
            staySignedIn: true,
            storagePath: "/run/user/1/hearthwire/vault/web/applet-1-g0",
            profileName: "applet-1-g0"
        })
        verify(view.persistentActive)
        verify(!card.visible)
    }

    function test_readyWithoutPathStaysPrivate() {
        var view = make({
            current: true,
            storageMode: "encrypted",
            storageReady: true,
            storagePath: "",
            profileName: "applet-1-g0",
            card: {view: "web", message: ""}
        })
        tryVerify(function () { return view.web !== null })
        compare(testCase.builds[0].staySignedIn, false)
        compare(testCase.builds[0].storagePath, "")
        compare(testCase.builds[0].profileName, "")
    }

    function test_memoryModeIgnoresReadyFlag() {
        var view = make({
            current: true,
            storageMode: "folder",
            storageReady: true,
            storagePath: "/x/applet-1-g0",
            profileName: "applet-1-g0"
        })
        tryVerify(function () { return view.web !== null })
        compare(testCase.builds[0].staySignedIn, false)
    }

    function test_profileChangeRebuildsTheView() {
        var view = make({
            current: true,
            storageMode: "encrypted",
            storageReady: true,
            storagePath: "/r/hearthwire/vault/web/applet-1-g0",
            profileName: "applet-1-g0"
        })
        tryVerify(function () { return view.web !== null })
        var first = view.web
        compare(first.staySignedIn, true)
        // Lock: not ready any more → the saved profile is destroyed and a
        // private one built in its place, never switched live.
        view.storageReady = false
        tryVerify(function () { return view.web !== null && view.web !== first })
        compare(view.web.staySignedIn, false)
        compare(testCase.builds.length, 2)
        compare(testCase.builds[1].staySignedIn, false)
    }

    function test_cardTearsDownTheView() {
        var view = make({current: true, storageMode: "encrypted"})
        tryVerify(function () { return view.web !== null })
        view.card = {view: "busy", message: "lock"}
        tryVerify(function () { return view.web === null })
        view.card = {view: "web", message: ""}
        tryVerify(function () { return view.web !== null })
        compare(testCase.builds.length, 2)
    }

    function test_clearRebuildsAndAsksToDeleteSavedData() {
        var view = make({
            current: true,
            storageMode: "encrypted",
            storageReady: true,
            storagePath: "/r/hearthwire/vault/web/applet-1-g0",
            profileName: "applet-1-g0"
        })
        tryVerify(function () { return view.web !== null })
        view.clearChatData()
        verify(testCase.requests.indexOf("clear-saved") >= 0)
        tryVerify(function () { return view.web !== null && !view.clearing })
        compare(testCase.builds.length, 2)
    }

    function test_clearInPrivateSessionDoesNotTouchSavedData() {
        var view = make({current: true})
        tryVerify(function () { return view.web !== null })
        view.clearChatData()
        compare(testCase.requests.indexOf("clear-saved"), -1)
        tryVerify(function () { return view.web !== null && !view.clearing })
    }

    function test_lockOnlyWithSavedProfile() {
        var view = make({current: true})
        tryVerify(function () { return view.web !== null })
        view.lockSaved()
        compare(testCase.requests.indexOf("lock"), -1)
    }

    function test_cardButtonsRequestActions() {
        var view = make({
            current: true,
            storageMode: "encrypted",
            card: {view: "create", message: ""}
        })
        var card = findChild(view, "storageCard")
        verify(card.visible)
        view.card = {view: "unlock", message: "wrong-passphrase"}
        compare(card.message, "Wrong passphrase. Try again.")
    }

    function test_damagedCardDeletesOnlyAfterConfirming() {
        var view = make({
            current: true,
            storageMode: "encrypted",
            card: {view: "damaged", message: ""}
        })
        var card = findChild(view, "storageCard")
        verify(card.visible)
        var button = findChild(view, "deleteDamagedButton")
        var confirm = findChild(view, "deleteDamagedConfirm")
        verify(button !== null && confirm !== null)
        verify(button.visible)
        verify(!confirm.visible)
        compare(testCase.builds.length, 0)
        button.clicked()
        verify(!button.visible)
        verify(confirm.visible)
        compare(testCase.requests.indexOf("delete-damaged"), -1)
        // Cancel asks for nothing.
        confirm.actions[1].trigger()
        verify(!confirm.visible)
        compare(testCase.requests.indexOf("delete-damaged"), -1)
        button.clicked()
        confirm.actions[0].trigger()
        verify(!confirm.visible)
        verify(testCase.requests.indexOf("delete-damaged") >= 0)
        // Leaving the damaged card forgets a pending confirmation.
        button.clicked()
        view.card = {view: "busy", message: "destroy"}
        view.card = {view: "damaged", message: ""}
        verify(button.visible)
        verify(!confirm.visible)
        view.card = {view: "damaged", message: "busy"}
        compare(card.message, "The encrypted folder is busy, perhaps used by another Hearthwire widget. Try again in a moment.")
    }

    // --- Lock automatically ---------------------------------------------

    // A saved web chat, built while shown (a hidden view never starts) and
    // then hidden when `current: false` is asked for.
    function makeSaved(properties) {
        var extra = Object.assign({}, properties || {})
        var shown = extra.current !== false
        delete extra.current
        var view = make(Object.assign({
            current: true,
            storageMode: "encrypted",
            storageReady: true,
            storagePath: "/r/hearthwire/vault/web/applet-1-g0",
            profileName: "applet-1-g0",
            autoLockMinutes: 1
        }, extra))
        tryVerify(function () { return view.persistentActive })
        view.current = shown
        return view
    }

    function autoLocks() {
        return testCase.requests.filter(function (action) { return action === "auto-lock" }).length
    }

    function test_autoLockNeverWhileChatIsShown() {
        var view = makeSaved()
        verify(!view.autoLockArmed)
        compare(view.idleSince, 0)
        view.idleSince = Date.now() - 3600000
        view.checkIdle()
        compare(autoLocks(), 0)
    }

    function test_autoLockAfterTheIdleTime() {
        var view = makeSaved()
        var before = Date.now()
        view.current = false
        verify(view.autoLockArmed)
        verify(view.idleSince >= before && view.idleSince <= Date.now())
        view.checkIdle()
        compare(autoLocks(), 0)
        // One minute later (wall clock, so time asleep counts too).
        view.idleSince = Date.now() - 60000
        view.checkIdle()
        compare(autoLocks(), 1)
        compare(testCase.requests.indexOf("lock"), -1)
    }

    function test_showingChatRestartsTheIdleTime() {
        var view = makeSaved({current: false})
        view.idleSince = Date.now() - 59000
        view.current = true
        compare(view.idleSince, 0)
        view.current = false
        verify(Date.now() - view.idleSince < 1000)
        view.checkIdle()
        compare(autoLocks(), 0)
    }

    function test_autoLockWaitsForHelperSteps() {
        var view = makeSaved({current: false, storageBusy: true})
        view.idleSince = Date.now() - 60000
        view.checkIdle()
        compare(autoLocks(), 0)
        verify(view.autoLockDue)
        // A dialog of the page holds it off as well.
        view.web.dialogOpen = true
        view.storageBusy = false
        wait(50)
        compare(autoLocks(), 0)
        view.web.dialogOpen = false
        view.checkIdle()
        compare(autoLocks(), 1)
        verify(!view.autoLockDue)
    }

    function test_autoLockFiresOnceHelperIsDone() {
        var view = makeSaved({current: false, storageBusy: true})
        view.idleSince = Date.now() - 60000
        view.checkIdle()
        view.storageBusy = false
        tryVerify(function () { return autoLocks() === 1 })
    }

    function test_autoLockOffForNeverAndPrivateSessions() {
        var never = makeSaved({current: false, autoLockMinutes: 0})
        verify(!never.autoLockArmed)
        never.idleSince = Date.now() - 86400000
        never.checkIdle()
        var odd = makeSaved({current: false, autoLockMinutes: 7})
        verify(!odd.autoLockArmed)
        var memory = make({current: true, autoLockMinutes: 1})
        tryVerify(function () { return memory.web !== null })
        memory.current = false
        verify(!memory.autoLockArmed)
        memory.idleSince = Date.now() - 86400000
        memory.checkIdle()
        compare(autoLocks(), 0)
    }

    function test_changingTheSettingRestartsTheIdleTime() {
        var view = makeSaved({current: false})
        view.idleSince = Date.now() - 60000
        view.autoLockMinutes = 5
        verify(Date.now() - view.idleSince < 1000)
        view.checkIdle()
        compare(autoLocks(), 0)
    }

    function test_lockedAutomaticallyCard() {
        var view = make({
            current: true,
            storageMode: "encrypted",
            card: {view: "unlock", message: "auto-locked"}
        })
        var card = findChild(view, "storageCard")
        verify(card.visible)
        compare(card.message, "Locked automatically.")
    }

    // --- Local owner check messages (M2) -------------------------------------

    function test_localOwnerMessages() {
        var view = make({current: true, siteId: "local", siteIds: ["local", "claude"]})
        tryVerify(function () { return view.web !== null })
        var message = findChild(view, "localOwnerMessage")
        verify(!message.visible)
        view.web.localOwnerPort = 3000
        view.web.localOwnerProblem = "other"
        verify(message.visible)
        compare(message.text, "Another user's program is using port 3000. Hearthwire won't load anything from it.")
        compare(view.localOwnerText("other", 3000).indexOf("localhost"), -1)
        compare(view.localOwnerText("owner-unknown", 3000),
                "Couldn't check which program is using port 3000. Nothing was loaded.")
        compare(view.localOwnerText("not-running", 3000),
                "Nothing is using port 3000. Is your local chat server running?")
        compare(view.localOwnerText("anything else", 3000), view.localOwnerText("owner-unknown", 3000))
        compare(view.localOwnerText("", 3000), "")
        compare(message.type, Kirigami.MessageType.Error)
        message.actions[0].trigger()
        compare(view.web.retries, 1)
        // Shown for the Local site only.
        view.siteId = "claude"
        verify(!message.visible)
        view.siteId = "local"
        view.web.localOwnerProblem = "resend"
        compare(message.type, Kirigami.MessageType.Information)
        verify(!message.actions[0].visible)
        message.actions[1].trigger()
        compare(view.web.localOwnerProblem, "")
        // Dismiss also ends the pass for the form (N4).
        compare(view.web.dismissals, 1)
    }

    // --- open in browser prompt (N1) -----------------------------------------

    function test_externalPromptAsksBeforeOpening() {
        var view = make({current: true, siteId: "claude", siteIds: ["claude"]})
        tryVerify(function () { return view.web !== null })
        var prompt = findChild(view, "externalPrompt")
        var label = findChild(view, "externalText")
        var open = findChild(view, "externalOpen")
        var cancel = findChild(view, "externalCancel")
        verify(!prompt.visible)
        // ChatSites never yields such a host; the label must still show it literally.
        var host = "<b>example.net</b>"
        view.web.externalUrl = "https://example.net/"
        view.web.externalHost = host
        verify(prompt.visible)
        compare(label.textFormat, Text.PlainText)
        compare(label.text, "Open " + host + " in your browser?")
        compare(view.web.opened, 0)
        cancel.clicked()
        compare(view.web.cancelled, 1)
        compare(view.web.opened, 0)
        verify(!prompt.visible)
        view.web.externalUrl = "https://example.net/"
        view.web.externalHost = "example.net"
        open.clicked()
        compare(view.web.opened, 1)
        verify(!prompt.visible)
        // Never without a host to name.
        view.web.externalUrl = "https://example.net/"
        view.web.externalHost = ""
        verify(!prompt.visible)
    }

    // --- off-site notice (L2) ------------------------------------------------

    function test_offSiteNoticeShowsTheHostAsPlainText() {
        var view = make({current: true, siteId: "claude", siteIds: ["claude"]})
        tryVerify(function () { return view.web !== null })
        var notice = findChild(view, "offSiteNotice")
        var label = findChild(view, "offSiteText")
        var back = findChild(view, "offSiteBack")
        verify(!notice.visible)
        view.web.activeSiteName = "Claude"
        // ChatSites never yields such a host; the label must still show it literally.
        var host = "<img src=\"http://127.0.0.1:9/x\"><b>claude.ai</b>"
        view.web.offSite = {off: true, host: host}
        verify(notice.visible)
        compare(label.textFormat, Text.PlainText)
        compare(label.text, "You are on " + host + " — not Claude")
        compare(back.text, "Back to Claude")
        back.clicked()
        compare(view.web.homes, 1)
        view.web.offSite = {off: true, host: ""}
        compare(label.text, "You are on another site — not Claude")
        view.web.offSite = {off: false, host: ""}
        verify(!notice.visible)
    }

    // --- download names (L3) -------------------------------------------------

    function test_downloadNamesRevealHiddenCharacters() {
        var view = make()
        compare(view.plainName("invoice‮fdp.exe"), "invoice⟦U+202E⟧fdp.exe")
        compare(view.plainName("a​b⁦c﻿"), "a⟦U+200B⟧b⟦U+2066⟧c⟦U+FEFF⟧")
        compare(view.plainName("<b>x</b>&.txt"), "&lt;b&gt;x&lt;/b&gt;&amp;.txt")
        var long = ""
        for (var index = 0; index < 70; index++)
            long += "‮"
        var shown = view.plainName(long)
        verify(!/[‪-‮]/.test(shown), shown)
        compare(shown.length, 60)
        compare(view.plainName("report.pdf"), "report.pdf")
    }

    // Long names are cut in the middle; the real last extension stays.
    function test_downloadNamesKeepTheLastExtension() {
        var view = make()
        var padding = ""
        for (var index = 0; index < 80; index++)
            padding += "a"
        var shown = view.plainName("invoice.pdf" + padding + ".exe")
        compare(shown.length, 60)
        verify(/^invoice\.pdfa+…a+\.exe$/.test(shown), shown)
        // A hidden character just before the end stays visible too.
        shown = view.plainName(padding + "‮gpj.exe")
        verify(/…a*⟦U\+202E⟧gpj\.exe$/.test(shown), shown)
        // A long extension is kept whole up to the limit.
        var ext = "." + padding.slice(0, 40) + "x"
        shown = view.plainName(padding + ext)
        compare(shown.slice(-ext.length), ext)
        compare(shown.length, 60)
        // No name: the end stays.
        shown = view.plainName(padding + "bcd")
        compare(shown.slice(-3), "bcd")
        compare(shown.indexOf("…"), 31)
        // An emoji at a cut is never split into half a character.
        var emoji = ""
        for (index = 0; index < 40; index++)
            emoji += "😀"
        shown = view.plainName(emoji)
        verify(!/[\ud800-\udbff](?![\udc00-\udfff])|(?:^|[^\ud800-\udbff])[\udc00-\udfff]/.test(shown), shown)
        verify(shown.indexOf("…") > 0)
    }

    // --- zoom keys (Ctrl+= / Ctrl+- / Ctrl+0) --------------------------------

    function test_zoomKeysAskForTheSiteShown() {
        testCase.shownAtCreation = true
        var view = make({zoomMap: {claude: 1.25}})
        var asked = []
        view.zoomRequested.connect(function (direction) { asked.push(direction) })
        tryVerify(function () { return view.web !== null })
        // The web view gets the zoom map and follows it.
        compare(view.web.zoomMap, {claude: 1.25})
        view.zoomMap = {claude: 1.5}
        compare(view.web.zoomMap, {claude: 1.5})
        keyClick(Qt.Key_Equal, Qt.ControlModifier)
        keyClick(Qt.Key_Minus, Qt.ControlModifier)
        keyClick(Qt.Key_0, Qt.ControlModifier)
        compare(asked, [1, -1, 0])
    }

    function test_zoomKeysOnlyWhileShown() {
        var view = make({current: false})
        var asked = []
        view.zoomRequested.connect(function (direction) { asked.push(direction) })
        keyClick(Qt.Key_Equal, Qt.ControlModifier)
        keyClick(Qt.Key_0, Qt.ControlModifier)
        compare(asked, [])
    }

    // --- R3: KDE Wallet on the locked card ----------------------------------------

    function test_walletUnlockCardOffersThePassphrase() {
        var view = make({ current: true, storageMode: "encrypted", card: {view: "unlock", message: ""} })
        var unlock = findChild(view, "unlockButton")
        var passphrase = findChild(view, "unlockPassphraseButton")
        var setup = findChild(view, "walletSetupButton")
        compare(unlock.text, "Unlock…")
        verify(!passphrase.visible)
        view.unlockMethod = "wallet"
        compare(unlock.text, "Unlock with KDE Wallet")
        verify(passphrase.visible)
        verify(!setup.visible)
        unlock.clicked()
        passphrase.clicked()
        compare(testCase.requests.slice(-2), ["unlock", "unlock-passphrase"])
        // The key no longer fits: set up again, only when the wallet is chosen.
        view.card = {view: "unlock", message: "wallet-mismatch"}
        verify(!setup.visible)
        view.walletChosen = true
        verify(setup.visible)
        verify(passphrase.visible)
        setup.clicked()
        compare(testCase.requests[testCase.requests.length - 1], "wallet-setup")
        compare(findChild(view, "storageCard").message,
                "The key in KDE Wallet no longer opens the encrypted folder. Set it up again, or use your passphrase.")
        view.card = {view: "unlock", message: "not-set-up"}
        verify(setup.visible)
        view.card = {view: "unlock", message: "wallet-failed"}
        verify(!setup.visible)
        view.card = {view: "busy", message: "unlock-wallet"}
        compare(findChild(view, "storageCard").message,
                "Unlocking with KDE Wallet… If KDE Wallet asks for its password, answer its window.")
    }

    // M1: a key set up but not applied is said on the card.
    function test_walletNotAppliedNote() {
        var view = make({ current: true, storageMode: "encrypted", card: {view: "unlock", message: ""} })
        var note = findChild(view, "walletNotAppliedNote")
        verify(!note.visible)
        view.walletNotApplied = true
        verify(note.visible)
        compare(note.textFormat, Text.PlainText)
        // The card still unlocks with the passphrase.
        compare(findChild(view, "unlockButton").text, "Unlock…")
        view.card = {view: "create", message: ""}
        verify(!note.visible)
    }

    // --- split view ---------------------------------------------------------------

    function test_splitIsPassedOnAndHintedWhenNarrow() {
        var view = make({ current: true, siteIds: ["claude", "chatgpt"], siteId: "claude" })
        tryVerify(function () { return view.web !== null })
        view.siteIdB = "chatgpt"
        view.splitActive = true
        compare(view.web.siteIdB, "chatgpt")
        compare(view.web.splitActive, true)
        // The stub is "too narrow" below 600 px.
        var hint = findChild(view, "splitHint")
        verify(view.web.width < 600)
        verify(hint.visible)
        compare(hint.text, "Use the Large popup size for split view")
        view.splitActive = false
        verify(!hint.visible)
        compare(view.web.splitActive, false)
    }

    function test_zoomKeysAskForThePaneInUse() {
        var view = make({ current: true, siteIds: ["claude", "chatgpt"], siteId: "claude" })
        tryVerify(function () { return view.web !== null })
        compare(view.zoomSiteId, "claude")
        view.web.activeSiteId = "chatgpt"
        compare(view.zoomSiteId, "chatgpt")
    }

    // M2: an owner problem of the pane without focus still shows.
    function test_splitLocalProblemInTheOtherPaneShows() {
        var view = make({ current: true, siteIds: ["claude", "local"], siteId: "claude" })
        tryVerify(function () { return view.web !== null })
        view.siteIdB = "local"
        view.splitActive = true
        view.web.splitShown = true
        compare(view.zoomSiteId, "claude")
        view.web.localOwnerProblem = "other"
        verify(findChild(view, "localOwnerMessage").visible)
        // Only pane a shown (too narrow): pane b's Local isn't on screen.
        view.web.splitShown = false
        verify(!findChild(view, "localOwnerMessage").visible)
    }

    // S2: the download prompt names the site that asked.
    function test_downloadPromptNamesTheSite() {
        var view = make({ current: true, siteIds: ["claude"], siteId: "claude" })
        tryVerify(function () { return view.web !== null })
        view.web.pendingDownloadName = "notes.txt"
        view.web.pendingDownloadSite = "Claude"
        var items = []
        var found = ""
        var stack = [view]
        while (stack.length > 0) {
            var item = stack.pop()
            if (typeof item.text === "string" && item.text.indexOf("notes.txt") >= 0 && item.visible)
                found = item.text
            var kids = item.children || []
            for (var index = 0; index < kids.length; index++)
                stack.push(kids[index])
        }
        verify(found.indexOf("from Claude to Downloads?") >= 0, found)
    }
}
