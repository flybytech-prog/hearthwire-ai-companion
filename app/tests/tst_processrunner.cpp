// ProcessRunner: runs only the helper (here a fake python3 written by the
// test), as an argv list with HEARTHWIRE_FRONTEND=app in its environment,
// with output caps, a time limit and a stop on disconnect and on quit.
#include <QDir>
#include <QFile>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>

#include <algorithm>
#include <cerrno>
#include <csignal>
#include <fcntl.h>
#include <unistd.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <vector>

#include "HelperCommand.h"
#include "ProcessRunner.h"

namespace {
// The fake helper: prints its argv and environment, or misbehaves on purpose
// for the helper option given after -m hearthwire.
const char FakePython[] = R"SH(#!/bin/sh
dir="$HW_TEST_DIR"
: > "$dir/started"
shift 3
case "$1" in
--sleep) echo $$ > "$dir/pid"; exec sleep 60 ;;
--big) head -c 9000000 /dev/zero; exit 0 ;;
--noisy) head -c 100000 /dev/zero | tr '\0' 'e' >&2; printf 'last line' >&2; exit 0 ;;
--fail) echo out; echo 'the error' >&2; exit 3 ;;
esac
printf 'ARG %s\n' "$@"
printf 'FRONTEND=%s\n' "${HEARTHWIRE_FRONTEND-unset}"
printf 'AGENTS=%s\n' "${HEARTHWIRE_AGENTS_PANEL-unset}"
printf 'RUN=%s\n' "${HEARTHWIRE_RUN-unset}"
printf 'APPLET=%s\n' "${HEARTHWIRE_APPLET-unset}"
printf 'OTHER=%s\n' "${HEARTHWIRE_OTHER-unset}"
printf 'PYTHONPATH=%s\n' "${PYTHONPATH-unset}"
printf 'PYTHONSTARTUP=%s\n' "${PYTHONSTARTUP-unset}"
printf 'LD_PRELOAD=%s\n' "${LD_PRELOAD-unset}"
printf 'LD_LIBRARY_PATH=%s\n' "${LD_LIBRARY_PATH-unset}"
printf 'LD_AUDIT=%s\n' "${LD_AUDIT-unset}"
printf 'GCONV_PATH=%s\n' "${GCONV_PATH-unset}"
printf 'LOCPATH=%s\n' "${LOCPATH-unset}"
printf 'KEPT=%s\n' "${HW_TEST_KEPT-unset}"
printf 'CWD=%s\n' "$(pwd)"
printf 'STDIN=%s\n' "$(readlink /proc/$$/fd/0)"
printf 'FD9=%s\n' "$(test -e /proc/$$/fd/9 && echo open || echo closed)"
)SH";

bool alive(qint64 pid)
{
    return pid > 0 && ::kill(pid_t(pid), 0) == 0;
}

// Uses up every descriptor under a low limit; gives them and the limit back
// when it goes out of scope (also when a check fails).
struct NoDescriptorsLeft {
    rlimit old {};
    std::vector<int> fds;
    int lastErrno = 0;
    NoDescriptorsLeft()
    {
        ::getrlimit(RLIMIT_NOFILE, &old);
        rlimit low = old;
        low.rlim_cur = std::min<rlim_t>(old.rlim_cur, 256);
        ::setrlimit(RLIMIT_NOFILE, &low);
        for (;;) {
            const int fd = ::open("/dev/null", O_RDONLY | O_CLOEXEC);
            if (fd < 0) {
                lastErrno = errno;
                break;
            }
            fds.push_back(fd);
        }
    }
    ~NoDescriptorsLeft()
    {
        for (int fd : fds)
            ::close(fd);
        ::setrlimit(RLIMIT_NOFILE, &old);
    }
    NoDescriptorsLeft(const NoDescriptorsLeft &) = delete;
    NoDescriptorsLeft &operator=(const NoDescriptorsLeft &) = delete;
};
}

class TestProcessRunner : public QObject
{
    Q_OBJECT

