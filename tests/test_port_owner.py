"""``hearthwire --port-owner N``: who listens on the Ollama port (docs/provider-contracts.md).

All tables are sanitized /proc/net text written into ``tmp_path``; the real
/proc is never read. Addresses are the kernel's little-endian word format.
"""

import json
import pwd
from types import SimpleNamespace

import pytest

from hearthwire import cli
from hearthwire.core import portowner


SELF = 1000
OLLAMA = 952
OTHER = 1001
PORT = 11434  # 0x2CAA

TCP_HEADER = (
    "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
)
TCP6_HEADER = (
    "  sl  local_address                         remote_address                        st tx_queue "
    "rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
)
V4 = {
    "127.0.0.1": "0100007F",
    "0.0.0.0": "00000000",
    "127.0.0.2": "0200007F",
    "192.168.1.5": "0501A8C0",
}
V6 = {
    "::": "00000000000000000000000000000000",
    "::1": "00000000000000000000000001000000",
    "::ffff:127.0.0.1": "0000000000000000FFFF00000100007F",
    "::ffff:0.0.0.0": "0000000000000000FFFF000000000000",
    "::ffff:192.168.1.5": "0000000000000000FFFF00000501A8C0",
    "fe80::1": "000080FE000000000000000001000000",
}


def _line(index, local, port, state, uid, remote):
    return (
        f"  {index:>2}: {local}:{port:04X} {remote}:0000 {state} 00000000:00000000 00:00000000 "
        f"00000000 {uid:>5}        0 {40000 + index} 1 0000000000000000 100 0 0 10 0\n"
    )


def tcp(*sockets):
    """sockets: (address, port, state, uid)."""
    return TCP_HEADER + "".join(
        _line(index, V4[address], port, state, uid, "00000000")
        for index, (address, port, state, uid) in enumerate(sockets)
    )


def tcp6(*sockets):
    return TCP6_HEADER + "".join(
        _line(index, V6[address], port, state, uid, "0" * 32)
        for index, (address, port, state, uid) in enumerate(sockets)
    )


@pytest.fixture
def proc(tmp_path, monkeypatch):
    """Write fake tables; the session is uid SELF and the ollama account exists."""
    monkeypatch.setattr(portowner, "_BYTE_ORDER", "little")
    monkeypatch.setattr(portowner.os, "getuid", lambda: SELF)
    monkeypatch.setattr(portowner, "PROC_NET", tmp_path)
    users = {"ollama": OLLAMA}

    def getpwnam(name):
        if name not in users:
            raise KeyError(name)
        return SimpleNamespace(pw_uid=users[name])

    monkeypatch.setattr(pwd, "getpwnam", getpwnam)

    def write(v4=None, v6=None):
        (tmp_path / "tcp").write_text(tcp() if v4 is None else v4, encoding="ascii")
        (tmp_path / "tcp6").write_text(tcp6() if v6 is None else v6, encoding="ascii")
        return tmp_path

    write.users = users
    write.path = tmp_path
    return write


def owner(port=PORT):
    reply = portowner.run(port)
    assert reply["ok"] is True, reply
    return reply["owner"]


# --- owners --------------------------------------------------------------------


def test_no_listener_is_none(proc):
    proc()
    assert owner() == "none"


def test_own_listener_is_self(proc):
    proc(tcp(("127.0.0.1", PORT, "0A", SELF)))
    assert owner() == "self"


@pytest.mark.parametrize("uid", [OLLAMA, 0])
def test_ollama_account_or_root_is_system(proc, uid):
    proc(tcp(("127.0.0.1", PORT, "0A", uid)))
    assert owner() == "system"


def test_another_user_is_other(proc):
    proc(tcp(("127.0.0.1", PORT, "0A", OTHER)))
    assert owner() == "other"


def test_self_and_system_together_is_system(proc):
    proc(tcp(("127.0.0.1", PORT, "0A", SELF)), tcp6(("::1", PORT, "0A", OLLAMA)))
    assert owner() == "system"


@pytest.mark.parametrize("trusted", [SELF, OLLAMA, 0])
def test_any_untrusted_listener_makes_it_other(proc, trusted):
    # A second listener (SO_REUSEPORT, or v4 plus v6) by anyone else wins.
    proc(tcp(("127.0.0.1", PORT, "0A", trusted)), tcp6(("::", PORT, "0A", OTHER)))
    assert owner() == "other"


