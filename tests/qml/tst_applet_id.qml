import QtQuick
import QtTest
import "../../plasmoid/contents/ui"
import "../../plasmoid/contents/ui/ChatStorage.js" as ChatStorage
import "../../plasmoid/contents/ui/InstallInfo.js" as InstallInfo
import "../../plasmoid/contents/ui/PromptLibrary.js" as PromptLibrary

// The hearthwire-hyprland app's applet id, 2**31 (core/frontend.py
// APP_APPLET_ID), must reach the chat storage (web-data) and vault commands
// exactly, and a Plasma widget's (small) id must give the same commands as
// before. main.qml keeps the id in chatAppletId and configGeneral.qml in
// vaultApplet, both `property double` (an int wraps 2**31 to -2147483648).
//
// Runs in the widget suite (qmltestrunner) and under the app's stand-ins
// (hearthwire-qmltests). The holders below have the two properties' type and
// expressions; under the stand-ins, whose Plasmoid.id is the app id, the
// real main.qml and configGeneral.qml are loaded too. The widget suite can't
// create them outside an applet; tests/mainqml (test_main_qml_wiring.py)
// checks the real files there, for both ids.
TestCase {
    id: testCase
    name: "AppletId"

    readonly property double appId: 2147483648
    readonly property bool standIns: Qt.application.arguments.length > 0
        && /hearthwire-qmltests$/.test(String(Qt.application.arguments[0]))

    function i18n(text) {
        var result = text
        for (var index = 1; index < arguments.length; index++)
            result = result.replace("%" + index, arguments[index])
        return result
    }
    function i18nc(context, text) {
        return i18n.apply(null, Array.prototype.slice.call(arguments, 1))
    }
    function i18np(singular, plural, count) {
        return i18n.apply(null, [count === 1 ? singular : plural].concat(Array.prototype.slice.call(arguments, 2)))
    }

    Component {
        id: holders
        QtObject {
            property var plasmoidId
            // As main.qml and configGeneral.qml declare them.
            readonly property double chatAppletId: ChatStorage.validInt(plasmoidId)
            readonly property double vaultApplet: Math.max(0, ChatStorage.validInt(plasmoidId))
            // What an int would make of it (the bug the doubles fix).
            readonly property int asInt: ChatStorage.validInt(plasmoidId)
        }
    }

    function rows() {
        return [{tag: "app id", id: 2147483648, text: "2147483648"},
                {tag: "plasma id", id: 7, text: "7"},
                {tag: "first plasma id", id: 1, text: "1"}]
    }

    function test_theIdKeepsItsExactDigits_data() {
        return rows()
    }

    function test_theIdKeepsItsExactDigits(data) {
        var holder = createTemporaryObject(holders, testCase, {plasmoidId: data.id})
        compare(holder.chatAppletId, data.id)
        compare(holder.vaultApplet, data.id)
        compare(String(holder.chatAppletId), data.text)
        compare("" + holder.vaultApplet, data.text)
        verify(Number.isInteger(holder.chatAppletId))
        compare(ChatStorage.validInt(holder.chatAppletId), data.id)
        compare(InstallInfo.validInt(holder.vaultApplet), true)
        // The form a double prints in never has an exponent or a fraction.
        verify(!/[e.]/i.test(String(holder.chatAppletId)), String(holder.chatAppletId))
    }

    function test_anIntWouldWrapTheAppId() {
        var holder = createTemporaryObject(holders, testCase, {plasmoidId: testCase.appId})
        compare(holder.asInt, -2147483648)
        compare(ChatStorage.webDataCommand("remove", "encrypted", holder.asInt, null, null, 5), "")
    }

    function test_oddIdsStayRefused() {
        var bad = [-1, 2147483649, 1.5, "7", null, undefined, NaN]
        for (var index = 0; index < bad.length; index++) {
            var holder = createTemporaryObject(holders, testCase, {plasmoidId: bad[index]})
            compare(holder.chatAppletId, -1, String(bad[index]))
            compare(holder.vaultApplet, 0, String(bad[index]))
        }
    }

    function test_chatStorageCommandsNameTheIdExactly_data() {
        return rows()
    }

    function test_chatStorageCommandsNameTheIdExactly(data) {
        var holder = createTemporaryObject(holders, testCase, {plasmoidId: data.id})
        var applet = holder.chatAppletId
        var prefix = "env HEARTHWIRE_RUN=5 HEARTHWIRE_APPLET=" + data.text + " python3 -P -m hearthwire "
        var store = " --store encrypted --applet " + data.text
        compare(ChatStorage.webDataCommand("prepare", "encrypted", applet, 3, null, 5, ["claude"]),
                prefix + "--web-data prepare" + store + " --generation 3 --sites claude")
        compare(ChatStorage.webDataCommand("prune", "encrypted", applet, 3, null, 5, ["claude", "user-0a1b2c3d"]),
                prefix + "--web-data prune" + store + " --generation 3 --known claude,user-0a1b2c3d")
        compare(ChatStorage.webDataCommand("remove-site", "encrypted", applet, 3, null, 5, "claude"),
                prefix + "--web-data remove-site" + store + " --generation 3 --site claude")
        compare(ChatStorage.webDataCommand("remove", "encrypted", applet, null, 3, 5),
                prefix + "--web-data remove" + store + " --keep 3")
        compare(ChatStorage.webDataCommand("remove", "encrypted", applet, null, null, 5), prefix + "--web-data remove" + store)
        compare(ChatStorage.profileName(applet, 3), "applet-" + data.text + "-g3")
        compare(ChatStorage.vaultCommand("status", 5, applet), prefix + "--vault status")
        compare(ChatStorage.vaultCommand("unlock", 5, applet, "wallet"), prefix + "--vault unlock --method wallet")
        // main.qml's prompt library and dropped-file reads use Math.max(0, chatAppletId).
        compare(PromptLibrary.promptsCommand("list", 5, Math.max(0, applet)), prefix + "--prompts list")
        compare(PromptLibrary.readDroppedCommand("2f61", 5, Math.max(0, applet)), prefix + "--read-dropped 2f61")
    }

    function test_vaultPageCommandsNameTheIdExactly_data() {
        return rows()
    }

    function test_vaultPageCommandsNameTheIdExactly(data) {
        var holder = createTemporaryObject(holders, testCase, {plasmoidId: data.id})
        var applet = holder.vaultApplet
        var prefix = "env HEARTHWIRE_RUN=5 HEARTHWIRE_APPLET=" + data.text + " python3 -P -m hearthwire "
        compare(ChatStorage.vaultCommand("status", 5, applet), prefix + "--vault status")
        compare(ChatStorage.vaultCommand("add-key", 5, applet, "wallet"), prefix + "--vault add-key --method wallet")
        compare(InstallInfo.command(5, applet, false),
                "env HEARTHWIRE_RUN=5 HEARTHWIRE_APPLET=" + data.text + " python3 -P -s -m hearthwire --install-info")
    }

    // F1b: the four views that carry the id into the helper's commands and
    // the profile names must keep 2**31 exact (a `property int` wraps it).
    Component {
        id: ownerCheckComponent
        LocalOwnerCheck {
            property var commands: []
            runOwnerCheck: function (command) { commands.push(command) }
        }
    }
    Component {
        id: ollamaComponent
        OllamaChatView {
            property var commands: []
            current: true
            siteEnabled: true
            runOwnerCheck: function (command) { commands.push(command) }
            createRequest: function () { return null }
        }
    }
    Component {
        id: chatViewComponent
        ChatView {
            webSource: Qt.resolvedUrl("ChatWebStub.qml")
        }
    }

    function test_localOwnerCheckKeepsTheId_data() {
        return rows()
    }

    function test_localOwnerCheckKeepsTheId(data) {
        var check = createTemporaryObject(ownerCheckComponent, testCase, {appletId: data.id})
        compare(check.appletId, data.id)
        check.start(3000)
        compare(check.commands.length, 1)
        compare(check.commands[0].replace(/HEARTHWIRE_RUN=\d+/, "HEARTHWIRE_RUN=5"),
                "env HEARTHWIRE_RUN=5 HEARTHWIRE_APPLET=" + data.text + " python3 -P -m hearthwire --port-owner 3000")
    }

    function test_ollamaChatViewKeepsTheId_data() {
        return rows()
    }

    function test_ollamaChatViewKeepsTheId(data) {
        var view = createTemporaryObject(ollamaComponent, testCase, {appletId: data.id, width: 300, height: 300})
        verify(view !== null)
        compare(view.appletId, data.id)
        compare(String(view.appletId), data.text)
        verify(view.commands.length >= 1)
        verify(view.commands[0].indexOf(" HEARTHWIRE_APPLET=" + data.text + " python3 -P -m hearthwire --port-owner ") > 0,
               view.commands[0])
    }

    function test_chatViewKeepsTheIdsAndPassesThem_data() {
        return rows()
    }

    function test_chatViewKeepsTheIdsAndPassesThem(data) {
        var view = createTemporaryObject(chatViewComponent, testCase,
            {appletId: data.id, storageApplet: data.id, width: 300, height: 300})
        verify(view !== null)
        compare(view.appletId, data.id)
        compare(view.storageApplet, data.id)
        compare(String(view.storageApplet), data.text)
    }

    function test_chatWebViewKeepsTheIdsInProfilesAndChecks_data() {
        return rows()
    }

    function test_chatWebViewKeepsTheIdsInProfilesAndChecks(data) {
        var web = createTemporaryObject(webComponent, testCase, {
            staySignedIn: true, runtimeDir: "/nonexistent/run",
            storageApplet: data.id, storageGeneration: 4, appletId: data.id
        })
        verify(web !== null)
        compare(web.storageApplet, data.id)
        compare(web.appletId, data.id)
        web.preparedSites = ["claude"]
        compare(web.siteProfileSpec("claude"), {
            saved: true,
            sitePath: "/nonexistent/run/hearthwire/vault/web/applet-" + data.text + "-g4/site-claude",
            siteName: "applet-" + data.text + "-g4-claude"
        })
        var check = null
        for (var index = 0; index < web.children.length; index++) {
            if (web.children[index].objectName === "localOwnerCheck")
                check = web.children[index]
        }
        verify(check !== null)
        compare(check.appletId, data.id)
        var commands = []
        check.runOwnerCheck = function (command) { commands.push(command) }
        check.start(3000)
        compare(commands.length, 1)
        verify(commands[0].indexOf(" HEARTHWIRE_APPLET=" + data.text + " python3 -P -m hearthwire --port-owner 3000") > 0,
               commands[0])
    }

    Component {
        id: webComponent
        ChatWebView { width: 300; height: 300 }
    }

    // Under the stand-ins only: the real files with the app's Plasmoid.id.
    function test_realFilesUnderTheStandIns() {
        if (!testCase.standIns)
            skip("the widget suite can't create main.qml outside an applet; tests/mainqml checks the real files")
        var mainComponent = Qt.createComponent("../../plasmoid/contents/ui/main.qml")
        compare(mainComponent.status, Component.Ready, mainComponent.errorString())
        var main = createTemporaryObject(mainComponent, testCase)
        verify(main !== null)
        compare(main.chatAppletId, testCase.appId)
        var gen = main.chatGeneration
        verify(gen >= 0)
        var prefix = "env HEARTHWIRE_RUN=5 HEARTHWIRE_APPLET=2147483648 python3 -P -m hearthwire "
        compare(main.chatCommand("remove", 5), prefix + "--web-data remove --store encrypted --applet 2147483648")
        compare(main.chatCommand("prepare", 5),
                prefix + "--web-data prepare --store encrypted --applet 2147483648 --generation " + gen)
        compare(main.chatCommand("status", 5), prefix + "--vault status")
        compare(main.chatProfileName, "applet-2147483648-g" + gen)

        var pageComponent = Qt.createComponent("../../plasmoid/contents/ui/configGeneral.qml")
        compare(pageComponent.status, Component.Ready, pageComponent.errorString())
        var page = createTemporaryObject(pageComponent, testCase)
        verify(page !== null)
        compare(page.vaultApplet, testCase.appId)
        compare(ChatStorage.vaultCommand("status", 5, page.vaultApplet), prefix + "--vault status")
    }
}
