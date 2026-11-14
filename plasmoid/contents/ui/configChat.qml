import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasmoid
import "ChatSites.js" as ChatSites
import "ChatStorage.js" as ChatStorage
import "OllamaChat.js" as OllamaChat

KCM.SimpleKCM {
    id: page

    // Every key is declared so the config dialog can map all of them.
    property string cfg_trackedProviders:
        "[\"claude\",\"codex\",\"cursor\",\"antigravity\",\"copilot\",\"devin\",\"grok\"]"
    property string cfg_trackedProvidersDefault:
        "[\"claude\",\"codex\",\"cursor\",\"antigravity\",\"copilot\",\"devin\",\"grok\"]"
    property string cfg_providerMetrics: "{}"
    property string cfg_providerMetricsDefault: "{}"
    property string cfg_usageMode: "remaining"
    property string cfg_usageModeDefault: "remaining"
    property int cfg_refreshInterval: 300
    property int cfg_refreshIntervalDefault: 300
    property int cfg_configSchemaVersion: 2
    property int cfg_configSchemaVersionDefault: 2
    property bool cfg_initialSetupComplete: false
    property bool cfg_initialSetupCompleteDefault: false
    property string cfg_chatSites:
        "[\"claude\",\"chatgpt\",\"grok\",\"gemini\",\"copilot\",\"mscopilot\"]"
    property string cfg_chatSitesDefault:
        "[\"claude\",\"chatgpt\",\"grok\",\"gemini\",\"copilot\",\"mscopilot\"]"
    property string cfg_chatDefaultSite: "claude"
    property string cfg_chatDefaultSiteDefault: "claude"
    property string cfg_chatCustomUrls: "{}"
    property string cfg_chatCustomUrlsDefault: "{}"
    property string cfg_chatSignInStorage: "memory"
    property string cfg_chatSignInStorageDefault: "memory"
    // Written only by main.qml; kept in step so Apply never writes back an
    // old value.
    property int cfg_chatProfileGeneration: 0
    property int cfg_chatProfileGenerationDefault: 0
    property int cfg_chatProfileLayout: 0
    property int cfg_chatProfileLayoutDefault: 0
    property string cfg_chatPendingSiteClears: ""
    property string cfg_chatPendingSiteClearsDefault: ""
    // Written only here (the site table) and by a backup Replace (General).
    property string cfg_chatUserSites: "[]"
    property string cfg_chatUserSitesDefault: "[]"
    property string cfg_chatSiteOrder: ""
    property string cfg_chatSiteOrderDefault: ""
    property int cfg_chatAutoLockMinutes: 0
    property int cfg_chatAutoLockMinutesDefault: 0
    property string cfg_chatVaultUnlock: "passphrase"
    property string cfg_chatVaultUnlockDefault: "passphrase"
    property bool cfg_chatKeepOpen: false
    property bool cfg_chatKeepOpenDefault: false
    property string cfg_chatOllamaUrl: "http://127.0.0.1:11434"
    property string cfg_chatOllamaUrlDefault: "http://127.0.0.1:11434"
    property string cfg_popupDefaultTab: "chat"
    property string cfg_popupDefaultTabDefault: "chat"
    property bool cfg_showUsageTab: true
    property bool cfg_showUsageTabDefault: true
    property bool cfg_showChatTab: true
    property bool cfg_showChatTabDefault: true
    property string cfg_popupSize: "normal"
    property string cfg_popupSizeDefault: "normal"
    property bool cfg_tooltipShowsUsage: true
    property bool cfg_tooltipShowsUsageDefault: true
    property string cfg_tooltipMetrics: ""
    property string cfg_tooltipMetricsDefault: ""
    property string cfg_shortcutOpens: "popup"
    property string cfg_shortcutOpensDefault: "popup"
    // Written only by main.qml (zoom keys, Ctrl+wheel); kept in step so
    // Apply never writes back an old value.
    property string cfg_chatSiteZoom: "{}"
    property string cfg_chatSiteZoomDefault: "{}"
    property bool cfg_alertLowEnabled: false
    property bool cfg_alertLowEnabledDefault: false
    property int cfg_alertLowPercent: 20
    property int cfg_alertLowPercentDefault: 20
    property bool cfg_alertResetEnabled: false
    property bool cfg_alertResetEnabledDefault: false
    property string cfg_providerOrder: ""
    property string cfg_providerOrderDefault: ""
    property bool cfg_usageCompact: false
    property bool cfg_usageCompactDefault: false
    property int cfg_usageWarnPercent: 60
    property int cfg_usageWarnPercentDefault: 60
    property int cfg_usageCriticalPercent: 85
    property int cfg_usageCriticalPercentDefault: 85
    property string cfg_usageNormalColor: ""
    property string cfg_usageNormalColorDefault: ""
    property string cfg_usageWarnColor: ""
    property string cfg_usageWarnColorDefault: ""
    property string cfg_usageCriticalColor: ""
    property string cfg_usageCriticalColorDefault: ""
    property string cfg_panelRing: "auto"
    property string cfg_panelRingDefault: "auto"
    property string cfg_middleClickOpens: "refresh"
    property string cfg_middleClickOpensDefault: "refresh"
    property bool cfg_usageHistoryEnabled: false
    property bool cfg_usageHistoryEnabledDefault: false
    // Written only by main.qml; kept in step so Apply never writes back an
    // old value.
    property bool cfg_usageHistoryClearOwed: false
    property bool cfg_usageHistoryClearOwedDefault: false
    property bool cfg_backupAutoExport: false
    property bool cfg_backupAutoExportDefault: false
    // Written only by main.qml (panel menu → Restore settings…).
    property string cfg_backupRestoreAt: ""
    property string cfg_backupRestoreAtDefault: ""


    // main.qml may move to a new generation or layout, or store a zoom,
    // while this page is open.
    Connections {
        target: Plasmoid.configuration
        function onValueChanged(key, value) {
            if (key === "chatProfileGeneration")
                page.cfg_chatProfileGeneration = value
            else if (key === "chatProfileLayout")
                page.cfg_chatProfileLayout = value
            else if (key === "chatPendingSiteClears")
                page.cfg_chatPendingSiteClears = value
            else if (key === "chatSiteZoom")
                page.cfg_chatSiteZoom = value
            else if (key === "usageHistoryClearOwed")
                page.cfg_usageHistoryClearOwed = value
            else if (key === "backupRestoreAt")
                page.cfg_backupRestoreAt = value
        }
    }

    // The added sites this page holds now; only valid entries are shown.
    readonly property var userSites: ChatSites.parseUserSites(page.cfg_chatUserSites).sites
    readonly property var userSiteIds: page.userSites.map(function (site) { return site.id })
    // Every row of the table, in order: built-in and added web sites and
    // Ollama.
    readonly property var tableSites: ChatSites.orderedSites(page.userSites, page.cfg_chatSiteOrder)
    readonly property var tableIds: page.tableSites.map(function (site) { return site.id })
    // The enabled web sites and Ollama when it is on, in table order.
    readonly property var enabledSites: OllamaChat.menuEntries(
        ChatSites.enabledSites(page.cfg_chatSites, page.userSites, page.cfg_chatSiteOrder),
        page.cfg_chatSites, page.tableIds)
    readonly property var enabledIds: page.enabledSites.map(function (site) { return site.id })
    // Added sites the applied settings have and this page no longer does:
    // applying signs them out and deletes their site data. Every id in the
    // applied text counts, also of entries this version can't read.
    readonly property var removedUserSiteIds: ChatSites.removedUserSiteIds(
        Plasmoid.configuration.chatUserSites, page.cfg_chatUserSites)
    // The page's added sites read whole. When they don't (an entry this
    // version can't read, a hand edit), added sites can't be added, edited,
    // removed or moved here: a write would drop the unreadable entries.
    readonly property bool userSitesReadable: ChatSites.parseUserSites(page.cfg_chatUserSites).ok
    readonly property bool canAddSite: page.userSitesReadable && page.userSites.length < ChatSites.MAX_USER_SITES
    // Every added id this page has seen (it opened with them or made them):
    // a new site never takes one, nor one whose delete is still owed.
    property var seenUserSiteIds: []

    // One editor at a time: a row's id, "new" for Add site…, "" for none.
    property string editingId: ""
    // The added site whose Remove asks first; "" when none.
    property string confirmingRemove: ""

    Component.onCompleted: page.noteUserSiteIds()
    onUserSiteIdsChanged: page.noteUserSiteIds()
    // Defaults or a write elsewhere changes what an open editor showed.
    onCfg_chatUserSitesChanged: {
        if (page.editingId !== "new" && page.editingId !== "" && page.tableIds.indexOf(page.editingId) < 0)
            page.closeEditor()
        if (page.userSiteIds.indexOf(page.confirmingRemove) < 0)
            page.confirmingRemove = ""
    }

    function noteUserSiteIds() {
        var seen = page.seenUserSiteIds.slice()
        page.userSiteIds.forEach(function (id) {
            if (seen.indexOf(id) < 0)
                seen.push(id)
        })
        if (seen.length !== page.seenUserSiteIds.length)
            page.seenUserSiteIds = seen
    }

    function openEditor(siteId) {
        page.confirmingRemove = ""
        page.editingId = siteId
    }

    function closeEditor() {
        page.editingId = ""
    }

    function setEnabled(siteId, enabled) {
        var ids = OllamaChat.allSiteIds(ChatSites.siteIds(page.userSites)).filter(function (id) {
            return id === siteId ? enabled : page.enabledIds.indexOf(id) >= 0
        })
        // Added ids this page can't read stay as they were; readable ones
        // follow their checkbox like any other site.
        var stored = []
        try {
            stored = JSON.parse(page.cfg_chatSites)
        } catch (error) {
        }
        if (Array.isArray(stored))
            ids = ids.concat(stored.filter(function (id, index) {
                return ChatSites.isUserSiteId(id) && page.userSiteIds.indexOf(id) < 0
                    && ids.indexOf(id) < 0 && stored.indexOf(id) === index
            }))
        page.cfg_chatSites = JSON.stringify(ids)
        // Open first: the first enabled row, if any (an unreadable id has no row).
        var shown = page.tableIds.filter(function (id) { return ids.indexOf(id) >= 0 })
        if (ids.indexOf(page.cfg_chatDefaultSite) < 0 && shown.length > 0)
            page.cfg_chatDefaultSite = shown[0]
    }

    // Saved custom address of one site, "" when it uses the built-in one.
    function savedCustomUrl(siteId) {
        var map = ChatSites.parseCustomUrls(page.cfg_chatCustomUrls)
        return Object.prototype.hasOwnProperty.call(map, siteId) ? map[siteId] : ""
    }

    // The address a row opens and what the table shows of it.
    function rowAddress(site) {
        if (site.native === true)
            return OllamaChat.effectiveAddress(page.cfg_chatOllamaUrl)
        return ChatSites.homeUrl(site.id, ChatSites.parseCustomUrls(page.cfg_chatCustomUrls), page.userSites)
    }

    // An added http site shows http:// (and a port that isn't 80), so "not
    // encrypted" stays visible with the editor closed; an added https site on
    // this computer or the network shows a port that isn't 443.
    function rowHost(site) {
        var address = page.rowAddress(site)
        if (site.native === true)
            return address
        var shown = ChatSites.shortHost(ChatSites.displayHost(address))
        var parsed = site.user === true ? ChatSites.parseUserUrl(address) : null
        if (!parsed || shown === "")
            return shown
        if (parsed.scheme === "http")
            return "http://" + shown + (parsed.port !== "" && parsed.port !== "80" ? ":" + parsed.port : "")
        if ((site.local_kind === "loopback" || site.local_kind === "private")
                && parsed.port !== "" && parsed.port !== "443")
            return shown + ":" + parsed.port
        return shown
    }

    // --- Save: only valid values are ever written -------------------------

    // A built-in site's address ("" uses the built-in one); the error code,
    // "" when saved.
    function saveCustomUrl(siteId, text) {
        var checked = ChatSites.validateCustomUrl(siteId, String(text || "").trim())
        if (!checked.ok)
            return checked.error
        var map = ChatSites.parseCustomUrls(page.cfg_chatCustomUrls)
        if (checked.url === "")
            delete map[siteId]
        else
            map[siteId] = checked.url
        page.closeEditor()
        page.cfg_chatCustomUrls = ChatSites.serializeCustomUrls(map)
        return ""
    }

    // The Ollama address ("" is the default); the error code, "" when saved.
    function saveOllamaAddress(text) {
        var checked = OllamaChat.validateAddress(String(text || "").trim())
        if (!checked.ok)
            return checked.error
        page.closeEditor()
        page.cfg_chatOllamaUrl = checked.address
        return ""
    }

    // Whether url is on another host than the added site siteId: saving it
    // makes a new site (M1), so no sign-in moves to the other host.
    function hostChanges(siteId, url) {
        var site = ChatSites.byId(siteId, page.userSites)
        var next = ChatSites.parseUserUrl(String(url || "").trim())
        if (!site || site.user !== true || !next || next.host === "")
            return false
        return ChatSites.normalizeHost(next.host) !== site.exact_hosts[0]
    }

    // Adds a site (siteId "new") or saves an added one; the error code
    // (ChatSites.validateUserSite, or "full"), "" when saved. A new site
    // starts on, at the end (above Ollama when Ollama is last). Another
    // host gives the site a new id at the same place; the old one is
    // removed (its data is deleted on Apply).
    function saveUserSite(siteId, name, url) {
        if (!page.userSitesReadable)
            return "damaged"
        var adding = siteId === "new"
        var at = page.userSiteIds.indexOf(siteId)
        if (!adding && at < 0)
            return "entry"
        if (adding && !page.canAddSite)
            return "full"
        var entry = { id: "", name: String(name || "").trim(), url: String(url || "").trim() }
        var renewed = !adding && page.hostChanges(siteId, entry.url)
        entry.id = adding || renewed ? page.newSiteId() : siteId
        if (entry.id === "")
            return "full"
        var others = page.userSites.filter(function (site) { return site.id !== siteId })
        var checked = ChatSites.validateUserSite(entry, others)
        if (!checked.ok)
            return checked.error
        var list = page.userSites.slice()
        if (adding)
            list.push(entry)
        else
            list[at] = entry
        var text = ChatSites.serializeUserSites(list)
        if (text === "")
            return adding ? "full" : "too-long"
        var order = page.tableIds.slice()
        var enabled = page.enabledIds.slice()
        var first = page.cfg_chatDefaultSite
        var ollamaLast = order.length > 0 && order[order.length - 1] === OllamaChat.ENTRY.id
        if (adding) {
            order.splice(ollamaLast ? order.length - 1 : order.length, 0, entry.id)
            enabled.push(entry.id)
        } else if (renewed) {
            order = order.map(function (id) { return id === siteId ? entry.id : id })
            enabled = enabled.map(function (id) { return id === siteId ? entry.id : id })
            if (first === siteId)
                first = entry.id
        }
        page.closeEditor()
        page.cfg_chatUserSites = text
        page.cfg_chatSiteOrder = ChatSites.serializeSiteOrder(order, list)
        page.cfg_chatSites = JSON.stringify(enabled)
        if (page.cfg_chatDefaultSite !== first)
            page.cfg_chatDefaultSite = first
        return ""
    }

    function newSiteId() {
        var excluded = page.seenUserSiteIds.concat(page.userSiteIds,
            ChatStorage.parsePendingClears(page.cfg_chatPendingSiteClears),
            ChatSites.parseUserSites(Plasmoid.configuration.chatUserSites).sites.map(function (site) {
                return site.id
            }))
        var id = ChatSites.newUserSiteId(excluded, Math.random)
        if (id !== "")
            page.seenUserSiteIds = page.seenUserSiteIds.concat([id])
        return id
    }

    // Removes an added site from the page (after its confirmation). Nothing
    // happens until Apply; then main.qml signs it out and deletes its data.
    function removeUserSite(siteId) {
        page.confirmingRemove = ""
        if (!page.userSitesReadable || page.userSiteIds.indexOf(siteId) < 0)
            return
        if (page.editingId === siteId)
            page.closeEditor()
        var list = page.userSites.filter(function (site) { return site.id !== siteId })
        var text = ChatSites.serializeUserSites(list)
        if (text === "")
            return
        var order = page.tableIds.filter(function (id) { return id !== siteId })
        var enabled = page.enabledIds.filter(function (id) { return id !== siteId })
        page.cfg_chatUserSites = text
        page.cfg_chatSiteOrder = ChatSites.serializeSiteOrder(order, list)
        page.cfg_chatSites = JSON.stringify(enabled)
        if (enabled.indexOf(page.cfg_chatDefaultSite) < 0 && enabled.length > 0)
            page.cfg_chatDefaultSite = order.filter(function (id) { return enabled.indexOf(id) >= 0 })[0]
    }

    // ↑ (-1) and ↓ (+1): the order only, no site or data changes.
    function moveSite(siteId, delta) {
        if (!page.userSitesReadable && ChatSites.isUserSiteId(siteId))
            return
        page.cfg_chatSiteOrder = ChatSites.serializeSiteOrder(
            ChatSites.moveInOrder(page.tableIds, siteId, delta), page.userSites)
    }

    function customUrlError(siteId, code) {
        switch (code) {
        case "":
            return ""
        case "too-long":
            return i18n("This address is too long.")
        case "whitespace":
            return i18n("Addresses can't contain spaces or line breaks.")
        case "userinfo":
            return i18n("Addresses with a user name or password aren't allowed.")
        case "scheme":
            return ChatSites.byId(siteId) && ChatSites.byId(siteId).local === true
                ? i18n("Use an address that starts with https:// or http://.")
                : i18n("Use an address that starts with https://.")
        case "http-not-loopback":
            return i18n("http is allowed only for this computer. Use https or an SSH tunnel.")
        case "loopback-not-allowed":
            return i18n("Addresses on this computer are allowed only for Local.")
        default:
            return i18n("This isn't a valid web address.")
        }
    }

    // Whether url's host is a short name (no dot, not a number), like nas:
    // refused as possibly this computer, but most likely a device on the
    // network (REV L-1).
    function isShortName(url) {
        var parsed = ChatSites.parseUserUrl(String(url || "").trim())
        var host = parsed ? parsed.host : ""
        return host !== "" && host.indexOf(".") < 0 && host.charAt(0) !== "["
            && !/^(0x[0-9a-f]*|[0-9]+)$/.test(host) && ChatSites.LOCAL_NAMES.indexOf(host) < 0
    }

    // A fixed text for each code of an added site (ChatSites.validateUserSite);
    // url: the address it was given, for loopback-not-allowed.
    function userSiteError(code, url) {
        switch (code) {
        case "":
            return ""
        case "full":
            return i18n("Can't add more sites.")
        case "damaged":
            return i18n("Some added sites can't be read by this version, so added sites can't be changed here.")
        case "name-empty":
            return i18n("Enter a name.")
        case "name-too-long":
            return i18n("Use a name of at most %1 characters.", ChatSites.MAX_USER_SITE_NAME)
        case "name-chars":
            return i18n("Names can't contain <, >, &, control characters or invisible formatting characters.")
        case "name-taken":
            return i18n("Another site already has this name.")
        case "url-empty":
            return i18n("Enter the site's address.")
        case "too-long":
            return i18n("This address is too long.")
        case "whitespace":
            return i18n("Addresses can't contain spaces or line breaks.")
        case "url-chars":
            return i18n("Use plain letters, digits and URL punctuation only (international names in their xn-- form).")
        case "userinfo":
            return i18n("Addresses with a user name or password aren't allowed.")
        case "malformed":
            return i18n("This isn't a valid web address.")
        case "http-not-allowed":
            return i18n("http is allowed only for this computer (localhost, 127.0.0.1, [::1]) and home-network IP addresses such as 192.168.1.20.")
        case "scheme":
            return i18n("Use an address that starts with https:// or http://.")
        case "loopback-not-allowed":
            return page.isShortName(url)
                ? i18n("http is allowed only for this computer (localhost, 127.0.0.1, [::1]) or a home-network IP address like 192.168.1.20. Other names need https and a full name, like nas.example.org.")
                : i18n("On this computer, use localhost, 127.0.0.1 or [::1].")
        case "ip-literal":
            return i18n("Use the site's name. IP addresses are allowed only on your home network (10.x, 172.16–31.x, 192.168.x, fc00::/7).")
        case "ip-form":
            return i18n("Write the IP address as four numbers, like 192.168.1.20, or IPv6 in its short form, like [fd00::1].")
        case "link-local":
            return i18n("Link-local and cloud metadata addresses (169.254.x.x, fe80::, fd00:ec2::) can't be added.")
        default:
            return i18n("This isn't a valid web address.")
        }
    }

    function ollamaAddressError(code) {
        switch (code) {
        case "":
            return ""
        case "too-long":
            return i18n("This address is too long.")
        case "whitespace":
            return i18n("Addresses can't contain spaces or line breaks.")
        case "userinfo":
            return i18n("Addresses with a user name or password aren't allowed.")
        case "scheme":
            return i18n("Use an address that starts with http://.")
        case "not-loopback":
            return i18n("Only this computer is allowed: 127.0.0.1, localhost or [::1].")
        case "port-missing":
            return i18n("Add the port, for example http://127.0.0.1:11434.")
        case "port-range":
            return i18n("The port must be between 1 and 65535.")
        case "path":
            return i18n("Use only the address and port, without a path.")
        default:
            return i18n("This isn't a valid address.")
        }
    }

    // The table's column widths, shared by the header and every row.
    readonly property real onColumnWidth: Kirigami.Units.gridUnit * 2
    readonly property real iconColumnWidth: Kirigami.Units.iconSizes.smallMedium
    readonly property real nameColumnWidth: Kirigami.Units.gridUnit * 10
    // The ↑ ↓ Edit Remove buttons' width, as the first row lays them out.
    property real actionsColumnWidth: 0

    // A tooltip that never reads its text as markup (addresses and names).
    component PlainToolTip: QQC2.ToolTip {
        id: tip
        contentItem: QQC2.Label {
            objectName: "plainToolTipText"
            text: tip.text
            textFormat: Text.PlainText
            wrapMode: Text.WrapAnywhere
        }
    }

    // The inline editor of one row (or of a new site), under that row, made
    // by a Repeater of 0 or 1 (no Loader on the settings pages). It
    // writes only on Save and only a valid value; Cancel or Escape closes
    // it unchanged.
    component SiteEditor: ColumnLayout {
        id: editor
        // A table id, or "new".
        required property string siteId
        readonly property var site: editor.siteId === OllamaChat.ENTRY.id ? OllamaChat.ENTRY
            : ChatSites.byId(editor.siteId, page.userSites)
        readonly property string kind: editor.siteId === "new" || (editor.site && editor.site.user === true)
            ? "user" : editor.siteId === OllamaChat.ENTRY.id ? "ollama" : "builtin"
        property string error: ""
        readonly property bool hostChange: editor.kind === "user" && editor.siteId !== "new"
            && page.hostChanges(editor.siteId, addressField.text)
        // The class of the address being typed (an added site only), for
        // the note under it.
        readonly property string addressKind: editor.kind === "user"
            ? ChatSites.addressClass(addressField.text.trim()) : ""
        readonly property bool addressHttp: /^http:/i.test(addressField.text.trim())
        readonly property bool notEncrypted: editor.addressKind === "private" && editor.addressHttp
        // An https address on the home network: it may be this computer's
        // own, which is checked like localhost would be (LOW-2).
        readonly property bool homeHttps: editor.addressKind === "private" && !editor.addressHttp

        Layout.fillWidth: true
        Layout.leftMargin: page.onColumnWidth + page.iconColumnWidth + Kirigami.Units.smallSpacing * 2
        // Its fields end where the table's addresses do, before the actions.
        Layout.rightMargin: page.actionsColumnWidth + Kirigami.Units.smallSpacing
        spacing: Kirigami.Units.smallSpacing

        function save() {
            if (editor.kind === "builtin")
                editor.error = page.saveCustomUrl(editor.siteId, addressField.text)
            else if (editor.kind === "ollama")
                editor.error = page.saveOllamaAddress(addressField.text)
            else
                editor.error = page.saveUserSite(editor.siteId, nameField.text, addressField.text)
        }

        Component.onCompleted: {
            if (editor.kind === "builtin") {
                addressField.text = page.savedCustomUrl(editor.siteId)
            } else if (editor.kind === "ollama") {
                // The default shows as the placeholder.
                addressField.text = page.cfg_chatOllamaUrl === OllamaChat.DEFAULT_ADDRESS
                    ? "" : page.cfg_chatOllamaUrl
            } else if (editor.site) {
                nameField.text = editor.site.name
                addressField.text = editor.site.url
            }
            if (editor.kind === "user")
                nameField.forceActiveFocus()
            else
                addressField.forceActiveFocus()
        }

        QQC2.Label {
            objectName: "editorFull"
            Layout.fillWidth: true
            visible: editor.siteId === "new" && !page.canAddSite
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            text: i18n("Can't add more sites.")
        }

        GridLayout {
            Layout.fillWidth: true
            visible: !(editor.siteId === "new" && !page.canAddSite)
            columns: 2
            columnSpacing: Kirigami.Units.smallSpacing
            rowSpacing: Kirigami.Units.smallSpacing

            QQC2.Label {
                visible: editor.kind === "user"
                text: i18n("Name:")
            }
            QQC2.TextField {
                id: nameField
                objectName: "editorName"
                visible: editor.kind === "user"
                Layout.fillWidth: true
                maximumLength: ChatSites.MAX_USER_SITE_NAME * 2
                inputMethodHints: Qt.ImhNoPredictiveText
                Accessible.name: i18n("Site name")
                // Enter saves this editor only; the settings dialog's OK
                // never sees it.
                Keys.onReturnPressed: (event) => { editor.save(); event.accepted = true }
                Keys.onEnterPressed: (event) => { editor.save(); event.accepted = true }
                Keys.onEscapePressed: page.closeEditor()
            }

            QQC2.Label {
                text: i18n("Address:")
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing
                QQC2.TextField {
                    id: addressField
                    objectName: "editorAddress"
                    Layout.fillWidth: true
                    placeholderText: editor.kind === "ollama" ? OllamaChat.DEFAULT_ADDRESS
                        : editor.kind === "builtin" && editor.site ? editor.site.url : "https://"
                    maximumLength: (editor.kind === "ollama" ? OllamaChat.MAX_ADDRESS_LENGTH
                        : ChatSites.MAX_CUSTOM_URL_LENGTH) * 2
                    inputMethodHints: Qt.ImhUrlCharactersOnly | Qt.ImhNoPredictiveText
                        | Qt.ImhNoAutoUppercase
                    Accessible.name: editor.kind === "ollama" ? i18n("Ollama address")
                        : editor.kind === "user" ? i18n("Site address")
                        : i18n("Address for %1", editor.site ? editor.site.name : "")
                    Keys.onReturnPressed: (event) => { editor.save(); event.accepted = true }
                    Keys.onEnterPressed: (event) => { editor.save(); event.accepted = true }
                    Keys.onEscapePressed: page.closeEditor()
                }
                QQC2.ToolButton {
                    objectName: "editorUseDefault"
                    visible: editor.kind !== "user"
                    icon.name: "edit-undo"
                    display: QQC2.AbstractButton.IconOnly
                    text: editor.kind === "ollama" ? i18n("Use the default address")
                        : i18n("Use the built-in address")
                    enabled: addressField.text !== ""
                    onClicked: addressField.text = ""
                    QQC2.ToolTip.text: text
                    QQC2.ToolTip.visible: hovered
                }
                Kirigami.ContextualHelpButton {
                    visible: editor.kind === "ollama"
                    toolTipText: i18n("Only this computer: http:// with 127.0.0.1, localhost or [::1] and a port. Leave empty for the default, http://127.0.0.1:11434.")
                }
            }

            // Under Address, live while typing: a home-network http address
            // isn't encrypted; one on this computer is owner-checked; a
            // home-network one should be localhost when it is this computer.
            Item {
                visible: editorNoteRow.visible
            }
            RowLayout {
                id: editorNoteRow
                Layout.fillWidth: true
                visible: editor.notEncrypted || editor.homeHttps || editor.addressKind === "loopback"
                spacing: Kirigami.Units.smallSpacing
                QQC2.Label {
                    objectName: "editorNote"
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    textFormat: Text.PlainText
                    text: editor.notEncrypted
                        ? i18n("Not encrypted on your network. https is recommended.")
                        : editor.homeHttps
                            ? i18n("For a server on this computer, use localhost.")
                            : i18n("Checked before loading: the program on this port must be yours or the system's.")
                }
                Kirigami.ContextualHelpButton {
                    objectName: "editorNoteHelp"
                    visible: editor.notEncrypted
                    toolTipText: i18n("Anyone on your network can read and change this traffic. On another network (a café, a hotel) a different device can have the same address and would get this site's sign-in and saved data. Use https with a certificate your system trusts to rule this out. For a server on this computer, use localhost: when this address is this computer's own, Hearthwire still checks that the program on the port is yours or the system's.")
                }
            }
        }

        // Saving another host makes it another site (M1).
        QQC2.Label {
            objectName: "editorHostChange"
            Layout.fillWidth: true
            visible: editor.hostChange
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            color: Kirigami.Theme.negativeTextColor
            text: i18n("This is another site: Hearthwire signs you out of %1 and deletes its site data.",
                       editor.site ? editor.site.name : "")
        }

        QQC2.Label {
            objectName: "editorError"
            Layout.fillWidth: true
            visible: editor.error !== ""
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            color: Kirigami.Theme.negativeTextColor
            text: editor.kind === "builtin" ? page.customUrlError(editor.siteId, editor.error)
                : editor.kind === "ollama" ? page.ollamaAddressError(editor.error)
                : page.userSiteError(editor.error, addressField.text)
        }

        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            QQC2.Button {
                objectName: "editorSave"
                visible: !(editor.siteId === "new" && !page.canAddSite)
                icon.name: "document-save"
                text: editor.siteId === "new" ? i18n("Add") : i18n("Save")
                onClicked: editor.save()
            }
            QQC2.Button {
                objectName: "editorCancel"
                icon.name: "dialog-cancel"
                text: i18n("Cancel")
                onClicked: page.closeEditor()
            }
        }
    }

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Kirigami.Heading {
                level: 2
                text: i18n("Chat sites")
            }
            Kirigami.ContextualHelpButton {
                toolTipText: i18n("Sites open in a private, in-memory browser profile unless Stay signed in is on (General). The widget never reads or changes the pages and sends nothing to the developer. Microphone, camera, screen sharing, notifications, location and clipboard reading are always denied. Downloads ask first and go to your Downloads folder. Links to other websites open in your browser. Text you copy may be kept by your clipboard manager. Each open site uses roughly 200–500 MB of memory.")
            }
        }
        QQC2.Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: i18n("Custom and added addresses are saved in your Plasma configuration file: don't put passwords, tokens or other secrets in them.")
            opacity: 0.72
        }

        // Header row.
        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            QQC2.Label {
                Layout.preferredWidth: page.onColumnWidth
                text: i18nc("column: the site is enabled", "On")
                font.bold: true
                elide: Text.ElideRight
            }
            Item {
                Layout.preferredWidth: page.iconColumnWidth
            }
            QQC2.Label {
                Layout.preferredWidth: page.nameColumnWidth
                text: i18n("Name")
                font.bold: true
                elide: Text.ElideRight
            }
            QQC2.Label {
                Layout.fillWidth: true
                text: i18n("Address")
                font.bold: true
                elide: Text.ElideRight
            }
        }

        Repeater {
            model: page.tableSites

            delegate: ColumnLayout {
                id: siteRow
                objectName: "siteRow"
                required property var modelData
                required property int index
                readonly property string siteId: siteRow.modelData.id
                readonly property bool added: siteRow.modelData.user === true
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    Item {
                        Layout.preferredWidth: page.onColumnWidth
                        implicitHeight: siteCheck.implicitHeight
                        QQC2.CheckBox {
                            id: siteCheck
                            objectName: "siteOn"
                            checked: page.enabledIds.indexOf(siteRow.siteId) >= 0
                            onToggled: page.setEnabled(siteRow.siteId, checked)
                            Accessible.name: i18n("Show %1", siteRow.modelData.name)
                        }
                    }
                    Item {
                        Layout.preferredWidth: page.iconColumnWidth
                        Layout.preferredHeight: page.iconColumnWidth
                        Kirigami.Icon {
                            anchors.fill: parent
                            visible: !siteRow.added
                            source: siteRow.added ? "" : Qt.resolvedUrl("../images/" + siteRow.modelData.icon)
                            isMask: true
                            color: Kirigami.Theme.textColor
                        }
                        LetterBadge {
                            anchors.centerIn: parent
                            visible: siteRow.added
                            name: siteRow.added ? siteRow.modelData.name : ""
                            size: page.iconColumnWidth
                        }
                    }
                    RowLayout {
                        Layout.preferredWidth: page.nameColumnWidth
                        Layout.maximumWidth: page.nameColumnWidth
                        spacing: Kirigami.Units.smallSpacing
                        QQC2.Label {
                            objectName: "siteName"
                            Layout.fillWidth: true
                            textFormat: Text.PlainText
                            text: siteRow.modelData.native === true
                                ? i18n("%1 (built-in chat with Ollama on this computer)", siteRow.modelData.name)
                                : siteRow.modelData.name
                            elide: Text.ElideRight
                            MouseArea {
                                anchors.fill: parent
                                onClicked: page.setEnabled(siteRow.siteId, !siteCheck.checked)
                            }
                        }
                        Kirigami.ContextualHelpButton {
                            visible: siteRow.modelData.native === true
                            toolTipText: i18n("The conversation is kept in memory only and goes to the Ollama server on this computer, nowhere else. Clear also unloads the models it used. Cloud models are hidden. Before sending, Hearthwire checks that the Ollama port belongs to you or to the system, never to another user. Hearthwire never starts Ollama.")
                        }
                        Kirigami.ContextualHelpButton {
                            visible: siteRow.modelData.local === true
                            toolTipText: i18n("http is allowed only for this computer (localhost, 127.0.0.1, [::1]). For a server elsewhere on your home network, add it with Add site…, or use https or an SSH tunnel.")
                        }
                    }
                    QQC2.Label {
                        id: addressLabel
                        objectName: "siteAddress"
                        Layout.fillWidth: true
                        textFormat: Text.PlainText
                        text: page.rowHost(siteRow.modelData)
                        elide: Text.ElideLeft
                        opacity: 0.72
                        HoverHandler {
                            id: addressHover
                        }
                        PlainToolTip {
                            objectName: "siteAddressTip"
                            text: page.rowAddress(siteRow.modelData)
                            visible: addressHover.hovered && addressLabel.text !== ""
                        }
                    }
                    RowLayout {
                        id: actionsRow
                        spacing: Kirigami.Units.smallSpacing
                        // Added sites stay as they are while the list can't be read.
                        readonly property bool locked: siteRow.added && !page.userSitesReadable

                        QQC2.ToolButton {
                            id: upButton
                            objectName: "moveUp"
                            icon.name: "go-up"
                            display: QQC2.AbstractButton.IconOnly
                            text: i18n("Move %1 up", siteRow.modelData.name)
                            enabled: siteRow.index > 0 && !actionsRow.locked
                            onClicked: page.moveSite(siteRow.siteId, -1)
                            PlainToolTip {
                                text: upButton.text
                                visible: upButton.hovered
                            }
                        }
                        QQC2.ToolButton {
                            id: downButton
                            objectName: "moveDown"
                            icon.name: "go-down"
                            display: QQC2.AbstractButton.IconOnly
                            text: i18n("Move %1 down", siteRow.modelData.name)
                            enabled: siteRow.index < page.tableSites.length - 1 && !actionsRow.locked
                            onClicked: page.moveSite(siteRow.siteId, 1)
                            PlainToolTip {
                                text: downButton.text
                                visible: downButton.hovered
                            }
                        }
                        QQC2.ToolButton {
                            id: editButton
                            objectName: "editSite"
                            icon.name: "document-edit"
                            display: QQC2.AbstractButton.IconOnly
                            text: i18n("Edit %1", siteRow.modelData.name)
                            enabled: !actionsRow.locked
                            checkable: true
                            checked: page.editingId === siteRow.siteId
                            onClicked: page.editingId === siteRow.siteId ? page.closeEditor()
                                : page.openEditor(siteRow.siteId)
                            PlainToolTip {
                                text: editButton.text
                                visible: editButton.hovered
                            }
                        }
                        QQC2.ToolButton {
                            id: removeButton
                            objectName: "removeSite"
                            icon.name: "list-remove"
                            display: QQC2.AbstractButton.IconOnly
                            text: i18n("Remove %1", siteRow.modelData.name)
                            // Built-ins keep the column's width.
                            opacity: siteRow.added ? 1 : 0
                            enabled: siteRow.added && !actionsRow.locked
                            Accessible.ignored: !siteRow.added
                            onClicked: {
                                page.closeEditor()
                                page.confirmingRemove = siteRow.siteId
                            }
                            PlainToolTip {
                                text: removeButton.text
                                visible: removeButton.hovered && siteRow.added
                            }
                        }
                    }
                }

                // The editors' right edge follows the action buttons.
                Binding {
                    target: page
                    property: "actionsColumnWidth"
                    value: actionsRow.implicitWidth
                    when: siteRow.index === 0
                    restoreMode: Binding.RestoreNone
                }

                // Remove asks first, in the row.
                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: page.onColumnWidth + page.iconColumnWidth + Kirigami.Units.smallSpacing * 2
                    visible: page.confirmingRemove === siteRow.siteId
                    spacing: Kirigami.Units.smallSpacing
                    QQC2.Label {
                        objectName: "removeText"
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        textFormat: Text.PlainText
                        text: i18n("Remove %1? This also signs you out of %1 and deletes its site data.",
                                   siteRow.modelData.name)
                    }
                    QQC2.Button {
                        objectName: "removeConfirm"
                        icon.name: "list-remove"
                        text: i18n("Remove")
                        onClicked: page.removeUserSite(siteRow.siteId)
                    }
                    QQC2.Button {
                        objectName: "removeCancel"
                        icon.name: "dialog-cancel"
                        text: i18n("Cancel")
                        onClicked: page.confirmingRemove = ""
                    }
                }

                // The row's editor while it is open (a fresh one each time).
                Repeater {
                    model: page.editingId === siteRow.siteId ? 1 : 0
                    delegate: SiteEditor {
                        siteId: siteRow.siteId
                    }
                }
            }
        }

        // An added site this version can't read (a hand edit, a newer
        // version's entry): nothing about added sites changes here.
        QQC2.Label {
            objectName: "damagedSites"
            Layout.fillWidth: true
            visible: !page.userSitesReadable
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            color: Kirigami.Theme.negativeTextColor
            text: i18n("Some added sites can't be read by this version, so added sites can't be added, changed, moved or removed here. Nothing is deleted while this is so.")
        }

        QQC2.Button {
            objectName: "addSite"
            enabled: page.userSitesReadable
            icon.name: "list-add"
            text: i18n("Add site…")
            checkable: true
            checked: page.editingId === "new"
            onClicked: page.editingId === "new" ? page.closeEditor() : page.openEditor("new")
        }
        Repeater {
            model: page.editingId === "new" ? 1 : 0
            delegate: SiteEditor {
                siteId: "new"
            }
        }

        // Every way a site goes before Apply (Remove, another host,
        // Defaults, a backup Replace): said until Apply or Cancel.
        QQC2.Label {
            objectName: "removalWarning"
            Layout.fillWidth: true
            visible: page.removedUserSiteIds.length > 0
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            color: Kirigami.Theme.negativeTextColor
            text: i18np("When you apply, %1 removed site is signed out and its site data is deleted.",
                        "When you apply, %1 removed sites are signed out and their site data is deleted.",
                        page.removedUserSiteIds.length)
        }

        Kirigami.FormLayout {
            Layout.fillWidth: true

            QQC2.ComboBox {
                objectName: "openFirst"
                Kirigami.FormData.label: i18n("Open first:")
                enabled: page.enabledSites.length > 0
                model: page.enabledSites
                textRole: "name"
                valueRole: "id"
                currentIndex: Math.max(0, page.enabledIds.indexOf(
                    ChatSites.initialSite(page.enabledIds, page.cfg_chatDefaultSite)
                ))
                onActivated: page.cfg_chatDefaultSite = currentValue
                delegate: QQC2.ItemDelegate {
                    id: firstDelegate
                    required property var modelData
                    required property int index
                    width: ListView.view ? ListView.view.width : implicitWidth
                    highlighted: ListView.isCurrentItem
                    contentItem: QQC2.Label {
                        textFormat: Text.PlainText
                        text: firstDelegate.modelData.name
                        elide: Text.ElideRight
                    }
                }
            }
        }

        QQC2.Label {
            Layout.fillWidth: true
            visible: page.enabledSites.length === 0
            text: i18n("The Chat tab is hidden while no site is enabled.")
            wrapMode: Text.WordWrap
            opacity: 0.72
        }
        QQC2.Label {
            Layout.fillWidth: true
            visible: !page.cfg_showChatTab
            text: i18n("The Chat tab is hidden in General.")
            wrapMode: Text.WordWrap
            opacity: 0.72
        }
    }
}
