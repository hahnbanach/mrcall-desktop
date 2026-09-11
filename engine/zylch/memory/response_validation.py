"""Reject incomplete model responses before committing memory or checkpoints."""


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
