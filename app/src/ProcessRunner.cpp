#include "ProcessRunner.h"

#include "HelperCommand.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcessEnvironment>
#include <QRegularExpression>
#include <QTimer>

#include <algorithm>

#include <csignal>
#include <sys/prctl.h>
#include <unistd.h>

#ifndef HW_HELPER_PYTHON
#define HW_HELPER_PYTHON "/usr/bin/python3"
#endif

namespace {
int s_answered = 0;
int s_running = 0;
int s_timeoutOverride = 0;
quint64 s_serial = 0;
QString s_program = QStringLiteral(HW_HELPER_PYTHON);

struct Rule {
    QRegularExpression pattern;
    int exitCode = 0;
    QByteArray out;
    QByteArray err;
};
bool s_fixtures = false;
QList<Rule> s_book;

QByteArray readFile(const QString &path)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly))
        return QByteArray();
    return file.read(ProcessRunner::MaxStdout);
}
}

ProcessRunner::ProcessRunner(QObject *parent)
    : QObject(parent)
{
}

ProcessRunner::~ProcessRunner()
{
    // Quitting (or the page going away) stops every helper of this source:
    // SIGTERM to all, a short wait, then SIGKILL for the rest.
    QList<Job *> jobs = m_jobs.values() + m_detached;
    m_jobs.clear();
    m_detached.clear();
    for (Job *job : std::as_const(jobs)) {
        job->process->disconnect(this);
        job->process->terminate();
    }
    for (Job *job : std::as_const(jobs)) {
        if (!job->process->waitForFinished(1000)) {
            job->process->kill();
            job->process->waitForFinished(1000);
        }
        --s_running;
        delete job->process;
        delete job;
    }
}

bool ProcessRunner::useFixtures(const QString &bookPath)
{
    s_book.clear();
    s_fixtures = !bookPath.isEmpty();
    if (!s_fixtures)
        return true;
    const QString base = QFileInfo(bookPath).absolutePath();
    QJsonParseError error;
    const QJsonDocument doc = QJsonDocument::fromJson(readFile(bookPath), &error);
    if (error.error != QJsonParseError::NoError || !doc.isArray())
        return false;
    const QJsonArray entries = doc.array();
    for (const QJsonValue &entry : entries) {
        const QJsonObject object = entry.toObject();
        Rule rule;
        rule.pattern = QRegularExpression(object.value(QLatin1String("match")).toString());
        if (!rule.pattern.isValid())
            return false;
        rule.exitCode = object.value(QLatin1String("exitCode")).toInt();
        rule.out = object.value(QLatin1String("stdout")).toString().toUtf8();
        const QString file = object.value(QLatin1String("stdoutFile")).toString();
        if (!file.isEmpty())
            rule.out = readFile(QDir(base).filePath(file));
        rule.err = object.value(QLatin1String("stderr")).toString().toUtf8();
        s_book.append(rule);
    }
    return true;
}

bool ProcessRunner::fixtures()
{
    return s_fixtures;
}

void ProcessRunner::setHelperProgram(const QString &absolutePath)
{
    s_program = absolutePath;
}

QString ProcessRunner::helperProgram()
{
    return s_program;
}

void ProcessRunner::setTimeoutOverride(int ms)
{
    s_timeoutOverride = ms > 0 ? ms : 0;
}

int ProcessRunner::timeoutFor(const HelperCommand &command)
{
    if (s_timeoutOverride > 0)
        return s_timeoutOverride;
    // The helper option is the word right after "-m hearthwire", never a value.
    const qsizetype module = command.arguments.indexOf(QLatin1String("hearthwire"));
    const bool vault = module >= 0 && command.arguments.value(module + 1) == QLatin1String("--vault");
    return vault ? VaultTimeoutMs : DefaultTimeoutMs;
}

int ProcessRunner::answered()
{
    return s_answered;
}

int ProcessRunner::running()
{
    return s_running;
}

void ProcessRunner::setConnectedSources(const QStringList &sources)
{
    const QStringList old = m_sources;
    for (const QString &source : old) {
        if (!sources.contains(source))
            disconnectSource(source);
    }
    for (const QString &source : sources) {
        if (!m_sources.contains(source))
            connectSource(source);
    }
}

