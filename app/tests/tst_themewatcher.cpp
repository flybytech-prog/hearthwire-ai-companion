// ThemeWatcher (round R2): the Omarchy theme's colors.toml is untrusted
// input (strict subset, size cap, our own regular file only, never through
// a link), its colours reach every Kirigami colour set, and a theme switch
// done the way omarchy-theme-set does it (build next-theme, remove theme,
// move next-theme into place) or a swap of a `current` link is followed
// without polling. Everything runs in a temp folder; the real
// ~/.local/state/omarchy is never read.
#include <QDir>
#include <QFile>
#include <QQmlComponent>
#include <QQmlEngine>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>
#include <QtQml/qqmlextensionplugin.h>

#include <cstdio>
#include <memory>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include "KirigamiCompat.h"
#include "ThemeWatcher.h"

Q_IMPORT_QML_PLUGIN(Hearthwire_Compat_KirigamiPlugin)

using namespace HwTheme;

namespace {
// Omarchy 4.5's tokyo-night and white colors.toml, as shipped.
const QByteArray TokyoNight = R"(mode = "dark"

accent = "#7aa2f7"
selection = "#292e42"
muted = "#414868"

background = "#1a1b26"
dark_background = "#13141c"
darker_background = "#0e0e14"
lighter_background = "#24283b"

foreground = "#a9b1d6"
dark_foreground = "#565f89"
light_foreground = "#b4bee6"
bright_foreground = "#c0caf5"

red = "#f7768e"
yellow = "#e0af68"
orange = "#eb927b"
green = "#9ece6a"
cyan = "#449dab"
blue = "#7aa2f7"
magenta = "#ad8ee6"
brown = "#75493d"

bright_red = "#ff7a93"
bright_yellow = "#ff9e64"
bright_green = "#b9f27c"
bright_cyan = "#0db9d7"
bright_blue = "#7da6ff"
bright_magenta = "#bb9af7"
)";

const QByteArray White = R"(mode = "light"

accent = "#6e6e6e"
selection = "#c0c0c0"
muted = "#808080"

background = "#ffffff"
dark_background = "#f5f5f5"
darker_background = "#e8e8e8"
lighter_background = "#c0c0c0"

foreground = "#000000"
dark_foreground = "#c0c0c0"
light_foreground = "#000000"
bright_foreground = "#000000"

red = "#2a2a2a"
yellow = "#4a4a4a"
green = "#3a3a3a"
cyan = "#3e3e3e"
blue = "#1a1a1a"
magenta = "#2e2e2e"
)";

const QByteArray Minimal = "accent = \"#ffd60a\"\nbackground = \"#101010\"\nforeground = \"#eeeeee\"\n";

bool write(const QString &path, const QByteArray &data, int mode = 0644)
{
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate))
        return false;
    const bool ok = file.write(data) == data.size();
    file.close();
    return ok && ::chmod(QFile::encodeName(path).constData(), mode_t(mode)) == 0;
}

// A new folder made as omarchy-theme-set makes next-theme.
bool makeTheme(const QString &dir, const QByteArray &colors)
{
    return QDir().mkpath(dir) && ::chmod(QFile::encodeName(dir).constData(), 0755) == 0
        && write(dir + "/colors.toml", colors);
}

bool rename(const QString &from, const QString &to)
{
    return ::rename(QFile::encodeName(from).constData(), QFile::encodeName(to).constData()) == 0;
}
}

class TestThemeWatcher : public QObject
{
    Q_OBJECT

    QTemporaryDir m_dir;
    int m_case = 0;

    // A fresh theme folder for one case.
    QString freshDir()
    {
        const QString dir = QDir(m_dir.path()).filePath(QStringLiteral("case-%1").arg(++m_case));
        QDir().mkpath(dir);
        ::chmod(QFile::encodeName(dir).constData(), 0755);
        return dir;
    }

private Q_SLOTS:
    void initTestCase()
    {
        QVERIFY(m_dir.isValid());
        ::chmod(QFile::encodeName(m_dir.path()).constData(), 0700);
    }

