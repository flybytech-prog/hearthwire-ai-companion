"""Task 014: the Secret Service contract of core/secretkey.py, without any real keyring.

The stub ``secret-tool`` and ``busctl`` below are the only programs that run
(a private PATH): they keep a JSON "keyring" of dummy values under tmp_path,
answer in the formats measured in the Omarchy lab VM (R0, R0b: probe-0.md) and
log sha256 hashes, lengths and where their fds point, never a value. The
plain-keyring check reads files made under tmp_path only. The session bus is
never reachable (conftest), and no host keyring path is read.
"""

import ast
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hearthwire.core import secretkey, termination, webdata
from test_frontend import mutant

SOURCE = Path(secretkey.__file__)
COLLECTION = "/org/freedesktop/secrets/collection/Default_5fkeyring"

# secret-tool and busctl (not a format string). STUB_KEYRING is a JSON file
# {item: value}; values are dummy keys made by the stub openssl below.
KEYRING_STUB = r'''#!PYTHON
import hashlib, json, os, sys, time

tool = os.path.basename(sys.argv[0])
args = sys.argv[1:]
env = os.environ
COLLECTION = "/org/freedesktop/secrets/collection/Default_5fkeyring"


def fd_target(fd):
    try:
        return os.readlink(f"/proc/self/fd/{fd}")
    except OSError:
        return "closed"


def log(record):
    with open(env["STUB_LOG"], "a") as handle:
        handle.write(json.dumps(record) + "\n")


def keyring():
    try:
        with open(env["STUB_KEYRING"]) as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {}


def save(state):
    with open(env["STUB_KEYRING"], "w") as handle:
        json.dump(state, handle)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def note(role):
    """For the stop-signal tests: this process (pid and kernel start time)."""
    if "STUB_PIDS" not in env:
        return
    with open("/proc/self/stat") as handle:
        start = handle.read().rsplit(")", 1)[1].split()[19]
    with open(os.path.join(env["STUB_PIDS"], f"{role}-{os.getpid()}"), "w") as handle:
        handle.write(start)


def bad_bus(message):
    # R0b: a bad or missing bus is exit 1, nothing on stdout, the message on stderr only.
    if env.get("STUB_SS_BUS") == "bad":
        sys.stderr.write(message + "\n")
        log(record)
        sys.exit(1)


record = {"tool": tool, "argv": args, "fds": [fd_target(0), fd_target(1), fd_target(2)]}
code = 0
if tool == "secret-tool":
    command, item = args[0], args[-1]
    record["item"] = item
    if env.get("STUB_SS_BLOCK") == f"{command}:{item}":
        # As on the gcr prompt: waits until stopped.
        note("keyring")
        time.sleep(float(env.get("STUB_SS_SLEEP", "60")))
    bad_bus("secret-tool: Could not connect: No such file or directory")
    if command == "store":
        # R0 S2: stdin is kept exactly (a trailing LF too), an empty one is stored as well.
        data = sys.stdin.buffer.read()
        record.update(sha=sha(data), length=len(data), lf=data.endswith(b"\n"))
        code = 1 if env.get("STUB_SS_STORE_FAIL_ITEM") in (item, "*") else 0
        if code == 0:
            state = keyring()
            state[item] = data.decode("latin-1")
            save(state)
    elif command == "lookup":
        state = keyring()
        if env.get("STUB_SS_LOOKUP_FAIL_ITEM") in (item, "*") or item not in state:
            code = 1  # R0 S2: a missing item is exit 1, silent.
        else:
            value = state[item].encode("latin-1") + (b"\n" if env.get("STUB_SS_LOOKUP_LF") else b"")
            if env.get("STUB_SS_LOOKUP_EMPTY") in (item, "*"):
                value = b""  # As for an empty secret stored by someone else (R0 S2).
            sys.stdout.buffer.write(value)
            record.update(sha=sha(value[:-1] if value.endswith(b"\n") else value), length=len(value))
    elif command == "clear":
        state = keyring()
        code = 1
        if item in state and not env.get("STUB_SS_CLEAR_KEEPS"):
            del state[item]
            save(state)
            code = 0
elif tool == "busctl":
    bad_bus("Failed to connect to user scope bus via local transport: No such file or directory")
    COLLECTION = env.get("STUB_SS_COLLECTION", COLLECTION)
    if env.get("STUB_BUSCTL_BIG"):
        # A service answering with far more than the helper may read: it keeps writing until it is stopped.
        with open(env["STUB_BUSCTL_BIG"], "w") as handle:
            handle.write(str(os.getpid()))
        chunk = b"x" * 65536
        for _ in range(4000):
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
        time.sleep(30)
    time.sleep(float(env.get("STUB_BUSCTL_SLEEP", "0")))
    if "get-property" in args:
        answer = env.get("STUB_SS_LOCKED", "false")
        if answer == "fail":
            # R0 S4, no default alias.
            sys.stderr.write("Failed to get property Locked on interface org.freedesktop.Secret.Collection: "
                             "Object does not exist at path /org/freedesktop/secrets/aliases/default\n")
            code = 1
        else:
            print(env.get("STUB_SS_LOCKED_RAW", f"b {answer}"))
    elif "SearchItems" in args:
        item = args[-1]
        search = env.get("STUB_SS_SEARCH", "")
        if search == "fail":
            code = 1
        elif search == "junk":
            print("aoao 1")
        else:
            paths = [f'"{COLLECTION}/4"'] if item in keyring() else []
            # R0 S5/S6: while locked the item is listed in the second group.
            if env.get("STUB_SS_LOCKED") == "true":
                print(" ".join(["aoao", "0", str(len(paths)), *paths]))
            else:
                print(" ".join(["aoao", str(len(paths)), *paths, "0"]))
log(record)
sys.exit(code)
'''

# openssl rand -hex 32 with output variants (STUB_OPENSSL_OUTPUT: empty, short,
# long, nolf), so the empty-key and length rules can be shown.
OPENSSL_STUB = r'''#!PYTHON
import hashlib, json, os, sys

env = os.environ
value = os.urandom(32).hex().encode() + b"\n"
variant = env.get("STUB_OPENSSL_OUTPUT", "")
value = {"empty": b"", "short": value[:40] + b"\n", "long": value[:-1] + b"ab\n", "nolf": value[:-1]}.get(variant, value)
code = int(env.get("STUB_OPENSSL_EXIT", "0"))
if code == 0:
    sys.stdout.buffer.write(value)
with open(env["STUB_LOG"], "a") as handle:
    handle.write(json.dumps({"tool": "openssl", "argv": sys.argv[1:], "length": len(value),
                             "sha": hashlib.sha256(value).hexdigest(),
                             "fds": [os.readlink(f"/proc/self/fd/{fd}") for fd in (0, 1, 2)]}) + "\n")
sys.exit(code)
'''


