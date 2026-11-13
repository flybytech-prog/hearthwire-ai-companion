"""Chat profile folders (core/webdata.py) and the --web-data CLI."""

import errno
import json
import os
import shutil
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from hearthwire import cli
from hearthwire.core import vault, webdata


@pytest.fixture(autouse=True)
def _empty_proc(tmp_path_factory, monkeypatch):
    """remove-site's open-file scan never reads the host's /proc: an empty fake one."""
    proc = tmp_path_factory.mktemp("proc")
    monkeypatch.setattr(webdata, "PROC_ROOT", str(proc))
    return proc


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
    # The applet id starts at 1 (below); the generation may be 0.
    assert prepare(capsys, value if value != "0" else "1", value) == {"ok": True}


@pytest.mark.parametrize("operation", ["prepare", "prune", "remove-site", "remove"])
def test_applet_zero_is_refused_like_usage_history(data, capsys, mounted, operation):
    argv = ["--web-data", operation, "--store", "encrypted", "--applet", "0"]
    argv += {"prepare": ["--generation", "0"], "prune": ["--generation", "0", "--known", "claude"],
             "remove-site": ["--generation", "0", "--site", "claude"], "remove": []}[operation]
    make_container(mounted, 0, 0, sites=("claude",))
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--applet must be from 1 to 2147483648" in captured.err
    assert names(mounted / "web" / "applet-0-g0") == ["Cookies", "site-claude"]


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


# --- per-site folders: prepare --sites, prune --known, remove-site (task 004) -----------------


BUILTINS = ("claude", "chatgpt", "grok", "gemini", "copilot", "mscopilot", "local")
USER_IDS = tuple(f"user-{number:08x}" for number in range(200))


def web_op(capsys, operation, applet=1, generation=0, **options):
    argv = [operation, "--store", "encrypted", "--applet", str(applet), "--generation", str(generation)]
    for name, value in options.items():
        argv += [f"--{name}", value]
    return web_reply(argv, capsys)


def make_container(mountpoint, applet=1, generation=0, sites=(), root_files=("Cookies",)):
    container = mountpoint / "web" / f"applet-{applet}-g{generation}"
    container.mkdir(parents=True, exist_ok=True)
    for name in root_files:
        (container / name).write_text("x")
    for site in sites:
        (container / f"site-{site}").mkdir()
        (container / f"site-{site}" / "Cookies").write_text(site)
    return container


def names(path):
    return sorted(entry.name for entry in path.iterdir())


