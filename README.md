
# **Multi MCP**

A flexible and dynamic **Multi-MCP** Proxy Server that acts as a single MCP server while connecting to and routing between
multiple backend MCP servers over `STDIO` or `SSE`.

<p align="center">
  <img src="assets/multi-mcp-diagram.png" alt="Multi-MCP Server Architecture" width="300"/>
</p>

## 🚀 Features

- ✅ Supports both `STDIO` and `SSE` transports
- ✅ Can connect to MCP servers running in either `STDIO` or `SSE` mode
- ✅ Proxies requests to multiple MCP servers
- ✅ Automatically initializes capabilities (tools, prompts, resources) from connected servers
- ✅ Dynamically **add/remove MCP servers** at runtime (via HTTP API)
- ✅ Supports tools with the same name on different servers (using namespacing)
- ✅ Deployable on Kubernetes, exposing a single port to access all connected MCP servers through the proxy

## 📦 Installation

To get started with this project locally:

```bash
# Clone the repository
git clone https://github.com/kfirtoledo/multi-mcp.git
cd multi-mcp

# Install using uv (recommended)
uv venv
uv pip install -r requirements.txt
```

## 🖥️ Running Locally

You can run the proxy locally in either `STDIO` or `SSE` mode depending on your needs:

### 1. STDIO Mode
For CLI-style operation (pipe-based communication).
Used for chaining locally executed tools or agents.

```bash
uv run main.py --transport stdio
```

### 2. SSE Mode
Runs an HTTP SSE server that exposes a `/sse` endpoint.
Useful for remote access, browser agents, and network-based tools.

```bash
uv run main.py --transport sse
```

**Note:** You can also configure the host and port using `--host` / `--port` arguments.

### 3. Production Mode (with External MCP Servers)

For production deployments with external MCP servers (GitHub, Brave Search, Context7), use the included startup script:

```bash
# Set required environment variables
export GITHUB_PERSONAL_ACCESS_TOKEN="your-token-here"
export BRAVE_API_KEY="your-api-key-here"
export MULTI_MCP_API_KEY="your-secret-key"  # Optional, for authentication

# Run the startup script
./start-server.sh
```

The production configuration is stored in `msc/mcp.json` (git-ignored for security). This configuration includes:
- **GitHub MCP Server**: Repository management, issues, pull requests
- **Brave Search MCP Server**: Web search capabilities
- **Context7 MCP Server**: Library documentation and code examples

All servers use environment variable interpolation for secrets (e.g., `${GITHUB_PERSONAL_ACCESS_TOKEN}`).

## ⚙️ Configuration

The proxy is initialized using a JSON config (default: `./mcp.json`):

```json
{
  "mcpServers": {
    "weather": {
      "command": "python",
      "args": ["./tools/get_weather.py"]
    },
    "calculator": {
      "command": "python",
      "args": ["./tools/calculator.py"]
    }
  }
}
```

This config defines the initial list of MCP-compatible servers to spawn and connect at startup.

**Note:** Tool names are namespaced internally as `server_name::tool_name` to avoid conflicts and allow multiple servers to expose tools with the same base name. For example, if an MCP server named `calculator` provides an `add` tool, it will be referenced as `calculator::add`.

You can also connect to a remote MCP server using SSE:

```json
{
  "mcpServers": {
    "weather": {
      "url": "http://127.0.0.1:9080/sse"
    }
  }
}
```

More examples can be found in the [examples/config/](./examples/config/) directory.

## 🔄 Dynamic Server Management (SSE only)

When running in SSE mode, you can **add/remove/list MCP servers at runtime** via HTTP endpoints:

| Method | Endpoint               | Description                 |
|--------|------------------------|-----------------------------|
| `GET`  | `/mcp_servers`         | List active MCP servers     |
| `POST` | `/mcp_servers`         | Add a new MCP server        |
| `DELETE`| `/mcp_servers/{name}` | Remove an MCP server by name |
| `GET`  | `/mcp_tools`           | Lists all available tools and their serves sources|

### Example to add a new server:

```bash
curl -X POST http://localhost:8080/mcp_servers \
  -H "Content-Type: application/json" \
  --data @add_server.json
```

**add_server.json**:

```json
{
  "mcpServers": {
    "unit_converter": {
      "command": "python",
      "args": ["./tools/unit_converter.py"]
    }
  }
}
```

## 🐳 Docker

You can containerize and run the SSE server in K8s:

```bash
# Build the image
make docker-build

# Run locally with port exposure
make docker-run
```

## Kubernetes

You can deploy the proxy in a Kubernetes cluster using the provided manifests.

### Run with [Kind](https://kind.sigs.k8s.io/)

To run the proxy locally using Kind:

```bash
kind create cluster --name multi-mcp-test
kind load docker-image multi-mcp --name multi-mcp-test
kubectl apply -f k8s/multi-mcp.yaml
```
### Exposing the Proxy
The K8s manifest exposes the SSE server via a NodePort (30080 by default):
You can then connect to the SSE endpoint from outside the cluster:

```sh
http://<kind-node-ip>:30080/sse
```
## Connecting to MCP Clients
Once the proxy is running, you can connect to it using any MCP-compatible client — such as a LangGraph agent or custom MCP client.

For example, using the langchain_mcp_adapters client, you can integrate directly with LangGraph to access tools from one or more backend MCP servers.

See [`examples/connect_langgraph_client.py`](examples/connect_langgraph_client.py) for a working integration example.

Make sure your environment is set up with:

- An MCP-compatible client (e.g. LangGraph)

- .env file containing:

```env
MODEL_NAME=<your-model-name>
BASE_URL=<https://your-openai-base-url>
OPENAI_API_KEY=<your-api-key>
```



## Inspiration

This project is inspired by and builds on ideas from two excellent open-source MCP projects:

- [`mcp-proxy`](https://github.com/sparfenyuk/mcp-proxy) by @sparfenyuk
- [`fastmcp`](https://github.com/jlowin/fastmcp) by @jlowin

