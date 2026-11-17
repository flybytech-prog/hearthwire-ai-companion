import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as T

// Kirigami.InlineMessage: a tinted box with an icon, wrapped text and its
// actions as buttons.
T.Control {
    id: message

    property int type: MessageType.Information
    property string text
    property list<QtObject> actions
    property bool showCloseButton: false
    property int position: 0
    readonly property color tone: message.type === MessageType.Error ? Theme.negativeTextColor
        : message.type === MessageType.Warning ? Theme.neutralTextColor
        : message.type === MessageType.Positive ? Theme.positiveTextColor
        : Theme.highlightColor
    readonly property string iconName: message.type === MessageType.Error ? "dialog-error"
        : message.type === MessageType.Warning ? "dialog-warning"
        : message.type === MessageType.Positive ? "dialog-positive"
        : "dialog-information"

    signal linkHovered(string link)
    signal linkActivated(string link)

    padding: Units.largeSpacing

    background: Rectangle {
        radius: Units.cornerRadius
        color: Qt.alpha(message.tone, 0.15)
        border.color: Qt.alpha(message.tone, 0.6)
        border.width: 1
    }

    contentItem: RowLayout {
        spacing: Units.smallSpacing
        Icon {
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: Units.iconSizes.smallMedium
            Layout.preferredHeight: Units.iconSizes.smallMedium
            source: message.iconName
        }
        T.Label {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            text: message.text
            wrapMode: Text.WordWrap
            color: Theme.textColor
            onLinkHovered: (link) => message.linkHovered(link)
            onLinkActivated: (link) => message.linkActivated(link)
        }
        Repeater {
            model: message.actions
            delegate: T.Button {
                required property var modelData
                Layout.alignment: Qt.AlignVCenter
                action: modelData
                visible: modelData.visible !== false
                flat: true
            }
        }
        T.ToolButton {
            visible: message.showCloseButton
            icon.name: "dialog-close"
            display: T.AbstractButton.IconOnly
            text: "×"
            onClicked: message.visible = false
        }
    }
}
