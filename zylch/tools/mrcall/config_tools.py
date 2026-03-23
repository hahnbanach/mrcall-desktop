"""MrCall assistant configuration tools.

Provides tools for configuring MrCall AI phone assistants:
- get_assistant_catalog: Get available configuration variables
- configure_assistant: Modify variables with preview+confirm workflow

The ConfigureAssistantTool now uses MrCallConfiguratorTrainer for sub-prompt
regeneration after config changes, replacing the legacy memory system.
"""

import logging
from typing import Any, Dict, List, Optional

from ..base import Tool, ToolResult, ToolStatus
from ..factory import SessionState
from .llm_helper import modify_prompt_with_llm, get_default_value
from .variable_utils import format_variable_changes
from zylch.agents.trainers import MrCallConfiguratorTrainer

logger = logging.getLogger(__name__)

# Derive from single source of truth (MrCallConfiguratorTrainer.FEATURES)
# This is the inverse mapping: variable_name -> feature_name

VARIABLE_TO_FEATURE = {
    var: feature_name
    for feature_name, feature in MrCallConfiguratorTrainer.FEATURES.items()
    for var in feature["variables"]
}


class GetAssistantCatalogTool(Tool):
    """Tool to get available configuration variables for MrCall assistant."""

    def __init__(self, starchat_client, session_state: SessionState):
        super().__init__(
            name="get_assistant_catalog",
            description=(
                "Get the catalog of configurable variables for the current MrCall assistant. "
                "Shows variable names, descriptions, current values, and which ones are modifiable. "
                "Use filter_category to focus on specific types: 'welcome' for greeting messages, "
                "'conversation' for conversation flow settings, or 'all' for everything."
            )
        )
        self.starchat = starchat_client
        self.session_state = session_state

    async def execute(
        self,
        filter_category: str = "all",
    ) -> ToolResult:
        """Get catalog of configurable variables.

        Args:
            filter_category: Filter by category ('welcome', 'conversation', 'all')
        """
        business_id = self.session_state.get_business_id()
        if not business_id:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="No MrCall assistant selected. Use /mrcall <id> to select one."
            )

        try:
            # Get variable schema
            schema = await self.starchat.get_variable_schema(
                template_name="private",
                language="it-IT",
                nested=True
            )

            # Get current business values
            business = await self.starchat.get_business_config(business_id)
            if not business:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=f"Business not found: {business_id}"
                )

            current_values = business.get("variables", {})

            # Filter and build catalog
            catalog = self._build_catalog(schema, current_values, filter_category)

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=catalog,
                message=f"Found {len(catalog['modifiable'])} modifiable variables for category: {filter_category}"
            )

        except Exception as e:
            logger.error(f"Failed to get catalog: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

    def _build_catalog(
        self,
        schema: Dict[str, Any],
        current_values: Dict[str, str],
        filter_category: str
    ) -> Dict[str, Any]:
        """Build catalog from schema and current values."""
        modifiable = []
        read_only = []

        def process_variables(data: Any, parent_key: str = ""):
            """Recursively process nested schema."""
            if isinstance(data, dict):
                for key, value in data.items():
                    full_key = f"{parent_key}.{key}" if parent_key else key

                    # Check if this is a variable definition
                    if isinstance(value, dict) and "type" in value:
                        # Apply category filter using VARIABLE_TO_FEATURE
                        # (derived from MrCallConfiguratorTrainer.FEATURES)
                        if filter_category != "all":
                            if VARIABLE_TO_FEATURE.get(full_key) != filter_category:
                                continue

                        var_info = {
                            "name": full_key,
                            "type": value.get("type"),
                            "description": value.get("description_multilang", {}).get("it-IT", ""),
                            "human_name": value.get("human_name_multilang", {}).get("it-IT", full_key),
                            "current_value": current_values.get(full_key),
                            "modifiable": value.get("modifiable", False),
                        }

                        if var_info["modifiable"]:
                            modifiable.append(var_info)
                        else:
                            read_only.append(var_info)
                    else:
                        # Recurse into nested structure
                        process_variables(value, full_key)

        process_variables(schema)

        return {
            "modifiable": modifiable,
            "read_only": read_only,
            "filter_applied": filter_category,
            "business_id": self.session_state.get_business_id(),
        }

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "filter_category": {
                        "type": "string",
                        "description": "Filter variables by feature category",
                        "enum": ["all"] + list(MrCallConfiguratorTrainer.FEATURES.keys()),
                        "default": "all"
                    }
                },
                "required": []
            }
        }


