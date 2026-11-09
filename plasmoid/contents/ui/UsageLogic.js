.pragma library

// The Usage tab's choices: pure rules, no QML state. main.qml, UsageView.qml
// and configUsage.qml pass the catalog ids, the settings and the clock in,
// and do the translating; nothing here reads the configuration.
//
// providerOrder: a JSON array of catalog ids; "" (or anything unreadable)
// means catalog order. Unknown ids are dropped, missing ones appended.
// providerMetrics: {providerId: [metricIds]}; a provider without a list, or
// with an empty one, shows all its readings in the Usage tab.

var COLOR_PERCENTS = [50, 55, 60, 65, 70, 75, 80, 85, 90, 95]
// The settings page's choices: the warning level stays below the critical one.
var WARN_PERCENTS = COLOR_PERCENTS.slice(0, COLOR_PERCENTS.length - 1)
var CRITICAL_PERCENTS = COLOR_PERCENTS.slice(1)
var DEFAULT_WARN = 60
var DEFAULT_CRITICAL = 85
var MINUTE_MS = 60000
// Longest provider-supplied text (name, plan, caption, error) shown as is.
var MAX_SHOWN_CHARS = 200

// Helper (and so provider server) text as shown in the Usage tab: a string
// or number as text, cut to MAX_SHOWN_CHARS with "…" at the end (never in
// the middle of a surrogate pair); anything else is "".
function shownText(value) {
    var text = typeof value === "string" ? value
        : typeof value === "number" && isFinite(value) ? String(value) : ""
    if (text.length <= MAX_SHOWN_CHARS)
        return text
    var cut = MAX_SHOWN_CHARS - 1
    var last = text.charCodeAt(cut - 1)
    if (last >= 0xd800 && last <= 0xdbff)
        cut -= 1
    return text.slice(0, cut) + "\u2026"
}

// A plain array from an array or an array-like list (a Repeater's
// modelData hands its lists over as sequences, not arrays); else [].
function toArray(value) {
    if (Array.isArray(value))
        return value
    if (value && typeof value === "object" && typeof value.length === "number" && value.length >= 0)
        return Array.prototype.slice.call(value)
    return []
}

// Every id of ids exactly once: the configured order first, then the rest
// in the order of ids.
function normalizeOrder(value, ids) {
    var known = toArray(ids)
    var parsed = []
    if (typeof value === "string" && value !== "") {
        try {
            parsed = JSON.parse(value)
        } catch (error) {
            parsed = []
        }
    }
    if (!Array.isArray(parsed))
        parsed = []
    var result = []
    var all = parsed.concat(known)
    for (var index = 0; index < all.length; index++) {
        var id = all[index]
        if (typeof id === "string" && known.indexOf(id) >= 0 && result.indexOf(id) < 0)
            result.push(id)
    }
    return result
}

// Where providerId would move to (direction -1 up, +1 down): the index of
// the next id in that direction that is in eligible (every id when eligible
// isn't given), or -1 when it can't move. providerId must be eligible too.
function moveTarget(order, providerId, direction, eligible) {
    var list = toArray(order)
    var allowed = eligible === undefined || eligible === null ? list : toArray(eligible)
    var at = list.indexOf(providerId)
    if (at < 0 || allowed.indexOf(providerId) < 0)
        return -1
    var step = direction < 0 ? -1 : 1
    for (var to = at + step; to >= 0 && to < list.length; to += step) {
        if (allowed.indexOf(list[to]) >= 0)
            return to
    }
    return -1
}

function canMove(order, providerId, direction, eligible) {
    return moveTarget(order, providerId, direction, eligible) >= 0
}

// Swaps providerId with the next eligible id in that direction; ids in
// between stay where they are. A new array, unchanged when it can't move.
function moveId(order, providerId, direction, eligible) {
    var result = toArray(order).slice()
    var to = moveTarget(result, providerId, direction, eligible)
    if (to < 0)
        return result
    var at = result.indexOf(providerId)
    result[at] = result[to]
    result[to] = providerId
    return result
}

