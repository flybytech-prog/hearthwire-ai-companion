"""Opt-in usage history (core/usagehistory.py) and --usage-history."""

import ast
import fcntl
import json
import os
import stat
from pathlib import Path

import pytest

from hearthwire import cli
from hearthwire.core import usagehistory
from hearthwire.core.catalog import PROVIDER_CATALOG

SOURCE = Path(usagehistory.__file__)
HOUR = 3600
NOW = 1_793_923_829  # Some second inside an hour bucket.
BUCKET = NOW - NOW % HOUR
APPLET = 7
FILE = "applet-7.json"


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Every XDG base and HOME inside tmp_path; returns the history folder path."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "home").mkdir()
    return tmp_path / "data" / "hearthwire" / "usage-history"


def record(sample, now=NOW, applet=APPLET, **kwargs):
    """record() as the CLI replies: a HelperError becomes its code."""
    try:
        return usagehistory.record(applet, sample, clock=lambda: now, **kwargs)
    except usagehistory.HelperError as error:
        return {"ok": False, "error": error.code}


def read(now=NOW, applet=APPLET, **kwargs):
    try:
        return usagehistory.read(applet, clock=lambda: now, **kwargs)
    except usagehistory.HelperError as error:
        return {"ok": False, "error": error.code}


def run(operation, applet=APPLET, **kwargs):
    return usagehistory.run(operation, applet=applet, **kwargs)


def cli_reply(capsys, *argv):
    assert cli.main(list(argv)) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    return json.loads(captured.out)


def write_history(folder, document, name=FILE):
    folder.mkdir(parents=True, exist_ok=True)
    folder.parent.chmod(0o700)
    folder.chmod(0o700)
    data = document if isinstance(document, (bytes, str)) else json.dumps(document)
    (folder / name).write_bytes(data.encode() if isinstance(data, str) else data)


def points_of(reply, provider_id, metric_id):
    for entry in reply["series"]:
        if (entry["provider_id"], entry["metric_id"]) == (provider_id, metric_id):
            return entry["points"]
    return None


# --- the sample grammar ---------------------------------------------------------------------------


def test_pairs_are_every_catalog_percentage_in_catalog_order_without_extra_usage():
    expected = [(entry.provider_id, metric) for entry in PROVIDER_CATALOG
                for metric in entry.supported_metrics if metric != "extra_usage"]
    assert list(usagehistory.PAIRS) == expected
    assert ("claude", "extra_usage") not in usagehistory.PAIRS
    assert ("codex", "credits") in usagehistory.PAIRS  # A catalog percentage, kept.


def test_a_valid_sample_parses():
    assert usagehistory.parse_sample("claude.session=0,codex.weekly=100,grok.weekly=57") == {
        ("claude", "session"): 0, ("codex", "weekly"): 100, ("grok", "weekly"): 57,
    }


@pytest.mark.parametrize("sample", [
    "", ",", "claude.session=5,", ",claude.session=5", "claude.session=5,,codex.weekly=1",
    "claude.session=101", "claude.session=05", "claude.session=-1", "claude.session=+1", "claude.session=1.5",
    "claude.session= 5", "claude.session=5 ", " claude.session=5", "claude.session=5\n", "claude.session=",
    "claude.session", "claude=5", ".session=5", "claude.=5", "Claude.session=5", "claude.Session=5",
    "claude.session=٥", "claude-code.session=5", "claude.session=5;codex.weekly=1",
    "claude.extra_usage=5", "claude.spark=5", "nobody.session=5", "claude.nothing=5",
    "claude.session=5,claude.session=6", "a" * 33 + ".session=5", "claude." + "a" * 33 + "=5",
])
def test_bad_samples_are_refused(sample):
    assert usagehistory.parse_sample(sample) is None


