"""MrCall assistant configuration tools.

Provides tools for configuring MrCall AI phone assistants:
- get_assistant_catalog: Get available configuration variables
- configure_assistant: Modify variables with preview+confirm workflow
- save_mrcall_admin_rule: Save admin-level rules (explicit command only)

TODO: ConfigureAssistantTool and SaveMrCallAdminRuleTool are currently disabled in factory.py
# because they depend on the removed legacy memory system. They need to be migrated to use
# Supabase tables for admin rules and modification templates.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..base import Tool, ToolResult, ToolStatus
from ..factory import SessionState
from .llm_helper import modify_prompt_with_llm, get_default_value
from .variable_utils import format_variable_changes

logger = logging.getLogger(__name__)

# Namespace constants for memory
MRCALL_ADMIN_NAMESPACE = "mrcall:admin"
MRCALL_BUSINESS_PREFIX = "mrcall:"


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
        # Key variables for each category
        category_map = {
            "welcome": [
                "OSCAR_INBOUND_WELCOME_MESSAGE_PROMPT",
                "OSCAR_OUTBOUND_WELCOME_MESSAGE_PROMPT",
                "WELCOME_BIZ_OPENING",
                "OSCAR_INBOUND_TOGGLE_INITIAL_MESSAGE_WITH_PROMPT",
                "SET_SMART_GREETINGS",
                "SAY_CONVERSATION_NICKNAME",
            ],
            "conversation": [
                "OSCAR_INBOUND_BASE_INSTRUCTION_PROMPT",
                "OSCAR_INBOUND_CLOSING_PROMPT",
                "OSCAR_OUTBOUND_BASE_INSTRUCTION_PROMPT",
                "MAX_TURNS_BEFORE_FALLBACK",
                "ENABLE_CONVERSATION_SUMMARY",
            ],
        }

        modifiable = []
        read_only = []

        def process_variables(data: Any, parent_key: str = ""):
            """Recursively process nested schema."""
            if isinstance(data, dict):
                for key, value in data.items():
                    full_key = f"{parent_key}.{key}" if parent_key else key

                    # Check if this is a variable definition
                    if isinstance(value, dict) and "type" in value:
                        # Apply category filter
                        if filter_category != "all":
                            if full_key not in category_map.get(filter_category, []):
                                continue

                        var_info = {
                            "name": full_key,
                            "type": value.get("type"),
                            "description": value.get("description_multilang", {}).get("it-IT", ""),
                            "human_name": value.get("human_name_multilang", {}).get("it-IT", full_key),
                            "current_value": current_values.get(full_key),
                            "modifiable": value.get("modifiable", False) and value.get("advanced", False),
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
                        "description": "Filter variables by category",
                        "enum": ["welcome", "conversation", "all"],
                        "default": "all"
                    }
                },
                "required": []
            }
        }


class ConfigureAssistantTool(Tool):
    """Tool to configure MrCall assistant variables with preview+confirm workflow."""

    def __init__(
        self,
        starchat_client,
        session_state: SessionState,
        memory_system,
        anthropic_api_key: str
    ):
        super().__init__(
            name="configure_assistant",
            description=(
                "Configure MrCall assistant variables. ALWAYS does a dry-run first and shows "
                "a preview of changes. User must confirm before applying. "
                "Searches memory for similar past modifications to suggest as templates. "
                "Use variable_name from get_assistant_catalog output."
            )
        )
        self.starchat = starchat_client
        self.session_state = session_state
        self.memory = memory_system
        self.anthropic_api_key = anthropic_api_key

    async def execute(
        self,
        variable_name: str,
        request: str,
        confirm_apply: bool = False,
    ) -> ToolResult:
        """Configure an assistant variable.

        Args:
            variable_name: Variable to configure (e.g., OSCAR_INBOUND_WELCOME_MESSAGE_PROMPT)
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

            # Search memory for admin rules and similar patterns
            admin_rules = await self._get_admin_rules(variable_name)
            similar_patterns = await self._get_similar_patterns(business_id, request)

            # Check if this is a reset request
            if any(word in request.lower() for word in ["reset", "default", "ripristina", "originale"]):
                # Get default value
                schema = await self.starchat.get_variable_schema()
                new_value = get_default_value(variable_name, schema, "it-IT")
                if not new_value:
                    new_value = current_value
                validation = {"all_preserved": True, "removed": [], "added": [], "preserved": [], "error": None}
            else:
                # Use LLM to modify
                new_value, validation = await modify_prompt_with_llm(
                    current_prompt=current_value,
                    user_request=request,
                    admin_rules=admin_rules,
                    similar_patterns=similar_patterns,
                    anthropic_api_key=self.anthropic_api_key,
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
                "admin_rules_applied": admin_rules,
                "similar_patterns_found": [
                    {"context": p.get("context"), "confidence": p.get("confidence")}
                    for p in (similar_patterns or [])[:3]
                ],
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
                        f"ATTUALE:\n{current_value[:500]}{'...' if len(current_value) > 500 else ''}\n\n"
                        f"NUOVO:\n{new_value[:500]}{'...' if len(new_value) > 500 else ''}\n\n"
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

            # Store successful modification in memory
            await self._store_modification(business_id, variable_name, request, new_value)

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=preview,
                message=f"Configurazione applicata con successo per {variable_name}"
            )

        except Exception as e:
            logger.error(f"Failed to configure assistant: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

    async def _get_admin_rules(self, variable_name: str) -> List[str]:
        """Get admin rules from memory that apply to this variable."""
        if not self.memory:
            return []

        try:
            # Search admin namespace for rules
            memories = self.memory.retrieve_memories(
                query=f"rules for {variable_name}",
                namespace=MRCALL_ADMIN_NAMESPACE,
                category="rules",
                limit=5
            )

            rules = []
            for mem in memories:
                if mem.get("confidence", 0) >= 0.7:
                    rules.append(mem.get("pattern") or mem.get("context", ""))

            return rules
        except Exception as e:
            logger.warning(f"Could not retrieve admin rules: {e}")
            return []

    async def _get_similar_patterns(
        self,
        business_id: str,
        request: str
    ) -> List[Dict[str, Any]]:
        """Get similar past modifications from memory."""
        if not self.memory:
            return []

        try:
            # Search business-specific namespace
            namespace = f"{MRCALL_BUSINESS_PREFIX}{business_id}"
            memories = self.memory.retrieve_memories(
                query=request,
                namespace=namespace,
                category="modifications",
                limit=5
            )

            patterns = []
            for mem in memories:
                if mem.get("confidence", 0) >= 0.6:
                    patterns.append({
                        "context": mem.get("context"),
                        "pattern": mem.get("pattern"),
                        "confidence": mem.get("confidence"),
                        "variable_name": mem.get("metadata", {}).get("variable_name"),
                    })

            return patterns
        except Exception as e:
            logger.warning(f"Could not retrieve similar patterns: {e}")
            return []

    async def _store_modification(
        self,
        business_id: str,
        variable_name: str,
        request: str,
        new_value: str
    ) -> None:
        """Store successful modification in memory for future reference."""
        if not self.memory:
            return

        try:
            namespace = f"{MRCALL_BUSINESS_PREFIX}{business_id}"

            # Build context with metadata encoded in the string
            context_with_meta = (
                f"{request} | variable={variable_name} | "
                f"applied_at={datetime.now().isoformat()}"
            )

            # Use reconsolidation (force_new=False) to merge similar modifications
            self.memory.store_memory(
                namespace=namespace,
                category="modifications",
                context=context_with_meta,
                pattern=f"Modified {variable_name}: {request[:100]}",
                examples=[variable_name, new_value[:100]],
                confidence=0.8,
                force_new=False  # Enable reconsolidation
            )

            logger.info(f"Stored modification in memory: {namespace}")
        except Exception as e:
            logger.warning(f"Could not store modification in memory: {e}")

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "variable_name": {
                        "type": "string",
                        "description": "Variable to configure (e.g., OSCAR_INBOUND_WELCOME_MESSAGE_PROMPT)"
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


class SaveMrCallAdminRuleTool(Tool):
    """Tool to save admin-level rules for MrCall configuration.

    This tool requires explicit command invocation (/mrcall-admin) and
    admin role verification via StarChat.
    """

    def __init__(
        self,
        starchat_client,
        session_state: SessionState,
        memory_system
    ):
        super().__init__(
            name="save_mrcall_admin_rule",
            description=(
                "Save an admin-level rule that will be applied to all MrCall assistant configurations. "
                "Requires admin privileges (verified via StarChat). "
                "Use this to define global standards like 'Always use formal tone in German greetings'. "
                "This tool should ONLY be called when user explicitly uses /mrcall-admin command."
            )
        )
        self.starchat = starchat_client
        self.session_state = session_state
        self.memory = memory_system

    async def execute(
        self,
        rule: str,
        applies_to: str = "all",
    ) -> ToolResult:
        """Save an admin rule.

        Args:
            rule: The rule to save (e.g., "Always maintain formal tone in French")
            applies_to: Category this rule applies to ('welcome', 'conversation', 'all')
        """
        business_id = self.session_state.get_business_id()
        if not business_id:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="No MrCall assistant selected. Use /mrcall <id> to select one first."
            )

        # Check admin role via StarChat
        try:
            user_role = await self.starchat.check_user_role(business_id)
            if user_role not in ["admin", "owner"]:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=(
                        f"Permesso negato. Ruolo attuale: {user_role or 'unknown'}. "
                        "Solo gli admin possono salvare regole globali."
                    )
                )
        except Exception as e:
            logger.warning(f"Could not verify admin role: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Impossibile verificare i permessi admin: {e}"
            )

        # Store in admin namespace
        if not self.memory:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="Memory system not available"
            )

        try:
            # Build context with metadata encoded
            context_with_meta = (
                f"Admin rule for {applies_to} | "
                f"created_by={business_id} | "
                f"created_at={datetime.now().isoformat()}"
            )

            self.memory.store_memory(
                namespace=MRCALL_ADMIN_NAMESPACE,
                category="rules",
                context=context_with_meta,
                pattern=rule,
                examples=[applies_to],
                confidence=1.0,  # Admin rules have max confidence
                force_new=True  # Admin rules are always new, no reconsolidation
            )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "rule": rule,
                    "applies_to": applies_to,
                    "namespace": MRCALL_ADMIN_NAMESPACE,
                },
                message=(
                    f"Regola admin salvata: '{rule}'\n"
                    f"Si applica a: {applies_to}\n"
                    "Sara' applicata a tutte le future configurazioni di assistenti."
                )
            )

        except Exception as e:
            logger.error(f"Failed to save admin rule: {e}")
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
                    "rule": {
                        "type": "string",
                        "description": "The admin rule to save"
                    },
                    "applies_to": {
                        "type": "string",
                        "description": "Category this rule applies to",
                        "enum": ["welcome", "conversation", "all"],
                        "default": "all"
                    }
                },
                "required": ["rule"]
            }
        }
