// The app's Plasmoid.configuration: the plasmoid's main.xml keys and
// defaults in a QQmlPropertyMap, kept in settings.json. It copies what
// Plasma 6's KConfigPropertyMap does that the plasmoid depends on:
// - a QML write is stored at once (Plasma's applet config autosaves);
// - after each write or writeConfig() every key emits valueChanged again,
//   changed or not, backupAutoExport last (the lab log of task 007).
// - every key also has a read-only "<key>Default" entry, which is how the
//   settings dialog fills the pages' cfg_<key>Default properties.
//
// The file (plan-v1 §2.4/§5; read by the helper's core/appconfig.py for a
// backup, which refuses anything more open than 0700/0600):
//   $XDG_CONFIG_HOME (absolute, else ~/.config)/hearthwire-hyprland/settings.json
//   {"format":"hearthwire-app-settings","version":1,
//    "settings":{"<main.xml key>": <Bool|Int|String>, ...},
//    "app":{"background":false,"agentsPanel":false,"tray":false}}
// Writing: the folder is created 0700 (and set to exactly 0700 whatever the
// umask), opened without following a link, must be ours and have no
// permission bit beyond 0700 (an existing folder is never loosened or
// tightened unless it passed that check); the
// file is written to a new 0600 temp file in that folder, synced, and
// renamed over settings.json (then the folder is synced), so a reader sees
// the old file or the new one, never a part. More than MaxFileBytes is not
// saved.
// Reading: the file is untrusted. A link, a file or folder that is not
// ours, a folder with a permission bit beyond 0700 or a file with one beyond
// 0600 (as the helper's appconfig; set-id and sticky bits ignored), a
// config base folder ($XDG_CONFIG_HOME or ~/.config; a link to it is fine)
// that is not ours, not a regular file, or larger than MaxFileBytes is
// "unreadable":
// defaults, and nothing is ever saved over it. A file that is not the
// format (bad JSON included) is "damaged": defaults, and it is kept as
// settings.json.damaged before the next save. Unknown keys are dropped,
// values of the wrong JSON type (a Bool must be true/false, an Int a 32-bit
// integer, a String a string) keep the default and are counted.
#pragma once

#include <QHash>
#include <QJsonValue>
#include <QQmlPropertyMap>
#include <QStringList>
#include <QVariant>

class ConfigStore : public QQmlPropertyMap
{
    Q_OBJECT
    // Full re-emit passes so far (tests and the fixture checks read it).
    Q_PROPERTY(int reemitCount READ reemitCount NOTIFY reemitted)

public:
    enum class Status { Missing, Ok, Damaged, Unreadable };
    Q_ENUM(Status)

    static constexpr qint64 MaxFileBytes = 1024 * 1024;
    // A StringList key (chatHttpWarnedSites): at most this many entries of
    // at most this many characters; a stored list beyond that is dropped
    // whole (the default stays), a QML write beyond it is refused.
    static constexpr qsizetype MaxListEntries = 1000;
    static constexpr qsizetype MaxListEntryChars = 512;

    explicit ConfigStore(QObject *parent = nullptr);

    // <XDG config home>/hearthwire-hyprland/settings.json, as the helper finds it.
    static QString defaultFile();

    // main.xml as KConfigXT reads it: entries with String, Int, Bool or StringList type.
    bool loadSchema(const QString &path);
    // Reads `file` (missing = all defaults) and saves there from now on
    // unless it was unreadable. True unless unreadable or damaged.
    bool open(const QString &file);
    Status status() const { return m_status; }
    // Values of the wrong type found by open().
    int dropped() const { return m_dropped; }
    // The "app" object's flags (not main.xml keys; never in a backup).
    bool appFlag(const QString &name) const { return m_app.value(name, false).toBool(); }

    // Each key's "<key>Default" entry, then the key, in main.xml order.
    Q_INVOKABLE QStringList keys() const;
    Q_INVOKABLE void writeConfig();
    Q_INVOKABLE QVariant defaultValue(const QString &key) const { return m_defaults.value(key); }

    // Saves now; false when not saved (unreadable file, unsafe folder, too
    // large, or an OS error).
    bool save();

    int reemitCount() const { return m_reemits; }

Q_SIGNALS:
    void reemitted();

protected:
    QVariant updateValue(const QString &key, const QVariant &input) override;

private:
    QVariant coerce(const QString &key, const QVariant &value, bool *ok) const;
    bool fromFile(const QString &key, const QJsonValue &value, QVariant *out) const;
    QByteArray document() const;
    void scheduleSave();
    void reemitAll();

    QStringList m_order;
    QHash<QString, QString> m_types;
    QHash<QString, QVariant> m_defaults;
    QVariantHash m_app;
    QString m_file;
    Status m_status = Status::Missing;
    bool m_writable = false;
    bool m_moveDamaged = false;
    bool m_pending = false;
    int m_dropped = 0;
    int m_reemits = 0;
};
