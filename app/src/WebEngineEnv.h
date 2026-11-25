// Qt WebEngine in the app (task 013): the Chat tab's ChatWebView runs in
// Qt WebEngine's own processes with Chromium's sandbox on, always. Two
// things could change that from outside the app's code, and both are shut
// before any WebEngine profile exists:
// - The environment. Qt WebEngine reads every QTWEBENGINE_* variable
//   (QTWEBENGINE_CHROMIUM_FLAGS takes any Chromium switch, such as
//   --no-sandbox; QTWEBENGINE_DISABLE_SANDBOX, QTWEBENGINE_REMOTE_DEBUGGING,
//   QTWEBENGINE_RESOURCES_PATH, QTWEBENGINE_LOCALES_PATH,
//   QTWEBENGINE_DICTIONARIES_PATH, ...) and QTWEBENGINEPROCESS_PATH (which
//   program runs as its renderer). hwStartWebEngine() unsets every
//   variable whose name starts with "QTWEBENGINE" (both families, and any
//   later one) except exactly QTWEBENGINE_ENABLE_LINUX_ACCESSIBILITY
//   (screen readers), plus SSLKEYLOGFILE and the CHROME_* / GOOGLE_*
//   names in hwChromiumVariables, fails closed (fixed line, exit 2) if one
//   remains, and only then calls QtWebEngineQuick::initialize(), before
//   QGuiApplication exists. The QtWebEngineProcess children inherit the
//   cleaned environment.
// - The command line. Qt WebEngine hands the application's arguments to
//   Chromium (all of them, or those after --webEngineArgs). The app refuses
//   --webEngineArgs and the Chromium switches below (one or two dashes,
//   alone or with =value, any letter case) with one fixed line and exit 2,
//   before QGuiApplication; any other unknown option ends at the app's own
//   parser with exit 2, still before the QML engine and any profile.
// The app itself never adds a Chromium switch and never sets a QTWEBENGINE_*
// variable (tests/test_app_sync.py checks app/src).
#pragma once

#include <QtGlobal>
#include <QtWebEngineQuick/qtwebenginequickglobal.h>

#include <unistd.h>

#include <cstdlib>
#include <string>
#include <string_view>
#include <vector>

extern char **environ;

// The one QTWEBENGINE* variable that stays (user decision I3): it only
// switches Qt WebEngine's accessibility support on for screen readers.
inline constexpr std::string_view hwWebEngineKept = "QTWEBENGINE_ENABLE_LINUX_ACCESSIBILITY";

// Other variables Chromium or its sandbox helper reads that write files
// (TLS session keys, logs), pick the sandbox helper or carry Google keys.
// Exact names. Proxy variables (http_proxy, ...) stay: they are the user's
// real network setting.
inline constexpr std::string_view hwChromiumVariables[] = {
    "SSLKEYLOGFILE",
    "CHROME_DEVEL_SANDBOX",
    "CHROME_SANDBOX_DEBUGGING",
    "CHROME_LOG_FILE",
    "GOOGLE_API_KEY",
    "GOOGLE_DEFAULT_CLIENT_ID",
    "GOOGLE_DEFAULT_CLIENT_SECRET",
};

// Whether the app drops this variable: every QTWEBENGINE* name except
// hwWebEngineKept (exact), and the hwChromiumVariables names.
inline bool hwWebEngineVariable(std::string_view name)
{
    constexpr std::string_view prefix("QTWEBENGINE");
    if (name == hwWebEngineKept)
        return false;
    if (name.substr(0, prefix.size()) == prefix)
        return true;
    for (std::string_view exact : hwChromiumVariables) {
        if (name == exact)
            return true;
    }
    return false;
}

inline bool hwUnsetVariable(const char *name)
{
    return qunsetenv(name);
}

// Whether any variable to drop is still in environ.
inline bool hwWebEngineEnvironmentLeft()
{
    for (char **entry = environ; entry && *entry; ++entry) {
        const std::string_view text(*entry);
        if (hwWebEngineVariable(text.substr(0, text.find('='))))
            return true;
    }
    return false;
}

