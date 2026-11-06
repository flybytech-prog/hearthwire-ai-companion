"""Fake sites for the runtime WebEngine tests. Run only by run.sh, inside a
private network namespace where nothing but loopback exists.

- "site": the chat site (claude.ai, mapped to 127.0.0.1 by a private
  /etc/hosts), HTTPS on 127.0.0.1:443 with a self-signed certificate made at
  run time. /new is the hostile page, /dl an attachment.
- "victim": a service on this computer, http on [::]:3999 and https on
  [::]:3998 (both IPv4 and IPv6). A page must never reach it.

Every request except GET /__hits is recorded; /__hits (victim, http) returns
{"site": [...], "victim": [...]} so a QML test can read what was reached.
"""

import http.server
import json
import socket
import socketserver
import ssl
import sys
import threading
from pathlib import Path

WORK = Path(sys.argv[1])
HOSTILE = (Path(__file__).resolve().parent / "hostile.html").read_bytes()
HITS = {"site": [], "victim": []}
LOCK = threading.Lock()
LOG = open(WORK / "hits.log", "a", buffering=1, encoding="utf-8")


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, kind, body, extra=()):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        for name, value in extra:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        tag = self.server.tag
        if tag == "victim" and self.path == "/__hits":
            with LOCK:
                body = json.dumps(HITS).encode()
            self.reply(200, "application/json", body, [("Access-Control-Allow-Origin", "*")])
            return
        entry = f"{self.headers.get('Host')} {self.command} {self.path}"
        with LOCK:
            HITS[tag].append(entry)
        LOG.write(f"{tag} {entry}\n")
        if tag == "site" and self.path.startswith("/new"):
            self.reply(200, "text/html; charset=utf-8", HOSTILE)
        elif tag == "site" and self.path.startswith("/dl"):
            self.reply(200, "application/octet-stream", b"not a real file\n",
                       [("Content-Disposition", 'attachment; filename="hearthwire-test.bin"')])
        elif tag == "site":
            self.reply(404, "text/plain", b"")
        else:
            self.reply(200, "text/html", b"<h1>LOCAL SERVICE</h1>")

    do_POST = do_GET


class Dual(socketserver.ThreadingMixIn, http.server.HTTPServer):
    address_family = socket.AF_INET6
    daemon_threads = True

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


class Four(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def tls(server):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(WORK / "cert.pem", WORK / "key.pem")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    return server


servers = []
site = tls(Four(("127.0.0.1", 443), Handler))
site.tag = "site"
victim = Dual(("::", 3999), Handler)
victim.tag = "victim"
victim_tls = tls(Dual(("::", 3998), Handler))
victim_tls.tag = "victim"
for server in (site, victim, victim_tls):
    threading.Thread(target=server.serve_forever, daemon=True).start()
(WORK / "ready").write_text("ok\n")
threading.Event().wait()
