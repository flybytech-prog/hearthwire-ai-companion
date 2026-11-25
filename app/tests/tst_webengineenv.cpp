// Qt WebEngine's environment and command line (task 013, src/WebEngineEnv.h).
// - main() plants every QTWEBENGINE* variable Qt WebEngine reads (and two
//   later-looking ones, and one name twice in environ) before
//   hwStartWebEngine(), whose initialize step is a probe: it records what
//   is still set at that moment, then calls the real
//   QtWebEngineQuick::initialize(). Nothing planted may be left then; the
//   names around them stay.
// - hwRefusedChromiumArgument's table.
// - The real binary with each refused switch (and planted variables): exit
//   2 with the one fixed line, nothing on stdout, and no process left
//   behind (this test is a child subreaper, so an orphaned QtWebEngineProcess
//   would become its child).
#include <QDir>
#include <QGuiApplication>
#include <QProcess>
#include <QTest>
#include <QtWebEngineQuick/qtwebenginequickglobal.h>

#include <sys/prctl.h>
#include <sys/wait.h>
#include <unistd.h>

#include <csignal>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "WebEngineEnv.h"

namespace {
// Every variable Qt WebEngine is known to read, plus two it might read later.
const char *const kPlanted[][2] = {
    {"QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --single-process"},
    {"QTWEBENGINE_DISABLE_SANDBOX", "1"},
    {"QTWEBENGINE_REMOTE_DEBUGGING", "9222"},
    {"QTWEBENGINEPROCESS_PATH", "/nonexistent/hw-planted-renderer"},
    {"QTWEBENGINE_RESOURCES_PATH", "/nonexistent/hw-planted-resources"},
    {"QTWEBENGINE_LOCALES_PATH", "/nonexistent/hw-planted-locales"},
    {"QTWEBENGINE_DICTIONARIES_PATH", "/nonexistent/hw-planted-dictionaries"},
    {"QTWEBENGINE_DIALOG_SET", "QtQuickControls2"},
    {"QTWEBENGINE_FUTURE_SWITCH", "1"},
    {"QTWEBENGINEPROCESS_FUTURE", "1"},
    // A longer name is another variable: dropped.
    {"QTWEBENGINE_ENABLE_LINUX_ACCESSIBILITY2", "1"},
    {"QTWEBENGINE_ENABLE_LINUX_ACCESSIBILIT", "1"},
    // Not QTWEBENGINE*: Chromium and its sandbox helper read these.
    {"SSLKEYLOGFILE", "/nonexistent/hw-planted-keys.log"},
    {"CHROME_DEVEL_SANDBOX", "/nonexistent/hw-planted-sandbox"},
    {"CHROME_SANDBOX_DEBUGGING", "1"},
    {"CHROME_LOG_FILE", "/nonexistent/hw-planted-chrome.log"},
    {"GOOGLE_API_KEY", "hw-planted"},
    {"GOOGLE_DEFAULT_CLIENT_ID", "hw-planted"},
    {"GOOGLE_DEFAULT_CLIENT_SECRET", "hw-planted"},
};
// Names that only look alike: not Qt WebEngine's, they stay.
const char *const kKept[][2] = {
    {"HW_TEST_KEPT", "kept"},
    {"XQTWEBENGINE_CHROMIUM_FLAGS", "kept"},
    {"qtwebengine_chromium_flags", "kept"},
    {"QT_WEBENGINE_LOOKALIKE", "kept"},
    // User decision I3: exactly this one QTWEBENGINE name passes (screen readers).
    {"QTWEBENGINE_ENABLE_LINUX_ACCESSIBILITY", "1"},
    // Proxy settings are the user's real network setting.
    {"http_proxy", "http://127.0.0.1:9"},
    {"HTTPS_PROXY", "http://127.0.0.1:9"},
    {"SSLKEYLOGFILE_X", "kept"},
    {"XSSLKEYLOGFILE", "kept"},
};
// A second QTWEBENGINE_CHROMIUM_FLAGS entry, put into environ by hand.
char g_duplicate[] = "QTWEBENGINE_CHROMIUM_FLAGS=--remote-debugging-port=9223";
std::vector<char *> g_environ;

std::vector<std::string> g_leftAtInitialize;
bool g_initialized = false;
bool g_appAtInitialize = true;

void plant()
{
    for (const auto &pair : kPlanted)
        ::setenv(pair[0], pair[1], 1);
    for (const auto &pair : kKept)
        ::setenv(pair[0], pair[1], 1);
    for (char **entry = environ; entry && *entry; ++entry)
        g_environ.push_back(*entry);
    g_environ.push_back(g_duplicate);
    g_environ.push_back(nullptr);
    environ = g_environ.data();
}

// What is still there when initialize runs, then the real one.
void probeInitialize()
{
    for (char **entry = environ; entry && *entry; ++entry) {
        if (std::strncmp(*entry, "QTWEBENGINE", 11) == 0
            && std::strncmp(*entry, "QTWEBENGINE_ENABLE_LINUX_ACCESSIBILITY=", 39) != 0)
            g_leftAtInitialize.emplace_back(*entry, std::strcspn(*entry, "="));
        else if (std::strncmp(*entry, "SSLKEYLOGFILE=", 14) == 0 || std::strncmp(*entry, "CHROME_", 7) == 0
                 || std::strncmp(*entry, "GOOGLE_", 7) == 0)
            g_leftAtInitialize.emplace_back(*entry, std::strcspn(*entry, "="));
    }
    g_initialized = true;
    g_appAtInitialize = QCoreApplication::instance() != nullptr;
    QtWebEngineQuick::initialize();
}

const char kRefusedLine[] =
    "hearthwire-hyprland: Chromium switches are not accepted; Qt WebEngine always runs with its sandbox on\n";
const char kUnknownLine[] = "hearthwire-hyprland: unknown option or missing value; see --help\n";

bool refused(const QStringList &arguments)
{
    std::vector<QByteArray> bytes{QByteArrayLiteral("hearthwire-hyprland")};
    for (const QString &argument : arguments)
        bytes.push_back(argument.toUtf8());
    std::vector<char *> argv;
    for (QByteArray &word : bytes)
        argv.push_back(word.data());
    argv.push_back(nullptr);
    return hwRefusedChromiumArgument(int(bytes.size()), argv.data());
}

// Our children that are still around (an orphan of the app re-parents here).
QList<int> ourChildren()
{
    QList<int> found;
    const QString self = QString::number(::getpid());
    const QStringList entries = QDir(QStringLiteral("/proc")).entryList(QDir::Dirs | QDir::NoDotAndDotDot);
    for (const QString &entry : entries) {
        bool number = false;
        const int pid = entry.toInt(&number);
        if (!number)
            continue;
        QFile status(QStringLiteral("/proc/%1/status").arg(entry));
        if (!status.open(QIODevice::ReadOnly))
            continue;
        const QList<QByteArray> lines = status.readAll().split('\n');
        for (const QByteArray &line : lines) {
            if (line.startsWith("PPid:") && line.mid(5).trimmed() == self.toLatin1())
                found.append(pid);
        }
    }
    return found;
}
}