def outside_target(tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    target.chmod(0o755)
    (target / "precious").write_text("keep")
    return target


def assert_target_intact(target):
    assert names(target) == ["precious"]
    assert (target / "precious").read_text() == "keep"
    assert mode(target) == 0o755


def fake_foreign_owner(monkeypatch, foreign_name):
    """Make lstat-style lookups of ``foreign_name`` report another owner.

    Unprivileged tests cannot chown, so the owner check is exercised by
    rewriting st_uid of the stat result for that one name.
    """
    real_stat = os.stat

    def stat_with_foreign_owner(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if path == foreign_name:
            fields = list(result[:10])
            fields[4] = os.getuid() + 1
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(os, "stat", stat_with_foreign_owner)


def test_builtin_site_ids_match_the_backup_helper():
    from hearthwire.core import settingsbackup
    assert webdata.BUILTIN_SITE_IDS == settingsbackup.WEB_SITE_IDS == BUILTINS
    assert "ollama" not in webdata.BUILTIN_SITE_IDS
    assert webdata.MAX_SITE_IDS == len(BUILTINS) + len(USER_IDS) == 207


@pytest.mark.parametrize("value", [*BUILTINS, "user-00000000", "user-0123abcd", "user-ffffffff"])
def test_valid_site_ids(value):
    assert webdata.valid_site_id(value)
    assert webdata.site_folder(value) == f"site-{value}"


@pytest.mark.parametrize("value", [
    "", "ollama", "Claude", "CLAUDE", " claude", "claude ", "claude\n", "claude/..", "../claude", ".", "..",
    "site-claude", "user-", "user-deadbee", "user-deadbeef0", "user-DEADBEEF", "user-deadbeeg", "user_deadbeef",
    "user-deadbeef/", "user-١٢٣٤٥٦٧٨", "xclaude", "claudex", "local2", None, 1,
])
def test_invalid_site_ids(value):
    assert not webdata.valid_site_id(value)
    if isinstance(value, str):
        with pytest.raises(ValueError):
            webdata.site_folder(value)


def test_prepare_creates_only_the_listed_site_folders_private(data, capsys, mounted):
    assert web_op(capsys, "prepare", 3, 2, sites="claude,user-0a1b2c3d") == {"ok": True}
    container = mounted / "web" / "applet-3-g2"
    assert names(container) == ["site-claude", "site-user-0a1b2c3d"]
    for path in (mounted / "web", container, container / "site-claude", container / "site-user-0a1b2c3d"):
        assert path.is_dir() and not path.is_symlink()
        assert mode(path) == 0o700
    assert names(mounted / "web") == ["applet-3-g2"]
    assert no_plaintext_store(data)


def test_prepare_sites_is_idempotent_resets_modes_and_keeps_data(data, capsys, mounted):
    container = make_container(mounted, sites=("gemini",), root_files=())
    (container / "site-gemini").chmod(0o755)
    assert web_op(capsys, "prepare", sites="gemini,grok") == {"ok": True}
    assert web_op(capsys, "prepare", sites="gemini,grok") == {"ok": True}
    assert names(container) == ["site-gemini", "site-grok"]
    assert mode(container / "site-gemini") == mode(container / "site-grok") == 0o700
    assert (container / "site-gemini" / "Cookies").read_text() == "gemini"


def test_prepare_without_sites_creates_only_the_container(data, capsys, mounted):
    assert prepare(capsys, 1, 0) == {"ok": True}
    assert names(mounted / "web" / "applet-1-g0") == []


def test_prepare_accepts_207_ids(data, capsys, mounted):
    ids = BUILTINS + USER_IDS
    assert web_op(capsys, "prepare", sites=",".join(ids)) == {"ok": True}
    assert names(mounted / "web" / "applet-1-g0") == sorted(f"site-{site}" for site in ids)


def test_prepare_refuses_a_symlinked_site_folder(data, capsys, tmp_path, mounted):
    target = outside_target(tmp_path)
    container = make_container(mounted, root_files=())
    (container / "site-chatgpt").symlink_to(target)
    assert web_op(capsys, "prepare", sites="chatgpt") == {"ok": False, "error": "symlink"}
    assert (container / "site-chatgpt").is_symlink()
    assert_target_intact(target)


def test_prepare_sites_refuses_a_symlinked_container(data, capsys, tmp_path, mounted):
    target = outside_target(tmp_path)
    (mounted / "web").mkdir()
    (mounted / "web" / "applet-1-g0").symlink_to(target)
    assert web_op(capsys, "prepare", sites="claude") == {"ok": False, "error": "symlink"}
    assert_target_intact(target)


def test_prepare_refuses_a_file_as_site_folder(data, capsys, mounted):
    container = make_container(mounted, root_files=("site-grok",))
    assert web_op(capsys, "prepare", sites="grok") == {"ok": False, "error": "not-directory"}
    assert (container / "site-grok").read_text() == "x"


def test_prepare_refuses_a_foreign_site_folder(data, capsys, mounted, monkeypatch):
    container = make_container(mounted, sites=("claude",), root_files=())
    (container / "site-claude").chmod(0o755)
    fake_foreign_owner(monkeypatch, "site-claude")
    assert web_op(capsys, "prepare", sites="claude") == {"ok": False, "error": "not-owned"}
    assert mode(container / "site-claude") == 0o755


def test_prune_keeps_exactly_the_known_site_folders(data, capsys, mounted):
    # Only site folders at the root: no rollback, so the known ones stay.
    container = make_container(
        mounted,
        sites=("claude", "gemini", "user-0000000a", "user-0000000b", "local"),
        root_files=("site-grok",),
    )
    known = ",".join(("claude", "gemini", "grok", "user-0000000a"))
    assert web_op(capsys, "prune", known=known) == {"ok": True}
    assert names(container) == ["site-claude", "site-gemini", "site-user-0000000a"]
    assert (container / "site-claude" / "Cookies").read_text() == "claude"
    assert (container / "site-user-0000000a" / "Cookies").read_text() == "user-0000000a"


def test_prune_never_touches_other_generations_or_applets(data, capsys, mounted):
    make_container(mounted, 1, 0, sites=("claude", "user-000000aa"), root_files=())
    others = {
        (1, 1): make_container(mounted, 1, 1, sites=("claude", "user-0000000b")),
        (2, 0): make_container(mounted, 2, 0, sites=("user-0000000b",)),
        (12, 0): make_container(mounted, 12, 0, sites=("grok",)),
        (1, 10): make_container(mounted, 1, 10, sites=("grok",)),
    }
    before = {key: names(path) for key, path in others.items()}
    (mounted / "web" / "applet-1-g0.bak").mkdir()
    (mounted / "web" / "notes.txt").write_text("keep")
    assert web_op(capsys, "prune", 1, 0, known="claude") == {"ok": True}
    assert names(mounted / "web" / "applet-1-g0") == ["site-claude"]
    assert {key: names(path) for key, path in others.items()} == before
    assert (mounted / "web" / "applet-1-g0.bak").is_dir()
    assert (mounted / "web" / "notes.txt").read_text() == "keep"


def test_prune_of_missing_folders_is_ok_and_creates_nothing(data, capsys, mounted):
    assert web_op(capsys, "prune", known="claude") == {"ok": True}
    assert not (mounted / "web").exists()
    (mounted / "web").mkdir()
    assert web_op(capsys, "prune", known="claude") == {"ok": True}
    assert names(mounted / "web") == []


def test_prune_refuses_a_symlinked_container(data, capsys, tmp_path, mounted):
    target = outside_target(tmp_path)
    (target / "site-gone").mkdir()
    (mounted / "web").mkdir()
    (mounted / "web" / "applet-1-g0").symlink_to(target)
    assert web_op(capsys, "prune", known="claude") == {"ok": False, "error": "symlink"}
    assert names(target) == ["precious", "site-gone"]
    assert (mounted / "web" / "applet-1-g0").is_symlink()


def test_prune_refuses_a_symlinked_web_folder(data, capsys, tmp_path, mounted):
    target = outside_target(tmp_path)
    (target / "applet-1-g0").mkdir()
    (target / "applet-1-g0" / "Cookies").write_text("x")
    (mounted / "web").symlink_to(target)
    assert web_op(capsys, "prune", known="claude") == {"ok": False, "error": "symlink"}
    assert (target / "applet-1-g0" / "Cookies").read_text() == "x"


@pytest.mark.parametrize("name, rollback", [("site-claude", False), ("site-grok", False),
                                            ("site-ollama", True), ("Cookies", True)])
def test_prune_unlinks_symlinks_and_never_follows_them(data, capsys, tmp_path, mounted, name, rollback):
    # site-claude is known but a symlink is never a profile, so it is unlinked too.
    # A non-site name at the root is rollback evidence: then every site folder goes.
    target = outside_target(tmp_path)
    container = make_container(mounted, sites=("chatgpt",), root_files=())
    (container / name).symlink_to(target)
    (container / "site-chatgpt" / "link").symlink_to(target)
    assert web_op(capsys, "prune", known="claude,chatgpt") == {"ok": True}
    assert names(container) == ([] if rollback else ["site-chatgpt"])
    if not rollback:
        assert (container / "site-chatgpt" / "link").is_symlink()
    assert_target_intact(target)


def test_prune_deletes_a_known_name_that_is_a_file(data, capsys, mounted):
    container = make_container(mounted, root_files=("site-claude",))
    assert web_op(capsys, "prune", known="claude") == {"ok": True}
    assert names(container) == []


def test_prune_refuses_a_foreign_folder(data, capsys, mounted, monkeypatch):
    container = make_container(mounted, sites=("claude",), root_files=())
    (container / "leftover").mkdir()
    fake_foreign_owner(monkeypatch, "leftover")
    assert web_op(capsys, "prune", known="claude") == {"ok": False, "error": "not-owned"}
    assert (container / "leftover").is_dir()


def test_prune_refuses_a_foreign_container(data, capsys, mounted, monkeypatch):
    container = make_container(mounted, root_files=("Cookies",))
    fake_foreign_owner(monkeypatch, "applet-1-g0")
    assert web_op(capsys, "prune", known="claude") == {"ok": False, "error": "not-owned"}
    assert names(container) == ["Cookies"]


def test_prune_requires_symlink_safe_rmtree(data, capsys, mounted, monkeypatch):
    container = make_container(mounted, root_files=("Cookies",))
    monkeypatch.setattr(shutil.rmtree, "avoids_symlink_attacks", False)
    assert web_op(capsys, "prune", known="claude") == {"ok": False, "error": "os-error"}
    assert names(container) == ["Cookies"]


def test_prune_needs_a_verified_mount(data, capsys, tmp_path, mounted):
    container = make_container(mounted, root_files=("Cookies",))
    (tmp_path / "mountinfo").write_text("")
    assert web_op(capsys, "prune", known="claude") == {"ok": False, "error": "not-verified"}
    assert web_op(capsys, "remove-site", site="claude") == {"ok": False, "error": "not-verified"}
    assert web_op(capsys, "prepare", sites="claude") == {"ok": False, "error": "not-verified"}
    assert names(container) == ["Cookies"]


def test_remove_site_deletes_only_its_target(data, capsys, mounted):
    container = make_container(mounted, sites=("claude", "chatgpt", "user-0000000c"), root_files=("Cookies",))
    other_generation = make_container(mounted, 1, 1, sites=("claude",))
    other_applet = make_container(mounted, 2, 0, sites=("claude",))
    assert web_op(capsys, "remove-site", site="claude") == {"ok": True}
    assert names(container) == ["Cookies", "site-chatgpt", "site-user-0000000c"]
    assert names(other_generation) == ["Cookies", "site-claude"]
    assert names(other_applet) == ["Cookies", "site-claude"]
    assert web_op(capsys, "remove-site", site="user-0000000c") == {"ok": True}
    assert names(container) == ["Cookies", "site-chatgpt"]


def test_remove_site_of_missing_folders_is_ok(data, capsys, mounted):
    assert web_op(capsys, "remove-site", site="grok") == {"ok": True}
    assert not (mounted / "web").exists()
    make_container(mounted, root_files=())
    assert web_op(capsys, "remove-site", site="grok") == {"ok": True}


def test_remove_site_unlinks_a_symlink_and_never_follows_it(data, capsys, tmp_path, mounted):
    target = outside_target(tmp_path)
    container = make_container(mounted, sites=("gemini",), root_files=())
    (container / "site-claude").symlink_to(target)
    (container / "site-gemini" / "link").symlink_to(target)
    assert web_op(capsys, "remove-site", site="claude") == {"ok": True}
    assert web_op(capsys, "remove-site", site="gemini") == {"ok": True}
    assert names(container) == []
    assert_target_intact(target)


def test_remove_site_refuses_a_symlinked_container(data, capsys, tmp_path, mounted):
    target = outside_target(tmp_path)
    (target / "site-claude").mkdir()
    (mounted / "web").mkdir()
    (mounted / "web" / "applet-1-g0").symlink_to(target)
    assert web_op(capsys, "remove-site", site="claude") == {"ok": False, "error": "symlink"}
    assert names(target) == ["precious", "site-claude"]


def test_remove_site_refuses_a_foreign_folder(data, capsys, mounted, monkeypatch):
    container = make_container(mounted, sites=("claude",), root_files=())
    fake_foreign_owner(monkeypatch, "site-claude")
    assert web_op(capsys, "remove-site", site="claude") == {"ok": False, "error": "not-owned"}
    assert (container / "site-claude" / "Cookies").read_text() == "claude"


def test_remove_keep_still_works_with_site_folders(data, capsys, tmp_path, mounted):
    target = outside_target(tmp_path)
    old = make_container(mounted, 1, 0, sites=("claude", "user-0000000d"))
    (old / "site-claude" / "link").symlink_to(target)
    kept = make_container(mounted, 1, 1, sites=("claude", "gemini"))
    other = make_container(mounted, 2, 0, sites=("claude",))
    assert remove(capsys, 1, keep=1) == {"ok": True}
    assert names(mounted / "web") == ["applet-1-g1", "applet-2-g0"]
    assert names(kept) == ["Cookies", "site-claude", "site-gemini"]
    assert names(other) == ["Cookies", "site-claude"]
    assert_target_intact(target)
    assert remove(capsys, 1) == {"ok": True}
    assert names(mounted / "web") == ["applet-2-g0"]


def test_prepare_prune_remove_site_flow(data, capsys, mounted):
    # Unlock: prepare then prune; a site's data is cleared; an added site is removed.
    old_root = make_container(mounted, 4, 2, root_files=("Cookies", "Preferences"))
    assert web_op(capsys, "prepare", 4, 2, sites="claude,user-000000ff") == {"ok": True}
    assert names(old_root) == ["site-claude", "site-user-000000ff"]
    (old_root / "site-claude" / "Cookies").write_text("new")
    assert web_op(capsys, "prune", 4, 2, known=",".join(BUILTINS + ("user-000000ff",))) == {"ok": True}
    assert names(old_root) == ["site-claude", "site-user-000000ff"]
    assert (old_root / "site-claude" / "Cookies").read_text() == "new"
    assert web_op(capsys, "remove-site", 4, 2, site="claude") == {"ok": True}
    assert web_op(capsys, "prune", 4, 2, known=",".join(BUILTINS)) == {"ok": True}
    assert names(old_root) == []


@pytest.mark.parametrize("call", ["prepare", "prune", "remove-site"])
@pytest.mark.parametrize("ids", [("ollama",), ("claude", "claude"), (), ("Claude",), ("user-DEADBEEF",),
                                 BUILTINS + USER_IDS + ("user-ffffffff",)])
def test_library_refuses_bad_ids_and_touches_nothing(data, mounted, call, ids):
    with pytest.raises(ValueError):
        if call == "prepare":
            webdata.prepare("encrypted", 1, 0, sites=ids or ("",))
        elif call == "prune":
            webdata.prune("encrypted", 1, 0, ids)
        else:
            webdata.remove_site("encrypted", 1, 0, ",".join(ids))
    assert not (mounted / "web").exists()


def test_library_refuses_any_other_store_for_site_operations(data):
    with pytest.raises(ValueError):
        webdata.prune("folder", 1, 0, ("claude",))
    with pytest.raises(ValueError):
        webdata.remove_site("folder", 1, 0, "claude")
    with pytest.raises(ValueError):
        webdata.prepare("folder", 1, 0, sites=("claude",))
    assert not data.exists()


_SITE_BASE = ["--store", "encrypted", "--applet", "1", "--generation", "0"]
_TOO_MANY = ",".join(BUILTINS + USER_IDS + ("user-ffffffff",))


@pytest.mark.parametrize("operation, option", [("prepare", "--sites"), ("prune", "--known")])
@pytest.mark.parametrize("value", [
    "ollama", "claude,ollama", "Claude", "claude,claude", "claude,chatgpt,claude", "", ",", "claude,", ",claude",
    " claude", "claude ,chatgpt", "claude;chatgpt", "user-deadbee", "user-deadbeef0", "user-DEADBEEF",
    "user-deadbeeg", "site-claude", "../claude", "claude/x", "user-0000000a,user-0000000a", _TOO_MANY,
])
def test_bad_site_id_lists_are_usage_errors(data, capsys, operation, option, value):
    with pytest.raises(SystemExit) as raised:
        cli.main(["--web-data", operation, *_SITE_BASE, option, value])
    assert raised.value.code == 2
    assert capsys.readouterr().out == ""
    assert not data.exists()


@pytest.mark.parametrize("value", ["ollama", "", "Claude", "claude,chatgpt", "user-deadbee", "site-claude", ".."])
def test_bad_single_site_id_is_a_usage_error(data, capsys, value):
    with pytest.raises(SystemExit) as raised:
        cli.main(["--web-data", "remove-site", *_SITE_BASE, "--site", value])
    assert raised.value.code == 2
    assert capsys.readouterr().out == ""
    assert not data.exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["--web-data", "prune", *_SITE_BASE],
        ["--web-data", "prune", "--store", "encrypted", "--applet", "1", "--known", "claude"],
        ["--web-data", "prune", "--store", "encrypted", "--generation", "0", "--known", "claude"],
        ["--web-data", "prune", "--applet", "1", "--generation", "0", "--known", "claude"],
        ["--web-data", "prune", *_SITE_BASE, "--known", "claude", "--keep", "0"],
        ["--web-data", "prune", *_SITE_BASE, "--known", "claude", "--sites", "claude"],
        ["--web-data", "prune", *_SITE_BASE, "--known", "claude", "--site", "claude"],
        ["--web-data", "remove-site", *_SITE_BASE],
        ["--web-data", "remove-site", "--store", "encrypted", "--applet", "1", "--site", "claude"],
        ["--web-data", "remove-site", *_SITE_BASE, "--site", "claude", "--keep", "0"],
        ["--web-data", "remove-site", *_SITE_BASE, "--site", "claude", "--known", "claude"],
        ["--web-data", "remove-site", *_SITE_BASE, "--site", "claude", "--site", "x"],
        ["--web-data", "prepare", *_SITE_BASE, "--known", "claude"],
        ["--web-data", "prepare", *_SITE_BASE, "--site", "claude"],
        ["--web-data", "prepare", "--store", "encrypted", "--applet", "1", "--sites", "claude"],
        ["--web-data", "remove", "--store", "encrypted", "--applet", "1", "--sites", "claude"],
        ["--web-data", "remove", "--store", "encrypted", "--applet", "1", "--known", "claude"],
        ["--web-data", "remove", "--store", "encrypted", "--applet", "1", "--site", "claude"],
        ["--web-data", "purge", "--sites", "claude"],
        ["--web-data", "purge", "--known", "claude"],
        ["--web-data", "purge", "--site", "claude"],
        ["--sites", "claude"],
        ["--known", "claude"],
        ["--site", "claude"],
        ["--catalog", "--site", "claude"],
        ["--vault", "status", "--known", "claude"],
        ["--prompts", "list", "--site", "claude"],
        ["--usage-history", "read", "--applet", "1", "--sites", "claude"],
        ["--web-data", "prune", "--store", "folder", *_SITE_BASE[2:], "--known", "claude"],
        ["--web-data", "remove-site", *_SITE_BASE, "--site", "claude", "--json"],
    ],
)
def test_bad_site_operation_arguments_exit_2_and_touch_nothing(data, capsys, argv):
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 2
    assert capsys.readouterr().out == ""
    assert not data.exists()


