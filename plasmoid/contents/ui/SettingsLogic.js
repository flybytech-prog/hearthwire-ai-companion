.pragma library

// Settings → General: pure normalizers for the popup options. Anything odd
// in the configuration falls back to the default.

var POPUP_TABS = ["chat", "usage"]
var POPUP_SIZES = ["compact", "normal", "large"]
var POPUP_SCALES = { compact: 0.8, normal: 1, large: 1.25 }

// "usage" or "chat"; anything else is "chat".
function normalizeDefaultTab(value) {
    return value === "usage" ? "usage" : "chat"
}

// compact, normal or large; anything else is normal.
function normalizePopupSize(value) {
    return POPUP_SIZES.indexOf(value) >= 0 ? value : "normal"
}

function popupScale(value) {
    return POPUP_SCALES[normalizePopupSize(value)]
}

// Which tabs the popup shows. Chat needs the setting on (exactly true) and
// at least one enabled site; Usage shows when it is on or when Chat can't
// show, so the popup is never empty.
function visibleTabs(showUsage, showChat, chatAvailable) {
    var chat = showChat === true && chatAvailable === true
    var usage = showUsage !== false || !chat
    return { usage: usage, chat: chat }
}

// The tab to show: the wanted one if it is visible, else the other.
function shownTab(wanted, tabs) {
    var tab = normalizeDefaultTab(wanted)
    var shown = tabs || { usage: true, chat: false }
    if (tab === "chat" && shown.chat === true)
        return "chat"
    if (tab === "usage" && shown.usage === true)
        return "usage"
    return shown.chat === true && shown.usage !== true ? "chat" : "usage"
}

// The other tab's box must stay checked: false when unticking this one
// would leave no tab.
function canUntick(otherChecked) {
    return otherChecked === true
}

// --- Keyboard shortcut target (Settings → General → Popup) -----------------

// popup = as when clicking the icon; ollama = the Ollama message box.
var SHORTCUT_TARGETS = ["popup", "chat", "ollama", "usage"]

// One of SHORTCUT_TARGETS; anything else is popup.
function normalizeShortcutTarget(value) {
    return SHORTCUT_TARGETS.indexOf(value) >= 0 ? value : "popup"
}

// What the shortcut opens: {tab, site, focusInput}. tab "" keeps the tab
// the popup would show anyway (popup target); site "" keeps the chat site.
// A hidden target tab falls back to the other one; Ollama needs the Chat tab
// and the Ollama entry, else it acts as popup.
function shortcutPlan(target, tabs, ollamaEnabled) {
    var shown = tabs || { usage: true, chat: false }
    var plan = { tab: "", site: "", focusInput: false }
    switch (normalizeShortcutTarget(target)) {
    case "chat":
        plan.tab = shown.chat === true ? "chat" : "usage"
        break
    case "usage":
        plan.tab = shown.usage === true || shown.chat !== true ? "usage" : "chat"
        break
    case "ollama":
        if (ollamaEnabled === true && shown.chat === true) {
            plan.tab = "chat"
            plan.site = "ollama"
            plan.focusInput = true
        }
        break
    }
    return plan
}

// --- Middle-click on the panel icon (Settings → General → Popup) ------------

// refresh = refresh usage; usage = the Usage tab; ollama = the Ollama message
// box; otherwise the id of a web chat site.
var MIDDLE_CLICK_TARGETS = ["refresh", "usage", "ollama"]

// One of MIDDLE_CLICK_TARGETS or one of webSiteIds; anything else is refresh.
function normalizeMiddleClick(value, webSiteIds) {
    if (MIDDLE_CLICK_TARGETS.indexOf(value) >= 0)
        return value
    return typeof value === "string" && value !== "" && Array.isArray(webSiteIds)
        && webSiteIds.indexOf(value) >= 0 ? value : "refresh"
}

