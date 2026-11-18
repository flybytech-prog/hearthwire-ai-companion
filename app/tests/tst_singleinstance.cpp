// SingleInstance (task 012 R3.1), on the test's private bus only
// (BusGuard.h): the name is owned once and can't be taken over, the two
// methods take only their enum and token, and nothing else is exported.
#include <QDBusConnection>
#include <QDBusConnectionInterface>
#include <QDBusMessage>
#include <QDBusPendingCall>
#include <QScopeGuard>
#include <QSignalSpy>
#include <QTest>
#include <QXmlStreamReader>

#include <memory>

#include <unistd.h>

#include "BusGuard.h"
#include "SingleInstance.h"

namespace {
const QString Name = QLatin1String(SingleInstance::ServiceName);
const QString OtherName = QStringLiteral("hw-test-other");
} // namespace

class TestSingleInstance : public QObject
{
    Q_OBJECT

private:
    std::unique_ptr<QDBusConnection> m_other;
    std::unique_ptr<SingleInstance> m_first;

    // A call from the other connection, answered by m_first on this
    // thread's event loop (so never a blocking call).
    QDBusMessage call(const QString &method, const QVariantList &args,
                      const QString &interface = QLatin1String(SingleInstance::InterfaceName))
    {
        return callOn(*m_other, Name, method, args, interface);
    }

    static QDBusMessage callOn(const QDBusConnection &from, const QString &service, const QString &method,
                               const QVariantList &args,
                               const QString &interface = QLatin1String(SingleInstance::InterfaceName))
    {
        QDBusMessage message = QDBusMessage::createMethodCall(service, QLatin1String(SingleInstance::ObjectPath), interface, method);
        message.setArguments(args);
        QDBusPendingCall pending = from.asyncCall(message, 5000);
        for (int i = 0; i < 500 && !pending.isFinished(); ++i)
            QTest::qWait(10);
        return pending.reply();
    }

private Q_SLOTS:
    void initTestCase()
    {
        QVERIFY2(hwOnPrivateBus(), hwPrivateBusMessage());
        QVERIFY(QDBusConnection::sessionBus().isConnected());
        m_other = std::make_unique<QDBusConnection>(QDBusConnection::connectToBus(QDBusConnection::SessionBus, OtherName));
        QVERIFY(m_other->isConnected());
        m_first = std::make_unique<SingleInstance>(QDBusConnection::sessionBus());
        QVERIFY(!m_first->available());
        QCOMPARE(m_first->claim(), SingleInstance::Claim::Claimed);
        QVERIFY(m_first->available());
    }

    void cleanupTestCase()
    {
        m_first.reset();
        QDBusConnection::disconnectFromBus(OtherName);
    }

    // Owned once: a second claim fails, and the name can't be taken over
    // even when asked to replace (DontAllowReplacement).
    void claimedOnce()
    {
        SingleInstance second(*m_other);
        QCOMPARE(second.claim(), SingleInstance::Claim::Taken);
        QVERIFY(!second.available());
        // Not ours, so not exported on the unique name either
        // (review-6-security INFO-3).
        QSignalSpy shown(&second, &SingleInstance::showRequested);
        const QDBusMessage onUnique = callOn(QDBusConnection::sessionBus(), m_other->baseService(), QStringLiteral("Show"),
                                             {QStringLiteral("usage"), QStringLiteral("tok")});
        QCOMPARE(onUnique.type(), QDBusMessage::ErrorMessage);
        QCOMPARE(shown.size(), 0);
        QCOMPARE(second.takeToken(), QString());
        const QDBusReply<QDBusConnectionInterface::RegisterServiceReply> replaced = m_other->interface()->registerService(
            Name, QDBusConnectionInterface::ReplaceExistingService, QDBusConnectionInterface::AllowReplacement);
        QVERIFY(replaced.isValid());
        QVERIFY(replaced.value() != QDBusConnectionInterface::ServiceRegistered);
        QCOMPARE(m_other->interface()->serviceOwner(Name).value(), QDBusConnection::sessionBus().baseService());
        // Not even queued behind us.
        m_other->interface()->unregisterService(Name);
    }

