import QtQuick
import QtTest
import "../../plasmoid/contents/ui/ChatStorage.js" as ChatStorage

TestCase {
    name: "ChatStorage"

    function test_normalizeMode() {
        compare(ChatStorage.normalizeMode("encrypted"), "encrypted")
        compare(ChatStorage.normalizeMode("memory"), "memory")
        compare(ChatStorage.normalizeMode("folder"), "memory")
        compare(ChatStorage.normalizeMode("Encrypted"), "memory")
        compare(ChatStorage.normalizeMode(" encrypted"), "memory")
        compare(ChatStorage.normalizeMode(""), "memory")
        compare(ChatStorage.normalizeMode(undefined), "memory")
        compare(ChatStorage.normalizeMode(null), "memory")
        compare(ChatStorage.normalizeMode(true), "memory")
    }

    function test_validInt() {
        compare(ChatStorage.validInt(0), 0)
        compare(ChatStorage.validInt(42), 42)
        compare(ChatStorage.validInt(2147483648), 2147483648)
        compare(ChatStorage.validInt(2147483649), -1)
        compare(ChatStorage.validInt(-1), -1)
        compare(ChatStorage.validInt(1.5), -1)
        compare(ChatStorage.validInt("3"), -1)
        compare(ChatStorage.validInt(NaN), -1)
        compare(ChatStorage.validInt(Infinity), -1)
        compare(ChatStorage.validInt(null), -1)
    }

    function test_generations() {
        compare(ChatStorage.normalizeGeneration(7), 7)
        compare(ChatStorage.normalizeGeneration(-3), 0)
        compare(ChatStorage.normalizeGeneration("7"), 0)
        compare(ChatStorage.nextGeneration(0), 1)
        compare(ChatStorage.nextGeneration(41), 42)
        compare(ChatStorage.nextGeneration(2147483648), 0)
        compare(ChatStorage.nextGeneration(-1), 0)
    }

    function test_profileName() {
        compare(ChatStorage.profileName(12, 3), "applet-12-g3")
        compare(ChatStorage.profileName(12, -1), "")
        compare(ChatStorage.profileName("12", 0), "")
        compare(ChatStorage.profileName(1.5, 0), "")
    }

    function test_vaultCommands() {
        compare(ChatStorage.vaultCommand("status", 3, 12),
                "env HEARTHWIRE_RUN=3 HEARTHWIRE_APPLET=12 python3 -P -m hearthwire --vault status")
        var ops = ["status", "create", "unlock", "lock", "change-passphrase", "destroy"]
        for (var index = 0; index < ops.length; index++)
            compare(ChatStorage.vaultCommand(ops[index], 1, 0),
                    "env HEARTHWIRE_RUN=1 HEARTHWIRE_APPLET=0 python3 -P -m hearthwire --vault " + ops[index])
    }

    function test_vaultCommandRejectsAnythingElse() {
        compare(ChatStorage.vaultCommand("purge", 1, 1), "")
        compare(ChatStorage.vaultCommand("status; rm -rf ~", 1, 1), "")
        compare(ChatStorage.vaultCommand("STATUS", 1, 1), "")
        compare(ChatStorage.vaultCommand("", 1, 1), "")
        compare(ChatStorage.vaultCommand(undefined, 1, 1), "")
        compare(ChatStorage.vaultCommand("leave-destroy", 1, 1), "")
        compare(ChatStorage.vaultCommand("status", -1, 1), "")
        compare(ChatStorage.vaultCommand("status", "1", 1), "")
        compare(ChatStorage.vaultCommand("status", 1.5, 1), "")
        // The applet word is an integer too.
        compare(ChatStorage.vaultCommand("status", 1), "")
        compare(ChatStorage.vaultCommand("status", 1, "1"), "")
        compare(ChatStorage.vaultCommand("status", 1, -1), "")
        compare(ChatStorage.vaultCommand("status", 1, "1 rm"), "")
    }

    function test_runNumbers() {
        compare(ChatStorage.firstRun(0, 0), 0)
        compare(ChatStorage.firstRun(1730000000123, 0), 1730000000123 % 2147483648)
        compare(ChatStorage.firstRun(5, 0.5), 5 + 1073741824)
        var samples = [[1730000000123, 0.999999], [-7, 0.25], [NaN, 0.5], [undefined, 2], [Infinity, -1]]
        for (var index = 0; index < samples.length; index++) {
            var run = ChatStorage.firstRun(samples[index][0], samples[index][1])
            verify(ChatStorage.validInt(run) === run, "run " + run)
            verify(run < 2147483648, "run " + run)
        }
        compare(ChatStorage.nextRun(7), 8)
        compare(ChatStorage.nextRun(2147483648), 0)
        compare(ChatStorage.nextRun(-1), 0)
        // Two widgets or a widget and its settings page started together.
        verify(ChatStorage.vaultCommand("status", 1, 5) !== ChatStorage.vaultCommand("status", 1, 6))
    }

    function test_webDataCommands() {
        compare(ChatStorage.webDataCommand("prepare", "encrypted", 5, 2, null, 9),
                "env HEARTHWIRE_RUN=9 HEARTHWIRE_APPLET=5 python3 -P -m hearthwire --web-data prepare --store encrypted --applet 5 --generation 2")
        compare(ChatStorage.webDataCommand("remove", "encrypted", 5, null, 2, 9),
                "env HEARTHWIRE_RUN=9 HEARTHWIRE_APPLET=5 python3 -P -m hearthwire --web-data remove --store encrypted --applet 5 --keep 2")
        compare(ChatStorage.webDataCommand("remove", "encrypted", 5, null, null, 9),
                "env HEARTHWIRE_RUN=9 HEARTHWIRE_APPLET=5 python3 -P -m hearthwire --web-data remove --store encrypted --applet 5")
        compare(ChatStorage.webDataCommand("remove", "encrypted", 5, null, undefined, 9),
                "env HEARTHWIRE_RUN=9 HEARTHWIRE_APPLET=5 python3 -P -m hearthwire --web-data remove --store encrypted --applet 5")
    }

    function test_webDataCommandRejectsAnythingElse() {
        // No plaintext store and no purge, ever.
        compare(ChatStorage.webDataCommand("prepare", "folder", 5, 2, null, 1), "")
        compare(ChatStorage.webDataCommand("purge", "encrypted", 5, 2, null, 1), "")
        compare(ChatStorage.webDataCommand("prepare", "encrypted", "5", 2, null, 1), "")
        compare(ChatStorage.webDataCommand("prepare", "encrypted", 5, "2", null, 1), "")
        compare(ChatStorage.webDataCommand("prepare", "encrypted", 5, -1, null, 1), "")
        compare(ChatStorage.webDataCommand("prepare", "encrypted", 5, null, null, 1), "")
        compare(ChatStorage.webDataCommand("prepare", "encrypted", -5, 2, null, 1), "")
        compare(ChatStorage.webDataCommand("prepare", "encrypted", 2147483649, 2, null, 1), "")
        compare(ChatStorage.webDataCommand("remove", "encrypted", 5, null, -2, 1), "")
        compare(ChatStorage.webDataCommand("remove", "encrypted", 5, null, "2 --x", 1), "")
        compare(ChatStorage.webDataCommand("prepare", "encrypted", 5, 2, null, -1), "")
    }

    function test_parseReplyOk() {
        compare(ChatStorage.parseReply("{\"ok\":true}"), {ok: true})
        // An older reply without "wallet" never offers the wallet.
        compare(ChatStorage.parseReply("{\"ok\":true,\"state\":\"locked\"}"),
                {ok: true, state: "locked", wallet: "unavailable", missing: []})
        compare(ChatStorage.parseReply("{\"ok\":true,\"state\":\"unlocked\",\"wallet\":\"set-up\"}\n"),
                {ok: true, state: "unlocked", wallet: "set-up", missing: []})
        compare(ChatStorage.parseReply("{\"ok\":true,\"state\":\"absent\"}"), {ok: true, state: "absent"})
    }

    function test_parseReplyUnavailableKeepsKnownTools() {
        compare(ChatStorage.parseReply(
            "{\"ok\":true,\"state\":\"unavailable\",\"missing\":[\"kdialog\",\"/usr/bin/x\",\"gocryptfs\"]}"),
            {ok: true, state: "unavailable", missing: ["gocryptfs", "kdialog"]})
        compare(ChatStorage.parseReply("{\"ok\":true,\"state\":\"unavailable\",\"missing\":\"gocryptfs\"}"),
                {ok: true, state: "unavailable", missing: ["gocryptfs"]})
        compare(ChatStorage.parseReply("{\"ok\":true,\"state\":\"unavailable\"}"),
                {ok: true, state: "unavailable", missing: ["gocryptfs"]})
    }

    function test_parseReplyErrors() {
        compare(ChatStorage.parseReply("{\"ok\":false,\"error\":\"wrong-passphrase\"}"),
                {ok: false, error: "wrong-passphrase"})
        compare(ChatStorage.parseReply("{\"ok\":false,\"error\":\"busy\"}"), {ok: false, error: "busy"})
        // Unknown or odd codes never reach the UI as they are.
        compare(ChatStorage.parseReply("{\"ok\":false,\"error\":\"/home/me/secret\"}"),
                {ok: false, error: "failed"})
        compare(ChatStorage.parseReply("{\"ok\":false,\"error\":7}"), {ok: false, error: "failed"})
        compare(ChatStorage.parseReply("{\"ok\":false}"), {ok: false, error: "failed"})
    }

    function test_parseReplyBad() {
        var bad = {ok: false, error: "bad-reply"}
        compare(ChatStorage.parseReply(""), bad)
        compare(ChatStorage.parseReply(undefined), bad)
        compare(ChatStorage.parseReply("Traceback (most recent call last)"), bad)
        compare(ChatStorage.parseReply("[]"), bad)
        compare(ChatStorage.parseReply("null"), bad)
        compare(ChatStorage.parseReply("{\"ok\":\"true\"}"), bad)
        compare(ChatStorage.parseReply("{\"ok\":true,\"state\":\"mounted\"}"), bad)
        compare(ChatStorage.replyFor(2, "{\"ok\":true}"), bad)
        compare(ChatStorage.replyFor(undefined, "{\"ok\":true}"), bad)
        compare(ChatStorage.replyFor(0, "{\"ok\":true}"), {ok: true})
    }

    function test_localPath() {
        compare(ChatStorage.localPath("file:///run/user/1000"), "/run/user/1000")
        compare(ChatStorage.localPath("/run/user/1000/"), "/run/user/1000")
        compare(ChatStorage.localPath("file:///tmp/a%20b"), "/tmp/a b")
        compare(ChatStorage.localPath(""), "")
        compare(ChatStorage.localPath(undefined), "")
        compare(ChatStorage.localPath("/"), "")
        compare(ChatStorage.localPath("file:///"), "")
        compare(ChatStorage.localPath("run/user/1000"), "")
        compare(ChatStorage.localPath("file:///run/../etc"), "")
        compare(ChatStorage.localPath("/run/./user"), "")
        compare(ChatStorage.localPath("file:///run/%E0%A4%A"), "")
        compare(ChatStorage.localPath("/run/user\n/1000"), "")
        compare(ChatStorage.localPath("https://example.com/x"), "")
    }

    function test_profilePath() {
        compare(ChatStorage.profilePath("file:///run/user/1000", 7, 3),
                "/run/user/1000/hearthwire/vault/web/applet-7-g3")
        compare(ChatStorage.profilePath("", 7, 3), "")
        compare(ChatStorage.profilePath("file:///run/user/1000", -1, 3), "")
        compare(ChatStorage.profilePath("file:///run/user/1000", 7, "3"), "")
    }

    function test_installCommand() {
        compare(ChatStorage.installCommand(["gocryptfs"]), "sudo pacman -S --needed gocryptfs")
        compare(ChatStorage.installCommand(["gocryptfs-v2"]), "sudo pacman -S --needed gocryptfs")
        compare(ChatStorage.installCommand(["fusermount3", "gocryptfs", "kdialog", "gocryptfs-v2"]),
                "sudo pacman -S --needed gocryptfs kdialog fuse3")
        compare(ChatStorage.installCommand([]), "sudo pacman -S --needed gocryptfs")
        compare(ChatStorage.installCommand(["evil; rm"]), "sudo pacman -S --needed gocryptfs")
        compare(ChatStorage.installCommand(null), "sudo pacman -S --needed gocryptfs")
    }

    function test_messageFor() {
        compare(ChatStorage.messageFor("cancelled"), "")
        compare(ChatStorage.messageFor("empty-passphrase"), "")
        compare(ChatStorage.messageFor(""), "")
        compare(ChatStorage.messageFor("wrong-passphrase"), "wrong-passphrase")
        compare(ChatStorage.messageFor("busy"), "busy")
        compare(ChatStorage.messageFor("lock-busy"), "lock-busy")
        compare(ChatStorage.messageFor("init-failed"), "failed")
        compare(ChatStorage.messageFor("not-verified"), "mount-failed")
        compare(ChatStorage.messageFor("stale-mount"), "mount-failed")
        compare(ChatStorage.messageFor("os-error"), "failed")
        compare(ChatStorage.messageFor("bad-reply"), "failed")
        compare(ChatStorage.messageFor("something-new"), "failed")
    }

    function card(fields) {
        return ChatStorage.cardFor(Object.assign({
            mode: "encrypted", state: "", op: "", error: "", hold: false,
            privateSession: false, ready: false
        }, fields))
    }

    function test_cardMemoryModeAlwaysWeb() {
        compare(card({mode: "memory"}).view, "web")
        compare(card({mode: "folder", state: "locked"}).view, "web")
        compare(card({mode: undefined}).view, "web")
        compare(ChatStorage.cardFor(null).view, "web")
    }

    function test_cardEncrypted() {
        compare(card({}), {view: "busy", message: "status"})
        compare(card({op: "unlock", state: "locked"}), {view: "busy", message: "unlock"})
        compare(card({state: "absent"}), {view: "create", message: ""})
        compare(card({state: "locked"}), {view: "unlock", message: ""})
        compare(card({state: "locked", error: "wrong-passphrase"}),
                {view: "unlock", message: "wrong-passphrase"})
        compare(card({state: "locked", error: "cancelled"}), {view: "unlock", message: ""})
        compare(card({state: "unavailable"}).view, "install")
        compare(card({state: "unlocked"}), {view: "retry", message: "prepare-failed"})
        compare(card({state: "unlocked", hold: true, error: "lock-busy"}),
                {view: "held", message: "lock-busy"})
        compare(card({state: "error"}), {view: "retry", message: "failed"})
        compare(card({state: "error", error: "no-runtime-dir"}), {view: "retry", message: "failed"})
    }

    function test_cardReadyOrPrivateShowsWeb() {
        compare(card({state: "unlocked", ready: true}).view, "web")
        compare(card({state: "unlocked", ready: true, op: "status"}).view, "web")
        compare(card({state: "locked", privateSession: true}).view, "web")
        compare(card({state: "unavailable", privateSession: true}).view, "web")
        // Only literal true counts.
        compare(card({state: "locked", privateSession: "yes"}).view, "unlock")
        compare(card({state: "locked", ready: 1}).view, "unlock")
    }

    // --- Step queue ---------------------------------------------------------

    readonly property var leaveSteps:
        ["leave-wait", "leave-remove", "leave-lock", "leave-status", "leave-destroy"]

    // Runs `queue` through nextStep like main.qml does, with `context` fixed;
    // returns the steps that would run.
    function drain(queue, context) {
        var ran = []
        var rest = queue
        while (true) {
            var next = ChatStorage.nextStep(rest, context)
            rest = next.queue
            if (next.step === "")
                break
            ran.push(next.step)
        }
        compare(rest, [])
        return ran
    }

    function test_enqueueDedupsStatus() {
        compare(ChatStorage.enqueueSteps([], ["status"], ""), ["status"])
        compare(ChatStorage.enqueueSteps(["status"], ["status"], ""), ["status"])
        compare(ChatStorage.enqueueSteps([], ["status"], "status"), [])
        // A fresh status is queued even while an earlier one runs.
        compare(ChatStorage.enqueueSteps([], ["status"], "status", true), ["status"])
        compare(ChatStorage.enqueueSteps(["status"], ["status"], "status", true), ["status"])
        // A leave status never hides a real one (and the other way round).
        compare(ChatStorage.enqueueSteps(["leave-status"], ["status"], ""), ["leave-status", "status"])
        compare(ChatStorage.enqueueSteps([], ["status"], "leave-status"), ["status"])
        compare(ChatStorage.enqueueSteps(["status"], ["leave-status"], ""), ["status", "leave-status"])
        // Leave steps aren't queued twice; other steps are kept in order.
        compare(ChatStorage.enqueueSteps(leaveSteps, leaveSteps, ""), leaveSteps)
        compare(ChatStorage.enqueueSteps(["keep"], ["wait", "lock"], ""), ["keep", "wait", "lock"])
        // Odd input is ignored, never thrown.
        compare(ChatStorage.enqueueSteps(null, ["status", "", 3, null], ""), ["status"])
        compare(ChatStorage.enqueueSteps(["lock"], undefined, ""), ["lock"])
        // The input queue is not changed.
        var queue = ["lock"]
        ChatStorage.enqueueSteps(queue, ["status"], "")
        compare(queue, ["lock"])
    }

    function test_leaveStepsRunOnlyWhileOff() {
        var off = {mode: "memory", state: "locked", wantsSaved: false}
        compare(drain(leaveSteps, off), leaveSteps)
        var on = {mode: "encrypted", state: "locked", wantsSaved: false}
        compare(drain(leaveSteps, on), [])
        compare(drain(["leave-remove", "status", "leave-destroy"], on), ["status"])
    }

    function test_leaveDestroySkipsAbsentOrUnavailableFolders() {
        compare(drain(["leave-destroy"], {mode: "memory", state: "absent"}), [])
        compare(drain(["leave-destroy"], {mode: "memory", state: "unavailable"}), [])
        compare(drain(["leave-destroy"], {mode: "memory", state: "error"}), ["leave-destroy"])
        compare(drain(["leave-destroy"], {mode: "memory", state: "unlocked"}), ["leave-destroy"])
    }

    function test_encryptedOnlyStepsDropWhileOff() {
        var off = {mode: "memory", state: "locked", wantsSaved: true}
        compare(drain(["create", "unlock", "prepare", "keep", "status", "lock", "remove", "wait"], off),
                ["status", "lock", "remove", "wait"])
        compare(ChatStorage.queueForMode(["unlock", "status", "keep", "lock"], "memory"), ["status", "lock"])
        compare(ChatStorage.queueForMode(["leave-wait", "status", "leave-destroy", "lock"], "encrypted"),
                ["status", "lock"])
        compare(ChatStorage.queueForMode(null, "encrypted"), [])
    }

    function test_prepareOnlyWhenSavedIsWanted() {
        compare(drain(["prepare"], {mode: "encrypted", state: "unlocked", wantsSaved: false}), [])
        compare(drain(["prepare"], {mode: "encrypted", state: "unlocked", wantsSaved: "yes"}), [])
        compare(drain(["prepare"], {mode: "encrypted", state: "unlocked", wantsSaved: true}), ["prepare"])
    }

    function test_nextStepOneAtATime() {
        var context = {mode: "memory", state: "locked"}
        var next = ChatStorage.nextStep(leaveSteps, context)
        compare(next, {step: "leave-wait", queue: leaveSteps.slice(1)})
        compare(ChatStorage.nextStep([], context), {step: "", queue: []})
        compare(ChatStorage.nextStep(undefined, context), {step: "", queue: []})
    }

    // Encrypted → Off: the leave steps are queued; turning it back on before
    // they run keeps the folder and asks for a fresh status.
    function test_scenarioEncryptedOffEncryptedQuickly() {
        var queue = ChatStorage.queueForMode([], "memory")
        queue = ChatStorage.enqueueSteps(queue, leaveSteps, "")
        // leave-wait starts.
        var next = ChatStorage.nextStep(queue, {mode: "memory", state: "unlocked"})
        compare(next.step, "leave-wait")
        var running = next.step
        queue = next.queue
        // Back to Encrypted while it waits.
        queue = ChatStorage.queueForMode(queue, "encrypted")
        queue = ChatStorage.enqueueSteps(queue, ["status"], running, true)
        compare(queue, ["status"])
        compare(drain(queue, {mode: "encrypted", state: ""}), ["status"])
    }

    // Same, but the steps were queued and not trimmed: they are still dropped
    // when they come up.
    function test_scenarioLeaveStepsDroppedAtRunTime() {
        var queue = ChatStorage.enqueueSteps(leaveSteps, ["status"], "leave-wait", true)
        compare(drain(queue, {mode: "encrypted", state: "unlocked"}), ["status"])
    }

    // Off → Encrypted quickly (a widget that was never on): only a status runs.
    function test_scenarioOffToEncryptedQuickly() {
        var queue = ChatStorage.queueForMode(["status"], "encrypted")
        queue = ChatStorage.enqueueSteps(queue, ["status"], "status", true)
        compare(queue, ["status"])
        compare(drain(queue, {mode: "encrypted", state: ""}), ["status"])
    }

    // Encrypted → Off → Encrypted → Off: one set of leave steps runs.
    function test_scenarioTogglingTwiceRunsLeaveStepsOnce() {
        var queue = ChatStorage.enqueueSteps([], leaveSteps, "")
        queue = ChatStorage.queueForMode(queue, "encrypted")
        queue = ChatStorage.enqueueSteps(queue, ["status"], "", true)
        queue = ChatStorage.queueForMode(queue, "memory")
        queue = ChatStorage.enqueueSteps(queue, leaveSteps, "")
        compare(queue, ["status"].concat(leaveSteps))
    }

    // Leave destroy then a status: the folder is known to be gone, so a later
    // switch back to Encrypted offers Create, never Unlock.
    function test_scenarioDestroyThenStatus() {
        compare(ChatStorage.afterDestroy({ok: true}), {state: "absent", steps: []})
        compare(ChatStorage.afterDestroy({ok: false, error: "busy"}), {state: "", steps: ["status"]})
        compare(ChatStorage.afterDestroy({ok: false, error: "not-locked"}), {state: "", steps: ["status"]})
        compare(ChatStorage.afterDestroy(null), {state: "", steps: ["status"]})
        compare(ChatStorage.afterDestroy({ok: "true"}), {state: "", steps: ["status"]})
        compare(card({state: ChatStorage.afterDestroy({ok: true}).state}).view, "create")
        // A failed destroy queues a status behind whatever else is waiting.
        var queue = ChatStorage.enqueueSteps(["leave-status"],
                                             ChatStorage.afterDestroy({ok: false}).steps, "leave-destroy")
        compare(queue, ["leave-status", "status"])
    }

    function test_stepOperation() {
        compare(ChatStorage.stepOperation("leave-wait"), "wait")
        compare(ChatStorage.stepOperation("leave-remove"), "remove")
        compare(ChatStorage.stepOperation("leave-lock"), "lock")
        compare(ChatStorage.stepOperation("leave-status"), "status")
        compare(ChatStorage.stepOperation("leave-destroy"), "destroy")
        compare(ChatStorage.stepOperation("unlock"), "unlock")
        compare(ChatStorage.stepOperation(undefined), "")
        // Leave operations show the same busy card as the plain ones.
        compare(card({op: ChatStorage.stepOperation("leave-lock")}), {view: "busy", message: "lock"})
    }

    // A code or state the plasmoid doesn't know fails closed: the Try again
    // card, never the saved profile.
    function test_unknownHelperCodesFailClosed() {
        var unknownError = ChatStorage.parseReply("{\"ok\":false,\"error\":\"corrupted\"}")
        compare(unknownError, {ok: false, error: "failed"})
        compare(card({state: "error", error: unknownError.error}), {view: "retry", message: "failed"})
        var unknownState = ChatStorage.parseReply("{\"ok\":true,\"state\":\"corrupted\"}")
        compare(unknownState, {ok: false, error: "bad-reply"})
        compare(card({state: "error", error: unknownState.error}), {view: "retry", message: "failed"})
        compare(card({state: "corrupted"}), {view: "retry", message: "failed"})
    }

    // Cipher folder with files but no gocryptfs.conf.
    function test_damagedFolder() {
        compare(ChatStorage.parseReply("{\"ok\":true,\"state\":\"damaged\"}"), {ok: true, state: "damaged"})
        compare(ChatStorage.parseReply("{\"ok\":false,\"error\":\"damaged\"}"), {ok: false, error: "damaged"})
        compare(ChatStorage.messageFor("damaged"), "damaged")
        compare(card({state: "damaged"}), {view: "damaged", message: ""})
        compare(card({state: "damaged", error: "damaged"}), {view: "damaged", message: ""})
        compare(card({state: "damaged", error: "busy"}), {view: "damaged", message: "busy"})
        compare(card({state: "damaged", error: "bad-reply"}), {view: "damaged", message: "failed"})
        compare(card({state: "damaged", op: "destroy"}), {view: "busy", message: "destroy"})
        compare(card({state: "damaged", privateSession: true}).view, "web")
        compare(card({mode: "memory", state: "damaged"}).view, "web")
        // Never the saved profile, even if something claimed ready.
        compare(card({state: "absent", error: "damaged"}), {view: "create", message: "damaged"})
    }

    // The Chat tab's destroy step only runs on a damaged folder, in either mode.
    function test_destroyStepOnlyForDamagedFolders() {
        compare(drain(["destroy"], {mode: "encrypted", state: "damaged"}), ["destroy"])
        compare(drain(["destroy"], {mode: "memory", state: "damaged"}), ["destroy"])
        var others = ["", "absent", "locked", "unlocked", "unavailable", "error", undefined]
        for (var index = 0; index < others.length; index++)
            compare(drain(["destroy"], {mode: "encrypted", state: others[index]}), [])
        compare(drain(["destroy", "status"], {mode: "encrypted", state: "locked"}), ["status"])
    }

    // Delete the damaged folder → status → Create.
    function test_scenarioDeleteDamagedThenCreate() {
        var queue = ChatStorage.enqueueSteps([], ["destroy"], "")
        var next = ChatStorage.nextStep(queue, {mode: "encrypted", state: "damaged"})
        compare(next.step, "destroy")
        var after = ChatStorage.afterDestroy({ok: true})
        compare(after.state, "absent")
        queue = ChatStorage.enqueueSteps(next.queue, ["status"], "")
        compare(drain(queue, {mode: "encrypted", state: after.state}), ["status"])
        compare(card({state: "absent"}).view, "create")
        // A failed delete re-checks and stays on the damaged card.
        compare(ChatStorage.afterDestroy({ok: false, error: "busy"}).state, "")
        compare(card({state: "damaged", error: "busy"}).view, "damaged")
    }

    function test_normalizeAutoLock() {
        var allowed = [0, 1, 5, 15, 30, 60, 480, 1440]
        compare(ChatStorage.AUTO_LOCK_MINUTES, allowed)
        for (var index = 0; index < allowed.length; index++)
            compare(ChatStorage.normalizeAutoLock(allowed[index]), allowed[index])
        // Anything else is "never": harmless, the folder just isn't locked by itself.
        var odd = [2, 10, 59, 61, 1441, -1, 1.5, "5", NaN, Infinity, null, undefined, true, {}, [5]]
        for (index = 0; index < odd.length; index++)
            compare(ChatStorage.normalizeAutoLock(odd[index]), 0, String(odd[index]))
    }

    function test_autoLockIntervals() {
        compare(ChatStorage.autoLockInterval(0), 0)
        compare(ChatStorage.autoLockInterval(1), 60000)
        compare(ChatStorage.autoLockInterval(60), 3600000)
        compare(ChatStorage.autoLockInterval(1440), 86400000)
        compare(ChatStorage.autoLockInterval(7), 0)
        compare(ChatStorage.autoLockCheckInterval(0), 0)
        compare(ChatStorage.autoLockCheckInterval(1), 15000)
        compare(ChatStorage.autoLockCheckInterval(5), 30000)
        compare(ChatStorage.autoLockCheckInterval(1440), 30000)
        compare(ChatStorage.autoLockCheckInterval("x"), 0)
    }

    function test_autoLockStep() {
        var minute = 60000
        function step(extra) {
            return ChatStorage.autoLockStep(Object.assign(
                {armed: true, minutes: 5, idleSince: 1000, now: 1000 + 5 * minute, busy: false}, extra))
        }
        compare(step({}), "lock")
        compare(step({now: 1000 + 5 * minute - 1}), "")
        compare(step({now: 1000 + 8 * 60 * minute}), "lock")
        compare(step({busy: true}), "wait")
        // Never while Chat is shown, never for "Never", never without a start time.
        compare(step({armed: false}), "")
        compare(step({armed: 1}), "")
        compare(step({minutes: 0}), "")
        compare(step({minutes: 7}), "")
        compare(step({idleSince: 0}), "")
        compare(step({idleSince: "1000"}), "")
        compare(step({now: NaN}), "")
        compare(step({now: undefined}), "")
        // The clock went back: start counting again.
        compare(step({now: 999}), "restart")
        compare(ChatStorage.autoLockStep(undefined), "")
    }

    function test_autoLockedMessage() {
        compare(ChatStorage.messageFor("auto-locked"), "auto-locked")
        compare(card({state: "locked", error: "auto-locked", hold: true}),
                {view: "unlock", message: "auto-locked"})
    }

    // --- R3: KDE Wallet unlock ---------------------------------------------------

    function test_unlockMethods() {
        compare(ChatStorage.UNLOCK_METHODS, ["passphrase", "wallet"])
        compare(ChatStorage.normalizeUnlockMethod("wallet"), "wallet")
        var others = ["passphrase", "fido2", "Wallet", "", null, undefined, 1, "wallet "]
        for (var index = 0; index < others.length; index++)
            compare(ChatStorage.normalizeUnlockMethod(others[index]), "passphrase", String(others[index]))
        compare(ChatStorage.effectiveUnlockMethod("wallet", "set-up"), "wallet")
        compare(ChatStorage.effectiveUnlockMethod("wallet", "off"), "passphrase")
        compare(ChatStorage.effectiveUnlockMethod("wallet", "unavailable"), "passphrase")
        compare(ChatStorage.effectiveUnlockMethod("wallet", ""), "passphrase")
        compare(ChatStorage.effectiveUnlockMethod("passphrase", "set-up"), "passphrase")
    }

    function test_walletVaultCommands() {
        var prefix = "env HEARTHWIRE_RUN=3 HEARTHWIRE_APPLET=5 python3 -P -m hearthwire --vault "
        compare(ChatStorage.vaultCommand("unlock", 3, 5), prefix + "unlock")
        compare(ChatStorage.vaultCommand("unlock", 3, 5, "passphrase"), prefix + "unlock")
        compare(ChatStorage.vaultCommand("unlock", 3, 5, "wallet"), prefix + "unlock --method wallet")
        compare(ChatStorage.vaultCommand("add-key", 3, 5, "wallet"), prefix + "add-key --method wallet")
        compare(ChatStorage.vaultCommand("remove-key", 3, 5, "wallet"), prefix + "remove-key --method wallet")
        compare(ChatStorage.vaultCommand("auto-unlock", 3, 5), prefix + "auto-unlock")
        // add-key and remove-key need wallet; nothing else takes a method.
        compare(ChatStorage.vaultCommand("add-key", 3, 5), "")
        compare(ChatStorage.vaultCommand("add-key", 3, 5, "passphrase"), "")
        compare(ChatStorage.vaultCommand("remove-key", 3, 5, "fido2"), "")
        compare(ChatStorage.vaultCommand("unlock", 3, 5, "fido2"), "")
        compare(ChatStorage.vaultCommand("unlock", 3, 5, "wallet --x"), "")
        compare(ChatStorage.vaultCommand("status", 3, 5, "wallet"), "")
        compare(ChatStorage.vaultCommand("auto-unlock", 3, 5, "wallet"), "")
        compare(ChatStorage.vaultCommand("lock", 3, 5, "passphrase"), "")
    }

    function test_walletStatusReply() {
        compare(ChatStorage.parseReply(
            "{\"ok\":true,\"state\":\"locked\",\"wallet\":\"off\",\"missing\":[\"openssl\",\"x\",\"qdbus6\",\"kwallet-query\"]}"),
            {ok: true, state: "locked", wallet: "off", missing: ["kwallet-query", "qdbus6", "openssl"]})
        compare(ChatStorage.parseReply("{\"ok\":true,\"state\":\"locked\",\"wallet\":\"maybe\"}").wallet,
                "unavailable")
        // Only locked/unlocked carry the wallet.
        compare(ChatStorage.parseReply("{\"ok\":true,\"state\":\"absent\",\"wallet\":\"set-up\"}"),
                {ok: true, state: "absent"})
        compare(ChatStorage.installCommand(["kwallet-query", "qdbus6", "openssl"]),
                "sudo pacman -S --needed kwallet qt6-tools openssl")
        compare(ChatStorage.installCommand(["qdbus6"]), "sudo pacman -S --needed qt6-tools")
    }

    function test_walletErrors() {
        var codes = ["not-set-up", "wallet-disabled", "wallet-failed", "wallet-mismatch", "wallet-write-failed"]
        for (var index = 0; index < codes.length; index++) {
            compare(ChatStorage.parseReply("{\"ok\":false,\"error\":\"" + codes[index] + "\"}"),
                    {ok: false, error: codes[index]})
            compare(ChatStorage.messageFor(codes[index]), codes[index])
        }
        // A closed wallet at Plasma start says nothing; the card offers Unlock.
        compare(ChatStorage.parseReply("{\"ok\":false,\"error\":\"wallet-closed\"}").error, "wallet-closed")
        compare(ChatStorage.messageFor("wallet-closed"), "")
        compare(card({state: "locked", error: "wallet-mismatch"}), {view: "unlock", message: "wallet-mismatch"})
        compare(ChatStorage.parseReply("{\"ok\":false,\"error\":\"wallet-other\"}").error, "failed")
    }

    function test_autoUnlockOnlyForALockedFolderWithAWalletSlot() {
        var base = {mode: "encrypted", state: "locked", wallet: "set-up", hold: false}
        verify(!ChatStorage.dropStep("auto-unlock", base))
        verify(ChatStorage.dropStep("auto-unlock", Object.assign({}, base, {state: "unlocked"})))
        verify(ChatStorage.dropStep("auto-unlock", Object.assign({}, base, {state: ""})))
        verify(ChatStorage.dropStep("auto-unlock", Object.assign({}, base, {wallet: "off"})))
        verify(ChatStorage.dropStep("auto-unlock", Object.assign({}, base, {wallet: "unavailable"})))
        verify(ChatStorage.dropStep("auto-unlock", Object.assign({}, base, {hold: true})))
        verify(ChatStorage.dropStep("auto-unlock", Object.assign({}, base, {mode: "memory"})))
        // Status first, then the unlock only when it says so.
        var next = ChatStorage.nextStep(["status", "auto-unlock"], {mode: "encrypted", state: ""})
        compare(next.step, "status")
        compare(ChatStorage.nextStep(next.queue, {mode: "encrypted", state: "locked", wallet: "off"}).step, "")
        compare(ChatStorage.nextStep(next.queue, base).step, "auto-unlock")
        // Wallet steps go when Stay signed in is turned off.
        compare(ChatStorage.queueForMode(["unlock-wallet", "auto-unlock", "add-key", "status"], "memory"),
                ["status"])
    }

    function test_walletStepOperations() {
        compare(ChatStorage.stepOperation("unlock-wallet"), "unlock")
        compare(ChatStorage.stepMethod("unlock-wallet"), "wallet")
        compare(ChatStorage.stepOperation("auto-unlock"), "auto-unlock")
        compare(ChatStorage.stepMethod("auto-unlock"), "")
        compare(ChatStorage.stepOperation("add-key"), "add-key")
        compare(ChatStorage.stepMethod("add-key"), "wallet")
        compare(ChatStorage.stepMethod("unlock"), "")
        compare(ChatStorage.vaultCommand(ChatStorage.stepOperation("unlock-wallet"), 1, 1,
                ChatStorage.stepMethod("unlock-wallet")),
                "env HEARTHWIRE_RUN=1 HEARTHWIRE_APPLET=1 python3 -P -m hearthwire --vault unlock --method wallet")
    }

    // M1: Unlock with shows the real slot, and a slot not applied.
    function test_walletChoice() {
        compare(ChatStorage.walletChoice("wallet", "set-up"), { shown: "wallet", notApplied: false })
        compare(ChatStorage.walletChoice("passphrase", "set-up"), { shown: "wallet", notApplied: true })
        compare(ChatStorage.walletChoice("odd", "set-up"), { shown: "wallet", notApplied: true })
        compare(ChatStorage.walletChoice("wallet", "off"), { shown: "passphrase", notApplied: false })
        compare(ChatStorage.walletChoice("passphrase", "off"), { shown: "passphrase", notApplied: false })
        compare(ChatStorage.walletChoice("wallet", "unavailable"), { shown: "passphrase", notApplied: false })
        compare(ChatStorage.walletChoice("wallet", ""), { shown: "passphrase", notApplied: false })
    }
}