// What a middle-click does: {action, tab, site, focusInput}. action is
// refresh, toggle (as a left click: the target's tab is hidden or its site
// is off), close (the popup already shows the target) or open (tab and site
// to show; also switches an open popup). state: {expanded, tabs, siteIds
// (the enabled chat entries, Ollama included), shownTab, siteId}.
function middleClickPlan(target, state) {
    var plan = { action: "refresh", tab: "", site: "", focusInput: false }
    if (target === "refresh")
        return plan
    var now = state || {}
    var tabs = now.tabs || {}
    var sites = Array.isArray(now.siteIds) ? now.siteIds : []
    if (target === "usage" ? tabs.usage !== true : tabs.chat !== true || sites.indexOf(target) < 0) {
        plan.action = "toggle"
        return plan
    }
    if (now.expanded === true && now.shownTab === (target === "usage" ? "usage" : "chat")
            && (target === "usage" || now.siteId === target)) {
        plan.action = "close"
        return plan
    }
    plan.action = "open"
    plan.tab = target === "usage" ? "usage" : "chat"
    plan.site = target === "usage" ? "" : target
    plan.focusInput = target === "ollama"
    return plan
}

// --- Per-site zoom (Ctrl+= / Ctrl+- / Ctrl+0) -------------------------------

var ZOOM_STEPS = [0.5, 0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0]

function isZoomStep(value) {
    return typeof value === "number" && ZOOM_STEPS.indexOf(value) >= 0
}

// {siteId: factor} from the stored JSON. Only allowed ids with a factor from
// ZOOM_STEPS other than 1.0 survive; anything odd is dropped.
function parseZoomMap(json, allowedIds) {
    var result = {}
    var parsed = null
    try {
        parsed = JSON.parse(typeof json === "string" ? json : "")
    } catch (error) {
        return result
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
        return result
    var allowed = Array.isArray(allowedIds) ? allowedIds : []
    for (var index = 0; index < allowed.length; index++) {
        var id = allowed[index]
        if (typeof id !== "string" || !Object.prototype.hasOwnProperty.call(parsed, id))
            continue
        var factor = parsed[id]
        if (isZoomStep(factor) && factor !== 1.0)
            result[id] = factor
    }
    return result
}

// The factor for id; 1.0 when it has none.
function zoomFor(map, id) {
    if (!map || typeof map !== "object" || typeof id !== "string"
            || !Object.prototype.hasOwnProperty.call(map, id))
        return 1.0
    return isZoomStep(map[id]) ? map[id] : 1.0
}

// The next step from current: direction +1 bigger, -1 smaller, 0 reset.
// A current value between steps moves to the neighbouring step.
function zoomStep(current, direction) {
    if (direction !== 1 && direction !== -1)
        return 1.0
    var value = typeof current === "number" && isFinite(current) ? current : 1.0
    if (direction === 1) {
        for (var up = 0; up < ZOOM_STEPS.length; up++) {
            if (ZOOM_STEPS[up] > value + 0.001)
                return ZOOM_STEPS[up]
        }
        return ZOOM_STEPS[ZOOM_STEPS.length - 1]
    }
    for (var down = ZOOM_STEPS.length - 1; down >= 0; down--) {
        if (ZOOM_STEPS[down] < value - 0.001)
            return ZOOM_STEPS[down]
    }
    return ZOOM_STEPS[0]
}

// The JSON to store after setting id to factor: keys sorted, 1.0 and odd
// factors removed, so the same zoom always gives the same text.
function zoomMapToPersist(map, id, factor) {
    var next = {}
    var source = map && typeof map === "object" ? map : {}
    for (var key in source) {
        if (Object.prototype.hasOwnProperty.call(source, key) && isZoomStep(source[key])
                && source[key] !== 1.0)
            next[key] = source[key]
    }
    if (typeof id === "string" && id !== "") {
        if (isZoomStep(factor) && factor !== 1.0)
            next[id] = factor
        else
            delete next[id]
    }
    var keys = Object.keys(next).sort()
    var sorted = {}
    for (var index = 0; index < keys.length; index++)
        sorted[keys[index]] = next[keys[index]]
    return JSON.stringify(sorted)
}

// --- Usage alerts (Settings → General → Usage) ------------------------------

// Percent left at or below which "running low" fires.
var ALERT_PERCENTS = [5, 10, 15, 20, 25, 30, 40, 50]

// One of ALERT_PERCENTS; anything else is 20.
function normalizeAlertPercent(value) {
    return ALERT_PERCENTS.indexOf(value) >= 0 ? value : 20
}
