"""Tests for sandbox_service.py - Sandbox mode enforcement."""

import pytest
from zylch.services.sandbox_service import (
    is_command_allowed_in_sandbox,
    get_sandbox_blocked_response,
    get_sandbox_freeform_blocked_response,
    get_sandbox_help,
    SANDBOX_MODE_MRCALL,
)


class TestIsCommandAllowedInSandbox:
    """Test is_command_allowed_in_sandbox function."""

    # ========== NO SANDBOX = ALL ALLOWED ==========

    def test_no_sandbox_allows_everything(self):
        """With sandbox_mode=None, all commands should be allowed."""
        assert is_command_allowed_in_sandbox("/email", ["list"], None) is True
        assert is_command_allowed_in_sandbox("/sync", [], None) is True
        assert is_command_allowed_in_sandbox("/calendar", [], None) is True
        assert is_command_allowed_in_sandbox("/anything", ["foo"], None) is True

    # ========== MRCALL SANDBOX - ALLOWED COMMANDS ==========

    @pytest.mark.parametrize(
        "cmd,args",
        [
            # /help is always allowed
            ("/help", []),
            ("/HELP", []),  # case insensitive
            # /mrcall is always allowed (all subcommands)
            ("/mrcall", []),
            ("/mrcall", ["open", "abc123"]),
            ("/mrcall", ["list"]),
            ("/mrcall", ["variables"]),
            ("/mrcall", ["show"]),
            ("/mrcall", ["close"]),
            ("/mrcall", ["config", "greeting", "Hello"]),
            ("/MRCALL", ["list"]),  # case insensitive
            # /agent mrcall is allowed
            ("/agent", ["mrcall", "train"]),
            ("/agent", ["mrcall", "run"]),
            ("/agent", ["mrcall", "show"]),
            ("/agent", ["mrcall", "reset"]),
            ("/agent", ["MRCALL", "train"]),  # case insensitive subcommand
            ("/AGENT", ["mrcall", "train"]),  # case insensitive command
        ],
    )
    def test_mrcall_sandbox_allowed_commands(self, cmd, args):
        """Verify allowed commands pass the mrcall sandbox check."""
        assert is_command_allowed_in_sandbox(cmd, args, SANDBOX_MODE_MRCALL) is True

    # ========== MRCALL SANDBOX - BLOCKED COMMANDS ==========

    @pytest.mark.parametrize(
        "cmd,args",
        [
            # Email commands
            ("/email", []),
            ("/email", ["list"]),
            ("/email", ["create"]),
            ("/email", ["send"]),
            ("/email", ["search", "test"]),
            # Calendar commands
            ("/calendar", []),
            ("/calendar", ["today"]),
            ("/calendar", ["7"]),
            # Tasks commands
            ("/tasks", []),
            ("/tasks", ["add", "Buy milk"]),
            ("/tasks", ["list"]),
            # Memory commands
            ("/memory", []),
            ("/memory", ["search", "coffee"]),
            ("/memory", ["store", "test"]),
            # Sync commands
            ("/sync", []),
            ("/sync", ["status"]),
            ("/sync", ["--days", "30"]),
            # Connect commands
            ("/connect", []),
            ("/connect", ["google"]),
            ("/connect", ["mrcall"]),
            # Stats and jobs
            ("/stats", []),
            ("/jobs", []),
            ("/jobs", ["status"]),
            # Reset
            ("/reset", []),
            # Share/revoke
            ("/share", ["test@example.com"]),
            ("/revoke", ["test@example.com"]),
            # /agent with non-mrcall subcommand
            ("/agent", []),  # no subcommand
            ("/agent", ["other", "train"]),
            ("/agent", ["email", "train"]),
            ("/agent", ["zylch", "train"]),
            # Unknown commands
            ("/unknown", []),
            ("/foo", ["bar"]),
        ],
    )
    def test_mrcall_sandbox_blocked_commands(self, cmd, args):
        """Verify blocked commands fail the mrcall sandbox check."""
        assert is_command_allowed_in_sandbox(cmd, args, SANDBOX_MODE_MRCALL) is False