class TestWebEngineEnv : public QObject
{
    Q_OBJECT

private Q_SLOTS:
    void nothingPlantedIsLeftWhenInitializeRuns()
    {
        QVERIFY(g_initialized);
        QStringList left;
        for (const std::string &name : g_leftAtInitialize)
            left.append(QString::fromStdString(name));
        QVERIFY2(left.isEmpty(), qPrintable(left.join(QLatin1Char(' '))));
        for (const auto &pair : kPlanted)
            QVERIFY2(!qEnvironmentVariableIsSet(pair[0]), pair[0]);
        for (const auto &pair : kKept)
            QCOMPARE(qgetenv(pair[0]), QByteArray(pair[1]));
    }

    void initializeRanBeforeTheApplication()
    {
        // Qt WebEngine needs it before QGuiApplication (it warns otherwise).
        QVERIFY(g_initialized);
        QVERIFY(!g_appAtInitialize);
    }

    void dropCountsAndRemovesEveryName()
    {
        qputenv("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox");
        qputenv("QTWEBENGINEPROCESS_PATH", "/nonexistent/x");
        qputenv("QTWEBENGINE", "bare");
        qputenv("SSLKEYLOGFILE", "/nonexistent/x");
        qputenv("HW_TEST_KEPT", "kept");
        QCOMPARE(hwDropWebEngineEnvironment(), 4);
        QVERIFY(!qEnvironmentVariableIsSet("SSLKEYLOGFILE"));
        QVERIFY(!qEnvironmentVariableIsSet("QTWEBENGINE_CHROMIUM_FLAGS"));
        QVERIFY(!qEnvironmentVariableIsSet("QTWEBENGINEPROCESS_PATH"));
        QVERIFY(!qEnvironmentVariableIsSet("QTWEBENGINE"));
        QCOMPARE(qgetenv("HW_TEST_KEPT"), QByteArray("kept"));
        QCOMPARE(hwDropWebEngineEnvironment(), 0);
    }

