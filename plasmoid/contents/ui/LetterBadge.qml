import QtQuick
import org.kde.kirigami as Kirigami
import "ChatSites.js" as ChatSites

// An added chat site's icon: the first letter of its name in a circle, in
// the theme's highlight colors. Plain text only, never an image and never
// anything from the network. The name beside it says the same, so screen
// readers skip it.
Rectangle {
    id: badge

    property string name: ""
    property real size: Kirigami.Units.iconSizes.smallMedium

    implicitWidth: badge.size
    implicitHeight: badge.size
    radius: badge.size / 2
    color: Kirigami.Theme.highlightColor
    Accessible.ignored: true

    Text {
        anchors.centerIn: parent
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        textFormat: Text.PlainText
        text: ChatSites.badgeLetter(badge.name)
        color: Kirigami.Theme.highlightedTextColor
        font.pixelSize: Math.max(1, Math.round(badge.size * 0.6))
        font.bold: true
        elide: Text.ElideNone
        clip: true
        Accessible.ignored: true
    }
}
