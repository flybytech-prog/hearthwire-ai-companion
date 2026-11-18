import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import QtTest
import Hearthwire.Compat.Kirigami as Kirigami

// Round R2: the FormLayout stand-in's wide and narrow modes (as Kirigami's).
Item {
    id: root
    width: 900
    height: 700

    Kirigami.FormLayout {
        id: form
        width: root.width

        QQC2.TextField {
            id: field
            Kirigami.FormData.label: "A rather long label:"
            implicitWidth: 200
        }
        QQC2.CheckBox {
            id: box
            Kirigami.FormData.label: "Other:"
            text: "Option"
        }
        // Fills the width and wraps: it must not make the form narrow.
        QQC2.Label {
            id: wrapping
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: "long text ".repeat(100)
        }
        // A row of controls that fills the width (as configGeneral's): it
        // counts with its minimum width (review-4 S1).
        RowLayout {
            id: controls
            Kirigami.FormData.label: "Controls:"
            Layout.fillWidth: true
            QQC2.TextField {
                id: wideField
                implicitWidth: 260
            }
            QQC2.Button {
                id: rowEnd
                text: "Info"
            }
        }
        Kirigami.Separator {
            id: section
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: "Section"
        }
        QQC2.TextArea {
            id: area
            Kirigami.FormData.label: "Notes:"
            implicitWidth: 200
            implicitHeight: 200
        }
    }

    TestCase {
        name: "FormLayout"
        when: windowShown

        function labelOf(item) {
            for (var i = 0; i < form.rows.length; i++) {
                if (form.rows[i].item === item)
                    return form.rows[i].label
            }
            return null
        }

        function initTestCase() {
            tryVerify(function () { return form.rows.length === 6 })
        }

        function init() {
            root.width = 900
            tryVerify(function () { return form.wideMode })
            wait(50)
        }

        function test_wideImplicitWidthIgnoresFillingFields() {
            verify(form.wideImplicitWidth > 200, "width " + form.wideImplicitWidth)
            // The wrapping label (minimum 0) does not count...
            verify(form.wideImplicitWidth < 800, "width " + form.wideImplicitWidth)
            compare(form.implicitWidth, form.wideImplicitWidth)
        }

        // ...a fillWidth RowLayout counts with its minimum width.
        function test_aFillingRowCountsWithItsMinimum() {
            var label = labelOf(controls)
            verify(controls.Layout.minimumWidth >= 260)
            verify(form.wideImplicitWidth >= label.implicitWidth + Kirigami.Units.largeSpacing + controls.Layout.minimumWidth,
                   form.wideImplicitWidth + " < " + label.implicitWidth + " + " + controls.Layout.minimumWidth)
        }

        function rightEdge(item) {
            return rowEnd.mapToItem(form, rowEnd.width, 0).x
        }

        // At exactly its wide width, and in narrow mode just under it,
        // nothing extends past the form.
        function test_nothingPastTheEdge() {
            root.width = form.wideImplicitWidth
            tryVerify(function () { return form.wideMode })
            wait(50)
            verify(rightEdge() <= form.width + 1, rightEdge() + " > " + form.width)
            root.width = form.wideImplicitWidth - 1
            tryVerify(function () { return !form.wideMode })
            wait(50)
            verify(rightEdge() <= form.width + 1, rightEdge() + " > " + form.width)
        }

        // Measured again when a field grows (through Qt.callLater).
        function test_remeasuredWhenAFieldGrows() {
            var before = form.wideImplicitWidth
            wideField.implicitWidth = 400
            tryVerify(function () { return form.wideImplicitWidth >= before + 139 }, 1000,
                      "width " + form.wideImplicitWidth + " from " + before)
            wideField.implicitWidth = 260
            tryCompare(form, "wideImplicitWidth", before)
        }

        function test_wide() {
            var label = labelOf(field)
            verify(label !== null && label.visible)
            var l = label.mapToItem(root, 0, 0)
            var f = field.mapToItem(root, 0, 0)
            verify(l.x + label.width <= f.x, "label beside the field")
            fuzzyCompare(l.y + label.height / 2, f.y + field.height / 2, 2)
            compare(label.horizontalAlignment, Text.AlignRight)
            // A tall field: its label at the top.
            var areaLabel = labelOf(area)
            var a = area.mapToItem(root, 0, 0)
            var al = areaLabel.mapToItem(root, 0, 0)
            verify(al.y - a.y <= Kirigami.Units.smallSpacing + 1, "label at the top: " + (al.y - a.y))
            // A section heading and its separator span both columns.
            var heading = labelOf(section)
            verify(heading.visible)
            compare(heading.Layout.columnSpan, 2)
        }

        function test_narrow() {
            root.width = form.wideImplicitWidth - 1
            tryVerify(function () { return !form.wideMode })
            wait(50)
            var label = labelOf(field)
            var l = label.mapToItem(root, 0, 0)
            var f = field.mapToItem(root, 0, 0)
            verify(l.y + label.height <= f.y, "label above the field")
            fuzzyCompare(l.x, f.x, 1)
            compare(label.horizontalAlignment, Text.AlignLeft)
            compare(labelOf(section).Layout.columnSpan, 1)
            // An unlabelled field takes no label row.
            verify(!labelOf(wrapping).visible)
            // Wide again.
            root.width = form.wideImplicitWidth
            tryVerify(function () { return form.wideMode })
        }
    }
}
