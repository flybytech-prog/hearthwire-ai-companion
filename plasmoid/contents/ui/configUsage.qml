import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami
import QtQuick.Dialogs as QtDialogs
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as Plasma5Support
import "ProviderCatalog.js" as Catalog
import "TooltipLogic.js" as TooltipLogic
import "UsageLogic.js" as UsageLogic

KCM.ScrollViewKCM {
    id: page

    property string cfg_trackedProviders:
        "[\"claude\",\"codex\",\"cursor\",\"antigravity\",\"copilot\",\"devin\",\"grok\"]"
    property string cfg_trackedProvidersDefault:
        "[\"claude\",\"codex\",\"cursor\",\"antigravity\",\"copilot\",\"devin\",\"grok\"]"
    property string cfg_providerMetrics: "{}"
    property string cfg_providerMetricsDefault: "{}"
    property string cfg_usageMode: "remaining"
    property string cfg_usageModeDefault: "remaining"
    property int cfg_refreshInterval: 300
    property int cfg_refreshIntervalDefault: 300
    property int cfg_configSchemaVersion: 2
    property int cfg_configSchemaVersionDefault: 2
    property bool cfg_initialSetupComplete: false
    property bool cfg_initialSetupCompleteDefault: false
    property string cfg_chatSites:
        "[\"claude\",\"chatgpt\",\"grok\",\"gemini\",\"copilot\",\"mscopilot\"]"
    property string cfg_chatSitesDefault:
        "[\"claude\",\"chatgpt\",\"grok\",\"gemini\",\"copilot\",\"mscopilot\"]"
    property string cfg_chatDefaultSite: "claude"
    property string cfg_chatDefaultSiteDefault: "claude"
    property string cfg_chatCustomUrls: "{}"
    property string cfg_chatCustomUrlsDefault: "{}"
    property string cfg_chatSignInStorage: "memory"
    property string cfg_chatSignInStorageDefault: "memory"
    // Written only by main.qml; kept in step so Apply never writes back an
    // old value.
    property int cfg_chatProfileGeneration: 0
    property int cfg_chatProfileGenerationDefault: 0
    property int cfg_chatAutoLockMinutes: 0
    property int cfg_chatAutoLockMinutesDefault: 0
    property string cfg_chatVaultUnlock: "passphrase"
    property string cfg_chatVaultUnlockDefault: "passphrase"
    property bool cfg_chatKeepOpen: false
    property bool cfg_chatKeepOpenDefault: false
    property string cfg_chatOllamaUrl: "http://127.0.0.1:11434"
    property string cfg_chatOllamaUrlDefault: "http://127.0.0.1:11434"
    property string cfg_popupDefaultTab: "chat"
    property string cfg_popupDefaultTabDefault: "chat"
    property bool cfg_showUsageTab: true
    property bool cfg_showUsageTabDefault: true
    property bool cfg_showChatTab: true
    property bool cfg_showChatTabDefault: true
    property string cfg_popupSize: "normal"
    property string cfg_popupSizeDefault: "normal"
    property bool cfg_tooltipShowsUsage: true
    property bool cfg_tooltipShowsUsageDefault: true
    property string cfg_tooltipMetrics: ""
    property string cfg_tooltipMetricsDefault: ""
    property string cfg_shortcutOpens: "popup"
    property string cfg_shortcutOpensDefault: "popup"
    // Written only by main.qml (zoom keys, Ctrl+wheel); kept in step so
    // Apply never writes back an old value.
    property string cfg_chatSiteZoom: "{}"
    property string cfg_chatSiteZoomDefault: "{}"
    property bool cfg_alertLowEnabled: false
    property bool cfg_alertLowEnabledDefault: false
    property int cfg_alertLowPercent: 20
    property int cfg_alertLowPercentDefault: 20
    property bool cfg_alertResetEnabled: false
    property bool cfg_alertResetEnabledDefault: false
    property string cfg_providerOrder: ""
    property string cfg_providerOrderDefault: ""
    property bool cfg_usageCompact: false
    property bool cfg_usageCompactDefault: false
    property int cfg_usageWarnPercent: 60
    property int cfg_usageWarnPercentDefault: 60
    property int cfg_usageCriticalPercent: 85
    property int cfg_usageCriticalPercentDefault: 85
    property string cfg_usageNormalColor: ""
    property string cfg_usageNormalColorDefault: ""
    property string cfg_usageWarnColor: ""
    property string cfg_usageWarnColorDefault: ""
    property string cfg_usageCriticalColor: ""
    property string cfg_usageCriticalColorDefault: ""

    property var catalogModel: Catalog.providers
    // The provider rows in the Usage tab's order.
    readonly property var providerOrder: UsageLogic.normalizeOrder(page.cfg_providerOrder, Catalog.providerIds())
    readonly property var orderedCatalog: UsageLogic.orderProviders(page.catalogModel, page.providerOrder)
    readonly property var thresholds: UsageLogic.normalizeThresholds(
        page.cfg_usageWarnPercent, page.cfg_usageCriticalPercent)
    // Warning 50–90, critical 55–95: every pick is kept, the other level
    // moves out of its way.
    // The levels read as used or left, like General → Display.
    readonly property var warnChoices: UsageLogic.WARN_PERCENTS.map(function (percent) {
        return { value: percent, text: i18nc("@item level", "%1%", UsageLogic.shownPercent(percent, page.cfg_usageMode)) }
    })
    readonly property var criticalChoices: UsageLogic.CRITICAL_PERCENTS.map(function (percent) {
        return { value: percent, text: i18nc("@item level", "%1%", UsageLogic.shownPercent(percent, page.cfg_usageMode)) }
    })
    // The arrows order the tracked providers only.
    readonly property var trackedIds: page.tracked()
    // Hover popup readings: null while "Same as the Usage tab" is on.
    readonly property var tooltipChoice: TooltipLogic.parseTooltipMetrics(page.cfg_tooltipMetrics, Catalog.providers)
    readonly property bool tooltipReadingsEnabled: page.cfg_showUsageTab && page.cfg_tooltipShowsUsage
    // Tracked providers in the Usage tab's order (all of them if the list is odd).
    readonly property var tooltipProviders: {
        var tracked = null
        try {
            tracked = JSON.parse(page.cfg_trackedProviders || "")
        } catch (error) {
        }
        var ordered = UsageLogic.orderProviders(Catalog.providers, page.providerOrder)
        if (!Array.isArray(tracked))
            return ordered
        return ordered.filter(function (provider) {
            return tracked.indexOf(provider.provider_id) >= 0
        })
    }
    property var installedProviderIds: []
    property var providerResults: ({})
    property string statusMessage: ""
    property bool checkingProviders: false
    property bool detecting: false
    readonly property string detectCommand: "python3 -P -m hearthwire --detect"

    function parseList(value, fallback) {
        try {
            var parsed = JSON.parse(value || "")
            if (Array.isArray(parsed))
                return parsed
        } catch (error) {
        }
        return fallback.slice()
    }

    function parseMetrics() {
        try {
            var parsed = JSON.parse(page.cfg_providerMetrics || "")
            if (parsed && typeof parsed === "object" && !Array.isArray(parsed))
                return parsed
        } catch (error) {
        }
        return {}
    }

    function tracked() {
        return parseList(page.cfg_trackedProviders, Catalog.providerIds())
    }

    function contains(list, value) {
        return list.indexOf(value) >= 0
    }

    function setMembership(list, value, enabled) {
        var result = list.slice()
        var index = result.indexOf(value)
        if (enabled && index < 0)
            result.push(value)
        else if (!enabled && index >= 0)
            result.splice(index, 1)
        return result
    }

    function setTracked(providerId, enabled) {
        page.cfg_trackedProviders = JSON.stringify(
            setMembership(tracked(), providerId, enabled)
        )
    }

    // The ticked readings that are still catalog metrics, as main.qml reads them.
    function selectedMetrics(providerId) {
        return UsageLogic.effectiveChoice(parseMetrics()[providerId], page.metricIds(providerId))
    }

    function metricIds(providerId) {
        var descriptor = Catalog.byId(providerId)
        return descriptor ? descriptor.metrics.map(function (metric) { return metric.id }) : []
    }

    // No ticked reading stored means the Usage tab shows them all, so every
    // box shows ticked; the last ticked one can't be unticked.
    function setMetric(providerId, metricId, enabled) {
        var metrics = parseMetrics()
        var selected = Array.isArray(metrics[providerId]) ? metrics[providerId] : []
        var next = UsageLogic.toggleMetric(selected, page.metricIds(providerId), metricId, enabled)
        if (next.length === 0)
            delete metrics[providerId]
        else
            metrics[providerId] = next
        page.cfg_providerMetrics = JSON.stringify(metrics)
        if (enabled) {
            page.cfg_trackedProviders = JSON.stringify(
                setMembership(tracked(), providerId, true)
            )
        }
    }

    function lastShownMetric(providerId, metricId) {
        return UsageLogic.isLastShown(parseMetrics()[providerId], page.metricIds(providerId), metricId)
    }

    function canMove(providerId, direction) {
        return UsageLogic.canMove(page.providerOrder, providerId, direction, page.trackedIds)
    }

    // Swaps with the next tracked provider; untracked ones keep their place.
    function moveProvider(providerId, direction) {
        page.cfg_providerOrder = JSON.stringify(
            UsageLogic.moveId(page.providerOrder, providerId, direction, page.trackedIds))
    }

    function descriptorFor(providerId) {
        var list = page.catalogModel || []
        for (var index = 0; index < list.length; index++) {
            if (list[index] && list[index].provider_id === providerId)
                return list[index]
        }
        return Catalog.byId(providerId)
    }

    // Moves the rows instead of resetting the model, so the list keeps its
    // scroll position and the arrow keeps its focus.
    function syncProviderRows() {
        var wanted = page.orderedCatalog.map(function (provider) { return provider.provider_id })
        var current = []
        for (var index = 0; index < providerRows.count; index++)
            current.push(providerRows.get(index).providerId)
        var moves = UsageLogic.syncMoves(current, wanted)
        if (moves === null) {
            providerRows.clear()
            for (var add = 0; add < wanted.length; add++)
                providerRows.append({ providerId: wanted[add] })
            return
        }
        for (var step = 0; step < moves.length; step++)
            providerRows.move(moves[step].from, moves[step].to, 1)
    }

    onOrderedCatalogChanged: page.syncProviderRows()

    ListModel {
        id: providerRows
    }

    // level: "normal", "warning" or "critical"; "" is the default color.
    // The color dialog's choice as "#rrggbb", always opaque, so a
    // translucent color can't turn into "" (normalizeColor still checks it).
    function opaqueColor(color) {
        return String(Qt.rgba(color.r, color.g, color.b, 1))
    }

    // {level: the color its box shows}, kept by the boxes for setUsageColor.
    property var shownColors: ({})

    function setUsageColor(level, color) {
        var value = UsageLogic.normalizeColor(color)
        var current = UsageLogic.normalizeColor(level === "normal" ? page.cfg_usageNormalColor
            : level === "warning" ? page.cfg_usageWarnColor : page.cfg_usageCriticalColor)
        // The dialog opens on the color shown: OK without picking another
        // keeps an empty box empty, so it goes on following its default.
        if (value !== "" && current === "" && Qt.colorEqual(value, page.shownColors[level]))
            return
        if (level === "normal")
            page.cfg_usageNormalColor = value
        else if (level === "warning")
            page.cfg_usageWarnColor = value
        else if (level === "critical")
            page.cfg_usageCriticalColor = value
    }

    // A color box: the chosen color, else the default one; the reset
    // button next to it goes back to the default.
    component ColorChoice: RowLayout {
        id: colorChoice

        property string level
        property string chosen
        property color fallback

        spacing: Kirigami.Units.smallSpacing

        readonly property color shown: colorChoice.chosen !== "" ? colorChoice.chosen : colorChoice.fallback
        onShownChanged: page.shownColors[colorChoice.level] = String(colorChoice.shown)
        Component.onCompleted: page.shownColors[colorChoice.level] = String(colorChoice.shown)

        QQC2.Button {
            objectName: colorChoice.level + "ColorButton"
            enabled: page.cfg_showUsageTab
            implicitWidth: Kirigami.Units.gridUnit * 3
            Accessible.name: i18n("Choose a color")
            QQC2.ToolTip.text: i18n("Choose a color")
            QQC2.ToolTip.visible: hovered
            onClicked: colorDialog.open()

            Rectangle {
                anchors.fill: parent
                anchors.margins: Kirigami.Units.smallSpacing + 1
                radius: Kirigami.Units.cornerRadius / 2
                color: parent.enabled ? colorChoice.shown : "transparent"
                border.color: Kirigami.Theme.textColor
                border.width: 1
                opacity: parent.enabled ? 1 : 0.4
            }
        }
        QtDialogs.ColorDialog {
            id: colorDialog
            title: i18n("Choose a color")
            selectedColor: colorChoice.shown
            onAccepted: page.setUsageColor(colorChoice.level, page.opaqueColor(selectedColor))
        }
        QQC2.ToolButton {
            objectName: colorChoice.level + "ColorReset"
            enabled: page.cfg_showUsageTab
            visible: colorChoice.chosen !== ""
            icon.name: "edit-reset"
            display: QQC2.AbstractButton.IconOnly
            text: i18n("Use the default color")
            QQC2.ToolTip.text: text
            QQC2.ToolTip.visible: hovered
            onClicked: page.setUsageColor(colorChoice.level, "")
        }
    }

    function setThresholds(warn, critical) {
        var next = UsageLogic.normalizeThresholds(warn, critical)
        page.cfg_usageWarnPercent = next.warn
        page.cfg_usageCriticalPercent = next.critical
    }

    function setTooltipSame(same) {
        page.cfg_tooltipMetrics = same ? "" : JSON.stringify(
            TooltipLogic.seedTooltipMetrics(page.cfg_providerMetrics, Catalog.providers))
    }

    function setTooltipMetric(providerId, metricId, enabled) {
        var choice = page.tooltipChoice
            || TooltipLogic.seedTooltipMetrics(page.cfg_providerMetrics, Catalog.providers)
        page.cfg_tooltipMetrics = JSON.stringify(
            TooltipLogic.setTooltipMetric(choice, Catalog.providers, providerId, metricId, enabled))
    }

    function choiceIndex(choices, value, fallback) {
        for (var index = 0; index < choices.length; index++) {
            if (choices[index].value === value)
                return index
        }
        return fallback
    }

    function resultFor(providerId) {
        return page.providerResults[providerId] || null
    }

    function providerStatus(providerId) {
        if (!contains(page.installedProviderIds, providerId)) {
            return page.detecting && page.installedProviderIds.length === 0
                ? i18n("Checking…") : i18n("Not detected")
        }
        var result = resultFor(providerId)
        if (!result)
            return page.checkingProviders ? i18n("Checking…") : i18n("Detected")
        if (result.status === "ok")
            return result.plan ? i18n("Connected · %1", result.plan) : i18n("Connected")
        if (result.status === "stale")
            return i18n("Connected · stale")
        return result.error_message || result.status
    }

    function metricAvailable(providerId, metricId) {
        var result = resultFor(providerId)
        return !result || !Array.isArray(result.available_metrics)
            || contains(result.available_metrics, metricId)
    }

    function refreshProviders() {
        page.checkingProviders = true
        var safe = tracked().filter(function (providerId) {
            return Catalog.byId(providerId) !== null
        })
        providerSource.connectSource(
            "python3 -P -m hearthwire --json --providers=" + safe.join(",")
        )
    }

    // Network-free: only reports which providers are installed.
    function detectProviders() {
        page.detecting = true
        providerSource.connectSource(page.detectCommand)
    }

    Component.onCompleted: {
        // Never back to 2, which would run main.qml's migration again.
        page.cfg_configSchemaVersion = 3
        page.cfg_initialSetupComplete = true
        page.syncProviderRows()
        Qt.callLater(page.detectProviders)
    }

    Connections {
        target: Plasmoid.configuration
        function onValueChanged(key, value) {
            if (key === "chatProfileGeneration")
                page.cfg_chatProfileGeneration = value
            else if (key === "chatSiteZoom")
                page.cfg_chatSiteZoom = value
        }
    }

    Plasma5Support.DataSource {
        id: providerSource
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            providerSource.disconnectSource(source)
            var detectOnly = source === page.detectCommand
            if (detectOnly)
                page.detecting = false
            else
                page.checkingProviders = false
            try {
                var payload = JSON.parse((data["stdout"] || "").toString())
                if (payload.schema_version !== 2)
                    throw new Error("schema")
                if (payload.catalog && payload.catalog.length)
                    page.catalogModel = payload.catalog
                page.statusMessage = ""
                page.installedProviderIds = payload.installed_provider_ids || []
                // Detection carries no status; keep results from a network run.
                if (detectOnly)
                    return
                var results = {}
                var providers = payload.providers || []
                for (var index = 0; index < providers.length; index++)
                    results[providers[index].provider_id] = providers[index]
                page.providerResults = results
            } catch (error) {
                page.statusMessage = i18n("Could not read provider status.")
            }
        }
    }

    view: ListView {
        id: providerList
        clip: true
        spacing: Kirigami.Units.smallSpacing
        model: providerRows

        header: ColumnLayout {
            width: providerList.width
            spacing: Kirigami.Units.largeSpacing

            RowLayout {
                Layout.fillWidth: true
                Kirigami.Heading {
                    level: 2
                    text: i18n("Usage tab")
                }
                Kirigami.ContextualHelpButton {
                    toolTipText: i18n("Tracked providers appear in the Usage tab in the order below. The arrows move a tracked provider past the next tracked one; untracked providers keep their place and can't be moved. The ticked readings are the ones the Usage tab shows; with every reading ticked it also shows readings added later. Usage notifications follow the ticked readings, or a provider's main reading while all are ticked. Credentials stay on this computer; the helper only contacts the usage APIs of providers you track.")
                }
                Item {
                    Layout.fillWidth: true
                }
                QQC2.Button {
                    text: page.checkingProviders ? i18n("Checking…") : i18n("Refresh status")
                    icon.name: "view-refresh"
                    enabled: !page.checkingProviders
                    onClicked: page.refreshProviders()
                }
            }
            QQC2.Label {
                Layout.fillWidth: true
                visible: !page.cfg_showUsageTab
                text: i18n("The Usage tab is hidden in General, so usage isn't refreshed.")
                wrapMode: Text.WordWrap
                opacity: 0.72
            }

            Kirigami.FormLayout {
                Layout.fillWidth: true

                RowLayout {
                    Kirigami.FormData.label: i18n("Layout:")
                    spacing: Kirigami.Units.smallSpacing

                    QQC2.CheckBox {
                        objectName: "usageCompactChoice"
                        enabled: page.cfg_showUsageTab
                        text: i18n("Compact")
                        checked: page.cfg_usageCompact
                        onToggled: page.cfg_usageCompact = checked
                    }
                    Kirigami.ContextualHelpButton {
                        toolTipText: i18n("Shows one slim bar per reading with its name, value and time until reset, without plan names or captions. Errors still show, on one line.")
                    }
                }

                ColorChoice {
                    Kirigami.FormData.label: i18n("Normal color:")
                    level: "normal"
                    chosen: UsageLogic.normalizeColor(page.cfg_usageNormalColor)
                    fallback: UsageLogic.defaultNormalColor(Kirigami.Theme.backgroundColor.r,
                        Kirigami.Theme.backgroundColor.g, Kirigami.Theme.backgroundColor.b)
                }

                RowLayout {
                    Kirigami.FormData.label: i18n("Warning color from:")
                    spacing: Kirigami.Units.smallSpacing

                    QQC2.ComboBox {
                        objectName: "usageWarnChoice"
                        enabled: page.cfg_showUsageTab
                        textRole: "text"
                        valueRole: "value"
                        model: page.warnChoices
                        currentIndex: page.choiceIndex(page.warnChoices, page.thresholds.warn, 2)
                        onActivated: page.setThresholds(currentValue, page.thresholds.critical)
                    }
                    ColorChoice {
                        level: "warning"
                        chosen: UsageLogic.normalizeColor(page.cfg_usageWarnColor)
                        fallback: Kirigami.Theme.neutralTextColor
                    }
                    Kirigami.ContextualHelpButton {
                        toolTipText: i18n("Bars and values turn to the warning color at this level and to the critical color at the Critical level. The levels read as left or used, as General → Display shows: with Left, 40% means 40% left. The critical level always stays past the warning level. The color boxes choose each color; the reset button next to a box goes back to the default.")
                    }
                }

                RowLayout {
                    Kirigami.FormData.label: i18n("Critical color from:")
                    spacing: Kirigami.Units.smallSpacing

                    QQC2.ComboBox {
                        objectName: "usageCriticalChoice"
                        enabled: page.cfg_showUsageTab
                        textRole: "text"
                        valueRole: "value"
                        model: page.criticalChoices
                        currentIndex: page.choiceIndex(page.criticalChoices, page.thresholds.critical, 6)
                        onActivated: {
                            // Keeps the pick: the warning level moves below it.
                            var warn = Math.min(page.thresholds.warn, currentValue - 5)
                            page.setThresholds(warn, currentValue)
                        }
                    }
                    ColorChoice {
                        level: "critical"
                        chosen: UsageLogic.normalizeColor(page.cfg_usageCriticalColor)
                        // Shown while empty, as main.qml uses it; never saved.
                        fallback: UsageLogic.effectiveCriticalColor("", page.cfg_usageWarnColor)
                            || Kirigami.Theme.negativeTextColor
                    }
                }
            }

            Kirigami.Heading {
                level: 3
                text: i18n("Providers and readings")
            }
        }

        delegate: Rectangle {
            id: providerRow
            required property string providerId
            readonly property var descriptor: page.descriptorFor(providerRow.providerId) || ({})
            width: providerList.width
            implicitHeight: providerColumn.implicitHeight
                + Kirigami.Units.largeSpacing * 2
            radius: Kirigami.Units.smallSpacing
            color: Qt.rgba(
                Kirigami.Theme.textColor.r,
                Kirigami.Theme.textColor.g,
                Kirigami.Theme.textColor.b,
                0.045
            )

            ColumnLayout {
                id: providerColumn
                anchors {
                    left: parent.left
                    right: parent.right
                    top: parent.top
                    margins: Kirigami.Units.largeSpacing
                }
                spacing: Kirigami.Units.smallSpacing

                RowLayout {
                    Layout.fillWidth: true

                    Kirigami.Icon {
                        source: Qt.resolvedUrl(
                            "../images/" + providerRow.descriptor.icon
                        )
                        Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                        Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                        isMask: true
                        color: Kirigami.Theme.textColor
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        Kirigami.Heading {
                            Layout.fillWidth: true
                            level: 4
                            textFormat: Text.PlainText
                            text: providerRow.descriptor.display_name
                            elide: Text.ElideRight
                        }
                        QQC2.Label {
                            Layout.fillWidth: true
                            // Helper text: never rich text.
                            textFormat: Text.PlainText
                            text: page.providerStatus(
                                providerRow.descriptor.provider_id
                            )
                            opacity: 0.62
                            elide: Text.ElideRight
                            font: Kirigami.Theme.smallFont
                        }
                    }
                    QQC2.ToolButton {
                        id: moveUpButton
                        icon.name: "go-up"
                        display: QQC2.AbstractButton.IconOnly
                        text: i18n("Move up")
                        enabled: page.canMove(providerRow.providerId, -1)
                        onClicked: {
                            page.moveProvider(providerRow.providerId, -1)
                            // At the top: the row's other arrow keeps the focus.
                            if (!moveUpButton.enabled && moveDownButton.enabled)
                                moveDownButton.forceActiveFocus()
                        }
                        QQC2.ToolTip.text: text
                        QQC2.ToolTip.visible: hovered
                    }
                    QQC2.ToolButton {
                        id: moveDownButton
                        icon.name: "go-down"
                        display: QQC2.AbstractButton.IconOnly
                        text: i18n("Move down")
                        enabled: page.canMove(providerRow.providerId, 1)
                        onClicked: {
                            page.moveProvider(providerRow.providerId, 1)
                            if (!moveDownButton.enabled && moveUpButton.enabled)
                                moveUpButton.forceActiveFocus()
                        }
                        QQC2.ToolTip.text: text
                        QQC2.ToolTip.visible: hovered
                    }
                    QQC2.Switch {
                        text: i18n("Track")
                        checked: page.contains(
                            page.tracked(),
                            providerRow.descriptor.provider_id
                        )
                        onClicked: page.setTracked(
                            providerRow.descriptor.provider_id,
                            checked
                        )
                    }
                }

                Flow {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    Repeater {
                        model: providerRow.descriptor.metrics || []

                        delegate: QQC2.CheckBox {
                            id: metricCheck
                            required property var modelData
                            text: page.metricAvailable(
                                providerRow.descriptor.provider_id,
                                metricCheck.modelData.id
                            )
                                ? metricCheck.modelData.title
                                : i18n("%1 (unavailable)", metricCheck.modelData.title)
                            opacity: page.metricAvailable(
                                providerRow.descriptor.provider_id,
                                metricCheck.modelData.id
                            ) ? 1 : 0.65
                            checked: UsageLogic.isShown(
                                page.selectedMetrics(
                                    providerRow.descriptor.provider_id
                                ),
                                metricCheck.modelData.id
                            )
                            enabled: !metricCheck.checked || !page.lastShownMetric(
                                providerRow.descriptor.provider_id,
                                metricCheck.modelData.id
                            )
                            onClicked: page.setMetric(
                                providerRow.descriptor.provider_id,
                                metricCheck.modelData.id,
                                checked
                            )
                        }
                    }
                }
            }
        }

        footer: ColumnLayout {
            width: providerList.width
            spacing: Kirigami.Units.largeSpacing

            QQC2.Label {
                visible: page.statusMessage !== ""
                Layout.fillWidth: true
                textFormat: Text.PlainText
                text: page.statusMessage
                wrapMode: Text.WordWrap
                opacity: 0.72
            }

            Kirigami.Heading {
                Layout.topMargin: Kirigami.Units.largeSpacing
                level: 2
                text: i18n("Hover popup")
            }

            Kirigami.FormLayout {
                Layout.fillWidth: true

                RowLayout {
                    Kirigami.FormData.label: i18n("Panel icon:")
                    spacing: Kirigami.Units.smallSpacing

                    QQC2.CheckBox {
                        objectName: "tooltipUsageChoice"
                        enabled: page.cfg_showUsageTab
                        text: i18n("Show usage when hovering over the panel icon")
                        checked: page.cfg_tooltipShowsUsage
                        onToggled: page.cfg_tooltipShowsUsage = checked
                    }
                    Kirigami.ContextualHelpButton {
                        toolTipText: i18n("Percentages follow General → Display: Left shows \"62% left\", Used shows \"38% used\".")
                    }
                }

                RowLayout {
                    Kirigami.FormData.label: i18n("Readings:")
                    spacing: Kirigami.Units.smallSpacing

                    QQC2.CheckBox {
                        objectName: "tooltipSameChoice"
                        enabled: page.tooltipReadingsEnabled
                        text: i18n("Same as the Usage tab")
                        checked: page.tooltipChoice === null
                        onToggled: page.setTooltipSame(checked)
                    }
                    Kirigami.ContextualHelpButton {
                        toolTipText: i18n("Same as the Usage tab shows the readings ticked above, or each provider's main reading while all of its readings are ticked. Turn it off to choose the hover popup's readings for each tracked provider here. Claude Code has no daily limit: its Session is the 5-hour window, Weekly the 7-day one.")
                    }
                }

                Repeater {
                    model: page.tooltipChoice === null ? [] : page.tooltipProviders

                    delegate: RowLayout {
                        id: tooltipProviderRow
                        required property var modelData
                        Kirigami.FormData.label: i18nc("@label provider name", "%1:", tooltipProviderRow.modelData.display_name)
                        spacing: Kirigami.Units.smallSpacing

                        Repeater {
                            model: tooltipProviderRow.modelData.metrics || []

                            delegate: QQC2.CheckBox {
                                id: tooltipMetricCheck
                                required property var modelData
                                objectName: "tooltipMetric_" + tooltipProviderRow.modelData.provider_id
                                    + "_" + tooltipMetricCheck.modelData.id
                                enabled: page.tooltipReadingsEnabled
                                text: tooltipMetricCheck.modelData.title
                                checked: TooltipLogic.isChosen(page.tooltipChoice,
                                    tooltipProviderRow.modelData.provider_id, tooltipMetricCheck.modelData.id)
                                onToggled: page.setTooltipMetric(tooltipProviderRow.modelData.provider_id,
                                    tooltipMetricCheck.modelData.id, checked)
                            }
                        }
                    }
                }
            }
            Item {
                implicitHeight: Kirigami.Units.largeSpacing
            }
        }
    }
}
