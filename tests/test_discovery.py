import re
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from hearthwire.core import environment as environment_module
from hearthwire.core.discovery import detect_installed_providers
from hearthwire.core.environment import _SUPPORTED_NAMES, LoginShellEnvironment


class _Environment:
    def __init__(self, values):
        self.values = values

    def value(self, name):
        return self.values.get(name)


def test_login_shell_environment_prefers_process_and_parses_markers():
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "startup noise\n"
                "__HEARTHWIRE_ENV_BEGIN__\n"
                "__HEARTHWIRE_ENV_VAR__CLAUDE_CONFIG_DIR\n"
                "/profiles/work\n"
                "__HEARTHWIRE_ENV_VAR__CODEX_HOME\n"
                "/profiles/codex\n"
                "__HEARTHWIRE_ENV_VAR__PATH\n"
                "/login/bin:/process/bin\n"
                "__HEARTHWIRE_ENV_END__\n"
                "more noise"
            ),
            stderr="",
        )

    environment = LoginShellEnvironment(
        environ={
            "PATH": "/process/bin",
            "SHELL": "/bin/sh",
            "HOME": "/tmp/home",
        },
        runner=runner,
    )
    assert environment.value("PATH") == "/process/bin"
    assert calls == []
    assert environment.search_path() == "/process/bin:/login/bin"
    assert len(calls) == 1
    assert environment.value("CLAUDE_CONFIG_DIR") == "/profiles/work"
    assert environment.value("CODEX_HOME") == "/profiles/codex"
    assert len(calls) == 1
    assert environment.value("UNSUPPORTED_SECRET") is None


def test_detects_executables_and_installation_indicators(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    claude.write_text("#!/bin/sh\n", encoding="utf-8")
    claude.chmod(0o755)
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()

    installed = detect_installed_providers(_Environment({
        "PATH": str(bin_dir),
        "CODEX_HOME": str(codex_home),
    }))
    assert installed == {"claude", "codex"}


def test_detects_executable_from_login_shell_path(tmp_path):
    bin_dir = tmp_path / "login-bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    claude.write_text("#!/bin/sh\n", encoding="utf-8")
    claude.chmod(0o755)

    def runner(args, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "__HEARTHWIRE_ENV_BEGIN__\n"
                "__HEARTHWIRE_ENV_VAR__PATH\n"
                f"{bin_dir}\n"
                "__HEARTHWIRE_ENV_END__\n"
            ),
            stderr="",
        )

    environment = LoginShellEnvironment(
        environ={
            "PATH": "/usr/bin",
            "SHELL": "/bin/sh",
            "HOME": str(tmp_path),
        },
        runner=runner,
    )
    exists_in_test = lambda path: path.exists() and tmp_path in path.parents
    assert detect_installed_providers(
        environment,
        exists=exists_in_test,
    ) == {"claude"}


def test_non_executable_file_does_not_count_as_cli(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text("not executable", encoding="utf-8")
    environment = _Environment({
        "PATH": str(bin_dir),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "missing-claude"),
        "CODEX_HOME": str(tmp_path / "missing-codex"),
    })
    exists_in_test = lambda path: path.exists() and tmp_path in path.parents
    assert detect_installed_providers(environment, exists=exists_in_test) == set()


def test_custom_claude_directory_is_an_installation_indicator(tmp_path):
    config_dir = tmp_path / "claude-profile"
    config_dir.mkdir()
    environment = _Environment({
        "PATH": "",
        "CLAUDE_CONFIG_DIR": str(config_dir),
    })
    exists_in_test = lambda path: path.exists() and tmp_path in path.parents
    assert detect_installed_providers(environment, exists=exists_in_test) == {"claude"}


def test_detects_all_reference_cli_names_in_catalog_order(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in (
        "claude",
        "codex",
        "cursor-agent",
        "agy-ide",
        "github-copilot",
        "devin",
        "grok",
    ):
        executable = bin_dir / name
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o755)
    installed = detect_installed_providers(_Environment({"PATH": str(bin_dir)}))
    assert installed == {
        "claude", "codex", "cursor", "antigravity", "copilot", "devin", "grok"
    }


