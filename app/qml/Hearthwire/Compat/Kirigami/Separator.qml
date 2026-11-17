import QtQuick

// Kirigami.Separator: a one-pixel line in the text color, faded.
Rectangle {
    property int weight: 0
    implicitWidth: 1
    implicitHeight: 1
    color: Qt.alpha(Theme.textColor, 0.2)
}
