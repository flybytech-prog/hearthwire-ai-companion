"""Opt-in usage history (core/usagehistory.py) and --usage-history."""

import ast
import fcntl
import json
import os
import stat
from pathlib import Path

import pytest

from hearthside import cli
from hearthside.core import usagehistory
from hearthside.core.catalog import PROVIDER_CATALOG

SOURCE = Path(usagehistory.__file__)
HOUR = 3600
NOW = 1_793_923_829  # Some second inside an hour bucket.
BUCKET = NOW - NOW % HOUR


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Every XDG base and HOME inside tmp_path; returns the history folder path."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "home").mkdir()
    return tmp_path / "data" / "hearthside" / "usage-history"


def record(sample, now=NOW, **kwargs):
    """record() as the CLI replies: a HelperError becomes its code."""
    try:
        return usagehistory.record(sample, clock=lambda: now, **kwargs)
    except usagehistory.HelperError as error:
        return {"ok": False, "error": error.code}


def read(now=NOW):
    return usagehistory.read(clock=lambda: now)


def cli_reply(capsys, *argv):
    assert cli.main(list(argv)) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    return json.loads(captured.out)


def write_history(folder, document):
    folder.mkdir(parents=True, exist_ok=True)
    folder.parent.chmod(0o700)
    folder.chmod(0o700)
    data = document if isinstance(document, (bytes, str)) else json.dumps(document)
    (folder / "history.json").write_bytes(data.encode() if isinstance(data, str) else data)


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
    assert sorted(os.listdir(home)) == ["history.json", "history.lock"]
    for name in ("history.json", "history.lock"):
        assert stat.S_IMODE((home / name).stat().st_mode) == 0o600
    assert read() == reply


def test_read_creates_nothing(home, tmp_path):
    assert read() == {"ok": True, "history_version": 1, "bucket_seconds": 3600, "now": NOW, "series": []}
    assert not (tmp_path / "data").exists()
    (tmp_path / "data" / "hearthside" / "usage-history").mkdir(parents=True)
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
    stored = json.loads((home / "history.json").read_text())
    assert len(stored["series"][0]["points"]) == 169
    # Read prunes too, without writing.
    before = (home / "history.json").read_bytes()
    assert len(points_of(read(now + 10 * HOUR), "claude", "session")) == 159
    assert (home / "history.json").read_bytes() == before


def test_future_points_are_dropped(home):
    write_history(home, {"history_version": 1, "series": [
        {"provider_id": "claude", "metric_id": "session", "points": [[BUCKET, 1], [BUCKET + HOUR, 2]]},
    ]})
    assert points_of(read(), "claude", "session") == [[BUCKET, 1]]
    record("codex.weekly=3")
    assert "%d" % (BUCKET + HOUR) not in (home / "history.json").read_text()


def test_nothing_is_written_when_nothing_changed(home):
    record("claude.session=10")
    before = os.stat(home / "history.json")
    record("claude.session=10", NOW + 5)
    after = os.stat(home / "history.json")
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)
    record("claude.session=11", NOW + 6)
    assert os.stat(home / "history.json").st_ino != before.st_ino


def test_writes_are_atomic_through_an_exclusive_temporary(home, monkeypatch):
    record("claude.session=10")
    seen = []
    real_open = os.open

    def watching_open(path, flags, *args, **kwargs):
        if str(path).startswith("history.json.") and flags & os.O_CREAT:
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
    assert replaced[0][1] == "history.json" and replaced[0][2] == ["dst_dir_fd", "src_dir_fd"]
    assert sorted(os.listdir(home)) == ["history.json", "history.lock"]


def test_a_failed_write_leaves_the_old_file_and_no_temporary(home, monkeypatch):
    record("claude.session=10")
    before = (home / "history.json").read_bytes()

    def failing_fsync(descriptor):
        raise OSError(5, "I/O")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    assert record("claude.session=11") == {"ok": False, "error": "os-error"}
    assert (home / "history.json").read_bytes() == before
    assert sorted(os.listdir(home)) == ["history.json", "history.lock"]


def test_stale_temporaries_are_removed_under_the_lock(home):
    record("claude.session=10")
    (home / "history.json.0123456789abcdef.tmp").write_text("junk")
    (home / "keep-me").write_text("x")
    record("claude.session=11")
    assert sorted(os.listdir(home)) == ["history.json", "history.lock", "keep-me"]


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
    assert json.loads((home / "history.json").read_text())["history_version"] == 1


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
    for operation in (lambda: record("claude.session=1"), lambda: usagehistory.run("read"),
                      lambda: usagehistory.run("clear")):
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


