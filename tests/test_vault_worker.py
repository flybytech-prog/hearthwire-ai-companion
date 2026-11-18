"""Task 011d: a SIGKILL of the helper process still stops its --vault and --prompts job.

The Plasma widget ends a dropped source with SIGKILL. From the command line the
helper (the "front") forks a worker that gets SIGTERM when the front dies
(``core/worker.py``). Each case runs the helper as in test_vault_signals.py
(``python -I``, an environment built from nothing, stub tools), waits until a
stub dialog is open, SIGKILLs the front (never the worker) and checks that the
worker stopped every stub, undid the step, released the lock and exited.
Proofs run the same cases with one part of the split taken out.
"""

import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from hearthwire import cli
from hearthwire.core import termination, vault, worker
from test_vault_signals import (  # noqa: F401 - case is a fixture
    ADD_KEY, INTERRUPTED, SRC, _keys, _kwallet_waits, _mounted_library, _set_up_wallet, _start_time, _unlocked,
    _wallet, WALLET_KEY, case, main_thread_only, stop_problems,
)


def _children(pid):
    """Pids whose parent is ``pid`` (from /proc, so it works without CONFIG_PROC_CHILDREN)."""
    found = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as handle:
                fields = handle.read().rsplit(")", 1)[1].split()
        except OSError:
            continue
        if int(fields[1]) == pid and fields[0] != "Z":
            found.append(int(entry))
    return found


def _open_files(pid):
    names = []
    try:
        for fd in os.listdir(f"/proc/{pid}/fd"):
            try:
                names.append(os.readlink(f"/proc/{pid}/fd/{fd}"))
            except OSError:
                pass
    except OSError:
        pass
    return names


def _flock_holders(path):
    """Pids that hold a flock on ``path`` (from /proc/locks: the worker is not dumpable, its fds are hidden)."""
    inode = os.stat(path).st_ino
    holders = []
    with open("/proc/locks") as handle:
        for line in handle:
            fields = line.split()
            if "->" in fields or len(fields) < 6 or fields[1] != "FLOCK":
                continue
            if int(fields[5].rsplit(":", 1)[1]) == inode:
                holders.append(int(fields[4]))
    return holders


def _worker_of(case, helper):
    """(pid, start time) of the front's one worker, the Python process it forked."""
    for pid in _children(helper.pid):
        start = _start_time(pid)
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                argv = handle.read().split(b"\0")
        except OSError:
            continue
        if start is not None and str(case.driver).encode() in argv:
            return pid, start
    return None, None


def kill_problems(case, argv, *, ready=lambda case: bool(case.alive("dialog")), mutations=(), lock=True,
                  term_first=False, expect=INTERRUPTED[0], **stub_env):
    """Start the helper, SIGKILL the front once ``ready``; what is wrong with the outcome (empty: all good)."""
    helper = case.start(argv, mutations=mutations, **stub_env)
    problems = []
    if not case.wait_for(lambda: ready(case) or helper.poll() is not None):
        problems.append("the helper never got to its dialog")
    if helper.poll() is not None:
        problems.append(f"the helper ended before the kill: {helper.returncode}")
        return problems
    pid, start = _worker_of(case, helper)
    if pid is None:
        problems.append("no worker")
    lock_file = str(Path(os.path.realpath(case.runtime)) / "hearthwire" / vault.LOCK_FILE)
    if lock_file in _open_files(helper.pid):
        problems.append("the front holds the vault lock file")
    holders = _flock_holders(lock_file) if os.path.exists(lock_file) else []
    if helper.pid in holders:
        problems.append("the front holds the vault lock")
    if lock and pid is not None and pid not in holders:
        problems.append("the worker does not hold the vault lock")
    if term_first:
        # The front forwards this one; the death signal is then a second SIGTERM.
        os.kill(helper.pid, signal.SIGTERM)
        time.sleep(0.2)
    os.kill(helper.pid, signal.SIGKILL)
    try:
        # EOF only once the worker (and every stub that shares stdout) is gone.
        out, err = helper.communicate(timeout=8)
    except subprocess.TimeoutExpired:
        problems.append("the worker kept running after the front was killed")
        if pid is not None and _start_time(pid) == start:
            os.kill(pid, signal.SIGKILL)
        return problems
    if helper.returncode != -signal.SIGKILL:
        problems.append(f"front exit status {helper.returncode}")
    if out.decode() != expect:
        problems.append(f"reply {out!r}")
    if err:
        problems.append("something on stderr")
    if pid is not None and not case.wait_for(lambda: _start_time(pid) != start, timeout=5):
        problems.append("the worker is left")

    def left():
        return [name for name in case.alive() if not name.startswith("daemon-")] + case.relays()

    if not case.wait_for(lambda: not left(), timeout=3):
        problems.append(f"left running: {left()}")
    if not case.lock_free():
        problems.append("the vault lock is still held")
    return problems


