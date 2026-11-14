"""Who owns the TCP listener the built-in Ollama chat is about to talk to.

The plasmoid runs ``hearthwire --port-owner N`` before every model-list load
and every send, so a prompt never goes to another user's program that took
the port while Ollama was down. Only ``/proc/net/tcp`` and ``/proc/net/tcp6``
are read: no socket is opened and nothing is sent anywhere. The reply is one
word; uids, user names, inodes and addresses never leave this module.

Task 006 (round 2, SEC LOW-2): ``--port-owner N --address IP`` does the same
for a chat site the user added by a home-network IP address. When IP is one
of this computer's own addresses, another local user could listen on it (or
on the wildcard) and get the site's cookies and prompts, so the same owner
check applies, counting listeners on IP and on the wildcard. When it isn't,
the connection leaves the machine and the answer is ``remote``. This
computer's addresses come from the kernel's tables only:
``/proc/net/fib_trie`` LOCAL routes (IPv4), ``/proc/net/if_inet6`` and the
RTF_LOCAL routes of ``/proc/net/ipv6_route`` (IPv6). A bind test would lie
under ``net.ipv4.ip_nonlocal_bind``. Anything unreadable is ``unreadable``.
"""

from __future__ import annotations

import ipaddress
import os
import pwd
import sys
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Optional, Union

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

# --address: exactly the host of a private added site (settingsbackup.address_class
# "private"): a canonical dotted quad in 10/8, 172.16/12, 192.168/16, or a
# bracketed lower-case canonical IPv6 literal in fc00::/7 outside fd00:ec2::/32.
_PRIVATE_V4 = tuple(ipaddress.IPv4Network(text) for text in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
_PRIVATE_V6 = ipaddress.IPv6Network("fc00::/7")
_METADATA_V6 = ipaddress.IPv6Network("fd00:ec2::/32")
_CANONICAL_V4 = re.compile(r"(?:0|[1-9][0-9]{0,2})(?:\.(?:0|[1-9][0-9]{0,2})){3}")
_BRACKETED_V6 = re.compile(r"\[([0-9a-f:]{2,39})\]")
# /proc/net/fib_trie, as the kernel prints it (net/ipv4/fib_trie.c fib_trie_seq_show).
_TRIE_TABLE = re.compile(r"(?:Main|Local|Id [0-9]+):")
_TRIE_NODE = re.compile(r" +\+-- [0-9.]+/[0-9]+ [0-9]+ [0-9]+ [0-9]+")
_TRIE_LEAF = re.compile(r" +\|-- ([0-9.]+)")
_TRIE_ROUTE = re.compile(r" +/([0-9]+) (\S+) (type [0-9]+|[A-Z]+)(?: tos=[0-9]+)?")
_HEX_V6 = re.compile(r"[0-9a-f]{32}")
_RTF_LOCAL = 0x80000000
Address = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]


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


def listener_uids(text: str, port: int, ipv6: bool, allowed: Optional[frozenset] = None) -> list[int]:
    """Uids of LISTEN sockets on ``port`` bound to an address in ``allowed``.

    ``allowed`` defaults to what loopback connections can reach. Any line that
    does not parse fails the whole file: a check that cannot read the table
    must not report "none".
    """
    lines = text.splitlines()
    if not lines or not lines[0].split() or lines[0].split()[0] != "sl":
        raise ProcNetError("header")
    if allowed is None:
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


def private_address(text: str) -> Optional[Address]:
    """The address ``--address`` names, or None unless it is a private added site's host."""
    if not isinstance(text, str):
        return None
    if _CANONICAL_V4.fullmatch(text):
        try:
            address = ipaddress.IPv4Address(text)
        except ValueError:
            return None
        return address if any(address in network for network in _PRIVATE_V4) else None
    bracket = _BRACKETED_V6.fullmatch(text)
    if bracket is None:
        return None
    try:
        address6 = ipaddress.IPv6Address(bracket.group(1))
    except ValueError:
        return None
    # fc00::/7 has no IPv4-mapped form, so ipaddress's text is the WHATWG one here.
    if address6.compressed != bracket.group(1) or address6 not in _PRIVATE_V6 or address6 in _METADATA_V6:
        return None
    return address6


