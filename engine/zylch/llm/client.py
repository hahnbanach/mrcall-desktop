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

# The response objects live in response.py; callers keep importing them from here.
from .response import LLMResponse, TextBlock, ToolUseBlock, _coerce_messages  # noqa: F401

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


@dataclass(frozen=True)
class RunClock:
    """The moment of one run: the datetime line every request of its loop carries.

    An agent loop (the chat turn, the task solve) creates one at the start of
    a turn and passes it with each request, so consecutive requests of one
    tool loop send a byte-identical ``system`` — the prefix a reasoning block
    is bound to (brief D3) — even when the minute changes mid-loop.
    """

    line: str = field(default_factory=lambda: current_datetime_line())


def _with_datetime(
    system: Optional[Union[str, List[Dict[str, Any]]]],
    clock: Optional[RunClock] = None,
) -> Union[str, List[Dict[str, Any]]]:
    """Return ``system`` with the current datetime appended.

    Appended LAST so it never busts prompt caching: the cached prefix is
    the caller's block(s) carrying ``cache_control``; the changing
    datetime sits PAST that breakpoint and is sent fresh each call
    without invalidating the cache. A bare-string ``system`` is never
    prompt-cached (caching needs the blocks + ``cache_control`` form), so
    plain concatenation is safe there too. ``None`` becomes the line on
    its own — so a request with no system prompt still carries the date.

    With a ``clock`` (:class:`RunClock`) the line is the run's, computed
    once for every request of its loop; without one it is read fresh, as a
    single call always did.
    """
    line = clock.line if clock is not None else current_datetime_line()
    if system is None:
        return line
    if isinstance(system, str):
        return f"{system}\n\n{line}"
    return list(system) + [{"type": "text", "text": line}]


# ─── Client ───────────────────────────────────────────────────────────


