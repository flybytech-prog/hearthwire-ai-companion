// Hearthwire.Compat.Plasma5Support.DataSource: the stand-in for Plasma's
// "executable" engine. A connected source is a command; its reply comes
// later through newData with the engine's keys ("exit code", "exit status",
// "stdout", "stderr"), and only while the source is still connected.
//
// Unlike Plasma it never starts a shell and never runs anything but the
// helper: the source must parse as a HelperCommand, which then runs as
// <helperProgram()> -P [-s] -m hearthwire ... (an argv list, a fixed absolute
// python3, no PATH lookup). The child gets only the allow-listed variables
// of the app's environment (passedToHelper(): no HEARTHWIRE_*, PYTHON*,
// LD_*, GTK/GIO module or Qt plugin folders), plus the command's env words
// and HEARTHWIRE_FRONTEND=app (task 011), its stdin is /dev/null, it gets no
// other open file of the app's, and it dies with the app. A source that
// does not parse gets exit code 127 and nothing runs.
//
// Limits: at most MaxRunning helpers at once (more get exit code 1), stdout
// up to MaxStdout (more: the helper is stopped, exit code 1), the last
// MaxStderr bytes of stderr, and a time limit (timeoutFor(); then the helper
// is stopped, exit code 124). A stopped helper gets SIGTERM, then SIGKILL
// after KillGraceMs; its reply has empty stdout and stderr. Disconnecting a
// running source stops its helper without a reply (as Plasma's engine drops
// an unused source's process); so does destroying the DataSource or quitting.
//
// Fixture mode (useFixtures(), C++ only: test runs and HW_FIXTURES builds;
// no environment variable or option of a release build turns it on):
// nothing ever runs; each accepted command gets the first matching reply of
// the fixture book.
#pragma once

#include <QByteArray>
#include <QHash>
#include <QList>
#include <QObject>
#include <QProcess>
#include <QStringList>
#include <QVariantMap>
#include <QtQml/qqmlregistration.h>

class QTimer;
struct HelperCommand;

class ProcessRunner : public QObject
{
    Q_OBJECT
    QML_NAMED_ELEMENT(DataSource)
    Q_PROPERTY(QString engine MEMBER m_engine NOTIFY engineChanged)
    Q_PROPERTY(QStringList connectedSources READ connectedSources WRITE setConnectedSources NOTIFY connectedSourcesChanged)
    Q_PROPERTY(int interval MEMBER m_interval NOTIFY intervalChanged)

public:
    static constexpr qint64 MaxStdout = 8 * 1024 * 1024;
    static constexpr qint64 MaxStderr = 64 * 1024;
    static constexpr int MaxRunning = 16;
    static constexpr int DefaultTimeoutMs = 180 * 1000;
    // A vault step may wait for the passphrase prompt.
    static constexpr int VaultTimeoutMs = 900 * 1000;
    static constexpr int KillGraceMs = 3000;
    static constexpr int ExitRefused = 127;
    static constexpr int ExitTimedOut = 124;
    static constexpr int ExitStopped = 1;

    explicit ProcessRunner(QObject *parent = nullptr);
    ~ProcessRunner() override;

    QStringList connectedSources() const { return m_sources; }
    void setConnectedSources(const QStringList &sources);

    Q_INVOKABLE void connectSource(const QString &source);
    Q_INVOKABLE void disconnectSource(const QString &source);

    // C++ only. A fixture book (JSON list of {match, exitCode, stdout |
    // stdoutFile, stderr}; stdoutFile next to the book); "" = real runs.
    static bool useFixtures(const QString &bookPath);
    static bool fixtures();
    // The python3 the helper runs with (absolute; tests point it at a fake).
    static void setHelperProgram(const QString &absolutePath);
    static QString helperProgram();
    // Tests: one time limit for every command (0 = the normal ones).
    static void setTimeoutOverride(int ms);
    static int timeoutFor(const HelperCommand &command);
    // Whether an inherited variable reaches the helper (an allow-list; see
    // ProcessRunner.cpp). Never HEARTHWIRE_*, PYTHON*, LD_*, GTK/GIO/Qt
    // module or plugin folders.
    static bool passedToHelper(const QString &name);

    // Replies sent so far in this process, and helpers running now.
    static int answered();
    static int running();

Q_SIGNALS:
    void newData(const QString &source, const QVariantMap &data);
    void engineChanged();
    void connectedSourcesChanged();
    void intervalChanged();

private:
    struct Job {
        QProcess *process = nullptr;
        QTimer *timer = nullptr;
        QByteArray out;
        QByteArray err;
        int forcedCode = 0;
        quint64 serial = 0;
    };

    bool owns(const Job *job, quint64 serial) const;

    void start(const QString &source);
    void replyLater(const QString &source, const QVariantMap &data);
    void deliver(const QString &source, const QVariantMap &data);
    void finished(const QString &source, Job *job, int exitCode, QProcess::ExitStatus status);
    void drain(Job *job);
    void stop(Job *job, int forcedCode);
    void release(Job *job);
    static QVariantMap reply(int exitCode, int exitStatus, const QByteArray &out = {}, const QByteArray &err = {});

    QString m_engine;
    QStringList m_sources;
    int m_interval = 0;
    QHash<QString, Job *> m_jobs;
    // Stopped after a disconnect: no reply, deleted when they end.
    QList<Job *> m_detached;
};
