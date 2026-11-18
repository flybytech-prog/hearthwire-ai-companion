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

Added sites (`chatUserSites`, written only by Settings → Chat and a backup
Replace; task 005):

- A JSON array of at most 200 entries (`MAX_USER_SITES`; with the 7 built-ins
  that is the web data helper's 207-id cap), at most 458752 UTF-16 units,
  each exactly `{"id","name","url"}`, written in that key order. Any other key
  (`local`, `site_hosts`, `auth_hosts`, `icon`...) makes the entry invalid.
- `id`: `user-` and 8 lower-case hex digits, random (`ChatSites.newUserSiteId`),
  unique, never reused while its delete is owed.
- `name`: stored trimmed, 1 to 40 UTF-16 units, no C0/C1 controls, lone
  surrogates, `<`, `>`, `&`, Default_Ignorable_Code_Point characters
  (U+00AD, U+034F, U+061C, U+115F–1160, U+17B4–17B5, U+180B–180F,
  U+200B–200F, U+202A–202E, U+2060–206F, U+3164, U+FE00–FE0F, U+FEFF,
  U+FFA0, U+FFF0–FFF8, U+1BCA0–1BCA3, U+1D173–1D17A, U+E0000–E0FFF),
  U+FFF9–FFFB, U+2800, U+2028–2029, or general category Cf or Co; at least
  one letter or digit (general category L* or N*). Both categories come from
  tables generated from Unicode 16.0 and shared by both ports
  (`FORMAT_PRIVATE_RANGES`, `LETTER_DIGIT_RANGES` in `ChatSites.js` and
  `settingsbackup.py`, kept equal by a test); unassigned (Cn) code points are
  not checked. And not a built-in name, `Ollama` or another
  added site's name in any case (code-point lower case, no confusable
  matching).
  Codes, first failure wins: `name-empty`, `name-too-long`, `name-chars`,
  `name-taken`.
- `url`, in order: `url-empty`, `too-long` (2048), `whitespace`,
  `url-chars` (outside 0x21–0x7E or one of `` " \ < > ` { } | ^ ``),
  `userinfo`, `malformed` (no scheme), `http-not-allowed`, `scheme`,
  `malformed` (`parseUrl`), `loopback-not-allowed` (`isLocalAddress`),
  `ip-literal` (any IPv4 literal, even a public one, until local sites
  arrive). What is left is a public DNS name, `ChatSites.addressClass` →
  `"public"`.
- The site is rebuilt from the name and address on every use
  (`ChatSites.effectiveSite`): no site or sign-in hosts, its exact host only,
  never local. Every navigation call takes `userSites`; an added id without
  its entry resolves to nothing and is blocked. `ChatSites.parseUserSites`
  is ok only when the whole value is valid; only an ok read may remove sites,
  build the `prune --known` list or prune zoom entries.
- Navigation for added sites: main-frame `https:` to any public host loads
  (redirects, sign-in); a clicked link off its host goes to the "Open in your
  browser" prompt; main frame, subframes and new windows block this computer
  (as above) and every IPv4 literal in 10/8, 172.16/12, 192.168/16,
  169.254/16 or 0/8 in any spelling, plus unreadable bracketed literals. New
  windows: a clicked dialog opens as the sign-in overlay, anything else
  `https:` goes to the browser. The built-in rules are unchanged (a recorded
  golden table, `tests/qml/ChatSitesGolden.js`).
- An address on another host gives the site a new id; the old id is removed.
  On import, `SettingsBackup.importPlan` (`renewMovedSites`) gives a backup
  entry whose id the page has on another exact host a fresh id (never one of
  the page's, the backup's, the applied value's or an owed delete's) and
  follows it in `chatSites`, `chatSiteOrder`, `chatDefaultSite` and
  `middleClickOpens`; the confirmation shows Removes plus Adds. At runtime
  main.qml (`chatUserSiteHostsSeen`) removes an id that is a valid entry of
  both the previous and the current read with another exact host, on any
  read (ok or not); ChatWebView's `applyCustomUrls` blanks such a view and
  `home()` refuses the new host, so the old profile never loads it. An id
  that was unreadable (its host never known) and becomes readable counts as
  moved too (`chatUserSiteUnreadableSeen`), and on import such an id (in the
  applied raw text but unreadable on the page, `tools.unreadableIds`) is
  renewed (L-2b, fails closed). Not caught: an edit made while the widget
  isn't running (the old host isn't stored).
- A damaged `chatUserSites` (not ok): Settings → Chat disables add, edit,
  remove and reorder for added sites, and its removal warning counts every
  `user-[0-9a-f]{8}` id in the raw applied text the page lacks.
- Removal (main.qml `chatRemoveUserSites`, after Apply; absent ids only on an
  ok read, moved ids as above): with
  Stay signed in the ids join `chatPendingSiteClears` first, then the Chat tab
  drops their views and profiles, and each folder goes through the same
  `wait` and `remove-site --site <id>` path as Clear <site> data (with its
  busy retry); while locked the delete waits for the next unlock.

