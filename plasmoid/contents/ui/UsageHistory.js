.pragma library

// The opt-in usage history (Settings → General → Privacy): pure rules, no QML
// state. main.qml and configGeneral.qml pass the catalog, the replies and the
// clock in. The helper's reply is checked in full before any of it is used:
// one odd field and the whole reply counts as no history.

// At most one sample per this long; the helper keeps one per hour anyway.
var RECORD_MIN_GAP_MS = 900000
var BUCKET_SECONDS = 3600
// Seven days of hour buckets behind the current one.
var KEEP_BUCKETS = 168
var MAX_PAIRS = 64
// The helper's file limit (256 KiB) and room for the reply's other fields.
var MAX_REPLY_CHARS = 262144 + 1024
var OPERATIONS = ["read", "record", "clear"]
// How often a clear is tried in a row while the helper answers busy.
var CLEAR_MAX_TRIES = 3
var CLEAR_RETRY_MS = 3000
var ERRORS = ["bad-sample", "symlink", "not-directory", "not-owned", "busy", "legacy-data", "os-error"]

var ID_PATTERN = /^[a-z_]{1,32}$/
var SAMPLE_PATTERN = /^[a-z_]{1,32}\.[a-z_]{1,32}=(100|[1-9]?[0-9])$/

function isInt(value) {
    return typeof value === "number" && isFinite(value) && Math.floor(value) === value
}

function isObject(value) {
    return !!value && typeof value === "object" && !Array.isArray(value)
}

function hasExactly(object, keys) {
    var names = Object.keys(object)
    return names.length === keys.length && keys.every(function (key) { return names.indexOf(key) >= 0 })
}

// "provider.metric" for every catalog reading that can have a history, in
// catalog order; extra_usage is money, not a percentage.
function catalogPairs(providers) {
    var result = []
    var list = Array.isArray(providers) ? providers : []
    for (var index = 0; index < list.length; index++) {
        var provider = list[index]
        if (!isObject(provider) || typeof provider.provider_id !== "string"
                || !ID_PATTERN.test(provider.provider_id) || !Array.isArray(provider.metrics))
            continue
        for (var at = 0; at < provider.metrics.length; at++) {
            var metric = provider.metrics[at]
            if (isObject(metric) && typeof metric.id === "string" && ID_PATTERN.test(metric.id)
                    && metric.id !== "extra_usage")
                result.push(provider.provider_id + "." + metric.id)
        }
    }
    return result
}

function firstWith(list, key, value) {
    for (var index = 0; index < list.length; index++) {
        if (isObject(list[index]) && list[index][key] === value)
            return list[index]
    }
    return null
}

// The --sample text for one helper run: "provider.metric=N,...", in catalog
// order, or "" when there is nothing to record. Only providers whose status
// is ok count; a reading above 100 is at its limit, so it reads as 100.
// results is the run's provider list, catalog the widget's own catalog.
function sampleArg(results, catalog) {
    var list = Array.isArray(results) ? results : []
    var pairs = catalogPairs(catalog)
    var items = []
    for (var index = 0; index < pairs.length && items.length < MAX_PAIRS; index++) {
        var parts = pairs[index].split(".")
        var provider = firstWith(list, "provider_id", parts[0])
        if (!provider || provider.status !== "ok" || provider.stale === true || !Array.isArray(provider.windows))
            continue
        var reading = firstWith(provider.windows, "kind", parts[1])
        if (!reading || typeof reading.used_percent !== "number" || !isFinite(reading.used_percent))
            continue
        items.push(pairs[index] + "=" + Math.round(Math.max(0, Math.min(100, reading.used_percent))))
    }
    return items.join(",")
}

function validSample(sample) {
    if (typeof sample !== "string" || sample === "")
        return false
    var items = sample.split(",")
    return items.length <= MAX_PAIRS && items.every(function (item) { return SAMPLE_PATTERN.test(item) })
}

// The helper command, or "" for anything odd. Built only from the fixed
// helper name, a known operation, a whole run number and a checked sample;
// the run only makes the source name unique.
function historyCommand(op, run, sample) {
    if (OPERATIONS.indexOf(op) < 0 || !isInt(run) || run < 0)
        return ""
    var command = "env HEARTHWIRE_RUN=" + run + " python3 -P -m hearthwire --usage-history " + op
    if (op !== "record")
        return command
    return validSample(sample) ? command + " --sample " + sample : ""
}

// Whether a sample may be recorded now; a clock that went back never blocks it.
function recordDue(lastMs, nowMs) {
    var now = Number(nowMs)
    var last = Number(lastMs)
    if (nowMs === null || nowMs === undefined || !isFinite(now))
        return false
    if (!isFinite(last) || last <= 0 || now < last)
        return true
    return now - last >= RECORD_MIN_GAP_MS
}

// One series as [[t, used], ...], or null when any point is odd: hour
// buckets only, ascending, inside the last seven days, used 0..100.
function parsePoints(points, now) {
    if (!Array.isArray(points) || points.length === 0)
        return null
    var newest = now - now % BUCKET_SECONDS
    var oldest = newest - KEEP_BUCKETS * BUCKET_SECONDS
    var result = []
    var previous = -1
    for (var index = 0; index < points.length; index++) {
        var point = points[index]
        if (!Array.isArray(point) || point.length !== 2 || !isInt(point[0]) || !isInt(point[1]))
            return null
        if (point[0] < 0 || point[0] % BUCKET_SECONDS !== 0 || point[0] <= previous
                || point[0] < oldest || point[0] > newest || point[1] < 0 || point[1] > 100)
            return null
        previous = point[0]
        result.push([point[0], point[1]])
    }
    return result
}

