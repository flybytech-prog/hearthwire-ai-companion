"""JSON nesting depth is limited before json.loads (core/jsondepth.py).

The CI runner's Python parsed 100000 nested brackets without a
RecursionError, so the settings backup accepted them. The limit is now an
explicit count, checked by a scan that never calls json.loads; these tests
also prove that with the interpreter's recursion limit raised, and with
json.loads replaced by a function that fails the test if a deep document
ever reaches it.
"""

import ast
import json
import sys
from pathlib import Path

import pytest

from hearthwire.core import jsondepth, settingsbackup, usagehistory
from hearthwire.core.jsondepth import check_depth

BUCKET = usagehistory.BUCKET_SECONDS


def nested(depth, inner="1"):
    return "[" * depth + inner + "]" * depth


# --- the scan ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("limit", [1, 4, 6])
def test_at_the_limit_passes_and_one_over_fails(limit):
    check_depth(nested(limit), limit)
    with pytest.raises(ValueError, match="too deeply nested"):
        check_depth(nested(limit + 1), limit)


def test_objects_count_like_arrays():
    check_depth('{"a":{"b":[1]}}', 3)
    with pytest.raises(ValueError):
        check_depth('{"a":{"b":[1]}}', 2)


def test_siblings_do_not_add_up():
    check_depth("[[1],[2],[3],{},{}]", 2)


def test_brackets_inside_a_string_do_not_count():
    check_depth(json.dumps(["[" * 1000 + "{" * 1000]), 1)
    check_depth(json.dumps({"a": "]]]]}}}}" + "[" * 50}), 1)


def test_an_escaped_quote_does_not_end_the_string():
    # The string is \"[[[[[[ : the brackets after the escaped quote are still inside it.
    text = '["\\"' + "[" * 10 + '"]'
    assert json.loads(text) == ['"' + "[" * 10]
    check_depth(text, 1)


def test_an_escaped_backslash_does_end_the_string():
    # "\\" is a whole string (one backslash), so the brackets after it are real.
    text = '["\\\\",' + nested(5) + "]"
    assert json.loads(text)[0] == "\\"
    check_depth(text, 6)
    with pytest.raises(ValueError):
        check_depth(text, 5)


def test_backslash_runs_and_unicode_escapes():
    check_depth(json.dumps(["\\" * 7 + '"' + "[" * 9, "é[", "\\u005b" * 9]), 1)
    text = '["\\\\\\\\\\"[[[[[[["]'  # \\ \\ \" then brackets: still one string
    assert len(json.loads(text)) == 1
    check_depth(text, 1)


def test_the_ci_document_is_refused_without_reaching_json():
    check = nested(100000, "")
    with pytest.raises(ValueError):
        check_depth(check, 4)


def test_deep_brackets_after_a_string_are_counted():
    with pytest.raises(ValueError):
        check_depth('["a]",' + nested(10) + "]", 4)


def test_the_scan_is_linear(monkeypatch):
    # Every significant character is looked at once: a 1 MB string full of
    # escapes is one pass, not a backtracking regex.
    text = json.dumps(["\\\"" * 250000])
    calls = []
    real = jsondepth._SIGNIFICANT

    class Counting:
        def finditer(self, value):
            calls.append(len(value))
            return real.finditer(value)

    monkeypatch.setattr(jsondepth, "_SIGNIFICANT", Counting())
    check_depth(text, 1)
    assert calls == [len(text)]


# --- the loaders ------------------------------------------------------------------------------------


def test_strict_loads_accepts_its_limit_and_refuses_one_over():
    limit = settingsbackup.MAX_JSON_DEPTH
    assert limit == 4
    assert settingsbackup.strict_loads(nested(limit)) == json.loads(nested(limit))
    with pytest.raises(ValueError, match="too deeply nested"):
        settingsbackup.strict_loads(nested(limit + 1))