def test_at_most_64_pairs(monkeypatch):
    # The catalog has fewer pairs; widen it so only the count rule can refuse.
    names = [f"p{chr(97 + index // 26)}{chr(97 + index % 26)}" for index in range(65)]
    pairs = {(name.replace("p", "p_"), "session"): index for index, name in enumerate(names)}
    monkeypatch.setattr(usagehistory, "_PAIR_ORDER", pairs)
    text = ",".join(f"{provider}.{metric}=1" for provider, metric in pairs)
    assert usagehistory.parse_sample(text) is None
    assert usagehistory.parse_sample(text.rsplit(",", 1)[0]) is not None


def test_a_non_string_sample_is_refused():
    assert usagehistory.parse_sample(None) is None


# --- record and read ------------------------------------------------------------------------------


def test_record_creates_private_folders_and_files_and_replies_with_the_series(home):
    reply = record("codex.weekly=7,claude.session=40")
    assert reply == {
        "ok": True, "history_version": 1, "bucket_seconds": 3600, "now": NOW,
        "series": [
            {"provider_id": "claude", "metric_id": "session", "points": [[BUCKET, 40]]},
            {"provider_id": "codex", "metric_id": "weekly", "points": [[BUCKET, 7]]},
        ],
    }
    assert stat.S_IMODE(home.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    assert sorted(os.listdir(home)) == [FILE, "history.lock"]
    for name in (FILE, "history.lock"):
        assert stat.S_IMODE((home / name).stat().st_mode) == 0o600
    assert read() == reply


def test_read_creates_nothing(home, tmp_path):
    assert read() == {"ok": True, "history_version": 1, "bucket_seconds": 3600, "now": NOW, "series": []}
    assert not (tmp_path / "data").exists()
    (tmp_path / "data" / "hearthwire" / "usage-history").mkdir(parents=True)
    assert read()["series"] == []
    assert os.listdir(home) == []


def test_one_value_per_hour_bucket_and_the_last_wins(home):
    record("claude.session=10", BUCKET)
    record("claude.session=20", BUCKET + HOUR - 1)
    reply = record("claude.session=30", BUCKET + HOUR)
    assert points_of(reply, "claude", "session") == [[BUCKET, 20], [BUCKET + HOUR, 30]]


def test_other_series_are_kept_when_one_is_recorded(home):
    record("claude.session=10,devin.daily=3")
    reply = record("claude.session=11")
    assert points_of(reply, "devin", "daily") == [[BUCKET, 3]]
    assert points_of(reply, "claude", "session") == [[BUCKET, 11]]


def test_only_seven_days_are_kept_and_at_most_169_points(home):
    for hour in range(200):
        record("claude.session=%d" % (hour % 101), BUCKET + hour * HOUR)
    now = BUCKET + 199 * HOUR
    points = points_of(read(now), "claude", "session")
    assert len(points) == usagehistory.MAX_POINTS == 169
    assert points[0][0] == now - 168 * HOUR and points[-1][0] == now
    stored = json.loads((home / FILE).read_text())
    assert len(stored["series"][0]["points"]) == 169
    # Reading within the hour writes nothing.
    before = os.stat(home / FILE)
    assert len(points_of(read(now + 5), "claude", "session")) == 169
    after = os.stat(home / FILE)
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)


def test_future_points_are_dropped(home):
    write_history(home, {"history_version": 1, "series": [
        {"provider_id": "claude", "metric_id": "session", "points": [[BUCKET, 1], [BUCKET + HOUR, 2]]},
    ]})
    assert points_of(read(), "claude", "session") == [[BUCKET, 1]]
    record("codex.weekly=3")
    assert "%d" % (BUCKET + HOUR) not in (home / FILE).read_text()


def test_nothing_is_written_when_nothing_changed(home):
    record("claude.session=10")
    before = os.stat(home / FILE)
    record("claude.session=10", NOW + 5)
    after = os.stat(home / FILE)
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)
    record("claude.session=11", NOW + 6)
    assert os.stat(home / FILE).st_ino != before.st_ino