void ProcessRunner::connectSource(const QString &source)
{
    if (source.isEmpty() || m_sources.contains(source))
        return;
    m_sources.append(source);
    Q_EMIT connectedSourcesChanged();
    if (m_engine != QLatin1String("executable"))
        return;
    start(source);
}

void ProcessRunner::disconnectSource(const QString &source)
{
    if (m_sources.removeAll(source) == 0)
        return;
    if (Job *job = m_jobs.take(source)) {
        m_detached.append(job);
        stop(job, ExitStopped);
    }
    Q_EMIT connectedSourcesChanged();
}

QVariantMap ProcessRunner::reply(int exitCode, int exitStatus, const QByteArray &out, const QByteArray &err)
{
    QVariantMap data;
    data.insert(QStringLiteral("exit code"), exitCode);
    data.insert(QStringLiteral("exit status"), exitStatus);
    data.insert(QStringLiteral("stdout"), QString::fromUtf8(out));
    data.insert(QStringLiteral("stderr"), QString::fromUtf8(err));
    return data;
}

// Like the engine: the reply comes on a later turn, never inside connectSource.
void ProcessRunner::replyLater(const QString &source, const QVariantMap &data)
{
    QTimer::singleShot(0, this, [this, source, data] { deliver(source, data); });
}

void ProcessRunner::deliver(const QString &source, const QVariantMap &data)
{
    if (!m_sources.contains(source))
        return;
    ++s_answered;
    Q_EMIT newData(source, data);
}

void ProcessRunner::start(const QString &source)
{
    const HelperCommand command = HelperCommand::parse(source);
    if (!command.ok) {
        replyLater(source, reply(ExitRefused, 0));
        return;
    }
    if (s_fixtures) {
        for (const Rule &rule : std::as_const(s_book)) {
            if (rule.pattern.match(source).hasMatch()) {
                replyLater(source, reply(rule.exitCode, 0, rule.out, rule.err));
                return;
            }
        }
        replyLater(source, reply(ExitRefused, 0));
        return;
    }
    const QFileInfo program(s_program);
    if (!program.isAbsolute() || !program.isFile() || !program.isExecutable()) {
        replyLater(source, reply(ExitRefused, 0));
        return;
    }
    if (s_running >= MaxRunning) {
        replyLater(source, reply(ExitStopped, 0));
        return;
    }

    QProcessEnvironment environment = QProcessEnvironment::systemEnvironment();
    const QStringList names = environment.keys();
    for (const QString &name : names) {
        if (!passedToHelper(name))
            environment.remove(name);
    }
    for (const auto &word : command.environment)
        environment.insert(word.first, word.second);
    environment.insert(QStringLiteral("HEARTHWIRE_FRONTEND"), QStringLiteral("app"));

    auto *job = new Job;
    job->serial = ++s_serial;
    job->process = new QProcess;
    job->process->setProgram(program.absoluteFilePath());
    job->process->setArguments(command.arguments);
    job->process->setProcessEnvironment(environment);
    job->process->setWorkingDirectory(QDir::homePath());
    job->process->setStandardInputFile(QProcess::nullDevice());
    QProcess::UnixProcessParameters parameters;
    parameters.flags = QProcess::UnixProcessFlag::CloseFileDescriptors | QProcess::UnixProcessFlag::ResetSignalHandlers;
    job->process->setUnixProcessParameters(parameters);
    // The helper ends with the app, even when the app crashes. If the app
    // died between fork and prctl, the child was already re-parented and
    // the signal would never come: it ends itself instead.
    const pid_t parent = ::getpid();
    job->process->setChildProcessModifier([parent] {
        ::prctl(PR_SET_PDEATHSIG, SIGTERM);
        if (::getppid() != parent)
            ::_exit(ExitRefused);
    });
    job->timer = new QTimer(job->process);
    job->timer->setSingleShot(true);
    job->timer->setInterval(timeoutFor(command));

    QProcess *process = job->process;
    connect(process, &QProcess::readyReadStandardOutput, this, [this, job] { drain(job); });
    connect(process, &QProcess::readyReadStandardError, this, [job] {
        job->err += job->process->readAllStandardError();
        if (job->err.size() > MaxStderr)
            job->err = job->err.right(MaxStderr);
    });
    connect(job->timer, &QTimer::timeout, this, [this, job] { stop(job, ExitTimedOut); });
    connect(process, &QProcess::finished, this, [this, source, job](int code, QProcess::ExitStatus status) {
        finished(source, job, code, status);
    });
    // Queued: QProcess reports some start failures (no descriptor left for
    // the pipes or /dev/null, fork failing) from inside start(). The reply
    // then still comes on a later turn, never inside connectSource, and the
    // job is never freed while start() still uses it.
    const quint64 serial = job->serial;
    connect(
        process, &QProcess::errorOccurred, this,
        [this, source, job, serial](QProcess::ProcessError error) {
            if (error == QProcess::FailedToStart && owns(job, serial))
                finished(source, job, ExitRefused, QProcess::NormalExit);
        },
        Qt::QueuedConnection);

    m_jobs.insert(source, job);
    ++s_running;
    process->setReadChannel(QProcess::StandardOutput);
    job->timer->start();
    process->start(QIODevice::ReadOnly);
}

