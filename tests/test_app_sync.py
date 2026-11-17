"""app/tools/sync_plasmoid.py: the app's copy of the plasmoid QML differs only in allowlisted import lines.

Every generated file must equal its source except import lines of the KDE
modules in IMPORTS, which point at Hearthwire.Compat.* with the alias kept.
The .js files (the protected ones too) and main.xml must be byte-identical,
and no generated file may still import an org.kde module.
"""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLASMOID = ROOT / "plasmoid"
UI = PLASMOID / "contents" / "ui"
TOOL = ROOT / "app" / "tools" / "sync_plasmoid.py"
PROTECTED = ("ProviderCatalog.js", "RefreshGate.js", "SnapshotLogic.js")


def _tool():
    # No __pycache__ next to the tool in the repo.
    spec = importlib.util.spec_from_file_location("sync_plasmoid", TOOL)
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


@pytest.fixture(scope="module")
def synced(tmp_path_factory):
    tool = _tool()
    dest = tmp_path_factory.mktemp("synced")
    names = tool.sync(PLASMOID, dest)
    return tool, dest, names


def _sources(tool):
    return {name: path for path, name in tool.plan(PLASMOID.resolve())}


# Plasma's own settings file, named in a configGeneral.qml message: the one
# org.kde text a synced file may keep (it can't import anything).
APPLETSRC = "plasma-org.kde.plasma.desktop-appletsrc"


def _kde_names(text):
    """Every line still naming org.kde anywhere (not only at column 0), whole-line // comments aside."""
    found = []
    for line in text.splitlines():
        if line.lstrip().startswith("//"):
            continue
        if re.search(r"\borg\.kde\.", line.replace(APPLETSRC, "")):
            found.append(line)
    return found


def test_every_ui_file_and_the_config_files_are_synced(synced):
    tool, dest, names = synced
    expected = sorted(p.name for p in UI.iterdir() if p.suffix in (".qml", ".js"))
    assert sorted(set(names) - {"config.qml", "main.xml"}) == expected
    assert {"config.qml", "main.xml"} <= set(names)
    assert sorted(p.name for p in dest.iterdir()) == sorted(names)


def test_js_protected_and_schema_files_are_byte_identical(synced):
    tool, dest, names = synced
    sources = _sources(tool)
    for name in names:
        if name.endswith(".js") or name == "main.xml":
            assert (dest / name).read_bytes() == sources[name].read_bytes(), name
    for name in PROTECTED:
        assert (dest / name).read_bytes() == (UI / name).read_bytes(), name


def test_qml_differs_only_in_allowlisted_import_lines(synced):
    tool, dest, names = synced
    sources = _sources(tool)
    allowed = {"import " + kde: "import " + app for kde, app in tool.IMPORTS.items()}
    for name in names:
        if not name.endswith(".qml"):
            continue
        original = sources[name].read_text(encoding="utf-8").splitlines(keepends=True)
        generated = (dest / name).read_text(encoding="utf-8").splitlines(keepends=True)
        assert len(original) == len(generated), name
        for before, after in zip(original, generated):
            if before == after:
                continue
            match = re.match(r"^import (\S+)( as \w+)?(\r?\n)?$", before)
            assert match is not None, (name, before)
            module, alias, newline = match.group(1), match.group(2) or "", match.group(3) or ""
            assert module in tool.IMPORTS, (name, before)
            assert allowed["import " + module] + alias + newline == after, (name, before, after)


def test_no_generated_file_imports_a_kde_module(synced):
    tool, dest, names = synced
    for name in names:
        if name.endswith(".qml"):
            text = (dest / name).read_text(encoding="utf-8")
            assert _kde_names(text) == [], name
            for line in re.findall(r"^import\s+Hearthwire\.\S+", text, re.MULTILINE):
                assert line.split()[1] in tool.IMPORTS.values(), (name, line)
            # String imports: only the plasmoid's own .js files, by bare name.
            for target in re.findall(r"\bimport\s+[\"']([^\"']*)", text):
                assert re.fullmatch(r"\w+\.js", target) and (dest / target).is_file(), (name, target)
        elif name.endswith(".js"):
            text = (dest / name).read_text(encoding="utf-8")
            assert _kde_names(text) == [], name
            assert not re.search(r"^\s*\.import\b", text, re.MULTILINE), name


def test_import_targets_are_private_names():
    tool = _tool()
    for kde, app in tool.IMPORTS.items():
        assert kde.startswith("org.kde.")
        assert app.startswith("Hearthwire.Compat.") and "org.kde" not in app


def test_unknown_kde_import_stops_the_sync(tmp_path):
    tool = _tool()
    with pytest.raises(tool.SyncError):
        tool.rewrite_qml("import QtQuick\nimport org.kde.plasma.private.foo as Foo\n")
    assert tool.rewrite_qml("import org.kde.kirigami as K\n") == "import Hearthwire.Compat.Kirigami as K\n"