def test_writes_are_atomic_through_an_exclusive_temporary(home, monkeypatch):
    record("claude.session=10")
    seen = []
    real_open = os.open

    def watching_open(path, flags, *args, **kwargs):
        if str(path).startswith(FILE + ".") and flags & os.O_CREAT:
            seen.append(flags)
        return real_open(path, flags, *args, **kwargs)

    real_replace = os.replace
    replaced = []

    def watching_replace(src, dst, **kwargs):
        replaced.append((src, dst, sorted(kwargs)))
        return real_replace(src, dst, **kwargs)

    monkeypatch.setattr(os, "open", watching_open)
    monkeypatch.setattr(os, "replace", watching_replace)
    record("claude.session=11")
    assert len(seen) == 1
    assert seen[0] & os.O_EXCL and seen[0] & os.O_NOFOLLOW
    assert replaced[0][1] == FILE and replaced[0][2] == ["dst_dir_fd", "src_dir_fd"]
    assert sorted(os.listdir(home)) == [FILE, "history.lock"]


def test_a_failed_write_leaves_the_old_file_and_no_temporary(home, monkeypatch):
    record("claude.session=10")
    before = (home / FILE).read_bytes()

    def failing_fsync(descriptor):
        raise OSError(5, "I/O")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    assert record("claude.session=11") == {"ok": False, "error": "os-error"}
    assert (home / FILE).read_bytes() == before
    assert sorted(os.listdir(home)) == [FILE, "history.lock"]


def test_stale_temporaries_are_removed_under_the_lock(home):
    record("claude.session=10")
    for name in ("history.json.0123456789abcdef.tmp", "applet-7.json.0123456789abcdef.tmp",
                 "applet-12.json.fedcba9876543210.tmp"):
        (home / name).write_text("junk")
    (home / "keep-me").write_text("x")
    (home / "applet-07.json.0123456789abcdef.tmp").write_text("not ours")
    record("claude.session=11")
    assert sorted(os.listdir(home)) == ["applet-07.json.0123456789abcdef.tmp", FILE, "history.lock", "keep-me"]


@pytest.mark.parametrize("content", [
    b"", b"not json", b"\xff\xfe", b"[]", b'{"history_version":2,"series":[]}',
    b'{"history_version":true,"series":[]}', b'{"history_version":1}',
    b'{"history_version":1,"series":{}}', b'{"history_version":1,"series":[],"extra":1}',
    b'{"history_version":1,"history_version":1,"series":[]}',
    b'{"history_version":1,"series":[{"provider_id":"claude","metric_id":"session","points":[[0,NaN]]}]}',
])
def test_a_corrupt_or_wrong_version_file_counts_as_empty(home, content):
    write_history(home, content)
    assert read()["series"] == []
    reply = record("claude.session=5")
    assert reply["series"] == [{"provider_id": "claude", "metric_id": "session", "points": [[BUCKET, 5]]}]
    assert json.loads((home / FILE).read_text())["history_version"] == 1


def test_an_oversized_file_counts_as_empty(home):
    good = {"history_version": 1, "series": [
        {"provider_id": "claude", "metric_id": "session", "points": [[BUCKET, 1]]}]}
    text = json.dumps(good)
    write_history(home, text + " " * (usagehistory.MAX_FILE_BYTES - len(text)))
    assert points_of(read(), "claude", "session") == [[BUCKET, 1]]
    write_history(home, text + " " * (usagehistory.MAX_FILE_BYTES - len(text) + 1))
    assert read()["series"] == []


def test_odd_points_and_unknown_series_are_skipped(home):
    write_history(home, {"history_version": 1, "series": [
        {"provider_id": "claude", "metric_id": "session",
         "points": [[BUCKET, 1], [BUCKET - HOUR, 101], [BUCKET - 2 * HOUR, True], [BUCKET - 1, 5],
                    [BUCKET - 3 * HOUR, 1.0], [BUCKET - 4 * HOUR], "x", [BUCKET - 5 * HOUR, 9]]},
        {"provider_id": "claude", "metric_id": "extra_usage", "points": [[BUCKET, 1]]},
        {"provider_id": ["claude"], "metric_id": "session", "points": [[BUCKET, 1]]},
        {"provider_id": "gone", "metric_id": "session", "points": [[BUCKET, 1]]},
        "junk",
    ]})
    assert read()["series"] == [
        {"provider_id": "claude", "metric_id": "session", "points": [[BUCKET - 5 * HOUR, 9], [BUCKET, 1]]},
    ]


