"""Saved prompts and personas for the Chat tab, inside the unlocked encrypted folder.

Layout below the verified gocryptfs mount (``vault.verified_mount()``)::

    library/                 0700
        prompt-<id>.txt      0600, one saved prompt (UTF-8)
        persona-<id>.txt     0600, one saved persona (a system prompt)
        personas.json        0600, {"<model>": <persona id>}: names and ints only

Nothing is ever written outside the mount: while the folder is locked every
command fails with ``locked`` and the plasmoid keeps prompts in memory only.

New text is typed into a kdialog text box this helper starts with its stdout
on a new ``O_EXCL`` file inside ``library/``, so the text never passes through
argv or the plasmoid's config. There is no initial text (that would be argv):
editing is Replace. The vault lock is not held while the dialog is open, only
before and after; the open file keeps the mount busy until the dialog ends.

``list`` returns the saved text to the plasmoid on stdout. This is the one
place where library text passes through the helper (plan D53); it is never
logged or written anywhere else. Every other reply holds codes and integers.
"""

from __future__ import annotations

import errno
import json
import os
import re
import shutil
import stat
import subprocess
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Optional

from . import vault
from .webdata import HelperError, _close, _descriptors, open_child_dir

OPERATIONS = ("list", "add", "replace", "remove", "set-persona")
KINDS = ("prompt", "persona")
LIBRARY_DIR = "library"
PERSONAS_FILE = "personas.json"
FILE_MODE = 0o600

# Plan D67: at most 100 items; a prompt holds up to 32000 characters, a persona 8000.
MAX_ITEMS = 100
MAX_CHARS = {"prompt": 32000, "persona": 8000}
# UTF-8 needs at most 4 bytes a character; kdialog adds one newline.
MAX_BYTES = {kind: chars * 4 + 1 for kind, chars in MAX_CHARS.items()}
MAX_PERSONA_MODELS = 200
MAX_PERSONAS_BYTES = 65536
MAX_ID = 2**31
MODEL_NAME = re.compile(r"[A-Za-z0-9._:/+-]{1,200}")

_ITEM_NAME = re.compile(r"(prompt|persona)-([1-9][0-9]{0,9})\.txt")
_PENDING_NAME = re.compile(r"pending-([1-9][0-9]{0,9})-[0-9a-f]{16}\.tmp")

# Fixed kdialog text box labels (D26); none may start with "-".
TITLE = "Hearthwire"
LABELS = {
    "prompt": "Type or paste the prompt to save in the Hearthwire library.",
    "persona": "Type or paste the personality (system prompt) to save in the Hearthwire library.",
}

_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_CREATE_FLAGS = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_KDIALOG_CANCEL = 1


def valid_model(name: object) -> bool:
    return isinstance(name, str) and MODEL_NAME.fullmatch(name) is not None and not name.startswith("-")


def item_name(kind: str, item: int) -> str:
    return f"{kind}-{item}.txt"


def dialog_argv(kdialog: str, kind: str) -> list[str]:
    return [kdialog, "--title", TITLE, "--textinputbox", LABELS[kind]]


def _check_dialog_argv(argv: list[str]) -> None:
    if not argv or not os.path.isabs(argv[0]) or os.path.basename(argv[0]) != "kdialog":
        raise HelperError("os-error")
    if argv not in (dialog_argv(argv[0], kind) for kind in KINDS):
        raise HelperError("os-error")


# --- the library folder ---------------------------------------------------------------------------


@contextmanager
def _root(environ: Optional[Mapping[str, str]]) -> Iterator[int]:
    """The verified mount root under the vault lock; ``locked`` when nothing is mounted."""
    try:
        with vault.verified_mount(environ) as root:
            yield root
    except HelperError as error:
        if error.code != "not-verified":
            raise
        ctx = vault.context(environ, find_tools=False)
        if vault.mount_entry(ctx.mountpoint) is None:
            raise HelperError("locked") from None
        raise


@contextmanager
def _library(environ: Optional[Mapping[str, str]], *, create: bool) -> Iterator[Optional[int]]:
    with _root(environ) as root:
        library = open_child_dir(root, LIBRARY_DIR, create=create)
        try:
            yield library
        finally:
            _close(library)


def _items(library: int) -> dict[int, str]:
    """{id: kind} for every well-named regular file of ours."""
    found: dict[int, str] = {}
    try:
        names = os.listdir(library)
    except OSError:
        raise HelperError("os-error") from None
    for name in names:
        match = _ITEM_NAME.fullmatch(name)
        if match is None or int(match.group(2)) > MAX_ID:
            continue
        try:
            info = os.stat(name, dir_fd=library, follow_symlinks=False)
        except OSError:
            continue
        if stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid():
            found[int(match.group(2))] = match.group(1)
    return found


