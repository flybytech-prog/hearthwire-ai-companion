"""``-extpass`` relay for ``gocryptfs -passwd`` (see ``vault.py``).

gocryptfs runs this file as its extpass program::

    python3 extpass_relay.py <marker> <kdialog> <kdialog arguments...>

The dialog inherits this process's stdout, which is gocryptfs's own pipe, so
the old passphrase goes from kdialog straight to gocryptfs. This process never
reads it. Once the dialog has exited, its exit status (a number, nothing
else) is published at ``<marker>`` by an atomic rename. That tells the helper
the first dialog is gone and it may open the second one. If the marker cannot
be written, the relay fails, so gocryptfs gives up ("cancelled") and the
helper is never left waiting.

Only ``os`` and ``sys`` are imported: this file runs as a script, and
nothing else from its directory or the environment should be loaded. The
helper starts gocryptfs (and so this relay) with every ``PYTHON*`` variable
removed and ``PYTHONNOUSERSITE=1`` and ``PYTHONSAFEPATH=1`` set, so neither
the package directory nor the user site directory is on ``sys.path``.
"""

import os
import sys

_TEMPORARY_SUFFIX = ".tmp"
_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


def _publish(marker: str, status: int) -> bool:
    temporary = marker + _TEMPORARY_SUFFIX
    try:
        descriptor = os.open(temporary, _FLAGS, 0o600)
    except OSError:
        return False
    try:
        written = os.write(descriptor, str(status).encode("ascii"))
    except OSError:
        written = 0
    finally:
        os.close(descriptor)
    try:
        if written == 0:
            raise OSError("marker not written")
        os.rename(temporary, marker)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        return False
    return True


def main(argv: list[str]) -> int:
    if len(argv) < 3 or not os.path.isabs(argv[1]) or not os.path.isabs(argv[2]):
        return 2
    marker, dialog = argv[1], argv[2:]
    try:
        status = os.spawnv(os.P_WAIT, dialog[0], dialog)
    except OSError:
        status = 127
    if not 0 <= status <= 255:
        status = 1  # Killed by a signal.
    if not _publish(marker, status):
        return 1
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
