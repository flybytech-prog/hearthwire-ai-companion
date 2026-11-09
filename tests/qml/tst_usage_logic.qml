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

    function test_colorChoicesKeepEveryPick() {
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

    function test_normalizeColor() {
        compare(UsageLogic.normalizeColor("#A1b2C3"), "#a1b2c3")
        compare(UsageLogic.normalizeColor(""), "")
        compare(UsageLogic.normalizeColor("red"), "")
        compare(UsageLogic.normalizeColor("#abc"), "")
        compare(UsageLogic.normalizeColor("#a1b2c3ff"), "")
        compare(UsageLogic.normalizeColor("#a1b2c3; x"), "")
        compare(UsageLogic.normalizeColor(" #a1b2c3"), "")
        compare(UsageLogic.normalizeColor(undefined), "")
        compare(UsageLogic.normalizeColor(0xa1b2c3), "")
    }

    function test_effectiveCriticalColor() {
        compare(UsageLogic.effectiveCriticalColor("#0000AA", "#aa0000"), "#0000aa")
        compare(UsageLogic.effectiveCriticalColor("", "#AA0000"), "#aa0000")
        compare(UsageLogic.effectiveCriticalColor("#0000aa", ""), "#0000aa")
        compare(UsageLogic.effectiveCriticalColor("", ""), "")
        // Unreadable values count as empty.
        compare(UsageLogic.effectiveCriticalColor("red", "#aa0000"), "#aa0000")
        compare(UsageLogic.effectiveCriticalColor("", "nope"), "")
        compare(UsageLogic.effectiveCriticalColor(undefined, undefined), "")
        compare(UsageLogic.effectiveCriticalColor(null, 0xaa0000), "")
    }

    function test_fillWidth() {
        // The share of the track, once past the minimum.
        compare(UsageLogic.fillWidth(200, 50, 12), 100)
        compare(UsageLogic.fillWidth(200, 100, 12), 200)
        compare(UsageLogic.fillWidth(200, 6, 12), 12)
        // Tiny readings still show; the 3% left that was easy to miss.
        compare(UsageLogic.fillWidth(200, 3, 12), 12)
        compare(UsageLogic.fillWidth(200, 0.1, 12), 12)
        // Exactly 0% and nonsense stay empty.
        compare(UsageLogic.fillWidth(200, 0, 12), 0)
        compare(UsageLogic.fillWidth(200, -5, 12), 0)
        compare(UsageLogic.fillWidth(200, NaN, 12), 0)
        compare(UsageLogic.fillWidth(200, Infinity, 12), 0)
        compare(UsageLogic.fillWidth(200, undefined, 12), 0)
        compare(UsageLogic.fillWidth(200, "x", 12), 0)
        // Never past the track, even above 100% or with a tiny track.
        compare(UsageLogic.fillWidth(200, 150, 12), 200)
        compare(UsageLogic.fillWidth(8, 3, 12), 8)
        compare(UsageLogic.fillWidth(8, 100, 12), 8)
        compare(UsageLogic.fillWidth(0, 50, 12), 0)
        compare(UsageLogic.fillWidth(-10, 50, 12), 0)
        compare(UsageLogic.fillWidth(NaN, 50, 12), 0)
        compare(UsageLogic.fillWidth(undefined, 50, 12), 0)
        // A missing or odd minimum falls back to the plain share.
        compare(UsageLogic.fillWidth(200, 3, undefined), 6)
        compare(UsageLogic.fillWidth(200, 3, NaN), 6)
        compare(UsageLogic.fillWidth(200, 3, -4), 6)
    }

    function test_shownPercent() {
        compare(UsageLogic.shownPercent(60, "used"), 60)
        compare(UsageLogic.shownPercent(60, "remaining"), 40)
        compare(UsageLogic.shownPercent(85, "anything"), 15)
        compare(UsageLogic.shownPercent("x", "used"), 0)
    }

    function test_defaultNormalColor() {
        compare(UsageLogic.defaultNormalColor(0.1, 0.1, 0.1), "#32c7d3")
        compare(UsageLogic.defaultNormalColor(0.95, 0.95, 0.95), "#008c95")
    }

    // --- Usage ring ---------------------------------------------------------

    function test_ringOptionsSkipMoney() {
        var options = UsageLogic.ringOptions(Catalog.providers)
        var values = options.map(function (option) { return option.value })
        verify(values.indexOf("claude.session") >= 0)
        verify(values.indexOf("codex.credits") >= 0)
        verify(values.indexOf("claude.extra_usage") < 0)
        compare(options[0], {value: "claude.session", provider: "Claude Code", metric: "Session"})
        compare(UsageLogic.ringOptions(null), [])
        compare(UsageLogic.ringOptions([null, {provider_id: 3}, {provider_id: "x", metrics: [{id: 1}, null]}]), [])
    }

    function test_parsePanelRing() {
        var auto = {mode: "auto", value: "auto", provider_id: "", metric_id: ""}
        compare(UsageLogic.parsePanelRing("off", Catalog.providers).mode, "off")
        compare(UsageLogic.parsePanelRing("auto", Catalog.providers), auto)
        compare(UsageLogic.parsePanelRing("grok.weekly", Catalog.providers),
                {mode: "pair", value: "grok.weekly", provider_id: "grok", metric_id: "weekly"})
        compare(UsageLogic.parsePanelRing("", Catalog.providers), auto)
        compare(UsageLogic.parsePanelRing("Auto", Catalog.providers), auto)
        compare(UsageLogic.parsePanelRing("claude", Catalog.providers), auto)
        compare(UsageLogic.parsePanelRing("claude.spark", Catalog.providers), auto)
        compare(UsageLogic.parsePanelRing("claude.extra_usage", Catalog.providers), auto)
        compare(UsageLogic.parsePanelRing("claude.session.x", Catalog.providers), auto)
        compare(UsageLogic.parsePanelRing("nobody.weekly", Catalog.providers), auto)
        compare(UsageLogic.parsePanelRing(undefined, Catalog.providers), auto)
        compare(UsageLogic.parsePanelRing(null, Catalog.providers), auto)
        compare(UsageLogic.parsePanelRing(7, Catalog.providers), auto)
    }

    // The fake metricReading: the metric id comes back, so a test sees which one.
    function readingOf(provider, metricId) {
        return provider.readings && provider.readings[metricId] !== undefined
            ? provider.readings[metricId] : null
    }

    function group(id, status, metrics, readings) {
        return {provider_id: id, metrics: metrics,
                provider: {provider_id: id, status: status, readings: readings}}
    }

    function test_ringReadingAutoIsFirstReadingOfFirstUsableGroup() {
        var a = {type: "percentage", raw_used: 10}
        var b = {type: "percentage", raw_used: 20}
        var auto = {mode: "auto"}
        var groups = [group("broken", "error", ["s"], {s: a}),
                      group("good", "ok", ["w", "s"], {w: b, s: a}),
                      group("later", "ok", ["s"], {s: a})]
        compare(UsageLogic.ringReading(auto, groups, [], readingOf), {reading: b, stale: false})
        var stale = [group("old", "stale", ["s"], {s: a}), group("good", "ok", ["s"], {s: b})]
        compare(UsageLogic.ringReading(auto, stale, [], readingOf), {reading: a, stale: true})
        // Only the first reading counts: a missing one is no ring, not another.
        compare(UsageLogic.ringReading(auto, [group("good", "ok", ["gone", "s"], {s: a})], [], readingOf), null)
        compare(UsageLogic.ringReading(auto, [group("good", "ok", [], {s: a})], [], readingOf), null)
        compare(UsageLogic.ringReading(auto, [null, {}, group("bad", "error", ["s"], {s: a})], [], readingOf), null)
        compare(UsageLogic.ringReading(auto, null, null, readingOf), null)
    }

    function test_ringReadingPairAndOff() {
        var a = {type: "percentage", raw_used: 10}
        var pair = {mode: "pair", provider_id: "good", metric_id: "w"}
        var okList = [{provider_id: "other", status: "ok", readings: {w: {type: "percentage", raw_used: 99}}},
                      {provider_id: "good", status: "ok", readings: {w: a}}]
        compare(UsageLogic.ringReading(pair, [], okList, readingOf), {reading: a, stale: false})
        compare(UsageLogic.ringReading(pair, [], [{provider_id: "good", status: "stale", readings: {w: a}}], readingOf),
                {reading: a, stale: true})
        compare(UsageLogic.ringReading(pair, [], [{provider_id: "good", status: "error", readings: {w: a}}], readingOf), null)
        compare(UsageLogic.ringReading(pair, [], [], readingOf), null)
        compare(UsageLogic.ringReading({mode: "off"}, [group("good", "ok", ["w"], {w: a})], okList, readingOf), null)
        compare(UsageLogic.ringReading(null, [], [], readingOf), null)
        compare(UsageLogic.ringReading({mode: "auto"}, [], [], undefined), null)
    }

    function test_ringFractionLeftDrainsUsedFills() {
        compare(UsageLogic.ringFraction({type: "percentage", raw_used: 30}, "remaining"), 0.7)
        compare(UsageLogic.ringFraction({type: "percentage", raw_used: 30}, "used"), 0.3)
        compare(UsageLogic.ringFraction({type: "percentage", raw_used: 0}, "remaining"), 1)
        compare(UsageLogic.ringFraction({type: "percentage", raw_used: 100}, "remaining"), 0)
        compare(UsageLogic.ringFraction({type: "percentage", raw_used: 100}, "used"), 1)
        // Helper numbers outside the range stay on the ring.
        compare(UsageLogic.ringFraction({type: "percentage", raw_used: 140}, "used"), 1)
        compare(UsageLogic.ringFraction({type: "percentage", raw_used: -20}, "remaining"), 1)
    }

    function test_ringFractionNeedsAPercentage() {
        compare(UsageLogic.ringFraction({type: "money", value: 3}, "used"), null)
        compare(UsageLogic.ringFraction({type: "money", value: 3, raw_used: 40}, "used"), null)
        compare(UsageLogic.ringFraction({type: "credits", value: 3}, "remaining"), null)
        compare(UsageLogic.ringFraction({type: "percentage", raw_used: NaN}, "used"), null)
        compare(UsageLogic.ringFraction({type: "percentage"}, "used"), null)
        compare(UsageLogic.ringFraction({type: "percentage", raw_used: null}, "used"), null)
        compare(UsageLogic.ringFraction(null, "used"), null)
        compare(UsageLogic.ringFraction("x", "used"), null)
    }

    // --- Color preview ------------------------------------------------------

    // Every pair of levels the page can set, in both modes.
    function everyThreshold(check) {
        UsageLogic.WARN_PERCENTS.forEach(function (warn) {
            UsageLogic.CRITICAL_PERCENTS.forEach(function (critical) {
                if (critical > warn) {
                    check(UsageLogic.levelSamples({warn: warn, critical: critical}, "remaining"), warn, critical, "remaining")
                    check(UsageLogic.levelSamples({warn: warn, critical: critical}, "used"), warn, critical, "used")
                }
            })
        })
    }

    function test_samplesSitInTheirOwnLevel() {
        everyThreshold(function (samples, warn, critical, mode) {
            compare(samples.map(function (sample) { return sample.level }), ["normal", "warning", "critical"])
            samples.forEach(function (sample) {
                compare(UsageLogic.usageLevel(sample.used, {warn: warn, critical: critical}), sample.level,
                        sample.level + " at " + warn + "/" + critical)
                compare(sample.shown, UsageLogic.shownPercent(sample.used, mode))
            })
        })
    }

    function test_samplesFollowLeftAndUsed() {
        var left = UsageLogic.levelSamples({warn: 60, critical: 85}, "remaining")
        compare(left.map(function (sample) { return sample.shown }), [70, 28, 7])
        var used = UsageLogic.levelSamples({warn: 60, critical: 85}, "used")
        compare(used.map(function (sample) { return sample.shown }), [30, 72, 93])
        // Unset limits read as the defaults.
        compare(UsageLogic.levelSamples(null, "used"), used)
    }

    function test_sampleBarsStayVisibleAndInOrder() {
        everyThreshold(function (samples, warn, critical, mode) {
            var shares = samples.map(function (sample) { return UsageLogic.sampleShare(sample.shown) })
            shares.forEach(function (share) {
                verify(share >= UsageLogic.SAMPLE_MIN_SHARE, "at least the minimum: " + share)
                verify(share <= 1)
            })
            if (mode === "used")
                verify(shares[0] < shares[1] && shares[1] < shares[2], "used grows: " + shares)
            else
                verify(shares[0] > shares[1] && shares[1] > shares[2], "left drains: " + shares)
        })
        compare(UsageLogic.sampleShare(0), UsageLogic.SAMPLE_MIN_SHARE)
        compare(UsageLogic.sampleShare(100), 1)
        compare(UsageLogic.sampleShare(200), 1)
        compare(UsageLogic.sampleShare("x"), UsageLogic.SAMPLE_MIN_SHARE)
    }
}
