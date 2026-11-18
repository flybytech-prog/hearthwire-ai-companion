// A runtime backstop behind the build-time import check (sync_plasmoid.py):
// the app's QML engine loads QML, JS and qmldir files only from its own
// compiled-in modules (qrc:) and from the local folders of its import path
// list (Qt's own QML folders, see ImportPaths.h), and never anything under
// an org/kde folder. Anything else (a Loader or Qt.createComponent with a
// file:/// URL, a string import of a file elsewhere, a network URL, a KDE
// module found in Qt's folder on a KDE host) is refused: the engine is
// handed a qrc: URL that does not exist, so the load fails closed, and one
// fixed line is logged (never the URL).
//
// An allowed local file is handed back as the canonical path that was
// checked, never the URL as asked: a link swapped between the check and the
// load can't lead anywhere else (round 2, check-vs-use). A path that does
// not exist (the engine probes qmldir candidates in Qt's folders) has
// nothing to load: it is refused quietly, without the log line or count.
//
// Other URLs (images, icons) are not this guard's business and pass.
#pragma once

#include <QDir>
#include <atomic>
#include <QFileInfo>
#include <QQmlAbstractUrlInterceptor>
#include <QStringList>
#include <QUrl>

class UrlGuard : public QQmlAbstractUrlInterceptor
{
public:
    // `importPaths`: the engine's final importPathList(); its local folders
    // are the only ones files may come from.
    explicit UrlGuard(const QStringList &importPaths)
    {
        for (const QString &path : importPaths) {
            if (path.startsWith(QLatin1String("qrc:")) || path.startsWith(QLatin1Char(':')))
                continue;
            const QUrl url(path);
            const QString local = url.isLocalFile() ? url.toLocalFile() : path;
            if (!QDir::isAbsolutePath(local))
                continue;
            m_folders.append(clean(local));
        }
    }

    static bool watched(DataType type) { return type == QmlFile || type == JavaScriptFile || type == QmldirFile; }

    bool allowed(const QUrl &url) const { return !resolve(url).isEmpty(); }

    // What the engine gets for an allowed URL: a qrc: URL as it is, a local
    // file as the canonical file URL that was checked. Empty when refused.
    QUrl resolve(const QUrl &url) const
    {
        if (url.scheme() == QLatin1String("qrc")) {
            const QString path = QDir::cleanPath(url.path());
            return kde(path) ? QUrl() : url;
        }
        if (!url.isLocalFile())
            return QUrl();
        // Canonicalised once: the path checked is the path handed back.
        // A path that does not exist has no canonical form and is refused.
        const QString canonical = QFileInfo(url.toLocalFile()).canonicalFilePath();
        if (canonical.isEmpty() || kde(canonical))
            return QUrl();
        for (const QString &folder : m_folders) {
            if (canonical.startsWith(folder + QLatin1Char('/')))
                return QUrl::fromLocalFile(canonical);
        }
        return QUrl();
    }

    QUrl intercept(const QUrl &url, DataType type) override
    {
        // An empty URL loads nothing (a Loader without a source).
        if (!watched(type) || url.isEmpty())
            return url;
        const QUrl resolved = resolve(url);
        if (!resolved.isEmpty())
            return resolved;
        if (!missingInFolder(url)) {
            s_refusals.fetch_add(1, std::memory_order_relaxed);
            qWarning("hearthwire-hyprland: refused to load a QML or JS file from outside the app and Qt");
        }
        return QUrl(QStringLiteral("qrc:/hearthwire-refused/refused.qml"));
    }

    // Refusals logged since start (fixture checks: 0 in a normal run).
    static int refusals() { return s_refusals.load(std::memory_order_relaxed); }

    QStringList folders() const { return m_folders; }

private:
    static bool kde(const QString &path)
    {
        return path.contains(QLatin1String("/org/kde/")) || path.startsWith(QLatin1String("org/kde/"));
    }

    // A local path in an allowed folder that does not exist: nothing to
    // load, nothing to report.
    bool missingInFolder(const QUrl &url) const
    {
        if (!url.isLocalFile())
            return false;
        const QString path = clean(url.toLocalFile());
        if (kde(path) || QFileInfo::exists(path))
            return false;
        for (const QString &folder : m_folders) {
            if (path.startsWith(folder + QLatin1Char('/')))
                return true;
        }
        return false;
    }

    // The real place of a path: links resolved where it exists, so neither
    // a link nor ".." can lead out of a folder.
    static QString clean(const QString &path)
    {
        const QString canonical = QFileInfo(path).canonicalFilePath();
        return canonical.isEmpty() ? QDir::cleanPath(path) : canonical;
    }

    QStringList m_folders;
    static inline std::atomic<int> s_refusals{0};
};
