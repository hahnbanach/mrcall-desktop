"""Tests for MrCall integration in Zylch.

Run with: python -m pytest tests/test_mrcall_integration.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Test imports
def test_imports():
    """Test that all mrcall modules import correctly."""
    from zylch.tools.mrcall import (
        extract_variables,
        validate_variable_preservation,
        create_variable_preservation_instructions,
        format_variable_changes,
        modify_prompt_with_llm,
        GetAssistantCatalogTool,
        ConfigureAssistantTool,
        SaveMrCallAdminRuleTool,
        MRCALL_ADMIN_NAMESPACE,
        MRCALL_BUSINESS_PREFIX,
    )
    assert MRCALL_ADMIN_NAMESPACE == "mrcall:admin"
    assert MRCALL_BUSINESS_PREFIX == "mrcall:"


# Test variable_utils
class TestVariableUtils:
    """Tests for variable_utils module."""

    def test_extract_variables_percent_format(self):
        from zylch.tools.mrcall.variable_utils import extract_variables

        text = "Hello %%name=Guest%%! Your phone is %%phone=unknown%%."
        variables = extract_variables(text)

        assert len(variables) == 2
        assert "%%name=Guest%%" in variables
        assert "%%phone=unknown%%" in variables

    def test_extract_variables_curly_format(self):
        from zylch.tools.mrcall.variable_utils import extract_variables

        text = "The time is {{public.HUMANIZED_TIME}} and date is {{public.DATE}}"
        variables = extract_variables(text)

        assert len(variables) == 2
        assert "{{public.HUMANIZED_TIME}}" in variables
        assert "{{public.DATE}}" in variables

    def test_extract_variables_mixed(self):
        from zylch.tools.mrcall.variable_utils import extract_variables

        text = "Hi %%name=Guest%%! Time: {{public.TIME}}"
        variables = extract_variables(text)

        assert len(variables) == 2

    def test_extract_variables_empty(self):
        from zylch.tools.mrcall.variable_utils import extract_variables

        assert extract_variables("") == []
        assert extract_variables(None) == []
        assert extract_variables("No variables here") == []

    def test_validate_variable_preservation_all_preserved(self):
        from zylch.tools.mrcall.variable_utils import validate_variable_preservation

        original = "Ciao %%name=Guest%%! Come posso aiutarti?"
        modified = "Buongiorno %%name=Guest%%! Sono qui per assisterti."

        result = validate_variable_preservation(original, modified)

        assert result["all_preserved"] is True
        assert result["removed"] == []
        assert result["added"] == []
        assert "%%name=Guest%%" in result["preserved"]

    def test_validate_variable_preservation_removed(self):
        from zylch.tools.mrcall.variable_utils import validate_variable_preservation

        original = "Ciao %%name=Guest%%! Il tuo telefono e' %%phone%%."
        modified = "Ciao Mario! Il tuo telefono e' %%phone%%."

        result = validate_variable_preservation(original, modified)

        assert result["all_preserved"] is False
        assert "%%name=Guest%%" in result["removed"]
        assert "%%phone%%" in result["preserved"]

    def test_validate_variable_preservation_added(self):
        from zylch.tools.mrcall.variable_utils import validate_variable_preservation

        original = "Ciao!"
        modified = "Ciao %%name=Guest%%!"

        result = validate_variable_preservation(original, modified)

        assert result["all_preserved"] is True  # No variables removed
        assert "%%name=Guest%%" in result["added"]

    def test_validate_no_placeholders_clean(self):
        from zylch.tools.mrcall.variable_utils import validate_no_placeholders

        text = "Questo e' un testo completo senza placeholder."
        is_valid, error = validate_no_placeholders(text)

        assert is_valid is True
        assert error is None

    def test_validate_no_placeholders_ellipsis(self):
        from zylch.tools.mrcall.variable_utils import validate_no_placeholders

        text = "Testo con ... nel mezzo"
        is_valid, error = validate_no_placeholders(text)

        assert is_valid is False
        assert "ellipsis" in error

    def test_validate_no_placeholders_resto(self):
        from zylch.tools.mrcall.variable_utils import validate_no_placeholders

        text = "Inizio [resto invariato]"
        is_valid, error = validate_no_placeholders(text)

        assert is_valid is False
        assert "resto" in error.lower()


# Test tool schemas
class TestToolSchemas:
    """Tests for tool schema definitions."""

    def test_get_assistant_catalog_schema(self):
        from zylch.tools.mrcall import GetAssistantCatalogTool
        from zylch.tools.factory import SessionState

        mock_starchat = MagicMock()
        session = SessionState(business_id="test-123")

        tool = GetAssistantCatalogTool(mock_starchat, session)
        schema = tool.get_schema()

        assert schema["name"] == "get_assistant_catalog"
        assert "filter_category" in schema["input_schema"]["properties"]
        assert "welcome" in schema["input_schema"]["properties"]["filter_category"]["enum"]

    def test_configure_assistant_schema(self):
        from zylch.tools.mrcall import ConfigureAssistantTool
        from zylch.tools.factory import SessionState

        mock_starchat = MagicMock()
        mock_memory = MagicMock()
        session = SessionState(business_id="test-123")

        tool = ConfigureAssistantTool(mock_starchat, session, mock_memory, "api-key")
        schema = tool.get_schema()

        assert schema["name"] == "configure_assistant"
        assert "variable_name" in schema["input_schema"]["properties"]
        assert "request" in schema["input_schema"]["properties"]
        assert "confirm_apply" in schema["input_schema"]["properties"]
        assert schema["input_schema"]["required"] == ["variable_name", "request"]

    def test_save_admin_rule_schema(self):
        from zylch.tools.mrcall import SaveMrCallAdminRuleTool
        from zylch.tools.factory import SessionState

        mock_starchat = MagicMock()
        mock_memory = MagicMock()
        session = SessionState(business_id="test-123")

        tool = SaveMrCallAdminRuleTool(mock_starchat, session, mock_memory)
        schema = tool.get_schema()

        assert schema["name"] == "save_mrcall_admin_rule"
        assert "rule" in schema["input_schema"]["properties"]
        assert "applies_to" in schema["input_schema"]["properties"]


# Test tool execution (with mocks)
class TestToolExecution:
    """Tests for tool execution logic."""

    @pytest.mark.asyncio
    async def test_get_catalog_no_business_selected(self):
        from zylch.tools.mrcall import GetAssistantCatalogTool
        from zylch.tools.factory import SessionState
        from zylch.tools.base import ToolStatus

        mock_starchat = MagicMock()
        session = SessionState(business_id=None)  # No business selected

        tool = GetAssistantCatalogTool(mock_starchat, session)
        result = await tool.execute(filter_category="all")

        assert result.status == ToolStatus.ERROR
        assert "No MrCall assistant selected" in result.error

    @pytest.mark.asyncio
    async def test_configure_assistant_no_business_selected(self):
        from zylch.tools.mrcall import ConfigureAssistantTool
        from zylch.tools.factory import SessionState
        from zylch.tools.base import ToolStatus

        mock_starchat = MagicMock()
        mock_memory = MagicMock()
        session = SessionState(business_id=None)

        tool = ConfigureAssistantTool(mock_starchat, session, mock_memory, "api-key")
        result = await tool.execute(
            variable_name="TEST_VAR",
            request="Test request"
        )

        assert result.status == ToolStatus.ERROR
        assert "No MrCall assistant selected" in result.error

    @pytest.mark.asyncio
    async def test_save_admin_rule_permission_denied(self):
        from zylch.tools.mrcall import SaveMrCallAdminRuleTool
        from zylch.tools.factory import SessionState
        from zylch.tools.base import ToolStatus

        mock_starchat = AsyncMock()
        mock_starchat.check_user_role = AsyncMock(return_value="user")  # Not admin
        mock_memory = MagicMock()
        session = SessionState(business_id="test-123")

        tool = SaveMrCallAdminRuleTool(mock_starchat, session, mock_memory)
        result = await tool.execute(
            rule="Test rule",
            applies_to="all"
        )

        assert result.status == ToolStatus.ERROR
        assert "Permesso negato" in result.error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
