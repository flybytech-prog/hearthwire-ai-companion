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
//   --session-bus      use the session bus (single instance, notifications);
//                      without it a fixture build never connects to a bus
//
// Options (every build): --toggle, or --tab usage|chat|ollama (not both).
// One copy per session (SingleInstance.h): a later launch asks the running
// one to show itself (Show(tab, token)) or toggle (Toggle(token)) and ends
// with 0; 1 when the running copy did not answer; 2 for any usage error
// (an unknown option, a missing value, an extra argument, both options, a
// tab outside the three), before any bus use.
// Without a session bus the app runs alone, without single instance.
//
// The look follows the Omarchy theme (ThemeWatcher.h) through the app's
// Qt Quick Controls style, Hearthwire.Style (Material behind it).
//
// The Chat tab runs in Qt WebEngine (task 013) with Chromium's sandbox on:
// Chromium switches on the command line end with exit 2, and every
// QTWEBENGINE* variable is dropped before QtWebEngineQuick::initialize(),
// which runs before QGuiApplication (WebEngineEnv.h).
#include <QCommandLineParser>
#include <QDBusConnection>
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
#include "ImportTrust.h"
#include "KirigamiCompat.h"
#include "LocalizedContext.h"
#include "Notifier.h"
#include "PlasmoidHost.h"
#include "ProcessRunner.h"
#include "SingleInstance.h"
#include "ThemeWatcher.h"
#include "UrlGuard.h"
#include "WebEngineEnv.h"

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
    if (hwRefusedChromiumArgument(argc, argv)) {
        std::fprintf(stderr, "hearthwire-hyprland: Chromium switches are not accepted; Qt WebEngine always runs with its sandbox on\n");
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
    // Qt WebEngine: its variables dropped, then initialize(), before
    // QGuiApplication exists (no WebEngine process starts here; the first
    // profile, made by the Chat tab, starts them).
    hwStartWebEngine();
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
    parser.addOption({QStringLiteral("session-bus"), QStringLiteral("Use the session bus (tests on a private bus only).")});
#endif
    parser.addOption({QStringLiteral("toggle"), QStringLiteral("Show the window, or hide it when it is shown and active.")});
    parser.addOption({QStringLiteral("tab"), QStringLiteral("Show the window on this tab: usage, chat or ollama."), QStringLiteral("tab")});
    // parse(), not process(): process() ends a bad command line with 1, the
    // code for "another copy did not answer". Every usage error is 2.
    if (!parser.parse(app.arguments())) {
        std::fprintf(stderr, "hearthwire-hyprland: unknown option or missing value; see --help\n");
        return 2;
    }
    if (parser.isSet(QStringLiteral("help")) || parser.isSet(QStringLiteral("help-all")))
        parser.showHelp(0);
    if (parser.isSet(QStringLiteral("version")))
        parser.showVersion();
    if (!parser.positionalArguments().isEmpty()) {
        std::fprintf(stderr, "hearthwire-hyprland: unexpected argument; see --help\n");
        return 2;
    }

    // Checked before any bus use.
    const bool toggle = parser.isSet(QStringLiteral("toggle"));
    const QString tab = parser.value(QStringLiteral("tab"));
    if ((toggle && parser.isSet(QStringLiteral("tab")))
        || (parser.isSet(QStringLiteral("tab")) && (tab.isEmpty() || !SingleInstance::validTab(tab)))) {
        std::fprintf(stderr, "hearthwire-hyprland: use --toggle or --tab usage|chat|ollama, not both\n");
        return 2;
    }

    // Single instance, before any settings, theme, helper or QML.
#ifdef HW_FIXTURES
    const bool useBus = parser.isSet(QStringLiteral("session-bus"));
#else
    const bool useBus = true;
#endif
    const QDBusConnection bus = useBus ? QDBusConnection::sessionBus() : QDBusConnection(QStringLiteral("hearthwire-no-bus"));
    auto *instance = new SingleInstance(bus, &app);
    if (useBus) {
        SingleInstance::Claim claim = instance->claim();
        if (claim == SingleInstance::Claim::Taken) {
            // forward() filters it (the same rule as the receiving side).
            const QString token = qEnvironmentVariable("XDG_ACTIVATION_TOKEN");
            const SingleInstance::Forward forwarded = SingleInstance::forward(bus, toggle, tab, token);
            if (forwarded == SingleInstance::Forward::Done)
                return 0;
            if (forwarded == SingleInstance::Forward::NoOwner)
                claim = instance->claim();
            if (claim != SingleInstance::Claim::Claimed) {
                std::fprintf(stderr, "hearthwire-hyprland: another copy is running but did not answer\n");
                return 1;
            }
        }
        if (claim == SingleInstance::Claim::NoBus)
            std::fprintf(stderr, "hearthwire-hyprland: no session bus; running without single instance\n");
        else
            Notifier::setDefaultMode(Notifier::Mode::Bus);
    }

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

    auto *tools = new AppTools(host, instance, &app);
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
        // Only folders nobody but root or the user can change (ImportTrust.h).
        engine.setImportPathList(hwTrustedImportPaths(hwImportPaths(engine.importPathList())));
        guard = std::make_unique<UrlGuard>(engine.importPathList());
        engine.addUrlInterceptor(guard.get());
        engine.addImageProvider(QStringLiteral("icon"), new IconProvider);
        engine.rootContext()->setContextObject(new LocalizedContext(&engine));
        QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed, &app, [] { QCoreApplication::exit(3); },
                         Qt::QueuedConnection);
        engine.loadFromModule("Hearthwire.App", "AppWindow");
        // --tab on the first copy: that tab (as a later launch would ask).
        if (!tab.isEmpty())
            QMetaObject::invokeMethod(instance, [instance, tab] { instance->Show(tab, QString()); }, Qt::QueuedConnection);
        code = app.exec();
        // The engine (and every DataSource, which stops its helpers) goes first.
    }
    if (AppTools::fixtures())
        std::fprintf(stderr, "hearthwire-hyprland: exit %d, warnings %d (QML %d)\n", code, AppTools::s_warnings,
                     AppTools::s_qmlWarnings);
    return code;
}
