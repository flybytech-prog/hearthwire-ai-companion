// PlasmoidHost: the `Plasmoid` attached object as the plasmoid's QML sees
// it through Hearthwire.Compat.Plasmoid.
#include <QDir>
#include <QFile>
#include <QQmlComponent>
#include <QQmlEngine>
#include <QQmlListReference>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>
#include <QtQml/qqmlextensionplugin.h>

#include "ConfigStore.h"
#include "ImportPaths.h"
#include "PlasmoidHost.h"

Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_PlasmoidPlugin)

class TestPlasmoidHost : public QObject
{
    Q_OBJECT

    ConfigStore *m_store = nullptr;
    PlasmoidHost *m_host = nullptr;

    QObject *create(QQmlEngine &engine, const QByteArray &body)
    {
        QQmlComponent component(&engine);
        component.setData("import QtQuick\nimport Hearthwire.Compat.Plasmoid\n" + body, QUrl("qrc:/test.qml"));
        QObject *object = component.create();
        if (!object)
            qWarning() << component.errorString();
        return object;
    }

private Q_SLOTS:
    void initTestCase()
    {
        m_store = new ConfigStore(this);
        QVERIFY(m_store->loadSchema(QStringLiteral(HW_MAIN_XML)));
        m_host = new PlasmoidHost(this);
        m_host->setConfiguration(m_store);
        PlasmoidHost::setInstance(m_host);
    }

