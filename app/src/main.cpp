// hearthwire-hyprland: runs the plasmoid's main.qml, FullRepresentation and
// its Settings pages unchanged under the Hearthwire.Compat.* stand-ins
// (task 008 plan-v1 §2.1-2.2, task 012).
//
// Settings live in ConfigStore::defaultFile(). The helper runs through
// ProcessRunner (HEARTHWIRE_FRONTEND=app, Plasmoid.id 2147483648).
//
// A fixture build (CMake -DHW_FIXTURES=ON, tests only, never shipped) runs
// no helper at all, answers from the compiled-in fixture book, and takes:
//   --config-dir DIR   keep settings.json there (default: a new temp folder)
//   --shots DIR        save usage.png and one settings-<page>.png per settings
//                      page, then quit
//   --checks           run the app checks (SpikeChecks.qml), then quit
//
// The look follows the Omarchy theme (ThemeWatcher.h) through the app's
// Qt Quick Controls style, Hearthwire.Style (Material behind it).
#include <QCommandLineParser>
#include <QDir>
#include <QGuiApplication>
#include <QIcon>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickStyle>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QtQml/qqmlextensionplugin.h>

#include <cstdio>
#include <memory>

#include "AppTools.h"
#include "ConfigStore.h"
#include "IconProvider.h"
#include "ImportPaths.h"
#include "KirigamiCompat.h"
#include "LocalizedContext.h"
#include "PlasmoidHost.h"
#include "ProcessRunner.h"
#include "ThemeWatcher.h"
#include "UrlGuard.h"

Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_KirigamiPlugin)
Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_PlasmaComponentsPlugin)
Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_PlasmaExtrasPlugin)
Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_PlasmaCorePlugin)
Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_PlasmoidPlugin)
Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_Plasma5SupportPlugin)
Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_KCMUtilsPlugin)
Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_NotificationPlugin)
Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_ConfigurationPlugin)
Q_IMPORT_QML_PLUGIN(Hearthwire_PlasmoidPlugin)
Q_IMPORT_QML_PLUGIN(Hearthwire_StylePlugin)

namespace {
void countMessages(QtMsgType type, const QMessageLogContext &context, const QString &message)
{
    if (type == QtWarningMsg || type == QtCriticalMsg || type == QtFatalMsg) {
        ++AppTools::s_warnings;
        const QByteArray category(context.category ? context.category : "");
        if (category.startsWith("qml") || category.startsWith("js") || message.contains(QLatin1String("qrc:/"))
            || message.contains(QLatin1String(".qml")))
            ++AppTools::s_qmlWarnings;
    }
    std::fprintf(stderr, "%s\n", qPrintable(qFormatLogMessage(type, context, message)));
}
}

