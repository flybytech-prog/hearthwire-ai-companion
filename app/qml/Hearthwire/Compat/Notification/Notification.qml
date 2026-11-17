import QtQml

// Notification (KNotification): SPIKE: sendEvent() is counted, nothing is
// shown; the Notifier (later) replaces it.
QtObject {
    enum Urgency { DefaultUrgency = -1, LowUrgency = 10, NormalUrgency = 50, HighUrgency = 70, CriticalUrgency = 90 }

    property string componentName
    property string eventId
    property string iconName
    property int urgency: Notification.DefaultUrgency
    property bool autoDelete: true
    property string title
    property string text
    property int sent: 0

    signal closed()

    function sendEvent() {
        sent += 1
    }
    function close() {
        closed()
    }
}
