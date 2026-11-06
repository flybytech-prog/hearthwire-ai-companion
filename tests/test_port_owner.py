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


@pytest.mark.parametrize("port", ["1", "65535", "08080"])
def test_cli_accepts_ports_in_range(monkeypatch, capsys, port):
    seen = []
    monkeypatch.setattr(portowner, "run", lambda value: seen.append(value) or {"ok": True, "owner": "none"})
    _cli(["--port-owner", port], capsys)
    assert seen == [int(port)]


@pytest.mark.parametrize(
    "port",
    ["0", "65536", "70000", "abc", "-1", "+80", "", " 80", "80 ", "1_000", "011434", "0x2caa", "8e3",
     "٣٣"],
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
