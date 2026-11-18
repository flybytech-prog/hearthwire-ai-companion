// ThemeWatcher (task 012 R2, plan-v1 §2.7): the app follows the active
// Omarchy theme. Omarchy keeps it in ~/.local/state/omarchy/current/theme/
// and switches by building next-theme, removing theme and moving next-theme
// into its place (bin/omarchy-theme-set), so the watcher watches the theme
// folder, its colors.toml and the folders above it, and arms itself again
// after every change. No polling: inotify events, then one read 200 ms
// after the last one.
//
// colors.toml is untrusted input:
// - read only from a theme folder of ours (owner = us, not group/other
//   writable), never through a link (O_NOFOLLOW), only a regular file of
//   ours that is not group/other writable, at most 64 KiB;
// - a strict TOML subset: `key = "value"` (or 'value') lines, `#`
//   comments, blank lines; a table header ends the top-level keys; unknown
//   keys are ignored, any other line, a multi-line string, a known key
//   twice or a bad value refuses the whole file;
// - colours only as "#rrggbb", mode only "dark" or "light"; accent,
//   background and foreground are required, and the foreground must read
//   on the background (contrast >= 4.5);
// - colours that would not read are replaced in derive() (see the
//   Min*Contrast constants), and so are status colours that can't be told
//   apart (MinStatusChroma, MinStatusHueDistance).
// Anything else (no Omarchy, a missing or refused file) gives the built-in
// palette, dark or light as the system colour scheme says.
//
// The file is read on the GUI thread, synchronously (review-4-security
// INFO 4; kept on purpose, task 012 R3.7b): it sits in the same home as
// settings.json, which is read the same way at start, and fontconfig, the
// icon theme and Qt's QML cache read from there synchronously too, so a
// stalled home stalls the app anyway. The read itself is bounded: one
// regular file of at most 64 KiB, opened O_NONBLOCK | O_NOFOLLOW (a FIFO
// or a device is refused before any read), once per settled change.
#pragma once

#include <QByteArray>
#include <QColor>
#include <QFileSystemWatcher>
#include <QObject>
#include <QString>
#include <QStringList>
#include <QTimer>

#include <array>
#include <optional>

namespace HwTheme {

// Kirigami.Theme's colour roles.
enum Role : int {
    TextColor,
    DisabledTextColor,
    HighlightedTextColor,
    ActiveTextColor,
    LinkColor,
    VisitedLinkColor,
    NegativeTextColor,
    NeutralTextColor,
    PositiveTextColor,
    BackgroundColor,
    AlternateBackgroundColor,
    HighlightColor,
    ActiveBackgroundColor,
    LinkBackgroundColor,
    VisitedLinkBackgroundColor,
    NegativeBackgroundColor,
    NeutralBackgroundColor,
    PositiveBackgroundColor,
    FocusColor,
    HoverColor,
    RoleCount
};

// Kirigami.Theme's colour sets, in Kirigami's order.
enum Set : int { View = 0, Window, Button, Selection, Tooltip, Complementary, Header, SetCount };

// What a theme gives: Omarchy's colors.toml keys. Optional ones may be
// invalid QColors; derive() fills them in.
struct Source {
    bool dark = true;
    QColor accent;
    QColor background;
    QColor foreground;
    QColor darkBackground;
    QColor darkerBackground;
    QColor lighterBackground;
    QColor red;
    QColor yellow;
    QColor green;
    QColor blue;
    QColor magenta;

    bool operator==(const Source &other) const;
    bool operator!=(const Source &other) const { return !(*this == other); }
};

struct Palette {
    bool dark = true;
    std::array<std::array<QColor, RoleCount>, SetCount> sets{};

    const QColor &color(Set set, Role role) const { return sets[size_t(set)][size_t(role)]; }
    bool operator==(const Palette &other) const { return dark == other.dark && sets == other.sets; }
    bool operator!=(const Palette &other) const { return !(*this == other); }
};

constexpr qint64 MaxFileBytes = 64 * 1024;
// Minimum WCAG contrast (review-4 LOW-3): foreground on background, below
// which the theme is refused (and each set's text, below which the set
// takes the Window background); a status or link colour on its set's
// background and text on the accent, below which a built-in colour (or
// black or white on the accent) is used instead.
constexpr double MinTextContrast = 4.5;
constexpr double MinStatusContrast = 3.0;
constexpr double MinAccentContrast = 3.0;
// Status colours told apart (user decision 2026-11-17, Omarchy "white"):
// red, yellow and green (Negative, Neutral, Positive) each need a chroma
// (max - min of the sRGB channels, 0..1) of at least MinStatusChroma, and
// every two of them a hue at least MinStatusHueDistance degrees apart.
// Otherwise all three are the built-in ones (distinctStatus()).
// 0.15 kept by the user (2026-11-17, review-5 nit 2): the near-grey stock
// themes (ethereal, last-horizon, about 0.06) get the built-in colours.
constexpr double MinStatusChroma = 0.15;
constexpr double MinStatusHueDistance = 20.0;

enum class ReadStatus { Ok, Missing, Refused, TooLarge, Malformed };

// The built-in palette's source.
Source builtIn(bool dark);
// Every colour set from a source.
Palette derive(const Source &source);
// colors.toml text -> source; nullopt when the file is refused.
std::optional<Source> parse(const QByteArray &text);
// Reads <themeDir>/colors.toml with the rules above into `out`.
ReadStatus readColorsFile(const QString &themeDir, QByteArray *out);
// WCAG contrast ratio of two colours (1..21).
double contrast(const QColor &a, const QColor &b);
// max - min of the sRGB channels (0..1).
double chroma(const QColor &color);
// Whether red, yellow and green can be told apart (see MinStatusChroma).
bool distinctStatus(const QColor &red, const QColor &yellow, const QColor &green);

} // namespace HwTheme

class ThemeWatcher : public QObject
{
    Q_OBJECT

public:
    // `themeDir`: the theme folder (defaultThemeDir() in the app).
    explicit ThemeWatcher(const QString &themeDir, QObject *parent = nullptr);

    static QString defaultThemeDir();

    // Reads the theme now and starts watching.
    void start();
    // The Omarchy theme in use, or nullopt (built-in palette).
    const std::optional<HwTheme::Source> &source() const { return m_source; }
    HwTheme::ReadStatus status() const { return m_status; }
    // The paths being watched now (tests).
    QStringList watched() const;
    // Reads again now (also what an event leads to, 200 ms later).
    void reload();

Q_SIGNALS:
    // The theme in use changed (source() differs).
    void changed();

private:
    void arm();

    QString m_dir;
    QFileSystemWatcher m_watcher;
    QTimer m_settle;
    std::optional<HwTheme::Source> m_source;
    HwTheme::ReadStatus m_status = HwTheme::ReadStatus::Missing;
};