    // --- parse: the strict subset.
    void parseAccepts_data()
    {
        QTest::addColumn<QByteArray>("text");
        QTest::addColumn<bool>("dark");
        QTest::addColumn<QString>("accent");
        QTest::addColumn<QString>("background");
        QTest::newRow("tokyo-night as shipped") << TokyoNight << true << "#7aa2f7" << "#1a1b26";
        QTest::newRow("white as shipped") << White << false << "#6e6e6e" << "#ffffff";
        QTest::newRow("only the required keys, dark by background") << Minimal << true << "#ffd60a" << "#101010";
        QTest::newRow("light by background") << QByteArray("accent = \"#123456\"\nbackground = \"#fafafa\"\nforeground = \"#111111\"\n")
                                             << false << "#123456" << "#fafafa";
        QTest::newRow("mode wins over the background")
            << QByteArray("mode = \"light\"\n" + Minimal) << false << "#ffd60a" << "#101010";
        QTest::newRow("comments, blank lines, CRLF, spacing, inline comment")
            << QByteArray("# a theme\r\n\r\n  accent=\"#ffd60a\"   # yellow\r\n\tbackground =  \"#101010\"\r\nforeground = \"#EEEEEE\"\r\n")
            << true << "#ffd60a" << "#101010";
        QTest::newRow("unknown keys of any shape are ignored")
            << QByteArray("hyprland_active_border = \"rgba(26a269ee) rgba(2ec27eee) 45deg\"\nfoo = 12\nbar = [1, 2]\n"
                          "baz-qux = true\n" + Minimal)
            << true << "#ffd60a" << "#101010";
        QTest::newRow("literal strings") << QByteArray("mode = 'dark'\naccent = '#ffd60a'\nbackground = '#101010'\nforeground = \"#eeeeee\"\n")
                                         << true << "#ffd60a" << "#101010";
        QTest::newRow("fg on bg exactly readable (black on #767676: 4.54)")
            << QByteArray("accent = \"#ffd60a\"\nbackground = \"#767676\"\nforeground = \"#000000\"\n") << false << "#ffd60a" << "#767676";
        QTest::newRow("a table ends the top-level keys")
            << QByteArray(Minimal + "[shell]\naccent = \"#000000\"\nnot even = toml\n") << true << "#ffd60a" << "#101010";
    }

    void parseAccepts()
    {
        QFETCH(QByteArray, text);
        QFETCH(bool, dark);
        QFETCH(QString, accent);
        QFETCH(QString, background);
        const std::optional<Source> source = parse(text);
        QVERIFY(source.has_value());
        QCOMPARE(source->dark, dark);
        QCOMPARE(source->accent, QColor(accent));
        QCOMPARE(source->background, QColor(background));
        QVERIFY(source->foreground.isValid());
    }

