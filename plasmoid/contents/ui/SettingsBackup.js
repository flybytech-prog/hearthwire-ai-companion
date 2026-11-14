.pragma library

// Settings → General → Backup: pure rules, no QML state. The helper keeps one
// fixed file and checks every value; the widget checks the import again before
// the page applies it, so a reply can only ever set what the widget would
// store itself. Excluded keys are never exported and never applied. An export
// is the widget's applied settings, read by the helper from Plasma's own file.

var BACKUP_KEYS = [
    "trackedProviders", "providerMetrics", "providerOrder", "usageMode", "refreshInterval",
    "tooltipShowsUsage", "tooltipMetrics", "usageCompact",
    "usageWarnPercent", "usageCriticalPercent",
    "usageNormalColor", "usageWarnColor", "usageCriticalColor",
    "alertLowEnabled", "alertResetEnabled", "alertLowPercent",
    "chatSites", "chatDefaultSite", "chatOllamaUrl", "chatKeepOpen",
    "showUsageTab", "showChatTab", "popupDefaultTab", "popupSize", "shortcutOpens",
    "panelRing", "middleClickOpens", "chatCustomUrls",
    "chatUserSites", "chatSiteOrder"
]
// Sign-ins, the encrypted folder, zoom, first-run state and the history opt-in.
var EXCLUDED_KEYS = [
    "chatSignInStorage", "chatProfileGeneration", "chatAutoLockMinutes",
    "chatVaultUnlock", "chatSiteZoom", "configSchemaVersion",
    "initialSetupComplete", "usageHistoryEnabled", "usageHistoryClearOwed",
    "chatProfileLayout", "chatPendingSiteClears"
]
var OPERATIONS = ["status", "export", "import"]
var ERRORS = ["absent", "invalid", "unsupported", "too-large", "bad-data", "symlink", "not-owned",
              "unsafe-mode", "legacy-data", "os-error", "applet-not-found",
              "settings-unreadable"]
// A malformed reply; the helper's own "invalid" is about the file.
var BAD_REPLY = "bad-reply"

var MAX_STRING_CHARS = 4096
var MAX_CUSTOM_URLS_CHARS = 32768
var MAX_CUSTOM_URL_LENGTH = 2048
// ChatSites.MAX_USER_SITES and MAX_USER_SITES_CHARS (the helper's too).
var MAX_USER_SITES = 200
var MAX_USER_SITES_CHARS = 458752
// The same bound as ChatStorage.MAX_INT and the helper's --applet.
var MAX_APPLET = 2147483648
// The address changes an import confirmation lists one by one.
var MAX_SHOWN_CHANGES = 8
// The helper's file limit (512 KiB) and room for the reply's other fields.
var MAX_REPLY_CHARS = 524288 + 1024

var REFRESH_INTERVALS = [60, 300, 900, 1800, 3600]
var WARN_PERCENTS = [50, 55, 60, 65, 70, 75, 80, 85, 90]
var CRITICAL_PERCENTS = [55, 60, 65, 70, 75, 80, 85, 90, 95]
var ALERT_PERCENTS = [5, 10, 15, 20, 25, 30, 40, 50]
var USAGE_MODES = ["remaining", "used"]
var POPUP_TABS = ["chat", "usage"]
var POPUP_SIZES = ["compact", "normal", "large"]
var SHORTCUT_TARGETS = ["popup", "chat", "ollama", "usage"]
var OLLAMA_ID = "ollama"

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

// A widget id the helper accepts: a whole number from 1 to ChatStorage.MAX_INT.
function validApplet(value) {
    return isCount(value) && value >= 1 && value <= MAX_APPLET
}

// The helper command, or "" for anything odd. Built only from the fixed
// helper name, a known operation, a whole run number and the widget's id;
// the helper reads an export's settings from the widget's saved ones itself,
// so no setting ever goes on the command line.
function backupCommand(op, run, applet) {
    if (OPERATIONS.indexOf(op) < 0 || !isCount(run) || !validApplet(applet))
        return ""
    return "env HEARTHWIRE_RUN=" + run + " python3 -P -m hearthwire --settings-backup " + op + " --applet " + applet
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
// added: the added-site ids the same import keeps (chatUserSites); chatSites,
// chatSiteOrder, chatDefaultSite and middleClickOpens may name only those.
function checkedValue(key, value, tools, added) {
    var providers = tools.providers
    var providerIds = providers.map(function (provider) { return provider.provider_id })
    var addedIds = Array.isArray(added) ? added : []
    var chatIds = tools.webSiteIds.concat([OLLAMA_ID], addedIds)
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
        return choice(value, ["refresh", "usage", OLLAMA_ID].concat(tools.webSiteIds, addedIds))
    case "chatCustomUrls":
        return customUrls(value, tools)
    case "chatUserSites":
        return userSites(value, tools)
    case "chatSiteOrder":
        return value === "" ? "" : jsonIdList(value, chatIds)
    }
    return null
}

