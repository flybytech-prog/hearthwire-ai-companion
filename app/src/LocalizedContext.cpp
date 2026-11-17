#include "LocalizedContext.h"

namespace {
QVariantList list(const QVariant &a1, const QVariant &a2, const QVariant &a3, const QVariant &a4,
                  const QVariant &a5, const QVariant &a6, const QVariant &a7, const QVariant &a8,
                  const QVariant &a9)
{
    return {a1, a2, a3, a4, a5, a6, a7, a8, a9};
}

QString shown(const QVariant &value)
{
    // Whole doubles read as integers, like KLocalizedString's number args.
    if (value.typeId() == QMetaType::Double) {
        const double number = value.toDouble();
        if (number == double(qint64(number)))
            return QString::number(qint64(number));
    }
    return value.toString();
}
}

QString LocalizedContext::substitute(const QString &text, const QVariantList &args)
{
    QString result;
    result.reserve(text.size());
    for (qsizetype i = 0; i < text.size(); ++i) {
        const QChar c = text.at(i);
        if (c == QLatin1Char('%') && i + 1 < text.size() && text.at(i + 1).isDigit()) {
            const int index = text.at(i + 1).digitValue();
            if (index >= 1 && index <= args.size() && args.at(index - 1).isValid()) {
                result += shown(args.at(index - 1));
                ++i;
                continue;
            }
        }
        result += c;
    }
    return result;
}

#define HW_LIST list(a1, a2, a3, a4, a5, a6, a7, a8, a9)
#define HW_PARAMS const QVariant &a1, const QVariant &a2, const QVariant &a3, const QVariant &a4, \
    const QVariant &a5, const QVariant &a6, const QVariant &a7, const QVariant &a8, const QVariant &a9

QString LocalizedContext::i18n(const QString &text, HW_PARAMS) const
{
    return substitute(text, HW_LIST);
}

QString LocalizedContext::i18nc(const QString &, const QString &text, HW_PARAMS) const
{
    return substitute(text, HW_LIST);
}

QString LocalizedContext::i18np(const QString &singular, const QString &plural, HW_PARAMS) const
{
    return substitute(a1.toLongLong() == 1 ? singular : plural, HW_LIST);
}

QString LocalizedContext::i18ncp(const QString &, const QString &singular, const QString &plural, HW_PARAMS) const
{
    return substitute(a1.toLongLong() == 1 ? singular : plural, HW_LIST);
}

QString LocalizedContext::i18nd(const QString &, const QString &text, HW_PARAMS) const
{
    return substitute(text, HW_LIST);
}

QString LocalizedContext::i18ndc(const QString &, const QString &, const QString &text, HW_PARAMS) const
{
    return substitute(text, HW_LIST);
}