    void parseRefuses_data()
    {
        QTest::addColumn<QByteArray>("text");
        QTest::newRow("empty") << QByteArray();
        QTest::newRow("no accent") << QByteArray("background = \"#101010\"\nforeground = \"#eeeeee\"\n");
        QTest::newRow("no background") << QByteArray("accent = \"#101010\"\nforeground = \"#eeeeee\"\n");
        QTest::newRow("no foreground") << QByteArray("accent = \"#101010\"\nbackground = \"#eeeeee\"\n");
        QTest::newRow("short hex") << QByteArray(Minimal).replace("#ffd60a", "#ffd60");
        QTest::newRow("3-digit hex") << QByteArray(Minimal).replace("#ffd60a", "#fd0");
        QTest::newRow("alpha hex") << QByteArray(Minimal).replace("#ffd60a", "#ffd60aff");
        QTest::newRow("not hex") << QByteArray(Minimal).replace("#ffd60a", "#ggd60a");
        QTest::newRow("a colour name") << QByteArray(Minimal).replace("\"#ffd60a\"", "\"yellow\"");
        QTest::newRow("unquoted") << QByteArray(Minimal).replace("\"#ffd60a\"", "#ffd60a");
        QTest::newRow("an escape") << QByteArray(Minimal).replace("\"#ffd60a\"", "\"\\u0023ffd60a\"");
        QTest::newRow("unterminated") << QByteArray(Minimal).replace("\"#ffd60a\"", "\"#ffd60a");
        QTest::newRow("junk after the value") << QByteArray(Minimal).replace("\"#ffd60a\"", "\"#ffd60a\" x");
        QTest::newRow("a known key twice") << QByteArray(Minimal + "accent = \"#000000\"\n");
        QTest::newRow("mode not dark or light") << QByteArray("mode = \"auto\"\n" + Minimal);
        QTest::newRow("mode twice") << QByteArray("mode = \"dark\"\nmode = \"light\"\n" + Minimal);
        QTest::newRow("a line without =") << QByteArray(Minimal + "accent\n");
        QTest::newRow("no value") << QByteArray(Minimal + "red =\n");
        QTest::newRow("a dotted key") << QByteArray(Minimal + "theme.accent = \"#000000\"\n");
        QTest::newRow("a quoted key") << QByteArray("\"accent\" = \"#000000\"\n" + Minimal);
        QTest::newRow("a multi-line string") << QByteArray(Minimal + "notes = \"\"\"\nsome text\n\"\"\"\n");
        QTest::newRow("a NUL byte") << QByteArray(Minimal + QByteArray(1, '\0'));
        QTest::newRow("over 64 KiB") << QByteArray(Minimal + "#" + QByteArray(int(MaxFileBytes), 'x') + "\n");
        QTest::newRow("binary") << QByteArray("\x7f" "ELF\x02\x01\x01\x00", 8);
        // Its closing quotes in what would otherwise read as a comment: the
        // line inside is string content in TOML, not a key (security INFO 2).
        QTest::newRow("a multi-line string on an unknown key") << QByteArray(Minimal + "notes = \"\"\"\nred = \"#000001\" # \"\"\"\n");
        QTest::newRow("a multi-line literal string") << QByteArray(Minimal + "notes = '''\nred = '#000001' # '''\n");
        QTest::newRow("a literal string not closed") << QByteArray(Minimal).replace("\"#ffd60a\"", "'#ffd60a");
        QTest::newRow("mixed quotes") << QByteArray(Minimal).replace("\"#ffd60a\"", "'#ffd60a\"");
        QTest::newRow("foreground = background (LOW-3)") << QByteArray("accent = \"#ffd60a\"\nbackground = \"#101010\"\nforeground = \"#101010\"\n");
        QTest::newRow("every colour the same (LOW-3)")
            << QByteArray("accent = \"#808080\"\nbackground = \"#808080\"\nforeground = \"#808080\"\nred = \"#808080\"\n");
        QTest::newRow("fg on bg just under 4.5 (#777777 on white: 4.48)")
            << QByteArray("accent = \"#ffd60a\"\nbackground = \"#ffffff\"\nforeground = \"#777777\"\n");
        QTest::newRow("a control character in the value") << QByteArray(Minimal).replace("\"#ffd60a\"", "\"#ffd60a\x01\"");
    }

    void parseRefuses()
    {
        QFETCH(QByteArray, text);
        QVERIFY(!parse(text).has_value());
    }

    // --- derive: every colour set, the mapping of plan-v1 §2.7.
    void everySetHasEveryColour()
    {
        for (const QByteArray &text : {TokyoNight, White, Minimal}) {
            const Palette palette = derive(*parse(text));
            for (int set = 0; set < SetCount; ++set) {
                for (int role = 0; role < RoleCount; ++role)
                    QVERIFY2(palette.color(Set(set), Role(role)).isValid(), qPrintable(QStringLiteral("set %1 role %2").arg(set).arg(role)));
            }
        }
        for (bool dark : {true, false}) {
            const Palette palette = derive(builtIn(dark));
            QCOMPARE(palette.dark, dark);
            for (int set = 0; set < SetCount; ++set) {
                for (int role = 0; role < RoleCount; ++role)
                    QVERIFY(palette.color(Set(set), Role(role)).isValid());
            }
        }
    }

