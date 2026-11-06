import QtQuick
import QtTest
import "../../plasmoid/contents/ui/RefreshGate.js" as RefreshGate

TestCase {
    name: "RefreshGate"

    function test_idleStarts() {
        compare(RefreshGate.decide(false, 0, 1000), "start")
        compare(RefreshGate.decide(false, 1000, 1000), "start")
    }

    function test_inFlightQueues() {
        compare(RefreshGate.decide(true, 1000, 1000), "queue")
        compare(RefreshGate.decide(true, 1000, 61000), "queue")
        // A slow but legitimate worst-case run (~125 s) is never dropped.
        compare(RefreshGate.decide(true, 0, 125000), "queue")
        compare(RefreshGate.decide(true, 0, 150000), "queue")
    }

    function test_staleInFlightStarts() {
        compare(RefreshGate.decide(true, 1000, 1000 + 10 * RefreshGate.STALE_MS), "start")
    }

    function test_staleBoundary() {
        compare(RefreshGate.STALE_MS, 180000)
        compare(RefreshGate.decide(true, 0, RefreshGate.STALE_MS - 1), "queue")
        compare(RefreshGate.decide(true, 0, RefreshGate.STALE_MS), "start")
        compare(RefreshGate.decide(true, 0, 179999), "queue")
        compare(RefreshGate.decide(true, 0, 180000), "start")
    }

    function test_usageCommandFormat() {
        compare(RefreshGate.usageCommand(3, ["claude", "codex"]),
                "env HEARTHWIRE_RUN=3 python3 -P -m hearthwire --json --providers=claude,codex")
        compare(RefreshGate.usageCommand(1, []),
                "env HEARTHWIRE_RUN=1 python3 -P -m hearthwire --json --providers=")
    }

    function test_usageCommandUniquePerRun() {
        var ids = ["claude"]
        verify(RefreshGate.usageCommand(1, ids) !== RefreshGate.usageCommand(2, ids))
    }

    function test_usageCommandSanitizesRunId() {
        compare(RefreshGate.usageCommand("1; rm -rf ~", ["grok"]),
                "env HEARTHWIRE_RUN=0 python3 -P -m hearthwire --json --providers=grok")
        compare(RefreshGate.usageCommand(-4, ["grok"]),
                "env HEARTHWIRE_RUN=0 python3 -P -m hearthwire --json --providers=grok")
        compare(RefreshGate.usageCommand(2.7, null),
                "env HEARTHWIRE_RUN=2 python3 -P -m hearthwire --json --providers=")
    }
}
