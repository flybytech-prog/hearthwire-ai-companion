"""``hearthwire --install-info``: where the helper and the widget are installed (docs/provider-contracts.md).

Every directory and os-release file is built in ``tmp_path``: the real site
directories, data directories and /etc/os-release are never read.
"""

import json
import os
from pathlib import Path

import pytest

from hearthwire import cli
from hearthwire.core import installinfo


PLUGIN = "io.github.flybytechprog.hearthwire"
REPLY_KEYS = ["ok", "install_info_version", "helper", "system_helper", "user_helper", "user_plasmoid",
              "system_plasmoid", "distro"]


@pytest.fixture
def places(tmp_path, monkeypatch):
    """Fake user and system site directories, data directories and os-release roots."""
    user_site = tmp_path / "home" / ".local" / "lib" / "python3.14" / "site-packages"
    system_site = tmp_path / "usr" / "lib" / "python3.14" / "site-packages"
    local_site = tmp_path / "usr" / "local" / "lib" / "python3.14" / "site-packages"
    for directory in (user_site, system_site, local_site):
        directory.mkdir(parents=True)
    monkeypatch.setattr(installinfo.site, "getusersitepackages", lambda: str(user_site))
    monkeypatch.setattr(installinfo.site, "getsitepackages",
                        lambda prefixes=None: [str(local_site), str(system_site)])
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_DIRS", raising=False)
    defaults = (tmp_path / "usr" / "local" / "share", tmp_path / "usr" / "share")
    monkeypatch.setattr(installinfo, "DEFAULT_DATA_DIRS", tuple(str(path) for path in defaults))
    etc = tmp_path / "etc"
    usr_lib = tmp_path / "usr" / "lib"
    etc.mkdir()
    monkeypatch.setattr(installinfo, "OS_RELEASE_PATHS", (str(etc / "os-release"), str(usr_lib / "os-release")))
    monkeypatch.setattr(installinfo, "OS_RELEASE_ROOTS", (str(etc), str(usr_lib)))
    # The running helper: a source checkout unless a test says otherwise.
    checkout = tmp_path / "checkout" / "src" / "hearthwire"
    checkout.mkdir(parents=True)
    monkeypatch.setattr(installinfo, "PACKAGE_DIRECTORY", checkout)
    monkeypatch.chdir(tmp_path)
    return {"user_site": user_site, "system_site": system_site, "local_site": local_site, "home": home,
            "data_home": home / ".local" / "share", "system_data": defaults[1], "local_data": defaults[0],
            "etc": etc, "usr_lib": usr_lib, "checkout": checkout}


def package(directory):
    (directory / "hearthwire").mkdir(parents=True, exist_ok=True)
    (directory / "hearthwire" / "__init__.py").write_text("")
    return directory / "hearthwire"


def plasmoid(data_directory):
    folder = data_directory / "plasma" / "plasmoids" / PLUGIN
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "metadata.json").write_text("{}")
    return folder


def os_release(places, text, where="etc"):
    path = places[where] / "os-release"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text if isinstance(text, bytes) else text.encode())
    return path


def reply(capsys):
    assert cli.main(["--install-info"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


# --- the reply ---------------------------------------------------------------------------------------


def test_the_reply_has_exactly_the_contract_keys_in_order(places, capsys):
    os_release(places, "ID=arch\n")
    result = reply(capsys)
    assert list(result) == REPLY_KEYS
    assert result == {"ok": True, "install_info_version": 1, "helper": "other", "system_helper": False,
                      "user_helper": False, "user_plasmoid": False, "system_plasmoid": False, "distro": "arch"}


def test_the_reply_never_holds_a_path_or_file_text(places, capsys, monkeypatch):
    package(places["user_site"])
    package(places["system_site"])
    plasmoid(places["data_home"])
    plasmoid(places["system_data"])
    os_release(places, 'ID=cachyos\nPRETTY_NAME="CachyOS Linux"\n')
    monkeypatch.setattr(installinfo, "PACKAGE_DIRECTORY", places["user_site"] / "hearthwire")
    raw = json.dumps(reply(capsys))
    for text in (str(places["home"]), "site-packages", "CachyOS", PLUGIN, "/"):
        assert text not in raw
    result = json.loads(raw)
    assert result["helper"] in installinfo.HELPER_PLACES and result["distro"] in installinfo.DISTROS
    assert all(isinstance(result[key], bool) for key in REPLY_KEYS[3:7])


def test_any_surprise_is_a_bare_error_code(places, capsys, monkeypatch):
    def broken():
        raise RuntimeError(str(places["home"]))
    monkeypatch.setattr(installinfo, "run", broken)
    assert cli.main(["--install-info"]) == 0
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ('{"ok":false,"error":"os-error"}\n', "")


@pytest.mark.parametrize("argv", [
    ["--install-info", "--json"], ["--install-info", "--catalog"], ["--install-info", "--detect"],
    ["--install-info", "--providers", "claude"], ["--install-info", "--applet", "1"],
    ["--install-info", "--port-owner", "11434"], ["--install-info", "--vault", "status"],
    ["--install-info", "--migrate", "status"], ["--install-info", "--usage-history", "read", "--applet", "1"],
    ["--install-info", "--store", "encrypted"],
])
def test_install_info_stands_alone(argv, capsys):
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 2
    assert capsys.readouterr().out == ""


# --- the helper ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(("where", "expected"), [("user_site", "user"), ("system_site", "system"),
                                                 ("local_site", "system"), ("checkout", "other")])
