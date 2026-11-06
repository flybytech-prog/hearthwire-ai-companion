from __future__ import annotations

import http.client
import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

# No provider answers with more than a few KiB; a body above this is refused
# (HttpError) instead of being read into memory whole.
MAX_BODY = 1024 * 1024
# ``timeout`` bounds each socket operation only, so a server that drips one
# byte per few seconds would keep a request alive indefinitely. This bounds the
# whole request (connect, TLS handshake, headers and body); beyond it the
# socket is shut down and the request raises TimeoutError.
TOTAL_DEADLINE = 20.0
_CHUNK = 65536


@dataclass
class HttpResponse:
    status: int
    body: bytes
    headers: dict[str, str]

    def json(self):
        return json.loads(self.body.decode("utf-8"))

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: the 3xx comes back to the caller as a response.

    urllib's default handler copies every request header except Content-Length
    and Content-Type (so Authorization too) to the redirect target, on any host
    and over plain http. No provider endpoint needs redirects, so a 3xx is
    returned like any other non-2xx status, and the providers classify it as a
    failed request.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

    def _refuse(self, req, fp, code, msg, headers):
        # Returning None hands the 3xx to HTTPDefaultErrorHandler, which raises
        # HTTPError; http_request turns that into an HttpResponse. The Location
        # header is never parsed.
        return None

    http_error_301 = http_error_302 = http_error_303 = _refuse
    http_error_307 = http_error_308 = _refuse


class _Deadline:
    """One request's overall deadline: at expiry every connection it opened is
    shut down, which makes the blocked read in http.client return or raise at once.

    Each watched socket is held as a dup of its descriptor: HTTPS detaches the
    original into an SSL socket, and a dup we own until cancel() can never be a
    descriptor number that was closed and reused meanwhile.
    """

    def __init__(self, seconds: float):
        self._at = time.monotonic() + seconds
        self._lock = threading.Lock()
        self._sockets: list[socket.socket] = []
        self.expired = False
        self._timer = threading.Timer(seconds, self._expire)
        self._timer.daemon = True

    def start(self) -> None:
        self._timer.start()

    def cancel(self) -> None:
        self._timer.cancel()
        with self._lock:
            sockets, self._sockets = self._sockets, []
        for sock in sockets:
            sock.close()

    def remaining(self) -> float:
        return self._at - time.monotonic()

    def watch(self, sock: socket.socket) -> None:
        watcher = sock.dup()
        with self._lock:
            if not self.expired:
                self._sockets.append(watcher)
                return
        _shutdown(watcher)
        watcher.close()

    def _expire(self) -> None:
        with self._lock:
            self.expired = True
            for sock in self._sockets:
                _shutdown(sock)


def _shutdown(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass  # The peer is gone already.


# The deadline of the request running in this thread (urllib opens the
# connection synchronously in the caller's thread).
_active = threading.local()


def _deadline_exceeded() -> TimeoutError:
    return TimeoutError("HTTP request exceeded its overall deadline.")


def _watched_connection(address, timeout, source_address=None, *args, **kwargs):
    deadline: _Deadline | None = getattr(_active, "deadline", None)
    if deadline is not None:
        remaining = deadline.remaining()
        if remaining <= 0:
            raise _deadline_exceeded()
        if not isinstance(timeout, (int, float)) or timeout > remaining:
            timeout = remaining
    sock = socket.create_connection(address, timeout, source_address, *args, **kwargs)
    if deadline is not None:
        # Before the TLS handshake (HTTPS wraps this socket afterwards), so a
        # slow handshake is covered too.
        try:
            deadline.watch(sock)
        except BaseException:
            sock.close()  # dup() failed (e.g. EMFILE): never leak the connection.
            raise
    return sock


class _WatchedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _watched_connection


class _WatchedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _watched_connection


class _WatchedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_WatchedHTTPConnection, req)


class _WatchedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_WatchedHTTPSConnection, req, context=self._context)


# Same handlers as urlopen's default opener (proxies from the environment,
# https), with the redirect handler replaced and the connections watched by
# the request deadline.
_OPENER = urllib.request.build_opener(_RefuseRedirects, _WatchedHTTPHandler, _WatchedHTTPSHandler)


class HttpError(Exception):
    def __init__(self, status: int, message: str = ""):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


def _too_large(status: int) -> HttpError:
    return HttpError(status, "response body too large")


def _read_body(resp, status: int, headers: Mapping[str, str], deadline: _Deadline) -> bytes:
    """At most MAX_BODY bytes; one byte more (or a larger Content-Length) is HttpError."""
    try:
        declared = int(headers.get("content-length", ""))
    except ValueError:
        declared = -1
    if declared > MAX_BODY:
        raise _too_large(status)
    chunks: list[bytes] = []
    total = 0
    while True:
        if deadline.expired:
            raise _deadline_exceeded()
        chunk = resp.read(min(_CHUNK, MAX_BODY + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_BODY:
            raise _too_large(status)
    if deadline.expired:
        raise _deadline_exceeded()  # The shutdown may have cut the body short.
    return b"".join(chunks)


def _headers(raw) -> dict[str, str]:
    return {k.lower(): v for k, v in (raw or {}).items()}


def http_request(
    method: str,
    url: str,
    headers: Mapping[str, str],
    *,
    body: bytes | None = None,
    timeout: float = 15.0,
) -> HttpResponse:
    """One request, no redirects followed.

    ``timeout`` bounds each socket operation; TOTAL_DEADLINE bounds the whole
    request (TimeoutError beyond it). A body over MAX_BODY raises HttpError.
    A non-2xx status is returned as a response, not raised.
    """
    req = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    deadline = _Deadline(TOTAL_DEADLINE)
    previous = getattr(_active, "deadline", None)
    _active.deadline = deadline
    deadline.start()
    try:
        try:
            with _OPENER.open(req, timeout=min(timeout, TOTAL_DEADLINE)) as resp:
                found = _headers(resp.headers)
                return HttpResponse(status=resp.status, body=_read_body(resp, resp.status, found, deadline),
                                    headers=found)
        except urllib.error.HTTPError as e:
            try:
                found = _headers(e.headers)
                return HttpResponse(status=e.code, body=_read_body(e, e.code, found, deadline),
                                    headers=found)
            finally:
                e.close()
    except (OSError, http.client.HTTPException):
        # urllib wraps socket errors in URLError (an OSError); after the
        # deadline shut the socket down, any of them means "too slow".
        if deadline.expired:
            raise _deadline_exceeded() from None
        raise
    finally:
        deadline.cancel()
        _active.deadline = previous


def http_get(url: str, headers: dict[str, str], timeout: float = 15.0) -> HttpResponse:
    return http_request("GET", url, headers, timeout=timeout)


def http_post_form(url: str, data: Mapping[str, str] | Iterable[tuple[str, str]],
                   headers: dict[str, str],
                   timeout: float = 15.0) -> HttpResponse:
    payload = urllib.parse.urlencode(
        data,
        quote_via=urllib.parse.quote,
    ).encode("utf-8")
    h = {"Content-Type": "application/x-www-form-urlencoded", **headers}
    return http_request("POST", url, h, body=payload, timeout=timeout)


def http_post_json(url: str, data: Mapping[str, Any], headers: dict[str, str],
                   timeout: float = 15.0) -> HttpResponse:
    payload = json.dumps(data, separators=(",", ":")).encode("utf-8")
    h = {"Content-Type": "application/json", **headers}
    return http_request("POST", url, h, body=payload, timeout=timeout)
