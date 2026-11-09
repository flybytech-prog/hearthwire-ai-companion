// The stand-in for org.kde.plasma.plasmoid that lets the real main.qml load
// under qmltestrunner. `Plasmoid.icon: ...` in main.qml is an attached
// property, and only C++ can define one: a QML singleton named Plasmoid is
// refused with "Non-existent attached object". tests/test_main_qml_wiring.py
// builds this into a temporary copy of stubs/; nothing here touches a real
// applet, the session bus or the helper.

#include <QFile>
#include <QHash>
#include <QList>
#include <QObject>
#include <QQmlExtensionPlugin>
#include <QQmlListProperty>
#include <QQmlPropertyMap>
#include <QUrl>
#include <QVariant>
#include <QXmlStreamReader>
#include <QtQml>

class PlasmoidStub : public QObject
{
    Q_OBJECT
    Q_PROPERTY(int id READ id CONSTANT)
    Q_PROPERTY(QObject *configuration READ configuration CONSTANT)
    Q_PROPERTY(QVariant icon MEMBER m_icon NOTIFY changed)
    Q_PROPERTY(bool busy MEMBER m_busy NOTIFY changed)
    Q_PROPERTY(int formFactor MEMBER m_formFactor NOTIFY changed)
    Q_PROPERTY(QQmlListProperty<QObject> contextualActions READ contextualActions CONSTANT)
    QML_ATTACHED(PlasmoidStub)

public:
    explicit PlasmoidStub(QObject *parent = nullptr)
        : QObject(parent)
        , m_configuration(QQmlPropertyMap::create(this))
    {
    }

    // One object for the whole test, as Plasma hands every item its applet.
    static PlasmoidStub *qmlAttachedProperties(QObject *)
    {
        static PlasmoidStub *shared = new PlasmoidStub;
        return shared;
    }

    int id() const { return 7; }
    QObject *configuration() const { return m_configuration; }
    QQmlListProperty<QObject> contextualActions() { return QQmlListProperty<QObject>(this, &m_actions); }

    // Fills the configuration with main.xml's entries and defaults, as
    // KConfigXT does; false for a file or an entry type it can't read.
    Q_INVOKABLE bool loadSchema(const QUrl &url)
    {
        QFile file(url.toLocalFile());
        if (!file.open(QIODevice::ReadOnly))
            return false;
        QHash<QString, QVariant> values;
        QXmlStreamReader xml(&file);
        QString name;
        QString type;
        while (!xml.atEnd()) {
            xml.readNext();
            if (!xml.isStartElement())
                continue;
            if (xml.name() == QLatin1String("entry")) {
                name = xml.attributes().value(QLatin1String("name")).toString();
                type = xml.attributes().value(QLatin1String("type")).toString();
                values.insert(name, emptyValue(type));
            } else if (xml.name() == QLatin1String("default") && !name.isEmpty()) {
                values.insert(name, typedValue(type, xml.readElementText()));
            }
        }
        if (xml.hasError() || values.isEmpty())
            return false;
        for (auto entry = values.constBegin(); entry != values.constEnd(); ++entry) {
            if (!entry.value().isValid())
                return false;
            m_configuration->insert(entry.key(), entry.value());
        }
        return true;
    }

    // The real applet's actions are never triggered in these tests.
    Q_INVOKABLE QObject *internalAction(const QString &) { return nullptr; }

Q_SIGNALS:
    void changed();
    void activated();

private:
    static QVariant emptyValue(const QString &type)
    {
        return typedValue(type, QString());
    }

    static QVariant typedValue(const QString &type, const QString &text)
    {
        if (type == QLatin1String("String"))
            return text;
        if (type == QLatin1String("Int"))
            return text.toInt();
        if (type == QLatin1String("Bool"))
            return text == QLatin1String("true");
        return QVariant();
    }

    QQmlPropertyMap *m_configuration;
    QVariant m_icon;
    bool m_busy = false;
    int m_formFactor = 0;
    QList<QObject *> m_actions;
};

QML_DECLARE_TYPE(PlasmoidStub)

class PlasmoidStubPlugin : public QQmlExtensionPlugin
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID QQmlExtensionInterface_iid)

public:
    void registerTypes(const char *uri) override
    {
        qmlRegisterUncreatableType<PlasmoidStub>(uri, 1, 0, "Plasmoid", QStringLiteral("attached only"));
    }
};

#include "plasmoidstub.moc"
