"""Reject incomplete model responses before committing memory or checkpoints."""

import json


class MemoryResponseError(RuntimeError):
    """The provider did not return a complete textual memory decision."""


def complete_memory_text(response) -> str:
    """Accept only a finished text answer, never a truncated prefix or tool call.

    These extraction/merge requests do not supply tools or stop sequences.
    Their expected Anthropic-shaped completion is therefore ``end_turn``.
    A valid-looking identity prefix is insufficient when generation was cut off.
    """
    if getattr(response, "stop_reason", None) != "end_turn":
        raise MemoryResponseError("Memory response did not finish normally")
    blocks = getattr(response, "content", None)
    if not isinstance(blocks, (list, tuple)) or not blocks:
        raise MemoryResponseError("Memory response has no text content")
    text = []
    for block in blocks:
        if getattr(block, "type", None) != "text" or not isinstance(
            getattr(block, "text", None), str
        ):
            raise MemoryResponseError("Memory response contains unexpected non-text content")
        text.append(block.text)
    result = "\n".join(text).strip()
    if not result:
        raise MemoryResponseError("Memory response text is empty")
    return result


def strict_json_object(text: str) -> dict:
    """Exactly one JSON object and nothing else.

    A decision envelope is not prose with some JSON in it. The three shapes
    refused here are the ones that actually arrive:

    - a promise followed by a cut-off object ("I will update it now. {...") —
      the model narrated instead of answering, and the object is incomplete;
    - a complete object followed by trailing commentary, where the commentary
      may contradict the object a reader would act on;
    - an empty object, which carries no decision at all but parses cleanly and
      would otherwise sail through as a well-formed answer.

    A single ```json fence is tolerated — it is a formatting habit, not a
    second answer — and nothing else is.
    """
    body = (text or "").strip()
    if body.startswith("```"):
        newline = body.find("\n")
        closing = body.rfind("```")
        if newline == -1 or closing <= newline:
            raise MemoryResponseError("Memory decision has an unterminated code fence")
        if body[closing + 3 :].strip():
            raise MemoryResponseError(
                "Memory decision carries trailing content after the JSON object"
            )
        body = body[newline + 1 : closing].strip()
    if not body:
        raise MemoryResponseError("Memory decision is empty")
    if not body.startswith("{"):
        raise MemoryResponseError("Memory decision is not a JSON object")
    try:
        parsed, end = json.JSONDecoder().raw_decode(body)
    except ValueError as exc:
        raise MemoryResponseError(f"Memory decision is not valid JSON: {exc}") from None
    if body[end:].strip():
        raise MemoryResponseError("Memory decision carries trailing content after the JSON object")
    if not isinstance(parsed, dict):
        raise MemoryResponseError("Memory decision must be a JSON object")
    if not parsed:
        raise MemoryResponseError("Memory decision object is empty")
    return parsed
