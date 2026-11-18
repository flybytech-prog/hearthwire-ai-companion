"""Task 011c: a stopped helper run stops the children it started, and only those.

The Hyprland app stops a helper with SIGTERM (its time limit, a disconnected
or destroyed source, quitting), and so does a logout. With no handler, Python
ends at once. No ``finally`` runs, and a passphrase dialog, a
gocryptfs that has not mounted yet or the ``-passwd`` relay keeps running with
nobody waiting for it: the user could still type into that dialog, and the
folder would mount with no front end.

``handling()`` (cli.py, for --vault and --prompts only) turns SIGTERM, SIGHUP
and SIGINT into a flag. The handler itself never raises, so no exception can
start in the middle of other code. The flag is acted on only where the helper
waits for something that can take a long time: a child that may show a dialog
(``wait``), the vault lock or a poll loop (``sleep``). Those raise ``Stopped``.
The flows' own ``finally`` and ``except Stopped`` blocks then stop the step's
children (``stop``), unmount a mount that came up before the step finished, and
remove a half-made folder or pending file. cli.py prints ``reply()`` and
exits with ``EXIT_CODE``. A signal that comes after the last such wait lets the
run finish its short file work and print its normal reply.

Every child that can wait for the user is started in its own process group
(``process_group=0``), so the group id is the child's pid. ``stop`` signals
that group only while the child is not yet reaped, so the id cannot have been
reused by anyone else. It reaches the child and whatever the child started
and kept in its group (the dialog under gocryptfs, the relay and its dialog).
It never reaches the helper's own group or a front end. When the child is not
its own group's leader, only the child is signalled. A child that already
exited is only reaped and its group is never signalled. One example is a
gocryptfs whose mount came up and whose parent exited 0: that daemon is the
user's open folder.

The Plasma widget's executable engine does not send SIGTERM: it deletes the
QProcess of a dropped source, which is SIGKILL. Nothing can handle that, so
from the command line these jobs run in a worker process (task 011d,
``worker.py``): the helper process only waits for it and forwards stop
signals, and when the helper process is killed the kernel sends the worker
SIGTERM. The stop below then runs in the worker.

``handling()`` also sets SIGCHLD to its default for the run (cli.main does
so for every command, task 011d). With SIGCHLD
ignored (inherited), the kernel reaps exited children itself: exit codes are
lost and a pid could be reused while we still hold it. A child that was
reaped elsewhere is never signalled.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Optional

SIGNALS = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
# One fixed exit status for every stop signal (128 + SIGTERM).
EXIT_CODE = 143
ERROR = "interrupted"
# How long a stopped step's group gets after SIGTERM before SIGKILL. When the
# app quits, it waits only 1000 ms after its SIGTERM before it kills the helper
# (~ProcessRunner; forceStop gives 3 s). Two stops in a row (_passwd) and an
# unmount have to fit in that.
STOP_GRACE = 0.3
# How long a step that already has everything it needs may still take after a
# stop signal before it is stopped anyway (vault.FINISH_TIMEOUT, the wallet slot
# commit's kwallet-query -w).
FINISH_TIMEOUT = 10.0
# Longest gap between two looks at the flag or a child while waiting.
POLL_INTERVAL = 0.05
_FIRST_POLL = 0.001


class Stopped(BaseException):
    """A stop signal came; raised only at a wait point.

    A BaseException, so no flow's ``except HelperError``, ``except OSError`` or
    ``except Exception`` takes it for an ordinary failure.
    """


class _State:
    signal: Optional[int] = None
    # Set by record_early(): the next handling() keeps a signal that came before it.
    early: bool = False


_STATE = _State()


def reply() -> dict[str, object]:
    return {"ok": False, "error": ERROR}


def _record(signum: int, _frame: object) -> None:
    if _STATE.signal is None:
        _STATE.signal = signum


def record_early() -> None:
    """Task 011d, in the worker before its job starts: record stop signals from now on (one ignored
    stays ignored), and let the job's ``handling()`` see one that came before it."""
    _STATE.signal = None
    _STATE.early = True
    for number in SIGNALS:
        if signal.getsignal(number) is not signal.SIG_IGN:
            signal.signal(number, _record)


