"""The passphrase-encrypted Chat folder (core/vault.py) against stub tools.

Stub gocryptfs, kdialog and fusermount3 scripts are the only programs on PATH:
the real ones never run and nothing prompts. The stubs record their argv and
where their stdin/stdout/stderr point, emulate exit codes, and "mount" by
writing a line into a fake mountinfo file the helper is pointed at.
"""

import errno
import fcntl
import json
import os
import re
import stat
import subprocess
import time
import sys
from pathlib import Path

import pytest

from hearthwire import cli
from hearthwire.core import vault, webdata


SOURCE = Path(vault.__file__)

STUB = r'''#!{python}
import json, os, stat, sys, time

tool = os.path.basename(sys.argv[0])
args = sys.argv[1:]
env = os.environ


def fd_target(fd):
    try:
        return os.readlink(f"/proc/self/fd/{{fd}}")
    except OSError:
        return "closed"


def escape(path):
    return path.replace("\\", "\\134").replace(" ", "\\040").replace("\t", "\\011").replace("\n", "\\012")


def log(record):
    with open(env["STUB_LOG"], "a") as handle:
        handle.write(json.dumps(record) + "\n")


record = {{"tool": tool, "argv": args, "fds": [fd_target(0), fd_target(1), fd_target(2)],
          "start_ns": time.monotonic_ns(),
          "python_env": {{key: value for key, value in env.items() if key.startswith("PYTHON")}}}}

if tool == "kdialog":
    # Logged at start: a dialog killed while open never logs "kdialog-end".
    log(record)
    new = args[2:3] == ["--newpassword"]
    code = int(env.get("STUB_KDIALOG_EXIT", "0"))
    if new and "STUB_KDIALOG_NEW_EXIT" in env:
        code = int(env["STUB_KDIALOG_NEW_EXIT"])
    if new:
        time.sleep(float(env.get("STUB_KDIALOG_NEW_SLEEP", "0")))
    if code == 0:
        sys.stdout.write("\n" if new and env.get("STUB_KDIALOG_NEW_EMPTY") else "stub-passphrase\n")
        sys.stdout.flush()
    log({{"tool": "kdialog-end", "argv": args, "end_ns": time.monotonic_ns()}})
    sys.exit(code)
elif tool == "fusermount3":
    code = int(env.get("STUB_FUSERMOUNT_EXIT", "0"))
    counter = env["STUB_LOG"] + ".fusermount"
    calls = int(open(counter).read()) if os.path.exists(counter) else 0
    with open(counter, "w") as handle:
        handle.write(str(calls + 1))
    if calls < int(env.get("STUB_FUSERMOUNT_FAILS", "0")):
        code = 1
    if code == 0 and args[:1] == ["-u"]:
        info = env["STUB_MOUNTINFO"]
        with open(info) as handle:
            lines = handle.read().splitlines(keepends=True)
        target = escape(args[1])
        with open(info, "w") as handle:
            handle.writelines(line for line in lines if line.split(" ")[4] != target)
else:
    if args == ["-version"]:
        sys.stdout.write(env.get("STUB_VERSION", "gocryptfs v2.6.1; go-fuse [vendored]; 2025-08-11 go1.24.6 linux/amd64") + "\n")
        sys.exit(0)
    extpass, positional, index, config = [], [], 0, None
    while index < len(args):
        if args[index] == "-extpass":
            extpass.append(args[index + 1])
            index += 2
            continue
        if args[index] == "-config":
            config = args[index + 1]
            index += 2
            continue
        if not args[index].startswith("-"):
            positional.append(args[index])
        index += 1
    record["extpass"] = extpass
    phase = "init" if "-init" in args else "passwd" if "-passwd" in args else "mount"
    code = int(env.get(f"STUB_{{phase.upper()}}_EXIT", "0"))

    def run_extpass():
        # Like gocryptfs: the extpass program gets stdin on /dev/null and a stdout pipe.
        import subprocess
        answer = subprocess.run(extpass, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
        record["extpass_exit"] = answer.returncode
        record["extpass_got_answer"] = bool(answer.stdout.strip())
        return answer.returncode == 0 and bool(answer.stdout.strip())

    import hashlib

    def extpass_key():
        # Measured (KS1): one trailing LF is trimmed; a second line, an empty answer
        # or a non-zero exit (even with the right key printed) -> exit 9.
        import subprocess
        answer = subprocess.run(extpass, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
        data = answer.stdout[:-1] if answer.stdout.endswith(b"\n") else answer.stdout
        record["extpass_exit"] = answer.returncode
        record["extpass_sha"] = hashlib.sha256(data).hexdigest()
        if answer.returncode != 0 or not data or b"\n" in data:
            return None
        return data

    if phase == "passwd" and config is not None:
        # -passwd -config <copy>: re-wraps the copy; gocryptfs writes <config>.tmp
        # with O_EXCL (exit 24 if it exists), then renames it over <config> as 0400.
        if not os.path.exists(config):
            code = 11
        elif os.path.lexists(config + ".tmp"):
            code = 24
        elif code not in (6, 11):
            if not run_extpass():
                code = 9
            elif code != 12:
                line = sys.stdin.buffer.readline()
                key = line[:-1] if line.endswith(b"\n") else line
                record["stdin_sha"] = hashlib.sha256(key).hexdigest()
                if not key:
                    code = 9
                elif code == 0:
                    descriptor = os.open(config + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
                    os.write(descriptor, json.dumps({{"key_sha": record["stdin_sha"]}}).encode())
                    os.close(descriptor)
                    os.rename(config + ".tmp", config)
    elif phase == "passwd":
        # Measured gocryptfs 2.6.1: 6/11 before extpass; extpass once for the old
        # passphrase; wrong old -> 12 without reading stdin; else one stdin line.
        if code not in (6, 11):
            if not run_extpass():
                code = 9
            elif code == 12:
                time.sleep(float(env.get("STUB_PASSWD_DELAY", "0")))
            else:
                line = sys.stdin.readline()
                record["stdin_read_ns"] = time.monotonic_ns()
                record["new_received"] = bool(line.strip())
                if not line.strip():
                    code = 9
    elif phase == "mount" and config is not None and code == 0:
        if not os.path.exists(config):
            code = 11
        else:
            key = extpass_key()
            with open(config) as handle:
                expected = json.load(handle).get("key_sha")
            if key is None:
                code = 9
            elif hashlib.sha256(key).hexdigest() != expected:
                code = 12
            record["config"] = config
    elif extpass and env.get("STUB_RUN_EXTPASS"):
        run_extpass()
    if code == 0 and phase == "init":
        with open(os.path.join(positional[0], "gocryptfs.conf"), "w") as handle:
            handle.write("{{}}")
    if phase == "mount":
        cipher, mountpoint = positional
        record["mountpoint_mode"] = stat.S_IMODE(os.lstat(mountpoint).st_mode)
        record["mountpoint_entries"] = sorted(os.listdir(mountpoint))
    if phase == "mount" and (code == 0 or env.get("STUB_MOUNT_ADD_ENTRY")):
        fstype = env.get("STUB_FSTYPE", "fuse.gocryptfs")
        source = env.get("STUB_SOURCE", cipher)
        mount_options = env.get("STUB_MOUNT_OPTIONS", "rw,nosuid,nodev,relatime")
        uid = env.get("STUB_UID", str(os.getuid()))
        super_options = env.get("STUB_SUPER", f"rw,user_id={{uid}},group_id={{os.getgid()}},max_read=1048576")
        with open(env["STUB_MOUNTINFO"], "a") as handle:
            handle.write(f"901 30 0:99 / {{escape(mountpoint)}} {{mount_options}} shared:1 - {{fstype}} {{escape(source)}} {{super_options}}\n")

log(record)
sys.exit(code)
'''