def test_missing_ollama_account_is_not_trusted(proc):
    del proc.users["ollama"]
    proc(tcp(("127.0.0.1", PORT, "0A", OLLAMA)))
    assert owner() == "other"
    proc(tcp(("127.0.0.1", PORT, "0A", 0)))
    assert owner() == "system"


def test_mixed_table_like_this_machine(proc):
    # Other users' listeners on other ports, connections on the port itself
    # (state 01/06), and the real server.
    proc(
        tcp(
            ("127.0.0.1", 631, "0A", 0),
            ("127.0.0.1", 34525, "0A", 954),
            ("127.0.0.1", PORT, "0A", OLLAMA),
            ("127.0.0.1", PORT, "01", OTHER),
            ("127.0.0.1", PORT, "06", OTHER),
            ("0.0.0.0", 22, "0A", 0),
        ),
        tcp6(("::", 5355, "0A", 974), ("::1", 631, "0A", 0)),
    )
    assert owner() == "system"


# --- which sockets count -------------------------------------------------------


@pytest.mark.parametrize("address", ["127.0.0.1", "0.0.0.0"])
def test_ipv4_loopback_and_wildcard_listeners_count(proc, address):
    proc(tcp((address, PORT, "0A", OTHER)))
    assert owner() == "other"


@pytest.mark.parametrize("address", ["::1", "::", "::ffff:127.0.0.1", "::ffff:0.0.0.0"])
def test_ipv6_loopback_wildcard_and_v4_mapped_listeners_count(proc, address):
    proc(v6=tcp6((address, PORT, "0A", OTHER)))
    assert owner() == "other"


def test_non_loopback_bind_addresses_are_ignored(proc):
    proc(
        tcp(("127.0.0.2", PORT, "0A", OTHER), ("192.168.1.5", PORT, "0A", OTHER)),
        tcp6(("fe80::1", PORT, "0A", OTHER), ("::ffff:192.168.1.5", PORT, "0A", OTHER)),
    )
    assert owner() == "none"


@pytest.mark.parametrize("state", ["01", "02", "06", "07", "08"])
def test_only_listen_state_counts(proc, state):
    proc(tcp(("127.0.0.1", PORT, state, OTHER)))
    assert owner() == "none"


def test_other_ports_are_ignored(proc):
    proc(tcp(("127.0.0.1", PORT + 1, "0A", OTHER), ("127.0.0.1", PORT - 1, "0A", OTHER)))
    assert owner() == "none"
    assert owner(PORT + 1) == "other"


def test_lowercase_state_and_hex_parse(proc):
    proc(tcp(("127.0.0.1", PORT, "0A", OTHER)).replace(" 0A ", " 0a ").replace(":2CAA", ":2caa"))
    assert owner() == "other"


def test_big_endian_hosts_print_addresses_in_network_order(proc, monkeypatch):
    monkeypatch.setattr(portowner, "_BYTE_ORDER", "big")
    proc(tcp(("127.0.0.1", PORT, "0A", OTHER)).replace("0100007F:", "7F000001:"))
    assert owner() == "other"


def test_missing_tcp6_means_no_ipv6_sockets(proc):
    proc(tcp(("127.0.0.1", PORT, "0A", OLLAMA)))
    (proc.path / "tcp6").unlink()
    assert owner() == "system"


# --- fail closed ---------------------------------------------------------------


UNREADABLE = {"ok": False, "error": "unreadable"}


def test_missing_tcp_is_unreadable(proc):
    proc()
    (proc.path / "tcp").unlink()
    assert portowner.run(PORT) == UNREADABLE


@pytest.mark.parametrize("name", ["tcp", "tcp6"])
def test_unreadable_file_is_unreadable(proc, monkeypatch, name):
    proc()
    real = type(proc.path).read_text

    def read_text(self, *args, **kwargs):
        if self.name == name:
            raise PermissionError(13, "denied")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(type(proc.path), "read_text", read_text)
    assert portowner.run(PORT) == UNREADABLE


