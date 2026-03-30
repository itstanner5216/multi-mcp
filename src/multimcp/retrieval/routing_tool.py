"""Synthetic MCP routing tool for demoted tools discovery.

The routing tool is the safety valve for the bounded active set invariant.
Every tool beyond top-K appears in the routing tool's enum, never as a
direct tool. The model calls `request_tool(name="server__tool", describe=true)`
to get any schema, or omits describe to proxy-call it.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import TYPE_CHECKING, Optional

from mcp import types

if TYPE_CHECKING:
    pass  # ToolMapping imported at runtime only where needed

ROUTING_TOOL_NAME = "request_tool"
ROUTING_TOOL_KEY = "__routing__request_tool"


def build_routing_tool_schema(demoted_tool_ids: list[str]) -> types.Tool:
    """Build the synthetic routing tool with enum of all demoted tool IDs.

    Args:
        demoted_tool_ids: List of tool keys in "server__tool" format that are
            beyond the active set and accessible only via routing.

    Returns:
        A types.Tool representing the routing tool with the full enum.
    """
    return types.Tool(
        name=ROUTING_TOOL_NAME,
        description=(
            "Access tools not in your active set. "
            "Use describe=true to get full schema, or provide arguments to call directly."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Tool name (server__tool format)",
                    "enum": demoted_tool_ids,
                },
                "describe": {
                    "type": "boolean",
                    "description": "If true, return tool schema instead of calling",
                    "default": False,
                },
                "arguments": {
                    "type": "object",
                    "description": "Arguments to pass when describe=false",
                    "default": {},
                },
            },
            "required": ["name"],
        },
    )


def format_namespace_grouped(
    tool_ids: list[str],
    env_namespaces: list[str],
) -> list[str]:
    """Order tool IDs with env-relevant namespaces first, then alphabetically.

    Groups tool_ids by namespace (prefix before "__").
    Outputs env_namespaces groups first (each sorted internally),
    then remaining groups sorted alphabetically.

    Args:
        tool_ids: List of tool keys in "server__tool" format.
        env_namespaces: Namespaces to place at the front of the ordering.

    Returns:
        Ordered list of tool IDs.
    """
    groups: dict[str, list[str]] = defaultdict(list)
    for tool_id in tool_ids:
        if "__" in tool_id:
            ns = tool_id.split("__", 1)[0]
        else:
            ns = ""
        groups[ns].append(tool_id)

    ordered: list[str] = []
    # Env namespaces first, in declaration order
    for ns in env_namespaces:
        if ns in groups:
            ordered.extend(sorted(groups.pop(ns)))

    # Remaining groups sorted alphabetically by namespace
    for ns in sorted(groups.keys()):
        ordered.extend(sorted(groups[ns]))

    return ordered


def handle_routing_call(
    name: str,
    describe: bool,
    arguments: dict,
    tool_to_server: dict,
) -> list[types.TextContent]:
    """Handle a call to the routing tool.

    Args:
        name: The tool key (server__tool format) to look up or call.
        describe: If True, return the tool's schema as JSON.
        arguments: Arguments to pass when describe=False.
        tool_to_server: Mapping from tool key to ToolMapping objects.

    Returns:
        List with a single TextContent response.
    """
    mapping = tool_to_server.get(name)
    if mapping is None:
        available = sorted(tool_to_server.keys())[:10]
        return [
            types.TextContent(
                type="text",
                text=f"Tool not found: {name!r}. Available: {available}",
            )
        ]

    if describe:
        tool = mapping.tool
        schema_info = {
            "name": tool.name,
            "description": tool.description or "",
            "inputSchema": tool.inputSchema,
        }
        return [
            types.TextContent(
                type="text",
                text=json.dumps(schema_info, indent=2),
            )
        ]

    # describe=False: proxy caller handles async dispatch
    return [
        types.TextContent(
            type="text",
            text=f"__PROXY_CALL__:{name}",
        )
    ]