def test_helper_says_where_the_running_package_lives(places, capsys, monkeypatch, where, expected):
    running = places["checkout"] if where == "checkout" else package(places[where])
    monkeypatch.setattr(installinfo, "PACKAGE_DIRECTORY", running)
    assert reply(capsys)["helper"] == expected


def test_a_venv_is_other_and_its_site_packages_is_not_a_system_one(places, capsys, monkeypatch, tmp_path):
    venv_site = tmp_path / "venv" / "lib" / "python3.14" / "site-packages"
    running = package(venv_site)
    monkeypatch.setattr(installinfo.sys, "prefix", str(tmp_path / "venv"))
    monkeypatch.setattr(installinfo.sys, "base_prefix", str(tmp_path / "usr"))

    def site_packages(prefixes=None):
        if prefixes is None:
            return [str(venv_site)]
        return [str(places["system_site"])]
    monkeypatch.setattr(installinfo.site, "getsitepackages", site_packages)
    monkeypatch.setattr(installinfo, "PACKAGE_DIRECTORY", running)
    result = reply(capsys)
    assert (result["helper"], result["system_helper"]) == ("other", False)
    package(places["system_site"])
    assert reply(capsys)["system_helper"] is True


@pytest.mark.parametrize(("user", "system"), [(False, False), (True, False), (False, True), (True, True)])
def test_each_copy_is_found_in_its_own_site_directory(places, capsys, user, system):
    if user:
        package(places["user_site"])
    if system:
        package(places["system_site"])
    result = reply(capsys)
    assert (result["user_helper"], result["system_helper"]) == (user, system)


def test_a_copy_in_usr_local_counts_as_system(places, capsys):
    package(places["local_site"])
    assert reply(capsys)["system_helper"] is True


def test_the_copies_are_found_without_importing_them(places, capsys):
    marker = places["home"] / "imported"
    for directory in (places["user_site"], places["system_site"]):
        init = package(directory) / "__init__.py"
        init.write_text(f"open({str(marker)!r}, 'w').write('x')\n")
    result = reply(capsys)
    assert result["user_helper"] and result["system_helper"]
    assert not marker.exists()


def test_a_leftover_folder_without_init_is_not_a_copy(places, capsys):
    (places["user_site"] / "hearthwire" / "__pycache__").mkdir(parents=True)
    (places["system_site"] / "hearthwire").mkdir()
    result = reply(capsys)
    assert (result["user_helper"], result["system_helper"]) == (False, False)


@pytest.mark.parametrize("bad", ["", "relative/site-packages", "."])
def test_relative_and_empty_site_entries_are_ignored(places, capsys, monkeypatch, bad):
    # A relative entry would resolve against the working folder, which holds a copy.
    package(places["home"].parent)
    package(places["home"].parent / "relative" / "site-packages")
    monkeypatch.setattr(installinfo.site, "getusersitepackages", lambda: bad)
    monkeypatch.setattr(installinfo.site, "getsitepackages", lambda prefixes=None: [bad])
    result = reply(capsys)
    assert (result["user_helper"], result["system_helper"]) == (False, False)


def test_the_current_directory_is_never_searched(places, capsys, monkeypatch):
    package(places["user_site"])
    package(places["system_site"])
    monkeypatch.chdir(places["system_site"])
    result = reply(capsys)
    assert (result["user_helper"], result["system_helper"]) == (True, False)
    monkeypatch.chdir(places["user_site"])
    result = reply(capsys)
    assert (result["user_helper"], result["system_helper"]) == (False, True)


def test_a_user_site_that_is_also_listed_as_system_counts_as_user_only(places, capsys, monkeypatch):
    package(places["user_site"])
    monkeypatch.setattr(installinfo.site, "getsitepackages",
                        lambda prefixes=None: [str(places["user_site"]), str(places["system_site"])])
    result = reply(capsys)
    assert (result["user_helper"], result["system_helper"]) == (True, False)


