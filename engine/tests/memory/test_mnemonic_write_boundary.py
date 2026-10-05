"""The sealed direct-write boundary (milestone 8): one path, and a reviewed list of exceptions.

After milestone 8 every writer of company semantic memory in ``zylch/`` and
``scripts/`` is either the harness — ``memory/mnemonic/commit.py`` and the
storage primitives it alone drives — or a named, reviewed mechanical primitive
with a fixed precondition. The frozen writer inventory
(``tests/fixtures/mnemonic/legacy_writer_inventory.json``, checked by
``test_mnemonic_inventory.py``) holds every scanned writer edge; this file holds
what makes that list a boundary rather than a census:

- the exemptions are written here, as literal ``(path, symbol)`` pairs, and the
  inventory's ``exempt`` rows must name exactly those — adding one changes a
  reviewed test, not only a fixture;
- a writer reached other than by calling its name — an attribute reference, a
  ``getattr`` string, an import alias — is an edge too, and the real tree has
  none; synthetic sources prove each spelling, and a raw statement, are caught;
- the storage internals that assign ``Blob.content`` are reached only by the
  committed writers and the byte-identical restore, and the permit factory is
  called only by the commit — neither by any spelling elsewhere;
- a statement built from strings at run time is frozen per function, so a new
  one is a reviewed change;
- at run time a fresh ``BlobStorage`` has no seeding writer and refuses a
  semantic write without a permit, no production module imports the permit
  factory but the commit module, and none imports the test seeding module.
"""

from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path

import pytest

from .mnemonic_inventory_scan import (
    built_sql_calls,
    literal_sql_sinks,
    symbol_calls,
    writer_references,
)

ENGINE_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "mnemonic" / "legacy_writer_inventory.json"
WRITER_SECTIONS = (
    "call_sites",
    "orm_sinks",
    "orm_mutations",
    "orm_assignments",
    "orm_core_mutations",
    "raw_sql_sinks",
    "known_dynamic_sql_sinks",
)

# The reviewed mechanical primitives, each with the precondition its inventory
# row states. A new entry here is a reviewed decision, not a fixture edit.
EXEMPT = frozenset(
    {
        ("zylch/memory/join_import.py", "_put"),
        ("zylch/memory/rebuilds.py", "rebuild_source_links"),
        ("zylch/memory/rebuilds.py", "reindex_identifiers"),
        ("scripts/compact_learned_prefs.py", "drop_rules"),
        ("zylch/storage/storage.py", "Storage.delete_whatsapp_message_by_message_id"),
        ("zylch/storage/step_company_key.py", "apply"),
        ("zylch/storage/step_company_key.py", "reverse"),
        ("zylch/storage/step_identifiers_company_unique.py", "apply"),
        ("zylch/storage/step_memory_split.py", "apply"),
        ("zylch/storage/step_memory_split.py", "copy_if_absent"),
        ("zylch/storage/step_memory_split.py", "reverse_into_profile"),
        ("zylch/storage/step_memory_operations_drop_approval.py", "apply"),
    }
)

# Who may reach the internals that write a blob row: the committed writers and
# the byte-identical restore, which retains the text it replaces first.
INTERNAL_WRITERS = frozenset({"_insert", "_rewrite"})
INTERNAL_CALLERS = Counter(
    {
        ("zylch/memory/blob_commits.py", "CommittedWrites.semantic_create", "_insert"): 1,
        ("zylch/memory/blob_commits.py", "CommittedWrites.semantic_update", "_rewrite"): 1,
        ("zylch/memory/blob_commits.py", "CommittedWrites.semantic_merge", "_rewrite"): 1,
        ("zylch/memory/blob_versions.py", "restore_version", "_rewrite"): 1,
    }
)


# The one caller of the permit factory.
PERMIT_FACTORY = "issue_commit_permit"
PERMIT_CALLERS = Counter({("zylch/memory/mnemonic/commit.py", "_commit", PERMIT_FACTORY): 1})

