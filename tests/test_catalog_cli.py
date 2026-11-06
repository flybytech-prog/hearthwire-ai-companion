import json

import pytest

from hearthwire import cli
from hearthwire.core.catalog import PROVIDER_IDS, catalog_json
from hearthwire.core.snapshot import collect_snapshot


def test_catalog_has_reference_order_defaults_and_metrics():
    catalog = catalog_json()
    assert tuple(item["provider_id"] for item in catalog) == PROVIDER_IDS
    assert PROVIDER_IDS == (
        "claude", "codex", "cursor", "antigravity", "copilot", "devin", "grok"
    )
    assert catalog[0]["default_metric"] == "weekly"
    assert catalog[2]["default_metric"] == "total_usage"
    assert catalog[4]["default_metric"] == "credits"


def test_cli_provider_filter_is_forwarded(monkeypatch, capsys):
    captured = {}

    def collect(**kwargs):
        captured.update(kwargs)
        return {"schema_version": 2, "providers": []}

    monkeypatch.setattr(cli, "collect_snapshot", collect)
    assert cli.main(["--providers=codex,claude,codex"]) == 0
    assert captured["provider_ids"] == ["codex", "claude"]
    assert json.loads(capsys.readouterr().out)["schema_version"] == 2


def test_cli_catalog_does_not_collect_provider_usage(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "collect_snapshot",
        lambda **kwargs: pytest.fail("catalog must not contact providers"),
    )
    assert cli.main(["--catalog"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 2
    assert len(payload["catalog"]) == 7
    assert payload["providers"] == []


def test_cli_detect_reports_installed_ids_without_providers(monkeypatch, capsys):
    import hearthwire.core.snapshot as snapshot

    monkeypatch.setattr(
        cli,
        "collect_snapshot",
        lambda **kwargs: pytest.fail("detect must not collect provider usage"),
    )
    monkeypatch.setattr(
        snapshot,
        "provider_factory",
        lambda *args: pytest.fail("detect must not build providers"),
    )
    monkeypatch.setattr(
        snapshot,
        "detect_installed_providers",
        lambda environment: {"grok", "claude"},
    )
    assert cli.main(["--detect"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 2
    assert len(payload["catalog"]) == 7
    assert payload["installed_provider_ids"] == ["claude", "grok"]
    assert payload["providers"] == []


def test_cli_catalog_wins_over_detect(monkeypatch, capsys):
    import hearthwire.core.snapshot as snapshot

    monkeypatch.setattr(
        snapshot,
        "detect_installed_providers",
        lambda environment: pytest.fail("catalog must not detect providers"),
    )
    assert cli.main(["--catalog", "--detect"]) == 0
    assert json.loads(capsys.readouterr().out)["installed_provider_ids"] == []


def test_untracked_installed_provider_is_not_instantiated(monkeypatch):
    import hearthwire.core.snapshot as snapshot

    monkeypatch.setattr(
        snapshot,
        "provider_factory",
        lambda *args: pytest.fail("untracked provider must not be instantiated"),
    )
    payload = collect_snapshot(
        installed_provider_ids={"claude"},
        provider_ids=[],
    )
    assert payload["installed_provider_ids"] == ["claude"]
    assert payload["providers"] == []


def test_cli_has_no_update_check(capsys):
    with pytest.raises(SystemExit) as raised:
        cli.main(["--check-update"])
    assert raised.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "--check-update" in output.err
