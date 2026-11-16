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
| `chatProfileLayout` | Written by the widget | `0` (the default: the old shared chat profile, or a new install), `1` (moved to one profile per site; the Chat tab's one-time notice still shows), or `2` (done). It makes the [move to one profile per site](#one-profile-per-site-the-one-time-move) run once |
| `chatPendingSiteClears` | Written by the widget | Which chat sites still owe the delete of a **Clear <site> data** with saved sign-ins, so a failed delete is retried and the site stays closed even after a Plasma restart: chat site ids separated by commas, for example `claude,gemini`, never a path, an address or a sign-in; empty (the default) when none. Anything in it that isn't a site id is ignored |
| `chatUserSites` | Chat → Add site…, Edit, Remove | The sites you added: for each one an id (`user-` and 8 random hex digits, never made from the name or address), the name and the address you typed, for example `[{"id":"user-3fa9c01b","name":"Le Chat","url":"https://chat.example.org/"}]`; `[]` (the default) when none. Nothing else is stored for a site: its hosts and whether it is local are worked out from the address each time. A value the widget can't read whole is shown as far as it is valid, and never deletes anything |
| `chatSiteOrder` | Chat → ↑ ↓ | The order of the chat sites (built-in and added ids and `ollama`), for example `["user-3fa9c01b","claude","ollama"]`; empty (the default) is the built-in order with added sites after the built-ins and Ollama last |

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
  `~/.local/share/hearthwire/usage-history/`), with one file per widget,
  `applet-<N>.json`, where N is the widget's Plasma id, and `history.lock`
  (empty; only its lock is used, by every widget).
- The folders are mode `0700` and the files mode `0600`, so only you can read
  them. Symlinks and other users' files are refused. The file is replaced
  atomically and is never larger than 256 KiB.
