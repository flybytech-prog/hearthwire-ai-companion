#include "ThemeWatcher.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <fcntl.h>
#include <initializer_list>
#include <sys/stat.h>
#include <unistd.h>

namespace HwTheme {

namespace {

// Closes a descriptor when it goes out of scope.
class Fd
{
public:
    explicit Fd(int fd) : m_fd(fd) {}
    ~Fd()
    {
        if (m_fd >= 0)
            ::close(m_fd);
    }
    Fd(const Fd &) = delete;
    Fd &operator=(const Fd &) = delete;
    int get() const { return m_fd; }

private:
    int m_fd;
};

// Ours and not writable by anyone else.
bool ours(const struct stat &info)
{
    return info.st_uid == ::geteuid() && (info.st_mode & (S_IWGRP | S_IWOTH)) == 0;
}

// a weighted `weight`, b the rest.
QColor mix(const QColor &a, const QColor &b, double weight)
{
    const auto part = [weight](double x, double y) { return x * weight + y * (1.0 - weight); };
    return QColor::fromRgbF(float(part(a.redF(), b.redF())), float(part(a.greenF(), b.greenF())),
                            float(part(a.blueF(), b.blueF())))
        .toRgb();
}

double luminance(const QColor &color)
{
    const auto channel = [](double c) { return c <= 0.03928 ? c / 12.92 : std::pow((c + 0.055) / 1.055, 2.4); };
    const QColor rgb = color.toRgb();
    return 0.2126 * channel(rgb.redF()) + 0.7152 * channel(rgb.greenF()) + 0.0722 * channel(rgb.blueF());
}

QByteArray trimmed(QByteArray text)
{
    while (!text.isEmpty() && (text.front() == ' ' || text.front() == '\t'))
        text.remove(0, 1);
    while (!text.isEmpty() && (text.back() == ' ' || text.back() == '\t'))
        text.chop(1);
    return text;
}

bool bareKeyChar(char c)
{
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '-';
}

// "#rrggbb" only.
QColor hexColor(const QByteArray &value)
{
    if (value.size() != 7 || value[0] != '#')
        return QColor();
    for (int i = 1; i < 7; ++i) {
        const char c = value[i];
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F')))
            return QColor();
    }
    bool ok = false;
    const uint rgb = value.mid(1).toUInt(&ok, 16);
    return ok ? QColor::fromRgb(QRgb(0xff000000u | rgb)) : QColor();
}

// The content of a basic string `"..."` or a literal string `'...'` with
// nothing after it but an optional comment; nullopt for anything else
// (escapes and control characters included: no known value needs them).
std::optional<QByteArray> quoted(const QByteArray &value)
{
    if (value.size() < 2 || (value[0] != '"' && value[0] != '\''))
        return std::nullopt;
    const int end = value.indexOf(value[0], 1);
    if (end < 0)
        return std::nullopt;
    const QByteArray content = value.mid(1, end - 1);
    for (const char c : content) {
        if (c == '\\' || static_cast<unsigned char>(c) < 0x20 || c == 0x7f)
            return std::nullopt;
    }
    const QByteArray rest = trimmed(value.mid(end + 1));
    if (!rest.isEmpty() && rest[0] != '#')
        return std::nullopt;
    return content;
}

} // namespace

double chroma(const QColor &color)
{
    const QColor rgb = color.toRgb();
    const float r = rgb.redF(), g = rgb.greenF(), b = rgb.blueF();
    return double(std::max({r, g, b}) - std::min({r, g, b}));
}

bool distinctStatus(const QColor &red, const QColor &yellow, const QColor &green)
{
    const QColor colours[] = {red, yellow, green};
    for (const QColor &colour : colours) {
        if (chroma(colour) < MinStatusChroma)
            return false;
    }
    for (int a = 0; a < 3; ++a) {
        for (int b = a + 1; b < 3; ++b) {
            const double hueA = colours[a].toHsv().hsvHueF() * 360.0;
            const double hueB = colours[b].toHsv().hsvHueF() * 360.0;
            const double apart = std::fabs(hueA - hueB);
            if (std::min(apart, 360.0 - apart) < MinStatusHueDistance)
                return false;
        }
    }
    return true;
}

bool Source::operator==(const Source &other) const
{
    return dark == other.dark && accent == other.accent && background == other.background
        && foreground == other.foreground && darkBackground == other.darkBackground
        && darkerBackground == other.darkerBackground && lighterBackground == other.lighterBackground
        && red == other.red && yellow == other.yellow && green == other.green && blue == other.blue
        && magenta == other.magenta;
}

double contrast(const QColor &a, const QColor &b)
{
    const double la = luminance(a);
    const double lb = luminance(b);
    return (std::max(la, lb) + 0.05) / (std::min(la, lb) + 0.05);
}

Source builtIn(bool dark)
{
    Source s;
    s.dark = dark;
    if (dark) {
        s.accent = QColor(0x8a, 0xb4, 0xf8);
        s.background = QColor(0x1c, 0x1b, 0x1f);
        s.foreground = QColor(0xe6, 0xe1, 0xe5);
        s.lighterBackground = QColor(0x2b, 0x29, 0x30);
        s.red = QColor(0xf2, 0x8b, 0x82);
        s.yellow = QColor(0xfd, 0xd6, 0x63);
        s.green = QColor(0x81, 0xc9, 0x95);
        s.blue = QColor(0x8a, 0xb4, 0xf8);
        s.magenta = QColor(0xc5, 0x8a, 0xf9);
    } else {
        s.accent = QColor(0x1a, 0x73, 0xe8);
        s.background = QColor(0xfe, 0xfb, 0xff);
        s.foreground = QColor(0x1c, 0x1b, 0x1f);
        s.lighterBackground = QColor(0xf1, 0xee, 0xf4);
        s.red = QColor(0xc5, 0x22, 0x1f);
        s.yellow = QColor(0xb0, 0x60, 0x00);
        s.green = QColor(0x18, 0x80, 0x38);
        s.blue = QColor(0x1a, 0x73, 0xe8);
        s.magenta = QColor(0x7b, 0x1f, 0xa2);
    }
    return s;
}

Palette derive(const Source &in)
{
    const Source fallback = builtIn(in.dark);
    const auto pick = [](const QColor &given, const QColor &otherwise) { return given.isValid() ? given : otherwise; };
    const QColor bg = in.background;
    const QColor fg = in.foreground;
    const QColor accent = in.accent;
    const QColor lighter = pick(in.lighterBackground, mix(fg, bg, 0.08));
    const QColor darkBg = pick(in.darkBackground, in.dark ? bg.darker(115) : bg.darker(104));
    const QColor darker = pick(in.darkerBackground, in.dark ? bg.darker(130) : bg.darker(110));
    QColor setRed = pick(in.red, fallback.red);
    QColor setYellow = pick(in.yellow, fallback.yellow);
    QColor setGreen = pick(in.green, fallback.green);
    // Critical, Warning and Good must be told apart (user decision
    // 2026-11-17): when they are not, all three are the built-in ones, so
    // the three stay one consistent palette. The contrast rule below still
    // applies to whichever three are used.
    if (!distinctStatus(setRed, setYellow, setGreen)) {
        setRed = fallback.red;
        setYellow = fallback.yellow;
        setGreen = fallback.green;
    }
    const QColor setBlue = pick(in.blue, fallback.blue);
    const QColor setMagenta = pick(in.magenta, fallback.magenta);
    // Text on the accent: whichever of the two reads better; black or
    // white when neither reaches MinAccentContrast (a mid-tone accent).
    QColor onAccent = contrast(accent, bg) >= contrast(accent, fg) ? bg : fg;
    if (contrast(onAccent, accent) < MinAccentContrast)
        onAccent = contrast(accent, Qt::black) >= contrast(accent, Qt::white) ? QColor(Qt::black) : QColor(Qt::white);

    struct Base {
        QColor background, alternate, text;
    };
    std::array<Base, SetCount> bases{};
    bases[View] = {in.dark ? darkBg : bg, in.dark ? bg : darkBg, fg};
    bases[Window] = {bg, lighter, fg};
    bases[Button] = {lighter, mix(lighter, fg, 0.9), fg};
    bases[Selection] = {accent, mix(accent, bg, 0.8), onAccent};
    bases[Tooltip] = {in.dark ? lighter : darkBg, in.dark ? bg : lighter, fg};
    bases[Complementary] = {in.dark ? darker : fg, in.dark ? darkBg : mix(fg, bg, 0.9), in.dark ? fg : bg};
    bases[Header] = {darkBg, lighter, fg};
    // A set whose text does not read on its own background (a theme's
    // dark/darker/lighter background too close to the foreground) takes
    // the Window background, which parse() made sure reads.
    for (int set = 0; set < SetCount; ++set) {
        Base &b = bases[size_t(set)];
        if (set != Selection && contrast(b.text, b.background) < MinTextContrast) {
            b.background = bg;
            b.text = fg;
        }
        // The same for the alternate background (list rows).
        if (set != Selection && contrast(b.text, b.alternate) < MinTextContrast)
            b.alternate = contrast(b.text, mix(b.text, b.background, 0.08)) >= MinTextContrast ? mix(b.text, b.background, 0.08)
                                                                                                 : b.background;
    }

    // A status or link colour that does not stand out from the set's
    // background (Window's for Selection) (LOW-3: a warning made invisible) is replaced by the
    // built-in one, of either palette, that does; failing that the one
    // that reads best.
    const Source otherFallback = builtIn(!in.dark);
    const auto readable = [](const QColor &on, std::initializer_list<QColor> candidates) {
        QColor best;
        for (const QColor &candidate : candidates) {
            if (contrast(candidate, on) >= MinStatusContrast)
                return candidate;
            if (!best.isValid() || contrast(candidate, on) > contrast(best, on))
                best = candidate;
        }
        return best;
    };

    Palette palette;
    palette.dark = in.dark;
    for (int set = 0; set < SetCount; ++set) {
        const Base &b = bases[size_t(set)];
        auto &c = palette.sets[size_t(set)];
        // Selection's background is the accent, on which no status colour
        // of a theme (or of ours) reliably reads: it takes Window's.
        const QColor &on = set == Selection ? bases[Window].background : b.background;
        const QColor red = readable(on, {setRed, fallback.red, otherFallback.red});
        const QColor yellow = readable(on, {setYellow, fallback.yellow, otherFallback.yellow});
        const QColor green = readable(on, {setGreen, fallback.green, otherFallback.green});
        const QColor blue = readable(on, {setBlue, fallback.blue, otherFallback.blue});
        const QColor magenta = readable(on, {setMagenta, fallback.magenta, otherFallback.magenta});
        c[TextColor] = b.text;
        c[DisabledTextColor] = mix(b.text, b.background, 0.55);
        c[HighlightedTextColor] = onAccent;
        c[ActiveTextColor] = accent;
        c[LinkColor] = blue;
        c[VisitedLinkColor] = magenta;
        c[NegativeTextColor] = red;
        c[NeutralTextColor] = yellow;
        c[PositiveTextColor] = green;
        c[BackgroundColor] = b.background;
        c[AlternateBackgroundColor] = b.alternate;
        c[HighlightColor] = accent;
        c[ActiveBackgroundColor] = accent;
        c[LinkBackgroundColor] = mix(blue, b.background, 0.2);
        c[VisitedLinkBackgroundColor] = mix(magenta, b.background, 0.2);
        c[NegativeBackgroundColor] = mix(red, b.background, 0.2);
        c[NeutralBackgroundColor] = mix(yellow, b.background, 0.2);
        c[PositiveBackgroundColor] = mix(green, b.background, 0.2);
        c[FocusColor] = accent;
        c[HoverColor] = accent;
    }
    return palette;
}

std::optional<Source> parse(const QByteArray &text)
{
    if (text.size() > MaxFileBytes || text.contains('\0'))
        return std::nullopt;
    struct Key {
        const char *name;
        QColor Source::*color;
    };
    static const Key colorKeys[] = {
        {"accent", &Source::accent},
        {"background", &Source::background},
        {"foreground", &Source::foreground},
        {"dark_background", &Source::darkBackground},
        {"darker_background", &Source::darkerBackground},
        {"lighter_background", &Source::lighterBackground},
        {"red", &Source::red},
        {"yellow", &Source::yellow},
        {"green", &Source::green},
        {"blue", &Source::blue},
        {"magenta", &Source::magenta},
    };

    Source source;
    std::optional<bool> dark;
    QList<QByteArray> seen;
    for (QByteArray line : text.split('\n')) {
        if (line.endsWith('\r'))
            line.chop(1);
        line = trimmed(line);
        if (line.isEmpty() || line[0] == '#')
            continue;
        // A table: its keys are not the top-level colours.
        if (line[0] == '[')
            break;
        int at = 0;
        while (at < line.size() && bareKeyChar(line[at]))
            ++at;
        if (at == 0)
            return std::nullopt;
        const QByteArray key = line.left(at);
        const QByteArray rest = trimmed(line.mid(at));
        if (rest.isEmpty() || rest[0] != '=')
            return std::nullopt;
        const QByteArray value = trimmed(rest.mid(1));
        if (value.isEmpty())
            return std::nullopt;

        // A multi-line string, even on an unknown key: its lines are not
        // keys and must not be read as such.
        if (value.startsWith("\"\"\"") || value.startsWith("'''"))
            return std::nullopt;

        const Key *known = nullptr;
        for (const Key &candidate : colorKeys) {
            if (key == candidate.name)
                known = &candidate;
        }
        if (!known && key != "mode")
            continue;
        if (seen.contains(key))
            return std::nullopt;
        seen.append(key);
        const std::optional<QByteArray> content = quoted(value);
        if (!content)
            return std::nullopt;
        if (!known) {
            if (*content == "dark")
                dark = true;
            else if (*content == "light")
                dark = false;
            else
                return std::nullopt;
            continue;
        }
        const QColor color = hexColor(*content);
        if (!color.isValid())
            return std::nullopt;
        source.*(known->color) = color;
    }
    if (!source.accent.isValid() || !source.background.isValid() || !source.foreground.isValid())
        return std::nullopt;
    // Text that does not read on the background is no theme to show.
    if (contrast(source.foreground, source.background) < MinTextContrast)
        return std::nullopt;
    source.dark = dark.value_or(luminance(source.background) < 0.18);
    return source;
}

ReadStatus readColorsFile(const QString &themeDir, QByteArray *out)
{
    out->clear();
    const QByteArray dirPath = QFile::encodeName(themeDir);
    const Fd dir(::open(dirPath.constData(), O_RDONLY | O_DIRECTORY | O_CLOEXEC));
    if (dir.get() < 0)
        return (errno == ENOENT || errno == ENOTDIR) ? ReadStatus::Missing : ReadStatus::Refused;
    struct stat info {};
    if (::fstat(dir.get(), &info) != 0 || !ours(info))
        return ReadStatus::Refused;
    const Fd file(::openat(dir.get(), "colors.toml", O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_NOCTTY | O_CLOEXEC));
    if (file.get() < 0)
        return errno == ENOENT ? ReadStatus::Missing : ReadStatus::Refused;
    if (::fstat(file.get(), &info) != 0 || !S_ISREG(info.st_mode) || !ours(info))
        return ReadStatus::Refused;
    if (info.st_size > MaxFileBytes)
        return ReadStatus::TooLarge;
    QByteArray data(int(MaxFileBytes + 1), Qt::Uninitialized);
    qsizetype total = 0;
    while (total < data.size()) {
        const ssize_t got = ::read(file.get(), data.data() + total, size_t(data.size() - total));
        if (got < 0) {
            if (errno == EINTR)
                continue;
            return ReadStatus::Refused;
        }
        if (got == 0)
            break;
        total += got;
    }
    // It grew after the fstat.
    if (total > MaxFileBytes)
        return ReadStatus::TooLarge;
    data.truncate(total);
    *out = data;
    return ReadStatus::Ok;
}

} // namespace HwTheme

