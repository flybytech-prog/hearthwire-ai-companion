.pragma library

// Saved sign-ins for the Chat tab ("Stay signed in"). Pure helpers only: the
// plasmoid runs the commands built here and maps the helper's short replies
// to what the Chat tab shows. Commands carry only fixed words and integers;
// a value that fails validation gives "" and the caller runs nothing.

var MODES = ["memory", "encrypted"]
var MAX_INT = 2147483648

var VAULT_OPERATIONS = ["status", "create", "unlock", "lock", "change-passphrase", "destroy",
                        "add-key", "remove-key", "auto-unlock"]
// How the folder is unlocked (Settings → General → Unlock with).
var UNLOCK_METHODS = ["passphrase", "wallet"]
// The operations that take --method; add-key and remove-key need wallet.
var METHOD_OPERATIONS = ["unlock", "add-key", "remove-key"]
var VAULT_STATES = ["absent", "locked", "unlocked", "unavailable", "damaged"]
// The wallet key slot, as status reports it with locked and unlocked.
var WALLET_STATES = ["set-up", "off", "unavailable"]
var MISSING_TOOLS = ["gocryptfs", "gocryptfs-v2", "kdialog", "fusermount3"]
// Tools only the KDE Wallet unlock needs (reported with locked/unlocked).
var WALLET_TOOLS = ["kwallet-query", "qdbus6", "openssl"]
// The packages that provide each missing tool, per distro family as
// --install-info reports it, exactly as the packaging files name them
// (packaging/arch/PKGBUILD optdepends, packaging/fedora/hearthwire.spec and
// packaging/debian/control Suggests). "other" (or not known yet) names only
// the tools, for any package manager.
var TOOL_PACKAGES = {
    "arch": {
        "gocryptfs": "gocryptfs",
        "gocryptfs-v2": "gocryptfs",
        "kdialog": "kdialog",
        "fusermount3": "fuse3",
        "kwallet-query": "kwallet",
        "qdbus6": "qt6-tools",
        "openssl": "openssl"
    },
    "fedora": {
        "gocryptfs": "gocryptfs",
        "gocryptfs-v2": "gocryptfs",
        "kdialog": "kdialog",
        "fusermount3": "fuse3",
        "kwallet-query": "kf6-kwallet",
        "qdbus6": "qt6-qttools",
        "openssl": "openssl"
    },
    "debian": {
        "gocryptfs": "gocryptfs",
        "gocryptfs-v2": "gocryptfs",
        "kdialog": "kdialog",
        "fusermount3": "fuse3",
        "kwallet-query": "kwallet6",
        "qdbus6": "qdbus-qt6",
        "openssl": "openssl"
    },
    "other": {
        "gocryptfs": "gocryptfs",
        "gocryptfs-v2": "gocryptfs",
        "kdialog": "kdialog",
        "fusermount3": "fusermount3",
        "kwallet-query": "kwallet-query",
        "qdbus6": "qdbus6",
        "openssl": "openssl"
    }
}
// Each family's own package manager; "other" has none.
var INSTALL_COMMANDS = {
    "arch": "sudo pacman -S --needed",
    "fedora": "sudo dnf install",
    "debian": "sudo apt install"
}
var HELPER_ERRORS = [
    "symlink", "not-owned", "not-directory", "os-error", "missing-tool", "exists",
    "absent", "cancelled", "wrong-passphrase", "empty-passphrase", "init-failed",
    "mount-failed", "not-verified", "stale-mount", "busy", "not-locked", "no-runtime-dir",
    "damaged", "not-set-up", "wallet-disabled", "wallet-closed", "wallet-failed",
    "wallet-mismatch", "wallet-write-failed", "legacy-data"
]

// Only the exact word "wallet" means KDE Wallet; anything else (including
// a later "fido2" this version doesn't know) is the passphrase.
function normalizeUnlockMethod(value) {
    return value === "wallet" ? "wallet" : "passphrase"
}

