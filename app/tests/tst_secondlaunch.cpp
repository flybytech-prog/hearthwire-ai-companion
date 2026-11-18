// A later launch of the REAL hearthwire-hyprland (task 012 R3.1), on the
// test's private bus only (BusGuard.h). This test owns the app's bus name
// (a fake first copy) before every run, so the binary only ever runs as a
// second copy: it must forward Show/Toggle with the filtered token and end,
// without making a settings folder; a bad option ends with 2 before any
// bus use.
#include <QDBusConnection>
#include <QDBusConnectionInterface>
#include <QDBusContext>
#include <QDBusMessage>
#include <QDir>
#include <QFile>
#include <QProcess>
#include <QTemporaryDir>
#include <QTest>

#include "BusGuard.h"

namespace {
const QString Name = QStringLiteral("io.github.flybytechprog.hearthwire.hyprland");
const QString Path = QStringLiteral("/io/github/flybytechprog/hearthwire/hyprland");
} // namespace

class FakeFirstCopy : public QObject, protected QDBusContext
{
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "io.github.flybytechprog.hearthwire.hyprland.Window")

public:
    QStringList calls;
    bool fail = false;

public Q_SLOTS:
    void Toggle(const QString &token)
    {
        calls.append(QStringLiteral("Toggle(%1)").arg(token));
        if (fail)
            sendErrorReply(QDBusError::Failed, QStringLiteral("test failure"));
    }
    void Show(const QString &tab, const QString &token)
    {
        calls.append(QStringLiteral("Show(%1,%2)").arg(tab, token));
        if (fail)
            sendErrorReply(QDBusError::Failed, QStringLiteral("test failure"));
    }
};

class TestSecondLaunch : public QObject
{
    Q_OBJECT

private:
    FakeFirstCopy m_fake;
    QTemporaryDir m_home;

    struct Run {
        int code = -1;
        QString err;
    };

    // Runs the app with `args` (and the token, if any) and waits on the
    // event loop, so the fake can answer.
    Run launch(const QStringList &args, const QByteArray &token = QByteArray())
    {
        Run run;
        if (QDBusConnection::sessionBus().interface()->serviceOwner(Name).value() != QDBusConnection::sessionBus().baseService()) {
            qWarning("the fake first copy does not own the name; not starting the app");
            return run;
        }
        QProcess process;
        QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
        env.insert(QStringLiteral("HOME"), m_home.path());
        env.insert(QStringLiteral("XDG_CONFIG_HOME"), m_home.filePath(QStringLiteral("config")));
        env.insert(QStringLiteral("XDG_STATE_HOME"), m_home.filePath(QStringLiteral("state")));
        env.insert(QStringLiteral("XDG_DATA_HOME"), m_home.filePath(QStringLiteral("data")));
        env.insert(QStringLiteral("XDG_CACHE_HOME"), m_home.filePath(QStringLiteral("cache")));
        // Never a display of the host, whatever the calling shell has.
        env.remove(QStringLiteral("DISPLAY"));
        env.remove(QStringLiteral("WAYLAND_DISPLAY"));
        env.insert(QStringLiteral("QT_QPA_PLATFORM"), QStringLiteral("offscreen"));
        env.remove(QStringLiteral("XDG_ACTIVATION_TOKEN"));
        if (!token.isNull())
            env.insert(QStringLiteral("XDG_ACTIVATION_TOKEN"), QString::fromLatin1(token));
        process.setProcessEnvironment(env);
        QStringList all = args;
#ifdef HW_APP_FIXTURES
        all.prepend(QStringLiteral("--session-bus"));
#endif
        process.start(QStringLiteral(HW_APP_BINARY), all);
        if (!process.waitForStarted(5000))
            return run;
        for (int i = 0; i < 1500 && process.state() != QProcess::NotRunning; ++i)
            QTest::qWait(10);
        if (process.state() != QProcess::NotRunning) {
            process.kill();
            process.waitForFinished(2000);
            return run;
        }
        run.code = process.exitStatus() == QProcess::NormalExit ? process.exitCode() : -2;
        run.err = QString::fromUtf8(process.readAllStandardError());
        return run;
    }

