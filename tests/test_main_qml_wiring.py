"""Runs the real main.qml, configUsage.qml and configGeneral.qml under qmltestrunner (tests/mainqml/).

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
# The 167 test functions of tst_main_wiring.qml, fourteen of them run once for
# each of their data rows (3, 24, 24, 6, 6, 4, 4, 3, 2, 8, 3, 5, 3 and 2), plus
# QtTest's initTestCase and cleanupTestCase, which count as passed even when no
# test ran.
MIN_PASSED = 252


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


PROFILE_FOLDERS = HARNESS / "profilefolders" / "tst_profile_folders.qml"
SITE_FOLDERS = ("site-claude", "site-chatgpt")
# What Qt WebEngine (Chromium) keeps in a profile folder; none of it may
# appear outside a site's own folder.
WEBENGINE_NAMES = re.compile(
    r"QtWebEngine|webengine|chromium|Cookies|GPUCache|Dawn\w*Cache|Local Storage|Session Storage|"
    r"History|Favicons|blob_storage|Visited Links|Trust Tokens|Shared Dictionary|Network Persistent State|"
    r"user_prefs\.json|applet-", re.IGNORECASE)


def test_saved_profiles_write_only_inside_their_site_folders(tmp_path):
    """Real saved per-site profiles (Qt WebEngine) write only into site-<id>; no stray folder anywhere.

    Every folder the run can reach (HOME, TMPDIR, XDG_RUNTIME_DIR) is new and
    empty; the QML file refuses to run with any other runtime or home folder.
    """
    runner = shutil.which("qmltestrunner", path=PATH)
    if runner is None:
        pytest.skip("qmltestrunner is not installed")
    home = tmp_path / "hw-profile-home"
    runtime = tmp_path / "hw-profile-folders"
    temp = tmp_path / "tmp"
    home.mkdir()
    temp.mkdir()
    runtime.mkdir(mode=0o700)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "LANG": "C.UTF-8", "QT_QPA_PLATFORM": "offscreen",
           "XDG_RUNTIME_DIR": str(runtime), "TMPDIR": str(temp)}
    completed = _run([runner, "-input", str(PROFILE_FOLDERS)], env, tmp_path)
    output = completed.stdout + completed.stderr
    if "module \"QtTest\" is not installed" in output or "module \"QtWebEngine\" is not installed" in output:
        pytest.skip("QtTest or Qt WebEngine is not installed")
    assert completed.returncode == 0, output
    assert re.search(r"Totals: 3 passed, 0 failed", output), output
    container = runtime / "hearthwire" / "vault" / "web" / "applet-3-g4"
    sites = [container / name for name in SITE_FOLDERS]
    for site in sites:
        assert (site / "Cookies").is_file(), f"{site.name} holds its own cookies"
    chain = {runtime / "hearthwire", runtime / "hearthwire" / "vault", runtime / "hearthwire" / "vault" / "web",
             container}
    stray = []
    for path in sorted(tmp_path.rglob("*")):
        if path in chain or any(path == site or site in path.parents for site in sites):
            continue
        relative = path.relative_to(tmp_path)
        if WEBENGINE_NAMES.search(str(relative)) or runtime in path.parents:
            stray.append(str(relative))
    assert not stray, f"Qt WebEngine wrote outside the site folders: {stray}"
