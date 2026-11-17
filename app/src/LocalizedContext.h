// i18n(), i18nc(), i18np(), i18ncp(), i18nd(), i18ndc() for the shared QML,
// set as the root context object like KLocalizedContext. English only:
// %1..%9 are replaced with the arguments; i18np picks the form from the
// first argument. SPIKE: no wording overrides yet (app/wording, later).
#pragma once

#include <QObject>
#include <QVariant>

class LocalizedContext : public QObject
{
    Q_OBJECT

public:
    explicit LocalizedContext(QObject *parent = nullptr) : QObject(parent) {}

#define HW_ARGS const QVariant &a1 = {}, const QVariant &a2 = {}, const QVariant &a3 = {}, \
    const QVariant &a4 = {}, const QVariant &a5 = {}, const QVariant &a6 = {}, \
    const QVariant &a7 = {}, const QVariant &a8 = {}, const QVariant &a9 = {}
    Q_INVOKABLE QString i18n(const QString &text, HW_ARGS) const;
    Q_INVOKABLE QString i18nc(const QString &context, const QString &text, HW_ARGS) const;
    Q_INVOKABLE QString i18np(const QString &singular, const QString &plural, HW_ARGS) const;
    Q_INVOKABLE QString i18ncp(const QString &context, const QString &singular, const QString &plural, HW_ARGS) const;
    Q_INVOKABLE QString i18nd(const QString &domain, const QString &text, HW_ARGS) const;
    Q_INVOKABLE QString i18ndc(const QString &domain, const QString &context, const QString &text, HW_ARGS) const;
#undef HW_ARGS

    static QString substitute(const QString &text, const QVariantList &args);
};
