"""Chat profile folders (core/webdata.py) and the --web-data CLI."""

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from hearthwire import cli
from hearthwire.core import vault, webdata


@pytest.fixture
def data(tmp_path, monkeypatch):
    base = tmp_path / "data"
    monkeypatch.setenv("XDG_DATA_HOME", str(base))
    # No tool may run: --web-data never needs one.
    empty = tmp_path / "no-tools"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    return base


def web_reply(argv, capsys):
    assert cli.main(["--web-data", *argv]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    return json.loads(captured.out)


def prepare(capsys, applet=1, generation=0, store="encrypted"):
    return web_reply(["prepare", "--store", store, "--applet", str(applet), "--generation", str(generation)], capsys)


def remove(capsys, applet=1, keep=None, store="encrypted"):
    argv = ["remove", "--store", store, "--applet", str(applet)]
    if keep is not None:
        argv += ["--keep", str(keep)]
    return web_reply(argv, capsys)


def mode(path):
    return stat.S_IMODE(os.lstat(path).st_mode)


def _fake_mount(monkeypatch, info, cipher, mountpoint):
    mountpoint.mkdir(parents=True, mode=0o700, exist_ok=True)
    info.write_text(
        f"901 30 0:99 / {mountpoint} rw,nosuid,nodev shared:1 - fuse.gocryptfs {cipher} "
        f"rw,user_id={os.getuid()},group_id={os.getgid()}\n"
    )
    monkeypatch.setattr(vault, "MOUNTINFO", str(info))
    # The fake mountpoint is a plain directory, so its device equals its parent's.
    monkeypatch.setattr(vault, "_same_device", lambda root_info, parent_info: False)


@pytest.fixture
def mounted(data, tmp_path, monkeypatch, _private_runtime_dir):
    """Fake a verified gocryptfs mount at $XDG_RUNTIME_DIR/hearthwire/vault."""
    cipher = Path(os.path.realpath(data)) / "hearthwire" / "vault"
    cipher.mkdir(parents=True, mode=0o700)
    mountpoint = Path(os.path.realpath(_private_runtime_dir)) / "hearthwire" / "vault"
    _fake_mount(monkeypatch, tmp_path / "mountinfo", cipher, mountpoint)
    return mountpoint


def no_plaintext_store(data):
    """Nothing may ever create $XDG_DATA_HOME/hearthwire/web."""
    return not (data / "hearthwire" / "web").exists()


# --- the unencrypted "folder" store is gone ---------------------------------------------------


def test_only_the_encrypted_store_exists():
    assert webdata.STORES == ("encrypted",)
    for name in ("_prepare_folder", "_remove_folder"):
        assert not hasattr(webdata, name)
    code = Path(webdata.__file__).read_text(encoding="utf-8")
    assert '"folder"' not in code


@pytest.mark.parametrize("operation", ["prepare", "remove"])
def test_store_folder_is_rejected_by_argparse(data, capsys, operation):
    argv = ["--web-data", operation, "--store", "folder", "--applet", "1"]
    if operation == "prepare":
        argv += ["--generation", "0"]
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid choice: 'folder'" in captured.err
    assert not data.exists()


@pytest.mark.parametrize("call", ["prepare", "remove"])
def test_library_refuses_any_other_store(data, call):
    with pytest.raises(ValueError):
        if call == "prepare":
            webdata.prepare("folder", 1, 0)
        else:
            webdata.remove("folder", 1)
    assert not data.exists()


# --- prepare --------------------------------------------------------------------------------


def test_prepare_creates_private_folders_inside_the_mount_and_prints_only_ok(data, capsys, mounted):
    assert cli.main(["--web-data", "prepare", "--store", "encrypted", "--applet", "1", "--generation", "0"]) == 0
    captured = capsys.readouterr()
    assert captured.out == '{"ok":true}\n'
    assert captured.err == ""
    for path in (mounted / "web", mounted / "web" / "applet-1-g0"):
        assert path.is_dir() and not path.is_symlink()
        assert mode(path) == 0o700
    assert no_plaintext_store(data)


def test_prepare_resets_loose_modes_and_is_idempotent(data, capsys, mounted):
    profile = mounted / "web" / "applet-7-g3"
    profile.mkdir(parents=True)
    for path in (profile.parent, profile):
        path.chmod(0o755)
    assert prepare(capsys, 7, 3) == {"ok": True}
    assert prepare(capsys, 7, 3) == {"ok": True}
    assert {mode(path) for path in (profile.parent, profile)} == {0o700}


def test_relative_xdg_data_home_falls_back_to_home(tmp_path, monkeypatch, capsys, _private_runtime_dir):
    monkeypatch.setenv("XDG_DATA_HOME", "relative/data")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    cipher = Path(os.path.realpath(tmp_path)) / "home" / ".local" / "share" / "hearthwire" / "vault"
    mountpoint = Path(os.path.realpath(_private_runtime_dir)) / "hearthwire" / "vault"
    _fake_mount(monkeypatch, tmp_path / "mountinfo", cipher, mountpoint)
    assert prepare(capsys) == {"ok": True}
    assert (mountpoint / "web" / "applet-1-g0").is_dir()
    assert not Path("relative").exists()
    assert not (tmp_path / "home" / ".local" / "share" / "hearthwire" / "web").exists()


@pytest.mark.parametrize("component", ["web", "profile"])
def test_prepare_refuses_symlinked_components(data, capsys, tmp_path, mounted, component):
    target = tmp_path / "target"
    target.mkdir()
    target.chmod(0o755)
    parents = {"web": mounted, "profile": mounted / "web"}
    names = {"web": "web", "profile": "applet-1-g0"}
    parents[component].mkdir(parents=True, exist_ok=True)
    (parents[component] / names[component]).symlink_to(target)
    assert prepare(capsys) == {"ok": False, "error": "symlink"}
    assert list(target.iterdir()) == []
    assert mode(target) == 0o755


def test_prepare_refuses_a_file_in_the_way(data, capsys, mounted):
    (mounted / "web").write_text("")
    assert prepare(capsys) == {"ok": False, "error": "not-directory"}


def test_prepare_reports_os_errors_without_paths(data, capsys, mounted):
    mounted.chmod(0o500)
    try:
        if os.access(mounted, os.W_OK):
            pytest.skip("running with privileges that ignore modes")
        out = prepare(capsys)
    finally:
        mounted.chmod(0o700)
    assert out == {"ok": False, "error": "os-error"}
    assert not (mounted / "web").exists()


# --- remove ---------------------------------------------------------------------------------


def make_profiles(mountpoint, names):
    web = mountpoint / "web"
    web.mkdir(parents=True, exist_ok=True)
    for name in names:
        (web / name).mkdir()
        (web / name / "Cookies").write_text("x")
    return web


def test_remove_deletes_only_this_applets_other_generations(data, capsys, mounted):
    web = make_profiles(mounted, [
        "applet-1-g0", "applet-1-g1", "applet-1-g12", "applet-12-g0", "applet-2-g1",
        "applet-1-g01", "xapplet-1-g0", "applet-1-g0.bak",
    ])
    (web / "notes.txt").write_text("keep")
    assert remove(capsys, 1, keep=1) == {"ok": True}
    assert sorted(path.name for path in web.iterdir()) == sorted([
        "applet-1-g01", "applet-1-g0.bak", "applet-1-g1", "applet-12-g0", "applet-2-g1",
        "notes.txt", "xapplet-1-g0",
    ])


def test_remove_without_keep_deletes_every_generation(data, capsys, mounted):
    web = make_profiles(mounted, ["applet-4-g0", "applet-4-g9", "applet-5-g0"])
    assert remove(capsys, 4) == {"ok": True}
    assert [path.name for path in web.iterdir()] == ["applet-5-g0"]


def test_remove_of_missing_folders_is_ok(data, capsys, mounted):
    assert remove(capsys, 1) == {"ok": True}
    assert remove(capsys, 1, keep=0) == {"ok": True}
    assert not (mounted / "web").exists()
    assert no_plaintext_store(data)


def test_remove_never_follows_links(data, capsys, tmp_path, mounted):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious").write_text("keep")
    web = make_profiles(mounted, ["applet-1-g0"])
    (web / "applet-1-g0" / "link").symlink_to(outside)
    (web / "applet-1-g2").symlink_to(outside)
    assert remove(capsys, 1) == {"ok": True}
    assert (outside / "precious").read_text() == "keep"
    assert sorted(path.name for path in web.iterdir()) == []


def test_remove_refuses_a_symlinked_web_folder(data, capsys, tmp_path, mounted):
    outside = tmp_path / "outside"
    (outside / "applet-1-g0").mkdir(parents=True)
    (mounted / "web").symlink_to(outside)
    assert remove(capsys, 1) == {"ok": False, "error": "symlink"}
    assert (outside / "applet-1-g0").is_dir()


def test_remove_requires_symlink_safe_rmtree(data, capsys, mounted, monkeypatch):
    web = make_profiles(mounted, ["applet-1-g0"])
    monkeypatch.setattr(shutil.rmtree, "avoids_symlink_attacks", False)
    assert remove(capsys, 1) == {"ok": False, "error": "os-error"}
    assert (web / "applet-1-g0").is_dir()


def test_remove_uses_rmtree_relative_to_a_directory_fd(data, capsys, mounted, monkeypatch):
    make_profiles(mounted, ["applet-1-g0"])
    calls = []
    real = shutil.rmtree

    def spy(path, *args, **kwargs):
        calls.append((path, kwargs.get("dir_fd")))
        return real(path, *args, **kwargs)

    spy.avoids_symlink_attacks = True
    monkeypatch.setattr(shutil, "rmtree", spy)
    assert remove(capsys, 1) == {"ok": True}
    assert calls and all(name == "applet-1-g0" and isinstance(fd, int) for name, fd in calls)


# --- mount verification ---------------------------------------------------------------------


def test_encrypted_store_needs_a_verified_mount(data, capsys, tmp_path, monkeypatch):
    info = tmp_path / "mountinfo"
    info.write_text("")
    monkeypatch.setattr(vault, "MOUNTINFO", str(info))
    assert prepare(capsys) == {"ok": False, "error": "not-verified"}
    assert remove(capsys) == {"ok": False, "error": "not-verified"}
    assert not data.exists()


def test_encrypted_store_without_runtime_dir(data, capsys, monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    assert prepare(capsys) == {"ok": False, "error": "no-runtime-dir"}
    assert not data.exists()


def test_encrypted_prepare_and_remove_inside_the_mount(data, capsys, mounted):
    assert prepare(capsys, 2, 0) == {"ok": True}
    assert prepare(capsys, 2, 1) == {"ok": True}
    assert mode(mounted / "web") == mode(mounted / "web" / "applet-2-g1") == 0o700
    assert no_plaintext_store(data)
    assert remove(capsys, 2, keep=1) == {"ok": True}
    assert [path.name for path in (mounted / "web").iterdir()] == ["applet-2-g1"]
    assert remove(capsys, 2) == {"ok": True}
    assert list((mounted / "web").iterdir()) == []


def test_encrypted_store_runs_no_tool(data, capsys, mounted, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("no child may run"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("no child may run"))
    assert prepare(capsys) == {"ok": True}


# --- purge (install.sh --uninstall-web-data) -------------------------------------------------


@pytest.fixture
def no_mounts(tmp_path, monkeypatch, _private_runtime_dir):
    info = tmp_path / "mountinfo"
    info.write_text("25 1 0:22 / /run rw - tmpfs tmpfs rw\n")
    monkeypatch.setattr(vault, "MOUNTINFO", str(info))
    # Never look at the real /run/user/<uid>.
    monkeypatch.setattr(vault, "DEFAULT_RUNTIME", str(tmp_path / "no-such-runtime-{uid}"))
    return info


def purge(capsys):
    return web_reply(["purge"], capsys)


def make_cipher(data):
    cipher = data / "hearthwire" / "vault"
    cipher.mkdir(parents=True, exist_ok=True)
    (cipher / "gocryptfs.conf").write_text("{}")
    (cipher / "abcdef").write_text("ciphertext")
    return cipher


def test_purge_deletes_the_vault_and_names_only_categories(data, capsys, no_mounts):
    make_cipher(data)
    assert cli.main(["--web-data", "purge"]) == 0
    captured = capsys.readouterr()
    assert captured.out == '{"ok":true,"removed":["vault"]}\n'
    assert captured.err == ""
    assert not (data / "hearthwire").exists()
    assert data.is_dir()


def test_purge_keeps_other_files_in_the_app_folder(data, capsys, no_mounts):
    make_cipher(data)
    (data / "hearthwire" / "other").write_text("keep")
    assert purge(capsys) == {"ok": True, "removed": ["vault"]}
    assert (data / "hearthwire" / "other").read_text() == "keep"


def test_purge_of_nothing_is_ok(data, capsys, no_mounts):
    assert purge(capsys) == {"ok": True, "removed": []}
    assert not data.exists()
    data.mkdir()
    (data / "hearthwire").mkdir()
    assert purge(capsys) == {"ok": True, "removed": []}
    assert not (data / "hearthwire").exists()


@pytest.mark.parametrize("mounted_at", ["mountpoint", "source", "stale"])
def test_purge_refuses_while_the_vault_is_mounted(data, capsys, no_mounts, _private_runtime_dir, mounted_at):
    cipher = make_cipher(data)
    mountpoint = Path(os.path.realpath(_private_runtime_dir)) / "hearthwire" / "vault"
    if mounted_at == "mountpoint":
        line = f"901 30 0:99 / {mountpoint} rw - fuse.other other rw\n"
    elif mounted_at == "source":
        line = f"901 30 0:99 / /somewhere/else rw - fuse.gocryptfs {os.path.realpath(cipher)} rw\n"
    else:
        mountpoint.mkdir(parents=True)
        line = f"901 30 0:99 / {mountpoint} rw - fuse.gocryptfs {cipher} rw,user_id={os.getuid()}\n"
    no_mounts.write_text(no_mounts.read_text() + line)
    assert purge(capsys) == {"ok": False, "error": "not-locked"}
    assert (cipher / "gocryptfs.conf").exists()
    assert (cipher / "abcdef").exists()


def test_purge_checks_the_default_runtime_when_the_variable_is_unset(
    data, capsys, no_mounts, tmp_path, monkeypatch
):
    make_cipher(data)
    runtime = tmp_path / "default-runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setattr(vault, "DEFAULT_RUNTIME", str(runtime))
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    mountpoint = runtime / "hearthwire" / "vault"
    no_mounts.write_text(f"901 30 0:99 / {mountpoint} rw - fuse.gocryptfs elsewhere rw\n")
    assert purge(capsys) == {"ok": False, "error": "not-locked"}
    assert (data / "hearthwire" / "vault").is_dir()
    no_mounts.write_text("")
    assert purge(capsys) == {"ok": True, "removed": ["vault"]}


def test_purge_without_any_runtime_dir_still_checks_the_source(data, capsys, no_mounts, monkeypatch):
    cipher = make_cipher(data)
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    no_mounts.write_text(f"901 30 0:99 / /mnt/x rw - fuse.gocryptfs {cipher} rw\n")
    assert purge(capsys) == {"ok": False, "error": "not-locked"}
    no_mounts.write_text("")
    assert purge(capsys) == {"ok": True, "removed": ["vault"]}


def test_purge_refuses_when_mountinfo_is_unreadable(data, capsys, no_mounts, tmp_path, monkeypatch):
    make_cipher(data)
    monkeypatch.setattr(vault, "MOUNTINFO", str(tmp_path / "missing"))
    assert purge(capsys) == {"ok": False, "error": "os-error"}
    assert (data / "hearthwire" / "vault" / "gocryptfs.conf").exists()


@pytest.mark.parametrize("component", ["hearthwire", "vault"])
def test_purge_refuses_symlinks_and_deletes_nothing(data, capsys, no_mounts, tmp_path, component):
    target = tmp_path / "target"
    target.mkdir()
    (target / "precious").write_text("keep")
    data.mkdir()
    if component == "hearthwire":
        (data / "hearthwire").symlink_to(target)
    else:
        (data / "hearthwire").mkdir()
        (data / "hearthwire" / "other").write_text("keep")
        (data / "hearthwire" / component).symlink_to(target)
    assert purge(capsys) == {"ok": False, "error": "symlink"}
    assert (target / "precious").read_text() == "keep"
    if component == "hearthwire":
        assert (data / "hearthwire").is_symlink()
    else:
        assert (data / "hearthwire" / component).is_symlink()
        assert (data / "hearthwire" / "other").read_text() == "keep"


def test_purge_refuses_a_file_in_the_way(data, capsys, no_mounts):
    (data / "hearthwire").mkdir(parents=True)
    (data / "hearthwire" / "vault").write_text("not a folder")
    assert purge(capsys) == {"ok": False, "error": "not-directory"}
    assert (data / "hearthwire" / "vault").read_text() == "not a folder"


def test_purge_never_follows_links_inside_the_tree(data, capsys, no_mounts, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious").write_text("keep")
    cipher = make_cipher(data)
    (cipher / "link").symlink_to(outside)
    assert purge(capsys) == {"ok": True, "removed": ["vault"]}
    assert (outside / "precious").read_text() == "keep"


def test_purge_leaves_an_unknown_web_folder_alone(data, capsys, no_mounts):
    # There is no plaintext store any more, so purge has no business there.
    (data / "hearthwire" / "web").mkdir(parents=True)
    make_cipher(data)
    assert purge(capsys) == {"ok": True, "removed": ["vault"]}
    assert (data / "hearthwire" / "web").is_dir()


def test_purge_waits_for_the_vault_lock(data, capsys, no_mounts, monkeypatch):
    make_cipher(data)
    clock = iter([0.0, 0.0, vault.LOCK_TIMEOUT + 1])
    monkeypatch.setattr(vault, "_POLL_INTERVAL", 0.0)
    ctx = vault.context(find_tools=False)
    with vault.vault_lock(ctx):
        # purge opens the lock file again, so its flock contends with this one.
        monkeypatch.setattr(vault.time, "monotonic", lambda: next(clock))
        assert purge(capsys) == {"ok": False, "error": "busy"}
    assert (data / "hearthwire" / "vault").is_dir()


def test_purge_runs_no_tool(data, capsys, no_mounts, monkeypatch):
    make_cipher(data)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("no child may run"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("no child may run"))
    assert purge(capsys) == {"ok": True, "removed": ["vault"]}


def test_purge_requires_symlink_safe_rmtree(data, capsys, no_mounts, monkeypatch):
    make_cipher(data)
    monkeypatch.setattr(shutil.rmtree, "avoids_symlink_attacks", False, raising=False)
    assert purge(capsys) == {"ok": False, "error": "os-error"}
    assert (data / "hearthwire" / "vault").is_dir()


def test_purge_output_never_contains_a_path(data, capsys, no_mounts, tmp_path):
    make_cipher(data)
    texts = []
    for _ in range(2):
        cli.main(["--web-data", "purge"])
        captured = capsys.readouterr()
        texts.append(captured.out + captured.err)
    data.mkdir(exist_ok=True)
    (data / "hearthwire").symlink_to(tmp_path)
    cli.main(["--web-data", "purge"])
    captured = capsys.readouterr()
    texts.append(captured.out + captured.err)
    text = "".join(texts)
    assert str(tmp_path) not in text
    assert "/" not in text and "applet" not in text and "Cookies" not in text


INSTALL_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "install.sh"


# install.sh runs `python3 -P -m hearthwire`. This python3 is a shim that points the helper
# at a fake mountinfo and a fake default runtime dir before running it, so the script
# never reads the real /proc/self/mountinfo or /run/user/<uid> (the test must pass even
# while the user's real folder is unlocked). It refuses (exit 98) a call without -P, so
# the script cannot regress to importing modules from the working folder.
PYTHON_SHIM = """#!/bin/sh
exec {python} -P -c '
import os, runpy, sys
if sys.argv[1:4] != ["-P", "-m", "hearthwire"]:
    sys.exit(98)
from hearthwire.core import vault
vault.MOUNTINFO = os.environ["TEST_MOUNTINFO"]
vault.DEFAULT_RUNTIME = os.environ["TEST_DEFAULT_RUNTIME"]
# Never the real kwallet-query/qdbus6: purge finds no wallet tools here.
from hearthwire.core import walletkey
walletkey.find_tools = lambda: ({{}}, walletkey.TOOLS)
sys.argv = ["hearthwire", *sys.argv[4:]]
runpy.run_module("hearthwire", run_name="__main__", alter_sys=True)
' "$@"
"""


def run_install_script(tmp_path, *argv, runtime=None, mountinfo=""):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    shim = tmp_path / "shim-bin"
    shim.mkdir(exist_ok=True)
    (shim / "python3").write_text(PYTHON_SHIM.format(python=sys.executable))
    (shim / "python3").chmod(0o755)
    (tmp_path / "mountinfo").write_text(mountinfo)
    env = {
        "PATH": f"{shim}:{os.environ['PATH']}",
        "HOME": str(home),
        "TEST_MOUNTINFO": str(tmp_path / "mountinfo"),
        "TEST_DEFAULT_RUNTIME": str(tmp_path / "no-default-runtime-{uid}"),
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={tmp_path / 'no-bus'}",
    }
    if runtime is not None:
        env["XDG_RUNTIME_DIR"] = str(runtime)
    return subprocess.run(
        ["sh", str(INSTALL_SCRIPT), *argv],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=60, check=False,
    )


@pytest.mark.parametrize(
    "argv",
    [["--bogus"], ["--uninstall-web-data", "--restart-plasma"], ["--restart-plasma", "--uninstall-web-data"],
     ["--uninstall-web-data", "x"], ["--restart-plasma", "x"]],
)
def test_install_script_rejects_unknown_or_combined_options(tmp_path, _private_runtime_dir, argv):
    completed = run_install_script(tmp_path, *argv, runtime=_private_runtime_dir)
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr.startswith("Usage: ") and "--uninstall-web-data" in completed.stderr


def test_install_script_uninstall_web_data_only_deletes(tmp_path, _private_runtime_dir):
    share = tmp_path / "home" / ".local" / "share" / "hearthwire"
    (share / "vault").mkdir(parents=True)
    (share / "vault" / "gocryptfs.conf").write_text("{}")
    completed = run_install_script(tmp_path, "--uninstall-web-data", runtime=_private_runtime_dir)
    assert (completed.returncode, completed.stderr) == (0, "")
    assert completed.stdout == "Deleted: encrypted chat folder (saved chat sign-ins).\n"
    assert not share.exists()
    again = run_install_script(tmp_path, "--uninstall-web-data", runtime=_private_runtime_dir)
    assert (again.returncode, again.stdout) == (0, "No Hearthwire chat sign-in data found.\n")
    assert sorted(path.name for path in (tmp_path / "home").iterdir()) == [".local"]


def test_install_script_uninstall_web_data_without_runtime_dir(tmp_path):
    share = tmp_path / "home" / ".local" / "share" / "hearthwire"
    (share / "vault").mkdir(parents=True)
    completed = run_install_script(tmp_path, "--uninstall-web-data")
    assert (completed.returncode, completed.stderr) == (0, "")
    assert completed.stdout == "Deleted: encrypted chat folder (saved chat sign-ins).\n"
    assert not share.exists()


def test_install_script_refuses_while_the_fake_mountinfo_shows_a_mount(tmp_path, _private_runtime_dir):
    # Proves the subprocess reads the test's mountinfo, not the real one.
    share = tmp_path / "home" / ".local" / "share" / "hearthwire"
    (share / "vault").mkdir(parents=True)
    mountpoint = Path(os.path.realpath(_private_runtime_dir)) / "hearthwire" / "vault"
    line = (f"901 30 0:99 / {mountpoint} rw,nosuid,nodev shared:1 - fuse.gocryptfs "
            f"{share / 'vault'} rw,user_id={os.getuid()},group_id={os.getgid()}\n")
    completed = run_install_script(tmp_path, "--uninstall-web-data", runtime=_private_runtime_dir, mountinfo=line)
    assert completed.returncode == 1 and completed.stdout == ""
    assert completed.stderr.startswith("Lock the encrypted folder in Hearthwire first")
    assert (share / "vault").is_dir()


def _notifyrc(tmp_path):
    path = tmp_path / "home" / ".local" / "share" / "knotifications6" / "hearthwire.notifyrc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[Global]\n")
    return path


@pytest.mark.parametrize("with_vault", [True, False])
def test_install_script_uninstall_web_data_removes_the_notifyrc(tmp_path, _private_runtime_dir, with_vault):
    if with_vault:
        (tmp_path / "home" / ".local" / "share" / "hearthwire" / "vault").mkdir(parents=True)
    notifyrc = _notifyrc(tmp_path)
    neighbour = notifyrc.parent / "plasma_workspace.notifyrc"
    neighbour.write_text("keep")
    completed = run_install_script(tmp_path, "--uninstall-web-data", runtime=_private_runtime_dir)
    assert (completed.returncode, completed.stderr) == (0, "")
    assert not notifyrc.exists()
    assert neighbour.read_text() == "keep"


def test_install_script_uninstall_web_data_removes_a_notifyrc_symlink_not_its_target(tmp_path, _private_runtime_dir):
    target = tmp_path / "precious"
    target.write_text("keep")
    link = _notifyrc(tmp_path)
    link.unlink()
    link.symlink_to(target)
    completed = run_install_script(tmp_path, "--uninstall-web-data", runtime=_private_runtime_dir)
    assert completed.returncode == 0
    assert not link.is_symlink() and target.read_text() == "keep"


def test_install_script_keeps_the_notifyrc_when_it_deletes_nothing(tmp_path, _private_runtime_dir):
    share = tmp_path / "home" / ".local" / "share" / "hearthwire"
    (share / "vault").mkdir(parents=True)
    notifyrc = _notifyrc(tmp_path)
    mountpoint = Path(os.path.realpath(_private_runtime_dir)) / "hearthwire" / "vault"
    line = (f"901 30 0:99 / {mountpoint} rw,nosuid,nodev shared:1 - fuse.gocryptfs "
            f"{share / 'vault'} rw,user_id={os.getuid()},group_id={os.getgid()}\n")
    completed = run_install_script(tmp_path, "--uninstall-web-data", runtime=_private_runtime_dir, mountinfo=line)
    assert completed.returncode == 1 and "Nothing was deleted" in completed.stderr
    assert notifyrc.read_text() == "[Global]\n"


def test_install_script_refuses_symlinked_web_data(tmp_path, _private_runtime_dir):
    target = tmp_path / "target"
    target.mkdir()
    (target / "precious").write_text("keep")
    share = tmp_path / "home" / ".local" / "share"
    share.mkdir(parents=True)
    (share / "hearthwire").symlink_to(target)
    completed = run_install_script(tmp_path, "--uninstall-web-data", runtime=_private_runtime_dir)
    assert completed.returncode == 1
    assert completed.stdout == ""
    assert "symbolic link" in completed.stderr and str(tmp_path) not in completed.stderr
    assert (target / "precious").read_text() == "keep"


# --- output and arguments -------------------------------------------------------------------


def test_output_never_contains_a_path(data, capsys, tmp_path, mounted, monkeypatch):
    texts = []
    make_profiles(mounted, ["applet-1-g0"])
    for argv in (
        ["prepare", "--store", "encrypted", "--applet", "1", "--generation", "5"],
        ["remove", "--store", "encrypted", "--applet", "1", "--keep", "5"],
    ):
        cli.main(["--web-data", *argv])
        captured = capsys.readouterr()
        texts.append(captured.out + captured.err)
    shutil.rmtree(mounted / "web")
    (mounted / "web").symlink_to(tmp_path)
    cli.main(["--web-data", "prepare", "--store", "encrypted", "--applet", "1", "--generation", "0"])
    captured = capsys.readouterr()
    texts.append(captured.out + captured.err)
    (tmp_path / "mountinfo").write_text("")
    cli.main(["--web-data", "prepare", "--store", "encrypted", "--applet", "1", "--generation", "0"])
    captured = capsys.readouterr()
    texts.append(captured.out + captured.err)
    text = "".join(texts)
    assert '"error":"symlink"' in text and '"error":"not-verified"' in text
    assert str(tmp_path) not in text
    assert "/" not in text and "applet" not in text


def test_unexpected_exception_is_a_bare_code(data, capsys, monkeypatch):
    monkeypatch.setattr(webdata, "prepare", lambda *a, **k: (_ for _ in ()).throw(RuntimeError(str(data))))
    assert prepare(capsys) == {"ok": False, "error": "os-error"}


@pytest.mark.parametrize("value", ["0", "1", "2147483648"])
def test_integer_arguments_accept_zero_to_two_pow_31(data, capsys, mounted, value):
    assert prepare(capsys, value, value) == {"ok": True}


_PREPARE = ["--web-data", "prepare", "--store", "encrypted"]


@pytest.mark.parametrize(
    "argv",
    [
        [*_PREPARE, "--applet", "-1", "--generation", "0"],
        [*_PREPARE, "--applet", "2147483649", "--generation", "0"],
        [*_PREPARE, "--applet", "1_0", "--generation", "0"],
        [*_PREPARE, "--applet", " 1", "--generation", "0"],
        [*_PREPARE, "--applet", "+1", "--generation", "0"],
        [*_PREPARE, "--applet", "0x1", "--generation", "0"],
        [*_PREPARE, "--applet", "١", "--generation", "0"],
        [*_PREPARE, "--applet", "../x", "--generation", "0"],
        [*_PREPARE, "--applet", "1"],
        [*_PREPARE, "--generation", "0"],
        ["--web-data", "prepare", "--applet", "1", "--generation", "0"],
        ["--web-data", "prepare", "--store", "memory", "--applet", "1", "--generation", "0"],
        ["--web-data", "prepare", "--store", "folder", "--applet", "1", "--generation", "0"],
        ["--web-data", "remove", "--store", "folder", "--applet", "1"],
        ["--web-data", "prepare", "--store", "", "--applet", "1", "--generation", "0"],
        [*_PREPARE, "--applet", "1", "--generation", "0", "--keep", "0"],
        ["--web-data", "remove", "--store", "encrypted", "--applet", "1", "--generation", "0"],
        ["--web-data", "delete", "--store", "encrypted", "--applet", "1"],
        [*_PREPARE, "--applet", "1", "--generation", "0", "--catalog"],
        [*_PREPARE, "--applet", "1", "--generation", "0", "--detect"],
        [*_PREPARE, "--applet", "1", "--generation", "0", "--json"],
        [*_PREPARE, "--applet", "1", "--generation", "0", "--providers", "claude"],
        [*_PREPARE, "--applet", "1", "--generation", "0", "--vault", "status"],
        [*_PREPARE, "--applet", "1", "--generation", "0", "--path", "/tmp"],
        ["--applet", "1"],
        ["--catalog", "--store", "encrypted"],
        ["--web-data", "purge", "--store", "encrypted"],
        ["--web-data", "purge", "--applet", "1"],
        ["--web-data", "purge", "--generation", "0"],
        ["--web-data", "purge", "--keep", "0"],
        ["--web-data", "purge", "--vault", "status"],
        ["--web-data", "purge", "--catalog"],
        ["--web-data", "purge", "--json"],
        ["--web-data", "purge", "extra"],
    ],
)
def test_bad_arguments_exit_2_and_touch_nothing(data, capsys, argv):
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 2
    assert capsys.readouterr().out == ""
    assert not data.exists()


def _cli(tmp_path, *argv):
    src = Path(__file__).resolve().parent.parent / "src"
    env = {**os.environ, "PYTHONPATH": str(src), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [sys.executable, "-m", "hearthwire", "--web-data", *argv],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=60, check=False,
    )


def test_cli_subprocess_prints_one_json_object_and_never_creates_a_plaintext_store(data, tmp_path):
    # No gocryptfs mount in this (private) runtime dir: refused, nothing created.
    completed = _cli(tmp_path, "prepare", "--store", "encrypted", "--applet", "1", "--generation", "0")
    assert (completed.returncode, completed.stdout, completed.stderr) == (
        0, '{"ok":false,"error":"not-verified"}\n', "")
    assert not data.exists()


def test_cli_subprocess_rejects_store_folder(data, tmp_path):
    completed = _cli(tmp_path, "prepare", "--store", "folder", "--applet", "1", "--generation", "0")
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr.startswith("usage: ")
    assert not data.exists()


def test_webdata_module_never_prints():
    code = Path(webdata.__file__).read_text(encoding="utf-8")
    assert "print(" not in code
    assert "subprocess" not in code
