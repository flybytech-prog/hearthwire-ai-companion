"""Opt-in usage history for the Usage tab's sparklines (round 4 idea 5, plan D70).

Layout below ``$XDG_DATA_HOME`` (when absolute, else ``~/.local/share``)::

    hearthwire/                  0700
        usage-history/           0700
            applet-<N>.json      0600, {"history_version":1,"series":[...]}, one per widget
            history.lock         0600, empty; only its flock matters (shared)

Each widget (``--applet N``, its Plasma applet id) has its own file, as the
on/off choice is per widget (audit L1). The plasmoid records only while the
user has turned history on, and clears it when they turn it off. The shared
``history.json`` of earlier builds is never read; any clear deletes it. A sample is percent USED per catalog (provider, metric)
pair; nothing else is stored: no names, plans, amounts, accounts or times
other than the hour bucket. Every directory is opened through
``webdata.open_base`` / ``open_child_dir`` (no symlinks, owner checked), the
file is replaced atomically, and replies hold codes and integers only.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import re
import stat
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Callable, Optional

from .catalog import PROVIDER_CATALOG
from .webdata import APP_DIR, HelperError, _close, _descriptors, data_base, open_base, open_child_dir, remove_entry

OPERATIONS = ("read", "record", "clear")
MAX_APPLET = 2**31
HISTORY_VERSION = 1
BUCKET_SECONDS = 3600
# Seven days of hour buckets behind the current one: at most 169 points.
KEEP_BUCKETS = 7 * 24
MAX_POINTS = KEEP_BUCKETS + 1
MAX_FILE_BYTES = 256 * 1024
MAX_PAIRS = 64
LOCK_WAIT_SECONDS = 2.0
HISTORY_DIR = "usage-history"
# The one shared file of earlier builds; only ever deleted now.
LEGACY_FILE = "history.json"
LOCK_FILE = "history.lock"
FILE_MODE = 0o600

# Codes the plasmoid knows for --usage-history; anything else is os-error.
ERRORS = frozenset({"bad-sample", "symlink", "not-directory", "not-owned", "busy", "legacy-data", "os-error"})

# Every catalog (provider, metric) pair with a percentage, in catalog order.
# extra_usage is money, not a percentage of a plan, so it is never recorded.
PAIRS: tuple[tuple[str, str], ...] = tuple(
    (entry.provider_id, metric)
    for entry in PROVIDER_CATALOG
    for metric in entry.supported_metrics
    if metric != "extra_usage"
)
_PAIR_ORDER = {pair: index for index, pair in enumerate(PAIRS)}

_SAMPLE_PAIR = re.compile(r"([a-z_]{1,32})\.([a-z_]{1,32})=(100|[1-9]?[0-9])")
# _write_file's temporary names, of any widget (and of earlier builds).
_TEMPORARY_NAME = re.compile(r"(?:history|applet-[1-9][0-9]{0,9})\.json\.[0-9a-f]{16}\.tmp")
_POLL_INTERVAL = 0.05
_WOULD_BLOCK = {errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES}

_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOCTTY
_CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC

History = dict[tuple[str, str], dict[int, int]]


def file_name(applet: int) -> str:
    """``applet-<N>.json`` for a widget id 1..2**31; anything else is a programming error."""
    if type(applet) is not int or not 1 <= applet <= MAX_APPLET:
        raise ValueError("applet id out of range")
    return f"applet-{applet}.json"


def parse_sample(text: object) -> Optional[dict[tuple[str, str], int]]:
    """``{(provider, metric): used}`` for a valid --sample, else None.

    Comma-joined ``provider.metric=N`` (N 0..100, no sign or leading zero), at
    most 64 pairs, each a tracked catalog pair, none twice.
    """
    if not isinstance(text, str):
        return None
    items = text.split(",")
    if len(items) > MAX_PAIRS:
        return None
    sample: dict[tuple[str, str], int] = {}
    for item in items:
        match = _SAMPLE_PAIR.fullmatch(item)
        if match is None:
            return None
        pair = (match.group(1), match.group(2))
        if pair not in _PAIR_ORDER or pair in sample:
            return None
        sample[pair] = int(match.group(3))
    return sample


def bucket_of(now: int) -> int:
    return now - now % BUCKET_SECONDS


def pruned(history: History, now: int) -> History:
    """Only buckets of the last seven days up to the current one."""
    newest = bucket_of(now)
    oldest = newest - KEEP_BUCKETS * BUCKET_SECONDS
    result: History = {}
    for pair, points in history.items():
        kept = {moment: used for moment, used in points.items() if oldest <= moment <= newest}
        if kept:
            result[pair] = kept
    return result


def series(history: History) -> list[dict[str, object]]:
    """Catalog order, points ascending, empty series left out."""
    result = []
    for pair in sorted(history, key=_PAIR_ORDER.__getitem__):
        points = history[pair]
        if not points:
            continue
        result.append({
            "provider_id": pair[0],
            "metric_id": pair[1],
            "points": [[moment, points[moment]] for moment in sorted(points)][-MAX_POINTS:],
        })
    return result


def encode(history: History) -> bytes:
    document = {"history_version": HISTORY_VERSION, "series": series(history)}
    return json.dumps(document, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _no_duplicates(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _no_constant(name: str) -> object:
    raise ValueError("non-finite number")


def decode(data: bytes) -> History:
    """The stored history; a corrupt, oversized or wrong-version file is empty.

    Series of pairs the catalog no longer tracks, and odd points, are skipped.
    """
    if len(data) > MAX_FILE_BYTES:
        return {}
    try:
        document = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates,
                              parse_constant=_no_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return {}
    if not isinstance(document, dict) or set(document) != {"history_version", "series"}:
        return {}
    if type(document["history_version"]) is not int or document["history_version"] != HISTORY_VERSION:
        return {}
    entries = document["series"]
    if not isinstance(entries, list):
        return {}
    history: History = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        provider_id, metric_id, points = entry.get("provider_id"), entry.get("metric_id"), entry.get("points")
        if not isinstance(provider_id, str) or not isinstance(metric_id, str) or not isinstance(points, list):
            continue
        pair = (provider_id, metric_id)
        if pair not in _PAIR_ORDER:
            continue
        kept = history.setdefault(pair, {})
        for point in points:
            if (isinstance(point, list) and len(point) == 2
                    and type(point[0]) is int and type(point[1]) is int
                    and point[0] >= 0 and point[0] % BUCKET_SECONDS == 0
                    and 0 <= point[1] <= 100):
                kept[point[0]] = point[1]
    return {pair: points for pair, points in history.items() if points}


# --- the folder ---------------------------------------------------------------------------------------


def _history_directory(environ: Optional[Mapping[str, str]], opened: list[int], *, create: bool) -> Optional[int]:
    """``<data>/hearthwire/usage-history``; None when a part is missing and not ``create``.

    Never created while the previous version's data waits for the installer:
    the new folder would then be a conflict.
    """
    if create:
        from .legacy import refuse_legacy_data  # Imported here: legacy itself builds on this module.

        refuse_legacy_data(environ)
    parent = open_base(data_base(environ), create=create)
    if parent is None:
        return None
    opened.append(parent)
    for name in (APP_DIR, HISTORY_DIR):
        parent = open_child_dir(parent, name, create=create)
        if parent is None:
            return None
        opened.append(parent)
    return parent


def _file_error(error: OSError) -> HelperError:
    return HelperError("symlink" if error.errno == errno.ELOOP else "os-error")


@contextmanager
def _locked(
    directory: int,
    *,
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
) -> Iterator[None]:
    """Hold ``history.lock`` (created 0600 when missing); ``busy`` after two seconds."""
    try:
        descriptor = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NOCTTY,
                             FILE_MODE, dir_fd=directory)
    except OSError as error:
        raise _file_error(error) from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise HelperError("os-error")
        if info.st_uid != os.getuid():
            raise HelperError("not-owned")
        if stat.S_IMODE(info.st_mode) != FILE_MODE:
            os.fchmod(descriptor, FILE_MODE)
        deadline = monotonic() + LOCK_WAIT_SECONDS
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if error.errno not in _WOULD_BLOCK:
                    raise HelperError("os-error") from None
            if monotonic() >= deadline:
                raise HelperError("busy")
            sleep(_POLL_INTERVAL)
        yield
    except OSError:
        raise HelperError("os-error") from None
    finally:
        _close(descriptor)  # Closing releases the flock.


def _read_file(directory: int, name: str) -> Optional[bytes]:
    """The file's bytes, None when missing; an oversized file reads as empty."""
    try:
        descriptor = os.open(name, _READ_FLAGS, dir_fd=directory)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise _file_error(error) from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise HelperError("os-error")
        if info.st_uid != os.getuid():
            raise HelperError("not-owned")
        if info.st_size > MAX_FILE_BYTES:
            return b""
        data = b""
        while len(data) <= MAX_FILE_BYTES:
            chunk = os.pread(descriptor, MAX_FILE_BYTES + 1 - len(data), len(data))
            if not chunk:
                break
            data += chunk
        return b"" if len(data) > MAX_FILE_BYTES else data
    except OSError:
        raise HelperError("os-error") from None
    finally:
        _close(descriptor)


