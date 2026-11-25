// ConfigStore: settings.json in the format the helper reads (011
// core/appconfig.py), folder exactly 0700 and file exactly 0600 whatever the
// umask, written atomically; the file is untrusted on reading.
#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QQmlComponent>
#include <QQmlContext>
#include <QQmlEngine>
#include <QQmlExpression>
#include <QQmlPropertyMap>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>

#include <memory>
#include <sys/stat.h>
#include <unistd.h>

#include "ConfigStore.h"

namespace {
int modeOf(const QString &path)
{
    struct stat info {};
    if (::lstat(QFile::encodeName(path).constData(), &info) != 0)
        return -1;
    return int(info.st_mode & 07777);
}

ino_t inodeOf(const QString &path)
{
    struct stat info {};
    ::lstat(QFile::encodeName(path).constData(), &info);
    return info.st_ino;
}

QByteArray readAll(const QString &path)
{
    QFile file(path);
    return file.open(QIODevice::ReadOnly) ? file.readAll() : QByteArray();
}

// Writes a file of ours; its folder is 0700, as the app makes it.
void writeFile(const QString &path, const QByteArray &data, int mode = 0600)
{
    QDir().mkpath(QFileInfo(path).absolutePath());
    QCOMPARE(::chmod(QFile::encodeName(QFileInfo(path).absolutePath()).constData(), 0700), 0);
    QFile file(path);
    QVERIFY(file.open(QIODevice::WriteOnly | QIODevice::Truncate));
    file.write(data);
    file.close();
    QCOMPARE(::chmod(QFile::encodeName(path).constData(), mode_t(mode)), 0);
}

QByteArray document(const QJsonObject &settings)
{
    QJsonObject root;
    root.insert("format", "hearthwire-app-settings");
    root.insert("version", 1);
    root.insert("settings", settings);
    return QJsonDocument(root).toJson();
}
}

class TestConfigStore : public QObject
{
    Q_OBJECT

    QTemporaryDir m_dir;
    QString m_folder;
    QString m_file;

    // A folder per data row, still named hearthwire-hyprland (the helper
    // reads <base>/hearthwire-hyprland/settings.json).
    void caseFolder(const QString &row)
    {
        m_folder = QDir(m_dir.path()).filePath(QString::fromLatin1(QTest::currentTestFunction()) + "-" + row
                                               + "/hearthwire-hyprland");
        m_file = m_folder + "/settings.json";
    }

    void load(ConfigStore &store)
    {
        QVERIFY(store.loadSchema(QStringLiteral(HW_MAIN_XML)));
    }

    // Runs `script` with the repo's helper sources (stdlib python3 -I, no
    // inherited environment); its stdout, trimmed.
    QString runHelperPython(const QString &script, const QString &configBase)
    {
        QProcess python;
        python.setProcessChannelMode(QProcess::ForwardedErrorChannel);
        QProcessEnvironment env;
        env.insert("PATH", "/usr/bin:/bin");
        env.insert("HOME", m_dir.path());
        env.insert("LANG", "C.UTF-8");
        python.setProcessEnvironment(env);
        python.start(QStringLiteral(HW_TEST_PYTHON), {"-I", "-B", "-c", script, QStringLiteral(HW_REPO_SRC), configBase});
        if (!python.waitForFinished(30000) || python.exitCode() != 0)
            return QStringLiteral("<python failed>");
        return QString::fromUtf8(python.readAllStandardOutput()).trimmed();
    }

private Q_SLOTS:
    void init()
    {
        QVERIFY(m_dir.isValid());
        m_folder = QDir(m_dir.path()).filePath(QString::fromLatin1(QTest::currentTestFunction()) + "/hearthwire-hyprland");
        m_file = m_folder + "/settings.json";
        ::umask(022);
    }

    void defaultFileFollowsXdgLikeTheHelper()
    {
        const QByteArray oldXdg = qgetenv("XDG_CONFIG_HOME");
        const QByteArray oldHome = qgetenv("HOME");
        qputenv("HOME", "/nonexistent-home");
        qputenv("XDG_CONFIG_HOME", "/cfg");
        QCOMPARE(ConfigStore::defaultFile(), QStringLiteral("/cfg/hearthwire-hyprland/settings.json"));
        qputenv("XDG_CONFIG_HOME", "relative/cfg");
        QCOMPARE(ConfigStore::defaultFile(), QStringLiteral("/nonexistent-home/.config/hearthwire-hyprland/settings.json"));
        qunsetenv("XDG_CONFIG_HOME");
        QCOMPARE(ConfigStore::defaultFile(), QStringLiteral("/nonexistent-home/.config/hearthwire-hyprland/settings.json"));
        qputenv("HOME", oldHome);
        if (!oldXdg.isNull())
            qputenv("XDG_CONFIG_HOME", oldXdg);
    }