def test_series_follow_the_catalog_order(home):
    reply = record("grok.weekly=1,devin.daily=2,claude.fable=3,claude.session=4,codex.spark=5")
    assert [(entry["provider_id"], entry["metric_id"]) for entry in reply["series"]] == [
        ("claude", "session"), ("claude", "fable"), ("codex", "spark"), ("devin", "daily"), ("grok", "weekly"),
    ]


def test_a_bad_sample_writes_nothing(home, tmp_path):
    assert record("claude.extra_usage=5") == {"ok": False, "error": "bad-sample"}
    assert not (tmp_path / "data").exists()


# --- refusals -------------------------------------------------------------------------------------


def test_a_symlinked_history_folder_is_refused(home, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    home.parent.mkdir(parents=True)
    home.symlink_to(elsewhere)
    for operation in (lambda: record("claude.session=1"), lambda: run("read"),
                      lambda: run("clear")):
        assert operation() == {"ok": False, "error": "symlink"}
    assert os.listdir(elsewhere) == []
    assert home.is_symlink()


def test_a_symlinked_app_folder_is_refused(home, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "data").mkdir()
    home.parent.symlink_to(elsewhere)
    assert record("claude.session=1") == {"ok": False, "error": "symlink"}
    assert os.listdir(elsewhere) == []


@pytest.mark.parametrize("name", [FILE, "history.lock"])
def test_a_symlinked_file_is_refused(home, tmp_path, name):
    record("claude.session=1")
    target = tmp_path / "precious"
    target.write_text("keep")
    (home / name).unlink()
    (home / name).symlink_to(target)
    assert record("claude.session=2") == {"ok": False, "error": "symlink"}
    assert target.read_text() == "keep"
    if name == FILE:
        assert run("read") == {"ok": False, "error": "symlink"}


def test_a_file_in_place_of_the_folder_is_refused(home):
    home.parent.mkdir(parents=True)
    home.write_text("x")
    assert record("claude.session=1") == {"ok": False, "error": "not-directory"}
    assert run("read") == {"ok": False, "error": "not-directory"}
    assert run("clear") == {"ok": False, "error": "not-directory"}
    assert home.read_text() == "x"


def test_someone_elses_folder_is_refused(home, monkeypatch):
    record("claude.session=1")
    monkeypatch.setattr(os, "getuid", lambda: os.geteuid() + 1)
    assert run("read") == {"ok": False, "error": "not-owned"}
    assert run("clear") == {"ok": False, "error": "not-owned"}


def test_a_held_lock_is_busy_after_two_seconds(home):
    record("claude.session=1")
    clock = [0.0]
    waited = []

    def sleep(seconds):
        waited.append(seconds)
        clock[0] += seconds

    holder = os.open(home / "history.lock", os.O_RDWR)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX)
        assert record("claude.session=2", monotonic=lambda: clock[0], sleep=sleep) == \
            {"ok": False, "error": "busy"}
        assert 1.9 <= sum(waited) <= 2.1
        try:
            usagehistory.clear(APPLET, monotonic=lambda: clock[0], sleep=sleep)
        except usagehistory.HelperError as error:
            assert error.code == "busy"
        else:
            pytest.fail("clear did not wait for the lock")
        assert points_of(read(), "claude", "session") == [[BUCKET, 1]]
        assert home.is_dir()
    finally:
        os.close(holder)
    assert record("claude.session=2")["ok"] is True


# --- clear ----------------------------------------------------------------------------------------


def test_clear_removes_the_files_and_the_folder(home):
    record("claude.session=1")
    (home / "applet-7.json.0123456789abcdef.tmp").write_text("junk")
    assert run("clear") == {"ok": True}
    assert not home.exists()
    assert home.parent.is_dir()
    assert read()["series"] == []


