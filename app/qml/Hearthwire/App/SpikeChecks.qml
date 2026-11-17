import QtQuick
import QtQuick.Controls
import Hearthwire.Compat.Plasmoid
import Hearthwire.App

// FIXTURE BUILDS ONLY (task 012; HW_FIXTURES=ON): with --shots and/or --checks, drives the
// app through the Usage tab and the settings dialog and prints one
// "SPIKE CHECK <name>: PASS|FAIL" line per Plasma semantic it compares,
// then quits. Without either option it does nothing.
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

    Connections {
        target: checks.config
        function onValueChanged(key, value) {
            checks.emitted.push(key)
        }
    }

    // Each step returns how long to wait before the next, in ms.
    readonly property var steps: [
        function () {
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
            shot(settings, "settings-general.png")
            if (!App.runChecks())
                return -1
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
            return -1
        }
    ]

    Timer {
        id: driver
        running: checks.active
        interval: 100
        onTriggered: {
            var wait = -1
            try {
                wait = checks.steps[checks.step]()
            } catch (error) {
                checks.check("step " + checks.step, false, String(error))
            }
            checks.step += 1
            if (wait < 0 || checks.step >= checks.steps.length) {
                console.info("SPIKE CHECKS: " + checks.failures + " failed")
                App.finish(checks.failures === 0 ? 0 : 1)
                return
            }
            driver.interval = Math.max(1, wait)
            driver.start()
        }
    }
}
