"""The run-time distribution of the model table (brief D9; AC 8): downloaded, cached, fallen back.

`zylch/llm/roles/distribution.py` downloads `table.json` and `snapshot.json`
from the data branch (ETag), checks them with the static gates, caches them in
the profile's own directory and falls back to the last good copy, then to the
build copies. Here every download goes through a fake fetcher (no network):
the "published" documents are the fixture ones (`model_table_fixture`),
reordered or re-priced where a test needs a copy that differs from what is in
force, and the build copies are the fixture's too (`build` fixture), so no
expectation moves with the coordinator's refreshes.
"""

from __future__ import annotations

import copy
import json
import threading
from decimal import Decimal

import pytest

from zylch.llm.roles import catalogue, distribution, gates, table

from . import model_table_fixture as fixture

URL = "https://raw.githubusercontent.com/hahnbanach/mrcall-desktop/model-table/v1/{}"


class Published:
    """A fake data branch: ``{name: (document or raw bytes, etag)}``, every GET recorded."""

    def __init__(self, **files):
        self.files = {name.replace("_", "."): value for name, value in files.items()}
        self.calls: list[tuple[str, str | None]] = []
        self.blocked = False

    def __call__(self, url, etag):
        self.calls.append((url, etag))
        if self.blocked:
            raise OSError("connection refused (blocked egress)")
        name = url.rsplit("/", 1)[1]
        body, tag = self.files[name]
        if isinstance(body, int):
            return body, None, None
        if etag is not None and etag == tag:
            return 304, None, tag
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        return 200, data, tag


def reordered(record: dict) -> dict:
    """The fixture table with every ranking reversed: a different, valid decision."""
    record = copy.deepcopy(record)
    for body in record["presets"].values():
        for rankings in body["roles"].values():
            rankings["ranking"].reverse()
            rankings["anthropic_ranking"].reverse()
    return gates.stamped(record)


def repriced(snap: dict, model: str, output: str) -> dict:
    snap = copy.deepcopy(snap)
    snap["models"][model]["pricing"]["output"] = output
    return gates.stamped(snap)


def restart():
    """What a new engine process starts with: the build copies in force."""
    table.set_table(None)
    catalogue.set_layers()
    distribution._sources.update(snapshot="build", table="build")


@pytest.fixture
def build(monkeypatch, tmp_path):
    """The build copies are the fixture's: the snapshot, and the table in a temp file."""
    snap, record = fixture.doc("snapshot.json"), fixture.doc("table.json")
    built = tmp_path / "build-table.json"
    built.write_text(json.dumps(record))
    monkeypatch.setattr(catalogue, "_build", lambda: snap)
    monkeypatch.setattr(table, "BUILD", built)
    monkeypatch.setattr(distribution, "_sources", {"snapshot": "build", "table": "build"})
    table._build.cache_clear()
    restart()
    yield {"snapshot": snap, "table": record}
    table._build.cache_clear()


@pytest.fixture
def profile(tmp_path):
    directory = tmp_path / "profile"
    directory.mkdir()
    return directory


def cached(profile) -> dict[str, bytes]:
    folder = profile / "model-table"
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir())} if folder.exists() else {}


def test_a_downloaded_table_and_snapshot_are_used_and_cached_in_the_profile(build, profile):
    newer_table = reordered(build["table"])
    newer_snapshot = repriced(build["snapshot"], fixture.K3, "14")
    branch = Published(table_json=(newer_table, '"t1"'), snapshot_json=(newer_snapshot, '"s1"'))
    assert distribution.refresh(profile, fetch=branch) == {
        "snapshot": "downloaded",
        "table": "downloaded",
    }
    assert [url for url, _ in branch.calls] == [
        URL.format("snapshot.json"),
        URL.format("table.json"),
    ]
    assert table.document() == newer_table
    assert table.pick("economy", "CHAT", "openrouter") == fixture.SONNET5  # reversed
    assert catalogue.layers() == (newer_snapshot, build["snapshot"])
    assert catalogue.rates(fixture.K3, "openrouter") == (Decimal("2.7"), Decimal("14"))
    # Cached in the profile's own directory, and only there.
    files = cached(profile)
    assert set(files) == {"table.json", "snapshot.json", "etags.json"}
    assert json.loads(files["table.json"]) == newer_table
    assert json.loads(files["etags.json"]) == {"snapshot.json": '"s1"', "table.json": '"t1"'}
    assert sorted(p.name for p in profile.iterdir()) == ["model-table"]


def test_an_unchanged_file_costs_a_304_and_keeps_the_copy_in_force(build, profile):
    newer_table = reordered(build["table"])
    branch = Published(table_json=(newer_table, '"t1"'), snapshot_json=(build["snapshot"], '"s1"'))
    distribution.refresh(profile, fetch=branch)
    before = cached(profile)
    branch.calls.clear()
    distribution.refresh(profile, fetch=branch)
    assert branch.calls == [
        (URL.format("snapshot.json"), '"s1"'),
        (URL.format("table.json"), '"t1"'),
    ]
    assert cached(profile) == before and table.document() == newer_table


