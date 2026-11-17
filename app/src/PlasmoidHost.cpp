#include "PlasmoidHost.h"

#include "ConfigStore.h"

namespace {
PlasmoidHost *s_host = nullptr;
}

HostAction::HostAction(const QString &name, QObject *parent)
    : QObject(parent)
    , m_name(name)
{
}

PlasmoidHost::PlasmoidHost(QObject *parent)
    : QObject(parent)
{
}

PlasmoidHost *PlasmoidHost::instance()
{
    return s_host;
}

void PlasmoidHost::setInstance(PlasmoidHost *host)
{
    s_host = host;
}

PlasmoidHost *PlasmoidHost::qmlAttachedProperties(QObject *)
{
    return s_host;
}

QObject *PlasmoidHost::configuration() const
{
    return m_configuration;
}

QQmlListProperty<QObject> PlasmoidHost::contextualActions()
{
    return QQmlListProperty<QObject>(this, nullptr, &appendAction, &actionCount, &actionAt, &clearActions);
}

HostAction *PlasmoidHost::internalAction(const QString &name)
{
    if (name != QLatin1String("configure"))
        return nullptr;
    if (!m_configure) {
        m_configure = new HostAction(name, this);
        connect(m_configure, &HostAction::triggered, this, &PlasmoidHost::configureRequested);
    }
    return m_configure;
}

QList<QObject *> PlasmoidHost::actions() const
{
    QList<QObject *> alive;
    for (const QPointer<QObject> &action : m_actions) {
        if (action)
            alive.append(action.data());
    }
    return alive;
}

void PlasmoidHost::appendAction(QQmlListProperty<QObject> *list, QObject *action)
{
    auto *host = static_cast<PlasmoidHost *>(list->object);
    host->m_actions.removeAll(QPointer<QObject>());
    if (action)
        host->m_actions.append(action);
    Q_EMIT host->contextualActionsChanged();
}

qsizetype PlasmoidHost::actionCount(QQmlListProperty<QObject> *list)
{
    return static_cast<PlasmoidHost *>(list->object)->actions().size();
}

QObject *PlasmoidHost::actionAt(QQmlListProperty<QObject> *list, qsizetype index)
{
    return static_cast<PlasmoidHost *>(list->object)->actions().value(index);
}

void PlasmoidHost::clearActions(QQmlListProperty<QObject> *list)
{
    auto *host = static_cast<PlasmoidHost *>(list->object);
    host->m_actions.clear();
    Q_EMIT host->contextualActionsChanged();
}
