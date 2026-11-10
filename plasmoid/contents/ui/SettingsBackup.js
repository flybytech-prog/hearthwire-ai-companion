.pragma library

// Settings → General → Backup: pure rules, no QML state. The helper keeps one
// fixed file and checks every value; the widget checks the import again before
// the page applies it, so a reply can only ever set what the widget would
// store itself. Excluded keys are never exported and never applied.

var BACKUP_KEYS = [
    "trackedProviders", "providerMetrics", "providerOrder", "usageMode", "refreshInterval",
    "tooltipShowsUsage", "tooltipMetrics", "usageCompact",
    "usageWarnPercent", "usageCriticalPercent",
    "usageNormalColor", "usageWarnColor", "usageCriticalColor",
    "alertLowEnabled", "alertResetEnabled", "alertLowPercent",
    "chatSites", "chatDefaultSite", "chatOllamaUrl", "chatKeepOpen",
    "showUsageTab", "showChatTab", "popupDefaultTab", "popupSize", "shortcutOpens",
    "panelRing", "middleClickOpens", "chatCustomUrls"
]
// Sign-ins, the encrypted folder, zoom, first-run state and the history opt-in.
var EXCLUDED_KEYS = [
    "chatSignInStorage", "chatProfileGeneration", "chatAutoLockMinutes",
    "chatVaultUnlock", "chatSiteZoom", "configSchemaVersion",
    "initialSetupComplete", "usageHistoryEnabled", "usageHistoryClearOwed"
]
var OPERATIONS = ["status", "export", "import"]
var ERRORS = ["absent", "invalid", "unsupported", "too-large", "bad-data", "symlink", "not-owned",
              "unsafe-mode", "legacy-data", "os-error"]
// A malformed reply; the helper's own "invalid" is about the file.
var BAD_REPLY = "bad-reply"

var MAX_STRING_CHARS = 4096
var MAX_CUSTOM_URLS_CHARS = 32768
var MAX_CUSTOM_URL_LENGTH = 2048
// One argv string is limited to 128 KiB; the helper's own limit is that size.
var MAX_DATA_HEX = 130000
// The helper's file limit (64 KiB) and room for the reply's other fields.
var MAX_REPLY_CHARS = 65536 + 1024

var REFRESH_INTERVALS = [60, 300, 900, 1800, 3600]
var WARN_PERCENTS = [50, 55, 60, 65, 70, 75, 80, 85, 90]
var CRITICAL_PERCENTS = [55, 60, 65, 70, 75, 80, 85, 90, 95]
var ALERT_PERCENTS = [5, 10, 15, 20, 25, 30, 40, 50]
var USAGE_MODES = ["remaining", "used"]
var POPUP_TABS = ["chat", "usage"]
var POPUP_SIZES = ["compact", "normal", "large"]
var SHORTCUT_TARGETS = ["popup", "chat", "ollama", "usage"]
var OLLAMA_ID = "ollama"

var HEX_PATTERN = /^(?:[0-9a-f]{2})+$/
var STAMP_PATTERN = /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/
var CONTROL_PATTERN = /[\u0000-\u001f\u007f-\u009f]/
var LONE_SURROGATE = /[\ud800-\udbff](?![\udc00-\udfff])|(?:[^\ud800-\udbff]|^)[\udc00-\udfff]/
var COLOR_PATTERN = /^#[0-9a-fA-F]{6}$/

function isObject(value) {
    return !!value && typeof value === "object" && !Array.isArray(value)
}

function isCount(value) {
    return typeof value === "number" && isFinite(value) && Math.floor(value) === value && value >= 0
}

function hasExactly(object, keys) {
    var names = Object.keys(object)
    return names.length === keys.length && keys.every(function (key) { return names.indexOf(key) >= 0 })
}

function has(object, key) {
    return Object.prototype.hasOwnProperty.call(object, key)
}

// Lowercase hex of the UTF-8 bytes of text; "" for text that isn't valid.
function hexUtf8(text) {
    var encoded = ""
    try {
        encoded = encodeURIComponent(text)
    } catch (error) {
        return ""
    }
    var result = ""
    for (var index = 0; index < encoded.length; index++) {
        if (encoded[index] === "%") {
            result += encoded.substr(index + 1, 2).toLowerCase()
            index += 2
        } else {
            var code = encoded.charCodeAt(index).toString(16)
            result += code.length < 2 ? "0" + code : code
        }
    }
    return result
}

// The --data text for an export: the backup keys of settings as hex of UTF-8
// JSON, or "" when there is nothing to send or it is too long for one argument.
function exportPayload(settings) {
    if (!isObject(settings))
        return ""
    var picked = {}
    var count = 0
    BACKUP_KEYS.forEach(function (key) {
        if (has(settings, key) && settings[key] !== undefined) {
            picked[key] = settings[key]
            count += 1
        }
    })
    if (count === 0)
        return ""
    var hex = hexUtf8(JSON.stringify(picked))
    return hex.length <= MAX_DATA_HEX ? hex : ""
}

