#include "AppTools.h"

#include "PlasmoidHost.h"
#include "ProcessRunner.h"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QQmlEngine>
#include <QQuickWindow>

#include <cstdio>
#include <sys/stat.h>

namespace {
AppTools *s_tools = nullptr;
}

int AppTools::s_warnings = 0;
int AppTools::s_qmlWarnings = 0;

AppTools::AppTools(PlasmoidHost *host, QObject *parent)
    : QObject(parent)
    , m_host(host)
{
}

AppTools *AppTools::create(QQmlEngine *, QJSEngine *)
{
    QQmlEngine::setObjectOwnership(s_tools, QQmlEngine::CppOwnership);
    return s_tools;
}

void AppTools::setInstance(AppTools *tools)
{
    s_tools = tools;
}

bool AppTools::fixtures()
{
#ifdef HW_FIXTURES
    return true;
#else
    return false;
#endif
}

QString AppTools::shots() const
{
    return fixtures() ? shotsDir : QString();
}

bool AppTools::runChecks() const
{
    return fixtures() && checks;
}

bool AppTools::grab(QObject *window, const QString &name) const
{
    auto *quick = qobject_cast<QQuickWindow *>(window);
    if (!fixtures() || !quick || shotsDir.isEmpty() || name.contains(QLatin1Char('/')))
        return false;
    return quick->grabWindow().save(QDir(shotsDir).filePath(name));
}

int AppTools::qmlWarnings() const
{
    return s_qmlWarnings;
}

int AppTools::commandsAnswered() const
{
    return ProcessRunner::answered();
}

QString AppTools::settingsFile() const
{
    return fixtures() ? file : QString();
}

int AppTools::fileMode() const
{
    struct stat info {};
    if (!fixtures() || ::lstat(QFile::encodeName(file).constData(), &info) != 0)
        return -1;
    return int(info.st_mode & 07777);
}

QVariant AppTools::storedValue(const QString &key) const
{
    if (!fixtures())
        return QVariant();
    QFile f(file);
    if (!f.open(QIODevice::ReadOnly))
        return QVariant();
    const QJsonObject root = QJsonDocument::fromJson(f.read(1024 * 1024)).object();
    return root.value(QLatin1String("settings")).toObject().value(key).toVariant();
}

void AppTools::finish(int code) const
{
    if (!fixtures())
        return;
    std::fprintf(stderr, "hearthwire-hyprland fixtures: warnings %d (QML %d), replies %d\n", s_warnings,
                 s_qmlWarnings, ProcessRunner::answered());
    QCoreApplication::exit(code);
}