// The method the Chat tab's Unlock uses: KDE Wallet only when it is chosen
// in the settings and the helper says its key slot is set up.
function effectiveUnlockMethod(setting, wallet) {
    return normalizeUnlockMethod(setting) === "wallet" && wallet === "set-up" ? "wallet" : "passphrase"
}

// What Settings → General → Unlock with shows: the real key slot (KDE
// Wallet while one is set up), and whether a set-up slot is not applied
// (the setting still says Passphrase, e.g. the page was closed without
// Apply).
function walletChoice(setting, wallet) {
    var slot = wallet === "set-up"
    return { shown: slot ? "wallet" : "passphrase",
             notApplied: slot && normalizeUnlockMethod(setting) !== "wallet" }
}

// Anything but the exact word "encrypted" (including the old "folder") means
// the private in-memory profile.
function normalizeMode(value) {
    return value === "encrypted" ? "encrypted" : "memory"
}

// A plain integer 0..2**31, else -1.
function validInt(value) {
    if (typeof value !== "number" || !Number.isInteger(value) || value < 0 || value > MAX_INT)
        return -1
    return value
}

function normalizeGeneration(value) {
    return Math.max(0, validInt(value))
}

function nextGeneration(generation) {
    var current = validInt(generation)
    return current < 0 || current >= MAX_INT ? 0 : current + 1
}

function profileName(applet, generation) {
    if (validInt(applet) < 0 || validInt(generation) < 0)
        return ""
    return "applet-" + applet + "-g" + generation
}

// First run number for a widget or settings page: the clock plus a random
// part, so two pages (or widgets) started together don't share source names.
function firstRun(now, random) {
    var clock = typeof now === "number" && isFinite(now) ? Math.abs(Math.floor(now)) : 0
    var extra = typeof random === "number" && random >= 0 && random < 1
        ? Math.floor(random * MAX_INT) : 0
    return (clock % MAX_INT + extra) % MAX_INT
}

function nextRun(run) {
    return nextGeneration(run)
}

// Both env words only make the DataSource source name unique across widgets
// and pages (the executable engine shares sources by name); the helper
// ignores them.
function helperPrefix(run, applet) {
    if (validInt(run) < 0 || validInt(applet) < 0)
        return ""
    return "env HEARTHWIRE_RUN=" + run + " HEARTHWIRE_APPLET=" + applet + " python3 -P -m hearthwire"
}

// op "prepare" needs a generation; op "remove" keeps generation `keep` when it
// is a valid integer and removes every generation otherwise.
function webDataCommand(op, store, applet, generation, keep, run) {
    var prefix = helperPrefix(run, applet)
    if (prefix === "" || store !== "encrypted" || validInt(applet) < 0)
        return ""
    var command = prefix + " --web-data " + op + " --store encrypted --applet " + applet
    if (op === "prepare") {
        if (validInt(generation) < 0)
            return ""
        return command + " --generation " + generation
    }
    if (op === "remove") {
        if (keep === undefined || keep === null)
            return command
        if (validInt(keep) < 0)
            return ""
        return command + " --keep " + keep
    }
    return ""
}

// method: undefined or "" for none; unlock takes passphrase (the default,
// left out) or wallet; add-key and remove-key take wallet only.
function vaultCommand(op, run, applet, method) {
    var prefix = helperPrefix(run, applet)
    if (prefix === "" || VAULT_OPERATIONS.indexOf(op) < 0)
        return ""
    var command = prefix + " --vault " + op
    var none = method === undefined || method === null || method === ""
    if (op === "add-key" || op === "remove-key")
        return method === "wallet" ? command + " --method wallet" : ""
    if (none)
        return command
    if (op !== "unlock" || UNLOCK_METHODS.indexOf(method) < 0)
        return ""
    return method === "wallet" ? command + " --method wallet" : command
}

