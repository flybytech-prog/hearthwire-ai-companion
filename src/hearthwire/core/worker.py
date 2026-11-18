"""Task 011d: --vault and --prompts run in a worker that a SIGKILL of the helper still stops.

The Plasma widget's executable engine ends a dropped source by deleting its
QProcess, which is SIGKILL. Nothing can handle that, so the 011c clean stop
(``termination.py``) never ran in the widget: a passphrase dialog, or the
``-fg`` child of a real gocryptfs with its dialog, outlived the helper and
could still mount the folder.

So the helper process a front end starts (the "front") only forks a worker
(``os.fork``, no exec) and waits for it:

- The worker first asks the kernel for SIGTERM when the front dies
  (``prctl(PR_SET_PDEATHSIG, SIGTERM)``, read back with ``PR_GET_PDEATHSIG``),
  then checks that the front is still its parent. If the front died before
  that, the worker exits at once and runs nothing. If the prctl fails (a
  seccomp filter), the worker runs nothing either and the front runs the job
  itself, as when ``prctl`` is missing. It also makes itself not dumpable
  (``PR_SET_DUMPABLE`` 0: no core dump, no same-user ptrace or
  ``/proc/<pid>/mem`` read of the prompt text it holds); that may fail.
- The death signal always stops the job (fail closed): the worker unblocks
  SIGTERM, SIGHUP and SIGINT, and a SIGTERM that was ignored at start is set
  back to its default, so ``termination.handling()`` records it. Only SIGHUP
  and SIGINT ignored at start stay ignored in the worker. Then it runs the 011c job unchanged: ``termination.handling()``,
  its children's process groups and undo steps, and the vault lock, which only
  the worker ever takes. It prints the one reply on the inherited stdout and
  exits with the job's status.
- The front holds no lock and opens nothing. It forwards SIGTERM, SIGHUP and
  SIGINT to the worker (a signal ignored at start stays ignored in the front;
  a blocked one is unblocked once the forwarding is in place), waits for it
  and exits with its status. A forwarded stop and the death signal are the
  same stop: ``termination`` records the first signal only.
- A SIGKILL of the front therefore becomes a SIGTERM to the worker: it stops
  its dialogs and gocryptfs, undoes the step and releases the lock itself.
  It keeps the lock until then, also while a step that has all it needs
  finishes (``vault.FINISH_TIMEOUT``).
- The front never returns before the worker is reaped, so a worker never
  outlives a front that exits by any other way than SIGKILL.

The death signal belongs to the thread that forked: when that thread ends,
the kernel sends it. The front forks from its only thread, so that is the
front's exit. A fork is safe only while the process has one thread: with
more (or no ``prctl``, a failed prctl, or a failed fork) the job runs in
this process as in 011c instead.

Stop signals are blocked from just before the fork: the front unblocks them
once it forwards them, the worker once its death signal is set. A signal in
that window is then forwarded (front) or recorded for the job
(``termination.record_early``), so the job stops at its first check. The worker's children get the old
mask without the stop signals.

The forwarding pid is always ours: the front never reaps the worker before
forwarding has ended (``waitid`` with ``WNOWAIT`` first, then the reap).
"""

from __future__ import annotations

import os
import signal
import sys
import threading
from collections.abc import Callable
from typing import Optional

from . import termination

PR_SET_PDEATHSIG = 1
PR_GET_PDEATHSIG = 2
PR_SET_DUMPABLE = 4
DEATH_SIGNAL = signal.SIGTERM
# The worker's status when the front was already gone (nobody reads it).
GONE_CODE = termination.EXIT_CODE
# A worker that died of an uncaught exception.
FAILED_CODE = 1
# The worker could not set its death signal and ran nothing: the front runs the job itself.
# No job returns it (cli.main returns 0, 1, 2 or 143).
NO_DEATH_SIGNAL_CODE = 120

_Prctl = Callable[[int, int, int, int, int], int]


def _prctl() -> Optional[_Prctl]:
    """libc's prctl(2), or None when it cannot be found."""
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        function = libc.prctl
    except (ImportError, OSError, AttributeError):
        return None
    function.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    function.restype = ctypes.c_int
    return function


def single_threaded() -> bool:
    """True when this process has exactly one thread (Python's and the kernel's count)."""
    if threading.active_count() != 1:
        return False
    try:
        return len(os.listdir("/proc/self/task")) == 1
    except OSError:
        return False


def set_death_signal(prctl: _Prctl) -> bool:
    """In the worker, right after the fork: SIGTERM when the front dies; True when it is set (read back)."""
    import ctypes

    if prctl(PR_SET_PDEATHSIG, DEATH_SIGNAL, 0, 0, 0) != 0:
        return False
    value = ctypes.c_int(0)
    if prctl(PR_GET_PDEATHSIG, ctypes.addressof(value), 0, 0, 0) != 0:
        return False
    return value.value == DEATH_SIGNAL