    bool noSettingsFolder() const
    {
        return !QDir(m_home.filePath(QStringLiteral("config/hearthwire-hyprland"))).exists()
            && !QDir(m_home.filePath(QStringLiteral(".config/hearthwire-hyprland"))).exists();
    }

private Q_SLOTS:
    void initTestCase()
    {
        QVERIFY2(hwOnPrivateBus(), hwPrivateBusMessage());
        QVERIFY(m_home.isValid());
        QDBusConnection bus = QDBusConnection::sessionBus();
        QVERIFY(bus.isConnected());
        QVERIFY(bus.registerObject(Path, &m_fake, QDBusConnection::ExportAllSlots));
        QCOMPARE(bus.interface()
                     ->registerService(Name, QDBusConnectionInterface::DontQueueService, QDBusConnectionInterface::DontAllowReplacement)
                     .value(),
                 QDBusConnectionInterface::ServiceRegistered);
    }

    void init()
    {
        m_fake.calls.clear();
        m_fake.fail = false;
    }

    void forwards_data()
    {
        QTest::addColumn<QStringList>("args");
        QTest::addColumn<QByteArray>("token");
        QTest::addColumn<QString>("expected");
        QTest::newRow("--tab usage, token") << QStringList{QStringLiteral("--tab"), QStringLiteral("usage")} << QByteArray("abc")
                                            << QStringLiteral("Show(usage,abc)");
        QTest::newRow("--tab=chat") << QStringList{QStringLiteral("--tab=chat")} << QByteArray() << QStringLiteral("Show(chat,)");
        QTest::newRow("--tab ollama") << QStringList{QStringLiteral("--tab"), QStringLiteral("ollama")} << QByteArray("x.y")
                                      << QStringLiteral("Show(ollama,x.y)");
        QTest::newRow("--toggle") << QStringList{QStringLiteral("--toggle")} << QByteArray() << QStringLiteral("Toggle()");
        QTest::newRow("--toggle, token") << QStringList{QStringLiteral("--toggle")} << QByteArray("t-1") << QStringLiteral("Toggle(t-1)");
        QTest::newRow("no option") << QStringList{} << QByteArray("abc") << QStringLiteral("Show(,abc)");
        QTest::newRow("a bad token is not sent") << QStringList{} << QByteArray("a b;c") << QStringLiteral("Show(,)");
        QTest::newRow("a long token is not sent") << QStringList{QStringLiteral("--toggle")} << QByteArray(256, 'a')
                                                  << QStringLiteral("Toggle()");
    }

    void forwards()
    {
        QFETCH(QStringList, args);
        QFETCH(QByteArray, token);
        QFETCH(QString, expected);
        const Run run = launch(args, token);
        QCOMPARE(run.code, 0);
        QCOMPARE(m_fake.calls, QStringList{expected});
        QVERIFY(noSettingsFolder());
        // The token is never printed.
        if (!token.isEmpty())
            QVERIFY(!run.err.contains(QString::fromLatin1(token)));
    }

