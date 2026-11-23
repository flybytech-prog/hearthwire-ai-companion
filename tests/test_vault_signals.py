"""Task 011c: a stopped helper run (SIGTERM, SIGHUP, SIGINT) stops the children it started.

Each case runs the helper as a process of its own (``python -I``, an environment
built from nothing: PATH is the stub folder, HOME and the XDG folders are under
tmp_path, no bus and no display). It waits until a stub dialog is open,
signals the helper and then checks the fixed reply and exit status. It also
checks that no stub is left running and that nothing is left mounted or
half-made. The stubs only record their pids and sleep; nothing prompts. The
stub gocryptfs works like the real one: the process the helper starts forks
a worker. The worker runs the dialog and, once mounted, stays as the daemon
in the same process group. Proofs run the same cases with the handler or one
cleanup step taken out.
"""

import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from hearthwire.core import termination, vault
from test_vault import BASE_MOUNTINFO, WALLET_STUB

SRC = Path(vault.__file__).resolve().parents[2]
main_thread_only = pytest.mark.skipif(threading.current_thread() is not threading.main_thread(),
                                      reason="signal handlers need the main thread")
UID, GID = os.getuid(), os.getgid()

STUB = r'''#!PYTHON
import os, signal, subprocess, sys, time

tool = os.path.basename(sys.argv[0])
args = sys.argv[1:]
env = os.environ
PIDS = env["STUB_PIDS"]


def note(role):
    """Record this process (pid and kernel start time) so the test can prove it is gone."""
    with open("/proc/self/stat") as handle:
        start = handle.read().rsplit(")", 1)[1].split()[19]
    with open(os.path.join(PIDS, f"{role}-{os.getpid()}"), "w") as handle:
        handle.write(start)


def escape(path):
    return path.replace("\\", "\\134").replace(" ", "\\040").replace("\t", "\\011").replace("\n", "\\012")


def unmount(mountpoint):
    with open(env["STUB_MOUNTINFO"]) as handle:
        lines = handle.read().splitlines(keepends=True)
    with open(env["STUB_MOUNTINFO"], "w") as handle:
        handle.writelines(line for line in lines if line.split(" ")[4] != escape(mountpoint))


def mounted(mountpoint):
    with open(env["STUB_MOUNTINFO"]) as handle:
        return any(line.split(" ")[4] == escape(mountpoint) for line in handle if line.strip())


if tool in ("kdialog", "hearthwire-askpass"):
    if "STUB_DIALOG_IGNORE_TERM" in env:
        # Only SIGKILL ends it: a stop then takes the whole grace time.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    note("dialog")
    if "--newpassword" in args and "STUB_NEWDIALOG_SLEEP" in env:
        note("newdialog")
        time.sleep(float(env["STUB_NEWDIALOG_SLEEP"]))
    else:
        time.sleep(float(env.get("STUB_DIALOG_SLEEP", "60")))
    code = int(env.get("STUB_DIALOG_EXIT", "0"))
    if code == 0:
        print("stub-passphrase", flush=True)
    if "--newpassword" in args:
        note("newdialog-end")
    sys.exit(code)
if tool == "fusermount3":
    unmount(args[1])
    sys.exit(0)
if args == ["-version"]:
    print("gocryptfs v2.6.1; go-fuse [vendored]; 2025-08-11 go1.24.6 linux/amd64")
    sys.exit(0)

extpass, positional, index = [], [], 0
while index < len(args):
    if args[index] == "-extpass":
        extpass.append(args[index + 1])
        index += 2
        continue
    if args[index] == "-config":
        index += 2
        continue
    if not args[index].startswith("-"):
        positional.append(args[index])
    index += 1
phase = "init" if "-init" in args else "passwd" if "-passwd" in args else "mount"

if "STUB_READY" not in env:
    # The process the helper started: fork the worker (same stdin, same process
    # group), wait until it mounted or exited, then exit like gocryptfs.
    note("gocryptfs")
    ready = os.path.join(PIDS, f"ready-{os.getpid()}")
    worker = subprocess.Popen([sys.argv[0], *args], env={**env, "STUB_READY": ready})
    while worker.poll() is None and not os.path.exists(ready):
        time.sleep(0.02)
    if os.path.exists(ready):
        time.sleep(float(env.get("STUB_PARENT_HOLD", "0")))
        sys.exit(0)
    sys.exit(worker.returncode)

note("worker")
answer = subprocess.run(extpass, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
if answer.returncode != 0 or not answer.stdout.strip():
    sys.exit(9)
if phase == "init":
    # Like gocryptfs: the config goes to a .tmp file first, then is renamed.
    conf = os.path.join(positional[0], "gocryptfs.conf")
    with open(conf + ".tmp", "w") as handle:
        handle.write("{}")
    time.sleep(float(env.get("STUB_INIT_HOLD", "0")))
    os.rename(conf + ".tmp", conf)
    sys.exit(0)
if phase == "passwd":
    line = sys.stdin.readline()
    time.sleep(float(env.get("STUB_PASSWD_HOLD", "0")))
    sys.exit(0 if line.strip() else 9)
cipher, mountpoint = positional
with open(env["STUB_MOUNTINFO"], "a") as handle:
    handle.write(f"901 30 0:99 / {escape(mountpoint)} rw,nosuid,nodev,relatime shared:1 - fuse.gocryptfs "
                 f"{escape(cipher)} rw,user_id={os.getuid()},group_id={os.getgid()},max_read=1048576\n")
# Now the daemon. Killed, it leaves its mount line behind (a dead FUSE mount);
# it exits on its own once unmounted.
os.rename(os.path.join(PIDS, f"worker-{os.getpid()}"), os.path.join(PIDS, f"daemon-{os.getpid()}"))
open(env["STUB_READY"], "w").close()
while mounted(mountpoint):
    time.sleep(0.05)
sys.exit(0)
'''

