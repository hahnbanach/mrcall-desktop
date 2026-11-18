"""Migration preserves active operation bindings and admits exact send."""

from sqlalchemy import create_engine
from sqlalchemy.schema import CreateTable, CreateIndex
from zylch.storage.draft_operation_models import DraftOperation
from zylch.storage.draft_operations import DraftOperations
from zylch.storage.step_exact_send import STEP
from zylch.storage.migrations import run_migrations


def test_migration_preserves_active_journal(tmp_path):
    path = tmp_path / "old.db"
    engine = create_engine("sqlite:///" + str(path))
    with engine.begin() as conn:
        old = str(CreateTable(DraftOperation.__table__).compile(engine)).replace(", 'send'", "")
        conn.exec_driver_sql(old)
        for index in DraftOperation.__table__.indexes:
            conn.execute(CreateIndex(index))
    store = DraftOperations(engine)
    values = dict(
        owner_uid="owner",
        operation_id="old",
        canonical_root="root",
        operation_type="publish",
        draft_id="draft",
        expected_snapshot="snapshot",
        binding={"source": "exact"},
        output_mime_digest="digest",
    )
    reserved = store.reserve(**values)
    assert run_migrations(engine, str(path), steps=[STEP]) == [STEP.id]
    assert store.read("owner", "old") == reserved.operation
    assert run_migrations(engine, str(path), steps=[STEP]) == []
    assert store.reserve(
        **dict(values, operation_type="send", operation_id="send", canonical_root="other")
    ).acquired
    assert list((tmp_path / "backups").glob("*.bak"))
    engine.dispose()
