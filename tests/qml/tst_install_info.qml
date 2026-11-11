import QtQuick
import QtTest
import "../../plasmoid/contents/ui/InstallInfo.js" as InstallInfo

TestCase {
    name: "InstallInfo"

    function reply(changes) {
        var value = {ok: true, install_info_version: 1, helper: "system", system_helper: true,
                     user_helper: false, user_plasmoid: false, system_plasmoid: true, distro: "arch"}
        for (var key in changes) {
            if (changes[key] === undefined)
                delete value[key]
            else
                value[key] = changes[key]
        }
        return JSON.stringify(value)
    }

    function checkUnknown(info, what) {
        compare(info.known, false, what)
        compare(info.shadowed, false, what)
        compare(info.distro, "other", what)
        compare(info.helper, "", what)
        compare(info.user_helper, false, what)
        compare(info.system_helper, false, what)
        compare(info.user_plasmoid, false, what)
        compare(info.system_plasmoid, false, what)
    }

    function test_command() {
        compare(InstallInfo.command(5, 7),
                "env HEARTHWIRE_RUN=5 HEARTHWIRE_APPLET=7 python3 -P -s -m hearthwire --install-info")
        compare(InstallInfo.command(0, 0),
                "env HEARTHWIRE_RUN=0 HEARTHWIRE_APPLET=0 python3 -P -s -m hearthwire --install-info")
        compare(InstallInfo.command(-1, 7), "")
        compare(InstallInfo.command(5, -1), "")
        compare(InstallInfo.command("5", 7), "")
        compare(InstallInfo.command(5, "7; rm"), "")
        compare(InstallInfo.command(1.5, 7), "")
        compare(InstallInfo.command(2147483649, 7), "")
        // The one retry without -s; only the exact true picks it.
        compare(InstallInfo.command(5, 7, true),
                "env HEARTHWIRE_RUN=5 HEARTHWIRE_APPLET=7 python3 -P -m hearthwire --install-info")
        compare(InstallInfo.command(5, 7, false),
                "env HEARTHWIRE_RUN=5 HEARTHWIRE_APPLET=7 python3 -P -s -m hearthwire --install-info")
        compare(InstallInfo.command(5, 7, "true"),
                "env HEARTHWIRE_RUN=5 HEARTHWIRE_APPLET=7 python3 -P -s -m hearthwire --install-info")
        compare(InstallInfo.command(-1, 7, true), "")
        compare(InstallInfo.command(5, "7; rm", true), "")
    }

    // Only a failed first run is retried, and only once.
    function test_needsRetry() {
        compare(InstallInfo.needsRetry(1, false), true)
        compare(InstallInfo.needsRetry(2, false), true)
        compare(InstallInfo.needsRetry(undefined, false), true, "no exit code")
        compare(InstallInfo.needsRetry(0, false), false)
        compare(InstallInfo.needsRetry(1, true), false)
        compare(InstallInfo.needsRetry(2, true), false)
        compare(InstallInfo.needsRetry(0, true), false)
    }

    function test_goodReply() {
        var info = InstallInfo.parseReply(0, reply({}))
        compare(info, {known: true, helper: "system", distro: "arch", system_helper: true, user_helper: false,
                       user_plasmoid: false, system_plasmoid: true, shadowed: false})
        compare(InstallInfo.parseReply(0, reply({}) + "\n").known, true, "a trailing newline")
        ;["user", "system", "other"].forEach(function (helper) {
            compare(InstallInfo.parseReply(0, reply({helper: helper})).helper, helper)
        })
        ;["arch", "fedora", "debian", "other"].forEach(function (distro) {
            compare(InstallInfo.parseReply(0, reply({distro: distro})).distro, distro)
        })
    }

    // The contract's rule: a home-folder copy next to a system one, for the
    // helper or the widget.
    function test_shadowedRule_data() {
        var rows = []
        for (var bits = 0; bits < 16; bits++) {
            var flags = {user_helper: !!(bits & 1), system_helper: !!(bits & 2),
                         user_plasmoid: !!(bits & 4), system_plasmoid: !!(bits & 8)}
            rows.push({tag: JSON.stringify(flags), flags: flags,
                       shadowed: (flags.user_helper && flags.system_helper)
                                 || (flags.user_plasmoid && flags.system_plasmoid)})
        }
        return rows
    }

    function test_shadowedRule(data) {
        compare(InstallInfo.isShadowed(data.flags), data.shadowed)
        compare(InstallInfo.parseReply(0, reply(data.flags)).shadowed, data.shadowed)
    }

    function test_shadowedExamples() {
        compare(InstallInfo.parseReply(0, reply({user_helper: true})).shadowed, true, "both helpers")
        compare(InstallInfo.parseReply(0, reply({user_plasmoid: true})).shadowed, true, "both widgets")
        compare(InstallInfo.parseReply(0, reply({user_helper: true, system_helper: false,
                                                 user_plasmoid: true, system_plasmoid: false})).shadowed,
                false, "a script install alone")
        // The helper key says where the running copy is, not whether one shadows.
        compare(InstallInfo.parseReply(0, reply({helper: "user"})).shadowed, false)
        compare(InstallInfo.isShadowed(null), false)
        compare(InstallInfo.isShadowed({user_helper: 1, system_helper: "yes"}), false, "only true counts")
    }

    function test_notTheCommand() {
        checkUnknown(InstallInfo.parseReply(1, reply({})), "exit code 1")
        checkUnknown(InstallInfo.parseReply(2, ""), "an older helper or a combined option")
        checkUnknown(InstallInfo.parseReply(0, "{\"ok\":false,\"error\":\"os-error\"}"), "the helper's error")
        checkUnknown(InstallInfo.parseReply("0", reply({})), "exit code as text")
        checkUnknown(InstallInfo.parseReply(undefined, reply({})), "no exit code")
        checkUnknown(InstallInfo.parseReply(0, undefined), "no stdout")
        checkUnknown(InstallInfo.parseReply(0, null), "null stdout")
        checkUnknown(InstallInfo.parseReply(0, ""), "empty stdout")
        checkUnknown(InstallInfo.parseReply(0, "usage: hearthwire [-h]"), "an old helper's text")
        checkUnknown(InstallInfo.parseReply(0, "{\"ok\": true,"), "cut off")
        checkUnknown(InstallInfo.parseReply(0, "[]"), "an array")
        checkUnknown(InstallInfo.parseReply(0, "null"), "null")
        checkUnknown(InstallInfo.parseReply(0, "true"), "a word")
        checkUnknown(InstallInfo.parseReply(0, {ok: true}), "not text")
        var padded = reply({}) + new Array(InstallInfo.MAX_REPLY_CHARS).join(" ")
        checkUnknown(InstallInfo.parseReply(0, padded), "too long")
    }

    // Only the documented keys and words: anything else is unknown, never
    // a part of it.
    function test_strictKeysAndValues() {
        var odd = [
            [{ok: false}, "not ok"],
            [{ok: "true"}, "ok as text"],
            [{install_info_version: 2}, "a later version"],
            [{install_info_version: "1"}, "version as text"],
            [{helper: "venv"}, "an unknown helper"],
            [{helper: "User"}, "a helper in caps"],
            [{helper: ["user"]}, "a helper list"],
            [{distro: "ubuntu"}, "an unmapped distro"],
            [{distro: "Arch"}, "a distro in caps"],
            [{distro: "__proto__"}, "a prototype name"],
            [{distro: null}, "a null distro"],
            [{user_helper: 1}, "a number flag"],
            [{system_plasmoid: "true"}, "a text flag"],
            [{user_plasmoid: null}, "a null flag"],
            [{path: "/home/soul/.local"}, "an extra key"],
            [{error: "boom"}, "an extra error"],
            [{distro: undefined}, "no distro"],
            [{user_helper: undefined}, "a missing flag"],
            [{ok: undefined}, "no ok"],
            [{install_info_version: undefined}, "no version"]
        ]
        odd.forEach(function (entry) {
            checkUnknown(InstallInfo.parseReply(0, reply(entry[0])), entry[1])
        })
        // An odd reply that would say shadowed is still unknown.
        checkUnknown(InstallInfo.parseReply(0, reply({user_helper: true, path: "/x"})), "shadowed with an extra key")
        checkUnknown(InstallInfo.parseReply(0, reply({user_helper: true, install_info_version: 2})),
                     "shadowed from a later version")
    }

    // Each unknown is a fresh copy: a caller changing one can't change the next.
    function test_unknownIsACopy() {
        var first = InstallInfo.unknown()
        first.shadowed = true
        first.distro = "arch"
        compare(InstallInfo.unknown().shadowed, false)
        compare(InstallInfo.unknown().distro, "other")
        compare(InstallInfo.UNKNOWN.shadowed, false)
    }
}