    void schemaKeysAndDefaults()
    {
        ConfigStore store;
        load(store);
        QVERIFY(store.keys().contains("refreshIntervalDefault"));
        QCOMPARE(store.value("refreshInterval").toInt(), 300);
        QCOMPARE(store.value("refreshIntervalDefault").toInt(), 300);
        QCOMPARE(store.keys().size() % 2, 0);
    }

    void modesAreExactWhateverTheUmask_data()
    {
        QTest::addColumn<int>("mask");
        QTest::newRow("umask 000") << 0;
        QTest::newRow("umask 022") << 022;
        QTest::newRow("umask 077") << 077;
        QTest::newRow("umask 277") << 0277;
    }

    void modesAreExactWhateverTheUmask()
    {
        QFETCH(int, mask);
        m_folder += QString::number(mask);
        m_file = m_folder + "/settings.json";
        ConfigStore store;
        load(store);
        QVERIFY(store.open(m_file));
        QCOMPARE(store.status(), ConfigStore::Status::Missing);
        const mode_t old = ::umask(mode_t(mask));
        const bool saved = store.save();
        ::umask(old);
        QVERIFY(saved);
        QCOMPARE(modeOf(m_folder), 0700);
        QCOMPARE(modeOf(m_file), 0600);
    }

    // Security M1: a folder or file more open than the helper accepts
    // (core/appconfig.py _too_open) is unreadable: defaults, and nothing is
    // saved, tightened or replaced, so planted values never become ours.
    void tooOpenModesAreUnreadable_data()
    {
        QTest::addColumn<int>("folderMode");
        QTest::addColumn<int>("fileMode");
        QTest::addColumn<bool>("refused");
        QTest::newRow("0700/0600") << 0700 << 0600 << false;
        QTest::newRow("0500 folder") << 0500 << 0600 << false;
        QTest::newRow("0400 file") << 0700 << 0400 << false;
        QTest::newRow("setgid folder") << 02700 << 0600 << false;
        QTest::newRow("sticky folder") << 01700 << 0600 << false;
        QTest::newRow("setuid file") << 0700 << 04600 << false;
        QTest::newRow("folder 0755") << 0755 << 0600 << true;
        QTest::newRow("folder 0750") << 0750 << 0600 << true;
        QTest::newRow("folder 0710") << 0710 << 0600 << true;
        QTest::newRow("folder 0701") << 0701 << 0600 << true;
        QTest::newRow("folder 0707") << 0707 << 0600 << true;
        QTest::newRow("folder 0777") << 0777 << 0600 << true;
        QTest::newRow("setgid folder 02750") << 02750 << 0600 << true;
        QTest::newRow("file 0666 (planted)") << 0700 << 0666 << true;
        QTest::newRow("file 0644") << 0700 << 0644 << true;
        QTest::newRow("file 0640") << 0700 << 0640 << true;
        QTest::newRow("file 0620") << 0700 << 0620 << true;
        QTest::newRow("file 0604") << 0700 << 0604 << true;
        QTest::newRow("file 0602") << 0700 << 0602 << true;
        QTest::newRow("file 0601") << 0700 << 0601 << true;
        QTest::newRow("file 0610") << 0700 << 0610 << true;
        QTest::newRow("file 0700 (owner x)") << 0700 << 0700 << true;
        QTest::newRow("setuid file 04644") << 0700 << 04644 << true;
    }

    void tooOpenModesAreUnreadable()
    {
        QFETCH(int, folderMode);
        QFETCH(int, fileMode);
        QFETCH(bool, refused);
        caseFolder(QString::number(folderMode, 8) + "-" + QString::number(fileMode, 8));
        QJsonObject planted;
        planted.insert("refreshInterval", 60);
        planted.insert("chatUserSites", "[{\"id\":\"planted\"}]");
        const QByteArray content = document(planted);
        writeFile(m_file, content, fileMode);
        QCOMPARE(modeOf(m_file), fileMode);
        QCOMPARE(::chmod(QFile::encodeName(m_folder).constData(), mode_t(folderMode)), 0);
        QCOMPARE(modeOf(m_folder), folderMode);
        ConfigStore store;
        load(store);
        if (!refused) {
            QVERIFY(store.open(m_file));
            QCOMPARE(store.status(), ConfigStore::Status::Ok);
            QCOMPARE(store.value("refreshInterval").toInt(), 60);
            // Only a folder that passed is set to exactly 0700 on a save.
            QVERIFY(store.save());
            QCOMPARE(modeOf(m_folder), 0700);
            QCOMPARE(modeOf(m_file), 0600);
            return;
        }
        QVERIFY(!store.open(m_file));
        QCOMPARE(store.status(), ConfigStore::Status::Unreadable);
        QCOMPARE(store.value("refreshInterval").toInt(), 300);
        QCOMPARE(store.value("chatUserSites"), store.defaultValue("chatUserSites"));
        store.insert("refreshInterval", 120);
        QVERIFY(!store.save());
        QCOMPARE(modeOf(m_folder), folderMode);
        QCOMPARE(modeOf(m_file), fileMode);
        QCOMPARE(readAll(m_file), content);
        ::chmod(QFile::encodeName(m_folder).constData(), 0700);
    }

