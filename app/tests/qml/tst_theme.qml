import QtQuick
import QtTest
import Hearthwire.Compat.Kirigami as Kirigami

// Round R2: Kirigami.Theme's colour sets and inheritance in the stand-in.
Item {
    id: root

    Item {
        id: plain
    }
    Item {
        id: view
        Kirigami.Theme.colorSet: Kirigami.Theme.View
        Kirigami.Theme.inherit: false
        Item {
            id: inheriting
        }
        Item {
            id: own
            Kirigami.Theme.colorSet: Kirigami.Theme.Selection
        }
        // Under a View item, no set of its own and inherit: false: Window,
        // not the parent's View (review-4 N2).
        Item {
            id: notInheriting
            Kirigami.Theme.inherit: false
        }
    }
    Item {
        id: standalone
        Kirigami.Theme.inherit: false
    }

    TestCase {
        name: "Theme"

        function test_sets() {
            compare(plain.Kirigami.Theme.colorSet, Kirigami.Theme.Window)
            compare(view.Kirigami.Theme.colorSet, Kirigami.Theme.View)
            compare(inheriting.Kirigami.Theme.colorSet, Kirigami.Theme.View)
            compare(own.Kirigami.Theme.colorSet, Kirigami.Theme.Selection)
            compare(standalone.Kirigami.Theme.colorSet, Kirigami.Theme.Window)
            compare(notInheriting.Kirigami.Theme.colorSet, Kirigami.Theme.Window)
            verify(Qt.colorEqual(notInheriting.Kirigami.Theme.backgroundColor, plain.Kirigami.Theme.backgroundColor))
        }

        function test_colours() {
            verify(!Qt.colorEqual(view.Kirigami.Theme.backgroundColor, plain.Kirigami.Theme.backgroundColor))
            verify(Qt.colorEqual(inheriting.Kirigami.Theme.backgroundColor, view.Kirigami.Theme.backgroundColor))
            verify(Qt.colorEqual(own.Kirigami.Theme.backgroundColor, plain.Kirigami.Theme.highlightColor))
            verify(Qt.colorEqual(own.Kirigami.Theme.textColor, plain.Kirigami.Theme.highlightedTextColor))
        }

        function test_everySet() {
            var sets = ["View", "Window", "Button", "Selection", "Tooltip", "Complementary", "Header"]
            var backgrounds = []
            for (var i = 0; i < sets.length; i++) {
                var item = Qt.createQmlObject("import QtQuick; import Hearthwire.Compat.Kirigami as Kirigami; Item { Kirigami.Theme.inherit: false; Kirigami.Theme.colorSet: Kirigami.Theme." + sets[i] + " }", root)
                compare(item.Kirigami.Theme.colorSet, Kirigami.Theme[sets[i]])
                verify(item.Kirigami.Theme.textColor.a > 0)
                verify(item.Kirigami.Theme.backgroundColor.a > 0)
                backgrounds.push(String(item.Kirigami.Theme.backgroundColor))
                item.destroy()
            }
            // Selection's background is the accent, unlike Window's.
            verify(backgrounds[3] !== backgrounds[1])
        }
    }
}