    QTemporaryDir m_dir;
    QString m_fake;

    QString path(const QString &name) const { return QDir(m_dir.path()).filePath(name); }

    qint64 waitForPid()
    {
        for (int i = 0; i < 100 && !QFile::exists(path("pid")); ++i)
            QTest::qWait(50);
        QFile file(path("pid"));
        if (!file.open(QIODevice::ReadOnly))
            return -1;
        return file.readAll().trimmed().toLongLong();
    }

    ProcessRunner *runner(QObject *parent)
    {
        auto *r = new ProcessRunner(parent);
        r->setProperty("engine", QStringLiteral("executable"));
        return r;
    }

    void reset()
    {
        QFile::remove(path("started"));
        QFile::remove(path("pid"));
    }

private Q_SLOTS:
    void initTestCase()
    {
        QVERIFY(m_dir.isValid());
        m_fake = path("python3");
        QFile file(m_fake);
        QVERIFY(file.open(QIODevice::WriteOnly));
        file.write(FakePython);
        file.close();
        QVERIFY(QFile::setPermissions(m_fake, QFileDevice::ReadOwner | QFileDevice::WriteOwner | QFileDevice::ExeOwner));
        ProcessRunner::setHelperProgram(m_fake);
        // An inheritable descriptor of the app's that the helper must not get.
        const int fd = ::open(QFile::encodeName(m_fake).constData(), O_RDONLY);
        QVERIFY(fd >= 0 && ::dup2(fd, 9) == 9);
        QVERIFY(!(::fcntl(9, F_GETFD) & FD_CLOEXEC));
        qputenv("HW_TEST_DIR", QFile::encodeName(m_dir.path()));
        // Inherited values the child must never see.
        qputenv("HEARTHWIRE_FRONTEND", "plasma");
        qputenv("HEARTHWIRE_AGENTS_PANEL", "1");
        qputenv("HEARTHWIRE_OTHER", "x");
        // Ways into python3 or the loader that the helper must never inherit.
        qputenv("PYTHONPATH", QFile::encodeName(m_dir.path()));
        qputenv("PYTHONSTARTUP", QFile::encodeName(path("startup.py")));
        qputenv("LD_PRELOAD", "/nonexistent/libhw-test-preload.so");
        qputenv("LD_LIBRARY_PATH", QFile::encodeName(m_dir.path()));
        qputenv("LD_AUDIT", "/nonexistent/libhw-test-audit.so");
        qputenv("GCONV_PATH", QFile::encodeName(m_dir.path()));
        qputenv("LOCPATH", QFile::encodeName(m_dir.path()));
        qputenv("HW_TEST_KEPT", "kept");
        qputenv("HOME", QFile::encodeName(m_dir.path()));
    }

    void init()
    {
        reset();
        ProcessRunner::useFixtures(QString());
        ProcessRunner::setTimeoutOverride(0);
        ProcessRunner::setHelperProgram(m_fake);
    }

    void runsTheHelperWithTheAppEnvironment()
    {
        QObject owner;
        ProcessRunner *r = runner(&owner);
        QSignalSpy spy(r, &ProcessRunner::newData);
        const QString source = QStringLiteral("env HEARTHWIRE_RUN=7 HEARTHWIRE_APPLET=2147483648 python3 -P -m hearthwire --port-owner 80 --address '[::1]'");
        r->connectSource(source);
        QCOMPARE(spy.count(), 0);  // never inside connectSource
        QTRY_COMPARE_WITH_TIMEOUT(spy.count(), 1, 10000);
        QCOMPARE(spy.at(0).at(0).toString(), source);
        const QVariantMap data = spy.at(0).at(1).toMap();
        QCOMPARE(data.value("exit code").toInt(), 0);
        QCOMPARE(data.value("exit status").toInt(), 0);
        QCOMPARE(data.value("stderr").toString(), QString());
        const QStringList lines = data.value("stdout").toString().split(QLatin1Char('\n'), Qt::SkipEmptyParts);
        QCOMPARE(lines, (QStringList{
            "ARG --port-owner", "ARG 80", "ARG --address", "ARG [::1]",
            "FRONTEND=app", "AGENTS=unset", "RUN=7", "APPLET=2147483648", "OTHER=unset",
            "PYTHONPATH=unset", "PYTHONSTARTUP=unset", "LD_PRELOAD=unset", "LD_LIBRARY_PATH=unset", "LD_AUDIT=unset",
            "GCONV_PATH=unset", "LOCPATH=unset",
            "KEPT=kept",
            "CWD=" + QDir(m_dir.path()).canonicalPath(), "STDIN=/dev/null", "FD9=closed"}));
        QCOMPARE(ProcessRunner::running(), 0);
    }

