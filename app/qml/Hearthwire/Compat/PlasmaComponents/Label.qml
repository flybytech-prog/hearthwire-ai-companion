import QtQuick
import QtQuick.Controls as T
import Hearthwire.Compat.Kirigami as Kirigami

// The defaults Plasma's PlasmaComponents.Label sets on QQC2's Label.
T.Label {
    horizontalAlignment: Text.AlignLeft
    activeFocusOnTab: false
    color: Kirigami.Theme.textColor
    linkColor: Kirigami.Theme.linkColor
    opacity: enabled ? 1 : 0.75
    Accessible.role: Accessible.StaticText
    Accessible.name: text
}