@pytest.mark.parametrize(
    "table",
    [
        "",
        "\n",
        "garbage\n",
        TCP_HEADER + "   0: 0100007F:2CAA 00000000:0000 0A\n",
        TCP_HEADER + tcp(("127.0.0.1", PORT, "0A", OTHER))[len(TCP_HEADER):].replace("0100007F", "100007F"),
        TCP_HEADER + tcp(("127.0.0.1", PORT, "0A", OTHER))[len(TCP_HEADER):].replace(":2CAA", ":2CAAA"),
        TCP_HEADER + tcp(("127.0.0.1", PORT, "0A", OTHER))[len(TCP_HEADER):].replace("0100007F", "0100007G"),
        TCP_HEADER + tcp(("127.0.0.1", PORT, "0A", OTHER))[len(TCP_HEADER):].replace(f" {OTHER} ", " ollama "),
        TCP_HEADER + tcp(("127.0.0.1", PORT, "0A", OTHER))[len(TCP_HEADER):].replace(f" {OTHER} ", " -1 "),
        TCP_HEADER + tcp(("127.0.0.1", PORT, "0A", OTHER))[len(TCP_HEADER):].replace(" 0A ", " LISTEN "),
    ],
    ids=["empty", "blank", "no-header", "short-line", "short-address", "long-port", "bad-hex",
         "named-uid", "negative-uid", "bad-state"],
)
def test_malformed_tcp_is_unreadable_not_none(proc, table):
    proc(table)
    assert portowner.run(PORT) == UNREADABLE


def test_ipv4_width_address_in_tcp6_is_unreadable(proc):
    proc(v6=TCP6_HEADER + _line(0, "0100007F", PORT, "0A", OTHER, "0" * 32))
    assert portowner.run(PORT) == UNREADABLE


def test_non_ascii_table_is_unreadable(proc):
    proc()
    (proc.path / "tcp").write_bytes(TCP_HEADER.encode() + "  0: é\n".encode())
    assert portowner.run(PORT) == UNREADABLE


@pytest.mark.parametrize("port", [0, 65536, -1, True, "11434", 11434.0, None])
def test_run_rejects_ports_outside_the_range(proc, port):
    proc(tcp(("127.0.0.1", 1, "0A", SELF)))
    assert portowner.run(port) == UNREADABLE


# --- command line --------------------------------------------------------------


def _cli(argv, capsys):
    assert cli.main(argv) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    return captured.out


@pytest.mark.parametrize(
    ("v4", "expected"),
    [
        (tcp(), "none"),
        (tcp(("127.0.0.1", PORT, "0A", SELF)), "self"),
        (tcp(("127.0.0.1", PORT, "0A", OLLAMA)), "system"),
        (tcp(("0.0.0.0", PORT, "0A", OTHER)), "other"),
    ],
)
def test_cli_prints_exactly_one_owner_object(proc, capsys, v4, expected):
    proc(v4)
    out = _cli(["--port-owner", str(PORT)], capsys)
    assert out == json.dumps({"ok": True, "owner": expected}, separators=(",", ":")) + "\n"
    assert out.count("\n") == 1
    # Only the word: no uid, user name, inode, address or path.
    for leak in (str(SELF), str(OLLAMA), str(OTHER), "ollama", "4000", "0100007F", "127.0.0.1",
                 str(proc.path), "/proc"):
        assert leak not in out


def test_cli_unreadable_reply_names_no_path(proc, capsys):
    proc()
    (proc.path / "tcp").unlink()
    out = _cli([f"--port-owner={PORT}"], capsys)
    assert json.loads(out) == UNREADABLE
    assert str(proc.path) not in out and "tcp" not in out


def test_cli_turns_any_surprise_into_unreadable(monkeypatch, capsys):
    def boom(port):
        raise RuntimeError("secret /proc/net/tcp detail")

    monkeypatch.setattr(portowner, "run", boom)
    out = _cli(["--port-owner", "1"], capsys)
    assert json.loads(out) == UNREADABLE


@pytest.mark.parametrize("port", ["1", "80", "8080", "11434", "65535"])
def test_cli_accepts_ports_in_range(monkeypatch, capsys, port):
    seen = []
    monkeypatch.setattr(portowner, "run", lambda value: seen.append(value) or {"ok": True, "owner": "none"})
    _cli(["--port-owner", port], capsys)
    assert seen == [int(port)]


@pytest.mark.parametrize(
    "port",
    ["0", "65536", "70000", "abc", "-1", "+80", "", " 80", "80 ", "1_000", "011434", "0x2caa", "8e3",
     "٣٣", "08080", "080", "00080", "00", "01"],
)
def test_cli_rejects_bad_ports_with_exit_2(monkeypatch, capsys, port):
    monkeypatch.setattr(portowner, "run", lambda value: pytest.fail("must not run"))
    with pytest.raises(SystemExit) as raised:
        cli.main(["--port-owner", port])
    assert raised.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage:" in captured.err


