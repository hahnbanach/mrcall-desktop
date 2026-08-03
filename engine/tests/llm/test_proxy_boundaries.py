"""Boundary regressions for the MrCall SSE proxy transport."""

from __future__ import annotations

import gzip

import httpx
import pytest

from tests.llm.proxy_fixtures import _FakeSession, _happy_sse_bytes
from zylch.llm.proxy_client import (
    MrCallProxyClient,
    MrCallProxyError,
    _accumulate_events,
    _iter_sse_events,
)


def test_sse_parser_preserves_utf8_split_across_transport_chunks():
    raw = (
        "event: content_block_start\n"
        'data: {"index":0,"content_block":{"type":"text","text":""}}\n\n'
        "event: content_block_delta\n"
        'data: {"index":0,"delta":{"type":"text_delta","text":"identità 🔐"}}\n\n'
        "event: content_block_stop\n"
        'data: {"index":0}\n\n'
    ).encode()
    split = raw.index("🔐".encode()) + 1

    message = _accumulate_events(_iter_sse_events(iter([raw[:split], raw[split:]])))

    assert message.content[0].text == "identità 🔐"


def _patch_client(monkeypatch, handler) -> None:
    real_client = httpx.Client

    def factory(*_args, **kwargs):
        return real_client(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout"))

    monkeypatch.setattr(httpx, "Client", factory)


def _invoke() -> object:
    client = MrCallProxyClient(
        proxy_base_url="https://zylch-test.mrcall.ai", firebase_session=_FakeSession()
    )
    return client.messages.create(
        model="claude-sonnet-4-5",
        messages=[{"role": "user", "content": "x"}],
        max_tokens=128,
    )


def test_gzip_without_content_encoding_is_inflated(monkeypatch):
    def handler(_request):
        return httpx.Response(200, content=gzip.compress(_happy_sse_bytes()))

    _patch_client(monkeypatch, handler)

    assert _invoke().content[0].text == "Hello, world!"


def test_transport_disconnect_is_mapped_to_typed_error(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("synthetic disconnect", request=request)

    _patch_client(monkeypatch, handler)

    with pytest.raises(MrCallProxyError) as excinfo:
        _invoke()

    assert excinfo.value.status == 0
    assert "transport_error" in excinfo.value.detail