def test_clear_with_nothing_there_is_success_and_creates_nothing(home, tmp_path):
    for applet in (APPLET, None):
        assert usagehistory.run("clear", applet=applet, every_applet=applet is None) == {"ok": True}
        assert not (tmp_path / "data").exists()
    (tmp_path / "data" / "hearthwire").mkdir(parents=True)
    for applet in (APPLET, None):
        assert usagehistory.run("clear", applet=applet, every_applet=applet is None) == {"ok": True}
        assert os.listdir(tmp_path / "data" / "hearthwire") == []


# --- one file per widget (audit L1) and pruning on read (audit L2) ---------------------------------


LEGACY = {"history_version": 1, "series": [
    {"provider_id": "claude", "metric_id": "session", "points": [[BUCKET, 50]]}]}


def test_each_widget_has_its_own_file(home):
    record("claude.session=10", applet=7)
    record("claude.session=90,codex.weekly=1", applet=12)
    assert sorted(os.listdir(home)) == ["applet-12.json", FILE, "history.lock"]
    assert points_of(read(applet=7), "claude", "session") == [[BUCKET, 10]]
    assert points_of(read(applet=7), "codex", "weekly") is None
    assert points_of(read(applet=12), "claude", "session") == [[BUCKET, 90]]
    assert read(applet=13)["series"] == []
    for name in ("applet-12.json", FILE):
        assert stat.S_IMODE((home / name).stat().st_mode) == 0o600


def test_the_old_shared_file_is_never_read_as_a_widgets_history(home):
    write_history(home, LEGACY, name="history.json")
    assert read()["series"] == []
    assert record("codex.weekly=3")["series"] == [
        {"provider_id": "codex", "metric_id": "weekly", "points": [[BUCKET, 3]]}]
    assert (home / "history.json").exists()  # Only a clear deletes it.


@pytest.mark.parametrize("applet", [0, -1, 2**31 + 1, True, "7", 7.0, None])
def test_a_bad_applet_id_is_a_programming_error(home, applet):
    with pytest.raises(ValueError):
        usagehistory.file_name(applet)
    with pytest.raises(ValueError):
        usagehistory.record(applet, "claude.session=1")
    assert not home.exists()


def test_the_largest_applet_id_has_a_file():
    assert usagehistory.file_name(1) == "applet-1.json"
    assert usagehistory.file_name(2**31) == "applet-2147483648.json"


def test_run_needs_an_applet_or_all_for_clear(home):
    for operation, applet, every in (("read", None, False), ("read", 7, True), ("record", None, True),
                                     ("clear", None, False), ("clear", 7, True)):
        with pytest.raises(ValueError):
            usagehistory.run(operation, applet=applet, every_applet=every, sample="claude.session=1")


def test_clear_deletes_only_that_widgets_file_and_keeps_the_folder_for_others(home):
    record("claude.session=1", applet=7)
    record("claude.session=2", applet=12)
    assert run("clear", applet=7) == {"ok": True}
    assert sorted(os.listdir(home)) == ["applet-12.json", "history.lock"]
    assert points_of(read(applet=12), "claude", "session") == [[BUCKET, 2]]
    assert run("clear", applet=12) == {"ok": True}
    assert not home.exists()  # Nothing but the lock was left.
    assert home.parent.is_dir()


def test_any_clear_deletes_the_old_shared_file(home):
    record("claude.session=1", applet=12)
    write_history(home, LEGACY, name="history.json")
    (home / "history.json.0123456789abcdef.tmp").write_text("junk")
    assert run("clear", applet=7) == {"ok": True}  # Widget 7 had no file of its own.
    assert sorted(os.listdir(home)) == ["applet-12.json", "history.lock"]
    write_history(home, LEGACY, name="history.json")
    assert run("clear", applet=12) == {"ok": True}
    assert not home.exists()


def test_the_old_shared_file_alone_goes_with_its_folder(home):
    write_history(home, LEGACY, name="history.json")
    assert run("clear", applet=3) == {"ok": True}
    assert not home.exists()