@pytest.mark.parametrize(
    "extra",
    [
        ["--json"], ["--providers=claude"], ["--catalog"], ["--detect"],
        ["--vault", "status"], ["--web-data", "purge"],
        ["--web-data", "prepare", "--store", "encrypted", "--applet", "1", "--generation", "0"],
        ["--store", "encrypted"], ["--applet", "1"], ["--generation", "0"], ["--keep", "0"],
    ],
)
def test_cli_port_owner_stands_alone(monkeypatch, capsys, extra):
    monkeypatch.setattr(portowner, "run", lambda value: pytest.fail("must not run"))
    monkeypatch.setattr(cli, "collect_snapshot", lambda **kwargs: pytest.fail("must not collect"))
    for argv in (["--port-owner", "11434", *extra], [*extra, "--port-owner", "11434"]):
        with pytest.raises(SystemExit) as raised:
            cli.main(argv)
        assert raised.value.code == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "--port-owner" in captured.err


@pytest.mark.parametrize("argv", [["--port-owner", "11434", "--port-owner", "11434"],
                                  ["--port-owner", "11434", "--port-owner", "8080"],
                                  ["--port-owner", "11434", "--port", "8080"]])
def test_cli_refuses_a_repeated_port_owner(monkeypatch, capsys, argv):
    monkeypatch.setattr(portowner, "run", lambda value: pytest.fail("must not run"))
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--port-owner may be given only once" in captured.err


# --- --address: a home-network address of an added site (006 round 2, SEC LOW-2) ---------------
#
# Fake /proc/net/fib_trie, if_inet6 and ipv6_route in tmp_path, in the kernel's
# own layout (net/ipv4/fib_trie.c, net/ipv6/addrconf.c, net/ipv6/route.c).

import ipaddress  # noqa: E402

LAN = "192.168.1.20"
LAN6 = "fd00::20"
HTTP = 3000


def kernel_hex(address):
    """An address as /proc/net/tcp{,6} prints it: 32-bit words in host (here little-endian) order."""
    packed = ipaddress.ip_address(address).packed
    return "".join(f"{int.from_bytes(packed[at:at + 4], 'little'):08X}" for at in range(0, len(packed), 4))


def tcp_at(*sockets):
    """sockets: (address, port, state, uid), any IPv4 address."""
    return TCP_HEADER + "".join(_line(index, kernel_hex(address), port, state, uid, "00000000")
                                for index, (address, port, state, uid) in enumerate(sockets))


def tcp6_at(*sockets):
    return TCP6_HEADER + "".join(_line(index, kernel_hex(address), port, state, uid, "0" * 32)
                                 for index, (address, port, state, uid) in enumerate(sockets))


def fib_trie(*local, extra=""):
    """A Main and a Local table with 127.0.0.1 and each (address, prefix) of ``local`` as LOCAL."""
    leaves = "".join(f"        |-- {address}\n           /{prefix} host LOCAL\n" for address, prefix in local)
    table = ("  +-- 0.0.0.0/0 3 0 5\n"
             "     |-- 0.0.0.0\n        /0 universe UNICAST\n"
             "     +-- 127.0.0.0/8 2 0 2\n"
             "        +-- 127.0.0.0/31 1 0 0\n"
             "           |-- 127.0.0.0\n              /8 host LOCAL\n"
             "           |-- 127.0.0.1\n              /32 host LOCAL\n"
             "        |-- 127.255.255.255\n           /32 link BROADCAST\n"
             "     +-- 192.168.1.0/24 2 0 2\n"
             "        |-- 192.168.1.0\n           /24 link UNICAST\n"
             "        |-- 192.168.1.255\n           /32 link BROADCAST\n" + leaves + extra)
    return "Main:\n" + table + "Local:\n" + table


def if_inet6(*addresses):
    rows = ["00000000000000000000000000000001 01 80 10 80       lo"]
    rows += [f"{ipaddress.IPv6Address(address).exploded.replace(':', '')} 02 40 00 80     eth0" for address in addresses]
    return "\n".join(rows) + "\n"


def ipv6_route(*routes):
    """routes: (network, flags); always the loopback local route."""
    rows = []
    for network, flags in (("::1/128", 0x80200001), *routes):
        net = ipaddress.IPv6Network(network)
        rows.append(f"{net.network_address.exploded.replace(':', '')} {net.prefixlen:02x} {'0' * 32} 00 {'0' * 32} "
                    f"00000000 00000002 00000000 {flags:08x}     eth0")
    return "\n".join(rows) + "\n"