def local_ipv4_networks(text: str) -> list[ipaddress.IPv4Network]:
    """Every LOCAL route of /proc/net/fib_trie (all tables): addresses this computer answers on.

    A line of another shape, or a route line before any leaf, fails the whole
    file; so does a table without a single LOCAL route (127.0.0.1 always is one).
    """
    networks: list[ipaddress.IPv4Network] = []
    leaf: Optional[ipaddress.IPv4Address] = None
    for line in text.splitlines():
        if line == "" or _TRIE_TABLE.fullmatch(line) or _TRIE_NODE.fullmatch(line):
            leaf = None  # A route line belongs to the leaf right above it.
            continue
        found = _TRIE_LEAF.fullmatch(line)
        if found:
            leaf = ipaddress.IPv4Address(found.group(1))
            continue
        route = _TRIE_ROUTE.fullmatch(line)
        if route is None or leaf is None or not 0 <= int(route.group(1)) <= 32:
            raise ProcNetError("fib_trie")
        if route.group(3) == "LOCAL":
            networks.append(ipaddress.IPv4Network(f"{leaf}/{route.group(1)}", strict=False))
    if not networks:
        raise ProcNetError("fib_trie without LOCAL routes")
    return networks


def local_ipv6_networks(if_inet6: str, ipv6_route: str) -> list[ipaddress.IPv6Network]:
    """This computer's IPv6 addresses (if_inet6) and RTF_LOCAL routes (ipv6_route), in network order."""
    networks = []
    for line in if_inet6.splitlines():
        fields = line.split()
        if not fields:
            continue
        if len(fields) != 6 or not _HEX_V6.fullmatch(fields[0]):
            raise ProcNetError("if_inet6")
        networks.append(ipaddress.IPv6Network((int(fields[0], 16), 128)))
    for line in ipv6_route.splitlines():
        fields = line.split()
        if not fields:
            continue
        if len(fields) != 10 or not _HEX_V6.fullmatch(fields[0]) or len(fields[1]) != 2 or len(fields[8]) != 8:
            raise ProcNetError("ipv6_route")
        length, flags = int(fields[1], 16), int(fields[8], 16)
        if length > 128:
            raise ProcNetError("ipv6_route prefix")
        if flags & _RTF_LOCAL:
            networks.append(ipaddress.IPv6Network((int(fields[0], 16), length), strict=False))
    return networks


def _is_local(address: Address, proc_net: Path) -> bool:
    if isinstance(address, ipaddress.IPv4Address):
        return any(address in network
                   for network in local_ipv4_networks((proc_net / "fib_trie").read_text(encoding="ascii")))
    networks = local_ipv6_networks((proc_net / "if_inet6").read_text(encoding="ascii"),
                                   (proc_net / "ipv6_route").read_text(encoding="ascii"))
    return any(address in network for network in networks)


def _bind_addresses(address: Address) -> tuple[frozenset, frozenset]:
    """(IPv4, IPv6) bind addresses a connection to ``address`` on this computer can reach."""
    if isinstance(address, ipaddress.IPv4Address):
        mapped = ipaddress.IPv6Address("::ffff:" + str(address))
        return (frozenset({address, ipaddress.IPv4Address("0.0.0.0")}),
                frozenset({ipaddress.IPv6Address("::"), mapped, ipaddress.IPv6Address("::ffff:0.0.0.0")}))
    return frozenset(), frozenset({address, ipaddress.IPv6Address("::")})


def run(port: int, proc_net: Path | None = None, address: Optional[str] = None) -> dict[str, object]:
    """One reply object; any doubt is ``unreadable`` (the plasmoid fails closed).

    Without ``address``: listeners loopback connections can reach. With it (a
    private added site's host, see private_address): ``remote`` when it isn't
    this computer's, else the owner of the listeners on it and on the wildcard.
    """
    proc_net = PROC_NET if proc_net is None else proc_net
    if not isinstance(port, int) or isinstance(port, bool) or not MIN_PORT <= port <= MAX_PORT:
        return {"ok": False, "error": "unreadable"}
    target = None
    if address is not None:
        target = private_address(address)
        if target is None:
            return {"ok": False, "error": "unreadable"}
    try:
        allowed_v4, allowed_v6 = (None, None) if target is None else _bind_addresses(target)
        if target is not None and not _is_local(target, proc_net):
            return {"ok": True, "owner": "remote"}
        uids = listener_uids((proc_net / "tcp").read_text(encoding="ascii"), port, ipv6=False, allowed=allowed_v4)
        try:
            tcp6 = (proc_net / "tcp6").read_text(encoding="ascii")
        except FileNotFoundError:
            # No IPv6 in this kernel (ipv6.disable=1): no IPv6 socket can exist.
            tcp6 = None
        if tcp6 is not None:
            uids += listener_uids(tcp6, port, ipv6=True, allowed=allowed_v6)
        own_uid = os.getuid()
        owner = classify(uids, own_uid, trusted_uids(own_uid))
    except (OSError, ValueError):
        return {"ok": False, "error": "unreadable"}
    return {"ok": True, "owner": owner}