def install_keyring_stubs(folder, *, openssl=True):
    """secret-tool and busctl (and the variant openssl) as scripts in ``folder``."""
    for name in ("secret-tool", "busctl", *(["openssl"] if openssl else [])):
        path = Path(folder) / name
        path.write_text((OPENSSL_STUB if name == "openssl" else KEYRING_STUB).replace("PYTHON", sys.executable, 1))
        path.chmod(0o755)


class Keyring:
    def __init__(self, root, monkeypatch):
        self.root = root
        self.bin = root / "bin"
        self.bin.mkdir(exist_ok=True)
        install_keyring_stubs(self.bin)
        self.log = root / "keyring.log"
        self.log.write_text("")
        self.store = root / "keyring.json"
        self.monkeypatch = monkeypatch
        monkeypatch.setenv("PATH", str(self.bin))
        monkeypatch.setenv("STUB_LOG", str(self.log))
        monkeypatch.setenv("STUB_KEYRING", str(self.store))
        self.tools, missing = secretkey.find_tools()
        assert missing == ()

    def env(self, **values):
        for key, value in values.items():
            self.monkeypatch.setenv(key, str(value))

    def calls(self, tool=None):
        records = [json.loads(line) for line in self.log.read_text().splitlines() if line]
        return [record for record in records if tool is None or record["tool"] == tool]

    def items(self):
        return json.loads(self.store.read_text()) if self.store.exists() else {}


@pytest.fixture
def keyring(tmp_path, monkeypatch):
    return Keyring(tmp_path, monkeypatch)


def pipe_bytes(descriptor):
    """The test (never the helper) reads a returned pipe: dummy keys only."""
    try:
        os.set_blocking(descriptor, False)
        return os.read(descriptor, 4096)
    finally:
        os.close(descriptor)


# --- the contract, exactly ------------------------------------------------------------------------


def test_the_argv_shapes_are_the_contract():
    tool, bus = "/usr/bin/secret-tool", "/usr/bin/busctl"
    attributes = ["application", "hearthwire", "item", "encrypted-chat-folder"]
    assert secretkey.store_argv(tool, "encrypted-chat-folder") == [
        tool, "store", "--label=Hearthwire encrypted chat folder", *attributes]
    assert secretkey.lookup_argv(tool) == [tool, "lookup", *attributes]
    assert secretkey.clear_argv(tool, "encrypted-chat-folder.new") == [
        tool, "clear", "application", "hearthwire", "item", "encrypted-chat-folder.new"]
    assert secretkey.locked_argv(bus) == [
        bus, "--user", "--timeout=2", "get-property", "org.freedesktop.secrets",
        "/org/freedesktop/secrets/aliases/default", "org.freedesktop.Secret.Collection", "Locked"]
    assert secretkey.search_argv(bus, "encrypted-chat-folder") == [
        bus, "--user", "--timeout=2", "call", "org.freedesktop.secrets", "/org/freedesktop/secrets",
        "org.freedesktop.Secret.Service", "SearchItems", "a{ss}", "2", *attributes]
    assert secretkey.keygen_argv("/usr/bin/openssl") == ["/usr/bin/openssl", "rand", "-hex", "32"]
    assert secretkey.ITEMS == ("encrypted-chat-folder", "encrypted-chat-folder.new")
    assert secretkey.SLOT_NAMES == ("secret-service.conf", "secret-service.conf.old", "secret-service.conf.new")
    assert (secretkey.TOOLS, secretkey.REPORTED) == (("secret-tool", "busctl"), ("secret-tool",))
    assert (secretkey.BUS_TIMEOUT, secretkey.PROMPT_TIMEOUT, secretkey.KEY_LENGTH) == (2, 120.0, 64)
    # None of the lookup's words starts with a dash: it is also gocryptfs's extpass.
    assert not any(word.startswith("-") for word in secretkey.lookup_argv(tool))


def argv_problems(module):
    """check_argv takes exactly the contract's shapes; is_lookup_argv only the real item's lookup."""
    tool, bus, openssl = "/usr/bin/secret-tool", "/usr/bin/busctl", "/usr/bin/openssl"
    good = {
        "keygen": module.keygen_argv(openssl),
        **{f"{shape.__name__} {item}": shape(tool, item)
           for shape in (module.store_argv, module.lookup_argv, module.clear_argv) for item in module.ITEMS},
        "locked": module.locked_argv(bus),
        **{f"search {item}": module.search_argv(bus, item) for item in module.ITEMS},
    }
    attributes = ["application", "hearthwire", "item", "encrypted-chat-folder"]
    bad = {
        "search prints secrets": [tool, "search", *attributes],
        "search --all": [tool, "search", "--all", *attributes],
        "another item": [tool, "lookup", "application", "hearthwire", "item", "other"],
        "another application": [tool, "lookup", "application", "other", "item", "encrypted-chat-folder"],
        "an extra attribute": [tool, "lookup", *attributes, "x", "y"],
        "store without the label": [tool, "store", *attributes],
        "store with another label": [tool, "store", "--label=x", *attributes],
        "the label split": [tool, "store", "--label", "Hearthwire encrypted chat folder", *attributes],
        "a relative secret-tool": ["secret-tool", "lookup", *attributes],
        "a relative busctl": ["busctl", *module.locked_argv(bus)[1:]],
        "busctl another property": [*module.locked_argv(bus)[:-1], "Label"],
        "busctl another path": [*module.locked_argv(bus)[:5], "/org/freedesktop/secrets/collection/x",
                                *module.locked_argv(bus)[6:]],
        "busctl on the system bus": [bus, "--system", *module.locked_argv(bus)[2:]],
        "busctl without a timeout": [bus, "--user", *module.locked_argv(bus)[3:]],
        "busctl a longer timeout": [bus, "--user", "--timeout=60", *module.locked_argv(bus)[3:]],
        "busctl GetSecrets": [*module.search_argv(bus, "encrypted-chat-folder")[:7], "GetSecrets", "ao", "0"],
        "busctl Unlock": [*module.search_argv(bus, "encrypted-chat-folder")[:7], "Unlock", "ao", "0"],
        "busctl SearchItems for another item": [*module.search_argv(bus, "x")],
        "openssl another size": [openssl, "rand", "-hex", "16"],
        "openssl to a file": [openssl, "rand", "-hex", "-out", "/tmp/k", "32"],
        "kwallet-query": ["/usr/bin/kwallet-query", "--folder", "Hearthwire", "--read-password",
                          "encrypted-chat-folder", "kdewallet"],
        "a shell": ["/bin/sh", "-c", "secret-tool lookup"],
        "empty": [],
    }
    problems = []
    for name, argv in good.items():
        try:
            module.check_argv(argv)
        except webdata.HelperError:
            problems.append(f"refuses {name}")
    for name, argv in bad.items():
        try:
            module.check_argv(argv)
            problems.append(f"takes {name}")
        except webdata.HelperError:
            pass
    if not module.is_lookup_argv(module.lookup_argv(tool)):
        problems.append("the extpass lookup is refused")
    for name, values in {"the staging item": module.lookup_argv(tool, module.ITEM_NEW),
                         "a store": module.store_argv(tool, module.ITEM),
                         "a relative lookup": module.lookup_argv("secret-tool"),
                         "another program": module.lookup_argv("/usr/bin/kwallet-query")}.items():
        if module.is_lookup_argv(values):
            problems.append(f"the extpass may be {name}")
    return problems


