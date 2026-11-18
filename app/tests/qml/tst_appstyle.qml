import QtQuick
import QtQuick.Controls
import QtQuick.Templates as T
import QtTest
import Hearthwire.Compat.KCMUtils as KCM

// Round R2: the app style (a ComboBox shows its widest item whole) and
// ScrollViewKCM (a list still at its top stays there while its header
// grows, as configUsage.qml's does).
Item {
    id: root
    width: 600
    height: 400

    ComboBox {
        id: combo
        model: ["Chat", "As when clicking the icon"]
        currentIndex: 0
    }
    TextMetrics {
        id: longest
        font: combo.font
        text: "As when clicking the icon"
    }

    KCM.ScrollViewKCM {
        id: page
        y: 100
        width: 600
        height: 300
        view: ListView {
            id: list
            model: 50
            delegate: Text {
                required property int index
                text: "row " + index
                height: 30
            }
            header: Rectangle {
                id: header
                objectName: "header"
                width: 600
                height: 40
                property alias grow: grow
                Timer {
                    id: grow
                    interval: 50
                    onTriggered: header.height = 200
                }
            }
        }
    }

    TestCase {
        name: "AppStyle"
        when: windowShown

        function test_comboShowsItsWidestItem() {
            compare(combo.implicitContentWidthPolicy, T.ComboBox.WidestText)
            verify(combo.implicitContentWidth >= longest.advanceWidth,
                   combo.implicitContentWidth + " < " + longest.advanceWidth)
        }

        function test_listIsTheScrollViewsFlickable() {
            compare(page.contentItem.contentItem, list)
        }

        function test_listStaysAtItsTopWhileTheHeaderGrows() {
            tryVerify(function () { return list.headerItem !== null })
            list.headerItem.grow.start()
            tryVerify(function () { return list.headerItem.height === 200 })
            wait(50)
            compare(list.contentY, list.originY)
            var top = list.headerItem.mapToItem(page, 0, 0)
            fuzzyCompare(top.y, 0, 1)
            // Scrolled by the user: the position is theirs.
            list.contentY = list.originY + 100
            list.headerItem.height = 250
            wait(50)
            verify(list.contentY > list.originY + 1, "not pulled back to the top")
        }
    }
}