// Drops every variable hwWebEngineVariable names; returns how many names
// were dropped, or -1 when some are still there after the last round (the
// caller must not go on). `unset` is a seam for the test.
inline int hwDropWebEngineEnvironment(bool (*unset)(const char *) = &hwUnsetVariable)
{
    int dropped = 0;
    // Names first, then unset: unsetenv changes environ under the loop.
    // Repeated until none is left (environ may hold a name twice).
    for (int round = 0; round < 8; ++round) {
        std::vector<std::string> names;
        for (char **entry = environ; entry && *entry; ++entry) {
            const std::string_view text(*entry);
            const std::string_view name = text.substr(0, text.find('='));
            if (hwWebEngineVariable(name))
                names.emplace_back(name);
        }
        if (names.empty())
            return dropped;
        for (const std::string &name : names)
            unset(name.c_str());
        dropped += int(names.size());
    }
    return hwWebEngineEnvironmentLeft() ? -1 : dropped;
}

// The Chromium switches the app refuses on its command line (lower case,
// without dashes): every one would weaken the sandbox, the site isolation,
// what the renderer runs or where data goes.
inline constexpr std::string_view hwChromiumSwitches[] = {
    "webengineargs",
    "no-sandbox",
    "disable-seccomp-filter-sandbox",
    "disable-namespace-sandbox",
    "disable-setuid-sandbox",
    "disable-gpu-sandbox",
    "single-process",
    "in-process-gpu",
    "no-zygote",
    "remote-debugging-port",
    "remote-debugging-pipe",
    "remote-debugging-address",
    "remote-allow-origins",
    "disable-web-security",
    "disable-site-isolation-trials",
    "allow-running-insecure-content",
    "ignore-certificate-errors",
    "user-data-dir",
    "renderer-cmd-prefix",
    "utility-cmd-prefix",
    "gpu-launcher",
    "browser-subprocess-path",
    "js-flags",
    "enable-logging",
    "log-file",
    "proxy-server",
    "proxy-pac-url",
    "host-resolver-rules",
    "load-extension",
    "ssl-key-log-file",
    "log-net-log",
    "net-log-capture-mode",
    "enable-features",
    "disable-features",
    "unsafely-treat-insecure-origin-as-secure",
    "allow-file-access-from-files",
    "allow-insecure-localhost",
};

// Whether argv holds --webEngineArgs or one of hwChromiumSwitches: the app
// does not start then.
inline bool hwRefusedChromiumArgument(int argc, char **argv)
{
    for (int i = 1; i < argc; ++i) {
        if (!argv[i])
            continue;
        std::string_view word(argv[i]);
        if (word.substr(0, 2) == "--")
            word.remove_prefix(2);
        else if (word.substr(0, 1) == "-")
            word.remove_prefix(1);
        else
            continue;
        std::string name(word.substr(0, word.find('=')));
        for (char &c : name) {
            if (c >= 'A' && c <= 'Z')
                c = char(c - 'A' + 'a');
        }
        for (std::string_view refused : hwChromiumSwitches) {
            if (name == refused)
                return true;
        }
    }
    return false;
}

// The one line printed when the environment could not be cleaned.
inline constexpr char hwEnvironmentFailedLine[] =
    "hearthwire-hyprland: the Qt WebEngine environment could not be cleaned; not starting\n";

// The app's one way to start Qt WebEngine: the environment first (fail
// closed: if variables remain, one fixed line and exit 2, `initialize` not
// called), then `initialize` (QtWebEngineQuick::initialize; a test hands in
// a probe that looks at the environment and then calls it). Before
// QGuiApplication.
inline void hwStartWebEngine(void (*initialize)() = &QtWebEngineQuick::initialize,
                             bool (*unset)(const char *) = &hwUnsetVariable)
{
    if (hwDropWebEngineEnvironment(unset) < 0) {
        const ssize_t ignored = ::write(2, hwEnvironmentFailedLine, sizeof(hwEnvironmentFailedLine) - 1);
        (void)ignored;
        std::_Exit(2);
    }
    initialize();
}
