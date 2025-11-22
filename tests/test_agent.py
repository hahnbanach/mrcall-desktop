"""Tests for MrPark agent."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from mrpark.agent import MrParkAgent
from mrpark.agent.models import ModelSelector
from mrpark.tools.base import Tool, ToolResult, ToolStatus


class MockTool(Tool):
    """Mock tool for testing."""

    def __init__(self):
        super().__init__(name="mock_tool", description="Mock tool for testing")

    async def execute(self, **kwargs):
        return ToolResult(
            status=ToolStatus.SUCCESS,
            data={"test": "data"},
            message="Mock tool executed"
        )

    def get_schema(self):
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }


@pytest.mark.asyncio
async def test_agent_initialization():
    """Test agent initialization."""
    tools = [MockTool()]
    model_selector = ModelSelector()

    agent = MrParkAgent(
        api_key="test_key",
        tools=tools,
        model_selector=model_selector,
    )

    assert agent is not None
    assert len(agent.tools) == 1
    assert agent.model_selector is not None


@pytest.mark.asyncio
async def test_model_selector():
    """Test model selection logic."""
    selector = ModelSelector()

    # Test classification
    model = selector.select_model("who is john@example.com?")
    assert model == selector.classification_model

    # Test drafting
    model = selector.select_model("draft an email to jane@example.com")
    assert model == selector.default_model

    # Test executive
    model = selector.select_model("write to the CEO about urgent matter")
    assert model == selector.executive_model