    void theMappingFollowsThePlan()
    {
        const Source source = *parse(TokyoNight);
        const Palette p = derive(source);
        QCOMPARE(p.dark, true);
        QCOMPARE(p.color(Window, TextColor), QColor("#a9b1d6"));
        QCOMPARE(p.color(Window, BackgroundColor), QColor("#1a1b26"));
        QCOMPARE(p.color(Window, AlternateBackgroundColor), QColor("#24283b"));
        QCOMPARE(p.color(Window, HighlightColor), QColor("#7aa2f7"));
        QCOMPARE(p.color(Window, NegativeTextColor), QColor("#f7768e"));
        QCOMPARE(p.color(Window, NeutralTextColor), QColor("#e0af68"));
        QCOMPARE(p.color(Window, PositiveTextColor), QColor("#9ece6a"));
        QCOMPARE(p.color(Window, LinkColor), QColor("#7aa2f7"));
        QCOMPARE(p.color(Window, VisitedLinkColor), QColor("#ad8ee6"));
        // 20% of the colour over the background.
        const QColor negative = p.color(Window, NegativeBackgroundColor);
        QVERIFY(qAbs(negative.red() - qRound(0xf7 * 0.2 + 0x1a * 0.8)) <= 1);
        QVERIFY(qAbs(negative.blue() - qRound(0x8e * 0.2 + 0x26 * 0.8)) <= 1);
        // The sets differ where Kirigami's do.
        QCOMPARE(p.color(View, BackgroundColor), QColor("#13141c"));
        QCOMPARE(p.color(Header, BackgroundColor), QColor("#13141c"));
        QCOMPARE(p.color(Button, BackgroundColor), QColor("#24283b"));
        QCOMPARE(p.color(Selection, BackgroundColor), QColor("#7aa2f7"));
        QCOMPARE(p.color(Selection, TextColor), p.color(Window, HighlightedTextColor));
        QCOMPARE(p.color(Complementary, BackgroundColor), QColor("#0e0e14"));
        QCOMPARE(p.color(Tooltip, BackgroundColor), QColor("#24283b"));
        // Light: Complementary is the inverse.
        const Palette light = derive(*parse(White));
        QCOMPARE(light.dark, false);
        QCOMPARE(light.color(Complementary, BackgroundColor), QColor("#000000"));
        QCOMPARE(light.color(Complementary, TextColor), QColor("#ffffff"));
        QCOMPARE(light.color(View, BackgroundColor), QColor("#ffffff"));
    }

    // LOW-3: what a hostile (or careless) theme can't hide. Per role, a
    // colour that does not read falls back; the rest of the theme stays.
    void unreadableColoursFallBack_data()
    {
        QTest::addColumn<QByteArray>("text");
        QTest::addColumn<QString>("what");
        // Chromatic, so only the contrast rule decides (not distinctStatus).
        QTest::newRow("red near background") << QByteArray(Minimal + "red = \"#3a0a0a\"\n") << "red";
        QTest::newRow("yellow near background") << QByteArray(Minimal + "yellow = \"#303000\"\n") << "yellow";
        QTest::newRow("green near background") << QByteArray(Minimal + "green = \"#003000\"\n") << "green";
        QTest::newRow("all status colours near background, light")
            << QByteArray("accent = \"#1a73e8\"\nbackground = \"#ffffff\"\nforeground = \"#000000\"\n"
                          "red = \"#ffd0d0\"\nyellow = \"#ffffc0\"\ngreen = \"#d0ffd0\"\nblue = \"#ffffff\"\nmagenta = \"#ffffff\"\n")
            << "all";
        QTest::newRow("lighter background = foreground (Button, Tooltip)")
            << QByteArray(Minimal + "lighter_background = \"#eeeeee\"\n") << "set";
        QTest::newRow("dark backgrounds = foreground (View, Header, Complementary)")
            << QByteArray(Minimal + "dark_background = \"#eeeeee\"\ndarker_background = \"#eeeeee\"\n") << "set";
        QTest::newRow("mid-tone accent: neither fg nor bg reads on it")
            << QByteArray("accent = \"#444444\"\nbackground = \"#000000\"\nforeground = \"#7f7f7f\"\n") << "accent";
    }

    void unreadableColoursFallBack()
    {
        QFETCH(QByteArray, text);
        QFETCH(QString, what);
        const std::optional<Source> source = parse(text);
        QVERIFY(source.has_value());
        const Palette p = derive(*source);
        for (int set = 0; set < SetCount; ++set) {
            const QColor bg = p.color(Set(set), BackgroundColor);
            const QString name = QStringLiteral("set %1").arg(set);
            if (set == Selection) {
                QVERIFY2(contrast(p.color(Selection, TextColor), bg) >= MinAccentContrast, qPrintable(name));
                // Status colours as Window's (none reads on the accent reliably).
                for (Role role : {NegativeTextColor, NeutralTextColor, PositiveTextColor, LinkColor, VisitedLinkColor})
                    QCOMPARE(p.color(Selection, role), p.color(Window, role));
                continue;
            }
            QVERIFY2(contrast(p.color(Set(set), TextColor), bg) >= MinTextContrast, qPrintable(name));
            QVERIFY2(contrast(p.color(Set(set), TextColor), p.color(Set(set), AlternateBackgroundColor)) >= MinTextContrast,
                     qPrintable(name + " alternate"));
            for (Role role : {NegativeTextColor, NeutralTextColor, PositiveTextColor, LinkColor, VisitedLinkColor})
                QVERIFY2(contrast(p.color(Set(set), role), bg) >= MinStatusContrast,
                         qPrintable(name + QStringLiteral(" role %1").arg(int(role))));
        }
        QVERIFY(contrast(p.color(Window, HighlightedTextColor), p.color(Window, HighlightColor)) >= MinAccentContrast);
        // The theme's own colours stay where they read.
        QCOMPARE(p.color(Window, BackgroundColor), source->background);
        QCOMPARE(p.color(Window, TextColor), source->foreground);
        QCOMPARE(p.color(Window, HighlightColor), source->accent);
        const Source builtin = builtIn(source->dark);
        if (what != "all" && what != "accent")
            QVERIFY(distinctStatus(source->red.isValid() ? source->red : builtin.red,
                                   source->yellow.isValid() ? source->yellow : builtin.yellow,
                                   source->green.isValid() ? source->green : builtin.green));
        if (what == "red")
            QCOMPARE(p.color(Window, NegativeTextColor), builtin.red);
        if (what == "yellow")
            QCOMPARE(p.color(Window, NeutralTextColor), builtin.yellow);
        if (what == "green")
            QCOMPARE(p.color(Window, PositiveTextColor), builtin.green);
        if (what == "red" || what == "yellow" || what == "green") {
            // Only that role: accent and text are the theme's.
            QCOMPARE(p.color(Window, LinkColor), builtin.blue);
        }
        if (what == "accent")
            QCOMPARE(p.color(Window, HighlightedTextColor), QColor(Qt::white));
    }