# --- a SIGKILL of the front during each waiting step --------------------------------------------------


def unlock_problems(case, mutations=()):
    """The unlock dialog: the stub gocryptfs works like the real one (its -fg-like child runs the dialog)."""
    case.make_locked()
    problems = kill_problems(case, ["--vault", "unlock"], mutations=mutations)
    if case.mounted():
        problems.append("mounted")
    if os.path.isdir(case.mountpoint) and os.lstat(case.mountpoint).st_mode & 0o777 != vault.SEALED_MODE:
        problems.append("the mountpoint is not sealed")
    if not (case.noted("gocryptfs") and case.noted("worker") and case.noted("dialog")):
        problems.append("the stub gocryptfs did not run")
    return problems


def test_a_killed_front_during_the_unlock_dialog_stops_gocryptfs_and_its_dialog(case):
    assert unlock_problems(case) == []


def _new_passphrase_given(case):
    return bool(case.noted("newdialog-end")) and not case.alive("newdialog-end")


def test_a_forwarded_stop_and_then_the_death_signal_are_one_stop(case):
    """The forwarded SIGTERM comes once -passwd has both passphrases: the worker lets it finish (3 s).
    The kill lands during that wait, so the death signal is a second SIGTERM that changes nothing."""
    case.make_locked()
    assert kill_problems(case, ["--vault", "change-passphrase"], ready=_new_passphrase_given, term_first=True,
                         expect='{"ok":true}\n', STUB_DIALOG_SLEEP=0, STUB_PASSWD_HOLD=3) == []
    assert not (case.mountpoint.parent / vault.PASSWD_MARKER).exists()


def test_a_killed_front_in_app_mode_stops_the_askpass_prompt(case):
    case.make_locked()
    assert kill_problems(case, ["--vault", "unlock"], app=True) == []
    assert not case.mounted()


def test_a_killed_front_after_the_mount_came_up_unmounts(case):
    case.make_locked()
    assert kill_problems(case, ["--vault", "unlock"], ready=lambda case: bool(case.alive("daemon")),
                         STUB_DIALOG_SLEEP=0, STUB_PARENT_HOLD=60) == []
    assert not case.alive("daemon")
    assert not case.mounted()


def test_a_killed_front_during_create_removes_the_new_folder(case):
    assert kill_problems(case, ["--vault", "create"]) == []
    assert not case.cipher.exists()
    assert not case.mounted()


def test_a_killed_front_during_change_passphrase_stops_the_relay_and_its_dialog(case):
    case.make_locked()
    assert kill_problems(case, ["--vault", "change-passphrase"]) == []
    assert not (case.mountpoint.parent / vault.PASSWD_MARKER).exists()
    assert (case.cipher / "gocryptfs.conf").read_text() == "{}"


def test_a_killed_front_during_the_new_passphrase_dialog(case):
    case.make_locked()
    assert kill_problems(case, ["--vault", "change-passphrase"], ready=lambda case: bool(case.alive("newdialog")),
                         STUB_DIALOG_SLEEP=0, STUB_NEWDIALOG_SLEEP=60) == []
    assert not (case.mountpoint.parent / vault.PASSWD_MARKER).exists()
    assert (case.cipher / "gocryptfs.conf").read_text() == "{}"


def test_a_killed_front_during_add_key_keeps_the_open_folder(case):
    _unlocked(case)
    daemon = case.alive("daemon")
    assert kill_problems(case, ADD_KEY) == []
    assert case.alive("daemon") == daemon and case.mounted()
    assert not (_keys(case) / "wallet.conf.new").exists()
    assert not (_keys(case) / "wallet.conf").exists()