def test_site_operation_output_never_contains_a_path(data, capsys, tmp_path, mounted, monkeypatch):
    texts = []

    def run(*argv):
        cli.main(["--web-data", *argv])
        captured = capsys.readouterr()
        texts.append(captured.out + captured.err)

    make_container(mounted, sites=("claude", "user-0000000e"))
    run("prepare", *_SITE_BASE, "--sites", "claude,user-0000000e")
    run("prune", *_SITE_BASE, "--known", "claude")
    run("remove-site", *_SITE_BASE, "--site", "claude")
    container = mounted / "web" / "applet-1-g0"
    (container / "site-gemini").symlink_to(tmp_path)
    run("prepare", *_SITE_BASE, "--sites", "gemini")
    (container / "leftover").mkdir()
    with monkeypatch.context() as patch:
        fake_foreign_owner(patch, "leftover")
        run("prune", *_SITE_BASE, "--known", "claude")
    shutil.rmtree(container)
    container.symlink_to(tmp_path)
    run("prune", *_SITE_BASE, "--known", "claude")
    run("remove-site", *_SITE_BASE, "--site", "claude")
    (tmp_path / "mountinfo").write_text("")
    run("prune", *_SITE_BASE, "--known", "claude")
    text = "".join(texts)
    for code in ('"ok":true', '"error":"symlink"', '"error":"not-owned"', '"error":"not-verified"'):
        assert code in text
    assert str(tmp_path) not in text
    assert "/" not in text and "applet" not in text and "site" not in text
    assert "claude" not in text and "user-" not in text and "Cookies" not in text


