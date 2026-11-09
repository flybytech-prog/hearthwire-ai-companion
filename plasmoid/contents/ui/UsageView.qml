import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.extras as PlasmaExtras
import org.kde.kirigami as Kirigami
import "SnapshotLogic.js" as SnapshotLogic
import "UsageLogic.js" as UsageLogic
import "UsageHistory.js" as UsageHistory
import "ProviderCatalog.js" as Catalog
import "ProviderAccent.js" as ProviderAccent

// Usage tab body, moved verbatim from FullRepresentation.qml.
// Names, plans, captions, errors and amounts come from the helper (and so
// from provider servers): every label shows them as plain text only, never
// as rich text that could load images or links, and at most
// UsageLogic.MAX_SHOWN_CHARS long (UsageLogic.shownText).
// Settings → AI Provider Settings → Usage tab picks the providers' order,
// their readings (none ticked = all) and the compact layout.
ColumnLayout {
    id: usage

    spacing: Kirigami.Units.smallSpacing

    // Wall clock for the reset and retry countdowns, "Updated N min ago"
    // and "Next reset"; ticks only while open.
    property double nowMs: Date.now()
    // The leading accent strip of each provider section, and its gap.
    readonly property real accentWidth: Math.max(2, Math.round(Kirigami.Units.smallSpacing * 0.75))
    readonly property real accentGap: Kirigami.Units.smallSpacing
    // The narrowest fill of a bar above 0%, so its color can be seen.
    readonly property real minimumFillWidth: Kirigami.Units.gridUnit * 0.75

    Timer {
        interval: 30000
        repeat: true
        triggeredOnStart: true
        running: root.expanded
        onTriggered: usage.nowMs = Date.now()
    }

    // Refresh shows also while loading and after a failed first load.
    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        PlasmaComponents.Label {
            objectName: "usageUpdatedLabel"
            Layout.fillWidth: true
            visible: root.hasData
            textFormat: Text.PlainText
            text: usage.updatedText(root.lastUpdate.getTime(), usage.nowMs)
            opacity: 0.6
            font: Kirigami.Theme.smallFont
            elide: Text.ElideRight
        }
        Item {
            Layout.fillWidth: true
            visible: !root.hasData
        }
        PlasmaComponents.ToolButton {
            objectName: "usageRefreshButton"
            text: i18n("Refresh")
            icon.name: "view-refresh"
            enabled: !root.refreshInFlight
            onClicked: root.refresh()
        }
    }

    // The soonest reset among the readings shown below; catalog names only.
    PlasmaComponents.Label {
        objectName: "usageNextResetLabel"
        Layout.fillWidth: true
        visible: root.hasData && text !== ""
        textFormat: Text.PlainText
        text: UsageLogic.shownText(usage.nextResetText(root.shownProviders, usage.nowMs))
        opacity: 0.6
        font: Kirigami.Theme.smallFont
        elide: Text.ElideRight
    }

    // History can't be saved yet; a fixed message, never the helper's text.
    PlasmaComponents.Label {
        objectName: "usageHistoryNotice"
        Layout.fillWidth: true
        visible: text !== ""
        textFormat: Text.PlainText
        text: root.historyNotice
        wrapMode: Text.Wrap
        opacity: 0.75
        font: Kirigami.Theme.smallFont
    }

    PlasmaExtras.PlaceholderMessage {
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: !root.hasData && root.lastError !== ""
        iconName: "network-disconnect"
        text: i18n("Couldn't load usage")

        // Instead of `explanation`, whose label reads rich text.
        PlasmaComponents.Label {
            Layout.fillWidth: true
            visible: text !== ""
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            opacity: 0.75
            text: UsageLogic.shownText(root.lastError)
        }
    }

    PlasmaExtras.PlaceholderMessage {
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: !root.hasData && root.lastError === ""
        iconName: "speedometer"
        text: i18n("Loading…")
    }

    PlasmaExtras.PlaceholderMessage {
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: root.hasData
            && (root.snapshot.installed_provider_ids || []).length === 0
        iconName: "system-search"
        text: i18n("No supported tools detected")
        explanation: i18n(
            "Install or sign in to a supported AI coding tool, then refresh."
        )
    }

    PlasmaExtras.PlaceholderMessage {
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: root.hasData
            && (root.snapshot.installed_provider_ids || []).length > 0
            && (root.snapshot.providers || []).length === 0
        iconName: "view-hidden"
        text: i18n("No tracked providers")
        explanation: i18n("Choose providers in the widget settings.")
    }

    QQC2.ScrollView {
        id: providerScroll
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: root.hasData && (root.snapshot.providers || []).length > 0
        contentWidth: availableWidth
        QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff
        QQC2.ScrollBar.vertical.policy: (root.snapshot.providers || []).length > 2
            ? QQC2.ScrollBar.AsNeeded : QQC2.ScrollBar.AlwaysOff

        ColumnLayout {
            width: providerScroll.availableWidth
            spacing: root.usageCompact ? Kirigami.Units.smallSpacing : Kirigami.Units.largeSpacing

            Repeater {
                model: root.shownProviders

                delegate: ColumnLayout {
                    id: providerSection
                    required property var modelData
                    // The readings ticked in settings; [] shows them all.
                    readonly property var chosen: root.selectedMetrics(providerSection.modelData.provider_id)
                    readonly property var windows: UsageLogic.shownWindows(
                        providerSection.modelData.windows, providerSection.chosen)
                    readonly property bool billingShown: UsageLogic.showsBilling(
                        providerSection.modelData.billing_usage, providerSection.chosen)
                    // Decorative; "" (no strip) for a provider the catalog doesn't know.
                    readonly property string accent: ProviderAccent.accentFor(
                        providerSection.modelData.provider_id, Kirigami.Theme.backgroundColor.r,
                        Kirigami.Theme.backgroundColor.g, Kirigami.Theme.backgroundColor.b)
                    Layout.fillWidth: true
                    // Room for the accent strip on the leading edge.
                    Layout.leftMargin: usage.accentWidth + usage.accentGap
                    spacing: root.usageCompact ? 0 : Kirigami.Units.smallSpacing

                    RowLayout {
                        Layout.fillWidth: true
                        visible: !root.usageCompact
                        spacing: Kirigami.Units.smallSpacing

                        Kirigami.Icon {
                            source: root.providerIconSource(
                                providerSection.modelData.provider_id
                            )
                            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                            Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                            isMask: true
                            color: Kirigami.Theme.textColor
                        }
                        Kirigami.Heading {
                            Layout.fillWidth: true
                            level: 3
                            textFormat: Text.PlainText
                            text: UsageLogic.shownText(providerSection.modelData.display_name)
                            elide: Text.ElideRight
                        }
                        PlasmaComponents.Label {
                            visible: UsageLogic.shownText(providerSection.modelData.plan) !== ""
                            textFormat: Text.PlainText
                            text: UsageLogic.shownText(providerSection.modelData.plan)
                            opacity: 0.65
                            elide: Text.ElideRight
                        }
                        Kirigami.Icon {
                            visible: providerSection.modelData.status === "stale"
                            source: "data-warning"
                            Layout.preferredWidth: Kirigami.Units.iconSizes.small
                            Layout.preferredHeight: Kirigami.Units.iconSizes.small
                            color: Kirigami.Theme.neutralTextColor
                        }
                    }

                    // Compact: a small name line, no plan.
                    RowLayout {
                        Layout.fillWidth: true
                        visible: root.usageCompact
                        spacing: Kirigami.Units.smallSpacing

                        Kirigami.Icon {
                            source: root.providerIconSource(
                                providerSection.modelData.provider_id
                            )
                            Layout.preferredWidth: Kirigami.Units.iconSizes.small
                            Layout.preferredHeight: Kirigami.Units.iconSizes.small
                            isMask: true
                            color: Kirigami.Theme.textColor
                        }
                        PlasmaComponents.Label {
                            Layout.fillWidth: true
                            textFormat: Text.PlainText
                            text: UsageLogic.shownText(providerSection.modelData.display_name)
                            font.bold: true
                            elide: Text.ElideRight
                        }
                        Kirigami.Icon {
                            visible: providerSection.modelData.status === "stale"
                            source: "data-warning"
                            Layout.preferredWidth: Kirigami.Units.iconSizes.small
                            Layout.preferredHeight: Kirigami.Units.iconSizes.small
                            color: Kirigami.Theme.neutralTextColor
                        }
                    }

                    // Like a Kirigami.InlineMessage, whose label reads rich text.
                    Rectangle {
                        id: failureBox
                        readonly property bool warning: providerSection.modelData.status === "stale"
                            || providerSection.modelData.status === "rate_limited"
                        Layout.fillWidth: true
                        visible: providerSection.modelData.status !== "ok"
                        implicitHeight: failureRow.implicitHeight + Kirigami.Units.smallSpacing * 2
                        radius: Kirigami.Units.cornerRadius
                        color: failureBox.warning
                            ? Kirigami.Theme.neutralBackgroundColor
                            : Kirigami.Theme.negativeBackgroundColor
                        border.width: 1
                        border.color: failureBox.warning
                            ? Kirigami.Theme.neutralTextColor
                            : Kirigami.Theme.negativeTextColor

                        RowLayout {
                            id: failureRow
                            anchors {
                                left: parent.left
                                right: parent.right
                                verticalCenter: parent.verticalCenter
                                margins: Kirigami.Units.smallSpacing
                            }
                            spacing: Kirigami.Units.smallSpacing

                            Kirigami.Icon {
                                source: failureBox.warning ? "data-warning" : "data-error"
                                Layout.alignment: Qt.AlignTop
                                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                                Layout.preferredHeight: Kirigami.Units.iconSizes.small
                            }
                            PlasmaComponents.Label {
                                Layout.fillWidth: true
                                textFormat: Text.PlainText
                                wrapMode: Text.Wrap
                                text: usage.failureText(providerSection.modelData, usage.nowMs)
                                // Compact: one line.
                                maximumLineCount: root.usageCompact ? 1 : 2147483647
                                elide: root.usageCompact ? Text.ElideRight : Text.ElideNone
                                font: root.usageCompact ? Kirigami.Theme.smallFont : Kirigami.Theme.defaultFont
                            }
                        }
                    }

                    PlasmaComponents.Label {
                        Layout.fillWidth: true
                        visible: (providerSection.modelData.status === "ok"
                                || providerSection.modelData.status === "stale")
                            && providerSection.windows.length === 0 && !providerSection.billingShown
                            && providerSection.chosen.length > 0
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        text: i18n("None of the chosen readings is available.")
                        opacity: 0.65
                        font: Kirigami.Theme.smallFont
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        visible: !root.usageCompact
                        columns: 2
                        columnSpacing: Kirigami.Units.smallSpacing
                        rowSpacing: Kirigami.Units.smallSpacing

                        Repeater {
                            model: root.usageCompact ? [] : providerSection.windows

                            delegate: Rectangle {
                                id: quotaCard
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.preferredWidth: (
                                    providerScroll.availableWidth
                                    - Kirigami.Units.smallSpacing
                                ) / 2
                                implicitHeight: quotaContent.implicitHeight
                                    + Kirigami.Units.largeSpacing * 2
                                radius: Kirigami.Units.smallSpacing
                                color: Qt.rgba(
                                    Kirigami.Theme.textColor.r,
                                    Kirigami.Theme.textColor.g,
                                    Kirigami.Theme.textColor.b,
                                    0.055
                                )

                                ColumnLayout {
                                    id: quotaContent
                                    anchors {
                                        left: parent.left
                                        right: parent.right
                                        top: parent.top
                                        margins: Kirigami.Units.largeSpacing
                                    }
                                    spacing: Kirigami.Units.smallSpacing

                                    RowLayout {
                                        Layout.fillWidth: true
                                        PlasmaComponents.Label {
                                            Layout.fillWidth: true
                                            textFormat: Text.PlainText
                                            text: UsageLogic.shownText(quotaCard.modelData.caption)
                                            opacity: 0.72
                                            elide: Text.ElideRight
                                        }
                                        PlasmaComponents.Label {
                                            textFormat: Text.PlainText
                                            text: Math.round(root.displayedPercent(
                                                Number(quotaCard.modelData.used_percent)
                                            )) + "%"
                                            font.bold: true
                                            color: root.valueColor(
                                                Number(quotaCard.modelData.used_percent)
                                            )
                                        }
                                    }

                                    Rectangle {
                                        Layout.fillWidth: true
                                        height: Math.round(Kirigami.Units.gridUnit * 0.35)
                                        radius: height / 2
                                        color: Qt.rgba(
                                            Kirigami.Theme.textColor.r,
                                            Kirigami.Theme.textColor.g,
                                            Kirigami.Theme.textColor.b,
                                            0.14
                                        )

                                        Rectangle {
                                            objectName: "usageBarFill"
                                            width: UsageLogic.fillWidth(
                                                parent.width,
                                                root.displayedPercent(
                                                    Number(quotaCard.modelData.used_percent)
                                                ),
                                                usage.minimumFillWidth
                                            )
                                            height: parent.height
                                            radius: height / 2
                                            color: root.barColor(
                                                Number(quotaCard.modelData.used_percent)
                                            )
                                            Behavior on width {
                                                NumberAnimation {
                                                    duration: 250
                                                    easing.type: Easing.OutCubic
                                                }
                                            }
                                        }
                                    }

                                    // Seven days of this reading (opt-in, see main.qml).
                                    // Decorative; visible follows the points only: an
                                    // invisible item in a layout never gets a width.
                                    Canvas {
                                        id: sparkline
                                        objectName: "usageSparkline"
                                        readonly property real lineWidth: Math.round(Kirigami.Units.smallSpacing / 2)
                                        readonly property var points: root.historyPoints(
                                            providerSection.modelData.provider_id, quotaCard.modelData.kind)
                                        readonly property var segments: UsageHistory.sparkSegments(
                                            sparkline.points, root.historyNow, root.usageMode,
                                            sparkline.width, sparkline.height, sparkline.lineWidth)
                                        readonly property var segmentColors: sparkline.segments.map(function (segment) {
                                            return root.barColor(segment.used)
                                        })
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: Kirigami.Units.gridUnit
                                        visible: sparkline.points.length > 0
                                        Accessible.ignored: true
                                        onSegmentColorsChanged: sparkline.requestPaint()
                                        onAvailableChanged: sparkline.requestPaint()
                                        onPaint: {
                                            var context = sparkline.getContext("2d")
                                            if (!context)
                                                return
                                            context.reset()
                                            context.lineWidth = sparkline.lineWidth
                                            context.lineCap = "round"
                                            for (var index = 0; index < sparkline.segments.length; index++) {
                                                var segment = sparkline.segments[index]
                                                context.beginPath()
                                                if (segment.dot) {
                                                    context.fillStyle = sparkline.segmentColors[index]
                                                    context.arc(segment.x1, segment.y1, sparkline.lineWidth, 0, Math.PI * 2)
                                                    context.fill()
                                                } else {
                                                    context.strokeStyle = sparkline.segmentColors[index]
                                                    context.moveTo(segment.x1, segment.y1)
                                                    context.lineTo(segment.x2, segment.y2)
                                                    context.stroke()
                                                }
                                            }
                                        }
                                    }

                                    PlasmaComponents.Label {
                                        visible: text !== ""
                                        textFormat: Text.PlainText
                                        text: usage.relativeReset(
                                            quotaCard.modelData.resets_at,
                                            usage.nowMs
                                        )
                                        opacity: 0.55
                                        font: Kirigami.Theme.smallFont
                                    }
                                }
                            }
                        }

                        Rectangle {
                            id: billingCard
                            visible: providerSection.billingShown
                            Layout.fillWidth: true
                            Layout.preferredWidth: (
                                providerScroll.availableWidth
                                - Kirigami.Units.smallSpacing
                            ) / 2
                            implicitHeight: billingColumn.implicitHeight
                                + Kirigami.Units.largeSpacing * 2
                            radius: Kirigami.Units.smallSpacing
                            color: Qt.rgba(
                                Kirigami.Theme.textColor.r,
                                Kirigami.Theme.textColor.g,
                                Kirigami.Theme.textColor.b,
                                0.055
                            )

                            ColumnLayout {
                                id: billingColumn
                                anchors {
                                    left: parent.left
                                    right: parent.right
                                    top: parent.top
                                    margins: Kirigami.Units.largeSpacing
                                }
                                PlasmaComponents.Label {
                                    textFormat: Text.PlainText
                                    text: usage.billingTitle(
                                        providerSection.modelData.billing_usage
                                    )
                                    opacity: 0.72
                                }
                                PlasmaComponents.Label {
                                    textFormat: Text.PlainText
                                    text: usage.billingValue(
                                        providerSection.modelData.billing_usage
                                    )
                                    font.bold: true
                                }
                            }
                        }
                    }

                    // Compact: one slim bar per reading.
                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: root.usageCompact
                        spacing: 0

                        Repeater {
                            model: root.usageCompact ? providerSection.windows : []

                            delegate: RowLayout {
                                id: compactRow
                                required property var modelData
                                readonly property real rawUsed: Number(compactRow.modelData.used_percent)
                                Layout.fillWidth: true
                                spacing: Kirigami.Units.smallSpacing

                                PlasmaComponents.Label {
                                    Layout.preferredWidth: Kirigami.Units.gridUnit * 5
                                    textFormat: Text.PlainText
                                    text: usage.readingTitle(
                                        providerSection.modelData.provider_id, compactRow.modelData
                                    )
                                    opacity: 0.72
                                    elide: Text.ElideRight
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.alignment: Qt.AlignVCenter
                                    implicitHeight: Math.round(Kirigami.Units.gridUnit * 0.25)
                                    radius: height / 2
                                    color: Qt.rgba(
                                        Kirigami.Theme.textColor.r,
                                        Kirigami.Theme.textColor.g,
                                        Kirigami.Theme.textColor.b,
                                        0.14
                                    )

                                    Rectangle {
                                        objectName: "usageCompactFill"
                                        width: UsageLogic.fillWidth(parent.width,
                                            root.displayedPercent(compactRow.rawUsed),
                                            usage.minimumFillWidth)
                                        height: parent.height
                                        radius: height / 2
                                        color: root.barColor(compactRow.rawUsed)
                                    }
                                }
                                PlasmaComponents.Label {
                                    Layout.preferredWidth: Kirigami.Units.gridUnit * 2
                                    horizontalAlignment: Text.AlignRight
                                    textFormat: Text.PlainText
                                    text: Math.round(root.displayedPercent(compactRow.rawUsed)) + "%"
                                    font.bold: true
                                    color: root.valueColor(compactRow.rawUsed)
                                }
                                PlasmaComponents.Label {
                                    Layout.preferredWidth: Kirigami.Units.gridUnit * 3
                                    textFormat: Text.PlainText
                                    text: usage.shortReset(compactRow.modelData.resets_at, usage.nowMs)
                                    opacity: 0.55
                                    font: Kirigami.Theme.smallFont
                                    elide: Text.ElideRight
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            visible: providerSection.billingShown
                            spacing: Kirigami.Units.smallSpacing

                            PlasmaComponents.Label {
                                Layout.fillWidth: true
                                textFormat: Text.PlainText
                                text: usage.billingTitle(providerSection.modelData.billing_usage)
                                opacity: 0.72
                                elide: Text.ElideRight
                            }
                            PlasmaComponents.Label {
                                textFormat: Text.PlainText
                                text: usage.billingValue(providerSection.modelData.billing_usage)
                                font.bold: true
                            }
                        }
                    }

                    // The separator, and the accent strip next to the whole
                    // section: a child of this Item, so the layout leaves it alone.
                    Item {
                        id: sectionEnd
                        Layout.fillWidth: true
                        Layout.topMargin: root.usageCompact ? Kirigami.Units.smallSpacing : 0
                        implicitHeight: sectionSeparator.implicitHeight

                        Kirigami.Separator {
                            id: sectionSeparator
                            anchors.fill: parent
                            opacity: 0.45
                        }

                        Rectangle {
                            objectName: "providerAccent"
                            anchors {
                                right: parent.left
                                rightMargin: usage.accentGap
                                bottom: parent.bottom
                            }
                            width: usage.accentWidth
                            height: providerSection.height
                            radius: width / 2
                            visible: providerSection.accent !== ""
                            color: providerSection.accent !== "" ? providerSection.accent : "transparent"
                        }
                    }
                }
            }
        }
    }

    function failureText(providerData, nowMs) {
        var text = UsageLogic.shownText(providerData.error_message || providerData.status)
        if (providerData.status === "stale")
            text = i18n("Showing the last successful reading. %1", text)
        var retry = relativeRetry(providerData.retry_at, nowMs)
        if (retry !== "")
            text += " " + retry
        return text
    }

    function relativeReset(iso, nowMs) {
        var difference = SnapshotLogic.millisUntil(iso, nowMs)
        if (difference === null)
            return ""
        if (difference <= 0)
            return i18n("Resetting…")
        var minutes = Math.max(1, Math.round(difference / 60000))
        if (minutes < 60)
            return i18np("Resets in %1 minute", "Resets in %1 minutes", minutes)
        var hours = Math.floor(minutes / 60)
        if (hours < 24)
            return i18n("Resets in %1h %2m", hours, minutes % 60)
        var days = Math.floor(hours / 24)
        return i18n("Resets in %1d %2h", days, hours % 24)
    }

    // "Updated N min ago" from the time of the last helper reply.
    function updatedText(updatedMs, nowMs) {
        var parts = UsageLogic.updatedPhrase(updatedMs, nowMs)
        if (!parts)
            return ""
        if (parts.kind === "now")
            return i18n("Updated just now")
        if (parts.kind === "minutes")
            return i18np("Updated %1 min ago", "Updated %1 min ago", parts.minutes)
        if (parts.kind === "hours")
            return i18np("Updated %1 hour ago", "Updated %1 hours ago", parts.hours)
        return i18np("Updated %1 day ago", "Updated %1 days ago", parts.days)
    }

    // The catalog's name for a reading, else the helper's caption.
    function readingTitle(providerId, window) {
        var metric = window ? Catalog.metric(providerId, window.kind) : null
        return metric ? metric.title : UsageLogic.shownText(window && window.caption ? window.caption : "")
    }

    // "Next reset: Claude Code Session in 2h 10m" for the soonest reset of
    // the readings the tab shows, or "" when none lies ahead. The names are
    // the catalog's, never the helper's captions.
    function nextResetText(providers, nowMs) {
        var entries = []
        var list = UsageLogic.toArray(providers)
        for (var index = 0; index < list.length; index++) {
            var providerData = list[index]
            var descriptor = providerData ? Catalog.byId(providerData.provider_id) : null
            if (!descriptor)
                continue
            var windows = UsageLogic.shownWindows(
                providerData.windows, root.selectedMetrics(descriptor.provider_id))
            for (var windowIndex = 0; windowIndex < windows.length; windowIndex++) {
                var metric = Catalog.metric(descriptor.provider_id, windows[windowIndex].kind)
                var resetsAt = windows[windowIndex].resets_at
                var target = typeof resetsAt === "string" ? new Date(resetsAt).getTime() : NaN
                if (metric && isFinite(target))
                    entries.push({resetsAtMs: target, provider: descriptor.display_name, metric: metric.title})
            }
        }
        var next = UsageLogic.nextReset(entries, nowMs)
        if (!next)
            return ""
        return i18nc("@label soonest reset: provider, reading, time left", "Next reset: %1 %2 in %3",
                     next.provider, next.metric,
                     usage.countdownText(UsageLogic.shortCountdown(next.resetsAtMs, nowMs)))
    }

    // Compact: "2d 4h", "3h 5m", "12m", or "" when unknown.
    function shortReset(iso, nowMs) {
        var target = iso ? new Date(iso).getTime() : NaN
        return usage.countdownText(UsageLogic.shortCountdown(isFinite(target) ? target : null, nowMs))
    }

    // shortCountdown parts as "2d 4h", "3h 5m", "12m" or "now"; "" for null.
    function countdownText(parts) {
        if (!parts)
            return ""
        if (parts.days > 0)
            return i18nc("@label short time until reset", "%1d %2h", parts.days, parts.hours)
        if (parts.hours > 0)
            return i18nc("@label short time until reset", "%1h %2m", parts.hours, parts.minutes)
        if (parts.minutes > 0)
            return i18nc("@label short time until reset", "%1m", parts.minutes)
        return i18n("now")
    }

    function relativeRetry(iso, nowMs) {
        var difference = SnapshotLogic.millisUntil(iso, nowMs)
        if (difference === null)
            return ""
        if (difference <= 0)
            return i18n("Ready to retry.")
        var minutes = Math.max(1, Math.ceil(difference / 60000))
        if (minutes < 60)
            return i18np("Retry in %1 minute.", "Retry in %1 minutes.", minutes)
        return i18n("Retry in %1h %2m.", Math.floor(minutes / 60), minutes % 60)
    }

    function billingTitle(billing) {
        return billing && billing.kind === "flex_credit_balance"
            ? i18n("Credits") : i18n("Extra Usage")
    }

    function billingValue(billing) {
        if (!billing)
            return ""
        if (billing.kind === "bounded_spend") {
            var used = Number(billing.used_amount || 0)
            var limit = Number(billing.limit_amount || 0)
            var value = root.usageMode === "used" ? used : Math.max(limit - used, 0)
            return "$" + value.toFixed(2)
                + (root.usageMode === "used" ? " / $" + limit.toFixed(2) : "")
        }
        if (billing.kind === "unbounded_spend")
            return "$" + Number(billing.used_amount || 0).toFixed(2)
        if (billing.kind === "flex_credit_balance")
            return i18n(
                "%1 (~$%2)",
                // A number keeps i18n's locale formatting; only text is cut.
                typeof billing.remaining_credits === "number" && isFinite(billing.remaining_credits)
                    ? billing.remaining_credits : UsageLogic.shownText(billing.remaining_credits),
                Number(billing.usd_value || 0).toFixed(2)
            )
        return ""
    }
}
