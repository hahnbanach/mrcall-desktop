"""Utilities for StarChat variable handling.

StarChat uses two variable placeholder formats:
1. %%variable.path=default%% - Variable with default value
2. {{variable.path}} - Variable without default

These variables are replaced at runtime during conversation.
"""

import re
from typing import List, Dict, Any


def extract_variables(text: str) -> List[str]:
    """Extract all variable placeholders from text.

    Matches:
    - %%...%% format (with optional =default)
    - {{...}} format

    Args:
        text: Text containing variable placeholders

    Returns:
        List of variable placeholders found (preserves exact format)

    Examples:
        >>> extract_variables("Hi %%name=Guest%%!")
        ['%%name=Guest%%']
        >>> extract_variables("Time is {{public.HUMANIZED_TIME}}")
        ['{{public.HUMANIZED_TIME}}']
    """
    if not text:
        return []

    # Match %%anything%% (non-greedy)
    pattern1 = r'%%[^%]+%%'
    # Match {{anything}} (non-greedy)
    pattern2 = r'{{[^}]+}}'

    vars1 = re.findall(pattern1, text)
    vars2 = re.findall(pattern2, text)

    return vars1 + vars2


def validate_variable_preservation(
    original: str,
    modified: str
) -> Dict[str, Any]:
    """Check if variables were preserved during text modification.

    Compares variable placeholders before and after modification to detect:
    - Removed variables (present in original, missing in modified)
    - Added variables (not in original, present in modified)
    - Preserved variables (present in both)

    Args:
        original: Original text with variables
        modified: Modified text (potentially with changes)

    Returns:
        Dictionary with:
            - removed: List of variables removed
            - added: List of variables added
            - preserved: List of variables kept
            - all_preserved: Boolean indicating if all original variables remain
            - count_original: Count of variables in original
            - count_modified: Count of variables in modified
    """
    original_vars = set(extract_variables(original))
    modified_vars = set(extract_variables(modified))

    removed = original_vars - modified_vars
    added = modified_vars - original_vars
    preserved = original_vars & modified_vars

    return {
        "removed": sorted(list(removed)),
        "added": sorted(list(added)),
        "preserved": sorted(list(preserved)),
        "all_preserved": len(removed) == 0,
        "count_original": len(original_vars),
        "count_modified": len(modified_vars)
    }


def create_variable_preservation_instructions(variables: List[str]) -> str:
    """Create instructions for LLM to preserve variables during modification.

    Args:
        variables: List of variable placeholders to preserve

    Returns:
        Instructions text to include in LLM prompt
    """
    if not variables:
        return ""

    instructions = f"""
CRITICAL: VARIABLE PRESERVATION REQUIRED

This prompt contains {len(variables)} VARIABLE PLACEHOLDER(S) that are replaced at runtime.

Variables in this prompt:
{chr(10).join(f"  - {var}" for var in variables)}

STRICT RULES:
1. You MUST preserve ALL variable placeholders EXACTLY as written
2. DO NOT remove, modify, rename, or rewrite any variables
3. DO NOT replace variables with example values or text
4. You CAN add new text before, after, or around variables
5. You CAN move variables to different positions in the text
6. You CAN change the text structure, but keep variables intact

Variable formats used in StarChat:
- %%variable.path=default%%  (variable with default value)
- {{variable.path}}          (variable without default)

Example of CORRECT modification:
  Before: "Ciao! Il tuo nome e' %%FIRST_NAME=unknown%%."
  After:  "Buongiorno %%FIRST_NAME=unknown%%!" (variable preserved)

Example of INCORRECT modification:
  Before: "Ciao! Il tuo nome e' %%FIRST_NAME=unknown%%."
  After:  "Buongiorno Mario!" (variable removed - WRONG!)

If the user's request would require removing a variable, keep the variable and explain
in your response why it should remain.
"""
    return instructions.strip()


def format_variable_changes(validation: Dict[str, Any], show_colors: bool = True) -> str:
    """Format variable validation results as human-readable text.

    Args:
        validation: Output from validate_variable_preservation()
        show_colors: Whether to use ANSI colors (for terminal)

    Returns:
        Formatted string describing the changes
    """
    lines = []

    # Colors
    GREEN = '\033[92m' if show_colors else ''
    RED = '\033[91m' if show_colors else ''
    YELLOW = '\033[93m' if show_colors else ''
    RESET = '\033[0m' if show_colors else ''

    if validation["all_preserved"]:
        lines.append(f"{GREEN}All {validation['count_original']} variables preserved{RESET}")
    else:
        lines.append(f"{RED}Variable changes detected{RESET}")

    if validation["removed"]:
        lines.append(f"\n{RED}{len(validation['removed'])} variable(s) will be REMOVED:{RESET}")
        for var in validation["removed"]:
            lines.append(f"   - {var}")

    if validation["added"]:
        lines.append(f"\n{YELLOW}{len(validation['added'])} new variable(s) added:{RESET}")
        for var in validation["added"]:
            lines.append(f"   - {var}")

    if validation["preserved"] and not validation["all_preserved"]:
        lines.append(f"\n{GREEN}{len(validation['preserved'])} variable(s) preserved:{RESET}")
        for var in validation["preserved"]:
            lines.append(f"   - {var}")

    return "\n".join(lines)


def validate_no_placeholders(text: str) -> tuple:
    """Check if text contains placeholder comments that should not be there.

    Args:
        text: Text to validate

    Returns:
        Tuple of (is_valid, error_message)
        is_valid=True means no placeholders found
        is_valid=False means placeholders found, error_message explains what
    """
    # Patterns that indicate incomplete/placeholder content
    placeholder_patterns = [
        (r'\[.*?resto.*?\]', "placeholder comment with 'resto'"),
        (r'\[.*?rest.*?\]', "placeholder comment with 'rest'"),
        (r'\[.*?previous.*?\]', "placeholder comment with 'previous'"),
        (r'\[.*?invariato.*?\]', "placeholder comment with 'invariato'"),
        (r'\[.*?unchanged.*?\]', "placeholder comment with 'unchanged'"),
        (r'\[.*?keep.*?\]', "placeholder comment with 'keep'"),
        (r'\[.*?existing.*?\]', "placeholder comment with 'existing'"),
        (r'\[.*?same.*?\]', "placeholder comment with 'same'"),
        (r'\.{3,}', "ellipsis (...)"),
        (r'\[\.\.\.\]', "ellipsis in brackets [...]"),
    ]

    for pattern, description in placeholder_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            return False, f"Found {description}: '{match.group()}' - You MUST provide complete content, not placeholders!"

    return True, None