# kwallet-query in front of test_vault's wallet stub: blocks (as on KDE Wallet's own
# prompt) when "<mode>:<entry>" is STUB_KWALLET_BLOCK, otherwise runs the stub.
KWALLET_GATE = r'''#!PYTHON
import os, sys, time

args = sys.argv[1:]
if os.environ.get("STUB_KWALLET_BLOCK") == f"{args[2]}:{args[3]}":
    with open("/proc/self/stat") as handle:
        start = handle.read().rsplit(")", 1)[1].split()[19]
    with open(os.path.join(os.environ["STUB_PIDS"], f"kwallet-{os.getpid()}"), "w") as handle:
        handle.write(start)
    time.sleep(float(os.environ.get("STUB_KWALLET_SLEEP", "60")))
real = os.environ["STUB_KWALLET_REAL"]
os.execv(real, [real, *args])
'''

# Runs the helper the way a front end does; mutations (module, old, new) are the proofs.
DRIVER = r'''
import importlib, json, signal, sys

spec = json.load(open(sys.argv[1]))
sys.path.insert(0, spec["src"])
# A front end starts the helper with default dispositions; pytest's workers may ignore SIGINT.
signal.signal(signal.SIGINT, signal.default_int_handler)
signal.signal(signal.SIGHUP, signal.SIG_DFL)
signal.signal(signal.SIGTERM, signal.SIG_DFL)
if spec.get("sigterm_ignored"):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)  # As inherited (nohup-like): after the reset above.
if spec.get("sigchld_ignored"):
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)
from hearthwire import cli
from hearthwire.core import frontend, vault
sources = {}
for name, old, new in spec["mutations"]:
    # Several mutations of one module add up.
    module = importlib.import_module(name)
    source = sources[name] if name in sources else open(module.__file__).read()
    assert old in source, (name, old)
    sources[name] = source.replace(old, new, 1)
for name, source in sources.items():
    module = importlib.import_module(name)
    exec(compile(source, module.__file__, "exec"), module.__dict__)
vault.MOUNTINFO = spec["mountinfo"]
# The stub mountpoint is a plain directory, so its device equals its parent's.
vault._same_device = lambda root_info, parent_info: False
vault.PASSWD_GRACE = 0.2
if spec.get("askpass"):
    frontend.ASKPASS_PATH = spec["askpass"]
    frontend.askpass_path = lambda lstat=None: spec["askpass"]
# Task 011d: split like the real command line (a front process and its worker) unless told not to.
sys.exit(cli.main(spec["argv"], split=spec["split"]))
'''


def _start_time(pid):
    try:
        with open(f"/proc/{pid}/stat") as handle:
            fields = handle.read().rsplit(")", 1)[1].split()
    except OSError:
        return None
    return None if fields[0] == "Z" else fields[19]