def test_a_killed_front_while_kwallet_query_waits_in_add_key(case):
    _unlocked(case)
    assert kill_problems(case, ADD_KEY, ready=_kwallet_waits, STUB_DIALOG_SLEEP=0,
                         STUB_KWALLET_BLOCK="--write-password:encrypted-chat-folder.new") == []
    assert not os.path.lexists(_keys(case) / "wallet.conf.new")
    assert not set(_wallet(case)) & {WALLET_KEY, WALLET_KEY + ".new"}


def test_a_killed_front_during_the_prompt_text_box_removes_the_pending_file(case):
    _mounted_library(case)
    assert kill_problems(case, ["--prompts", "add", "--kind", "prompt"], lock=False) == []
    assert os.listdir(case.mountpoint / "library") == []


# --- normal runs, forwarding, and the front never outliving its worker ---------------------------------


def test_without_a_signal_the_split_runs_are_unchanged(case):
    assert case.run(["--vault", "create"], STUB_DIALOG_SLEEP=0) == (0, '{"ok":true}\n', "")
    assert case.mounted()
    assert case.run(["--vault", "status"]) == (0, '{"ok":true,"state":"unlocked","wallet":"off"}\n', "")
    assert case.run(["--vault", "lock"]) == (0, '{"ok":true}\n', "")
    assert case.run(["--vault", "unlock"], STUB_DIALOG_SLEEP=0, STUB_DIALOG_EXIT=1) == (
        0, '{"ok":false,"error":"cancelled"}\n', "")
    assert case.wait_for(lambda: not case.alive(), timeout=5)


def reaped_problems(case, mutations=()):
    """A normal run: the front exits only after its worker is gone, with the worker's reply and status.

    The output goes to files, so the check right after the front's exit does not wait for the
    worker's EOF (review-6 S1).
    """
    case.make_locked()
    out_path, err_path = case.root / "reaped.out", case.root / "reaped.err"
    with open(out_path, "wb") as out, open(err_path, "wb") as err:
        helper = case.start(["--vault", "unlock"], mutations=mutations, stdout=out, stderr=err, STUB_DIALOG_SLEEP=2)
    pid = start = None
    deadline = time.monotonic() + 10
    while pid is None and helper.poll() is None and time.monotonic() < deadline:
        pid, start = _worker_of(case, helper)
    if pid is None:
        return ["no worker"]
    helper.wait(timeout=15)
    problems = []
    if _start_time(pid) == start:
        problems.append("the worker outlived the front")
        case.wait_for(lambda: _start_time(pid) != start)
    got = (helper.returncode, out_path.read_text(), err_path.read_text())
    if got != (0, '{"ok":true}\n', ""):
        problems.append(f"got {got}")
    case.run(["--vault", "lock"])
    return problems


def test_the_front_exits_only_after_its_worker(case):
    assert reaped_problems(case) == []


def test_proof_the_front_waits_for_its_worker(case):
    """A front that gives up after 1 s (no blocking wait, a WNOHANG reap) leaves its worker running.

    The worker here does not act on the death signal, so it is still there to be seen after the front's exit.
    """
    assert "the worker outlived the front" in reaped_problems(case, [
        ("hearthwire.core.termination", "    if _STATE.signal is None:\n        _STATE.signal = signum\n",
         "    pass\n"),
        ("hearthwire.core.worker", "            os.waitid(os.P_PID, worker, os.WEXITED | os.WNOWAIT)\n",
         "            __import__('time').sleep(1.0)\n"),
        ("hearthwire.core.worker", "            _, status = os.waitpid(worker, 0)\n",
         "            _, status = os.waitpid(worker, os.WNOHANG)\n")])


@pytest.mark.parametrize("signal_number", [signal.SIGTERM, signal.SIGHUP, signal.SIGINT])
def test_a_stop_signal_to_the_front_reaches_the_worker(case, signal_number):
    """The front forwards it and exits with the worker's 143 once the step is undone."""
    case.make_locked()
    assert stop_problems(case, ["--vault", "unlock"], signal_number=signal_number) == []
    assert not case.mounted()