// Whether `job` (with this serial) is still one of ours: a queued report
// may arrive after the job ended and its memory was reused.
bool ProcessRunner::owns(const Job *job, quint64 serial) const
{
    const auto same = [job, serial](const Job *other) { return other == job && other->serial == serial; };
    for (const Job *other : m_jobs) {
        if (same(other))
            return true;
    }
    return std::any_of(m_detached.cbegin(), m_detached.cend(), same);
}

// What the helper inherits from the app: an allow-list (review-4 LOW-1),
// so no variable that loads code into python3, the loader, GTK, GIO or Qt
// (PYTHON*, LD_*, GCONV_PATH, LOCPATH, GTK_MODULES, GIO_EXTRA_MODULES,
// QT_PLUGIN_PATH, QML_IMPORT_PATH, ...) and no HEARTHWIRE_* (the front end
// is set by the app alone, task 011) reaches it or its dialogs. Kept, for
// what the helper and the programs it starts need (src/hearthwire):
// - the account and its tools: PATH (tool lookup, login-shell capture),
//   HOME, USER, LOGNAME, SHELL, TERM (core/environment.py), and
//   CLAUDE_CONFIG_DIR, CODEX_HOME (core/discovery.py, providers);
// - its folders and the session: XDG_* (config, data, cache, runtime:
//   settings backup, locks, the encrypted folder), DBUS_SESSION_BUS_ADDRESS
//   (secret-tool);
// - language and time: LANG, LANGUAGE, LC_*, TZ;
// - the network: SSL_CERT_FILE, SSL_CERT_DIR and the proxy variables
//   (urllib reads them; both cases);
// - the passphrase window (hearthwire-askpass, a Qt program; kdialog for
//   Plasma): WAYLAND_DISPLAY, DISPLAY, XAUTHORITY, the Qt look and scaling
//   variables that name no folder (QT_QPA_PLATFORM, QT_QPA_PLATFORMTHEME,
//   QT_STYLE_OVERRIDE, QT_*SCALE*, QT_FONT_DPI,
//   QT_WAYLAND_DISABLE_WINDOWDECORATION), XCURSOR_THEME, XCURSOR_SIZE,
//   GTK_THEME, GDK_SCALE, GDK_DPI_SCALE, GDK_BACKEND, DESKTOP_SESSION,
//   KDE_FULL_SESSION, KDE_SESSION_VERSION.
// HEARTHWIRE_FRONTEND=app and the command's own HEARTHWIRE_* words are
// added afterwards.
bool ProcessRunner::passedToHelper(const QString &name)
{
    static const QStringList exact{
        QStringLiteral("PATH"), QStringLiteral("HOME"), QStringLiteral("USER"), QStringLiteral("LOGNAME"),
        QStringLiteral("SHELL"), QStringLiteral("TERM"), QStringLiteral("CLAUDE_CONFIG_DIR"), QStringLiteral("CODEX_HOME"),
        QStringLiteral("DBUS_SESSION_BUS_ADDRESS"), QStringLiteral("LANG"), QStringLiteral("LANGUAGE"), QStringLiteral("TZ"),
        QStringLiteral("SSL_CERT_FILE"), QStringLiteral("SSL_CERT_DIR"), QStringLiteral("HTTP_PROXY"),
        QStringLiteral("HTTPS_PROXY"), QStringLiteral("NO_PROXY"), QStringLiteral("ALL_PROXY"), QStringLiteral("http_proxy"),
        QStringLiteral("https_proxy"), QStringLiteral("no_proxy"), QStringLiteral("all_proxy"),
        QStringLiteral("WAYLAND_DISPLAY"), QStringLiteral("DISPLAY"), QStringLiteral("XAUTHORITY"),
        QStringLiteral("QT_QPA_PLATFORM"), QStringLiteral("QT_QPA_PLATFORMTHEME"), QStringLiteral("QT_STYLE_OVERRIDE"),
        QStringLiteral("QT_SCALE_FACTOR"), QStringLiteral("QT_SCREEN_SCALE_FACTORS"),
        QStringLiteral("QT_AUTO_SCREEN_SCALE_FACTOR"), QStringLiteral("QT_ENABLE_HIGHDPI_SCALING"),
        QStringLiteral("QT_SCALE_FACTOR_ROUNDING_POLICY"), QStringLiteral("QT_FONT_DPI"),
        QStringLiteral("QT_WAYLAND_DISABLE_WINDOWDECORATION"), QStringLiteral("XCURSOR_THEME"),
        QStringLiteral("XCURSOR_SIZE"), QStringLiteral("GTK_THEME"), QStringLiteral("GDK_SCALE"),
        QStringLiteral("GDK_DPI_SCALE"), QStringLiteral("GDK_BACKEND"), QStringLiteral("DESKTOP_SESSION"),
        QStringLiteral("KDE_FULL_SESSION"), QStringLiteral("KDE_SESSION_VERSION")};
    return exact.contains(name) || name.startsWith(QLatin1String("XDG_")) || name.startsWith(QLatin1String("LC_"));
}