# Stub kwallet-query, qdbus6 and openssl (not a format string). The "wallet" is a JSON
# file (STUB_WALLET) holding dummy values only. Records never hold a value, only
# sha256 hashes, so tests can prove the key went fd-to-fd from openssl to the wallet
# to gocryptfs without this process seeing it.
WALLET_STUB = r'''#!PYTHON
import hashlib, json, os, sys, time

tool = os.path.basename(sys.argv[0])
args = sys.argv[1:]
env = os.environ
KEY = "Hearthwire/encrypted-chat-folder"


def fd_target(fd):
    try:
        return os.readlink(f"/proc/self/fd/{fd}")
    except OSError:
        return "closed"


def log(record):
    with open(env["STUB_LOG"], "a") as handle:
        handle.write(json.dumps(record) + "\n")


def wallet():
    try:
        with open(env["STUB_WALLET"]) as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {}


def save(state):
    with open(env["STUB_WALLET"], "w") as handle:
        json.dump(state, handle)


def sha(data):
    return hashlib.sha256(data).hexdigest()


record = {"tool": tool, "argv": args, "fds": [fd_target(0), fd_target(1), fd_target(2)]}
code = 0
if tool == "openssl":
    code = int(env.get("STUB_OPENSSL_EXIT", "0"))
    value = os.urandom(32).hex() + "\n"
    if code == 0:
        sys.stdout.write(value)
        record["sha"] = sha(value.encode())
elif tool == "kwallet-query":
    name = args[-1]
    KEY = args[1] + "/" + args[3]
    record["entry"] = args[3]
    time.sleep(float(env.get("STUB_KWALLET_SLEEP", "0")))
    if "--write-password" in args:
        data = sys.stdin.buffer.read()
        if data.endswith(b"\n"):
            data = data[:-1]
        code = int(env.get("STUB_KWALLET_WRITE_EXIT", "0"))
        if env.get("STUB_KWALLET_WRITE_FAIL_ENTRY") == args[3]:
            code = 1
        if code == 0:
            state = wallet()
            state[KEY] = data.decode()
            save(state)
            record["sha"] = sha(data)
        else:
            sys.stdout.write("Failed to write entry\n")
    else:
        code = int(env.get("STUB_KWALLET_READ_EXIT", "0"))
        if env.get("STUB_KWALLET_READ_FAIL_ENTRY") == args[3]:
            code = 1
        state = wallet()
        if code == 0 and KEY not in state:
            code = 4
        if code == 0:
            value = state[KEY]
            sys.stdout.write(value + "\n")
            record["sha"] = sha(value.encode())
        else:
            # Like kwallet-query: its error message goes to stdout.
            sys.stdout.write(f"Failed to read entry {KEY} value from the {name} wallet.\n")
elif tool == "qdbus6":
    time.sleep(float(env.get("STUB_QDBUS_SLEEP", "0")))
    code = int(env.get("STUB_QDBUS_EXIT", "0"))
    name = env.get("STUB_WALLET_NAME", "kdewallet")
    method = args[2].rsplit(".", 1)[-1] if len(args) > 2 else ""
    answer = ""
    if args[:2] == ["org.kde.kwalletd6", "/modules/kwalletd6"]:
        state = wallet()
        if method == "isEnabled":
            answer = env.get("STUB_WALLET_ENABLED", "true")
        elif method == "localWallet":
            answer = name
        elif method == "keyDoesNotExist":
            answer = "false" if args[4] + "/" + args[5] in state and args[3] == name else "true"
        elif method == "open":
            answer = env.get("STUB_OPEN_HANDLE", "7")
        elif method == "removeEntry":
            answer = "0" if state.pop(args[4] + "/" + args[5], None) is not None else "-1"
            if env.get("STUB_REMOVE_KEEPS"):
                answer = "-1"
            else:
                save(state)
        elif method == "close":
            answer = "1"
    elif args[:1] == ["org.freedesktop.secrets"]:
        if args[2] == "Label":
            answer = env.get("STUB_ALIAS_LABEL", name)
        elif args[2] == "Locked":
            answer = env.get("STUB_WALLET_LOCKED", "false")
    if code == 0:
        sys.stdout.write(answer + "\n")
log(record)
sys.exit(code)
'''

WALLET_TOOLS = ("kwallet-query", "qdbus6", "openssl")

# Unrelated mounts that must be ignored.
BASE_MOUNTINFO = (
    "22 1 0:21 / / rw,relatime shared:1 - btrfs /dev/nvme0n1p2 rw,ssd\n"
    "35 22 0:32 / /run/user/1000 rw,nosuid,nodev,relatime shared:2 - tmpfs tmpfs rw,size=1000k,mode=700\n"
)


class Stubs:
    def __init__(self, root, monkeypatch, runtime):
        self.root = root
        self.bin = root / "bin"
        self.bin.mkdir()
        self.log = root / "stub.log"
        self.log.write_text("")
        self.mountinfo = root / "mountinfo"
        self.mountinfo.write_text(BASE_MOUNTINFO)
        self.data = root / "data"
        self.runtime = runtime
        self.monkeypatch = monkeypatch
        for name in (*vault.TOOLS, *WALLET_TOOLS):
            self.install(name)
        monkeypatch.setenv("PATH", str(self.bin))
        monkeypatch.setenv("XDG_DATA_HOME", str(self.data))
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
        monkeypatch.setenv("STUB_LOG", str(self.log))
        self.wallet = root / "wallet.json"
        monkeypatch.setenv("STUB_WALLET", str(self.wallet))
        monkeypatch.setenv("STUB_MOUNTINFO", str(self.mountinfo))
        monkeypatch.setattr(vault, "MOUNTINFO", str(self.mountinfo))
        # The stub mountpoint is a plain directory, so its device equals its parent's.
        monkeypatch.setattr(vault, "_same_device", lambda root_info, parent_info: False)
        monkeypatch.setattr(vault, "LOCK_TIMEOUT", 0.3)
        monkeypatch.setattr(vault, "PASSWD_GRACE", 0.3)
        monkeypatch.setattr(vault, "UNMOUNT_RETRY_DELAYS", (0.0, 0.0))

    def install(self, name):
        path = self.bin / name
        if name in WALLET_TOOLS:
            path.write_text(WALLET_STUB.replace("PYTHON", sys.executable, 1))
        else:
            path.write_text(STUB.format(python=sys.executable))
        path.chmod(0o755)

    def remove(self, name):
        (self.bin / name).unlink()

    def calls(self, tool=None, *, skip_version=True):
        records = [json.loads(line) for line in self.log.read_text().splitlines() if line]
        return [
            record for record in records
            if (tool is None or record["tool"] == tool)
            and not (skip_version and record["argv"] == ["-version"])
        ]

    def env(self, **values):
        for key, value in values.items():
            self.monkeypatch.setenv(key, str(value))

    @property
    def cipher(self):
        return Path(os.path.realpath(self.data)) / "hearthwire" / "vault"

    @property
    def mountpoint(self):
        return Path(os.path.realpath(self.runtime)) / "hearthwire" / "vault"

    def make_locked(self):
        self.cipher.mkdir(parents=True, mode=0o700)
        (self.cipher / "gocryptfs.conf").write_text("{}")

    def mountpoint_mode(self):
        return stat.S_IMODE(os.lstat(self.mountpoint).st_mode)

    def ended(self, tool):
        return [json.loads(line) for line in self.log.read_text().splitlines()
                if line and json.loads(line)["tool"] == f"{tool}-end"]

    def mounted(self):
        text = self.mountinfo.read_text()
        return "fuse.gocryptfs" in text or "fuse.other" in text


@pytest.fixture
def stubs(tmp_path, monkeypatch, _private_runtime_dir):
    return Stubs(tmp_path, monkeypatch, _private_runtime_dir)


def vault_argv(operation):
    return ["--vault", operation, *(["--method", "wallet"] if operation in ("add-key", "remove-key") else [])]


