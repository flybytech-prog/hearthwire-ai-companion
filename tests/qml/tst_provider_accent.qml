import QtQuick
import QtTest
import "../../plasmoid/contents/ui/ProviderCatalog.js" as Catalog
import "../../plasmoid/contents/ui/ProviderAccent.js" as ProviderAccent

// U1: the Usage tab's accent strips: a light and a dark colour per catalog
// provider, picked by the background, and readable on both.
TestCase {
    name: "ProviderAccent"

    function linear(channel) {
        return channel <= 0.03928 ? channel / 12.92 : Math.pow((channel + 0.055) / 1.055, 2.4)
    }

    function luminance(hex) {
        var colour = Qt.color(hex)
        return 0.2126 * linear(colour.r) + 0.7152 * linear(colour.g) + 0.0722 * linear(colour.b)
    }

    function contrast(first, second) {
        var a = luminance(first)
        var b = luminance(second)
        return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
    }

    function accentOn(providerId, background) {
        var colour = Qt.color(background)
        return ProviderAccent.accentFor(providerId, colour.r, colour.g, colour.b)
    }

    function test_everyCatalogProviderHasBoth() {
        var ids = Catalog.providerIds()
        compare(Object.keys(ProviderAccent.ACCENTS).sort(), ids.slice().sort())
        for (var index = 0; index < ids.length; index++) {
            var light = accentOn(ids[index], "#ffffff")
            var dark = accentOn(ids[index], "#000000")
            verify(/^#[0-9a-f]{6}$/.test(light), ids[index] + " " + light)
            verify(/^#[0-9a-f]{6}$/.test(dark), ids[index] + " " + dark)
            verify(light !== dark, ids[index])
            // Not the catalog's near-black grok colour.
            verify(light !== "#111111" && dark !== "#111111", ids[index])
        }
    }

    // Breeze light and dark window and view colours.
    function test_readableOnBreeze() {
        var ids = Catalog.providerIds()
        for (var index = 0; index < ids.length; index++) {
            var backgrounds = ["#ffffff", "#eff0f1", "#202326", "#31363b", "#1b1e20"]
            for (var at = 0; at < backgrounds.length; at++) {
                var accent = accentOn(ids[index], backgrounds[at])
                verify(contrast(accent, backgrounds[at]) >= 3, ids[index] + " on " + backgrounds[at])
            }
        }
    }

    function test_luminanceThreshold() {
        compare(ProviderAccent.accentFor("claude", 1, 1, 1), ProviderAccent.ACCENTS.claude.light)
        compare(ProviderAccent.accentFor("claude", 0.5, 0.5, 0.5), ProviderAccent.ACCENTS.claude.light)
        compare(ProviderAccent.accentFor("claude", 0.49, 0.49, 0.49), ProviderAccent.ACCENTS.claude.dark)
        compare(ProviderAccent.accentFor("claude", 0, 0, 0), ProviderAccent.ACCENTS.claude.dark)
        // Out of range channels are clamped.
        compare(ProviderAccent.accentFor("claude", 5, 5, 5), ProviderAccent.ACCENTS.claude.light)
        compare(ProviderAccent.accentFor("claude", -1, -1, -1), ProviderAccent.ACCENTS.claude.dark)
    }

    function test_unknownOrOddInput() {
        compare(ProviderAccent.accentFor("nope", 1, 1, 1), "")
        compare(ProviderAccent.accentFor("toString", 1, 1, 1), "")
        compare(ProviderAccent.accentFor("__proto__", 1, 1, 1), "")
        compare(ProviderAccent.accentFor(undefined, 1, 1, 1), "")
        compare(ProviderAccent.accentFor("claude", NaN, 1, 1), "")
        compare(ProviderAccent.accentFor("claude", "1", 1, 1), "")
        compare(ProviderAccent.accentFor("claude"), "")
    }
}