def test_strict_loads_does_not_count_brackets_in_strings():
    text = json.dumps({"a": ["[" * 100 + "\\\"" + "{" * 100]})
    assert settingsbackup.strict_loads(text) == json.loads(text)


def _nested_list(depth):
    value = 1
    for _ in range(depth):
        value = [value]
    return value


def _history(extra_points):
    """A history document with one good series and one whose point nests ``extra_points``.

    Built without json.loads, so it works while json.loads is replaced."""
    provider_id, metric_id = usagehistory.PAIRS[0]
    other_provider, other_metric = usagehistory.PAIRS[1]
    document = {"history_version": usagehistory.HISTORY_VERSION, "series": [
        {"provider_id": provider_id, "metric_id": metric_id, "points": [[BUCKET, 40]]},
        {"provider_id": other_provider, "metric_id": other_metric,
         "points": ["DEEP"]},
    ]}
    text = json.dumps(document)
    return text.replace('"DEEP"', nested(extra_points)).encode("ascii")


def test_usage_history_accepts_its_limit_and_refuses_one_over():
    assert usagehistory.MAX_JSON_DEPTH == 6
    # document > series > entry > points > a point nested 2 more = depth 6.
    kept = usagehistory.decode(_history(2))
    assert kept == {usagehistory.PAIRS[0]: {BUCKET: 40}}
    # One level more: the whole file is refused, not just that odd point.
    assert usagehistory.decode(_history(3)) == {}


def test_a_real_history_file_is_within_the_limit():
    pair = usagehistory.PAIRS[0]
    history = {pair: {BUCKET * hour: hour % 101 for hour in range(1, usagehistory.MAX_POINTS + 1)}}
    data = usagehistory.encode(history)
    check_depth(data.decode("ascii"), usagehistory.MAX_JSON_DEPTH)
    assert usagehistory.decode(data) == history


def test_a_real_backup_document_is_within_the_limit():
    document = settingsbackup.encode_document({"chatSites": '["claude","chatgpt"]'}, "2026-11-10T12:00:00Z")
    check_depth(document.decode("utf-8"), settingsbackup.MAX_JSON_DEPTH)


# --- independent of RecursionError --------------------------------------------------------------------


@pytest.fixture
def huge_recursion_limit():
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(1_000_000)
    try:
        yield
    finally:
        sys.setrecursionlimit(old)


@pytest.fixture
def json_must_not_be_called(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a too deeply nested document reached json.loads")

    monkeypatch.setattr(settingsbackup.json, "loads", refuse)
    return refuse


def test_the_limit_holds_with_a_huge_recursion_limit(huge_recursion_limit):
    # Depth 200 parses everywhere without a RecursionError: only the explicit
    # limit can refuse it.
    with pytest.raises(ValueError, match="too deeply nested"):
        settingsbackup.strict_loads(nested(200))
    assert usagehistory.decode(_history(200)) == {}


def test_a_deep_document_never_reaches_json_loads(json_must_not_be_called):
    # settingsbackup.json and usagehistory.json are the same json module.
    assert usagehistory.json is settingsbackup.json
    for depth in (5, 200, 100000):
        with pytest.raises(ValueError, match="too deeply nested"):
            settingsbackup.strict_loads(nested(depth))
    for depth in (3, 200):
        assert usagehistory.decode(_history(depth)) == {}
    assert usagehistory.decode(nested(100000, "").encode("ascii")) == {}


def test_recursion_error_is_still_caught(monkeypatch):
    def recursing(*args, **kwargs):
        raise RecursionError

    monkeypatch.setattr(settingsbackup.json, "loads", recursing)
    with pytest.raises(ValueError, match="too deeply nested"):
        settingsbackup.strict_loads("[1]")
    assert usagehistory.decode(b"[1]") == {}


def test_the_module_imports_only_re():
    tree = ast.parse(Path(jsondepth.__file__).read_text(encoding="utf-8"))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported == {"__future__", "re"}