def test_check_argv_takes_only_the_contract():
    assert argv_problems(secretkey) == []


ARGV_MUTATIONS = {
    "search allowed": ("        allowed = [shape(argv[0], item) for shape in (store_argv, lookup_argv, clear_argv) for item in ITEMS]\n",
                       "        allowed = [shape(argv[0], item) for shape in (store_argv, lookup_argv, clear_argv) for item in ITEMS]\n"
                       "        allowed.append([argv[0], 'search', *attributes(ITEM)])\n"),
    "any secret-tool argv": ("    if argv not in allowed:\n", "    if tool not in (TOOL, BUSCTL, KEYGEN_TOOL):\n"),
    "relative paths": (" or not os.path.isabs(argv[0]):\n        raise HelperError(\"os-error\")\n    tool =",
                       ":\n        raise HelperError(\"os-error\")\n    tool ="),
    "the staging item as extpass": ("        and values == lookup_argv(values[0])\n",
                                    "        and values in (lookup_argv(values[0]), lookup_argv(values[0], ITEM_NEW))\n"),
    "any extpass program": (" and os.path.basename(values[0]) == TOOL\n", "\n"),
    "a longer bus timeout": ('    return [busctl, "--user", f"--timeout={BUS_TIMEOUT}"]\n',
                             '    return [busctl, "--user", f"--timeout={BUS_TIMEOUT * 30}"]\n'),
}


@pytest.mark.parametrize("name", sorted(ARGV_MUTATIONS))
def test_proof_the_argv_rule_catches(name):
    copy = mutant(secretkey, *ARGV_MUTATIONS[name])
    if name == "a longer bus timeout":
        assert copy.locked_argv("/b")[2] != "--timeout=2"  # The exact-shape test above pins the contract.
        return
    assert argv_problems(copy)


# --- busctl answers --------------------------------------------------------------------------------


@pytest.mark.parametrize(("answer", "count"), [
    # R0 S4 / S5 / S6, verbatim shapes.
    ("aoao 0 0", 0),
    (f'aoao 1 "{COLLECTION}/4" 0', 1),
    (f'aoao 0 1 "{COLLECTION}/5"', 1),  # Locked: the item is in the second group.
    (f'aoao 1 "{COLLECTION}/4" 1 "{COLLECTION}/5"', 2),
    ("aoao 0 1 \"/org/freedesktop/secrets/collection/login/1\"", 1),
    ("", None), ("aoao", None), ("aoao 1", None), ("aoao 1 0", None), ("aoao 0 0 extra", None),
    (f'aoao 2 "{COLLECTION}/4" 0', None), ('aoao 1 "/elsewhere/4" 0', None), ("ao 0", None),
    (f'aoao 1 {COLLECTION}/4 0', None), ("aoao -1 0", None),
])
def test_search_items_counts_both_groups(answer, count):
    assert secretkey._count_items(answer) == count


@pytest.mark.parametrize(("name", "path"), [
    ("Default_keyring", "Default_5fkeyring"), ("login", "login"), ("a-b.c", "a_2db_2ec"), ("_", "_5f"),
])
def test_collection_path_escapes_as_libsecret_does(name, path):
    assert secretkey.collection_path(name) == "/org/freedesktop/secrets/collection/" + path


def test_proof_an_unescaped_underscore_is_caught():
    copy = mutant(secretkey, 'char if char.isascii() and char.isalnum() else',
                  'char if char.isascii() and (char.isalnum() or char == "_") else')
    assert copy.collection_path("Default_keyring") != "/org/freedesktop/secrets/collection/Default_5fkeyring"


def test_item_paths_lists_both_groups():
    answer = f'aoao 1 "{COLLECTION}/4" 1 "{COLLECTION}/5"'
    assert secretkey._item_paths(answer) == [f"{COLLECTION}/4", f"{COLLECTION}/5"]
    assert secretkey._item_paths("junk") is None


def test_proof_counting_only_the_first_group_misses_a_locked_item():
    copy = mutant(secretkey, "        found.extend(path[1:-1] for path in paths)\n",
                  "        found.extend(path[1:-1] for path in paths if _group == 0)\n")
    assert copy._count_items(f'aoao 0 1 "{COLLECTION}/5"') == 0


@pytest.mark.parametrize(("answer", "locked"), [
    ("b true", True), ("b false", False), ("true", None), ("b maybe", None), ("", None), (None, None),
    ("b  true", None), ("b true extra", None),
])
def test_locked_takes_only_a_boolean(monkeypatch, answer, locked):
    monkeypatch.setattr(secretkey, "_query", lambda argv: answer)
    assert secretkey.collection_locked("/usr/bin/busctl") is locked


def test_queries_against_the_stub(keyring):
    bus = keyring.tools["busctl"]
    assert secretkey.collection_locked(bus) is False
    keyring.env(STUB_SS_LOCKED="true")
    assert secretkey.collection_locked(bus) is True
    keyring.env(STUB_SS_LOCKED="fail")
    assert secretkey.collection_locked(bus) is None
    assert secretkey.item_exists(bus) is False
    keyring.store.write_text(json.dumps({secretkey.ITEM: "0" * 64}))
    assert secretkey.item_exists(bus) is True
    keyring.env(STUB_SS_LOCKED="true")
    assert secretkey.item_exists(bus) is True  # Listed as locked, still there.
    assert secretkey.item_exists(bus, secretkey.ITEM_NEW) is False
    for search in ("fail", "junk"):
        keyring.env(STUB_SS_SEARCH=search)
        assert secretkey.item_exists(bus) is None
    keyring.env(STUB_SS_SEARCH="", STUB_SS_BUS="bad")
    assert secretkey.item_exists(bus) is None and secretkey.collection_locked(bus) is None
    for call in keyring.calls("busctl"):
        assert call["fds"][0] == "/dev/null" and call["fds"][2] == "/dev/null"


def test_a_slow_busctl_counts_as_no_answer(keyring, monkeypatch):
    monkeypatch.setattr(secretkey, "QUERY_TIMEOUT", 0.3)
    keyring.env(STUB_BUSCTL_SLEEP=5)
    assert secretkey.collection_locked(keyring.tools["busctl"]) is None


