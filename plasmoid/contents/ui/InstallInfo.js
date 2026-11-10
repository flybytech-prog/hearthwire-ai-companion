.pragma library

// Where the running helper and widget come from (`--install-info`), read
// once at start. Pure helpers only: the widget runs the command built here
// and shows a fixed notice when a leftover script install in the home
// folder shadows the system package. The reply carries no paths or text;
// anything but the exact documented keys and words means unknown.

var VERSION = 1
var MAX_REPLY_CHARS = 4096
var HELPERS = ["user", "system", "other"]
var DISTROS = ["arch", "fedora", "debian", "other"]
var FLAGS = ["system_helper", "user_helper", "user_plasmoid", "system_plasmoid"]
var KEYS = ["ok", "install_info_version", "helper"].concat(FLAGS).concat(["distro"])

// Not known (yet, or a reply that isn't exactly the contract's): no notice,
// and the install hints name only the tools.
var UNKNOWN = {
    known: false,
    helper: "",
    system_helper: false,
    user_helper: false,
    user_plasmoid: false,
    system_plasmoid: false,
    distro: "other",
    shadowed: false
}

function validInt(value) {
    return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 2147483648
}

// Same shape as ChatStorage.helperPrefix: the env words only make the
// DataSource source name unique; the helper ignores them. -s, here only:
// the system package answers even when an older home-folder copy (which
// doesn't know --install-info) would; it still finds that copy. Without a
// system package the run fails, which is unknown: nothing is shadowed.
function command(run, applet) {
    if (!validInt(run) || !validInt(applet))
        return ""
    return "env HEARTHWIRE_RUN=" + run + " HEARTHWIRE_APPLET=" + applet + " python3 -P -s -m hearthwire --install-info"
}

// A script install in the home folder next to a system package: Python and
// Plasma both prefer the home folder's copy.
function isShadowed(info) {
    if (!info || typeof info !== "object")
        return false
    return (info.user_helper === true && info.system_helper === true)
        || (info.user_plasmoid === true && info.system_plasmoid === true)
}

function unknown() {
    return Object.assign({}, UNKNOWN)
}

// Exit code 0 and stdout that is exactly one contract object; else UNKNOWN.
function parseReply(exitCode, stdout) {
    if (exitCode !== 0 || typeof stdout !== "string" || stdout.length > MAX_REPLY_CHARS)
        return unknown()
    var reply
    try {
        reply = JSON.parse(stdout)
    } catch (error) {
        return unknown()
    }
    if (!reply || typeof reply !== "object" || Array.isArray(reply))
        return unknown()
    var keys = Object.keys(reply)
    if (keys.length !== KEYS.length || !KEYS.every(function (key) { return keys.indexOf(key) >= 0 }))
        return unknown()
    if (reply.ok !== true || reply.install_info_version !== VERSION
            || HELPERS.indexOf(reply.helper) < 0 || DISTROS.indexOf(reply.distro) < 0
            || !FLAGS.every(function (flag) { return typeof reply[flag] === "boolean" }))
        return unknown()
    var info = {known: true, helper: reply.helper, distro: reply.distro}
    FLAGS.forEach(function (flag) { info[flag] = reply[flag] })
    info.shadowed = isShadowed(info)
    return info
}
