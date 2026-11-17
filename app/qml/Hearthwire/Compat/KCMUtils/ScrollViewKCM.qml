import QtQuick
import QtQuick.Controls as T

// KCM.ScrollViewKCM: a page around one scrolling view (`view`), with any
// other children above it in header/footer as the page sets them.
T.Page {
    id: page
    property Item view: null
    property bool unsavedChanges: false
    property int extraFooterTopPadding: 0
    readonly property Item flickable: page.view

    padding: 0
    background: null

    contentItem: T.ScrollView {
        id: scroller
        clip: true
    }
    onViewChanged: {
        if (page.view) {
            page.view.parent = scroller.contentItem
            page.view.anchors.fill = scroller.contentItem
        }
    }
}
