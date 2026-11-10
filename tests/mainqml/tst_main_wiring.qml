import QtQuick
import QtQuick.Controls as QQC2
import QtTest
import HearthwireStubs
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as Plasma5Support
import org.kde.notification
import "../../plasmoid/contents/ui/ChatSites.js" as ChatSites
import "../../plasmoid/contents/ui/ProviderCatalog.js" as Catalog

// The real main.qml with a stubbed Plasmoid: its colors, levels and tooltip,
// read through the same properties the bars, numbers and dots use. Run by
// tests/test_main_qml_wiring.py, which puts the stubs on the import path. The
// HearthwireStubs import and the two isStub bindings below refuse to compile
// this file unless these modules are the stubs, so the real DataSource can
// never start the helper from here.
TestCase {
    id: testCase
    name: "MainWiring"
    width: 400
    height: 400
    // TestCase hides itself by default; the panel item must take clicks.
    visible: true
    when: windowShown

    // A compile error unless the module is the stub: nothing has run yet then.
    Plasma5Support.DataSource {
        isStub: true
    }

    Notification {
        isStub: true
    }

    readonly property url schema: Qt.resolvedUrl("../../plasmoid/contents/config/main.xml")
    readonly property url mainFile: Qt.resolvedUrl("../../plasmoid/contents/ui/main.qml")
    readonly property url usagePageFile: Qt.resolvedUrl("../../plasmoid/contents/ui/configUsage.qml")
    readonly property url generalPageFile: Qt.resolvedUrl("../../plasmoid/contents/ui/configGeneral.qml")
    readonly property string normalPick: "#00aa00"
    readonly property string warningPick: "#aa0000"
    readonly property string criticalPick: "#0000aa"

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

    // The stub's applet id is shared by every test; one that changes it
    // can't leak into the next.
    function init() {
        Plasmoid.id = 7
    }

    function load(file, settings) {
        verify(Plasmoid.loadSchema(testCase.schema), "main.xml is readable")
        // No first-run settings window, no metric migration.
        Plasmoid.configuration.initialSetupComplete = true
        Plasmoid.configuration.configSchemaVersion = 3
        Plasmoid.configuration.providerMetrics = JSON.stringify({claude: ["session", "weekly", "sonnet"]})
        for (var key in settings)
            Plasmoid.configuration[key] = settings[key]
        var component = Qt.createComponent(file)
        compare(component.status, Component.Ready, component.errorString())
        var item = createTemporaryObject(component, testCase)
        verify(item, "created")
        return item
    }

    // The objects main.qml really made are the stubs. Its first refresh can
    // start while it is created, so what keeps the helper from running is
    // the compile-time check above; this one confirms it held.
    function checkStubs(main) {
        var sources = []
        var notifications = []
        for (var index = 0; index < main.data.length; index++) {
            var object = main.data[index]
            if (typeof object.connectSource === "function")
                sources.push(object)
            else if (typeof object.createObject === "function")
                notifications.push(object)
        }
        compare(sources.length, 5, "usage, history, library, dropped and storage sources")
        sources.forEach(function (source) { compare(source.isStub, true, "a stub DataSource") })
        compare(notifications.length, 1, "the alert notification's Component")
        var notification = notifications[0].createObject(main, {})
        verify(notification, "created")
        compare(notification.isStub, true, "a stub Notification")
        notification.destroy()
    }

    function loadMain(settings) {
        var main = load(testCase.mainFile, settings)
        checkStubs(main)
        main.applySnapshot({
            schema_version: 2,
            generated_at: "2026-11-09T12:00:00Z",
            catalog: Catalog.providers,
            installed_provider_ids: ["claude"],
            providers: [{
                provider_id: "claude",
                status: "ok",
                windows: [
                    {kind: "session", used_percent: 97, resets_at: null},
                    {kind: "weekly", used_percent: 70, resets_at: null},
                    {kind: "sonnet", used_percent: 40, resets_at: null}
                ]
            }]
        })
        return main
    }

    function sameColor(actual, expected, what) {
        verify(Qt.colorEqual(actual, expected), what + ": got " + actual + ", expected " + expected)
    }

    // The levels' colors everywhere main.qml hands them out.
    function checkColors(main, critical, warning, normal) {
        sameColor(main.barColor(97), critical, "critical bar")
        sameColor(main.valueColor(97), critical, "critical value")
        sameColor(main.barColor(70), warning, "warning bar")
        sameColor(main.valueColor(70), warning, "warning value")
        sameColor(main.barColor(40), normal, "normal bar")
        sameColor(main.valueColor(40), Kirigami.Theme.textColor, "normal value")
        sameColor(main.usageTooltip.criticalColor, critical, "tooltip critical")
        sameColor(main.usageTooltip.warningColor, warning, "tooltip warning")
        sameColor(main.usageTooltip.normalColor, normal, "tooltip normal")
    }

    function defaultNormal() {
        var background = Kirigami.Theme.backgroundColor
        var luminance = background.r * 0.2126 + background.g * 0.7152 + background.b * 0.0722
        return luminance < 0.5 ? "#32c7d3" : "#008c95"
    }

    // Normal and Warning set, Critical left empty: Critical is the Warning color.
    function test_emptyCriticalFollowsCustomWarning() {
        var main = loadMain({usageNormalColor: normalPick, usageWarnColor: warningPick})
        checkColors(main, warningPick, warningPick, normalPick)
        verify(!Qt.colorEqual(Kirigami.Theme.negativeTextColor, warningPick), "the theme can't pass by chance")
    }

    function test_allThreeCustom() {
        var main = loadMain({usageNormalColor: normalPick, usageWarnColor: warningPick,
                             usageCriticalColor: criticalPick})
        checkColors(main, criticalPick, warningPick, normalPick)
    }

    function test_noCustomColorsUseTheTheme() {
        var main = loadMain({})
        checkColors(main, Kirigami.Theme.negativeTextColor, Kirigami.Theme.neutralTextColor, defaultNormal())
    }

    // Warning and Normal keep their own fallbacks.
    function test_customCriticalOnlyLeavesWarningOnTheTheme() {
        var main = loadMain({usageCriticalColor: criticalPick})
        checkColors(main, criticalPick, Kirigami.Theme.neutralTextColor, defaultNormal())
    }

    // Applying a change in the settings reaches the running widget.
    function test_warningChangeReachesCriticalLive() {
        var main = loadMain({usageNormalColor: normalPick})
        sameColor(main.barColor(97), Kirigami.Theme.negativeTextColor, "before")
        Plasmoid.configuration.usageWarnColor = warningPick
        sameColor(main.barColor(97), warningPick, "after")
        sameColor(main.usageTooltip.criticalColor, warningPick, "tooltip after")
        Plasmoid.configuration.usageWarnColor = ""
        sameColor(main.barColor(97), Kirigami.Theme.negativeTextColor, "cleared")
    }

    function findAll(item, objectName, found) {
        found = found || []
        if (item.objectName === objectName)
            found.push(item)
        for (var index = 0; index < item.children.length; index++)
            findAll(item.children[index], objectName, found)
        return found
    }

    function test_tooltipSectionsCarryTheLevels() {
        var main = loadMain({usageNormalColor: normalPick, usageWarnColor: warningPick})
        compare(main.tooltipSections.length, 1)
        var section = main.tooltipSections[0]
        compare(section.name, "Claude Code")
        compare(section.items.map(function (item) { return item.title }), ["Session", "Weekly", "Sonnet"])
        compare(section.items.map(function (item) { return item.value }), ["3% left", "30% left", "60% left"])
        compare(section.items.map(function (item) { return item.level }), ["critical", "warning", "normal"])
        compare(main.usageTooltip.sections.length, 1)
        compare(main.toolTipItem, main.usageTooltip)
        var dots = findAll(main.usageTooltip, "tooltipReadingDot")
        compare(dots.length, 3)
        sameColor(dots[0].color, warningPick, "critical dot")
        sameColor(dots[1].color, warningPick, "warning dot")
        sameColor(dots[2].color, normalPick, "normal dot")
    }

    function test_defaultThresholdBoundaries() {
        var main = loadMain({usageNormalColor: normalPick, usageWarnColor: warningPick,
                             usageCriticalColor: criticalPick})
        compare(main.usageThresholds.warn, 60)
        compare(main.usageThresholds.critical, 85)
        sameColor(main.barColor(59.9), normalPick, "just under warning")
        sameColor(main.barColor(60), warningPick, "at warning")
        sameColor(main.barColor(84.9), warningPick, "just under critical")
        sameColor(main.barColor(85), criticalPick, "at critical")
        sameColor(main.barColor(100), criticalPick, "full")
    }

    // The theme as the color box itself reads it: the settings page has its
    // own colors under some styles.
    Component {
        id: themeProbe
        Item {
            visible: false
            readonly property color negative: Kirigami.Theme.negativeTextColor
        }
    }

    function colorSwatch(button) {
        for (var index = 0; index < button.children.length; index++) {
            if (button.children[index].border !== undefined)
                return button.children[index]
        }
        return null
    }

    function namedInPage(item, objectName) {
        if (item.objectName === objectName)
            return item
        var kids = item.children || []
        for (var index = 0; index < kids.length; index++) {
            var found = namedInPage(kids[index], objectName)
            if (found)
                return found
        }
        if (item.contentItem)
            return namedInPage(item.contentItem, objectName)
        return null
    }

    // One color box of a freshly loaded page: its button, swatch and dialog.
    function colorBox(page, level) {
        var button = null
        tryVerify(function () {
            button = namedInPage(page, level + "ColorButton")
            return button !== null
        }, 5000, "the " + level + " box exists")
        var dialog = null
        var data = button.parent.data
        for (var index = 0; index < data.length; index++) {
            if (data[index].selectedColor !== undefined)
                dialog = data[index]
        }
        verify(dialog, level + " dialog found")
        return {button: button, swatch: colorSwatch(button), dialog: dialog}
    }

    // OK in the dialog without picking another color saves nothing, so
    // Critical goes on following Warning.
    function test_settingsUnchangedOkKeepsCriticalEmpty() {
        var page = load(testCase.usagePageFile, {})
        var box = colorBox(page, "critical")
        page.cfg_usageWarnColor = warningPick
        sameColor(box.swatch.color, warningPick, "shows Warning")
        box.dialog.accepted()
        compare(page.cfg_usageCriticalColor, "")
        page.cfg_usageWarnColor = criticalPick
        sameColor(box.swatch.color, criticalPick, "follows the new Warning")
        compare(page.cfg_usageCriticalColor, "")
    }

    function test_settingsUnchangedOkKeepsEveryEmptyBoxEmpty() {
        var page = load(testCase.usagePageFile, {})
        colorBox(page, "normal").dialog.accepted()
        compare(page.cfg_usageNormalColor, "")
        colorBox(page, "warning").dialog.accepted()
        compare(page.cfg_usageWarnColor, "")
        colorBox(page, "critical").dialog.accepted()
        compare(page.cfg_usageCriticalColor, "")
    }

    function test_settingsDifferentColorStillSaves() {
        var page = load(testCase.usagePageFile, {})
        var box = colorBox(page, "critical")
        page.cfg_usageWarnColor = warningPick
        box.dialog.selectedColor = criticalPick
        box.dialog.accepted()
        compare(page.cfg_usageCriticalColor, criticalPick)
        sameColor(box.swatch.color, criticalPick, "shows its own color")
    }

    // The Critical box while empty shows what main.qml will use, follows the
    // Warning box before Apply, and saves nothing of its own.
    function test_settingsCriticalBoxFollowsWarning() {
        var page = load(testCase.usagePageFile, {})
        var box = colorBox(page, "critical")
        var button = box.button
        var swatch = box.swatch
        verify(swatch, "swatch found")
        var probe = createTemporaryObject(themeProbe, button.parent)
        verify(!Qt.colorEqual(probe.negative, warningPick), "the theme can't pass by chance")
        sameColor(swatch.color, probe.negative, "empty Warning: the theme")
        page.cfg_usageWarnColor = warningPick
        sameColor(swatch.color, warningPick, "Warning picked")
        compare(page.cfg_usageCriticalColor, "")
        page.cfg_usageWarnColor = ""
        sameColor(swatch.color, probe.negative, "Warning reset")
        page.cfg_usageCriticalColor = criticalPick
        page.cfg_usageWarnColor = warningPick
        sameColor(swatch.color, criticalPick, "its own color wins")
    }

    // --- Usage ring ---------------------------------------------------------

    function compactOf(main) {
        var compact = createTemporaryObject(main.compactRepresentation, main, {width: 48, height: 48})
        verify(compact, "the real CompactRepresentation")
        return compact
    }

    function ringOf(compact) {
        var rings = findAll(compact, "usageRing")
        compare(rings.length, 1, "one ring")
        return rings[0]
    }

    function checkRing(main, fraction, color) {
        verify(main.ringState.visible, "the ring shows")
        fuzzyCompare(main.ringState.fraction, fraction, 0.0001, "fraction")
        sameColor(main.ringState.color, color, "ring color")
    }

    // Default: the first reading in the hover popup (Session, 97 used).
    function test_ringDefaultIsTheFirstHoverReading() {
        var main = loadMain({usageNormalColor: normalPick, usageWarnColor: warningPick,
                             usageCriticalColor: criticalPick})
        compare(Plasmoid.configuration.panelRing, "auto")
        checkRing(main, 0.03, criticalPick)
    }

    // Left drains, Used fills, live.
    function test_ringFollowsLeftAndUsed() {
        var main = loadMain({usageMode: "used", usageCriticalColor: criticalPick})
        checkRing(main, 0.97, criticalPick)
        Plasmoid.configuration.usageMode = "remaining"
        checkRing(main, 0.03, criticalPick)
    }

    function test_ringChosenPairUsesItsLevelColor() {
        var main = loadMain({panelRing: "claude.weekly", usageWarnColor: warningPick, usageNormalColor: normalPick})
        checkRing(main, 0.3, warningPick)
        Plasmoid.configuration.panelRing = "claude.sonnet"
        checkRing(main, 0.6, normalPick)
    }

    // The ring uses the bars' colors, so an empty Critical follows Warning.
    function test_ringCriticalFollowsWarning() {
        var main = loadMain({})
        sameColor(main.ringState.color, Kirigami.Theme.negativeTextColor, "theme")
        Plasmoid.configuration.usageWarnColor = warningPick
        sameColor(main.ringState.color, warningPick, "follows")
        sameColor(main.ringState.color, main.barColor(97), "the bar's color")
    }

    function test_ringOffHidesIt() {
        var main = loadMain({panelRing: "off"})
        verify(!main.ringState.visible, "off")
        var ring = ringOf(compactOf(main))
        verify(!ring.visible, "the ring item is hidden")
    }

    function test_ringHiddenWithoutUsageTab() {
        var main = loadMain({showUsageTab: false})
        compare(main.usageShown, false)
        verify(!main.ringState.visible, "no usage, no ring")
    }

    function test_ringHiddenForAReadingWithoutPercentage() {
        var main = loadMain({panelRing: "claude.fable"})
        verify(!main.ringState.visible, "no such window")
    }

    function test_ringSkipsAFailedProviderInAuto() {
        var main = loadMain({})
        main.applySnapshot({
            schema_version: 2,
            generated_at: "2026-11-09T12:01:00Z",
            catalog: Catalog.providers,
            installed_provider_ids: ["claude", "codex"],
            providers: [
                {provider_id: "claude", status: "error", failure_kind: "auth"},
                {provider_id: "codex", status: "ok", windows: [{kind: "weekly", used_percent: 10, resets_at: null}]}
            ]
        })
        checkRing(main, 0.9, main.normalUsageColor)
    }

    function test_ringDimsWhenStale() {
        var main = loadMain({})
        var ring = ringOf(compactOf(main))
        compare(ring.stale, false)
        compare(ring.opacity, 1)
        main.applySnapshot({
            schema_version: 2,
            generated_at: "2026-11-09T12:01:00Z",
            catalog: Catalog.providers,
            installed_provider_ids: ["claude"],
            providers: [{provider_id: "claude", status: "error", failure_kind: "transient"}]
        })
        compare(main.ringState.stale, true)
        verify(main.ringState.visible, "the last good reading stays")
        compare(ring.stale, true)
        verify(ring.opacity < 1, "dimmed")
    }

    // The real panel item draws what main.qml computed, and makes room.
    function test_compactRingWiring() {
        var main = loadMain({usageWarnColor: warningPick})
        var compact = compactOf(main)
        var ring = ringOf(compact)
        verify(ring.visible, "shown")
        fuzzyCompare(ring.fraction, 0.03, 0.0001, "fraction")
        sameColor(ring.ringColor, warningPick, "color")
        compare(ring.width, 48)
        compare(ring.height, 48)
        var withRing = compact.children[compact.children.length - 1].width
        Plasmoid.configuration.panelRing = "off"
        verify(compact.children[compact.children.length - 1].width > withRing, "the icon grows back without a ring")
    }

    function test_compactRingSizes() {
        var main = loadMain({})
        var compact = compactOf(main)
        var ring = ringOf(compact)
        var thin = Math.round(Kirigami.Units.smallSpacing / 2)
        compact.width = 22
        compact.height = 22
        verify(ring.ringWidth >= thin && ring.ringWidth >= 2, "small panel: " + ring.ringWidth)
        verify(ring.ringWidth * 2 < 22 / 2, "leaves room: " + ring.ringWidth)
        compact.width = 96
        compact.height = 48
        compare(ring.width, 48)
        compare(ring.height, 48)
        compare(ring.ringWidth, 5)
    }

    // --- Middle-click -------------------------------------------------------

    function middle(compact) {
        mouseClick(compact, 10, 10, Qt.MiddleButton)
    }

    function test_middleClickDefaultRefreshes() {
        var main = loadMain({})
        compare(main.middleClickTarget, "refresh")
        main.refreshQueued = false
        var runs = main.refreshRun
        main.middleClick()
        verify(main.refreshRun > runs || main.refreshQueued, "a refresh ran or queued")
        compare(main.expanded, false)
    }

    function test_middleClickButtonCallsIt() {
        var main = loadMain({middleClickOpens: "usage"})
        var compact = compactOf(main)
        middle(compact)
        compare(main.expanded, true)
        compare(main.popupTab, "usage")
        middle(compact)
        compare(main.expanded, false)
        compare(Plasmoid.configuration.middleClickOpens, "usage", "the setting is unchanged")
    }

    function test_leftClickStillToggles() {
        var main = loadMain({middleClickOpens: "usage"})
        var compact = compactOf(main)
        mouseClick(compact, 10, 10, Qt.LeftButton)
        compare(main.expanded, true)
        mouseClick(compact, 10, 10, Qt.LeftButton)
        compare(main.expanded, false)
    }

    function test_middleClickOpensAWebSite() {
        var main = loadMain({middleClickOpens: "chatgpt"})
        main.middleClick()
        compare(main.expanded, true)
        compare(main.popupTab, "chat")
        compare(main.chatSiteId, "chatgpt")
        main.middleClick()
        compare(main.expanded, false)
    }

    function test_middleClickSwitchesAnOpenPopup() {
        var main = loadMain({middleClickOpens: "usage", popupDefaultTab: "chat"})
        main.popupTab = "chat"
        main.expanded = true
        main.middleClick()
        compare(main.expanded, true)
        compare(main.popupTab, "usage")
    }

    function test_middleClickOllamaTakesTheFocus() {
        var main = loadMain({middleClickOpens: "ollama",
                             chatSites: JSON.stringify(["claude", "ollama"])})
        var focused = 0
        main.ollamaFocusRequested.connect(function () { focused += 1 })
        main.middleClick()
        compare(main.expanded, true)
        compare(main.chatSiteId, "ollama")
        compare(focused, 1)
    }

    // Ollama is off by default: a plain click, nothing else changes.
    function test_middleClickOffTargetIsANormalClick() {
        var main = loadMain({middleClickOpens: "ollama"})
        var site = main.chatSiteId
        main.middleClick()
        compare(main.expanded, true)
        compare(main.chatSiteId, site)
        main.middleClick()
        compare(main.expanded, false)
    }

    function test_middleClickOddSettingIsRefresh() {
        var main = loadMain({middleClickOpens: "constructor"})
        compare(main.middleClickTarget, "refresh")
    }

    // --- Color preview ------------------------------------------------------

    function previewPart(page, kind, level) {
        var part = null
        tryVerify(function () {
            part = namedInPage(page, kind + "_" + level)
            return part !== null
        }, 5000, kind + " " + level + " exists")
        return part
    }

    function checkPreview(page, level, color, what) {
        sameColor(previewPart(page, "previewFill", level).color, color, what + " " + level + " bar")
        sameColor(previewPart(page, "previewDot", level).color, color, what + " " + level + " dot")
    }

    function test_previewShowsChosenColorsBeforeApply() {
        var page = load(testCase.usagePageFile, {})
        page.cfg_usageNormalColor = normalPick
        page.cfg_usageWarnColor = warningPick
        page.cfg_usageCriticalColor = criticalPick
        checkPreview(page, "normal", normalPick, "chosen")
        checkPreview(page, "warning", warningPick, "chosen")
        checkPreview(page, "critical", criticalPick, "chosen")
        compare(Plasmoid.configuration.usageCriticalColor, "", "nothing is applied")
    }

    function test_previewEmptyCriticalFollowsWarning() {
        var page = load(testCase.usagePageFile, {})
        var box = colorBox(page, "critical")
        page.cfg_usageWarnColor = warningPick
        checkPreview(page, "critical", warningPick, "follows")
        sameColor(box.swatch.color, warningPick, "as its box")
        page.cfg_usageWarnColor = criticalPick
        checkPreview(page, "critical", criticalPick, "follows the change")
        compare(page.cfg_usageCriticalColor, "", "and saves nothing")
    }

    function test_previewDefaultsMatchTheBoxes() {
        var page = load(testCase.usagePageFile, {})
        var levels = ["normal", "warning", "critical"]
        levels.forEach(function (level) {
            checkPreview(page, level, colorBox(page, level).swatch.color, "default")
        })
    }

    // The samples read the theme where they are, as the boxes do: the page's
    // own can differ under some styles.
    function test_previewReadsTheThemeOfItsRow() {
        var page = load(testCase.usagePageFile, {})
        checkPreview(page, "warning", colorBox(page, "warning").swatch.color, "before")
        var column = namedInPage(page, "usagePreview")
        verify(column, "preview found")
        column.Kirigami.Theme.inherit = false
        column.Kirigami.Theme.neutralTextColor = "#abcdef"
        checkPreview(page, "warning", "#abcdef", "the row's theme")
    }

    function previewWidths(page) {
        return ["normal", "warning", "critical"].map(function (level) {
            return previewPart(page, "previewFill", level).width
        })
    }

    function test_previewFollowsLeftAndUsed() {
        var page = load(testCase.usagePageFile, {})
        page.cfg_usageMode = "remaining"
        tryVerify(function () { return previewWidths(page)[0] > 0 }, 5000, "laid out")
        var left = previewWidths(page)
        verify(left[0] > left[1] && left[1] > left[2], "left drains: " + left)
        compare(previewPart(page, "previewLabel", "critical").text, "Critical · 7% left")
        page.cfg_usageMode = "used"
        tryVerify(function () { var w = previewWidths(page); return w[0] < w[2] }, 5000, "used fills")
        var used = previewWidths(page)
        verify(used[0] < used[1] && used[1] < used[2], "used grows: " + used)
        compare(previewPart(page, "previewLabel", "critical").text, "Critical · 93% used")
    }

    // At the far end of the scale the bars still show their color.
    function test_previewBarsStayVisible() {
        var page = load(testCase.usagePageFile, {})
        page.cfg_usageMode = "remaining"
        page.cfg_usageWarnPercent = 90
        page.cfg_usageCriticalPercent = 95
        var track = previewPart(page, "previewTrack", "critical")
        tryVerify(function () { return track.width > 0 }, 5000, "laid out")
        compare(previewPart(page, "previewLabel", "critical").text, "Critical · 2% left")
        verify(previewPart(page, "previewFill", "critical").width >= track.width * 0.25, "visible")
        page.cfg_usageMode = "used"
        var normalTrack = previewPart(page, "previewTrack", "normal")
        verify(previewPart(page, "previewFill", "normal").width >= normalTrack.width * 0.25, "visible")
    }

    function test_previewLabelsArePlainText() {
        var page = load(testCase.usagePageFile, {})
        compare(previewPart(page, "previewLabel", "normal").textFormat, Text.PlainText)
    }

    function test_settingsRingChoiceSaves() {
        var page = load(testCase.usagePageFile, {})
        compare(page.cfg_panelRing, "auto")
        compare(page.ringChoice.value, "auto")
        page.setPanelRing("claude.weekly")
        compare(page.cfg_panelRing, "claude.weekly")
        compare(page.ringChoice.mode, "pair")
    }

    function choiceBox(page, objectName) {
        var combo = null
        tryVerify(function () {
            combo = namedInPage(page, objectName)
            return combo !== null
        }, 5000, objectName + " exists")
        return combo
    }

    // As the user picking the entry with this value.
    function pick(combo, value) {
        var index = combo.indexOfValue(value)
        verify(index >= 0, value + " is offered")
        combo.currentIndex = index
        combo.activated(index)
    }

    function test_settingsRingBoxSaves() {
        var page = load(testCase.usagePageFile, {})
        var combo = choiceBox(page, "panelRingChoice")
        compare(combo.currentValue, "auto")
        verify(combo.indexOfValue("claude.extra_usage") < 0, "no money reading")
        pick(combo, "codex.weekly")
        compare(page.cfg_panelRing, "codex.weekly")
        pick(combo, "off")
        compare(page.cfg_panelRing, "off")
        compare(combo.currentValue, "off")
    }

    function test_settingsRingBoxShowsOddValuesAsAutomatic() {
        var page = load(testCase.usagePageFile, {})
        page.cfg_panelRing = "claude.spark"
        compare(choiceBox(page, "panelRingChoice").currentValue, "auto")
        compare(page.cfg_panelRing, "claude.spark", "untouched until a pick")
    }

    function test_settingsMiddleClickBoxSaves() {
        var page = load(testCase.generalPageFile, {})
        var combo = choiceBox(page, "middleClickChoice")
        compare(combo.currentValue, "refresh")
        pick(combo, "usage")
        compare(page.cfg_middleClickOpens, "usage")
        pick(combo, "local")
        compare(page.cfg_middleClickOpens, "local")
        pick(combo, "ollama")
        compare(page.cfg_middleClickOpens, "ollama")
    }

    function test_settingsMiddleClickBoxShowsOddValuesAsRefresh() {
        var page = load(testCase.generalPageFile, {})
        page.cfg_middleClickOpens = "chat"
        compare(choiceBox(page, "middleClickChoice").currentValue, "refresh")
        compare(page.cfg_middleClickOpens, "chat", "untouched until a pick")
    }

    // --- Usage history ------------------------------------------------------

    // A settings page keeps its sources deeper down than main.qml does.
    function sourcesOf(owner, found, seen) {
        found = found || []
        seen = seen || []
        if (!owner || seen.indexOf(owner) >= 0)
            return found
        seen.push(owner)
        if (typeof owner.connectSource === "function")
            found.push(owner)
        var lists = [owner.data, owner.children, owner.contentItem ? [owner.contentItem] : []]
        lists.forEach(function (list) {
            for (var index = 0; list && index < list.length; index++)
                sourcesOf(list[index], found, seen)
        })
        return found
    }

    function everyCommand(owner) {
        var found = []
        sourcesOf(owner).forEach(function (source) { found = found.concat(source.commands) })
        return found
    }

    // Every command the owner's sources were asked to run; none ever starts.
    // Each one names this widget and carries no settings.
    function historyCommands(owner) {
        wait(0)
        var found = []
        sourcesOf(owner).forEach(function (source) {
            source.commands.forEach(function (command) {
                if (command.indexOf("--usage-history") >= 0)
                    found.push(command)
            })
        })
        found.forEach(namesTheWidget)
        return found
    }

    // The fixed helper, the operation, then this widget's id as the only
    // --applet (a record's sample after it), and no --data.
    function namesTheWidget(command) {
        var pattern = new RegExp("^env HEARTHWIRE_RUN=[0-9]+ python3 -P -m hearthwire --(usage-history|settings-backup) "
                                 + "[a-z]+ --applet " + Plasmoid.id + "( --sample [a-z_.=0-9,]+)?$")
        verify(pattern.test(command), command)
        compare(command.split("--applet").length, 2, "one --applet: " + command)
        verify(command.indexOf("--data") < 0, "no --data: " + command)
    }

    function ops(commands) {
        return commands.map(function (command) {
            return command.split("--usage-history ")[1].split(" ")[0]
        })
    }

    // The helper answering its running step.
    function answer(owner, reply, exitCode) {
        wait(0)
        var running = null
        sourcesOf(owner).forEach(function (source) {
            source.connectedSources.forEach(function (command) {
                if (command.indexOf("--usage-history") >= 0) {
                    running = {source: source, command: command}
                }
            })
        })
        verify(running, "a history step is running")
        running.source.newData(running.command, {"exit code": exitCode === undefined ? 0 : exitCode, "stdout": reply})
        wait(0)
    }

    function nowSeconds() {
        var seconds = Math.floor(Date.now() / 1000)
        return seconds - seconds % 3600
    }

    function historyReply(points) {
        return JSON.stringify({ok: true, history_version: 1, bucket_seconds: 3600, now: nowSeconds(),
                               series: [{provider_id: "claude", metric_id: "weekly", points: points}]})
    }

    function goodSnapshot(main, providers) {
        main.applySnapshot({schema_version: 2, generated_at: "2026-11-09T12:01:00Z", catalog: Catalog.providers,
                            installed_provider_ids: ["claude"], providers: providers})
    }

    function okClaude() {
        return [{provider_id: "claude", status: "ok", windows: [{kind: "weekly", used_percent: 50, resets_at: null}]}]
    }

    readonly property string firstSample: "--sample claude.session=97,claude.weekly=70,claude.sonnet=40"

    function test_historyOffByDefaultRunsNothing() {
        var main = loadMain({})
        compare(Plasmoid.configuration.usageHistoryEnabled, false)
        compare(main.usageHistoryEnabled, false)
        goodSnapshot(main, okClaude())
        wait(20)
        compare(historyCommands(main), [])
        compare(main.historyPoints("claude", "weekly"), [])
    }

    function test_historyOnReadsOnceAndRecords() {
        var main = loadMain({usageHistoryEnabled: true})
        var commands = historyCommands(main)
        compare(ops(commands), ["read"], "one at a time")
        answer(main, historyReply([[nowSeconds(), 70]]))
        commands = historyCommands(main)
        compare(ops(commands), ["read", "record"])
        verify(commands[1].indexOf(firstSample) > 0, commands[1])
        verify(commands[1].indexOf("env HEARTHWIRE_RUN=") === 0, "the fixed helper command")
        verify(commands[1].indexOf("python3 -P -m hearthwire --usage-history record") > 0, commands[1])
        answer(main, historyReply([[nowSeconds(), 70]]))
        compare(ops(historyCommands(main)), ["read", "record"], "reads only once")
    }

    function test_historyReplyFeedsTheSeries() {
        var main = loadMain({usageHistoryEnabled: true})
        answer(main, historyReply([[nowSeconds(), 12]]))
        compare(main.historyPoints("claude", "weekly"), [[nowSeconds(), 12]])
        compare(main.historyNow, nowSeconds())
    }

    function test_historyNothingRecordedForStaleOrError() {
        var main = loadMain({usageHistoryEnabled: true})
        answer(main, historyReply([]))
        answer(main, historyReply([]))
        compare(ops(historyCommands(main)), ["read", "record"])
        main.historyLastRecord = 0
        goodSnapshot(main, [{provider_id: "claude", status: "error", failure_kind: "transient"}])
        compare(main.snapshot.providers[0].status, "stale", "the last good reading stays shown")
        wait(20)
        compare(ops(historyCommands(main)), ["read", "record"], "stale records nothing")
        goodSnapshot(main, [{provider_id: "claude", status: "error", failure_kind: "auth"}])
        wait(20)
        compare(ops(historyCommands(main)), ["read", "record"], "error records nothing")
    }

    function test_historyMinGap() {
        var main = loadMain({usageHistoryEnabled: true})
        answer(main, historyReply([]))
        answer(main, historyReply([]))
        goodSnapshot(main, okClaude())
        wait(20)
        compare(ops(historyCommands(main)), ["read", "record"], "inside the gap")
        main.historyLastRecord = Date.now() - 890000
        goodSnapshot(main, okClaude())
        wait(20)
        compare(ops(historyCommands(main)), ["read", "record"], "still inside the gap")
        main.historyLastRecord = Date.now() - 900000
        goodSnapshot(main, okClaude())
        compare(ops(historyCommands(main)), ["read", "record", "record"], "after the gap")
    }

    function test_historyOffClearsAndHidesAtOnce() {
        var main = loadMain({usageHistoryEnabled: true})
        answer(main, historyReply([[nowSeconds(), 12]]))
        answer(main, historyReply([[nowSeconds(), 12]]))
        compare(main.historyPoints("claude", "weekly").length, 1)
        Plasmoid.configuration.usageHistoryEnabled = false
        compare(main.historyPoints("claude", "weekly"), [], "gone at once")
        compare(main.historySeries, {})
        compare(ops(historyCommands(main)), ["read", "record", "clear"])
        answer(main, JSON.stringify({ok: true}))
        goodSnapshot(main, okClaude())
        wait(20)
        compare(ops(historyCommands(main)), ["read", "record", "clear"], "nothing after off")
    }

    // Back on: a new read, and the next good snapshot records at once.
    function test_historyOnAgainStartsOver() {
        var main = loadMain({usageHistoryEnabled: true})
        answer(main, historyReply([]))
        answer(main, historyReply([]))
        Plasmoid.configuration.usageHistoryEnabled = false
        answer(main, JSON.stringify({ok: true}))
        Plasmoid.configuration.usageHistoryEnabled = true
        compare(ops(historyCommands(main)), ["read", "record", "clear", "read"])
        answer(main, historyReply([]))
        goodSnapshot(main, okClaude())
        compare(ops(historyCommands(main)), ["read", "record", "clear", "read", "record"])
    }

    // A record still running when history goes off can't land after the clear.
    function test_historyClearWaitsForTheRunningStep() {
        var main = loadMain({usageHistoryEnabled: true})
        answer(main, historyReply([]))
        compare(ops(historyCommands(main)), ["read", "record"])
        Plasmoid.configuration.usageHistoryEnabled = false
        wait(20)
        compare(ops(historyCommands(main)), ["read", "record"], "the clear waits")
        answer(main, historyReply([[nowSeconds(), 12]]))
        compare(main.historyPoints("claude", "weekly"), [], "the late reply is not shown")
        compare(main.historySeries, {})
        compare(ops(historyCommands(main)), ["read", "record", "clear"])
    }

    function test_historyQueuedStepsDroppedWhenOff() {
        var main = loadMain({usageHistoryEnabled: true})
        // The read runs; the first snapshot's record waits behind it.
        compare(ops(historyCommands(main)), ["read"])
        compare(main.historyQueue.length, 1)
        Plasmoid.configuration.usageHistoryEnabled = false
        answer(main, historyReply([]))
        compare(ops(historyCommands(main)), ["read", "clear"], "the queued record is dropped")
    }

    function test_historyNotReadWithoutTheUsageTab() {
        var main = loadMain({usageHistoryEnabled: true, showUsageTab: false})
        compare(main.usageShown, false)
        goodSnapshot(main, okClaude())
        wait(20)
        compare(historyCommands(main), [])
    }

    function test_historyReadsWhenTheUsageTabComesBack() {
        var main = loadMain({usageHistoryEnabled: true, showUsageTab: false})
        compare(historyCommands(main), [])
        Plasmoid.configuration.showUsageTab = true
        compare(main.usageShown, true)
        compare(ops(historyCommands(main)), ["read"])
    }

    // Only this run's results: a provider left out of it keeps showing "ok"
    // from an earlier run, and its old reading must not be recorded as new.
    function test_historyRecordsOnlyThisRunsResults() {
        var main = loadMain({usageHistoryEnabled: true})
        answer(main, historyReply([]))
        answer(main, historyReply([]))
        main.historyLastRecord = 0
        main.applySnapshot({schema_version: 2, generated_at: "2026-11-09T12:01:00Z", catalog: Catalog.providers,
                            installed_provider_ids: ["claude", "codex"],
                            providers: [{provider_id: "codex", status: "ok",
                                         windows: [{kind: "weekly", used_percent: 5, resets_at: null}]}]})
        compare(main.snapshot.providers.length, 2, "Claude is still shown")
        var commands = historyCommands(main)
        compare(ops(commands), ["read", "record", "record"])
        verify(commands[2].indexOf("--sample codex.weekly=5") > 0 && commands[2].indexOf("claude") < 0, commands[2])
    }

    function test_historyMalformedReplyIsNoHistory() {
        var main = loadMain({usageHistoryEnabled: true})
        answer(main, historyReply([[nowSeconds(), 12]]))
        compare(main.historyPoints("claude", "weekly").length, 1)
        answer(main, JSON.stringify({ok: true, history_version: 1, bucket_seconds: 3600, now: nowSeconds(),
                                     series: [{provider_id: "claude", metric_id: "weekly", points: [[nowSeconds(), 900]]}]}))
        compare(main.historyPoints("claude", "weekly"), [], "never rendered")
    }

    function test_historyHelperErrorKeepsTheLastGoodLines() {
        var main = loadMain({usageHistoryEnabled: true})
        answer(main, historyReply([[nowSeconds(), 12]]))
        answer(main, JSON.stringify({ok: false, error: "busy"}))
        compare(main.historyPoints("claude", "weekly").length, 1)
        compare(main.historyNotice, "", "busy shows nothing")
    }

    function test_historyLegacyDataShowsTheFixedMessage() {
        var main = loadMain({usageHistoryEnabled: true})
        answer(main, historyReply([]))
        answer(main, JSON.stringify({ok: false, error: "legacy-data"}))
        compare(main.historyNotice, "Saved sign-ins from the previous version haven't been moved yet. Run the installer again with --restart-plasma.")
        Plasmoid.configuration.usageHistoryEnabled = false
        compare(main.historyNotice, "", "cleared with the history")
    }

    function test_historyGivesUpOnAStepThatNeverAnswers() {
        var main = loadMain({usageHistoryEnabled: true})
        compare(ops(historyCommands(main)), ["read"])
        main.historyStartedAt = Date.now() - 200000
        main.historyNext()
        compare(ops(historyCommands(main)), ["read", "record"])
    }

    function allNamed(item, objectName, found) {
        found = found || []
        if (!item || found.indexOf(item) >= 0)
            return found
        if (item.objectName === objectName)
            found.push(item)
        var kids = item.children || []
        for (var index = 0; index < kids.length; index++)
            allNamed(kids[index], objectName, found)
        if (item.contentItem)
            allNamed(item.contentItem, objectName, found)
        return found
    }

    function sparklineMain(settings) {
        var main = loadMain(Object.assign({usageHistoryEnabled: true, showChatTab: false,
                                           providerMetrics: "{}"}, settings))
        answer(main, historyReply([[nowSeconds() - 3600, 70], [nowSeconds(), 70]]))
        answer(main, historyReply([[nowSeconds() - 3600, 70], [nowSeconds(), 70]]))
        var full = createTemporaryObject(main.fullRepresentation, main, {width: 600, height: 800})
        verify(full, "the real popup")
        return {main: main, full: full}
    }

    // The real popup: a sparkline for the reading with history, colored by
    // the level of percent used, gone at once when history goes off.
    function test_sparklineInTheRealPopup() {
        var shown = sparklineMain({usageWarnColor: warningPick})
        var sparks = []
        tryVerify(function () {
            sparks = allNamed(shown.full, "usageSparkline").filter(function (item) { return item.visible })
            return sparks.length === 1
        }, 5000, "one reading has history")
        tryCompare(sparks[0].segments, "length", 1)
        sameColor(sparks[0].segmentColors[0], warningPick, "70% used is the warning level")
        Plasmoid.configuration.usageHistoryEnabled = false
        compare(sparks[0].visible, false, "gone at once")
    }

    function test_sparklineAbsentInCompactInTheRealPopup() {
        var shown = sparklineMain({usageCompact: true})
        wait(50)
        verify(allNamed(shown.full, "usageHistoryNotice").length === 1, "the Usage tab is built")
        compare(allNamed(shown.full, "usageSparkline").length, 0)
    }

    // --- Usage history settings ---------------------------------------------

    function generalPage() {
        var page = load(testCase.generalPageFile, {})
        // Its first vault status check is not part of these tests.
        wait(0)
        return page
    }

    function generalPart(page, objectName) {
        var part = null
        tryVerify(function () {
            part = namedInPage(page, objectName)
            return part !== null
        }, 5000, objectName + " exists")
        return part
    }

    function test_settingsHistoryBoxIsOffAndRunsNothing() {
        var page = generalPage()
        compare(page.cfg_usageHistoryEnabled, false)
        compare(generalPart(page, "usageHistoryChoice").checked, false)
        compare(sourcesOf(page).length, 3, "the vault's, the delete button's and the backup's")
        verify(everyCommand(page).length > 0, "its other source is really seen")
        compare(historyCommands(page), [])
    }

    function test_settingsHistoryBoxSaves() {
        var page = generalPage()
        var box = generalPart(page, "usageHistoryChoice")
        box.toggle()
        box.toggled()
        compare(page.cfg_usageHistoryEnabled, true)
        compare(historyCommands(page), [], "ticking runs nothing by itself")
    }

    function test_settingsExplanationIsPlainAndSaysWhere() {
        var label = generalPart(generalPage(), "usageHistoryExplanation")
        compare(label.textFormat, Text.PlainText)
        verify(label.text.indexOf("usage-history") >= 0, "where")
        verify(label.text.indexOf("percent used") >= 0, "what")
        verify(label.text.indexOf("Each widget keeps its own history.") >= 0, "per widget")
        verify(label.text.indexOf("saved at most every 15 minutes, keeping one value per hour") >= 0, "how often")
        verify(label.text.indexOf("once per hour") < 0, "not the old wording")
        verify(label.text.indexOf("Turning it off and applying deletes this widget's history") >= 0, "what off deletes")
    }

    function pressDelete(page) {
        var button = generalPart(page, "usageHistoryDelete")
        verify(button.enabled)
        button.clicked()
        compare(ops(historyCommands(page)), ["clear"])
        compare(button.enabled, false, "busy while it runs")
        return button
    }

    function test_settingsDeleteSuccess() {
        var page = generalPage()
        var button = pressDelete(page)
        var status = generalPart(page, "usageHistoryStatus")
        answer(page, JSON.stringify({ok: true}))
        compare(status.text, "Usage history deleted.")
        compare(status.textFormat, Text.PlainText)
        compare(button.enabled, true)
    }

    function test_settingsDeleteFailureIsAFixedMessage() {
        var page = generalPage()
        pressDelete(page)
        answer(page, JSON.stringify({ok: false, error: "not-owned"}))
        compare(generalPart(page, "usageHistoryStatus").text, "Couldn't delete the usage history. Try again in a moment.")
    }

    function test_settingsDeleteNeverShowsHelperText() {
        var page = generalPage()
        pressDelete(page)
        answer(page, "/home/soul/.local/share boom <b>secret</b>", 1)
        var text = generalPart(page, "usageHistoryStatus").text
        compare(text, "Couldn't delete the usage history. Try again in a moment.")
    }

    // A clear never meets legacy data (only a write does): no own text.
    function test_settingsDeleteLegacyDataIsAFailure() {
        var page = generalPage()
        pressDelete(page)
        answer(page, JSON.stringify({ok: false, error: "legacy-data"}))
        compare(generalPart(page, "usageHistoryStatus").text, "Couldn't delete the usage history. Try again in a moment.")
    }

    // --- History turned off: the clear is owed until the helper confirms it --

    readonly property string busy: JSON.stringify({ok: false, error: "busy"})
    readonly property string clearOk: JSON.stringify({ok: true})
    readonly property string clearNotice: "The usage history couldn't be deleted. Use Delete usage history in Settings → General → Privacy."

    // On, its first steps answered, then turned off and the first clear running.
    function mainClearing() {
        var main = loadMain({usageHistoryEnabled: true})
        answer(main, historyReply([]))
        answer(main, historyReply([]))
        Plasmoid.configuration.usageHistoryEnabled = false
        compare(ops(historyCommands(main)), ["read", "record", "clear"])
        return main
    }

    function clearCount(main) {
        return ops(historyCommands(main)).filter(function (op) { return op === "clear" }).length
    }

    function test_clearIsOwedUntilConfirmed() {
        var main = mainClearing()
        compare(Plasmoid.configuration.usageHistoryClearOwed, true, "stored before the helper answers")
        answer(main, clearOk)
        compare(Plasmoid.configuration.usageHistoryClearOwed, false)
        compare(main.historyNotice, "")
    }

    function test_clearRetriesBusyAfterADelay() {
        var main = mainClearing()
        answer(main, busy)
        compare(clearCount(main), 1, "not at once")
        compare(main.historyNotice, "", "not told yet")
        tryVerify(function () { return clearCount(main) === 2 }, 6000, "retried by its timer")
    }

    function test_clearGivesUpAfterBoundedBusy() {
        var main = mainClearing()
        answer(main, busy)
        tryVerify(function () { return clearCount(main) === 2 }, 6000, "second try")
        answer(main, busy)
        tryVerify(function () { return clearCount(main) === 3 }, 6000, "third try")
        answer(main, busy)
        compare(clearCount(main), 3)
        compare(main.historyNotice, clearNotice)
        compare(Plasmoid.configuration.usageHistoryClearOwed, true, "still owed")
        wait(3200)
        compare(clearCount(main), 3, "no more tries")
    }

    function test_clearOtherFailureIsToldAtOnce() {
        var main = mainClearing()
        answer(main, JSON.stringify({ok: false, error: "not-owned"}))
        compare(main.historyNotice, clearNotice)
        compare(clearCount(main), 1, "only busy is retried")
    }

    function test_clearMalformedReplyIsAFailure() {
        var main = mainClearing()
        answer(main, "/home/soul secret", 1)
        compare(main.historyNotice, clearNotice)
    }

    function test_clearOwedAtStartIsPaidOnce() {
        var main = loadMain({usageHistoryEnabled: false, usageHistoryClearOwed: true})
        compare(ops(historyCommands(main)), ["clear"], "and nothing else")
        answer(main, clearOk)
        compare(Plasmoid.configuration.usageHistoryClearOwed, false)
        goodSnapshot(main, okClaude())
        wait(20)
        compare(ops(historyCommands(main)), ["clear"])
    }

    function test_nothingOwedAtStartRunsNothing() {
        var main = loadMain({usageHistoryEnabled: false, usageHistoryClearOwed: false})
        wait(20)
        compare(historyCommands(main), [])
    }

    function test_clearNotOwedWhenOnAtStart() {
        var main = loadMain({usageHistoryEnabled: true, usageHistoryClearOwed: true})
        compare(Plasmoid.configuration.usageHistoryClearOwed, false)
        compare(ops(historyCommands(main)), ["read"])
    }

    function test_turningOnAgainDropsTheDebt() {
        var main = mainClearing()
        answer(main, busy)
        Plasmoid.configuration.usageHistoryEnabled = true
        compare(Plasmoid.configuration.usageHistoryClearOwed, false)
        compare(main.historyNotice, "")
        wait(3200)
        compare(clearCount(main), 1, "the retry was called off")
    }

    function test_clearReplyAfterTurningOnChangesNothing() {
        var main = mainClearing()
        Plasmoid.configuration.usageHistoryEnabled = true
        answer(main, busy)
        compare(main.historyNotice, "")
        compare(main.historyClearTries, 0)
    }

    function test_popupOpenPaysTheDebt() {
        var main = mainClearing()
        answer(main, JSON.stringify({ok: false, error: "os-error"}))
        compare(clearCount(main), 1)
        main.expanded = true
        compare(clearCount(main), 2)
        answer(main, clearOk)
        compare(main.historyNotice, "", "the notice goes once it worked")
        compare(Plasmoid.configuration.usageHistoryClearOwed, false)
        main.expanded = false
        main.expanded = true
        compare(clearCount(main), 2, "nothing owed any more")
    }

    function test_popupOpenDoesNotPileUpClears() {
        var main = mainClearing()
        main.expanded = true
        compare(clearCount(main), 1, "one is running")
        main.expanded = false
        main.expanded = true
        compare(main.historyQueue.length, 0, "and none waits behind it")
        answer(main, clearOk)
        wait(20)
        compare(clearCount(main), 1)
        compare(Plasmoid.configuration.usageHistoryClearOwed, false)
    }

    // The clear waits behind a running record: opening adds no second one.
    function test_popupOpenDoesNotAddToAQueuedClear() {
        var main = loadMain({usageHistoryEnabled: true})
        answer(main, historyReply([]))
        compare(ops(historyCommands(main)), ["read", "record"])
        Plasmoid.configuration.usageHistoryEnabled = false
        main.expanded = true
        answer(main, historyReply([]))
        compare(clearCount(main), 1)
        answer(main, clearOk)
        wait(20)
        compare(clearCount(main), 1)
    }

    // A debt written back while history is on (a stale settings page) is
    // never paid by deleting history that is in use.
    function test_popupOpenNeverClearsWhileOn() {
        var main = loadMain({usageHistoryEnabled: true})
        answer(main, historyReply([]))
        answer(main, historyReply([]))
        Plasmoid.configuration.usageHistoryClearOwed = true
        main.expanded = true
        wait(20)
        compare(clearCount(main), 0)
    }

    function test_turningOnClearsTheNotice() {
        var main = mainClearing()
        answer(main, JSON.stringify({ok: false, error: "not-owned"}))
        compare(main.historyNotice, clearNotice)
        Plasmoid.configuration.usageHistoryEnabled = true
        compare(main.historyNotice, "")
    }

    // Off again starts a new count, and the old retry is called off.
    function test_turningOffAgainStartsOver() {
        var main = mainClearing()
        answer(main, busy)
        tryVerify(function () { return clearCount(main) === 2 }, 6000, "second try")
        answer(main, busy)
        compare(main.historyClearTries, 2)
        Plasmoid.configuration.usageHistoryEnabled = true
        Plasmoid.configuration.usageHistoryEnabled = false
        compare(clearCount(main), 3, "a fresh clear")
        answer(main, busy)
        compare(main.historyNotice, "", "the first of a new count")
        compare(main.historyClearTries, 1)
    }

    function test_turningOffAgainDropsTheOldRetry() {
        var main = mainClearing()
        answer(main, busy)
        Plasmoid.configuration.usageHistoryEnabled = true
        Plasmoid.configuration.usageHistoryEnabled = false
        compare(clearCount(main), 2, "the new clear")
        answer(main, clearOk)
        wait(3200)
        compare(clearCount(main), 2, "the old timer did not fire")
    }

    function test_popupOpenDuringRetryWaits() {
        var main = mainClearing()
        answer(main, busy)
        main.expanded = true
        compare(clearCount(main), 1, "the retry timer has it")
    }

    function test_pagesKeepTheDebtInStep() {
        [testCase.generalPageFile, testCase.usagePageFile,
         Qt.resolvedUrl("../../plasmoid/contents/ui/configChat.qml")].forEach(function (file) {
            var page = load(file, {})
            compare(page.cfg_usageHistoryClearOwed, false)
            Plasmoid.configuration.usageHistoryClearOwed = true
            compare(page.cfg_usageHistoryClearOwed, true, "so Apply can't write back an old value")
            page.destroy()
        })
    }

    function test_settingsOwedNotice() {
        var page = generalPage()
        var notice = generalPart(page, "usageHistoryOwedNotice")
        compare(notice.visible, false)
        compare(notice.textFormat, Text.PlainText)
        Plasmoid.configuration.usageHistoryClearOwed = true
        compare(notice.visible, true)
        page.cfg_usageHistoryEnabled = true
        compare(notice.visible, false, "history is on again in this page")
        page.cfg_usageHistoryEnabled = false
        pressDelete(page)
        answer(page, clearOk)
        compare(notice.visible, false, "deleted by hand")
    }

    // --- Tooltip error --------------------------------------------------------

    function test_tooltipErrorIsCapped() {
        var main = load(testCase.mainFile, {})
        verify(!main.hasData, "before any data")
        main.lastError = new Array(1000).join("x")
        var text = main.toolTipSubText
        verify(text.indexOf("Error: ") === 0, text.slice(0, 20))
        compare(text.length, "Error: ".length + 200)
        compare(text[text.length - 1], "…")
        main.lastError = "short"
        compare(main.toolTipSubText, "Error: short")
    }

    // --- Backup -------------------------------------------------------------

    function runningOn(owner, marker) {
        wait(0)
        var running = null
        sourcesOf(owner).forEach(function (source) {
            source.connectedSources.forEach(function (command) {
                if (command.indexOf(marker) >= 0)
                    running = {source: source, command: command}
            })
        })
        return running
    }

    function answerBackup(page, reply, exitCode) {
        var running = runningOn(page, "--settings-backup")
        verify(running, "a backup step is running")
        running.source.newData(running.command, {"exit code": exitCode === undefined ? 0 : exitCode, "stdout": reply})
        wait(0)
    }

    function backupCommands(page) {
        wait(0)
        var found = everyCommand(page).filter(function (command) { return command.indexOf("--settings-backup") >= 0 })
        found.forEach(namesTheWidget)
        return found
    }

    function backupOps(page) {
        return backupCommands(page).map(function (command) {
            return command.split("--settings-backup ")[1].split(" ")[0]
        })
    }

    readonly property string backupStamp: "2026-11-06T00:10:29Z"
    readonly property var goodBackup: ({
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

    // The settings page after its first status check.
    function backupPage(status) {
        var page = load(testCase.generalPageFile, {})
        compare(backupOps(page), ["status"])
        answerBackup(page, JSON.stringify(status === undefined ? {ok: true, exists: false} : status))
        return page
    }

    function importing(page, settings, dropped) {
        generalPart(page, "backupImport").clicked()
        answerBackup(page, JSON.stringify({ok: true, exported_at: backupStamp, settings: settings, dropped: dropped || 0}))
    }

    // The last export, which must be the fixed command and nothing more.
    function lastExport(page) {
        var commands = backupCommands(page).filter(function (command) { return command.indexOf(" export ") >= 0 })
        verify(commands.length > 0, "an export ran")
        var command = commands[commands.length - 1]
        verify(/^env HEARTHWIRE_RUN=[0-9]+ python3 -P -m hearthwire --settings-backup export --applet 7$/.test(command), command)
        return command
    }

    function test_backupStatusAbsent() {
        var page = backupPage({ok: true, exists: false})
        compare(generalPart(page, "backupStatus").text, "No backup yet.")
    }

    function test_backupStatusExists() {
        var page = backupPage({ok: true, exists: true, exported_at: backupStamp})
        compare(generalPart(page, "backupStatus").text, "Last backup: 2026-11-06 00:10:29 UTC")
        compare(generalPart(page, "backupStatus").textFormat, Text.PlainText)
    }

    function test_backupStatusErrorIsFixedText() {
        var page = backupPage({ok: false, error: "unsafe-mode"})
        compare(generalPart(page, "backupStatus").text,
                "The backup file isn't safe to use, so it was left alone. Check the owner and permissions of its folder.")
    }

    function test_backupExplanationIsPlain() {
        var label = generalPart(backupPage(), "backupExplanation")
        compare(label.textFormat, Text.PlainText)
        verify(label.text.indexOf("usage history") >= 0, "says what is left out")
    }

    function test_backupExportWithoutABackupRunsAtOnce() {
        var page = backupPage({ok: true, exists: false})
        generalPart(page, "backupExport").clicked()
        compare(backupOps(page), ["status", "export"])
        compare(page.confirmingExport, false)
    }

    function test_backupExportOverABackupAsksFirst() {
        var page = backupPage({ok: true, exists: true, exported_at: backupStamp})
        generalPart(page, "backupExport").clicked()
        compare(backupOps(page), ["status"], "nothing yet")
        var box = generalPart(page, "backupExportConfirm")
        compare(box.visible, true)
        box.actions[1].trigger()
        compare(page.confirmingExport, false)
        compare(backupOps(page), ["status"], "Cancel")
        generalPart(page, "backupExport").clicked()
        box.actions[0].trigger()
        compare(backupOps(page), ["status", "export"], "Replace")
    }

    // Unknown state: it may exist, so it is not replaced without asking.
    function test_backupExportAsksWhenStatusFailed() {
        var page = backupPage({ok: false, error: "os-error"})
        generalPart(page, "backupExport").clicked()
        compare(page.confirmingExport, true)
        compare(backupOps(page), ["status"])
    }

    // M1: the helper reads the applied settings itself; the page's values,
    // custom addresses included, never go on the command line.
    function test_backupExportSendsNoSettings() {
        var page = backupPage()
        page.cfg_usageHistoryEnabled = true
        page.cfg_chatSignInStorage = "encrypted"
        page.cfg_chatCustomUrls = JSON.stringify({claude: "https://private.example.org/secret-path"})
        page.cfg_chatOllamaUrl = "http://127.0.0.1:12345"
        generalPart(page, "backupExport").clicked()
        lastExport(page)
        everyCommand(page).forEach(function (command) {
            verify(command.indexOf("private.example.org") < 0 && command.indexOf("12345") < 0
                   && command.indexOf("7072697661746") < 0, command)
        })
        compare(page.backupSettings, undefined, "nothing gathers the page's values for an export")
    }

    function test_backupExportSaysApplied() {
        var page = backupPage({ok: true, exists: true, exported_at: backupStamp})
        verify(generalPart(page, "backupExplanation").text.indexOf("Export saves the applied settings: press Apply first") >= 0)
        verify(generalPart(page, "backupExplanation").text.indexOf("not yet applied on any page are not exported") >= 0)
        generalPart(page, "backupExport").clicked()
        compare(generalPart(page, "backupExportConfirm").text,
                "Replace the existing backup with the applied settings? Changes not yet applied are not exported.")
    }

    function test_backupExportResultAndNewStatus() {
        var page = backupPage()
        generalPart(page, "backupExport").clicked()
        answerBackup(page, JSON.stringify({ok: true, saved: 27, dropped: 1}))
        compare(generalPart(page, "backupMessage").text, "Backup saved.")
        compare(generalPart(page, "backupDroppedCount").text, "Settings left out: 1")
        compare(backupOps(page), ["status", "export", "status"])
    }

    function test_backupButtonsWaitWhileRunning() {
        var page = backupPage()
        var button = generalPart(page, "backupExport")
        button.clicked()
        compare(button.enabled, false)
        compare(generalPart(page, "backupImport").enabled, false)
    }

    function test_backupOneStepAtATime() {
        var page = backupPage()
        generalPart(page, "backupImport").clicked()
        page.runBackup("status")
        compare(backupOps(page), ["status", "import"], "a second step is refused while one runs")
    }

    function test_backupLateReplyIsIgnored() {
        var page = backupPage()
        generalPart(page, "backupImport").clicked()
        var running = runningOn(page, "--settings-backup")
        running.source.newData("env HEARTHWIRE_RUN=1 python3 -P -m hearthwire --settings-backup import",
                               {"exit code": 0, "stdout": JSON.stringify({ok: false, error: "invalid"})})
        wait(0)
        compare(generalPart(page, "backupMessage").text, "")
        compare(page.backupOp, "import")
    }

    function test_backupImportAsksBeforeApplying() {
        var page = backupPage()
        importing(page, {popupSize: "large"}, 2)
        compare(page.cfg_popupSize, "normal", "nothing applied yet")
        compare(generalPart(page, "backupImportConfirm").visible, true)
        var label = generalPart(page, "backupPlanLabel")
        compare(label.text, "Settings to apply: 1. Saved: 2026-11-06 00:10:29 UTC.")
        compare(label.textFormat, Text.PlainText)
        compare(generalPart(page, "backupDroppedCount").text, "Settings left out: 2")
    }

    function test_backupCancelAppliesNothing() {
        var page = backupPage()
        importing(page, {popupSize: "large"})
        generalPart(page, "backupImportConfirm").actions[1].trigger()
        compare(page.cfg_popupSize, "normal")
        compare(page.backupPlan, null)
        compare(page.confirmingImport, false)
    }

    function test_backupApplyWithoutAPlanDoesNothing() {
        var page = backupPage()
        page.applyBackup()
        compare(generalPart(page, "backupMessage").text, "")
    }

    // Every backup key, through the real page's cfg_ properties and back out.
    function test_backupRoundTripsEveryKey() {
        var page = backupPage()
        importing(page, goodBackup)
        generalPart(page, "backupImportConfirm").actions[0].trigger()
        compare(generalPart(page, "backupMessage").text, "Backup loaded. Press Apply to save it.")
        for (var key in goodBackup)
            compare(page["cfg_" + key], goodBackup[key], key)
        compare(Object.keys(goodBackup).length, 28, "the fixture is complete")
        // The page shows what it took over.
        compare(generalPart(page, "middleClickChoice").currentValue, "mscopilot")
        // Out again is the helper's part (it reads the applied settings).
        generalPart(page, "backupExport").clicked()
        generalPart(page, "backupExportConfirm").actions[0].trigger()
        lastExport(page)
    }

    function test_backupKeysAllHaveAcfgProperty() {
        var page = backupPage()
        Object.keys(goodBackup).forEach(function (key) {
            verify(("cfg_" + key) in page, key)
            verify(Plasmoid.configuration[key] !== undefined, key + " is in main.xml")
        })
    }

    function test_backupNeverTurnsHistoryOn() {
        var page = backupPage()
        importing(page, {usageHistoryEnabled: true, usageHistoryClearOwed: true, chatSignInStorage: "encrypted",
                         chatVaultUnlock: "wallet", chatSiteZoom: "{\"claude\":2}", popupSize: "large"})
        compare(page.backupPlan.applied, 1)
        generalPart(page, "backupImportConfirm").actions[0].trigger()
        compare(page.cfg_usageHistoryEnabled, false)
        compare(page.cfg_usageHistoryClearOwed, false)
        compare(page.cfg_chatSignInStorage, "memory")
        compare(page.cfg_chatVaultUnlock, "passphrase")
        compare(page.cfg_chatSiteZoom, "{}")
        compare(page.cfg_popupSize, "large")
        compare(generalPart(page, "backupDroppedCount").text, "Settings left out: 5")
    }

    function test_backupImportChecksAgainInTheWidget() {
        var page = backupPage()
        importing(page, {chatOllamaUrl: "http://192.168.1.2:11434",
                         chatCustomUrls: JSON.stringify({claude: "http://claude.example.org/"}),
                         popupSize: "large"})
        compare(page.backupPlan.applied, 1, "only the good one")
        generalPart(page, "backupImportConfirm").actions[0].trigger()
        compare(page.cfg_chatOllamaUrl, "http://127.0.0.1:11434")
        compare(page.cfg_chatCustomUrls, "{}")
        compare(generalPart(page, "backupDroppedCount").text, "Settings left out: 2")
    }

    function test_backupImportWithNothingUsable() {
        var page = backupPage()
        importing(page, {usageHistoryEnabled: true})
        compare(page.confirmingImport, false)
        compare(generalPart(page, "backupMessage").text, "The backup has no settings that can be used.")
    }

    function checkBackupError(reply, exitCode, expected) {
        var page = backupPage()
        generalPart(page, "backupImport").clicked()
        answerBackup(page, reply, exitCode)
        var label = generalPart(page, "backupMessage")
        compare(label.text, expected)
        compare(label.textFormat, Text.PlainText)
        compare(page.confirmingImport, false)
    }

    function test_backupErrorsAreFixedText() {
        var cases = [
            ["absent", "There is no backup yet."],
            ["invalid", "The backup file is damaged and can't be read."],
            ["unsupported", "The backup was made by a different version and can't be read."],
            ["too-large", "The settings are too large to back up."],
            ["bad-data", "These settings couldn't be backed up."],
            ["symlink", "The backup file isn't safe to use, so it was left alone. Check the owner and permissions of its folder."],
            ["not-owned", "The backup file isn't safe to use, so it was left alone. Check the owner and permissions of its folder."],
            ["unsafe-mode", "The backup file isn't safe to use, so it was left alone. Check the owner and permissions of its folder."],
            ["legacy-data", "Saved sign-ins from the previous version haven't been moved yet. Run the installer again with --restart-plasma."],
            ["os-error", "Something went wrong with the backup. Nothing was changed."],
            ["applet-not-found", "This widget's applied settings weren't found. Press Apply, then try again. Nothing was changed."],
            ["settings-unreadable", "Plasma's settings file for this widget couldn't be read safely, so nothing was exported. Check the owner and type of ~/.config/plasma-org.kde.plasma.desktop-appletsrc."]
        ]
        cases.forEach(function (entry) {
            checkBackupError(JSON.stringify({ok: false, error: entry[0]}), 0, entry[1])
        })
    }

    function test_backupNeverShowsHelperText() {
        checkBackupError("/home/soul/.config boom <b>secret</b>", 1, "Something went wrong with the backup. Nothing was changed.")
        checkBackupError(JSON.stringify({ok: false, error: "/home/soul secret"}), 0, "Something went wrong with the backup. Nothing was changed.")
    }

    // --- Audit fixes: the widget's id on every step -------------------------

    readonly property string noAppletHistory: "This widget couldn't be identified, so its usage history can't be used."
    readonly property string noAppletBackup: "This widget couldn't be identified, so the backup can't be used. Nothing was changed."
    readonly property string emptyRead: JSON.stringify({ok: true, history_version: 1, bucket_seconds: 3600,
                                                        now: nowSeconds(), series: []})

    // L1: each history step is this widget's, whatever its id is.
    function test_historyStepsNameTheWidget() {
        Plasmoid.id = 42
        var main = loadMain({usageHistoryEnabled: true})
        answer(main, historyReply([]))
        Plasmoid.configuration.usageHistoryEnabled = false
        answer(main, clearOk)
        var commands = historyCommands(main)
        compare(ops(commands), ["read", "record", "clear"])
        verify(/^env HEARTHWIRE_RUN=[0-9]+ python3 -P -m hearthwire --usage-history read --applet 42$/.test(commands[0]), commands[0])
        verify(/^env HEARTHWIRE_RUN=[0-9]+ python3 -P -m hearthwire --usage-history record --applet 42 --sample [a-z_.=0-9,]+$/.test(commands[1]), commands[1])
        verify(/^env HEARTHWIRE_RUN=[0-9]+ python3 -P -m hearthwire --usage-history clear --applet 42$/.test(commands[2]), commands[2])
    }

    function test_historyWithoutAWidgetIdRunsNothing() {
        Plasmoid.id = 0
        var main = loadMain({usageHistoryEnabled: true})
        goodSnapshot(main, okClaude())
        main.expanded = true
        wait(20)
        compare(historyCommands(main), [])
        compare(main.historyQueue, [], "nothing waits for an id either")
        compare(main.historyNotice, noAppletHistory)
        Plasmoid.configuration.usageHistoryEnabled = false
        wait(20)
        compare(historyCommands(main), [], "not even the clear")
        compare(Plasmoid.configuration.usageHistoryClearOwed, true, "still owed")
        compare(main.historyNotice, noAppletHistory, "and said")
    }

    function test_historyOwedClearWithoutAWidgetIdRunsNothing() {
        Plasmoid.id = -1
        var main = loadMain({usageHistoryClearOwed: true})
        main.expanded = true
        wait(20)
        compare(historyCommands(main), [])
        compare(main.historyNotice, noAppletHistory)
    }

    function test_historyNoNoticeWithoutAWidgetIdWhileOff() {
        Plasmoid.id = 0
        var main = loadMain({})
        compare(main.historyNotice, "", "history isn't used, nothing to say")
    }

    // The popup opens: history is read again, one read at a time.
    function test_historyRereadWhenThePopupOpens() {
        var main = loadMain({usageHistoryEnabled: true})
        answer(main, historyReply([]))
        answer(main, historyReply([]))
        compare(ops(historyCommands(main)), ["read", "record"])
        main.expanded = true
        compare(ops(historyCommands(main)), ["read", "record", "read"])
        main.expanded = false
        main.expanded = true
        compare(ops(historyCommands(main)), ["read", "record", "read"], "one is running")
        compare(main.historyQueue.length, 0, "and none waits behind it")
        answer(main, historyReply([]))
        main.expanded = false
        main.expanded = true
        compare(ops(historyCommands(main)), ["read", "record", "read", "read"])
    }

    function test_historyNoRereadBeforeTheFirstRead() {
        var main = loadMain({usageHistoryEnabled: true})
        compare(ops(historyCommands(main)), ["read"])
        main.expanded = true
        wait(20)
        compare(ops(historyCommands(main)), ["read"])
        compare(main.historyQueue.map(function (job) { return job.op }), ["record"], "no second read waits")
    }

    function test_historyNoRereadWhileOff() {
        var main = loadMain({})
        main.expanded = true
        wait(20)
        compare(historyCommands(main), [])
        var hidden = loadMain({usageHistoryEnabled: true, showUsageTab: false})
        hidden.expanded = true
        wait(20)
        compare(historyCommands(hidden), [], "nor without the Usage tab")
    }

    // Settings → Delete usage history, then the popup opens: the old lines go.
    function test_historyDeleteThenOpenDropsStaleLines() {
        var shown = sparklineMain({})
        var sparks = []
        tryVerify(function () {
            sparks = allNamed(shown.full, "usageSparkline").filter(function (item) { return item.visible })
            return sparks.length === 1
        }, 5000, "a line before the delete")
        var page = generalPage()
        pressDelete(page)
        verify(/ --usage-history clear --applet 7$/.test(historyCommands(page)[0]), "this widget's history")
        answer(page, clearOk)
        shown.main.expanded = true
        answer(shown.main, emptyRead)
        compare(shown.main.historyPoints("claude", "weekly"), [])
        tryCompare(sparks[0], "visible", false)
    }

    function test_settingsWithoutAWidgetIdRunsNothing() {
        Plasmoid.id = 0
        var page = load(testCase.generalPageFile, {})
        wait(0)
        compare(backupCommands(page), [])
        compare(generalPart(page, "backupStatus").text, noAppletBackup)
        generalPart(page, "backupExport").clicked()
        generalPart(page, "backupExportConfirm").actions[0].trigger()
        compare(generalPart(page, "backupMessage").text, noAppletBackup)
        generalPart(page, "backupImport").clicked()
        compare(backupCommands(page), [])
        compare(page.confirmingImport, false)
        var button = generalPart(page, "usageHistoryDelete")
        button.clicked()
        compare(historyCommands(page), [])
        compare(generalPart(page, "usageHistoryStatus").text,
                "This widget couldn't be identified, so its usage history can't be deleted.")
        compare(button.enabled, true, "not left busy")
    }

    // I3: Replace lists each chat address it would change, old → new.
    function test_backupImportListsAddressChanges() {
        var page = backupPage()
        page.cfg_chatCustomUrls = JSON.stringify({claude: "https://old.example.org/"})
        page.cfg_chatOllamaUrl = "http://127.0.0.1:11434"
        importing(page, {chatCustomUrls: JSON.stringify({chatgpt: "https://new.example.org/"}),
                         chatOllamaUrl: "http://[::1]:11434", popupSize: "large"})
        var label = generalPart(page, "backupAddressChanges")
        compare(label.visible, true)
        compare(label.textFormat, Text.PlainText)
        compare(label.text, ["This changes 3 chat addresses:",
                             "Claude: https://old.example.org/ → " + ChatSites.homeUrl("claude", {}),
                             "ChatGPT: " + ChatSites.homeUrl("chatgpt", {}) + " → https://new.example.org/",
                             "Ollama: http://127.0.0.1:11434 → http://[::1]:11434"].join("\n"))
        generalPart(page, "backupImportConfirm").actions[1].trigger()
        compare(label.visible, false, "Cancel")
        compare(page.backupAddressChanges, [])
        compare(page.cfg_chatCustomUrls, JSON.stringify({claude: "https://old.example.org/"}), "nothing applied")
    }

    function test_backupImportWithoutAddressChangesListsNone() {
        var page = backupPage()
        importing(page, {popupSize: "large", chatOllamaUrl: page.cfg_chatOllamaUrl})
        compare(page.confirmingImport, true)
        compare(generalPart(page, "backupAddressChanges").visible, false)
    }

    function test_backupAddressChangesGoAfterReplace() {
        var page = backupPage()
        importing(page, {chatOllamaUrl: "http://[::1]:11434"})
        compare(generalPart(page, "backupAddressChanges").text,
                "This changes 1 chat address:\nOllama: " + page.cfg_chatOllamaUrl + " → http://[::1]:11434")
        generalPart(page, "backupImportConfirm").actions[0].trigger()
        compare(page.cfg_chatOllamaUrl, "http://[::1]:11434")
        compare(generalPart(page, "backupAddressChanges").visible, false)
    }

    // Each value capped; past the first eight a count. The text never links.
    function test_backupAddressChangesCappedAndCounted() {
        var page = backupPage()
        var long = "https://" + new Array(1500).join("a") + ".example.org/"
        page.cfg_chatCustomUrls = JSON.stringify({claude: long})
        importing(page, {chatCustomUrls: "{}"})
        var line = generalPart(page, "backupAddressChanges").text.split("\n")[1]
        verify(line.length < 500, "capped: " + line.length)
        verify(line.indexOf("\u2026 → ") > 0, line)
        var many = []
        for (var index = 0; index < 11; index++)
            many.push({id: "claude", from: "https://a.example.org/", to: "https://b.example.org/<a href=x>"})
        var lines = page.addressChangeText(many).split("\n")
        compare(lines.length, 10)
        compare(lines[0], "This changes 11 chat addresses:")
        compare(lines[9], "…and 3 more.")
    }

    // L2: Plasma's Apply and OK call the page's saveConfig() first; then
    // "press Apply" is no longer true.
    function test_settingsApplyClearsTheLoadedBackupNote() {
        var page = backupPage()
        importing(page, {popupSize: "large"})
        generalPart(page, "backupImportConfirm").actions[0].trigger()
        var label = generalPart(page, "backupMessage")
        compare(label.text, "Backup loaded. Press Apply to save it.")
        verify(page.saveConfig, "the hook Plasma looks for")
        page.saveConfig()
        compare(label.text, "")
        compare(label.visible, false)
        compare(page.cfg_popupSize, "large", "the loaded value is what Apply saves")
    }

    function test_settingsApplyKeepsOtherBackupResults() {
        var page = backupPage()
        generalPart(page, "backupExport").clicked()
        answerBackup(page, JSON.stringify({ok: true, saved: 27, dropped: 1}))
        answerBackup(page, JSON.stringify({ok: true, exists: true, exported_at: backupStamp}))
        page.saveConfig()
        compare(generalPart(page, "backupMessage").text, "Backup saved.")
        compare(generalPart(page, "backupDroppedCount").text, "Settings left out: 1")
        generalPart(page, "backupImport").clicked()
        answerBackup(page, JSON.stringify({ok: false, error: "invalid"}))
        page.saveConfig()
        compare(generalPart(page, "backupMessage").text, "The backup file is damaged and can't be read.")
    }

    // Every visible text and control under the page's flickable.
    function shownParts(item, found) {
        found = found || []
        if (!item || !item.visible)
            return found
        if (item instanceof Text || item instanceof QQC2.Control)
            found.push(item)
        var kids = item.children || []
        for (var index = 0; index < kids.length; index++)
            shownParts(kids[index], found)
        return found
    }

    // The parts that reach past the scrollable content width (the
    // flickable, which the org.kde.desktop style keeps clear of the
    // scrollbar, less the page's own padding).
    function partsPastTheEdge(page) {
        var flickable = page.flickable
        var right = flickable.width - page.rightPadding
        return shownParts(flickable.contentItem).filter(function (part) {
            var at = part.mapToItem(flickable, 0, 0)
            return at.x < page.leftPadding - 0.5 || at.x + part.width > right + 0.5
        }).map(function (part) {
            var at = part.mapToItem(flickable, 0, 0)
            return (part.objectName || String(part).split("(")[0]) + " " + String(part.text).slice(0, 24)
                + ": " + Math.round(at.x) + " + " + Math.round(part.width) + " > " + right
        })
    }

    // L1: the long help texts and the inline messages wrap inside the page,
    // at about the settings dialog's default page width (45 grid units less
    // the 7 of its sidebar), a little narrower, and at its smallest (30 less 7).
    function test_settingsGeneralTextFitsThePage_data() {
        return [{tag: "default", units: 38}, {tag: "narrower", units: 35}, {tag: "smallest", units: 23}]
    }

    function test_settingsGeneralTextFitsThePage(data) {
        var page = backupPage({ok: true, exists: true, exported_at: backupStamp})
        page.width = Kirigami.Units.gridUnit * data.units - 1
        page.height = Kirigami.Units.gridUnit * 30
        // Every confirmation and long message at once.
        page.cfg_usageHistoryClearOwed = true
        page.historyClearState = "no-applet"
        page.confirmingWalletOff = true
        page.confirmingOff = true
        page.showFolderActions = true
        page.confirmingDelete = true
        page.vaultMessage = "wallet-off"
        page.confirmingExport = true
        importing(page, {chatOllamaUrl: "http://[::1]:11434", popupSize: "large"}, 2)
        page.backupMessage = "settings-unreadable"
        wait(100)
        var named = ["usageHistoryExplanation", "usageHistoryStatus", "usageHistoryOwedNotice", "walletOffConfirm",
                     "backupExplanation", "backupExportConfirm", "backupImportConfirm", "backupAddressChanges",
                     "backupMessage"]
        named.forEach(function (name) { verify(generalPart(page, name).visible, name + " is shown") })
        verify(generalPart(page, "usageHistoryExplanation").lineCount > 2, "it wraps")
        verify(generalPart(page, "backupExplanation").lineCount > 2, "it wraps")
        verify(shownParts(page.flickable.contentItem).length > 40, "the walk sees the page")
        compare(partsPastTheEdge(page), [])
    }
}