# Review-1 #3 / security L2: every other shape that would still load a KDE
# module (or any file) on a host with KDE installed stops the sync.
@pytest.mark.parametrize("text", [
    "    import org.kde.kirigami\n",                          # indented
    "\timport org.kde.kirigami as Kirigami\n",                # tab
    "import org.kde.kirigami 2.20 as Kirigami\n",             # versioned
    "import org.kde.kirigami as Kirigami // note\n",          # trailing comment
    "import org.kde.kirigami as Kirigami;\n",                 # trailing ';'
    "import QtQuick; import org.kde.kirigami as Kirigami\n",  # ';'-joined
    "import QtQuick\nimport\norg.kde.kirigami\n",              # split over lines
    "import /* x */ org.kde.kirigami\n",                      # comment inside
    "import org.kde.plasma.core as PlasmaCore\r\n" "import org.kde.foo\r\n",
    "Item { Component.onCompleted: Qt.createQmlObject(\"import org.kde.kirigami; Item {}\", this) }\n",
    "text: \"import org.kde.kirigami\"\n",
    "import \"/usr/lib/qt6/qml/org/kde/kirigami/Page.qml\"\n",  # string imports
    "import \"../../../usr/share/plasma/x.js\" as X\n",
    "import \"file:///usr/share/x.js\" as X\n",
    "import \"qrc:/x.js\" as X\n",
    "import \"sub/Helper.js\" as Helper\n",
    "import \"Unknown.js\" as Unknown\n",
    "import 'Known.js' as Known\n",
    "import\"Known.js\" as Known\n",
    "import QtQuick; import \"Known.js\" as Known\n",
    "    import \"Known.js\" as Known\n",
    "import \"Known.js\" as Known; import QtQuick\n",
    "import \"Known.js\" as Known // org.kde\n",
    "Item { Component.onCompleted: Qt.createQmlObject('import \"x\"; Item {}', this) }\n",
])
def test_odd_import_shapes_stop_the_sync(text):
    tool = _tool()
    with pytest.raises(tool.SyncError):
        tool.rewrite_qml(text, {"Known.js"})


@pytest.mark.parametrize("text", [
    "import \"Known.js\" as Known\n",
    "import \"Known.js\"\n",
    "import QtQuick 2.15\n",
    "// Also run with QT_QUICK_CONTROLS_STYLE=org.kde.desktop\n",
    "    // org.kde.kirigami in a comment line\n",
    "text: i18n(\"Check ~/.config/" + APPLETSRC + ".\")\n",
    "onClicked: page.runBackup(\"import\")\n",
    "icon.name: \"document-import\"\n",
    "text: i18n(\"It waits while an import's Replace is pending\")\n",
])
def test_harmless_lines_pass_unchanged(text):
    tool = _tool()
    assert tool.rewrite_qml(text, {"Known.js"}) == text


def test_string_imports_need_a_known_js_name():
    tool = _tool()
    with pytest.raises(tool.SyncError):
        tool.rewrite_qml("import \"Known.js\" as Known\n")
    with pytest.raises(tool.SyncError):
        tool.rewrite_qml("import \"Other.js\" as Other\n", {"Known.js"})


@pytest.mark.parametrize("text", [
    ".import \"Other.js\" as Other\n",
    ".import org.kde.kirigami 2.0 as Kirigami\n",
    "  .import QtQuick.LocalStorage 2.0 as Sql\n",
    "var name = \"org.kde.kirigami\";\n",
])
def test_js_files_never_import_or_name_kde(text):
    tool = _tool()
    with pytest.raises(tool.SyncError):
        tool.check_js(text)
    tool.check_js(".pragma library\nvar OPERATIONS = [\"status\", \"import\"]\n// org.kde in a comment\n")


def test_a_bad_js_file_stops_the_whole_sync(tmp_path):
    tool = _tool()
    source = tmp_path / "plasmoid"
    (source / "contents" / "ui").mkdir(parents=True)
    (source / "contents" / "config").mkdir()
    (source / "contents" / "config" / "config.qml").write_text("import QtQuick\n")
    (source / "contents" / "config" / "main.xml").write_text("<kcfg/>\n")
    (source / "contents" / "ui" / "A.js").write_text(".import org.kde.kirigami 2.0 as K\n")
    with pytest.raises(tool.SyncError):
        tool.sync(source, tmp_path / "out")
    assert tool.main(["--source", str(source), "--dest", str(tmp_path / "out2")]) == 1


def test_dest_inside_the_plasmoid_is_refused(tmp_path):
    tool = _tool()
    with pytest.raises(tool.SyncError):
        tool.sync(PLASMOID, PLASMOID / "contents" / "ui" / "out")
    assert not (UI / "out").exists()


def test_exclude_leaves_a_file_out(tmp_path):
    tool = _tool()
    names = tool.sync(PLASMOID, tmp_path, exclude={"ChatWebView.qml"})
    assert "ChatWebView.qml" not in names and not (tmp_path / "ChatWebView.qml").exists()


