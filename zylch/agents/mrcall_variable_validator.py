"""Validate variable values against StarChat schema types before writing.

Prevents invalid values (e.g., malformed JSON for tuples-type variables)
from being written to StarChat and breaking the dashboard.
"""

import json
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def validate_variable_value(
    var_name: str,
    value: str,
    schema: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    """Validate a variable value against its schema type.

    Args:
        var_name: Variable name (e.g., KNOWLEDGE_BASE_ANSWER_INSTRUCTIONS)
        value: The string value to validate
        schema: Flattened schema dict from fetch_and_flatten_schema()

    Returns:
        (True, None) if valid, (False, "error message") if invalid.
        Error messages are descriptive enough for the LLM to self-correct.
    """
    var_schema = schema.get(var_name)
    if not var_schema:
        # Unknown variable — can't validate, let it through
        return True, None

    var_type = var_schema.get("type", "string").lower()

    try:
        if var_type == "tuples":
            return _validate_tuples(var_name, value)
        elif var_type in ("json", "object"):
            return _validate_json(var_name, value)
        elif var_type == "boolean":
            return _validate_boolean(var_name, value)
        elif var_type in ("number", "integer"):
            return _validate_number(var_name, value, var_type)
        else:
            # string, text, unknown — any value is valid
            return True, None
    except Exception as e:
        logger.error(f"[validator] Unexpected error validating {var_name}: {e}")
        return True, None  # Don't block on validator bugs


def _validate_tuples(var_name: str, value: str) -> Tuple[bool, Optional[str]]:
    """Validate tuples type: JSON array of 2-element string arrays."""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        return False, (
            f"{var_name} must be valid JSON. "
            f"Got JSON parse error: {e}. "
            f"Expected format: [[\"topic keywords\", \"answer instructions\"], ...]"
        )

    if not isinstance(parsed, list):
        return False, (
            f"{var_name} must be a JSON array of arrays. "
            f"Got {type(parsed).__name__} instead. "
            f"Expected format: [[\"topic\", \"answer\"], ...]"
        )

    for i, item in enumerate(parsed):
        if not isinstance(item, list):
            return False, (
                f"{var_name}[{i}] must be an array, got {type(item).__name__}. "
                f"Each element must be [\"topic\", \"answer\"]"
            )
        if len(item) != 2:
            return False, (
                f"{var_name}[{i}] must have exactly 2 elements, got {len(item)}. "
                f"Format: [\"topic keywords\", \"answer instructions\"]"
            )
        if not isinstance(item[0], str) or not isinstance(item[1], str):
            return False, (
                f"{var_name}[{i}] elements must be strings. "
                f"Got types: [{type(item[0]).__name__}, {type(item[1]).__name__}]"
            )
        if not item[0].strip() or not item[1].strip():
            return False, (
                f"{var_name}[{i}] has empty strings. "
                f"Both topic and answer must be non-empty."
            )

    return True, None


def _validate_json(var_name: str, value: str) -> Tuple[bool, Optional[str]]:
    """Validate json/object type: must be parseable JSON."""
    try:
        json.loads(value)
        return True, None
    except json.JSONDecodeError as e:
        return False, (
            f"{var_name} must be valid JSON. "
            f"Parse error: {e}"
        )


def _validate_boolean(var_name: str, value: str) -> Tuple[bool, Optional[str]]:
    """Validate boolean type: must be 'true' or 'false'."""
    if value.lower().strip() in ("true", "false"):
        return True, None
    return False, (
        f"{var_name} must be \"true\" or \"false\". "
        f"Got \"{value}\""
    )


def _validate_number(
    var_name: str, value: str, var_type: str
) -> Tuple[bool, Optional[str]]:
    """Validate number/integer type."""
    try:
        if var_type == "integer":
            int(value)
        else:
            float(value)
        return True, None
    except ValueError:
        return False, (
            f"{var_name} must be a valid {var_type}. "
            f"Got \"{value}\""
        )
