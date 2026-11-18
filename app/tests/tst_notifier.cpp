// Notifier (task 012 R3.2), on the test's private bus only (BusGuard.h): a
// fake org.freedesktop.Notifications on a second connection checks what is
// sent, that nothing blocks, and that nothing is logged but one fixed line.
#include <QDBusConnection>
#include <QDBusConnectionInterface>
#include <QDBusContext>
#include <QDBusMessage>
#include <QElapsedTimer>
#include <QMutex>
#include <QSemaphore>
#include <QThread>
#include <QTest>

#include <memory>

#include "BusGuard.h"
#include "Notifier.h"

namespace {
QStringList s_messages;
QtMessageHandler s_previous = nullptr;

void capture(QtMsgType type, const QMessageLogContext &context, const QString &message)
{
    s_messages.append(message);
    if (s_previous)
        s_previous(type, context, message);
}

const QString FakeName = QStringLiteral("hw-fake-notifications");
} // namespace

class FakeNotifications : public QObject, protected QDBusContext
{
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "org.freedesktop.Notifications")

public:
    struct Call {
        QString signature;
        QString appName;
        uint replacesId = 99;
        QString appIcon;
        QString summary;
        QString body;
        QStringList actions;
        QVariantMap hints;
        int expireTimeout = 0;
    };

    QStringList capabilities;
    bool hold = false;
    int capabilitiesAsked = 0;
    QList<Call> calls;
    QList<QDBusMessage> held;

Q_SIGNALS:
    void notified();

public Q_SLOTS:
    QStringList GetCapabilities()
    {
        ++capabilitiesAsked;
        return capabilities;
    }

    uint Notify(const QString &appName, uint replacesId, const QString &appIcon, const QString &summary,
                const QString &body, const QStringList &actions, const QVariantMap &hints, int expireTimeout)
    {
        calls.append({message().signature(), appName, replacesId, appIcon, summary, body, actions, hints, expireTimeout});
        if (hold) {
            setDelayedReply(true);
            held.append(message());
        }
        Q_EMIT notified();
        return uint(calls.size());
    }
};

// A notification daemon on its own thread and connection that takes every
// Notify and never answers it. waitReady() returns once it owns the name
// (or failed to), so nothing is timed before then (review-6-security
// INFO-5), and the destructor always stops the thread, whatever check
// failed first.
class HungDaemon : public QThread
{
public:
    ~HungDaemon() override
    {
        quit();
        wait();
    }

    // True when the daemon owns the name, within `ms`.
    bool waitReady(int ms)
    {
        if (!m_ready.tryAcquire(1, ms))
            return false;
        return m_owned.loadAcquire() != 0;
    }
    int received() const { return m_received.loadAcquire(); }
    QString unique() const
    {
        QMutexLocker lock(&m_mutex);
        return m_unique;
    }

protected:
    void run() override
    {
        const QString name = QStringLiteral("hw-hung-daemon");
        {
            QDBusConnection connection = QDBusConnection::connectToBus(QDBusConnection::SessionBus, name);
            FakeNotifications fake;
            fake.hold = true;
            connection.registerObject(QLatin1String(Notifier::Path), &fake, QDBusConnection::ExportAllSlots);
            connect(&fake, &FakeNotifications::notified, &fake, [this] { m_received.fetchAndAddRelease(1); });
            const QDBusReply<QDBusConnectionInterface::RegisterServiceReply> reply =
                connection.interface()->registerService(QLatin1String(Notifier::Service));
            {
                QMutexLocker lock(&m_mutex);
                m_unique = connection.baseService();
            }
            m_owned.storeRelease(reply.isValid() && reply.value() == QDBusConnectionInterface::ServiceRegistered ? 1 : 0);
            m_ready.release();
            exec();
            connection.unregisterObject(QLatin1String(Notifier::Path));
            connection.interface()->unregisterService(QLatin1String(Notifier::Service));
        }
        QDBusConnection::disconnectFromBus(name);
    }

private:
    mutable QMutex m_mutex;
    QString m_unique;
    QAtomicInt m_received;
    QAtomicInt m_owned;
    QSemaphore m_ready;
};

class TestNotifier : public QObject
{
    Q_OBJECT

private:
    FakeNotifications m_fake;
    std::unique_ptr<QDBusConnection> m_server;

    bool serve(bool on)
    {
        QDBusConnectionInterface *bus = m_server->interface();
        if (on)
            return bus->registerService(QLatin1String(Notifier::Service)).value() == QDBusConnectionInterface::ServiceRegistered;
        return bus->unregisterService(QLatin1String(Notifier::Service)).value();
    }

    static std::unique_ptr<Notifier> busNotifier()
    {
        return std::make_unique<Notifier>(Notifier::Mode::Bus, QDBusConnection::sessionBus());
    }

