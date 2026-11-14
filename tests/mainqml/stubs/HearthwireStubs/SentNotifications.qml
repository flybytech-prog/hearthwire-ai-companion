pragma Singleton
import QtQml

// Every notification the stub was asked to send, for the wiring tests.
QtObject {
    property var sent: []

    function record(notification) {
        sent = sent.concat([{
            componentName: notification.componentName,
            eventId: notification.eventId,
            iconName: notification.iconName,
            urgency: notification.urgency,
            autoDelete: notification.autoDelete,
            title: notification.title,
            text: notification.text,
            hasActions: notification.actions !== undefined || notification.defaultAction !== undefined
                        || notification.urls !== undefined
        }])
    }
}
