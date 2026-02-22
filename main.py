import asyncio
import anyio
import argparse
from pathlib import Path
from src.multimcp.multi_mcp import MultiMCP
from src.multimcp.cli import cmd_list, cmd_status, cmd_refresh, DEFAULT_YAML


def parse_args():
    parser = argparse.ArgumentParser(description="Multi-MCP proxy server")
    sub = parser.add_subparsers(dest="command", required=True)

    # start
    start = sub.add_parser("start", help="Start the proxy server")
    start.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    start.add_argument("--host", type=str, default="127.0.0.1")
    start.add_argument("--port", type=int, default=8085)
    start.add_argument(
        "--config", type=str, default=None,
        help="Path to MCP JSON config. If omitted, auto-discovers from Claude plugins and YAML sources."
    )
    start.add_argument("--api-key", type=str, default=None)
    start.add_argument(
        "--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO"
    )

    # refresh
    refresh = sub.add_parser("refresh", help="Re-discover tools and update YAML")
    refresh.add_argument("server", nargs="?", help="Specific server to refresh (omit for all)")

    # status
    sub.add_parser("status", help="Show server and tool summary")

    # list
    lst = sub.add_parser("list", help="List all tools with enabled/disabled status")
    lst.add_argument("--server", type=str, default=None, help="Filter to one server")
    lst.add_argument("--disabled", action="store_true", help="Show only disabled tools")

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.command == "start":
        server = MultiMCP(
            transport=args.transport,
            config=args.config,
            host=args.host,
            port=args.port,
            log_level=args.log_level,
            api_key=args.api_key,
        )
        asyncio.run(server.run())

    elif args.command == "refresh":
        async def _refresh():
            return await cmd_refresh(server_filter=args.server)
        result = anyio.run(_refresh)
        print(result)

    elif args.command == "status":
        print(cmd_status())

    elif args.command == "list":
        print(cmd_list(server_filter=args.server, disabled_only=args.disabled))
