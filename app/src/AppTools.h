// The `App` singleton of Hearthwire.App: the one PlasmoidHost, and in a
// fixture build (CMake HW_FIXTURES=ON; never a release) the helpers the
// fixture checks and screenshots use (SpikeChecks.qml). In a release build
// `fixtures` is false and those helpers do nothing.
#pragma once

#include <QObject>
#include <QString>
#include <QVariant>
#include <QtQml/qqmlregistration.h>

#include "PlasmoidHost.h"
class QQmlEngine;
class QJSEngine;

class AppTools : public QObject
{
    Q_OBJECT
    QML_NAMED_ELEMENT(App)
    QML_SINGLETON
    Q_PROPERTY(bool fixtures READ fixtures CONSTANT)
    Q_PROPERTY(PlasmoidHost *host READ host CONSTANT)

public:
    explicit AppTools(PlasmoidHost *host, QObject *parent = nullptr);

    static AppTools *create(QQmlEngine *, QJSEngine *);
    static void setInstance(AppTools *tools);

    static bool fixtures();
    PlasmoidHost *host() const { return m_host; }

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

    static int s_warnings;
    static int s_qmlWarnings;

private:
    PlasmoidHost *m_host = nullptr;
};
