import QtQuick
import QtQuick.Controls as T

// Kirigami.ContextualHelpButton: shows toolTipText on hover or click.
T.ToolButton {
    id: button
    property string toolTipText
    property bool toolTipVisible: false
    icon.name: "help-contextual"
    display: T.AbstractButton.IconOnly
    text: "?"
    checkable: true
    onClicked: button.toolTipVisible = button.checked
    Accessible.description: button.toolTipText
    T.ToolTip.text: button.toolTipText
    T.ToolTip.visible: button.hovered || button.toolTipVisible
    T.ToolTip.delay: button.toolTipVisible ? 0 : Units.toolTipDelay
}
