"""core/catalog.py and plasmoid ProviderCatalog.js must describe the same providers."""

import json
import re
from pathlib import Path

from hearthwire.core.catalog import catalog_json


CATALOG_JS = (
    Path(__file__).resolve().parent.parent
    / "plasmoid" / "contents" / "ui" / "ProviderCatalog.js"
)
JS_KEYS = {"provider_id", "display_name", "icon", "color", "default_metric", "metrics"}
PYTHON_ONLY_KEYS = ("executable_names", "installation_indicators")


def _providers_literal(source):
    marker = "var providers = "
    start = source.index(marker) + len(marker)
    assert source[start] == "[", "ProviderCatalog.js providers must be an array literal"
    depth = 0
    quote = None
    for index in range(start, len(source)):
        char = source[index]
        if quote is not None:
            if char == "\\":
                continue
            if char == quote and source[index - 1] != "\\":
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError("unterminated providers array in ProviderCatalog.js")


def _js_providers():
    literal = _providers_literal(CATALOG_JS.read_text(encoding="utf-8"))
    quoted = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', literal)
    # json.loads fails loudly if the array stops being a plain literal.
    return json.loads(quoted)


def test_js_catalog_matches_python_catalog():
    expected = [
        {key: value for key, value in entry.items() if key not in PYTHON_ONLY_KEYS}
        for entry in catalog_json()
    ]
    assert _js_providers() == expected


def test_js_catalog_entries_have_exactly_the_shared_keys():
    for entry in _js_providers():
        assert set(entry) == JS_KEYS, entry.get("provider_id")
