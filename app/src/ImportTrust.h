// Which QML import folders the app trusts (task 012 R3.5, review-4-security
// INFO 1). UrlGuard lets QML, JS and qmldir files load from the local
// folders of the import path list. So each local import folder is checked
// before the engine gets the list, and dropped (fail closed) unless every
// folder on its way, from / down to the import folder itself:
// - is reached without a link: the canonical path is walked one name at a
//   time with openat(O_PATH | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC) and
//   fstat on what was opened, so a link swapped in after the
//   canonicalisation makes the walk fail;
// - is owned by root or the session user;
// - is not group- or other-writable (a POSIX ACL with a named writer shows
//   as a group-writable mask, so it is dropped too).
// The one exception: a folder above it (never the folder itself) that is
// root-owned and sticky, as /tmp: others may add names there but can't
// replace ours.
// Only that path is checked: what is inside an import folder (its module
// folders, qmldir, .qml and plugin files) is trusted as installed. With the
// import folder itself root- or user-owned and not writable by others,
// nobody else can add or rename entries directly in it, but a group- or
// other-writable module folder below it would not be noticed
// (review-6 L5; a bounded check of the modules used is left for later).
// A folder that is missing or can't be checked is dropped. qrc: entries
// (the compiled-in modules) pass as they are. Qt's own folder
// (/usr/lib/qt6/qml) is root-owned on a normal system; if it is dropped,
// QtQuick can't load and the app ends with exit 3: fail closed, on purpose.
// Note: under a user namespace where root is not mapped (some sandboxes),
// root's folders appear as the overflow uid and are dropped too.
//
// The app applies this in main.cpp, after hwImportPaths(), before
// setImportPathList(); UrlGuard gets the filtered list. qt.conf is task 017.
#pragma once

#include <QList>
#include <QString>
#include <QStringList>

#include <sys/types.h>

// Whose folders are trusted. The app: root = {0}, user = getuid(). Tests
// pass the uid root appears as, or count one of their own as root.
struct HwImportOwners {
    // Owners that count as root (only their sticky folders may be writable).
    QList<uid_t> root;
    // The session user.
    uid_t user = 0;
};

// A local folder that may hold QML the app loads: its canonical path (the
// place that was checked), or empty when it is dropped.
QString hwTrustedFolder(const QString &folder, const HwImportOwners &owners);

// `paths` with every untrusted local folder dropped: qrc: entries as they
// are, local folders as their canonical path (the place that was checked).
// `dropped` (optional) gets how many were dropped.
QStringList hwTrustedImportPaths(const QStringList &paths, const HwImportOwners &owners, int *dropped = nullptr);

// The app's form: root = 0, the session user = getuid(); logs one fixed
// line with the count when something is dropped (never a path).
QStringList hwTrustedImportPaths(const QStringList &paths);
