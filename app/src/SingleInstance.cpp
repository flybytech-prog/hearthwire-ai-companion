#include "SingleInstance.h"

#include <QDBusConnectionInterface>
#include <QDBusError>
#include <QDBusMessage>
#include <QDBusReply>

#include <unistd.h>

SingleInstance::SingleInstance(const QDBusConnection &connection, QObject *parent)
    : SingleInstance(connection, uint(::getuid()), parent)
{
}

SingleInstance::SingleInstance(const QDBusConnection &connection, uint ownUid, QObject *parent)
    : QObject(parent)
    , m_connection(connection)
    , m_ownUid(ownUid)
{
}

SingleInstance::Claim SingleInstance::claim()
{
    if (!m_connection.isConnected())
        return Claim::NoBus;
    if (!m_exported) {
        if (!m_connection.registerObject(QLatin1String(ObjectPath), this, QDBusConnection::ExportScriptableSlots))
            return Claim::NoBus;
        m_exported = true;
        m_connection.connect(QStringLiteral("org.freedesktop.DBus"), QStringLiteral("/org/freedesktop/DBus"),
                             QStringLiteral("org.freedesktop.DBus"), QStringLiteral("NameLost"), this,
                             SLOT(nameLost(QString)));
    }
    const QDBusReply<QDBusConnectionInterface::RegisterServiceReply> reply = m_connection.interface()->registerService(
        QLatin1String(ServiceName), QDBusConnectionInterface::DontQueueService, QDBusConnectionInterface::DontAllowReplacement);
    if (reply.isValid() && reply.value() == QDBusConnectionInterface::ServiceRegistered) {
        setAvailable(true);
        return Claim::Claimed;
    }
    // Not ours: no Show/Toggle on the unique name meanwhile (review-6-security INFO-3).
    unexport();
    return reply.isValid() ? Claim::Taken : Claim::NoBus;
}

void SingleInstance::unexport()
{
    if (!m_exported)
        return;
    m_connection.disconnect(QStringLiteral("org.freedesktop.DBus"), QStringLiteral("/org/freedesktop/DBus"),
                            QStringLiteral("org.freedesktop.DBus"), QStringLiteral("NameLost"), this,
                            SLOT(nameLost(QString)));
    m_connection.unregisterObject(QLatin1String(ObjectPath));
    m_exported = false;
}

QString SingleInstance::takeToken()
{
    QString token;
    token.swap(m_token);
    return token;
}

bool SingleInstance::callerAllowed(uint callerUid, uint ownUid)
{
    return callerUid == ownUid;
}

QString SingleInstance::filterToken(const QString &token)
{
    if (token.isEmpty() || token.size() > MaxTokenLength)
        return QString();
    for (const QChar c : token) {
        const char16_t u = c.unicode();
        const bool ok = (u >= u'a' && u <= u'z') || (u >= u'A' && u <= u'Z') || (u >= u'0' && u <= u'9') || u == u'_'
            || u == u'.' || u == u':' || u == u'+' || u == u'/' || u == u'=' || u == u'-';
        if (!ok)
            return QString();
    }
    return token;
}

bool SingleInstance::validTab(const QString &tab)
{
    return tab.isEmpty() || tab == QLatin1String("usage") || tab == QLatin1String("chat") || tab == QLatin1String("ollama");
}

SingleInstance::Forward SingleInstance::forward(const QDBusConnection &connection, bool toggle, const QString &tab,
                                                const QString &token)
{
    QDBusMessage call = QDBusMessage::createMethodCall(QLatin1String(ServiceName), QLatin1String(ObjectPath),
                                                       QLatin1String(InterfaceName),
                                                       toggle ? QStringLiteral("Toggle") : QStringLiteral("Show"));
    if (toggle)
        call << filterToken(token);
    else
        call << (validTab(tab) ? tab : QString()) << filterToken(token);
    const QDBusMessage reply = connection.call(call, QDBus::Block, ForwardTimeoutMs);
    if (reply.type() == QDBusMessage::ReplyMessage)
        return Forward::Done;
    const QString error = reply.errorName();
    if (error == QLatin1String("org.freedesktop.DBus.Error.ServiceUnknown")
        || error == QLatin1String("org.freedesktop.DBus.Error.NameHasNoOwner"))
        return Forward::NoOwner;
    return Forward::Failed;
}

void SingleInstance::Toggle(const QString &activationToken)
{
    if (!callerOk())
        return;
    m_token = filterToken(activationToken);
    Q_EMIT toggleRequested();
}

void SingleInstance::Show(const QString &tab, const QString &activationToken)
{
    if (!callerOk())
        return;
    if (!validTab(tab)) {
        if (calledFromDBus())
            sendErrorReply(QDBusError::InvalidArgs, QStringLiteral("unknown tab"));
        return;
    }
    m_token = filterToken(activationToken);
    Q_EMIT showRequested(tab);
}

bool SingleInstance::callerOk()
{
    // A direct call from C++/QML is the app itself.
    if (!calledFromDBus())
        return true;
    const QDBusReply<uint> uid = connection().interface()->serviceUid(message().service());
    if (uid.isValid() && callerAllowed(uid.value(), m_ownUid))
        return true;
    sendErrorReply(QDBusError::AccessDenied, QStringLiteral("not allowed"));
    return false;
}

void SingleInstance::nameLost(const QString &name)
{
    if (name == QLatin1String(ServiceName))
        setAvailable(false);
}

void SingleInstance::setAvailable(bool available)
{
    if (m_available == available)
        return;
    m_available = available;
    Q_EMIT availableChanged();
}
