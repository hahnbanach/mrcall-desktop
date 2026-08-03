"""Executable boundary checks for the engine/app JSON-RPC contract."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest

from zylch.rpc.dispatch import (
    INVALID_PARAMS,
    _NON_SECRET_PARAM_KEYS_BY_METHOD,
    _redact_params,
    dispatch_raw,
)
from zylch.rpc.methods import METHODS
from zylch.rpc.param_spec import ACCEPTED_PARAMS, OPEN_METHODS, REQUIRED_PARAMS

#: The two rejections the DISPATCHER itself emits before a handler runs.
#: A handler is free to answer -32602 on its own (``chat.approve`` does,
#: for an unknown tool_use_id) — that is a real answer, not a refusal to
#: route, so the gates below match on the message, not just the code.
_MISSING_PREFIX = "Missing required parameter(s) for"
_UNKNOWN_PREFIX = "Unknown parameter(s) for"


def _request(method: str, params: object) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": 7, "method": method, "params": params})


def _notify(_method: str, _params: dict) -> None:
    """Same shape as the transports' notifier: sync, fire-and-forget."""
    return None


@pytest.mark.asyncio
async def test_dispatch_rejects_unknown_parameter_before_handler_runs():
    response = await dispatch_raw(
        _request("tasks.list", {"include_completed": False, "statuz": "open"}),
        _notify,
    )

    assert response is not None
    assert response["error"]["code"] == INVALID_PARAMS
    assert "statuz" in response["error"]["message"]


@pytest.mark.asyncio
async def test_dispatch_classifies_missing_required_parameter_as_invalid_params():
    response = await dispatch_raw(_request("tasks.complete", {}), _notify)

    assert response is not None
    assert response["error"]["code"] == INVALID_PARAMS


def test_every_registered_method_has_a_checkable_parameter_declaration():
    """A new handler cannot silently opt out of unknown-param validation."""
    assert not OPEN_METHODS
    assert set(ACCEPTED_PARAMS) == set(METHODS)


def test_required_params_are_a_subset_of_accepted_params():
    """The two docstring parsers cannot drift apart.

    A name the missing-param gate demands but the unknown-param gate
    rejects would make the method uncallable in both directions.
    """
    for method, required in REQUIRED_PARAMS.items():
        assert required <= ACCEPTED_PARAMS[method], method


# ─── Exhaustive minimal-payload gate ──────────────────────────────────
#
# Every method, driven with exactly the parameters its docstring marks
# mandatory, must reach its handler. This is the executable form of the
# rule the missing-param gate has to obey: a param is required only when
# the handler genuinely cannot proceed without it. A docstring typo that
# promotes an optional param to mandatory bricks the method for every
# independent consumer, and used to do so silently.

#: Methods this gate cannot safely invoke, each with the reason. Kept
#: visible (and asserted below) so the list cannot rot into an alibi.
_MINIMAL_PAYLOAD_EXEMPT = {
    "whatsapp.connect": (
        "blocks on the neonize pairing loop waiting for a QR scan; there "
        "is no offline path through it"
    ),
}

_SYNTHETIC_DICT_PARAMS = {"values", "updates", "context", "sources", "edited_input"}
_SYNTHETIC_LIST_PARAMS = {"lines", "conversation_history"}
_SYNTHETIC_BOOL_PARAMS = {"pinned", "approved", "action_required", "forget_session"}
_SYNTHETIC_INT_PARAMS = {"expires_at_ms", "limit", "offset", "days", "due_at"}


def _synthetic(name: str):
    """A plausible value for a parameter, from its name alone."""
    if name in _SYNTHETIC_DICT_PARAMS:
        return {}
    if name in _SYNTHETIC_LIST_PARAMS:
        return []
    if name in _SYNTHETIC_BOOL_PARAMS:
        return True
    if name in _SYNTHETIC_INT_PARAMS:
        return 1
    if "email" in name:
        return "contract-probe@example.test"
    if name == "chat_jid":
        return "390000000000@s.whatsapp.net"
    return f"contract-probe-{name}"


@pytest.fixture
def offline_engine(tmp_path, monkeypatch):
    """A throwaway profile the whole RPC surface can be driven against.

    Isolation, in order of how much damage it prevents:

    - ``HOME`` points at a temp dir, so nothing can read or write the
      real ``~/.zylch`` (``profiles.create`` writes a profile directory).
    - the active profile's ``.env`` carries NO credentials, so no handler
      can authenticate to anything even if it tried.
    - the httpx TRANSPORTS refuse to send, so an HTTP call is an error
      rather than a packet. Patched at ``handle_request`` and not by
      swapping ``httpx.Client`` itself: third-party modules evaluate
      annotations like ``httpx.Client | None`` at import time, and a
      class replaced by a function makes that a TypeError which then
      sticks in ``sys.modules`` for the rest of the session.
    - the LLM factories are neutered, so nothing bills a token.
    """
    home = tmp_path / "home"
    profile = home / ".zylch" / "profiles" / "contract-probe"
    profile.mkdir(parents=True)
    (profile / ".env").write_text("EMAIL_ADDRESS=contract-probe@example.test\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(profile))
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "contract.db"))

    import httpx

    import zylch.llm as llm_mod
    from zylch.auth.session import clear_session
    from zylch.storage import database as db_mod

    def _no_network(*_args, **_kwargs):
        raise RuntimeError("network is blocked in the contract-boundary test")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _no_network)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _no_network)
    monkeypatch.setattr(llm_mod, "make_llm_client", _no_network)
    monkeypatch.setattr(llm_mod, "try_make_llm_client", lambda *a, **k: None)

    db_mod.dispose_engine()
    db_mod.init_db()
    try:
        yield profile
    finally:
        # `account.set_firebase_token` installs a process-global session;
        # do not leak it into the rest of the suite.
        clear_session()
        db_mod.dispose_engine()


