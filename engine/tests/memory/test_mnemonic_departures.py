"""A proposal that departs from the request is committed, and the departure is recorded.

The write-time approval gate is withdrawn (brief amendment, 2026-09-23). What
replaces it is not another gate: the rewrite retains the text it replaces
(`test_blob_versions.py`), and the operation receipt says how the role's
decision departed from what the tool call asked for. Both halves are asserted
against real rows — the journal row's `departure` column and the tool's
`data["departure"]` — so a departure that is written but not recorded, or
recorded but not returned, fails here.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from zylch.memory.mnemonic.approval import (
    CHANGED_SUBJECT,
    UNNAMED_SUBJECT,
    RequestedWrite,
    departure_for,
)
from zylch.memory.mnemonic.commit import submit
from zylch.memory.mnemonic.contracts import (
    CREATE,
    INTERACTIVE,
    OPERATOR_DELEGATED,
    UPDATE,
    MemoryEvent,
)
from zylch.memory.mnemonic.proposals import Proposal, WriteTarget
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.models import Blob, MemoryOperation

from tests.memory.mnemonic_env import (
    COMPANY_A,
    OWNER_A,
    BagOfWordsEmbedder,
    boot,
    clear_process_state,
    client,
    stub_embedder,
    with_client,
)

ACME = (
    "#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Acme Srl\n"
    "Email: info@acme.test\n#ABOUT\nIndustrial supplier in Milan."
)
BETA = (
    "#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Beta Spa\n"
    "Email: info@beta.test\n#ABOUT\nPackaging supplier in Turin."
)
BETA_CORRECTED = BETA.replace("info@beta.test", "orders@beta.test")
SAID = "L'indirizzo ordini di Beta Spa ora è orders@beta.test, non info@beta.test"


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def profile(tmp_path, monkeypatch, embedder):
    from zylch.assistant.turn_context import set_turn_observation

    stub_embedder(monkeypatch, embedder)
    owner = boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    set_turn_observation(SAID)
    yield owner
    dbm.dispose_engine()
    clear_process_state()


def seed(content, embedder):
    from zylch.memory.blob_storage import BlobStorage

    storage = BlobStorage(get_session, embedder)
    blob = storage.store_blob(
        owner_id=OWNER_A, namespace=f"user:{COMPANY_A}", content=content, event_description="seed"
    )
    return blob["id"], storage.get_blob(blob["id"], OWNER_A)["updated_at"]


def blobs():
    with get_session() as session:
        return {b.id: b.content for b in session.query(Blob).all()}


def journal_rows():
    with get_session() as session:
        return [r.to_dict() for r in session.query(MemoryOperation).all()]


def update_decision(blob_id, version, content=BETA_CORRECTED):
    return json.dumps(
        {
            "action": UPDATE,
            "entity_type": "COMPANY",
            "scope": "entity",
            "content": content,
            "write_set": [{"blob_id": blob_id, "expected_version": version, "role": "target"}],
            "reason": "the ordering address replaces the old one",
        }
    )


def run_update(monkeypatch, *, named, target, version):
    """The real ``update_memory`` tool: the model named ``named``, the role writes ``target``."""
    from zylch.tools.update_memory_tool import UpdateMemoryTool

    with_client(monkeypatch, client(update_decision(target, version)))
    return asyncio.run(
        UpdateMemoryTool(owner_id=OWNER_A).execute(
            blob_id=named, new_content=BETA_CORRECTED, entry_type="entity_fact"
        )
    )


# ─── What a departure is ──────────────────────────────────────────────


def test_a_faithful_proposal_records_no_departure():
    requested = RequestedWrite(action=UPDATE, blob_id="b1", subject_is_authoritative=True)
    proposal = Proposal(
        action=UPDATE,
        entity_type="COMPANY",
        scope="entity",
        content=ACME,
        write_set=(WriteTarget(blob_id="b1", expected_version="v1"),),
    )
    assert departure_for(requested, proposal) is None


def test_a_departure_names_the_flags_the_reasons_and_both_sides():
    requested = RequestedWrite(action=CREATE, entity_type="COMPANY")
    proposal = Proposal(
        action=UPDATE,
        entity_type="COMPANY",
        scope="entity",
        content=ACME,
        write_set=(WriteTarget(blob_id="b9", expected_version="v1"),),
    )
    record = departure_for(requested, proposal)
    assert record["flags"] == ["changed_action", UNNAMED_SUBJECT]
    assert len(record["why"]) == 2
    assert record["requested"]["action"] == CREATE
    assert record["proposed"] == {
        "action": UPDATE,
        "entity_type": "COMPANY",
        "scope": "entity",
        "targets": ["b9"],
    }
    # JSON-shaped, because it is stored and returned as it is.
    json.dumps(record)


def test_with_no_baseline_nothing_is_recorded():
    """A false flag in the journal is worse than an absent one."""
    proposal = Proposal(
        action=UPDATE,
        entity_type="COMPANY",
        scope="entity",
        content=ACME,
        write_set=(WriteTarget(blob_id="b1", expected_version="v1"),),
    )
    assert departure_for(None, proposal) is None


# ─── Against real rows ────────────────────────────────────────────────


def test_a_changed_subject_is_committed_and_recorded_on_both_sides(profile, monkeypatch, embedder):
    """The model named ACME; the human spoke about Beta; the role wrote Beta.

    That write lands — nobody is asked — and the departure is in the journal
    row and in the tool's response, so a reader can see the role chose
    differently from the call.
    """
    named, _ = seed(ACME, embedder)
    target, version = seed(BETA, embedder)

    result = run_update(monkeypatch, named=named, target=target, version=version)

    assert result.status.value == "success", result.error
    assert "orders@beta.test" in blobs()[target]
    assert blobs()[named] == ACME
    departure = result.data["departure"]
    assert CHANGED_SUBJECT in departure["flags"]
    assert departure["requested"]["blob_id"] == named
    assert departure["proposed"]["targets"] == [target]
    (row,) = journal_rows()
    assert row["state"] == "committed"
    assert row["departure"] == departure


def test_a_faithful_update_leaves_the_column_and_the_field_empty(profile, monkeypatch, embedder):
    target, version = seed(BETA, embedder)

    result = run_update(monkeypatch, named=target, target=target, version=version)

    assert result.status.value == "success", result.error
    assert result.data["departure"] is None
    (row,) = journal_rows()
    assert row["departure"] is None


def test_a_headless_caller_writes(profile, monkeypatch, embedder):
    """There is no channel to lack: nothing at write time asks anyone."""
    named, _ = seed(ACME, embedder)
    target, version = seed(BETA, embedder)
    result = run_update(monkeypatch, named=named, target=target, version=version)
    assert result.status.value == "success", result.error
    assert "orders@beta.test" in blobs()[target]


def test_the_departing_write_retained_what_it_replaced(profile, monkeypatch, embedder):
    """The two halves together: recorded, and reversible."""
    from zylch.memory.blob_versions import list_versions

    named, _ = seed(ACME, embedder)
    target, version = seed(BETA, embedder)
    run_update(monkeypatch, named=named, target=target, version=version)
    with get_session() as session:
        kept = list_versions(session, target)
        assert [v.content for v in kept] == [BETA]
        assert kept[0].operation_id == journal_rows()[0]["event_id"]


def test_submit_without_a_baseline_commits_and_records_nothing(profile, monkeypatch, embedder):
    target, version = seed(BETA, embedder)
    event = MemoryEvent(
        event_id="evt-no-baseline",
        owner_id=OWNER_A,
        company_key=COMPANY_A,
        caller_class=OPERATOR_DELEGATED,
        origin=INTERACTIVE,
        source_kind="chat",
        source_id="turn:1",
        source_revision="rev-1",
        observation=SAID,
    )
    result = submit(event, client=client(update_decision(target, version)))
    assert result.outcome == "committed", result.reason
    assert result.departure is None
    (row,) = journal_rows()
    assert row["departure"] is None


# ─── Restore: mechanical, retained, gated on every route ─────────────────


def versions_of(blob_id):
    from zylch.memory.blob_versions import list_versions

    with get_session() as session:
        return [(v.id, v.reason, v.content) for v in list_versions(session, blob_id)]


def test_a_restore_brings_back_the_named_version_and_retains_what_it_replaced(profile, embedder):
    from zylch.memory.blob_storage import BlobStorage

    storage = BlobStorage(get_session, embedder)
    target, _ = seed(BETA, embedder)
    storage.update_blob(target, OWNER_A, BETA_CORRECTED, event_description="correction")
    ((first_id, _, first_text),) = versions_of(target)
    assert first_text == BETA

    out = storage.restore_version(target, OWNER_A, first_id)

    assert out["ok"] is True, out
    assert out["blob"]["content"] == BETA
    assert blobs()[target] == BETA
    # The restore retained the text it replaced: history only grows. It is
    # stamped as the owner's restore, which is what ends a sink's count.
    assert [(r, c) for _, r, c in versions_of(target)] == [
        ("append", BETA),
        ("restore", BETA_CORRECTED),
    ]


def test_a_version_of_another_blob_cannot_be_restored_into_this_one(profile, embedder):
    from zylch.memory.blob_storage import BlobStorage

    storage = BlobStorage(get_session, embedder)
    acme, _ = seed(ACME, embedder)
    beta, _ = seed(BETA, embedder)
    storage.update_blob(beta, OWNER_A, BETA_CORRECTED, event_description="correction")
    ((beta_version, _, _),) = versions_of(beta)

    out = storage.restore_version(acme, OWNER_A, beta_version)

    assert out["ok"] is False and "no such version" in out["reason"]
    assert blobs()[acme] == ACME
    assert versions_of(acme) == []
    assert storage.restore_version("no-such-blob", OWNER_A, beta_version)["ok"] is False


def test_the_rpc_and_the_slash_verb_drive_the_same_restore(profile, embedder, monkeypatch):
    """Both doors answer; neither raises; the listing gives a human the id."""
    from zylch.memory.blob_storage import BlobStorage
    from zylch.rpc import maintenance
    from zylch.services.command_handlers import handle_memory

    storage = BlobStorage(get_session, embedder)
    target, _ = seed(BETA, embedder)
    storage.update_blob(target, OWNER_A, BETA_CORRECTED, event_description="correction")
    ((v1, _, _),) = versions_of(target)
    monkeypatch.setattr(maintenance, "_owner_id", lambda: OWNER_A)

    out = asyncio.run(
        maintenance.memory_restore_version({"blob_id": target, "version_id": v1}, lambda *_: None)
    )
    assert out["ok"] is True, out
    assert blobs()[target] == BETA

    listing = asyncio.run(handle_memory(["versions", target], None, OWNER_A))
    ids = [i for i, _, _ in versions_of(target)]
    assert len(ids) == 2 and all(i in listing for i in ids), listing
    answer = asyncio.run(handle_memory(["restore", target, ids[1]], None, OWNER_A))
    assert "Memory restored" in answer, answer
    assert blobs()[target] == BETA_CORRECTED
    assert len(versions_of(target)) == 3

    # A caller can render every refusal; nothing raises.
    assert asyncio.run(maintenance.memory_restore_version({}, lambda *_: None))["ok"] is False
    assert "Missing ids" in asyncio.run(handle_memory(["restore", target], None, OWNER_A))
    assert "Not restored" in asyncio.run(handle_memory(["restore", target, "x"], None, OWNER_A))


def kernel_root() -> Path:
    root = Path(__file__).resolve().parents[2].parent.parent / "cs-kernel"
    if not (root / "cs/templates/project/bin/cs_operator_cron.sh.j2").exists():
        pytest.skip("cs-kernel sibling checkout is required for the cross-repository check")
    return root


def test_the_restore_is_gated_on_every_route_a_mutation_has():
    """Slash verb, tool permission, read-only turn, scheduled operator."""
    from zylch.services.approval_gate import _MUTATING_SUBCOMMANDS, mutation_gate_for_command
    from zylch.services.request_policy import MUTATING_TOOLS, command_effect
    from zylch.services.task_executor import APPROVAL_TOOLS

    assert mutation_gate_for_command("/memory", ["restore", "b", "v"]) == "restore_memory"
    assert _MUTATING_SUBCOMMANDS[("/memory", "restore")] == "restore_memory"
    assert "restore_memory" in APPROVAL_TOOLS
    assert "restore_memory" in MUTATING_TOOLS
    # A read-only turn (`cs ask`) refuses it before routing, like store/delete/reset;
    # the listing is a read and stays available.
    assert command_effect("/memory", ["restore", "b", "v"]) == "memory_write"
    assert command_effect("/memory", ["versions", "b"]) is None

    # The scheduled operator cannot reach the RPC: denied by name in the cron
    # template's raw-RPC list, at the same position the kernel's gate 17 checks.
    kernel = kernel_root()
    cron = (kernel / "cs/templates/project/bin/cs_operator_cron.sh.j2").read_text()
    block = cron.split("{% for method in [", 1)[1].split("] %}", 1)[0]
    denied = [line.strip().strip(",").strip("'") for line in block.splitlines() if line.strip()]
    assert "memory.restore_version" in denied, denied
    gate = (kernel / "tests/run.sh").read_text()
    verbs_block = gate.split("VERBS = [", 1)[1].split("]", 1)[0]
    verbs = [v.strip().strip('"') for v in verbs_block.replace("\n", " ").split(",") if v.strip()]
    assert "rpc memory.restore_version" in verbs, verbs
    assert verbs.index("rpc memory.restore_version") - verbs.index(
        "rpc memory.reset"
    ) == denied.index("memory.restore_version") - denied.index("memory.reset")