    void noBusIsNoClaim()
    {
        SingleInstance none(QDBusConnection(QStringLiteral("hw-never-connected")));
        QCOMPARE(none.claim(), SingleInstance::Claim::NoBus);
        QVERIFY(!none.available());
    }

    void show_data()
    {
        QTest::addColumn<QString>("tab");
        for (const char *tab : {"", "usage", "chat", "ollama"})
            QTest::newRow(*tab ? tab : "(keep)") << QString::fromLatin1(tab);
    }

    void show()
    {
        QFETCH(QString, tab);
        QSignalSpy shown(m_first.get(), &SingleInstance::showRequested);
        QSignalSpy toggled(m_first.get(), &SingleInstance::toggleRequested);
        const QDBusMessage reply = call(QStringLiteral("Show"), {tab, QStringLiteral("tok")});
        QCOMPARE(reply.type(), QDBusMessage::ReplyMessage);
        QVERIFY(reply.arguments().isEmpty());
        QCOMPARE(shown.size(), 1);
        QCOMPARE(shown.first().first().toString(), tab);
        QCOMPARE(toggled.size(), 0);
        QCOMPARE(m_first->takeToken(), QStringLiteral("tok"));
    }

    void aBadTabIsRefused_data()
    {
        QTest::addColumn<QString>("tab");
        for (const char *tab : {"nope", "Usage", "usage ", "settings", "chat/../usage", "ollama\n"})
            QTest::newRow(tab) << QString::fromLatin1(tab);
    }

    void aBadTabIsRefused()
    {
        QFETCH(QString, tab);
        QSignalSpy shown(m_first.get(), &SingleInstance::showRequested);
        const QDBusMessage reply = call(QStringLiteral("Show"), {tab, QStringLiteral("tok")});
        QCOMPARE(reply.type(), QDBusMessage::ErrorMessage);
        QCOMPARE(reply.errorName(), QStringLiteral("org.freedesktop.DBus.Error.InvalidArgs"));
        QCOMPARE(reply.errorMessage(), QStringLiteral("unknown tab"));
        QCOMPARE(shown.size(), 0);
        QCOMPARE(m_first->takeToken(), QString());
    }

    void aWrongSignatureIsRefused()
    {
        QSignalSpy shown(m_first.get(), &SingleInstance::showRequested);
        QSignalSpy toggled(m_first.get(), &SingleInstance::toggleRequested);
        QCOMPARE(call(QStringLiteral("Show"), {QStringLiteral("usage")}).type(), QDBusMessage::ErrorMessage);
        QCOMPARE(call(QStringLiteral("Toggle"), {42}).type(), QDBusMessage::ErrorMessage);
        QCOMPARE(call(QStringLiteral("nameLost"), {Name}).type(), QDBusMessage::ErrorMessage);
        QCOMPARE(call(QStringLiteral("takeToken"), {}).type(), QDBusMessage::ErrorMessage);
        QCOMPARE(shown.size() + toggled.size(), 0);
        QVERIFY(m_first->available());
    }

    void toggle()
    {
        QSignalSpy toggled(m_first.get(), &SingleInstance::toggleRequested);
        QSignalSpy shown(m_first.get(), &SingleInstance::showRequested);
        const QDBusMessage reply = call(QStringLiteral("Toggle"), {QStringLiteral("abc")});
        QCOMPARE(reply.type(), QDBusMessage::ReplyMessage);
        QVERIFY(reply.arguments().isEmpty());
        QCOMPARE(toggled.size(), 1);
        QCOMPARE(shown.size(), 0);
        QCOMPARE(m_first->takeToken(), QStringLiteral("abc"));
        // Taken once.
        QCOMPARE(m_first->takeToken(), QString());
    }