    void accessibilityNameIsTheOnlyQtWebEngineNameKept()
    {
        QVERIFY(!hwWebEngineVariable("QTWEBENGINE_ENABLE_LINUX_ACCESSIBILITY"));
        QVERIFY(hwWebEngineVariable("QTWEBENGINE_ENABLE_LINUX_ACCESSIBILITY2"));
        QVERIFY(hwWebEngineVariable("QTWEBENGINE_ENABLE_LINUX_ACCESSIBILIT"));
        QVERIFY(hwWebEngineVariable("QTWEBENGINE_CHROMIUM_FLAGS"));
        QVERIFY(hwWebEngineVariable("SSLKEYLOGFILE"));
        QVERIFY(!hwWebEngineVariable("sslkeylogfile"));
        QVERIFY(!hwWebEngineVariable("http_proxy"));
        QVERIFY(!hwWebEngineVariable("HTTPS_PROXY"));
        qputenv("QTWEBENGINE_ENABLE_LINUX_ACCESSIBILITY", "1");
        qputenv("QTWEBENGINE_DISABLE_SANDBOX", "1");
        QCOMPARE(hwDropWebEngineEnvironment(), 1);
        QCOMPARE(qgetenv("QTWEBENGINE_ENABLE_LINUX_ACCESSIBILITY"), QByteArray("1"));
    }

    void dropFailsClosedWhenNamesRemain()
    {
        qputenv("SSLKEYLOGFILE", "/nonexistent/x");
        // An unset that does nothing: names remain after the last round.
        QCOMPARE(hwDropWebEngineEnvironment([](const char *) { return false; }), -1);
        QVERIFY(qEnvironmentVariableIsSet("SSLKEYLOGFILE"));
        QCOMPARE(hwDropWebEngineEnvironment(), 1);
    }

    void startWebEngineExitsWithAFixedLineWhenNamesRemain()
    {
        qputenv("SSLKEYLOGFILE", "/nonexistent/x");
        int fds[2];
        QVERIFY(::pipe(fds) == 0);
        const pid_t pid = ::fork();
        QVERIFY(pid >= 0);
        if (pid == 0) {
            ::dup2(fds[1], 2);
            ::close(fds[0]);
            hwStartWebEngine([] { ::_exit(77); }, [](const char *) { return false; });
            ::_exit(78);
        }
        ::close(fds[1]);
        char buffer[512] = {};
        const ssize_t got = ::read(fds[0], buffer, sizeof(buffer) - 1);
        ::close(fds[0]);
        int status = 0;
        ::waitpid(pid, &status, 0);
        qunsetenv("SSLKEYLOGFILE");
        QVERIFY(WIFEXITED(status));
        QCOMPARE(WEXITSTATUS(status), 2);
        QCOMPARE(QByteArray(buffer, int(got)), QByteArray(hwEnvironmentFailedLine));
    }

    void refusedArgument_data()
    {
        QTest::addColumn<QStringList>("arguments");
        QTest::addColumn<bool>("refused");
        const auto row = [](const char *name, QStringList arguments, bool refused) {
            QTest::newRow(name) << arguments << refused;
        };
        row("--no-sandbox", {QStringLiteral("--no-sandbox")}, true);
        row("-no-sandbox", {QStringLiteral("-no-sandbox")}, true);
        row("--No-Sandbox", {QStringLiteral("--No-Sandbox")}, true);
        row("--single-process", {QStringLiteral("--single-process")}, true);
        row("--remote-debugging-port=9222", {QStringLiteral("--remote-debugging-port=9222")}, true);
        row("--remote-debugging-port 9222", {QStringLiteral("--remote-debugging-port"), QStringLiteral("9222")}, true);
        row("--remote-debugging-pipe", {QStringLiteral("--remote-debugging-pipe")}, true);
        row("--webEngineArgs", {QStringLiteral("--webEngineArgs")}, true);
        row("--webEngineArgs --no-sandbox", {QStringLiteral("--webEngineArgs"), QStringLiteral("--no-sandbox")}, true);
        row("--disable-web-security", {QStringLiteral("--disable-web-security")}, true);
        row("--disable-seccomp-filter-sandbox", {QStringLiteral("--disable-seccomp-filter-sandbox")}, true);
        row("--in-process-gpu", {QStringLiteral("--in-process-gpu")}, true);
        row("--no-zygote", {QStringLiteral("--no-zygote")}, true);
        row("--renderer-cmd-prefix=x", {QStringLiteral("--renderer-cmd-prefix=/bin/x")}, true);
        row("--user-data-dir=/tmp/x", {QStringLiteral("--user-data-dir=/tmp/x")}, true);
        row("--proxy-server=x", {QStringLiteral("--proxy-server=127.0.0.1:1")}, true);
        row("after an app option", {QStringLiteral("--toggle"), QStringLiteral("--no-sandbox")}, true);
        row("as the value of --tab", {QStringLiteral("--tab"), QStringLiteral("--single-process")}, true);
        row("--ssl-key-log-file", {QStringLiteral("--ssl-key-log-file=/tmp/k")}, true);
        row("--log-net-log", {QStringLiteral("--log-net-log=/tmp/n")}, true);
        row("--net-log-capture-mode", {QStringLiteral("--net-log-capture-mode=Everything")}, true);
        row("--enable-features", {QStringLiteral("--enable-features=x")}, true);
        row("--disable-features", {QStringLiteral("--disable-features=x")}, true);
        row("--unsafely-treat-insecure-origin-as-secure", {QStringLiteral("--unsafely-treat-insecure-origin-as-secure=http://x")}, true);
        row("--allow-file-access-from-files", {QStringLiteral("--allow-file-access-from-files")}, true);
        row("--allow-insecure-localhost", {QStringLiteral("--allow-insecure-localhost")}, true);
        row("nothing", {}, false);
        row("--toggle", {QStringLiteral("--toggle")}, false);
        row("--tab chat", {QStringLiteral("--tab"), QStringLiteral("chat")}, false);
        row("--tab=ollama", {QStringLiteral("--tab=ollama")}, false);
        row("a plain word", {QStringLiteral("no-sandbox")}, false);
        row("a longer name", {QStringLiteral("--no-sandboxes")}, false);
        row("--", {QStringLiteral("--")}, false);
    }

