"""Tests for `zylch.llm.proxy_client.MrCallProxyClient`.

We mock the proxy server with `httpx.MockTransport` (no `respx` in the
repo, no extra dep) and verify:

  1. Happy streaming path: SSE events reconstruct into a Message with
     the expected `.content`, `.usage`, `.stop_reason`.
  2. 402 → MrCallInsufficientCredits with parsed `available` / `topup_url`.
  3. 401 → MrCallAuthError raised so the caller can re-auth.
  4. Auth header: `auth: <id_token>` (no Bearer prefix), value pulled
     from `firebase_session.id_token`.
  5. Body forwarding: model / messages / max_tokens / stream forwarded;
     temperature / tools / system pass through when present; `stream`
     is forced to True regardless of caller intent.

We do NOT spin up a network listener — `httpx.MockTransport` lets us
intercept the call inside the same process and assert on what the proxy
client actually sent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Optional, Tuple

import httpx
import pytest

from zylch.llm.proxy_client import (
    MrCallAuthError,
    MrCallInsufficientCredits,
    MrCallProxyClient,
    MrCallProxyError,
)


# ─── Helpers ──────────────────────────────────────────────────────────


@dataclass
class _FakeSession:
    """Stand-in for `zylch.auth.session.FirebaseSession`."""

    id_token: str = "fake-jwt-token-for-tests"
    uid: str = "uid-test"
    email: Optional[str] = "user@example.com"


def _sse(events: List[Tuple[str, dict]]) -> bytes:
    """Render a list of (event_name, payload) into raw SSE bytes."""
    out = []
    for name, payload in events:
        out.append(f"event: {name}\n")
        out.append(f"data: {json.dumps(payload)}\n")
        out.append("\n")
    return "".join(out).encode("utf-8")


def _happy_sse_bytes() -> bytes:
    """Anthropic-format streaming response for: text + tool_use blocks."""
    return _sse(
        [
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_test_123",
                        "model": "claude-sonnet-4-5",
                        "role": "assistant",
                        "type": "message",
                        "usage": {
                            "input_tokens": 100,
                            "output_tokens": 1,
                            "cache_creation_input_tokens": 10,
                            "cache_read_input_tokens": 50,
                        },
                    },
                },
            ),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Hello, "},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "world!"},
                },
            ),
            (
                "content_block_stop",
                {"type": "content_block_stop", "index": 0},
            ),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu_42",
                        "name": "lookup_thing",
                        "input": {},
                    },
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "input_json_delta", "partial_json": '{"q":'},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "input_json_delta", "partial_json": '"hi"}'},
                },
            ),
            (
                "content_block_stop",
                {"type": "content_block_stop", "index": 1},
            ),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                    "usage": {"output_tokens": 25},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]
    )


def _client_with_handler(handler) -> MrCallProxyClient:
    """Build a MrCallProxyClient whose underlying httpx.Client uses a
    MockTransport pointing at `handler`.

    We monkey-patch httpx.Client at construction time inside
    `_do_create` by injecting a custom factory; the simplest way is to
    patch the module-level `httpx.Client` attribute via a context. To
    keep the test self-contained we just override
    `MrCallProxyClient._do_create` to build the client with the mock
    transport — done by subclassing.
    """

    class _TestClient(MrCallProxyClient):
        def _do_create(self, kwargs):  # type: ignore[override]
            # Same body as the real impl, but with MockTransport.
            from zylch.llm.proxy_client import _accumulate_events, _iter_sse_events

            body = self._build_body(kwargs)
            headers = self._build_headers()
            url = f"{self.proxy_base_url}/api/desktop/llm/proxy"
            transport = httpx.MockTransport(handler)
            with httpx.Client(transport=transport, timeout=self._timeout) as client:
                with client.stream("POST", url, headers=headers, json=body) as response:
                    if response.status_code >= 400:
                        response.read()
                        self._raise_for_status(response)
                    events = _iter_sse_events(response.iter_bytes())
                    msg = _accumulate_events(events)
            if not msg.model:
                msg.model = body.get("model", "?")
            return msg

    return _TestClient(
        proxy_base_url="https://zylch-test.mrcall.ai",
        firebase_session=_FakeSession(),
    )


# ─── 1. Happy streaming path ──────────────────────────────────────────


def test_happy_streaming_path_reconstructs_message():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_happy_sse_bytes(),
        )

    client = _client_with_handler(handler)
    msg = client.messages.create(
        model="claude-sonnet-4-5",
        messages=[{"role": "user", "content": "say hi"}],
        max_tokens=1024,
    )

    # Two content blocks in original order.
    assert len(msg.content) == 2
    assert msg.content[0].type == "text"
    assert msg.content[0].text == "Hello, world!"
    assert msg.content[1].type == "tool_use"
    assert msg.content[1].id == "toolu_42"
    assert msg.content[1].name == "lookup_thing"
    assert msg.content[1].input == {"q": "hi"}

    # Stop reason from message_delta.
    assert msg.stop_reason == "tool_use"
    # Model populated from message_start.
    assert msg.model == "claude-sonnet-4-5"
    # Usage: input from message_start (100), output overwritten by
    # message_delta (25), cache fields from message_start.
    assert msg.usage.input_tokens == 100
    assert msg.usage.output_tokens == 25
    assert msg.usage.cache_creation_input_tokens == 10
    assert msg.usage.cache_read_input_tokens == 50


# ─── 2. 402 insufficient credits ──────────────────────────────────────


def test_402_raises_insufficient_credits_with_topup_url():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            402,
            json={
                "error": "insufficient_credits",
                "available": 0,
                "topup_url": "https://dashboard.mrcall.ai/billing/topup",
            },
        )

    client = _client_with_handler(handler)
    with pytest.raises(MrCallInsufficientCredits) as excinfo:
        client.messages.create(
            model="claude-sonnet-4-5",
            messages=[{"role": "user", "content": "x"}],
            max_tokens=1024,
        )
    err = excinfo.value
    assert err.available == 0
    assert err.topup_url == "https://dashboard.mrcall.ai/billing/topup"
    assert err.status == 402


# ─── 3. 401 unauthorized ──────────────────────────────────────────────


def test_401_raises_auth_error_so_caller_can_reauth():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": "invalid_token", "detail": "JWT expired"},
        )

    client = _client_with_handler(handler)
    with pytest.raises(MrCallAuthError) as excinfo:
        client.messages.create(
            model="claude-sonnet-4-5",
            messages=[{"role": "user", "content": "x"}],
            max_tokens=1024,
        )
    assert excinfo.value.status == 401


# ─── 4. Auth header shape ─────────────────────────────────────────────


def test_auth_header_is_set_with_no_bearer_prefix_and_token_from_session():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_happy_sse_bytes(),
        )

    client = _client_with_handler(handler)
    client.messages.create(
        model="claude-sonnet-4-5",
        messages=[{"role": "user", "content": "x"}],
        max_tokens=1024,
    )
    req = captured["request"]
    auth_value = req.headers.get("auth")
    assert auth_value == "fake-jwt-token-for-tests"
    # No Bearer prefix — matches StarChat / mrcall-agent convention.
    assert not auth_value.lower().startswith("bearer ")
    # Authorization header MUST NOT be set (we use the lowercase `auth`
    # custom header instead).
    assert req.headers.get("authorization") is None


# ─── 5. Body forwarding ───────────────────────────────────────────────


def test_body_forwards_model_messages_max_tokens_and_forces_stream_true():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_happy_sse_bytes(),
        )

    client = _client_with_handler(handler)
    client.messages.create(
        model="claude-sonnet-4-5",
        messages=[{"role": "user", "content": "x"}],
        max_tokens=2048,
        # explicit stream=False should still arrive as True (proxy is SSE-only)
        stream=False,
    )

    body = captured["body"]
    assert body["model"] == "claude-sonnet-4-5"
    assert body["messages"] == [{"role": "user", "content": "x"}]
    assert body["max_tokens"] == 2048
    assert body["stream"] is True


def test_body_forwards_optional_kwargs_when_present():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_happy_sse_bytes(),
        )

    client = _client_with_handler(handler)
    tools = [
        {
            "name": "calc",
            "description": "do math",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]
    system_prompt = "You are helpful."
    client.messages.create(
        model="claude-sonnet-4-5",
        messages=[{"role": "user", "content": "x"}],
        max_tokens=512,
        temperature=0.3,
        tools=tools,
        system=system_prompt,
        top_p=0.9,
        stop_sequences=["END"],
    )

    body = captured["body"]
    assert body["temperature"] == 0.3
    assert body["tools"] == tools
    assert body["system"] == system_prompt
    assert body["top_p"] == 0.9
    assert body["stop_sequences"] == ["END"]


def test_unknown_kwargs_are_dropped_and_do_not_leak():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_happy_sse_bytes(),
        )

    client = _client_with_handler(handler)
    client.messages.create(
        model="claude-sonnet-4-5",
        messages=[{"role": "user", "content": "x"}],
        max_tokens=512,
        # Bogus kwargs we DO NOT want forwarded to the proxy.
        cache_control={"type": "ephemeral"},
        future_secret_kwarg="xyz",
    )
    body = captured["body"]
    assert "cache_control" not in body
    assert "future_secret_kwarg" not in body


# ─── 6. 5xx → MrCallProxyError ────────────────────────────────────────


def test_5xx_raises_generic_proxy_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "anthropic_upstream", "detail": "boom"})

    client = _client_with_handler(handler)
    with pytest.raises(MrCallProxyError) as excinfo:
        client.messages.create(
            model="claude-sonnet-4-5",
            messages=[{"role": "user", "content": "x"}],
            max_tokens=512,
        )
    assert excinfo.value.status == 503
    # Specific subclasses must NOT match here.
    assert not isinstance(excinfo.value, MrCallAuthError)
    assert not isinstance(excinfo.value, MrCallInsufficientCredits)