def _unlink(directory: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=directory)
    except OSError:
        pass


def _remove_file(directory: int, name: str) -> None:
    """Delete ``name`` (a symlink itself, never its target); missing is fine, else os-error."""
    try:
        os.unlink(name, dir_fd=directory)
    except FileNotFoundError:
        pass
    except OSError:
        raise HelperError("os-error") from None


def _clear_stale_temporaries(directory: int) -> None:
    """Delete temporaries a crashed writer left; called under the lock."""
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        if _TEMPORARY_NAME.fullmatch(name):
            _unlink(directory, name)


def _write_file(directory: int, name: str, data: bytes) -> None:
    """Replace ``name`` atomically: O_EXCL temporary, fsync, rename, fsync dir."""
    temporary = f"{name}.{os.urandom(8).hex()}.tmp"
    try:
        descriptor = os.open(temporary, _CREATE_FLAGS, FILE_MODE, dir_fd=directory)
    except OSError as error:
        raise _file_error(error) from None
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view):]
        os.fsync(descriptor)
        os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    except OSError:
        _unlink(directory, temporary)
        raise HelperError("os-error") from None
    finally:
        _close(descriptor)


# --- operations ---------------------------------------------------------------------------------------


def _reply(history: History, now: int) -> dict[str, object]:
    return {
        "ok": True,
        "history_version": HISTORY_VERSION,
        "bucket_seconds": BUCKET_SECONDS,
        "now": now,
        "series": series(history),
    }


