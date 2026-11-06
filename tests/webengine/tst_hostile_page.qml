import QtQuick
import QtTest
import QtWebEngine
import "../../plasmoid/contents/ui"

// Runtime check of the real ChatWebView against a hostile chat site. Run
// only by tests/webengine/run.sh, inside a private network namespace: the
// site (claude.ai, https on 127.0.0.1 with a self-signed certificate that
// Chromium is told to accept) and a fake service on this computer are the
// only things that exist. The page tries every request the Chat tab must
// refuse and writes what it got into its title.
TestCase {
    id: testCase
    name: "HostilePage"
    width: 800
    height: 600
    visible: true
    when: windowShown

    function i18n(text) {
        var result = text
        for (var index = 1; index < arguments.length; index++)
            result = result.replace("%" + index, String(arguments[index]))
        return result
    }

    Component {
        id: webComponent
        ChatWebView {
            anchors.fill: parent
        }
    }

    // What the page reported, {} until it ran.
    function reported(view) {
        var title = view ? String(view.title) : ""
        if (title.indexOf("HS:") !== 0)
            return {}
        try {
            return JSON.parse(title.slice(3))
        } catch (error) {
            return {}
        }
    }

    // {site: [...], victim: [...]}: every request each fake server got.
    property var hits: null

    function fetchHits() {
        testCase.hits = null
        var request = new XMLHttpRequest()
        request.onreadystatechange = function () {
            if (request.readyState === XMLHttpRequest.DONE)
                testCase.hits = request.status === 200 ? JSON.parse(request.responseText) : { error: request.status }
        }
        request.open("GET", "http://127.0.0.1:3999/__hits")
        request.send()
        tryVerify(function () { return testCase.hits !== null }, 5000, "the fake servers did not answer")
        verify(testCase.hits.error === undefined, "hits: " + JSON.stringify(testCase.hits))
        return testCase.hits
    }

    function test_hostilePageGetsNothing() {
        var web = createTemporaryObject(webComponent, testCase, {})
        verify(web !== null)
        var asked = []
        web.siteIds = ["claude"]
        web.siteId = "claude"
        verify(web.currentView !== null)
        web.currentView.permissionRequested.connect(function (permission) {
            asked.push(permission.permissionType)
        })

        // Stay signed in is off: the profile is private and in memory only.
        var profile = web.currentView.profile
        compare(profile.offTheRecord, true)
        // Qt reports a placeholder path for an off-the-record profile; run.sh
        // checks that nothing is ever created there.
        verify(/\/QtWebEngine\/OffTheRecord$/.test(profile.persistentStoragePath), profile.persistentStoragePath)
        compare(profile.storageName, "")
        compare(profile.persistentCookiesPolicy, WebEngineProfile.NoPersistentCookies)
        compare(profile.httpCacheType, WebEngineProfile.MemoryHttpCache)

        tryVerify(function () { return testCase.reported(web.currentView).download === "asked" }, 30000,
                  "the hostile page never finished: " + web.currentView.title)
        var result = testCase.reported(web.currentView)

        // Every permission the page asks for is refused.
        compare(result.notification, "denied", JSON.stringify(result))
        verify(result.microphone !== "granted", JSON.stringify(result))
        verify(result.camera !== "granted", JSON.stringify(result))
        verify(result.location !== "granted", JSON.stringify(result))
        verify(result.clipboard !== "granted" && result.clipboard !== "ok", JSON.stringify(result))
        verify(asked.length > 0, "no permission request reached the view")

        // Settings stay as declared after the page ran.
        compare(web.currentView.settings.javascriptCanAccessClipboard, false)
        compare(web.currentView.settings.javascriptCanPaste, false)
        compare(web.currentView.settings.localContentCanAccessFileUrls, false)
        compare(web.currentView.settings.allowRunningInsecureContent, false)

        // A script-opened window opens no sign-in window and no prompt for
        // a page on this computer.
        compare(web.overlayOpen, false)
        compare(web.externalUrl, "")

        // The download waits for the user's Save.
        tryVerify(function () { return web.pendingDownload !== null }, 10000, "no download was offered")
        compare(web.pendingDownloadName, "hearthwire-test.bin")
        compare(web.pendingDownload.state, WebEngineDownloadRequest.DownloadRequested)
        wait(1500)
        verify(web.pendingDownload !== null)
        compare(web.pendingDownload.state, WebEngineDownloadRequest.DownloadRequested)

        // Nothing reached the service on this computer; the site was used.
        var got = testCase.fetchHits()
        compare(JSON.stringify(got.victim), "[]")
        verify(got.site.some(function (entry) { return / GET \/new$/.test(entry) }), JSON.stringify(got.site))
        verify(got.site.some(function (entry) { return / GET \/dl$/.test(entry) }), JSON.stringify(got.site))
        web.cancelDownload()
        compare(web.pendingDownload, null)
    }
}
