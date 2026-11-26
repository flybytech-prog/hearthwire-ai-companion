"""Task 014 (ledger item): the helper's TLS never honours SSLKEYLOGFILE.

``ssl.create_default_context()`` sets ``keylog_filename`` from SSLKEYLOGFILE,
and setting it opens (creates) that file at once and then appends every
connection's session secrets: whoever can set the helper's environment could
decrypt its captured provider traffic later. core/http.py builds its one
context itself, without that. These tests set SSLKEYLOGFILE to a path under
tmp_path and never reach the network: the only connection attempt goes to a
closed port on 127.0.0.1.
"""

import ast
import os
import re
import ssl
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

from hearthwire.core import http
from test_frontend import mutant

SRC = Path(http.__file__).resolve().parents[2]
HTTP_PY = Path(http.__file__)


def https_handler_context(module):
    (handler,) = [item for item in module._OPENER.handlers if isinstance(item, module._WatchedHTTPSHandler)]
    return handler._context


COMPARED = ("verify_mode", "check_hostname", "verify_flags", "options", "minimum_version", "maximum_version",
            "protocol", "security_level", "post_handshake_auth", "hostname_checks_common_name", "num_tickets",
            "verify_mode")


def context_differences(context, reference):
    """Every readable attribute, the cipher list and the CA store compared exactly; keylog_filename is the one allowed gap."""
    problems = []
    for name in sorted(set(dir(reference)) - {"keylog_filename"}):
        if name.startswith("_") or name in ("sni_callback", "session_stats", "cert_store_stats", "get_ciphers",
                                           "get_ca_certs"):
            continue
        try:
            wanted = getattr(reference, name)
        except (AttributeError, ValueError, NotImplementedError):
            continue
        if callable(wanted):
            continue
        if getattr(context, name) != wanted:
            problems.append(f"{name}: {getattr(context, name)!r} != {wanted!r}")
    if [item["name"] for item in context.get_ciphers()] != [item["name"] for item in reference.get_ciphers()]:
        problems.append("the cipher list differs")
    if context.cert_store_stats() != reference.cert_store_stats():
        problems.append("the CA store differs")
    return problems


def reference_context(monkeypatch):
    """The standard library's default context, plus http.client's ALPN and post-handshake settings."""
    monkeypatch.delenv("SSLKEYLOGFILE", raising=False)
    reference = ssl.create_default_context()
    reference.set_alpn_protocols(["http/1.1"])
    if reference.post_handshake_auth is not None:
        reference.post_handshake_auth = True
    return reference


def test_the_context_has_no_key_log_and_equals_the_default_one(tmp_path, monkeypatch):
    reference = reference_context(monkeypatch)
    assert reference.keylog_filename is None
    log = tmp_path / "keys.log"
    monkeypatch.setenv("SSLKEYLOGFILE", str(log))
    context = http.tls_context()
    assert context.keylog_filename is None
    assert not log.exists()
    assert context_differences(context, reference) == []
    # The control: the standard library's default context does write the file.
    ssl.create_default_context()
    assert log.exists()


def test_proof_the_equality_check_catches_a_weaker_context(monkeypatch):
    reference = reference_context(monkeypatch)
    for change in ("verify_mode", "check_hostname", "verify_flags", "options", "minimum_version"):
        weaker = http.tls_context()
        if change == "verify_mode":
            weaker.check_hostname = False
            weaker.verify_mode = ssl.CERT_NONE
        elif change == "check_hostname":
            weaker.check_hostname = False
        elif change == "verify_flags":
            weaker.verify_flags &= ~ssl.VERIFY_X509_PARTIAL_CHAIN & ~ssl.VERIFY_X509_STRICT
            weaker.verify_flags |= ssl.VERIFY_DEFAULT if False else 0
            if weaker.verify_flags == reference.verify_flags:
                weaker.verify_flags = ssl.VERIFY_DEFAULT
        elif change == "options":
            weaker.options &= ~ssl.OP_NO_COMPRESSION
        else:
            weaker.minimum_version = ssl.TLSVersion.TLSv1_2 if reference.minimum_version != ssl.TLSVersion.TLSv1_2 \
                else ssl.TLSVersion.TLSv1_3
        assert context_differences(weaker, reference), change


def test_every_https_request_uses_that_context():
    context = https_handler_context(http)
    assert isinstance(context, ssl.SSLContext) and context.keylog_filename is None


