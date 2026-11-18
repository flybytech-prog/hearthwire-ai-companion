import QtQuick
import QtQuick.Controls as T

// KCM.ScrollViewKCM: a page around one scrolling view (`view`), with any
// other children above it in header/footer as the page sets them.
// The view (a ListView) is the ScrollView's own Flickable, as in Kirigami.
// A view still at its top stays there while its header grows (the header's
// content arrives after the first layout); otherwise ListView keeps its
// old position and the top of the header is cut off. Once the user
// scrolls, the position is theirs.
T.Page {
    id: page
    property Flickable view: null
    property bool unsavedChanges: false
    property int extraFooterTopPadding: 0
    readonly property Item flickable: page.view
    // The view is at its top (and kept there).
    property bool atTop: true

    padding: 0
    background: null

    contentItem: T.ScrollView {
        id: scroller
        clip: true
    }
    function place() {
        if (page.view && scroller.contentItem !== page.view)
            scroller.contentItem = page.view
    }
    onViewChanged: page.place()
    Component.onCompleted: page.place()

    Connections {
        target: page.view
        function onOriginYChanged() {
            if (page.atTop)
                page.view.contentY = page.view.originY
        }
        function onContentYChanged() {
            page.atTop = Math.abs(page.view.contentY - page.view.originY) < 1
        }
    }
}
