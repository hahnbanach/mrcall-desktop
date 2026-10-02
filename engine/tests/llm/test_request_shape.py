"""The one request shape (milestone 10, brief D3, AC 2): decided by metadata, never by name.

Every request leaves the client without sampling, without a forced tool
choice, with reasoning set from the model's published metadata — on at the
lowest published effort (never ``disabled``), off where it is optional and on
by default, the provider's default where it is mandatory without efforts —
and with ``REASONING_HEADROOM`` more output tokens whenever reasoning is on.

The metadata below is the 2026-10-02 catalogue capture's, mapped as
``roles/catalogue.metadata`` publishes it. The sweep at the end sends every
entry of that capture (S2's committed fixture) and an id no catalogue has
seen, ``claude-opus-6``, through the shape.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path

import pytest

from zylch.llm import request_shape
from zylch.llm.request_shape import EFFORTS, REASONING_HEADROOM, lowest_effort, shape, shaped

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "llm" / "resolver-2026-10-02"
TOOL = {"name": "decide", "description": "d", "input_schema": {"type": "object"}}
CLOSED = {
    "name": "record",
    "input_schema": {
        "type": "object",
        "properties": {
            "value": {"type": "string"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"n": {"type": "integer"}},
                    "required": ["n"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["value", "items"],
        "additionalProperties": False,
    },
}


def meta(reasoning=None, parameters=("tools", "tool_choice")):
    """A catalogue entry's ``reasoning`` and ``supported_parameters`` as metadata."""
    reasoning = reasoning or {}
    return {
        "reasoning": {
            "mandatory": bool(reasoning.get("mandatory")),
            "efforts": list(reasoning.get("supported_efforts") or []),
            "default_enabled": reasoning.get("default_enabled"),
        },
        "parameters": list(parameters),
        "forced_tool": True,
        "structured_outputs": "structured_outputs" in parameters,
        "context_length": 1_000_000,
        "expiration_date": None,
    }


# The 2026-10-02 capture's `reasoning` field, entry by entry.
SONNET_5_5 = meta(
    {"mandatory": True, "supported_efforts": ["max", "xhigh", "high", "medium", "low"]},
    ("reasoning", "structured_outputs", "temperature", "tool_choice", "tools"),
)
QWEN_3_8_MAX = meta(
    {
        "mandatory": True,
        "default_enabled": True,
        "supported_efforts": ["xhigh", "high", "medium", "low", "minimal"],
    }
)
GLM_5_3_FLASH = meta(
    {"mandatory": True, "default_enabled": True, "supported_efforts": ["max", "high", "low"]}
)
OPUS_5 = meta(
    {
        "mandatory": False,
        "default_enabled": True,
        "supported_efforts": ["max", "xhigh", "high", "medium", "low"],
    }
)
HAIKU_4_5 = meta({"mandatory": False})
KIMI_K2_7_CODE = meta({"mandatory": True, "default_enabled": True})
LING_3_FLASH = meta({"mandatory": False, "default_enabled": True})
LFM_2_5 = meta({"mandatory": True})
NONE_EFFORT = meta({"mandatory": False, "supported_efforts": ["high", "none"]})


def request(model="any/model", **extra):
    base = {
        "model": model,
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 400,
        "temperature": 0,
        "top_p": 0.9,
        "top_k": 5,
        "extra_body": {"temperature": 0.2, "keep": 1},
        "tools": [TOOL],
        "tool_choice": {"type": "tool", "name": "decide"},
        "service_tier": "standard_only",
    }
    base.update(extra)
    return base


def assert_one_shape(out):
    assert not {"temperature", "top_p", "top_k"} & set(out), out
    assert not {"temperature", "top_p", "top_k"} & set(out.get("extra_body") or {}), out
    assert (out.get("tool_choice") or {}).get("type") not in ("any", "tool"), out


@pytest.mark.parametrize(
    "metadata,effort",
    [
        (SONNET_5_5, "low"),
        (QWEN_3_8_MAX, "minimal"),
        (GLM_5_3_FLASH, "low"),
        (OPUS_5, "low"),
        (NONE_EFFORT, "high"),
    ],
)
def test_published_efforts_turn_reasoning_on_at_the_lowest(metadata, effort):
    out = shape(request(), metadata)
    assert_one_shape(out)
    assert out["thinking"] == {"type": "adaptive"}
    assert out["output_config"] == {"effort": effort}
    assert out["max_tokens"] == 400 + REASONING_HEADROOM


