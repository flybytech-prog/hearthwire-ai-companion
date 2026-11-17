import QtQuick
import QtQuick.Controls as T

// Kirigami.Heading: a label sized by level (Kirigami 6's factors).
T.Label {
    id: heading
    property int level: 1
    property int type: 0
    readonly property var factors: [1.35, 1.35, 1.20, 1.15, 1.10, 1.0]
    font.pointSize: Theme.defaultFont.pointSize * heading.factors[Math.max(0, Math.min(5, heading.level))]
    font.weight: heading.type === 1 ? Font.DemiBold : Font.Normal
    color: Theme.textColor
    wrapMode: Text.NoWrap
}
