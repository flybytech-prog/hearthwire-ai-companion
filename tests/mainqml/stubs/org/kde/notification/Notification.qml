import QtQml
import HearthwireStubs

// Never reaches the session bus; sendEvent() only records what was asked.
QtObject {
    // tst_main_wiring.qml checks this: the real type has no such property.
    property bool isStub: true

    // The real KNotification values.
    enum Urgency { LowUrgency = 10, NormalUrgency = 50 }

    property string componentName
    property string eventId
    property string iconName
    property int urgency
    property bool autoDelete
    property string title
    property string text

    function sendEvent() {
        SentNotifications.record(this)
    }
}