def reply(operation, capsys, *extra):
    assert cli.main([*vault_argv(operation), *extra]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    return json.loads(captured.out)


def extpass_values(argv):
    """Values of the repeated ``-extpass VALUE`` pairs, in order."""
    values = []
    for index, argument in enumerate(argv):
        if argument == "-extpass":
            values.append(argv[index + 1])
    return values


def without_extpass(argv):
    """argv with every ``-extpass VALUE`` pair removed."""
    out, index = [], 0
    while index < len(argv):
        if argv[index] == "-extpass":
            index += 2
            continue
        out.append(argv[index])
        index += 1
    return out


# --- availability ---------------------------------------------------------------------


def test_status_reports_missing_tools_without_paths(stubs, capsys, tmp_path):
    for name in vault.TOOLS:
        stubs.remove(name)
    out = reply("status", capsys)
    assert out == {"ok": True, "state": "unavailable", "missing": ["gocryptfs", "kdialog", "fusermount3"]}
    assert stubs.calls(skip_version=False) == []


@pytest.mark.parametrize("name", vault.TOOLS)
def test_status_names_only_the_missing_tool(stubs, capsys, name):
    stubs.remove(name)
    assert reply("status", capsys) == {"ok": True, "state": "unavailable", "missing": [name]}


@pytest.mark.parametrize("version", ["gocryptfs v1.8.0; go-fuse v2.0.3", "garbage", ""])
def test_status_requires_gocryptfs_v2(stubs, capsys, version):
    stubs.env(STUB_VERSION=version)
    assert reply("status", capsys) == {"ok": True, "state": "unavailable", "missing": ["gocryptfs-v2"]}


@pytest.mark.parametrize("path", ["bin:/usr/bin", "bin", "./bin:/usr/bin"])
def test_relative_path_entries_count_as_missing(stubs, capsys, monkeypatch, path):
    # shutil.which returns "bin/gocryptfs" for a relative PATH entry: not found.
    monkeypatch.chdir(stubs.root)
    monkeypatch.setenv("PATH", path)
    assert reply("status", capsys) == {"ok": True, "state": "unavailable", "missing": list(vault.TOOLS)}
    assert reply("create", capsys) == {"ok": False, "error": "missing-tool"}
    assert stubs.calls(skip_version=False) == []


def test_only_a_relative_gocryptfs_is_missing(stubs, capsys, monkeypatch):
    other = stubs.root / "other"
    other.mkdir()
    for name in ("kdialog", "fusermount3"):
        os.rename(stubs.bin / name, other / name)
    monkeypatch.chdir(stubs.root)
    monkeypatch.setenv("PATH", f"bin:{other}")
    assert reply("status", capsys) == {"ok": True, "state": "unavailable", "missing": ["gocryptfs"]}
    assert stubs.calls(skip_version=False) == []


def test_missing_tools_refuse_interactive_operations(stubs, capsys):
    stubs.remove("kdialog")
    for operation in ("create", "unlock", "change-passphrase"):
        assert reply(operation, capsys) == {"ok": False, "error": "missing-tool"}
    assert stubs.calls("gocryptfs") == []


def test_status_absent_then_locked(stubs, capsys):
    assert reply("status", capsys) == {"ok": True, "state": "absent"}
    stubs.make_locked()
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "off"}
    assert [call for call in stubs.calls() if call["tool"] != "qdbus6"] == []


@pytest.mark.parametrize("problem", ["unset", "relative", "group-readable", "symlink", "missing", "file"])
def test_runtime_dir_must_be_absolute_ours_and_private(stubs, capsys, tmp_path, monkeypatch, problem):
    target = tmp_path / "rt"
    if problem == "unset":
        monkeypatch.delenv("XDG_RUNTIME_DIR")
    elif problem == "relative":
        monkeypatch.setenv("XDG_RUNTIME_DIR", "run/user/1000")
    elif problem == "group-readable":
        target.mkdir(mode=0o750)
        target.chmod(0o750)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(target))
    elif problem == "symlink":
        target.mkdir(mode=0o700)
        (tmp_path / "link").symlink_to(target)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "link"))
    elif problem == "missing":
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(target))
    else:
        target.write_text("")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(target))
    for operation in vault.OPERATIONS:
        out = reply(operation, capsys)
        assert out == {"ok": False, "error": "no-runtime-dir"}, operation
    assert stubs.calls() == []


def test_runtime_dir_not_owned_is_refused(stubs, capsys, monkeypatch):
    real = os.getuid()
    monkeypatch.setattr(os, "getuid", lambda: real + 1)
    assert reply("status", capsys) == {"ok": False, "error": "no-runtime-dir"}


# --- create and unlock -----------------------------------------------------------------


def test_create_initialises_and_mounts_with_extpass_argv(stubs, capsys):
    stubs.env(STUB_RUN_EXTPASS=1)
    assert reply("create", capsys) == {"ok": True}
    init, mount = stubs.calls("gocryptfs")
    kdialog = stubs.calls("kdialog")
    kdialog_path = str(stubs.bin / "kdialog")

    # Measured framing: always -init -q; mount with -q -nosyslog; one argv element per
    # -extpass value, never the "-extpass=" form or a single string split on spaces.
    assert without_extpass(init["argv"]) == ["-init", "-q", str(stubs.cipher)]
    assert extpass_values(init["argv"]) == [kdialog_path, "--title", "Hearthwire", "--newpassword", vault.PROMPT_CREATE]
    assert without_extpass(mount["argv"]) == ["-q", "-nosyslog", str(stubs.cipher), str(stubs.mountpoint)]
    assert extpass_values(mount["argv"]) == [kdialog_path, "--title", "Hearthwire", "--password", vault.PROMPT_UNLOCK]
    for call in (init, mount):
        assert call["argv"].count("-extpass") == 5
        assert not any(argument.startswith("-extpass=") for argument in call["argv"])

    # gocryptfs ran kdialog itself, with each argument kept whole.
    assert [call["argv"] for call in kdialog] == [
        ["--title", "Hearthwire", "--newpassword", vault.PROMPT_CREATE],
        ["--title", "Hearthwire", "--password", vault.PROMPT_UNLOCK],
    ]
    assert init["extpass_exit"] == mount["extpass_exit"] == 0
    for call in (init, mount):
        assert call["fds"] == ["/dev/null"] * 3

    assert (stubs.cipher / "gocryptfs.conf").is_file()
    assert stubs.cipher.stat().st_mode & 0o777 == 0o700
    assert mount["mountpoint_mode"] == 0o700
    assert (stubs.mountpoint.parent / "vault.lock").stat().st_mode & 0o777 == 0o600
    assert reply("status", capsys) == {"ok": True, "state": "unlocked", "wallet": "off"}


def test_create_refuses_an_existing_folder(stubs, capsys):
    stubs.make_locked()
    assert reply("create", capsys) == {"ok": False, "error": "exists"}
    assert stubs.calls("gocryptfs") == []


@pytest.mark.parametrize(
    ("code", "error"),
    [(6, "exists"), (9, "cancelled"), (22, "init-failed"), (1, "init-failed"), (24, "init-failed")],
)
def test_create_maps_init_exit_codes_and_leaves_nothing(stubs, capsys, code, error):
    stubs.env(STUB_INIT_EXIT=code)
    assert reply("create", capsys) == {"ok": False, "error": error}
    assert not stubs.cipher.exists()
    assert len(stubs.calls("gocryptfs")) == 1
    assert not stubs.mounted()
    assert reply("status", capsys) == {"ok": True, "state": "absent"}


@pytest.mark.parametrize(
    ("code", "error"),
    [(12, "wrong-passphrase"), (9, "cancelled"), (10, "mount-failed"), (6, "absent"), (11, "absent"),
     (19, "mount-failed"), (22, "mount-failed"), (23, "mount-failed"), (1, "mount-failed"),
     (99, "mount-failed")],
)
def test_unlock_maps_mount_exit_codes(stubs, capsys, code, error):
    stubs.make_locked()
    stubs.env(STUB_MOUNT_EXIT=code)
    assert reply("unlock", capsys) == {"ok": False, "error": error}
    assert not stubs.mounted()
    # The failed attempt still had a 0700 mountpoint; afterwards it is sealed again.
    assert stubs.calls("gocryptfs")[-1]["mountpoint_mode"] == 0o700
    assert stubs.mountpoint_mode() == vault.SEALED_MODE
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "off"}


def test_unlock_exit_19_with_a_mount_present_is_busy(stubs, capsys):
    # 19 = fusermount3 refused; with an entry at our mountpoint afterwards it means
    # "already mounted" (e.g. mounted outside the helper's lock).
    stubs.make_locked()
    stubs.env(STUB_MOUNT_EXIT=19, STUB_MOUNT_ADD_ENTRY=1)
    assert reply("unlock", capsys) == {"ok": False, "error": "busy"}
    assert stubs.calls("fusermount3") == []


def test_exit_code_table_matches_the_measured_contract():
    assert set(vault.EXIT_CODES) == set(vault.EXIT_FALLBACK) == {
        "init", "mount", "passwd", "wallet-mount", "wallet-passwd"}
    assert vault.EXIT_CODES == {
        "init": {6: "exists", 9: "cancelled"},
        "mount": {6: "absent", 9: "cancelled", 10: "mount-failed", 11: "absent", 12: "wrong-passphrase",
                  19: "mount-failed"},
        "passwd": {6: "absent", 9: "cancelled", 11: "absent", 12: "wrong-passphrase"},
        "wallet-mount": {6: "absent", 9: "wallet-failed", 10: "mount-failed", 11: "not-set-up",
                         12: "wallet-mismatch", 19: "mount-failed"},
        "wallet-passwd": {6: "absent", 9: "cancelled", 11: "absent", 12: "wrong-passphrase",
                          24: "wallet-write-failed"},
    }
    assert vault.EXIT_FALLBACK == {"init": "init-failed", "mount": "mount-failed", "passwd": "os-error",
                                   "wallet-mount": "mount-failed", "wallet-passwd": "wallet-write-failed"}
    assert vault.exit_error("mount", 4242) == "mount-failed"
    # Killed by a signal (negative return code): the operation's fallback.
    assert [vault.exit_error(phase, -9) for phase in ("init", "mount", "passwd")] == [
        "init-failed", "mount-failed", "os-error"]
    # Never emitted any more: 22 was never seen, an empty passphrase exits 9.
    assert "empty-passphrase" not in {code for table in vault.EXIT_CODES.values() for code in table.values()}


