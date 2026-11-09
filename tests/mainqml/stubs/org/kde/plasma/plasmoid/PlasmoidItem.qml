import QtQuick

// The PlasmoidItem properties main.qml sets; nothing shows them.
Item {
    property bool expanded: false
    property bool activationTogglesExpanded: true
    property bool hideOnWindowDeactivate: true
    property string toolTipMainText
    property string toolTipSubText
    property int toolTipTextFormat
    property Item toolTipItem
    property Component compactRepresentation
    property Component fullRepresentation
}
