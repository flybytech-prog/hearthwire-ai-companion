// The `App` singleton of Hearthwire.App: the one PlasmoidHost, the
// SingleInstance (task 012 R3.1), present() and quit() for the window, the
// About page's values (R4 P2c), and
// in a fixture build (CMake HW_FIXTURES=ON; never a release) the helpers
// the fixture checks and screenshots use (SpikeChecks.qml). In a release
// build `fixtures` is false and those helpers do nothing.
#pragma once

#include <QList>
#include <QObject>
#include <QString>
#include <QVariant>
#include <QVariantMap>
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
    // The About page's values, fixed at build time (AboutInfo.h).
    Q_PROPERTY(QVariantMap about READ about CONSTANT)

public:
    AppTools(PlasmoidHost *host, SingleInstance *instance, QObject *parent = nullptr);

    static AppTools *create(QQmlEngine *, QJSEngine *);
    static void setInstance(AppTools *tools);

    static bool fixtures();
    PlasmoidHost *host() const { return m_host; }
    SingleInstance *instance() const { return m_instance; }

    // Shows, raises and activates the window, with exactly one activation
    // request (task 012 R4 P2b, F4), in the order presentSteps() gives:
    // 1. the last Show/Toggle call's token, if any, goes into
    //    XDG_ACTIVATION_TOKEN BEFORE show();
    // 2. show(), raise();
    // 3. requestActivate() only if needsRequestActivate(wasVisible, Wayland);
    // 4. XDG_ACTIVATION_TOKEN is always removed again.
    // Why (qtbase v6.12.0, tag object fcef5b2c755492753eb8f7424dd2bc7337832068,
    // src/plugins/platforms/wayland/): qwaylandwindow.cpp setVisible()
    // (644-664) calls the shell surface's requestActivateOnShow() (656) when
    // a hidden window is shown; plugins/shellintegration/xdg-shell/
    // qwaylandxdgshell.cpp requestActivateOnShow() (624-638) calls
    // requestActivate() (584-622), which uses a pending token (587-590),
    // else reads XDG_ACTIVATION_TOKEN (591) and unsets it (593), else asks
    // the compositor for a token of its own with the last input serial
    // (595-617). A later QWindow::requestActivate() goes the same way
    // (qwaylandwindow.cpp requestActivateWindow(), 1599-1603). So showing a
    // hidden window already activates once, with our token if it is in the
    // environment by then; a second requestActivate() would be a second,
    // tokenless activation. A window that was already shown gets no
    // activation from show(), so there it is our requestActivate().
    // Other platforms (X11, offscreen) don't activate on show: always
    // requestActivate() there.
    // The token is in the process environment for the length of this call,
    // and any getenv() in the process sees it meanwhile: the QML and C++
    // handlers that show() runs synchronously on this thread (visibleChanged,
    // QShowEvent, before the platform window reads the variable) and Qt's
    // other threads (QtDBus, the QML loader, the scene graph), which could
    // read it at any moment of the call (review-6 I3, review-7 L2). What
    // keeps it in: ProcessRunner never passes XDG_ACTIVATION_TOKEN to the
    // helper (its environment allow-list), and app_starts_nothing_else
    // (check_no_opener.py) keeps any other process start out of the app.
    // present() must not be re-entered from a show handler: a nested call
    // would remove the variable before the outer show() has used it (a
    // tokenless activation, F4). So a nested call is ignored (m_presenting):
    // the outer call is already showing, raising and activating the window,
    // and the nested one takes no token (a token that arrived meanwhile
    // waits in SingleInstance for the next present() or dropToken()). It is
    // ignored rather than deferred: run afterwards it would be a second
    // activation request. There is no other
    // public way to hand Qt a token: the private
    // QWaylandWindow::setXdgActivationToken() logs the token when the window
    // has no surface role yet (qwaylandwindow.cpp 1891-1896), so it is not
    // used.
    Q_INVOKABLE void present(QObject *window);
    enum class Step { SetToken, Show, Raise, Activate, UnsetToken };
    Q_ENUM(Step)
    // The steps of present(), in order (pure; unit-tested).
    static QList<Step> presentSteps(bool hasToken, bool wasVisible, bool isWayland);
    // Whether present() must call requestActivate() itself: the window was
    // already shown, or the platform doesn't activate on show (not Wayland).
    static bool needsRequestActivate(bool wasVisible, bool isWayland);
    static bool platformIsWayland();
    // The window was hidden instead: the last call's token is dropped.
    Q_INVOKABLE void dropToken();
    // The window was closed: the app quits (fixture checks may hold it).
    Q_INVOKABLE void quit();

    // {name, appId, version, comment, license, authors (the names joined
    // with ", "), authorCount, website, bugReportUrl, icon}:
    // plasmoid/metadata.json and the .desktop file's Comment, read by CMake
    // at configure time.
    static QVariantMap about();
    // Puts one of the About page's links (website, bugReportUrl) on the
    // clipboard; false for any other key. Nothing is opened or started.
    Q_INVOKABLE bool copyAbout(const QString &key) const;

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
    // The clipboard's text ("" in a release build).
    Q_INVOKABLE QString clipboardText() const;

    static int s_warnings;
    static int s_qmlWarnings;

private:
    PlasmoidHost *m_host = nullptr;
    SingleInstance *m_instance = nullptr;
    bool m_holdQuit = false;
    int m_quitRequests = 0;
    int m_presents = 0;
    // present() is running (a nested call is ignored, see present()).
    bool m_presenting = false;
};
