.pragma library

// Built-in Ollama chat. Pure helpers only: OllamaChatView.qml does the
// requests and keeps the conversation in memory. Everything that comes back
// from the server (or the port-owner helper) is untrusted and is reduced here
// to checked values; anything odd fails safe.

var ENTRY = Object.freeze({
    id: "ollama",
    name: "Ollama",
    icon: "provider-local.svg",
    native: true,
    default_on: false
})

var DEFAULT_ADDRESS = "http://127.0.0.1:11434"
var MAX_ADDRESS_LENGTH = 64
var MAX_PROMPT_CHARS = 32000
var MAX_REPLY_CHARS = 200000
var MAX_MODELS = 200
var MAX_SERVER_ERROR_CHARS = 300
// Unread text a reply may hold: a stream line not yet ended by "\n", or a
// whole GET reply. More stops reading (I3).
var MAX_BUFFERED_CHARS = 1048576
// A non-200 reply is only read for its error message, up to this size.
var MAX_ERROR_REPLY_CHARS = 65536
var MAX_INT = 2147483648
// A personality (system prompt) per model, memory only.
var MAX_SYSTEM_CHARS = 8000
// Longer blocks are shown as one plain text, markers and all: every styled
// word is an item of its own.
var MAX_STYLED_WORDS = 300
var MAX_STYLED_CHARS = 4000
// List nesting shown: 0, 1, 2.
var MAX_LIST_DEPTH = 2

var LOOPBACK_HOSTS = ["127.0.0.1", "localhost", "[::1]"]
var ENDPOINTS = { version: "/api/version", tags: "/api/tags", chat: "/api/chat" }
var ROLES = ["user", "assistant"]
var OWNERS = ["none", "self", "system", "other"]
var OWNER_ERRORS = ["unreadable"]

// --- Chat site list ---------------------------------------------------------

// Whether the chatSites config JSON turns Ollama on; unreadable → false.
function isEnabled(chatSitesJson) {
    try {
        var parsed = JSON.parse(typeof chatSitesJson === "string" ? chatSitesJson : "")
        return Array.isArray(parsed) && parsed.indexOf(ENTRY.id) >= 0
    } catch (error) {
        return false
    }
}

// The Chat dropdown: web sites first, then Ollama when it is on.
function menuEntries(webSites, chatSitesJson) {
    var sites = Array.isArray(webSites) ? webSites : []
    return sites.concat(isEnabled(chatSitesJson) ? [ENTRY] : [])
}

function allSiteIds(webIds) {
    var ids = Array.isArray(webIds) ? webIds : []
    return ids.filter(function (id) { return id !== ENTRY.id }).concat([ENTRY.id])
}

// --- Address ----------------------------------------------------------------