def test_a_mandatory_model_without_efforts_keeps_the_provider_default():
    for metadata in (KIMI_K2_7_CODE, LFM_2_5):
        out = shape(request(), metadata)
        assert_one_shape(out)
        assert "thinking" not in out and "output_config" not in out
        assert out["max_tokens"] == 400 + REASONING_HEADROOM


def test_an_optional_model_on_by_default_is_turned_off():
    out = shape(request(), LING_3_FLASH)
    assert out["thinking"] == {"type": "disabled"}
    assert "output_config" not in out and out["max_tokens"] == 400


def test_an_optional_model_off_by_default_gets_nothing():
    out = shape(request(model="claude-haiku-4-5"), HAIKU_4_5)
    assert_one_shape(out)
    assert "thinking" not in out and "output_config" not in out
    assert out["max_tokens"] == 400


def test_an_unseen_id_gets_no_sampling_no_forced_choice_and_no_reasoning():
    out = shape(request(model="claude-opus-6"), None)
    assert_one_shape(out)
    assert out["tool_choice"] == {"type": "auto"}
    assert out["extra_body"] == {"keep": 1}
    assert "thinking" not in out and "output_config" not in out
    assert out["max_tokens"] == 400


def test_the_shape_owns_reasoning_a_caller_set():
    sent = request(thinking={"type": "disabled"}, output_config={"effort": "max"})
    assert shape(sent, SONNET_5_5)["thinking"] == {"type": "adaptive"}
    assert shape(sent, SONNET_5_5)["output_config"] == {"effort": "low"}
    unknown = shape(sent, None)
    assert "thinking" not in unknown and "output_config" not in unknown


def test_a_forced_choice_from_any_caller_is_sent_as_auto_and_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="zylch.llm.request_shape"):
        for forced in ({"type": "any"}, {"type": "tool", "name": "decide"}):
            assert shape(request(tool_choice=forced), HAIKU_4_5)["tool_choice"] == {"type": "auto"}
    assert caplog.text.count("sent as auto") == 2
    kept = {"type": "none"}
    assert shape(request(tool_choice=kept), HAIKU_4_5)["tool_choice"] == kept


def test_the_callers_request_is_never_mutated():
    sent = request(tools=[CLOSED])
    before = copy.deepcopy(sent)
    shape(sent, SONNET_5_5)
    assert sent == before


def test_strict_only_on_a_closed_schema_of_a_structured_outputs_model():
    out = shape(request(tools=[CLOSED, TOOL]), SONNET_5_5)
    assert out["tools"][0]["strict"] is True
    assert "strict" not in out["tools"][1]
    assert "strict" not in shape(request(tools=[CLOSED]), QWEN_3_8_MAX)["tools"][0]
    open_nested = copy.deepcopy(CLOSED)
    open_nested["input_schema"]["properties"]["items"]["items"]["required"] = []
    assert "strict" not in shape(request(tools=[open_nested]), SONNET_5_5)["tools"][0]
    claimed = {**TOOL, "strict": True}
    assert "strict" not in shape(request(tools=[claimed]), SONNET_5_5)["tools"][0]


def test_an_adapter_model_comes_back_untouched():
    from zylch.llm.k3_reasoning import MODEL

    sent = request(model=MODEL)
    assert shape(sent, GLM_5_3_FLASH) is sent
    assert sent["tool_choice"] == {"type": "tool", "name": "decide"}


def test_efforts_in_any_order_resolve_to_the_lowest_of_the_vocabulary():
    assert lowest_effort(["max", "xhigh", "high", "low"]) == "low"
    assert lowest_effort(["xhigh", "high", "medium", "low", "minimal"]) == "minimal"
    assert lowest_effort(["none"]) is None and lowest_effort(None) is None
    assert EFFORTS == ("minimal", "low", "medium", "high", "xhigh", "max")


