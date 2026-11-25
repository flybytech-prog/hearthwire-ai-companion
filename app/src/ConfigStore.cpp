#include "ConfigStore.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJSValue>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRandomGenerator>
#include <QTimer>
#include <QXmlStreamReader>

#include <cerrno>
#include <climits>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace {
const QString LastKey = QStringLiteral("backupAutoExport");
const QString Format = QStringLiteral("hearthwire-app-settings");
constexpr int Version = 1;
const QStringList AppFlags = {QStringLiteral("background"), QStringLiteral("agentsPanel"), QStringLiteral("tray")};

constexpr mode_t FolderMode = 0700;
constexpr mode_t FileMode = 0600;

// As the helper's appconfig._too_open: any permission bit beyond what the
// app writes (a group or other bit, or x on the file) makes the folder or
// file unreadable. Set-id and sticky bits are not permission bits (a setgid
// parent passes its bit on to a new folder), so they are ignored.
bool tooOpen(mode_t mode, mode_t allowed)
{
    return (mode & 0777 & ~allowed) != 0;
}

// Closes a descriptor when it goes out of scope.
struct Fd {
    int fd = -1;
    explicit Fd(int value) : fd(value) {}
    ~Fd()
    {
        if (fd >= 0)
            ::close(fd);
    }
    Fd(const Fd &) = delete;
    Fd &operator=(const Fd &) = delete;
};

enum class Open { Ok, Missing, Unsafe, Error };

// The settings folder. As the helper's open_base/open_child_dir: its parent
// (the config base, $XDG_CONFIG_HOME or ~/.config) is the user's choice and
// may be a link, but must be a directory of ours; the folder itself is
// opened below it without following a link and must be a directory of ours
// with no permission bit beyond 0700 (else Unsafe, as the helper refuses
// it). `create` makes it (0700) when missing and then sets it to exactly
// 0700 (the umask may have taken owner bits away); an existing folder is
// only changed once it has passed that check.
int openFolder(const QString &path, bool create, Open *result)
{
    const QFileInfo folderInfo(path);
    const QByteArray baseName = QFile::encodeName(folderInfo.absolutePath());
    const QByteArray name = QFile::encodeName(folderInfo.fileName());
    if (create)
        QDir().mkpath(folderInfo.absolutePath());
    Fd base(::open(baseName.constData(), O_RDONLY | O_DIRECTORY | O_CLOEXEC));
    if (base.fd < 0) {
        *result = errno == ENOENT ? Open::Missing : errno == ENOTDIR ? Open::Unsafe : Open::Error;
        return -1;
    }
    struct stat baseStat {};
    if (::fstat(base.fd, &baseStat) != 0 || baseStat.st_uid != ::geteuid()) {
        *result = Open::Unsafe;
        return -1;
    }
    if (create && ::mkdirat(base.fd, name.constData(), FolderMode) != 0 && errno != EEXIST) {
        *result = Open::Error;
        return -1;
    }
    const int fd = ::openat(base.fd, name.constData(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) {
        *result = errno == ENOENT ? Open::Missing : (errno == ELOOP || errno == ENOTDIR) ? Open::Unsafe : Open::Error;
        return -1;
    }
    struct stat info {};
    if (::fstat(fd, &info) != 0 || !S_ISDIR(info.st_mode) || info.st_uid != ::geteuid()
        || tooOpen(info.st_mode, FolderMode)) {
        ::close(fd);
        *result = Open::Unsafe;
        return -1;
    }
    if (create && (info.st_mode & 07777) != FolderMode && ::fchmod(fd, FolderMode) != 0) {
        ::close(fd);
        *result = Open::Error;
        return -1;
    }
    *result = Open::Ok;
    return fd;
}

bool writeAll(int fd, const QByteArray &data)
{
    const char *at = data.constData();
    qsizetype left = data.size();
    while (left > 0) {
        const ssize_t n = ::write(fd, at, size_t(left));
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0)
            return false;
        at += n;
        left -= n;
    }
    return true;
}
}

ConfigStore::ConfigStore(QObject *parent)
    : QQmlPropertyMap(this, parent)
{
}

