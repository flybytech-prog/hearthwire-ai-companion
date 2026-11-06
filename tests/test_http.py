import os
import io
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from contextlib import contextmanager
from urllib.parse import urlencode

import pytest

from hearthwire.core import http
from hearthwire.core.model import FailureKind, ProviderStatus
from hearthwire.providers.copilot import CopilotProvider

DUMMY_TOKEN = "Bearer DUMMY-NOT-A-SECRET"


class _FakeResp:
    status = 200

    def __init__(self):
        self._body = io.BytesIO(b'{"access_token":"new"}')

    def read(self, size=-1):
        return self._body.read(size)

    @property
    def headers(self):
        return {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_http_post_form_sends_urlencoded(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=15.0):
        captured["data"] = req.data
        captured["ctype"] = req.headers.get("Content-type")
        captured["method"] = req.get_method()
        return _FakeResp()

    monkeypatch.setattr(http._OPENER, "open", fake_urlopen)
    payload = {"grant_type": "refresh_token", "refresh_token": "r"}
    resp = http.http_post_form("https://example.com/token", payload,
                               {"Accept": "application/json"})
    assert captured["method"] == "POST"
    assert captured["ctype"] == "application/x-www-form-urlencoded"
    assert captured["data"] == urlencode(payload).encode()
    assert resp.status == 200
    assert resp.json()["access_token"] == "new"


def test_http_post_form_uses_rfc3986_encoding(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=15.0):
        captured["data"] = req.data
        return _FakeResp()

    monkeypatch.setattr(http._OPENER, "open", fake_urlopen)
    http.http_post_form(
        "https://example.com/token",
        [("refresh_token", "a+b c&d")],
        {},
    )
    assert captured["data"] == b"refresh_token=a%2Bb%20c%26d"


def test_http_post_json_sends_compact_json(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=15.0):
        captured["data"] = req.data
        captured["ctype"] = req.headers.get("Content-type")
        return _FakeResp()

    monkeypatch.setattr(http._OPENER, "open", fake_urlopen)
    http.http_post_json("https://example.com/token", {"a": "b"}, {})
    assert captured["data"] == b'{"a":"b"}'
    assert captured["ctype"] == "application/json"


class _Origin(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, handler):
        super().__init__(("127.0.0.1", 0), handler)
        self.seen: list[tuple[str, str | None]] = []
        self.redirect_status = 302
        self.location = ""

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class _Recorder(BaseHTTPRequestHandler):
    """Second origin: records every request that reaches it."""

    def _answer(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self.server.seen.append((self.command, self.headers.get("Authorization")))
        body = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_PUT = _answer

    def log_message(self, *args):
        pass


class _Redirector(BaseHTTPRequestHandler):
    """First origin: answers every request with a redirect to the second origin."""

    def _answer(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self.server.seen.append((self.command, self.headers.get("Authorization")))
        body = b"moved"
        self.send_response(self.server.redirect_status)
        self.send_header("Location", self.server.location)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _answer

    def log_message(self, *args):
        pass


@contextmanager
def _two_origins(status: int):
    first, second = _Origin(_Redirector), _Origin(_Recorder)
    first.redirect_status = status
    first.location = second.url + "/stolen"
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (first, second)]
    for thread in threads:
        thread.start()
    try:
        yield first, second
    finally:
        for server in (first, second):
            server.shutdown()
            server.server_close()


@pytest.fixture
def _no_proxy(monkeypatch):
    for name in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setenv("NO_PROXY", "*")


REDIRECTS = (301, 302, 303, 307, 308)


@pytest.mark.parametrize("status", REDIRECTS)
def test_get_never_follows_redirects(_no_proxy, status):
    with _two_origins(status) as (first, second):
        resp = http.http_get(first.url + "/usage", {"Authorization": DUMMY_TOKEN}, timeout=5)
    assert first.seen == [("GET", DUMMY_TOKEN)]
    assert second.seen == []
    assert resp.status == status
    assert resp.body == b"moved"
    assert resp.header("location") == second.url + "/stolen"


@pytest.mark.parametrize("status", REDIRECTS)
def test_post_json_never_follows_redirects(_no_proxy, status):
    with _two_origins(status) as (first, second):
        resp = http.http_post_json(first.url + "/token", {"refresh_token": "dummy"},
                                   {"Authorization": DUMMY_TOKEN}, timeout=5)
    assert first.seen == [("POST", DUMMY_TOKEN)]
    assert second.seen == []
    assert resp.status == status


@pytest.mark.parametrize("status", REDIRECTS)
def test_post_form_never_follows_redirects(_no_proxy, status):
    with _two_origins(status) as (first, second):
        resp = http.http_post_form(first.url + "/token", {"refresh_token": "dummy"},
                                   {"Authorization": DUMMY_TOKEN}, timeout=5)
    assert first.seen == [("POST", DUMMY_TOKEN)]
    assert second.seen == []
    assert resp.status == status


def test_redirect_to_non_http_scheme_is_a_plain_response(_no_proxy):
    with _two_origins(302) as (first, second):
        first.location = "file:///etc/passwd"
        resp = http.http_get(first.url, {"Authorization": DUMMY_TOKEN}, timeout=5)
    assert resp.status == 302
    assert second.seen == []


class _Token:
    def load_token(self):
        return "DUMMY-NOT-A-SECRET"


@pytest.mark.parametrize("status", REDIRECTS)
def test_provider_classifies_redirect_as_invalid_response(_no_proxy, status):
    with _two_origins(status) as (first, second):
        provider = CopilotProvider(
            auth_store=_Token(),
            getter=lambda url, headers, **kw: http.http_get(first.url + "/copilot", headers, timeout=5),
        )
        usage = provider.fetch()
    assert second.seen == []
    assert usage.status == ProviderStatus.ERROR
    assert usage.failure_kind == FailureKind.INVALID_RESPONSE
    assert usage.error_message == f"Copilot usage request failed ({status})."
    assert "DUMMY" not in (usage.error_message or "")


# --- body cap and overall deadline (loopback server in this process) -------------------------


class _Shaped(BaseHTTPRequestHandler):
    """Answers by path: /ok, /status-404, /big-declared, /big-streamed, /exact,
    /drip-body, /drip-headers. Drips stop when the server's stop event is set."""

    protocol_version = "HTTP/1.1"

    def _send(self, status, body, length=True):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Test-Header", "Kept")
        if length:
            self.send_header("Content-Length", str(len(body)))
        else:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _drip(self, data: bytes):
        stop = self.server.stop
        for index in range(len(data)):
            if stop.wait(0.1):
                return
            try:
                self.wfile.write(data[index:index + 1])
                self.wfile.flush()
            except OSError:
                return

    def do_GET(self):
        path = self.path
        if path == "/ok":
            self._send(200, b'{"plan":"pro"}')
        elif path == "/status-404":
            self._send(404, b'{"error":"missing"}')
        elif path == "/exact":
            self._send(200, b"a" * http.MAX_BODY)
        elif path == "/big-declared":
            self.send_response(200)
            self.send_header("Content-Length", str(http.MAX_BODY + 1))
            self.end_headers()
            self.server.sent = 0
            try:
                self.wfile.write(b"a" * 1024)
            except OSError:
                pass
        elif path == "/big-streamed" or path == "/big-error":
            self.send_response(200 if path == "/big-streamed" else 500)
            self.send_header("Connection", "close")
            self.end_headers()
            sent = 0
            try:
                while sent < 400 * 1024 * 1024 and not self.server.stop.is_set():
                    self.wfile.write(b"a" * 65536)
                    sent += 65536
            except OSError:
                pass
            self.server.sent = sent
        elif path == "/drip-body":
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            self.wfile.flush()
            self._drip(b"a" * 1000)
        elif path == "/drip-headers":
            self._drip(b"HTTP/1.1 200 OK\r\nX-Slow: " + b"a" * 1000 + b"\r\n\r\n")
        self.close_connection = True

    def log_message(self, *args):
        pass


@contextmanager
def _shaped_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Shaped)
    server.daemon_threads = True
    server.stop = threading.Event()
    server.sent = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.stop.set()
        server.shutdown()
        server.server_close()


def test_normal_response_is_unchanged(_no_proxy):
    with _shaped_server() as (_server, url):
        resp = http.http_get(url + "/ok", {"Authorization": DUMMY_TOKEN}, timeout=5)
        missing = http.http_get(url + "/status-404", {}, timeout=5)
    assert resp.status == 200
    assert resp.json() == {"plan": "pro"}
    assert resp.header("X-Test-Header") == "Kept"
    assert resp.header("content-type") == "application/json"
    assert (missing.status, missing.body) == (404, b'{"error":"missing"}')


def test_a_body_of_exactly_the_cap_is_read(_no_proxy):
    with _shaped_server() as (_server, url):
        resp = http.http_get(url + "/exact", {}, timeout=5)
    assert len(resp.body) == http.MAX_BODY


def test_a_declared_oversized_body_is_refused_before_reading(_no_proxy):
    with _shaped_server() as (_server, url):
        with pytest.raises(http.HttpError) as raised:
            http.http_get(url + "/big-declared", {}, timeout=5)
    assert raised.value.status == 200
    assert "too large" in str(raised.value)


@pytest.mark.parametrize(("path", "status"), [("/big-streamed", 200), ("/big-error", 500)])
def test_an_undeclared_oversized_body_stops_after_the_cap(_no_proxy, path, status):
    with _shaped_server() as (server, url):
        with pytest.raises(http.HttpError) as raised:
            http.http_get(url + path, {}, timeout=5)
    assert raised.value.status == status
    # The 400 MiB stream was cut off long before the end.
    assert server.sent is None or server.sent < 64 * 1024 * 1024


@pytest.mark.parametrize("path", ["/drip-body", "/drip-headers"])
def test_a_slow_drip_is_aborted_at_the_overall_deadline(_no_proxy, monkeypatch, path):
    monkeypatch.setattr(http, "TOTAL_DEADLINE", 1.0)
    with _shaped_server() as (_server, url):
        started = time.monotonic()
        # Each byte arrives well within the 5 s per-read timeout.
        with pytest.raises(TimeoutError):
            http.http_get(url + path, {"Authorization": DUMMY_TOKEN}, timeout=5)
        elapsed = time.monotonic() - started
    assert 0.9 <= elapsed < 4.0


def test_the_deadline_closes_its_watch_descriptors(_no_proxy):
    before = len(os.listdir("/proc/self/fd"))
    with _shaped_server() as (_server, url):
        for _ in range(5):
            http.http_get(url + "/ok", {}, timeout=5)
    time.sleep(0.2)
    assert len(os.listdir("/proc/self/fd")) <= before + 2


def test_https_connections_are_watched_too():
    # The deadline watches the socket before the TLS wrap (HTTPS handshake included).
    connection = http._WatchedHTTPSConnection("127.0.0.1", 1)
    assert connection._create_connection is http._watched_connection
    assert http._watched_connection.__name__ == "_watched_connection"
    handlers = {type(handler) for handler in http._OPENER.handlers}
    assert http._WatchedHTTPSHandler in handlers and http._WatchedHTTPHandler in handlers


def test_the_deadline_shuts_down_a_detached_socket_through_its_dup():
    left, right = socket.socketpair()
    deadline = http._Deadline(0.2)
    try:
        deadline.watch(left)
        deadline.start()
        left.settimeout(5)
        started = time.monotonic()
        assert left.recv(1) == b""  # Shut down by the timer, not the 5 s timeout.
        assert time.monotonic() - started < 3
        assert deadline.expired
    finally:
        deadline.cancel()
        left.close()
        right.close()


def test_a_slow_provider_request_is_a_failure_not_a_hang(_no_proxy, monkeypatch):
    monkeypatch.setattr(http, "TOTAL_DEADLINE", 1.0)
    with _shaped_server() as (_server, url):
        provider = CopilotProvider(
            auth_store=_Token(),
            getter=lambda _url, headers, **kw: http.http_get(url + "/drip-body", headers, timeout=5),
        )
        usage = provider.fetch()
    assert usage.status == ProviderStatus.ERROR
    assert "DUMMY" not in (usage.error_message or "")


def test_a_failed_watch_dup_closes_the_fresh_socket(_no_proxy, monkeypatch):
    created = []
    real_create = socket.create_connection

    def recording_create(*args, **kwargs):
        sock = real_create(*args, **kwargs)
        created.append(sock)
        return sock

    def no_descriptors(self):
        raise OSError(24, "Too many open files")

    monkeypatch.setattr(socket, "create_connection", recording_create)
    monkeypatch.setattr(socket.socket, "dup", no_descriptors)
    with _shaped_server() as (_server, url):
        with pytest.raises(OSError):
            http.http_get(url + "/ok", {}, timeout=5)
    assert len(created) == 1
    assert created[0].fileno() == -1  # Closed, not leaked.
