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
// Other URLs (images, icons) are not this guard's business and pass.
#pragma once

#include <QDir>
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

    bool allowed(const QUrl &url) const
    {
        const QString path = url.isLocalFile() ? clean(url.toLocalFile()) : QDir::cleanPath(url.path());
        if (path.contains(QLatin1String("/org/kde/")) || path.startsWith(QLatin1String("org/kde/")))
            return false;
        if (url.scheme() == QLatin1String("qrc"))
            return true;
        if (!url.isLocalFile())
            return false;
        for (const QString &folder : m_folders) {
            if (path.startsWith(folder + QLatin1Char('/')))
                return true;
        }
        return false;
    }

    QUrl intercept(const QUrl &url, DataType type) override
    {
        // An empty URL loads nothing (a Loader without a source).
        if (!watched(type) || url.isEmpty() || allowed(url))
            return url;
        qWarning("hearthwire-hyprland: refused to load a QML or JS file from outside the app and Qt");
        return QUrl(QStringLiteral("qrc:/hearthwire-refused/refused.qml"));
    }

    QStringList folders() const { return m_folders; }

private:
    // The real place of a path: links resolved where it exists, so neither
    // a link nor ".." can lead out of a folder.
    static QString clean(const QString &path)
    {
        const QString canonical = QFileInfo(path).canonicalFilePath();
        return canonical.isEmpty() ? QDir::cleanPath(path) : canonical;
    }

    QStringList m_folders;
};
