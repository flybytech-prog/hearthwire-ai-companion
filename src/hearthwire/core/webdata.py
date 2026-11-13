"""Private folders for the Chat tab's opt-in saved sign-ins.

The plasmoid passes only an applet id, a profile generation and checked chat
site ids. The helper creates or deletes the generation folder
``web/applet-<N>-g<G>/`` inside the verified gocryptfs mount (store
``encrypted``, see ``vault.py``). The generation folder is only a container:
each chat site keeps its own profile in ``site-<id>/`` inside it, so no two
sites share cookies or storage. There is no unencrypted store: Qt
WebEngine keeps cookies and site storage in plaintext, so a saved sign-in may
only ever live inside the encrypted folder. Every directory is opened one
component at a time relative to its parent's descriptor with ``O_NOFOLLOW``,
so a symlink planted anywhere in our part of the tree is refused rather than
followed. Results are short error codes only: never paths, names or counts.
"""

from __future__ import annotations

import errno
import os
import re
import shutil
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

# Only "encrypted"; --store stays so the CLI contract can grow later.
STORES = ("encrypted",)
APP_DIR = "hearthwire"
WEB_DIR = "web"
PRIVATE_MODE = 0o700

# The chat site id grammar (task 002 plan-v3-delta): exactly the built-in web
# sites (settingsbackup.WEB_SITE_IDS, ChatSites.js) or an added site's
# ``user-`` plus 8 lowercase hex digits. "ollama" is never a web site. The
# grammar is prefix-free, so ``site-<id>`` folders never collide.
BUILTIN_SITE_IDS = ("claude", "chatgpt", "grok", "gemini", "copilot", "mscopilot", "local")
_USER_SITE_ID = re.compile(r"user-[0-9a-f]{8}")
SITE_PREFIX = "site-"
# Most ids one command may name: the built-ins plus 200 added sites.
MAX_SITE_IDS = 207

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class HelperError(Exception):
    """A failure reported to the plasmoid as ``{"ok":false,"error":code}``."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def profile_name(applet: int, generation: int) -> str:
    return f"applet-{applet}-g{generation}"


def valid_site_id(value: object) -> bool:
    """True only for a built-in site id or ``user-`` plus 8 lowercase hex digits."""
    if not isinstance(value, str):
        return False
    return value in BUILTIN_SITE_IDS or _USER_SITE_ID.fullmatch(value) is not None


def site_ids(text: str) -> tuple[str, ...]:
    """Parse a comma-separated id list: 1 to MAX_SITE_IDS valid ids, no duplicates.

    Nothing is trimmed or skipped; any other text raises ValueError.
    """
    ids = tuple(text.split(","))
    _check_site_ids(ids)
    return ids


def _check_site_ids(ids: tuple[str, ...]) -> None:
    if not 1 <= len(ids) <= MAX_SITE_IDS:
        raise ValueError("Expected 1 to 207 site ids.")
    if not all(valid_site_id(value) for value in ids):
        raise ValueError("Unsupported site id.")
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate site id.")


def site_folder(site: str) -> str:
    if not valid_site_id(site):
        raise ValueError("Unsupported site id.")
    return SITE_PREFIX + site


def _profile_pattern(applet: int) -> re.Pattern[str]:
    # Only names this helper creates: no leading zeros, nothing around them.
    return re.compile(rf"applet-{applet}-g(0|[1-9][0-9]*)")


def data_base(environ: Optional[Mapping[str, str]] = None) -> str:
    """``$XDG_DATA_HOME`` when it is absolute, else ``~/.local/share``."""
    values = os.environ if environ is None else environ
    configured = values.get("XDG_DATA_HOME") or ""
    if configured and os.path.isabs(configured):
        return configured
    return str(Path.home() / ".local" / "share")


def _close(descriptor: Optional[int]) -> None:
    if descriptor is not None and descriptor >= 0:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _open_error(error: OSError) -> HelperError:
    if error.errno == errno.ELOOP:
        return HelperError("symlink")
    if error.errno == errno.ENOTDIR:
        return HelperError("not-directory")
    return HelperError("os-error")


def open_base(base: str, *, create: bool) -> Optional[int]:
    """Open the user's data base directory, or None when it does not exist.

    The base itself is the user's own choice (it may be a symlink, e.g. on
    image-based systems), so it is followed; it must still be ours.
    """
    try:
        if create:
            os.makedirs(base, PRIVATE_MODE, exist_ok=True)
        descriptor = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except FileNotFoundError:
        if create:
            raise HelperError("os-error") from None
        return None
    except OSError as error:
        raise _open_error(error) from None
    try:
        info = os.fstat(descriptor)
    except OSError:
        _close(descriptor)
        raise HelperError("os-error") from None
    if info.st_uid != os.getuid():
        _close(descriptor)
        raise HelperError("not-owned")
    return descriptor


def open_child_dir(
    parent: int,
    name: str,
    *,
    create: bool,
    mode: int = PRIVATE_MODE,
) -> Optional[int]:
    """Open ``name`` below ``parent`` without following links.

    With ``create`` the directory is made (``mode``) when missing and an
    existing one is reset to ``mode``. Without it a missing directory gives
    None and nothing is changed. Symlinks, non-directories and directories
    owned by someone else are refused.
    """
    if create:
        try:
            os.mkdir(name, mode, dir_fd=parent)
        except FileExistsError:
            pass
        except OSError:
            raise HelperError("os-error") from None
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        if create:
            raise HelperError("os-error") from None
        return None
    except OSError:
        raise HelperError("os-error") from None
    if stat.S_ISLNK(info.st_mode):
        raise HelperError("symlink")
    if not stat.S_ISDIR(info.st_mode):
        raise HelperError("not-directory")
    if info.st_uid != os.getuid():
        raise HelperError("not-owned")
    try:
        descriptor = os.open(name, _DIR_FLAGS, dir_fd=parent)
    except OSError as error:
        raise _open_error(error) from None
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            # Swapped between the check and the open.
            raise HelperError("symlink")
        if opened.st_uid != os.getuid():
            raise HelperError("not-owned")
        if create and stat.S_IMODE(opened.st_mode) != mode:
            os.fchmod(descriptor, mode)
    except HelperError:
        _close(descriptor)
        raise
    except OSError:
        _close(descriptor)
        raise HelperError("os-error") from None
    return descriptor


@contextmanager
def _descriptors() -> Iterator[list[int]]:
    opened: list[int] = []
    try:
        yield opened
    finally:
        for descriptor in reversed(opened):
            _close(descriptor)


def _require_safe_rmtree() -> None:
    if not getattr(shutil.rmtree, "avoids_symlink_attacks", False):
        raise HelperError("os-error")


def remove_entry(parent: int, name: str) -> None:
    """Delete ``name`` below ``parent``; a symlink is unlinked, never followed."""
    _require_safe_rmtree()
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError:
        raise HelperError("os-error") from None
    try:
        if stat.S_ISDIR(info.st_mode):
            if info.st_uid != os.getuid():
                raise HelperError("not-owned")
            shutil.rmtree(name, dir_fd=parent)
        else:
            os.unlink(name, dir_fd=parent)
    except FileNotFoundError:
        return
    except OSError:
        raise HelperError("os-error") from None


def _remove_profiles(web: int, applet: int, keep: Optional[int]) -> None:
    pattern = _profile_pattern(applet)
    try:
        names = os.listdir(web)
    except OSError:
        raise HelperError("os-error") from None
    for name in sorted(names):
        match = pattern.fullmatch(name)
        if match is None:
            continue
        if keep is not None and int(match.group(1)) == keep:
            continue
        remove_entry(web, name)


# --- store "encrypted": <verified gocryptfs mount>/web ---------------------------------


def _is_site_folder_name(name: str) -> bool:
    return name.startswith(SITE_PREFIX) and valid_site_id(name[len(SITE_PREFIX):])


def _list(directory: int) -> list[str]:
    try:
        return sorted(os.listdir(directory))
    except OSError:
        raise HelperError("os-error") from None


def _clear_after_rollback(container: int, names: list[str]) -> bool:
    """Empty the container when its root holds anything but site folders.

    Since every site has its own profile, nothing this version makes lives
    at the container root; anything there was written by an older version
    that opened the container as its one shared profile, i.e. after a
    downgrade. The site folders from before that downgrade then hold
    sign-ins the user may have changed or left there, so every one goes too:
    after a re-upgrade each site starts signed out (REV-M1). Site folders are
    deleted first, the root leftovers last, so a failed delete keeps the
    evidence and the next run tries again. True when it emptied the container.
    """
    if all(_is_site_folder_name(name) for name in names):
        return False
    for name in sorted(names, key=lambda entry: not _is_site_folder_name(entry)):
        remove_entry(container, name)
    return True


def _prepare_encrypted(
    applet: int,
    generation: int,
    sites: tuple[str, ...],
    environ: Optional[Mapping[str, str]],
) -> None:
    from . import vault

    with vault.verified_mount(environ) as root, _descriptors() as opened:
        parent = root
        for name in (WEB_DIR, profile_name(applet, generation)):
            parent = open_child_dir(parent, name, create=True)
            opened.append(parent)
        # Before any site folder is handed out: never an old one after a rollback.
        _clear_after_rollback(parent, _list(parent))
        for site in sites:
            opened.append(open_child_dir(parent, site_folder(site), create=True))


def _remove_encrypted(applet: int, keep: Optional[int], environ: Optional[Mapping[str, str]]) -> None:
    from . import vault

    _require_safe_rmtree()
    with vault.verified_mount(environ) as root, _descriptors() as opened:
        web = open_child_dir(root, WEB_DIR, create=False)
        if web is None:
            return
        opened.append(web)
        _remove_profiles(web, applet, keep)


@contextmanager
def _existing_container(
    applet: int,
    generation: int,
    environ: Optional[Mapping[str, str]],
) -> Iterator[Optional[int]]:
    """The generation folder inside the verified mount, or None when it does not exist."""
    from . import vault

    _require_safe_rmtree()
    with vault.verified_mount(environ) as root, _descriptors() as opened:
        parent: Optional[int] = root
        for name in (WEB_DIR, profile_name(applet, generation)):
            parent = open_child_dir(parent, name, create=False)
            if parent is None:
                break
            opened.append(parent)
        yield parent


def _is_real_directory(parent: int, name: str) -> bool:
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError:
        raise HelperError("os-error") from None
    return stat.S_ISDIR(info.st_mode)


def _prune_encrypted(
    applet: int,
    generation: int,
    known: tuple[str, ...],
    environ: Optional[Mapping[str, str]],
) -> None:
    keep = {site_folder(site) for site in known}
    with _existing_container(applet, generation, environ) as container:
        if container is None:
            return
        names = _list(container)
        if _clear_after_rollback(container, names):
            return
        for name in names:
            # A known name that is a symlink or a file is never a site's
            # profile (prepare would refuse it), so it goes too.
            if name in keep and _is_real_directory(container, name):
                continue
            remove_entry(container, name)


# --- remove-site: refuse while a process still has a file open in the site folder (L2-r) ----

# Injectable for tests: a fake tree of <pid>/fd/<n> links and <pid>/maps files.
PROC_ROOT = "/proc"
# The kernel appends this to the link or maps path of a file that was unlinked.
_DELETED_SUFFIX = " (deleted)"


def _is_below(path: str, folder: str) -> bool:
    """``folder`` itself or anything below it; ``site-claude2`` is not below ``site-claude``."""
    return path == folder or path.startswith(folder + os.sep)


def _names_folder(path: str, folder: str) -> bool:
    if _is_below(path, folder):
        return True
    # An open file whose entry is gone (rmtree raced it, or Chromium replaced
    # it) reads "<path> (deleted)". Stripped once: a file whose own name ends
    # in " (deleted)" already matched above.
    return path.endswith(_DELETED_SUFFIX) and _is_below(path[: -len(_DELETED_SUFFIX)], folder)


def _process_owner(process: str) -> Optional[int]:
    """The uid owning ``/proc/<pid>``, or None when it is gone or unreadable.

    The kernel shows a non-dumpable process as root's; it is skipped like any
    other user's process (its fds could not be read anyway).
    """
    try:
        return os.stat(process, follow_symlinks=False).st_uid
    except OSError:
        return None


def _fd_paths(process: str) -> Iterator[str]:
    fd_dir = os.path.join(process, "fd")
    try:
        entries = os.listdir(fd_dir)
    except OSError:
        return
    for entry in entries:
        try:
            yield os.readlink(os.path.join(fd_dir, entry))
        except OSError:
            continue


def _mapped_paths(process: str) -> Iterator[str]:
    try:
        with open(os.path.join(process, "maps"), "rb") as maps:
            for line in maps:
                # address perms offset dev inode [path]; the path may hold spaces.
                fields = line.rstrip(b"\n").split(None, 5)
                if len(fields) == 6 and fields[5].startswith(b"/"):
                    yield os.fsdecode(fields[5])
    except OSError:
        return


def site_folder_in_use(folder: str, *, proc_root: Optional[str] = None, uid: Optional[int] = None) -> bool:
    """True when a process of ``uid`` (default: ours) has a file under ``folder`` open or mapped.

    ``folder`` must be the resolved path; the kernel's fd links and maps
    paths are resolved too. Processes of other users and processes (or single
    entries) that can't be read are skipped. When ``proc_root`` itself can't
    be listed nothing can be known, so that fails as os-error, not as free.
    """
    root = PROC_ROOT if proc_root is None else proc_root
    owner = os.getuid() if uid is None else uid
    try:
        pids = [name for name in os.listdir(root) if name.isdigit()]
    except OSError:
        raise HelperError("os-error") from None
    for pid in pids:
        process = os.path.join(root, pid)
        if _process_owner(process) != owner:
            continue
        for path in _fd_paths(process):
            if _names_folder(path, folder):
                return True
        for path in _mapped_paths(process):
            if _names_folder(path, folder):
                return True
    return False


def _container_path(
    applet: int,
    generation: int,
    container: int,
    environ: Optional[Mapping[str, str]],
) -> str:
    """The resolved path of the open generation folder, checked against its fd."""
    from . import vault

    path = os.path.join(
        vault.context(environ, find_tools=False).mountpoint, WEB_DIR, profile_name(applet, generation),
    )
    try:
        by_path = os.stat(path)
        by_fd = os.fstat(container)
    except OSError:
        raise HelperError("os-error") from None
    if (by_path.st_dev, by_path.st_ino) != (by_fd.st_dev, by_fd.st_ino):
        raise HelperError("os-error")
    return os.path.realpath(path)


def _remove_site_encrypted(
    applet: int,
    generation: int,
    site: str,
    environ: Optional[Mapping[str, str]],
) -> None:
    name = site_folder(site)
    with _existing_container(applet, generation, environ) as container:
        if container is None:
            return
        if _is_real_directory(container, name):
            # The site's profile object can be gone while its storage still
            # has files open (heavy IndexedDB writes kept LevelDB files open
            # ~20 s, review L2-r). Deleting then would leave the old store
            # writing into "(deleted)" files, or into the re-created folder.
            # So: refuse with "busy" and delete nothing; the widget retries.
            # Remaining race: the scan runs right before the delete, but a
            # process may still open a file in between (the vault lock does
            # not bind Chromium). The widget asks only after the site's views
            # and profile are destroyed, so nothing should open new files.
            folder = os.path.join(_container_path(applet, generation, container, environ), name)
            if site_folder_in_use(folder):
                raise HelperError("busy")
        remove_entry(container, name)


def prepare(
    store: str,
    applet: int,
    generation: int,
    environ: Optional[Mapping[str, str]] = None,
    sites: tuple[str, ...] = (),
) -> None:
    """Create the private generation folder and a ``site-<id>`` folder per listed site."""
    if store != "encrypted":
        raise ValueError("Unsupported web data store.")
    sites = tuple(sites)
    if sites:
        _check_site_ids(sites)
    _prepare_encrypted(applet, generation, sites, environ)


def prune(
    store: str,
    applet: int,
    generation: int,
    known: tuple[str, ...],
    environ: Optional[Mapping[str, str]] = None,
) -> None:
    """Inside one generation folder, delete every entry but the ``known`` site folders.

    Other generations and other applets are never touched. A missing folder
    counts as success; the encrypted folder must still be unlocked and verified.
    """
    if store != "encrypted":
        raise ValueError("Unsupported web data store.")
    known = tuple(known)
    _check_site_ids(known)
    _prune_encrypted(applet, generation, known, environ)


def remove_site(
    store: str,
    applet: int,
    generation: int,
    site: str,
    environ: Optional[Mapping[str, str]] = None,
) -> None:
    """Delete one site's folder inside one generation folder; missing is success.

    Refused with ``busy`` (nothing deleted) while a process of this user has
    a file under that folder open or mapped.
    """
    if store != "encrypted":
        raise ValueError("Unsupported web data store.")
    _remove_site_encrypted(applet, generation, site, environ)


def remove(
    store: str,
    applet: int,
    keep: Optional[int] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> None:
    """Delete one applet's profile folders except generation ``keep``.

    A missing tree counts as success; the folder must still be unlocked and
    verified.
    """
    if store != "encrypted":
        raise ValueError("Unsupported web data store.")
    _remove_encrypted(applet, keep, environ)


OPERATIONS = ("prepare", "prune", "remove-site", "remove")


def run(
    operation: str,
    store: str,
    applet: int,
    generation: Optional[int] = None,
    keep: Optional[int] = None,
    environ: Optional[Mapping[str, str]] = None,
    sites: Optional[tuple[str, ...]] = None,
    known: Optional[tuple[str, ...]] = None,
    site: Optional[str] = None,
) -> dict[str, object]:
    """CLI entry: a reply object that never contains a path or name."""
    try:
        if operation == "remove":
            remove(store, applet, keep, environ)
        elif operation not in OPERATIONS:
            raise ValueError("Unsupported web data operation.")
        elif generation is None:
            raise ValueError(f"{operation} needs a generation.")
        elif operation == "prepare":
            prepare(store, applet, generation, environ, sites or ())
        elif operation == "prune":
            if known is None:
                raise ValueError("prune needs the known site ids.")
            prune(store, applet, generation, known, environ)
        else:
            if site is None:
                raise ValueError("remove-site needs a site id.")
            remove_site(store, applet, generation, site, environ)
    except HelperError as error:
        return {"ok": False, "error": error.code}
    except OSError:
        return {"ok": False, "error": "os-error"}
    return {"ok": True}