@pytest.fixture
def lan(proc):
    """proc plus the address tables: by default this computer has none of the LAN addresses."""

    def write(v4=None, v6=None, trie=None, inet6=None, route6=None):
        path = proc(tcp_at() if v4 is None else v4, tcp6_at() if v6 is None else v6)
        (path / "fib_trie").write_text(fib_trie() if trie is None else trie, encoding="ascii")
        (path / "if_inet6").write_text(if_inet6() if inet6 is None else inet6, encoding="ascii")
        (path / "ipv6_route").write_text(ipv6_route() if route6 is None else route6, encoding="ascii")
        return path

    write.path = proc.path
    return write


def owner_at(address, port=HTTP):
    reply = portowner.run(port, address=address)
    assert reply["ok"] is True, reply
    return reply["owner"]


@pytest.mark.parametrize("text", ["192.168.1.20", "10.0.0.0", "10.255.255.255", "172.16.0.1", "172.31.255.255",
                                  "192.168.0.0", "[fd00::20]", "[fc00::]", "[fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff]",
                                  "[fd00:ec1::1]", "[fd00:ec3::1]"])
def test_private_addresses_are_accepted(text):
    assert portowner.private_address(text) is not None


@pytest.mark.parametrize("text", [
    "", "localhost", "127.0.0.1", "0.0.0.0", "8.8.8.8", "100.64.0.1", "169.254.169.254", "172.15.255.255",
    "172.32.0.0", "192.169.0.1", "192.168.1.020", "192.168.01.1", "192.168.1", "192.168.1.20.", "0xc0.168.1.20",
    "3232235796", " 192.168.1.20", "192.168.1.20 ", "192.168.1.256", "192.168.1.20:3000", "[192.168.1.20]",
    "fd00::20", "[FD00::20]", "[fd00:0::20]", "[fd00::0:20]", "[fd00:ec2::254]", "[fd00:ec2::]", "[fe80::1]",
    "[::1]", "[::]", "[2001:db8::1]", "[::ffff:192.168.1.20]", "[::ffff:c0a8:114]", "[fd00::20%25eth0]",
    "[fd00::20]:3000", "[[fd00::20]]", "[fd00::1::2]", "[fd000::1]", "nas.local", "-1", None, 3232235796,
])
def test_other_addresses_are_refused(text):
    assert portowner.private_address(text) is None


def test_an_address_of_another_machine_is_remote(lan):
    # Another user's wildcard listener can't answer a connection that leaves the machine.
    lan(tcp_at(("0.0.0.0", HTTP, "0A", OTHER), (LAN, HTTP, "0A", OTHER)), tcp6_at(("::", HTTP, "0A", OTHER)))
    assert owner_at(LAN) == "remote"
    assert owner_at(f"[{LAN6}]") == "remote"


def test_a_nonlocal_bind_never_makes_an_address_local(lan):
    """With net.ipv4.ip_nonlocal_bind a user can bind any address; only the route tables count."""
    lan(tcp_at((LAN, HTTP, "0A", OTHER)), tcp6_at((LAN6, HTTP, "0A", OTHER)))
    assert owner_at(LAN) == "remote" and owner_at(f"[{LAN6}]") == "remote"


@pytest.mark.parametrize(("bound", "table"), [
    (LAN, "tcp"), ("0.0.0.0", "tcp"), ("::", "tcp6"), (f"::ffff:{LAN}", "tcp6"), ("::ffff:0.0.0.0", "tcp6"),
])
def test_an_own_ipv4_address_counts_its_listeners_and_the_wildcards(lan, bound, table):
    sockets = ((bound, HTTP, "0A", OTHER),)
    lan(tcp_at(*sockets) if table == "tcp" else None, tcp6_at(*sockets) if table == "tcp6" else None,
        trie=fib_trie((LAN, 32)))
    assert owner_at(LAN) == "other"


@pytest.mark.parametrize(("uid", "expected"), [(SELF, "self"), (OLLAMA, "system"), (0, "system")])
def test_an_own_address_has_the_usual_owners(lan, uid, expected):
    lan(tcp_at((LAN, HTTP, "0A", uid)), tcp6_at((LAN6, HTTP, "0A", uid)), trie=fib_trie((LAN, 32)),
        inet6=if_inet6(LAN6))
    assert owner_at(LAN) == expected
    assert owner_at(f"[{LAN6}]") == expected