def test_a_stop_without_the_worker_still_works(case):
    """The in-process path (no fork possible) is the 011c one."""
    case.make_locked()
    assert stop_problems(case, ["--vault", "unlock"], split=False) == []


# --- proofs: each part of the split is needed --------------------------------------------------------

PROOFS = {
    "no death signal": [("hearthwire.core.worker", "    prctl(PR_SET_PDEATHSIG, DEATH_SIGNAL, 0, 0, 0)\n", "")],
    # The front takes the lock itself: its fd shows (and the worker can never get it).
    "the front holds the lock": [("hearthwire.core.worker", "    front = os.getpid()\n",
                                  "    front = os.getpid()\n"
                                  "    from . import vault as _vault\n"
                                  "    _held = _vault.vault_lock(_vault.context())\n"
                                  "    _held.__enter__()\n")],
}


@pytest.mark.parametrize("name", sorted(PROOFS))
def test_proof_each_part_of_the_split_is_needed(case, name):
    assert unlock_problems(case, PROOFS[name])


def test_proof_the_front_must_forward(case):
    case.make_locked()
    assert stop_problems(case, ["--vault", "unlock"], mutations=[(
        "hearthwire.core.worker", "        if state[\"forwarding\"]:\n", "        if False:\n")])


def test_proof_the_front_must_not_die_of_the_signal(case):
    """Without the forwarding handler the front dies at once (-15), before the worker undid the step."""
    case.make_locked()
    assert stop_problems(case, ["--vault", "unlock"], mutations=[(
        "hearthwire.core.worker", "            previous[number] = signal.signal(number, forward)\n",
        "            previous[number] = signal.getsignal(number)\n")])


# --- the worker's start: the front already gone ----------------------------------------------------

# Forks like worker.run; the "worker" waits until its front is gone, then starts. Prints the worker's pid.
ORPHAN = textwrap.dedent(r'''
    import importlib, json, os, signal, sys, time
    spec = json.load(open(sys.argv[1]))
    sys.path.insert(0, spec["src"])
    from hearthwire.core import worker
    for old, new in spec["mutations"]:
        source = open(worker.__file__).read()
        assert old in source, old
        exec(compile(source.replace(old, new, 1), worker.__file__, "exec"), worker.__dict__)
    front = os.getpid()
    prctl = worker._prctl()
    child = os.fork()
    if child == 0:
        if spec["front_gone"]:
            while os.getppid() == front:
                time.sleep(0.01)
        def job():
            open(spec["marker"], "w").close()
            return 0
        worker._worker(job, prctl, front, signal.pthread_sigmask(signal.SIG_BLOCK, []))
    print(child, flush=True)
    if not spec["front_gone"]:
        os.waitpid(child, 0)
    os._exit(0)
''')


def orphan_problems(tmp_path, front_gone, mutations=()):
    import json

    marker = tmp_path / "job-ran"
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"src": str(SRC), "marker": str(marker), "front_gone": front_gone,
                                "mutations": [list(item) for item in mutations]}))
    script = tmp_path / "orphan.py"
    script.write_text(ORPHAN)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "LANG": "C.UTF-8"}
    front = subprocess.run([sys.executable, "-I", str(script), str(spec)], env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=15)
    child = int(front.stdout)
    deadline = time.monotonic() + 10
    while _start_time(child) is not None and time.monotonic() < deadline:
        time.sleep(0.02)
    problems = [] if front.returncode == 0 and not front.stderr else [f"front {front.returncode} {front.stderr!r}"]
    if _start_time(child) is not None:
        problems.append("the worker is left")
    if marker.exists() == front_gone:
        problems.append("the job ran" if front_gone else "the job did not run")
    return problems


def test_a_worker_whose_front_is_already_gone_runs_nothing(tmp_path):
    assert orphan_problems(tmp_path, front_gone=True) == []


def test_a_worker_whose_front_is_there_runs_the_job(tmp_path):
    assert orphan_problems(tmp_path, front_gone=False) == []


def test_proof_the_parent_check_is_needed(tmp_path):
    assert orphan_problems(tmp_path, front_gone=True, mutations=[
        ("        elif os.getppid() == front:\n", "        elif True:\n")])


