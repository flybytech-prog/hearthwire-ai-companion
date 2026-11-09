"""The former name (Hearthside) survives only where the migration needs it (plan R2).

``git grep -i hearthside`` over every tracked or new (not ignored) text file
may hit only:

- ``src/hearthwire/core/legacy.py``, the one Python file that knows the old
  names and plugin id, and the ``LEGACY_FOLDER`` line of ``walletkey.py``;
- the migration tests themselves (this file and ``test_legacy_migration.py``);
- blocks between ``# >>> legacy-migration`` and ``# <<< legacy-migration``
  marker lines in ``scripts/install.sh`` and in other tests;
- in ``README.md`` and ``docs/*.md``, sections under a heading whose text is
  exactly ``Upgrading from Hearthside`` (any level; the section ends at the
  next heading of the same or a higher level).
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
OLD = re.compile("hearth" + "side", re.IGNORECASE)
WHOLE_FILES = {"src/hearthwire/core/legacy.py", "tests/test_legacy_migration.py", "tests/test_stale_names.py"}
SINGLE_LINES = {"src/hearthwire/core/walletkey.py": 'LEGACY_FOLDER = "Hearth' + 'side"'}
BLOCK_BEGIN = "# >>> legacy-migration"
BLOCK_END = "# <<< legacy-migration"
BLOCK_FILES = re.compile(r"scripts/install\.sh|tests/[^/]+\.py")
DOC_FILES = re.compile(r"README\.md|docs/[^/]+\.md")
DOC_HEADING = "Upgrading from Hearth" + "side"
_HEADING = re.compile(r"(#{1,6})\s+(.*?)\s*#*\s*$")


def _hits():
    """{path: [(line number, text)]} for every text file git knows (tracked or new)."""
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "grep", "--untracked", "-I", "-i", "-n", "--full-name", "-e", OLD.pattern],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, check=False,
    )
    if completed.returncode not in (0, 1):
        pytest.skip("git grep is not usable here")
    found = {}
    for line in completed.stdout.splitlines():
        path, number, text = line.split(":", 2)
        found.setdefault(path, []).append((int(number), text))
    return found


def _read(path):
    return (ROOT / path).read_text(encoding="utf-8").splitlines()


def block_lines(lines):
    """Line numbers inside (and of) legacy-migration marker blocks."""
    allowed, inside = set(), False
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith(BLOCK_BEGIN):
            assert not inside, f"line {number}: nested {BLOCK_BEGIN}"
            inside = True
        if inside:
            allowed.add(number)
        if stripped == BLOCK_END:
            assert inside, f"line {number}: {BLOCK_END} without a begin"
            inside = False
    assert not inside, f"{BLOCK_BEGIN} is never closed"
    return allowed


def section_lines(lines):
    """Line numbers of sections headed exactly DOC_HEADING (Markdown ATX headings)."""
    allowed, level, fenced = set(), None, False
    for number, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        heading = None if fenced else _HEADING.fullmatch(line)
        if heading:
            depth = len(heading.group(1))
            if level is not None and depth <= level:
                level = None
            if heading.group(2) == DOC_HEADING:
                level = depth
        if level is not None:
            allowed.add(number)
    return allowed


def offenders(found, *, docs):
    problems = []
    for path, lines in sorted(found.items()):
        if path in WHOLE_FILES:
            continue
        is_doc = DOC_FILES.fullmatch(path) is not None
        if is_doc != docs:
            continue
        if path in SINGLE_LINES:
            allowed = {number for number, text in lines if text.strip() == SINGLE_LINES[path]}
        elif BLOCK_FILES.fullmatch(path):
            allowed = block_lines(_read(path))
        elif is_doc:
            allowed = section_lines(_read(path))
        else:
            allowed = set()
        problems += [f"{path}:{number}: {text.strip()}" for number, text in lines if number not in allowed]
    return problems


def test_the_old_name_is_only_where_the_migration_needs_it():
    problems = offenders(_hits(), docs=False)
    assert not problems, "the former name outside the migration:\n" + "\n".join(problems)


def test_the_docs_name_the_old_name_only_in_the_upgrade_section():
    problems = offenders(_hits(), docs=True)
    assert not problems, "the former name outside 'Upgrading from Hearthside':\n" + "\n".join(problems)


def test_the_only_python_files_with_the_old_name_are_the_allowed_ones():
    found = _hits()
    python = {path for path in found if path.startswith("src/") and path.endswith(".py")}
    assert python <= {"src/hearthwire/core/legacy.py", "src/hearthwire/core/walletkey.py"}
    assert [text.strip() for _, text in found.get("src/hearthwire/core/walletkey.py", [])] == \
        [SINGLE_LINES["src/hearthwire/core/walletkey.py"]]


# --- proofs --------------------------------------------------------------------------------------------


def test_proof_a_stray_name_in_code_is_caught():
    found = {"src/hearthwire/core/vault.py": [(3, "APP = 'hearth" + "side'")],
             "plasmoid/contents/ui/main.qml": [(9, "plugin: io.github.flybytechprog.hearth" + "side")]}
    assert len(offenders(found, docs=False)) == 2


def test_proof_a_second_walletkey_line_is_caught():
    found = {"src/hearthwire/core/walletkey.py": [(5, SINGLE_LINES["src/hearthwire/core/walletkey.py"]),
                                                  (9, "FOLDER = 'Hearth" + "side'")]}
    assert offenders(found, docs=False) == ["src/hearthwire/core/walletkey.py:9: FOLDER = 'Hearth" + "side'"]


def test_proof_blocks_and_sections_bound_the_allowance():
    lines = ["a", "  " + BLOCK_BEGIN + ": x", "old", "  " + BLOCK_END, "old again"]
    assert block_lines(lines) == {2, 3, 4}
    with pytest.raises(AssertionError):
        block_lines([BLOCK_BEGIN, "x"])
    doc = ["# Title", "old", "## " + DOC_HEADING, "old", "### Details", "old", "```", "# not a heading", "```",
           "## Next", "old"]
    assert section_lines(doc) == set(range(3, 10))
    assert section_lines(["## Upgrading from Hearth" + "side, sort of", "old"]) == set()