@pytest.mark.parametrize("name", ["history.json", "history.lock"])
def test_a_symlinked_file_is_refused(home, tmp_path, name):
    record("claude.session=1")
    target = tmp_path / "precious"
    target.write_text("keep")
    (home / name).unlink()
    (home / name).symlink_to(target)
    assert record("claude.session=2") == {"ok": False, "error": "symlink"}
    assert target.read_text() == "keep"
    if name == "history.json":
        assert usagehistory.run("read") == {"ok": False, "error": "symlink"}


def test_a_file_in_place_of_the_folder_is_refused(home):
    home.parent.mkdir(parents=True)
    home.write_text("x")
    assert record("claude.session=1") == {"ok": False, "error": "not-directory"}
    assert usagehistory.run("read") == {"ok": False, "error": "not-directory"}
    assert usagehistory.run("clear") == {"ok": False, "error": "not-directory"}
    assert home.read_text() == "x"


def test_someone_elses_folder_is_refused(home, monkeypatch):
    record("claude.session=1")
    monkeypatch.setattr(os, "getuid", lambda: os.geteuid() + 1)
    assert usagehistory.run("read") == {"ok": False, "error": "not-owned"}
    assert usagehistory.run("clear") == {"ok": False, "error": "not-owned"}


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
            usagehistory.clear(monotonic=lambda: clock[0], sleep=sleep)
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
    (home / "history.json.0123456789abcdef.tmp").write_text("junk")
    assert usagehistory.run("clear") == {"ok": True}
    assert not home.exists()
    assert home.parent.is_dir()
    assert read()["series"] == []


def test_clear_with_nothing_there_is_success_and_creates_nothing(home, tmp_path):
    assert usagehistory.run("clear") == {"ok": True}
    assert not (tmp_path / "data").exists()
    (tmp_path / "data" / "hearthside").mkdir(parents=True)
    assert usagehistory.run("clear") == {"ok": True}
    assert os.listdir(tmp_path / "data" / "hearthside") == []


# --- the CLI --------------------------------------------------------------------------------------


def test_cli_round_trip_prints_one_json_line(home, capsys, tmp_path):
    reply = cli_reply(capsys, "--usage-history", "record", "--sample", "claude.session=12")
    assert reply["ok"] is True and reply["series"][0]["points"][0][1] == 12
    assert cli_reply(capsys, "--usage-history", "read")["series"] == reply["series"]
    assert cli_reply(capsys, "--usage-history", "clear") == {"ok": True}
    assert cli_reply(capsys, "--usage-history", "read")["series"] == []


def test_cli_bad_sample_is_a_code_with_exit_0(home, capsys, tmp_path):
    assert cli_reply(capsys, "--usage-history", "record", "--sample", "claude.session=500") == \
        {"ok": False, "error": "bad-sample"}
    assert not (tmp_path / "data").exists()


def test_cli_replies_never_hold_a_path(home, capsys, tmp_path):
    home.parent.mkdir(parents=True)
    home.write_text("x")
    for argv in (["read"], ["clear"], ["record", "--sample", "claude.session=1"]):
        assert cli.main(["--usage-history", *argv]) == 0
        captured = capsys.readouterr()
        assert str(tmp_path) not in captured.out and captured.err == ""
        assert "Traceback" not in captured.out


def test_cli_turns_any_surprise_into_os_error(home, capsys, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError(str(home))

    monkeypatch.setattr(usagehistory, "read", boom)
    assert cli_reply(capsys, "--usage-history", "read") == {"ok": False, "error": "os-error"}


@pytest.mark.parametrize("argv", [
    ["--usage-history", "record"],
    ["--usage-history", "read", "--sample", "claude.session=1"],
    ["--usage-history", "clear", "--sample", "claude.session=1"],
    ["--sample", "claude.session=1"],
    ["--usage-history", "nope"],
    ["--usage-history", "read", "--json"],
    ["--usage-history", "read", "--providers", "claude"],
    ["--usage-history", "read", "--catalog"],
    ["--usage-history", "read", "--applet", "1"],
    ["--usage-history", "read", "--settings-backup", "status"],
    ["--usage-history", "read", "--port-owner", "11434"],
    ["--usage-history", "read", "--vault", "status"],
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
            assert node.module in ("catalog", "webdata"), node.module
    assert imported <= {"__future__", "collections", "contextlib", "errno", "fcntl", "json", "os", "re",
                        "stat", "time", "typing"}, imported
    for banned in ("socket", "http", "urllib", "ssl", "subprocess"):
        assert banned not in imported