def test_minimal_payload_exemptions_name_real_methods():
    assert set(_MINIMAL_PAYLOAD_EXEMPT) <= set(METHODS)
    assert all(reason for reason in _MINIMAL_PAYLOAD_EXEMPT.values())


@pytest.mark.asyncio
async def test_every_method_accepts_its_documented_minimal_payload(offline_engine):
    """No method may reject the payload its own docstring declares sufficient."""
    refused: list[str] = []

    for method in sorted(METHODS):
        if method in _MINIMAL_PAYLOAD_EXEMPT:
            continue
        params = {name: _synthetic(name) for name in sorted(REQUIRED_PARAMS.get(method, set()))}
        response = await dispatch_raw(_request(method, params), _notify)

        assert response is not None, method
        error = response.get("error")
        if error and (
            error["message"].startswith(_MISSING_PREFIX)
            or error["message"].startswith(_UNKNOWN_PREFIX)
        ):
            refused.append(f"{method} {sorted(params)} -> {error['message']}")

    assert not refused, "dispatcher refused a documented-minimal payload:\n" + "\n".join(refused)


@pytest.mark.asyncio
async def test_every_required_param_is_one_the_handler_cannot_do_without(offline_engine):
    """Leave-one-out: prove each `required` mark is earned, not assumed.

    The gate above cannot catch an over-strict docstring — it builds the
    payload FROM the required set, so adding a name there also adds it to
    the payload. This one asks the opposite question, of the handler
    directly (deliberately bypassing the dispatcher's own gate): drop one
    required param, and see whether the handler still does the work.

    If it does — `emails.search` without `query` returns every thread in
    the folder, `whatsapp.send_message` without `text` answers
    `{ok: false, error: …}` — then marking that param required turns an
    answer the engine has always given into a -32602, which breaks every
    independent consumer that relied on the default.

    "Cannot proceed" means the handler RAISES. A returned `{ok: false}`
    is a well-formed answer the caller can render, not a failure, so it
    counts as served: that param is optional and its docstring must say
    so with a trailing `?`.
    """
    unjustified: list[str] = []

    for method in sorted(REQUIRED_PARAMS):
        if method in _MINIMAL_PAYLOAD_EXEMPT:
            continue
        for dropped in sorted(REQUIRED_PARAMS[method]):
            params = {
                name: _synthetic(name)
                for name in sorted(REQUIRED_PARAMS[method])
                if name != dropped
            }
            try:
                result = await METHODS[method](params, _notify)
            except Exception:  # noqa: BLE001 — any raise IS "cannot proceed"
                continue
            unjustified.append(f"{method} without {dropped!r} still served: {result!r}"[:200])

    assert not unjustified, (
        "these params are marked required but the handler answers without them,\n"
        "so the missing-param gate would reject traffic the engine used to serve:\n"
        + "\n".join(unjustified)
    )


# ─── Preload ↔ engine registry ────────────────────────────────────────

#: Bindings the preload is known to expose. A floor, not an equality:
#: adding an RPC to the app must not require touching this test, but
#: an extractor that quietly stops seeing half the file must fail it.
_PRELOAD_BINDING_FLOOR = 50


def test_every_preload_rpc_binding_targets_a_registered_engine_method():
    """Catch preload typos/removals without importing Electron in Python."""
    preload = Path(__file__).parents[3] / "app" / "src" / "preload" / "index.ts"
    if not preload.is_file():
        pytest.skip(f"engine-only checkout: {preload} is absent")
    source = preload.read_text(encoding="utf-8")
    # The generic type argument may span lines and contain `;` (object
    # literals like `call<{ ok: boolean; error?: string }>('x', …)`), so
    # the body must be matched with `[\s\S]` rather than a `;`-free run —
    # the old `[^;]+?` form silently missed 15 of the 52 bindings.
    bound_methods = set(re.findall(r"call(?:<[\s\S]*?>)?\(\s*['\"]([\w.]+)['\"]", source))

    assert (
        len(bound_methods) >= _PRELOAD_BINDING_FLOOR
    ), f"preload RPC extractor found only {len(bound_methods)} bindings: {sorted(bound_methods)}"
    assert bound_methods <= set(METHODS), sorted(bound_methods - set(METHODS))


# ─── Redaction ────────────────────────────────────────────────────────


