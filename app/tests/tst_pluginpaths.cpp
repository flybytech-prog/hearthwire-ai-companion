// QT_PLUGIN_PATH and QT_QPA_PLATFORM_PLUGIN_PATH from the environment can't
// make the app load a plugin from another folder (round 2, user rule "as
// secure as we can"). Both are read when QGuiApplication first needs a
// plugin, so each case runs in a child process of this test: once as Qt
// would by default (the planted plugins are found: the proof that the
// variables take effect), once after hwDropEnvironmentPluginPaths() as
// main() does it.
#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QGuiApplication>
#include <QImageReader>
#include <QProcess>
#include <QTemporaryDir>
#include <QTest>

#include <cstdio>
#include <cstring>
#include <vector>

#include "ImportPaths.h"

namespace {
// A GTK platform theme with a planted GTK module (review-4 LOW-1).
int gtkChild(bool drop, int argc, char **argv)
{
    if (drop) {
        hwDropEnvironmentPluginPaths();
        hwDropEnvironmentModulePaths();
    }
    QGuiApplication app(argc, argv);
    return 0;
}

int child(bool drop, int argc, char **argv)
{
    if (drop)
        hwDropEnvironmentPluginPaths();
    QGuiApplication app(argc, argv);
    const bool planted = QImageReader::supportedImageFormats().contains("hwplanted");
    std::printf("IMAGE %s\n", planted ? "planted" : "absent");
    std::printf("PLUGIN_PATH %s\n", qEnvironmentVariableIsSet("QT_PLUGIN_PATH") ? "set" : "unset");
    std::printf("PLATFORM_PATH %s\n", qEnvironmentVariableIsSet("QT_QPA_PLATFORM_PLUGIN_PATH") ? "set" : "unset");
    std::printf("PLATFORM %s\n", qPrintable(QGuiApplication::platformName()));
    return 0;
}
}

class TestPluginPaths : public QObject
{
    Q_OBJECT

    QTemporaryDir m_dir;

    QStringList run(bool drop)
    {
        QFile::remove(marker());
        QProcess process;
        QProcessEnvironment env;
        env.insert("PATH", "/usr/bin:/bin");
        env.insert("HOME", m_dir.path());
        env.insert("TMPDIR", m_dir.path());
        env.insert("XDG_RUNTIME_DIR", m_dir.path());
        // The planted platform first; Qt's offscreen when that is not found.
        env.insert("QT_QPA_PLATFORM", "hwplanted;offscreen");
        env.insert("QT_PLUGIN_PATH", QStringLiteral(HW_PLANTED_PLUGINS));
        env.insert("QT_QPA_PLATFORM_PLUGIN_PATH", QStringLiteral(HW_PLANTED_PLATFORMS));
        env.insert("HW_PLANTED_MARKER", marker());
        process.setProcessEnvironment(env);
        process.setProcessChannelMode(QProcess::ForwardedErrorChannel);
        process.start(QCoreApplication::applicationFilePath(), {"--child", drop ? "drop" : "keep"});
        if (!process.waitForFinished(30000) || process.exitStatus() != QProcess::NormalExit || process.exitCode() != 0)
            return {QStringLiteral("child failed")};
        return QString::fromUtf8(process.readAllStandardOutput()).split(QLatin1Char('\n'), Qt::SkipEmptyParts);
    }

    QString marker() const { return QDir(m_dir.path()).filePath("platform-plugin-loaded"); }
    QString gtkMarker() const { return QDir(m_dir.path()).filePath("gtk-module-loaded"); }

    // Whether GTK loaded the planted module.
    bool runGtk(bool drop)
    {
        QFile::remove(gtkMarker());
        QProcess process;
        QProcessEnvironment env;
        env.insert("PATH", "/usr/bin:/bin");
        env.insert("HOME", m_dir.path());
        env.insert("TMPDIR", m_dir.path());
        env.insert("XDG_RUNTIME_DIR", m_dir.path());
        env.insert("QT_QPA_PLATFORM", "offscreen");
        env.insert("QT_QPA_PLATFORMTHEME", "gtk3");
        env.insert("GTK_PATH", QStringLiteral(HW_PLANTED_GTK));
        env.insert("GTK_MODULES", "hwplantedgtk");
        env.insert("GTK3_MODULES", QStringLiteral(HW_PLANTED_GTK "/modules/libhwplantedgtk.so"));
        env.insert("HW_PLANTED_GTK_MARKER", gtkMarker());
        process.setProcessEnvironment(env);
        process.setProcessChannelMode(QProcess::ForwardedErrorChannel);
        process.start(QCoreApplication::applicationFilePath(), {"--gtk-child", drop ? "drop" : "keep"});
        // Without a display gtk_init() ends the child (exit 1) after it
        // loaded the modules: only the marker counts here.
        process.waitForFinished(30000);
        return QFile::exists(gtkMarker());
    }

private Q_SLOTS:
    void initTestCase()
    {
        QVERIFY(m_dir.isValid());
        QVERIFY(QFile::exists(QStringLiteral(HW_PLANTED_PLUGINS "/imageformats")));
    }

