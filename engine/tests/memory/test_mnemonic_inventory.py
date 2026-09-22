"""Milestone 0: freeze every legacy semantic-memory write edge."""

from __future__ import annotations

import ast
from collections import Counter
import json
from pathlib import Path
import re

from tests.memory.mnemonic_inventory_scan import (
    orm_assignments,
    orm_core_mutations,
    orm_query_mutations,
    symbol_calls,
)

ENGINE_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "mnemonic" / "legacy_writer_inventory.json"


def _manifest() -> dict:
    return json.loads(FIXTURE.read_text())


def _source_files(manifest: dict) -> list[Path]:
    paths: list[Path] = []
    for root in manifest["scope"]:
        paths.extend(sorted((ENGINE_ROOT / root).rglob("*.py")))
    return paths


def _expected(entries: list[dict], *, include_mode: bool) -> Counter:
    out: Counter = Counter()
    for row in entries:
        key = (row["path"], row["symbol"], row["call"])
        if include_mode:
            key += (row["mode"],)
        out[key] = row["count"]
    return out


def test_every_direct_writer_call_is_owned_by_a_later_milestone():
    manifest = _manifest()
    tracked = set(manifest["tracked_calls"])
    models = set(manifest["tracked_models"])
    actual_calls: Counter = Counter()
    actual_constructors: Counter = Counter()
    actual_mutations: Counter = Counter()
    actual_assignments: Counter = Counter()
    actual_core_mutations: Counter = Counter()

    for path in _source_files(manifest):
        rel = path.relative_to(ENGINE_ROOT).as_posix()
        calls, constructors = symbol_calls(path, tracked, models)
        for (symbol, name, mode), count in calls.items():
            actual_calls[(rel, symbol, name, mode)] += count
        for scanner, destination in (
            (constructors, actual_constructors),
            (orm_query_mutations(path, models), actual_mutations),
            (orm_assignments(path, models), actual_assignments),
            (orm_core_mutations(path, models), actual_core_mutations),
        ):
            for (symbol, name), count in scanner.items():
                destination[(rel, symbol, name)] += count

    assert actual_calls == _expected(manifest["call_sites"], include_mode=True)
    assert actual_constructors == _expected(manifest["orm_sinks"], include_mode=False)
    assert actual_mutations == _expected(manifest["orm_mutations"], include_mode=False)
    assert actual_assignments == _expected(manifest["orm_assignments"], include_mode=False)
    assert actual_core_mutations == _expected(manifest["orm_core_mutations"], include_mode=False)
    for section in (
        "call_sites",
        "orm_sinks",
        "orm_mutations",
        "orm_assignments",
        "orm_core_mutations",
    ):
        assert all(1 <= row["milestone"] <= 8 for row in manifest[section])


def test_assignment_scanner_catches_aliases_and_equivalent_write_forms(tmp_path: Path):
    source = tmp_path / "new_writer.py"
    source.write_text("""\
from sqlalchemy import update as mutate
from zylch.storage.models import Blob as MemoryBlob

def write(session):
    row = session.query(MemoryBlob).one()
    row.content = "changed"
    setattr(row, "events", [])
    fresh = MemoryBlob()
    fresh.updated_at = None
    (session.query(MemoryBlob).one()).embedding = b"changed"
    loaded = session.get(MemoryBlob, "id")
    loaded.content = "loaded change"
    mutate(MemoryBlob).values(content="also changed")
""")
    models = {"Blob"}
    assert orm_assignments(source, models) == Counter(
        {
            ("write", "assign:Blob.content"): 2,
            ("write", "assign:Blob.events"): 1,
            ("write", "assign:Blob.updated_at"): 1,
            ("write", "assign:Blob.embedding"): 1,
        }
    )
    assert orm_core_mutations(source, models) == Counter({("write", "orm-core:update:Blob"): 1})


def test_every_literal_sql_sink_is_owned_by_a_later_milestone():
    manifest = _manifest()
    table_names = {
        "blobs",
        "blob_sentences",
        "person_identifiers",
        "email_blobs",
        "calendar_blobs",
        "whatsapp_blobs",
        "blob_aliases",
        "fact_history",
        "memory_meta",
    }
    pattern = re.compile(
        r"\b(INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE|DELETE\s+FROM)\s+("
        + "|".join(sorted(table_names, key=len, reverse=True))
        + r")\b",
        re.IGNORECASE,
    )
    actual: Counter = Counter()

    for path in _source_files(manifest):
        rel = path.relative_to(ENGINE_ROOT).as_posix()
        tree = ast.parse(path.read_text(), filename=str(path))
        stack: list[str] = []

        class Visitor(ast.NodeVisitor):
            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            visit_FunctionDef = _visit_function
            visit_AsyncFunctionDef = _visit_function

            def visit_Constant(self, node: ast.Constant) -> None:
                if not isinstance(node.value, str):
                    return
                for match in pattern.finditer(node.value):
                    verb = match.group(1).upper().split()[0]
                    actual[
                        (
                            rel,
                            ".".join(stack) or "<module>",
                            f"sql:{verb}:{match.group(2).lower()}",
                        )
                    ] += 1

        Visitor().visit(tree)

    assert actual == _expected(manifest["raw_sql_sinks"], include_mode=False)
    assert all(1 <= row["milestone"] <= 8 for row in manifest["raw_sql_sinks"])

    for row in manifest["known_dynamic_sql_sinks"]:
        source = (ENGINE_ROOT / row["path"]).read_text()
        assert f"def {row['symbol']}(" in source
        assert all(table in source for table in row["tables"])
        assert 1 <= row["milestone"] <= 8
