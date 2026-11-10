import QtQuick
import QtTest
import "../../plasmoid/contents/ui/ProviderCatalog.js" as Catalog
import "../../plasmoid/contents/ui/UsageHistory.js" as UsageHistory

TestCase {
    name: "UsageHistory"

    readonly property int hour: 3600
    // A whole number of hours, so the current bucket is simply `now`.
    readonly property int now: 1700000000 - 1700000000 % 3600

    function reply(overrides) {
        return Object.assign({ok: true, history_version: 1, bucket_seconds: 3600, now: now,
                              series: [{provider_id: "claude", metric_id: "weekly", points: [[now - hour, 40], [now, 42]]}]},
                             overrides)
    }

    function parse(object) {
        return UsageHistory.parseReply("read", 0, JSON.stringify(object), Catalog.providers)
    }

    function rejected(object, what) {
        compare(parse(object), {ok: false, error: "invalid"}, what)
    }

    function withSeries(entry) {
        return reply({series: [entry]})
    }

    function point(list) {
        return withSeries({provider_id: "claude", metric_id: "weekly", points: list})
    }

    function test_constants() {
        compare(UsageHistory.RECORD_MIN_GAP_MS, 900000)
        compare(UsageHistory.OPERATIONS, ["read", "record", "clear"])
        compare(UsageHistory.ERRORS, ["bad-sample", "symlink", "not-directory", "not-owned", "busy", "legacy-data", "os-error"])
    }

    function ok(id, windows) {
        return {provider_id: id, status: "ok", windows: windows}
    }

    function test_sampleUsesCatalogOrderAndPairs() {
        var results = [ok("codex", [{kind: "weekly", used_percent: 3}]),
                       ok("claude", [{kind: "sonnet", used_percent: 40.4}, {kind: "session", used_percent: 97.6}])]
        compare(UsageHistory.sampleArg(results, Catalog.providers), "claude.session=98,claude.sonnet=40,codex.weekly=3")
    }

    function test_sampleOnlyOkStatus() {
        var windows = [{kind: "weekly", used_percent: 3}]
        compare(UsageHistory.sampleArg([{provider_id: "claude", status: "stale", windows: windows}], Catalog.providers), "")
        compare(UsageHistory.sampleArg([{provider_id: "claude", status: "error", windows: windows}], Catalog.providers), "")
        compare(UsageHistory.sampleArg([{provider_id: "claude", status: "ok", stale: true, windows: windows}], Catalog.providers), "")
        compare(UsageHistory.sampleArg([{provider_id: "claude", windows: windows}], Catalog.providers), "")
    }

    function test_sampleOnlyCatalogPairs() {
        compare(UsageHistory.sampleArg([ok("nobody", [{kind: "weekly", used_percent: 3}])], Catalog.providers), "")
        compare(UsageHistory.sampleArg([ok("claude", [{kind: "extra_usage", used_percent: 3}])], Catalog.providers), "")
        compare(UsageHistory.sampleArg([ok("claude", [{kind: "weekly;rm -rf ~", used_percent: 3}])], Catalog.providers), "")
        compare(UsageHistory.sampleArg([ok("claude", [{kind: "spark", used_percent: 3}])], Catalog.providers), "")
    }

    function test_sampleOddNumbers() {
        function sampleOf(value) {
            return UsageHistory.sampleArg([ok("claude", [{kind: "weekly", used_percent: value}])], Catalog.providers)
        }
        compare(sampleOf(0), "claude.weekly=0")
        compare(sampleOf(100), "claude.weekly=100")
        compare(sampleOf(140), "claude.weekly=100")
        compare(sampleOf(-3), "claude.weekly=0")
        compare(sampleOf(null), "", "null is not 0")
        compare(sampleOf(undefined), "")
        compare(sampleOf("40"), "")
        compare(sampleOf(NaN), "")
        compare(sampleOf(Infinity), "")
        compare(UsageHistory.sampleArg(null, Catalog.providers), "")
        compare(UsageHistory.sampleArg([null, 3, {}], Catalog.providers), "")
        compare(UsageHistory.sampleArg([ok("claude", null)], Catalog.providers), "")
        compare(UsageHistory.sampleArg([ok("claude", [null, {kind: "weekly"}])], Catalog.providers), "")
    }

    function test_sampleFirstDuplicateWins() {
        var results = [ok("claude", [{kind: "weekly", used_percent: 1}, {kind: "weekly", used_percent: 2}]),
                       ok("claude", [{kind: "weekly", used_percent: 3}])]
        compare(UsageHistory.sampleArg(results, Catalog.providers), "claude.weekly=1")
    }

    function test_commands() {
        compare(UsageHistory.historyCommand("read", 7), "env HEARTHWIRE_RUN=7 python3 -P -m hearthwire --usage-history read")
        compare(UsageHistory.historyCommand("clear", 0), "env HEARTHWIRE_RUN=0 python3 -P -m hearthwire --usage-history clear")
        compare(UsageHistory.historyCommand("record", 7, "claude.weekly=4,codex.session=100"),
                "env HEARTHWIRE_RUN=7 python3 -P -m hearthwire --usage-history record --sample claude.weekly=4,codex.session=100")
    }

    function test_commandsRefuseAnythingOdd() {
        compare(UsageHistory.historyCommand("purge", 7), "")
        compare(UsageHistory.historyCommand("read; rm", 7), "")
        compare(UsageHistory.historyCommand("read", -1), "")
        compare(UsageHistory.historyCommand("read", 1.5), "")
        compare(UsageHistory.historyCommand("read", "7"), "")
        compare(UsageHistory.historyCommand("read", undefined), "")
        var odd = ["", undefined, 3, "claude.weekly=", "claude.weekly=101", "claude.weekly=04", "claude.weekly=-1",
                   "claude.weekly=4 --sample x", "claude.weekly=4;rm", "Claude.weekly=4", "claude.weekly=4,", ",claude.weekly=4",
                   "$(id).weekly=4", "claude.weekly=4\ncodex.weekly=5"]
        odd.forEach(function (sample) {
            compare(UsageHistory.historyCommand("record", 7, sample), "", String(sample))
        })
        var many = []
        for (var index = 0; index < 65; index++)
            many.push("claude.weekly=1")
        compare(UsageHistory.historyCommand("record", 7, many.join(",")), "", "at most 64 pairs")
    }

    function test_recordDue() {
        var gap = UsageHistory.RECORD_MIN_GAP_MS
        var t = 5000000000
        verify(UsageHistory.recordDue(0, t), "never recorded")
        verify(!UsageHistory.recordDue(t, t), "just recorded")
        verify(!UsageHistory.recordDue(t, t + gap - 1), "one ms short")
        verify(UsageHistory.recordDue(t, t + gap), "exactly the gap")
        verify(UsageHistory.recordDue(t, t - 1), "the clock went back")
        verify(!UsageHistory.recordDue(t, NaN))
        verify(!UsageHistory.recordDue(t, undefined))
        verify(UsageHistory.recordDue(NaN, t))
    }

    function test_goodReplies() {
        compare(parse(reply({})), {ok: true, now: now, series: {"claude.weekly": [[now - hour, 40], [now, 42]]}})
        compare(parse(reply({series: []})), {ok: true, now: now, series: {}})
        compare(UsageHistory.parseReply("clear", 0, "{\"ok\":true}\n", Catalog.providers), {ok: true})
        compare(UsageHistory.parseReply("record", 0, JSON.stringify(reply({series: []})), Catalog.providers).ok, true)
    }

    function test_replyErrors() {
        ["bad-sample", "symlink", "not-directory", "not-owned", "busy", "legacy-data", "os-error"].forEach(function (code) {
            compare(UsageHistory.parseReply("record", 0, JSON.stringify({ok: false, error: code}), Catalog.providers),
                    {ok: false, error: code})
        })
    }

    function test_replyErrorsNeverCarryTheirText() {
        var invalid = {ok: false, error: "invalid"}
        compare(UsageHistory.parseReply("read", 0, "{\"ok\":false,\"error\":\"/home/x secret\"}", Catalog.providers), invalid)
        compare(UsageHistory.parseReply("read", 0, "{\"ok\":false,\"error\":\"busy\",\"detail\":\"x\"}", Catalog.providers), invalid)
        compare(UsageHistory.parseReply("read", 0, "{\"ok\":false,\"error\":3}", Catalog.providers), invalid)
    }

    function test_rejectsBadEnvelope() {
        var invalid = {ok: false, error: "invalid"}
        compare(UsageHistory.parseReply("read", 1, JSON.stringify(reply({})), Catalog.providers), invalid, "exit code")
        compare(UsageHistory.parseReply("read", undefined, JSON.stringify(reply({})), Catalog.providers), invalid, "no exit code")
        compare(UsageHistory.parseReply("nope", 0, JSON.stringify(reply({})), Catalog.providers), invalid, "op")
        compare(UsageHistory.parseReply("read", 0, undefined, Catalog.providers), invalid, "no stdout")
        compare(UsageHistory.parseReply("read", 0, "", Catalog.providers), invalid, "empty")
        compare(UsageHistory.parseReply("read", 0, "{", Catalog.providers), invalid, "not JSON")
        compare(UsageHistory.parseReply("read", 0, "[]", Catalog.providers), invalid, "array")
        compare(UsageHistory.parseReply("read", 0, "null", Catalog.providers), invalid, "null")
        compare(UsageHistory.parseReply("read", 0, "{\"ok\":true}", Catalog.providers), invalid, "read needs its fields")
        compare(UsageHistory.parseReply("clear", 0, JSON.stringify(reply({})), Catalog.providers), invalid, "clear is bare")
        var huge = JSON.stringify(reply({})) + new Array(UsageHistory.MAX_REPLY_CHARS + 2).join(" ")
        compare(UsageHistory.parseReply("read", 0, huge, Catalog.providers), invalid, "oversized")
        rejected(reply({ok: 1}), "ok truthy")
        rejected(reply({extra: 1}), "unknown field")
        rejected(reply({history_version: 2}), "version")
        rejected(reply({bucket_seconds: 60}), "bucket")
        rejected(reply({now: "x"}), "now type")
        rejected(reply({now: -1}), "negative now")
        rejected(reply({now: 1.5}), "fractional now")
        rejected(reply({series: {}}), "series type")
    }

    function test_rejectsBadSeries() {
        rejected(reply({series: [null]}), "null entry")
        rejected(withSeries({provider_id: "claude", metric_id: "weekly"}), "no points")
        rejected(withSeries({provider_id: "claude", metric_id: "weekly", points: [[now, 1]], x: 1}), "unknown field")
        rejected(withSeries({provider_id: 3, metric_id: "weekly", points: [[now, 1]]}), "id type")
        rejected(withSeries({provider_id: "nobody", metric_id: "weekly", points: [[now, 1]]}), "not in the catalog")
        rejected(withSeries({provider_id: "claude", metric_id: "extra_usage", points: [[now, 1]]}), "money")
        rejected(withSeries({provider_id: "claude", metric_id: "<b>", points: [[now, 1]]}), "markup")
        var same = {provider_id: "claude", metric_id: "weekly", points: [[now, 1]]}
        rejected(reply({series: [same, same]}), "duplicate pair")
    }

    function test_rejectsBadPoints() {
        rejected(point([]), "empty")
        rejected(point("x"), "type")
        rejected(point([[now]]), "short")
        rejected(point([[now, 1, 2]]), "long")
        rejected(point([null]), "null")
        rejected(point([{t: now}]), "object")
        rejected(point([[now, 1.5]]), "fractional used")
        rejected(point([[now, -1]]), "negative used")
        rejected(point([[now, 101]]), "over 100")
        rejected(point([[now, "1"]]), "string used")
        rejected(point([[now - hour + 1, 1]]), "off the hour")
        rejected(point([[now + hour, 1]]), "future")
        rejected(point([[now - 169 * hour, 1]]), "older than seven days")
        rejected(point([[now, 1], [now - hour, 2]]), "not ascending")
        rejected(point([[now, 1], [now, 2]]), "repeated")
        var many = []
        for (var index = 169; index >= 0; index--)
            many.push([now - index * hour, 1])
        rejected(point(many), "more hours than seven days hold")
    }

    function test_clearNext() {
        compare(UsageHistory.clearNext({ok: true}, 1), "done")
        compare(UsageHistory.clearNext({ok: false, error: "busy"}, 1), "retry")
        compare(UsageHistory.clearNext({ok: false, error: "busy"}, UsageHistory.CLEAR_MAX_TRIES - 1), "retry")
        compare(UsageHistory.clearNext({ok: false, error: "busy"}, UsageHistory.CLEAR_MAX_TRIES), "failed", "bounded")
        compare(UsageHistory.clearNext({ok: false, error: "os-error"}, 1), "failed")
        compare(UsageHistory.clearNext({ok: false, error: "invalid"}, 1), "failed", "a malformed reply")
        compare(UsageHistory.clearNext(null, 1), "failed")
        compare(UsageHistory.CLEAR_MAX_TRIES, 3)
    }

    function test_acceptsTheOldestBucket() {
        verify(parse(point([[now - 168 * hour, 1]])).ok)
    }

    // --- Sparkline ----------------------------------------------------------

    function test_sparkEmptyAndUnusableBoxes() {
        var points = [[now, 10]]
        compare(UsageHistory.sparkSegments([], now, "used", 100, 20, 1), [])
        compare(UsageHistory.sparkSegments(undefined, now, "used", 100, 20, 1), [])
        compare(UsageHistory.sparkSegments(points, now, "used", 0, 20, 1), [], "no width yet")
        compare(UsageHistory.sparkSegments(points, now, "used", 2, 20, 1), [], "only the inset")
        compare(UsageHistory.sparkSegments(points, now, "used", 100, 0, 1), [], "no height")
        compare(UsageHistory.sparkSegments(points, now, "used", NaN, 20, 1), [])
        compare(UsageHistory.sparkSegments(points, 0, "used", 100, 20, 1), [], "no clock yet")
    }

    function test_sparkOnePointIsADot() {
        var segments = UsageHistory.sparkSegments([[now, 25]], now, "used", 102, 22, 1)
        compare(segments.length, 1)
        compare(segments[0].dot, true)
        compare(segments[0].x1, 101, "the current hour is on the right")
        compare(segments[0].y1, 16, "25% used from the bottom")
        compare(segments[0].used, 25)
    }

    function test_sparkJoinsNeighbourHours() {
        var segments = UsageHistory.sparkSegments([[now - hour, 0], [now, 100]], now, "used", 102, 22, 1)
        compare(segments.length, 1)
        compare(segments[0].dot, false)
        compare(segments[0].y1, 21)
        compare(segments[0].y2, 1)
        compare(segments[0].used, 100, "colored by its end")
    }

    function test_sparkFollowsLeftAndUsed() {
        var used = UsageHistory.sparkSegments([[now, 25]], now, "used", 102, 22, 1)
        var left = UsageHistory.sparkSegments([[now, 25]], now, "remaining", 102, 22, 1)
        compare(used[0].y1, 16)
        compare(left[0].y1, 6, "75% left from the bottom")
        compare(left[0].used, 25, "the color still comes from percent used")
    }

    function test_sparkGaps() {
        var segments = UsageHistory.sparkSegments(
            [[now - 5 * hour, 10], [now - 4 * hour, 20], [now - 2 * hour, 30], [now, 40]], now, "used", 102, 22, 1)
        compare(segments.map(function (segment) { return [segment.used, segment.dot] }),
                [[20, false], [30, true], [40, true]])
    }

    function test_sparkKeepsToTheWindow() {
        compare(UsageHistory.sparkSegments([[now - 169 * hour, 1]], now, "used", 102, 22, 1), [])
        compare(UsageHistory.sparkSegments([[now + hour, 1]], now, "used", 102, 22, 1), [])
        var oldest = UsageHistory.sparkSegments([[now - 168 * hour, 1]], now, "used", 102, 22, 1)
        compare(oldest[0].x1, 1, "the oldest hour is on the left")
    }

    function test_sparkSkipsOddPoints() {
        var segments = UsageHistory.sparkSegments([null, "x", [now, 200], [now - hour, 5]], now, "used", 102, 22, 1)
        compare(segments.length, 1)
        compare(segments[0].used, 5)
    }
}