def test_listeners_on_other_addresses_or_ports_do_not_count(lan):
    lan(tcp_at(("127.0.0.1", HTTP, "0A", OTHER), ("192.168.1.21", HTTP, "0A", OTHER), (LAN, HTTP + 1, "0A", OTHER),
               (LAN, HTTP, "01", OTHER)),
        tcp6_at(("::1", HTTP, "0A", OTHER), ("fd00::21", HTTP, "0A", OTHER), ("::ffff:192.168.1.21", HTTP, "0A", OTHER)),
        trie=fib_trie((LAN, 32)), inet6=if_inet6(LAN6))
    assert owner_at(LAN) == "none"
    assert owner_at(f"[{LAN6}]") == "none"


def test_an_ipv6_address_ignores_ipv4_listeners(lan):
    lan(tcp_at(("0.0.0.0", HTTP, "0A", OTHER)), tcp6_at(("::", HTTP, "0A", SELF)), inet6=if_inet6(LAN6))
    assert owner_at(f"[{LAN6}]") == "self"


def test_a_local_range_makes_every_address_in_it_local(lan):
    """`ip route add local 192.168.1.0/24 dev lo` (AnyIP): the whole range is this computer."""
    lan(tcp_at(("0.0.0.0", HTTP, "0A", OTHER)), trie=fib_trie(("192.168.1.0", 24)))
    assert owner_at(LAN) == "other"
    assert owner_at("192.168.2.20") == "remote"


@pytest.mark.parametrize("route", [" link UNICAST", " link BROADCAST", " universe UNICAST", " host type 12"])
def test_only_local_routes_count(lan, route):
    trie = fib_trie(extra=f"        |-- {LAN}\n           /32{route}\n")
    lan(tcp_at(("0.0.0.0", HTTP, "0A", OTHER)), trie=trie)
    assert owner_at(LAN) == "remote"


def test_route_lines_with_tos_and_other_tables_parse(lan):
    trie = fib_trie() + "Id 100:\n  +-- 10.0.0.0/8 2 0 2\n     |-- 10.0.0.5\n        /32 host LOCAL tos=4\n"
    lan(tcp_at(("0.0.0.0", HTTP, "0A", SELF)), trie=trie)
    assert owner_at("10.0.0.5") == "self"


def test_an_ipv6_local_route_counts_and_others_do_not(lan):
    lan(v6=tcp6_at(("::", HTTP, "0A", OTHER)), route6=ipv6_route(("fd00::/64", 0x80200001), ("fd01::/64", 0x00200001)))
    assert owner_at(f"[{LAN6}]") == "other"
    assert owner_at("[fd01::20]") == "remote"


@pytest.mark.parametrize(("name", "content"), [
    ("fib_trie", None), ("fib_trie", ""), ("fib_trie", "Main:\n  +-- 0.0.0.0/0 3 0 5\n"),
    ("fib_trie", fib_trie() + "garbage\n"), ("fib_trie", "Main:\n           /32 host LOCAL\n"),
    ("fib_trie", fib_trie() + "     |-- 999.1.1.1\n        /32 host LOCAL\n"),
    ("fib_trie", fib_trie() + "     |-- 10.0.0.1\n        /33 host LOCAL\n"),
    ("fib_trie", fib_trie().replace("/8 host LOCAL", "/8 host local")),
])
def test_an_unreadable_ipv4_table_is_unreadable(lan, name, content):
    lan(tcp_at(("0.0.0.0", HTTP, "0A", SELF)))
    if content is None:
        (lan.path / name).unlink()
    else:
        (lan.path / name).write_text(content, encoding="ascii")
    assert portowner.run(HTTP, address=LAN) == UNREADABLE


@pytest.mark.parametrize(("name", "content"), [
    ("if_inet6", None), ("ipv6_route", None), ("if_inet6", "zz\n"), ("if_inet6", "0" * 32 + " 01 80 10\n"),
    ("ipv6_route", "0" * 32 + " 80 x\n"), ("ipv6_route", ipv6_route().replace(" 80 ", " 81 ", 1)),
])
def test_an_unreadable_ipv6_table_is_unreadable(lan, name, content):
    lan(v6=tcp6_at(("::", HTTP, "0A", SELF)))
    if content is None:
        (lan.path / name).unlink()
    else:
        (lan.path / name).write_text(content, encoding="ascii")
    assert portowner.run(HTTP, address=f"[{LAN6}]") == UNREADABLE


def test_a_bad_tcp_table_is_unreadable_for_an_own_address(lan):
    lan("not a table\n", trie=fib_trie((LAN, 32)))
    assert portowner.run(HTTP, address=LAN) == UNREADABLE


@pytest.mark.parametrize("address", ["8.8.8.8", "127.0.0.1", "[fd00:ec2::254]", "fd00::20", ""])
def test_run_refuses_an_address_that_is_not_private(lan, address):
    lan()
    assert portowner.run(HTTP, address=address) == UNREADABLE


