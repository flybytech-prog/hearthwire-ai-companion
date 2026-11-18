pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as T

// Kirigami.FormLayout: two columns, each child's Kirigami.FormData.label
// right-aligned beside it; isSection children span both columns with their
// label as a heading. Children are moved into the grid in their order,
// later ones (a Repeater's) included.
// Narrow mode, as Kirigami: when the form is narrower than its two-column
// width (wideImplicitWidth, below), it becomes one column with each label above
// its field, left-aligned; empty labels then take no row. A label beside a
// tall field (a text area, a list) sits at the field's top.
// Not copied: Kirigami's centring of a wide form and twinFormLayouts.
Item {
    id: form

    property bool wideMode: form.width >= form.wideImplicitWidth
    default property alias formChildren: holder.data
    // One entry per moved child: { item, label, section }.
    property var rows: []
    // The width both columns need side by side: the widest label, plus
    // the widest field. A field that fills the width (a RowLayout of
    // controls, a wrapping text) counts with its Layout.minimumWidth, the
    // least it can be laid out in; any other field with its implicitWidth.
    // A plain property set by measure(), never a binding: a binding that
    // reads Layout.minimumWidth re-ran while a page went away and asked a
    // grid that still listed a dying item (SIGSEGV, review-4 S2). measure()
    // runs once in relayout() and afterwards only through Qt.callLater,
    // which never runs inside a teardown; the connections go with the form.
    property real wideImplicitWidth: 0

    function measure() {
        var labels = 0
        var fields = 0
        var spanned = 0
        for (var i = 0; i < form.rows.length; i++) {
            var row = form.rows[i]
            if (!row.item || !row.item.visible)
                continue
            var itemWidth = row.item.Layout.fillWidth ? row.item.Layout.minimumWidth : row.item.implicitWidth
            if (row.section) {
                spanned = Math.max(spanned, row.label.implicitWidth)
            } else {
                labels = Math.max(labels, row.label.implicitWidth)
                fields = Math.max(fields, itemWidth)
            }
        }
        form.wideImplicitWidth = Math.ceil(Math.max(spanned, labels + grid.columnSpacing + fields))
    }

    function measureLater() {
        Qt.callLater(form.measure)
    }

    implicitWidth: form.wideImplicitWidth
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
        columns: form.wideMode ? 2 : 1
        columnSpacing: Units.largeSpacing
        rowSpacing: Units.smallSpacing
    }

    Component {
        id: labelComponent
        T.Label {
            property Item buddy
            property FormData formData
            readonly property bool section: formData !== null && formData.isSection
            // Taller than a row of controls (a text area, a list): the
            // label goes to the field's top.
            readonly property bool tall: buddy !== null && buddy.implicitHeight > Units.gridUnit * 3.5
            text: formData ? formData.label : ""
            visible: buddy !== null && buddy.visible
                     && (form.wideMode ? (text.length > 0 || !section) : text.length > 0)
            color: Theme.textColor
            wrapMode: form.wideMode ? Text.NoWrap : Text.WordWrap
            font.weight: section ? Font.DemiBold : Font.Normal
            font.pointSize: section ? Theme.defaultFont.pointSize * 1.15 : Theme.defaultFont.pointSize
            horizontalAlignment: section || !form.wideMode ? Text.AlignLeft : Text.AlignRight
            Layout.columnSpan: section && form.wideMode ? 2 : 1
            Layout.fillWidth: !form.wideMode
            Layout.alignment: section ? Qt.AlignLeft | Qt.AlignBottom
                : !form.wideMode ? Qt.AlignLeft | Qt.AlignBottom
                : tall ? Qt.AlignRight | Qt.AlignTop : Qt.AlignRight | Qt.AlignVCenter
            Layout.topMargin: section ? Units.largeSpacing
                : !form.wideMode ? Units.smallSpacing
                : tall ? Units.smallSpacing : 0
        }
    }

    // A section's own item (a Separator) spans the row in wide mode.
    function placeSections() {
        for (var i = 0; i < form.rows.length; i++) {
            var row = form.rows[i]
            if (row.section && row.item)
                FormSupport.setAttached(row.item, "Layout.columnSpan", form.wideMode ? 2 : 1, form)
        }
    }

    onWideModeChanged: form.placeSections()
    // At once, as Kirigami lays out while the page is made: a later first
    // layout made a ListView header grow under its first rows. Children
    // added later (a Repeater's) come through onChildrenChanged.
    Component.onCompleted: form.relayout()

    function relayout() {
        var items = []
        for (var i = 0; i < holder.children.length; i++)
            items.push(holder.children[i])
        var rows = form.rows.slice()
        for (var j = 0; j < items.length; j++) {
            var item = items[j]
            var data = FormSupport.formData(item)
            var label = labelComponent.createObject(grid, { buddy: item, formData: data }) as T.Label
            item.parent = grid
            var section = data !== null && data.isSection
            if (section)
                FormSupport.setAttached(item, "Layout.fillWidth", true, form)
            rows.push({ item: item, label: label, section: section })
            // Disconnected by Qt when the form goes (receiver form).
            item.implicitWidthChanged.connect(form, form.measureLater)
            item.visibleChanged.connect(form, form.measureLater)
            label.implicitWidthChanged.connect(form, form.measureLater)
        }
        form.rows = rows
        form.placeSections()
        form.measure()
    }
}
