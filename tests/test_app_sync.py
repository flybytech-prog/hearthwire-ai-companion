"""app/tools/sync_plasmoid.py: the app's copy of the plasmoid QML differs only in allowlisted import lines.

Every generated file must equal its source except import lines of the KDE
modules in IMPORTS, which point at Hearthwire.Compat.* with the alias kept.
The .js files (the protected ones too) and main.xml must be byte-identical,
except ui/Host.js (exactly PLASMA_HOST in, exactly APP_HOST out), and no
generated file may still import an org.kde module. ui/LinkOut.js (task 013)
is synced unchanged and only as the exact reviewed bytes; check_no_opener.py
allows that one file, there, and nothing else. app/src starts Qt WebEngine
only through WebEngineEnv.h and never sets a QTWEBENGINE variable.
"""

import hashlib
import importlib.util
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLASMOID = ROOT / "plasmoid"
UI = PLASMOID / "contents" / "ui"
TOOL = ROOT / "app" / "tools" / "sync_plasmoid.py"
PROTECTED = ("ProviderCatalog.js", "RefreshGate.js", "SnapshotLogic.js")


def _load(name, path):
    # No __pycache__ next to the tool in the repo.
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


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
        if name == "Host.js":
            continue
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


def _tmp_plasmoid(tmp_path, host, link_out=True):
    """A minimal plasmoid folder; host: the bytes of ui/Host.js (None: no Host.js);
    link_out: the bytes of ui/LinkOut.js (True: the reviewed ones, None: none)."""
    if link_out is True:
        link_out = _tool().PLASMA_LINK_OUT
    source = tmp_path / "plasmoid"
    (source / "contents" / "ui").mkdir(parents=True)
    (source / "contents" / "config").mkdir()
    (source / "contents" / "config" / "config.qml").write_text("import QtQuick\n")
    (source / "contents" / "config" / "main.xml").write_text("<kcfg/>\n")
    (source / "contents" / "ui" / "Page.qml").write_text('import QtQuick\nimport "Host.js" as Host\nItem {}\n')
    if host is not None:
        (source / "contents" / "ui" / "Host.js").write_bytes(host)
    if link_out is not None:
        (source / "contents" / "ui" / "LinkOut.js").write_bytes(link_out)
    return source


def test_a_bad_js_file_stops_the_whole_sync(tmp_path):
    tool = _tool()
    source = _tmp_plasmoid(tmp_path, tool.PLASMA_HOST)
    (source / "contents" / "ui" / "A.js").write_text(".import org.kde.kirigami 2.0 as K\n")
    with pytest.raises(tool.SyncError):
        tool.sync(source, tmp_path / "out")
    assert tool.main(["--source", str(source), "--dest", str(tmp_path / "out2")]) == 1


# Task 012 R4 P2a: ui/Host.js is the one .js file the app gets changed, from
# exactly PLASMA_HOST to exactly APP_HOST.
HOST_TEXT = (
    ".pragma library\n"
    "// Which front end runs these files: false in the Plasma widget. The\n"
    "// hearthwire-hyprland app's build (app/tools/sync_plasmoid.py) writes this\n"
    "// file with \"var isApp = true\" instead; nothing else may change here.\n"
    "var isApp = %s\n"
)


def test_host_js_constants_are_the_plan_bytes():
    tool = _tool()
    assert tool.PLASMA_HOST == (HOST_TEXT % "false").encode()
    assert tool.APP_HOST == (HOST_TEXT % "true").encode()


def test_host_js_source_is_plasma_and_the_copy_is_app(synced):
    tool, dest, names = synced
    assert "Host.js" in names
    assert (UI / "Host.js").read_bytes() == tool.PLASMA_HOST
    assert (dest / "Host.js").read_bytes() == tool.APP_HOST


def test_host_js_is_the_only_js_file_that_changes(synced):
    tool, dest, names = synced
    sources = _sources(tool)
    changed = [name for name in names if name.endswith(".js")
               and (dest / name).read_bytes() != sources[name].read_bytes()]
    assert changed == ["Host.js"]


def test_a_good_tmp_plasmoid_syncs_host_js(tmp_path):
    tool = _tool()
    source = _tmp_plasmoid(tmp_path, tool.PLASMA_HOST)
    names = tool.sync(source, tmp_path / "out")
    assert "Host.js" in names
    assert (tmp_path / "out" / "Host.js").read_bytes() == tool.APP_HOST