# --- in this process: the fork guard, N3 and N4 ------------------------------------------------------


def test_the_worker_runs_in_this_process_when_more_threads_run():
    """Never a fork with a second thread; the job then runs here (as in 011c)."""
    stop = threading.Event()
    thread = threading.Thread(target=stop.wait)
    thread.start()
    try:
        assert not worker.single_threaded()
        assert worker.run(lambda: os.getpid()) == os.getpid()
    finally:
        stop.set()
        thread.join()


def test_single_threaded_counts_the_kernels_threads(monkeypatch):
    monkeypatch.setattr(threading, "active_count", lambda: 1)
    monkeypatch.setattr(os, "listdir", lambda path: ["1", "2"] if path == "/proc/self/task" else [])
    assert not worker.single_threaded()


def test_the_command_line_splits_and_an_argv_does_not(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(worker, "run", lambda job: calls.append(job) or 7)
    monkeypatch.setattr(vault, "run", lambda operation, method=None: {"ok": True})
    monkeypatch.setattr(sys, "argv", ["hearthwire", "--vault", "status"])
    assert cli.main() == 7 and len(calls) == 1
    assert cli.main(["--vault", "status"]) == 0 and len(calls) == 1
    assert cli.main(["--vault", "status"], split=True) == 7 and len(calls) == 2
    # Refused runs and other commands never fork.
    monkeypatch.setattr(sys, "argv", ["hearthwire", "--catalog"])
    assert cli.main() == 0 and len(calls) == 2


class _Started(Exception):
    """Raised by the fake Popen: a child would have started."""


N3_CHECKS = {
    "vault._run": ("vault", "    if interruptible:\n        # Task 011d (audit N3): after a stop signal no new step starts "
                   "(no dialog flashes up).\n        termination.check()\n", ""),
    "vault._spawn": ("vault", "    termination.check()\n    _check_argv(argv, mode=mode)\n", "    _check_argv(argv, mode=mode)\n"),
    "walletkey._spawn": ("walletkey", "    termination.check()  # Task 011d (audit N3)", "    pass  #"),
    "promptstore._run_dialog": ("promptstore", "    termination.check()  # Task 011d: no text box", "    pass  #"),
}


def started_after_a_stop(monkeypatch, modules):
    """The starts that still reached Popen after a stop signal (audit N3)."""
    started = []

    def popen(*args, **kwargs):
        raise _Started

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(modules["vault"], "_check_argv", lambda *args, **kwargs: None)
    monkeypatch.setattr(modules["walletkey"], "check_argv", lambda argv: None)
    monkeypatch.setattr(modules["promptstore"], "_check_dialog_argv", lambda argv: None)
    starts = {
        "vault._run": lambda: modules["vault"]._run(["/x"]),
        "vault._spawn": lambda: modules["vault"]._spawn(["/x"]),
        "walletkey._spawn": lambda: modules["walletkey"]._spawn(["/x"]),
        "promptstore._run_dialog": lambda: modules["promptstore"]._run_dialog(["/x"], subprocess.DEVNULL),
    }
    with termination.handling():
        signal.raise_signal(signal.SIGTERM)
        for name, start in starts.items():
            try:
                start()
            except termination.Stopped:
                pass
            except _Started:
                started.append(name)
    return started


def _modules():
    from hearthwire.core import promptstore, walletkey

    return {"vault": vault, "walletkey": walletkey, "promptstore": promptstore}


@main_thread_only
def test_no_step_starts_after_a_stop_signal(monkeypatch):
    """Audit N3: the interruptible starts check the flag before Popen (no dialog flashes up)."""
    assert started_after_a_stop(monkeypatch, _modules()) == []


@main_thread_only
@pytest.mark.parametrize("name", sorted(N3_CHECKS))
def test_proof_each_start_checks_the_flag(monkeypatch, name):
    from test_frontend import mutant

    modules = _modules()
    key, old, new = N3_CHECKS[name]
    modules[key] = mutant(modules[key], old, new)
    assert started_after_a_stop(monkeypatch, modules) == [name]


@main_thread_only
def test_every_command_starts_with_the_default_sigchld(capsys):
    """Audit N4: not only --vault and --prompts."""
    previous = signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    try:
        assert cli.main(["--catalog"]) == 0
        assert signal.getsignal(signal.SIGCHLD) is signal.SIG_DFL
    finally:
        signal.signal(signal.SIGCHLD, previous)


# --- audit N2: the temp file of a cut-off -init --------------------------------------------------------


@pytest.fixture
def leftovers(tmp_path, _private_runtime_dir):
    return lambda names: _leftover_context(tmp_path, _private_runtime_dir, names)


def _leftover_context(tmp_path, runtime, names):
    data = tmp_path / "data"
    cipher = data / "hearthwire" / "vault"
    cipher.mkdir(parents=True, mode=0o700)
    for name in names:
        (cipher / name).write_text("{}")
    environ = {"HOME": str(tmp_path), "XDG_DATA_HOME": str(data), "XDG_RUNTIME_DIR": str(runtime)}
    return vault.context(environ, find_tools=False), cipher


def test_only_init_temp_files_are_removed(leftovers):
    ctx, cipher = leftovers(["gocryptfs.conf.tmp"])
    vault._forget_init_leftovers(ctx)
    assert os.listdir(cipher) == []


@pytest.mark.parametrize("names", [["gocryptfs.conf.tmp", "gocryptfs.conf"], ["gocryptfs.conf"], ["other"],
                                   ["gocryptfs.conf.tmp", "other"]])
def test_a_folder_with_more_than_temp_files_is_left_alone(leftovers, names):
    ctx, cipher = leftovers(names)
    vault._forget_init_leftovers(ctx)
    assert sorted(os.listdir(cipher)) == sorted(names)


def test_a_linked_temp_name_is_left_alone(tmp_path, leftovers):
    ctx, cipher = leftovers([])
    target = tmp_path / "elsewhere"
    target.write_text("keep")
    os.symlink(target, cipher / "gocryptfs.conf.tmp")
    vault._forget_init_leftovers(ctx)
    assert os.path.islink(cipher / "gocryptfs.conf.tmp") and target.read_text() == "keep"


# --- fix round 1: review-6 and security review-6 ------------------------------------------------------


def _block_sigterm():
    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})


