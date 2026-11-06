import QtQuick
import QtTest
import org.kde.kirigami as Kirigami
import "../../plasmoid/contents/ui"
import "../../plasmoid/contents/ui/OllamaChat.js" as OllamaChat

// OllamaChatView with a fake XMLHttpRequest (createRequest) and a fake port
// owner helper (runOwnerCheck). Nothing here opens a socket.
TestCase {
    id: testCase
    name: "OllamaChatView"
    width: 500
    height: 500
    visible: true
    when: windowShown

    // Plasma injects i18n(); a stand-in that fills %1.
    function i18n(text, arg) {
        return arg === undefined ? text : text.replace("%1", String(arg))
    }

    property var requests: []
    property var ownerCommands: []
    // What the fake helper answers; null leaves the check pending.
    property var ownerReply: ({ ok: true, owner: "system" })
    property int escapeAtParent: 0

    function newFake() {
        var fake = {
            readyState: 0,
            status: 0,
            responseText: "",
            // Like Qt: "" until readyState 3, then the address that answered.
            responseURL: "",
            // Set by a test: where the fake was redirected to.
            redirectedTo: "",
            method: "",
            url: "",
            headers: [],
            body: null,
            aborted: 0,
            onreadystatechange: null,
            open: function (method, url) {
                fake.method = method
                fake.url = url
                fake.readyState = 1
            },
            setRequestHeader: function (name, value) {
                fake.headers.push([name, value])
            },
            send: function (body) {
                fake.body = body === undefined ? null : body
                testCase.requests.push(fake)
            },
            // Like Qt 6.12: aborts, fires readyState 4, then throws.
            abort: function () {
                fake.aborted += 1
                fake.readyState = 4
                fake.status = 0
                fake.responseText = ""
                if (fake.onreadystatechange)
                    fake.onreadystatechange()
                throw new Error("Invalid state")
            },
            answered: function () {
                fake.responseURL = fake.redirectedTo !== "" ? fake.redirectedTo : fake.url
            },
            chunk: function (text) {
                fake.answered()
                fake.status = 200
                fake.readyState = 3
                fake.responseText += text
                if (fake.onreadystatechange)
                    fake.onreadystatechange()
            },
            finish: function (status, text) {
                fake.answered()
                fake.status = status
                fake.readyState = 4
                if (text !== undefined)
                    fake.responseText += text
                if (fake.onreadystatechange)
                    fake.onreadystatechange()
            }
        }
        return fake
    }

    function ownerAsked(view, command) {
        testCase.ownerCommands.push(command)
        if (testCase.ownerReply !== null)
            view.ownerDone(command, testCase.ownerReply)
    }

    Component {
        id: wrapperComponent
        FocusScope {
            id: wrapper
            property alias view: chat
            property bool shown: false
            property bool siteOn: true
            anchors.fill: parent
            Keys.onEscapePressed: testCase.escapeAtParent += 1

            OllamaChatView {
                id: chat
                anchors.fill: parent
                focus: true
                current: wrapper.shown
                siteEnabled: wrapper.siteOn
                appletId: 7
                // Every chunk on screen at once; test_renderIsThrottled covers the default.
                renderInterval: 0
                createRequest: function () { return testCase.newFake() }
                runOwnerCheck: function (command) { testCase.ownerAsked(chat, command) }
            }
        }
    }

    // Like the popup: a header with the tabs above the view.
    Component {
        id: headedComponent
        Column {
            id: headed
            property alias view: chat
            property alias header: tabs
            property bool shown: false
            anchors.fill: parent

            Rectangle {
                id: tabs
                width: parent.width
                height: 60
                color: "#ff00ff"
            }
            OllamaChatView {
                id: chat
                width: parent.width
                height: parent.height - tabs.height
                current: headed.shown
                siteEnabled: true
                appletId: 7
                renderInterval: 0
                createRequest: function () { return testCase.newFake() }
                runOwnerCheck: function (command) { testCase.ownerAsked(chat, command) }
            }
        }
    }

    function init() {
        testCase.requests = []
        testCase.ownerCommands = []
        testCase.ownerReply = { ok: true, owner: "system" }
        testCase.escapeAtParent = 0
    }

    function make(properties, component) {
        var wrapper = createTemporaryObject(component || wrapperComponent, testCase, properties || {})
        verify(wrapper !== null)
        return wrapper
    }

    function tags(models) {
        return JSON.stringify({ models: models })
    }

    property var defaultModels: [
        { name: "llama3:latest", details: { parameter_size: "8.0B", family: "llama" },
          capabilities: ["completion"] },
        { name: "qwen3:8b", capabilities: ["completion", "thinking"] },
        { name: "gpt-oss:120b-cloud", remote_host: "https://ollama.com:443" },
        { name: "nomic-embed-text:latest", capabilities: ["embedding"] }
    ]

    // Shown → owner check → version → tags, answered with models.
    function ready(models, component) {
        var wrapper = make({ shown: true }, component)
        var view = wrapper.view
        compare(testCase.requests.length, 1)
        compare(testCase.requests[0].url, "http://127.0.0.1:11434/api/version")
        testCase.requests[0].finish(200, "{\"version\":\"0.40.13\"}")
        compare(testCase.requests.length, 2)
        compare(testCase.requests[1].url, "http://127.0.0.1:11434/api/tags")
        testCase.requests[1].finish(200, tags(models === undefined ? testCase.defaultModels : models))
        return wrapper
    }

    function input(view) {
        var field = findChild(view, "ollamaInput")
        verify(field !== null)
        return field
    }

    // Types text and sends; returns the chat request.
    function sendText(view, text) {
        input(view).text = text
        verify(view.canSend)
        var before = testCase.requests.length
        view.send()
        compare(testCase.requests.length, before + 1)
        var request = testCase.requests[testCase.requests.length - 1]
        compare(request.method, "POST")
        compare(request.url, "http://127.0.0.1:11434/api/chat")
        return request
    }

    function line(object) {
        return JSON.stringify(object) + "\n"
    }

    function piece(content) {
        return line({ model: "llama3:latest", message: { role: "assistant", content: content }, done: false })
    }

    // --- when anything is contacted ------------------------------------------

    function test_nothingUntilShownAndEnabled() {
        var wrapper = make({ shown: false, siteOn: true })
        wait(30)
        compare(testCase.ownerCommands.length, 0)
        compare(testCase.requests.length, 0)
        wrapper.siteOn = false
        wrapper.shown = true
        wait(30)
        compare(testCase.ownerCommands.length, 0)
        compare(testCase.requests.length, 0)
        compare(wrapper.view.listState, "idle")
        wrapper.siteOn = true
        compare(testCase.ownerCommands.length, 1)
    }

    function test_loadOrderOwnerVersionTags() {
        testCase.ownerReply = null
        var wrapper = make({ shown: true })
        var view = wrapper.view
        compare(testCase.ownerCommands.length, 1)
        verify(/^env HEARTHWIRE_RUN=\d+ HEARTHWIRE_APPLET=7 python3 -P -m hearthwire --port-owner 11434$/
               .test(testCase.ownerCommands[0]), testCase.ownerCommands[0])
        // Nothing goes to the port before the owner is known.
        compare(testCase.requests.length, 0)
        compare(view.listState, "loading")
        view.ownerDone(testCase.ownerCommands[0], { ok: true, owner: "self" })
        compare(testCase.requests.length, 1)
        compare(testCase.requests[0].method, "GET")
        compare(testCase.requests[0].url, "http://127.0.0.1:11434/api/version")
        compare(testCase.requests[0].body, null)
        testCase.requests[0].finish(200, "{\"version\":\"0.40.13\"}")
        compare(testCase.requests[1].method, "GET")
        compare(testCase.requests[1].url, "http://127.0.0.1:11434/api/tags")
        testCase.requests[1].finish(200, tags(testCase.defaultModels))
        compare(view.listState, "ready")
        compare(view.modelList.map(function (m) { return m.name }), ["llama3:latest", "qwen3:8b"])
        compare(view.hiddenRemote, 1)
        compare(view.modelName, "llama3:latest")
        compare(view.problem, "")
        // GETs carry no headers.
        compare(testCase.requests[0].headers.length, 0)
        compare(testCase.requests[1].headers.length, 0)
    }

    function test_lateOwnerReplyIsIgnored() {
        testCase.ownerReply = null
        var wrapper = make({ shown: true })
        var view = wrapper.view
        var first = testCase.ownerCommands[0]
        view.reloadModels()
        // Busy: no second check while one runs.
        compare(testCase.ownerCommands.length, 1)
        view.cancelOwnerCheck()
        view.load()
        compare(testCase.ownerCommands.length, 2)
        verify(testCase.ownerCommands[1] !== first)
        view.ownerDone(first, { ok: true, owner: "system" })
        compare(testCase.requests.length, 0)
        view.ownerDone(testCase.ownerCommands[1], { ok: true, owner: "system" })
        compare(testCase.requests.length, 1)
    }

    function test_untrustedOwnerBlocksEverything_data() {
        return [
            { tag: "none", reply: { ok: true, owner: "none" }, problem: "not-running" },
            { tag: "other", reply: { ok: true, owner: "other" }, problem: "other" },
            { tag: "unreadable", reply: { ok: false, error: "unreadable" }, problem: "owner-unknown" },
            { tag: "bad-reply", reply: { ok: false, error: "bad-reply" }, problem: "owner-unknown" },
            { tag: "odd-owner", reply: { ok: true, owner: "root" }, problem: "owner-unknown" },
            { tag: "null", reply: null, problem: "owner-unknown" }
        ]
    }

    function test_untrustedOwnerBlocksEverything(data) {
        testCase.ownerReply = null
        var wrapper = make({ shown: true })
        var view = wrapper.view
        view.ownerDone(testCase.ownerCommands[0], data.reply)
        compare(testCase.requests.length, 0)
        compare(view.listState, "failed")
        compare(view.problem, data.problem)
        input(view).text = "hello"
        verify(!view.canSend)
        view.send()
        compare(testCase.requests.length, 0)
        compare(findChild(view, "retryButton").visible, true)
        if (data.problem === "other" || data.problem === "owner-unknown")
            verify(findChild(view, "problemText").text.indexOf("port 11434") >= 0)
        if (data.problem === "not-running")
            compare(findChild(view, "problemHint").text, "systemctl start ollama   (or run: ollama serve)")
    }

    function test_ownerCheckTimesOutClosed() {
        testCase.ownerReply = null
        var wrapper = make({ shown: false })
        var view = wrapper.view
        view.ownerTimeout = 30
        wrapper.shown = true
        tryCompare(view, "problem", "owner-unknown")
        compare(view.listState, "failed")
        compare(testCase.requests.length, 0)
    }

    function test_retryAfterFailure() {
        testCase.ownerReply = { ok: true, owner: "none" }
        var wrapper = make({ shown: true })
        var view = wrapper.view
        compare(view.problem, "not-running")
        testCase.ownerReply = { ok: true, owner: "system" }
        findChild(view, "retryButton").clicked()
        compare(testCase.ownerCommands.length, 2)
        compare(testCase.requests.length, 1)
        compare(view.listState, "loading")
    }

    function test_notOllama_data() {
        return [
            { tag: "plain text", status: 200, text: "Ollama is running" },
            { tag: "html", status: 200, text: "<html><body>hi</body></html>" },
            { tag: "no version", status: 200, text: "{\"name\":\"x\"}" },
            { tag: "404", status: 404, text: "" }
        ]
    }

    function test_notOllama(data) {
        var wrapper = make({ shown: true })
        var view = wrapper.view
        testCase.requests[0].finish(data.status, data.text)
        compare(testCase.requests.length, 1)
        compare(view.problem, "not-ollama")
        compare(view.listState, "failed")
        verify(!view.canSend)
    }

    function test_versionConnectionRefused() {
        var wrapper = make({ shown: true })
        testCase.requests[0].finish(0, "")
        compare(wrapper.view.problem, "not-running")
    }

    function test_forbidden() {
        var wrapper = make({ shown: true })
        testCase.requests[0].finish(403, "")
        compare(wrapper.view.problem, "forbidden")
    }

    function test_noModels() {
        var wrapper = ready([{ name: "kimi:cloud" }, { name: "embed:latest", capabilities: ["embedding"] }])
        var view = wrapper.view
        compare(view.listState, "ready")
        compare(view.modelList.length, 0)
        compare(view.problem, "no-models")
        compare(view.hiddenRemote, 1)
        compare(findChild(view, "problemHint").text, "ollama pull llama3")
        input(view).text = "hello"
        verify(!view.canSend)
        compare(findChild(view, "retryButton").text, "Reload models")
    }

    function test_probeTimeout() {
        var wrapper = make({ shown: false })
        var view = wrapper.view
        view.probeTimeout = 30
        wrapper.shown = true
        compare(testCase.requests.length, 1)
        tryCompare(view, "problem", "timeout")
        compare(testCase.requests[0].aborted, 1)
        // A late answer of the dropped request changes nothing.
        testCase.requests[0].onreadystatechange()
        compare(testCase.requests.length, 1)
    }

    // Qt follows redirects without showing them; only responseURL tells.
    function test_redirectedLoadIsRefused_data() {
        return [
            { tag: "version, other port", step: 0, to: "http://127.0.0.1:9999/api/version" },
            { tag: "version, other host", step: 0, to: "http://localhost:11434/api/version" },
            { tag: "version, first chunk", step: 0, to: "http://127.0.0.1:9999/api/version", chunk: true },
            { tag: "tags, other port", step: 1, to: "http://127.0.0.1:9999/api/tags" },
            { tag: "tags, other path", step: 1, to: "http://127.0.0.1:11434/api/version" }
        ]
    }

    function test_redirectedLoadIsRefused(data) {
        var wrapper = make({ shown: true })
        var view = wrapper.view
        if (data.step === 1)
            testCase.requests[0].finish(200, "{\"version\":\"0.40.13\"}")
        var request = testCase.requests[data.step]
        request.redirectedTo = data.to
        var reply = data.step === 0 ? "{\"version\":\"0.40.13\"}" : tags(testCase.defaultModels)
        if (data.chunk)
            request.chunk(reply)
        else
            request.finish(200, reply)
        compare(request.aborted, 1)
        compare(testCase.requests.length, data.step + 1)
        compare(view.listState, "failed")
        compare(view.problem, "not-ollama")
        compare(view.modelList.length, 0)
        verify(!view.canSend)
        // Later events of the dropped request change nothing.
        request.finish(200, "")
        compare(testCase.requests.length, data.step + 1)
        compare(view.problem, "not-ollama")
    }

    // --- sending ----------------------------------------------------------------

    function test_sendStreamsAndKeepsHistory() {
        var wrapper = ready()
        var view = wrapper.view
        var checks = testCase.ownerCommands.length
        var request = sendText(view, "Hi <there>")
        // Every send checks the owner again first.
        compare(testCase.ownerCommands.length, checks + 1)
        compare(request.headers, [["Content-Type", "application/json"]])
        compare(JSON.parse(request.body), {
            model: "llama3:latest",
            messages: [{ role: "user", content: "Hi <there>" }],
            stream: true
        })
        compare(input(view).text, "")
        verify(view.generating)
        compare(view.messages.count, 2)
        compare(view.messages.get(0).author, "user")
        compare(view.messages.get(0).body, "Hi <there>")
        compare(view.messages.get(1).phase, "waiting")

        // A line split across chunks is read once it is complete.
        var first = piece("Hel")
        request.chunk(first.slice(0, 10))
        compare(view.messages.get(1).body, "")
        request.chunk(first.slice(10))
        compare(view.messages.get(1).body, "Hel")
        compare(view.messages.get(1).phase, "streaming")
        request.chunk(piece("lo é"))
        compare(view.messages.get(1).body, "Hello é")
        request.chunk(line({ done: true, done_reason: "stop", message: { role: "assistant", content: "" } }))
        verify(!view.generating)
        compare(view.messages.get(1).phase, "done")
        compare(view.problem, "")
        // Events after done are ignored.
        request.chunk(piece(" more"))
        compare(view.messages.get(1).body, "Hello é")

        var second = sendText(view, "And?")
        compare(JSON.parse(second.body).messages, [
            { role: "user", content: "Hi <there>" },
            { role: "assistant", content: "Hello é" },
            { role: "user", content: "And?" }
        ])
    }

    function test_sendBlockedByOwnerKeepsPrompt_data() {
        return [
            { tag: "none", reply: { ok: true, owner: "none" }, problem: "not-running" },
            { tag: "other", reply: { ok: true, owner: "other" }, problem: "other" },
            { tag: "error", reply: { ok: false, error: "unreadable" }, problem: "owner-unknown" }
        ]
    }

    function test_sendBlockedByOwnerKeepsPrompt(data) {
        var wrapper = ready()
        var view = wrapper.view
        var before = testCase.requests.length
        input(view).text = "secret question"
        testCase.ownerReply = data.reply
        view.send()
        compare(testCase.requests.length, before)
        compare(view.messages.count, 0)
        compare(input(view).text, "secret question")
        compare(view.problem, data.problem)
        verify(!view.canSend)
    }

    function test_inputLockedWhileSendCheckRuns() {
        var wrapper = ready()
        var view = wrapper.view
        testCase.ownerReply = null
        input(view).text = "question"
        view.send()
        compare(view.checking, "send")
        verify(input(view).readOnly)
        // Stop cancels the check; nothing was sent.
        view.stop()
        compare(view.checking, "")
        verify(!input(view).readOnly)
        compare(input(view).text, "question")
        compare(testCase.requests.length, 2)
    }

    function test_stopHandlesThrowingAbortAndLateEvents() {
        var wrapper = ready()
        var view = wrapper.view
        var request = sendText(view, "Tell me a story")
        request.chunk(piece("Once upon"))
        view.stop()
        compare(request.aborted, 1)
        verify(!view.generating)
        compare(view.messages.get(1).body, "Once upon")
        compare(view.messages.get(1).phase, "stopped")
        request.chunk(piece(" a time"))
        compare(view.messages.get(1).body, "Once upon")
        compare(view.problem, "")
        verify(!findChild(view, "sendButton").stopping)
    }

    function test_stopBeforeAnyTextDropsEmptyReply() {
        var wrapper = ready()
        var view = wrapper.view
        sendText(view, "Hi")
        view.stop()
        compare(view.messages.count, 1)
        compare(view.messages.get(0).author, "user")
    }

    function test_renderIsThrottled() {
        var wrapper = ready()
        var view = wrapper.view
        view.renderInterval = 40
        var request = sendText(view, "Hi")
        request.chunk(piece("One"))
        request.chunk(piece(" two"))
        compare(view.messages.get(1).body, "")
        tryCompare(view.messages.get(1), "body", "One two")
        // Stop shows what arrived, at once.
        request.chunk(piece(" three"))
        view.stop()
        compare(view.messages.get(1).body, "One two three")
        compare(view.messages.get(1).phase, "stopped")
    }

    // Each read decodes the whole body again: chunks only schedule one.
    function test_streamIsReadOnTheTimer() {
        var wrapper = ready()
        var view = wrapper.view
        view.renderInterval = 40
        var request = sendText(view, "Hi")
        request.chunk(piece("One"))
        request.chunk(piece(" two"))
        compare(view.stream.content, "")
        compare(view.stream.offset, 0)
        tryVerify(function () { return view.stream.content === "One two" })
        compare(view.messages.get(1).body, "One two")
        // The end is read at once.
        request.chunk(piece(" three"))
        request.finish(200, line({ done: true }))
        verify(!view.generating)
        compare(view.messages.get(1).body, "One two three")
        compare(view.messages.get(1).phase, "done")
        wait(60)
        compare(view.messages.get(1).body, "One two three")
    }

    function test_replyBlocks() {
        var view = make().view
        // The blocks come from OllamaChat.blocks (tested there); the view
        // shows each in its own item.
        var wrapper = ready()
        var request = sendText(wrapper.view, "Hi")
        request.chunk(piece("Para one\nline\n\n  \nPara two\n```js\nx = 1\n\ny = 2\n```\ntail"))
        request.chunk(line({ done: true }))
        wait(30)
        var shown = shownTexts(wrapper.view)
        verify(shown.indexOf("Para one\nline") >= 0, JSON.stringify(shown))
        verify(shown.indexOf("Para two") >= 0, JSON.stringify(shown))
        verify(shown.indexOf("x = 1\n\ny = 2") >= 0, JSON.stringify(shown))
        verify(shown.indexOf("tail") >= 0, JSON.stringify(shown))
        compare(view.wrapFor("short words only"), TextEdit.Wrap)
        compare(view.wrapFor(new Array(121).join("x")), TextEdit.WrapAnywhere)
    }

    function test_thinkingShowsOnlyTheState() {
        var wrapper = ready()
        var view = wrapper.view
        var request = sendText(view, "Hi")
        request.chunk(line({ message: { role: "assistant", content: "", thinking: "secret plan" }, done: false }))
        compare(view.messages.get(1).phase, "thinking")
        compare(view.messages.get(1).body, "")
        request.chunk(piece("Answer"))
        compare(view.messages.get(1).phase, "streaming")
        compare(view.messages.get(1).body, "Answer")
    }

    function test_chatFailures_data() {
        return [
            { tag: "refused", status: 0, text: "", problem: "not-running", list: "failed" },
            { tag: "forbidden", status: 403, text: "", problem: "forbidden", list: "failed" },
            { tag: "missing", status: 404, text: "{\"error\":\"model 'x' not found\"}", problem: "model-missing",
              list: "ready" },
            { tag: "server", status: 500, text: "{\"error\":\"<b>out of memory</b>\"}", problem: "server-error",
              list: "ready", detail: "bout of memory/b" }
        ]
    }

    function test_chatFailures(data) {
        var wrapper = ready()
        var view = wrapper.view
        var request = sendText(view, "Hi")
        request.finish(data.status, data.text)
        verify(!view.generating)
        compare(view.problem, data.problem)
        compare(view.listState, data.list)
        compare(view.problemDetail, data.detail || "")
        // The empty reply is dropped, the question stays.
        compare(view.messages.count, 1)
    }

    function test_redirectedChatShowsNothing_data() {
        return [
            { tag: "chunk", interval: 0 },
            { tag: "chunk, throttled", interval: 40 },
            { tag: "finished", interval: 0, status: 200 },
            { tag: "error reply", interval: 0, status: 500 }
        ]
    }

    function test_redirectedChatShowsNothing(data) {
        var wrapper = ready()
        var view = wrapper.view
        view.renderInterval = data.interval
        var request = sendText(view, "Hi")
        request.redirectedTo = "http://127.0.0.1:9999/api/chat"
        if (data.status === undefined)
            request.chunk(piece("from elsewhere"))
        else if (data.status === 200)
            request.finish(200, piece("from elsewhere") + line({ done: true }))
        else
            request.finish(500, "{\"error\":\"from elsewhere\"}")
        compare(request.aborted, 1)
        verify(!view.generating)
        compare(view.problem, "server-error")
        compare(view.problemDetail, "")
        compare(view.stream.content, "")
        // Only the question stays.
        compare(view.messages.count, 1)
        compare(view.messages.get(0).author, "user")
        wait(60)
        request.chunk(piece(" more"))
        compare(view.messages.count, 1)
        compare(view.listState, "ready")
    }

    function test_serverErrorMarkupIsPlain() {
        var wrapper = ready()
        var view = wrapper.view
        var request = sendText(view, "Hi")
        request.chunk(line({ error: "<img src=\"http://127.0.0.1:9/x\"> &amp; <b>bold</b>" }))
        compare(view.problem, "server-error")
        var label = findChild(view, "problemDetail")
        verify(label.visible)
        compare(label.textFormat, Text.PlainText)
        compare(label.text, view.problemDetail)
        verify(label.text.indexOf("bold") >= 0, label.text)
        verify(!/[<>&]/.test(label.text), label.text)
    }

    function test_serverErrorLineKeepsPartialReply() {
        var wrapper = ready()
        var view = wrapper.view
        var request = sendText(view, "Hi")
        request.chunk(piece("Partial"))
        request.chunk(line({ error: "model runner stopped\u0007" }))
        verify(!view.generating)
        compare(view.messages.get(1).body, "Partial")
        compare(view.messages.get(1).phase, "failed")
        compare(view.problem, "server-error")
        compare(view.problemDetail, "model runner stopped")
    }

    function test_firstByteAndIdleTimeouts() {
        var wrapper = ready()
        var view = wrapper.view
        view.firstByteTimeout = 30
        var request = sendText(view, "Hi")
        tryCompare(view, "problem", "timeout")
        compare(request.aborted, 1)
        verify(!view.generating)

        view.firstByteTimeout = 100000
        view.idleTimeout = 30
        var next = sendText(view, "Again")
        next.chunk(piece("Part"))
        tryCompare(view, "problem", "timeout")
        compare(next.aborted, 1)
        compare(view.messages.get(view.messages.count - 1).body, "Part")
    }

    function test_replyTooLongIsCut() {
        var wrapper = ready()
        var view = wrapper.view
        var request = sendText(view, "Hi")
        request.chunk(piece(new Array(200002).join("x")))
        verify(!view.generating)
        compare(request.aborted, 1)
        compare(view.messages.get(1).phase, "cut")
        compare(view.messages.get(1).body.length, 200000)
    }

    // I3: a non-200 reply is dropped unread once it is over
    // MAX_ERROR_REPLY_CHARS, before it ends; a smaller one is read once.
    function errorChunk(request, status, text) {
        request.answered()
        request.status = status
        request.readyState = 3
        request.responseText += text
        request.onreadystatechange()
    }

    function test_hugeErrorReplyIsDroppedUnread() {
        var wrapper = ready()
        var view = wrapper.view
        var request = sendText(view, "Hi")
        errorChunk(request, 500, "{\"error\":\"boom\"}")
        verify(view.generating)
        compare(request.aborted, 0)
        errorChunk(request, 500, " ".repeat(OllamaChat.MAX_ERROR_REPLY_CHARS))
        compare(request.aborted, 1)
        verify(!view.generating)
        compare(view.problem, "server-error")
        compare(view.problemDetail, "")
        compare(view.messages.count, 1)

        var next = sendText(view, "Again")
        next.finish(500, "{\"error\":\"boom\"}")
        compare(view.problem, "server-error")
        compare(view.problemDetail, "boom")
        var missing = sendText(view, "Once more")
        errorChunk(missing, 404, "x".repeat(OllamaChat.MAX_ERROR_REPLY_CHARS + 1))
        compare(missing.aborted, 1)
        compare(view.problem, "model-missing")
    }

    function test_unendedStreamLineIsCut() {
        var wrapper = ready()
        var view = wrapper.view
        var request = sendText(view, "Hi")
        request.chunk(piece("Partial"))
        request.chunk("{\"message\":{\"content\":\"")
        verify(view.generating)
        request.chunk("x".repeat(OllamaChat.MAX_BUFFERED_CHARS))
        verify(!view.generating)
        compare(request.aborted, 1)
        compare(view.messages.get(1).body, "Partial")
        compare(view.messages.get(1).phase, "cut")
    }

    function test_hugeListReplyIsNotRead() {
        var wrapper = make({ shown: true })
        var view = wrapper.view
        compare(testCase.requests[0].url, "http://127.0.0.1:11434/api/version")
        testCase.requests[0].finish(200, "{\"version\":\"0.40.13\"}")
        var tagsRequest = testCase.requests[1]
        tagsRequest.chunk("{\"models\":[" + " ".repeat(OllamaChat.MAX_BUFFERED_CHARS))
        compare(tagsRequest.aborted, 1)
        compare(view.problem, "not-ollama")
        compare(view.modelList.length, 0)
    }

    function test_promptTooLong() {
        var wrapper = ready()
        var view = wrapper.view
        input(view).text = new Array(32002).join("x")
        verify(view.promptTooLong)
        verify(!view.canSend)
        input(view).text = new Array(32001).join("x")
        verify(!view.promptTooLong)
        verify(view.canSend)
    }

    function test_modelChoiceIsKeptAcrossReload() {
        var wrapper = ready()
        var view = wrapper.view
        view.selectModel("qwen3:8b")
        compare(view.modelName, "qwen3:8b")
        view.selectModel("not-listed")
        compare(view.modelName, "qwen3:8b")
        view.reloadModels()
        testCase.requests[2].finish(200, "{\"version\":\"0.40.13\"}")
        testCase.requests[3].finish(200, tags(testCase.defaultModels))
        compare(view.modelName, "qwen3:8b")
        var request = sendText(view, "Hi")
        compare(JSON.parse(request.body).model, "qwen3:8b")
    }

    // --- clear ------------------------------------------------------------------

    function test_clearEmptiesAndUnloads() {
        var wrapper = ready()
        var view = wrapper.view
        var request = sendText(view, "Hi")
        request.chunk(piece("Hello"))
        input(view).text = "draft"
        view.confirmingClear = true
        compare(findChild(view, "clearConfirm").visible, true)
        var before = testCase.requests.length
        var checks = testCase.ownerCommands.length
        view.clearConversation(true)
        compare(request.aborted, 1)
        compare(view.messages.count, 0)
        compare(input(view).text, "")
        verify(!view.generating)
        verify(!view.confirmingClear)
        compare(view.usedModels, [])
        // The unload request goes through the owner check and carries no prompt.
        compare(testCase.ownerCommands.length, checks + 1)
        compare(testCase.requests.length, before + 1)
        var unload = testCase.requests[before]
        compare(unload.method, "POST")
        compare(unload.url, "http://127.0.0.1:11434/api/chat")
        compare(unload.headers, [["Content-Type", "application/json"]])
        compare(JSON.parse(unload.body), { model: "llama3:latest", messages: [], keep_alive: 0 })
        // Late events of the aborted chat change nothing.
        request.chunk(piece(" again"))
        compare(view.messages.count, 0)
    }

    function test_clearDoesNotUnloadForAStranger() {
        var wrapper = ready()
        var view = wrapper.view
        sendText(view, "Hi").chunk(line({ done: true }))
        var before = testCase.requests.length
        testCase.ownerReply = { ok: true, owner: "other" }
        view.clearConversation(true)
        compare(testCase.requests.length, before)
        compare(view.messages.count, 0)
    }

    // Reopening the popup while the unload check runs must not lose the unload.
    function test_pendingUnloadSurvivesReopen() {
        var wrapper = ready()
        var view = wrapper.view
        sendText(view, "Hi").finish(0, "")
        compare(view.listState, "failed")
        testCase.ownerReply = null
        view.clearConversation(true)
        compare(view.checking, "unload")
        var check = testCase.ownerCommands[testCase.ownerCommands.length - 1]
        var before = testCase.requests.length
        wrapper.shown = false
        wrapper.shown = true
        compare(view.checking, "unload")
        compare(view.unloadNames, ["llama3:latest"])
        compare(testCase.ownerCommands[testCase.ownerCommands.length - 1], check)
        testCase.ownerReply = { ok: true, owner: "system" }
        view.ownerDone(check, { ok: true, owner: "system" })
        compare(testCase.requests.length, before + 2)
        compare(JSON.parse(testCase.requests[before].body), { model: "llama3:latest", messages: [], keep_alive: 0 })
        // The failed list is loaded again after the unload.
        compare(testCase.requests[before + 1].url, "http://127.0.0.1:11434/api/version")
        compare(view.listState, "loading")
    }

    // A send check still running for the old address is never answered.
    function test_addressChangeDuringSendCheckSendsNothing() {
        var wrapper = ready()
        var view = wrapper.view
        input(view).text = "secret"
        testCase.ownerReply = null
        var before = testCase.requests.length
        view.send()
        compare(view.checking, "send")
        var check = testCase.ownerCommands[testCase.ownerCommands.length - 1]
        view.address = "http://127.0.0.1:11435"
        // The new address gets its own check (for the model list).
        var next = testCase.ownerCommands[testCase.ownerCommands.length - 1]
        verify(next !== check)
        verify(/--port-owner 11435$/.test(next), next)
        compare(view.checking, "load")
        view.ownerDone(check, { ok: true, owner: "self" })
        compare(testCase.requests.length, before)
        compare(view.messages.count, 0)
        compare(input(view).text, "secret")
        compare(view.pendingPrompt, "")
        view.ownerDone(next, { ok: true, owner: "self" })
        compare(testCase.requests.length, before + 1)
        compare(testCase.requests[before].method, "GET")
        compare(testCase.requests[before].url, "http://127.0.0.1:11435/api/version")
    }

    function test_disablingClearsWithoutContact() {
        var wrapper = ready()
        var view = wrapper.view
        sendText(view, "Hi").chunk(piece("Hello"))
        var before = testCase.requests.length
        var checks = testCase.ownerCommands.length
        wrapper.siteOn = false
        compare(view.messages.count, 0)
        compare(view.modelList.length, 0)
        compare(view.listState, "idle")
        compare(testCase.requests.length, before)
        compare(testCase.ownerCommands.length, checks)
    }

    function test_conversationSurvivesHiding() {
        var wrapper = ready()
        var view = wrapper.view
        sendText(view, "Hi").chunk(line({ message: { role: "assistant", content: "Yo" }, done: true }))
        wrapper.shown = false
        wrapper.shown = true
        compare(view.messages.count, 2)
        compare(view.messages.get(1).body, "Yo")
    }

    // --- keyboard -----------------------------------------------------------------

    function test_enterSendsShiftEnterAddsLine() {
        var wrapper = ready()
        var view = wrapper.view
        var field = input(view)
        field.forceActiveFocus()
        verify(field.activeFocus)
        keyClick(Qt.Key_A)
        keyClick(Qt.Key_Return, Qt.ShiftModifier)
        keyClick(Qt.Key_B)
        compare(field.text, "a\nb")
        compare(testCase.requests.length, 2)
        keyClick(Qt.Key_Return)
        compare(testCase.requests.length, 3)
        compare(JSON.parse(testCase.requests[2].body).messages[0].content, "a\nb")
        compare(field.text, "")
    }

    function test_escapeStopsWithoutClosing() {
        var wrapper = ready()
        var view = wrapper.view
        var request = sendText(view, "Hi")
        request.chunk(piece("Hel"))
        input(view).forceActiveFocus()
        keyClick(Qt.Key_Escape)
        verify(!view.generating)
        compare(view.messages.get(1).phase, "stopped")
        compare(testCase.escapeAtParent, 0)
        // Idle: Esc passes on (the popup closes as usual).
        keyClick(Qt.Key_Escape)
        compare(testCase.escapeAtParent, 1)
    }

    function test_focusGoesToTheInputWhenShown() {
        var wrapper = make({ shown: false })
        wrapper.forceActiveFocus()
        wrapper.shown = true
        tryVerify(function () { return input(wrapper.view).activeFocus })
    }

    // --- untrusted text is plain text ---------------------------------------------

    function collect(item, out) {
        if (!item || out.indexOf(item) >= 0)
            return
        out.push(item)
        var kids = item.children || []
        for (var index = 0; index < kids.length; index++)
            collect(kids[index], out)
        if (item.contentItem)
            collect(item.contentItem, out)
    }

    // Every text the view sets on a control itself (never server text).
    property var fixedTexts: ["", "Clear this conversation?", "Clear", "Cancel", "Copy reply",
        "Copy code", "Retry", "Reload models", "Send", "Stop", "Back to bottom", "New messages",
        "Message (Enter sends, Shift+Enter adds a line)", "Model A", "Model B", "Close",
        "Edit message", "Regenerate reply",
        "How this model should answer, e.g. “Answer briefly, in German.”"]

    function test_everyShownTextIsPlain() {
        var wrapper = ready()
        var view = wrapper.view
        var request = sendText(view, "<b>mine</b>")
        request.chunk(piece("<img src=\"http://127.0.0.1:9/x\"> <b>b</b>\n```html\n<i>code</i>\n```\n![x](http://127.0.0.1:9/y)"))
        request.chunk(line({ done: true }))
        wait(50)
        var items = []
        collect(view, items)
        var formatted = 0
        var marked = 0
        for (var index = 0; index < items.length; index++) {
            var item = items[index]
            if (item.textFormat === undefined || typeof item.text !== "string")
                continue
            formatted += 1
            if (item.text.indexOf("<") >= 0)
                marked += 1
            // Labels inside the controls (buttons, actions, placeholders,
            // the inline message) keep their style's format; they only
            // ever show the view's own fixed texts.
            if (item.textFormat !== Text.PlainText)
                verify(testCase.fixedTexts.indexOf(item.text) >= 0,
                       "not plain text at " + item + ": " + item.text)
        }
        // The user's message, the reply text and the code block.
        verify(marked >= 3, "found " + marked)
        verify(formatted > marked, "found " + formatted)
    }

    // --- hidden direction characters are shown and copied as markers ----------

    TextEdit {
        id: pasteTarget
        visible: false
        textFormat: TextEdit.PlainText
    }

    // The shown item with this objectName (each message has its own).
    function named(view, name) {
        var items = []
        collect(view, items)
        for (var index = 0; index < items.length; index++) {
            if (items[index].objectName === name && items[index].visible)
                return items[index]
        }
        return null
    }

    function pasted() {
        pasteTarget.text = ""
        pasteTarget.paste()
        return pasteTarget.text
    }

    function test_hiddenCharactersAreShownAndCopiedMarked() {
        var wrapper = ready()
        var view = wrapper.view
        var request = sendText(view, "How do I clean?")
        request.chunk(piece("Run:\n```sh\nrm -rf ./build ‮⁦# keep ~⁩\n```\nDone​."))
        request.chunk(line({ done: true }))
        wait(50)
        var items = []
        collect(view, items)
        var shownCode = null
        for (var index = 0; index < items.length; index++) {
            var text = items[index].text
            if (typeof text !== "string")
                continue
            verify(!/[‪-‮⁦-⁩​-‏]/.test(text), "raw hidden character shown: " + text)
            if (text.indexOf("rm -rf") >= 0 && items[index].textFormat !== undefined)
                shownCode = text
        }
        compare(shownCode, "rm -rf ./build ⟦U+202E⟧⟦U+2066⟧# keep ~⟦U+2069⟧")
        var note = named(view, "hiddenCharsNote")
        verify(note !== null && note.visible)
        compare(note.textFormat, Text.PlainText)

        var copyCode = null
        var copyReply = null
        for (index = 0; index < items.length; index++) {
            if (!items[index].visible || !items[index].clicked)
                continue
            if (items[index].text === "Copy code")
                copyCode = items[index]
            if (items[index].text === "Copy reply")
                copyReply = items[index]
        }
        verify(copyCode !== null && copyReply !== null)
        copyCode.clicked()
        compare(pasted(), shownCode)
        copyReply.clicked()
        compare(pasted(), "Run:\n```sh\n" + shownCode + "\n```\nDone⟦U+200B⟧.")
    }

    function test_ordinaryReplyHasNoNote() {
        var wrapper = ready()
        var view = wrapper.view
        var request = sendText(view, "Hi")
        request.chunk(piece("Hello é 日本 שלום"))
        request.chunk(line({ done: true }))
        wait(50)
        var note = named(view, "hiddenCharsNote")
        compare(note, null)
    }

    // --- text size (Ctrl+= / Ctrl+- / Ctrl+0) -------------------------------

    function test_zoomKeysOnlyWhileShown() {
        var wrapper = make({ shown: false })
        var asked = []
        wrapper.view.zoomRequested.connect(function (direction) { asked.push(direction) })
        keyClick(Qt.Key_Equal, Qt.ControlModifier)
        compare(asked, [])
        wrapper.shown = true
        keyClick(Qt.Key_Equal, Qt.ControlModifier)
        keyClick(Qt.Key_Minus, Qt.ControlModifier)
        keyClick(Qt.Key_0, Qt.ControlModifier)
        compare(asked, [1, -1, 0])
    }

    function test_textScaleSizesTranscriptAndInput() {
        var wrapper = ready()
        var view = wrapper.view
        var field = input(view)
        var base = field.font.pointSize > 0 ? field.font.pointSize : field.font.pixelSize
        verify(base > 0)
        view.textScale = 1.5
        var scaled = field.font.pointSize > 0 ? field.font.pointSize : field.font.pixelSize
        fuzzyCompare(scaled, base * 1.5, 1)
        compare(view.bodyFont.family, field.font.family)
        verify((view.codeFont.pointSize > 0 ? view.codeFont.pointSize : view.codeFont.pixelSize) > base)
        view.textScale = 1.0
        compare(field.font.pointSize > 0 ? field.font.pointSize : field.font.pixelSize, base)
    }

    function test_ctrlWheelStepsTextScale() {
        var wrapper = ready()
        var view = wrapper.view
        var asked = []
        view.zoomRequested.connect(function (direction) { asked.push(direction) })
        var transcript = findChild(view, "transcript")
        var field = input(view)
        mouseWheel(transcript, 50, 50, 0, 120, Qt.NoButton, Qt.ControlModifier)
        mouseWheel(transcript, 50, 50, 0, -120, Qt.NoButton, Qt.ControlModifier)
        mouseWheel(field, 10, 10, 0, 120, Qt.NoButton, Qt.ControlModifier)
        compare(asked, [1, -1, 1])
        // Touchpad-sized moves add up to one step.
        mouseWheel(field, 10, 10, 0, 60, Qt.NoButton, Qt.ControlModifier)
        compare(asked.length, 3)
        mouseWheel(field, 10, 10, 0, 60, Qt.NoButton, Qt.ControlModifier)
        compare(asked, [1, -1, 1, 1])
        // A plain wheel scrolls and never zooms.
        mouseWheel(transcript, 50, 50, 0, 120)
        mouseWheel(field, 10, 10, 0, -120)
        compare(asked.length, 4)
    }

    function test_ctrlWheelOnlyWhileShown() {
        var wrapper = make({ shown: false })
        var asked = []
        wrapper.view.zoomRequested.connect(function (direction) { asked.push(direction) })
        mouseWheel(findChild(wrapper.view, "transcript"), 50, 50, 0, 120, Qt.NoButton, Qt.ControlModifier)
        compare(asked, [])
    }

    // --- the transcript follows the reply -----------------------------------

    function atBottom(list) {
        var end = list.originY + list.contentHeight + list.bottomMargin - list.height
        return list.contentY >= end - 2
    }

    function paragraphs(from, count) {
        var text = ""
        for (var index = from; index < from + count; index++)
            text += "Paragraph " + index + " of a reply that streams in.\n\n"
        return text
    }

    function test_transcriptFollowsTheReply() {
        var wrapper = ready()
        var view = wrapper.view
        var list = findChild(view, "transcript")
        var request = sendText(view, "Tell me a long story")
        // Each chunk: wait for its layout (the height grows), then check.
        var grown = 0
        for (var chunk = 0; chunk < 8; chunk++) {
            request.chunk(piece(paragraphs(chunk * 10, 10)))
            tryVerify(function () { return list.contentHeight > grown }, 2000, "chunk " + chunk + " not laid out")
            grown = list.contentHeight
            tryVerify(function () { return atBottom(list) }, 2000, "not at the bottom after chunk " + chunk)
        }
        verify(list.contentHeight > list.height * 2,
               "the transcript must be taller than the view: " + list.contentHeight + " / " + list.height)

        // The user scrolls up: a new chunk doesn't move them.
        mouseWheel(list, 50, 50, 0, 600)
        tryVerify(function () { return !atBottom(list) && !view.transcriptHeld })
        wait(50)
        var kept = list.contentY
        var height = list.contentHeight
        request.chunk(piece(paragraphs(80, 5)))
        tryVerify(function () { return list.contentHeight > height })
        wait(100)
        fuzzyCompare(list.contentY, kept, 1)
        verify(!view.followTranscript)

        // The user scrolls back to the bottom: it follows again.
        mouseWheel(list, 50, 50, 0, -6000)
        tryVerify(function () { return atBottom(list) && !view.transcriptHeld })
        tryVerify(function () { return view.followTranscript })
        height = list.contentHeight
        request.chunk(piece(paragraphs(85, 5)))
        tryVerify(function () { return list.contentHeight > height })
        tryVerify(function () { return atBottom(list) }, 2000)
        request.chunk(line({ done: true, done_reason: "stop", message: { role: "assistant", content: "" } }))
        verify(!view.generating)

        // Scrolled up, then a new message: sending always jumps down.
        mouseWheel(list, 50, 50, 0, 600)
        tryVerify(function () { return !atBottom(list) })
        var second = sendText(view, "And then?")
        tryVerify(function () { return atBottom(list) }, 2000)
        height = list.contentHeight
        second.chunk(piece(paragraphs(100, 6)))
        tryVerify(function () { return list.contentHeight > height })
        tryVerify(function () { return atBottom(list) }, 2000)
    }

    function test_backToBottom() {
        var wrapper = ready()
        var view = wrapper.view
        var list = findChild(view, "transcript")
        var button = findChild(view, "backToBottom")
        verify(button !== null)
        var request = sendText(view, "Tell me a long story")
        var grown = 0
        for (var chunk = 0; chunk < 6; chunk++) {
            request.chunk(piece(paragraphs(chunk * 10, 10)))
            tryVerify(function () { return list.contentHeight > grown }, 2000)
            grown = list.contentHeight
        }
        tryVerify(function () { return atBottom(list) }, 2000)
        // Hidden at the bottom.
        verify(!view.showBackToBottom)
        tryVerify(function () { return !button.visible })

        // Shown after scrolling up; the label is fixed text.
        mouseWheel(list, 50, 50, 0, 600)
        tryVerify(function () { return !view.transcriptHeld && view.showBackToBottom })
        tryVerify(function () { return button.visible && button.opacity === 1 })
        compare(button.text, "New messages")
        compare(button.focusPolicy, Qt.NoFocus)
        // It sits above the message box, never over it.
        var field = input(view)
        var buttonBottom = button.mapToItem(view, 0, button.height).y
        verify(buttonBottom <= field.mapToItem(view, 0, 0).y, buttonBottom + " overlaps the input")

        // Click: at the bottom, following again, hidden; the input keeps the focus.
        field.forceActiveFocus()
        mouseClick(button)
        tryVerify(function () { return atBottom(list) }, 2000)
        verify(view.followTranscript)
        verify(field.activeFocus)
        tryVerify(function () { return !button.visible })
        // And it keeps following the reply.
        request.chunk(piece(paragraphs(60, 6)))
        tryVerify(function () { return list.contentHeight > grown }, 2000)
        tryVerify(function () { return atBottom(list) }, 2000)

        // Done replying: the plain label.
        request.chunk(line({ done: true, done_reason: "stop", message: { role: "assistant", content: "" } }))
        mouseWheel(list, 50, 50, 0, 600)
        tryVerify(function () { return !view.transcriptHeld && button.visible })
        compare(button.text, "Back to bottom")
    }

    // --- nothing paints outside the view --------------------------------------

    function test_viewAndTranscriptClip() {
        var view = make({ shown: true }).view
        verify(view.clip)
        verify(findChild(view, "transcript").clip)
        verify(findChild(view, "inputScroll").clip)
        verify(findChild(view, "backToBottom").parent.clip)
    }

    function headerIsClean(header) {
        var image = grabImage(header)
        for (var y = 2; y < header.height - 2; y += 4) {
            for (var x = 2; x < header.width - 2; x += 8) {
                if (!Qt.colorEqual(image.pixel(x, y), "#ff00ff"))
                    return "x=" + x + " y=" + y + " is " + image.pixel(x, y)
            }
        }
        return ""
    }

    // Scrolled messages never paint over the tabs above the view.
    function test_scrolledTranscriptStaysBelowTheTabs() {
        var wrapper = ready(undefined, headedComponent)
        var view = wrapper.view
        var list = findChild(view, "transcript")
        var request = sendText(view, "Tell me a long story")
        var grown = 0
        for (var chunk = 0; chunk < 6; chunk++) {
            request.chunk(piece(paragraphs(chunk * 10, 10)))
            tryVerify(function () { return list.contentHeight > grown }, 2000)
            grown = list.contentHeight
        }
        request.chunk(line({ done: true, done_reason: "stop", message: { role: "assistant", content: "" } }))
        verify(view.mapToItem(wrapper, 0, 0).y >= wrapper.header.height)
        // Mid-way: messages above the view's top edge exist and must be clipped.
        list.contentY = list.contentHeight / 2
        wait(100)
        compare(headerIsClean(wrapper.header), "")
        list.contentY = list.originY - list.topMargin
        wait(100)
        compare(headerIsClean(wrapper.header), "")
    }

    // --- wheel in Plasma's desktop style (bugs A and B) ---------------------
    // Also run with QT_QUICK_CONTROLS_STYLE=org.kde.desktop: there the
    // style's ScrollView brings its own Kirigami.WheelHandler.

    function tallReply(view, list) {
        var request = sendText(view, "Tell me a long story")
        var grown = 0
        for (var chunk = 0; chunk < 6; chunk++) {
            request.chunk(piece(paragraphs(chunk * 10, 10)))
            tryVerify(function () { return list.contentHeight > grown }, 2000)
            grown = list.contentHeight
        }
        tryVerify(function () { return atBottom(list) }, 2000)
        return request
    }

    // A: scrolling up with the wheel while the reply streams stays up.
    function test_wheelUpWhileStreamingStaysUp() {
        var wrapper = ready()
        var view = wrapper.view
        var list = findChild(view, "transcript")
        var request = tallReply(view, list)
        mouseWheel(list, 50, 50, 0, 240)
        // Chunks keep arriving during and after the smooth scroll.
        request.chunk(piece(paragraphs(60, 3)))
        request.chunk(piece(paragraphs(63, 3)))
        tryVerify(function () { return !view.transcriptHeld })
        verify(!atBottom(list))
        verify(!view.followTranscript)
        var kept = list.contentY
        for (var chunk = 0; chunk < 4; chunk++) {
            var height = list.contentHeight
            request.chunk(piece(paragraphs(70 + chunk * 4, 4)))
            tryVerify(function () { return list.contentHeight > height }, 2000)
            wait(50)
            fuzzyCompare(list.contentY, kept, 1)
        }
        verify(view.showBackToBottom)
        tryVerify(function () { return findChild(view, "backToBottom").visible })
        // Wheel back down to the end: following again.
        mouseWheel(list, 50, 50, 0, -12000)
        tryVerify(function () { return !view.transcriptHeld })
        tryVerify(function () { return atBottom(list) && view.followTranscript })
    }

    // B: Ctrl+wheel zooms and never scrolls, even with something to scroll.
    function test_ctrlWheelZoomsInsteadOfScrolling() {
        var wrapper = ready()
        var view = wrapper.view
        var list = findChild(view, "transcript")
        tallReply(view, list)
        mouseWheel(list, 50, 50, 0, 600)
        tryVerify(function () { return !view.transcriptHeld })
        var asked = []
        view.zoomRequested.connect(function (direction) { asked.push(direction) })
        var y = list.contentY
        mouseWheel(list, 50, 50, 0, 120, Qt.NoButton, Qt.ControlModifier)
        mouseWheel(list, 50, 50, 0, -120, Qt.NoButton, Qt.ControlModifier)
        wait(Kirigami.Units.longDuration * 3)
        compare(asked, [1, -1])
        fuzzyCompare(list.contentY, y, 1)

        // The message box: long enough to scroll inside.
        var field = input(view)
        field.text = paragraphs(0, 40)
        var flick = field.parent
        while (flick && flick.contentY === undefined)
            flick = flick.parent
        verify(flick !== null)
        tryVerify(function () { return flick.contentHeight > flick.height })
        flick.contentY = 0
        mouseWheel(field, 10, 10, 0, 120, Qt.NoButton, Qt.ControlModifier)
        wait(Kirigami.Units.longDuration * 3)
        compare(asked, [1, -1, 1])
        compare(flick.contentY, 0)
        // A plain wheel still scrolls it.
        mouseWheel(field, 10, 10, 0, -240)
        tryVerify(function () { return flick.contentY > 0 }, 2000)
        compare(asked.length, 3)
    }

    // --- R2: formatting, personalities, regenerate/edit, compare, drops --------

    // Texts of the shown text items (Text, Label, TextEdit) under item.
    function shownTexts(item) {
        var items = []
        collect(item, items)
        var texts = []
        for (var index = 0; index < items.length; index++) {
            if (items[index].visible && items[index].textFormat !== undefined
                    && typeof items[index].text === "string" && items[index].text !== "")
                texts.push(items[index].text)
        }
        return texts
    }

    function reply(request, text) {
        request.chunk(piece(text))
        request.chunk(line({ done: true }))
    }

    function messagesOf(request) {
        return JSON.parse(request.body).messages
    }

    function test_formattedReplyIsPlainWordItems() {
        var wrapper = ready()
        var view = wrapper.view
        reply(sendText(view, "Hi"), "# Title\n\nSay **bold** and *it* `code` <b>x</b> [t](http://127.0.0.1:9/)\n\n- item **b**\n2. two")
        wait(50)
        var items = []
        collect(view, items)
        var bold = null
        var italic = null
        var code = null
        var words = 0
        for (var index = 0; index < items.length; index++) {
            var item = items[index]
            if (!item.visible || item.textFormat === undefined || typeof item.text !== "string")
                continue
            if (item.text === "bold" && item.font.bold)
                bold = item
            if (item.text === "it" && item.font.italic)
                italic = item
            if (item.text === "code")
                code = item
            if (item.text === "<b>x</b>" || item.text === "[t](http://127.0.0.1:9/)")
                words += 1
        }
        verify(bold !== null && italic !== null && code !== null)
        compare(bold.textFormat, Text.PlainText)
        compare(italic.textFormat, Text.PlainText)
        compare(code.textFormat, Text.PlainText)
        compare(code.font.family, view.codeFont.family)
        // HTML and links stay literal words.
        compare(words, 2)
        var shown = shownTexts(view)
        verify(shown.indexOf("Title") >= 0, JSON.stringify(shown))
        verify(shown.indexOf("•") >= 0 && shown.indexOf("2.") >= 0, JSON.stringify(shown))
        verify(shown.indexOf("**bold**") < 0)
        verify(findChild(view, "replyWords") !== null)
    }

    function test_everyShownTextIsPlainWithFormatting() {
        var wrapper = ready()
        var view = wrapper.view
        view.setPersona("llama3:latest", "<b>persona</b>")
        view.setComparing(true)
        view.editingPersona = true
        var request = sendText(view, "<i>q</i>")
        reply(request, "**<img src=\"http://127.0.0.1:9/x\">** and *<a href=\"x\">a</a>*\n\n- <b>li</b>\n### <h1>h</h1>")
        reply(testCase.requests[testCase.requests.length - 1], "**B <b>**")
        wait(50)
        var items = []
        collect(view, items)
        var marked = 0
        for (var index = 0; index < items.length; index++) {
            var item = items[index]
            if (item.textFormat === undefined || typeof item.text !== "string")
                continue
            if (item.text.indexOf("<") >= 0)
                marked += 1
            if (item.textFormat !== Text.PlainText)
                verify(testCase.fixedTexts.indexOf(item.text) >= 0,
                       "not plain text at " + item + ": " + item.text)
        }
        verify(marked >= 6, "found " + marked)
    }

    function test_personaIsTheFirstAndOnlySystemMessage() {
        var wrapper = ready()
        var view = wrapper.view
        view.editingPersona = true
        var field = findChild(view, "personaInput")
        verify(field !== null && field.visible)
        compare(field.textFormat, TextEdit.PlainText)
        field.text = "Answer in German.\nBriefly."
        compare(view.personaFor("llama3:latest"), "Answer in German.\nBriefly.")
        // Another model's personality is never sent to this one.
        view.setPersona("qwen3:8b", "Pirate")
        var first = sendText(view, "Hi")
        var sent = messagesOf(first)
        compare(sent[0], { role: "system", content: "Answer in German.\nBriefly." })
        compare(sent.filter(function (m) { return m.role === "system" }).length, 1)
        // With a personality the newest message carries the fixed reminder.
        compare(sent[1], { role: "user", content: OllamaChat.PERSONA_REMINDER + "Hi" })
        reply(first, "Hallo")
        // The note above the transcript shows the first line, as plain text.
        var note = findChild(view, "personaLine")
        verify(note.visible)
        compare(note.textFormat, Text.PlainText)
        compare(note.text, "Personality: Answer in German.")
        // Only the persona makes a system message: none in history, none
        // after it is removed.
        field.text = ""
        var second = sendText(view, "Again")
        compare(messagesOf(second).map(function (m) { return m.role }), ["user", "assistant", "user"])
        // The conversation never shows the persona.
        compare(view.messages.count, 4)
        for (var index = 0; index < view.messages.count; index++)
            verify(view.messages.get(index).body.indexOf("German") < 0)
    }

    function test_personaLimitAndMemoryOnly() {
        var wrapper = ready()
        var view = wrapper.view
        view.setPersona("llama3:latest", "x".repeat(8001))
        input(view).text = "Hi"
        verify(view.personaTooLong)
        verify(!view.canSend)
        view.setPersona("llama3:latest", "Be kind")
        verify(view.canSend)
        reply(sendText(view, "Hi"), "Hello")
        // Clear keeps personalities; turning Ollama off drops them.
        view.clearConversation(false)
        compare(view.personaFor("llama3:latest"), "Be kind")
        wrapper.siteOn = false
        compare(view.personaFor("llama3:latest"), "")
        compare(JSON.stringify(view.sessionPersonas), "{}")
        verify(!view.comparing)
        // Odd model names are never keys.
        view.setPersona("__proto__", "x")
        view.setPersona("bad name", "x")
        compare(JSON.stringify(view.sessionPersonas), "{\"m:__proto__\":\"x\"}")
        compare(view.personaFor("constructor"), "")
    }

    function test_regenerateReplacesTheLastReply() {
        var wrapper = ready()
        var view = wrapper.view
        view.setPersona("llama3:latest", "Short answers")
        reply(sendText(view, "First"), "One")
        reply(sendText(view, "Second"), "Two")
        compare(view.messages.count, 4)
        wait(30)
        var button = named(view, "regenerateButton")
        verify(button !== null)
        var checks = testCase.ownerCommands.length
        var before = testCase.requests.length
        button.clicked()
        // Its own owner check, then the same history without the old reply.
        compare(testCase.ownerCommands.length, checks + 1)
        compare(testCase.requests.length, before + 1)
        var again = testCase.requests[before]
        compare(messagesOf(again), [
            { role: "system", content: "Short answers" },
            { role: "user", content: "First" }, { role: "assistant", content: "One" },
            { role: "user", content: OllamaChat.PERSONA_REMINDER + "Second" }
        ])
        compare(view.messages.count, 4)
        compare(view.messages.get(3).body, "")
        reply(again, "Two again")
        compare(view.messages.count, 4)
        compare(view.messages.get(2).body, "Second")
        compare(view.messages.get(3).body, "Two again")
        // A port owned by someone else: nothing is sent, the reply stays.
        testCase.ownerReply = { ok: true, owner: "other" }
        before = testCase.requests.length
        view.regenerate("a")
        compare(testCase.requests.length, before)
        compare(view.problem, "other")
        compare(view.messages.get(3).body, "Two again")
    }

    function test_regenerateOnlyForTheLastFinishedReply() {
        var wrapper = ready()
        var view = wrapper.view
        var request = sendText(view, "Hi")
        request.chunk(piece("Part"))
        // Not while generating.
        var before = testCase.requests.length
        view.regenerate("a")
        compare(testCase.requests.length, before)
        verify(named(view, "regenerateButton") === null)
        request.chunk(line({ done: true }))
        wait(30)
        verify(named(view, "regenerateButton") !== null)
        verify(named(view, "editButton") !== null)
        // Only the last reply of the pane offers it.
        reply(sendText(view, "Two"), "B")
        wait(30)
        var items = []
        collect(view, items)
        var shown = items.filter(function (item) { return item.objectName === "regenerateButton" && item.visible })
        compare(shown.length, 1)
    }

    function test_editPutsTheLastMessageBack() {
        var wrapper = ready()
        var view = wrapper.view
        reply(sendText(view, "First"), "One")
        reply(sendText(view, "Second try"), "Two")
        wait(30)
        input(view).text = ""
        var before = testCase.requests.length
        var checks = testCase.ownerCommands.length
        named(view, "editButton").clicked()
        compare(input(view).text, "Second try")
        compare(view.messages.count, 2)
        compare(view.messages.get(1).body, "One")
        // Nothing is sent or checked until Send.
        compare(testCase.requests.length, before)
        compare(testCase.ownerCommands.length, checks)
        var resent = sendText(view, "Second, better")
        compare(messagesOf(resent).length, 3)
        compare(view.messages.count, 4)
    }

    function compareReady(models) {
        var wrapper = ready(models)
        var view = wrapper.view
        view.setComparing(true)
        verify(view.comparing)
        compare(view.modelName, "llama3:latest")
        compare(view.modelNameB, "qwen3:8b")
        return wrapper
    }

    function test_compareRunsAThenBWithTwoOwnerChecks() {
        var wrapper = compareReady()
        var view = wrapper.view
        view.setPersona("qwen3:8b", "Persona B")
        var checks = testCase.ownerCommands.length
        var a = sendText(view, "Same question")
        compare(testCase.ownerCommands.length, checks + 1)
        compare(JSON.parse(a.body).model, "llama3:latest")
        compare(messagesOf(a), [{ role: "user", content: "Same question" }])
        compare(input(view).text, "")
        // B waits for A.
        a.chunk(piece("Answer A"))
        compare(testCase.requests.length, 3)
        a.chunk(line({ done: true }))
        compare(testCase.ownerCommands.length, checks + 2)
        compare(testCase.requests.length, 4)
        var b = testCase.requests[3]
        compare(JSON.parse(b.body).model, "qwen3:8b")
        compare(messagesOf(b), [{ role: "system", content: "Persona B" },
                                { role: "user", content: OllamaChat.PERSONA_REMINDER + "Same question" }])
        verify(view.generating)
        reply(b, "Answer B")
        verify(!view.generating)
        compare(view.messages.count, 2)
        compare(view.messages.get(1).body, "Answer A")
        compare(view.messagesB.count, 2)
        compare(view.messagesB.get(1).body, "Answer B")
        // Each pane keeps its own history.
        var a2 = sendText(view, "Next")
        compare(messagesOf(a2).map(function (m) { return m.content }), ["Same question", "Answer A", "Next"])
        reply(a2, "A2")
        var b2 = testCase.requests[testCase.requests.length - 1]
        compare(messagesOf(b2).map(function (m) { return m.content }),
                ["Persona B", "Same question", "Answer B", OllamaChat.PERSONA_REMINDER + "Next"])
        // Model B's pane shows its model name, as plain text.
        var label = null
        var items = []
        collect(view, items)
        for (var index = 0; index < items.length; index++) {
            if (items[index].objectName === "paneModel" && items[index].text === "qwen3:8b")
                label = items[index]
        }
        verify(label !== null && label.visible)
        compare(label.textFormat, Text.PlainText)
    }

    function test_compareStopCancelsB() {
        var wrapper = compareReady()
        var view = wrapper.view
        var a = sendText(view, "Q")
        a.chunk(piece("Partial A"))
        var checks = testCase.ownerCommands.length
        view.stop()
        compare(a.aborted, 1)
        verify(!view.generating)
        compare(view.checking, "")
        a.chunk(line({ done: true }))
        wait(30)
        compare(testCase.ownerCommands.length, checks)
        compare(testCase.requests.length, 3)
        compare(view.messagesB.count, 0)
        compare(view.messages.get(1).phase, "stopped")

        // Stop during B's owner check: B never starts.
        var a2 = sendText(view, "Q2")
        testCase.ownerReply = null
        reply(a2, "A2")
        compare(view.checking, "send")
        view.stop()
        compare(view.checking, "")
        compare(testCase.requests.length, 4)
        compare(view.messagesB.count, 0)
    }

    function test_compareBGetsNothingWhenAFailsHard() {
        var wrapper = compareReady()
        var view = wrapper.view
        var a = sendText(view, "Q")
        a.finish(0, "")
        compare(view.problem, "not-running")
        compare(testCase.requests.length, 3)
        compare(view.messagesB.count, 0)
    }

    function test_compareClearClearsBothAndUnloadsBoth() {
        var wrapper = compareReady()
        var view = wrapper.view
        reply(sendText(view, "Q"), "A")
        reply(testCase.requests[testCase.requests.length - 1], "B")
        view.setPersona("llama3:latest", "kept")
        var before = testCase.requests.length
        view.clearConversation(true)
        compare(view.messages.count, 0)
        compare(view.messagesB.count, 0)
        var unloads = testCase.requests.slice(before)
        compare(unloads.length, 2)
        compare(unloads.map(function (r) { return JSON.parse(r.body).model }).sort(),
                ["llama3:latest", "qwen3:8b"])
        for (var index = 0; index < unloads.length; index++)
            compare(JSON.parse(unloads[index].body).messages, [])
        compare(view.personaFor("llama3:latest"), "kept")
    }

    function test_compareEditAndRegeneratePerPane() {
        var wrapper = compareReady()
        var view = wrapper.view
        reply(sendText(view, "Q"), "A")
        reply(testCase.requests[testCase.requests.length - 1], "B")
        // Regenerate in pane B asks model B only.
        var before = testCase.requests.length
        view.regenerate("b")
        compare(testCase.requests.length, before + 1)
        var again = testCase.requests[before]
        compare(JSON.parse(again.body).model, "qwen3:8b")
        reply(again, "B2")
        compare(testCase.requests.length, before + 1)
        compare(view.messagesB.get(1).body, "B2")
        compare(view.messages.get(1).body, "A")
        // Edit takes the message back out of both panes.
        view.editLast()
        compare(input(view).text, "Q")
        compare(view.messages.count, 0)
        compare(view.messagesB.count, 0)
    }

    function test_compareLayoutAndHint() {
        var wrapper = compareReady()
        var view = wrapper.view
        var paneA = findChild(view, "transcript")
        var paneB = findChild(view, "transcriptB")
        verify(paneB !== null && paneB.visible)
        verify(paneB.clip)
        // 500 px is narrow: stacked, with the hint toward the Large popup.
        verify(!view.sideBySide)
        verify(findChild(view, "compareHint").visible)
        var a = paneA.mapToItem(view, 0, 0)
        var b = paneB.mapToItem(view, 0, 0)
        verify(b.y > a.y)
        wrapper.anchors.fill = undefined
        wrapper.height = testCase.height
        wrapper.width = Kirigami.Units.gridUnit * 41
        verify(view.sideBySide)
        tryVerify(function () { return paneB.mapToItem(view, 0, 0).x > paneA.mapToItem(view, 0, 0).x })
        verify(!findChild(view, "compareHint").visible)
        view.setComparing(false)
        verify(!paneB.visible)
    }

    // Pane B has the same wheel handling: Ctrl+wheel zooms, a wheel up
    // stops following, Back to bottom brings it back.
    function test_compareSecondPaneScrollsAndZooms() {
        var wrapper = compareReady()
        var view = wrapper.view
        var list = findChild(view, "transcriptB")
        reply(sendText(view, "Long"), "A")
        var b = testCase.requests[testCase.requests.length - 1]
        for (var chunk = 0; chunk < 6; chunk++)
            b.chunk(piece(paragraphs(chunk * 10, 10)))
        b.chunk(line({ done: true }))
        tryVerify(function () { return atBottom(list) }, 2000)
        var asked = []
        view.zoomRequested.connect(function (direction) { asked.push(direction) })
        mouseWheel(list, 50, 50, 0, 120, Qt.NoButton, Qt.ControlModifier)
        compare(asked, [1])
        verify(atBottom(list))
        mouseWheel(list, 50, 50, 0, 600)
        tryVerify(function () { return !atBottom(list) })
        var button = findChild(view, "backToBottomB")
        tryVerify(function () { return button.visible })
        // Pane A is unaffected.
        verify(view.followTranscript)
        button.clicked()
        tryVerify(function () { return atBottom(list) })
    }

    function test_dropFillsTheInputAndNeverSends() {
        var wrapper = ready()
        var view = wrapper.view
        var field = input(view)
        field.text = "Typed"
        var before = testCase.requests.length
        var checks = testCase.ownerCommands.length
        verify(view.textDropped(true, false, "Dropped\u0007 text"))
        compare(field.text, "Typed\n\nDropped text")
        // Also nothing a moment later (no deferred send).
        wait(50)
        compare(testCase.requests.length, before)
        verify(!testCase.requests.some(function (r) { return r.url.indexOf("/api/chat") >= 0 }))
        compare(testCase.ownerCommands.length, checks)
        verify(!view.generating)
        // Files are refused, with a fixed text.
        verify(!view.textDropped(true, true, "/home/user/file.txt"))
        compare(view.problem, "drop-file")
        compare(findChild(view, "problemText").text, "Drop text, not files.")
        compare(field.text, "Typed\n\nDropped text")
        // Too long: refused, the input stays.
        verify(view.textDropped(true, false, "x".repeat(32000)))
        compare(view.problem, "drop-too-long")
        compare(field.text, "Typed\n\nDropped text")
        // A good drop clears the drop problem.
        verify(view.textDropped(true, false, "more"))
        compare(view.problem, "")
        compare(testCase.requests.length, before)
        // Nothing without text, nothing while hidden or off.
        verify(!view.textDropped(false, false, ""))
        wrapper.shown = false
        verify(!view.textDropped(true, false, "x"))
        compare(field.text, "Typed\n\nDropped text\n\nmore")
        compare(testCase.requests.length, before)
    }

    function test_takeDropFromThePanelIcon() {
        var wrapper = ready()
        var view = wrapper.view
        var before = testCase.requests.length
        view.takeDrop("from the icon")
        compare(input(view).text, "from the icon")
        view.takeDrop("a\u0000b")
        compare(view.problem, "drop-file")
        compare(input(view).text, "from the icon")
        compare(testCase.requests.length, before)
        wrapper.siteOn = false
        view.takeDrop("off")
        compare(input(view).text, "")
    }

    // --- R4: file drops, prompts, saved personalities ------------------------------

    function test_singleFileDropAsksMainToReadIt() {
        var wrapper = ready()
        var view = wrapper.view
        var files = []
        view.fileDropped.connect(function (hex) { files.push(hex) })
        var before = testCase.requests.length
        verify(view.textDropped(true, true, "/tmp/a.txt", "2f746d702f612e747874"))
        compare(files, ["2f746d702f612e747874"])
        compare(view.problem, "")
        // Several files or a link: refused, nothing read.
        verify(!view.textDropped(true, true, "x", ""))
        compare(view.problem, "drop-file")
        compare(files.length, 1)
        // The text comes back through takeDrop; nothing is sent, not even later.
        view.takeDrop("file text")
        compare(input(view).text, "file text")
        wait(50)
        compare(testCase.requests.length, before)
        verify(!testCase.requests.some(function (r) { return r.url.indexOf("/api/chat") >= 0 }))
        verify(!view.generating)
        var codes = [["too-large", "drop-too-large"], ["too-long", "drop-too-long"], ["not-text", "drop-not-text"],
                     ["absent", "drop-unreadable"], ["bad-reply", "drop-unreadable"]]
        for (var index = 0; index < codes.length; index++) {
            view.dropFailed(codes[index][0])
            compare(view.problem, codes[index][1])
            compare(findChild(view, "problemText").textFormat, Text.PlainText)
        }
    }

    function test_insertPromptAtTheCursor() {
        var wrapper = ready()
        var view = wrapper.view
        var field = input(view)
        field.text = "Hello world"
        field.cursorPosition = 6
        view.insertPrompt("big ")
        compare(field.text, "Hello big world")
        compare(field.cursorPosition, 10)
        view.insertPrompt("x".repeat(32000))
        compare(view.problem, "insert-too-long")
        compare(field.text, "Hello big world")
        compare(testCase.requests.length, 2)
    }

    function test_savedPersonalityIsTheDefault() {
        var wrapper = ready()
        var view = wrapper.view
        var chosen = []
        view.personaDefaultChosen.connect(function (model, id) { chosen.push([model, id]) })
        view.libraryItems = [{ id: 4, kind: "persona", text: "Saved persona" }, { id: 5, kind: "prompt", text: "P" },
                             { id: -1, kind: "persona", text: "Session persona" }]
        view.libraryPersonas = { "m:llama3:latest": 4 }
        view.libraryReady = true
        compare(view.personaFor("llama3:latest"), "Saved persona")
        compare(view.personaFor("qwen3:8b"), "")
        compare(view.personaChoices.length, 3)
        var request = sendText(view, "Hi")
        compare(messagesOf(request)[0], { role: "system", content: "Saved persona" })
        reply(request, "ok")
        // Choosing in the picker: the session's text and the saved default.
        view.editingPersona = true
        var picker = findChild(view, "personaPicker")
        verify(picker.visible)
        compare(picker.displayText, "Choose a saved personality…")
        view.choosePersona(view.personaChoices[2])
        compare(view.personaFor("llama3:latest"), "Session persona")
        compare(chosen, [])
        view.choosePersona(view.personaChoices[1])
        compare(chosen, [["llama3:latest", 4]])
        view.choosePersona(view.personaChoices[0])
        compare(chosen[1], ["llama3:latest", -1])
        // Not saved (folder locked): nothing is asked of the helper.
        view.libraryReady = false
        view.choosePersona(view.personaChoices[1])
        compare(chosen.length, 2)
    }

    function test_personaPickerShowsTextAsPlainText() {
        var wrapper = ready()
        var view = wrapper.view
        view.libraryItems = [{ id: 4, kind: "persona", text: "<b>bold</b> <img src=\"http://127.0.0.1:9/\">" }]
        view.editingPersona = true
        var picker = findChild(view, "personaPicker")
        picker.popup.open()
        wait(50)
        var items = []
        collect(picker.popup.contentItem, items)
        var found = null
        for (var index = 0; index < items.length; index++) {
            if (typeof items[index].text === "string" && items[index].text.indexOf("<b>") === 0)
                found = items[index]
        }
        verify(found !== null)
        compare(found.textFormat, Text.PlainText)
        picker.popup.close()
    }

    Component {
        id: panelComponent
        PromptLibraryPanel {
            width: 400
        }
    }

    function test_libraryPanelCopiesOnClickAndKeepsSessionItems() {
        var panel = createTemporaryObject(panelComponent, testCase, {
            items: [{ id: 1, kind: "prompt", text: "<i>Summarize</i>\nthis" }, { id: -2, kind: "persona", text: "Kind" }]
        })
        verify(panel !== null)
        wait(30)
        // Only plain text, never the library text as markup.
        var items = []
        collect(panel, items)
        var shown = 0
        for (var index = 0; index < items.length; index++) {
            if (items[index].objectName === "libraryItemText") {
                compare(items[index].textFormat, Text.PlainText)
                shown += 1
            }
        }
        compare(shown, 2)
        compare(named(panel, "libraryNote").text,
                "Kept for this session only. To save prompts, turn on Stay signed in → Encrypted in the settings.")
        // A web site: Copy puts the whole text on the clipboard, on a click.
        var copy = named(panel, "libraryUseButton")
        compare(copy.text, "Copy")
        copy.clicked()
        compare(pasted(), "<i>Summarize</i>\nthis")
        verify(named(panel, "copiedNote").visible)
        // Ollama: insert instead.
        var used = []
        panel.useRequested.connect(function (text) { used.push(text) })
        panel.forOllama = true
        named(panel, "libraryUseButton").clicked()
        compare(used, ["<i>Summarize</i>\nthis"])
        // Session items are typed here.
        var kept = []
        panel.sessionAddRequested.connect(function (kind, text) { kept.push([kind, text]) })
        var field = named(panel, "sessionLibraryInput")
        compare(field.textFormat, TextEdit.PlainText)
        field.text = "New one"
        named(panel, "keepPromptButton").clicked()
        compare(kept, [["prompt", "New one"]])
        compare(field.text, "")
        // Saved: kdialog through the helper, no typing field.
        panel.saved = true
        verify(named(panel, "sessionLibraryInput") === null)
    }

    // --- review fixes ----------------------------------------------------------------

    // M2: an emptied personality box beats the saved default.
    function test_emptiedPersonalityBeatsTheSavedDefault() {
        var wrapper = ready()
        var view = wrapper.view
        view.libraryItems = [{ id: 4, kind: "persona", text: "Saved persona" }]
        view.libraryPersonas = { "m:llama3:latest": 4 }
        view.libraryReady = true
        view.libraryOpen = true
        view.editingPersona = true
        var field = findChild(view, "personaInput")
        compare(field.text, "Saved persona")
        field.text = ""
        compare(view.personaFor("llama3:latest"), "")
        var request = sendText(view, "Hi")
        compare(messagesOf(request).filter(function (m) { return m.role === "system" }).length, 0)
        reply(request, "ok")
        // "None" in the picker is empty at once, before the helper answers.
        field.text = "Mine"
        view.choosePersona(view.personaChoices[0])
        compare(view.personaFor("llama3:latest"), "")
        compare(messagesOf(sendText(view, "Again")).filter(function (m) { return m.role === "system" }).length, 0)
    }

    // S1: a personality picked from the saved library goes with Lock.
    function test_savedPersonalityLeavesWithLock() {
        var wrapper = ready()
        var view = wrapper.view
        view.libraryItems = [{ id: 4, kind: "persona", text: "Library text" }]
        view.libraryReady = true
        view.libraryOpen = true
        view.setPersona("qwen3:8b", "Typed for qwen")
        view.editingPersona = true
        view.choosePersona(view.personaChoices[1])
        compare(view.personaFor("llama3:latest"), "Library text")
        // Locked: main.qml drops the library; the view drops its copy.
        view.libraryItems = []
        view.libraryReady = false
        view.libraryOpen = false
        compare(view.personaFor("llama3:latest"), "")
        compare(findChild(view, "personaInput").text, "")
        var request = sendText(view, "Hi")
        var sent = messagesOf(request)
        compare(sent.filter(function (m) { return m.role === "system" }).length, 0)
        verify(JSON.stringify(sent).indexOf("Library text") < 0)
        // The user's own text stays.
        compare(view.personaFor("qwen3:8b"), "Typed for qwen")
        // Edited after picking: the user's text, kept after Lock.
        view.libraryOpen = true
        view.libraryItems = [{ id: 4, kind: "persona", text: "Library text" }]
        reply(request, "ok")
        view.choosePersona(view.personaChoices[1])
        findChild(view, "personaInput").text = "Library text, changed"
        view.libraryOpen = false
        compare(view.personaFor("llama3:latest"), "Library text, changed")
    }

    // S3: Edit takes back pane B's copy of the same turn only.
    function test_editKeepsAnOlderPaneBTurnWithTheSameText() {
        var wrapper = compareReady()
        var view = wrapper.view
        reply(sendText(view, "continue"), "A1")
        reply(testCase.requests[testCase.requests.length - 1], "B1")
        compare(view.messagesB.count, 2)
        var a2 = sendText(view, "continue")
        a2.chunk(piece("partial"))
        view.stop()
        compare(view.messagesB.count, 2)
        view.editLast()
        compare(input(view).text, "continue")
        compare(view.messages.count, 2)
        // Pane B keeps turn 1.
        compare(view.messagesB.count, 2)
        compare(view.messagesB.get(1).body, "B1")
        // The same turn in both panes still goes from both.
        var a3 = sendText(view, "again")
        reply(a3, "A3")
        reply(testCase.requests[testCase.requests.length - 1], "B3")
        view.editLast()
        compare(view.messages.count, 2)
        compare(view.messagesB.count, 2)
    }

    // --- Task 1: the user's flow, typed with the keyboard -----------------------------

    // Open Personality, type, close, send: the body starts with that
    // personality as the system message (and the conversation shows the
    // plain message).
    function typedPersonaIsSent(lockFirst) {
        var wrapper = ready()
        var view = wrapper.view
        if (lockFirst) {
            // Stay signed in → Encrypted: the folder was unlocked, then locked.
            view.libraryOpen = true
            view.libraryItems = [{ id: 4, kind: "persona", text: "Saved" }]
            view.libraryOpen = false
            view.libraryItems = []
        }
        view.editingPersona = true
        var field = findChild(view, "personaInput")
        tryVerify(function () { return field.activeFocus })
        keyClick("B"); keyClick("e"); keyClick(Qt.Key_Space); keyClick("b"); keyClick("r"); keyClick("i")
        keyClick("e"); keyClick("f"); keyClick(Qt.Key_Period)
        compare(field.text, "Be brief.")
        view.editingPersona = false
        var box = input(view)
        tryVerify(function () { return box.activeFocus })
        keyClick("H"); keyClick("i")
        var before = testCase.requests.length
        keyClick(Qt.Key_Return)
        compare(testCase.requests.length, before + 1)
        var sent = messagesOf(testCase.requests[before])
        compare(sent[0], { role: "system", content: "Be brief." })
        compare(sent.map(function (m) { return m.role }), ["system", "user"])
        compare(sent[1].content, OllamaChat.PERSONA_REMINDER + "Hi")
        compare(view.messages.get(0).body, "Hi")
        reply(testCase.requests[before], "Ok.")
        // The next turn keeps it; only the newest message has the reminder.
        keyClick("Y"); keyClick(Qt.Key_Return)
        var next = messagesOf(testCase.requests[testCase.requests.length - 1])
        compare(next.map(function (m) { return m.role }), ["system", "user", "assistant", "user"])
        compare(next[0].content, "Be brief.")
        compare(next[1].content, "Hi")
        compare(next[3].content, OllamaChat.PERSONA_REMINDER + "Y")
    }

    function test_typedPersonaIsSentWithTheFolderOff() {
        typedPersonaIsSent(false)
    }

    function test_typedPersonaIsSentWithTheFolderLocked() {
        typedPersonaIsSent(true)
    }

    // --- R4: chat bubbles ------------------------------------------------------

    // Like wrapperComponent, laid out right to left.
    Component {
        id: mirroredComponent
        FocusScope {
            id: mirrored
            property alias view: chat
            property bool shown: false
            anchors.fill: parent
            LayoutMirroring.enabled: true
            LayoutMirroring.childrenInherit: true

            OllamaChatView {
                id: chat
                anchors.fill: parent
                focus: true
                current: mirrored.shown
                siteEnabled: true
                appletId: 7
                renderInterval: 0
                createRequest: function () { return testCase.newFake() }
                runOwnerCheck: function (command) { testCase.ownerAsked(chat, command) }
            }
        }
    }

    // Every item with this objectName, shown or not.
    function allNamed(view, name) {
        var items = []
        collect(view, items)
        return items.filter(function (item) { return item.objectName === name })
    }

    // The shown text item showing exactly text.
    function textItem(view, text) {
        var items = []
        collect(view, items)
        for (var index = 0; index < items.length; index++) {
            if (items[index].visible && items[index].textFormat !== undefined && items[index].text === text)
                return items[index]
        }
        return null
    }

    // item's rectangle in outer's coordinates.
    function rectIn(item, outer) {
        var at = item.mapToItem(outer, 0, 0)
        return { x: at.x, y: at.y, right: at.x + item.width, bottom: at.y + item.height }
    }

    function verifyInside(item, outer, what) {
        var rect = rectIn(item, outer)
        verify(rect.x >= -1 && rect.y >= -1 && rect.right <= outer.width + 1 && rect.bottom <= outer.height + 1,
            what + " " + JSON.stringify(rect) + " outside " + outer.width + "x" + outer.height)
    }

    function test_bubblesAlign_data() {
        return [
            { tag: "left to right", mirrored: false },
            { tag: "right to left", mirrored: true }
        ]
    }

    function test_bubblesAlign(data) {
        var view = ready(undefined, data.mirrored ? mirroredComponent : undefined).view
        reply(sendText(view, "Hi there"), "Hello")
        wait(50)
        var user = named(view, "userBubble")
        var answer = named(view, "replyBubble")
        verify(user !== null && answer !== null)
        // The bubble's parent is its message: the transcript's content width.
        var userRight = user.x + user.width
        var answerRight = answer.x + answer.width
        if (data.mirrored) {
            verify(Math.abs(user.x) <= 1, "user bubble at " + user.x)
            verify(Math.abs(answerRight - answer.parent.width) <= 1,
                "reply bubble ends at " + answerRight + " of " + answer.parent.width)
        } else {
            verify(Math.abs(userRight - user.parent.width) <= 1,
                "user bubble ends at " + userRight + " of " + user.parent.width)
            verify(Math.abs(answer.x) <= 1, "reply bubble at " + answer.x)
        }
        // A short reply's bubble fits its text, well under the cap.
        verify(answer.width < answer.parent.width * 0.5, "reply bubble " + answer.width)
        verifyInside(textItem(view, "Hello"), answer, "reply text")
        verifyInside(textItem(view, "Hi there"), user, "user text")
    }

    function test_userBubbleIsTheHighlight() {
        var view = ready().view
        reply(sendText(view, "Plain <b>me</b>"), "Ok")
        wait(50)
        var bubble = named(view, "userBubble")
        verify(bubble !== null)
        verify(Qt.colorEqual(bubble.color, bubble.Kirigami.Theme.highlightColor), String(bubble.color))
        compare(bubble.radius, Kirigami.Units.cornerRadius * 2)
        var text = textItem(view, "Plain <b>me</b>")
        verify(text !== null && text.parent === bubble)
        verify(text.readOnly)
        compare(text.textFormat, TextEdit.PlainText)
        verify(Qt.colorEqual(text.color, text.Kirigami.Theme.highlightedTextColor), String(text.color))
        // The Edit button stays below the bubble, at the right.
        var edit = named(view, "editButton")
        verify(edit !== null)
        verify(edit.y >= bubble.y + bubble.height)
        verify(Math.abs(edit.x + edit.width - edit.parent.width) <= 1)
    }

    function test_replyBubbleOnlyForAnswers() {
        var view = ready().view
        var request = sendText(view, "Hi")
        // Thinking: no reply bubble yet, only the state row.
        request.chunk(line({ message: { role: "assistant", content: "", thinking: "plan" }, done: false }))
        wait(30)
        var bubbles = allNamed(view, "replyBubble")
        compare(bubbles.length, 2)
        verify(bubbles.every(function (bubble) { return !bubble.visible }))
        verify(shownTexts(view).indexOf("Thinking…") >= 0)
        request.chunk(piece("Answer"))
        request.chunk(line({ done: true }))
        wait(30)
        bubbles = allNamed(view, "replyBubble").filter(function (bubble) { return bubble.visible })
        compare(bubbles.length, 1)
        var bubble = bubbles[0]
        verify(Qt.colorEqual(bubble.color, Qt.alpha(bubble.Kirigami.Theme.textColor, 0.06)), String(bubble.color))
        compare(bubble.radius, Kirigami.Units.cornerRadius * 2)
        verify(textItem(view, "Answer").parent !== null)
        verifyInside(textItem(view, "Answer"), bubble, "answer")
        // The user's row has no shown reply bubble; the reply's has no user bubble.
        compare(allNamed(view, "userBubble").filter(function (b) { return b.visible }).length, 1)
        // The copy row stays below the bubble.
        var items = []
        collect(view, items)
        var copy = items.filter(function (item) { return item.visible && item.text === "Copy reply" })
        compare(copy.length, 1)
        verify(copy[0].mapToItem(bubble, 0, 0).y >= bubble.height)
    }

    function test_longWordWrapsInsideTheBubble() {
        var view = ready().view
        var word = new Array(301).join("w")
        reply(sendText(view, "Long"), word)
        wait(50)
        var bubble = named(view, "replyBubble")
        verify(bubble !== null)
        var pane = bubble.parent.width
        verify(bubble.width <= pane * 0.92 + 1, bubble.width + " > 92% of " + pane)
        var text = textItem(view, word)
        verify(text !== null)
        verify(text.lineCount > 1, "not wrapped: " + text.lineCount)
        verify(text.contentWidth <= text.width + 1)
        verifyInside(text, bubble, "long word")
    }

    function test_codeBlockFitsInsideTheBubble() {
        var view = ready().view
        reply(sendText(view, "Code"), "Short.\n```js\nx = 1\n```\nAfter")
        wait(50)
        var bubble = named(view, "replyBubble")
        verify(bubble !== null)
        verify(bubble.width <= bubble.parent.width * 0.92 + 1)
        var code = textItem(view, "x = 1")
        verify(code !== null)
        // The code block: its alternate-background box.
        var box = code.parent
        verify(Qt.colorEqual(box.color, box.Kirigami.Theme.alternateBackgroundColor), String(box.color))
        verifyInside(box, bubble, "code block")
        verifyInside(textItem(view, "Short."), bubble, "paragraph")
        verifyInside(textItem(view, "After"), bubble, "paragraph")
    }

    function test_hiddenCharsNoteIsInsideTheBubble() {
        var view = ready().view
        reply(sendText(view, "Hi"), "Hid​den")
        wait(50)
        var bubble = named(view, "replyBubble")
        var note = named(view, "hiddenCharsNote")
        verify(bubble !== null && note !== null)
        verifyInside(note, bubble, "note")
    }
}