def test_mountpoint_is_0700_while_mounting_even_after_sealing(stubs, capsys):
    stubs.make_locked()
    stubs.mountpoint.mkdir(parents=True, mode=0o700)
    stubs.mountpoint.chmod(0o500)
    assert reply("unlock", capsys) == {"ok": True}
    assert stubs.calls("gocryptfs")[-1]["mountpoint_mode"] == 0o700
    assert reply("lock", capsys) == {"ok": True}
    assert stubs.mountpoint_mode() == vault.SEALED_MODE
    assert reply("unlock", capsys) == {"ok": True}
    assert stubs.calls("gocryptfs")[-1]["mountpoint_mode"] == 0o700


def test_unlock_absent_and_already_unlocked(stubs, capsys):
    assert reply("unlock", capsys) == {"ok": False, "error": "absent"}
    stubs.make_locked()
    assert reply("unlock", capsys) == {"ok": True}
    assert reply("unlock", capsys) == {"ok": True}
    assert len(stubs.calls("gocryptfs")) == 1


def test_unlock_refuses_a_non_empty_mountpoint(stubs, capsys):
    stubs.make_locked()
    stubs.mountpoint.mkdir(parents=True, mode=0o700)
    (stubs.mountpoint / "leftover").write_text("")
    assert reply("unlock", capsys) == {"ok": False, "error": "mount-failed"}
    assert stubs.calls("gocryptfs") == []


def _leftover(stubs, *names):
    for name in names:
        profile = stubs.mountpoint / "web" / name / "Default"
        profile.mkdir(parents=True, mode=0o700)
        (profile / "Cookies").write_text("leftover")


def test_unlock_clears_leftover_profiles_from_the_bare_mountpoint(stubs, capsys):
    # A chat that kept writing after another widget locked the folder left these in tmpfs.
    stubs.make_locked()
    _leftover(stubs, "applet-1-g0", "applet-22-g3")
    stubs.mountpoint.chmod(vault.SEALED_MODE)
    assert reply("unlock", capsys) == {"ok": True}
    (mount,) = stubs.calls("gocryptfs")
    assert mount["mountpoint_entries"] == []
    assert mount["mountpoint_mode"] == 0o700


def test_create_clears_leftover_profiles_too(stubs, capsys):
    _leftover(stubs, "applet-0-g0")
    assert reply("create", capsys) == {"ok": True}
    assert stubs.calls("gocryptfs")[-1]["mountpoint_entries"] == []


@pytest.mark.parametrize(
    "variant",
    ["top-level-file", "web-other-name", "bad-profile-name", "profile-is-file", "web-is-file",
     "web-symlink", "profile-symlink"],
)
def test_unlock_keeps_unexpected_leftovers_and_refuses(stubs, capsys, tmp_path, variant):
    stubs.make_locked()
    outside = tmp_path / "outside"
    (outside / "applet-1-g0").mkdir(parents=True)
    (outside / "applet-1-g0" / "keep").write_text("keep")
    web = stubs.mountpoint / "web"
    if variant == "web-symlink":
        stubs.mountpoint.mkdir(parents=True, mode=0o700)
        web.symlink_to(outside)
    elif variant == "web-is-file":
        stubs.mountpoint.mkdir(parents=True, mode=0o700)
        web.write_text("")
    else:
        _leftover(stubs, "applet-1-g0")
        if variant == "top-level-file":
            (stubs.mountpoint / "leftover").write_text("")
        elif variant == "web-other-name":
            (web / "notes").mkdir()
        elif variant == "bad-profile-name":
            (web / "applet-01-g0").mkdir()
        elif variant == "profile-is-file":
            (web / "applet-2-g0").write_text("")
        else:
            (web / "applet-2-g0").symlink_to(outside / "applet-1-g0")
    before = sorted(str(path.relative_to(stubs.mountpoint)) for path in stubs.mountpoint.rglob("*"))
    assert reply("unlock", capsys) == {"ok": False, "error": "mount-failed"}
    assert stubs.calls("gocryptfs") == []
    after = sorted(str(path.relative_to(stubs.mountpoint)) for path in stubs.mountpoint.rglob("*"))
    assert after == before
    assert (outside / "applet-1-g0" / "keep").read_text() == "keep"


def test_unlock_refuses_a_symlinked_mountpoint(stubs, capsys, tmp_path):
    stubs.make_locked()
    stubs.mountpoint.parent.mkdir(mode=0o700)
    (tmp_path / "elsewhere").mkdir()
    stubs.mountpoint.symlink_to(tmp_path / "elsewhere")
    assert reply("unlock", capsys) == {"ok": False, "error": "symlink"}
    assert stubs.calls("gocryptfs") == []


def test_symlinked_cipher_parent_is_refused(stubs, capsys, tmp_path):
    stubs.data.mkdir()
    (tmp_path / "evil").mkdir()
    (stubs.data / "hearthwire").symlink_to(tmp_path / "evil")
    assert reply("status", capsys) == {"ok": False, "error": "symlink"}
    assert reply("create", capsys) == {"ok": False, "error": "symlink"}
    assert list((tmp_path / "evil").iterdir()) == []


@pytest.mark.parametrize("content", ["stray-file", "conf-is-directory"])
def test_cipher_dir_without_gocryptfs_conf_is_damaged(stubs, capsys, content):
    stubs.cipher.mkdir(parents=True, mode=0o700)
    if content == "stray-file":
        (stubs.cipher / "abcdef").write_text("ciphertext")
    else:
        (stubs.cipher / "gocryptfs.conf").mkdir()
    assert reply("status", capsys) == {"ok": True, "state": "damaged"}
    for operation in ("create", "unlock", "change-passphrase"):
        assert reply(operation, capsys) == {"ok": False, "error": "damaged"}, operation
    assert stubs.calls("gocryptfs") == [] and stubs.calls("kdialog") == []
    # Delete clears it and Create works again.
    assert reply("destroy", capsys) == {"ok": True}
    assert reply("status", capsys) == {"ok": True, "state": "absent"}
    assert reply("create", capsys) == {"ok": True}


def test_empty_cipher_dir_is_absent_and_can_be_created(stubs, capsys):
    stubs.cipher.mkdir(parents=True, mode=0o700)
    assert reply("status", capsys) == {"ok": True, "state": "absent"}
    assert reply("create", capsys) == {"ok": True}
    assert (stubs.cipher / "gocryptfs.conf").is_file()


# --- mount verification -------------------------------------------------------------------


@pytest.mark.parametrize(
    "variant",
    ["wrong-fstype", "wrong-source", "wrong-user", "allow-other-super", "allow-root-super", "allow-other-mount"],
)
def test_unverified_mount_is_never_trusted(stubs, capsys, tmp_path, variant):
    settings = {
        "wrong-fstype": {"STUB_FSTYPE": "fuse.other"},
        "wrong-source": {"STUB_SOURCE": str(tmp_path / "other-cipher")},
        "wrong-user": {"STUB_UID": os.getuid() + 1},
        "allow-other-super": {"STUB_SUPER": f"rw,user_id={os.getuid()},group_id=0,allow_other"},
        "allow-root-super": {"STUB_SUPER": f"rw,user_id={os.getuid()},group_id=0,allow_root"},
        "allow-other-mount": {"STUB_MOUNT_OPTIONS": "rw,nosuid,allow_other"},
    }[variant]
    stubs.make_locked()
    stubs.env(**settings)
    # Unlock mounts, finds the entry is not ours and unmounts it again.
    assert reply("unlock", capsys) == {"ok": False, "error": "not-verified"}
    assert [call["argv"] for call in stubs.calls("fusermount3")] == [["-u", str(stubs.mountpoint)]]
    assert not stubs.mounted()

    # A foreign entry that stays: nothing uses it, nothing is persisted.
    stubs.env(STUB_FUSERMOUNT_EXIT=1)
    reply("unlock", capsys)
    assert stubs.mounted()
    assert reply("status", capsys) == {"ok": False, "error": "not-verified"}
    out = webdata.run("prepare", "encrypted", 1, generation=0)
    assert out == {"ok": False, "error": "not-verified"}
    assert not (stubs.mountpoint / "web").exists()


def test_same_device_as_parent_is_not_a_mount(stubs, capsys, monkeypatch):
    stubs.make_locked()
    monkeypatch.setattr(vault, "_same_device", lambda root_info, parent_info: True)
    assert reply("unlock", capsys) == {"ok": False, "error": "not-verified"}


