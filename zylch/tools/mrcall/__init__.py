"""MrCall assistant configuration tools.

This module enables natural language configuration of MrCall AI phone assistants.
It provides tools for modifying welcome messages and conversation handling.

Features:
- Two-level memory system: Admin (global) + Business (per-assistant)
- Preview + confirm workflow for all changes
- Variable preservation (%%VAR%%, {{VAR}}) during modifications
- Incremental updates from memory
"""

from .variable_utils import (
    extract_variables,
    validate_variable_preservation,
    create_variable_preservation_instructions,
    format_variable_changes,
)
from .llm_helper import modify_prompt_with_llm
from .config_tools import (
    GetAssistantCatalogTool,
    ConfigureAssistantTool,
    SaveMrCallAdminRuleTool,
    MRCALL_ADMIN_NAMESPACE,
    MRCALL_BUSINESS_PREFIX,
)

__all__ = [
    # Variable utilities
    "extract_variables",
    "validate_variable_preservation",
    "create_variable_preservation_instructions",
    "format_variable_changes",
    # LLM helper
    "modify_prompt_with_llm",
    # Tools
    "GetAssistantCatalogTool",
    "ConfigureAssistantTool",
    "SaveMrCallAdminRuleTool",
    # Constants
    "MRCALL_ADMIN_NAMESPACE",
    "MRCALL_BUSINESS_PREFIX",
]
