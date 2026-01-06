"""LLM helper functions for prompt modification.

Uses LLM to modify assistant prompts while preserving StarChat variables.
"""

import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any

from zylch.llm import LLMClient, PROVIDER_MODELS

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
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    provider: str = "anthropic",
) -> Tuple[str, Dict[str, Any]]:
    """Modify a prompt using LLM while preserving variables.

    Args:
        current_prompt: Current prompt text
        user_request: User's modification request
        admin_rules: Optional list of admin rules to apply
        similar_patterns: Optional list of similar past modifications for context
        model: LLM model to use (defaults to provider's default model)
        api_key: LLM API key
        provider: LLM provider (anthropic, openai, mistral)

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
    if not api_key:
        raise ValueError(
            "LLM API key required. "
            "Please run `/connect <provider>` to configure your API key."
        )

    # Use provider's default model if not specified
    if not model:
        model = PROVIDER_MODELS.get(provider, PROVIDER_MODELS["anthropic"])

    client = LLMClient(api_key=api_key, provider=provider)

    logger.info(f"Calling LLM to modify prompt (provider: {provider}, model: {model})")

    response = await client.create_message(
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


# --- Multi-variable support with function calling ---


@dataclass
class VariableUpdateResult:
    """Result from LLM variable modification with function calling."""
    new_values: Dict[str, str]  # var_name -> new_value
    behavior_summary: str       # Human-readable summary for user feedback


def build_update_variables_tool(variable_names: List[str]) -> dict:
    """Build dynamic tool schema based on feature's variables.

    Creates a tool definition that forces the LLM to return structured
    output with all variable values and a behavior summary.

    Args:
        variable_names: List of variable names that need new values

    Returns:
        Tool definition dict in Anthropic format (auto-converted for other providers)
    """
    properties = {
        # Summary of new behavior for user feedback
        "behavior_summary": {
            "type": "string",
            "description": (
                "Human-readable summary of the new assistant behavior after these changes "
                "(1-2 sentences, e.g., 'Now the assistant will use formal tone and won't ask for the caller's name')"
            )
        }
    }

    for var_name in variable_names:
        properties[var_name] = {
            "type": "string",
            "description": f"Complete new value for {var_name}. Must preserve all %%...%% variable references."
        }

    return {
        "name": "update_variables",
        "description": "Update MrCall configuration variables with new values based on user instructions",
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": ["behavior_summary"] + variable_names
        }
    }


async def modify_variables_with_llm(
    current_values: Dict[str, str],
    context: str,
    instructions: str,
    api_key: str,
    provider: str = "anthropic",
    model: Optional[str] = None,
) -> VariableUpdateResult:
    """Use LLM with function calling to modify multiple variables.

    This function uses forced tool use to ensure structured output,
    avoiding parsing issues with free-form LLM responses.

    Args:
        current_values: Dict of variable_name -> current_value
        context: Feature configuration context (sub-prompt)
        instructions: User's modification instructions
        api_key: LLM API key
        provider: LLM provider (anthropic, openai, mistral)
        model: Optional model override

    Returns:
        VariableUpdateResult with new_values dict and behavior_summary

    Raises:
        ValueError: If LLM doesn't return expected tool call
    """
    # Build tool with dynamic schema based on variables
    variable_names = list(current_values.keys())
    tool = build_update_variables_tool(variable_names)

    # Format current values for prompt
    current_values_text = "\n\n".join(
        f"### {name}\n```\n{value}\n```"
        for name, value in current_values.items()
    )

    prompt = f"""You are modifying a MrCall AI phone assistant configuration.

## CONFIGURATION CONTEXT
{context}

## CURRENT VALUES
{current_values_text}

## USER INSTRUCTIONS
{instructions}

## CRITICAL RULES
1. Preserve ALL %%...%% variable references exactly as they appear
2. Preserve the --- separator between variable declarations and behavioral instructions
3. Apply the user's requested changes to the behavioral part
4. Provide a clear behavior_summary explaining what changed

Generate the updated values for ALL variables using the update_variables tool."""

    # Use provider's default model if not specified
    if not model:
        model = PROVIDER_MODELS.get(provider, PROVIDER_MODELS["anthropic"])

    client = LLMClient(api_key=api_key, provider=provider)

    logger.info(f"Calling LLM with function calling to modify {len(variable_names)} variable(s)")

    # Force tool use - LLM must call update_variables
    response = await client.create_message(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        tools=[tool],
        tool_choice={"type": "tool", "name": "update_variables"},
        max_tokens=8000,
        temperature=0.3
    )

    # Extract tool result from response
    for block in response.content:
        if block.type == "tool_use" and block.name == "update_variables":
            result = dict(block.input)  # Make a copy to avoid mutation
            behavior_summary = result.pop("behavior_summary", "Configuration updated.")

            # Remaining keys are variable names -> new values
            new_values = result

            logger.info(f"LLM returned {len(new_values)} variable update(s): {behavior_summary}")

            return VariableUpdateResult(
                new_values=new_values,
                behavior_summary=behavior_summary
            )

    # Should never reach here with forced tool use, but handle it
    raise ValueError("LLM did not return the expected update_variables tool call")
