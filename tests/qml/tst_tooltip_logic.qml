import QtQuick
import QtTest
import "../../plasmoid/contents/ui/ProviderCatalog.js" as Catalog
import "../../plasmoid/contents/ui/TooltipLogic.js" as TooltipLogic

TestCase {
    name: "TooltipLogic"

    readonly property double minute: 60000
    readonly property double hour: 3600000

    function test_emptyOrOddMeansSameAsUsageTab() {
        compare(TooltipLogic.parseTooltipMetrics("", Catalog.providers), null)
        compare(TooltipLogic.parseTooltipMetrics(undefined, Catalog.providers), null)
        compare(TooltipLogic.parseTooltipMetrics("{", Catalog.providers), null)
        compare(TooltipLogic.parseTooltipMetrics("[\"claude\"]", Catalog.providers), null)
        compare(TooltipLogic.parseTooltipMetrics("null", Catalog.providers), null)
        compare(TooltipLogic.parseTooltipMetrics("7", Catalog.providers), null)
    }

    function test_parseKeepsCatalogIdsInCatalogOrder() {
        var parsed = TooltipLogic.parseTooltipMetrics(
            "{\"claude\":[\"weekly\",\"session\",\"session\",\"daily\",5],\"nope\":[\"weekly\"],"
            + "\"codex\":\"weekly\",\"grok\":[]}", Catalog.providers)
        compare(parsed, {claude: ["session", "weekly"], grok: []})
    }

    function test_claudeSessionIsSelectable() {
        var parsed = TooltipLogic.parseTooltipMetrics("{\"claude\":[\"session\"]}", Catalog.providers)
        compare(parsed.claude, ["session"])
        var next = TooltipLogic.setTooltipMetric(parsed, Catalog.providers, "claude", "weekly", true)
        compare(next.claude, ["session", "weekly"])
        compare(parsed.claude, ["session"])
        verify(TooltipLogic.isChosen(next, "claude", "session"))
        verify(!TooltipLogic.isChosen(next, "claude", "sonnet"))
        verify(!TooltipLogic.isChosen(null, "claude", "session"))
    }

    function test_setTooltipMetricIgnoresUnknownIds() {
        var next = TooltipLogic.setTooltipMetric({}, Catalog.providers, "claude", "daily", true)
        compare(next.claude, [])
        next = TooltipLogic.setTooltipMetric({claude: ["weekly"]}, Catalog.providers, "claude", "weekly", false)
        compare(next.claude, [])
        next = TooltipLogic.setTooltipMetric({}, Catalog.providers, "nope", "weekly", true)
        compare(next, {})
    }

    function test_seedFollowsTheUsageTab() {
        var seed = TooltipLogic.seedTooltipMetrics(
            "{\"claude\":[\"weekly\",\"session\"],\"codex\":[\"bogus\"]}", Catalog.providers)
        compare(seed.claude, ["session", "weekly"])
        compare(seed.codex, ["weekly"])
        compare(seed.cursor, ["total_usage"])
        compare(seed.copilot, ["credits"])
        compare(Object.keys(seed).length, Catalog.providers.length)
        compare(TooltipLogic.seedTooltipMetrics("broken", Catalog.providers).claude, ["weekly"])
    }

    function test_applyChoice() {
        var groups = [
            {provider_id: "claude", metrics: ["weekly"], name: "c"},
            {provider_id: "codex", metrics: ["weekly"]},
            {provider_id: "grok", metrics: ["weekly"]}
        ]
        compare(TooltipLogic.applyChoice(groups, null), groups)
        var applied = TooltipLogic.applyChoice(groups, {claude: ["session", "weekly"], grok: []})
        compare(applied.length, 2)
        compare(applied[0], {provider_id: "claude", metrics: ["session", "weekly"], name: "c"})
        // Not listed: what the Usage tab shows.
        compare(applied[1].metrics, ["weekly"])
        compare(groups[0].metrics, ["weekly"])
        compare(TooltipLogic.applyChoice(undefined, {}), [])
    }

    function test_sections() {
        var groups = [
            {name: "Claude Code", items: [
                {title: "Session", value: "38% used"},
                {title: "Weekly", value: "20% used", reset: "ignored"},
                null
            ]},
            {name: "Codex", items: []},
            {name: "Cursor"},
            null
        ]
        compare(TooltipLogic.tooltipSections(groups), [{name: "Claude Code", items: [
            {title: "Session", value: "38% used", level: ""},
            {title: "Weekly", value: "20% used", level: ""}
        ]}])
        compare(TooltipLogic.tooltipSections(undefined), [])
        // Everything comes back as plain strings.
        compare(TooltipLogic.tooltipSections([{name: 5, items: [{title: null, value: 7}]}]),
                [{name: "5", items: [{title: "", value: "7", level: ""}]}])
    }

    // T1: each reading keeps its level for the dot; anything else is ""
    // (money, credits, missing readings), a clear dot.
    function test_sectionLevels() {
        var sections = TooltipLogic.tooltipSections([{name: "Claude Code", items: [
            {title: "Session", value: "90% used", level: "critical"},
            {title: "Weekly", value: "70% used", level: "warning"},
            {title: "Sonnet", value: "10% used", level: "normal"},
            {title: "Extra Usage", value: "$1.00", level: ""},
            {title: "Fable", value: "x", level: "CRITICAL"},
            {title: "Odd", value: "x", level: {toString: function () { return "warning" }}},
            {title: "Number", value: "x", level: 3}
        ]}])
        compare(sections[0].items.map(function (item) { return item.level }),
                ["critical", "warning", "normal", "", "", "", ""])
        compare(TooltipLogic.readingLevel(undefined), "")
        compare(TooltipLogic.readingLevel("normal"), "normal")
    }
}
