import QtQuick
import QtTest
import "../../plasmoid/contents/ui/OllamaChat.js" as OllamaChat

TestCase {
    name: "OllamaChat"

    function line(object) {
        return JSON.stringify(object) + "\n"
    }

    function chunk(content, extra) {
        var value = { model: "llama3:latest", message: { role: "assistant", content: content },
                      done: false }
        if (extra)
            for (var key in extra)
                value[key] = extra[key]
        return line(value)
    }

    function feedAll(chunks, final) {
        var state = OllamaChat.newStream()
        var body = ""
        for (var index = 0; index < chunks.length; index++) {
            body += chunks[index]
            state = OllamaChat.feedStream(state, body, final === true && index === chunks.length - 1)
        }
        return state
    }

    // --- metadata and site list ---------------------------------------------

    function test_constants() {
        compare(OllamaChat.ENTRY.id, "ollama")
        compare(OllamaChat.ENTRY.name, "Ollama")
        compare(OllamaChat.ENTRY.icon, "provider-local.svg")
        compare(OllamaChat.ENTRY.native, true)
        compare(OllamaChat.ENTRY.default_on, false)
        compare(OllamaChat.DEFAULT_ADDRESS, "http://127.0.0.1:11434")
        compare(OllamaChat.MAX_ADDRESS_LENGTH, 64)
        compare(OllamaChat.MAX_PROMPT_CHARS, 32000)
        compare(OllamaChat.MAX_REPLY_CHARS, 200000)
        compare(OllamaChat.MAX_MODELS, 200)
    }

    function test_entryIsFrozen() {
        try {
            OllamaChat.ENTRY.id = "x"
        } catch (error) {
        }
        compare(OllamaChat.ENTRY.id, "ollama")
    }

    function test_isEnabled() {
        compare(OllamaChat.isEnabled('["claude","ollama"]'), true)
        compare(OllamaChat.isEnabled('["ollama"]'), true)
        compare(OllamaChat.isEnabled('["claude"]'), false)
        compare(OllamaChat.isEnabled("[]"), false)
        compare(OllamaChat.isEnabled('"ollama"'), false)
        compare(OllamaChat.isEnabled('{"ollama":true}'), false)
        compare(OllamaChat.isEnabled("not json"), false)
        compare(OllamaChat.isEnabled(""), false)
        compare(OllamaChat.isEnabled(undefined), false)
        compare(OllamaChat.isEnabled(null), false)
        compare(OllamaChat.isEnabled(["ollama"]), false)
    }

    function test_menuEntries() {
        var web = [{ id: "claude" }, { id: "local" }]
        var on = OllamaChat.menuEntries(web, '["claude","ollama"]')
        compare(on.length, 3)
        compare(on[0].id, "claude")
        compare(on[1].id, "local")
        compare(on[2].id, "ollama")
        compare(on[2].native, true)
        compare(web.length, 2)
        var off = OllamaChat.menuEntries(web, '["claude"]')
        compare(off.length, 2)
        compare(OllamaChat.menuEntries(web, "junk").length, 2)
        compare(OllamaChat.menuEntries(null, '["ollama"]').length, 1)
        compare(OllamaChat.menuEntries(undefined, "[]").length, 0)
    }

    function test_allSiteIds() {
        compare(OllamaChat.allSiteIds(["claude", "local"]), ["claude", "local", "ollama"])
        compare(OllamaChat.allSiteIds([]), ["ollama"])
        compare(OllamaChat.allSiteIds(null), ["ollama"])
        compare(OllamaChat.allSiteIds(["ollama", "claude"]), ["claude", "ollama"])
    }

    // --- address -------------------------------------------------------------

    function test_validateAddressAccepts() {
        var cases = [
            ["http://127.0.0.1:11434", "http://127.0.0.1:11434"],
            ["http://127.0.0.1:11434/", "http://127.0.0.1:11434"],
            ["http://localhost:8080", "http://localhost:8080"],
            ["HTTP://LOCALHOST:8080/", "http://localhost:8080"],
            ["http://[::1]:11434", "http://[::1]:11434"],
            ["http://127.0.0.1:1", "http://127.0.0.1:1"],
            ["http://127.0.0.1:65535", "http://127.0.0.1:65535"],
            ["http://127.0.0.1:00080", "http://127.0.0.1:80"]
        ]
        for (var index = 0; index < cases.length; index++) {
            var checked = OllamaChat.validateAddress(cases[index][0])
            compare(checked.ok, true, cases[index][0])
            compare(checked.address, cases[index][1], cases[index][0])
            compare(checked.error, "", cases[index][0])
        }
    }

    function test_validateAddressEmptyMeansDefault() {
        var values = ["", undefined, null]
        for (var index = 0; index < values.length; index++) {
            var checked = OllamaChat.validateAddress(values[index])
            compare(checked.ok, true)
            compare(checked.address, OllamaChat.DEFAULT_ADDRESS)
        }
    }

    function test_validateAddressErrors() {
        var cases = [
            ["http://127.0.0.1:11434/" + "a".repeat(60), "too-long"],
            [" http://127.0.0.1:11434", "whitespace"],
            ["http://127.0.0.1:11434 ", "whitespace"],
            ["http://127.0.0.1:11 434", "whitespace"],
            ["http://127.0.0.1:11434\t", "whitespace"],
            ["http://127.0.0.1:\u000011434", "whitespace"],
            ["http://user@127.0.0.1:11434", "userinfo"],
            ["http://user:pass@127.0.0.1:11434", "userinfo"],
            ["http://evil.example@127.0.0.1:11434", "userinfo"],
            ["https://127.0.0.1:11434", "scheme"],
            ["ftp://127.0.0.1:11434", "scheme"],
            ["file:///tmp/x", "scheme"],
            ["javascript:alert(1)", "scheme"],
            ["http://127.0.0.2:11434", "not-loopback"],
            ["http://0.0.0.0:11434", "not-loopback"],
            ["http://0x7f000001:11434", "not-loopback"],
            ["http://2130706433:11434", "not-loopback"],
            ["http://127.1:11434", "not-loopback"],
            ["http://foo.localhost:11434", "not-loopback"],
            ["http://localhost.:11434", "not-loopback"],
            ["http://127.0.0.1.nip.io:11434", "not-loopback"],
            ["http://evil.example:11434", "not-loopback"],
            ["http://[::ffff:127.0.0.1]:11434", "not-loopback"],
            ["http://[::]:11434", "not-loopback"],
            ["http://192.168.1.2:11434", "not-loopback"],
            ["http://127.0.0.1", "port-missing"],
            ["http://127.0.0.1:", "port-missing"],
            ["http://localhost/", "port-missing"],
            ["http://[::1]", "port-missing"],
            ["http://127.0.0.1:0", "port-range"],
            ["http://127.0.0.1:65536", "port-range"],
            ["http://127.0.0.1:100000", "port-range"],
            ["http://127.0.0.1:11434/api", "path"],
            ["http://127.0.0.1:11434//", "path"],
            ["http://127.0.0.1:11434?x=1", "path"],
            ["http://127.0.0.1:11434#top", "path"],
            ["http://127.0.0.1:11434/?", "path"],
            ["127.0.0.1:11434", "malformed"],
            ["localhost:11434", "scheme"],
            ["localhost", "malformed"],
            ["//127.0.0.1:11434", "malformed"],
            ["http:127.0.0.1:11434", "malformed"],
            ["http://", "malformed"],
            ["http://:11434", "malformed"],
            ["http://[::1:11434", "malformed"],
            ["http://127.0.0.1:abc", "malformed"],
            ["http://127.0.0.1:+80", "malformed"],
            ["http://127.0.0.1:80:81", "malformed"]
        ]
        for (var index = 0; index < cases.length; index++) {
            var checked = OllamaChat.validateAddress(cases[index][0])
            compare(checked.ok, false, cases[index][0])
            compare(checked.address, "", cases[index][0])
            compare(checked.error, cases[index][1], cases[index][0])
        }
    }

    function test_validateAddressLengthLimit() {
        // 64 characters exactly is fine as far as length goes.
        var exact = "http://127.0.0.1:11434/"
        exact += "?".repeat(OllamaChat.MAX_ADDRESS_LENGTH - exact.length)
        compare(exact.length, 64)
        compare(OllamaChat.validateAddress(exact).error, "path")
        compare(OllamaChat.validateAddress(exact + "?").error, "too-long")
    }

    function test_addressToPersist() {
        var base = "http://127.0.0.1:11434"
        compare(OllamaChat.addressToPersist("http://localhost:8080/", base),
                { address: "http://localhost:8080", error: "" })
        compare(OllamaChat.addressToPersist("  http://localhost:8080  ", base),
                { address: "http://localhost:8080", error: "" })
        compare(OllamaChat.addressToPersist("", base),
                { address: OllamaChat.DEFAULT_ADDRESS, error: "" })
        compare(OllamaChat.addressToPersist("   ", base),
                { address: OllamaChat.DEFAULT_ADDRESS, error: "" })
        // Half-typed or invalid text keeps the baseline saved when the page opened.
        compare(OllamaChat.addressToPersist("http://user@", "http://localhost:9000"),
                { address: "http://localhost:9000", error: "userinfo" })
        compare(OllamaChat.addressToPersist("http://127.0.0.1:", "http://[::1]:1"),
                { address: "http://[::1]:1", error: "port-missing" })
        compare(OllamaChat.addressToPersist("https://x", "http://localhost:9000/"),
                { address: "http://localhost:9000", error: "scheme" })
        // An invalid baseline never gets saved.
        compare(OllamaChat.addressToPersist("http://evil", "http://evil.example:1"),
                { address: OllamaChat.DEFAULT_ADDRESS, error: "not-loopback" })
        compare(OllamaChat.addressToPersist("http://evil", undefined),
                { address: OllamaChat.DEFAULT_ADDRESS, error: "not-loopback" })
        compare(OllamaChat.addressToPersist(null, base),
                { address: OllamaChat.DEFAULT_ADDRESS, error: "" })
    }

    function test_effectiveAddress() {
        compare(OllamaChat.effectiveAddress("http://localhost:8080/"), "http://localhost:8080")
        compare(OllamaChat.effectiveAddress(""), OllamaChat.DEFAULT_ADDRESS)
        compare(OllamaChat.effectiveAddress("http://10.0.0.1:11434"), OllamaChat.DEFAULT_ADDRESS)
        compare(OllamaChat.effectiveAddress(" http://localhost:8080"), OllamaChat.DEFAULT_ADDRESS)
        compare(OllamaChat.effectiveAddress(undefined), OllamaChat.DEFAULT_ADDRESS)
        compare(OllamaChat.effectiveAddress(8080), OllamaChat.DEFAULT_ADDRESS)
    }

    function test_portOf() {
        compare(OllamaChat.portOf("http://127.0.0.1:11434"), 11434)
        compare(OllamaChat.portOf("http://[::1]:8080/"), 8080)
        compare(OllamaChat.portOf("http://localhost:1"), 1)
        compare(OllamaChat.portOf("http://evil.example:80"), 0)
        compare(OllamaChat.portOf(""), 0)
        compare(OllamaChat.portOf(null), 0)
    }

    function test_endpoint() {
        var base = "http://127.0.0.1:11434"
        compare(OllamaChat.endpoint(base, "version"), base + "/api/version")
        compare(OllamaChat.endpoint(base, "tags"), base + "/api/tags")
        compare(OllamaChat.endpoint(base, "chat"), base + "/api/chat")
        compare(OllamaChat.endpoint("http://[::1]:9/", "tags"), "http://[::1]:9/api/tags")
        compare(OllamaChat.endpoint(base, "pull"), "")
        compare(OllamaChat.endpoint(base, "delete"), "")
        compare(OllamaChat.endpoint(base, "toString"), "")
        compare(OllamaChat.endpoint(base, "__proto__"), "")
        compare(OllamaChat.endpoint(base, undefined), "")
        compare(OllamaChat.endpoint("http://evil.example:11434", "chat"), "")
        compare(OllamaChat.endpoint("", "chat"), "")
        compare(OllamaChat.endpoint(undefined, "chat"), "")
    }

    // --- request bodies ------------------------------------------------------

    function test_chatRequestBody() {
        var body = OllamaChat.chatRequestBody("llama3:latest", [
            { role: "user", content: "hi" },
            { role: "assistant", content: "hello", failed: true },
            { role: "user", content: "again" }
        ])
        compare(body, '{"model":"llama3:latest","messages":[{"role":"user","content":"hi"},'
                + '{"role":"assistant","content":"hello"},{"role":"user","content":"again"}],'
                + '"stream":true}')
        var parsed = JSON.parse(OllamaChat.chatRequestBody("m", [{ role: "user", content: "\"<x>\n" }]))
        compare(parsed.messages[0].content, "\"<x>\n")
        compare(parsed.stream, true)
    }

    function test_chatRequestBodyRejects() {
        var ok = [{ role: "user", content: "hi" }]
        compare(OllamaChat.chatRequestBody("", ok), "")
        compare(OllamaChat.chatRequestBody("bad name", ok), "")
        compare(OllamaChat.chatRequestBody("a\"b", ok), "")
        compare(OllamaChat.chatRequestBody("x".repeat(201), ok), "")
        compare(OllamaChat.chatRequestBody(undefined, ok), "")
        compare(OllamaChat.chatRequestBody("m", []), "")
        compare(OllamaChat.chatRequestBody("m", null), "")
        compare(OllamaChat.chatRequestBody("m", "hi"), "")
        compare(OllamaChat.chatRequestBody("m", [{ role: "system", content: "x" }]), "")
        compare(OllamaChat.chatRequestBody("m", [{ role: "tool", content: "x" }]), "")
        compare(OllamaChat.chatRequestBody("m", [{ role: "user", content: 5 }]), "")
        compare(OllamaChat.chatRequestBody("m", [{ role: "user" }]), "")
        compare(OllamaChat.chatRequestBody("m", [null]), "")
        compare(OllamaChat.chatRequestBody("m", [ok[0], "x"]), "")
        compare(OllamaChat.chatRequestBody("m",
                [{ role: "user", content: "x".repeat(OllamaChat.MAX_PROMPT_CHARS + 1) }]), "")
        compare(OllamaChat.chatRequestBody("m",
                [{ role: "assistant", content: "x".repeat(OllamaChat.MAX_REPLY_CHARS + 1) }]), "")
        verify(OllamaChat.chatRequestBody("m",
                [{ role: "user", content: "x".repeat(OllamaChat.MAX_PROMPT_CHARS) }]) !== "")
    }

    function test_chatRequestBodySystemGoesFirst() {
        var history = [{ role: "user", content: "hi" }, { role: "assistant", content: "hello" },
                       { role: "user", content: "again" }]
        var parsed = JSON.parse(OllamaChat.chatRequestBody("m", history, "Answer in German."))
        compare(parsed.messages.length, 4)
        compare(parsed.messages[0], { role: "system", content: "Answer in German." })
        compare(parsed.messages[1].role, "user")
        compare(parsed.messages.filter(function (m) { return m.role === "system" }).length, 1)
        // No personality: no system message at all.
        var values = [undefined, null, "", "   \n "]
        for (var index = 0; index < values.length; index++) {
            parsed = JSON.parse(OllamaChat.chatRequestBody("m", history, values[index]))
            compare(parsed.messages.length, 3, String(values[index]))
            compare(parsed.messages[0].role, "user")
        }
        // At the cap it goes; one more character, or not a string, sends nothing.
        var full = "x".repeat(OllamaChat.MAX_SYSTEM_CHARS)
        compare(JSON.parse(OllamaChat.chatRequestBody("m", history, full)).messages[0].content, full)
        compare(OllamaChat.chatRequestBody("m", history, full + "x"), "")
        compare(OllamaChat.chatRequestBody("m", history, 5), "")
        compare(OllamaChat.chatRequestBody("m", history, { role: "system" }), "")
        compare(OllamaChat.chatRequestBody("m", history, ["x"]), "")
        // History can never carry the system role, with or without a personality.
        compare(OllamaChat.chatRequestBody("m", [{ role: "system", content: "x" }], "p"), "")
        compare(OllamaChat.chatRequestBody("m", [], "p"), "")
        compare(OllamaChat.MAX_SYSTEM_CHARS, 8000)
        // With a personality the newest user message starts with the reminder.
        parsed = JSON.parse(OllamaChat.chatRequestBody("m", history, "Answer in German."))
        compare(parsed.messages.map(function (m) { return m.content }),
                ["Answer in German.", "hi", "hello", OllamaChat.PERSONA_REMINDER + "again"])
        // Without one, nothing is added.
        parsed = JSON.parse(OllamaChat.chatRequestBody("m", history, "  "))
        compare(parsed.messages[2].content, "again")
        compare(OllamaChat.ROLES, ["user", "assistant"])
    }

    function test_unloadRequestBody() {
        compare(OllamaChat.unloadRequestBody("llama3:latest"),
                '{"model":"llama3:latest","messages":[],"keep_alive":0}')
        compare(OllamaChat.unloadRequestBody("bad name"), "")
        compare(OllamaChat.unloadRequestBody(""), "")
        compare(OllamaChat.unloadRequestBody(null), "")
    }

    // --- version and tags ----------------------------------------------------

    function test_parseVersion() {
        compare(OllamaChat.parseVersion(200, '{"version":"0.40.13"}'), { ok: true, version: "0.40.13" })
        compare(OllamaChat.parseVersion(200, '{"version":"1.2"}'), { ok: true, version: "1.2" })
        compare(OllamaChat.parseVersion(200, '{"version":"0.5.0-rc1"}').ok, true)
        var bad = [
            [200, "Ollama is running"],
            [200, ""],
            [200, "[]"],
            [200, '{"version":1}'],
            [200, '{"version":"abc"}'],
            [200, '{"version":"1"}'],
            [200, '{"version":"1.2<b>"}'],
            [200, '{"version":"1.2' + "9".repeat(40) + '"}'],
            [200, '{}'],
            [404, '{"version":"0.40.13"}'],
            [0, ""],
            [200, undefined]
        ]
        for (var index = 0; index < bad.length; index++)
            compare(OllamaChat.parseVersion(bad[index][0], bad[index][1]),
                    { ok: false, error: "not-ollama" }, String(bad[index][1]))
    }

    function test_parseTags() {
        var text = JSON.stringify({ models: [
            { name: "llama3:latest", model: "llama3:latest", size: 1,
              details: { family: "llama", parameter_size: "8.0B" }, capabilities: ["completion"] },
            { name: "qwen3:8b", details: { family: "qwen3" } },
            { name: "mistral:7b" }
        ] })
        var tags = OllamaChat.parseTags(200, text)
        compare(tags.ok, true)
        compare(tags.error, "")
        compare(tags.hiddenRemote, 0)
        compare(tags.models, [
            { name: "llama3:latest", parameterSize: "8.0B", family: "llama" },
            { name: "qwen3:8b", parameterSize: "", family: "qwen3" },
            { name: "mistral:7b", parameterSize: "", family: "" }
        ])
    }

    function test_parseTagsHidesRemote() {
        var text = JSON.stringify({ models: [
            { name: "gpt-oss:120b-cloud" },
            { name: "deepseek:cloud" },
            { name: "Kimi:CLOUD" },
            { name: "remote-a", remote_host: "https://ollama.com:443" },
            { name: "remote-b", remote_model: "gpt-oss:120b" },
            { name: "remote-c", remote_host: "" },
            { name: "llama3:latest" },
            { name: "cloudy:latest" }
        ] })
        var tags = OllamaChat.parseTags(200, text)
        compare(tags.ok, true)
        compare(tags.hiddenRemote, 6)
        compare(tags.models.map(function (m) { return m.name }), ["llama3:latest", "cloudy:latest"])
    }

    function test_parseTagsCapabilities() {
        var text = JSON.stringify({ models: [
            { name: "nomic-embed-text:latest", capabilities: ["embedding"] },
            { name: "empty-caps", capabilities: [] },
            { name: "odd-caps", capabilities: "completion" },
            { name: "vision", capabilities: ["completion", "vision"] },
            { name: "null-caps", capabilities: null },
            { name: "no-caps" }
        ] })
        var tags = OllamaChat.parseTags(200, text)
        compare(tags.models.map(function (m) { return m.name }), ["vision", "null-caps", "no-caps"])
        compare(tags.hiddenRemote, 0)
    }

    function test_parseTagsBadEntries() {
        var text = JSON.stringify({ models: [
            null, 5, "llama3", [], {},
            { name: "" },
            { name: "has space" },
            { name: "<img src=x>" },
            { name: "x".repeat(201) },
            { name: 42 },
            { name: "ok:1", details: { family: "<b>", parameter_size: "x".repeat(41) } },
            { name: "ok:1" },
            { name: "ok/two+x_y-z.v:3", details: "junk" }
        ] })
        var tags = OllamaChat.parseTags(200, text)
        compare(tags.ok, true)
        compare(tags.models, [
            { name: "ok:1", parameterSize: "", family: "" },
            { name: "ok/two+x_y-z.v:3", parameterSize: "", family: "" }
        ])
    }

    function test_parseTagsMaxModels() {
        var models = []
        for (var index = 0; index < 250; index++)
            models.push({ name: "m" + index })
        var tags = OllamaChat.parseTags(200, JSON.stringify({ models: models }))
        compare(tags.models.length, OllamaChat.MAX_MODELS)
        compare(tags.models[0].name, "m0")
        compare(tags.models[199].name, "m199")
    }

    function test_parseTagsFailures() {
        compare(OllamaChat.parseTags(200, '{"models":[]}'),
                { ok: true, models: [], hiddenRemote: 0, error: "" })
        compare(OllamaChat.parseTags(200, "nope"),
                { ok: false, models: [], hiddenRemote: 0, error: "bad-tags" })
        compare(OllamaChat.parseTags(200, '{"models":{}}').error, "bad-tags")
        compare(OllamaChat.parseTags(200, "[]").error, "bad-tags")
        compare(OllamaChat.parseTags(200, undefined).error, "bad-tags")
        compare(OllamaChat.parseTags(0, "").error, "not-running")
        compare(OllamaChat.parseTags(403, "").error, "forbidden")
        compare(OllamaChat.parseTags(500, '{"models":[{"name":"a"}]}').ok, false)
    }

    function test_pickModel() {
        var models = [{ name: "a:1" }, { name: "b:2" }]
        compare(OllamaChat.pickModel(models, "b:2"), "b:2")
        compare(OllamaChat.pickModel(models, "gone"), "a:1")
        compare(OllamaChat.pickModel(models, ""), "a:1")
        compare(OllamaChat.pickModel(models, undefined), "a:1")
        compare(OllamaChat.pickModel([], "a:1"), "")
        compare(OllamaChat.pickModel(null, "a:1"), "")
        compare(OllamaChat.pickModel([null, { name: "bad name" }, { name: "c" }], "bad name"), "c")
    }

    // --- stream --------------------------------------------------------------

    function test_newStream() {
        compare(OllamaChat.newStream(), { offset: 0, content: "", thinking: false, done: false,
                                          doneReason: "", error: "", errorText: "" })
        verify(OllamaChat.newStream() !== OllamaChat.newStream())
    }

    function test_feedStreamBasic() {
        var state = feedAll([chunk("Hel"), chunk("lo"),
                             line({ message: { role: "assistant", content: "" }, done: true,
                                    done_reason: "stop", eval_count: 3 })])
        compare(state.content, "Hello")
        compare(state.done, true)
        compare(state.doneReason, "stop")
        compare(state.error, "")
        compare(state.thinking, false)
    }

    function test_feedStreamDoesNotMutateInput() {
        var start = OllamaChat.newStream()
        var next = OllamaChat.feedStream(start, chunk("x"), false)
        compare(start.content, "")
        compare(start.offset, 0)
        compare(next.content, "x")
    }

    function test_feedStreamSplitLines() {
        var body = chunk("one") + chunk("two") + chunk("three")
        var state = OllamaChat.newStream()
        // Grow the body a few characters at a time, splitting lines anywhere.
        for (var end = 1; end <= body.length; end += 7)
            state = OllamaChat.feedStream(state, body.slice(0, end), false)
        state = OllamaChat.feedStream(state, body, false)
        compare(state.content, "onetwothree")
        compare(state.offset, body.length)
        compare(state.error, "")
    }

    function test_feedStreamPartialLineWaits() {
        var whole = chunk("abc")
        var state = OllamaChat.feedStream(OllamaChat.newStream(), whole.slice(0, 20), false)
        compare(state.content, "")
        compare(state.offset, 0)
        compare(state.error, "")
        state = OllamaChat.feedStream(state, whole, false)
        compare(state.content, "abc")
    }

    function test_feedStreamFinalPartialLine() {
        var body = chunk("a") + JSON.stringify({ message: { content: "b" }, done: true,
                                                  done_reason: "length" })
        var state = OllamaChat.feedStream(OllamaChat.newStream(), body, false)
        compare(state.content, "a")
        compare(state.done, false)
        state = OllamaChat.feedStream(state, body, true)
        compare(state.content, "ab")
        compare(state.done, true)
        compare(state.doneReason, "length")
        // A cut-off final line is a broken stream.
        var cut = OllamaChat.feedStream(OllamaChat.newStream(), chunk("a") + '{"message":{"con', true)
        compare(cut.content, "a")
        compare(cut.error, "bad-stream")
    }

    function test_feedStreamMultibyte() {
        var body = chunk("héllo ") + chunk("日本語 ") + chunk("😀")
        var state = OllamaChat.newStream()
        for (var end = 1; end <= body.length; end++)
            state = OllamaChat.feedStream(state, body.slice(0, end), false)
        compare(state.content, "héllo 日本語 😀")
        compare(state.error, "")
        // Escaped forms decode the same.
        var escaped = '{"message":{"content":"\\u00e9\\ud83d\\ude00"}}\n'
        compare(OllamaChat.feedStream(OllamaChat.newStream(), escaped, false).content,
                "é😀")
    }

    function test_feedStreamBlankLines() {
        var state = feedAll(["\n", chunk("a"), "\r\n", "   \n", chunk("b"), "\n\n"], true)
        compare(state.content, "ab")
        compare(state.error, "")
        var crlf = OllamaChat.feedStream(OllamaChat.newStream(),
                                         JSON.stringify({ message: { content: "c" } }) + "\r\n", false)
        compare(crlf.content, "c")
    }

    function test_feedStreamServerError() {
        var state = feedAll([chunk("partial "),
                             line({ error: "model <b>\"x\"</b> not found\u0007 & more" })])
        compare(state.content, "partial ")
        compare(state.error, "server")
        compare(state.errorText, "model b\"x\"/b not found more")
        compare(state.done, false)
        var odd = OllamaChat.feedStream(OllamaChat.newStream(), line({ error: { nested: 1 } }), false)
        compare(odd.error, "server")
        compare(odd.errorText, "")
    }

    function test_feedStreamBadLines() {
        var bad = ["not json\n", "[1,2]\n", "42\n", '"text"\n', "null\n"]
        for (var index = 0; index < bad.length; index++) {
            var state = OllamaChat.feedStream(OllamaChat.newStream(), chunk("a") + bad[index], false)
            compare(state.error, "bad-stream", bad[index])
            compare(state.content, "a")
        }
    }

    function test_feedStreamIgnoresOddFields() {
        var state = feedAll([
            line({ message: "text" }),
            line({ message: { content: 5 } }),
            line({ message: null, extra: [1] }),
            line({ unknown: true }),
            chunk("ok")
        ])
        compare(state.content, "ok")
        compare(state.error, "")
        var reason = OllamaChat.feedStream(OllamaChat.newStream(),
                                           line({ done: true, done_reason: "<x>" }), false)
        compare(reason.done, true)
        compare(reason.doneReason, "")
        var notDone = OllamaChat.feedStream(OllamaChat.newStream(), line({ done: "true" }), false)
        compare(notDone.done, false)
    }

    function test_feedStreamThinking() {
        var state = feedAll([
            line({ message: { role: "assistant", content: "", thinking: "secret plan" } }),
            line({ message: { role: "assistant", content: "", thinking: "more" } })
        ])
        compare(state.thinking, true)
        compare(state.content, "")
        verify(JSON.stringify(state).indexOf("secret") < 0)
        var body = line({ message: { role: "assistant", content: "", thinking: "secret plan" } })
            + line({ message: { role: "assistant", content: "", thinking: "more" } })
        state = OllamaChat.feedStream(state, body + chunk("Answer"), false)
        compare(state.thinking, true)
        compare(state.content, "Answer")
        var empty = OllamaChat.feedStream(OllamaChat.newStream(),
                                          line({ message: { content: "", thinking: "" } }), false)
        compare(empty.thinking, false)
    }

    function test_feedStreamStopsAfterDoneOrError() {
        var done = feedAll([line({ done: true, done_reason: "stop" }), chunk("late")])
        compare(done.content, "")
        compare(done.done, true)
        var sameBody = line({ done: true }) + chunk("late")
        compare(OllamaChat.feedStream(OllamaChat.newStream(), sameBody, true).content, "")
        var failed = feedAll(["junk\n", chunk("late")])
        compare(failed.error, "bad-stream")
        compare(failed.content, "")
    }

    function test_feedStreamCap() {
        var piece = "x".repeat(50000)
        var state = feedAll([chunk(piece), chunk(piece), chunk(piece), chunk(piece)])
        compare(state.content.length, OllamaChat.MAX_REPLY_CHARS)
        compare(state.error, "")
        state = OllamaChat.feedStream(state, chunk(piece).repeat(4) + chunk("y"), false)
        compare(state.error, "too-long")
        compare(state.content.length, OllamaChat.MAX_REPLY_CHARS)
        var big = OllamaChat.feedStream(OllamaChat.newStream(),
                                        chunk("z".repeat(OllamaChat.MAX_REPLY_CHARS + 10)), false)
        compare(big.error, "too-long")
        compare(big.content.length, OllamaChat.MAX_REPLY_CHARS)
    }

    // I3: an unended line is never buffered past MAX_BUFFERED_CHARS, nor a
    // whole one read; what came before stays.
    function test_feedStreamBufferCap() {
        compare(OllamaChat.MAX_BUFFERED_CHARS, 1048576)
        var head = chunk("kept")
        var open = head + "{\"message\":{\"content\":\"" + "x".repeat(OllamaChat.MAX_BUFFERED_CHARS)
        var state = OllamaChat.feedStream(OllamaChat.newStream(), open, false)
        compare(state.error, "too-long")
        compare(state.content, "kept")
        compare(state.offset, head.length)
        // At the limit it still waits for the rest of the line.
        var atLimit = head + "y".repeat(OllamaChat.MAX_BUFFERED_CHARS)
        state = OllamaChat.feedStream(OllamaChat.newStream(), atLimit, false)
        compare(state.error, "")
        compare(state.content, "kept")
        // Final, or ended by a newline: still not parsed.
        compare(OllamaChat.feedStream(OllamaChat.newStream(), open, true).error, "too-long")
        var ended = OllamaChat.feedStream(OllamaChat.newStream(),
                                          head + " ".repeat(OllamaChat.MAX_BUFFERED_CHARS + 1) + "\n" + chunk("late"), false)
        compare(ended.error, "too-long")
        compare(ended.content, "kept")
        // Nothing more is read after it.
        compare(OllamaChat.feedStream(ended, open + "\n" + chunk("z"), true).content, "kept")
    }

    function test_errorReplyDetail() {
        compare(OllamaChat.MAX_ERROR_REPLY_CHARS, 65536)
        compare(OllamaChat.errorReplyDetail("{\"error\":\"model runner stopped\"}"), "model runner stopped")
        compare(OllamaChat.errorReplyDetail("<html>502</html>"), "")
        compare(OllamaChat.errorReplyDetail(""), "")
        compare(OllamaChat.errorReplyDetail(null), "")
        compare(OllamaChat.errorReplyDetail(42), "")
        var padded = "{\"error\":\"boom\"}" + " ".repeat(OllamaChat.MAX_ERROR_REPLY_CHARS)
        compare(OllamaChat.errorReplyDetail(padded), "")
        var fits = "{\"error\":\"boom\"}"
        fits += " ".repeat(OllamaChat.MAX_ERROR_REPLY_CHARS - fits.length)
        compare(OllamaChat.errorReplyDetail(fits), "boom")
    }

    function test_tooLarge() {
        verify(OllamaChat.tooLarge("abcd", 3))
        verify(!OllamaChat.tooLarge("abc", 3))
        verify(!OllamaChat.tooLarge(null, 0))
        verify(!OllamaChat.tooLarge(undefined, 0))
        verify(!OllamaChat.tooLarge(["abcd"], 1))
    }

    function test_feedStreamShrunkOrOddBody() {
        var state = OllamaChat.feedStream(OllamaChat.newStream(), chunk("abc"), false)
        // abort() empties responseText; the kept reply must stay.
        var after = OllamaChat.feedStream(state, "", true)
        compare(after.content, "abc")
        compare(after.error, "")
        compare(OllamaChat.feedStream(state, undefined, true).content, "abc")
        compare(OllamaChat.feedStream(null, chunk("q"), false).content, "q")
        compare(OllamaChat.feedStream({ offset: -5, content: 7 }, chunk("q"), false).content, "q")
    }

    // --- failures and error text ---------------------------------------------

    function test_classifyFailure() {
        compare(OllamaChat.classifyFailure(0), "not-running")
        compare(OllamaChat.classifyFailure(403), "forbidden")
        compare(OllamaChat.classifyFailure(404), "model-missing")
        compare(OllamaChat.classifyFailure(500), "server-error")
        compare(OllamaChat.classifyFailure(503), "server-error")
        compare(OllamaChat.classifyFailure(400), "unexpected")
        compare(OllamaChat.classifyFailure(307), "unexpected")
        compare(OllamaChat.classifyFailure(200), "unexpected")
        compare(OllamaChat.classifyFailure(undefined), "unexpected")
        compare(OllamaChat.classifyFailure("500"), "unexpected")
    }

    function test_serverErrorText() {
        compare(OllamaChat.serverErrorText("model \"x\" not found, try pulling it first"),
                "model \"x\" not found, try pulling it first")
        compare(OllamaChat.serverErrorText("<img src=http://127.0.0.1:9/x>&amp;"),
                "img src=http://127.0.0.1:9/xamp;")
        compare(OllamaChat.serverErrorText("a\nb\r\tc\u0000d\u007fe\u009bf"), "a b c d e f")
        compare(OllamaChat.serverErrorText("‮evil⁦x‏"), "evil x")
        compare(OllamaChat.serverErrorText("   "), "")
        compare(OllamaChat.serverErrorText("y".repeat(1000)).length, 300)
        compare(OllamaChat.serverErrorText(undefined), "")
        compare(OllamaChat.serverErrorText({ error: "x" }), "")
        compare(OllamaChat.serverErrorText(500), "")
    }

    // --- segments ------------------------------------------------------------

    function test_segmentsPlain() {
        compare(OllamaChat.segments("just text\nsecond line"),
                [{ kind: "text", text: "just text\nsecond line", lang: "" }])
        compare(OllamaChat.segments(""), [])
        compare(OllamaChat.segments(undefined), [])
        compare(OllamaChat.segments(5), [])
        // Inline triple backticks are not a fence.
        compare(OllamaChat.segments("use ```x``` here"),
                [{ kind: "text", text: "use ```x``` here", lang: "" }])
    }

    function test_segmentsFences() {
        var text = "Before\n```python\nprint(1)\n\nprint(2)\n```\nAfter\n```\nraw <b>\n```"
        compare(OllamaChat.segments(text), [
            { kind: "text", text: "Before", lang: "" },
            { kind: "code", text: "print(1)\n\nprint(2)", lang: "python" },
            { kind: "text", text: "After", lang: "" },
            { kind: "code", text: "raw <b>", lang: "" }
        ])
        compare(OllamaChat.segments("```js\n```"), [{ kind: "code", text: "", lang: "js" }])
        compare(OllamaChat.segments("  ```c++\nx\n  ```  \n"),
                [{ kind: "code", text: "x", lang: "c++" }])
        compare(OllamaChat.segments("````\nx\n````"), [{ kind: "code", text: "x", lang: "" }])
        compare(OllamaChat.segments("```\r\nx\r\n```\r\n"), [{ kind: "code", text: "x\r", lang: "" }])
    }

    function test_segmentsUnterminatedFence() {
        compare(OllamaChat.segments("Here:\n```bash\necho hi\nls"), [
            { kind: "text", text: "Here:", lang: "" },
            { kind: "code", text: "echo hi\nls", lang: "bash" }
        ])
        compare(OllamaChat.segments("Here:\n```"), [
            { kind: "text", text: "Here:", lang: "" },
            { kind: "code", text: "", lang: "" }
        ])
        // A fence with trailing words inside code is content, not a close.
        compare(OllamaChat.segments("```\na\n```js\nb"),
                [{ kind: "code", text: "a\n```js\nb", lang: "" }])
    }

    function test_segmentsLang() {
        var good = ["c#", "c++", "objective-c", "x.y", "A1", "a".repeat(20)]
        for (var index = 0; index < good.length; index++)
            compare(OllamaChat.segments("```" + good[index] + "\nx\n```")[0].lang, good[index])
        var bad = ["a".repeat(21), "<script>", "py thon", "js{1}", "\"x\"", "a/b", "&amp"]
        for (index = 0; index < bad.length; index++)
            compare(OllamaChat.segments("```" + bad[index] + "\nx\n```")[0].lang, "", bad[index])
        compare(OllamaChat.segments("``` python \nx\n```")[0].lang, "python")
    }

    function test_segmentsDropsBlankText() {
        compare(OllamaChat.segments("```\na\n```\n\n   \n```\nb\n```"), [
            { kind: "code", text: "a", lang: "" },
            { kind: "code", text: "b", lang: "" }
        ])
    }

    // --- port owner ----------------------------------------------------------

    function test_ownerCommand() {
        compare(OllamaChat.ownerCommand(11434, 3, 12),
                "env HEARTHWIRE_RUN=3 HEARTHWIRE_APPLET=12 python3 -P -m hearthwire --port-owner 11434")
        compare(OllamaChat.ownerCommand(1, 0, 0),
                "env HEARTHWIRE_RUN=0 HEARTHWIRE_APPLET=0 python3 -P -m hearthwire --port-owner 1")
        compare(OllamaChat.ownerCommand(65535, 2147483648, 2147483648),
                "env HEARTHWIRE_RUN=2147483648 HEARTHWIRE_APPLET=2147483648"
                + " python3 -P -m hearthwire --port-owner 65535")
    }

    function test_ownerCommandRejects() {
        var bad = [
            [0, 1, 1], [65536, 1, 1], [-1, 1, 1], [11434.5, 1, 1], ["11434", 1, 1],
            [NaN, 1, 1], [Infinity, 1, 1], [null, 1, 1], [undefined, 1, 1],
            [11434, -1, 1], [11434, 1.5, 1], [11434, "1", 1], [11434, 2147483649, 1],
            [11434, 1, -1], [11434, 1, "; rm -rf ~"], [11434, 1, undefined], [11434, undefined, 1]
        ]
        for (var index = 0; index < bad.length; index++)
            compare(OllamaChat.ownerCommand(bad[index][0], bad[index][1], bad[index][2]), "",
                    JSON.stringify(bad[index]))
    }

    function test_parseOwnerReply() {
        var owners = ["none", "self", "system", "other"]
        for (var index = 0; index < owners.length; index++)
            compare(OllamaChat.parseOwnerReply(0, '{"ok":true,"owner":"' + owners[index] + '"}\n'),
                    { ok: true, owner: owners[index] })
        compare(OllamaChat.parseOwnerReply(0, '{"ok":false,"error":"unreadable"}'),
                { ok: false, error: "unreadable" })
    }

    function test_parseOwnerReplyRejects() {
        var bad = { ok: false, error: "bad-reply" }
        var cases = [
            [1, '{"ok":true,"owner":"self"}'],
            [2, ""],
            [undefined, '{"ok":true,"owner":"self"}'],
            [0, ""],
            [0, "self"],
            [0, "[]"],
            [0, '{"ok":true}'],
            [0, '{"ok":true,"owner":"root"}'],
            [0, '{"ok":true,"owner":"Self"}'],
            [0, '{"ok":"true","owner":"self"}'],
            [0, '{"ok":false,"error":"permission denied: /proc/net/tcp"}'],
            [0, '{"ok":false}'],
            [0, '{"ok":true,"owner":"self"} {"ok":true}'],
            [0, '{"ok":true,"owner":"self","pad":"' + "x".repeat(300) + '"}'],
            [0, undefined],
            [0, null]
        ]
        for (var index = 0; index < cases.length; index++)
            compare(OllamaChat.parseOwnerReply(cases[index][0], cases[index][1]), bad,
                    String(cases[index][1]))
    }

    function test_trusted() {
        compare(OllamaChat.trusted("self"), true)
        compare(OllamaChat.trusted("system"), true)
        compare(OllamaChat.trusted("none"), false)
        compare(OllamaChat.trusted("other"), false)
        compare(OllamaChat.trusted(""), false)
        compare(OllamaChat.trusted(undefined), false)
        compare(OllamaChat.trusted("SELF"), false)
    }

    function test_ownerProblem() {
        compare(OllamaChat.ownerProblem({ ok: true, owner: "self" }), "")
        compare(OllamaChat.ownerProblem({ ok: true, owner: "system" }), "")
        compare(OllamaChat.ownerProblem({ ok: true, owner: "none" }), "not-running")
        compare(OllamaChat.ownerProblem({ ok: true, owner: "other" }), "other")
        compare(OllamaChat.ownerProblem({ ok: true, owner: "SELF" }), "owner-unknown")
        compare(OllamaChat.ownerProblem({ ok: false, error: "unreadable" }), "owner-unknown")
        compare(OllamaChat.ownerProblem({ owner: "self" }), "owner-unknown")
        compare(OllamaChat.ownerProblem(null), "owner-unknown")
        compare(OllamaChat.ownerProblem(undefined), "owner-unknown")
    }

    // --- hidden characters (L3) ----------------------------------------------

    // Every range of HIDDEN_CHARS: [first, last] code points, both ends and
    // the middle checked.
    readonly property var hiddenRanges: [
        [0x0000, 0x0008], [0x000b, 0x001f], [0x007f, 0x009f], [0x00ad, 0x00ad],
        [0x034f, 0x034f], [0x061c, 0x061c], [0x115f, 0x1160], [0x17b4, 0x17b5],
        [0x180e, 0x180e], [0x200b, 0x200f], [0x2028, 0x2029], [0x202a, 0x202e],
        [0x2060, 0x2064], [0x2066, 0x2069], [0x206a, 0x206f], [0x3164, 0x3164],
        [0xfe00, 0xfe0f], [0xfeff, 0xfeff], [0xffa0, 0xffa0], [0xfff9, 0xfffb],
        [0x1bca0, 0x1bca3], [0x1d173, 0x1d17a], [0xe0000, 0xe007f], [0xe0100, 0xe01ef]
    ]

    function marker(point) {
        var code = point.toString(16).toUpperCase()
        while (code.length < 4)
            code = "0" + code
        return "⟦U+" + code + "⟧"
    }

    function test_revealHiddenMarksEveryHiddenCharacter() {
        for (var range = 0; range < hiddenRanges.length; range++) {
            var first = hiddenRanges[range][0]
            var last = hiddenRanges[range][1]
            var points = [first, Math.floor((first + last) / 2), last]
            for (var index = 0; index < points.length; index++) {
                var text = "a" + String.fromCodePoint(points[index]) + "b"
                compare(OllamaChat.revealHidden(text), "a" + marker(points[index]) + "b")
                verify(OllamaChat.hasHidden(text), marker(points[index]))
                verify(!OllamaChat.hasHidden(OllamaChat.revealHidden(text)))
            }
        }
    }

    function test_revealHiddenNamedControls() {
        // CR would act as Enter in a terminal, ESC starts escape sequences.
        compare(OllamaChat.revealHidden("ls\r\nrm -rf ~"), "ls⟦U+000D⟧\nrm -rf ~")
        compare(OllamaChat.revealHidden("\u001b[2Jok"), "⟦U+001B⟧[2Jok")
        compare(OllamaChat.revealHidden("a\u0085b c d"), "a⟦U+0085⟧b⟦U+2028⟧c⟦U+2029⟧d")
        compare(OllamaChat.revealHidden("pass­word"), "pass⟦U+00AD⟧word")
        // Tag characters spell hidden ASCII ("hi"); each one is marked.
        compare(OllamaChat.revealHidden("x\u{e0068}\u{e0069}\u{e007f}"),
                "x⟦U+E0068⟧⟦U+E0069⟧⟦U+E007F⟧")
        compare(OllamaChat.revealHidden("e\u{e0100}"), "e⟦U+E0100⟧")
    }

    function test_revealHiddenKeepsTabAndNewline() {
        compare(OllamaChat.revealHidden("a\tb\nc"), "a\tb\nc")
        verify(!OllamaChat.hasHidden("a\tb\nc"))
        // Next to the hidden ranges, but visible.
        var visible = [0x0020, 0x00a0, 0x00ac, 0x00ae, 0x034e, 0x0350, 0x200a, 0x2010,
                       0x2065, 0x2070, 0xfdff, 0xfe10, 0xfffc, 0x1bc9f, 0x1bca4, 0x1d172,
                       0x1d17b, 0xe0080, 0xe01f0]
        for (var index = 0; index < visible.length; index++) {
            var text = "a" + String.fromCodePoint(visible[index]) + "b"
            compare(OllamaChat.revealHidden(text), text, marker(visible[index]))
        }
    }

    // One U+FE0F right after an emoji only asks for its colour form.
    function test_revealHiddenAllowsOneEmojiVariationSelector() {
        compare(OllamaChat.revealHidden("I ❤️ it ✔️ 😀️"), "I ❤️ it ✔️ 😀️")
        verify(!OllamaChat.hasHidden("❤️"))
        compare(OllamaChat.revealHidden("❤️️"), "❤️⟦U+FE0F⟧")
        compare(OllamaChat.revealHidden("a️b"), "a⟦U+FE0F⟧b")
        compare(OllamaChat.revealHidden("️"), "⟦U+FE0F⟧")
        compare(OllamaChat.revealHidden("❤︎"), "❤⟦U+FE0E⟧")
        verify(OllamaChat.hasHidden("1️"))
    }

    function test_revealHiddenTrojanSource() {
        var line = "rm -rf ./build ‮⁦# safe⁩⁦ ~"
        compare(OllamaChat.revealHidden(line), "rm -rf ./build ⟦U+202E⟧⟦U+2066⟧# safe⟦U+2069⟧⟦U+2066⟧ ~")
        compare(OllamaChat.revealHidden("invoice‮fdp.exe"), "invoice⟦U+202E⟧fdp.exe")
        // Called twice in a row it still only marks, never removes.
        compare(OllamaChat.revealHidden(OllamaChat.revealHidden("x​y")), "x⟦U+200B⟧y")
    }

    function test_revealHiddenKeepsOrdinaryText() {
        var text = "Hello é ü 日本 مرحبا שלום\n\t<b>&amp;</b>   😀"
        compare(OllamaChat.revealHidden(text), text)
        verify(!OllamaChat.hasHidden(text))
        compare(OllamaChat.revealHidden(""), "")
        compare(OllamaChat.revealHidden(undefined), "")
        compare(OllamaChat.revealHidden(42), "")
        verify(!OllamaChat.hasHidden(null))
    }

    // --- formatting ----------------------------------------------------------

    function plain(text) {
        return [{ text: text, bold: false, italic: false, code: false }]
    }

    function test_blocksEveryKind() {
        var text = "# Title\n## Sub ##\n### Small\nIntro **bold** and *it*.\nsecond line\n\n"
            + "- one\n* two\n+ three\n\n1. first\n2. second\n10. tenth\n\n```js\nx = 1\n```\nend"
        compare(OllamaChat.blocks(text), [
            { kind: "heading", spans: plain("Title"), level: 1 },
            { kind: "heading", spans: plain("Sub"), level: 2 },
            { kind: "heading", spans: plain("Small"), level: 3 },
            { kind: "paragraph", spans: [
                { text: "Intro ", bold: false, italic: false, code: false },
                { text: "bold", bold: true, italic: false, code: false },
                { text: " and ", bold: false, italic: false, code: false },
                { text: "it", bold: false, italic: true, code: false },
                { text: ".\nsecond line", bold: false, italic: false, code: false }] },
            { kind: "bullet", spans: plain("one"), depth: 0 },
            { kind: "bullet", spans: plain("two"), depth: 0 },
            { kind: "bullet", spans: plain("three"), depth: 0 },
            { kind: "number", spans: plain("first"), n: 1 },
            { kind: "number", spans: plain("second"), n: 2 },
            { kind: "number", spans: plain("tenth"), n: 10 },
            { kind: "code", text: "x = 1", lang: "js" },
            { kind: "paragraph", spans: plain("end") }
        ])
        compare(OllamaChat.blocks(""), [])
        compare(OllamaChat.blocks(undefined), [])
        compare(OllamaChat.blocks("  \n\n "), [])
    }

    function test_blocksNotRecognised() {
        // Four hashes, no space, a rule: literal paragraphs.
        var literal = ["#### Four", "#Tight", "---", "* * *", "-no space", "1)x", "| a | b |\n|---|---|"]
        for (var index = 0; index < literal.length; index++)
            compare(OllamaChat.blocks(literal[index]), [{ kind: "paragraph", spans: plain(literal[index]) }],
                    literal[index])
    }

    function test_blocksListNesting() {
        var depths = OllamaChat.blocks("- a\n  - b\n    - c\n      - d\n        - e\n  - f\n- g")
            .map(function (block) { return block.depth })
        compare(depths, [0, 1, 2, 2, 2, 1, 0])
        // Four-space indents nest the same way; tabs count as four.
        compare(OllamaChat.blocks("* a\n    * b\n\t\t* c").map(function (b) { return b.depth }), [0, 1, 2])
        // A line right after an item joins it; after a blank line it is a paragraph.
        compare(OllamaChat.blocks("- a\n  more\n\nafter"), [
            { kind: "bullet", spans: plain("a\nmore"), depth: 0 },
            { kind: "paragraph", spans: plain("after") }
        ])
        // A heading line ends a paragraph.
        compare(OllamaChat.blocks("text\n# H").map(function (b) { return b.kind }), ["paragraph", "heading"])
    }

    function test_literalLinksImagesAndHtml() {
        var cases = [
            "[t](http://127.0.0.1:9/)",
            "![x](http://127.0.0.1:9/y.png)",
            "<img src=\"http://127.0.0.1:9/x\">",
            "<b>bold</b> &amp; &lt;i&gt;",
            "<http://127.0.0.1:9/auto>",
            "see http://127.0.0.1:9/plain"
        ]
        for (var index = 0; index < cases.length; index++) {
            var shown = OllamaChat.blocks(cases[index])
            compare(shown, [{ kind: "paragraph", spans: plain(cases[index]) }], cases[index])
            verify(!OllamaChat.isStyled(shown[0].spans))
        }
        // Inside emphasis, the link text still stays literal.
        compare(OllamaChat.spans("**[t](http://x/)**"),
                [{ text: "[t](http://x/)", bold: true, italic: false, code: false }])
    }

    function test_spansEmphasis() {
        compare(OllamaChat.spans("__b__ _i_ `c d`"), [
            { text: "b", bold: true, italic: false, code: false },
            { text: " ", bold: false, italic: false, code: false },
            { text: "i", bold: false, italic: true, code: false },
            { text: " ", bold: false, italic: false, code: false },
            { text: "c d", bold: false, italic: false, code: true }
        ])
        compare(OllamaChat.spans("**bold *both* bold**"), [
            { text: "bold ", bold: true, italic: false, code: false },
            { text: "both", bold: true, italic: true, code: false },
            { text: " bold", bold: true, italic: false, code: false }
        ])
        // Inline code keeps its markers' insides as they are.
        compare(OllamaChat.spans("`**x**`"), [{ text: "**x**", bold: false, italic: false, code: true }])
        // snake_case, a lone star, "2 * 3 * 4" and spaced marks stay literal.
        var literal = ["snake_case_name", "a * b", "2 * 3 * 4", "** spaced **", "_ x _", "a_b_c"]
        for (var index = 0; index < literal.length; index++)
            compare(OllamaChat.spans(literal[index]), plain(literal[index]), literal[index])
        compare(OllamaChat.spans(""), [])
        compare(OllamaChat.spans(null), [])
    }

    function test_unterminatedMarksStayLiteral() {
        compare(OllamaChat.spans("**never closed"), plain("**never closed"))
        compare(OllamaChat.spans("*open and `tick"), plain("*open and `tick"))
        compare(OllamaChat.spans("``"), plain("``"))
        compare(OllamaChat.spans("a **b** c **d"), [
            { text: "a ", bold: false, italic: false, code: false },
            { text: "b", bold: true, italic: false, code: false },
            { text: " c **d", bold: false, italic: false, code: false }
        ])
        // Streaming: half a bold stays literal until it closes.
        compare(OllamaChat.blocks("Use **bo"), [{ kind: "paragraph", spans: plain("Use **bo") }])
        // An unterminated fence is code to the end, markup and all.
        compare(OllamaChat.blocks("x\n```\n# not a heading\n**b**"), [
            { kind: "paragraph", spans: plain("x") },
            { kind: "code", text: "# not a heading\n**b**", lang: "" }
        ])
        // Many unclosed marks stay quick (linear).
        var many = new Array(1300).join("*a ")
        compare(OllamaChat.spans(many), plain(many))
    }

    function test_styledWordCap() {
        var words = []
        for (var index = 0; index < OllamaChat.MAX_STYLED_WORDS; index++)
            words.push(index === 0 ? "**w**" : "w")
        var atCap = words.join(" ")
        verify(OllamaChat.isStyled(OllamaChat.spans(atCap)))
        var over = atCap + " w"
        compare(OllamaChat.spans(over), plain(over))
        compare(OllamaChat.blocks("- " + over)[0].spans, plain(over))
        var long = "**" + "x".repeat(OllamaChat.MAX_STYLED_CHARS) + "**"
        compare(OllamaChat.spans(long), plain(long))
        compare(OllamaChat.MAX_STYLED_WORDS, 300)
    }

    function test_blocksRevealHidden() {
        var shown = OllamaChat.blocks("# A‮B\n- x​y\nok\u0007\n```\nrm ⁦z\n```")
        compare(OllamaChat.spansText(shown[0].spans), "A⟦U+202E⟧B")
        compare(OllamaChat.spansText(shown[1].spans), "x⟦U+200B⟧y\nok⟦U+0007⟧")
        compare(shown[2].text, "rm ⟦U+2066⟧z")
    }

    function test_flowWords() {
        var words = OllamaChat.flowWords(OllamaChat.spans("Say **hi**, then\n`run x`."))
        compare(words.map(function (w) { return w.br ? "|" : w.text + (w.space ? "_" : "") }),
                ["Say_", "hi", ",_", "then", "|", "run_", "x", "."])
        compare(words[1].bold, true)
        compare(words[5].code, true)
        compare(words[7].code, false)
        compare(OllamaChat.flowWords([]), [])
        compare(OllamaChat.flowWords(null), [])
        compare(OllamaChat.spansText(OllamaChat.spans("a **b** `c`")), "a b c")
        verify(!OllamaChat.isStyled(plain("x")))
        verify(!OllamaChat.isStyled(null))
    }

    // --- conversation --------------------------------------------------------

    function test_lastTurn() {
        var u = { author: "user" }
        var a = { author: "assistant" }
        compare(OllamaChat.lastTurn([u, a, u, a]), { userIndex: 2, assistantIndex: 3 })
        compare(OllamaChat.lastTurn([u, a, u]), { userIndex: 2, assistantIndex: -1 })
        compare(OllamaChat.lastTurn([a]), { userIndex: -1, assistantIndex: 0 })
        compare(OllamaChat.lastTurn([u, a, a]), { userIndex: -1, assistantIndex: 2 })
        var none = { userIndex: -1, assistantIndex: -1 }
        compare(OllamaChat.lastTurn([]), none)
        compare(OllamaChat.lastTurn(null), none)
        compare(OllamaChat.lastTurn("ua"), none)
        compare(OllamaChat.lastTurn([u, null]), none)
        compare(OllamaChat.lastTurn([u, { author: "system" }]), none)
    }

    function test_dropText() {
        compare(OllamaChat.dropText("hello", ""), { ok: true, text: "hello" })
        compare(OllamaChat.dropText("dropped", "typed\n\n "), { ok: true, text: "typed\n\ndropped" })
        compare(OllamaChat.dropText("dropped", "   "), { ok: true, text: "dropped" })
        compare(OllamaChat.dropText("dropped", undefined), { ok: true, text: "dropped" })
        // Controls go, tab and line feed stay; CRLF becomes LF.
        compare(OllamaChat.dropText("a\u0007b\r\nc\td\u001b[31m\u0085", ""), { ok: true, text: "ab\nc\td[31m" })
        compare(OllamaChat.dropText("a\u0000b", ""), { ok: false, error: "not-text" })
        compare(OllamaChat.dropText(5, ""), { ok: false, error: "not-text" })
        compare(OllamaChat.dropText(null, ""), { ok: false, error: "not-text" })
        compare(OllamaChat.dropText("", "x"), { ok: false, error: "empty" })
        compare(OllamaChat.dropText(" \n\u0007\t", ""), { ok: false, error: "empty" })
        var max = OllamaChat.MAX_PROMPT_CHARS
        compare(OllamaChat.dropText("x".repeat(max), "").ok, true)
        compare(OllamaChat.dropText("x".repeat(max + 1), ""), { ok: false, error: "too-long" })
        // Typed text plus the drop and the blank line between them count.
        compare(OllamaChat.dropText("x".repeat(max - 4), "ab").ok, true)
        compare(OllamaChat.dropText("x".repeat(max - 3), "ab"), { ok: false, error: "too-long" })
    }

    function test_withPersonaReminder() {
        var reminder = OllamaChat.PERSONA_REMINDER
        compare(reminder, "(Stay in character as described in your instructions.)\n\n")
        var messages = [{ role: "user", content: "a" }, { role: "assistant", content: "b" },
                        { role: "user", content: "c" }]
        var copy = OllamaChat.withPersonaReminder(messages)
        compare(copy, [{ role: "user", content: "a" }, { role: "assistant", content: "b" },
                       { role: "user", content: reminder + "c" }])
        // The input is never changed.
        compare(messages[2].content, "c")
        // The last user message, even when a reply follows it.
        compare(OllamaChat.withPersonaReminder([{ role: "user", content: "q" }, { role: "assistant", content: "r" }])[0].content,
                reminder + "q")
        compare(OllamaChat.withPersonaReminder([]), [])
        compare(OllamaChat.withPersonaReminder(null), [])
        compare(OllamaChat.withPersonaReminder([{ role: "assistant", content: "x" }]), [{ role: "assistant", content: "x" }])
        // A prompt at the limit is still sent with the reminder.
        var full = "x".repeat(OllamaChat.MAX_PROMPT_CHARS)
        var body = OllamaChat.chatRequestBody("m", [{ role: "user", content: full }], "p")
        compare(JSON.parse(body).messages[1].content, reminder + full)
    }
}