def test_the_loopback_check_is_unchanged_without_an_address(lan):
    lan(tcp_at((LAN, HTTP, "0A", OTHER), ("127.0.0.1", HTTP, "0A", SELF)), trie=fib_trie((LAN, 32)))
    assert portowner.run(HTTP) == {"ok": True, "owner": "self"}


def test_cli_passes_the_address_and_prints_only_the_word(lan, capsys):
    lan(tcp_at(("0.0.0.0", HTTP, "0A", OTHER)), trie=fib_trie((LAN, 32)))
    out = _cli(["--port-owner", str(HTTP), "--address", LAN], capsys)
    assert out == '{"ok":true,"owner":"other"}\n'
    out = _cli(["--address", f"[{LAN6}]", "--port-owner", str(HTTP)], capsys)
    assert out == '{"ok":true,"owner":"remote"}\n'
    for leak in (LAN, LAN6, str(OTHER), str(lan.path), "fib_trie", "/proc"):
        assert leak not in out


def test_cli_without_an_address_calls_the_loopback_check(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(portowner, "run", lambda *args, **kwargs: seen.append((args, kwargs)) or {"ok": True, "owner": "none"})
    _cli(["--port-owner", "3000"], capsys)
    _cli(["--port-owner", "3000", "--address", LAN], capsys)
    assert seen == [((3000,), {}), ((3000,), {"address": LAN})]


@pytest.mark.parametrize("argv", [
    ["--address", LAN], ["--address", LAN, "--json"], ["--address", LAN, "--install-info"],
    ["--port-owner", "3000", "--address", LAN, "--address", LAN],
    ["--port-owner", "3000", "--address", "8.8.8.8"], ["--port-owner", "3000", "--address", "fd00::20"],
    ["--port-owner", "3000", "--address", "[FD00::20]"], ["--port-owner", "3000", "--address", "127.0.0.1"],
    ["--port-owner", "3000", "--address", "[fd00:ec2::254]"], ["--port-owner", "3000", "--address", "192.168.1.020"],
    ["--port-owner", "3000", "--address", ""], ["--port-owner", "3000", "--address"],
])
def test_cli_refuses_a_bad_address_with_exit_2(monkeypatch, capsys, argv):
    monkeypatch.setattr(portowner, "run", lambda *args, **kwargs: pytest.fail("must not run"))
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage:" in captured.err


def test_cli_turns_any_surprise_with_an_address_into_unreadable(monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise RuntimeError("secret /proc/net/fib_trie detail 192.168.1.20")

    monkeypatch.setattr(portowner, "run", boom)
    out = _cli(["--port-owner", "3000", "--address", LAN], capsys)
    assert json.loads(out) == UNREADABLE and LAN not in out


# --- the widget's own command through a real shell (006 round 2, phase 2b) ------------------------
#
# OllamaChat.ownerCommand (run in qmltestrunner) builds the string the widget's
# DataSource hands to `sh -c`. Here it goes through /bin/sh under a bare
# environment, in a folder of one-letter files that `[fd00::20]` would glob to
# if it weren't quoted. On PATH, `python3` is a shim that records its argv and
# runs the real hearthwire.cli against a fake /proc/net.

import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "plasmoid" / "contents" / "ui"
COMMAND_QML = """import QtQuick
import QtTest
import "OllamaChat.js" as OllamaChat

TestCase {
    name: "OwnerCommand"
    function test_dump() {
        console.log("COMMANDS " + JSON.stringify([
            OllamaChat.ownerCommand(3000, 7, 2, "[fd00::20]"),
            OllamaChat.ownerCommand(3000, 7, 2, "192.168.1.20"),
            OllamaChat.ownerCommand(11434, 7, 2),
            OllamaChat.ownerCommand(3000, 7, 2, "[fd00::20]';id;'")
        ]))
    }
}
"""
SHIM = """#!{python}
import json, os, sys
from pathlib import Path
with open(os.environ["HW_ARGV_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({{"argv": sys.argv[1:], "run": os.environ.get("HEARTHWIRE_RUN"),
                          "applet": os.environ.get("HEARTHWIRE_APPLET")}}) + "\\n")
if sys.argv[1:4] != ["-P", "-m", "hearthwire"]:
    sys.exit(97)
sys.path.insert(0, os.environ["HW_SRC"])
from hearthwire import cli
from hearthwire.core import portowner
portowner.PROC_NET = Path(os.environ["HW_FAKE_PROC"])
portowner._BYTE_ORDER = "little"
sys.exit(cli.main(sys.argv[4:]))
"""


def widget_commands(tmp_path):
    runner = shutil.which("qmltestrunner", path="/usr/lib/qt6/bin:/usr/bin:/bin")
    if runner is None:
        pytest.skip("qmltestrunner is not installed")
    folder = tmp_path / "qml"
    folder.mkdir()
    for script in UI.glob("*.js"):
        shutil.copy2(script, folder / script.name)
    (folder / "tst_command.qml").write_text(COMMAND_QML, encoding="utf-8")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(folder), "LANG": "C.UTF-8", "QT_QPA_PLATFORM": "offscreen",
           "XDG_RUNTIME_DIR": str(folder), "TMPDIR": str(folder)}
    done = subprocess.run([runner, "-input", str(folder / "tst_command.qml")], env=env, cwd=folder,
                          capture_output=True, text=True, timeout=120, check=False)
    output = done.stdout + done.stderr
    if "module \"QtTest\" is not installed" in output:
        pytest.skip("QtTest is not installed")
    found = re.search(r"COMMANDS (\[.*\])", output)
    assert found, output[-3000:]
    return json.loads(found.group(1))


@pytest.fixture
def shell(tmp_path):
    """Runs a command string with /bin/sh -c the way Plasma5Support's executable engine does."""
    bin_dir, proc_dir, work = tmp_path / "bin", tmp_path / "proc-net", tmp_path / "work"
    for folder in (bin_dir, proc_dir, work):
        folder.mkdir()
    shim = bin_dir / "python3"
    shim.write_text(SHIM.format(python=sys.executable), encoding="utf-8")
    shim.chmod(0o755)
    for bait in ("f", "d", "0", "2", ":"):  # What an unquoted [fd00::20] would glob to.
        (work / bait).write_text("", encoding="ascii")
    log = tmp_path / "argv.jsonl"
    (proc_dir / "tcp").write_text(tcp_at(("0.0.0.0", HTTP, "0A", 4242)), encoding="ascii")
    (proc_dir / "tcp6").write_text(tcp6_at(), encoding="ascii")
    (proc_dir / "fib_trie").write_text(fib_trie((LAN, 32)), encoding="ascii")
    (proc_dir / "if_inet6").write_text(if_inet6(), encoding="ascii")
    (proc_dir / "ipv6_route").write_text(ipv6_route(), encoding="ascii")

    def run(command):
        if log.exists():
            log.unlink()
        env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HW_ARGV_LOG": str(log), "HW_FAKE_PROC": str(proc_dir),
               "HW_SRC": str(ROOT / "src"), "HOME": str(work), "LANG": "C.UTF-8"}
        done = subprocess.run(["/bin/sh", "-c", command], env=env, cwd=work, capture_output=True, text=True,
                              timeout=60, check=False)
        calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
        return done, calls

    return run


