"""Tests for Zylch AI agent."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from zylch.agent import ZylchAIAgent
from zylch.agent.models import ModelSelector
from zylch.tools.base import Tool, ToolResult, ToolStatus


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

    agent = ZylchAIAgent(
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

    # Test classification - uses haiku for explicit classification keywords
    model = selector.select_model("classify this email priority")
    assert model == selector.classification_model

    # Test "who is" queries - uses Sonnet (default) for tool calling intelligence
    model = selector.select_model("who is john@example.com?")
    assert model == selector.default_model

    # Test drafting
    model = selector.select_model("draft an email to jane@example.com")
    assert model == selector.default_model

    # Test executive (use message without "write" to avoid quality model trigger)
    model = selector.select_model("urgent message for the CEO")
    assert model == selector.executive_model