def test_verified_mount_with_escaped_spaces(stubs, capsys, tmp_path, monkeypatch):
    runtime = tmp_path / "run time\tdir"
    runtime.mkdir(mode=0o700)
    runtime.chmod(0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    stubs.runtime = runtime
    stubs.make_locked()
    assert reply("unlock", capsys) == {"ok": True}
    assert "\\040" in stubs.mountinfo.read_text()
    assert reply("status", capsys) == {"ok": True, "state": "unlocked", "wallet": "off"}
    assert webdata.run("prepare", "encrypted", 3, generation=1) == {"ok": True}
    assert (stubs.mountpoint / "web" / "applet-3-g1").is_dir()


def test_parse_mountinfo_unescapes_and_splits_optional_fields():
    line = (
        "901 30 0:99 / /run/user/1000/a\\040b\\134c rw,nosuid shared:1 master:2 - "
        "fuse.gocryptfs /home/u/x\\011y rw,user_id=1000,group_id=1000\n"
        "broken line\n"
    )
    (entry,) = vault.parse_mountinfo(line)
    assert entry.mountpoint == "/run/user/1000/a b\\c"
    assert entry.source == "/home/u/x\ty"
    assert entry.fstype == "fuse.gocryptfs"
    assert "user_id=1000" in entry.super_options


# --- stale mounts ----------------------------------------------------------------------------


def _stale(monkeypatch):
    def dead(app):
        raise OSError(errno.ENOTCONN, "Transport endpoint is not connected")

    monkeypatch.setattr(vault, "_open_mount_root", dead)


def test_status_cleans_a_stale_mount_and_reports_locked(stubs, capsys, monkeypatch):
    stubs.make_locked()
    assert reply("unlock", capsys) == {"ok": True}
    _stale(monkeypatch)
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "off"}
    assert [call["argv"] for call in stubs.calls("fusermount3")] == [["-u", str(stubs.mountpoint)]]
    assert stubs.calls("fusermount3")[0]["fds"] == ["/dev/null"] * 3
    assert not stubs.mounted()
    assert stubs.mountpoint_mode() == vault.SEALED_MODE


def test_stale_mount_cleanup_failure(stubs, capsys, monkeypatch):
    stubs.make_locked()
    reply("unlock", capsys)
    _stale(monkeypatch)
    stubs.env(STUB_FUSERMOUNT_EXIT=1)
    assert reply("status", capsys) == {"ok": False, "error": "stale-mount"}
    assert reply("unlock", capsys) == {"ok": False, "error": "stale-mount"}
    assert webdata.run("prepare", "encrypted", 1, generation=0) == {"ok": False, "error": "not-verified"}


def test_unlock_after_stale_cleanup_mounts_again(stubs, capsys, monkeypatch):
    stubs.make_locked()
    reply("unlock", capsys)
    original = vault._open_mount_root
    _stale(monkeypatch)
    calls = []

    def once_dead(app):
        calls.append(app)
        if len(calls) == 1:
            raise OSError(errno.ENOTCONN, "stale")
        return original(app)

    monkeypatch.setattr(vault, "_open_mount_root", once_dead)
    assert reply("unlock", capsys) == {"ok": True}
    assert len(stubs.calls("gocryptfs")) == 2
    assert len(stubs.calls("fusermount3")) == 1


# --- lock ----------------------------------------------------------------------------------------


def test_lock_unmounts_and_is_idempotent(stubs, capsys):
    assert reply("lock", capsys) == {"ok": True}
    stubs.make_locked()
    reply("unlock", capsys)
    assert reply("lock", capsys) == {"ok": True}
    assert not stubs.mounted()
    assert stubs.mountpoint_mode() == vault.SEALED_MODE
    assert reply("lock", capsys) == {"ok": True}
    (call,) = stubs.calls("fusermount3")
    assert call["argv"] == ["-u", str(stubs.mountpoint)]
    assert call["fds"] == ["/dev/null"] * 3
    assert reply("status", capsys) == {"ok": True, "state": "locked", "wallet": "off"}


def test_lock_reports_busy_when_unmount_keeps_failing(stubs, capsys):
    stubs.make_locked()
    reply("unlock", capsys)
    stubs.env(STUB_FUSERMOUNT_EXIT=1)
    assert reply("lock", capsys) == {"ok": False, "error": "busy"}
    calls = stubs.calls("fusermount3")
    assert len(calls) == 1 + len(vault.UNMOUNT_RETRY_DELAYS)
    # Plain unmount only: never lazy (-z), never forced.
    assert all(call["argv"] == ["-u", str(stubs.mountpoint)] for call in calls)
    assert reply("status", capsys) == {"ok": True, "state": "unlocked", "wallet": "off"}
    assert stubs.mountpoint_mode() == 0o700


def test_lock_retries_a_briefly_busy_unmount(stubs, capsys, monkeypatch):
    slept = []
    monkeypatch.setattr(vault, "UNMOUNT_RETRY_DELAYS", (0.0125, 0.0375))
    stubs.make_locked()
    reply("unlock", capsys)
    real_sleep = time.sleep
    monkeypatch.setattr(vault.time, "sleep", lambda seconds: (slept.append(seconds), real_sleep(seconds)))
    stubs.env(STUB_FUSERMOUNT_FAILS=1)
    assert reply("lock", capsys) == {"ok": True}
    assert len(stubs.calls("fusermount3")) == 2
    # subprocess itself also sleeps while waiting; only the retry delays matter here.
    assert [seconds for seconds in slept if seconds in vault.UNMOUNT_RETRY_DELAYS] == [0.0125]
    assert not stubs.mounted()


# --- change passphrase --------------------------------------------------------------------------


def _passwd_calls(stubs):
    (passwd,) = stubs.calls("gocryptfs")
    return passwd, stubs.calls("kdialog"), stubs.ended("kdialog")


def test_change_passphrase_runs_old_dialog_via_extpass_then_new_dialog_into_stdin(stubs, capsys):
    stubs.make_locked()
    assert reply("change-passphrase", capsys) == {"ok": True}
    passwd, dialogs, ended = _passwd_calls(stubs)
    marker = str(stubs.mountpoint.parent / vault.PASSWD_MARKER)
    kdialog_path = str(stubs.bin / "kdialog")

    # gocryptfs -passwd -q <extpass relay ...> <cipher>; the relay runs the old dialog.
    assert without_extpass(passwd["argv"]) == ["-passwd", "-q", str(stubs.cipher)]
    assert extpass_values(passwd["argv"]) == [
        sys.executable, vault.RELAY, marker,
        kdialog_path, "--title", "Hearthwire", "--password", vault.PROMPT_CURRENT,
    ]
    assert passwd["extpass_exit"] == 0 and passwd["extpass_got_answer"]
    assert passwd["new_received"] is True
    # stdin is the pipe, stdout/stderr /dev/null.
    assert passwd["fds"][0].startswith("pipe:")
    assert passwd["fds"][1:] == ["/dev/null", "/dev/null"]

    old, new = dialogs
    assert old["argv"] == ["--title", "Hearthwire", "--password", vault.PROMPT_CURRENT]
    assert new["argv"] == ["--title", "Hearthwire", "--newpassword", vault.PROMPT_NEW]
    # Old dialog: stdin /dev/null, stdout = gocryptfs's extpass pipe (not its stdin).
    assert old["fds"][0] == old["fds"][2] == "/dev/null"
    assert old["fds"][1].startswith("pipe:") and old["fds"][1] != passwd["fds"][0]
    # New dialog: stdout is exactly gocryptfs's stdin pipe.
    assert new["fds"] == ["/dev/null", passwd["fds"][0], "/dev/null"]

    # Ordering: the new dialog starts only after the old one exited, and gocryptfs
    # read its stdin only after the new dialog started.
    old_end = next(record["end_ns"] for record in ended if record["argv"] == old["argv"])
    assert new["start_ns"] > old_end
    assert passwd["stdin_read_ns"] > new["start_ns"]
    assert not (stubs.mountpoint.parent / vault.PASSWD_MARKER).exists()


def test_change_passphrase_runs_gocryptfs_and_the_relay_with_a_clean_python_env(stubs, capsys, monkeypatch):
    # gocryptfs runs the relay as a plain script (no -I): no inherited PYTHON* variable.
    for key, value in {"PYTHONPATH": "/nonexistent/evil", "PYTHONUSERBASE": "/nonexistent/user",
                       "PYTHONSAFEPATH": "", "PYTHONNOUSERSITE": "", "PYTHONWARNINGS": "ignore"}.items():
        monkeypatch.setenv(key, value)
    stubs.make_locked()
    assert reply("change-passphrase", capsys) == {"ok": True}
    passwd, dialogs, _ = _passwd_calls(stubs)
    assert passwd["python_env"] == {"PYTHONNOUSERSITE": "1", "PYTHONSAFEPATH": "1"}
    # The old-passphrase dialog runs under the relay, so it inherited the same.
    assert dialogs[0]["python_env"] == {"PYTHONNOUSERSITE": "1", "PYTHONSAFEPATH": "1"}