def test_an_oversized_busctl_answer_is_refused(keyring):
    keyring.env(STUB_SS_LOCKED_RAW="b " + "x" * 5000)
    assert secretkey.collection_locked(keyring.tools["busctl"]) is None


def _big_answer_problems(module, keyring, monkeypatch, tmp_path):
    """The stub prints 250 MB; the helper may read 4097 bytes, then stops the child's group."""
    pidfile = tmp_path / "big.pid"
    keyring.env(STUB_BUSCTL_BIG=pidfile)
    reads = []
    real = os.read

    def spy(descriptor, size):
        data = real(descriptor, size)
        reads.append(len(data))
        return data

    monkeypatch.setattr(module.os, "read", spy)
    started = time.monotonic()
    answer = module._query(module.search_argv(keyring.tools["busctl"], module.ITEM))
    problems = []
    if answer is not None:
        problems.append("an oversized answer was accepted")
    if sum(reads) > 4097:
        problems.append(f"{sum(reads)} bytes were read")
    if time.monotonic() - started > 2.5:
        problems.append("it took until the deadline")
    pid = int(pidfile.read_text())
    try:
        os.kill(pid, 0)
        problems.append("the child is still running")
    except ProcessLookupError:
        pass
    return problems


def test_a_huge_busctl_answer_is_read_only_up_to_the_cap_and_the_child_stopped(keyring, monkeypatch, tmp_path):
    assert _big_answer_problems(secretkey, keyring, monkeypatch, tmp_path) == []


@pytest.mark.parametrize(("old", "new"), [
    ("os.read(descriptor, _MAX_QUERY_OUTPUT + 1 - len(data))", "os.read(descriptor, 65536)"),
    ("        termination.stop(child, grace=0.0)\n        child.stdout.close()\n", "        child.stdout.close()\n"),
])
def test_proof_the_busctl_cap_rule_catches(keyring, monkeypatch, tmp_path, old, new):
    # The first mutant reads to the deadline: bound it so the proof stays quick.
    monkeypatch.setattr(secretkey, "QUERY_TIMEOUT", 1.0)
    copy = mutant(secretkey, old, new)
    monkeypatch.setattr(copy, "QUERY_TIMEOUT", 1.0)
    assert _big_answer_problems(copy, keyring, monkeypatch, tmp_path)


# --- the key: pipes only, exactly 64 bytes, never empty -----------------------------------------------


def _filled(data):
    reader, writer = os.pipe()
    os.write(writer, data)
    os.close(writer)
    return reader


@pytest.mark.parametrize(("data", "accepted"), [
    (b"a" * 64, True), (b"a" * 64 + b"\n", True),
    (b"", False), (b"a" * 63, False), (b"a" * 66, False), (b"\n", False), (b"a" * 4000, False),
    # Only the count is known (the bytes stay unread): 63 digits and a LF pass as 64 bytes,
    # and gocryptfs then finds a key that does not fit (wallet-mismatch), never an empty one.
    (b"a" * 63 + b"\n", True),
])
def test_key_pipe_moves_exactly_the_key_and_drops_the_lf(data, accepted):
    source = _filled(data)
    try:
        if not accepted:
            with pytest.raises(webdata.HelperError):
                secretkey._key_pipe(source)
            return
        assert pipe_bytes(secretkey._key_pipe(source)) == data[:64]
    finally:
        os.close(source)


class ReadSpy:
    """Records every os.read made by the helper's own modules (secretkey, vault, and their
    mutants); the helper must never read a pipe (FIFO) fd. subprocess's own reads of its
    exec-error pipe and of busctl's captured answer are not the helper's."""

    MODULES = ("hearthwire.core.secretkey", "hearthwire.core.vault")
    # Pipes the helper does read, holding no key: gocryptfs -version's version line and busctl's
    # answer (booleans and object paths, at most 4097 bytes; the one PIPE of secretkey.py).
    NOT_KEYS = ("_gocryptfs_major", "_read_answer")

    def __init__(self, monkeypatch):
        self.calls = []
        self.real = os.read
        monkeypatch.setattr(os, "read", self._read)

    def _read(self, descriptor, count):
        frame = sys._getframe(1)
        caller = frame.f_globals.get("__name__", "")
        if caller.startswith(self.MODULES):
            self.calls.append((descriptor, count, stat.S_ISFIFO(os.fstat(descriptor).st_mode), caller,
                               frame.f_code.co_name))
        return self.real(descriptor, count)

    def pipe_reads(self):
        return [call for call in self.calls if call[2] and call[4] not in self.NOT_KEYS]


def test_key_pipe_never_reads_the_key(monkeypatch):
    source = _filled(b"b" * 64 + b"\n")
    spy = ReadSpy(monkeypatch)
    result = secretkey._key_pipe(source)
    assert spy.calls == []
    monkeypatch.setattr(os, "read", spy.real)
    assert pipe_bytes(result) == b"b" * 64
    os.close(source)


KEY_MUTATIONS = {
    "no count": ("    if _waiting(source) not in _KEY_COUNTS:\n        raise HelperError(\"os-error\")\n", ""),
    "any count": ("    if _waiting(source) not in _KEY_COUNTS:\n", "    if _waiting(source) < 0:\n"),
    "the LF kept": ("            count = os.splice(source, writer, KEY_LENGTH - moved)\n",
                    "            count = os.splice(source, writer, KEY_LENGTH + 1 - moved)\n"),
    "read and written": ("            count = os.splice(source, writer, KEY_LENGTH - moved)\n",
                         "            count = os.write(writer, os.read(source, KEY_LENGTH - moved))\n"),
}


def key_pipe_problems(module, monkeypatch):
    problems = []
    for data in (b"", b"c" * 10, b"c" * 100):
        source = _filled(data)
        try:
            module._key_pipe(source)
            problems.append(f"takes {len(data)} bytes")
        except (webdata.HelperError, OSError):
            pass
        finally:
            os.close(source)
    source = _filled(b"d" * 64 + b"\n")
    spy = ReadSpy(monkeypatch)
    try:
        result = module._key_pipe(source)
    finally:
        monkeypatch.setattr(os, "read", spy.real)
        os.close(source)
    if spy.calls:
        problems.append("reads the key")
    if pipe_bytes(result) != b"d" * 64:
        problems.append("hands on something else than the 64 hex digits")
    return problems


def test_key_pipe_rules_hold(monkeypatch):
    assert key_pipe_problems(secretkey, monkeypatch) == []


@pytest.mark.parametrize("name", sorted(KEY_MUTATIONS))
def test_proof_the_key_pipe_rules_catch(monkeypatch, name):
    assert key_pipe_problems(mutant(secretkey, *KEY_MUTATIONS[name]), monkeypatch)