    // Qt's default: both planted plugins are loaded.
    void theVariablesWorkByDefault()
    {
        const QStringList lines = run(false);
        QCOMPARE(lines.value(0), QStringLiteral("IMAGE planted"));
    }

    void thePlatformVariableWorksByDefault()
    {
#ifdef HW_NO_PLANTED_PLATFORM
        QSKIP("built without Qt6 GuiPrivate: no planted platform plugin");
#else
        run(false);
        QVERIFY(QFile::exists(marker()));
#endif
    }

    // GTK loads the planted module through Qt's gtk3 platform theme by
    // default; after hwDropEnvironmentModulePaths(), as main() does, not.
    void aGtkModuleIsNotLoaded()
    {
        if (!QFile::exists(QStringLiteral("/usr/lib/qt6/plugins/platformthemes/libqgtk3.so"))
            && !QFile::exists(QStringLiteral("/usr/lib64/qt6/plugins/platformthemes/libqgtk3.so")))
            QSKIP("no Qt gtk3 platform theme here");
        if (!runGtk(false))
            QSKIP("GTK does not load modules here (no proof that the variables take effect)");
        QVERIFY(!runGtk(true));
    }

    // Every variable of the list, the GTK ones above and the ones without a
    // planted proof (GIO, pixbuf, QML's XMLHttpRequest file access).
    void everyModuleVariableIsDropped()
    {
        const char *names[] = {"GTK_PATH", "GTK_MODULES", "GTK3_MODULES", "GTK_EXE_PREFIX", "GTK_IM_MODULE_FILE",
                               "GIO_EXTRA_MODULES", "GIO_MODULE_DIR", "GDK_PIXBUF_MODULE_FILE", "GDK_PIXBUF_MODULEDIR",
                               "QML_XHR_ALLOW_FILE_READ", "QML_XHR_ALLOW_FILE_WRITE"};
        for (const char *name : names)
            qputenv(name, "1");
        qputenv("GTK_THEME", "Adwaita");
        hwDropEnvironmentModulePaths();
        for (const char *name : names)
            QVERIFY2(!qEnvironmentVariableIsSet(name), name);
        // A theme name is no folder of code: kept.
        QVERIFY(qEnvironmentVariableIsSet("GTK_THEME"));
        qunsetenv("GTK_THEME");
    }

    // -platformpluginpath and --platformpluginpath, alone or with =value
    // (review-4 LOW-2).
    void aPluginPathArgumentIsRefused_data()
    {
        QTest::addColumn<QStringList>("args");
        QTest::addColumn<bool>("refused");
        QTest::newRow("-x dir") << QStringList{"-platformpluginpath", "/tmp/x"} << true;
        QTest::newRow("--x dir") << QStringList{"--platformpluginpath", "/tmp/x"} << true;
        QTest::newRow("-x=dir") << QStringList{"-platformpluginpath=/tmp/x"} << true;
        QTest::newRow("--x=dir") << QStringList{"--platformpluginpath=/tmp/x"} << true;
        QTest::newRow("after other words") << QStringList{"--checks", "-platform", "offscreen", "-platformpluginpath", "x"} << true;
        QTest::newRow("-x alone at the end") << QStringList{"-platformpluginpath"} << true;
        QTest::newRow("none") << QStringList{"-platform", "offscreen"} << false;
        QTest::newRow("a value, not an option") << QStringList{"--shots", "platformpluginpath"} << false;
        QTest::newRow("a longer name") << QStringList{"-platformpluginpaths"} << false;
        QTest::newRow("no arguments") << QStringList{} << false;
    }

    void aPluginPathArgumentIsRefused()
    {
        QFETCH(QStringList, args);
        QFETCH(bool, refused);
        std::vector<QByteArray> words{QByteArray("hearthwire-hyprland")};
        for (const QString &arg : args)
            words.push_back(arg.toUtf8());
        std::vector<char *> argv;
        for (QByteArray &word : words)
            argv.push_back(word.data());
        argv.push_back(nullptr);
        QCOMPARE(hwRefusedArgument(int(words.size()), argv.data()), refused);
    }

    void theAppDropsThem()
    {
        const QStringList lines = run(true);
        QCOMPARE(lines, (QStringList{"IMAGE absent", "PLUGIN_PATH unset", "PLATFORM_PATH unset", "PLATFORM offscreen"}));
        QVERIFY(!QFile::exists(marker()));
    }
};

int main(int argc, char **argv)
{
    if (argc >= 3 && std::strcmp(argv[1], "--child") == 0)
        return child(std::strcmp(argv[2], "drop") == 0, argc, argv);
    if (argc >= 3 && std::strcmp(argv[1], "--gtk-child") == 0)
        return gtkChild(std::strcmp(argv[2], "drop") == 0, argc, argv);
    QCoreApplication app(argc, argv);
    TestPluginPaths test;
    return QTest::qExec(&test, argc, argv);
}

#include "tst_pluginpaths.moc"