@pytest.mark.parametrize("host", [
    None,                                                       # no Host.js
    (HOST_TEXT % "false").encode() + b"var x = 1\n",            # an extra line
    (HOST_TEXT % "true").encode(),                              # the value changed
    (HOST_TEXT % "false").encode()[:-1],                        # no last newline
    (HOST_TEXT % "false").replace("\n", "\r\n").encode(),       # CRLF
    (HOST_TEXT % "false").encode() + b"\n",                     # a trailing empty line
    b"\xef\xbb\xbf" + (HOST_TEXT % "false").encode(),           # a BOM
    (HOST_TEXT % "false").replace("// file", "//  file").encode(),  # a comment changed
    (HOST_TEXT % "1").encode(),
    b"",
])
def test_any_other_host_js_stops_the_sync(tmp_path, host):
    tool = _tool()
    source = _tmp_plasmoid(tmp_path, host)
    with pytest.raises(tool.SyncError):
        tool.sync(source, tmp_path / "out")
    # Nothing was written, and the command line says so without a traceback.
    assert not (tmp_path / "out").exists()
    assert tool.main(["--source", str(source), "--dest", str(tmp_path / "out2")]) == 1
    assert not (tmp_path / "out2").exists()


def test_a_host_js_symlink_stops_the_sync(tmp_path):
    tool = _tool()
    source = _tmp_plasmoid(tmp_path, None)
    real = tmp_path / "real.js"
    real.write_bytes(tool.PLASMA_HOST)
    (source / "contents" / "ui" / "Host.js").symlink_to(real)
    with pytest.raises(tool.SyncError):
        tool.sync(source, tmp_path / "out")


def test_host_js_can_not_be_left_out(tmp_path):
    tool = _tool()
    source = _tmp_plasmoid(tmp_path, tool.PLASMA_HOST)
    with pytest.raises(tool.SyncError):
        tool.sync(source, tmp_path / "out", exclude={"Host.js"})
    assert not (tmp_path / "out").exists()


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
    names = tool.sync(TESTS_QML, dest, synced)
    expected = sorted(p.name for p in TESTS_QML.iterdir() if p.suffix in (".qml", ".js"))
    assert "tst_chat_web_view.qml" in names
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


# Task 013 (user decision Q1 = B): ui/LinkOut.js, the one chat-link opener,
# is synced unchanged but only as the reviewed bytes, and check_no_opener.py
# allows exactly that file in the synced folder.
NO_OPENER = ROOT / "app" / "tests" / "check_no_opener.py"
CHECK_SYNCED = ROOT / "app" / "tests" / "check_synced.py"
APP = ROOT / "app"


def _no_opener():
    return _load("check_no_opener", NO_OPENER)


def _check_synced():
    return _load("check_synced", CHECK_SYNCED)


def test_link_out_pins_agree_and_match_the_plasmoid_file():
    tool = _tool()
    digest = hashlib.sha256(tool.PLASMA_LINK_OUT).hexdigest()
    assert digest == _no_opener().LINK_OUT_SHA256
    assert digest == _check_synced().LINK_OUT_SHA256
    assert (UI / "LinkOut.js").read_bytes() == tool.PLASMA_LINK_OUT
    # Its one way out: Qt.openUrlExternally, once, in open().
    text = tool.PLASMA_LINK_OUT.decode("utf-8")
    assert text.count("openUrlExternally") == 1
    assert "function open(url) { Qt.openUrlExternally(url) }\n" in text
    assert text.startswith(".pragma library\n")


def test_link_out_is_synced_unchanged(synced):
    tool, dest, names = synced
    assert "LinkOut.js" in names and "ChatWebView.qml" in names
    assert (dest / "LinkOut.js").read_bytes() == tool.PLASMA_LINK_OUT == (UI / "LinkOut.js").read_bytes()


def test_a_good_tmp_plasmoid_syncs_link_out(tmp_path):
    tool = _tool()
    names = tool.sync(_tmp_plasmoid(tmp_path, tool.PLASMA_HOST), tmp_path / "out")
    assert "LinkOut.js" in names
    assert (tmp_path / "out" / "LinkOut.js").read_bytes() == tool.PLASMA_LINK_OUT


