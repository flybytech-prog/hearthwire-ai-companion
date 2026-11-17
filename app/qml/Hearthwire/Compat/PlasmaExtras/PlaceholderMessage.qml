import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as T
import Hearthwire.Compat.Kirigami as Kirigami

// PlasmaExtras.PlaceholderMessage: icon, heading, explanation, then any
// children, centered.
ColumnLayout {
    id: message
    property string iconName
    property string text
    property string explanation
    property int type: 0
    property T.Action helpfulAction: null

    spacing: Kirigami.Units.largeSpacing

    Kirigami.Icon {
        Layout.alignment: Qt.AlignHCenter
        Layout.preferredWidth: Kirigami.Units.iconSizes.huge
        Layout.preferredHeight: Kirigami.Units.iconSizes.huge
        source: message.iconName
        visible: message.iconName.length > 0
        opacity: 0.6
    }
    Kirigami.Heading {
        Layout.fillWidth: true
        level: 3
        text: message.text
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        opacity: 0.75
        visible: message.text.length > 0
    }
    T.Label {
        Layout.fillWidth: true
        text: message.explanation
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        color: Kirigami.Theme.textColor
        opacity: 0.75
        visible: message.explanation.length > 0
    }
    T.Button {
        Layout.alignment: Qt.AlignHCenter
        action: message.helpfulAction
        visible: message.helpfulAction !== null && message.helpfulAction.enabled
    }
}
