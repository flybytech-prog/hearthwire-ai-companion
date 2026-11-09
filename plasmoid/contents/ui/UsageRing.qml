import QtQuick
import QtQuick.Shapes

// The panel icon's usage ring: a full track and an arc from the top,
// clockwise, for one reading. No text; main.qml's ringState and the panel's
// size set it, so nothing here reads the configuration or the theme.
Shape {
    id: ring

    // 0 to 1, as UsageLogic.ringFraction gives it.
    property real fraction: 0
    property color ringColor: "transparent"
    property color trackColor: "transparent"
    property real ringWidth: 2
    // The last good reading: the ring dims so it reads as old.
    property bool stale: false

    // A sliver of usage must still be seen, as the bars' minimum width does.
    readonly property real minimumSweep: 15
    readonly property real sweep: ring.fraction > 0
        ? Math.min(360, Math.max(ring.minimumSweep, ring.fraction * 360)) : 0
    readonly property real radius: Math.max(0, (Math.min(ring.width, ring.height) - ring.ringWidth) / 2)

    opacity: ring.stale ? 0.5 : 1
    preferredRendererType: Shape.CurveRenderer

    ShapePath {
        strokeColor: ring.trackColor
        strokeWidth: ring.ringWidth
        fillColor: "transparent"
        capStyle: ShapePath.FlatCap
        PathAngleArc {
            centerX: ring.width / 2
            centerY: ring.height / 2
            radiusX: ring.radius
            radiusY: ring.radius
            startAngle: -90
            sweepAngle: 360
        }
    }

    ShapePath {
        strokeColor: ring.ringColor
        strokeWidth: ring.ringWidth
        fillColor: "transparent"
        capStyle: ShapePath.FlatCap
        PathAngleArc {
            centerX: ring.width / 2
            centerY: ring.height / 2
            radiusX: ring.radius
            radiusY: ring.radius
            startAngle: -90
            sweepAngle: ring.sweep
        }
    }
}