def test_relay_environment_drops_every_python_variable():
    environ = {"HOME": "/h", "PATH": "/bin", "PYTHONPATH": "/x", "PYTHONHOME": "/y", "PYTHONSTARTUP": "/z",
               "PYTHONSAFEPATH": "0", "PYTHONINSPECT": "1"}
    assert vault.relay_environment(environ) == {
        "HOME": "/h", "PATH": "/bin", "PYTHONNOUSERSITE": "1", "PYTHONSAFEPATH": "1"}
    assert environ["PYTHONPATH"] == "/x"


def test_change_passphrase_wrong_old_never_opens_the_new_dialog(stubs, capsys):
    stubs.make_locked()
    stubs.env(STUB_PASSWD_EXIT=12)
    assert reply("change-passphrase", capsys) == {"ok": False, "error": "wrong-passphrase"}
    passwd, dialogs, _ = _passwd_calls(stubs)
    assert [call["argv"][2] for call in dialogs] == ["--password"]
    assert "stdin_read_ns" not in passwd


def test_change_passphrase_wrong_old_after_the_grace_closes_the_new_dialog(stubs, capsys, monkeypatch):
    # gocryptfs is slow to reject the old passphrase: the new dialog is already open
    # and must be closed again, without waiting for the user.
    monkeypatch.setattr(vault, "PASSWD_GRACE", 0.0)
    stubs.make_locked()
    stubs.env(STUB_PASSWD_EXIT=12, STUB_PASSWD_DELAY=1.5, STUB_KDIALOG_NEW_SLEEP=60)
    started = time.monotonic()
    assert reply("change-passphrase", capsys) == {"ok": False, "error": "wrong-passphrase"}
    assert time.monotonic() - started < 30
    _, dialogs, ended = _passwd_calls(stubs)
    assert [call["argv"][2] for call in dialogs] == ["--password", "--newpassword"]
    assert [record["argv"][2] for record in ended] == ["--password"]


@pytest.mark.parametrize(
    ("settings", "error", "dialogs"),
    [
        ({"STUB_KDIALOG_EXIT": 1}, "cancelled", ["--password"]),
        ({"STUB_KDIALOG_NEW_EXIT": 1}, "cancelled", ["--password", "--newpassword"]),
        ({"STUB_KDIALOG_NEW_EMPTY": 1}, "cancelled", ["--password", "--newpassword"]),
        ({"STUB_PASSWD_EXIT": 6}, "absent", []),
        ({"STUB_PASSWD_EXIT": 11}, "absent", []),
        ({"STUB_PASSWD_EXIT": 1}, "os-error", ["--password", "--newpassword"]),
        ({"STUB_PASSWD_EXIT": 22}, "os-error", ["--password", "--newpassword"]),
    ],
)
def test_change_passphrase_maps_exit_codes(stubs, capsys, settings, error, dialogs):
    stubs.make_locked()
    stubs.env(**settings)
    assert reply("change-passphrase", capsys) == {"ok": False, "error": error}
    _, calls, _ = _passwd_calls(stubs)
    assert [call["argv"][2] for call in calls] == dialogs
    assert not (stubs.mountpoint.parent / vault.PASSWD_MARKER).exists()


def test_change_passphrase_never_reads_a_passphrase(stubs, capsys, monkeypatch):
    seen = []
    real_read = os.read

    def spy_read(fd, size):
        data = real_read(fd, size)
        seen.append(data)
        return data

    monkeypatch.setattr(os, "read", spy_read)
    stubs.make_locked()
    assert reply("change-passphrase", capsys) == {"ok": True}
    assert not any(b"stub-passphrase" in data for data in seen)
    for call in stubs.calls(skip_version=False):
        assert not any("stub-passphrase" in argument for argument in call["argv"])


def test_change_passphrase_ignores_a_stale_marker(stubs, capsys):
    stubs.make_locked()
    stubs.mountpoint.parent.mkdir(mode=0o700)
    (stubs.mountpoint.parent / vault.PASSWD_MARKER).write_text("0")
    (stubs.mountpoint.parent / (vault.PASSWD_MARKER + ".tmp")).write_text("0")
    stubs.env(STUB_KDIALOG_EXIT=1)
    assert reply("change-passphrase", capsys) == {"ok": False, "error": "cancelled"}
    _, dialogs, _ = _passwd_calls(stubs)
    assert len(dialogs) == 1


def test_change_passphrase_requires_a_locked_folder(stubs, capsys):
    assert reply("change-passphrase", capsys) == {"ok": False, "error": "absent"}
    stubs.make_locked()
    reply("unlock", capsys)
    assert reply("change-passphrase", capsys) == {"ok": False, "error": "not-locked"}
    assert all("-passwd" not in call["argv"] for call in stubs.calls("gocryptfs"))


# --- extpass relay -------------------------------------------------------------------------------


def _relay(tmp_path, marker, *dialog):
    return subprocess.run(
        [sys.executable, vault.RELAY, str(marker), *dialog],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=False,
    )


@pytest.mark.parametrize("code", [0, 1, 7])
def test_relay_passes_stdout_through_and_publishes_only_the_status(tmp_path, code):
    dialog = tmp_path / "dialog"
    dialog.write_text(f"#!/bin/sh\nprintf 'secret\\n'\nexit {code}\n")
    dialog.chmod(0o755)
    marker = tmp_path / "marker"
    completed = _relay(tmp_path, marker, str(dialog), "--title", "x")
    assert completed.returncode == code
    assert completed.stdout == b"secret\n"
    assert completed.stderr == b""
    assert marker.read_text() == str(code)
    assert stat.S_IMODE(marker.stat().st_mode) == 0o600
    assert not (tmp_path / "marker.tmp").exists()


def test_relay_fails_when_it_cannot_publish(tmp_path):
    marker = tmp_path / "marker"
    (tmp_path / "marker.tmp").symlink_to(tmp_path / "elsewhere")
    completed = _relay(tmp_path, marker, "/bin/true")
    assert completed.returncode == 1
    assert not marker.exists() and not (tmp_path / "elsewhere").exists()


@pytest.mark.parametrize("argv", [[], ["relative", "/bin/true"], ["/m"], ["/m", "relative"]])
def test_relay_refuses_bad_arguments(tmp_path, argv):
    completed = subprocess.run([sys.executable, vault.RELAY, *argv], stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, timeout=60, check=False)
    assert completed.returncode == 2


def test_relay_source_imports_only_os_and_sys():
    code = Path(vault.RELAY).read_text(encoding="utf-8")
    assert re.findall(r"^\s*(?:from|import)\s+([\w.]+)", code, re.MULTILINE) == ["os", "sys"]
    for pattern in (r"\bos\.read\b", r"\bstdin\b", r"\bsubprocess\b", r"(?<![\w.])print\s*\("):
        assert not re.search(pattern, code), pattern


# --- destroy ---------------------------------------------------------------------------------------