    // The same modes as the helper: open() refuses exactly what
    // appconfig.applied_settings calls settings-unreadable.
    void tooOpenMatchesTheHelper_data()
    {
        tooOpenModesAreUnreadable_data();
    }

    void tooOpenMatchesTheHelper()
    {
        QFETCH(int, folderMode);
        QFETCH(int, fileMode);
        QFETCH(bool, refused);
        caseFolder(QString::number(folderMode, 8) + "-" + QString::number(fileMode, 8));
        writeFile(m_file, document({}), fileMode);
        QCOMPARE(::chmod(QFile::encodeName(m_folder).constData(), mode_t(folderMode)), 0);
        ConfigStore store;
        load(store);
        const bool appRefuses = !store.open(m_file) && store.status() == ConfigStore::Status::Unreadable;
        const QString script = QStringLiteral(
            "import sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from hearthwire.core import appconfig\n"
            "from hearthwire.core.webdata import HelperError\n"
            "try:\n"
            "    appconfig.applied_settings(['refreshInterval'], sys.argv[2])\n"
            "    print('ok')\n"
            "except HelperError as error:\n"
            "    print(error.code)\n");
        const QString answer = runHelperPython(script, QFileInfo(m_folder).absolutePath());
        ::chmod(QFile::encodeName(m_folder).constData(), 0700);
        QCOMPARE(answer, refused ? QStringLiteral("settings-unreadable") : QStringLiteral("ok"));
        QCOMPARE(appRefuses, refused);
    }

    // A file with a second name (hard link) is read like any other, as by
    // the helper (round-2 decision): it is ours in our 0700 folder, and
    // hard-link backups (rsync --link-dest, rsnapshot, cp -al) give it a
    // second name. A save renames a new file over settings.json, so the
    // other name keeps the old content and never sees a later write.
    void aHardLinkedFileIsReadAndReplacedByRename()
    {
        const QByteArray content = document({{"refreshInterval", 60}});
        writeFile(m_file, content);
        const QString other = QDir(m_dir.path()).filePath("second-name.json");
        QCOMPARE(::link(QFile::encodeName(m_file).constData(), QFile::encodeName(other).constData()), 0);
        ConfigStore store;
        load(store);
        QVERIFY(store.open(m_file));
        QCOMPARE(store.status(), ConfigStore::Status::Ok);
        QCOMPARE(store.value("refreshInterval").toInt(), 60);
        store.insert("refreshInterval", 120);
        QVERIFY(store.save());
        QCOMPARE(readAll(other), content);
        QVERIFY(inodeOf(m_file) != inodeOf(other));
        QCOMPARE(QJsonDocument::fromJson(readAll(m_file)).object().value("settings").toObject().value("refreshInterval").toInt(), 120);
    }

    // The config base ($XDG_CONFIG_HOME or ~/.config) must be ours, as the
    // helper's open_base wants; a link to a folder of ours is fine.
    void aConfigBaseOfSomeoneElseIsUnreadable()
    {
        struct stat info {};
        QCOMPARE(::stat("/usr", &info), 0);
        if (info.st_uid == ::geteuid())
            QSKIP("/usr is ours here");
        ConfigStore store;
        load(store);
        const QString file = QStringLiteral("/usr/hearthwire-hyprland/settings.json");
        QVERIFY(!store.open(file));
        QCOMPARE(store.status(), ConfigStore::Status::Unreadable);
        QVERIFY(!store.save());
        QVERIFY(!QFile::exists(file));
    }

    void aLinkedConfigBaseOfOursIsFollowed()
    {
        const QString real = QDir(m_dir.path()).filePath("real-base");
        writeFile(real + "/hearthwire-hyprland/settings.json", document({{"refreshInterval", 60}}));
        const QString base = QDir(m_dir.path()).filePath("linked-base");
        QVERIFY(QFile::link(real, base));
        ConfigStore store;
        load(store);
        QVERIFY(store.open(base + "/hearthwire-hyprland/settings.json"));
        QCOMPARE(store.status(), ConfigStore::Status::Ok);
        QCOMPARE(store.value("refreshInterval").toInt(), 60);
        QVERIFY(store.save());
        QCOMPARE(modeOf(real + "/hearthwire-hyprland/settings.json"), 0600);
    }

    // Missing at open, then made too open before the first save: never
    // tightened or written into.
    void aFolderMadeOpenBeforeTheSaveIsRefused()
    {
        ConfigStore store;
        load(store);
        QVERIFY(store.open(m_file));
        QCOMPARE(store.status(), ConfigStore::Status::Missing);
        QVERIFY(QDir().mkpath(m_folder));
        QCOMPARE(::chmod(QFile::encodeName(m_folder).constData(), 0755), 0);
        QVERIFY(!store.save());
        QCOMPARE(modeOf(m_folder), 0755);
        QVERIFY(!QFile::exists(m_file));
    }

