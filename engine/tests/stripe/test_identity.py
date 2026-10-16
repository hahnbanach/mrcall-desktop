"""Real Stripe identity checks with isolated authenticated profiles."""

import time

import pytest

from zylch.auth import clear_session, set_session
from zylch.stripe.identity import current_authority
from tests.qonto.conftest import UID


@pytest.mark.parametrize("mode", ["missing", "other_uid", "expired"])
def test_invalid_firebase_session_refused(env, mode):
    if mode == "missing":
        clear_session()
    else:
        set_session(
            "other" if mode == "other_uid" else UID,
            None,
            "fixture",
            int(time.time() * 1000) + (-1000 if mode == "expired" else 3600000),
        )
    result = env.rpc("stripe.test", api_key="rk_test_" + "a" * 32)
    assert "error" in result
    assert ("session_expired" if mode == "expired" else "identity_required") in result["error"][
        "message"
    ]


def test_real_company_and_installation_authority_without_bank_connection(env):
    actor = current_authority()
    assert actor.uid == UID
    assert actor.profile_dir == env.directory
    assert actor.host_id.startswith("local:")
    assert len(actor.company_scope) == 64
    assert env.rpc("stripe.status")["result"]["status"] == "disconnected"
    assert not env.provider.calls


def test_company_join_refused(env):
    with (env.directory / ".env").open("a") as stream:
        stream.write("MEMORY_JOIN_TO=fixture-pending\n")
    result = env.rpc("stripe.status")
    assert "company_joining" in result["error"]["message"]


def test_transferred_hosted_profile_needs_separate_private_installation(env, monkeypatch):
    from zylch import runtime

    monkeypatch.setattr(runtime, "_serving", True)
    monkeypatch.delenv("STRIPE_HOST_ID_FILE", raising=False)
    monkeypatch.delenv("QONTO_HOST_ID_FILE", raising=False)
    assert "host_identity_unavailable" in env.rpc("stripe.status")["error"]["message"]
