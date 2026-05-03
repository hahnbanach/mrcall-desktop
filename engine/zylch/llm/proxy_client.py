"""MrCall credit-mode LLM client.

A drop-in replacement for the subset of the `anthropic.Anthropic()` SDK
surface that `LLMClient` actually uses (`client.messages.create(**kwargs)`
returning a `Message`-like object with `.content`, `.stop_reason`,
`.usage`, `.model`).

The "MrCall credits" billing mode routes the call through
`mrcall-agent`'s `POST /api/desktop/llm/proxy` endpoint instead of going
straight to Anthropic. The proxy:

  - authenticates via the user's Firebase ID token (header `auth: <jwt>`,
    no Bearer prefix — same convention StarChat uses);
  - returns an Anthropic-format SSE stream (`message_start`,
    `content_block_*`, `message_delta`, `message_stop`); we accumulate
    those events and reconstruct a single Message-shaped object so the
    downstream `LLMResponse` adapter is unaware that streaming happened;
  - charges the user's `CALLCREDIT` credit balance (StarChat-side; the
    same unified pool that funds phone-call minutes — there is no
    separate LLM-only category since the 2026-05 pivot); on 402 we
    surface a typed exception the renderer can show as a "top up" toast.

We never log the JWT — only its length / first 8 characters at most,
matching the rest of the engine's secret-logging policy.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


# ─── Exceptions ───────────────────────────────────────────────────────


class MrCallProxyError(RuntimeError):
    """Generic transport / 5xx error from the MrCall proxy.

    Attributes:
        status: HTTP status code returned by the proxy (or 0 if the call
            never completed an HTTP exchange).
        detail: Server-provided error detail when available; otherwise
            a short description of the transport failure.
    """

    def __init__(self, status: int, detail: str):
        super().__init__(f"MrCall proxy error ({status}): {detail}")
        self.status = status
        self.detail = detail


class MrCallAuthError(MrCallProxyError):
    """401 from the proxy — Firebase token rejected (expired / invalid).

    The caller is expected to prompt the user to re-sign-in.
    """

    def __init__(self, detail: str = "Firebase token rejected"):
        super().__init__(401, detail)


class MrCallInsufficientCredits(MrCallProxyError):
    """402 from the proxy — pre-flight credit check failed.

    Attributes:
        available: Credits remaining at the time of the rejection (0 in
            the typical case but the proxy may surface a non-zero value
            if it ever adds a "minimum balance" rule).
        topup_url: Where to send the user to recharge.
    """

    def __init__(self, available: int, topup_url: str):
        super().__init__(
            402,
            f"insufficient_credits (available={available}, topup_url={topup_url})",
        )
        self.available = available
        self.topup_url = topup_url


# ─── Anthropic-shape return objects ───────────────────────────────────
#
# These mimic the attributes the `anthropic` SDK Message exposes, but
# only the fields the engine's LLMResponse adapter actually reads
# (`.content` items with `.type`/`.text`/`.id`/`.name`/`.input`,
# `.stop_reason`, `.model`, `.usage` with the four token counters we
# track). Plain dataclasses keep this dependency-free.


@dataclass
class _ProxyTextBlock:
    text: str = ""
    type: str = "text"


@dataclass
class _ProxyToolUseBlock:
    id: str = ""
    name: str = ""
    input: Dict[str, Any] = field(default_factory=dict)
    type: str = "tool_use"


@dataclass
class _ProxyUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class _ProxyMessage:
    """Mimics enough of `anthropic.types.Message` for `LLMResponse`."""

    content: List[Any] = field(default_factory=list)
    stop_reason: str = "end_turn"
    model: str = ""
    usage: Optional[_ProxyUsage] = None
    id: str = ""
    role: str = "assistant"
    type: str = "message"


# ─── SSE parsing ──────────────────────────────────────────────────────


def _iter_sse_events(byte_iter: Iterator[bytes]) -> Iterator[Tuple[Optional[str], str]]:
    """Yield `(event_name, data_str)` tuples from a raw SSE byte stream.

    Anthropic SSE format follows the spec: an event = one or more lines
    `event: <name>` and `data: <json>` separated by a blank line. We
    handle multi-line `data:` by joining with newlines (per the spec)
    even though Anthropic always emits single-line data today.
    """
    buffer = b""
    for chunk in byte_iter:
        if not chunk:
            continue
        buffer += chunk
        while b"\n\n" in buffer:
            raw_event, buffer = buffer.split(b"\n\n", 1)
            event_name: Optional[str] = None
            data_lines: List[str] = []
            for raw_line in raw_event.split(b"\n"):
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r")
                if not line or line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_name = line[len("event:") :].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[len("data:") :].lstrip())
            if data_lines:
                yield event_name, "\n".join(data_lines)
    # Flush any trailing event that lacked the final blank line — the
    # proxy is expected to always end with `\n\n`, but be robust anyway.
    if buffer.strip():
        event_name = None
        data_lines = []
        for raw_line in buffer.split(b"\n"):
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r")
            if not line or line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].lstrip())
        if data_lines:
            yield event_name, "\n".join(data_lines)


def _accumulate_events(events: Iterator[Tuple[Optional[str], str]]) -> _ProxyMessage:
    """Reconstruct a Message from an Anthropic-format SSE stream.

    Anthropic's documented streaming contract:

      message_start          → {message: {id, model, usage(initial), ...}}
      content_block_start    → {index, content_block: {type, ...}}
      content_block_delta    → {index, delta: {type: text_delta|input_json_delta, ...}}
      content_block_stop     → {index}
      message_delta          → {delta: {stop_reason, stop_sequence}, usage: {output_tokens}}
      message_stop           → {} or final message snapshot

    We only need to assemble the content blocks (text accumulation +
    tool_use input JSON) and pull final stop_reason + usage. Anything
    we don't recognize is logged and ignored — robust against future
    event types.
    """
    msg = _ProxyMessage()
    blocks_by_index: Dict[int, Any] = {}
    tool_input_json_buf: Dict[int, str] = {}
    text_buf: Dict[int, List[str]] = {}

    for event_name, data_str in events:
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            logger.warning(f"[mrcall-proxy] SSE data not JSON; event={event_name!r}")
            continue

        ev = event_name or data.get("type")

        if ev == "message_start":
            inner = data.get("message", {}) or {}
            msg.id = inner.get("id", msg.id)
            msg.model = inner.get("model", msg.model)
            msg.role = inner.get("role", msg.role)
            usage = inner.get("usage") or {}
            if usage:
                msg.usage = _ProxyUsage(
                    input_tokens=int(usage.get("input_tokens") or 0),
                    output_tokens=int(usage.get("output_tokens") or 0),
                    cache_creation_input_tokens=int(
                        usage.get("cache_creation_input_tokens") or 0
                    ),
                    cache_read_input_tokens=int(usage.get("cache_read_input_tokens") or 0),
                )

        elif ev == "content_block_start":
            idx = int(data.get("index", 0))
            cb = data.get("content_block") or {}
            ctype = cb.get("type")
            if ctype == "text":
                blk = _ProxyTextBlock(text=cb.get("text", "") or "")
                blocks_by_index[idx] = blk
                text_buf[idx] = [blk.text] if blk.text else []
            elif ctype == "tool_use":
                blk = _ProxyToolUseBlock(
                    id=cb.get("id", ""),
                    name=cb.get("name", ""),
                    input=dict(cb.get("input") or {}),
                )
                blocks_by_index[idx] = blk
                tool_input_json_buf[idx] = ""
            else:
                # Unknown / future content block type — keep a minimal
                # placeholder so indices line up with content_block_stop.
                logger.debug(f"[mrcall-proxy] unknown content_block type={ctype}")
                blocks_by_index[idx] = cb

        elif ev == "content_block_delta":
            idx = int(data.get("index", 0))
            delta = data.get("delta") or {}
            dtype = delta.get("type")
            if dtype == "text_delta":
                text_buf.setdefault(idx, []).append(delta.get("text", "") or "")
            elif dtype == "input_json_delta":
                tool_input_json_buf[idx] = (
                    tool_input_json_buf.get(idx, "") + (delta.get("partial_json", "") or "")
                )
            else:
                logger.debug(f"[mrcall-proxy] unknown delta type={dtype}")

        elif ev == "content_block_stop":
            idx = int(data.get("index", 0))
            blk = blocks_by_index.get(idx)
            if isinstance(blk, _ProxyTextBlock):
                blk.text = "".join(text_buf.get(idx, []))
            elif isinstance(blk, _ProxyToolUseBlock):
                buf = tool_input_json_buf.get(idx, "")
                if buf:
                    try:
                        blk.input = json.loads(buf)
                    except json.JSONDecodeError:
                        logger.warning(
                            f"[mrcall-proxy] tool_use input JSON parse failed; "
                            f"len={len(buf)}; keeping initial input"
                        )

        elif ev == "message_delta":
            delta = data.get("delta") or {}
            sr = delta.get("stop_reason")
            if sr:
                msg.stop_reason = sr
            usage = data.get("usage") or {}
            if usage:
                if msg.usage is None:
                    msg.usage = _ProxyUsage()
                # output_tokens is the final count on message_delta;
                # cache fields can also appear here on some SDK versions.
                if "output_tokens" in usage:
                    msg.usage.output_tokens = int(usage["output_tokens"] or 0)
                if "input_tokens" in usage:
                    msg.usage.input_tokens = int(usage["input_tokens"] or 0)
                if "cache_creation_input_tokens" in usage:
                    msg.usage.cache_creation_input_tokens = int(
                        usage["cache_creation_input_tokens"] or 0
                    )
                if "cache_read_input_tokens" in usage:
                    msg.usage.cache_read_input_tokens = int(
                        usage["cache_read_input_tokens"] or 0
                    )

        elif ev == "message_stop":
            # Some implementations attach a full message snapshot here;
            # take it as a tiebreaker for usage / stop_reason.
            inner = data.get("message")
            if isinstance(inner, dict):
                if "stop_reason" in inner and inner["stop_reason"]:
                    msg.stop_reason = inner["stop_reason"]
                usage = inner.get("usage") or {}
                if usage:
                    if msg.usage is None:
                        msg.usage = _ProxyUsage()
                    for k in (
                        "input_tokens",
                        "output_tokens",
                        "cache_creation_input_tokens",
                        "cache_read_input_tokens",
                    ):
                        if k in usage and usage[k] is not None:
                            setattr(msg.usage, k, int(usage[k]))

        elif ev == "ping":
            # Anthropic-defined keep-alive; ignore.
            pass

        elif ev == "error":
            err = data.get("error") or data
            etype = err.get("type", "unknown") if isinstance(err, dict) else "unknown"
            emsg = err.get("message", "") if isinstance(err, dict) else str(err)
            logger.warning(f"[mrcall-proxy] SSE error event type={etype} message={emsg!r}")
            raise MrCallProxyError(502, f"upstream_error: {etype}: {emsg}")

        else:
            logger.debug(f"[mrcall-proxy] unhandled SSE event={ev!r}")

    # Materialize content list in index order so callers see blocks the
    # way Anthropic's non-streaming SDK would have returned them.
    msg.content = [blocks_by_index[i] for i in sorted(blocks_by_index.keys())]
    if msg.usage is None:
        msg.usage = _ProxyUsage()
    return msg


# ─── Public client surface ────────────────────────────────────────────


# Anthropic kwargs we forward to the proxy. Any kwarg not in this set is
# logged and dropped — this avoids accidentally leaking
# implementation-detail kwargs (e.g. `cache_control` on a per-message
# basis is encoded inside `messages` already).
_FORWARDED_KWARGS = frozenset(
    [
        "model",
        "messages",
        "system",
        "tools",
        "tool_choice",
        "max_tokens",
        "temperature",
        "top_p",
        "top_k",
        "stop_sequences",
        "metadata",
        "service_tier",
    ]
)


class _MessagesNamespace:
    """Mirror of `anthropic.Anthropic().messages` — exposes `.create`."""

    def __init__(self, client: "MrCallProxyClient"):
        self._client = client

    def create(self, **kwargs: Any) -> _ProxyMessage:
        """Synchronous Message creation — mirrors the Anthropic SDK call.

        We always request streaming from the proxy (the proxy contract
        is SSE-only) and re-assemble the events into a single
        Message-shaped object before returning. The caller never sees
        the SSE plumbing.
        """
        return self._client._do_create(kwargs)


class MrCallProxyClient:
    """Anthropic-shape client that POSTs to mrcall-agent's proxy.

    Construction:

        from zylch.auth import get_session
        client = MrCallProxyClient(
            proxy_base_url=settings.mrcall_proxy_url,
            firebase_session=get_session(),  # any object exposing .id_token
        )

    Use:

        msg = client.messages.create(model="...", messages=[...], max_tokens=4096)
        for block in msg.content: ...
        print(msg.usage.input_tokens, msg.usage.output_tokens)
    """

    def __init__(
        self,
        proxy_base_url: str,
        firebase_session: Any,
        *,
        timeout: float = 600.0,
        verify_ssl: bool = True,
    ):
        if not proxy_base_url:
            raise ValueError("proxy_base_url is required")
        if firebase_session is None:
            raise ValueError("firebase_session is required (no signed-in user)")
        self.proxy_base_url = proxy_base_url.rstrip("/")
        self._session = firebase_session
        self._timeout = timeout
        self._verify_ssl = verify_ssl
        self.messages = _MessagesNamespace(self)
        # Match the engine's logging policy: never log the token; only
        # its length, which is a safe fingerprint.
        token = self._current_id_token()
        logger.info(
            f"[mrcall-proxy] init proxy_base_url={self.proxy_base_url} "
            f"token_len={len(token) if token else 0}"
        )

    # Token reads go through this so a future token-refresh hook on the
    # session has a single integration point.
    def _current_id_token(self) -> str:
        token = getattr(self._session, "id_token", None)
        if not isinstance(token, str) or not token:
            raise MrCallAuthError("No Firebase ID token on the session")
        return token

    def _build_headers(self) -> Dict[str, str]:
        # `auth:` (no Bearer prefix) matches StarChat / mrcall-agent
        # convention used elsewhere in the engine; see
        # zylch/tools/starchat.py:_build_headers.
        return {
            "auth": self._current_id_token(),
            "content-type": "application/json",
            "accept": "text/event-stream",
            "user-agent": "zylch-mrcall-proxy/0.1",
        }

    def _build_body(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        for k, v in kwargs.items():
            if k in _FORWARDED_KWARGS:
                body[k] = v
            elif k == "stream":
                # Honour caller intent if they explicitly pass stream=True;
                # we always force True below regardless.
                continue
            else:
                logger.debug(f"[mrcall-proxy] dropping unsupported kwarg={k!r}")
        # The proxy contract is SSE-only — always stream.
        body["stream"] = True
        return body

    def _decode_error(
        self, response: httpx.Response
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                return payload, json.dumps(payload)[:500]
        except Exception:  # noqa: BLE001 — any decode failure falls through
            pass
        return None, (response.text or "")[:500]

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        payload, raw = self._decode_error(response)
        if response.status_code == 401:
            detail = (
                (payload or {}).get("detail") if isinstance(payload, dict) else None
            ) or (payload or {}).get("error") if isinstance(payload, dict) else raw
            raise MrCallAuthError(str(detail or "unauthorized"))
        if response.status_code == 402:
            available = 0
            topup_url = ""
            if isinstance(payload, dict):
                available = int(payload.get("available", 0) or 0)
                topup_url = str(payload.get("topup_url", "") or "")
            raise MrCallInsufficientCredits(available=available, topup_url=topup_url)
        # 403 / 429 / 5xx / etc. — generic.
        raise MrCallProxyError(response.status_code, raw)

    # ─── core call ────────────────────────────────────────────────
    def _do_create(self, kwargs: Dict[str, Any]) -> _ProxyMessage:
        body = self._build_body(kwargs)
        headers = self._build_headers()
        url = f"{self.proxy_base_url}/api/desktop/llm/proxy"
        model = body.get("model", "?")
        msg_count = len(body.get("messages") or [])
        logger.debug(
            f"[mrcall-proxy] POST {url} model={model} messages={msg_count} "
            f"stream={body.get('stream')}"
        )

        # Sync httpx — we open and close per call. The engine wraps the
        # sync entry points in run_in_executor (see LLMClient.create_message),
        # so blocking inside this method is fine.
        try:
            with httpx.Client(timeout=self._timeout, verify=self._verify_ssl) as client:
                with client.stream("POST", url, headers=headers, json=body) as response:
                    if response.status_code >= 400:
                        # Buffer the body so _raise_for_status can read JSON.
                        response.read()
                        self._raise_for_status(response)
                    logger.debug(
                        f"[mrcall-proxy] stream open status={response.status_code} model={model}"
                    )
                    events = _iter_sse_events(response.iter_bytes())
                    msg = _accumulate_events(events)
        except (MrCallProxyError, MrCallAuthError, MrCallInsufficientCredits):
            raise
        except httpx.HTTPError as exc:
            raise MrCallProxyError(0, f"transport_error: {exc}") from exc

        logger.debug(
            f"[mrcall-proxy] stream closed model={msg.model or model} "
            f"blocks={len(msg.content)} stop_reason={msg.stop_reason} "
            f"usage(in/out/cw/cr)={msg.usage.input_tokens}/"
            f"{msg.usage.output_tokens}/"
            f"{msg.usage.cache_creation_input_tokens}/"
            f"{msg.usage.cache_read_input_tokens}"
        )
        # Make sure .model is always populated for downstream callers
        # that print it; fall back to the requested model if the proxy
        # didn't include one in message_start (it should, per Anthropic).
        if not msg.model:
            msg.model = model
        return msg