    // Passed at open, then opened up before a save: refused too.
    void aFolderOpenedUpAfterOpenIsRefused()
    {
        writeFile(m_file, document({}));
        QCOMPARE(::chmod(QFile::encodeName(m_folder).constData(), 0700), 0);
        ConfigStore store;
        load(store);
        QVERIFY(store.open(m_file));
        QCOMPARE(::chmod(QFile::encodeName(m_folder).constData(), 0750), 0);
        store.insert("refreshInterval", 120);
        QVERIFY(!store.save());
        QCOMPARE(modeOf(m_folder), 0750);
        QCOMPARE(readAll(m_file), document({}));
    }

    void writesTheHelpersFormat()
    {
        ConfigStore store;
        load(store);
        QVERIFY(store.open(m_file));
        store.insert("refreshInterval", 60);
        QVERIFY(store.save());
        const QJsonObject root = QJsonDocument::fromJson(readAll(m_file)).object();
        QCOMPARE(QStringList(root.keys()), (QStringList{"app", "format", "settings", "version"}));
        QCOMPARE(root.value("format").toString(), QStringLiteral("hearthwire-app-settings"));
        QCOMPARE(root.value("version").toVariant().typeId(), int(QMetaType::LongLong));
        QCOMPARE(root.value("version").toInt(), 1);
        const QJsonObject app = root.value("app").toObject();
        QCOMPARE(QStringList(app.keys()), (QStringList{"agentsPanel", "background", "tray"}));
        const QJsonObject settings = root.value("settings").toObject();
        QCOMPARE(settings.value("refreshInterval").toVariant().typeId(), int(QMetaType::LongLong));
        QCOMPARE(settings.value("refreshInterval").toInt(), 60);
        int keys = 0;
        for (const QString &key : store.keys()) {
            if (key.endsWith("Default"))
                continue;
            ++keys;
            QVERIFY2(settings.contains(key), qPrintable(key));
        }
        QCOMPARE(settings.size(), keys);
    }

    void roundTrip()
    {
        {
            ConfigStore store;
            load(store);
            QVERIFY(store.open(m_file));
            store.insert("refreshInterval", 900);
            store.insert("usageMode", QStringLiteral("used"));
            store.insert("backupAutoExport", true);
            QVERIFY(store.save());
        }
        ConfigStore again;
        load(again);
        QVERIFY(again.open(m_file));
        QCOMPARE(again.status(), ConfigStore::Status::Ok);
        QCOMPARE(again.value("refreshInterval"), QVariant(900));
        QCOMPARE(again.value("usageMode"), QVariant(QStringLiteral("used")));
        QCOMPARE(again.value("backupAutoExport"), QVariant(true));
        QCOMPARE(again.dropped(), 0);
    }

    void wrongTypesKeepTheDefault()
    {
        QJsonObject settings;
        settings.insert("refreshInterval", "60");      // text in an Int
        settings.insert("usageMode", 5);               // number in a String
        settings.insert("backupAutoExport", 1);        // number in a Bool
        settings.insert("unknownKey", true);           // not in main.xml
        QJsonObject root = QJsonDocument::fromJson(document(settings)).object();
        root.insert("app", QJsonObject{{"background", "yes"}, {"tray", true}});
        writeFile(m_file, QJsonDocument(root).toJson());
        ConfigStore store;
        load(store);
        QVERIFY(store.open(m_file));
        QCOMPARE(store.status(), ConfigStore::Status::Ok);
        QCOMPARE(store.value("refreshInterval").toInt(), 300);
        QCOMPARE(store.value("usageMode"), store.defaultValue("usageMode"));
        QCOMPARE(store.value("backupAutoExport"), store.defaultValue("backupAutoExport"));
        QCOMPARE(store.dropped(), 4);
        QVERIFY(!store.contains("unknownKey"));
        QVERIFY(store.appFlag("tray"));
        QVERIFY(!store.appFlag("background"));
        QVERIFY(store.save());
        const QJsonObject saved = QJsonDocument::fromJson(readAll(m_file)).object();
        QVERIFY(!saved.value("settings").toObject().contains("unknownKey"));
        QCOMPARE(saved.value("app").toObject().value("tray").toBool(), true);
    }

    void intsMustBeWhole32BitIntegers_data()
    {
        QTest::addColumn<QByteArray>("number");
        QTest::newRow("fraction") << QByteArray("1.5");
        // Not covered: 60.0 and 6e1 read as 60 here (Qt's JSON keeps no
        // integer/float distinction for whole numbers); the helper's backup
        // drops them. The app itself always writes integers.
        QTest::newRow("too big") << QByteArray("2147483648");
        QTest::newRow("too small") << QByteArray("-2147483649");
    }