def _read_bytes(library: int, name: str, limit: int) -> Optional[bytes]:
    """A regular file of ours, at most ``limit`` bytes, never through a link."""
    try:
        descriptor = os.open(name, _READ_FLAGS, dir_fd=library)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > limit:
            return None
        return _read_all(descriptor, limit)
    except OSError:
        return None
    finally:
        _close(descriptor)


def _read_all(descriptor: int, limit: int, offset: int = 0) -> Optional[bytes]:
    data = b""
    while len(data) <= limit:
        chunk = os.pread(descriptor, limit + 1 - len(data), offset + len(data))
        if not chunk:
            break
        data += chunk
    return None if len(data) > limit else data


def decode_text(data: bytes, kind: str) -> str:
    """Saved text from file bytes; raises cancelled / not-text / too-long."""
    if len(data) > MAX_BYTES[kind]:
        raise HelperError("too-long")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise HelperError("not-text") from None
    if "\x00" in text:
        raise HelperError("not-text")
    if text.endswith("\n"):
        text = text[:-1]  # kdialog ends its answer with one newline.
    if not text.strip():
        raise HelperError("cancelled")
    if len(text) > MAX_CHARS[kind]:
        raise HelperError("too-long")
    return text


def _read_personas(library: int, items: dict[int, str]) -> dict[str, int]:
    data = _read_bytes(library, PERSONAS_FILE, MAX_PERSONAS_BYTES)
    if not data:
        return {}
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for model, item in value.items():
        if (valid_model(model) and type(item) is int and items.get(item) == "persona"
                and len(result) < MAX_PERSONA_MODELS):
            result[model] = item
    return result


def _write_file(library: int, name: str, data: bytes) -> None:
    """Write ``name`` atomically (O_EXCL temporary, fsync, rename)."""
    temporary = f"{name}.{os.urandom(8).hex()}.new"
    try:
        descriptor = os.open(temporary, _CREATE_FLAGS, FILE_MODE, dir_fd=library)
    except OSError:
        raise HelperError("os-error") from None
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view):]
        os.fsync(descriptor)
        os.rename(temporary, name, src_dir_fd=library, dst_dir_fd=library)
    except OSError:
        _unlink(library, temporary)
        raise HelperError("os-error") from None
    finally:
        _close(descriptor)


def _write_personas(library: int, personas: dict[str, int]) -> None:
    data = json.dumps(personas, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    if len(data) > MAX_PERSONAS_BYTES:
        raise HelperError("full")
    _write_file(library, PERSONAS_FILE, data)


def _unlink(library: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=library)
    except OSError:
        pass


def _clear_stale_pending(library: int) -> None:
    """Delete dialog files left by helpers that are no longer running."""
    try:
        names = os.listdir(library)
    except OSError:
        return
    for name in names:
        match = _PENDING_NAME.fullmatch(name)
        if match is None:
            continue
        try:
            os.kill(int(match.group(1)), 0)
            continue  # Still running (or not ours to judge): leave it.
        except ProcessLookupError:
            _unlink(library, name)
        except (PermissionError, OverflowError, OSError):
            continue


# --- the dialog --------------------------------------------------------------------------------------


def _kdialog() -> str:
    path = shutil.which("kdialog")
    if not path or not os.path.isabs(path):
        raise HelperError("missing-tool")
    return path


def _run_dialog(argv: list[str], stdout: int) -> int:
    """kdialog with stdout on our file; argv list, no shell, stdin/stderr on /dev/null."""
    _check_dialog_argv(argv)
    try:
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            check=False,
        )
    except OSError:
        raise HelperError("missing-tool") from None
    return completed.returncode


def _same_directory(first: int, second: int) -> bool:
    one, two = os.fstat(first), os.fstat(second)
    return (one.st_dev, one.st_ino) == (two.st_dev, two.st_ino)


def _ask(environ: Optional[Mapping[str, str]], kind: str, target: Optional[int]) -> int:
    """Run the text box into a new file and file it as ``target`` (or the next id).

    Returns the item id. The dialog runs without the vault lock; afterwards,
    under the lock again, the library must still be the same directory.
    """
    kdialog = _kdialog()
    pending = f"pending-{os.getpid()}-{os.urandom(8).hex()}.tmp"
    with _descriptors() as opened:
        with _library(environ, create=True) as library:
            if library is None:
                raise HelperError("os-error")
            _clear_stale_pending(library)
            items = _items(library)
            if target is None and len(items) >= MAX_ITEMS:
                raise HelperError("full")
            if target is not None and items.get(target) != kind:
                raise HelperError("absent")
            held = os.dup(library)
            opened.append(held)
            try:
                output = os.open(pending, _CREATE_FLAGS, FILE_MODE, dir_fd=library)
            except OSError:
                raise HelperError("os-error") from None
            opened.append(output)
        filed = False
        try:
            code = _run_dialog(dialog_argv(kdialog, kind), output)
            if code == _KDIALOG_CANCEL:
                raise HelperError("cancelled")
            if code != 0:
                raise HelperError("os-error")
            size = os.fstat(output).st_size
            if size == 0:
                raise HelperError("cancelled")
            if size > MAX_BYTES[kind]:
                raise HelperError("too-long")
            data = _read_all(output, MAX_BYTES[kind])
            if data is None:
                raise HelperError("too-long")
            decode_text(data, kind)
            os.fsync(output)
            with _library(environ, create=False) as library:
                if library is None or not _same_directory(library, held):
                    raise HelperError("not-verified")
                items = _items(library)
                if target is None:
                    if len(items) >= MAX_ITEMS:
                        raise HelperError("full")
                    item = max(items, default=0) + 1
                    if item > MAX_ID:
                        raise HelperError("full")
                else:
                    if items.get(target) != kind:
                        raise HelperError("absent")
                    item = target
                try:
                    os.rename(pending, item_name(kind, item), src_dir_fd=library, dst_dir_fd=library)
                    os.fsync(library)
                except OSError:
                    raise HelperError("os-error") from None
                filed = True
            return item
        except OSError:
            raise HelperError("os-error") from None
        finally:
            if not filed:
                _unlink(held, pending)


