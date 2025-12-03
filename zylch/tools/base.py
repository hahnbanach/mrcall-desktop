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
