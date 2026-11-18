import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import QtQuick.Controls.Material
import Hearthwire.Compat.Kirigami as Kirigami
import Hearthwire.Compat.Plasmoid

// Plasma's applet settings dialog, rebuilt from config.qml's ConfigModel.
// The page logic follows plasma-desktop 6.8's AppletConfiguration.qml:
// - a page opens with cfg_<key> = configuration[<key>] for every key of
//   Plasmoid.configuration, "<key>Default" entries included;
// - Apply is enabled by any cfg_<key>Changed (compared with the stored
//   value), configurationChanged() or unsavedChanges;
// - Apply calls the page's saveConfig(), writes every cfg_<key> the page
//   has, then writeConfig(); OK applies and closes;
// - Cancel, closing the window or picking another page with unsaved
//   changes asks: Apply, Discard or Cancel.
// Plasma 6.8 has no Defaults button for applets; neither has this.
// Keys as in Plasma's dialog: Return/Enter = OK, Escape = Cancel. They act
// only when the control with focus leaves the key alone (a text area keeps
// its Return, an open ComboBox list or the prompt its Escape).
// Like Plasma's ConfigView (deleted once hidden), a hidden dialog destroys
// its page on a later turn: the page's Component.onDestruction runs (it
// ends an Automatic backup hold) and its DataSources stop their helpers.
ApplicationWindow {
    id: dialog

    title: i18n("Hearthwire Settings")
    // Wide enough by default for General's form in two columns (it needs
    // about 34 grid units beside the category list); at the minimum the
    // form is one column and its widest row (Notifications, about 25 grid
    // units) still fits (review-4 S1; checked by the fixture checks).
    width: Kirigami.Units.gridUnit * 48
    height: Kirigami.Units.gridUnit * 35
    minimumWidth: Kirigami.Units.gridUnit * 39
    minimumHeight: Kirigami.Units.gridUnit * 21
    color: Kirigami.Theme.backgroundColor

    Material.theme: Kirigami.Theme.dark ? Material.Dark : Material.Light
    Material.accent: Kirigami.Theme.highlightColor
    Material.background: Kirigami.Theme.backgroundColor
    Material.foreground: Kirigami.Theme.textColor

    readonly property string packageBase: "qrc:/qt/qml/Hearthwire/Plasmoid/"
    property QtObject configModel: null
    property string currentSource
    property bool wasConfigurationChangedSignalSent: false
    readonly property Item currentPage: stack.currentItem
    readonly property bool applyEnabled: applyButton.enabled
    readonly property bool promptOpen: prompt.visible
    // The category a prompt was opened for; null = the dialog is closing.
    property QtObject pendingItem: null

    function load() {
        if (dialog.configModel)
            return true
        var component = Qt.createComponent(dialog.packageBase + "config.qml")
        if (component.status !== Component.Ready) {
            console.warn("config.qml:", component.errorString())
            return false
        }
        dialog.configModel = component.createObject(dialog)
        return dialog.configModel !== null
    }

    function openDialog() {
        if (!dialog.load())
            return
        // Plasma makes a new dialog for each opening: fresh pages, first
        // category, Apply off. While shown it only comes to the front.
        if (!dialog.visible) {
            stack.clear()
            dialog.wasConfigurationChangedSignalSent = false
            if (dialog.configModel.count > 0)
                dialog.open(dialog.configModel.get(0))
        }
        dialog.show()
        dialog.raise()
        dialog.requestActivate()
    }

    function closingAllowed() {
        if (applyButton.enabled) {
            dialog.pendingItem = null
            prompt.open()
            return false
        }
        return true
    }

    function saveConfig() {
        var config = Plasmoid.configuration
        var page = stack.currentItem
        // The page's own handling first, so it can still set cfg_ values.
        if (page.saveConfig)
            page.saveConfig()
        config.keys().forEach(function (key) {
            var cfgKey = "cfg_" + key
            if (cfgKey in page)
                config[key] = page[cfgKey]
        })
        Plasmoid.configuration.writeConfig()
    }

    function isConfigurationChanged() {
        var config = Plasmoid.configuration
        var page = stack.currentItem
        if (!page)
            return false
        return config.keys().some(function (key) {
            var cfgKey = "cfg_" + key
            if (!page.hasOwnProperty(cfgKey))
                return false
            return config[key] != page[cfgKey]
                && String(config[key]) != String(page[cfgKey])
        })
    }

    function settingValueChanged() {
        var page = stack.currentItem
        // A page going away (its onDestruction may still write settings).
        if (!page)
            return
        applyButton.enabled = dialog.wasConfigurationChangedSignalSent || dialog.isConfigurationChanged()
            || (page && page.unsavedChanges === true)
    }

    function open(item) {
        dialog.currentSource = item.source
        var config = Plasmoid.configuration
        var props = { "title": item.name }
        config.keys().forEach(function (key) {
            props["cfg_" + key] = config[key]
        })
        var url = Qt.resolvedUrl(dialog.packageBase + item.source)
        if (stack.depth === 0)
            stack.push(url, props)
        else
            stack.replace(url, props)
        applyButton.enabled = false
    }

    function openCategory(item) {
        if (applyButton.enabled) {
            dialog.pendingItem = item
            prompt.open()
            return
        }
        dialog.open(item)
    }

    function apply() {
        dialog.saveConfig()
        dialog.wasConfigurationChangedSignalSent = false
        applyButton.enabled = false
    }

    function accept() {
        applyButton.enabled = false
        dialog.close()
        dialog.apply()
    }

    function cancel() {
        if (dialog.closingAllowed())
            dialog.close()
    }

    function keyAccept(event) {
        event.accepted = true
        if (stack.currentItem)
            dialog.accept()
    }

    function discard() {
        dialog.wasConfigurationChangedSignalSent = false
        if (dialog.pendingItem) {
            dialog.open(dialog.pendingItem)
            prompt.close()
        } else {
            applyButton.enabled = false
            prompt.close()
            dialog.close()
        }
        dialog.pendingItem = null
    }

    // The app is quitting (its window was closed, task 012 R3.4): unapplied
    // changes are dropped, as Cancel + Discard would, without asking.
    function dropAndClose() {
        dialog.pendingItem = null
        dialog.wasConfigurationChangedSignalSent = false
        applyButton.enabled = false
        prompt.close()
        dialog.close()
    }

    onClosing: (close) => {
        close.accepted = dialog.closingAllowed()
    }

    // Later, not now: accept() closes first and then applies with the page
    // still there, as Plasma's deleteLater allows. Opened again meanwhile:
    // openDialog() has already made the new page, which stays.
    onVisibleChanged: {
        if (!dialog.visible)
            Qt.callLater(dialog.dropPages)
    }

    function dropPages() {
        if (dialog.visible)
            return
        stack.clear(StackView.Immediate)
        dialog.currentSource = ""
    }

    Connections {
        target: stack
        function onCurrentItemChanged() {
            var page = stack.currentItem
            if (page === null)
                return
            Plasmoid.configuration.keys().forEach(function (key) {
                var changed = page["cfg_" + key + "Changed"]
                if (changed)
                    changed.connect(dialog.settingValueChanged)
            })
            if (page.configurationChanged) {
                page.configurationChanged.connect(function () {
                    dialog.wasConfigurationChangedSignalSent = true
                    dialog.settingValueChanged()
                })
            }
            if (page.unsavedChangesChanged)
                page.unsavedChangesChanged.connect(dialog.settingValueChanged)
            if (page.settingValueChanged) {
                page.settingValueChanged.connect(function () {
                    dialog.wasConfigurationChangedSignalSent = true
                })
            }
        }
    }

    // The category list is as wide as its widest entry (within limits).
    Item {
        visible: false
        Repeater {
            id: measure
            model: dialog.configModel ? dialog.configModel.categories : []
            delegate: ItemDelegate {
                id: entry
                required property var modelData
                text: entry.modelData.name
                icon.name: entry.modelData.icon
            }
        }
    }
    readonly property real categoriesWidth: {
        var widest = Kirigami.Units.gridUnit * 9
        for (var i = 0; i < measure.count; i++) {
            var item = measure.itemAt(i)
            if (item)
                widest = Math.max(widest, item.implicitWidth)
        }
        return Math.min(Math.ceil(widest), Kirigami.Units.gridUnit * 16)
    }

    FocusScope {
        id: keys
        anchors.fill: parent
        focus: true

        Keys.onReturnPressed: (event) => dialog.keyAccept(event)
        Keys.onEnterPressed: (event) => dialog.keyAccept(event)
        Keys.onEscapePressed: (event) => {
            event.accepted = true
            dialog.cancel()
        }

        RowLayout {
            anchors.fill: parent
            spacing: 0

            ListView {
                id: categories
                objectName: "settingsCategories"
                Layout.fillHeight: true
                Layout.preferredWidth: dialog.categoriesWidth
                model: dialog.configModel ? dialog.configModel.categories : []
                delegate: ItemDelegate {
                    required property var modelData
                    width: ListView.view.width
                    visible: modelData.visible
                    text: modelData.name
                    icon.name: modelData.icon
                    highlighted: dialog.currentSource === modelData.source
                    onClicked: dialog.openCategory(modelData)
                }
            }
            Kirigami.Separator {
                Layout.fillHeight: true
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                Label {
                    Layout.fillWidth: true
                    Layout.margins: Kirigami.Units.largeSpacing
                    text: stack.currentItem ? stack.currentItem.title : ""
                    font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.35
                }
                StackView {
                    id: stack
                    objectName: "settingsStack"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                }
                Kirigami.Separator {
                    Layout.fillWidth: true
                }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.margins: Kirigami.Units.largeSpacing
                    spacing: Kirigami.Units.smallSpacing
                    Item {
                        Layout.fillWidth: true
                    }
                    Button {
                        objectName: "settingsOk"
                        icon.name: "dialog-ok"
                        text: i18n("OK")
                        onClicked: dialog.accept()
                    }
                    Button {
                        id: applyButton
                        objectName: "settingsApply"
                        enabled: false
                        icon.name: "dialog-ok-apply"
                        text: i18n("Apply")
                        visible: stack.currentItem !== null
                        onClicked: dialog.apply()
                    }
                    Button {
                        objectName: "settingsCancel"
                        icon.name: "dialog-cancel"
                        text: i18n("Cancel")
                        onClicked: dialog.cancel()
                    }
                }
            }
        }
    }

    Dialog {
        id: prompt
        objectName: "settingsPrompt"
        anchors.centerIn: parent
        modal: true
        title: i18n("Apply Settings")
        standardButtons: Dialog.Apply | Dialog.Discard | Dialog.Cancel
        Label {
            text: i18n("The current page has unsaved changes. Apply the changes or discard them?")
            wrapMode: Text.WordWrap
            width: Kirigami.Units.gridUnit * 20
        }
        onApplied: {
            dialog.apply()
            dialog.discard()
        }
        onDiscarded: dialog.discard()
        onRejected: dialog.pendingItem = null
    }
}
