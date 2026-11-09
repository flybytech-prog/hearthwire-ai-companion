"""Runs the real main.qml and configUsage.qml under qmltestrunner (tests/mainqml/).

The stubs need an import path and a compiled plugin (see plasmoidstub.cpp), so
this file builds them in a temporary folder and runs the test there; they
shadow only the Plasma modules that would reach an applet, the session bus or
the helper. Skipped where Qt's development tools or QtTest are missing.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent / "mainqml"
PATH = "/usr/lib/qt6:/usr/lib/qt6/bin:/usr/bin:/bin"
# The 67 test functions of tst_main_wiring.qml, plus QtTest's initTestCase and
# cleanupTestCase, which count as passed even when no test ran.
MIN_PASSED = 69


def _run(command, env, cwd):
    return subprocess.run(command, env=env, cwd=cwd, capture_output=True, text=True, errors="replace", timeout=300, check=False)


def _build_plugin(imports, env, work):
    moc = shutil.which("moc", path=PATH)
    compiler = shutil.which("g++", path=PATH) or shutil.which("clang++", path=PATH)
    pkg_config = shutil.which("pkg-config", path=PATH)
    if moc is None or compiler is None or pkg_config is None:
        pytest.skip("moc, a C++ compiler or pkg-config is not installed")
    flags = _run([pkg_config, "--cflags", "--libs", "Qt6Qml"], env, work)
    if flags.returncode != 0:
        pytest.skip("the Qt6Qml development files are not installed")
    source = HARNESS / "plasmoidstub.cpp"
    includes = [flag for flag in flags.stdout.split() if flag.startswith("-I")]
    generated = _run([moc, *includes, str(source), "-o", str(work / "plasmoidstub.moc")], env, work)
    assert generated.returncode == 0, generated.stderr
    library = imports / "org/kde/plasma/plasmoid/libplasmoidstub.so"
    built = _run([compiler, "-std=c++17", "-shared", "-fPIC", "-I", str(work), str(source),
                  "-o", str(library), *flags.stdout.split()], env, work)
    assert built.returncode == 0, built.stderr


def test_real_main_qml_wiring(tmp_path):
    runner = shutil.which("qmltestrunner", path=PATH)
    if runner is None:
        pytest.skip("qmltestrunner is not installed")
    (tmp_path / "tmp").mkdir()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "LANG": "C.UTF-8", "QT_QPA_PLATFORM": "offscreen",
           "XDG_RUNTIME_DIR": str(tmp_path), "TMPDIR": str(tmp_path / "tmp")}
    imports = tmp_path / "imports"
    shutil.copytree(HARNESS / "stubs", imports)
    _build_plugin(imports, env, tmp_path)
    completed = _run([runner, "-import", str(imports), "-input", str(HARNESS / "tst_main_wiring.qml")], env, tmp_path)
    output = completed.stdout + completed.stderr
    if "module \"QtTest\" is not installed" in output:
        pytest.skip("QtTest is not installed")
    assert completed.returncode == 0, output
    totals = re.search(r"Totals: (\d+) passed, 0 failed", output)
    assert totals is not None and int(totals.group(1)) >= MIN_PASSED, output
