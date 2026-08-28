"""What `settings.get_secret` will hand over, and what it refuses.

`settings.get` masks every secret because it returns all keys at once and
is what a UI renders. This method is the deliberate other door: one key per
call, secrets only, so a clone stamped on a machine that is not the
engine's can read the mailbox credential the engine already uses instead of
asking a human to paste an app password.

Its access decision is NOT here — it is `server_ws.py`, which gates every
connection on `token.sub == OWNER_ID`. What is asserted here is the
handler's own contract: a non-secret key is refused rather than served
(that is `settings.get`'s job, unmasked), a missing key is refused, an
unset secret is an empty string rather than an error, and the value comes
back verbatim.

`read_env` is stubbed: it is exercised against a real file by the settings
tests, and stubbing keeps these about the handler's decisions.
"""

from __future__ import annotations

import asyncio

import pytest

from zylch.rpc import methods
from zylch.services import settings_io


ENV = {
    "EMAIL_PASSWORD": "abcd efgh ijkl mnop",
    "EMAIL_ADDRESS": "support@example.test",
}


def _notify(*_a, **_k):
    return None


@pytest.fixture(autouse=True)
def _stub_env(monkeypatch):
    monkeypatch.setattr(settings_io, "read_env", lambda: dict(ENV))


def _call(params):
    return asyncio.run(methods.settings_get_secret(params, _notify))


def test_secret_key_is_returned_verbatim():
    assert _call({"key": "EMAIL_PASSWORD"}) == {
        "key": "EMAIL_PASSWORD",
        "value": "abcd efgh ijkl mnop",
    }


def test_whitespace_around_the_key_is_tolerated():
    assert _call({"key": "  EMAIL_PASSWORD  "})["value"] == "abcd efgh ijkl mnop"


def test_a_non_secret_key_is_refused_and_says_where_to_read_it():
    with pytest.raises(ValueError) as e:
        _call({"key": "EMAIL_ADDRESS"})
    assert "settings.get" in str(e.value)


def test_an_unknown_key_is_refused_rather_than_served_empty():
    with pytest.raises(ValueError):
        _call({"key": "NOT_A_SETTING"})


def test_a_missing_key_is_refused():
    with pytest.raises(ValueError):
        _call({})


def test_an_unset_secret_is_empty_not_an_error(monkeypatch):
    monkeypatch.setattr(settings_io, "read_env", lambda: {})
    assert _call({"key": "EMAIL_PASSWORD"}) == {"key": "EMAIL_PASSWORD", "value": ""}


def test_the_method_is_reachable_under_its_wire_name():
    assert methods.METHODS["settings.get_secret"] is methods.settings_get_secret