def test_store_new_key_stores_64_hex_digits_without_lf_through_pipes(keyring):
    secretkey.store_new_key(keyring.tools, secretkey.ITEM_NEW)
    openssl, store = keyring.calls()
    assert openssl["tool"] == "openssl" and openssl["length"] == 65
    assert openssl["fds"][0] == "/dev/null" and openssl["fds"][1].startswith("pipe:")
    assert store["argv"] == secretkey.store_argv(keyring.tools["secret-tool"], secretkey.ITEM_NEW)[1:]
    assert store["fds"][0].startswith("pipe:") and store["fds"][1:] == ["/dev/null", "/dev/null"]
    assert store["length"] == 64 and store["lf"] is False
    value = keyring.items()[secretkey.ITEM_NEW]
    assert re.fullmatch(r"[0-9a-f]{64}", value)
    assert hashlib.sha256(value.encode()).hexdigest() == store["sha"]


@pytest.mark.parametrize("output", ["empty", "short", "long"])
def test_store_new_key_refuses_anything_but_a_key_and_stores_nothing(keyring, output):
    keyring.env(STUB_OPENSSL_OUTPUT=output)
    with pytest.raises(webdata.HelperError) as raised:
        secretkey.store_new_key(keyring.tools, secretkey.ITEM)
    assert raised.value.code == "wallet-write-failed"
    assert keyring.calls("secret-tool") == [] and keyring.items() == {}


def test_store_new_key_accepts_openssl_without_the_lf(keyring):
    keyring.env(STUB_OPENSSL_OUTPUT="nolf")
    secretkey.store_new_key(keyring.tools, secretkey.ITEM)
    assert keyring.calls("secret-tool")[0]["length"] == 64


@pytest.mark.parametrize(("settings", "error"), [
    ({"STUB_OPENSSL_EXIT": 1}, "wallet-write-failed"),
    ({"STUB_SS_STORE_FAIL_ITEM": "*"}, "wallet-write-failed"),
    ({"STUB_SS_BUS": "bad"}, "wallet-write-failed"),
])
def test_store_new_key_failures(keyring, settings, error):
    keyring.env(**settings)
    with pytest.raises(webdata.HelperError) as raised:
        secretkey.store_new_key(keyring.tools, secretkey.ITEM)
    assert raised.value.code == error
    if "STUB_OPENSSL_EXIT" in settings:
        assert keyring.calls("secret-tool") == []  # The store never starts on a closed pipe.


def test_lookup_into_pipe_hands_on_the_key_only_after_exit_0(keyring, monkeypatch):
    keyring.store.write_text(json.dumps({secretkey.ITEM: "e" * 64}))
    tool = keyring.tools["secret-tool"]
    assert pipe_bytes(secretkey.lookup_into_pipe(tool)) == b"e" * 64
    keyring.env(STUB_SS_LOOKUP_LF=1)  # R0 S2: a stored LF came back once; it is dropped.
    assert pipe_bytes(secretkey.lookup_into_pipe(tool)) == b"e" * 64
    (call, _) = keyring.calls("secret-tool")
    assert call["fds"][0] == "/dev/null" and call["fds"][1].startswith("pipe:") and call["fds"][2] == "/dev/null"
    for settings, items in (({"STUB_SS_LOOKUP_FAIL_ITEM": "*"}, {secretkey.ITEM: "e" * 64}),
                            ({}, {}), ({}, {secretkey.ITEM: ""}), ({}, {secretkey.ITEM: "e" * 10}),
                            ({"STUB_SS_BUS": "bad"}, {secretkey.ITEM: "e" * 64})):
        keyring.env(STUB_SS_LOOKUP_LF="", **settings)
        keyring.store.write_text(json.dumps(items))
        with pytest.raises(webdata.HelperError) as raised:
            secretkey.lookup_into_pipe(tool)
        assert raised.value.code == "wallet-failed", (settings, items)
        for key in settings:
            keyring.monkeypatch.delenv(key)


def test_lookup_times_out_on_an_unanswered_prompt(keyring):
    keyring.store.write_text(json.dumps({secretkey.ITEM: "e" * 64}))
    keyring.env(STUB_SS_BLOCK="lookup:encrypted-chat-folder", STUB_SS_SLEEP=5)
    with pytest.raises(webdata.HelperError) as raised:
        secretkey.lookup_into_pipe(keyring.tools["secret-tool"], timeout=0.3)
    assert raised.value.code == "wallet-failed"


def test_copy_item_moves_the_key_fd_to_fd(keyring):
    keyring.store.write_text(json.dumps({secretkey.ITEM_NEW: "f" * 64, secretkey.ITEM: "0" * 64}))
    secretkey.copy_item(keyring.tools, secretkey.ITEM_NEW, secretkey.ITEM)
    lookup, store = keyring.calls("secret-tool")
    assert lookup["argv"][0] == "lookup" and store["argv"][0] == "store"
    assert lookup["fds"][1].startswith("pipe:") and store["fds"][0].startswith("pipe:")
    assert lookup["sha"] == store["sha"] and store["length"] == 64 and not store["lf"]
    assert keyring.items()[secretkey.ITEM] == "f" * 64


def test_copy_item_never_stores_a_failed_lookup(keyring):
    keyring.store.write_text(json.dumps({secretkey.ITEM: "0" * 64}))
    with pytest.raises(webdata.HelperError) as raised:
        secretkey.copy_item(keyring.tools, secretkey.ITEM_NEW, secretkey.ITEM)
    assert raised.value.code == "wallet-failed"
    assert [call["argv"][0] for call in keyring.calls("secret-tool")] == ["lookup"]
    assert keyring.items() == {secretkey.ITEM: "0" * 64}


def test_clear_item_overwrites_then_clears_and_checks(keyring):
    keyring.store.write_text(json.dumps({secretkey.ITEM: "1" * 64}))
    secretkey.clear_item(keyring.tools, secretkey.ITEM)
    steps = [(call["tool"], call["argv"][2] if call["tool"] == "busctl" else call["argv"][0])
             for call in keyring.calls()]
    assert steps == [("openssl", "rand"), ("secret-tool", "store"), ("secret-tool", "clear"), ("busctl", "call")]
    stored = keyring.calls("secret-tool")[0]["sha"]
    assert stored != hashlib.sha256(b"1" * 64).hexdigest()
    assert keyring.items() == {}


def test_clear_item_that_stays_is_wallet_failed(keyring):
    keyring.store.write_text(json.dumps({secretkey.ITEM: "1" * 64}))
    keyring.env(STUB_SS_CLEAR_KEEPS=1)
    with pytest.raises(webdata.HelperError) as raised:
        secretkey.clear_item(keyring.tools, secretkey.ITEM)
    assert raised.value.code == "wallet-failed"