// The helper's stdout, reduced to known words. Anything unexpected is
// {ok: false, error: "bad-reply"}; an unknown error code becomes "failed".
function parseReply(stdout) {
    var bad = {ok: false, error: "bad-reply"}
    var reply
    try {
        reply = JSON.parse(String(stdout === undefined || stdout === null ? "" : stdout))
    } catch (error) {
        return bad
    }
    if (!reply || typeof reply !== "object" || Array.isArray(reply))
        return bad
    if (reply.ok === false) {
        var code = typeof reply.error === "string" && HELPER_ERRORS.indexOf(reply.error) >= 0
            ? reply.error : "failed"
        return {ok: false, error: code}
    }
    if (reply.ok !== true)
        return bad
    if (reply.state === undefined)
        return {ok: true}
    if (VAULT_STATES.indexOf(reply.state) < 0)
        return bad
    var result = {ok: true, state: reply.state}
    if (reply.state === "locked" || reply.state === "unlocked") {
        // An older or odd reply never offers the wallet.
        result.wallet = WALLET_STATES.indexOf(reply.wallet) >= 0 ? reply.wallet : "unavailable"
        var walletMissing = Array.isArray(reply.missing) ? reply.missing : []
        result.missing = WALLET_TOOLS.filter(function (name) {
            return walletMissing.indexOf(name) >= 0
        })
    }
    if (reply.state === "unavailable") {
        var missing = Array.isArray(reply.missing) ? reply.missing : []
        result.missing = MISSING_TOOLS.filter(function (name) {
            return missing.indexOf(name) >= 0
        })
        if (result.missing.length === 0)
            result.missing = ["gocryptfs"]
    }
    return result
}

function replyFor(exitCode, stdout) {
    if (exitCode !== 0)
        return {ok: false, error: "bad-reply"}
    return parseReply(stdout)
}

// "file:///run/user/1000" or "/run/user/1000" → "/run/user/1000"; anything
// relative, odd or undecodable → "".
function localPath(value) {
    var text = String(value === undefined || value === null ? "" : value)
    if (text.indexOf("file://") === 0) {
        try {
            text = decodeURIComponent(text.slice(7))
        } catch (error) {
            return ""
        }
    }
    if (text.charAt(0) !== "/" || /[\u0000-\u001f\u007f]/.test(text))
        return ""
    var parts = text.split("/")
    for (var index = 0; index < parts.length; index++) {
        if (parts[index] === "." || parts[index] === "..")
            return ""
    }
    while (text.length > 1 && text.charAt(text.length - 1) === "/")
        text = text.slice(0, -1)
    return text === "/" ? "" : text
}

// Profile folder inside the helper's verified mount; "" when unknown.
function profilePath(runtimeDir, applet, generation) {
    var base = localPath(runtimeDir)
    var name = profileName(applet, generation)
    if (base === "" || name === "")
        return ""
    return base + "/hearthwire/vault/web/" + name
}

// The table for a reported distro family; anything else is "other".
function installDistro(distro) {
    return typeof distro === "string" && distro !== "other"
        && Object.prototype.hasOwnProperty.call(INSTALL_COMMANDS, distro) ? distro : "other"
}

// Whether installCommand gives a command to run (else only the tool names).
function hasInstallCommand(distro) {
    return installDistro(distro) !== "other"
}

// The install command for the missing tools on this distro family, or for
// "other" just the tool names; gocryptfs when none is known.
function installCommand(missing, distro) {
    var family = installDistro(distro)
    var table = TOOL_PACKAGES[family]
    var names = Array.isArray(missing) ? missing : []
    var packages = []
    var tools = MISSING_TOOLS.concat(WALLET_TOOLS)
    for (var index = 0; index < tools.length; index++) {
        var tool = tools[index]
        if (names.indexOf(tool) >= 0 && packages.indexOf(table[tool]) < 0)
            packages.push(table[tool])
    }
    if (packages.length === 0)
        packages.push(table["gocryptfs"])
    return family === "other" ? packages.join(" ") : INSTALL_COMMANDS[family] + " " + packages.join(" ")
}