    // The stock Omarchy themes shown in the shots: tokyo-night keeps every
    // colour of its own where Kirigami shows status and text; white keeps
    // its text, accent and link colours, but its grey status colours can't
    // be told apart (user decision 2026-11-17), so those are the built-in
    // ones, all three.
    void stockThemesKeepTheirColours_data()
    {
        QTest::addColumn<QByteArray>("text");
        QTest::addColumn<bool>("ownStatus");
        QTest::newRow("tokyo-night keeps its status colours") << TokyoNight << true;
        QTest::newRow("white gets the built-in status colours") << White << false;
    }

    void stockThemesKeepTheirColours()
    {
        QFETCH(QByteArray, text);
        QFETCH(bool, ownStatus);
        const Source source = *parse(text);
        const Source builtin = builtIn(source.dark);
        QCOMPARE(distinctStatus(source.red, source.yellow, source.green), ownStatus);
        const Palette p = derive(source);
        for (Set set : {Window, View, Header, Button, Tooltip, Selection}) {
            if (set != Selection)
                QCOMPARE(p.color(set, TextColor), source.foreground);
            QCOMPARE(p.color(set, NegativeTextColor), ownStatus ? source.red : builtin.red);
            QCOMPARE(p.color(set, NeutralTextColor), ownStatus ? source.yellow : builtin.yellow);
            QCOMPARE(p.color(set, PositiveTextColor), ownStatus ? source.green : builtin.green);
            QCOMPARE(p.color(set, LinkColor), source.blue);
            QCOMPARE(p.color(set, VisitedLinkColor), source.magenta);
        }
        QCOMPARE(p.color(Window, HighlightColor), source.accent);
    }

    // The distinctness rule at its thresholds: red at hue 0, green at 120;
    // yellow's hue 19 (too close to red) or 21 degrees; green's chroma
    // 36/255 = 0.141 (too grey) or 41/255 = 0.161. On a dark background
    // all of them read (contrast >= 3), so only this rule decides.
    void statusColoursMustBeDistinct_data()
    {
        QTest::addColumn<QColor>("yellow");
        QTest::addColumn<QColor>("green");
        QTest::addColumn<bool>("own");
        const QColor green = QColor::fromRgb(80, 200, 80);
        QTest::newRow("yellow 21 degrees from red: own") << QColor::fromHsv(21, 200, 230).toRgb() << green << true;
        QTest::newRow("yellow 19 degrees from red: built-in") << QColor::fromHsv(19, 200, 230).toRgb() << green << false;
        QTest::newRow("green chroma 0.161: own") << QColor::fromRgb(230, 200, 40) << QColor::fromRgb(100, 141, 100) << true;
        QTest::newRow("green chroma 0.141: built-in") << QColor::fromRgb(230, 200, 40) << QColor::fromRgb(100, 136, 100) << false;
        QTest::newRow("same hue, different lightness: built-in")
            << QColor::fromRgb(240, 140, 140) << QColor::fromRgb(150, 40, 40) << false;
    }

