#include "Notifier.h"

#include <QCoreApplication>
#include <QDBusMessage>
#include <QDBusPendingCall>
#include <QDBusPendingCallWatcher>
#include <QDBusPendingReply>
#include <QPointer>
#include <QQmlEngine>
#include <QStringList>

namespace {
QPointer<Notifier> s_notifier;
Notifier::Mode s_mode = Notifier::Mode::Off;
}

Notifier::Notifier(Mode mode, const QDBusConnection &connection, QObject *parent)
    : QObject(parent)
    , m_mode(mode)
    , m_connection(connection)
{
}

Notifier *Notifier::create(QQmlEngine *, QJSEngine *)
{
    if (!s_notifier) {
        // Only Bus mode touches a bus; the others get a connection that
        // was never made.
        const QDBusConnection connection = s_mode == Mode::Bus ? QDBusConnection::sessionBus()
                                                                : QDBusConnection(QStringLiteral("hearthwire-no-bus"));
        s_notifier = new Notifier(s_mode, connection, QCoreApplication::instance());
    }
    QQmlEngine::setObjectOwnership(s_notifier, QQmlEngine::CppOwnership);
    return s_notifier;
}

void Notifier::setDefaultMode(Mode mode)
{
    s_mode = mode;
}

uchar Notifier::busUrgency(int urgency)
{
    switch (urgency) {
    case 10: // LowUrgency
        return 0;
    case 90: // CriticalUrgency
        return 2;
    default: // DefaultUrgency, NormalUrgency, HighUrgency
        return 1;
    }
}

QString Notifier::plainBody(const QString &text)
{
    QString plain = text;
    plain.replace(QLatin1String("&lt;"), QLatin1String("<"));
    plain.replace(QLatin1String("&gt;"), QLatin1String(">"));
    plain.replace(QLatin1String("&amp;"), QLatin1String("&"));
    return plain;
}

void Notifier::send(const QString &eventId, const QString &title, const QString &text, int urgency)
{
    ++m_count;
    if (m_mode == Mode::Off) {
        Q_EMIT sentChanged();
        return;
    }
    const uchar level = busUrgency(urgency);
    const QString body = m_capabilitiesKnown && !m_bodyMarkup ? plainBody(text) : text;
    if (m_mode == Mode::Record) {
        m_last = QVariantMap{{QStringLiteral("eventId"), eventId},
                             {QStringLiteral("title"), title},
                             {QStringLiteral("text"), body},
                             {QStringLiteral("urgency"), int(level)}};
        Q_EMIT sentChanged();
        return;
    }
    Q_EMIT sentChanged();
    if (!m_connection.isConnected()) {
        failed();
        return;
    }
    if (!m_capabilitiesAsked)
        askCapabilities();

    QDBusMessage call = QDBusMessage::createMethodCall(QLatin1String(Service), QLatin1String(Path),
                                                       QLatin1String(Interface), QStringLiteral("Notify"));
    const QVariantMap hints{{QStringLiteral("transient"), true},
                            {QStringLiteral("urgency"), QVariant::fromValue<uchar>(level)},
                            {QStringLiteral("desktop-entry"), QLatin1String(DesktopEntry)}};
    call << QLatin1String(AppName) << uint(0) << QLatin1String(AppIcon) << title << body << QStringList() << hints
         << int(-1);
    auto *watcher = new QDBusPendingCallWatcher(m_connection.asyncCall(call, CallTimeoutMs), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this, [this](QDBusPendingCallWatcher *done) {
        if (done->isError())
            failed();
        done->deleteLater();
    });
}

void Notifier::askCapabilities()
{
    m_capabilitiesAsked = true;
    const QDBusMessage call = QDBusMessage::createMethodCall(QLatin1String(Service), QLatin1String(Path),
                                                             QLatin1String(Interface), QStringLiteral("GetCapabilities"));
    auto *watcher = new QDBusPendingCallWatcher(m_connection.asyncCall(call, CallTimeoutMs), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this, [this](QDBusPendingCallWatcher *done) {
        const QDBusPendingReply<QStringList> reply = *done;
        if (reply.isError()) {
            failed();
        } else {
            m_bodyMarkup = reply.value().contains(QStringLiteral("body-markup"));
            m_capabilitiesKnown = true;
        }
        done->deleteLater();
    });
}

void Notifier::failed()
{
    if (m_failed)
        return;
    m_failed = true;
    qWarning("hearthwire-hyprland: notifications are not available");
}
