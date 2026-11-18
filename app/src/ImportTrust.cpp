#include "ImportTrust.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QUrl>

#include <cstdio>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace {

// One open O_PATH descriptor, closed when it goes.
class Fd
{
public:
    explicit Fd(int fd)
        : m_fd(fd)
    {
    }
    ~Fd()
    {
        if (m_fd >= 0)
            ::close(m_fd);
    }
    Fd(const Fd &) = delete;
    Fd &operator=(const Fd &) = delete;
    int get() const { return m_fd; }
    void reset(int fd)
    {
        if (m_fd >= 0)
            ::close(m_fd);
        m_fd = fd;
    }

private:
    int m_fd = -1;
};

constexpr int WalkFlags = O_PATH | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC;

// One folder on the way: a folder, owned by root or us, that nobody else
// can write to. Only above the leaf, a root-owned sticky folder (/tmp) may
// be writable by others.
bool acceptable(int fd, bool leaf, const HwImportOwners &owners)
{
    struct stat info {};
    if (::fstat(fd, &info) != 0 || !S_ISDIR(info.st_mode))
        return false;
    const bool root = owners.root.contains(info.st_uid);
    if (!root && info.st_uid != owners.user)
        return false;
    if ((info.st_mode & (S_IWGRP | S_IWOTH)) == 0)
        return true;
    return !leaf && root && (info.st_mode & S_ISVTX) != 0;
}

bool qrc(const QString &path)
{
    return path.startsWith(QLatin1String("qrc:")) || path.startsWith(QLatin1Char(':'));
}

} // namespace

QString hwTrustedFolder(const QString &folder, const HwImportOwners &owners)
{
    if (!QDir::isAbsolutePath(folder))
        return QString();
    const QString canonical = QFileInfo(folder).canonicalFilePath();
    if (canonical.isEmpty() || !canonical.startsWith(QLatin1Char('/')))
        return QString();
    const QStringList names = canonical.split(QLatin1Char('/'), Qt::SkipEmptyParts);
    Fd fd(::open("/", WalkFlags));
    if (fd.get() < 0 || !acceptable(fd.get(), names.isEmpty(), owners))
        return QString();
    for (qsizetype i = 0; i < names.size(); ++i) {
        const QByteArray name = QFile::encodeName(names.at(i));
        if (name.isEmpty() || name == "." || name == ".." || name.contains('\0'))
            return QString();
        fd.reset(::openat(fd.get(), name.constData(), WalkFlags));
        if (fd.get() < 0 || !acceptable(fd.get(), i == names.size() - 1, owners))
            return QString();
    }
    return canonical;
}

QStringList hwTrustedImportPaths(const QStringList &paths, const HwImportOwners &owners, int *dropped)
{
    QStringList kept;
    int count = 0;
    for (const QString &path : paths) {
        if (qrc(path)) {
            kept.append(path);
            continue;
        }
        const QUrl url(path);
        const QString local = url.isLocalFile() ? url.toLocalFile() : path;
        const QString trusted = hwTrustedFolder(local, owners);
        if (trusted.isEmpty()) {
            ++count;
            continue;
        }
        kept.append(trusted);
    }
    if (dropped)
        *dropped = count;
    return kept;
}

QStringList hwTrustedImportPaths(const QStringList &paths)
{
    int dropped = 0;
    const QStringList kept = hwTrustedImportPaths(paths, HwImportOwners{{0}, ::getuid()}, &dropped);
    if (dropped > 0)
        std::fprintf(stderr,
                     "hearthwire-hyprland: %d QML import folder(s) dropped: not owned by root or you, or others can change them\n",
                     dropped);
    return kept;
}
