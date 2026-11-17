#include "KirigamiCompat.h"

#include <QFontDatabase>
#include <QGuiApplication>
#include <QHash>
#include <QQmlContext>
#include <QQmlEngine>
#include <QQmlProperty>

namespace {
// Material-like palettes; the real colors will come from ThemeWatcher.
const QHash<QByteArray, QColor> &palette(bool dark)
{
    static const QHash<QByteArray, QColor> darkColors = {
        {"textColor", QColor(0xe6, 0xe1, 0xe5)},
        {"disabledTextColor", QColor(0x93, 0x8f, 0x99)},
        {"highlightedTextColor", QColor(0x1c, 0x1b, 0x1f)},
        {"activeTextColor", QColor(0x8a, 0xb4, 0xf8)},
        {"linkColor", QColor(0x8a, 0xb4, 0xf8)},
        {"visitedLinkColor", QColor(0xc5, 0x8a, 0xf9)},
        {"negativeTextColor", QColor(0xf2, 0x8b, 0x82)},
        {"neutralTextColor", QColor(0xfd, 0xd6, 0x63)},
        {"positiveTextColor", QColor(0x81, 0xc9, 0x95)},
        {"backgroundColor", QColor(0x1c, 0x1b, 0x1f)},
        {"alternateBackgroundColor", QColor(0x2b, 0x29, 0x30)},
        {"highlightColor", QColor(0x8a, 0xb4, 0xf8)},
        {"activeBackgroundColor", QColor(0x8a, 0xb4, 0xf8)},
        {"linkBackgroundColor", QColor(0x2b, 0x39, 0x52)},
        {"visitedLinkBackgroundColor", QColor(0x3d, 0x2b, 0x52)},
        {"negativeBackgroundColor", QColor(0x52, 0x2b, 0x2b)},
        {"neutralBackgroundColor", QColor(0x52, 0x46, 0x2b)},
        {"positiveBackgroundColor", QColor(0x2b, 0x52, 0x36)},
        {"focusColor", QColor(0x8a, 0xb4, 0xf8)},
        {"hoverColor", QColor(0x8a, 0xb4, 0xf8)},
    };
    static const QHash<QByteArray, QColor> lightColors = {
        {"textColor", QColor(0x1c, 0x1b, 0x1f)},
        {"disabledTextColor", QColor(0x79, 0x74, 0x7e)},
        {"highlightedTextColor", QColor(0xff, 0xff, 0xff)},
        {"activeTextColor", QColor(0x1a, 0x73, 0xe8)},
        {"linkColor", QColor(0x1a, 0x73, 0xe8)},
        {"visitedLinkColor", QColor(0x7b, 0x1f, 0xa2)},
        {"negativeTextColor", QColor(0xc5, 0x22, 0x1f)},
        {"neutralTextColor", QColor(0xb0, 0x60, 0x00)},
        {"positiveTextColor", QColor(0x18, 0x80, 0x38)},
        {"backgroundColor", QColor(0xfe, 0xfb, 0xff)},
        {"alternateBackgroundColor", QColor(0xf1, 0xee, 0xf4)},
        {"highlightColor", QColor(0x1a, 0x73, 0xe8)},
        {"activeBackgroundColor", QColor(0x1a, 0x73, 0xe8)},
        {"linkBackgroundColor", QColor(0xd2, 0xe3, 0xfc)},
        {"visitedLinkBackgroundColor", QColor(0xe9, 0xd5, 0xf5)},
        {"negativeBackgroundColor", QColor(0xfc, 0xe8, 0xe6)},
        {"neutralBackgroundColor", QColor(0xfe, 0xf7, 0xe0)},
        {"positiveBackgroundColor", QColor(0xe6, 0xf4, 0xea)},
        {"focusColor", QColor(0x1a, 0x73, 0xe8)},
        {"hoverColor", QColor(0x1a, 0x73, 0xe8)},
    };
    return dark ? darkColors : lightColors;
}
}

ThemePalette::ThemePalette()
{
    m_dark = qEnvironmentVariable("HEARTHWIRE_THEME") != QLatin1String("light");
}

ThemePalette *ThemePalette::instance()
{
    static ThemePalette *shared = new ThemePalette;
    return shared;
}

QColor ThemePalette::color(const char *role) const
{
    return palette(m_dark).value(QByteArray(role));
}

Theme::Theme(QObject *parent)
    : QObject(parent)
{
    connect(ThemePalette::instance(), &ThemePalette::changed, this, &Theme::paletteChanged);
}

QFont Theme::defaultFont() const
{
    return QGuiApplication::font();
}

QFont Theme::smallFont() const
{
    QFont font = QGuiApplication::font();
    if (font.pointSizeF() > 0)
        font.setPointSizeF(font.pointSizeF() * 0.8);
    else
        font.setPixelSize(qMax(1, int(font.pixelSize() * 0.8)));
    return font;
}

QFont Theme::fixedWidthFont() const
{
    return QFontDatabase::systemFont(QFontDatabase::FixedFont);
}

FormData *FormSupport::formData(QObject *item) const
{
    if (!item)
        return nullptr;
    return qobject_cast<FormData *>(qmlAttachedPropertiesObject<FormData>(item, false));
}

bool FormSupport::setAttached(QObject *item, const QString &name, const QVariant &value, QObject *scope) const
{
    QQmlContext *context = scope ? qmlContext(scope) : nullptr;
    if (!item || !context)
        return false;
    QQmlProperty property(item, name, context);
    return property.isValid() && property.write(value);
}
