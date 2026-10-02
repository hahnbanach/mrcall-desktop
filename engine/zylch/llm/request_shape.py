"""The one request shape (milestone 10, brief D3): decided by metadata, never by name.

Every request leaves ``LLMClient`` in one shape on every transport (direct,
OpenRouter, MrCall credits), set from the model's published metadata
(``roles/catalogue.metadata``: the snapshot of OpenRouter's catalogue):

- no sampling field (``temperature``, ``top_p``, ``top_k``), at the top level
  or in ``extra_body`` — Opus 4.7 and later refuse any of them;
- ``tool_choice`` never forced: ``any`` / ``tool`` from any caller is sent as
  ``auto`` and logged. The call sites name their tool in the instruction, and
  when a model answers without calling it their existing error path runs;
- reasoning from the metadata: where the model publishes efforts, adaptive
  reasoning at the lowest of them (never ``disabled``, which Opus 5.5 and
  Sonnet 5.5 refuse); where it publishes none, ``disabled`` if reasoning is
  optional and on by default, nothing otherwise; mandatory without efforts,
  nothing (the provider's default); no metadata at all, nothing;
- ``strict`` on a tool whose schema already closes every object and requires
  every property, when the model supports structured outputs;
- ``REASONING_HEADROOM`` tokens added to ``max_tokens`` whenever reasoning is
  on, so a short-output role still has room for its answer.

The shape owns ``thinking``, ``output_config.effort`` and ``strict``: what a
caller set there is replaced. Adapter models (K3, ``k3_reasoning.py``) are
returned untouched — their adapter decides the whole request. The client
shapes before admission, so the dict the budget reserves is the dict a
transport sends; the shape only removes fields, relaxes a forced choice and
adds reasoning that ``max_tokens`` bounds, so the reservation stays a bound.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

SAMPLING_KEYS = ("temperature", "top_p", "top_k")
FORCED = ("any", "tool")
AUTO = {"type": "auto"}
# The effort vocabulary of the catalogue's `supported_efforts`, lowest first.
# Lists arrive in any order and may carry values outside it (`none`), which
# never count as an effort.
EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")
REASONING_HEADROOM = 1024


def _metadata(model_id: Optional[str]) -> Optional[dict]:
    """The snapshot's request metadata for ``model_id``, or ``None``.

    The one seam to the catalogue reader (``roles/catalogue.py``): tests
    replace it. ``None`` means only that the snapshot does not list the
    model; a reader that cannot be imported or read raises, so a broken
    catalogue fails loudly instead of sending every request without its
    reasoning controls.
    """
    from .roles.catalogue import metadata

    return metadata(model_id) if model_id else None


def is_adapter(model: Optional[str]) -> bool:
    """True for a model whose protocol adapter decides its whole request."""
    from .k3_reasoning import MODEL as K3

    return model == K3


def lowest_effort(efforts: Optional[Iterable[str]]) -> Optional[str]:
    """The lowest effort of the vocabulary that ``efforts`` publishes, or ``None``."""
    published = set(efforts or ())
    return next((effort for effort in EFFORTS if effort in published), None)


def tool_instruction(name: str) -> str:
    """The sentence that replaces a forced ``tool_choice`` at a call site."""
    return f"Answer by calling the {name} tool exactly once; do not answer in plain text."


def shaped(request: Dict[str, Any]) -> Dict[str, Any]:
    """:func:`shape` with the metadata of the request's own model."""
    return shape(request, _metadata(request.get("model")))


def shape(request: Dict[str, Any], meta: Optional[dict]) -> Dict[str, Any]:
    """Return ``request`` in the one shape for a model described by ``meta``.

    Pure: the caller's dict, its tools and its ``extra_body`` are never
    mutated. An adapter model's request comes back as the same object.
    """
    if is_adapter(request.get("model")):
        return request
    out = dict(request)
    for key in SAMPLING_KEYS:
        out.pop(key, None)
    if isinstance(out.get("extra_body"), dict):
        extra = {k: v for k, v in out["extra_body"].items() if k not in SAMPLING_KEYS}
        if extra:
            out["extra_body"] = extra
        else:
            out.pop("extra_body")
    choice = out.get("tool_choice")
    if isinstance(choice, dict) and choice.get("type") in FORCED:
        logger.warning(f"[shape] model={out.get('model')} forced tool_choice={choice} sent as auto")
        out["tool_choice"] = dict(AUTO)
    out.pop("thinking", None)
    config = {k: v for k, v in (out.pop("output_config", None) or {}).items() if k != "effort"}
    reasoning = _reasoning(out, config, meta)
    if config:
        out["output_config"] = config
    if isinstance(out.get("tools"), list):
        structured = bool(meta and meta.get("structured_outputs"))
        out["tools"] = [_strict(tool, structured) for tool in out["tools"]]
    if reasoning and type(out.get("max_tokens")) is int:
        out["max_tokens"] += REASONING_HEADROOM
    logger.debug(
        f"[shape] model={out.get('model')} meta={'present' if meta else 'absent'} "
        f"thinking={out.get('thinking')} effort={config.get('effort')} reasoning={reasoning}"
    )
    return out


def _reasoning(out: Dict[str, Any], config: Dict[str, Any], meta: Optional[dict]) -> bool:
    """Set the reasoning fields from ``meta``; True when reasoning will be on."""
    if meta is None:
        return False
    published = meta.get("reasoning") or {}
    effort = lowest_effort(published.get("efforts"))
    if effort is not None:
        out["thinking"] = {"type": "adaptive"}
        config["effort"] = effort
        return True
    if published.get("mandatory"):
        return True
    if published.get("default_enabled") is True:
        out["thinking"] = {"type": "disabled"}
    return False


def _strict(tool: Any, structured: bool) -> Any:
    """``tool`` with ``strict`` set only where its schema is already strict-ready."""
    if not isinstance(tool, dict):
        return tool
    ready = structured and _closed(tool.get("input_schema"))
    if (ready and tool.get("strict") is True) or (not ready and "strict" not in tool):
        return tool
    out = {k: v for k, v in tool.items() if k != "strict"}
    if ready:
        out["strict"] = True
    return out


def _closed(schema: Any) -> bool:
    """True when every object in ``schema`` forbids extra properties and requires
    all it declares — the schemas strict mode accepts without a rewrite."""
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return False
    return _nested_closed(schema)


def _nested_closed(schema: Any) -> bool:
    if not isinstance(schema, dict):
        return True
    if schema.get("type") == "object" or "properties" in schema:
        properties = schema.get("properties") or {}
        if not isinstance(properties, dict) or schema.get("additionalProperties") is not False:
            return False
        if set(schema.get("required") or ()) != set(properties):
            return False
        return all(_nested_closed(value) for value in properties.values())
    if "items" in schema:
        return _nested_closed(schema["items"])
    for key in ("anyOf", "oneOf", "allOf"):
        if isinstance(schema.get(key), list):
            return all(_nested_closed(option) for option in schema[key])
    return True
