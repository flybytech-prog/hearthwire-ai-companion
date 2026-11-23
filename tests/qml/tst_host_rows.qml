import QtQuick
import QtTest
import "../../plasmoid/contents/ui/Host.js" as Host

// Host.js says which front end runs the pages: false in the widget, true in
// the hearthwire-hyprland app (its build rewrites that one file). The one
// panel-only row and the two storage texts follow it. The widget suite can't
// create the pages outside an applet, so the page checks run under the app's
// stand-ins only; Host.isApp itself is checked in both.
TestCase {
    id: testCase
    name: "HostRows"
    width: 400
    height: 400
    // The row is only visible when its page is shown.
    visible: true
    when: windowShown

    readonly property bool standIns: Qt.application.arguments.length > 0
        && /hearthwire-qmltests$/.test(String(Qt.application.arguments[0]))

    readonly property string appUnreadable: "The app's settings file couldn't be read safely, so nothing was exported. Check that ~/.config/hearthwire-hyprland/settings.json is a file of yours that only you can read and change, in a folder only you can open."
    readonly property string plasmaUnreadable: "Plasma's settings file for this widget couldn't be read safely, so nothing was exported. Check the owner and type of ~/.config/plasma-org.kde.plasma.desktop-appletsrc."
    readonly property string appChat: "Custom and added addresses are saved in the app's settings file (~/.config/hearthwire-hyprland/settings.json): don't put passwords, tokens or other secrets in them."
    readonly property string plasmaChat: "Custom and added addresses are saved in your Plasma configuration file: don't put passwords, tokens or other secrets in them."

    function findByName(item, name) {
        if (item.objectName === name)
            return item
        var lists = [item.children, item.data]
        for (var l = 0; l < lists.length; l++) {
            if (!lists[l])
                continue
            for (var i = 0; i < lists[l].length; i++) {
                var child = lists[l][i]
                if (!child || child.objectName === undefined)
                    continue
                var found = findByName(child, name)
                if (found)
                    return found
            }
        }
        return null
    }

    function findText(item, text) {
        if (item.text === text)
            return item
        var lists = [item.children, item.data]
        for (var l = 0; l < lists.length; l++) {
            if (!lists[l])
                continue
            for (var i = 0; i < lists[l].length; i++) {
                var child = lists[l][i]
                if (!child || child.objectName === undefined)
                    continue
                var found = findText(child, text)
                if (found)
                    return found
            }
        }
        return null
    }

    function page(file) {
        var component = Qt.createComponent(file)
        compare(component.status, Component.Ready, component.errorString())
        var item = createTemporaryObject(component, testCase)
        verify(item !== null)
        return item
    }

    function test_hostFlag() {
        compare(typeof Host.isApp, "boolean")
        // The app's build rewrites Host.js (sync_plasmoid.py), so the rows
        // below take the app's branches there.
        compare(Host.isApp, testCase.standIns, testCase.standIns ? "the app's Host.js" : "the widget's Host.js")
    }

    function test_shortcutRowOnlyInThePlasmaWidget() {
        if (!testCase.standIns)
            skip("the widget suite can't create the pages outside an applet; tests/mainqml checks the real files")
        var general = page("../../plasmoid/contents/ui/configGeneral.qml")
        var choice = findByName(general, "shortcutOpensChoice")
        verify(choice !== null)
        compare(choice.parent.visible, !Host.isApp)
        compare(choice.visible, !Host.isApp)
    }

    function test_unreadableText() {
        if (!testCase.standIns)
            skip("the widget suite can't create the pages outside an applet; tests/mainqml checks the real files")
        var general = page("../../plasmoid/contents/ui/configGeneral.qml")
        compare(general.backupText("settings-unreadable"),
                Host.isApp ? testCase.appUnreadable : testCase.plasmaUnreadable)
    }

    function test_chatAddressText() {
        if (!testCase.standIns)
            skip("the widget suite can't create the pages outside an applet; tests/mainqml checks the real files")
        var chat = page("../../plasmoid/contents/ui/configChat.qml")
        verify(findText(chat, Host.isApp ? testCase.appChat : testCase.plasmaChat) !== null)
        verify(findText(chat, Host.isApp ? testCase.plasmaChat : testCase.appChat) === null)
    }
}
