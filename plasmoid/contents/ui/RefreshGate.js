.pragma library

// A helper run that has not reported back after this long is treated as dead,
// so a hung process can never block refreshes forever. A legitimate worst-case
// run (shell capture, lock waits, refresh POST and usage GET, repeated once on
// a 401) takes about 125 s, so this leaves headroom and never drops a live run
// between its refresh POST and save.
var STALE_MS = 180000

function decide(inFlight, startedAtMs, nowMs) {
    if (!inFlight)
        return "start"
    var started = Number(startedAtMs)
    var now = Number(nowMs)
    if (!isFinite(started) || !isFinite(now) || now - started >= STALE_MS)
        return "start"
    return "queue"
}

// Builds a usage command that is unique per run, so a late reply from an old
// run can be told apart from the current one. `env` works whether the engine
// execs the command directly or through /bin/sh, and the helper ignores the
// marker variable. providerIds must already be catalog ids.
function usageCommand(runId, providerIds) {
    var run = Math.max(0, Math.floor(Number(runId) || 0))
    var ids = Array.isArray(providerIds) ? providerIds : []
    return "env HEARTHWIRE_RUN=" + run
        + " python3 -P -m hearthwire --json --providers=" + ids.join(",")
}
