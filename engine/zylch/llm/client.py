"""Unified LLM client for the engine.

The engine uses a single provider — Anthropic — over one of two
transports:

- ``direct``: BYOK. The user's ``ANTHROPIC_API_KEY`` from the profile
  ``.env`` is used to call Anthropic's SDK directly.
- ``proxy``: MrCall credits. Calls are routed through ``mrcall-agent``'s
  proxy and billed against the user's MrCall credit balance. The
  credential is the in-memory Firebase ID token held by
  :mod:`zylch.auth.session`.

Both transports return Anthropic-shape ``Message`` objects, so the rest
of the engine sees a uniform interface and never branches on the
transport.

Callers don't pick the transport. They call :func:`make_llm_client`,
which inspects ``settings.anthropic_api_key`` and the Firebase session
and returns a ready :class:`LLMClient`. Background workers that should
silently skip when no LLM is configured use :func:`try_make_llm_client`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from dataclasses import dataclass, field
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
        self._stop_reason: str = "end_turn"
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
        self._stop_reason = self._raw.stop_reason or "end_turn"

    @property
    def content(self) -> List[Union[TextBlock, ToolUseBlock]]:
        return self._content

    @property
    def stop_reason(self) -> str:
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
        return {
            "input_tokens": int(getattr(u, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(u, "output_tokens", 0) or 0),
            "cache_creation_input_tokens": int(getattr(u, "cache_creation_input_tokens", 0) or 0),
            "cache_read_input_tokens": int(getattr(u, "cache_read_input_tokens", 0) or 0),
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


Transport = Literal["direct", "proxy"]


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
        model: Optional[str] = None,
    ) -> None:
        from zylch.config import settings

        if transport == "direct":
            if not api_key:
                raise ValueError("api_key is required for transport='direct'")
            import anthropic

            # 2026-05-06: bump max_retries from the SDK default (2) to 5.
            # The SDK retries on 408/409/429/≥500 with exponential
            # backoff (0.5 → 16 s in this version). Default 2 = 3 total
            # attempts spanning ~3 s, which is too short for an
            # overloaded_error (529) cluster — the F4 sweep + F8 dedup
            # together fire ~20 calls per /update, all of which fail
            # in lockstep when Anthropic is briefly overloaded.
            # 5 retries spans ~30 s, which covers transient capacity
            # blips without making the user wait forever on a real
            # outage.
            self._client = anthropic.Anthropic(api_key=api_key, max_retries=5)
            self.model = model or settings.anthropic_model
        elif transport == "proxy":
            if firebase_session is None:
                raise ValueError(
                    "firebase_session is required for transport='proxy' " "(no signed-in user)"
                )
            from .proxy_client import MrCallProxyClient

            self._client = MrCallProxyClient(
                proxy_base_url=settings.mrcall_proxy_url,
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
        """Async wrapper around :meth:`create_message_sync`."""
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self.create_message_sync(
                messages=messages,
                system=system,
                tools=tools,
                tool_choice=tool_choice,
                max_tokens=max_tokens,
                temperature=temperature,
                model=model,
                **kwargs,
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
        model_name = model or self.model
        coerced = _coerce_messages(messages)

        request_kwargs: Dict[str, Any] = {
            "model": model_name,
            "messages": coerced,
            "max_tokens": max_tokens,
            "temperature": temperature,
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
        raw = self._client.messages.create(**request_kwargs)
        return LLMResponse(raw)


# ─── Factory ──────────────────────────────────────────────────────────


def _read_profile_anthropic_key() -> Optional[str]:
    """Read ``ANTHROPIC_API_KEY`` directly from the active profile's
    ``.env`` file, ignoring the global shell env.

    Why bypass Pydantic Settings: ``settings.anthropic_api_key`` is the
    MERGED value (env var > .env file > default), so a key exported in
    the user's ``~/.bash_profile`` silently bleeds into the desktop
    sidecar (Electron spawns the sidecar with the parent process env)
    and routes every LLM call through BYOK ``direct`` transport. The
    user thinks they're on MrCall credits (no key in the Settings UI,
    `LLMProviderCard` shows "MrCall credits") but the credit balance
    never decreases because no call ever reaches the proxy. Mario
    chased this for days on ``production@example.com``.

    The profile ``.env`` is the source of truth the Settings UI writes
    to, so anchoring the BYOK decision there closes the leak. Returns
    the key string when present (non-empty after stripping quotes) or
    ``None`` when absent / file missing / unreadable.
    """
    profile_dir = os.environ.get("ZYLCH_PROFILE_DIR") or os.path.expanduser("~/.zylch")
    env_path = os.path.join(profile_dir, ".env")
    if not os.path.isfile(env_path):
        return None
    try:
        with open(env_path, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if not line.startswith("ANTHROPIC_API_KEY"):
                    continue
                # Match KEY=value, KEY = value, KEY="value", KEY='value'
                _, _, value = line.partition("=")
                value = value.strip().strip('"').strip("'")
                return value or None
    except Exception as e:
        logger.warning(f"[llm] failed to read {env_path}: {e}")
    return None


def make_llm_client(model: Optional[str] = None) -> LLMClient:
    """Build an :class:`LLMClient` for the active profile.

    Resolution order:

    1. ``ANTHROPIC_API_KEY`` present in the **profile** ``.env`` (NOT
       the shell env — see :func:`_read_profile_anthropic_key`) → BYOK
       (``transport='direct'``).
    2. Otherwise → MrCall credits (``transport='proxy'``). Requires a
       live Firebase session; raises :class:`RuntimeError` otherwise.

    Callers that should silently skip when no LLM is available
    (e.g. background workers) use :func:`try_make_llm_client` instead.
    """
    from zylch.auth import get_session

    profile_key = _read_profile_anthropic_key()
    if profile_key:
        logger.debug("[llm] make_llm_client: profile has ANTHROPIC_API_KEY → direct")
        return LLMClient(
            transport="direct",
            api_key=profile_key,
            model=model,
        )
    session = get_session()
    if session is None:
        raise RuntimeError(
            "No LLM configured: set ANTHROPIC_API_KEY in the profile .env "
            "(Settings → LLM) or sign in with Firebase to use MrCall credits."
        )
    logger.debug("[llm] make_llm_client: no profile key → proxy (MrCall credits)")
    return LLMClient(
        transport="proxy",
        firebase_session=session,
        model=model,
    )


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
