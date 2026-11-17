import QtQuick

// Kirigami.WheelHandler: every wheel event over target is reported first
// (wheel(event), with Kirigami's fields: x, y, angleDelta, pixelDelta,
// buttons, modifiers, inverted, accepted); unless a handler sets accepted,
// the handler then scrolls a Flickable target itself, as Kirigami does.
// No smoothing animation (Kirigami's is optional).
Item {
    id: handler
    property Item target
    property bool filterMouseEvents: false
    property bool keyNavigationEnabled: false
    // Kirigami's defaults: 20 px per line, 3 lines per wheel step (Qt's
    // default wheelScrollLines).
    property real verticalStepSize: 60
    property real horizontalStepSize: 60
    signal wheel(var wheel)

    parent: handler.target
    anchors.fill: parent
    z: 1

    function scroll(event) {
        var flickable = handler.target as Flickable
        if (!flickable)
            return false
        var dy = event.pixelDelta.y !== 0 ? event.pixelDelta.y : event.angleDelta.y / 120 * handler.verticalStepSize
        var dx = event.pixelDelta.x !== 0 ? event.pixelDelta.x : event.angleDelta.x / 120 * handler.horizontalStepSize
        if (event.inverted) {
            dy = -dy
            dx = -dx
        }
        var top = flickable.originY - flickable.topMargin
        var bottom = Math.max(top, flickable.originY + flickable.contentHeight + flickable.bottomMargin - flickable.height)
        var left = flickable.originX - flickable.leftMargin
        var right = Math.max(left, flickable.originX + flickable.contentWidth + flickable.rightMargin - flickable.width)
        var y = Math.max(top, Math.min(bottom, flickable.contentY - dy))
        var x = Math.max(left, Math.min(right, flickable.contentX - dx))
        var moved = y !== flickable.contentY || x !== flickable.contentX
        flickable.contentY = y
        flickable.contentX = x
        return moved
    }

    // Passed as an object (a JS object would reach the handlers as a copy,
    // and their `accepted` would be lost), like Kirigami's WheelEvent.
    QtObject {
        id: report
        property real x
        property real y
        property point angleDelta
        property point pixelDelta
        property int buttons
        property int modifiers
        property bool inverted
        property bool accepted
    }

    WheelHandler {
        target: null
        onWheel: (event) => {
            report.x = event.x
            report.y = event.y
            report.angleDelta = event.angleDelta
            report.pixelDelta = event.pixelDelta
            report.buttons = event.buttons
            report.modifiers = event.modifiers
            report.inverted = event.inverted
            report.accepted = false
            handler.wheel(report)
            if (!report.accepted)
                handler.scroll(report)
            event.accepted = true
        }
    }
}
