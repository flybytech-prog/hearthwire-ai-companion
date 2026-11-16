import os
import sys
from pathlib import Path

import pytest

# Headless Qt for any test that touches PySide6.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name: str) -> Path:
    return FIXTURES / name


@pytest.fixture(autouse=True)
def _private_runtime_dir(tmp_path_factory, monkeypatch):
    """Keep credential lock files out of the real XDG_RUNTIME_DIR."""
    runtime = tmp_path_factory.mktemp("runtime")
    runtime.chmod(0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    return runtime


# Never reachable from a test: the host's session and system bus (KDE Wallet,
# Secret Service) and its display. With these unset, D-Bus clients fall back
# to $XDG_RUNTIME_DIR/bus, which is the empty per-test runtime dir above.
HOST_SESSION_VARIABLES = ("DBUS_SESSION_BUS_ADDRESS", "DBUS_SYSTEM_BUS_ADDRESS", "DISPLAY", "WAYLAND_DISPLAY")


@pytest.fixture(autouse=True)
def _no_session_bus(_private_runtime_dir, monkeypatch):
    """Remove the bus and display variables, so no test can reach the real
    session's KDE Wallet or Secret Service, even if a real qdbus6 or
    kwallet-query were found on PATH (the wallet tests use stubs)."""
    for name in HOST_SESSION_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _plasma_frontend(monkeypatch):
    """Task 011: every test starts as the Plasma widget, whatever the shell running pytest set.
    App-mode tests set HEARTHWIRE_FRONTEND=app themselves."""
    monkeypatch.delenv("HEARTHWIRE_FRONTEND", raising=False)