// The ListModel.move(from, to, 1) steps that turn the ids current into
// wanted, so the settings list keeps its rows (and their focus) instead of
// being rebuilt; null when the two don't hold the same unique ids.
function syncMoves(current, wanted) {
    var have = toArray(current).slice()
    var want = toArray(wanted)
    if (have.length !== want.length)
        return null
    for (var check = 0; check < want.length; check++) {
        if (have.indexOf(want[check]) < 0 || want.indexOf(want[check]) !== check
                || have.indexOf(have[check]) !== check)
            return null
    }
    var moves = []
    for (var index = 0; index < want.length; index++) {
        var from = have.indexOf(want[index])
        if (from === index)
            continue
        moves.push({from: from, to: index})
        have.splice(index, 0, have.splice(from, 1)[0])
    }
    return moves
}

// Items with a provider_id sorted by order; ids not in order keep their
// relative place after the ordered ones. Never mutates the input.
function orderProviders(items, order) {
    var list = toArray(items).filter(function (item) {
        return !!item && typeof item === "object"
    })
    var ranks = toArray(order)
    var decorated = list.map(function (item, index) {
        var rank = ranks.indexOf(item.provider_id)
        return {item: item, rank: rank < 0 ? ranks.length : rank, index: index}
    })
    decorated.sort(function (a, b) {
        return a.rank !== b.rank ? a.rank - b.rank : a.index - b.index
    })
    return decorated.map(function (entry) { return entry.item })
}

function showsAll(chosen) {
    return toArray(chosen).length === 0
}

// The quota windows the Usage tab shows: all of them for an empty choice,
// else those whose kind is chosen.
function shownWindows(windows, chosen) {
    var list = toArray(windows).filter(function (window) {
        return !!window && typeof window === "object"
    })
    if (showsAll(chosen))
        return list
    var wanted = toArray(chosen)
    return list.filter(function (window) { return wanted.indexOf(window.kind) >= 0 })
}

// The metric id a billing entry reads as: extra_usage or credits, else "".
function billingMetric(billing) {
    if (!billing || typeof billing !== "object")
        return ""
    if (billing.kind === "bounded_spend" || billing.kind === "unbounded_spend")
        return "extra_usage"
    if (billing.kind === "flex_credit_balance")
        return "credits"
    return ""
}

function showsBilling(billing, chosen) {
    if (!billing || typeof billing !== "object")
        return false
    return showsAll(chosen) || toArray(chosen).indexOf(billingMetric(billing)) >= 0
}

// The chosen ids that are still catalog metrics of the provider, in catalog
// order; ids the catalog dropped are ignored, as main.qml does.
function effectiveChoice(chosen, allIds) {
    var given = toArray(chosen)
    return toArray(allIds).filter(function (id) { return given.indexOf(id) >= 0 })
}

// Whether metricId is the only reading the Usage tab shows for a provider,
// so its box can't be unticked.
function isLastShown(chosen, allIds, metricId) {
    var ids = toArray(allIds)
    var shown = effectiveChoice(chosen, ids)
    if (shown.length === 0)
        shown = ids
    return shown.length === 1 && shown[0] === metricId
}

// Whether a reading's box is ticked: every box while the choice is empty.
function isShown(chosen, metricId) {
    return showsAll(chosen) || toArray(chosen).indexOf(metricId) >= 0
}

// Ticks or unticks one reading; allIds are the provider's catalog metric ids.
// The result is in catalog order without ids the catalog dropped; every
// reading ticked is stored as [] (show all), and the last ticked reading
// can't be unticked.
function toggleMetric(chosen, allIds, metricId, enabled) {
    var ids = toArray(allIds)
    var given = effectiveChoice(chosen, ids)
    if (ids.indexOf(metricId) < 0)
        return given.slice()
    var current = given.length === 0 ? ids.slice() : given.slice()
    var next = ids.filter(function (id) {
        return id === metricId ? enabled === true : current.indexOf(id) >= 0
    })
    if (next.length === 0)
        return given.length === 0 ? [] : ids.filter(function (id) { return current.indexOf(id) >= 0 })
    return next.length === ids.length ? [] : next
}

