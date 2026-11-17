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

#include "ImportPaths.h"

namespace {
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
        QVERIFY(QFile::exists(marker()));
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
    QCoreApplication app(argc, argv);
    TestPluginPaths test;
    return QTest::qExec(&test, argc, argv);
}

#include "tst_pluginpaths.moc"
