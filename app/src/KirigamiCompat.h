// The attached parts of Hearthwire.Compat.Kirigami, which only C++ can
// define: Theme, FormData and SpellCheck, plus FormSupport, which lets the
// QML FormLayout read the FormData of its children.
//
// Theme's colours come from ThemePalette: the Omarchy theme the app's
// ThemeWatcher hands it (main.cpp), else the built-in palette, dark or
// light as the system colour scheme says. Every Kirigami colour set has its
// own colours (ThemeWatcher.cpp, derive()); colorSet and inherit work as in
// Kirigami: an item's colorSet, once set, is its own, otherwise it follows
// the nearest ancestor with a Theme (inherit: true) or is Window.
#pragma once

#include <QColor>
#include <QFont>
#include <QObject>
#include <QPointer>
#include <QQuickItem>
#include <QtQml/qqmlregistration.h>

#include <optional>

#include "ThemeWatcher.h"

class ThemePalette : public QObject
{
    Q_OBJECT
public:
    static ThemePalette *instance();
    bool dark() const { return m_palette.dark; }
    QColor color(HwTheme::Set set, HwTheme::Role role) const { return m_palette.color(set, role); }
    // The Omarchy theme to show, or nullopt for the built-in palette.
    void setTheme(const std::optional<HwTheme::Source> &source);

Q_SIGNALS:
    void changed();

private:
    ThemePalette();
    void update();

    std::optional<HwTheme::Source> m_theme;
    HwTheme::Palette m_palette;
};

class Theme : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    QML_UNCREATABLE("Theme is attached only")
    QML_ATTACHED(Theme)
    Q_PROPERTY(ColorSet colorSet READ colorSet WRITE setColorSet NOTIFY colorSetChanged)
    Q_PROPERTY(bool inherit READ inherit WRITE setInherit NOTIFY inheritChanged)
    Q_PROPERTY(bool dark READ dark NOTIFY paletteChanged)
    Q_PROPERTY(QColor textColor READ textColor NOTIFY paletteChanged)
    Q_PROPERTY(QColor disabledTextColor READ disabledTextColor NOTIFY paletteChanged)
    Q_PROPERTY(QColor highlightedTextColor READ highlightedTextColor NOTIFY paletteChanged)
    Q_PROPERTY(QColor activeTextColor READ activeTextColor NOTIFY paletteChanged)
    Q_PROPERTY(QColor linkColor READ linkColor NOTIFY paletteChanged)
    Q_PROPERTY(QColor visitedLinkColor READ visitedLinkColor NOTIFY paletteChanged)
    Q_PROPERTY(QColor negativeTextColor READ negativeTextColor NOTIFY paletteChanged)
    Q_PROPERTY(QColor neutralTextColor READ neutralTextColor NOTIFY paletteChanged)
    Q_PROPERTY(QColor positiveTextColor READ positiveTextColor NOTIFY paletteChanged)
    Q_PROPERTY(QColor backgroundColor READ backgroundColor NOTIFY paletteChanged)
    Q_PROPERTY(QColor alternateBackgroundColor READ alternateBackgroundColor NOTIFY paletteChanged)
    Q_PROPERTY(QColor highlightColor READ highlightColor NOTIFY paletteChanged)
    Q_PROPERTY(QColor activeBackgroundColor READ activeBackgroundColor NOTIFY paletteChanged)
    Q_PROPERTY(QColor linkBackgroundColor READ linkBackgroundColor NOTIFY paletteChanged)
    Q_PROPERTY(QColor visitedLinkBackgroundColor READ visitedLinkBackgroundColor NOTIFY paletteChanged)
    Q_PROPERTY(QColor negativeBackgroundColor READ negativeBackgroundColor NOTIFY paletteChanged)
    Q_PROPERTY(QColor neutralBackgroundColor READ neutralBackgroundColor NOTIFY paletteChanged)
    Q_PROPERTY(QColor positiveBackgroundColor READ positiveBackgroundColor NOTIFY paletteChanged)
    Q_PROPERTY(QColor focusColor READ focusColor NOTIFY paletteChanged)
    Q_PROPERTY(QColor hoverColor READ hoverColor NOTIFY paletteChanged)
    Q_PROPERTY(QFont defaultFont READ defaultFont NOTIFY paletteChanged)
    Q_PROPERTY(QFont smallFont READ smallFont NOTIFY paletteChanged)
    Q_PROPERTY(QFont fixedWidthFont READ fixedWidthFont NOTIFY paletteChanged)

