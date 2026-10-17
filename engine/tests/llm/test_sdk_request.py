"""No transport hands a provider a sampling keyword; the direct one adds the binding.

``anthropic`` 1.x raises ``TypeError`` for ``temperature`` / ``top_p`` /
``top_k`` before any request leaves the process, and milestone 10's one
request shape (brief D3) sends no sampling on any transport: a non-default
value is dropped too, never moved to ``extra_body``. The priced request dict
is never mutated. On the direct transport, adaptive reasoning gains the
``drop_block`` binding and its beta header. These tests pin the seam.
"""

from __future__ import annotations

import inspect

from zylch.llm.sdk_request import sdk_request


def _request(**extra):
    base = {
        "model": "claude-haiku-4-5",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 64,
        "temperature": 1.0,
        "service_tier": "standard_only",
    }
    base.update(extra)
    return base


def test_the_installed_sdk_has_no_sampling_keywords():
    from anthropic.resources.messages import Messages

    params = inspect.signature(Messages.create).parameters
    assert not {"temperature", "top_p", "top_k"} & set(params)
    assert {"extra_body", "service_tier", "max_tokens"} <= set(params)


def test_a_default_temperature_is_dropped_and_the_priced_dict_is_untouched():
    priced = _request()
    sent = sdk_request(priced, "direct")
    assert "temperature" not in sent
    assert "extra_body" not in sent
    assert priced["temperature"] == 1.0
    assert set(sent) <= set(inspect.signature(_messages_create()).parameters)


def test_a_non_default_temperature_is_dropped_too():
    # Brief D3: no sampling on any transport (it used to travel in extra_body).
    sent = sdk_request(_request(temperature=0, top_k=5), "direct")
    assert "extra_body" not in sent
    assert "temperature" not in sent and "top_k" not in sent


def test_an_existing_extra_body_keeps_its_other_keys_and_loses_sampling():
    sent = sdk_request(_request(temperature=0, extra_body={"keep": 1, "top_p": 0.5}), "direct")
    assert sent["extra_body"] == {"keep": 1}


def test_other_transports_get_the_request_without_sampling():
    priced = _request(temperature=0, extra_body={"top_k": 5})
    for transport in ("proxy", "openrouter", "openai_voice"):
        sent = sdk_request(priced, transport)
        assert not {"temperature", "top_p", "top_k", "extra_body"} & set(sent)
        assert priced["temperature"] == 0 and priced["extra_body"] == {"top_k": 5}
    plain = {k: v for k, v in _request().items() if k != "temperature"}
    for transport in ("direct", "proxy", "openrouter"):
        assert sdk_request(plain, transport) is plain


def test_adaptive_reasoning_on_direct_gains_the_drop_block_binding_and_its_beta():
    priced = _request(thinking={"type": "adaptive"}, output_config={"effort": "low"})
    sent = sdk_request(priced, "direct")
    assert sent["thinking"] == {
        "type": "adaptive",
        "block_binding": {"prefix_mismatch_behavior": "drop_block"},
    }
    assert sent["extra_headers"] == {"anthropic-beta": "thinking-binding-controls-2026-08-01"}
    assert priced["thinking"] == {"type": "adaptive"} and "extra_headers" not in priced
    inspect.signature(_messages_create()).bind(None, **sent)
    other = sdk_request({**priced, "extra_headers": {"anthropic-beta": "other-beta"}}, "direct")
    assert other["extra_headers"]["anthropic-beta"] == (
        "other-beta,thinking-binding-controls-2026-08-01"
    )
    for transport in ("proxy", "openrouter"):
        assert sdk_request(priced, transport)["thinking"] == {"type": "adaptive"}
    disabled = sdk_request(_request(thinking={"type": "disabled"}), "direct")
    assert disabled["thinking"] == {"type": "disabled"} and "extra_headers" not in disabled


def test_the_direct_client_calls_the_sdk_without_the_keyword(monkeypatch):
    """End to end through ``LLMClient``: the real SDK signature, a fake wire."""
    from types import SimpleNamespace

    from zylch.llm import budget, client as client_mod
    from zylch.llm.client import LLMClient

    llm = LLMClient(transport="direct", api_key="fake", model="claude-haiku-4-5")
    seen = {}

    def create(**kwargs):
        # Bind against the real signature so a removed keyword raises here
        # exactly as the SDK would.
        inspect.signature(_messages_create()).bind(llm._client.messages, **kwargs)
        seen.update(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="ok", refusal=None)],
            model="claude-haiku-4-5",
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            refusal=None,
        )

    llm._client.messages.create = create
    monkeypatch.setattr(budget, "reserve", lambda *a, **k: None)
    monkeypatch.setattr(budget, "settle", lambda *a, **k: None)
    monkeypatch.setattr(client_mod, "validate_response_model", lambda *a, **k: None, raising=False)
    from zylch.services import preparation

    monkeypatch.setattr(preparation, "check_dispatch", lambda: None)
    monkeypatch.setattr(preparation, "record_dispatch", lambda: None)
    llm.create_message_sync([{"role": "user", "content": "hi"}], max_tokens=8, temperature=0)
    assert "temperature" not in seen
    assert "extra_body" not in seen  # brief D3: dropped, not moved to extra_body


def _messages_create():
    from anthropic.resources.messages import Messages

    return Messages.create
