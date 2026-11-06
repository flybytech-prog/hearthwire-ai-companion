import QtQuick
import QtTest
import "../../plasmoid/contents/ui/ProviderCatalog.js" as Catalog
import "../../plasmoid/contents/ui/UsageLogic.js" as UsageLogic

TestCase {
    name: "UsageLogic"

    readonly property double minute: 60000
    readonly property double hour: 3600000

    // W1: provider text is cut to MAX_SHOWN_CHARS with an ellipsis.
    function test_shownText() {
        compare(UsageLogic.MAX_SHOWN_CHARS, 200)
        compare(UsageLogic.shownText("Pro"), "Pro")
        compare(UsageLogic.shownText(""), "")
        compare(UsageLogic.shownText(12.5), "12.5")
        compare(UsageLogic.shownText(NaN), "")
        compare(UsageLogic.shownText(Infinity), "")
        compare(UsageLogic.shownText(null), "")
        compare(UsageLogic.shownText(undefined), "")
        compare(UsageLogic.shownText({ toString: function () { return "x" } }), "")
        compare(UsageLogic.shownText(["a"]), "")
        compare(UsageLogic.shownText(true), "")
        var exact = "a".repeat(200)
        compare(UsageLogic.shownText(exact), exact)
        var long = UsageLogic.shownText("b".repeat(201))
        compare(long.length, 200)
        compare(long, "b".repeat(199) + "\u2026")
        compare(UsageLogic.shownText("c".repeat(100000)).length, 200)
        // Never half a surrogate pair: an emoji at the cut goes whole.
        var emoji = UsageLogic.shownText("d".repeat(197) + "\ud83d\ude00" + "e".repeat(10))
        compare(emoji, "d".repeat(197) + "\ud83d\ude00" + "\u2026")
        var split = UsageLogic.shownText("d".repeat(198) + "\ud83d\ude00" + "e".repeat(10))
        compare(split, "d".repeat(198) + "\u2026")
        compare(split.length, 199)
    }

    function test_emptyOrOddOrderIsCatalogOrder() {
        var ids = Catalog.providerIds()
        compare(UsageLogic.normalizeOrder("", ids), ids)
        compare(UsageLogic.normalizeOrder(undefined, ids), ids)
        compare(UsageLogic.normalizeOrder("{", ids), ids)
        compare(UsageLogic.normalizeOrder("{\"claude\":1}", ids), ids)
        compare(UsageLogic.normalizeOrder("\"grok\"", ids), ids)
    }

    function test_orderDropsUnknownAndAppendsMissing() {
        var order = UsageLogic.normalizeOrder(
            "[\"grok\",\"nope\",5,\"codex\",\"grok\",null]", ["claude", "codex", "cursor", "grok"])
        compare(order, ["grok", "codex", "claude", "cursor"])
    }

    function test_moveIdSwapsNeighboursAndStopsAtTheEnds() {
        var order = ["claude", "codex", "grok"]
        compare(UsageLogic.moveId(order, "codex", -1), ["codex", "claude", "grok"])
        compare(UsageLogic.moveId(order, "codex", 1), ["claude", "grok", "codex"])
        compare(UsageLogic.moveId(order, "claude", -1), order)
        compare(UsageLogic.moveId(order, "grok", 1), order)
        compare(UsageLogic.moveId(order, "nope", 1), order)
        compare(order, ["claude", "codex", "grok"])
    }

    function test_moveSkipsIneligibleIds() {
        var order = ["claude", "codex", "cursor", "grok"]
        var tracked = ["claude", "cursor", "grok"]
        compare(UsageLogic.moveId(order, "claude", 1, tracked), ["cursor", "codex", "claude", "grok"])
        compare(UsageLogic.moveId(order, "cursor", -1, tracked), ["cursor", "codex", "claude", "grok"])
        compare(UsageLogic.moveId(order, "codex", 1, tracked), order)
        verify(!UsageLogic.canMove(order, "codex", 1, tracked))
        verify(!UsageLogic.canMove(order, "codex", -1, tracked))
        verify(!UsageLogic.canMove(order, "claude", -1, tracked))
        verify(UsageLogic.canMove(order, "claude", 1, tracked))
        verify(!UsageLogic.canMove(order, "grok", 1, tracked))
        verify(!UsageLogic.canMove(order, "claude", 1, ["claude"]))
        verify(UsageLogic.canMove(order, "codex", 1, undefined))
        compare(UsageLogic.moveTarget(order, "grok", -1, tracked), 2)
        compare(UsageLogic.moveTarget(order, "nope", -1, tracked), -1)
    }

    function apply(ids, moves) {
        var result = ids.slice()
        for (var index = 0; index < moves.length; index++)
            result.splice(moves[index].to, 0, result.splice(moves[index].from, 1)[0])
        return result
    }

    function test_syncMovesKeepsTheRows() {
        var current = ["claude", "codex", "cursor", "grok"]
        compare(UsageLogic.syncMoves(current, current), [])
        compare(UsageLogic.syncMoves(current, ["codex", "claude", "cursor", "grok"]), [{from: 1, to: 0}])
        var wanted = ["grok", "cursor", "claude", "codex"]
        compare(apply(current, UsageLogic.syncMoves(current, wanted)), wanted)
        wanted = ["cursor", "codex", "claude", "grok"]
        compare(apply(current, UsageLogic.syncMoves(current, wanted)), wanted)
        compare(UsageLogic.syncMoves(current, ["claude", "codex", "cursor"]), null)
        compare(UsageLogic.syncMoves(current, ["claude", "codex", "cursor", "devin"]), null)
        compare(UsageLogic.syncMoves(["claude", "claude"], ["claude", "claude"]), null)
        compare(UsageLogic.syncMoves([], []), [])
    }

    function test_orderProvidersSortsAndKeepsUnlistedLast() {
        var items = [
            {provider_id: "claude"}, null, {provider_id: "odd"}, {provider_id: "codex"}, {provider_id: "grok"}
        ]
        var sorted = UsageLogic.orderProviders(items, ["grok", "codex", "claude"])
        compare(sorted.map(function (item) { return item.provider_id }), ["grok", "codex", "claude", "odd"])
        compare(items[0].provider_id, "claude")
        compare(UsageLogic.orderProviders(undefined, ["grok"]), [])
    }

    function test_toArrayTakesArrayLikes() {
        compare(UsageLogic.toArray([1, 2]), [1, 2])
        compare(UsageLogic.toArray({length: 2, 0: "a", 1: "b"}), ["a", "b"])
        compare(UsageLogic.toArray("ab"), [])
        compare(UsageLogic.toArray(null), [])
        compare(UsageLogic.toArray({length: -1}), [])
        compare(UsageLogic.shownWindows({length: 1, 0: {kind: "weekly"}}, {length: 1, 0: "weekly"}), [{kind: "weekly"}])
    }

    function test_emptyChoiceShowsEveryWindow() {
        var windows = [{kind: "session"}, {kind: "weekly"}, null, "x"]
        compare(UsageLogic.shownWindows(windows, []).length, 2)
        compare(UsageLogic.shownWindows(windows, undefined).length, 2)
        compare(UsageLogic.shownWindows(windows, "weekly").length, 2)
        compare(UsageLogic.shownWindows(windows, ["weekly"]), [{kind: "weekly"}])
        compare(UsageLogic.shownWindows(undefined, ["weekly"]), [])
    }

    function test_billingFollowsItsMetric() {
        var spend = {kind: "bounded_spend"}
        var credits = {kind: "flex_credit_balance"}
        compare(UsageLogic.billingMetric(spend), "extra_usage")
        compare(UsageLogic.billingMetric({kind: "unbounded_spend"}), "extra_usage")
        compare(UsageLogic.billingMetric(credits), "credits")
        compare(UsageLogic.billingMetric({kind: "odd"}), "")
        compare(UsageLogic.billingMetric(null), "")
        verify(UsageLogic.showsBilling(spend, []))
        verify(UsageLogic.showsBilling(spend, ["extra_usage"]))
        verify(!UsageLogic.showsBilling(spend, ["weekly"]))
        verify(UsageLogic.showsBilling(credits, ["credits"]))
        verify(!UsageLogic.showsBilling(null, []))
        verify(!UsageLogic.showsBilling({kind: "odd"}, ["weekly"]))
    }

    function test_toggleMetricFromShowAll() {
        var ids = ["session", "weekly", "sonnet"]
        verify(UsageLogic.isShown([], "sonnet"))
        compare(UsageLogic.toggleMetric([], ids, "sonnet", false), ["session", "weekly"])
        compare(UsageLogic.toggleMetric([], ids, "sonnet", true), [])
        compare(UsageLogic.toggleMetric(["weekly"], ids, "session", true), ["session", "weekly"])
        // Ticking the last one shows all again.
        compare(UsageLogic.toggleMetric(["session", "weekly"], ids, "sonnet", true), [])
        verify(!UsageLogic.isShown(["weekly"], "session"))
    }

    // N3: an id the catalog no longer has doesn't count as a shown reading.
    function test_staleMetricIds() {
        var ids = ["session", "weekly"]
        compare(UsageLogic.effectiveChoice(["gone", "weekly", "session"], ids), ["session", "weekly"])
        compare(UsageLogic.effectiveChoice("weekly", ids), [])
        verify(UsageLogic.isLastShown(["weekly", "gone"], ids, "weekly"))
        verify(!UsageLogic.isLastShown(["weekly", "gone"], ids, "session"))
        verify(!UsageLogic.isLastShown(["gone"], ids, "weekly"))
        verify(UsageLogic.isLastShown([], ["weekly"], "weekly"))
        verify(!UsageLogic.isLastShown([], ids, "weekly"))
        compare(UsageLogic.toggleMetric(["weekly", "gone"], ids, "weekly", false), ["weekly"])
        compare(UsageLogic.toggleMetric(["weekly", "gone"], ids, "session", true), [])
        compare(UsageLogic.toggleMetric(["gone"], ids, "session", false), ["weekly"])
    }

    function test_lastReadingStaysTicked() {
        var ids = ["session", "weekly"]
        compare(UsageLogic.toggleMetric(["weekly"], ids, "weekly", false), ["weekly"])
        compare(UsageLogic.toggleMetric(["weekly"], ["weekly"], "weekly", false), ["weekly"])
        compare(UsageLogic.toggleMetric([], ["weekly"], "weekly", false), [])
    }

    function test_toggleMetricIgnoresUnknownIds() {
        var ids = ["session", "weekly"]
        compare(UsageLogic.toggleMetric(["weekly"], ids, "daily", true), ["weekly"])
        compare(UsageLogic.toggleMetric([], ids, "daily", false), [])
        compare(UsageLogic.toggleMetric(["weekly", "nope"], ids, "session", true), [])
    }

    function test_thresholdsSnapAndStayApart() {
        compare(UsageLogic.normalizeThresholds(60, 85), {warn: 60, critical: 85})
        compare(UsageLogic.normalizeThresholds(undefined, null), {warn: 60, critical: 85})
        compare(UsageLogic.normalizeThresholds("x", ""), {warn: 60, critical: 85})
        compare(UsageLogic.normalizeThresholds(12, 300), {warn: 50, critical: 95})
        compare(UsageLogic.normalizeThresholds(63, 71), {warn: 65, critical: 70})
        compare(UsageLogic.normalizeThresholds(80, 80), {warn: 80, critical: 85})
        compare(UsageLogic.normalizeThresholds(90, 60), {warn: 90, critical: 95})
        compare(UsageLogic.normalizeThresholds(95, 95), {warn: 90, critical: 95})
        compare(UsageLogic.normalizeThresholds(95, 50), {warn: 90, critical: 95})
    }

    function test_colourChoicesKeepEveryPick() {
        compare(UsageLogic.WARN_PERCENTS, [50, 55, 60, 65, 70, 75, 80, 85, 90])
        compare(UsageLogic.CRITICAL_PERCENTS, [55, 60, 65, 70, 75, 80, 85, 90, 95])
        // Any warn pick with a lower critical: the critical level moves up.
        for (var w = 0; w < UsageLogic.WARN_PERCENTS.length; w++) {
            var warn = UsageLogic.WARN_PERCENTS[w]
            compare(UsageLogic.normalizeThresholds(warn, 55).warn, warn)
        }
        // Any critical pick with a higher warn: the page moves warn below it.
        for (var c = 0; c < UsageLogic.CRITICAL_PERCENTS.length; c++) {
            var critical = UsageLogic.CRITICAL_PERCENTS[c]
            compare(UsageLogic.normalizeThresholds(Math.min(90, critical - 5), critical).critical, critical)
        }
    }

    function test_migrationMovesTheOldChoiceToTheHoverPopup() {
        var old = "{\"claude\":[\"weekly\"],\"codex\":[\"weekly\"]}"
        var result = UsageLogic.migratedUsageMetrics(old, "", Catalog.providers)
        compare(result.providerMetrics, "{}")
        compare(JSON.parse(result.tooltipMetrics), {claude: ["weekly"], codex: ["weekly"]})
        result = UsageLogic.migratedUsageMetrics(
            "{\"claude\":[\"weekly\",\"daily\",\"session\"],\"grok\":[],\"nope\":[\"weekly\"],"
            + "\"codex\":\"weekly\",\"devin\":[\"gone\"]}", "", Catalog.providers)
        compare(JSON.parse(result.tooltipMetrics), {claude: ["session", "weekly"]})
    }

    function test_migrationOfEmptyOrOddValues() {
        var values = ["", "{}", "{\"claude\":[]}", "garbage", "[\"claude\"]", "null", "7", undefined]
        for (var index = 0; index < values.length; index++) {
            compare(UsageLogic.migratedUsageMetrics(values[index], "", Catalog.providers),
                    {providerMetrics: "{}", tooltipMetrics: ""}, String(values[index]))
        }
        compare(UsageLogic.migratedUsageMetrics("{\"claude\":[\"weekly\"]}", undefined, Catalog.providers),
                {providerMetrics: "{}", tooltipMetrics: "{\"claude\":[\"weekly\"]}"})
    }

    function test_migrationKeepsAnOwnHoverPopupChoice() {
        var own = "{\"claude\":[\"session\"]}"
        compare(UsageLogic.migratedUsageMetrics("{\"claude\":[\"weekly\"]}", own, Catalog.providers),
                {providerMetrics: "{}", tooltipMetrics: own})
        compare(UsageLogic.migratedUsageMetrics("{}", own, Catalog.providers),
                {providerMetrics: "{}", tooltipMetrics: own})
    }

    function test_usageLevel() {
        var limits = {warn: 70, critical: 90}
        compare(UsageLogic.usageLevel(69.9, limits), "normal")
        compare(UsageLogic.usageLevel(70, limits), "warning")
        compare(UsageLogic.usageLevel(90, limits), "critical")
        compare(UsageLogic.usageLevel(60, undefined), "warning")
        compare(UsageLogic.usageLevel(85, null), "critical")
        compare(UsageLogic.usageLevel(NaN, limits), "normal")
        compare(UsageLogic.usageLevel(80, {warn: 95, critical: 95}), "normal")
    }

    function test_updatedPhrase() {
        var now = 100 * hour
        compare(UsageLogic.updatedPhrase(0, now), null)
        compare(UsageLogic.updatedPhrase(NaN, now), null)
        compare(UsageLogic.updatedPhrase(now, NaN), null)
        compare(UsageLogic.updatedPhrase(now - 59000, now), {kind: "now"})
        compare(UsageLogic.updatedPhrase(now + minute, now), {kind: "now"})
        compare(UsageLogic.updatedPhrase(now - 5 * minute, now), {kind: "minutes", minutes: 5})
        compare(UsageLogic.updatedPhrase(now - 125 * minute, now), {kind: "hours", hours: 2})
        compare(UsageLogic.updatedPhrase(now - 50 * hour, now), {kind: "days", days: 2})
    }

    function test_shortCountdown() {
        var now = 10 * hour
        compare(UsageLogic.shortCountdown(null, now), null)
        compare(UsageLogic.shortCountdown("", now), null)
        compare(UsageLogic.shortCountdown(now, NaN), null)
        compare(UsageLogic.shortCountdown(now - minute, now), {days: 0, hours: 0, minutes: 0})
        compare(UsageLogic.shortCountdown(now + 10000, now), {days: 0, hours: 0, minutes: 1})
        compare(UsageLogic.shortCountdown(now + 125 * minute, now), {days: 0, hours: 2, minutes: 5})
        compare(UsageLogic.shortCountdown(now + 26 * hour, now), {days: 1, hours: 2, minutes: 0})
    }

    // U1: the soonest reset still ahead; the first of equals; the entry itself.
    function test_nextReset() {
        var now = 10 * hour
        var soon = {resetsAtMs: now + 2 * hour, name: "soon"}
        var twin = {resetsAtMs: now + 2 * hour, name: "twin"}
        var later = {resetsAtMs: now + 5 * hour, name: "later"}
        var past = {resetsAtMs: now - minute, name: "past"}
        var exact = {resetsAtMs: now, name: "exact"}
        compare(UsageLogic.nextReset([later, past, soon, twin, exact], now), soon)
        verify(UsageLogic.nextReset([later, soon], now) === soon)
        compare(UsageLogic.nextReset([past, exact], now), null)
        compare(UsageLogic.nextReset([], now), null)
        compare(UsageLogic.nextReset(undefined, now), null)
        compare(UsageLogic.nextReset("x", now), null)
        // Unusable entries are skipped.
        compare(UsageLogic.nextReset([null, 5, {}, {resetsAtMs: "99999999999"}, {resetsAtMs: NaN},
                                      {resetsAtMs: Infinity}, later], now), later)
        // An unusable clock gives nothing.
        compare(UsageLogic.nextReset([later], NaN), null)
        compare(UsageLogic.nextReset([later], null), null)
        compare(UsageLogic.nextReset([later], ""), null)
        compare(UsageLogic.nextReset([later], undefined), null)
        // Array-likes (a Repeater's modelData) work too.
        compare(UsageLogic.nextReset({length: 2, 0: later, 1: soon}, now), soon)
    }

    function test_normalizeColour() {
        compare(UsageLogic.normalizeColour("#A1b2C3"), "#a1b2c3")
        compare(UsageLogic.normalizeColour(""), "")
        compare(UsageLogic.normalizeColour("red"), "")
        compare(UsageLogic.normalizeColour("#abc"), "")
        compare(UsageLogic.normalizeColour("#a1b2c3ff"), "")
        compare(UsageLogic.normalizeColour("#a1b2c3; x"), "")
        compare(UsageLogic.normalizeColour(" #a1b2c3"), "")
        compare(UsageLogic.normalizeColour(undefined), "")
        compare(UsageLogic.normalizeColour(0xa1b2c3), "")
    }

    function test_shownPercent() {
        compare(UsageLogic.shownPercent(60, "used"), 60)
        compare(UsageLogic.shownPercent(60, "remaining"), 40)
        compare(UsageLogic.shownPercent(85, "anything"), 15)
        compare(UsageLogic.shownPercent("x", "used"), 0)
    }

    function test_defaultNormalColour() {
        compare(UsageLogic.defaultNormalColour(0.1, 0.1, 0.1), "#32c7d3")
        compare(UsageLogic.defaultNormalColour(0.95, 0.95, 0.95), "#008c95")
    }
}
