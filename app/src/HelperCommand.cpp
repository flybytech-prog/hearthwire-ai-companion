#include "HelperCommand.h"

namespace {
bool plainChar(QChar c)
{
    const ushort u = c.unicode();
    return (u >= 'a' && u <= 'z') || (u >= 'A' && u <= 'Z') || (u >= '0' && u <= '9') || u == '_' || u == '='
        || u == ',' || u == '.' || u == ':' || u == '/' || u == '+' || u == '-';
}

bool quotedChar(QChar c)
{
    const ushort u = c.unicode();
    return u >= 0x20 && u <= 0x7e && u != '\'';
}

// sh's words for the accepted alphabet, or false.
bool split(const QString &source, QStringList *words)
{
    const qsizetype n = source.size();
    qsizetype i = 0;
    while (i < n) {
        QString word;
        if (source.at(i) == QLatin1Char('\'')) {
            const qsizetype end = source.indexOf(QLatin1Char('\''), i + 1);
            if (end < 0)
                return false;
            word = source.mid(i + 1, end - i - 1);
            for (const QChar c : std::as_const(word)) {
                if (!quotedChar(c))
                    return false;
            }
            i = end + 1;
        } else {
            const qsizetype start = i;
            while (i < n && plainChar(source.at(i)))
                ++i;
            if (i == start)
                return false;
            word = source.mid(start, i - start);
        }
        // A word ends at one space, or at the end; never two spaces, a
        // leading or a trailing one, or a quote glued to a word.
        if (i < n) {
            if (source.at(i) != QLatin1Char(' ') || i + 1 == n)
                return false;
            ++i;
        }
        words->append(word);
        if (words->size() > HelperCommand::MaxWords)
            return false;
    }
    return !words->isEmpty();
}

bool digits(const QString &text)
{
    if (text.isEmpty() || text.size() > 10)
        return false;
    for (const QChar c : text) {
        if (c < QLatin1Char('0') || c > QLatin1Char('9'))
            return false;
    }
    return true;
}
}

HelperCommand HelperCommand::parse(const QString &source)
{
    HelperCommand result;
    QStringList words;
    if (source.size() > MaxLength || !split(source, &words))
        return result;
    qsizetype at = 0;
    if (words.at(0) == QLatin1String("env")) {
        at = 1;
        while (at < words.size() && words.at(at).contains(QLatin1Char('='))) {
            const QString word = words.at(at);
            const qsizetype eq = word.indexOf(QLatin1Char('='));
            const QString name = word.left(eq);
            const QString value = word.mid(eq + 1);
            if ((name != QLatin1String("HEARTHWIRE_RUN") && name != QLatin1String("HEARTHWIRE_APPLET")) || !digits(value))
                return HelperCommand();
            for (const auto &pair : std::as_const(result.environment)) {
                if (pair.first == name)
                    return HelperCommand();
            }
            result.environment.append({name, value});
            ++at;
        }
        if (result.environment.isEmpty())
            return HelperCommand();
    }
    // python3 -P [-s] -m hearthwire
    if (at >= words.size() || words.at(at) != QLatin1String("python3"))
        return HelperCommand();
    ++at;
    if (at >= words.size() || words.at(at) != QLatin1String("-P"))
        return HelperCommand();
    result.arguments << words.at(at++);
    if (at < words.size() && words.at(at) == QLatin1String("-s"))
        result.arguments << words.at(at++);
    if (at + 1 >= words.size() || words.at(at) != QLatin1String("-m") || words.at(at + 1) != QLatin1String("hearthwire"))
        return HelperCommand();
    result.arguments << words.at(at) << words.at(at + 1);
    at += 2;
    // The helper's own options: at least one, and the first is an option.
    if (at >= words.size() || !words.at(at).startsWith(QLatin1String("--")))
        return HelperCommand();
    for (; at < words.size(); ++at)
        result.arguments << words.at(at);
    result.ok = true;
    return result;
}
