"""Guarded Anthropic-shaped client for direct, OpenRouter and MrCall billing.

Saved profile policy chooses a provider explicitly; legacy profiles retain
key-or-credits selection. Every paid dispatch uses the common durable budget.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union

logger = logging.getLogger(__name__)


# ─── Current-datetime injection ───────────────────────────────────────
# Every request that goes to the LLM MUST carry the real current moment.
# Without it the model guesses the date from its training cutoff and gets
# every relative deadline wrong ("today is May 20, pickup is tomorrow"
# when it is actually a different day). Injected at the single LLMClient
# chokepoint below so it covers task detection, memory, solve, chat,
# trainers, sweeps — everything — automatically.


def current_datetime_line() -> str:
    """Short, useful ``now`` line injected into every LLM system prompt.

    Local, timezone-aware, with the weekday — so any model reasoning
    about relative dates ("today", "tomorrow", a deadline) has the real
    moment instead of guessing from its training cutoff.

    Example: ``Datetime=2026-05-22T10:30+02:00 (Thursday) — current
    moment; use it for any relative date reasoning.``
    """
    now = datetime.now().astimezone()
    return (
        f"Datetime={now.isoformat(timespec='minutes')} ({now:%A}) — "
        "current moment; use it for any relative date reasoning."
    )


def _with_datetime(
    system: Optional[Union[str, List[Dict[str, Any]]]],
) -> Union[str, List[Dict[str, Any]]]:
    """Return ``system`` with the current datetime appended.

    Appended LAST so it never busts prompt caching: the cached prefix is
    the caller's block(s) carrying ``cache_control``; the changing
    datetime sits PAST that breakpoint and is sent fresh each call
    without invalidating the cache. A bare-string ``system`` is never
    prompt-cached (caching needs the blocks + ``cache_control`` form), so
    plain concatenation is safe there too. ``None`` becomes the line on
    its own — so a request with no system prompt still carries the date.
    """
    line = current_datetime_line()
    if system is None:
        return line
    if isinstance(system, str):
        return f"{system}\n\n{line}"
    return list(system) + [{"type": "text", "text": line}]


# ─── Anthropic-shape return objects (kept for backward compat) ────────


@dataclass
class ToolUseBlock:
    """Tool-use block in Anthropic format."""

    type: str = "tool_use"
    id: str = ""
    name: str = ""
    input: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TextBlock:
    """Text block in Anthropic format."""

    type: str = "text"
    text: str = ""


class LLMResponse:
    """Adapter exposing the Anthropic-shape fields callers care about.

    Both transports return Anthropic-shape Message objects (the proxy
    reconstructs them from SSE), so this adapter only needs the
    Anthropic branch.
    """

    def __init__(self, raw_response: Any):
        self._raw = raw_response
        self._content: List[Union[TextBlock, ToolUseBlock]] = []
        self._stop_reason: Optional[str] = None
        self._parse_response()

    def _parse_response(self) -> None:
        if not (hasattr(self._raw, "stop_reason") and hasattr(self._raw, "content")):
            return
        if not isinstance(self._raw.content, list):
            return
        for block in self._raw.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                self._content.append(TextBlock(text=getattr(block, "text", "")))
            elif btype == "tool_use":
                raw_input = getattr(block, "input", None)
                inp = raw_input if isinstance(raw_input, dict) else {}
                self._content.append(
                    ToolUseBlock(
                        id=getattr(block, "id", ""),
                        name=getattr(block, "name", ""),
                        input=inp,
                    )
                )
        self._stop_reason = self._raw.stop_reason

    @property
    def content(self) -> List[Union[TextBlock, ToolUseBlock]]:
        return self._content

    @property
    def stop_reason(self) -> Optional[str]:
        return self._stop_reason

    @property
    def model(self) -> str:
        return getattr(self._raw, "model", "")

    @property
    def usage(self) -> Dict[str, int]:
        u = getattr(self._raw, "usage", None)
        if not u:
            return {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            }
        read = u.get if isinstance(u, dict) else lambda key, default=0: getattr(u, key, default)
        return {
            "input_tokens": int(read("input_tokens", 0) or 0),
            "output_tokens": int(read("output_tokens", 0) or 0),
            "cache_creation_input_tokens": int(read("cache_creation_input_tokens", 0) or 0),
            "cache_read_input_tokens": int(read("cache_read_input_tokens", 0) or 0),
        }


# ─── Message coercion helpers ─────────────────────────────────────────


def _coerce_block(block: Any) -> Any:
    """Convert SDK block objects (TextBlock/ToolUseBlock) into plain
    dicts. Anthropic's request serializer raises on lingering SDK
    objects, and the proxy's body builder forwards the value verbatim,
    so we normalise here once.
    """
    if isinstance(block, dict):
        return block
    btype = getattr(block, "type", None)
    if btype == "text":
        return {"type": "text", "text": getattr(block, "text", "")}
    if btype == "tool_use":
        return {
            "type": "tool_use",
            "id": getattr(block, "id", ""),
            "name": getattr(block, "name", ""),
            "input": dict(getattr(block, "input", {}) or {}),
        }
    if hasattr(block, "model_dump"):
        try:
            return block.model_dump()
        except Exception:  # noqa: BLE001
            pass
    return block


def _coerce_messages(messages: List[Any]) -> List[Any]:
    out: List[Any] = []
    for m in messages:
        if isinstance(m, dict):
            content = m.get("content")
            if isinstance(content, list):
                out.append({**m, "content": [_coerce_block(b) for b in content]})
                continue
        out.append(m)
    return out


# ─── Client ───────────────────────────────────────────────────────────


Transport = Literal["direct", "proxy", "openrouter"]


class LLMClient:
    """Anthropic-shape LLM client, transport-agnostic.

    Construct via :func:`make_llm_client`. Calling the constructor
    directly is supported but rare — typically only tests do that.

    Example:
        client = make_llm_client()
        response = await client.create_message(
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=1000,
        )
        print(response.content[0].text)
    """

    def __init__(
        self,
        transport: Transport,
        *,
        api_key: Optional[str] = None,
        firebase_session: Optional[Any] = None,
        proxy_base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        from zylch.config import settings

        if transport == "direct":
            if not api_key:
                raise ValueError("api_key is required for transport='direct'")
            import anthropic

            # Each transport attempt owns a durable budget reservation. Hidden
            # retries can bill more than the admitted request after a timeout.
            self._client = anthropic.Anthropic(
                api_key=api_key,
                base_url="https://api.anthropic.com",
                max_retries=0,
                timeout=120.0,
            )
            # An inherited shell gateway/token must not change the admitted
            # billing transport or leak a second credential to the provider.
            self._client.auth_token = None
            self.model = model or settings.anthropic_model
        elif transport == "openrouter":
            if not api_key:
                raise ValueError("api_key is required for transport='openrouter'")
            from .openrouter_client import OpenRouterClient
            from .openrouter_pricing import MODEL

            self._client = OpenRouterClient(api_key=api_key)
            self.model = model or MODEL
        elif transport == "proxy":
            if firebase_session is None:
                raise ValueError(
                    "firebase_session is required for transport='proxy' " "(no signed-in user)"
                )
            from .bounded_proxy import BoundedProxyClient

            self._client = BoundedProxyClient(
                proxy_base_url=proxy_base_url or settings.mrcall_proxy_url,
                firebase_session=firebase_session,
            )
            self.model = model or settings.mrcall_credits_model
        else:
            raise ValueError(f"Unknown transport: {transport!r}")

        self.transport: Transport = transport
        logger.info(f"Initialized LLMClient transport={transport} model={self.model}")

    @property
    def is_metered(self) -> bool:
        """True when calls bill against the user's MrCall credit balance.

        Replaces the old ``PROVIDER_FEATURES[provider]['is_metered']``
        flag — equivalent to ``transport == 'proxy'``.
        """
        return self.transport == "proxy"

    async def create_message(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[Union[str, List[Dict[str, Any]]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Dict[str, Any]] = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Async wrapper around :meth:`create_message_sync`.

        The sync call runs in a thread-pool executor, which starts with a
        fresh contextvars context — so the caller's ``usage.call_site``
        tag would be lost unless we carry the context across explicitly.
        Copy it here and run the sync call inside it so spend recorded in
        ``create_message_sync`` is attributed to the right call site.
        """
        ctx = contextvars.copy_context()
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: ctx.run(
                lambda: self.create_message_sync(
                    messages=messages,
                    system=system,
                    tools=tools,
                    tool_choice=tool_choice,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    model=model,
                    **kwargs,
                )
            ),
        )

    def create_message_sync(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[Union[str, List[Dict[str, Any]]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Dict[str, Any]] = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a Messages-API request and return a unified
        :class:`LLMResponse`."""
        if getattr(self, "_saved_policy_fingerprint", None) is not None:
            from .model_policy import policy_fingerprint
            from .budget_pricing import BudgetError
            if policy_fingerprint() != self._saved_policy_fingerprint:
                raise BudgetError("AI settings changed. Start a new run or conversation to use the saved provider and models.")
        model_name = model or self.model
        coerced = _coerce_messages(messages)

        request_kwargs: Dict[str, Any] = {
            "model": model_name,
            "messages": coerced,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "service_tier": "standard_only",
        }
        # Always inject the current datetime (appended last → cache-safe).
        # Every LLM request carries the real moment; no exceptions.
        request_kwargs["system"] = _with_datetime(system)
        if tools:
            request_kwargs["tools"] = tools
        if tool_choice:
            request_kwargs["tool_choice"] = tool_choice
        for key, value in kwargs.items():
            request_kwargs[key] = value

        num_tools = len(tools) if tools else 0
        logger.debug(
            f"llm request: transport={self.transport} model={model_name} "
            f"messages={len(coerced)} tools={num_tools}"
        )
        from zylch.llm.budget import reserve, settle
        from zylch.services.preparation import check_dispatch, record_dispatch

        # Admission uses the final provider-visible payload, including kwargs.
        # A cancellation/timeout never releases a possibly dispatched request.
        check_dispatch()
        quote = self._client.quote(request_kwargs) if self.transport == "proxy" else None
        reservation = reserve(request_kwargs, self.transport, quote=quote)
        record_dispatch()
        receipt = None
        if self.transport == "proxy":
            raw, receipt = self._client.execute(request_kwargs, quote, reservation)
        else:
            raw = self._client.messages.create(**request_kwargs)
        if self.transport == "direct":
            from .budget_pricing import validate_response_model
            validate_response_model(request_kwargs["model"], getattr(raw, "model", None))
        response = LLMResponse(raw)
        # Preserve missing/invalid usage as unknown; the display adapter's zero
        # defaults must never release money reserved for an uncertain response.
        raw_usage = getattr(raw, "usage", None)
        if hasattr(raw_usage, "model_dump"):
            raw_usage = raw_usage.model_dump()
        elif raw_usage is not None and not isinstance(raw_usage, dict):
            raw_usage = vars(raw_usage)
        settle(reservation, raw_usage, receipt=receipt)

        return response


# ─── Factory ──────────────────────────────────────────────────────────


def make_llm_client(model: Optional[str] = None) -> LLMClient:
    """Resolve saved billing and model policy without credential-driven fallback."""
    from zylch.auth import get_session
    from .model_policy import profile_values, resolve_model, resolve_provider, policy_fingerprint

    values = profile_values()
    provider = resolve_provider(values)
    selected_model = resolve_model(model=model, values=values)
    if provider in ("anthropic", "openrouter"):
        key_name = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENROUTER_API_KEY"
        key = str(values.get(key_name) or "").strip()
        if not key:
            raise RuntimeError(f"Configure the API key for the selected {provider} provider in Settings.")
        client = LLMClient(
            transport="direct" if provider == "anthropic" else "openrouter",
            api_key=key,
            model=selected_model,
        )
        client._saved_policy_fingerprint = policy_fingerprint(values)
        return client
    session = get_session()
    if session is None:
        raise RuntimeError("Sign in to use the selected MrCall credits billing mode.")
    client = LLMClient(transport="proxy", firebase_session=session, model=selected_model,
                       proxy_base_url=str(values.get("MRCALL_PROXY_URL") or "https://zylch.mrcall.ai").strip())
    client._saved_policy_fingerprint = policy_fingerprint(values)
    return client


def try_make_llm_client(model: Optional[str] = None) -> Optional[LLMClient]:
    """Like :func:`make_llm_client` but returns ``None`` instead of
    raising when no transport is available. Use in background paths
    (workers, scheduled jobs) where "LLM not configured" is not an
    error worth surfacing to the user.
    """
    try:
        return make_llm_client(model)
    except RuntimeError:
        return None
