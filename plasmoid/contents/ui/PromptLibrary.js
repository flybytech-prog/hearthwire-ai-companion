.pragma library

// Saved prompts and personalities (the prompt library), and text files
// dropped on the Ollama chat. Pure helpers only: main.qml runs the commands
// built here and keeps the replies in memory. Commands carry fixed words,
// integers, a checked model name, or a path as lowercase hex, never user
// text. Every reply is untrusted and reduced here to checked values.

var MAX_INT = 2147483648
var MAX_ITEMS = 100
var MAX_PERSONA_DEFAULTS = 200
var KINDS = ["prompt", "persona"]
var MAX_CHARS = { prompt: 32000, persona: 8000 }
// The longest text a dropped file may give (the message limit).
var MAX_DROPPED_CHARS = 32000
// Hex of a dropped file's path: 2 to 8192 lowercase hex digits.
var MAX_HEX = 8192
var MAX_STDOUT = 4000000
var PROMPT_OPERATIONS = ["list", "add", "replace", "remove", "set-persona"]
var ERRORS = [
    "locked", "not-verified", "cancelled", "too-long", "too-large", "not-text", "not-file",
    "full", "absent", "unreadable", "busy", "missing-tool", "os-error"
]

// A plain integer 0..2**31, else -1 (same rule as ChatStorage.validInt).
function validInt(value) {
    if (typeof value !== "number" || !Number.isInteger(value) || value < 0 || value > MAX_INT)
        return -1
    return value
}

function validId(value) {
    return validInt(value) >= 1
}

// Same rule as the helper: an Ollama model name that can't be an option.
function isModelName(name) {
    return typeof name === "string" && /^[A-Za-z0-9._:\/+-]{1,200}$/.test(name)
        && name.charAt(0) !== "-"
}

// Same shape as ChatStorage.helperPrefix: the env words only make the
// DataSource source name unique; the helper ignores them.
function helperPrefix(run, applet) {
    if (validInt(run) < 0 || validInt(applet) < 0)
        return ""
    return "env HEARTHWIRE_RUN=" + run + " HEARTHWIRE_APPLET=" + applet + " python3 -P -m hearthwire"
}

// op: list | add (args.kind) | replace (args.id) | remove (args.id) |
// set-persona (args.model, args.id or args.id === null for none).
// Anything off gives "" and nothing runs.
function promptsCommand(op, run, applet, args) {
    var prefix = helperPrefix(run, applet)
    var value = args && typeof args === "object" ? args : {}
    if (prefix === "" || PROMPT_OPERATIONS.indexOf(op) < 0)
        return ""
    var command = prefix + " --prompts " + op
    switch (op) {
    case "list":
        return command
    case "add":
        return KINDS.indexOf(value.kind) >= 0 ? command + " --kind " + value.kind : ""
    case "replace":
    case "remove":
        return validId(value.id) ? command + " --id " + value.id : ""
    case "set-persona":
        if (!isModelName(value.model))
            return ""
        if (value.id === null)
            return command + " --model " + value.model + " --none"
        return validId(value.id) ? command + " --model " + value.model + " --id " + value.id : ""
    }
    return ""
}

function isHexPath(hex) {
    return typeof hex === "string" && hex.length <= MAX_HEX && /^(?:[0-9a-f]{2})+$/.test(hex)
}

function readDroppedCommand(hex, run, applet) {
    var prefix = helperPrefix(run, applet)
    if (prefix === "" || !isHexPath(hex))
        return ""
    return prefix + " --read-dropped " + hex
}

