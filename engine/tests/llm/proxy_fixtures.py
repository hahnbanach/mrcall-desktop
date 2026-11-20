"""Shared SSE / session fixtures for the MrCall proxy-client tests.

`tests/llm/test_proxy_client.py` and `tests/llm/test_proxy_boundaries.py`
both need a fake Firebase session and a canned Anthropic SSE stream.
They live here so neither test module has to import the other's private
helpers — a test importing another test's underscore names breaks the
moment that file is reorganised.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Optional, Tuple


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


def v2_quote(request: dict, account: str, business: str, credit: int, credits: int) -> dict:
    """The quote a billing server speaking `mrcall-bounded-v2` answers for
    `request` (`zylch/llm/roles/contract/protocol-v2.md`): v1's fields, the
    snapshot version it priced with, and its own hash, as `validate_quote`
    checks them."""
    from zylch.llm.bounded_proxy import PROTOCOL, digest, wire_request

    body = {
        "protocol": PROTOCOL,
        "currency": "USD",
        "account_id": account,
        "model": request["model"],
        "payload_hash": digest(wire_request(request)),
        "business_id": business,
        "tariff_version": "v1",
        "credit_value_micro_usd": credit,
        "max_credits": credits,
        "max_debit_micro_usd": credit * credits,
        "snapshot_version": "0" * 64,
    }
    return {**body, "quote_hash": digest(body)}
