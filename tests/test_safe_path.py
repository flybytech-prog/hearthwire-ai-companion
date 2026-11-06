"""`python3 -m hearthwire` must not import modules from the working directory.

plasmashell runs the helper with $HOME as its working directory, so a stray
~/json.py would otherwise run inside the process that reads provider tokens.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import hearthwire

SRC = Path(__file__).resolve().parent.parent / "src"
# Standard-library modules the helper imports after the package __init__ runs.
PLANTED = ("json", "argparse", "re", "dataclasses", "datetime", "pathlib", "subprocess")


def _plant(folder: Path) -> Path:
    marker = folder / "planted-module-was-imported"
    for name in PLANTED:
        (folder / f"{name}.py").write_text(
            f"open({str(marker)!r}, 'a').write({name!r} + '\\n')\n"
            "raise SystemExit(97)\n",
            encoding="utf-8",
        )
    return marker


def _env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {
        "PATH": os.defpath,
        "HOME": str(home),
        "SHELL": "/bin/sh",
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_STATE_HOME": str(home / ".local/state"),
        "XDG_RUNTIME_DIR": os.environ["XDG_RUNTIME_DIR"],
        "PYTHONPATH": str(SRC),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _run(cwd: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
        check=False,
    )


def test_planted_module_is_imported_without_the_guard(tmp_path):
    """Control: the planted files really would shadow the standard library."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    marker = _plant(cwd)
    result = _run(cwd, _env(tmp_path), "-c", "import json")
    assert result.returncode == 97
    assert marker.read_text(encoding="utf-8") == "json\n"


@pytest.mark.parametrize("flag", (None, "-P"))
def test_version_ignores_modules_in_working_directory(tmp_path, flag):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    marker = _plant(cwd)
    args = [a for a in (flag, "-m", "hearthwire", "--version") if a]
    result = _run(cwd, _env(tmp_path), *args)
    assert not marker.exists()
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == hearthwire.__version__


def test_detect_ignores_modules_in_working_directory(tmp_path):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    marker = _plant(cwd)
    result = _run(cwd, _env(tmp_path), "-m", "hearthwire", "--detect")
    assert not marker.exists()
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)


def test_running_from_the_package_parent_still_works(tmp_path):
    """`cd src && python3 -m hearthwire` keeps the package's own folder."""
    env = _env(tmp_path)
    del env["PYTHONPATH"]
    result = _run(SRC, env, "-m", "hearthwire", "--version")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == hearthwire.__version__


def test_importing_the_package_elsewhere_leaves_sys_path_alone(tmp_path):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    code = (
        "import sys; before = list(sys.path); import hearthwire; "
        "sys.exit(0 if sys.path == before else 1)"
    )
    result = _run(cwd, _env(tmp_path), "-c", code)
    assert result.returncode == 0, result.stderr
