// ImportTrust (task 012 R3.5): a QML import folder is kept only when every
// folder from / down to it is owned by root or us and nobody else can
// write to it (a root-owned sticky folder above it excepted).
#include <QDir>
#include <QFile>
#include <QTemporaryDir>
#include <QTest>

#include <sys/stat.h>
#include <unistd.h>

#include "ImportTrust.h"
#include "UrlGuard.h"

namespace {
// The uid root's files show as here: 0 on a normal system, the overflow
// uid under a user namespace that does not map root (a test sandbox).
uid_t rootHere()
{
    struct stat info {};
    return ::stat("/", &info) == 0 ? info.st_uid : 0;
}

HwImportOwners app()
{
    return HwImportOwners{{rootHere()}, ::getuid()};
}
} // namespace

class TestImportTrust : public QObject
{
    Q_OBJECT

private:
    QTemporaryDir m_dir;
    int m_count = 0;

    // A new folder under the test folder with exactly `mode`.
    QString folder(mode_t mode, const QString &parent = QString())
    {
        const QString path = QDir(parent.isEmpty() ? m_dir.path() : parent).filePath(QStringLiteral("f%1").arg(++m_count));
        if (::mkdir(QFile::encodeName(path).constData(), 0700) != 0 || ::chmod(QFile::encodeName(path).constData(), mode) != 0)
            return QString();
        return path;
    }

private Q_SLOTS:
    void initTestCase()
    {
        QVERIFY(m_dir.isValid());
        // Everything below stands on the test folder: it must pass itself.
        QVERIFY2(!hwTrustedFolder(m_dir.path(), app()).isEmpty(),
                 "the test's temp folder is not trusted (set TMPDIR to a folder of yours under a root-owned path)");
    }

    void modes_data()
    {
        QTest::addColumn<int>("mode");
        QTest::addColumn<bool>("kept");
        QTest::newRow("0755 kept") << 0755 << true;
        QTest::newRow("0700 kept") << 0700 << true;
        QTest::newRow("0775 dropped (group-writable)") << 0775 << false;
        QTest::newRow("0757 dropped (other-writable)") << 0757 << false;
        QTest::newRow("0777 dropped") << 0777 << false;
        QTest::newRow("1777 dropped (sticky is no excuse for the folder itself)") << 01777 << false;
    }

    void modes()
    {
        QFETCH(int, mode);
        QFETCH(bool, kept);
        const QString path = folder(mode_t(mode));
        QVERIFY(!path.isEmpty());
        QCOMPARE(!hwTrustedFolder(path, app()).isEmpty(), kept);
    }

    // The walk covers every folder on the way, not only the last one.
    void aWritableParentDrops()
    {
        const QString parent = folder(0775);
        const QString child = folder(0755, parent);
        QVERIFY(!child.isEmpty());
        QVERIFY(hwTrustedFolder(child, app()).isEmpty());
        const QString other = folder(0757);
        const QString deep = folder(0755, folder(0755, other));
        QVERIFY(!deep.isEmpty());
        QVERIFY(hwTrustedFolder(deep, app()).isEmpty());
    }

    // A root-owned sticky folder (as /tmp) may be above a kept folder; one
    // of ours that others can write to may not. Here one of our own uids
    // counts as root, since a test can't make a folder root's.
    void aStickyRootAncestorIsKept()
    {
        const QString sticky = folder(01777);
        const QString child = folder(0755, sticky);
        QVERIFY(!child.isEmpty());
        const uid_t self = ::getuid();
        const HwImportOwners selfIsRoot{{rootHere(), self}, self + 4242};
        QVERIFY(!hwTrustedFolder(child, selfIsRoot).isEmpty());
        // ...but never the sticky folder itself.
        QVERIFY(hwTrustedFolder(sticky, selfIsRoot).isEmpty());
        // Sticky, but ours (not root's): dropped.
        QVERIFY(hwTrustedFolder(child, app()).isEmpty());
        // Not sticky, root's and other-writable: dropped.
        const QString open = folder(0777);
        const QString below = folder(0755, open);
        QVERIFY(!below.isEmpty());
        QVERIFY(hwTrustedFolder(below, selfIsRoot).isEmpty());
    }

