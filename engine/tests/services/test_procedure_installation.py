"""Executable offline rehearsal: installation -> real chat/core -> SQLite drafts.

Only outbound model/provider responses are fixtures. The installed objects, source
validation, scoped reads, guarded client/budget and draft persistence stay real.
"""

import asyncio
import hashlib
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from tests.assistant.installation_fixture import installation_bytes
from tests.services.test_procedure_email import (
    FACT,
    KEY,
    OWNER,
    RECIPIENT,
    drafts,
    finish,
    read,
)
from tests.services.test_procedure_email import (
    setup as base_setup,  # noqa: F401 -- reuse real SQLite/model-edge fixture
)
from zylch.assistant.installation import InstallationSpec
from zylch.services.capability_contract import ContactGrant
from zylch.services.chat_service import ChatService
from zylch.services.procedure_email import EmailSelection, source_revision
from zylch.services.procedure_installation import PilotProcedureInstallation
from zylch.storage import database
from zylch.storage.models import Email

SECOND = "second@example.com"


@pytest.fixture
def installed(base_setup):  # noqa: F811
    state = base_setup
    state.route.close()
    raw = installation_bytes()
    state.spec = InstallationSpec.parse(
        raw, hashlib.sha256(raw).hexdigest(), state.artifact.revision
    )
    state.binding = replace(
        state.service.binding,
        business_id=state.spec.business_id,
        contacts=state.service.binding.contacts + (ContactGrant("second", SECOND),),
    )
    state.options = {
        "connection_ref": state.spec.connection_ref,
        "authority_ref": state.spec.authority_ref,
        "read_customers": state.provider,
        "session_factory": database.get_session,
        "profile_scope": lambda: (OWNER, KEY),
        "verify_token": Mock(side_effect=AssertionError("preflight must not verify tokens")),
    }
    with database.get_session() as session:
        session.add(
            Email(
                id="second-source",
                owner_id=OWNER,
                gmail_id="second-source",
                thread_id="second-thread",
                from_email=SECOND,
                to_email="owner@example.com",
                subject="Order question",
                body_plain="Do I have an order?",
                date=datetime.now(UTC),
            )
        )
        session.commit()
    source = state.storage.get_email_by_supabase_id(OWNER, "second-source")
    state.second = EmailSelection("second-source", source_revision(source), SECOND, "second")

    def customers(email):
        return {
            "data": {
                "customers": {
                    "edges": [
                        {
                            "node": {
                                "id": "fixture",
                                "email": email,
                                "numberOfOrders": "1" if email == RECIPIENT else "0",
                            }
                        }
                    ]
                }
            }
        }

    state.provider.side_effect = customers
    state.installation = PilotProcedureInstallation(
        state.spec, state.artifact, state.binding, **state.options
    )
    yield state
    state.installation.close()


async def process(state, handle, *, owner=OWNER, source=None):
    chat = ChatService(pilot_email_route=handle.route)
    chat.storage = state.storage
    return await chat.process_message(
        "/sync", owner, context={"email_id": source or handle.route.selection.source_id}
    )


def test_two_contacts_and_unidentified_selection_use_real_hosts_and_separate_evidence(installed):
    state = installed
    pool = state.installation._workers
    with state.installation.prepare_email(state.selection, state.storage, OWNER) as first:
        state.messages.side_effect = [
            read("memory.recall"),
            read(call_id="order"),
            finish(include=True),
        ]
        first_result = asyncio.run(process(state, first))
        assert first.route._workers is pool
    with state.installation.prepare_email(state.second, state.storage, OWNER) as second:
        state.messages.side_effect = [read(), finish("no_order")]
        second_result = asyncio.run(process(state, second))
        assert second.route._workers is pool
    unknown = replace(state.second, contact_ref=None)
    with state.installation.prepare_email(unknown, state.storage, OWNER) as third:
        state.messages.side_effect = [read(), finish("need_identification")]
        third_result = asyncio.run(process(state, third))
    assert first_result["response"] == state.artifact.message("order_exists") + "\n\n" + FACT
    assert second_result["response"] == state.artifact.message("no_order")
    assert third_result["response"] == state.artifact.message("need_identification")
    assert len(drafts()) == 3
    assert {tuple(d["to_addresses"]) for d in drafts()} == {(RECIPIENT,), (SECOND,)}
    assert [call.args[0] for call in state.provider.call_args_list] == [RECIPIENT, SECOND]
    assert state.installation.readiness().local_ready
    assert ChatService()._pilot_email_route is None


@pytest.mark.parametrize(
    "change", ["owner", "digest", "foreign_contact", "wrong_recipient", "source"]
)
def test_preparation_refuses_invalid_selection_without_model_or_provider(installed, change):
    state = installed
    owner, selection = OWNER, state.selection
    if change == "owner":
        owner = "foreign"
    elif change == "digest":
        selection = replace(selection, source_revision="0" * 64)
    elif change == "foreign_contact":
        selection = replace(selection, contact_ref="foreign")
    elif change == "wrong_recipient":
        selection = replace(selection, contact_ref="second")
    else:
        selection = replace(selection, source_id="absent")
    with pytest.raises(PermissionError, match="email_selection_denied"):
        state.installation.prepare_email(selection, state.storage, owner)
    state.messages.assert_not_called()
    state.provider.assert_not_called()
    assert not drafts()


