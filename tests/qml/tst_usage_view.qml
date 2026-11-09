import QtQuick
import QtTest
import org.kde.kirigami as Kirigami
import "../../plasmoid/contents/ui"
import "../../plasmoid/contents/ui/ProviderAccent.js" as ProviderAccent

// UsageView with provider text that tries to be markup: every name, plan,
// caption, error and amount from the helper is shown literally, as plain
// text, so a reply can't make the widget load an image or a link.
TestCase {
    id: testCase
    name: "UsageView"
    width: 500
    height: 700
    visible: true
    when: windowShown

    // Plasma injects i18n(); a stand-in that fills %1, %2...
    function i18n(text) {
        var result = text
        for (var index = 1; index < arguments.length; index++)
            result = result.replace("%" + index, String(arguments[index]))
        return result
    }

    function i18np(singular, plural, count) {
        return (count === 1 ? singular : plural).replace("%1", String(count))
    }

    function i18nc(context, text) {
        return i18n.apply(null, Array.prototype.slice.call(arguments, 1))
    }

    // Port 9 on this computer: nothing listens, and the test never loads it.
    readonly property string marker: "<img src=\"http://127.0.0.1:9/beacon.png\"><b>Pro</b> &amp;"

    // What main.qml provides as `root`.
    Item {
        id: root
        width: testCase.width
        height: testCase.height
        property bool hasData: true
        property string lastError: ""
        property var snapshot: ({})
        property bool expanded: true
        property string usageMode: "used"
        property var shownProviders: snapshot.providers || []
        property bool usageCompact: false
        property bool refreshInFlight: false
        property date lastUpdate: new Date(0)
        property var metricChoice: ({})
        property int refreshCalls: 0
        function refresh() { refreshCalls += 1 }
        function selectedMetrics(providerId) {
            return Array.isArray(metricChoice[providerId]) ? metricChoice[providerId] : []
        }
        function providerIconSource(providerId) { return "" }
        function displayedPercent(value) { return value }
        function valueColor(value) { return "black" }
        function barColor(value) { return value >= 50 ? "#ff0000" : "black" }
        property string historyNotice: ""
        property double historyNow: 0
        property var historyData: ({})
        function historyPoints(providerId, metricId) { return historyData[providerId + "." + metricId] || [] }

        UsageView {
            id: usage
            anchors.fill: parent
        }
    }

    Text {
        id: reference
        visible: false
    }

    function hostileSnapshot(status) {
        return {
            installed_provider_ids: ["cursor"],
            providers: [{
                provider_id: "cursor",
                display_name: testCase.marker,
                plan: testCase.marker,
                status: status,
                error_message: testCase.marker,
                windows: [{ caption: testCase.marker, used_percent: 40, resets_at: null }],
                billing_usage: { kind: "flex_credit_balance", remaining_credits: testCase.marker, usd_value: 1 }
            }]
        }
    }

    function collect(item, out) {
        if (!item || out.indexOf(item) >= 0)
            return
        out.push(item)
        var kids = item.children || []
        for (var index = 0; index < kids.length; index++)
            collect(kids[index], out)
        if (item.contentItem)
            collect(item.contentItem, out)
    }

    // Shown text items whose text carries the marker.
    function markedItems() {
        var items = []
        collect(usage, items)
        return items.filter(function (item) {
            return typeof item.text === "string" && item.text.indexOf("<img") >= 0
                && item.textFormat !== undefined && item.visible
        })
    }

    function init() {
        root.hasData = true
        root.lastError = ""
        root.snapshot = ({})
        root.usageCompact = false
        root.refreshInFlight = false
        root.lastUpdate = new Date(0)
        root.metricChoice = ({})
        root.refreshCalls = 0
    }

    function findNamed(name) {
        var items = []
        collect(usage, items)
        return items.filter(function (item) { return item.objectName === name })[0] || null
    }

    // Visible plain labels' texts.
    function shownTexts() {
        var items = []
        collect(usage, items)
        var result = []
        for (var index = 0; index < items.length; index++) {
            var item = items[index]
            var shown = item.visible
            for (var parent = item.parent; shown && parent && parent !== usage; parent = parent.parent)
                shown = parent.visible
            if (shown && typeof item.text === "string" && item.textFormat === Text.PlainText)
                result.push(item.text)
        }
        return result
    }

    function claudeSnapshot() {
        return {
            installed_provider_ids: ["claude", "codex"],
            providers: [{
                provider_id: "claude", display_name: "Claude Code", plan: "Max", status: "ok",
                windows: [
                    { kind: "session", caption: "5-hour window", used_percent: 10, resets_at: null },
                    { kind: "weekly", caption: "7-day window", used_percent: 70, resets_at: null }
                ],
                billing_usage: { kind: "bounded_spend", used_amount: 1, limit_amount: 5 }
            }, {
                provider_id: "codex", display_name: "Codex", status: "ok",
                windows: [{ kind: "weekly", caption: "Codex week", used_percent: 5, resets_at: null }]
            }]
        }
    }

    function test_emptyChoiceShowsEveryReading() {
        root.snapshot = claudeSnapshot()
        wait(20)
        var texts = shownTexts()
        verify(texts.indexOf("5-hour window") >= 0, texts)
        verify(texts.indexOf("7-day window") >= 0, texts)
        verify(texts.indexOf("Extra Usage") >= 0, texts)
        verify(texts.indexOf("Max") >= 0, texts)
    }

    function test_chosenReadingsFilterTheCards() {
        root.metricChoice = {claude: ["weekly"]}
        root.snapshot = claudeSnapshot()
        wait(20)
        var texts = shownTexts()
        verify(texts.indexOf("7-day window") >= 0, texts)
        verify(texts.indexOf("5-hour window") < 0, texts)
        verify(texts.indexOf("Extra Usage") < 0, texts)
        verify(texts.indexOf("Codex week") >= 0, texts)
    }

    function test_missingChosenReadingSaysSo() {
        root.metricChoice = {codex: ["spark"]}
        root.snapshot = claudeSnapshot()
        wait(20)
        verify(shownTexts().indexOf("None of the chosen readings is available.") >= 0)
    }

    function test_providersFollowTheGivenOrder() {
        root.snapshot = claudeSnapshot()
        root.shownProviders = [root.snapshot.providers[1], root.snapshot.providers[0]]
        wait(20)
        var texts = shownTexts()
        verify(texts.indexOf("Codex") >= 0 && texts.indexOf("Claude Code") > texts.indexOf("Codex"), texts)
        root.shownProviders = Qt.binding(function () { return root.snapshot.providers || [] })
    }

    function fillSnapshot(used) {
        return {
            installed_provider_ids: ["cursor"],
            providers: [{
                provider_id: "cursor",
                status: "ok",
                windows: [{ kind: "total_usage", caption: "Month", used_percent: used, resets_at: null }]
            }]
        }
    }

    // Above 0% the fill is wide enough to see; the number stays what it was.
    function checkFill(name, used, expected) {
        root.snapshot = fillSnapshot(used)
        // Looked up each time: a new snapshot rebuilds the bar, and the card's
        // fill animates to its width.
        var fill = null
        tryVerify(function () {
            fill = findNamed(name)
            return fill !== null && fill.parent.width > 0
                && Math.abs(fill.width - expected(fill.parent.width)) < 0.5
        }, 5000, name + " at " + used + "%")
        verify(fill.width <= fill.parent.width)
        verify(shownTexts().indexOf(Math.round(used) + "%") >= 0, shownTexts())
    }

    function checkFills(name) {
        var minimum = usage.minimumFillWidth
        compare(minimum, Kirigami.Units.gridUnit * 0.75)
        checkFill(name, 1, function () { return minimum })
        checkFill(name, 0, function () { return 0 })
        checkFill(name, 100, function (track) { return track })
        checkFill(name, 50, function (track) { return track / 2 })
    }

    function test_cardBarHasAMinimumFill() {
        checkFills("usageBarFill")
    }

    function test_compactBarHasAMinimumFill() {
        root.usageCompact = true
        checkFills("usageCompactFill")
    }

    function test_compactShowsTitlesNotCaptionsOrPlans() {
        root.usageCompact = true
        root.snapshot = claudeSnapshot()
        wait(20)
        var texts = shownTexts()
        verify(texts.indexOf("Session") >= 0, texts)
        verify(texts.indexOf("Weekly") >= 0, texts)
        verify(texts.indexOf("5-hour window") < 0, texts)
        verify(texts.indexOf("Max") < 0, texts)
        verify(texts.indexOf("Extra Usage") >= 0, texts)
        verify(texts.indexOf("70%") >= 0, texts)
    }

    function test_compactProviderTextIsPlain() {
        root.usageCompact = true
        root.snapshot = hostileSnapshot("error")
        wait(20)
        var marked = markedItems()
        // Name, error and credit amount.
        verify(marked.length >= 3, "found " + marked.length)
        var errorLines = 0
        for (var index = 0; index < marked.length; index++) {
            compare(marked[index].textFormat, Text.PlainText)
            if (marked[index].wrapMode === Text.Wrap) {
                compare(marked[index].maximumLineCount, 1)
                errorLines += 1
            }
        }
        compare(errorLines, 1)
    }

    // S1: Refresh also while loading and after a failed first load; the
    // "Updated" line only with data.
    function test_refreshWithoutData() {
        root.hasData = false
        root.lastError = "Helper exited with code 1"
        wait(20)
        var button = findNamed("usageRefreshButton")
        verify(button !== null && button.visible && button.enabled)
        verify(!findNamed("usageUpdatedLabel").visible)
        mouseClick(button)
        compare(root.refreshCalls, 1)
        root.lastError = ""
        wait(20)
        verify(button.visible)
        root.hasData = true
        wait(20)
        verify(findNamed("usageUpdatedLabel").visible)
    }

    function test_updatedLabelAndRefreshButton() {
        root.snapshot = claudeSnapshot()
        root.lastUpdate = new Date(Date.now() - 5 * 60000 - 1000)
        usage.nowMs = Date.now()
        wait(20)
        var label = findNamed("usageUpdatedLabel")
        verify(label !== null)
        compare(label.textFormat, Text.PlainText)
        compare(label.text, "Updated 5 min ago")
        var button = findNamed("usageRefreshButton")
        verify(button !== null && button.enabled)
        mouseClick(button)
        compare(root.refreshCalls, 1)
        root.refreshInFlight = true
        verify(!button.enabled)
        mouseClick(button)
        compare(root.refreshCalls, 1)
    }

    function test_providerTextIsPlain() {
        root.snapshot = hostileSnapshot("error")
        wait(20)
        var marked = markedItems()
        // Name, plan, error, caption and credit amount.
        verify(marked.length >= 5, "found " + marked.length)
        for (var index = 0; index < marked.length; index++)
            compare(marked[index].textFormat, Text.PlainText, "rich text at " + marked[index] + ": " + marked[index].text)
    }

    function test_staleReadingIsPlainToo() {
        root.snapshot = hostileSnapshot("stale")
        wait(20)
        var marked = markedItems()
        verify(marked.length >= 5, "found " + marked.length)
        for (var index = 0; index < marked.length; index++)
            compare(marked[index].textFormat, Text.PlainText)
    }

    // The plan name is laid out as the literal characters "<img src=...>",
    // as wide as plain text, not as an image plus a bold "Pro".
    function test_planNameIsShownLiterally() {
        root.snapshot = hostileSnapshot("ok")
        wait(20)
        var plan = null
        var items = markedItems()
        for (var index = 0; index < items.length; index++) {
            if (items[index].text === testCase.marker && items[index].opacity < 0.7)
                plan = items[index]
        }
        verify(plan !== null, "plan label not found")
        compare(plan.textFormat, Text.PlainText)
        reference.font = plan.font
        reference.textFormat = Text.PlainText
        reference.text = testCase.marker
        var plainWidth = reference.implicitWidth
        // (Without the <img>: rich text would really fetch it.)
        reference.text = testCase.marker.replace(/<img[^>]*>/, "")
        reference.textFormat = Text.RichText
        var richWidth = reference.implicitWidth
        verify(plainWidth > richWidth, "the reference must tell the formats apart")
        compare(plan.implicitWidth, plainWidth)
    }

    // W1: long provider text is cut to 200 characters wherever it shows.
    function test_longProviderTextIsCut() {
        var long = "L".repeat(5000)
        var snapshot = hostileSnapshot("error")
        var provider = snapshot.providers[0]
        provider.display_name = long
        provider.plan = long
        provider.error_message = long
        provider.windows[0].caption = long
        provider.billing_usage.remaining_credits = long
        root.snapshot = snapshot
        wait(20)
        var cut = "L".repeat(199) + "\u2026"
        var texts = shownTexts()
        var longest = 0
        var found = 0
        for (var index = 0; index < texts.length; index++) {
            if (texts[index].indexOf("LLL") >= 0) {
                found += 1
                verify(texts[index].indexOf(cut) >= 0, texts[index].slice(0, 40))
                verify(texts[index].indexOf("L".repeat(200)) < 0)
            }
            longest = Math.max(longest, texts[index].length)
        }
        // Name, plan, error, caption and credits.
        verify(found >= 5, "found " + found)
        verify(longest < 260, "longest shown text " + longest)
        root.snapshot = ({})
        root.hasData = false
        root.lastError = long
        wait(20)
        verify(shownTexts().indexOf(cut) >= 0)
    }

    function findAllNamed(name) {
        var items = []
        collect(usage, items)
        return items.filter(function (item) { return item.objectName === name })
    }

    function shownIn(item) {
        var shown = item.visible
        for (var parent = item.parent; shown && parent && parent !== usage; parent = parent.parent)
            shown = parent.visible
        return shown
    }

    function resetSnapshot(now) {
        var iso = function (ms) { return new Date(now + ms).toISOString() }
        return {
            installed_provider_ids: ["claude", "codex", "cursor"],
            providers: [{
                provider_id: "claude", display_name: testCase.marker, plan: "Max", status: "ok",
                windows: [
                    { kind: "session", caption: testCase.marker, used_percent: 10,
                      resets_at: iso(2 * 3600000 + 10 * 60000 + 5000) },
                    { kind: "weekly", caption: "7-day window", used_percent: 70, resets_at: iso(3 * 86400000) }
                ]
            }, {
                provider_id: "codex", display_name: "Codex", status: "ok",
                windows: [
                    { kind: "weekly", caption: "Codex week", used_percent: 5, resets_at: iso(5 * 3600000) },
                    { kind: "session", caption: "gone", used_percent: 5, resets_at: iso(-60000) }
                ]
            }, {
                // Unknown kinds and providers never name the next reset.
                provider_id: "cursor", display_name: "Cursor", status: "ok",
                windows: [{ kind: testCase.marker, caption: testCase.marker, used_percent: 5, resets_at: iso(60000) }]
            }, {
                provider_id: "nope", display_name: "Nope", status: "ok",
                windows: [{ kind: "weekly", caption: "x", used_percent: 5, resets_at: iso(60000) }]
            }]
        }
    }

    // U1: "Next reset" names the soonest reset of the readings shown, with
    // catalog names only, as plain text; hidden when none lies ahead.
    function test_nextResetLine() {
        var now = Date.now()
        usage.nowMs = now
        root.snapshot = resetSnapshot(now)
        wait(20)
        var label = findNamed("usageNextResetLabel")
        verify(label !== null)
        compare(label.textFormat, Text.PlainText)
        compare(label.elide, Text.ElideRight)
        verify(shownIn(label))
        compare(label.text, "Next reset: Claude Code Session in 2h 10m")
        // Below the "Updated" line.
        verify(label.mapToItem(usage, 0, 0).y > findNamed("usageUpdatedLabel").mapToItem(usage, 0, 0).y)
        // Only the readings the tab shows count.
        root.metricChoice = {claude: ["weekly"]}
        wait(20)
        compare(label.text, "Next reset: Codex Weekly in 5h 0m")
        // The 30 s clock moves it on.
        usage.nowMs = now + 6 * 3600000
        wait(20)
        compare(label.text, "Next reset: Claude Code Weekly in 2d 18h")
        usage.nowMs = now + 4 * 86400000
        wait(20)
        compare(label.text, "")
        verify(!label.visible)
        root.hasData = false
        usage.nowMs = now
        wait(20)
        verify(!label.visible)
    }

    // U1: a decorative accent strip on the leading edge of every catalog
    // provider's section, in both layouts.
    function test_accentStrips() {
        var layouts = [false, true]
        for (var layout = 0; layout < layouts.length; layout++) {
            root.usageCompact = layouts[layout]
            root.snapshot = claudeSnapshot()
            wait(20)
            var strips = findAllNamed("providerAccent").filter(shownIn)
            compare(strips.length, 2, "compact " + layouts[layout])
            var background = Kirigami.Theme.backgroundColor
            var ids = ["claude", "codex"]
            for (var index = 0; index < strips.length; index++) {
                var strip = strips[index]
                verify(Qt.colorEqual(strip.color, ProviderAccent.accentFor(
                    ids[index], background.r, background.g, background.b)), ids[index])
                verify(strip.width > 0 && strip.width < strip.height)
                // Leading edge: left of everything else in the section.
                var section = strip.parent.parent
                var left = strip.mapToItem(usage, strip.width, 0).x
                verify(left <= section.mapToItem(usage, 0, 0).x, "strip inside its section")
                verify(strip.mapToItem(usage, 0, 0).x >= 0)
                fuzzyCompare(strip.height, section.height, 0.5)
                fuzzyCompare(strip.mapToItem(usage, 0, 0).y, section.mapToItem(usage, 0, 0).y, 0.5)
            }
        }
        // A provider the catalog doesn't know gets no strip.
        root.usageCompact = false
        root.snapshot = {installed_provider_ids: ["nope"], providers: [{
            provider_id: "nope", display_name: "Nope", status: "ok",
            windows: [{ kind: "weekly", caption: "x", used_percent: 5, resets_at: null }]}]}
        wait(20)
        compare(findAllNamed("providerAccent").filter(shownIn).length, 0)
    }

    // A helper error without data: shown in a plain label, not the
    // placeholder's rich-text explanation.
    function test_helperErrorIsPlain() {
        root.hasData = false
        root.lastError = testCase.marker
        wait(20)
        var marked = markedItems()
        compare(marked.length, 1)
        compare(marked[0].textFormat, Text.PlainText)
        compare(marked[0].text, testCase.marker)
    }

    // --- Sparkline ----------------------------------------------------------

    readonly property int historyHour: 1700000000 - 1700000000 % 3600

    function historySnapshot() {
        return {
            installed_provider_ids: ["claude"],
            providers: [{provider_id: "claude", display_name: "Claude", status: "ok",
                         windows: [{kind: "weekly", caption: "Weekly", used_percent: 40, resets_at: null}]}]
        }
    }

    function sparklines() {
        var items = []
        collect(usage, items)
        return items.filter(function (item) { return item.objectName === "usageSparkline" })
    }

    function showSparkline(points) {
        root.usageCompact = false
        root.historyNow = historyHour
        root.historyData = {"claude.weekly": points}
        root.snapshot = historySnapshot()
        wait(20)
        var found = sparklines()
        compare(found.length, 1, "one per reading card")
        return found[0]
    }

    function cleanup() {
        root.usageCompact = false
        root.usageMode = "used"
        root.historyData = ({})
        root.historyNotice = ""
    }

    function test_sparklineHiddenWithoutPoints() {
        var spark = showSparkline([])
        compare(spark.visible, false)
        compare(spark.segments, [])
    }

    function test_sparklineOnePoint() {
        var spark = showSparkline([[historyHour, 30]])
        compare(spark.visible, true)
        tryVerify(function () { return spark.width > 0 }, 5000, "laid out")
        tryCompare(spark.segments, "length", 1)
        compare(spark.segments[0].dot, true)
    }

    function test_sparklineIsDecorative() {
        var spark = showSparkline([[historyHour, 30]])
        compare(spark.Accessible.ignored, true)
        compare(spark.text, undefined, "no text")
        compare(spark.children.length, 0, "no labels inside")
    }

    function test_sparklineGap() {
        var spark = showSparkline([[historyHour - 3 * 3600, 30], [historyHour - 2 * 3600, 35], [historyHour, 40]])
        tryCompare(spark.segments, "length", 2)
        compare(spark.segments[0].dot, false)
        compare(spark.segments[1].dot, true)
    }

    // The strokes really draw, in the level color barColor gives.
    function test_sparklinePaintsTheLevelColor() {
        var spark = showSparkline([[historyHour - 3600, 80], [historyHour, 80]])
        tryCompare(spark.segments, "length", 1)
        compare(spark.segmentColors.length, 1)
        verify(Qt.colorEqual(spark.segmentColors[0], "#ff0000"), "barColor of percent used")
        var segment = spark.segments[0]
        var x = Math.round((segment.x1 + segment.x2) / 2)
        var y = Math.floor((segment.y1 + segment.y2) / 2)
        tryVerify(function () {
            var data = spark.getContext("2d").getImageData(x, y, 1, 1).data
            return data[0] === 255 && data[1] === 0 && data[3] > 128
        }, 5000, "a red pixel on the stroke")
    }

    function strokePixel(spark) {
        var segment = spark.segments[0]
        return {x: Math.round((segment.x1 + segment.x2) / 2), y: Math.floor((segment.y1 + segment.y2) / 2)}
    }

    function alphaAt(spark, spot) {
        return spark.getContext("2d").getImageData(spot.x, spot.y, 1, 1).data[3]
    }

    // The old stroke goes and the new one is drawn, not only computed.
    function test_sparklineRepaintsWhenItsPointsChange() {
        var spark = showSparkline([[historyHour - 3600, 80], [historyHour, 80]])
        tryCompare(spark.segments, "length", 1)
        var before = strokePixel(spark)
        tryVerify(function () { return alphaAt(spark, before) > 128 }, 5000, "first stroke drawn")
        root.historyData = {"claude.weekly": [[historyHour - 3600, 20], [historyHour, 20]]}
        tryVerify(function () { return strokePixel(spark).y !== before.y }, 5000, "new geometry")
        var after = strokePixel(spark)
        tryVerify(function () { return alphaAt(spark, before) === 0 && alphaAt(spark, after) > 128 }, 5000, "repainted")
    }

    // Left drains, Used fills, like the bars.
    function test_sparklineFollowsLeftAndUsed() {
        var spark = showSparkline([[historyHour, 25]])
        tryCompare(spark.segments, "length", 1)
        var used = spark.segments[0].y1
        root.usageMode = "remaining"
        tryVerify(function () { return spark.segments[0].y1 < used }, 5000, "75% left sits higher than 25% used")
    }

    function test_sparklineAbsentInCompact() {
        showSparkline([[historyHour, 30]])
        root.usageCompact = true
        wait(20)
        compare(sparklines().length, 0)
    }

    function test_historyNoticeIsPlainTextAndHiddenWhenEmpty() {
        var items = []
        collect(usage, items)
        var label = items.filter(function (item) { return item.objectName === "usageHistoryNotice" })[0]
        compare(label.visible, false)
        root.historyNotice = testCase.marker
        tryCompare(label, "visible", true)
        compare(label.textFormat, Text.PlainText)
    }
}