public:
    // Kirigami's values, same order.
    enum ColorSet { View = 0, Window, Button, Selection, Tooltip, Complementary, Header };
    Q_ENUM(ColorSet)

    explicit Theme(QObject *parent = nullptr);
    static Theme *qmlAttachedProperties(QObject *object) { return new Theme(object); }

    // The set in effect (what QML reads as colorSet).
    ColorSet colorSet() const;
    void setColorSet(ColorSet set);
    bool inherit() const { return m_inherit; }
    void setInherit(bool inherit);

    bool dark() const { return ThemePalette::instance()->dark(); }
    QColor textColor() const { return color(HwTheme::TextColor); }
    QColor disabledTextColor() const { return color(HwTheme::DisabledTextColor); }
    QColor highlightedTextColor() const { return color(HwTheme::HighlightedTextColor); }
    QColor activeTextColor() const { return color(HwTheme::ActiveTextColor); }
    QColor linkColor() const { return color(HwTheme::LinkColor); }
    QColor visitedLinkColor() const { return color(HwTheme::VisitedLinkColor); }
    QColor negativeTextColor() const { return color(HwTheme::NegativeTextColor); }
    QColor neutralTextColor() const { return color(HwTheme::NeutralTextColor); }
    QColor positiveTextColor() const { return color(HwTheme::PositiveTextColor); }
    QColor backgroundColor() const { return color(HwTheme::BackgroundColor); }
    QColor alternateBackgroundColor() const { return color(HwTheme::AlternateBackgroundColor); }
    QColor highlightColor() const { return color(HwTheme::HighlightColor); }
    QColor activeBackgroundColor() const { return color(HwTheme::ActiveBackgroundColor); }
    QColor linkBackgroundColor() const { return color(HwTheme::LinkBackgroundColor); }
    QColor visitedLinkBackgroundColor() const { return color(HwTheme::VisitedLinkBackgroundColor); }
    QColor negativeBackgroundColor() const { return color(HwTheme::NegativeBackgroundColor); }
    QColor neutralBackgroundColor() const { return color(HwTheme::NeutralBackgroundColor); }
    QColor positiveBackgroundColor() const { return color(HwTheme::PositiveBackgroundColor); }
    QColor focusColor() const { return color(HwTheme::FocusColor); }
    QColor hoverColor() const { return color(HwTheme::HoverColor); }
    QFont defaultFont() const;
    QFont smallFont() const;
    QFont fixedWidthFont() const;

Q_SIGNALS:
    void colorSetChanged();
    void inheritChanged();
    void paletteChanged();

private:
    QColor color(HwTheme::Role role) const
    {
        return ThemePalette::instance()->color(HwTheme::Set(colorSet()), role);
    }
    void refresh();

    ColorSet m_colorSet = Window;
    bool m_ownSet = false;
    bool m_inherit = true;
};

class FormData : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    QML_UNCREATABLE("FormData is attached only")
    QML_ATTACHED(FormData)
    Q_PROPERTY(QString label MEMBER m_label NOTIFY changed)
    Q_PROPERTY(bool isSection MEMBER m_isSection NOTIFY changed)
    Q_PROPERTY(QQuickItem *buddyFor MEMBER m_buddyFor NOTIFY changed)
    Q_PROPERTY(int labelAlignment MEMBER m_labelAlignment NOTIFY changed)

public:
    explicit FormData(QObject *parent = nullptr) : QObject(parent) {}
    static FormData *qmlAttachedProperties(QObject *object) { return new FormData(object); }

Q_SIGNALS:
    void changed();

private:
    QString m_label;
    bool m_isSection = false;
    QPointer<QQuickItem> m_buddyFor;
    int m_labelAlignment = 0;
};

class SpellCheck : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    QML_UNCREATABLE("SpellCheck is attached only")
    QML_ATTACHED(SpellCheck)
    // Kept only; the app has no spell checker.
    Q_PROPERTY(bool enabled MEMBER m_enabled NOTIFY enabledChanged)

public:
    explicit SpellCheck(QObject *parent = nullptr) : QObject(parent) {}
    static SpellCheck *qmlAttachedProperties(QObject *object) { return new SpellCheck(object); }

Q_SIGNALS:
    void enabledChanged();

private:
    bool m_enabled = false;
};

class FormSupport : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON

public:
    explicit FormSupport(QObject *parent = nullptr) : QObject(parent) {}
    // The item's FormData, or null when it has none.
    Q_INVOKABLE FormData *formData(QObject *item) const;
    // Writes an attached property such as "Layout.columnSpan" of item, with
    // the type names of `scope`'s QML file; false if it can't.
    Q_INVOKABLE bool setAttached(QObject *item, const QString &name, const QVariant &value, QObject *scope) const;
};
