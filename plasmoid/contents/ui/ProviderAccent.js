.pragma library

// The Usage tab's provider accent strips: pure rules, no QML state.
// UsageView.qml passes the provider id and the background color in.
// Decorative only: the strip carries no meaning the text doesn't.
//
// ProviderCatalog.js's colors are brand colors and some don't read on
// every background (grok's is near black), so each catalog provider has its
// own pair here: "light" for light backgrounds and "dark" for dark ones,
// both at least 3:1 against Breeze's light and dark window colors.
var ACCENTS = {
    claude: {light: "#b4532a", dark: "#e8926f"},
    codex: {light: "#0a7d61", dark: "#3cc9a1"},
    cursor: {light: "#4646c0", dark: "#9b9bf2"},
    antigravity: {light: "#1a62d1", dark: "#8ab4f8"},
    copilot: {light: "#7340d0", dark: "#b494f4"},
    devin: {light: "#0a6f9e", dark: "#5cc3f0"},
    grok: {light: "#4d4d4d", dark: "#c4c4c4"}
}

function channel(value) {
    var number = Number(value)
    return Math.max(0, Math.min(1, number))
}

// The accent "#rrggbb" for a catalog provider on a background of r, g, b
// (from 0 to 1): the dark variant when the background's luminance is below
// 0.5, as UsageLogic.defaultNormalColor decides. "" for an unknown id or
// a background that isn't three numbers.
function accentFor(providerId, red, green, blue) {
    if (typeof providerId !== "string" || !Object.prototype.hasOwnProperty.call(ACCENTS, providerId))
        return ""
    var parts = [red, green, blue]
    for (var index = 0; index < parts.length; index++) {
        if (typeof parts[index] !== "number" || !isFinite(parts[index]))
            return ""
    }
    var luminance = channel(red) * 0.2126 + channel(green) * 0.7152 + channel(blue) * 0.0722
    var pair = ACCENTS[providerId]
    return luminance < 0.5 ? pair.dark : pair.light
}
