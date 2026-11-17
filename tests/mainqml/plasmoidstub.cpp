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
#include <QStringList>
#include <QUrl>
#include <QVariant>
#include <QXmlStreamReader>
#include <QtQml>

class PlasmoidStub;

// Plasma's "configure" action, when a test asks for one: trigger() only
// records itself and what backupRestoreAt held at that moment.
class ActionStub : public QObject
{
    Q_OBJECT

public:
    ActionStub(PlasmoidStub *owner, const QString &name);
    Q_INVOKABLE void trigger();

private:
    PlasmoidStub *m_owner;
    QString m_name;
};

class PlasmoidStub : public QObject
{
    Q_OBJECT
    // 7 unless a test sets another; tst_main_wiring.qml puts it back in init().
    Q_PROPERTY(qint64 id MEMBER m_id NOTIFY idChanged)
    Q_PROPERTY(QObject *configuration READ configuration CONSTANT)
    Q_PROPERTY(QVariant icon MEMBER m_icon NOTIFY changed)
    Q_PROPERTY(bool busy MEMBER m_busy NOTIFY changed)
    Q_PROPERTY(int formFactor MEMBER m_formFactor NOTIFY changed)
    Q_PROPERTY(QQmlListProperty<QObject> contextualActions READ contextualActions CONSTANT)
    // false (kiosk: no actions) unless a test sets it; put back in init().
    Q_PROPERTY(bool actionsAvailable MEMBER m_actionsAvailable NOTIFY changed)
    // Each trigger() as "name" and backupRestoreAt at that moment.
    Q_PROPERTY(QStringList triggered MEMBER m_triggered NOTIFY changed)
    Q_PROPERTY(QStringList triggeredRestoreAt MEMBER m_triggeredRestoreAt NOTIFY changed)
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

    // The real applet's actions are never triggered in these tests; with
    // actionsAvailable a stand-in records the trigger instead.
    Q_INVOKABLE QObject *internalAction(const QString &name)
    {
        if (!m_actionsAvailable)
            return nullptr;
        return new ActionStub(this, name);
    }

    // What real Plasma 6 does on each Apply and after the widget's own
    // writes: valueChanged for every key, changed or not (a plain
    // QQmlPropertyMap is silent for an unchanged write). backupAutoExport
    // comes last, as in the lab's log.
    Q_INVOKABLE void reemitAll()
    {
        const QString last = QStringLiteral("backupAutoExport");
        const QStringList keys = m_configuration->keys();
        for (const QString &key : keys) {
            if (key != last)
                Q_EMIT m_configuration->valueChanged(key, m_configuration->value(key));
        }
        if (m_configuration->contains(last))
            Q_EMIT m_configuration->valueChanged(last, m_configuration->value(last));
    }

    void recordTrigger(const QString &name)
    {
        m_triggered.append(name);
        m_triggeredRestoreAt.append(m_configuration->value(QStringLiteral("backupRestoreAt")).toString());
        Q_EMIT changed();
    }

Q_SIGNALS:
    void changed();
    void idChanged();
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
    // 64-bit: the hearthwire-hyprland app's id is 2147483648 (2**31).
    qint64 m_id = 7;
    QVariant m_icon;
    bool m_busy = false;
    int m_formFactor = 0;
    QList<QObject *> m_actions;
    bool m_actionsAvailable = false;
    QStringList m_triggered;
    QStringList m_triggeredRestoreAt;
};

ActionStub::ActionStub(PlasmoidStub *owner, const QString &name)
    : QObject(owner)
    , m_owner(owner)
    , m_name(name)
{
}

void ActionStub::trigger()
{
    m_owner->recordTrigger(m_name);
}

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