def test_a_widget_clear_keeps_files_it_does_not_know(home):
    record("claude.session=1")
    (home / "keep-me").write_text("x")
    assert run("clear") == {"ok": True}
    assert sorted(os.listdir(home)) == ["history.lock", "keep-me"]


def test_clear_all_deletes_every_widgets_history_and_the_folder(home):
    for applet in (1, 7, 2**31):
        record("claude.session=1", applet=applet)
    write_history(home, LEGACY, name="history.json")
    (home / "keep-me").write_text("x")
    assert usagehistory.run("clear", every_applet=True) == {"ok": True}
    assert not home.exists()
    assert home.parent.is_dir()


def test_a_widget_clear_refuses_a_symlinked_folder_and_a_symlinked_file_is_only_unlinked(home, tmp_path):
    record("claude.session=1")
    target = tmp_path / "precious"
    target.write_text("keep")
    (home / FILE).unlink()
    (home / FILE).symlink_to(target)
    (home / "history.json").symlink_to(target)
    assert run("clear") == {"ok": True}
    assert target.read_text() == "keep"
    assert not home.exists()


def test_a_widget_clear_waits_for_the_lock(home):
    record("claude.session=1")
    clock = [0.0]

    def sleep(seconds):
        clock[0] += seconds

    holder = os.open(home / "history.lock", os.O_RDWR)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX)
        for applet in (APPLET, None):
            with pytest.raises(usagehistory.HelperError) as raised:
                usagehistory.clear(applet, monotonic=lambda: clock[0], sleep=sleep)
            assert raised.value.code == "busy"
        assert (home / FILE).exists()
    finally:
        os.close(holder)


def write_stale(home):
    """A file with one point older than seven days and one of the last hour."""
    write_history(home, {"history_version": 1, "series": [
        {"provider_id": "claude", "metric_id": "session", "points": [[BUCKET - 200 * HOUR, 1], [BUCKET - HOUR, 2]]}]})
    (home / "history.lock").touch(mode=0o600)


def test_read_rewrites_the_pruned_file_atomically_under_the_lock(home, monkeypatch):
    old = BUCKET - 200 * HOUR
    write_history(home, {"history_version": 1, "series": [
        {"provider_id": "claude", "metric_id": "session", "points": [[old, 5], [BUCKET - HOUR, 6]]},
        {"provider_id": "codex", "metric_id": "weekly", "points": [[old, 7], [BUCKET + HOUR, 8]]},
    ]})
    (home / "applet-7.json.0123456789abcdef.tmp").write_text("junk")
    (home / FILE).chmod(0o600)
    before = os.stat(home / FILE).st_ino
    locked, created, replaced = [], [], []
    real_flock, real_open, real_replace = fcntl.flock, os.open, os.replace

    def watching_flock(descriptor, operation):
        locked.append(operation)
        return real_flock(descriptor, operation)

    def watching_open(path, flags, *args, **kwargs):
        if str(path).startswith(FILE + ".") and flags & os.O_CREAT:
            created.append(flags)
        return real_open(path, flags, *args, **kwargs)

    def watching_replace(src, dst, **kwargs):
        replaced.append((dst, sorted(kwargs), list(locked)))
        return real_replace(src, dst, **kwargs)

    monkeypatch.setattr(fcntl, "flock", watching_flock)
    monkeypatch.setattr(os, "open", watching_open)
    monkeypatch.setattr(os, "replace", watching_replace)
    reply = read()
    assert reply["series"] == [{"provider_id": "claude", "metric_id": "session", "points": [[BUCKET - HOUR, 6]]}]
    assert len(created) == 1 and created[0] & os.O_EXCL and created[0] & os.O_NOFOLLOW
    assert replaced == [(FILE, ["dst_dir_fd", "src_dir_fd"], [fcntl.LOCK_EX | fcntl.LOCK_NB])]
    assert os.stat(home / FILE).st_ino != before
    assert json.loads((home / FILE).read_text()) == {"history_version": 1, "series": reply["series"]}
    assert stat.S_IMODE((home / FILE).stat().st_mode) == 0o600
    assert sorted(os.listdir(home)) == [FILE, "history.lock"]
    # Once pruned, reading changes nothing.
    stamp = os.stat(home / FILE)
    assert read() == reply
    assert (os.stat(home / FILE).st_ino, os.stat(home / FILE).st_mtime_ns) == (stamp.st_ino, stamp.st_mtime_ns)