// The added sites as the widget writes them (tools.serializeUserSites), by
// its own rule (tools.validateUserSite): a list of exactly {id, name, url}
// entries; one odd entry, a repeated id or name, more than MAX_USER_SITES
// entries or more than MAX_USER_SITES_CHARS drops the whole setting, as the
// helper does.
function userSites(value, tools) {
    if (typeof tools.validateUserSite !== "function" || typeof tools.serializeUserSites !== "function"
            || typeof value !== "string" || value.length > MAX_USER_SITES_CHARS)
        return null
    var parsed = embedded(value, MAX_USER_SITES_CHARS)
    if (!Array.isArray(parsed) || parsed.length > MAX_USER_SITES)
        return null
    for (var index = 0; index < parsed.length; index++) {
        var checked = tools.validateUserSite(parsed[index], parsed.slice(0, index))
        if (!checked || checked.ok !== true)
            return null
    }
    var text = tools.serializeUserSites(parsed)
    return typeof text === "string" && text !== "" ? text : null
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
// tools: {providers, webSiteIds, ringPairs, validateCustomUrl, ollamaAddress,
// userSiteIds, validateUserSite, serializeUserSites, and for renewing moved
// sites currentUserSites, userSiteHosts, newUserSiteId, excludedIds};
// userSiteIds(text) gives the ids of a checked chatUserSites value. The added ids other keys
// may name come only from this import's own chatUserSites, never the page.
function importPlan(settings, helperDropped, tools) {
    var source = isObject(settings) ? settings : {}
    var plan = { settings: {}, applied: 0, dropped: isCount(helperDropped) ? helperDropped : 0 }
    var names = Object.keys(source)
    var kept = has(source, "chatUserSites") ? checkedValue("chatUserSites", source.chatUserSites, tools) : null
    var added = kept !== null && typeof tools.userSiteIds === "function" ? tools.userSiteIds(kept) : []
    if (!Array.isArray(added))
        added = []
    names.forEach(function (name) {
        // Null for anything that isn't a backup key, excluded ones included.
        var value = checkedValue(name, source[name], tools, added)
        if (value === null) {
            plan.dropped += 1
            return
        }
        plan.settings[name] = value
        plan.applied += 1
    })
    renewMovedSites(plan, tools)
    // Pairs the settings pages themselves never store.
    dropPair(plan, "usageWarnPercent", "usageCriticalPercent", function (warn, critical) { return warn < critical })
    dropPair(plan, "showUsageTab", "showChatTab", function (usage, chat) { return usage || chat })
    return plan
}

// An added site of the backup whose id the page has with another host is
// another site (M1): it gets a new id, so applying removes the old one
// (its data is deleted) and adds the new one with a profile of its own,
// and the confirmation lists it as Removes and Adds. The other keys that
// name it follow. tools: currentUserSites (the page's), userSiteHosts,
// newUserSiteId(excluded), excludedIds (ids still owing a delete); without
// them nothing is renewed, and an id that can't be renewed drops the list.
// tools.unreadableHosts: {id: host} of applied entries the page can't read
// whose url still names a host (compared like the page's own);
// tools.unreadableIds: those with no host at all, renewed whatever the
// backup's host (fails closed).
function renewMovedSites(plan, tools) {
    if (!has(plan.settings, "chatUserSites") || typeof tools.userSiteHosts !== "function"
            || typeof tools.newUserSiteId !== "function")
        return
    var list = JSON.parse(plan.settings.chatUserSites)
    // The page's hosts, and for applied entries it can't read the host their
    // url still names (tools.unreadableHosts).
    var before = Object.assign({}, isObject(tools.unreadableHosts) ? tools.unreadableHosts : {},
        tools.userSiteHosts(tools.currentUserSites))
    var after = tools.userSiteHosts(list)
    var unreadable = Array.isArray(tools.unreadableIds) ? tools.unreadableIds : []
    var excluded = Object.keys(before).concat(Object.keys(after),
        Array.isArray(tools.excludedIds) ? tools.excludedIds : [], unreadable)
    var renamed = {}
    var count = 0
    for (var index = 0; index < list.length; index++) {
        var id = list[index].id
        // An id the applied settings hold but the page can't read: its old
        // host is unknown, so it is renewed too (fails closed, L-2b).
        if ((!has(before, id) || before[id] === after[id]) && unreadable.indexOf(id) < 0)
            continue
        var fresh = tools.newUserSiteId(excluded)
        if (typeof fresh !== "string" || !/^user-[0-9a-f]{8}$/.test(fresh) || excluded.indexOf(fresh) >= 0) {
            delete plan.settings.chatUserSites
            plan.applied -= 1
            plan.dropped += 1
            return
        }
        excluded.push(fresh)
        renamed[id] = fresh
        list[index] = {id: fresh, name: list[index].name, url: list[index].url}
        count += 1
    }
    if (count === 0)
        return
    plan.settings.chatUserSites = tools.serializeUserSites(list)
    var rename = function (id) { return has(renamed, id) ? renamed[id] : id }
    ;["chatSites", "chatSiteOrder"].forEach(function (key) {
        if (has(plan.settings, key) && plan.settings[key] !== "")
            plan.settings[key] = JSON.stringify(JSON.parse(plan.settings[key]).map(rename))
    })
    ;["chatDefaultSite", "middleClickOpens"].forEach(function (key) {
        if (has(plan.settings, key))
            plan.settings[key] = rename(plan.settings[key])
    })
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

// What Replace would change in the chat addresses: [{id, from, to}] in site
// order, then the added sites, Ollama last, each value capped by
// tools.shownText; [] when the plan leaves them alone. A custom address map
// replaces the whole map, so a site the backup has no address for goes back
// to its built-in one; both sides are the address the site would really
// open. An added-site list replaces the whole list: {kind: "add", id, name,
// host, http} for a new site (http: its address is plain http, derived from
// the scheme), {id, name, from, to} for a new address of the same
// id and {kind: "remove", id, name} for a site it no longer has (applying
// deletes its data). current holds the page's chatCustomUrls, chatOllamaUrl
// and chatUserSites. tools: {webSiteIds, parseCustomUrls, effectiveUrl,
// shownText, parseUserSites, hostOf}.
function addressChanges(current, plan, tools) {
    var now = isObject(current) ? current : {}
    var next = isObject(plan) && isObject(plan.settings) ? plan.settings : {}
    var result = []
    if (has(next, "chatCustomUrls")) {
        var before = tools.parseCustomUrls(now.chatCustomUrls)
        var after = tools.parseCustomUrls(next.chatCustomUrls)
        tools.webSiteIds.forEach(function (id) {
            var from = tools.effectiveUrl(id, before)
            var to = tools.effectiveUrl(id, after)
            if (from !== to)
                result.push({id: id, from: tools.shownText(from), to: tools.shownText(to)})
        })
    }
    if (has(next, "chatUserSites") && typeof tools.parseUserSites === "function")
        result = result.concat(userSiteChanges(tools.parseUserSites(now.chatUserSites).sites,
            tools.parseUserSites(next.chatUserSites).sites, tools))
    if (has(next, "chatOllamaUrl") && next.chatOllamaUrl !== now.chatOllamaUrl)
        result.push({id: OLLAMA_ID, from: tools.shownText(now.chatOllamaUrl), to: tools.shownText(next.chatOllamaUrl)})
    return result
}

function userSiteChanges(before, after, tools) {
    var find = function (list, id) {
        for (var index = 0; index < list.length; index++) {
            if (list[index].id === id)
                return list[index]
        }
        return null
    }
    var host = function (url) {
        return tools.shownText(typeof tools.hostOf === "function" ? tools.hostOf(url) : "")
    }
    var result = []
    after.forEach(function (site) {
        var old = find(before, site.id)
        if (old === null)
            result.push({kind: "add", id: site.id, name: tools.shownText(site.name), host: host(site.url),
                         http: /^http:/i.test(String(site.url))})
        else if (old.url !== site.url)
            result.push({id: site.id, name: tools.shownText(site.name), from: tools.shownText(old.url),
                         to: tools.shownText(site.url)})
    })
    before.forEach(function (site) {
        if (find(after, site.id) === null)
            result.push({kind: "remove", id: site.id, name: tools.shownText(site.name)})
    })
    return result
}
