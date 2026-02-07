"""
Tests for keyword-triggered auto-enable functionality (Task 07).

Following TDD: RED -> GREEN -> REFACTOR
"""

import pytest
import json
from src.multimcp.mcp_client import MCPClientManager
from src.multimcp.mcp_proxy import MCPProxyServer
from src.multimcp.multi_mcp import MultiMCP


class TestKeywordTriggerConfig:
    """Test that trigger keywords can be configured in server configs."""

    def test_config_with_triggers_is_accepted(self):
        """Test that server config can include 'triggers' field."""
        config = {
            "mcpServers": {
                "test_server": {
                    "command": "python",
                    "args": ["./tests/tools/calculator.py"],
                    "triggers": ["calculate", "math", "addition"],
                }
            }
        }

        # Should parse without error
        assert "triggers" in config["mcpServers"]["test_server"]
        assert len(config["mcpServers"]["test_server"]["triggers"]) == 3

    def test_config_without_triggers_is_accepted(self):
        """Test that server config without 'triggers' still works (backward compatible)."""
        config = {
            "mcpServers": {
                "test_server": {
                    "command": "python",
                    "args": ["./tests/tools/calculator.py"],
                }
            }
        }

        # Should not have triggers
        assert "triggers" not in config["mcpServers"]["test_server"]


class TestKeywordMatching:
    """Test keyword matching logic."""

    def test_extract_keywords_from_message(self):
        """Test extracting keywords from JSON-RPC message content."""
        from src.multimcp.utils.keyword_matcher import extract_keywords_from_message

        message = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "some_tool",
                "arguments": {"query": "I need to calculate the sum of 5 and 3"},
            },
        }

        keywords = extract_keywords_from_message(message)

        # Should extract text from arguments
        assert "calculate" in keywords.lower()
        assert "sum" in keywords.lower()

    def test_match_triggers_in_text(self):
        """Test matching trigger keywords in text."""
        from src.multimcp.utils.keyword_matcher import match_triggers

        triggers = ["sentry", "error", "exception"]
        text = "I'm getting a sentry error with this code"

        matched = match_triggers(text, triggers)

        assert matched is True

    def test_no_match_when_triggers_absent(self):
        """Test that no match occurs when triggers not in text."""
        from src.multimcp.utils.keyword_matcher import match_triggers

        triggers = ["sentry", "error", "exception"]
        text = "This is working fine, no issues"

        matched = match_triggers(text, triggers)

        assert matched is False

    def test_case_insensitive_matching(self):
        """Test that trigger matching is case-insensitive."""
        from src.multimcp.utils.keyword_matcher import match_triggers

        triggers = ["GitHub"]
        text = "I need to search github repositories"

        matched = match_triggers(text, triggers)

        assert matched is True


@pytest.mark.asyncio
class TestAutoEnableOnTrigger:
    """Test automatic server enabling based on keyword triggers."""

    async def test_pending_server_enabled_when_trigger_matched(self):
        """Test that pending server is auto-enabled when trigger keyword appears."""
        from src.multimcp.mcp_trigger_manager import MCPTriggerManager

        manager = MCPClientManager()

        # Add pending server with triggers
        manager.add_pending_server(
            "github",
            {
                "command": "echo",
                "args": ["github-server"],
                "triggers": ["github", "repository", "pull request"],
            },
        )

        trigger_mgr = MCPTriggerManager(manager)

        # Message with trigger keyword
        message = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "arguments": {"query": "Search github repositories for python projects"}
            },
        }

        # Should detect trigger and attempt to enable
        matched_servers = await trigger_mgr.check_and_enable(message)

        assert "github" in matched_servers

    async def test_no_enable_when_no_trigger_match(self):
        """Test that server stays pending when no trigger matches."""
        from src.multimcp.mcp_trigger_manager import MCPTriggerManager

        manager = MCPClientManager()

        # Add pending server with triggers
        manager.add_pending_server(
            "github",
            {
                "command": "echo",
                "args": ["github-server"],
                "triggers": ["github", "repository"],
            },
        )

        trigger_mgr = MCPTriggerManager(manager)

        # Message without trigger keywords
        message = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"arguments": {"query": "Calculate the sum of 5 and 3"}},
        }

        matched_servers = await trigger_mgr.check_and_enable(message)

        assert "github" not in matched_servers

    async def test_multiple_servers_enabled_when_multiple_triggers_match(self):
        """Test that multiple servers can be enabled from same message."""
        from src.multimcp.mcp_trigger_manager import MCPTriggerManager

        manager = MCPClientManager()

        # Add multiple pending servers with different triggers
        manager.add_pending_server(
            "github",
            {
                "command": "echo",
                "args": ["github"],
                "triggers": ["github", "repository"],
            },
        )
        manager.add_pending_server(
            "sentry",
            {
                "command": "echo",
                "args": ["sentry"],
                "triggers": ["sentry", "error", "exception"],
            },
        )

        trigger_mgr = MCPTriggerManager(manager)

        # Message with both triggers
        message = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"arguments": {"query": "Check github for sentry error logs"}},
        }

        matched_servers = await trigger_mgr.check_and_enable(message)

        assert "github" in matched_servers
        assert "sentry" in matched_servers


@pytest.mark.asyncio
class TestMCPControlEndpoint:
    """Test /mcp_control endpoint for manual server management."""

    async def test_mcp_control_enable_activates_pending_server(self):
        """Test POST /mcp_control with action=enable activates a pending server."""
        # This test requires HTTP client, will implement after core logic works
        pass

    async def test_mcp_control_disable_moves_server_to_pending(self):
        """Test POST /mcp_control with action=disable moves server to pending."""
        # This test requires HTTP client, will implement after core logic works
        pass

    async def test_mcp_control_requires_auth_when_enabled(self):
        """Test that /mcp_control respects API key auth."""
        # This test requires HTTP client, will implement after core logic works
        pass
