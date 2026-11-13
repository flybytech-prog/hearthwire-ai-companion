import QtQuick
import QtCore
import QtTest
import "../../../plasmoid/contents/ui"

// Real saved (on-disk) per-site profiles, for test_main_qml_wiring.py, which
// runs this file with HOME, TMPDIR and XDG_RUNTIME_DIR in a fresh temporary
// folder and then checks that Qt WebEngine wrote only inside each site's own
// folder (no stray QtWebEngine folder anywhere else). Anywhere else (the
// real session, checks.sh's tests/qml run) it refuses to start: the
// runtime and home folders must carry the names the Python test gives them.
TestCase {
    id: testCase
    name: "ProfileFolders"
    width: 400
    height: 400
    visible: true
    when: windowShown

    function i18n(text) {
        var result = text
        for (var index = 1; index < arguments.length; index++)
            result = result.replace("%" + index, String(arguments[index]))
        return result
    }

    readonly property string runtime: String(StandardPaths.writableLocation(StandardPaths.RuntimeLocation))
        .replace(/^file:\/\//, "")
    readonly property string home: String(StandardPaths.writableLocation(StandardPaths.HomeLocation))
        .replace(/^file:\/\//, "")
    readonly property string base: testCase.runtime + "/hearthwire/vault/web/applet-3-g4"
    // .invalid never resolves: nothing is loaded from anywhere.
    readonly property var nowhere: ({ claude: "https://claude.invalid/", chatgpt: "https://chatgpt.invalid/" })

    Component {
        id: webComponent
        ChatWebView {
            anchors.fill: parent
        }
    }

    function initTestCase() {
        if (!/\/hw-profile-folders$/.test(testCase.runtime) || !/\/hw-profile-home$/.test(testCase.home))
            fail("run only by tests/test_main_qml_wiring.py, never with a real session's folders")
    }

    function test_savedProfilesStayInTheirSiteFolders() {
        var web = createTemporaryObject(webComponent, testCase, {
            staySignedIn: true,
            runtimeDir: testCase.runtime,
            storageApplet: 3,
            storageGeneration: 4,
            preparedSites: ["claude", "chatgpt"]
        })
        verify(web !== null)
        web.customUrls = testCase.nowhere
        web.siteIds = ["claude", "chatgpt"]
        web.siteId = "claude"
        verify(web.currentView !== null)
        web.siteId = "chatgpt"
        verify(web.currentView !== null)
        var claude = web.profileFor("claude")
        var chatgpt = web.profileFor("chatgpt")
        verify(claude !== chatgpt)
        compare(claude.offTheRecord, false)
        compare(claude.persistentStoragePath, testCase.base + "/site-claude")
        compare(claude.storageName, "applet-3-g4-claude")
        compare(chatgpt.persistentStoragePath, testCase.base + "/site-chatgpt")
        // Let Chromium open and write its files.
        tryVerify(function () { return !web.currentView.loading }, 10000)
        wait(1500)

        // REV-L1: the cleared site's pane shows the busy indicator again as
        // soon as its old profile is gone (its folder isn't prepared now).
        web.siteId = "claude"
        var spinner = findChild(web, "siteWaitA")
        verify(spinner !== null)
        verify(!spinner.visible)
        web.preparedSites = ["chatgpt"]
        var released = []
        web.siteReleased.connect(function (siteId) { released.push(siteId) })
        web.clearSite("claude")
        tryVerify(function () { return released.length === 1 }, 3000)
        compare(released, ["claude"])
        tryVerify(function () { return spinner.visible }, 3000, "the waiting pane shows its indicator")
        compare(web.profileFor("claude"), null)
        web.destroy()
        wait(1500)
    }
}