    void argvIsTheFixedPythonWithPAndModule()
    {
        // The fake drops -P -m hearthwire with `shift 3`; check them here.
        QObject owner;
        ProcessRunner *r = runner(&owner);
        QSignalSpy spy(r, &ProcessRunner::newData);
        ProcessRunner::setHelperProgram(QStringLiteral("/bin/echo"));
        r->connectSource(QStringLiteral("python3 -P -s -m hearthwire --install-info"));
        QTRY_COMPARE_WITH_TIMEOUT(spy.count(), 1, 10000);
        QCOMPARE(spy.at(0).at(1).toMap().value("stdout").toString(), QStringLiteral("-P -s -m hearthwire --install-info\n"));
    }

    void refusedCommandsStartNothing_data()
    {
        QTest::addColumn<QString>("source");
        QTest::newRow("shell") << "sh -c id";
        QTest::newRow("chained") << "python3 -P -m hearthwire --json; id";
        QTest::newRow("front end word") << "env HEARTHWIRE_FRONTEND=plasma python3 -P -m hearthwire --json";
        QTest::newRow("substitution") << "python3 -P -m hearthwire --json $(id)";
    }

    void refusedCommandsStartNothing()
    {
        QFETCH(QString, source);
        QObject owner;
        ProcessRunner *r = runner(&owner);
        QSignalSpy spy(r, &ProcessRunner::newData);
        r->connectSource(source);
        QCOMPARE(spy.count(), 0);
        QTRY_COMPARE_WITH_TIMEOUT(spy.count(), 1, 5000);
        const QVariantMap data = spy.at(0).at(1).toMap();
        QCOMPARE(data.value("exit code").toInt(), ProcessRunner::ExitRefused);
        QCOMPARE(data.value("stdout").toString(), QString());
        QCOMPARE(data.value("stderr").toString(), QString());
        QTest::qWait(200);
        QVERIFY(!QFile::exists(path("started")));
    }

    void missingOrRelativeProgramIsRefused()
    {
        for (const QString &program : {path("nothing-here"), QStringLiteral("python3"), m_dir.path()}) {
            ProcessRunner::setHelperProgram(program);
            QObject owner;
            ProcessRunner *r = runner(&owner);
            QSignalSpy spy(r, &ProcessRunner::newData);
            r->connectSource(QStringLiteral("python3 -P -m hearthwire --json"));
            QTRY_COMPARE_WITH_TIMEOUT(spy.count(), 1, 5000);
            QCOMPARE(spy.at(0).at(1).toMap().value("exit code").toInt(), ProcessRunner::ExitRefused);
        }
        QVERIFY(!QFile::exists(path("started")));
    }

    void otherEnginesRunNothing()
    {
        QObject owner;
        auto *r = new ProcessRunner(&owner);
        QSignalSpy spy(r, &ProcessRunner::newData);
        r->connectSource(QStringLiteral("python3 -P -m hearthwire --json"));
        QTest::qWait(300);
        QCOMPARE(spy.count(), 0);
        QVERIFY(!QFile::exists(path("started")));
    }