def test_top_level_secret_values_are_redacted_without_mutating_input():
    params = {"id_token": "jwt-value", "api_key": "key-value", "label": "safe"}

    redacted = _redact_params("account.set_firebase_token", params)

    assert params["id_token"] == "jwt-value"
    assert redacted == {
        "id_token": "<redacted len=9>",
        "api_key": "<redacted len=9>",
        "label": "safe",
    }


def test_nested_secret_values_are_redacted_recursively():
    secret = "nested-super-secret"
    params = {
        "context": {"credentials": [{"password": secret}, {"session": {"access_token": secret}}]}
    }

    rendered = repr(_redact_params("chat.send", params))

    assert secret not in rendered


#: The bare words a caller reaches for when it has no better name. All
#: six reached the DEBUG dispatch line verbatim before 2026-08.
_PLAN_SECRET_WORDS = ("token", "session", "credential", "secret", "password", "key")


@pytest.mark.asyncio
async def test_dispatch_success_log_redacts_every_plan_secret_word(caplog, monkeypatch):
    """Drive the real dispatcher and read the real log line."""
    values = {word: f"live-{word}-material-9f3a" for word in _PLAN_SECRET_WORDS}
    params = dict(values)
    params["nested"] = {"credentials": [{"passwd": "live-passwd-material-9f3a"}]}
    params["label"] = "not-a-secret"

    async def sink(_params, _notify):
        return {"ok": True}

    monkeypatch.setitem(METHODS, "contract.secret_sink", sink)
    monkeypatch.setitem(ACCEPTED_PARAMS, "contract.secret_sink", set(params))
    caplog.set_level(logging.DEBUG, logger="zylch.rpc.dispatch")

    response = await dispatch_raw(_request("contract.secret_sink", params), _notify)

    assert response is not None and response.get("result") == {"ok": True}
    assert "[rpc] method=contract.secret_sink params=" in caplog.text
    assert "not-a-secret" in caplog.text, "the log line must stay useful"
    leaked = [word for word, value in values.items() if value in caplog.text]
    assert not leaked, f"secret values reached the DEBUG line for: {leaked}"
    assert "live-passwd-material-9f3a" not in caplog.text


@pytest.mark.asyncio
async def test_compound_secret_names_are_redacted_but_usage_counters_are_not():
    params = {
        "firebase_id_token": "compound-token-value",
        "smtp_password": "compound-password-value",
        "x_api_key": "compound-key-value",
        "device_session": "compound-session-value",
        "vault_credential": "compound-credential-value",
        "shared_secret": "compound-secret-value",
        "input_tokens": 4096,
        "output_tokens": 128,
    }

    redacted = _redact_params("contract.whatever", params)

    for name in [k for k in params if k.startswith(("firebase", "smtp", "x_", "device", "vault"))]:
        assert redacted[name].startswith("<redacted"), name
    assert redacted["shared_secret"].startswith("<redacted")
    assert redacted["input_tokens"] == 4096
    assert redacted["output_tokens"] == 128


def test_non_secret_carve_out_is_per_method_and_not_a_hole():
    """`agents.get_prompt(key=…)` names a prompt; every other `key` is a secret."""
    assert _NON_SECRET_PARAM_KEYS_BY_METHOD["agents.get_prompt"] == {"key"}

    assert _redact_params("agents.get_prompt", {"key": "task_email"}) == {"key": "task_email"}
    assert _redact_params("settings.get", {"key": "task_email"}) == {"key": "<redacted len=10>"}
    # The carve-out exempts the NAME, never the subtree under it.
    assert _redact_params("agents.get_prompt", {"key": {"api_key": "sk-live"}}) == {
        "key": {"api_key": "<redacted len=7>"}
    }


def test_settings_update_keeps_preference_names_readable_but_masks_secret_settings():
    """`settings.update` takes `updates`, not `key` — the names are the dict's.

    The plan flagged a `key` param on this method; it has none. What it
    does carry is a `{setting_name: value}` map, and the two cases have
    to behave differently: a preference name must stay readable for
    debugging, a credential-shaped one must not.
    """
    assert "key" not in ACCEPTED_PARAMS["settings.update"]

    redacted = _redact_params(
        "settings.update",
        {"updates": {"LLM_PROVIDER": "mrcall", "ANTHROPIC_API_KEY": "sk-ant-live"}},
    )

    assert redacted["updates"]["LLM_PROVIDER"] == "mrcall"
    assert redacted["updates"]["ANTHROPIC_API_KEY"] == "<redacted len=11>"


@pytest.mark.asyncio
async def test_exception_log_does_not_echo_top_level_secret(caplog, monkeypatch):
    secret = "exception-path-secret"

    async def exploding_handler(_params, _notify):
        raise RuntimeError("synthetic failure")

    monkeypatch.setitem(METHODS, "contract.explode", exploding_handler)
    monkeypatch.setitem(ACCEPTED_PARAMS, "contract.explode", {"password"})
    caplog.set_level(logging.DEBUG, logger="zylch.rpc.dispatch")

    response = await dispatch_raw(_request("contract.explode", {"password": secret}), _notify)

    assert response is not None
    assert secret not in caplog.text
