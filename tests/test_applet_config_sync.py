"""core/appletconfig.CONFIG_ENTRIES stays equal to plasmoid/contents/config/main.xml.

Export reads the applied settings from Plasma's rc file, where a key the
widget never changed is absent and means its main.xml default. So every
main.xml entry, its type and its default must be in the Python table, and
nothing else.
"""

import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

from hearthwire.core.appletconfig import CONFIG_ENTRIES
from hearthwire.core.settingsbackup import BACKUP_KEYS, RULES

ROOT = Path(__file__).resolve().parent.parent
MAIN_XML = ROOT / "plasmoid" / "contents" / "config" / "main.xml"
KCFG = "{http://www.kde.org/standards/kcfg/1.0}"


def main_xml_entries(text):
    """{name: (type, default)} of group General, defaults as KConfigSkeleton reads them."""
    root = ElementTree.fromstring(text)
    groups = root.findall(f"{KCFG}group")
    assert [group.get("name") for group in groups] == ["General"]
    entries = {}
    for entry in groups[0].findall(f"{KCFG}entry"):
        name, kind = entry.get("name"), entry.get("type")
        assert name not in entries, name
        default = entry.find(f"{KCFG}default")
        text_value = "" if default is None or default.text is None else default.text
        if kind == "Int":
            value = int(text_value)
        elif kind == "Bool":
            assert text_value in ("true", "false"), (name, text_value)
            value = text_value == "true"
        else:
            value = text_value
        entries[name] = (kind, value)
    return entries


def sync_problems(xml_text, table):
    xml_entries = main_xml_entries(xml_text)
    problems = [f"{name}: only in main.xml" for name in xml_entries if name not in table]
    problems += [f"{name}: only in CONFIG_ENTRIES" for name in table if name not in xml_entries]
    for name in xml_entries.keys() & table.keys():
        if xml_entries[name] != table[name] or type(xml_entries[name][1]) is not type(table[name][1]):
            problems.append(f"{name}: main.xml {xml_entries[name]!r}, CONFIG_ENTRIES {table[name]!r}")
    return problems


def test_config_entries_equal_main_xml():
    assert sync_problems(MAIN_XML.read_text(encoding="utf-8"), CONFIG_ENTRIES) == []


def test_main_xml_uses_only_the_types_the_reader_knows():
    assert {kind for kind, _ in main_xml_entries(MAIN_XML.read_text(encoding="utf-8")).values()} <= \
        {"String", "Int", "Bool"}


def test_every_backup_default_passes_the_backup_rules():
    """A widget left at its defaults exports every backup key, none dropped."""
    for key in BACKUP_KEYS:
        RULES[key](CONFIG_ENTRIES[key][1])


# --- proofs: each rule catches what it is for -------------------------------------------------------


@pytest.mark.parametrize(("old", "new"), [
    ("<default>300</default>", "<default>600</default>"),                     # a default
    ('name="refreshInterval" type="Int"', 'name="refreshInterval" type="String"'),  # a type
    ("<default>auto</default>", "<default></default>"),
    ('<entry name="usageHistoryClearOwed" type="Bool">\n            <default>false</default>\n        </entry>\n',
     ""),                                                                       # a removed key
    ("    </group>", '        <entry name="newKey" type="String">\n            <default>x</default>\n'
                     "        </entry>\n    </group>"),                          # an added key
    ('<entry name="showUsageTab" type="Bool">\n            <default>true</default>',
     '<entry name="showUsageTab" type="Bool">\n            <default>false</default>'),
])
def test_proof_a_main_xml_change_without_the_table_is_caught(old, new):
    text = MAIN_XML.read_text(encoding="utf-8")
    assert old in text
    assert sync_problems(text.replace(old, new, 1), CONFIG_ENTRIES) != []


def test_proof_a_table_change_without_main_xml_is_caught():
    text = MAIN_XML.read_text(encoding="utf-8")
    for changed in (dict(CONFIG_ENTRIES, refreshInterval=("Int", 301)),
                    dict(CONFIG_ENTRIES, refreshInterval=("Int", True)),
                    dict(CONFIG_ENTRIES, extra=("String", "")),
                    {key: value for key, value in CONFIG_ENTRIES.items() if key != "panelRing"}):
        assert sync_problems(text, changed) != []