def test_unexpected_exception_in_site_operations_is_a_bare_code(data, capsys, monkeypatch):
    boom = lambda *a, **k: (_ for _ in ()).throw(RuntimeError(str(data)))  # noqa: E731
    monkeypatch.setattr(webdata, "prune", boom)
    monkeypatch.setattr(webdata, "remove_site", boom)
    assert web_op(capsys, "prune", known="claude") == {"ok": False, "error": "os-error"}
    assert web_op(capsys, "remove-site", site="claude") == {"ok": False, "error": "os-error"}


# --- REV-M1: leftovers at the container root mean a rollback; every site starts fresh --------


# What 1.0.1 writes when it opens the container as its one shared profile.
OLD_SHARED_PROFILE = ("Cookies", "Cookies-journal", "Preferences", "Network Persistent State")
OLD_SHARED_DIRS = ("Local Storage", "Service Worker", "Session Storage")


def downgrade_wrote(container):
    for name in OLD_SHARED_PROFILE:
        (container / name).write_text("1.0.1")
    for name in OLD_SHARED_DIRS:
        (container / name).mkdir()
        (container / name / "data").write_text("1.0.1")


def test_re_upgrade_never_brings_an_old_sign_in_back(data, capsys, mounted):
    # The lab's REV-M1 sequence: signed in on this version, down to 1.0.1, up again.
    container = make_container(mounted, 4, 2, sites=("claude", "user-0000000a"), root_files=())
    (container / "site-claude" / "Cookies").write_text("ck_one=one")
    downgrade_wrote(container)
    other = make_container(mounted, 4, 1, sites=("claude",))
    other_applet = make_container(mounted, 5, 2, sites=("claude",))
    # The first prepare after the unlock comes before any profile opens.
    assert web_op(capsys, "prepare", 4, 2, sites="claude") == {"ok": True}
    assert names(container) == ["site-claude"]
    assert names(container / "site-claude") == []
    assert mode(container / "site-claude") == 0o700
    assert web_op(capsys, "prune", 4, 2, known=",".join(BUILTINS + ("user-0000000a",))) == {"ok": True}
    assert names(container) == ["site-claude"]
    assert names(other) == ["Cookies", "site-claude"] and names(other_applet) == ["Cookies", "site-claude"]


def test_prune_after_a_rollback_deletes_every_site_folder(data, capsys, mounted):
    container = make_container(mounted, sites=("claude", "gemini", "user-0000000a"), root_files=())
    downgrade_wrote(container)
    assert web_op(capsys, "prune", known=",".join(BUILTINS + ("user-0000000a",))) == {"ok": True}
    assert names(container) == []
    assert container.is_dir() and not container.is_symlink()


@pytest.mark.parametrize("leftover", ["Cookies", "site-", "site-ollama", "site-Claude", "site-claude.bak",
                                      "site-user-DEADBEEF", "x"])
def test_any_non_site_name_at_the_root_counts_as_a_rollback(data, capsys, mounted, leftover):
    container = make_container(mounted, sites=("claude",), root_files=(leftover,))
    assert web_op(capsys, "prune", known="claude") == {"ok": True}
    assert names(container) == []


def test_prepare_without_leftovers_keeps_every_site_folder(data, capsys, mounted):
    container = make_container(mounted, sites=("claude", "user-0000000a"), root_files=("site-grok",))
    assert web_op(capsys, "prepare", sites="gemini") == {"ok": True}
    assert names(container) == ["site-claude", "site-gemini", "site-grok", "site-user-0000000a"]
    assert (container / "site-claude" / "Cookies").read_text() == "claude"


def test_prepare_without_sites_also_clears_after_a_rollback(data, capsys, mounted):
    container = make_container(mounted, sites=("claude",), root_files=("Cookies",))
    assert prepare(capsys, 1, 0) == {"ok": True}
    assert names(container) == []


def test_rollback_clear_deletes_site_folders_before_the_leftovers(data, capsys, mounted, monkeypatch):
    container = make_container(mounted, sites=("claude", "grok"), root_files=("Cookies", "Preferences"))
    order = []
    real = webdata.remove_entry
    monkeypatch.setattr(webdata, "remove_entry", lambda parent, name: (order.append(name), real(parent, name)))
    assert web_op(capsys, "prune", known="claude") == {"ok": True}
    assert order == ["site-claude", "site-grok", "Cookies", "Preferences"]
    assert names(container) == []


@pytest.mark.parametrize("operation", ["prepare", "prune"])
def test_a_refused_site_folder_keeps_the_rollback_evidence(data, capsys, mounted, monkeypatch, operation):
    # The next run must try again, so the leftovers stay while a site folder does.
    container = make_container(mounted, sites=("claude", "gemini"), root_files=("Cookies",))
    with monkeypatch.context() as patch:
        fake_foreign_owner(patch, "site-gemini")
        options = {"sites": "claude"} if operation == "prepare" else {"known": "claude"}
        assert web_op(capsys, operation, **options) == {"ok": False, "error": "not-owned"}
    assert names(container) == ["Cookies", "site-gemini"]
    assert web_op(capsys, operation, **options) == {"ok": True}
    assert names(container) == (["site-claude"] if operation == "prepare" else [])


def test_a_refused_leftover_stops_prepare_before_any_site_folder(data, capsys, mounted, monkeypatch):
    container = make_container(mounted, sites=("claude",), root_files=())
    (container / "Local Storage").mkdir()
    fake_foreign_owner(monkeypatch, "Local Storage")
    assert web_op(capsys, "prepare", sites="claude,gemini") == {"ok": False, "error": "not-owned"}
    assert names(container) == ["Local Storage"]


def test_rollback_clear_unlinks_symlinks_and_never_follows_them(data, capsys, tmp_path, mounted):
    target = outside_target(tmp_path)
    container = make_container(mounted, sites=("gemini",), root_files=())
    (container / "site-claude").symlink_to(target)
    (container / "Cookies").symlink_to(target)
    (container / "site-gemini" / "link").symlink_to(target)
    assert web_op(capsys, "prepare", sites="claude") == {"ok": True}
    assert names(container) == ["site-claude"]
    assert not (container / "site-claude").is_symlink()
    assert_target_intact(target)


