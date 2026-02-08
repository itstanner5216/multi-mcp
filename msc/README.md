# Production MCP Configuration

This directory contains production MCP server configuration for the multi-mcp proxy.

## Configuration File

The `mcp.json` file in this directory defines external MCP servers to connect to:

- **GitHub MCP Server**: Repository management, issues, pull requests
- **Brave Search MCP Server**: Web search capabilities  
- **Context7 MCP Server**: Library documentation and code examples

## Security Note

⚠️ **The `msc/` directory is git-ignored** to prevent accidental commits of configuration that may contain sensitive data.

The configuration uses environment variable interpolation for secrets:
- `${GITHUB_PERSONAL_ACCESS_TOKEN}` - GitHub personal access token
- `${BRAVE_API_KEY}` - Brave Search API key
- `${MULTI_MCP_API_KEY}` - (Optional) Multi-MCP API authentication key

## Template Configuration

Create your `msc/mcp.json` using this template:

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}"
      },
      "triggers": ["github", "repository", "repo", "pull request", "pr", "issue", "commit", "branch", "fork", "clone"]
    },
    "brave-search": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": {
        "BRAVE_API_KEY": "${BRAVE_API_KEY}"
      },
      "triggers": ["search", "web search", "brave", "find", "lookup", "query", "internet"]
    },
    "context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp"],
      "triggers": ["documentation", "docs", "library", "api reference", "code example", "how to use", "package", "framework"]
    }
  }
}
```

## Environment Variables

Set these environment variables before starting the server:

```bash
export GITHUB_PERSONAL_ACCESS_TOKEN="your-token-here"
export BRAVE_API_KEY="your-api-key-here"
export MULTI_MCP_API_KEY="your-secret-key"  # Optional, for authentication
```

## Usage

Start the server with production configuration:

```bash
./start-server.sh
```

Or manually:

```bash
python main.py --transport sse --host 0.0.0.0 --port 8085 --config msc/mcp.json
```
