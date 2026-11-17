import QtQuick
import QtQuick.Controls as T
import QtQuick.Controls.impl
import QtQuick.Controls.Material

// Plasma's PlasmaComponents.ToolButton is QQC2's with the Plasma style; here the
// app's Material style draws it. The content is Material's own, except that an
// icon-only button's label item holds no text: Plasma's content item names
// its text labelText, so the plasmoid (and its tests, which look for shown
// items by their text) never meet a second "text" inside an icon button.
T.ToolButton {
    id: control

    contentItem: IconLabel {
        spacing: control.spacing
        mirrored: control.mirrored
        display: control.display

        icon: control.icon
        defaultIconColor: !control.enabled ? control.Material.hintTextColor
            : control.checked || control.highlighted ? control.Material.accent : control.Material.foreground
        text: control.display === T.AbstractButton.IconOnly ? "" : control.text
        font: control.font
        color: defaultIconColor
    }
}