    void statusColoursMustBeDistinct()
    {
        QFETCH(QColor, yellow);
        QFETCH(QColor, green);
        QFETCH(bool, own);
        const QColor red = QColor::fromRgb(224, 48, 48);
        const QByteArray text = Minimal + "red = \"" + red.name().toLatin1() + "\"\nyellow = \"" + yellow.name().toLatin1()
            + "\"\ngreen = \"" + green.name().toLatin1() + "\"\n";
        const std::optional<Source> source = parse(text);
        QVERIFY(source.has_value());
        QCOMPARE(distinctStatus(source->red, source->yellow, source->green), own);
        const Palette p = derive(*source);
        const Source builtin = builtIn(true);
        // All three at once, never one alone.
        QCOMPARE(p.color(Window, NegativeTextColor), own ? red : builtin.red);
        QCOMPARE(p.color(Window, NeutralTextColor), own ? source->yellow : builtin.yellow);
        QCOMPARE(p.color(Window, PositiveTextColor), own ? source->green : builtin.green);
        // Links are not status colours: the theme's (here the built-in
        // blue, Minimal has none).
        QCOMPARE(p.color(Window, LinkColor), builtin.blue);
    }

    void textOnTheAccentReads()
    {
        for (const QByteArray &text : {TokyoNight, White, Minimal}) {
            const Palette p = derive(*parse(text));
            QVERIFY(contrast(p.color(Window, HighlightColor), p.color(Window, HighlightedTextColor)) >= 3.0);
        }
    }

    // --- readColorsFile: only our own regular file, never a link, capped.
    void readFile()
    {
        QByteArray out;
        const QString ok = freshDir();
        QVERIFY(write(ok + "/colors.toml", TokyoNight));
        QCOMPARE(readColorsFile(ok, &out), ReadStatus::Ok);
        QCOMPARE(out, TokyoNight);

        QCOMPARE(readColorsFile(freshDir(), &out), ReadStatus::Missing);
        QCOMPARE(readColorsFile(m_dir.path() + "/no-such-folder", &out), ReadStatus::Missing);

        // A link, even to a good file of ours, is refused.
        const QString linked = freshDir();
        QVERIFY(QFile::link(ok + "/colors.toml", linked + "/colors.toml"));
        QCOMPARE(readColorsFile(linked, &out), ReadStatus::Refused);
        QVERIFY(out.isEmpty());
        const QString toZero = freshDir();
        QVERIFY(QFile::link("/dev/zero", toZero + "/colors.toml"));
        QCOMPARE(readColorsFile(toZero, &out), ReadStatus::Refused);

        for (int mode : {0664, 0646, 0666}) {
            const QString open = freshDir();
            QVERIFY(write(open + "/colors.toml", TokyoNight, mode));
            QCOMPARE(readColorsFile(open, &out), ReadStatus::Refused);
        }
        const QString openDir = freshDir();
        QVERIFY(write(openDir + "/colors.toml", TokyoNight));
        QVERIFY(::chmod(QFile::encodeName(openDir).constData(), 0777) == 0);
        QCOMPARE(readColorsFile(openDir, &out), ReadStatus::Refused);

        // Not a regular file: a FIFO (no hang) and a folder.
        const QString fifo = freshDir();
        QVERIFY(::mkfifo(QFile::encodeName(fifo + "/colors.toml").constData(), 0600) == 0);
        QCOMPARE(readColorsFile(fifo, &out), ReadStatus::Refused);
        const QString folder = freshDir();
        QVERIFY(QDir().mkdir(folder + "/colors.toml"));
        QCOMPARE(readColorsFile(folder, &out), ReadStatus::Refused);

        // The cap: 64 KiB is read, one byte more is not.
        const QString edge = freshDir();
        QByteArray atCap = Minimal + "#";
        atCap += QByteArray(int(MaxFileBytes) - atCap.size(), 'x');
        QCOMPARE(atCap.size(), qsizetype(MaxFileBytes));
        QVERIFY(write(edge + "/colors.toml", atCap));
        QCOMPARE(readColorsFile(edge, &out), ReadStatus::Ok);
        QVERIFY(parse(out).has_value());
        const QString huge = freshDir();
        QVERIFY(write(huge + "/colors.toml", atCap + "x"));
        QCOMPARE(readColorsFile(huge, &out), ReadStatus::TooLarge);
        QVERIFY(out.isEmpty());
        const QString giant = freshDir();
        QVERIFY(write(giant + "/colors.toml", QByteArray(8 * 1024 * 1024, '#')));
        QCOMPARE(readColorsFile(giant, &out), ReadStatus::TooLarge);

        // The theme folder may be reached through a link (a `current` swap).
        const QString viaLink = QDir(m_dir.path()).filePath("link-to-ok");
        QVERIFY(QFile::link(ok, viaLink));
        QCOMPARE(readColorsFile(viaLink, &out), ReadStatus::Ok);
    }

