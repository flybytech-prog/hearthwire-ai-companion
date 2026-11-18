// SingleInstance (task 012 R3.1): one hearthwire-hyprland per session. The
// first copy owns a name on the session bus; a later launch asks it to show
// itself (or toggle) and ends. docs/provider-contracts.md "App mode" has the
// contract:
// - bus name io.github.flybytechprog.hearthwire.hyprland, object
//   /io/github/flybytechprog/hearthwire/hyprland, interface
//   io.github.flybytechprog.hearthwire.hyprland.Window;
// - exported with ExportScriptableSlots only (no properties, no signals):
//     Toggle(s activationToken)
//     Show(s tab, s activationToken)   tab: "", usage, chat or ollama
//   both return nothing. Another tab gets InvalidArgs, a caller that is not
//   the session user AccessDenied (both fixed messages), and nothing happens;
// - an activation token is kept only when it is 1..255 characters of
//   [A-Za-z0-9_.:+/=-], else it is "" (the sending side filters the same).
// The methods never return data, never read or write settings and never
// run a helper: they only emit toggleRequested() / showRequested(), which
// move the window and pick a tab (AppWindow.qml).
#pragma once

#include <QDBusConnection>
#include <QDBusContext>
#include <QObject>
#include <QString>
#include <QtQml/qqmlregistration.h>

class SingleInstance : public QObject, protected QDBusContext
{
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "io.github.flybytechprog.hearthwire.hyprland.Window")
    QML_ANONYMOUS
    Q_PROPERTY(bool available READ available NOTIFY availableChanged)

public:
    static constexpr const char *ServiceName = "io.github.flybytechprog.hearthwire.hyprland";
    static constexpr const char *ObjectPath = "/io/github/flybytechprog/hearthwire/hyprland";
    static constexpr const char *InterfaceName = "io.github.flybytechprog.hearthwire.hyprland.Window";
    static constexpr int ForwardTimeoutMs = 5000;
    static constexpr int MaxTokenLength = 255;

    enum class Claim { Claimed, Taken, NoBus };
    enum class Forward { Done, NoOwner, Failed };

    // `connection`: the session bus (it may be one that is not connected).
    // The session user is getuid().
    explicit SingleInstance(const QDBusConnection &connection, QObject *parent = nullptr);
    // As above with the session user given (tests: a caller that is not it).
    SingleInstance(const QDBusConnection &connection, uint ownUid, QObject *parent = nullptr);

    // Owns the name (DontQueueService, DontAllowReplacement) with the
    // object exported first, so a call can't come before the object. When
    // the name is not ours (Taken, NoBus) the object is unexported again,
    // so nothing can reach it on the connection's unique name either.
    Claim claim();
    // Whether this copy owns the name (and so may hide its window).
    bool available() const { return m_available; }
    // The token of the last call, once (empty when none or refused).
    QString takeToken();
    // Whether a token is waiting (never the token itself).
    bool hasToken() const { return !m_token.isEmpty(); }

    // Defence in depth on a session bus: only the session user may call.
    static bool callerAllowed(uint callerUid, uint ownUid);
    // The token rule, both sides: the token or "".
    static QString filterToken(const QString &token);
    // "", usage, chat or ollama.
    static bool validTab(const QString &tab);
    // A later launch: Toggle(token) when `toggle`, else Show(tab, token),
    // waiting at most ForwardTimeoutMs for the answer.
    static Forward forward(const QDBusConnection &connection, bool toggle, const QString &tab, const QString &token);

#ifdef HW_FIXTURES
    // Fixture checks only (compiled out of a release build).
    void simulateAvailable(bool available) { setAvailable(available); }
#endif

public Q_SLOTS:
    Q_SCRIPTABLE void Toggle(const QString &activationToken);
    Q_SCRIPTABLE void Show(const QString &tab, const QString &activationToken);

Q_SIGNALS:
    void availableChanged();
    void toggleRequested();
    void showRequested(const QString &tab);

private Q_SLOTS:
    void nameLost(const QString &name);

private:
    bool callerOk();
    void setAvailable(bool available);
    void unexport();

    QDBusConnection m_connection;
    uint m_ownUid = 0;
    bool m_available = false;
    bool m_exported = false;
    QString m_token;
};
