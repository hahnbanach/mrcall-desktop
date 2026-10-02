"""The Anthropic-shape response every transport returns, reasoning included.

Moved out of ``client.py`` (milestone 10, brief D3), which re-exports these
names, so ``from zylch.llm.client import LLMResponse`` keeps working.

``LLMResponse.content`` stays what callers read — text and tool_use blocks —
while ``assistant_content`` is the whole assistant turn: every block in order,
reasoning blocks (``thinking``, ``redacted_thinking``) included, as the plain
dicts a tool loop replays unchanged. Within a tool loop the provider needs
those blocks back exactly as it sent them; where the engine rewrites history
instead, :func:`without_reasoning` removes them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

# The reasoning block types of the Messages API, on every transport.
REASONING = ("thinking", "redacted_thinking")


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


def _kind(block: Any) -> Optional[str]:
    return block.get("type") if isinstance(block, dict) else getattr(block, "type", None)


def _well_formed_reasoning(block: Any) -> bool:
    """A reasoning block as the providers send it, nothing to repair.

    ``thinking`` carries its text and, on Anthropic, a signature (OpenRouter
    may omit the signature, never send another type in its place);
    ``redacted_thinking`` carries non-empty opaque ``data``.
    """
    kind = getattr(block, "type", None)
    if kind == "thinking":
        signature = getattr(block, "signature", None)
        return isinstance(getattr(block, "thinking", None), str) and (
            signature is None or isinstance(signature, str)
        )
    data = getattr(block, "data", None)
    return kind == "redacted_thinking" and isinstance(data, str) and bool(data)


class LLMResponse:
    """Adapter exposing the Anthropic-shape fields callers care about.

    Both transports return Anthropic-shape Message objects (the proxy
    reconstructs them from SSE), so this adapter only needs the
    Anthropic branch. Reasoning blocks are kept, not dropped: ``content``
    leaves them out because no caller reads them, ``assistant_content``
    keeps them for the replay a tool loop owes the provider.
    """

    def __init__(self, raw_response: Any, *, normalize_tool_completion: bool = True):
        self._normalize_tool_completion = normalize_tool_completion
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
        if self._normalize_tool_completion and self._complete_tool_turn():
            self._stop_reason = "tool_use"

    def _complete_tool_turn(self) -> bool:
        """Recognize complete tool turns without repairing malformed provider data.

        A well-formed reasoning block is part of a complete turn (a reasoning
        model leads its tool calls with one); a malformed one is not repaired.
        """
        if self._raw.stop_reason != "end_turn" or getattr(self._raw, "refusal", None):
            return False
        has_tool = False
        for block in self._raw.content:
            if getattr(block, "refusal", None):
                return False
            kind = getattr(block, "type", None)
            if kind == "text":
                if not isinstance(getattr(block, "text", None), str):
                    return False
            elif kind == "tool_use":
                if not all(
                    isinstance(getattr(block, field, None), str) and getattr(block, field).strip()
                    for field in ("id", "name")
                ) or not isinstance(getattr(block, "input", None), dict):
                    return False
                has_tool = True
            elif kind not in REASONING or not _well_formed_reasoning(block):
                return False
        return has_tool

    @property
    def original_stop_reason(self) -> Optional[str]:
        return getattr(self._raw, "stop_reason", None)

    @property
    def content(self) -> List[Union[TextBlock, ToolUseBlock]]:
        return self._content

    @property
    def assistant_content(self) -> List[Any]:
        """Every block of the turn, in order, reasoning included, as dicts.

        What a tool loop appends to its history and sends back on the next
        request: a fresh list each time, so a caller may edit its copy.
        """
        raw = getattr(self._raw, "content", None)
        return [_coerce_block(block) for block in raw] if isinstance(raw, list) else []

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
    so we normalise here once. Reasoning blocks keep exactly their
    documented fields (a signature only when the provider sent one), so
    the replayed block is the block the provider signed.
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
    if btype == "thinking":
        out = {"type": "thinking", "thinking": getattr(block, "thinking", "")}
        if getattr(block, "signature", None) is not None:
            out["signature"] = block.signature
        return out
    if btype == "redacted_thinking":
        return {"type": "redacted_thinking", "data": getattr(block, "data", "")}
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


def assistant_blocks(response: Any) -> List[Any]:
    """The assistant turn a tool loop replays: ``assistant_content`` when the
    response has one (every :class:`LLMResponse`), else its ``content`` as dicts."""
    blocks = getattr(response, "assistant_content", None)
    if blocks is None:
        blocks = [_coerce_block(block) for block in getattr(response, "content", None) or []]
    return blocks


def without_reasoning(messages: List[Any]) -> List[Any]:
    """``messages`` with every reasoning block removed (brief D3).

    Where the engine rewrites history — a new user turn after earlier tool
    loops, chat compaction — the retained turns carry no reasoning: a
    reasoning block is bound to the conversation before it, and the API
    permits leaving earlier turns' blocks out (they lead their assistant
    turn). A message that held nothing else is dropped; the API merges the
    consecutive turns that leaves. The input is never mutated.
    """
    out: List[Any] = []
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            out.append(message)
            continue
        kept = [block for block in content if _kind(block) not in REASONING]
        if len(kept) == len(content):
            out.append(message)
        elif kept:
            out.append({**message, "content": kept})
    return out
