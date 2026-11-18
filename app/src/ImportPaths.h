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
//
// Further code-loading variables of the libraries under Qt are dropped too
// (review-4 LOW-1): with a GTK platform theme (QT_QPA_PLATFORMTHEME=gtk3)
// GTK and GIO load modules from GTK_PATH, GTK_MODULES, GTK3_MODULES,
// GTK_EXE_PREFIX, GTK_IM_MODULE_FILE, GIO_EXTRA_MODULES, GIO_MODULE_DIR,
// GDK_PIXBUF_MODULE_FILE and GDK_PIXBUF_MODULEDIR; and Qt's own
// QML_XHR_ALLOW_FILE_READ / _WRITE would let QML read or write local files
// with XMLHttpRequest. And the -platformpluginpath argument names a plugin
// folder as QT_QPA_PLATFORM_PLUGIN_PATH does: the app refuses to start with
// it (LOW-2). What none of this covers: whoever sets the session
// environment can also set LD_PRELOAD; the session environment as a whole
// must be trusted.
#pragma once

#include <QCoreApplication>
#include <QStringList>

#include <string_view>

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

// Before QGuiApplication is made (the platform theme loads GTK there).
inline void hwDropEnvironmentModulePaths()
{
    for (const char *name : {"GTK_PATH", "GTK_MODULES", "GTK3_MODULES", "GTK_EXE_PREFIX", "GTK_IM_MODULE_FILE",
                             "GIO_EXTRA_MODULES", "GIO_MODULE_DIR", "GDK_PIXBUF_MODULE_FILE", "GDK_PIXBUF_MODULEDIR",
                             "QML_XHR_ALLOW_FILE_READ", "QML_XHR_ALLOW_FILE_WRITE"})
        qunsetenv(name);
}

// Whether argv names a plugin folder (-platformpluginpath or
// --platformpluginpath, alone or with =value): the app does not start then.
inline bool hwRefusedArgument(int argc, char **argv)
{
    for (int i = 1; i < argc; ++i) {
        if (!argv[i])
            continue;
        std::string_view word(argv[i]);
        if (word.substr(0, 2) == "--")
            word.remove_prefix(2);
        else if (word.substr(0, 1) == "-")
            word.remove_prefix(1);
        else
            continue;
        constexpr std::string_view name("platformpluginpath");
        if (word.substr(0, name.size()) == name && (word.size() == name.size() || word[name.size()] == '='))
            return true;
    }
    return false;
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
