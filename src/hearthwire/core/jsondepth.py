"""A JSON nesting-depth limit checked before ``json.loads`` ever sees the text.

``json.loads`` refuses a deeply nested document only by raising RecursionError,
and whether it does depends on the interpreter build and its stack: one
Python refuses 100000 nested brackets, another parses them. The loaders that
read files Hearthwire did not just write (the settings backup, the usage
history) therefore call ``check_depth`` first, with a small limit that fits
their format, and still catch RecursionError as a second line.

The scan is linear: it looks only at brackets, braces, quotes and
backslashes, skips everything inside JSON strings (a backslash escapes the
next character, so ``"\\""`` stays one string), and stops at the first
bracket past the limit.
"""

from __future__ import annotations

import re

# Characters that can change the depth or the in-string state.
_SIGNIFICANT = re.compile(r'[\[\]{}"\\]')


def check_depth(text: str, limit: int) -> None:
    """Raise ValueError when an array or object in ``text`` opens deeper than ``limit``.

    Depth counts open arrays and objects: ``[]`` and ``{}`` are depth 1,
    ``[[]]`` is 2. Brackets inside strings don't count. Malformed text that
    stays within the limit is left for ``json.loads`` to refuse.
    """
    depth = 0
    in_string = False
    escaped_index = -1
    for match in _SIGNIFICANT.finditer(text):
        char = match.group()
        index = match.start()
        if in_string:
            if index == escaped_index:
                continue  # The character after a backslash: \" or \\.
            if char == "\\":
                escaped_index = index + 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > limit:
                raise ValueError("too deeply nested")
        elif char in "]}":
            depth -= 1


__all__ = ["check_depth"]
