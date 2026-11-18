// The bus tests' guard (task 012 R3): they run only on the private bus
// dbus-run-session started from tests/dbus-session.conf, never on a
// session bus of the host. Checked before any connection is made.
#pragma once

#include <QByteArray>

// HW_TEST_BUS_DIR: the build tree's bus folder (CMake).
inline bool hwOnPrivateBus()
{
    const QByteArray address = qgetenv("DBUS_SESSION_BUS_ADDRESS");
    // ';' would add another address that libdbus tries next
    // (review-6-security INFO-6): exactly one address.
    if (address.isEmpty() || address.contains(';') || address.contains("/run/user/") || address.contains("abstract=")
        || address.contains("tmpdir=") || address.contains("runtime="))
        return false;
    return address.startsWith("unix:path=" HW_TEST_BUS_DIR "/");
}

inline const char *hwPrivateBusMessage()
{
    return "DBUS_SESSION_BUS_ADDRESS is not the test's private bus (dbus-run-session with tests/dbus-session.conf); "
           "refusing to touch any other bus";
}
