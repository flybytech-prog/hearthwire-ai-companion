"""Print the release version from pyproject.toml, or refuse.

Usage: python3 -I packaging/check-version.py [--tag TAG] < pyproject.toml

The version must be exactly X.Y.Z (digits only, no newline or anything
else), since it ends up in file names and in GitHub's $GITHUB_OUTPUT. With
--tag, the tag must be exactly "v" + that version. On any problem nothing
goes to stdout, a fixed message goes to stderr, and the exit status is 1.
Run with -I: only the standard library is used.
"""

import re
import sys
import tomllib

VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


def release_version(pyproject: str, tag: "str | None" = None) -> str:
    """The checked version; ValueError with a fixed message otherwise."""
    try:
        version = tomllib.loads(pyproject)["project"]["version"]
    except (tomllib.TOMLDecodeError, KeyError, TypeError):
        raise ValueError("pyproject.toml has no [project] version") from None
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise ValueError("the version in pyproject.toml is not a plain X.Y.Z")
    if tag is not None and tag != "v" + version:
        raise ValueError("the tag is not exactly v" + version)
    return version


def main(argv: list[str]) -> int:
    if argv not in ([], ) and not (len(argv) == 2 and argv[0] == "--tag"):
        print("Usage: check-version.py [--tag TAG] < pyproject.toml", file=sys.stderr)
        return 2
    try:
        version = release_version(sys.stdin.read(), argv[1] if argv else None)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    print(version)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
