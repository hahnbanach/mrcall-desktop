"""Base classes for Zylch AI tools."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from dataclasses import dataclass
from enum import Enum


class ToolStatus(Enum):
    """Tool execution status."""

    SUCCESS = "success"
    ERROR = "error"
    PENDING_APPROVAL = "pending_approval"


@dataclass
class ToolResult:
    """Result from tool execution."""

    status: ToolStatus
    data: Any
    message: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "status": self.status.value,
            "data": self.data,
            "message": self.message,
            "error": self.error,
        }


class Tool(ABC):
    """Base class for all Zylch AI tools."""

    def __init__(self, name: str, description: str):
        """Initialize tool with name and description."""
        self.name = name
        self.description = description

    @abstractmethod
    async def execute(self, validation_only: bool = False, **kwargs) -> ToolResult:
        """Execute the tool with given parameters.

        Args:
            validation_only: If True, return preview without side effects
            **kwargs: Tool-specific parameters

        Returns:
            ToolResult with execution status and data
        """
        pass

    @abstractmethod
    def get_schema(self) -> Dict[str, Any]:
        """Get Anthropic function calling schema for this tool.

        Returns:
            Schema dictionary for Anthropic API
        """
        pass

    def approval_input(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """Fields to show (and let the user edit) in the approval card.

        The renderer's approval card renders every string field of this
        dict as an editable textarea/input, and the edited copy is swapped
        back in as the tool's actual input before it runs. By default the
        card mirrors the model-supplied ``tool_input`` verbatim.

        Override when the model-facing schema is a *reference* (e.g. a bare
        ``draft_id``) but the human needs the *content* in front of them to
        review and edit — the override hydrates the referenced content into
        editable fields. ``execute`` must then accept those extra fields.
        """
        return dict(tool_input or {})