def test_parse_tolerates_noise_and_filters_values():
    output = (
        "\x1b]0;title\x07welcome banner\n"
        "\x1b[0m__HEARTHWIRE_ENV_BEGIN__\n"
        "__HEARTHWIRE_ENV_VAR__CLAUDE_CONFIG_DIR\n"
        "__HEARTHWIRE_ENV_VAR__CODEX_HOME\n"
        "/profiles/codex\n"
        "__HEARTHWIRE_ENV_VAR__AWS_SECRET_ACCESS_KEY\n"
        "must-not-be-read\n"
        "__HEARTHWIRE_ENV_VAR__XDG_DATA_HOME\n"
        "/broken/\ufffd/path\n"
        "__HEARTHWIRE_ENV_VAR__PATH\n"
        "/login/bin\n"
        "\x1b[0m__HEARTHWIRE_ENV_END__\n"
        "goodbye noise\n"
    )
    assert LoginShellEnvironment.parse(output) == {
        "CODEX_HOME": "/profiles/codex",
        "PATH": "/login/bin",
    }


def test_parse_requires_end_marker():
    output = (
        "__HEARTHWIRE_ENV_BEGIN__\n"
        "__HEARTHWIRE_ENV_VAR__CODEX_HOME\n"
        "/profiles/codex\n"
    )
    assert LoginShellEnvironment.parse(output) == {}
    assert LoginShellEnvironment.parse("no markers at all") == {}


def test_capture_parses_framed_output_even_on_nonzero_exit():
    def runner(args, **kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout=(
                "__HEARTHWIRE_ENV_BEGIN__\n"
                "__HEARTHWIRE_ENV_VAR__CODEX_HOME\n"
                "/profiles/codex\n"
                "__HEARTHWIRE_ENV_END__\n"
            ),
            stderr="",
        )

    environment = LoginShellEnvironment(
        environ={"SHELL": "/bin/sh", "HOME": "/tmp/home"},
        runner=runner,
    )
    assert environment.value("CODEX_HOME") == "/profiles/codex"


@pytest.mark.parametrize("error", [
    OSError("no shell"),
    subprocess.TimeoutExpired("sh", 5),
    ValueError("bad"),
])
def test_capture_failures_yield_no_values(error):
    def runner(args, **kwargs):
        raise error

    environment = LoginShellEnvironment(
        environ={"SHELL": "/bin/sh", "HOME": "/tmp/home"},
        runner=runner,
    )
    assert environment.value("CODEX_HOME") is None
    assert environment.search_path() == ""


def test_capture_command_is_shell_agnostic_and_allow_listed():
    command = LoginShellEnvironment.command()
    assert not re.search(r"\bfor\b", command)
    assert not re.search(r"\bdo\b", command)
    assert "$(" not in command
    assert "\\0" not in command and "\0" not in command
    statements = [part.strip() for part in command.split(";")]
    allowed = (
        {"echo __HEARTHWIRE_ENV_BEGIN__", "echo __HEARTHWIRE_ENV_END__"}
        | {f"echo __HEARTHWIRE_ENV_VAR__{name}" for name in _SUPPORTED_NAMES}
        | {f"printenv {name}" for name in _SUPPORTED_NAMES}
    )
    assert set(statements) <= allowed
    printed = {item.removeprefix("printenv ") for item in statements if item.startswith("printenv ")}
    assert printed == set(_SUPPORTED_NAMES)
    assert command.endswith("echo __HEARTHWIRE_ENV_END__")


def test_run_process_detaches_stdin_and_session(monkeypatch):
    seen = {}

    def fake_run(args, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(environment_module.subprocess, "run", fake_run)
    environment_module._run_process(["/bin/sh", "-c", "true"], env={}, timeout=1)
    assert seen["stdin"] is subprocess.DEVNULL
    assert seen["start_new_session"] is True
    assert seen["encoding"] == "utf-8"
    assert seen["errors"] == "replace"


_SHELL_STARTUP = {
    "sh": (".profile", "export CODEX_HOME=/t/sh\n"),
    "bash": (".bash_profile", "export CODEX_HOME=/t/bash\n"),
    "zsh": (".zshrc", "export CODEX_HOME=/t/zsh\n"),
    "fish": (
        ".config/fish/config.fish",
        "if status is-interactive\n    set -gx CODEX_HOME /t/fish\nend\n",
    ),
}


@pytest.mark.parametrize("shell_name", sorted(_SHELL_STARTUP))
def test_real_login_shell_capture(shell_name, tmp_path):
    shell = shutil.which(shell_name)
    if shell is None:
        pytest.skip(f"{shell_name} is not installed")
    relative, content = _SHELL_STARTUP[shell_name]
    startup = tmp_path / relative
    startup.parent.mkdir(parents=True, exist_ok=True)
    startup.write_text(content, encoding="utf-8")

    environment = LoginShellEnvironment(
        environ={"HOME": str(tmp_path), "SHELL": shell},
        timeout=10.0,
    )
    assert environment.value("CODEX_HOME") == f"/t/{shell_name}"
    assert environment.value("CLAUDE_CONFIG_DIR") is None
