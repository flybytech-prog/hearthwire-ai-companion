import QtQuick
import QtQuick.Controls as T
import Hearthwire.Compat.Kirigami as Kirigami

// Plasma's PlasmaComponents.TabBar is QQC2's with the Plasma style; here the
// app's Material style draws it. Material fills a TabBar with its primary
// color, on which the checked tab's accent label was hard to read; Plasma's
// tab bar sits on the heading's own background, so this one does too.
T.TabBar {
    background: Rectangle {
        color: Kirigami.Theme.backgroundColor
    }
}