# "ignored" goes through the driver (it resets SIGTERM to the default first); "blocked" is the inherited mask.
START_STATES = {"ignored": {"sigterm_ignored": True}, "blocked": {"preexec_fn": _block_sigterm}}
# Each takes out what makes the death signal work in that start state (security L1).
START_STATE_MUTATIONS = {
    "ignored": [("hearthwire.core.worker", "            signal.signal(DEATH_SIGNAL, signal.SIG_DFL)\n",
                 "            pass\n")],
    "blocked": [("hearthwire.core.worker",
                 "            signal.pthread_sigmask(signal.SIG_SETMASK, _unblocked(mask))\n            code = job()",
                 "            signal.pthread_sigmask(signal.SIG_SETMASK, mask)\n            code = job()")],
}


def start_state_problems(case, state, mutations=()):
    """SIGTERM ignored or blocked when the helper starts; a SIGKILL of the front must still stop the job."""
    case.make_locked()
    problems = kill_problems(case, ["--vault", "unlock"], mutations=mutations, **START_STATES[state])
    if case.mounted():
        problems.append("mounted")
    return problems


@pytest.mark.parametrize("state", sorted(START_STATES))
def test_a_killed_front_stops_the_job_with_sigterm_ignored_or_blocked_at_start(case, state):
    assert start_state_problems(case, state) == []


@pytest.mark.parametrize("state", sorted(START_STATES))
def test_proof_the_death_signal_is_made_to_work(case, state):
    assert "the worker kept running after the front was killed" in start_state_problems(
        case, state, START_STATE_MUTATIONS[state])


def blocked_forward_problems(case, mutations=()):
    """SIGTERM blocked at start: the front still forwards it."""
    case.make_locked()
    return stop_problems(case, ["--vault", "unlock"], mutations=mutations, preexec_fn=_block_sigterm)


def test_a_blocked_sigterm_is_still_forwarded(case):
    assert blocked_forward_problems(case) == []


