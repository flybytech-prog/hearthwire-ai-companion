// The `Plasmoid` attached object of Hearthwire.Compat.Plasmoid: one host for
// the whole app, as Plasma hands every item of an applet the same applet.
// Only the names the plasmoid uses (plan-v1 §2.2): configuration, id, icon,
// busy, formFactor, contextualActions, internalAction().
// id is the app's reserved applet id (core/frontend.py APP_APPLET_ID, 2**31):
// the helper takes only that id in app mode and refuses it in Plasma mode,
// so the app's chat profiles and usage history never mix with a widget's.
#pragma once

#include <QList>
#include <QObject>
#include <QPointer>
#include <QQmlListProperty>
#include <QVariant>
#include <QtQml/qqmlregistration.h>

class ConfigStore;

// What internalAction() returns; trigger() asks the window to act.
class HostAction : public QObject
{
    Q_OBJECT
    QML_ANONYMOUS
    Q_PROPERTY(QString name READ name CONSTANT)

public:
    HostAction(const QString &name, QObject *parent);
    QString name() const { return m_name; }
    Q_INVOKABLE void trigger() { Q_EMIT triggered(); }

Q_SIGNALS:
    void triggered();

private:
    QString m_name;
};

class PlasmoidHost : public QObject
{
    Q_OBJECT
    QML_NAMED_ELEMENT(Plasmoid)
    QML_UNCREATABLE("Plasmoid is attached only")
    QML_ATTACHED(PlasmoidHost)
    Q_PROPERTY(qint64 id READ id CONSTANT)
    Q_PROPERTY(QObject *configuration READ configuration CONSTANT)
    Q_PROPERTY(QVariant icon MEMBER m_icon NOTIFY iconChanged)
    Q_PROPERTY(bool busy MEMBER m_busy NOTIFY busyChanged)
    // Plasma::Types::Planar: the app window is no panel.
    Q_PROPERTY(int formFactor READ formFactor CONSTANT)
    Q_PROPERTY(QQmlListProperty<QObject> contextualActions READ contextualActions NOTIFY contextualActionsChanged)

public:
    explicit PlasmoidHost(QObject *parent = nullptr);

    static PlasmoidHost *instance();
    static void setInstance(PlasmoidHost *host);
    static PlasmoidHost *qmlAttachedProperties(QObject *);

    void setConfiguration(ConfigStore *store) { m_configuration = store; }
    static constexpr qint64 AppAppletId = qint64(1) << 31;
    qint64 id() const { return AppAppletId; }
    QObject *configuration() const;
    int formFactor() const { return 0; }
    QQmlListProperty<QObject> contextualActions();
    // The actions still alive (main.qml's items go away with main.qml).
    QList<QObject *> actions() const;

    // "configure" opens Settings; any other name gets no action, like an
    // applet without it (kiosk).
    Q_INVOKABLE HostAction *internalAction(const QString &name);

Q_SIGNALS:
    void iconChanged();
    void busyChanged();
    void contextualActionsChanged();
    void configureRequested();
    // Plasma: the applet's global shortcut. The app never sends it: a later
    // launch (--toggle/--tab) goes through AppWindow.qml's Show/Toggle
    // handling; Settings' shortcutOpens is panel-only (R4 hides that row).
    void activated();

private:
    static void appendAction(QQmlListProperty<QObject> *list, QObject *action);
    static qsizetype actionCount(QQmlListProperty<QObject> *list);
    static QObject *actionAt(QQmlListProperty<QObject> *list, qsizetype index);
    static void clearActions(QQmlListProperty<QObject> *list);

    ConfigStore *m_configuration = nullptr;
    QVariant m_icon;
    bool m_busy = false;
    // Not owned: main.qml's PlasmaCore.Action objects.
    QList<QPointer<QObject>> m_actions;
    HostAction *m_configure = nullptr;
};