def _link_out_variants():
    reviewed = _tool().PLASMA_LINK_OUT
    return [
        None,                                                              # no LinkOut.js
        b"",
        reviewed + b"function again(u) { Qt.openUrlExternally(u) }\n",    # a second opener
        reviewed + b"\n",                                                  # a trailing empty line
        reviewed[:-1],                                                     # no last newline
        reviewed.replace(b"\n", b"\r\n"),                                  # CRLF
        b"\xef\xbb\xbf" + reviewed,                                        # a BOM
        reviewed.replace(b"Qt.openUrlExternally(url)", b""),               # opens nothing
        reviewed.replace(b"(url)", b"(\"https://example.org/\")"),         # a fixed address
        reviewed.replace(b"// Where", b"//  Where"),                       # a comment changed
    ]


@pytest.mark.parametrize("index", range(len(_link_out_variants())))
def test_any_other_link_out_stops_the_sync(tmp_path, index):
    tool = _tool()
    source = _tmp_plasmoid(tmp_path, tool.PLASMA_HOST, _link_out_variants()[index])
    with pytest.raises(tool.SyncError):
        tool.sync(source, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert tool.main(["--source", str(source), "--dest", str(tmp_path / "out2")]) == 1
    assert not (tmp_path / "out2").exists()


def test_a_link_out_symlink_stops_the_sync(tmp_path):
    tool = _tool()
    source = _tmp_plasmoid(tmp_path, tool.PLASMA_HOST, None)
    real = tmp_path / "real.js"
    real.write_bytes(tool.PLASMA_LINK_OUT)
    (source / "contents" / "ui" / "LinkOut.js").symlink_to(real)
    with pytest.raises(tool.SyncError):
        tool.sync(source, tmp_path / "out")


def test_link_out_can_not_be_left_out(tmp_path):
    tool = _tool()
    with pytest.raises(tool.SyncError):
        tool.sync(_tmp_plasmoid(tmp_path, tool.PLASMA_HOST), tmp_path / "out", exclude={"LinkOut.js"})
    assert not (tmp_path / "out").exists()


def _app_folders():
    return [str(APP / "src"), str(APP / "qml")]


def test_check_no_opener_passes_the_app_and_the_synced_tree(synced):
    tool, dest, names = synced
    check = _no_opener()
    assert check.scan(_app_folders(), str(dest)) == []
    assert check.main(["check"] + _app_folders() + ["--synced", str(dest)]) == 0


def test_check_no_opener_needs_the_synced_folder_named(synced):
    # Mutation proof: the same tree with the folder given plainly (no
    # exception) is caught, at LinkOut.js only.
    tool, dest, names = synced
    found = _no_opener().scan(_app_folders() + [str(dest)])
    assert any("LinkOut.js:" in line and "openUrl" in line for line in found)
    # F1: the way to LinkOut (names, openHttps, acceptExternal, externalUrl =)
    # is caught outside the exception too, in the two files that hold it.
    gate = [line for line in found if "only the synced ChatWebView.qml" in line]
    assert gate and all("ChatWebView.qml:" in line or "ChatView.qml:" in line for line in gate)
    assert any("ChatWebView.qml:" in line for line in gate)
    assert all("LinkOut.js:" in line or "ChatWebView.qml:" in line or "ChatView.qml:" in line for line in found)


def test_check_no_opener_catches_a_caller_of_link_out_in_the_app(tmp_path):
    # The auditor's repro (L2): an app QML that imports LinkOut.js and calls
    # openHttps/acceptExternal and assigns externalUrl, outside the exception.
    check = _no_opener()
    qml = tmp_path / "qml"
    qml.mkdir()
    (qml / "Evil.qml").write_text(
        'import QtQuick\nimport "qrc:/qt/qml/Hearthwire/Plasmoid/LinkOut.js" as Out\n'
        'Item { Component.onCompleted: Out.open("http://127.0.0.1:9/x") ; function f(w) { '
        'w.externalUrl = "https://x.example/"; w.acceptExternal(); w.openHttps("https://y.example/") } }\n',
        encoding="utf-8")
    found = check.scan([str(qml)])
    assert any("Evil.qml:2" in line for line in found) and any("Evil.qml:3" in line for line in found)
    # Each word on its own is caught too (one finding per line, so one file each).
    for number, text in enumerate(("w.acceptExternal()", "w.openHttps(u)", "w.externalUrl = u", "Out.open(u) // LinkOut")):
        (qml / ("One%d.qml" % number)).write_text("Item { function f(w) { %s } }\n" % text, encoding="utf-8")
        assert check.scan([str(qml)]) and any("One%d.qml:1" % number in line for line in check.scan([str(qml)])), text
    # Not in a folder named --synced either: only the exact synced names are exempt.
    assert check.scan([], str(qml))
    # The exact names, directly in --synced, are fine for the gate words.
    synced = tmp_path / "synced"
    synced.mkdir()
    (synced / "ChatWebView.qml").write_text('import "LinkOut.js" as LinkOut\nItem { property string externalUrl: "" }\n',
                                            encoding="utf-8")
    assert check.scan([], str(synced)) == []


def _copy(dest, tmp_path):
    copy = tmp_path / "synced"
    shutil.copytree(dest, copy)
    return copy


@pytest.mark.parametrize("change", [
    ("ChatWebView.qml", lambda data: data + b"// Qt.openUrlExternally(url)\n"),        # another file opens
    ("ChatView.qml", lambda data: data.replace(b"import QtQuick\n", b"import QtQuick\n// openUrl\n", 1)),
    ("LinkOut.js", lambda data: data + b"// reviewed?\n"),                            # LinkOut.js changed
    ("LinkOut.js", lambda data: data.replace(b"Qt.openUrlExternally(url)", b"")),     # ... to open nothing
    ("LinkOut.js", lambda data: data.replace(b"Qt.openUrlExternally", b"Qt[\"openUrlExternally\"]")),
])
def test_check_no_opener_catches_every_other_opener(synced, tmp_path, change):
    tool, dest, names = synced
    copy = _copy(dest, tmp_path)
    name, edit = change
    (copy / name).write_bytes(edit((copy / name).read_bytes()))
    found = _no_opener().scan(_app_folders(), str(copy))
    assert found and all(name + ":" in line for line in found), found
    assert _no_opener().main(["check"] + _app_folders() + ["--synced", str(copy)]) == 1


def test_check_no_opener_allows_link_out_nowhere_else(synced, tmp_path):
    tool, dest, names = synced
    check = _no_opener()
    copy = _copy(dest, tmp_path)
    # The reviewed bytes under another name, or one folder down.
    (copy / "Opener.js").write_bytes(tool.PLASMA_LINK_OUT)
    (copy / "sub").mkdir()
    (copy / "sub" / "LinkOut.js").write_bytes(tool.PLASMA_LINK_OUT)
    found = check.scan([], str(copy))
    assert len(found) == 2 and any("Opener.js:" in line for line in found) and any("sub/LinkOut.js:" in line for line in found)
    # In the app's own folders it is not allowed either.
    app_copy = tmp_path / "qml"
    app_copy.mkdir()
    (app_copy / "LinkOut.js").write_bytes(tool.PLASMA_LINK_OUT)
    assert check.scan([str(app_copy)], str(dest)) != []


def test_check_no_opener_self_test_passes():
    assert _no_opener().main(["check", "--self-test"]) == 0


def test_check_synced_wants_the_reviewed_link_out(synced, tmp_path):
    tool, dest, names = synced
    check = _check_synced()
    assert check.link_out_problems(dest) == []
    copy = _copy(dest, tmp_path)
    (copy / "LinkOut.js").write_bytes(tool.PLASMA_LINK_OUT + b"\n")
    assert check.link_out_problems(copy) == ["LinkOut.js: not the reviewed bytes"]
    (copy / "LinkOut.js").unlink()
    assert check.link_out_problems(copy) == ["LinkOut.js: missing"]


# Task 013: Qt WebEngine starts only through WebEngineEnv.h's
# hwStartWebEngine() (environment dropped, then initialize), after the argv
# refusal and before QGuiApplication; nothing in app/ turns the sandbox off.
def _code_lines(path):
    """The lines of a C++/CMake file without whole-line comments."""
    return [line for line in path.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith(("//", "#"))]


def test_main_starts_webengine_after_the_refusals_and_before_the_app():
    text = (APP / "src" / "main.cpp").read_text(encoding="utf-8")
    code = "\n".join(_code_lines(APP / "src" / "main.cpp"))
    assert "QtWebEngineQuick::initialize" not in code
    assert code.count("hwStartWebEngine()") == 1
    refusal = code.index("hwRefusedChromiumArgument(argc, argv)")
    plugin_refusal = code.index("hwRefusedArgument(argc, argv)")
    start = code.index("hwStartWebEngine();")
    application = code.index("QGuiApplication app(argc, argv);")
    assert plugin_refusal < refusal < start < application
    assert "#include \"WebEngineEnv.h\"" in text


def test_webengine_env_drops_before_initialize():
    header = (APP / "src" / "WebEngineEnv.h").read_text(encoding="utf-8")
    body = header[header.index("inline void hwStartWebEngine("):]
    assert body.index("hwDropWebEngineEnvironment(unset)") < body.index("initialize();")
    # Fail closed: a drop that left names (-1) ends the app before initialize.
    assert body.index("< 0") < body.index("std::_Exit(2)") < body.index("initialize();")
    assert 'constexpr std::string_view prefix("QTWEBENGINE");' in header


def test_webengine_env_lists():
    header = (APP / "src" / "WebEngineEnv.h").read_text(encoding="utf-8")
    # Dropped by exact name besides QTWEBENGINE* (F1: M1 and L3).
    for name in ("SSLKEYLOGFILE", "CHROME_DEVEL_SANDBOX", "CHROME_SANDBOX_DEBUGGING", "CHROME_LOG_FILE",
                 "GOOGLE_API_KEY", "GOOGLE_DEFAULT_CLIENT_ID", "GOOGLE_DEFAULT_CLIENT_SECRET"):
        assert '"%s",' % name in header, name
    # Proxy variables are the user's real setting: never dropped.
    assert '"http_proxy"' not in header.lower() and '"https_proxy"' not in header.lower()
    # The one QTWEBENGINE name that passes (user decision I3), by exact name.
    assert 'hwWebEngineKept = "QTWEBENGINE_ENABLE_LINUX_ACCESSIBILITY";' in header
    assert header.count("QTWEBENGINE_ENABLE_LINUX_ACCESSIBILITY\"") == 1
    for switch in ("ssl-key-log-file", "log-net-log", "net-log-capture-mode", "enable-features", "disable-features",
                   "unsafely-treat-insecure-origin-as-secure", "allow-file-access-from-files",
                   "allow-insecure-localhost"):
        assert '"%s",' % switch in header, switch


def test_only_webengine_env_initializes_webengine():
    for path in sorted((APP / "src").rglob("*")):
        if path.is_file() and path.name != "WebEngineEnv.h":
            assert "QtWebEngineQuick::initialize" not in "\n".join(_code_lines(path)), path
    qmltests = "\n".join(_code_lines(APP / "tests" / "qmltests.cpp"))
    assert "QtWebEngineQuick::initialize" not in qmltests
    assert qmltests.index("hwStartWebEngine();") < qmltests.index("quick_test_main_with_setup(")


SETS_WEBENGINE = re.compile(r"\b(?:qputenv|setenv|putenv|insert)\s*\(\s*(?:QByteArrayLiteral\(|QStringLiteral\(|u)?\"QTWEBENGINE")
CHROMIUM_SWITCH_LITERAL = re.compile(r"[\"']--?(?:no-sandbox|single-process|disable-[a-z-]*sandbox|remote-debugging|disable-web-security"
                                     r"|in-process-gpu|no-zygote|webEngineArgs)")


def test_app_never_sets_a_webengine_variable_or_switch():
    for root in (APP / "src", APP / "qml"):
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            assert not SETS_WEBENGINE.search(text), path
            assert not CHROMIUM_SWITCH_LITERAL.search(text), path
            assert "appendChromium" not in text and "QTWEBENGINE_CHROMIUM_FLAGS=" not in text, path
            for line in _code_lines(path):
                assert "QTWEBENGINE_DISABLE_SANDBOX" not in line, (path, line)
    # The build and the tests' environment never switch the sandbox off.
    for path in (APP / "CMakeLists.txt", APP / "tests" / "CMakeLists.txt"):
        assert "QTWEBENGINE_DISABLE_SANDBOX" not in path.read_text(encoding="utf-8"), path


@pytest.mark.parametrize("line", [
    'qputenv("QTWEBENGINE_DISABLE_SANDBOX", "1");',
    'setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox", 1);',
    'environment.insert(QStringLiteral("QTWEBENGINE_REMOTE_DEBUGGING"), x);',
    'args << QStringLiteral("--no-sandbox");',
    'char flag[] = "--single-process";',
    'argv.push_back("--webEngineArgs");',
])
def test_the_webengine_patterns_catch_the_usual_forms(line):
    # Mutation proof for the scan above.
    assert SETS_WEBENGINE.search(line) or CHROMIUM_SWITCH_LITERAL.search(line)