# --- the widget ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("where", ["data_home", "system_data", "local_data"])
def test_each_default_plasmoid_location(places, capsys, where):
    plasmoid(places[where])
    result = reply(capsys)
    assert (result["user_plasmoid"], result["system_plasmoid"]) == (where == "data_home", where != "data_home")


def test_both_plasmoids(places, capsys):
    plasmoid(places["data_home"])
    plasmoid(places["system_data"])
    result = reply(capsys)
    assert (result["user_plasmoid"], result["system_plasmoid"]) == (True, True)


def test_xdg_data_home_replaces_the_default(places, capsys, monkeypatch, tmp_path):
    plasmoid(places["data_home"])
    data = tmp_path / "data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    assert reply(capsys)["user_plasmoid"] is False
    plasmoid(data)
    assert reply(capsys)["user_plasmoid"] is True


def test_a_relative_xdg_data_home_is_ignored(places, capsys, monkeypatch):
    plasmoid(places["data_home"])
    plasmoid(Path("data"))  # relative to the working folder
    monkeypatch.setenv("XDG_DATA_HOME", "data")
    assert reply(capsys)["user_plasmoid"] is True
    (places["data_home"] / "plasma" / "plasmoids" / PLUGIN / "metadata.json").unlink()
    assert reply(capsys)["user_plasmoid"] is False


def test_xdg_data_dirs_replaces_the_defaults_and_skips_relative_entries(places, capsys, monkeypatch, tmp_path):
    plasmoid(places["system_data"])
    other = tmp_path / "opt" / "share"
    monkeypatch.setenv("XDG_DATA_DIRS", f"relative:{tmp_path / 'flatpak'}:{other}:")
    assert reply(capsys)["system_plasmoid"] is False
    plasmoid(other)
    assert reply(capsys)["system_plasmoid"] is True
    plasmoid(Path("relative"))
    monkeypatch.setenv("XDG_DATA_DIRS", "relative")
    # Only relative entries: the defaults, which hold one.
    assert reply(capsys)["system_plasmoid"] is True


def test_an_empty_xdg_data_dirs_means_the_defaults(places, capsys, monkeypatch):
    plasmoid(places["local_data"])
    monkeypatch.setenv("XDG_DATA_DIRS", "")
    assert reply(capsys)["system_plasmoid"] is True


def test_the_data_home_listed_in_xdg_data_dirs_is_not_a_system_location(places, capsys, monkeypatch):
    plasmoid(places["data_home"])
    monkeypatch.setenv("XDG_DATA_DIRS", f"{places['data_home']}:{places['system_data']}")
    result = reply(capsys)
    assert (result["user_plasmoid"], result["system_plasmoid"]) == (True, False)


def test_metadata_must_be_a_regular_file(places, capsys):
    folder = places["data_home"] / "plasma" / "plasmoids" / PLUGIN
    (folder / "metadata.json").mkdir(parents=True)
    (places["system_data"] / "plasma" / "plasmoids" / PLUGIN).mkdir(parents=True)
    result = reply(capsys)
    assert (result["user_plasmoid"], result["system_plasmoid"]) == (False, False)


def test_a_linked_user_plasmoid_counts(places, capsys, tmp_path):
    target = plasmoid(tmp_path / "checkout-data")
    plasmoids = places["data_home"] / "plasma" / "plasmoids"
    plasmoids.mkdir(parents=True)
    (plasmoids / PLUGIN).symlink_to(target)
    assert reply(capsys)["user_plasmoid"] is True
    (target / "metadata.json").unlink()
    assert reply(capsys)["user_plasmoid"] is False


def test_without_a_usable_home_there_is_no_user_plasmoid(places, capsys, monkeypatch):
    plasmoid(places["data_home"])
    monkeypatch.setenv("HOME", "home")
    assert reply(capsys)["user_plasmoid"] is False