def test_read_prunes_what_record_wrote_once_the_week_has_passed(home):
    for hour in range(3):
        record("claude.session=%d" % hour, BUCKET + hour * HOUR)
    later = BUCKET + (2 + 168) * HOUR
    assert points_of(read(later), "claude", "session") == [[BUCKET + 2 * HOUR, 2]]
    assert json.loads((home / FILE).read_text())["series"][0]["points"] == [[BUCKET + 2 * HOUR, 2]]


def test_read_deletes_the_file_when_nothing_of_the_last_seven_days_is_left(home):
    record("claude.session=1,codex.weekly=2", applet=7)
    record("claude.session=3", applet=12)
    later = BUCKET + 169 * HOUR
    assert read(later, applet=7)["series"] == []
    assert sorted(os.listdir(home)) == ["applet-12.json", "history.lock"]
    assert points_of(read(applet=12), "claude", "session") == [[BUCKET, 3]]  # Another widget's file stays.


@pytest.mark.parametrize("content", [b"not json", b'{"history_version":2,"series":[]}',
                                     b'{"history_version":1,"series":[]}'])
def test_read_deletes_a_file_with_nothing_usable(home, content):
    write_history(home, content)
    assert read()["series"] == []
    assert not (home / FILE).exists()


def test_read_with_nothing_to_prune_takes_no_lock_and_creates_nothing(home):
    record("claude.session=1")
    (home / "history.lock").unlink()
    assert points_of(read(NOW + 60), "claude", "session") == [[BUCKET, 1]]
    assert sorted(os.listdir(home)) == [FILE]


def test_a_held_lock_defers_pruning_but_not_the_reply(home):
    write_stale(home)
    before = (home / FILE).read_bytes()
    clock = [0.0]

    def sleep(seconds):
        clock[0] += seconds

    holder = os.open(home / "history.lock", os.O_RDWR)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX)
        reply = read(monotonic=lambda: clock[0], sleep=sleep)
        assert points_of(reply, "claude", "session") == [[BUCKET - HOUR, 2]]
        assert clock[0] >= 2.0
        assert (home / FILE).read_bytes() == before
    finally:
        os.close(holder)
    assert points_of(read(), "claude", "session") == [[BUCKET - HOUR, 2]]
    assert (home / FILE).read_bytes() != before


def test_a_failed_prune_leaves_the_file_and_no_temporary(home, monkeypatch):
    write_stale(home)
    before = (home / FILE).read_bytes()

    def failing_fsync(descriptor):
        raise OSError(5, "I/O")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    assert read() == {"ok": False, "error": "os-error"}
    assert (home / FILE).read_bytes() == before
    assert sorted(os.listdir(home)) == [FILE, "history.lock"]


def test_read_refuses_a_symlinked_lock_when_it_has_to_prune(home, tmp_path):
    write_stale(home)
    target = tmp_path / "precious"
    target.write_text("keep")
    (home / "history.lock").unlink()
    (home / "history.lock").symlink_to(target)
    assert read() == {"ok": False, "error": "symlink"}
    assert target.read_text() == "keep"


# --- the CLI --------------------------------------------------------------------------------------


def test_cli_round_trip_prints_one_json_line(home, capsys, tmp_path):
    reply = cli_reply(capsys, "--usage-history", "record", "--applet", "7", "--sample", "claude.session=12")
    assert reply["ok"] is True and reply["series"][0]["points"][0][1] == 12
    assert cli_reply(capsys, "--usage-history", "read", "--applet", "7")["series"] == reply["series"]
    assert cli_reply(capsys, "--usage-history", "read", "--applet", "8")["series"] == []
    assert cli_reply(capsys, "--usage-history", "clear", "--applet", "7") == {"ok": True}
    assert cli_reply(capsys, "--usage-history", "read", "--applet", "7")["series"] == []
    cli_reply(capsys, "--usage-history", "record", "--applet", "2147483648", "--sample", "claude.session=1")
    assert sorted(os.listdir(home)) == ["applet-2147483648.json", "history.lock"]
    assert cli_reply(capsys, "--usage-history", "clear", "--all") == {"ok": True}
    assert not home.exists()