    void refusedArgument()
    {
        QFETCH(QStringList, arguments);
        QFETCH(bool, refused);
        QCOMPARE(::refused(arguments), refused);
    }

    void appRefuses_data()
    {
        QTest::addColumn<QStringList>("arguments");
        QTest::addColumn<QByteArray>("line");
        const QByteArray refusedLine(kRefusedLine);
        const QByteArray unknownLine(kUnknownLine);
        QTest::newRow("--no-sandbox") << QStringList{QStringLiteral("--no-sandbox")} << refusedLine;
        QTest::newRow("--single-process") << QStringList{QStringLiteral("--single-process")} << refusedLine;
        QTest::newRow("--remote-debugging-port=9222")
            << QStringList{QStringLiteral("--remote-debugging-port=9222")} << refusedLine;
        QTest::newRow("--webEngineArgs --no-sandbox")
            << QStringList{QStringLiteral("--webEngineArgs"), QStringLiteral("--no-sandbox")} << refusedLine;
        QTest::newRow("--disable-web-security") << QStringList{QStringLiteral("--disable-web-security")} << refusedLine;
        QTest::newRow("--toggle --no-zygote")
            << QStringList{QStringLiteral("--toggle"), QStringLiteral("--no-zygote")} << refusedLine;
        QTest::newRow("--enable-features=x") << QStringList{QStringLiteral("--enable-features=WebUIDarkMode")} << refusedLine;
        QTest::newRow("--ssl-key-log-file=x") << QStringList{QStringLiteral("--ssl-key-log-file=/tmp/k")} << refusedLine;
        // Not on the list: the app's own parser ends it, still before any profile.
        QTest::newRow("--disable-gpu (parser)") << QStringList{QStringLiteral("--disable-gpu")} << unknownLine;
    }

    void appRefuses()
    {
        QFETCH(QStringList, arguments);
        QFETCH(QByteArray, line);
        QProcess app;
        QProcessEnvironment environment = QProcessEnvironment::systemEnvironment();
        for (const auto &pair : kPlanted)
            environment.insert(QString::fromLatin1(pair[0]), QString::fromLatin1(pair[1]));
        app.setProcessEnvironment(environment);
        app.setProgram(QStringLiteral(HW_APP_BINARY));
        app.setArguments(arguments);
        app.setStandardInputFile(QProcess::nullDevice());
        app.start();
        QVERIFY(app.waitForStarted(10000));
        QVERIFY(app.waitForFinished(30000));
        const QByteArray err = app.readAllStandardError();
        QCOMPARE(app.exitStatus(), QProcess::NormalExit);
        QCOMPARE(app.exitCode(), 2);
        QCOMPARE(app.readAllStandardOutput(), QByteArray());
        if (line == kRefusedLine)
            QCOMPARE(err, line);
        else
            QVERIFY2(err.endsWith(line), err.constData());
        // An orphaned child (a WebEngine process) would be ours now.
        QTest::qWait(200);
        const QList<int> left = ourChildren();
        for (int pid : left)
            ::kill(pid, SIGKILL);
        QVERIFY2(left.isEmpty(), "the app left a process behind");
    }
};

int main(int argc, char **argv)
{
    // Orphans of the app become this test's children (see ourChildren()).
    ::prctl(PR_SET_CHILD_SUBREAPER, 1);
    plant();
    hwStartWebEngine(&probeInitialize);
    QGuiApplication app(argc, argv);
    TestWebEngineEnv test;
    return QTest::qExec(&test, argc, argv);
}

#include "tst_webengineenv.moc"
