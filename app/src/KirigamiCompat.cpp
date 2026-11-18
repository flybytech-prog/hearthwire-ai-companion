#include "KirigamiCompat.h"

#include <QFontDatabase>
#include <QGuiApplication>
#include <QQmlContext>
#include <QQmlEngine>
#include <QQmlProperty>
#include <QStyleHints>

static_assert(int(Theme::View) == HwTheme::View && int(Theme::Window) == HwTheme::Window
                  && int(Theme::Button) == HwTheme::Button && int(Theme::Selection) == HwTheme::Selection
                  && int(Theme::Tooltip) == HwTheme::Tooltip && int(Theme::Complementary) == HwTheme::Complementary
                  && int(Theme::Header) == HwTheme::Header,
              "Theme::ColorSet and HwTheme::Set must match");

namespace {
bool systemDark()
{
    return QGuiApplication::styleHints()->colorScheme() != Qt::ColorScheme::Light;
}
}

ThemePalette::ThemePalette()
{
    m_palette = HwTheme::derive(HwTheme::builtIn(systemDark()));
    connect(QGuiApplication::styleHints(), &QStyleHints::colorSchemeChanged, this, &ThemePalette::update);
}

ThemePalette *ThemePalette::instance()
{
    static ThemePalette *shared = new ThemePalette;
    return shared;
}

void ThemePalette::setTheme(const std::optional<HwTheme::Source> &source)
{
    m_theme = source;
    update();
}

void ThemePalette::update()
{
    const HwTheme::Palette palette = HwTheme::derive(m_theme ? *m_theme : HwTheme::builtIn(systemDark()));
    if (palette == m_palette)
        return;
    m_palette = palette;
    Q_EMIT changed();
}

Theme::Theme(QObject *parent)
    : QObject(parent)
{
    // A colour set change anywhere can change what an inheriting item shows.
    connect(ThemePalette::instance(), &ThemePalette::changed, this, &Theme::refresh);
    if (auto *item = qobject_cast<QQuickItem *>(parent))
        connect(item, &QQuickItem::parentChanged, this, &Theme::refresh);
}

void Theme::refresh()
{
    Q_EMIT colorSetChanged();
    Q_EMIT paletteChanged();
}

Theme::ColorSet Theme::colorSet() const
{
    if (m_ownSet)
        return m_colorSet;
    if (!m_inherit)
        return Window;
    QObject *object = parent();
    auto *item = qobject_cast<QQuickItem *>(object);
    QObject *ancestor = item ? static_cast<QObject *>(item->parentItem()) : (object ? object->parent() : nullptr);
    while (ancestor) {
        if (auto *theme = qobject_cast<Theme *>(qmlAttachedPropertiesObject<Theme>(ancestor, false)))
            return theme->colorSet();
        auto *ancestorItem = qobject_cast<QQuickItem *>(ancestor);
        ancestor = ancestorItem ? static_cast<QObject *>(ancestorItem->parentItem()) : ancestor->parent();
    }
    return Window;
}

void Theme::setColorSet(ColorSet set)
{
    if (m_ownSet && m_colorSet == set)
        return;
    m_ownSet = true;
    m_colorSet = set;
    // Items below that inherit change too.
    Q_EMIT ThemePalette::instance()->changed();
}

void Theme::setInherit(bool inherit)
{
    if (m_inherit == inherit)
        return;
    m_inherit = inherit;
    Q_EMIT inheritChanged();
    Q_EMIT ThemePalette::instance()->changed();
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
