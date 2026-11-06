"""The helper, the Python distribution and the plasmoid must ship one version."""

import json
import tomllib
from pathlib import Path

import hearthwire


ROOT = Path(__file__).resolve().parent.parent
EXPECTED_VERSION = "1.0.0"


def _pyproject_version():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def _plasmoid_version():
    metadata = json.loads((ROOT / "plasmoid" / "metadata.json").read_text(encoding="utf-8"))
    return metadata["KPlugin"]["Version"]


def test_versions_are_in_sync():
    assert hearthwire.__version__ == EXPECTED_VERSION
    assert _pyproject_version() == EXPECTED_VERSION
    assert _plasmoid_version() == EXPECTED_VERSION
