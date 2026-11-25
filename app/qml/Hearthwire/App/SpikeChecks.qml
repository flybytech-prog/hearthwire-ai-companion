import QtQuick
import QtQuick.Controls
import Hearthwire.Compat.Plasmoid
import Hearthwire.Compat.Plasma5Support as Plasma5Support
import Hearthwire.App
import "qrc:/qt/qml/Hearthwire/Plasmoid/ChatStorage.js" as ChatStorage

// FIXTURE BUILDS ONLY (task 012; HW_FIXTURES=ON): with --checks, drives the
// app through the Usage tab and the settings dialog and prints one
// "SPIKE CHECK <name>: PASS|FAIL" line per Plasma semantic it compares,
// then quits; the last checks prove the URL guard is installed and refused
// nothing else. With --shots only, saves the Usage tab and every settings
// page. Without either option it does nothing.
// Task 013: the run starts on the Chat tab, which must load the plasmoid's
// ChatWebView (Qt WebEngine) without a QML warning; then the vault status
// with hearthwire-askpass missing and the helper's bad-frontend refusal,
// both from the fixture book (applet id 2147483648 in every command).
Item {
    id: checks

    // The AppWindow it is loaded into.
    readonly property var appWindow: checks.Window.window
    readonly property bool active: App.runChecks() || App.shots() !== ""
    readonly property var config: Plasmoid.configuration
    readonly property var settings: appWindow ? appWindow.settings : null
    readonly property var page: settings ? settings.currentPage : null

    property int step: 0
    property int failures: 0
    property var emitted: []
    property int reemitsBefore: 0
    property string holdStamp: ""
    property bool chatShownBefore: false
    property bool activeBefore: false
    property int presentsBefore: 0
    // QML warnings before Settings first opens (round 2: a TypeError while a
    // page goes away must fail a check, not only move the count).
    property int qmlWarningsBefore: -1

    function check(name, ok, detail) {
        if (!ok)
            checks.failures += 1
        console.info("SPIKE CHECK " + name + ": " + (ok ? "PASS" : "FAIL") + (detail ? " (" + detail + ")" : ""))
    }

    function shot(window, name) {
        if (App.shots() !== "")
            check("screenshot " + name, App.grab(window, name))
    }

    property real defaultWidth: 0

    // The Usage tab for usage.png (the popup opens on Chat by default).
    function showUsage() {
        if (appWindow.plasmoidItem)
            appWindow.plasmoidItem.popupTab = "usage"
    }

    // The right edge, in form's coordinates, of the furthest visible item
    // under item.
    function rightEdge(item, form) {
        if (!item || !item.visible)
            return 0
        var edge = item.width > 0 ? item.mapToItem(form, item.width, 0).x : 0
        for (var i = 0; i < item.children.length; i++)
            edge = Math.max(edge, checks.rightEdge(item.children[i], form))
        return edge
    }

    // The first ComboBox under item (QQC2's, from the app style).
    function findCombo(item) {
        if (!item)
            return null
        if (item.implicitContentWidthPolicy !== undefined && item.popup !== undefined)
            return item
        for (var i = 0; i < item.children.length; i++) {
            var found = checks.findCombo(item.children[i])
            if (found)
                return found
        }
        if (item.contentItem && item.contentItem !== item && item.contentItem.parent !== item) {
            var inside = checks.findCombo(item.contentItem)
            if (inside)
                return inside
        }
        return null
    }

    // The first item under item with this objectName.
    function findByName(item, name) {
        if (!item)
            return null
        if (item.objectName === name)
            return item
        for (var i = 0; i < item.children.length; i++) {
            var found = checks.findByName(item.children[i], name)
            if (found)
                return found
        }
        if (item.contentItem && item.contentItem !== item && item.contentItem.parent !== item)
            return checks.findByName(item.contentItem, name)
        return null
    }

    // Fixture-book commands answered with {"ok":false,"error":"bad-frontend"}.
    readonly property var badFrontendCommands: [
        "env HEARTHWIRE_RUN=7 HEARTHWIRE_APPLET=2147483648 python3 -P -m hearthwire --vault lock",
        "env HEARTHWIRE_RUN=8 HEARTHWIRE_APPLET=2147483648 python3 -P -m hearthwire --web-data remove --store encrypted --applet 2147483648"
    ]
    property var helperReplies: ({})

    Plasma5Support.DataSource {
        id: probe
        engine: "executable"
        onNewData: (source, data) => {
            var replies = Object.assign({}, checks.helperReplies)
            replies[source] = ChatStorage.replyFor(data["exit code"], data["stdout"])
            checks.helperReplies = replies
            probe.disconnectSource(source)
        }
    }

    function chatView() {
        return checks.findByName(appWindow.full, "chatView")
    }

    function shownText(name) {
        var item = checks.findByName(page, name)
        return item ? item.text : undefined
    }

    Connections {
        target: checks.config
        function onValueChanged(key, value) {
            checks.emitted.push(key)
        }
    }

    // Each step returns how long to wait before the next, in ms.
    readonly property var steps: [
        // Task 013: the Chat tab with Qt WebEngine.
        function () {
            appWindow.plasmoidItem.popupTab = "chat"
            return 4000
        },
        function () {
            var chat = checks.chatView()
            var web = chat ? chat.web : null
            check("the Chat tab loads the plasmoid's ChatWebView (Qt WebEngine)",
                  chat !== null && chat.current === true && web !== null && web.siteIds !== undefined
                  && web.activeView !== null && web.activeView !== undefined,
                  chat ? "current " + chat.current + ", web " + (web !== null) : "no chatView")
            // The web view gets storageApplet only for saved sign-ins (-1 in
            // memory mode), so the stored id is checked on ChatView.
            check("the Chat views keep the app id 2147483648 (double, not int)",
                  web !== null && web.appletId === 2147483648 && chat.appletId === 2147483648
                  && chat.storageApplet === 2147483648 && web.storageApplet === -1,
                  web ? "appletId " + web.appletId + "/" + chat.appletId + ", storageApplet " + chat.storageApplet
                        + "/" + web.storageApplet : "")
            check("no QML warning from the start through the Chat tab", App.qmlWarnings() === 0,
                  App.qmlWarnings() + " QML warning(s)")
            config.chatSignInStorage = "encrypted"
            return 1500
        },
        function () {
            var root = appWindow.plasmoidItem
            var chat = checks.chatView()
            check("vault status: hearthwire-askpass is reported missing",
                  root.chatVaultState === "unavailable"
                  && JSON.stringify(root.chatVaultMissing) === "[\"hearthwire-askpass\"]",
                  "state '" + root.chatVaultState + "', missing " + JSON.stringify(root.chatVaultMissing))
            check("the Chat tab shows the install card for it",
                  chat !== null && chat.card.view === "install"
                  && ChatStorage.installCommand(root.chatVaultMissing, root.installDistro).indexOf("hearthwire-") >= 0,
                  chat ? "view " + chat.card.view : "")
            config.chatSignInStorage = "memory"
            for (var i = 0; i < checks.badFrontendCommands.length; i++)
                probe.connectSource(checks.badFrontendCommands[i])
            return 800
        },
        function () {
            var chat = checks.chatView()
            for (var i = 0; i < checks.badFrontendCommands.length; i++) {
                var command = checks.badFrontendCommands[i]
                var reply = checks.helperReplies[command]
                var code = reply ? ChatStorage.messageFor(reply.error) : ""
                var text = chat && code !== "" ? chat.storageText(code) : ""
                check("bad-frontend reply " + (i + 1) + " gives the version message",
                      reply !== undefined && reply.ok === false && reply.error === "bad-frontend"
                      && code === "bad-frontend" && text.indexOf("of the same version") >= 0,
                      reply ? "error '" + reply.error + "', text '" + text + "'" : "no reply")
            }
            check("no QML warning in the Chat steps", App.qmlWarnings() === 0, App.qmlWarnings() + " QML warning(s)")
            // Task 013 F2: the http acknowledgement goes main.qml ->
            // Plasmoid.configuration -> settings.json, and back into the view.
            appWindow.plasmoidItem.chatHttpSiteAcknowledged("http://example.org:8080/not-an-origin")
            appWindow.plasmoidItem.chatHttpSiteAcknowledged("http://example.org:8080")
            return 300
        },
        function () {
            var chat = checks.chatView()
            var stored = App.storedValue("chatHttpWarnedSites")
            check("an http acknowledgement is saved to settings.json (0600) and reaches the Chat view",
                  JSON.stringify(stored) === "[\"http://example.org:8080\"]" && App.fileMode() === 384
                  && chat !== null && JSON.stringify(chat.httpWarnedSites) === "[\"http://example.org:8080\"]",
                  "stored " + JSON.stringify(stored) + ", mode " + App.fileMode().toString(8)
                  + ", view " + (chat ? JSON.stringify(chat.httpWarnedSites) : "none"))
            return 100
        },
        function () {
            checks.showUsage()
            return 1500
        },
        function () {
            var root = appWindow.plasmoidItem
            check("main.qml and FullRepresentation load", root !== null && appWindow.full !== null)
            check("Plasmoid.id is the app id 2147483648", Plasmoid.id === 2147483648, "id " + Plasmoid.id)
            // main.qml keeps the id in a `property int` (32-bit): reported, not checked.
            console.info("SPIKE INFO main.qml chatAppletId = " + (root ? root.chatAppletId : "?"))
            check("fixture snapshot shown", root && root.hasData === true && root.snapshot.providers.length > 0,
                  root ? "providers " + (root.snapshot.providers || []).length + ", error '" + root.lastError + "'" : "")
            shot(appWindow, "usage.png")
            if (!App.runChecks() && App.shots() === "")
                return -1
            checks.qmlWarningsBefore = App.qmlWarnings()
            Plasmoid.internalAction("configure").trigger()
            return 1500
        },
        function () {
            check("configure opens Settings on its first page", settings.visible && page !== null
                  && settings.currentSource === "configGeneral.qml")
            check("page opens with cfg_<key> = stored value",
                  page.cfg_refreshInterval === config.refreshInterval && page.cfg_usageMode === config.usageMode
                  && page.cfg_trackedProviders === config.trackedProviders)
            check("page opens with cfg_<key>Default from \"<key>Default\" entries",
                  config.keys().indexOf("refreshIntervalDefault") >= 0
                  && page.cfg_refreshIntervalDefault === config.refreshIntervalDefault
                  && page.cfg_refreshIntervalDefault === 300)
            check("Apply disabled after open", settings.applyEnabled === false)
            // R2 look: the app style, and the form in two columns at the default size.
            var combo = checks.findCombo(page)
            check("the app style sizes a ComboBox to its widest item", combo !== null
                  && combo.implicitContentWidthPolicy === 1, combo ? "policy " + combo.implicitContentWidthPolicy : "none")
            var edge = checks.rightEdge(page.mainItem, page.mainItem)
            check("nothing on General extends past the form's edge (default size)",
                  page.mainItem !== null && edge <= page.mainItem.width + 1,
                  "right edge " + Math.round(edge) + ", form " + Math.round(page.mainItem.width)
                  + (page.mainItem.wideMode ? ", two columns" : ", one column"))
            shot(settings, "settings-general.png")
            if (!App.runChecks())
                return -1
            checks.defaultWidth = settings.width
            settings.width = settings.minimumWidth
            return 600
        },
        function () {
            var edge = checks.rightEdge(page.mainItem, page.mainItem)
            check("nothing on General extends past the form's edge (minimum size)",
                  page.mainItem !== null && edge <= page.mainItem.width + 1,
                  "right edge " + Math.round(edge) + ", form " + Math.round(page.mainItem.width)
                  + (page.mainItem.wideMode ? ", two columns" : ", one column"))
            shot(settings, "settings-general-min.png")
            settings.width = checks.defaultWidth
            return 600
        },
        function () {
            page.cfg_refreshInterval = 60
            return 50
        },
        function () {
            check("a cfg_ change enables Apply", settings.applyEnabled === true)
            page.cfg_refreshInterval = config.refreshInterval
            return 50
        },
        function () {
            check("changing back disables Apply (compare with stored)", settings.applyEnabled === false)
            page.cfg_refreshInterval = 60
            checks.emitted = []
            checks.reemitsBefore = config.reemitCount
            settings.apply()
            return 100
        },
        function () {
            var real = config.keys().filter(function (key) { return !/Default$/.test(key) })
            var lastKey = checks.emitted.length ? checks.emitted[checks.emitted.length - 1] : ""
            check("Apply stores the value", config.refreshInterval === 60 && App.storedValue("refreshInterval") === 60)
            check("Apply re-emits every key once, backupAutoExport last",
                  config.reemitCount === checks.reemitsBefore + 1 && lastKey === "backupAutoExport"
                  && real.every(function (key) { return checks.emitted.indexOf(key) >= 0 }),
                  checks.emitted.length + " emits for " + real.length + " keys, last " + lastKey)
            check("Apply disables Apply", settings.applyEnabled === false)
            check("settings file is 0600", App.fileMode() === 384, "mode " + App.fileMode().toString(8))
            check("main.qml sees the applied value", appWindow.plasmoidItem.refreshInterval === 60)
            page.cfg_usageMode = "used"
            settings.cancel()
            return 200
        },
        function () {
            check("Cancel with changes asks first", settings.visible && settings.promptOpen === true)
            settings.discard()
            return 200
        },
        function () {
            check("Discard closes without storing", settings.visible === false && config.usageMode === "remaining")
            check("closing destroys the page (Plasma's ConfigView is deleted when hidden)",
                  settings.currentPage === null && settings.currentSource === "")
            Plasmoid.internalAction("configure").trigger()
            return 800
        },
        function () {
            check("reopening shows the stored values, Apply off",
                  page.cfg_refreshInterval === 60 && page.cfg_usageMode === "remaining" && settings.applyEnabled === false)
            page.cfg_usageMode = "used"
            settings.openCategory(settings.configModel.get(1))
            return 200
        },
        function () {
            check("switching page with changes asks first", settings.currentSource === "configGeneral.qml"
                  && settings.promptOpen === true)
            settings.discard()
            return 1200
        },
        function () {
            check("Discard opens the other page", settings.currentSource === "configUsage.qml"
                  && page !== null && page.cfg_usageMode === "remaining")
            check("the AI Provider Settings list opens at its top (header not cut off)",
                  page.view.contentY === page.view.originY && page.view.headerItem.height > 0,
                  "contentY " + page.view.contentY + ", originY " + page.view.originY)
            shot(settings, "settings-usage.png")
            page.cfg_usageMode = "used"
            settings.accept()
            return 200
        },
        function () {
            check("OK stores and closes", settings.visible === false && config.usageMode === "used"
                  && App.storedValue("usageMode") === "used")
            check("OK: the page is destroyed after the apply", settings.currentPage === null)
            checks.emitted = []
            checks.reemitsBefore = config.reemitCount
            config.chatSiteZoom = "{\"claude\":110}"
            return 100
        },
        function () {
            check("a widget's own write is stored and re-emits every key",
                  App.storedValue("chatSiteZoom") === "{\"claude\":110}"
                  && config.reemitCount === checks.reemitsBefore + 1
                  && checks.emitted[checks.emitted.length - 1] === "backupAutoExport",
                  checks.emitted.length + " emits")
            config.refreshIntervalDefault = 5
            check("\"<key>Default\" entries can't be written", config.refreshIntervalDefault === 300)
            config.refreshInterval = "900"
            return 100
        },
        function () {
            check("Int key keeps its type", config.refreshInterval === 900 && App.storedValue("refreshInterval") === 900)
            Plasmoid.internalAction("configure").trigger()
            return 800
        },
        // review-1 #2: a hold on Automatic backup (an import confirmation
        // open) ends when Settings is closed, through the page's
        // Component.onDestruction, as in Plasma.
        function () {
            check("Settings opens on General again", settings.visible && page !== null
                  && settings.currentSource === "configGeneral.qml")
            page.restoreHoldWait = 100
            page.holdAutoBackup()
            checks.holdStamp = config.backupRestoreAt
            return 350
        },
        function () {
            check("the page holds Automatic backup", checks.holdStamp !== "" && page.restoreHold !== ""
                  && config.backupRestoreAt !== "" && settings.applyEnabled === false,
                  "hold '" + checks.holdStamp + "', apply " + settings.applyEnabled)
            settings.close()
            return 300
        },
        function () {
            check("closing Settings destroys the held page", settings.visible === false && settings.currentPage === null)
            check("its onDestruction ended the hold", config.backupRestoreAt === "" && App.storedValue("backupRestoreAt") === "",
                  "backupRestoreAt '" + config.backupRestoreAt + "'")
            checks.reemitsBefore = config.reemitCount
            return 500
        },
        function () {
            check("no hold refresh after the close", config.reemitCount === checks.reemitsBefore && config.backupRestoreAt === "",
                  (config.reemitCount - checks.reemitsBefore) + " re-emits")
            check("no QML warning while Settings opened, applied and closed its pages",
                  checks.qmlWarningsBefore >= 0 && App.qmlWarnings() === checks.qmlWarningsBefore,
                  (App.qmlWarnings() - checks.qmlWarningsBefore) + " new")
            // R2: main.qml's `expanded = false` (the popup's Minimize button).
            appWindow.plasmoidItem.expanded = false
            return 300
        },
        // R3.4 (M16): without single instance nothing could bring a hidden
        // window back, so Minimize keeps it; with it, Minimize hides.
        function () {
            check("M16a: expanded = false keeps the window without single instance",
                  App.instance.available === false && appWindow.hideOnCollapse === false
                  && appWindow.visible === true && appWindow.plasmoidItem.expanded === true)
            App.simulateInstance(true)
            appWindow.plasmoidItem.expanded = false
            return 300
        },
        function () {
            check("M16b: with single instance, expanded = false hides the window (the app keeps running)",
                  appWindow.hideOnCollapse === true && appWindow.visible === false
                  && appWindow.plasmoidItem.expanded === false)
            checks.chatShownBefore = config.showChatTab
            config.showChatTab = false
            checks.presentsBefore = App.presents()
            App.simulateShow("chat", "hw-check-token")
            return 300
        },
        function () {
            check("M16c: Show(chat) with Chat hidden shows the window on Usage",
                  appWindow.visible === true && appWindow.plasmoidItem.expanded === true
                  && appWindow.plasmoidItem.popupTab === "usage", "tab " + appWindow.plasmoidItem.popupTab)
            // review-6 L1: one present(), so the token goes to the one activation.
            check("showing a hidden window presents it once and uses the token",
                  App.presents() - checks.presentsBefore === 1 && App.tokenPending() === false,
                  (App.presents() - checks.presentsBefore) + " present(s)")
            config.showChatTab = checks.chatShownBefore
            checks.activeBefore = appWindow.active
            checks.presentsBefore = App.presents()
            App.simulateToggle("hw-check-token")
            return 300
        },
        function () {
            check("Toggle on a shown, active window hides it", checks.activeBefore === true && appWindow.visible === false,
                  "active before " + checks.activeBefore)
            // review-6 I2: the hiding call's token is not kept for a later present().
            check("the hiding Toggle keeps no token and presents nothing",
                  App.tokenPending() === false && App.presents() === checks.presentsBefore)
            App.simulateToggle()
            return 300
        },
        function () {
            check("the next Toggle shows it again", appWindow.visible === true && appWindow.plasmoidItem.expanded === true)
            check("the showing Toggle presents once", App.presents() - checks.presentsBefore === 1,
                  (App.presents() - checks.presentsBefore) + " present(s)")
            checks.presentsBefore = App.presents()
            App.simulateShow("", "hw-check-token")
            return 300
        },
        function () {
            check("Show on a shown window presents it once and uses the token",
                  appWindow.visible === true && App.presents() - checks.presentsBefore === 1 && App.tokenPending() === false,
                  (App.presents() - checks.presentsBefore) + " present(s)")
            appWindow.plasmoidItem.expanded = false
            return 300
        },
        // review-6 L4: losing the name brings a hidden window back.
        function () {
            check("M16d: hidden before the name is lost", appWindow.visible === false && App.instance.available === true)
            App.simulateInstance(false)
            return 300
        },
        function () {
            check("M16d: losing the name shows the hidden window",
                  App.instance.available === false && appWindow.visible === true && appWindow.plasmoidItem.expanded === true)
            Plasmoid.internalAction("configure").trigger()
            return 800
        },
        // R2: Escape = Cancel, Return = OK.
        function () {
            page.cfg_refreshInterval = 120
            check("Escape: sent", App.sendKey(settings, Qt.Key_Escape))
            return 200
        },
        function () {
            check("Escape with changes asks first (Cancel)", settings.visible && settings.promptOpen === true)
            settings.discard()
            return 300
        },
        function () {
            check("Discard after Escape closes without storing", settings.visible === false && config.refreshInterval === 900)
            Plasmoid.internalAction("configure").trigger()
            return 800
        },
        function () {
            page.cfg_refreshInterval = 120
            check("Return: sent", App.sendKey(settings, Qt.Key_Return))
            return 300
        },
        function () {
            check("Return applies and closes (OK)", settings.visible === false && config.refreshInterval === 120
                  && App.storedValue("refreshInterval") === 120)
            check("no QML warning in the R2 steps", App.qmlWarnings() === checks.qmlWarningsBefore,
                  (App.qmlWarnings() - checks.qmlWarningsBefore) + " new")
            // The URL guard refused nothing the app itself loads...
            check("the URL guard refused nothing in the whole run", App.guardRefusals() === 0,
                  App.guardRefusals() + " refusal(s)")
            // ...and is installed: a file outside the app and Qt is refused.
            var probe = Qt.createComponent("file:///hw-guard-probe/none.qml")
            var error = probe.status === Component.Error ? probe.errorString() : ""
            check("the URL guard is installed (a probe outside the app is refused)",
                  error.indexOf("hearthwire-refused") >= 0 && App.guardRefusals() === 1,
                  "refusals " + App.guardRefusals())
            Plasmoid.internalAction("configure").trigger()
            return 800
        },
        // R4 P2c: About, the last category, with no settings.
        function () {
            var list = settings.categoryList
            check("About is the last category, after config.qml's",
                  list.length === settings.configModel.count + 1 && list[list.length - 1] === settings.aboutCategory
                  && settings.aboutCategory.name === "About", list.length + " categories")
            page.cfg_refreshInterval = 121
            settings.openCategory(settings.aboutCategory)
            return 200
        },
        function () {
            check("switching to About with unsaved changes asks first",
                  settings.promptOpen === true && settings.currentSource === "configGeneral.qml")
            settings.discard()
            return 800
        },
        function () {
            var about = App.about
            check("About opens, titled About, Apply off", settings.currentSource === "about" && settings.aboutShown
                  && page !== null && page.title === "About" && settings.applyEnabled === false
                  && config.refreshInterval === 120)
            check("About has no cfg_ properties",
                  Object.keys(page).filter(function (key) { return key.indexOf("cfg_") === 0 }).length === 0)
            check("About shows App.about's values",
                  shownText("aboutName") === "Hearthwire"
                  && shownText("aboutAppVersion") === "hearthwire-hyprland " + about.version
                  && shownText("aboutComment") === about.comment && shownText("aboutLicense") === "MIT"
                  && shownText("aboutAuthors") === about.authors && shownText("aboutWebsite") === about.website
                  && shownText("aboutBugReportUrl") === about.bugReportUrl
                  && /^https:\/\//.test(about.website) && /^https:\/\//.test(about.bugReportUrl)
                  && about.version !== "" && about.comment !== "" && about.authors !== "",
                  "website " + about.website)
            // review-7 I2: the label follows the number of authors.
            var authorsLabel = checks.findByName(page, "aboutAuthorsLabel")
            var shownLabel = authorsLabel ? authorsLabel.text : ""
            page.about = Object.assign({}, about, {authorCount: 2, authors: "A, B"})
            var manyLabel = authorsLabel ? authorsLabel.text : ""
            page.about = Object.assign({}, about, {authorCount: 1})
            var oneLabel = authorsLabel ? authorsLabel.text : ""
            page.about = Qt.binding(function () { return App.about })
            check("About says Author: for one author and Authors: for more",
                  about.authorCount >= 1 && shownLabel === (about.authorCount === 1 ? "Author:" : "Authors:")
                  && manyLabel === "Authors:" && oneLabel === "Author:" && shownText("aboutAuthors") === about.authors,
                  "count " + about.authorCount + ": " + shownLabel + ", " + manyLabel + ", " + oneLabel)
            shot(settings, "settings-about.png")
            checks.findByName(page, "aboutCopyWebsite").clicked()
            check("Copy puts the website on the clipboard", App.clipboardText() === about.website)
            checks.findByName(page, "aboutCopyBugReportUrl").clicked()
            check("Copy puts the bug report address on the clipboard", App.clipboardText() === about.bugReportUrl)
            check("only the two links can be copied", App.copyAbout("comment") === false && App.copyAbout("") === false
                  && App.clipboardText() === about.bugReportUrl)
            check("About's links are plain read-only text", checks.findByName(page, "aboutWebsite").readOnly === true
                  && checks.findByName(page, "aboutWebsite").textFormat === TextEdit.PlainText)
            check("opening About leaves Apply off", settings.applyEnabled === false)
            settings.openCategory(settings.configModel.get(0))
            return 800
        },
        function () {
            check("leaving About never asks", settings.promptOpen === false && settings.currentSource === "configGeneral.qml"
                  && page !== null && settings.applyEnabled === false,
                  "prompt " + settings.promptOpen + ", " + settings.currentSource + ", apply " + settings.applyEnabled)
            settings.openCategory(settings.aboutCategory)
            return 800
        },
        function () {
            check("About opens again without asking", settings.promptOpen === false && settings.aboutShown)
            checks.reemitsBefore = config.reemitCount
            settings.accept()
            return 300
        },
        function () {
            check("OK on About only closes: nothing written, no re-emit",
                  settings.visible === false && config.reemitCount === checks.reemitsBefore,
                  (config.reemitCount - checks.reemitsBefore) + " re-emits")
            check("no QML warning on the About steps", App.qmlWarnings() === checks.qmlWarningsBefore,
                  (App.qmlWarnings() - checks.qmlWarningsBefore) + " new")
            Plasmoid.internalAction("configure").trigger()
            return 800
        },
        // R3.4: closing the window quits, Settings and its changes go too.
        function () {
            page.cfg_refreshInterval = 333
            App.holdQuit(true)
            appWindow.close()
            return 300
        },
        function () {
            check("closing the window quits; open Settings closes without asking, its change dropped",
                  App.quitRequests() === 1 && settings.visible === false && settings.promptOpen === false
                  && config.refreshInterval === 120 && App.storedValue("refreshInterval") === 120,
                  "quit " + App.quitRequests() + ", refreshInterval " + config.refreshInterval)
            return -1
        }
    ]

    // --shots without --checks: the Usage tab and every settings page.
    readonly property var shotSteps: [
        function () {
            appWindow.plasmoidItem.popupTab = "chat"
            return 4000
        },
        function () {
            shot(appWindow, "chat.png")
            checks.showUsage()
            return 1500
        },
        function () {
            shot(appWindow, "usage.png")
            Plasmoid.internalAction("configure").trigger()
            return 1500
        },
        function () {
            shot(settings, "settings-general.png")
            checks.defaultWidth = settings.width
            settings.width = settings.minimumWidth
            return 1000
        },
        function () {
            shot(settings, "settings-general-min.png")
            settings.width = checks.defaultWidth
            settings.openCategory(settings.configModel.get(1))
            return 1500
        },
        function () {
            shot(settings, "settings-usage.png")
            settings.openCategory(settings.configModel.get(2))
            return 1500
        },
        function () {
            shot(settings, "settings-chat.png")
            settings.openCategory(settings.aboutCategory)
            return 1500
        },
        function () {
            shot(settings, "settings-about.png")
            return -1
        }
    ]
    readonly property var plan: App.runChecks() ? checks.steps : checks.shotSteps

    Timer {
        id: driver
        running: checks.active
        interval: 100
        onTriggered: {
            var wait = -1
            try {
                wait = checks.plan[checks.step]()
            } catch (error) {
                checks.check("step " + checks.step, false, String(error))
            }
            checks.step += 1
            if (wait < 0 || checks.step >= checks.plan.length) {
                console.info("SPIKE CHECKS: " + checks.failures + " failed")
                App.finish(checks.failures === 0 ? 0 : 1)
                return
            }
            driver.interval = Math.max(1, wait)
            driver.start()
        }
    }
}
