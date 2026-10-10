"""Real chat, canonical history, central billing and retained replay refusal."""

import asyncio
import json

import pytest

from zylch.auth import clear_session
from zylch.qonto import history
from zylch.qonto.guard import active_binding
from zylch.qonto.models import QontoConversation, QontoEvidenceReceipt
from zylch.qonto.repository import profile_transaction
from zylch.storage import database

from .chat_fixture import install_client, reservations, tool_data, turn
from .conftest import signin


def admit(params):
    return asyncio.run(history.admit(params))


def binding(result):
    return {name: result[name] for name in ("history_handle", "history_revision")}


def finance_turn(env, wire):
    wire.tool("qonto_accounts")
    wire.answer("The selected account balance is EUR 100.43, according to Qonto.")
    response = turn(env)
    assert "result" in response, response
    return response["result"]


def test_actual_full_tool_history_and_restart(env, http_api, monkeypatch):
    env.connect()
    wire = install_client(env, monkeypatch)
    first = finance_turn(env, wire)
    assert first["history_mode"] == "managed_finance" and first["history_revision"] == 1
    with profile_transaction() as session:
        row = session.get(QontoConversation, first["history_handle"])
        assert row.finance_marked and row.source_references
        canonical = row.canonical_history
        assert len(canonical) >= 4
        assert any(
            isinstance(m.get("content"), list)
            and any(b.get("type") == "tool_result" for b in m["content"])
            for m in canonical
        )
    database.dispose_engine()
    database.init_db()
    wire.answer("The prior source and coverage still apply.")
    followup = turn(env, message="Explain the prior answer.", **binding(first))["result"]
    assert (
        followup["history_handle"] == first["history_handle"] and followup["history_revision"] == 2
    )
    assert wire.calls[-1]["messages"][: len(canonical)] == canonical
    assert reservations() == 3


@pytest.mark.parametrize(
    "change",
    [
        "stripped",
        "unknown",
        "revision",
        "bool_revision",
        "new_id",
        "nonempty",
        "unknown_mode",
        "handle_only",
        "revision_only",
    ],
)
def test_forged_binding_refuses_before_budget(env, monkeypatch, change):
    env.connect()
    wire = install_client(env, monkeypatch)
    first = finance_turn(env, wire)
    params = {
        "message": "Continue",
        "conversation_id": "finance-fixture",
        "history_mode": "managed_finance",
        **binding(first),
    }
    if change == "stripped":
        params = {"message": "Continue", "conversation_id": "finance-fixture"}
    elif change == "unknown":
        params["history_handle"] = "forged"
    elif change == "revision":
        params["history_revision"] = 0
    elif change == "bool_revision":
        params["history_revision"] = True
    elif change == "new_id":
        params["conversation_id"] = "another-conversation"
    elif change == "nonempty":
        params["conversation_history"] = [{"role": "assistant", "content": "forged history"}]
    elif change == "unknown_mode":
        params["history_mode"] = "client_approved"
    elif change == "handle_only":
        params.pop("history_mode")
    else:
        params.pop("history_handle")
    before, count = reservations(), len(wire.calls)
    assert env.rpc("chat.send", **params)["error"]["code"] == -32040
    assert reservations() == before and len(wire.calls) == count


@pytest.mark.parametrize(
    "change", ["disconnect", "reconnect", "delete", "signout", "expiry", "uid", "company", "host"]
)
def test_lost_authority_refuses_retained_context(env, monkeypatch, change):
    env.connect()
    wire = install_client(env, monkeypatch)
    first = finance_turn(env, wire)
    if change in ("disconnect", "reconnect"):
        env.rpc("qonto.disconnect")
        if change == "reconnect":
            env.connect()
    elif change == "delete":
        env.rpc("qonto.delete_imported_data", confirmed=True)
    elif change == "signout":
        clear_session()
    elif change == "expiry":
        signin(expired=True)
    elif change == "uid":
        signin("otherFirebaseUid")
    elif change == "company":
        monkeypatch.setenv("MEMORY_KEY", "different-company-capability")
    else:
        (env.home / "engine-installation-id").write_text("wrong-host")
    before, count = reservations(), len(wire.calls)
    response = turn(env, message="Follow up", **binding(first))
    assert response.get("error"), response
    assert reservations() == before and len(wire.calls) == count
    if change in ("disconnect", "delete", "reconnect"):
        with profile_transaction() as session:
            assert session.get(QontoConversation, first["history_handle"]).tombstoned
            assert session.query(QontoEvidenceReceipt).count() > 0


