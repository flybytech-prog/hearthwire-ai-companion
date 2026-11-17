// The QML import paths of the app (and its QML test runner). Qt's default
// list also takes QML_IMPORT_PATH and QML2_IMPORT_PATH from the environment,
// in front of Qt's own QML folder, so an inherited entry could put another
// QtQuick.Controls, Material style or other module in place of Qt's. The app
// drops both variables before any engine exists, and the binary's own
// folder from the list; what is left is the compiled-in modules (the
// stand-ins, the synced plasmoid, the app: qrc:/qt/qml) and Qt's folders as
// QLibraryInfo / qt.conf name them.
//
// The same for Qt plugins: QT_PLUGIN_PATH and QT_QPA_PLATFORM_PLUGIN_PATH
// would make Qt load plugins (platform, style, image formats, ...) from any
// folder named there, so the app drops both before QGuiApplication exists.
// Qt's own plugin folder (and theming plugins installed there, such as a
// platform theme) still loads; only the environment's extra folders are gone.
#pragma once

#include <QCoreApplication>
#include <QStringList>

// Before the first QML engine is made.
inline void hwDropEnvironmentImportPaths()
{
    qunsetenv("QML_IMPORT_PATH");
    qunsetenv("QML2_IMPORT_PATH");
}

// Before QGuiApplication is made (Qt reads both when it first needs a plugin).
inline void hwDropEnvironmentPluginPaths()
{
    qunsetenv("QT_PLUGIN_PATH");
    qunsetenv("QT_QPA_PLATFORM_PLUGIN_PATH");
}

// `defaults`: a new engine's importPathList(), made after
// hwDropEnvironmentImportPaths().
inline QStringList hwImportPaths(const QStringList &defaults)
{
    QStringList paths = defaults;
    if (QCoreApplication::instance())
        paths.removeAll(QCoreApplication::applicationDirPath());
    return paths;
}
