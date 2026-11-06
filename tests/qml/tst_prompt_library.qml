import QtQuick
import QtTest
import "../../plasmoid/contents/ui/PromptLibrary.js" as PromptLibrary

TestCase {
    name: "PromptLibrary"

    readonly property string prefix: "env HEARTHWIRE_RUN=3 HEARTHWIRE_APPLET=5 python3 -P -m hearthwire "

    function test_promptsCommands() {
        compare(PromptLibrary.promptsCommand("list", 3, 5), prefix + "--prompts list")
        compare(PromptLibrary.promptsCommand("add", 3, 5, { kind: "prompt" }), prefix + "--prompts add --kind prompt")
        compare(PromptLibrary.promptsCommand("add", 3, 5, { kind: "persona" }), prefix + "--prompts add --kind persona")
        compare(PromptLibrary.promptsCommand("replace", 3, 5, { id: 7 }), prefix + "--prompts replace --id 7")
        compare(PromptLibrary.promptsCommand("remove", 3, 5, { id: 2147483648 }),
                prefix + "--prompts remove --id 2147483648")
        compare(PromptLibrary.promptsCommand("set-persona", 3, 5, { model: "llama3:latest", id: 4 }),
                prefix + "--prompts set-persona --model llama3:latest --id 4")
        compare(PromptLibrary.promptsCommand("set-persona", 3, 5, { model: "hf.co/a/b-Q4_K_M", id: null }),
                prefix + "--prompts set-persona --model hf.co/a/b-Q4_K_M --none")
    }

    function test_promptsCommandsRejectAnythingElse() {
        var bad = [
            ["list", "3", 5, {}], ["list", 3, -1, {}], ["purge", 3, 5, {}], ["list; rm", 3, 5, {}],
            ["add", 3, 5, {}], ["add", 3, 5, { kind: "Prompt" }], ["add", 3, 5, { kind: "prompt --x" }],
            ["replace", 3, 5, { id: 0 }], ["replace", 3, 5, { id: "7" }], ["replace", 3, 5, { id: 1.5 }],
            ["remove", 3, 5, { id: 2147483649 }], ["remove", 3, 5, {}],
            ["set-persona", 3, 5, { model: "-x", id: 1 }], ["set-persona", 3, 5, { model: "a b", id: 1 }],
            ["set-persona", 3, 5, { model: "a;b", id: 1 }], ["set-persona", 3, 5, { model: "$(x)", id: 1 }],
            ["set-persona", 3, 5, { model: "m", id: undefined }], ["set-persona", 3, 5, { model: "m", id: 0 }],
            ["set-persona", 3, 5, { model: "x".repeat(201), id: 1 }]
        ]
        for (var index = 0; index < bad.length; index++)
            compare(PromptLibrary.promptsCommand(bad[index][0], bad[index][1], bad[index][2], bad[index][3]), "",
                    JSON.stringify(bad[index]))
    }

    function test_hexPath() {
        compare(PromptLibrary.hexPath("file:///tmp/a.txt"), "2f746d702f612e747874")
        // Percent escapes decode as UTF-8; the hex is the path's UTF-8 bytes.
        compare(PromptLibrary.hexPath("file:///h/%C3%A9%20x"), "2f682fc3a92078")
        compare(PromptLibrary.hexPath("file:///h/é"), "2f682fc3a9")
        compare(PromptLibrary.hexPath("file:///a'b;$(c)"), "2f6127623b24286329")
        var refused = ["", null, undefined, "/tmp/a.txt", "file://host/tmp/a", "file://localhost/tmp/a",
                       "http://127.0.0.1/a", "file:///a?b", "file:///a#b", "file:///a%00b", "file:///a%ZZ",
                       "file:///a%C3", "FILE:///a", "smb://x/y"]
        for (var index = 0; index < refused.length; index++)
            compare(PromptLibrary.hexPath(refused[index]), "", String(refused[index]))
        // At most 8192 hex digits (4096 bytes).
        compare(PromptLibrary.hexPath("file:///" + "a".repeat(4095)).length, 8192)
        compare(PromptLibrary.hexPath("file:///" + "a".repeat(4096)), "")
    }

    function test_readDroppedCommand() {
        compare(PromptLibrary.readDroppedCommand("2f61", 3, 5), prefix + "--read-dropped 2f61")
        var bad = ["", "2f6", "2F61", "2f 61", "2f61;", "zz", "a".repeat(8194), null]
        for (var index = 0; index < bad.length; index++)
            compare(PromptLibrary.readDroppedCommand(bad[index], 3, 5), "", String(bad[index]))
        compare(PromptLibrary.readDroppedCommand("2f61", -1, 5), "")
    }

    function test_parseList() {
        var reply = JSON.stringify({ ok: true,
            items: [{ id: 1, kind: "prompt", text: "Summarize:" }, { id: 3, kind: "persona", text: "Be brief" },
                    { id: 3, kind: "prompt", text: "dup" }, { id: 0, kind: "prompt", text: "x" },
                    { id: 4, kind: "other", text: "x" }, { id: 5, kind: "prompt", text: "" },
                    { id: 6, kind: "persona", text: "x".repeat(8001) }, { id: 7, kind: "prompt", text: "a\u0000" },
                    null, "x"],
            personas: { "llama3:latest": 3, "qwen3:8b": 1, "bad name": 3, "-x": 3, "gone": 9 } })
        compare(PromptLibrary.parseList(0, reply), { ok: true,
            items: [{ id: 1, kind: "prompt", text: "Summarize:" }, { id: 3, kind: "persona", text: "Be brief" }],
            personas: { "m:llama3:latest": 3 } })
        compare(PromptLibrary.parseList(0, "{\"ok\":false,\"error\":\"locked\"}"), { ok: false, error: "locked" })
        compare(PromptLibrary.parseList(0, "{\"ok\":false,\"error\":\"secret /path\"}"), { ok: false, error: "failed" })
        compare(PromptLibrary.parseList(1, "{\"ok\":true,\"items\":[]}"), { ok: false, error: "bad-reply" })
        compare(PromptLibrary.parseList(0, "not json"), { ok: false, error: "bad-reply" })
        compare(PromptLibrary.parseList(0, "[]"), { ok: false, error: "bad-reply" })
        compare(PromptLibrary.parseList(0, "{\"ok\":true}"), { ok: true, items: [], personas: {} })
        // At most 100 items.
        var many = []
        for (var index = 1; index <= 120; index++)
            many.push({ id: index, kind: "prompt", text: "p" + index })
        compare(PromptLibrary.parseList(0, JSON.stringify({ ok: true, items: many })).items.length, 100)
    }

    function test_parseChangeAndDropped() {
        compare(PromptLibrary.parseChange(0, "{\"ok\":true,\"id\":5}"), { ok: true, id: 5 })
        compare(PromptLibrary.parseChange(0, "{\"ok\":true}"), { ok: true })
        compare(PromptLibrary.parseChange(0, "{\"ok\":false,\"error\":\"cancelled\"}"), { ok: false, error: "cancelled" })
        compare(PromptLibrary.parseDropped(0, "{\"ok\":true,\"text\":\"hello\\n\"}"), { ok: true, text: "hello\n" })
        var codes = ["absent", "unreadable", "not-file", "too-large", "not-text", "too-long", "os-error"]
        for (var index = 0; index < codes.length; index++)
            compare(PromptLibrary.parseDropped(0, "{\"ok\":false,\"error\":\"" + codes[index] + "\"}"),
                    { ok: false, error: codes[index] })
        compare(PromptLibrary.parseDropped(0, JSON.stringify({ ok: true, text: "x".repeat(32001) })),
                { ok: false, error: "bad-reply" })
        compare(PromptLibrary.parseDropped(0, JSON.stringify({ ok: true, text: 5 })), { ok: false, error: "bad-reply" })
        compare(PromptLibrary.parseDropped(0, JSON.stringify({ ok: true, text: "a\u0000" })),
                { ok: false, error: "bad-reply" })
        compare(PromptLibrary.parseDropped(2, "{\"ok\":true,\"text\":\"x\"}"), { ok: false, error: "bad-reply" })
    }

    function test_usingTheLibrary() {
        var items = [{ id: 1, kind: "prompt", text: "P" }, { id: 2, kind: "persona", text: "Be brief" },
                     { id: -1, kind: "persona", text: "Session" }]
        compare(PromptLibrary.itemsOf(items, "persona").length, 2)
        compare(PromptLibrary.defaultPersona(items, { "m:llama3": 2 }, "llama3"), "Be brief")
        compare(PromptLibrary.defaultPersona(items, { "m:llama3": 1 }, "llama3"), "")
        compare(PromptLibrary.defaultPersona(items, {}, "llama3"), "")
        compare(PromptLibrary.defaultPersona(items, { "m:__proto__": 2 }, "constructor"), "")
        compare(PromptLibrary.label("\n  First line \nsecond"), "First line")
        compare(PromptLibrary.label("x".repeat(70)), "x".repeat(60) + "…")
        compare(PromptLibrary.label(null), "")
        compare(PromptLibrary.insertAt("Hello world", 6, "big ", 100), { ok: true, text: "Hello big world", cursor: 10 })
        compare(PromptLibrary.insertAt("ab", 99, "c", 100), { ok: true, text: "abc", cursor: 3 })
        compare(PromptLibrary.insertAt("ab", 1, "xyz", 4), { ok: false, error: "too-long" })
    }
}