QString ConfigStore::defaultFile()
{
    // As the helper's appconfig: XDG_CONFIG_HOME only when absolute.
    QString base = qEnvironmentVariable("XDG_CONFIG_HOME");
    if (base.isEmpty() || !QDir::isAbsolutePath(base))
        base = QDir::homePath() + QStringLiteral("/.config");
    return QDir(base).filePath(QStringLiteral("hearthwire-hyprland/settings.json"));
}

bool ConfigStore::loadSchema(const QString &path)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly))
        return false;
    QXmlStreamReader xml(&file);
    QString name;
    QString type;
    QStringList order;
    QHash<QString, QString> types;
    QHash<QString, QVariant> defaults;
    while (!xml.atEnd()) {
        xml.readNext();
        if (!xml.isStartElement())
            continue;
        if (xml.name() == QLatin1String("entry")) {
            name = xml.attributes().value(QLatin1String("name")).toString();
            type = xml.attributes().value(QLatin1String("type")).toString();
            if (name.isEmpty() || types.contains(name))
                return false;
            if (type == QLatin1String("String"))
                defaults.insert(name, QString());
            else if (type == QLatin1String("Int"))
                defaults.insert(name, 0);
            else if (type == QLatin1String("Bool"))
                defaults.insert(name, false);
            else if (type == QLatin1String("StringList"))
                defaults.insert(name, QStringList());
            else
                return false;
            order.append(name);
            types.insert(name, type);
        } else if (xml.name() == QLatin1String("default") && !name.isEmpty()) {
            const QString text = xml.readElementText();
            if (type == QLatin1String("Int"))
                defaults.insert(name, text.toInt());
            else if (type == QLatin1String("Bool"))
                defaults.insert(name, text == QLatin1String("true"));
            else if (type == QLatin1String("StringList"))
                defaults.insert(name, text.split(QLatin1Char(','), Qt::SkipEmptyParts));
            else
                defaults.insert(name, text);
        }
    }
    if (xml.hasError() || order.isEmpty())
        return false;
    m_order = order;
    m_types = types;
    m_defaults = defaults;
    for (const QString &key : std::as_const(m_order)) {
        insert(key + QStringLiteral("Default"), m_defaults.value(key));
        insert(key, m_defaults.value(key));
    }
    return true;
}

QStringList ConfigStore::keys() const
{
    QStringList result;
    for (const QString &key : m_order)
        result << key + QStringLiteral("Default") << key;
    return result;
}

bool ConfigStore::open(const QString &path)
{
    m_file = QFileInfo(path).absoluteFilePath();
    m_status = Status::Missing;
    m_writable = true;
    m_moveDamaged = false;
    m_dropped = 0;
    Open opened = Open::Ok;
    Fd folder(openFolder(QFileInfo(m_file).absolutePath(), false, &opened));
    if (opened == Open::Missing)
        return true;
    if (folder.fd < 0) {
        m_status = Status::Unreadable;
        m_writable = false;
        return false;
    }
    const QByteArray name = QFile::encodeName(QFileInfo(m_file).fileName());
    Fd file(::openat(folder.fd, name.constData(), O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK));
    if (file.fd < 0 && errno == ENOENT)
        return true;
    struct stat info {};
    // A second name (hard link) is fine, as for the helper: the file is ours
    // in our 0700 folder, and a save renames a new file over this name, so
    // the other name never sees later writes (hard-link backups keep working).
    if (file.fd < 0 || ::fstat(file.fd, &info) != 0 || !S_ISREG(info.st_mode) || info.st_uid != ::geteuid()
        || tooOpen(info.st_mode, FileMode) || info.st_size > MaxFileBytes) {
        m_status = Status::Unreadable;
        m_writable = false;
        return false;
    }
    QByteArray data;
    char buffer[65536];
    for (;;) {
        const ssize_t n = ::read(file.fd, buffer, sizeof buffer);
        if (n < 0 && errno == EINTR)
            continue;
        if (n < 0) {
            m_status = Status::Unreadable;
            m_writable = false;
            return false;
        }
        if (n == 0)
            break;
        data.append(buffer, n);
        if (data.size() > MaxFileBytes) {
            m_status = Status::Unreadable;
            m_writable = false;
            return false;
        }
    }

    QJsonParseError error;
    const QJsonDocument doc = QJsonDocument::fromJson(data, &error);
    const QJsonObject root = doc.object();
    const QJsonValue settings = root.value(QLatin1String("settings"));
    const QJsonValue app = root.value(QLatin1String("app"));
    bool known = true;
    for (auto it = root.begin(); it != root.end(); ++it) {
        if (it.key() != QLatin1String("format") && it.key() != QLatin1String("version")
            && it.key() != QLatin1String("settings") && it.key() != QLatin1String("app"))
            known = false;
    }
    const QVariant version = root.value(QLatin1String("version")).toVariant();
    if (error.error != QJsonParseError::NoError || !doc.isObject() || !known
        || root.value(QLatin1String("format")) != QJsonValue(Format)
        || version.typeId() != QMetaType::LongLong || version.toLongLong() != Version || !settings.isObject()
        || !(app.isUndefined() || app.isObject())) {
        m_status = Status::Damaged;
        m_moveDamaged = true;
        return false;
    }
    const QJsonObject values = settings.toObject();
    for (const QString &key : std::as_const(m_order)) {
        if (!values.contains(key))
            continue;
        QVariant value;
        if (fromFile(key, values.value(key), &value))
            insert(key, value);
        else
            ++m_dropped;
    }
    const QJsonObject flags = app.toObject();
    for (const QString &flag : AppFlags) {
        const QJsonValue value = flags.value(flag);
        if (value.isBool())
            m_app.insert(flag, value.toBool());
        else if (!value.isUndefined())
            ++m_dropped;
    }
    m_status = Status::Ok;
    return true;
}

