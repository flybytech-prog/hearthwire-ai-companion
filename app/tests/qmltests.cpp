// hearthwire-qmltests: qmltestrunner for the plasmoid's tests/qml under the
// app's stand-ins. The stand-in modules are static (as in the app), so a
// plain qmltestrunner can't load them; this runner links them in and sets up
// the engine as the app does: the app style (Material behind it), i18n() as the root context
// object, image://icon, one Plasmoid host whose settings are main.xml's
// defaults and never saved. Fixture mode is on, so no test can start a
// helper. Run: hearthwire-qmltests -input <synced test file>.
#include <QQmlContext>
#include <QQmlEngine>
#include <QQuickStyle>
#include <QtQml/qqmlextensionplugin.h>
#include <QtQuickTest>

#include "ConfigStore.h"
#include "IconProvider.h"
#include "ImportPaths.h"
#include "LocalizedContext.h"
#include "PlasmoidHost.h"
#include "ProcessRunner.h"

Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_KirigamiPlugin)
Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_PlasmaComponentsPlugin)
Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_PlasmaExtrasPlugin)
Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_PlasmaCorePlugin)
Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_PlasmoidPlugin)
Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_Plasma5SupportPlugin)
Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_KCMUtilsPlugin)
Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_NotificationPlugin)
Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_ConfigurationPlugin)
Q_IMPORT_QML_PLUGIN(Hearthwire_StylePlugin)

class Setup : public QObject
{
    Q_OBJECT

public Q_SLOTS:
    void applicationAvailable()
    {
        hwDropEnvironmentImportPaths();
        // The app's style, as main.cpp sets it.
        QQuickStyle::setStyle(QStringLiteral("Hearthwire.Style"));
        QQuickStyle::setFallbackStyle(QStringLiteral("Material"));
        // An empty book: every command gets exit code 127, nothing runs.
        ProcessRunner::useFixtures(QStringLiteral(HW_EMPTY_BOOK));
        m_store = new ConfigStore(this);
        m_store->loadSchema(QStringLiteral(HW_MAIN_XML));
        m_host = new PlasmoidHost(this);
        m_host->setConfiguration(m_store);
        PlasmoidHost::setInstance(m_host);
    }

    void qmlEngineAvailable(QQmlEngine *engine)
    {
        engine->setImportPathList(hwImportPaths(engine->importPathList()));
        engine->addImageProvider(QStringLiteral("icon"), new IconProvider);
        engine->rootContext()->setContextObject(new LocalizedContext(engine));
    }

private:
    ConfigStore *m_store = nullptr;
    PlasmoidHost *m_host = nullptr;
};

QUICK_TEST_MAIN_WITH_SETUP(hearthwire_qmltests, Setup)

#include "qmltests.moc"