def test_rollback_clear_replies_with_codes_only(data, capsys, tmp_path, mounted, monkeypatch):
    texts = []
    container = make_container(mounted, sites=("claude",), root_files=("Cookies",))
    for argv in (["prepare", *_SITE_BASE, "--sites", "claude"], ["prune", *_SITE_BASE, "--known", "claude"]):
        downgrade_wrote(container)
        with monkeypatch.context() as patch:
            fake_foreign_owner(patch, "Local Storage")
            cli.main(["--web-data", *argv])
        cli.main(["--web-data", *argv])
        captured = capsys.readouterr()
        texts.append(captured.out + captured.err)
    text = "".join(texts)
    assert text.count('{"ok":false,"error":"not-owned"}') == 2 and text.count('{"ok":true}') == 2
    assert str(tmp_path) not in text and "/" not in text
    assert "Cookies" not in text and "site" not in text and "claude" not in text and "Local" not in text


# --- SEC-I2: no leading zeros, no option given twice --------------------------------------


@pytest.mark.parametrize("argv", [
    [*_PREPARE, "--applet", "01", "--generation", "0"],
    [*_PREPARE, "--applet", "00", "--generation", "0"],
    [*_PREPARE, "--applet", "1", "--generation", "00"],
    [*_PREPARE, "--applet", "1", "--generation", "007"],
    ["--web-data", "remove", "--store", "encrypted", "--applet", "1", "--keep", "01"],
    ["--web-data", "remove-site", *_SITE_BASE, "--site", "claude", "--site", "gemini"],
    ["--web-data", "remove-site", *_SITE_BASE, "--site", "claude", "--site", "claude"],
    ["--web-data", "prepare", *_SITE_BASE, "--sites", "claude", "--sites", "gemini"],
    ["--web-data", "prune", *_SITE_BASE, "--known", "claude", "--known", "gemini"],
    ["--web-data", "prune", *_SITE_BASE, "--known", "claude", "--know", "gemini"],
    [*_PREPARE, "--applet", "1", "--applet", "2", "--generation", "0"],
    [*_PREPARE, "--applet", "1", "--generation", "0", "--generation", "1"],
    [*_PREPARE, "--applet", "1", "--generation", "0", "--gen", "1"],
    [*_PREPARE, "--store", "encrypted", "--applet", "1", "--generation", "0"],
    ["--web-data", "prepare", "--web-data", "remove", "--store", "encrypted", "--applet", "1", "--generation", "0"],
    ["--web-data", "remove", "--store", "encrypted", "--applet", "1", "--keep", "0", "--keep", "1"],
    ["--web-data", "purge", "--web-data", "purge"],
])
def test_leading_zeros_and_repeated_options_exit_2_and_touch_nothing(data, capsys, mounted, argv):
    make_container(mounted, sites=("claude", "gemini"), root_files=())
    before = names(mounted / "web" / "applet-1-g0")
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 2
    assert capsys.readouterr().out == ""
    assert names(mounted / "web" / "applet-1-g0") == before
    assert names(mounted / "web") == ["applet-1-g0"]


@pytest.mark.parametrize("argv", [["--json", "--json"], ["--catalog", "--catalog"], ["--detect", "--det"],
                                  ["--vault", "status", "--vault", "lock"], ["--prompts", "list", "--prompts", "list"],
                                  ["--usage-history", "read", "--applet", "1", "--applet", "1"],
                                  ["--port-owner", "8080", "--port-owner", "9090"]])
def test_every_option_is_refused_the_second_time(data, capsys, argv):
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "may be given only once" in captured.err


def test_a_repeated_option_is_named_without_its_value(data, capsys):
    with pytest.raises(SystemExit):
        cli.main(["--data", "secret-settings-text", "--data", "more-secret-text"])
    err = capsys.readouterr().err
    assert "--data" in err and "secret" not in err


# --- L2-r: remove-site refuses with "busy" while a file in the site folder is open -----------


def fake_process(proc, pid, fds=(), maps=(), uid=None, uids=None):
    """A fake /proc/<pid>: ``fd/<n>`` links to ``fds``, a ``maps`` file mapping ``maps``
    and a ``status`` with all four uids ``uid`` (default: ours), or exactly ``uids``."""
    process = proc / str(pid)
    (process / "fd").mkdir(parents=True)
    every = os.getuid() if uid is None else uid
    fields = uids if uids is not None else (every,) * 4
    (process / "status").write_text(
        f"Name:\tplasmashell\nState:\tS (sleeping)\nPid:\t{pid}\n"
        f"Uid:\t{chr(9).join(str(field) for field in fields)}\nGid:\t0\t0\t0\t0\n")
    for number, target in enumerate(fds):
        (process / "fd" / str(number)).symlink_to(target)
    lines = ["00400000-00452000 r-xp 00000000 08:02 173521 /usr/bin/plasmashell",
             "7f0000000000-7f0000021000 rw-p 00000000 00:00 0 ",
             "7ffd00000000-7ffd00021000 rw-p 00000000 00:00 0 [stack]"]
    lines += [f"7f1000000000-7f1000001000 r--s 00000000 00:2a 4242 {path}" for path in maps]
    (process / "maps").write_text("\n".join(lines) + "\n")
    return process


def site_path(mounted, site="claude"):
    return os.path.join(os.path.realpath(mounted), "web", "applet-1-g0", f"site-{site}")


def test_remove_site_is_busy_while_a_file_in_it_is_open(data, capsys, mounted, _empty_proc):
    container = make_container(mounted, sites=("claude", "gemini"), root_files=())
    (container / "site-claude" / "IndexedDB").mkdir()
    fake_process(_empty_proc, 4242, fds=["/dev/null", "socket:[1234]",
                                        site_path(mounted) + "/IndexedDB/LOCK"])
    assert web_op(capsys, "remove-site", site="claude") == {"ok": False, "error": "busy"}
    # Nothing at all was deleted.
    assert names(container) == ["site-claude", "site-gemini"]
    assert names(container / "site-claude") == ["Cookies", "IndexedDB"]
    # Another site of the same generation is not held up.
    assert web_op(capsys, "remove-site", site="gemini") == {"ok": True}
    # Once the file is closed, the delete works.
    shutil.rmtree(_empty_proc / "4242")
    assert web_op(capsys, "remove-site", site="claude") == {"ok": True}
    assert names(container) == []


def test_remove_site_is_busy_while_the_folder_itself_is_open(data, capsys, mounted, _empty_proc):
    container = make_container(mounted, sites=("claude",), root_files=())
    fake_process(_empty_proc, 7, fds=[site_path(mounted)])
    assert web_op(capsys, "remove-site", site="claude") == {"ok": False, "error": "busy"}
    assert names(container) == ["site-claude"]


def test_remove_site_is_not_busy_for_files_elsewhere(data, capsys, mounted, _empty_proc):
    container = make_container(mounted, sites=("claude",), root_files=())
    other_generation = make_container(mounted, 1, 1, sites=("claude",), root_files=())
    fake_process(_empty_proc, 10, fds=["/dev/null", "pipe:[99]", "anon_inode:[eventfd]",
                                      os.path.join(os.path.realpath(other_generation), "site-claude", "Cookies"),
                                      os.path.join(os.path.realpath(container), "LOG")],
                 maps=["/usr/lib/libQt6WebEngineCore.so.6"])
    (_empty_proc / "self").symlink_to("10")
    (_empty_proc / "meminfo").write_text("")
    assert web_op(capsys, "remove-site", site="claude") == {"ok": True}
    assert names(container) == []
    assert names(other_generation) == ["site-claude"]


# Not "site-claude (deleted)": the kernel writes that for the deleted folder
# itself, so it counts (see below); no such sibling can exist (prune drops it).
@pytest.mark.parametrize("sibling", ["site-claude2", "site-claude-x", "site-claude.old", "site-claud"])
def test_a_sibling_with_the_same_prefix_does_not_count(data, capsys, mounted, _empty_proc, sibling):
    container = make_container(mounted, sites=("claude",), root_files=())
    base = os.path.join(os.path.realpath(container), sibling)
    fake_process(_empty_proc, 11, fds=[base, base + "/Cookies"], maps=[base + "/Cookies"])
    assert webdata.site_folder_in_use(site_path(mounted), proc_root=str(_empty_proc)) is False
    assert web_op(capsys, "remove-site", site="claude") == {"ok": True}
    assert names(container) == []


