"""LLM helper functions for prompt modification.

Uses Claude to modify assistant prompts while preserving StarChat variables.
"""

import logging
import os
from typing import List, Optional, Tuple, Dict, Any

from anthropic import Anthropic

from .variable_utils import (
    extract_variables,
    validate_variable_preservation,
    create_variable_preservation_instructions,
    validate_no_placeholders,
)

logger = logging.getLogger(__name__)


async def modify_prompt_with_llm(
    current_prompt: str,
    user_request: str,
    admin_rules: Optional[List[str]] = None,
    similar_patterns: Optional[List[Dict[str, Any]]] = None,
    model: str = "claude-3-5-haiku-20241022",
    anthropic_api_key: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Modify a prompt using LLM while preserving variables.

    Args:
        current_prompt: Current prompt text
        user_request: User's modification request
        admin_rules: Optional list of admin rules to apply
        similar_patterns: Optional list of similar past modifications for context
        model: Anthropic model to use (default: claude-3-5-haiku-20241022)
        anthropic_api_key: API key (defaults to env var)

    Returns:
        Tuple of (modified_prompt, validation_result)
        validation_result includes:
            - all_preserved: bool
            - removed: list of removed variables
            - added: list of added variables
            - preserved: list of preserved variables
            - error: Optional error message if modification failed

    Raises:
        Exception: If LLM call fails
    """
    # Extract variables for protection
    variables_in_prompt = extract_variables(current_prompt)

    # Build variable preservation instructions
    variable_instructions = (
        create_variable_preservation_instructions(variables_in_prompt)
        if variables_in_prompt
        else ""
    )

    # Build admin rules section
    admin_section = ""
    if admin_rules:
        admin_section = f"""
ADMIN RULES (MUST be followed):
{chr(10).join(f"- {rule}" for rule in admin_rules)}
"""

    # Build similar patterns section
    patterns_section = ""
    if similar_patterns:
        patterns_section = """
SIMILAR PAST MODIFICATIONS (for reference, not mandatory):
"""
        for p in similar_patterns[:3]:  # Max 3 patterns
            patterns_section += f"- {p.get('context', 'N/A')}: {p.get('pattern', 'N/A')}\n"

    # Build modification prompt
    modification_prompt = f"""You are an expert at modifying AI assistant prompts.

USER REQUEST: {user_request}

CURRENT PROMPT:
{current_prompt}

{variable_instructions}
{admin_section}
{patterns_section}

Your task: Modify the CURRENT PROMPT to fulfill the USER REQUEST while preserving all instructions and variable references.

IMPORTANT:
- Keep all variable references intact (%%...%% and {{...}})
- Maintain the overall structure and logic
- Only change what's necessary to fulfill the user's request
- Follow ALL admin rules if provided
- Return ONLY the modified prompt, no explanations or comments
- Do NOT use placeholders like [...] or "..." - provide COMPLETE content

MODIFIED PROMPT:"""

    # Call LLM - BYOK only, no env var fallback
    if not anthropic_api_key:
        raise ValueError(
            "Anthropic API key required. "
            "Please run `/connect anthropic` to configure your API key."
        )
    client = Anthropic(api_key=anthropic_api_key)

    logger.info(f"Calling LLM to modify prompt (model: {model})")

    response = client.messages.create(
        model=model,
        max_tokens=4000,
        temperature=0.3,
        messages=[{"role": "user", "content": modification_prompt}]
    )

    modified_prompt = response.content[0].text.strip()

    # First, check for placeholders
    is_valid, placeholder_error = validate_no_placeholders(modified_prompt)
    if not is_valid:
        # Return error immediately - this is a critical failure
        validation = {
            "all_preserved": False,
            "removed": [],
            "added": [],
            "preserved": [],
            "count_original": len(variables_in_prompt),
            "count_modified": 0,
            "error": f"PLACEHOLDER_DETECTED: {placeholder_error}"
        }
        return modified_prompt, validation

    # Then validate variable preservation
    validation = validate_variable_preservation(current_prompt, modified_prompt)

    # Add error field if variables were removed
    if not validation["all_preserved"]:
        validation["error"] = f"Variables removed: {', '.join(validation['removed'])}"
    else:
        validation["error"] = None

    logger.info(f"Prompt modified successfully. Variables preserved: {validation['all_preserved']}")

    return modified_prompt, validation


def get_default_value(
    variable_name: str,
    variable_schema: Dict[str, Any],
    language: str = "it-IT"
) -> Optional[str]:
    """Get default value for a variable from schema.

    Args:
        variable_name: Variable name
        variable_schema: Variable schema from StarChat
        language: Language code for default value

    Returns:
        Default value or None if not found
    """
    if variable_name not in variable_schema:
        return None

    var_data = variable_schema[variable_name]

    # Try language-specific default first
    default_multilang = var_data.get("default_value_multilang", {})
    if language in default_multilang:
        return default_multilang[language]

    # Fall back to English
    if "en-US" in default_multilang:
        return default_multilang["en-US"]

    # Fall back to any default
    if default_multilang:
        return next(iter(default_multilang.values()))

    return None
