"""Lossless text/function history conversion from Messages to Chat."""

import json
from copy import deepcopy

from .budget_pricing import BudgetError


def translate_messages(messages):
    result = []
    for message in messages:
        if not isinstance(message, dict) or set(message) != {"role", "content"}:
            raise BudgetError("Unsupported K3 message shape.")
        role, content = message["role"], message["content"]
        if role not in ("user", "assistant"):
            raise BudgetError("Unsupported K3 message role.")
        if isinstance(content, str):
            result.append(deepcopy(message))
            continue
        if not isinstance(content, list):
            raise BudgetError("Unsupported K3 content.")
        start_index = len(result)
        pending = []

        def flush(pending=pending, role=role):
            if pending:
                result.append({"role": role, "content": deepcopy(pending)})
                pending.clear()

        for block in content:
            if not isinstance(block, dict):
                raise BudgetError("Malformed K3 content block.")
            kind = block.get("type")
            if kind == "text" and set(block) == {"type", "text"} and isinstance(block["text"], str):
                pending.append(deepcopy(block))
            elif kind == "tool_use" and role == "assistant":
                if (
                    set(block) != {"type", "id", "name", "input"}
                    or not all(
                        isinstance(block.get(k), str) and block[k].strip() for k in ("id", "name")
                    )
                    or not isinstance(block.get("input"), dict)
                ):
                    raise BudgetError("Malformed K3 historical tool call.")
                # Consecutive calls share one assistant message. Text preceding
                # calls remains on that message; text following starts a new one.
                if (
                    pending
                    or len(result) == start_index
                    or result[-1].get("role") != "assistant"
                    or "tool_calls" not in result[-1]
                ):
                    result.append(
                        {
                            "role": "assistant",
                            "content": deepcopy(pending) or None,
                            "tool_calls": [],
                        }
                    )
                    pending.clear()
                result[-1]["tool_calls"].append(
                    {
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(
                                block["input"], ensure_ascii=False, allow_nan=False
                            ),
                        },
                    }
                )
            elif kind == "tool_result" and role == "user":
                if (
                    set(block) - {"type", "tool_use_id", "content", "is_error"}
                    or not isinstance(block.get("tool_use_id"), str)
                    or not block["tool_use_id"].strip()
                ):
                    raise BudgetError("Malformed K3 historical tool result.")
                if "is_error" in block and type(block["is_error"]) is not bool:
                    raise BudgetError("Invalid K3 tool-result error flag.")
                value = block.get("content", "")
                if not isinstance(value, str) and not (
                    isinstance(value, list)
                    and all(
                        isinstance(b, dict)
                        and set(b) == {"type", "text"}
                        and b.get("type") == "text"
                        and isinstance(b.get("text"), str)
                        for b in value
                    )
                ):
                    raise BudgetError("K3 tool results support text only.")
                if block.get("is_error"):
                    value = json.dumps(
                        {"is_error": True, "content": value}, ensure_ascii=False, allow_nan=False
                    )
                flush()
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": block["tool_use_id"],
                        "content": deepcopy(value),
                    }
                )
            else:
                raise BudgetError("Unsupported K3 history block.")
        flush()
        if not content:
            result.append({"role": role, "content": []})
    return result
