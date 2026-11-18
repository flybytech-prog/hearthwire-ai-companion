// BusGuard.h itself (review-6-security INFO-6): only one address, the
// private bus's path socket, passes. No bus is used here.
#include <QTest>

#include "BusGuard.h"

class TestBusGuard : public QObject
{
    Q_OBJECT

private Q_SLOTS:
    void cleanup() { qunsetenv("DBUS_SESSION_BUS_ADDRESS"); }

    void addresses_data()
    {
        QTest::addColumn<QByteArray>("address");
        QTest::addColumn<bool>("ok");
        const QByteArray ours = "unix:path=" HW_TEST_BUS_DIR "/dbus-0123456789";
        QTest::newRow("the private bus") << ours << true;
        QTest::newRow("the private bus, with a guid") << ours + ",guid=0123456789abcdef" << true;
        QTest::newRow("empty") << QByteArray() << false;
        QTest::newRow("a second address after ;") << ours + ";unix:path=/elsewhere/bus" << false;
        QTest::newRow("a trailing ;") << ours + ";" << false;
        QTest::newRow("the host's runtime folder") << QByteArray("unix:path=/run/user/1000/bus") << false;
        QTest::newRow("an abstract socket") << QByteArray("unix:abstract=" HW_TEST_BUS_DIR "/x") << false;
        QTest::newRow("tmpdir") << QByteArray("unix:tmpdir=" HW_TEST_BUS_DIR) << false;
        QTest::newRow("runtime") << QByteArray("unix:runtime=yes") << false;
        QTest::newRow("another folder") << QByteArray("unix:path=/tmp/bus") << false;
        QTest::newRow("the bus folder's prefix only") << QByteArray("unix:path=" HW_TEST_BUS_DIR "x/bus") << false;
        QTest::newRow("tcp") << QByteArray("tcp:host=localhost,port=1") << false;
    }

    void addresses()
    {
        QFETCH(QByteArray, address);
        QFETCH(bool, ok);
        qputenv("DBUS_SESSION_BUS_ADDRESS", address);
        QCOMPARE(hwOnPrivateBus(), ok);
    }
};

QTEST_GUILESS_MAIN(TestBusGuard)
#include "tst_busguard.moc"