def test_a_blocked_download_uses_the_last_good_copy_then_the_build_copies(build, profile, tmp_path):
    newer_table = reordered(build["table"])
    newer_snapshot = repriced(build["snapshot"], fixture.K3, "14")
    branch = Published(table_json=(newer_table, '"t1"'), snapshot_json=(newer_snapshot, '"s1"'))
    distribution.refresh(profile, fetch=branch)
    # A restart: nothing in memory; the last good copy comes back from disk alone.
    restart()
    assert distribution.load(profile) == {"snapshot": "cached", "table": "cached"}
    assert table.document() == newer_table and catalogue.layers()[0] == newer_snapshot
    # The download is blocked: the last good copy stays in force, untouched.
    branch.blocked = True
    before = cached(profile)
    assert distribution.refresh(profile, fetch=branch) == {"snapshot": "cached", "table": "cached"}
    assert cached(profile) == before and table.document() == newer_table
    # A profile with no last good copy, after a restart, and a blocked download:
    # the build copies (loading nothing leaves what the process started with).
    other = tmp_path / "other-profile"
    other.mkdir()
    restart()
    assert distribution.load(other) == {"snapshot": "build", "table": "build"}
    assert distribution.refresh(other, fetch=branch) == {"snapshot": "build", "table": "build"}
    assert table.document() == build["table"] and catalogue.layers() == (build["snapshot"],)
    assert cached(other) == {}


def test_an_old_table_is_used_while_it_passes_the_gates(build, profile):
    """The job restamps table.json only when a decision changes: a table resolved
    long ago, published with today's snapshot, is a valid copy, never refused or
    replaced by the build copy for its age (a copy's age is its snapshot's read_at)."""
    old = copy.deepcopy(build["table"])
    old.update(resolved_at="2020-01-01T00:00:00Z", catalogue_read_at="2020-01-01T00:00:00Z")
    old = reordered(gates.stamped(old))
    branch = Published(table_json=(old, '"t1"'), snapshot_json=(build["snapshot"], '"s1"'))
    assert distribution.refresh(profile, fetch=branch)["table"] == "downloaded"
    assert table.document() == old
    restart()
    assert distribution.load(profile)["table"] == "cached" and table.document() == old


def test_loading_a_profile_with_nothing_cached_leaves_the_copies_in_force(build, profile):
    """At engine start that is the build copies; nothing is reset to them later."""
    in_force = reordered(build["table"])
    table.set_table(in_force)
    distribution.load(profile)
    assert table.document() == in_force and cached(profile) == {}


def test_without_any_table_every_pick_pauses_rather_than_guessing(build, monkeypatch, profile):
    monkeypatch.setattr(table, "BUILD", profile / "absent.json")
    table._build.cache_clear()
    distribution.load(profile)
    assert table.document() is None
    with pytest.raises(table.BudgetError, match="no valid model table"):
        table.pick("economy", "CHAT", "openrouter")


def _tampered_snapshot(snap):
    snap = copy.deepcopy(snap)
    snap["models"][fixture.QWEN]["pricing"]["output"] = "0.01"  # version no longer matches
    return snap


def _uncovered_table(record):
    record = copy.deepcopy(record)
    del record["presets"]["economy"]["roles"]["DEDUP"]
    return gates.stamped(record)


def _haiku_table(record):
    record = copy.deepcopy(record)
    haiku = {"id": fixture.HAIKU, "direct_id": "claude-haiku-4-5"}
    record["presets"]["economy"]["roles"]["CHAT"]["ranking"].insert(0, haiku)
    return gates.stamped(record)


def _unpriced_table(record):
    record = copy.deepcopy(record)
    unknown = {"id": "vendor/unknown-model", "direct_id": None}
    record["presets"]["economy"]["roles"]["CHAT"]["ranking"].insert(0, unknown)
    return gates.stamped(record)


@pytest.mark.parametrize(
    "bad, which",
    [
        (lambda b: {"snapshot_json": (500, None)}, "snapshot"),
        (lambda b: {"snapshot_json": (b"<html>not json</html>", '"x"')}, "snapshot"),
        (lambda b: {"snapshot_json": (_tampered_snapshot(b["snapshot"]), '"x"')}, "snapshot"),
        (lambda b: {"table_json": (404, None)}, "table"),
        (lambda b: {"table_json": (b'{"schema": 1', '"x"')}, "table"),
        (lambda b: {"table_json": (_uncovered_table(b["table"]), '"x"')}, "table"),
        (lambda b: {"table_json": (_haiku_table(b["table"]), '"x"')}, "table"),
        (lambda b: {"table_json": (_unpriced_table(b["table"]), '"x"')}, "table"),
    ],
    ids=[
        "http-500",
        "not-json",
        "bad-version",
        "http-404",
        "truncated",
        "uncovered",
        "haiku",
        "unpriced",
    ],
)
def test_a_bad_download_never_replaces_the_last_good_copy(build, profile, bad, which):
    good_table, good_snapshot = reordered(build["table"]), repriced(
        build["snapshot"], fixture.K3, "14"
    )
    branch = Published(table_json=(good_table, '"t1"'), snapshot_json=(good_snapshot, '"s1"'))
    distribution.refresh(profile, fetch=branch)
    before = cached(profile)
    branch.files.update({k.replace("_", "."): v for k, v in bad(build).items()})
    distribution.refresh(profile, fetch=branch)
    assert cached(profile) == before
    assert table.document() == good_table and catalogue.layers()[0] == good_snapshot
    assert distribution.sources()[which] in ("cached", "downloaded")