// Reads what stdout has; past MaxStdout the helper is stopped.
void ProcessRunner::drain(Job *job)
{
    const QByteArray chunk = job->process->readAllStandardOutput();
    if (job->forcedCode != 0)
        return;
    if (job->out.size() + chunk.size() > MaxStdout) {
        stop(job, ExitStopped);
        return;
    }
    job->out += chunk;
}

void ProcessRunner::stop(Job *job, int forcedCode)
{
    if (job->forcedCode != 0)
        return;
    job->forcedCode = forcedCode;
    job->timer->stop();
    job->out.clear();
    job->err.clear();
    if (job->process->state() == QProcess::NotRunning)
        return;
    job->process->terminate();
    QTimer::singleShot(KillGraceMs, job->process, [process = job->process] {
        if (process->state() != QProcess::NotRunning)
            process->kill();
    });
}

void ProcessRunner::finished(const QString &source, Job *job, int exitCode, QProcess::ExitStatus status)
{
    const bool detached = m_detached.removeAll(job) > 0;
    if (!detached && m_jobs.value(source) == job)
        m_jobs.remove(source);
    else if (!detached)
        return;  // already handled (errorOccurred after finished)
    drain(job);
    job->err += job->process->readAllStandardError();
    if (job->err.size() > MaxStderr)
        job->err = job->err.right(MaxStderr);
    QVariantMap data;
    if (job->forcedCode != 0)
        data = reply(job->forcedCode, QProcess::CrashExit);
    else
        data = reply(exitCode, status == QProcess::CrashExit ? 1 : 0, job->out, job->err);
    release(job);
    if (!detached)
        deliver(source, data);
}

void ProcessRunner::release(Job *job)
{
    --s_running;
    job->timer->stop();
    job->process->disconnect(this);
    job->process->deleteLater();
    delete job;
}
