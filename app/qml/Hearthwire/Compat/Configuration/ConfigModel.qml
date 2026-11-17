import QtQml

// Plasma's ConfigModel as config.qml uses it: a list of ConfigCategory.
QtObject {
    default property list<QtObject> categories
    readonly property int count: categories.length
    function get(index) {
        return categories[index]
    }
}