    void aFolderOfSomeoneElseIsRefused()
    {
        if (::geteuid() == 0)
            QSKIP("running as root owns every folder");
        QByteArray out;
        // Owned by root: refused before any file in it is opened.
        QCOMPARE(readColorsFile(QStringLiteral("/etc"), &out), ReadStatus::Refused);
    }

    // --- ThemeWatcher: follows the switch, re-arms, falls back.
    void followsAThemeSwitch()
    {
        const QString omarchy = freshDir() + "/omarchy";
        const QString current = omarchy + "/current";
        const QString theme = current + "/theme";
        QVERIFY(QDir().mkpath(omarchy));
        ThemeWatcher watcher(theme);
        QSignalSpy spy(&watcher, &ThemeWatcher::changed);
        watcher.start();
        QVERIFY(!watcher.source().has_value());
        QCOMPARE(watcher.status(), ReadStatus::Missing);
        QCOMPARE(watcher.watched(), QStringList{omarchy});

        // First theme: current/ and theme/ appear.
        QVERIFY(QDir().mkpath(current));
        QVERIFY(makeTheme(current + "/next-theme", TokyoNight));
        QVERIFY(rename(current + "/next-theme", theme));
        QVERIFY(spy.wait(5000));
        QVERIFY(watcher.source().has_value());
        QCOMPARE(watcher.source()->accent, QColor("#7aa2f7"));
        QVERIFY(watcher.watched().contains(theme));
        QVERIFY(watcher.watched().contains(theme + "/colors.toml"));

        // A switch as omarchy-theme-set does it.
        spy.clear();
        QVERIFY(makeTheme(current + "/next-theme", White));
        QVERIFY(QDir(theme).removeRecursively());
        QVERIFY(rename(current + "/next-theme", theme));
        QVERIFY(spy.wait(5000));
        QCOMPARE(watcher.source()->dark, false);
        QCOMPARE(watcher.source()->accent, QColor("#6e6e6e"));
        QVERIFY(watcher.watched().contains(theme + "/colors.toml"));

        // The file replaced by a rename, then rewritten in place.
        spy.clear();
        QVERIFY(write(theme + "/colors.new", Minimal));
        QVERIFY(rename(theme + "/colors.new", theme + "/colors.toml"));
        QVERIFY(spy.wait(5000));
        QCOMPARE(watcher.source()->accent, QColor("#ffd60a"));
        spy.clear();
        QVERIFY(write(theme + "/colors.toml", TokyoNight));
        QVERIFY(spy.wait(5000));
        QCOMPARE(watcher.source()->accent, QColor("#7aa2f7"));

        // A broken file: the built-in palette, one fixed line, no content.
        spy.clear();
        QTest::ignoreMessage(QtWarningMsg,
                             "hearthwire-hyprland: the Omarchy theme's colors.toml is not in the expected format; using the built-in colours");
        QVERIFY(write(theme + "/colors.toml", "accent = \"#7aa2f7\"\n"));
        QVERIFY(spy.wait(5000));
        QVERIFY(!watcher.source().has_value());
        QCOMPARE(watcher.status(), ReadStatus::Malformed);

        // A link put in its place is refused too.
        spy.clear();
        QVERIFY(write(theme + "/colors.toml", TokyoNight));
        QVERIFY(spy.wait(5000));
        QVERIFY(watcher.source().has_value());
        spy.clear();
        QVERIFY(write(omarchy + "/elsewhere.toml", White));
        QVERIFY(QFile::link(omarchy + "/elsewhere.toml", theme + "/colors.link"));
        QTest::ignoreMessage(QtWarningMsg,
                             "hearthwire-hyprland: the Omarchy theme's colors.toml is not a file only you can change; using the built-in colours");
        QVERIFY(rename(theme + "/colors.link", theme + "/colors.toml"));
        QVERIFY(spy.wait(5000));
        QVERIFY(!watcher.source().has_value());
        QCOMPARE(watcher.status(), ReadStatus::Refused);

        // The theme gone: built-in palette, still watching what is left.
        QVERIFY(write(theme + "/colors.new", TokyoNight));
        QVERIFY(rename(theme + "/colors.new", theme + "/colors.toml"));
        QVERIFY(spy.wait(5000));
        spy.clear();
        QVERIFY(QDir(theme).removeRecursively());
        QVERIFY(spy.wait(5000));
        QVERIFY(!watcher.source().has_value());
        QCOMPARE(watcher.status(), ReadStatus::Missing);
        QVERIFY(watcher.watched().contains(current));
        for (const QString &path : watcher.watched())
            QVERIFY2(QFileInfo::exists(path), qPrintable(path));
    }

