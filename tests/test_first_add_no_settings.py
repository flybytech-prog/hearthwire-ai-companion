"""Task 021: adding the widget must not open Settings by itself.

main.qml cannot be instantiated without a Plasmoid, so this reads the real
file: no first-run timer, no configure trigger in Component.onCompleted or in
any Timer, and the initialSetupComplete flag is still written (the migrations
and chatMigrateLayout depend on it).
"""

import re
from pathlib import Path

MAIN = Path(__file__).resolve().parent.parent / "plasmoid" / "contents" / "ui" / "main.qml"
TRIGGER = re.compile(r"internalAction\(\s*[\"']configure[\"']\s*\)\s*\.\s*trigger\s*\(")


def _block(text, start):
    """The brace-balanced text from the first '{' at or after start."""
    begin = text.index("{", start)
    depth = 0
    for i in range(begin, len(text)):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        if depth == 0:
            return text[begin:i + 1]
    raise AssertionError("unbalanced braces")


def test_no_first_run_settings_timer():
    assert "firstRunSettingsTimer" not in MAIN.read_text(encoding="utf-8")


def test_no_configure_trigger_in_on_completed_or_timers():
    text = MAIN.read_text(encoding="utf-8")
    starts = [m.start() for m in re.finditer(r"Component\.onCompleted\s*:", text)]
    starts += [m.start() for m in re.finditer(r"^\s*Timer\s*\{", text, re.M)]
    assert starts
    for start in starts:
        assert not TRIGGER.search(_block(text, start)), text[start:start + 60]


def test_initial_setup_flag_still_written_on_completed():
    text = MAIN.read_text(encoding="utf-8")
    match = re.search(r"Component\.onCompleted\s*:", text)
    assert match
    assert re.search(r"Plasmoid\.configuration\.initialSetupComplete\s*=\s*true", _block(text, match.start()))
