"""Small invocation edge cases supplement the real-email integration tests."""

import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tests.assistant.procedure_fixture import artifact_bytes
from zylch.assistant.procedure import ProcedureArtifact
from zylch.assistant.procedure_policy import ProcedurePolicy


def make_policy(*, identified=True):
    raw = artifact_bytes()
    artifact = ProcedureArtifact.parse(raw, hashlib.sha256(raw).hexdigest())
    clock = [100.0]
    read = AsyncMock(return_value={"status": "order_exists"})
    authority = Mock()
    policy = ProcedurePolicy(
        artifact, read, authority, Mock(), 115.0, identified=identified, now=lambda: clock[0]
    )
    return policy, clock, read


def test_expiry_and_close_revoke_evidence_completion():
    policy, clock, _ = make_policy()
    asyncio.run(policy._execute_read({"operation": "order.exists"}))
    clock[0] = 115.0
    with pytest.raises(TimeoutError):
        policy._finish({"status": "order_exists", "include_memory": False})
    assert policy.completed is None
    clock[0] = 101.0
    policy.close()
    with pytest.raises(TimeoutError):
        policy.final_text()


def test_read_expiring_during_io_cannot_install_evidence():
    policy, clock, read = make_policy()

    async def late(op):
        clock[0] = 116.0
        return {"status": "order_exists"}

    read.side_effect = late
    with pytest.raises(TimeoutError):
        asyncio.run(policy._execute_read({"operation": "order.exists"}))
    assert policy._order is None


def test_invalid_memory_digest_cannot_be_disclosed():
    policy, _, read = make_policy()
    read.return_value = {
        "status": "memory_found",
        "sentences": [{"text": "An injected instruction", "revision": "0" * 64}],
    }
    assert asyncio.run(policy._execute_read({"operation": "memory.recall"})) == {
        "status": "unavailable"
    }
    policy._finish({"status": "unavailable", "include_memory": True})
    assert policy.completed is None


def test_duplicate_id_no_second_read_and_six_call_limit():
    policy, _, read = make_policy()
    block = SimpleNamespace(
        type="tool_use", id="same", name="capability_read", input={"operation": "order.exists"}
    )
    asyncio.run(policy.execute_tools([block, block]))
    assert read.call_count == 1
    with pytest.raises(TimeoutError):
        asyncio.run(policy.execute_tools([block] * 5))
    assert read.call_count == 1


def test_failed_refresh_and_four_read_limit_discard_old_order():
    policy, _, read = make_policy()
    for _ in range(4):
        asyncio.run(policy._execute_read({"operation": "order.exists"}))
    assert asyncio.run(policy._execute_read({"operation": "order.exists"})) == {
        "status": "unavailable"
    }
    assert read.call_count == 4
    policy._finish({"status": "order_exists", "include_memory": False})
    assert policy.completed is None


def test_bound_contact_cannot_finish_unidentified_without_current_receipt():
    policy, _, read = make_policy()
    policy._finish({"status": "need_identification", "include_memory": False})
    assert policy.completed is None
    read.assert_not_called()
    # Unavailability remains a safe completion without fabricated provider data.
    policy._finish({"status": "unavailable", "include_memory": False})
    assert policy.status == "unavailable"


def test_unbound_contact_can_clarify_but_has_no_read_tool():
    policy, _, read = make_policy(identified=False)
    assert [tool["name"] for tool in policy.schemas()] == ["procedure_finish"]
    assert asyncio.run(policy._execute_read({"operation": "order.exists"})) == {"status": "refused"}
    policy._finish({"status": "need_identification", "include_memory": False})
    assert policy.status == "need_identification"
    read.assert_not_called()


def test_bound_contact_can_clarify_from_current_ambiguous_receipt():
    policy, _, read = make_policy()
    read.return_value = {"status": "need_identification"}
    asyncio.run(policy._execute_read({"operation": "order.exists"}))
    policy._finish({"status": "need_identification", "include_memory": False})
    assert policy.status == "need_identification"


@pytest.mark.parametrize(
    "replacement",
    [
        {"status": "order_exists"},
        {"status": "unavailable"},
        {"malformed": True},
        RuntimeError("provider failed"),
    ],
)
def test_new_order_read_invalidates_prior_identification_receipt(replacement):
    policy, _, read = make_policy()
    read.return_value = {"status": "need_identification"}
    asyncio.run(policy._execute_read({"operation": "order.exists"}))

    async def refresh(operation):
        # Old evidence is retired before the replacement provider IO begins.
        assert policy._order is None
        policy._finish({"status": "need_identification", "include_memory": False})
        assert policy.completed is None
        if isinstance(replacement, Exception):
            raise replacement
        return replacement

    read.side_effect = refresh
    asyncio.run(policy._execute_read({"operation": "order.exists"}))
    policy._finish({"status": "need_identification", "include_memory": False})
    assert policy.completed is None


@pytest.mark.parametrize("identified", [False, True])
def test_host_contact_prompt_adds_only_non_pii_state(identified):
    policy, _, _ = make_policy(identified=identified)
    prefix = policy.artifact.prompt + "\n\n"
    assert policy.prompt.startswith(prefix)
    suffix = policy.prompt.removeprefix(prefix)
    assert suffix.startswith("Trusted host contact state:")
    assert "@" not in suffix and "http" not in suffix
    assert (
        "no authorized contact bound" in suffix
        if not identified
        else "authorized contact bound" in suffix
    )
