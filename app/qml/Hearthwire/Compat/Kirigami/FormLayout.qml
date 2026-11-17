import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as T

// Kirigami.FormLayout: two columns, each child's Kirigami.FormData.label
// right-aligned beside it; isSection children span both columns with their
// label as a heading. Children are moved into the grid in their order,
// later ones (a Repeater's) included.
// SPIKE: no narrow (one-column) mode and no centering.
Item {
    id: form

    property bool wideMode: true
    default property alias formChildren: holder.data

    implicitWidth: grid.implicitWidth
    implicitHeight: grid.implicitHeight
    Layout.preferredHeight: grid.implicitHeight

    Item {
        id: holder
        visible: false
        onChildrenChanged: Qt.callLater(form.relayout)
    }

    GridLayout {
        id: grid
        width: form.width
        columns: 2
        columnSpacing: Units.largeSpacing
        rowSpacing: Units.smallSpacing
    }

    Component {
        id: labelComponent
        T.Label {
            property Item buddy
            property FormData formData
            readonly property bool section: formData !== null && formData.isSection
            text: formData ? formData.label : ""
            visible: buddy !== null && buddy.visible && (text.length > 0 || !section)
            color: Theme.textColor
            font.weight: section ? Font.DemiBold : Font.Normal
            font.pointSize: section ? Theme.defaultFont.pointSize * 1.15 : Theme.defaultFont.pointSize
            horizontalAlignment: section ? Text.AlignLeft : Text.AlignRight
            Layout.columnSpan: section ? 2 : 1
            Layout.alignment: section ? Qt.AlignLeft | Qt.AlignBottom : Qt.AlignRight | Qt.AlignVCenter
            Layout.topMargin: section ? Units.largeSpacing : 0
        }
    }

    function relayout() {
        var items = []
        for (var i = 0; i < holder.children.length; i++)
            items.push(holder.children[i])
        for (var j = 0; j < items.length; j++) {
            var item = items[j]
            var data = FormSupport.formData(item)
            var label = labelComponent.createObject(grid, { buddy: item, formData: data })
            item.parent = grid
            if (data !== null && data.isSection) {
                // The section's own item (a Separator) sits under the heading.
                FormSupport.setAttached(item, "Layout.columnSpan", 2, form)
                FormSupport.setAttached(item, "Layout.fillWidth", true, form)
            }
        }
    }
}