function snapPercent(value, fallback) {
    var number = Number(value)
    if (value === null || value === undefined || value === "" || !isFinite(number))
        return fallback
    var best = COLOR_PERCENTS[0]
    for (var index = 1; index < COLOR_PERCENTS.length; index++) {
        if (Math.abs(COLOR_PERCENTS[index] - number) < Math.abs(best - number))
            best = COLOR_PERCENTS[index]
    }
    return best
}

// {warn, critical} in percent used, both from COLOR_PERCENTS, with
// critical above warn.
function normalizeThresholds(warn, critical) {
    var low = snapPercent(warn, DEFAULT_WARN)
    var high = snapPercent(critical, DEFAULT_CRITICAL)
    if (high <= low) {
        if (low >= COLOR_PERCENTS[COLOR_PERCENTS.length - 1])
            low = COLOR_PERCENTS[COLOR_PERCENTS.length - 2]
        high = Math.max(high, low + 5)
    }
    return {warn: low, critical: high}
}

// The default normal bar color: a teal that reads on the background
// (r, g, b from 0 to 1).
function defaultNormalColor(red, green, blue) {
    var luminance = Number(red) * 0.2126 + Number(green) * 0.7152 + Number(blue) * 0.0722
    return luminance < 0.5 ? "#32c7d3" : "#008c95"
}

// A color setting: "" (the default color) or "#rrggbb" in lower case;
// anything else is "".
function normalizeColor(value) {
    return typeof value === "string" && /^#[0-9a-fA-F]{6}$/.test(value) ? value.toLowerCase() : ""
}

// The custom color the critical level uses: its own, else the custom
// warning color; "" means the theme's color.
function effectiveCriticalColor(critical, warning) {
    var own = normalizeColor(critical)
    return own !== "" ? own : normalizeColor(warning)
}

// A bar's fill in the width of its track: its share of the track, but at
// least minimumWidth so the color can be seen, and never wider than the
// track. 0 for a percent of 0 or less, or anything that isn't a number.
function fillWidth(trackWidth, displayedPercent, minimumWidth) {
    var track = Number(trackWidth)
    var percent = Number(displayedPercent)
    var minimum = Number(minimumWidth)
    if (!isFinite(track) || track <= 0 || !isFinite(percent) || percent <= 0)
        return 0
    var share = track * Math.min(1, percent / 100)
    return Math.min(track, Math.max(share, isFinite(minimum) ? minimum : 0))
}

// A level in percent used as the settings page shows it: as used, or in
// Left mode ("remaining") as what is left at that level.
function shownPercent(percentUsed, mode) {
    var used = Number(percentUsed)
    if (!isFinite(used))
        return 0
    return mode === "used" ? used : 100 - used
}

// "critical", "warning" or "normal" for a used percentage.
function usageLevel(rawUsed, thresholds) {
    var used = Number(rawUsed)
    if (!isFinite(used))
        return "normal"
    var limits = thresholds && typeof thresholds === "object"
        ? normalizeThresholds(thresholds.warn, thresholds.critical)
        : normalizeThresholds(DEFAULT_WARN, DEFAULT_CRITICAL)
    if (used >= limits.critical)
        return "critical"
    if (used >= limits.warn)
        return "warning"
    return "normal"
}