# Every function that hands SQL built from strings to the driver, and how often.
# The memory-writing ones are the inventory's ``known_dynamic_sql_sinks`` and the
# join import; the others write profile or ledger tables or only read.
BUILT_SQL = Counter(
    {
        ("scripts/backfill_notifier_task_contacts.py", "run", "execute"): 1,
        ("zylch/email/sync_cursor.py", "drop_cursor", "exec_driver_sql"): 1,
        ("zylch/email/sync_cursor.py", "get_cursor", "exec_driver_sql"): 1,
        ("zylch/email/sync_cursor.py", "list_cursors", "exec_driver_sql"): 1,
        ("zylch/email/sync_cursor.py", "set_cursor", "exec_driver_sql"): 1,
        ("zylch/memory/join_import.py", "_put", "exec_driver_sql"): 1,
        ("zylch/memory/join_import.py", "_rows", "exec_driver_sql"): 1,
        # Fixed table/column/type constants add columns to private profile tables.
        ("zylch/qonto/migration.py", "sync_columns", "exec_driver_sql"): 1,
        ("zylch/rpc/preparation.py", "preparation_status", "exec_driver_sql"): 2,
        ("zylch/services/command_handlers.py", "handle_email", "text"): 2,
        ("zylch/services/preparation.py", "_finish", "exec_driver_sql"): 1,
        ("zylch/storage/database.py", "_apply_column_migrations", "exec_driver_sql"): 3,
        ("zylch/storage/migrations.py", "applied_step_ids", "text"): 1,
        ("zylch/storage/migrations.py", "ensure_schema_version_table", "exec_driver_sql"): 1,
        ("zylch/storage/migrations.py", "record_step", "text"): 1,
        ("zylch/storage/migrations.py", "unrecord_step", "text"): 1,
        ("zylch/storage/step_company_key.py", "apply", "exec_driver_sql"): 1,
        ("zylch/storage/step_identifiers_company_unique.py", "apply", "exec_driver_sql"): 2,
        ("zylch/storage/step_memory_operations_drop_approval.py", "apply", "exec_driver_sql"): 1,
        ("zylch/storage/step_memory_split.py", "_columns", "exec_driver_sql"): 1,
        ("zylch/storage/step_memory_split.py", "apply", "exec_driver_sql"): 1,
        ("zylch/storage/step_memory_split.py", "copy_if_absent", "exec_driver_sql"): 2,
        ("zylch/storage/step_memory_split.py", "reverse_into_profile", "exec_driver_sql"): 2,
    }
)


def _manifest() -> dict:
    return json.loads(FIXTURE.read_text())


def _source_files() -> list[Path]:
    paths: list[Path] = []
    for root in _manifest()["scope"]:
        paths.extend(sorted((ENGINE_ROOT / root).rglob("*.py")))
    return paths


def exempt_rows(manifest: dict) -> set[tuple[str, str]]:
    return {
        (row["path"], row["symbol"])
        for section in WRITER_SECTIONS
        for row in manifest.get(section, [])
        if "exempt" in row
    }


def test_the_inventory_exempts_exactly_the_reviewed_primitives():
    assert exempt_rows(_manifest()) == set(EXEMPT)


def _guarded_names() -> set[str]:
    """Every name a write may not be reached through: the tracked writers, the row internals, the permit factory."""
    return set(_manifest()["tracked_calls"]) | INTERNAL_WRITERS | {PERMIT_FACTORY}


def test_no_tracked_writer_is_reached_by_reference_getattr_or_alias():
    tracked = _guarded_names()
    found: Counter = Counter()
    for path in _source_files():
        rel = path.relative_to(ENGINE_ROOT).as_posix()
        for (symbol, spelling), count in writer_references(path, tracked).items():
            found[(rel, symbol, spelling)] += count
    assert found == Counter()


def test_the_blob_row_internals_are_reached_only_by_the_committed_writers_and_the_restore():
    found: Counter = Counter()
    for path in _source_files():
        rel = path.relative_to(ENGINE_ROOT).as_posix()
        calls, _ = symbol_calls(path, set(INTERNAL_WRITERS), set())
        for (symbol, name, _mode), count in calls.items():
            found[(rel, symbol, name)] += count
    assert found == INTERNAL_CALLERS


def test_only_the_commit_calls_the_permit_factory():
    found: Counter = Counter()
    for path in _source_files():
        rel = path.relative_to(ENGINE_ROOT).as_posix()
        calls, _ = symbol_calls(path, {PERMIT_FACTORY}, set())
        for (symbol, name, _mode), count in calls.items():
            found[(rel, symbol, name)] += count
    assert found == PERMIT_CALLERS


def test_sql_built_at_run_time_is_frozen_per_function():
    found: Counter = Counter()
    for path in _source_files():
        rel = path.relative_to(ENGINE_ROOT).as_posix()
        for (symbol, method), count in built_sql_calls(path).items():
            found[(rel, symbol, method)] += count
    assert found == BUILT_SQL


# ─── Synthetic bypasses: each spelling is caught ──────────────────────

BYPASSES = {
    "attribute reference": (
        "def write(storage):\n    save = storage.store_blob\n    save('o', 'user:k', 'x')\n",
        ("write", "ref:store_blob"),
    ),
    "callback in a list": (
        "from zylch.services.facts_store import upsert_fact\n\nHANDLERS = [upsert_fact]\n",
        ("<module>", "ref:upsert_fact"),
    ),
    "getattr string": (
        "def write(storage):\n    getattr(storage, 'update_blob')('b', 'o', 'x')\n",
        ("write", "getattr:update_blob"),
    ),
    "row internal by getattr": (
        "def write(storage, session, prepared):\n"
        "    getattr(storage, '_insert')(session, owner_id='o', namespace='n', prepared=prepared)\n",
        ("write", "getattr:_insert"),
    ),
    "row internal by reference": (
        "def write(storage):\n    rewrite = storage._rewrite\n    return rewrite\n",
        ("write", "ref:_rewrite"),
    ),
    "permit factory by getattr": (
        "from zylch.memory import commit_permit\n\n"
        "def mint():\n    return getattr(commit_permit, 'issue_commit_permit')\n",
        ("mint", "getattr:issue_commit_permit"),
    ),
    "import alias": (
        "from zylch.services.facts_store import upsert_fact as keep\n\n"
        "def write():\n    keep('o', 'pricing', 'list', '100')\n",
        ("<module>", "import-alias:upsert_fact"),
    ),
}