- The helper writes it (`--usage-history`; see
  [Provider contracts](provider-contracts.md#usage-history-helper)). Its
  command line holds the widget's id and, when recording, the sample: the
  provider and reading ids with their percentages, for example
  `claude.weekly=38`. That sample is the only history data in a command line,
  so for a moment other local users can see those percentages in the process
  list, unless `/proc` is mounted with `hidepid` (see
  [Recommended system settings](#recommended-system-settings)).
- History is per widget: each Hearthwire widget has its own on/off setting
  and its own file, and never reads another widget's. The widget keeps its
  own copy of what the helper last returned in Plasma's memory, only while
  history is on, and reads the file again each time the popup opens.

How long: each record and each read drops everything older than 7 days (the
current hour and the 168 before it); a file with nothing left is deleted.

How to delete it:

- Turn **Usage history** off and apply: the widget forgets what it showed and
  deletes its own file. Other widgets' history stays.
- **Delete usage history** (next to the setting) deletes this widget's file at
  once and leaves the setting as it is. While history stays on, recording
  starts again at the next refresh.
- Either also deletes the shared `history.json` an earlier build may have
  left, and the `usage-history` folder once no widget's file is left in it.
- `scripts/install.sh --uninstall-web-data` deletes the history of every
  widget (the whole `usage-history` folder), after the chat sign-in data. If
  it can't, it says so and asks you to delete the folder by hand. It doesn't
  change the setting: a widget that still has history on starts recording
  again.
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

**Export** and **Import** (Settings → General → Backup), the panel menu's
**Back up settings** and **Restore settings…**, and **Automatic backup** use
one fixed file; there is no file dialog.

- Where: `$XDG_CONFIG_HOME/hearthwire/settings-backup.json` (usually
  `~/.config/hearthwire/settings-backup.json`). The folder is mode `0700`
  (made, or tightened, by Export) and the file mode `0600`, so only you can
  read it. It is replaced atomically. A symlink, another user's file, or a
  folder or file other users may write to is refused and left alone.
- What is in it: a format name, a version (`2`), the settings format (`3`),
  the time of the export (UTC), two checksums (see
  [Backup identity](#backup-identity)), and these settings: `trackedProviders`,
  `providerMetrics`, `providerOrder`, `usageMode`, `refreshInterval`,
  `tooltipShowsUsage`, `tooltipMetrics`, `usageCompact`, `usageWarnPercent`,
  `usageCriticalPercent`, `usageNormalColor`, `usageWarnColor`,
  `usageCriticalColor`, `alertLowEnabled`, `alertResetEnabled`,
  `alertLowPercent`, `chatSites`, `chatDefaultSite`, `chatOllamaUrl`,
  `chatKeepOpen`, `showUsageTab`, `showChatTab`, `popupDefaultTab`,
  `popupSize`, `shortcutOpens`, `panelRing`, `middleClickOpens`,
  `chatCustomUrls`, `chatUserSites` and `chatSiteOrder`. So it names the
  providers and chat sites you use and holds your custom chat addresses and
  the names and addresses of the sites you added in plain text, like the
  Plasma configuration file does. The file is at most 512 KiB (enough for
  200 added sites with long addresses); a bigger file is refused.
- What is never in it: sign-ins, cookies, passphrases, the KDE Wallet key,
  prompts, personalities, chat text or model names; and the settings
  `chatSignInStorage`, `chatProfileGeneration`, `chatAutoLockMinutes`,
  `chatVaultUnlock`, `chatSiteZoom`, `configSchemaVersion`,
  `initialSetupComplete`, `usageHistoryEnabled`, `usageHistoryClearOwed`,
  `chatProfileLayout`, `chatPendingSiteClears`, `backupAutoExport` and
  `backupRestoreAt`. An import never turns on Usage history or Stay signed
  in, and never changes Automatic backup. The backup key is never in it.
- Export saves the widget's applied settings only: the helper reads them
  itself from Plasma's configuration file
  (`~/.config/plasma-org.kde.plasma.desktop-appletsrc`, or
  `plasmawindowedrc` when the first file has no Hearthwire widget with that
  id) by the widget's id, read-only, and refuses a symlinked file or another
  user's. It reads only a widget whose plugin is Hearthwire, never another
  widget's settings. A setting the file doesn't have counts as its
  default. Changes not yet applied on any settings page are not exported, so
  press **Apply** first. The Export button asks before it replaces an
  existing backup; the menu's **Back up settings** and Automatic backup
  replace it without asking. None of them replaces a backup with an empty
  one.
- **Automatic backup** (off by default; Settings → General → Backup, "Back
  up automatically when settings are applied"): about 3 seconds after you
  press Apply with a changed backed-up setting, and once when you turn it on,
  the widget exports the same way as the button, to the same file. Starting
  Plasma exports nothing, and applying with nothing changed exports nothing.
  A success is silent; a failure shows one notification with a fixed reason
  (once per reason, until an export works again). There is one file per
  user and no older copies: with several Hearthwire widgets that have it on,
  the last one to apply wins. After **Restore settings…** it waits up to a
  minute, while an import's Replace question is open, and after Replace
  until you apply, so the backup you are restoring from is never replaced
  while you look at it. If you cancel the import or close Settings without
  applying, the next automatic backup saves your current settings over that
  file.
- **Back up settings** in the panel menu exports at once and shows a
  notification ("Settings backed up" or a fixed reason). **Restore
  settings…** opens Settings on General at the Backup section and starts an
  Import there, with the same checks and confirmation as the Import button;
  nothing changes until you press Replace and then Apply. Notifications
  never contain a path, a setting or helper text.
- No setting you entered is passed on a command line: the helper's command
  holds only fixed words, the step (status, export or import) and two whole
  numbers (a run number and the widget's id). Other local users can't see
  your settings in the process list.
- Import reads the file; the helper and then the widget check every value,
  and a value the widget would not store is left out ("Settings left out:
  N"). An added site is kept only when every added site in the file is
  valid (exactly an id, a name and an address the widget accepts, nothing
  else; see [Custom and added addresses](#custom-and-added-addresses)), and
  `chatSites`, `chatSiteOrder`, `chatDefaultSite` and `middleClickOpens` may
  name only the added sites the same file keeps. Before **Replace**, the
  confirmation lists each chat address the import would change, each site it
  adds, and each added site it removes, as plain text and shortened when
  long; a site it adds over plain `http://` is marked "not encrypted". An added site the backup moves to another host is listed as removed
  and added. **A site the backup doesn't have, or moves to another host, is
  removed when you apply, and its data is deleted** (as for Remove, see
  [One profile per chat site](#one-profile-per-chat-site)); a red warning
  says so before you apply. After
  **Replace** the values fill in the settings pages; nothing is saved until
  you press **Apply** on the General page.
- The file stays until you delete it. `scripts/install.sh
  --uninstall-web-data` leaves it in place and says where it is, and
  removing the widget leaves it too. Both also leave the backup key.

### Backup identity

Each backup made by Hearthwire 1.1 or later (format version 2) carries a
plain SHA-256 of its content (`sha256`) and an HMAC-SHA256 of it
(`signature`) made with a key that only this install has. Both cover the
format, version, settings format, export time and settings, as the helper
reads them (whitespace and key order don't count).

- The key: `$XDG_DATA_HOME/hearthwire/backup-key` (usually
  `~/.local/share/hearthwire/backup-key`), 32 random bytes, mode `0600` in a
  `0700` folder, so only you can read it. The first export makes it; it is
  never changed after that and has no rotation. It is deliberately not next
  to the backup in `~/.config` (copying or syncing that folder would carry
  the key along), not in the encrypted folder (export must work while it is
  locked, or with Off) and not in KDE Wallet (reading it can wait on a
  prompt, and the wallet would not keep it from programs running as you
  either). The key is never shown, logged, written into the backup, put in
  a reply, the environment or a command line. A key file that is a symlink,
  another user's, readable or writable by others or unreadable, not exactly
  32 bytes, hard-linked elsewhere, or in a folder others may write to is
  never used or replaced: Export then
  stops with "The backup key … isn't safe to use", and you delete it to
  make a new one. Status never reads it; Import only reads it.
- What Import shows, before you can press Replace:
  - checksum and signature match: "Made by Hearthwire on this computer.";
  - checksum doesn't match (the file was damaged or edited): **refused**,
    "The backup file is damaged", and nothing changes;
  - checksum matches but the signature doesn't (another computer, user or
    key, or a deleted key): "Not made by this Hearthwire: check every change
    below before you press Replace." The import still works;
  - a version 1 file (Hearthwire 1.0.x and 1.1 pre-release builds) has no
    checksums: the same warning, and the import still works. Every new
    export writes version 2.
- The result is for your information only: the same settings are checked
  and kept, with the same preview, whatever it says.
- **After you restore another computer's backup, the next backup signs it
  as this computer's.** Once you press Replace and Apply, those settings are
  this widget's own, so the next export (the button, the menu or Automatic
  backup, which runs about 3 seconds after that Apply, or up to a minute
  after a menu Restore, see above) writes them signed
  with this install's key, and a later import says "Made by Hearthwire on
  this computer." The warning you saw before Replace is not kept anywhere.
- If the computer crashes or loses power at the moment the first export
  makes the key, the key may be left with a second file name next to it.
  Until the next export cleans that up, Import shows the warning even for
  this computer's backups (the key is then not used); nothing else changes.
- Deleting the key makes every earlier backup show the warning. Hearthwire
  1.0.1 can't read a version 2 file ("made by a different version") and
  ignores the key.
- What it protects against and what it doesn't: see the
  [Threat model](#threat-model).

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

Each chat site signs in on its own (see
[One profile per chat site](#one-profile-per-chat-site)). Signing in to Google
in Gemini no longer signs you in on other sites, and "Sign in with Google" on
Claude, ChatGPT, Grok or Copilot asks for your Google account separately.

**Stay signed in** (Settings → General → Privacy) has two choices:

- **Off** (the default): everything you enter (accounts, passwords, prompts,
  uploaded files, cookies) stays in Plasma's memory and is gone when Plasma
  restarts or you choose **Clear chat data**. Nothing is written to disk.
- **Encrypted**: sign-ins and site data are kept in a passphrase-protected
  folder made with gocryptfs, so you stay signed in across Plasma restarts.

**Split view** (the Chat toolbar's Split button, not saved in the settings)
shows a second site in a second page. Two different sites use their own
two profiles; the same site in both panes shares that site's one profile and
sign-in. The rules are the same (Off or Encrypted, permissions, external-link prompts, sign-in
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

### One profile per chat site

Every chat site (Claude, ChatGPT, Grok, Gemini, GitHub Copilot, Microsoft
Copilot and Local web UI, and every site you add in Settings → Chat) has its
own Qt WebEngine profile; no profile is shared between sites. A site's profile is made the first time that site is
opened, so memory grows only with the sites you actually open (each one adds
its own network context and in-memory cache on top of the page itself). A site's sign-in windows use that site's profile.

What this guarantees:

- Each chat site has its own cookies, local storage, IndexedDB, cache,
  service workers, permissions, history and favicons, and with saved sign-ins
  its own folder (including its GPU caches) in the encrypted folder.
- A compromised or hostile page on one site can't send requests that carry
  another site's sign-in, and can't read another site's data. Another site
  framed inside it shows as signed out.

Its limits:

- The pages themselves run in separate, sandboxed renderer processes, one
  per page. What all profiles share is Chromium's browser process, which is
  Plasma itself, and its network and GPU processes. A page that exploits a
  bug in its renderer and also escapes Chromium's sandbox runs as you, inside
  Plasma, and could read every site's data in memory and, while it is
  unlocked, the encrypted folder.
- The clipboard, your Downloads folder, your system browser and your network
  are shared by all sites.

Sites you add:

- An added site gets its profile exactly as a built-in one does (with saved
  sign-ins, its own `site-user-<8 hex>` folder in the encrypted folder). Its
  sign-in windows use its profile; a page it frames from another site shows
  as signed out.
- Its address is an `https://` address with a public name, a server on this
  computer (`localhost`, `127.0.0.1` or `[::1]`), or a home-network IP
  address (`10.x`, `172.16–31.x`, `192.168.x`, IPv6 `fc00::/7`); the last two
  over `http://` or `https://` (see
  [Custom and added addresses](#custom-and-added-addresses) and
  [Local web UI and sites on this computer](#local-web-ui-and-sites-on-this-computer)).
  Its kind is worked out from the address each time and never stored, so a
  hand edit or a backup can't make a public host count as this computer.
  A public added site's pages, frames and windows can't open this computer
  or a private, link-local or loopback IP address. One on this computer or
  the network opens only its own exact address (scheme, host and port)
  there, never another one, and no window to this computer or the network,
  its own address included. Like any browser, it may follow redirects and sign-in pages to other public
  `https://` hosts; a link you click to another host opens in your browser.
- Changing an added site's address to **another host** makes it a new site
  (the editor says so): the old site is signed out and its data deleted on
  Apply, so no sign-in carries over to a different host. A new address on the
  same host keeps the sign-in. (A built-in site's custom address keeps that
  site's profile, as before.)
- **Removing an added site deletes its data.** Settings → Chat warns you
  before Apply; Cancel keeps everything. On Apply its pages and profile
  close, and with saved sign-ins its folder is deleted, through the same
  path as Clear <site> data: the delete is stored as owed first, so if the
  encrypted folder is locked (or another widget holds it) the folder is
  deleted at the next unlock, also after a Plasma restart. The first prepare
  after each unlock also deletes the folder of any site that no longer
  exists. A value of
  `chatUserSites` the widget can't read whole never deletes an entry it
  can't read or that is missing from it: no site is removed and nothing is
  pruned, and Settings → Chat refuses to add, edit, remove or reorder added
  sites until the list is readable again (its warning counts every site id
  in the applied value, readable or not). The one exception is the host
  change below: an entry that is readable both before and after and now
  points at another host is removed even when other entries are damaged. Ids of
  removed sites are never reused while their delete is owed. A backup import
  without a site, and a **Defaults** button on the Chat page if your Plasma
  version shows one, remove it in the same way.
- **A host change is a new site, however it arrives.** A backup import that
  gives an added site an address on another host gives it a new id, so the
  import confirmation lists it as removed and added, and on Apply the old
  site's data is deleted as above. A hand edit of the settings file (or any
  other writer) that keeps the id but changes the host is caught while the
  widget runs: the site is removed the same way, its page never loads the
  new host with the old profile (Home refuses too), and it opens again on a
  new, signed-out profile. Limit: an edit made while the widget isn't
  running can't be noticed, because the old host isn't stored; the site's
  saved sign-in folder then stays with it. Don't edit added sites' addresses
  by hand.
- **A damaged entry that comes back starts fresh.** If an added site's entry
  can't be read (the rest of the list may be fine) and later becomes
  readable again, for example on another host, its old host is unknown, so
  it is treated as a new site: signed out, its data deleted, a new profile.
  A backup import gives such an entry a new id, listed as removed and
  added.

### Off: private in-memory profiles

Every site's profile, including the sign-in windows that use it, is off the
record, with an in-memory HTTP cache and no persistent cookies. Qt WebEngine
creates no profile directory for them. Cookies, sessions, local storage,
IndexedDB, service workers, history, and favicons exist only in memory.
Spell checking is off. You are signed out on every Plasma restart.

**Clear <site> data…** (a Chat toolbar button for the site of the pane you
are using, after a confirmation) closes that site's pages and sign-in window
and destroys its profile, which signs you out of that site only; the other
sites stay signed in. A new, empty profile is made when you open the site
again.

**Clear chat data** (in the Chat tab, after a confirmation) destroys every
chat page together with every site's profile, which signs you out of all
chat sites at once. Chat is the first tab, so Qt WebEngine starts the first time you open
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
  keeps its saved sign-ins in its own folder there,
  `web/applet-<N>-g<G>/` (N is the widget's Plasma id, G a counter that
  Clear chat data raises), and each chat site in its own `site-<id>/` folder
  inside that one, for example `web/applet-42-g3/site-claude/`. A site's
  folder is made only when the site is first opened while the folder is
  unlocked, and a site never opens with saved sign-ins before its folder is
  ready: until then its page waits, it never silently opens privately
  instead.
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
deletes this widget's saved sign-ins inside the folder (every site's), and
locks the folder.

**Clear <site> data…** in Encrypted mode is offered only while the folder is
unlocked and its saved sign-ins are open (not in a private session).
Clear <site> data first records the site in the widget's settings, then deletes its saved sign-in; if the delete fails, the site stays closed and is deleted at the next unlock (also after a restart) before it can open again, and Clear chat data, once its delete succeeds, settles every such pending delete.

In detail: the site is noted in the setting `chatPendingSiteClears`, and
Plasma is asked to save the settings at once; if the note can't be saved,
nothing is cleared. Then the site's pages and profile close, the widget waits
about a second for them to finish writing, and deletes only that site's
`site-<id>/` folder; the other sites stay signed in. While any of your
programs still has a file in that folder open (Qt WebEngine can keep its site
storage open for a while after the profile closed), the helper answers
`busy` and deletes nothing. To find out it reads only the open-file and
mapped-file lists of your own processes under `/proc` (ones it isn't allowed
to read, and ones running as root through sudo, are skipped), and it tries,
without waiting, to lock each of the site's own `LOCK` files (the lock Qt
WebEngine's site storage holds while it is open, whichever program that is)
and lets go at once. It changes nothing there, and its answer holds
no path or name. The note goes only once
the delete worked, and the site gets a new, empty folder the next time it is
opened. If the delete fails, the Chat tab says so. Clear chat data clears the
note only after its own delete worked; if that fails, the note stays.

At each unlock the widget first runs every delete still owed, then prepares
the shown sites' folders, and then tidies its own folder: older counters of
this widget's folder are deleted (as before), and so is anything in the
current one that isn't a chat site's `site-<id>/` folder. Turning a site off
in settings keeps its saved sign-in.

#### One profile per site: the one-time move

Versions up to 1.0.1 kept every site in one shared profile. The first time a
newer version starts, it moves to one profile per site once
(`chatProfileLayout`):

- It switches to a new, empty profile counter, so nothing of the old shared
  profile is ever opened again. Every site asks you to sign in once more.
- After the next unlock, the old shared profile's folder is deleted inside the
  encrypted folder, with the same safe delete as Clear chat data. Until then
  it stays encrypted and unused.
- With saved sign-ins on a widget you had already set up, the Chat tab shows
  a one-time notice saying so (and the Google sign-in note above), until you
  click **Got it**.

Going back to 1.0.1 is harmless: its sign-ins start empty, and its Clear chat
data still deletes everything, including the per-site folders. Upgrading
again shows no second notice. At the next unlock, before any site opens, the
widget sees what 1.0.1 left in its folder and deletes everything in that
folder: 1.0.1's files and every site's saved sign-in from before you went
back. So no account you used before the downgrade comes back on its own; you
sign in to each site once more.

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
| Cookies, sessions, site storage | Memory only, one profile per site; dropped on Clear <site> data (that site), removing an added site, Clear chat data or Plasma restart | Encrypted folder, one `site-<id>` folder per site (with that site's history, favicons and GPU caches); deleted on Clear <site> data (that site), removing an added site (that site, at the next unlock if locked), Clear chat data (this widget) or when you turn it Off (all widgets) |
| HTTP cache | Memory only | Memory only |
| Page titles, addresses, history, icons | Memory only; the widget never shows, stores, or logs them | Same; Qt WebEngine's own history files, if any, are inside the encrypted folder |
| Passphrase | Not used | Never stored; typed into kdialog, read by gocryptfs |
| Passwords and form autofill | Not supported by Qt WebEngine; nothing is saved | Same |
| Widget settings | The enabled sites (`chatSites`), the first site (`chatDefaultSite`), any custom addresses you enter (`chatCustomUrls`), the names and addresses of the sites you add (`chatUserSites`) and the site order (`chatSiteOrder`), the Stay signed in choice (`chatSignInStorage`), a profile counter (`chatProfileGeneration`), the one-time profile move's state (`chatProfileLayout`), the sites still owing a Clear <site> data delete (`chatPendingSiteClears`), the Ollama address (`chatOllamaUrl`), the zoom of each site and of the Ollama chat, set with the zoom keys or Ctrl+scroll (`chatSiteZoom`, for example `{"claude":1.25}`; sites at 100% are left out), the General page's popup choices (`popupDefaultTab`, `showUsageTab`, `showChatTab`, `popupSize`, `chatKeepOpen`, `chatAutoLockMinutes`, `shortcutOpens`, `middleClickOpens`, and
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
when you export (button, menu or Automatic backup), the
[settings backup](#settings-backup) file and, the first time, its
[backup key](#backup-identity) (`~/.local/share/hearthwire/backup-key`); and, only
after the one-time upgrade from the previous name, a backup of Plasma's panel
layout (see the last section of this page).

Installing or removing a release package (pacman, dnf, apt) changes only
files under `/usr`. A package runs nothing as you and never reads, moves or
deletes anything in your home folder, so removing it keeps the usage history,
the settings backup and its key, the encrypted folder with its key slots, the KDE Wallet
key, the Antigravity token cache and the widget settings. To delete the
chat sign-ins and the usage history, use the helper commands in the
README's "Install from a package" section before you remove the package.

The widget never runs scripts in, reads from, or injects anything into the
pages, sets no `QTWEBENGINE_*` variables or Chromium flags, and does not pass
chat data to the Python helper, process arguments, or the environment. For
Stay signed in the widget runs the helper with fixed words and numbers only
(see [Provider contracts](provider-contracts.md#stay-signed-in-helper)); its
replies are short codes, never paths. For the Ollama chat, Local web UI and
the sites you added on this computer it runs the helper with the port number
only, and for a site you added by a home-network IP address also with that IP
address ([port owner helper](provider-contracts.md#port-owner-helper)). A settings export passes
only the widget's id; the helper reads the applied settings itself (see
[Settings backup](#settings-backup)). Load errors show generic text and are
not logged. The system file dialog may remember recently used folders, as it
does for any application.

### Custom and added addresses

With a built-in site's **Edit** button in **Settings → Chat** you can change
the address it opens, and with **Add site…** you add a site by name and
address. Only a valid address is saved, when you press Save. Custom and added
addresses are saved in plain text in your Plasma
configuration file (`~/.config/plasma-org.kde.plasma.desktop-appletsrc`), which
other programs running as your user and your backups can read. Don't put
passwords, tokens, or other secrets in them. Addresses with a user name or
password (`https://user:pass@host/`) are refused, and text that isn't a valid
address is never saved. A custom address adds only its exact host to the site;
an added site's address is its own host, and nothing else is stored with it.

An added site's address may be:

- `https://` with a public name;
- this computer, written `localhost`, `127.0.0.1` or `[::1]`, over `http://`
  or `https://`, any port;
- a home-network IP address in `10.0.0.0/8`, `172.16.0.0/12`,
  `192.168.0.0/16` or IPv6 `fc00::/7`, over `http://` or `https://`, any
  port.

Everything else is refused, the same way by the widget and by the backup
helper (one set of rules, tested against each other):

- `http://` with a name, `.local` and `.lan` included: the widget can't check
  names, and any device on the network can answer for one (mDNS, DNS);
- other spellings of this computer (`127.0.0.2`, `localhost.`, names
  without a dot);
- IP addresses not in their usual form (`192.168.1.020`, `0xc0.168.1.1`,
  `3232235777`, `[fd00:0:0:0:0:0:0:1]`; IPv6 is written short, `[fd00::1]`),
  because pages are matched against the exact address the engine reports;
- IPv6 zone ids (`fe80::1%eth0`) and IPv4 inside IPv6 (`[::ffff:192.168.1.1]`);
- link-local addresses (`169.254.0.0/16`, `fe80::/10`): they aren't stable,
  and `169.254.169.254` is the cloud metadata address; `fd00:ec2::/32`, the
  cloud (AWS) IPv6 metadata range, is refused the same way, although it is
  inside `fc00::/7`;
- every other IP address: public ones, and `100.64.0.0/10` (carrier-grade
  NAT, which on many providers is their side of the line; Tailscale's IPv4
  range). Tailscale's IPv6 addresses are inside `fc00::/7` and are accepted.

### Local web UI and sites on this computer

Local web UI is off by default. It and the sites you added on this computer
or your home network are the only sites whose pages may use plain `http:`,
and only for the exact address and port configured (for Local web UI and the
sites on this computer: `localhost`, `127.0.0.1`, or `[::1]`); traffic over
loopback never leaves the computer, but it is not encrypted. That rule covers
the pages and embedded frames the widget controls; the page's own background
requests (fetch, WebSocket, images, scripts) are not filtered by the widget.

For every other site, and for an added site anywhere but its own address,
the widget never opens or navigates to this computer:
not as the page, not in a new window, and not in an embedded frame. Like in
any browser, though, a page can still make background requests (fetch,
WebSocket, images and similar) to this computer or to names that resolve to it
(for example `*.nip.io`); the widget can't filter those. Keep in mind:

- Open WebUI (or whatever server you run) keeps its own accounts and chat
  history on its side. Clear chat data signs you out of it in the widget but
  does not delete anything stored by the server.
- **The port's owner is checked.** On a shared computer, another user could
  start their own server on the port before yours does. Before the Local page,
  or the page of a site you added on this computer, is created, and before
  each of its main-frame navigations to this computer, the widget asks the helper who owns the listening socket (the same
  check as for Ollama; the helper sees only the port number). It loads
  nothing unless it belongs to you, root, or the system `ollama` account.
  Otherwise it shows "Another user's program is using port …" (or "Couldn't
  check which program is using port …", or "Nothing is using port …") with a
  Retry button, and every page on that port that was already open (Local
  web UI or an added site) is replaced by an empty page, so it can't keep
  talking to the new listener; pages on other ports stay. A form sent to
  the Local page is checked too; it can't be replayed, so after the check you
  send it again within 10 seconds. That one-time pass ends after 10 seconds,
  on Dismiss and on any problem; later the form is checked again. Windows
  such a page opens on this computer are dropped,
  since they would skip the check. The check cannot tell your own programs
  apart, and a listener could change in the milliseconds between the check
  and the load. Requests the page makes by itself (fetch, WebSocket) after it
  loaded, and embedded frames, are not checked again.
- **A server elsewhere on your home network** can be added with Add site… by
  its IP address (see
  [Custom and added addresses](#custom-and-added-addresses)). Before its
  page is created, and before each main-frame navigation to that address,
  the widget asks the helper whether the address is one of **this
  computer's own**. The helper reads only the kernel's address and route
  tables, not a test connection, which another program could fool.
  - If it is this computer's address, another local user could listen on it,
    and the page would load from them. So the same owner check as above
    applies, counting the listeners on that address and on all addresses
    (`0.0.0.0`, `::`).
  - If it isn't, the connection leaves this computer, no local program can
    answer it, and the page loads. The widget can't ask another machine who
    is listening there.
  - The check reads only the address and route tables. Firewall rules an
    administrator set up, such as NAT, port forwarding or a transparent proxy
    (`iptables`/`nftables` DNAT or REDIRECT), can still send that traffic to
    a program on this computer, and the check doesn't see them. That is
    accepted because only root can set up such rules, and root is trusted
    anyway: it owns the system's programs and can read everything the widget
    stores.
  - For a server on this computer, use `localhost` rather than its network
    address.

  Over plain `http://`:
  - anyone on the network can read and change the traffic, including the
    site's cookies;
  - a device that takes that address (by spoofing on your network, or simply
    because another network such as a café or hotel uses the same address)
    gets that site's cookies, and its pages run as that site: they can read
    that site's saved data (Local Storage, IndexedDB, for example a web UI's
    saved token or cached chats). It can't reach any other site's sign-in or
    data, the encrypted folder's other sites or the widget, and it can't open
    or frame this computer or other addresses on the network;
  - the page isn't a "secure context" for the engine (unlike `http://` on
    this computer), so service workers, the async clipboard, `crypto.subtle`
    and `crypto.randomUUID` are unavailable and some web UIs work only
    partly.

  Use `https:` with a certificate your system trusts to rule this out; pages
  with self-signed or otherwise invalid certificates are not loaded. An
  `https:` page can't load or frame an `http:` one (mixed content).
- **DNS rebinding.** An added site's own address can't be rebound: this
  computer is fixed to `localhost`, `127.0.0.1` or `[::1]` (the engine
  resolves `localhost` itself), home-network sites are IP addresses, and
  `http://` names are refused. Any page in any site can still point a name
  it controls at a server on this computer or your network and read its
  unauthenticated replies, as in any browser; such a request never carries
  the added site's cookies, which live in that site's own profile. Have local
  model servers check the `Host` header and require a sign-in (Open WebUI
  accounts; Ollama's `OLLAMA_ORIGINS`).
- For Local web UI, address another machine by a full name such as
  `nas.lan`: a short name without a dot counts as this computer.
  Alternatively, reach it through an SSH tunnel to a local port.

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
dropped. They stay inside the widget, in a sign-in overlay that uses the
profile of the site that opened it (private in Off, that site's saved one in
Encrypted). Its
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
- with Local web UI and sites you added on this computer: other users'
  programs on their port; with a site you added by a home-network address
  that is this computer's own, the same;
- one chat site's page using or reading another chat site's sign-in or data
  (each site has its own profile; see the limits under
  [One profile per chat site](#one-profile-per-chat-site));
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
  page that exploits such a bug runs inside Plasma (see below); pages have
  their own sandboxed renderer processes, but Chromium's browser process
  (Plasma itself) and its network and GPU processes serve every site's
  profile, so such a page that also escapes Chromium's sandbox can reach
  every site's data;
- what all sites share: the clipboard, your Downloads folder, your system
  browser and your network;
- with a site you added on the home network over plain `http://`: anything
  on the network between you and that device, and a device that takes its
  address (it gets that one site's sign-in and data, never another site's);
- background requests a page makes to this computer or your network (fetch,
  WebSocket, images), which the widget can't filter; with a site on your
  network, bugs in the web engine are reachable from that network, not only
  from the internet;
- swap, hibernation, core dumps, or clipboard managers, unless configured as
  below;
- other local users seeing, in the process list, the path of a file dropped
  on the Ollama chat (and, with Usage history on, its percentages), unless
  `/proc` is mounted with `hidepid` as below.

The settings backup's [identity](#backup-identity) protects against:

- accidental damage (disk errors, a truncated copy or sync): the file is
  refused;
- a backup that came from elsewhere (another computer or user, a dotfiles
  repository, a shared or downloaded file, a sync conflict copy): a warning;
- tampering by something that can write `~/.config/hearthwire` but can't read
  `~/.local/share/hearthwire` (for example a sync tool limited to the config
  folder): a warning.

It does not protect against:

- anything running as you, root, or anyone with a copy of your home folder
  including `~/.local/share`: they can read the key and sign any file (and
  could change Plasma's settings directly anyway);
- an older genuine backup from this computer put back in place (there is no
  replay protection);
- reading the file: it is not encrypted;
- older files counting as "made on this computer" after you move or restore
  your home folder with the key;
- proving anything to anyone else: this is not a public-key signature.

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
  dropped file and the usage history percentages, from those users. This needs root and is your choice; some
  system services expect to see every process, so check your distribution's
  notes first.

## The hearthwire-hyprland app

The separate Hyprland/Omarchy app uses the same helper. It tells the helper
so with one environment variable it sets for its own commands
(`HEARTHWIRE_FRONTEND=app`); nothing on a command line can switch it, and the
Plasma widget never sets it. For the widget nothing changes.

- **Its own settings file.** The app keeps its settings in
  `~/.config/hearthwire-hyprland/settings.json` (folder `0700`, file `0600`),
  not in Plasma's config. It holds the same settings as the widget (tracked
  providers, chat sites with your custom and added addresses, alerts, and so
  on) plus the app's own switches (keep running in the background, Agents
  panel, tray). No sign-ins, passphrases, keys or chat text are in it. The
  helper only reads it, for a settings backup, and refuses it when it is a
  link, someone else's, over 1 MiB, or when other users could read or change
  it: the folder must be `0700` or stricter and the file `0600` or stricter.
- **Separate from the widget.** The app uses one fixed id of its own
  (2147483648), so its chat profiles inside the encrypted folder and its
  usage history are kept apart from every widget's. Shared on purpose: the
  encrypted folder itself (one passphrase), the settings backup file and its
  key, so a backup made in the app restores in the widget and the other way
  round. The app's own switches are never in a backup. The app can't clear
  the widgets' usage history ("clear all" is refused there; it clears only
  its own) and never runs the move from the former name, which changes
  Plasma's own files.
- **Passphrase window.** Instead of KDE's kdialog the app's own small
  passphrase window, `hearthwire-askpass`, asks for the passphrase, and
  gocryptfs reads it from there directly, as with kdialog; it never passes
  through the helper or the app. The helper runs only the copy at
  `/usr/lib/hearthwire-hyprland/hearthwire-askpass`, and only while that file
  and every folder above it belong to root and nobody else can change them,
  so another program of yours (or another user) can't put a look-alike in
  its place there. A look-alike window opened by a program already running
  as you is not something the helper can tell apart.
- **No KDE Wallet in the app.** The KDE Wallet unlock belongs to the widget.
  The app never uses it, never changes the widget's wallet key and runs no
  wallet tool; the app unlocks with the passphrase. Deleting the encrypted
  folder from the app removes the folder and its key slots but leaves the
  widget's wallet entry; it is useless without the slot, and the widget's own remove
  or uninstall deletes it.
- **Saved prompts.** The app has no text window for the prompt library yet,
  so adding or replacing a saved prompt or persona there is not available
  (the helper reports a missing tool and never opens KDE's kdialog); saved
  ones can still be listed and removed.

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
