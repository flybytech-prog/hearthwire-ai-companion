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
        chatSites: "[\"claude\",\"ollama\",\"local\"]",
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
        chatCustomUrls: "{\"claude\":\"https://claude.example.org/new?x=1\",\"local\":\"http://localhost:8080/\"}"
    })

    function tools() {
        return {
            providers: Catalog.providers,
            webSiteIds: ChatSites.siteIds(),
            ringPairs: UsageLogic.ringOptions(Catalog.providers).map(function (option) { return option.value }),
            validateCustomUrl: ChatSites.validateCustomUrl,
            ollamaAddress: OllamaChat.checkedAddress
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
        compare(SettingsBackup.BACKUP_KEYS.length, 28)
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
        compare(SettingsBackup.parseReply("status", 0, "{\"ok\":true,\"exists\":false}" + new Array(70000).join(" ")), bad, "oversized")
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
        compare(result.applied, 28)
        compare(result.dropped, 0)
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
            shownText: UsageLogic.shownText
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

    function test_maxShownChanges() {
        compare(SettingsBackup.MAX_SHOWN_CHANGES, 8)
    }
}