@pytest.mark.parametrize("name", sorted(BYPASSES))
def test_a_writer_reached_around_its_name_is_caught(tmp_path, name):
    source, edge = BYPASSES[name]
    path = tmp_path / "bypass.py"
    path.write_text(source)

    assert writer_references(path, _guarded_names())[edge] == 1


def test_an_aliased_call_is_attributed_to_the_writer_it_names(tmp_path):
    path = tmp_path / "aliased.py"
    path.write_text(BYPASSES["import alias"][0])
    calls, _ = symbol_calls(path, set(_manifest()["tracked_calls"]), set())

    assert calls == Counter({("write", "upsert_fact", "sync"): 1})


def test_a_permit_minted_through_the_module_is_caught(tmp_path):
    path = tmp_path / "mint.py"
    path.write_text(
        "from zylch.memory import commit_permit\n\n"
        "def mint(event):\n    return commit_permit.issue_commit_permit(event)\n"
    )
    calls, _ = symbol_calls(path, {PERMIT_FACTORY}, set())

    assert calls == Counter({("mint", PERMIT_FACTORY, "sync"): 1})


def test_a_statement_built_from_strings_is_caught(tmp_path):
    path = tmp_path / "built.py"
    path.write_text(
        "def write(conn, table, column):\n"
        "    conn.exec_driver_sql(f'UPDATE {table} SET content = ?', ('x',))\n"
        "    sql = 'DELETE FROM ' + table\n"
        "    conn.execute(sql)\n"
        "    conn.execute('UPDATE {} SET {} = ?'.format(table, column), ('y',))\n"
        "    conn.execute('SELECT 1')\n"
        "    grown = 'DELETE FROM '\n"
        "    grown += table\n"
        "    conn.execute(grown)\n"
        "    conn.exec_driver_sql(statement=f'DELETE FROM {table}')\n"
    )

    assert built_sql_calls(path) == Counter({("write", "exec_driver_sql"): 2, ("write", "execute"): 3})


def test_a_raw_statement_is_caught(tmp_path):
    path = tmp_path / "raw.py"
    path.write_text(
        "def write(conn):\n"
        "    conn.execute(\"UPDATE blobs SET namespace = ? WHERE id = ?\", ('x', 'y'))\n"
        "    conn.execute('insert or ignore into person_identifiers (id) values (?)', ('i',))\n"
        "    conn.execute('DELETE FROM blob_versions WHERE blob_id = ?', ('b',))\n"
    )

    assert literal_sql_sinks(path) == Counter(
        {
            ("write", "sql:UPDATE:blobs"): 1,
            ("write", "sql:INSERT:person_identifiers"): 1,
            ("write", "sql:DELETE:blob_versions"): 1,
        }
    )


# ─── At run time ──────────────────────────────────────────────────────


def test_a_fresh_blob_storage_has_no_seeding_writer_and_refuses_a_write_without_a_permit(
    tmp_path, monkeypatch, embedder
):
    from zylch.memory.blob_storage import BlobStorage
    from zylch.memory.commit_permit import PermitError
    from zylch.memory.mnemonic.session import company_transaction
    from zylch.storage import database as dbm
    from zylch.storage.database import get_session

    from .mnemonic_env import COMPANY_A, OWNER_A, boot, clear_process_state, stub_embedder

    stub_embedder(monkeypatch, embedder)
    boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    try:
        storage = BlobStorage(get_session, embedder)
        assert not hasattr(storage, "store_blob") and not hasattr(storage, "update_blob")
        prepared = storage.prepare("#IDENTIFIERS\nEntity type: PERSON\nName: Luca\n#ABOUT\nx")
        with pytest.raises(PermitError):
            with company_transaction(write=True) as session:
                storage.semantic_create(
                    session, None, owner_id=OWNER_A, namespace=f"user:{COMPANY_A}", prepared=prepared
                )
        with get_session() as session:
            from zylch.storage.models import Blob

            assert session.query(Blob).count() == 0
    finally:
        dbm.dispose_engine()
        clear_process_state()


def _importers(module_names: set[str], names: set[str]) -> list[str]:
    """Production modules importing any of ``module_names``, or any of ``names`` from anywhere."""
    found: list[str] = []
    for path in _source_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if any(module == m or module.endswith("." + m) for m in module_names) or any(
                    item.name in names for item in node.names
                ):
                    found.append(path.relative_to(ENGINE_ROOT).as_posix())
            elif isinstance(node, ast.Import):
                if any(item.name.split(".")[0] == "tests" for item in node.names):
                    found.append(path.relative_to(ENGINE_ROOT).as_posix())
    return sorted(set(found))


def test_only_the_commit_module_imports_the_permit_factory():
    assert _importers(set(), {"issue_commit_permit"}) == ["zylch/memory/mnemonic/commit.py"]


def test_no_production_module_imports_the_test_seeding_module():
    assert _importers({"seeding", "tests.memory", "tests"}, {"seeding"}) == []