class TestSandboxResponses:
    """Test sandbox response messages."""

    def test_mrcall_blocked_response_contains_available_commands(self):
        """Blocked response should list available commands."""
        response = get_sandbox_blocked_response(SANDBOX_MODE_MRCALL)
        assert "/mrcall" in response
        assert "/agent mrcall" in response
        assert "/help" in response
        # Should mention Zylch app for full features
        assert "Zylch" in response

    def test_mrcall_blocked_response_does_not_contain_blocked_commands(self):
        """Blocked response should not mention blocked commands."""
        response = get_sandbox_blocked_response(SANDBOX_MODE_MRCALL)
        assert "/email" not in response
        assert "/calendar" not in response
        assert "/tasks" not in response
        assert "/sync" not in response

    def test_mrcall_freeform_blocked_response_mentions_mrcall_open(self):
        """Free-form blocked response should guide user to /mrcall open."""
        response = get_sandbox_freeform_blocked_response(SANDBOX_MODE_MRCALL)
        assert "/mrcall open" in response
        assert "/mrcall list" in response

    def test_mrcall_sandbox_help_contains_mrcall_commands(self):
        """Sandbox help should list MrCall configuration commands."""
        help_text = get_sandbox_help(SANDBOX_MODE_MRCALL)
        assert "/mrcall open" in help_text
        assert "/mrcall variables" in help_text
        assert "/mrcall show" in help_text
        assert "/mrcall config" in help_text
        assert "/mrcall close" in help_text

    def test_mrcall_sandbox_help_contains_agent_mrcall_commands(self):
        """Sandbox help should list agent mrcall commands."""
        help_text = get_sandbox_help(SANDBOX_MODE_MRCALL)
        assert "/agent mrcall train" in help_text
        assert "/agent mrcall run" in help_text
        assert "/agent mrcall show" in help_text
        assert "/agent mrcall reset" in help_text

    def test_mrcall_sandbox_help_does_not_contain_blocked_commands(self):
        """Sandbox help should not mention blocked commands."""
        help_text = get_sandbox_help(SANDBOX_MODE_MRCALL)
        # Check that email/calendar/tasks/sync are NOT mentioned as commands
        # (they might appear in explanatory text like "For full features...")
        assert "/email" not in help_text
        assert "/calendar" not in help_text
        assert "/tasks" not in help_text
        assert "/sync" not in help_text
        assert "/memory" not in help_text


class TestEdgeCases:
    """Test edge cases for sandbox logic."""

    def test_empty_args_for_agent_in_mrcall_sandbox(self):
        """Agent with no args should be blocked in mrcall sandbox."""
        assert is_command_allowed_in_sandbox("/agent", [], SANDBOX_MODE_MRCALL) is False

    def test_agent_mrcall_case_variations(self):
        """Agent mrcall should work with various case combinations."""
        assert is_command_allowed_in_sandbox("/agent", ["mrcall"], SANDBOX_MODE_MRCALL) is True
        assert is_command_allowed_in_sandbox("/agent", ["MRCALL"], SANDBOX_MODE_MRCALL) is True
        assert is_command_allowed_in_sandbox("/agent", ["MrCall"], SANDBOX_MODE_MRCALL) is True

    def test_mrcall_with_any_subcommand(self):
        """Any /mrcall subcommand should be allowed in mrcall sandbox."""
        # Even unknown subcommands - let the handler deal with them
        assert is_command_allowed_in_sandbox("/mrcall", ["unknown"], SANDBOX_MODE_MRCALL) is True
        assert is_command_allowed_in_sandbox("/mrcall", ["foo", "bar"], SANDBOX_MODE_MRCALL) is True

    def test_unknown_sandbox_mode_blocks_everything(self):
        """Unknown sandbox mode should block everything for safety."""
        assert is_command_allowed_in_sandbox("/help", [], "unknown_mode") is False
        assert is_command_allowed_in_sandbox("/mrcall", ["list"], "unknown_mode") is False