def test_an_https_request_never_builds_a_default_context(monkeypatch):
    """A request (to a closed local port: no network) builds no context of its own."""

    def refused(*args, **kwargs):
        raise AssertionError("a default TLS context was built")

    monkeypatch.setattr(ssl, "create_default_context", refused)
    monkeypatch.setattr(ssl, "_create_default_https_context", refused)
    seen = []
    real = http._WatchedHTTPSConnection.__init__

    def init(self, *args, **kwargs):
        seen.append(kwargs.get("context"))
        real(self, *args, **kwargs)

    monkeypatch.setattr(http._WatchedHTTPSConnection, "__init__", init)
    for name in ("https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises((urllib.error.URLError, OSError)):
        http.http_get("https://127.0.0.1:9/", {}, timeout=2.0)
    assert seen and all(context is https_handler_context(http) for context in seen)


PROBE = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
import importlib, pkgutil
import hearthwire
# Every helper module, as the CLI could import it.
for info in pkgutil.walk_packages(hearthwire.__path__, "hearthwire."):
    if not info.name.endswith("__main__"):  # That one runs the CLI.
        importlib.import_module(info.name)
from hearthwire.core import http
try:
    http.http_get("https://127.0.0.1:9/", {}, timeout=2.0)
except Exception:
    pass
print("exists" if os.path.exists(os.environ["SSLKEYLOGFILE"]) else "absent")
'''


def run_probe(tmp_path, src, source=PROBE):
    log = tmp_path / "keys.log"
    script = tmp_path / "probe.py"
    script.write_text(source)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "SSLKEYLOGFILE": str(log), "LANG": "C.UTF-8"}
    if os.environ.get("TMPDIR"):
        env["TMPDIR"] = os.environ["TMPDIR"]
    # Not -I (that implies -E, and ssl ignores SSLKEYLOGFILE then): the front ends start the
    # helper without it. The environment is built from nothing, no user site, no script dir.
    completed = subprocess.run([sys.executable, "-s", "-P", str(script), str(src)], env=env, capture_output=True,
                               text=True, timeout=60, check=False)
    assert completed.returncode == 0, completed.stderr[-2000:]
    return completed.stdout.strip(), log


def test_with_sslkeylogfile_set_no_helper_module_writes_a_key_log(tmp_path):
    answer, log = run_probe(tmp_path, SRC)
    assert answer == "absent" and not log.exists()


def test_proof_the_probe_sees_a_key_log(tmp_path):
    """The same probe with the old opener (http.client's default context) does create the file."""
    copy = tmp_path / "src"
    (copy / "hearthwire").mkdir(parents=True)
    source = HTTP_PY.read_text(encoding="utf-8")
    old = "                                      _WatchedHTTPSHandler(context=tls_context()))"
    assert old in source
    mutated = source.replace(old, "                                      _WatchedHTTPSHandler)", 1)
    for path in SRC.joinpath("hearthwire").rglob("*.py"):
        target = copy / path.relative_to(SRC)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(mutated if path == HTTP_PY else path.read_text(encoding="utf-8"), encoding="utf-8")
    answer, log = run_probe(tmp_path, copy)
    assert answer == "exists" and log.exists()


def keylog_rule_problems(module):
    problems = []
    if module.tls_context().keylog_filename is not None:
        problems.append("the context keeps a key log")
    if https_handler_context(module) is None:
        problems.append("the HTTPS handler has no context (http.client builds a default one)")
    return problems


def test_the_key_log_rule_holds(monkeypatch, tmp_path):
    monkeypatch.setenv("SSLKEYLOGFILE", str(tmp_path / "keys.log"))
    assert keylog_rule_problems(http) == []
    assert not (tmp_path / "keys.log").exists()


KEYLOG_MUTATIONS = {
    "the default context": ("    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # CERT_REQUIRED, check_hostname.\n",
                            "    context = ssl.create_default_context()\n"),
    "no context given": ("                                      _WatchedHTTPSHandler(context=tls_context()))",
                         "                                      _WatchedHTTPSHandler)"),
    "the key log from the environment": ("    context.keylog_filename = None\n",
                                         "    context.keylog_filename = __import__('os').environ.get('SSLKEYLOGFILE')\n"),
}


@pytest.mark.parametrize("name", sorted(KEYLOG_MUTATIONS))
def test_proof_the_key_log_rule_catches(monkeypatch, tmp_path, name):
    monkeypatch.setenv("SSLKEYLOGFILE", str(tmp_path / "keys.log"))
    copy = mutant(http, *KEYLOG_MUTATIONS[name])
    assert keylog_rule_problems(copy) or (tmp_path / "keys.log").exists()


def test_no_other_helper_module_makes_a_tls_context_or_opener():
    """Only core/http.py talks TLS, and only through tls_context()."""
    patterns = (r"\bcreate_default_context\b", r"\bSSLContext\s*\(", r"\b_create_default_https_context\b",
                r"\burlopen\s*\(", r"\bbuild_opener\s*\(", r"\bHTTPSConnection\b", r"\bwrap_socket\b",
                r"\bimport ssl\b", r"\bfrom ssl\b")
    for path in SRC.joinpath("hearthwire").rglob("*.py"):
        code = path.read_text(encoding="utf-8")
        if path == HTTP_PY:
            tree = ast.parse(code)
            makers = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                      and ast.unparse(node.func) in ("ssl.SSLContext", "ssl.create_default_context")]
            assert [ast.unparse(node) for node in makers] == ["ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)"]
            assert "create_default_context(" not in code.replace("``ssl.create_default_context()``", "")
            continue
        for pattern in patterns:
            assert not re.search(pattern, code), (path.name, pattern)
