import QtQuick
import QtQuick.Dialogs
import QtQuick.Layouts
import QtQuick.Window
import QtWebEngine
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents
import "ChatSites.js" as ChatSites
import "ChatStorage.js" as ChatStorage
import "SettingsLogic.js" as SettingsLogic

// The only file that touches Qt WebEngine. Every chat site has its own
// profile (cookies, storage, cache, service workers, permissions), created
// by ensureProfile right before the site's first view; no profile is shared
// between sites. By default each is off the record: everything stays in
// memory and vanishes when the profile or this item is destroyed (Clear
// <site> data, Clear chat data) or Plasma restarts. Only with "Stay signed
// in" and a verified, unlocked encrypted folder does ChatView create this
// item with staySignedIn set; then a site's cookies and site storage live in
// its own site-<id> folder inside that folder (HTTP cache stays in memory),
// and only once main.qml has prepared that folder: until then the site's
// view waits, it never opens privately instead. The profile kind is fixed
// for the item's lifetime: ChatView recreates it instead of changing it (a
// live switch crashes Qt WebEngine).
// Pages are never read or scripted, and their console output is dropped.
//
// Local web UI pages on this computer, and those of added sites on this
// computer or the home network (ChatSites.ownerChecked), load only after
// the helper said the port belongs to this user or the system, or (a home
// network site, with its address) that the address isn't this computer's
// (LocalOwnerCheck): before the site's view is created and before each of
// its main-frame navigations to its own pages. Anything else loads nothing
// and shows a message instead.
//
// Split view: a second pane (b) shows siteIdB next to the first, with its
// own pages; the same site in both panes shares that site's profile. Its
// pages exist only while split is on and are destroyed when it is turned
// off. Every rule below holds for both panes; the pages are never scripted.
//
// A page never opens the system browser by itself: an address it hands over
// (a clicked link off the site, a clicked window) only asks "Open <host> in
// your browser?" in ChatView, one at a time; Open there or the toolbar's
// Open in browser are the only ways out.
Item {
    id: chatWeb

    // Set once through the Loader's initial properties, before any profile
    // exists. Defaults are private in-memory profiles. With staySignedIn,
    // the parts every site's folder and name are built from
    // (ChatStorage.siteProfilePath / siteProfileName).
    property bool staySignedIn: false
    property string runtimeDir: ""
    property int storageApplet: -1
    property int storageGeneration: -1
    // Sites whose folder main.qml prepared in this generation; a saved
    // profile is made only for these.
    property var preparedSites: []

    // {siteId: profile}, filled only by ensureProfile. Never reassigned, so
    // a page's profile binding is evaluated once.
    readonly property var profiles: ({})
    // {siteId: true} while a dropped profile still waits to be destroyed;
    // no new profile is made for that site until it is gone.
    readonly property var retiring: ({})
    // Bumped whenever profiles or retiring change (they never notify), so
    // bindings that read them (siteWaits) are evaluated again.
    property int profilesRevision: 0

    // Enabled site ids (catalog order) and the one being shown.
    property var siteIds: []
    property string siteId: ""
    // Validated {siteId: url} custom addresses; set before siteId so the
    // first load already uses them.
    property var customUrls: ({})
    // The added sites [{id, name, url}] (main.qml's ok-or-not read), set
    // before siteId too; every ChatSites call gets them.
    property var userSites: []
    // Only makes the owner check's helper source name unique.
    property int appletId: 0
    // Per-site zoom {siteId: factor}; a sign-in window uses its site's.
    property var zoomMap: ({})

    // A page was zoomed with Ctrl+wheel (Chromium's own zoom): main.qml
    // stores factor, a ZOOM_STEPS value, for siteId. Never written here.
    signal siteZoomRequested(string siteId, real factor)
    // Saved sign-ins: a shown site has no profile and may not get one yet;
    // main.qml prepares (and so verifies) its folder again first.
    signal siteWanted(string siteId)
    // Clear <site> data: the site's profile is destroyed (or it had none);
    // only now may its folder be deleted.
    signal siteReleased(string siteId)

    // Split view (runtime only): pane b shows siteIdB. Below splitMinWidth
    // only pane a is shown (its pages stay).
    property bool splitActive: false
    property string siteIdB: ""
    property real splitMinWidth: Kirigami.Units.gridUnit * 40
    readonly property bool splitShown: chatWeb.splitActive && chatWeb.width >= chatWeb.splitMinWidth
    // The pane the toolbar, the zoom keys and the notices act on: the one
    // that last had the keyboard focus.
    property string focusedPane: "a"
    readonly property string activePane: chatWeb.splitShown && chatWeb.focusedPane === "b" ? "b" : "a"
    readonly property string activeSiteId: chatWeb.activePane === "b" ? chatWeb.siteIdB : chatWeb.siteId
    // The pane whose page opened the sign-in window; it covers that pane.
    property string overlayPane: "a"

    property var currentView: null
    property var currentViewB: null
    readonly property var paneView: chatWeb.activePane === "b" ? chatWeb.currentViewB : chatWeb.currentView
    readonly property bool overlayOpen: chatWeb.overlayView !== null
    // The sign-in window counts only for the pane it belongs to; the other
    // pane's toolbar and notices stay with that pane's page.
    readonly property bool overlayActive: chatWeb.overlayView !== null && chatWeb.overlayPane === chatWeb.activePane
    readonly property var activeView: chatWeb.overlayActive ? chatWeb.overlayView : chatWeb.paneView
    readonly property bool canGoBack: !!chatWeb.activeView && chatWeb.activeView.canGoBack
    readonly property bool loading: !!chatWeb.activeView && chatWeb.activeView.loading
    readonly property real loadProgress: chatWeb.activeView
        ? chatWeb.activeView.loadProgress / 100 : 0
    readonly property bool pageFailed: !!chatWeb.activeView && chatWeb.activeView.failed
    readonly property bool pageCrashed: !!chatWeb.activeView && chatWeb.activeView.crashed
    readonly property bool canOpenExternally: !!chatWeb.activeView
        && ChatSites.isPageUrl(
            ChatSites.effectiveSite(chatWeb.activeView.site, chatWeb.customUrls, chatWeb.userSites),
            chatWeb.activeView.url.toString())

    // Title of the sign-in window: {kind: "page"|"opener"|"unknown", host}.
    readonly property var overlayTitle: chatWeb.overlayView
        ? ChatSites.overlayHost({
            url: chatWeb.overlayView.url.toString(),
            openerUrl: chatWeb.overlayView.openerUrl
        })
        : ({kind: "unknown", host: ""})

    // Off-site notice for the page shown: {off, host} from ChatSites.
    readonly property var offSite: chatWeb.activeView
        ? ChatSites.offSiteHost({
            siteId: chatWeb.activeView.site,
            customUrls: chatWeb.customUrls,
            userSites: chatWeb.userSites,
            url: chatWeb.activeView.url.toString()
        })
        : ({off: false, host: ""})
    readonly property string activeSiteName: {
        var site = chatWeb.activeView ? ChatSites.byId(chatWeb.activeView.site, chatWeb.userSites) : null
        return site ? site.name : ""
    }

    // Local web UI owner check. Problem codes as OllamaChat.ownerProblem,
    // plus "resend" after a checked form post; port is the one checked.
    property string localOwnerProblem: ""
    property int localOwnerPort: 0
    readonly property bool localOwnerChecking: localOwner.busy
    // What waits for the check: {view, url, port, form, create, pane, site,
    // address}, or null.
    property var ownerPending: null
    // The address a good check before creating an owner-checked view was
    // made for, and that view's site; handed to it as its first pass.
    property string localCreatePass: ""
    property string localCreateSite: ""
    // Retry's views still to check, one at a time (REV M-1).
    property var ownerRetries: []
    // How long a pass is good for (ms); overridable by tests only.
    property int ownerPassLifetime: 10000

    // A page's request to open an address in the system browser, waiting
    // for Open or Cancel: the address and its ASCII host, "" when none.
    property string externalUrl: ""
    property string externalHost: ""
    // Requests sooner than this (ms) after the last prompt was shown or
    // answered are dropped; overridable by tests only.
    property int externalPromptGap: 3000
    property double externalQuietUntil: 0

    property bool dialogOpen: false
    property bool passkeyNotice: false
    property var overlayView: null
    property var pendingDownload: null
    property string pendingDownloadName: ""
    // The catalog name of the site whose page started it ("" if unknown).
    property string pendingDownloadSite: ""
    // That site's id, so clearing the site drops its download too.
    property string pendingDownloadSiteId: ""
    // The page a pending upload dialog belongs to.
    property var uploadView: null

    // The first profile's own user agent (QtWebEngine token stripped) and
    // client hints, captured once; every profile starts with them and gets
    // them back whenever none of its pages is on Google sign-in.
    property string baseUserAgent: ""
    property bool baseClientHintsEnabled: true
    property var baseBrands: ({})

    function goBack() {
        if (chatWeb.activeView)
            chatWeb.activeView.goBack()
    }

    function reload() {
        if (!chatWeb.activeView)
            return
        chatWeb.activeView.failed = false
        chatWeb.activeView.crashed = false
        chatWeb.activeView.reload()
    }

    function home() {
        if (chatWeb.overlayActive)
            chatWeb.closeOverlay()
        var url = ChatSites.homeUrl(chatWeb.activeSiteId, chatWeb.customUrls, chatWeb.userSites)
        if (!chatWeb.paneView || url === "")
            return
        // Never an added site's new host with its old profile (M1).
        if (ChatSites.isUserSiteId(chatWeb.paneView.site)
                && chatWeb.hostOf(url) !== chatWeb.hostOf(chatWeb.paneView.homeUrl))
            return
        chatWeb.paneView.url = url
    }

    // The toolbar's Open in browser: the user's own click, for a page of
    // the current site only.
    function openExternally() {
        if (chatWeb.canOpenExternally)
            Qt.openUrlExternally(chatWeb.activeView.url)
    }

    // A page wants url in the system browser: only asks. Dropped while
    // another prompt waits, right after one, or without a readable host.
    function askExternal(url) {
        var now = Date.now()
        if (chatWeb.externalUrl !== "" || now < chatWeb.externalQuietUntil
                || !ChatSites.isHttpsUrl(url))
            return
        var host = ChatSites.shortHost(ChatSites.displayHost(url))
        if (host === "")
            return
        chatWeb.externalQuietUntil = now + chatWeb.externalPromptGap
        chatWeb.externalHost = host
        chatWeb.externalUrl = url
    }

    // Open on the prompt: the user's answer, the only other way out.
    function acceptExternal() {
        var url = chatWeb.externalUrl
        chatWeb.clearExternal()
        if (ChatSites.isHttpsUrl(url))
            Qt.openUrlExternally(url)
    }

    function clearExternal() {
        chatWeb.externalUrl = ""
        chatWeb.externalHost = ""
        chatWeb.externalQuietUntil = Date.now() + chatWeb.externalPromptGap
    }

    function focusView() {
        if (chatWeb.activeView)
            chatWeb.activeView.forceActiveFocus()
    }

    // Local and added sites on this computer: whether siteId's pages there
    // wait for the owner check.
    function ownerChecked(siteId) {
        return ChatSites.ownerChecked(siteId, chatWeb.customUrls, chatWeb.userSites)
    }

    // An owner-checked site's main-frame navigation (or creating its view,
    // view null) waits for the owner check; the request itself was already
    // rejected. pane: where a view created after the check goes ("a" or
    // "b"); siteId: the site checked.
    function checkLocalOwner(view, url, form, create, pane, siteId) {
        var site = typeof siteId === "string" ? siteId : ""
        var port = ChatSites.localOwnerPort({ siteId: site, customUrls: chatWeb.customUrls,
                                              userSites: chatWeb.userSites, url: url })
        // A home-network site's address, checked with the port (LOW-2).
        var address = ChatSites.localOwnerAddress({ siteId: site, customUrls: chatWeb.customUrls,
                                                    userSites: chatWeb.userSites, url: url })
        // A Retry check this one replaces waits for its turn again.
        var replaced = chatWeb.ownerPending
        if (replaced && replaced.retry === true && replaced.view)
            chatWeb.ownerRetries = [replaced.view].concat(chatWeb.ownerRetries)
        // A late answer of an earlier check must not count for this one.
        localOwner.cancel()
        chatWeb.ownerPending = { view: view, url: url, port: port, form: form, create: create,
                                 pane: pane === "b" ? "b" : "a", site: site, address: address }
        chatWeb.localOwnerPort = port
        // Never from inside the navigation request itself.
        Qt.callLater(function () {
            // chatWeb is null once this item is gone.
            if (chatWeb && chatWeb.ownerPending && chatWeb.ownerPending.url === url)
                localOwner.start(port, address)
        })
    }

    function localOwnerFinished(port, problem) {
        var pending = chatWeb.ownerPending
        if (!pending || pending.port !== port || (pending.address || "") !== localOwner.address)
            return
        chatWeb.ownerPending = null
        if (problem !== "") {
            // Fail closed: nothing from this computer stays on screen, so a
            // page loaded earlier can't keep talking to the new listener.
            chatWeb.localOwnerProblem = problem
            chatWeb.ownerRetries = []
            chatWeb.blankLocalViews(port)
            return
        }
        chatWeb.localOwnerProblem = ""
        // The next view Retry waits to check, once this one is done.
        Qt.callLater(chatWeb.nextOwnerRetry)
        // A pane's owner-checked view still to create (its check waited for
        // this one).
        if (!pending.create && chatWeb.localViewMissing())
            Qt.callLater(chatWeb.syncViews)
        if (pending.create) {
            var site = pending.site
            if (chatWeb.siteIds.indexOf(site) < 0 || chatWeb.viewFor(site, pending.pane) !== null
                    || (pending.pane === "b" && !chatWeb.splitActive) || !chatWeb.ensureProfile(site))
                return
            chatWeb.localCreatePass = pending.url
            chatWeb.localCreateSite = site
            visitedSites.append({ site: site, pane: pending.pane })
            // The other pane may wait for its own check.
            Qt.callLater(chatWeb.syncViews)
            return
        }
        var view = pending.view
        if (!view || chatWeb.viewList().indexOf(view) < 0)
            return
        view.ownerPass = pending.url
        view.ownerPassExpires = Date.now() + chatWeb.ownerPassLifetime
        ownerPassTimer.restart()
        // A form post can't be replayed; the user sends it again.
        if (pending.form) {
            chatWeb.localOwnerProblem = "resend"
            return
        }
        view.url = pending.url
    }

    // Every pass ends: on any problem, on Dismiss and when it expires.
    function clearOwnerPasses() {
        ownerPassTimer.stop()
        chatWeb.localCreatePass = ""
        chatWeb.localCreateSite = ""
        var views = chatWeb.viewList()
        for (var index = 0; index < views.length; index++)
            views[index].ownerPass = ""
    }

    // Dismiss on "Send the form again", or the pass for it expired.
    function dismissLocalOwner() {
        chatWeb.clearOwnerPasses()
        chatWeb.localOwnerProblem = ""
    }

    // A check of port failed: every pass ends, and every view (any site)
    // whose page is on that port of this computer goes blank (M-D). Views
    // on other ports stay: only this listener changed hands.
    function blankLocalViews(port) {
        chatWeb.clearOwnerPasses()
        var views = chatWeb.viewList()
        for (var index = 0; index < views.length; index++) {
            var view = views[index]
            var viewPort = ChatSites.localOwnerPort({ siteId: view.site, customUrls: chatWeb.customUrls,
                                                      userSites: chatWeb.userSites,
                                                      url: view.url.toString() })
            if (viewPort > 0 && viewPort === port)
                view.url = "about:blank"
        }
    }

    // With saved sign-ins, a pane's site still waits for main.qml to
    // prepare its folder: no view, no profile, none allowed yet.
    function siteWaits(siteId, pane) {
        return chatWeb.profilesRevision >= 0 && chatWeb.staySignedIn && chatWeb.siteIds.indexOf(siteId) >= 0
            && chatWeb.viewFor(siteId, pane) === null && !chatWeb.profileFor(siteId)
            && !chatWeb.siteProfileSpec(siteId)
    }

    // A shown pane has an owner-checked site without its view yet.
    function localViewMissing() {
        var panes = [["a", chatWeb.siteId], ["b", chatWeb.splitActive ? chatWeb.siteIdB : ""]]
        for (var index = 0; index < panes.length; index++) {
            var site = panes[index][1]
            if (site !== "" && chatWeb.siteIds.indexOf(site) >= 0 && chatWeb.ownerChecked(site)
                    && chatWeb.viewFor(site, panes[index][0]) === null)
                return true
        }
        return false
    }

    // Retry after a problem: create a missing owner-checked view again, and
    // check again only the shown owner-checked views that are blank or on
    // the failed port, one at a time; a healthy view on another port keeps
    // its page (REV M-1).
    function retryLocalOwner() {
        var failedPort = chatWeb.localOwnerPort
        chatWeb.localOwnerProblem = ""
        var queue = []
        var panes = [["a", chatWeb.siteId], ["b", chatWeb.splitActive ? chatWeb.siteIdB : ""]]
        for (var index = 0; index < panes.length; index++) {
            var site = panes[index][1]
            var view = site !== "" && chatWeb.ownerChecked(site) ? chatWeb.viewFor(site, panes[index][0]) : null
            if (!view || view.homeUrl === "")
                continue
            var url = view.url.toString()
            var port = ChatSites.localOwnerPort({ siteId: site, customUrls: chatWeb.customUrls,
                                                  userSites: chatWeb.userSites, url: url })
            if (url === "" || ChatSites.isAboutBlank(url) || (port > 0 && port === failedPort))
                queue.push(view)
        }
        chatWeb.ownerRetries = queue
        // A missing view comes through its own check (syncViews runs one
        // at a time); the queue waits for it.
        if (chatWeb.localViewMissing())
            chatWeb.syncViews()
        chatWeb.nextOwnerRetry()
    }

    // Starts the next Retry check unless one is running; never cancels one.
    function nextOwnerRetry() {
        while (!chatWeb.ownerPending && chatWeb.ownerRetries.length > 0) {
            var queue = chatWeb.ownerRetries.slice()
            var view = queue.shift()
            chatWeb.ownerRetries = queue
            if (chatWeb.viewList().indexOf(view) < 0 || view.homeUrl === "")
                continue
            if (ChatSites.localOwnerPort({ siteId: view.site, customUrls: chatWeb.customUrls,
                                           userSites: chatWeb.userSites, url: view.homeUrl }) === 0) {
                view.url = view.homeUrl
                continue
            }
            chatWeb.checkLocalOwner(view, view.homeUrl, false, false, view.pane, view.site)
            chatWeb.ownerPending.retry = true
        }
    }

    function closeOverlay() {
        if (!chatWeb.overlayView)
            return
        var view = chatWeb.overlayView
        chatWeb.overlayView = null
        view.destroy()
        Qt.callLater(chatWeb.syncUserAgent)
    }

    // Every page and the sign-in window.
    function viewList() {
        var views = []
        for (var index = 0; index < pages.count; index++) {
            if (pages.itemAt(index))
                views.push(pages.itemAt(index))
        }
        if (chatWeb.overlayView)
            views.push(chatWeb.overlayView)
        return views
    }

    // Addresses of the pages (and sign-in window) of siteId, which share
    // its profile; view's own address is replaced by pendingUrl (the one it
    // is about to load).
    function viewUrls(siteId, view, pendingUrl) {
        var views = chatWeb.viewList()
        var urls = []
        for (var index = 0; index < views.length; index++) {
            if (views[index] !== view && views[index].site === siteId)
                urls.push(views[index].url.toString())
        }
        if (view)
            urls.push(pendingUrl)
        return urls
    }

    function wantedUserAgent(siteId, view, pendingUrl) {
        return ChatSites.userAgentFor(chatWeb.viewUrls(siteId, view, pendingUrl), chatWeb.baseUserAgent)
    }

    // The user agent is profile-wide and only a plain property, but it must
    // never be set from inside a navigation request (that aborts Qt
    // WebEngine); callers defer this. On Google sign-in, client hints are
    // emptied too so they don't name Chromium behind the Firefox agent.
    function applyUserAgent(profile, userAgent) {
        if (!profile || chatWeb.baseUserAgent === "" || profile.httpUserAgent === userAgent)
            return
        var firefox = userAgent === ChatSites.GOOGLE_SIGNIN_UA
        profile.clientHints.isAllClientHintsEnabled = firefox ? false : chatWeb.baseClientHintsEnabled
        profile.clientHints.fullVersionList = firefox ? ({}) : chatWeb.baseBrands
        profile.httpUserAgent = userAgent
    }

    // Settles each profile's user agent from its own pages' addresses, but
    // only while none of them is loading: a load in flight is handled by
    // its own request and ends with another sync.
    function syncUserAgent() {
        var views = chatWeb.viewList()
        for (var siteId in chatWeb.profiles) {
            var loading = false
            for (var index = 0; index < views.length; index++) {
                if (views[index].site === siteId && views[index].loading)
                    loading = true
            }
            if (!loading)
                chatWeb.applyUserAgent(chatWeb.profiles[siteId], chatWeb.wantedUserAgent(siteId, null, ""))
        }
    }

    // What a new profile for siteId is made with, or null when it may not
    // have one now: not a web site id, its old profile is still being
    // destroyed, or (saved sign-ins) its folder isn't prepared or the name
    // and path can't be built. Name and path come only from ChatStorage,
    // with this same id.
    function siteProfileSpec(siteId) {
        if (!ChatStorage.isSiteId(siteId) || chatWeb.retiring[siteId] === true)
            return null
        if (!chatWeb.staySignedIn)
            return { saved: false, sitePath: "", siteName: "" }
        if (!ChatStorage.listHas(chatWeb.preparedSites, siteId))
            return null
        var name = ChatStorage.siteProfileName(chatWeb.storageApplet, chatWeb.storageGeneration, siteId)
        var path = ChatStorage.siteProfilePath(chatWeb.runtimeDir, chatWeb.storageApplet,
            chatWeb.storageGeneration, siteId)
        if (name === "" || path === "")
            return null
        return { saved: true, sitePath: path, siteName: name }
    }

    // A cleared site's old profile is still being destroyed.
    function siteRetiring(siteId) {
        return chatWeb.retiring[siteId] === true
    }

    // siteId's profile, made now if it has none; called only right before a
    // view of that site is created. null: no view may be created.
    function ensureProfile(siteId) {
        var existing = chatWeb.profileFor(siteId)
        if (existing)
            return existing
        var spec = chatWeb.siteProfileSpec(siteId)
        if (!spec)
            return null
        var profile = siteProfileComponent.createObject(chatWeb, spec)
        if (!profile)
            return null
        if (chatWeb.baseUserAgent === "") {
            chatWeb.baseUserAgent = ChatSites.userAgent(profile.httpUserAgent)
            chatWeb.baseClientHintsEnabled = profile.clientHints.isAllClientHintsEnabled
            chatWeb.baseBrands = profile.clientHints.fullVersionList
        }
        profile.httpUserAgent = chatWeb.baseUserAgent
        chatWeb.profiles[siteId] = profile
        chatWeb.profilesRevision++
        return profile
    }

    // Only a lookup: null for a site without a profile.
    function profileFor(siteId) {
        return typeof siteId === "string" && Object.prototype.hasOwnProperty.call(chatWeb.profiles, siteId)
            ? chatWeb.profiles[siteId] : null
    }

    // Clear <site> data: every page and the sign-in window of siteId go,
    // then its profile (with an off-the-record profile, all its data). The
    // profile is destroyed only once its views are gone; a shown site gets
    // a new profile after that (with saved sign-ins only once main.qml has
    // prepared its folder again).
    function clearSite(siteId) {
        if (!ChatStorage.isSiteId(siteId))
            return
        if (chatWeb.overlayView && chatWeb.overlayView.site === siteId)
            chatWeb.closeOverlay()
        if (chatWeb.pendingDownload && chatWeb.pendingDownloadSiteId === siteId)
            chatWeb.cancelDownload()
        if (uploadDialog.request && chatWeb.uploadView && chatWeb.uploadView.site === siteId) {
            uploadDialog.close()
            chatWeb.finishUpload(false)
        }
        if (chatWeb.ownerPending && chatWeb.ownerPending.site === siteId) {
            localOwner.cancel()
            chatWeb.ownerPending = null
        }
        for (var index = visitedSites.count - 1; index >= 0; index--) {
            if (visitedSites.get(index).site === siteId)
                visitedSites.remove(index)
        }
        chatWeb.syncCurrentViews()
        var profile = chatWeb.profileFor(siteId)
        if (!profile) {
            Qt.callLater(function () { chatWeb.siteReleased(siteId) })
            return
        }
        delete chatWeb.profiles[siteId]
        chatWeb.retiring[siteId] = true
        chatWeb.profilesRevision++
        // The views' own deletion was posted first; the profile's follows.
        Qt.callLater(function () { chatWeb.releaseProfile(siteId, profile) })
    }

    function releaseProfile(siteId, profile) {
        var views = chatWeb.viewList()
        for (var index = 0; index < views.length; index++) {
            if (views[index].profile === profile) {
                Qt.callLater(function () { chatWeb.releaseProfile(siteId, profile) })
                return
            }
        }
        profile.destroy()
        Qt.callLater(function () {
            delete chatWeb.retiring[siteId]
            chatWeb.profilesRevision++
            chatWeb.siteReleased(siteId)
            chatWeb.syncViews()
        })
    }

    // Every profile's downloads: only one waits at a time.
    function handleDownload(download) {
        if (download.isSavePageDownload || chatWeb.pendingDownload !== null) {
            download.cancel()
            return
        }
        // Deferred: the request stays pending until Save, Cancel or timeout.
        chatWeb.pendingDownload = download
        chatWeb.pendingDownloadName = download.downloadFileName
        var siteId = download.view && typeof download.view.site === "string" ? download.view.site : ""
        var source = siteId !== "" ? ChatSites.byId(siteId, chatWeb.userSites) : null
        chatWeb.pendingDownloadSite = source ? source.name : ""
        chatWeb.pendingDownloadSiteId = source ? siteId : ""
        downloadTimeout.restart()
    }

    // openerUrl: the address of the page that asked for the window; its host
    // names a window that is still blank.
    // overlayPane (set by the opener's page) says which pane it covers.
    // The window gets its opener's profile (request.openIn needs it); a
    // site without one opens nothing.
    function openOverlay(request, siteId, openerUrl) {
        chatWeb.closeOverlay()
        if (!chatWeb.profileFor(siteId))
            return
        var view = pageComponent.createObject(overlayContent, {
            site: siteId,
            pane: chatWeb.overlayPane,
            isOverlay: true,
            openerUrl: String(openerUrl || "")
        })
        if (!view)
            return
        chatWeb.overlayView = view
        request.openIn(view)
        Qt.callLater(chatWeb.focusView)
    }

    function saveDownload() {
        var download = chatWeb.pendingDownload
        chatWeb.clearPendingDownload()
        if (download)
            download.accept()
    }

    function cancelDownload() {
        var download = chatWeb.pendingDownload
        chatWeb.clearPendingDownload()
        try {
            if (download)
                download.cancel()
        } catch (error) {
            // Already gone together with the profile.
        }
    }

    function clearPendingDownload() {
        downloadTimeout.stop()
        chatWeb.pendingDownload = null
        chatWeb.pendingDownloadName = ""
        chatWeb.pendingDownloadSite = ""
        chatWeb.pendingDownloadSiteId = ""
    }

    function openUploadDialog(request, view) {
        if (chatWeb.dialogOpen
                || (request.mode !== FileDialogRequest.FileModeOpen
                    && request.mode !== FileDialogRequest.FileModeOpenMultiple)) {
            // Folder uploads and save pickers are refused; reading is file-by-file.
            request.accepted = true
            request.dialogReject()
            return
        }
        request.accepted = true
        uploadDialog.request = request
        chatWeb.uploadView = view || null
        uploadDialog.fileMode = request.mode === FileDialogRequest.FileModeOpenMultiple
            ? FileDialog.OpenFiles : FileDialog.OpenFile
        chatWeb.dialogOpen = true
        uploadDialog.open()
    }

    function finishUpload(accepted) {
        var request = uploadDialog.request
        uploadDialog.request = null
        chatWeb.uploadView = null
        chatWeb.dialogOpen = false
        if (!request)
            return
        var paths = []
        if (accepted) {
            var files = uploadDialog.selectedFiles
            for (var index = 0; index < files.length; index++) {
                var text = String(files[index])
                if (text.indexOf("file:///") !== 0)
                    continue
                try {
                    paths.push(decodeURIComponent(text.slice(7)))
                } catch (error) {
                    // Undecodable name: skip it rather than log the path.
                }
            }
        }
        if (paths.length > 0)
            request.dialogAccept(paths)
        else
            request.dialogReject()
    }

    // pane: "a" (the default) or "b".
    function viewFor(siteId, pane) {
        var wanted = pane === "b" ? "b" : "a"
        for (var index = 0; index < pages.count; index++) {
            var view = pages.itemAt(index)
            if (view && view.site === siteId && view.pane === wanted)
                return view
        }
        return null
    }

    function syncCurrentViews() {
        chatWeb.currentView = chatWeb.viewFor(chatWeb.siteId, "a")
        chatWeb.currentViewB = chatWeb.splitActive ? chatWeb.viewFor(chatWeb.siteIdB, "b") : null
    }

    function syncViews() {
        // Destroy views of sites that were disabled in the settings, and
        // every pane b view once split is off.
        for (var index = visitedSites.count - 1; index >= 0; index--) {
            var entry = visitedSites.get(index)
            if (chatWeb.siteIds.indexOf(entry.site) < 0 || (entry.pane === "b" && !chatWeb.splitActive)) {
                // An upload dialog of that page is answered first.
                if (uploadDialog.request && chatWeb.uploadView
                        && chatWeb.uploadView === chatWeb.viewFor(entry.site, entry.pane)) {
                    uploadDialog.close()
                    chatWeb.finishUpload(false)
                }
                visitedSites.remove(index)
            }
        }
        if (chatWeb.overlayView && (chatWeb.siteIds.indexOf(chatWeb.overlayView.site) < 0
                || (chatWeb.overlayPane === "b" && !chatWeb.splitActive)))
            chatWeb.closeOverlay()
        if (chatWeb.ownerPending && chatWeb.ownerPending.create
                && (chatWeb.siteIds.indexOf(chatWeb.ownerPending.site) < 0
                    || (chatWeb.ownerPending.pane === "b" && !chatWeb.splitActive))) {
            localOwner.cancel()
            chatWeb.ownerPending = null
        }
        if (!chatWeb.splitActive)
            chatWeb.focusedPane = "a"
        // Append only: existing views keep their page and are never reloaded.
        // An owner-checked view on this computer (Local, an added loopback
        // site) is created only after the owner check.
        // A site that may not have a profile yet (with saved sign-ins: no
        // prepare of its folder since the last status check) waits and asks
        // main.qml for one; this runs again when the prepared sites change.
        var panes = chatWeb.splitActive ? ["a", "b"] : ["a"]
        for (var at = 0; at < panes.length; at++) {
            var pane = panes[at]
            var wanted = pane === "b" ? chatWeb.siteIdB : chatWeb.siteId
            if (chatWeb.siteIds.indexOf(wanted) < 0 || chatWeb.viewFor(wanted, pane) !== null)
                continue
            // An added id without its entry is no site: no view, no profile.
            var home = ChatSites.homeUrl(wanted, chatWeb.customUrls, chatWeb.userSites)
            if (home === "")
                continue
            if (!chatWeb.profileFor(wanted) && !chatWeb.siteProfileSpec(wanted)) {
                if (chatWeb.staySignedIn && ChatStorage.isSiteId(wanted) && !chatWeb.siteRetiring(wanted))
                    chatWeb.siteWanted(wanted)
                continue
            }
            if (ChatSites.localOwnerPort({ siteId: wanted, customUrls: chatWeb.customUrls,
                                           userSites: chatWeb.userSites,
                                           url: home }) === 0) {
                if (chatWeb.ensureProfile(wanted))
                    visitedSites.append({ site: wanted, pane: pane })
            }
            // One check at a time: a check running for the other pane (a
            // navigation or a create) re-runs this when it ends.
            else if (!chatWeb.ownerPending)
                chatWeb.checkLocalOwner(null, home, false, true, pane, wanted)
        }
        chatWeb.syncCurrentViews()
    }

    // A changed address moves only the views whose home actually changed.
    // An added site on another host is another site (M1): its view never
    // goes there with the old profile; it is blanked, and main.qml drops
    // the site (dropSites), which comes back with a new profile.
    function applyCustomUrls() {
        for (var index = 0; index < pages.count; index++) {
            var view = pages.itemAt(index)
            if (!view || view.isOverlay)
                continue
            var url = ChatSites.homeUrl(view.site, chatWeb.customUrls, chatWeb.userSites)
            if (url === "" || url === view.homeUrl)
                continue
            if (chatWeb.overlayView && chatWeb.overlayView.site === view.site)
                chatWeb.closeOverlay()
            if (ChatSites.isUserSiteId(view.site) && chatWeb.hostOf(url) !== chatWeb.hostOf(view.homeUrl)) {
                view.url = "about:blank"
                continue
            }
            view.homeUrl = url
            view.failed = false
            view.crashed = false
            view.url = url
        }
    }

    // The exact host of an added site's http(s) address (IPv6 literals
    // too), "" when it has none.
    function hostOf(url) {
        var parsed = ChatSites.parseUserUrl(url)
        return parsed && parsed.host !== "" ? ChatSites.normalizeHost(parsed.host) : ""
    }

    onSiteIdsChanged: chatWeb.syncViews()
    onPreparedSitesChanged: chatWeb.syncViews()
    onCustomUrlsChanged: chatWeb.applyCustomUrls()
    // An added site's address may have changed (same host: same profile).
    onUserSitesChanged: chatWeb.applyCustomUrls()
    onSiteIdChanged: {
        if (chatWeb.overlayPane === "a")
            chatWeb.closeOverlay()
        chatWeb.clearExternal()
        chatWeb.passkeyNotice = false
        chatWeb.syncViews()
    }
    onSiteIdBChanged: {
        if (chatWeb.overlayPane === "b")
            chatWeb.closeOverlay()
        chatWeb.clearExternal()
        chatWeb.passkeyNotice = false
        chatWeb.syncViews()
    }
    onSplitActiveChanged: {
        chatWeb.syncViews()
        Qt.callLater(chatWeb.syncUserAgent)
    }

    // The pane of the item that has the keyboard focus (a page or its
    // inner items), if it is one of ours.
    function paneOf(item) {
        for (var at = item; at; at = at.parent) {
            if ((at.pane === "a" || at.pane === "b") && typeof at.site === "string" && at.isOverlay !== undefined)
                return at.pane
            if (at === chatWeb)
                return ""
        }
        return ""
    }

    Connections {
        target: chatWeb.Window.window
        ignoreUnknownSignals: true
        function onActiveFocusItemChanged() {
            var pane = chatWeb.paneOf(chatWeb.Window.activeFocusItem)
            if (pane !== "")
                chatWeb.focusedPane = pane
        }
    }

    Component.onCompleted: chatWeb.syncViews()

    Component.onDestruction: {
        localOwner.cancel()
        chatWeb.cancelDownload()
        if (uploadDialog.request)
            chatWeb.finishUpload(false)
    }

    // The only profile there is: one instance per site, made by
    // ensureProfile alone, which sets saved, sitePath and siteName once at
    // creation. Order matters: the paths come before storageName and
    // offTheRecord is last, or Qt creates a stray profile folder under
    // Plasma's own data directory before it sees the paths.
    // Qt 6.9+ logs that WebEngineProfilePrototype should be used instead. It
    // is not: QML can't pick a type by Qt version, so 6.8 (still the
    // minimum, e.g. Debian stable) would need a second, untested profile
    // path. tests/test_main_qml_wiring.py checks with real saved profiles
    // that nothing is written outside the site folders.
    Component {
        id: siteProfileComponent

        WebEngineProfile {
            id: siteProfile
            property bool saved: false
            property string sitePath: ""
            property string siteName: ""

            persistentStoragePath: siteProfile.saved ? siteProfile.sitePath : ""
            cachePath: siteProfile.saved ? siteProfile.sitePath : ""
            storageName: siteProfile.saved ? siteProfile.siteName : ""
            httpCacheType: WebEngineProfile.MemoryHttpCache
            persistentCookiesPolicy: siteProfile.saved
                ? WebEngineProfile.AllowPersistentCookies : WebEngineProfile.NoPersistentCookies
            persistentPermissionsPolicy: WebEngineProfile.PersistentPermissionsPolicy.AskEveryTime
            spellCheckEnabled: false
            offTheRecord: !siteProfile.saved

            onDownloadRequested: (download) => chatWeb.handleDownload(download)
        }
    }

    LocalOwnerCheck {
        id: localOwner
        objectName: "localOwnerCheck"
        appletId: chatWeb.appletId
        onFinished: (port, problem) => chatWeb.localOwnerFinished(port, problem)
    }

    // A "Send the form again" pass is good for ownerPassLifetime only.
    Timer {
        id: ownerPassTimer
        interval: chatWeb.ownerPassLifetime
        onTriggered: {
            if (chatWeb.localOwnerProblem === "resend")
                chatWeb.dismissLocalOwner()
            else
                chatWeb.clearOwnerPasses()
        }
    }

    Timer {
        id: downloadTimeout
        interval: 60000
        onTriggered: chatWeb.cancelDownload()
    }

    ListModel {
        id: visitedSites
    }

    Component {
        id: pageComponent

        WebEngineView {
            id: page

            required property string site
            // "a" or "b": the split pane it belongs to (a sign-in window: its opener's).
            required property string pane
            property bool isOverlay: false
            // The address this view was opened with (custom or built-in).
            property string homeUrl: ""
            property bool failed: false
            property bool crashed: false
            // Address re-requested once after a user agent switch.
            property string userAgentRetry: ""
            // Address a good owner check was just made for (owner-checked
            // sites only); used up by the next main-frame navigation.
            property string ownerPass: ""
            // Date.now() after which ownerPass no longer counts.
            property double ownerPassExpires: 0
            // Sign-in window only: the address of the page that opened it.
            property string openerUrl: ""
            readonly property real wantedZoom: SettingsLogic.zoomFor(chatWeb.zoomMap, page.site)
            // The last zoom change came while a page was loading.
            property bool zoomedWhileLoading: false

            // Chromium keeps it across navigations (spike Z1), so it is
            // bound once.
            zoomFactor: page.wantedZoom

            anchors.fill: page.isOverlay ? parent : page.pane === "b" ? paneAreaB : paneAreaA
            visible: page.isOverlay || (page.pane === "b"
                ? chatWeb.splitShown && page.site === chatWeb.siteIdB
                : page.site === chatWeb.siteId)
            // Its site's own profile, made right before this view; fixed
            // for the view's lifetime (profiles is never reassigned).
            profile: chatWeb.profileFor(page.site)
            backgroundColor: Kirigami.Theme.backgroundColor

            settings.screenCaptureEnabled: false
            settings.pluginsEnabled: false
            settings.dnsPrefetchEnabled: false
            settings.navigateOnDropEnabled: false
            settings.localContentCanAccessFileUrls: false
            settings.allowRunningInsecureContent: false
            settings.javascriptCanAccessClipboard: false
            settings.javascriptCanPaste: false
            settings.focusOnNavigationEnabled: false
            settings.unknownUrlSchemePolicy: WebEngineSettings.DisallowUnknownUrlSchemes

            // Page console output must never reach the journal.
            onJavaScriptConsoleMessage: (level, message, lineNumber, sourceID) => {}

            onPermissionRequested: (permission) => {
                permission.deny()
            }
            onFullScreenRequested: (request) => {
                request.reject()
            }
            onCertificateError: (error) => {
                error.rejectCertificate()
            }
            onAuthenticationDialogRequested: (request) => {
                request.accepted = true
                request.dialogReject()
            }
            onSelectClientCertificate: (selection) => {
                selection.selectNone()
            }
            onFileSystemAccessRequested: (request) => {
                request.reject()
            }
            onDesktopMediaRequested: (request) => {
                request.cancel()
            }
            onRegisterProtocolHandlerRequested: (request) => {
                request.reject()
            }
            onWebAuthUxRequested: (request) => {
                request.cancel()
                chatWeb.passkeyNotice = true
            }
            onFileDialogRequested: (request) => {
                chatWeb.openUploadDialog(request, page)
            }

            onNavigationRequested: (request) => {
                var verdict = ChatSites.classifyNavigation({
                    url: request.url.toString(),
                    isMainFrame: request.isMainFrame,
                    linkClicked: request.navigationType
                        === WebEngineNavigationRequest.LinkClickedNavigation,
                    siteId: page.site,
                    customUrls: chatWeb.customUrls,
                    userSites: chatWeb.userSites
                })
                if (verdict === "allow") {
                    if (!request.isMainFrame)
                        return
                    var url = request.url.toString()
                    if (Date.now() >= page.ownerPassExpires)
                        page.ownerPass = ""
                    var gate = ChatSites.localOwnerGate({
                        url: url,
                        isMainFrame: request.isMainFrame,
                        siteId: page.site,
                        customUrls: chatWeb.customUrls,
                        userSites: chatWeb.userSites,
                        pass: page.ownerPass
                    })
                    if (gate !== "skip")
                        page.ownerPass = ""
                    if (gate === "check") {
                        request.reject()
                        chatWeb.checkLocalOwner(page, url, request.navigationType
                            === WebEngineNavigationRequest.FormSubmittedNavigation, false, page.pane, page.site)
                        return
                    }
                    page.checkUserAgent(request)
                    return
                }
                request.reject()
                if (verdict === "external")
                    chatWeb.askExternal(request.url.toString())
            }

            onNewWindowRequested: (request) => {
                var url = request.requestedUrl.toString()
                var verdict = ChatSites.classifyNewWindow({
                    url: url,
                    isDialog: request.destination === WebEngineNewWindowRequest.InNewDialog,
                    // A sign-in window opens only for a click.
                    userInitiated: request.userInitiated === true,
                    siteId: page.site,
                    customUrls: chatWeb.customUrls,
                    userSites: chatWeb.userSites
                })
                // A window of an owner-checked site starting on this
                // computer would skip the owner check: dropped.
                if (verdict === "overlay" && ChatSites.localOwnerPort({
                        siteId: page.site, customUrls: chatWeb.customUrls,
                        userSites: chatWeb.userSites, url: url }) > 0)
                    return
                // A sign-in window cannot open another overlay on top of itself.
                if (verdict === "overlay" && !page.isOverlay) {
                    chatWeb.overlayPane = page.pane
                    chatWeb.openOverlay(request, page.site, page.url.toString())
                }
                // Only a click may ask to hand an address to the system
                // browser (external or nested sign-in); script-opened ones
                // are dropped.
                else if (verdict !== "block" && request.userInitiated
                         && ChatSites.isHttpsUrl(url))
                    chatWeb.askExternal(url)
            }

            // A main-frame load that needs the other user agent is stopped
            // and asked again once the switch is done, so its very first
            // request already carries the right one. A form post can't be
            // replayed: it goes out as is and the switch follows at the end
            // of the load.
            function checkUserAgent(request) {
                var url = request.url.toString()
                var retried = page.userAgentRetry === url
                page.userAgentRetry = ""
                if (retried || chatWeb.wantedUserAgent(page.site, page, url) === page.profile.httpUserAgent)
                    return
                if (request.navigationType === WebEngineNavigationRequest.FormSubmittedNavigation)
                    return
                request.reject()
                page.userAgentRetry = url
                Qt.callLater(function () {
                    // Closed meanwhile (sign-in window, disabled site).
                    if (chatWeb.viewList().indexOf(page) < 0)
                        return
                    chatWeb.applyUserAgent(page.profile, chatWeb.wantedUserAgent(page.site, page, url))
                    page.url = url
                })
            }

            onWindowCloseRequested: {
                if (page.isOverlay)
                    chatWeb.closeOverlay()
            }

            onLoadingChanged: (loadingInfo) => {
                if (loadingInfo.status === WebEngineLoadingInfo.LoadStartedStatus)
                    page.failed = false
                // Aborted loads (-3) come from our own rejections; not a failure.
                else if (loadingInfo.status === WebEngineLoadingInfo.LoadFailedStatus
                        && loadingInfo.errorCode !== -3)
                    page.failed = true
                if (loadingInfo.status !== WebEngineLoadingInfo.LoadStartedStatus)
                    Qt.callLater(chatWeb.syncUserAgent)
            }

            // Ctrl+wheel zooms inside Chromium itself: the zoom moves one
            // step that way and is stored for the page's site (a sign-in
            // window's too), then the binding is back. While a page loads
            // a change is never stored, only undone.
            onZoomFactorChanged: {
                if (Math.abs(page.zoomFactor - page.wantedZoom) > 0.001) {
                    page.zoomedWhileLoading = page.loading
                    Qt.callLater(page.adoptZoom)
                }
            }

            function adoptZoom() {
                // Qt WebEngine's wheel zoom moves by 0.1 a notch: one step
                // that way, so 1.25 → 1.35 means 1.5, never back to 1.25.
                var factor = SettingsLogic.zoomStep(page.wantedZoom,
                    page.zoomFactor > page.wantedZoom ? 1 : -1)
                if (!page.zoomedWhileLoading && Math.abs(factor - page.wantedZoom) > 0.001)
                    chatWeb.siteZoomRequested(page.site, factor)
                // The stored zoom (new or old); equal values change nothing,
                // so this can't loop.
                page.zoomFactor = Qt.binding(function () { return page.wantedZoom })
            }

            onRenderProcessTerminated: (terminationStatus, exitCode) => {
                if (terminationStatus !== WebEngineView.NormalTerminationStatus)
                    page.crashed = true
            }

            Component.onCompleted: {
                // Never without its site's profile (the default one is not ours).
                if (page.isOverlay || !page.profile || page.profile !== chatWeb.profileFor(page.site))
                    return
                if (chatWeb.ownerChecked(page.site)) {
                    // Only the view the good check was made for gets its pass.
                    if (page.site === chatWeb.localCreateSite)
                        page.ownerPass = chatWeb.localCreatePass
                    page.ownerPassExpires = Date.now() + chatWeb.ownerPassLifetime
                    chatWeb.localCreatePass = ""
                    chatWeb.localCreateSite = ""
                }
                page.homeUrl = ChatSites.homeUrl(page.site, chatWeb.customUrls, chatWeb.userSites)
                if (page.homeUrl !== "")
                    page.url = page.homeUrl
            }
        }
    }

    // Where each pane's pages are: side by side while split is shown, else
    // pane a takes everything.
    Item {
        id: paneAreaA
        objectName: "paneAreaA"
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: chatWeb.splitShown ? Math.floor((parent.width - paneSeparator.width) / 2) : parent.width

        PlasmaComponents.BusyIndicator {
            objectName: "siteWaitA"
            anchors.centerIn: parent
            visible: chatWeb.siteWaits(chatWeb.siteId, "a")
            running: visible
        }
    }
    Kirigami.Separator {
        id: paneSeparator
        anchors.left: paneAreaA.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        visible: chatWeb.splitShown
    }
    Item {
        id: paneAreaB
        objectName: "paneAreaB"
        anchors.left: paneSeparator.right
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        visible: chatWeb.splitShown

        PlasmaComponents.BusyIndicator {
            objectName: "siteWaitB"
            anchors.centerIn: parent
            visible: chatWeb.splitActive && chatWeb.siteWaits(chatWeb.siteIdB, "b")
            running: visible
        }
    }

    Repeater {
        id: pages
        model: visitedSites
        delegate: pageComponent
        onItemAdded: chatWeb.syncCurrentViews()
        onItemRemoved: chatWeb.syncCurrentViews()
    }

    Rectangle {
        id: overlay
        objectName: "signInOverlay"
        anchors.fill: chatWeb.overlayPane === "b" ? paneAreaB : paneAreaA
        // Pane b's window hides with pane b (too narrow); it stays open.
        visible: chatWeb.overlayOpen && (chatWeb.overlayPane === "a" || chatWeb.splitShown)
        color: Kirigami.Theme.backgroundColor

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            RowLayout {
                Layout.fillWidth: true
                Layout.margins: Kirigami.Units.smallSpacing
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Icon {
                    source: "dialog-password"
                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                    Layout.preferredHeight: Kirigami.Units.iconSizes.small
                }
                // Always names a host: the window's own, or while it is
                // still blank the host of the page that opened it.
                PlasmaComponents.Label {
                    objectName: "overlayTitle"
                    Layout.fillWidth: true
                    textFormat: Text.PlainText
                    elide: Text.ElideLeft
                    text: chatWeb.overlayTitle.kind === "page"
                        ? i18n("Sign-in window: %1", chatWeb.overlayTitle.host)
                        : chatWeb.overlayTitle.kind === "opener"
                            ? i18n("Window opened by %1", chatWeb.overlayTitle.host)
                            : i18n("Window opened by an unknown page")
                }
                PlasmaComponents.ToolButton {
                    text: i18n("Close")
                    icon.name: "window-close"
                    onClicked: chatWeb.closeOverlay()
                }
            }
            Kirigami.Separator {
                Layout.fillWidth: true
            }
            Item {
                id: overlayContent
                Layout.fillWidth: true
                Layout.fillHeight: true
            }
        }
    }

    FileDialog {
        id: uploadDialog
        property var request: null
        title: i18n("Choose files to upload")
        onAccepted: chatWeb.finishUpload(true)
        onRejected: chatWeb.finishUpload(false)
    }
}