// Helper error → message code the Chat tab shows ("" = nothing to say).
function messageFor(error) {
    switch (error) {
    case "":
    case undefined:
    case null:
    case "cancelled":
    case "empty-passphrase":
        return ""
    case "wrong-passphrase":
    case "busy":
    case "lock-busy":
    case "missing-tool":
    case "exists":
    case "prepare-failed":
    case "remove-failed":
    case "cleared":
    case "auto-locked":
    case "damaged":
    case "not-set-up":
    case "wallet-disabled":
    case "wallet-failed":
    case "wallet-mismatch":
    case "wallet-write-failed":
    // Saved data of the previous version is still waiting for the installer.
    case "legacy-data":
        return error
    // Plasma start found the wallet closed: the card just offers Unlock.
    case "wallet-closed":
        return ""
    case "not-verified":
    case "stale-mount":
    case "mount-failed":
        return "mount-failed"
    default:
        return "failed"
    }
}

// What the Chat tab shows instead of (or as) the web view.
// input: {mode, state, op, error, hold, privateSession, ready}
// view: "web" | "busy" | "create" | "unlock" | "install" | "held" | "retry"
//       | "damaged".
function cardFor(input) {
    var value = input || {}
    if (normalizeMode(value.mode) !== "encrypted" || value.privateSession === true
            || value.ready === true)
        return {view: "web", message: ""}
    var op = typeof value.op === "string" ? value.op : ""
    if (op !== "")
        return {view: "busy", message: op}
    var message = messageFor(value.error)
    switch (value.state) {
    case "":
    case undefined:
    case null:
        return {view: "busy", message: "status"}
    case "unavailable":
        return {view: "install", message: ""}
    case "absent":
        return {view: "create", message: message}
    case "damaged":
        // The card says so itself; other messages (e.g. busy) still show.
        return {view: "damaged", message: message === "damaged" ? "" : message}
    case "locked":
        return {view: "unlock", message: message}
    case "unlocked":
        if (value.hold === true)
            return {view: "held", message: message}
        return {view: "retry", message: message !== "" ? message : "prepare-failed"}
    default:
        return {view: "retry", message: message !== "" ? message : "failed"}
    }
}

// --- Lock automatically ---------------------------------------------------
//
// Minutes the saved web chat may stay out of sight before the folder is
// locked; 0 = never. Anything else (odd or hand-edited values) is "never".

var AUTO_LOCK_MINUTES = [0, 1, 5, 15, 30, 60, 480, 1440]

function normalizeAutoLock(value) {
    return AUTO_LOCK_MINUTES.indexOf(validInt(value)) >= 0 ? value : 0
}

function autoLockInterval(minutes) {
    return normalizeAutoLock(minutes) * 60000
}

// How often the idle time is checked: a quarter of the interval, at most
// every 30 s, so a sleeping computer is caught soon after it wakes.
function autoLockCheckInterval(minutes) {
    var interval = autoLockInterval(minutes)
    return interval === 0 ? 0 : Math.min(30000, Math.max(1000, Math.floor(interval / 4)))
}

// context: {armed, minutes, idleSince, now, busy}. idleSince and now are
// wall-clock milliseconds, so time asleep counts as idle.
// "" = nothing to do, "lock" = lock now, "wait" = due but a helper step or
// dialog is running (check again once it ends), "restart" = the clock went
// back: count from now.
function autoLockStep(context) {
    var value = context || {}
    var interval = autoLockInterval(value.minutes)
    var since = value.idleSince
    var now = value.now
    if (value.armed !== true || interval === 0 || typeof since !== "number" || !(since > 0)
            || typeof now !== "number" || !isFinite(now))
        return ""
    if (now < since)
        return "restart"
    if (now - since < interval)
        return ""
    return value.busy === true ? "wait" : "lock"
}