# --- the distribution ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("text", "expected"), [
    ("ID=arch\n", "arch"),
    ("ID=cachyos\nID_LIKE=arch\n", "arch"),
    ('ID="manjaro"\nID_LIKE="arch"\n', "arch"),
    ("ID=endeavouros\n", "arch"),
    ("ID=garuda\nID_LIKE=arch\n", "arch"),
    ("ID=biglinux\nID_LIKE='manjaro arch'\n", "arch"),
    ("ID=fedora\n", "fedora"),
    ('ID=nobara\nID_LIKE="rhel centos fedora"\n', "fedora"),
    ("ID=debian\n", "debian"),
    ("ID=ubuntu\nID_LIKE=debian\n", "debian"),
    ("ID=kubuntu\n", "debian"),
    ('ID=neon\nID_LIKE="ubuntu debian"\n', "debian"),
    ('ID=pop\nID_LIKE="ubuntu debian"\n', "debian"),
    ("ID=linuxmint\nID_LIKE=ubuntu\n", "debian"),
    ('ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n', "other"),
    ("ID=gentoo\n", "other"),
    ("ID_LIKE=debian\n", "debian"),
    ("NAME=Something\n", "other"),
    ("", "other"),
    # ID wins over ID_LIKE; the first known ID_LIKE word wins.
    ("ID=fedora\nID_LIKE=debian\n", "fedora"),
    ('ID=hybrid\nID_LIKE="suse fedora debian"\n', "fedora"),
    # IDs are lower case only.
    ("ID=Arch\n", "other"),
    ('ID="arch linux"\n', "other"),
    # Comments, blank lines, other keys, escapes and the last ID count as usual.
    ('# a comment\n\nNAME="Arch Linux"\nPRETTY_NAME="say \\"hi\\""\nID=debian\nID=arch\n', "arch"),
    ("ID=ubuntu\r\nID_LIKE=debian\r\n", "debian"),
])
def test_distro_mapping(places, capsys, text, expected):
    os_release(places, text)
    assert reply(capsys)["distro"] == expected


@pytest.mark.parametrize("text", [
    b"\x89PNG\r\n\x1a\n\x00\x00garbage",
    b"ID=arch\n\xff\xfe\n",
    b"ID=arch\x00\n",
    b"ID=arch\nthis is not an assignment\n",
    b"ID=arch\nexport FOO=1\n",
    b'ID=arch\nNAME="unterminated\n',
    b"ID=arch\nNAME='mixed\"\n",
    b'ID=arch\nNAME="a"b"\n',
    b'ID=arch\nNAME="ends with \\"\n',
    b"ID=arch\nNAME=two words\n",
    b"ID=arch\nNAME=$(reboot)\n",
    b"<html>ID=arch</html>\n",
])
def test_a_garbage_os_release_is_other(places, capsys, text):
    os_release(places, text)
    assert reply(capsys)["distro"] == "other"


def test_a_missing_os_release_is_other(places, capsys):
    assert reply(capsys)["distro"] == "other"


def test_usr_lib_os_release_is_the_fallback(places, capsys):
    os_release(places, "ID=fedora\n", where="usr_lib")
    assert reply(capsys)["distro"] == "fedora"


def test_etc_os_release_comes_first_and_a_bad_one_is_not_skipped(places, capsys):
    os_release(places, "ID=fedora\n", where="usr_lib")
    path = os_release(places, "ID=debian\n")
    assert reply(capsys)["distro"] == "debian"
    path.write_text("garbage line\n")
    assert reply(capsys)["distro"] == "other"


def test_an_oversized_os_release_is_other(places, capsys):
    os_release(places, "ID=arch\n" + "#" * (installinfo.MAX_OS_RELEASE_BYTES - 8) + "\n")
    assert reply(capsys)["distro"] == "other"


def test_an_os_release_of_exactly_the_cap_is_read(places, capsys):
    text = "ID=arch\n" + "#" * (installinfo.MAX_OS_RELEASE_BYTES - 9) + "\n"
    assert len(text) == installinfo.MAX_OS_RELEASE_BYTES
    os_release(places, text)
    assert reply(capsys)["distro"] == "arch"


def test_the_usual_link_into_usr_lib_is_followed(places, capsys):
    target = os_release(places, "ID=arch\n", where="usr_lib")
    (places["etc"] / "os-release").symlink_to(os.path.relpath(target, places["etc"]))
    assert reply(capsys)["distro"] == "arch"


def test_a_link_out_of_etc_and_usr_lib_is_refused(places, capsys, tmp_path):
    outside = tmp_path / "home" / "os-release"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("ID=arch\n")
    (places["etc"] / "os-release").symlink_to(outside)
    os_release(places, "ID=fedora\n", where="usr_lib")
    assert reply(capsys)["distro"] == "other"


def test_a_dangling_etc_link_falls_back_to_usr_lib(places, capsys):
    (places["etc"] / "os-release").symlink_to(places["usr_lib"] / "missing")
    os_release(places, "ID=fedora\n", where="usr_lib")
    assert reply(capsys)["distro"] == "fedora"


def test_a_fifo_or_folder_is_never_read(places, capsys):
    os.mkfifo(places["etc"] / "os-release")
    assert reply(capsys)["distro"] == "other"  # returns at once: opened non-blocking, then refused
    (places["etc"] / "os-release").unlink()
    (places["etc"] / "os-release").mkdir()
    assert reply(capsys)["distro"] == "other"
