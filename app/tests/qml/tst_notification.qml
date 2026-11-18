import QtQuick
import QtTest
import Hearthwire.Compat.Notification

// Task 012 R3.2: the Notification stand-in hands sendEvent() to the
// Notifier (here in Record mode: nothing leaves the process).
TestCase {
    id: root

    name: "Notification"

    property QtObject held: null

    Component {
        id: notificationComponent

        Notification {
            componentName: "hearthwire"
            eventId: "usageLow"
            iconName: "hearthwire"
            autoDelete: false
            title: "Claude is running low"
            text: "Session: 20% left"
        }
    }

    function make(properties) {
        var notification = notificationComponent.createObject(root, properties || {})
        verify(notification !== null)
        return notification
    }

    function test_recordMode() {
        compare(Notifier.mode, Notifier.Record)
    }

    function test_urgency_data() {
        return [
            {tag: "low", urgency: Notification.LowUrgency, bus: 0},
            {tag: "default", urgency: Notification.DefaultUrgency, bus: 1},
            {tag: "normal", urgency: Notification.NormalUrgency, bus: 1},
            {tag: "high", urgency: Notification.HighUrgency, bus: 1},
            {tag: "critical", urgency: Notification.CriticalUrgency, bus: 2}
        ]
    }

    function test_urgency(data) {
        var notification = make({urgency: data.urgency})
        notification.sendEvent()
        compare(Notifier.lastCall.urgency, data.bus)
        notification.destroy()
    }

    function test_sentCount() {
        var notification = make()
        var before = Notifier.count
        notification.sendEvent()
        notification.sendEvent()
        compare(notification.sent, 2)
        compare(Notifier.count, before + 2)
        notification.destroy()
    }

    // As KNotification: autoDelete destroys the object after the send, on
    // a later turn (main.qml never touches it again).
    function test_autoDelete() {
        root.held = make({autoDelete: true})
        root.held.sendEvent()
        verify(root.held !== null)
        tryVerify(function () { return root.held === null })

        root.held = make({autoDelete: false})
        root.held.sendEvent()
        wait(50)
        verify(root.held !== null)
        root.held.destroy()
        tryVerify(function () { return root.held === null })
    }

    // Title and text go on as main.qml built them (markup handling is the
    // Notifier's, on the bus only).
    function test_titleAndTextUnchanged() {
        var notification = make({eventId: "settingsBackup", title: "Settings backed up",
                                 text: "Codex &amp; Claude: &lt;b&gt;"})
        notification.sendEvent()
        compare(Notifier.lastCall.eventId, "settingsBackup")
        compare(Notifier.lastCall.title, "Settings backed up")
        compare(Notifier.lastCall.text, "Codex &amp; Claude: &lt;b&gt;")
        notification.destroy()
    }
}