// {pair: points} from the reply's series, or null when anything is odd.
function parseSeries(entries, now, catalog) {
    if (!Array.isArray(entries))
        return null
    var pairs = catalogPairs(catalog)
    var series = {}
    for (var index = 0; index < entries.length; index++) {
        var entry = entries[index]
        if (!isObject(entry) || !hasExactly(entry, ["provider_id", "metric_id", "points"])
                || typeof entry.provider_id !== "string" || typeof entry.metric_id !== "string")
            return null
        var pair = entry.provider_id + "." + entry.metric_id
        if (pairs.indexOf(pair) < 0 || Object.prototype.hasOwnProperty.call(series, pair))
            return null
        var points = parsePoints(entry.points, now)
        if (points === null)
            return null
        series[pair] = points
    }
    return series
}

// A helper reply. read and record: {ok: true, now, series: {pair: points}};
// clear: {ok: true}; otherwise {ok: false, error}, error being one of ERRORS
// or "invalid" for anything malformed. Nothing else of a reply is kept.
function parseReply(op, exitCode, stdout, catalog) {
    var invalid = { ok: false, error: "invalid" }
    if (OPERATIONS.indexOf(op) < 0 || exitCode !== 0 || typeof stdout !== "string"
            || stdout === "" || stdout.length > MAX_REPLY_CHARS)
        return invalid
    var reply = null
    try {
        reply = JSON.parse(stdout)
    } catch (error) {
        return invalid
    }
    if (!isObject(reply))
        return invalid
    if (reply.ok === false) {
        return hasExactly(reply, ["ok", "error"]) && typeof reply.error === "string"
            && ERRORS.indexOf(reply.error) >= 0 ? { ok: false, error: reply.error } : invalid
    }
    if (reply.ok !== true)
        return invalid
    if (op === "clear")
        return hasExactly(reply, ["ok"]) ? { ok: true } : invalid
    if (!hasExactly(reply, ["ok", "history_version", "bucket_seconds", "now", "series"])
            || reply.history_version !== 1 || reply.bucket_seconds !== BUCKET_SECONDS
            || !isInt(reply.now) || reply.now < 0)
        return invalid
    var series = parseSeries(reply.series, reply.now, catalog)
    return series === null ? invalid : { ok: true, now: reply.now, series: series }
}

// What follows a clear's reply, triesDone counting this one: done, retry
// (only for busy, a bounded number of times) or failed.
function clearNext(reply, triesDone) {
    if (reply && reply.ok === true)
        return "done"
    return reply && reply.error === "busy" && triesDone < CLEAR_MAX_TRIES ? "retry" : "failed"
}

// The sparkline's strokes in a box of width x height: seven days up to the
// current hour, left to right. Each is {x1, y1, x2, y2, used, dot}: used is
// percent used at its end, for the level color; dot is a lone hour with no
// neighbor, drawn as a dot. Hours without a sample leave a gap. y follows
// Left or Used like the bars; inset keeps the strokes inside the box.
function sparkSegments(points, nowSeconds, mode, width, height, inset) {
    var w = Number(width)
    var h = Number(height)
    var margin = Number(inset)
    if (!isFinite(margin) || margin < 0)
        margin = 0
    var now = Number(nowSeconds)
    if (!Array.isArray(points) || !isFinite(w) || !isFinite(h) || w <= margin * 2 || h <= margin * 2
            || !isFinite(now) || now <= 0)
        return []
    var newest = now - now % BUCKET_SECONDS
    var oldest = newest - KEEP_BUCKETS * BUCKET_SECONDS
    var span = newest - oldest
    var plotted = []
    for (var index = 0; index < points.length; index++) {
        var point = points[index]
        if (!Array.isArray(point) || !isInt(point[0]) || !isInt(point[1])
                || point[0] < oldest || point[0] > newest || point[1] < 0 || point[1] > 100)
            continue
        var shown = mode === "used" ? point[1] : 100 - point[1]
        plotted.push({
            t: point[0],
            used: point[1],
            x: margin + (point[0] - oldest) / span * (w - margin * 2),
            y: margin + (1 - shown / 100) * (h - margin * 2)
        })
    }
    var segments = []
    for (var at = 0; at < plotted.length; at++) {
        var here = plotted[at]
        var joinsNext = at + 1 < plotted.length && plotted[at + 1].t - here.t === BUCKET_SECONDS
        var joinsPrevious = at > 0 && here.t - plotted[at - 1].t === BUCKET_SECONDS
        if (joinsNext) {
            var next = plotted[at + 1]
            segments.push({x1: here.x, y1: here.y, x2: next.x, y2: next.y, used: next.used, dot: false})
        } else if (!joinsPrevious) {
            segments.push({x1: here.x, y1: here.y, x2: here.x, y2: here.y, used: here.used, dot: true})
        }
    }
    return segments
}