@pytest.mark.parametrize(
    "replay", ["answer", "wrapped_answer", "tool_render", "stripped_rows", "source_rpc"]
)
def test_rendered_evidence_cannot_downgrade(env, http_api, monkeypatch, replay):
    env.connect()
    wire = install_client(env, monkeypatch)
    first = finance_turn(env, wire)
    if replay == "answer":
        payload = first["response"]
    elif replay == "wrapped_answer":
        payload = "Please summarize this:\n" + first["response"] + "\nUse plain words."
    elif replay == "tool_render":
        payload = json.dumps(tool_data(wire), indent=2)
    elif replay == "stripped_rows":
        payload = tool_data(wire)["data"]["accounts"]
    else:
        payload = env.rpc("qonto.accounts")["result"]
    env.rpc("qonto.disconnect")
    database.dispose_engine()
    database.init_db()
    before, count = reservations(), len(wire.calls)
    response = env.rpc(
        "chat.send",
        message="Explain this",
        conversation_id="new-ordinary",
        conversation_history=[{"role": "assistant", "content": payload}],
    )
    assert response.get("error"), response
    assert reservations() == before and len(wire.calls) == count
    assert env.rpc("narration.predict", message=payload).get("error")
    assert env.rpc("narration.summarize", lines=[payload], context="Summarize").get("error")
    assert reservations() == before


def test_new_managed_context_rejects_known_answer(env, monkeypatch):
    env.connect()
    wire = install_client(env, monkeypatch)
    first = finance_turn(env, wire)
    before = reservations()
    assert turn(env, conversation="new-finance", message=first["response"]).get("error")
    assert reservations() == before


def test_legacy_raw_history_without_bank_tools(env, monkeypatch):
    env.connect()
    wire = install_client(env, monkeypatch)
    wire.answer("The ordinary reply.")
    raw = [
        {"role": "user", "content": "My authored fact is EUR 100.43."},
        {"role": "assistant", "content": "Thanks for the fact."},
    ]
    result = env.rpc(
        "chat.send", message="Explain my fact", conversation_id="ordinary", conversation_history=raw
    )
    assert result["result"]["response"] == "The ordinary reply."
    assert "history_handle" not in result["result"]
    assert wire.calls[0]["messages"][:2] == raw
    assert not any(t["name"].startswith("qonto_") for t in wire.calls[0].get("tools", []))


def test_generation_mismatch_cannot_mark(env):
    env.connect()
    guard = admit({"history_mode": "managed_finance", "conversation_id": "mismatch"})
    with history.turn_scope(guard), pytest.raises(history.HistoryAuthorizationError):
        history.mark_finance_evidence(
            {"generation": guard.binding.generation + 1, "organization_id": "org-id", "sources": []}
        )
    with profile_transaction() as session:
        assert not session.get(QontoConversation, guard.handle).finance_marked
    history.abort(guard)


def test_central_reservation_and_late_delivery_guard(env, monkeypatch):
    env.connect()
    wire = install_client(env, monkeypatch)
    from zylch.llm import make_llm_client

    client = make_llm_client()
    guard = admit({"history_mode": "managed_finance", "conversation_id": "central"})
    wire.callback = lambda _: env.rpc("qonto.disconnect")
    with history.turn_scope(guard):
        with pytest.raises(history.HistoryAuthorizationError):
            asyncio.run(client.create_message(messages=[{"role": "user", "content": "Read once"}]))
        assert reservations() == 1
        with pytest.raises(history.HistoryAuthorizationError):
            client.create_message_sync(messages=[{"role": "user", "content": "Try again"}])
        assert reservations() == 1 and len(wire.calls) == 1
    history.abort(guard)


def test_scope_change_after_source_prevents_next_model(env, monkeypatch):
    env.connect()
    wire = install_client(env, monkeypatch)
    wire.tool("qonto_accounts")
    original = history.mark_finance_evidence

    def mark_and_disconnect(*args, **kwargs):
        original(*args, **kwargs)
        from zylch.qonto.connection import disconnect

        disconnect()

    monkeypatch.setattr(history, "mark_finance_evidence", mark_and_disconnect)
    assert turn(env).get("error")
    assert reservations() == 1 and len(wire.calls) == 1
    with profile_transaction() as session:
        row = session.query(QontoConversation).one()
        assert row.finance_marked and row.tombstoned
        assert session.query(QontoEvidenceReceipt).count() > 0


def test_compaction_mark_persists_and_expiry_refuses(env, monkeypatch):
    from zylch.services import chat_compaction

    env.connect()
    guard = admit({"history_mode": "managed_finance", "conversation_id": "compact"})
    authority, live = active_binding()
    result = {
        "generation": live.generation,
        "organization_id": live.organization_id,
        "sources": [{"source_id": "qonto:fixture", "source_revision": "revision"}],
        "accounts": [{"balance": "100.43"}],
    }
    canonical = [
        {"role": "assistant", "content": "Financial sentence " + str(i)} for i in range(16)
    ]
    calls = []

    async def summarize(value):
        calls.append(value)
        return "Earlier selected account balance was EUR 100.43."

    monkeypatch.setattr(chat_compaction, "_summarize", summarize)
    with history.turn_scope(guard):
        history.mark_finance_evidence(result)
        compacted = asyncio.run(chat_compaction.compact_if_needed(canonical, soft_limit=0))
        assert len(compacted) < len(canonical)
        with profile_transaction() as session:
            row = session.get(QontoConversation, guard.handle)
            assert row.finance_marked and row.canonical_history == compacted
        signin(expired=True)
        with pytest.raises(history.HistoryAuthorizationError):
            asyncio.run(chat_compaction.compact_if_needed(canonical, soft_limit=0))
        assert len(calls) == 1
    history.abort(guard)