Transport = Literal["direct", "proxy", "openrouter", "openai_voice"]


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
        openai_project: Optional[str] = None,
        firebase_session: Optional[Any] = None,
        proxy_base_url: Optional[str] = None,
        billing_business_id: Optional[str] = None,
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
        elif transport == "openai_voice":
            from .openai_voice import OpenAIVoiceClient, MODEL
            self._client = OpenAIVoiceClient(api_key, openai_project)
            self.model = model or MODEL
        elif transport == "openrouter":
            if not api_key:
                raise ValueError("api_key is required for transport='openrouter'")
            from .openrouter_client import OpenRouterClient
            from .roles.table import pick

            self._client = OpenRouterClient(api_key=api_key)
            self.model = model or pick("economy", "CHAT", "openrouter")
        elif transport == "proxy":
            if firebase_session is None:
                raise ValueError(
                    "firebase_session is required for transport='proxy' " "(no signed-in user)"
                )
            from .bounded_proxy import BoundedProxyClient

            self._client = BoundedProxyClient(
                proxy_base_url=proxy_base_url or settings.mrcall_proxy_url,
                firebase_session=firebase_session,
                business_id=billing_business_id,
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
        model: Optional[str] = None,
        run_clock: Optional[RunClock] = None,
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
                    model=model,
                    run_clock=run_clock,
                    **kwargs,
                )
            ),
        )

    async def check_transport(self) -> None:
        """The pipeline's free preflight (``preflight.py``): no inference, nothing
        reserved. Its reads run in a thread, as a request does."""
        from .preflight import check_transport

        await asyncio.get_event_loop().run_in_executor(None, check_transport, self)

    def _release_unused_reservation(self, reservation, settle) -> None:
        """Give back a hold for a call that provably never left this process.

        Only on the unmetered transports. A metered reservation is
        receipt-gated on purpose — ``settle`` looks for the billing
        authorization and refuses without a receipt, because only the receipt
        says whether the upstream debit happened. Calling it here would not
        release anything, and its ``BudgetError`` would replace the real
        refusal with "MrCall charge is unconfirmed" for a user who simply
        cancelled. On that transport the hold stands until the in-flight
        horizon resolves it.

        A failure to release is reported and swallowed: the caller must still
        see why the dispatch was refused, not why the refund failed.
        """
        if self.transport == "proxy":
            return
        try:
            settle(reservation, {"input_tokens": 0, "output_tokens": 0})
        except Exception as exc:  # noqa: BLE001 - never mask the real refusal
            logger.warning(f"[llm] could not release an undispatched reservation: {exc}")

    def create_message_sync(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[Union[str, List[Dict[str, Any]]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Dict[str, Any]] = None,
        max_tokens: int = 4096,
        model: Optional[str] = None,
        run_clock: Optional[RunClock] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a Messages-API request and return a unified
        :class:`LLMResponse`. ``run_clock`` fixes the datetime line for every
        request of one loop (:class:`RunClock`)."""
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
            "service_tier": "standard_only",
        }
        # Always inject the current datetime (appended last → cache-safe).
        # Every LLM request carries the real moment; no exceptions.
        request_kwargs["system"] = _with_datetime(system, run_clock)
        if tools:
            request_kwargs["tools"] = tools
        if tool_choice:
            request_kwargs["tool_choice"] = tool_choice
        for key, value in kwargs.items():
            request_kwargs[key] = value
        if self.transport != "openai_voice":
            # The one shape (request_shape.py), before quote and admission, so
            # the reserved dict is the dict sent; adapters come back untouched.
            from .request_shape import shaped

            request_kwargs = shaped(request_kwargs)

        if model_name == "moonshotai/kimi-k3" and self.transport in ("openrouter", "proxy") and not ({"thinking", "output_config"} & request_kwargs.keys()):
            # The combined cap includes reasoning: worker-specific final-output
            # limits would starve the tested max-effort configuration. Apply
            # before quote/hash/admission so every reserved byte is dispatched.
            request_kwargs.update(
                thinking={"type": "adaptive"}, output_config={"effort": "max"}, max_tokens=8192
            )
        if model_name == "moonshotai/kimi-k3" and self.transport in ("openrouter", "proxy"):
            from .k3_reasoning import request_bound as validate_k3
            validate_k3(request_kwargs)

        num_tools = len(tools) if tools else 0
        logger.debug(
            f"llm request: transport={self.transport} model={model_name} "
            f"messages={len(coerced)} tools={num_tools}"
        )
        from zylch.llm.budget import reserve, settle
        from zylch.llm.sdk_request import sdk_request
        from zylch.memory.mnemonic.authorization import MnemonicAuthorizationError, assert_no_tools
        from zylch.services.preparation import check_dispatch, company_fenced, record_dispatch

        # The mnemonic role returns a proposal, never a write. Refusing tools
        # here — at the one boundary every dispatch passes — means no future
        # adapter can hand that role a generic database writer.
        assert_no_tools(request_kwargs)
        # Admission uses the final provider-visible payload, including kwargs.
        # A cancellation/timeout never releases a possibly dispatched request.
        check_dispatch()
        quote = self._client.quote(request_kwargs := sdk_request(request_kwargs, "proxy")) if self.transport == "proxy" else None
        reservation = reserve(request_kwargs, self.transport, quote=quote)
        try:
            record_dispatch()
        except (MnemonicAuthorizationError, company_fenced()):
            # Revoked or fenced between admission and dispatch: nothing
            # reached a provider, so the hold can go back.
            self._release_unused_reservation(reservation, settle)
            raise
        receipt = None
        try:
            if self.transport == "proxy":
                raw, receipt = self._client.execute(request_kwargs, quote, reservation)
            else:
                raw = self._client.messages.create(**sdk_request(request_kwargs, self.transport))
        except BaseException as exc:
            # A dispatch that raises leaves the hold open, and on the direct
            # transport nothing can ever close it: there is no receipt, so
            # `usage.reconcile` has nothing to reconcile. Callers that swallow
            # the exception — `utils/reply_need.py` swallows every one of them,
            # by contract — turn that into a permanent leak. Measured on
            # support@mrcall.ai: 113 abandoned holds worth $17.08.
            #
            # Release ONLY what the provider provably refused before doing any
            # work. Everything ambiguous — timeouts, 5xx, anything unrecognised
            # — keeps its hold, because a possibly incurred charge must not be
            # given back.
            if _rejected_before_inference(exc):
                _release_hold(reservation, settle)
            raise
        try:
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
        except BaseException:
            # The provider answered and charged us; only our handling of the
            # answer failed. Record what it actually cost rather than leaving
            # a hold for a call that is demonstrably over.
            _settle_from_raw(reservation, raw, receipt, settle)
            raise
        settle(reservation, raw_usage, receipt=receipt)

        return response


# Statuses a provider returns without running inference: the request was
# rejected on its way in, so no token was ever produced and nothing was
# charged. 5xx is deliberately absent — a server error can follow work that
# was already done — and so is every timeout, where the request may well have
# been processed after we stopped listening.
_NO_WORK_STATUSES = frozenset({400, 401, 403, 404, 413, 422, 429})


def _rejected_before_inference(exc: BaseException) -> bool:
    """True only when the provider demonstrably did no billable work."""
    try:
        import anthropic
    except Exception:  # noqa: BLE001 — the predicate must never mask the real error
        anthropic = None
    if anthropic is not None:
        # A timeout is a subclass of APIConnectionError and is NOT safe: the
        # request may have been served after we gave up waiting.
        if isinstance(exc, anthropic.APITimeoutError):
            return False
        if isinstance(exc, anthropic.APIConnectionError):
            return True
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and status in _NO_WORK_STATUSES


def _release_hold(reservation, settle) -> None:
    """Give back a hold for a call that was refused before it cost anything.

    Never on the metered transport: there `settle` is receipt-gated on purpose,
    because only the receipt says whether the upstream debit happened, and
    calling it without one raises instead of releasing. A failure to release is
    reported and swallowed — the caller must still see why the dispatch failed,
    not why the refund did.
    """
    if reservation.transport == "proxy":
        return
    try:
        # A refused call cost nothing. OpenRouter settles on a receipt's `cost`,
        # so the release states it; the other transports price the token counts.
        settle(reservation, {"input_tokens": 0, "output_tokens": 0, "cost": 0})
    except Exception as release_error:  # noqa: BLE001
        logger.warning(
            "[budget] could not release the hold for a refused dispatch (%s: %s)",
            type(release_error).__name__,
            release_error,
        )


def _settle_from_raw(reservation, raw, receipt, settle) -> None:
    """Settle from a response we received but failed to handle."""
    usage = getattr(raw, "usage", None)
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    elif usage is not None and not isinstance(usage, dict):
        usage = vars(usage)
    try:
        settle(reservation, usage, receipt=receipt)
    except Exception as settle_error:  # noqa: BLE001
        logger.warning(
            "[budget] could not settle the hold for an unhandled response (%s: %s)",
            type(settle_error).__name__,
            settle_error,
        )


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
                       proxy_base_url=str(values.get("MRCALL_PROXY_URL") or "https://zylch.mrcall.ai").strip(),
                       billing_business_id=str(values.get("SMS_BUSINESS_ID") or "").strip())
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
