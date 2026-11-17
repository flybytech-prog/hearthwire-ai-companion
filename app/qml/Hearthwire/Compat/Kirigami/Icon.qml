import QtQuick
import QtQuick.Effects

// Kirigami.Icon: a theme icon name (image://icon/), or a URL. color with
// isMask tints it.
Item {
    id: icon

    enum Status { Null = 0, Ready = 1, Loading = 2, Error = 3 }

    property var source
    property color color: "transparent"
    property bool isMask: false
    property bool active: false
    property bool selected: false
    property bool animated: false
    property bool roundToIconSize: true
    property string fallback: "unknown"
    property string placeholder: "image-png"
    readonly property int status: !icon.imageUrl.toString() ? Icon.Null : image.status
    readonly property url imageUrl: {
        var text = icon.source === undefined || icon.source === null ? "" : icon.source.toString()
        if (text.length === 0)
            return ""
        if (text.indexOf(":") > 0 || text.charAt(0) === "/")
            return text
        return "image://icon/" + text
    }
    readonly property bool tinted: icon.isMask || icon.color.a > 0

    implicitWidth: Units.iconSizes.medium
    implicitHeight: Units.iconSizes.medium

    Image {
        id: image
        anchors.fill: parent
        source: icon.imageUrl
        sourceSize: Qt.size(Math.max(1, icon.width), Math.max(1, icon.height))
        fillMode: Image.PreserveAspectFit
        visible: !icon.tinted
        opacity: icon.active ? 0.85 : 1
    }
    MultiEffect {
        anchors.fill: image
        source: image
        visible: icon.tinted
        colorization: 1
        colorizationColor: icon.color.a > 0 ? icon.color : Theme.textColor
        brightness: 1
    }
}