def test_proof_the_front_unblocks(case):
    assert blocked_forward_problems(case, [(
        "hearthwire.core.worker",
        "        # Forwarding is in place: a signal that came since the fork is forwarded now.\n"
        "        signal.pthread_sigmask(signal.SIG_SETMASK, _unblocked(mask))\n", "")])


def dumpable_problems(case, mutations=()):
    """Security I3: the worker is not dumpable, so even the same user cannot read its /proc/<pid>/fd or mem."""
    case.make_locked()
    helper = case.start(["--vault", "unlock"], mutations=mutations)
    problems = []
    if not case.wait_for(lambda: bool(case.alive("dialog")) or helper.poll() is not None):
        problems.append("the helper never got to its dialog")
    pid, _ = _worker_of(case, helper)
    if pid is None:
        return problems + ["no worker"]
    try:
        os.listdir(f"/proc/{pid}/fd")
        problems.append("the worker's fds can be read")
    except PermissionError:
        pass
    try:
        os.listdir(f"/proc/{helper.pid}/fd")
    except PermissionError:
        problems.append("the front is not dumpable either")
    os.kill(helper.pid, signal.SIGTERM)
    helper.communicate(timeout=8)
    return problems


def test_the_worker_is_not_dumpable(case):
    assert dumpable_problems(case) == []


def test_proof_the_worker_sets_dumpable_off(case):
    assert dumpable_problems(case, [("hearthwire.core.worker", "    prctl(PR_SET_DUMPABLE, 0, 0, 0, 0)\n",
                                     "    pass\n")]) == ["the worker's fds can be read"]


# worker.run in a plain process, with a job that reports where and how it ran.
FRONT = textwrap.dedent(r'''
    import json, os, signal, sys
    spec = json.load(open(sys.argv[1]))
    sys.path.insert(0, spec["src"])
    from hearthwire.core import termination, worker
    if spec["mutations"]:
        source = open(worker.__file__).read()
        for old, new in spec["mutations"]:
            assert old in source, old
            source = source.replace(old, new, 1)
        exec(compile(source, worker.__file__, "exec"), worker.__dict__)
    if spec["block"]:
        signal.pthread_sigmask(signal.SIG_BLOCK, [getattr(signal, name) for name in spec["block"]])
    real_prctl = worker._prctl()

    def prctl(option, *args):
        if option == worker.PR_SET_PDEATHSIG and spec["prctl"] == "fails":
            return -1
        if option == worker.PR_SET_PDEATHSIG and spec["prctl"] == "no-op":
            return 0  # Says yes, does nothing (the read-back shows it).
        return real_prctl(option, *args)

    worker._prctl = lambda: prctl
    if spec["sigint_after_fork"]:
        real_fork = os.fork

        def fork():
            child = real_fork()
            if child:
                os.kill(os.getpid(), signal.SIGINT)  # Before the front's forwarding is in place.
            return child

        os.fork = fork

    def blocked(pid):
        with open(f"/proc/{pid}/status") as handle:
            line = next(line for line in handle if line.startswith("SigBlk:"))
        mask = int(line.split()[1], 16)
        return sorted(signal.Signals(number).name for number in range(1, 65) if mask >> (number - 1) & 1)

    def job():
        report = {"pid": os.getpid(), "mask": blocked(os.getpid()),
                  "front_mask": blocked(os.getppid()) if os.getpid() != front else None}
        if spec["sigint_after_fork"]:
            try:
                with termination.handling():
                    termination.sleep(5)
            except termination.Stopped:
                report["stopped"] = True
        with open(spec["report"], "a") as handle:
            handle.write(json.dumps(report) + "\n")
        return termination.EXIT_CODE if report.get("stopped") else 0

    front = os.getpid()
    code = worker.run(job)
    print(json.dumps({"front": front, "code": code, "mask_after": blocked(front)}), flush=True)
''')


