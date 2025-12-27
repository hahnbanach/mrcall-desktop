"""Triggered Instructions tools for event-driven automation.

These tools allow users to create triggered instructions that execute automatically
when specific events occur. For example:
- "All'inizio di ogni sessione devi dirmi 'Buongiorno Mario...'" (session_start trigger)
- "When a new email arrives from someone I don't know, create a contact" (email_received trigger)
- "When a prospect replies, invite them to call the demo number" (email_received trigger)

TODO: These tools are currently disabled in factory.py because they depend on the removed
zylch_memory system. They need to be migrated to use the Supabase `triggers` table instead.
The table schema already exists (see ARCHITECTURE.md).

NOTE: This file is kept for future use - do not delete. Just needs migration from
zylch_memory.store_memory()/retrieve_memories() to Supabase triggers table CRUD.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

from .base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)


class AddTriggeredInstructionTool(Tool):
    """Add a triggered instruction that executes automatically on specific events."""

    def __init__(self, zylch_memory, owner_id: str, zylch_assistant_id: str):
        super().__init__(
            name="add_triggered_instruction",
            description="Add a triggered instruction that executes automatically when specific events occur"
        )
        self.zylch_memory = zylch_memory
        self.owner_id = owner_id
        self.zylch_assistant_id = zylch_assistant_id

    def _get_namespace(self) -> str:
        """Get the triggers namespace for this user."""
        return f"{self.owner_id}:{self.zylch_assistant_id}:triggers"

    async def execute(
        self,
        validation_only: bool = False,
        instruction: str = "",
        trigger: str = "",
        name: Optional[str] = None
    ) -> ToolResult:
        """Save a triggered instruction.

        Args:
            validation_only: If True, return preview without saving
            instruction: The instruction text (what Zylch should do)
            trigger: REQUIRED trigger type (session_start, email_received, sms_received, call_received)
            name: Optional short name for the trigger

        Returns:
            ToolResult with trigger ID
        """
        try:
            # Validate required parameters
            if not instruction or not trigger:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error="Missing required parameters: instruction and trigger are required"
                )

            trigger_id = f"trigger_{uuid.uuid4().hex[:8]}"
            created_at = datetime.utcnow().isoformat()

            # Build trigger data (preview)
            trigger_data = {
                "id": trigger_id,
                "instruction": instruction,
                "trigger": trigger,
                "name": name or instruction[:50],
                "created_at": created_at,
                "active": True,
                "namespace": self._get_namespace(),
                "will_execute_on": self._get_trigger_description(trigger),
                "example_scenario": self._get_example_scenario(trigger)
            }

            # VALIDATION MODE: Return preview without saving
            if validation_only:
                logger.info(f"PREVIEW: Would create triggered instruction {trigger_id} (trigger={trigger})")
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data=trigger_data,
                    message=(
                        f"PREVIEW: This would add a triggered instruction.\n"
                        f"Event: {trigger_data['will_execute_on']}\n"
                        f"Example: {trigger_data['example_scenario']}\n"
                        f"Instruction: {instruction}"
                    )
                )

            # EXECUTION MODE: Actually save to memory
            namespace = self._get_namespace()

            memory_id = self.zylch_memory.store_memory(
                namespace=namespace,
                category="trigger",
                context=f"Triggered instruction ({trigger}): {name or instruction[:50]}",
                pattern=json.dumps(trigger_data),
                examples=[]
            )

            logger.info(f"Saved triggered instruction: {trigger_id} (trigger={trigger})")

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "trigger_id": trigger_id,
                    "memory_id": str(memory_id),
                    "instruction": instruction,
                    "trigger": trigger
                },
                message=f"Triggered instruction saved. Will execute on {trigger} events."
            )

        except Exception as e:
            logger.error(f"Failed to save triggered instruction: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

    def _get_trigger_description(self, trigger: str) -> str:
        """Get human-readable event description."""
        descriptions = {
            "session_start": "When a new CLI or API session starts",
            "email_received": "When a new email arrives in your inbox",
            "sms_received": "When a new SMS is received",
            "call_received": "When a new phone call is received"
        }
        return descriptions.get(trigger, f"On {trigger} event")

    def _get_example_scenario(self, trigger: str) -> str:
        """Get example scenario for this trigger."""
        examples = {
            "session_start": "You open Zylch CLI → instruction executes",
            "email_received": "Email arrives → instruction executes",
            "sms_received": "SMS arrives → instruction executes",
            "call_received": "Call received → instruction executes"
        }
        return examples.get(trigger, "Event occurs → instruction executes")

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": "The instruction to execute (e.g., 'All'inizio di ogni sessione devi dirmi Buongiorno Mario...')"
                    },
                    "trigger": {
                        "type": "string",
                        "enum": ["session_start", "email_received", "sms_received", "call_received"],
                        "description": "REQUIRED: When to trigger this instruction (session_start, email_received, sms_received, call_received)"
                    },
                    "name": {
                        "type": "string",
                        "description": "Short name for this trigger (e.g., 'Morning greeting')"
                    }
                },
                "required": ["instruction", "trigger"]  # trigger is now REQUIRED
            }
        }


class ListTriggeredInstructionsTool(Tool):
    """List all active triggered instructions."""

    def __init__(self, zylch_memory, owner_id: str, zylch_assistant_id: str):
        super().__init__(
            name="list_triggered_instructions",
            description="List all my active triggered instructions"
        )
        self.zylch_memory = zylch_memory
        self.owner_id = owner_id
        self.zylch_assistant_id = zylch_assistant_id

    def _get_namespace(self) -> str:
        return f"{self.owner_id}:{self.zylch_assistant_id}:triggers"

    async def execute(self) -> ToolResult:
        """List all triggered instructions."""
        try:
            namespace = self._get_namespace()

            # Retrieve all triggers from memory
            memories = self.zylch_memory.retrieve_memories(
                query="triggered instruction",
                namespace=namespace,
                category="trigger",
                limit=50  # Get all
            )

            triggers = []
            for memory in memories:
                try:
                    # Parse the stored JSON
                    data = json.loads(memory.get("pattern", "{}"))
                    if data.get("active", True):
                        triggers.append({
                            "id": data.get("id"),
                            "name": data.get("name"),
                            "instruction": data.get("instruction"),
                            "trigger": data.get("trigger"),
                            "created_at": data.get("created_at")
                        })
                except json.JSONDecodeError:
                    continue

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"triggers": triggers, "count": len(triggers)},
                message=f"Found {len(triggers)} active triggered instructions"
            )

        except Exception as e:
            logger.error(f"Failed to list triggered instructions: {e}")
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
                "properties": {}
            }
        }


class RemoveTriggeredInstructionTool(Tool):
    """Deactivate a triggered instruction."""

    def __init__(self, zylch_memory, owner_id: str, zylch_assistant_id: str):
        super().__init__(
            name="remove_triggered_instruction",
            description="Remove/deactivate a triggered instruction"
        )
        self.zylch_memory = zylch_memory
        self.owner_id = owner_id
        self.zylch_assistant_id = zylch_assistant_id

    def _get_namespace(self) -> str:
        return f"{self.owner_id}:{self.zylch_assistant_id}:triggers"

    async def execute(self, validation_only: bool = False, trigger_id: str = "") -> ToolResult:
        """Remove a triggered instruction by ID.

        Args:
            validation_only: If True, return preview without removing
            trigger_id: The trigger ID to remove

        Returns:
            ToolResult with removal status
        """
        try:
            if not trigger_id:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error="Missing required parameter: trigger_id"
                )

            namespace = self._get_namespace()

            # Find the trigger
            memories = self.zylch_memory.retrieve_memories(
                query=trigger_id,
                namespace=namespace,
                category="trigger",
                limit=10
            )

            found = False
            trigger_data = None
            for memory in memories:
                try:
                    data = json.loads(memory.get("pattern", "{}"))
                    if data.get("id") == trigger_id:
                        found = True
                        trigger_data = data
                        break
                except json.JSONDecodeError:
                    continue

            if not found:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=f"Triggered instruction {trigger_id} not found"
                )

            # VALIDATION MODE: Return preview without removing
            if validation_only:
                logger.info(f"PREVIEW: Would remove triggered instruction {trigger_id}")
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={
                        "trigger_id": trigger_id,
                        "name": trigger_data.get("name"),
                        "instruction": trigger_data.get("instruction"),
                        "trigger": trigger_data.get("trigger"),
                        "action": "remove"
                    },
                    message=(
                        f"PREVIEW: This would remove the triggered instruction.\n"
                        f"Name: {trigger_data.get('name')}\n"
                        f"Trigger: {trigger_data.get('trigger')}\n"
                        f"Instruction: {trigger_data.get('instruction', '')[:80]}..."
                    )
                )

            # EXECUTION MODE: Actually deactivate
            trigger_data["active"] = False
            trigger_data["deactivated_at"] = datetime.utcnow().isoformat()

            # Update in memory (store again with same context)
            self.zylch_memory.store_memory(
                namespace=namespace,
                category="trigger",
                context=f"Triggered instruction (DEACTIVATED): {trigger_data.get('name')}",
                pattern=json.dumps(trigger_data),
                examples=[]
            )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"trigger_id": trigger_id, "removed": True},
                message=f"Triggered instruction {trigger_id} has been deactivated"
            )

        except Exception as e:
            logger.error(f"Failed to remove triggered instruction: {e}")
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
                    "trigger_id": {
                        "type": "string",
                        "description": "The ID of the trigger to remove (e.g., 'trigger_abc123')"
                    }
                },
                "required": ["trigger_id"]
            }
        }


# Helper function to load triggered instructions (for use in chat_service/CLI)
async def load_triggered_instructions(
    zylch_memory,
    owner_id: str,
    zylch_assistant_id: str,
    trigger_filter: Optional[str] = None
) -> List[Dict[str, str]]:
    """Load triggered instructions, optionally filtered by trigger type.

    Args:
        zylch_memory: ZylchMemory instance
        owner_id: Owner ID
        zylch_assistant_id: Assistant ID
        trigger_filter: Optional filter (e.g., "session_start", "email_received")

    Returns:
        List of dicts with {"instruction": str, "trigger": str, "name": str, "id": str}
    """
    namespace = f"{owner_id}:{zylch_assistant_id}:triggers"

    try:
        memories = zylch_memory.retrieve_memories(
            query="triggered instruction",
            namespace=namespace,
            category="trigger",
            limit=50
        )

        triggers = []
        for memory in memories:
            try:
                data = json.loads(memory.get("pattern", "{}"))
                if not data.get("active", True):
                    continue

                trigger_type = data.get("trigger")

                # Apply filter if specified
                if trigger_filter and trigger_type != trigger_filter:
                    continue

                triggers.append({
                    "instruction": data.get("instruction", ""),
                    "trigger": trigger_type,
                    "name": data.get("name", ""),
                    "id": data.get("id", "")
                })
            except json.JSONDecodeError:
                continue

        return [t for t in triggers if t["instruction"]]  # Filter empty

    except Exception as e:
        logger.warning(f"Failed to load triggered instructions: {e}")
        return []