// How long ago the last reading arrived, as parts for the caller to
// translate, or null when there is none. kind: "now", "minutes" {minutes},
// "hours" {hours} or "days" {days}.
function updatedPhrase(updatedMs, nowMs) {
    var then = Number(updatedMs)
    var now = Number(nowMs)
    if (!isFinite(then) || !isFinite(now) || then <= 0)
        return null
    var minutes = Math.floor(Math.max(0, now - then) / MINUTE_MS)
    if (minutes < 1)
        return {kind: "now"}
    if (minutes < 60)
        return {kind: "minutes", minutes: minutes}
    var hours = Math.floor(minutes / 60)
    if (hours < 24)
        return {kind: "hours", hours: hours}
    return {kind: "days", days: Math.floor(hours / 24)}
}

// A short countdown {days, hours, minutes} until a reset, null when the
// time is unknown, or {days: 0, hours: 0, minutes: 0} once it has passed.
function shortCountdown(resetsAtMs, nowMs) {
    var target = Number(resetsAtMs)
    var now = Number(nowMs)
    if (resetsAtMs === null || resetsAtMs === undefined || resetsAtMs === ""
            || !isFinite(target) || !isFinite(now))
        return null
    var minutes = Math.max(0, Math.round((target - now) / MINUTE_MS))
    if (target > now)
        minutes = Math.max(1, minutes)
    return {days: Math.floor(minutes / 1440), hours: Math.floor(minutes / 60) % 24, minutes: minutes % 60}
}

// The Usage tab's "Next reset" line: of entries ({resetsAtMs, ...}, one per
// reading it shows), the one whose reset comes soonest after nowMs, the
// first of equals; null when none lies ahead. Returns the entry itself; the
// caller builds the text from the catalog.
function nextReset(entries, nowMs) {
    var now = Number(nowMs)
    if (nowMs === null || nowMs === undefined || nowMs === "" || !isFinite(now))
        return null
    var list = toArray(entries)
    var best = null
    for (var index = 0; index < list.length; index++) {
        var entry = list[index]
        if (!entry || typeof entry !== "object" || typeof entry.resetsAtMs !== "number"
                || !isFinite(entry.resetsAtMs) || entry.resetsAtMs <= now)
            continue
        if (best === null || entry.resetsAtMs < best.resetsAtMs)
            best = entry
    }
    return best
}

// Settings schema 2 -> 3: providerMetrics used to choose only the hover
// popup's readings (and the alerts'), and now filters the Usage tab. Returns
// the strings to store: providerMetrics becomes "{}" (show every reading),
// and while the hover popup was "Same as the Usage tab" (tooltipMetrics ""),
// the old choice moves to tooltipMetrics, so the hover popup keeps showing
// it. providers is the catalog ([{provider_id, metrics: [{id}]}]): only its
// providers and metric ids move, and a provider left with none is left out,
// because it showed its default metric, as an unlisted provider still does.
function catalogIdsOf(providers, providerId) {
    var list = toArray(providers)
    for (var index = 0; index < list.length; index++) {
        var provider = list[index]
        if (provider && provider.provider_id === providerId)
            return toArray(provider.metrics).map(function (metric) { return metric ? metric.id : "" })
    }
    return []
}

function migratedUsageMetrics(providerMetricsValue, tooltipMetricsValue, providers) {
    var tooltip = typeof tooltipMetricsValue === "string" ? tooltipMetricsValue : ""
    if (tooltip === "") {
        var parsed = null
        try {
            parsed = JSON.parse(typeof providerMetricsValue === "string" ? providerMetricsValue : "")
        } catch (error) {
            parsed = null
        }
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
            var kept = {}
            var count = 0
            for (var providerId in parsed) {
                if (!Object.prototype.hasOwnProperty.call(parsed, providerId))
                    continue
                var list = effectiveChoice(parsed[providerId], catalogIdsOf(providers, providerId))
                if (list.length === 0)
                    continue
                kept[providerId] = list
                count += 1
            }
            if (count > 0)
                tooltip = JSON.stringify(kept)
        }
    }
    return {providerMetrics: "{}", tooltipMetrics: tooltip}
}
