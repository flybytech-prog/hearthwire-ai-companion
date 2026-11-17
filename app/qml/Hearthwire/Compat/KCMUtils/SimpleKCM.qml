import QtQuick
import QtQuick.Controls as T
import Hearthwire.Compat.Kirigami as Kirigami

// KCM.SimpleKCM: a scrolling page. Its first visual child is the content,
// as wide as the page; other children (Connections, DataSource, Timer)
// just live there.
T.Page {
    id: page
    default property alias kcmData: content.data
    readonly property alias flickable: flick
    property bool unsavedChanges: false
    property int extraFooterTopPadding: 0

    padding: 0
    background: null

    contentItem: Flickable {
        id: flick
        clip: true
        contentWidth: width
        contentHeight: page.mainItem ? page.mainItem.implicitHeight + 2 * Kirigami.Units.largeSpacing : 0
        boundsBehavior: Flickable.StopAtBounds
        T.ScrollBar.vertical: T.ScrollBar {}

        Item {
            id: content
            x: Kirigami.Units.largeSpacing
            y: Kirigami.Units.largeSpacing
            width: flick.width - 2 * Kirigami.Units.largeSpacing
            height: page.mainItem ? page.mainItem.implicitHeight : 0
        }
    }

    readonly property Item mainItem: content.children.length > 0 ? content.children[0] : null
    onMainItemChanged: {
        if (page.mainItem)
            page.mainItem.width = Qt.binding(function () { return content.width })
    }
}