# --- operations --------------------------------------------------------------------------------------


def list_items(environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    with _library(environ, create=False) as library:
        if library is None:
            return {"ok": True, "items": [], "personas": {}}
        items = _items(library)
        result = []
        for item in sorted(items):
            if len(result) >= MAX_ITEMS:
                break
            kind = items[item]
            data = _read_bytes(library, item_name(kind, item), MAX_BYTES[kind])
            if data is None:
                continue
            try:
                text = decode_text(data, kind)
            except HelperError:
                continue  # Unreadable or odd files are skipped, never shown.
            result.append({"id": item, "kind": kind, "text": text})
        listed = {entry["id"]: entry["kind"] for entry in result}
        return {"ok": True, "items": result, "personas": _read_personas(library, listed)}


def add(kind: str, environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    if kind not in KINDS:
        raise ValueError("Unsupported item kind.")
    return {"ok": True, "id": _ask(environ, kind, None)}


def replace(item: int, environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    with _library(environ, create=False) as library:
        kind = None if library is None else _items(library).get(item)
    if kind is None:
        raise HelperError("absent")
    return {"ok": True, "id": _ask(environ, kind, item)}


def remove(item: int, environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    with _library(environ, create=False) as library:
        if library is None:
            raise HelperError("absent")
        items = _items(library)
        kind = items.get(item)
        if kind is None:
            raise HelperError("absent")
        if kind == "persona":
            personas = _read_personas(library, items)
            kept = {model: value for model, value in personas.items() if value != item}
            if kept != personas:
                _write_personas(library, kept)
        try:
            os.unlink(item_name(kind, item), dir_fd=library)
        except FileNotFoundError:
            raise HelperError("absent") from None
        except OSError:
            raise HelperError("os-error") from None
    return {"ok": True}


def set_persona(model: str, item: Optional[int], environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    """Make persona ``item`` the default for ``model``; None clears it."""
    if not valid_model(model):
        raise ValueError("Unsupported model name.")
    with _library(environ, create=item is not None) as library:
        if library is None:
            return {"ok": True}  # Nothing saved, so nothing to clear.
        items = _items(library)
        if item is not None and items.get(item) != "persona":
            raise HelperError("absent")
        personas = _read_personas(library, items)
        if item is None:
            if model not in personas:
                return {"ok": True}
            del personas[model]
        else:
            if model not in personas and len(personas) >= MAX_PERSONA_MODELS:
                raise HelperError("full")
            personas[model] = item
        _write_personas(library, personas)
    return {"ok": True}


# Codes the plasmoid knows for --prompts; anything else is os-error.
ERRORS = frozenset({
    "locked", "not-verified", "cancelled", "too-long", "not-text", "full", "absent", "busy", "missing-tool", "os-error",
})


def run(
    operation: str,
    *,
    kind: Optional[str] = None,
    item: Optional[int] = None,
    model: Optional[str] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> dict[str, object]:
    """CLI entry. Only ``list`` replies carry text; nothing carries a path."""
    try:
        if operation == "list":
            return list_items(environ)
        if operation == "add":
            return add(kind or "", environ)
        if operation in ("replace", "remove"):
            if item is None:
                raise ValueError("An item id is needed.")
            return (replace if operation == "replace" else remove)(item, environ)
        if operation == "set-persona":
            return set_persona(model or "", item, environ)
        raise ValueError("Unsupported prompts operation.")
    except HelperError as error:
        return {"ok": False, "error": error.code if error.code in ERRORS else "os-error"}
    except OSError as error:
        return {"ok": False, "error": "busy" if error.errno == errno.EBUSY else "os-error"}


__all__ = ["KINDS", "MAX_CHARS", "MAX_ITEMS", "OPERATIONS", "run", "valid_model"]