def test_destroy_removes_cipher_dir_and_mountpoint(stubs, capsys, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("")
    stubs.make_locked()
    (stubs.cipher / "link").symlink_to(outside)
    reply("unlock", capsys)
    assert reply("destroy", capsys) == {"ok": False, "error": "not-locked"}
    reply("lock", capsys)
    assert reply("destroy", capsys) == {"ok": True}
    assert not stubs.cipher.exists()
    assert not stubs.mountpoint.exists()
    assert (outside / "keep").exists()
    assert reply("status", capsys) == {"ok": True, "state": "absent"}
    assert reply("destroy", capsys) == {"ok": True}


def test_destroy_needs_symlink_safe_rmtree(stubs, capsys, monkeypatch):
    import shutil

    stubs.make_locked()
    monkeypatch.setattr(shutil.rmtree, "avoids_symlink_attacks", False)
    assert reply("destroy", capsys) == {"ok": False, "error": "os-error"}
    assert stubs.cipher.exists()


# --- locking ---------------------------------------------------------------------------------------


def test_vault_lock_serialises_instances(stubs, capsys):
    app = stubs.mountpoint.parent
    app.mkdir(mode=0o700)
    holder = os.open(app / "vault.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX)
        for operation in ("status", "lock", "destroy"):
            assert reply(operation, capsys) == {"ok": False, "error": "busy"}
        assert webdata.run("prepare", "encrypted", 1, generation=0) == {"ok": False, "error": "busy"}
    finally:
        os.close(holder)
    assert reply("status", capsys) == {"ok": True, "state": "absent"}


def test_lock_file_symlink_is_refused(stubs, capsys, tmp_path):
    app = stubs.mountpoint.parent
    app.mkdir(mode=0o700)
    (app / "vault.lock").symlink_to(tmp_path / "target")
    assert reply("status", capsys) == {"ok": False, "error": "symlink"}
    assert not (tmp_path / "target").exists()


# --- children and output -------------------------------------------------------------------------


def test_children_get_argv_lists_no_shell_and_devnull(stubs, capsys, monkeypatch):
    seen = []
    real_run, real_popen = subprocess.run, subprocess.Popen

    def spy_run(*args, **kwargs):
        seen.append(("run", args, kwargs))
        return real_run(*args, **kwargs)

    class SpyPopen(real_popen):
        def __init__(self, *args, **kwargs):
            seen.append(("popen", args, kwargs))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy_run)
    monkeypatch.setattr(subprocess, "Popen", SpyPopen)
    for operation in ("status", "create", "lock", "unlock", "lock", "change-passphrase", "add-key",
                      "status", "remove-key", "add-key", "destroy"):
        reply(operation, capsys)
    assert seen
    tools = set()
    for kind, args, kwargs in seen:
        argv = args[0]
        tool = Path(argv[0]).name
        tools.add(tool)
        assert isinstance(argv, list) and all(isinstance(item, str) for item in argv)
        assert os.path.isabs(argv[0])
        assert not kwargs.get("shell")
        assert "capture_output" not in kwargs
        assert kwargs["stderr"] is subprocess.DEVNULL
        assert kwargs.get("close_fds", True) is True
        if tool == "qdbus6":
            # walletkey._query: the one captured answer (booleans, names, a handle).
            assert kwargs["stdout"] is subprocess.PIPE and kwargs["stdin"] is subprocess.DEVNULL
            continue
        assert kwargs["stdin"] is subprocess.DEVNULL or isinstance(kwargs["stdin"], int)
        assert kwargs["stdout"] is subprocess.DEVNULL or isinstance(kwargs["stdout"], int)
        assert kwargs["stdin"] is not subprocess.PIPE and kwargs["stdout"] is not subprocess.PIPE
        # The only non-/dev/null streams: -passwd's stdin pipe, the new-passphrase
        # dialog writing into it, the version line, and the wallet key's pipes
        # (openssl -> kwallet-query -w; kwallet-query -r -> gocryptfs -passwd -config).
        if kwargs["stdin"] is not subprocess.DEVNULL:
            assert (argv[1:3] == ["-passwd", "-q"] or (tool == "kwallet-query" and "--write-password" in argv))
        if kwargs["stdout"] is not subprocess.DEVNULL:
            assert argv[1:] == ["-version"] or (
                tool == "kdialog" and argv[1:] == vault.new_passphrase_argv("kdialog")[1:]
            ) or (tool == "openssl" and argv[1:] == ["rand", "-hex", "32"]) or (
                tool == "kwallet-query" and "--read-password" in argv)
    assert {"gocryptfs", "kdialog", "fusermount3", "kwallet-query", "qdbus6", "openssl"} <= tools


def test_every_gocryptfs_and_fusermount_stream_is_devnull(stubs, capsys, monkeypatch):
    stubs.env(STUB_RUN_EXTPASS=1)
    for operation in ("create", "lock", "unlock", "lock", "change-passphrase", "status"):
        reply(operation, capsys)
    assert reply("unlock", capsys) == {"ok": True}
    _stale(monkeypatch)
    reply("status", capsys)
    calls = stubs.calls("gocryptfs") + stubs.calls("fusermount3")
    assert {call["argv"][0] if call["argv"] else "" for call in stubs.calls("fusermount3")} == {"-u"}
    assert len(calls) >= 8
    for call in calls:
        if "-passwd" in call["argv"]:
            assert call["fds"][0].startswith("pipe:") and call["fds"][1:] == ["/dev/null"] * 2
        else:
            assert call["fds"] == ["/dev/null"] * 3, call["argv"]


def test_no_forbidden_flag_ever_reaches_a_child(stubs, capsys):
    stubs.env(STUB_RUN_EXTPASS=1)
    for operation in ("create", "lock", "change-passphrase", "unlock", "lock", "destroy"):
        reply(operation, capsys)
    forbidden = re.compile(r"^--?(passfile|masterkey|allow_other|allow_root|plaintextnames|o)(=|$)")
    for call in stubs.calls(skip_version=False):
        assert not any(argument.startswith("-extpass=") for argument in call["argv"])
        for argument in call["argv"]:
            assert not forbidden.match(argument), call
            assert "allow_" not in argument
            assert "-nonempty" != argument and "-z" != argument


GOCRYPTFS = "/usr/bin/gocryptfs"


@pytest.mark.parametrize(
    "argv",
    [["-passfile", "/x"], ["--masterkey=x", "/x"], ["-allow_other", "/x"], ["-o", "/x"], ["-plaintextnames", "/x"],
     ["-ko=allow_root", "/x"], ["-extpass", "-X", "/x"], ["-extpass", "-o", "/x"], ["/x", "-extpass"],
     ["-extpass=/bin/kdialog", "-extpass=-o allow_other", "/x"],
     # Allow-list proofs: a value after a flag is never a way around the check.
     ["-ko", "allow_other", "/c", "/m"], ["-q", "-ko", "allow_other", "/c", "/m"],
     ["-zerokey", "/c", "/m"], ["-fsname", "x", "/c", "/m"], ["-fsname", "/x", "/c"],
     ["-config", "/x", "/c", "/m"], ["-fusedebug", "/c", "/m"], ["-q", "-nonempty", "/c", "/m"],
     ["-init", "-q", "-nosyslog", "/c"], ["-init", "-passwd", "/c"], ["-passwd", "-nosyslog", "/c"],
     ["-version", "-q"], ["--version"], ["-q", "/c", "/m/allow_other"], ["-q", "allow_other", "/m"],
     ["-q", "/c"], ["-q", "/c", "/m", "/x"], ["-q", "c", "/m"], ["-init", "-q"], ["-init", "/c", "/m"]],
)
def test_argv_guard_refuses_forbidden_flags(argv):
    with pytest.raises(webdata.HelperError):
        vault._check_argv([GOCRYPTFS, *argv])


@pytest.mark.parametrize(
    "argv",
    [["g", "-q", "/c", "/m"], ["/bin/sh", "-c", "x"], ["/usr/bin/python3", "/x"],
     ["/bin/fusermount3", "-u", "/m", "-z"], ["/bin/fusermount3", "-uz", "/m"], ["/bin/fusermount3", "-u", "m"],
     ["/bin/fusermount3", "-u", "/m", "-o", "allow_other"], ["/bin/fusermount3", "-u", "/run/allow_other/m"],
     ["/bin/kdialog", "--title", "Hearthwire", "--password", vault.PROMPT_NEW],
     ["/bin/kdialog", "--title", "Hearthwire", "--newpassword", vault.PROMPT_NEW, "--allow_other"]],
)
def test_argv_guard_refuses_other_tools_and_shapes(argv):
    with pytest.raises(webdata.HelperError):
        vault._check_argv(argv)


def test_argv_guard_accepts_exactly_the_contract_argv():
    kdialog = "/usr/bin/kdialog"
    for argv in (
        [GOCRYPTFS, *vault.VERSION_ARGS],
        vault.init_argv(GOCRYPTFS, kdialog, "/data/hearthwire/vault"),
        vault.mount_argv(GOCRYPTFS, kdialog, "/data/hearthwire/vault", "/run/hearthwire/vault"),
        vault.passwd_argv(GOCRYPTFS, "/usr/bin/python3", "/run/hearthwire/passwd.status", kdialog,
                          "/data/hearthwire/vault"),
        vault.unmount_argv("/usr/bin/fusermount3", "/run/hearthwire/vault"),
        vault.new_passphrase_argv(kdialog),
    ):
        vault._check_argv(argv)
    flags = {argument for argv in (
        vault.init_argv(GOCRYPTFS, kdialog, "/c"), vault.mount_argv(GOCRYPTFS, kdialog, "/c", "/m"),
        vault.passwd_argv(GOCRYPTFS, "/p", "/m", kdialog, "/c"),
    ) for argument in without_extpass(argv[1:]) if argument.startswith("-")}
    assert flags == {"-init", "-passwd", "-q", "-nosyslog"}
    assert set().union(*vault.PHASE_FLAGS.values()) == {
        "-init", "-passwd", "-q", "-nosyslog", "-extpass", "-config"}
    assert "-config" not in vault.PHASE_FLAGS["init"]
    # The wallet shapes pass only with their own slot path.
    slot = "/data/hearthwire/vault-keys/wallet.conf"
    mount = vault.wallet_mount_argv(GOCRYPTFS, "/usr/bin/kwallet-query", "kdewallet", slot,
                                    "/data/hearthwire/vault", "/run/hearthwire/vault")
    passwd = vault.wallet_passwd_argv(GOCRYPTFS, kdialog, slot + ".new", "/data/hearthwire/vault")
    vault._check_argv(mount, config=slot)
    vault._check_argv(passwd, config=slot + ".new")
    for argv, config in ((mount, None), (mount, slot + ".new"), (passwd, slot), (passwd, None)):
        with pytest.raises(webdata.HelperError):
            vault._check_argv(argv, config=config)


def test_argv_guard_allows_paths_and_prompts():
    vault._check_argv([GOCRYPTFS, "-q", "-extpass", "/bin/kdialog", "-extpass", "--title",
                       "-extpass", "Mind the -o allow_other", "/home/u/x", "/run/u/m"])


def test_argv_guard_refuses_allow_outside_extpass_values():
    # Even a path: "allow_" may only appear inside a dialog argument.
    with pytest.raises(webdata.HelperError):
        vault._check_argv([GOCRYPTFS, "-q", "-extpass", "/bin/kdialog", "/home/allow_other/x", "/run/u/m"])


def test_extpass_values_may_not_start_with_a_single_dash():
    # gocryptfs would turn "-X" into "--X" (dash duplication).
    with pytest.raises(webdata.HelperError):
        vault.extpass_args("/bin/kdialog", "-X")
    assert vault.extpass_args("/bin/kdialog", "--password", "a b") == [
        "-extpass", "/bin/kdialog", "-extpass", "--password", "-extpass", "a b"]
    for prompt in (vault.TITLE, vault.PROMPT_CREATE, vault.PROMPT_UNLOCK, vault.PROMPT_CURRENT, vault.PROMPT_NEW):
        assert not prompt.startswith("-")


def test_output_never_contains_a_path(stubs, capsys, tmp_path, monkeypatch):
    outputs = []
    stubs.env(STUB_RUN_EXTPASS=1)
    for operation in ("status", "create", "status", "unlock", "lock", "unlock", "status", "lock",
                      "change-passphrase", "destroy", "status"):
        assert cli.main(vault_argv(operation)) == 0
        captured = capsys.readouterr()
        outputs.append(captured.out + captured.err)
    _stale(monkeypatch)
    stubs.env(STUB_FUSERMOUNT_EXIT=1)
    for operation in vault.OPERATIONS:
        assert cli.main(vault_argv(operation)) == 0
        captured = capsys.readouterr()
        outputs.append(captured.out + captured.err)
    text = "".join(outputs)
    assert str(tmp_path) not in text
    assert "/" not in text
    assert "stub-passphrase" not in text


def test_unexpected_exception_is_a_bare_code(stubs, capsys, monkeypatch):
    def boom(environ=None):
        raise RuntimeError(f"secret path {stubs.cipher}")

    monkeypatch.setattr(vault, "_HANDLERS", {**vault._HANDLERS, "status": boom})
    assert reply("status", capsys) == {"ok": False, "error": "os-error"}


def test_cli_subprocess_prints_one_json_object(stubs, tmp_path):
    src = Path(__file__).resolve().parent.parent / "src"
    env = {**os.environ, "PYTHONPATH": str(src), "PYTHONDONTWRITEBYTECODE": "1"}
    completed = subprocess.run(
        [sys.executable, "-m", "hearthwire", "--vault", "status"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=60, check=False,
    )
    assert completed.returncode == 0
    assert completed.stderr == ""
    assert completed.stdout == '{"ok":true,"state":"absent"}\n'


@pytest.mark.parametrize(
    "argv",
    [
        ["--vault"],
        ["--vault", "open"],
        ["--vault", "status", "--applet", "1"],
        ["--vault", "status", "--catalog"],
        ["--vault", "status", "--web-data", "remove", "--store", "encrypted", "--applet", "1"],
        ["--vault", "status", "--providers", "claude"],
    ],
)
def test_vault_cli_rejects_bad_arguments(stubs, capsys, argv):
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 2
    assert capsys.readouterr().out == ""
    assert stubs.calls(skip_version=False) == []


# --- static rules --------------------------------------------------------------------------------


def test_vault_source_never_captures_output_uses_a_shell_or_prints():
    code = SOURCE.read_text(encoding="utf-8")
    for pattern in (r"\bcapture_output\b", r"\bPIPE\b", r"\bshell\s*=", r"(?<![\w.])print\s*\(",
                    r"\bcheck_output\b", r"\bos\.system\b", r"\bos\.popen\b", r"\bgetoutput\b"):
        assert not re.search(pattern, code), pattern
    for flag in ("-passfile", "-masterkey", "-allow_other", "-allow_root", "-plaintextnames"):
        assert flag not in code, flag


def test_vault_and_webdata_use_only_the_standard_library():
    allowed = set(sys.stdlib_module_names) | {"hearthwire"}
    for path in (SOURCE, Path(webdata.__file__)):
        code = path.read_text(encoding="utf-8")
        modules = re.findall(r"^\s*(?:from|import)\s+([\w.]+)", code, re.MULTILINE)
        external = [name for name in modules if not name.startswith(".") and name.split(".")[0] not in allowed]
        assert not external, (path.name, external)


# >>> legacy-migration: D5 and the helpers the installer's migration uses (plan R2) -----------------


def _old_data(stubs):
    old = Path(os.path.realpath(stubs.data)) / "hearthside"
    old.mkdir(parents=True)
    return old


@pytest.mark.parametrize("operation", ["create", "unlock"])
def test_setup_and_unlock_refuse_while_old_data_waits(stubs, capsys, operation):
    if operation == "unlock":
        stubs.make_locked()
    _old_data(stubs)
    assert reply(operation, capsys) == {"ok": False, "error": "legacy-data"}
    assert [call for call in stubs.calls() if call["tool"] in ("gocryptfs", "kdialog")] == []
    assert not stubs.mounted()


def test_status_lock_and_destroy_still_work_while_old_data_waits(stubs, capsys):
    stubs.make_locked()
    _old_data(stubs)
    assert reply("status", capsys)["state"] == "locked"
    assert reply("lock", capsys) == {"ok": True}


def test_purge_refuses_while_old_data_waits(stubs, capsys, monkeypatch, tmp_path):
    stubs.make_locked()
    old = _old_data(stubs)
    monkeypatch.setattr(vault, "DEFAULT_RUNTIME", str(tmp_path / "none-{uid}"))
    assert cli.main(["--web-data", "purge"]) == 0
    assert capsys.readouterr().out == '{"ok":false,"error":"legacy-data"}\n'
    assert stubs.cipher.is_dir() and old.is_dir()


def test_mounted_any_checks_every_name_and_runtime(stubs, monkeypatch, tmp_path):
    monkeypatch.setattr(vault, "DEFAULT_RUNTIME", str(tmp_path / "none-{uid}"))
    runtime = Path(os.path.realpath(stubs.runtime))
    data = Path(os.path.realpath(stubs.data))
    assert vault.mounted_any(None, ("hearthside", "hearthwire")) is False
    with open(stubs.mountinfo, "a") as handle:
        handle.write(f"901 30 0:99 / {runtime}/hearthside/vault rw - fuse.x src rw\n")
    assert vault.mounted_any() is False
    assert vault.mounted_any(None, ("hearthside", "hearthwire")) is True
    stubs.mountinfo.write_text(BASE_MOUNTINFO + f"902 30 0:98 / /elsewhere rw - fuse.gocryptfs {data}/hearthside/vault rw\n")
    assert vault.mounted_any(None, ("hearthside",)) is True


def test_vault_lock_of_another_name_is_a_separate_lock(stubs):
    ctx = vault.context(find_tools=False)
    with vault.vault_lock(ctx, app_dir="hearthside"):
        with vault.vault_lock(ctx):
            pass
        with pytest.raises(webdata.HelperError) as raised:
            with vault.vault_lock(ctx, app_dir="hearthside"):
                pass
    assert raised.value.code == "busy"
    assert stat.S_IMODE(os.lstat(Path(os.path.realpath(stubs.runtime)) / "hearthside").st_mode) == 0o700
# <<< legacy-migration