    void tokens_data()
    {
        QTest::addColumn<QString>("token");
        QTest::addColumn<QString>("kept");
        const QString valid = QStringLiteral("hyprland-1:abc_DEF.09+/=-");
        QTest::newRow("valid") << valid << valid;
        QTest::newRow("255 characters") << QString(255, QLatin1Char('a')) << QString(255, QLatin1Char('a'));
        QTest::newRow("256 characters") << QString(256, QLatin1Char('a')) << QString();
        QTest::newRow("a space") << QStringLiteral("abc def") << QString();
        QTest::newRow("a newline") << QStringLiteral("abc\n") << QString();
        QTest::newRow("a semicolon") << QStringLiteral("abc;rm") << QString();
        QTest::newRow("non-ASCII") << QStringLiteral("abcé") << QString();
        QTest::newRow("a NUL") << QStringLiteral("ab") + QChar(0) + QStringLiteral("c") << QString();
        QTest::newRow("empty") << QString() << QString();
    }

    void tokens()
    {
        QFETCH(QString, token);
        QFETCH(QString, kept);
        QCOMPARE(SingleInstance::filterToken(token), kept);
        // A D-Bus string can't hold a NUL (libdbus cuts it there): that row
        // is for the filter alone.
        if (token.contains(QChar(0)))
            return;
        QCOMPARE(call(QStringLiteral("Show"), {QStringLiteral("usage"), token}).type(), QDBusMessage::ReplyMessage);
        QCOMPARE(m_first->takeToken(), kept);
        QCOMPARE(call(QStringLiteral("Toggle"), {token}).type(), QDBusMessage::ReplyMessage);
        QCOMPARE(m_first->takeToken(), kept);
    }

    void callerAllowed_data()
    {
        QTest::addColumn<uint>("caller");
        QTest::addColumn<uint>("own");
        QTest::addColumn<bool>("allowed");
        QTest::newRow("the session user") << 1000u << 1000u << true;
        QTest::newRow("root calling a user's app") << 0u << 1000u << false;
        QTest::newRow("another user") << 1001u << 1000u << false;
        QTest::newRow("a user calling root's app") << 1000u << 0u << false;
        QTest::newRow("root, as root") << 0u << 0u << true;
    }

    void callerAllowed()
    {
        QFETCH(uint, caller);
        QFETCH(uint, own);
        QFETCH(bool, allowed);
        QCOMPARE(SingleInstance::callerAllowed(caller, own), allowed);
    }

    // The wiring of the uid check (review-6 L3): an app whose session user
    // is not the caller's uid refuses both calls with AccessDenied, emits
    // nothing and keeps no token.
    void aCallerOfAnotherUidIsRefused()
    {
        QVERIFY(QDBusConnection::sessionBus().interface()->unregisterService(Name).value());
        QTRY_VERIFY(!m_first->available());
        const QString thirdName = QStringLiteral("hw-test-third");
        auto stranger = std::make_unique<SingleInstance>(QDBusConnection::connectToBus(QDBusConnection::SessionBus, thirdName),
                                                         uint(::getuid()) + 1u);
        // Whatever fails below, the name goes back to m_first for the
        // other tests.
        const auto restore = qScopeGuard([&] {
            stranger.reset();
            QDBusConnection::disconnectFromBus(thirdName);
            QTRY_VERIFY(m_first->claim() == SingleInstance::Claim::Claimed);
        });
        QCOMPARE(stranger->claim(), SingleInstance::Claim::Claimed);
        QSignalSpy shown(stranger.get(), &SingleInstance::showRequested);
        QSignalSpy toggled(stranger.get(), &SingleInstance::toggleRequested);
        const QDBusMessage show = call(QStringLiteral("Show"), {QStringLiteral("usage"), QStringLiteral("tok")});
        QCOMPARE(show.type(), QDBusMessage::ErrorMessage);
        QCOMPARE(show.errorName(), QStringLiteral("org.freedesktop.DBus.Error.AccessDenied"));
        QCOMPARE(show.errorMessage(), QStringLiteral("not allowed"));
        const QDBusMessage toggle = call(QStringLiteral("Toggle"), {QStringLiteral("tok")});
        QCOMPARE(toggle.type(), QDBusMessage::ErrorMessage);
        QCOMPARE(toggle.errorName(), QStringLiteral("org.freedesktop.DBus.Error.AccessDenied"));
        QCOMPARE(shown.size() + toggled.size(), 0);
        QVERIFY(!stranger->hasToken());
    }