def test_shaped_reads_the_catalogue_through_the_seam(monkeypatch):
    asked = []

    def metadata(model_id):
        asked.append(model_id)
        return QWEN_3_8_MAX

    monkeypatch.setattr(request_shape, "_metadata", metadata)
    out = shaped(request(model="qwen/qwen3.8-max-0902"))
    assert asked == ["qwen/qwen3.8-max-0902"]
    assert out["output_config"] == {"effort": "minimal"}


# ─── The 2026-10-02 capture, every entry, and an unseen id ────────────


def _capture_metadata():
    """Metadata for every entry of S2's committed capture, derived here from
    ``reasoning`` and ``supported_parameters`` (endpoints intersected when read)."""
    models = json.loads((FIXTURE / "models.json").read_text())["data"]
    endpoints = {}
    if (FIXTURE / "endpoints.json").exists():
        endpoints = json.loads((FIXTURE / "endpoints.json").read_text())["data"]
    out = {}
    for entry in models:
        parameters = set(entry.get("supported_parameters") or ())
        listed = (endpoints.get(entry["id"]) or {}).get("endpoints") or []
        for endpoint in listed:
            parameters &= set(endpoint.get("supported_parameters") or ())
        out[entry["id"]] = meta(entry.get("reasoning"), tuple(sorted(parameters)))
    return out


def test_every_capture_entry_and_an_unseen_id_get_the_one_shape():
    if not (FIXTURE / "models.json").exists():
        pytest.skip(f"S2's 2026-10-02 capture is not committed yet ({FIXTURE})")
    catalogue = _capture_metadata()
    assert len(catalogue) >= 400, "the capture lost its entries"
    catalogue["claude-opus-6"] = None
    seen = {"effort": 0, "mandatory_default": 0, "off": 0, "nothing": 0}
    for model, metadata in sorted(catalogue.items(), key=lambda item: item[0]):
        sent = request(model=model, tools=[CLOSED])
        out = shape(sent, metadata)
        if request_shape.is_adapter(model):
            assert out is sent, "an adapter model was shaped"
            continue
        assert_one_shape(out)
        published = (metadata or {}).get("reasoning") or {}
        effort = lowest_effort(published.get("efforts"))
        if published.get("mandatory"):
            assert out.get("thinking") != {"type": "disabled"}, model
        if metadata is not None and effort:
            assert out["thinking"] == {"type": "adaptive"}, model
            assert out["output_config"] == {"effort": effort}, model
            assert out["max_tokens"] == 400 + REASONING_HEADROOM, model
            seen["effort"] += 1
        elif metadata is not None and published.get("mandatory"):
            assert "thinking" not in out and out["max_tokens"] == 400 + REASONING_HEADROOM
            seen["mandatory_default"] += 1
        elif metadata is not None and published.get("default_enabled") is True:
            assert out["thinking"] == {"type": "disabled"} and out["max_tokens"] == 400, model
            seen["off"] += 1
        else:
            assert "thinking" not in out and out["max_tokens"] == 400, model
            seen["nothing"] += 1
        structured = bool(metadata and metadata["structured_outputs"])
        assert out["tools"][0].get("strict") is (True if structured else None), model
    assert all(seen.values()), seen


# ─── The seam is strict (IR1 integration) ─────────────────────────────


def test_metadata_seam_reads_the_catalogue_and_fails_loudly(monkeypatch):
    """The seam answers from ``roles/catalogue.py``; a catalogue that cannot be
    imported or read raises instead of reading every model as unknown, which
    would silently send requests without their reasoning controls."""
    import sys

    from zylch.llm.roles import catalogue

    meta = request_shape._metadata("anthropic/claude-sonnet-5.5")
    assert meta is not None and meta["reasoning"]["mandatory"] is True
    assert request_shape._metadata(None) is None

    def broken(model_id):
        raise RuntimeError("snapshot unreadable")

    monkeypatch.setattr(catalogue, "metadata", broken)
    with pytest.raises(RuntimeError):
        request_shape._metadata("anthropic/claude-sonnet-5.5")
    monkeypatch.setitem(sys.modules, "zylch.llm.roles.catalogue", None)
    with pytest.raises(ImportError):
        request_shape._metadata("anthropic/claude-sonnet-5.5")