ThemeWatcher::ThemeWatcher(const QString &themeDir, QObject *parent)
    : QObject(parent)
    , m_dir(QDir::cleanPath(themeDir))
{
    m_settle.setSingleShot(true);
    m_settle.setInterval(200);
    connect(&m_settle, &QTimer::timeout, this, &ThemeWatcher::reload);
    connect(&m_watcher, &QFileSystemWatcher::fileChanged, this, [this] { m_settle.start(); });
    connect(&m_watcher, &QFileSystemWatcher::directoryChanged, this, [this] { m_settle.start(); });
}

QString ThemeWatcher::defaultThemeDir()
{
    return QDir::homePath() + QLatin1String("/.local/state/omarchy/current/theme");
}

void ThemeWatcher::start()
{
    reload();
}

QStringList ThemeWatcher::watched() const
{
    return m_watcher.files() + m_watcher.directories();
}

void ThemeWatcher::reload()
{
    // Armed before the read: a change during the read is then still seen
    // (review-4 L1); armed after it, the event would go to a removed watch.
    arm();
    QByteArray text;
    HwTheme::ReadStatus status = HwTheme::readColorsFile(m_dir, &text);
    std::optional<HwTheme::Source> source;
    if (status == HwTheme::ReadStatus::Ok) {
        source = HwTheme::parse(text);
        if (!source)
            status = HwTheme::ReadStatus::Malformed;
    }
    if (status != m_status && status != HwTheme::ReadStatus::Ok && status != HwTheme::ReadStatus::Missing) {
        // Never the file's content.
        const char *why = status == HwTheme::ReadStatus::TooLarge ? "too large"
            : status == HwTheme::ReadStatus::Malformed           ? "not in the expected format"
                                                                 : "not a file only you can change";
        qWarning("hearthwire-hyprland: the Omarchy theme's colors.toml is %s; using the built-in colours", why);
    }
    m_status = status;
    if (source != m_source) {
        m_source = source;
        Q_EMIT changed();
    }
}

// Watches what exists of the theme folder, its colors.toml and the two
// folders above it; a swap removes the old ones, so this runs after every
// read.
void ThemeWatcher::arm()
{
    const QStringList old = watched();
    if (!old.isEmpty())
        m_watcher.removePaths(old);
    const QString current = QFileInfo(m_dir).path();
    const QStringList wanted{m_dir + QLatin1String("/colors.toml"), m_dir, current, QFileInfo(current).path()};
    QStringList existing;
    for (const QString &path : wanted) {
        if (QFileInfo::exists(path))
            existing.append(path);
    }
    if (!existing.isEmpty())
        m_watcher.addPaths(existing);
}
