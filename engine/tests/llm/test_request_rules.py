"""Request shapes the picked models refuse never leave the client (review 2, B1).

Moving the defaults off Haiku sends the shapes of three call sites —
`utils/reply_need.py` (temperature 0 and a forced tool), the intent
classifier (temperature 0), `services/correction_learning.py` (a forced
tool) and the narrations (max_tokens 40 without thinking) — to models that
answer them with a 400. Each shape runs here through the real
`LLMClient.create_message_sync` on the direct and the OpenRouter transport
for every model the resolved table or the allowlist names, with the
dispatch captured. The forbidden fields below are written from Anthropic's
model reference, independently of `requirements.json`'s `request_rules`:

- any sampling field: Opus 4.7 and later, Sonnet 5, Fable 5 and 5.1;
- a non-default sampling value: Sonnet 5.5;
- a forced tool_choice (`any` / `tool`): Fable 5.1, Opus 5.5, Sonnet 5.5;
- thinking on by default when omitted: Sonnet 5 / 5.5, Opus 5 / 5.5; Sonnet
  5.5 refuses `disabled`, Opus 5.5 cannot turn thinking off.

Haiku 4.5 and the 4.6 / 4.5 line keep temperature 0 and the forced tool.
The reservation prices the request the caller sent, before the rules.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from zylch.llm import budget
from zylch.llm.budget_pricing import BudgetError, request_bound
from zylch.llm.client import LLMClient
from zylch.llm.openrouter_client import OpenRouterClient

ROLES = Path(__file__).resolve().parents[2] / "zylch" / "llm" / "roles"
ANY_SAMPLING = {"opus-4-7", "opus-4-8", "opus-5", "opus-5-5", "sonnet-5", "fable-5-1"}
NON_DEFAULT_SAMPLING = {"sonnet-5-5"}
FORCED_TOOL = {"fable-5-1", "opus-5-5", "sonnet-5-5"}
THINKS_BY_DEFAULT = {"sonnet-5", "sonnet-5-5", "opus-5", "opus-5-5"}
REFUSES_DISABLED = {"sonnet-5-5", "opus-5-5"}
KEEPS_SHAPES = {"haiku-4-5", "sonnet-4-6", "sonnet-4-5", "opus-4-6", "opus-4-5"}
FAMILIES = ANY_SAMPLING | NON_DEFAULT_SAMPLING | FORCED_TOOL | KEEPS_SHAPES
TOOL = {"name": "decide", "description": "d", "input_schema": {"type": "object"}}
FORCE = {"type": "tool", "name": "decide"}
SHAPES = {
    "reply_need": dict(temperature=0, tools=[TOOL], tool_choice=FORCE, max_tokens=2000),
    "intent": dict(temperature=0, max_tokens=500),
    "correction_learning": dict(tools=[TOOL], tool_choice=FORCE, max_tokens=300),
    "narration": dict(max_tokens=40),
}


def family(model: str) -> str | None:
    name = model.removeprefix("anthropic/").removeprefix("claude-").replace(".", "-")
    found = [f for f in FAMILIES if name == f or name.startswith(f + "-")]
    return max(found, key=len) if found else None


def named(transport: str) -> list[str]:
    resolved = json.loads((ROLES / "resolved.json").read_text())
    allowlist = json.loads((ROLES / "requirements.json").read_text())["allowlist"]
    key = "direct_id" if transport == "direct" else "catalogue_id"
    models = {
        row[key]
        for preset in resolved["presets"].values()
        for record in preset["roles"].values()
        for row in (record, record["anthropic_fallback"])
        if row.get(key)
    }
    return sorted(models | {m for m, row in allowlist.items() if row["transport"] == transport})


class Sent(Exception):
    """Raised by the fake provider once it has captured the outgoing request."""


@pytest.fixture
def boundary(monkeypatch):
    """Run a shape through create_message_sync; return (reserved, sent)."""
    import zylch.services.preparation as preparation

    monkeypatch.setattr(preparation, "check_dispatch", lambda: None)
    monkeypatch.setattr(preparation, "record_dispatch", lambda: None)
    seen = {}

    def reserve(request_kwargs, transport, *, quote=None):
        seen["bound"] = request_bound(request_kwargs, transport)  # a price refusal raises here
        seen["reserved"] = copy.deepcopy(request_kwargs)
        return None

    monkeypatch.setattr(budget, "reserve", reserve)

    def run(transport, model, shape):
        for key in ("sent", "reserved", "bound"):
            seen.pop(key, None)
        if transport == "direct":
            client = LLMClient("direct", api_key="synthetic", model=model)

            def create(**kwargs):
                seen["sent"] = kwargs
                raise Sent

            client._client = SimpleNamespace(messages=SimpleNamespace(create=create))
        else:
            client = LLMClient("openrouter", api_key="synthetic", model=model)

            def upstream(request):
                seen["sent"] = json.loads(request.content)
                return httpx.Response(500)

            http = httpx.Client(transport=httpx.MockTransport(upstream))
            client._client = OpenRouterClient("synthetic", http_client=http)
        messages = [{"role": "user", "content": "hello"}]
        with pytest.raises((Sent, BudgetError)):
            client.create_message_sync(messages=messages, **copy.deepcopy(shape))
        return seen.get("reserved"), seen.get("sent"), seen.get("bound")

    return run


def sampling(sent: dict) -> dict:
    out = {k: sent[k] for k in ("temperature", "top_p", "top_k") if k in sent}
    out.update(
        {
            k: v
            for k, v in (sent.get("extra_body") or {}).items()
            if k in out or k in ("temperature", "top_p", "top_k")
        }
    )
    return out


CASES = [(t, m, s) for t in ("direct", "openrouter") for m in named(t) for s in SHAPES]


@pytest.mark.parametrize("transport,model,shape", CASES)
def test_no_refused_field_leaves_the_client(boundary, transport, model, shape):
    _, sent, _ = boundary(transport, model, SHAPES[shape])
    fam = family(model)
    refused_by_price = (
        sent is None and model == "anthropic/claude-sonnet-5" and "temperature" in SHAPES[shape]
    )
    if "claude" in model and not refused_by_price:
        assert sent is not None, "the request never reached the provider"
    if sent is None:
        return
    if fam in ANY_SAMPLING:
        assert not sampling(sent), sent
    if fam in NON_DEFAULT_SAMPLING:
        assert all(v == 1 for v in sampling(sent).values()), sent
    if fam in FORCED_TOOL:
        assert (sent.get("tool_choice") or {}).get("type") not in ("any", "tool"), sent
    if fam in REFUSES_DISABLED:
        assert sent.get("thinking") != {"type": "disabled"}, sent
    # Default thinking may not starve a short answer nor meet a tool the model must call.
    forced = (sent.get("tool_choice") or {}).get("type") in ("any", "tool")
    small = SHAPES[shape]["max_tokens"] <= 1024 or forced
    if fam in THINKS_BY_DEFAULT - {"opus-5-5"} and small:
        assert (sent.get("thinking") or {}).get("type") in ("disabled", "between_tools"), sent
    if fam in KEEPS_SHAPES:
        if "temperature" in SHAPES[shape]:
            assert sampling(sent) == {"temperature": 0}, sent
        if "tool_choice" in SHAPES[shape]:
            assert sent["tool_choice"] == FORCE, sent


@pytest.mark.parametrize("transport,model,shape", CASES)
def test_the_reservation_prices_the_request_as_sent_by_the_caller(
    boundary, transport, model, shape
):
    reserved, _, bound = boundary(transport, model, SHAPES[shape])
    if reserved is None:  # refused by the price check before any reservation
        return
    caller = {**reserved, "temperature": SHAPES[shape].get("temperature", 1.0)}
    if "tool_choice" in SHAPES[shape]:
        caller["tool_choice"] = SHAPES[shape]["tool_choice"]
    if model != "moonshotai/kimi-k3":  # K3's reasoning contract is applied before pricing
        caller.pop("thinking", None)
        assert reserved == caller
    assert bound == request_bound(caller, transport)


def test_haiku_and_the_four_six_line_keep_every_shape_on_direct(boundary):
    for model in ("claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-6"):
        _, sent, _ = boundary("direct", model, SHAPES["reply_need"])
        assert sent["extra_body"] == {"temperature": 0}
        assert sent["tool_choice"] == FORCE and "thinking" not in sent


def test_the_longest_prefix_wins():
    from zylch.llm.roles.request_rules import apply

    request = {"model": "", "max_tokens": 40, "temperature": 1, "tool_choice": FORCE}
    five = apply({**request, "model": "claude-sonnet-5"})
    five_five = apply({**request, "model": "claude-sonnet-5-5"})
    assert five["tool_choice"] == FORCE and five["thinking"] == {"type": "disabled"}
    assert "temperature" not in five
    assert five_five["tool_choice"] == {"type": "auto"}
    assert five_five["thinking"] == {"type": "between_tools"}
    assert five_five["temperature"] == 1


SERVED = json.loads((ROLES / "requirements.json").read_text())["mrcall_served"]


@pytest.mark.parametrize("model", [m for m in SERVED if not m.startswith("moonshotai/")])
@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_the_credits_quote_carries_no_refused_field_and_adds_no_thinking(model, shape):
    """The credits server quotes and runs the exact body: the rules apply before
    the quote, sampling and a forced tool go, and no `thinking` field is added
    (adding one is the server's contract to change, not the client's)."""
    from zylch.llm.sdk_request import sdk_request

    sent = {"model": model, "messages": [{"role": "user", "content": "x"}], **SHAPES[shape]}
    body = sdk_request(copy.deepcopy(sent), "proxy")
    fam = family(model)
    if fam in ANY_SAMPLING:
        assert not {"temperature", "top_p", "top_k"} & set(body)
    if fam in NON_DEFAULT_SAMPLING:
        assert body.get("temperature", 1.0) == 1.0
    if fam in FORCED_TOOL and "tool_choice" in sent:
        assert body["tool_choice"] == {"type": "auto"}
    if fam in KEEPS_SHAPES:
        assert body == sent
    assert "thinking" not in body


def test_the_proxy_quote_is_taken_on_the_rewritten_body():
    source = (ROLES.parent / "client.py").read_text()
    assert 'self._client.quote(request_kwargs := sdk_request(request_kwargs, "proxy"))' in source
