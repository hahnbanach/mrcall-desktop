"""The chat's wire transcript: the user turn as it was sent, and the cache marker.

Consecutive requests of one tool loop must share a byte-identical prefix —
system, tools and every earlier message — because Anthropic binds each
reasoning block to the conversation before it (brief D3) and the prompt cache
reads only an unchanged prefix. Two things used to edit that prefix between
the requests of one loop:

- the volatile per-turn context (date/time, channel status) was appended to
  the LAST message on the wire only, so the loop's next request moved it from
  the user turn to the tool results;
- the system prompt's datetime line was computed per request (``RunClock`` in
  ``zylch/llm/client.py`` now fixes it for the turn).

The context is now stored in the user turn it is sent with
(:func:`user_turn`), so history only ever grows. The cache marker still moves
to the newest message on every request (:func:`with_history_cache`); the API
ignores markers when it compares prefixes.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Dict, List


def turn_context(now: datetime, channel_status: str) -> str:
    """The volatile per-turn context: the turn's moment and the channel status."""
    return (
        "\n\n[CURRENT DATE/TIME — "
        f"{now.strftime('%A, %B %d, %Y')}, {now.strftime('%H:%M')}]"
        "\n\n"
        f"{channel_status}"
    )


def user_turn(text: str, context: str) -> Dict[str, Any]:
    """The user turn as stored and sent: the message, then its volatile context.

    An empty message keeps only the context: the API refuses an empty text block.
    """
    blocks = [{"type": "text", "text": text}] if text else []
    blocks.append({"type": "text", "text": context})
    return {"role": "user", "content": blocks}


def with_history_cache(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return a deep copy of ``messages`` with a cache_control marker on
    the last content block of the most recent message.

    Anthropic caches the entire prefix up to the marker, so on the next
    turn the whole history becomes a cache read. We never mutate
    ``self.conversation_history`` — the marker is added only on the wire
    representation, because history is serialized/restored elsewhere and
    stale cache_control markers would accumulate.

    The per-turn, minute-granular content (current time, notifications) is
    no longer appended here: it used to ride AFTER the breakpoint on the last
    message, on the wire only, which moved it on every request of a tool loop
    and so edited a message an earlier request had already sent. It is now
    stored in the user turn itself (:func:`user_turn`), inside the cached
    prefix, where it stays put.

    Anthropic allows at most 4 ephemeral breakpoints; the system prompt
    consumes 1, this adds 1, total = 2 — well within the limit.
    """
    if not messages:
        return messages
    out = copy.deepcopy(messages)
    last = out[-1]
    content = last.get("content")
    if isinstance(content, str):
        # Promote string content to a single text block so we can attach
        # cache_control on it. Anthropic accepts both shapes.
        last["content"] = [
            {
                "type": "text",
                "text": content,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        return out
    if isinstance(content, list) and content:
        # Attach cache_control to the last block — the stable prefix.
        last_block = content[-1]
        if isinstance(last_block, dict):
            last_block["cache_control"] = {"type": "ephemeral"}
    return out