// A stored value of the key's JSON type, as the helper's appconfig reads it.
bool ConfigStore::fromFile(const QString &key, const QJsonValue &value, QVariant *out) const
{
    const QString type = m_types.value(key);
    if (type == QLatin1String("String") && value.isString()) {
        *out = value.toString();
        return true;
    }
    if (type == QLatin1String("Bool") && value.isBool()) {
        *out = value.toBool();
        return true;
    }
    if (type == QLatin1String("StringList") && value.isArray()) {
        // An array of strings, within the caps; anything else is dropped whole.
        const QJsonArray array = value.toArray();
        if (array.size() > MaxListEntries)
            return false;
        QStringList list;
        for (const QJsonValue &item : array) {
            if (!item.isString() || item.toString().size() > MaxListEntryChars)
                return false;
            list.append(item.toString());
        }
        *out = list;
        return true;
    }
    if (type == QLatin1String("Int")) {
        // A JSON integer (no fraction or exponent) in 32-bit range.
        const QVariant number = value.toVariant();
        if (number.typeId() == QMetaType::LongLong && number.toLongLong() >= INT_MIN
            && number.toLongLong() <= INT_MAX) {
            *out = int(number.toLongLong());
            return true;
        }
    }
    return false;
}

// A value of the key's type, or ok = false. Numbers in a Bool key or text in
// an Int key are refused rather than guessed.
QVariant ConfigStore::coerce(const QString &key, const QVariant &value, bool *ok) const
{
    *ok = false;
    const QString type = m_types.value(key);
    const auto id = value.typeId();
    if (type == QLatin1String("String") && id == QMetaType::QString) {
        *ok = true;
        return value.toString();
    }
    if (type == QLatin1String("Bool") && id == QMetaType::Bool) {
        *ok = true;
        return value.toBool();
    }
    if (type == QLatin1String("StringList") && (id == QMetaType::QStringList || id == QMetaType::QVariantList)) {
        // From QML an array of strings (a QVariantList); the same caps as a read.
        QStringList list;
        const QVariantList items = value.toList();
        if (id == QMetaType::QStringList)
            list = value.toStringList();
        else {
            for (const QVariant &item : items) {
                if (item.typeId() != QMetaType::QString)
                    return QVariant();
                list.append(item.toString());
            }
        }
        if (list.size() > MaxListEntries)
            return QVariant();
        for (const QString &entry : std::as_const(list)) {
            if (entry.size() > MaxListEntryChars)
                return QVariant();
        }
        *ok = true;
        return list;
    }
    if (type == QLatin1String("Int")
        && (id == QMetaType::Int || id == QMetaType::LongLong || id == QMetaType::Double
            || id == QMetaType::UInt || id == QMetaType::ULongLong)) {
        const double number = value.toDouble();
        if (number >= INT_MIN && number <= INT_MAX) {
            *ok = true;
            return int(number);
        }
    }
    return QVariant();
}