    static bool logged(const QString &text)
    {
        for (const QString &line : std::as_const(s_messages)) {
            if (line.contains(text))
                return true;
        }
        return false;
    }

private Q_SLOTS:
    void initTestCase()
    {
        QVERIFY2(hwOnPrivateBus(), hwPrivateBusMessage());
        s_previous = qInstallMessageHandler(capture);
        m_server = std::make_unique<QDBusConnection>(QDBusConnection::connectToBus(QDBusConnection::SessionBus, FakeName));
        QVERIFY(m_server->isConnected());
        QVERIFY(QDBusConnection::sessionBus().isConnected());
        QVERIFY(m_server->registerObject(QLatin1String(Notifier::Path), &m_fake, QDBusConnection::ExportAllSlots));
        QVERIFY(serve(true));
    }

    void init()
    {
        m_fake.calls.clear();
        m_fake.capabilities = {QStringLiteral("body")};
        m_fake.capabilitiesAsked = 0;
        m_fake.hold = false;
    }

    void cleanupTestCase()
    {
        // Nothing that was sent ever reached the log.
        for (const char *secret : {"Claude is running low", "Session: 20% left", "usageLow", "hw-secret-title",
                                   "hw-secret-body", "hw-hung-title"})
            QVERIFY2(!logged(QLatin1String(secret)), secret);
        qInstallMessageHandler(s_previous);
        m_server->unregisterObject(QLatin1String(Notifier::Path));
        QDBusConnection::disconnectFromBus(FakeName);
    }

    void exactArguments()
    {
        const auto notifier = busNotifier();
        notifier->send(QStringLiteral("usageLow"), QStringLiteral("Claude is running low"), QStringLiteral("Session: 20% left"), 50);
        QCOMPARE(notifier->count(), 1);
        QTRY_COMPARE(m_fake.calls.size(), 1);
        const FakeNotifications::Call call = m_fake.calls.first();
        QCOMPARE(call.signature, QStringLiteral("susssasa{sv}i"));
        QCOMPARE(call.appName, QStringLiteral("Hearthwire"));
        QCOMPARE(call.replacesId, 0u);
        QCOMPARE(call.appIcon, QStringLiteral("hearthwire"));
        QCOMPARE(call.summary, QStringLiteral("Claude is running low"));
        QCOMPARE(call.body, QStringLiteral("Session: 20% left"));
        QVERIFY(call.actions.isEmpty());
        QCOMPARE(call.expireTimeout, -1);
        QCOMPARE(call.hints.keys(), QStringList({QStringLiteral("desktop-entry"), QStringLiteral("transient"), QStringLiteral("urgency")}));
        QCOMPARE(call.hints.value(QStringLiteral("transient")).metaType(), QMetaType::fromType<bool>());
        QCOMPARE(call.hints.value(QStringLiteral("transient")).toBool(), true);
        QCOMPARE(call.hints.value(QStringLiteral("urgency")).metaType(), QMetaType::fromType<uchar>());
        QCOMPARE(call.hints.value(QStringLiteral("urgency")).value<uchar>(), uchar(1));
        QCOMPARE(call.hints.value(QStringLiteral("desktop-entry")).toString(), QStringLiteral("hearthwire-hyprland"));
    }

    void urgency_data()
    {
        QTest::addColumn<int>("urgency");
        QTest::addColumn<int>("byte");
        QTest::newRow("low") << 10 << 0;
        QTest::newRow("default") << -1 << 1;
        QTest::newRow("normal") << 50 << 1;
        QTest::newRow("high") << 70 << 1;
        QTest::newRow("critical") << 90 << 2;
        QTest::newRow("unknown") << 33 << 1;
    }

    void urgency()
    {
        QFETCH(int, urgency);
        QFETCH(int, byte);
        QCOMPARE(int(Notifier::busUrgency(urgency)), byte);
        const auto notifier = busNotifier();
        notifier->send(QStringLiteral("e"), QStringLiteral("t"), QStringLiteral("b"), urgency);
        QTRY_COMPARE(m_fake.calls.size(), 1);
        const QVariant sent = m_fake.calls.first().hints.value(QStringLiteral("urgency"));
        QCOMPARE(sent.metaType(), QMetaType::fromType<uchar>());
        QCOMPARE(int(sent.value<uchar>()), byte);
    }

    void markup_data()
    {
        QTest::addColumn<QStringList>("capabilities");
        QTest::addColumn<QString>("later");
        const QString escaped = QStringLiteral("a &lt;b&gt; &amp;lt; &quot;");
        QTest::newRow("no body-markup: un-escaped, &amp; last")
            << QStringList{QStringLiteral("body")} << QStringLiteral("a <b> &lt; &quot;");
        QTest::newRow("body-markup: kept") << QStringList{QStringLiteral("body"), QStringLiteral("body-markup")} << escaped;
    }

    void markup()
    {
        QFETCH(QStringList, capabilities);
        QFETCH(QString, later);
        m_fake.capabilities = capabilities;
        const QString escaped = QStringLiteral("a &lt;b&gt; &amp;lt; &quot;");
        const auto notifier = busNotifier();
        notifier->send(QStringLiteral("e"), QStringLiteral("t"), escaped, 50);
        QTRY_COMPARE(m_fake.calls.size(), 1);
        // Sent before the daemon answered: as it is.
        QCOMPARE(m_fake.calls.at(0).body, escaped);
        QTRY_VERIFY(notifier->capabilitiesKnown());
        notifier->send(QStringLiteral("e"), QStringLiteral("t"), escaped, 50);
        notifier->send(QStringLiteral("e"), QStringLiteral("t"), escaped, 50);
        QTRY_COMPARE(m_fake.calls.size(), 3);
        QCOMPARE(m_fake.calls.at(1).body, later);
        QCOMPARE(m_fake.calls.at(2).body, later);
        // Asked once.
        QCOMPARE(m_fake.capabilitiesAsked, 1);
        // The summary is never touched.
        QCOMPARE(m_fake.calls.at(2).summary, QStringLiteral("t"));
    }