def test_clear_item_without_openssl_skips_the_overwrite(keyring):
    keyring.store.write_text(json.dumps({secretkey.ITEM: "1" * 64}))
    tools = {name: path for name, path in keyring.tools.items() if name != "openssl"}
    secretkey.clear_item(tools, secretkey.ITEM)
    assert [call["argv"][0] for call in keyring.calls("secret-tool")] == ["clear"]
    assert keyring.items() == {}


def test_after_a_stop_the_clear_still_runs_without_the_overwrite(keyring, monkeypatch):
    keyring.store.write_text(json.dumps({secretkey.ITEM_NEW: "1" * 64}))
    def stopped():
        raise termination.Stopped

    monkeypatch.setattr(termination, "requested", lambda: True)
    monkeypatch.setattr(termination, "check", stopped)
    secretkey.clear_item(keyring.tools, secretkey.ITEM_NEW)
    assert [call["argv"][0] for call in keyring.calls("secret-tool")] == ["clear"]
    assert keyring.items() == {}


def test_remove_items(keyring):
    assert secretkey.forget(keyring.tools) is False and keyring.calls("secret-tool") == []
    keyring.store.write_text(json.dumps({secretkey.ITEM: "1" * 64, secretkey.ITEM_NEW: "2" * 64, "other": "3"}))
    assert secretkey.remove_items(keyring.tools) is True
    assert keyring.items() == {"other": "3"}
    assert secretkey.remove_items(keyring.tools) is False
    keyring.store.write_text(json.dumps({secretkey.ITEM: "1" * 64}))
    keyring.env(STUB_SS_SEARCH="fail")
    with pytest.raises(webdata.HelperError) as raised:
        secretkey.remove_items(keyring.tools)
    assert raised.value.code == "wallet-failed"


def forget_problems(module, keyring):
    """forget decides on SearchItems: no default alias (Locked fails) is no reason to leave an item."""
    problems = []
    keyring.store.write_text(json.dumps({secretkey.ITEM: "1" * 64}))
    keyring.env(STUB_SS_LOCKED="fail")
    try:
        if module.forget(keyring.tools) is not True or keyring.items() != {}:
            problems.append("the item stays when Locked fails")
    except webdata.HelperError as failure:
        problems.append(f"Locked failing gave {failure.code}")
    # No answer at all (no bus): wallet-failed, never a quiet ok.
    keyring.store.write_text(json.dumps({secretkey.ITEM: "1" * 64}))
    keyring.env(STUB_SS_LOCKED="false", STUB_SS_BUS="bad")
    try:
        module.forget(keyring.tools)
        problems.append("no answer at all was taken for nothing to do")
    except webdata.HelperError as failure:
        if failure.code != "wallet-failed":
            problems.append(f"no answer gave {failure.code}")
    keyring.env(STUB_SS_BUS="")
    # An answer that says "no item": nothing to do.
    keyring.store.write_text(json.dumps({}))
    if module.forget(keyring.tools) is not False:
        problems.append("no item was not nothing to do")
    return problems


def test_forget(keyring):
    assert forget_problems(secretkey, keyring) == []


FORGET_MUTATIONS = {
    "gated on Locked": ("    states = [item_exists(busctl, item) for item in ITEMS]\n",
                        "    if collection_locked(busctl) is None:\n        return False\n"
                        "    states = [item_exists(busctl, item) for item in ITEMS]\n"),
    "no answer is nothing to do": ("    if all(state is None for state in states):\n        raise HelperError(\"wallet-failed\")\n",
                                   "    if all(state is None for state in states):\n        return False\n"),
}


@pytest.mark.parametrize("name", sorted(FORGET_MUTATIONS))
def test_proof_the_forget_rule_catches(keyring, name):
    assert forget_problems(mutant(secretkey, *FORGET_MUTATIONS[name]), keyring)


# --- is the keyring stored encrypted? (the 32-byte header check) ------------------------------------------

PLAIN = b"[keyring]\ndisplay-name=Default keyring\nctime=0\nmtime=0\nlock-on-idle=false\nlock-after=false\n"
ENCRYPTED = b"GnomeKeyring\n\r\x00\n\x00\x00\x00\x00" + b"\x00" * 89


def keyrings(home, *, default="Default_keyring\n", name="Default_keyring", content=PLAIN):
    folder = home / "keyrings"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if default is not None:
        (folder / "default").write_text(default)
    if content is not None:
        (folder / f"{name}.keyring").write_bytes(content)
    return folder