// --- Helper step queue (main.qml runs one step at a time) ----------------
//
// Steps: "status", "create", "unlock" (passphrase), "unlock-wallet",
// "auto-unlock" (Plasma start only), "add-key" (wallet set-up again from the
// card), "lock", "prepare", "keep", "remove",
// "wait", "destroy" (damaged folder only) while Stay signed in is on, and the leave-* steps queued when it is
// turned off. Leave steps delete the encrypted folder, so they only ever run
// while the mode is still off.

var LEAVE_STEPS = ["leave-wait", "leave-remove", "leave-lock", "leave-status", "leave-destroy"]
// Steps that only make sense while Stay signed in is on.
var ENCRYPTED_STEPS = ["create", "unlock", "unlock-wallet", "auto-unlock", "add-key", "prepare", "keep"]

function isLeaveStep(step) {
    return LEAVE_STEPS.indexOf(step) >= 0
}

// The queue with `steps` added. A status already queued (or running, unless
// `fresh` is true) isn't added twice; leave steps already queued aren't either.
function enqueueSteps(queue, steps, running, fresh) {
    var result = Array.isArray(queue) ? queue.slice() : []
    var added = Array.isArray(steps) ? steps : []
    for (var index = 0; index < added.length; index++) {
        var step = added[index]
        if (typeof step !== "string" || step === "")
            continue
        if (step === "status" && (result.indexOf("status") >= 0
                || (fresh !== true && running === "status")))
            continue
        if (isLeaveStep(step) && result.indexOf(step) >= 0)
            continue
        result.push(step)
    }
    return result
}

// The queue without steps that no longer apply to `mode`.
function queueForMode(queue, mode) {
    var encrypted = normalizeMode(mode) === "encrypted"
    return (Array.isArray(queue) ? queue : []).filter(function (step) {
        return encrypted ? !isLeaveStep(step) : ENCRYPTED_STEPS.indexOf(step) < 0
    })
}

// Whether `step` should be skipped now.
// context: {mode, state, wantsSaved, wallet, hold}
function dropStep(step, context) {
    var value = context || {}
    var encrypted = normalizeMode(value.mode) === "encrypted"
    if (isLeaveStep(step))
        return encrypted || (step === "leave-destroy"
            && (value.state === "absent" || value.state === "unavailable"))
    if (ENCRYPTED_STEPS.indexOf(step) >= 0 && !encrypted)
        return true
    if (step === "prepare")
        return value.wantsSaved !== true
    // Silent unlock at Plasma start: only a locked folder with a wallet slot,
    // and never after the user locked it.
    if (step === "auto-unlock")
        return value.state !== "locked" || value.wallet !== "set-up" || value.hold === true
    // The Chat tab only deletes a folder the helper reported as damaged.
    if (step === "destroy")
        return value.state !== "damaged"
    return false
}

// {step, queue}: the first step to run now ("" = none) and what is left.
function nextStep(queue, context) {
    var rest = Array.isArray(queue) ? queue.slice() : []
    while (rest.length > 0) {
        var step = rest.shift()
        if (!dropStep(step, context))
            return {step: step, queue: rest}
    }
    return {step: "", queue: rest}
}

// The helper operation a step runs, as the Chat tab names it.
function stepOperation(step) {
    if (typeof step !== "string")
        return ""
    if (step === "unlock-wallet")
        return "unlock"
    return isLeaveStep(step) ? step.slice("leave-".length) : step
}

// The --method a step's operation takes ("" = none).
function stepMethod(step) {
    return step === "unlock-wallet" || step === "add-key" ? "wallet" : ""
}

// After the leave-destroy step: {state} to set when the folder is known to be
// gone, else {steps} to re-check.
function afterDestroy(reply) {
    if (reply && reply.ok === true)
        return {state: "absent", steps: []}
    return {state: "", steps: ["status"]}
}
