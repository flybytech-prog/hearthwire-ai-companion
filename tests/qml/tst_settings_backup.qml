import QtQuick
import QtTest
import "../../plasmoid/contents/ui/ChatSites.js" as ChatSites
import "../../plasmoid/contents/ui/ChatStorage.js" as ChatStorage
import "../../plasmoid/contents/ui/OllamaChat.js" as OllamaChat
import "../../plasmoid/contents/ui/ProviderCatalog.js" as Catalog
import "../../plasmoid/contents/ui/SettingsBackup.js" as SettingsBackup
import "../../plasmoid/contents/ui/SettingsLogic.js" as SettingsLogic
import "../../plasmoid/contents/ui/UsageLogic.js" as UsageLogic

TestCase {
    id: testCase
    name: "SettingsBackup"

    readonly property string stamp: "2026-11-06T00:10:29Z"
    readonly property var good: ({
        trackedProviders: "[\"claude\",\"codex\"]",
        providerMetrics: "{\"claude\":[\"session\",\"weekly\"]}",
        providerOrder: "[\"codex\",\"claude\"]",
        usageMode: "used",
        refreshInterval: 900,
        tooltipShowsUsage: false,
        tooltipMetrics: "{\"claude\":[\"weekly\"],\"codex\":[]}",
        usageCompact: true,
        usageWarnPercent: 70,
        usageCriticalPercent: 90,
        usageNormalColor: "#00aaff",
        usageWarnColor: "",
        usageCriticalColor: "#ff0000",
        alertLowEnabled: true,
        alertResetEnabled: true,
        alertLowPercent: 40,
        chatSites: "[\"claude\",\"ollama\",\"local\",\"user-3fa9c01b\"]",
        chatDefaultSite: "ollama",
        chatOllamaUrl: "http://[::1]:11434",
        chatKeepOpen: true,
        showUsageTab: true,
        showChatTab: false,
        popupDefaultTab: "usage",
        popupSize: "large",
        shortcutOpens: "ollama",
        panelRing: "codex.spark_weekly",
        middleClickOpens: "mscopilot",
        chatCustomUrls: "{\"claude\":\"https://claude.example.org/new?x=1\",\"local\":\"http://localhost:8080/\"}",
        chatUserSites: "[{\"id\":\"user-3fa9c01b\",\"name\":\"Le Chat\",\"url\":\"https://chat.mistral.ai/chat\"}]",
        chatSiteOrder: "[\"user-3fa9c01b\",\"claude\",\"ollama\"]"
    })

    function tools() {
        return {
            providers: Catalog.providers,
            webSiteIds: ChatSites.siteIds(),
            ringPairs: UsageLogic.ringOptions(Catalog.providers).map(function (option) { return option.value }),
            validateCustomUrl: ChatSites.validateCustomUrl,
            ollamaAddress: OllamaChat.checkedAddress,
            userSiteIds: function (text) {
                return ChatSites.parseUserSites(text).sites.map(function (site) { return site.id })
            },
            validateUserSite: ChatSites.validateUserSite,
            serializeUserSites: ChatSites.serializeUserSites
        }
    }

    function plan(settings, dropped) {
        return SettingsBackup.importPlan(settings, dropped === undefined ? 0 : dropped, tools())
    }

    function reply(op, object) {
        return SettingsBackup.parseReply(op, 0, JSON.stringify(object))
    }

    readonly property var bad: ({ok: false, error: "bad-reply"})

    function test_listsMatchTheOtherLibraries() {
        compare(SettingsBackup.WARN_PERCENTS, UsageLogic.WARN_PERCENTS)
        compare(SettingsBackup.CRITICAL_PERCENTS, UsageLogic.CRITICAL_PERCENTS)
        compare(SettingsBackup.ALERT_PERCENTS, SettingsLogic.ALERT_PERCENTS)
        compare(SettingsBackup.POPUP_TABS, SettingsLogic.POPUP_TABS)
        compare(SettingsBackup.POPUP_SIZES, SettingsLogic.POPUP_SIZES)
        compare(SettingsBackup.SHORTCUT_TARGETS, SettingsLogic.SHORTCUT_TARGETS)
        compare(SettingsBackup.OLLAMA_ID, OllamaChat.ENTRY.id)
    }

    function test_keyListsDoNotOverlap() {
        compare(SettingsBackup.BACKUP_KEYS.length, 30)
        // Task 005's two keys come last, as in the helper.
        compare(SettingsBackup.BACKUP_KEYS.slice(-2), ["chatUserSites", "chatSiteOrder"])
        SettingsBackup.EXCLUDED_KEYS.forEach(function (key) {
            verify(SettingsBackup.BACKUP_KEYS.indexOf(key) < 0, key)
        })
        verify(SettingsBackup.EXCLUDED_KEYS.indexOf("usageHistoryEnabled") >= 0)
    }

    readonly property string helper: "env HEARTHWIRE_RUN=7 python3 -P -m hearthwire --settings-backup "

    // Every step names the widget; export carries no settings at all.
    function test_commands() {
        compare(SettingsBackup.backupCommand("status", 7, 3), helper + "status --applet 3")
        compare(SettingsBackup.backupCommand("import", 0, 3), "env HEARTHWIRE_RUN=0 python3 -P -m hearthwire --settings-backup import --applet 3")
        compare(SettingsBackup.backupCommand("export", 7, 3), helper + "export --applet 3")
        compare(SettingsBackup.backupCommand("export", 7, 2147483648), helper + "export --applet 2147483648")
        compare(SettingsBackup.backupCommand("export", 7, 3, "7b7d"), helper + "export --applet 3", "a fourth argument is ignored")
    }

    function test_noDataArgument() {
        compare(SettingsBackup.exportPayload, undefined, "nothing builds settings for the command line")
        compare(SettingsBackup.MAX_DATA_HEX, undefined)
        SettingsBackup.OPERATIONS.forEach(function (op) {
            verify(SettingsBackup.backupCommand(op, 7, 3).indexOf("--data") < 0, op)
        })
    }

    function test_appletBoundMatchesChatStorage() {
        compare(SettingsBackup.MAX_APPLET, ChatStorage.MAX_INT)
    }

    function test_commandsRefuseAnythingOdd() {
        compare(SettingsBackup.backupCommand("delete", 7, 3), "")
        compare(SettingsBackup.backupCommand("status; rm", 7, 3), "")
        compare(SettingsBackup.backupCommand("status", -1, 3), "")
        compare(SettingsBackup.backupCommand("status", 1.5, 3), "")
        compare(SettingsBackup.backupCommand("status", "7", 3), "")
    }

    // A widget id like chatAppletId's, and never 0.
    function test_commandsRefuseAnOddApplet() {
        var odd = [undefined, null, 0, -1, 1.5, "3", "3 --data 7b7d", NaN, Infinity, 2147483649, [3], true]
        SettingsBackup.OPERATIONS.forEach(function (op) {
            odd.forEach(function (applet) {
                compare(SettingsBackup.backupCommand(op, 7, applet), "", op + " " + String(applet))
            })
        })
        compare(SettingsBackup.validApplet(1), true)
        compare(SettingsBackup.validApplet(0), false)
    }

    function test_shownStamp() {
        compare(SettingsBackup.shownStamp(stamp), "2026-11-06 00:10:29 UTC")
        compare(SettingsBackup.shownStamp("<b>x</b>"), "")
        compare(SettingsBackup.shownStamp(undefined), "")
    }

    function test_goodReplies() {
        compare(reply("status", {ok: true, exists: false}), {ok: true, exists: false, exportedAt: ""})
        compare(reply("status", {ok: true, exists: true, exported_at: stamp}), {ok: true, exists: true, exportedAt: stamp})
        compare(reply("export", {ok: true, saved: 28, dropped: 1}), {ok: true, saved: 28, dropped: 1})
        compare(reply("import", {ok: true, exported_at: stamp, settings: {popupSize: "large"}, dropped: 2}),
                {ok: true, exportedAt: stamp, settings: {popupSize: "large"}, dropped: 2})
    }

    function test_errorCodesKept() {
        SettingsBackup.ERRORS.forEach(function (code) {
            compare(reply("import", {ok: false, error: code}), {ok: false, error: code})
        })
        compare(SettingsBackup.ERRORS, ["absent", "invalid", "unsupported", "too-large", "bad-data", "symlink",
                                        "not-owned", "unsafe-mode", "legacy-data", "os-error", "applet-not-found",
                                        "settings-unreadable"])
    }

    function test_rejectsBadReplies() {
        compare(SettingsBackup.parseReply("status", 1, "{\"ok\":true,\"exists\":false}"), bad, "exit code")
        compare(SettingsBackup.parseReply("nope", 0, "{\"ok\":true,\"exists\":false}"), bad, "op")
        compare(SettingsBackup.parseReply("status", 0, undefined), bad, "stdout")
        compare(SettingsBackup.parseReply("status", 0, ""), bad, "empty")
        compare(SettingsBackup.parseReply("status", 0, "{"), bad, "json")
        compare(SettingsBackup.parseReply("status", 0, "[]"), bad, "array")
        compare(SettingsBackup.parseReply("status", 0, "{\"ok\":true,\"exists\":false}" + new Array(530000).join(" ")), bad, "oversized")
        compare(reply("status", {ok: 1, exists: false}), bad, "ok truthy")
        compare(reply("status", {ok: true}), bad, "no exists")
        compare(reply("status", {ok: true, exists: "no"}), bad, "exists type")
        compare(reply("status", {ok: true, exists: false, x: 1}), bad, "extra")
        compare(reply("status", {ok: true, exists: true}), bad, "no stamp")
        compare(reply("status", {ok: true, exists: true, exported_at: "/home/soul"}), bad, "stamp")
        compare(reply("status", {ok: true, exists: true, exported_at: stamp, x: 1}), bad, "extra with stamp")
        compare(reply("export", {ok: true, saved: 0, dropped: 0}), bad, "nothing saved")
        compare(reply("export", {ok: true, saved: 1.5, dropped: 0}), bad, "saved type")
        compare(reply("export", {ok: true, saved: 1, dropped: -1}), bad, "dropped")
        compare(reply("export", {ok: true, saved: 1, dropped: 0, x: 1}), bad, "extra")
        compare(reply("import", {ok: true, exported_at: "x", settings: {}, dropped: 0}), bad, "import stamp")
        compare(reply("import", {ok: true, exported_at: stamp, settings: [], dropped: 0}), bad, "settings type")
        compare(reply("import", {ok: true, exported_at: stamp, settings: {}, dropped: "0"}), bad, "dropped type")
        compare(reply("import", {ok: true, exported_at: stamp, settings: {}, dropped: 0, x: 1}), bad, "extra")
    }

    function test_replyErrorsNeverCarryTheirText() {
        compare(reply("status", {ok: false, error: "/home/soul secret"}), bad)
        compare(reply("status", {ok: false, error: "busy"}), bad, "not a code of this command")
        compare(reply("status", {ok: false, error: "absent", detail: "x"}), bad)
        compare(reply("status", {ok: false, error: 3}), bad)
    }

    function test_planKeepsEveryGoodKey() {
        var result = plan(good, 0)
        compare(result.settings, good)
        compare(result.applied, 30)
        compare(result.dropped, 0)
    }

    // --- task 005: added sites and the site order ---------------------------

    function site(id, name, url) {
        return {id: id, name: name, url: url}
    }

    function sitesText(list) {
        return JSON.stringify(list)
    }

    readonly property var mistral: ({id: "user-3fa9c01b", name: "Le Chat", url: "https://chat.mistral.ai/chat"})
    readonly property var deepseek: ({id: "user-00c0ffee", name: "DeepSeek", url: "https://chat.deepseek.com/"})

    function test_replyBoundFollowsTheHelperFile() {
        compare(SettingsBackup.MAX_REPLY_CHARS, 512 * 1024 + 1024)
        compare(SettingsBackup.MAX_USER_SITES, ChatSites.MAX_USER_SITES)
        compare(SettingsBackup.MAX_USER_SITES_CHARS, ChatSites.MAX_USER_SITES_CHARS)
        var padded = function (length) {
            var head = "{\"ok\":true,\"exists\":false}"
            return head + new Array(length - head.length + 1).join(" ")
        }
        compare(SettingsBackup.parseReply("status", 0, padded(SettingsBackup.MAX_REPLY_CHARS)),
                {ok: true, exists: false, exportedAt: ""})
        compare(SettingsBackup.parseReply("status", 0, padded(SettingsBackup.MAX_REPLY_CHARS + 1)), bad)
    }

    // Kept as the widget writes it: keys in id, name, url order.
    function test_planUserSitesCanonical() {
        var result = plan({chatUserSites: "[{\"url\":\"https://chat.mistral.ai/chat\",\"name\":\"Le Chat\",\"id\":\"user-3fa9c01b\"}]"})
        compare(result.settings.chatUserSites, sitesText([mistral]))
        compare(result.dropped, 0)
        compare(plan({chatUserSites: "[]"}).settings.chatUserSites, "[]")
    }

    // One odd entry drops the whole setting, counted once.
    function test_planUserSitesStrict_data() {
        var extra = function (key, value) {
            var entry = Object.assign({}, mistral)
            entry[key] = value
            return sitesText([entry])
        }
        return [
            {tag: "local key", value: extra("local", true)},
            {tag: "local_kind key", value: extra("local_kind", "loopback")},
            {tag: "site_hosts key", value: extra("site_hosts", ["evil.example"])},
            {tag: "auth_hosts key", value: extra("auth_hosts", ["evil.example"])},
            {tag: "icon key", value: extra("icon", "x.svg")},
            {tag: "missing url", value: sitesText([{id: mistral.id, name: mistral.name}])},
            {tag: "bad id", value: sitesText([site("user-3FA9C01B", "A", "https://a.example/")])},
            {tag: "built-in id", value: sitesText([site("claude", "A", "https://a.example/")])},
            {tag: "duplicate id", value: sitesText([mistral, site(mistral.id, "Other", "https://o.example/")])},
            {tag: "name taken by another", value: sitesText([mistral, site("user-00000002", "le chat", "https://o.example/")])},
            {tag: "built-in name", value: sitesText([site("user-00000002", "CLAUDE", "https://o.example/")])},
            {tag: "Ollama name", value: sitesText([site("user-00000002", "ollama", "https://o.example/")])},
            {tag: "untrimmed name", value: sitesText([site("user-00000002", " A", "https://o.example/")])},
            {tag: "bidi name", value: sitesText([site("user-00000002", "A\u202eB", "https://o.example/")])},
            {tag: "markup name", value: sitesText([site("user-00000002", "<b>A</b>", "https://o.example/")])},
            {tag: "http", value: sitesText([site("user-00000002", "A", "http://a.example/")])},
            {tag: "loopback", value: sitesText([site("user-00000002", "A", "https://localhost./")])},
            {tag: "other loopback", value: sitesText([site("user-00000002", "A", "http://127.0.0.2/")])},
            {tag: "odd ip form", value: sitesText([site("user-00000002", "A", "http://192.168.1.020/")])},
            {tag: "link-local", value: sitesText([site("user-00000002", "A", "http://169.254.169.254/")])},
            {tag: "http name", value: sitesText([site("user-00000002", "A", "http://nas.local/")])},
            {tag: "ip literal", value: sitesText([site("user-00000002", "A", "https://8.8.8.8/")])},
            {tag: "not a list", value: JSON.stringify(mistral)},
            {tag: "not JSON", value: "[{"},
            {tag: "not text", value: 7}
        ]
    }

    function test_planUserSitesStrict(data) {
        var result = plan({chatUserSites: data.value, popupSize: "large"})
        verify(result.settings.chatUserSites === undefined, data.tag)
        compare(result.applied, 1)
        compare(result.dropped, 1)
    }

    function manySites(count) {
        var list = []
        for (var index = 0; index < count; index++) {
            var hex = ("0000000" + index.toString(16)).slice(-8)
            list.push(site("user-" + hex, "Site " + index, "https://s" + index + ".example.org/"))
        }
        return list
    }

    function test_planUserSitesCaps() {
        var full = sitesText(manySites(200))
        compare(plan({chatUserSites: full}).settings.chatUserSites, full)
        compare(plan({chatUserSites: sitesText(manySites(201))}).dropped, 1)
        // Past the char cap: dropped, whatever it holds.
        var long = sitesText([site("user-00000001", "A", "https://a.example/?" + new Array(2030).join("x"))])
        compare(plan({chatUserSites: long}).settings.chatUserSites, long)
        compare(plan({chatUserSites: long + new Array(ChatSites.MAX_USER_SITES_CHARS).join(" ")}).dropped, 1)
    }

    // 200 added ids fit chatSites and chatSiteOrder (4096 characters).
    function test_planTwoHundredAddedIdsFit() {
        var list = manySites(200)
        var ids = ChatSites.siteIds().concat(list.map(function (entry) { return entry.id }), ["ollama"])
        var text = JSON.stringify(ids)
        verify(text.length <= SettingsBackup.MAX_STRING_CHARS, text.length)
        var result = plan({chatUserSites: sitesText(list), chatSites: text, chatSiteOrder: text})
        compare(result.settings.chatSites, text)
        compare(result.settings.chatSiteOrder, text)
        compare(result.dropped, 0)
    }

    function test_planSiteOrder() {
        compare(plan({chatSiteOrder: ""}).settings.chatSiteOrder, "")
        compare(plan({chatSiteOrder: "[\"ollama\",\"grok\"]"}).settings.chatSiteOrder, "[\"ollama\",\"grok\"]")
        compare(plan({chatSiteOrder: "[\"grok\",\"grok\"]"}).dropped, 1, "an id twice")
        compare(plan({chatSiteOrder: "[\"grok\",\"devin\"]"}).dropped, 1, "unknown id")
        compare(plan({chatSiteOrder: "{}"}).dropped, 1, "not a list")
        compare(plan({chatSiteOrder: 3}).dropped, 1, "not text")
    }

    // The four keys that may name an added id: only one the same import's
    // chatUserSites keeps.
    function test_planCrossKey_data() {
        return [
            {tag: "chatSites", key: "chatSites", known: "[\"claude\",\"user-3fa9c01b\"]",
             unknown: "[\"claude\",\"user-00000009\"]"},
            {tag: "chatSiteOrder", key: "chatSiteOrder", known: "[\"user-3fa9c01b\",\"claude\"]",
             unknown: "[\"user-00000009\",\"claude\"]"},
            {tag: "chatDefaultSite", key: "chatDefaultSite", known: "user-3fa9c01b", unknown: "user-00000009"},
            {tag: "middleClickOpens", key: "middleClickOpens", known: "user-3fa9c01b", unknown: "user-00000009"}
        ]
    }

    function test_planCrossKey(data) {
        var users = sitesText([mistral])
        var settings = {chatUserSites: users}
        settings[data.key] = data.known
        var kept = plan(settings)
        compare(kept.settings[data.key], data.known)
        compare(kept.dropped, 0)
        settings[data.key] = data.unknown
        var dropped = plan(settings)
        verify(dropped.settings[data.key] === undefined)
        compare(dropped.settings.chatUserSites, users)
        compare(dropped.dropped, 1)
        // No chatUserSites (or a dropped one): no added id at all.
        var alone = {}
        alone[data.key] = data.known
        compare(plan(alone).dropped, 1)
        var broken = {chatUserSites: sitesText([Object.assign({local: true}, mistral)])}
        broken[data.key] = data.known
        compare(plan(broken).dropped, 2)
        compare(plan(broken).applied, 0)
        // The page's own added sites never count.
        var tools = testCase.tools()
        tools.userSiteIds = function () { return [] }
        compare(SettingsBackup.importPlan(settings, 0, tools).dropped, 1)
    }

    // Round 2 (SEC L-2): a backup site whose id the page has on another host
    // is another site; it gets a new id, the other keys follow it, and the
    // confirmation lists Removes and Adds.
    function renewTools(current, ids) {
        var tools = testCase.tools()
        var next = (ids || ["user-0000aaaa", "user-0000bbbb"]).slice()
        tools.currentUserSites = current
        tools.userSiteHosts = ChatSites.userSiteHosts
        tools.newUserSiteId = function (excluded) {
            var id = next.shift() || ""
            tools.asked = (tools.asked || []).concat([excluded.slice()])
            return id
        }
        tools.excludedIds = ["user-00c0ffee"]
        return tools
    }

    function test_planRenewsAMovedSite() {
        var moved = site(mistral.id, "Le Chat", "https://other.example.org/chat")
        var settings = {chatUserSites: sitesText([moved, deepseek]),
                        chatSites: JSON.stringify(["claude", mistral.id, deepseek.id]),
                        chatSiteOrder: JSON.stringify([mistral.id, "claude"]),
                        chatDefaultSite: mistral.id, middleClickOpens: mistral.id}
        var tools = renewTools([mistral, deepseek])
        var result = SettingsBackup.importPlan(settings, 0, tools)
        compare(result.settings.chatUserSites,
                sitesText([site("user-0000aaaa", "Le Chat", "https://other.example.org/chat"), deepseek]))
        compare(result.settings.chatSites, JSON.stringify(["claude", "user-0000aaaa", deepseek.id]))
        compare(result.settings.chatSiteOrder, JSON.stringify(["user-0000aaaa", "claude"]))
        compare(result.settings.chatDefaultSite, "user-0000aaaa")
        compare(result.settings.middleClickOpens, "user-0000aaaa")
        compare(result.applied, 5)
        compare(result.dropped, 0)
        // Never an id the page, the backup or an owed delete has.
        var excluded = tools.asked[0]
        ;[mistral.id, deepseek.id, "user-00c0ffee"].forEach(function (id) { verify(excluded.indexOf(id) >= 0, id) })
        // The page sees the old site removed and the new one added.
        var listed = SettingsBackup.addressChanges({chatUserSites: sitesText([mistral, deepseek])}, result,
                                                   addressTools())
        compare(listed, [{kind: "add", id: "user-0000aaaa", name: "Le Chat", host: "other.example.org", http: false},
                         {kind: "remove", id: mistral.id, name: "Le Chat"}])
    }

    function test_planKeepsTheIdOnTheSameHost() {
        var moved = site(mistral.id, "Mistral", "https://chat.mistral.ai/other")
        var result = SettingsBackup.importPlan({chatUserSites: sitesText([moved])}, 0, renewTools([mistral]))
        compare(result.settings.chatUserSites, sitesText([moved]))
        // A site the page doesn't have keeps its id too.
        result = SettingsBackup.importPlan({chatUserSites: sitesText([pi()])}, 0, renewTools([mistral]))
        compare(result.settings.chatUserSites, sitesText([pi()]))
    }

    function pi() {
        return site("user-0000beef", "Pi", "https://pi.ai/talk")
    }

    // Round 3 (SEC L-2b): an id the applied settings hold but the page can't
    // read has no known host, so a backup entry with it is renewed too.
    function test_planRenewsAnUnreadableId() {
        var evil = site("user-0000beef", "Pi", "https://evil.example/")
        var tools = renewTools([mistral])
        tools.unreadableIds = ["user-0000beef"]
        var result = SettingsBackup.importPlan({chatUserSites: sitesText([mistral, evil]),
                                                chatDefaultSite: "user-0000beef"}, 0, tools)
        compare(result.settings.chatUserSites,
                sitesText([mistral, site("user-0000aaaa", "Pi", "https://evil.example/")]))
        compare(result.settings.chatDefaultSite, "user-0000aaaa")
        verify(tools.asked[0].indexOf("user-0000beef") >= 0, "never the unreadable id itself")
        // Listed as an add with a new id; the old one goes through the
        // removal warning (it is in the applied text).
        compare(SettingsBackup.addressChanges({chatUserSites: sitesText([mistral])}, result, addressTools()),
                [{kind: "add", id: "user-0000aaaa", name: "Pi", host: "evil.example", http: false}])
        // An unreadable entry whose url names a host is compared by it: the
        // same host keeps its id, another host is renewed.
        var hosted = renewTools([mistral])
        hosted.unreadableHosts = {"user-0000beef": "pi.ai"}
        compare(SettingsBackup.importPlan({chatUserSites: sitesText([pi()])}, 0, hosted).settings.chatUserSites,
                sitesText([pi()]))
        hosted = renewTools([mistral])
        hosted.unreadableHosts = {"user-0000beef": "pi.ai"}
        compare(SettingsBackup.importPlan({chatUserSites: sitesText([evil])}, 0, hosted).settings.chatUserSites,
                sitesText([site("user-0000aaaa", "Pi", "https://evil.example/")]))
        // Without unreadable ids it keeps its id (a new site).
        var plain = SettingsBackup.importPlan({chatUserSites: sitesText([evil])}, 0, renewTools([mistral]))
        compare(plain.settings.chatUserSites, sitesText([evil]))
    }

    // No usable new id: the list is dropped (the page keeps its own).
    function test_planDropsAMovedSiteWithoutANewId() {
        var moved = site(mistral.id, "Le Chat", "https://other.example.org/")
        var bad = [[""], ["claude"], ["user-00c0ffee"], [mistral.id]]
        bad.forEach(function (ids) {
            var result = SettingsBackup.importPlan({chatUserSites: sitesText([moved]), popupSize: "large"}, 0,
                                                   renewTools([mistral], ids))
            verify(result.settings.chatUserSites === undefined, JSON.stringify(ids))
            compare(result.applied, 1)
            compare(result.dropped, 1)
        })
        // Without the renewal tools nothing is renewed (older callers).
        var plain = plan({chatUserSites: sitesText([moved])})
        compare(plain.settings.chatUserSites, sitesText([moved]))
    }

    function test_planWithoutUserSiteToolsDropsThem() {
        var result = SettingsBackup.importPlan({chatUserSites: sitesText([mistral])}, 0, {
            providers: Catalog.providers, webSiteIds: ChatSites.siteIds(), ringPairs: [],
            validateCustomUrl: ChatSites.validateCustomUrl, ollamaAddress: OllamaChat.checkedAddress
        })
        compare(result.dropped, 1)
        compare(result.applied, 0)
    }

    function test_planCanonicalizes() {
        var result = plan({usageNormalColor: "#00AAFF",
                           tooltipMetrics: "{\"codex\":[],\"claude\":[\"weekly\"]}",
                           chatCustomUrls: "{\"local\":\"http://localhost:8080/\",\"claude\":\"https://c.example.org/\"}"})
        compare(result.settings.usageNormalColor, "#00aaff")
        compare(result.settings.tooltipMetrics, "{\"claude\":[\"weekly\"],\"codex\":[]}")
        compare(result.settings.chatCustomUrls, "{\"claude\":\"https://c.example.org/\",\"local\":\"http://localhost:8080/\"}")
    }

    function test_planNeverCarriesExcludedKeys() {
        var extra = {}
        SettingsBackup.EXCLUDED_KEYS.forEach(function (key) { extra[key] = true })
        extra.popupSize = "large"
        var result = plan(extra, 1)
        compare(result.settings, {popupSize: "large"})
        compare(result.applied, 1)
        compare(result.dropped, SettingsBackup.EXCLUDED_KEYS.length + 1, "counted, with the helper's")
    }

    function test_planDropsUnknownKeys() {
        var result = plan(JSON.parse("{\"__proto__\":{\"popupSize\":\"large\"},\"other\":1,\"popupSize\":\"compact\"}"))
        compare(result.settings, {popupSize: "compact"})
        compare(result.dropped, 2)
    }

    function dropped(key, value, what) {
        var settings = {}
        settings[key] = value
        var result = plan(settings)
        compare(result.settings, {}, key + " " + (what || String(value)))
        compare(result.dropped, 1, key)
    }

    function test_planRejectsBadValues() {
        dropped("trackedProviders", "[\"nobody\"]")
        dropped("trackedProviders", "[\"claude\",\"claude\"]", "twice")
        dropped("trackedProviders", "{}", "not a list")
        dropped("trackedProviders", "[", "not json")
        dropped("trackedProviders", 3)
        dropped("providerOrder", "[1]")
        dropped("providerMetrics", "{\"nobody\":[]}")
        dropped("providerMetrics", "{\"claude\":[\"spark\"]}")
        dropped("providerMetrics", "[]", "array")
        dropped("tooltipMetrics", "x")
        dropped("usageMode", "both")
        dropped("refreshInterval", 61)
        dropped("refreshInterval", "300")
        dropped("tooltipShowsUsage", "true")
        dropped("usageCompact", 1)
        dropped("usageWarnPercent", 95, "only critical has 95")
        dropped("usageCriticalPercent", 50, "only warning has 50")
        dropped("usageNormalColor", "red")
        dropped("usageNormalColor", "#12345")
        dropped("usageWarnColor", 3)
        dropped("alertLowPercent", 7)
        dropped("chatSites", "[\"nobody\"]")
        dropped("chatDefaultSite", "nobody")
        dropped("popupDefaultTab", "other")
        dropped("popupSize", "huge")
        dropped("shortcutOpens", "refresh")
        dropped("panelRing", "claude.extra_usage")
        dropped("panelRing", "claude.spark")
        dropped("panelRing", "")
        dropped("middleClickOpens", "chat")
        dropped("middleClickOpens", "")
    }

    function test_planControlCharacters() {
        // Valid JSON once parsed; the helper refuses these too.
        dropped("trackedProviders", "[\"claude\",\n\"codex\"]")
        dropped("providerMetrics", "{\"claude\":\t[]}")
    }

    function test_planOllamaLoopbackOnly() {
        verify(plan({chatOllamaUrl: "http://127.0.0.1:11434"}).settings.chatOllamaUrl !== undefined)
        verify(plan({chatOllamaUrl: "http://localhost:80"}).settings.chatOllamaUrl !== undefined)
        dropped("chatOllamaUrl", "http://192.168.1.2:11434")
        dropped("chatOllamaUrl", "http://0.0.0.0:11434")
        dropped("chatOllamaUrl", "http://attacker.example:11434")
        dropped("chatOllamaUrl", "https://127.0.0.1:11434")
        dropped("chatOllamaUrl", "http://127.0.0.1:11434/", "not the stored form")
        dropped("chatOllamaUrl", "http://localhost")
        dropped("chatOllamaUrl", "")
        dropped("chatOllamaUrl", 3)
    }

    function urls(map) {
        return JSON.stringify(map)
    }

    function test_planCustomUrlsFollowTheWidgetsRule() {
        verify(plan({chatCustomUrls: "{}"}).settings.chatCustomUrls === "{}")
        dropped("chatCustomUrls", urls({claude: "http://claude.example.org/"}), "http")
        dropped("chatCustomUrls", urls({claude: "https://user:pw@claude.example.org/"}), "credentials")
        dropped("chatCustomUrls", urls({claude: "https://claude.example.org/ x"}), "space")
        dropped("chatCustomUrls", urls({claude: "https://localhost/"}), "loopback on a web site")
        dropped("chatCustomUrls", urls({claude: "ftp://claude.example.org/"}), "scheme")
        dropped("chatCustomUrls", urls({claude: ""}), "empty entry")
        dropped("chatCustomUrls", urls({claude: 3}), "not text")
        dropped("chatCustomUrls", urls({nobody: "https://x.example.org/"}), "unknown site")
        dropped("chatCustomUrls", urls({ollama: "https://x.example.org/"}), "Ollama has none")
        dropped("chatCustomUrls", urls({claude: "https://" + new Array(2100).join("a") + ".org/"}), "too long")
        dropped("chatCustomUrls", "[]", "array")
        // One bad entry drops the whole setting.
        dropped("chatCustomUrls", urls({claude: "https://ok.example.org/", chatgpt: "http://bad.example.org/"}), "one bad")
    }

    function test_planDropsPairsThePagesNeverStore() {
        var both = plan({usageWarnPercent: 90, usageCriticalPercent: 55, popupSize: "large"})
        compare(both.settings, {popupSize: "large"})
        compare(both.applied, 1)
        compare(both.dropped, 2)
        var neither = plan({showUsageTab: false, showChatTab: false})
        compare(neither.settings, {})
        compare(neither.dropped, 2)
        compare(plan({showUsageTab: false, showChatTab: true}).applied, 2)
        compare(plan({usageWarnPercent: 90}).applied, 1, "alone it keeps its place")
    }

    function test_planOddInput() {
        compare(SettingsBackup.importPlan(null, 0, tools()), {settings: {}, applied: 0, dropped: 0})
        compare(SettingsBackup.importPlan([], -1, tools()), {settings: {}, applied: 0, dropped: 0})
    }

    // --- what Replace would change in the chat addresses ------------------

    function addressTools() {
        return {
            webSiteIds: ChatSites.siteIds(),
            parseCustomUrls: ChatSites.parseCustomUrls,
            effectiveUrl: ChatSites.homeUrl,
            shownText: UsageLogic.shownText,
            parseUserSites: ChatSites.parseUserSites,
            hostOf: function (url) { return ChatSites.shortHost(ChatSites.displayHost(url)) }
        }
    }

    function changes(current, settings) {
        return SettingsBackup.addressChanges(current, plan(settings), addressTools())
    }

    readonly property var applied: ({chatCustomUrls: urls({claude: "https://old.example.org/"}),
                                     chatOllamaUrl: "http://127.0.0.1:11434"})

    function test_addressChangesListEveryChangedSite() {
        var result = changes(applied, {
            chatCustomUrls: urls({chatgpt: "https://new.example.org/", local: "http://localhost:8080/"}),
            chatOllamaUrl: "http://[::1]:11434"
        })
        compare(result, [
            {id: "claude", from: "https://old.example.org/", to: ChatSites.homeUrl("claude", {})},
            {id: "chatgpt", from: ChatSites.homeUrl("chatgpt", {}), to: "https://new.example.org/"},
            {id: "local", from: ChatSites.homeUrl("local", {}), to: "http://localhost:8080/"},
            {id: "ollama", from: "http://127.0.0.1:11434", to: "http://[::1]:11434"}
        ])
    }

    function test_addressChangesLeaveOutWhatStaysTheSame() {
        compare(changes(applied, {chatCustomUrls: applied.chatCustomUrls, chatOllamaUrl: applied.chatOllamaUrl}), [])
        compare(changes(applied, {popupSize: "large"}), [], "no address in the backup")
        compare(changes(applied, {chatCustomUrls: urls({claude: "https://old.example.org/"}), popupSize: "large"}), [])
    }

    // A value the widget's check dropped is not applied, so not listed.
    function test_addressChangesOnlyFromThePlan() {
        compare(changes(applied, {chatOllamaUrl: "http://192.168.1.2:11434",
                                  chatCustomUrls: urls({claude: "http://plain.example.org/"})}), [])
    }

    function test_addressChangesAreCapped() {
        var long = "https://" + new Array(1500).join("a") + ".example.org/"
        var result = changes({chatCustomUrls: urls({claude: long}), chatOllamaUrl: ""},
                             {chatCustomUrls: "{}"})
        compare(result.length, 1)
        compare(result[0].from, UsageLogic.shownText(long))
        compare(result[0].from.length, UsageLogic.MAX_SHOWN_CHARS)
        verify(result[0].from.length < long.length, "capped")
    }

    function test_addressChangesOddInput() {
        compare(SettingsBackup.addressChanges(null, null, addressTools()), [])
        compare(SettingsBackup.addressChanges({}, {settings: []}, addressTools()), [])
        // The page's own value unreadable: the sites' built-in addresses.
        compare(changes({chatCustomUrls: "{", chatOllamaUrl: 3}, {chatCustomUrls: "{}"}), [])
        compare(changes({}, {chatOllamaUrl: "http://[::1]:11434"}),
                [{id: "ollama", from: "", to: "http://[::1]:11434"}])
    }

    // Added sites: adds with their host, address changes by id, then
    // removes (applying deletes their data); before Ollama.
    function test_addressChangesListAddedSites() {
        var moved = site(deepseek.id, "DeepSeek", "https://www.deepseek.com/chat")
        var fresh = site("user-0000beef", "Pi", "https://pi.ai/talk")
        var result = changes({chatCustomUrls: "{}", chatOllamaUrl: "http://127.0.0.1:11434",
                              chatUserSites: sitesText([mistral, deepseek])},
                             {chatUserSites: sitesText([moved, fresh]), chatOllamaUrl: "http://[::1]:11434"})
        compare(result, [
            {id: deepseek.id, name: "DeepSeek", from: "https://chat.deepseek.com/", to: "https://www.deepseek.com/chat"},
            {kind: "add", id: fresh.id, name: "Pi", host: "pi.ai", http: false},
            {kind: "remove", id: mistral.id, name: "Le Chat"},
            {id: "ollama", from: "http://127.0.0.1:11434", to: "http://[::1]:11434"}
        ])
        // The same list (any key order): nothing.
        compare(changes({chatUserSites: sitesText([mistral])},
                        {chatUserSites: "[{\"url\":\"https://chat.mistral.ai/chat\",\"id\":\"user-3fa9c01b\",\"name\":\"Le Chat\"}]"}), [])
        // A dropped list is not applied, so not listed.
        compare(changes({chatUserSites: sitesText([mistral])},
                        {chatUserSites: sitesText([Object.assign({icon: "x"}, deepseek)])}), [])
        // No list in the backup: the added sites stay.
        compare(changes({chatUserSites: sitesText([mistral])}, {popupSize: "large"}), [])
    }

    // Task 006: an added http site is flagged from its scheme (the text says
    // "not encrypted"); https ones, also on the home network, are not.
    function test_addressChangesFlagHttpAdds() {
        var nas = site("user-0000a001", "NAS", "http://192.168.1.20:3000/")
        var lan = site("user-0000a002", "LAN", "https://10.0.0.5/")
        var loop = site("user-0000a003", "Loop", "HTTP://localhost:3000/")
        var result = changes({chatUserSites: "[]"}, {chatUserSites: sitesText([nas, lan, loop])})
        compare(result, [
            {kind: "add", id: nas.id, name: "NAS", host: "192.168.1.20", http: true},
            {kind: "add", id: lan.id, name: "LAN", host: "10.0.0.5", http: false},
            {kind: "add", id: loop.id, name: "Loop", host: "localhost", http: true}
        ])
        // The helper's strict rule and this one agree: the list is kept.
        var plan = SettingsBackup.importPlan({chatUserSites: sitesText([nas, lan, loop])}, 0, renewTools([]))
        compare(plan.settings.chatUserSites, sitesText([nas, lan, loop]))
        // M1 for IPv6 hosts: another literal is another site, a port change isn't.
        var v6 = site("user-0000a004", "V6", "http://[fd00::20]:3000/")
        plan = SettingsBackup.importPlan({chatUserSites: sitesText([site(v6.id, "V6", "http://[fd00::21]:3000/")])},
                                         0, renewTools([v6]))
        compare(plan.settings.chatUserSites, sitesText([site("user-0000aaaa", "V6", "http://[fd00::21]:3000/")]))
        plan = SettingsBackup.importPlan({chatUserSites: sitesText([site(v6.id, "V6", "https://[fd00::20]:8443/")])},
                                         0, renewTools([v6]))
        compare(plan.settings.chatUserSites, sitesText([site(v6.id, "V6", "https://[fd00::20]:8443/")]))
    }

    function test_maxShownChanges() {
        compare(SettingsBackup.MAX_SHOWN_CHANGES, 8)
    }
}
