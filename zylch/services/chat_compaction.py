"""Automatic compaction of ChatService conversation history.

When a chat conversation grows past ``SOFT_LIMIT`` tokens we summarize
the middle portion via Haiku and splice the summary into the history,
keeping the first turn intact (for rapport / task context) and the last
``KEEP_RECENT`` turns intact (for precise short-term memory).

Token counting uses a cheap char-based heuristic (``~4 chars ≈ 1 token``)
to avoid adding a ``tiktoken`` dependency. The heuristic over-estimates
slightly, which is the safe direction — we compact a little sooner
rather than blow past the context window.

All failures are swallowed and the original history is returned — a
compaction bug must never break the user's chat turn.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Haiku is cheap and fast. Model ID is pinned to the one the user named
# in the task — if it drifts we fall back to the env override.
_COMPACTION_MODEL = os.environ.get(
    "ZYLCH_COMPACTION_MODEL",
    "claude-haiku-4-5-20251001",
)

# Trigger threshold in tokens. Anthropic 1M context is the hard ceiling;
# 80K keeps plenty of headroom for the system prompt, tools, and the
# fresh turn being processed.
SOFT_LIMIT = 80_000

# First N turns to keep verbatim at the head.
KEEP_FIRST = 1

# Last N turns to keep verbatim at the tail.
KEEP_RECENT = 10

# Chars-per-token heuristic (Anthropic guidance: ~4).
_CHARS_PER_TOKEN = 4


def _estimate_tokens(history: List[Dict[str, Any]]) -> int:
    """Rough token count for ``history`` using a 4-chars-per-token rule."""
    total_chars = 0
    for msg in history:
        content = msg.get("content") if isinstance(msg, dict) else None
        if content is None:
            continue
        if isinstance(content, str):
            total_chars += len(content)
            continue
        if isinstance(content, list):
            for block in content:
                if isinstance(block, str):
                    total_chars += len(block)
                elif isinstance(block, dict):
                    # Best-effort: dump the whole block including tool_use /
                    # tool_result payloads so their bodies are accounted for.
                    try:
                        total_chars += len(json.dumps(block, default=str))
                    except Exception:
                        total_chars += len(str(block))
                else:
                    total_chars += len(str(block))
            continue
        total_chars += len(str(content))
    return total_chars // _CHARS_PER_TOKEN


def _narrate_block(block: Any) -> str:
    """Return a short prose sentence describing a content block.

    Tool use / tool result blocks in the middle of a long conversation
    don't need their full payload in the summary — just a line that says
    which tool ran and what it returned at a glance. Text blocks are
    emitted verbatim (the summarizer LLM can condense further).
    """
    if isinstance(block, str):
        return block
    if not isinstance(block, dict):
        return str(block)
    btype = block.get("type")
    if btype == "text":
        return str(block.get("text", ""))
    if btype == "tool_use":
        name = block.get("name", "?")
        try:
            inp = json.dumps(block.get("input", {}), ensure_ascii=False, default=str)
        except Exception:
            inp = str(block.get("input", {}))
        # Keep payload bounded so one huge tool_use doesn't dominate the
        # summarizer input. This trims the PROMPT to Haiku, not what the
        # main chat LLM sees — per project rules, no [:N] on the main
        # LLM inputs.
        if len(inp) > 2000:
            inp = inp[:2000] + "…"
        return f"[tool_use {name}({inp})]"
    if btype == "tool_result":
        content = block.get("content", "")
        if isinstance(content, list):
            try:
                content = json.dumps(content, ensure_ascii=False, default=str)
            except Exception:
                content = str(content)
        content = str(content)
        if len(content) > 2000:
            content = content[:2000] + "…"
        tool_id = block.get("tool_use_id", "?")
        return f"[tool_result id={tool_id} -> {content}]"
    # Fallback: dump the block so nothing is silently dropped.
    try:
        return json.dumps(block, ensure_ascii=False, default=str)
    except Exception:
        return str(block)


def _render_middle_for_summary(middle: List[Dict[str, Any]]) -> str:
    """Render the middle slice of the history as prose for the summarizer."""
    lines: List[str] = []
    for msg in middle:
        role = msg.get("role", "?") if isinstance(msg, dict) else "?"
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, list):
            narrated = " ".join(_narrate_block(b) for b in content if b is not None)
        else:
            narrated = _narrate_block(content)
        lines.append(f"{role.upper()}: {narrated}")
    return "\n\n".join(lines)


async def _summarize(middle_text: str) -> str:
    """Call Haiku to summarize ``middle_text`` into a single block.

    Returns the summary string on success, raises on failure — callers
    handle the exception.
    """
    import anthropic

    client = anthropic.AsyncAnthropic()
    system = (
        "You are a conversation summarizer. Produce a concise, faithful "
        "summary of the CHAT HISTORY below. Keep the same language as the "
        "conversation (mixed languages are fine). Capture: user intents, "
        "decisions made, drafts created, tools invoked and their results, "
        "any identifiers (task IDs, email IDs, draft IDs) the assistant "
        "must remember. Do NOT invent facts. Output prose only — no "
        "headings, no lists unless the original had lists."
    )
    resp = await client.messages.create(
        model=_COMPACTION_MODEL,
        max_tokens=4096,
        system=system,
        messages=[
            {
                "role": "user",
                "content": f"CHAT HISTORY:\n\n{middle_text}\n\n---\n\n" "Write the summary now.",
            }
        ],
    )
    parts: List[str] = []
    for block in resp.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            parts.append(getattr(block, "text", ""))
    summary = "".join(parts).strip()
    if not summary:
        raise RuntimeError("Haiku returned empty summary")
    return summary


async def compact_if_needed(
    history: List[Dict[str, Any]],
    soft_limit: int = SOFT_LIMIT,
    keep_first: int = KEEP_FIRST,
    keep_recent: int = KEEP_RECENT,
) -> List[Dict[str, Any]]:
    """Compact ``history`` if its estimated token count exceeds ``soft_limit``.

    On success returns ``[first_turn(s), <summary user msg>, <last N turns>]``.
    On any failure (or when the middle is empty) returns ``history`` unchanged.
    """
    if not isinstance(history, list) or not history:
        return history

    # Need enough turns that middle is non-empty. If the user only has
    # first+recent turns, there is no middle to compact.
    if len(history) <= keep_first + keep_recent:
        return history

    estimated = _estimate_tokens(history)
    if estimated < soft_limit:
        return history

    logger.info(
        f"[compaction] triggered: history_len={len(history)} "
        f"estimated_tokens={estimated} soft_limit={soft_limit} "
        f"keep_first={keep_first} keep_recent={keep_recent}"
    )

    head = history[:keep_first]
    tail = history[-keep_recent:]
    middle = history[keep_first:-keep_recent]
    if not middle:
        return history

    try:
        middle_text = _render_middle_for_summary(middle)
        summary = await _summarize(middle_text)
    except Exception as e:
        logger.warning(f"[compaction] summarization failed, returning original history: {e}")
        return history

    summary_block = {
        "role": "user",
        "content": (
            "[Previous conversation summary — the earlier portion of this "
            "chat has been compacted. Treat the following as authoritative "
            "background for what happened before the recent turns below:]\n\n"
            f"{summary}"
        ),
    }
    new_history = list(head) + [summary_block] + list(tail)
    logger.info(
        f"[compaction] done: original_len={len(history)} "
        f"compacted_len={len(new_history)} summary_chars={len(summary)}"
    )
    return new_history