def test_a_sibling_site_id_is_not_busy_through_its_prefix(data, capsys, mounted, _empty_proc):
    # site-user-0000000c and site-user-0000000c0 can't both exist, but the
    # match must still stop at a path separator.
    container = make_container(mounted, sites=("claude", "chatgpt"), root_files=())
    fake_process(_empty_proc, 12, fds=[site_path(mounted, "chatgpt") + "/Cookies"])
    assert web_op(capsys, "remove-site", site="claude") == {"ok": True}
    assert web_op(capsys, "remove-site", site="chatgpt") == {"ok": False, "error": "busy"}
    assert names(container) == ["site-chatgpt"]


@pytest.mark.parametrize("where", ["fd", "maps"])
def test_a_deleted_but_still_open_file_counts(data, capsys, mounted, _empty_proc, where):
    container = make_container(mounted, sites=("claude",), root_files=())
    held = site_path(mounted) + "/IndexedDB/000003.log (deleted)"
    fake_process(_empty_proc, 13, **{"fds" if where == "fd" else "maps": [held]})
    assert web_op(capsys, "remove-site", site="claude") == {"ok": False, "error": "busy"}
    assert names(container) == ["site-claude"]


def test_a_deleted_site_folder_itself_counts(data, capsys, mounted, _empty_proc):
    container = make_container(mounted, sites=("claude",), root_files=())
    fake_process(_empty_proc, 14, fds=[site_path(mounted) + " (deleted)"])
    assert web_op(capsys, "remove-site", site="claude") == {"ok": False, "error": "busy"}
    assert names(container) == ["site-claude"]


def test_a_file_named_like_a_deleted_one_still_counts(data, mounted, _empty_proc):
    make_container(mounted, sites=("claude",), root_files=())
    fake_process(_empty_proc, 15, fds=[site_path(mounted) + "/x (deleted) (deleted)"])
    assert webdata.site_folder_in_use(site_path(mounted), proc_root=str(_empty_proc)) is True


def test_a_mapped_file_alone_makes_it_busy(data, capsys, mounted, _empty_proc):
    container = make_container(mounted, sites=("claude",), root_files=())
    fake_process(_empty_proc, 16, fds=["/dev/null"],
                 maps=[site_path(mounted) + "/GPUCache/data 1"])
    assert web_op(capsys, "remove-site", site="claude") == {"ok": False, "error": "busy"}
    assert names(container) == ["site-claude"]


def test_a_process_of_another_user_is_skipped(data, capsys, mounted, _empty_proc, monkeypatch):
    container = make_container(mounted, sites=("claude",), root_files=())
    foreign = fake_process(_empty_proc, 17, fds=[site_path(mounted) + "/Cookies"],
                           maps=[site_path(mounted) + "/Cookies"])
    real_owner = webdata._process_owner
    monkeypatch.setattr(webdata, "_process_owner",
                        lambda process: os.getuid() + 1 if process == str(foreign) else real_owner(process))
    assert web_op(capsys, "remove-site", site="claude") == {"ok": True}
    assert names(container) == []


def test_the_owner_comes_from_the_proc_entry(data, mounted, _empty_proc):
    make_container(mounted, sites=("claude",), root_files=())
    fake_process(_empty_proc, 18, fds=[site_path(mounted) + "/Cookies"])
    folder = site_path(mounted)
    assert webdata.site_folder_in_use(folder, proc_root=str(_empty_proc)) is True
    assert webdata.site_folder_in_use(folder, proc_root=str(_empty_proc), uid=os.getuid() + 1) is False


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any mode")
@pytest.mark.parametrize("closed", ["fd", "maps"])
def test_an_unreadable_process_of_ours_counts_as_busy(data, capsys, mounted, _empty_proc, closed):
    # Non-dumpable, or in a user namespace we can't inspect (review-3 L2):
    # it could hold the folder open, so nothing is deleted.
    container = make_container(mounted, sites=("claude",), root_files=())
    process = fake_process(_empty_proc, 19, fds=["/dev/null"], maps=["/usr/lib/libc.so.6"])
    (process / closed).chmod(0)
    try:
        assert web_op(capsys, "remove-site", site="claude") == {"ok": False, "error": "busy"}
    finally:
        (process / closed).chmod(0o700)
    assert names(container) == ["site-claude"]


@pytest.mark.parametrize("error", [PermissionError, lambda *a: OSError(errno.EPERM, "x")])
def test_an_unreadable_fd_folder_of_ours_counts_as_busy(data, capsys, mounted, _empty_proc, monkeypatch, error):
    container = make_container(mounted, sites=("claude",), root_files=())
    process = fake_process(_empty_proc, 23)
    real_listdir = os.listdir

    def listdir(path="."):
        if path == str(process / "fd"):
            raise error(errno.EACCES, "denied")
        return real_listdir(path)

    monkeypatch.setattr(os, "listdir", listdir)
    assert web_op(capsys, "remove-site", site="claude") == {"ok": False, "error": "busy"}
    assert names(container) == ["site-claude"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any mode")
def test_an_unreadable_process_of_another_user_is_skipped(data, capsys, mounted, _empty_proc):
    container = make_container(mounted, sites=("claude",), root_files=())
    process = fake_process(_empty_proc, 24, fds=[site_path(mounted) + "/Cookies"], uid=os.getuid() + 1)
    (process / "fd").chmod(0)
    (process / "maps").chmod(0)
    try:
        assert web_op(capsys, "remove-site", site="claude") == {"ok": True}
    finally:
        (process / "fd").chmod(0o700)
        (process / "maps").chmod(0o600)
    assert names(container) == []


@pytest.mark.parametrize("error", [errno.ENOENT, errno.ESRCH])
@pytest.mark.parametrize("where", ["fd", "maps", "link"])
def test_a_vanished_process_is_skipped(data, capsys, mounted, _empty_proc, monkeypatch, error, where):
    container = make_container(mounted, sites=("claude",), root_files=())
    process = fake_process(_empty_proc, 25, fds=[site_path(mounted) + "/Cookies"],
                           maps=[site_path(mounted) + "/Cookies"])
    real_listdir, real_readlink, real_open = os.listdir, os.readlink, open
    gone = OSError(error, os.strerror(error))

    def listdir(path="."):
        if where in ("fd", "maps") and path == str(process / "fd"):
            raise gone
        return real_listdir(path)

    def readlink(path, *args, **kwargs):
        if str(path).startswith(str(process)):
            raise gone
        return real_readlink(path, *args, **kwargs)

    def opener(path, *args, **kwargs):
        if str(path) == str(process / "maps"):
            raise gone
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "listdir", listdir)
    monkeypatch.setattr(os, "readlink", readlink)
    monkeypatch.setattr("builtins.open", opener)
    assert web_op(capsys, "remove-site", site="claude") == {"ok": True}
    assert names(container) == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any mode")
@pytest.mark.parametrize("uids", [
    lambda me: (me, 0, 0, 0),       # sudo: real uid ours, running as root
    lambda me: (me, 0, me, 0),      # a setuid-root program
    lambda me: (me, me, 0, me),     # saved uid root
    lambda me: (me, me, me, 0),     # fs uid root
])
def test_a_process_running_as_root_for_us_is_skipped_even_when_unreadable(
        data, capsys, mounted, _empty_proc, uids):
    container = make_container(mounted, sites=("claude",), root_files=())
    process = fake_process(_empty_proc, 33, fds=[site_path(mounted) + "/Cookies"], uids=uids(os.getuid()))
    (process / "fd").chmod(0)
    (process / "maps").chmod(0)
    try:
        assert web_op(capsys, "remove-site", site="claude") == {"ok": True}
    finally:
        (process / "fd").chmod(0o700)
        (process / "maps").chmod(0o600)
    assert names(container) == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any mode")