// The helper command, or "" for anything odd. Built only from the fixed
// helper name, a known operation, a whole run number and checked hex.
function backupCommand(op, run, data) {
    if (OPERATIONS.indexOf(op) < 0 || !isCount(run))
        return ""
    var command = "env HEARTHWIRE_RUN=" + run + " python3 -P -m hearthwire --settings-backup " + op
    if (op !== "export")
        return command
    return typeof data === "string" && data.length <= MAX_DATA_HEX && HEX_PATTERN.test(data)
        ? command + " --data " + data : ""
}

function validStamp(value) {
    return typeof value === "string" && STAMP_PATTERN.test(value)
}

// A checked stamp as "YYYY-MM-DD HH:MM:SS UTC"; "" for anything else.
function shownStamp(value) {
    return validStamp(value) ? value.replace("T", " ").replace("Z", " UTC") : ""
}

// A helper reply. status: {ok, exists, exportedAt}; export: {ok, saved,
// dropped}; import: {ok, exportedAt, settings, dropped}; otherwise {ok: false,
// error}, error being one of ERRORS or BAD_REPLY. Nothing else is kept.
function parseReply(op, exitCode, stdout) {
    var bad = { ok: false, error: BAD_REPLY }
    if (OPERATIONS.indexOf(op) < 0 || exitCode !== 0 || typeof stdout !== "string"
            || stdout === "" || stdout.length > MAX_REPLY_CHARS)
        return bad
    var reply = null
    try {
        reply = JSON.parse(stdout)
    } catch (error) {
        return bad
    }
    if (!isObject(reply))
        return bad
    if (reply.ok === false) {
        return hasExactly(reply, ["ok", "error"]) && typeof reply.error === "string"
            && ERRORS.indexOf(reply.error) >= 0 ? { ok: false, error: reply.error } : bad
    }
    if (reply.ok !== true)
        return bad
    if (op === "status") {
        if (reply.exists === false && hasExactly(reply, ["ok", "exists"]))
            return { ok: true, exists: false, exportedAt: "" }
        return reply.exists === true && hasExactly(reply, ["ok", "exists", "exported_at"])
            && validStamp(reply.exported_at) ? { ok: true, exists: true, exportedAt: reply.exported_at } : bad
    }
    if (op === "export") {
        return hasExactly(reply, ["ok", "saved", "dropped"]) && isCount(reply.saved) && reply.saved > 0
            && isCount(reply.dropped) ? { ok: true, saved: reply.saved, dropped: reply.dropped } : bad
    }
    return hasExactly(reply, ["ok", "exported_at", "settings", "dropped"]) && validStamp(reply.exported_at)
        && isObject(reply.settings) && isCount(reply.dropped)
        ? { ok: true, exportedAt: reply.exported_at, settings: reply.settings, dropped: reply.dropped } : bad
}

// --- the widget's own check of an import ------------------------------------

function isText(value, limit) {
    return typeof value === "string" && value.length <= limit
        && !CONTROL_PATTERN.test(value) && !LONE_SURROGATE.test(value)
}

function embedded(value, limit) {
    if (!isText(value, limit))
        return undefined
    try {
        return JSON.parse(value)
    } catch (error) {
        return undefined
    }
}

function idList(value, known) {
    return Array.isArray(value) && value.every(function (id, index) {
        return typeof id === "string" && known.indexOf(id) >= 0 && value.indexOf(id) === index
    })
}

function jsonIdList(value, known) {
    var parsed = embedded(value, MAX_STRING_CHARS)
    return idList(parsed, known) ? JSON.stringify(parsed) : null
}

function providerEntry(providers, id) {
    for (var index = 0; index < providers.length; index++) {
        if (providers[index] && providers[index].provider_id === id)
            return providers[index]
    }
    return null
}

// {providerId: [metricIds]} as canonical JSON, in catalog order; null if odd.
function metricMap(value, providers) {
    var parsed = embedded(value, MAX_STRING_CHARS)
    if (!isObject(parsed))
        return null
    var result = {}
    var names = Object.keys(parsed)
    for (var index = 0; index < names.length; index++) {
        var provider = providerEntry(providers, names[index])
        if (!provider || !idList(parsed[names[index]], (provider.metrics || []).map(function (metric) { return metric.id })))
            return null
    }
    providers.forEach(function (provider) {
        if (provider && has(parsed, provider.provider_id))
            result[provider.provider_id] = parsed[provider.provider_id]
    })
    return JSON.stringify(result)
}