    // m_first, whose session user is the caller, takes the same call.
    void theSessionUserIsAllowed()
    {
        QVERIFY(m_first->available());
        QCOMPARE(call(QStringLiteral("Show"), {QStringLiteral("usage"), QStringLiteral("tok")}).type(), QDBusMessage::ReplyMessage);
        QCOMPARE(m_first->takeToken(), QStringLiteral("tok"));
    }

    // Exactly Toggle(s) and Show(ss), no out arguments, no properties, no
    // signals.
    void introspection()
    {
        const QDBusMessage reply = call(QStringLiteral("Introspect"), {}, QStringLiteral("org.freedesktop.DBus.Introspectable"));
        QCOMPARE(reply.type(), QDBusMessage::ReplyMessage);
        QXmlStreamReader xml(reply.arguments().value(0).toString());
        QStringList interfaces;
        QStringList methods;
        QStringList others;
        QString interface;
        QString method;
        while (!xml.atEnd()) {
            xml.readNext();
            if (xml.isStartElement()) {
                const QString name = xml.attributes().value(QLatin1String("name")).toString();
                if (xml.name() == QLatin1String("interface")) {
                    interface = name;
                    interfaces.append(name);
                } else if (interface == QLatin1String(SingleInstance::InterfaceName)) {
                    if (xml.name() == QLatin1String("method")) {
                        method = name;
                        methods.append(name + QLatin1Char('('));
                    } else if (xml.name() == QLatin1String("arg")) {
                        QVERIFY(xml.attributes().value(QLatin1String("direction")) != QLatin1String("out"));
                        methods.last() += xml.attributes().value(QLatin1String("type")).toString();
                    } else {
                        others.append(xml.name().toString() + QLatin1Char(' ') + name);
                    }
                }
            } else if (xml.isEndElement() && xml.name() == QLatin1String("interface")) {
                interface.clear();
            }
        }
        QVERIFY(!xml.hasError());
        interfaces.sort();
        QCOMPARE(interfaces, QStringList({QStringLiteral("io.github.flybytechprog.hearthwire.hyprland.Window"),
                                          QStringLiteral("org.freedesktop.DBus.Introspectable"),
                                          QStringLiteral("org.freedesktop.DBus.Peer"),
                                          QStringLiteral("org.freedesktop.DBus.Properties")}));
        methods.sort();
        QCOMPARE(methods, QStringList({QStringLiteral("Show(ss"), QStringLiteral("Toggle(s")}));
        QVERIFY2(others.isEmpty(), qPrintable(others.join(QLatin1String(", "))));
        // Properties.GetAll on our interface has nothing to give.
        const QDBusMessage all = call(QStringLiteral("GetAll"), {QLatin1String(SingleInstance::InterfaceName)},
                                      QStringLiteral("org.freedesktop.DBus.Properties"));
        QVERIFY(all.type() == QDBusMessage::ErrorMessage || all.arguments().value(0).toMap().isEmpty());
    }

    // Nobody owns the name: a later launch learns so (and claims it).
    void forwardWithNoOwner()
    {
        QDBusConnection::sessionBus().interface()->unregisterService(Name);
        QTRY_VERIFY(!m_first->available());
        QCOMPARE(SingleInstance::forward(*m_other, false, QStringLiteral("usage"), QStringLiteral("t")),
                 SingleInstance::Forward::NoOwner);
        QCOMPARE(SingleInstance::forward(*m_other, true, QString(), QString()), SingleInstance::Forward::NoOwner);
        QCOMPARE(m_first->claim(), SingleInstance::Claim::Claimed);
        QVERIFY(m_first->available());
    }

    // NameLost on our own name: available goes false (once).
    void nameLost()
    {
        QSignalSpy changed(m_first.get(), &SingleInstance::availableChanged);
        QVERIFY(m_first->available());
        QVERIFY(QDBusConnection::sessionBus().interface()->unregisterService(Name).value());
        QTRY_VERIFY(!m_first->available());
        QCOMPARE(changed.size(), 1);
        QCOMPARE(m_first->claim(), SingleInstance::Claim::Claimed);
    }
};

QTEST_GUILESS_MAIN(TestSingleInstance)
#include "tst_singleinstance.moc"