def test_cli_bad_sample_is_a_code_with_exit_0(home, capsys, tmp_path):
    assert cli_reply(capsys, "--usage-history", "record", "--applet", "7", "--sample", "claude.session=500") == \
        {"ok": False, "error": "bad-sample"}
    assert not (tmp_path / "data").exists()


def test_cli_replies_never_hold_a_path(home, capsys, tmp_path):
    home.parent.mkdir(parents=True)
    home.write_text("x")
    for argv in (["read", "--applet", "7"], ["clear", "--applet", "7"], ["clear", "--all"],
                 ["record", "--applet", "7", "--sample", "claude.session=1"]):
        assert cli.main(["--usage-history", *argv]) == 0
        captured = capsys.readouterr()
        assert str(tmp_path) not in captured.out and captured.err == ""
        assert "Traceback" not in captured.out


def test_cli_turns_any_surprise_into_os_error(home, capsys, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError(str(home))

    monkeypatch.setattr(usagehistory, "read", boom)
    assert cli_reply(capsys, "--usage-history", "read", "--applet", "7") == {"ok": False, "error": "os-error"}


@pytest.mark.parametrize("argv", [
    ["--usage-history", "record", "--applet", "7"],
    ["--usage-history", "read", "--applet", "7", "--sample", "claude.session=1"],
    ["--usage-history", "clear", "--applet", "7", "--sample", "claude.session=1"],
    ["--sample", "claude.session=1"],
    ["--usage-history", "nope", "--applet", "7"],
    ["--usage-history", "read", "--applet", "7", "--json"],
    ["--usage-history", "read", "--applet", "7", "--providers", "claude"],
    ["--usage-history", "read", "--applet", "7", "--catalog"],
    ["--usage-history", "read", "--applet", "7", "--settings-backup", "status"],
    ["--usage-history", "read", "--applet", "7", "--port-owner", "11434"],
    ["--usage-history", "read", "--applet", "7", "--vault", "status"],
    ["--usage-history", "read", "--applet", "7", "--store", "encrypted"],
    ["--usage-history", "read", "--applet", "7", "--generation", "1"],
    # The widget id (audit L1).
    ["--usage-history", "read"],
    ["--usage-history", "record", "--sample", "claude.session=1"],
    ["--usage-history", "clear"],
    ["--usage-history", "read", "--applet", "0"],
    ["--usage-history", "read", "--applet", "2147483649"],
    ["--usage-history", "read", "--applet", "-1"],
    ["--usage-history", "read", "--applet", "07x"],
    ["--usage-history", "read", "--applet", " 7"],
    ["--usage-history", "read", "--applet", "12345678901"],
    ["--usage-history", "read", "--all"],
    ["--usage-history", "record", "--all", "--sample", "claude.session=1"],
    ["--usage-history", "clear", "--all", "--applet", "7"],
    ["--all"],
    ["--settings-backup", "status", "--all"],
])
def test_cli_argument_rules_exit_2(home, capsys, argv):
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 2
    assert capsys.readouterr().out == ""


# --- the module -----------------------------------------------------------------------------------


def test_the_module_imports_only_the_standard_library_and_no_network():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and not node.level:
            imported.add((node.module or "").split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            assert node.module in ("catalog", "webdata", "legacy"), node.module  # legacy: only legacy-data
    assert imported <= {"__future__", "collections", "contextlib", "errno", "fcntl", "json", "os", "re",
                        "stat", "time", "typing"}, imported
    for banned in ("socket", "http", "urllib", "ssl", "subprocess"):
        assert banned not in imported
