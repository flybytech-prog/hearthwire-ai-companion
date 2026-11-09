import QtQuick
import QtTest
import HearthwireStubs
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as Plasma5Support
import org.kde.notification
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
        compare(sources.length, 4, "usage, library, dropped and storage sources")
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
}
