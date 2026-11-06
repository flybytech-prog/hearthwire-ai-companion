import QtQuick
import QtQuick.Layouts
import QtTest
import org.kde.kirigami as Kirigami
import "../../plasmoid/contents/ui"

// The hover popup layout: title, each provider in bold, one reading per
// line; plain text only, so names can't turn into markup.
TestCase {
    name: "UsageTooltip"
    when: windowShown
    width: 400
    height: 400

    Component {
        id: tooltipComponent
        UsageTooltip {}
    }

    function findAll(item, objectName, found) {
        found = found || []
        if (item.objectName === objectName)
            found.push(item)
        for (var index = 0; index < item.children.length; index++)
            findAll(item.children[index], objectName, found)
        return found
    }

    function test_layout() {
        var tip = createTemporaryObject(tooltipComponent, this, {
            title: "Hearthwire",
            sections: [
                {name: "Claude Code", items: [{title: "Session", value: "100% left"},
                                              {title: "Weekly", value: "41% left"}]},
                {name: "Codex", items: [{title: "Weekly", value: "80% left"}]}
            ]
        })
        verify(tip)
        var providers = findAll(tip, "tooltipProvider")
        compare(providers.length, 2)
        compare(providers[0].text, "Claude Code")
        verify(providers[0].font.bold)
        compare(providers[0].textFormat, Text.PlainText)
        var titles = findAll(tip, "tooltipReadingTitle")
        var values = findAll(tip, "tooltipReadingValue")
        compare(titles.map(function (label) { return label.text }), ["Session", "Weekly", "Weekly"])
        compare(values.map(function (label) { return label.text }), ["100% left", "41% left", "80% left"])
        values.concat(titles).forEach(function (label) { compare(label.textFormat, Text.PlainText) })
        // Values line up on the right edge, below their provider.
        tryVerify(function () { return tip.implicitWidth > 0 && tip.implicitHeight > 0 })
        var right0 = values[0].mapToItem(tip, values[0].width, 0).x
        var right1 = values[1].mapToItem(tip, values[1].width, 0).x
        fuzzyCompare(right0, right1, 1)
        verify(values[0].mapToItem(tip, 0, 0).y > providers[0].mapToItem(tip, 0, 0).y)
        verify(values[1].mapToItem(tip, 0, 0).y > values[0].mapToItem(tip, 0, 0).y)
    }

    function test_markupStaysText() {
        var tip = createTemporaryObject(tooltipComponent, this, {
            sections: [{name: "<b>x</b>", items: [{title: "<img src=a>", value: "1%"}]}]
        })
        var providers = findAll(tip, "tooltipProvider")
        compare(providers[0].text, "<b>x</b>")
        compare(providers[0].textFormat, Text.PlainText)
    }

    // Long names and titles elide; the popup stays at most 24 grid units wide.
    function test_longNamesElide() {
        var long = ""
        for (var index = 0; index < 30; index++)
            long += "Provider name "
        var tip = createTemporaryObject(tooltipComponent, this, {
            title: long,
            sections: [{name: long, items: [{title: long, value: "41% left"}]}]
        })
        verify(tip)
        tryVerify(function () { return tip.implicitWidth > 0 })
        verify(tip.implicitWidth <= Kirigami.Units.gridUnit * 24)
        compare(tip.Layout.maximumWidth, tip.implicitWidth)
        var provider = findAll(tip, "tooltipProvider")[0]
        var title = findAll(tip, "tooltipReadingTitle")[0]
        var value = findAll(tip, "tooltipReadingValue")[0]
        compare(provider.elide, Text.ElideRight)
        compare(title.elide, Text.ElideRight)
        tryVerify(function () { return provider.truncated && title.truncated })
        compare(provider.text, long)
        compare(provider.textFormat, Text.PlainText)
        compare(title.textFormat, Text.PlainText)
        // The value is still shown whole, inside the popup.
        verify(!value.truncated)
        compare(value.text, "41% left")
        verify(value.mapToItem(tip, value.width, 0).x <= tip.implicitWidth)
        // Short content keeps its own width.
        var small = createTemporaryObject(tooltipComponent, this, {
            sections: [{name: "Codex", items: [{title: "Weekly", value: "80% left"}]}]
        })
        tryVerify(function () { return small.implicitWidth > 0 })
        verify(small.implicitWidth < Kirigami.Units.gridUnit * 24)
        verify(!findAll(small, "tooltipProvider")[0].truncated)
    }

    // T1: a dot per reading in the level's colour; money and credits get a
    // clear one, so every title starts in the same column.
    function test_levelDots() {
        var tip = createTemporaryObject(tooltipComponent, this, {
            normalColor: "#00ff00", warningColor: "#ffaa00", criticalColor: "#ff0000",
            sections: [
                {name: "Claude Code", items: [
                    {title: "Session", value: "5% left", level: "critical"},
                    {title: "Weekly", value: "30% left", level: "warning"},
                    {title: "Sonnet", value: "90% left", level: "normal"},
                    {title: "Extra Usage", value: "$4.00", level: ""}
                ]},
                {name: "Codex", items: [{title: "Credits", value: "12"}]}
            ]
        })
        verify(tip)
        tryVerify(function () { return tip.implicitWidth > 0 })
        var dots = findAll(tip, "tooltipReadingDot")
        var titles = findAll(tip, "tooltipReadingTitle")
        compare(dots.length, 5)
        verify(Qt.colorEqual(dots[0].color, "#ff0000"))
        verify(Qt.colorEqual(dots[1].color, "#ffaa00"))
        verify(Qt.colorEqual(dots[2].color, "#00ff00"))
        compare(dots[3].color.a, 0)
        compare(dots[4].color.a, 0)
        for (var index = 0; index < dots.length; index++) {
            verify(dots[index].width > 0 && dots[index].width === dots[index].height)
            fuzzyCompare(titles[index].mapToItem(tip, 0, 0).x, titles[0].mapToItem(tip, 0, 0).x, 0.5)
            // The dot comes before its title (after it in right-to-left).
            verify(dots[index].mapToItem(tip, dots[index].width, 0).x <= titles[index].mapToItem(tip, 0, 0).x)
        }
        // The user changing a colour repaints the dots.
        tip.criticalColor = "#0000ff"
        verify(Qt.colorEqual(dots[0].color, "#0000ff"))
    }

    function test_empty() {
        var tip = createTemporaryObject(tooltipComponent, this, {sections: []})
        compare(findAll(tip, "tooltipProvider").length, 0)
    }
}