def test_a_bad_cached_copy_is_ignored_and_fetched_again_in_full(build, profile):
    good_table = reordered(build["table"])
    branch = Published(table_json=(good_table, '"t1"'), snapshot_json=(build["snapshot"], '"s1"'))
    distribution.refresh(profile, fetch=branch)
    (profile / "model-table" / "table.json").write_text('{"schema": 1, "presets": {}}')
    assert distribution.load(profile)["table"] == "build"
    assert table.document() == build["table"]
    branch.calls.clear()
    distribution.refresh(profile, fetch=branch)
    assert (URL.format("table.json"), None) in branch.calls  # no ETag for a copy not held good
    assert table.document() == good_table


def test_a_newer_snapshot_keeps_the_one_it_replaces_as_a_layer(build, profile):
    first = repriced(build["snapshot"], fixture.K3, "14")
    branch = Published(table_json=(build["table"], '"t1"'), snapshot_json=(first, '"s1"'))
    distribution.refresh(profile, fetch=branch)
    second = copy.deepcopy(first)
    del second["models"][fixture.OPUS5]  # gone from the newer catalogue
    del second["direct"]["claude-opus-5"]
    second["models"][fixture.K3]["pricing"]["output"] = "15"
    second = gates.stamped(second)
    branch.files["snapshot.json"] = (second, '"s2"')
    assert distribution.refresh(profile, fetch=branch)["snapshot"] == "downloaded"
    assert catalogue.layers() == (second, first, build["snapshot"])
    assert catalogue.rates(fixture.K3, "openrouter")[1] == Decimal("15")  # the newest first
    # The older copy keeps a price for an id only it knows (brief D5).
    assert catalogue.rates(fixture.OPUS5, "openrouter") == (Decimal(5), Decimal(25))
    assert catalogue.rates("claude-opus-5", "direct") == (Decimal(5), Decimal(25))
    assert json.loads(cached(profile)["snapshot.previous.json"]) == first
    table.set_table(None)
    catalogue.set_layers()
    distribution.load(profile)
    assert catalogue.layers() == (second, first, build["snapshot"])


def test_no_profile_directory_downloads_nothing(build, monkeypatch):
    monkeypatch.delenv("ZYLCH_PROFILE_DIR", raising=False)
    branch = Published(
        table_json=(build["table"], '"t1"'), snapshot_json=(build["snapshot"], '"s1"')
    )
    assert distribution.cache_dir() is None
    distribution.refresh(fetch=branch)
    assert branch.calls == []


def test_start_loads_now_and_downloads_in_the_background(build, monkeypatch, profile):
    newer_table = reordered(build["table"])
    done = threading.Event()

    class Branch(Published):
        def __call__(self, url, etag):
            answer = super().__call__(url, etag)
            if url.endswith("table.json"):
                done.set()
            return answer

    branch = Branch(table_json=(newer_table, '"t1"'), snapshot_json=(build["snapshot"], '"s1"'))
    monkeypatch.setattr(distribution, "_fetch", branch)
    monkeypatch.setattr(distribution, "_thread", None)
    try:
        distribution.start(profile)
        assert done.wait(10)
        distribution._stop.set()
        distribution._thread.join(10)
        assert not distribution._thread.is_alive()
        assert table.document() == newer_table
        assert distribution.sources()["table"] == "downloaded"
    finally:
        distribution._stop.set()
        distribution._stop.clear()


def test_activating_a_profile_starts_the_distribution_on_its_directory(monkeypatch, tmp_path):
    import zylch.config as config
    from zylch.cli import profiles

    started = []
    monkeypatch.setattr(distribution, "start", lambda directory: started.append(directory))
    monkeypatch.setattr(profiles, "PROFILES_DIR", str(tmp_path))
    monkeypatch.setattr(profiles, "_active_profile", None)
    monkeypatch.setattr(profiles, "_active_profile_dir", None)
    monkeypatch.setattr(config, "settings", config.settings)
    for key in ("ZYLCH_DB_PATH", "ZYLCH_PROFILE_DIR"):
        monkeypatch.setenv(key, "")
    (tmp_path / "uid-1").mkdir()
    (tmp_path / "uid-1" / ".env").write_text("OWNER_ID=uid-1\n")
    monkeypatch.setenv("OWNER_ID", "")
    profiles.activate_profile("uid-1")
    assert started == [str(tmp_path / "uid-1")]
