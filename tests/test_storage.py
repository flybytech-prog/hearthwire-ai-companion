import os

from hearthwire.core.storage import atomic_write_private


def _leftover_temps(*directories):
    return [
        entry
        for directory in directories
        for entry in os.listdir(directory)
        if entry.endswith(".tmp")
    ]


def test_regular_file_is_replaced_privately(tmp_path):
    path = tmp_path / "nested" / "auth.json"
    assert atomic_write_private(path, "first")
    assert path.read_text() == "first"
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert os.stat(path.parent).st_mode & 0o777 == 0o700

    path.chmod(0o644)
    assert atomic_write_private(path, "second", expected_text="first")
    assert path.read_text() == "second"
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert not atomic_write_private(path, "third", expected_text="first")
    assert path.read_text() == "second"
    assert _leftover_temps(path.parent) == []


def test_missing_file_with_expected_text_creates_nothing(tmp_path):
    path = tmp_path / "missing" / "auth.json"
    assert not atomic_write_private(path, "new", expected_text="old")
    assert not path.parent.exists()


def test_symlink_is_preserved_and_target_is_written(tmp_path):
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    target = dotfiles / "auth.json"
    target.write_text("old")
    target.chmod(0o644)
    home = tmp_path / "home"
    home.mkdir()
    link = home / "auth.json"
    link.symlink_to(target)

    assert atomic_write_private(link, "new", expected_text="old")
    assert link.is_symlink()
    assert target.read_text() == "new"
    assert os.stat(target).st_mode & 0o777 == 0o600
    assert _leftover_temps(home, dotfiles) == []


def test_chained_symlinks_write_the_final_target(tmp_path):
    target = tmp_path / "real.json"
    target.write_text("old")
    middle = tmp_path / "middle.json"
    middle.symlink_to(target)
    link = tmp_path / "link.json"
    link.symlink_to(middle)

    assert atomic_write_private(link, "new", expected_text="old")
    assert link.is_symlink() and middle.is_symlink()
    assert target.read_text() == "new"


def test_symlink_compare_uses_target_contents(tmp_path):
    target = tmp_path / "real.json"
    target.write_text("concurrent")
    link = tmp_path / "link.json"
    link.symlink_to(target)

    assert not atomic_write_private(link, "new", expected_text="old")
    assert target.read_text() == "concurrent"
    assert link.is_symlink()


def test_dangling_symlink_is_refused(tmp_path):
    link = tmp_path / "link.json"
    missing = tmp_path / "gone" / "real.json"
    link.symlink_to(missing)

    assert not atomic_write_private(link, "new")
    assert not missing.exists()
    assert not missing.parent.exists()
    assert link.is_symlink()


def test_symlink_loop_is_refused(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.symlink_to(second)
    second.symlink_to(first)
    assert not atomic_write_private(first, "new")


def test_symlink_to_directory_is_refused(tmp_path):
    directory = tmp_path / "directory"
    directory.mkdir()
    link = tmp_path / "link.json"
    link.symlink_to(directory)

    assert not atomic_write_private(link, "new")
    assert os.listdir(directory) == []


def test_symlink_to_file_owned_by_someone_else_is_refused(tmp_path, monkeypatch):
    target = tmp_path / "real.json"
    target.write_text("old")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    real_uid = os.getuid()
    monkeypatch.setattr(os, "getuid", lambda: real_uid + 1)

    assert not atomic_write_private(link, "new", expected_text="old")
    assert target.read_text() == "old"
