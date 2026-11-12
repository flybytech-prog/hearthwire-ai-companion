"""Hearthwire: KDE Plasma companion for AI coding subscriptions (usage meters and AI chats)."""

# Runs before anything else in the package imports a module, so only sys and
# os (both already loaded by the interpreter at startup) are used here.
import os as _os
import sys as _sys


def _drop_working_directory_from_path() -> None:
    """Do at runtime what `python3 -P` (sys.flags.safe_path) does at startup.

    `python3 -m hearthwire` puts the working directory first on sys.path, and
    plasmashell's working directory is $HOME, so a stray ~/json.py would be
    imported by the helper that reads provider tokens. sys.flags is read-only,
    so the flag cannot be set from here; removing the entry before cli.py
    imports json, argparse and the rest gives the same protection for every
    later import. It cannot protect the package itself (a planted
    ~/hearthwire/ wins the -m lookup) or modules the interpreter loaded before
    this runs; launch with `python3 -P -m hearthwire` for that.

    Only applies to `-m` runs (sys.argv[0] is "-m" while the package is being
    imported), so importing the package from another program never changes
    that program's sys.path. The package's own parent folder is kept, so
    `cd src && python3 -m hearthwire` still works.
    """
    if _sys.flags.safe_path or _sys.argv[:1] != ["-m"]:
        return
    try:
        cwd = _os.path.realpath(_os.getcwd())
    except OSError:
        cwd = None
    own = _os.path.realpath(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    kept = []
    for entry in _sys.path:
        if isinstance(entry, str):
            if cwd is None and entry in ("", "."):
                continue
            try:
                resolved = _os.path.realpath(entry or ".")
            except (OSError, ValueError):
                resolved = None
            if resolved == cwd and resolved != own:
                continue
        kept.append(entry)
    _sys.path[:] = kept


_drop_working_directory_from_path()
del _drop_working_directory_from_path

__version__ = "1.0.1"
