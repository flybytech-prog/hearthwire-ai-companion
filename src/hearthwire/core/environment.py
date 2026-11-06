from __future__ import annotations

import os
import pwd
import subprocess
from collections.abc import Mapping
from typing import Optional, Protocol


_SUPPORTED_NAMES = (
    "CLAUDE_CONFIG_DIR",
    "CODEX_HOME",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "PATH",
)
_BEGIN_MARKER = "__HEARTHWIRE_ENV_BEGIN__"
_END_MARKER = "__HEARTHWIRE_ENV_END__"
_VAR_MARKER = "__HEARTHWIRE_ENV_VAR__"


class ProcessRunner(Protocol):
    def __call__(
        self,
        args: list[str],
        *,
        env: Mapping[str, str],
        timeout: float,
    ) -> subprocess.CompletedProcess[str]: ...


def _run_process(
    args: list[str],
    *,
    env: Mapping[str, str],
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        env=dict(env),
        timeout=timeout,
        check=False,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        encoding="utf-8",
        errors="replace",
    )


class LoginShellEnvironment:
    """Read selected values from this process, then from the login shell.

    Plasma helpers do not always inherit the user's interactive PATH. Only a
    fixed allow-list is captured, and startup-file noise is ignored by parsing
    only the lines between begin/end markers. The command uses nothing but
    ``echo`` and ``printenv`` so it runs unchanged in POSIX shells and fish.
    """

    def __init__(
        self,
        environ: Optional[Mapping[str, str]] = None,
        runner: ProcessRunner = _run_process,
        timeout: float = 5.0,
    ):
        self._environ = dict(os.environ if environ is None else environ)
        self._runner = runner
        self._timeout = timeout
        self._captured: Optional[dict[str, str]] = None

    def value(self, name: str) -> Optional[str]:
        if name not in _SUPPORTED_NAMES:
            return None
        direct = self._clean(self._environ.get(name))
        if direct is not None:
            return direct
        if self._captured is None:
            self._captured = self._capture()
        return self._captured.get(name)

    def snapshot(self) -> dict[str, str]:
        return {
            name: value
            for name in _SUPPORTED_NAMES
            if (value := self.value(name)) is not None
        }

    def search_path(self) -> str:
        """Merge the process and login-shell PATH values for CLI discovery."""
        direct = self._clean(self._environ.get("PATH"))
        if self._captured is None:
            self._captured = self._capture()
        captured = self._clean(self._captured.get("PATH"))

        entries: list[str] = []
        for value in (direct, captured):
            if value is None:
                continue
            for entry in value.split(os.pathsep):
                if entry and entry not in entries:
                    entries.append(entry)
        return os.pathsep.join(entries)

    def _capture(self) -> dict[str, str]:
        shell = self._shell()
        command = self.command()
        child_env = {
            key: value
            for key in ("HOME", "USER", "LOGNAME", "SHELL", "TERM")
            if (value := self._environ.get(key))
        }
        child_env.setdefault("HOME", os.path.expanduser("~"))
        child_env.setdefault("SHELL", shell)
        child_env.setdefault("TERM", "dumb")
        child_env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
        try:
            result = self._runner(
                [shell, "-ilc", command],
                env=child_env,
                timeout=self._timeout,
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return {}
        # Startup files may make the shell exit non-zero after our output;
        # parse() only trusts text framed by both markers.
        return self.parse(result.stdout or "")

    def _shell(self) -> str:
        configured = self._clean(self._environ.get("SHELL"))
        if configured and os.path.isfile(configured) and os.access(configured, os.X_OK):
            return configured
        try:
            account_shell = pwd.getpwuid(os.getuid()).pw_shell
        except (KeyError, OSError):
            account_shell = ""
        if account_shell and os.path.isfile(account_shell) and os.access(account_shell, os.X_OK):
            return account_shell
        return "/bin/sh"

    @staticmethod
    def command() -> str:
        """Shell-agnostic capture command built only from constants."""
        parts = [f"echo {_BEGIN_MARKER}"]
        for name in _SUPPORTED_NAMES:
            parts.append(f"echo {_VAR_MARKER}{name}")
            parts.append(f"printenv {name}")
        parts.append(f"echo {_END_MARKER}")
        return "; ".join(parts)

    @staticmethod
    def parse(output: str) -> dict[str, str]:
        begin = output.find(_BEGIN_MARKER)
        if begin < 0:
            return {}
        begin += len(_BEGIN_MARKER)
        end = output.find(_END_MARKER, begin)
        if end < 0:
            return {}

        # Drop any partial line in front of the end marker (prompt escapes).
        framed = output[begin:end]
        framed = framed[:framed.rfind("\n") + 1]

        collected: dict[str, list[str]] = {}
        current: Optional[str] = None
        for line in framed.splitlines():
            marker = line.find(_VAR_MARKER)
            if marker >= 0:
                name = line[marker + len(_VAR_MARKER):].strip()
                current = name if name in _SUPPORTED_NAMES else None
                if current is not None:
                    collected[current] = []
                continue
            if current is not None:
                collected[current].append(line)

        values: dict[str, str] = {}
        for name, lines in collected.items():
            value = "\n".join(lines).strip()
            if value and "\ufffd" not in value:
                values[name] = value
        return values

    @staticmethod
    def _clean(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None