def _stored(history: History, data: Optional[bytes]) -> bool:
    """The file already holds exactly ``history`` (or is rightly missing)."""
    return encode(history) == data if history else data is None


def _store(directory: int, name: str, history: History, data: Optional[bytes]) -> None:
    """Write ``history`` unless the file holds it already; delete the file when it is empty.

    Called under the lock.
    """
    if _stored(history, data):
        return
    if not history:
        _remove_file(directory, name)
        return
    encoded = encode(history)
    if len(encoded) > MAX_FILE_BYTES:
        raise HelperError("os-error")
    _write_file(directory, name, encoded)


def read(
    applet: int,
    environ: Optional[Mapping[str, str]] = None,
    *,
    clock: Callable[[], float] = time.time,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """The widget's last seven days (audit L2: the file is pruned here too).

    Creates nothing while there is nothing to prune. When the file holds
    older, future or odd points, it is rewritten under the lock exactly as
    ``record`` writes, or deleted when nothing of the last seven days is
    left. A lock held past two seconds only defers that: the reply is the
    same.
    """
    name = file_name(applet)
    with _descriptors() as opened:
        directory = _history_directory(environ, opened, create=False)
        data = None if directory is None else _read_file(directory, name)
        now = int(clock())
        history = pruned(decode(data or b""), now)
        if directory is None or _stored(history, data):
            return _reply(history, now)
        try:
            with _locked(directory, monotonic=monotonic, sleep=sleep):
                _clear_stale_temporaries(directory)
                now = int(clock())
                data = _read_file(directory, name)
                history = pruned(decode(data or b""), now)
                _store(directory, name, history, data)
        except HelperError as error:
            if error.code != "busy":
                raise
    return _reply(history, now)


def record(
    applet: int,
    sample_text: object,
    environ: Optional[Mapping[str, str]] = None,
    *,
    clock: Callable[[], float] = time.time,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Store one sample in the widget's current hour bucket (last wins) and reply as ``read``."""
    name = file_name(applet)
    sample = parse_sample(sample_text)
    if sample is None:
        raise HelperError("bad-sample")
    with _descriptors() as opened:
        directory = _history_directory(environ, opened, create=True)
        if directory is None:
            raise HelperError("os-error")
        with _locked(directory, monotonic=monotonic, sleep=sleep):
            _clear_stale_temporaries(directory)
            now = int(clock())
            data = _read_file(directory, name)
            history = pruned(decode(data or b""), now)
            bucket = bucket_of(now)
            for pair, used in sample.items():
                history.setdefault(pair, {})[bucket] = used
            _store(directory, name, history, data)
    return _reply(history, now)


def clear(
    applet: Optional[int],
    environ: Optional[Mapping[str, str]] = None,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Delete one widget's history (``applet``) or, with None, all of ``usage-history/``.

    Either also deletes the shared ``history.json`` of earlier builds and
    leftover temporaries; the folder goes once no widget's file is left in
    it (only the lock). Nothing there is success.
    """
    name = None if applet is None else file_name(applet)
    with _descriptors() as opened:
        parent = open_base(data_base(environ), create=False)
        if parent is None:
            return {"ok": True}
        opened.append(parent)
        app = open_child_dir(parent, APP_DIR, create=False)
        if app is None:
            return {"ok": True}
        opened.append(app)
        directory = open_child_dir(app, HISTORY_DIR, create=False)
        if directory is None:
            return {"ok": True}
        opened.append(directory)
        with _locked(directory, monotonic=monotonic, sleep=sleep):
            if name is not None:
                for doomed in (name, LEGACY_FILE):
                    _remove_file(directory, doomed)
                _clear_stale_temporaries(directory)
                try:
                    left = set(os.listdir(directory))
                except OSError:
                    raise HelperError("os-error") from None
                if left - {LOCK_FILE}:
                    return {"ok": True}
            # A recorder that was waiting finds its folder gone and fails.
            remove_entry(app, HISTORY_DIR)
    return {"ok": True}


def run(
    operation: str,
    *,
    applet: Optional[int] = None,
    every_applet: bool = False,
    sample: Optional[str] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> dict[str, object]:
    """CLI entry: a reply that never carries a path or text.

    ``applet`` is required, except for ``clear`` with ``every_applet``
    (``--all``), which takes none.
    """
    if every_applet != (applet is None) or (every_applet and operation != "clear"):
        raise ValueError("Give an applet id, or --all for clear only.")
    try:
        if operation == "read":
            return read(applet, environ)  # type: ignore[arg-type]
        if operation == "record":
            return record(applet, sample, environ)  # type: ignore[arg-type]
        if operation == "clear":
            return clear(applet, environ)
        raise ValueError("Unsupported usage history operation.")
    except HelperError as error:
        return {"ok": False, "error": error.code if error.code in ERRORS else "os-error"}
    except OSError:
        return {"ok": False, "error": "os-error"}


__all__ = ["BUCKET_SECONDS", "HISTORY_VERSION", "MAX_APPLET", "MAX_POINTS", "OPERATIONS", "PAIRS", "file_name",
           "parse_sample", "run"]
