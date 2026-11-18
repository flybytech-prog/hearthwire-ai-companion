import QtQml

// Notification (KNotification): sendEvent() hands the event to the
// Notifier (Notifier.h), which shows it through the desktop's notification
// daemon in the app, or only counts it (QML tests, fixture builds, no
// session bus). No actions. As in KNotification, autoDelete (the default)
// destroys the object once the event is sent.
QtObject {
    id: notification

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
        Notifier.send(notification.eventId, notification.title, notification.text, notification.urgency)
        notification.sent += 1
        if (notification.autoDelete)
            Qt.callLater(notification.destroy)
    }
    function close() {
        closed()
    }
}
