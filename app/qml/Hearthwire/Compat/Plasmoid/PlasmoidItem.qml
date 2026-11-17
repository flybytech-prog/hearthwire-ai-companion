import QtQuick

// PlasmoidItem: main.qml's root. The app window (AppWindow.qml) creates
// fullRepresentation in itself and keeps expanded while it is shown; the
// compact and tooltip parts have no panel to live in.
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
    property Item fullRepresentationItem: null
    property Item compactRepresentationItem: null
    property int switchWidth: 0
    property int switchHeight: 0
}
