import QtQml

// One page of the settings dialog; source is relative to config.qml.
QtObject {
    property string name
    property string icon
    property string source
    property string pluginName
    property string configUiModule
    property string configUiComponent
    property bool visible: true
    property bool includeMargins: true
}
