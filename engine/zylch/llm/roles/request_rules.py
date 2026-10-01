"""Request shapes a model refuses, applied at the client boundary.

`requirements.json`'s `request_rules` maps a model-id prefix (direct id or
OpenRouter catalogue id; the longest prefix wins, so `…-5-5` can differ
from `…-5`) to what the model refuses, from Anthropic's model reference:
sampling fields (`drop`: any of them; `drop_non_default`: only a value
other than the API default), a forced `tool_choice` (`any` / `tool`,
downgraded to `auto`), and default thinking (`thinking_off`: the field that
turns it off, null when the model cannot). The transports call `apply`
after the budget reservation, on the dict they are about to send: a rule
only removes or relaxes a field, and thinking stays within `max_tokens`, so
the reserved bound still holds. A model with no rule is returned unchanged.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

SAMPLING_KEYS = ("temperature", "top_p", "top_k")
SAMPLING_DEFAULTS: Dict[str, Any] = {"temperature": 1}
FORCED = ("any", "tool")
DISABLED = {"type": "disabled"}
# A request this small is where default thinking could spend every token.
SHORT_OUTPUT = 1024


@lru_cache(maxsize=None)
def _rules() -> Dict[str, dict]:
    path = Path(__file__).resolve().parent / "requirements.json"
    return json.loads(path.read_text(encoding="utf-8")).get("request_rules", {})


def rule_for(model: Optional[str]) -> Optional[dict]:
    """The rule of the longest prefix of `model`, or None."""
    if not model:
        return None
    matches = [prefix for prefix in _rules() if model.startswith(prefix)]
    return _rules()[max(matches, key=len)] if matches else None


def _drop_sampling(holder: dict, how: str) -> None:
    for key in SAMPLING_KEYS:
        if key in holder and (how == "drop" or holder[key] != SAMPLING_DEFAULTS.get(key)):
            holder.pop(key)


def apply(
    request: Dict[str, Any], model: Optional[str] = None, *, thinking: bool = True
) -> Dict[str, Any]:
    """Return a copy of `request` without the fields `model`'s rule refuses.

    ``thinking=False`` leaves the ``thinking`` field as the caller sent it: the
    MrCall credits server quotes the exact body it will execute, and adding a
    field it may not accept is the server's contract to change, not ours.
    """
    model = model or request.get("model")
    rule = rule_for(model)
    if rule is None:
        return request
    out = copy.deepcopy(request)
    if rule.get("sampling") in ("drop", "drop_non_default"):
        _drop_sampling(out, rule["sampling"])
        if isinstance(out.get("extra_body"), dict):
            _drop_sampling(out["extra_body"], rule["sampling"])
            if not out["extra_body"]:
                out.pop("extra_body")
    forced = isinstance(out.get("tool_choice"), dict) and out["tool_choice"].get("type") in FORCED
    if forced and rule.get("forced_tool_choice") == "auto":
        out["tool_choice"] = {"type": "auto"}
        forced = False
    thinking_off = rule.get("thinking_off") if thinking else None
    if not thinking:
        return out
    if "thinking" not in out:
        # Default thinking could exhaust a short budget, and a model that
        # thinks may not be forced to call a tool.
        if thinking_off and (out.get("max_tokens", 0) <= SHORT_OUTPUT or forced):
            out["thinking"] = dict(thinking_off)
    elif out["thinking"] == DISABLED and thinking_off != DISABLED:
        # A transport that always disables thinking: send what this model takes.
        if thinking_off:
            out["thinking"] = dict(thinking_off)
        else:
            out.pop("thinking")
    return out
