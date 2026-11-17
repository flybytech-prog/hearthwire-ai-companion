// UrlGuard (round 2, runtime backstop): the app's engine loads QML, JS and
// qmldir files only from qrc: and the local folders of its import path
// list, never from an org/kde folder. Each refusal is proved against a
// plain engine that does load the same planted file.
#include <QDir>
#include <QFile>
#include <QQmlComponent>
#include <QQmlEngine>
#include <QTemporaryDir>
#include <QTest>
#include <QtQml/qqmlextensionplugin.h>

#include "ConfigStore.h"
#include "ImportPaths.h"
#include "PlasmoidHost.h"
#include "UrlGuard.h"

Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_PlasmoidPlugin)

namespace {
const char Refused[] = "hearthwire-hyprland: refused to load a QML or JS file from outside the app and Qt";

void write(const QString &path, const QByteArray &data)
{
    QDir().mkpath(QFileInfo(path).absolutePath());
    QFile file(path);
    QVERIFY(file.open(QIODevice::WriteOnly));
    file.write(data);
}
}

class TestUrlGuard : public QObject
{
    Q_OBJECT

    QTemporaryDir m_dir;
    QString m_allowed;   // stands for Qt's QML folder
    QString m_outside;   // anywhere else
    ConfigStore *m_store = nullptr;
    PlasmoidHost *m_host = nullptr;

    QUrl fileUrl(const QString &path) const { return QUrl::fromLocalFile(path); }

    // An engine set up as main() does (the extra folder plays Qt's).
    void setUp(QQmlEngine &engine, std::unique_ptr<UrlGuard> &guard, bool guarded)
    {
        engine.setImportPathList(hwImportPaths(engine.importPathList()) << m_allowed);
        if (!guarded)
            return;
        guard = std::make_unique<UrlGuard>(engine.importPathList());
        engine.addUrlInterceptor(guard.get());
    }

    // The objectName of what the QML text made, or "" when it failed.
    QString make(QQmlEngine &engine, const QByteArray &body, const QVariantMap &properties = {})
    {
        QQmlComponent component(&engine);
        component.setData(body, QUrl("qrc:/guard-test.qml"));
        std::unique_ptr<QObject> object(component.createWithInitialProperties(properties));
        if (!object)
            return QString();
        QTest::qWait(50);
        return object->property("result").toString();
    }

private Q_SLOTS:
    void initTestCase()
    {
        QVERIFY(m_dir.isValid());
        hwDropEnvironmentImportPaths();
        m_allowed = QDir(m_dir.path()).filePath("qt-qml");
        m_outside = QDir(m_dir.path()).filePath("elsewhere");
        const QByteArray planted = "import QtQuick\nItem { objectName: \"planted\" }\n";
        write(m_outside + "/Planted.qml", planted);
        write(m_outside + "/planted.js", "function name() { return \"planted\" }\n");
        write(m_allowed + "/Fine/Fine.qml", "import QtQuick\nItem { objectName: \"fine\" }\n");
        write(m_allowed + "/org/kde/kirigami/Page.qml", planted);
        QVERIFY(QFile::link(m_outside, m_allowed + "/link-out"));
        m_store = new ConfigStore(this);
        QVERIFY(m_store->loadSchema(QStringLiteral(HW_MAIN_XML)));
        m_host = new PlasmoidHost(this);
        m_host->setConfiguration(m_store);
        PlasmoidHost::setInstance(m_host);
    }

    void urlTable_data()
    {
        QTest::addColumn<QString>("url");
        QTest::addColumn<bool>("allowed");
        QTest::newRow("qrc module") << "qrc:/qt/qml/Hearthwire/Plasmoid/main.qml" << true;
        QTest::newRow("qrc org/kde") << "qrc:/qt/qml/org/kde/kirigami/Page.qml" << false;
        QTest::newRow("Qt's folder") << "file://" + m_allowed + "/Fine/Fine.qml" << true;
        QTest::newRow("Qt's folder, org/kde") << "file://" + m_allowed + "/org/kde/kirigami/Page.qml" << false;
        QTest::newRow("dot-dot out") << "file://" + m_allowed + "/../elsewhere/Planted.qml" << false;
        QTest::newRow("link out") << "file://" + m_allowed + "/link-out/Planted.qml" << false;
        QTest::newRow("prefix, not folder") << "file://" + m_allowed + "-x/Planted.qml" << false;
        QTest::newRow("elsewhere") << "file://" + m_outside + "/Planted.qml" << false;
        QTest::newRow("system KDE") << "file:///usr/lib/qt6/qml/org/kde/kirigami/qmldir" << false;
        QTest::newRow("network") << "https://example.invalid/x.qml" << false;
        QTest::newRow("data") << "data:text/plain,Item{}" << false;
    }

