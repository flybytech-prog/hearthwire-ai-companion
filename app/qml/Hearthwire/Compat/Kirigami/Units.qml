pragma Singleton
import QtQuick

// Kirigami.Units: Kirigami 6's values, gridUnit from the font height.
QtObject {
    readonly property FontMetrics metrics: FontMetrics {}
    readonly property int gridUnit: Math.ceil(metrics.height)
    readonly property int smallSpacing: 4
    readonly property int mediumSpacing: 6
    readonly property int largeSpacing: 8
    readonly property int cornerRadius: 5
    readonly property int veryShortDuration: 50
    readonly property int shortDuration: 100
    readonly property int longDuration: 200
    readonly property int veryLongDuration: 400
    readonly property int humanMoment: 2000
    readonly property int toolTipDelay: 700
    readonly property IconSizes iconSizes: IconSizes {}
}
