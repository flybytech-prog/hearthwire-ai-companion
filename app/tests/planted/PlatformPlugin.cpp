// A planted platform plugin for tst_pluginpaths, keyed "hwplanted" (the
// child asks for "hwplanted;offscreen"): when Qt loads it, it leaves a
// marker file ($HW_PLANTED_MARKER) and makes nothing, so Qt goes on to its
// own offscreen plugin.
#include <QFile>
#include <qpa/qplatformintegrationplugin.h>

class PlantedPlatformPlugin : public QPlatformIntegrationPlugin
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID QPlatformIntegrationFactoryInterface_iid FILE "platform.json")

public:
    QPlatformIntegration *create(const QString &, const QStringList &) override
    {
        QFile marker(qEnvironmentVariable("HW_PLANTED_MARKER"));
        if (marker.open(QIODevice::WriteOnly))
            marker.write("loaded\n");
        return nullptr;
    }
};

#include "PlatformPlugin.moc"
