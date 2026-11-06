"""Who owns the TCP listener the built-in Ollama chat is about to talk to.

The plasmoid runs ``hearthwire --port-owner N`` before every model-list load
and every send, so a prompt never goes to another user's program that took
the port while Ollama was down. Only ``/proc/net/tcp`` and ``/proc/net/tcp6``
are read: no socket is opened and nothing is sent anywhere. The reply is one
word; uids, user names, inodes and addresses never leave this module.
"""

from __future__ import annotations

import ipaddress
import os
import pwd
import sys
from collections.abc import Iterable
from pathlib import Path

PROC_NET = Path("/proc/net")
OLLAMA_USER = "ollama"
MIN_PORT = 1
MAX_PORT = 65535

_LISTEN = "0A"
# Bind addresses a connection to 127.0.0.1, localhost or [::1] can reach.
_LOOPBACK_V4 = frozenset(ipaddress.IPv4Address(text) for text in ("127.0.0.1", "0.0.0.0"))
_LOOPBACK_V6 = frozenset(
    ipaddress.IPv6Address(text) for text in ("::1", "::", "::ffff:127.0.0.1", "::ffff:0.0.0.0")
)
# The kernel prints each 32-bit address word in host byte order.
_BYTE_ORDER = sys.byteorder


class ProcNetError(ValueError):
    """A /proc/net/tcp line did not have the expected shape."""


def _address(text: str, ipv6: bool) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    if len(text) != (32 if ipv6 else 8):
        raise ProcNetError("address length")
    raw = b"".join(
        int(text[index:index + 8], 16).to_bytes(4, _BYTE_ORDER)
        for index in range(0, len(text), 8)
    )
    return ipaddress.IPv6Address(raw) if ipv6 else ipaddress.IPv4Address(raw)


def listener_uids(text: str, port: int, ipv6: bool) -> list[int]:
    """Uids of LISTEN sockets on ``port`` that loopback connections can reach.

    Any line that does not parse fails the whole file: a check that cannot
    read the table must not report "none".
    """
    lines = text.splitlines()
    if not lines or not lines[0].split() or lines[0].split()[0] != "sl":
        raise ProcNetError("header")
    allowed = _LOOPBACK_V6 if ipv6 else _LOOPBACK_V4
    uids = []
    for line in lines[1:]:
        fields = line.split()
        if not fields:
            continue
        if len(fields) < 10 or not fields[0].endswith(":"):
            raise ProcNetError("fields")
        address_text, sep, port_text = fields[1].partition(":")
        if not sep or len(port_text) != 4 or len(fields[3]) != 2:
            raise ProcNetError("local address")
        address = _address(address_text, ipv6)
        local_port = int(port_text, 16)
        state = fields[3].upper()
        int(state, 16)
        uid = int(fields[7], 10)
        if uid < 0:
            raise ProcNetError("uid")
        if state == _LISTEN and local_port == port and address in allowed:
            uids.append(uid)
    return uids


def trusted_uids(own_uid: int) -> frozenset[int]:
    """The session user, root, and the system ``ollama`` account if it exists."""
    trusted = {own_uid, 0}
    try:
        trusted.add(pwd.getpwnam(OLLAMA_USER).pw_uid)
    except KeyError:
        pass
    return frozenset(trusted)


def classify(uids: Iterable[int], own_uid: int, trusted: Iterable[int]) -> str:
    owners = set(uids)
    if not owners:
        return "none"
    if not owners <= set(trusted):
        return "other"
    if owners == {own_uid}:
        return "self"
    return "system"


def run(port: int, proc_net: Path | None = None) -> dict[str, object]:
    """One reply object; any doubt is ``unreadable`` (the plasmoid fails closed)."""
    proc_net = PROC_NET if proc_net is None else proc_net
    if not isinstance(port, int) or isinstance(port, bool) or not MIN_PORT <= port <= MAX_PORT:
        return {"ok": False, "error": "unreadable"}
    try:
        uids = listener_uids((proc_net / "tcp").read_text(encoding="ascii"), port, ipv6=False)
        try:
            tcp6 = (proc_net / "tcp6").read_text(encoding="ascii")
        except FileNotFoundError:
            # No IPv6 in this kernel (ipv6.disable=1): no IPv6 socket can exist.
            tcp6 = None
        if tcp6 is not None:
            uids += listener_uids(tcp6, port, ipv6=True)
        own_uid = os.getuid()
        owner = classify(uids, own_uid, trusted_uids(own_uid))
    except (OSError, ValueError):
        return {"ok": False, "error": "unreadable"}
    return {"ok": True, "owner": owner}
