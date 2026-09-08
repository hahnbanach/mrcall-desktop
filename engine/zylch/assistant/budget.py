"""Bounds on what one chat turn feeds the model.

Two bounds, both taken from a measured incident
(`~/hb/docs/known-issues/2026-09-08-engine-chat-prompt-unbounded.md`):

- a formatted tool result is cut to `TOOL_RESULT_MAX_CHARS`, with a marker
  the model reads that names the tool, the original size and what to do
  instead;
- the assembled prompt is estimated before every dispatch and refused
  above `PROMPT_TOKEN_BUDGET`, so a request already known to exceed the
  window is never sent.

The estimator is calibrated on that incident, not on prose. The rejected
request carried 1,368,597 characters of JSON tool results and was counted
upstream at 485,835 tokens: 2.9 characters per token. Dense JSON tokenises
tighter than English, so the 4-characters-per-token rule that sizes
history compaction under-counts it by a quarter; this module uses 3.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from zylch.llm.exceptions import LLMPromptTooLargeError

# Characters per token for JSON-heavy prompts (measured: 2.9).
CHARS_PER_TOKEN = 3

# Estimated tokens above which a prompt is refused. The production route
# has a 200,000-token window; the margin absorbs estimator error and the
# response.
PROMPT_TOKEN_BUDGET = 150_000

# Characters one formatted tool result may occupy in the conversation —
# about 27,000 estimated tokens. Two results in one step stay well under
# the budget next to the system prompt and the tool schemas (about 15,000
# tokens together).
TOOL_RESULT_MAX_CHARS = 80_000


def _chars(part: Any) -> int:
    if part is None:
        return 0
    if isinstance(part, str):
        return len(part)
    try:
        return len(json.dumps(part, default=str))
    except Exception:
        return len(str(part))


def estimate_tokens(*parts: Any) -> int:
    """Estimated token count of `parts`: strings, or anything JSON-shaped."""
    return sum(_chars(p) for p in parts) // CHARS_PER_TOKEN


def check_prompt_budget(
    *,
    system: Any,
    tools: Any,
    messages: Any,
    budget: int = PROMPT_TOKEN_BUDGET,
) -> int:
    """Return the prompt's estimated tokens, or raise if it exceeds `budget`."""
    estimated = estimate_tokens(system, tools, messages)
    if estimated > budget:
        raise LLMPromptTooLargeError(estimated, budget)
    return estimated


def bound_tool_result(
    tool_name: str,
    formatted: str,
    max_chars: int = TOOL_RESULT_MAX_CHARS,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Cut `formatted` to `max_chars` with a marker, and report the cut.

    Returns the text to hand the model and, when it was cut, a record
    `{tool, original_chars, shown_chars}` for the turn's metadata. Within
    budget the text comes back untouched and the record is None. This is
    the one place a tool result is shortened, and it always says so.
    """
    original = len(formatted)
    if original <= max_chars:
        return formatted, None
    shown = formatted[:max_chars]
    marker = (
        f"\n\n[TOOL RESULT TRUNCATED: {tool_name} returned {original:,} characters;"
        f" the first {max_chars:,} are shown. Narrow the query (a more specific"
        " predicate, a smaller limit, a date range) and call again."
        " Do not call update_memory or create_memory from a partial result.]"
    )
    return shown + marker, {
        "tool": tool_name,
        "original_chars": original,
        "shown_chars": max_chars,
    }
