import QtCore
import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasma5support as Plasma5Support
import org.kde.kirigami as Kirigami
import org.kde.notification
import "ProviderCatalog.js" as Catalog
import "RefreshGate.js" as RefreshGate
import "SnapshotLogic.js" as SnapshotLogic
import "ChatSites.js" as ChatSites
import "ChatStorage.js" as ChatStorage
import "OllamaChat.js" as OllamaChat
import "PromptLibrary.js" as PromptLibrary
import "SettingsLogic.js" as SettingsLogic
import "AlertLogic.js" as AlertLogic
import "TooltipLogic.js" as TooltipLogic
import "UsageLogic.js" as UsageLogic

PlasmoidItem {
    id: root

    property var snapshot: ({
        "schema_version": 2,
        "catalog": Catalog.providers,
        "installed_provider_ids": [],
        "providers": []
    })
    property var providerStates: ({})
    property var lastGoodProviders: ({})
    property var cooldownUntil: ({})
    property bool hasData: false
    property string lastError: ""
    property date lastUpdate: new Date(0)
    property bool refreshInFlight: false
    property bool refreshQueued: false
    property double refreshStartedAt: 0
    property string refreshSource: ""
    property int refreshRun: 0

    // Chat tab runtime state; never written to the configuration.
    property string popupTab: "chat"
    property string chatSiteId: ""
    property bool chatDialogOpen: false
    // Settings → General → Show tabs. Chat also needs an enabled site.
    readonly property var popupTabs: SettingsLogic.visibleTabs(
        Plasmoid.configuration.showUsageTab,
        Plasmoid.configuration.showChatTab,
        root.chatSiteIds.length > 0)
    // A hidden Chat tab builds no chat view; a hidden Usage tab runs no
    // usage helper.
    readonly property bool chatShown: root.popupTabs.chat
    readonly property bool usageShown: root.popupTabs.usage
    // The tab the popup shows: popupTab while it is visible, else the other.
    readonly property string shownTab: SettingsLogic.shownTab(root.popupTab, root.popupTabs)
    readonly property real popupScale: SettingsLogic.popupScale(Plasmoid.configuration.popupSize)
    // Settings → General → Size changed: the popup takes the new size the
    // next time it can (FullRepresentation.applyPopupSize clears this).
    property bool popupSizePending: false
    onPopupScaleChanged: root.popupSizePending = true
    readonly property bool tooltipShowsUsage: Plasmoid.configuration.tooltipShowsUsage !== false
    readonly property var tooltipChoice: TooltipLogic.parseTooltipMetrics(
        Plasmoid.configuration.tooltipMetrics, Catalog.providers)
    // Web sites, then the built-in Ollama chat when it is on.
    readonly property var chatSites: OllamaChat.menuEntries(
        ChatSites.enabledSites(Plasmoid.configuration.chatSites),
        Plasmoid.configuration.chatSites)
    readonly property var chatSiteIds: root.chatSites.map(function (site) { return site.id })
    // The web chat only knows web sites. It keeps its last one while Ollama
    // is shown, so its pages stay as they were.
    readonly property var chatWebSiteIds: root.chatSiteIds.filter(function (id) {
        return id !== OllamaChat.ENTRY.id
    })
    property string chatWebSiteId: ""
    // Split view, runtime only: a second web pane with its own site.
    property bool chatSplit: false
    property string chatSiteIdB: ""
    // Its sites: the enabled web sites.
    readonly property var chatSplitSites: root.chatSites.filter(function (site) {
        return site.id !== OllamaChat.ENTRY.id
    })
    // Validated loopback address; anything odd → the default.
    readonly property string chatOllamaAddress:
        OllamaChat.effectiveAddress(Plasmoid.configuration.chatOllamaUrl)
    // {siteId: url}; only valid addresses survive, anything odd → built-in.
    readonly property var chatCustomUrls:
        ChatSites.parseCustomUrls(Plasmoid.configuration.chatCustomUrls)
    // Per-site zoom {siteId: factor} for the web sites and Ollama. Read from
    // the configuration at start; Ctrl+= / Ctrl+- / Ctrl+0 change it here and
    // zoomWriteTimer stores it a moment later.
    readonly property var chatZoomIds: ChatSites.siteIds().concat([OllamaChat.ENTRY.id])
    property var chatZoom: ({})

    // Settings → General → Keyboard shortcut opens.
    readonly property string shortcutTarget:
        SettingsLogic.normalizeShortcutTarget(Plasmoid.configuration.shortcutOpens)
    // Settings → General → Middle-click opens.
    readonly property string middleClickTarget:
        SettingsLogic.normalizeMiddleClick(Plasmoid.configuration.middleClickOpens, ChatSites.siteIds())
    // The shortcut opened the Ollama chat: its message box takes the focus.
    signal ollamaFocusRequested()
    // What the last shortcut press asked for: open (true) or closed.
    property bool shortcutOpen: false
    // Ollama is on and the Chat tab can show it: text dropped on the panel
    // icon opens it.
    readonly property bool ollamaDropTarget: root.chatShown
        && root.chatSiteIds.indexOf(OllamaChat.ENTRY.id) >= 0
    // Text dropped on the panel icon, until the popup puts it into Ollama's
    // message box (FullRepresentation.takePendingDrop). Runtime only, never
    // sent from here.
    property string pendingDrop: ""
    // Why a file dropped on the chat or the icon gave no text (a
    // PromptLibrary error code), until the popup shows it.
    property string pendingDropError: ""
    property string droppedSourceName: ""
    property int droppedRun: 0

    // Prompt library (saved prompts and personalities). Saved only inside
    // the unlocked encrypted folder; the helper lists them and main.qml
    // keeps the copy in memory, cleared as soon as the folder is locked.
    // Never in the configuration.
    readonly property bool libraryAvailable:
        root.chatVaultState === "unlocked" && root.chatStorageMode === "encrypted"
    property var libraryItems: []
    // {"m:<model>": persona id}
    property var libraryPersonas: ({})
    // "", loading, ready, error
    property string libraryState: ""
    property string libraryError: ""
    property var libraryQueue: []
    property string libraryOp: ""
    property string librarySourceName: ""
    property int libraryRun: 0
    // Prompts and personalities kept for this session only (the folder is
    // locked or Stay signed in is off): [{id (negative), kind, text}].
    property var sessionLibrary: []
    property int sessionLibraryNext: -1
    // Everything the popup lists: saved items, then this session's.
    readonly property var promptItems: root.libraryItems.concat(root.sessionLibrary)

    // Usage alerts, memory only: after a Plasma restart the first reading is
    // a baseline again.
    property var alertState: ({})

    // Stay signed in. Runtime state only; nothing here reaches the config
    // except chatProfileGeneration. The helper reports short codes and the
    // profile path is derived here, never received or shown.
    readonly property string chatStorageMode:
        ChatStorage.normalizeMode(Plasmoid.configuration.chatSignInStorage)
    readonly property int chatConfiguredGeneration:
        ChatStorage.normalizeGeneration(Plasmoid.configuration.chatProfileGeneration)
    // -1 until Component.onCompleted has read the configuration.
    property int chatGeneration: -1
    property string chatModeSeen: "memory"
    readonly property int chatAppletId: ChatStorage.validInt(Plasmoid.id)
    readonly property string chatProfileName:
        ChatStorage.profileName(root.chatAppletId, root.chatGeneration)
    // Same rule as the helper: $XDG_RUNTIME_DIR, else nothing (memory only).
    readonly property string chatProfilePath: ChatStorage.profilePath(
        StandardPaths.writableLocation(StandardPaths.RuntimeLocation),
        root.chatAppletId, root.chatGeneration)
    // "", absent, locked, unlocked, unavailable, error
    property string chatVaultState: ""
    property var chatVaultMissing: []
    // The KDE Wallet key slot as status reports it: "", set-up, off, unavailable.
    property string chatVaultWallet: ""
    // Settings → General → Unlock with; used only when the slot is set up.
    readonly property string chatUnlockSetting:
        ChatStorage.normalizeUnlockMethod(Plasmoid.configuration.chatVaultUnlock)
    // A wallet key slot exists but Passphrase is chosen: the card says so.
    readonly property bool chatWalletNotApplied:
        ChatStorage.walletChoice(root.chatUnlockSetting, root.chatVaultWallet).notApplied
    readonly property string chatUnlockMethod:
        ChatStorage.effectiveUnlockMethod(root.chatUnlockSetting, root.chatVaultWallet)
    // Generation the helper prepared inside the verified mount; -1 = none.
    property int chatPreparedGeneration: -1
    // The user locked or cleared: don't reopen saved sign-ins by itself.
    property bool chatVaultHold: false
    property bool chatPrivateSession: false
    property string chatVaultError: ""
    property string chatStorageNotice: ""
    // Helper steps still to run and the one running.
    property var chatQueue: []
    property string chatOp: ""
    property string chatOpSource: ""
    property int chatOpGeneration: -1
    // Seeded in Component.onCompleted; see ChatStorage.firstRun.
    property int chatOpRun: 0
    // A passphrase or KDE Wallet window may be open.
    readonly property bool chatVaultPrompting: root.chatOp === "create" || root.chatOp === "unlock"
        || root.chatOp === "unlock-wallet" || root.chatOp === "add-key"
    // A helper step runs or waits to run; Lock automatically holds off.
    readonly property bool chatStorageBusy: root.chatOp !== "" || root.chatQueue.length > 0
    // Lock automatically after this many idle minutes; 0 = never.
    readonly property int chatAutoLockMinutes:
        ChatStorage.normalizeAutoLock(Plasmoid.configuration.chatAutoLockMinutes)
    // The running lock was started by Lock automatically.
    property bool chatAutoLocking: false
    readonly property bool chatStorageReady: root.chatStorageMode === "encrypted"
        && root.chatVaultState === "unlocked"
        && !root.chatVaultHold
        && root.chatPreparedGeneration === root.chatGeneration
        && root.chatProfilePath !== ""
        && root.chatProfileName !== ""
    readonly property var chatCard: ChatStorage.cardFor({
        mode: root.chatStorageMode,
        state: root.chatVaultState,
        // Quiet re-checks while the saved profile is open don't show a card.
        // Wallet steps keep their own name, for their own busy text.
        op: root.chatOp === "keep" ? ""
            : root.chatOp === "unlock-wallet" || root.chatOp === "auto-unlock" || root.chatOp === "add-key"
            ? root.chatOp : ChatStorage.stepOperation(root.chatOp),
        error: root.chatVaultError,
        hold: root.chatVaultHold,
        privateSession: root.chatPrivateSession,
        ready: root.chatStorageReady
    })

    readonly property int refreshInterval: normalizedRefresh(
        Plasmoid.configuration.refreshInterval || 300
    )
    readonly property string usageMode:
        Plasmoid.configuration.usageMode === "used" ? "used" : "remaining"
    readonly property var trackedProviders: configuredList(
        Plasmoid.configuration.trackedProviders,
        Catalog.providerIds()
    )
    readonly property var configuredMetrics: configuredObject(
        Plasmoid.configuration.providerMetrics,
        {}
    )
    // Settings → AI Provider Settings → Usage tab.
    readonly property var providerOrder: UsageLogic.normalizeOrder(
        Plasmoid.configuration.providerOrder, Catalog.providerIds())
    // The Usage tab's providers in that order; the hover popup and the
    // alerts follow it too.
    readonly property var shownProviders: UsageLogic.orderProviders(
        root.snapshot.providers || [], root.providerOrder)
    readonly property bool usageCompact: Plasmoid.configuration.usageCompact === true
    readonly property var usageThresholds: UsageLogic.normalizeThresholds(
        Plasmoid.configuration.usageWarnPercent, Plasmoid.configuration.usageCriticalPercent)
    readonly property var tooltipGroups: TooltipLogic.applyChoice(
        root.tooltipProviderGroups(), root.tooltipChoice)
    // AI Provider Settings → the color boxes; "" keeps the default color. An
    // empty Critical box follows a custom Warning color.
    readonly property string customNormalColor: UsageLogic.normalizeColor(Plasmoid.configuration.usageNormalColor)
    readonly property string customWarnColor: UsageLogic.normalizeColor(Plasmoid.configuration.usageWarnColor)
    readonly property string customCriticalColor: UsageLogic.effectiveCriticalColor(
        Plasmoid.configuration.usageCriticalColor, Plasmoid.configuration.usageWarnColor)
    readonly property color warnUsageColor: root.customWarnColor !== ""
        ? root.customWarnColor : Kirigami.Theme.neutralTextColor
    readonly property color criticalUsageColor: root.customCriticalColor !== ""
        ? root.customCriticalColor : Kirigami.Theme.negativeTextColor
    readonly property color normalUsageColor: {
        if (root.customNormalColor !== "")
            return root.customNormalColor
        var background = Kirigami.Theme.backgroundColor
        return UsageLogic.defaultNormalColor(background.r, background.g, background.b)
    }

    // AI Provider Settings → Usage ring. Same reading rules and colors as
    // the hover popup and the bars.
    readonly property var ringChoice: UsageLogic.parsePanelRing(
        Plasmoid.configuration.panelRing, Catalog.providers)
    readonly property var ringState: {
        var none = {visible: false, fraction: 0, color: root.normalUsageColor, stale: false}
        if (!root.usageShown || !root.hasData)
            return none
        var found = UsageLogic.ringReading(root.ringChoice, root.tooltipGroups,
            root.shownProviders, root.metricReading)
        var fraction = found ? UsageLogic.ringFraction(found.reading, root.usageMode) : null
        if (fraction === null)
            return none
        return {visible: true, fraction: fraction, color: root.barColor(found.reading.raw_used), stale: found.stale}
    }

    function configuredList(value, fallback) {
        try {
            var parsed = JSON.parse(value || "")
            if (Array.isArray(parsed))
                return parsed.filter(function (id) { return Catalog.byId(id) !== null })
        } catch (error) {
        }
        return fallback.slice()
    }

    function configuredObject(value, fallback) {
        try {
            var parsed = JSON.parse(value || "")
            if (parsed && typeof parsed === "object" && !Array.isArray(parsed))
                return parsed
        } catch (error) {
        }
        return fallback
    }

    function normalizedRefresh(value) {
        var choices = [60, 300, 900, 1800, 3600]
        var closest = choices[0]
        for (var index = 1; index < choices.length; index++) {
            if (Math.abs(choices[index] - value) < Math.abs(closest - value))
                closest = choices[index]
        }
        return closest
    }

    function selectedMetrics(providerId) {
        var configured = root.configuredMetrics[providerId]
        if (!Array.isArray(configured))
            return []
        return configured.filter(function (metricId) {
            return Catalog.metric(providerId, metricId) !== null
        })
    }

    // Thin wrappers: reading root.usageMode here keeps callers' bindings live.
    function windowFor(providerData, metricId) {
        return SnapshotLogic.windowFor(providerData, metricId)
    }

    function metricReading(providerData, metricId) {
        return SnapshotLogic.metricReading(providerData, metricId, root.usageMode)
    }

    function displayedPercent(rawUsed) {
        return SnapshotLogic.displayedPercent(rawUsed, root.usageMode)
    }

    function formatReading(reading) {
        if (!reading)
            return "—"
        if (reading.type === "percentage")
            return Math.round(reading.value) + "%"
        if (reading.type === "money")
            return "$" + Number(reading.value).toFixed(2)
        if (reading.type === "credits")
            return String(Math.round(reading.value))
        return "—"
    }

    // Percentages say whether they are left or used; amounts and credits
    // read as in the Usage tab.
    function tooltipValue(reading) {
        if (!reading || reading.type !== "percentage")
            return root.formatReading(reading)
        var percent = Math.round(reading.value)
        return root.usageMode === "used"
            ? i18n("%1% used", percent) : i18n("%1% left", percent)
    }

    function barColor(rawUsed) {
        var level = UsageLogic.usageLevel(rawUsed, root.usageThresholds)
        if (level === "critical")
            return root.criticalUsageColor
        if (level === "warning")
            return root.warnUsageColor
        return root.normalUsageColor
    }

    // Values below the warning level keep the text color, so they stay
    // readable whatever the normal bar color is.
    function valueColor(rawUsed) {
        var level = UsageLogic.usageLevel(rawUsed, root.usageThresholds)
        if (level === "critical")
            return root.criticalUsageColor
        if (level === "warning")
            return root.warnUsageColor
        return Kirigami.Theme.textColor
    }

    function providerIconSource(providerId) {
        var descriptor = Catalog.byId(providerId)
        return descriptor
            ? Qt.resolvedUrl("../images/" + descriptor.icon)
            : "speedometer"
    }

    // The providers the Usage tab shows, in its order, each with its
    // selected metrics (else its default metric).
    function tooltipProviderGroups() {
        var result = []
        var shown = root.shownProviders
        for (var index = 0; index < shown.length; index++) {
            var providerId = shown[index].provider_id
            var descriptor = Catalog.byId(providerId)
            if (!descriptor)
                continue
            var metrics = root.selectedMetrics(providerId)
            if (metrics.length === 0 && Catalog.metric(providerId, descriptor.default_metric) !== null)
                metrics = [descriptor.default_metric]
            if (metrics.length === 0)
                continue
            result.push({
                provider_id: providerId,
                descriptor: descriptor,
                provider: shown[index],
                metrics: metrics
            })
        }
        return result
    }

    function activeProviderIds() {
        var now = Date.now()
        var installed = root.snapshot.installed_provider_ids || []
        var knownInstallations = root.hasData
        var result = []
        for (var index = 0; index < root.trackedProviders.length; index++) {
            var providerId = root.trackedProviders[index]
            if (knownInstallations && installed.indexOf(providerId) < 0)
                continue
            var retry = Number(root.cooldownUntil[providerId] || 0)
            if (retry > now)
                continue
            result.push(providerId)
        }
        return result
    }

    function refresh() {
        if (!root.usageShown)
            return
        var providerIds = activeProviderIds()
        if (root.hasData && providerIds.length === 0)
            return
        // Only one helper may run at a time; extra requests collapse into a
        // single follow-up run once the current one reports back.
        var now = Date.now()
        if (RefreshGate.decide(root.refreshInFlight, root.refreshStartedAt, now) === "queue") {
            root.refreshQueued = true
            return
        }
        // Drop a stale run; each run gets a unique command so its late reply
        // can never be mistaken for the current run.
        if (root.refreshSource !== "")
            usageSource.disconnectSource(root.refreshSource)
        root.refreshRun += 1
        var command = RefreshGate.usageCommand(root.refreshRun, providerIds)
        root.refreshInFlight = true
        root.refreshQueued = false
        root.refreshStartedAt = now
        root.refreshSource = command
        usageSource.connectSource(command)
    }

    function applySnapshot(payload) {
        if (!payload || payload.schema_version !== 2)
            throw new Error("Unsupported helper schema")
        var merged = SnapshotLogic.mergeResults(
            root.providerStates,
            root.lastGoodProviders,
            root.cooldownUntil,
            payload.providers || []
        )
        var states = merged.states

        var installed = payload.installed_provider_ids || []
        var visible = []
        var catalog = payload.catalog && payload.catalog.length
            ? payload.catalog : Catalog.providers
        for (var catalogIndex = 0; catalogIndex < catalog.length; catalogIndex++) {
            var descriptor = catalog[catalogIndex]
            if (installed.indexOf(descriptor.provider_id) >= 0
                    && root.trackedProviders.indexOf(descriptor.provider_id) >= 0
                    && states[descriptor.provider_id]) {
                visible.push(states[descriptor.provider_id])
            }
        }
        root.providerStates = states
        root.lastGoodProviders = merged.goods
        root.cooldownUntil = merged.cooldowns
        root.snapshot = {
            schema_version: 2,
            generated_at: payload.generated_at,
            catalog: catalog,
            installed_provider_ids: installed,
            providers: visible
        }
        root.hasData = true
        root.lastError = ""
        root.lastUpdate = new Date()
    }

    function rebuildVisibleProviders() {
        if (!root.hasData)
            return
        var installed = root.snapshot.installed_provider_ids || []
        var catalog = root.snapshot.catalog || Catalog.providers
        var visible = []
        for (var index = 0; index < catalog.length; index++) {
            var providerId = catalog[index].provider_id
            if (installed.indexOf(providerId) >= 0
                    && root.trackedProviders.indexOf(providerId) >= 0
                    && root.providerStates[providerId]) {
                visible.push(root.providerStates[providerId])
            }
        }
        root.snapshot = Object.assign({}, root.snapshot, {providers: visible})
    }

    // Turns split view on or off; pane b starts on another site than pane a.
    function setChatSplit(on) {
        root.chatSplit = on === true
        if (root.chatSplit)
            root.syncSplitSite()
    }

    function syncSplitSite() {
        var ids = root.chatSplitSites.map(function (site) { return site.id })
        if (ids.indexOf(root.chatSiteIdB) >= 0)
            return
        var other = ids.filter(function (id) { return id !== root.chatWebSiteId })
        root.chatSiteIdB = other.length > 0 ? other[0] : (ids.length > 0 ? ids[0] : "")
    }

    function syncChatSite() {
        if (root.chatSiteIds.indexOf(root.chatSiteId) < 0)
            root.chatSiteId = ChatSites.initialSite(
                root.chatSiteIds,
                Plasmoid.configuration.chatDefaultSite
            )
    }

    // --- Stay signed in: helper steps, run one at a time --------------------

    // fresh: queue a status even while one started earlier is running.
    function chatEnqueue(steps, fresh) {
        root.chatQueue = ChatStorage.enqueueSteps(root.chatQueue, steps, root.chatOp, fresh === true)
        if (root.chatOp === "")
            Qt.callLater(root.chatNext)
    }

    function chatCommand(step, run) {
        switch (step) {
        case "prepare":
            return ChatStorage.webDataCommand("prepare", "encrypted",
                root.chatAppletId, root.chatGeneration, null, run)
        case "keep":
            return ChatStorage.webDataCommand("remove", "encrypted",
                root.chatAppletId, null, root.chatGeneration, run)
        case "remove":
        case "leave-remove":
            return ChatStorage.webDataCommand("remove", "encrypted",
                root.chatAppletId, null, null, run)
        default:
            return ChatStorage.vaultCommand(ChatStorage.stepOperation(step), run, root.chatAppletId,
                ChatStorage.stepMethod(step))
        }
    }

    function chatNext() {
        if (root.chatOp !== "" || root.chatQueue.length === 0)
            return
        // Leave steps are dropped once Stay signed in is back on.
        var next = ChatStorage.nextStep(root.chatQueue, {
            mode: root.chatStorageMode,
            state: root.chatVaultState,
            wantsSaved: root.chatWantsSaved(),
            wallet: root.chatVaultWallet,
            hold: root.chatVaultHold
        })
        root.chatQueue = next.queue
        var step = next.step
        if (step === "")
            return
        if (step === "wait" || step === "leave-wait") {
            // Destroying the profile writes its cookies and site storage and
            // closes its files at once (measured: done within 0.2 s, also
            // with 150 cookies and 1 MB of site storage); the second is
            // margin. The helper's unmount fails as busy, never loses data,
            // while any file is still open.
            root.chatOp = step
            chatWaitTimer.start()
            return
        }
        root.chatOpRun = ChatStorage.nextRun(root.chatOpRun)
        var command = root.chatCommand(step, root.chatOpRun)
        if (command === "") {
            root.chatFinish(step, {ok: false, error: "failed"})
            return
        }
        root.chatOp = step
        root.chatOpGeneration = root.chatGeneration
        root.chatOpSource = command
        storageSource.connectSource(command)
    }

    function chatWantsSaved() {
        return root.chatStorageMode === "encrypted" && !root.chatVaultHold
            && !root.chatPrivateSession && root.chatVaultState === "unlocked"
            && root.chatProfilePath !== ""
    }

    function chatFinish(step, reply) {
        root.chatOp = ""
        root.chatOpSource = ""
        switch (step) {
        case "status":
        case "leave-status":
            // Another widget holds the folder's lock (e.g. its passphrase
            // window is open): keep what we knew.
            if (!reply.ok && reply.error === "busy" && root.chatVaultState !== "")
                break
            if (reply.ok && reply.state) {
                root.chatVaultState = reply.state
                root.chatVaultMissing = reply.missing || []
                root.chatVaultWallet = reply.wallet || ""
            } else {
                root.chatVaultState = "error"
                root.chatVaultError = reply.error || "failed"
            }
            if (root.chatVaultState !== "unlocked")
                root.chatPreparedGeneration = -1
            else if (root.chatWantsSaved()
                     && root.chatPreparedGeneration !== root.chatGeneration)
                root.chatEnqueue(["prepare"])
            break
        case "prepare":
            if (reply.ok && root.chatOpGeneration === root.chatGeneration && root.chatWantsSaved()) {
                root.chatVaultError = ""
                root.chatPreparedGeneration = root.chatGeneration
                // Old generations of this widget (e.g. after Clear) go away.
                root.chatEnqueue(["keep"])
                // Another widget may lock the folder while the view opens it.
                chatRecheckTimer.restart()
            } else if (!reply.ok) {
                root.chatPreparedGeneration = -1
                root.chatVaultError = reply.error === "not-verified" || reply.error === "stale-mount"
                    || reply.error === "legacy-data" ? reply.error : "prepare-failed"
                root.chatEnqueue(["status"])
            }
            break
        case "keep":
            break
        case "remove":
            if (!reply.ok && root.chatStorageMode === "encrypted")
                root.chatVaultError = "remove-failed"
            break
        case "auto-unlock":
            // Plasma start: a closed wallet (or another widget busy with the
            // folder) just leaves the Unlock card; other problems are said.
            if (!reply.ok && reply.error !== "wallet-closed" && reply.error !== "busy")
                root.chatVaultError = reply.error || "failed"
            root.chatEnqueue(["status"])
            break
        case "add-key":
            // Set up again from the card: unlock with the new key at once.
            if (reply.ok) {
                root.chatVaultError = ""
                root.chatEnqueue(["status", "unlock-wallet"])
            } else {
                root.chatVaultError = reply.error === "cancelled" ? "" : reply.error || "failed"
                root.chatEnqueue(["status"])
            }
            break
        case "create":
        case "unlock":
        case "unlock-wallet":
        case "lock":
            var automatic = step === "lock" && root.chatAutoLocking
            if (step === "lock")
                root.chatAutoLocking = false
            if (automatic && !reply.ok && reply.error === "busy") {
                // Never forced: keep the saved sign-ins open; ChatView tries
                // again after the next idle period.
                root.chatVaultHold = false
                root.chatVaultError = ""
            } else if (!reply.ok)
                root.chatVaultError = step === "lock" && reply.error === "busy"
                    ? "lock-busy" : reply.error || "failed"
            else if (automatic)
                root.chatVaultError = "auto-locked"
            root.chatEnqueue(["status"])
            break
        case "destroy":
            // Damaged folder, confirmed in the Chat tab; then Create.
            if (!reply.ok)
                root.chatVaultError = reply.error || "failed"
            var destroyed = ChatStorage.afterDestroy(reply)
            if (destroyed.state !== "") {
                root.chatVaultState = destroyed.state
                root.chatVaultMissing = []
                root.chatPreparedGeneration = -1
            }
            root.chatEnqueue(["status"])
            break
        case "leave-remove":
        case "leave-lock":
            // leave-status reports how the folder ended up.
            break
        case "leave-destroy":
            if (!reply.ok && root.chatStorageMode === "memory")
                root.chatStorageNotice = "delete-failed"
            var outcome = ChatStorage.afterDestroy(reply)
            if (outcome.state !== "") {
                root.chatVaultState = outcome.state
                root.chatVaultMissing = []
                root.chatPreparedGeneration = -1
            }
            root.chatEnqueue(outcome.steps)
            break
        }
        Qt.callLater(root.chatNext)
    }

    // ChatView's requests (buttons and lifecycle).
    function chatStorageRequest(action) {
        switch (action) {
        case "open":
            // The Chat view starts: never trust an earlier answer.
            root.chatPreparedGeneration = -1
            root.chatEnqueue(["status"])
            break
        case "recheck":
            root.chatEnqueue(["status"])
            break
        case "retry":
            root.chatVaultHold = false
            root.chatVaultError = ""
            root.chatPreparedGeneration = -1
            root.chatEnqueue(["status"])
            break
        case "create":
            root.chatVaultHold = false
            root.chatVaultError = ""
            root.chatEnqueue([action])
            break
        case "unlock":
            // The configured method; one click, also after Lock.
            root.chatVaultHold = false
            root.chatVaultError = ""
            root.chatEnqueue([root.chatUnlockMethod === "wallet" ? "unlock-wallet" : "unlock"])
            break
        case "unlock-passphrase":
            root.chatVaultHold = false
            root.chatVaultError = ""
            root.chatEnqueue(["unlock"])
            break
        case "wallet-setup":
            // The wallet's key no longer fits (or is gone): set it up again,
            // with the passphrase window, then unlock with it.
            if (root.chatUnlockSetting !== "wallet" || root.chatVaultWallet === "unavailable")
                break
            root.chatVaultHold = false
            root.chatVaultError = ""
            root.chatEnqueue(["add-key"])
            break
        case "private":
            root.chatPrivateSession = true
            root.chatVaultError = ""
            break
        case "saved-session":
            root.chatPrivateSession = false
            root.chatVaultHold = false
            root.chatVaultError = ""
            root.chatEnqueue(["status"])
            break
        case "lock":
            // Destroy the profile first (ready turns false), then unmount.
            // A busy folder is reported, never forced.
            root.chatAutoLocking = false
            root.chatVaultHold = true
            root.chatVaultError = ""
            root.chatPreparedGeneration = -1
            root.chatEnqueue(["wait", "lock"])
            break
        case "auto-lock":
            // Same as Lock; ChatView asks only while the saved web chat is
            // hidden and no helper step runs.
            if (!root.chatStorageReady || root.chatStorageBusy)
                break
            root.chatAutoLocking = true
            root.chatVaultHold = true
            root.chatVaultError = ""
            root.chatPreparedGeneration = -1
            root.chatEnqueue(["wait", "lock"])
            break
        case "clear-saved":
            root.chatVaultHold = true
            root.chatPreparedGeneration = -1
            root.chatSetGeneration(ChatStorage.nextGeneration(root.chatGeneration))
            root.chatVaultError = "cleared"
            root.chatEnqueue(["wait", "remove", "lock"])
            break
        case "delete-damaged":
            if (root.chatVaultState !== "damaged")
                break
            root.chatVaultError = ""
            root.chatEnqueue(["destroy"])
            break
        case "dismiss-notice":
            root.chatStorageNotice = ""
            break
        }
    }

    function chatSetGeneration(generation) {
        root.chatGeneration = generation
        if (Plasmoid.configuration.chatProfileGeneration !== generation)
            Plasmoid.configuration.chatProfileGeneration = generation
    }

    function chatModeChanged() {
        if (root.chatGeneration < 0)
            return
        var previous = root.chatModeSeen
        root.chatModeSeen = root.chatStorageMode
        if (previous === root.chatStorageMode)
            return
        root.chatVaultHold = false
        root.chatPrivateSession = false
        root.chatAutoLocking = false
        root.chatVaultError = ""
        root.chatPreparedGeneration = -1
        chatRecheckTimer.stop()
        root.chatQueue = ChatStorage.queueForMode(root.chatQueue, root.chatStorageMode)
        if (root.chatStorageMode === "encrypted") {
            // Never trust a state read while leave steps may have run.
            root.chatStorageNotice = ""
            root.chatVaultState = ""
            root.chatEnqueue(["status"], true)
        } else {
            // Leaving Stay signed in deletes the encrypted folder (confirmed
            // in the settings). The view is back to private already.
            root.chatEnqueue(["leave-wait", "leave-remove", "leave-lock", "leave-status", "leave-destroy"])
        }
    }

    // Plasma's activation (the keyboard shortcut): closes an open popup,
    // else opens it on the target from Settings → General.
    function openFromShortcut() {
        root.shortcutOpen = !root.expanded
        if (root.shortcutOpen) {
            var plan = SettingsLogic.shortcutPlan(root.shortcutTarget, root.popupTabs,
                root.chatSiteIds.indexOf(OllamaChat.ENTRY.id) >= 0)
            if (plan.tab !== "")
                root.popupTab = plan.tab
            if (plan.site !== "")
                root.chatSiteId = plan.site
            root.expanded = true
            if (plan.focusInput)
                root.ollamaFocusRequested()
        }
        // Plasma expands the popup itself right after this handler (spike
        // K1), so the close is applied once it is done.
        Qt.callLater(root.finishShortcut)
    }

    // A middle-click on the panel icon, as chosen in Settings → General.
    function middleClick() {
        var plan = SettingsLogic.middleClickPlan(root.middleClickTarget, {
            expanded: root.expanded,
            tabs: root.popupTabs,
            siteIds: root.chatSiteIds,
            shownTab: root.shownTab,
            siteId: root.chatSiteId
        })
        if (plan.action === "refresh") {
            root.refresh()
        } else if (plan.action === "toggle") {
            root.expanded = !root.expanded
        } else if (plan.action === "close") {
            root.expanded = false
        } else {
            root.popupTab = plan.tab
            if (plan.site !== "")
                root.chatSiteId = plan.site
            root.expanded = true
            if (plan.focusInput)
                root.ollamaFocusRequested()
        }
    }

    // Text dropped on the panel icon: open the popup on Ollama with it in the
    // message box. One character over the limit is enough for the view to
    // refuse it.
    function dropToOllama(text) {
        if (typeof text !== "string" || text === "" || !root.ollamaDropTarget)
            return
        root.pendingDrop = text.length > OllamaChat.MAX_PROMPT_CHARS
            ? text.slice(0, OllamaChat.MAX_PROMPT_CHARS + 1) : text
        root.popupTab = "chat"
        root.chatSiteId = OllamaChat.ENTRY.id
        root.expanded = true
    }

    // A single text file dropped on the icon: open the popup on Ollama and
    // read it there (hex is the path, see PromptLibrary.hexPath).
    function dropFileToOllama(hex) {
        if (!root.ollamaDropTarget)
            return
        root.popupTab = "chat"
        root.chatSiteId = OllamaChat.ENTRY.id
        root.expanded = true
        root.readDroppedFile(hex)
    }

    // The helper reads the file (regular, at most 128 KiB, UTF-8 text) and
    // returns its text, which goes into the message box like dropped text.
    function readDroppedFile(hex) {
        if (!root.ollamaDropTarget || root.droppedSourceName !== "")
            return
        root.droppedRun = ChatStorage.nextRun(root.droppedRun)
        var command = PromptLibrary.readDroppedCommand(hex, root.droppedRun, Math.max(0, root.chatAppletId))
        if (command === "") {
            root.pendingDropError = "not-file"
            return
        }
        root.droppedSourceName = command
        droppedSource.connectSource(command)
    }

    function droppedDone(reply) {
        root.droppedSourceName = ""
        if (reply.ok && reply.text !== "")
            root.pendingDrop = reply.text
        else
            root.pendingDropError = reply.ok ? "not-text" : reply.error
    }

    // --- Prompt library: helper jobs, one at a time ------------------------

    // op: list, add {kind}, replace {id}, remove {id}, set-persona {model, id|null}
    function libraryRequest(op, args) {
        root.libraryQueue = root.libraryQueue.concat([{ op: op, args: args || {} }])
        if (root.libraryOp === "")
            Qt.callLater(root.libraryNext)
    }

    function libraryNext() {
        if (root.libraryOp !== "" || root.libraryQueue.length === 0)
            return
        var job = root.libraryQueue[0]
        root.libraryQueue = root.libraryQueue.slice(1)
        if (!root.libraryAvailable) {
            Qt.callLater(root.libraryNext)
            return
        }
        root.libraryRun = ChatStorage.nextRun(root.libraryRun)
        var command = PromptLibrary.promptsCommand(job.op, root.libraryRun, Math.max(0, root.chatAppletId), job.args)
        if (command === "") {
            root.libraryError = "failed"
            Qt.callLater(root.libraryNext)
            return
        }
        if (job.op === "list" && root.libraryState !== "ready")
            root.libraryState = "loading"
        root.libraryOp = job.op
        root.librarySourceName = command
        librarySource.connectSource(command)
    }

    function libraryFinish(op, exitCode, stdout) {
        root.libraryOp = ""
        root.librarySourceName = ""
        if (op === "list") {
            var list = PromptLibrary.parseList(exitCode, stdout)
            if (!root.libraryAvailable || (!list.ok && list.error === "locked")) {
                root.libraryClear()
            } else if (list.ok) {
                root.libraryItems = list.items
                root.libraryPersonas = list.personas
                root.libraryState = "ready"
            } else {
                root.libraryState = "error"
                root.libraryError = list.error
            }
        } else {
            var change = PromptLibrary.parseChange(exitCode, stdout)
            root.libraryError = change.ok || change.error === "cancelled" ? "" : change.error
            root.libraryRequest("list")
        }
        Qt.callLater(root.libraryNext)
    }

    // Locked (or Stay signed in off): the saved items leave memory.
    function libraryClear() {
        root.libraryQueue = root.libraryQueue.filter(function (job) { return job.op === "list" })
        root.libraryItems = []
        root.libraryPersonas = ({})
        root.libraryState = ""
        gc()
    }

    function addSessionItem(kind, text) {
        if (PromptLibrary.KINDS.indexOf(kind) < 0 || typeof text !== "string" || text.trim() === ""
                || text.length > PromptLibrary.MAX_CHARS[kind]
                || root.sessionLibrary.length >= PromptLibrary.MAX_ITEMS)
            return false
        root.sessionLibrary = root.sessionLibrary.concat([{ id: root.sessionLibraryNext, kind: kind, text: text }])
        root.sessionLibraryNext -= 1
        return true
    }

    function removeSessionItem(id) {
        root.sessionLibrary = root.sessionLibrary.filter(function (item) { return item.id !== id })
    }

    onLibraryAvailableChanged: {
        if (root.libraryAvailable)
            root.libraryRequest("list")
        else
            root.libraryClear()
    }

    function finishShortcut() {
        if (root.expanded !== root.shortcutOpen)
            root.expanded = root.shortcutOpen
    }

    // factor must be one of ZOOM_STEPS; 1.0 removes the site's zoom.
    function setSiteZoom(siteId, factor) {
        if (root.chatZoomIds.indexOf(siteId) < 0 || SettingsLogic.ZOOM_STEPS.indexOf(factor) < 0)
            return
        root.chatZoom = SettingsLogic.parseZoomMap(
            SettingsLogic.zoomMapToPersist(root.chatZoom, siteId, factor), root.chatZoomIds)
        zoomWriteTimer.restart()
    }

    // direction: +1 bigger, -1 smaller, 0 back to 100%.
    function stepSiteZoom(siteId, direction) {
        root.setSiteZoom(siteId, SettingsLogic.zoomStep(
            SettingsLogic.zoomFor(root.chatZoom, siteId), direction))
    }

    // Fresh percentage windows of the providers this run reported, for the
    // metrics the Usage tab shows. Stale and failed providers are left out,
    // so they keep their alert state.
    function alertReadings(providerIds) {
        var readings = []
        var groups = root.tooltipProviderGroups()
        for (var groupIndex = 0; groupIndex < groups.length; groupIndex++) {
            var group = groups[groupIndex]
            if (providerIds.indexOf(group.provider_id) < 0 || group.provider.status !== "ok")
                continue
            for (var metricIndex = 0; metricIndex < group.metrics.length; metricIndex++) {
                var window = SnapshotLogic.windowFor(group.provider, group.metrics[metricIndex])
                if (!window || typeof window.used_percent !== "number")
                    continue
                var resetsAt = typeof window.resets_at === "string"
                    ? new Date(window.resets_at).getTime() : NaN
                readings.push({
                    providerId: group.provider_id,
                    metricId: group.metrics[metricIndex],
                    usedPercent: window.used_percent,
                    resetsAtMs: isFinite(resetsAt) ? resetsAt : null
                })
            }
        }
        return readings
    }

    function checkAlerts(results) {
        if (!root.usageShown)
            return
        var providerIds = []
        var list = Array.isArray(results) ? results : []
        for (var index = 0; index < list.length; index++) {
            if (list[index] && typeof list[index].provider_id === "string")
                providerIds.push(list[index].provider_id)
        }
        var result = AlertLogic.evaluate(root.alertState, root.alertReadings(providerIds), {
            lowEnabled: Plasmoid.configuration.alertLowEnabled === true,
            lowPercent: SettingsLogic.normalizeAlertPercent(Plasmoid.configuration.alertLowPercent),
            resetEnabled: Plasmoid.configuration.alertResetEnabled === true
        })
        root.alertState = result.state
        for (var alertIndex = 0; alertIndex < result.alerts.length; alertIndex++)
            root.notifyAlert(result.alerts[alertIndex])
    }

    // Plasma reads a little markup in a notification's body (its title is
    // plain text): the body's name is escaped.
    function markupSafe(text) {
        return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    }

    // Catalog names and a whole percentage only; never helper text.
    function notifyAlert(alert) {
        var descriptor = Catalog.byId(alert.providerId)
        var metric = Catalog.metric(alert.providerId, alert.metricId)
        if (!descriptor || !metric)
            return
        var notification = alertNotification.createObject(root, {
            reset: alert.kind === "reset",
            providerName: descriptor.display_name,
            metricName: root.markupSafe(metric.title),
            percentLeft: Math.max(0, Math.min(100, Math.round(Number(alert.left) || 0)))
        })
        if (notification)
            notification.sendEvent()
    }

    function setUsageMode(mode) {
        Plasmoid.configuration.usageMode = mode === "used" ? "used" : "remaining"
    }

    Plasma5Support.DataSource {
        id: usageSource
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            usageSource.disconnectSource(source)
            if (source === root.refreshSource) {
                root.refreshInFlight = false
                root.refreshSource = ""
            }
            var code = data["exit code"]
            var output = (data["stdout"] || "").toString()
            if (code === 0 && output.trim().length > 0) {
                var payload = null
                try {
                    payload = JSON.parse(output)
                    root.applySnapshot(payload)
                } catch (error) {
                    payload = null
                    root.lastError = i18n("Could not parse helper output")
                }
                if (payload)
                    root.checkAlerts(payload.providers)
            } else {
                var errorText = (data["stderr"] || "").toString().trim()
                root.lastError = errorText.length > 0
                    ? errorText.split("\n").pop()
                    : i18n("Helper exited with code %1", code)
            }
            if (!root.refreshInFlight && root.refreshQueued) {
                root.refreshQueued = false
                Qt.callLater(root.refresh)
            }
        }
    }

    // Prompt library jobs; only stdout's checked fields are used.
    Plasma5Support.DataSource {
        id: librarySource
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            librarySource.disconnectSource(source)
            if (source !== root.librarySourceName)
                return
            root.libraryFinish(root.libraryOp, data["exit code"], data["stdout"])
        }
    }

    // Reads one dropped text file; only stdout's checked text is used.
    Plasma5Support.DataSource {
        id: droppedSource
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            droppedSource.disconnectSource(source)
            if (source !== root.droppedSourceName)
                return
            root.droppedDone(PromptLibrary.parseDropped(data["exit code"], data["stdout"]))
        }
    }

    Plasma5Support.DataSource {
        id: storageSource
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            storageSource.disconnectSource(source)
            if (source !== root.chatOpSource)
                return
            // Only stdout's known words are used; stderr is never read.
            root.chatFinish(root.chatOp, ChatStorage.replyFor(data["exit code"], data["stdout"]))
        }
    }

    Timer {
        id: chatWaitTimer
        interval: 1000
        repeat: false
        onTriggered: {
            root.chatOp = ""
            root.chatNext()
        }
    }

    // Rechecks the folder shortly after the saved profile is built; a busy
    // reply keeps things as they are.
    Timer {
        id: chatRecheckTimer
        interval: 2000
        repeat: false
        onTriggered: {
            if (root.chatStorageReady)
                root.chatEnqueue(["status"])
        }
    }

    // Starts (and refreshes at once) when the Usage tab is shown again.
    Timer {
        interval: root.refreshInterval * 1000
        running: root.usageShown
        repeat: true
        triggeredOnStart: true
        onTriggered: root.refresh()
    }

    // Stores the zoom a second after the last Ctrl+= / Ctrl+- / Ctrl+0, so
    // holding a key writes the configuration once.
    Timer {
        id: zoomWriteTimer
        interval: 1000
        repeat: false
        onTriggered: {
            Plasmoid.configuration.chatSiteZoom = SettingsLogic.zoomMapToPersist(root.chatZoom, "", 1.0)
        }
    }

    // One usage alert; destroyed by itself once shown (autoDelete).
    Component {
        id: alertNotification

        Notification {
            property bool reset: false
            property string providerName: ""
            property string metricName: ""
            property int percentLeft: 0

            componentName: "hearthwire"
            eventId: reset ? "usageReset" : "usageLow"
            iconName: "hearthwire"
            urgency: Notification.NormalUrgency
            autoDelete: true
            title: reset ? i18n("%1 has reset", providerName) : i18n("%1 is running low", providerName)
            text: reset ? i18n("%1 is available again.", metricName) : i18n("%1: %2% left", metricName, percentLeft)
        }
    }

    Timer {
        id: firstRunSettingsTimer
        interval: 1200
        repeat: false
        onTriggered: Plasmoid.internalAction("configure").trigger()
    }

    // Settings schema 2 -> 3, once: the reading boxes now filter the Usage
    // tab. A choice saved for the hover popup moves to tooltipMetrics (unless
    // it has its own), and the Usage tab shows every reading again.
    function migrateUsageMetrics() {
        var next = UsageLogic.migratedUsageMetrics(Plasmoid.configuration.providerMetrics,
            Plasmoid.configuration.tooltipMetrics, Catalog.providers)
        if (Plasmoid.configuration.tooltipMetrics !== next.tooltipMetrics)
            Plasmoid.configuration.tooltipMetrics = next.tooltipMetrics
        if (Plasmoid.configuration.providerMetrics !== next.providerMetrics)
            Plasmoid.configuration.providerMetrics = next.providerMetrics
    }

    Component.onCompleted: {
        if (Plasmoid.configuration.refreshInterval !== root.refreshInterval)
            Plasmoid.configuration.refreshInterval = root.refreshInterval
        // A fresh widget has nothing to migrate.
        if (Plasmoid.configuration.initialSetupComplete && Number(Plasmoid.configuration.configSchemaVersion) < 3)
            root.migrateUsageMetrics()
        if (Plasmoid.configuration.configSchemaVersion !== 3)
            Plasmoid.configuration.configSchemaVersion = 3
        if (!Plasmoid.configuration.initialSetupComplete) {
            Plasmoid.configuration.initialSetupComplete = true
            firstRunSettingsTimer.start()
        }
        root.syncChatSite()
        root.popupTab = SettingsLogic.normalizeDefaultTab(Plasmoid.configuration.popupDefaultTab)
        root.chatGeneration = root.chatConfiguredGeneration
        root.chatModeSeen = root.chatStorageMode
        root.chatOpRun = ChatStorage.firstRun(Date.now(), Math.random())
        root.libraryRun = ChatStorage.firstRun(Date.now(), Math.random())
        root.droppedRun = ChatStorage.firstRun(Date.now(), Math.random())
        root.chatZoom = SettingsLogic.parseZoomMap(Plasmoid.configuration.chatSiteZoom, root.chatZoomIds)
        // Plasma start, Unlock with KDE Wallet: open the folder silently when
        // the wallet is already open (the helper never prompts here). The
        // step is dropped unless status says locked with a wallet slot.
        if (root.chatStorageMode === "encrypted" && root.chatUnlockSetting === "wallet")
            root.chatEnqueue(["status", "auto-unlock"])
    }

    // The zoom map changed outside this widget (e.g. Defaults in the
    // settings); a write of our own still waiting wins.
    readonly property string configuredZoom: Plasmoid.configuration.chatSiteZoom
    onConfiguredZoomChanged: {
        if (!zoomWriteTimer.running)
            root.chatZoom = SettingsLogic.parseZoomMap(root.configuredZoom, root.chatZoomIds)
    }

    // A zoom still waiting is stored before the widget goes (Plasma quits,
    // the widget is removed), through the timer's own handler.
    Component.onDestruction: {
        if (zoomWriteTimer.running) {
            zoomWriteTimer.stop()
            zoomWriteTimer.triggered()
        }
    }

    onChatStorageModeChanged: root.chatModeChanged()
    // A settings dialog opened earlier may write back an old generation.
    onChatConfiguredGenerationChanged: {
        if (root.chatGeneration >= 0 && root.chatConfiguredGeneration !== root.chatGeneration)
            Plasmoid.configuration.chatProfileGeneration = root.chatGeneration
    }

    onTrackedProvidersChanged: {
        root.rebuildVisibleProviders()
        root.refresh()
    }
    onExpandedChanged: {
        if (root.expanded) {
            root.refresh()
            if (root.chatShown && root.chatStorageMode === "encrypted" && root.chatVaultState !== "")
                root.chatEnqueue(["status"])
        }
    }
    onChatSiteIdsChanged: {
        root.syncChatSite()
        if (root.chatSplit)
            root.syncSplitSite()
    }
    // Settings → General → Open on.
    readonly property string configuredDefaultTab:
        SettingsLogic.normalizeDefaultTab(Plasmoid.configuration.popupDefaultTab)
    onConfiguredDefaultTabChanged: root.popupTab = root.configuredDefaultTab
    onChatSiteIdChanged: {
        if (root.chatSiteId !== OllamaChat.ENTRY.id)
            root.chatWebSiteId = root.chatSiteId
    }

    // The keyboard shortcut (set in Plasma's Keyboard Shortcuts tab) goes
    // through openFromShortcut, never Plasma's plain toggle.
    activationTogglesExpanded: false
    Connections {
        target: Plasmoid
        function onActivated() {
            root.openFromShortcut()
        }
    }

    // Settings → General → Keep the popup open; also while a dialog is open.
    hideOnWindowDeactivate: !Plasmoid.configuration.chatKeepOpen && !root.chatDialogOpen

    Plasmoid.icon: Qt.resolvedUrl("../images/hearthwire.svg")
    Plasmoid.busy: root.usageShown && !root.hasData && root.lastError === ""
    toolTipMainText: i18n("Hearthwire")
    // Provider names, plans and helper errors: never rich text.
    toolTipTextFormat: Text.PlainText
    // Errors, loading and "no usage" as one line of text; the readings use
    // the UsageTooltip layout below instead.
    toolTipSubText: {
        if (!root.usageShown || !root.tooltipShowsUsage)
            return ""
        if (root.lastError !== "" && !root.hasData)
            return i18n("Error: %1", root.lastError)
        if (!root.hasData)
            return i18n("Loading…")
        if (root.tooltipSections.length === 0)
            return i18n("No usage to show.")
        return ""
    }
    // AI Provider Settings → Hover popup: each provider in bold with one
    // reading per line, a dot in its level color (percentages only); no bars
    // or reset times, to keep it short.
    readonly property var tooltipSections: {
        if (!root.usageShown || !root.tooltipShowsUsage || !root.hasData)
            return []
        var groups = []
        for (var groupIndex = 0; groupIndex < root.tooltipGroups.length; groupIndex++) {
            var group = root.tooltipGroups[groupIndex]
            var items = []
            for (var metricIndex = 0; metricIndex < group.metrics.length; metricIndex++) {
                var metricId = group.metrics[metricIndex]
                var metric = Catalog.metric(group.provider_id, metricId)
                if (!metric)
                    continue
                var reading = root.metricReading(group.provider, metricId)
                items.push({
                    title: metric.title,
                    value: root.tooltipValue(reading),
                    level: reading && reading.type === "percentage"
                        ? UsageLogic.usageLevel(reading.raw_used, root.usageThresholds) : ""
                })
            }
            groups.push({name: group.descriptor.display_name, items: items})
        }
        return TooltipLogic.tooltipSections(groups)
    }
    property Item usageTooltip: UsageTooltip {
        title: i18n("Hearthwire")
        sections: root.tooltipSections
        normalColor: root.normalUsageColor
        warningColor: root.warnUsageColor
        criticalColor: root.criticalUsageColor
    }
    toolTipItem: root.tooltipSections.length > 0 ? root.usageTooltip : null

    compactRepresentation: CompactRepresentation {}
    fullRepresentation: FullRepresentation {}

    Plasmoid.contextualActions: [
        PlasmaCore.Action {
            text: i18n("Refresh now")
            icon.name: "view-refresh"
            visible: root.usageShown
            onTriggered: root.refresh()
        }
    ]
}