// The UTF-8 bytes of a local file URL's path as lowercase hex, else "".
// Only file:/// URLs (no host, query or fragment) of an absolute path
// without NUL; percent escapes must decode as UTF-8.
function hexPath(url) {
    var text = url === undefined || url === null ? "" : String(url)
    if (text.indexOf("file:///") !== 0 || /[?#]/.test(text))
        return ""
    var path
    try {
        path = decodeURIComponent(text.slice("file://".length))
    } catch (error) {
        return ""
    }
    if (path.charAt(0) !== "/" || path.indexOf("\u0000") >= 0)
        return ""
    var encoded
    try {
        encoded = encodeURIComponent(path)
    } catch (error) {
        return ""
    }
    var hex = ""
    for (var index = 0; index < encoded.length; index++) {
        if (encoded.charAt(index) === "%") {
            hex += encoded.substr(index + 1, 2).toLowerCase()
            index += 2
        } else {
            var code = encoded.charCodeAt(index)
            hex += (code < 16 ? "0" : "") + code.toString(16)
        }
        if (hex.length > MAX_HEX)
            return ""
    }
    return hex
}

function parseObject(exitCode, stdout) {
    if (exitCode !== 0 || typeof stdout !== "string" || stdout.length > MAX_STDOUT)
        return null
    try {
        var value = JSON.parse(stdout)
        return value && typeof value === "object" && !Array.isArray(value) ? value : null
    } catch (error) {
        return null
    }
}

function failure(reply) {
    if (reply === null)
        return { ok: false, error: "bad-reply" }
    return { ok: false, error: typeof reply.error === "string" && ERRORS.indexOf(reply.error) >= 0
        ? reply.error : "failed" }
}

function goodText(text, cap) {
    return typeof text === "string" && text.length > 0 && text.length <= cap
        && text.indexOf("\u0000") < 0 && text.trim() !== ""
}

// --prompts list → {ok, items: [{id, kind, text}], personas: {model: id}}.
// Odd items, duplicates and defaults that name no listed persona are left out.
function parseList(exitCode, stdout) {
    var reply = parseObject(exitCode, stdout)
    if (reply === null || reply.ok !== true)
        return failure(reply)
    var items = []
    var ids = []
    var list = Array.isArray(reply.items) ? reply.items : []
    for (var index = 0; index < list.length && items.length < MAX_ITEMS; index++) {
        var item = list[index]
        if (!item || typeof item !== "object" || !validId(item.id) || ids.indexOf(item.id) >= 0
                || KINDS.indexOf(item.kind) < 0 || !goodText(item.text, MAX_CHARS[item.kind]))
            continue
        ids.push(item.id)
        items.push({ id: item.id, kind: item.kind, text: item.text })
    }
    var personas = {}
    var defaults = reply.personas && typeof reply.personas === "object" && !Array.isArray(reply.personas)
        ? reply.personas : {}
    var count = 0
    for (var model in defaults) {
        if (!Object.prototype.hasOwnProperty.call(defaults, model) || !isModelName(model)
                || count >= MAX_PERSONA_DEFAULTS)
            continue
        var id = defaults[model]
        if (!items.some(function (entry) { return entry.id === id && entry.kind === "persona" }))
            continue
        personas["m:" + model] = id
        count++
    }
    return { ok: true, items: items, personas: personas }
}

// add/replace → {ok, id}; remove/set-persona → {ok}.
function parseChange(exitCode, stdout) {
    var reply = parseObject(exitCode, stdout)
    if (reply === null || reply.ok !== true)
        return failure(reply)
    return validId(reply.id) ? { ok: true, id: reply.id } : { ok: true }
}

// --read-dropped → {ok, text} or {ok: false, error}.
function parseDropped(exitCode, stdout) {
    var reply = parseObject(exitCode, stdout)
    if (reply === null || reply.ok !== true)
        return failure(reply)
    if (typeof reply.text !== "string" || reply.text.length > MAX_DROPPED_CHARS
            || reply.text.indexOf("\u0000") >= 0)
        return { ok: false, error: "bad-reply" }
    return { ok: true, text: reply.text }
}

// --- Using the library -------------------------------------------------------

// A list from QML may be a sequence wrapper rather than a JS array.
function asArray(value) {
    if (Array.isArray(value))
        return value
    return value && typeof value === "object" && typeof value.length === "number"
        ? Array.prototype.slice.call(value) : []
}

function itemsOf(items, kind) {
    return asArray(items).filter(function (item) {
        return item && item.kind === kind
    })
}

// The saved default persona's text for a model ("" when none).
function defaultPersona(items, personas, model) {
    if (!isModelName(model) || !personas || typeof personas !== "object")
        return ""
    var key = "m:" + model
    if (!Object.prototype.hasOwnProperty.call(personas, key))
        return ""
    var id = personas[key]
    var found = itemsOf(items, "persona").filter(function (item) { return item.id === id })
    return found.length === 1 ? found[0].text : ""
}

// The id of the saved default persona of a model, else -1.
function defaultPersonaId(personas, model) {
    var key = "m:" + model
    return isModelName(model) && personas && Object.prototype.hasOwnProperty.call(personas, key)
        ? personas[key] : -1
}

// A one-line label for a menu or list: the first non-empty line, at most
// 60 characters.
function label(text) {
    if (typeof text !== "string")
        return ""
    var lines = text.split("\n").map(function (line) { return line.trim() })
        .filter(function (line) { return line !== "" })
    var first = lines.length > 0 ? lines[0] : ""
    return first.length > 60 ? first.slice(0, 60) + "…" : first
}

// The message box with text put in at cursor: {ok, text, cursor} or
// {ok: false, error: "too-long"} past the message limit.
function insertAt(current, cursor, text, limit) {
    var base = typeof current === "string" ? current : ""
    var added = typeof text === "string" ? text : ""
    var at = typeof cursor === "number" && cursor >= 0 && cursor <= base.length ? Math.floor(cursor) : base.length
    var result = base.slice(0, at) + added + base.slice(at)
    if (result.length > (typeof limit === "number" ? limit : MAX_CHARS.prompt))
        return { ok: false, error: "too-long" }
    return { ok: true, text: result, cursor: at + added.length }
}
