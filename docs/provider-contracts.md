# Provider contracts

The implementation follows the macOS AI Usage menubar app, using Linux/XDG
equivalents for local storage. These endpoints are not public provider APIs,
so sanitized fixture tests protect the known response shapes.

## Discovery and failure behavior

The helper merges the process and login-shell `PATH`, then checks provider CLI
names and local data locations. The login-shell capture runs `$SHELL -ilc`
with a command built only from `echo` and `printenv`, so it works the same in
POSIX shells and fish. It reads only the allow-listed variables
`CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `XDG_CACHE_HOME`, `XDG_CONFIG_HOME`,
`XDG_DATA_HOME`, and `PATH`, parses only the text between its begin and end
markers, and ignores startup-file noise. `--detect` runs only this discovery
step: it reads no credentials and makes no network requests.

Only tracked and installed providers are contacted. A sign-in file that cannot
be read or is not valid UTF-8 skips that source, and the next source is tried.
If a provider cannot be set up at all, only that provider reports a `storage`
failure; the others are still refreshed. Authentication and storage failures clear the widget's previous
reading; transient, rate-limit, and invalid-response failures preserve the
last successful reading in Plasma memory and mark it stale.

A failed token refresh is classified by what the token endpoint said, not as a
sign-out by default: a network error or a `5xx` reply is `transient`, a `429`
is `rate_limited` with a cooldown from `Retry-After`, and only a `4xx` grant
error (or an explicit logout flag) reports the provider as signed out. This
applies to Cursor, Antigravity, and Grok.

The helper never follows HTTP redirects: a 3xx from a provider is reported as
a failed request (`invalid-response`), never sent on to the `Location`
address with the credentials.

Every request has a per-read socket timeout (15 s by default) and an overall
deadline of 20 s across connect, TLS handshake, headers and body (every
step except the name lookup, which cannot be interrupted); a server
that drips its answer past the deadline is cut off and the request fails like
an unreachable provider. Bodies are read up to 1 MiB; a larger body (declared
or streamed) fails the request instead of being read into memory.

`Retry-After` accepts seconds or an HTTP date and defaults to five minutes
when missing or unparseable. The resulting cooldown is clamped to between now
and 24 hours from now.
Cooldowns are held in Plasma memory and are not written to disk.

## Claude Code

- Auth: `$CLAUDE_CONFIG_DIR/.credentials.json`, otherwise
  `~/.claude/.credentials.json`
- Usage: `GET https://api.anthropic.com/api/oauth/usage`
- Refresh: `POST https://platform.claude.com/v1/oauth/token`
- Metrics: Session, Weekly, Sonnet, Fable, Extra Usage

The `user:profile` scope is required when scope metadata exists.
`CLAUDE_CODE_OAUTH_TOKEN` setup tokens are intentionally ignored.

## Codex

- Auth: `$CODEX_HOME/auth.json` exclusively when set; otherwise
  `~/.config/codex/auth.json`, `~/.codex/auth.json`, then Secret Service
  `Codex Auth`
- Usage: `GET https://chatgpt.com/backend-api/wham/usage`
- Refresh: `POST https://auth.openai.com/oauth/token`
- Metrics: Session, Weekly, Spark, Spark Weekly, Credits

API-key-only documents are detected but cannot read ChatGPT subscription
usage.

## Cursor

- Auth: `~/.config/Cursor/User/globalStorage/state.vscdb` (plus the legacy
  `~/.cursor` equivalent), then Secret Service services
  `cursor-access-token` and `cursor-refresh-token`
- Usage:
  `POST https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage`
- Plan:
  `POST https://api2.cursor.sh/aiserver.v1.DashboardService/GetPlanInfo`
- Refresh: `POST https://api2.cursor.sh/oauth/token`
- Metrics: Total Usage, Auto Usage, API Usage

Cursor refreshes early, within five minutes of the access token's expiry. If
that early refresh hits an outage or a `429` while the access token is still
valid, the helper uses the current token; the failure is reported only once
the token has actually expired. A refused grant still reports signed out. Each
helper run sends a given refresh token at most once.

## Antigravity

- Auth: Secret Service service `gemini`, username `antigravity`
- OAuth refresh metadata: resolved at runtime from the installed Antigravity IDE
  bundle; no OAuth client credentials are shipped in this repository
- Refresh: `POST https://oauth2.googleapis.com/token`
- Usage: `retrieveUserQuotaSummary`, falling back to
  `fetchAvailableModels`, on Google's daily Cloud Code and Cloud Code hosts
- Plan: `loadCodeAssist`
- Metrics: Gemini Session/Weekly and Claude Session/Weekly

The fallback also runs when the summary succeeds but holds no known quota
bucket. Each request tries both hosts. A `429` from one host is reported as
`rate_limited` (with its `Retry-After`) only if no host succeeds, and then no
further plan or quota requests are sent. If neither host answers, the provider
reports `transient`. A refresh outage leaves the derived-token cache untouched,
and each helper run sends a given refresh token at most once.

The derived access-token cache is documented in [Privacy](privacy.md).

## GitHub Copilot

- Auth: `~/.config/github-copilot/apps.json`, then `hosts.json`, then
  `~/.config/gh/hosts.yml`, then Secret Service `gh:github.com`
- Usage: `GET https://api.github.com/copilot_internal/user`
- Metrics: Credits, Chat, Completions

Unlimited and zero-entitlement buckets are not rendered.

## Devin

- Auth: `~/.local/share/devin/credentials.toml`, then the Linux Devin
  `state.vscdb`
- Usage:
  `POST /exa.seat_management_pb.SeatManagementService/GetUserStatus` on the
  configured HTTPS server or `https://server.codeium.com`
- Metrics: Daily, Weekly

## Grok

- Auth: `~/.grok/auth.json`
- Refresh: `POST https://auth.x.ai/oauth2/token`
- Usage: `GET https://cli-chat-proxy.grok.com/v1/billing?format=credits`
- Plan: `GET https://cli-chat-proxy.grok.com/v1/settings`
- Metric: Weekly

A missing or empty `auth.json`, or one with no usable account entry, reports
signed out. A file that exists but cannot be read, is not valid UTF-8, or is
not valid JSON reports `storage`. A usage `429` reports `rate_limited` with
its `Retry-After` and skips the plan request.

All credential rotations use source-aware, mode-`0600` writes and avoid
overwriting a concurrent login. A credential file that is a symlink is written
through to its final target, leaving the link in place; the write is refused
(`storage`) if the target is missing, is not a regular file, or is not owned
by the current user.

Claude Code, Codex, and Grok rotate refresh tokens, so each refresh holds a
per-provider cross-process lock (`flock` on an empty lock file, waiting up to
30 seconds). Under the lock the helper re-reads the exact credential source.
If another process already rotated the tokens, the helper uses them and sends
no refresh. Otherwise it sends at most one refresh `POST` per refresh token
and writes the result back with compare-before-write. If that write fails, the
provider reports a `storage` failure and does not reload or retry, because the
old refresh token has already been spent. If the lock stays busy, the provider
reports a `transient` failure without sending a refresh. Grok refreshes early,
within five minutes of expiry; if that early refresh fails for any reason
other than storage (including a busy lock) while its access token has not yet
expired, Grok still uses the current access token, and reports the failure
only once the token has expired. A refresh token that already failed in this
run is not resent; the earlier failure is reported again. If the re-read finds the
login gone (file deleted or emptied, or Codex switched to an API key), the
provider reports it as signed out; if the source cannot be read or decoded, or
the Secret Service lookup fails, it reports `storage`. Neither case sends a
refresh. The usage request
itself never runs under the lock. Provider CLIs do not take this lock;
compare-before-write still catches their concurrent writes.