    void plainBody()
    {
        QCOMPARE(Notifier::plainBody(QStringLiteral("&amp;gt;")), QStringLiteral("&gt;"));
        QCOMPARE(Notifier::plainBody(QStringLiteral("&lt;&gt;&amp;")), QStringLiteral("<>&"));
        QCOMPARE(Notifier::plainBody(QStringLiteral("&quot;&#60;")), QStringLiteral("&quot;&#60;"));
    }

    // A daemon that never answers can't hold up send(). It runs on its own
    // thread, so a blocking call would really wait for it (on this thread
    // QtDBus would fail such a call at once instead).
    void aHungDaemonDoesNotBlock()
    {
        QVERIFY(serve(false));
        HungDaemon hung;
        hung.start();
        QVERIFY(hung.waitReady(10000));
        QCOMPARE(QDBusConnection::sessionBus().interface()->serviceOwner(QLatin1String(Notifier::Service)).value(),
                 hung.unique());
        const auto notifier = busNotifier();
        QElapsedTimer timer;
        timer.start();
        notifier->send(QStringLiteral("e"), QStringLiteral("hw-hung-title"), QStringLiteral("b"), 50);
        notifier->send(QStringLiteral("e"), QStringLiteral("hw-hung-title"), QStringLiteral("b"), 50);
        const qint64 elapsed = timer.elapsed();
        QTRY_COMPARE(hung.received(), 2);
        hung.quit();
        QVERIFY(hung.wait(10000));
        QVERIFY2(elapsed < 100, qPrintable(QStringLiteral("%1 ms").arg(elapsed)));
        QTRY_VERIFY(QDBusConnection::sessionBus().interface()->serviceOwner(QLatin1String(Notifier::Service)).value().isEmpty());
        QVERIFY(serve(true));
    }

    // No notification daemon: send() returns at once, one fixed line, then
    // silence; neither title nor body is logged.
    void noDaemon()
    {
        QVERIFY(serve(false));
        s_messages.clear();
        const auto notifier = busNotifier();
        QElapsedTimer timer;
        timer.start();
        notifier->send(QStringLiteral("e"), QStringLiteral("hw-secret-title"), QStringLiteral("hw-secret-body"), 50);
        QVERIFY2(timer.elapsed() < 100, qPrintable(QStringLiteral("%1 ms").arg(timer.elapsed())));
        QTRY_COMPARE(s_messages.size(), 1);
        QCOMPARE(s_messages.first(), QStringLiteral("hearthwire-hyprland: notifications are not available"));
        notifier->send(QStringLiteral("e"), QStringLiteral("hw-secret-title"), QStringLiteral("hw-secret-body"), 90);
        QTest::qWait(300);
        QCOMPARE(s_messages.size(), 1);
        QCOMPARE(notifier->count(), 2);
        QVERIFY(m_fake.calls.isEmpty());
        QVERIFY(serve(true));
    }

    // Off mode counts and sends nothing (not even GetCapabilities).
    void offModeSendsNothing()
    {
        Notifier notifier(Notifier::Mode::Off, QDBusConnection::sessionBus());
        notifier.send(QStringLiteral("e"), QStringLiteral("t"), QStringLiteral("b"), 50);
        QCOMPARE(notifier.count(), 1);
        QVERIFY(notifier.lastCall().isEmpty());
        QTest::qWait(300);
        QVERIFY(m_fake.calls.isEmpty());
        QCOMPARE(m_fake.capabilitiesAsked, 0);
    }

    void recordModeKeepsTheLastCall()
    {
        Notifier notifier(Notifier::Mode::Record, QDBusConnection::sessionBus());
        notifier.send(QStringLiteral("usageLow"), QStringLiteral("t1"), QStringLiteral("b1"), 10);
        notifier.send(QStringLiteral("usageReset"), QStringLiteral("t2"), QStringLiteral("b2"), 90);
        QCOMPARE(notifier.count(), 2);
        const QVariantMap last = notifier.lastCall();
        QCOMPARE(last.value(QStringLiteral("eventId")).toString(), QStringLiteral("usageReset"));
        QCOMPARE(last.value(QStringLiteral("title")).toString(), QStringLiteral("t2"));
        QCOMPARE(last.value(QStringLiteral("text")).toString(), QStringLiteral("b2"));
        QCOMPARE(last.value(QStringLiteral("urgency")).toInt(), 2);
        QTest::qWait(200);
        QVERIFY(m_fake.calls.isEmpty());
    }
};

QTEST_GUILESS_MAIN(TestNotifier)
#include "tst_notifier.moc"