class Case:
    def __init__(self, root, runtime):
        self.root = root
        self.bin = root / "bin"
        self.bin.mkdir()
        self.pids = root / "pids"
        self.pids.mkdir()
        self.home = root / "home"
        self.home.mkdir()
        self.data = root / "data"
        self.runtime = runtime
        self.mountinfo = root / "mountinfo"
        self.mountinfo.write_text(BASE_MOUNTINFO)
        self.wallet = root / "wallet.json"
        for name in ("gocryptfs", "kdialog", "fusermount3"):
            self._tool(name, STUB)
        for name in ("qdbus6", "openssl"):
            self._tool(name, WALLET_STUB)
        (root / "wallet-bin").mkdir()
        self.kwallet_real = root / "wallet-bin" / "kwallet-query"
        self._tool(self.kwallet_real, WALLET_STUB)
        self._tool("kwallet-query", KWALLET_GATE)
        self.askpass = root / "lib" / "hearthwire-askpass"
        self.askpass.parent.mkdir()
        self._tool(self.askpass, STUB)
        self.driver = root / "driver.py"
        self.driver.write_text(DRIVER)
        self.helpers = []
        self.held = []

    def _tool(self, name, text):
        path = name if isinstance(name, Path) else self.bin / name
        path.write_text(text.replace("PYTHON", sys.executable, 1))
        path.chmod(0o755)

    @property
    def cipher(self):
        return Path(os.path.realpath(self.data)) / "hearthwire" / "vault"

    @property
    def mountpoint(self):
        return Path(os.path.realpath(self.runtime)) / "hearthwire" / "vault"

    def make_locked(self):
        self.cipher.mkdir(parents=True, mode=0o700)
        (self.cipher / "gocryptfs.conf").write_text("{}")

    def mounted(self):
        return "fuse.gocryptfs" in self.mountinfo.read_text()

    def start(self, argv, *, mutations=(), app=False, sigchld_ignored=False, sigterm_ignored=False, split=True,
              preexec_fn=None,
              stdout=subprocess.PIPE, stderr=subprocess.PIPE, **stub_env):
        spec = {"src": str(SRC), "argv": argv, "mutations": [list(item) for item in mutations],
                "mountinfo": str(self.mountinfo), "askpass": str(self.askpass) if app else None,
                "sigchld_ignored": sigchld_ignored, "sigterm_ignored": sigterm_ignored, "split": split}
        spec_path = self.root / f"spec-{len(self.helpers)}.json"
        spec_path.write_text(json.dumps(spec))
        env = {"PATH": str(self.bin), "HOME": str(self.home), "XDG_DATA_HOME": str(self.data),
               "XDG_RUNTIME_DIR": str(self.runtime), "LANG": "C.UTF-8", "STUB_PIDS": str(self.pids),
               "STUB_MOUNTINFO": str(self.mountinfo), "STUB_LOG": str(self.root / "wallet.log"),
               "STUB_WALLET": str(self.wallet), "STUB_KWALLET_REAL": str(self.kwallet_real), **{key: str(value) for key, value in stub_env.items()}}
        if os.environ.get("TMPDIR"):
            env["TMPDIR"] = os.environ["TMPDIR"]
        if app:
            env["HEARTHWIRE_FRONTEND"] = "app"
        helper = subprocess.Popen([sys.executable, "-I", str(self.driver), str(spec_path)], env=env,
                                  stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                  start_new_session=True, preexec_fn=preexec_fn)
        self.helpers.append(helper)
        return helper

    def run(self, argv, **kwargs):
        helper = self.start(argv, **kwargs)
        out, err = helper.communicate(timeout=30)
        return helper.returncode, out.decode(), err.decode()

    def noted(self, role=None):
        """{name: start time} of every stub process recorded so far."""
        return {path.name: path.read_text() for path in self.pids.iterdir()
                if not path.name.startswith("ready-") and (role is None or path.name.startswith(role + "-"))}

    def alive(self, role=None):
        return sorted(name for name, start in self.noted(role).items()
                      if _start_time(int(name.rsplit("-", 1)[1])) == start)

    def wait_for(self, predicate, timeout=15.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return False

    def relays(self):
        """Pids of extpass_relay.py processes that run for this case (their marker is in our runtime dir)."""
        marker = os.path.join(os.path.realpath(self.runtime), "hearthwire", vault.PASSWD_MARKER).encode()
        found = []
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/cmdline", "rb") as handle:
                    argv = handle.read().split(b"\0")
            except OSError:
                continue
            if marker in argv and _start_time(int(entry)) is not None:
                found.append(int(entry))
        return found

    def hold_lock(self):
        app = self.mountpoint.parent
        app.mkdir(mode=0o700, exist_ok=True)
        holder = os.open(app / "vault.lock", os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(holder, fcntl.LOCK_EX)
        self.held.append(holder)

    def lock_free(self):
        lock = self.mountpoint.parent / "vault.lock"
        if not lock.exists():
            return True
        descriptor = os.open(lock, os.O_RDWR)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False
        finally:
            os.close(descriptor)

    def cleanup(self):
        for holder in self.held:
            os.close(holder)
        for helper in self.helpers:
            if helper.poll() is None:
                helper.kill()
                helper.communicate()
        for name in self.alive():
            try:
                os.kill(int(name.rsplit("-", 1)[1]), signal.SIGKILL)
            except ProcessLookupError:
                pass
        for pid in self.relays():
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.fixture
def case(tmp_path, _private_runtime_dir):
    made = Case(tmp_path, _private_runtime_dir)
    yield made
    made.cleanup()


INTERRUPTED = ('{"ok":false,"error":"interrupted"}\n', termination.EXIT_CODE)


def stop_problems(case, argv, *, signal_number=signal.SIGTERM, ready=lambda case: bool(case.alive("dialog")),
                  mutations=(), app=False, expect=INTERRUPTED, **stub_env):
    """Start the helper, signal it once ``ready``; what is wrong with the outcome (empty: all good)."""
    helper = case.start(argv, mutations=mutations, app=app, **stub_env)
    problems = []
    if not case.wait_for(lambda: ready(case) or helper.poll() is not None):
        problems.append("the helper never got to its dialog")
    if helper.poll() is not None:
        problems.append(f"the helper ended before the signal: {helper.returncode}")
        return problems
    os.kill(helper.pid, signal_number)
    try:
        out, err = helper.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        problems.append("the helper kept running after the signal")
        return problems
    if helper.returncode != expect[1]:
        problems.append(f"exit status {helper.returncode}")
    if out.decode() != expect[0]:
        problems.append(f"reply {out!r}")
    if err:
        problems.append("something on stderr")
    def left():
        return [name for name in case.alive() if not name.startswith("daemon-")] + case.relays()

    if not case.wait_for(lambda: not left(), timeout=3):
        problems.append(f"left running: {left()}")
    if not case.lock_free():
        problems.append("the vault lock is still held")
    return problems


# --- the stop itself ------------------------------------------------------------------------------


@pytest.mark.parametrize("signal_number", [signal.SIGTERM, signal.SIGHUP, signal.SIGINT])
def test_a_stop_during_the_unlock_dialog_stops_gocryptfs_and_the_dialog(case, signal_number):
    case.make_locked()
    assert stop_problems(case, ["--vault", "unlock"], signal_number=signal_number) == []
    assert not case.mounted()
    assert os.lstat(case.mountpoint).st_mode & 0o777 == vault.SEALED_MODE
    assert case.noted("gocryptfs") and case.noted("worker") and case.noted("dialog")


def test_a_stop_in_app_mode_stops_the_askpass_prompt(case):
    case.make_locked()
    assert stop_problems(case, ["--vault", "unlock"], app=True) == []
    assert not case.mounted()


def test_a_stop_during_create_removes_the_new_folder(case):
    assert stop_problems(case, ["--vault", "create"]) == []
    assert not case.cipher.exists()
    assert not case.mounted()


def test_a_stop_after_the_mount_came_up_but_before_gocryptfs_reported_unmounts(case):
    """gocryptfs had not exited yet, so the step was unfinished: its daemon goes, and so does its mount."""
    case.make_locked()
    problems = stop_problems(case, ["--vault", "unlock"], ready=lambda case: bool(case.alive("daemon")),
                             STUB_DIALOG_SLEEP=0, STUB_PARENT_HOLD=60)
    assert problems == []
    assert not case.alive("daemon")
    assert not case.mounted()
    assert os.lstat(case.mountpoint).st_mode & 0o777 == vault.SEALED_MODE


def test_a_stop_during_change_passphrase_stops_the_relay_and_its_dialog(case):
    case.make_locked()
    assert stop_problems(case, ["--vault", "change-passphrase"]) == []
    assert not (case.mountpoint.parent / vault.PASSWD_MARKER).exists()
    assert (case.cipher / "gocryptfs.conf").read_text() == "{}"


def _unlocked(case):
    case.make_locked()
    code, out, err = case.run(["--vault", "unlock"], STUB_DIALOG_SLEEP=0)
    assert (code, out, err) == (0, '{"ok":true}\n', "")
    assert case.mounted() and case.alive("daemon")


def test_a_stop_never_touches_an_open_folder(case):
    """add-key while unlocked: the -passwd step and its dialog go; the daemon an earlier run left stays."""
    _unlocked(case)
    daemon = case.alive("daemon")
    assert stop_problems(case, ["--vault", "add-key", "--method", "wallet"]) == []
    assert case.alive("daemon") == daemon
    assert case.mounted()
    keys = Path(os.path.realpath(case.data)) / "hearthwire" / "vault-keys"
    assert not (keys / "wallet.conf.new").exists()
    assert not (keys / "wallet.conf").exists()


def test_a_stop_while_waiting_for_the_vault_lock_runs_nothing(case):
    case.make_locked()
    case.hold_lock()
    started = time.monotonic()
    assert stop_problems(case, ["--vault", "unlock"], ready=lambda case: time.monotonic() - started > 0.5) == [
        "the vault lock is still held"]  # Held by this test, not the helper.
    assert case.noted() == {}


def _mounted_library(case):
    """A fake verified mount, as test_promptstore uses (no gocryptfs runs)."""
    case.cipher.mkdir(parents=True, mode=0o700)
    case.mountpoint.mkdir(parents=True, mode=0o700)
    case.mountinfo.write_text(
        f"901 30 0:99 / {case.mountpoint} rw,nosuid,nodev shared:1 - fuse.gocryptfs {case.cipher} "
        f"rw,user_id={UID},group_id={GID}\n")


def test_a_stop_during_the_prompt_text_box_removes_the_pending_file(case):
    _mounted_library(case)
    assert stop_problems(case, ["--prompts", "add", "--kind", "prompt"]) == []
    assert os.listdir(case.mountpoint / "library") == []


def test_without_a_signal_the_runs_are_unchanged(case):
    """The handler changes nothing for a run that is not stopped (reply and status as before)."""
    assert case.run(["--vault", "create"], STUB_DIALOG_SLEEP=0) == (0, '{"ok":true}\n', "")
    assert case.mounted()
    assert case.run(["--vault", "lock"]) == (0, '{"ok":true}\n', "")
    assert not case.mounted()
    assert case.wait_for(lambda: not case.alive(), timeout=5)


# --- fix round 1: the wallet, SIGCHLD, steps that already finished ---------------------------------

WALLET_KEY = "Hearthwire/encrypted-chat-folder"
ADD_KEY = ["--vault", "add-key", "--method", "wallet"]


def _keys(case):
    return Path(os.path.realpath(case.data)) / "hearthwire" / "vault-keys"


def _wallet(case):
    return json.loads(case.wallet.read_text()) if case.wallet.exists() else {}


def _kwallet_waits(case):
    return bool(case.alive("kwallet"))


def _set_up_wallet(case):
    _unlocked(case)
    assert case.run(ADD_KEY, STUB_DIALOG_SLEEP=0) == (0, '{"ok":true}\n', "")
    assert (_keys(case) / "wallet.conf").exists() and WALLET_KEY in _wallet(case)


# The commit's kwallet-query -w is let finish after a stop (task 011d, N5); with this bound it is
# stopped after 0.5 s, so the rollback runs.
SHORT_FINISH = ("hearthwire.core.termination", "FINISH_TIMEOUT = 10.0\n", "FINISH_TIMEOUT = 0.5\n")


def resetup_problems(case, mutations=()):
    """Re-setup stopped while the staged key is copied to the real entry and the write
    does not finish (security M1, L2)."""
    _set_up_wallet(case)
    slot = _keys(case) / "wallet.conf"
    inode, entry = os.stat(slot).st_ino, _wallet(case)[WALLET_KEY]
    problems = stop_problems(case, ADD_KEY, ready=_kwallet_waits, mutations=[SHORT_FINISH, *mutations],
                             STUB_DIALOG_SLEEP=0, STUB_KWALLET_BLOCK="--write-password:encrypted-chat-folder")
    if not slot.exists() or os.stat(slot).st_ino != inode:
        problems.append("the old slot is not back")
    for name in ("wallet.conf.old", "wallet.conf.new"):
        if (_keys(case) / name).exists():
            problems.append(f"{name} is left")
    if _wallet(case).get(WALLET_KEY) != entry:
        problems.append("the real entry changed")
    if WALLET_KEY + ".new" in _wallet(case):
        problems.append("the staged entry is left")
    if not case.mounted():
        problems.append("the open folder was touched")
    return problems


def test_a_stop_while_the_slot_is_committed_rolls_back(case):
    assert resetup_problems(case) == []


@pytest.mark.parametrize(("module", "old", "new"), [
    ("hearthwire.core.vault", "    except (HelperError, termination.Stopped):\n        try:\n            _rename(",
     "    except HelperError:\n        try:\n            _rename("),
    ("hearthwire.core.vault", "                if not (isinstance(error, HelperError) and error.code == \"wallet-failed\"):\n",
     "                if not isinstance(error, termination.Stopped) and not (\n"
     "                        isinstance(error, HelperError) and error.code == \"wallet-failed\"):\n"),
])
def test_proof_the_commit_rollback_and_entry_drop_are_needed(case, module, old, new):
    assert resetup_problems(case, [(module, old, new)])


def kwallet_wait_problems(case, mutations=()):
    """add-key's first set-up, stopped while kwallet-query waits (as for KDE Wallet's prompt) (review F3)."""
    _unlocked(case)
    problems = stop_problems(case, ADD_KEY, ready=_kwallet_waits, mutations=mutations, STUB_DIALOG_SLEEP=0,
                             STUB_KWALLET_BLOCK="--write-password:encrypted-chat-folder.new")
    if os.path.lexists(_keys(case) / "wallet.conf.new") or os.path.lexists(_keys(case) / "wallet.conf"):
        problems.append("a slot file is left")
    if set(_wallet(case)) & {WALLET_KEY, WALLET_KEY + ".new"}:
        problems.append("an entry is left")
    return problems


def test_a_stop_while_kwallet_query_waits_in_add_key(case):
    assert kwallet_wait_problems(case) == []


def test_proof_the_kwallet_query_wait_is_interruptible(case):
    assert kwallet_wait_problems(case, [("hearthwire.core.walletkey", "    code = termination.wait(child, timeout)\n",
                                         "    code = termination.wait(child, timeout, interruptible=False)\n")])


def test_a_stop_while_kwallet_query_answers_the_wallet_unlock(case):
    """kwallet-query is gocryptfs's extpass here, so it goes with gocryptfs's group."""
    _set_up_wallet(case)
    assert case.run(["--vault", "lock"]) == (0, '{"ok":true}\n', "")
    assert case.wait_for(lambda: not case.alive("daemon"))
    assert stop_problems(case, ["--vault", "unlock", "--method", "wallet"], ready=_kwallet_waits,
                         STUB_KWALLET_BLOCK="--read-password:encrypted-chat-folder") == []
    assert not case.mounted()


def remove_key_problems(case, mutations=()):
    """remove-key stopped during the overwrite: the qdbus6 delete still runs (security L2)."""
    _set_up_wallet(case)
    problems = stop_problems(case, ["--vault", "remove-key", "--method", "wallet"], ready=_kwallet_waits,
                             mutations=mutations, expect=('{"ok":true}\n', 0),
                             STUB_KWALLET_BLOCK="--write-password:encrypted-chat-folder")
    if WALLET_KEY in _wallet(case):
        problems.append("the entry is left")
    if (_keys(case) / "wallet.conf").exists():
        problems.append("the slot is left")
    return problems


def test_a_stop_during_the_overwrite_still_deletes_the_entry(case):
    assert remove_key_problems(case) == []


def test_proof_the_delete_after_a_stop_is_needed(case):
    assert remove_key_problems(case, [("hearthwire.core.walletkey",
                                       "        except (HelperError, termination.Stopped):\n            pass  # Best",
                                       "        except HelperError:\n            pass  # Best")])


def sigchld_problems(case, mutations=(), split=True):
    """SIGCHLD ignored by whoever started the helper: exit codes must still count (security L1)."""
    case.make_locked()
    result = case.run(["--vault", "unlock"], mutations=mutations, sigchld_ignored=True, split=split,
                      STUB_DIALOG_SLEEP=0, STUB_DIALOG_EXIT=1)
    return [] if result == (0, '{"ok":false,"error":"cancelled"}\n', "") else [f"got {result}"]


def test_an_inherited_ignored_sigchld_is_reset(case):
    assert sigchld_problems(case) == []
    assert not case.mounted()


def test_proof_the_sigchld_reset_is_needed(case):
    """Both resets taken out (cli.main's for every command, task 011d N4, and handling()'s)."""
    assert sigchld_problems(case, [("hearthwire.core.termination",
                                    "            previous[signal.SIGCHLD] = signal.signal(signal.SIGCHLD, signal.SIG_DFL)\n",
                                    "            pass\n"),
                                   ("hearthwire.cli", "        signal.signal(signal.SIGCHLD, signal.SIG_DFL)\n",
                                    "        pass\n")])


@pytest.mark.parametrize("split", [True, False])
def test_an_inherited_ignored_sigchld_is_reset_with_and_without_the_worker(case, split):
    assert sigchld_problems(case, split=split) == []


def _new_passphrase_given(case):
    return bool(case.noted("newdialog-end")) and not case.alive("newdialog-end")


def passwd_finish_problems(case, mutations=()):
    """A stop after the new passphrase was given: gocryptfs finishes, the change is reported (security L3)."""
    case.make_locked()
    return stop_problems(case, ["--vault", "change-passphrase"], ready=_new_passphrase_given, mutations=mutations,
                         expect=('{"ok":true}\n', 0), STUB_DIALOG_SLEEP=0, STUB_PASSWD_HOLD=1.5)


def test_a_stop_after_the_new_passphrase_lets_the_change_finish(case):
    assert passwd_finish_problems(case) == []


def test_proof_the_change_is_let_finish(case):
    assert passwd_finish_problems(case, [(
        "hearthwire.core.vault",
        "        if dialog is None or not termination.exited(dialog) or dialog.wait() != 0:\n            raise\n",
        "        raise\n")])


def init_finish_problems(case, mutations=()):
    """A stop while -init writes the folder: it finishes (a complete, locked folder), and no mount starts."""
    temporary = case.cipher / "gocryptfs.conf.tmp"
    problems = stop_problems(case, ["--vault", "create"], ready=lambda case: temporary.exists(),
                             mutations=mutations, STUB_DIALOG_SLEEP=0, STUB_INIT_HOLD=1.5)
    if temporary.exists() or not (case.cipher / "gocryptfs.conf").exists():
        problems.append("the folder is half-written")
    if case.mounted():
        problems.append("mounted")
    # Task 011d (review-5 I4): the mount after it is not started just to be stopped
    # (its first step makes the mountpoint).
    if len(case.noted("gocryptfs")) != 1 or os.path.lexists(case.mountpoint):
        problems.append("the mount step started")
    return problems


def test_a_stop_while_init_writes_lets_it_finish(case):
    assert init_finish_problems(case) == []


def test_proof_init_is_let_finish(case):
    assert init_finish_problems(case, [("hearthwire.core.vault", "settling=lambda: _cipher_has_files(ctx))",
                                        "settling=None)")])


def test_proof_no_mount_starts_after_a_finished_init(case):
    assert init_finish_problems(case, [
        ("hearthwire.core.vault",
         "    # A stop that came while -init finished: no gocryptfs is started just to be stopped.\n"
         "    termination.check()\n", "")])


# --- task 011d: review-5 R1, audit N2 and N5 -------------------------------------------------------


def newdialog_problems(case, mutations=()):
    """change-passphrase stopped while the new-passphrase dialog is still open (review-5 R1)."""
    case.make_locked()
    problems = stop_problems(case, ["--vault", "change-passphrase"], ready=lambda case: bool(case.alive("newdialog")),
                             mutations=mutations, STUB_DIALOG_SLEEP=0, STUB_NEWDIALOG_SLEEP=60)
    if (case.cipher / "gocryptfs.conf").read_text() != "{}":
        problems.append("the config changed")
    if (case.mountpoint.parent / vault.PASSWD_MARKER).exists():
        problems.append("passwd.status is left")
    return problems


def test_a_stop_while_the_new_passphrase_dialog_is_open(case):
    assert newdialog_problems(case) == []


def test_proof_an_open_new_passphrase_dialog_is_not_waited_for(case):
    """Mutation N1 of review-5: the finish wait also while the second dialog is still open."""
    assert newdialog_problems(case, [(
        "hearthwire.core.vault",
        "        if dialog is None or not termination.exited(dialog) or dialog.wait() != 0:\n",
        "        if dialog is None:\n")])


# -init cut off at its first write: the "has started writing" check said not yet (the race of audit N2).
INIT_RACE = ("hearthwire.core.vault", "settling=lambda: _cipher_has_files(ctx))", "settling=None)")


def init_cut_problems(case, mutations=()):
    temporary = case.cipher / "gocryptfs.conf.tmp"
    problems = stop_problems(case, ["--vault", "create"], ready=lambda case: temporary.exists(),
                             mutations=[INIT_RACE, *mutations], STUB_DIALOG_SLEEP=0, STUB_INIT_HOLD=60)
    if case.cipher.exists():
        problems.append(f"the folder is left: {sorted(os.listdir(case.cipher))}")
    return problems


def test_a_stop_that_cuts_off_init_leaves_no_damaged_folder(case):
    assert init_cut_problems(case) == []


def test_proof_the_init_temp_file_is_removed(case):
    assert init_cut_problems(case, [("hearthwire.core.vault", "            _forget_init_leftovers(ctx)\n", "")])


def commit_finish_problems(case, mutations=()):
    """A stop while the commit's kwallet-query -w writes the real entry: it finishes, the new slot stays (N5)."""
    _set_up_wallet(case)
    slot = _keys(case) / "wallet.conf"
    inode, entry = os.stat(slot).st_ino, _wallet(case)[WALLET_KEY]
    problems = stop_problems(case, ADD_KEY, ready=_kwallet_waits, mutations=mutations, expect=('{"ok":true}\n', 0),
                             STUB_DIALOG_SLEEP=0, STUB_KWALLET_SLEEP=1.0,
                             STUB_KWALLET_BLOCK="--write-password:encrypted-chat-folder")
    if not slot.exists() or os.stat(slot).st_ino == inode:
        problems.append("the new slot is not in")
    if _wallet(case).get(WALLET_KEY) in (None, entry):
        problems.append("the real entry is not the new one")
    for name in ("wallet.conf.old", "wallet.conf.new"):
        if (_keys(case) / name).exists():
            problems.append(f"{name} is left")
    if WALLET_KEY + ".new" in _wallet(case):
        problems.append("the staged entry is left")
    return problems


def test_a_stop_while_the_commit_writes_the_entry_lets_it_finish(case):
    assert commit_finish_problems(case) == []


def test_proof_the_commit_write_is_let_finish(case):
    assert commit_finish_problems(case, [("hearthwire.core.vault", "walletkey.ENTRY, settling=True)",
                                          "walletkey.ENTRY, settling=False)")])


# --- proofs: each check bites ---------------------------------------------------------------------

UNLOCK = (["--vault", "unlock"], {})
PROOFS = {
    "no handler": ("hearthwire.core.termination", "previous[number] = signal.signal(number, _record)",
                   "previous[number] = signal.getsignal(number)", UNLOCK),
    "only the child signalled": ("hearthwire.core.termination", "            os.killpg(child.pid, number)\n",
                                 "            os.kill(child.pid, number)\n", UNLOCK),
    "the unfinished step not stopped": ("hearthwire.core.vault", "        termination.stop(child)\n    if code is None:",
                                        "        pass\n    if code is None:", UNLOCK),
    "the wait not interruptible": ("hearthwire.core.vault", "        code = termination.wait(child, timeout, "
                                   "interruptible=interruptible)\n",
                                   "        code = termination.wait(child, timeout, interruptible=False)\n", UNLOCK),
    "the unfinished mount kept": ("hearthwire.core.vault", "    except termination.Stopped:\n        _drop_mount(ctx, app)\n",
                                  "    except termination.Stopped:\n        pass\n",
                                  (["--vault", "unlock"], {"STUB_DIALOG_SLEEP": 0, "STUB_PARENT_HOLD": 60,
                                                           "ready": "daemon"})),
    "the half-made folder kept": ("hearthwire.core.vault", "            if created:\n                _forget_cipher_dir(ctx)\n"
                                  "            raise\n", "            raise\n", (["--vault", "create"], {})),
    "the passwd group not stopped": ("hearthwire.core.vault", "        if child is not None:\n            "
                                     "termination.stop(child)\n        _clear_marker(app)\n",
                                     "        _clear_marker(app)\n", (["--vault", "change-passphrase"], {})),
    "the staged slot kept": ("hearthwire.core.vault", "            except (HelperError, OSError, termination.Stopped) as error:\n",
                             "            except (HelperError, OSError) as error:\n",
                             (["--vault", "add-key", "--method", "wallet"], {"unlocked": True})),
    "the lock wait not interruptible": ("hearthwire.core.vault", "    sleep: Callable[[float], None] = termination.sleep,\n",
                                        "    sleep: Callable[[float], None] = time.sleep,\n",
                                        (["--vault", "unlock"], {"hold": True})),
    "the text box not stopped": ("hearthwire.core.promptstore", "        termination.stop(child)\n    assert code",
                                 "        pass\n    assert code", (["--prompts", "add", "--kind", "prompt"], {"library": True})),
}


def _outcome_problems(case, argv, options, mutations):
    options = dict(options)
    started = time.monotonic()
    ready = {"daemon": lambda case: bool(case.alive("daemon"))}.get(options.pop("ready", None))
    if options.pop("unlocked", False):
        _unlocked(case)
    elif options.pop("library", False):
        _mounted_library(case)
    elif argv[1] != "create":
        case.make_locked()
    held = options.pop("hold", False)
    if held:
        case.hold_lock()
        ready = lambda case: time.monotonic() - started > 0.5  # noqa: E731
    daemons, mounted = case.alive("daemon"), case.mounted()
    problems = stop_problems(case, argv, mutations=mutations, **({"ready": ready} if ready else {}), **options)
    if held:
        problems = [problem for problem in problems if problem != "the vault lock is still held"]
        if case.noted():
            problems.append("a tool ran after the stop")
    if case.alive("daemon") != daemons or case.mounted() != mounted:
        problems.append("the mount changed")
    if argv[1] == "create" and case.cipher.exists():
        problems.append("the new folder is left")
    keys = Path(os.path.realpath(case.data)) / "hearthwire" / "vault-keys"
    if (keys / "wallet.conf.new").exists():
        problems.append("the staged slot is left")
    if argv[0] == "--prompts" and os.listdir(case.mountpoint / "library"):
        problems.append("the pending file is left")
    return problems


@pytest.mark.parametrize("name", sorted(PROOFS))
def test_the_unmutated_cases_pass(case, name):
    module, old, new, (argv, options) = PROOFS[name]
    assert _outcome_problems(case, argv, options, ()) == []


@pytest.mark.parametrize("name", sorted(PROOFS))
def test_proof_each_stop_step_is_needed(case, name):
    module, old, new, (argv, options) = PROOFS[name]
    mutations = [(module, old, new)]
    if name == "no handler":
        # Task 011d: the worker records stop signals before the job (record_early); take that out too.
        mutations.append(("hearthwire.core.termination", "            signal.signal(number, _record)\n",
                          "            pass\n"))
    assert _outcome_problems(case, argv, options, mutations)


# --- termination.py itself, in this process ---------------------------------------------------------

SLEEPER = [sys.executable, "-I", "-c", "import time; time.sleep(60)"]
# Starts a sleeping grandchild in its own group; prints its pid, then sleeps (or exits with "exit").
PARENT = [sys.executable, "-I", "-c",
          "import subprocess, sys, time\n"
          "child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(60)'])\n"
          "print(child.pid, flush=True)\n"
          "time.sleep(0 if sys.argv[1:] == ['exit'] else 60)\n"]


def _gone(pid, timeout=10.0):
    """True once ``pid`` has exited (a zombie counts as gone)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _start_time(pid) is None:
            return True
        time.sleep(0.02)
    return False


def _grandchild(argv, **kwargs):
    child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, **kwargs)
    pid = int(child.stdout.readline())
    child.stdout.close()
    return child, pid


def test_stop_reaches_the_childs_own_group():
    child, grandchild = _grandchild(PARENT, process_group=0)
    termination.stop(child)
    assert child.returncode is not None
    assert _gone(grandchild)


def _stays_alive(pid, seconds=0.5):
    """True when ``pid`` is still running all through ``seconds`` (a signalled one is gone by then)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _start_time(pid) is None:
            return False
        time.sleep(0.02)
    return True


def finished_group_problems(module):
    """Like a gocryptfs whose mount came up: the parent exited (not reaped yet), the daemon in its group stays."""
    child, grandchild = _grandchild([*PARENT, "exit"], process_group=0)
    try:
        if not _gone(child.pid) or child.returncode is not None:
            return ["the parent did not exit unreaped"]
        module.stop(child)
        problems = [] if child.returncode == 0 else [f"returncode {child.returncode}"]
        if not _stays_alive(grandchild):
            problems.append("the finished leader's group was signalled")
        return problems
    finally:
        try:
            os.kill(grandchild, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_stop_never_signals_the_group_of_a_child_that_finished():
    assert finished_group_problems(termination) == []


def test_proof_the_finished_group_check_bites():
    from test_frontend import mutant

    copy = mutant(termination, "    if _probe(child) is not False:\n        # Finished on its own, or reaped elsewhere: "
                               "never signalled.\n        child.wait()\n        return\n", "")
    assert finished_group_problems(copy)


def reaped_kill_problems(module, monkeypatch):
    """SIGCHLD ignored: the kernel reaps the child as it exits; that pid is never signalled again."""
    sent = []
    real_killpg, real_kill = os.killpg, os.kill
    monkeypatch.setattr(os, "killpg", lambda pid, number: (sent.append(number), real_killpg(pid, number)))
    monkeypatch.setattr(os, "kill", lambda pid, number: (sent.append(number), real_kill(pid, number)))
    previous = signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    try:
        child = subprocess.Popen(SLEEPER, process_group=0)
        module.stop(child)
    finally:
        signal.signal(signal.SIGCHLD, previous)
    return [] if sent == [signal.SIGTERM] else [f"sent {sent}"]


@main_thread_only
def test_stop_never_signals_a_pid_the_kernel_reaped(monkeypatch):
    assert reaped_kill_problems(termination, monkeypatch) == []


@main_thread_only
def test_proof_the_reaped_check_bites(monkeypatch):
    from test_frontend import mutant

    copy = mutant(termination, "    if _probe(child) is not None:\n        _signal(child, signal.SIGKILL)",
                  "    if True:\n        _signal(child, signal.SIGKILL)")
    assert reaped_kill_problems(copy, monkeypatch)


def test_stop_signals_only_a_child_that_is_not_its_groups_leader():
    """Without its own group, killpg(child.pid) could name a group that is not the child's: never used."""
    child, grandchild = _grandchild(PARENT)
    try:
        termination.stop(child)
        assert child.returncode == -signal.SIGTERM
        assert _stays_alive(grandchild)
    finally:
        os.kill(grandchild, signal.SIGKILL)


@main_thread_only
def test_wait_raises_stopped_only_while_the_child_runs():
    with termination.handling():
        running = subprocess.Popen(SLEEPER, process_group=0)
        done = subprocess.Popen([sys.executable, "-I", "-c", "raise SystemExit(3)"], process_group=0)
        try:
            assert _gone(done.pid)
            signal.raise_signal(signal.SIGTERM)
            assert termination.requested()
            # The finished step reports its code even after the signal.
            assert termination.wait(done) == 3
            with pytest.raises(termination.Stopped):
                termination.wait(running)
            assert running.returncode is None and not termination.exited(running)
            # Non-interruptible waits (an unmount, the version line) are not cut short.
            assert termination.wait(running, 0.05, interruptible=False) is None
            with pytest.raises(termination.Stopped):
                termination.sleep(5)
        finally:
            termination.stop(running)
    assert running.returncode == -signal.SIGTERM
    assert not termination.requested()


@pytest.fixture
def default_stop_signals():
    """Explicit start state: the stop signals at SIG_DFL (a background job starts pytest with SIGINT ignored)."""
    saved = {number: signal.signal(number, signal.SIG_DFL) for number in (*termination.SIGNALS, signal.SIGQUIT)}
    signal.signal(signal.SIGINT, signal.default_int_handler)
    yield
    for number, handler in saved.items():
        signal.signal(number, handler)


@main_thread_only
def test_handling_restores_the_handlers_and_keeps_ignored_signals_ignored(default_stop_signals):
    before = {number: signal.getsignal(number) for number in termination.SIGNALS}
    previous_hup = signal.signal(signal.SIGHUP, signal.SIG_IGN)
    previous_chld = signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    try:
        with termination.handling():
            assert signal.getsignal(signal.SIGCHLD) is signal.SIG_DFL
            assert signal.getsignal(signal.SIGHUP) is signal.SIG_IGN
            assert signal.getsignal(signal.SIGTERM) is termination._record
            assert signal.getsignal(signal.SIGINT) is termination._record
        assert signal.getsignal(signal.SIGHUP) is signal.SIG_IGN
        assert signal.getsignal(signal.SIGCHLD) is signal.SIG_IGN
    finally:
        signal.signal(signal.SIGHUP, previous_hup)
        signal.signal(signal.SIGCHLD, previous_chld)
    assert {number: signal.getsignal(number) for number in termination.SIGNALS} == before


def test_wait_with_a_timeout_returns_none_and_leaves_the_child_for_stop():
    child = subprocess.Popen(SLEEPER, process_group=0)
    try:
        assert termination.wait(child, 0.05) is None
        assert child.returncode is None
    finally:
        termination.stop(child, grace=0.0)
    assert child.returncode in (-signal.SIGTERM, -signal.SIGKILL)
