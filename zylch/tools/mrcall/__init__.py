"""MrCall assistant configuration tools.

This module enables natural language configuration of MrCall AI phone assistants.
It provides tools for modifying welcome messages and conversation handling.

Features:
- Dynamic sub-prompt generation via MrCallConfiguratorTrainer
- Preview + confirm workflow for all changes
- Variable preservation (%%VAR%%, {{VAR}}) during modifications
- Automatic sub-prompt regeneration after config changes
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
    VARIABLE_TO_FEATURE,
)
from .feature_context_tool import GetMrCallFeatureContextTool

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
    "GetMrCallFeatureContextTool",
    # Constants
    "VARIABLE_TO_FEATURE",
]
