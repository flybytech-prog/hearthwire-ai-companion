#include "AppTools.h"

#include "PlasmoidHost.h"
#include "ProcessRunner.h"
#include "UrlGuard.h"

#include <QCoreApplication>
#include <QGuiApplication>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QKeyEvent>
#include <QQmlEngine>
#include <QQuickWindow>

#include <cstdio>
#include <sys/stat.h>

namespace {
AppTools *s_tools = nullptr;
}

int AppTools::s_warnings = 0;
int AppTools::s_qmlWarnings = 0;

AppTools::AppTools(PlasmoidHost *host, SingleInstance *instance, QObject *parent)
    : QObject(parent)
    , m_host(host)
    , m_instance(instance)
{
}

void AppTools::present(QObject *window)
{
    auto *quick = qobject_cast<QQuickWindow *>(window);
    if (!quick)
        return;
    ++m_presents;
    quick->show();
    quick->raise();
    const QString token = m_instance ? SingleInstance::filterToken(m_instance->takeToken()) : QString();
    if (token.isEmpty()) {
        quick->requestActivate();
        return;
    }
    qputenv("XDG_ACTIVATION_TOKEN", token.toLatin1());
    quick->requestActivate();
    // qtwayland has used and unset it; without Wayland it is still ours.
    qunsetenv("XDG_ACTIVATION_TOKEN");
}

void AppTools::dropToken()
{
    if (m_instance)
        m_instance->takeToken();
}

void AppTools::quit()
{
    if (fixtures() && m_holdQuit) {
        ++m_quitRequests;
        return;
    }
    QCoreApplication::quit();
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

int AppTools::guardRefusals() const
{
    return fixtures() ? UrlGuard::refusals() : -1;
}

void AppTools::simulateInstance(bool available)
{
#ifdef HW_FIXTURES
    if (m_instance)
        m_instance->simulateAvailable(available);
#else
    Q_UNUSED(available)
#endif
}

void AppTools::simulateShow(const QString &tab, const QString &token)
{
    if (fixtures() && m_instance)
        m_instance->Show(tab, token);
}

void AppTools::simulateToggle(const QString &token)
{
    if (fixtures() && m_instance)
        m_instance->Toggle(token);
}

int AppTools::presents() const
{
    return fixtures() ? m_presents : -1;
}

bool AppTools::tokenPending() const
{
    return fixtures() && m_instance && m_instance->hasToken();
}

void AppTools::holdQuit(bool hold)
{
    if (!fixtures())
        return;
    m_holdQuit = hold;
    // Held, the last window closing doesn't end the checks either.
    QGuiApplication::setQuitOnLastWindowClosed(!hold);
}

int AppTools::quitRequests() const
{
    return fixtures() ? m_quitRequests : -1;
}

bool AppTools::sendKey(QObject *window, int key) const
{
    auto *quick = qobject_cast<QQuickWindow *>(window);
    if (!fixtures() || !quick)
        return false;
    QKeyEvent press(QEvent::KeyPress, key, Qt::NoModifier);
    QKeyEvent release(QEvent::KeyRelease, key, Qt::NoModifier);
    QCoreApplication::sendEvent(quick, &press);
    QCoreApplication::sendEvent(quick, &release);
    return true;
}