    void intsMustBeWhole32BitIntegers()
    {
        QFETCH(QByteArray, number);
        const QByteArray text = R"({"format":"hearthwire-app-settings","version":1,"settings":{"refreshInterval":)" + number + "}}";
        writeFile(m_file, text);
        ConfigStore store;
        load(store);
        QVERIFY(store.open(m_file));
        QCOMPARE(store.value("refreshInterval").toInt(), 300);
        QCOMPARE(store.dropped(), 1);
    }

    void damagedFilesAreKeptAside_data()
    {
        QTest::addColumn<QByteArray>("content");
        QTest::newRow("not JSON") << QByteArray("{");
        QTest::newRow("flat, no format") << QByteArray(R"({"refreshInterval": 60})");
        QTest::newRow("other format") << QByteArray(R"({"format":"x","version":1,"settings":{}})");
        QTest::newRow("other version") << QByteArray(R"({"format":"hearthwire-app-settings","version":2,"settings":{}})");
        QTest::newRow("version text") << QByteArray(R"({"format":"hearthwire-app-settings","version":"1","settings":{}})");
        QTest::newRow("settings not an object") << QByteArray(R"({"format":"hearthwire-app-settings","version":1,"settings":[]})");
        QTest::newRow("extra key") << QByteArray(R"({"format":"hearthwire-app-settings","version":1,"settings":{},"x":1})");
        QTest::newRow("app not an object") << QByteArray(R"({"format":"hearthwire-app-settings","version":1,"settings":{},"app":1})");
        QTest::newRow("array") << QByteArray("[]");
    }

    void damagedFilesAreKeptAside()
    {
        QFETCH(QByteArray, content);
        writeFile(m_file, content);
        ConfigStore store;
        load(store);
        QVERIFY(!store.open(m_file));
        QCOMPARE(store.status(), ConfigStore::Status::Damaged);
        QCOMPARE(store.value("refreshInterval").toInt(), 300);
        QCOMPARE(readAll(m_file), content);  // untouched until a save
        QVERIFY(store.save());
        QCOMPARE(readAll(m_file + ".damaged"), content);
        QCOMPARE(QJsonDocument::fromJson(readAll(m_file)).object().value("format").toString(),
                 QStringLiteral("hearthwire-app-settings"));
        QCOMPARE(modeOf(m_file), 0600);
    }

    void aLinkedFileIsNeverReadOrReplaced()
    {
        const QString target = QDir(m_dir.path()).filePath("elsewhere.json");
        writeFile(target, document({{"refreshInterval", 60}}));
        QVERIFY(QDir().mkpath(m_folder));
        QVERIFY(QFile::link(target, m_file));
        ConfigStore store;
        load(store);
        QVERIFY(!store.open(m_file));
        QCOMPARE(store.status(), ConfigStore::Status::Unreadable);
        QCOMPARE(store.value("refreshInterval").toInt(), 300);
        QVERIFY(!store.save());
        QVERIFY(QFileInfo(m_file).isSymLink());
        QCOMPARE(QJsonDocument::fromJson(readAll(target)).object().value("settings").toObject().value("refreshInterval").toInt(), 60);
    }

    void aLinkedFolderIsRefused()
    {
        const QString real = QDir(m_dir.path()).filePath("real-folder");
        QVERIFY(QDir().mkpath(real));
        writeFile(real + "/settings.json", document({}));
        QVERIFY(QDir().mkpath(QFileInfo(m_folder).absolutePath()));
        QVERIFY(QFile::link(real, m_folder));
        ConfigStore store;
        load(store);
        QVERIFY(!store.open(m_file));
        QCOMPARE(store.status(), ConfigStore::Status::Unreadable);
        QVERIFY(!store.save());
    }

    void aLinkedFolderIsRefusedOnSaveToo()
    {
        // Missing at open, then swapped for a link before the save.
        ConfigStore store;
        load(store);
        QVERIFY(store.open(m_file));
        const QString real = QDir(m_dir.path()).filePath("real-folder-2");
        QVERIFY(QDir().mkpath(real));
        QVERIFY(QDir().mkpath(QFileInfo(m_folder).absolutePath()));
        QVERIFY(QFile::link(real, m_folder));
        QVERIFY(!store.save());
        QVERIFY(!QFile::exists(real + "/settings.json"));
    }

    void notARegularFileIsRefused()
    {
        QVERIFY(QDir().mkpath(m_file));  // a folder named settings.json
        ConfigStore store;
        load(store);
        QVERIFY(!store.open(m_file));
        QCOMPARE(store.status(), ConfigStore::Status::Unreadable);
        QVERIFY(!store.save());
    }

    void tooLargeIsRefused()
    {
        QByteArray big = document({});
        big.append(QByteArray(ConfigStore::MaxFileBytes, ' '));
        writeFile(m_file, big);
        ConfigStore store;
        load(store);
        QVERIFY(!store.open(m_file));
        QCOMPARE(store.status(), ConfigStore::Status::Unreadable);
        QVERIFY(!store.save());
        QCOMPARE(QFileInfo(m_file).size(), big.size());
    }

