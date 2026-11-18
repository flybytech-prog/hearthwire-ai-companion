import QtQuick.Templates as T
import QtQuick.Controls.Material as Material

// The app style (Hearthwire.Style, Material behind it for every other
// control): a ComboBox is as wide as its widest item, so a closed one shows
// its whole text ("As when clicked", not "As when cli…"). Kirigami's own
// style does the same; Material's default is the current text only.
Material.ComboBox {
    implicitContentWidthPolicy: T.ComboBox.WidestText
}
