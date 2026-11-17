import QtQuick.Controls as T

// PlasmaCore.Action (a QAction in Plasma): text, icon.name, enabled,
// visible and triggered are what the plasmoid uses.
T.Action {
    property bool visible: true
    property bool isSeparator: false
    property int priority: 1
}
