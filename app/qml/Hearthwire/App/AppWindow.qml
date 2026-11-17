import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import QtQuick.Controls.Material
import Hearthwire.Compat.Kirigami as Kirigami
import Hearthwire.Compat.Plasmoid
import Hearthwire.App

// The app window: the plasmoid's main.qml (unchanged, from the synced
// Hearthwire.Plasmoid module) lives here without a panel, and its
// fullRepresentation fills the window. expanded stays true while the
// window is shown. Settings opens from Plasmoid.internalAction("configure").
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