def test_a_non_dumpable_process_with_all_uids_ours_is_busy(data, capsys, mounted, _empty_proc):
    container = make_container(mounted, sites=("claude",), root_files=())
    me = os.getuid()
    process = fake_process(_empty_proc, 34, uids=(me, me, me, me))
    (process / "fd").chmod(0)
    try:
        assert web_op(capsys, "remove-site", site="claude") == {"ok": False, "error": "busy"}
    finally:
        (process / "fd").chmod(0o700)
    assert names(container) == ["site-claude"]


def test_a_status_with_too_few_uid_fields_is_skipped(data, mounted, _empty_proc):
    make_container(mounted, sites=("claude",), root_files=())
    fake_process(_empty_proc, 35, fds=[site_path(mounted) + "/Cookies"], uids=(os.getuid(),))
    assert webdata.site_folder_in_use(site_path(mounted), proc_root=str(_empty_proc)) is False


def test_the_real_uid_decides_not_the_proc_folder_owner(data, mounted, _empty_proc):
    make_container(mounted, sites=("claude",), root_files=())
    folder = site_path(mounted)
    # The folder is ours, but the real uid in status is someone else's: skipped.
    fake_process(_empty_proc, 26, fds=[folder + "/Cookies"], uid=os.getuid() + 1)
    assert webdata.site_folder_in_use(folder, proc_root=str(_empty_proc)) is False
    # A process with an unparsable or missing status is skipped too.
    odd = fake_process(_empty_proc, 27, fds=[folder + "/Cookies"])
    (odd / "status").write_text("Name:\tx\nUid:\tnot-a-number\n")
    missing = fake_process(_empty_proc, 28, fds=[folder + "/Cookies"])
    (missing / "status").unlink()
    assert webdata.site_folder_in_use(folder, proc_root=str(_empty_proc)) is False
    fake_process(_empty_proc, 29, fds=[folder + "/Cookies"])
    assert webdata.site_folder_in_use(folder, proc_root=str(_empty_proc)) is True


def test_gone_or_odd_process_entries_are_skipped(data, capsys, mounted, _empty_proc):
    container = make_container(mounted, sites=("claude",), root_files=())
    (_empty_proc / "30").mkdir()              # no fd, no maps: exited mid-scan
    (_empty_proc / "31").write_text("")       # not a directory
    dangling = fake_process(_empty_proc, 32)
    (dangling / "fd" / "3").mkdir()           # not a link
    assert web_op(capsys, "remove-site", site="claude") == {"ok": True}
    assert names(container) == []


def test_an_unreadable_proc_root_fails_closed(data, capsys, mounted, _empty_proc, monkeypatch):
    container = make_container(mounted, sites=("claude",), root_files=())
    monkeypatch.setattr(webdata, "PROC_ROOT", str(_empty_proc / "missing"))
    assert web_op(capsys, "remove-site", site="claude") == {"ok": False, "error": "os-error"}
    assert names(container) == ["site-claude"]


def test_a_missing_site_folder_is_success_without_a_scan(data, capsys, mounted, _empty_proc, monkeypatch):
    monkeypatch.setattr(webdata, "PROC_ROOT", str(_empty_proc / "missing"))
    assert web_op(capsys, "remove-site", site="claude") == {"ok": True}
    container = make_container(mounted, root_files=())
    assert web_op(capsys, "remove-site", site="claude") == {"ok": True}
    assert names(container) == []


def test_a_symlinked_site_name_is_unlinked_without_a_scan(data, capsys, tmp_path, mounted, _empty_proc, monkeypatch):
    target = outside_target(tmp_path)
    container = make_container(mounted, root_files=())
    (container / "site-claude").symlink_to(target)
    fake_process(_empty_proc, 40, fds=[str(target / "precious")])
    monkeypatch.setattr(webdata, "PROC_ROOT", str(_empty_proc / "missing"))
    assert web_op(capsys, "remove-site", site="claude") == {"ok": True}
    assert names(container) == []
    assert_target_intact(target)


def test_the_scan_runs_right_before_the_delete(data, capsys, mounted, monkeypatch):
    container = make_container(mounted, sites=("claude",), root_files=())
    calls = []
    real_scan, real_remove = webdata.site_folder_in_use, webdata.remove_entry
    monkeypatch.setattr(webdata, "site_folder_in_use",
                        lambda folder, **kw: calls.append(("scan", folder)) or real_scan(folder, **kw))
    monkeypatch.setattr(webdata, "remove_entry",
                        lambda parent, name: calls.append(("delete", name)) or real_remove(parent, name))
    assert web_op(capsys, "remove-site", site="claude") == {"ok": True}
    assert calls == [("scan", site_path(mounted)), ("delete", "site-claude")]
    assert names(container) == []


@pytest.mark.parametrize("swap", ["other-folder", "gone"])
def test_a_mismatched_container_path_deletes_nothing(data, capsys, tmp_path, mounted, monkeypatch, swap):
    # The scan needs the generation folder's path; it must name the folder
    # that is open, else nothing is deleted.
    container = make_container(mounted, sites=("claude",), root_files=())
    expected = str(container)
    real_stat = os.stat

    def stat_elsewhere(path, *args, **kwargs):
        if path == expected:
            if swap == "gone":
                raise FileNotFoundError(path)
            return real_stat(tmp_path, *args, **kwargs)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat_elsewhere)
    assert web_op(capsys, "remove-site", site="claude") == {"ok": False, "error": "os-error"}
    assert names(container) == ["site-claude"]


def test_busy_reply_never_contains_a_path(data, capsys, mounted, _empty_proc):
    make_container(mounted, sites=("claude",), root_files=())
    fake_process(_empty_proc, 50, fds=[site_path(mounted) + "/Cookies"])
    assert cli.main(["--web-data", "remove-site", *_SITE_BASE, "--site", "claude"]) == 0
    captured = capsys.readouterr()
    assert captured.out == '{"ok":false,"error":"busy"}\n'
    assert captured.err == ""


def test_the_default_proc_root_is_the_real_proc():
    import importlib.util

    spec = importlib.util.find_spec("hearthwire.core.webdata")
    assert 'PROC_ROOT = "/proc"' in Path(spec.origin).read_text(encoding="utf-8")


# --- review-3 L2: the LevelDB LOCK probe (fcntl and flock, never waiting) ---------------------


_HOLDER = """
import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDWR)
if sys.argv[2] == "fcntl":
    fcntl.lockf(fd, fcntl.LOCK_EX)
else:
    fcntl.flock(fd, fcntl.LOCK_EX)
print("held", flush=True)
sys.stdin.read()
"""


@contextmanager
def lock_held(path, kind="fcntl"):
    """Hold ``path`` locked in another process: POSIX locks are per process."""
    child = subprocess.Popen(
        [sys.executable, "-I", "-c", _HOLDER, str(path), kind],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env={"PATH": os.defpath},
    )
    try:
        assert child.stdout.readline() == "held\n"
        yield
    finally:
        child.stdin.close()
        child.wait(timeout=30)
        child.stdout.close()


def leveldb(folder, *parts):
    store = folder.joinpath(*parts)
    store.mkdir(parents=True, exist_ok=True)
    for name in ("LOCK", "LOG", "MANIFEST-000001", "000003.log"):
        (store / name).write_text("")
    return store / "LOCK"