@pytest.fixture
def home(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    return data


def storage(home):
    return secretkey.keyring_storage({"XDG_DATA_HOME": str(home)})


def test_plain_and_encrypted_keyrings(home):
    folder = keyrings(home)
    assert storage(home) == "plain"  # Omarchy's Default_keyring (R0 S1).
    (folder / "default").write_text("login\n")
    (folder / "login.keyring").write_bytes(ENCRYPTED)
    assert storage(home) == "encrypted"
    (folder / "default").unlink()
    assert storage(home) == "encrypted"  # No default file: the daemon's login keyring (R0 S6).
    (folder / "login.keyring").unlink()
    assert storage(home) == "unknown"
    (folder / "default").write_text("Default_keyring")  # Without the LF too.
    assert storage(home) == "plain"


def test_the_base_is_xdg_data_home_or_local_share(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    keyrings(tmp_path / "home" / ".local" / "share")
    assert secretkey.keyring_storage({"XDG_DATA_HOME": "relative/path"}) == "plain"
    assert secretkey.keyring_storage({}) == "plain"
    assert secretkey.keyring_storage({"XDG_DATA_HOME": str(tmp_path / "none")}) == "unknown"


@pytest.mark.parametrize("content", [b"", b"[keyrin", b"GnomeKeyring\n\r\x00", b"PK\x03\x04", b"\x00" * 32,
                                     b" [keyring]"])
def test_other_headers_are_unknown(home, content):
    keyrings(home, content=content)
    assert storage(home) == "unknown"


@pytest.mark.parametrize("name", ["", "\n", "\n\n", ".hidden", "-x", "..", "a/b", "../keyrings/x", "a b", "x" * 65,
                                  "Default_keyring\n\n", "é", "a\0b", " Default_keyring", "Default_keyring\r\n"])
def test_bad_default_names_are_unknown(home, name):
    folder = keyrings(home, default=None)  # Default_keyring.keyring is there and plain.
    (folder / "default").write_bytes(name.encode())
    assert storage(home) == "unknown"


def test_an_oversized_default_file_is_unknown(home):
    keyrings(home, default="Default_keyring\n" + "#" * 300)
    assert storage(home) == "unknown"


def _link(path, target):
    if path.exists():
        path.unlink()
    path.symlink_to(target)


@pytest.mark.parametrize("variant", ["keyrings link", "keyrings file", "default link", "keyring link",
                                     "default fifo", "keyring fifo", "keyring dir", "default dir"])
def test_links_and_non_files_are_refused(home, tmp_path, variant):
    elsewhere = tmp_path / "elsewhere"
    keyrings(elsewhere)
    folder = home / "keyrings"
    if variant == "keyrings link":
        folder.symlink_to(elsewhere / "keyrings")
    elif variant == "keyrings file":
        folder.write_text("")
    else:
        keyrings(home)
        target = folder / ("default" if variant.startswith("default") else "Default_keyring.keyring")
        target.unlink()
        if variant.endswith("link"):
            target.symlink_to(elsewhere / "keyrings" / target.name)
        elif variant.endswith("fifo"):
            os.mkfifo(target)
        else:
            target.mkdir()
    assert storage(home) == "unknown"


def foreign(monkeypatch, name):
    """Make the open file whose name is ``name`` look like another user's."""
    real = os.fstat

    def fstat(descriptor):
        info = real(descriptor)
        try:
            path = os.readlink(f"/proc/self/fd/{descriptor}")
        except OSError:
            return info
        if os.path.basename(path) == name:
            values = list(info)
            values[4] = info.st_uid + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(os, "fstat", fstat)


@pytest.mark.parametrize("name", ["default", "Default_keyring.keyring"])
def test_foreign_files_are_refused(home, monkeypatch, name):
    keyrings(home)
    foreign(monkeypatch, name)
    assert storage(home) == "unknown"


def test_a_foreign_keyrings_folder_is_refused(home, monkeypatch):
    keyrings(home)
    real = os.stat

    def stat_(path, *args, **kwargs):
        info = real(path, *args, **kwargs)
        if path == "keyrings":
            values = list(info)
            values[4] = info.st_uid + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(os, "stat", stat_)
    assert storage(home) == "unknown"


def header_read_problems(module, home, monkeypatch):
    """The .keyring file gets exactly one os.read of at most 32 bytes; nothing else of it is read."""
    big = PLAIN + b"x" * 5000
    keyrings(home, content=big)
    calls = []
    real = os.read

    def spy(descriptor, count):
        path = os.readlink(f"/proc/self/fd/{descriptor}")
        data = real(descriptor, count)
        calls.append((os.path.basename(path), count, len(data)))
        return data

    real_fdopen, real_pread = os.fdopen, os.pread
    with monkeypatch.context() as patch:
        patch.setattr(os, "read", spy)
        patch.setattr(os, "fdopen", lambda *a, **k: calls.append(("fdopen",)) or real_fdopen(*a, **k))
        patch.setattr(os, "pread", lambda *a, **k: calls.append(("pread",)) or real_pread(*a, **k))
        result = module.keyring_storage({"XDG_DATA_HOME": str(home)})
    problems = []
    if result != "plain":
        problems.append(f"says {result}")
    header = [call for call in calls if call[0] == "Default_keyring.keyring"]
    if len(header) != 1:
        problems.append(f"{len(header)} reads of the keyring file")
    elif header[0][1] > 32 or header[0][2] > 32:
        problems.append(f"reads {header[0][1]} bytes of the keyring file")
    if any(call[0] in ("fdopen", "pread") for call in calls):
        problems.append("reads the file another way")
    return problems


def test_the_header_read_is_one_read_of_at_most_32_bytes(home, monkeypatch):
    assert header_read_problems(secretkey, home, monkeypatch) == []


HEADER_MUTATIONS = {
    "33 bytes": ("HEADER_SIZE = 32\n", "HEADER_SIZE = 33\n"),
    "the whole file": ("        head = os.read(descriptor, HEADER_SIZE)\n",
                       "        head = os.read(descriptor, 1 << 20)\n"),
    "two reads": ("        head = os.read(descriptor, HEADER_SIZE)\n",
                  "        head = os.read(descriptor, 16)\n        head += os.read(descriptor, 16)\n"),
    "a read to the end": ("        head = os.read(descriptor, HEADER_SIZE)\n",
                          "        head = os.read(descriptor, HEADER_SIZE)\n        os.read(descriptor, 99)\n"),
}


@pytest.mark.parametrize("name", sorted(HEADER_MUTATIONS))
def test_proof_the_header_read_rule_catches(home, monkeypatch, name):
    assert header_read_problems(mutant(secretkey, *HEADER_MUTATIONS[name]), home, monkeypatch)


def _named(home, name):
    """A default file naming ``name``, and a plain ``<name>.keyring`` next to it."""
    (home / "keyrings" / "default").write_text(name + "\n")
    (home / "keyrings" / f"{name}.keyring").write_bytes(PLAIN)


def refusal_problems(module, tmp_path, monkeypatch):
    """Links, non-files, foreign files and bad names give "unknown"."""
    problems = []
    for index, (variant, setup) in enumerate({
        "a linked default": lambda h, e: _link(h / "keyrings" / "default", e / "keyrings" / "default"),
        "a linked keyring": lambda h, e: _link(h / "keyrings" / "Default_keyring.keyring",
                                               e / "keyrings" / "Default_keyring.keyring"),
        "a dotted name": lambda h, e: _named(h, ".Default_keyring"),
        "a dashed name": lambda h, e: _named(h, "-Default_keyring"),
        "a long default file": lambda h, e: (h / "keyrings" / "default").write_text("Default_keyring\n" + " " * 300),
    }.items()):
        home, elsewhere = tmp_path / f"h{index}", tmp_path / f"e{index}"
        keyrings(home)
        keyrings(elsewhere)
        setup(home, elsewhere)
        if module.keyring_storage({"XDG_DATA_HOME": str(home)}) != "unknown":
            problems.append(f"takes {variant}")
    home = tmp_path / "foreign"
    keyrings(home)
    with monkeypatch.context() as patch:
        foreign(patch, "Default_keyring.keyring")
        if module.keyring_storage({"XDG_DATA_HOME": str(home)}) != "unknown":
            problems.append("takes a foreign keyring file")
    return problems


def test_refusals_hold(tmp_path, monkeypatch):
    assert refusal_problems(secretkey, tmp_path, monkeypatch) == []


REFUSAL_MUTATIONS = {
    "links followed": ("_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK",
                       "_FILE_FLAGS = os.O_RDONLY | os.O_NONBLOCK"),
    "any owner": ("        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():\n            raise OSError(",
                  "        if not stat.S_ISREG(info.st_mode):\n            raise OSError("),
    "dotted names": ('            and not name.startswith((".", "-")))\n', '            and not name.startswith("-"))\n'),
    "dashed names": ('            and not name.startswith((".", "-")))\n', '            and not name.startswith("."))\n'),
    "no size limit": ("        if os.fstat(descriptor).st_size > _MAX_DEFAULT_SIZE:\n            return None\n"
                      "        content = os.read(descriptor, _MAX_DEFAULT_SIZE + 1)\n",
                      "        content = os.read(descriptor, 1 << 20)[:64].rstrip()\n"),
}


@pytest.mark.parametrize("name", sorted(REFUSAL_MUTATIONS))
def test_proof_the_refusals_catch(tmp_path, monkeypatch, name):
    assert refusal_problems(mutant(secretkey, *REFUSAL_MUTATIONS[name]), tmp_path, monkeypatch)


def test_a_linked_base_is_allowed_but_a_linked_keyrings_folder_is_not(tmp_path):
    real = tmp_path / "real"
    keyrings(real)
    (tmp_path / "link").symlink_to(real)
    assert secretkey.keyring_storage({"XDG_DATA_HOME": str(tmp_path / "link")}) == "plain"


# --- static rules ---------------------------------------------------------------------------------------

# The only functions that may read a file: the keyring's name and its header.
FILE_READERS = {"_default_name", "_header_class"}
# The one bounded read of a busctl answer (booleans and object paths).
BUS_READERS = {"_read_answer"}


def test_secretkey_source_rules():
    code = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] in sys.stdlib_module_names for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            assert (node.module or "").split(".")[0] in sys.stdlib_module_names
    for pattern in (r"\bshell\s*=", r"(?<![\w.])print\s*\(", r"\bcapture_output\b", r"\bcheck_output\b",
                    r"\bos\.system\b", r"\bos\.popen\b", r"\bgetoutput\b", r"\bcommunicate\b",
                    r"\bsys\.std(out|err)\b", r"\bos\.fdopen\b", r"(?<![\w.])open\s*\(",
                    r"\b(?:stdin|stdout|stderr)\s*=\s*-\s*1\b", r"\"search\""):
        assert not re.search(pattern, code), pattern
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    for function in functions:
        reads = [node for node in ast.walk(function) if isinstance(node, ast.Attribute)
                 and node.attr in ("read", "readv", "pread", "preadv", "recv", "readinto", "readline",
                                   "readlines", "readall")]
        assert not reads or function.name in FILE_READERS | BUS_READERS, function.name
        uses_pipe = any(isinstance(node, ast.Attribute) and node.attr == "PIPE" for node in ast.walk(function))
        assert uses_pipe == (function.name == "_query"), function.name
    assert code.count("subprocess.PIPE") == 1
    # The file readers open with O_NOFOLLOW (the flags) and never get a pipe from a child.
    for function in (node for node in functions if node.name in FILE_READERS):
        assert "_open_own_file" in ast.unparse(function), function.name


@pytest.mark.parametrize("old,new", [
    ("            stdin=stdin,\n            stdout=stdout,\n", "            stdin=stdin,\n            stdout=subprocess.PIPE,\n"),
    ("        code = _finish(child, PROMPT_TIMEOUT if timeout is None else timeout)\n        if code != 0:\n",
     "        code = _finish(child, PROMPT_TIMEOUT if timeout is None else timeout)\n        os.read(reader, 99)\n"
     "        if code != 0:\n"),
    ("        code = _finish(child, PROMPT_TIMEOUT if timeout is None else timeout)\n        if code != 0:\n",
     "        code = _finish(child, PROMPT_TIMEOUT if timeout is None else timeout)\n        child.communicate()\n"
     "        if code != 0:\n"),
    ("        code = _finish(child, PROMPT_TIMEOUT if timeout is None else timeout)\n        if code != 0:\n",
     "        code = _finish(child, PROMPT_TIMEOUT if timeout is None else timeout)\n"
     "        os.readv(reader, [bytearray(65)])\n        if code != 0:\n"),
    ("        code = _finish(child, PROMPT_TIMEOUT if timeout is None else timeout)\n        if code != 0:\n",
     "        code = _finish(child, PROMPT_TIMEOUT if timeout is None else timeout)\n"
     "        os.fdopen(reader).readline()\n        if code != 0:\n"),
    ("    return [secret_tool, \"lookup\", *attributes(item)]\n",
     "    return [secret_tool, \"search\", *attributes(item)]\n"),
])
def test_proof_secretkey_source_rules_catch(old, new, monkeypatch, tmp_path):
    code = SOURCE.read_text(encoding="utf-8")
    assert old in code
    mutated = tmp_path / "secretkey.py"
    mutated.write_text(code.replace(old, new, 1))
    monkeypatch.setattr(sys.modules[__name__], "SOURCE", mutated)
    with pytest.raises(AssertionError):
        test_secretkey_source_rules()


def test_the_runtime_spy_sees_no_key_read(keyring, monkeypatch):
    """The same rule at run time: store, lookup and copy never os.read a pipe."""
    spy = ReadSpy(monkeypatch)
    secretkey.store_new_key(keyring.tools, secretkey.ITEM_NEW)
    secretkey.copy_item(keyring.tools, secretkey.ITEM_NEW, secretkey.ITEM)
    reader = secretkey.lookup_into_pipe(keyring.tools["secret-tool"])
    os.close(reader)
    assert spy.pipe_reads() == []
    assert keyring.items()[secretkey.ITEM] == keyring.items()[secretkey.ITEM_NEW]


def test_proof_the_runtime_spy_sees_a_key_read(keyring, monkeypatch):
    copy = mutant(secretkey, "        if code != 0:\n            raise HelperError(\"wallet-failed\")\n        try:\n",
                  "        if code != 0:\n            raise HelperError(\"wallet-failed\")\n        os.read(reader, 1)\n"
                  "        try:\n")
    keyring.store.write_text(json.dumps({secretkey.ITEM: "a" * 64 + "\n"}))
    spy = ReadSpy(monkeypatch)
    try:
        os.close(copy.lookup_into_pipe(keyring.tools["secret-tool"]))
    except webdata.HelperError:
        pass
    assert spy.pipe_reads()


def test_find_tools_needs_absolute_paths(tmp_path, monkeypatch):
    install_keyring_stubs(tmp_path)
    monkeypatch.chdir(tmp_path.parent)
    monkeypatch.setenv("PATH", tmp_path.name)
    assert secretkey.find_tools() == ({}, ("secret-tool", "busctl"))
    monkeypatch.setenv("PATH", str(tmp_path))
    found, missing = secretkey.find_tools()
    assert set(found) == {"secret-tool", "busctl", "openssl"} and missing == ()


def test_children_get_their_own_process_group(keyring, monkeypatch):
    seen = []
    real = subprocess.Popen

    def popen(*args, **kwargs):
        seen.append(kwargs.get("process_group"))
        return real(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", popen)
    secretkey.store_new_key(keyring.tools, secretkey.ITEM)
    secretkey.collection_locked(keyring.tools["busctl"])
    assert seen and all(group == 0 for group in seen)
