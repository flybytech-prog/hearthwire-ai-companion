// image://icon/<name>: a themed icon by name, for the Kirigami.Icon
// stand-in. Only icon theme names; never a path.
#pragma once

#include <QIcon>
#include <QQuickImageProvider>

class IconProvider : public QQuickImageProvider
{
public:
    IconProvider() : QQuickImageProvider(QQuickImageProvider::Pixmap) {}

    QPixmap requestPixmap(const QString &id, QSize *size, const QSize &requested) override
    {
        const int edge = qMax(16, qMax(requested.width(), requested.height()));
        QPixmap pixmap;
        if (!id.contains(QLatin1Char('/')))
            pixmap = QIcon::fromTheme(id).pixmap(edge, edge);
        if (size)
            *size = pixmap.size();
        return pixmap;
    }
};
