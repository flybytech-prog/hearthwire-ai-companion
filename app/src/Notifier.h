// Notifier (task 012 R3.2): what the Notification stand-in's sendEvent()
// becomes in the app, a desktop notification through
// org.freedesktop.Notifications on the session bus.
//
// - Content: only what main.qml builds (catalog names, a whole percentage,
//   fixed backup texts); the plasmoid is unchanged. The summary is the
//   title, the body the text. No actions, app icon "hearthwire".
// - Hints: transient (the daemon shows it and keeps no history entry, if it
//   honours the hint), urgency as a byte, desktop-entry
//   "hearthwire-hyprland". Other daemons and bus monitors may still see or
//   keep it (docs/privacy.md).
// - Never blocks: every call is asynchronous, so a hung daemon can't freeze
//   the window.
// - Markup: the body arrives escaped (&lt; &gt; &amp;, main.qml's
//   markupSafe). GetCapabilities is asked once, on the first send; a daemon
//   without "body-markup" then gets the body un-escaped (exactly &lt;, &gt;,
//   then &amp; last). Until it answers, the body goes as it is.
// - Logging: never a title, body, event id or reply. The first failure
//   logs one fixed line, "notifications are not available"; then nothing.
//
// Modes: Off (the default: sendEvent() is counted, nothing is sent; the QML
// tests, fixture builds without --session-bus, no session bus), Record
// (tests: keeps the last call) and Bus (the app on a session bus).
#pragma once

#include <QDBusConnection>
#include <QObject>
#include <QString>
#include <QVariantMap>
#include <QtQml/qqmlregistration.h>

class QQmlEngine;
class QJSEngine;

class Notifier : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    Q_PROPERTY(Mode mode READ mode CONSTANT)
    Q_PROPERTY(int count READ count NOTIFY sentChanged)
    Q_PROPERTY(QVariantMap lastCall READ lastCall NOTIFY sentChanged)

public:
    enum class Mode { Off, Record, Bus };
    Q_ENUM(Mode)

    // The fixed D-Bus names and values (tests compare with these).
    static constexpr const char *Service = "org.freedesktop.Notifications";
    static constexpr const char *Path = "/org/freedesktop/Notifications";
    static constexpr const char *Interface = "org.freedesktop.Notifications";
    static constexpr const char *AppName = "Hearthwire";
    static constexpr const char *AppIcon = "hearthwire";
    static constexpr const char *DesktopEntry = "hearthwire-hyprland";
    static constexpr int CallTimeoutMs = 10000;

    // Bus mode talks on `connection` (the session bus in the app).
    Notifier(Mode mode, const QDBusConnection &connection, QObject *parent = nullptr);

    // The QML singleton: one per process, in the mode set before the first
    // engine asks for it.
    static Notifier *create(QQmlEngine *, QJSEngine *);
    static void setDefaultMode(Mode mode);

    Mode mode() const { return m_mode; }
    int count() const { return m_count; }
    // Record mode: {eventId, title, text, urgency} of the last send.
    QVariantMap lastCall() const { return m_last; }
    bool capabilitiesKnown() const { return m_capabilitiesKnown; }
    bool bodyMarkup() const { return m_bodyMarkup; }

    // urgency: KNotification's (Notification.qml's enum).
    Q_INVOKABLE void send(const QString &eventId, const QString &title, const QString &text, int urgency);

    // KNotification urgency -> the spec's byte: Low 0; Default, Normal,
    // High (and anything unknown) 1; Critical 2.
    static uchar busUrgency(int urgency);
    // The escaped body as plain text: &lt; and &gt;, then &amp; last.
    static QString plainBody(const QString &text);

Q_SIGNALS:
    void sentChanged();

private:
    void askCapabilities();
    void failed();

    Mode m_mode;
    QDBusConnection m_connection;
    int m_count = 0;
    QVariantMap m_last;
    bool m_capabilitiesAsked = false;
    bool m_capabilitiesKnown = false;
    bool m_bodyMarkup = false;
    bool m_failed = false;
};
