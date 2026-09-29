"""`settings.get` on a hosted engine reports the keys it does not honour
as an additive `ignored` sibling; `values` keeps its shape. `settings.update`
still refuses unknown keys, so the serve flag cannot be written to `.env`."""

from __future__ import annotations

import asyncio

import pytest

from zylch import runtime
from zylch.rpc import methods
from zylch.services import settings_io


def _notify(*_a, **_k):
    return None


@pytest.fixture(autouse=True)
def _stub_env(monkeypatch):
    monkeypatch.setattr(settings_io, "read_env", lambda: {"DOCUMENT_PATHS": "/x"})


def test_local_get_has_no_ignored_field():
    out = asyncio.run(methods.settings_get({}, _notify))
    assert "ignored" not in out
    assert out["values"]["DOCUMENT_PATHS"] == "/x"


def test_hosted_get_reports_ignored_keys(monkeypatch):
    monkeypatch.setattr(runtime, "_serving", True)
    out = asyncio.run(methods.settings_get({}, _notify))
    assert set(out["ignored"]) == {"DOCUMENT_PATHS", "DOWNLOADS_DIR"}
    assert all(isinstance(v, str) for v in out["values"].values())
    assert out["values"]["DOCUMENT_PATHS"] == "/x"


def test_update_refuses_the_serve_flag():
    with pytest.raises(ValueError, match="unknown setting keys"):
        asyncio.run(methods.settings_update({"updates": {"ZYLCH_SERVE": "0"}}, _notify))
