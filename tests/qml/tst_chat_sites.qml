import QtQuick
import QtTest
import "../../plasmoid/contents/ui/ChatSites.js" as ChatSites
import "../../plasmoid/contents/ui/ChatStorage.js" as ChatStorage
import "../../plasmoid/contents/ui/OllamaChat.js" as OllamaChat
import "ChatSitesGolden.js" as Golden

TestCase {
    id: testCase
    name: "ChatSites"

    function nav(url, siteId, linkClicked, isMainFrame, customUrls) {
        return ChatSites.classifyNavigation({
            url: url,
            siteId: siteId === undefined ? "claude" : siteId,
            linkClicked: !!linkClicked,
            isMainFrame: isMainFrame === undefined ? true : isMainFrame,
            customUrls: customUrls
        })
    }

    // Clicked (userInitiated) unless clicked is false.
    function popup(url, siteId, isDialog, customUrls, clicked) {
        return ChatSites.classifyNewWindow({
            url: url,
            siteId: siteId === undefined ? "claude" : siteId,
            isDialog: !!isDialog,
            userInitiated: clicked !== false,
            customUrls: customUrls
        })
    }

    function ids(list) {
        return list.map(function (s) { return s.id })
    }

    function checkUrl(siteId, text) {
        return ChatSites.validateCustomUrl(siteId, text)
    }

    // Task 005 golden table: every built-in answer recorded before added
    // sites existed must stay the same, with or without request.userSites.
    function test_builtinGoldenTable() {
        var added = [
            { id: "user-3fa9c01b", name: "Le Chat", url: "https://chat.mistral.ai/chat" },
            { id: "user-00000001", name: "Claude look-alike", url: "https://claude.ai/new" },
            { id: "user-00000002", name: "Example", url: "https://example.com/page" }
        ]
        // Task 006: added sites on this computer and the home network change
        // no built-in answer.
        var home = added.concat([
            { id: "user-00000003", name: "Loopback http", url: "http://localhost:3000/" },
            { id: "user-00000004", name: "Loopback https", url: "https://127.0.0.1:8443/" },
            { id: "user-00000005", name: "Loopback v6", url: "http://[::1]:8080/" },
            { id: "user-00000006", name: "NAS chat", url: "http://192.168.1.20:3000/" },
            { id: "user-00000007", name: "Private https", url: "https://10.0.0.5/" },
            { id: "user-00000008", name: "Private v6", url: "http://[fd00::20]:3000/" }
        ])
        compare(ChatSites.validUserSites(home).length, 9)
        var variants = [undefined, [], added, home]
        var keys = Object.keys(Golden.EXPECTED)
        compare(keys.length, Golden.SITE_IDS.length * Golden.ADDRESSES.length * 2)
        for (var v = 0; v < variants.length; v++) {
            var now = Golden.table(ChatSites, variants[v])
            compare(Object.keys(now).length, keys.length)
            for (var index = 0; index < keys.length; index++)
                compare(now[keys[index]], Golden.EXPECTED[keys[index]], "variant " + v + ": " + keys[index])
        }
    }

    // --- task 005: added sites -----------------------------------------------

    readonly property var mistral: ({id: "user-3fa9c01b", name: "Le Chat", url: "https://chat.mistral.ai/chat"})
    readonly property var pi: ({id: "user-0000beef", name: "Pi", url: "https://pi.ai/talk"})
    readonly property var added: [mistral, pi]

    // userSites: the added sites, all of them when left out (arguments
    // count, so an explicit undefined stays undefined).
    function userNav(url, linkClicked, isMainFrame, userSites) {
        return ChatSites.classifyNavigation({
            url: url, siteId: "user-3fa9c01b", linkClicked: !!linkClicked,
            isMainFrame: isMainFrame === undefined ? true : isMainFrame,
            userSites: arguments.length > 3 ? userSites : testCase.added
        })
    }

    function userPopup(url, isDialog, clicked, userSites) {
        return ChatSites.classifyNewWindow({
            url: url, siteId: "user-3fa9c01b", isDialog: !!isDialog, userInitiated: clicked !== false,
            userSites: arguments.length > 3 ? userSites : testCase.added
        })
    }

    // --- task 006: added sites on this computer and the home network ---------

    function test_parseUserUrl() {
        var parse = ChatSites.parseUserUrl
        compare(parse("http://[FD00::1]:3000/x"), {scheme: "http", host: "[fd00::1]", port: "3000"})
        compare(parse("HTTPS://[fd00::1]"), {scheme: "https", host: "[fd00::1]", port: ""})
        compare(parse("https://[::1]:08080/"), {scheme: "https", host: "[::1]", port: "8080"})
        compare(parse("https://chat.example.org/"), ChatSites.parseUrl("https://chat.example.org/"))
        compare(parse("ftp://a.example/"), {scheme: "ftp", host: "", port: ""})
        compare(parse("ftp://[fd00::1]/"), {scheme: "ftp", host: "", port: ""})
        ;["http://[fe80::1%25eth0]/", "http://[::ffff:192.168.1.1]/", "http://[f]/", "http://[]/",
          "http://[fd00::1]:0/", "http://[fd00::1]:65536/", "http://[fd00::1]:/", "http://[fd00::1]x/",
          "http://[" + new Array(41).join("a") + "]/", "http:[fd00::1]",
          "http://u@[fd00::1]/", "http://[fd00::g]/"].forEach(function (url) {
            compare(parse(url), null, url)
        })
        // The narrow parser is untouched: built-ins still read [::1] alone.
        compare(ChatSites.parseUrl("http://[fd00::1]/"), null)
        compare(ChatSites.parseUrl("http://[::1]/").host, "[::1]")
    }

    function test_canonicalIpv4() {
        ;["0.0.0.0", "10.0.0.1", "192.168.1.20", "255.255.255.255", "172.31.255.255"].forEach(function (host) {
            verify(ChatSites.canonicalIpv4(host), host)
        })
        ;["127.1", "0x7f.0.0.1", "010.0.0.1", "3232235777", "192.168.1.020", "192.168.1", "192.168.1.20.",
          "256.1.1.1", "1.2.3.4.5", "1.2.3.1000", "", undefined, "a.b.c.d"].forEach(function (host) {
            verify(!ChatSites.canonicalIpv4(host), String(host))
        })
    }

    function test_canonicalIpv6() {
        var c = ChatSites.canonicalIpv6
        compare(c("fd00::1"), "fd00::1")
        compare(c("FD00::1"), "fd00::1")
        compare(c("[FD00::1]"), "[fd00::1]")
        compare(c("fd00:0:0:0:0:0:0:1"), "fd00::1")
        compare(c("fd00::0:1"), "fd00::1")
        compare(c("fd00:0:1:1:1:1:1:1"), "fd00:0:1:1:1:1:1:1", "one zero group stays")
        compare(c("fd00:1:0:0:1:0:0:1"), "fd00:1::1:0:0:1", "the first longest run")
        compare(c("fd00:0:0:1:0:0:0:1"), "fd00:0:0:1::1", "the longest run")
        compare(c("0:0:0:0:0:0:0:0"), "::")
        compare(c("0:0:0:0:0:0:0:1"), "::1")
        compare(c("fc00:0:0:0:0:0:0:0"), "fc00::")
        compare(c("00fd::0001"), "fd::1")
        compare(c("1:2:3:4:5:6:7::"), "1:2:3:4:5:6:7:0")
        compare(c("::2:3:4:5:6:7:8"), "0:2:3:4:5:6:7:8")
        ;["", ":", ":::", "1:::2", "1::2::3", ":1:2:3:4:5:6:7:8", "1:2:3:4:5:6:7:8:", "1:2:3:4:5:6:7",
          "1:2:3:4:5:6:7:8:9", "1::2:3:4:5:6:7:8", "12345::", "g::", "1.2.3.4", undefined].forEach(function (text) {
            compare(c(text), "", String(text))
        })
    }

    // Plan §3.3 and §7: every code and class, first failure wins.
    function test_userSiteUrlErrorHomeTable() {
        var table = [
            // Loopback: these three spellings, http or https, any port.
            ["http://localhost:3000/", "", "loopback"], ["https://localhost/", "", "loopback"],
            ["HTTP://LOCALHOST:3000/", "", "loopback"], ["http://127.0.0.1/", "", "loopback"],
            ["https://127.0.0.1:8443/", "", "loopback"], ["http://[::1]:8080/", "", "loopback"],
            ["http://localhost:1/", "", "loopback"], ["http://localhost:65535/", "", "loopback"],
            ["http://localhost:0/", "malformed", ""], ["http://localhost:65536/", "malformed", ""],
            ["http://localhost./", "loopback-not-allowed", ""], ["http://127.0.0.2/", "loopback-not-allowed", ""],
            ["https://127.1/", "loopback-not-allowed", ""], ["http://0.0.0.0/", "loopback-not-allowed", ""],
            ["http://foo.localhost/", "loopback-not-allowed", ""],
            ["http://localhost.localdomain/", "loopback-not-allowed", ""],
            ["http://nas/", "loopback-not-allowed", ""], ["http://3232235777/", "loopback-not-allowed", ""],
            // Private IPv4: the edges of each range.
            ["http://10.0.0.0/", "", "private"], ["http://10.255.255.255/", "", "private"],
            ["http://172.15.255.255/", "ip-literal", ""], ["http://172.16.0.0/", "", "private"],
            ["http://172.31.255.255/", "", "private"], ["http://172.32.0.0/", "ip-literal", ""],
            ["http://192.167.255.255/", "ip-literal", ""], ["http://192.168.0.0/", "", "private"],
            ["http://192.168.255.255/", "", "private"], ["http://192.168.1.20:3000/", "", "private"],
            ["https://10.0.0.5/", "", "private"], ["http://192.168.1.20:80/", "", "private"],
            ["http://169.254.169.254/", "link-local", ""], ["http://100.64.0.1/", "ip-literal", ""],
            ["https://8.8.8.8/", "ip-literal", ""], ["http://255.255.255.255/", "ip-literal", ""],
            ["http://0.1.2.3/", "ip-literal", ""], ["http://224.0.0.1/", "ip-literal", ""],
            // Not canonical IPv4.
            ["http://192.168.1.020/", "ip-form", ""], ["http://0xc0.168.1.1/", "ip-form", ""],
            ["http://192.168.1/", "ip-form", ""], ["http://192.168.1.20./", "ip-form", ""],
            ["http://010.0.0.1/", "ip-form", ""], ["http://256.1.1.1/", "loopback-not-allowed", ""],
            // IPv6.
            ["http://[fd00::1]/", "", "private"], ["http://[FD00::1]/", "", "private"],
            ["http://[fd00:0:0:0:0:0:0:1]/", "ip-form", ""], ["http://[fd00::0:1]/", "ip-form", ""],
            ["http://[fd00:0:1:1:1:1:1:1]/", "", "private"], ["http://[fd00:1:0:0:1:0:0:1]/", "ip-form", ""],
            ["http://[fd00:1::1:0:0:1]/", "", "private"], ["http://[fc00::]/", "", "private"],
            ["https://[fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff]:65535/", "", "private"],
            ["http://[fe80::1]/", "link-local", ""], ["http://[febf::1]/", "link-local", ""],
            ["http://[fec0::1]/", "ip-literal", ""], ["http://[fe80::1%25eth0]/", "malformed", ""],
            ["http://[2001:db8::1]/", "ip-literal", ""], ["http://[::ffff:192.168.1.1]/", "malformed", ""],
            ["http://[::ffff:c0a8:101]/", "ip-literal", ""], ["http://[::]/", "ip-literal", ""],
            ["http://[ff02::1]/", "ip-literal", ""], ["http://[0:0:0:0:0:0:0:1]/", "ip-form", ""],
            ["http://[1::2::3]/", "ip-form", ""], ["http://[fd00::1]:0/", "malformed", ""],
            // LOW-1: fd00:ec2::/32, the cloud metadata range, as link-local.
            ["http://[fd00:ec2::254]/", "link-local", ""], ["https://[fd00:ec2::254]/", "link-local", ""],
            ["http://[fd00:ec2::]/", "link-local", ""],
            ["http://[fd00:ec2:ffff:ffff:ffff:ffff:ffff:ffff]:8080/", "link-local", ""],
            ["http://[FD00:EC2::254]/", "link-local", ""], ["http://[fd00:0ec2::254]/", "ip-form", ""],
            ["http://[fd00:ec1:ffff:ffff:ffff:ffff:ffff:ffff]/", "", "private"],
            ["http://[fd00:ec3::1]/", "", "private"], ["http://[fd01:ec2::1]/", "", "private"],
            ["http://[fd00::ec2]/", "", "private"],
            // DNS names: https only.
            ["http://nas.local/", "http-not-allowed", ""], ["http://nas.lan:3000/", "http-not-allowed", ""],
            ["https://nas.local/", "", "public"], ["http://chat.example.org/", "http-not-allowed", ""],
            // The order: scheme before anything about the host.
            ["ftp://192.168.1.20/", "scheme", ""], ["ws://localhost/", "scheme", ""]
        ]
        table.forEach(function (row) {
            compare(ChatSites.userSiteUrlError(row[0]), row[1], row[0])
            compare(ChatSites.addressClass(row[0]), row[2], row[0])
            var entry = {id: "user-00000009", name: "Home", url: row[0]}
            compare(ChatSites.validateUserSite(entry, []).error, row[1], row[0])
            compare(ChatSites.parseUserSites(JSON.stringify([entry])).ok, row[1] === "", row[0])
        })
        // The longest IPv6 entry still fits the address cap.
        var longest = "https://[fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff]:65535/"
        compare(ChatSites.userSiteUrlError(longest + new Array(ChatSites.MAX_CUSTOM_URL_LENGTH - longest.length + 1)
                                           .join("x")), "")
    }

    readonly property var nas: ({id: "user-0000a001", name: "NAS chat", url: "http://192.168.1.20:3000/"})
    readonly property var nasV6: ({id: "user-0000a002", name: "NAS v6", url: "http://[fd00::20]:3000/"})
    readonly property var webui: ({id: "user-0000a003", name: "My UI", url: "http://localhost:3000/"})
    readonly property var secureUi: ({id: "user-0000a004", name: "Secure UI", url: "https://127.0.0.1:8443/app"})
    readonly property var homeSites: [mistral, nas, nasV6, webui, secureUi]

    function homeNav(site, url, linkClicked, isMainFrame) {
        return ChatSites.classifyNavigation({
            url: url, siteId: site.id, linkClicked: !!linkClicked,
            isMainFrame: isMainFrame === undefined ? true : isMainFrame, userSites: testCase.homeSites
        })
    }

    function test_userSiteFromHomeSites() {
        var site = ChatSites.effectiveSite(testCase.nas.id, {}, testCase.homeSites)
        compare(site.local, false)
        compare(site.local_kind, "private")
        compare(site.origin, "http://192.168.1.20:3000")
        compare(site.exact_hosts, ["192.168.1.20"])
        compare(site.http_origin, "")
        site = ChatSites.effectiveSite(testCase.nasV6.id, {}, testCase.homeSites)
        compare(site.local_kind, "private")
        compare(site.origin, "http://[fd00::20]:3000")
        compare(site.exact_hosts, ["[fd00::20]"])
        site = ChatSites.effectiveSite(testCase.webui.id, {}, testCase.homeSites)
        compare(site.local, false, "never Local's branches")
        compare(site.local_kind, "loopback")
        compare(site.origin, "http://localhost:3000")
        compare(ChatSites.effectiveSite(testCase.secureUi.id, {}, testCase.homeSites).origin, "https://127.0.0.1:8443")
        compare(ChatSites.userOriginOf("https://a.example/"), "https://a.example:443")
        compare(ChatSites.userOriginOf("http://a.example/"), "http://a.example:80")
        compare(ChatSites.userOriginOf({url: "http://[FD00::1]:81/x"}), "http://[fd00::1]:81")
        compare(ChatSites.userOriginOf("ftp://a.example/"), "")
        compare(ChatSites.userOriginOf(undefined), "")
        // Hosts for M1, IPv6 too.
        compare(ChatSites.userSiteHosts([testCase.nasV6, testCase.webui]),
                {"user-0000a002": "[fd00::20]", "user-0000a003": "localhost"})
        compare(ChatSites.rawUserSiteHosts(JSON.stringify([testCase.nasV6, {id: "user-0000a005",
                                                                            url: "http://[FE80::1]/"}])),
                {"user-0000a002": "[fd00::20]", "user-0000a005": "[fe80::1]"})
    }

    function test_privateSiteNavigation() {
        ;[[testCase.nas, "http://192.168.1.20:3000/", "192.168.1.20"],
          [testCase.nasV6, "http://[fd00::20]:3000/", "[fd00::20]"]].forEach(function (row) {
            var site = row[0]
            var own = row[1]
            var host = row[2]
            compare(homeNav(site, own), "allow", own)
            compare(homeNav(site, own + "chat?x=1#y", true), "allow", "clicked, own origin")
            compare(homeNav(site, own.replace(":3000/", "/")), "block", "same host, port 80")
            compare(homeNav(site, own.replace(":3000/", ":3001/")), "block", "another port")
            compare(homeNav(site, own.replace("http:", "https:")), "block", "the other scheme")
            ;["http://192.168.1.21:3000/", "https://192.168.1.21/", "http://10.0.0.1/", "https://172.16.0.1/",
              "https://169.254.169.254/", "https://192.168.1.020:3000/", "https://0xc0.0xa8.1.20/",
              "https://3232235796/", "http://[fd00::21]:3000/", "https://[fe80::1]/", "https://[2001:db8::1]/",
              "https://[fd00:0:0:0:0:0:0:20]:3000/", "http://localhost:3000/", "https://localhost/",
              "https://127.0.0.1/", "https://127.0.0.2/", "https://[::1]/", "https://nas/",
              "https://foo.localhost/", "http://chat.example.org/", "ftp://a.example/",
              "javascript:alert(1)", "http://[fd00::1%25eth0]/", "file:///etc/passwd"].forEach(function (url) {
                compare(homeNav(site, url), "block", site.name + " main: " + url)
                compare(homeNav(site, url, false, false), url.indexOf("http") === 0 ? "block" : "allow",
                        site.name + " frame: " + url)
            })
            compare(homeNav(site, "about:blank"), "allow")
            // Public https, as for any site; a clicked link off the site goes out.
            compare(homeNav(site, "https://cdn.example.org/a.js"), "allow")
            compare(homeNav(site, "https://cdn.example.org/", true), "external")
            compare(homeNav(site, "https://cdn.example.org/", false, false), "allow")
            compare(homeNav(site, own, false, false), "allow", "frames of its own origin")
            ;["about:srcdoc", "blob:http://192.168.1.20:3000/x", "data:text/html,x"].forEach(function (url) {
                compare(homeNav(site, url, false, false), "allow", url)
            })
            // New windows: never its own origin or anything local (M-G).
            var popup = function (url, isDialog) {
                return ChatSites.classifyNewWindow({url: url, siteId: site.id, isDialog: !!isDialog,
                                                    userInitiated: true, userSites: testCase.homeSites})
            }
            compare(popup(own), "block")
            compare(popup(own, true), "block")
            compare(popup(own.replace("http:", "https:"), true), "block")
            compare(popup("https://127.0.0.1/"), "block")
            compare(popup("https://cdn.example.org/"), "external")
            // isPageUrl: its own origin and public https only.
            var effective = ChatSites.effectiveSite(site.id, {}, testCase.homeSites)
            verify(ChatSites.isPageUrl(effective, own + "x"))
            verify(ChatSites.isPageUrl(effective, "https://cdn.example.org/"))
            ;[own.replace(":3000/", ":3001/"), own.replace("http:", "https:"), "http://cdn.example.org/",
              "https://192.168.1.21/", "https://[fd00::21]/", "https://localhost/",
              "https://169.254.169.254/"].forEach(function (url) {
                verify(!ChatSites.isPageUrl(effective, url), url)
            })
            // LOW-2: its own host is checked, with its address (it may be
            // this computer's own); nothing else is.
            var owner = function (url) {
                var request = {siteId: site.id, userSites: testCase.homeSites, url: url}
                return [ChatSites.localOwnerPort(request), ChatSites.localOwnerAddress(request)]
            }
            compare(owner(own), [3000, host])
            compare(owner(own + "c/1?x"), [3000, host])
            compare(owner(own.replace(":3000/", ":3001/")), [3001, host], "blocked anyway, still fails closed")
            compare(owner(own.replace(":3000/", "/")), [80, host])
            compare(owner("https://cdn.example.org/"), [0, ""])
            compare(owner("http://localhost:3000/"), [0, ""])
            compare(owner("about:blank"), [0, ""])
            verify(ChatSites.ownerChecked(site.id, {}, testCase.homeSites))
            compare(ChatSites.localOwnerGate({siteId: site.id, userSites: testCase.homeSites, url: own,
                                              isMainFrame: true, pass: ""}), "check")
            // The off-site notice knows its own host.
            compare(ChatSites.offSiteHost({siteId: site.id, userSites: testCase.homeSites, url: own}).off, false)
            compare(ChatSites.offSiteHost({siteId: site.id, userSites: testCase.homeSites,
                                           url: "https://cdn.example.org/"}),
                    {off: true, host: "cdn.example.org"})
            verify(host !== "")
        })
    }

    function test_loopbackSiteNavigation() {
        var site = testCase.webui
        compare(homeNav(site, "http://localhost:3000/c/1"), "allow")
        ;["http://localhost:3001/", "https://localhost:3000/", "http://127.0.0.1:3000/", "http://[::1]:3000/",
          "http://localhost./", "http://localhost.:3000/", "http://127.0.0.2:3000/", "http://127.1:3000/",
          "http://192.168.1.20:3000/", "http://[fd00::1]/", "https://[fe80::1]/",
          "http://chat.example.org/"].forEach(function (url) {
            compare(homeNav(site, url), "block", url)
            compare(homeNav(site, url, false, false), "block", "frame " + url)
        })
        compare(homeNav(site, "https://cdn.example.org/"), "allow")
        compare(homeNav(site, "https://cdn.example.org/", true), "external")
        // The owner check: its own port, explicit or by scheme.
        var port = function (s, url) {
            return ChatSites.localOwnerPort({siteId: s.id, userSites: testCase.homeSites, url: url})
        }
        compare(port(site, "http://localhost:3000/"), 3000)
        compare(port(testCase.secureUi, "https://127.0.0.1:8443/"), 8443)
        var defaults = [{id: "user-0000b001", name: "D80", url: "http://localhost/"},
                        {id: "user-0000b002", name: "D443", url: "https://[::1]/"}]
        compare(ChatSites.localOwnerPort({siteId: "user-0000b001", userSites: defaults, url: "http://localhost/"}), 80)
        compare(ChatSites.localOwnerPort({siteId: "user-0000b002", userSites: defaults, url: "https://[::1]/"}), 443)
        // Every this-computer target is gated, even ones blocked later.
        compare(port(site, "http://127.0.0.2:4000/"), 4000)
        compare(port(site, "https://cdn.example.org/"), 0)
        compare(port(site, "about:blank"), 0)
        compare(port(testCase.mistral, "https://localhost/"), 0, "public added sites: none")
        compare(port(testCase.nas, "http://localhost:3000/"), 0)
        compare(ChatSites.localOwnerAddress({siteId: site.id, userSites: testCase.homeSites,
                                             url: "http://localhost:3000/"}), "", "this computer: no address")
        compare(ChatSites.localOwnerAddress({siteId: "local", url: "http://localhost:3000/"}), "")
        compare(ChatSites.localOwnerAddress({siteId: testCase.mistral.id, userSites: testCase.homeSites,
                                             url: "https://chat.mistral.ai/"}), "")
        verify(ChatSites.ownerChecked(site.id, {}, testCase.homeSites))
        verify(ChatSites.ownerChecked(testCase.secureUi.id, {}, testCase.homeSites))
        verify(ChatSites.ownerChecked("local"))
        verify(!ChatSites.ownerChecked(testCase.mistral.id, {}, testCase.homeSites))
        verify(!ChatSites.ownerChecked("claude"))
        verify(!ChatSites.ownerChecked(site.id, {}, []), "unknown without its entry")
        // The gate follows: check, then go with the pass.
        var gate = function (pass) {
            return ChatSites.localOwnerGate({siteId: site.id, userSites: testCase.homeSites,
                                             url: "http://localhost:3000/", isMainFrame: true, pass: pass})
        }
        compare(gate(""), "check")
        compare(gate("http://localhost:3000/"), "go")
        compare(ChatSites.localOwnerGate({siteId: site.id, userSites: testCase.homeSites,
                                          url: "http://localhost:3000/", isMainFrame: false}), "skip")
        // New windows, even to its own origin.
        compare(ChatSites.classifyNewWindow({url: "http://localhost:3000/", siteId: site.id, isDialog: true,
                                             userInitiated: true, userSites: testCase.homeSites}), "block")
        compare(ChatSites.classifyNewWindow({url: "https://127.0.0.1:8443/", siteId: testCase.secureUi.id,
                                             isDialog: true, userInitiated: true,
                                             userSites: testCase.homeSites}), "block")
        var effective = ChatSites.effectiveSite(site.id, {}, testCase.homeSites)
        verify(ChatSites.isPageUrl(effective, "http://localhost:3000/x"))
        verify(!ChatSites.isPageUrl(effective, "http://127.0.0.1:3000/x"))
    }

    // A public added site is unchanged: every home target stays blocked.
    function test_publicAddedSiteStillBlocksHomeTargets() {
        ;["http://localhost:3000/", "https://localhost/", "https://192.168.1.20/", "http://192.168.1.20:3000/",
          "https://[fd00::20]/", "http://[fd00::20]:3000/", "https://[::1]/"].forEach(function (url) {
            compare(homeNav(testCase.mistral, url), "block", url)
            compare(homeNav(testCase.mistral, url, false, false), "block", "frame " + url)
        })
        compare(homeNav(testCase.mistral, "https://chat.mistral.ai/x"), "allow")
    }

    // ChatSites.js has no imports: its copy of Ollama's entry stays equal.
    function test_ollamaEntryMirrorsOllamaChat() {
        compare(ChatSites.OLLAMA_ENTRY, OllamaChat.ENTRY)
        compare(Object.keys(ChatSites.OLLAMA_ENTRY), Object.keys(OllamaChat.ENTRY))
        verify(Object.isFrozen(ChatSites.OLLAMA_ENTRY))
    }

    function test_userSiteCaps() {
        compare(ChatSites.MAX_USER_SITES, 200)
        compare(ChatSites.MAX_USER_SITES_CHARS, 448 * 1024)
        compare(ChatSites.MAX_USER_SITE_NAME, 40)
        compare(ChatSites.MAX_USER_SITES + ChatSites.sites.length, ChatStorage.MAX_SITE_IDS)
        compare(ChatSites.MAX_USER_SITES + 7, 207)
    }

    function test_isUserSiteId() {
        verify(ChatSites.isUserSiteId("user-3fa9c01b"))
        verify(!ChatSites.isUserSiteId("user-3FA9C01B"))
        verify(!ChatSites.isUserSiteId("user-3fa9c01"))
        verify(!ChatSites.isUserSiteId("user-3fa9c01bb"))
        verify(!ChatSites.isUserSiteId("claude"))
        verify(!ChatSites.isUserSiteId(" user-3fa9c01b"))
        verify(!ChatSites.isUserSiteId(undefined))
        // No built-in id looks like an added one.
        ChatSites.siteIds().forEach(function (id) { verify(id.indexOf("user-") !== 0, id) })
    }

    function test_newUserSiteId() {
        var seq = function (values) {
            var at = 0
            return function () { return values[at++ % values.length] }
        }
        // Deterministic with an injected random: 8 hex digits.
        compare(ChatSites.newUserSiteId([], seq([0])), "user-00000000")
        compare(ChatSites.newUserSiteId([], seq([0.999])), "user-ffffffff")
        compare(ChatSites.newUserSiteId([], seq([0.2, 0.25, 0.5, 0.75])), "user-348c348c")
        // Never an excluded id: the next draw is taken.
        var draws = [0, 0, 0, 0, 0, 0, 0, 0, 0.0625, 0, 0, 0, 0, 0, 0, 0]
        compare(ChatSites.newUserSiteId(["user-00000000"], seq(draws)), "user-10000000")
        // Nothing free: "".
        compare(ChatSites.newUserSiteId(["user-00000000"], seq([0])), "")
        // Odd random values give digits in range.
        verify(ChatSites.isUserSiteId(ChatSites.newUserSiteId([], seq([NaN, -1, 2]))))
        // The real one.
        for (var index = 0; index < 20; index++)
            verify(ChatSites.isUserSiteId(ChatSites.newUserSiteId([], Math.random)))
    }

    function test_userSiteNameError() {
        var err = function (name, others) { return ChatSites.userSiteNameError(name, others) }
        var hex = function (text) {
            return text.split("").map(function (unit) { return unit.charCodeAt(0).toString(16) }).join(" ")
        }
        compare(err("Le Chat"), "")
        compare(err(""), "name-empty")
        compare(err("   "), "name-empty")
        compare(err("\u3000"), "name-empty")
        compare(err(undefined), "name-empty")
        compare(err(7), "name-empty")
        compare(err(new Array(41).join("a")), "")
        compare(err(new Array(42).join("a")), "name-too-long")
        // UTF-16 units: an emoji is two.
        compare(err(new Array(20).join("\ud83d\ude00") + "ab"), "")
        compare(err(new Array(21).join("\ud83d\ude00") + "a"), "name-too-long")
        compare(err("é" + new Array(40).join("x")), "")
        compare(err(" A"), "name-chars", "stored trimmed")
        compare(err("A "), "name-chars")
        compare(err("A\tB"), "name-chars")
        compare(err("A\nB"), "name-chars")
        compare(err("A\u0085B"), "name-chars", "C1")
        compare(err("A<B"), "name-chars")
        compare(err("A>B"), "name-chars")
        compare(err("A&B"), "name-chars")
        compare(err("A\ud800B"), "name-chars", "lone surrogate")
        compare(err("A\udc00"), "name-chars")
        // Every Default_Ignorable_Code_Point and the other invisible marks
        // (round 2, SEC M-1), at both ends of each range: inside a name,
        // after a built-in's name, and alone.
        ;["\u00ad", "\u034f", "\u061c", "ᅟ", "ᅠ", "\u17b4", "\u17b5", "\u180b", "\u180e", "\u180f",
          "\u200b", "\u200f", "\u2028", "\u2029", "\u202a", "\u202e", "\u2060", "\u2065", "\u206f",
          "⠀", "ㅤ", "\ufe00", "\ufe0f", "\ufeff", "ﾠ", "\ufff0", "\ufff8", "\ufff9", "\ufffb",
          "\ud82f\udca0", "\ud82f\udca3", "\ud834\udd73", "\ud834\udd7a", "\udb40\udc00", "\udb40\udc01",
          "\udb40\udc20", "\udb43\udfff"].forEach(function (mark) {
            compare(err("A" + mark + "B"), "name-chars", hex(mark))
            compare(err("Claude" + mark), "name-chars", "Claude + " + hex(mark))
            // Alone, the ones that are JS whitespace trim to nothing.
            compare(err(mark), mark.trim() === "" ? "name-empty" : "name-chars", "alone " + hex(mark))
        })
        // Their neighbours are allowed.
        ;["¬", "\u034e", "\u0350", "ឳ", "\u17b6", "‧", "⁰", "⟿", "⠁", "ㅣ",
          "ㅥ", "﷿", "︐", "ﾟ", "ﾡ", "\uffef", "￼", "\ud82f\udc9f", "\ud82f\udca4",
          "\ud834\udd72", "\ud834\udd7b", "\udb3f\udfff", "\udb44\udc00"].forEach(function (mark) {
            compare(err("A" + mark + "B"), "", hex(mark))
        })
        // At least one letter or digit.
        compare(err("..."), "name-chars")
        compare(err("-"), "name-chars")
        compare(err("\ud83d\ude00"), "name-chars", "an emoji alone")
        compare(err("\u0301"), "name-chars", "a combining mark alone")
        compare(err("7"), "")
        compare(err("١"), "", "Nd")
        compare(err("½"), "", "No")
        compare(err("Ⅰ"), "", "Nl")
        compare(err("日"), "", "Lo")
        compare(err("\ud840\udc00"), "", "astral Lo (U+20000)")
        compare(err("\ud835\udc00"), "", "U+1D400 math letter")
        compare(err("\ud83d\ude00 Chat"), "")
        compare(err("e\u0301"), "")
        // Other spaces inside are fine.
        compare(err("Le\u00a0Chat"), "")
        compare(err("Claude"), "name-taken")
        compare(err("claude"), "name-taken")
        compare(err("GITHUB COPILOT"), "name-taken")
        compare(err("Local web UI (Open WebUI)"), "name-taken")
        compare(err("ollama"), "name-taken")
        compare(err("le chat", [testCase.mistral]), "name-taken")
        compare(err("le chat", ["Le Chat"]), "name-taken")
        compare(err("Le Chat", [testCase.pi]), "")
        compare(err("Claude 2"), "")
    }

    // Round 3 (SEC I-5): no format (Cf) or private-use (Co) code point,
    // also those outside Default_Ignorable; their neighbours are allowed.
    function test_userSiteNameRefusesFormatAndPrivateUse() {
        var err = ChatSites.userSiteNameError
        ;["\u0600", "\u0605", "\u06dd", "\u070f", "\u0890", "\u0891", "\u08e2", "\ud804\udcbd", "\ud804\udccd", "\ud80d\udc30", "\ud80d\udc3f", "\ue000", "\uf8ff", "\udb80\udc00", "\udbbf\udffd", "\udbc0\udc00", "\udbff\udffd", "\udb40\udc01", "\udb40\udc7f"].forEach(function (mark, at) {
            compare(err("A" + mark + "B"), "name-chars", "refused " + at)
            compare(err("Claude" + mark), "name-chars", "after Claude " + at)
        })
        ;["\u05ff", "\u0606", "\u06dc", "\u06de", "\u070e", "\u0710", "\u088f", "\u0892", "\u08e1", "\u08e3", "\ud804\udcbc", "\ud804\udcbe", "\ud80d\udc2f", "\ud80d\udc40", "\ud7fb", "\uf900", "\udb7f\udfff"].forEach(function (mark, at) {
            compare(err("A" + mark + "B"), "", "allowed " + at)
        })
        // Unassigned (Cn) stays allowed: it renders as a box.
        compare(err("A\u0378B"), "")
    }

    // The shared Cf+Co table: Python 3.14 unicodedata 16.0.0, as the helper
    // uses it (settingsbackup.py); a few category facts.
    function test_formatPrivateTable() {
        compare(ChatSites.FORMAT_PRIVATE_RANGES, "ad,600-605,61c,6dd,70f,890-891,8e2,180e,200b-200f,202a-202e,2060-2064,2066-206f,e000-f8ff,feff,fff9-fffb,110bd,110cd,13430-1343f,1bca0-1bca3,1d173-1d17a,e0001,e0020-e007f,f0000-ffffd,100000-10fffd")
        ;[0xad, 0x600, 0x70f, 0x200b, 0xe000, 0xf8ff, 0xfeff, 0x110bd, 0xe0001, 0xf0000, 0x10fffd].forEach(function (point) {
            verify(ChatSites.isFormatOrPrivate(point), point.toString(16))
        })
        ;[0x41, 0xac, 0x5ff, 0x606, 0xdfff, 0xf900, 0xe0002, 0xe0080, 0xeffff, 0x10fffe, -1, 0x110000].forEach(function (point) {
            verify(!ChatSites.isFormatOrPrivate(point), point.toString(16))
        })
    }

    // The letter-or-digit table, against a few category facts.
    function test_isLetterOrDigit() {
        ;[0x30, 0x39, 0x41, 0x7a, 0xaa, 0xb2, 0x3a3, 0x661, 0x4e00, 0xac00, 0x2160, 0x1f100, 0x20000,
          0x1d400].forEach(function (point) {
            verify(ChatSites.isLetterOrDigit(point), point.toString(16))
        })
        ;[0x20, 0x2f, 0x3a, 0x40, 0x5b, 0x60, 0x7b, 0xad, 0x301, 0x200b, 0x2028, 0x3000, 0xd800, 0xdfff,
          0xe000, 0xfeff, 0x1f600, 0x10ffff, -1, 0x110000].forEach(function (point) {
            verify(!ChatSites.isLetterOrDigit(point), point.toString(16))
        })
    }

    function test_userSiteUrlError() {
        var err = ChatSites.userSiteUrlError
        compare(err("https://chat.mistral.ai/chat"), "")
        compare(err("https://nas.local/"), "", "public in 005")
        compare(err("https://nas.lan/"), "")
        compare(err("https://xn--e1afmkfd.xn--p1ai/"), "")
        compare(err("https://chat.example.org:8443/x?y=1#z"), "")
        compare(err(""), "url-empty")
        compare(err(undefined), "url-empty")
        compare(err("https://a.example/" + new Array(2031).join("x")), "")
        compare(err("https://a.example/" + new Array(2032).join("x")), "too-long")
        compare(err("https://a.example/ x"), "whitespace")
        compare(err("https://a.example/\u00a0"), "whitespace")
        compare(err("https://a.example/\u0001"), "whitespace")
        compare(err("https://a.example/\u0085"), "url-chars")
        compare(err("https://пример.рф/"), "url-chars")
        ;["\"", "\\", "<", ">", "`", "{", "}", "|", "^"].forEach(function (mark) {
            compare(err("https://a.example/" + mark), "url-chars", mark)
        })
        compare(err("https://user:pw@a.example/"), "userinfo")
        compare(err("https://a.example@evil.example/"), "userinfo")
        compare(err("a.example/chat"), "malformed")
        compare(err("http://a.example/"), "http-not-allowed")
        compare(err("HTTP://a.example/"), "http-not-allowed")
        compare(err("ftp://a.example/"), "scheme")
        compare(err("javascript:alert(1)"), "scheme")
        compare(err("https:a.example"), "malformed")
        compare(err("https://"), "malformed")
        compare(err("https://a..example/"), "malformed")
        compare(err("https://a.example%2f/"), "malformed")
        compare(err("https://[fd00::1]/"), "", "006: private IPv6")
        compare(err("https://localhost/"), "", "006: loopback")
        compare(err("https://[::1]/"), "")
        compare(err("https://intranet/"), "loopback-not-allowed")
        compare(err("https://foo.localhost/"), "loopback-not-allowed")
        compare(err("https://127.0.0.1/"), "")
        compare(err("https://127.1/"), "loopback-not-allowed")
        compare(err("https://0x7f000001/"), "loopback-not-allowed")
        compare(err("https://0.0.0.0/"), "loopback-not-allowed")
        compare(err("https://8.8.8.8/"), "ip-literal", "M2: public literals too")
        compare(err("https://10.0.0.1/"), "", "006: private")
        compare(err("https://192.168.1.1/"), "")
        compare(err("https://169.254.169.254/"), "link-local")
        compare(err("https://0300.0250.1.1/"), "ip-form")
        compare(err("https://0xa.1/"), "ip-form")
        // A numeric last label that can't be IPv4 counts as this computer.
        compare(err("https://example.0x1/"), "loopback-not-allowed")
        compare(err("https://example.1/"), "loopback-not-allowed")
    }

    // Round 2 (SEC M-2): every id in a stored text, read or not.
    function test_rawUserSiteIds() {
        var damaged = JSON.stringify([testCase.mistral, {id: "user-00c0ffee", name: "x", url: "http://10.0.0.1/",
                                                        local_kind: "private"}, testCase.mistral])
        compare(ChatSites.rawUserSiteIds(damaged), ["user-3fa9c01b", "user-00c0ffee"])
        compare(ChatSites.rawUserSiteIds("[{"), [])
        compare(ChatSites.rawUserSiteIds("user-0000beef user-0000BEEF user-0000bee"), ["user-0000beef"])
        compare(ChatSites.rawUserSiteIds(undefined), [])
        // Applied vs page: the unreadable entry the page lost counts.
        compare(ChatSites.removedUserSiteIds(damaged, JSON.stringify([testCase.mistral])), ["user-00c0ffee"])
        compare(ChatSites.removedUserSiteIds(damaged, damaged), [])
        compare(ChatSites.removedUserSiteIds(damaged, "[]"), ["user-3fa9c01b", "user-00c0ffee"])
        compare(ChatSites.removedUserSiteIds(JSON.stringify(testCase.added), JSON.stringify([testCase.pi])),
                ["user-3fa9c01b"])
        // A page name that looks like an id doesn't hide a removal.
        var spoof = JSON.stringify([{id: "user-00000001", name: "user-3fa9c01b", url: "https://a.example/"}])
        compare(ChatSites.removedUserSiteIds(JSON.stringify([testCase.mistral]), spoof), ["user-3fa9c01b"])
    }

    // Round 3 (SEC L-2b): the host an unreadable entry's url still names.
    function test_rawUserSiteHosts() {
        var text = JSON.stringify([testCase.mistral,
            {id: "user-0000beef", name: "Pi", url: "http://Pi.AI./x", local_kind: "private"},
            {id: "user-00000001", name: "x", url: 7}, {id: "user-00000002", url: "ftp://a.example/"},
            {id: "claude", url: "https://evil.example/"}, "user-00000003",
            {id: "user-0000beef", url: "https://second.example/"}])
        compare(ChatSites.rawUserSiteHosts(text), {"user-3fa9c01b": "chat.mistral.ai", "user-0000beef": "pi.ai"})
        compare(ChatSites.rawUserSiteHosts("[{"), {})
        compare(ChatSites.rawUserSiteHosts("{}"), {})
        compare(ChatSites.rawUserSiteHosts(undefined), {})
    }

    function test_userSiteHosts() {
        compare(ChatSites.userSiteHosts(testCase.added), {"user-3fa9c01b": "chat.mistral.ai", "user-0000beef": "pi.ai"})
        compare(ChatSites.userSiteHosts([{id: "user-00000001", name: "A", url: "https://A.Example./x"}]),
                {"user-00000001": "a.example"})
        compare(ChatSites.userSiteHosts(undefined), {})
    }

    function test_addressClass() {
        compare(ChatSites.addressClass("https://chat.mistral.ai/"), "public")
        compare(ChatSites.addressClass("https://nas.local/"), "public")
        compare(ChatSites.addressClass("http://chat.mistral.ai/"), "")
        compare(ChatSites.addressClass("https://localhost/"), "loopback")
        compare(ChatSites.addressClass("https://10.0.0.1/"), "private")
        compare(ChatSites.addressClass("https://10.0.0.1./"), "")
        compare(ChatSites.addressClass(""), "")
    }

    function test_validateUserSite() {
        var ok = {ok: true, error: ""}
        compare(ChatSites.validateUserSite(testCase.mistral, []), ok)
        compare(ChatSites.validateUserSite(testCase.mistral), ok)
        compare(ChatSites.validateUserSite(Object.assign({local: true}, testCase.mistral)).error, "entry")
        compare(ChatSites.validateUserSite(Object.assign({auth_hosts: []}, testCase.mistral)).error, "entry")
        compare(ChatSites.validateUserSite({id: testCase.mistral.id, name: "A"}).error, "entry")
        compare(ChatSites.validateUserSite(null).error, "entry")
        compare(ChatSites.validateUserSite([]).error, "entry")
        compare(ChatSites.validateUserSite({id: "claude", name: "A", url: "https://a.example/"}).error, "id")
        compare(ChatSites.validateUserSite(testCase.mistral, [testCase.mistral]).error, "id-taken")
        compare(ChatSites.validateUserSite({id: "user-00000001", name: "Le chat", url: "https://a.example/"},
                                           [testCase.mistral]).error, "name-taken")
        compare(ChatSites.validateUserSite({id: "user-00000001", name: "A", url: "http://a.example/"}).error,
                "http-not-allowed")
    }

    function test_parseUserSites() {
        var text = JSON.stringify(testCase.added)
        compare(ChatSites.parseUserSites(text), {ok: true, sites: testCase.added})
        compare(ChatSites.parseUserSites("[]"), {ok: true, sites: []})
        // Not ok, nothing shown.
        compare(ChatSites.parseUserSites(""), {ok: false, sites: []})
        compare(ChatSites.parseUserSites("{"), {ok: false, sites: []})
        compare(ChatSites.parseUserSites("{}"), {ok: false, sites: []})
        compare(ChatSites.parseUserSites(undefined), {ok: false, sites: []})
        compare(ChatSites.parseUserSites(" " + text + new Array(ChatSites.MAX_USER_SITES_CHARS).join(" ")),
                {ok: false, sites: []})
        // Not ok, the good entries still shown in order.
        var bad = JSON.stringify([testCase.mistral, {id: "user-00000001", name: "<b>", url: "https://a.example/"},
                                  testCase.pi])
        compare(ChatSites.parseUserSites(bad), {ok: false, sites: testCase.added})
        var duplicate = JSON.stringify([testCase.mistral, testCase.pi, testCase.mistral])
        compare(ChatSites.parseUserSites(duplicate), {ok: false, sites: testCase.added})
        var extra = JSON.stringify([Object.assign({local: true}, testCase.mistral), testCase.pi])
        compare(ChatSites.parseUserSites(extra), {ok: false, sites: [testCase.pi]})
        // Never more than MAX_USER_SITES.
        var many = []
        for (var index = 0; index < 201; index++)
            many.push({id: "user-" + ("0000000" + index.toString(16)).slice(-8), name: "S" + index,
                       url: "https://s" + index + ".example.org/"})
        var read = ChatSites.parseUserSites(JSON.stringify(many))
        compare(read.ok, false)
        compare(read.sites.length, 200)
        compare(ChatSites.parseUserSites(JSON.stringify(many.slice(0, 200))).ok, true)
        // Only the three keys are kept.
        compare(Object.keys(ChatSites.parseUserSites(text).sites[0]), ["id", "name", "url"])
    }

    function test_serializeUserSites() {
        var text = ChatSites.serializeUserSites([{url: testCase.mistral.url, name: testCase.mistral.name,
                                                  id: testCase.mistral.id}])
        compare(text, "[{\"id\":\"user-3fa9c01b\",\"name\":\"Le Chat\",\"url\":\"https://chat.mistral.ai/chat\"}]")
        compare(ChatSites.serializeUserSites([]), "[]")
        compare(ChatSites.serializeUserSites([{id: "user-00000001", name: "Ça va", url: "https://a.example/"}]),
                "[{\"id\":\"user-00000001\",\"name\":\"Ça va\",\"url\":\"https://a.example/\"}]")
        // Refusals.
        compare(ChatSites.serializeUserSites([testCase.mistral, testCase.mistral]), "")
        compare(ChatSites.serializeUserSites([Object.assign({local: false}, testCase.mistral)]), "")
        compare(ChatSites.serializeUserSites([{id: "user-00000001", name: "", url: "https://a.example/"}]), "")
        compare(ChatSites.serializeUserSites("nope"), "")
        var many = []
        for (var index = 0; index < 201; index++)
            many.push({id: "user-" + ("0000000" + index.toString(16)).slice(-8), name: "S" + index,
                       url: "https://s" + index + ".example.org/"})
        compare(ChatSites.serializeUserSites(many), "")
        verify(ChatSites.serializeUserSites(many.slice(0, 200)) !== "")
        // 200 entries at their longest still fit the char cap.
        var long = []
        for (var at = 0; at < 200; at++)
            long.push({id: "user-" + ("0000000" + at.toString(16)).slice(-8),
                       name: "N" + at + new Array(38 - String(at).length + 1).join("é"),
                       url: "https://s" + at + ".example.org/" + new Array(2048 - 22 - String(at).length).join("x")})
        verify(long.every(function (entry) { return ChatSites.validateUserSite(entry).ok }))
        var longest = ChatSites.serializeUserSites(long)
        verify(longest !== "")
        verify(longest.length <= ChatSites.MAX_USER_SITES_CHARS, longest.length)
        compare(ChatSites.parseUserSites(longest).ok, true)
    }

    function test_effectiveSiteForAnAddedSite() {
        var site = ChatSites.effectiveSite("user-3fa9c01b", {}, testCase.added)
        compare(site, {
            id: "user-3fa9c01b", name: "Le Chat", url: "https://chat.mistral.ai/chat", icon: "", user: true,
            site_hosts: [], auth_hosts: [], exact_hosts: ["chat.mistral.ai"], local: false,
            local_kind: "public", origin: "https://chat.mistral.ai:443", default_on: true, http_origin: ""
        })
        // Nothing from extra keys, even if a caller passed them.
        compare(ChatSites.effectiveSite("user-3fa9c01b", {}, [Object.assign({local: true, auth_hosts: ["evil.example"]},
                                                                           testCase.mistral)]), null)
        // Custom addresses never apply to added sites.
        compare(ChatSites.effectiveSite("user-3fa9c01b", {"user-3fa9c01b": "https://evil.example/"},
                                        testCase.added).url, testCase.mistral.url)
        // Unknown without userSites, or with an invalid entry.
        compare(ChatSites.effectiveSite("user-3fa9c01b"), null)
        compare(ChatSites.effectiveSite("user-3fa9c01b", {}, []), null)
        compare(ChatSites.effectiveSite("user-3fa9c01b", {}, "nope"), null)
        compare(ChatSites.effectiveSite("user-3fa9c01b", {}, [{id: "user-3fa9c01b", name: "A", url: "http://a.example/"}]),
                null)
        compare(ChatSites.byId("user-3fa9c01b", testCase.added).name, "Le Chat")
        compare(ChatSites.byId("user-3fa9c01b"), null)
        compare(ChatSites.homeUrl("user-0000beef", {}, testCase.added), "https://pi.ai/talk")
        compare(ChatSites.homeUrl("user-0000beef"), "")
        compare(ChatSites.siteIds(testCase.added),
                ChatSites.siteIds().concat(["user-3fa9c01b", "user-0000beef"]))
        // A second entry with the same id or name never resolves.
        compare(ChatSites.siteIds([testCase.mistral, {id: "user-00000001", name: "le chat", url: "https://a.example/"}]),
                ChatSites.siteIds().concat(["user-3fa9c01b"]))
        // The built-ins are never touched.
        compare(ChatSites.effectiveSite("claude", {}, testCase.added).site_hosts, ChatSites.byId("claude").site_hosts)
    }

    // Main frame: https anywhere public (redirects and SSO); a click off its
    // own host goes to the browser; nothing on this computer or the home
    // network, in any IPv4 form.
    function test_addedSiteNavigation() {
        compare(userNav("https://chat.mistral.ai/chat"), "allow")
        compare(userNav("https://chat.mistral.ai/c/1", true), "allow")
        compare(userNav("https://auth.mistral.ai/login"), "allow", "a redirect")
        compare(userNav("https://accounts.google.com/o/oauth2"), "allow")
        compare(userNav("https://auth.mistral.ai/login", true), "external")
        compare(userNav("https://mistral.ai/", true), "external", "exact host only")
        compare(userNav("about:blank"), "allow")
        compare(userNav("http://chat.mistral.ai/"), "block")
        compare(userNav("data:text/html,x"), "block")
        compare(userNav("javascript:alert(1)"), "block")
        compare(userNav("file:///etc/passwd"), "block")
        compare(userNav("https://8.8.8.8/"), "allow", "a public literal by redirect")
        var blocked = ["https://localhost/", "https://127.0.0.1/", "https://127.1/", "https://0x7f000001/",
                       "https://017700000001/", "https://2130706433/", "https://[::1]/", "https://[fd00::1]/",
                       "https://[fe80::1]/", "https://10.0.0.1/", "https://172.16.0.1/", "https://172.31.255.255/",
                       "https://192.168.1.1/", "https://169.254.169.254/", "https://0.0.0.0/", "https://0.1.2.3/",
                       "https://10.1/", "https://192.168.257/", "https://0300.0250.1.1/", "https://0xa.1/", "https://0xc0a80101/",
                       "https://3232235777/", "https://foo.localhost/", "https://intranet/",
                       "https://256.256.256.256/", "http://localhost:3000/", "https://user@chat.mistral.ai/"]
        blocked.forEach(function (url) {
            compare(userNav(url), "block", "main frame " + url)
            compare(userNav(url, false, false), "block", "subframe " + url)
            compare(userPopup(url, true), "block", "dialog " + url)
            compare(userPopup(url, false), "block", "window " + url)
        })
        compare(userNav("https://1.2.3/"), "allow", "1.2.0.3")
        compare(userNav("https://172.15.0.1/"), "allow")
        compare(userNav("https://172.32.0.1/"), "allow")
        compare(userNav("https://192.169.0.1/"), "allow")
    }

    function test_addedSiteSubframes() {
        compare(userNav("https://ads.example.com/", true, false), "allow")
        compare(userNav("http://cdn.example.com/", true, false), "allow")
        compare(userNav("about:blank", false, false), "allow")
        compare(userNav("blob:https://chat.mistral.ai/1", false, false), "allow")
        compare(userNav("data:text/html,x", false, false), "allow")
        compare(userNav("https://nas.local/", false, false), "allow")
        // Built-ins keep their looser subframe rule (golden table).
        compare(nav("https://10.0.0.1/", "claude", false, false), "allow")
    }

    function test_addedSiteNewWindow() {
        // No sign-in hosts: a clicked dialog is the overlay, anything else
        // https goes to the browser, a script-opened one is blocked.
        compare(userPopup("https://auth.mistral.ai/", true, true), "overlay")
        compare(userPopup("about:blank", true, true), "overlay")
        compare(userPopup("https://auth.mistral.ai/", true, false), "block")
        compare(userPopup("https://accounts.google.com/", false, true), "external")
        compare(userPopup("https://chat.mistral.ai/x", false, true), "external")
        compare(userPopup("http://chat.mistral.ai/x", false, true), "block")
    }

    // Without its entry an added id is blocked everywhere.
    function test_addedIdWithoutUserSitesIsBlocked() {
        ;[undefined, [], [testCase.pi], "x"].forEach(function (userSites, at) {
            compare(userNav("https://chat.mistral.ai/chat", false, true, userSites), "block", "main " + at)
            compare(userNav("https://chat.mistral.ai/chat", false, false, userSites), "block", "subframe " + at)
            compare(userNav("about:blank", false, false, userSites), "block", "subframe blank " + at)
            compare(userPopup("https://chat.mistral.ai/", true, true, userSites), "block", "popup " + at)
            compare(ChatSites.offSiteHost({siteId: "user-3fa9c01b", url: "https://chat.mistral.ai/",
                                           userSites: userSites}), {off: false, host: ""})
            compare(ChatSites.isPageUrl(ChatSites.effectiveSite("user-3fa9c01b", {}, userSites),
                                        "https://chat.mistral.ai/"), false)
        })
    }

    function test_addedSiteOffSiteAndLocalOwner() {
        var off = function (url) {
            return ChatSites.offSiteHost({siteId: "user-3fa9c01b", url: url, userSites: testCase.added})
        }
        compare(off("https://chat.mistral.ai/c/1"), {off: false, host: ""})
        compare(off("https://Chat.Mistral.AI./x"), {off: false, host: ""})
        compare(off("https://auth.mistral.ai/"), {off: true, host: "auth.mistral.ai"})
        compare(off("https://mistral.ai/"), {off: true, host: "mistral.ai"})
        var site = ChatSites.effectiveSite("user-3fa9c01b", {}, testCase.added)
        verify(ChatSites.isPageUrl(site, "https://chat.mistral.ai/c/1"))
        verify(!ChatSites.isPageUrl(site, "https://localhost/"))
        verify(!ChatSites.isPageUrl(site, "http://chat.mistral.ai/"))
        // Never local in 005.
        compare(ChatSites.localOwnerPort({siteId: "user-3fa9c01b", url: "https://localhost:3000/",
                                         userSites: testCase.added}), 0)
        compare(ChatSites.localOwnerGate({siteId: "user-3fa9c01b", url: "https://localhost:3000/",
                                         userSites: testCase.added}), "skip")
    }

    function test_orderedSites() {
        var order = function (userSites, text) {
            return ChatSites.orderedSites(userSites, text).map(function (site) { return site.id })
        }
        var defaults = ChatSites.siteIds().concat(["user-3fa9c01b", "user-0000beef", "ollama"])
        compare(order(testCase.added, ""), defaults)
        compare(order(testCase.added, undefined), defaults)
        compare(order([], ""), ChatSites.siteIds().concat(["ollama"]))
        compare(order(undefined, ""), ChatSites.siteIds().concat(["ollama"]))
        // A stored order; unknown ids dropped, missing ones appended in
        // default order, a missing Ollama last.
        compare(order(testCase.added, "[\"user-0000beef\",\"ollama\",\"grok\",\"devin\",\"user-00000009\"]"),
                ["user-0000beef", "ollama", "grok", "claude", "chatgpt", "gemini", "copilot", "mscopilot", "local",
                 "user-3fa9c01b"])
        compare(order(testCase.added, "[\"grok\"]"),
                ["grok", "claude", "chatgpt", "gemini", "copilot", "mscopilot", "local", "user-3fa9c01b",
                 "user-0000beef", "ollama"])
        // Damaged: the default order.
        compare(order(testCase.added, "[\"grok\",\"grok\"]"), defaults)
        compare(order(testCase.added, "[\"grok\",7]"), defaults)
        compare(order(testCase.added, "{"), defaults)
        compare(order(testCase.added, "{}"), defaults)
        // Site objects: built-ins from the catalog, added ones built, Ollama's entry.
        var sites = ChatSites.orderedSites(testCase.added, "")
        compare(sites[0], ChatSites.byId("claude"))
        compare(sites[7].user, true)
        compare(sites[7].icon, "")
        compare(sites[9], OllamaChat.ENTRY)
    }

    function test_serializeSiteOrder() {
        var defaults = ChatSites.siteIds(testCase.added).concat(["ollama"])
        compare(ChatSites.serializeSiteOrder(defaults, testCase.added), "")
        compare(ChatSites.serializeSiteOrder([], testCase.added), "")
        var moved = ChatSites.moveInOrder(defaults, "ollama", -1)
        compare(ChatSites.serializeSiteOrder(moved, testCase.added), JSON.stringify(moved))
        // Round trip.
        compare(ChatSites.orderedSites(testCase.added, ChatSites.serializeSiteOrder(moved, testCase.added))
                .map(function (site) { return site.id }), moved)
        // Unknown ids are not written; the rest is completed.
        compare(ChatSites.serializeSiteOrder(["user-00000009", "grok"], []),
                JSON.stringify(["grok", "claude", "chatgpt", "gemini", "copilot", "mscopilot", "local", "ollama"]))
        compare(ChatSites.serializeSiteOrder(["ollama"].concat(ChatSites.siteIds()), []),
                JSON.stringify(["ollama"].concat(ChatSites.siteIds())))
    }

    function test_moveInOrder() {
        compare(ChatSites.moveInOrder(["a", "b", "c"], "b", -1), ["b", "a", "c"])
        compare(ChatSites.moveInOrder(["a", "b", "c"], "b", 1), ["a", "c", "b"])
        compare(ChatSites.moveInOrder(["a", "b", "c"], "a", -1), ["a", "b", "c"])
        compare(ChatSites.moveInOrder(["a", "b", "c"], "c", 1), ["a", "b", "c"])
        compare(ChatSites.moveInOrder(["a", "b", "c"], "x", 1), ["a", "b", "c"])
        compare(ChatSites.moveInOrder(["a", "b", "c"], "a", 0.5), ["a", "b", "c"])
        compare(ChatSites.moveInOrder(null, "a", 1), [])
        var list = ["a", "b"]
        ChatSites.moveInOrder(list, "a", 1)
        compare(list, ["a", "b"], "a copy")
    }

    function test_enabledSitesFollowTheOrder() {
        var json = JSON.stringify(["claude", "grok", "user-0000beef", "user-3fa9c01b", "ollama"])
        compare(ids(ChatSites.enabledSites(json, testCase.added, "")),
                ["claude", "grok", "user-3fa9c01b", "user-0000beef"])
        compare(ids(ChatSites.enabledSites(json, testCase.added, "[\"user-0000beef\",\"grok\"]")),
                ["user-0000beef", "grok", "claude", "user-3fa9c01b"])
        // Without userSites an added id is never enabled.
        compare(ids(ChatSites.enabledSites(json)), ["claude", "grok"])
        // Unreadable chatSites: the default-on built-ins only.
        compare(ids(ChatSites.enabledSites("x", testCase.added, "")), ChatSites.defaultSiteIds())
    }

    function test_badgeLetter() {
        compare(ChatSites.badgeLetter("le Chat"), "L")
        compare(ChatSites.badgeLetter("  pi "), "P")
        compare(ChatSites.badgeLetter("éclair"), "É")
        compare(ChatSites.badgeLetter("e\u0301clair"), "E", "combining mark: the first code point")
        compare(ChatSites.badgeLetter("\ud83d\ude00 Smile"), "\ud83d\ude00")
        compare(ChatSites.badgeLetter("\ud83d"), "\ud83d".toUpperCase())
        compare(ChatSites.badgeLetter("日本"), "日")
        compare(ChatSites.badgeLetter(""), "?")
        compare(ChatSites.badgeLetter("   "), "?")
        compare(ChatSites.badgeLetter(undefined), "?")
    }

    function test_userSitesPerformance() {
        var many = []
        for (var index = 0; index < 200; index++)
            many.push({id: "user-" + ("0000000" + index.toString(16)).slice(-8), name: "Site " + index,
                       url: "https://s" + index + ".example.org/"})
        var start = Date.now()
        for (var run = 0; run < 20; run++)
            ChatSites.classifyNavigation({siteId: "user-000000c7", url: "https://s199.example.org/", userSites: many})
        verify(Date.now() - start < 2000, "a navigation with 200 added sites stays quick")
    }

    function test_catalogOrderAndFields() {
        compare(ChatSites.siteIds(),
                ["claude", "chatgpt", "grok", "gemini", "copilot", "mscopilot", "local"])
        for (var index = 0; index < ChatSites.sites.length; index++) {
            var site = ChatSites.sites[index]
            verify(site.name.length > 0)
            if (site.id === "local")
                verify(site.url.indexOf("http://localhost") === 0)
            else
                verify(site.url.indexOf("https://") === 0, site.id)
            verify(/^provider-[a-z]+\.svg$/.test(site.icon))
            verify(site.site_hosts.length > 0)
            // Only Local has no sign-in providers.
            compare(site.auth_hosts.length === 0, site.id === "local", site.id)
            compare(site.local === true, site.id === "local", site.id)
            // Every home page must be allowed by its own navigation policy.
            compare(nav(site.url, site.id, false), "allow")
            compare(nav(site.url, site.id, true), "allow")
        }
    }

    function test_byId() {
        compare(ChatSites.byId("grok").name, "Grok")
        compare(ChatSites.byId("mscopilot").url, "https://copilot.microsoft.com/")
        compare(ChatSites.byId("devin"), null)
        compare(ChatSites.byId(""), null)
        compare(ChatSites.byId(undefined), null)
    }

    function test_defaultSiteIds() {
        compare(ChatSites.defaultSiteIds(),
                ["claude", "chatgpt", "grok", "gemini", "copilot", "mscopilot"])
        compare(ChatSites.byId("local").default_on, false)
    }

    // The web UI entry is named so it isn't mistaken for the built-in
    // Ollama chat (OllamaChat.js); its id stays "local".
    function test_localSiteLabel() {
        compare(ChatSites.byId("local").name, "Local web UI (Open WebUI)")
        compare(ChatSites.siteIds().indexOf("ollama"), -1)
    }

    function test_enabledSites() {
        var defaults = ChatSites.defaultSiteIds()
        compare(ids(ChatSites.enabledSites(
            "[\"claude\",\"chatgpt\",\"grok\",\"gemini\",\"copilot\",\"mscopilot\"]")),
            defaults)
        compare(ids(ChatSites.enabledSites(JSON.stringify(ChatSites.siteIds()))),
                ChatSites.siteIds())
        // Catalog order wins over config order; unknown ids are dropped.
        compare(ids(ChatSites.enabledSites("[\"mscopilot\",\"cursor\",\"claude\",42]")),
                ["claude", "mscopilot"])
        compare(ids(ChatSites.enabledSites("[\"local\"]")), ["local"])
        compare(ids(ChatSites.enabledSites("[]")), [])
        // Unreadable config falls back to the default-on sites, never Local.
        compare(ids(ChatSites.enabledSites("not json")), defaults)
        compare(ids(ChatSites.enabledSites("{\"claude\":true}")), defaults)
        compare(ids(ChatSites.enabledSites("")), defaults)
        compare(ids(ChatSites.enabledSites(undefined)), defaults)
        compare(ids(ChatSites.enabledSites(null)), defaults)
    }

    function test_copilotSignInUrl() {
        var copilot = ChatSites.byId("copilot")
        compare(copilot.url, "https://github.com/login?return_to=%2Fcopilot")
        compare(copilot.auth_hosts, ["github.com", "accounts.google.com", "appleid.apple.com"])
        compare(nav(copilot.url, "copilot", false), "allow")
        compare(nav("https://github.com/copilot", "copilot", true), "allow")
        compare(popup("https://accounts.google.com/o/oauth2", "copilot"), "overlay")
        compare(popup("https://appleid.apple.com/auth", "copilot"), "overlay")
    }

    function test_initialSite() {
        compare(ChatSites.initialSite(["claude", "grok"], "grok"), "grok")
        compare(ChatSites.initialSite(["chatgpt", "grok"], "claude"), "chatgpt")
        compare(ChatSites.initialSite(["chatgpt"], ""), "chatgpt")
        compare(ChatSites.initialSite([], "claude"), "")
        compare(ChatSites.initialSite(null, "claude"), "")
    }

    function test_hostMatches() {
        var list = ["claude.ai", "anthropic.com"]
        verify(ChatSites.hostMatches("claude.ai", list))
        verify(ChatSites.hostMatches("www.claude.ai", list))
        verify(ChatSites.hostMatches("a.b.anthropic.com", list))
        verify(ChatSites.hostMatches("CLAUDE.AI", list))
        verify(ChatSites.hostMatches("claude.ai.", list))
        verify(ChatSites.hostMatches("claude.ai", ["Claude.AI"]))
        verify(!ChatSites.hostMatches("evilclaude.ai", list))
        verify(!ChatSites.hostMatches("claude.ai.evil.com", list))
        verify(!ChatSites.hostMatches("ai", list))
        verify(!ChatSites.hostMatches("", list))
        verify(!ChatSites.hostMatches("claude.ai", []))
        verify(!ChatSites.hostMatches("claude.ai", null))
        verify(!ChatSites.hostMatches(null, list))
    }

    function test_navigationAllowsSiteAndSso() {
        compare(nav("https://claude.ai/chat/1"), "allow")
        compare(nav("https://CLAUDE.AI/new"), "allow")
        compare(nav("about:blank"), "allow")
        // Redirects and form posts to other https hosts are allowed.
        compare(nav("https://accounts.google.com/o/oauth2", "claude", false), "allow")
        compare(nav("https://sso.example.com/login", "claude", false), "allow")
        compare(nav("https://accounts.google.com/signin", "claude", true), "allow")
        compare(nav("https://login.live.com/", "chatgpt", true), "allow")
    }

    function test_navigationLinkClicksLeaveForBrowser() {
        compare(nav("https://example.com/docs", "claude", true), "external")
        compare(nav("https://evilclaude.ai/", "claude", true), "external")
        compare(nav("https://claude.ai.evil.com/", "claude", true), "external")
        compare(nav("https://chatgpt.com/", "claude", true), "external")
        compare(nav("https://claude.ai/", "chatgpt", true), "external")
    }

    function test_navigationBlocksSchemes() {
        var blocked = [
            "file:///etc/passwd",
            "data:text/html,<b>x</b>",
            "javascript:alert(1)",
            "view-source:https://claude.ai/",
            "chrome://settings",
            "qrc:/main.qml",
            "http://claude.ai/",
            "ftp://claude.ai/",
            "about:config",
            "blob:https://claude.ai/123"
        ]
        for (var index = 0; index < blocked.length; index++) {
            compare(nav(blocked[index], "claude", false), "block", blocked[index])
            compare(nav(blocked[index], "claude", true), "block", blocked[index])
        }
    }

    function test_navigationMalformed() {
        var malformed = [
            "",
            "claude.ai",
            "https:claude.ai",
            "https://",
            "https://user@claude.ai/",
            "https://evil.com\\@claude.ai/",
            "https://cl aude.ai/",
            "https://%63laude.ai/",
            "https://.claude.ai/",
            "https://claude..ai/",
            "https://claude.ai:99999999/",
            "https://claude.ai:0/",
            "https://claude.ai:65536/",
            "https://[::2]/",
            "https://[::1/"
        ]
        for (var index = 0; index < malformed.length; index++)
            compare(nav(malformed[index], "claude", true), "block", malformed[index])
        compare(nav(null), "block")
        compare(nav(undefined), "block")
        compare(ChatSites.classifyNavigation(null), "block")
        compare(ChatSites.classifyNavigation({url: "https://claude.ai/", siteId: "claude"}), "allow")
        compare(ChatSites.classifyNavigation({url: "file:///etc/passwd", siteId: "claude"}), "block")
        compare(ChatSites.classifyNavigation({url: "file:///etc/passwd", siteId: "claude",
            isMainFrame: undefined}), "block")
        compare(ChatSites.classifyNavigation({url: "file:///etc/passwd", siteId: "claude",
            isMainFrame: 0}), "block")
    }

    function test_navigationSubframesAndUnknownSite() {
        compare(nav("file:///etc/passwd", "claude", false, false), "allow")
        compare(nav("https://ads.example.com/", "claude", true, false), "allow")
        compare(nav("about:blank", "claude", false, false), "allow")
        compare(nav("about:srcdoc", "claude", false, false), "allow")
        compare(nav("", "claude", false, false), "allow")
        compare(nav("blob:https://claude.ai/0b1c", "claude", false, false), "allow")
        compare(nav("data:text/html,x", "claude", false, false), "allow")
        compare(nav("https://claude.ai/", "devin", false), "block")
        compare(nav("https://claude.ai/", "", false), "block")
    }

    function test_newWindow() {
        compare(popup("https://accounts.google.com/o/oauth2/auth", "claude"), "overlay")
        compare(popup("https://ACCOUNTS.google.com/", "claude"), "overlay")
        compare(popup("https://login.microsoftonline.com/x", "chatgpt"), "overlay")
        compare(popup("https://appleid.apple.com/auth", "mscopilot"), "overlay")
        compare(popup("https://example.com/", "claude", true), "overlay")
        compare(popup("about:blank", "claude", true), "overlay")
        compare(popup("", "claude", true), "overlay")
        compare(popup("https://example.com/paper", "claude"), "external")
        compare(popup("https://claude.ai/other", "claude"), "external")
        compare(popup("https://evilaccounts.google.com/", "claude"), "external")
        compare(popup("http://example.com/", "claude"), "block")
        compare(popup("http://example.com/", "claude", true), "block")
        compare(popup("javascript:alert(1)", "claude", true), "block")
        compare(popup("file:///etc/passwd", "claude", true), "block")
        compare(popup("view-source:https://claude.ai/", "claude"), "block")
        compare(popup("about:blank", "claude"), "block")
        compare(popup("https://user@accounts.google.com/", "claude", true), "block")
        compare(popup("https://accounts.google.com/", "devin", true), "block")
        compare(ChatSites.classifyNewWindow(null), "block")
    }

    // L1: a sign-in window opens only for a click; a script-opened one is
    // dropped, and "external" still needs the click in ChatWebView.
    function test_newWindowOverlayNeedsAClick() {
        var none = undefined
        compare(popup("https://accounts.google.com/o/oauth2/auth", "claude", false, none, false), "block")
        compare(popup("https://example.com/", "claude", true, none, false), "block")
        compare(popup("about:blank", "claude", true, none, false), "block")
        compare(popup("", "claude", true, none, false), "block")
        compare(popup("https://example.com/paper", "claude", false, none, false), "external")
        compare(ChatSites.classifyNewWindow({url: "https://accounts.google.com/", siteId: "claude"}), "block")
        compare(ChatSites.classifyNewWindow({url: "https://accounts.google.com/", siteId: "claude",
            userInitiated: "true"}), "block")
        compare(ChatSites.classifyNewWindow({url: "https://accounts.google.com/", siteId: "claude",
            userInitiated: 1}), "block")
        compare(ChatSites.classifyNewWindow({url: "https://accounts.google.com/", siteId: "claude",
            userInitiated: true}), "overlay")
        compare(ChatSites.classifyNewWindow({url: "", isDialog: true, siteId: "claude",
            userInitiated: true}), "overlay")
    }

    function test_parseUrl() {
        compare(ChatSites.parseUrl("https://claude.ai/new"),
                {scheme: "https", host: "claude.ai", port: ""})
        compare(ChatSites.parseUrl("HTTP://LocalHost:3000/c/1"),
                {scheme: "http", host: "localhost", port: "3000"})
        compare(ChatSites.parseUrl("https://[::1]/"), {scheme: "https", host: "[::1]", port: ""})
        compare(ChatSites.parseUrl("http://[::1]:8080/x"),
                {scheme: "http", host: "[::1]", port: "8080"})
        compare(ChatSites.parseUrl("https://claude.ai:1/").port, "1")
        compare(ChatSites.parseUrl("https://claude.ai:65535/").port, "65535")
        compare(ChatSites.parseUrl("https://claude.ai:0443/").port, "443")
        compare(ChatSites.parseUrl("javascript:alert(1)"), {scheme: "javascript", host: "", port: ""})
        var invalid = [
            "https://[::2]/",
            "https://[fe80::1]/",
            "https://[::1/",
            "https://[::1]x/",
            "https://[::1]:/",
            "https://claude.ai:0/",
            "https://claude.ai:00000/",
            "https://claude.ai:65536/",
            "https://claude.ai:/",
            "https://user@claude.ai/",
            "https://a\\b.ai/",
            "https://cl%61ude.ai/",
            "https://cl aude.ai/",
            ""
        ]
        for (var index = 0; index < invalid.length; index++)
            compare(ChatSites.parseUrl(invalid[index]), null, invalid[index])
    }

    function test_isLoopbackHost() {
        verify(ChatSites.isLoopbackHost("localhost"))
        verify(ChatSites.isLoopbackHost("LOCALHOST"))
        verify(ChatSites.isLoopbackHost("localhost."))
        verify(ChatSites.isLoopbackHost("127.0.0.1"))
        verify(ChatSites.isLoopbackHost("[::1]"))
        verify(!ChatSites.isLoopbackHost("127.0.0.2"))
        verify(!ChatSites.isLoopbackHost("foo.localhost"))
        verify(!ChatSites.isLoopbackHost("localhost.example.com"))
        verify(!ChatSites.isLoopbackHost("::1"))
        verify(!ChatSites.isLoopbackHost(""))
        verify(!ChatSites.isLoopbackHost(null))
        verify(!ChatSites.isLoopbackHost(undefined))
    }

    // L5: frames, pages and windows never reach these names of this computer.
    function test_newLocalNamesAreBlocked() {
        var names = ["localhost.localdomain", "app.localhost.localdomain", "ip6-localhost",
                     "ip6-loopback", "prime"]
        for (var index = 0; index < names.length; index++) {
            var url = "https://" + names[index] + ":3998/x"
            compare(nav(url, "claude", false, true), "block", url)
            compare(nav(url, "claude", true, true), "block", url)
            compare(nav(url, "claude", false, false), "block", url)
            compare(popup(url, "claude", true), "block", url)
            compare(popup(url, "claude", false), "block", url)
        }
    }

    function test_isLocalAddress() {
        var local = ["localhost", "127.0.0.1", "[::1]", "127.0.0.2", "127.1", "0.0.0.0", "0",
                     "2130706433", "0x7f000001", "0x7f.1", "017700000001", "foo.localhost",
                     "1.2.3.4.5", "08.1.1.1", "999.1.1.1",
                     // L5: /etc/hosts names of this computer and every name
                     // without a dot (the machine's own name, LAN names).
                     "localhost.localdomain", "LOCALHOST.LOCALDOMAIN.", "app.localhost.localdomain",
                     "ip6-localhost", "ip6-loopback", "prime", "myhost", "router", "a-b_c"]
        for (var index = 0; index < local.length; index++)
            verify(ChatSites.isLocalAddress(local[index]), local[index])
        var remote = ["claude.ai", "192.168.1.5", "10.0.0.1", "8.8.8.8", "localhost.example.com",
                      "127.example.com", "localhost.localdomain.example.com", "ip6-localhost.example.com",
                      "mylocalhost.localdomain.example", "", null]
        for (var other = 0; other < remote.length; other++)
            verify(!ChatSites.isLocalAddress(remote[other]), String(remote[other]))
    }

    function test_validateCustomUrl() {
        var cases = [
            ["local", "http://localhost:3000", true, ""],
            ["local", "http://127.0.0.1:8080/", true, ""],
            ["local", "http://[::1]:3000/", true, ""],
            ["local", "https://ai.home.example/", true, ""],
            ["local", "https://localhost/", true, ""],
            ["local", "http://192.168.1.5:3000", false, "http-not-loopback"],
            ["local", "http://ai.home.example/", false, "http-not-loopback"],
            ["claude", "https://chat.example.org/x", true, ""],
            ["claude", "http://localhost:3000", false, "scheme"],
            ["claude", "http://chat.example.org/", false, "scheme"],
            ["claude", "https://localhost/", false, "loopback-not-allowed"],
            ["claude", "https://127.0.0.1:8443/", false, "loopback-not-allowed"],
            ["claude", "https://[::1]/", false, "loopback-not-allowed"],
            ["chatgpt", "https://2130706433/", false, "loopback-not-allowed"],
            ["claude", "https://localhost.localdomain/", false, "loopback-not-allowed"],
            ["claude", "https://ip6-localhost/", false, "loopback-not-allowed"],
            ["claude", "https://myhost:8443/", false, "loopback-not-allowed"],
            ["local", "https://myhost:8443/", true, ""],
            ["claude", "https://user:pw@claude.ai/", false, "userinfo"],
            ["claude", "javascript:https://user@x/", false, "scheme"],
            ["local", "http://user@localhost:3000/", false, "userinfo"],
            ["claude", "javascript:alert(1)", false, "scheme"],
            ["claude", "data:text/html,x", false, "scheme"],
            ["claude", "file:///etc/passwd", false, "scheme"],
            ["local", "file:///etc/passwd", false, "scheme"],
            ["claude", "https://chat example.org/", false, "whitespace"],
            ["claude", "https://chat.example.org/a\tb", false, "whitespace"],
            ["claude", "https://chat.example.org/\n", false, "whitespace"],
            ["claude", "https://claude.ai/\u0001", false, "whitespace"],
            ["claude", "https://claude.ai/\u0000x", false, "whitespace"],
            ["claude", "https://claude.ai/\u001f", false, "whitespace"],
            ["claude", "https://claude.ai/\u007f", false, "whitespace"],
            ["local", "http://local\u0001host:3000/", false, "whitespace"],
            ["claude", "chat.example.org", false, "malformed"],
            ["claude", "https://", false, "malformed"],
            ["claude", "https://chat..example.org/", false, "malformed"],
            ["claude", "https://[fe80::1]/", false, "malformed"],
            ["claude", "https://chat.example.org:70000/", false, "malformed"],
            ["devin", "https://chat.example.org/", false, "unknown-site"],
            ["", "https://chat.example.org/", false, "unknown-site"]
        ]
        for (var index = 0; index < cases.length; index++) {
            var row = cases[index]
            var result = checkUrl(row[0], row[1])
            compare(result.ok, row[2], row[0] + " " + row[1])
            compare(result.error, row[3], row[0] + " " + row[1])
            compare(result.url, row[2] ? row[1] : "", row[0] + " " + row[1])
        }
        compare(checkUrl("claude", ""), {ok: true, url: "", error: ""})
        compare(checkUrl("claude", undefined), {ok: true, url: "", error: ""})
        var longUrl = "https://chat.example.org/"
        while (longUrl.length < 2049)
            longUrl += "a"
        compare(longUrl.length, 2049)
        compare(checkUrl("claude", longUrl).error, "too-long")
        verify(checkUrl("claude", longUrl.slice(0, 2048)).ok)
    }

    function test_subframesNeverReachThisComputer() {
        var blocked = [
            "http://localhost:3000",
            "http://localhost:3000/",
            "https://localhost/",
            "https://127.0.0.1/",
            "https://[::1]/",
            "https://2130706433/",
            "https://foo.localhost/",
            "https://0.0.0.0/",
            "http://user@localhost/"
        ]
        for (var index = 0; index < blocked.length; index++) {
            compare(nav(blocked[index], "claude", false, false), "block", blocked[index])
            compare(nav(blocked[index], "mscopilot", true, false), "block", blocked[index])
            compare(nav(blocked[index], "devin", false, false), "block", blocked[index])
        }
        compare(nav("https://example.com", "claude", false, false), "allow")
        compare(nav("https://example.com/frame", "claude", true, false), "allow")
        compare(nav("http://example.com/", "claude", false, false), "allow")
        compare(nav("https://chat.example.org/", "claude", false, false,
            {claude: "https://chat.example.org/"}), "allow")
    }

    function test_localSubframes() {
        compare(nav("http://192.168.1.5/", "local", false, false), "block")
        compare(nav("http://example.com/", "local", false, false), "block")
        compare(nav("http://localhost:8080/", "local", false, false), "block")
        compare(nav("http://127.0.0.1:3000/", "local", false, false), "block")
        compare(nav("http://localhost:3000/x", "local", false, false), "allow")
        compare(nav("http://localhost:3000/x", "local", true, false), "allow")
        compare(nav("https://cdn.example", "local", false, false), "allow")
        compare(nav("https://localhost/", "local", false, false), "allow")
        compare(nav("about:blank", "local", false, false), "allow")
        compare(nav("blob:http://localhost:3000/0b1c", "local", false, false), "allow")
        compare(nav("data:text/html,x", "local", false, false), "allow")
        var ipv4 = {local: "http://127.0.0.1:8080/"}
        compare(nav("http://127.0.0.1:8080/f", "local", false, false, ipv4), "allow")
        compare(nav("http://localhost:3000/f", "local", false, false, ipv4), "block")
        var secure = {local: "https://ai.home.example/"}
        compare(nav("http://localhost:3000/", "local", false, false, secure), "block")
        compare(nav("https://ai.home.example/f", "local", false, false, secure), "allow")
    }

    function test_customUrlsParseAndSerialize() {
        var map = {local: "http://localhost:8080/", claude: "https://chat.example.org/x"}
        var json = ChatSites.serializeCustomUrls(map)
        // Catalog order, not insertion order.
        compare(json, "{\"claude\":\"https://chat.example.org/x\",\"local\":\"http://localhost:8080/\"}")
        compare(ChatSites.parseCustomUrls(json), map)
        compare(ChatSites.serializeCustomUrls(ChatSites.parseCustomUrls(json)), json)
        // Unknown ids, invalid, empty and non-string values are dropped.
        var dirty = {
            devin: "https://devin.example/",
            chatgpt: "http://chatgpt.example/",
            grok: "",
            gemini: 42,
            copilot: "https://localhost/",
            mscopilot: "https://copilot.example.net/",
            __proto__: "https://evil.example/"
        }
        compare(ChatSites.parseCustomUrls(JSON.stringify(dirty)),
                {mscopilot: "https://copilot.example.net/"})
        compare(ChatSites.serializeCustomUrls(dirty),
                "{\"mscopilot\":\"https://copilot.example.net/\"}")
        compare(ChatSites.serializeCustomUrls({}), "{}")
        compare(ChatSites.serializeCustomUrls(null), "{}")
        compare(ChatSites.serializeCustomUrls(["https://chat.example.org/"]), "{}")
        compare(ChatSites.serializeCustomUrls({claude: "not a url"}), "{}")
        var bad = ["", "not json", "[]", "[\"https://x.example/\"]", "null", "42",
                   "\"https://x.example/\"", "{\"claude\":[\"https://x.example/\"]}"]
        for (var index = 0; index < bad.length; index++)
            compare(ChatSites.parseCustomUrls(bad[index]), {}, bad[index])
        compare(ChatSites.parseCustomUrls(undefined), {})
        compare(ChatSites.parseCustomUrls(null), {})
    }

    function test_effectiveSite() {
        compare(ChatSites.effectiveSite("devin", {}), null)
        var builtIn = ChatSites.effectiveSite("claude")
        compare(builtIn.url, "https://claude.ai/new")
        compare(builtIn.exact_hosts, [])
        compare(builtIn.http_origin, "")
        var custom = ChatSites.effectiveSite("claude", {claude: "https://Chat.Example.org/x"})
        compare(custom.url, "https://Chat.Example.org/x")
        compare(custom.exact_hosts, ["chat.example.org"])
        compare(custom.site_hosts, ChatSites.byId("claude").site_hosts)
        // Stale or invalid custom values fall back to the built-in address.
        compare(ChatSites.effectiveSite("claude", {claude: "http://chat.example.org/"}).url,
                "https://claude.ai/new")
        compare(ChatSites.effectiveSite("claude", {claude: 7}).url, "https://claude.ai/new")
        compare(ChatSites.effectiveSite("claude", "nonsense").url, "https://claude.ai/new")
        compare(ChatSites.effectiveSite("local").http_origin, "localhost:3000")
        compare(ChatSites.effectiveSite("local", {local: "http://[::1]/"}).http_origin, "[::1]:80")
        compare(ChatSites.effectiveSite("local", {local: "https://ai.home.example/"}).http_origin, "")
        // Never mutates the catalog.
        custom.site_hosts.push("evil.example")
        compare(ChatSites.byId("claude").site_hosts.indexOf("evil.example"), -1)
    }

    function test_homeUrl() {
        compare(ChatSites.homeUrl("claude"), "https://claude.ai/new")
        compare(ChatSites.homeUrl("claude", {}), "https://claude.ai/new")
        compare(ChatSites.homeUrl("claude", {claude: "https://chat.example.org/x"}),
                "https://chat.example.org/x")
        compare(ChatSites.homeUrl("claude", {claude: "https://localhost/"}), "https://claude.ai/new")
        compare(ChatSites.homeUrl("local"), "http://localhost:3000/")
        compare(ChatSites.homeUrl("local", {local: "http://127.0.0.1:8080/"}), "http://127.0.0.1:8080/")
        compare(ChatSites.homeUrl("copilot"), "https://github.com/login?return_to=%2Fcopilot")
        compare(ChatSites.homeUrl("devin"), "")
    }

    function test_customHostIsExact() {
        var custom = {claude: "https://chat.example.org/x"}
        compare(nav("https://chat.example.org/x", "claude", false, true, custom), "allow")
        compare(nav("https://chat.example.org/other", "claude", true, true, custom), "allow")
        compare(nav("https://CHAT.example.org./other", "claude", true, true, custom), "allow")
        compare(nav("https://sub.chat.example.org/", "claude", true, true, custom), "external")
        compare(nav("https://example.org/", "claude", true, true, custom), "external")
        compare(nav("https://claude.ai/new", "claude", true, true, custom), "allow")
        // The custom host belongs to its own site only.
        compare(nav("https://chat.example.org/", "chatgpt", true, true, custom), "external")
        // Without customUrls: today's behaviour.
        compare(nav("https://chat.example.org/", "claude", true), "external")
        compare(nav("https://chat.example.org/", "claude", true, true, {}), "external")
        compare(nav("https://chat.example.org/", "claude", true, true, null), "external")
    }

    function test_localHttpRule() {
        compare(nav("http://localhost:3000/", "local", true), "allow")
        compare(nav("http://localhost:3000/c/1", "local", true), "allow")
        compare(nav("http://LOCALHOST:3000/c/1", "local", false), "allow")
        compare(nav("http://localhost:8080/", "local", false), "block")
        compare(nav("http://localhost/", "local", false), "block")
        compare(nav("http://127.0.0.1:3000/", "local", false), "block")
        compare(nav("http://[::1]:3000/", "local", false), "block")
        compare(nav("http://192.168.1.2:3000/", "local", false), "block")
        compare(nav("http://example.com/", "local", false), "block")
        var ipv4 = {local: "http://127.0.0.1:8080/"}
        compare(nav("http://127.0.0.1:8080/x", "local", true, true, ipv4), "allow")
        compare(nav("http://localhost:8080/x", "local", true, true, ipv4), "block")
        compare(nav("http://localhost:3000/x", "local", true, true, ipv4), "block")
        var ipv6 = {local: "http://[::1]/"}
        compare(nav("http://[::1]/", "local", false, true, ipv6), "allow")
        compare(nav("http://[::1]:80/", "local", false, true, ipv6), "allow")
        compare(nav("http://[::1]:3000/", "local", false, true, ipv6), "block")
        // A custom https address for Local turns http off entirely.
        var secure = {local: "https://ai.home.example/"}
        compare(nav("https://ai.home.example/c/1", "local", true, true, secure), "allow")
        compare(nav("https://other.example/", "local", true, true, secure), "external")
        compare(nav("http://localhost:3000/", "local", false, true, secure), "block")
        compare(nav("http://ai.home.example/", "local", false, true, secure), "block")
        compare(nav("https://localhost/", "local", false), "allow")
        compare(nav("file:///etc/passwd", "local", false), "block")
        compare(nav("javascript:alert(1)", "local", true), "block")
    }

    function test_loopbackBlockedForOtherSites() {
        var urls = [
            "http://localhost:3000",
            "http://localhost:3000/",
            "https://localhost/",
            "https://127.0.0.1/",
            "https://127.0.0.2/",
            "https://[::1]/",
            "https://[::1]:8443/",
            "https://2130706433/",
            "https://foo.localhost/",
            "https://0.0.0.0/"
        ]
        for (var index = 0; index < urls.length; index++) {
            compare(nav(urls[index], "claude", false), "block", urls[index])
            compare(nav(urls[index], "claude", true), "block", urls[index])
            compare(nav(urls[index], "mscopilot", true), "block", urls[index])
            compare(popup(urls[index], "claude"), "block", urls[index])
            compare(popup(urls[index], "claude", true), "block", urls[index])
        }
        // Even with a (rejected) loopback custom address.
        compare(nav("https://localhost/", "claude", true, true, {claude: "https://localhost/"}),
                "block")
    }

    function test_newWindowForLocal() {
        compare(popup("http://localhost:3000/", "local"), "block")
        compare(popup("http://localhost:3000/", "local", true), "block")
        compare(popup("http://127.0.0.1:3000/x", "local", true), "block")
        compare(popup("about:blank", "local", true), "overlay")
        compare(popup("", "local", true), "overlay")
        compare(popup("https://example.com/docs", "local"), "external")
        compare(popup("https://localhost/", "local"), "external")
        var secure = {local: "https://ai.home.example/"}
        compare(popup("http://ai.home.example/", "local", true, secure), "block")
        compare(popup("https://ai.home.example/x", "local", false, secure), "external")
    }

    function test_isPageUrl() {
        var claude = ChatSites.effectiveSite("claude")
        verify(ChatSites.isPageUrl(claude, "https://claude.ai/chat/1"))
        verify(ChatSites.isPageUrl(claude, "https://example.com/"))
        verify(!ChatSites.isPageUrl(claude, "http://claude.ai/"))
        verify(!ChatSites.isPageUrl(claude, "https://localhost/"))
        verify(!ChatSites.isPageUrl(claude, "https://[::1]/"))
        verify(!ChatSites.isPageUrl(claude, "about:blank"))
        verify(!ChatSites.isPageUrl(claude, "file:///etc/passwd"))
        verify(!ChatSites.isPageUrl(claude, ""))
        var local = ChatSites.effectiveSite("local")
        verify(ChatSites.isPageUrl(local, "http://localhost:3000/c/1"))
        verify(ChatSites.isPageUrl(local, "https://localhost/"))
        verify(ChatSites.isPageUrl(local, "https://ai.home.example/"))
        verify(!ChatSites.isPageUrl(local, "http://localhost:8080/"))
        verify(!ChatSites.isPageUrl(local, "http://127.0.0.1:3000/"))
        verify(!ChatSites.isPageUrl(local, "http://192.168.1.2:3000/"))
        var secure = ChatSites.effectiveSite("local", {local: "https://ai.home.example/"})
        verify(ChatSites.isPageUrl(secure, "https://ai.home.example/c/1"))
        verify(!ChatSites.isPageUrl(secure, "http://localhost:3000/"))
        verify(!ChatSites.isPageUrl(null, "https://claude.ai/"))
    }

    function test_isHttpUrlAndIsWebUrl_data() {
        return [
            {tag: "http", url: "http://example.org/a", http: true, https: false},
            {tag: "https", url: "https://example.org/a", http: false, https: true},
            {tag: "http upper", url: "HTTP://Example.ORG:8080/", http: true, https: false},
            {tag: "user info", url: "http://user@example.org/", http: false, https: false},
            {tag: "backslash", url: "http://example.org\\@evil.example/", http: false, https: false},
            {tag: "percent host", url: "http://ev%69l.example/", http: false, https: false},
            {tag: "no host", url: "http:///x", http: false, https: false},
            {tag: "bad port", url: "http://example.org:99999/", http: false, https: false},
            {tag: "no slashes", url: "http:example.org", http: false, https: false},
            {tag: "ftp", url: "ftp://example.org/", http: false, https: false},
            {tag: "file", url: "file:///etc/passwd", http: false, https: false},
            {tag: "javascript", url: "javascript:alert(1)", http: false, https: false},
            {tag: "blank", url: "about:blank", http: false, https: false},
            {tag: "empty", url: "", http: false, https: false},
            {tag: "null", url: null, http: false, https: false}
        ]
    }

    function test_isHttpUrlAndIsWebUrl(data) {
        compare(ChatSites.isHttpUrl(data.url), data.http)
        compare(ChatSites.isHttpsUrl(data.url), data.https)
        compare(ChatSites.isWebUrl(data.url), data.http || data.https)
    }

    function test_httpWarnedSites() {
        compare(ChatSites.httpWarnOrigin("http://Example.ORG/a?b#c"), "http://example.org:80")
        compare(ChatSites.httpWarnOrigin("http://example.org:8080/"), "http://example.org:8080")
        compare(ChatSites.httpWarnOrigin("http://[::1]:3000/"), "http://[::1]:3000")
        compare(ChatSites.httpWarnOrigin("https://example.org/"), "")
        compare(ChatSites.httpWarnOrigin("junk"), "")
        // Only canonical http origins are kept, once each.
        var clean = ChatSites.cleanWarnedSites(["http://a.example:80", "http://a.example:80",
            "http://A.example:80", "https://b.example:443", "a.example", 5, null, "http://c.example",
            "http://d.example:81"])
        compare(clean, ["http://a.example:80", "http://d.example:81"])
        compare(ChatSites.cleanWarnedSites("http://a.example:80"), [])
        compare(ChatSites.cleanWarnedSites(null), [])
        compare(ChatSites.cleanWarnedSites(undefined), [])
        var added = ChatSites.addWarnedSite(["http://a.example:80"], "http://b.example/x")
        compare(added, ["http://a.example:80", "http://b.example:80"])
        compare(ChatSites.addWarnedSite(added, "http://b.example:80/y"), added)
        compare(ChatSites.addWarnedSite(added, "https://c.example/"), added)
        compare(ChatSites.addWarnedSite(added, "ftp://c.example/"), added)
        compare(ChatSites.addWarnedSite(null, "http://z.example/"), ["http://z.example:80"])
        verify(ChatSites.isWarnedSite(added, "http://b.example/else"))
        verify(!ChatSites.isWarnedSite(added, "http://b.example:81/"))
        verify(!ChatSites.isWarnedSite(added, "https://b.example/"))
        // Capped: the oldest go first.
        var many = []
        for (var index = 0; index < 205; index++)
            many = ChatSites.addWarnedSite(many, "http://h" + index + ".example/")
        compare(many.length, 200)
        compare(many[0], "http://h5.example:80")
        compare(many[199], "http://h204.example:80")
        compare(ChatSites.cleanWarnedSites(many).length, 200)
    }

    function test_isHttpsUrl() {
        verify(ChatSites.isHttpsUrl("https://claude.ai/new"))
        verify(!ChatSites.isHttpsUrl("http://claude.ai/"))
        verify(!ChatSites.isHttpsUrl("about:blank"))
        verify(!ChatSites.isHttpsUrl(""))
    }

    function test_userAgent() {
        var ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            + "QtWebEngine/6.11.3 Chrome/134.0.6998.208 Safari/537.36"
        compare(ChatSites.userAgent(ua),
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                + "Chrome/134.0.6998.208 Safari/537.36")
        verify(ChatSites.userAgent(ua).indexOf("Chrome/134.0.6998.208") >= 0)
        verify(ChatSites.userAgent(ua).indexOf("X11; Linux x86_64") >= 0)
        compare(ChatSites.userAgent("Mozilla/5.0 Chrome/1.0"), "Mozilla/5.0 Chrome/1.0")
        compare(ChatSites.userAgent(undefined), "")
    }

    function test_isGoogleSignInHost() {
        verify(ChatSites.isGoogleSignInHost("https://accounts.google.com/"))
        verify(ChatSites.isGoogleSignInHost("https://accounts.google.com"))
        verify(ChatSites.isGoogleSignInHost(
            "https://accounts.google.com/v3/signin/identifier?continue=https%3A%2F%2Fclaude.ai"))
        verify(ChatSites.isGoogleSignInHost("HTTPS://Accounts.Google.COM/signin"))
        verify(ChatSites.isGoogleSignInHost("https://accounts.google.com:443/o/oauth2/auth"))
        var rejected = [
            "http://accounts.google.com/",
            "wss://accounts.google.com/",
            "https:accounts.google.com/",
            "https://accounts.google.com:8443/",
            "https://accounts.google.com./",
            "https://accounts.google.com.evil.example/",
            "https://evilaccounts.google.com/",
            "https://evil-accounts.google.com/",
            "https://x.accounts.google.com/",
            "https://google.com/",
            "https://gemini.google.com/app",
            "https://accounts.google.co/",
            "https://accounts.google.com@evil.example/",
            "https://user@accounts.google.com/",
            "https://evil.example/?u=https://accounts.google.com/",
            "https://evil.example/#https://accounts.google.com",
            "https://evil.example\\@accounts.google.com/",
            "https://accounts%2egoogle.com/",
            " https://accounts.google.com/",
            "about:blank",
            "",
            undefined,
            null
        ]
        for (var index = 0; index < rejected.length; index++)
            verify(!ChatSites.isGoogleSignInHost(rejected[index]), String(rejected[index]))
    }

    function test_userAgentFor() {
        var ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            + "QtWebEngine/6.11.3 Chrome/134.0.6998.208 Safari/537.36"
        var stripped = ChatSites.userAgent(ua)
        var firefox = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
        compare(ChatSites.GOOGLE_SIGNIN_UA, firefox)
        compare(ChatSites.userAgentFor("https://accounts.google.com/signin", ua), firefox)
        compare(ChatSites.userAgentFor("https://claude.ai/new", ua), stripped)
        compare(ChatSites.userAgentFor("https://gemini.google.com/app", ua), stripped)
        compare(ChatSites.userAgentFor("https://accounts.google.com.evil.example/", ua), stripped)
        compare(ChatSites.userAgentFor("http://accounts.google.com/", ua), stripped)
        compare(ChatSites.userAgentFor("", ua), stripped)
        compare(ChatSites.userAgentFor(undefined, ua), stripped)
        // Lists: any page on the sign-in host wins, since the profile is shared.
        compare(ChatSites.userAgentFor(["https://claude.ai/new", "https://accounts.google.com/"], ua),
                firefox)
        compare(ChatSites.userAgentFor(["https://claude.ai/new", "about:blank"], ua), stripped)
        compare(ChatSites.userAgentFor([], ua), stripped)
        // Already stripped stays the same.
        compare(ChatSites.userAgentFor("https://claude.ai/", stripped), stripped)
    }

    function test_popupSize() {
        var gu = 18
        compare(ChatSites.popupSize("usage", gu, 1920, 1080), {width: 23 * gu, height: 28 * gu})
        // Clamped to the screen too, never below the popup minimums.
        compare(ChatSites.popupSize("usage", gu, 100, 100), {width: 18 * gu, height: 15 * gu})
        compare(ChatSites.popupSize("chat", gu, 1920, 1080), {width: 34 * gu, height: 40 * gu})
        compare(ChatSites.popupSize("chat", gu, 600, 700), {width: 600 - 2 * gu, height: 700 - 4 * gu})
        // Never below the existing popup minimums.
        compare(ChatSites.popupSize("chat", gu, 200, 200), {width: 18 * gu, height: 15 * gu})
        compare(ChatSites.popupSize("chat", gu, 0, undefined), {width: 34 * gu, height: 40 * gu})
    }

    // Split view: wide enough for two chat sites, same height as Chat.
    function test_popupSizeSplit() {
        var gu = 18
        compare(ChatSites.popupSize("split", gu, 1920, 1080), {width: 52 * gu, height: 40 * gu})
        compare(ChatSites.popupSize("split", gu, 1920, 1080, 1.25),
                {width: Math.round(52 * gu * 1.25), height: Math.round(40 * gu * 1.25)})
        compare(ChatSites.popupSize("split", gu, 1920, 1080, 0.8),
                {width: Math.round(52 * gu * 0.8), height: Math.round(40 * gu * 0.8)})
        // Still clamped to the screen.
        compare(ChatSites.popupSize("split", gu, 800, 600), {width: 800 - 2 * gu, height: 600 - 4 * gu})
        compare(ChatSites.popupSize("split", gu, 200, 200), {width: 18 * gu, height: 15 * gu})
    }

    // Settings → General → Size scales the popup, still within the screen.
    function test_popupSizeScale() {
        var gu = 18
        compare(ChatSites.popupSize("chat", gu, 4000, 4000, 1), {width: 34 * gu, height: 40 * gu})
        compare(ChatSites.popupSize("chat", gu, 4000, 4000, 1.25),
                {width: Math.round(34 * gu * 1.25), height: Math.round(40 * gu * 1.25)})
        compare(ChatSites.popupSize("usage", gu, 4000, 4000, 0.8),
                {width: Math.round(23 * gu * 0.8), height: Math.round(28 * gu * 0.8)})
        compare(ChatSites.popupSize("chat", gu, 1366, 768, 1.25),
                {width: Math.round(34 * gu * 1.25), height: 768 - 4 * gu})
        // Odd scales are 1.
        compare(ChatSites.popupSize("chat", gu, 4000, 4000, 0), {width: 34 * gu, height: 40 * gu})
        compare(ChatSites.popupSize("chat", gu, 4000, 4000, -2), {width: 34 * gu, height: 40 * gu})
        compare(ChatSites.popupSize("chat", gu, 4000, 4000, "x"), {width: 34 * gu, height: 40 * gu})
        compare(ChatSites.popupSize("chat", gu, 4000, 4000, Infinity), {width: 34 * gu, height: 40 * gu})
        // Compact never goes below the popup minimums.
        compare(ChatSites.popupSize("usage", 10, 0, 0, 0.8), {width: 184, height: 224})
    }

    // The popup width around split view (FullRepresentation.fitSplit).
    function splitStep(show, popupWidth, before, repair) {
        // gu 18: split 52 gu, chat 34 gu; the window adds 12 px around it.
        return ChatSites.splitWidthStep({
            show: show, popupWidth: popupWidth, padding: 12,
            splitWidth: 52 * 18, normalWidth: 34 * 18, before: before, repair: repair
        })
    }

    function test_splitWidthStepWidens() {
        // Split shown: widen and remember the width to go back to.
        compare(splitStep(true, 400, 0), {width: 52 * 18 + 12, before: 400})
        // Already widened (or wider by hand): leave it, keep what to go back to.
        compare(splitStep(true, 52 * 18 + 12, 400), {width: 0, before: 400})
        compare(splitStep(true, 2000, 0), {width: 0, before: 0})
        // Widened again before narrowing: the first width stays.
        compare(splitStep(true, 500, 400), {width: 52 * 18 + 12, before: 400})
    }

    function test_splitWidthStepNarrows() {
        // Split hidden (Split off, Usage tab, Ollama, Chat tab hidden): back.
        compare(splitStep(false, 52 * 18 + 12, 400), {width: 400, before: 0})
        // Nothing to go back to: leave it.
        compare(splitStep(false, 700, 0), {width: 0, before: 0})
        // Closing with split shown narrows; opening again with it shown widens.
        var closed = splitStep(false, 52 * 18 + 12, 400)
        compare(splitStep(true, closed.width, closed.before), {width: 52 * 18 + 12, before: 400})
    }

    // After a Plasma restart the saved width can be the split width (the
    // size is saved before narrowing): the first open puts it back.
    function test_splitWidthStepRepairsTheFirstOpen() {
        compare(splitStep(false, 52 * 18 + 12, 0, true), {width: 34 * 18 + 12, before: 0})
        compare(splitStep(false, 52 * 18 + 13, 0, true), {width: 34 * 18 + 12, before: 0})
        compare(splitStep(false, 52 * 18 + 11, 0, true), {width: 34 * 18 + 12, before: 0})
        // Only within 1 px of the split width, only on the first open.
        compare(splitStep(false, 52 * 18 + 14, 0, true), {width: 0, before: 0})
        compare(splitStep(false, 700, 0, true), {width: 0, before: 0})
        compare(splitStep(false, 52 * 18 + 12, 0, false), {width: 0, before: 0})
        compare(splitStep(false, 52 * 18 + 12, 0), {width: 0, before: 0})
        // Never while split is shown.
        compare(splitStep(true, 52 * 18 + 12, 0, true), {width: 0, before: 0})
        // The Usage tab's width when Usage shows.
        compare(ChatSites.splitWidthStep({show: false, popupWidth: 52 * 18 + 12, padding: 12,
                                          splitWidth: 52 * 18, normalWidth: 23 * 18, repair: true}),
                {width: 23 * 18 + 12, before: 0})
        // A small screen clamps both to the same width: nothing to repair.
        compare(ChatSites.splitWidthStep({show: false, popupWidth: 600, padding: 0,
                                          splitWidth: 600, normalWidth: 600, repair: true}),
                {width: 0, before: 0})
    }

    // A size change before the first open (applyPopupSize) leaves no width
    // to go back to unless split is shown; the step then follows it.
    function test_splitWidthStepAfterSizeChange() {
        var scaled = Math.round(52 * 18 * 1.25)
        var chat = Math.round(34 * 18 * 1.25)
        compare(ChatSites.splitWidthStep({show: true, popupWidth: scaled + 12, padding: 12,
                                          splitWidth: scaled, normalWidth: chat, before: chat + 12}),
                {width: 0, before: chat + 12})
        compare(ChatSites.splitWidthStep({show: false, popupWidth: scaled + 12, padding: 12,
                                          splitWidth: scaled, normalWidth: chat, before: chat + 12}),
                {width: chat + 12, before: 0})
        // The old scale's split width is not repaired at the new scale.
        compare(ChatSites.splitWidthStep({show: false, popupWidth: 52 * 18 + 12, padding: 12,
                                          splitWidth: scaled, normalWidth: chat, repair: true}),
                {width: 0, before: 0})
    }

    // R3: with maxPadding, a widening or first-open repair waits while the
    // measured padding is outside 0..maxPadding (window not laid out yet);
    // narrowing back never waits.
    function test_splitWidthStepWaitsForAPlausiblePadding() {
        var step = function (show, padding, before, repair) {
            return ChatSites.splitWidthStep({
                show: show, popupWidth: 400, padding: padding, maxPadding: 4 * 18,
                splitWidth: 52 * 18, normalWidth: 34 * 18, before: before, repair: repair
            })
        }
        compare(step(true, 12, 0), {width: 52 * 18 + 12, before: 400})
        compare(step(true, 0, 0), {width: 52 * 18, before: 400})
        compare(step(true, 4 * 18, 0), {width: 52 * 18 + 4 * 18, before: 400})
        compare(step(true, 4 * 18 + 1, 0), {width: 0, before: 0, wait: true})
        compare(step(true, -1, 0), {width: 0, before: 0, wait: true})
        compare(step(true, -400, 300), {width: 0, before: 300, wait: true})
        compare(step(true, NaN, 0), {width: 0, before: 0, wait: true})
        compare(step(true, undefined, 0), {width: 0, before: 0, wait: true})
        compare(step(true, "x", 0), {width: 0, before: 0, wait: true})
        // The first-open repair waits too.
        compare(step(false, 500, 0, true), {width: 0, before: 0, wait: true})
        // Narrowing back goes ahead whatever the padding.
        compare(step(false, -50, 300), {width: 300, before: 0})
        compare(step(false, 9999, 300), {width: 300, before: 0})
        compare(step(false, 9999, 0), {width: 0, before: 0})
        // Without maxPadding nothing waits (old callers).
        compare(ChatSites.splitWidthStep({show: true, popupWidth: 400, padding: 9999,
                                          splitWidth: 52 * 18}), {width: 52 * 18 + 9999, before: 400})
        compare(ChatSites.splitWidthStep({show: true, popupWidth: 400, padding: -5, maxPadding: 0,
                                          splitWidth: 52 * 18}), {width: 52 * 18, before: 400})
    }

    function test_splitWidthStepOddInput() {
        compare(ChatSites.splitWidthStep(undefined), {width: 0, before: 0})
        compare(ChatSites.splitWidthStep({show: "yes", popupWidth: 400, splitWidth: 936}), {width: 0, before: 0})
        compare(ChatSites.splitWidthStep({show: true, popupWidth: "x", padding: -5, splitWidth: 936}),
                {width: 936, before: 0})
        compare(ChatSites.splitWidthStep({show: true, popupWidth: 400, splitWidth: NaN}), {width: 0, before: 0})
        compare(ChatSites.splitWidthStep({show: false, popupWidth: 400, before: Infinity}), {width: 0, before: 0})
    }

    // --- Local web UI owner check (M2) --------------------------------------

    function test_localOwnerPort() {
        var port = function (url, siteId, customUrls) {
            return ChatSites.localOwnerPort({ siteId: siteId === undefined ? "local" : siteId,
                                              customUrls: customUrls, url: url })
        }
        compare(port("http://localhost:3000/"), 3000)
        compare(port("http://127.0.0.1:8080/c/1"), 8080)
        compare(port("http://[::1]:5/"), 5)
        compare(port("http://localhost/"), 80)
        compare(port("https://localhost/"), 443)
        compare(port("https://127.0.0.1:8443/"), 8443)
        // Every spelling of this computer counts, not just the http ones.
        compare(port("https://foo.localhost:9000/"), 9000)
        compare(port("https://127.1:9001/"), 9001)
        compare(port("https://0x7f000001:9002/"), 9002)
        // L5: these names are this computer too; never loaded unchecked.
        compare(port("https://localhost.localdomain:9003/"), 9003)
        compare(port("https://app.localhost.localdomain/"), 443)
        compare(port("https://ip6-localhost:9004/"), 9004)
        compare(port("https://ip6-loopback/"), 443)
        compare(port("https://prime:8080/"), 8080)
        compare(port("https://myhost/"), 443)
        // Not this computer, not Local, or nothing to check.
        compare(port("https://example.com/"), 0)
        compare(port("https://example.com:3000/"), 0)
        compare(port("about:blank"), 0)
        compare(port("data:text/html,x"), 0)
        compare(port("http://user@localhost:3000/"), 0)
        compare(port(""), 0)
        compare(port(undefined), 0)
        compare(port("http://localhost:3000/", "claude"), 0)
        compare(port("http://localhost:3000/", "nope"), 0)
        compare(ChatSites.localOwnerPort(undefined), 0)
    }

    function test_localOwnerGate() {
        var gate = function (url, pass, isMainFrame, siteId) {
            return ChatSites.localOwnerGate({ siteId: siteId === undefined ? "local" : siteId,
                                              url: url, pass: pass, isMainFrame: isMainFrame })
        }
        compare(gate("http://localhost:3000/", ""), "check")
        compare(gate("http://localhost:3000/", undefined), "check")
        compare(gate("http://localhost:3000/", "http://localhost:3000/"), "go")
        // A pass is for exactly one address.
        compare(gate("http://localhost:3000/x", "http://localhost:3000/"), "check")
        compare(gate("https://localhost:3001/", "http://localhost:3000/"), "check")
        // Missing frame info is the main frame.
        compare(gate("http://localhost:3000/", "", undefined), "check")
        compare(gate("http://localhost:3000/", "", false), "skip")
        compare(gate("https://example.com/", ""), "skip")
        compare(gate("about:blank", ""), "skip")
        compare(gate("http://localhost:3000/", "", true, "claude"), "skip")
        compare(ChatSites.localOwnerGate(undefined), "skip")
    }

    // --- off-site notice (L2) ------------------------------------------------

    function test_punycode() {
        // RFC 3492 / IDNA samples.
        compare(ChatSites.displayHost("https://bücher.example/"), "xn--bcher-kva.example")
        compare(ChatSites.displayHost("https://münchen.de/"), "xn--mnchen-3ya.de")
        compare(ChatSites.displayHost("https://пример.рф/"), "xn--e1afmkfd.xn--p1ai")
        compare(ChatSites.displayHost("https://例え.テスト/"), "xn--r8jz45g.xn--zckzah")
        // Cyrillic look-alike of "apple": never shown as Latin letters.
        compare(ChatSites.displayHost("https://аррӏе.com/"), "xn--80ak6aa92e.com")
        compare(ChatSites.displayHost("https://\ud83d\ude00.example/"), "xn--e28h.example")
    }

    function test_displayHost() {
        compare(ChatSites.displayHost("https://Claude.AI./new"), "claude.ai")
        compare(ChatSites.displayHost("https://user:pw@evil.example:8443/x"), "evil.example")
        compare(ChatSites.displayHost("http://[::1]:3000/"), "[::1]")
        compare(ChatSites.displayHost("https://BÜCHER.example/"), "xn--bcher-kva.example")
        compare(ChatSites.displayHost("https://a。b.example/"), "a.b.example")
        compare(ChatSites.displayHost("https://<img src=x>/"), "")
        compare(ChatSites.displayHost("https://ev%69l.example/"), "")
        compare(ChatSites.displayHost("https://a b/"), "")
        compare(ChatSites.displayHost("https://[x]/"), "")
        compare(ChatSites.displayHost("about:blank"), "")
        compare(ChatSites.displayHost("data:text/html,x"), "")
        compare(ChatSites.displayHost(undefined), "")
    }

    function off(url, siteId, customUrls) {
        return ChatSites.offSiteHost({ siteId: siteId === undefined ? "claude" : siteId,
                                       customUrls: customUrls, url: url })
    }

    function test_offSiteHostKnownHostsAreOnSite() {
        compare(off("https://claude.ai/new"), { off: false, host: "" })
        compare(off("https://www.anthropic.com/"), { off: false, host: "" })
        // Sign-in hosts are part of the site: OAuth flows show no notice.
        compare(off("https://accounts.google.com/o/oauth2"), { off: false, host: "" })
        compare(off("https://appleid.apple.com/auth"), { off: false, host: "" })
        compare(off("https://login.microsoftonline.com/x", "chatgpt"), { off: false, host: "" })
        compare(off("https://auth.openai.com/log-in", "chatgpt"), { off: false, host: "" })
        compare(off("http://localhost:3000/", "local"), { off: false, host: "" })
        // A custom address adds its exact host.
        compare(off("https://chat.example.org/", "claude", { claude: "https://chat.example.org/" }),
                { off: false, host: "" })
        // Nothing to say about blank or non-web pages.
        compare(off("about:blank"), { off: false, host: "" })
        compare(off(""), { off: false, host: "" })
        compare(off("data:text/html,x"), { off: false, host: "" })
    }

    function test_offSiteHostElsewhere() {
        compare(off("https://claude.ai.evil.example/login"), { off: true, host: "claude.ai.evil.example" })
        compare(off("https://evilclaude.ai/"), { off: true, host: "evilclaude.ai" })
        compare(off("https://сlaude.ai/"), { off: true, host: "xn--laude-0ye.ai" })
        compare(off("https://sub.chat.example.org/", "claude", { claude: "https://chat.example.org/" }),
                { off: true, host: "sub.chat.example.org" })
        compare(off("https://example.com/", "local"), { off: true, host: "example.com" })
        compare(off("https://accounts.google.com/", "copilot", {}), { off: false, host: "" })
        compare(off("https://accounts.google.com.evil/", "copilot"), { off: true, host: "accounts.google.com.evil" })
        // Unreadable host: still off, without a host.
        compare(off("https://ev%69l.example/"), { off: true, host: "" })
        // "\" is read as "/" by browsers: never the host after it.
        compare(off("https://evil.example\\@claude.ai/"), { off: true, host: "" })
        compare(off("https://claude.ai\\x/"), { off: true, host: "" })
    }

    function test_displayHostRejectsBackslashes() {
        compare(ChatSites.displayHost("https://evil.example\\@claude.ai/"), "")
        compare(ChatSites.displayHost("https://evil.example\\claude.ai/"), "")
        compare(ChatSites.displayHost("https://a\\b@claude.ai/"), "")
        // A backslash after the host (in the path) changes nothing.
        compare(ChatSites.displayHost("https://claude.ai/a\\b"), "claude.ai")
    }

    // N5: a sign-in window always names a host.
    function test_overlayHost() {
        compare(ChatSites.overlayHost({ url: "https://accounts.google.com/x", openerUrl: "https://claude.ai/" }),
                { kind: "page", host: "accounts.google.com" })
        compare(ChatSites.overlayHost({ url: "about:blank", openerUrl: "https://claude.ai/new" }),
                { kind: "opener", host: "claude.ai" })
        compare(ChatSites.overlayHost({ url: "", openerUrl: "https://Evil.Example./x" }),
                { kind: "opener", host: "evil.example" })
        compare(ChatSites.overlayHost({ url: "data:text/html,x", openerUrl: "https://сlaude.ai/" }),
                { kind: "opener", host: "xn--laude-0ye.ai" })
        compare(ChatSites.overlayHost({ url: "about:blank", openerUrl: "about:blank" }),
                { kind: "unknown", host: "" })
        compare(ChatSites.overlayHost({ url: "about:blank", openerUrl: "https://evil.example\\@claude.ai/" }),
                { kind: "unknown", host: "" })
        compare(ChatSites.overlayHost({}), { kind: "unknown", host: "" })
        compare(ChatSites.overlayHost(undefined), { kind: "unknown", host: "" })
        var long = ""
        for (var index = 0; index < 20; index++)
            long += "claude-ai-"
        var result = ChatSites.overlayHost({ url: "about:blank", openerUrl: "https://" + long + ".evil.example/" })
        compare(result.host.length, ChatSites.MAX_HOST_DISPLAY)
        verify(result.host.slice(-13) === ".evil.example")
    }

    function test_offSiteHostIsShortenedFromTheFront() {
        var long = ""
        for (var index = 0; index < 20; index++)
            long += "claude-ai-"
        var result = off("https://" + long + ".evil.example/")
        compare(result.off, true)
        compare(result.host.length, ChatSites.MAX_HOST_DISPLAY)
        compare(result.host.charAt(0), "…")
        verify(result.host.slice(-13) === ".evil.example")
    }
}