    void tooLargeIsNeverWritten()
    {
        ConfigStore store;
        load(store);
        QVERIFY(store.open(m_file));
        store.insert("chatSiteZoom", QString(ConfigStore::MaxFileBytes, QLatin1Char('x')));
        QVERIFY(!store.save());
        QVERIFY(!QFile::exists(m_file));
    }

    void saveReplacesTheFileAtomically()
    {
        ConfigStore store;
        load(store);
        QVERIFY(store.open(m_file));
        QVERIFY(store.save());
        // A hard link to the old file keeps the old content: the save made a
        // new file and renamed it over, it never wrote into the old one.
        const QString old = QDir(m_dir.path()).filePath("old-link.json");
        QVERIFY(::link(QFile::encodeName(m_file).constData(), QFile::encodeName(old).constData()) == 0);
        const QByteArray before = readAll(old);
        const ino_t inode = inodeOf(m_file);
        store.insert("refreshInterval", 120);
        QVERIFY(store.save());
        QVERIFY(inodeOf(m_file) != inode);
        QCOMPARE(readAll(old), before);
        // No temp file is left behind.
        QCOMPARE(QDir(m_folder).entryList(QDir::Files | QDir::Hidden | QDir::System), QStringList{"settings.json"});
    }

    void aQmlWriteIsStoredAndReemitsEveryKeyOnce()
    {
        ConfigStore store;
        load(store);
        QVERIFY(store.open(m_file));
        QSignalSpy spy(&store, &QQmlPropertyMap::valueChanged);
        QSignalSpy reemits(&store, &ConfigStore::reemitted);
        QQmlEngine engine;
        engine.rootContext()->setContextProperty("store", &store);
        // An Apply: writes (a text for an Int too, as a TextField gives), then writeConfig().
        QQmlExpression apply(engine.rootContext(), nullptr,
                             "store.refreshInterval = \"60\"; store.usageMode = \"used\"; store.writeConfig(); 0");
        apply.evaluate();
        QVERIFY(!apply.hasError());
        QTRY_COMPARE(reemits.count(), 1);
        QTest::qWait(50);
        QCOMPARE(reemits.count(), 1);
        int real = 0;
        for (const QString &key : store.keys())
            real += key.endsWith("Default") ? 0 : 1;
        // The two real changes, then one pass over every key.
        QCOMPARE(spy.count(), 2 + real);
        QCOMPARE(spy.last().at(0).toString(), QStringLiteral("backupAutoExport"));
        QCOMPARE(store.value("refreshInterval"), QVariant(60));
        const QJsonObject settings = QJsonDocument::fromJson(readAll(m_file)).object().value("settings").toObject();
        QCOMPARE(settings.value("refreshInterval").toVariant(), QVariant(qlonglong(60)));
        QCOMPARE(settings.value("usageMode").toString(), QStringLiteral("used"));
    }

    void defaultEntriesCannotBeWritten()
    {
        ConfigStore store;
        load(store);
        QVERIFY(store.open(m_file));
        QQmlEngine engine;
        engine.rootContext()->setContextProperty("store", &store);
        QQmlExpression write(engine.rootContext(), nullptr, "store.refreshIntervalDefault = 5; store.refreshIntervalDefault");
        QCOMPARE(write.evaluate().toInt(), 300);
    }

    // A schema with a StringList key (the widget's chatHttpWarnedSites), apart
    // from main.xml so this holds whatever main.xml carries.
    void loadListSchema(ConfigStore &store)
    {
        const QString path = m_dir.filePath(QStringLiteral("list-main.xml"));
        QFile xml(path);
        QVERIFY(xml.open(QIODevice::WriteOnly | QIODevice::Truncate));
        xml.write("<kcfg><group name=\"General\">"
                  "<entry name=\"refreshInterval\" type=\"Int\"><default>300</default></entry>"
                  "<entry name=\"chatHttpWarnedSites\" type=\"StringList\"><default></default></entry>"
                  "<entry name=\"listWithDefault\" type=\"StringList\"><default>a,b</default></entry>"
                  "</group></kcfg>");
        xml.close();
        QVERIFY(store.loadSchema(path));
    }

