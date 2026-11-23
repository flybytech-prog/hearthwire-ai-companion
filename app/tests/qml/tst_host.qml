import QtQuick
import QtTest
import "../synced/Host.js" as Host

// Task 012 R4 P2a: the app's copy of the plasmoid's Host.js says the app
// runs the pages (sync_plasmoid.py writes it with "var isApp = true").
// CMake runs this file from a folder next to the synced plasmoid
// (app/tests/CMakeLists.txt), so the import is the app's own copy.
TestCase {
    name: "AppHost"

    function test_theAppsHostJsSaysApp() {
        compare(typeof Host.isApp, "boolean")
        compare(Host.isApp, true)
    }
}