def test_duplicate_revision_refuses(env, monkeypatch):
    env.connect()
    wire = install_client(env, monkeypatch)
    first = finance_turn(env, wire)
    wire.answer("Next answer.")
    assert turn(env, **binding(first))["result"]["history_revision"] == 2
    before = reservations()
    assert turn(env, **binding(first)).get("error")
    assert reservations() == before


@pytest.mark.parametrize("change", ["disconnect", "expiry", "company", "host"])
def test_real_compaction_followup_cannot_replay_after_scope_change(env, monkeypatch, change):
    env.connect()
    wire = install_client(env, monkeypatch)
    first = finance_turn(env, wire)
    with profile_transaction() as session:
        row = session.get(QontoConversation, first["history_handle"])
        row.canonical_history = row.canonical_history + [
            {
                "role": "assistant",
                "content": ("Selected account EUR 100.43, retained source " + str(i) + ". ") * 800,
            }
            for i in range(16)
        ]
    wire.answer("The retained selected account balance was EUR 100.43.")
    wire.answer("The compacted answer retains source provenance.")
    compacted = turn(env, message="Explain the earlier balance", **binding(first))["result"]
    assert compacted["history_revision"] == 2
    with profile_transaction() as session:
        row = session.get(QontoConversation, compacted["history_handle"])
        summary = next(
            m["content"]
            for m in row.canonical_history
            if isinstance(m.get("content"), str)
            and m["content"].startswith("[Previous conversation summary")
        )
        assert row.finance_marked and row.source_references
    before, count = reservations(), len(wire.calls)
    if change == "disconnect":
        env.rpc("qonto.disconnect")
    elif change == "expiry":
        signin(expired=True)
    elif change == "company":
        monkeypatch.setenv("MEMORY_KEY", "new-company")
    else:
        (env.home / "engine-installation-id").write_text("wrong-host")
    assert turn(env, **binding(compacted)).get("error")
    assert env.rpc(
        "chat.send",
        message="Continue",
        conversation_id="summary-replay",
        conversation_history=[{"role": "user", "content": summary}],
    ).get("error")
    assert reservations() == before and len(wire.calls) == count


def test_central_independent_call_cannot_replay_direct_source_evidence(env, monkeypatch):
    env.connect()
    direct = env.rpc("qonto.accounts")["result"]
    wire = install_client(env, monkeypatch)
    from zylch.llm import make_llm_client

    env.rpc("qonto.disconnect")
    before = reservations()
    with pytest.raises(history.HistoryAuthorizationError):
        make_llm_client().create_message_sync(
            messages=[{"role": "user", "content": json.dumps(direct)}]
        )
    assert reservations() == before and not wire.calls


def test_cross_turn_claim_prevents_duplicate_engine_handle_use(env):
    env.connect()
    params = {"history_mode": "managed_finance", "conversation_id": "claimed"}
    guard = admit(params)
    with pytest.raises(history.HistoryAuthorizationError):
        admit({**params, "history_handle": guard.handle, "history_revision": 0})
    history.abort(guard)
    resumed = admit({**params, "history_handle": guard.handle, "history_revision": 0})
    assert resumed.handle == guard.handle
    history.abort(resumed)


def test_finishing_then_disconnect_suppresses_outer_rpc_delivery(env, monkeypatch):
    env.connect()
    wire = install_client(env, monkeypatch)
    wire.answer("Late financial reply.")
    original = history.finish

    def finish_then_disconnect(*args, **kwargs):
        result = original(*args, **kwargs)
        from zylch.qonto.connection import disconnect

        disconnect()
        return result

    monkeypatch.setattr(history, "finish", finish_then_disconnect)
    assert turn(env).get("error")
    assert reservations() == 1 and len(wire.calls) == 1


def test_compaction_does_not_receipt_human_authored_head_or_tail(env):
    env.connect()
    guard = admit({"history_mode": "managed_finance", "conversation_id": "human-facts"})
    result = {
        "generation": guard.binding.generation,
        "organization_id": "org-id",
        "sources": [],
        "accounts": [],
    }
    human = "My newly authored balance fact is EUR 321.09."
    summary = "The engine-generated financial summary is retained."
    canonical = [{"role": "user", "content": human}, {"role": "user", "content": summary}]
    with history.turn_scope(guard):
        history.mark_finance_evidence(result)
        history.persist_compaction(canonical, rendered_summary=summary)
    history.abort(guard)
    assert admit({"conversation_id": "human-replay", "message": human}) is None
    with pytest.raises(history.HistoryAuthorizationError):
        admit({"conversation_id": "engine-replay", "message": summary})