@contextmanager
def handling() -> Iterator[None]:
    """Record SIGTERM, SIGHUP and SIGINT instead of dying; the old handlers come back afterwards.

    A signal that is ignored when the run starts (``nohup``) stays ignored.
    """
    previous: dict[int, object] = {}
    if not _STATE.early:
        _STATE.signal = None
    _STATE.early = False
    try:
        try:
            previous[signal.SIGCHLD] = signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        except ValueError:
            pass  # Not the main thread.
        for number in SIGNALS:
            if signal.getsignal(number) is signal.SIG_IGN:
                continue
            try:
                previous[number] = signal.signal(number, _record)
            except ValueError:
                break  # Not the main thread: nothing can be installed.
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)  # type: ignore[arg-type]
        _STATE.signal = None


def requested() -> bool:
    return _STATE.signal is not None


def check() -> None:
    """Raise Stopped when a stop signal has come."""
    if _STATE.signal is not None:
        raise Stopped


def sleep(seconds: float) -> None:
    """``time.sleep`` that ends early with Stopped once a stop signal has come."""
    check()
    if seconds <= 0:
        return
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(POLL_INTERVAL, remaining))
        check()


def _probe(child: subprocess.Popen) -> Optional[bool]:
    """False: running. True: exited, not reaped yet. None: already reaped (by Popen or,
    with SIGCHLD ignored, by the kernel), so its pid may belong to someone else now.

    Never reaps (``WNOWAIT``).
    """
    if child.returncode is not None:
        return None
    try:
        return os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    except ChildProcessError:
        return None


def exited(child: subprocess.Popen) -> bool:
    """True once the child has exited (reaped or not); never reaps it, so an unreaped pid stays ours."""
    return _probe(child) is not False


def wait(child: subprocess.Popen, timeout: Optional[float] = None, *, interruptible: bool = True) -> Optional[int]:
    """The child's exit code; None when it is still running after ``timeout``.

    ``interruptible`` (a step that may wait for the user): raises Stopped when a
    stop signal comes first. The child is then still running and not reaped,
    so the caller can ``stop`` its group. A child that exited is reaped and
    its code returned, even after a stop signal: that step did finish.
    """
    if not interruptible:
        try:
            return child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
    deadline = None if timeout is None else time.monotonic() + timeout
    interval = _FIRST_POLL
    while not exited(child):
        check()
        pause = interval
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            pause = min(pause, remaining)
        time.sleep(pause)
        interval = min(interval * 2, POLL_INTERVAL)
    return child.wait()


def _signal(child: subprocess.Popen, number: int) -> None:
    """Signal the child's own process group; only the child when it is not that group's leader.

    Called only right after _probe found the child unreaped, so ``child.pid`` is still ours.
    """
    try:
        own_group = os.getpgid(child.pid) == child.pid
    except OSError:
        own_group = False
    try:
        if own_group:
            os.killpg(child.pid, number)
        else:
            os.kill(child.pid, number)
    except (ProcessLookupError, PermissionError):
        pass


def stop(child: subprocess.Popen, grace: float = STOP_GRACE) -> None:
    """Stop an unfinished step with everything it started; always reap the child.

    A child that already exited is only reaped: its group may hold a daemon that
    finished its job (a mounted gocryptfs) and is never signalled. Otherwise the
    group gets SIGTERM, ``grace`` seconds to go, then SIGKILL for anything left,
    sent while the child is still unreaped.
    """
    if child.returncode is not None:
        return
    if _probe(child) is not False:
        # Finished on its own, or reaped elsewhere: never signalled.
        child.wait()
        return
    _signal(child, signal.SIGTERM)
    deadline = time.monotonic() + grace
    interval = _FIRST_POLL
    while _probe(child) is False:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))
        interval = min(interval * 2, POLL_INTERVAL)
    if _probe(child) is not None:
        _signal(child, signal.SIGKILL)  # Confirmed unreaped (running or a zombie): still ours.
    child.wait()


__all__ = ["ERROR", "EXIT_CODE", "FINISH_TIMEOUT", "SIGNALS", "STOP_GRACE", "Stopped", "check", "exited", "handling", "record_early",
           "reply", "requested", "sleep", "stop", "wait"]
