"""Retention: what consolidation prunes, what it keeps, and what ends a sink.

Every case runs against a real company store booted through `init_db`. The
retention step is driven here the way the consolidation operation drives it —
the sink report first, then `expire_versions` with the sinks it names — so the
policy itself is under test: the window, the floor, the sink threshold, the
restore that ends a sink, and the dropped donor that is never one. Old
versions are seeded as rows with an explicit `superseded_at`, because age is
what the window measures and a test cannot wait ninety days; the restore case
goes through the real `restore_version`.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from zylch.memory.blob_storage import BlobStorage
from zylch.memory.blob_versions import (
    APPEND,
    CONSOLIDATE,
    RESTORE,
    SINK_REPORT_LIMIT,
    expire_versions,
    list_versions,
    retention_policy,
    sink_report,
    version_counts,
)
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.models import BlobVersion

from tests.memory.mnemonic_env import (
    COMPANY_A,
    OWNER_A,
    OWNER_B,
    BagOfWordsEmbedder,
    boot,
    clear_process_state,
    stub_embedder,
)

ENGINE_ROOT = Path(__file__).resolve().parents[2]
WINDOW, FLOOR, THRESHOLD = 90, 10, 25
OTHER_COMPANY = "OOOOOOOOOOOOOOOOOOOOOO"


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def profile_a(tmp_path, monkeypatch, embedder):
    stub_embedder(monkeypatch, embedder)
    yield boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    dbm.dispose_engine()
    clear_process_state()


def storage(embedder) -> BlobStorage:
    return BlobStorage(get_session, embedder)


def seed_blob(embedder, name="Acme Srl", owner=OWNER_A, namespace=None) -> str:
    content = (
        f"#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: {name}\n#ABOUT\nA supplier."
    )
    return storage(embedder).store_blob(
        owner_id=owner,
        namespace=namespace or f"user:{COMPANY_A}",
        content=content,
        event_description="seed",
    )["id"]


def seed_versions(blob_id, n, *, reason=APPEND, days_old=200, company=COMPANY_A, owner=OWNER_A):
    """``n`` retained versions of one blob: the newest ``days_old`` days ago, an hour apart."""
    newest = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_old)
    with get_session() as session:
        for i in range(n):
            session.add(
                BlobVersion(
                    blob_id=blob_id,
                    company_key=company,
                    owner_id=owner,
                    namespace=f"user:{company}",
                    content=f"text {i} of {blob_id}",
                    reason=reason,
                    superseded_at=newest - timedelta(hours=i),
                )
            )


def count(blob_id, company=COMPANY_A) -> int:
    with get_session() as session:
        return (
            session.query(BlobVersion)
            .filter(BlobVersion.blob_id == blob_id, BlobVersion.company_key == company)
            .count()
        )


def run(owner=OWNER_A, *, window=WINDOW, floor=FLOOR, threshold=THRESHOLD):
    """The retention step as consolidation runs it: report, then prune what is not a sink."""
    with get_session() as session:
        report, sinks = sink_report(session, COMPANY_A, owner, threshold)
        pruned = expire_versions(session, COMPANY_A, window_days=window, floor=floor, sinks=sinks)
    return report, pruned


# ─── The window, the floor and the threshold ──────────────────────────


def test_a_blob_over_the_threshold_keeps_every_version_and_is_reported(profile_a, embedder):
    sink = seed_blob(embedder, "Sink Srl")
    seed_versions(sink, 30)
    ordinary = seed_blob(embedder, "Ordinary Srl")
    seed_versions(ordinary, 12)

    report, pruned = run()

    assert count(sink) == 30
    assert report["version_sinks"] == [{"blob_id": sink, "versions": 30}]
    assert report["version_sinks_total"] == 1
    assert report["blobs_versions_max"] == 30
    assert count(ordinary) == FLOOR and pruned == 2


def test_a_blob_under_the_threshold_is_pruned_to_the_floor_and_no_further(profile_a, embedder):
    blob = seed_blob(embedder)
    seed_versions(blob, 20)

    _, pruned = run()

    assert pruned == 10 and count(blob) == FLOOR
    with get_session() as session:
        kept = {v.content for v in list_versions(session, blob)}
    assert kept == {f"text {i} of {blob}" for i in range(FLOOR)}  # the newest ten
    _, again = run()
    assert again == 0 and count(blob) == FLOOR


def test_a_version_younger_than_the_window_is_never_pruned_however_many(profile_a, embedder):
    recent = seed_blob(embedder, "Recent Srl")
    seed_versions(recent, 60, days_old=1)
    mixed = seed_blob(embedder, "Mixed Srl")
    seed_versions(mixed, 15, days_old=1)
    seed_versions(mixed, 15, days_old=200)

    _, pruned = run(threshold=1000)

    assert count(recent) == 60
    # The floor keeps the ten newest; the five other recent ones are inside the
    # window; only the fifteen old ones go.
    assert count(mixed) == 15 and pruned == 15


# ─── What counts, and what ends a sink ────────────────────────────────


def test_a_restore_ends_a_sink_and_the_next_prune_is_ordinary(profile_a, embedder):
    blob = seed_blob(embedder)
    seed_versions(blob, 30)
    report, _ = run()
    assert report["version_sinks_total"] == 1 and count(blob) == 30

    with get_session() as session:
        oldest = list_versions(session, blob)[0].id
    out = storage(embedder).restore_version(blob, OWNER_A, oldest)
    assert out["ok"] is True, out

    with get_session() as session:
        assert version_counts(session, COMPANY_A)[blob] == 0
        reasons = [v.reason for v in list_versions(session, blob)]
    assert reasons[-1] == RESTORE  # the text the restore replaced, stamped as the owner's
    report, pruned = run()
    assert report["version_sinks_total"] == 0 and report["version_sinks"] == []
    # 31 versions: the restore's own (recent) and nine appends survive the floor.
    assert pruned == 21 and count(blob) == FLOOR


def test_consolidate_and_restore_versions_never_count_and_appends_count_after_a_restore(
    profile_a, embedder
):
    busy = seed_blob(embedder, "Merged Often Srl")
    seed_versions(busy, 30, reason=CONSOLIDATE)
    seed_versions(busy, 30, reason=RESTORE, days_old=300)
    acknowledged = seed_blob(embedder, "Acknowledged Srl")
    seed_versions(acknowledged, 30, days_old=300)  # before its restore
    seed_versions(acknowledged, 1, reason=RESTORE, days_old=200)
    seed_versions(acknowledged, 5, days_old=100)  # after it

    with get_session() as session:
        counts = version_counts(session, COMPANY_A)
    assert counts[busy] == 0
    assert counts[acknowledged] == 5
    report, _ = run()
    assert report["version_sinks_total"] == 0


def test_a_dropped_donors_versions_are_pruned_to_the_floor_and_never_a_sink(profile_a, embedder):
    donor = seed_blob(embedder, "Gone Srl")
    seed_versions(donor, 30)
    # The consolidation drop: the final text retained, the row gone, no cascade.
    assert storage(embedder).delete_blob(donor, OWNER_A, retain=True) is True

    report, pruned = run()

    assert report["version_sinks_total"] == 0 and report["version_sinks"] == []
    assert report["blobs_versions_max"] == 0  # no live blob holds a version
    # The floor keeps the donor's final text and its nine newest appends.
    assert count(donor) == FLOOR and pruned == 21
    with get_session() as session:
        assert list_versions(session, donor)[-1].reason == CONSOLIDATE


# ─── The report ───────────────────────────────────────────────────────


def test_the_report_lists_only_sinks_the_owner_can_see_at_most_a_hundred_with_the_total(
    profile_a, embedder
):
    visible = []
    for i in range(SINK_REPORT_LIMIT + 1):
        blob = seed_blob(embedder, f"Company {i:03d}")
        seed_versions(blob, THRESHOLD + 1 + i)
        visible.append((blob, THRESHOLD + 1 + i))
    b_rule = seed_blob(embedder, "B's rule", owner=OWNER_B, namespace=f"template:{OWNER_B}")
    seed_versions(b_rule, 500, owner=OWNER_B)

    report, _ = run()

    listed = report["version_sinks"]
    assert len(listed) == SINK_REPORT_LIMIT
    assert report["version_sinks_total"] == SINK_REPORT_LIMIT + 2
    assert b_rule not in {row["blob_id"] for row in listed}  # another account's rule
    expected = sorted(visible, key=lambda p: (-p[1], p[0]))[:SINK_REPORT_LIMIT]
    assert [(row["blob_id"], row["versions"]) for row in listed] == expected
    assert report["blobs_versions_max"] == 500
    assert count(b_rule) == 500  # listed or not, a sink is never pruned


# ─── The settings and the company ─────────────────────────────────────


def test_invalid_settings_prune_nothing_and_say_why(profile_a, monkeypatch):
    default = retention_policy()
    assert (default.window_days, default.floor, default.sink_threshold) == (90, 10, 25)
    assert default.prunes and default.pairs and default.refused == ()

    def policy(window=90, floor=10, threshold=25):
        return retention_policy(
            SimpleNamespace(
                version_retention_days=window,
                version_floor=floor,
                version_sink_threshold=threshold,
            )
        )

    no_window = policy(window=0)
    assert not no_window.prunes and no_window.pairs
    assert no_window.refused == ("version_retention_days=0 is below 1",)
    assert not policy(floor=0).prunes
    no_threshold = policy(threshold=0)
    assert not no_threshold.prunes and not no_threshold.pairs
    assert no_threshold.refused == ("version_sink_threshold=0 is below 1",)

    with get_session() as session, pytest.raises(ValueError):
        expire_versions(session, COMPANY_A, window_days=90, floor=0, sinks=())

    monkeypatch.setenv("MEMORY_VERSION_FLOOR", "3")
    assert retention_policy().floor == 3


def test_retention_is_company_scoped(profile_a, embedder):
    blob = seed_blob(embedder)
    seed_versions(blob, 20)
    # Another company's rows in the same file, as a join leaves them.
    seed_versions(blob, 20, company=OTHER_COMPANY)

    _, pruned = run()

    assert pruned == 10 and count(blob) == FLOOR
    assert count(blob, company=OTHER_COMPANY) == 20


# ─── Who may prune ────────────────────────────────────────────────────


def _callers(name: str) -> set:
    """``(path, symbol)`` of every call to ``name`` in the production tree."""

    class Calls(ast.NodeVisitor):
        def __init__(self, rel):
            self.rel, self.stack, self.found = rel, [], set()

        def visit_ClassDef(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef

        def visit_Call(self, node):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if called == name:
                self.found.add((self.rel, ".".join(self.stack)))
            self.generic_visit(node)

    found = set()
    for root in ("zylch", "scripts"):
        for path in sorted((ENGINE_ROOT / root).rglob("*.py")):
            visitor = Calls(path.relative_to(ENGINE_ROOT).as_posix())
            visitor.visit(ast.parse(path.read_text(), filename=str(path)))
            found |= visitor.found
    return found


def test_only_the_owners_delete_and_reset_remove_a_blobs_versions_wholesale():
    assert _callers("prune_versions") == {
        ("zylch/memory/blob_storage.py", "BlobStorage.delete_blob"),
        ("zylch/memory/blob_storage.py", "BlobStorage.delete_all_blobs"),
    }


def test_only_the_consolidation_operation_prunes_by_the_policy():
    assert {path for path, _ in _callers("expire_versions")} <= {"zylch/memory/consolidation.py"}