    void idIsTheReservedAppId()
    {
        // core/frontend.py APP_APPLET_ID = 2**31; never 1, never a 32-bit int.
        QCOMPARE(PlasmoidHost::AppAppletId, qint64(2147483648LL));
        QQmlEngine engine;
        QScopedPointer<QObject> item(create(engine, R"(
Item {
    readonly property var id: Plasmoid.id
    readonly property bool whole: Number.isInteger(Plasmoid.id)
    readonly property string text: "applet-" + Plasmoid.id
    // InstallInfo.js / ChatStorage.js validInt: a whole number 0..2147483648.
    readonly property bool validInt: typeof Plasmoid.id === "number" && Number.isInteger(Plasmoid.id)
                                     && Plasmoid.id >= 0 && Plasmoid.id <= 2147483648
}
)"));
        QVERIFY(item);
        QCOMPARE(item->property("id").toDouble(), 2147483648.0);
        QVERIFY(item->property("whole").toBool());
        QCOMPARE(item->property("text").toString(), QStringLiteral("applet-2147483648"));
        QVERIFY(item->property("validInt").toBool());
    }

    void oneHostForEveryItem()
    {
        QQmlEngine engine;
        QScopedPointer<QObject> item(create(engine, R"(
Item {
    readonly property var first: Plasmoid
    readonly property var second: child.Plasmoid
    readonly property var configuration: Plasmoid.configuration
    readonly property int formFactor: Plasmoid.formFactor
    Item { id: child }
}
)"));
        QVERIFY(item);
        QCOMPARE(item->property("first").value<QObject *>(), m_host);
        QCOMPARE(item->property("second").value<QObject *>(), m_host);
        QCOMPARE(item->property("configuration").value<QObject *>(), m_store);
        QCOMPARE(item->property("formFactor").toInt(), 0);
    }

    void onlyTheConfigureAction()
    {
        QSignalSpy spy(m_host, &PlasmoidHost::configureRequested);
        QQmlEngine engine;
        QScopedPointer<QObject> item(create(engine, R"(
Item {
    readonly property bool configure: Plasmoid.internalAction("configure") !== null
    readonly property bool other: Plasmoid.internalAction("remove") === null
    Component.onCompleted: Plasmoid.internalAction("configure").trigger()
}
)"));
        QVERIFY(item);
        QVERIFY(item->property("configure").toBool());
        QVERIFY(item->property("other").toBool());
        QCOMPARE(spy.count(), 1);
        QCOMPARE(m_host->internalAction("configure"), m_host->internalAction("configure"));
    }

    void busyIconAndActions()
    {
        QQmlEngine engine;
        QScopedPointer<QObject> item(create(engine, R"(
Item {
    Component.onCompleted: {
        Plasmoid.busy = true
        Plasmoid.icon = "hearthwire"
    }
}
)"));
        QVERIFY(item);
        QCOMPARE(m_host->property("busy").toBool(), true);
        QCOMPARE(m_host->property("icon").toString(), QStringLiteral("hearthwire"));
    }

    // Security I3: QML_IMPORT_PATH / QML2_IMPORT_PATH from the environment
    // can't shadow a stand-in or a Qt module once the app's list is set.
    void environmentImportPathsAreDropped()
    {
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        // A module only the environment's folder has, and a planted stand-in.
        for (const QString &module : {QStringLiteral("HwShadowTest"), QStringLiteral("Hearthwire/Compat/Plasmoid")}) {
            QVERIFY(QDir(dir.path()).mkpath(module));
            QFile qmldir(dir.path() + "/" + module + "/qmldir");
            QVERIFY(qmldir.open(QIODevice::WriteOnly));
            qmldir.write("module " + module.toUtf8().replace('/', '.') + "\nPlanted 1.0 Planted.qml\n");
            qmldir.close();
            QFile planted(dir.path() + "/" + module + "/Planted.qml");
            QVERIFY(planted.open(QIODevice::WriteOnly));
            planted.write("import QtQuick\nItem { objectName: \"planted\" }\n");
        }
        const QByteArray old = qgetenv("QML_IMPORT_PATH");
        const QByteArray old2 = qgetenv("QML2_IMPORT_PATH");
        qputenv("QML_IMPORT_PATH", QFile::encodeName(dir.path()));
        qputenv("QML2_IMPORT_PATH", QFile::encodeName(dir.path()));
        const auto loads = [](QQmlEngine &engine, const QByteArray &body) {
            QQmlComponent component(&engine);
            component.setData(body, QUrl("qrc:/import-test.qml"));
            QScopedPointer<QObject> object(component.create());
            return object && object->objectName() == QLatin1String("planted");
        };
        const QByteArray shadow = "import HwShadowTest\nPlanted {}\n";
        const QByteArray standIn = "import Hearthwire.Compat.Plasmoid\nPlanted {}\n";
        {
            // Qt's default list takes the environment's folder: the proof
            // that the variable is seen at all.
            QQmlEngine engine;
            QVERIFY(engine.importPathList().contains(dir.path()));
            QVERIFY(loads(engine, shadow));
        }
        hwDropEnvironmentImportPaths();
        QVERIFY(qgetenv("QML_IMPORT_PATH").isNull() && qgetenv("QML2_IMPORT_PATH").isNull());
        {
            QQmlEngine engine;
            engine.setImportPathList(hwImportPaths(engine.importPathList()));
            QVERIFY(!engine.importPathList().contains(dir.path()));
            QVERIFY(!engine.importPathList().contains(QCoreApplication::applicationDirPath()));
            QVERIFY(engine.importPathList().contains(QStringLiteral("qrc:/qt/qml")));
            QVERIFY(!loads(engine, shadow));
            QVERIFY(!loads(engine, standIn));
            // The stand-in itself still loads.
            QQmlComponent component(&engine);
            component.setData("import QtQuick\nimport Hearthwire.Compat.Plasmoid\nItem { property var id: Plasmoid.id }\n",
                              QUrl("qrc:/import-test-2.qml"));
            QScopedPointer<QObject> object(component.create());
            QVERIFY2(object, qPrintable(component.errorString()));
            QCOMPARE(object->property("id").toDouble(), 2147483648.0);
        }
        qputenv("QML_IMPORT_PATH", old);
        qputenv("QML2_IMPORT_PATH", old2);
        if (old.isNull())
            qunsetenv("QML_IMPORT_PATH");
        if (old2.isNull())
            qunsetenv("QML2_IMPORT_PATH");
    }

    // The host never hands out an action that is gone (review-1 #4). QML
    // parents main.qml's actions to the attached host, but nothing promises
    // they live as long as it does.
    void deletedActionsAreDropped()
    {
        QQmlEngine engine;
        QScopedPointer<QObject> item(create(engine, R"(
Item {
    Plasmoid.contextualActions: [
        QtObject { objectName: "one" },
        QtObject { objectName: "two" }
    ]
}
)"));
        QVERIFY(item);
        QCOMPARE(m_host->actions().size(), 2);
        QQmlListReference list(m_host, "contextualActions");
        QCOMPARE(list.count(), 2);
        delete m_host->actions().at(0);
        QCOMPARE(m_host->actions().size(), 1);
        QCOMPARE(m_host->actions().at(0)->objectName(), QStringLiteral("two"));
        QCOMPARE(list.count(), 1);
        QCOMPARE(list.at(0)->objectName(), QStringLiteral("two"));
        QCOMPARE(list.at(1), nullptr);
        delete m_host->actions().at(0);
        QCOMPARE(m_host->actions().size(), 0);
        QCOMPARE(list.count(), 0);
        list.clear();
    }
};

QTEST_MAIN(TestPlasmoidHost)
#include "tst_plasmoidhost.moc"