    void stringListKeyRoundTrips()
    {
        const QStringList sites{QStringLiteral("http://example.org:80"), QStringLiteral("http://[::1]:8080")};
        {
            ConfigStore store;
            loadListSchema(store);
            QCOMPARE(store.value("chatHttpWarnedSites"), QVariant(QStringList()));
            QCOMPARE(store.value("listWithDefault"), QVariant(QStringList{"a", "b"}));
            QVERIFY(store.open(m_file));
            // From QML: an array of strings, then the Apply.
            QQmlEngine engine;
            engine.rootContext()->setContextProperty("store", &store);
            QQmlExpression write(engine.rootContext(), nullptr,
                                 "store.chatHttpWarnedSites = [\"http://example.org:80\", \"http://[::1]:8080\"]; "
                                 "store.writeConfig(); store.chatHttpWarnedSites.length");
            QCOMPARE(write.evaluate().toInt(), 2);
            QCOMPARE(store.value("chatHttpWarnedSites").toStringList(), sites);
        }
        const QJsonObject saved = QJsonDocument::fromJson(readAll(m_file)).object().value("settings").toObject();
        QCOMPARE(saved.value("chatHttpWarnedSites").toArray().size(), 2);
        QCOMPARE(modeOf(m_file), 0600);
        ConfigStore again;
        loadListSchema(again);
        QVERIFY(again.open(m_file));
        QCOMPARE(again.dropped(), 0);
        QCOMPARE(again.value("chatHttpWarnedSites").toStringList(), sites);
    }

    void stringListKeyIsCheckedOnReadAndWrite_data()
    {
        QTest::addColumn<QJsonValue>("stored");
        QJsonArray tooMany;
        for (int i = 0; i <= ConfigStore::MaxListEntries; ++i)
            tooMany.append(QStringLiteral("http://h%1:80").arg(i));
        QTest::newRow("text") << QJsonValue(QStringLiteral("http://a:80"));
        QTest::newRow("number in the list") << QJsonValue(QJsonArray{QStringLiteral("http://a:80"), 5});
        QTest::newRow("object in the list") << QJsonValue(QJsonArray{QJsonObject{}});
        QTest::newRow("too many") << QJsonValue(tooMany);
        QTest::newRow("a long entry")
            << QJsonValue(QJsonArray{QString(ConfigStore::MaxListEntryChars + 1, QLatin1Char('x'))});
    }

    void stringListKeyIsCheckedOnReadAndWrite()
    {
        QFETCH(QJsonValue, stored);
        writeFile(m_file, document(QJsonObject{{"chatHttpWarnedSites", stored}}));
        ConfigStore store;
        loadListSchema(store);
        QVERIFY(store.open(m_file));
        QCOMPARE(store.dropped(), 1);
        QCOMPARE(store.value("chatHttpWarnedSites"), QVariant(QStringList()));
        // The same shapes from QML are refused: the value stays.
        QQmlEngine engine;
        engine.rootContext()->setContextProperty("store", &store);
        QQmlExpression bad(engine.rootContext(), nullptr,
                           "store.chatHttpWarnedSites = [\"http://a:80\", 5]; "
                           "store.chatHttpWarnedSites = \"http://a:80\"; "
                           "store.chatHttpWarnedSites.length");
        QCOMPARE(bad.evaluate().toInt(), 0);
    }

    // Task 013 F2: the http acknowledgement persists. These are main.qml's two
    // lines (chatHttpWarnedSites, chatHttpSiteAcknowledged) on the real
    // main.xml schema and the real synced ChatSites.js; the fixture check in
    // SpikeChecks.qml runs the real main.qml, FullRepresentation and ChatView.
    QString warnedSitesQml() const
    {
        const QString ui = QFileInfo(QStringLiteral(HW_MAIN_XML)).absolutePath();
        return QStringLiteral(
                   "import QtQml\n"
                   "import \"file://%1/ChatSites.js\" as ChatSites\n"
                   "QtObject {\n"
                   "    readonly property var warned: ChatSites.cleanWarnedSites(Plasmoid.configuration.chatHttpWarnedSites)\n"
                   "    function acknowledged(origin) {\n"
                   "        if (typeof origin !== \"string\" || ChatSites.httpWarnOrigin(origin) !== origin)\n"
                   "            return\n"
                   "        Plasmoid.configuration.chatHttpWarnedSites = ChatSites.addWarnedSite(warned, origin)\n"
                   "    }\n"
                   "}\n")
            .arg(ui);
    }

    // Returns the view's warned list; `ack` runs first, when not empty.
    QStringList warnedSites(ConfigStore &store, const QString &ack)
    {
        QQmlEngine engine;
        auto *plasmoid = QQmlPropertyMap::create(&engine);
        plasmoid->insert(QStringLiteral("configuration"), QVariant::fromValue<QObject *>(&store));
        engine.rootContext()->setContextProperty("Plasmoid", plasmoid);
        QQmlComponent component(&engine);
        component.setData(warnedSitesQml().toUtf8(), QUrl(QStringLiteral("file:///hw/warned.qml")));
        std::unique_ptr<QObject> view(component.create());
        if (!view) {
            qWarning().noquote() << component.errorString();
            return {QStringLiteral("<no view>")};
        }
        if (!ack.isEmpty())
            QMetaObject::invokeMethod(view.get(), "acknowledged", Q_ARG(QVariant, ack));
        QTest::qWait(50); // the deferred save
        QVariantList list = view->property("warned").toList();
        QStringList out;
        for (const QVariant &v : list)
            out << v.toString();
        return out;
    }