@pytest.mark.parametrize("kind", ["fcntl", "flock"])
def test_a_held_leveldb_lock_makes_it_busy(data, capsys, mounted, kind):
    container = make_container(mounted, sites=("claude",), root_files=())
    lock = leveldb(container / "site-claude", "IndexedDB", "https_claude.ai_0.indexeddb.leveldb")
    with lock_held(lock, kind):
        assert web_op(capsys, "remove-site", site="claude") == {"ok": False, "error": "busy"}
        assert lock.exists()
        assert names(container) == ["site-claude"]
    # Released: the probe itself left no lock behind, and the delete works.
    assert web_op(capsys, "remove-site", site="claude") == {"ok": True}
    assert names(container) == []


def test_a_deeply_nested_lock_counts(data, capsys, mounted):
    container = make_container(mounted, sites=("claude",), root_files=())
    lock = leveldb(container / "site-claude", "Service Worker", "Database", "a", "b", "c")
    with lock_held(lock):
        assert web_op(capsys, "remove-site", site="claude") == {"ok": False, "error": "busy"}
    assert names(container) == ["site-claude"]


def test_free_locks_and_other_names_are_not_busy(data, capsys, mounted, tmp_path):
    container = make_container(mounted, sites=("claude", "gemini"), root_files=())
    leveldb(container / "site-claude", "Local Storage", "leveldb")
    leveldb(container / "site-claude", "IndexedDB", "x.leveldb")
    other = leveldb(container / "site-gemini", "Local Storage", "leveldb")
    held_elsewhere = container / "site-claude" / "LOCKED"
    held_elsewhere.write_text("")
    (container / "site-claude" / "LOCK.old").write_text("")
    with lock_held(other), lock_held(held_elsewhere):
        assert web_op(capsys, "remove-site", site="claude") == {"ok": True}
    assert names(container) == ["site-gemini"]


def test_a_symlinked_lock_is_never_probed_or_followed(data, capsys, tmp_path, mounted, monkeypatch):
    target = outside_target(tmp_path)
    held = target / "precious"
    container = make_container(mounted, sites=("claude",), root_files=())
    (container / "site-claude" / "LOCK").symlink_to(held)
    (container / "site-claude" / "db").symlink_to(target, target_is_directory=True)
    opened = []
    real_open = os.open
    monkeypatch.setattr(os, "open", lambda path, *a, **k: opened.append(path) or real_open(path, *a, **k))
    with lock_held(held):
        assert web_op(capsys, "remove-site", site="claude") == {"ok": True}
    assert "LOCK" not in opened and "db" not in opened
    assert names(container) == []
    assert_target_intact(target)


def test_a_lock_swapped_for_a_symlink_counts_as_held(data, mounted, tmp_path):
    folder = make_container(mounted, sites=("claude",), root_files=()) / "site-claude"
    (folder / "LOCK").symlink_to(outside_target(tmp_path) / "precious")
    descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    try:
        # As if the scan had seen a file: O_NOFOLLOW refuses the link (ELOOP).
        assert webdata._lock_is_held(descriptor, "LOCK") is True
        assert webdata._lock_is_held(descriptor, "missing") is False
    finally:
        os.close(descriptor)


def test_a_lock_swapped_for_a_fifo_counts_as_held_without_blocking(data, mounted):
    folder = make_container(mounted, sites=("claude",), root_files=()) / "site-claude"
    os.mkfifo(folder / "LOCK")
    descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert webdata._lock_is_held(descriptor, "LOCK") is True
    finally:
        os.close(descriptor)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any mode")
def test_an_unopenable_lock_counts_as_held(data, capsys, mounted):
    container = make_container(mounted, sites=("claude",), root_files=())
    lock = leveldb(container / "site-claude", "IndexedDB", "x.leveldb")
    lock.chmod(0o400)
    assert web_op(capsys, "remove-site", site="claude") == {"ok": False, "error": "busy"}
    assert lock.exists()
    lock.chmod(0o600)
    assert web_op(capsys, "remove-site", site="claude") == {"ok": True}


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any mode")
def test_an_unreadable_subfolder_counts_as_held(data, capsys, mounted):
    container = make_container(mounted, sites=("claude",), root_files=())
    hidden = container / "site-claude" / "IndexedDB"
    hidden.mkdir()
    hidden.chmod(0)
    try:
        assert web_op(capsys, "remove-site", site="claude") == {"ok": False, "error": "busy"}
    finally:
        hidden.chmod(0o700)
    assert names(container) == ["site-claude"]


def test_the_lock_walk_is_bounded(data, capsys, mounted, monkeypatch):
    container = make_container(mounted, sites=("claude",), root_files=())
    deep = container / "site-claude"
    for level in range(webdata.MAX_LOCK_DEPTH + 1):
        deep = deep / f"d{level}"
    deep.mkdir(parents=True)
    assert web_op(capsys, "remove-site", site="claude") == {"ok": False, "error": "os-error"}
    assert names(container) == ["site-claude"]
    monkeypatch.setattr(webdata, "MAX_LOCK_DEPTH", webdata.MAX_LOCK_DEPTH + 1)
    monkeypatch.setattr(webdata, "MAX_LOCK_ENTRIES", 5)
    assert web_op(capsys, "remove-site", site="claude") == {"ok": False, "error": "os-error"}
    monkeypatch.setattr(webdata, "MAX_LOCK_ENTRIES", 100)
    assert web_op(capsys, "remove-site", site="claude") == {"ok": True}
    assert names(container) == []


def test_the_lock_probe_closes_every_descriptor(data, capsys, mounted):
    container = make_container(mounted, sites=("claude",), root_files=())
    for index in range(5):
        leveldb(container / "site-claude", f"db{index}", "x.leveldb")
    before = len(os.listdir("/proc/self/fd"))
    descriptor = os.open(container / "site-claude", os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert webdata.site_locks_held(descriptor) is False
    finally:
        os.close(descriptor)
    assert len(os.listdir("/proc/self/fd")) == before


def test_the_order_is_proc_scan_then_lock_probe_then_delete(data, capsys, mounted, monkeypatch):
    container = make_container(mounted, sites=("claude",), root_files=())
    calls = []
    real_scan, real_locks, real_remove = webdata.site_folder_in_use, webdata.site_locks_held, webdata.remove_entry
    monkeypatch.setattr(webdata, "site_folder_in_use", lambda f, **k: calls.append("scan") or real_scan(f, **k))
    monkeypatch.setattr(webdata, "site_locks_held", lambda fd: calls.append("locks") or real_locks(fd))
    monkeypatch.setattr(webdata, "remove_entry", lambda p, n: calls.append("delete") or real_remove(p, n))
    assert web_op(capsys, "remove-site", site="claude") == {"ok": True}
    assert calls == ["scan", "locks", "delete"]
    assert names(container) == []


@pytest.mark.parametrize("argv", [
    ["--web-data", "prepare", "--store", "encrypted", "--applet", "2147483649", "--generation", "0"],
    ["--usage-history", "read", "--applet", "2147483649"],
    ["--usage-history", "read", "--applet", "0"],
    ["--web-data", "remove", "--store", "encrypted", "--applet", "0"],
])
def test_the_applet_bound_message_matches_the_accepted_range(data, capsys, argv):
    with pytest.raises(SystemExit):
        cli.main(argv)
    err = capsys.readouterr().err
    assert str(cli.MAX_INT_ARGUMENT) in err and cli.MAX_INT_ARGUMENT == 2**31
    assert "2147483647" not in err


def test_the_largest_applet_id_is_accepted_everywhere(data, capsys, mounted):
    top = str(cli.MAX_INT_ARGUMENT)
    assert prepare(capsys, top, 0) == {"ok": True}
    with pytest.raises(SystemExit):
        cli.main(["--usage-history", "read", "--applet", str(cli.MAX_INT_ARGUMENT + 1)])
    capsys.readouterr()
    assert cli.main(["--usage-history", "read", "--applet", top]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] in (True, False)