`chatSiteOrder`: `""` (built-ins, added sites, Ollama) or a JSON array of
site ids (built-in, added, `ollama`), each once. Unknown ids are dropped and
missing ones appended in the default order, a missing `ollama` last. The
order the user set is written as `""` when it equals the default order.

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
  the profile of the site that opened it, and closes when the page closes it.
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
entities and tables are never recognized. A block over 300 words (or 4000
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
running.", `other` "Another user's program is using port N. Hearthwire won't
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
`env HEARTHWIRE_RUN=<n> HEARTHWIRE_APPLET=<applet> python3 -P -m hearthwire ...`
(`-P`: Python doesn't put the working folder on the module path).
`HEARTHWIRE_RUN` is a run counter and `HEARTHWIRE_APPLET` the widget id; together
they keep command names unique across widgets and settings pages so replies are
told apart. The helper ignores both.

### Layout

- Encrypted folder (gocryptfs cipher directory):
  `$XDG_DATA_HOME/hearthwire/vault/` (`~/.local/share` when `XDG_DATA_HOME` is
  unset or not absolute).
- Mount: `$XDG_RUNTIME_DIR/hearthwire/vault/`. `XDG_RUNTIME_DIR` must be set,
  absolute, a real directory, owned by you and mode `0700`, else the reply is
  `no-runtime-dir`. The bare mountpoint is mode `0700` while mounting and
  `0500` while locked.
- Profiles: `<mount>/web/applet-<N>-g<G>/` is the generation folder, one per
  widget id `N` and profile generation `G` (`chatProfileGeneration`, raised by
  Clear chat data). It is only a container: each chat site keeps its own
  profile in `site-<id>/` inside it, so no two sites share cookies, storage,
  cache or service workers. Folders are mode `0700`.
- Site ids: exactly one of the built-in ids `claude`, `chatgpt`, `grok`,
  `gemini`, `copilot`, `mscopilot`, `local`, or an added site's `user-`
  followed by 8 lowercase hex digits (`user-[0-9a-f]{8}`). `ollama` is never a
  site id. Ids are matched exactly, never trimmed or by prefix; the grammar is
  prefix-free, so two ids never share a folder.
- KDE Wallet key slot: `$XDG_DATA_HOME/hearthwire/vault-keys/wallet.conf`
  (folder `0700`, file `0400`, outside the cipher directory). It is a copy of
  `gocryptfs.conf` whose master key is wrapped with a random key
  (`openssl rand -hex 32`) kept in your KDE Wallet (`localWallet`, normally
  `kdewallet`), folder `Hearthwire`, entry `encrypted-chat-folder`. The
  passphrase slot (`gocryptfs.conf`) is never changed by it and stays the
  recovery slot. While being set up the copy is `wallet.conf.new` (gocryptfs
  itself writes `wallet.conf.new.tmp`) and its key is staged in the entry
  `encrypted-chat-folder.new`; while the new slot is swapped in, the previous
  one is `wallet.conf.old`. Leftovers of all of these are cleared.
- Lock file: `$XDG_RUNTIME_DIR/hearthwire/vault.lock` (`flock`). Jobs that
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
| `--web-data prepare --store encrypted --applet N --generation G [--sites IDS]` | Creates `web/applet-N-gG/` inside the verified mount and, for each id in `IDS`, `site-<id>/` inside it (all `0700`; an existing folder is reset to `0700` and keeps its contents). Without `--sites` only the generation folder is made. First, if the generation folder's root holds anything but `site-<id>` entries (rollback evidence, see below), it deletes everything in it, site folders first, then makes the listed ones empty. Run when a site is first opened | `{"ok":true}` |
| `--web-data prune --store encrypted --applet N --generation G --known IDS` | Inside `applet-N-gG/` only, deletes every entry except a `site-<id>/` folder whose id is in `IDS`: unknown or removed sites, and a symlink or file wearing a known name (it is unlinked, never followed). If the root holds anything but `site-<id>` entries (rollback evidence, see below), it deletes every entry, known site folders included. Never touches other generations, other applets or anything else in `web/`. A missing `web/` or generation folder is success and nothing is created. The widget runs it only when its site list reads as valid, after each unlock's prepare and after an added site is removed | `{"ok":true}` |
| `--web-data remove-site --store encrypted --applet N --generation G --site ID` | Deletes `applet-N-gG/site-<ID>` only (a symlink there is unlinked, never followed); a missing folder is success. Right before the delete it scans `/proc/<pid>/fd` and `/proc/<pid>/maps` of every process whose real, effective, saved and fs uids (the four `Uid:` fields of `/proc/<pid>/status`) all are the caller's; every other process (other users', and root's through sudo or a setuid program, which can read the folder anyway) is skipped, and so is any process whose fd folder, fd links or maps can't be read (vanished, non-dumpable, with file capabilities like kwin_wayland, or in another user namespace: a normal Plasma desktop always has some, review-4 H1). It replies `busy` and deletes nothing while any scanned process has a file in that folder open or mapped (resolved path equal to the folder or below it; a ` (deleted)` suffix is stripped once). Then, covering processes the scan can't see, it checks every entry named `LOCK` below the folder (Chromium's LevelDB lock; walked with directory fds, never following a link, at most 16 levels and 200000 entries, else `os-error`). A regular file is opened `O_RDWR\|O_NOFOLLOW\|O_NONBLOCK` without creating it and gets a non-blocking `fcntl` write lock and then a non-blocking `flock`, each released at once. A held lock, a `LOCK` entry that isn't a regular file (FIFO, directory, socket, device or symlink; never followed), or a `LOCK` or folder that can't be opened (anything but gone), is `busy` too. If `/proc` can't be listed it replies `os-error` and deletes nothing. A process may still open a file between the scan and the delete; the widget asks only after the site's views and profile are gone. Used by "Clear <site> data" after the site's profile is gone | `{"ok":true}`; `{"ok":false,"error":"busy"}` while a file in the folder is open |
| `--web-data remove --store encrypted --applet N [--keep G]` | Deletes this widget's `applet-N-g*` folders, except generation `G` when given; nothing there is success. Unchanged by per-site folders: deleting a generation folder deletes its `site-*` folders with it | `{"ok":true}` |
| `--web-data purge` | Deletes the encrypted folder and `vault-keys/` for `scripts/install.sh --uninstall-web-data`, then the wallet entry when `vault-keys/` held a wallet slot, kwallet-query and qdbus6 are there and the wallet holds it; refuses while anything is mounted at the mountpoint or from the cipher directory (also checks `/run/user/<uid>`); runs no other tool | `{"ok":true,"removed":[...]}` with any of `"vault"`, `"vault-keys"`, `"wallet-entry"` in that order (empty when nothing was there) |

**Rollback evidence.** Since every site has its own profile, nothing this
version makes lives at the root of `applet-N-gG/`; only an older version that
opened the folder as its one shared profile (1.0.1 or earlier, after a
downgrade) writes there. Any root name that isn't `site-` plus a valid site id
counts. Then `prepare` and `prune` delete every entry with the safe delete
(`remove_entry`): all site entries first and the root leftovers last, so a
refused entry (`not-owned`) keeps the evidence and the next run tries again.
Every site then starts signed out, and no account from before the downgrade
comes back (review REV-M1). `prepare` does this too because it runs before any
saved profile opens; prune alone would come after one.

#### How the widget uses the web-data commands

Every chat site has its own Qt WebEngine profile. Its storage name
`applet-<N>-g<G>-<id>` (only a label; the path is given explicitly) and its
folder `<runtime>/hearthwire/vault/web/applet-<N>-g<G>/site-<id>` are built
only by `ChatStorage.siteProfileName` and `siteProfilePath`, which return ""
for anything that isn't a site id. The `prepare`, `prune` and `remove-site`
builders in `ChatStorage.webDataCommand` return "" when any id fails the
grammar; the step then fails and no command runs. main.qml runs the steps one
at a time:

- **Unlock:** once `--vault status` says `unlocked` and saved sign-ins are
  wanted, the order is `remove-site` for each id in `chatPendingSiteClears`,
  then `prepare --sites`, then (after the first prepare of this generation
  since the unlock) `remove --keep G` and `prune --known`. `prepare --sites`
  covers the sites the shown panes need (the current site, and the second
  pane's in split view), never one whose delete is still owed, and the
  prepare reply never counts a pending id as prepared. `remove --keep G`
  deletes older generations, including the shared profile from 1.0.1 or
  earlier; `prune --known` takes every built-in site id (added sites join in
  a later version). These steps show no card. A site gets a saved profile only
  after its folder was prepared in the current generation; until then its view
  waits.
- **A shown site without a folder** (a site switch, split view): one more
  `prepare --sites`, at most one at a time, again without pending ids.
- **Clear <site> data** with saved sign-ins.
  Clear <site> data first records the site in the widget's settings, then deletes its saved sign-in; if the delete fails, the site stays closed and is deleted at the next unlock (also after a restart) before it can open again, and Clear chat data, once its delete succeeds, settles every such pending delete.
  main.qml first stores the id in `chatPendingSiteClears` ("" or
  comma-separated site ids, written with `ChatStorage.pendingClearsText` and
  read strictly with `parsePendingClears`, which drops anything that isn't a
  site id) and calls `writeConfig()` when the configuration offers it. Only if
  the stored value took does ChatView destroy the site's views and then its
  profile. main.qml drops the site from the prepared set, waits
  `chatProfileCloseWait` (1 s) and runs one `remove-site --site <id>` for each
  owed id not yet tried in this round. An ok reply removes the id from the
  list, and the site is prepared again when shown. A failure marks it tried
  and shows `site-remove-failed`; the id stays in the list, so the site stays
  closed (never prepared) until a later unlock's `remove-site` works, also
  after a Plasma restart. In memory mode no helper runs: destroying the
  profile is the whole clear.
- **Clear chat data:** a new generation, wait, `remove`, then `lock`. Deleting
  the generation folders deletes every `site-*` folder, so an ok `remove`
  reply empties `chatPendingSiteClears`; a failed one leaves it as it is.
- **The one-time move** (`chatProfileLayout` 0): at start the widget raises
  `chatProfileGeneration` once and stores 1 (Encrypted on a widget already set
  up: the Chat tab's notice shows until **Got it** stores 2) or 2. The keep
  step after the next unlock's prepare then deletes the old shared profile's
  folder.

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
`openssl`). `qdbus6` is looked up on `PATH` as `qdbus6` first, then as
`qdbus-qt6` (Fedora's `qt6-qttools` installs only that name); either is
called and reported as `qdbus6`, held to the same argument contract, and,
like every tool, must resolve to an absolute path. `openssl` is needed only by `add-key` (`remove-key`, `destroy`
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
4. `keyDoesNotExist(<wallet>, Hearthwire, encrypted-chat-folder)` (answers
   while locked, without a prompt); true → `not-set-up`.
5. `gocryptfs -q -nosyslog -config <slot> -extpass kwallet-query -extpass
   --folder -extpass Hearthwire -extpass --read-password -extpass
   encrypted-chat-folder -extpass <wallet> <cipher> <mount>`, then the usual
   mount checks.

Setting up (`add-key`) is staged, so a failed re-setup (Cancel, a wrong
passphrase, a wallet error) leaves an existing slot and entry working:

1. After the same step 1, `gocryptfs.conf` is copied to `wallet.conf.new`.
2. `openssl rand -hex 32` writes into `kwallet-query --folder Hearthwire
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
`org.kde.KWallet.open(<wallet>, 0, Hearthwire)` → handle,
`removeEntry(handle, Hearthwire, <entry>, Hearthwire)`,
`close(handle, false, Hearthwire)`, and checked with `keyDoesNotExist`.
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

- `--web-data`, `--vault`, `--prompts`, `--read-dropped`, `--port-owner`,
  `--install-info`, `--usage-history`, `--settings-backup`, and `--migrate`
  cannot be combined with each other or with `--json`, `--providers`,
  `--catalog`, or `--detect`.
- `--method passphrase|wallet` needs `--vault unlock`, `add-key`, or
  `remove-key`; `add-key` and `remove-key` need `--method wallet`; `unlock`
  defaults to `passphrase`.
- `--store`, `--applet`, `--generation`, `--keep`, `--sites`, `--known`, and
  `--site` need `--web-data` `prepare`, `prune`, `remove-site`, or `remove`.
  `prepare`, `prune`, and `remove-site` need `--store`, `--applet`, and
  `--generation` and refuse `--keep`; `remove` needs `--store` and `--applet`
  and refuses `--generation`; `purge` takes none of them.
- `--sites` is only for `prepare` (optional), `--known` only for `prune`
  (required), `--site` only for `remove-site` (required). `IDS` is 1 to 207
  comma-separated site ids (see Layout) with no duplicates, no spaces and no
  empty items; `ID` is one site id. Any other id, including `ollama`, is a
  usage error and nothing is touched.
- `N` and `G` are plain decimal integers from 0 to 2147483648 (at most 10
  digits; no sign, leading zero, spaces, or underscores), and so is the
  `--keep` and `--id` value. `--applet 0` is refused for `--web-data` too
  (Plasma applet ids start at 1), as for `--usage-history`.
- Every option may be given at most once, under any of its names or
  abbreviations (`--site a --site b`, `--gen 0 --generation 1`); a repeat is a
  usage error that names the option but never its value.
- `--usage-history read|record|clear` need `--applet N` with N from 1 to
  2147483648 (the widget's Plasma applet id; 2147483648 is the
  hearthwire-hyprland app's and refused for the widget, see App mode); only `clear --all` takes no
  `--applet`, and `--all` is refused anywhere else (and in app mode, see App
  mode). `--settings-backup export` needs `--applet N` (1 or more); `status`
  and `import` accept it and ignore it, except that the other front end's id
  is `applet-not-found` (App mode). `--store`, `--generation` and `--keep`
  stay `--web-data` only.
- `--data` is refused with every command (audit M1: settings must never be
  in argv, which every local user can read through `/proc`). The refusal
  names the option but never echoes its value.

### Replies and errors

Every job prints one JSON object on stdout and exits 0 (143 after a stop
signal, see Signal handling below). Replies never contain
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
to re-key); the `-extpass` program is kdialog (or, in app mode,
`hearthwire-askpass` at its fixed path), the relay running one of those, or exactly
`kwallet-query --folder Hearthwire --read-password encrypted-chat-folder
<wallet>` (never the staging entry); `fusermount3` only `-u <mountpoint>`;
kdialog only the new-passphrase dialog; `openssl` only `rand -hex 32`;
`kwallet-query` only `--read-password` or `--write-password` of
`encrypted-chat-folder` or `encrypted-chat-folder.new` in folder
`Hearthwire` (the one-time migration has its own rule, in the last section of
this page; it never applies to `-extpass`); `qdbus6` only the kwalletd6 methods `isEnabled`, `localWallet`,
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
| `busy` | The lock file is held by another job, the folder is mounted elsewhere, `lock` found it still in use, or `--web-data remove-site` found a file in the site's folder still open (nothing deleted) |
| `not-locked` | `change-passphrase`, `destroy`, `purge`: the folder is unlocked (for `purge`: anything is mounted there) |
| `symlink`, `not-directory`, `not-owned` | Something in the way is a symlink, not a folder, or not yours; nothing is followed and it is not deleted. `--web-data prune` and `remove` stop there; entries before it (in name order) may already be gone |
| `not-set-up` | `unlock --method wallet`, `auto-unlock`: no usable wallet slot, or the wallet has no entry for it (gocryptfs exit 11 with `-config`, too) |
| `wallet-disabled` | Wallet jobs: KWallet is disabled (`isEnabled` = false) |
| `wallet-closed` | `auto-unlock`: the wallet is locked (or its state is unknown); nothing was run |
| `wallet-failed` | Wallet jobs: `kwallet-query` exited non-zero or did not finish within 120 s (denied, cancelled, locked and not answered, no entry), a `qdbus6` query failed or timed out, `localWallet` is not a valid name, or (gocryptfs exit 9 with the wallet extpass) an empty value; for `remove-key`, `destroy`, `purge`: the wallet entry may remain |
| `wallet-mismatch` | `unlock --method wallet`, `auto-unlock`: the wallet's value does not open the slot (gocryptfs exit 12); set the wallet up again |
| `wallet-write-failed` | `add-key`: openssl failed, gocryptfs could not write the slot (exit 24 or another code) or the slot could not be saved |
| `legacy-data` | `create`, `unlock`, `auto-unlock`, `add-key`, `--web-data purge`, `--usage-history record`, `--settings-backup export`: the previous version's data folder still exists and only the installer may move it; nothing else was done. The Chat tab and settings page show one fixed message, and `scripts/install.sh --uninstall-web-data` stops with one |
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

### Signal handling

Task 011c (`src/hearthwire/core/termination.py`): the clean stop below
applies when the helper gets SIGTERM, SIGHUP or SIGINT. The Hyprland app
sends SIGTERM for its time limit, a disconnected or destroyed source, and
when it quits; a logout sends SIGTERM too. The Plasma widget's executable
engine instead deletes the process of a dropped source, which is SIGKILL
(closing the settings window, removing the widget, plasmashell quitting).

Task 011d (`src/hearthwire/core/worker.py`) covers the widget too: a SIGKILL
of the helper still stops the step. From the command line (`python3 -m
hearthwire`, the console script), `--vault` and `--prompts` run in a worker
process:

- The process the front end started (the front) forks the worker (no exec)
  right after it checked the arguments and the front end, and only if it
  has a single thread and libc's `prctl` is there; otherwise the job runs
  in the front as before. It opens nothing and never takes the vault lock.
  SIGTERM, SIGHUP and SIGINT are blocked from just before the fork. The
  front forwards them to the worker (one ignored at start stays ignored in
  the front) and then unblocks them, so one that came meanwhile, or one
  blocked at start, is forwarded too. It waits for the worker and exits with
  its exit status; its old mask comes back afterwards. stdout and stderr are
  inherited, so the reply and the exit status are unchanged.
- The worker first sets `PR_SET_DUMPABLE` to 0 (no core dump, no same-user
  ptrace or `/proc/<pid>/mem` read; a failure there is ignored). A SIGTERM
  ignored at start is set back to its default, so the death signal always
  stops the job (fail closed); SIGHUP and SIGINT ignored at start stay
  ignored. It sets `PR_SET_PDEATHSIG` to SIGTERM and reads it back with
  `PR_GET_PDEATHSIG`. If that fails (a seccomp filter, say), the worker runs
  nothing and exits with 120, and the front runs the job itself, as when
  `prctl` is missing or the process has a second thread; a stop that came
  meanwhile ends the run with exit 143 and no reply. Then the worker checks
  that the front is still its parent; if not, it exits at once and runs
  nothing. Then it records stop signals, unblocks them (its children get
  the old mask without them) and runs the job, holding the vault lock
  itself. A stop that came before the job's own signal handling is kept, so
  the job stops at its first check.
- When the front is killed (SIGKILL included), the kernel sends the worker
  SIGTERM, and the stop below runs there. A forwarded signal followed by
  that one is the same stop. The front never exits before its worker is
  reaped, so no worker outlives a front that exited on its own.
- The app kills the front 1 s after its SIGTERM when it quits, or 3 s after
  it on a forced stop. That kill now reaches only the front: the worker
  keeps going, including the 10 s finish wait below, and holds the vault
  lock until its step is finished or undone. A job started meanwhile waits
  for the lock (or replies `busy` after 5 s, as for any held lock).

Every command starts with SIGCHLD set to its default. For `--vault` and
`--prompts` only, the helper (the worker, when split) records SIGTERM,
SIGHUP and SIGINT (a signal ignored at start stays ignored) and sets SIGCHLD
to its default for the run. It acts on the signal at the next point where it
waits: for a dialog's or kwallet-query's child, for the vault lock, or in the
change-passphrase poll loop. After a stop signal no child that can wait for
the user is started any more, and neither is the mount after an `-init` that
finished. `fusermount3`, `gocryptfs -version` and `cmp`
are short and never cut short. Neither are the `qdbus6` calls, including a
wallet `open` that may wait for KDE Wallet's own prompt (up to 120 s): the
job then waits for that answer and finishes normally.

- Every child that can wait for the user (gocryptfs `-init`, mount and
  `-passwd`, the new-passphrase dialog, kwallet-query, openssl, the prompt
  text box) runs in its own process group. An unfinished step's group gets
  SIGTERM, 0.3 s, then SIGKILL.
  - The group is signalled only while its leader is confirmed unreaped
    (`waitid` with `WNOWAIT`), so the id is still ours.
  - It is signalled only when the child is that group's leader; otherwise
    only the child is signalled.
  - A child that was already reaped is never signalled. Nothing else is ever
    signalled: not the helper's group, not a front end.
- A child that already exited is only reaped. A gocryptfs that mounted and
  exited 0 leaves its daemon (the open folder) alone, and so does a daemon
  from an earlier unlock.
- A step that already has everything it needs gets up to 10 s to finish
  instead of being cut off:
  - `-passwd` once the new-passphrase dialog returned 0 (while that dialog
    is still open, the stop is immediate);
  - `-init` once it has started writing the folder;
  - add-key's `kwallet-query -w` of the real entry, once it has started.
  A finished change or add-key then replies as usual. A finished `-init`
  leaves a complete, locked folder, and no mount is started after it.
- The unfinished step is undone:
  - a mount that came up before gocryptfs reported it is unmounted and the
    mountpoint sealed (0500);
  - a folder that an unfinished `create` made is removed (only while still
    empty). An `-init` cut off at its first write can leave only
    `gocryptfs.conf.tmp`; with no `gocryptfs.conf` next to it, that regular
    file of yours is removed first (without following links), so the folder
    is never left `damaged`;
  - `add-key`: `wallet.conf.new` is removed. A stop while the staged key is
    read for the copy to the real entry, or a `-w` that does not finish within
    the 10 s, puts the old `wallet.conf` back, as after other failures. The
    staged entry is then deleted. A `-w` that timed out may still have
    written the real entry, so run `add-key` again if the wallet unlock fails.
  - the prompt's pending file is removed;
  - `passwd.status` is cleared.
- Entry deletes (`remove-key`, `destroy`, the add-key cleanup) skip their
  overwrite after a stop, or end it when the signal comes while it waits, and
  still delete through `qdbus6`. A `remove-key` stopped this way finishes and
  replies as usual.
- The reply is then `{"ok":false,"error":"interrupted"}` with exit status
  143, whichever signal it was. A signal that arrives after the last such
  wait lets the job finish its short file work and print its normal reply
  (exit 0). Other commands keep Python's default signal behaviour.
- Neither front end reads a stopped job's reply, so `interrupted` is not
  in the plasmoid's list of codes. Should one ever be read, the non-zero exit
  makes it `bad-reply`.

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
(`src/hearthwire/core/promptstore.py`):

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
| `--prompts add --kind prompt\|persona` | Opens `kdialog --title Hearthwire --textinputbox "<fixed label>"` (no initial text) with its stdout on a new `O_EXCL` file inside `library/`; files it as the next id | `{"ok":true,"id":N}` |
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
a symlink or non-folder in place of `library/`). A stop signal while the
text box is open closes it, removes the pending file and replies
`interrupted` with exit status 143 (see Signal handling, under the Stay
signed in helper).

The plasmoid builds these commands only in `PromptLibrary.js`
(`promptsCommand`), with the same `env HEARTHWIRE_RUN=… HEARTHWIRE_APPLET=…
python3 -P -m hearthwire` prefix, from fixed words, ids (1 to 2147483648) and a
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
other helper modes (`src/hearthwire/core/droppedfile.py`). It runs no
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

    env HEARTHWIRE_RUN=<n> HEARTHWIRE_APPLET=<applet> python3 -P -m hearthwire --port-owner <port>
    env HEARTHWIRE_RUN=<n> HEARTHWIRE_APPLET=<applet> python3 -P -m hearthwire --port-owner <port> --address <ip>

The env words only keep DataSource names unique (as for the Stay signed in
helper); the helper ignores them. The command carries no prompt, model name,
or web address, touches no credentials, and makes no network request.

The `--address` form (task 006, round 2) is for a chat site you added by a
home-network IP address. `<ip>` is exactly that site's host:
- a canonical dotted quad in `10.0.0.0/8`, `172.16.0.0/12` or `192.168.0.0/16`
  (`192.168.1.20`);
- or a bracketed, lower-case, short-form IPv6 literal in `fc00::/7` outside
  `fd00:ec2::/32` (`[fd00::20]`).

Anything else (loopback, public, link-local, upper case, leading zeros, a
zone id, IPv6 without brackets) exits 2. If `<ip>` is not one of this
computer's own addresses, a connection to it leaves the machine, so no local
listener can take it: the reply is `remote`. If it is one, another local user
could listen on it, so the usual owner check applies to the listeners on
`<ip>` and on the wildcard. Loopback sites, Ollama and Local web UI keep the
plain form.

- Reads only `/proc/net/tcp` and `/proc/net/tcp6`, and with `--address`
  also `/proc/net/fib_trie`, `/proc/net/if_inet6` and `/proc/net/ipv6_route`;
  opens no socket and starts no program (`src/hearthwire/core/portowner.py`).
- With `--address`, this computer's addresses come from the kernel's tables:
  - IPv4: every `LOCAL` route in `fib_trie`, in every table. A `/N` local
    route makes its whole range local, so `ip route add local` (AnyIP)
    counts.
  - IPv6: the addresses in `if_inet6`, and every `ipv6_route` route flagged
    `RTF_LOCAL` (`0x80000000`).
  - There is no bind test: with `net.ipv4.ip_nonlocal_bind` any user can
    bind any address, and that says nothing about where a connection goes.
  - Packet-filter rules are not read. A NAT, port-forwarding or
    transparent-proxy rule (`iptables`/`nftables` DNAT or REDIRECT) can send
    traffic for a `remote` address to a local listener. Only root can set up
    such a rule, and root is already a trusted owner (uid 0 counts as
    `system`), so this is accepted and documented in `docs/privacy.md`.
  - A missing or unreadable table, a line of another shape, or a `fib_trie`
    without a single `LOCAL` route gives `unreadable`.
- Counts sockets in state LISTEN (`0A`) on `<port>` whose local address a
  connection to `127.0.0.1`, `localhost`, or `[::1]` can reach: `127.0.0.1`,
  `0.0.0.0`, `::1`, `::`, `::ffff:127.0.0.1`, `::ffff:0.0.0.0`. Other bind
  addresses (for example `127.0.0.2` or a LAN address) and connections in any
  other state are ignored. With `--address <ip>`, the counted addresses are:
  - for an IPv4 `<ip>`: `<ip>` and `0.0.0.0`, plus `::`, `::ffff:<ip>` and
    `::ffff:0.0.0.0` in `tcp6` (dual-stack sockets);
  - for an IPv6 `<ip>`: `<ip>` and `::`.
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
| `{"ok":true,"owner":"remote"}` | Only with `--address`: the address is not this computer's, so no local listener can answer |
| `{"ok":false,"error":"unreadable"}` | The tables could not be read or parsed, or anything unexpected happened |

Replies never contain uids, user names, inodes, or addresses. `<port>` is a
plain decimal integer from 1 to 65535 (at most 5 digits; no sign, leading
zero, spaces, or underscores), `--port-owner` and `--address` may each be
given only once, `--address` needs `--port-owner`, and they can't be
combined with any other option;
otherwise argparse exits 2 with a usage message on stderr and prints nothing on
stdout. The plasmoid sends (or, for Local web UI and the sites on this
computer, loads) only for `self` or `system`, and a home-network site also
for `remote`, and fails closed on everything else, including a non-zero exit, any other
output (`bad-reply`), or no answer within 15 seconds. For Local web UI, a
server bound only to another loopback address (for example `127.0.0.2`) is
not seen and so reads as `none`: nothing loads.
The check cannot tell your own programs apart, and a listener could change in
the milliseconds between the check and the request; see `docs/privacy.md`.

## Usage history helper

Opt-in (plan D70): the widget runs it only while **Settings → General →
Privacy → Usage history** (`usageHistoryEnabled`, off by default) is on, and
to delete the history (`src/hearthwire/core/usagehistory.py`). No network, no
credentials, no provider data other than percentages.

- `$XDG_DATA_HOME` (when absolute, else `~/.local/share`)`/hearthwire/usage-history/`
  (`0700`) holds one `applet-<N>.json` per widget (`N` its Plasma applet id;
  the on/off choice is per widget, audit L1) and one shared `history.lock`
  (all `0600`). Every folder is opened through `webdata.open_base` /
  `open_child_dir` (no symlinks, owner checked). The single shared
  `history.json` of earlier builds is never read; every `clear` deletes it.
- `applet-<N>.json` is `{"history_version":1,"series":[{"provider_id","metric_id","points":[[t,used],...]}]}`.
  `t` is the start of a UTC hour bucket (a multiple of 3600), `used` an
  integer percent used from 0 to 100. A corrupt, oversized (over 256 KiB),
  duplicate-key or wrong-version file counts as empty, and so does one whose
  arrays and objects nest deeper than 6 (the format nests 5: document >
  series > entry > points > point). The depth is counted before the JSON is
  parsed, by a linear scan that skips string contents, so the limit doesn't
  depend on the Python build's recursion handling. Series of pairs the
  catalog no longer has, and odd points, are skipped.
- Writes hold an `flock` on `history.lock` (2 s wait, else `busy`), write an
  `O_EXCL|O_NOFOLLOW` temporary, fsync it, `os.replace` it with directory
  descriptors and fsync the folder. Each write keeps only the last 7 days
  (the current bucket and the 168 before it, so at most 169 points per
  series), drops future points, keeps one value per bucket (the last wins)
  and writes nothing when the bytes would not change. Temporaries a crashed
  writer left (of any widget) are deleted under the lock.
- `read` prunes too (audit L2): when the file holds points older than 7
  days, future points or anything it cannot use, it takes the lock, reads
  again, and rewrites the file exactly as `record` does, or deletes it when
  nothing within 7 days is left. With nothing to prune it takes no lock and
  creates nothing. When the lock stays held for 2 s the prune waits for a
  later `read`; the reply is the same pruned series.

| Command | Does | Success reply |
| --- | --- | --- |
| `--usage-history read --applet N` | Widget N's last 7 days (pruning the file as above) | `{"ok":true,"history_version":1,"bucket_seconds":3600,"now":<int>,"series":[...]}` |
| `--usage-history record --applet N --sample a.b=N,...` | Stores the sample in widget N's current bucket, then replies as `read` | the same |
| `--usage-history clear --applet N` | Deletes `applet-N.json`, the old shared `history.json` and stray temporaries; the folder too once only the lock is left in it (nothing there is success) | `{"ok":true}` |
| `--usage-history clear --all` | Deletes `usage-history/` and everything in it (nothing there is success) | `{"ok":true}` |

`series` entries are `{"provider_id","metric_id","points":[[t,used],...]}` in
catalog order, points ascending, empty series left out. The sample is
comma-joined pairs, each a fullmatch of
`[a-z_]{1,32}\.[a-z_]{1,32}=(100|[1-9]?[0-9])`, at most 64, none twice, each
a catalog (provider, supported metric) pair other than `extra_usage`;
anything else is `bad-sample` and writes nothing. `--sample` is required with
`record` and refused otherwise, `--applet N` (1 to 2147483648) is required
except with `clear --all`, and `--usage-history` stands alone; otherwise
argparse exits 2.

Errors (`{"ok":false,"error":"<code>"}`, exit 0): `bad-sample`, `symlink` (a
folder or file of ours is a symlink), `not-directory`, `not-owned`, `busy`
(`record`, `clear`; never `read`), `legacy-data` (`record` only: the previous
version's data still waits for the installer), `os-error` (anything else).
Replies never carry a path or text. `scripts/install.sh --uninstall-web-data`
also runs `--usage-history clear --all` once the chat sign-in data is gone.

### How the plasmoid uses it

`UsageHistory.historyCommand` builds
`env HEARTHWIRE_RUN=<run> python3 -P -m hearthwire --usage-history <op> --applet <Plasmoid.id>`,
plus `--sample <checked sample>` for `record`; anything odd gives no command. Steps
run one at a time from a queue, so a `clear` never overtakes a running
`record`.

- `read` once per Plasma session, when history is on and the Usage tab is
  shown.
- `record` after a successful usage refresh, at most once every 15 minutes
  (`RECORD_MIN_GAP_MS`), while history is on and the Usage tab is shown. The
  sample holds every catalog reading (not `extra_usage`) of each tracked
  provider whose status is `ok` and that is not a kept stale reading, with
  `used_percent` rounded and clamped to 0..100. An empty sample records
  nothing.
- `clear` when history is turned off. The widget first sets
  `usageHistoryClearOwed` to true, drops what it showed and queued, and sets
  it back to false only after `{"ok":true}`. `busy` is retried up to three
  times, three seconds apart (`CLEAR_MAX_TRIES`, `CLEAR_RETRY_MS`); any other
  failure, or the last `busy`, shows a fixed notice in the Usage tab. While
  the flag is set and history is off, the widget runs `clear` again at
  Plasma start and each time the popup opens. Turning history on clears the
  flag. **Delete usage history** on the settings page runs its own `clear`
  and shows a fixed result text.

`UsageHistory.parseReply` checks a whole reply: exit code 0, at most
257 KiB of stdout, exactly the keys above, `history_version` 1,
`bucket_seconds` 3600, catalog pairs only, none twice, points ascending hour
buckets inside the last 7 days with `used` 0..100, and a known error code.
Anything else is `invalid` and the shown series are dropped. Only
`legacy-data` has its own notice; the helper's text is never shown. Each
reading's sparkline (`usageSparkline`, standard layout only) is drawn from
these points.

## Settings backup helper

Saves the widget's settings to one fixed file and reads them back (plan D71;
no file dialog; `src/hearthwire/core/settingsbackup.py`). The widget runs it
from **Settings → General → Backup**, and `export` also from the panel menu's
**Back up settings** and from Automatic backup (task 007). No network, no
credentials.

Export saves the **applied** settings: the helper reads them itself, read
only, from Plasma's own config (`src/hearthwire/core/appletconfig.py`), so
nothing the user typed is ever in argv (audit M1). Changes not yet applied
are not in the backup. In app mode it reads the hearthwire-hyprland app's
settings file instead (App mode, below).

- `$XDG_CONFIG_HOME` (when absolute, else `~/.config`)`/plasma-org.kde.plasma.desktop-appletsrc`,
  else `plasmawindowedrc` next to it. The second file is tried when the
  first is missing, has no widget N, or its widget N is another plugin
  (plasmawindowed ids are small, so the desktop often has, say, a pager with
  the same id). In the desktop file the group is
  `[Containments][C][Applets][N][Configuration][General]` for any containment
  C, and the widget's group `[Containments][C][Applets][N]` must say
  `plugin=io.github.flybytechprog.hearthwire`. plasmawindowed keeps its
  widget at the top level, so `plasmawindowedrc` also takes `[Applets][N]`
  and `[Applets][N][Configuration][General]` (the containment form too); the
  desktop file never takes the top-level form. The settings of a widget of
  another plugin are never read. N names exactly one widget in a file (Plasma
  reads the group name as a number, so `021` and `21` are the same widget);
  two are `applet-not-found`, never a guess, and the other file is not tried
  then. When both files have our widget N, the desktop file wins.
- The rc file is opened `O_RDONLY|O_NOFOLLOW|O_NONBLOCK` and never written; a
  symlink, a non-regular file, another user's file or one over 4 MiB is
  `settings-unreadable` (no fallback to the other file).
- Lines are trimmed as KConfig trims them; `#` comments and lines without
  `=` are skipped; the last line of a key wins. Values are decoded exactly as
  `KConfigIniBackend::printableToString` does (`\s \t \n \r \\ \xHH`; `\;` and
  `\,` stay as written; a bad `\x` gives `x`; any other escape keeps its
  backslash). Keys with a suffix (`key[de]`, `key[$e]`, `key[$i]`) are
  ignored, never trusted, and a malformed group header starts a group that
  is not read.
- A key that is not there takes its `main.xml` default from
  `appletconfig.CONFIG_ENTRIES` (kept equal to `main.xml` by
  `tests/test_applet_config_sync.py`). A value that is not UTF-8, or a Bool
  or Int in a spelling KConfig never writes (Bool: `true on yes 1` /
  `false off no 0`, any case; Int: an optional sign and up to 10 digits), is
  dropped and counted like any other bad value.

- `$XDG_CONFIG_HOME` (when absolute, else `~/.config`)`/hearthwire/settings-backup.json`.
  The folder is `0700` and made only by `export` (which also tightens a safe
  existing one to `0700`); the file is `0600`, written as an
  `O_EXCL|O_NOFOLLOW` temporary, fsynced and `os.replace`d with directory
  descriptors. Export refuses to replace a symlink or someone else's file,
  and first deletes `settings-backup.json.<16 hex>.tmp` files a crashed
  export left (audit I1; a symlink there is unlinked, never followed).
  `scripts/install.sh --uninstall-web-data` keeps the backup (it holds no
  sign-ins) and says so, with its path, when it exists (audit I2).
- Format (version 2, task 007; written compact in this key order, ending in a newline):
  `{"format":"hearthwire-settings","version":2,"config_schema":3,"exported_at":"YYYY-MM-DDTHH:MM:SSZ","settings":{...},"sha256":"<64 hex>","signature":"<64 hex>"}`.
  Import also reads version 1, `{"format":…,"version":1,"config_schema":3,"exported_at":…,"settings":{…}}`
  (1.0.x and 1.1 pre-release builds); export always writes version 2.
  Exactly these keys per version (a version 1 file with either digest, or a
  version 2 file without one, is `invalid`); each digest is 64 lowercase hex
  digits (`fullmatch`, else `invalid`). `version` and `config_schema` must be
  integers (not booleans, else `invalid`); a `version` other than 1 or 2, or
  a `config_schema` other than 3, is `unsupported`.
- Canonical content (what both digests cover; M-2): `CONTENT_KEYS =
  ("format", "version", "config_schema", "exported_at", "settings")` as
  parsed from the file (before `validate_settings` drops anything),
  `json.dumps({k: doc[k] for k in CONTENT_KEYS}, ensure_ascii=False,
  sort_keys=True, separators=(",", ":"), allow_nan=False)` in UTF-8. So
  whitespace and key order don't count. A lone surrogate (a `\ud800`
  escape) has no UTF-8 form and is `invalid`.
  - `sha256 = hashlib.sha256(content).hexdigest()`;
  - `signature = hmac.new(key, b"hearthwire-settings-backup\x00" + content, hashlib.sha256).hexdigest()`
    (the prefix is `SIGN_CONTEXT`, domain separation).
  - Both are compared with `hmac.compare_digest`, the checksum first. A
    fixed test vector in `tests/test_settingsbackup.py` pins the bytes.
- `origin` (import only; informational, M-6: it never changes which
  settings are kept; M-8: once an `other` or `unsigned` import is applied,
  the next export signs those settings with this install's key):

  | File | Result |
  | --- | --- |
  | version 2, checksum and signature match this install's key | `"origin":"this-computer"` |
  | version 2, checksum doesn't match | `{"ok":false,"error":"damaged"}` from `status` and `import` (refused, M-4) |
  | version 2, checksum matches; signature doesn't, or the key is missing or unusable | `"origin":"other"` |
  | version 1 | `"origin":"unsigned"` |

- Backup key (M-1): `$XDG_DATA_HOME` (when absolute, else
  `~/.local/share`)`/hearthwire/backup-key`, exactly 32 bytes from
  `secrets.token_bytes(32)`, raw, mode `0600`. The folder is opened with
  `webdata.open_base` / `open_child_dir` (no symlink, ours) and must not be
  group- or other-writable; only `export` makes it (`0700`), after
  `refuse_legacy_data`, and tightens a safe existing one to `0700` with
  `fchmod` on the opened descriptor (round 3, LOW-B: no other user can then
  open it and hold its lock; a failed `fchmod` is `key-unusable`). `import`
  and `status` never change a mode. Only `export`
  makes the key: an `O_CREAT|O_EXCL|O_NOFOLLOW` temporary
  `backup-key.<16 hex>.tmp` at `0600`, fsynced, then `link()`ed to
  `backup-key` (never replaces; on `EEXIST` the existing key is read and
  used, so two exports at once share one key), the temporary unlinked and
  the folder fsynced. Export first deletes stale `backup-key.<16 hex>.tmp`
  files (a symlink is unlinked, never followed). Export holds an exclusive
  `flock` on the backup folder's descriptor for its whole write, and on the
  key folder's while it reads or makes the key (round 2, LOW-1; the key
  folder's descriptor, and so its lock, is closed before the backup is
  written, when the key is already final), so a concurrent export never
  deletes another's live temporary or sees a key mid-link. When both are the
  same folder (`XDG_DATA_HOME` equal to `XDG_CONFIG_HOME`; compared by
  `(st_dev, st_ino)` of the opened descriptors), the lock is taken once
  (round 3, LOW-A). Import takes the key folder's lock shared, `status`
  none. No lock file is made; a wait over
  10 s (`LOCK_WAIT_SECONDS`) is `os-error`, and a file system without flock
  runs unlocked (still fail-closed). Read (`export` and
  `import`; `status` never reads it, and `import` only after the checksum
  passed) with `O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC|O_NOCTTY`; it must be
  a regular file, ours, with no group or other bits, exactly 32 bytes and one
  name (`st_nlink == 1`); an open refused with `ELOOP`, `EACCES`, `ENXIO` or
  `EISDIR` counts as unusable too. A crash between `link()` and the unlink
  of the temporary leaves the key with two names (`st_nlink` 2), so import
  gives `other` until the next export, whose stale cleanup removes the
  temporary first, so that export uses the key as before (INFO-A).
  Otherwise `export` is `key-unusable` and `import` gives `other`; the key
  is never replaced or repaired (M-5). No rotation. The key is never in
  argv, the environment, stdout, stderr, a reply, the backup or a log.
  `scripts/install.sh --uninstall-web-data` and package removal leave it
  (M-9).

| Command | Success reply |
| --- | --- |
| `--settings-backup status [--applet N]` | `{"ok":true,"exists":false}` or `{"ok":true,"exists":true,"exported_at":"..."}` |
| `--settings-backup export --applet N` | `{"ok":true,"saved":N,"dropped":M}` |
| `--settings-backup import [--applet N]` | `{"ok":true,"exported_at":"...","settings":{...},"dropped":M,"origin":"this-computer"\|"other"\|"unsigned"}` |

`--applet N` (1 to 2147483648, the widget's Plasma applet id) is required
with `export`; `status` and `import` accept it and ignore it, except that the
other front end's id is `applet-not-found` (App mode). `--data` is
refused everywhere; `--settings-backup` stands alone. `status` and `import`
create nothing (no folder, no key) and check the whole file the same way,
the checksum included; only `import` checks the signature. The argv is
unchanged by task 007: no key, path or setting is ever on the command line.

One check (`validate_settings`) runs on the applied settings export reads
(every `BACKUP_KEYS` key, defaults included) and on the import file. JSON with NaN, Infinity, overflowing numbers or duplicate keys is
refused, and so is JSON whose arrays and objects nest deeper than 4, both the
file and the JSON a setting holds (both nest at most 2). The depth is counted
before parsing, by a linear scan that skips string contents, so the limit
doesn't depend on the Python build's recursion handling. Only `BACKUP_KEYS` are kept, in that order; unknown keys,
`EXCLUDED_KEYS` (`chatSignInStorage`, `chatProfileGeneration`,
`chatAutoLockMinutes`, `chatVaultUnlock`, `chatSiteZoom`,
`configSchemaVersion`, `initialSetupComplete`, `usageHistoryEnabled`,
`usageHistoryClearOwed`, `chatProfileLayout`, `chatPendingSiteClears`) and
known keys with a value the widget would not store are dropped and counted
in `dropped`. Strings hold at most 4096 characters (`chatCustomUrls` 32768,
`chatUserSites` 458752 UTF-16 units) and no C0/C1 controls or lone
surrogates; a boolean is never an integer.

A second pass checks the keys that may name an added site: `chatSites`,
`chatSiteOrder`, `chatDefaultSite` and `middleClickOpens` may name only the
added ids of the `chatUserSites` the same settings keep (none when that key
is absent or dropped). Any other `user-` id drops that whole key.

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
| `chatSites` | JSON array of `claude chatgpt grok gemini copilot mscopilot local ollama` and the kept added ids, none twice |
| `chatDefaultSite` | one of those ids |
| `chatSiteOrder` | `""` or a JSON array like `chatSites` |
| `chatUserSites` | JSON array of added sites under the rules above (`settingsbackup.user_site_name_error`, `user_site_url_error`, the same codes as `ChatSites.js`); one bad entry, extra key, repeated id or name, more than 200 entries or more than 458752 UTF-16 units drops the whole key. Re-serialized with the keys in `id, name, url` order |
| `chatOllamaUrl` | `http://<127.0.0.1\|localhost\|[::1]>:<1-65535>` exactly as the widget stores it |
| `popupDefaultTab` | `chat` or `usage` |
| `popupSize` | `compact`, `normal` or `large` |
| `shortcutOpens` | `popup`, `chat`, `ollama` or `usage` |
| `panelRing` | `off`, `auto` or a catalog `provider.metric` pair (not `extra_usage`) |
| `middleClickOpens` | `refresh`, `usage`, `ollama`, a web site id or a kept added id |
| `chatCustomUrls` | JSON object `{webSiteId: address}` (D74); every address non-empty and valid under the rules of `ChatSites.validateCustomUrl` (https only, http only for Local and only to loopback, at most 2048 UTF-16 units, no whitespace or control characters, no user info, no local address except for Local). One bad entry drops the whole key |

`BACKUP_KEYS` and `EXCLUDED_KEYS` together are every `main.xml` key, with no
overlap (`tests/test_settings_backup_sync.py`). `backupAutoExport` and
`backupRestoreAt` (task 007) are excluded, so a restore never changes backup
behavior.

The helper is stricter than the widget about custom addresses: it rejects
every C0 and C1 control character in them, while
`ChatSites.validateCustomUrl` refuses only JavaScript whitespace, C0 and
U+007F. An address the widget accepted with U+0085 or another C1 character
therefore drops the whole `chatCustomUrls` key on export.

JSON settings are stored re-serialized as `JSON.stringify` writes them, in
catalog order. `dropped` on export counts the backup keys whose applied
value failed; excluded keys are never read. An export that keeps nothing is
`bad-data` (an existing backup is never replaced with an empty one).

Errors (`{"ok":false,"error":"<code>"}`, exit 0): `absent` (no backup;
`import` only), `invalid` (not a backup file), `unsupported` (another
version or schema), `too-large` (file over 512 KiB, or an export that would
be), `damaged` (`status` and `import`: a version 2 file whose `sha256`
doesn't match its content), `key-unusable` (`export` only: the backup key or
its folder is unsafe, see above; nothing was exported), `bad-data` (export:
no applied setting passed), `symlink`, `not-owned`,
`unsafe-mode` (the backup folder or file is group- or other-writable),
`legacy-data` (`export` only: the previous version's data still waits for the
installer), `applet-not-found` (`export` only: no rc file has exactly one
widget of ours with that id), `settings-unreadable` (`export` only: an rc file
is a symlink, not a regular file, not yours, or over 4 MiB), `os-error`.
Replies never carry a path.

### How the plasmoid uses it

`SettingsBackup.backupCommand` builds
`env HEARTHWIRE_RUN=<run> python3 -P -m hearthwire --settings-backup <op> --applet <Plasmoid.id>`;
anything odd gives no command. One step runs at a time.

- `status` when the General page opens and after each export, for the
  "Last backup" line.
- `export` on **Export**, and after an inline **Replace** confirmation when
  a backup exists (or its status isn't known to be `absent`). main.qml also
  runs exactly `SettingsBackup.backupCommand("export", root.backupRun,
  Plasmoid.id)` for the menu's **Back up settings** and for Automatic backup
  (`backupAutoExport`, about 3 s after an Apply that changed a backup key,
  and once when it is turned on); it never runs `status` or `import`.
- **Restore settings…** writes `backupRestoreAt` (`String(Date.now())`) and
  opens Settings; General runs `status` then `import` when that request is
  at most 60 s old (`SettingsBackup.restoreRequested`).
  The helper saves the applied settings it reads itself; changes not yet
  applied do not count, so the page asks for Apply first.
- `import` on **Import**. `SettingsBackup.importPlan` checks every value
  again with the widget's own rules (the catalog, `ChatSites.siteIds`,
  `ChatSites.validateCustomUrl`, `OllamaChat.checkedAddress`, the ring
  pairs, and `ChatSites.validateUserSite` / `serializeUserSites` with the
  same cross-key check, the added ids taken only from the import's own
  `chatUserSites`), drops what fails, and adds that to the helper's
  `dropped`. `origin` is shown as one line ("Made by Hearthwire on this
computer." or, for `other` and `unsigned`, one warning) and is never passed
to `importPlan` or `addressChanges`. The confirmation lists address changes, added sites ("Adds
  <name> (<host>)") and removed ones ("Removes <name> and deletes its site
  data when you apply") as plain text, at most 8 lines and a count. It also
  drops both levels when the warning level isn't below the critical one, and
  both tab switches when they would hide both tabs. Only
  after an inline **Replace** does `applyBackup` set the page's `cfg_` values
  for backup keys (never an excluded key); Apply on the General page saves
  them. A plan with nothing to apply shows a fixed message instead.

`SettingsBackup.parseReply` accepts exit code 0, at most 512 KiB + 1024
characters of stdout (`MAX_REPLY_CHARS`),
exactly the keys of each reply above and a known error code; anything else
is `bad-reply`. Every code is shown as fixed text, never the helper's own.

## Install info helper

A script install (`scripts/install.sh`: `pip install --user`,
`kpackagetool6 -i`) puts the helper in the Python user site and the widget in
`$XDG_DATA_HOME/plasma/plasmoids`. Both win over a system package, so after a
package is installed an older script copy keeps running. The widget runs
`hearthwire --install-info` once per start (main.qml) and once per open of
Settings → General to notice that, and to pick the package names of the
distribution family for its install hints
(`src/hearthwire/core/installinfo.py`). The command is built only by
`InstallInfo.command(run, applet, retry)` in
`plasmoid/contents/ui/InstallInfo.js`, as
`env HEARTHWIRE_RUN=<run> HEARTHWIRE_APPLET=<applet>` followed by one of two
fixed forms:

1. `python3 -P -s -m hearthwire --install-info` (`retry` not `true`): the
   first run. `-s` leaves the user site off `sys.path`, so the system package
   answers even when an older home-folder copy (which doesn't know the
   option) would be imported; the reply still reports that copy, since the
   directories are checked directly.
2. `python3 -P -m hearthwire --install-info` (`retry === true`): run once,
   only when the first run exited non-zero (`InstallInfo.needsRetry(exitCode,
   retried)`: `exitCode !== 0 && retried !== true`), for example because no
   system package is installed. A script install alone then still reports
   its distro family.

A first run that exits 0 is never retried, whatever it printed. The retry's
result is final: its exit code and stdout go through the same strict
`InstallInfo.parseReply`, so a failing retry (such as a copy too old to know
the option) means unknown, and there is never a third run. The retried flag is
never cleared, so a widget start or a page open makes at most two runs. Only
the exit code and stdout are read, never stderr. `scripts/install.sh
--remove-script-install` runs the checkout's copy to see whether a package is
installed before it removes the script copy.

Read only: no network, no credentials, nothing written or started, and no
Hearthwire copy is imported (each directory is checked with
`importlib.machinery.PathFinder.find_spec`). It stands alone like the other
helper modes (argparse exits 2 otherwise).

Reply (one JSON object on stdout, exit 0, keys in this order):

    {"ok":true,"install_info_version":1,"helper":"user"|"system"|"other","system_helper":BOOL,"user_helper":BOOL,"user_plasmoid":BOOL,"system_plasmoid":BOOL,"distro":"arch"|"fedora"|"debian"|"other"}

| Key | Meaning |
| --- | --- |
| `helper` | Where the running `hearthwire` package lives: `user` in `site.getusersitepackages()`, `system` in a site directory of the base interpreter (`site.getsitepackages()`, `/usr/local` included), `other` anywhere else (a checkout, a venv, `PYTHONPATH`) |
| `user_helper` | A regular `hearthwire` package (with `__init__.py`) is in the user site directory |
| `system_helper` | One is in a system site directory |
| `user_plasmoid` | `$XDG_DATA_HOME/plasma/plasmoids/io.github.flybytechprog.hearthwire/metadata.json` is a regular file (links followed); `$XDG_DATA_HOME` defaults to `~/.local/share` when unset or relative |
| `system_plasmoid` | The same under any absolute `$XDG_DATA_DIRS` entry (`/usr/local/share:/usr/share` when unset or without one), except an entry that is the data home itself |
| `distro` | The family from os-release, see below |

The site directories come from `site`, not from `sys.path`, so the reply is
the same under `python3 -s` or in a venv. Empty and relative entries and the
current directory are never searched.

`distro` reads `/etc/os-release`, or `/usr/lib/os-release` only when that does
not exist. The file, after following links, must be inside `/etc` or
`/usr/lib`, be a regular file and hold at most 64 KiB; it must be UTF-8 without
NUL, and every line must be blank, a `#` comment, or `KEY=value` with the
value unquoted (no spaces, quotes, `\`, `` ` `` or `$`) or in matching quotes.
Anything else makes `distro` `other`. `ID` is looked up first, then each
`ID_LIKE` word in order; the first known word wins:

| Word | `distro` |
| --- | --- |
| `arch`, `cachyos`, `manjaro`, `endeavouros` | `arch` |
| `fedora` | `fedora` |
| `debian`, `ubuntu`, `kubuntu`, `neon` | `debian` |
| anything else, or no os-release | `other` |

Any surprise is `{"ok":false,"error":"os-error"}`. The reply never holds a
path, version, name or file text. The widget treats the install as shadowed
when `(user_helper && system_helper) || (user_plasmoid && system_plasmoid)`,
and then shows the fixed notice "A script install of Hearthwire is running
instead of the installed package…" with the remedy on Settings → General and
in the Usage tab. A helper too old to know `--install-info` exits 2 with a
usage message, which counts as unknown (no notice). A widget copy older than
this release never asks, so a script install of such a version that hides
the package shows no notice; the README says how to check by hand.

`scripts/install.sh --remove-script-install [--restart-plasma]` removes what
the script installs in the home folder and nothing else: the helper in the
Python user site (`pip uninstall`, only when `site.getusersitepackages()`
holds a copy and `pip show` resolves `hearthwire` to exactly that directory;
pip also deletes its `~/.local/bin/hearthwire` entry point and may remove
`~/.local/bin` if that leaves it empty),
the folder `$XDG_DATA_HOME/plasma/plasmoids/io.github.flybytechprog.hearthwire`
(a link there is unlinked, never followed), the four
`icons/hicolor/scalable/apps/hearthwire*.svg` icons and
`knotifications6/hearthwire.notifyrc`. It never touches Hearthwire's data
or settings (`~/.local/share/hearthwire`, `~/.config/hearthwire`,
`~/.config/hearthwire.notifyrc`, the widget settings), never touches a file
outside the home folder, never runs `sudo` or `kpackagetool6`, and refuses to
run as root. Without both system copies (by `--install-info`) it first warns
that Hearthwire is gone until a package is installed. It prints each removed
item, says so when there was nothing to remove (a second run is harmless),
and asks for a Plasma restart unless `--restart-plasma` did one.

`kpackagetool6 -s` also finds the system package in `/usr/share`, so the
installer never uses it to ask whether this user has a widget copy: a plain
install runs `kpackagetool6 -u` only when
`$XDG_DATA_HOME/plasma/plasmoids/io.github.flybytechprog.hearthwire` (an
absolute `$XDG_DATA_HOME`, else `~/.local/share`) is a folder and `-i`
otherwise, and `--rollback-hearthwire` runs `kpackagetool6 -r` only for that
folder, never for the package. Likewise the rollback runs `pip uninstall
hearthwire` only when `pip show` names exactly the Python user site
(`site.getusersitepackages()`, the same check as `--remove-script-install`);
a copy pip finds anywhere else, such as the system package, is left in place
and the script says where it is.

## App mode (hearthwire-hyprland)

The helper also serves `hearthwire-hyprland`, the separate Hyprland/Omarchy
app (task 008, slice 011; `src/hearthwire/core/frontend.py`). Nothing changes
for the Plasma widget: without the variable below every command behaves
exactly as in 1.1.0.

- Environment, never argv: `HEARTHWIRE_FRONTEND` is unset, `plasma` or `app`.
  Only the app's process runner sets it, in the child's environment; no
  command-line option sets or changes it. Any other value (also the empty
  string, other case or spaces) runs nothing: the reply is
  `{"ok":false,"error":"bad-frontend"}` on stdout with exit status 2 (usage
  errors stay argparse's, exit 2 with a message on stderr). The value is never
  echoed.
- App id: `APP_APPLET_ID = 2147483648` (2**31). In app mode every `--applet`
  must be that id; in Plasma mode that id is refused. Both are
  `{"ok":false,"error":"applet-not-found"}` (exit 0), for `--web-data`,
  `--usage-history` and every `--settings-backup` operation, before anything
  is read or created. So the app's chat profiles
  (`web/applet-2147483648-g<G>/`) and history (`usage-history/applet-2147483648.json`)
  never mix with a widget's. `usagehistory.run` and `webdata.run` check the
  id again on their own. Shared on purpose: the encrypted folder, the
  settings backup file and the backup key.
- `--usage-history clear --all` (install.sh only) is unchanged in Plasma
  mode. In app mode it would delete every widget's history, so it is refused
  with `{"ok":false,"error":"applet-not-found"}` (exit 0, nothing deleted);
  the app clears its own history with `clear --applet 2147483648`.
- `--migrate …` rewrites Plasma's own files and moves the widget's wallet
  entry, so app mode refuses every operation with
  `{"ok":false,"error":"bad-frontend"}` and exit status 2, before anything
  is read. `legacy.run_operation` refuses app mode (and a bad value) with
  `bad-frontend` again on its own.
- `--prompts add|replace` (app mode): the prompt library has no text box in
  app mode yet (the app's own comes in a later slice), so they reply
  `missing-tool` and kdialog is never looked up; `list`, `remove` and
  `set-persona` work as in Plasma mode. `replace` looks the item up first,
  as in Plasma mode, so it replies `locked` while the encrypted folder is
  locked and `absent` for an id that does not exist, before `missing-tool`.
- `--settings-backup export --applet 2147483648` (app mode) reads the app's
  settings file below instead of Plasma's rc files. A missing folder or file,
  or a file that is not exactly the format, is `bad-data`; a link, a
  non-regular file or folder, someone else's, a folder whose permission bits
  are more open than 0700 or a file more open than 0600 (any group or other
  bit, read included), or a file over 1 MiB is `settings-unreadable`; other codes as
  before. The backup file and its format are the same for both front ends, so
  a backup made in one restores in the other (origin `this-computer`, the
  key is shared).
- `--vault …` (app mode): the passphrase dialog is `hearthwire-askpass`
  instead of kdialog, with kdialog's arguments (`--title T --password P`,
  `--title T --newpassword P`; it prints the passphrase and a newline, exit 0
  OK, 1 cancelled). It is used only at exactly
  `/usr/lib/hearthwire-hyprland/hearthwire-askpass`, never looked up on
  `PATH` or taken from the environment, and only while that path is a
  regular file (not a link) owned by root, executable, without set-id bits
  and not writable by group or others, and `/usr/lib/hearthwire-hyprland`,
  `/usr/lib`, `/usr` and `/` are real directories (not links) owned by root
  and not writable by group or others. Otherwise `status` replies
  `{"ok":true,"state":"unavailable","missing":["hearthwire-askpass"]}` (in
  `TOOLS` order, so `["gocryptfs","hearthwire-askpass","fusermount3"]` when
  all three are missing) and the dialog operations reply `missing-tool`;
  kdialog is never used in app mode, even when it is installed. The child
  allow-list (Replies and errors, above) takes `hearthwire-askpass` only at
  that path, as an `-extpass` program, as the dialog the `-passwd` relay
  runs, and as the new-passphrase dialog. Each mode takes only its own
  dialog in all three places: app mode only that path (never kdialog),
  Plasma mode only an absolute kdialog (never `hearthwire-askpass`).
- KDE Wallet (app mode, until the app's own keyring unlock, slice 014): the
  wallet slot belongs to the Plasma widget and is never used or changed.
  `status` replies `"wallet":"unavailable"` with no wallet `missing` list and
  runs no wallet tool; `add-key`, `remove-key`, `auto-unlock` and `unlock
  --method wallet` reply `{"ok":false,"error":"wallet-disabled"}` before
  anything is touched. `destroy` and `--web-data purge` still delete the
  shared folder and its key slots, but run no wallet tool in app mode, so a
  wallet entry the widget made stays there (useless without the slot) until
  the widget's remove or uninstall; purge's reply then has no
  `wallet-entry`. Both skip the wallet by their own app-mode check, not only
  because app mode finds no wallet tools, and the vault's argv check refuses
  every kwallet-query, qdbus6 and openssl argv, and the `kwallet-query`
  extpass, in app mode.

### App settings file

Written only by the app (0700 folder, 0600 file, replaced atomically, at most
1 MiB; the reader refuses anything more open as `settings-unreadable`, so the
app's writer must create exactly those modes); the helper only reads it, for a backup
(`src/hearthwire/core/appconfig.py`):

- `$XDG_CONFIG_HOME` (when absolute, else `~/.config`)`/hearthwire-hyprland/settings.json`
- `{"format":"hearthwire-app-settings","version":1,"settings":{"<main.xml key>":<value>,...},"app":{"background":false,"agentsPanel":false,"tray":false}}`
- Exactly `format`, `version` and `settings`, plus `app` (optional); any
  other top-level key, another `format`, a `version` other than the integer
  1, a non-object `settings` or `app`, or JSON that `strict_loads` refuses
  (duplicate keys, NaN, Infinity, nesting deeper than 4) is `bad-data`.
- `settings` holds the group General keys of `main.xml`
  (`appletconfig.CONFIG_ENTRIES`, kept equal by
  `tests/test_applet_config_sync.py`; `tests/test_app_config_sync.py` checks
  the reader against it). A missing key is its `main.xml` default; an
  unknown key is ignored; a value of the wrong JSON type (Bool: `true` or
  `false`; Int: an integer from -2147483648 to 2147483647, not a boolean;
  String: a string) is dropped and counted by the backup, as an unreadable
  rc value is. `app.*` is never read into a backup.

## Upgrading from Hearthside

`hearthwire --migrate status|run|applets|rollback` is the one-time move from
the former name (`src/hearthwire/core/legacy.py`, the only Python file with the
old names apart from `LEGACY_FOLDER` in `walletkey.py`). Only
`scripts/install.sh` runs it; the widget never does. It uses no network and no
provider credentials, and stands alone like the other helper modes (argparse
exits 2 otherwise). Every reply is one JSON object on stdout with exit 0, and
holds only category names and fixed codes, never a path, count, name or key.

Categories, always in this order: `data`, `config`, `notifyrc`, `cache`,
`wallet-entry`, `applets`.

| Category | What happens |
| --- | --- |
| `data` | `$XDG_DATA_HOME/hearthside` becomes `.../hearthwire` by one rename; never merged, and an empty target is removed first |
| `config` | `$XDG_CONFIG_HOME/hearthside` likewise |
| `notifyrc` | `$XDG_CONFIG_HOME/hearthside.notifyrc` becomes `hearthwire.notifyrc`; an existing new file is kept and the old one dropped |
| `cache` | `$XDG_CACHE_HOME/hearthside/antigravity-auth.json` and its temporaries are deleted, not moved; the folder goes only if that leaves it empty |
| `wallet-entry` | Only when the moved folder has a wallet slot (`vault-keys/wallet.conf`, a regular file of yours); see the wallet rule below |
| `applets` | With plasmashell stopped, exact `plugin=io.github.flybytechprog.hearthside` lines directly under `[Containments][N][Applets][M]` get the new id; every other byte stays |

| Command | Does | Success reply |
| --- | --- | --- |
| `--migrate status` | Read only. `pending` is what still has to move, `present` what already uses the new name (`data`, `config`, `notifyrc`, `wallet-entry`, `applets`). With work pending it also refuses a mounted vault, a held lock and data under both names; with nothing pending, or only `wallet-entry`, a mounted vault is fine | `{"ok":true,"pending":[...],"present":[...]}` |
| `--migrate run` | Moves the first five categories. `migrated` is what this call moved, `pending` what is still left afterwards (including `applets`, which is its own step). With none of the five pending it returns at once and takes no lock. plasmashell may keep running when only `wallet-entry` is left | `{"ok":true,"migrated":[...],"pending":[...]}` |
| `--migrate applets` | Checks everything first under the locks, so a refusal changes nothing. Writes `<appletsrc>.hearthside-backup` (mode `0600`, once; an existing one is kept), then replaces appletsrc atomically, keeping its mode, after checking again that plasmashell is stopped and the file is unchanged | `{"ok":true,"migrated":[...],"pending":[...]}` |
| `--migrate rollback` | The inverse of `run` and `applets`, except that the token cache is not restored. `pending` can only be `["wallet-entry"]` or empty; a later rollback finishes it | `{"ok":true,"restored":[...],"pending":[...]}` |

A failure is `{"ok":false,"error":CODE}`, with `"category":NAME` added when one
category's step failed. The checks that come before the steps (the mounted
vault and the locks, and plasmashell for `run` and `rollback`) have no
category; a planted link or another user's entry among the moved folder's fixed
children (`vault`, `usage-history`, `vault-keys` and its `wallet.conf`,
`.old`, `.new`) is `data` or `wallet-entry` and refuses before anything changes; `plasma-running` from the appletsrc step itself has
`"category":"applets"`.

| Code | Meaning |
| --- | --- |
| `not-locked` | A vault is mounted under either name |
| `busy` | The vault lock of either name is held (5 second wait) |
| `symlink`, `not-directory`, `not-owned` | Something in the way is a symlink, the wrong kind of file, or not yours; nothing is followed |
| `conflict` | `data` or `config` holds files under both names, or a rename target appeared |
| `plasma-running` | A plasmashell process of this user exists (`/proc/<pid>/comm`) |
| `invalid` | appletsrc is over 16 MiB, not a regular file, not UTF-8, holds NUL, has a malformed group header, or names either id in an inexact `plugin` line of an applet group |
| `os-error` | Anything else, including no usable runtime directory or an appletsrc that changed during the rewrite |

Every step is idempotent, so a run that stopped half-way is finished by the
next. The old and then the new vault lock are held. Names are opened one
component at a time without following links and must be yours; renames use
directory descriptors and `renameat2(RENAME_NOREPLACE)` where available; nothing
is deleted recursively.

Wallet rule (`walletkey.LEGACY_FOLDER`, `Hearthside`, migration only):
`kwallet-query` may read or write `encrypted-chat-folder` there, and `qdbus6`
may call `keyDoesNotExist` or `removeEntry` for `encrypted-chat-folder` and
`encrypted-chat-folder.new`. It is never an `-extpass` value, and the folder
itself is never removed (`removeFolder` is not an allowed method). In `run`, an
entry in the new folder that already opens the slot is kept; otherwise the old
entry is copied with `kwallet-query -r` into a pipe and `-w` from it. The copy
is proven by a real mount with the wallet slot, then unmounted, and only then
are the old entry and any old staging entry removed. If the proof fails the
copy is removed and `wallet-entry` stays pending. Without an enabled wallet,
its tools, gocryptfs or fusermount3 the step also stays pending. A staging
entry with no real old entry proves nothing: it stays and is not reported. In
`rollback`, the new entry is copied into the old folder and removed only after
`cmp -s` on two pipes (this process never reads them) found both entries equal;
without that proof both stay and `wallet-entry` is pending.

The installer checks `status` before changing anything, needs
`--restart-plasma` or a yes in a terminal, stops plasmashell (an exit trap
starts it again), runs `run` then `applets`, and removes the old package,
widget, icons and events file. When only `wallet-entry` is pending it does not
stop Plasma or ask: it tries `run`, carries on with the install either way, and
while the entry stays pending prints "KDE Wallet wasn't available; run the
installer again later to finish moving its entry". A later complete install
that finds nothing pending and `applets` in `present` deletes the appletsrc backup (an owned
regular file only, never through a symlink). `--rollback-hearthwire` runs
`rollback` and uninstalls this release.
