import QtQuick
import QtTest

TestCase {
    id: testCase
    name: "UsageRing"
    width: 64
    height: 64
    when: windowShown

    Component {
        id: ringFactory
        Loader {
            source: "../../plasmoid/contents/ui/UsageRing.qml"
        }
    }

    function makeRing(properties) {
        var loader = createTemporaryObject(ringFactory, testCase)
        verify(loader, "created")
        tryCompare(loader, "status", Loader.Ready)
        var ring = loader.item
        ring.width = 22
        ring.height = 22
        for (var key in properties)
            ring[key] = properties[key]
        return ring
    }

    function test_sweepFollowsTheFraction() {
        var ring = makeRing({fraction: 0.5})
        compare(ring.sweep, 180)
        ring.fraction = 1
        compare(ring.sweep, 360)
        ring.fraction = 0
        compare(ring.sweep, 0)
    }

    // A sliver stays visible; an empty ring stays empty.
    function test_minimumSweepOnlyAboveZero() {
        var ring = makeRing({fraction: 0.001})
        compare(ring.sweep, ring.minimumSweep)
        ring.fraction = 0
        compare(ring.sweep, 0)
    }

    function test_arcs() {
        var ring = makeRing({fraction: 0.25, ringWidth: 2, ringColor: "#00aa00", trackColor: "#333333"})
        compare(ring.data.length, 2)
        var track = ring.data[0]
        var arc = ring.data[1]
        verify(Qt.colorEqual(track.strokeColor, "#333333"), "track color")
        verify(Qt.colorEqual(arc.strokeColor, "#00aa00"), "arc color")
        compare(track.strokeWidth, 2)
        compare(arc.strokeWidth, 2)
        compare(track.pathElements[0].sweepAngle, 360)
        compare(arc.pathElements[0].sweepAngle, 90)
        compare(arc.pathElements[0].startAngle, -90)
    }

    // The stroke stays inside the item in a small and a tall box.
    function test_ringFitsItsBox() {
        var ring = makeRing({fraction: 1, ringWidth: 2})
        compare(ring.radius, 10)
        ring.width = 48
        ring.height = 22
        compare(ring.radius, 10)
        var arc = ring.data[1].pathElements[0]
        compare(arc.centerX, 24)
        compare(arc.centerY, 11)
    }

    function test_staleDims() {
        var ring = makeRing({})
        compare(ring.opacity, 1)
        ring.stale = true
        verify(ring.opacity < 1 && ring.opacity > 0, "dimmed: " + ring.opacity)
    }
}
