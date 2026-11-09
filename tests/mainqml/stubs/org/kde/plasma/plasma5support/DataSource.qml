import QtQml

// Records what would run; the helper is never started.
QtObject {
    // tst_main_wiring.qml checks this: the real type has no such property.
    property bool isStub: true

    property string engine
    property var connectedSources: []

    signal newData(string source, var data)

    function connectSource(source) {
        connectedSources = connectedSources.concat([source])
    }

    function disconnectSource(source) {
        connectedSources = connectedSources.filter(function (name) { return name !== source })
    }
}