    void followsASwapOfACurrentLink()
    {
        const QString omarchy = freshDir() + "/omarchy";
        QVERIFY(makeTheme(omarchy + "/a/theme", TokyoNight));
        QVERIFY(makeTheme(omarchy + "/b/theme", White));
        QVERIFY(QFile::link(omarchy + "/a", omarchy + "/current"));
        ThemeWatcher watcher(omarchy + "/current/theme");
        QSignalSpy spy(&watcher, &ThemeWatcher::changed);
        watcher.start();
        QVERIFY(watcher.source().has_value());
        QCOMPARE(watcher.source()->dark, true);
        // ln -s b current.new && mv current.new current
        QVERIFY(QFile::link(omarchy + "/b", omarchy + "/current.new"));
        QVERIFY(rename(omarchy + "/current.new", omarchy + "/current"));
        QVERIFY(spy.wait(5000));
        QCOMPARE(watcher.source()->dark, false);
        // And again, back: the watch was armed on the new target.
        spy.clear();
        QVERIFY(QFile::link(omarchy + "/a", omarchy + "/current.new"));
        QVERIFY(rename(omarchy + "/current.new", omarchy + "/current"));
        QVERIFY(spy.wait(5000));
        QCOMPARE(watcher.source()->dark, true);
    }

    // Nothing to watch and nothing to read: no events, no timer, no reads.
    void outsideOmarchyItStaysIdle()
    {
        ThemeWatcher watcher(m_dir.path() + "/none/.local/state/omarchy/current/theme");
        QSignalSpy spy(&watcher, &ThemeWatcher::changed);
        watcher.start();
        QVERIFY(!watcher.source().has_value());
        QVERIFY(watcher.watched().isEmpty());
        QVERIFY(!spy.wait(400));
    }

    // --- Kirigami.Theme in QML follows ThemePalette, per colour set.
    void kirigamiThemeFollows()
    {
        QQmlEngine engine;
        QQmlComponent component(&engine);
        component.setData(R"(import QtQuick
import Hearthwire.Compat.Kirigami as Kirigami
Item {
    property color bg: Kirigami.Theme.backgroundColor
    property bool dark: Kirigami.Theme.dark
    property alias view: view
    Item {
        id: view
        Kirigami.Theme.colorSet: Kirigami.Theme.View
        Kirigami.Theme.inherit: false
        property color bg: Kirigami.Theme.backgroundColor
        Item {
            id: child
            property color bg: Kirigami.Theme.backgroundColor
            property int set: Kirigami.Theme.colorSet
        }
        property alias child: child
    }
})",
                          QUrl("qrc:/theme-test.qml"));
        std::unique_ptr<QObject> root(component.create());
        QVERIFY2(root, qPrintable(component.errorString()));
        ThemePalette::instance()->setTheme(parse(TokyoNight));
        QCOMPARE(root->property("bg").value<QColor>(), QColor("#1a1b26"));
        QCOMPARE(root->property("dark").toBool(), true);
        auto *view = root->property("view").value<QObject *>();
        auto *child = view->property("child").value<QObject *>();
        QCOMPARE(view->property("bg").value<QColor>(), QColor("#13141c"));
        QCOMPARE(child->property("bg").value<QColor>(), QColor("#13141c"));
        QCOMPARE(child->property("set").toInt(), int(Theme::View));
        ThemePalette::instance()->setTheme(parse(White));
        QCOMPARE(root->property("bg").value<QColor>(), QColor("#ffffff"));
        QCOMPARE(root->property("dark").toBool(), false);
        // No theme: the built-in palette again.
        ThemePalette::instance()->setTheme(std::nullopt);
        QCOMPARE(root->property("bg").value<QColor>(), derive(builtIn(ThemePalette::instance()->dark())).color(Window, BackgroundColor));
    }
};

QTEST_MAIN(TestThemeWatcher)
#include "tst_themewatcher.moc"
