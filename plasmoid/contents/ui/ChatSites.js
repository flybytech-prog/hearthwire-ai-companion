.pragma library

// Chat tab websites. Kept here only; the usage catalog (ProviderCatalog.js)
// is unrelated. Hosts match exactly or as a dot-suffix, case-insensitively;
// a user's custom address adds only its exact host.
//
// Sites the user added (Settings → Chat, chatUserSites) are passed in as
// userSites, a list of {id, name, url}; nothing here stores them. Without
// userSites an added id is unknown, so it resolves to nothing and is
// blocked. Their hosts and class are derived from the address on every
// call, never read from the stored entry.
var sites = [
    {
        id: "claude",
        name: "Claude",
        url: "https://claude.ai/new",
        icon: "provider-claude.svg",
        site_hosts: ["claude.ai", "claude.com", "anthropic.com"],
        auth_hosts: ["accounts.google.com", "appleid.apple.com"]
    },
    {
        id: "chatgpt",
        name: "ChatGPT",
        url: "https://chatgpt.com/",
        icon: "provider-codex.svg",
        site_hosts: ["chatgpt.com", "openai.com"],
        auth_hosts: [
            "accounts.google.com",
            "login.microsoftonline.com",
            "login.live.com",
            "appleid.apple.com"
        ]
    },
    {
        id: "grok",
        name: "Grok",
        url: "https://grok.com/",
        icon: "provider-grok.svg",
        site_hosts: ["grok.com", "x.ai", "x.com"],
        auth_hosts: ["accounts.google.com", "appleid.apple.com"]
    },
    {
        id: "gemini",
        name: "Gemini",
        url: "https://gemini.google.com/app",
        icon: "provider-gemini.svg",
        site_hosts: ["gemini.google.com", "accounts.google.com", "consent.google.com"],
        auth_hosts: ["accounts.google.com"]
    },
    {
        id: "copilot",
        name: "GitHub Copilot",
        // Signed-out visitors to /copilot get a landing page, not the sign-in.
        url: "https://github.com/login?return_to=%2Fcopilot",
        icon: "provider-copilot.svg",
        site_hosts: ["github.com"],
        auth_hosts: ["github.com", "accounts.google.com", "appleid.apple.com"]
    },
    {
        id: "mscopilot",
        name: "Microsoft Copilot",
        url: "https://copilot.microsoft.com/",
        icon: "provider-mscopilot.svg",
        site_hosts: ["copilot.microsoft.com", "microsoft.com", "bing.com"],
        auth_hosts: [
            "login.microsoftonline.com",
            "login.live.com",
            "account.live.com",
            "accounts.google.com",
            "appleid.apple.com"
        ]
    },
    {
        // A chat server on this computer. Plain http is allowed only here and
        // only for the exact loopback origin of its address.
        id: "local",
        name: "Local web UI (Open WebUI)",
        url: "http://localhost:3000/",
        icon: "provider-local.svg",
        site_hosts: ["localhost", "127.0.0.1", "[::1]"],
        auth_hosts: [],
        local: true,
        default_on: false
    }
]

var MAX_CUSTOM_URL_LENGTH = 2048

// The built-in Ollama chat's entry, the same as OllamaChat.ENTRY (a test
// keeps them equal); this file stays a library without imports.
var OLLAMA_ENTRY = Object.freeze({
    id: "ollama",
    name: "Ollama",
    icon: "provider-local.svg",
    native: true,
    default_on: false
})

// Added sites: at most this many (plus the 7 built-ins: ChatStorage's
// MAX_SITE_IDS), this long as stored (UTF-16 units), names this long.
var MAX_USER_SITES = 200
var MAX_USER_SITES_CHARS = 458752
var MAX_USER_SITE_NAME = 40

// The built-in web sites, then the valid added ones in their own order.
function siteIds(userSites) {
    return sites.map(function (site) { return site.id }).concat(
        validUserSites(userSites).map(function (site) { return site.id }))
}

// A built-in site as in the catalog, an added one as effectiveSite builds
// it; null when unknown.
function byId(siteId, userSites) {
    for (var index = 0; index < sites.length; index++) {
        if (sites[index].id === siteId)
            return sites[index]
    }
    return isUserSiteId(siteId) ? userSite(siteId, userSites) : null
}

// Sites that are on unless the user turns them off.
function defaultSiteIds() {
    return sites.filter(function (site) { return site.default_on !== false })
        .map(function (site) { return site.id })
}

// Web sites enabled by the chatSites config JSON, in the chatSiteOrder
// order (orderedSites). Unreadable config falls back to the default-on
// built-in sites only.
function enabledSites(json, userSites, orderText) {
    var wanted = null
    try {
        var parsed = JSON.parse(json || "")
        if (Array.isArray(parsed))
            wanted = parsed
    } catch (error) {
    }
    if (wanted === null)
        wanted = defaultSiteIds()
    return orderedSites(userSites, orderText).filter(function (site) {
        return site.id !== OLLAMA_ENTRY.id && wanted.indexOf(site.id) >= 0
    })
}

function initialSite(enabledIds, configuredDefault) {
    var ids = Array.isArray(enabledIds) ? enabledIds : []
    if (ids.indexOf(configuredDefault) >= 0)
        return configuredDefault
    return ids.length > 0 ? ids[0] : ""
}

function normalizeHost(host) {
    if (typeof host !== "string")
        return ""
    var normalized = host.toLowerCase()
    if (normalized.charAt(normalized.length - 1) === ".")
        normalized = normalized.slice(0, -1)
    return normalized
}

function hostMatches(host, list) {
    if (typeof host !== "string" || host === "" || !Array.isArray(list))
        return false
    var normalized = normalizeHost(host)
    for (var index = 0; index < list.length; index++) {
        var entry = String(list[index]).toLowerCase()
        if (entry === "")
            continue
        if (normalized === entry
                || normalized.slice(-(entry.length + 1)) === "." + entry)
            return true
    }
    return false
}

// Exact host equality only; custom addresses never cover subdomains.
function exactHostMatches(host, list) {
    if (typeof host !== "string" || host === "" || !Array.isArray(list))
        return false
    var normalized = normalizeHost(host)
    for (var index = 0; index < list.length; index++) {
        var entry = normalizeHost(String(list[index]))
        if (entry !== "" && normalized === entry)
            return true
    }
    return false
}

// The three spellings of this computer that Local may use over plain http.
function isLoopbackHost(host) {
    var normalized = normalizeHost(host)
    return normalized === "localhost" || normalized === "127.0.0.1" || normalized === "[::1]"
}

// Numeric value of an IPv4 literal in any form the browser accepts
// (127.1, 0x7f000001, 017700000001...), -1 when it can't be one.
function ipv4Value(host) {
    var parts = host.split(".")
    if (parts.length > 4)
        return -1
    var numbers = []
    for (var index = 0; index < parts.length; index++) {
        var part = parts[index]
        var number
        if (/^0x[0-9a-f]*$/.test(part))
            number = part.length > 2 ? parseInt(part.slice(2), 16) : 0
        else if (/^0[0-7]+$/.test(part))
            number = parseInt(part.slice(1), 8)
        else if (/^(0|[1-9][0-9]*)$/.test(part))
            number = parseInt(part, 10)
        else
            return -1
        numbers.push(number)
    }
    var value = 0
    for (var head = 0; head < numbers.length - 1; head++) {
        if (numbers[head] > 255)
            return -1
        value = value * 256 + numbers[head]
    }
    var room = Math.pow(256, 5 - numbers.length)
    var last = numbers[numbers.length - 1]
    if (last >= room)
        return -1
    return value * room + last
}

