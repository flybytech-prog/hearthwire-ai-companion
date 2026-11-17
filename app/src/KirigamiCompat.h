// The attached parts of Hearthwire.Compat.Kirigami, which only C++ can
// define: Theme, FormData and SpellCheck, plus FormSupport, which lets the
// QML FormLayout read the FormData of its children.
//
// SPIKE: one app palette (dark unless HEARTHWIRE_THEME=light); colorSet and
// inherit are kept but do not change the colors yet (ThemeWatcher, later).
#pragma once

#include <QColor>
#include <QFont>
#include <QObject>
#include <QPointer>
#include <QQuickItem>
#include <QtQml/qqmlregistration.h>

class ThemePalette : public QObject
{
    Q_OBJECT
public:
    static ThemePalette *instance();
    bool dark() const { return m_dark; }
    QColor color(const char *role) const;

Q_SIGNALS:
    void changed();

private:
    ThemePalette();
    bool m_dark = true;
};

class Theme : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    QML_UNCREATABLE("Theme is attached only")
    QML_ATTACHED(Theme)
    Q_PROPERTY(ColorSet colorSet MEMBER m_colorSet NOTIFY colorSetChanged)
    Q_PROPERTY(bool inherit MEMBER m_inherit NOTIFY inheritChanged)
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

    bool dark() const { return ThemePalette::instance()->dark(); }
    QColor textColor() const { return ThemePalette::instance()->color("textColor"); }
    QColor disabledTextColor() const { return ThemePalette::instance()->color("disabledTextColor"); }
    QColor highlightedTextColor() const { return ThemePalette::instance()->color("highlightedTextColor"); }
    QColor activeTextColor() const { return ThemePalette::instance()->color("activeTextColor"); }
    QColor linkColor() const { return ThemePalette::instance()->color("linkColor"); }
    QColor visitedLinkColor() const { return ThemePalette::instance()->color("visitedLinkColor"); }
    QColor negativeTextColor() const { return ThemePalette::instance()->color("negativeTextColor"); }
    QColor neutralTextColor() const { return ThemePalette::instance()->color("neutralTextColor"); }
    QColor positiveTextColor() const { return ThemePalette::instance()->color("positiveTextColor"); }
    QColor backgroundColor() const { return ThemePalette::instance()->color("backgroundColor"); }
    QColor alternateBackgroundColor() const { return ThemePalette::instance()->color("alternateBackgroundColor"); }
    QColor highlightColor() const { return ThemePalette::instance()->color("highlightColor"); }
    QColor activeBackgroundColor() const { return ThemePalette::instance()->color("activeBackgroundColor"); }
    QColor linkBackgroundColor() const { return ThemePalette::instance()->color("linkBackgroundColor"); }
    QColor visitedLinkBackgroundColor() const { return ThemePalette::instance()->color("visitedLinkBackgroundColor"); }
    QColor negativeBackgroundColor() const { return ThemePalette::instance()->color("negativeBackgroundColor"); }
    QColor neutralBackgroundColor() const { return ThemePalette::instance()->color("neutralBackgroundColor"); }
    QColor positiveBackgroundColor() const { return ThemePalette::instance()->color("positiveBackgroundColor"); }
    QColor focusColor() const { return ThemePalette::instance()->color("focusColor"); }
    QColor hoverColor() const { return ThemePalette::instance()->color("hoverColor"); }
    QFont defaultFont() const;
    QFont smallFont() const;
    QFont fixedWidthFont() const;

Q_SIGNALS:
    void colorSetChanged();
    void inheritChanged();
    void paletteChanged();

private:
    ColorSet m_colorSet = Window;
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