## Chat tab

The Chat tab is not a provider contract: it shows each provider's own website
and never calls an API or reads the pages. The one exception is the built-in
Ollama chat, which calls the local Ollama API (see
[below](#built-in-ollama-chat)). It runs the helper only for Stay signed in
(see [below](#stay-signed-in-helper)) and for the port owner check of the
Ollama chat and Local web UI (see [below](#port-owner-helper)), never with
chat data. Web sites, their home
pages and host lists live only in `plasmoid/contents/ui/ChatSites.js`. The
navigation rules below are the same with Stay signed in Off or Encrypted.

| Site | Home page | Site hosts | Sign-in hosts |
| --- | --- | --- | --- |
| Claude | `https://claude.ai/new` | claude.ai, claude.com, anthropic.com | accounts.google.com, appleid.apple.com |
| ChatGPT | `https://chatgpt.com/` | chatgpt.com, openai.com | accounts.google.com, login.microsoftonline.com, login.live.com, appleid.apple.com |
| Grok | `https://grok.com/` | grok.com, x.ai, x.com | accounts.google.com, appleid.apple.com |
| Gemini (best effort) | `https://gemini.google.com/app` | gemini.google.com, accounts.google.com, consent.google.com | accounts.google.com |
| GitHub Copilot | `https://github.com/login?return_to=%2Fcopilot` | github.com | github.com, accounts.google.com, appleid.apple.com |
| Microsoft Copilot | `https://copilot.microsoft.com/` | copilot.microsoft.com, microsoft.com, bing.com | login.microsoftonline.com, login.live.com, account.live.com, accounts.google.com, appleid.apple.com |
| Local web UI (Open WebUI), off by default | `http://localhost:3000/` | localhost, 127.0.0.1, [::1] | none |

GitHub Copilot starts at the sign-in page because signed-out visitors to
`/copilot` are redirected to a landing page; after sign-in GitHub returns to
`/copilot`.

A host matches when it equals a listed host or ends with `.` plus that host,
case-insensitively, so `evilclaude.ai` never matches `claude.ai`.

Custom addresses (`chatCustomUrls`, JSON `{siteId: url}`, written only by the
settings page):

- Only known site ids with a valid, non-empty address are kept, in catalog
  order; unreadable JSON, unknown ids, or invalid entries fall back to the
  built-in address. Every use re-validates the address.
- An address must be at most 2048 characters, contain no whitespace or user
  info (`@` in the host part), and use `https:`. Local may also use `http:`,
  but only with the host `localhost`, `127.0.0.1`, or `[::1]`. No other site
  may point at this computer. Control characters (U+0000–U+001F, U+007F) are
  rejected like whitespace.
- A custom address adds exactly its own host to the site (no subdomains); the
  built-in site and sign-in hosts still apply.

Navigation in a site view (main frame unless noted):

- Only `https:` main-frame pages load, plus `about:blank`. `http:`, `file:`,
  `data:`, `javascript:`, `view-source:`, `chrome:`, `qrc:`, other schemes, and
  malformed URLs (including user info in the host) are blocked.
- Local only: every main-frame navigation to this computer (any scheme the
  rules allow, port 80/443 when absent) first runs the
  [port owner check](#port-owner-helper); the request is rejected and loads
  only after the helper said `self` or `system`, as a one-time pass for
  exactly that address. The Local view is not even created before such an
  answer. Anything else loads nothing, shows a message, and turns an open
  Local page into `about:blank`. A form post is not replayed after the check;
  the user sends it again. That pass expires after 10 seconds
  (`ownerPassLifetime`) and is cleared on Dismiss and on any problem. Pure decisions: `ChatSites.localOwnerPort` and
  `ChatSites.localOwnerGate`; the check runs in `LocalOwnerCheck.qml`.
- Exception for Local only: `http:` loads when the host is a loopback name
  (`localhost`, `127.0.0.1`, `[::1]`) and host plus port (80 when absent)
  equal those of Local's address exactly. Any other port, loopback spelling or
  host is blocked; with an `https:` custom address Local allows no `http:`.
- Every site except Local is blocked from this computer under any scheme:
  `localhost`, `*.localhost`, `localhost.localdomain`,
  `*.localhost.localdomain`, `ip6-localhost`, `ip6-loopback`, every name
  without a dot, `[::1]`, `0.0.0.0`, and any `127.x.x.x` address in any
  numeric spelling. So a Local web UI on another machine must be addressed by
  a full name (e.g. `nas.lan`): a short name like `nas` is treated as this
  computer and owner-checked.
- Embedded frames (subframes) may load `https:` from any host and `about:`,
  `blob:`, `data:` or srcdoc content, with two exceptions: an `http:` or
  `https:` frame on this computer (same test as above) is blocked for every
  site except Local, and Local's `http:` frames load only for the exact origin
  of its address. Malformed `http:`/`https:` frame URLs are blocked.
- Scope: these rules cover what the widget can intercept, which is main-frame
  and frame navigations and new windows. Background requests made by a page
  (fetch, XHR, WebSocket, images, scripts, styles) are not filtered, so a page
  can still reach this computer that way, directly or through names that
  resolve to it (such as `*.nip.io`), as in any browser. The same applies to
  the Local page's own subresources over `http:`.
- A clicked link to a host outside the site and sign-in hosts is cancelled.
  The widget then asks "Open <host> in your browser?" (plain text, host from
  `ChatSites.displayHost`); only Open hands it to the system browser. One
  prompt at a time; requests while one is shown or within 3 seconds after
  the last one was shown or answered are dropped, as are addresses without
  a readable host. `Qt.openUrlExternally` is called only by that Open and
  by the toolbar's **Open in browser**.
- Other `https:` navigations, such as sign-in redirects and form posts, stay
  in the view, so sign-in flows keep working. While the main frame is on a
  host outside the site, sign-in and custom hosts, a plain-text notice "You
  are on <host> — not <site>" with **Back to <site>** (home) stays above the
  page (`ChatSites.offSiteHost`). The host is ASCII: lower case, without user
  info or port, international labels in their `xn--` (punycode) form, at most
  64 characters, shortened from the front. An authority containing `\` has
  no readable host (browsers read it as `/`), so the notice says "another
  site".

New windows requested by a page:

- A popup dialog (`about:blank` or `https:`) or an `https:` window on one of
  the site's sign-in hosts opens in a sign-in overlay inside the popup, using
  the same profile as the site view, and closes when the page closes it.
  Its plain-text title names its own host ("Sign-in window: <host>"), or
  while it has none (`about:blank`, empty, written by a script) the opener's
  ("Window opened by <host>", `ChatSites.overlayHost`).
  A sign-in window opens only when the page's window request was
  user-initiated (a click); script-opened windows are dropped.
- Any other `https:` window, or a sign-in window opened from the overlay,
  gets the same "Open <host> in your browser?" prompt, and only when you
  clicked to open it; windows a page opens by itself are dropped.
- Everything else is blocked, including every `http:` window (Local too) and
  windows to this computer from any site except Local. A Local sign-in
  window that would start on this computer is dropped too, because it would
  skip the port owner check.

**Open in browser** is offered only for a page of the current site: an
`https:` page (not on this computer, except for Local), or Local's own `http:`
loopback address.

Gemini sign-in may be refused by Google inside embedded browsers. The
Microsoft Copilot host lists are a best guess; a wrong entry only changes
whether a link opens inside the widget or in the browser.

### Built-in Ollama chat

"Ollama" (id `ollama`, off by default) is not a web site and is not in
`ChatSites.js`: `plasmoid/contents/ui/OllamaChat.js` holds its entry and all
parsing, and `OllamaChatView.qml` makes the requests with QML
`XMLHttpRequest` (the only file that does). `chatSites` may contain `ollama`,
and `chatDefaultSite` may be `ollama`; the dropdown lists it after the web
sites. The web view never gets `ollama` as a site and does not start while
Ollama is shown.

Address (`chatOllamaUrl`, String, default `http://127.0.0.1:11434`, written
only by the settings page):

- Exactly `http://<host>:<port>` with an optional trailing `/`, at most 64
  characters, saved normalized as `http://host:port`. `host` is `127.0.0.1`,
  `localhost`, or `[::1]` (any case), nothing else: no other `127.x` address,
  `0.0.0.0`, numeric spellings such as `2130706433` or `0x7f000001`,
  `*.localhost`, or names that resolve to loopback. `port` is 1 to 65535 and
  must be given.
- Refused, with these codes: `too-long`, `whitespace` (also control
  characters), `userinfo`, `scheme` (anything but `http`), `not-loopback`,
  `port-missing`, `port-range`, `path` (any path, query or fragment),
  `malformed`. Empty text means the default. While the field holds invalid
  text the value saved when the page opened stays saved. A config value that
  doesn't validate is replaced by the default when used.

Requests, all to the configured address, nothing in the URL but the path:

| Request | When | Body |
| --- | --- | --- |
| `GET /api/version` | The Ollama view is shown, after the owner check | none |
| `GET /api/tags` | After a valid version reply | none |
| `POST /api/chat` | Send or Regenerate, after its own owner check; while comparing, again for model B once A is done (second owner check) | `{"model":m,"messages":[{"role":"system","content":p}?,{"role":"user"\|"assistant","content":s},…],"stream":true}` |
| `POST /api/chat` | Clear conversation, once per model used, after an owner check | `{"model":m,"messages":[],"keep_alive":0}` (unloads the model) |

The only header set is `Content-Type: application/json` (POST only); no
credentials, cookies or `Authorization`, and Qt's XMLHttpRequest sends no
`Origin` header (Ollama answers 403 to a foreign `Origin`). Nothing is
requested until Ollama is enabled and shown in the open popup, and there is no
polling: the list is loaded when the view is shown while it isn't loaded yet
(also after a failure), on **Retry** or **Reload models**, and when the
address changes. Each turn sends the whole
conversation; prompts are at most 32000 characters (Send is disabled above
that).

System message: the model's personality (memory only, per model name, at
most 8000 characters) is sent as the **first** message,
`{"role":"system","content":p}`, built only by
`OllamaChat.chatRequestBody(model, messages, system)`. No personality (empty,
blank, null or undefined) sends no system message; a longer one, or a
non-string, sends nothing at all (Send is disabled). The history never
carries the system role (`ROLES` is user and assistant; a history message
with any other role makes the body empty). llama3 obeys it (spike O1, Ollama
0.40.13), but drifts away from it in longer conversations, so with a
personality the newest user message is sent as
`OllamaChat.PERSONA_REMINDER` ("(Stay in character as described in your
instructions.)" and a blank line) followed by the text
(`withPersonaReminder`); earlier turns are sent as typed.

Compare runs the two models one after the other, never at once: model A's
request, then model B's with B's own history and personality. Stop aborts
the running request and B is not asked; B is also not asked after a failure
that means the server is gone (not running, refused, timeout). Clear unloads
every model either pane used. Regenerate drops the pane's last reply and
sends the same history again; Edit only changes the conversation in memory.

Formatting (`OllamaChat.blocks`): the reply is read into heading (`#`–`###`),
paragraph, bullet (`-`, `*`, `+`, nested to depth 2), numbered (`1.`) and
code (```` ``` ```` fences, unterminated = code to the end) blocks, each with
spans of plain text marked bold (`**`/`__`), italic (`*`/`_`) or inline code
(`` ` ``). Unclosed markers stay literal; links, autolinks, images, HTML and
entities and tables are never recognised. A block over 300 words (or 4000
characters) is one plain span with its markers left in. Every block's text
goes through `revealHidden` first.

Replies:

- `/api/version` must be status 200 with a JSON object whose `version`
  matches `^\d+\.\d+` (at most 32 characters); anything else is "Something
  other than Ollama is answering at this address." and nothing more is sent.
- `/api/tags`: `models[]` in server order, at most 200. A model is kept when
  its `name` matches `^[A-Za-z0-9._:/+-]{1,200}$`. Dropped and counted as
  hidden: entries with `remote_host` or `remote_model`, or names ending in
  `:cloud` or `-cloud` (cloud models forward prompts to ollama.com). Dropped
  silently: entries whose `capabilities` exists but lacks `completion`
  (embedding models) and duplicates. `details.parameter_size` and `family`
  are shown only when they are short plain words. The model choice is
  runtime only: the previous choice while it is still listed, else the first.
- `/api/chat` streams NDJSON. Only complete `\n`-terminated lines are read
  (plus the last line when the reply ends); blank lines are skipped. For each
  object, `message.content` is appended; `message.thinking` only shows
  "Thinking…" and its text is discarded; `done: true` ends the reply; an
  `error` string ends it as a server error. A line that isn't a JSON object
  ends it as unreadable. Replies are cut at 200000 characters (the request is
  aborted and the text kept). Unknown fields are ignored.
- Server error text is shown only as plain text, at most 300 characters,
  with control characters, bidi controls and `<`, `>`, `&` removed.

Status handling: 0 (connection refused) "Ollama isn't running."; 403
"Ollama refused the request."; 404 on chat "This model isn't installed any
more."; anything else non-2xx a generic error plus the server's `error`
text. No first byte within 300 s (a model can take minutes to load on a CPU)
or no data for 120 s aborts with "Ollama stopped responding." Stop and Esc
abort the request; a reply that was already partly shown is kept and marked
stopped. Late events of any aborted or finished request are ignored.

Owner check (see [below](#port-owner-helper)): `none` is "Ollama isn't
running.", `other` "Another user's program is using port N. Hearthside won't
send anything to it.", any failure or a check that takes over 15 s
"Couldn't check which program is using port N."; only `self` and `system`
let a request through. Error texts never show the address, only its port.

Redirects: Qt's XMLHttpRequest follows HTTP redirects on its own, including
to another host or port, and repeats a POST body there; JavaScript never sees
the 3xx (measured with Qt 6.12.0 for 302 and 307). From readyState 3 on,
`responseURL` holds the address that actually answered, so every reply is
checked against the exact `OllamaChat.endpoint()` it was sent to. On the
first mismatch the request is aborted and nothing from it is read: a
redirected `/api/version` or `/api/tags` is "Something other than Ollama is
answering at this address." (no model list, nothing can be sent), a
redirected `/api/chat` ends as "Ollama reported an error." with no reply text
and no server error text shown.

Limits: by the time a redirect is seen, Qt has already sent the request to
the new address, so a trusted listener (one that passed the owner check) that
answers `/api/version` and `/api/tags` normally but redirects only
`POST /api/chat` still hands the prompt to wherever it points, possibly
another computer. That is the same trust as in a listener that proxies the
request onward itself; the owner check covers only the configured port. An
unload request (no prompt) is sent the same way and its reply is never read.
The check also cannot tell programs of your own user apart. While a reply
streams, it is read at most every 100 ms (Qt decodes the whole body again on
each read), and once more when it ends.

## Stay signed in helper

For **Stay signed in → Encrypted** the plasmoid runs the helper for a few
fixed jobs. These commands touch no provider credentials, make no network
requests, and pass no chat data; the wallet jobs read and write only the
folder's own key entry in KDE Wallet. The plasmoid builds them in
`plasmoid/contents/ui/ChatStorage.js` from fixed words and integers only, as
`env HEARTHSIDE_RUN=<n> HEARTHSIDE_APPLET=<applet> python3 -P -m hearthside ...`
(`-P`: Python doesn't put the working folder on the module path).
`HEARTHSIDE_RUN` is a run counter and `HEARTHSIDE_APPLET` the widget id; together
they keep command names unique across widgets and settings pages so replies are
told apart. The helper ignores both.

### Layout

- Encrypted folder (gocryptfs cipher directory):
  `$XDG_DATA_HOME/hearthside/vault/` (`~/.local/share` when `XDG_DATA_HOME` is
  unset or not absolute).
- Mount: `$XDG_RUNTIME_DIR/hearthside/vault/`. `XDG_RUNTIME_DIR` must be set,
  absolute, a real directory, owned by you and mode `0700`, else the reply is
  `no-runtime-dir`. The bare mountpoint is mode `0700` while mounting and
  `0500` while locked.
- Profiles: `<mount>/web/applet-<N>-g<G>/`, one per widget id `N` and profile
  generation `G` (`chatProfileGeneration`, raised by Clear chat data). Folders
  are mode `0700`.
- KDE Wallet key slot: `$XDG_DATA_HOME/hearthside/vault-keys/wallet.conf`
  (folder `0700`, file `0400`, outside the cipher directory). It is a copy of
  `gocryptfs.conf` whose master key is wrapped with a random key
  (`openssl rand -hex 32`) kept in your KDE Wallet (`localWallet`, normally
  `kdewallet`), folder `Hearthside`, entry `encrypted-chat-folder`. The
  passphrase slot (`gocryptfs.conf`) is never changed by it and stays the
  recovery slot. While being set up the copy is `wallet.conf.new` (gocryptfs
  itself writes `wallet.conf.new.tmp`) and its key is staged in the entry
  `encrypted-chat-folder.new`; while the new slot is swapped in, the previous
  one is `wallet.conf.old`. Leftovers of all of these are cleared.
- Lock file: `$XDG_RUNTIME_DIR/hearthside/vault.lock` (`flock`). Jobs that
  may open a window (`create`, `unlock`, `change-passphrase`, `add-key`,
  `remove-key`) wait for it as long as needed; all others (including
  `auto-unlock`) give up after 5 seconds with `busy`.

A mount is used only after `/proc/self/mountinfo` shows a `fuse.gocryptfs`
mount of exactly that cipher directory with your `user_id` and without
`allow_other` or `allow_root`, and the mount root is a directory you own on a
different device than its parent. Every folder below it is opened one level
at a time without following symlinks.

### Commands

| Command | Does | Success reply |
| --- | --- | --- |
| `--vault status` | Reports the folder's state; cleans up a dead mount; never prompts | `{"ok":true,"state":"absent"}`, `"damaged"`, `{"ok":true,"state":"locked","wallet":W}`, `{"ok":true,"state":"unlocked","wallet":W}` (optionally with `"missing"`, see below), or `{"ok":true,"state":"unavailable","missing":[...]}` |
| `--vault create` | Creates and initialises the folder (kdialog `--newpassword`), then mounts it (kdialog `--password`); deletes a `vault-keys/` left from an older folder | `{"ok":true}` |
| `--vault unlock [--method passphrase]` | Mounts the folder (kdialog `--password`); already unlocked is success | `{"ok":true}` |
| `--vault unlock --method wallet` | Mounts the folder with the wallet slot: gocryptfs runs `kwallet-query -r` itself (KWallet's own password prompt if the wallet is locked; capped at 120 s); already unlocked is success | `{"ok":true}` |
| `--vault auto-unlock` | For Plasma start: like `unlock --method wallet`, but only when the Secret Service says the wallet is unlocked; otherwise `wallet-closed` and nothing else runs, so it never prompts | `{"ok":true}` |
| `--vault add-key --method wallet` | Sets up (or replaces) the wallet slot, folder locked or unlocked: copies `gocryptfs.conf`, stages a new random key in the wallet, re-keys the copy with `gocryptfs -passwd -config` (kdialog `--password` for the current passphrase), then swaps slot and key in; a failure leaves an existing slot working | `{"ok":true}` |
| `--vault remove-key --method wallet` | Deletes the wallet slot, then overwrites the wallet entry (and a leftover staging entry) with a fresh random value and deletes it; no slot and no entry is success; needs no openssl (without it the overwrite is skipped) | `{"ok":true}` |
| `--vault lock` | `fusermount3 -u`; retried after 0.5 s and 1 s, never forced or lazy; already locked or a dead mount is success | `{"ok":true}` |
| `--vault change-passphrase` | `gocryptfs -passwd`, only while locked (kdialog `--password`, then `--newpassword`) | `{"ok":true}` |
| `--vault destroy` | Deletes the cipher directory, `vault-keys/` and the bare mountpoint, only while not unlocked, then the wallet entry when this folder had a wallet slot and the wallet holds it; nothing there is success | `{"ok":true}` |
| `--web-data prepare --store encrypted --applet N --generation G` | Creates `web/applet-N-gG/` inside the verified mount | `{"ok":true}` |
| `--web-data remove --store encrypted --applet N [--keep G]` | Deletes this widget's `applet-N-g*` folders, except generation `G` when given; nothing there is success | `{"ok":true}` |
| `--web-data purge` | Deletes the encrypted folder and `vault-keys/` for `scripts/install.sh --uninstall-web-data`, then the wallet entry when `vault-keys/` held a wallet slot, kwallet-query and qdbus6 are there and the wallet holds it; refuses while anything is mounted at the mountpoint or from the cipher directory (also checks `/run/user/<uid>`); runs no other tool | `{"ok":true,"removed":[...]}` with any of `"vault"`, `"vault-keys"`, `"wallet-entry"` in that order (empty when nothing was there) |

`absent` means there is no cipher directory or it is empty. `damaged` means the
cipher directory holds files but no regular `gocryptfs.conf`: gocryptfs can
neither open nor initialise it, so `create`, `unlock`, and `change-passphrase`
fail with `damaged` and only `destroy` (or `purge`) clears it.

With `"state":"unavailable"`, `missing` lists, in this order, whichever of
`gocryptfs`, `gocryptfs-v2` (gocryptfs is older than 2.0, or its version can't
be read), `kdialog`, and `fusermount3` are not found on `PATH`. `--store`
accepts only `encrypted`; there is no unencrypted store.

`wallet` (only with `locked` and `unlocked`) is `set-up` when
`vault-keys/wallet.conf` is a regular file of yours with mode `0400`, `off`
when there is none (or anything else is in its place), and `unavailable` when
`kwallet-query` or `qdbus6` is missing, KWallet is disabled
(`isEnabled` = false), or `qdbus6` did not answer within 2 seconds. When a
tool is missing the reply also has `"missing"` with any of `kwallet-query`,
`qdbus6` and `openssl`, in that order (packages `kwallet`, `qt6-tools` and
`openssl`). `openssl` is needed only by `add-key` (`remove-key`, `destroy`
and `purge` skip their best-effort overwrite without it), so when only it is
missing `wallet` still says `set-up` or `off`. `status` never checks the
wallet entry or opens the wallet; `unlock --method wallet` does. It does run
one `qdbus6 … org.kde.KWallet.isEnabled` query (when kwallet-query and qdbus6
are there and the folder is locked or unlocked): that call can D-Bus-activate
kwalletd6 if it is not running yet, and while a KWallet password prompt is
pending it waits for its 2 second timeout, so `status` can take up to 2
seconds longer and then reports `wallet:"unavailable"` for that call.

Wallet unlock, step by step (all queries through `qdbus6` with a 2 second
timeout, answers are booleans, the wallet's name or a handle):

1. `org.kde.kwalletd6 /modules/kwalletd6 org.kde.KWallet.isEnabled`; false →
   `wallet-disabled`. `localWallet` must match `^[A-Za-z0-9._ -]{1,64}$` and
   not start with `-`.
2. The slot must be set up (see above), else `not-set-up`.
3. `auto-unlock` only: `org.freedesktop.secrets
   /org/freedesktop/secrets/aliases/default Label` must equal the wallet's
   name, then that alias's `Locked` is read (else the collection
   `/org/freedesktop/secrets/collection/<name>` when the name is a valid path
   element). Anything but `false` is `wallet-closed`. kwalletd6 `isOpen` is
   never used: it is false right after a PAM login even with the wallet
   unlocked.
4. `keyDoesNotExist(<wallet>, Hearthside, encrypted-chat-folder)` (answers
   while locked, without a prompt); true → `not-set-up`.
5. `gocryptfs -q -nosyslog -config <slot> -extpass kwallet-query -extpass
   --folder -extpass Hearthside -extpass --read-password -extpass
   encrypted-chat-folder -extpass <wallet> <cipher> <mount>`, then the usual
   mount checks.

Setting up (`add-key`) is staged, so a failed re-setup (Cancel, a wrong
passphrase, a wallet error) leaves an existing slot and entry working:

1. After the same step 1, `gocryptfs.conf` is copied to `wallet.conf.new`.
2. `openssl rand -hex 32` writes into `kwallet-query --folder Hearthside
   --write-password encrypted-chat-folder.new <wallet>` through a pipe. If
   openssl fails after kwallet-query stored what it got (an empty value),
   that staging entry is deleted again (`wallet-write-failed`).
3. `kwallet-query --read-password encrypted-chat-folder.new` writes into a
   second pipe, and only when it exited 0 does that pipe become the stdin of
   `gocryptfs -passwd -q -config <slot>.new -extpass kdialog ... <cipher>`
   (kwallet-query prints its errors on stdout, so a failed read must never
   reach gocryptfs).
4. When gocryptfs exited 0, the copy is made `0400` and fsynced;
   `wallet.conf` (if any) becomes `wallet.conf.old` and the copy becomes
   `wallet.conf`. The staged key is then moved to the real entry:
   `kwallet-query --read-password encrypted-chat-folder.new` into a pipe and,
   after it exited 0, `kwallet-query --write-password encrypted-chat-folder`
   from that pipe (the helper never reads it). Only when that write exited 0
   is `wallet.conf.old` deleted; otherwise the new slot goes back to
   `wallet.conf.new` and `wallet.conf.old` back to `wallet.conf`, so the old
   slot keeps opening the folder with the old entry (unless kwallet-query
   changed the real entry before it failed).
5. The staging entry is overwritten with a fresh value and deleted, after a
   success and after a failure. When the wallet itself did not answer
   (`wallet-failed`) it is not asked again; a staging entry left then is
   deleted by the next set-up, `remove-key`, `destroy` or `purge`.

On the first set-up a failure leaves no slot. `remove-key` removes the slot
first in every case; if it then fails (`missing-tool`, `wallet-disabled`,
`wallet-failed`), only wallet entries may remain. It removes both the entry
and a leftover staging entry: each is overwritten with a fresh value (only
when openssl is there), then deleted through
`org.kde.KWallet.open(<wallet>, 0, Hearthside)` → handle,
`removeEntry(handle, Hearthside, <entry>, Hearthside)`,
`close(handle, false, Hearthside)`, and checked with `keyDoesNotExist`.
`destroy` and `purge` delete the files first and the entries last (openssl
is not needed), and touch the wallet only when this data folder's
`vault-keys/` held a wallet slot of ours (a regular file `wallet.conf`, or the
`wallet.conf.old` / `wallet.conf.new` an interrupted set-up leaves; checked
without following links before anything is deleted). A stray or empty
`vault-keys/` leaves the wallet alone and is not reported as `wallet-entry`.
There `wallet-failed` means only an entry may remain (`remove-key` or
KWalletManager removes it; running destroy or purge again does not, the slot
being gone), and purge reports `wallet-entry` when it removed either entry.

Calls that may show KWallet's own password prompt (the wallet is locked):
`kwallet-query` in `unlock --method wallet`, `add-key`, `remove-key`,
`destroy` and `purge`, and `open` in the last three. Each is capped at 120
seconds; a timeout is `wallet-failed`. The key never passes through the
helper: it moves only between children through pipes the helper holds but
never reads, and never appears in argv, the environment or a reply.

Argument rules (argparse exits 2 with a usage message on stderr otherwise):

- `--web-data`, `--vault`, `--prompts`, `--read-dropped`, and `--port-owner`
  cannot be combined with each other or with `--json`, `--providers`,
  `--catalog`, or `--detect`.
- `--method passphrase|wallet` needs `--vault unlock`, `add-key`, or
  `remove-key`; `add-key` and `remove-key` need `--method wallet`; `unlock`
  defaults to `passphrase`.
- `--store`, `--applet`, `--generation`, and `--keep` need `--web-data`
  `prepare` or `remove`; `prepare` needs `--store`, `--applet`, and
  `--generation` and refuses `--keep`; `remove` needs `--store` and
  `--applet` and refuses `--generation`; `purge` takes none of them.
- `N` and `G` are plain decimal integers from 0 to 2147483648 (at most 10
  digits; no sign, spaces, or underscores).

### Replies and errors

Every job prints one JSON object on stdout and exits 0. Replies never contain
paths, names, counts, keys, or passphrases; stderr carries only argparse usage.
Children get an argument list (no shell) with stdin, stdout, and stderr on
`/dev/null`; the only exceptions are the pipe between the second
change-passphrase dialog and gocryptfs and the wallet key's pipes (openssl →
`kwallet-query -w`; `kwallet-query -r` → `gocryptfs -passwd -config`), which
the helper never reads, the version line of `gocryptfs -version`, and the
`qdbus6` answers. gocryptfs runs with `-q -nosyslog`
(and `-init -q`, so the master key is never printed). Every child's arguments
are checked against an allow-list before it starts: gocryptfs gets only
`-init`, `-passwd`, `-q`, `-nosyslog`, `-extpass`, and `-config` (each only in
its phase, plus a lone `-version`) and absolute paths; `-config` only with the
one slot path the helper computed (`wallet.conf` to mount, `wallet.conf.new`
to re-key); the `-extpass` program is kdialog, the relay, or exactly
`kwallet-query --folder Hearthside --read-password encrypted-chat-folder
<wallet>` (never the staging entry); `fusermount3` only `-u <mountpoint>`;
kdialog only the new-passphrase dialog; `openssl` only `rand -hex 32`;
`kwallet-query` only `--read-password` or `--write-password` of
`encrypted-chat-folder` or `encrypted-chat-folder.new` in folder
`Hearthside`; `qdbus6` only the kwalletd6 methods `isEnabled`, `localWallet`,
`keyDoesNotExist`, `open`, `removeEntry`, `close` with our folder, those two
entries and app id, and the Secret Service properties
`Label` and `Locked`. Anything else (for example `-passfile`, `-masterkey`,
`-ko`, `-o`, another `-config`, `-fsname`, `-zerokey`, `-fusedebug`) and any
argument containing `allow_` outside an `-extpass` value is refused with
`os-error`. `gocryptfs -passwd`, and with it
the Python extpass relay, runs with every `PYTHON*` variable removed and
`PYTHONNOUSERSITE=1` and `PYTHONSAFEPATH=1` set. A tool that `PATH` finds only
through a relative entry counts as missing.

Before mounting, under the lock and with nothing mounted, the bare mountpoint
must be empty. The only leftovers removed there are `web/applet-<N>-g<G>/`
folders you own (a chat that kept writing into the in-memory directory after
another widget locked the folder); they are deleted without following links.
Anything else there gives `mount-failed` and nothing is deleted.

A failure is `{"ok":false,"error":"<code>"}`:

| Code | Meaning |
| --- | --- |
| `missing-tool` | A needed tool is missing or could not start |
| `no-runtime-dir` | `XDG_RUNTIME_DIR` is unusable (see above) |
| `exists` | `create`: a folder already exists |
| `absent` | `unlock`, `change-passphrase`: no folder yet (or gocryptfs found no folder) |
| `damaged` | `create`, `unlock`, `change-passphrase`: the cipher directory holds files but no `gocryptfs.conf`; delete it with `destroy` |
| `cancelled` | The passphrase window was cancelled, or the passphrase was empty |
| `wrong-passphrase` | gocryptfs rejected the passphrase |
| `init-failed` | `create`: gocryptfs could not initialise the folder |
| `mount-failed` | `create`, `unlock`: the mount did not come up, or the mountpoint holds something other than leftover profile folders |
| `not-verified` | The folder is not unlocked, or the mount failed the checks above (a failed check after mounting unmounts it again) |
| `stale-mount` | A dead mount could not be cleaned up |
| `busy` | The lock file is held by another job, the folder is mounted elsewhere, or `lock` found it still in use |
| `not-locked` | `change-passphrase`, `destroy`, `purge`: the folder is unlocked (for `purge`: anything is mounted there) |
| `symlink`, `not-directory`, `not-owned` | Something in the way is a symlink, not a folder, or not yours; nothing is followed or deleted |
| `not-set-up` | `unlock --method wallet`, `auto-unlock`: no usable wallet slot, or the wallet has no entry for it (gocryptfs exit 11 with `-config`, too) |
| `wallet-disabled` | Wallet jobs: KWallet is disabled (`isEnabled` = false) |
| `wallet-closed` | `auto-unlock`: the wallet is locked (or its state is unknown); nothing was run |
| `wallet-failed` | Wallet jobs: `kwallet-query` exited non-zero or did not finish within 120 s (denied, cancelled, locked and not answered, no entry), a `qdbus6` query failed or timed out, `localWallet` is not a valid name, or (gocryptfs exit 9 with the wallet extpass) an empty value; for `remove-key`, `destroy`, `purge`: the wallet entry may remain |
| `wallet-mismatch` | `unlock --method wallet`, `auto-unlock`: the wallet's value does not open the slot (gocryptfs exit 12); set the wallet up again |
| `wallet-write-failed` | `add-key`: openssl failed, gocryptfs could not write the slot (exit 24 or another code) or the slot could not be saved |
| `os-error` | Any other failure, including unexpected errors (no traceback is printed) |

The plasmoid accepts only these codes (plus `empty-passphrase`, which the
helper does not currently send because gocryptfs reports an empty passphrase
like a cancel). Any other code becomes `failed`; a non-zero exit or output
that is not one of the replies above becomes `bad-reply`. Every failure keeps
the Chat tab on its card or in the private session; nothing is saved.

gocryptfs exit codes are mapped as measured with gocryptfs 2.6.1: 12
`wrong-passphrase`; 9 `cancelled`; 10 `mount-failed`; 6 `absent` (`exists`
for `create`); 11 `absent`; 19 `busy` when a mount is present afterwards,
else `mount-failed`; anything else `init-failed` (`create`), `mount-failed`
(mount), or `os-error` (`change-passphrase`). With the wallet slot (mount
with `-config`): 9 `wallet-failed`, 12 `wallet-mismatch`, 11 `not-set-up`,
10 and 19 `mount-failed`, 6 `absent`, anything else `mount-failed`. Re-keying
the slot (`add-key`): 9 `cancelled` (the current-passphrase window), 12
`wrong-passphrase`, 6 and 11 `absent`, 24 and anything else
`wallet-write-failed`.

### How the plasmoid uses the wallet jobs

`chatVaultUnlock` (String, default `passphrase`; only the exact word `wallet`
means KDE Wallet, anything else is the passphrase) is written only by
Settings → General (`cfg_chatVaultUnlock`), and only after the helper answered:
`add-key --method wallet` succeeded → `wallet`; `remove-key --method wallet`
succeeded (or no slot was set up) → `passphrase`. The Chat tab uses the wallet
only when the setting is `wallet` **and** `status` says `"wallet":"set-up"`
(`ChatStorage.effectiveUnlockMethod`); a missing or unknown `wallet` field
counts as `unavailable`. `auto-unlock` is queued only once, from main.qml's
`Component.onCompleted`, behind a `status`, and runs only when that status is
`locked` with `wallet: set-up` and nothing locked it on purpose
(`ChatStorage.dropStep`); `wallet-closed` and `busy` from it show nothing. The
card's **Unlock** runs `unlock --method wallet` (or the passphrase), **Use
passphrase instead…** runs `unlock`, and after `wallet-mismatch` or
`not-set-up` **Set up KDE Wallet again…** runs `add-key --method wallet`,
then the wallet unlock.

## Prompt library helper

Saved prompts and personas live only inside the unlocked encrypted folder
(`src/hearthside/core/promptstore.py`):

- `<mount>/library/` (`0700`) holds `prompt-<id>.txt` and `persona-<id>.txt`
  (`0600`, UTF-8) and `personas.json` (`0600`, `{"<model>": <persona id>}`,
  model names and integers only). Ids are integers from 1, unique across both
  kinds, never reused below the highest id in use.
- At most 100 items; a prompt holds at most 32000 characters, a persona 8000.
- Nothing is written anywhere else. While the folder is locked every command
  fails with `locked`.

| Command | Does | Success reply |
| --- | --- | --- |
| `--prompts list` | Returns every saved item, sorted by id, and the per-model persona defaults (only those pointing at a listed persona). Files that are not regular files of yours, symlinks, odd names, invalid UTF-8 or over the cap are skipped | `{"ok":true,"items":[{"id":N,"kind":"prompt"\|"persona","text":"..."}],"personas":{"<model>":N}}` |
| `--prompts add --kind prompt\|persona` | Opens `kdialog --title Hearthside --textinputbox "<fixed label>"` (no initial text) with its stdout on a new `O_EXCL` file inside `library/`; files it as the next id | `{"ok":true,"id":N}` |
| `--prompts replace --id N` | The same dialog; replaces item `N` (same id and kind) | `{"ok":true,"id":N}` |
| `--prompts remove --id N` | Deletes item `N` (and every persona default pointing at it) | `{"ok":true}` |
| `--prompts set-persona --model <name> --id N` | Makes persona `N` the default for `<name>` | `{"ok":true}` |
| `--prompts set-persona --model <name> --none` | Clears `<name>`'s default (nothing saved is success) | `{"ok":true}` |

The dialog's answer is accepted only when kdialog exits 0 and the file is not
empty: one trailing newline (kdialog adds it) is dropped; strict UTF-8, no
NUL, not only whitespace, within the character cap. The helper does not hold
the vault lock while the dialog is open (only before and after), so other
widgets keep working; its open file keeps the mount busy, so a Lock at that
moment answers `busy` until the dialog is closed. Afterwards the library must
still be the same directory in a verified mount.

`list` is the one reply that carries user text (plan D53); nothing is logged
and no reply carries a path. Rules: `--kind` only and always with `add`;
`--id N` (1 to 2147483648) with `replace` and `remove`, or with
`set-persona` instead of `--none`; `--model` only and always with
`set-persona`, matching `^[A-Za-z0-9._:/+-]{1,200}$` and not starting with
`-`. Otherwise argparse exits 2.

Errors (`{"ok":false,"error":"<code>"}`): `locked` (nothing is mounted),
`not-verified` (a mount failed the checks, or vanished while the dialog was
open), `cancelled` (Cancel, or an empty answer), `too-long`, `not-text`
(invalid UTF-8 or NUL), `full` (100 items, or 200 persona defaults),
`absent` (no such item, or `set-persona --id` names a prompt), `busy` (vault
lock held), `missing-tool` (no kdialog), `os-error` (anything else, including
a symlink or non-folder in place of `library/`).

The plasmoid builds these commands only in `PromptLibrary.js`
(`promptsCommand`), with the same `env HEARTHSIDE_RUN=… HEARTHSIDE_APPLET=…
python3 -P -m hearthside` prefix, from fixed words, ids (1 to 2147483648) and a
model name checked against the helper's rule; anything else builds nothing.
main.qml runs one job at a time, lists the library whenever the folder turns
unlocked and after every change, and drops its copy (and queued changes) as
soon as the folder is not unlocked. Replies are reduced by `parseList` (at
most 100 items with a valid id, kind and non-empty text within its cap,
duplicates dropped; defaults kept only for valid model names pointing at a
listed persona) and `parseChange`. The text is shown as plain text only and
never written to the configuration.

## Dropped file helper

For a single local `file://` URL dropped on the Ollama chat, the plasmoid
runs `--read-dropped <HEX>`, where `<HEX>` is the path's UTF-8 bytes as
lowercase hex (`^([0-9a-f]{2}){1,4096}$`; the decoded path must be absolute
and contain no NUL; otherwise argparse exits 2). It stands alone like the
other helper modes (`src/hearthside/core/droppedfile.py`). It runs no
program and writes nothing.

- `lstat` first: anything but a regular file (symlink in the last
  component, FIFO, device, directory) is refused before it is opened. Then
  `O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC|O_NOCTTY`; the opened file must be
  the same one.
- Size 1 to 131072 bytes (`/proc` files report 0). A file that grows while
  being read is refused.
- Before the open, the file's filesystem type comes from
  `/proc/self/mountinfo` (the mounts of its device number; for a device no
  line names, the longest mount point above its real path). proc, sysfs,
  efivarfs, securityfs, pstore, debugfs, tracefs, cgroup, cgroup2, bpf,
  configfs, fusectl, devpts, mqueue, hugetlbfs, binfmt_misc, autofs,
  rpc_pipefs and nsfs are refused (`not-file`). Unreadable mountinfo, or no
  mount for the file, is `os-error` (nothing is read).
- Strict UTF-8, no NUL, at most 32000 characters.

Reply: `{"ok":true,"text":"..."}` (the text only, never the path), or
`{"ok":false,"error":E}` with `absent` (missing), `unreadable` (permission),
`not-file` (not a regular file, a symlink, empty, a kernel pseudo-filesystem,
or a bad argument), `too-large`, `not-text`, `too-long`, `os-error`.

The plasmoid runs it only for a drop of exactly one URL on the Ollama chat or
the panel icon, with `PromptLibrary.hexPath(url)`: `file:///` URLs only (no
host, query or fragment), percent-decoded as UTF-8, absolute, no NUL, at most
8192 hex digits; anything else is "Drop text, not files." and runs nothing.
`parseDropped` accepts only a string of at most 32000 characters without NUL;
that text then goes through `OllamaChat.dropText` into the message box and is
never sent by itself.

## Port owner helper

Before the built-in Ollama chat loads the model list or sends a message, the
plasmoid asks the helper who listens on the Ollama port, so a prompt never
goes to another user's program that took the port while Ollama was down.
Local web UI runs the same check on its port before its page is created and
before each main-frame navigation to this computer
(`plasmoid/contents/ui/LocalOwnerCheck.qml`). The command is built only in
`plasmoid/contents/ui/OllamaChat.js` (`ownerCommand`), from integers only:

    env HEARTHSIDE_RUN=<n> HEARTHSIDE_APPLET=<applet> python3 -P -m hearthside --port-owner <port>

The env words only keep DataSource names unique (as for the Stay signed in
helper); the helper ignores them. The command carries no prompt, model name,
or address, touches no credentials, and makes no network request.

- Reads only `/proc/net/tcp` and `/proc/net/tcp6`; opens no socket and starts
  no program (`src/hearthside/core/portowner.py`).
- Counts sockets in state LISTEN (`0A`) on `<port>` whose local address a
  connection to `127.0.0.1`, `localhost`, or `[::1]` can reach: `127.0.0.1`,
  `0.0.0.0`, `::1`, `::`, `::ffff:127.0.0.1`, `::ffff:0.0.0.0`. Other bind
  addresses (for example `127.0.0.2` or a LAN address) and connections in any
  other state are ignored.
- Trusted owners are your own uid, root (uid 0), and the system `ollama`
  account when that user exists (`getpwnam("ollama")`).
- A missing `/proc/net/tcp6` (kernel without IPv6) counts as no IPv6 sockets.
  A missing or unreadable `/proc/net/tcp`, an unreadable `tcp6`, or any line
  that does not parse gives `unreadable`, never `none`.

Reply (one JSON object on stdout, exit 0):

| Reply | Meaning |
| --- | --- |
| `{"ok":true,"owner":"none"}` | Nothing listens there |
| `{"ok":true,"owner":"self"}` | Every listener is yours |
| `{"ok":true,"owner":"system"}` | Every listener is trusted and at least one is root or `ollama` (the packaged `ollama.service`) |
| `{"ok":true,"owner":"other"}` | At least one listener belongs to another user |
| `{"ok":false,"error":"unreadable"}` | The tables could not be read or parsed, or anything unexpected happened |

Replies never contain uids, user names, inodes, or addresses. `<port>` is a
plain decimal integer from 1 to 65535 (at most 5 digits; no sign, spaces, or
underscores), and `--port-owner` cannot be combined with any other option;
otherwise argparse exits 2 with a usage message on stderr and prints nothing on
stdout. The plasmoid sends (or, for Local web UI, loads) only for `self` or `system`
and fails closed on everything else, including a non-zero exit, any other
output (`bad-reply`), or no answer within 15 seconds. For Local web UI, a
server bound only to another loopback address (for example `127.0.0.2`) is
not seen and so reads as `none`: nothing loads.
The check cannot tell your own programs apart, and a listener could change in
the milliseconds between the check and the request; see `docs/privacy.md`.

## Usage history helper

Opt-in (plan D70, off by default): the plasmoid records only while
`usageHistoryEnabled` is on, and clears the history when it is turned off
(`src/hearthside/core/usagehistory.py`). No network, no credentials, no
provider data other than percentages.

- `$XDG_DATA_HOME` (when absolute, else `~/.local/share`)`/hearthside/usage-history/`
  (`0700`) holds `history.json` and `history.lock` (both `0600`). Every folder
  is opened through `webdata.open_base` / `open_child_dir` (no symlinks,
  owner checked).
- `history.json` is `{"history_version":1,"series":[{"provider_id","metric_id","points":[[t,used],...]}]}`.
  `t` is the start of a UTC hour bucket (a multiple of 3600), `used` an
  integer percent used from 0 to 100. A corrupt, oversized (over 256 KiB),
  duplicate-key or wrong-version file counts as empty; series of pairs the
  catalog no longer has, and odd points, are skipped.
- Writes hold an `flock` on `history.lock` (2 s wait, else `busy`), write an
  `O_EXCL|O_NOFOLLOW` temporary, fsync it, `os.replace` it with directory
  descriptors and fsync the folder. Each write keeps only the last 7 days
  (the current bucket and the 168 before it, so at most 169 points per
  series), drops future points, keeps one value per bucket (the last wins)
  and writes nothing when the bytes would not change. Temporaries a crashed
  writer left are deleted under the lock.

| Command | Does | Success reply |
| --- | --- | --- |
| `--usage-history read` | The last 7 days; creates nothing (no folder, no lock file) | `{"ok":true,"history_version":1,"bucket_seconds":3600,"now":<int>,"series":[...]}` |
| `--usage-history record --sample a.b=N,...` | Stores the sample in the current bucket, then replies as `read` | the same |
| `--usage-history clear` | Deletes `usage-history/` and everything in it (nothing there is success) | `{"ok":true}` |

`series` entries are `{"provider_id","metric_id","points":[[t,used],...]}` in
catalog order, points ascending, empty series left out. The sample is
comma-joined pairs, each a fullmatch of
`[a-z_]{1,32}\.[a-z_]{1,32}=(100|[1-9]?[0-9])`, at most 64, none twice, each
a catalog (provider, supported metric) pair other than `extra_usage`;
anything else is `bad-sample` and writes nothing. `--sample` is required with
`record` and refused otherwise, and `--usage-history` stands alone; otherwise
argparse exits 2.

Errors (`{"ok":false,"error":"<code>"}`, exit 0): `bad-sample`, `symlink` (a
folder or file of ours is a symlink), `not-directory`, `not-owned`, `busy`,
`os-error` (anything else). Replies never carry a path or text.
`scripts/install.sh --uninstall-web-data` also runs `--usage-history clear`
once the chat sign-in data is gone.

## Settings backup helper

Settings → General → Backup saves the widget's settings to one fixed file and
reads them back (plan D71; no file dialog;
`src/hearthside/core/settingsbackup.py`). No network, no credentials.

- `$XDG_CONFIG_HOME` (when absolute, else `~/.config`)`/hearthside/settings-backup.json`.
  The folder is `0700` and made only by `export` (which also tightens a safe
  existing one to `0700`); the file is `0600`, written as an
  `O_EXCL|O_NOFOLLOW` temporary, fsynced and `os.replace`d with directory
  descriptors. Export refuses to replace a symlink or someone else's file.
- Format: `{"format":"hearthside-settings","version":1,"config_schema":3,"exported_at":"YYYY-MM-DDTHH:MM:SSZ","settings":{...}}`,
  exactly these keys. Another `version` or `config_schema` is `unsupported`.

| Command | Success reply |
| --- | --- |
| `--settings-backup status` | `{"ok":true,"exists":false}` or `{"ok":true,"exists":true,"exported_at":"..."}` |
| `--settings-backup export --data <hex>` | `{"ok":true,"saved":N,"dropped":M}` |
| `--settings-backup import` | `{"ok":true,"exported_at":"...","settings":{...},"dropped":M}` |

`<hex>` is lowercase hex of a UTF-8 JSON object of settings (even length, at
most 131072 characters). `--data` is required with `export` and refused
otherwise; `--settings-backup` stands alone. `status` and `import` create
nothing and check the whole file the same way.

One check (`validate_settings`) runs on the export input and on the import
file. JSON with NaN, Infinity, overflowing numbers or duplicate keys is
refused. Only `BACKUP_KEYS` are kept, in that order; unknown keys,
`EXCLUDED_KEYS` (`chatSignInStorage`, `chatProfileGeneration`,
`chatAutoLockMinutes`, `chatVaultUnlock`, `chatSiteZoom`,
`configSchemaVersion`, `initialSetupComplete`, `usageHistoryEnabled`) and
known keys with a value the widget would not store are dropped and counted
in `dropped`. Strings hold at most 4096 characters (`chatCustomUrls` 32768)
and no C0/C1 controls or lone surrogates; a boolean is never an integer.

| Key | Accepted value |
| --- | --- |
| `trackedProviders` | JSON array of catalog provider ids, none twice |
| `providerMetrics` | JSON object `{providerId: [metric ids of that provider]}`, none twice |
| `providerOrder` | `""` or a JSON array like `trackedProviders` |
| `usageMode` | `remaining` or `used` |
| `refreshInterval` | 60, 300, 900, 1800 or 3600 |
| `tooltipShowsUsage`, `usageCompact`, `alertLowEnabled`, `alertResetEnabled`, `chatKeepOpen`, `showUsageTab`, `showChatTab` | boolean |
| `tooltipMetrics` | `""` or a JSON object like `providerMetrics` |
| `usageWarnPercent` / `usageCriticalPercent` | 50 to 90 / 55 to 95, steps of 5 |
| `usageNormalColor`, `usageWarnColor`, `usageCriticalColor` | `""` or `#rrggbb` (kept in lower case) |
| `alertLowPercent` | 5, 10, 15, 20, 25, 30, 40 or 50 |
| `chatSites` | JSON array of `claude chatgpt grok gemini copilot mscopilot local ollama`, none twice |
| `chatDefaultSite` | one of those ids |
| `chatOllamaUrl` | `http://<127.0.0.1\|localhost\|[::1]>:<1-65535>` exactly as the widget stores it |
| `popupDefaultTab` | `chat` or `usage` |
| `popupSize` | `compact`, `normal` or `large` |
| `shortcutOpens` | `popup`, `chat`, `ollama` or `usage` |
| `panelRing` | `off`, `auto` or a catalog `provider.metric` pair (not `extra_usage`) |
| `middleClickOpens` | `refresh`, `usage`, `ollama` or a web site id |
| `chatCustomUrls` | JSON object `{webSiteId: address}` (D74); every address non-empty and valid under the rules of `ChatSites.validateCustomUrl` (https only, http only for Local and only to loopback, at most 2048 UTF-16 units, no whitespace or control characters, no user info, no local address except for Local). One bad entry drops the whole key |

JSON settings are stored re-serialized as `JSON.stringify` writes them, in
catalog order. An export that keeps nothing is `bad-data` (an existing
backup is never replaced with an empty one).

Errors (`{"ok":false,"error":"<code>"}`, exit 0): `absent` (no backup;
`import` only), `invalid` (not a backup file), `unsupported` (another
version or schema), `too-large` (file over 64 KiB, or an export that would
be), `bad-data` (export input), `symlink`, `not-owned`, `unsafe-mode` (the
folder or file is group- or other-writable), `os-error`. Replies never carry
a path. The widget re-checks every imported value before it applies it.
