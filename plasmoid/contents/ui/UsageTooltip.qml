pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import org.kde.plasma.components as PlasmaComponents
import org.kde.kirigami as Kirigami

// The panel icon's hover popup while it shows usage: the title, then each
// provider's name in bold with one reading per line (a dot in the
// reading's level colour, name left, value right). main.qml passes
// TooltipLogic.tooltipSections() and the Usage tab's colours; every text
// here is plain text.
Item {
    id: tip

    property string title: ""
    // [{name, items: [{title, value, level}]}]
    property var sections: []
    // The user's colours for the levels (main.qml: normalUsageColor and so on).
    property color normalColor: Kirigami.Theme.positiveTextColor
    property color warningColor: Kirigami.Theme.neutralTextColor
    property color criticalColor: Kirigami.Theme.negativeTextColor

    // At most 24 grid units wide; long names and titles elide.
    readonly property real maximumColumnWidth: Kirigami.Units.gridUnit * 24 - Kirigami.Units.largeSpacing * 2

    implicitWidth: column.width + Kirigami.Units.largeSpacing * 2
    implicitHeight: column.implicitHeight + Kirigami.Units.largeSpacing * 2
    Layout.minimumWidth: implicitWidth
    Layout.minimumHeight: implicitHeight
    Layout.maximumWidth: implicitWidth
    Layout.maximumHeight: implicitHeight

    LayoutMirroring.enabled: Application.layoutDirection === Qt.RightToLeft
    LayoutMirroring.childrenInherit: true

    Kirigami.Theme.colorSet: Kirigami.Theme.Window
    Kirigami.Theme.inherit: false

    ColumnLayout {
        id: column
        objectName: "tooltipColumn"
        x: Kirigami.Units.largeSpacing
        y: Kirigami.Units.largeSpacing
        width: Math.min(column.implicitWidth, tip.maximumColumnWidth)
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Heading {
            level: 3
            Layout.fillWidth: true
            elide: Text.ElideRight
            textFormat: Text.PlainText
            text: tip.title
            visible: text !== ""
        }

        Repeater {
            model: tip.sections

            delegate: ColumnLayout {
                id: section
                required property var modelData
                required property int index
                objectName: "tooltipSection"
                Layout.fillWidth: true
                Layout.topMargin: section.index > 0 ? Kirigami.Units.smallSpacing : 0
                spacing: 0

                PlasmaComponents.Label {
                    objectName: "tooltipProvider"
                    Layout.fillWidth: true
                    textFormat: Text.PlainText
                    font.bold: true
                    elide: Text.ElideRight
                    text: section.modelData.name
                }

                Repeater {
                    model: section.modelData.items

                    delegate: RowLayout {
                        id: reading
                        required property var modelData
                        objectName: "tooltipReading"
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing

                        // Money and credits have no level: a clear dot keeps the columns.
                        Rectangle {
                            objectName: "tooltipReadingDot"
                            Layout.alignment: Qt.AlignVCenter
                            implicitWidth: Math.round(Kirigami.Units.gridUnit / 2)
                            implicitHeight: implicitWidth
                            radius: width / 2
                            color: tip.levelColor(reading.modelData.level)
                        }
                        PlasmaComponents.Label {
                            objectName: "tooltipReadingTitle"
                            Layout.fillWidth: true
                            textFormat: Text.PlainText
                            opacity: 0.75
                            elide: Text.ElideRight
                            text: reading.modelData.title
                        }
                        PlasmaComponents.Label {
                            objectName: "tooltipReadingValue"
                            Layout.leftMargin: Kirigami.Units.gridUnit - reading.spacing
                            textFormat: Text.PlainText
                            horizontalAlignment: Text.AlignRight
                            text: reading.modelData.value
                        }
                    }
                }
            }
        }
    }

    function levelColor(level) {
        if (level === "critical")
            return tip.criticalColor
        if (level === "warning")
            return tip.warningColor
        if (level === "normal")
            return tip.normalColor
        return "transparent"
    }
}