QVariant ConfigStore::updateValue(const QString &key, const QVariant &input)
{
    // "<key>Default" and unknown names stay as they are, as in KConfig.
    if (!m_types.contains(key))
        return value(key);
    bool ok = false;
    // A JS array from QML arrives as a QJSValue: its elements as a QVariantList.
    const QVariant plain = input.canConvert<QJSValue>() && m_types.value(key) == QLatin1String("StringList")
        ? input.value<QJSValue>().toVariant()
        : input;
    QVariant typed = coerce(key, plain, &ok);
    if (!ok) {
        // KConfig converts what it can; a QML string for an Int key is the
        // one case the pages have (TextField text).
        if (m_types.value(key) == QLatin1String("Int") && input.canConvert<int>())
            typed = input.toInt(&ok);
        else if (m_types.value(key) == QLatin1String("String"))
            typed = input.toString(), ok = true;
        else if (m_types.value(key) == QLatin1String("Bool"))
            typed = input.toBool(), ok = true;
    }
    if (!ok)
        return value(key);
    scheduleSave();
    return typed;
}

void ConfigStore::writeConfig()
{
    save();
    scheduleSave();
}

// One save and one full re-emit for a burst of writes (an Apply writes every
// key of the page, then calls writeConfig()).
void ConfigStore::scheduleSave()
{
    if (m_pending)
        return;
    m_pending = true;
    QTimer::singleShot(0, this, [this] {
        m_pending = false;
        save();
        reemitAll();
    });
}

QByteArray ConfigStore::document() const
{
    QJsonObject settings;
    for (const QString &key : std::as_const(m_order))
        settings.insert(key, QJsonValue::fromVariant(value(key)));
    QJsonObject app;
    for (const QString &flag : AppFlags)
        app.insert(flag, m_app.value(flag, false).toBool());
    QJsonObject root;
    root.insert(QStringLiteral("format"), Format);
    root.insert(QStringLiteral("version"), Version);
    root.insert(QStringLiteral("settings"), settings);
    root.insert(QStringLiteral("app"), app);
    return QJsonDocument(root).toJson(QJsonDocument::Indented);
}

bool ConfigStore::save()
{
    if (m_file.isEmpty() || !m_writable)
        return false;
    const QByteArray data = document();
    if (data.size() > MaxFileBytes)
        return false;
    const QFileInfo target(m_file);
    Open opened = Open::Ok;
    Fd folder(openFolder(target.absolutePath(), true, &opened));
    if (folder.fd < 0)
        return false;
    const QByteArray name = QFile::encodeName(target.fileName());
    if (m_moveDamaged) {
        // Kept once, for the user to look at; then the new file replaces it.
        const QByteArray kept = name + ".damaged";
        if (::renameat(folder.fd, name.constData(), folder.fd, kept.constData()) != 0 && errno != ENOENT)
            return false;
        m_moveDamaged = false;
    }
    const QByteArray temp = "." + name + "." + QByteArray::number(QRandomGenerator::system()->generate64(), 16);
    Fd file(::openat(folder.fd, temp.constData(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, FileMode));
    if (file.fd < 0)
        return false;
    // The umask may have taken bits away; the helper wants 0600 or less, and
    // the app sets exactly 0600.
    const bool written = ::fchmod(file.fd, FileMode) == 0 && writeAll(file.fd, data) && ::fsync(file.fd) == 0;
    if (!written || ::renameat(folder.fd, temp.constData(), folder.fd, name.constData()) != 0) {
        ::unlinkat(folder.fd, temp.constData(), 0);
        return false;
    }
    ::fsync(folder.fd);
    return true;
}

void ConfigStore::reemitAll()
{
    for (const QString &key : std::as_const(m_order)) {
        if (key != LastKey)
            Q_EMIT valueChanged(key, value(key));
    }
    if (m_types.contains(LastKey))
        Q_EMIT valueChanged(LastKey, value(LastKey));
    ++m_reemits;
    Q_EMIT reemitted();
}
