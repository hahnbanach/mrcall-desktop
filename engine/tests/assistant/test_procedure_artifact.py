"""The email host reads the canonical phone artifact, never a maintained copy."""

import hashlib
import json

import pytest

from tests.assistant.procedure_fixture import artifact_bytes
from zylch.assistant.procedure import ProcedureArtifact


@pytest.fixture
def raw():
    return artifact_bytes()


def parse(raw):
    return ProcedureArtifact.parse(raw, hashlib.sha256(raw).hexdigest())


def test_canonical_artifact_and_revision_snapshot(raw):
    first = parse(raw)
    changed = json.loads(raw)
    changed["instructions"] = "Ask for identification before attempting any read."
    second = parse(json.dumps(changed).encode())
    assert first.revision != second.revision
    assert first.instructions != second.instructions
    assert first.revision in first.prompt
    assert second.instructions in second.prompt
    assert [s["name"] for s in first.schemas()] == ["capability_read", "procedure_finish"]
    assert [s["name"] for s in first.schemas(frozenset())] == ["procedure_finish"]
    assert first.schemas(frozenset({"memory.recall"}))[0]["input_schema"]["properties"][
        "operation"
    ]["enum"] == ["memory.recall"]
    assert first.schemas()[1]["input_schema"]["properties"]["status"]["enum"] == [
        "need_identification",
        "no_order",
        "order_exists",
        "unavailable",
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", True),
        ("version", 1.0),
        ("extra", "ignored?"),
        ("id", "../secret"),
        ("instructions", ""),
        ("instructions", "x" * 8001),
        ("instructions", "bad\x00text"),
        ("instructions", "\ud800"),
        ("operations", ["shell"]),
        ("operations", ["order.exists", "order.exists"]),
        ("operations", []),
        ("completion", "shell"),
        ("messages", {}),
    ],
)
def test_reject_invalid_content(raw, field, value):
    artifact = json.loads(raw)
    artifact[field] = value
    with pytest.raises(ValueError):
        parse(json.dumps(artifact).encode())


def test_reject_drift_duplicate_keys_invalid_utf8_and_oversize(raw):
    with pytest.raises(ValueError):
        ProcedureArtifact.parse(raw, "0" * 64)
    for value in (
        raw.replace(b'"version": 1', b'"version": 1, "version": 1'),
        b"\xff",
        b" " * 16385,
    ):
        with pytest.raises(ValueError):
            parse(value)


def test_harmless_memory_only_procedure_needs_no_dispatch_change(raw):
    artifact = json.loads(raw)
    artifact.update(id="approved-memory", operations=["memory.recall"], completion="memory")
    result = parse(json.dumps(artifact).encode())
    assert result.operations == ("memory.recall",)
    assert result.schemas()[0]["input_schema"]["properties"]["operation"]["enum"] == [
        "memory.recall"
    ]
    artifact["completion"] = "order"
    with pytest.raises(ValueError):
        parse(json.dumps(artifact).encode())