// Names the usual /etc/hosts gives this computer, beside "localhost".
var LOCAL_NAMES = ["localhost.localdomain", "ip6-localhost", "ip6-loopback"]

// Wider than isLoopbackHost: everything the browser would send to this
// computer. Used only to block, never to allow. Hosts ending in a number
// that isn't a valid IPv4 literal are treated as local (fail closed), and
// so is every name without a dot (the machine's own name, LAN names).
function isLocalAddress(host) {
    var normalized = normalizeHost(host)
    if (normalized === "")
        return false
    if (isLoopbackHost(normalized) || normalized.indexOf(".") < 0
            || LOCAL_NAMES.indexOf(normalized) >= 0
            || normalized.slice(-10) === ".localhost"
            || normalized.slice(-22) === ".localhost.localdomain")
        return true
    var labels = normalized.split(".")
    if (!/^(0x[0-9a-f]*|[0-9]+)$/.test(labels[labels.length - 1]))
        return false
    var value = ipv4Value(normalized)
    return value < 0 || value === 0 || Math.floor(value / 16777216) === 127
}

// Minimal parser: {scheme, host, port} or null when malformed; port is ""
// when absent. Hosts must be plain DNS names, IPv4 or [::1]; user info,
// backslashes and odd characters are treated as hostile.
function parseUrl(value) {
    var text = String(value === undefined || value === null ? "" : value)
    var schemeMatch = /^([A-Za-z][A-Za-z0-9+.\-]*):(.*)$/.exec(text)
    if (!schemeMatch)
        return null
    var scheme = schemeMatch[1].toLowerCase()
    var rest = schemeMatch[2]
    if (scheme !== "https" && scheme !== "http")
        return { scheme: scheme, host: "", port: "" }
    if (rest.indexOf("//") !== 0)
        return null
    var authority = rest.slice(2).split(/[\/?#]/)[0]
    if (authority === "" || /[@\\\s%]/.test(authority))
        return null
    var host
    var port
    if (authority.charAt(0) === "[") {
        var bracketMatch = /^(\[::1\])(?::([0-9]{1,5}))?$/.exec(authority)
        if (!bracketMatch)
            return null
        host = bracketMatch[1]
        port = bracketMatch[2]
    } else {
        var hostMatch = /^([A-Za-z0-9.\-]+)(?::([0-9]{1,5}))?$/.exec(authority)
        if (!hostMatch)
            return null
        host = hostMatch[1].toLowerCase()
        port = hostMatch[2]
        if (host.charAt(0) === "." || host.indexOf("..") >= 0)
            return null
    }
    if (port === undefined) {
        port = ""
    } else {
        var number = parseInt(port, 10)
        if (number < 1 || number > 65535)
            return null
        port = String(number)
    }
    return { scheme: scheme, host: host, port: port }
}

function isAboutBlank(value) {
    return String(value === undefined || value === null ? "" : value)
        .toLowerCase() === "about:blank"
}

function isHttpsUrl(value) {
    var parsed = parseUrl(value)
    return parsed !== null && parsed.scheme === "https" && parsed.host !== ""
}

// "host:port" of a parsed http URL, port 80 when absent.
function httpOrigin(parsed) {
    return normalizeHost(parsed.host) + ":" + (parsed.port !== "" ? parsed.port : "80")
}

// {ok, url, error} for a custom address typed by the user. Empty means
// "use the built-in address". The text is checked as given (callers trim).
function validateCustomUrl(siteId, text) {
    var fail = function (code) { return { ok: false, url: "", error: code } }
    var site = byId(siteId)
    if (!site)
        return fail("unknown-site")
    var value = text === undefined || text === null ? "" : String(text)
    if (value === "")
        return { ok: true, url: "", error: "" }
    if (value.length > MAX_CUSTOM_URL_LENGTH)
        return fail("too-long")
    if (/[\s\u0000-\u001f\u007f]/.test(value))
        return fail("whitespace")
    var authorityMatch = /^[A-Za-z][A-Za-z0-9+.\-]*:\/\/([^\/?#]*)/.exec(value)
    if (authorityMatch && authorityMatch[1].indexOf("@") >= 0)
        return fail("userinfo")
    var schemeMatch = /^([A-Za-z][A-Za-z0-9+.\-]*):/.exec(value)
    if (!schemeMatch)
        return fail("malformed")
    var scheme = schemeMatch[1].toLowerCase()
    if (scheme !== "https" && !(scheme === "http" && site.local === true))
        return fail("scheme")
    var parsed = parseUrl(value)
    if (parsed === null || parsed.host === "")
        return fail("malformed")
    if (parsed.scheme === "http" && !isLoopbackHost(parsed.host))
        return fail("http-not-loopback")
    if (site.local !== true && isLocalAddress(parsed.host))
        return fail("loopback-not-allowed")
    return { ok: true, url: value, error: "" }
}

// Only known ids with a valid non-empty address, in catalog order.
function filterCustomUrls(map) {
    var result = {}
    if (map === null || typeof map !== "object" || Array.isArray(map))
        return result
    for (var index = 0; index < sites.length; index++) {
        var id = sites[index].id
        if (!Object.prototype.hasOwnProperty.call(map, id) || typeof map[id] !== "string")
            continue
        var checked = validateCustomUrl(id, map[id])
        if (checked.ok && checked.url !== "")
            result[id] = checked.url
    }
    return result
}

// The chatCustomUrls config JSON as {siteId: url}; anything odd → {}.
function parseCustomUrls(json) {
    var parsed = null
    try {
        parsed = JSON.parse(typeof json === "string" ? json : "")
    } catch (error) {
    }
    return filterCustomUrls(parsed)
}

function serializeCustomUrls(map) {
    return JSON.stringify(filterCustomUrls(map))
}

// The site with the user's custom address applied, or null when unknown.
// The address is re-validated on every call; invalid falls back to built-in.
// An added site (userSites) is rebuilt from its name and address alone.
function effectiveSite(siteId, customUrls, userSites) {
    if (isUserSiteId(siteId))
        return userSite(siteId, userSites)
    var site = byId(siteId)
    if (!site)
        return null
    var custom = ""
    if (customUrls !== null && typeof customUrls === "object" && !Array.isArray(customUrls)
            && Object.prototype.hasOwnProperty.call(customUrls, site.id)
            && typeof customUrls[site.id] === "string") {
        var checked = validateCustomUrl(site.id, customUrls[site.id])
        if (checked.ok)
            custom = checked.url
    }
    var url = custom !== "" ? custom : site.url
    var parsed = parseUrl(url)
    return {
        id: site.id,
        name: site.name,
        url: url,
        icon: site.icon,
        site_hosts: site.site_hosts.slice(),
        auth_hosts: site.auth_hosts.slice(),
        exact_hosts: custom !== "" ? [normalizeHost(parsed.host)] : [],
        local: site.local === true,
        default_on: site.default_on !== false,
        http_origin: site.local === true && parsed.scheme === "http" ? httpOrigin(parsed) : ""
    }
}

function homeUrl(siteId, customUrls, userSites) {
    var site = effectiveSite(siteId, customUrls, userSites)
    return site ? site.url : ""
}

function knownHost(site, host) {
    return hostMatches(host, site.site_hosts) || hostMatches(host, site.auth_hosts)
        || exactHostMatches(host, site.exact_hosts)
}

// Local http is allowed only for the exact loopback origin of its address.
function httpAllowed(site, parsed) {
    return site.local === true && typeof site.http_origin === "string"
        && site.http_origin !== "" && isLoopbackHost(parsed.host)
        && httpOrigin(parsed) === site.http_origin
}

// Whether url is a page of site that may be handed to the browser.
function isPageUrl(site, url) {
    if (!site)
        return false
    var parsed = parseUrl(url)
    if (parsed === null || parsed.host === "")
        return false
    if (parsed.scheme === "https")
        return site.local === true || !isLocalAddress(parsed.host)
    if (parsed.scheme === "http")
        return httpAllowed(site, parsed)
    return false
}

// "allow" | "external" | "block" for a WebEngine navigation request.
// request.customUrls is optional; without it the built-in addresses apply.
// request.userSites: the added sites (see the top of this file).
function classifyNavigation(request) {
    var info = request || {}
    // Only an explicit subframe gets the looser rules; missing info is
    // treated as the main frame.
    if (info.isMainFrame === false)
        return classifySubframe(info)
    var site = effectiveSite(info.siteId, info.customUrls, info.userSites)
    if (!site)
        return "block"
    if (isAboutBlank(info.url))
        return "allow"
    var parsed = parseUrl(info.url)
    if (parsed === null)
        return "block"
    if (parsed.host !== "" && !site.local && isLocalAddress(parsed.host))
        return "block"
    if (site.user === true && parsed.host !== "" && isPrivateLiteral(parsed.host))
        return "block"
    if (parsed.scheme === "https") {
        if (info.linkClicked && !knownHost(site, parsed.host))
            return "external"
        return "allow"
    }
    if (parsed.scheme === "http")
        return httpAllowed(site, parsed) ? "allow" : "block"
    return "block"
}

// --- Added sites (Settings → Chat) --------------------------------------------

// Names an added site may not take, in any case: the built-ins and Ollama.
var USER_SITE_KEYS = ["id", "name", "url"]
var NAME_CONTROLS = /[\u0000-\u001f\u007f-\u009f]/
var LONE_SURROGATE = /[\ud800-\udbff](?![\udc00-\udfff])|(?:[^\ud800-\udbff]|^)[\udc00-\udfff]/
// Markup, and invisible or bidi formatting that could spoof the table or a
// prompt (M3): every Default_Ignorable_Code_Point, the line and paragraph
// separators, the Mongolian vowel separator, the interlinear annotation
// marks (U+FFF9-FFFB) and the braille blank (U+2800). Astral ones as
// surrogate pairs: U+1BCA0-1BCA3, U+1D173-1D17A, U+E0000-E0FFF.
var NAME_FORBIDDEN = new RegExp("[<>&\\u00ad\\u034f\\u061c\\u115f\\u1160\\u17b4\\u17b5\\u180b-\\u180f"
    + "\\u200b-\\u200f\\u2028-\\u202e\\u2060-\\u206f\\u2800\\u3164\\ufe00-\\ufe0f\\ufeff\\uffa0"
    + "\\ufff0-\\ufffb]|\\ud82f[\\udca0-\\udca3]|\\ud834[\\udd73-\\udd7a]|\\udb40[\\udc00-\\udfff]"
    + "|[\\udb41-\\udb43][\\udc00-\\udfff]")
// A name needs at least one letter or digit: the code points whose Unicode
// general category is L* or N*, as "start-end" (hex) ranges. Generated
// from Python 3.14's unicodedata (Unicode 16.0.0), the helper's own rule
// (settingsbackup.py), so both read a name the same way.
var LETTER_DIGIT_RANGES =
    "30-39,41-5a,61-7a,aa,b2-b3,b5,b9-ba,bc-be,c0-d6,d8-f6,f8-2c1,2c6-2d1,2e0-2e4,2ec,2ee,370-374,376-377,37a-37d," +
    "37f,386,388-38a,38c,38e-3a1,3a3-3f5,3f7-481,48a-52f,531-556,559,560-588,5d0-5ea,5ef-5f2,620-64a,660-669," +
    "66e-66f,671-6d3,6d5,6e5-6e6,6ee-6fc,6ff,710,712-72f,74d-7a5,7b1,7c0-7ea,7f4-7f5,7fa,800-815,81a,824,828," +
    "840-858,860-86a,870-887,889-88e,8a0-8c9,904-939,93d,950,958-961,966-96f,971-980,985-98c,98f-990,993-9a8," +
    "9aa-9b0,9b2,9b6-9b9,9bd,9ce,9dc-9dd,9df-9e1,9e6-9f1,9f4-9f9,9fc,a05-a0a,a0f-a10,a13-a28,a2a-a30,a32-a33," +
    "a35-a36,a38-a39,a59-a5c,a5e,a66-a6f,a72-a74,a85-a8d,a8f-a91,a93-aa8,aaa-ab0,ab2-ab3,ab5-ab9,abd,ad0,ae0-ae1," +
    "ae6-aef,af9,b05-b0c,b0f-b10,b13-b28,b2a-b30,b32-b33,b35-b39,b3d,b5c-b5d,b5f-b61,b66-b6f,b71-b77,b83,b85-b8a," +
    "b8e-b90,b92-b95,b99-b9a,b9c,b9e-b9f,ba3-ba4,ba8-baa,bae-bb9,bd0,be6-bf2,c05-c0c,c0e-c10,c12-c28,c2a-c39,c3d," +
    "c58-c5a,c5d,c60-c61,c66-c6f,c78-c7e,c80,c85-c8c,c8e-c90,c92-ca8,caa-cb3,cb5-cb9,cbd,cdd-cde,ce0-ce1,ce6-cef," +
    "cf1-cf2,d04-d0c,d0e-d10,d12-d3a,d3d,d4e,d54-d56,d58-d61,d66-d78,d7a-d7f,d85-d96,d9a-db1,db3-dbb,dbd,dc0-dc6," +
    "de6-def,e01-e30,e32-e33,e40-e46,e50-e59,e81-e82,e84,e86-e8a,e8c-ea3,ea5,ea7-eb0,eb2-eb3,ebd,ec0-ec4,ec6," +
    "ed0-ed9,edc-edf,f00,f20-f33,f40-f47,f49-f6c,f88-f8c,1000-102a,103f-1049,1050-1055,105a-105d,1061,1065-1066," +
    "106e-1070,1075-1081,108e,1090-1099,10a0-10c5,10c7,10cd,10d0-10fa,10fc-1248,124a-124d,1250-1256,1258,125a-125d," +
    "1260-1288,128a-128d,1290-12b0,12b2-12b5,12b8-12be,12c0,12c2-12c5,12c8-12d6,12d8-1310,1312-1315,1318-135a," +
    "1369-137c,1380-138f,13a0-13f5,13f8-13fd,1401-166c,166f-167f,1681-169a,16a0-16ea,16ee-16f8,1700-1711,171f-1731," +
    "1740-1751,1760-176c,176e-1770,1780-17b3,17d7,17dc,17e0-17e9,17f0-17f9,1810-1819,1820-1878,1880-1884,1887-18a8," +
    "18aa,18b0-18f5,1900-191e,1946-196d,1970-1974,1980-19ab,19b0-19c9,19d0-19da,1a00-1a16,1a20-1a54,1a80-1a89," +
    "1a90-1a99,1aa7,1b05-1b33,1b45-1b4c,1b50-1b59,1b83-1ba0,1bae-1be5,1c00-1c23,1c40-1c49,1c4d-1c7d,1c80-1c8a," +
    "1c90-1cba,1cbd-1cbf,1ce9-1cec,1cee-1cf3,1cf5-1cf6,1cfa,1d00-1dbf,1e00-1f15,1f18-1f1d,1f20-1f45,1f48-1f4d," +
    "1f50-1f57,1f59,1f5b,1f5d,1f5f-1f7d,1f80-1fb4,1fb6-1fbc,1fbe,1fc2-1fc4,1fc6-1fcc,1fd0-1fd3,1fd6-1fdb,1fe0-1fec," +
    "1ff2-1ff4,1ff6-1ffc,2070-2071,2074-2079,207f-2089,2090-209c,2102,2107,210a-2113,2115,2119-211d,2124,2126,2128," +
    "212a-212d,212f-2139,213c-213f,2145-2149,214e,2150-2189,2460-249b,24ea-24ff,2776-2793,2c00-2ce4,2ceb-2cee," +
    "2cf2-2cf3,2cfd,2d00-2d25,2d27,2d2d,2d30-2d67,2d6f,2d80-2d96,2da0-2da6,2da8-2dae,2db0-2db6,2db8-2dbe,2dc0-2dc6," +
    "2dc8-2dce,2dd0-2dd6,2dd8-2dde,2e2f,3005-3007,3021-3029,3031-3035,3038-303c,3041-3096,309d-309f,30a1-30fa," +
    "30fc-30ff,3105-312f,3131-318e,3192-3195,31a0-31bf,31f0-31ff,3220-3229,3248-324f,3251-325f,3280-3289,32b1-32bf," +
    "3400-4dbf,4e00-a48c,a4d0-a4fd,a500-a60c,a610-a62b,a640-a66e,a67f-a69d,a6a0-a6ef,a717-a71f,a722-a788,a78b-a7cd," +
    "a7d0-a7d1,a7d3,a7d5-a7dc,a7f2-a801,a803-a805,a807-a80a,a80c-a822,a830-a835,a840-a873,a882-a8b3,a8d0-a8d9," +
    "a8f2-a8f7,a8fb,a8fd-a8fe,a900-a925,a930-a946,a960-a97c,a984-a9b2,a9cf-a9d9,a9e0-a9e4,a9e6-a9fe,aa00-aa28," +
    "aa40-aa42,aa44-aa4b,aa50-aa59,aa60-aa76,aa7a,aa7e-aaaf,aab1,aab5-aab6,aab9-aabd,aac0,aac2,aadb-aadd,aae0-aaea," +
    "aaf2-aaf4,ab01-ab06,ab09-ab0e,ab11-ab16,ab20-ab26,ab28-ab2e,ab30-ab5a,ab5c-ab69,ab70-abe2,abf0-abf9,ac00-d7a3," +
    "d7b0-d7c6,d7cb-d7fb,f900-fa6d,fa70-fad9,fb00-fb06,fb13-fb17,fb1d,fb1f-fb28,fb2a-fb36,fb38-fb3c,fb3e,fb40-fb41," +
    "fb43-fb44,fb46-fbb1,fbd3-fd3d,fd50-fd8f,fd92-fdc7,fdf0-fdfb,fe70-fe74,fe76-fefc,ff10-ff19,ff21-ff3a,ff41-ff5a," +
    "ff66-ffbe,ffc2-ffc7,ffca-ffcf,ffd2-ffd7,ffda-ffdc,10000-1000b,1000d-10026,10028-1003a,1003c-1003d,1003f-1004d," +
    "10050-1005d,10080-100fa,10107-10133,10140-10178,1018a-1018b,10280-1029c,102a0-102d0,102e1-102fb,10300-10323," +
    "1032d-1034a,10350-10375,10380-1039d,103a0-103c3,103c8-103cf,103d1-103d5,10400-1049d,104a0-104a9,104b0-104d3," +
    "104d8-104fb,10500-10527,10530-10563,10570-1057a,1057c-1058a,1058c-10592,10594-10595,10597-105a1,105a3-105b1," +
    "105b3-105b9,105bb-105bc,105c0-105f3,10600-10736,10740-10755,10760-10767,10780-10785,10787-107b0,107b2-107ba," +
    "10800-10805,10808,1080a-10835,10837-10838,1083c,1083f-10855,10858-10876,10879-1089e,108a7-108af,108e0-108f2," +
    "108f4-108f5,108fb-1091b,10920-10939,10980-109b7,109bc-109cf,109d2-10a00,10a10-10a13,10a15-10a17,10a19-10a35," +
    "10a40-10a48,10a60-10a7e,10a80-10a9f,10ac0-10ac7,10ac9-10ae4,10aeb-10aef,10b00-10b35,10b40-10b55,10b58-10b72," +
    "10b78-10b91,10ba9-10baf,10c00-10c48,10c80-10cb2,10cc0-10cf2,10cfa-10d23,10d30-10d39,10d40-10d65,10d6f-10d85," +
    "10e60-10e7e,10e80-10ea9,10eb0-10eb1,10ec2-10ec4,10f00-10f27,10f30-10f45,10f51-10f54,10f70-10f81,10fb0-10fcb," +
    "10fe0-10ff6,11003-11037,11052-1106f,11071-11072,11075,11083-110af,110d0-110e8,110f0-110f9,11103-11126," +
    "11136-1113f,11144,11147,11150-11172,11176,11183-111b2,111c1-111c4,111d0-111da,111dc,111e1-111f4,11200-11211," +
    "11213-1122b,1123f-11240,11280-11286,11288,1128a-1128d,1128f-1129d,1129f-112a8,112b0-112de,112f0-112f9," +
    "11305-1130c,1130f-11310,11313-11328,1132a-11330,11332-11333,11335-11339,1133d,11350,1135d-11361,11380-11389," +
    "1138b,1138e,11390-113b5,113b7,113d1,113d3,11400-11434,11447-1144a,11450-11459,1145f-11461,11480-114af," +
    "114c4-114c5,114c7,114d0-114d9,11580-115ae,115d8-115db,11600-1162f,11644,11650-11659,11680-116aa,116b8," +
    "116c0-116c9,116d0-116e3,11700-1171a,11730-1173b,11740-11746,11800-1182b,118a0-118f2,118ff-11906,11909," +
    "1190c-11913,11915-11916,11918-1192f,1193f,11941,11950-11959,119a0-119a7,119aa-119d0,119e1,119e3,11a00," +
    "11a0b-11a32,11a3a,11a50,11a5c-11a89,11a9d,11ab0-11af8,11bc0-11be0,11bf0-11bf9,11c00-11c08,11c0a-11c2e,11c40," +
    "11c50-11c6c,11c72-11c8f,11d00-11d06,11d08-11d09,11d0b-11d30,11d46,11d50-11d59,11d60-11d65,11d67-11d68," +
    "11d6a-11d89,11d98,11da0-11da9,11ee0-11ef2,11f02,11f04-11f10,11f12-11f33,11f50-11f59,11fb0,11fc0-11fd4," +
    "12000-12399,12400-1246e,12480-12543,12f90-12ff0,13000-1342f,13441-13446,13460-143fa,14400-14646,16100-1611d," +
    "16130-16139,16800-16a38,16a40-16a5e,16a60-16a69,16a70-16abe,16ac0-16ac9,16ad0-16aed,16b00-16b2f,16b40-16b43," +
    "16b50-16b59,16b5b-16b61,16b63-16b77,16b7d-16b8f,16d40-16d6c,16d70-16d79,16e40-16e96,16f00-16f4a,16f50," +
    "16f93-16f9f,16fe0-16fe1,16fe3,17000-187f7,18800-18cd5,18cff-18d08,1aff0-1aff3,1aff5-1affb,1affd-1affe," +
    "1b000-1b122,1b132,1b150-1b152,1b155,1b164-1b167,1b170-1b2fb,1bc00-1bc6a,1bc70-1bc7c,1bc80-1bc88,1bc90-1bc99," +
    "1ccf0-1ccf9,1d2c0-1d2d3,1d2e0-1d2f3,1d360-1d378,1d400-1d454,1d456-1d49c,1d49e-1d49f,1d4a2,1d4a5-1d4a6," +
    "1d4a9-1d4ac,1d4ae-1d4b9,1d4bb,1d4bd-1d4c3,1d4c5-1d505,1d507-1d50a,1d50d-1d514,1d516-1d51c,1d51e-1d539," +
    "1d53b-1d53e,1d540-1d544,1d546,1d54a-1d550,1d552-1d6a5,1d6a8-1d6c0,1d6c2-1d6da,1d6dc-1d6fa,1d6fc-1d714," +
    "1d716-1d734,1d736-1d74e,1d750-1d76e,1d770-1d788,1d78a-1d7a8,1d7aa-1d7c2,1d7c4-1d7cb,1d7ce-1d7ff,1df00-1df1e," +
    "1df25-1df2a,1e030-1e06d,1e100-1e12c,1e137-1e13d,1e140-1e149,1e14e,1e290-1e2ad,1e2c0-1e2eb,1e2f0-1e2f9," +
    "1e4d0-1e4eb,1e4f0-1e4f9,1e5d0-1e5ed,1e5f0-1e5fa,1e7e0-1e7e6,1e7e8-1e7eb,1e7ed-1e7ee,1e7f0-1e7fe,1e800-1e8c4," +
    "1e8c7-1e8cf,1e900-1e943,1e94b,1e950-1e959,1ec71-1ecab,1ecad-1ecaf,1ecb1-1ecb4,1ed01-1ed2d,1ed2f-1ed3d," +
    "1ee00-1ee03,1ee05-1ee1f,1ee21-1ee22,1ee24,1ee27,1ee29-1ee32,1ee34-1ee37,1ee39,1ee3b,1ee42,1ee47,1ee49,1ee4b," +
    "1ee4d-1ee4f,1ee51-1ee52,1ee54,1ee57,1ee59,1ee5b,1ee5d,1ee5f,1ee61-1ee62,1ee64,1ee67-1ee6a,1ee6c-1ee72," +
    "1ee74-1ee77,1ee79-1ee7c,1ee7e,1ee80-1ee89,1ee8b-1ee9b,1eea1-1eea3,1eea5-1eea9,1eeab-1eebb,1f100-1f10c," +
    "1fbf0-1fbf9,20000-2a6df,2a700-2b739,2b740-2b81d,2b820-2cea1,2ceb0-2ebe0,2ebf0-2ee5d,2f800-2fa1d,30000-3134a," +
    "31350-323af"
var letterDigitTable = null

function isLetterOrDigit(point) {
    if (letterDigitTable === null) {
        letterDigitTable = LETTER_DIGIT_RANGES.split(",").map(function (range) {
            var ends = range.split("-")
            return [parseInt(ends[0], 16), parseInt(ends[ends.length - 1], 16)]
        })
    }
    var low = 0
    var high = letterDigitTable.length - 1
    while (low <= high) {
        var middle = (low + high) >> 1
        if (point < letterDigitTable[middle][0])
            high = middle - 1
        else if (point > letterDigitTable[middle][1])
            low = middle + 1
        else
            return true
    }
    return false
}

function hasLetterOrDigit(text) {
    var points = codePointsOf(text)
    for (var index = 0; index < points.length; index++) {
        if (isLetterOrDigit(points[index]))
            return true
    }
    return false
}
var URL_CHARS = /[^\x21-\x7e]|["\\<>`{}|^]/

function isUserSiteId(id) {
    return typeof id === "string" && /^user-[0-9a-f]{8}$/.test(id)
}

// A new added-site id: user- and 8 hex digits from random (a () => [0,1)
// function, Math.random in the page), never one in excluded (the page's
// ids, those it opened with and those still owing a delete). "" when no
// free one turned up.
function newUserSiteId(excluded, random) {
    var taken = Array.isArray(excluded) ? excluded : []
    var next = typeof random === "function" ? random : Math.random
    for (var attempt = 0; attempt < 1000; attempt++) {
        var id = "user-"
        for (var digit = 0; digit < 8; digit++) {
            var value = Math.floor(Number(next()) * 16)
            id += (isFinite(value) && value >= 0 && value < 16 ? value : 0).toString(16)
        }
        if (taken.indexOf(id) < 0)
            return id
    }
    return ""
}

function nameOf(other) {
    if (typeof other === "string")
        return other
    return other !== null && typeof other === "object" && typeof other.name === "string" ? other.name : ""
}

// "" when name may be stored, else name-empty, name-too-long, name-chars or
// name-taken (first failure wins). The name is checked as stored: leading
// or trailing whitespace is name-chars (the editor trims), and so is a name
// with a forbidden character or without any letter or digit. others: the
// other added sites (or their names).
function userSiteNameError(name, others) {
    if (typeof name !== "string" || name.trim() === "")
        return "name-empty"
    if (name.length > MAX_USER_SITE_NAME)
        return "name-too-long"
    if (name.trim() !== name || NAME_CONTROLS.test(name) || LONE_SURROGATE.test(name)
            || NAME_FORBIDDEN.test(name) || !hasLetterOrDigit(name))
        return "name-chars"
    var lowered = name.toLowerCase()
    var taken = sites.map(function (site) { return site.name }).concat([OLLAMA_ENTRY.name])
    if (Array.isArray(others))
        taken = taken.concat(others.map(nameOf))
    for (var index = 0; index < taken.length; index++) {
        if (taken[index] !== "" && taken[index].toLowerCase() === lowered)
            return "name-taken"
    }
    return ""
}

// "" for an address an added site may have (https to a public DNS name in
// 005), else its code; checked in this order, first failure wins.
function userSiteUrlError(url) {
    if (typeof url !== "string" || url === "")
        return "url-empty"
    if (url.length > MAX_CUSTOM_URL_LENGTH)
        return "too-long"
    if (/[\s\u0000-\u001f\u007f]/.test(url))
        return "whitespace"
    if (URL_CHARS.test(url))
        return "url-chars"
    var authorityMatch = /^[A-Za-z][A-Za-z0-9+.\-]*:\/\/([^\/?#]*)/.exec(url)
    if (authorityMatch && authorityMatch[1].indexOf("@") >= 0)
        return "userinfo"
    var schemeMatch = /^([A-Za-z][A-Za-z0-9+.\-]*):/.exec(url)
    if (!schemeMatch)
        return "malformed"
    var scheme = schemeMatch[1].toLowerCase()
    if (scheme === "http")
        return "http-not-allowed"
    if (scheme !== "https")
        return "scheme"
    var parsed = parseUrl(url)
    if (parsed === null || parsed.host === "")
        return "malformed"
    if (isLocalAddress(parsed.host))
        return "loopback-not-allowed"
    var labels = normalizeHost(parsed.host).split(".")
    if (/^(0x[0-9a-f]*|[0-9]+)$/.test(labels[labels.length - 1]))
        return "ip-literal"
    return ""
}

// The only place that classifies an added site's address: "public" or ""
// in 005 (006 adds loopback and private).
function addressClass(url) {
    return userSiteUrlError(url) === "" ? "public" : ""
}

// An IPv4 literal (any form) in 10/8, 172.16/12, 192.168/16, 169.254/16 or
// 0/8. Added sites never reach one; isLocalAddress covers loopback.
function isPrivateLiteral(host) {
    var normalized = normalizeHost(host)
    var labels = normalized.split(".")
    if (!/^(0x[0-9a-f]*|[0-9]+)$/.test(labels[labels.length - 1]))
        return false
    var value = ipv4Value(normalized)
    if (value < 0)
        return true
    var first = Math.floor(value / 16777216)
    var second = Math.floor(value / 65536) % 256
    return first === 10 || first === 0 || (first === 172 && second >= 16 && second <= 31)
        || (first === 192 && second === 168) || (first === 169 && second === 254)
}

// {ok, error} for one stored entry: exactly id, name and url, an id not in
// others, a valid name and address. others: the other added sites.
function validateUserSite(entry, others) {
    var fail = function (code) { return { ok: false, error: code } }
    if (entry === null || typeof entry !== "object" || Array.isArray(entry))
        return fail("entry")
    var keys = Object.keys(entry)
    if (keys.length !== USER_SITE_KEYS.length || !USER_SITE_KEYS.every(function (key) {
        return keys.indexOf(key) >= 0
    }))
        return fail("entry")
    if (!isUserSiteId(entry.id))
        return fail("id")
    var list = Array.isArray(others) ? others : []
    for (var index = 0; index < list.length; index++) {
        if (list[index] && list[index].id === entry.id)
            return fail("id-taken")
    }
    var nameError = userSiteNameError(entry.name, list)
    if (nameError !== "")
        return fail(nameError)
    var urlError = userSiteUrlError(entry.url)
    if (urlError !== "")
        return fail(urlError)
    return { ok: true, error: "" }
}

// chatUserSites as {ok, sites}: sites are the valid entries in order (at
// most MAX_USER_SITES, as {id, name, url}); ok only when the text is a JSON
// array within MAX_USER_SITES_CHARS and every entry is valid and unique.
// Only an ok read may ever remove or delete anything.
function parseUserSites(text) {
    var result = { ok: false, sites: [] }
    if (typeof text !== "string" || text.length > MAX_USER_SITES_CHARS)
        return result
    var parsed = null
    try {
        parsed = JSON.parse(text)
    } catch (error) {
        return result
    }
    if (!Array.isArray(parsed))
        return result
    var ok = parsed.length <= MAX_USER_SITES
    for (var index = 0; index < parsed.length; index++) {
        if (result.sites.length >= MAX_USER_SITES)
            break
        var entry = parsed[index]
        if (!validateUserSite(entry, result.sites).ok) {
            ok = false
            continue
        }
        result.sites.push({ id: entry.id, name: entry.name, url: entry.url })
    }
    result.ok = ok
    return result
}

// The text to store for the list, keys in id, name, url order; "" (don't
// write) when any entry is invalid or a cap is passed.
function serializeUserSites(list) {
    if (!Array.isArray(list) || list.length > MAX_USER_SITES)
        return ""
    var clean = []
    for (var index = 0; index < list.length; index++) {
        if (!validateUserSite(list[index], clean).ok)
            return ""
        clean.push({ id: list[index].id, name: list[index].name, url: list[index].url })
    }
    var text = JSON.stringify(clean)
    return text.length > MAX_USER_SITES_CHARS ? "" : text
}

// The valid entries of a userSites list as {id, name, url}, in order; an id
// or name (any case) seen before is left out, as are entries past
// MAX_USER_SITES. Anything that isn't a list is none.
function validUserSites(userSites) {
    var list = userSites !== null && typeof userSites === "object" && typeof userSites.length === "number"
        ? userSites : []
    var valid = []
    var ids = Object.create(null)
    var names = Object.create(null)
    for (var index = 0; index < list.length && valid.length < MAX_USER_SITES; index++) {
        var entry = list[index]
        if (!validateUserSite(entry, []).ok)
            continue
        var lowered = entry.name.toLowerCase()
        if (ids[entry.id] === true || names[lowered] === true)
            continue
        ids[entry.id] = true
        names[lowered] = true
        valid.push({ id: entry.id, name: entry.name, url: entry.url })
    }
    return valid
}

// The site object of a valid entry. Only name and url come from it; the
// hosts and class are built here, never read from the stored entry.
function userSiteFrom(entry) {
    return {
        id: entry.id,
        name: entry.name,
        url: entry.url,
        icon: "",
        user: true,
        site_hosts: [],
        auth_hosts: [],
        exact_hosts: [normalizeHost(parseUrl(entry.url).host)],
        local: false,
        local_kind: addressClass(entry.url),
        default_on: true,
        http_origin: ""
    }
}

// The site object of an added id, or null.
function userSite(siteId, userSites) {
    var valid = validUserSites(userSites)
    for (var index = 0; index < valid.length; index++) {
        if (valid[index].id === siteId)
            return userSiteFrom(valid[index])
    }
    return null
}

// Every added-site id written anywhere in a stored chatUserSites text, read
// or not, each once: what an unreadable value may still hold. Used only to
// warn, never to delete.
function rawUserSiteIds(text) {
    var found = typeof text === "string" ? text.slice(0, 4 * MAX_USER_SITES_CHARS).match(/user-[0-9a-f]{8}/g) : null
    var ids = []
    ;(found || []).forEach(function (id) {
        if (ids.indexOf(id) < 0)
            ids.push(id)
    })
    return ids
}

// The added sites applying a page's value would remove: every id in the
// applied text (raw, so unreadable entries count too) that the page's
// value doesn't hold (its entries when it reads whole, else its raw ids).
function removedUserSiteIds(appliedText, pageText) {
    var page = parseUserSites(pageText)
    var kept = page.ok ? page.sites.map(function (site) { return site.id }) : rawUserSiteIds(pageText)
    return rawUserSiteIds(appliedText).filter(function (id) { return kept.indexOf(id) < 0 })
}

// The exact host of each valid entry, {id: host}: what an id stands for.
function userSiteHosts(userSites) {
    var hosts = {}
    validUserSites(userSites).forEach(function (entry) {
        hosts[entry.id] = normalizeHost(parseUrl(entry.url).host)
    })
    return hosts
}

// --- Site order (chatSiteOrder) ---------------------------------------------

// The default order: built-ins, the added sites in their own order, Ollama.
function defaultOrder(userSites) {
    return siteIds(userSites).concat([OLLAMA_ENTRY.id])
}

// The stored order as a list of ids, or null for "" and for anything
// damaged (not a JSON array of strings, or an id twice).
function parseSiteOrder(orderText) {
    if (typeof orderText !== "string" || orderText === "" || orderText.length > 65536)
        return null
    var parsed = null
    try {
        parsed = JSON.parse(orderText)
    } catch (error) {
        return null
    }
    if (!Array.isArray(parsed))
        return null
    for (var index = 0; index < parsed.length; index++) {
        if (typeof parsed[index] !== "string" || parsed.indexOf(parsed[index]) !== index)
            return null
    }
    return parsed
}

// Every web site (built-in and added) and the Ollama entry, each once, in
// the stored order: unknown ids dropped, missing ones appended in default
// order, a missing Ollama always last. A damaged order counts as "".
function orderedSites(userSites, orderText) {
    var valid = validUserSites(userSites)
    var known = defaultOrder(valid)
    var stored = parseSiteOrder(orderText) || []
    var ids = stored.filter(function (id) { return known.indexOf(id) >= 0 })
    known.forEach(function (id) {
        if (id !== OLLAMA_ENTRY.id && ids.indexOf(id) < 0)
            ids.push(id)
    })
    if (ids.indexOf(OLLAMA_ENTRY.id) < 0)
        ids.push(OLLAMA_ENTRY.id)
    return ids.map(function (id) {
        if (id === OLLAMA_ENTRY.id)
            return OLLAMA_ENTRY
        for (var index = 0; index < valid.length; index++) {
            if (valid[index].id === id)
                return userSiteFrom(valid[index])
        }
        return byId(id)
    })
}

// The text to store for an order: "" when it is the default order (so the
// default stays "" in backups and diffs), else the full list.
function serializeSiteOrder(ids, userSites) {
    var valid = validUserSites(userSites)
    var order = orderedSites(valid, JSON.stringify(Array.isArray(ids) ? ids : []))
        .map(function (site) { return site.id })
    return order.join(",") === defaultOrder(valid).join(",") ? "" : JSON.stringify(order)
}

// ids with id moved delta places (clamped); a copy, unchanged when id is
// not in it.
function moveInOrder(ids, id, delta) {
    var list = Array.isArray(ids) ? ids.slice() : []
    var from = list.indexOf(id)
    var step = Number(delta)
    if (from < 0 || !isFinite(step) || Math.floor(step) !== step)
        return list
    var to = Math.max(0, Math.min(list.length - 1, from + step))
    list.splice(from, 1)
    list.splice(to, 0, id)
    return list
}

// The letter an added site's badge shows: the first code point of the
// trimmed name, upper-cased; "?" when there is none.
function badgeLetter(name) {
    var text = typeof name === "string" ? name.trim() : ""
    if (text === "")
        return "?"
    var first = text.charAt(0)
    var code = text.charCodeAt(0)
    if (code >= 0xd800 && code <= 0xdbff && text.length > 1) {
        var low = text.charCodeAt(1)
        if (low >= 0xdc00 && low <= 0xdfff)
            first = text.slice(0, 2)
    }
    return first.toUpperCase()
}

// --- Local web UI owner check -------------------------------------------------

// The port whose owner the helper must vouch for (self or system) before
// the main frame of a Local page goes to url: any address on this computer,
// default port by scheme. 0 when no check applies (other sites, other hosts,
// about:blank, unreadable addresses; those are blocked by classifyNavigation).
function localOwnerPort(request) {
    var info = request || {}
    var site = effectiveSite(info.siteId, info.customUrls, info.userSites)
    if (!site || site.local !== true)
        return 0
    var parsed = parseUrl(info.url)
    if (parsed === null || parsed.host === ""
            || (parsed.scheme !== "http" && parsed.scheme !== "https")
            || !isLocalAddress(parsed.host))
        return 0
    if (parsed.port !== "")
        return parseInt(parsed.port, 10)
    return parsed.scheme === "https" ? 443 : 80
}

// "skip" | "go" | "check" for a navigation request: "check" means reject it
// and ask the helper first. request.pass is the address a good check was
// just made for; it is used up by this navigation whatever the result.
// Subframes are not gated.
function localOwnerGate(request) {
    var info = request || {}
    if (info.isMainFrame === false || localOwnerPort(info) === 0)
        return "skip"
    var url = info.url === undefined || info.url === null ? "" : String(info.url)
    return typeof info.pass === "string" && info.pass !== "" && info.pass === url ? "go" : "check"
}

// --- Off-site notice ----------------------------------------------------------

var MAX_HOST_DISPLAY = 64

function punycodeDigit(digit) {
    return String.fromCharCode(digit < 26 ? 97 + digit : 22 + digit)
}

function punycodeAdapt(delta, points, first) {
    delta = first ? Math.floor(delta / 700) : Math.floor(delta / 2)
    delta += Math.floor(delta / points)
    var k = 0
    while (delta > 455) {
        delta = Math.floor(delta / 35)
        k += 36
    }
    return k + Math.floor(36 * delta / (delta + 38))
}

// RFC 3492 encoding of one label's code points (without "xn--"); "" on overflow.
function punycodeEncode(codePoints) {
    var output = []
    for (var index = 0; index < codePoints.length; index++) {
        if (codePoints[index] < 128)
            output.push(String.fromCharCode(codePoints[index]))
    }
    var basic = output.length
    var handled = basic
    if (basic > 0)
        output.push("-")
    var n = 128
    var delta = 0
    var bias = 72
    while (handled < codePoints.length) {
        var next = 0x10ffff + 1
        for (index = 0; index < codePoints.length; index++) {
            if (codePoints[index] >= n && codePoints[index] < next)
                next = codePoints[index]
        }
        delta += (next - n) * (handled + 1)
        if (delta > 0x7fffffff)
            return ""
        n = next
        for (index = 0; index < codePoints.length; index++) {
            var point = codePoints[index]
            if (point < n)
                delta++
            if (point !== n)
                continue
            var q = delta
            for (var k = 36; ; k += 36) {
                var t = k <= bias ? 1 : (k >= bias + 26 ? 26 : k - bias)
                if (q < t)
                    break
                output.push(punycodeDigit(t + (q - t) % (36 - t)))
                q = Math.floor((q - t) / (36 - t))
            }
            output.push(punycodeDigit(q))
            bias = punycodeAdapt(delta, handled + 1, handled === basic)
            delta = 0
            handled++
        }
        delta++
        n++
    }
    return output.join("")
}

function codePointsOf(text) {
    var points = []
    for (var index = 0; index < text.length; index++) {
        var code = text.charCodeAt(index)
        if (code >= 0xd800 && code <= 0xdbff && index + 1 < text.length) {
            var low = text.charCodeAt(index + 1)
            if (low >= 0xdc00 && low <= 0xdfff) {
                points.push((code - 0xd800) * 0x400 + (low - 0xdc00) + 0x10000)
                index++
                continue
            }
        }
        points.push(code)
    }
    return points
}

// The host of an http(s) address as plain ASCII: lower case, without user
// info, port or final dot; international labels as their "xn--" form, so
// look-alike letters can't pass for the real name. "" when there is no
// readable host.
function displayHost(url) {
    var text = String(url === undefined || url === null ? "" : url)
    var match = /^https?:\/\/([^\/?#]*)/i.exec(text)
    if (!match)
        return ""
    var authority = match[1]
    // Browsers read "\" as "/", so "evil.example\@good.example" is on
    // evil.example: unreadable rather than guessed.
    if (authority.indexOf("\\") >= 0)
        return ""
    authority = authority.slice(authority.lastIndexOf("@") + 1)
    var host
    if (authority.charAt(0) === "[") {
        var end = authority.indexOf("]")
        host = end > 0 ? authority.slice(0, end + 1).toLowerCase() : ""
        return /^\[[0-9a-f:.]+\]$/.test(host) ? host : ""
    }
    host = authority.replace(/:[0-9]*$/, "").toLowerCase()
    if (host.charAt(host.length - 1) === ".")
        host = host.slice(0, -1)
    if (host === "" || /[\u0000- %\\]/.test(host))
        return ""
    var labels = host.split(/[.。．｡]/)
    for (var index = 0; index < labels.length; index++) {
        var label = labels[index]
        if (/^[\u0000-\u007f]*$/.test(label))
            continue
        var encoded = punycodeEncode(codePointsOf(label))
        if (encoded === "")
            return ""
        labels[index] = "xn--" + encoded
    }
    host = labels.join(".")
    return /^[a-z0-9_\-]+(?:\.[a-z0-9_\-]+)*$/.test(host) ? host : ""
}

// Long hosts keep their end, where the real domain is.
function shortHost(host) {
    var text = String(host || "")
    return text.length > MAX_HOST_DISPLAY ? "…" + text.slice(-(MAX_HOST_DISPLAY - 1)) : text
}

// {off, host} for the page shown in a site's main frame: off when it is an
// http(s) page on a host outside the site's own, sign-in and custom hosts.
// host is shortHost(displayHost(url)), "" when unreadable (still off).
function offSiteHost(request) {
    var info = request || {}
    var site = effectiveSite(info.siteId, info.customUrls, info.userSites)
    var url = info.url === undefined || info.url === null ? "" : String(info.url)
    if (!site || !/^https?:/i.test(url))
        return { off: false, host: "" }
    var host = displayHost(url)
    if (host !== "" && knownHost(site, host))
        return { off: false, host: "" }
    return { off: true, host: shortHost(host) }
}

// {kind, host} naming a sign-in window: "page" with the host of its own
// http(s) address; while it has none (about:blank, empty, a page it was
// written into) "opener" with the host of request.openerUrl, the page that
// opened it; "unknown" when neither is readable. Hosts as in offSiteHost.
function overlayHost(request) {
    var info = request || {}
    var own = displayHost(info.url)
    if (own !== "")
        return { kind: "page", host: shortHost(own) }
    var opener = displayHost(info.openerUrl)
    if (opener !== "")
        return { kind: "opener", host: shortHost(opener) }
    return { kind: "unknown", host: "" }
}

// "allow" | "block" for an embedded frame. Frames may load https from any
// host and about:, blob:, data: or srcdoc content, but never this computer
// unless the site is Local, and Local frames get plain http only for the
// exact origin of its address. Unreadable http(s) addresses are blocked.
// Added sites' frames never reach a private or link-local IPv4 literal
// either; an added id without its entry gets no frame at all.
function classifySubframe(request) {
    var info = request || {}
    if (isUserSiteId(info.siteId) && effectiveSite(info.siteId, info.customUrls, info.userSites) === null)
        return "block"
    var url = info.url === undefined || info.url === null ? "" : String(info.url)
    var parsed = parseUrl(url)
    if (parsed === null)
        return /^https?:/i.test(url) ? "block" : "allow"
    if (parsed.scheme !== "http" && parsed.scheme !== "https")
        return "allow"
    var site = effectiveSite(info.siteId, info.customUrls, info.userSites)
    if (site !== null && site.user === true)
        return isLocalAddress(parsed.host) || isPrivateLiteral(parsed.host) ? "block" : "allow"
    if (site === null || site.local !== true)
        return isLocalAddress(parsed.host) ? "block" : "allow"
    if (parsed.scheme === "http")
        return httpAllowed(site, parsed) ? "allow" : "block"
    return "allow"
}

// "overlay" | "external" | "block" for a new-window request. Plain http is
// always blocked here, even for Local. A sign-in window ("overlay") opens
// only for a click (request.userInitiated === true); a script-opened one is
// blocked.
function classifyNewWindow(request) {
    var info = request || {}
    var site = effectiveSite(info.siteId, info.customUrls, info.userSites)
    if (!site)
        return "block"
    var url = info.url === undefined || info.url === null ? "" : String(info.url)
    var parsed = parseUrl(url)
    if (parsed !== null && parsed.host !== "" && !site.local && isLocalAddress(parsed.host))
        return "block"
    if (site.user === true && parsed !== null && parsed.host !== "" && isPrivateLiteral(parsed.host))
        return "block"
    var https = isHttpsUrl(url)
    var clicked = info.userInitiated === true
    if (info.isDialog && (https || url === "" || isAboutBlank(url)))
        return clicked ? "overlay" : "block"
    if (!https)
        return "block"
    if (hostMatches(parsed.host, site.auth_hosts))
        return clicked ? "overlay" : "block"
    return "external"
}

// Drops only the QtWebEngine/x.y.z product token; Chrome/platform stay intact.
function userAgent(defaultUa) {
    if (typeof defaultUa !== "string")
        return ""
    return defaultUa.replace(/\s*QtWebEngine\/\S+/g, "")
}

// Google's sign-in refuses embedded Chromium ("This browser or app may not be
// secure") but accepts a desktop Firefox, as qutebrowser found. Used only on
// that one page; everywhere else the real engine is announced.
var GOOGLE_SIGNIN_HOST = "accounts.google.com"
var GOOGLE_SIGNIN_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"

// https on exactly accounts.google.com (default port); no subdomains, look-
// alike suffixes, user info or other schemes.
function isGoogleSignInHost(url) {
    var parsed = parseUrl(url)
    return parsed !== null && parsed.scheme === "https"
        && parsed.host === GOOGLE_SIGNIN_HOST
        && (parsed.port === "" || parsed.port === "443")
}

// The user agent for a profile whose pages are at url (one address or a
// list): Firefox while any of them is Google's sign-in, otherwise
// userAgent(defaultUa).
function userAgentFor(url, defaultUa) {
    var urls = Array.isArray(url) ? url : [url]
    for (var index = 0; index < urls.length; index++) {
        if (isGoogleSignInHost(urls[index]))
            return GOOGLE_SIGNIN_UA
    }
    return userAgent(defaultUa)
}

// Preferred popup size in pixels for the given tab ("chat", "split" for the
// web split view, else usage), times scale (Settings → General → Size;
// anything odd is 1), clamped to the screen. Split is wide enough for two
// chat sites side by side.
function popupSize(tab, gu, availW, availH, scale) {
    var unit = Number(gu) > 0 ? Number(gu) : 18
    var factor = Number(scale) > 0 && isFinite(Number(scale)) ? Number(scale) : 1
    var minWidth = unit * 18
    var minHeight = unit * 15
    var chat = tab === "chat" || tab === "split"
    var width = Math.round(unit * (tab === "split" ? 52 : chat ? 34 : 23) * factor)
    var height = Math.round(unit * (chat ? 40 : 28) * factor)
    if (Number(availW) > 0)
        width = Math.min(width, Number(availW) - unit * 2)
    if (Number(availH) > 0)
        height = Math.min(height, Number(availH) - unit * 4)
    return { width: Math.max(minWidth, width), height: Math.max(minHeight, height) }
}

// The panel popup's width around split view (FullRepresentation resizes the
// window itself, since Plasma keeps the size it last closed at). In:
// show: split view is shown now; popupWidth, padding: the window's width and
// what it adds around the popup's content; splitWidth, normalWidth:
// popupSize() widths for "split" and for the tab shown without split;
// before: the width to go back to (0: none); repair: the first open of the
// session, when a width saved before narrowing (Plasma restart) is put back;
// maxPadding (optional): the largest padding that can be real.
// Returns {width: the new window width (0: leave it), before}; with
// maxPadding, a widening or repair that would use a padding outside
// 0..maxPadding (the window not laid out yet) returns {width: 0, before,
// wait: true} instead: try again later.
function splitWidthStep(input) {
    var step = input || {}
    var pixels = function (value) {
        var number = Number(value)
        return isFinite(number) && number > 0 ? Math.round(number) : 0
    }
    var popupWidth = pixels(step.popupWidth)
    var padding = pixels(step.padding)
    var before = pixels(step.before)
    var limit = pixels(step.maxPadding)
    var measured = Number(step.padding)
    if (limit > 0 && (step.show === true || step.repair === true)
            && !(isFinite(measured) && measured >= 0 && measured <= limit))
        return { width: 0, before: before, wait: true }
    var split = pixels(step.splitWidth) > 0 ? pixels(step.splitWidth) + padding : 0
    var normal = pixels(step.normalWidth) > 0 ? pixels(step.normalWidth) + padding : 0
    if (step.show === true) {
        // Already wide enough: keep the width to go back to.
        if (split > 0 && popupWidth < split)
            return { width: split, before: before > 0 ? before : popupWidth }
        return { width: 0, before: before }
    }
    if (before > 0)
        return { width: before, before: 0 }
    if (step.repair === true && split > 0 && normal > 0 && normal !== popupWidth
            && Math.abs(popupWidth - split) <= 1)
        return { width: normal, before: 0 }
    return { width: 0, before: 0 }
}
