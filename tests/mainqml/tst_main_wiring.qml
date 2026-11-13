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
    readonly property url chatPageFile: Qt.resolvedUrl("../../plasmoid/contents/ui/configChat.qml")
    // ChatView's web view in the real popup: the stub, no Qt WebEngine.
    readonly property url chatWebStub: Qt.resolvedUrl("../qml/ChatWebStub.qml")
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
        compare(sources.length, 6, "usage, history, library, dropped, install info and storage sources")
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
        compare(sourcesOf(page).length, 4, "the vault's, the install info's, the delete button's and the backup's")
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

    // The short line stays shown; the rest is in the "?" beside the box.
    function test_settingsExplanationIsPlainAndSaysWhere() {
        var page = generalPage()
        var label = generalPart(page, "usageHistoryExplanation")
        compare(label.textFormat, Text.PlainText)
        compare(label.text, "Only on this computer. Turning it off and applying deletes this widget's history.")
        var help = generalPart(page, "usageHistoryHelp")
        compare(help.parent, generalPart(page, "usageHistoryChoice").parent, "beside the box")
        var text = help.toolTipText
        verify(text.indexOf("usage-history") >= 0, "where")
        verify(text.indexOf("percent used") >= 0, "what")
        verify(text.indexOf("Each widget keeps its own history.") >= 0, "per widget")
        verify(text.indexOf("saved at most every 15 minutes, keeping one value per hour") >= 0, "how often")
        verify(text.indexOf("once per hour") < 0, "not the old wording")
        verify(text.indexOf("No names, plans, amounts or accounts are saved.") >= 0, "what is not kept")
        verify(text.indexOf("Delete usage history deletes it at once.") >= 0, "the button")
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

    // The "?" follows the status text, as on every other row: right after a
    // short status, and top-aligned beside a long one that wraps.
    function test_backupHelpFollowsTheStatus_data() {
        var unsafe = {ok: false, error: "unsafe-mode"}
        return [{tag: "short", status: {ok: true, exists: false}, units: 38, wraps: false},
                {tag: "long", status: unsafe, units: 38, wraps: true},
                {tag: "long smallest", status: unsafe, units: 23, wraps: true}]
    }

    function test_backupHelpFollowsTheStatus(data) {
        var page = backupPage(data.status)
        page.width = Kirigami.Units.gridUnit * data.units - 1
        page.height = Kirigami.Units.gridUnit * 30
        wait(100)
        var label = generalPart(page, "backupStatus")
        var help = generalPart(page, "backupHelp")
        compare(label.lineCount > 1, data.wraps, "wraps only when long")
        var shown = Math.min(label.implicitWidth, label.width)
        var at = label.mapToItem(label.parent, 0, 0)
        var helpAt = help.mapToItem(label.parent, 0, 0)
        fuzzyCompare(helpAt.x, at.x + shown + label.parent.spacing, 1, "right after the text")
        fuzzyCompare(helpAt.y, at.y, 1, "top-aligned")
        verify(helpAt.x + help.width <= label.parent.width + 0.5, "not clipped")
        compare(partsPastTheEdge(page), [])
    }

    // The short line stays shown; where and what is in the "?" beside the status.
    function test_backupExplanationIsPlain() {
        var page = backupPage()
        var label = generalPart(page, "backupExplanation")
        compare(label.textFormat, Text.PlainText)
        compare(label.text, "Export saves the applied settings: press Apply first.")
        var help = generalPart(page, "backupHelp")
        compare(help.parent, generalPart(page, "backupStatus").parent, "beside the status")
        compare(help.toolTipText, "One file on this computer, in the hearthwire folder of your configuration folder (usually ~/.config). It holds these settings, including your custom chat addresses. Sign-ins, the encrypted folder, zoom and the usage history setting are not part of it.")
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
        compare(generalPart(page, "backupExplanation").text, "Export saves the applied settings: press Apply first.")
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
        answerInstall(page, installReply({user_helper: true}))
        wait(100)
        var named = ["installShadowedNotice", "installShadowedCommand", "usageHistoryHelp", "usageHistoryExplanation",
                     "usageHistoryStatus", "usageHistoryOwedNotice", "walletOffConfirm", "backupStatus", "backupHelp",
                     "backupExplanation", "backupExportConfirm", "backupImportConfirm", "backupAddressChanges",
                     "backupMessage"]
        named.forEach(function (name) { verify(generalPart(page, name).visible, name + " is shown") })
        compare(generalPart(page, "usageHistoryExplanation").text,
                "Only on this computer. Turning it off and applying deletes this widget's history.")
        compare(generalPart(page, "backupExplanation").text, "Export saves the applied settings: press Apply first.")
        verify(generalPart(page, "usageHistoryHelp").toolTipText.indexOf("usage-history") >= 0, "the moved text")
        verify(generalPart(page, "backupHelp").toolTipText.indexOf("~/.config") >= 0, "the moved text")
        verify(shownParts(page.flickable.contentItem).length > 40, "the walk sees the page")
        compare(partsPastTheEdge(page), [])
    }

    // --- Install info: a script install shadowing the package ---------------

    readonly property string installPattern:
        "^env HEARTHWIRE_RUN=[0-9]+ HEARTHWIRE_APPLET=7 python3 -P -s -m hearthwire --install-info$"
    // The one retry after a failed -s run (a script install alone).
    readonly property string installRetryPattern:
        "^env HEARTHWIRE_RUN=[0-9]+ HEARTHWIRE_APPLET=7 python3 -P -m hearthwire --install-info$"
    readonly property string popupInstallNotice: "A script install of Hearthwire is running instead of the installed package. To fix it, run ./scripts/install.sh --remove-script-install from the Hearthwire source folder, then restart Plasma. Your settings and data are kept."
    readonly property string settingsInstallNotice: "A script install of Hearthwire is running instead of the installed package. To use the package, run ./scripts/install.sh --remove-script-install from the Hearthwire source folder, then restart Plasma. Your settings, usage history and saved sign-ins are kept."

    function installCommands(owner) {
        wait(0)
        return everyCommand(owner).filter(function (command) { return command.indexOf("--install-info") >= 0 })
    }

    function answerInstall(owner, reply, exitCode) {
        var running = runningOn(owner, "--install-info")
        verify(running, "the install info check is running")
        running.source.newData(running.command, {"exit code": exitCode === undefined ? 0 : exitCode, "stdout": reply})
        wait(0)
    }

    // The contract's reply: a system package alone, on Arch, unless changed.
    function installReply(changes) {
        var value = {ok: true, install_info_version: 1, helper: "system", system_helper: true,
                     user_helper: false, user_plasmoid: false, system_plasmoid: true, distro: "arch"}
        for (var key in changes)
            value[key] = changes[key]
        return JSON.stringify(value)
    }

    // Each combination of the four flags, and replies that mean unknown.
    function installRows() {
        var rows = []
        for (var bits = 0; bits < 16; bits++) {
            var flags = {user_helper: !!(bits & 1), system_helper: !!(bits & 2),
                         user_plasmoid: !!(bits & 4), system_plasmoid: !!(bits & 8)}
            rows.push({tag: "flags " + bits, reply: installReply(flags), exitCode: 0,
                       shown: (flags.user_helper && flags.system_helper)
                              || (flags.user_plasmoid && flags.system_plasmoid)})
        }
        var shadowed = {user_helper: true, user_plasmoid: true}
        rows.push({tag: "exit code 1", reply: installReply(shadowed), exitCode: 1, shown: false})
        rows.push({tag: "old helper", reply: "", exitCode: 2, shown: false})
        rows.push({tag: "os-error", reply: JSON.stringify({ok: false, error: "os-error"}), exitCode: 0, shown: false})
        rows.push({tag: "extra key", reply: installReply({user_helper: true, path: "/home/x"}), exitCode: 0, shown: false})
        rows.push({tag: "later version", reply: installReply({user_helper: true, install_info_version: 2}), exitCode: 0,
                   shown: false})
        rows.push({tag: "text flag", reply: installReply({user_helper: "true"}), exitCode: 0, shown: false})
        rows.push({tag: "not json", reply: "usage: hearthwire [-h] <b>boom</b>", exitCode: 0, shown: false})
        rows.push({tag: "no reply", reply: null, exitCode: 0, shown: false})
        return rows
    }

    function installPopup(main) {
        var full = createTemporaryObject(main.fullRepresentation, main, {width: 600, height: 800})
        verify(full, "the real popup")
        return full
    }

    // Once at start, the fixed command; nothing later runs it again.
    function test_installInfoRunsOnceAtStart() {
        var main = loadMain({})
        var commands = installCommands(main)
        compare(commands.length, 1, "once")
        verify(new RegExp(testCase.installPattern).test(commands[0]), commands[0])
        main.expanded = true
        main.refresh()
        main.expanded = false
        main.expanded = true
        answerInstall(main, installReply({}))
        main.checkInstall()
        main.expanded = false
        main.expanded = true
        compare(installCommands(main).length, 1, "still once")
        compare(runningOn(main, "--install-info"), null, "and done")
    }

    // Also with the Usage tab hidden: the install hints need the distro.
    function test_installInfoRunsWithoutTheUsageTab() {
        var main = loadMain({showUsageTab: false})
        compare(installCommands(main).length, 1)
    }

    function test_installNoticeInThePopup_data() {
        return installRows()
    }

    function test_installNoticeInThePopup(data) {
        var main = loadMain({showChatTab: false})
        var full = installPopup(main)
        var notice = null
        tryVerify(function () {
            notice = allNamed(full, "usageInstallNotice")[0] || null
            return notice !== null
        }, 5000, "the Usage tab is built")
        compare(notice.visible, false, "not before the reply")
        if (data.reply !== null)
            answerInstall(main, data.reply, data.exitCode)
        compare(main.installShadowed, data.shown)
        compare(notice.visible, data.shown)
        compare(notice.text, testCase.popupInstallNotice)
        compare(notice.textFormat, Text.PlainText)
    }

    function test_installNoticeInSettings_data() {
        return installRows()
    }

    function test_installNoticeInSettings(data) {
        var page = generalPage()
        var commands = installCommands(page)
        compare(commands.length, 1, "once per page open")
        verify(new RegExp(testCase.installPattern).test(commands[0]), commands[0])
        var notice = generalPart(page, "installShadowedNotice")
        var command = generalPart(page, "installShadowedCommand")
        compare(notice.visible, false, "not before the reply")
        if (data.reply !== null)
            answerInstall(page, data.reply, data.exitCode)
        tryCompare(notice, "visible", data.shown)
        compare(command.visible, data.shown)
        compare(notice.text, testCase.settingsInstallNotice)
        compare(notice.type, Kirigami.MessageType.Warning)
        compare(notice.actions.length, 0, "nothing to click")
        compare(command.text, "./scripts/install.sh --remove-script-install")
        compare(command.readOnly, true)
        page.checkInstall()
        // A failed first run is asked once more without -s.
        compare(installCommands(page).length, data.exitCode !== 0 ? 2 : 1, "no more runs")
    }

    function test_installNoticeIsTheFirstSettingsPart() {
        var page = generalPage()
        page.width = Kirigami.Units.gridUnit * 38
        page.height = Kirigami.Units.gridUnit * 30
        answerInstall(page, installReply({user_plasmoid: true}))
        var notice = generalPart(page, "installShadowedNotice")
        tryCompare(notice, "visible", true)
        wait(100)
        var content = page.flickable.contentItem
        var top = notice.mapToItem(content, 0, 0).y
        var above = shownParts(content).filter(function (part) {
            return part.mapToItem(content, 0, 0).y < top - 0.5
        }).map(function (part) { return part.objectName || String(part).split("(")[0] })
        verify(shownParts(content).length > 40, "the walk sees the page")
        compare(above, [], "at the top of Settings → General")
    }

    readonly property var everyTool: ["gocryptfs", "gocryptfs-v2", "kdialog", "fusermount3", "kwallet-query", "qdbus6", "openssl"]

    function test_installHintsPerDistroInSettings_data() {
        return [
            {tag: "unknown", reply: null, vault: "gocryptfs kdialog fusermount3 kwallet-query qdbus6 openssl",
             wallet: "kwallet-query qdbus6 openssl"},
            {tag: "arch", reply: installReply({distro: "arch"}),
             vault: "sudo pacman -S --needed gocryptfs kdialog fuse3 kwallet qt6-tools openssl",
             wallet: "sudo pacman -S --needed kwallet qt6-tools openssl"},
            {tag: "fedora", reply: installReply({distro: "fedora"}),
             vault: "sudo dnf install gocryptfs kdialog fuse3 kf6-kwallet qt6-qttools openssl",
             wallet: "sudo dnf install kf6-kwallet qt6-qttools openssl"},
            {tag: "debian", reply: installReply({distro: "debian"}),
             vault: "sudo apt install gocryptfs kdialog fuse3 kwallet6 qdbus-qt6 openssl",
             wallet: "sudo apt install kwallet6 qdbus-qt6 openssl"},
            {tag: "other", reply: installReply({distro: "other"}),
             vault: "gocryptfs kdialog fusermount3 kwallet-query qdbus6 openssl",
             wallet: "kwallet-query qdbus6 openssl"},
            {tag: "odd reply", reply: installReply({distro: "ubuntu"}),
             vault: "gocryptfs kdialog fusermount3 kwallet-query qdbus6 openssl",
             wallet: "kwallet-query qdbus6 openssl"}
        ]
    }

    function test_installHintsPerDistroInSettings(data) {
        var page = generalPage()
        page.vaultMissing = testCase.everyTool
        if (data.reply !== null)
            answerInstall(page, data.reply)
        compare(generalPart(page, "vaultInstallCommand").text, data.vault)
        compare(generalPart(page, "walletInstallCommand").text, data.wallet)
    }

    function test_installHintsPerDistroInThePopup_data() {
        return [
            {tag: "unknown", reply: null, command: "fusermount3 qdbus6"},
            {tag: "arch", reply: installReply({distro: "arch"}), command: "sudo pacman -S --needed fuse3 qt6-tools"},
            {tag: "fedora", reply: installReply({distro: "fedora"}), command: "sudo dnf install fuse3 qt6-qttools"},
            {tag: "debian", reply: installReply({distro: "debian"}), command: "sudo apt install fuse3 qdbus-qt6"},
            {tag: "other", reply: installReply({distro: "other"}), command: "fusermount3 qdbus6"},
            {tag: "odd reply", reply: installReply({distro: "arch", extra: 1}), command: "fusermount3 qdbus6"}
        ]
    }

    function test_installHintsPerDistroInThePopup(data) {
        var main = loadMain({})
        if (data.reply !== null)
            answerInstall(main, data.reply)
        main.chatVaultMissing = ["qdbus6", "fusermount3"]
        var full = installPopup(main)
        var field = null
        tryVerify(function () {
            field = allNamed(full, "chatInstallCommand")[0] || null
            return field !== null
        }, 5000, "the Chat tab is built")
        compare(field.text, data.command)
    }

    // A late or foreign reply on the source changes nothing.
    function test_installInfoForeignReplyIsIgnored() {
        var main = loadMain({})
        var running = runningOn(main, "--install-info")
        verify(running)
        running.source.newData(running.command + " x", {"exit code": 0, "stdout": installReply({user_helper: true})})
        wait(0)
        compare(main.installShadowed, false)
        answerInstall(main, installReply({}))
        running.source.newData(running.command, {"exit code": 0, "stdout": installReply({user_helper: true})})
        wait(0)
        compare(main.installShadowed, false, "only the first reply counts")
    }

    // --- Install info retry without -s (lab M1) ------------------------------

    // The widget or the settings page, with its Arch hint field.
    function installOwner(kind) {
        if (kind === "main") {
            var main = loadMain({})
            main.chatVaultMissing = ["fusermount3"]
            var full = installPopup(main)
            var field = null
            tryVerify(function () {
                field = allNamed(full, "chatInstallCommand")[0] || null
                return field !== null
            }, 5000, "the Chat tab is built")
            return {owner: main, hint: field, shadowed: function () { return main.installShadowed }}
        }
        var page = generalPage()
        page.vaultMissing = ["fusermount3"]
        var notice = generalPart(page, "installShadowedNotice")
        return {owner: page, hint: generalPart(page, "vaultInstallCommand"),
                shadowed: function () { return notice.visible }}
    }

    function test_installRetryWithoutS_data() {
        return [
            {tag: "widget", kind: "main", reply: installReply({helper: "user", system_helper: false, user_helper: true,
                                                               system_plasmoid: false, user_plasmoid: true}),
             shown: false},
            {tag: "settings", kind: "settings", reply: installReply({helper: "user", system_helper: false,
                                                                     user_helper: true, system_plasmoid: false,
                                                                     user_plasmoid: true}),
             shown: false},
            // The notice comes from the reply that parsed, the retry's.
            {tag: "widget shadowed", kind: "main", reply: installReply({user_plasmoid: true}), shown: true},
            {tag: "settings shadowed", kind: "settings", reply: installReply({user_plasmoid: true}), shown: true}
        ]
    }

    // No system package: the -s run exits 1, the retry without -s answers.
    function test_installRetryWithoutS(data) {
        var shown = installOwner(data.kind)
        compare(shown.hint.text, "fusermount3", "generic before any reply")
        answerInstall(shown.owner, "", 1)
        var commands = installCommands(shown.owner)
        compare(commands.length, 2, "one retry")
        verify(new RegExp(testCase.installPattern).test(commands[0]), commands[0])
        verify(new RegExp(testCase.installRetryPattern).test(commands[1]), commands[1])
        compare(shown.hint.text, "fusermount3", "still generic while the retry runs")
        answerInstall(shown.owner, data.reply)
        compare(shown.owner.installDistro, "arch")
        compare(shown.hint.text, "sudo pacman -S --needed fuse3")
        tryVerify(function () { return shown.shadowed() === data.shown }, 5000, "the notice follows the retry")
        compare(shown.owner.installInfo.known, true)
        shown.owner.checkInstall()
        compare(installCommands(shown.owner).length, 2, "never a third run")
        compare(runningOn(shown.owner, "--install-info"), null, "and done")
    }

    function test_installRetryFailsToo_data() {
        return [{tag: "widget", kind: "main", exitCode: 2}, {tag: "settings", kind: "settings", exitCode: 2},
                {tag: "widget exit 1", kind: "main", exitCode: 1},
                {tag: "settings exit 1", kind: "settings", exitCode: 1}]
    }

    // An old home-folder copy without --install-info: exit 2 again is unknown.
    function test_installRetryFailsToo(data) {
        var shown = installOwner(data.kind)
        answerInstall(shown.owner, "", 1)
        compare(installCommands(shown.owner).length, 2)
        // Even a reply that would say shadowed doesn't count with a failed exit.
        answerInstall(shown.owner, installReply({user_helper: true}), data.exitCode)
        compare(shown.owner.installInfo.known, false)
        compare(shown.owner.installDistro, "other")
        compare(shown.hint.text, "fusermount3")
        wait(50)
        compare(shown.shadowed(), false, "no notice")
        shown.owner.checkInstall()
        compare(installCommands(shown.owner).length, 2, "no third run")
        compare(runningOn(shown.owner, "--install-info"), null, "nothing running")
    }

    function test_installFirstReplyOkNoRetry_data() {
        return [{tag: "widget", kind: "main"}, {tag: "settings", kind: "settings"}]
    }

    function test_installFirstReplyOkNoRetry(data) {
        var shown = installOwner(data.kind)
        answerInstall(shown.owner, installReply({distro: "fedora"}))
        compare(installCommands(shown.owner).length, 1, "no second run")
        compare(runningOn(shown.owner, "--install-info"), null, "nothing running")
        compare(shown.hint.text, "sudo dnf install fuse3")
        // A first reply that parses as unknown (exit 0) is not retried either.
        var other = installOwner(data.kind)
        answerInstall(other.owner, "{\"ok\":false,\"error\":\"os-error\"}")
        compare(installCommands(other.owner).length, 1, "exit 0 is never retried")
        compare(other.owner.installInfo.known, false)
    }

    // --- one profile per site: migration, prepare/prune/keep, per-site clear --

    readonly property var builtIns: ["claude", "chatgpt", "grok", "gemini", "copilot", "mscopilot", "local"]
    readonly property string unlockedReply: JSON.stringify({ok: true, state: "unlocked", wallet: "off"})
    readonly property string okReply: JSON.stringify({ok: true})

    // The Stay signed in helper commands, without the run prefix (checked
    // here: this widget, nothing else in front).
    // main.qml's own sources sit at its top level (see checkStubs); a full
    // walk of a popup's tree on every poll is slow.
    function topSources(owner) {
        var found = []
        for (var index = 0; index < owner.data.length; index++) {
            if (typeof owner.data[index].connectSource === "function")
                found.push(owner.data[index])
        }
        return found
    }

    function storageCommands(owner) {
        wait(0)
        var prefix = new RegExp("^env HEARTHWIRE_RUN=[0-9]+ HEARTHWIRE_APPLET=" + Plasmoid.id
                                + " python3 -P -m hearthwire ")
        var all = []
        topSources(owner).forEach(function (source) { all = all.concat(source.commands) })
        return all.filter(function (command) {
            return / --(web-data|vault) /.test(command)
        }).map(function (command) {
            verify(prefix.test(command), command)
            return command.replace(prefix, "")
        })
    }

    // The same without status checks (main.qml's recheck may come at any
    // time in a longer test).
    function webDataCommands(owner) {
        return storageCommands(owner).filter(function (command) { return command !== "--vault status" })
    }

    function lastStorageCommand(owner) {
        var commands = storageCommands(owner)
        return commands.length > 0 ? commands[commands.length - 1] : ""
    }

    function answerStorage(owner, reply) {
        wait(0)
        var running = null
        topSources(owner).forEach(function (source) {
            source.connectedSources.forEach(function (command) {
                if (/ --(web-data|vault) /.test(command))
                    running = {source: source, command: command}
            })
        })
        verify(running, "a storage step is running")
        running.source.newData(running.command, {"exit code": 0, "stdout": reply})
        wait(0)
    }

    // Answers the running step after checking it is `expected`.
    // main.qml's recheck 2 s after the first prepare may come in between:
    // it is answered (still unlocked) when another step is expected.
    function expectStorage(owner, expected, reply) {
        tryVerify(function () {
            var last = lastStorageCommand(owner)
            if (last === "--vault status" && expected !== last && owner.chatOp === "status"
                    && owner.chatStorageReady)
                answerStorage(owner, testCase.unlockedReply)
            return lastStorageCommand(owner) === expected
        }, 3000, "expected `" + expected + "`, last was `" + lastStorageCommand(owner) + "`")
        answerStorage(owner, reply === undefined ? testCase.okReply : reply)
    }

    function webData(op, rest) {
        return "--web-data " + op + " --store encrypted --applet " + Plasmoid.id + rest
    }

    // Unlocked and prepared for the shown site (claude), keep and prune
    // done; with popup, through the real Chat tab's start.
    function unlockedMain(settings, popup) {
        var main = loadMain(Object.assign({chatSignInStorage: "encrypted"}, settings || {}))
        compare(main.chatWebSiteId, "claude")
        var generation = main.chatGeneration
        if (popup)
            testCase.chatOpened = chatPopup(main)
        else
            main.chatStorageRequest("open")
        expectStorage(main, "--vault status", testCase.unlockedReply)
        expectStorage(main, webData("prepare", " --generation " + generation + " --sites claude"))
        expectStorage(main, webData("remove", " --keep " + generation))
        expectStorage(main, webData("prune", " --generation " + generation + " --known " + builtIns.join(",")))
        verify(main.chatStorageReady)
        compare(main.chatReadySites, ["claude"])
        return main
    }

    function test_profileLayoutMigration_data() {
        return [
            {tag: "old shared, encrypted", layout: 0, setup: true, mode: "encrypted", generation: 5, next: 1},
            {tag: "old shared, memory", layout: 0, setup: true, mode: "memory", generation: 5, next: 2},
            {tag: "new install, encrypted", layout: 0, setup: false, mode: "encrypted", generation: 5, next: 2},
            {tag: "odd value", layout: 7, setup: true, mode: "encrypted", generation: 5, next: 1},
            {tag: "negative value", layout: -1, setup: true, mode: "memory", generation: 5, next: 2},
            {tag: "notice pending", layout: 1, setup: true, mode: "encrypted", generation: 4, next: 1},
            {tag: "done", layout: 2, setup: true, mode: "encrypted", generation: 4, next: 2},
            {tag: "done, memory", layout: 2, setup: true, mode: "memory", generation: 4, next: 2}
        ]
    }

    // Layout 0 (or anything odd) moves to a new generation once; the
    // notice is owed only for saved sign-ins of a widget set up before.
    function test_profileLayoutMigration(data) {
        var main = loadMain({chatProfileLayout: data.layout, initialSetupComplete: data.setup,
                             chatSignInStorage: data.mode, chatProfileGeneration: 4})
        compare(Plasmoid.configuration.chatProfileLayout, data.next)
        compare(main.chatProfileLayout, data.next)
        compare(main.chatGeneration, data.generation)
        compare(Plasmoid.configuration.chatProfileGeneration, data.generation)
        // Nothing runs the helper for it.
        compare(storageCommands(main), [])
    }

    // A second start (Plasma restart) never moves again.
    function test_profileLayoutMigratesOnce() {
        var first = loadMain({chatSignInStorage: "encrypted", chatProfileGeneration: 4})
        compare(first.chatGeneration, 5)
        compare(Plasmoid.configuration.chatProfileLayout, 1)
        var component = Qt.createComponent(testCase.mainFile)
        var second = createTemporaryObject(component, testCase)
        verify(second)
        compare(second.chatGeneration, 5)
        compare(Plasmoid.configuration.chatProfileGeneration, 5)
        compare(Plasmoid.configuration.chatProfileLayout, 1)
    }

    // After an update, the first unlock's prepare is followed by keep (it
    // deletes the old shared generation folder) and prune.
    function test_unlockPreparesThenKeepsThenPrunes() {
        var main = unlockedMain({chatProfileGeneration: 4})
        compare(main.chatGeneration, 5)
        var commands = storageCommands(main)
        compare(commands, [
            "--vault status",
            webData("prepare", " --generation 5 --sites claude"),
            webData("remove", " --keep 5"),
            webData("prune", " --generation 5 --known claude,chatgpt,grok,gemini,copilot,mscopilot,local")
        ])
        // The prepared generation is never 4 (the old shared folder).
        verify(commands.every(function (command) { return command.indexOf("--generation 4") < 0 }))
        // Lock and unlock again: the same sequence once more.
        main.chatStorageRequest("lock")
        tryVerify(function () { return lastStorageCommand(main) === "--vault lock" }, 3000)
        answerStorage(main, testCase.okReply)
        expectStorage(main, "--vault status", JSON.stringify({ok: true, state: "locked", wallet: "off"}))
        verify(!main.chatStorageReady)
        compare(main.chatReadySites, [])
        main.chatStorageRequest("unlock")
        expectStorage(main, "--vault unlock")
        expectStorage(main, "--vault status", testCase.unlockedReply)
        expectStorage(main, webData("prepare", " --generation 5 --sites claude"))
        expectStorage(main, webData("remove", " --keep 5"))
        expectStorage(main, webData("prune", " --generation 5 --known " + builtIns.join(",")))
        compare(main.chatReadySites, ["claude"])
    }

    // A site shown later gets its folder then; split view needs both.
    function test_prepareFollowsTheShownSites() {
        var main = unlockedMain()
        var generation = main.chatGeneration
        main.chatSiteId = "gemini"
        // As the web view does for a shown site without a profile.
        main.chatSiteWanted("gemini")
        expectStorage(main, webData("prepare", " --generation " + generation + " --sites gemini"))
        compare(main.chatReadySites, ["claude", "gemini"])
        // Back to a prepared site: nothing runs.
        var count = storageCommands(main).length
        main.chatSiteId = "claude"
        wait(20)
        compare(storageCommands(main).length, count)
        // Split view on chatgpt next to claude: only chatgpt is new.
        main.chatSiteIdB = "chatgpt"
        main.setChatSplit(true)
        main.chatSiteWanted("chatgpt")
        expectStorage(main, webData("prepare", " --generation " + generation + " --sites claude,chatgpt"))
        compare(main.chatReadySites, ["claude", "gemini", "chatgpt"])
        // No more keep or prune after these.
        compare(storageCommands(main).filter(function (command) {
            return command.indexOf("--web-data prune") >= 0 || command.indexOf("--web-data remove ") >= 0
        }).length, 2)
        // Ollama never gets a folder.
        main.chatSiteId = "ollama"
        wait(20)
        verify(storageCommands(main).every(function (command) { return command.indexOf("ollama") < 0 }))
    }

    // Memory mode never prepares, keeps or prunes.
    function test_memoryModeRunsNoWebData() {
        var main = loadMain({})
        main.chatStorageRequest("open")
        main.chatSiteId = "gemini"
        main.chatClearSite("gemini")
        wait(50)
        compare(storageCommands(main), ["--vault status"])
        compare(main.chatReadySites, [])
    }

    property var chatFull: null
    property var chatOpened: null

    function chatPopup(main) {
        var full = createTemporaryObject(main.fullRepresentation, main, {width: 900, height: 800})
        verify(full, "the real popup")
        testCase.chatFull = full
        var views = allNamed(full, "chatView")
        compare(views.length, 1, "the real ChatView")
        var chat = views[0]
        chat.webSource = testCase.chatWebStub
        main.popupTab = "chat"
        main.expanded = true
        tryVerify(function () { return chat.started }, 3000)
        return chat
    }

    // Encrypted: the site's views and profile go, then the wait, then only
    // its folder is deleted, and made again for the site still shown.
    function test_clearSiteWithSavedSignIns() {
        var main = unlockedMain({}, true)
        var generation = main.chatGeneration
        var chat = testCase.chatOpened
        tryVerify(function () { return chat.persistentActive }, 3000)
        compare(chat.web.preparedSites, ["claude"])
        compare(chat.web.runtimeDir !== "", true)
        compare(chat.web.storageApplet, Plasmoid.id)
        compare(chat.web.storageGeneration, generation)
        // The toolbar names the site of the pane in use.
        var button = allNamed(testCase.chatFull, "clearSiteButton")
        compare(button.length, 1)
        verify(chat.canClearSite)
        verify(button[0].visible)
        compare(button[0].text, "Clear Claude data…")
        button[0].clicked()
        compare(chat.confirmingClearSite, "claude")
        var text = allNamed(chat, "clearSiteText")[0]
        compare(text.textFormat, Text.PlainText)
        compare(text.text, "Clear Claude data? This signs you out of this site and deletes its saved sign-in. Other sites stay signed in.")
        var count = webDataCommands(main).length
        // The delete it owes is stored before anything is torn down.
        var storedAtTeardown = []
        chat.web.holdRelease = true
        chat.web.clearHook = function (siteId) {
            storedAtTeardown.push(Plasmoid.configuration.chatPendingSiteClears)
        }
        allNamed(chat, "clearSiteConfirm")[0].clicked()
        compare(storedAtTeardown, ["claude"])
        compare(chat.web.clearedSites, ["claude"])
        compare(chat.pendingSiteClears, ["claude"])
        compare(chat.confirmingClearSite, "")
        compare(main.chatReadySites, [], "claude's folder no longer counts")
        compare(chat.web.preparedSites, [])
        // Nothing is deleted, nor waited for, before the profile is gone.
        wait(50)
        compare(webDataCommands(main).length, count)
        verify(main.chatOp !== "wait" && main.chatOp !== "remove-site", main.chatOp)
        compare(main.chatQueue.filter(function (step) { return step !== "status" }), [])
        // The web view destroyed the profile; the shown site then waits.
        chat.web.siteReleased("claude")
        chat.web.siteWanted("claude")
        // Then the wait (the profile closes its files), then the delete.
        tryVerify(function () {
            if (main.chatOp === "status" && main.chatStorageReady)
                answerStorage(main, testCase.unlockedReply)
            return main.chatOp === "wait"
        }, 3000)
        compare(main.chatProfileCloseWait, 1000)
        compare(Plasmoid.configuration.chatPendingSiteClears, "claude")
        expectStorage(main, webData("remove-site", " --generation " + generation + " --site claude"))
        // Only the ok reply ends the debt.
        compare(Plasmoid.configuration.chatPendingSiteClears, "")
        expectStorage(main, webData("prepare", " --generation " + generation + " --sites claude"))
        compare(main.chatReadySites, ["claude"])
        compare(chat.web.preparedSites, ["claude"])
        // Only that one folder: no remove of the generation, no prune
        // (the recheck's status may come in between).
        var after = webDataCommands(main).slice(count)
        compare(after, [webData("remove-site", " --generation " + generation + " --site claude"),
                        webData("prepare", " --generation " + generation + " --sites claude")])
    }

    // A failed delete keeps the site closed (never re-prepared with its old
    // sign-in) and says so; the next unlock tries again.
    function test_clearSiteFailureKeepsTheSiteClosed() {
        var main = unlockedMain()
        var generation = main.chatGeneration
        main.chatClearSite("claude")
        // As the web view does: profile gone, then the shown site waits.
        main.chatSiteReleased("claude")
        main.chatSiteWanted("claude")
        expectStorage(main, webData("remove-site", " --generation " + generation + " --site claude"),
                      JSON.stringify({ok: false, error: "os-error"}))
        wait(50)
        compare(main.chatStorageNotice, "site-remove-failed")
        compare(main.chatReadySites, [])
        compare(Plasmoid.configuration.chatPendingSiteClears, "claude", "a failed delete stays owed")
        verify(storageCommands(main).every(function (command, index, all) {
            return index < all.length - 1 || command.indexOf("--sites claude") < 0
        }))
        compare(main.chatOp, "")
        // Lock and unlock: prepare leaves claude out, then the delete again.
        main.chatStorageRequest("lock")
        tryVerify(function () { return lastStorageCommand(main) === "--vault lock" }, 3000)
        answerStorage(main, testCase.okReply)
        expectStorage(main, "--vault status", JSON.stringify({ok: true, state: "locked", wallet: "off"}))
        main.chatStorageRequest("unlock")
        expectStorage(main, "--vault unlock")
        expectStorage(main, "--vault status", testCase.unlockedReply)
        // The owed delete comes first; only then is claude prepared.
        expectStorage(main, webData("remove-site", " --generation " + generation + " --site claude"))
        compare(Plasmoid.configuration.chatPendingSiteClears, "")
        expectStorage(main, webData("prepare", " --generation " + generation + " --sites claude"))
        expectStorage(main, webData("remove", " --keep " + generation))
        expectStorage(main, webData("prune", " --generation " + generation + " --known " + builtIns.join(",")))
        compare(main.chatReadySites, ["claude"])
    }

    // Memory mode: only the site's views and profile go; no helper.
    function test_clearSiteInMemoryMode() {
        var main = loadMain({})
        var chat = chatPopup(main)
        tryVerify(function () { return chat.web !== null }, 3000)
        compare(chat.web.staySignedIn, false)
        verify(chat.canClearSite)
        chat.askClearSite()
        var text = allNamed(chat, "clearSiteText")[0]
        compare(text.text, "Clear Claude data? This signs you out of this site. Other sites stay signed in.")
        allNamed(chat, "clearSiteConfirm")[0].clicked()
        compare(chat.web.clearedSites, ["claude"])
        wait(50)
        // Only the Chat tab's own start (status); no web data at all.
        compare(storageCommands(main), ["--vault status"])
        // Cancel clears nothing.
        chat.askClearSite()
        allNamed(chat, "clearSiteCancel")[0].clicked()
        compare(chat.web.clearedSites, ["claude"])
    }

    // Encrypted but not open (private session, locked): not offered.
    function test_clearSiteNotOfferedWhileLocked() {
        var main = loadMain({chatSignInStorage: "encrypted"})
        var chat = chatPopup(main)
        expectStorage(main, "--vault status", JSON.stringify({ok: true, state: "locked", wallet: "off"}))
        main.chatStorageRequest("private")
        tryVerify(function () { return chat.web !== null }, 3000)
        compare(chat.web.staySignedIn, false)
        verify(!chat.canClearSite)
        verify(!allNamed(testCase.chatFull, "clearSiteButton")[0].visible)
        chat.askClearSite()
        compare(chat.confirmingClearSite, "")
        chat.confirmingClearSite = "claude"
        chat.clearSiteData()
        compare(chat.web.clearedSites, [])
        main.chatClearSite("claude")
        wait(50)
        compare(storageCommands(main), ["--vault status"])
    }

    // The one-time notice: plain text, exact words, gone for good after
    // Got it.
    function test_profileLayoutNoticeAndGotIt() {
        var main = loadMain({chatSignInStorage: "encrypted"})
        compare(Plasmoid.configuration.chatProfileLayout, 1)
        var chat = chatPopup(main)
        var notice = allNamed(chat, "layoutNotice")[0]
        verify(notice.visible)
        var text = allNamed(chat, "layoutNoticeText")[0]
        compare(text.textFormat, Text.PlainText)
        compare(text.text, "Each chat site now keeps its own sign-in, so one site can't use another's. "
                + "Sign in once more to each site. Signing in to Google in Gemini no longer signs you in on "
                + "other sites, and 'Sign in with Google' on Claude, ChatGPT, Grok or Copilot asks for your "
                + "Google account separately.")
        allNamed(chat, "layoutNoticeDone")[0].clicked()
        compare(Plasmoid.configuration.chatProfileLayout, 2)
        verify(!notice.visible)
        // Got it again changes nothing.
        main.chatStorageRequest("layout-notice-done")
        compare(Plasmoid.configuration.chatProfileLayout, 2)
    }

    function test_profileLayoutNoticeOnlyWithSavedSignIns() {
        var main = loadMain({chatProfileLayout: 1})
        var chat = chatPopup(main)
        verify(!allNamed(chat, "layoutNotice")[0].visible)
        // Got it in memory mode never writes 1 → 2 behind its back either way.
        compare(Plasmoid.configuration.chatProfileLayout, 1)
    }

    // Every settings page keeps chatProfileLayout in step, so Apply never
    // writes an old value back.
    function test_pagesKeepTheProfileLayoutInStep_data() {
        return [{tag: "usage", file: testCase.usagePageFile}, {tag: "general", file: testCase.generalPageFile},
                {tag: "chat", file: testCase.chatPageFile}]
    }

    function test_pagesKeepTheProfileLayoutInStep(data) {
        var page = load(data.file, {chatProfileLayout: 1})
        verify("cfg_chatProfileLayout" in page)
        compare(page.cfg_chatProfileLayoutDefault, 0)
        page.cfg_chatProfileLayout = 1
        Plasmoid.configuration.chatProfileLayout = 2
        compare(page.cfg_chatProfileLayout, 2)
    }

    // --- Clear <site> data survives a restart (chatPendingSiteClears) -------

    // Plasma restarted with a delete still owed: the unlock deletes the
    // folder before anything prepares that site.
    function test_restartRunsTheOwedDeleteBeforeAnyPrepare() {
        var main = loadMain({chatSignInStorage: "encrypted", chatPendingSiteClears: "claude"})
        var generation = main.chatGeneration
        compare(main.chatPendingClears, ["claude"])
        main.chatStorageRequest("open")
        expectStorage(main, "--vault status", testCase.unlockedReply)
        expectStorage(main, webData("remove-site", " --generation " + generation + " --site claude"))
        compare(Plasmoid.configuration.chatPendingSiteClears, "")
        expectStorage(main, webData("prepare", " --generation " + generation + " --sites claude"))
        expectStorage(main, webData("remove", " --keep " + generation))
        expectStorage(main, webData("prune", " --generation " + generation + " --known " + builtIns.join(",")))
        compare(main.chatReadySites, ["claude"])
    }

    // The delete fails after a restart: the site stays closed (prepared
    // without it) and owed; the rest goes on.
    function test_restartWithAFailedDeleteKeepsTheSiteClosed() {
        var main = loadMain({chatSignInStorage: "encrypted", chatPendingSiteClears: "claude"})
        var generation = main.chatGeneration
        main.chatStorageRequest("open")
        expectStorage(main, "--vault status", testCase.unlockedReply)
        expectStorage(main, webData("remove-site", " --generation " + generation + " --site claude"),
                      JSON.stringify({ok: false, error: "os-error"}))
        expectStorage(main, webData("prepare", " --generation " + generation))
        expectStorage(main, webData("remove", " --keep " + generation))
        expectStorage(main, webData("prune", " --generation " + generation + " --known " + builtIns.join(",")))
        wait(50)
        compare(Plasmoid.configuration.chatPendingSiteClears, "claude")
        compare(main.chatReadySites, [])
        compare(main.chatStorageNotice, "site-remove-failed")
        verify(storageCommands(main).every(function (command) { return command.indexOf("--sites claude") < 0 }))
        verify(main.chatStorageReady)
        // Another site shown meanwhile is prepared; claude never is.
        main.chatSiteId = "gemini"
        main.chatSiteWanted("gemini")
        expectStorage(main, webData("prepare", " --generation " + generation + " --sites gemini"))
        compare(main.chatReadySites, ["gemini"])
        compare(Plasmoid.configuration.chatPendingSiteClears, "claude")
    }

    function test_storedClearsAreReadStrictly_data() {
        return [
            {tag: "bad parts dropped", text: "claude,../evil,user-XYZ,gemini,claude,", pending: ["claude", "gemini"]},
            {tag: "spaces", text: "claude, gemini", pending: ["claude"]},
            {tag: "added site", text: "user-0123abcd,ollama", pending: ["user-0123abcd"]},
            {tag: "unreadable", text: "%%%;rm -rf", pending: []},
            {tag: "empty", text: "", pending: []}
        ]
    }

    // Unreadable parts never reach a command and never let a listed site
    // be prepared; every readable id is deleted first.
    function test_storedClearsAreReadStrictly(data) {
        var main = loadMain({chatSignInStorage: "encrypted", chatPendingSiteClears: data.text})
        var generation = main.chatGeneration
        compare(main.chatPendingClears, data.pending)
        main.chatStorageRequest("open")
        expectStorage(main, "--vault status", testCase.unlockedReply)
        var failed = JSON.stringify({ok: false, error: "os-error"})
        data.pending.forEach(function (id) {
            expectStorage(main, webData("remove-site", " --generation " + generation + " --site " + id), failed)
        })
        // claude is shown: prepared only when it isn't listed.
        expectStorage(main, webData("prepare", " --generation " + generation
                                    + (data.pending.indexOf("claude") >= 0 ? "" : " --sites claude")))
        storageCommands(main).forEach(function (command) {
            verify(/^--(vault|web-data) [a-z-]+( --[a-z]+ [a-z0-9,-]+)*$/.test(command), command)
            verify(!/evil|XYZ|ollama|%|;| ,/.test(command), command)
        })
        // A delete that works stores the list back clean.
        if (data.pending.length > 1) {
            main.chatStorageRequest("lock")
            tryVerify(function () { return lastStorageCommand(main) === webData("remove", " --keep " + generation) }, 3000)
            answerStorage(main, testCase.okReply)
            expectStorage(main, webData("prune", " --generation " + generation + " --known " + builtIns.join(",")))
            expectStorage(main, "--vault lock")
            expectStorage(main, "--vault status", JSON.stringify({ok: true, state: "locked", wallet: "off"}))
            main.chatStorageRequest("unlock")
            expectStorage(main, "--vault unlock")
            expectStorage(main, "--vault status", testCase.unlockedReply)
            expectStorage(main, webData("remove-site", " --generation " + generation + " --site claude"))
            compare(Plasmoid.configuration.chatPendingSiteClears, "gemini")
        }
    }

    // Every settings page keeps chatPendingSiteClears in step, so Apply
    // never writes an owed delete away.
    function test_pagesKeepThePendingClearsInStep_data() {
        return [{tag: "usage", file: testCase.usagePageFile}, {tag: "general", file: testCase.generalPageFile},
                {tag: "chat", file: testCase.chatPageFile}]
    }

    function test_pagesKeepThePendingClearsInStep(data) {
        var page = load(data.file, {})
        compare(page.cfg_chatPendingSiteClears, "")
        compare(page.cfg_chatPendingSiteClearsDefault, "")
        Plasmoid.configuration.chatPendingSiteClears = "claude"
        compare(page.cfg_chatPendingSiteClears, "claude")
        Plasmoid.configuration.chatPendingSiteClears = ""
        compare(page.cfg_chatPendingSiteClears, "")
    }

    // The owed delete can't be stored (the list is full): nothing is torn
    // down and nothing is deleted, so nothing is half cleared.
    function test_clearSiteNotTornDownWhenItCantBeStored() {
        var main = unlockedMain({}, true)
        var chat = testCase.chatOpened
        tryVerify(function () { return chat.persistentActive }, 3000)
        var full = []
        for (var index = 0; index < 207; index++)
            full.push("user-" + ("0000000" + index.toString(16)).slice(-8))
        Plasmoid.configuration.chatPendingSiteClears = full.join(",")
        var count = webDataCommands(main).length
        chat.askClearSite()
        allNamed(chat, "clearSiteConfirm")[0].clicked()
        compare(chat.web.clearedSites, [])
        compare(Plasmoid.configuration.chatPendingSiteClears, full.join(","))
        verify(!main.chatRemovalPending("claude"))
        wait(50)
        compare(webDataCommands(main).length, count)
        compare(main.chatQueue.filter(function (step) { return step !== "status" }), [])
    }

    function test_clearChatDataEndsTheOwedDeletes_data() {
        return [{tag: "remove ok", reply: JSON.stringify({ok: true}), left: ""},
                {tag: "remove failed", reply: JSON.stringify({ok: false, error: "os-error"}), left: "gemini,claude"}]
    }

    // Clear chat data deletes every generation: once that remove replied
    // ok, no Clear <site> delete is owed; if it failed, the list stays.
    function test_clearChatDataEndsTheOwedDeletes(data) {
        var main = unlockedMain()
        var generation = main.chatGeneration
        // Owed from an earlier failed delete (as if written by an earlier run).
        Plasmoid.configuration.chatPendingSiteClears = "gemini"
        main.chatClearSite("claude")
        main.chatSiteReleased("claude")
        compare(Plasmoid.configuration.chatPendingSiteClears, "gemini,claude")
        tryVerify(function () { return main.chatOp === "" || main.chatOp === "remove-site" }, 3000)
        expectStorage(main, webData("remove-site", " --generation " + generation + " --site gemini"),
                      JSON.stringify({ok: false, error: "os-error"}))
        expectStorage(main, webData("remove-site", " --generation " + generation + " --site claude"),
                      JSON.stringify({ok: false, error: "os-error"}))
        compare(Plasmoid.configuration.chatPendingSiteClears, "gemini,claude")
        main.chatStorageRequest("clear-saved")
        compare(main.chatGeneration, generation + 1)
        // Not before the remove step's reply.
        compare(Plasmoid.configuration.chatPendingSiteClears, "gemini,claude")
        expectStorage(main, webData("remove", ""), data.reply)
        compare(Plasmoid.configuration.chatPendingSiteClears, data.left)
        expectStorage(main, "--vault lock")
    }

    // --- SEC-L1: a new saved profile only after a fresh, verified prepare ---

    // Every status check ends what the prepares before it allowed: a site
    // opened after it is prepared again (the helper verifies the mount)
    // before any new saved profile is made for it.
    function test_newSavedProfileNeedsAPrepareAfterTheLastStatus() {
        var main = unlockedMain()
        var generation = main.chatGeneration
        compare(main.chatReadySites, ["claude"])
        main.chatStorageRequest("recheck")
        expectStorage(main, "--vault status", testCase.unlockedReply)
        compare(main.chatReadySites, [], "the check ends the prepare's say")
        verify(main.chatStorageReady, "open profiles stay")
        // The recheck alone runs nothing more.
        wait(50)
        compare(lastStorageCommand(main), "--vault status")
        // A site opened now (even claude again, after its view was gone).
        main.chatSiteId = "gemini"
        main.chatSiteWanted("gemini")
        expectStorage(main, webData("prepare", " --generation " + generation + " --sites gemini"))
        compare(main.chatReadySites, ["gemini"])
        main.chatSiteWanted("claude")
        expectStorage(main, webData("prepare", " --generation " + generation + " --sites gemini,claude"))
        compare(main.chatReadySites, ["gemini", "claude"])
        // Asking again while fresh runs nothing.
        var count = storageCommands(main).length
        main.chatSiteWanted("claude")
        wait(50)
        compare(storageCommands(main).length, count)
        // A busy status (another widget) counts as a check too.
        main.chatStorageRequest("recheck")
        expectStorage(main, "--vault status", JSON.stringify({ok: false, error: "busy"}))
        compare(main.chatReadySites, [])
    }

    // A prepare that fails (the mount went away) allows nothing.
    function test_failedPrepareAllowsNoNewProfile() {
        var main = unlockedMain()
        var generation = main.chatGeneration
        main.chatStorageRequest("recheck")
        expectStorage(main, "--vault status", testCase.unlockedReply)
        main.chatSiteId = "gemini"
        main.chatSiteWanted("gemini")
        expectStorage(main, webData("prepare", " --generation " + generation + " --sites gemini"),
                      JSON.stringify({ok: false, error: "not-verified"}))
        compare(main.chatReadySites, [])
        verify(!main.chatStorageReady)
    }

    // Requests for sites that aren't shown chat web sites are ignored.
    function test_siteWantedIgnoresOddIds() {
        var main = unlockedMain()
        var count = storageCommands(main).length
        ;["ollama", "", "claude2", "user-0123abcd", "__proto__"].forEach(function (id) { main.chatSiteWanted(id) })
        wait(50)
        compare(storageCommands(main).length, count)
        compare(main.chatWantedSites, [])
    }

    // The real Chat tab forwards its web view's request, only with saved
    // sign-ins open.
    function test_chatTabForwardsTheSiteRequest() {
        var main = unlockedMain({}, true)
        var generation = main.chatGeneration
        var chat = testCase.chatOpened
        tryVerify(function () { return chat.persistentActive }, 3000)
        main.chatSiteId = "gemini"
        chat.web.siteWanted("gemini")
        expectStorage(main, webData("prepare", " --generation " + generation + " --sites gemini"))
        verify(main.chatReadySites.indexOf("gemini") >= 0)
        compare(chat.web.preparedSites.indexOf("gemini") >= 0, true)
    }
}
