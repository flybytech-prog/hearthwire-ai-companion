.pragma library
// Where a link the user chose goes: the system browser, through Qt. Only
// ChatWebView calls it, and only for an https address the user confirmed.
// The Plasma widget and the hearthwire-hyprland app use this same file
// unchanged (the app build refuses any other bytes).
function open(url) { Qt.openUrlExternally(url) }
