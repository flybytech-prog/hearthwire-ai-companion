"""Which front end runs the helper: the Plasma widget or the hearthwire-hyprland app (task 011).

The app's process runner sets ``HEARTHWIRE_FRONTEND=app`` in the child's
environment, never in the command string; no command-line option can set or
change the front end. Unset, or ``plasma``, is exactly the 1.1.0 behavior.
Any other value (the empty string too) is ``bad-frontend``: nothing runs.

The app has one reserved applet id, ``APP_APPLET_ID`` (2**31), so its chat
profiles (``applet-2147483648-g<G>``) and its usage history
(``applet-2147483648.json``) never mix with a Plasma widget's. In app mode
every ``--applet`` must be that id; in Plasma mode that id is refused. Both
are ``applet-not-found``.

In app mode the vault's passphrase prompt is ``hearthwire-askpass`` instead
of kdialog. It is used only at ``ASKPASS_PATH`` (never looked up on PATH or
taken from the environment), and only while that file and every folder above
it are root's and nobody else may change them (``askpass_path``).
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Mapping
from typing import Optional

from .webdata import HelperError

VARIABLE = "HEARTHWIRE_FRONTEND"
PLASMA = "plasma"
APP = "app"
FRONTENDS = (PLASMA, APP)

# Plasma applet ids are small; the app's id is one more than the largest
# 32-bit signed id, and still a valid --applet (cli.MAX_INT_ARGUMENT).
APP_APPLET_ID = 2**31

APP_NAME = "hearthwire-hyprland"
ASKPASS_NAME = "hearthwire-askpass"
ASKPASS_PATH = "/usr/lib/hearthwire-hyprland/hearthwire-askpass"

# Nobody but the owner may write, and the program runs as the caller only.
_FOREIGN_WRITE = stat.S_IWGRP | stat.S_IWOTH
_SET_ID = stat.S_ISUID | stat.S_ISGID
_ROOT = 0


def mode(environ: Optional[Mapping[str, str]] = None) -> str:
    """``plasma`` (unset or "plasma") or ``app``; any other value is ``bad-frontend``.

    Read from the environment only: argv never chooses the front end.
    """
    values = os.environ if environ is None else environ
    value = values.get(VARIABLE)
    if value is None or value == PLASMA:
        return PLASMA
    if value == APP:
        return APP
    raise HelperError("bad-frontend")


def is_app(environ: Optional[Mapping[str, str]] = None) -> bool:
    return mode(environ) == APP


def applet_allowed(applet: int, current: str) -> bool:
    """App mode takes only APP_APPLET_ID; Plasma mode takes any id but that one."""
    if current == APP:
        return applet == APP_APPLET_ID
    return applet != APP_APPLET_ID


def check_applet(applet: int, environ: Optional[Mapping[str, str]] = None) -> None:
    """``applet-not-found`` unless ``applet`` belongs to the current front end."""
    if not applet_allowed(applet, mode(environ)):
        raise HelperError("applet-not-found")


def _root_only(info: os.stat_result) -> bool:
    return info.st_uid == _ROOT and not info.st_mode & _FOREIGN_WRITE


def askpass_path(lstat: Optional[Callable[[str], os.stat_result]] = None) -> Optional[str]:
    """``ASKPASS_PATH`` when it may run as the passphrase prompt, else None.

    The file must be a regular file (not a link) owned by root, executable,
    without set-id bits and not writable by group or others; each folder
    above it, up to ``/``, must be a real directory (not a link) owned by
    root and not writable by group or others. So only root could have put
    the program there or could swap it. ``lstat`` is for tests.
    """
    check = os.lstat if lstat is None else lstat
    path = ASKPASS_PATH
    if not os.path.isabs(path) or os.path.normpath(path) != path or os.path.basename(path) != ASKPASS_NAME:
        return None
    try:
        info = check(path)
        if (not stat.S_ISREG(info.st_mode) or not _root_only(info) or info.st_mode & _SET_ID
                or not info.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
            return None
        folder = os.path.dirname(path)
        while True:
            info = check(folder)
            if not stat.S_ISDIR(info.st_mode) or not _root_only(info):
                return None
            if folder == "/":
                return path
            folder = os.path.dirname(folder)
    except OSError:
        return None


__all__ = ["APP", "APP_APPLET_ID", "APP_NAME", "ASKPASS_NAME", "ASKPASS_PATH", "FRONTENDS", "PLASMA",
           "VARIABLE", "applet_allowed", "askpass_path", "check_applet", "is_app", "mode"]
