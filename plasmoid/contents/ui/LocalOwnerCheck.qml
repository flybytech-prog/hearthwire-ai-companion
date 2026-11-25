import QtQuick
import org.kde.plasma.plasma5support as Plasma5Support
import "OllamaChat.js" as OllamaChat
import "ChatStorage.js" as ChatStorage

// Asks the helper who listens on a Local web UI port: the same check the
// Ollama chat runs, with the command from OllamaChat.ownerCommand. One check
// at a time; starting another drops the first. Fails closed: a bad command,
// an unreadable reply or a timeout end as "owner-unknown", and only a clear
// self/system answer ends with no problem.
Item {
    id: ownerCheck

    // Only makes the helper's source name unique. runOwnerCheck is a test
    // seam: overridden by tests only, never in the plasmoid.
    property double appletId: 0
    property var runOwnerCheck: function (command) { ownerSource.connectSource(command) }
    property int timeout: 15000

    property string sourceName: ""
    property int port: 0
    // The home-network address checked with the port, "" for this computer.
    property string address: ""
    // See ChatStorage.firstRun.
    property int run: ChatStorage.firstRun(Date.now(), Math.random())
    readonly property bool busy: ownerCheck.sourceName !== ""

    // problem: "" (self or system; with an address also remote: not this
    // computer), "not-running", "other" or "owner-unknown".
    signal finished(int port, string problem)

    // address (optional): a home-network site's host (OllamaChat.ownerCommand).
    function start(port, address) {
        ownerCheck.cancel()
        ownerCheck.run = ChatStorage.nextRun(ownerCheck.run)
        ownerCheck.port = port
        ownerCheck.address = typeof address === "string" ? address : ""
        var command = OllamaChat.ownerCommand(port, ownerCheck.run,
            Math.max(0, ChatStorage.validInt(ownerCheck.appletId)), ownerCheck.address)
        if (command === "") {
            ownerCheck.finished(port, "owner-unknown")
            return
        }
        ownerCheck.sourceName = command
        ownerTimer.interval = ownerCheck.timeout
        ownerTimer.restart()
        ownerCheck.runOwnerCheck(command)
    }

    function cancel() {
        ownerTimer.stop()
        if (ownerCheck.sourceName !== "")
            ownerSource.disconnectSource(ownerCheck.sourceName)
        ownerCheck.sourceName = ""
    }

    // The helper's reply, already parsed by OllamaChat.parseOwnerReply.
    function ownerDone(source, reply) {
        if (ownerCheck.sourceName === "" || source !== ownerCheck.sourceName)
            return
        ownerTimer.stop()
        ownerCheck.sourceName = ""
        // remote: the address isn't this computer's, so no listener here
        // can answer; only for a check that named one.
        if (ownerCheck.address !== "" && reply && reply.ok === true && reply.owner === "remote")
            ownerCheck.finished(ownerCheck.port, "")
        else
            ownerCheck.finished(ownerCheck.port, OllamaChat.ownerProblem(reply))
    }

    Plasma5Support.DataSource {
        id: ownerSource
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            ownerSource.disconnectSource(source)
            // Only stdout's known words are used.
            ownerCheck.ownerDone(source, OllamaChat.parseOwnerReply(data["exit code"], data["stdout"],
                                                                    ownerCheck.address !== ""))
        }
    }

    Timer {
        id: ownerTimer
        repeat: false
        onTriggered: {
            ownerCheck.cancel()
            ownerCheck.finished(ownerCheck.port, "owner-unknown")
        }
    }
}
