"""Task 011: core/appconfig.py reads exactly the main.xml keys, with main.xml's types and defaults.

The app's settings.json holds the same group General keys the widget keeps
in Plasma's rc file, so the reader goes by appletconfig.CONFIG_ENTRIES
(itself kept equal to main.xml by test_applet_config_sync.py). Here: every
main.xml default, written as JSON the way the app writes it, reads back as
itself; an empty settings object reads as every main.xml default; and no
key outside main.xml is ever returned.
"""

import json

import pytest

from hearthwire.core import appconfig, appletconfig
from hearthwire.core.appletconfig import UNREADABLE
from test_applet_config_sync import MAIN_XML, main_xml_entries, sync_problems


def xml_entries():
    return main_xml_entries(MAIN_XML.read_text(encoding="utf-8"))


def app_sync_problems(entries, module=appconfig):
    """What the reader gets wrong about ``entries`` ({name: (type, default)}, as main.xml says)."""
    problems = []
    keys = list(entries)
    try:
        defaults = module.applied_from({}, keys)
    except KeyError as error:
        return [f"{error.args[0]}: unknown to the reader"]
    for name, (kind, default) in entries.items():
        if defaults.get(name) != default or type(defaults.get(name)) is not type(default):
            problems.append(f"{name}: absent reads {defaults.get(name)!r}, main.xml says {default!r}")
        written = json.loads(json.dumps({name: default}))
        value = module.applied_from(written, [name])[name]
        if value is UNREADABLE or value != default or type(value) is not type(default):
            problems.append(f"{name}: {kind} {default!r} as JSON reads {value!r}")
    if set(module.applied_from({"notInMainXml": 1}, keys)) != set(keys):
        problems.append("a key outside main.xml is returned")
    return problems


def test_the_reader_table_is_main_xml():
    assert sync_problems(MAIN_XML.read_text(encoding="utf-8"), appletconfig.CONFIG_ENTRIES) == []
    assert appconfig.CONFIG_ENTRIES is appletconfig.CONFIG_ENTRIES


def test_every_main_xml_default_reads_back_as_itself():
    assert app_sync_problems(xml_entries()) == []


def test_main_xml_types_are_the_ones_the_reader_knows():
    for kind, default in xml_entries().values():
        value = appconfig.typed_value(kind, default)
        assert value == default and type(value) is type(default)


def test_proof_a_main_xml_key_the_reader_does_not_know_is_caught():
    assert app_sync_problems({**xml_entries(), "newKey": ("String", "x")})


@pytest.mark.parametrize(("old", "new"), [
    ("        result[key] = typed_value(kind, settings[key]) if key in settings else (\n            list(default) if isinstance(default, list) else default)\n",
     "        result[key] = typed_value(kind, settings[key]) if key in settings else None\n"),
    ("        result[key] = typed_value(kind, settings[key]) if key in settings else (\n            list(default) if isinstance(default, list) else default)\n",
     "        result[key] = settings.get(key, default) if kind != \"Int\" else str(settings.get(key, default))\n"),
    ('    if kind == "Bool":\n        return value if type(value) is bool else UNREADABLE\n',
     '    if kind == "Bool":\n        return UNREADABLE\n'),
])
def test_proof_a_reader_that_misreads_main_xml_is_caught(old, new):
    from test_frontend import mutant

    assert app_sync_problems(xml_entries(), mutant(appconfig, old, new))


def test_proof_a_reader_that_drops_the_string_list_type_is_caught():
    from test_frontend import mutant

    assert app_sync_problems(xml_entries(), mutant(
        appconfig, '    if kind == "StringList":\n', '    if kind == "NoSuchKind":\n'))
