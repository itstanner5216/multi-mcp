import asyncio
import argparse
from src.multimcp.multi_mcp import MultiMCP


def parse_args():
    parser = argparse.ArgumentParser(description="Run MultiMCP server.")
    parser.add_argument(
        "--transport", choices=["stdio", "sse"], default="stdio", help="Transport mode"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="./examples/config/mcp.json",
        help="Path to MCP config JSON file",
    )
    parser.add_argument(
        "--host", type=str, default="127.0.0.1", help="Host to bind the SSE server"
    )
    parser.add_argument(
        "--port", type=int, default=8085, help="Port to bind the SSE server"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Logging level",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="API key for authentication (also configurable via MULTI_MCP_API_KEY env var)",
    )

    return parser.parse_args()


if __name__ == "__main__":
    # Parse CLI arguments and launch the MultiMCP server with the provided settings
    args = parse_args()

    server = MultiMCP(
        transport=args.transport,
        config=args.config,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        api_key=args.api_key,
    )
    asyncio.run(server.run())