    void aMissingFolderDrops()
    {
        QVERIFY(hwTrustedFolder(m_dir.filePath(QStringLiteral("no-such-folder")), app()).isEmpty());
        QVERIFY(hwTrustedFolder(QString(), app()).isEmpty());
        QVERIFY(hwTrustedFolder(QStringLiteral("relative/path"), app()).isEmpty());
        // A file is not a folder.
        QFile file(m_dir.filePath(QStringLiteral("a-file")));
        QVERIFY(file.open(QIODevice::WriteOnly));
        file.close();
        QVERIFY(hwTrustedFolder(file.fileName(), app()).isEmpty());
    }

    // A link is followed to its real place, and that place is checked.
    void aLinkIsCheckedWhereItLeads()
    {
        const QString good = folder(0755);
        const QString bad = folder(0757);
        const QString toGood = m_dir.filePath(QStringLiteral("to-good"));
        const QString toBad = m_dir.filePath(QStringLiteral("to-bad"));
        QVERIFY(QFile::link(good, toGood));
        QVERIFY(QFile::link(bad, toBad));
        QCOMPARE(hwTrustedFolder(toGood, app()), QFileInfo(good).canonicalFilePath());
        QVERIFY(hwTrustedFolder(toBad, app()).isEmpty());
        // A link inside a good folder, to a folder below a bad one.
        const QString deep = folder(0755, bad);
        const QString via = good + QStringLiteral("/via");
        QVERIFY(QFile::link(deep, via));
        QVERIFY(hwTrustedFolder(via, app()).isEmpty());
    }

    void qtsOwnFolderIsKept()
    {
        if (!QFileInfo(QStringLiteral("/usr/lib/qt6/qml")).isDir())
            QSKIP("no /usr/lib/qt6/qml here");
        QCOMPARE(hwTrustedFolder(QStringLiteral("/usr/lib/qt6/qml"), app()),
                 QFileInfo(QStringLiteral("/usr/lib/qt6/qml")).canonicalFilePath());
    }

    void anotherOwnerDrops()
    {
        const QString path = folder(0755);
        QVERIFY(!path.isEmpty());
        // The same folder, seen by another session user: not theirs, not root's.
        QVERIFY(hwTrustedFolder(path, HwImportOwners{{rootHere()}, ::getuid() + 4242}).isEmpty());
        QVERIFY(!hwTrustedFolder(path, app()).isEmpty());
    }

    void theListKeepsQrcAndDropsTheRest()
    {
        const QString good = folder(0755);
        const QString bad = folder(0775);
        int dropped = -1;
        const QStringList kept = hwTrustedImportPaths(
            {QStringLiteral("qrc:/qt/qml"), QStringLiteral(":/x"), good, bad, QUrl::fromLocalFile(good).toString(),
             m_dir.filePath(QStringLiteral("missing"))},
            app(), &dropped);
        QCOMPARE(dropped, 2);
        const QString canonical = QFileInfo(good).canonicalFilePath();
        QCOMPARE(kept, QStringList({QStringLiteral("qrc:/qt/qml"), QStringLiteral(":/x"), canonical, canonical}));
    }

    // Integration: a UrlGuard made from the filtered list refuses a QML
    // file in a dropped folder and allows one in a kept folder.
    void theGuardRefusesADroppedFolder()
    {
        const QString good = folder(0755);
        const QString bad = folder(0757);
        for (const QString &dir : {good, bad}) {
            QFile qml(dir + QStringLiteral("/Probe.qml"));
            QVERIFY(qml.open(QIODevice::WriteOnly));
            qml.write("import QtQml\nQtObject {}\n");
        }
        const QStringList filtered = hwTrustedImportPaths({QStringLiteral("qrc:/qt/qml"), good, bad}, app());
        const UrlGuard guard(filtered);
        QVERIFY(guard.allowed(QUrl::fromLocalFile(good + QStringLiteral("/Probe.qml"))));
        QVERIFY(!guard.allowed(QUrl::fromLocalFile(bad + QStringLiteral("/Probe.qml"))));
        // The unfiltered list would have let it through (the proof).
        const UrlGuard unfiltered({QStringLiteral("qrc:/qt/qml"), good, bad});
        QVERIFY(unfiltered.allowed(QUrl::fromLocalFile(bad + QStringLiteral("/Probe.qml"))));
    }
};

QTEST_GUILESS_MAIN(TestImportTrust)
#include "tst_importtrust.moc"