    void exitCodeAndStderrArePassedOn()
    {
        QObject owner;
        ProcessRunner *r = runner(&owner);
        QSignalSpy spy(r, &ProcessRunner::newData);
        r->connectSource(QStringLiteral("python3 -P -m hearthwire --fail"));
        QTRY_COMPARE_WITH_TIMEOUT(spy.count(), 1, 10000);
        const QVariantMap data = spy.at(0).at(1).toMap();
        QCOMPARE(data.value("exit code").toInt(), 3);
        QCOMPARE(data.value("stdout").toString(), QStringLiteral("out\n"));
        QCOMPARE(data.value("stderr").toString(), QStringLiteral("the error\n"));
    }

    void stdoutOverTheCapStopsTheHelper()
    {
        QObject owner;
        ProcessRunner *r = runner(&owner);
        QSignalSpy spy(r, &ProcessRunner::newData);
        r->connectSource(QStringLiteral("python3 -P -m hearthwire --big"));
        QTRY_COMPARE_WITH_TIMEOUT(spy.count(), 1, 15000);
        const QVariantMap data = spy.at(0).at(1).toMap();
        QCOMPARE(data.value("exit code").toInt(), ProcessRunner::ExitStopped);
        QCOMPARE(data.value("exit status").toInt(), 1);
        QCOMPARE(data.value("stdout").toString(), QString());
        QCOMPARE(data.value("stderr").toString(), QString());
    }

    void stderrKeepsOnlyTheLastPart()
    {
        QObject owner;
        ProcessRunner *r = runner(&owner);
        QSignalSpy spy(r, &ProcessRunner::newData);
        r->connectSource(QStringLiteral("python3 -P -m hearthwire --noisy"));
        QTRY_COMPARE_WITH_TIMEOUT(spy.count(), 1, 10000);
        const QString err = spy.at(0).at(1).toMap().value("stderr").toString();
        QCOMPARE(err.size(), int(ProcessRunner::MaxStderr));
        QVERIFY(err.endsWith(QStringLiteral("last line")));
    }

    void timeLimitStopsTheHelper()
    {
        ProcessRunner::setTimeoutOverride(500);
        QObject owner;
        ProcessRunner *r = runner(&owner);
        QSignalSpy spy(r, &ProcessRunner::newData);
        r->connectSource(QStringLiteral("python3 -P -m hearthwire --sleep"));
        const qint64 pid = waitForPid();
        QVERIFY(alive(pid));
        QTRY_COMPARE_WITH_TIMEOUT(spy.count(), 1, 10000);
        const QVariantMap data = spy.at(0).at(1).toMap();
        QCOMPARE(data.value("exit code").toInt(), ProcessRunner::ExitTimedOut);
        QCOMPARE(data.value("stdout").toString(), QString());
        QTRY_VERIFY_WITH_TIMEOUT(!alive(pid), 5000);
    }

    void timeLimits()
    {
        HelperCommand vault = HelperCommand::parse(QStringLiteral("python3 -P -m hearthwire --vault unlock"));
        HelperCommand vaultS = HelperCommand::parse(QStringLiteral("env HEARTHWIRE_RUN=3 python3 -P -s -m hearthwire --vault status"));
        HelperCommand usage = HelperCommand::parse(QStringLiteral("python3 -P -m hearthwire --json --providers=claude"));
        // "--vault" as a value, not the helper option: the normal limit.
        HelperCommand value = HelperCommand::parse(QStringLiteral("python3 -P -m hearthwire --port-owner 80 --address '--vault'"));
        HelperCommand later = HelperCommand::parse(QStringLiteral("python3 -P -m hearthwire --json --vault"));
        QVERIFY(vault.ok && vaultS.ok && usage.ok && value.ok && later.ok);
        QCOMPARE(ProcessRunner::timeoutFor(vault), ProcessRunner::VaultTimeoutMs);
        QCOMPARE(ProcessRunner::timeoutFor(vaultS), ProcessRunner::VaultTimeoutMs);
        QCOMPARE(ProcessRunner::timeoutFor(usage), ProcessRunner::DefaultTimeoutMs);
        QCOMPARE(ProcessRunner::timeoutFor(value), ProcessRunner::DefaultTimeoutMs);
        QCOMPARE(ProcessRunner::timeoutFor(later), ProcessRunner::DefaultTimeoutMs);
    }