function color(value) {
    if (!isText(value, MAX_STRING_CHARS))
        return null
    if (value === "")
        return ""
    return COLOR_PATTERN.test(value) ? value.toLowerCase() : null
}

function choice(value, options) {
    return options.indexOf(value) >= 0 ? value : null
}

function bool(value) {
    return typeof value === "boolean" ? value : null
}

// Every value checked, one key: the value to store, or null to drop it.
function checkedValue(key, value, tools) {
    var providers = tools.providers
    var providerIds = providers.map(function (provider) { return provider.provider_id })
    var chatIds = tools.webSiteIds.concat([OLLAMA_ID])
    switch (key) {
    case "trackedProviders":
        return jsonIdList(value, providerIds)
    case "providerOrder":
        return value === "" ? "" : jsonIdList(value, providerIds)
    case "providerMetrics":
        return metricMap(value, providers)
    case "tooltipMetrics":
        return value === "" ? "" : metricMap(value, providers)
    case "usageMode":
        return choice(value, USAGE_MODES)
    case "refreshInterval":
        return choice(value, REFRESH_INTERVALS)
    case "tooltipShowsUsage":
    case "usageCompact":
    case "alertLowEnabled":
    case "alertResetEnabled":
    case "chatKeepOpen":
    case "showUsageTab":
    case "showChatTab":
        return bool(value)
    case "usageWarnPercent":
        return choice(value, WARN_PERCENTS)
    case "usageCriticalPercent":
        return choice(value, CRITICAL_PERCENTS)
    case "usageNormalColor":
    case "usageWarnColor":
    case "usageCriticalColor":
        return color(value)
    case "alertLowPercent":
        return choice(value, ALERT_PERCENTS)
    case "chatSites":
        return jsonIdList(value, chatIds)
    case "chatDefaultSite":
        return choice(value, chatIds)
    case "popupDefaultTab":
        return choice(value, POPUP_TABS)
    case "popupSize":
        return choice(value, POPUP_SIZES)
    case "shortcutOpens":
        return choice(value, SHORTCUT_TARGETS)
    case "chatOllamaUrl":
        return typeof value === "string" && value !== "" && tools.ollamaAddress(value) === value ? value : null
    case "panelRing":
        return value === "off" || value === "auto" || tools.ringPairs.indexOf(value) >= 0 ? value : null
    case "middleClickOpens":
        return choice(value, ["refresh", "usage", OLLAMA_ID].concat(tools.webSiteIds))
    case "chatCustomUrls":
        return customUrls(value, tools)
    }
    return null
}

// {siteId: url} as canonical JSON by the widget's own address rule; one odd
// entry drops the whole setting, as the helper does.
function customUrls(value, tools) {
    var parsed = embedded(value, MAX_CUSTOM_URLS_CHARS)
    if (!isObject(parsed))
        return null
    var names = Object.keys(parsed)
    for (var index = 0; index < names.length; index++) {
        var url = parsed[names[index]]
        if (!isText(url, MAX_CUSTOM_URL_LENGTH) || url === "")
            return null
        var checked = tools.validateCustomUrl(names[index], url)
        if (!checked || checked.ok !== true || checked.url !== url)
            return null
    }
    var result = {}
    tools.webSiteIds.forEach(function (id) {
        if (has(parsed, id))
            result[id] = parsed[id]
    })
    return JSON.stringify(result)
}

// What Replace would apply: {settings: {key: value}, applied, dropped}.
// settings holds only BACKUP_KEYS that pass the widget's check; dropped adds
// up what the helper dropped, what this check dropped and any other key.
// tools: {providers, webSiteIds, ringPairs, validateCustomUrl, ollamaAddress}.
function importPlan(settings, helperDropped, tools) {
    var source = isObject(settings) ? settings : {}
    var plan = { settings: {}, applied: 0, dropped: isCount(helperDropped) ? helperDropped : 0 }
    var names = Object.keys(source)
    names.forEach(function (name) {
        // Null for anything that isn't a backup key, excluded ones included.
        var value = checkedValue(name, source[name], tools)
        if (value === null) {
            plan.dropped += 1
            return
        }
        plan.settings[name] = value
        plan.applied += 1
    })
    // Pairs the settings pages themselves never store.
    dropPair(plan, "usageWarnPercent", "usageCriticalPercent", function (warn, critical) { return warn < critical })
    dropPair(plan, "showUsageTab", "showChatTab", function (usage, chat) { return usage || chat })
    return plan
}

function dropPair(plan, first, second, allowed) {
    if (!has(plan.settings, first) || !has(plan.settings, second)
            || allowed(plan.settings[first], plan.settings[second]))
        return
    delete plan.settings[first]
    delete plan.settings[second]
    plan.applied -= 2
    plan.dropped += 2
}
