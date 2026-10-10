"""Fresh provider authority before retained history reaches any paid call."""

import asyncio

import httpx
import pytest

from zylch.qonto.models import QontoConversation
from zylch.qonto.repository import profile_transaction, read_binding

from .chat_fixture import install_client, reservations, turn
from .conftest import UID, signin
from .test_history_authorization import binding, finance_turn


@pytest.mark.parametrize("failure", ["auth", "network", "organization", "account"])
def test_no_tool_followup_requires_live_source_authority(env, http_api, monkeypatch, failure):
    env.connect()
    wire = install_client(env, monkeypatch)
    first = finance_turn(env, wire)
    if failure == "auth":
        http_api.callback = lambda request: httpx.Response(401)
    elif failure == "network":

        def unreachable(request):
            raise httpx.ConnectError("Fixture network failure", request=request)

        http_api.callback = unreachable
    elif failure == "organization":
        http_api.organization["id"] = "different-org"
    else:
        http_api.organization["bank_accounts"] = []
    before, calls, requests = reservations(), len(wire.calls), len(http_api.requests)
    wire.answer("A prohibited repeat of the earlier source balance.")
    response = turn(
        env, message="Repeat the prior source balance without reading a new tool.", **binding(first)
    )
    assert response.get("error"), response
    assert reservations() == before and len(wire.calls) == calls
    assert len(http_api.requests) == requests + 1
    assert http_api.requests[-1].url.path == "/v2/organization"
    if failure == "auth":
        current = read_binding(UID)
        assert current.status == "auth_failed" and current.encrypted_credentials is None
        with profile_transaction() as session:
            assert session.get(QontoConversation, first["history_handle"]).tombstoned


def test_ordinary_history_does_not_probe_qonto(env, http_api, monkeypatch):
    env.connect()
    wire = install_client(env, monkeypatch)
    requests = len(http_api.requests)
    wire.answer("Ordinary followup.")
    response = env.rpc(
        "chat.send",
        message="Explain my note",
        conversation_id="ordinary",
        conversation_history=[{"role": "user", "content": "My note"}],
    )
    assert "result" in response
    assert len(http_api.requests) == requests


def test_malformed_binding_refuses_before_live_probe(env, http_api, monkeypatch):
    env.connect()
    wire = install_client(env, monkeypatch)
    first = finance_turn(env, wire)
    requests, paid = len(http_api.requests), reservations()
    invalid = {**binding(first), "history_revision": 0}
    assert turn(env, **invalid).get("error")
    assert len(http_api.requests) == requests and reservations() == paid


def test_network_failure_does_not_orphan_new_empty_history(env, http_api, monkeypatch):
    env.connect()
    wire = install_client(env, monkeypatch)

    def unreachable(request):
        raise httpx.ConnectError("Fixture network failure", request=request)

    http_api.callback = unreachable
    before = reservations()
    assert turn(env).get("error")
    with profile_transaction() as session:
        assert session.query(QontoConversation).count() == 0
    assert reservations() == before and not wire.calls
    http_api.callback = None
    wire.answer("The fresh source was authorized.")
    assert turn(env)["result"]["history_revision"] == 1


@pytest.mark.parametrize("change", ["disconnect", "session", "company", "host"])
def test_binding_is_rechecked_across_blocked_live_probe(env, http_api, monkeypatch, change):
    env.connect()
    wire = install_client(env, monkeypatch)
    first = finance_turn(env, wire)
    paid, calls = reservations(), len(wire.calls)

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def blocked(request):
            entered.set()
            await release.wait()
            return httpx.Response(200, json={"organization": http_api.organization})

        http_api.callback = blocked
        task = asyncio.create_task(
            env.arpc(
                "chat.send",
                message="Repeat prior answer",
                conversation_id="finance-fixture",
                history_mode="managed_finance",
                **binding(first),
            )
        )
        await asyncio.wait_for(entered.wait(), 5)
        if change == "disconnect":
            assert (await env.arpc("qonto.disconnect"))["result"]["ok"]
        elif change == "session":
            signin(expired=True)
        elif change == "company":
            monkeypatch.setenv("MEMORY_KEY", "other-company")
        else:
            (env.home / "engine-installation-id").write_text("wrong-host")
        release.set()
        assert (await task).get("error")

    asyncio.run(scenario())
    assert reservations() == paid and len(wire.calls) == calls


