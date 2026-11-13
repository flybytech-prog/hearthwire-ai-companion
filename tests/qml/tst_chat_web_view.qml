import QtQuick
import QtTest
import QtWebEngine
import "../../plasmoid/contents/ui"

// ChatWebView's Local owner gate with a real, off-the-record Qt WebEngine
// view and a fake port owner helper. The Local address is 127.0.0.1:9,
// where nothing listens: no page is ever served and nothing leaves this
// computer.
TestCase {
    id: testCase
    name: "ChatWebView"
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

    readonly property string home: "http://127.0.0.1:9/"
    property var commands: []

    Component {
        id: webComponent
        ChatWebView {
            anchors.fill: parent
        }
    }

    function init() {
        testCase.commands = []
    }

    function ownerCheck(web) {
        for (var index = 0; index < web.children.length; index++) {
            if (web.children[index].objectName === "localOwnerCheck")
                return web.children[index]
        }
        return null
    }

    // A Local web view with the fake helper, before any site is chosen.
    function make() {
        var web = createTemporaryObject(webComponent, testCase, {})
        verify(web !== null)
        var check = ownerCheck(web)
        verify(check !== null)
        check.runOwnerCheck = function (command) { testCase.commands.push(command) }
        web.customUrls = { local: testCase.home }
        web.siteIds = ["local", "claude"]
        web.siteId = "local"
        return web
    }

    function answer(web, owner) {
        var check = ownerCheck(web)
        verify(check.busy, "no owner check is running")
        check.ownerDone(check.sourceName, { ok: true, owner: owner })
    }

    function waitForCheck(count) {
        tryVerify(function () { return testCase.commands.length === count }, 3000,
                  "expected " + count + " owner checks, got " + testCase.commands.length)
        verify(/ --port-owner 9$/.test(testCase.commands[count - 1]), testCase.commands[count - 1])
    }

    // Addresses the view really tried to reach. A rejected navigation ends
    // as an abort (-3) or not at all; a load that went out fails with
    // "connection refused", as nothing listens on port 9. (The url property
    // already shows a rejected address, so it proves nothing.)
    property var tried: []

    function watch(view) {
        view.loadingChanged.connect(function (info) {
            if (info.errorCode !== 0 && info.errorCode !== -3)
                testCase.tried.push(info.url.toString())
        })
    }

    function waitForTry(url) {
        tryVerify(function () { return testCase.tried.indexOf(url) >= 0 }, 5000, "never tried " + url)
    }

    // No Local view exists before the helper answered self or system.
    function test_localViewIsCreatedOnlyAfterAGoodCheck() {
        testCase.tried = []
        var web = make()
        waitForCheck(1)
        compare(web.currentView, null)
        answer(web, "other")
        compare(web.currentView, null)
        compare(web.localOwnerProblem, "other")
        compare(web.localOwnerPort, 9)

        web.retryLocalOwner()
        waitForCheck(2)
        compare(web.localOwnerProblem, "")
        answer(web, "none")
        compare(web.currentView, null)
        compare(web.localOwnerProblem, "not-running")

        web.retryLocalOwner()
        waitForCheck(3)
        answer(web, "self")
        verify(web.currentView !== null)
        watch(web.currentView)
        compare(web.localOwnerProblem, "")
        // The good check's pass let the first load through: no second check.
        waitForTry(testCase.home)
        compare(testCase.commands.length, 3)
    }

    // Every later main-frame navigation to this computer is checked again;
    // a bad answer blanks the page instead of loading.
    function test_everyNavigationIsCheckedAndABadAnswerBlanks() {
        testCase.tried = []
        var web = make()
        waitForCheck(1)
        answer(web, "system")
        verify(web.currentView !== null)
        var view = web.currentView
        watch(view)
        waitForTry(testCase.home)

        var next = testCase.home + "c/1"
        view.url = next
        waitForCheck(2)
        wait(200)
        compare(testCase.tried.indexOf(next), -1, "loaded before the check answered")
        answer(web, "other")
        compare(web.localOwnerProblem, "other")
        tryVerify(function () { return view.url.toString() === "about:blank" }, 5000)
        compare(view.ownerPass, "")
        wait(200)
        compare(testCase.tried.indexOf(next), -1, "loaded after a bad answer")

        // Retry goes home through the gate again; a good answer loads it once.
        testCase.tried = []
        web.retryLocalOwner()
        waitForCheck(3)
        wait(200)
        compare(testCase.tried, [])
        answer(web, "self")
        waitForTry(testCase.home)
        compare(testCase.commands.length, 3)
    }

    // A check that never answers loads nothing; the timeout fails closed.
    function test_noAnswerLoadsNothing() {
        var web = make()
        ownerCheck(web).timeout = 50
        waitForCheck(1)
        tryVerify(function () { return web.localOwnerProblem === "owner-unknown" }, 3000)
        compare(web.currentView, null)
    }

    // --- pass for "Send the form again" (N4) ----------------------------------

    // A Local view after a good first check, with its home tried.
    function makeLocalView() {
        testCase.tried = []
        var web = make()
        waitForCheck(1)
        answer(web, "self")
        verify(web.currentView !== null)
        watch(web.currentView)
        waitForTry(testCase.home)
        return web
    }

    // What localOwnerFinished gets after a checked form post.
    function grantFormPass(web, url) {
        web.ownerPending = { view: web.currentView, url: url, port: 9, form: true, create: false }
        web.localOwnerFinished(9, "")
        compare(web.localOwnerProblem, "resend")
        compare(web.currentView.ownerPass, url)
    }

    function test_formPassExpires() {
        var web = makeLocalView()
        web.ownerPassLifetime = 200
        grantFormPass(web, testCase.home + "form")
        tryVerify(function () { return web.currentView.ownerPass === "" }, 3000)
        compare(web.localOwnerProblem, "")
    }

    // Even if the timer is late, a stale pass doesn't count: a new check.
    function test_staleFormPassIsNotUsed() {
        var web = makeLocalView()
        var next = testCase.home + "form"
        grantFormPass(web, next)
        web.currentView.ownerPassExpires = Date.now() - 1
        web.currentView.url = next
        waitForCheck(2)
        wait(200)
        compare(testCase.tried.indexOf(next), -1, "a stale pass let the load through")
    }

    function test_formPassEndsOnDismissAndOnAProblem() {
        var web = makeLocalView()
        grantFormPass(web, testCase.home + "form")
        web.dismissLocalOwner()
        compare(web.currentView.ownerPass, "")
        compare(web.localOwnerProblem, "")

        grantFormPass(web, testCase.home + "form")
        web.ownerPending = { view: web.currentView, url: testCase.home + "x", port: 9, form: false, create: false }
        web.localOwnerFinished(9, "other")
        compare(web.localOwnerProblem, "other")
        compare(web.currentView.ownerPass, "")
    }

    // --- open in browser prompt (N1) ------------------------------------------

    function test_pageRequestsOnlyAsk() {
        var web = createTemporaryObject(webComponent, testCase, {})
        verify(web !== null)
        web.externalPromptGap = 100
        web.askExternal("https://example.net/a?x=1")
        compare(web.externalUrl, "https://example.net/a?x=1")
        compare(web.externalHost, "example.net")
        // One at a time: a second request while one waits is dropped.
        web.askExternal("https://other.example/")
        compare(web.externalUrl, "https://example.net/a?x=1")
        compare(web.externalHost, "example.net")
        web.clearExternal()
        compare(web.externalUrl, "")
        compare(web.externalHost, "")
        // Rate limit: right after a prompt, requests are dropped.
        web.askExternal("https://other.example/")
        compare(web.externalUrl, "")
        wait(150)
        web.askExternal("https://other.example/")
        compare(web.externalHost, "other.example")
        web.clearExternal()
        wait(150)
        // Nothing that isn't https with a readable host.
        web.askExternal("http://example.net/")
        web.askExternal("https://ev%69l.example/")
        web.askExternal("file:///etc/passwd")
        web.askExternal("")
        compare(web.externalUrl, "")
        // Qt WebEngine hands over look-alike letters in their xn-- form,
        // and the prompt names them that way; raw ones are dropped.
        web.askExternal("https://сlaude.ai/")
        compare(web.externalUrl, "")
        web.askExternal("https://xn--laude-0ye.ai/")
        compare(web.externalHost, "xn--laude-0ye.ai")
        // Changing the site drops the prompt.
        web.siteIds = ["local"]
        web.siteId = "local"
        compare(web.externalUrl, "")
        // Open with nothing waiting opens nothing.
        web.acceptExternal()
        compare(web.externalUrl, "")
    }

    // --- sign-in window title (N5) --------------------------------------------

    function test_blankSignInWindowNamesItsOpener() {
        // The window needs its opener's profile: the Local page comes first.
        var web = localView({})
        var title = findChild(web, "overlayTitle")
        verify(title !== null)
        compare(title.textFormat, Text.PlainText)
        // The window is never loaded here; it stays blank.
        web.openOverlay({ openIn: function (view) {} }, "local", testCase.home + "chat")
        verify(web.overlayOpen)
        compare(web.overlayTitle.kind, "opener")
        compare(title.text, "Window opened by 127.0.0.1")
        web.overlayView.url = "about:blank"
        tryVerify(function () { return web.overlayView.url.toString() === "about:blank" }, 3000)
        compare(title.text, "Window opened by 127.0.0.1")
        web.closeOverlay()
        web.openOverlay({ openIn: function (view) {} }, "local", "about:blank")
        compare(title.text, "Window opened by an unknown page")
        web.closeOverlay()
        verify(!web.overlayOpen)
    }

    // --- zoom -----------------------------------------------------------

    function localView(zoomMap) {
        var web = make()
        web.zoomMap = zoomMap
        waitForCheck(1)
        answer(web, "self")
        var view = web.currentView
        verify(view !== null)
        // The view isn't loading yet when it is created: its load starts a
        // moment later, and a zoom changed during a load is only undone
        // (zoomedWhileLoading). So wait for that load's own end; Chromium
        // refuses port 9, so it fails quickly. Connected before the event
        // loop runs again, so the start can't be missed.
        var ended = false
        view.loadingChanged.connect(function (info) {
            if (info.status !== WebEngineLoadingInfo.LoadStartedStatus)
                ended = true
        })
        tryVerify(function () { return ended && !view.loading }, 5000, "the first load ended")
        return web
    }

    function test_zoomFollowsTheMap() {
        var web = localView({local: 1.25})
        var view = web.currentView
        fuzzyCompare(view.zoomFactor, 1.25, 0.001)
        web.zoomMap = {local: 0.8, claude: 2.0}
        fuzzyCompare(view.zoomFactor, 0.8, 0.001)
        web.zoomMap = {}
        fuzzyCompare(view.zoomFactor, 1.0, 0.001)
    }

    // Chromium's own Ctrl+wheel zoom moves zoomFactor by 0.1 a notch: one
    // step that way is handed up for the page's site, never stored here.
    function test_wheelZoomIsSnappedAndReported() {
        var web = localView({local: 1.25})
        var view = web.currentView
        var asked = []
        web.siteZoomRequested.connect(function (siteId, factor) { asked.push([siteId, factor]) })
        // What main.qml does with the request.
        web.siteZoomRequested.connect(function (siteId, factor) {
            var map = Object.assign({}, web.zoomMap)
            map[siteId] = factor
            web.zoomMap = map
        })
        view.zoomFactor = 1.35
        tryVerify(function () { return asked.length === 1 })
        compare(asked[0][0], "local")
        compare(asked[0][1], 1.5)
        tryVerify(function () { return Math.abs(view.zoomFactor - 1.5) < 0.001 })
        // Back on the binding, and no feedback loop.
        wait(100)
        compare(asked.length, 1)
        web.zoomMap = {local: 0.75}
        fuzzyCompare(view.zoomFactor, 0.75, 0.001)
        compare(asked.length, 1)
        // Down one step.
        view.zoomFactor = 0.65
        tryVerify(function () { return asked.length === 2 })
        compare(asked[1], ["local", 0.67])
        tryVerify(function () { return Math.abs(view.zoomFactor - 0.67) < 0.001 })
        // Past the last step: nothing more to store, the zoom comes back.
        web.zoomMap = {local: 2.0}
        view.zoomFactor = 2.1
        tryVerify(function () { return Math.abs(view.zoomFactor - 2.0) < 0.001 })
        wait(100)
        compare(asked.length, 2)
    }

    // main.qml may refuse (e.g. an unknown id): the stored zoom comes back.
    function test_refusedWheelZoomGoesBack() {
        var web = localView({local: 1.25})
        var view = web.currentView
        var asked = 0
        web.siteZoomRequested.connect(function () { asked += 1 })
        view.zoomFactor = 1.35
        tryVerify(function () { return asked === 1 })
        tryVerify(function () { return Math.abs(view.zoomFactor - 1.25) < 0.001 })
        wait(100)
        compare(asked, 1)
    }

    // --- split view ---------------------------------------------------------------

    // Pane a and pane b both on the Local site (nothing listens on port 9).
    function splitViews() {
        var web = localView({})
        // The test window is narrow; pages side by side from 300 px here.
        web.splitMinWidth = 300
        web.siteIdB = "local"
        web.splitActive = true
        // Pane b's Local view goes through its own owner check, too.
        waitForCheck(2)
        compare(web.currentViewB, null)
        answer(web, "self")
        verify(web.currentViewB !== null)
        return web
    }

    function test_splitCreatesAndDestroysPaneB() {
        var web = splitViews()
        var a = web.currentView
        var b = web.currentViewB
        verify(a !== b)
        compare(a.pane, "a")
        compare(b.pane, "b")
        verify(web.splitShown)
        verify(a.visible && b.visible)
        // Side by side: b in the right half.
        verify(b.mapToItem(web, 0, 0).x >= web.width / 2 - 1)
        verify(a.width < web.width && b.width < web.width)
        // The same site in both panes shares that site's one profile.
        verify(a.profile !== null)
        verify(a.profile === b.profile)
        verify(a.profile === web.profileFor("local"))
        // Split off: pane b's page is destroyed, a keeps its page.
        web.splitActive = false
        compare(web.currentViewB, null)
        compare(web.currentView, a)
        tryVerify(function () { return web.viewFor("local", "b") === null })
        compare(a.width, web.width)
        compare(testCase.commands.length, 2)
    }

    function test_splitPaneFocusDrivesTheToolbarAndZoom() {
        var web = splitViews()
        compare(web.activePane, "a")
        compare(web.paneView, web.currentView)
        web.currentViewB.forceActiveFocus()
        tryCompare(web, "focusedPane", "b")
        compare(web.activePane, "b")
        compare(web.paneView, web.currentViewB)
        compare(web.activeSiteId, "local")
        web.currentView.forceActiveFocus()
        tryCompare(web, "focusedPane", "a")
        // Each pane's page has its own Chromium zoom, reported for its site.
        var asked = []
        web.siteZoomRequested.connect(function (siteId, factor) { asked.push([siteId, factor]) })
        web.currentViewB.zoomFactor = 1.05
        tryVerify(function () { return asked.length === 1 })
        compare(asked[0], ["local", 1.1])
        fuzzyCompare(web.currentView.zoomFactor, 1.0, 0.001)
    }

    function test_splitTooNarrowShowsPaneAOnly() {
        var web = splitViews()
        web.currentViewB.forceActiveFocus()
        tryCompare(web, "focusedPane", "b")
        web.splitMinWidth = 100000
        verify(!web.splitShown)
        verify(!web.currentViewB.visible)
        compare(web.currentView.width, web.width)
        // The toolbar acts on pane a again.
        compare(web.activePane, "a")
        compare(web.paneView, web.currentView)
    }

    // M1: pane a's navigation check replaces pane b's create check; pane b's
    // view is still created once it is done.
    function test_splitCreateCheckSurvivesANavigationCheck() {
        var web = localView({})
        web.splitMinWidth = 300
        web.siteIdB = "local"
        web.splitActive = true
        waitForCheck(2)
        // Pane a navigates to this computer before pane b's answer came.
        web.currentView.url = testCase.home + "chat"
        waitForCheck(3)
        answer(web, "self")
        compare(web.currentViewB, null)
        // Pane b's create check runs again, then its view comes.
        waitForCheck(4)
        answer(web, "self")
        verify(web.currentViewB !== null)
        compare(web.currentViewB.pane, "b")
    }

    // S1 / N1: a sign-in window belongs to its pane.
    function test_splitSignInWindowStaysWithItsPane() {
        var web = splitViews()
        web.currentViewB.forceActiveFocus()
        tryCompare(web, "focusedPane", "b")
        web.overlayPane = "b"
        web.openOverlay({ openIn: function (view) {} }, "local", "about:blank")
        verify(web.overlayOpen)
        compare(web.activeView, web.overlayView)
        // Pane a's toolbar and notices stay with pane a's page.
        web.currentView.forceActiveFocus()
        tryCompare(web, "focusedPane", "a")
        compare(web.activeView, web.currentView)
        // Home in pane a leaves pane b's window open.
        web.home()
        verify(web.overlayOpen)
        // Too narrow: pane b's window hides with pane b, never over pane a.
        var overlay = null
        for (var index = 0; index < web.children.length; index++) {
            if (web.children[index].objectName === "signInOverlay")
                overlay = web.children[index]
        }
        verify(overlay !== null)
        verify(overlay.visible)
        verify(overlay.mapToItem(web, 0, 0).x >= web.width / 2 - 1)
        web.splitMinWidth = 100000
        verify(!overlay.visible)
        verify(web.overlayOpen)
        web.splitMinWidth = 300
        verify(overlay.visible)
        web.closeOverlay()
    }

    // S3: a new site in pane b drops a waiting prompt.
    function test_splitSiteChangeClearsPrompts() {
        var web = splitViews()
        web.externalPromptGap = 0
        web.externalQuietUntil = 0
        web.askExternal("https://example.org/x")
        compare(web.externalHost, "example.org")
        web.passkeyNotice = true
        web.siteIds = ["local", "claude"]
        web.siteIdB = "claude"
        compare(web.externalUrl, "")
        verify(!web.passkeyNotice)
        // Back to Local before anything loads from the network.
        web.splitActive = false
    }

    // --- one profile per site -------------------------------------------------

    // Built-ins may not use this computer; .invalid never resolves, so
    // nothing is loaded from anywhere.
    readonly property var nowhere: ({ claude: "https://claude.invalid/", chatgpt: "https://chatgpt.invalid/" })

    function twoSites() {
        var web = createTemporaryObject(webComponent, testCase, {})
        verify(web !== null)
        web.customUrls = testCase.nowhere
        web.siteIds = ["claude", "chatgpt", "gemini"]
        web.siteId = "claude"
        verify(web.currentView !== null)
        web.siteId = "chatgpt"
        verify(web.currentView !== null)
        return web
    }

    function test_eachSiteGetsItsOwnProfile() {
        var web = twoSites()
        var claude = web.viewFor("claude", "a")
        var chatgpt = web.viewFor("chatgpt", "a")
        verify(claude !== null && chatgpt !== null)
        var first = web.profileFor("claude")
        var second = web.profileFor("chatgpt")
        verify(first !== null && second !== null)
        verify(first !== second, "two sites, two profiles")
        compare(claude.profile, first)
        compare(chatgpt.profile, second)
        // Memory mode: each one off the record, with no storage name.
        verify(first.offTheRecord && second.offTheRecord)
        compare(first.storageName, "")
        // Only the sites opened have one; never Ollama or an unknown id.
        compare(web.profileFor("gemini"), null)
        compare(web.profileFor("ollama"), null)
        compare(web.profileFor("toString"), null)
        compare(web.profileFor(""), null)
        compare(Object.keys(web.profiles).sort(), ["chatgpt", "claude"])
        // Switching back keeps the site's view and profile.
        web.siteId = "claude"
        compare(web.currentView, claude)
        compare(web.profileFor("claude"), first)
    }

    function test_noProfileForOllamaOrUnknownIds() {
        var web = createTemporaryObject(webComponent, testCase, {})
        verify(web !== null)
        compare(web.ensureProfile("ollama"), null)
        compare(web.ensureProfile("user-1234567"), null)
        compare(web.ensureProfile("claude2"), null)
        compare(web.ensureProfile(undefined), null)
        compare(Object.keys(web.profiles), [])
        // A site without a profile gets no view either.
        web.siteIds = ["ollama"]
        web.siteId = "ollama"
        compare(web.currentView, null)
    }

    // Google sign-in's user agent is per profile: one site's switch leaves
    // the others alone.
    function test_userAgentSwitchStaysWithItsProfile() {
        var web = twoSites()
        var first = web.profileFor("claude")
        var second = web.profileFor("chatgpt")
        verify(web.baseUserAgent !== "")
        compare(first.httpUserAgent, web.baseUserAgent)
        compare(second.httpUserAgent, web.baseUserAgent)
        // Each profile's choice looks only at its own site's pages.
        var claudeUrl = web.viewFor("claude", "a").url.toString()
        compare(web.viewUrls("claude", null, ""), [claudeUrl])
        compare(web.viewUrls("chatgpt", null, ""), [web.viewFor("chatgpt", "a").url.toString()])
        compare(web.viewUrls("claude", web.viewFor("claude", "a"), "https://accounts.google.com/x"),
                ["https://accounts.google.com/x"])
        compare(web.viewUrls("gemini", null, ""), [])
        web.applyUserAgent(first, "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0")
        verify(first.httpUserAgent !== web.baseUserAgent)
        compare(second.httpUserAgent, web.baseUserAgent)
        // No page of claude is on Google sign-in: the sync puts it back.
        tryVerify(function () {
            web.syncUserAgent()
            return first.httpUserAgent === web.baseUserAgent
        }, 5000)
        compare(second.httpUserAgent, web.baseUserAgent)
    }

    // The sign-in window uses its opener's profile; a site without one
    // opens nothing.
    function test_signInWindowUsesItsOpenersProfile() {
        var web = twoSites()
        web.openOverlay({ openIn: function (view) {} }, "claude", "https://claude.invalid/")
        verify(web.overlayOpen)
        compare(web.overlayView.profile, web.profileFor("claude"))
        verify(web.overlayView.profile !== web.profileFor("chatgpt"))
        web.closeOverlay()
        web.openOverlay({ openIn: function (view) {} }, "gemini", "https://gemini.google.com/")
        verify(!web.overlayOpen)
        compare(web.profileFor("gemini"), null)
    }

    // Clear <site> data: only that site's views and profile go; the
    // profile only once its views are gone, and a new one comes after.
    function test_clearSiteDropsOnlyThatSite() {
        var web = twoSites()
        var claude = web.profileFor("claude")
        var chatgpt = web.profileFor("chatgpt")
        web.openOverlay({ openIn: function (view) {} }, "chatgpt", "https://chatgpt.invalid/")
        verify(web.overlayOpen)
        web.clearSite("chatgpt")
        compare(web.viewFor("chatgpt", "a"), null)
        verify(!web.overlayOpen)
        compare(web.profileFor("chatgpt"), null)
        // Not yet: a new one waits until the old one is destroyed.
        compare(web.ensureProfile("chatgpt"), null)
        compare(web.profileFor("claude"), claude)
        verify(web.viewFor("claude", "a") !== null)
        // chatgpt is shown: it comes back with a new, empty profile.
        tryVerify(function () { return web.currentView !== null }, 3000)
        verify(web.profileFor("chatgpt") !== null)
        verify(web.profileFor("chatgpt") !== chatgpt)
        compare(web.currentView.profile, web.profileFor("chatgpt"))
        compare(web.profileFor("claude"), claude)
        // Odd ids change nothing.
        web.clearSite("ollama")
        web.clearSite("")
        compare(web.profileFor("claude"), claude)
    }

    // Saved sign-ins: a site's view waits for its prepared folder, never
    // opens privately; the name and path come only from ChatStorage with
    // the site's own id. (No saved profile is created here: that is
    // checked in the lab.)
    function test_savedProfileWaitsForThePreparedFolder() {
        var web = createTemporaryObject(webComponent, testCase, {
            staySignedIn: true,
            runtimeDir: "/nonexistent/run",
            storageApplet: 3,
            storageGeneration: 4
        })
        verify(web !== null)
        web.customUrls = testCase.nowhere
        web.siteIds = ["claude", "chatgpt"]
        web.siteId = "claude"
        compare(web.currentView, null)
        compare(web.profileFor("claude"), null)
        compare(web.siteProfileSpec("claude"), null)
        verify(web.siteWaits("claude", "a"))
        var wait = findChild(web, "siteWaitA")
        verify(wait !== null && wait.visible)
        // Nothing shown, then prepared: only the spec is looked at.
        web.siteIds = []
        web.preparedSites = ["claude", "ollama"]
        compare(web.siteProfileSpec("claude"), {
            saved: true,
            sitePath: "/nonexistent/run/hearthwire/vault/web/applet-3-g4/site-claude",
            siteName: "applet-3-g4-claude"
        })
        compare(web.siteProfileSpec("chatgpt"), null)
        compare(web.siteProfileSpec("ollama"), null)
        compare(Object.keys(web.profiles), [])
    }

    function test_memoryProfileSpecIsPrivate() {
        var web = createTemporaryObject(webComponent, testCase, {})
        verify(web !== null)
        web.preparedSites = ["claude"]
        compare(web.siteProfileSpec("claude"), { saved: false, sitePath: "", siteName: "" })
        compare(web.siteProfileSpec("gemini"), { saved: false, sitePath: "", siteName: "" })
        compare(web.siteProfileSpec("ollama"), null)
        verify(!web.siteWaits("claude", "a"))
    }

    // SEC-L1: a shown site with saved sign-ins and no fresh prepare asks
    // main.qml for one (each time its pane is synced), never opens.
    function test_savedSiteWithoutAFreshPrepareAsksForOne() {
        var web = createTemporaryObject(webComponent, testCase, {
            staySignedIn: true,
            runtimeDir: "/nonexistent/run",
            storageApplet: 3,
            storageGeneration: 4
        })
        verify(web !== null)
        var wanted = []
        web.siteWanted.connect(function (siteId) { wanted.push(siteId) })
        web.customUrls = testCase.nowhere
        web.siteIds = ["claude", "chatgpt"]
        web.siteId = "claude"
        compare(web.currentView, null)
        verify(wanted.indexOf("claude") >= 0)
        wanted = []
        web.siteIdB = "chatgpt"
        web.splitActive = true
        verify(wanted.indexOf("chatgpt") >= 0)
        compare(Object.keys(web.profiles), [])
        // Ollama and unknown ids are never asked for.
        wanted = []
        web.siteIds = ["ollama"]
        web.siteId = "ollama"
        web.splitActive = false
        compare(wanted, [])
    }

    // In memory mode nothing is ever asked for.
    function test_memoryModeNeverAsksForAPrepare() {
        var web = createTemporaryObject(webComponent, testCase, {})
        var wanted = []
        web.siteWanted.connect(function (siteId) { wanted.push(siteId) })
        web.customUrls = testCase.nowhere
        web.siteIds = ["claude"]
        web.siteId = "claude"
        verify(web.currentView !== null)
        compare(wanted, [])
        // Not while a cleared site's old profile is still going either.
        var old = web.profileFor("claude")
        web.clearSite("claude")
        web.syncViews()
        tryVerify(function () { return web.profileFor("claude") !== null && web.profileFor("claude") !== old }, 3000)
        compare(wanted, [])
    }

    // SEC-I1: preparedSites as a list from C++ (no JS Array) still works.
    QtObject {
        id: holder
        property list<string> ids: ["claude"]
    }

    function test_preparedSitesFromCpp() {
        verify(!Array.isArray(holder.ids))
        var web = createTemporaryObject(webComponent, testCase, {
            staySignedIn: true,
            runtimeDir: "/nonexistent/run",
            storageApplet: 3,
            storageGeneration: 4
        })
        web.preparedSites = holder.ids
        verify(web.siteProfileSpec("claude") !== null)
        compare(web.siteProfileSpec("chatgpt"), null)
        web.preparedSites = "claude"
        compare(web.siteProfileSpec("claude"), null)
    }

    // SEC-L2: siteReleased comes only after the profile is destroyed (and
    // for a site without one, too), never at once.
    function test_siteReleasedFollowsTheProfileDestroy() {
        var web = twoSites()
        var states = []
        web.siteReleased.connect(function (siteId) {
            states.push({site: siteId, profile: web.profileFor(siteId), retiring: web.retiring[siteId] === true,
                         views: web.viewList().filter(function (view) { return view.site === siteId }).length})
        })
        web.siteId = "claude"
        web.clearSite("chatgpt")
        compare(states, [], "not at once")
        tryVerify(function () { return states.length === 1 }, 3000)
        compare(states[0], {site: "chatgpt", profile: null, retiring: false, views: 0})
        // A site without a profile is released too (a moment later).
        web.clearSite("gemini")
        compare(states.length, 1)
        tryVerify(function () { return states.length === 2 }, 3000)
        compare(states[1].site, "gemini")
    }

    // --- task 005: added sites ------------------------------------------------

    // Addresses where nothing is served (.invalid never resolves).
    readonly property var added: [
        { id: "user-3fa9c01b", name: "Le Chat", url: "https://lechat.invalid/chat" },
        { id: "user-0000beef", name: "Pi", url: "https://pi.invalid/" }
    ]

    // A built-in and two added sites, each shown once (memory mode).
    function addedSites() {
        var web = createTemporaryObject(webComponent, testCase, {})
        verify(web !== null)
        web.customUrls = testCase.nowhere
        web.userSites = testCase.added
        web.siteIds = ["claude", "user-3fa9c01b", "user-0000beef"]
        web.siteId = "claude"
        verify(web.currentView !== null)
        web.siteId = "user-3fa9c01b"
        verify(web.currentView !== null)
        web.siteId = "user-0000beef"
        verify(web.currentView !== null)
        return web
    }

    // Each added site has a profile of its own: never a built-in's, never
    // another added site's, never none.
    function test_addedSiteGetsItsOwnProfile() {
        var web = addedSites()
        var claude = web.profileFor("claude")
        var lechat = web.profileFor("user-3fa9c01b")
        var pi = web.profileFor("user-0000beef")
        verify(claude !== null && lechat !== null && pi !== null)
        verify(lechat !== claude && pi !== claude && pi !== lechat)
        compare(web.viewFor("user-3fa9c01b", "a").profile, lechat)
        compare(web.viewFor("user-0000beef", "a").profile, pi)
        verify(lechat.offTheRecord && pi.offTheRecord)
        compare(Object.keys(web.profiles).sort(), ["claude", "user-0000beef", "user-3fa9c01b"])
        // Its own address is its home.
        compare(web.viewFor("user-3fa9c01b", "a").homeUrl, "https://lechat.invalid/chat")
        compare(web.activeSiteName, "Pi")
    }

    // Without its entry an added id gets no view (its home is unknown).
    function test_addedIdWithoutItsEntryLoadsNothing() {
        var web = createTemporaryObject(webComponent, testCase, {})
        web.customUrls = testCase.nowhere
        web.siteIds = ["user-3fa9c01b"]
        web.siteId = "user-3fa9c01b"
        compare(web.currentView, null)
        compare(web.profileFor("user-3fa9c01b"), null)
        // Its entry arrives: now it opens.
        web.userSites = testCase.added
        web.syncViews()
        verify(web.currentView !== null)
        compare(web.currentView.homeUrl, "https://lechat.invalid/chat")
    }

    // The sign-in window of an added site uses that site's profile.
    function test_addedSiteSignInWindowUsesItsProfile() {
        var web = addedSites()
        web.openOverlay({ openIn: function (view) {} }, "user-3fa9c01b", "https://lechat.invalid/")
        verify(web.overlayOpen)
        compare(web.overlayView.profile, web.profileFor("user-3fa9c01b"))
        verify(web.overlayView.profile !== web.profileFor("claude"))
        verify(web.overlayView.profile !== web.profileFor("user-0000beef"))
        web.closeOverlay()
    }

    // Saved sign-ins: the saved path is site-user-…, and only once its
    // folder is prepared.
    function test_addedSiteSavedProfileSpec() {
        var web = createTemporaryObject(webComponent, testCase, {
            staySignedIn: true,
            runtimeDir: "/nonexistent/run",
            storageApplet: 3,
            storageGeneration: 4
        })
        var wanted = []
        web.siteWanted.connect(function (siteId) { wanted.push(siteId) })
        web.userSites = testCase.added
        web.siteIds = ["user-3fa9c01b"]
        web.siteId = "user-3fa9c01b"
        compare(web.currentView, null)
        compare(web.siteProfileSpec("user-3fa9c01b"), null)
        verify(wanted.indexOf("user-3fa9c01b") >= 0)
        web.siteIds = []
        web.preparedSites = ["user-3fa9c01b"]
        compare(web.siteProfileSpec("user-3fa9c01b"), {
            saved: true,
            sitePath: "/nonexistent/run/hearthwire/vault/web/applet-3-g4/site-user-3fa9c01b",
            siteName: "applet-3-g4-user-3fa9c01b"
        })
        compare(web.siteProfileSpec("user-0000beef"), null)
        compare(Object.keys(web.profiles), [])
    }

    // Removal: clearSite drops the site's views and profile, then says it
    // is released; also for a site that never had one.
    function test_addedSiteClearAndRelease() {
        var web = addedSites()
        var released = []
        web.siteReleased.connect(function (siteId) { released.push(siteId) })
        var claude = web.profileFor("claude")
        web.userSites = [testCase.added[1]]
        web.siteIds = ["claude", "user-0000beef"]
        web.clearSite("user-3fa9c01b")
        compare(web.viewFor("user-3fa9c01b", "a"), null)
        compare(web.profileFor("user-3fa9c01b"), null)
        tryVerify(function () { return released.indexOf("user-3fa9c01b") >= 0 }, 3000)
        // Not made again: it is no longer a site.
        wait(50)
        compare(web.profileFor("user-3fa9c01b"), null)
        compare(web.profileFor("claude"), claude)
        web.clearSite("user-00c0ffee")
        tryVerify(function () { return released.indexOf("user-00c0ffee") >= 0 }, 3000)
    }

    // A download prompt names the added site that asked.
    function test_downloadNamesTheAddedSite() {
        var web = addedSites()
        var cancelled = 0
        web.handleDownload({ isSavePageDownload: false, downloadFileName: "notes.txt",
                             view: { site: "user-3fa9c01b" }, cancel: function () { cancelled++ } })
        compare(web.pendingDownloadSite, "Le Chat")
        compare(web.pendingDownloadSiteId, "user-3fa9c01b")
        web.cancelDownload()
        compare(cancelled, 1)
    }

    // A new address on the same host moves the open view home.
    function test_addedSiteAddressChangeMovesHome() {
        var web = addedSites()
        var view = web.viewFor("user-3fa9c01b", "a")
        var profile = web.profileFor("user-3fa9c01b")
        web.userSites = [{ id: "user-3fa9c01b", name: "Le Chat", url: "https://lechat.invalid/other" },
                         testCase.added[1]]
        compare(view.homeUrl, "https://lechat.invalid/other")
        compare(web.profileFor("user-3fa9c01b"), profile)
    }

    // Round 2 (SEC L-2): an added site moved to another host never goes there
    // with its old profile; the view is blanked until main.qml drops the
    // site, which then comes back with a new profile on the new host.
    function test_addedSiteOnAnotherHostIsNeverLoadedWithItsOldProfile() {
        var web = addedSites()
        var view = web.viewFor("user-3fa9c01b", "a")
        var profile = web.profileFor("user-3fa9c01b")
        web.siteId = "user-3fa9c01b"
        web.userSites = [{ id: "user-3fa9c01b", name: "Le Chat", url: "https://elsewhere.invalid/" },
                         testCase.added[1]]
        compare(view.url.toString(), "about:blank")
        compare(view.homeUrl, "https://lechat.invalid/chat", "not moved")
        compare(web.profileFor("user-3fa9c01b"), profile)
        // Home refuses too.
        web.home()
        compare(view.url.toString(), "about:blank")
        // main.qml's dropSites: views and profile go; a new profile, the new home.
        web.clearSite("user-3fa9c01b")
        tryVerify(function () {
            var next = web.viewFor("user-3fa9c01b", "a")
            return next !== null && next !== view && next.homeUrl === "https://elsewhere.invalid/"
        }, 3000)
        verify(web.profileFor("user-3fa9c01b") !== profile)
        compare(web.viewFor("user-3fa9c01b", "a").profile, web.profileFor("user-3fa9c01b"))
    }
}