    void urlTable()
    {
        QFETCH(QString, url);
        QFETCH(bool, allowed);
        UrlGuard guard({QStringLiteral("qrc:/qt/qml"), m_allowed});
        QCOMPARE(guard.allowed(QUrl(url)), allowed);
        for (auto type : {QQmlAbstractUrlInterceptor::QmlFile, QQmlAbstractUrlInterceptor::JavaScriptFile,
                          QQmlAbstractUrlInterceptor::QmldirFile}) {
            if (!allowed)
                QTest::ignoreMessage(QtWarningMsg, Refused);
            QCOMPARE(guard.intercept(QUrl(url), type) == QUrl(url), allowed);
        }
        QCOMPARE(guard.intercept(QUrl(), QQmlAbstractUrlInterceptor::QmlFile), QUrl());
        // Images and other plain URLs are not the guard's business.
        QCOMPARE(guard.intercept(QUrl(url), QQmlAbstractUrlInterceptor::UrlString), QUrl(url));
    }

    void plantedFilesAreRefused_data()
    {
        QTest::addColumn<QByteArray>("body");
        QTest::addColumn<QVariantMap>("properties");
        const QVariantMap target{{"target", fileUrl(m_outside + "/Planted.qml")}};
        QTest::newRow("Loader file:///") << QByteArray(R"(import QtQuick
Item {
    property url target
    property string result: loader.item ? loader.item.objectName : ""
    Loader { id: loader; source: parent.target }
})") << target;
        QTest::newRow("Qt.createComponent") << QByteArray(R"(import QtQuick
Item {
    property url target
    property string result
    Component.onCompleted: {
        var component = Qt.createComponent(target)
        var made = component.status === Component.Ready ? component.createObject(this) : null
        result = made ? made.objectName : ""
    }
})") << target;
        QTest::newRow("string import of a JS file") << ("import QtQuick\nimport \"" + fileUrl(m_outside + "/planted.js").toString().toUtf8()
                                                         + "\" as P\nItem { property string result: P.name() }\n")
                                                    << QVariantMap();
        QTest::newRow("string import of a folder") << ("import QtQuick\nimport \"" + fileUrl(m_outside).toString().toUtf8()
                                                        + "\"\nItem { property string result: planted.objectName; Planted { id: planted } }\n")
                                                   << QVariantMap();
        QTest::newRow("KDE file in Qt's folder") << QByteArray(R"(import QtQuick
Item {
    property url target
    property string result: loader.item ? loader.item.objectName : ""
    Loader { id: loader; source: parent.target }
})") << QVariantMap{{"target", fileUrl(m_allowed + "/org/kde/kirigami/Page.qml")}};
    }

    void plantedFilesAreRefused()
    {
        QFETCH(QByteArray, body);
        QFETCH(QVariantMap, properties);
        {
            // The proof: a plain engine loads the planted file.
            QQmlEngine engine;
            std::unique_ptr<UrlGuard> none;
            setUp(engine, none, false);
            QCOMPARE(make(engine, body, properties), QStringLiteral("planted"));
        }
        std::unique_ptr<UrlGuard> guard;
        QQmlEngine engine;
        setUp(engine, guard, true);
        QTest::ignoreMessage(QtWarningMsg, Refused);
        QCOMPARE(make(engine, body, properties), QString());
    }

    // What the app needs still loads: a stand-in from qrc:, Qt's own
    // modules from Qt's folder, and a file in an allowed folder.
    void theAppsModulesStillLoad()
    {
        std::unique_ptr<UrlGuard> guard;
        QQmlEngine engine;
        setUp(engine, guard, true);
        QTest::failOnWarning(QRegularExpression("refused"));
        QCOMPARE(make(engine, R"(import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import Hearthwire.Compat.Plasmoid
Item { property string result: "id " + Plasmoid.id; RowLayout { Button { text: "x" } } })"),
                 QStringLiteral("id 2147483648"));
        QCOMPARE(make(engine, R"(import QtQuick
Item {
    property url target
    property string result: loader.item ? loader.item.objectName : ""
    Loader { id: loader; source: parent.target }
})", {{"target", fileUrl(m_allowed + "/Fine/Fine.qml")}}),
                 QStringLiteral("fine"));
    }
};

QTEST_MAIN(TestUrlGuard)
#include "tst_urlguard.moc"
