"""
MCP Trigger Manager for keyword-based automatic server activation.
"""

from typing import List, Dict
from src.multimcp.mcp_client import MCPClientManager
from src.multimcp.utils.keyword_matcher import (
    extract_keywords_from_message,
    match_triggers,
)
from src.utils.logger import get_logger


class MCPTriggerManager:
    """
    Manages keyword-triggered activation of pending MCP servers.

    Scans incoming messages for trigger keywords and automatically
    enables matching pending servers on-demand.
    """

    def __init__(self, client_manager: MCPClientManager):
        """
        Initialize trigger manager.

        Args:
            client_manager: The client manager containing pending configs
        """
        self.client_manager = client_manager
        self.logger = get_logger("multi_mcp.TriggerManager")

    async def check_and_enable(self, message: dict) -> List[str]:
        """
        Check message for trigger keywords and enable matching servers.

        Args:
            message: JSON-RPC message to scan for triggers

        Returns:
            List of server names that were enabled
        """
        enabled_servers = []

        # Extract text from message
        text = extract_keywords_from_message(message)

        # Check each pending server for trigger matches
        for server_name, config in list(self.client_manager.pending_configs.items()):
            triggers = config.get("triggers", [])

            if triggers and match_triggers(text, triggers):
                self.logger.info(
                    f"🔥 Trigger matched for server '{server_name}', enabling..."
                )

                try:
                    # Enable the server by creating client
                    await self.client_manager.get_or_create_client(server_name)
                    enabled_servers.append(server_name)
                    self.logger.info(f"✅ Server '{server_name}' enabled successfully")
                except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
                    self.logger.error(
                        f"❌ Failed to enable server '{server_name}': {e}"
                    )

        return enabled_servers