    void inheritedVariablesTheHelperNeverGets_data()
    {
        QTest::addColumn<QString>("name");
        QTest::addColumn<bool>("stripped");
        for (const char *name : {"HEARTHWIRE_FRONTEND", "HEARTHWIRE_AGENTS_PANEL", "HEARTHWIRE_", "PYTHONPATH", "PYTHONHOME",
                                 "PYTHONSTARTUP", "PYTHONSAFEPATH", "PYTHONUSERBASE", "PYTHONINSPECT", "PYTHON",
                                 "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "GCONV_PATH", "LOCPATH"})
            QTest::newRow(name) << QString::fromLatin1(name) << true;
        for (const char *name : {"PATH", "HOME", "LANG", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "WAYLAND_DISPLAY",
                                 "MYPYTHONPATH", "hearthwire_x", "LD_BIND_NOW", "LC_ALL", "MYGCONV_PATH"})
            QTest::newRow(name) << QString::fromLatin1(name) << false;
    }

    void inheritedVariablesTheHelperNeverGets()
    {
        QFETCH(QString, name);
        QFETCH(bool, stripped);
        QCOMPARE(ProcessRunner::strippedFromHelper(name), stripped);
    }

    // QProcess reports a start that fails for want of descriptors from
    // inside start() (review-1 #1): the reply must still come on a later
    // turn, exactly once, and nothing may touch the freed job.
    void aStartFailureRepliesOnALaterTurn()
    {
        QObject owner;
        ProcessRunner *r = runner(&owner);
        QSignalSpy spy(r, &ProcessRunner::newData);
        {
            NoDescriptorsLeft exhausted;
            QVERIFY(exhausted.lastErrno == EMFILE || exhausted.lastErrno == ENFILE);
            r->connectSource(QStringLiteral("python3 -P -m hearthwire --json"));
            QCOMPARE(spy.count(), 0);  // never inside connectSource
            QTRY_COMPARE_WITH_TIMEOUT(spy.count(), 1, 5000);
            QCOMPARE(spy.at(0).at(1).toMap().value("exit code").toInt(), ProcessRunner::ExitRefused);
            QCOMPARE(ProcessRunner::running(), 0);
        }
        QTest::qWait(200);
        QCOMPARE(spy.count(), 1);
        QVERIFY(!QFile::exists(path("started")));
        // The runner still works once descriptors are back.
        r->disconnectSource(QStringLiteral("python3 -P -m hearthwire --json"));
        r->connectSource(QStringLiteral("python3 -P -m hearthwire --json"));
        QTRY_COMPARE_WITH_TIMEOUT(spy.count(), 2, 10000);
        QCOMPARE(spy.at(1).at(1).toMap().value("exit code").toInt(), 0);
    }

    void disconnectStopsTheHelperWithoutAReply()
    {
        QObject owner;
        ProcessRunner *r = runner(&owner);
        QSignalSpy spy(r, &ProcessRunner::newData);
        const QString source = QStringLiteral("python3 -P -m hearthwire --sleep");
        r->connectSource(source);
        const qint64 pid = waitForPid();
        QVERIFY(alive(pid));
        r->disconnectSource(source);
        QVERIFY(r->connectedSources().isEmpty());
        QTRY_VERIFY_WITH_TIMEOUT(!alive(pid), 5000);
        QTest::qWait(200);
        QCOMPARE(spy.count(), 0);
        QTRY_COMPARE_WITH_TIMEOUT(ProcessRunner::running(), 0, 5000);
    }

    void destroyingTheSourceStopsItsHelpers()
    {
        auto *owner = new QObject;
        ProcessRunner *r = runner(owner);
        r->connectSource(QStringLiteral("python3 -P -m hearthwire --sleep"));
        const qint64 pid = waitForPid();
        QVERIFY(alive(pid));
        delete owner;
        QTRY_VERIFY_WITH_TIMEOUT(!alive(pid), 5000);
        QCOMPARE(ProcessRunner::running(), 0);
    }

    void atMostMaxRunning()
    {
        QObject owner;
        ProcessRunner *r = runner(&owner);
        QSignalSpy spy(r, &ProcessRunner::newData);
        for (int i = 0; i < ProcessRunner::MaxRunning; ++i)
            r->connectSource(QStringLiteral("env HEARTHWIRE_RUN=%1 python3 -P -m hearthwire --sleep").arg(i));
        QCOMPARE(ProcessRunner::running(), ProcessRunner::MaxRunning);
        r->connectSource(QStringLiteral("env HEARTHWIRE_RUN=99 python3 -P -m hearthwire --json"));
        QTRY_COMPARE_WITH_TIMEOUT(spy.count(), 1, 5000);
        QCOMPARE(spy.at(0).at(1).toMap().value("exit code").toInt(), ProcessRunner::ExitStopped);
        r->setConnectedSources({});
        QTRY_COMPARE_WITH_TIMEOUT(ProcessRunner::running(), 0, 10000);
    }

    void fixturesNeverRunAnything()
    {
        QFile book(path("book.json"));
        QVERIFY(book.open(QIODevice::WriteOnly));
        book.write(R"([{"match": "--json --providers=", "exitCode": 0, "stdoutFile": "snap.json"},
                       {"match": "--detect", "exitCode": 2, "stdout": "x", "stderr": "y"}])");
        book.close();
        QFile snap(path("snap.json"));
        QVERIFY(snap.open(QIODevice::WriteOnly));
        snap.write("{\"providers\":[]}");
        snap.close();
        QVERIFY(ProcessRunner::useFixtures(path("book.json")));
        QVERIFY(ProcessRunner::fixtures());

        QObject owner;
        ProcessRunner *r = runner(&owner);
        QSignalSpy spy(r, &ProcessRunner::newData);
        r->connectSource(QStringLiteral("env HEARTHWIRE_RUN=1 python3 -P -m hearthwire --json --providers=claude"));
        r->connectSource(QStringLiteral("python3 -P -m hearthwire --detect"));
        r->connectSource(QStringLiteral("python3 -P -m hearthwire --prompts list"));
        // A non-helper command is refused even when the book would match it.
        r->connectSource(QStringLiteral("sh -c '--json --providers='"));
        QTRY_COMPARE_WITH_TIMEOUT(spy.count(), 4, 5000);
        QCOMPARE(spy.at(0).at(1).toMap().value("stdout").toString(), QStringLiteral("{\"providers\":[]}"));
        QCOMPARE(spy.at(1).at(1).toMap().value("exit code").toInt(), 2);
        QCOMPARE(spy.at(1).at(1).toMap().value("stderr").toString(), QStringLiteral("y"));
        QCOMPARE(spy.at(2).at(1).toMap().value("exit code").toInt(), ProcessRunner::ExitRefused);
        QCOMPARE(spy.at(3).at(1).toMap().value("exit code").toInt(), ProcessRunner::ExitRefused);
        QVERIFY(!QFile::exists(path("started")));
        QCOMPARE(ProcessRunner::running(), 0);
    }

    void replyOnlyWhileConnected()
    {
        QObject owner;
        ProcessRunner *r = runner(&owner);
        QSignalSpy spy(r, &ProcessRunner::newData);
        const QString source = QStringLiteral("python3 -P -m hearthwire --json");
        r->connectSource(source);
        r->disconnectSource(source);
        QTest::qWait(500);
        QCOMPARE(spy.count(), 0);
    }
};

QTEST_GUILESS_MAIN(TestProcessRunner)
#include "tst_processrunner.moc"