def _not_dumpable(prctl: _Prctl) -> None:
    """No core dump and no same-user ptrace of the worker (security I3); a failure is not fatal."""
    prctl(PR_SET_DUMPABLE, 0, 0, 0, 0)


def _unblocked(mask: set[int]) -> set[int]:
    """``mask`` without the stop signals: what the worker and the front run with."""
    return set(mask) - set(termination.SIGNALS)


def _flush() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (AttributeError, OSError, ValueError):
            pass  # No stream, or the front end stopped reading (a closed pipe): nothing to tell.


def _worker(job: Callable[[], int], prctl: _Prctl, front: int, mask: set[int]) -> None:
    """The forked worker: run the job, then leave without returning into the front's stack.

    The stop signals are still blocked here (``run``).
    """
    code = GONE_CODE
    try:
        _not_dumpable(prctl)
        if signal.getsignal(DEATH_SIGNAL) is signal.SIG_IGN:
            # Ignored at start would make the death signal a no-op (security L1): fail closed.
            signal.signal(DEATH_SIGNAL, signal.SIG_DFL)
        if not set_death_signal(prctl):
            code = NO_DEATH_SIGNAL_CODE
        elif os.getppid() == front:
            # The check comes after the prctl: a front that died before it is seen here, one that
            # dies after it sends the signal.
            termination.record_early()  # A stop before the job's handling() is not lost (review-6 N1).
            signal.pthread_sigmask(signal.SIG_SETMASK, _unblocked(mask))
            code = job()
    except BaseException:  # noqa: BLE001 - never unwind into the front's code
        code = FAILED_CODE
    finally:
        _flush()
        os._exit(code)


def _exit_code(status: int) -> int:
    """The worker's exit status; 128 + N when signal N ended it, as a shell reports it."""
    code = os.waitstatus_to_exitcode(status)
    return 128 - code if code < 0 else code


def _front(worker: int, mask: set[int]) -> tuple[int, bool]:
    """Forward stop signals to the worker until it exited, then reap it; its exit status and
    whether a stop signal came.

    The stop signals are blocked on entry (``run``); the old mask comes back on the way out.
    """
    state = {"forwarding": True, "stopped": False}

    def forward(number: int, _frame: object) -> None:
        state["stopped"] = True
        if state["forwarding"]:
            try:
                os.kill(worker, number)  # Not reaped yet, so the pid is still the worker's.
            except ProcessLookupError:
                pass

    previous: dict[int, object] = {}
    reaped: Optional[int] = None
    try:
        for number in termination.SIGNALS:
            if signal.getsignal(number) is signal.SIG_IGN:
                continue  # Ignored at start: the worker inherited that and ignores it too.
            previous[number] = signal.signal(number, forward)
        # Forwarding is in place: a signal that came since the fork is forwarded now.
        signal.pthread_sigmask(signal.SIG_SETMASK, _unblocked(mask))
        try:
            # Blocks without reaping; a forwarded signal only interrupts it for a moment (PEP 475).
            os.waitid(os.P_PID, worker, os.WEXITED | os.WNOWAIT)
        except ChildProcessError:
            pass
        state["forwarding"] = False
        try:
            _, status = os.waitpid(worker, 0)
            reaped = _exit_code(status)
        except ChildProcessError:
            reaped = FAILED_CODE
    finally:
        if reaped is None:
            # Only an exception in the front gets here: the worker stops and is waited for.
            state["forwarding"] = False
            try:
                os.kill(worker, DEATH_SIGNAL)
                os.waitpid(worker, 0)
            except ChildProcessError:
                pass
            except ProcessLookupError:
                pass
        for number, handler in previous.items():
            signal.signal(number, handler)  # type: ignore[arg-type]
        signal.pthread_sigmask(signal.SIG_SETMASK, mask)
    assert reaped is not None  # Set on every way out that returns.
    return reaped, state["stopped"]


def run(job: Callable[[], int]) -> int:
    """Run ``job`` (it prints the reply, returns the exit status) in a worker; the status.

    In this process instead when a fork is not safe or not possible.
    """
    prctl = _prctl()
    if prctl is None or not single_threaded():
        return job()
    front = os.getpid()
    _flush()  # Nothing buffered may be written twice.
    mask = signal.pthread_sigmask(signal.SIG_BLOCK, termination.SIGNALS)
    try:
        worker = os.fork()
    except OSError:
        signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        return job()
    if worker == 0:
        _worker(job, prctl, front, mask)
    code, stopped = _front(worker, mask)
    if code == NO_DEATH_SIGNAL_CODE:
        # The worker ran nothing (security L2). A stop that came meanwhile ends the run here.
        return termination.EXIT_CODE if stopped else job()
    return code


__all__ = ["DEATH_SIGNAL", "FAILED_CODE", "GONE_CODE", "NO_DEATH_SIGNAL_CODE", "PR_GET_PDEATHSIG",
           "PR_SET_DUMPABLE", "PR_SET_PDEATHSIG", "run", "set_death_signal", "single_threaded"]