// {ok, address, error} for the address typed in settings. Only
// http://<127.0.0.1|localhost|[::1]>:<port> with an optional trailing "/" is
// accepted, normalized to "http://host:port". Empty means the default.
function validateAddress(text) {
    var fail = function (code) { return { ok: false, address: "", error: code } }
    var value = text === undefined || text === null ? "" : String(text)
    if (value === "")
        return { ok: true, address: DEFAULT_ADDRESS, error: "" }
    if (value.length > MAX_ADDRESS_LENGTH)
        return fail("too-long")
    if (/[\s\u0000-\u001f\u007f]/.test(value))
        return fail("whitespace")
    var authorityMatch = /^[A-Za-z][A-Za-z0-9+.\-]*:\/\/([^\/?#]*)/.exec(value)
    if (authorityMatch && authorityMatch[1].indexOf("@") >= 0)
        return fail("userinfo")
    var schemeMatch = /^([A-Za-z][A-Za-z0-9+.\-]*):(.*)$/.exec(value)
    if (!schemeMatch)
        return fail("malformed")
    if (schemeMatch[1].toLowerCase() !== "http")
        return fail("scheme")
    var rest = schemeMatch[2]
    if (rest.indexOf("//") !== 0)
        return fail("malformed")
    rest = rest.slice(2)
    var authority = rest.split(/[\/?#]/)[0]
    var tail = rest.slice(authority.length)
    var host
    var port
    if (authority.charAt(0) === "[") {
        var bracketMatch = /^(\[[^\]]*\])(?::(.*))?$/.exec(authority)
        if (!bracketMatch)
            return fail("malformed")
        host = bracketMatch[1].toLowerCase()
        port = bracketMatch[2]
    } else {
        var hostMatch = /^([^:]*)(?::(.*))?$/.exec(authority)
        host = hostMatch[1].toLowerCase()
        port = hostMatch[2]
    }
    if (host === "")
        return fail("malformed")
    // Exact names only: no other 127/8 address, 0.0.0.0, numeric forms,
    // *.localhost or DNS names that happen to resolve to loopback.
    if (LOOPBACK_HOSTS.indexOf(host) < 0)
        return fail("not-loopback")
    if (port === undefined || port === "")
        return fail("port-missing")
    if (!/^[0-9]+$/.test(port))
        return fail("malformed")
    var number = port.length > 5 ? 0 : parseInt(port, 10)
    if (number < 1 || number > 65535)
        return fail("port-range")
    if (tail !== "" && tail !== "/")
        return fail("path")
    return { ok: true, address: "http://" + host + ":" + number, error: "" }
}

// {address, error} for the settings field: valid text (trimmed) is saved
// normalized; invalid text saves baseline, the value saved when the page
// opened, so a half-typed address never outlives a typo.
function addressToPersist(text, baseline) {
    var value = text === undefined || text === null ? "" : String(text).trim()
    var checked = validateAddress(value)
    if (checked.ok)
        return { address: checked.address, error: "" }
    var fallback = validateAddress(baseline)
    return { address: fallback.ok ? fallback.address : DEFAULT_ADDRESS, error: checked.error }
}

function effectiveAddress(configValue) {
    if (typeof configValue !== "string")
        return DEFAULT_ADDRESS
    var checked = validateAddress(configValue)
    return checked.ok ? checked.address : DEFAULT_ADDRESS
}

// The normalized address, or "" when empty or invalid.
function checkedAddress(address) {
    if (typeof address !== "string" || address === "")
        return ""
    var checked = validateAddress(address)
    return checked.ok ? checked.address : ""
}

// Port number of a valid address, else 0.
function portOf(address) {
    var normalized = checkedAddress(address)
    if (normalized === "")
        return 0
    return parseInt(normalized.slice(normalized.lastIndexOf(":") + 1), 10)
}

function endpoint(address, name) {
    var normalized = checkedAddress(address)
    if (normalized === "" || typeof name !== "string"
            || !Object.prototype.hasOwnProperty.call(ENDPOINTS, name))
        return ""
    return normalized + ENDPOINTS[name]
}

// --- Requests ---------------------------------------------------------------

// Small models (llama3 8B) drift from a personality after a turn or two; a
// fixed reminder in front of the newest message keeps them on it. Only the
// request carries it: the conversation shown and kept has the user's text.
var PERSONA_REMINDER = "(Stay in character as described in your instructions.)\n\n"

// A copy of messages with PERSONA_REMINDER in front of the last user message.
function withPersonaReminder(messages) {
    var list = Array.isArray(messages) ? messages.slice() : []
    for (var index = list.length - 1; index >= 0; index--) {
        var message = list[index]
        if (message && message.role === "user" && typeof message.content === "string") {
            list[index] = Object.assign({}, message, { content: PERSONA_REMINDER + message.content })
            break
        }
    }
    return list
}

function isModelName(name) {
    return typeof name === "string" && /^[A-Za-z0-9._:\/+-]{1,200}$/.test(name)
}

// The POST /api/chat body, or "" when anything is off. Only role and content
// are sent; user turns are capped at MAX_PROMPT_CHARS, replies at
// MAX_REPLY_CHARS. A personality (system, at most MAX_SYSTEM_CHARS) goes
// first, and the newest user message then starts with PERSONA_REMINDER;
// "", null or undefined means none, anything else odd sends nothing.
// Nothing else ever carries the system role.
function chatRequestBody(model, messages, system) {
    if (!isModelName(model) || !Array.isArray(messages) || messages.length === 0)
        return ""
    var clean = []
    var persona = false
    if (system !== undefined && system !== null && system !== "") {
        if (typeof system !== "string" || system.length > MAX_SYSTEM_CHARS)
            return ""
        persona = system.trim() !== ""
        if (persona)
            clean.push({ role: "system", content: system })
    }
    for (var index = 0; index < messages.length; index++) {
        var message = messages[index]
        if (!message || typeof message !== "object" || ROLES.indexOf(message.role) < 0
                || typeof message.content !== "string")
            return ""
        var limit = message.role === "user" ? MAX_PROMPT_CHARS : MAX_REPLY_CHARS
        if (message.content.length > limit)
            return ""
        clean.push({ role: message.role, content: message.content })
    }
    return JSON.stringify({ model: model, messages: persona ? withPersonaReminder(clean) : clean, stream: true })
}

// Asks Ollama to unload the model (and drop its cache). Carries no prompt.
function unloadRequestBody(model) {
    if (!isModelName(model))
        return ""
    return JSON.stringify({ model: model, messages: [], keep_alive: 0 })
}

// --- Responses --------------------------------------------------------------

function parseObject(text) {
    try {
        var value = JSON.parse(typeof text === "string" ? text : "")
        return value && typeof value === "object" && !Array.isArray(value) ? value : null
    } catch (error) {
        return null
    }
}

// A short display word from the server ("8.0B", "llama"), else "".
function safeWord(value) {
    return typeof value === "string" && /^[A-Za-z0-9._ +-]{1,40}$/.test(value) ? value : ""
}

// GET /api/version: proves something Ollama-shaped is answering.
function parseVersion(status, text) {
    var reply = status === 200 ? parseObject(text) : null
    if (reply === null || typeof reply.version !== "string" || reply.version.length > 32
            || !/^[0-9]+\.[0-9]+[0-9A-Za-z.+-]*$/.test(reply.version))
        return { ok: false, error: "not-ollama" }
    return { ok: true, version: reply.version }
}

function isRemoteName(name) {
    var lower = name.toLowerCase()
    return /[:-]cloud$/.test(lower)
}

function hasField(object, key) {
    return Object.prototype.hasOwnProperty.call(object, key)
        && object[key] !== null && object[key] !== undefined
}

// GET /api/tags → installed local chat models in server order. Cloud models
// (they forward prompts to ollama.com) are dropped and counted; models
// without "completion" (embeddings) and bad names are dropped silently.
function parseTags(status, text) {
    if (status !== 200)
        return { ok: false, models: [], hiddenRemote: 0, error: classifyFailure(status) }
    var reply = parseObject(text)
    if (reply === null || !Array.isArray(reply.models))
        return { ok: false, models: [], hiddenRemote: 0, error: "bad-tags" }
    var models = []
    var seen = []
    var hidden = 0
    for (var index = 0; index < reply.models.length && models.length < MAX_MODELS; index++) {
        var entry = reply.models[index]
        if (!entry || typeof entry !== "object" || Array.isArray(entry) || !isModelName(entry.name))
            continue
        if (hasField(entry, "remote_host") || hasField(entry, "remote_model")
                || isRemoteName(entry.name)) {
            hidden++
            continue
        }
        if (hasField(entry, "capabilities")
                && (!Array.isArray(entry.capabilities)
                    || entry.capabilities.indexOf("completion") < 0))
            continue
        if (seen.indexOf(entry.name) >= 0)
            continue
        seen.push(entry.name)
        var details = entry.details && typeof entry.details === "object" ? entry.details : {}
        models.push({
            name: entry.name,
            parameterSize: safeWord(details.parameter_size),
            family: safeWord(details.family)
        })
    }
    return { ok: true, models: models, hiddenRemote: hidden, error: "" }
}

// The previous choice while it is still listed, else the first model.
function pickModel(models, current) {
    var list = Array.isArray(models) ? models : []
    var first = ""
    for (var index = 0; index < list.length; index++) {
        var name = list[index] && list[index].name
        if (!isModelName(name))
            continue
        if (name === current)
            return name
        if (first === "")
            first = name
    }
    return first
}

// --- Streaming reply --------------------------------------------------------

function newStream() {
    return { offset: 0, content: "", thinking: false, done: false, doneReason: "",
             error: "", errorText: "" }
}

function copyStream(state) {
    var value = state && typeof state === "object" ? state : newStream()
    return {
        offset: typeof value.offset === "number" && value.offset >= 0 ? value.offset : 0,
        content: typeof value.content === "string" ? value.content : "",
        thinking: value.thinking === true,
        done: value.done === true,
        doneReason: typeof value.doneReason === "string" ? value.doneReason : "",
        error: typeof value.error === "string" ? value.error : "",
        errorText: typeof value.errorText === "string" ? value.errorText : ""
    }
}

// One NDJSON line into state (mutated). Returns false to stop reading.
function feedLine(state, line) {
    var trimmed = line.trim()
    if (trimmed === "")
        return true
    var chunk = parseObject(trimmed)
    if (chunk === null) {
        state.error = "bad-stream"
        return false
    }
    if (hasField(chunk, "error")) {
        state.error = "server"
        state.errorText = serverErrorText(chunk.error)
        return false
    }
    var message = chunk.message
    if (message && typeof message === "object") {
        if (typeof message.content === "string")
            state.content += message.content
        // Thinking text is never kept; only the fact that it arrives.
        if (typeof message.thinking === "string" && message.thinking !== "")
            state.thinking = true
    }
    if (state.content.length > MAX_REPLY_CHARS) {
        state.content = state.content.slice(0, MAX_REPLY_CHARS)
        state.error = "too-long"
        return false
    }
    if (chunk.done === true) {
        state.done = true
        state.doneReason = typeof chunk.done_reason === "string"
            && /^[a-z_]{1,20}$/.test(chunk.done_reason) ? chunk.done_reason : ""
        return false
    }
    return true
}

// The state after reading responseText (the whole body so far). Only
// complete "\n"-terminated lines from offset are read, plus the last line
// when final. Text before offset ends in a complete line, so later
// re-decoding of the body doesn't move it. After done or an error nothing
// more is read. A line (ended or not) over MAX_BUFFERED_CHARS is never
// parsed: the reply ends as "too-long".
function feedStream(state, responseText, final) {
    var next = copyStream(state)
    if (next.done || next.error !== "")
        return next
    var text = typeof responseText === "string" ? responseText : ""
    if (text.length < next.offset)
        return next
    while (true) {
        var end = text.indexOf("\n", next.offset)
        var line
        var length = (end >= 0 ? end : text.length) - next.offset
        if (length > MAX_BUFFERED_CHARS) {
            next.error = "too-long"
            break
        }
        if (end >= 0) {
            line = text.slice(next.offset, end)
            next.offset = end + 1
        } else if (final === true && next.offset < text.length) {
            line = text.slice(next.offset)
            next.offset = text.length
        } else {
            break
        }
        if (!feedLine(next, line))
            break
    }
    return next
}

// Whether a reply text is over limit characters (anything but a string is not).
function tooLarge(text, limit) {
    return typeof text === "string" && text.length > limit
}

// The server's error message from a whole non-200 reply, "" when there is
// none or the reply is over MAX_ERROR_REPLY_CHARS (never parsed then).
function errorReplyDetail(responseText) {
    if (typeof responseText !== "string" || responseText.length > MAX_ERROR_REPLY_CHARS)
        return ""
    var parsed = feedStream(newStream(), responseText, true)
    return parsed.error === "server" ? parsed.errorText : ""
}

function classifyFailure(status) {
    if (status === 0)
        return "not-running"
    if (status === 403)
        return "forbidden"
    if (status === 404)
        return "model-missing"
    if (typeof status === "number" && status >= 500)
        return "server-error"
    return "unexpected"
}

// A server error message made safe for a PlainText label.
function serverErrorText(raw) {
    if (typeof raw !== "string")
        return ""
    return raw.replace(/[\u0000-\u001f\u007f-\u009f‎‏‪-‮⁦-⁩]/g, " ")
        .replace(/[<>&]/g, "")
        .replace(/ {2,}/g, " ")
        .trim()
        .slice(0, MAX_SERVER_ERROR_CHARS)
        .trim()
}

// --- Hidden characters ------------------------------------------------------

// Characters that change how text looks, or what a terminal does with it,
// without being seen, so a copied command could differ from the one on
// screen: control characters (C0 except tab and line feed, so CR and ESC
// too; DEL; C1 with U+0085), U+2028/2029, the soft hyphen U+00AD, U+034F,
// direction controls (U+061C, U+200E/F, U+202A-E, U+2066-9, U+206A-F),
// zero-width and invisible characters (U+200B-D, U+2060-4, U+FEFF, U+180E,
// U+17B4/5, Hangul fillers U+115F/1160/3164/FFA0), variation selectors
// (U+FE00-F, U+E0100-E01EF), interlinear annotation (U+FFF9-B), shorthand
// format controls (U+1BCA0-3), musical format controls (U+1D173-A) and tag
// characters (U+E0000-E007F). Each one is shown as a visible marker such as
// ⟦U+202E⟧ instead. Only exception: one U+FE0F right after an emoji, which
// just asks for the colour form of that emoji.
// Built from strings because Qt's JavaScript lexer rejects an escaped U+2028 inside a
// regular expression literal.
var HIDDEN_RANGES = [
    "\\u0000-\\u0008", "\\u000b-\\u001f", "\\u007f-\\u009f", "\\u00ad", "\\u034f",
    "\\u061c", "\\u115f\\u1160", "\\u17b4\\u17b5", "\\u180e", "\\u200b-\\u200f",
    "\\u2028\\u2029", "\\u202a-\\u202e", "\\u2060-\\u2064", "\\u2066-\\u206f", "\\u3164",
    "\\ufe00-\\ufe0f", "\\ufeff", "\\uffa0", "\\ufff9-\\ufffb", "\\u{1bca0}-\\u{1bca3}",
    "\\u{1d173}-\\u{1d17a}", "\\u{e0000}-\\u{e007f}", "\\u{e0100}-\\u{e01ef}"
]
var HIDDEN_CHARS = new RegExp("[" + HIDDEN_RANGES.join("") + "]", "gu")

function hexCode(character) {
    var hex = character.codePointAt(0).toString(16).toUpperCase()
    while (hex.length < 4)
        hex = "0" + hex
    return "U+" + hex
}

// Code points that have an emoji form: symbols, arrows, dingbats and the
// emoji planes. Only used to let one U+FE0F after them stay unmarked.
function isEmojiBase(point) {
    return (point >= 0x1f000 && point <= 0x1faff)
        || (point >= 0x2190 && point <= 0x21ff)
        || (point >= 0x2300 && point <= 0x23ff)
        || (point >= 0x25a0 && point <= 0x27bf)
        || (point >= 0x2900 && point <= 0x297f)
        || (point >= 0x2b00 && point <= 0x2bff)
        || [0x00a9, 0x00ae, 0x203c, 0x2049, 0x2122, 0x2139, 0x24c2,
            0x3030, 0x303d, 0x3297, 0x3299].indexOf(point) >= 0
}

// The code point that ends just before offset, -1 at the start.
function pointBefore(text, offset) {
    if (offset <= 0)
        return -1
    var low = text.charCodeAt(offset - 1)
    if (low >= 0xdc00 && low <= 0xdfff && offset >= 2) {
        var high = text.charCodeAt(offset - 2)
        if (high >= 0xd800 && high <= 0xdbff)
            return text.codePointAt(offset - 2)
    }
    return low
}

function revealHidden(text) {
    if (typeof text !== "string")
        return ""
    return text.replace(HIDDEN_CHARS, function (character, offset, whole) {
        if (character === "️" && isEmojiBase(pointBefore(whole, offset)))
            return character
        return "⟦" + hexCode(character) + "⟧"
    })
}

function hasHidden(text) {
    return typeof text === "string" && revealHidden(text) !== text
}

// --- Reply layout -----------------------------------------------------------

// [{kind: "text"|"code", text, lang}] split on ``` fence lines. A fence that
// isn't closed yet (still streaming) is code to the end. Whitespace-only text
// between blocks is dropped.
function segments(text) {
    if (typeof text !== "string" || text === "")
        return []
    var result = []
    var lines = text.split("\n")
    var buffer = []
    var inCode = false
    var lang = ""
    var flush = function (kind) {
        var joined = buffer.join("\n")
        if (kind === "code" || joined.trim() !== "")
            result.push({ kind: kind, text: joined, lang: kind === "code" ? lang : "" })
        buffer = []
    }
    for (var index = 0; index < lines.length; index++) {
        var line = lines[index]
        var bare = line.replace(/\r$/, "")
        var fence = /^\s*```+(.*)$/.exec(bare)
        if (!inCode && fence) {
            flush("text")
            var word = fence[1].trim()
            lang = /^[A-Za-z0-9+#.-]{0,20}$/.test(word) ? word : ""
            inCode = true
        } else if (inCode && /^\s*```+\s*$/.test(bare)) {
            flush("code")
            inCode = false
            lang = ""
        } else {
            buffer.push(line)
        }
    }
    flush(inCode ? "code" : "text")
    return result
}

// --- Formatting ---------------------------------------------------------------

// A whitelisted subset of Markdown, read into blocks the view shows as
// separate plain text items: headings (#, ##, ###), - * + bullets, "1."
// lists, **bold** / __bold__, *italic* / _italic_, `code` and ``` fences.
// Links, autolinks, images, HTML tags and entities, tables and everything
// else stay literal text: nothing is ever fetched, opened or interpreted.

var HEADING_LINE = /^ {0,3}(#{1,3})[ \t]+(.*)$/
var BULLET_LINE = /^([ \t]*)[-*+][ \t]+(.*)$/
var NUMBER_LINE = /^([ \t]*)([0-9]{1,9})\.[ \t]+(.*)$/
var RULE_LINE = /^[ \t]*([-*_])(?:[ \t]*\1){2,}[ \t]*$/

function indentWidth(text) {
    var width = 0
    for (var index = 0; index < text.length; index++)
        width += text.charAt(index) === "\t" ? 4 : 1
    return width
}

// The nesting of a list item from its indent; indents (mutated) holds the
// indents of the open levels.
function listDepth(indents, width) {
    while (indents.length > 0 && indents[indents.length - 1] > width)
        indents.pop()
    if (indents.length === 0 || indents[indents.length - 1] < width)
        indents.push(width)
    return Math.min(MAX_LIST_DEPTH, indents.length - 1)
}

function isSpace(character) {
    return character === "" || /\s/.test(character)
}

function isWordCharacter(character) {
    return /[A-Za-z0-9]/.test(character)
}

// Where the mark opened at open closes, else -1. Text must follow the
// opening mark and come before the closing one; "_" only works at word
// edges (snake_case stays as it is). noCloser remembers marks without any
// closing left, so a run of unclosed marks stays linear.
function closingMark(text, open, mark, noCloser) {
    var single = mark.charAt(0)
    if (noCloser[mark] === true || isSpace(text.charAt(open + mark.length)))
        return -1
    if (single === "_" && open > 0 && isWordCharacter(text.charAt(open - 1)))
        return -1
    var from = open + mark.length + 1
    while (true) {
        var close = text.indexOf(mark, from)
        if (close < 0) {
            noCloser[mark] = true
            return -1
        }
        var after = text.charAt(close + mark.length)
        var good = !isSpace(text.charAt(close - 1))
            && (mark.length === 2 || after !== single)
            && (single !== "_" || !isWordCharacter(after))
        if (good)
            return close
        from = close + 1
    }
}

function pushSpan(out, text, bold, italic, code) {
    if (text === "")
        return
    var last = out.length > 0 ? out[out.length - 1] : null
    if (last !== null && last.bold === bold && last.italic === italic && last.code === code)
        last.text += text
    else
        out.push({ text: text, bold: bold, italic: italic, code: code })
}

// Bold and italic in text without inline code; unclosed marks stay literal.
function emphasis(text, bold, italic, out, depth) {
    var noCloser = {}
    var index = 0
    var plainStart = 0
    while (index < text.length) {
        var character = text.charAt(index)
        if ((character !== "*" && character !== "_") || depth >= 4) {
            index++
            continue
        }
        var mark = text.charAt(index + 1) === character ? character + character : character
        var close = closingMark(text, index, mark, noCloser)
        if (close < 0) {
            index += mark.length
            continue
        }
        pushSpan(out, text.slice(plainStart, index), bold, italic, false)
        emphasis(text.slice(index + mark.length, close),
            bold || mark.length === 2, italic || mark.length === 1, out, depth + 1)
        index = close + mark.length
        plainStart = index
    }
    pushSpan(out, text.slice(plainStart), bold, italic, false)
}

// [{text, bold, italic, code}] of one block's text (already revealed). A
// block over MAX_STYLED_WORDS words (or MAX_STYLED_CHARS characters) stays
// one plain span, markers and all.
function spans(text) {
    if (typeof text !== "string" || text === "")
        return []
    var trimmed = text.trim()
    var words = trimmed === "" ? 0 : trimmed.split(/\s+/).length
    if (words > MAX_STYLED_WORDS || text.length > MAX_STYLED_CHARS)
        return [{ text: text, bold: false, italic: false, code: false }]
    var out = []
    var parts = text.split("`")
    // Odd parts sit between two backticks: inline code, kept as it is. An
    // unclosed or empty one stays literal.
    for (var index = 0; index < parts.length; index++) {
        var closed = index + 1 < parts.length
        if (index % 2 === 0)
            emphasis(parts[index], false, false, out, 0)
        else if (closed && parts[index] !== "")
            pushSpan(out, parts[index], false, false, true)
        else
            emphasis((closed ? "``" : "`") + parts[index], false, false, out, 0)
    }
    return out
}

function isStyled(list) {
    return Array.isArray(list) && list.some(function (span) {
        return span.bold === true || span.italic === true || span.code === true
    })
}

// The block's text without its markers.
function spansText(list) {
    return Array.isArray(list) ? list.map(function (span) { return span.text }).join("") : ""
}

// The pieces of styled spans as laid out word by word: [{text, bold,
// italic, code, space, br}]. space: whitespace follows; br: a line break.
function flowWords(list) {
    var out = []
    var spanList = Array.isArray(list) ? list : []
    for (var index = 0; index < spanList.length; index++) {
        var span = spanList[index]
        var tokens = typeof span.text === "string" ? span.text.split(/(\s+)/) : []
        for (var inner = 0; inner < tokens.length; inner++) {
            var token = tokens[inner]
            if (token === "")
                continue
            if (/^\s+$/.test(token)) {
                if (out.length === 0)
                    continue
                if (token.indexOf("\n") >= 0)
                    out.push({ text: "", bold: false, italic: false, code: false, space: false, br: true })
                else
                    out[out.length - 1].space = true
                continue
            }
            out.push({ text: token, bold: span.bold === true, italic: span.italic === true,
                       code: span.code === true, space: false, br: false })
        }
    }
    return out
}

function textBlock(block) {
    // Hidden characters become visible markers before anything is shown.
    var shown = { kind: block.kind, spans: spans(revealHidden(block.lines.join("\n"))) }
    if (block.kind === "heading")
        shown.level = block.level
    else if (block.kind === "bullet")
        shown.depth = block.depth
    else if (block.kind === "number")
        shown.n = block.n
    return shown
}

// Headings, paragraphs and list items of text outside code fences.
function textBlocks(text) {
    var result = []
    var current = null
    var indents = []
    var flush = function () {
        if (current !== null)
            result.push(textBlock(current))
        current = null
    }
    var lines = text.split("\n")
    for (var index = 0; index < lines.length; index++) {
        var line = lines[index]
        var bare = line.replace(/\r$/, "")
        if (/^\s*$/.test(bare)) {
            flush()
            continue
        }
        var rule = RULE_LINE.test(bare)
        var match = rule ? null : HEADING_LINE.exec(bare)
        if (match) {
            flush()
            indents = []
            current = { kind: "heading", level: match[1].length,
                        lines: [match[2].replace(/[ \t]+#+[ \t]*$/, "").trim()] }
            flush()
            continue
        }
        match = rule ? null : BULLET_LINE.exec(bare)
        if (match) {
            flush()
            current = { kind: "bullet", depth: listDepth(indents, indentWidth(match[1])), lines: [match[2]] }
            continue
        }
        match = rule ? null : NUMBER_LINE.exec(bare)
        if (match) {
            flush()
            listDepth(indents, indentWidth(match[1]))
            current = { kind: "number", n: parseInt(match[2], 10), lines: [match[3]] }
            continue
        }
        if (current !== null && current.kind !== "paragraph") {
            // A line right after a list item belongs to it.
            current.lines.push(line.replace(/^[ \t]+/, ""))
            continue
        }
        if (current === null) {
            indents = []
            current = { kind: "paragraph", lines: [] }
        }
        current.lines.push(line)
    }
    flush()
    return result
}

// The reply as shown: [{kind: "heading", level, spans} | {kind: "paragraph",
// spans} | {kind: "bullet", depth, spans} | {kind: "number", n, spans} |
// {kind: "code", text, lang}]. Hidden, control and zero-width characters
// are shown as markers (revealHidden) in every block, so what is shown,
// selected and copied is the same text.
function blocks(text) {
    var result = []
    var parts = segments(text)
    for (var index = 0; index < parts.length; index++) {
        if (parts[index].kind === "code")
            result.push({ kind: "code", text: revealHidden(parts[index].text), lang: parts[index].lang })
        else
            result = result.concat(textBlocks(parts[index].text))
    }
    return result
}

// --- Conversation -----------------------------------------------------------

// The last exchange of a transcript ([{author}]): the index of its user
// message and of the reply to it, -1 when there is none. A user message
// without a reply (it failed) has assistantIndex -1.
function lastTurn(rows) {
    var none = { userIndex: -1, assistantIndex: -1 }
    if (!Array.isArray(rows) || rows.length === 0)
        return none
    var author = function (row) {
        return row && typeof row === "object" ? row.author : ""
    }
    var last = rows.length - 1
    if (author(rows[last]) === "user")
        return { userIndex: last, assistantIndex: -1 }
    if (author(rows[last]) !== "assistant")
        return none
    if (last >= 1 && author(rows[last - 1]) === "user")
        return { userIndex: last - 1, assistantIndex: last }
    return { userIndex: -1, assistantIndex: last }
}

// Text dropped on the chat, for the message box (it is never sent from
// here): control characters except tab and line feed are removed, NUL
// means it isn't text, and it is added after what is typed already.
// {ok: true, text} is the whole new message; else {ok: false, error}.
function dropText(text, currentInput) {
    if (typeof text !== "string" || text.indexOf("\u0000") >= 0)
        return { ok: false, error: "not-text" }
    var clean = text.replace(/[\u0001-\u0008\u000b-\u001f\u007f-\u009f]/g, "")
    if (clean.trim() === "")
        return { ok: false, error: "empty" }
    var current = typeof currentInput === "string" ? currentInput.replace(/\s+$/, "") : ""
    var joined = current === "" ? clean : current + "\n\n" + clean
    if (joined.length > MAX_PROMPT_CHARS)
        return { ok: false, error: "too-long" }
    return { ok: true, text: joined }
}

// --- Port owner check -------------------------------------------------------

// A plain integer 0..2**31, else -1 (same rule as ChatStorage.validInt).
function validInt(value) {
    if (typeof value !== "number" || !Number.isInteger(value) || value < 0 || value > MAX_INT)
        return -1
    return value
}

// The helper command that reports who listens on port. The env words only
// make the DataSource source name unique (same shape as
// ChatStorage.helperPrefix); the helper ignores them. Invalid → "".
function ownerCommand(port, run, applet) {
    if (typeof port !== "number" || !Number.isInteger(port) || port < 1 || port > 65535
            || validInt(run) < 0 || validInt(applet) < 0)
        return ""
    return "env HEARTHWIRE_RUN=" + run + " HEARTHWIRE_APPLET=" + applet
        + " python3 -P -m hearthwire --port-owner " + port
}

function parseOwnerReply(exitCode, stdout) {
    var bad = { ok: false, error: "bad-reply" }
    if (exitCode !== 0 || typeof stdout !== "string" || stdout.length > 200)
        return bad
    var reply = parseObject(stdout)
    if (reply === null)
        return bad
    if (reply.ok === true && OWNERS.indexOf(reply.owner) >= 0)
        return { ok: true, owner: reply.owner }
    if (reply.ok === false && OWNER_ERRORS.indexOf(reply.error) >= 0)
        return { ok: false, error: reply.error }
    return bad
}

// Whether prompts may go to the program that owns the port.
function trusted(owner) {
    return owner === "self" || owner === "system"
}

// The problem code for a parsed owner reply; "" only for self or system.
// Fails closed: anything else is a problem.
function ownerProblem(reply) {
    if (!reply || reply.ok !== true)
        return "owner-unknown"
    if (reply.owner === "none")
        return "not-running"
    if (reply.owner === "other")
        return "other"
    return trusted(reply.owner) ? "" : "owner-unknown"
}