def test_command_line_reports_errors_without_traceback(tmp_path, capsys):
    tool = _tool()
    assert tool.main(["--source", str(tmp_path), "--dest", str(tmp_path / "out")]) == 1
    assert "sync_plasmoid:" in capsys.readouterr().err


# app/tools/sync_qml_tests.py: the plasmoid's tests/qml under the stand-ins.
TESTS_QML = ROOT / "tests" / "qml"
TESTS_TOOL = ROOT / "app" / "tools" / "sync_qml_tests.py"


def _tests_tool():
    spec = importlib.util.spec_from_file_location("sync_qml_tests", TESTS_TOOL)
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def test_qml_tests_differ_only_in_kde_imports_and_ui_paths(tmp_path):
    tool = _tests_tool()
    synced = tmp_path / "synced"
    dest = tmp_path / "qmltests"
    names = tool.sync(TESTS_QML, dest, synced, exclude={"tst_chat_web_view.qml"})
    expected = sorted(p.name for p in TESTS_QML.iterdir() if p.suffix in (".qml", ".js") and p.name != "tst_chat_web_view.qml")
    assert sorted(names) == expected
    allowed = {"import " + kde: "import " + app for kde, app in tool.SYNC.IMPORTS.items()}
    for name in names:
        original = (TESTS_QML / name).read_text(encoding="utf-8").splitlines(keepends=True)
        generated = (dest / name).read_text(encoding="utf-8").splitlines(keepends=True)
        assert len(original) == len(generated), name
        for before, after in zip(original, generated):
            if before == after:
                continue
            if '"../../plasmoid/contents/ui' in before:
                assert after == before.replace('"../../plasmoid/contents/ui', '"../synced'), (name, before, after)
                continue
            match = re.match(r"^import (\S+)( as \w+)?(\r?\n)?$", before)
            assert match is not None and match.group(1) in tool.SYNC.IMPORTS, (name, before)
            assert allowed["import " + match.group(1)] + (match.group(2) or "") + (match.group(3) or "") == after
        text = (dest / name).read_text(encoding="utf-8")
        assert "plasmoid/contents" not in text, name
        assert _kde_names(text) == [], name
        for target in re.findall(r"\bimport\s+[\"']([^\"']*)", text):
            assert target == "../synced" or re.fullmatch(r"(\.\./synced/)?\w+\.js", target), (name, target)


def test_qml_test_paths_rewrite_only_the_plasmoid_ui_folder():
    tool = _tests_tool()
    assert tool.rewrite_line('import "../../plasmoid/contents/ui"\n', "../s") == 'import "../s"\n'
    assert tool.rewrite_line('import "../../plasmoid/contents/ui/A.js" as A\n', "../s") == 'import "../s/A.js" as A\n'
    assert tool.rewrite_line('    source: "../../plasmoid/contents/ui/R.qml"\n', "../s") == '    source: "../s/R.qml"\n'
    # Not the folder itself (a longer name), and not other folders.
    assert tool.rewrite_line('x: "../../plasmoid/contents/uix"\n', "../s") == 'x: "../../plasmoid/contents/uix"\n'
    assert tool.rewrite_line('x: "../../plasmoid/contents/images/a.svg"\n', "../s") == 'x: "../../plasmoid/contents/images/a.svg"\n'
    with pytest.raises(tool.SyncError):
        tool.rewrite_qml('import org.kde.plasma.private.x\n', "../s")
    # The tests' own .js files by bare name; nothing else.
    assert tool.rewrite_line('import "Golden.js" as Golden\n', "../s", {"Golden.js"}) == 'import "Golden.js" as Golden\n'
    for bad in ('import "Golden.js" as Golden\n',                                # not one of the tests' files
                'import "../../plasmoid/contents/ui/sub/A.js" as A\n',            # below the ui folder
                'import "../../plasmoid/contents/images" as I\n',                 # another plasmoid folder
                'import "../../plasmoid/contents/uix/A.js" as A\n',
                'import "/usr/share/plasma/plasmoids/x/contents/ui"\n',
                '    import "../../plasmoid/contents/ui"\n',
                'import QtQuick; import "../../plasmoid/contents/ui"\n',
                '    import org.kde.kirigami as Kirigami\n'):
        with pytest.raises(tool.SyncError):
            tool.rewrite_line(bad, "../s")


def test_qml_tests_dest_inside_the_tests_folder_is_refused(tmp_path):
    tool = _tests_tool()
    with pytest.raises(tool.SyncError):
        tool.sync(TESTS_QML, TESTS_QML / "out", tmp_path)
    assert not (TESTS_QML / "out").exists()
    assert tool.main(["--source", str(tmp_path / "none"), "--dest", str(tmp_path / "o"), "--synced", str(tmp_path)]) == 1