int main(int argc, char *argv[])
{
    qInstallMessageHandler(countMessages);
    if (hwRefusedArgument(argc, argv)) {
        std::fprintf(stderr, "hearthwire-hyprland: -platformpluginpath is not accepted; Qt's plugins come only from Qt's own folder\n");
        return 2;
    }
    hwDropEnvironmentImportPaths();
    hwDropEnvironmentPluginPaths();
    hwDropEnvironmentModulePaths();
    QGuiApplication::setApplicationName(QStringLiteral("hearthwire-hyprland"));
    QGuiApplication::setApplicationVersion(QStringLiteral(HW_VERSION));
    QGuiApplication::setDesktopFileName(QStringLiteral("hearthwire-hyprland"));
    // Material, through the app's own style module (qml/Hearthwire/Style).
    // Material is also named the fallback, so it reads its settings (the
    // Dense variant below) as when it is the style itself.
    QQuickStyle::setStyle(QStringLiteral("Hearthwire.Style"));
    QQuickStyle::setFallbackStyle(QStringLiteral("Material"));
    // Desktop sizes, not touch sizes, unless the user chose otherwise.
    if (qEnvironmentVariableIsEmpty("QT_QUICK_CONTROLS_MATERIAL_VARIANT"))
        qputenv("QT_QUICK_CONTROLS_MATERIAL_VARIANT", "Dense");
    QGuiApplication app(argc, argv);
    // Some platforms (offscreen, a bare Wayland session) give no icon
    // folders; add the XDG ones so theme icons resolve.
    QStringList iconPaths = QIcon::themeSearchPaths();
    const QStringList dataIcons = QStandardPaths::locateAll(QStandardPaths::GenericDataLocation, QStringLiteral("icons"),
                                                            QStandardPaths::LocateDirectory);
    for (const QString &path : dataIcons) {
        if (!iconPaths.contains(path))
            iconPaths.append(path);
    }
    QIcon::setThemeSearchPaths(iconPaths);
    if (QIcon::themeName().isEmpty() || QIcon::themeName() == QLatin1String("hicolor"))
        QIcon::setThemeName(QStringLiteral("breeze"));
    QIcon::setFallbackThemeName(QStringLiteral("hicolor"));

    QCommandLineParser parser;
    parser.addHelpOption();
    parser.addVersionOption();
#ifdef HW_FIXTURES
    parser.addOption({QStringLiteral("config-dir"), QStringLiteral("Settings folder."), QStringLiteral("dir")});
    parser.addOption({QStringLiteral("shots"), QStringLiteral("Save screenshots there, then quit."), QStringLiteral("dir")});
    parser.addOption({QStringLiteral("checks"), QStringLiteral("Run the config dialog checks, then quit.")});
#endif
    parser.process(app);

    QString settingsFile = ConfigStore::defaultFile();
#ifdef HW_FIXTURES
    QTemporaryDir temp;
    const QString configDir = parser.isSet(QStringLiteral("config-dir")) ? parser.value(QStringLiteral("config-dir")) : temp.path();
    settingsFile = QDir(configDir).filePath(QStringLiteral("settings.json"));
    if (!ProcessRunner::useFixtures(QStringLiteral(":/hearthwire/fixtures/replies.json"))) {
        std::fprintf(stderr, "hearthwire-hyprland: the fixture book is broken\n");
        return 2;
    }
#endif

    auto *store = new ConfigStore(&app);
    if (!store->loadSchema(QStringLiteral(":/qt/qml/Hearthwire/Plasmoid/main.xml"))) {
        std::fprintf(stderr, "hearthwire-hyprland: the settings schema is missing\n");
        return 2;
    }
    // Never the file's content or path details beyond what the user knows.
    if (!store->open(settingsFile)) {
        std::fprintf(stderr, store->status() == ConfigStore::Status::Damaged
                                 ? "hearthwire-hyprland: settings.json is damaged; using defaults (it is kept as settings.json.damaged)\n"
                                 : "hearthwire-hyprland: settings.json can't be read safely; using defaults and not saving\n");
    }

    // The Omarchy theme, followed live; the built-in palette without one.
    auto *theme = new ThemeWatcher(ThemeWatcher::defaultThemeDir(), &app);
    QObject::connect(theme, &ThemeWatcher::changed, &app, [theme] { ThemePalette::instance()->setTheme(theme->source()); });
    theme->start();
    ThemePalette::instance()->setTheme(theme->source());

    auto *host = new PlasmoidHost(&app);
    host->setConfiguration(store);
    PlasmoidHost::setInstance(host);

    auto *tools = new AppTools(host, &app);
#ifdef HW_FIXTURES
    tools->shotsDir = parser.value(QStringLiteral("shots"));
    tools->checks = parser.isSet(QStringLiteral("checks"));
    tools->file = settingsFile;
#endif
    AppTools::setInstance(tools);

    int code = 0;
    {
        // Made before the engine, so it outlives it.
        std::unique_ptr<UrlGuard> guard;
        QQmlApplicationEngine engine;
        engine.setImportPathList(hwImportPaths(engine.importPathList()));
        guard = std::make_unique<UrlGuard>(engine.importPathList());
        engine.addUrlInterceptor(guard.get());
        engine.addImageProvider(QStringLiteral("icon"), new IconProvider);
        engine.rootContext()->setContextObject(new LocalizedContext(&engine));
        QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed, &app, [] { QCoreApplication::exit(3); },
                         Qt::QueuedConnection);
        engine.loadFromModule("Hearthwire.App", "AppWindow");
        code = app.exec();
        // The engine (and every DataSource, which stops its helpers) goes first.
    }
    if (AppTools::fixtures())
        std::fprintf(stderr, "hearthwire-hyprland: exit %d, warnings %d (QML %d)\n", code, AppTools::s_warnings,
                     AppTools::s_qmlWarnings);
    return code;
}
