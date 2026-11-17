import QtQuick
import QtQuick.Controls as T
import Hearthwire.Compat.Kirigami as Kirigami

// PlasmaExtras.PlasmoidHeading: a tool bar on the window color with a
// separator line under it (the default Header location).
T.ToolBar {
    enum Location { Header = 0, Footer = 1 }
    property int location: PlasmoidHeading.Header
    padding: Kirigami.Units.smallSpacing
    background: Rectangle {
        color: Kirigami.Theme.backgroundColor
        Kirigami.Separator {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
        }
    }
}
