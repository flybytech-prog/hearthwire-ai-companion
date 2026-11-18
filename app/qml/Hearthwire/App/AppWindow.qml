import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import QtQuick.Controls.Material
import Hearthwire.Compat.Kirigami as Kirigami
import Hearthwire.Compat.Plasmoid
import Hearthwire.App
import "qrc:/qt/qml/Hearthwire/Plasmoid/SettingsLogic.js" as SettingsLogic

// The app window: the plasmoid's main.qml (unchanged, from the synced
// Hearthwire.Plasmoid module) lives here without a panel, and its
// fullRepresentation fills the window. expanded follows the window: shown
// = expanded. `expanded = true` shows and raises a hidden window.
// Task 012 R3.4:
// - Minimize (main.qml's `expanded = false`, the popup's button) hides the
//   window only while this copy owns the single-instance name
//   (hideOnCollapse = App.instance.available): it keeps running (refresh,
//   alerts) and a new launch, --toggle or --tab brings it back. Without a
//   session bus nothing could bring it back (review-4 S3), so expanded is
//   set back to true and the window stays.
// - Closing the window (its close button, Hyprland's killactive, Super+W)
//   quits the app; an open Settings dialog closes too and its unapplied
//   changes are dropped, as Cancel + Discard would, without asking. The
//   helpers stop as the engine is torn down.
// - A compositor's own minimize needs nothing here.
// - Focus loss never hides the window (main.qml's hideOnWindowDeactivate
//   is a panel popup's and is ignored).
// - Show(tab) / Toggle() from a later launch (SingleInstance.h) pick the
//   tab through SettingsLogic.shortcutPlan(), as the plasmoid's shortcut
//   does; Plasmoid.activated is not sent (shortcutOpens is panel-only).
// Settings opens from Plasmoid.internalAction("configure").
ApplicationWindow {
    id: window

    title: "Hearthwire"
    visible: true
    width: Kirigami.Units.gridUnit * 30
    height: Kirigami.Units.gridUnit * 36
    color: Kirigami.Theme.backgroundColor

    Material.theme: Kirigami.Theme.dark ? Material.Dark : Material.Light
    Material.accent: Kirigami.Theme.highlightColor
    Material.background: Kirigami.Theme.backgroundColor
    Material.foreground: Kirigami.Theme.textColor

    // Only a copy others can reach (single instance) may hide.
    readonly property bool hideOnCollapse: App.instance.available

    // main.qml's PlasmoidItem (created at run time, so untyped here).
    property var plasmoidItem: null
    property Item full: null
    readonly property alias settings: settingsWindow

    Item {
        id: holder
        visible: false
    }

    Item {
        id: stage
        anchors.fill: parent
    }

    Component.onCompleted: {
        var component = Qt.createComponent("qrc:/qt/qml/Hearthwire/Plasmoid/main.qml")
        if (component.status !== Component.Ready) {
            console.warn("main.qml:", component.errorString())
            return
        }
        window.plasmoidItem = component.createObject(holder)
        if (!window.plasmoidItem || !window.plasmoidItem.fullRepresentation)
            return
        window.plasmoidItem.expanded = window.visible
        window.full = window.plasmoidItem.fullRepresentation.createObject(stage)
        window.full.anchors.fill = stage
        window.plasmoidItem.fullRepresentationItem = window.full
        var preferredWidth = window.full.Layout.preferredWidth
        var preferredHeight = window.full.Layout.preferredHeight
        if (preferredWidth > 0)
            window.width = preferredWidth
        if (preferredHeight > 0)
            window.height = preferredHeight
    }

    onVisibleChanged: {
        if (window.plasmoidItem)
            window.plasmoidItem.expanded = window.visible
    }

    Connections {
        target: window.plasmoidItem
        function onExpandedChanged() {
            var expanded = window.plasmoidItem.expanded
            if (expanded && !window.visible) {
                App.present(window)
            } else if (!expanded && window.visible) {
                if (window.hideOnCollapse)
                    window.hide()
                else
                    window.plasmoidItem.expanded = true
            }
        }
    }

    // A later launch: show on a tab ("" keeps the tab).
    function showTab(tab) {
        var root = window.plasmoidItem
        var plan = null
        if (root && tab !== "") {
            // The linter can't see into a qrc: JS import.
            // qmllint disable missing-property
            plan = SettingsLogic.shortcutPlan(tab, root.popupTabs, root.chatSiteIds.indexOf("ollama") >= 0)
            // qmllint enable missing-property
            if (plan.tab !== "")
                root.popupTab = plan.tab
            if (plan.site !== "")
                root.chatSiteId = plan.site
            if (plan.focusInput)
                root.ollamaFocusRequested()
        }
        window.bringUp()
    }

    // --toggle: hide a shown, active window; else show it.
    function toggle() {
        var root = window.plasmoidItem
        if (window.visible && window.active) {
            // Hidden, not presented: the call's token is not kept for later.
            App.dropToken()
            if (root)
                root.expanded = false
            return
        }
        window.bringUp()
    }

    // Expanded and presented exactly once (the call's token is used once,
    // for the one requestActivate()): a hidden window is presented by
    // onExpandedChanged above, a shown one here.
    function bringUp() {
        var root = window.plasmoidItem
        if (root && !root.expanded && !window.visible) {
            root.expanded = true
            if (window.visible)
                return
        }
        if (root)
            root.expanded = true
        App.present(window)
    }

    Connections {
        target: App.instance
        function onShowRequested(tab) {
            window.showTab(tab)
        }
        function onToggleRequested() {
            window.toggle()
        }
        // The name was lost: nothing can bring a hidden window back.
        function onAvailableChanged() {
            if (!App.instance.available && !window.visible)
                window.showTab("")
        }
    }

    onClosing: {
        settingsWindow.dropAndClose()
        App.quit()
    }

    Connections {
        target: App.host
        function onConfigureRequested() {
            settingsWindow.openDialog()
        }
    }

    SettingsWindow {
        id: settingsWindow
    }

    // Fixture builds only (SpikeChecks.qml is not in a release build).
    Loader {
        active: App.fixtures
        source: "SpikeChecks.qml"
    }
}