class ConfigureAssistantTool(Tool):
    """Tool to configure MrCall assistant variables with preview+confirm workflow.

    After a successful configuration change, automatically regenerates the
    sub-prompt for the affected feature using MrCallConfiguratorTrainer.
    """

    def __init__(
        self,
        starchat_client,
        session_state: SessionState,
        trainer: "MrCallConfiguratorTrainer",
        api_key: str,
        provider: str,
    ):
        super().__init__(
            name="configure_assistant",
            description=(
                "Configure MrCall assistant variables. ALWAYS does a dry-run first and shows "
                "a preview of changes. User must confirm before applying. "
                "After applying changes, regenerates the feature context to reflect new behavior. "
                "Use variable_name from get_assistant_catalog output."
            )
        )
        self.starchat = starchat_client
        self.session_state = session_state
        self.trainer = trainer
        self.api_key = api_key
        self.provider = provider

    async def execute(
        self,
        variable_name: str,
        request: str,
        confirm_apply: bool = False,
    ) -> ToolResult:
        """Configure an assistant variable.

        Args:
            variable_name: Variable to configure (e.g., INBOUND_WELCOME_MESSAGE_PROMPT)
            request: Natural language description of desired change
            confirm_apply: Set to true to apply after preview. Default false (dry-run).
        """
        business_id = self.session_state.get_business_id()
        if not business_id:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="No MrCall assistant selected. Use /mrcall <id> to select one."
            )

        try:
            # Get current value
            business = await self.starchat.get_business_config(business_id)
            if not business:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=f"Business not found: {business_id}"
                )

            current_values = business.get("variables", {})
            current_value = current_values.get(variable_name)

            if current_value is None:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=f"Variable not found: {variable_name}. Use get_assistant_catalog to see available variables."
                )

            # Check if this is a reset request
            if any(word in request.lower() for word in ["reset", "default", "ripristina", "originale"]):
                # Get default value
                schema = await self.starchat.get_variable_schema()
                new_value = get_default_value(variable_name, schema, "it-IT")
                if not new_value:
                    new_value = current_value
                validation = {"all_preserved": True, "removed": [], "added": [], "preserved": [], "error": None}
            else:
                # Use LLM to modify (no admin rules or patterns for now)
                new_value, validation = await modify_prompt_with_llm(
                    current_prompt=current_value,
                    user_request=request,
                    admin_rules=[],
                    similar_patterns=[],
                    api_key=self.api_key,
                    provider=self.provider,
                )

            # Check for critical errors
            if validation.get("error") and "PLACEHOLDER_DETECTED" in str(validation.get("error", "")):
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=f"Modification failed: {validation['error']}"
                )

            # Build preview
            preview = {
                "dry_run": not confirm_apply,
                "variable": variable_name,
                "current_value": current_value,
                "new_value": new_value,
                "old_length": len(current_value),
                "new_length": len(new_value),
                "variable_validation": validation,
            }

            # If not confirming, return preview
            if not confirm_apply:
                # Format for user-friendly display
                validation_text = format_variable_changes(validation, show_colors=False)

                return ToolResult(
                    status=ToolStatus.PENDING_APPROVAL,
                    data=preview,
                    message=(
                        f"PREVIEW (non ancora applicato):\n\n"
                        f"VARIABILE: {variable_name}\n\n"
                        f"ATTUALE:\n{current_value}\n\n"
                        f"NUOVO:\n{new_value}\n\n"
                        f"VALIDAZIONE VARIABILI:\n{validation_text}\n\n"
                        f"Per applicare, chiama di nuovo con confirm_apply=true"
                    )
                )

            # Confirm apply - check variable preservation first
            if not validation["all_preserved"]:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=preview,
                    error=(
                        f"ATTENZIONE: Variabili rimosse: {', '.join(validation['removed'])}. "
                        "Non posso applicare modifiche che rimuovono variabili. "
                        "Modifica la richiesta per preservare tutte le variabili."
                    )
                )

            # Apply to StarChat
            await self.starchat.update_business_variable(
                business_id=business_id,
                variable_name=variable_name,
                value=new_value
            )

            # Regenerate sub-prompt to reflect new configuration
            feature_name = VARIABLE_TO_FEATURE.get(variable_name)
            new_behavior_description = None

            if feature_name and self.trainer:
                try:
                    logger.info(
                        f"Regenerating sub-prompt for {feature_name} "
                        f"after config change"
                    )
                    new_sub_prompt, _ = await self.trainer.train_feature(
                        feature_name, business_id
                    )
                    # Extract the CURRENT BEHAVIOR section for the response
                    # This gives the user immediate feedback on what changed
                    if "### CURRENT BEHAVIOR" in new_sub_prompt:
                        behavior_start = new_sub_prompt.find("### CURRENT BEHAVIOR")
                        behavior_end = new_sub_prompt.find("###", behavior_start + 20)
                        if behavior_end == -1:
                            behavior_end = new_sub_prompt.find("### WHAT CAN BE CHANGED")
                        if behavior_end > behavior_start:
                            new_behavior_description = new_sub_prompt[
                                behavior_start:behavior_end
                            ].strip()

                    # NOTE: We intentionally do NOT update the training snapshot here.
                    # The snapshot stays frozen from the last full training run, so the
                    # training status endpoint will correctly detect this variable change
                    # as "stale" and prompt the user to retrain.
                    logger.debug(
                        f"[ConfigureAssistantTool] Sub-prompt regenerated for {feature_name} "
                        f"(var: {variable_name}). Snapshot NOT updated — status will show stale."
                    )

                except Exception as e:
                    logger.warning(f"Failed to regenerate sub-prompt: {e}")

            # Build success message with new behavior description
            success_message = f"Configurazione applicata con successo per {variable_name}"
            if new_behavior_description:
                success_message += f"\n\n{new_behavior_description}"

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=preview,
                message=success_message
            )

        except Exception as e:
            logger.error(f"Failed to configure assistant: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "variable_name": {
                        "type": "string",
                        "description": "Variable to configure (e.g., INBOUND_WELCOME_MESSAGE_PROMPT)"
                    },
                    "request": {
                        "type": "string",
                        "description": "Natural language description of desired change"
                    },
                    "confirm_apply": {
                        "type": "boolean",
                        "description": "Set to true to apply after preview. Default false (dry-run).",
                        "default": False
                    }
                },
                "required": ["variable_name", "request"]
            }
        }


# NOTE: SaveMrCallAdminRuleTool has been removed as it depended on the legacy
# memory system. Admin rules functionality may be re-implemented in the future
# using Supabase tables if needed.
