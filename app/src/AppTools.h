// The `App` singleton of Hearthwire.App: the one PlasmoidHost, the
// SingleInstance (task 012 R3.1), present() and quit() for the window, and
// in a fixture build (CMake HW_FIXTURES=ON; never a release) the helpers
// the fixture checks and screenshots use (SpikeChecks.qml). In a release
// build `fixtures` is false and those helpers do nothing.
#pragma once

#include <QObject>
#include <QString>
#include <QVariant>
#include <QtQml/qqmlregistration.h>

#include "PlasmoidHost.h"
#include "SingleInstance.h"
class QQmlEngine;
class QJSEngine;

class AppTools : public QObject
{
    Q_OBJECT
    QML_NAMED_ELEMENT(App)
    QML_SINGLETON
    Q_PROPERTY(bool fixtures READ fixtures CONSTANT)
    Q_PROPERTY(PlasmoidHost *host READ host CONSTANT)
    Q_PROPERTY(SingleInstance *instance READ instance CONSTANT)

public:
    AppTools(PlasmoidHost *host, SingleInstance *instance, QObject *parent = nullptr);

    static AppTools *create(QQmlEngine *, QJSEngine *);
    static void setInstance(AppTools *tools);

    static bool fixtures();
    PlasmoidHost *host() const { return m_host; }
    SingleInstance *instance() const { return m_instance; }

    // Shows, raises and activates the window. With an activation token from
    // the last Show/Toggle call, XDG_ACTIVATION_TOKEN holds it only around
    // requestActivate() (qtwayland's xdg-shell reads and unsets it there).
    Q_INVOKABLE void present(QObject *window);
    // The window was hidden instead: the last call's token is dropped.
    Q_INVOKABLE void dropToken();
    // The window was closed: the app quits (fixture checks may hold it).
    Q_INVOKABLE void quit();

    // Fixture builds only (set by main.cpp's fixture options).
    QString shotsDir;
    bool checks = false;
    QString file;

    Q_INVOKABLE QString shots() const;
    Q_INVOKABLE bool runChecks() const;
    Q_INVOKABLE bool grab(QObject *window, const QString &name) const;
    Q_INVOKABLE int qmlWarnings() const;
    Q_INVOKABLE int commandsAnswered() const;
    Q_INVOKABLE QString settingsFile() const;
    // The file's permission bits (0600 expected) and a value as stored.
    Q_INVOKABLE int fileMode() const;
    Q_INVOKABLE QVariant storedValue(const QString &key) const;
    Q_INVOKABLE void finish(int code) const;
    // UrlGuard refusals so far (-1 in a release build).
    Q_INVOKABLE int guardRefusals() const;
    // Sends a key press and release to the window, as a user would.
    Q_INVOKABLE bool sendKey(QObject *window, int key) const;
    // Single instance as if on a bus, and its two calls (from the app, not
    // the bus). Fixture builds only; nothing in a release build.
    Q_INVOKABLE void simulateInstance(bool available);
    Q_INVOKABLE void simulateShow(const QString &tab, const QString &token = QString());
    Q_INVOKABLE void simulateToggle(const QString &token = QString());
    // How many times present() ran, and whether a token is waiting
    // (-1 / false in a release build; never the token).
    Q_INVOKABLE int presents() const;
    Q_INVOKABLE bool tokenPending() const;
    // quit() only counts while held; how many times it was called.
    Q_INVOKABLE void holdQuit(bool hold);
    Q_INVOKABLE int quitRequests() const;

    static int s_warnings;
    static int s_qmlWarnings;

private:
    PlasmoidHost *m_host = nullptr;
    SingleInstance *m_instance = nullptr;
    bool m_holdQuit = false;
    int m_quitRequests = 0;
    int m_presents = 0;
};
