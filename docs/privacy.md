# Privacy

Hearthwire reads existing local sign-in state only for providers the user tracks
and that are detected as installed. Credentials are sent only to the matching
provider's first-party OAuth and usage endpoints. The helper never follows
HTTP redirects: a 3xx from a provider is reported as a failed request
(`invalid-response`), so a token is never sent on to the redirect's address.
The widget always starts the helper as `python3 -P -m hearthwire`, so
Python doesn't load modules from Plasma's working folder.

The helper does not print or log access tokens, refresh tokens, API keys,
credential fingerprints, or raw provider responses. Its JSON output contains
only display metadata, quota percentages, billing summaries, plan names, and
timestamps.

Provider names, plan names, captions, error messages and billing amounts in
the Usage tab, the panel tooltip and the settings page are shown as plain
text only. Text such as `<img src="...">` in a provider's reply appears
literally and can't make the widget load an image or a link.

Usage snapshots, stale readings, and rate-limit cooldowns live only in the
Plasma widget process. They disappear when Plasma restarts. Hearthwire does not
read local chat transcripts. The widget keeps no usage history unless you turn
on **Usage history** (off by default; see [Usage history](#usage-history)).

Usage notifications (**Settings → General → Usage → Notifications**, off by
default) are sent to Plasma's notification server through KDE's notification
library as the `hearthwire` application. Each one names a provider, a plan
(for example "Claude Code" and "Weekly") and a whole percentage left, nothing
else: no account, plan name from the provider, error text or link, and no
buttons. Plasma may keep it in its notification history like any other
notification. They can be muted or changed under **System Settings →
Notifications → Hearthwire**, which saves that choice in
`~/.config/hearthwire.notifyrc`. Which plans already notified is kept only
in the widget's memory, so after a Plasma restart the first reading counts
as a starting point again and never notifies. `scripts/install.sh` installs
`hearthwire.notifyrc` to `${XDG_DATA_HOME:-~/.local/share}/knotifications6/`
so the two events appear in System Settings; it holds names and settings
only.

The usage settings are stored like every other widget setting: in plain
text in `~/.config/plasma-org.kde.plasma.desktop-appletsrc`, which is often
readable by other users (mode `0644`). They hold provider and reading ids
from the built-in catalog, choices and percentages only; never a credential,
an account, a plan name, a reading or an error from a provider.

| Setting | Where it is set | What it contains |
| --- | --- | --- |
| `trackedProviders` | AI Provider Settings → Track | The tracked provider ids, for example `["claude","codex"]` |
| `providerMetrics` | AI Provider Settings → reading boxes | The readings the Usage tab shows per provider, for example `{"claude":["session","weekly"]}`; a provider left out (the default, `{}`) shows all its readings |
| `providerOrder` | AI Provider Settings → Move up / Move down | The provider order, for example `["codex","claude"]`; empty (the default) is the built-in order |
| `usageCompact` | AI Provider Settings → Layout: Compact | `true` or `false` (the default) |
| `usageWarnPercent`, `usageCriticalPercent` | AI Provider Settings → Warning / Critical color from | Percent used in steps of 5: warning 50 to 90 (60 by default), critical 55 to 95 (85 by default); the page shows them as left or used, like General → Display |
| `usageNormalColor`, `usageWarnColor`, `usageCriticalColor` | AI Provider Settings → the color boxes | A color such as `#e07b1a`, or empty (the default) for the default color (an empty Critical box uses a custom Warning color if there is one); anything else is read as empty |
| `configSchemaVersion` | Written by the widget | The settings format, now `3`; it makes the upgrade step above run once |
| `tooltipShowsUsage` | AI Provider Settings → Hover popup | `true` (the default) or `false`. (An older `tooltipShowsReset` entry is no longer read.) |
| `tooltipMetrics` | AI Provider Settings → Hover popup → Readings | The hover popup's own readings, for example `{"claude":["session","weekly"]}`, or empty (the default) for Same as the Usage tab. On the first start after the upgrade that made the reading boxes filter the Usage tab, a saved `providerMetrics` choice moves here (unless this already had one), and `providerMetrics` becomes `{}` |
| `usageMode` | General → Display, or the popup's Left / Used | `remaining` (the default) or `used` |
| `refreshInterval` | General → Refresh every | Seconds: 60, 300 (the default), 900, 1800 or 3600 |
| `alertLowEnabled`, `alertLowPercent`, `alertResetEnabled` | General → Notifications | On/off and a percentage left (20 by default) |
| `panelRing` | AI Provider Settings → Hover popup → Usage ring | `auto` (the default), `off`, or a catalog provider and reading id such as `claude.weekly` (never `extra_usage`); anything else is read as `auto` |
| `middleClickOpens` | General → Popup → Middle-click opens | `refresh` (the default), `usage`, `ollama`, or a web chat site id such as `claude`; anything else is read as `refresh` |
| `usageHistoryEnabled` | General → Privacy → Usage history | `true` or `false` (the default) |
| `usageHistoryClearOwed` | Written by the widget | `true` while turning Usage history off still has to delete the stored history, else `false` (the default) |

Antigravity is the one provider that requires a derived access-token cache
because its Secret Service entry can contain only a refresh token. That cache
is written to `$XDG_CACHE_HOME/hearthwire/antigravity-auth.json` (falling back
to `~/.cache`) with mode `0600`. It contains a short-lived access token, expiry,
and a SHA-256 refresh-token fingerprint. It never contains the refresh token.
When upgrading from the previous release, `scripts/install.sh` deletes the old
cache files in `$XDG_CACHE_HOME/ai-usage-kde/`; a manual `pip` install leaves them in
place until you remove that directory yourself.

When a credential file is a symlink, refreshed credentials are written to the
file it points to with mode `0600`, and only if that file already exists, is a
regular file, and is owned by the current user.

To keep two helper runs from refreshing the same token, the helper creates
empty lock files named `<provider>.lock` in `$XDG_RUNTIME_DIR/hearthwire/`
(falling back to `<temp dir>/hearthwire-<uid>/`). The directory is mode
`0700` and each file is mode `0600`. The files hold no data; only their
advisory lock is used.

To find CLIs and profile directories, the helper may start the user's login
shell once per run. That shell prints only the allow-listed variables
`CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `XDG_CACHE_HOME`, `XDG_CONFIG_HOME`,
`XDG_DATA_HOME`, and `PATH`. The values stay in memory and are never cached to
disk.

Hearthwire makes no network requests other than to the tracked providers'
endpoints and the chat websites you open, plus whatever those sites load, and,
if you use the built-in Ollama chat, requests over loopback to the Ollama
server on this computer. No analytics or telemetry are collected.

The project's `.claude/` folder (local development notes and settings) is never
part of the repository or of the packages.

## Usage history

**Usage history** (Settings → General → Privacy) is off by default. Nothing
is recorded and no file is made until you turn it on and apply.

What is stored, while it is on:

- For each hour, the percent used (a whole number from 0 to 100) of each
  reading of each tracked provider, by its catalog ids, for example
  `claude` and `weekly`. All of a provider's readings are recorded, not only
  the ones the Usage tab shows. Extra usage (money) is never recorded.
- The time is the start of the hour (UTC). There is one value per hour; a
  later reading in the same hour replaces it.
- Nothing else: no account, plan name, amount, caption, error or reset time
  from a provider.
- Only fresh readings count: a provider that failed, or shows an older
  reading kept from before an error, is left out. The widget records after a
  successful refresh, at most once every 15 minutes, and only while the Usage
  tab is shown in settings.

Where and how:

- `$XDG_DATA_HOME/hearthwire/usage-history/` (usually
  `~/.local/share/hearthwire/usage-history/`), with `history.json` (the data)
  and `history.lock` (empty; only its lock is used).
- The folders are mode `0700` and the files mode `0600`, so only you can read
  them. Symlinks and other users' files are refused. The file is replaced
  atomically and is never larger than 256 KiB.
- The helper writes it (`--usage-history`; see
  [Provider contracts](provider-contracts.md#usage-history-helper)). The
  widget passes the sample in the helper's process arguments, for example
  `claude.weekly=38`, so for a moment other local users can see those
  percentages in the process list, unless `/proc` is mounted with `hidepid`
  (see [Recommended system settings](#recommended-system-settings)).
- It is one folder for your account, shared by every Hearthwire widget.
  The widget keeps its own copy of what the helper last returned in Plasma's
  memory, only while history is on.

How long: each write drops everything older than 7 days (the current hour and
the 168 before it).

How to delete it:

- Turn **Usage history** off and apply: the widget forgets what it showed and
  deletes the whole `usage-history` folder. With several Hearthwire widgets,
  this deletes it for all of them.
- **Delete usage history** (next to the setting) deletes it at once and leaves
  the setting as it is. While history stays on, recording starts again at the
  next refresh.
- `scripts/install.sh --uninstall-web-data` deletes it too, after the chat
  sign-in data. If it can't, it says so and asks you to delete the folder by
  hand. It doesn't change the setting: a widget that still has history on
  starts recording again.
- Removing the widget from the panel does not delete it.

If a delete fails: when the helper is busy the widget tries again up to three
times, three seconds apart. If it still fails, the Usage tab says "The usage
history couldn't be deleted. Use Delete usage history in Settings → General →
Privacy." The widget remembers that a delete is owed
(`usageHistoryClearOwed`) and tries again at the next Plasma start and each
time the popup opens; until a delete succeeds the Privacy section says "The
usage history hasn't been deleted yet." Turning history on again cancels the
owed delete and keeps the existing file. A delete removes the files normally;
on copy-on-write file systems and SSDs old blocks may stay on the disk for a
while.

## Settings backup

**Export** and **Import** (Settings → General → Backup) use one fixed file;
there is no file dialog.

- Where: `$XDG_CONFIG_HOME/hearthwire/settings-backup.json` (usually
  `~/.config/hearthwire/settings-backup.json`). The folder is mode `0700`
  (made, or tightened, by Export) and the file mode `0600`, so only you can
  read it. It is replaced atomically. A symlink, another user's file, or a
  folder or file other users may write to is refused and left alone.
- What is in it: a format name, a version, the settings format (`3`), the
  time of the export (UTC), and these settings: `trackedProviders`,
  `providerMetrics`, `providerOrder`, `usageMode`, `refreshInterval`,
  `tooltipShowsUsage`, `tooltipMetrics`, `usageCompact`, `usageWarnPercent`,
  `usageCriticalPercent`, `usageNormalColor`, `usageWarnColor`,
  `usageCriticalColor`, `alertLowEnabled`, `alertResetEnabled`,
  `alertLowPercent`, `chatSites`, `chatDefaultSite`, `chatOllamaUrl`,
  `chatKeepOpen`, `showUsageTab`, `showChatTab`, `popupDefaultTab`,
  `popupSize`, `shortcutOpens`, `panelRing`, `middleClickOpens` and
  `chatCustomUrls`. So it names the providers and chat sites you use and
  holds your custom chat addresses in plain text, like the Plasma
  configuration file does.
- What is never in it: sign-ins, cookies, passphrases, the KDE Wallet key,
  prompts, personalities, chat text or model names; and the settings
  `chatSignInStorage`, `chatProfileGeneration`, `chatAutoLockMinutes`,
  `chatVaultUnlock`, `chatSiteZoom`, `configSchemaVersion`,
  `initialSetupComplete`, `usageHistoryEnabled` and `usageHistoryClearOwed`.
  An import never turns on Usage history or Stay signed in.
- Export takes the settings as they are now, including changes on the
  General page not yet applied. It asks before it replaces an existing
  backup, and never replaces one with an empty one. The settings go to the
  helper as hexadecimal digits in its process arguments, which anyone can
  decode: for a moment other local users can see them in the process list,
  unless `/proc` is mounted with `hidepid`. That is the same information the
  Plasma configuration file (often mode `0644`) already shows them.
- Import reads the file; the helper and then the widget check every value,
  and a value the widget would not store is left out ("Settings left out:
  N"). After **Replace** the values fill in the settings pages; nothing is
  saved until you press **Apply** on the General page.
- The file stays until you delete it. `scripts/install.sh
  --uninstall-web-data` leaves it in place, and so does removing the widget.

## Chat tab

The Chat tab shows a provider's own website (Claude, ChatGPT, Grok, Gemini,
GitHub Copilot, or Microsoft Copilot), or a chat web interface on your own
computer (Local web UI, for example Open WebUI on top of Ollama), in Qt
WebEngine inside the Plasma process. You sign in on each site as you would in
a browser. The built-in Ollama chat is different: it is not a web page and
does not use Qt WebEngine (see [Ollama](#ollama-built-in-chat) below).

Google's sign-in page (accounts.google.com) refuses embedded browsers
("This browser or app may not be secure"). While a chat page or sign-in
window is on that page, Hearthwire identifies itself as Firefox on Linux and
sends no browser brand in its client hints, so Google allows the sign-in;
everywhere else it reports its real Chromium-based engine. Google may change
this check at any time, and sign-in with Google could stop working.

**Stay signed in** (Settings → General → Privacy) has two choices:

- **Off** (the default): everything you enter (accounts, passwords, prompts,
  uploaded files, cookies) stays in Plasma's memory and is gone when Plasma
  restarts or you choose **Clear chat data**. Nothing is written to disk.
- **Encrypted**: sign-ins and site data are kept in a passphrase-protected
  folder made with gocryptfs, so you stay signed in across Plasma restarts.

**Split view** (the Chat toolbar's Split button, not saved in the settings)
shows a second site in a second page of the same profile: same sign-ins,
same rules (Off or Encrypted, permissions, external-link prompts, sign-in
windows over the pane that opened them, plain-text notices), and Hearthwire
never scripts either page. The notices and toolbar act on the pane you last
clicked into. Two sites use about twice the memory of one (each page has
its own web engine process); turning Split off closes the second page. When
the popup is too narrow for two pages, only the first is shown: the second
page (and a sign-in window it opened) stays open but hidden, like a site you
switched away from, until the popup is wide enough again or Split is turned
off. A download prompt names the site whose page asked.

There is no plain "save to disk" choice. Qt WebEngine never encrypts cookies
or site storage itself (it does not use KDE Wallet for them), so a saved
sign-in would sit on disk as readable text. Hearthwire therefore saves
sign-ins only inside the encrypted folder.

### Off: private in-memory profile

All chat pages, including sign-in windows, share one off-the-record Qt
WebEngine profile with an in-memory HTTP cache and no persistent cookies.
Qt WebEngine creates no profile directory for it. Cookies, sessions, local
storage, IndexedDB, service workers, history, and favicons exist only in
memory. Spell checking is off. You are signed out on every Plasma restart.

**Clear chat data** (in the Chat tab, after a confirmation) destroys every
chat page together with the profile, which signs you out of all chat sites at
once. Chat is the first tab, so Qt WebEngine starts the first time you open
the popup on a web site; it doesn't start while no web chat sites are enabled
or while only the Ollama chat is shown, and it is never started just because
the widget is on the panel.

### Encrypted: saved sign-ins

Turning on **Encrypted** installs nothing and asks for nothing by itself. The
Chat tab shows a card instead: **Create encrypted folder…** the first time,
**Unlock…** after that. Each card also offers **Use a private session this
time**, which opens the sites in the Off profile above. If gocryptfs is not
installed, the card shows the install command; until then you can use a
private session.

How it works:

- The encrypted files are in `$XDG_DATA_HOME/hearthwire/vault/` (usually
  `~/.local/share/hearthwire/vault/`). While unlocked, gocryptfs shows their
  readable view at `$XDG_RUNTIME_DIR/hearthwire/vault/` (usually
  `/run/user/<uid>/hearthwire/vault/`), which lives in memory. Each widget
  keeps its profile in its own subfolder there.
- What is encrypted: cookies, local storage, IndexedDB, session storage and
  every other file the sites write, including the file names. The HTTP cache
  stays in memory.
- What is not encrypted: metadata such as the number of files, their
  approximate sizes, timestamps, and the folder layout. gocryptfs detects a
  changed file, but not an older copy of the whole folder put back in its
  place (no rollback protection).
- The folder is mounted only for you (no `allow_other`). Before using it, the
  helper checks that it looks like your gocryptfs mount of your encrypted
  folder; if not, the Chat tab falls back to the card and saves nothing. This
  check guards against mistakes and against other users. It does not protect
  against programs running as you: those can already read your files, and
  could mount a look-alike FUSE folder that passes the same check.
- One encrypted folder with one passphrase is shared by all Hearthwire widgets
  on your account. Unlocking it in one widget unlocks it for all of them.

Your passphrase:

- You type it only into a KDE dialog (kdialog) that gocryptfs itself starts;
  kdialog hands it straight to gocryptfs. It never passes through Hearthwire
  and is never in process arguments, environment variables, logs, or the
  widget's configuration.
- Creating the folder asks twice: once to choose the passphrase, then once
  more to unlock it. Hearthwire cannot enforce a strong passphrase; the
  dialog shows a strength meter.
- There is no recovery key. If you forget the passphrase, the saved sign-ins
  are lost: delete the folder and start again.
- **Change passphrase…** and **Delete encrypted folder…** are under Settings →
  General → Privacy → Show folder actions, and work only while the folder is
  locked.

The folder stays unlocked until you press the lock button (**Lock saved
sign-ins**) in the Chat tab, it is locked automatically (below), you choose
**Clear chat data**, turn Stay signed in Off, Plasma restarts, you log out, or
the computer restarts. Lock closes the chat pages first, then
locks the folder; if another Hearthwire widget is still using it, the folder
is not locked and the Chat tab says so. It is never forced.

**Lock automatically** (Settings → General → Privacy; only with
Encrypted) locks the folder after Never (the default), 1, 5, 15 or 30 minutes,
1, 8 or 24 hours of not using Chat. Not using means the Chat tab with a chat
site hasn't been shown: the popup is closed, or Usage or Ollama is shown.
Every time Chat is shown again the time starts over, and it never locks while
Chat is shown. It counts clock time, so time the computer was asleep counts
too. It works like the lock button, but it waits while a passphrase window or
another folder step is running, and if another Hearthwire widget is using the
folder it quietly keeps it open and tries again after the next idle period.
Afterwards the Chat tab says "Locked automatically".

When your sign-ins reach the folder: the web engine writes new cookies to disk
about 30 seconds after a site sets them (site storage after about 5 seconds),
and everything at once when the chat pages close: on Lock, Lock automatically,
Clear chat data, or when Plasma quits normally. If Plasma is stopped abruptly
(a crash, or killed) within those seconds after you signed in, that newest
sign-in is lost and you sign in again. To be sure, lock the folder or wait half
a minute after signing in before restarting Plasma or logging out.

**Clear chat data** in Encrypted mode signs you out of all chat sites,
deletes this widget's saved sign-ins inside the folder, and locks the folder.

Turning Stay signed in **Off** (after a confirmation in settings) deletes the
whole encrypted folder, with every sign-in saved in it, for all Hearthwire
widgets. If another widget still has it open, it is not deleted and the Chat
tab tells you; delete it later under Settings → General → Privacy → Show
folder actions.

Hiding the Chat tab (Settings → General → Show tabs) closes the chat pages
and, if saved sign-ins are open, locks the folder as the lock button does.
While Chat is hidden no chat page, web engine or Ollama chat starts.

#### Unlock with KDE Wallet

Settings → General → Privacy → **Unlock with** chooses **Passphrase** (the
default) or **KDE Wallet**. Choosing KDE Wallet sets it up at once: the helper
makes a second key slot (a copy of the folder's `gocryptfs.conf`, in
`~/.local/share/hearthwire/vault-keys/wallet.conf`) that opens with a random
256-bit key, stores that key in your KDE Wallet (folder `Hearthwire`, entry
`encrypted-chat-folder`), and asks for the passphrase once to do it. The key
moves only between KDE's and gocryptfs's own programs through pipes; it never
passes through Hearthwire, process arguments, the environment, logs or the
widget's configuration (only the word `wallet` is saved, as
`chatVaultUnlock`).

- At Plasma start, if the wallet is already open, the folder is unlocked
  silently. If the wallet is closed nothing is asked; the Chat tab shows the
  locked card, whose **Unlock with KDE Wallet** may show KDE Wallet's own
  password window. After Lock or Lock automatically it takes that one click
  again; it never re-opens by itself.
- The locked card always offers **Use passphrase instead…**: the passphrase
  slot is never changed and stays the way back in. If the wallet's key no
  longer fits (for example after the folder was re-created), the card offers
  **Set up KDE Wallet again…**. Setting it up again first stages the new key
  (wallet entry `encrypted-chat-folder.new`) and a new slot, and swaps them in
  only once gocryptfs accepted your passphrase; if you cancel or it fails, the
  slot and wallet key you had keep working, and the staged ones are removed.
- Choosing **Passphrase** again removes the wallet's key slot and its wallet
  entry (after a confirmation). Deleting the folder, turning Stay signed in
  Off, and `scripts/install.sh --uninstall-web-data` remove both too.
- **Change passphrase…** changes only the passphrase slot; the wallet slot
  keeps working.

| | Passphrase | KDE Wallet |
| --- | --- | --- |
| What opens the folder | The passphrase you type | The key in your KDE Wallet, so whatever opens the wallet (usually your login password) |
| While it is open | Programs running as you can read the folder | Same, and they can also read the key from the open wallet: KDE Wallet trusts every program's own claim of who it is |
| At Plasma start | Locked until you unlock | Unlocked if the wallet is open; with autologin, or a wallet password different from your login password, the wallet usually starts closed |
| Stolen, powered-off computer | Protected by the passphrase | Protected by the wallet's password; the weakest slot wins |

A key slot is a file: an old copy of `wallet.conf` in a backup still opens the
folder with the wallet key that was valid then, even after you removed it
here.

#### Prompt library

The **Prompts** button in the Chat toolbar opens your saved prompts and
personalities. They are saved only inside the unlocked encrypted folder, in
`library/` (one text file per item and `personas.json`, which maps model names
to a saved personality), so they exist only with Stay signed in → Encrypted.
Otherwise, or while the folder is locked, prompts and personalities you add
are kept in Plasma's memory for this session only. Nothing of them is ever in
the widget's configuration (that file is readable by other users here).

- New and replaced items are typed into a KDE text window (kdialog) that the
  helper starts; kdialog writes the text straight into the folder, and it
  never passes through process arguments.
- To show them, the helper reads the files and hands the text to the widget
  (`--prompts list`): this is the one place where your text passes through the
  helper process, in memory only, never to disk or logs. The widget keeps
  that copy in Plasma's memory and drops it as soon as the folder is locked.
- With Ollama, a prompt is put into the message box (nothing is sent until
  Send), and a saved personality can be made a model's default. On a web site
  a click copies the prompt to the clipboard ("Copied — paste with Ctrl+V");
  the page is never scripted. A clipboard manager such as Klipper may keep
  what you copy (see below).

Small files in `$XDG_RUNTIME_DIR/hearthwire/` (in memory, mode `0600`):
`vault.lock`, an empty lock file, and briefly `passwd.status`, which holds only
the exit status of the first passphrase dialog while you change the
passphrase.

What Encrypted mode does not protect against:

- While the folder is unlocked, any program running as you, and root, can
  read your saved sign-ins, just like the Plasma memory in Off mode.
  Keyloggers can capture the passphrase as you type it.
- A program running as you could show a fake passphrase window. Only type the
  passphrase right after you clicked Create, Unlock, or Change passphrase.
- Hibernation can write the folder's key, which is in memory while unlocked,
  to disk. Lock the folder before hibernating, or use encrypted swap.
- If gocryptfs is killed while a site is writing (for example when Plasma
  crashes), saved sign-ins can be damaged. This fails safe: you are signed
  out and sign in again. The helper cleans up the dead mount the next time the
  Chat tab checks the folder.
- Deleting the folder (Clear, turning Off, Delete encrypted folder, or
  `scripts/install.sh --uninstall-web-data`) removes the files normally. On
  btrfs or other copy-on-write file systems, and on SSDs (TRIM), old blocks
  may stay on the disk for a while; this is not a secure erase. They hold only
  encrypted data, so the risk is low.

### What is stored where

| Data | Off | Encrypted |
| --- | --- | --- |
| Cookies, sessions, site storage | Memory only; dropped on Clear chat data or Plasma restart | Encrypted folder; deleted on Clear chat data (this widget) or when you turn it Off (all widgets) |
| HTTP cache | Memory only | Memory only |
| Page titles, addresses, history, icons | Memory only; the widget never shows, stores, or logs them | Same; Qt WebEngine's own history files, if any, are inside the encrypted folder |
| Passphrase | Not used | Never stored; typed into kdialog, read by gocryptfs |
| Passwords and form autofill | Not supported by Qt WebEngine; nothing is saved | Same |
| Widget settings | The enabled sites (`chatSites`), the first site (`chatDefaultSite`), any custom addresses you enter (`chatCustomUrls`), the Stay signed in choice (`chatSignInStorage`), a profile counter (`chatProfileGeneration`), the Ollama address (`chatOllamaUrl`), the zoom of each site and of the Ollama chat, set with the zoom keys or Ctrl+scroll (`chatSiteZoom`, for example `{"claude":1.25}`; sites at 100% are left out), the General page's popup choices (`popupDefaultTab`, `showUsageTab`, `showChatTab`, `popupSize`, `chatKeepOpen`, `chatAutoLockMinutes`, `shortcutOpens`, `middleClickOpens`, and
`chatVaultUnlock`, Passphrase or KDE Wallet), and the usage settings in the table near the top of this page, in plain text in `~/.config/plasma-org.kde.plasma.desktop-appletsrc`; never the last page you visited, a passphrase, a path, a model name, or anything you typed into a chat | Same |
| Ollama conversation | Plasma memory only (and the Ollama server, see below); dropped on Clear conversation, when you turn Ollama off in settings, or on Plasma restart; kept while the popup is closed or another site is shown | Same; never in the encrypted folder |
| Prompt library | This session's prompts and personalities in Plasma memory only | Saved in the encrypted folder (`library/`); in Plasma memory only while unlocked; never in the configuration |
| KDE Wallet key | Not used | With Unlock with KDE Wallet: a random key in your KDE Wallet and a key slot file `vault-keys/wallet.conf` next to the encrypted folder |
| Ollama address | `chatOllamaUrl` in the Plasma configuration file, plain text; only a loopback `http://` address with a port is ever saved | Same |
| Downloads | Only files you approve, saved to your Downloads folder | Same |
| Uploads | Read-only, from files you pick in the file dialog | Same |
| Page console messages | Discarded; never written to the journal | Same |
| Links opened in your browser | Handed to your default browser, which may keep them in its history; the address briefly appears in that browser's process arguments | Same |

The configuration file is readable by other users on many systems (mode
`0644`), so the enabled sites and their zoom levels can be seen by anyone who
can log in to this computer.

Apart from your settings and approved downloads, Hearthwire writes to disk
only in these places: the Antigravity token cache described above; only if
you choose Encrypted, the encrypted folder (written by Qt WebEngine through
gocryptfs) and, with Unlock with KDE Wallet, its key slot next to it; only if
you turn on Usage history, the [usage history](#usage-history) folder; only
when you press Export, the [settings backup](#settings-backup) file; and, only
after the one-time upgrade from the previous name, a backup of Plasma's panel
layout (see the last section of this page).

The widget never runs scripts in, reads from, or injects anything into the
pages, sets no `QTWEBENGINE_*` variables or Chromium flags, and does not pass
chat data to the Python helper, process arguments, or the environment. For
Stay signed in the widget runs the helper with fixed words and numbers only
(see [Provider contracts](provider-contracts.md#stay-signed-in-helper)); its
replies are short codes, never paths. For the Ollama chat and Local web UI it
runs the helper with the port number only ([port owner helper](provider-contracts.md#port-owner-helper)). A settings export passes
your settings, custom addresses included, to the helper (see
[Settings backup](#settings-backup)). Load errors show generic text and are
not logged. The system file dialog may remember recently used folders, as it
does for any application.

### Custom addresses

Under **Settings → Chat → Show advanced settings** you can change the address
each site opens. Custom addresses are saved in plain text in your Plasma
configuration file (`~/.config/plasma-org.kde.plasma.desktop-appletsrc`), which
other programs running as your user and your backups can read. Don't put
passwords, tokens, or other secrets in them. Addresses with a user name or
password (`https://user:pass@host/`) are refused, and text that isn't a valid
address is never saved. A custom address adds only its exact host to the site.

### Local web UI

Local web UI is off by default. It is the only site whose pages may use plain
`http:`, and only for the exact address and port you configured on this
computer (`localhost`, `127.0.0.1`, or `[::1]`); traffic over loopback never
leaves the computer, but it is not encrypted. That rule covers the pages and
embedded frames the widget controls; the Local page's own background requests
(fetch, WebSocket, images, scripts) are not filtered by the widget.

For every other site, the widget never opens or navigates to this computer:
not as the page, not in a new window, and not in an embedded frame. Like in
any browser, though, a page can still make background requests (fetch,
WebSocket, images and similar) to this computer or to names that resolve to it
(for example `*.nip.io`); the widget can't filter those. Keep in mind:

- Open WebUI (or whatever server you run) keeps its own accounts and chat
  history on its side. Clear chat data signs you out of it in the widget but
  does not delete anything stored by the server.
- **The port's owner is checked.** On a shared computer, another user could
  start their own server on the port before yours does. Before the Local page
  is created, and before each main-frame navigation of a Local page to this
  computer, the widget asks the helper who owns the listening socket (the same
  check as for Ollama; the helper sees only the port number). It loads
  nothing unless it belongs to you, root, or the system `ollama` account.
  Otherwise it shows "Another user's program is using port …" (or "Couldn't
  check which program is using port …", or "Nothing is using port …") with a
  Retry button, and a Local page that was already open is replaced by an
  empty page, so it can't keep talking to the new listener. A form sent to
  the Local page is checked too; it can't be replayed, so after the check you
  send it again within 10 seconds. That one-time pass ends after 10 seconds,
  on Dismiss and on any problem; later the form is checked again. Windows a Local page opens on this computer are dropped,
  since they would skip the check. The check cannot tell your own programs
  apart, and a listener could change in the milliseconds between the check
  and the load. Requests the page makes by itself (fetch, WebSocket) after it
  loaded, and embedded frames, are not checked again.
- A server on another machine needs `https:` with a certificate your system
  trusts; pages with self-signed or otherwise invalid certificates are not
  loaded. Address it by a full name such as `nas.lan`: a short name without a
  dot counts as this computer. Alternatively, reach it through an SSH tunnel
  to a local port.

### Ollama (built-in chat)

The Ollama entry (off by default; Settings → Chat) is a small chat written in
QML that talks to the Ollama API directly. It does not use Qt WebEngine, so
none of the web profile rules above apply to it; these do:

- **Where your messages go.** Each message, with the conversation so far, is
  sent in the body of a `POST /api/chat` request over plain `http://` on
  loopback to the address you set (default `http://127.0.0.1:11434`; only
  `127.0.0.1`, `localhost`, or `[::1]` with a port is accepted). Hearthwire
  itself sends it nowhere else, and it is readable by the program that
  answers on that port. With the packaged `ollama.service` that is a process
  of the system `ollama` account, so the `ollama` account's processes, and
  root, can read your prompts and the replies. That program decides where
  the message goes next: Ollama keeps it on this computer for local models,
  but a program on that port could pass it on, and if it answers with an
  HTTP redirect, Qt sends the message again to the redirect's address (which
  may be another computer) before the widget can notice. The widget then
  drops the request and shows none of that reply, but cannot take the
  message back.
- **Personalities.** A personality (the toolbar's Personality button) is
  your instruction for one model, at most 8000 characters. It is sent as the
  first message (`role: "system"`) in every request to that model, the same
  way as the conversation. In this version it lives in Plasma's memory only:
  **Clear conversation** keeps it, turning Ollama off in settings or a Plasma
  restart drops it. It is never saved to a file or a setting. Only the first
  line is shown above the conversation ("Personality: …"). While one is
  active, the newest message in each request also starts with a short fixed
  reminder, "(Stay in character as described in your instructions.)", which
  helps small models keep to it; the conversation shown keeps your own text.
- **Compare.** With **Compare two models** on, each message goes to model A
  and then, once A is done, to model B: two requests, each with its own port
  owner check and its own conversation and personality. Both models then
  hold the message in their context cache (RAM, or GPU memory) until they
  are unloaded, so it sits in two places, and the memory needed is about the
  sum of both models (around 2 × 5 GB for two 8B models at 4-bit; on this
  kind of computer without a GPU that is RAM). **Stop** ends the running
  request and B is not asked. **Clear conversation** clears both panes and
  unloads both models.
- **Drag and drop.** Text dragged from another program onto the chat, or onto
  the panel icon (which opens the Ollama chat), goes into the message box
  after what you typed; nothing is sent until you press Send. The dragged
  text passes through the compositor like any drag and drop, as plain text
  only (no HTML is read); control characters other than tab and line feed
  are removed. Nothing is written anywhere. Text that would make the message
  longer than 32000 characters is refused. Dropping is off while Ollama is
  off.
- **Dropped files.** One local text file (at most 128 KB, UTF-8) can be
  dropped too: the helper reads it (`--read-dropped`) and hands back only its
  text, which goes into the message box the same way. Its path is passed to
  the helper as hexadecimal digits, which anyone can decode. While the helper
  runs, that path is visible in the process list to programs running as you
  and, because `/proc` is usually not mounted with `hidepid`, to other local
  users too. Only the path is exposed, never the file's contents (see
  [Recommended system settings](#recommended-system-settings)). Symlinks, pipes, devices,
  `/proc` and `/sys` files, empty or larger files and anything that isn't
  text are refused, as are several files at once and links ("Drop text, not
  files.").
- **What Ollama keeps.** Ollama holds the conversation in its memory (the
  model's context cache, also in GPU memory) until the model is unloaded,
  5 minutes after the last message by default. **Clear conversation** asks
  Ollama to unload every model this conversation used (a request with no
  prompt and `keep_alive: 0`), so the next message loads the model again,
  which takes a few seconds. This also affects a model you are using with
  `ollama run` in a terminal at the same time.
- **Logs.** Ollama's service log records each request's method, path, status
  and timing (for example `POST /api/chat`), not its content. Don't set
  `OLLAMA_DEBUG` for the service: debug logging can write more.
- **Ollama's own history.** Prompts you type into `ollama run` in a terminal
  are saved by Ollama's command line tool in `~/.ollama/history`. That is not
  Hearthwire, and the widget never writes there, but it is a place your
  prompts may end up on disk.
- **Cloud models are hidden.** Ollama can list cloud models (names ending in
  `:cloud` or `-cloud`, or with a remote host) that forward your messages to
  ollama.com. Hearthwire drops them from the model list and never sends to
  them. Embedding-only models are hidden too.
- **The port's owner is checked.** If Ollama is stopped, another program can
  take its port. Before each model-list load and each send or unload, the
  widget asks the helper who owns the listening socket (read from
  `/proc/net/tcp`; the helper sees only the port number, never a prompt) and
  sends nothing unless it belongs to you, root, or the system `ollama`
  account. Another user's program gets nothing: "Another user's program is
  using port …". If the check can't be done, nothing is sent either. The
  check cannot tell your own programs apart, so a program running as you can
  still pose as Ollama, and a listener could change in the milliseconds
  between the check and the request. Hearthwire never starts Ollama.
- **Nothing on disk from Hearthwire.** The conversation lives only in Plasma's
  memory: no file, log, journal message, process argument, environment
  variable, helper call, or setting holds it. Nothing is in the request
  address either; only the body carries text. The model you pick is not saved.
  It stays while the popup is closed or another site is shown, and is gone on
  Clear conversation, when you turn Ollama off in settings, or on Plasma
  restart.
- **What is shown.** Replies and server error messages are shown as plain
  text only, so a reply containing HTML, Markdown images or links can't make
  the widget load anything. A small set of formatting is shown: headings
  (`#`, `##`, `###`), bullet and numbered lists, bold, italic and inline
  code, each as separate plain text items (never as rich text). Links,
  images, HTML tags and entities and tables stay literal text; nothing in a
  reply can be clicked or opened. Copy copies the reply's text as it came,
  markers included. Fenced code blocks are shown in a monospace font.
  Hidden and control characters in a reply are shown as visible markers such
  as `⟦U+202E⟧`, with the note "This text contains hidden or control
  characters": control characters (U+0000–U+001F except tab and line feed, so
  carriage return and escape too; U+007F; U+0080–U+009F including U+0085),
  line and paragraph separators (U+2028, U+2029), the soft hyphen (U+00AD),
  U+034F, direction controls (U+061C, U+200E, U+200F, U+202A–U+202E,
  U+2066–U+206F), zero-width and invisible characters (U+200B–U+200D,
  U+2060–U+2064, U+FEFF, U+180E, U+17B4, U+17B5, the Hangul fillers U+115F,
  U+1160, U+3164, U+FFA0), variation selectors (U+FE00–U+FE0F,
  U+E0100–U+E01EF), interlinear annotation (U+FFF9–U+FFFB), shorthand and
  musical format controls (U+1BCA0–U+1BCA3, U+1D173–U+1D17A) and tag
  characters (U+E0000–U+E007F). Such characters can make a command look
  different from what it really is ("Trojan Source"), and a carriage return
  or escape can make a terminal act on it. One U+FE0F right after an emoji
  (it only asks for the color form) is left alone; emoji sequences joined
  with U+200D and right-to-left text that use these characters show the
  markers.
- **Typing.** Spell checking is off in the message and personality fields, and they ask input
  methods not to learn or predict what you type (`ImhSensitiveData`,
  `ImhNoPredictiveText`); some input methods (for example CJK prediction) may
  offer fewer suggestions there.
- **Regenerate and Edit.** Regenerate (on the last reply) sends the same
  conversation again, after a new owner check, and replaces that reply; Edit
  (on your last message) puts it back into the message box and removes it and
  its reply from the conversation, sending nothing until Send.
- **Copying.** The Copy buttons and Ctrl+C put text on the clipboard, where a
  clipboard manager such as Klipper may keep it (see below). They copy the
  text as shown, with the markers, never the characters listed above, so none
  of them can hide in what you paste into a terminal. Characters that are
  visible but look alike (such as Cyrillic `а` for Latin `a`) and combining
  marks are not marked: read a command before you run it.

### Permissions and prompts

Every site permission request is denied: microphone, camera, screen sharing,
notifications, location, clipboard reading, mouse lock, and local fonts. There
is no per-site allow. Full-screen requests, HTTP authentication prompts, client
certificate requests, file-system access, and protocol-handler registration
are refused. Pages with certificate errors are not loaded. Passkey (WebAuthn)
sign-in is cancelled with the message "Passkeys aren't supported here; choose
another sign-in method."

Downloads ask each time: **Save "name" to Downloads?** Save writes the file to
your XDG Downloads folder; Cancel, or no answer within 60 seconds, discards it.
"Save page" downloads are always refused. The name is shown as plain text,
shortened, with hidden direction and zero-width characters as markers, so
`invoice⟦U+202E⟧fdp.exe` can't pass for `invoiceexe.pdf`. Long names are
shortened in the middle, so the end with the real (last) extension always
stays visible.

A page never opens your browser by itself. When you click a link (or a
window) that leaves the chat site, a prompt above the page asks **Open
example.net in your browser?** with **Open** and **Cancel**; the host is plain
ASCII text as in the off-site notice below. Only Open hands the address over.
Only one prompt is shown at a time: further requests while it is shown, and
for 3 seconds after it was shown or answered, are dropped, so a page can't
pile up prompts. Windows a page opens by itself are dropped without a
prompt. **Open in browser** in the toolbar, your own click, opens the
current site's page directly. Your browser may keep an opened address in its
history, and the address briefly appears in the browser's process arguments.
Sign-in popups open only after a click; one a page tries to open by itself is
dropped. They stay inside the widget, in a sign-in overlay that uses the same
profile as the chat page (private in Off, the saved one in Encrypted). Its
title always names a host: "Sign-in window: accounts.google.com", or while
the window is still blank (`about:blank`, or text a page wrote into it)
"Window opened by claude.ai", the host of the page that opened it. See [Provider contracts](provider-contracts.md#chat-tab) for the exact
navigation rules.

The widget has no address bar, and a page's scripts, redirects and forms may
still take it to other `https:` sites (sign-in flows need this). While the
page is on a host outside the site's own, sign-in and custom hosts, a notice
stays above it: **You are on example.net — not Claude**, with **Back to
Claude**. The host is shown as plain ASCII: international names appear in
their `xn--` form, so look-alike letters can't pass for the real name, and
long names are shortened from the front so the real domain at the end stays
visible. Don't type a password into a page while that notice is shown unless
you expected to be there.

### Threat model

The Chat tab protects against:

- other local users, who cannot read Plasma's memory or the unlocked
  encrypted folder;
- the developer: there is no telemetry, the widget makes no requests of its
  own (apart from the Ollama chat's requests to Ollama on this computer), and
  it never reads or changes the pages;
- with the Ollama chat: other users' programs on the Ollama port, cloud
  models, and leftovers of the conversation on disk from Hearthwire;
- with Local web UI: other users' programs on its port;
- provider replies or pages that try to slip markup into the widget's own
  text, hide direction characters in replies or download names, or move a
  chat page to another site unnoticed;
- with Off: leftovers on disk after a Plasma restart or Clear chat data;
- with Encrypted: someone who reads your disk while the folder is locked
  (for example a stolen, powered-off laptop), apart from the metadata listed
  above; with Unlock with KDE Wallet, only as well as your wallet's password
  protects it;
- chat content in logs.

It does not protect against:

- root, or malware running as your user, which can read Plasma's memory and,
  while it is unlocked, the encrypted folder, log your keystrokes, or show a
  fake passphrase window;
- the chat providers themselves, and the third parties their pages load;
- the Ollama server: the program answering on the Ollama port (with the
  packaged service, the `ollama` account) reads your prompts and keeps them in
  its memory until the model is unloaded;
- security bugs in the web engine itself: Qt WebEngine ships its own copy of
  Chromium, which often lags weeks behind Chrome's security fixes, and a
  page that exploits such a bug runs inside Plasma (see below);
- swap, hibernation, core dumps, or clipboard managers, unless configured as
  below;
- other local users seeing, in the process list, the path of a file dropped
  on the Ollama chat (and, with the features on, usage history percentages
  and exported settings), unless `/proc` is mounted with `hidepid` as below.

### Recommended system settings

- **Keep Qt WebEngine updated.** The Chat tab's engine (`qt6-webengine` and
  similar packages) is Chromium, and Qt's releases often lag behind Chrome's
  security fixes. Run system updates regularly, and restart Plasma
  (`systemctl --user restart plasma-plasmashell`, or log out and in) after a
  Qt WebEngine update, since the running Plasma keeps using the old library
  until then. Enable only the chat sites you actually use: each one is a
  site whose scripts, and the third-party scripts it loads, run in that
  engine.
- Use full-disk encryption, or at least encrypted `/home` and encrypted
  swap. Without it, a stolen or lost computer gives away the provider
  credential files, the Antigravity token cache, your Plasma settings, the
  usage history and the settings backup (if you have them), and memory paged
  out to disk (or a hibernation image) is readable later.
  The encrypted folder for saved sign-ins stays protected either way.
- Disable stored core dumps: for systemd-coredump, create
  `/etc/systemd/coredump.conf.d/50-no-storage.conf` with `[Coredump]` and
  `Storage=none`. A Plasma crash dump would contain chat pages, Off-mode
  sessions and cookies, the Ollama conversation, provider tokens and, while
  the folder is unlocked, the saved sign-ins Plasma has read from it; an
  Ollama crash dump would contain its context.
- Text you copy is handled by your clipboard manager. If Klipper (or another
  clipboard manager) keeps its history across sessions, copied chat text
  (including Ollama replies and code blocks) may be written to disk. Pages
  cannot read the clipboard.
- Never set `QTWEBENGINE_REMOTE_DEBUGGING` for Plasma; it would expose every
  open page, including your sessions, to local connections.
- On a computer shared with other users, mounting `/proc` with
  `hidepid=invisible` hides your processes, and with them the path of a
  dropped file, the usage history percentages and the exported settings,
  from those users. This needs root and is your choice; some
  system services expect to see every process, so check your distribution's
  notes first.

## Upgrading from Hearthside

The move from the former name is done once, by `scripts/install.sh` only; the
widget never does it. It copies no data:

- `~/.local/share/hearthside` (the encrypted folder, its key slots and any
  usage history) and `~/.config/hearthside` are renamed in place to their
  `hearthwire` names, and never merged: when both names hold data the installer
  stops. `~/.config/hearthside.notifyrc` is renamed too; if
  `~/.config/hearthwire.notifyrc` already exists it is kept and the old file is
  dropped.
- The Antigravity token cache in `~/.cache/hearthside` is deleted, not moved.
- The KDE Wallet key goes pipe to pipe between KDE's own programs, from wallet
  folder `Hearthside` to `Hearthwire`; it never passes through Hearthwire,
  process arguments, the environment, logs or a file. While it moves, both
  folders hold it. The old entry is removed only after the new one has opened
  the encrypted folder in a real unlock; if that fails, the new copy is removed
  and the old one stays. The empty `Hearthside` wallet folder stays until you
  delete it in KWalletManager.

One new item appears on disk, created by this move:
`~/.config/plasma-org.kde.plasma.desktop-appletsrc.hearthside-backup`, a copy
of Plasma's panel layout as it was before the widgets got their new id. It
holds what that file holds, including custom chat addresses in plain text, but
with mode `0600` so only you can read it. It is written once, and only if a
widget with the old id was found. It is removed automatically on the next
complete install that finds the move finished and a widget using the new id. A
rollback (`scripts/install.sh --rollback-hearthwire`) leaves it in place and
never writes one.

While the move runs the helper also holds the old name's lock file,
`/run/user/<uid>/hearthside/vault.lock`, which is in memory and holds no data.
