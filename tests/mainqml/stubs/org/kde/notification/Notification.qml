import QtQml

// Never reaches the session bus.
QtObject {
    // tst_main_wiring.qml checks this: the real type has no such property.
    property bool isStub: true

    enum Urgency { NormalUrgency }

    property string componentName
    property string eventId
    property string iconName
    property int urgency
    property bool autoDelete
    property string title
    property string text

    function sendEvent() {
    }
}
