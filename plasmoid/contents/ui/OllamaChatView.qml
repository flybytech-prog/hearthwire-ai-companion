import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.plasma5support as Plasma5Support
import org.kde.kirigami as Kirigami
import "OllamaChat.js" as OllamaChat
import "ChatStorage.js" as ChatStorage
import "PromptLibrary.js" as PromptLibrary

// Built-in chat with the Ollama server on this computer. Prompts, replies
// and personalities live only in this view's memory (the transcript models
// and sessionPersonas below) and in the request body sent over loopback;
// nothing is saved, logged or handed to the helper. The helper only answers who owns the port, checked before the
// model list is loaded and before every request.
//
// Everything the server sends is untrusted: it is reduced by OllamaChat.js
// and shown as plain text only.
ColumnLayout {
    id: ollamaView

    // True while Ollama is shown in the open popup. Nothing is contacted
    // before that.
    property bool current: false
    // "ollama" is enabled in the settings; turning it off clears everything.
    property bool siteEnabled: false
    // Already validated by main.qml (OllamaChat.effectiveAddress).
    property string address: OllamaChat.DEFAULT_ADDRESS
    // appletId only makes the helper's source name unique. createRequest and
    // runOwnerCheck are test seams: overridden by tests only, never in the
    // plasmoid.
    property int appletId: 0
    property var createRequest: function () { return new XMLHttpRequest() }
    property var runOwnerCheck: function (command) { ownerSource.connectSource(command) }

    // Timeouts in ms. Loading a big model on a CPU can take minutes.
    property int firstByteTimeout: 300000
    property int idleTimeout: 120000
    property int probeTimeout: 15000
    property int ownerTimeout: 15000
    // While a reply streams it is read and shown at most this often: each
    // read decodes the whole body again, each refresh lays out the last
    // paragraph again. 0 = every chunk.
    property int renderInterval: 100

    // Installed local chat models, runtime only: [{name, parameterSize, family}]
    property var modelList: []
    property int hiddenRemote: 0
    property string modelName: ""
    // idle (not loaded), loading, ready, failed
    property string listState: "idle"
    // Message code shown above the input; "" when there is none.
    property string problem: ""
    // A server's own error text, already made safe by OllamaChat.
    property string problemDetail: ""
    // Owner check in flight for: "", load, send, unload
    property string checking: ""
    property string ownerSourceName: ""
    // See ChatStorage.firstRun.
    property int ownerRun: ChatStorage.firstRun(Date.now(), Math.random())
    property bool generating: false
    property bool confirmingClear: false
    // Bumped whenever a request is dropped; late events of older ones are ignored.
    property int requestToken: 0
    property var request: null
    property var stream: OllamaChat.newStream()
    property int replyRow: -1
    property string pendingPrompt: ""
    // The pane the pending prompt goes to ("a" or "b"); regenerate resends
    // the last turn instead of adding one.
    property string pendingPane: "a"
    property bool pendingRegenerate: false
    // Compare: the prompt waiting for model B until A is done.
    property string queuedPrompt: ""
    // Each send is a numbered turn; both panes tag its rows with it, so
    // Edit only takes back pane B's copy of the same turn.
    property int turnCounter: 0
    property int pendingTurn: 0
    property int queuedTurn: 0
    // The pane of the reply in flight.
    property string replyPane: "a"
    // Compare: a second pane with its own model and history (D59).
    property bool comparing: false
    property string modelNameB: ""
    // Personalities (system prompts) per model, memory only: {"m:<model>": text}.
    // Clear keeps them; turning Ollama off or a Plasma restart drops them.
    property var sessionPersonas: ({})
    property bool editingPersona: false
    // Whose personality the panel edits while comparing: "a" or "b".
    property string personaTarget: "a"
    property bool personaLoading: false
    // The prompt library from main.qml (saved and this session's items),
    // its saved per-model personalities ({"m:<model>": id}) and whether it
    // is saved (the folder is unlocked).
    property var libraryItems: []
    property var libraryPersonas: ({})
    property bool libraryReady: false
    // The encrypted folder is unlocked (the saved library may be used).
    property bool libraryOpen: false
    // Session personality keys whose text came from a saved item: they
    // leave memory with the library when the folder is locked.
    property var savedPersonaKeys: ({})
    // Saved personalities for the picker: "None" first.
    readonly property var personaChoices: [{ id: 0, kind: "persona", text: "" }].concat(
        PromptLibrary.itemsOf(ollamaView.libraryItems, "persona"))
    // Models used in this conversation; unloaded on Clear.
    property var usedModels: []
    property var unloadNames: []
    // Change handlers wait for this: they also run while the view is built.
    property bool completed: false
    // Ctrl+= / Ctrl+- / Ctrl+0 size of the transcript and message box, from
    // main.qml's zoom map ("ollama").
    property real textScale: 1.0
    // Ctrl+wheel: angle not yet used up (one step per 120, a mouse notch).
    property real wheelZoomAngle: 0
    // The first pane's scrolling (see TranscriptPane): it follows the newest
    // text until the user scrolls up, is held while the user moves it, and
    // offers Back to bottom when scrolled up.
    property alias followTranscript: paneA.follow
    readonly property bool transcriptHeld: paneA.held
    readonly property bool showBackToBottom: paneA.showBackToBottom
    readonly property font bodyFont: ollamaView.scaledFont(Kirigami.Theme.defaultFont)
    readonly property font codeFont: ollamaView.scaledFont(Kirigami.Theme.fixedWidthFont)
    // Between the words of a formatted paragraph.
    readonly property real spaceWidth: bodyMetrics.advanceWidth(" ")
    // Compare panes side by side from this width, else one above the other.
    readonly property bool sideBySide: ollamaView.width >= Kirigami.Units.gridUnit * 40

    property alias messages: transcript
    property alias messagesB: transcriptB
    readonly property int port: OllamaChat.portOf(ollamaView.address)
    readonly property int modelIndex: ollamaView.modelList.map(function (entry) {
        return entry.name
    }).indexOf(ollamaView.modelName)
    readonly property int modelIndexB: ollamaView.modelList.map(function (entry) {
        return entry.name
    }).indexOf(ollamaView.modelNameB)
    // The model whose personality the panel shows.
    readonly property string personaModel: ollamaView.comparing && ollamaView.personaTarget === "b"
        ? ollamaView.modelNameB : ollamaView.modelName
    readonly property bool promptTooLong: input.text.length > OllamaChat.MAX_PROMPT_CHARS
    readonly property bool personaTooLong:
        ollamaView.personaFor(ollamaView.modelName).length > OllamaChat.MAX_SYSTEM_CHARS
        || (ollamaView.comparing
            && ollamaView.personaFor(ollamaView.modelNameB).length > OllamaChat.MAX_SYSTEM_CHARS)
    readonly property bool busy: ollamaView.generating || ollamaView.checking !== ""
        || ollamaView.listState === "loading"
    // Regenerate needs the same as Send, except a typed message.
    readonly property bool canResend: ollamaView.current && ollamaView.siteEnabled
        && ollamaView.listState === "ready" && ollamaView.modelName !== ""
        && (!ollamaView.comparing || ollamaView.modelNameB !== "")
        && !ollamaView.generating && ollamaView.checking === "" && !ollamaView.personaTooLong
    readonly property bool canSend: ollamaView.canResend
        && input.text.trim() !== "" && !ollamaView.promptTooLong
    readonly property bool hasConversation: transcript.count > 0 || transcriptB.count > 0
        || ollamaView.generating

    // +1, -1 or 0 (reset), handled by main.qml.
    signal zoomRequested(int direction)
    // A single text file was dropped (hex: its path, PromptLibrary.hexPath);
    // main.qml reads it and the text comes back through takeDrop.
    signal fileDropped(string hex)
    // Save (id > 0) or clear (-1) the default personality of a model.
    signal personaDefaultChosen(string model, int id)

    spacing: 0
    // Nothing of the view paints outside it (e.g. over the popup's tabs).
    clip: true

    function scaledFont(base) {
        if (ollamaView.textScale === 1.0)
            return base
        var spec = { family: base.family, weight: base.weight, italic: base.italic }
        if (base.pixelSize > 0)
            spec.pixelSize = Math.max(1, Math.round(base.pixelSize * ollamaView.textScale))
        else
            spec.pointSize = base.pointSize * ollamaView.textScale
        return Qt.font(spec)
    }

    // A word of a formatted paragraph: bold, italic, or inline code in the
    // fixed-width font.
    function wordFont(piece) {
        var base = piece.code ? ollamaView.codeFont : ollamaView.bodyFont
        if (!piece.bold && !piece.italic)
            return base
        var spec = { family: base.family, weight: piece.bold ? Font.Bold : base.weight,
                     italic: piece.italic || base.italic }
        if (base.pixelSize > 0)
            spec.pixelSize = base.pixelSize
        else
            spec.pointSize = base.pointSize
        return Qt.font(spec)
    }

    // Bold, 1.35 / 1.2 / 1.1 times the body text for #, ## and ###.
    function headingFont(level) {
        var base = ollamaView.bodyFont
        var factor = level === 1 ? 1.35 : level === 2 ? 1.2 : 1.1
        var spec = { family: base.family, weight: Font.Bold }
        if (base.pixelSize > 0)
            spec.pixelSize = Math.max(1, Math.round(base.pixelSize * factor))
        else
            spec.pointSize = base.pointSize * factor
        return Qt.font(spec)
    }

    // Ctrl+wheel over the conversation or the message box: one step per
    // notch, smaller touchpad moves add up. A plain wheel still scrolls.
    function wheelZoom(wheel) {
        if (!ollamaView.current)
            return
        ollamaView.wheelZoomAngle += wheel.angleDelta.y
        while (Math.abs(ollamaView.wheelZoomAngle) >= 120) {
            var direction = ollamaView.wheelZoomAngle > 0 ? 1 : -1
            ollamaView.wheelZoomAngle -= direction * 120
            ollamaView.zoomRequested(direction)
        }
    }

    function focusInput() {
        if (ollamaView.current)
            input.forceActiveFocus()
    }

    function focusLater() {
        Qt.callLater(ollamaView.focusInput)
    }

    function selectModel(name) {
        if (ollamaView.modelList.some(function (entry) { return entry.name === name }))
            ollamaView.modelName = name
    }

    function selectModelB(name) {
        if (ollamaView.modelList.some(function (entry) { return entry.name === name }))
            ollamaView.modelNameB = name
    }

    // Model B starts as the first model other than A's.
    function secondModel() {
        for (var index = 0; index < ollamaView.modelList.length; index++) {
            if (ollamaView.modelList[index].name !== ollamaView.modelName)
                return ollamaView.modelList[index].name
        }
        return ollamaView.modelName
    }

    // Compare on or off; never while a reply is on its way. Pane B keeps its
    // history while hidden; Clear drops it with the rest.
    function setComparing(on) {
        if (ollamaView.busy)
            return
        ollamaView.comparing = on === true
        if (ollamaView.comparing && ollamaView.modelIndexB < 0)
            ollamaView.modelNameB = ollamaView.secondModel()
        if (!ollamaView.comparing)
            ollamaView.personaTarget = "a"
        ollamaView.focusLater()
    }

    // --- personalities (memory only) -----------------------------------------

    // This session's personality of a model, else its saved default.
    function personaFor(name) {
        var key = "m:" + name
        if (!OllamaChat.isModelName(name))
            return ""
        if (Object.prototype.hasOwnProperty.call(ollamaView.sessionPersonas, key))
            return ollamaView.sessionPersonas[key]
        return PromptLibrary.defaultPersona(ollamaView.libraryItems, ollamaView.libraryPersonas, name)
    }

    // A personality from the library (or None) for the model the panel
    // shows; a saved one also becomes that model's saved default.
    function choosePersona(entry) {
        var model = ollamaView.personaModel
        if (!OllamaChat.isModelName(model) || !entry)
            return
        // "None" is "" at once, before the saved default changes.
        ollamaView.setPersona(model, entry.id === 0 ? "" : entry.text)
        ollamaView.markSavedPersona(model, entry.id > 0)
        if (ollamaView.libraryReady && (entry.id === 0 || entry.id > 0))
            ollamaView.personaDefaultChosen(model, entry.id === 0 ? -1 : entry.id)
        ollamaView.loadPersona()
    }

    // A prompt from the library, put into the message box at the cursor.
    function insertPrompt(text) {
        if (!ollamaView.siteEnabled || input.readOnly)
            return
        var result = PromptLibrary.insertAt(input.text, input.cursorPosition, text, OllamaChat.MAX_PROMPT_CHARS)
        if (!result.ok) {
            ollamaView.problem = "insert-too-long"
            ollamaView.problemDetail = ""
            return
        }
        input.text = result.text
        input.cursorPosition = result.cursor
        ollamaView.focusLater()
    }

    function setPersona(name, text) {
        if (!OllamaChat.isModelName(name) || typeof text !== "string")
            return
        var next = {}
        for (var key in ollamaView.sessionPersonas) {
            if (Object.prototype.hasOwnProperty.call(ollamaView.sessionPersonas, key))
                next[key] = ollamaView.sessionPersonas[key]
        }
        // An empty text is kept too: it means "none", also over a saved default.
        next["m:" + name] = text
        ollamaView.sessionPersonas = next
    }

    // Marks (or unmarks) a model's session personality as taken from the
    // saved library.
    function markSavedPersona(name, saved) {
        var next = {}
        for (var key in ollamaView.savedPersonaKeys) {
            if (Object.prototype.hasOwnProperty.call(ollamaView.savedPersonaKeys, key) && key !== "m:" + name)
                next[key] = true
        }
        if (saved)
            next["m:" + name] = true
        ollamaView.savedPersonaKeys = next
    }

    // The folder was locked: personalities taken from saved items go too.
    function dropSavedPersonas() {
        var next = {}
        for (var key in ollamaView.sessionPersonas) {
            if (Object.prototype.hasOwnProperty.call(ollamaView.sessionPersonas, key)
                    && !Object.prototype.hasOwnProperty.call(ollamaView.savedPersonaKeys, key))
                next[key] = ollamaView.sessionPersonas[key]
        }
        ollamaView.sessionPersonas = next
        ollamaView.savedPersonaKeys = ({})
        ollamaView.loadPersona()
    }

    onLibraryOpenChanged: {
        if (!ollamaView.libraryOpen)
            ollamaView.dropSavedPersonas()
    }

    // The first line, for the small "Personality: …" note above a pane.
    function personaLine(name) {
        var text = ollamaView.personaFor(name).trim()
        if (text === "")
            return ""
        var first = text.split("\n")[0].trim()
        return first.length > 80 ? first.slice(0, 80) + "…" : first
    }

    function loadPersona() {
        ollamaView.personaLoading = true
        personaInput.text = ollamaView.personaFor(ollamaView.personaModel)
        ollamaView.personaLoading = false
    }

    function personaEdited(text) {
        if (ollamaView.personaLoading)
            return
        ollamaView.setPersona(ollamaView.personaModel, text)
        // Typed by the user: their own text now, kept after Lock.
        ollamaView.markSavedPersona(ollamaView.personaModel, false)
    }

    onPersonaModelChanged: ollamaView.loadPersona()
    onEditingPersonaChanged: {
        if (ollamaView.editingPersona) {
            ollamaView.loadPersona()
            Qt.callLater(personaInput.forceActiveFocus)
        } else {
            ollamaView.focusLater()
        }
    }

    function reloadModels() {
        if (!ollamaView.busy)
            ollamaView.load()
    }

    // --- requests -----------------------------------------------------------

    // Forgets the request in flight without touching it.
    function settle() {
        ollamaView.requestToken += 1
        ollamaView.request = null
        readTimer.stop()
        probeTimer.stop()
        firstByteTimer.stop()
        idleTimer.stop()
    }

    // abort() throws in Qt 6.12 even though it aborts; its events arrive
    // with an old token and are ignored.
    function dropRequest() {
        var xhr = ollamaView.request
        ollamaView.settle()
        if (xhr) {
            try {
                xhr.abort()
            } catch (error) {
            }
        }
    }

    function fetch(name, done) {
        ollamaView.dropRequest()
        if (OllamaChat.endpoint(ollamaView.address, name) === "") {
            ollamaView.loadFailed("not-ollama")
            return
        }
        var token = ollamaView.requestToken
        var url = OllamaChat.endpoint(ollamaView.address, name)
        var xhr = ollamaView.createRequest()
        ollamaView.request = xhr
        xhr.onreadystatechange = function () {
            if (token !== ollamaView.requestToken || xhr.readyState < 3)
                return
            if (!ollamaView.answeredAt(xhr, url)) {
                ollamaView.dropRequest()
                ollamaView.loadFailed("not-ollama")
                return
            }
            // A reply this large is no Ollama list; never read.
            if (OllamaChat.tooLarge(xhr.responseText, OllamaChat.MAX_BUFFERED_CHARS)) {
                ollamaView.dropRequest()
                ollamaView.loadFailed("not-ollama")
                return
            }
            if (xhr.readyState !== 4)
                return
            ollamaView.settle()
            done(xhr.status, xhr.responseText)
        }
        xhr.open("GET", OllamaChat.endpoint(ollamaView.address, name))
        xhr.send()
        probeTimer.restart()
    }

    // Qt follows redirects (and sends a POST body again) without showing
    // them; from readyState 3 on, responseURL is the address that answered.
    // A reply from anywhere but the checked endpoint is never read.
    function answeredAt(xhr, url) {
        return typeof xhr.responseURL === "string" && url !== "" && xhr.responseURL === url
    }

    // Owner check → GET /api/version → GET /api/tags. A pending unload check
    // reloads the list itself when it ends.
    function load() {
        if (!ollamaView.current || !ollamaView.siteEnabled || ollamaView.generating
                || ollamaView.checking === "send" || ollamaView.checking === "unload"
                || ollamaView.listState === "loading")
            return
        ollamaView.dropRequest()
        ollamaView.listState = "loading"
        ollamaView.problem = ""
        ollamaView.problemDetail = ""
        ollamaView.checkOwner("load")
    }

    // A failed GET: only a JSON reply from /api/version counts as Ollama.
    function getFailure(status) {
        var failure = OllamaChat.classifyFailure(status)
        return failure === "not-running" || failure === "forbidden" || failure === "server-error"
            ? failure : "not-ollama"
    }

    function probeVersion() {
        ollamaView.fetch("version", function (status, text) {
            if (status !== 200) {
                ollamaView.loadFailed(ollamaView.getFailure(status))
                return
            }
            if (!OllamaChat.parseVersion(status, text).ok) {
                ollamaView.loadFailed("not-ollama")
                return
            }
            ollamaView.listModels()
        })
    }

    function listModels() {
        ollamaView.fetch("tags", function (status, text) {
            var tags = OllamaChat.parseTags(status, text)
            if (!tags.ok) {
                ollamaView.loadFailed(status === 200 ? "not-ollama" : ollamaView.getFailure(status))
                return
            }
            ollamaView.modelList = tags.models
            ollamaView.hiddenRemote = tags.hiddenRemote
            ollamaView.modelName = OllamaChat.pickModel(tags.models, ollamaView.modelName)
            ollamaView.modelNameB = ollamaView.modelNameB === ""
                ? ollamaView.secondModel() : OllamaChat.pickModel(tags.models, ollamaView.modelNameB)
            ollamaView.listState = "ready"
            ollamaView.problem = tags.models.length === 0 ? "no-models" : ""
            ollamaView.problemDetail = ""
        })
    }

    function loadFailed(code) {
        ollamaView.listState = "failed"
        ollamaView.modelList = []
        ollamaView.hiddenRemote = 0
        ollamaView.problem = code
        ollamaView.problemDetail = ""
    }

    // --- port owner check ---------------------------------------------------

    function checkOwner(purpose) {
        ollamaView.cancelOwnerCheck()
        ollamaView.ownerRun = ChatStorage.nextRun(ollamaView.ownerRun)
        // From the address itself: in onAddressChanged the port binding
        // may still hold the old port.
        var command = OllamaChat.ownerCommand(OllamaChat.portOf(ollamaView.address), ollamaView.ownerRun,
            Math.max(0, ChatStorage.validInt(ollamaView.appletId)))
        if (command === "") {
            ollamaView.afterOwnerCheck(purpose, "owner-unknown")
            return
        }
        ollamaView.checking = purpose
        ollamaView.ownerSourceName = command
        checkTimer.interval = ollamaView.ownerTimeout
        checkTimer.restart()
        ollamaView.runOwnerCheck(command)
    }

    function endOwnerCheck() {
        checkTimer.stop()
        ollamaView.ownerSourceName = ""
        ollamaView.checking = ""
    }

    function cancelOwnerCheck() {
        if (ollamaView.ownerSourceName !== "")
            ownerSource.disconnectSource(ollamaView.ownerSourceName)
        var purpose = ollamaView.checking
        ollamaView.endOwnerCheck()
        if (purpose === "load")
            ollamaView.listState = "idle"
        else if (purpose === "send")
            ollamaView.dropPending()
        else if (purpose === "unload")
            ollamaView.unloadNames = []
    }

    // Fails closed: anything but a clear self/system answer stops here.
    function ownerProblem(reply) {
        if (!reply || reply.ok !== true)
            return "owner-unknown"
        if (reply.owner === "none")
            return "not-running"
        if (reply.owner === "other")
            return "other"
        return OllamaChat.trusted(reply.owner) ? "" : "owner-unknown"
    }

    // The helper's reply, already parsed by OllamaChat.parseOwnerReply.
    function ownerDone(source, reply) {
        if (ollamaView.checking === "" || source !== ollamaView.ownerSourceName)
            return
        var purpose = ollamaView.checking
        ollamaView.endOwnerCheck()
        ollamaView.afterOwnerCheck(purpose, ollamaView.ownerProblem(reply))
    }

    function afterOwnerCheck(purpose, problem) {
        switch (purpose) {
        case "load":
            if (problem !== "")
                ollamaView.loadFailed(problem)
            else
                ollamaView.probeVersion()
            break
        case "send":
            if (problem !== "") {
                // The prompt stays in the input; model B gets nothing either.
                ollamaView.dropPending()
                ollamaView.loadFailed(problem)
            } else {
                ollamaView.startChat()
            }
            break
        case "unload":
            var names = ollamaView.unloadNames
            ollamaView.unloadNames = []
            if (problem === "")
                ollamaView.unloadModels(names)
            if (ollamaView.listState === "idle" || ollamaView.listState === "failed")
                ollamaView.load()
            break
        }
    }

    // --- chat -----------------------------------------------------------------

    function paneRows(pane) {
        return pane === "b" ? transcriptB : transcript
    }

    function paneModel(pane) {
        return pane === "b" ? ollamaView.modelNameB : ollamaView.modelName
    }

    function paneView(pane) {
        return pane === "b" ? paneB : paneA
    }

    // [{author}] of a transcript model, for OllamaChat.lastTurn.
    function authorsOf(rows) {
        var list = []
        for (var index = 0; rows && index < rows.count; index++)
            list.push({ author: rows.get(index).author })
        return list
    }

    function dropPending() {
        ollamaView.pendingTurn = 0
        ollamaView.queuedTurn = 0
        ollamaView.pendingPrompt = ""
        ollamaView.pendingPane = "a"
        ollamaView.pendingRegenerate = false
        ollamaView.queuedPrompt = ""
    }

    // The messages before row end of rows, then prompt.
    function historyWith(prompt, rows, end) {
        var history = []
        for (var index = 0; index < end; index++) {
            var row = rows.get(index)
            if (row.body !== "")
                history.push({ role: row.author, content: row.body })
        }
        history.push({ role: "user", content: prompt })
        return history
    }

    // While comparing, the same prompt goes to model B once A is done.
    function send() {
        if (!ollamaView.canSend)
            return
        ollamaView.pendingPrompt = input.text
        ollamaView.pendingPane = "a"
        ollamaView.pendingRegenerate = false
        ollamaView.queuedPrompt = ollamaView.comparing ? input.text : ""
        ollamaView.turnCounter = ollamaView.turnCounter >= 2147483647 ? 1 : ollamaView.turnCounter + 1
        ollamaView.pendingTurn = ollamaView.turnCounter
        ollamaView.queuedTurn = ollamaView.comparing ? ollamaView.turnCounter : 0
        ollamaView.problem = ""
        ollamaView.problemDetail = ""
        ollamaView.checkOwner("send")
    }

    // The last reply of a pane again: the same history goes to the pane's
    // model, after its own owner check; the old reply is dropped once the
    // new request goes out.
    function regenerate(pane) {
        var rows = ollamaView.paneRows(pane)
        var turn = OllamaChat.lastTurn(ollamaView.authorsOf(rows))
        if (!ollamaView.canResend || turn.assistantIndex < 0 || turn.userIndex !== turn.assistantIndex - 1)
            return
        ollamaView.pendingPrompt = rows.get(turn.userIndex).body
        ollamaView.pendingPane = pane === "b" ? "b" : "a"
        ollamaView.pendingRegenerate = true
        ollamaView.queuedPrompt = ""
        ollamaView.problem = ""
        ollamaView.problemDetail = ""
        ollamaView.checkOwner("send")
    }

    // The last message back into the message box; it and its reply leave
    // the conversation (also pane B's, when it got the same turn).
    // Nothing is sent until Send.
    function editLast() {
        if (ollamaView.busy)
            return
        var turn = OllamaChat.lastTurn(ollamaView.authorsOf(transcript))
        if (turn.userIndex < 0)
            return
        var text = transcript.get(turn.userIndex).body
        var number = transcript.get(turn.userIndex).turn
        var turnB = OllamaChat.lastTurn(ollamaView.authorsOf(transcriptB))
        // Only pane B's copy of this very turn, never an older one with the
        // same text.
        if (ollamaView.comparing && turnB.userIndex >= 0 && typeof number === "number" && number > 0
                && transcriptB.get(turnB.userIndex).turn === number)
            transcriptB.remove(turnB.userIndex, transcriptB.count - turnB.userIndex)
        transcript.remove(turn.userIndex, transcript.count - turn.userIndex)
        input.text = text
        input.cursorPosition = input.length
        ollamaView.focusLater()
    }

    function startChat() {
        var prompt = ollamaView.pendingPrompt
        var pane = ollamaView.pendingPane === "b" ? "b" : "a"
        var regenerating = ollamaView.pendingRegenerate
        var turnNumber = ollamaView.pendingTurn
        ollamaView.pendingTurn = 0
        ollamaView.pendingPrompt = ""
        ollamaView.pendingPane = "a"
        ollamaView.pendingRegenerate = false
        var rows = ollamaView.paneRows(pane)
        var name = ollamaView.paneModel(pane)
        var turn = OllamaChat.lastTurn(ollamaView.authorsOf(rows))
        // Regenerate: the turn must still be the one it was asked for.
        var end = rows.count
        if (regenerating) {
            end = turn.assistantIndex >= 0 && turn.userIndex === turn.assistantIndex - 1
                && rows.get(turn.userIndex).body === prompt ? turn.userIndex : -1
        }
        var body = end < 0 ? "" : OllamaChat.chatRequestBody(name,
            ollamaView.historyWith(prompt, rows, end), ollamaView.personaFor(name))
        if (body === "" || OllamaChat.endpoint(ollamaView.address, "chat") === "") {
            ollamaView.queuedPrompt = ""
            ollamaView.problem = "not-sent"
            return
        }
        if (regenerating)
            rows.remove(turn.assistantIndex, rows.count - turn.assistantIndex)
        else if (pane === "a")
            input.text = ""
        // Sending always jumps to the bottom and follows the reply.
        var view = ollamaView.paneView(pane)
        view.follow = true
        view.sentWhileHeld = view.held
        if (!regenerating)
            rows.append({ author: "user", body: prompt, phase: "done", turn: turnNumber })
        rows.append({ author: "assistant", body: "", phase: "waiting",
                      turn: regenerating ? rows.get(rows.count - 1).turn : turnNumber })
        ollamaView.replyRow = rows.count - 1
        ollamaView.replyPane = pane
        if (ollamaView.usedModels.indexOf(name) < 0)
            ollamaView.usedModels = ollamaView.usedModels.concat([name])
        ollamaView.generating = true
        ollamaView.stream = OllamaChat.newStream()
        ollamaView.dropRequest()
        var token = ollamaView.requestToken
        var url = OllamaChat.endpoint(ollamaView.address, "chat")
        var xhr = ollamaView.createRequest()
        ollamaView.request = xhr
        xhr.onreadystatechange = function () {
            if (token !== ollamaView.requestToken)
                return
            if (xhr.readyState === 3 || xhr.readyState === 4)
                ollamaView.chatProgress(xhr, url, xhr.readyState === 4)
        }
        xhr.open("POST", OllamaChat.endpoint(ollamaView.address, "chat"))
        xhr.setRequestHeader("Content-Type", "application/json")
        xhr.send(body)
        firstByteTimer.interval = ollamaView.firstByteTimeout
        firstByteTimer.restart()
        Qt.callLater(view.pin)
    }

    function chatProgress(xhr, url, finished) {
        if (!ollamaView.answeredAt(xhr, url)) {
            // Redirected: nothing from there is read or shown.
            ollamaView.dropRequest()
            ollamaView.stream = OllamaChat.newStream()
            ollamaView.finishChat("failed", "server-error", "")
            return
        }
        var status = xhr.status
        if (status !== 200) {
            var failure = OllamaChat.classifyFailure(status)
            if (failure === "unexpected")
                failure = "server-error"
            // An error reply over the limit is dropped unread.
            if (OllamaChat.tooLarge(xhr.responseText, OllamaChat.MAX_ERROR_REPLY_CHARS)) {
                ollamaView.dropRequest()
                ollamaView.finishChat("failed", failure, "")
                return
            }
            // Wait for the whole error reply.
            if (!finished)
                return
            var detail = failure === "server-error" ? OllamaChat.errorReplyDetail(xhr.responseText) : ""
            ollamaView.finishChat("failed", failure, detail)
            return
        }
        firstByteTimer.stop()
        if (!finished) {
            idleTimer.interval = ollamaView.idleTimeout
            idleTimer.restart()
            if (ollamaView.renderInterval > 0) {
                if (!readTimer.running)
                    readTimer.start()
                return
            }
        }
        ollamaView.readReply(xhr, finished)
    }

    // Reads what has arrived of the reply (already checked by chatProgress)
    // and puts it on screen.
    function readReply(xhr, finished) {
        readTimer.stop()
        var next = OllamaChat.feedStream(ollamaView.stream, xhr.responseText, finished)
        ollamaView.stream = next
        if (next.error === "too-long") {
            ollamaView.dropRequest()
            ollamaView.finishChat("cut", "", "")
        } else if (next.error === "server") {
            ollamaView.finishChat("failed", "server-error", next.errorText)
        } else if (next.error !== "") {
            ollamaView.finishChat("failed", "server-error", "")
        } else if (next.done) {
            ollamaView.finishChat("done", "", "")
        } else if (finished) {
            // The connection ended without "done".
            ollamaView.finishChat("failed", "timeout", "")
        } else {
            ollamaView.render()
        }
    }

    // Puts the reply read so far on screen.
    function render() {
        var rows = ollamaView.paneRows(ollamaView.replyPane)
        var row = ollamaView.replyRow
        if (row < 0 || row >= rows.count)
            return
        var next = ollamaView.stream
        var phase = next.content !== "" ? "streaming" : next.thinking ? "thinking" : "waiting"
        // The transcript follows through its contentHeight handler.
        if (rows.get(row).body !== next.content)
            rows.setProperty(row, "body", next.content)
        if (rows.get(row).phase !== phase)
            rows.setProperty(row, "phase", phase)
    }

    // phase of the reply row: done, stopped, cut, failed. An empty reply
    // that didn't finish is removed; the user's message stays.
    function finishChat(phase, problem, detail) {
        ollamaView.render()
        ollamaView.settle()
        ollamaView.generating = false
        ollamaView.stream = OllamaChat.newStream()
        var rows = ollamaView.paneRows(ollamaView.replyPane)
        var pane = ollamaView.replyPane
        var row = ollamaView.replyRow
        ollamaView.replyRow = -1
        ollamaView.replyPane = "a"
        if (row >= 0 && row < rows.count) {
            if (rows.get(row).body === "" && phase !== "done")
                rows.remove(row)
            else
                rows.setProperty(row, "phase", phase)
        }
        ollamaView.problem = problem
        ollamaView.problemDetail = detail
        if (problem === "not-running" || problem === "forbidden")
            ollamaView.listState = "failed"
        var queued = ollamaView.queuedPrompt
        var queuedTurn = ollamaView.queuedTurn
        ollamaView.queuedPrompt = ""
        ollamaView.queuedTurn = 0
        // Compare runs one model after the other: B gets the prompt once A
        // is done, with an owner check of its own. Not after Stop, or when
        // the server is gone or stopped answering.
        if (queued !== "" && pane === "a" && ollamaView.comparing && ollamaView.siteEnabled
                && ollamaView.listState === "ready" && ollamaView.modelNameB !== ""
                && phase !== "stopped" && problem !== "timeout") {
            ollamaView.pendingPrompt = queued
            ollamaView.pendingPane = "b"
            ollamaView.pendingRegenerate = false
            ollamaView.pendingTurn = queuedTurn
            ollamaView.checkOwner("send")
        }
        ollamaView.focusLater()
    }

    // Send turns into Stop while a reply is coming; Esc does the same.
    function stop() {
        // Model B never starts after a Stop.
        ollamaView.queuedPrompt = ""
        if (ollamaView.checking === "send") {
            ollamaView.cancelOwnerCheck()
            return
        }
        // What arrived since the last read is shown too.
        if (readTimer.running && ollamaView.request)
            ollamaView.readReply(ollamaView.request, false)
        if (!ollamaView.generating)
            return
        ollamaView.dropRequest()
        ollamaView.finishChat("stopped", "", "")
    }

    // Drops the conversation (both panes) from memory; personalities stay.
    // With unload, Ollama is also asked to unload the models used
    // (keep_alive 0), which drops its cache of the conversation; that
    // request carries no prompt.
    function clearConversation(unload) {
        ollamaView.confirmingClear = false
        var names = ollamaView.usedModels
        ollamaView.cancelOwnerCheck()
        ollamaView.dropRequest()
        ollamaView.generating = false
        ollamaView.dropPending()
        ollamaView.stream = OllamaChat.newStream()
        ollamaView.replyRow = -1
        ollamaView.replyPane = "a"
        ollamaView.usedModels = []
        transcript.clear()
        transcriptB.clear()
        input.text = ""
        if (ollamaView.listState === "ready") {
            ollamaView.problem = ollamaView.modelList.length === 0 ? "no-models" : ""
            ollamaView.problemDetail = ""
        }
        gc()
        if (unload && names.length > 0 && ollamaView.current && ollamaView.siteEnabled) {
            ollamaView.unloadNames = names
            ollamaView.checkOwner("unload")
        } else if (ollamaView.listState === "idle") {
            ollamaView.load()
        }
        ollamaView.focusLater()
    }

    function unloadModels(names) {
        for (var index = 0; index < names.length; index++) {
            var body = OllamaChat.unloadRequestBody(names[index])
            if (body === "" || OllamaChat.endpoint(ollamaView.address, "chat") === "")
                continue
            // Fire and forget; the reply is never read.
            var xhr = ollamaView.createRequest()
            xhr.open("POST", OllamaChat.endpoint(ollamaView.address, "chat"))
            xhr.setRequestHeader("Content-Type", "application/json")
            xhr.send(body)
        }
    }

    // Word wrapping a long run without spaces gets very slow (quadratic in
    // Qt's text layout); such text wraps anywhere instead.
    function wrapFor(text) {
        return /\S{120}/.test(text) ? TextEdit.WrapAnywhere : TextEdit.Wrap
    }

    // A user-chosen text, copied through a hidden plain text field.
    function copyText(text) {
        copyHelper.text = text
        copyHelper.selectAll()
        copyHelper.copy()
        copyHelper.text = ""
    }

    // --- drag and drop ----------------------------------------------------------

    // Text dropped on the chat (or the panel icon, through main.qml) goes
    // into the message box after what is typed; it is never sent from here
    // (D62). Files are refused until they can be read safely.
    function takeDrop(text) {
        if (!ollamaView.siteEnabled || input.readOnly)
            return
        var result = OllamaChat.dropText(text, input.text)
        if (!result.ok) {
            if (result.error === "too-long")
                ollamaView.problem = "drop-too-long"
            else if (result.error === "not-text")
                ollamaView.problem = "drop-file"
            ollamaView.problemDetail = ""
            return
        }
        if (ollamaView.problem.indexOf("drop-") === 0 || ollamaView.problem === "insert-too-long")
            ollamaView.problem = ""
        input.text = result.text
        input.cursorPosition = input.length
        ollamaView.focusLater()
    }

    // From the drop areas: true when the drop was taken (as a copy, so the
    // source never deletes anything). hex is the path of a single local
    // file (else ""): main.qml reads it. Other files and links are refused.
    function textDropped(hasText, hasUrls, text, hex) {
        if (!ollamaView.current || !ollamaView.siteEnabled)
            return false
        if (hasUrls && typeof hex === "string" && hex !== "" && !input.readOnly) {
            if (ollamaView.problem.indexOf("drop-") === 0)
                ollamaView.problem = ""
            ollamaView.fileDropped(hex)
            return true
        }
        if (hasUrls) {
            ollamaView.problem = "drop-file"
            ollamaView.problemDetail = ""
            return false
        }
        if (!hasText)
            return false
        ollamaView.takeDrop(text)
        return true
    }

    // A dropped file gave no text (PromptLibrary error code).
    function dropFailed(code) {
        switch (code) {
        case "too-large":
            ollamaView.problem = "drop-too-large"
            break
        case "too-long":
            ollamaView.problem = "drop-too-long"
            break
        case "not-text":
            ollamaView.problem = "drop-not-text"
            break
        default:
            ollamaView.problem = "drop-unreadable"
        }
        ollamaView.problemDetail = ""
    }

    // Fixed texts only; the address is never shown, only its port.
    function problemText(code) {
        switch (code) {
        case "":
            return ""
        case "not-running":
            return i18n("Ollama isn't running.")
        case "other":
            return i18n("Another user's program is using port %1. Hearthwire won't send anything to it.", ollamaView.port)
        case "owner-unknown":
            return i18n("Couldn't check which program is using port %1.", ollamaView.port)
        case "not-ollama":
            return i18n("Something other than Ollama is answering at this address.")
        case "forbidden":
            return i18n("Ollama refused the request.")
        case "no-models":
            return i18n("No models installed. In a terminal run:")
        case "model-missing":
            return i18n("This model isn't installed any more.")
        case "timeout":
            return i18n("Ollama stopped responding.")
        case "not-sent":
            return i18n("Couldn't send this message.")
        case "drop-file":
            return i18n("Drop text, not files.")
        case "drop-too-long":
            return i18n("This text is too long to drop here. A message can have at most %1 characters.",
                OllamaChat.MAX_PROMPT_CHARS)
        case "drop-too-large":
            return i18n("This file is too big. Drop a text file of at most 128 KB.")
        case "drop-not-text":
            return i18n("This file isn't plain text.")
        case "drop-unreadable":
            return i18n("Couldn't read this file.")
        case "insert-too-long":
            return i18n("This prompt doesn't fit: a message can have at most %1 characters.",
                OllamaChat.MAX_PROMPT_CHARS)
        default:
            return i18n("Ollama reported an error.")
        }
    }

    function problemHint(code) {
        switch (code) {
        case "not-running":
            return "systemctl start ollama   (or run: ollama serve)"
        case "no-models":
            return "ollama pull llama3"
        default:
            return ""
        }
    }

    onCurrentChanged: {
        if (!ollamaView.completed || !ollamaView.current)
            return
        if (ollamaView.listState === "idle" || ollamaView.listState === "failed")
            ollamaView.load()
        ollamaView.focusLater()
    }
    onSiteEnabledChanged: {
        if (!ollamaView.completed)
            return
        if (ollamaView.siteEnabled) {
            if (ollamaView.current)
                ollamaView.load()
            return
        }
        ollamaView.clearConversation(false)
        ollamaView.cancelOwnerCheck()
        // Personalities are kept for the session only while Ollama is on.
        ollamaView.sessionPersonas = ({})
        ollamaView.savedPersonaKeys = ({})
        ollamaView.editingPersona = false
        ollamaView.comparing = false
        ollamaView.personaTarget = "a"
        ollamaView.loadPersona()
        ollamaView.listState = "idle"
        ollamaView.modelList = []
        ollamaView.hiddenRemote = 0
        ollamaView.problem = ""
        ollamaView.problemDetail = ""
    }
    // A new address: the old model list and any reply in flight belong to
    // the old server. The conversation stays.
    onAddressChanged: {
        if (!ollamaView.completed)
            return
        if (ollamaView.generating)
            ollamaView.stop()
        ollamaView.cancelOwnerCheck()
        ollamaView.dropRequest()
        ollamaView.listState = "idle"
        ollamaView.modelList = []
        ollamaView.hiddenRemote = 0
        ollamaView.problem = ""
        ollamaView.problemDetail = ""
        if (ollamaView.current)
            ollamaView.load()
    }

    // The popup may be created with Ollama already shown.
    Component.onCompleted: {
        ollamaView.completed = true
        if (ollamaView.current) {
            ollamaView.load()
            ollamaView.focusLater()
        }
    }

    // Accepted, so Esc stops a reply without closing the popup; otherwise it
    // passes on as usual.
    Keys.onEscapePressed: (event) => {
        if (ollamaView.generating || ollamaView.checking === "send") {
            ollamaView.stop()
            event.accepted = true
        } else {
            event.accepted = false
        }
    }

    ListModel {
        id: transcript
    }

    // Compare: model B's conversation.
    ListModel {
        id: transcriptB
    }

    FontMetrics {
        id: bodyMetrics
        font: ollamaView.bodyFont
    }

    Shortcut {
        sequences: [StandardKey.ZoomIn, "Ctrl+="]
        enabled: ollamaView.current
        onActivated: ollamaView.zoomRequested(1)
    }
    Shortcut {
        sequences: [StandardKey.ZoomOut]
        enabled: ollamaView.current
        onActivated: ollamaView.zoomRequested(-1)
    }
    Shortcut {
        sequence: "Ctrl+0"
        enabled: ollamaView.current
        onActivated: ollamaView.zoomRequested(0)
    }

    Plasma5Support.DataSource {
        id: ownerSource
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            ownerSource.disconnectSource(source)
            // Only stdout's known words are used.
            ollamaView.ownerDone(source, OllamaChat.parseOwnerReply(data["exit code"], data["stdout"]))
        }
    }

    Timer {
        id: readTimer
        interval: ollamaView.renderInterval
        repeat: false
        onTriggered: {
            if (ollamaView.request)
                ollamaView.readReply(ollamaView.request, false)
        }
    }

    Timer {
        id: checkTimer
        repeat: false
        onTriggered: {
            var purpose = ollamaView.checking
            ollamaView.cancelOwnerCheck()
            ollamaView.afterOwnerCheck(purpose, "owner-unknown")
        }
    }

    Timer {
        id: probeTimer
        interval: ollamaView.probeTimeout
        repeat: false
        onTriggered: {
            ollamaView.dropRequest()
            ollamaView.loadFailed("timeout")
        }
    }

    Timer {
        id: firstByteTimer
        repeat: false
        onTriggered: {
            ollamaView.dropRequest()
            ollamaView.finishChat("failed", "timeout", "")
        }
    }

    Timer {
        id: idleTimer
        repeat: false
        onTriggered: {
            ollamaView.dropRequest()
            ollamaView.finishChat("failed", "timeout", "")
        }
    }

    // Never shown; holds a copied text only for the moment of the copy.
    TextEdit {
        id: copyHelper
        visible: false
        readOnly: true
        textFormat: TextEdit.PlainText
    }

    Kirigami.InlineMessage {
        objectName: "clearConfirm"
        Layout.fillWidth: true
        visible: ollamaView.confirmingClear
        type: Kirigami.MessageType.Warning
        text: i18n("Clear this conversation?")
        actions: [
            Kirigami.Action {
                text: i18n("Clear")
                icon.name: "edit-clear-history"
                onTriggered: ollamaView.clearConversation(true)
            },
            Kirigami.Action {
                text: i18n("Cancel")
                icon.name: "dialog-cancel"
                onTriggered: ollamaView.confirmingClear = false
            }
        ]
    }

    // The personality of a model (its system prompt), held in memory only
    // and sent first with every message to that model.
    ColumnLayout {
        objectName: "personaPanel"
        Layout.fillWidth: true
        Layout.margins: Kirigami.Units.largeSpacing
        visible: ollamaView.editingPersona
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            PlasmaComponents.Label {
                Layout.fillWidth: true
                textFormat: Text.PlainText
                elide: Text.ElideRight
                text: ollamaView.personaModel !== ""
                    ? i18n("Personality for %1", ollamaView.personaModel)
                    : i18n("Personality")
            }
            PlasmaComponents.ToolButton {
                objectName: "personaForA"
                visible: ollamaView.comparing
                checked: ollamaView.personaTarget === "a"
                text: i18n("Model A")
                onClicked: ollamaView.personaTarget = "a"
            }
            PlasmaComponents.ToolButton {
                objectName: "personaForB"
                visible: ollamaView.comparing
                checked: ollamaView.personaTarget === "b"
                text: i18n("Model B")
                onClicked: ollamaView.personaTarget = "b"
            }
            PlasmaComponents.ToolButton {
                icon.name: "window-close"
                display: QQC2.AbstractButton.IconOnly
                text: i18n("Close")
                onClicked: ollamaView.editingPersona = false
                QQC2.ToolTip.text: text
                QQC2.ToolTip.visible: hovered
            }
        }
        // Saved personalities (and this session's) from the prompt library.
        // QQC2's: Plasma's ComboBox loops on its implicit height here.
        QQC2.ComboBox {
            id: personaPicker
            objectName: "personaPicker"
            Layout.fillWidth: true
            // Fixed: sizing to the choices (user text) loops.
            implicitWidth: Kirigami.Units.gridUnit * 10
            visible: ollamaView.personaChoices.length > 1
            enabled: ollamaView.personaModel !== ""
            model: ollamaView.personaChoices
            currentIndex: -1
            // A fixed text: the choices are user text, shown only by the
            // delegate below as plain text.
            displayText: i18n("Choose a saved personality…")
            onActivated: (index) => {
                ollamaView.choosePersona(ollamaView.personaChoices[index])
                personaPicker.currentIndex = -1
            }

            delegate: PlasmaComponents.ItemDelegate {
                id: personaDelegate
                required property var modelData
                required property int index
                width: ListView.view ? ListView.view.width : implicitWidth
                highlighted: personaPicker.highlightedIndex === personaDelegate.index
                contentItem: PlasmaComponents.Label {
                    textFormat: Text.PlainText
                    elide: Text.ElideRight
                    text: personaDelegate.modelData.id === 0 ? i18n("None")
                        : PromptLibrary.label(personaDelegate.modelData.text)
                }
            }
        }
        QQC2.ScrollView {
            Layout.fillWidth: true
            Layout.preferredHeight: Kirigami.Units.gridUnit * 4
            QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff
            clip: true

            PlasmaComponents.TextArea {
                id: personaInput
                objectName: "personaInput"
                enabled: ollamaView.personaModel !== ""
                wrapMode: TextEdit.Wrap
                textFormat: TextEdit.PlainText
                font: ollamaView.bodyFont
                Kirigami.SpellCheck.enabled: false
                inputMethodHints: Qt.ImhNoPredictiveText | Qt.ImhSensitiveData
                placeholderText: i18n("How this model should answer, e.g. “Answer briefly, in German.”")
                Accessible.name: i18n("Personality")
                onTextChanged: ollamaView.personaEdited(personaInput.text)
            }
        }
        PlasmaComponents.Label {
            Layout.fillWidth: true
            visible: ollamaView.personaTooLong
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            color: Kirigami.Theme.negativeTextColor
            text: i18n("A personality can have at most %1 characters.", OllamaChat.MAX_SYSTEM_CHARS)
        }
        PlasmaComponents.Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            opacity: 0.72
            font: Kirigami.Theme.smallFont
            text: i18n("Sent first with every message to this model. Kept in memory only: gone when Ollama is turned off or Plasma restarts.")
        }
    }

    PlasmaComponents.Label {
        objectName: "compareHint"
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.largeSpacing
        Layout.rightMargin: Kirigami.Units.largeSpacing
        Layout.topMargin: Kirigami.Units.smallSpacing
        visible: ollamaView.comparing && !ollamaView.sideBySide
        wrapMode: Text.WordWrap
        textFormat: Text.PlainText
        opacity: 0.72
        font: Kirigami.Theme.smallFont
        text: i18n("For the answers side by side, set Settings → General → Size to Large.")
    }

    Item {
        Layout.fillWidth: true
        Layout.fillHeight: true
        // Keeps the panes and Back to bottom inside this area.
        clip: true

        GridLayout {
            anchors.fill: parent
            columns: ollamaView.sideBySide ? 2 : 1
            rowSpacing: 0
            columnSpacing: 0

            TranscriptPane {
                id: paneA
                paneId: "a"
                rows: transcript
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1
                Layout.preferredHeight: 1
                showModel: ollamaView.comparing
                modelLabel: ollamaView.modelName
                personaText: ollamaView.personaLine(ollamaView.modelName)
            }
            TranscriptPane {
                id: paneB
                paneId: "b"
                rows: transcriptB
                visible: ollamaView.comparing
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1
                Layout.preferredHeight: 1
                showModel: true
                modelLabel: ollamaView.modelNameB
                personaText: ollamaView.personaLine(ollamaView.modelNameB)
            }
        }
        TextDropArea {
            anchors.fill: parent
        }
    }

    // Status and errors, above the input.
    ColumnLayout {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.largeSpacing
        Layout.rightMargin: Kirigami.Units.largeSpacing
        Layout.topMargin: Kirigami.Units.smallSpacing
        visible: ollamaView.problem !== "" || ollamaView.promptTooLong
        spacing: Kirigami.Units.smallSpacing

        PlasmaComponents.Label {
            objectName: "problemText"
            Layout.fillWidth: true
            visible: ollamaView.problem !== ""
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            color: ollamaView.problem === "no-models"
                ? Kirigami.Theme.textColor : Kirigami.Theme.negativeTextColor
            text: ollamaView.problemText(ollamaView.problem)
        }
        QQC2.TextField {
            objectName: "problemHint"
            Layout.fillWidth: true
            visible: text !== ""
            readOnly: true
            selectByMouse: true
            font: Kirigami.Theme.fixedWidthFont
            text: ollamaView.problemHint(ollamaView.problem)
        }
        PlasmaComponents.Label {
            objectName: "problemDetail"
            Layout.fillWidth: true
            visible: ollamaView.problemDetail !== ""
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            opacity: 0.72
            text: ollamaView.problemDetail
        }
        PlasmaComponents.Label {
            Layout.fillWidth: true
            visible: ollamaView.problem === "no-models" && ollamaView.hiddenRemote > 0
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            opacity: 0.72
            text: i18n("Cloud models are hidden because they send your messages to ollama.com.")
        }
        PlasmaComponents.Label {
            Layout.fillWidth: true
            visible: ollamaView.promptTooLong
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            color: Kirigami.Theme.negativeTextColor
            text: i18n("This message is too long. A message can have at most %1 characters.",
                OllamaChat.MAX_PROMPT_CHARS)
        }
        PlasmaComponents.Button {
            objectName: "retryButton"
            visible: ollamaView.listState === "failed"
                || ollamaView.problem === "no-models" || ollamaView.problem === "model-missing"
            enabled: !ollamaView.busy
            icon.name: "view-refresh"
            text: ollamaView.listState === "failed" ? i18n("Retry") : i18n("Reload models")
            onClicked: ollamaView.load()
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.margins: Kirigami.Units.largeSpacing
        spacing: Kirigami.Units.smallSpacing

        QQC2.ScrollView {
            id: inputScroll
            objectName: "inputScroll"
            Layout.fillWidth: true
            Layout.maximumHeight: Kirigami.Units.gridUnit * 8
            QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff
            // A long message scrolls inside the box, never over the transcript.
            clip: true

            PlasmaComponents.TextArea {
                id: input
                objectName: "ollamaInput"
                // Locked only while the port is checked for this message.
                readOnly: ollamaView.checking === "send"
                wrapMode: TextEdit.Wrap
                textFormat: TextEdit.PlainText
                font: ollamaView.bodyFont
                Kirigami.SpellCheck.enabled: false
                inputMethodHints: Qt.ImhNoPredictiveText | Qt.ImhSensitiveData
                placeholderText: i18n("Message (Enter sends, Shift+Enter adds a line)")
                Accessible.name: i18n("Message to Ollama")
                Keys.onPressed: (event) => {
                    if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
                            && !(event.modifiers & Qt.ShiftModifier)) {
                        event.accepted = true
                        ollamaView.send()
                    }
                }
            }
        }
        // Above the message box and its style's own wheel handling, so
        // Ctrl+wheel always zooms; any other wheel passes on and scrolls.
        // It takes no clicks, hover or focus. Drops land here too, never in
        // the text area's own drop handling.
        Item {
            parent: inputScroll
            anchors.fill: parent
            z: 10

            WheelHandler {
                objectName: "inputWheelZoom"
                target: null
                acceptedModifiers: Qt.ControlModifier
                onWheel: (wheel) => ollamaView.wheelZoom(wheel)
            }
            TextDropArea {
                anchors.fill: parent
            }
        }
        PlasmaComponents.Button {
            id: sendButton
            objectName: "sendButton"
            readonly property bool stopping: ollamaView.generating || ollamaView.checking === "send"
            Layout.alignment: Qt.AlignBottom
            enabled: sendButton.stopping || ollamaView.canSend
            icon.name: sendButton.stopping ? "media-playback-stop" : "document-send"
            text: sendButton.stopping ? i18n("Stop") : i18n("Send")
            onClicked: {
                if (sendButton.stopping)
                    ollamaView.stop()
                else
                    ollamaView.send()
            }
        }
    }

    // Text from another program, dragged onto the chat. It only ever reads
    // whether the drag has text or files, and the text; it never sends.
    component TextDropArea: DropArea {
        enabled: ollamaView.current && ollamaView.siteEnabled
        onEntered: (drag) => {
            // Files are let in only to say why they are refused.
            if (drag.hasText || drag.hasUrls)
                drag.accept(Qt.CopyAction)
            else
                drag.accepted = false
        }
        onDropped: (drop) => {
            if (ollamaView.textDropped(drop.hasText, drop.hasUrls, drop.hasText ? drop.text : "",
                    drop.hasUrls && drop.urls.length === 1 ? PromptLibrary.hexPath(drop.urls[0]) : ""))
                drop.accept(Qt.CopyAction)
            else
                drop.accepted = false
        }
    }

    // A paragraph or list item of a reply. Without formatting it is one
    // selectable plain text; with it, one plain Text per word in a Flow
    // (bold, italic, inline code), so nothing is ever parsed as markup.
    component ReplyParagraph: Item {
        id: paragraph

        property var spans: []
        // Set directly, never from a layout pass (see textWidth below).
        property real textWidth: 0
        readonly property bool styled: OllamaChat.isStyled(paragraph.spans)
        // The width unwrapped; formatted text takes all it is given.
        readonly property real naturalWidth: paragraph.styled ? Infinity : plainText.implicitWidth

        width: paragraph.textWidth
        implicitHeight: paragraph.styled ? wordFlow.height : plainText.height

        TextEdit {
            id: plainText
            visible: !paragraph.styled
            width: paragraph.textWidth
            readOnly: true
            selectByMouse: true
            wrapMode: ollamaView.wrapFor(plainText.text)
            textFormat: TextEdit.PlainText
            color: Kirigami.Theme.textColor
            selectionColor: Kirigami.Theme.highlightColor
            selectedTextColor: Kirigami.Theme.highlightedTextColor
            font: ollamaView.bodyFont
            text: paragraph.styled ? "" : OllamaChat.spansText(paragraph.spans)
        }
        Flow {
            id: wordFlow
            objectName: "replyWords"
            visible: paragraph.styled
            width: paragraph.textWidth

            Repeater {
                model: paragraph.styled ? OllamaChat.flowWords(paragraph.spans) : []

                delegate: Item {
                    id: word
                    required property var modelData
                    // A line break takes a whole row of no height.
                    width: word.modelData.br ? wordFlow.width
                        : wordText.width + (word.modelData.space ? ollamaView.spaceWidth : 0)
                    height: word.modelData.br ? 0 : wordText.height

                    Rectangle {
                        visible: word.modelData.code
                        anchors.fill: wordText
                        radius: Kirigami.Units.smallSpacing / 2
                        color: Kirigami.Theme.alternateBackgroundColor
                    }
                    Text {
                        id: wordText
                        visible: !word.modelData.br
                        width: Math.min(wordText.implicitWidth, wordFlow.width)
                        wrapMode: Text.WrapAnywhere
                        textFormat: Text.PlainText
                        color: Kirigami.Theme.textColor
                        font: ollamaView.wordFont(word.modelData)
                        text: word.modelData.text
                    }
                }
            }
        }
    }

    // One conversation: its transcript with its own wheel handling,
    // following and Back to bottom. Compare shows a second one (pane "b")
    // for model B, with the same behaviour.
    component TranscriptPane: Item {
        id: pane

        // "a" or "b": which conversation this is.
        property string paneId: "a"
        property ListModel rows: null
        // Shown above the transcript while comparing.
        property bool showModel: false
        property string modelLabel: ""
        property string personaText: ""
        // The transcript follows the newest text until the user scrolls up;
        // back at the bottom, or on the next send, it follows again.
        property bool follow: true
        // A message was sent while the transcript was held.
        property bool sentWhileHeld: false
        // The user is moving the transcript (drag, flick, wheel, scroll
        // bar): it is never pinned meanwhile.
        readonly property bool held: list.moving || bar.pressed || wheelSettle.running
        // Scrolled up away from the newest text: Back to bottom is offered.
        // Updated after each change, not bound: reading the list's geometry
        // in a binding while its reply blocks resize loops.
        property bool showBackToBottom: false
        // Where Regenerate and Edit are offered.
        readonly property var turn: OllamaChat.lastTurn(ollamaView.authorsOf(pane.rows !== null
            && pane.rows.count >= 0 ? pane.rows : null))

        // Nothing of the pane paints outside it.
        clip: true

        // The transcript's last position, bottom margin included.
        function end() {
            return Math.max(list.originY - list.topMargin,
                list.originY + list.contentHeight + list.bottomMargin - list.height)
        }

        // Within a line of the end, so a pixel off still counts as the bottom.
        function atBottom() {
            return list.contentY >= pane.end() - Kirigami.Units.gridUnit
        }

        // positionViewAtEnd() creates the last items but stops short of the
        // bottom margin; the exact end follows.
        function scrollToEnd() {
            list.positionViewAtEnd()
            list.contentY = pane.end()
        }

        // Runs after the new text is laid out (contentHeight changed), never
        // straight after it is set: the reply's height isn't known yet then.
        function pin() {
            if (pane.follow && !pane.held)
                pane.scrollToEnd()
        }

        // The user let go: following again only if they ended at the
        // bottom, or they sent a message meanwhile.
        function released() {
            pane.follow = pane.sentWhileHeld || pane.atBottom()
            pane.sentWhileHeld = false
            pane.pin()
        }

        // A wheel scroll by the user. Up stops following at once; either way
        // nothing is pinned until the smooth scroll has settled, then
        // released decides from where it ended.
        function wheeled(wheel) {
            var delta = wheel.angleDelta.y !== 0 ? wheel.angleDelta.y : wheel.pixelDelta.y
            if (delta > 0)
                pane.follow = false
            wheelSettle.restart()
        }

        function updateBackToBottom() {
            pane.showBackToBottom = !pane.follow && pane.rows !== null && pane.rows.count > 0
                && !pane.atBottom()
        }

        function laterBackToBottom() {
            Qt.callLater(pane.updateBackToBottom)
        }

        // Back to bottom: jump down and follow again.
        function followBottom() {
            pane.follow = true
            pane.scrollToEnd()
            Qt.callLater(pane.pin)
        }

        onHeldChanged: {
            if (!pane.held)
                pane.released()
        }
        onFollowChanged: {
            if (pane.follow)
                pane.showBackToBottom = false
            pane.laterBackToBottom()
        }

        // Kirigami's smooth wheel scroll takes about a long duration; the
        // user's wheel scroll counts as held until it is done.
        Timer {
            id: wheelSettle
            interval: Kirigami.Units.longDuration * 2
            repeat: false
        }

        Kirigami.Separator {
            visible: pane.paneId === "b"
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.right: ollamaView.sideBySide ? undefined : parent.right
            anchors.bottom: ollamaView.sideBySide ? parent.bottom : undefined
        }

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            PlasmaComponents.Label {
                objectName: "paneModel"
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.largeSpacing
                Layout.rightMargin: Kirigami.Units.largeSpacing
                Layout.topMargin: Kirigami.Units.smallSpacing
                visible: pane.showModel
                textFormat: Text.PlainText
                elide: Text.ElideRight
                font.bold: true
                text: pane.modelLabel !== "" ? pane.modelLabel : i18n("No model")
            }
            PlasmaComponents.Label {
                objectName: "personaLine"
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.largeSpacing
                Layout.rightMargin: Kirigami.Units.largeSpacing
                Layout.topMargin: Kirigami.Units.smallSpacing
                visible: pane.personaText !== ""
                textFormat: Text.PlainText
                elide: Text.ElideRight
                opacity: 0.72
                font: Kirigami.Theme.smallFont
                text: i18n("Personality: %1", pane.personaText)
            }

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true
                // Keeps the transcript and Back to bottom inside this area.
                clip: true

                // A plain ListView with its own Kirigami.WheelHandler, not a
                // QQC2.ScrollView: in Plasma's desktop style the ScrollView
                // adds a WheelHandler of its own that scrolls without moving
                // the list (so a wheel scroll never counted as the user's)
                // and may swallow Ctrl+wheel. With one handler every wheel
                // event is seen here first.
                ListView {
                    id: list
                    objectName: pane.paneId === "b" ? "transcriptB" : "transcript"
                    anchors.fill: parent
                    model: pane.rows
                    spacing: Kirigami.Units.largeSpacing
                    topMargin: Kirigami.Units.largeSpacing
                    bottomMargin: Kirigami.Units.largeSpacing
                    leftMargin: Kirigami.Units.largeSpacing
                    // Room for the scroll bar while it is shown.
                    rightMargin: Kirigami.Units.largeSpacing + (bar.visible ? bar.width : 0)
                    reuseItems: false
                    // A Flickable doesn't clip by itself: messages scrolled
                    // past the top would paint over the popup's header and tabs.
                    clip: true

                    onContentHeightChanged: {
                        if (pane.follow)
                            Qt.callLater(pane.pin)
                        pane.laterBackToBottom()
                    }
                    onHeightChanged: {
                        if (pane.follow)
                            Qt.callLater(pane.pin)
                        pane.laterBackToBottom()
                    }
                    onContentYChanged: pane.laterBackToBottom()
                    onOriginYChanged: pane.laterBackToBottom()
                    onCountChanged: pane.laterBackToBottom()

                    QQC2.ScrollBar.vertical: QQC2.ScrollBar {
                        id: bar
                        objectName: pane.paneId === "b" ? "transcriptBarB" : "transcriptBar"
                    }

                    // Smooth wheel scrolling as elsewhere in Plasma. Ctrl+wheel
                    // zooms and never scrolls; any other wheel is the user's own
                    // scroll (see wheeled).
                    Kirigami.WheelHandler {
                        objectName: "transcriptWheel"
                        target: list
                        onWheel: (wheel) => {
                            if (wheel.modifiers & Qt.ControlModifier) {
                                wheel.accepted = true
                                ollamaView.wheelZoom(wheel)
                            } else {
                                pane.wheeled(wheel)
                            }
                        }
                    }

                    delegate: ColumnLayout {
                        id: message
                        required property int index
                        required property string author
                        required property string body
                        required property string phase
                        readonly property bool mine: message.author === "user"
                        // Text widths are set directly, never from a layout pass:
                        // wrapping long text at width 0 first would stall.
                        readonly property real textWidth: Math.max(Kirigami.Units.gridUnit * 10, message.width)
                        // The widest a reply's blocks get: the reply bubble is at
                        // most 92% of the pane, padding included.
                        readonly property real replyTextWidth: Math.max(Kirigami.Units.gridUnit * 5,
                            Math.round(message.textWidth * 0.92) - Kirigami.Units.largeSpacing * 2)
                        // Bumped when a block item comes or goes, so replyWidth
                        // looks at every block again.
                        property int blockItems: 0
                        // The reply's content width: its widest block, at most
                        // replyTextWidth. Built from the blocks' natural widths,
                        // which never depend on the width they are given.
                        readonly property real replyWidth: {
                            // Never true: only makes the binding depend on blockItems.
                            if (message.blockItems < 0)
                                return message.replyTextWidth
                            var widest = OllamaChat.hasHidden(message.body) ? message.replyTextWidth : 0
                            for (var index = 0; index < blockRepeater.count; index++) {
                                var item = blockRepeater.itemAt(index)
                                widest = Math.max(widest, item ? item.naturalWidth : message.replyTextWidth)
                            }
                            return Math.min(message.replyTextWidth, widest)
                        }
                        // Regenerate and Edit act on the last turn only (D49).
                        readonly property bool lastReply: !message.mine && pane.turn !== null
                            && message.index === pane.turn.assistantIndex
                            && pane.turn.userIndex === message.index - 1
                        readonly property bool lastMessage: message.mine && pane.paneId === "a"
                            && pane.turn !== null && message.index === pane.turn.userIndex

                        width: ListView.view.width - ListView.view.leftMargin - ListView.view.rightMargin
                        spacing: Kirigami.Units.smallSpacing

                        // Updates the reply's blocks in place: unchanged blocks
                        // keep their item and layout while the reply grows.
                        function syncBlocks() {
                            var wanted = message.mine ? [] : OllamaChat.blocks(message.body)
                            for (var index = 0; index < wanted.length; index++) {
                                var shape = JSON.stringify(wanted[index])
                                if (index >= blockModel.count) {
                                    blockModel.append({ kind: wanted[index].kind, shape: shape })
                                    continue
                                }
                                var shown = blockModel.get(index)
                                if (shown.kind !== wanted[index].kind)
                                    blockModel.setProperty(index, "kind", wanted[index].kind)
                                if (shown.shape !== shape)
                                    blockModel.setProperty(index, "shape", shape)
                            }
                            if (blockModel.count > wanted.length)
                                blockModel.remove(wanted.length, blockModel.count - wanted.length)
                        }

                        onBodyChanged: message.syncBlocks()
                        Component.onCompleted: message.syncBlocks()

                        ListModel {
                            id: blockModel
                        }

                        // The user's message, right-aligned in a highlight bubble.
                        Rectangle {
                            objectName: "userBubble"
                            Layout.alignment: Qt.AlignRight
                            Layout.preferredWidth: userText.width + Kirigami.Units.largeSpacing * 2
                            Layout.preferredHeight: userText.height + Kirigami.Units.smallSpacing * 2
                            visible: message.mine
                            radius: Kirigami.Units.cornerRadius * 2
                            color: Kirigami.Theme.highlightColor

                            TextEdit {
                                id: userText
                                x: Kirigami.Units.largeSpacing
                                y: Kirigami.Units.smallSpacing
                                width: Math.min(userText.implicitWidth,
                                    Math.round(message.textWidth * 0.85) - Kirigami.Units.largeSpacing * 2)
                                readOnly: true
                                selectByMouse: true
                                wrapMode: ollamaView.wrapFor(message.body)
                                textFormat: TextEdit.PlainText
                                color: Kirigami.Theme.highlightedTextColor
                                // Inverted: the bubble is already the highlight colour.
                                selectionColor: Kirigami.Theme.highlightedTextColor
                                selectedTextColor: Kirigami.Theme.highlightColor
                                font: ollamaView.bodyFont
                                text: message.mine ? message.body : ""
                            }
                        }
                        PlasmaComponents.ToolButton {
                            objectName: "editButton"
                            Layout.alignment: Qt.AlignRight
                            visible: message.lastMessage && !ollamaView.busy
                            icon.name: "document-edit"
                            display: QQC2.AbstractButton.IconOnly
                            text: i18n("Edit message")
                            onClicked: ollamaView.editLast()
                            QQC2.ToolTip.text: text
                            QQC2.ToolTip.visible: hovered
                        }

                        // The reply, left-aligned in a faint bubble: headings,
                        // paragraphs, lists, and fenced code blocks in monospace;
                        // all plain text. While the body is empty only the
                        // thinking row below shows.
                        Rectangle {
                            objectName: "replyBubble"
                            Layout.alignment: Qt.AlignLeft
                            Layout.preferredWidth: message.replyWidth + Kirigami.Units.largeSpacing * 2
                            Layout.preferredHeight: replyColumn.height + Kirigami.Units.smallSpacing * 2
                            visible: !message.mine && message.body !== ""
                            radius: Kirigami.Units.cornerRadius * 2
                            color: Qt.alpha(Kirigami.Theme.textColor, 0.06)

                            Column {
                                id: replyColumn
                                x: Kirigami.Units.largeSpacing
                                y: Kirigami.Units.smallSpacing
                                width: message.replyWidth
                                spacing: Kirigami.Units.smallSpacing

                                Repeater {
                                    id: blockRepeater
                                    model: blockModel
                                    onItemAdded: message.blockItems += 1
                                    onItemRemoved: message.blockItems += 1

                                    delegate: Item {
                                        id: segment
                                        required property string kind
                                        required property string shape
                                        readonly property var block: JSON.parse(segment.shape)
                                        readonly property bool code: segment.kind === "code"
                                        readonly property string content: segment.code ? segment.block.text : ""
                                        // The block's width unwrapped (replyTextWidth until
                                        // it is loaded, so long text never wraps at 0).
                                        readonly property real naturalWidth: blockLoader.item
                                            ? Math.min(message.replyTextWidth, blockLoader.item.naturalWidth)
                                            : message.replyTextWidth
                                        // Every block is as wide as the bubble's content.
                                        readonly property real blockWidth: Math.min(message.replyTextWidth,
                                            Math.max(segment.naturalWidth, message.replyWidth))

                                        width: segment.blockWidth
                                        height: blockLoader.height

                                        Loader {
                                            id: blockLoader
                                            width: segment.blockWidth
                                            sourceComponent: segment.code ? codeBlock
                                                : segment.kind === "heading" ? headingBlock
                                                : segment.kind === "bullet" || segment.kind === "number" ? listBlock
                                                : paragraphBlock
                                        }

                                        Component {
                                            id: paragraphBlock
                                            ReplyParagraph {
                                                spans: segment.block.spans
                                                textWidth: segment.blockWidth
                                            }
                                        }
                                        Component {
                                            id: headingBlock
                                            Text {
                                                readonly property real naturalWidth: implicitWidth
                                                width: segment.blockWidth
                                                wrapMode: Text.Wrap
                                                textFormat: Text.PlainText
                                                color: Kirigami.Theme.textColor
                                                font: ollamaView.headingFont(segment.block.level)
                                                text: OllamaChat.spansText(segment.block.spans)
                                            }
                                        }
                                        Component {
                                            id: listBlock
                                            RowLayout {
                                                id: listItem
                                                readonly property real markerWidth: Kirigami.Units.gridUnit * 1.5
                                                readonly property real indent: (segment.block.depth || 0) * Kirigami.Units.gridUnit
                                                readonly property real naturalWidth: message.replyTextWidth
                                                spacing: Kirigami.Units.smallSpacing

                                                PlasmaComponents.Label {
                                                    Layout.leftMargin: listItem.indent
                                                    Layout.preferredWidth: Math.max(listItem.markerWidth, implicitWidth)
                                                    Layout.alignment: Qt.AlignTop
                                                    horizontalAlignment: Text.AlignRight
                                                    textFormat: Text.PlainText
                                                    font: ollamaView.bodyFont
                                                    text: segment.kind === "number" ? segment.block.n + "."
                                                        : ["•", "◦", "▪"][segment.block.depth || 0]
                                                }
                                                ReplyParagraph {
                                                    Layout.alignment: Qt.AlignTop
                                                    Layout.preferredWidth: textWidth
                                                    Layout.preferredHeight: implicitHeight
                                                    spans: segment.block.spans
                                                    textWidth: Math.max(Kirigami.Units.gridUnit * 5, segment.blockWidth
                                                        - listItem.indent - listItem.markerWidth - listItem.spacing)
                                                }
                                            }
                                        }
                                        Component {
                                            id: codeBlock
                                            Rectangle {
                                                readonly property real inset: Kirigami.Units.smallSpacing
                                                readonly property real naturalWidth: message.replyTextWidth
                                                width: segment.blockWidth
                                                height: codeText.height + inset * 2
                                                radius: Kirigami.Units.smallSpacing
                                                color: Kirigami.Theme.alternateBackgroundColor

                                                TextEdit {
                                                    id: codeText
                                                    x: parent.inset
                                                    y: parent.inset
                                                    width: segment.blockWidth - parent.inset * 2
                                                        - Kirigami.Units.iconSizes.medium - Kirigami.Units.smallSpacing
                                                    readOnly: true
                                                    selectByMouse: true
                                                    wrapMode: ollamaView.wrapFor(segment.content)
                                                    textFormat: TextEdit.PlainText
                                                    color: Kirigami.Theme.textColor
                                                    selectionColor: Kirigami.Theme.highlightColor
                                                    selectedTextColor: Kirigami.Theme.highlightedTextColor
                                                    font: ollamaView.codeFont
                                                    text: segment.content
                                                }
                                                PlasmaComponents.ToolButton {
                                                    anchors.top: parent.top
                                                    anchors.right: parent.right
                                                    icon.name: "edit-copy"
                                                    display: QQC2.AbstractButton.IconOnly
                                                    text: i18n("Copy code")
                                                    onClicked: ollamaView.copyText(segment.content)
                                                    QQC2.ToolTip.text: text
                                                    QQC2.ToolTip.visible: hovered
                                                }
                                            }
                                        }
                                    }
                                }

                                PlasmaComponents.Label {
                                    objectName: "hiddenCharsNote"
                                    width: message.replyWidth
                                    visible: !message.mine && OllamaChat.hasHidden(message.body)
                                    textFormat: Text.PlainText
                                    wrapMode: Text.Wrap
                                    color: Kirigami.Theme.neutralTextColor
                                    font: Kirigami.Theme.smallFont
                                    text: i18n("This text contains hidden or control characters, shown as ⟦U+…⟧. Copy copies the marked text.")
                                }
                            }
                        }

                        RowLayout {
                            visible: !message.mine
                            spacing: Kirigami.Units.smallSpacing

                            PlasmaComponents.BusyIndicator {
                                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                                Layout.preferredHeight: Kirigami.Units.iconSizes.small
                                visible: message.phase === "waiting" || message.phase === "thinking"
                                running: visible
                            }
                            PlasmaComponents.Label {
                                textFormat: Text.PlainText
                                opacity: 0.7
                                font: Kirigami.Theme.smallFont
                                visible: text !== ""
                                text: {
                                    switch (message.phase) {
                                    case "thinking":
                                        return i18n("Thinking…")
                                    case "stopped":
                                        return i18n("(stopped)")
                                    case "cut":
                                        return i18n("Reply cut off (too long).")
                                    case "failed":
                                        return i18n("(incomplete)")
                                    default:
                                        return ""
                                    }
                                }
                            }
                            PlasmaComponents.ToolButton {
                                visible: message.body !== "" && message.phase !== "waiting"
                                    && message.phase !== "streaming" && message.phase !== "thinking"
                                icon.name: "edit-copy"
                                display: QQC2.AbstractButton.IconOnly
                                text: i18n("Copy reply")
                                // The marked text, as shown: hidden characters never
                                // reach the clipboard.
                                onClicked: ollamaView.copyText(OllamaChat.revealHidden(message.body))
                                QQC2.ToolTip.text: text
                                QQC2.ToolTip.visible: hovered
                            }
                            PlasmaComponents.ToolButton {
                                objectName: "regenerateButton"
                                visible: message.lastReply && ollamaView.canResend
                                icon.name: "view-refresh"
                                display: QQC2.AbstractButton.IconOnly
                                text: i18n("Regenerate reply")
                                onClicked: ollamaView.regenerate(pane.paneId)
                                QQC2.ToolTip.text: text
                                QQC2.ToolTip.visible: hovered
                            }
                        }
                    }
                }

                // Over the transcript's bottom edge, never over the message box,
                // and it never takes the focus from it. Fixed texts only.
                PlasmaComponents.Button {
                    objectName: pane.paneId === "b" ? "backToBottomB" : "backToBottom"
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: Kirigami.Units.largeSpacing
                    focusPolicy: Qt.NoFocus
                    icon.name: "go-down"
                    text: ollamaView.generating && ollamaView.replyPane === pane.paneId
                        ? i18n("New messages") : i18n("Back to bottom")
                    enabled: pane.showBackToBottom
                    opacity: pane.showBackToBottom ? 1 : 0
                    visible: opacity > 0
                    onClicked: pane.followBottom()

                    Behavior on opacity {
                        NumberAnimation {
                            duration: Kirigami.Units.shortDuration
                        }
                    }
                }

                ColumnLayout {
                    anchors.centerIn: parent
                    width: Math.min(parent.width - Kirigami.Units.gridUnit * 2, Kirigami.Units.gridUnit * 22)
                    visible: pane.rows !== null && pane.rows.count === 0
                    spacing: Kirigami.Units.largeSpacing

                    Kirigami.Icon {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.preferredWidth: Kirigami.Units.iconSizes.huge
                        Layout.preferredHeight: Kirigami.Units.iconSizes.huge
                        visible: pane.paneId === "a"
                        source: Qt.resolvedUrl("../images/" + OllamaChat.ENTRY.icon)
                        isMask: true
                        color: Kirigami.Theme.textColor
                        opacity: 0.5
                    }
                    PlasmaComponents.BusyIndicator {
                        Layout.alignment: Qt.AlignHCenter
                        visible: pane.paneId === "a" && ollamaView.listState === "loading"
                        running: visible
                    }
                    PlasmaComponents.Label {
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        textFormat: Text.PlainText
                        opacity: 0.72
                        text: pane.paneId === "b"
                            ? i18n("The second model answers here, after the first one.")
                            : ollamaView.listState === "loading"
                            ? i18n("Connecting to Ollama…")
                            : i18n("Chat with a model on this computer. The conversation stays in memory only and is gone after Clear or a Plasma restart.")
                    }
                }
            }
        }
    }
}