    void httpAcknowledgementPersistsAndIsReadBack()
    {
        const QString origin = QStringLiteral("http://example.org:8080");
        {
            ConfigStore store;
            load(store);
            QVERIFY(store.open(m_file));
            QCOMPARE(warnedSites(store, QString()), QStringList());
            // Not a canonical origin: refused, nothing stored.
            QCOMPARE(warnedSites(store, QStringLiteral("http://example.org:8080/path")), QStringList());
            QCOMPARE(warnedSites(store, QStringLiteral("https://example.org:443")), QStringList());
            QCOMPARE(warnedSites(store, origin), QStringList{origin});
        }
        QCOMPARE(modeOf(m_file), 0600);
        const QJsonObject saved = QJsonDocument::fromJson(readAll(m_file)).object().value("settings").toObject();
        QCOMPARE(saved.value("chatHttpWarnedSites").toArray(), QJsonArray{origin});
        // The next start reads it back.
        ConfigStore again;
        load(again);
        QVERIFY(again.open(m_file));
        QCOMPARE(warnedSites(again, QString()), QStringList{origin});
        // A second site is added, the first kept.
        QCOMPARE(warnedSites(again, QStringLiteral("http://[::1]:80")),
                 (QStringList{origin, QStringLiteral("http://[::1]:80")}));
    }

    void aNonStringInTheStoredAcknowledgementsDropsTheList()
    {
        const QString good = QStringLiteral("http://example.org:8080");
        writeFile(m_file, document(QJsonObject{{"chatHttpWarnedSites",
            QJsonArray{good, QStringLiteral("javascript:alert(1)"), QStringLiteral("http://example.org:8080/x"),
                       QStringLiteral("https://a:443"), good,
                       QString(400, QLatin1Char('a')), 7}}}));
        ConfigStore store;
        load(store);
        QVERIFY(store.open(m_file));
        QCOMPARE(store.dropped(), 1); // a non-string entry: ConfigStore drops the whole list
        QCOMPARE(warnedSites(store, QString()), QStringList());
    }

    void junkStringsInTheStoredAcknowledgementsAreDroppedByTheWidget()
    {
        const QString good = QStringLiteral("http://example.org:8080");
        writeFile(m_file, document(QJsonObject{{"chatHttpWarnedSites",
            QJsonArray{good, QStringLiteral("javascript:alert(1)"), QStringLiteral("http://example.org:8080/x"),
                       QStringLiteral("https://a:443"), good, QString(400, QLatin1Char('a'))}}}));
        ConfigStore store;
        load(store);
        QVERIFY(store.open(m_file));
        QCOMPARE(store.dropped(), 0); // strings: ConfigStore keeps them, the widget filters
        QCOMPARE(warnedSites(store, QString()), QStringList{good});
    }

    // The helper itself (core/appconfig.py, stdlib only) reads what the app
    // wrote: same keys and values, and no settings-unreadable for the modes.
    void theHelperReadsTheFile()
    {
        ConfigStore store;
        load(store);
        QVERIFY(store.open(m_file));
        store.insert("refreshInterval", 60);
        store.insert("usageMode", QStringLiteral("used"));
        QVERIFY(store.save());
        const QString script = QStringLiteral(
            "import json, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from hearthwire.core import appconfig, appletconfig\n"
            "keys = list(appletconfig.CONFIG_ENTRIES)\n"
            "print(json.dumps(appconfig.applied_settings(keys, sys.argv[2]), sort_keys=True))\n");
        QProcess python;
        python.setProcessChannelMode(QProcess::ForwardedErrorChannel);
        QProcessEnvironment env;
        env.insert("PATH", "/usr/bin:/bin");
        env.insert("HOME", m_dir.path());
        env.insert("LANG", "C.UTF-8");
        python.setProcessEnvironment(env);
        python.start(QStringLiteral(HW_TEST_PYTHON),
                     {"-I", "-B", "-c", script, QStringLiteral(HW_REPO_SRC), QFileInfo(m_folder).absolutePath()});
        QVERIFY(python.waitForFinished(30000));
        QCOMPARE(python.exitCode(), 0);
        const QJsonObject applied = QJsonDocument::fromJson(python.readAllStandardOutput()).object();
        QVERIFY(!applied.isEmpty());
        QCOMPARE(applied.value("refreshInterval").toInt(), 60);
        QCOMPARE(applied.value("usageMode").toString(), QStringLiteral("used"));
        int real = 0;
        for (const QString &key : store.keys()) {
            if (key.endsWith("Default"))
                continue;
            ++real;
            QVERIFY2(applied.contains(key), qPrintable(key));
            QCOMPARE(applied.value(key).toVariant(), QJsonValue::fromVariant(store.value(key)).toVariant());
        }
        QCOMPARE(applied.size(), real);
    }
};

QTEST_GUILESS_MAIN(TestConfigStore)
#include "tst_configstore.moc"