    // The second copy never opens the settings: a damaged settings.json
    // (which opening would report and move aside) stays as it is.
    void theSettingsAreNotOpened()
    {
        const QString folder = m_home.filePath(QStringLiteral("config/hearthwire-hyprland"));
        QVERIFY(QDir().mkpath(folder));
        QVERIFY(QFile::setPermissions(folder, QFileDevice::ReadOwner | QFileDevice::WriteOwner | QFileDevice::ExeOwner));
        QFile file(folder + QStringLiteral("/settings.json"));
        QVERIFY(file.open(QIODevice::WriteOnly));
        file.write("{ damaged");
        file.close();
        QVERIFY(file.setPermissions(QFileDevice::ReadOwner | QFileDevice::WriteOwner));
        const Run run = launch({QStringLiteral("--tab"), QStringLiteral("chat")});
        QCOMPARE(run.code, 0);
        QCOMPARE(m_fake.calls, QStringList{QStringLiteral("Show(chat,)")});
        QVERIFY2(!run.err.contains(QStringLiteral("settings.json")), qPrintable(run.err));
        QCOMPARE(QDir(folder).entryList(QDir::Files | QDir::Hidden), QStringList{QStringLiteral("settings.json")});
        QVERIFY(file.open(QIODevice::ReadOnly));
        QCOMPARE(file.readAll(), QByteArray("{ damaged"));
        file.close();
        QVERIFY(QDir(folder).removeRecursively());
    }

    void aFirstCopyThatFailsEndsWithOne()
    {
        m_fake.fail = true;
        const Run run = launch({QStringLiteral("--tab"), QStringLiteral("usage")}, "abc");
        QCOMPARE(run.code, 1);
        QVERIFY2(run.err.contains(QStringLiteral("hearthwire-hyprland: another copy is running but did not answer")),
                 qPrintable(run.err));
        QVERIFY(!run.err.contains(QStringLiteral("abc")));
        QCOMPARE(m_fake.calls.size(), 1);
        QVERIFY(noSettingsFolder());
    }

    void aBadOptionEndsWithTwo_data()
    {
        QTest::addColumn<QStringList>("args");
        QTest::addColumn<QString>("line");
        const QString tabLine = QStringLiteral("hearthwire-hyprland: use --toggle or --tab usage|chat|ollama, not both");
        const QString parseLine = QStringLiteral("hearthwire-hyprland: unknown option or missing value; see --help");
        QTest::newRow("--tab nope") << QStringList{QStringLiteral("--tab"), QStringLiteral("nope")} << tabLine;
        QTest::newRow("--tab empty") << QStringList{QStringLiteral("--tab=")} << tabLine;
        QTest::newRow("--tab Usage") << QStringList{QStringLiteral("--tab"), QStringLiteral("Usage")} << tabLine;
        QTest::newRow("both") << QStringList{QStringLiteral("--toggle"), QStringLiteral("--tab"), QStringLiteral("usage")} << tabLine;
        // review-6 L2: Qt's own parse errors are 2 too, never 1.
        QTest::newRow("an unknown option") << QStringList{QStringLiteral("--tabb"), QStringLiteral("usage")} << parseLine;
        QTest::newRow("--tab without a value") << QStringList{QStringLiteral("--tab")} << parseLine;
        QTest::newRow("a value on --toggle") << QStringList{QStringLiteral("--toggle=yes")} << parseLine;
        QTest::newRow("an extra argument") << QStringList{QStringLiteral("usage")}
                                           << QStringLiteral("hearthwire-hyprland: unexpected argument; see --help");
    }

    void aBadOptionEndsWithTwo()
    {
        QFETCH(QStringList, args);
        QFETCH(QString, line);
        const Run run = launch(args, "abc");
        QCOMPARE(run.code, 2);
        QVERIFY2(run.err.contains(line), qPrintable(run.err));
        // One fixed line: the bad argument is not echoed.
        QVERIFY2(!run.err.contains(QStringLiteral("tabb")), qPrintable(run.err));
        QVERIFY(m_fake.calls.isEmpty());
        QVERIFY(noSettingsFolder());
    }

    void helpEndsWithZero()
    {
        const Run run = launch({QStringLiteral("--help")});
        QCOMPARE(run.code, 0);
        QVERIFY(m_fake.calls.isEmpty());
        QVERIFY(noSettingsFolder());
    }
};

QTEST_GUILESS_MAIN(TestSecondLaunch)
#include "tst_secondlaunch.moc"