def run_front(tmp_path, *, mutations=(), prctl="real", block=(), sigint_after_fork=False):
    """(what the front printed, the job's reports, stderr) of FRONT."""
    import json

    report = tmp_path / "report.jsonl"
    spec = tmp_path / "front.json"
    spec.write_text(json.dumps({"src": str(SRC), "report": str(report), "prctl": prctl, "block": list(block),
                                "sigint_after_fork": sigint_after_fork,
                                "mutations": [list(item) for item in mutations]}))
    script = tmp_path / "front.py"
    script.write_text(FRONT)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "LANG": "C.UTF-8"}
    done = subprocess.run([sys.executable, "-I", str(script), str(spec)], env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, timeout=20)
    printed = json.loads(done.stdout) if done.stdout.strip() else None
    reports = [json.loads(line) for line in report.read_text().splitlines()] if report.exists() else []
    return printed, reports, done.stderr.decode()


def test_a_normal_run_happens_in_the_worker(tmp_path):
    printed, reports, err = run_front(tmp_path)
    assert err == "" and printed["code"] == 0
    assert len(reports) == 1 and reports[0]["pid"] != printed["front"]


@pytest.mark.parametrize("mode", ["fails", "no-op"])
def test_a_failed_death_signal_runs_the_job_in_the_front(tmp_path, mode):
    """Security L2: the worker runs nothing; the front runs the job once, itself (the 011c way)."""
    printed, reports, err = run_front(tmp_path, prctl=mode)
    assert err == "" and printed["code"] == 0
    assert [report["pid"] for report in reports] == [printed["front"]]


@pytest.mark.parametrize("mode", ["fails", "no-op"])
def test_proof_the_death_signal_is_checked(tmp_path, mode):
    printed, reports, err = run_front(tmp_path, prctl=mode, mutations=[
        ("        if not set_death_signal(prctl):\n", "        if not (set_death_signal(prctl) or True):\n")])
    assert [report["pid"] for report in reports] != [printed["front"]]


def test_proof_the_read_back_is_needed(tmp_path):
    printed, reports, err = run_front(tmp_path, prctl="no-op", mutations=[
        ("    return value.value == DEATH_SIGNAL\n", "    return True\n")])
    assert [report["pid"] for report in reports] != [printed["front"]]


SIGNAL_NAMES = sorted(signal.Signals(number).name for number in termination.SIGNALS)


def test_the_masks_around_the_fork(tmp_path):
    """Review-6 N1: the worker and the front run with the old mask minus the stop signals (so no child
    inherits them blocked); the front's old mask comes back afterwards."""
    printed, reports, err = run_front(tmp_path, block=["SIGUSR1", "SIGTERM"])
    assert err == "" and printed["code"] == 0
    assert reports[0]["mask"] == ["SIGUSR1"]
    assert reports[0]["front_mask"] == ["SIGUSR1"]
    assert printed["mask_after"] == ["SIGTERM", "SIGUSR1"]


def test_proof_the_worker_restores_the_mask(tmp_path):
    printed, reports, err = run_front(tmp_path, block=["SIGUSR1"], mutations=[
        ("            signal.pthread_sigmask(signal.SIG_SETMASK, _unblocked(mask))\n            code = job()",
         "            code = job()")])
    assert reports[0]["mask"] == sorted(["SIGUSR1", *SIGNAL_NAMES])


def test_a_signal_right_after_the_fork_is_forwarded(tmp_path):
    """Review-6 N1: a SIGINT before the front's handlers are in is held back, then forwarded."""
    printed, reports, err = run_front(tmp_path, sigint_after_fork=True)
    assert err == ""
    assert printed["code"] == termination.EXIT_CODE
    assert len(reports) == 1 and reports[0].get("stopped")


def test_proof_a_signal_before_the_jobs_handling_is_kept(tmp_path):
    printed, reports, err = run_front(tmp_path, sigint_after_fork=True, mutations=[
        ("            termination.record_early()", "            pass")])
    assert printed["code"] != termination.EXIT_CODE


def test_proof_the_stop_signals_are_blocked_before_the_fork(tmp_path):
    printed, reports, err = run_front(tmp_path, sigint_after_fork=True, mutations=[
        ("    mask = signal.pthread_sigmask(signal.SIG_BLOCK, termination.SIGNALS)\n",
         "    mask = signal.pthread_sigmask(signal.SIG_BLOCK, [])\n")])
    assert "KeyboardInterrupt" in err