def test_the_widget_command_reaches_the_helper_exactly_through_sh(shell, tmp_path):
    six, four, plain, hostile = widget_commands(tmp_path)
    assert hostile == ""  # The widget builds no command for an address with shell characters.
    assert six.endswith(" --address '[fd00::20]'")
    done, calls = shell(six)
    assert (done.returncode, done.stderr) == (0, "")
    assert calls == [{"argv": ["-P", "-m", "hearthwire", "--port-owner", "3000", "--address", "[fd00::20]"],
                      "run": "7", "applet": "2"}]
    assert done.stdout == '{"ok":true,"owner":"remote"}\n'
    # 192.168.1.20 is this (fake) computer's own address: the owner check, here another user's wildcard.
    done, calls = shell(four)
    assert calls[0]["argv"][3:] == ["--port-owner", "3000", "--address", "192.168.1.20"]
    assert done.stdout == '{"ok":true,"owner":"other"}\n'
    done, calls = shell(plain)
    assert calls[0]["argv"][3:] == ["--port-owner", "11434"]
    assert done.stdout == '{"ok":true,"owner":"none"}\n'


def test_the_glob_bait_would_catch_an_unquoted_address(shell, tmp_path):
    """Control: without the quotes the shell rewrites [fd00::20], and the helper refuses what is left."""
    six = widget_commands(tmp_path)[0]
    done, calls = shell(six.replace("'", ""))
    assert calls and calls[0]["argv"][-1] != "[fd00::20]"
    assert done.returncode == 2 and done.stdout == ""
