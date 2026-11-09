import QtQuick
import QtTest
import "../../plasmoid/contents/ui/SettingsLogic.js" as SettingsLogic

TestCase {
    name: "SettingsLogic"

    function test_defaultTab() {
        compare(SettingsLogic.normalizeDefaultTab("chat"), "chat")
        compare(SettingsLogic.normalizeDefaultTab("usage"), "usage")
        compare(SettingsLogic.normalizeDefaultTab(""), "chat")
        compare(SettingsLogic.normalizeDefaultTab("Usage"), "chat")
        compare(SettingsLogic.normalizeDefaultTab(undefined), "chat")
        compare(SettingsLogic.normalizeDefaultTab(1), "chat")
    }

    function test_popupSize() {
        compare(SettingsLogic.normalizePopupSize("compact"), "compact")
        compare(SettingsLogic.normalizePopupSize("normal"), "normal")
        compare(SettingsLogic.normalizePopupSize("large"), "large")
        compare(SettingsLogic.normalizePopupSize("huge"), "normal")
        compare(SettingsLogic.normalizePopupSize(""), "normal")
        compare(SettingsLogic.normalizePopupSize(undefined), "normal")
        compare(SettingsLogic.popupScale("compact"), 0.8)
        compare(SettingsLogic.popupScale("normal"), 1)
        compare(SettingsLogic.popupScale("large"), 1.25)
        compare(SettingsLogic.popupScale("constructor"), 1)
        compare(SettingsLogic.popupScale(null), 1)
    }

    function test_visibleTabs() {
        compare(SettingsLogic.visibleTabs(true, true, true), {usage: true, chat: true})
        compare(SettingsLogic.visibleTabs(true, false, true), {usage: true, chat: false})
        compare(SettingsLogic.visibleTabs(false, true, true), {usage: false, chat: true})
        // Chat needs an enabled site; the popup is never empty.
        compare(SettingsLogic.visibleTabs(false, true, false), {usage: true, chat: false})
        compare(SettingsLogic.visibleTabs(true, true, false), {usage: true, chat: false})
        // Both off (only by hand-editing the config): Usage, never Chat.
        compare(SettingsLogic.visibleTabs(false, false, true), {usage: true, chat: false})
        // Chat only when the setting is exactly true.
        compare(SettingsLogic.visibleTabs(true, "true", true), {usage: true, chat: false})
        compare(SettingsLogic.visibleTabs(true, undefined, true), {usage: true, chat: false})
        compare(SettingsLogic.visibleTabs(undefined, true, true), {usage: true, chat: true})
    }

    function test_shownTab() {
        var both = {usage: true, chat: true}
        var usageOnly = {usage: true, chat: false}
        var chatOnly = {usage: false, chat: true}
        compare(SettingsLogic.shownTab("chat", both), "chat")
        compare(SettingsLogic.shownTab("usage", both), "usage")
        compare(SettingsLogic.shownTab("odd", both), "chat")
        compare(SettingsLogic.shownTab("chat", usageOnly), "usage")
        compare(SettingsLogic.shownTab("usage", usageOnly), "usage")
        compare(SettingsLogic.shownTab("usage", chatOnly), "chat")
        compare(SettingsLogic.shownTab("chat", chatOnly), "chat")
        compare(SettingsLogic.shownTab("chat", undefined), "usage")
    }

    function test_canUntick() {
        verify(SettingsLogic.canUntick(true))
        verify(!SettingsLogic.canUntick(false))
        verify(!SettingsLogic.canUntick(undefined))
    }

    function test_shortcutTarget() {
        compare(SettingsLogic.SHORTCUT_TARGETS, ["popup", "chat", "ollama", "usage"])
        compare(SettingsLogic.normalizeShortcutTarget("popup"), "popup")
        compare(SettingsLogic.normalizeShortcutTarget("chat"), "chat")
        compare(SettingsLogic.normalizeShortcutTarget("ollama"), "ollama")
        compare(SettingsLogic.normalizeShortcutTarget("usage"), "usage")
        compare(SettingsLogic.normalizeShortcutTarget("Chat"), "popup")
        compare(SettingsLogic.normalizeShortcutTarget(""), "popup")
        compare(SettingsLogic.normalizeShortcutTarget(undefined), "popup")
        compare(SettingsLogic.normalizeShortcutTarget(2), "popup")
    }

    function test_shortcutPlan() {
        var both = {usage: true, chat: true}
        var usageOnly = {usage: true, chat: false}
        var chatOnly = {usage: false, chat: true}
        var keep = {tab: "", site: "", focusInput: false}
        compare(SettingsLogic.shortcutPlan("popup", both, true), keep)
        compare(SettingsLogic.shortcutPlan("odd", both, true), keep)
        compare(SettingsLogic.shortcutPlan("chat", both, true), {tab: "chat", site: "", focusInput: false})
        compare(SettingsLogic.shortcutPlan("usage", both, true), {tab: "usage", site: "", focusInput: false})
        compare(SettingsLogic.shortcutPlan("ollama", both, true), {tab: "chat", site: "ollama", focusInput: true})
        // Ollama off, or the Chat tab hidden: as when clicking the icon.
        compare(SettingsLogic.shortcutPlan("ollama", both, false), keep)
        compare(SettingsLogic.shortcutPlan("ollama", both, "true"), keep)
        compare(SettingsLogic.shortcutPlan("ollama", usageOnly, true), keep)
        // A hidden target tab falls back to the other one.
        compare(SettingsLogic.shortcutPlan("chat", usageOnly, true).tab, "usage")
        compare(SettingsLogic.shortcutPlan("usage", chatOnly, true).tab, "chat")
        compare(SettingsLogic.shortcutPlan("usage", undefined, true).tab, "usage")
        compare(SettingsLogic.shortcutPlan("chat", undefined, true).tab, "usage")
    }

    function test_zoomSteps() {
        compare(SettingsLogic.ZOOM_STEPS, [0.5, 0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0])
        compare(SettingsLogic.zoomStep(1.0, 1), 1.1)
        compare(SettingsLogic.zoomStep(1.0, -1), 0.9)
        compare(SettingsLogic.zoomStep(1.5, 0), 1.0)
        compare(SettingsLogic.zoomStep(2.0, 1), 2.0)
        compare(SettingsLogic.zoomStep(0.5, -1), 0.5)
        compare(SettingsLogic.zoomStep(0.67, 1), 0.75)
        compare(SettingsLogic.zoomStep(0.75, -1), 0.67)
        // Between steps: the neighbouring step.
        compare(SettingsLogic.zoomStep(1.2, 1), 1.25)
        compare(SettingsLogic.zoomStep(1.2, -1), 1.1)
        // Odd input.
        compare(SettingsLogic.zoomStep(NaN, 1), 1.1)
        compare(SettingsLogic.zoomStep("1.5", 1), 1.1)
        compare(SettingsLogic.zoomStep(1.5, 2), 1.0)
        compare(SettingsLogic.zoomStep(1.5, undefined), 1.0)
        compare(SettingsLogic.zoomStep(9, 1), 2.0)
        compare(SettingsLogic.zoomStep(9, -1), 2.0)
        compare(SettingsLogic.zoomStep(0.1, -1), 0.5)
    }

    function test_parseZoomMap() {
        var ids = ["claude", "chatgpt", "ollama"]
        compare(SettingsLogic.parseZoomMap("{}", ids), {})
        compare(SettingsLogic.parseZoomMap('{"claude":1.25,"ollama":0.8}', ids), {claude: 1.25, ollama: 0.8})
        // Unknown ids, 1.0, factors off the steps, strings and junk are dropped.
        compare(SettingsLogic.parseZoomMap('{"claude":1.0,"evil":1.5,"chatgpt":1.3}', ids), {})
        compare(SettingsLogic.parseZoomMap('{"claude":"1.25","chatgpt":null}', ids), {})
        compare(SettingsLogic.parseZoomMap("[1.5]", ids), {})
        compare(SettingsLogic.parseZoomMap("not json", ids), {})
        compare(SettingsLogic.parseZoomMap("", ids), {})
        compare(SettingsLogic.parseZoomMap(undefined, ids), {})
        compare(SettingsLogic.parseZoomMap('{"claude":1.5}', undefined), {})
    }

    function test_zoomFor() {
        var map = {claude: 1.5}
        compare(SettingsLogic.zoomFor(map, "claude"), 1.5)
        compare(SettingsLogic.zoomFor(map, "chatgpt"), 1.0)
        compare(SettingsLogic.zoomFor(map, "toString"), 1.0)
        compare(SettingsLogic.zoomFor({claude: 3}, "claude"), 1.0)
        compare(SettingsLogic.zoomFor(null, "claude"), 1.0)
        compare(SettingsLogic.zoomFor(map, undefined), 1.0)
    }

    function test_zoomMapToPersist() {
        compare(SettingsLogic.zoomMapToPersist({}, "claude", 1.25), '{"claude":1.25}')
        // Sorted keys: the same zoom always gives the same text.
        compare(SettingsLogic.zoomMapToPersist({ollama: 0.8}, "chatgpt", 1.5), '{"chatgpt":1.5,"ollama":0.8}')
        // 1.0 and odd factors are never stored.
        compare(SettingsLogic.zoomMapToPersist({claude: 1.25}, "claude", 1.0), "{}")
        compare(SettingsLogic.zoomMapToPersist({claude: 1.25}, "claude", 1.3), "{}")
        compare(SettingsLogic.zoomMapToPersist({claude: 1.25, grok: "2"}, "", 1.5), '{"claude":1.25}')
        compare(SettingsLogic.zoomMapToPersist(null, "claude", 2.0), '{"claude":2}')
        // Round trip.
        var ids = ["claude", "chatgpt", "ollama"]
        var text = SettingsLogic.zoomMapToPersist({claude: 0.67}, "ollama", 1.75)
        compare(SettingsLogic.parseZoomMap(text, ids), {claude: 0.67, ollama: 1.75})
    }

    function test_alertPercent() {
        compare(SettingsLogic.ALERT_PERCENTS, [5, 10, 15, 20, 25, 30, 40, 50])
        compare(SettingsLogic.normalizeAlertPercent(5), 5)
        compare(SettingsLogic.normalizeAlertPercent(50), 50)
        compare(SettingsLogic.normalizeAlertPercent(35), 20)
        compare(SettingsLogic.normalizeAlertPercent(0), 20)
        compare(SettingsLogic.normalizeAlertPercent("10"), 20)
        compare(SettingsLogic.normalizeAlertPercent(undefined), 20)
        compare(SettingsLogic.normalizeAlertPercent(NaN), 20)
    }

    // --- Middle-click -------------------------------------------------------

    readonly property var webIds: ["claude", "chatgpt", "local"]

    function test_normalizeMiddleClick() {
        compare(SettingsLogic.MIDDLE_CLICK_TARGETS, ["refresh", "usage", "ollama"])
        compare(SettingsLogic.normalizeMiddleClick("refresh", webIds), "refresh")
        compare(SettingsLogic.normalizeMiddleClick("usage", webIds), "usage")
        compare(SettingsLogic.normalizeMiddleClick("ollama", webIds), "ollama")
        compare(SettingsLogic.normalizeMiddleClick("claude", webIds), "claude")
        compare(SettingsLogic.normalizeMiddleClick("local", webIds), "local")
        compare(SettingsLogic.normalizeMiddleClick("chat", webIds), "refresh")
        compare(SettingsLogic.normalizeMiddleClick("Claude", webIds), "refresh")
        compare(SettingsLogic.normalizeMiddleClick("", webIds), "refresh")
        compare(SettingsLogic.normalizeMiddleClick(undefined, webIds), "refresh")
        compare(SettingsLogic.normalizeMiddleClick(3, webIds), "refresh")
        compare(SettingsLogic.normalizeMiddleClick("claude", null), "refresh")
    }

    function clickState(extra) {
        return Object.assign({expanded: false, tabs: {usage: true, chat: true},
                              siteIds: ["claude", "ollama"], shownTab: "usage", siteId: "claude"}, extra)
    }

    function test_middleClickRefreshIgnoresThePopup() {
        var refresh = {action: "refresh", tab: "", site: "", focusInput: false}
        compare(SettingsLogic.middleClickPlan("refresh", clickState({})), refresh)
        compare(SettingsLogic.middleClickPlan("refresh", clickState({expanded: true})), refresh)
    }

    function test_middleClickOpens() {
        compare(SettingsLogic.middleClickPlan("usage", clickState({})),
                {action: "open", tab: "usage", site: "", focusInput: false})
        compare(SettingsLogic.middleClickPlan("claude", clickState({})),
                {action: "open", tab: "chat", site: "claude", focusInput: false})
        compare(SettingsLogic.middleClickPlan("ollama", clickState({})),
                {action: "open", tab: "chat", site: "ollama", focusInput: true})
    }

    function test_middleClickClosesOnlyWhatItShows() {
        var close = {action: "close", tab: "", site: "", focusInput: false}
        compare(SettingsLogic.middleClickPlan("usage", clickState({expanded: true})), close)
        compare(SettingsLogic.middleClickPlan("claude", clickState({expanded: true, shownTab: "chat"})), close)
        // Open on something else: it switches.
        compare(SettingsLogic.middleClickPlan("usage", clickState({expanded: true, shownTab: "chat"})).action, "open")
        compare(SettingsLogic.middleClickPlan("claude", clickState({expanded: true})).action, "open")
        var other = SettingsLogic.middleClickPlan("ollama", clickState({expanded: true, shownTab: "chat", siteId: "claude"}))
        compare(other, {action: "open", tab: "chat", site: "ollama", focusInput: true})
    }

    function test_middleClickHiddenTargetIsANormalClick() {
        var toggle = {action: "toggle", tab: "", site: "", focusInput: false}
        compare(SettingsLogic.middleClickPlan("usage", clickState({tabs: {usage: false, chat: true}})), toggle)
        compare(SettingsLogic.middleClickPlan("claude", clickState({tabs: {usage: true, chat: false}})), toggle)
        compare(SettingsLogic.middleClickPlan("chatgpt", clickState({})), toggle)
        compare(SettingsLogic.middleClickPlan("ollama", clickState({siteIds: ["claude"]})), toggle)
        compare(SettingsLogic.middleClickPlan("usage", undefined), toggle)
        compare(SettingsLogic.middleClickPlan("claude", {tabs: {chat: true}, siteIds: "claude"}), toggle)
    }
}
