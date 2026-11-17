// What the app's DataSource may run: only the helper, the way the plasmoid's
// JS builders spell it, and nothing a shell would read differently.
//
//   [env (HEARTHWIRE_RUN|HEARTHWIRE_APPLET)=<digits> ...] python3 -P [-s] -m hearthwire --<option> ...
//
// Plasma runs such a source through /bin/sh -c; the app never starts a
// shell. parse() splits the source the way sh would for exactly this
// shape: words of [A-Za-z0-9_=,.:/+-] or one whole '...' word (printable
// ASCII), separated by single spaces. Anything else (another program, other
// env words, $, `, ;, |, globs, quotes inside a word, tabs, newlines) is
// refused, so the helper is the only program that can run and nothing on
// the command line can choose the front end (HEARTHWIRE_FRONTEND).
#pragma once

#include <QList>
#include <QPair>
#include <QString>
#include <QStringList>

struct HelperCommand
{
    bool ok = false;
    // The python3 arguments: -P [-s] -m hearthwire <helper options>.
    QStringList arguments;
    // The env words, in order (only make the source name unique; Plasma's
    // sh would have put them into the child's environment too).
    QList<QPair<QString, QString>> environment;

    static HelperCommand parse(const QString &source);

    // Longest source and most words accepted (a --read-dropped path is at
    // most 8192 hex digits).
    static constexpr int MaxLength = 16384;
    static constexpr int MaxWords = 256;
};