def test_busy_closed_handle_and_installation_lifetimes(installed):
    state = installed
    first = state.installation.prepare_email(state.selection, state.storage, OWNER)
    with pytest.raises(PermissionError, match="busy"):
        state.installation.prepare_email(state.second, state.storage, OWNER)
    first.close()
    first.close()
    assert "error" in asyncio.run(process(state, first))["metadata"]
    second = state.installation.prepare_email(state.second, state.storage, OWNER)
    state.installation.close()
    state.installation.close()
    second.close()
    assert "error" in asyncio.run(process(state, second))["metadata"]
    with pytest.raises(PermissionError, match="closed"):
        state.installation.prepare_email(state.selection, state.storage, OWNER)
    assert state.installation.readiness().code == "installation_closed"
    state.messages.assert_not_called()
    assert not drafts()


@pytest.mark.parametrize("change", ["source", "profile", "binding", "close"])
def test_prepared_route_rechecks_authority_before_drafting(installed, change):
    state = installed
    handle = state.installation.prepare_email(state.selection, state.storage, OWNER)

    def response(**kwargs):
        if change == "source":
            with database.get_session() as session:
                session.query(Email).filter_by(id="source").update({"body_plain": "changed"})
                session.commit()
        elif change == "profile":
            state.installation._profile_scope = lambda: (OWNER, "B" * 22)
        elif change == "binding":
            state.installation.service.binding = replace(state.binding, business_id="other")
        else:
            state.installation.close()
        return finish("unavailable")

    state.messages.side_effect = response
    assert "error" in asyncio.run(process(state, handle))["metadata"]
    assert not drafts()
    state.provider.assert_not_called()


def test_cancelled_models_keep_shared_pool_slots_after_handle_close(installed):
    state = installed
    release = threading.Event()
    entered = [threading.Event(), threading.Event()]
    counter_lock = threading.Lock()
    count = 0

    def blocked(**kwargs):
        nonlocal count
        with counter_lock:
            index = count
            count += 1
        entered[index].set()
        release.wait(5)
        return finish("unavailable")

    state.messages.side_effect = blocked

    async def exercise():
        for event in entered:
            handle = state.installation.prepare_email(state.selection, state.storage, OWNER)
            task = asyncio.create_task(process(state, handle))
            async with asyncio.timeout(3):
                while not event.is_set():
                    await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            handle.close()
        with state.installation.prepare_email(state.second, state.storage, OWNER) as third:
            assert "error" in (await process(state, third))["metadata"]
        assert count == 2
        assert not drafts()
        release.set()
        await asyncio.sleep(0.1)
        state.messages.side_effect = [read(), finish("no_order")]
        with state.installation.prepare_email(state.second, state.storage, OWNER) as fourth:
            result = await process(state, fourth)
        assert result["response"] == state.artifact.message("no_order")

    try:
        asyncio.run(exercise())
    finally:
        release.set()
    assert len(drafts()) == 1


def test_retained_remote_endpoint_drops_pending_read_after_close(installed):
    state = installed
    import json
    from types import SimpleNamespace

    from zylch.services.capability_contract import CapabilityRequest

    entered, release = threading.Event(), threading.Event()

    def blocked(email):
        entered.set()
        release.wait(5)
        return state.provider.return_value

    state.provider.side_effect = blocked
    request = CapabilityRequest(
        1,
        state.spec.business_id,
        "remote-session",
        state.artifact.revision,
        "remote-request",
        1,
        0,
        "customer",
        "order.exists",
        int(time.time() * 1000) + 2900,
    )
    sent = []

    async def recv():
        return json.dumps(request.public_dict())

    async def send(value):
        sent.append(value)

    async def close(*args):
        pass

    connection = SimpleNamespace(
        _capability_claims={"sub": state.binding.service_uid, "exp": int(time.time()) + 100},
        recv=recv,
        send=send,
        close=close,
    )

    async def exercise():
        task = asyncio.create_task(state.installation.endpoint.handle(connection))
        async with asyncio.timeout(3):
            while not entered.is_set():
                await asyncio.sleep(0.01)
        state.installation.close()
        release.set()
        await task

    try:
        asyncio.run(exercise())
    finally:
        release.set()
    assert not sent


def test_close_during_source_lookup_cannot_publish_handle(installed, monkeypatch):
    state = installed
    original = state.storage.get_email_by_supabase_id

    def close_during_lookup(*args):
        result = original(*args)
        state.installation.close()
        return result

    monkeypatch.setattr(state.storage, "get_email_by_supabase_id", close_during_lookup)
    with pytest.raises(PermissionError, match="email_selection_denied"):
        state.installation.prepare_email(state.selection, state.storage, OWNER)
    assert state.installation._active is None
    assert state.installation.readiness().code == "installation_closed"
    state.messages.assert_not_called()


def test_close_inside_last_source_lookup_cannot_write_draft(installed, monkeypatch):
    state = installed
    handle = state.installation.prepare_email(state.selection, state.storage, OWNER)
    original = state.storage.get_email_by_supabase_id
    from zylch.assistant.procedure_policy import ProcedurePolicy

    final_text = ProcedurePolicy.final_text
    finalizing = False
    reads_after_final = 0

    def mark_final(policy):
        nonlocal finalizing
        text = final_text(policy)
        finalizing = True
        return text

    def close_in_last_read(*args):
        nonlocal reads_after_final
        result = original(*args)
        if finalizing:
            reads_after_final += 1
            # policy.check performs the first read; the route then fetches the
            # threading headers for the actual synchronous draft write.
            if reads_after_final == 2:
                state.installation.close()
        return result

    monkeypatch.setattr(ProcedurePolicy, "final_text", mark_final)
    monkeypatch.setattr(state.storage, "get_email_by_supabase_id", close_in_last_read)
    state.messages.side_effect = [finish("unavailable")]
    result = asyncio.run(process(state, handle))
    assert reads_after_final == 2
    assert "error" in result["metadata"]
    assert not drafts()
