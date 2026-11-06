"""Runtime tests of the real ChatWebView.qml in Qt WebEngine (tests/webengine/).

They start Chromium against a hostile fake chat site inside a private user,
network and mount namespace (see tests/webengine/run.sh), so they are slow
and need user namespaces. They run only with HEARTHWIRE_WEBENGINE_TESTS=1;
where the runner can't isolate itself (no unshare, openssl or user
namespaces) it says SKIP and the test is skipped.

With HEARTHWIRE_WEBENGINE_BYPASSES=1 as well, the runner is also pointed at
copies of the plasmoid with one of the pentest bypasses (grant, cert, nav)
applied, and must fail on each.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "tests" / "webengine" / "run.sh"
UI = ROOT / "plasmoid" / "contents" / "ui"

pytestmark = pytest.mark.skipif(os.environ.get("HEARTHWIRE_WEBENGINE_TESTS") != "1",
                                reason="set HEARTHWIRE_WEBENGINE_TESTS=1 to run the WebEngine runtime tests")

# (name, old, new) in ChatWebView.qml: the pentest bypasses the runtime
# tests must catch even if a static rule were missed.
BYPASSES = [
    ("grant", "                permission.deny()\n",
     "                if (permission.permissionType < 0) permission.deny(); else permission[\"gr\" + \"ant\"]()\n"),
    ("cert", "error.rejectCertificate()", "error.acceptCertificate()"),
    ("nav", 'if (verdict === "allow") {', 'if (verdict === "allow" || verdict === "block") {'),
]


# What only a test that really ran and failed prints (qmltestrunner's own
# failure line, or run.sh's checks after a run).
TEST_FAILURES = ("FAIL!  :", "FAIL: the service on this computer was reached", "left site data on disk")
# What a run that never got to the tests prints.
SETUP_FAILURES = ("cannot replace", "did not start", "could not make a certificate", "no /etc/hosts",
                  "no ChatWebView.qml")


def _run(ui, tmp_path):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "LANG": "C.UTF-8", "TMPDIR": str(work)}
    result = subprocess.run(["/bin/sh", str(RUNNER), str(ui)], env=env, capture_output=True, text=True,
                            timeout=900)
    output = result.stdout + result.stderr
    if output.startswith("SKIP:"):
        pytest.skip(output.strip())
    return result.returncode, output


def test_hostile_site_gets_nothing_from_the_real_chat_web_view(tmp_path):
    code, output = _run(UI, tmp_path)
    assert not any(message in output for message in SETUP_FAILURES), output
    assert code == 0 and "webengine runtime tests: PASS" in output, output


@pytest.mark.skipif(os.environ.get("HEARTHWIRE_WEBENGINE_BYPASSES") != "1",
                    reason="set HEARTHWIRE_WEBENGINE_BYPASSES=1 to prove the runtime tests catch the bypasses")
@pytest.mark.parametrize(("name", "old", "new"), BYPASSES, ids=[name for name, _, _ in BYPASSES])
def test_runtime_tests_fail_on_a_bypass(tmp_path, name, old, new):
    ui = tmp_path / "ui"
    shutil.copytree(UI, ui)
    web = ui / "ChatWebView.qml"
    text = web.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"bypass fixture out of date: {old!r}"
    web.write_text(text.replace(old, new), encoding="utf-8")
    code, output = _run(ui, tmp_path)
    setup = [message for message in SETUP_FAILURES if message in output]
    assert not setup, f"the {name} run failed before any test ran ({setup}):\n{output}"
    assert code != 0 and any(message in output for message in TEST_FAILURES), \
        f"the {name} bypass passed the runtime tests:\n{output}"
