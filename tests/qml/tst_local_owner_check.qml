import QtQuick
import QtTest
import "../../plasmoid/contents/ui"

// LocalOwnerCheck with a fake helper (runOwnerCheck): the command it runs
// and how every answer ends. Nothing here starts a process.
TestCase {
    id: testCase
    name: "LocalOwnerCheck"
    when: windowShown

    property var commands: []
    property var results: []

    Component {
        id: checkComponent
        LocalOwnerCheck {
            appletId: 7
            runOwnerCheck: function (command) { testCase.commands.push(command) }
            onFinished: (port, problem) => testCase.results.push({ port: port, problem: problem })
        }
    }

    function init() {
        testCase.commands = []
        testCase.results = []
    }

    function make(properties) {
        var check = createTemporaryObject(checkComponent, testCase, properties || {})
        verify(check !== null)
        return check
    }

    function answer(check, reply) {
        check.ownerDone(check.sourceName, reply)
    }

    function test_runsTheSharedOwnerCommand() {
        var check = make()
        check.start(3000)
        compare(testCase.commands.length, 1)
        verify(/^env HEARTHWIRE_RUN=\d+ HEARTHWIRE_APPLET=7 python3 -P -m hearthwire --port-owner 3000$/
               .test(testCase.commands[0]), testCase.commands[0])
        verify(check.busy)
        compare(testCase.results, [])
    }

    function test_onlySelfOrSystemPass() {
        var cases = [
            [{ ok: true, owner: "self" }, ""],
            [{ ok: true, owner: "system" }, ""],
            [{ ok: true, owner: "other" }, "other"],
            [{ ok: true, owner: "none" }, "not-running"],
            [{ ok: false, error: "unreadable" }, "owner-unknown"],
            [{ ok: false, error: "bad-reply" }, "owner-unknown"],
            [null, "owner-unknown"]
        ]
        var check = make()
        for (var index = 0; index < cases.length; index++) {
            testCase.results = []
            check.start(8080)
            answer(check, cases[index][0])
            compare(testCase.results, [{ port: 8080, problem: cases[index][1] }], JSON.stringify(cases[index][0]))
            verify(!check.busy)
        }
    }

    // A new check gets a new source name and drops the old one: a late
    // answer of the first can't end the second.
    function test_lateAnswerOfAnOlderCheckIsIgnored() {
        var check = make()
        check.start(3000)
        var first = check.sourceName
        check.start(3001)
        verify(check.sourceName !== first)
        check.ownerDone(first, { ok: true, owner: "self" })
        compare(testCase.results, [])
        answer(check, { ok: true, owner: "other" })
        compare(testCase.results, [{ port: 3001, problem: "other" }])
        // Nothing more once done.
        check.ownerDone(first, { ok: true, owner: "self" })
        compare(testCase.results.length, 1)
    }

    function test_cancelDropsTheAnswer() {
        var check = make()
        check.start(3000)
        var source = check.sourceName
        check.cancel()
        verify(!check.busy)
        check.ownerDone(source, { ok: true, owner: "self" })
        compare(testCase.results, [])
    }

    function test_badPortFailsClosedWithoutRunning() {
        var check = make()
        var ports = [0, -1, 65536, 1.5]
        for (var index = 0; index < ports.length; index++)
            check.start(ports[index])
        compare(testCase.commands, [])
        compare(testCase.results.map(function (r) { return r.problem }),
                ["owner-unknown", "owner-unknown", "owner-unknown", "owner-unknown"])
    }

    function test_timeoutFailsClosed() {
        var check = make({ timeout: 30 })
        check.start(3000)
        tryVerify(function () { return testCase.results.length === 1 }, 2000)
        compare(testCase.results[0], { port: 3000, problem: "owner-unknown" })
        verify(!check.busy)
    }
}