@pytest.mark.parametrize(
    "acknowledgement",
    [
        "OK",
        "Okay.",
        "Thanks!",
        "Done",
        "Grazie",
        "OK, thanks.",
        "Okay and thank you!",
        "Sure; understood.",
        "Yes — thanks!",
        "Thanks, got it.",
        "Done and finished.",
        "Va bene, grazie!",
        "D’accord et merci.",
        "Vale y gracias.",
        "Danke und verstanden.",
        "OK.\nThanks.",
        "Okay, thanks and done!",
        "Thank you very much, noted.",
        "D'accordo e capito, grazie.",
        "De acuerdo, muchas gracias.",
        "Bien reçu et merci beaucoup.",
        "In Ordnung und vielen Dank.",
        "Got it and also thanks.",
        '"Okay, thanks."',
    ],
)
@pytest.mark.parametrize("wrapped", [False, True])
def test_generic_finance_acknowledgement_preserves_ordinary_chat(
    env, http_api, monkeypatch, acknowledgement, wrapped
):
    env.connect()
    wire = install_client(env, monkeypatch)
    wire.tool("qonto_accounts")
    wire.answer(acknowledgement)
    assert turn(env)["result"]["response"] == acknowledgement
    before, requests = reservations(), len(http_api.requests)
    message = acknowledgement + ", please find my ordinary email." if wrapped else acknowledgement
    wire.answer("Your ordinary email request was handled.")
    response = env.rpc("chat.send", message=message, conversation_id="ordinary-after-finance")
    assert response.get("result"), response
    assert reservations() == before + 1
    assert len(http_api.requests) == requests


def test_acknowledgement_policy_preserves_known_substantial_finance_replay_refusal(
    env, http_api, monkeypatch
):
    env.connect()
    wire = install_client(env, monkeypatch)
    first = finance_turn(env, wire)
    paid = reservations()
    assert env.rpc(
        "chat.send",
        message="Please explain: " + first["response"],
        conversation_id="ordinary-bank-replay",
    ).get("error")
    assert reservations() == paid


def test_live_admission_preserves_busy_and_cancelled_turn_cleanup(env, http_api, monkeypatch):
    from zylch.rpc.methods import _active_chats

    env.connect()
    wire = install_client(env, monkeypatch)
    first = finance_turn(env, wire)
    paid, calls, requests = reservations(), len(wire.calls), len(http_api.requests)

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def blocked(request):
            entered.set()
            await release.wait()
            return httpx.Response(200, json={"organization": http_api.organization})

        http_api.callback = blocked
        params = {
            "message": "Continue",
            "conversation_id": "finance-fixture",
            "history_mode": "managed_finance",
            **binding(first),
        }
        task = asyncio.create_task(env.arpc("chat.send", **params))
        await asyncio.wait_for(entered.wait(), 5)
        duplicate = await env.arpc("chat.send", **params)
        assert duplicate.get("error")
        assert len(http_api.requests) == requests + 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert "finance-fixture" not in _active_chats

    asyncio.run(scenario())
    assert reservations() == paid and len(wire.calls) == calls


@pytest.mark.parametrize(
    "answer",
    [
        "OK, the selected account balance is EUR 100.43.",
        "Thanks, transaction status completed.",
        "OK and GBP 10.00.",
        "Sure, account-eur.",
        "OK, €100.",
        "EUR 100.43",
    ],
)
def test_acknowledgement_grammar_never_exempts_financial_payload(
    env, http_api, monkeypatch, answer
):
    env.connect()
    wire = install_client(env, monkeypatch)
    wire.tool("qonto_accounts")
    wire.answer(answer)
    assert turn(env)["result"]["response"] == answer
    paid = reservations()
    replay = env.rpc(
        "chat.send", message="Please explain: " + answer, conversation_id="ordinary-bank-replay"
    )
    assert replay.get("error"), replay
    assert reservations() == paid


def test_acknowledgement_grammar_is_bounded_and_whole_string():
    from zylch.qonto.history_receipts import acknowledgement_only

    assert acknowledgement_only("OK, thanks.")
    assert acknowledgement_only("Okay and thank you!")
    assert not acknowledgement_only("OK, thanks. Please find my ordinary email.")
    assert not acknowledgement_only("OK and")
    assert not acknowledgement_only("OK, 100.43")
    assert not acknowledgement_only("OK " * 17)
    assert not acknowledgement_only("Thanks " * 100)


def test_compound_acknowledgement_keeps_structured_bank_tool_receipts(env, http_api, monkeypatch):
    import json
    from .chat_fixture import tool_data

    env.connect()
    wire = install_client(env, monkeypatch)
    wire.tool("qonto_accounts")
    wire.answer("OK, thanks.")
    assert turn(env)["result"]["response"] == "OK, thanks."
    paid = reservations()
    copied = json.dumps(tool_data(wire)["data"]["accounts"])
    response = env.rpc(
        "chat.send",
        message="Explain these",
        conversation_id="ordinary-structured-replay",
        conversation_history=[{"role": "assistant", "content": copied}],
    )
    assert response.get("error"), response
    assert reservations() == paid
