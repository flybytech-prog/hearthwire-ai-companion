import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as Plasma5Support
import "ChatStorage.js" as ChatStorage
import "ChatSites.js" as ChatSites
import "UsageHistory.js" as UsageHistory
import "SettingsBackup.js" as SettingsBackup
import "UsageLogic.js" as UsageLogic
import "OllamaChat.js" as OllamaChat
import "SettingsLogic.js" as SettingsLogic
import "ProviderCatalog.js" as Catalog
import "InstallInfo.js" as InstallInfo

KCM.SimpleKCM {
    id: page

    // Every key is declared so the config dialog can map all of them.
    property string cfg_trackedProviders:
        "[\"claude\",\"codex\",\"cursor\",\"antigravity\",\"copilot\",\"devin\",\"grok\"]"
    property string cfg_trackedProvidersDefault:
        "[\"claude\",\"codex\",\"cursor\",\"antigravity\",\"copilot\",\"devin\",\"grok\"]"
    property string cfg_providerMetrics: "{}"
    property string cfg_providerMetricsDefault: "{}"
    property string cfg_usageMode: "remaining"
    property string cfg_usageModeDefault: "remaining"
    property int cfg_refreshInterval: 300
    property int cfg_refreshIntervalDefault: 300
    property int cfg_configSchemaVersion: 2
    property int cfg_configSchemaVersionDefault: 2
    property bool cfg_initialSetupComplete: false
    property bool cfg_initialSetupCompleteDefault: false
    property string cfg_chatSites:
        "[\"claude\",\"chatgpt\",\"grok\",\"gemini\",\"copilot\",\"mscopilot\"]"
    property string cfg_chatSitesDefault:
        "[\"claude\",\"chatgpt\",\"grok\",\"gemini\",\"copilot\",\"mscopilot\"]"
    property string cfg_chatDefaultSite: "claude"
    property string cfg_chatDefaultSiteDefault: "claude"
    property string cfg_chatCustomUrls: "{}"
    property string cfg_chatCustomUrlsDefault: "{}"
    property string cfg_chatSignInStorage: "memory"
    property string cfg_chatSignInStorageDefault: "memory"
    // Written only by main.qml; kept in step so Apply never writes back an
    // old value.
    property int cfg_chatProfileGeneration: 0
    property int cfg_chatProfileGenerationDefault: 0
    property int cfg_chatAutoLockMinutes: 0
    property int cfg_chatAutoLockMinutesDefault: 0
    property string cfg_chatVaultUnlock: "passphrase"
    property string cfg_chatVaultUnlockDefault: "passphrase"
    property bool cfg_chatKeepOpen: false
    property bool cfg_chatKeepOpenDefault: false
    property string cfg_chatOllamaUrl: "http://127.0.0.1:11434"
    property string cfg_chatOllamaUrlDefault: "http://127.0.0.1:11434"
    property string cfg_popupDefaultTab: "chat"
    property string cfg_popupDefaultTabDefault: "chat"
    property bool cfg_showUsageTab: true
    property bool cfg_showUsageTabDefault: true
    property bool cfg_showChatTab: true
    property bool cfg_showChatTabDefault: true
    property string cfg_popupSize: "normal"
    property string cfg_popupSizeDefault: "normal"
    property bool cfg_tooltipShowsUsage: true
    property bool cfg_tooltipShowsUsageDefault: true
    property string cfg_tooltipMetrics: ""
    property string cfg_tooltipMetricsDefault: ""
    property string cfg_shortcutOpens: "popup"
    property string cfg_shortcutOpensDefault: "popup"
    // Written only by main.qml (zoom keys, Ctrl+wheel); kept in step so
    // Apply never writes back an old value.
    property string cfg_chatSiteZoom: "{}"
    property string cfg_chatSiteZoomDefault: "{}"
    property bool cfg_alertLowEnabled: false
    property bool cfg_alertLowEnabledDefault: false
    property int cfg_alertLowPercent: 20
    property int cfg_alertLowPercentDefault: 20
    property bool cfg_alertResetEnabled: false
    property bool cfg_alertResetEnabledDefault: false
    property string cfg_providerOrder: ""
    property string cfg_providerOrderDefault: ""
    property bool cfg_usageCompact: false
    property bool cfg_usageCompactDefault: false
    property int cfg_usageWarnPercent: 60
    property int cfg_usageWarnPercentDefault: 60
    property int cfg_usageCriticalPercent: 85
    property int cfg_usageCriticalPercentDefault: 85
    property string cfg_usageNormalColor: ""
    property string cfg_usageNormalColorDefault: ""
    property string cfg_usageWarnColor: ""
    property string cfg_usageWarnColorDefault: ""
    property string cfg_usageCriticalColor: ""
    property string cfg_usageCriticalColorDefault: ""
    property string cfg_panelRing: "auto"
    property string cfg_panelRingDefault: "auto"
    property string cfg_middleClickOpens: "refresh"
    property string cfg_middleClickOpensDefault: "refresh"
    property bool cfg_usageHistoryEnabled: false
    property bool cfg_usageHistoryEnabledDefault: false
    // Written only by main.qml; kept in step so Apply never writes back an
    // old value.
    property bool cfg_usageHistoryClearOwed: false
    property bool cfg_usageHistoryClearOwedDefault: false

    // Page-local only; the folder actions always start collapsed.
    property bool showFolderActions: false
    // The width wrapped text asks the form for. Without it a long label asks
    // for its unwrapped width, the form drops to its narrow mode, and there
    // its fields are wider than the form, so their right edge is cut off.
    readonly property real wrappedTextWidth: Kirigami.Units.gridUnit * 22
    readonly property var refreshChoices: [
        { value: 60, text: i18n("1 minute") },
        { value: 300, text: i18n("5 minutes") },
        { value: 900, text: i18n("15 minutes") },
        { value: 1800, text: i18n("30 minutes") },
        { value: 3600, text: i18n("1 hour") }
    ]
    readonly property var shortcutChoices: [
        { value: "popup", text: i18n("As when clicking the icon") },
        { value: "chat", text: i18n("Chat") },
        { value: "ollama", text: i18n("Ollama message box") },
        { value: "usage", text: i18n("Usage") }
    ]
    // Refresh, the Usage tab, Ollama or a web site, enabled or not: a site
    // that is off acts as a normal click (SettingsLogic.middleClickPlan).
    readonly property var middleClickChoices: [
        { value: "refresh", text: i18n("Refresh usage") },
        { value: "usage", text: i18n("Usage") },
        { value: "ollama", text: i18n("Ollama message box") }
    ].concat(ChatSites.sites.map(function (site) {
        return { value: site.id, text: site.name }
    }))
    readonly property var alertChoices: SettingsLogic.ALERT_PERCENTS.map(function (percent) {
        return { value: percent, text: i18n("%1%", percent) }
    })
    readonly property var sizeChoices: [
        { value: "compact", text: i18n("Compact") },
        { value: "normal", text: i18n("Normal") },
        { value: "large", text: i18n("Large") }
    ]

    // Stay signed in. The mode the page opened with decides whether turning
    // it off needs a confirmation (applying it deletes the encrypted folder).
    property string savedSignInMode: "memory"
    readonly property string signInMode: ChatStorage.normalizeMode(page.cfg_chatSignInStorage)
    property bool confirmingOff: false
    property bool confirmingDelete: false
    // Encrypted folder, as the helper reports it: "", absent, locked,
    // unlocked, unavailable, error. Never a path.
    property string vaultState: ""
    property var vaultMissing: []
    property string vaultOp: ""
    property string vaultSourceName: ""
    // Seeded in Component.onCompleted; see ChatStorage.firstRun.
    property int vaultRun: 0
    // Only makes the helper's source name unique; 0 if the id is odd.
    readonly property int vaultApplet: Math.max(0, ChatStorage.validInt(Plasmoid.id))
    property string vaultMessage: ""
    // The KDE Wallet key slot as status reports it: "", set-up, off, unavailable.
    property string vaultWallet: ""
    property bool confirmingWalletOff: false
    // Unlock with shows the real key slot: KDE Wallet while one is set up,
    // also before Apply (see walletNotApplied).
    readonly property var walletChoice: ChatStorage.walletChoice(page.cfg_chatVaultUnlock, page.vaultWallet)
    readonly property string unlockShown: page.walletChoice.shown
    readonly property bool walletNotApplied: page.walletChoice.notApplied
    // The choice needs an existing folder (locked or unlocked) under the
    // applied Stay signed in → Encrypted, and a usable KDE Wallet.
    readonly property bool unlockChoiceEnabled: page.signInMode === "encrypted"
        && page.savedSignInMode === "encrypted"
        && (page.vaultState === "locked" || page.vaultState === "unlocked")
        && (page.vaultWallet === "set-up" || page.vaultWallet === "off")
        && page.vaultOp === ""
    // Tools only the KDE Wallet unlock needs, as status reports them.
    readonly property var walletMissing: page.vaultMissing.filter(function (name) {
        return ChatStorage.WALLET_TOOLS.indexOf(name) >= 0
    })

    // Where the helper and widget come from, read once per page open (this
    // page can't reach main.qml's copy); unknown until then.
    property var installInfo: InstallInfo.unknown()
    property string installInfoSourceName: ""
    property bool installInfoAsked: false
    // The run without -s has been asked (at most once).
    property bool installInfoRetried: false
    readonly property string installDistro: ChatStorage.installDistro(page.installInfo.distro)
    // The remedy the notice names, offered for copying.
    readonly property string removeScriptCommand: "./scripts/install.sh --remove-script-install"

    function checkInstall() {
        if (page.installInfoAsked)
            return
        page.installInfoAsked = true
        page.runInstallInfo(false)
    }

    function runInstallInfo(retry) {
        var command = InstallInfo.command(ChatStorage.firstRun(Date.now(), Math.random()),
                                          page.vaultApplet, retry)
        if (command === "")
            return
        page.installInfoSourceName = command
        installInfoSource.connectSource(command)
    }

    // A failed -s run is asked once more without -s; every reply that
    // counts goes through the same strict parse.
    function finishInstallInfo(exitCode, stdout) {
        page.installInfoSourceName = ""
        if (InstallInfo.needsRetry(exitCode, page.installInfoRetried)) {
            page.installInfoRetried = true
            page.runInstallInfo(true)
            return
        }
        page.installInfo = InstallInfo.parseReply(exitCode, stdout)
    }

    function normalizedRefresh(value) {
        var best = page.refreshChoices[0].value
        for (var index = 1; index < page.refreshChoices.length; index++) {
            var candidate = page.refreshChoices[index].value
            if (Math.abs(candidate - value) < Math.abs(best - value))
                best = candidate
        }
        return best
    }

    function choiceIndex(choices, value, fallback) {
        for (var index = 0; index < choices.length; index++) {
            if (choices[index].value === value)
                return index
        }
        return fallback
    }

    function syncSignInChoice() {
        offChoice.checked = page.signInMode === "memory"
        encryptedChoice.checked = page.signInMode === "encrypted"
    }

    function chooseSignIn(mode) {
        page.confirmingOff = false
        if (mode === "memory" && page.signInMode === "encrypted"
                && page.savedSignInMode === "encrypted") {
            page.confirmingOff = true
            page.syncSignInChoice()
            return
        }
        page.cfg_chatSignInStorage = mode
    }

    function syncUnlockChoice() {
        unlockChoice.currentIndex = page.unlockShown === "wallet" ? 1 : 0
    }

    // KDE Wallet is set up at once (the helper asks for the passphrase) and
    // only then chosen; Passphrase removes the wallet's key after a confirm.
    function chooseUnlock(method) {
        page.confirmingWalletOff = false
        if (method === "wallet") {
            // A key that is already set up is just chosen again.
            if (page.unlockShown === "wallet")
                page.useWalletSlot()
            else
                page.runVault("add-key", "wallet")
        } else if (page.vaultWallet === "set-up") {
            page.confirmingWalletOff = true
        } else {
            page.cfg_chatVaultUnlock = "passphrase"
        }
        page.syncUnlockChoice()
    }

    // Only a key slot the helper reports as set up is chosen without add-key.
    function useWalletSlot() {
        if (page.vaultWallet === "set-up")
            page.cfg_chatVaultUnlock = "wallet"
    }

    function runVault(op, method) {
        if (page.vaultOp !== "")
            return
        page.vaultRun = ChatStorage.nextRun(page.vaultRun)
        var command = ChatStorage.vaultCommand(op, page.vaultRun, page.vaultApplet, method)
        if (command === "")
            return
        page.vaultOp = op
        page.vaultSourceName = command
        page.confirmingDelete = false
        if (op !== "status")
            page.vaultMessage = ""
        vaultSource.connectSource(command)
    }

    function finishVault(op, reply) {
        page.vaultOp = ""
        page.vaultSourceName = ""
        if (op === "status") {
            page.vaultState = reply.ok && reply.state ? reply.state : "error"
            page.vaultMissing = reply.missing || []
            page.vaultWallet = reply.ok && reply.wallet ? reply.wallet : ""
            page.syncUnlockChoice()
            return
        }
        if (reply.ok && op === "add-key")
            page.cfg_chatVaultUnlock = "wallet"
        else if (reply.ok && op === "remove-key")
            page.cfg_chatVaultUnlock = "passphrase"
        if (reply.ok)
            page.vaultMessage = op === "destroy" ? "deleted" : op === "add-key" ? "wallet-on"
                : op === "remove-key" ? "wallet-off" : "changed"
        // The folder is gone but its wallet entry stayed: a retry would
        // report success without touching the wallet, so say what is left.
        else if (op === "destroy" && reply.error === "wallet-failed")
            page.vaultMessage = "deleted-wallet-left"
        else
            page.vaultMessage = reply.error === "cancelled" || reply.error === "empty-passphrase"
                ? "" : reply.error
        page.runVault("status")
    }

    // Delete usage history: "", busy, ok or an error code; the text is
    // fixed, the helper's own text is never shown.
    property string historyClearState: ""
    property string historyClearName: ""
    property int historyClearRun: 0

    // This widget's history only; nothing runs without a usable id.
    function clearHistory() {
        if (page.historyClearState === "busy")
            return
        page.historyClearRun = ChatStorage.nextRun(page.historyClearRun)
        var command = UsageHistory.historyCommand("clear", page.historyClearRun, Plasmoid.id)
        if (command === "") {
            page.historyClearState = "no-applet"
            return
        }
        page.historyClearState = "busy"
        page.historyClearName = command
        historyClearSource.connectSource(command)
    }

    function historyClearText(state) {
        switch (state) {
        case "":
        case "busy":
            return ""
        case "ok":
            return i18n("Usage history deleted.")
        case "no-applet":
            return i18n("This widget couldn't be identified, so its usage history can't be deleted.")
        default:
            return i18n("Couldn't delete the usage history. Try again in a moment.")
        }
    }

    // --- Backup: one fixed file, chosen by the helper ----------------------

    // "" checking, exists, absent, or an error code.
    property string backupState: ""
    property string backupExportedAt: ""
    property string backupOp: ""
    property string backupSourceName: ""
    property int backupRun: 0
    // The last result as a code; backupText() has its fixed text.
    property string backupMessage: ""
    property int backupDropped: 0
    property bool confirmingExport: false
    property bool confirmingImport: false
    // What Replace would apply (SettingsBackup.importPlan), until then.
    property var backupPlan: null
    // The chat addresses it would change (SettingsBackup.addressChanges).
    property var backupAddressChanges: []

    // Every step names this widget; nothing runs without a usable id.
    function runBackup(op) {
        if (page.backupOp !== "")
            return
        page.backupRun = ChatStorage.nextRun(page.backupRun)
        var command = SettingsBackup.backupCommand(op, page.backupRun, Plasmoid.id)
        if (command === "") {
            if (op === "status")
                page.backupState = "no-applet"
            else
                page.backupMessage = "no-applet"
            return
        }
        page.backupOp = op
        page.backupSourceName = command
        backupSource.connectSource(command)
    }

    function requestExport() {
        page.backupMessage = ""
        // Only a backup known to be absent can't be overwritten.
        if (page.backupState === "absent")
            page.exportBackup()
        else
            page.confirmingExport = true
    }

    // The helper saves this widget's applied settings; nothing of this
    // page goes with the command.
    function exportBackup() {
        page.confirmingExport = false
        page.runBackup("export")
    }

    function requestImport() {
        page.backupMessage = ""
        page.confirmingImport = false
        page.backupPlan = null
        page.backupAddressChanges = []
        page.runBackup("import")
    }

    function finishBackup(op, reply) {
        page.backupOp = ""
        page.backupSourceName = ""
        if (op === "status") {
            page.backupState = reply.ok ? (reply.exists ? "exists" : "absent") : reply.error
            page.backupExportedAt = reply.ok ? reply.exportedAt : ""
            return
        }
        if (!reply.ok) {
            page.backupMessage = reply.error
            return
        }
        if (op === "export") {
            page.backupMessage = "saved"
            page.backupDropped = reply.dropped
            page.runBackup("status")
            return
        }
        var plan = SettingsBackup.importPlan(reply.settings, reply.dropped, {
            providers: Catalog.providers,
            webSiteIds: ChatSites.siteIds(),
            ringPairs: UsageLogic.ringOptions(Catalog.providers).map(function (option) { return option.value }),
            validateCustomUrl: ChatSites.validateCustomUrl,
            ollamaAddress: OllamaChat.checkedAddress
        })
        page.backupDropped = plan.dropped
        if (plan.applied === 0) {
            page.backupMessage = "nothing"
            return
        }
        page.backupPlan = plan
        page.backupAddressChanges = SettingsBackup.addressChanges(
            {chatCustomUrls: page.cfg_chatCustomUrls, chatOllamaUrl: page.cfg_chatOllamaUrl}, plan, {
                webSiteIds: ChatSites.siteIds(),
                parseCustomUrls: ChatSites.parseCustomUrls,
                effectiveUrl: ChatSites.homeUrl,
                shownText: UsageLogic.shownText
            })
        page.backupExportedAt = reply.exportedAt
        page.confirmingImport = true
    }

    // The address changes as plain lines, "name: old → new", the first
    // SettingsBackup.MAX_SHOWN_CHANGES of them and a count of the rest.
    function addressChangeText(changes) {
        var list = Array.isArray(changes) ? changes : []
        if (list.length === 0)
            return ""
        var lines = [i18np("This changes %1 chat address:", "This changes %1 chat addresses:", list.length)]
        list.slice(0, SettingsBackup.MAX_SHOWN_CHANGES).forEach(function (change) {
            var site = change.id === SettingsBackup.OLLAMA_ID ? null : ChatSites.byId(change.id)
            var name = site ? site.name : i18n("Ollama")
            lines.push(i18nc("a chat address: site, old address, new address", "%1: %2 → %3",
                             name, change.from, change.to))
        })
        if (list.length > SettingsBackup.MAX_SHOWN_CHANGES)
            lines.push(i18np("…and %1 more.", "…and %1 more.", list.length - SettingsBackup.MAX_SHOWN_CHANGES))
        return lines.join("\n")
    }

    // Replace: sets the settings pages' values; Apply saves them. Only keys
    // that are in a backup are ever assigned here.
    function applyBackup() {
        var plan = page.backupPlan
        page.confirmingImport = false
        page.backupPlan = null
        page.backupAddressChanges = []
        if (!plan)
            return
        var values = plan.settings
        if (values.trackedProviders !== undefined) page.cfg_trackedProviders = values.trackedProviders
        if (values.providerMetrics !== undefined) page.cfg_providerMetrics = values.providerMetrics
        if (values.providerOrder !== undefined) page.cfg_providerOrder = values.providerOrder
        if (values.usageMode !== undefined) page.cfg_usageMode = values.usageMode
        if (values.refreshInterval !== undefined) page.cfg_refreshInterval = values.refreshInterval
        if (values.tooltipShowsUsage !== undefined) page.cfg_tooltipShowsUsage = values.tooltipShowsUsage
        if (values.tooltipMetrics !== undefined) page.cfg_tooltipMetrics = values.tooltipMetrics
        if (values.usageCompact !== undefined) page.cfg_usageCompact = values.usageCompact
        if (values.usageWarnPercent !== undefined) page.cfg_usageWarnPercent = values.usageWarnPercent
        if (values.usageCriticalPercent !== undefined) page.cfg_usageCriticalPercent = values.usageCriticalPercent
        if (values.usageNormalColor !== undefined) page.cfg_usageNormalColor = values.usageNormalColor
        if (values.usageWarnColor !== undefined) page.cfg_usageWarnColor = values.usageWarnColor
        if (values.usageCriticalColor !== undefined) page.cfg_usageCriticalColor = values.usageCriticalColor
        if (values.alertLowEnabled !== undefined) page.cfg_alertLowEnabled = values.alertLowEnabled
        if (values.alertResetEnabled !== undefined) page.cfg_alertResetEnabled = values.alertResetEnabled
        if (values.alertLowPercent !== undefined) page.cfg_alertLowPercent = values.alertLowPercent
        if (values.chatSites !== undefined) page.cfg_chatSites = values.chatSites
        if (values.chatDefaultSite !== undefined) page.cfg_chatDefaultSite = values.chatDefaultSite
        if (values.chatOllamaUrl !== undefined) page.cfg_chatOllamaUrl = values.chatOllamaUrl
        if (values.chatKeepOpen !== undefined) page.cfg_chatKeepOpen = values.chatKeepOpen
        if (values.showUsageTab !== undefined) page.cfg_showUsageTab = values.showUsageTab
        if (values.showChatTab !== undefined) page.cfg_showChatTab = values.showChatTab
        if (values.popupDefaultTab !== undefined) page.cfg_popupDefaultTab = values.popupDefaultTab
        if (values.popupSize !== undefined) page.cfg_popupSize = values.popupSize
        if (values.shortcutOpens !== undefined) page.cfg_shortcutOpens = values.shortcutOpens
        if (values.panelRing !== undefined) page.cfg_panelRing = values.panelRing
        if (values.middleClickOpens !== undefined) page.cfg_middleClickOpens = values.middleClickOpens
        if (values.chatCustomUrls !== undefined) page.cfg_chatCustomUrls = values.chatCustomUrls
        page.backupMessage = "applied"
    }

    // Plasma calls this on Apply and OK, before it saves the cfg_ values.
    // A loaded backup is saved then; other results stay true.
    function saveConfig() {
        if (page.backupMessage === "applied")
            page.backupMessage = ""
    }

    function backupStatusText() {
        switch (page.backupState) {
        case "":
            return i18n("Checking…")
        case "exists":
            return i18n("Last backup: %1", SettingsBackup.shownStamp(page.backupExportedAt))
        case "absent":
            return i18n("No backup yet.")
        default:
            return page.backupText(page.backupState)
        }
    }

    function backupText(code) {
        switch (code) {
        case "":
            return ""
        case "saved":
            return i18n("Backup saved.")
        case "applied":
            return i18n("Backup loaded. Press Apply to save it.")
        case "nothing":
            return i18n("The backup has no settings that can be used.")
        case "absent":
            return i18n("There is no backup yet.")
        case "invalid":
            return i18n("The backup file is damaged and can't be read.")
        case "unsupported":
            return i18n("The backup was made by a different version and can't be read.")
        case "too-large":
            return i18n("The settings are too large to back up.")
        case "bad-data":
            return i18n("These settings couldn't be backed up.")
        case "symlink":
        case "not-owned":
        case "unsafe-mode":
            return i18n("The backup file isn't safe to use, so it was left alone. Check the owner and permissions of its folder.")
        case "legacy-data":
            return i18n("Saved sign-ins from the previous version haven't been moved yet. Run the installer again with --restart-plasma.")
        case "applet-not-found":
            return i18n("This widget's applied settings weren't found. Press Apply, then try again. Nothing was changed.")
        case "settings-unreadable":
            return i18n("Plasma's settings file for this widget couldn't be read safely, so nothing was exported. Check the owner and type of ~/.config/plasma-org.kde.plasma.desktop-appletsrc.")
        case "no-applet":
            return i18n("This widget couldn't be identified, so the backup can't be used. Nothing was changed.")
        default:
            return i18n("Something went wrong with the backup. Nothing was changed.")
        }
    }

    function vaultText(code) {
        switch (code) {
        case "":
            return ""
        case "changed":
            return i18n("Passphrase changed.")
        case "deleted":
            return i18n("Encrypted folder deleted.")
        case "wallet-on":
            return i18n("KDE Wallet is set up. Apply to unlock with it.")
        case "wallet-off":
            return i18n("The key was removed from KDE Wallet. The passphrase unlocks the folder.")
        case "missing-tool":
            return i18n("A required tool is missing. Nothing was changed.")
        case "wallet-disabled":
            return i18n("KDE Wallet is turned off. Turn it on in System Settings first.")
        case "wallet-failed":
            return i18n("KDE Wallet didn't answer or was cancelled. Try again.")
        case "deleted-wallet-left":
            return i18n("The encrypted folder was deleted, but its key could not be removed from KDE Wallet (folder Hearthwire, entry encrypted-chat-folder). Remove it in KWalletManager.")
        case "wallet-write-failed":
            return i18n("Couldn't set up KDE Wallet. The passphrase still unlocks the folder.")
        case "wrong-passphrase":
            return i18n("Wrong passphrase. Nothing was changed.")
        case "not-locked":
            return i18n("Lock the encrypted folder from the Chat tab first.")
        case "busy":
            return i18n("The encrypted folder is busy. Try again in a moment.")
        case "damaged":
            return i18n("The encrypted folder is damaged and can't be opened. Nothing was changed.")
        case "legacy-data":
            return i18n("Saved sign-ins from the previous version haven't been moved yet. Run the installer again with --restart-plasma.")
        default:
            return i18n("That didn't work. Nothing was changed.")
        }
    }

    function vaultStateText() {
        switch (page.vaultState) {
        case "absent":
            return i18n("No encrypted folder has been created.")
        case "locked":
            return i18n("The encrypted folder is locked.")
        case "unlocked":
            return i18n("The encrypted folder is unlocked. Lock it from the Chat tab to change its passphrase or delete it.")
        case "unavailable":
            return i18n("gocryptfs isn't installed.")
        case "damaged":
            return i18n("The encrypted folder is damaged and can't be opened. Delete it to start again with a new one.")
        case "":
            return i18n("Checking…")
        default:
            return i18n("Couldn't check the encrypted folder.")
        }
    }

    onCfg_chatSignInStorageChanged: page.syncSignInChoice()
    onUnlockShownChanged: page.syncUnlockChoice()

    Component.onCompleted: {
        page.cfg_refreshInterval = page.normalizedRefresh(page.cfg_refreshInterval)
        page.savedSignInMode = page.signInMode
        page.syncSignInChoice()
        page.vaultRun = ChatStorage.firstRun(Date.now(), Math.random())
        page.historyClearRun = ChatStorage.firstRun(Date.now(), Math.random())
        page.backupRun = ChatStorage.firstRun(Date.now(), Math.random())
        page.runBackup("status")
        page.runVault("status")
        page.checkInstall()
    }

    // main.qml may move to a new generation or store a zoom while this page
    // is open.
    Connections {
        target: Plasmoid.configuration
        function onValueChanged(key, value) {
            if (key === "chatProfileGeneration")
                page.cfg_chatProfileGeneration = value
            else if (key === "chatSiteZoom")
                page.cfg_chatSiteZoom = value
            else if (key === "usageHistoryClearOwed")
                page.cfg_usageHistoryClearOwed = value
        }
    }

    Plasma5Support.DataSource {
        id: vaultSource
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            vaultSource.disconnectSource(source)
            if (source !== page.vaultSourceName)
                return
            page.finishVault(page.vaultOp, ChatStorage.replyFor(data["exit code"], data["stdout"]))
        }
    }

    // The page's one --install-info run; only stdout's checked words are used.
    Plasma5Support.DataSource {
        id: installInfoSource
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            installInfoSource.disconnectSource(source)
            if (source !== page.installInfoSourceName)
                return
            page.finishInstallInfo(data["exit code"], data["stdout"])
        }
    }

    Plasma5Support.DataSource {
        id: historyClearSource
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            historyClearSource.disconnectSource(source)
            if (source !== page.historyClearName)
                return
            page.historyClearName = ""
            var reply = UsageHistory.parseReply("clear", data["exit code"], data["stdout"], Catalog.providers)
            page.historyClearState = reply.ok ? "ok" : reply.error
        }
    }

    Plasma5Support.DataSource {
        id: backupSource
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            backupSource.disconnectSource(source)
            if (source !== page.backupSourceName)
                return
            page.finishBackup(page.backupOp, SettingsBackup.parseReply(page.backupOp, data["exit code"], data["stdout"]))
        }
    }

    QQC2.ButtonGroup {
        id: signInGroup
    }

    Kirigami.FormLayout {
        // A leftover script install shadows the package (InstallInfo); fixed
        // text, never the helper's. The Usage tab says the same.
        Kirigami.InlineMessage {
            objectName: "installShadowedNotice"
            Layout.fillWidth: true
            visible: page.installInfo.shadowed === true
            type: Kirigami.MessageType.Warning
            text: i18n("A script install of Hearthwire is running instead of the installed package. To use the package, run ./scripts/install.sh --remove-script-install from the Hearthwire source folder, then restart Plasma. Your settings, usage history and saved sign-ins are kept.")
        }
        QQC2.TextField {
            objectName: "installShadowedCommand"
            Layout.fillWidth: true
            visible: page.installInfo.shadowed === true
            readOnly: true
            selectByMouse: true
            text: page.removeScriptCommand
        }

        // --- Popup ----------------------------------------------------------

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("Popup")
        }

        QQC2.ComboBox {
            objectName: "defaultTabChoice"
            Kirigami.FormData.label: i18n("Open on:")
            // Only a choice while both tabs are shown.
            enabled: page.cfg_showUsageTab && page.cfg_showChatTab
            textRole: "text"
            valueRole: "value"
            model: [
                { value: "chat", text: i18n("Chat") },
                { value: "usage", text: i18n("Usage") }
            ]
            currentIndex: SettingsLogic.normalizeDefaultTab(page.cfg_popupDefaultTab) === "usage" ? 1 : 0
            onActivated: page.cfg_popupDefaultTab = currentValue
        }

        RowLayout {
            Kirigami.FormData.label: i18n("Show tabs:")
            spacing: Kirigami.Units.smallSpacing

            QQC2.CheckBox {
                objectName: "showUsageChoice"
                text: i18n("Usage")
                checked: page.cfg_showUsageTab
                // The last shown tab can't be unticked.
                enabled: !checked || SettingsLogic.canUntick(page.cfg_showChatTab)
                onToggled: page.cfg_showUsageTab = checked
            }
            QQC2.CheckBox {
                objectName: "showChatChoice"
                text: i18n("Chat")
                checked: page.cfg_showChatTab
                enabled: !checked || SettingsLogic.canUntick(page.cfg_showUsageTab)
                onToggled: page.cfg_showChatTab = checked
            }
            Kirigami.ContextualHelpButton {
                toolTipText: i18n("At least one tab stays shown. A hidden Chat tab opens no chat site and no Ollama chat, and locks saved sign-ins. Chat is also hidden while no chat site is enabled. A hidden Usage tab refreshes no usage, and the panel icon's tooltip shows only the name.")
            }
        }

        RowLayout {
            Kirigami.FormData.label: i18n("Size:")
            spacing: Kirigami.Units.smallSpacing

            QQC2.ComboBox {
                objectName: "popupSizeChoice"
                textRole: "text"
                valueRole: "value"
                model: page.sizeChoices
                currentIndex: page.choiceIndex(page.sizeChoices,
                    SettingsLogic.normalizePopupSize(page.cfg_popupSize), 1)
                onActivated: page.cfg_popupSize = currentValue
            }
            Kirigami.ContextualHelpButton {
                toolTipText: i18n("The popup never grows larger than the screen.")
            }
        }

        QQC2.CheckBox {
            objectName: "keepOpenChoice"
            text: i18n("Keep the popup open when clicking elsewhere")
            checked: page.cfg_chatKeepOpen
            onToggled: page.cfg_chatKeepOpen = checked
        }

        RowLayout {
            Kirigami.FormData.label: i18n("Keyboard shortcut opens:")
            spacing: Kirigami.Units.smallSpacing

            QQC2.ComboBox {
                objectName: "shortcutOpensChoice"
                textRole: "text"
                valueRole: "value"
                model: page.shortcutChoices
                currentIndex: page.choiceIndex(page.shortcutChoices,
                    SettingsLogic.normalizeShortcutTarget(page.cfg_shortcutOpens), 0)
                onActivated: page.cfg_shortcutOpens = currentValue
            }
            Kirigami.ContextualHelpButton {
                toolTipText: i18n("Choose the key in the Keyboard Shortcuts tab. Pressing it again closes the popup. Ollama message box opens the popup as usual while Ollama is off or the Chat tab is hidden; a hidden tab opens the other one.")
            }
        }

        RowLayout {
            Kirigami.FormData.label: i18n("Middle-click opens:")
            spacing: Kirigami.Units.smallSpacing

            QQC2.ComboBox {
                objectName: "middleClickChoice"
                textRole: "text"
                valueRole: "value"
                model: page.middleClickChoices
                currentIndex: page.choiceIndex(page.middleClickChoices,
                    SettingsLogic.normalizeMiddleClick(page.cfg_middleClickOpens, ChatSites.siteIds()), 0)
                onActivated: page.cfg_middleClickOpens = currentValue
            }
            Kirigami.ContextualHelpButton {
                toolTipText: i18n("A mouse action; the keyboard shortcut is in the Keyboard Shortcuts tab. A tab or site closes the popup if it is already showing it. While that tab is hidden or that site is off, the middle-click acts as a normal click.")
            }
        }

        // --- Usage ----------------------------------------------------------

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("Usage")
        }

        QQC2.ComboBox {
            Kirigami.FormData.label: i18n("Display:")
            enabled: page.cfg_showUsageTab
            model: [i18n("Left"), i18n("Used")]
            currentIndex: page.cfg_usageMode === "used" ? 1 : 0
            onActivated: page.cfg_usageMode = currentIndex === 1
                ? "used" : "remaining"
        }

        RowLayout {
            Kirigami.FormData.label: i18n("Refresh every:")
            spacing: Kirigami.Units.smallSpacing

            QQC2.ComboBox {
                enabled: page.cfg_showUsageTab
                textRole: "text"
                valueRole: "value"
                model: page.refreshChoices
                currentIndex: page.choiceIndex(page.refreshChoices, page.cfg_refreshInterval, 1)
                onActivated: page.cfg_refreshInterval = currentValue
            }
            Kirigami.ContextualHelpButton {
                toolTipText: i18n("Hearthwire starts with Plasma while this widget remains on a panel.")
            }
        }

        RowLayout {
            Kirigami.FormData.label: i18n("Notifications:")
            spacing: Kirigami.Units.smallSpacing

            QQC2.CheckBox {
                objectName: "alertLowChoice"
                enabled: page.cfg_showUsageTab
                text: i18n("Notify when a plan drops below")
                checked: page.cfg_alertLowEnabled
                onToggled: page.cfg_alertLowEnabled = checked
            }
            QQC2.ComboBox {
                objectName: "alertLowPercentChoice"
                enabled: page.cfg_showUsageTab && page.cfg_alertLowEnabled
                textRole: "text"
                valueRole: "value"
                model: page.alertChoices
                currentIndex: page.choiceIndex(page.alertChoices,
                    SettingsLogic.normalizeAlertPercent(page.cfg_alertLowPercent), 3)
                onActivated: page.cfg_alertLowPercent = currentValue
                Accessible.name: i18n("Percent left")
            }
            QQC2.Label {
                enabled: page.cfg_showUsageTab && page.cfg_alertLowEnabled
                text: i18n("left")
            }
            Kirigami.ContextualHelpButton {
                toolTipText: i18n("Shows one notification when a plan's usage left reaches this level, whether the popup shows Left or Used. It is checked at every usage refresh, only while the Usage tab is shown. A plan that is already this low when Plasma starts doesn't notify. Notifications can be muted under System Settings → Notifications → Hearthwire.")
            }
        }

        RowLayout {
            spacing: Kirigami.Units.smallSpacing

            QQC2.CheckBox {
                objectName: "alertResetChoice"
                enabled: page.cfg_showUsageTab
                text: i18n("Notify when a plan resets")
                checked: page.cfg_alertResetEnabled
                onToggled: page.cfg_alertResetEnabled = checked
            }
            Kirigami.ContextualHelpButton {
                toolTipText: i18n("Shows a notification when a plan that had dropped to the level above starts over with its next period. A notification names the provider, the plan and a percentage; Plasma may keep it in its notification history.")
            }
        }

        // --- Privacy --------------------------------------------------------

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("Privacy")
        }

        RowLayout {
            Kirigami.FormData.label: i18n("Usage history:")
            spacing: Kirigami.Units.smallSpacing

            QQC2.CheckBox {
                objectName: "usageHistoryChoice"
                text: i18n("Keep 7 days of usage for the Usage tab's graphs")
                checked: page.cfg_usageHistoryEnabled
                onToggled: page.cfg_usageHistoryEnabled = checked
            }
        }
        QQC2.Label {
            objectName: "usageHistoryExplanation"
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            opacity: 0.72
            text: i18n("Off by default. When on, the percent used of each reading is kept for 7 days, only on this computer, in the hearthwire/usage-history folder of your data folder (usually ~/.local/share). Each widget keeps its own history. It is saved at most every 15 minutes, keeping one value per hour. No names, plans, amounts or accounts are saved. Turning it off and applying deletes this widget's history; Delete usage history deletes it at once.")
            Layout.preferredWidth: page.wrappedTextWidth
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredWidth: page.wrappedTextWidth
            spacing: Kirigami.Units.smallSpacing

            QQC2.Button {
                objectName: "usageHistoryDelete"
                text: i18n("Delete usage history")
                icon.name: "edit-delete"
                enabled: page.historyClearState !== "busy"
                onClicked: page.clearHistory()
            }
            QQC2.Label {
                objectName: "usageHistoryStatus"
                Layout.fillWidth: true
                visible: text !== ""
                wrapMode: Text.WordWrap
                textFormat: Text.PlainText
                text: page.historyClearText(page.historyClearState)
            }
        }
        QQC2.Label {
            objectName: "usageHistoryOwedNotice"
            Layout.fillWidth: true
            visible: page.cfg_usageHistoryClearOwed && !page.cfg_usageHistoryEnabled
                && page.historyClearState !== "ok"
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            color: Kirigami.Theme.neutralTextColor
            text: i18n("The usage history hasn't been deleted yet. If this message stays, use Delete usage history.")
            Layout.preferredWidth: page.wrappedTextWidth
        }

        RowLayout {
            Kirigami.FormData.label: i18n("Stay signed in:")
            spacing: Kirigami.Units.smallSpacing

            QQC2.RadioButton {
                id: offChoice
                QQC2.ButtonGroup.group: signInGroup
                text: i18n("Off")
                onToggled: if (checked) page.chooseSignIn("memory")
            }
            Kirigami.ContextualHelpButton {
                toolTipText: i18n("Chat sites open in a private, in-memory browser profile. You are signed out on every Plasma restart; nothing is saved to disk. Clear chat data signs you out immediately.")
            }
        }
        RowLayout {
            spacing: Kirigami.Units.smallSpacing

            QQC2.RadioButton {
                id: encryptedChoice
                QQC2.ButtonGroup.group: signInGroup
                text: i18n("Encrypted")
                onToggled: if (checked) page.chooseSignIn("encrypted")
            }
            Kirigami.ContextualHelpButton {
                toolTipText: i18n("Sign-ins and site data, such as cached conversations, are kept in an encrypted folder made with gocryptfs. You enter its passphrase once per Plasma session in the Chat tab; until then you can use a private session. If you forget the passphrase, the saved data is lost: there is no recovery. While the folder is unlocked, programs running as you can read it. Clear chat data deletes the saved sign-ins and locks the folder.")
            }
        }

        RowLayout {
            Kirigami.FormData.label: i18n("Lock automatically:")
            spacing: Kirigami.Units.smallSpacing

            QQC2.ComboBox {
                id: autoLockChoice
                objectName: "autoLockChoice"
                // Only saved sign-ins can be locked.
                enabled: page.signInMode === "encrypted"
                textRole: "text"
                valueRole: "value"
                model: [
                    {value: 0, text: i18n("Never")},
                    {value: 1, text: i18n("1 minute")},
                    {value: 5, text: i18n("5 minutes")},
                    {value: 15, text: i18n("15 minutes")},
                    {value: 30, text: i18n("30 minutes")},
                    {value: 60, text: i18n("1 hour")},
                    {value: 480, text: i18n("8 hours")},
                    {value: 1440, text: i18n("24 hours")}
                ]
                currentIndex: Math.max(0, ChatStorage.AUTO_LOCK_MINUTES.indexOf(
                    ChatStorage.normalizeAutoLock(page.cfg_chatAutoLockMinutes)))
                onActivated: page.cfg_chatAutoLockMinutes = currentValue
            }
            Kirigami.ContextualHelpButton {
                toolTipText: i18n("Locks the encrypted folder once Chat hasn't been shown for this long, as if you pressed Lock. New sign-ins are saved within about 30 seconds, and at once when the folder is locked; if Plasma is stopped abruptly before that, you may have to sign in again.")
            }
        }

        RowLayout {
            Kirigami.FormData.label: i18n("Unlock with:")
            spacing: Kirigami.Units.smallSpacing

            QQC2.ComboBox {
                id: unlockChoice
                objectName: "unlockChoice"
                enabled: page.unlockChoiceEnabled
                textRole: "text"
                valueRole: "value"
                model: [
                    {value: "passphrase", text: i18n("Passphrase")},
                    {value: "wallet", text: i18n("KDE Wallet")}
                ]
                onActivated: page.chooseUnlock(currentValue)
            }
            QQC2.BusyIndicator {
                visible: page.vaultOp === "add-key" || page.vaultOp === "remove-key"
                running: visible
                Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                Layout.preferredWidth: Kirigami.Units.iconSizes.medium
            }
            Kirigami.ContextualHelpButton {
                toolTipText: i18n("KDE Wallet: a random key for the encrypted folder is kept in your wallet, so the folder opens without typing the passphrase: at Plasma start when the wallet is already open, else with one click (KDE Wallet may ask for its own password). Anyone who can use your open wallet can open the folder too. The passphrase keeps working and is always offered. Setting it up asks for the passphrase once. Choosing Passphrase again removes the key from the wallet. Needs an encrypted folder and KDE Wallet turned on.")
            }
        }

        Kirigami.InlineMessage {
            objectName: "walletNotApplied"
            Layout.fillWidth: true
            visible: page.walletNotApplied && !page.confirmingWalletOff
            type: Kirigami.MessageType.Information
            text: i18n("A KDE Wallet key is set up but not applied. Apply to use it, or remove the key.")
            actions: [
                // Chooses KDE Wallet again; Apply then uses it.
                Kirigami.Action {
                    text: i18n("Use KDE Wallet")
                    icon.name: "dialog-ok-apply"
                    onTriggered: page.useWalletSlot()
                },
                Kirigami.Action {
                    text: i18n("Remove key")
                    icon.name: "edit-delete"
                    enabled: page.vaultOp === ""
                    onTriggered: page.confirmingWalletOff = true
                }
            ]
        }

        Kirigami.InlineMessage {
            objectName: "walletOffConfirm"
            Layout.fillWidth: true
            visible: page.confirmingWalletOff
            type: Kirigami.MessageType.Warning
            text: i18n("Stop unlocking with KDE Wallet? Its key is removed from the wallet now; the passphrase unlocks the folder.")
            actions: [
                Kirigami.Action {
                    text: i18n("Remove key")
                    icon.name: "edit-delete"
                    onTriggered: {
                        page.confirmingWalletOff = false
                        page.runVault("remove-key", "wallet")
                    }
                },
                Kirigami.Action {
                    text: i18n("Cancel")
                    icon.name: "dialog-cancel"
                    onTriggered: page.confirmingWalletOff = false
                }
            ]
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.preferredWidth: page.wrappedTextWidth
            visible: page.signInMode === "encrypted" && page.walletMissing.length > 0
            spacing: Kirigami.Units.smallSpacing

            QQC2.Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: ChatStorage.hasInstallCommand(page.installDistro)
                    ? i18n("Unlocking with KDE Wallet needs tools that aren't installed. Install them with:")
                    : i18n("Unlocking with KDE Wallet needs tools that aren't installed. Install the packages that provide them with your distribution's package manager:")
            }
            QQC2.TextField {
                Layout.fillWidth: true
                readOnly: true
                selectByMouse: true
                objectName: "walletInstallCommand"
                text: ChatStorage.installCommand(page.walletMissing, page.installDistro)
            }
        }

        QQC2.Label {
            Layout.fillWidth: true
            // The folder actions' own label shows it while they are open.
            visible: !page.showFolderActions && page.vaultMessage !== ""
            wrapMode: Text.WordWrap
            color: page.vaultMessage === "wallet-on" || page.vaultMessage === "wallet-off"
                ? Kirigami.Theme.positiveTextColor : Kirigami.Theme.negativeTextColor
            text: page.vaultText(page.vaultMessage)
            Layout.preferredWidth: page.wrappedTextWidth
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.preferredWidth: page.wrappedTextWidth
            visible: page.vaultState === "unavailable"
            spacing: Kirigami.Units.smallSpacing

            QQC2.Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: ChatStorage.hasInstallCommand(page.installDistro)
                    ? i18n("This needs gocryptfs, which isn't installed. Install it with:")
                    : i18n("This needs gocryptfs, which isn't installed. Install it with your distribution's package manager:")
            }
            QQC2.TextField {
                Layout.fillWidth: true
                readOnly: true
                selectByMouse: true
                objectName: "vaultInstallCommand"
                text: ChatStorage.installCommand(page.vaultMissing, page.installDistro)
            }
        }

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: page.confirmingOff
            type: Kirigami.MessageType.Warning
            text: i18n("Turn off Stay signed in? When you apply this, the encrypted folder and every sign-in saved in it are deleted, for all Hearthwire widgets. This can't be undone.")
            actions: [
                Kirigami.Action {
                    text: i18n("Turn off and delete")
                    icon.name: "edit-delete"
                    onTriggered: {
                        page.confirmingOff = false
                        page.cfg_chatSignInStorage = "memory"
                    }
                },
                Kirigami.Action {
                    text: i18n("Cancel")
                    icon.name: "dialog-cancel"
                    onTriggered: {
                        page.confirmingOff = false
                        page.syncSignInChoice()
                    }
                }
            ]
        }

        QQC2.CheckBox {
            Kirigami.FormData.label: i18n("Encrypted folder:")
            text: i18n("Show folder actions")
            checked: page.showFolderActions
            onToggled: page.showFolderActions = checked
        }

        QQC2.Label {
            Layout.fillWidth: true
            visible: page.showFolderActions
            wrapMode: Text.WordWrap
            text: page.vaultStateText()
            Layout.preferredWidth: page.wrappedTextWidth
        }

        RowLayout {
            visible: page.showFolderActions
            spacing: Kirigami.Units.smallSpacing

            QQC2.Button {
                text: i18n("Change passphrase…")
                icon.name: "document-edit"
                enabled: page.vaultState === "locked" && page.vaultOp === ""
                onClicked: page.runVault("change-passphrase")
            }
            QQC2.Button {
                text: i18n("Delete encrypted folder…")
                icon.name: "edit-delete"
                enabled: (page.vaultState === "locked" || page.vaultState === "damaged")
                    && page.vaultOp === ""
                onClicked: page.confirmingDelete = true
            }
            QQC2.BusyIndicator {
                visible: page.vaultOp !== ""
                running: visible
                Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                Layout.preferredWidth: Kirigami.Units.iconSizes.medium
            }
        }

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: page.showFolderActions && page.confirmingDelete
            type: Kirigami.MessageType.Warning
            text: i18n("Delete the encrypted folder? Every sign-in saved in it is lost, for all Hearthwire widgets. This can't be undone.")
            actions: [
                Kirigami.Action {
                    text: i18n("Delete")
                    icon.name: "edit-delete"
                    onTriggered: page.runVault("destroy")
                },
                Kirigami.Action {
                    text: i18n("Cancel")
                    icon.name: "dialog-cancel"
                    onTriggered: page.confirmingDelete = false
                }
            ]
        }

        QQC2.Label {
            Layout.fillWidth: true
            visible: page.showFolderActions && page.vaultMessage !== ""
            wrapMode: Text.WordWrap
            color: page.vaultMessage === "changed" || page.vaultMessage === "deleted"
                ? Kirigami.Theme.positiveTextColor : Kirigami.Theme.negativeTextColor
            text: page.vaultText(page.vaultMessage)
            Layout.preferredWidth: page.wrappedTextWidth
        }

        // --- Backup ---------------------------------------------------------

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("Backup")
        }

        QQC2.Label {
            objectName: "backupStatus"
            Kirigami.FormData.label: i18n("Settings backup:")
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            text: page.backupStatusText()
            Layout.preferredWidth: page.wrappedTextWidth
        }
        QQC2.Label {
            objectName: "backupExplanation"
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            opacity: 0.72
            text: i18n("One file on this computer, in the hearthwire folder of your configuration folder (usually ~/.config). It holds these settings, including your custom chat addresses. Sign-ins, the encrypted folder, zoom and the usage history setting are not part of it. Export saves the applied settings: press Apply first, because changes not yet applied on any page are not exported.")
            Layout.preferredWidth: page.wrappedTextWidth
        }
        RowLayout {
            spacing: Kirigami.Units.smallSpacing

            QQC2.Button {
                objectName: "backupExport"
                text: i18n("Export")
                icon.name: "document-export"
                enabled: page.backupOp === ""
                onClicked: page.requestExport()
            }
            QQC2.Button {
                objectName: "backupImport"
                text: i18n("Import")
                icon.name: "document-import"
                enabled: page.backupOp === ""
                onClicked: page.requestImport()
            }
            QQC2.BusyIndicator {
                visible: page.backupOp !== ""
                running: visible
                Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                Layout.preferredWidth: Kirigami.Units.iconSizes.medium
            }
        }

        Kirigami.InlineMessage {
            objectName: "backupExportConfirm"
            Layout.fillWidth: true
            visible: page.confirmingExport
            type: Kirigami.MessageType.Warning
            text: i18n("Replace the existing backup with the applied settings? Changes not yet applied are not exported.")
            actions: [
                Kirigami.Action {
                    text: i18n("Replace")
                    icon.name: "document-export"
                    onTriggered: page.exportBackup()
                },
                Kirigami.Action {
                    text: i18n("Cancel")
                    icon.name: "dialog-cancel"
                    onTriggered: page.confirmingExport = false
                }
            ]
        }

        Kirigami.InlineMessage {
            objectName: "backupImportConfirm"
            Layout.fillWidth: true
            visible: page.confirmingImport
            type: Kirigami.MessageType.Warning
            text: i18n("Replace the settings on these pages with the backup? Nothing is saved until you press Apply.")
            actions: [
                Kirigami.Action {
                    text: i18n("Replace")
                    icon.name: "document-import"
                    onTriggered: page.applyBackup()
                },
                Kirigami.Action {
                    text: i18n("Cancel")
                    icon.name: "dialog-cancel"
                    onTriggered: {
                        page.confirmingImport = false
                        page.backupPlan = null
                        page.backupAddressChanges = []
                    }
                }
            ]
        }

        QQC2.Label {
            objectName: "backupPlanLabel"
            Layout.fillWidth: true
            visible: page.confirmingImport
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            text: i18n("Settings to apply: %1. Saved: %2.",
                page.backupPlan ? page.backupPlan.applied : 0, SettingsBackup.shownStamp(page.backupExportedAt))
            Layout.preferredWidth: page.wrappedTextWidth
        }

        // Plain text only: an address is shown, never opened.
        QQC2.Label {
            objectName: "backupAddressChanges"
            Layout.fillWidth: true
            visible: page.confirmingImport && text !== ""
            wrapMode: Text.Wrap
            textFormat: Text.PlainText
            text: page.addressChangeText(page.backupAddressChanges)
            Layout.preferredWidth: page.wrappedTextWidth
        }

        QQC2.Label {
            objectName: "backupMessage"
            Layout.fillWidth: true
            visible: text !== ""
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            text: page.backupText(page.backupMessage)
            Layout.preferredWidth: page.wrappedTextWidth
        }

        QQC2.Label {
            objectName: "backupDroppedCount"
            Layout.fillWidth: true
            visible: page.backupDropped > 0
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            text: i18n("Settings left out: %1", page.backupDropped)
            Layout.preferredWidth: page.wrappedTextWidth
        }
    }
}
