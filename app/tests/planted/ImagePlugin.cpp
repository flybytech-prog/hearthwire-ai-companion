// A planted image format plugin for tst_pluginpaths: it only has to be
// found: it says it can read "hwplanted" and never reads anything.
#include <QImageIOPlugin>

class PlantedImagePlugin : public QImageIOPlugin
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID QImageIOHandlerFactoryInterface_iid FILE "image.json")

public:
    // Listed by supportedImageFormats(); it never reads anything.
    Capabilities capabilities(QIODevice *device, const QByteArray &) const override { return device ? Capabilities() : CanRead; }
    QImageIOHandler *create(QIODevice *, const QByteArray &) const override { return nullptr; }
};

#include "ImagePlugin.moc"
