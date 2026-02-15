"""Tests for Zylch AI agent."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from zylch.assistant import ZylchAIAgent
from zylch.assistant.models import ModelSelector
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
        provider="anthropic",
        model_selector=model_selector,
    )

    assert agent is not None
    assert len(agent.tools) == 1
    assert agent.model_selector is not None


@pytest.mark.asyncio
async def test_model_selector():
    """Test model selection — always returns default model."""
    selector = ModelSelector()

    # All queries return the same default model
    model = selector.select_model("classify this email priority")
    assert model == selector.default_model

    model = selector.select_model("who is john@example.com?")
    assert model == selector.default_model

    model = selector.select_model("draft an email to jane@example.com")
    assert model == selector.default_model

    model = selector.select_model("urgent message for the CEO")
    assert model == selector.default_model

    # force_model overrides
    model = selector.select_model("anything", force_model="custom-model")
    assert model == "custom-model"
