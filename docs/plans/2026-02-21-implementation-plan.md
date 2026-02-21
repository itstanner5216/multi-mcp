# Multi-MCP Proxy Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade multi-mcp into a production-quality system-wide MCP proxy with unified YAML config/cache, startup discovery-with-disconnect, always-on vs lazy server lifecycle, idle timeout auto-disconnect, and a clean CLI.

**Architecture:** Startup connects to every server briefly to discover tools, writes a unified YAML file (cache + config + control plane), then disconnects lazy servers. On subsequent starts it reads the YAML instantly with no network calls. Tool enable/disable is edited directly in the YAML and is never overwritten by refresh.

**Tech Stack:** Python 3.10+, pydantic 2, pyyaml 6, asyncio, mcp 1.4.1, existing multi-mcp codebase. All deps already installed.

**Test runner:** `uv run --project /home/tanner/Projects/multi-mcp python -m pytest <test> -v`

---

## Task 1: YAML Config Model

**Files:**
- Create: `src/multimcp/yaml_config.py`
- Create: `tests/test_yaml_config.py`

### Step 1: Write the failing tests

```python
# tests/test_yaml_config.py
import pytest
import yaml
import tempfile
from pathlib import Path
from src.multimcp.yaml_config import ToolEntry, ServerConfig, MultiMCPConfig, load_config, save_config

def test_tool_entry_defaults():
    t = ToolEntry()
    assert t.enabled is True
    assert t.stale is False
    assert t.description == ""

def test_server_config_defaults():
    s = ServerConfig()
    assert s.always_on is False
    assert s.idle_timeout_minutes == 5
    assert s.tools == {}

def test_load_config_from_yaml():
    content = """
servers:
  github:
    command: /usr/bin/run-github.sh
    always_on: true
    tools:
      search_repositories:
        enabled: true
      create_gist:
        enabled: false
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(content)
        path = Path(f.name)

    config = load_config(path)
    assert "github" in config.servers
    assert config.servers["github"].always_on is True
    assert config.servers["github"].tools["search_repositories"].enabled is True
    assert config.servers["github"].tools["create_gist"].enabled is False

def test_save_and_reload_config():
    config = MultiMCPConfig(servers={
        "exa": ServerConfig(
            url="https://mcp.exa.ai/mcp",
            always_on=False,
            tools={"web_search_exa": ToolEntry(enabled=True, description="Search the web")}
        )
    })
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        path = Path(f.name)

    save_config(config, path)
    reloaded = load_config(path)
    assert reloaded.servers["exa"].tools["web_search_exa"].enabled is True
    assert reloaded.servers["exa"].tools["web_search_exa"].description == "Search the web"

def test_load_missing_file_returns_empty_config():
    config = load_config(Path("/tmp/does_not_exist_multi_mcp.yaml"))
    assert config.servers == {}
```

### Step 2: Run to verify failure

```bash
uv run --project /home/tanner/Projects/multi-mcp python -m pytest tests/test_yaml_config.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.multimcp.yaml_config'`

### Step 3: Implement

```python
# src/multimcp/yaml_config.py
from __future__ import annotations
from pathlib import Path
from typing import Dict, Optional
import yaml
from pydantic import BaseModel, Field


class ToolEntry(BaseModel):
    enabled: bool = True
    stale: bool = False
    description: str = ""


class ServerConfig(BaseModel):
    command: Optional[str] = None
    args: list[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    url: Optional[str] = None
    type: str = "stdio"
    always_on: bool = False
    idle_timeout_minutes: int = 5
    tools: Dict[str, ToolEntry] = Field(default_factory=dict)


class MultiMCPConfig(BaseModel):
    servers: Dict[str, ServerConfig] = Field(default_factory=dict)


def load_config(path: Path) -> MultiMCPConfig:
    """Load YAML config from path. Returns empty config if file doesn't exist."""
    if not path.exists():
        return MultiMCPConfig()
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    return MultiMCPConfig.model_validate(raw)


def save_config(config: MultiMCPConfig, path: Path) -> None:
    """Save config to YAML file, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(
            config.model_dump(exclude_none=False),
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
```

### Step 4: Run to verify passing

```bash
uv run --project /home/tanner/Projects/multi-mcp python -m pytest tests/test_yaml_config.py -v
```
Expected: `5 passed`

### Step 5: Commit

```bash
git add src/multimcp/yaml_config.py tests/test_yaml_config.py
git commit -m "feat: add YAML config model with load/save"
```

---

## Task 2: Smart Merge Logic

**Files:**
- Create: `src/multimcp/cache_manager.py`
- Create: `tests/test_cache_manager.py`

### Step 1: Write the failing tests

```python
# tests/test_cache_manager.py
import pytest
from mcp import types
from src.multimcp.yaml_config import MultiMCPConfig, ServerConfig, ToolEntry
from src.multimcp.cache_manager import merge_discovered_tools, get_enabled_tools

def _make_tool(name: str, description: str = "") -> types.Tool:
    return types.Tool(name=name, description=description, inputSchema={"type": "object", "properties": {}})

def test_new_tools_added_as_enabled():
    config = MultiMCPConfig(servers={"github": ServerConfig()})
    discovered = [_make_tool("search_repositories", "Search repos")]
    result = merge_discovered_tools(config, "github", discovered)
    assert result.servers["github"].tools["search_repositories"].enabled is True
    assert result.servers["github"].tools["search_repositories"].stale is False

def test_user_disabled_tool_preserved():
    config = MultiMCPConfig(servers={
        "github": ServerConfig(tools={"create_gist": ToolEntry(enabled=False)})
    })
    discovered = [_make_tool("create_gist")]
    result = merge_discovered_tools(config, "github", discovered)
    assert result.servers["github"].tools["create_gist"].enabled is False

def test_gone_tool_marked_stale():
    config = MultiMCPConfig(servers={
        "github": ServerConfig(tools={"old_tool": ToolEntry(enabled=True)})
    })
    discovered = [_make_tool("new_tool")]
    result = merge_discovered_tools(config, "github", discovered)
    assert result.servers["github"].tools["old_tool"].stale is True
    assert result.servers["github"].tools["old_tool"].enabled is True  # setting preserved

def test_returned_tool_clears_stale():
    config = MultiMCPConfig(servers={
        "github": ServerConfig(tools={"search_repositories": ToolEntry(enabled=True, stale=True)})
    })
    discovered = [_make_tool("search_repositories")]
    result = merge_discovered_tools(config, "github", discovered)
    assert result.servers["github"].tools["search_repositories"].stale is False

def test_description_updated_on_refresh():
    config = MultiMCPConfig(servers={
        "github": ServerConfig(tools={"search_repositories": ToolEntry(description="old")})
    })
    discovered = [_make_tool("search_repositories", "new description")]
    result = merge_discovered_tools(config, "github", discovered)
    assert result.servers["github"].tools["search_repositories"].description == "new description"

def test_get_enabled_tools_filters_disabled_and_stale():
    config = MultiMCPConfig(servers={
        "github": ServerConfig(tools={
            "good": ToolEntry(enabled=True, stale=False),
            "disabled": ToolEntry(enabled=False),
            "stale": ToolEntry(enabled=True, stale=True),
        })
    })
    enabled = get_enabled_tools(config, "github")
    assert enabled == {"good"}
```

### Step 2: Run to verify failure

```bash
uv run --project /home/tanner/Projects/multi-mcp python -m pytest tests/test_cache_manager.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.multimcp.cache_manager'`

### Step 3: Implement

```python
# src/multimcp/cache_manager.py
from __future__ import annotations
from typing import Set
from mcp import types
from src.multimcp.yaml_config import MultiMCPConfig, ToolEntry


def merge_discovered_tools(
    config: MultiMCPConfig,
    server_name: str,
    discovered: list[types.Tool],
) -> MultiMCPConfig:
    """Merge newly discovered tools into existing config.

    Rules:
    - New tool: add with enabled=True
    - Existing tool: preserve enabled, update description, clear stale
    - Tool gone from server: mark stale=True, preserve enabled
    """
    server = config.servers[server_name]
    discovered_names = {t.name for t in discovered}

    # Mark gone tools as stale
    for tool_name, entry in server.tools.items():
        if tool_name not in discovered_names:
            entry.stale = True

    # Add or update discovered tools
    for tool in discovered:
        if tool.name in server.tools:
            entry = server.tools[tool.name]
            entry.description = tool.description or ""
            entry.stale = False  # back from the dead
        else:
            server.tools[tool.name] = ToolEntry(
                enabled=True,
                stale=False,
                description=tool.description or "",
            )

    return config


def get_enabled_tools(config: MultiMCPConfig, server_name: str) -> Set[str]:
    """Return set of tool names that should be exposed for a server."""
    server = config.servers.get(server_name)
    if not server:
        return set()
    return {
        name for name, entry in server.tools.items()
        if entry.enabled and not entry.stale
    }
```

### Step 4: Run to verify passing

```bash
uv run --project /home/tanner/Projects/multi-mcp python -m pytest tests/test_cache_manager.py -v
```
Expected: `6 passed`

### Step 5: Commit

```bash
git add src/multimcp/cache_manager.py tests/test_cache_manager.py
git commit -m "feat: add cache manager with smart merge logic"
```

---

## Task 3: Startup Discovery-with-Disconnect

**Files:**
- Modify: `src/multimcp/mcp_client.py`
- Create: `tests/test_startup_discovery.py`

### Step 1: Write the failing tests

```python
# tests/test_startup_discovery.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from src.multimcp.mcp_client import MCPClientManager
from src.multimcp.yaml_config import MultiMCPConfig, ServerConfig

@pytest.mark.asyncio
async def test_discover_all_returns_tool_dict():
    """discover_all connects, fetches tools, disconnects, returns {server: [tools]}."""
    manager = MCPClientManager()

    mock_tool = MagicMock()
    mock_tool.name = "search_repositories"
    mock_tool.description = "Search repos"

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock(return_value=MagicMock(
        capabilities=MagicMock(tools=True, prompts=False, resources=False)
    ))
    mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[mock_tool]))

    config = MultiMCPConfig(servers={
        "github": ServerConfig(command="/fake/run-github.sh", always_on=False)
    })

    with patch.object(manager, "_create_single_client", new_callable=AsyncMock) as mock_create:
        async def fake_create(name, server_config):
            manager.clients[name] = mock_session
        mock_create.side_effect = fake_create

        results = await manager.discover_all(config)

    assert "github" in results
    assert results["github"][0].name == "search_repositories"

@pytest.mark.asyncio
async def test_discover_all_disconnects_lazy_servers():
    """After discovery, lazy servers are removed from clients dict."""
    manager = MCPClientManager()

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock(return_value=MagicMock(
        capabilities=MagicMock(tools=True, prompts=False, resources=False)
    ))
    mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))

    config = MultiMCPConfig(servers={
        "tavily": ServerConfig(command="/fake/run-tavily.sh", always_on=False)
    })

    with patch.object(manager, "_create_single_client", new_callable=AsyncMock) as mock_create:
        async def fake_create(name, server_config):
            manager.clients[name] = mock_session
        mock_create.side_effect = fake_create

        await manager.discover_all(config)

    assert "tavily" not in manager.clients

@pytest.mark.asyncio
async def test_discover_all_keeps_always_on_connected():
    """After discovery, always_on servers remain in clients dict."""
    manager = MCPClientManager()

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock(return_value=MagicMock(
        capabilities=MagicMock(tools=True, prompts=False, resources=False)
    ))
    mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))

    config = MultiMCPConfig(servers={
        "github": ServerConfig(command="/fake/run-github.sh", always_on=True)
    })

    with patch.object(manager, "_create_single_client", new_callable=AsyncMock) as mock_create:
        async def fake_create(name, server_config):
            manager.clients[name] = mock_session
        mock_create.side_effect = fake_create

        await manager.discover_all(config)

    assert "github" in manager.clients
```

### Step 2: Run to verify failure

```bash
uv run --project /home/tanner/Projects/multi-mcp python -m pytest tests/test_startup_discovery.py -v
```
Expected: `AttributeError: 'MCPClientManager' object has no attribute 'discover_all'`

### Step 3: Implement — add `discover_all` to `MCPClientManager`

Add this method to the `MCPClientManager` class in `src/multimcp/mcp_client.py`:

```python
async def discover_all(
    self, config: "MultiMCPConfig"
) -> dict[str, list]:
    """Connect to every server, fetch tool lists, disconnect lazy ones.

    Returns:
        Dict mapping server_name -> list[types.Tool]
    """
    from mcp import types  # avoid circular at module level

    await self.stack.__aenter__()
    results: dict[str, list] = {}

    for name, server_config in config.servers.items():
        try:
            server_dict = server_config.model_dump(exclude_none=True)
            await asyncio.wait_for(
                self._create_single_client(name, server_dict),
                timeout=self._connection_timeout,
            )
            client = self.clients.get(name)
            if not client:
                continue

            init_result = await client.initialize()
            tools: list[types.Tool] = []
            if init_result.capabilities.tools:
                tools_result = await client.list_tools()
                tools = tools_result.tools

            results[name] = tools

            # Disconnect lazy servers immediately after discovery
            if not server_config.always_on:
                del self.clients[name]
                self.logger.info(f"🔌 Discovered {len(tools)} tools from '{name}', disconnected (lazy)")
            else:
                self.logger.info(f"✅ Discovered {len(tools)} tools from '{name}', staying connected (always_on)")

        except Exception as e:
            self.logger.error(f"❌ Discovery failed for '{name}': {e}")
            results[name] = []

    return results
```

Also add the import at the top of the file (after existing imports):
```python
from src.multimcp.yaml_config import MultiMCPConfig  # type: ignore[assignment]
```

### Step 4: Run to verify passing

```bash
uv run --project /home/tanner/Projects/multi-mcp python -m pytest tests/test_startup_discovery.py -v
```
Expected: `3 passed`

### Step 5: Run full test suite to check nothing broke

```bash
uv run --project /home/tanner/Projects/multi-mcp python -m pytest -v
```
Expected: all existing tests still pass

### Step 6: Commit

```bash
git add src/multimcp/mcp_client.py tests/test_startup_discovery.py
git commit -m "feat: add startup discovery-with-disconnect to MCPClientManager"
```

---

## Task 4: Idle Timeout Auto-Disconnect

**Files:**
- Modify: `src/multimcp/mcp_client.py`
- Create: `tests/test_idle_timeout.py`

### Step 1: Write the failing tests

```python
# tests/test_idle_timeout.py
import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock
from src.multimcp.mcp_client import MCPClientManager

@pytest.mark.asyncio
async def test_record_usage_updates_timestamp():
    manager = MCPClientManager()
    before = time.monotonic()
    manager.record_usage("exa")
    after = time.monotonic()
    assert before <= manager.last_used["exa"] <= after

@pytest.mark.asyncio
async def test_idle_servers_are_disconnected():
    manager = MCPClientManager()
    mock_session = AsyncMock()
    manager.clients["tavily"] = mock_session
    manager.always_on_servers = set()
    manager.idle_timeouts["tavily"] = 0.01  # 10ms timeout for test
    manager.last_used["tavily"] = time.monotonic() - 1.0  # 1 second ago

    await manager._disconnect_idle_servers()

    assert "tavily" not in manager.clients

@pytest.mark.asyncio
async def test_always_on_servers_not_disconnected():
    manager = MCPClientManager()
    mock_session = AsyncMock()
    manager.clients["github"] = mock_session
    manager.always_on_servers = {"github"}
    manager.idle_timeouts["github"] = 0.01
    manager.last_used["github"] = time.monotonic() - 1.0

    await manager._disconnect_idle_servers()

    assert "github" in manager.clients

@pytest.mark.asyncio
async def test_recently_used_server_not_disconnected():
    manager = MCPClientManager()
    mock_session = AsyncMock()
    manager.clients["exa"] = mock_session
    manager.always_on_servers = set()
    manager.idle_timeouts["exa"] = 300  # 5 minutes
    manager.last_used["exa"] = time.monotonic()  # just used

    await manager._disconnect_idle_servers()

    assert "exa" in manager.clients
```

### Step 2: Run to verify failure

```bash
uv run --project /home/tanner/Projects/multi-mcp python -m pytest tests/test_idle_timeout.py -v
```
Expected: `AttributeError: 'MCPClientManager' object has no attribute 'record_usage'`

### Step 3: Implement — add idle timeout tracking to `MCPClientManager`

Add to `__init__` in `MCPClientManager`:

```python
import time

# In __init__, add:
self.always_on_servers: set[str] = set()
self.idle_timeouts: dict[str, float] = {}   # server_name -> seconds
self.last_used: dict[str, float] = {}        # server_name -> monotonic timestamp
```

Add these methods to `MCPClientManager`:

```python
def record_usage(self, server_name: str) -> None:
    """Update last-used timestamp for a server."""
    self.last_used[server_name] = time.monotonic()

async def _disconnect_idle_servers(self) -> None:
    """Disconnect lazy servers that have exceeded their idle timeout."""
    now = time.monotonic()
    to_disconnect = []
    for name in list(self.clients.keys()):
        if name in self.always_on_servers:
            continue
        last = self.last_used.get(name, 0)
        timeout = self.idle_timeouts.get(name, 300)
        if now - last > timeout:
            to_disconnect.append(name)

    for name in to_disconnect:
        self.logger.info(f"💤 Disconnecting idle server: {name}")
        del self.clients[name]

async def start_idle_checker(self, interval_seconds: float = 60.0) -> None:
    """Background task: periodically disconnect idle lazy servers."""
    while True:
        await asyncio.sleep(interval_seconds)
        await self._disconnect_idle_servers()
```

Also add `import time` at the top of `mcp_client.py`.

### Step 4: Run to verify passing

```bash
uv run --project /home/tanner/Projects/multi-mcp python -m pytest tests/test_idle_timeout.py -v
```
Expected: `4 passed`

### Step 5: Commit

```bash
git add src/multimcp/mcp_client.py tests/test_idle_timeout.py
git commit -m "feat: add idle timeout auto-disconnect to MCPClientManager"
```

---

## Task 5: Wire YAML into Proxy Startup

**Files:**
- Modify: `src/multimcp/multi_mcp.py`
- Modify: `src/multimcp/mcp_proxy.py`
- Create: `tests/test_startup_flow.py`

### Step 1: Write the failing tests

```python
# tests/test_startup_flow.py
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from src.multimcp.yaml_config import MultiMCPConfig, ServerConfig, ToolEntry, save_config
from src.multimcp.mcp_proxy import MCPProxyServer
from src.multimcp.mcp_client import MCPClientManager

@pytest.mark.asyncio
async def test_proxy_respects_disabled_tools_from_yaml():
    """Tools marked enabled=False in YAML are not exposed."""
    manager = MCPClientManager()
    manager.tool_filters["github"] = {"allow": ["search_repositories"], "deny": []}

    mock_tool_sr = MagicMock()
    mock_tool_sr.name = "search_repositories"
    mock_tool_sr.description = "Search"
    mock_tool_sr.model_copy = lambda: mock_tool_sr

    mock_tool_cg = MagicMock()
    mock_tool_cg.name = "create_gist"
    mock_tool_cg.description = "Create gist"
    mock_tool_cg.model_copy = lambda: mock_tool_cg

    mock_session = AsyncMock()
    mock_session.list_tools = AsyncMock(
        return_value=MagicMock(tools=[mock_tool_sr, mock_tool_cg])
    )
    manager.clients["github"] = mock_session

    proxy = MCPProxyServer(manager)
    tools = await proxy._initialize_tools_for_client("github", mock_session)

    tool_names = [t.name.split("::")[-1] for t in tools]
    assert "search_repositories" in tool_names
    assert "create_gist" not in tool_names
```

### Step 2: Run to verify failure

```bash
uv run --project /home/tanner/Projects/multi-mcp python -m pytest tests/test_startup_flow.py -v
```
Expected: fails due to mock issues — if it passes, the filter is already working from Task 4 in our earlier session.

### Step 3: Implement — update `MultiMCP.run()` startup sequence

In `src/multimcp/multi_mcp.py`, find the `run` method and update the startup sequence:

```python
# Add at top of file
from pathlib import Path
from src.multimcp.yaml_config import load_config, save_config, MultiMCPConfig
from src.multimcp.cache_manager import merge_discovered_tools, get_enabled_tools

# Default config path
YAML_CONFIG_PATH = Path.home() / ".config" / "multi-mcp" / "servers.yaml"
```

Replace the config-loading section in `MultiMCP.__init__` or `run()` with:

```python
async def _bootstrap_from_yaml(self, yaml_path: Path) -> MultiMCPConfig:
    """Load YAML or run first-time discovery and write it."""
    config = load_config(yaml_path)

    if not config.servers:
        # No YAML yet — load from legacy JSON config if provided
        self.logger.info("📋 No YAML config found, running first-time discovery...")
        config = await self._first_run_discovery(yaml_path)
    else:
        self.logger.info(f"✅ Loaded config from {yaml_path}")

    # Apply tool filters to client manager
    for server_name, server_config in config.servers.items():
        enabled = get_enabled_tools(config, server_name)
        if enabled:
            self.client_manager.tool_filters[server_name] = {
                "allow": list(enabled), "deny": []
            }
        # Register idle timeout and always_on
        self.client_manager.idle_timeouts[server_name] = (
            server_config.idle_timeout_minutes * 60
        )
        if server_config.always_on:
            self.client_manager.always_on_servers.add(server_name)

    return config

async def _first_run_discovery(self, yaml_path: Path) -> MultiMCPConfig:
    """Connect to all servers, discover tools, write YAML, disconnect lazy ones."""
    # Build MultiMCPConfig from existing JSON config for backward compat
    from src.multimcp.yaml_config import ServerConfig
    config = MultiMCPConfig()
    json_servers = self.settings.get("mcpServers", {})
    for name, srv in json_servers.items():
        config.servers[name] = ServerConfig(**{
            k: v for k, v in srv.items()
            if k in ServerConfig.model_fields
        })

    discovered = await self.client_manager.discover_all(config)
    for server_name, tools in discovered.items():
        merge_discovered_tools(config, server_name, tools)

    save_config(config, yaml_path)
    self.logger.info(f"💾 Wrote config to {yaml_path}")
    return config
```

### Step 4: Run to verify passing

```bash
uv run --project /home/tanner/Projects/multi-mcp python -m pytest tests/test_startup_flow.py -v
```
Expected: `1 passed`

### Step 5: Run full suite

```bash
uv run --project /home/tanner/Projects/multi-mcp python -m pytest -v
```
Expected: all tests pass

### Step 6: Commit

```bash
git add src/multimcp/multi_mcp.py tests/test_startup_flow.py
git commit -m "feat: wire YAML config into proxy startup sequence"
```

---

## Task 6: CLI Commands

**Files:**
- Create: `src/multimcp/cli.py`
- Modify: `main.py`
- Create: `tests/test_cli.py`

### Step 1: Write the failing tests

```python
# tests/test_cli.py
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, AsyncMock
from src.multimcp.yaml_config import MultiMCPConfig, ServerConfig, ToolEntry, save_config
from src.multimcp.cli import cmd_list, cmd_status, cmd_refresh

@pytest.mark.asyncio
async def test_cmd_list_shows_enabled_and_disabled():
    """cmd_list returns string with tool names and their status."""
    config = MultiMCPConfig(servers={
        "github": ServerConfig(tools={
            "search_repositories": ToolEntry(enabled=True),
            "delete_repository": ToolEntry(enabled=False),
            "old_tool": ToolEntry(enabled=True, stale=True),
        })
    })
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        path = Path(f.name)
    save_config(config, path)

    output = cmd_list(yaml_path=path)
    assert "search_repositories" in output
    assert "delete_repository" in output
    assert "✓" in output or "enabled" in output.lower()
    assert "✗" in output or "disabled" in output.lower()
    assert "stale" in output.lower()

def test_cmd_status_shows_server_counts():
    config = MultiMCPConfig(servers={
        "github": ServerConfig(always_on=True, tools={"t1": ToolEntry()}),
        "exa": ServerConfig(always_on=False, tools={"t2": ToolEntry(), "t3": ToolEntry(enabled=False)}),
    })
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        path = Path(f.name)
    save_config(config, path)

    output = cmd_status(yaml_path=path)
    assert "github" in output
    assert "exa" in output
    assert "always_on" in output.lower() or "always" in output.lower()
```

### Step 2: Run to verify failure

```bash
uv run --project /home/tanner/Projects/multi-mcp python -m pytest tests/test_cli.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.multimcp.cli'`

### Step 3: Implement `src/multimcp/cli.py`

```python
# src/multimcp/cli.py
from __future__ import annotations
from pathlib import Path
from src.multimcp.yaml_config import load_config, MultiMCPConfig
from src.multimcp.cache_manager import merge_discovered_tools
from src.utils.logger import get_logger

logger = get_logger("multi_mcp.cli")
DEFAULT_YAML = Path.home() / ".config" / "multi-mcp" / "servers.yaml"


def cmd_list(
    yaml_path: Path = DEFAULT_YAML,
    server_filter: str | None = None,
    disabled_only: bool = False,
) -> str:
    config = load_config(yaml_path)
    if not config.servers:
        return "No servers configured. Run: multi-mcp start (first run will discover servers)"

    lines = []
    for server_name, server_config in config.servers.items():
        if server_filter and server_name != server_filter:
            continue
        enabled_count = sum(1 for t in server_config.tools.values() if t.enabled and not t.stale)
        total = len(server_config.tools)
        lines.append(f"\n[{server_name}] ({enabled_count}/{total} tools enabled)")
        for tool_name, entry in sorted(server_config.tools.items()):
            if disabled_only and entry.enabled and not entry.stale:
                continue
            status = "✓" if entry.enabled and not entry.stale else "✗"
            stale = " [stale]" if entry.stale else ""
            lines.append(f"  {status} {tool_name}{stale}")

    return "\n".join(lines)


def cmd_status(yaml_path: Path = DEFAULT_YAML) -> str:
    config = load_config(yaml_path)
    if not config.servers:
        return "No servers configured."

    lines = ["Multi-MCP Server Status", "=" * 40]
    for server_name, server_config in config.servers.items():
        enabled = sum(1 for t in server_config.tools.values() if t.enabled and not t.stale)
        disabled = sum(1 for t in server_config.tools.values() if not t.enabled)
        stale = sum(1 for t in server_config.tools.values() if t.stale)
        mode = "always_on" if server_config.always_on else f"lazy ({server_config.idle_timeout_minutes}m timeout)"
        lines.append(f"\n{server_name}")
        lines.append(f"  Mode:     {mode}")
        lines.append(f"  Tools:    {enabled} enabled, {disabled} disabled, {stale} stale")
        if server_config.command:
            lines.append(f"  Command:  {server_config.command}")
        elif server_config.url:
            lines.append(f"  URL:      {server_config.url}")

    return "\n".join(lines)


async def cmd_refresh(
    server_filter: str | None = None,
    yaml_path: Path = DEFAULT_YAML,
) -> str:
    """Re-discover tools and smart-merge into YAML."""
    import asyncio
    from src.multimcp.mcp_client import MCPClientManager

    config = load_config(yaml_path)
    if not config.servers:
        return "No servers configured."

    manager = MCPClientManager()
    servers_to_refresh = (
        {server_filter: config.servers[server_filter]}
        if server_filter and server_filter in config.servers
        else config.servers
    )

    from src.multimcp.yaml_config import MultiMCPConfig, save_config
    partial = MultiMCPConfig(servers=servers_to_refresh)
    discovered = await manager.discover_all(partial)

    updated = 0
    for name, tools in discovered.items():
        merge_discovered_tools(config, name, tools)
        updated += len(tools)

    from src.multimcp.yaml_config import save_config
    save_config(config, yaml_path)
    return f"✅ Refreshed {len(discovered)} server(s), {updated} tools discovered. Saved to {yaml_path}"
```

### Step 4: Update `main.py` with subcommands

```python
# main.py (full replacement)
import asyncio
import argparse
from pathlib import Path
from src.multimcp.multi_mcp import MultiMCP
from src.multimcp.yaml_config import load_config
from src.multimcp.cli import cmd_list, cmd_status, cmd_refresh, DEFAULT_YAML


def parse_args():
    parser = argparse.ArgumentParser(description="Multi-MCP proxy server")
    sub = parser.add_subparsers(dest="command", required=True)

    # start
    start = sub.add_parser("start", help="Start the proxy server")
    start.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    start.add_argument("--host", type=str, default="127.0.0.1")
    start.add_argument("--port", type=int, default=8085)
    start.add_argument("--config", type=str, default=None,
                       help="Legacy JSON config (used only on first run if no YAML exists)")
    start.add_argument("--api-key", type=str, default=None)
    start.add_argument("--log-level",
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")

    # refresh
    refresh = sub.add_parser("refresh", help="Re-discover tools and update YAML")
    refresh.add_argument("server", nargs="?", help="Specific server to refresh")

    # status
    sub.add_parser("status", help="Show server and tool summary")

    # list
    lst = sub.add_parser("list", help="List all tools")
    lst.add_argument("--server", type=str, default=None)
    lst.add_argument("--disabled", action="store_true")

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.command == "start":
        server = MultiMCP(
            transport=args.transport,
            config=args.config or "./examples/config/mcp.json",
            host=args.host,
            port=args.port,
            log_level=args.log_level,
            api_key=args.api_key,
        )
        asyncio.run(server.run())

    elif args.command == "refresh":
        result = asyncio.run(cmd_refresh(server_filter=args.server))
        print(result)

    elif args.command == "status":
        print(cmd_status())

    elif args.command == "list":
        print(cmd_list(server_filter=args.server, disabled_only=args.disabled))
```

### Step 5: Run to verify tests pass

```bash
uv run --project /home/tanner/Projects/multi-mcp python -m pytest tests/test_cli.py -v
```
Expected: `2 passed`

### Step 6: Smoke test the CLI manually

```bash
cd /home/tanner/Projects/multi-mcp
uv run python main.py status
uv run python main.py list
```
Expected: "No servers configured" (no YAML yet — that's correct)

### Step 7: Run full suite

```bash
uv run --project /home/tanner/Projects/multi-mcp python -m pytest -v
```
Expected: all tests pass

### Step 8: Commit

```bash
git add src/multimcp/cli.py main.py tests/test_cli.py
git commit -m "feat: add CLI subcommands (start, refresh, status, list)"
```

---

## Task 7: Auto-Reconnect for Always-On Servers

**Files:**
- Modify: `src/multimcp/mcp_client.py`
- Modify: `src/multimcp/mcp_proxy.py`
- Create: `tests/test_reconnect.py`

### Step 1: Write the failing tests

```python
# tests/test_reconnect.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.multimcp.mcp_client import MCPClientManager
from src.multimcp.yaml_config import ServerConfig

@pytest.mark.asyncio
async def test_get_or_create_records_usage():
    """get_or_create_client records last_used timestamp."""
    import time
    manager = MCPClientManager()
    mock_session = AsyncMock()
    manager.clients["exa"] = mock_session

    before = time.monotonic()
    client = await manager.get_or_create_client("exa")
    after = time.monotonic()

    assert before <= manager.last_used["exa"] <= after
    assert client is mock_session
```

### Step 2: Run to verify failure

```bash
uv run --project /home/tanner/Projects/multi-mcp python -m pytest tests/test_reconnect.py -v
```
Expected: FAIL (record_usage not called in get_or_create_client)

### Step 3: Update `get_or_create_client` to record usage

In `src/multimcp/mcp_client.py`, add `self.record_usage(name)` after returning an existing client and after creating a new one from pending config:

```python
async def get_or_create_client(self, name: str) -> ClientSession:
    if name in self.clients:
        self.record_usage(name)          # ← add this
        return self.clients[name]

    if name in self.pending_configs:
        config = self.pending_configs.pop(name)
        async with self._connection_semaphore:
            try:
                await asyncio.wait_for(
                    self._create_single_client(name, config),
                    timeout=self._connection_timeout,
                )
            except asyncio.TimeoutError:
                self.logger.error(f"❌ Connection timeout for {name}")
                raise
        self.record_usage(name)          # ← add this
        return self.clients[name]

    raise KeyError(f"Unknown server: {name}")
```

### Step 4: Run to verify passing

```bash
uv run --project /home/tanner/Projects/multi-mcp python -m pytest tests/test_reconnect.py -v
```
Expected: `1 passed`

### Step 5: Run full suite

```bash
uv run --project /home/tanner/Projects/multi-mcp python -m pytest -v
```
Expected: all pass

### Step 6: Commit

```bash
git add src/multimcp/mcp_client.py tests/test_reconnect.py
git commit -m "feat: record usage timestamps in get_or_create_client"
```

---

## Task 8: Update AI Tool Configs to Point at Multi-MCP

**Files:**
- Modify: `~/.copilot/mcp-config.json`
- Modify: `~/.config/opencode/.mcp.json`
- Modify: `~/.gemini/antigravity/mcp_config.json`
- Modify: `~/.codex/config.toml`
- Modify: `~/.config/Claude/claude_desktop_config.json`
- Modify: `~/.gemini/settings.json`
- Modify: `~/.claude.json`

### Step 1: Verify multi-mcp starts cleanly in stdio mode

```bash
cd /home/tanner/Projects/multi-mcp
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}' | uv run python main.py start 2>/dev/null | head -5
```
Expected: JSON response with `protocolVersion`

### Step 2: Update all configs via script

```python
# Run this once: python /tmp/update_configs.py
import json
from pathlib import Path

MULTI_MCP_ENTRY_STDIO = {
    "type": "stdio",
    "command": "uv",
    "args": ["run", "--project", "/home/tanner/Projects/multi-mcp", "python", "main.py", "start"],
}

# Copilot
path = Path.home() / ".copilot/mcp-config.json"
d = json.loads(path.read_text())
d["mcpServers"] = {"multi-mcp": MULTI_MCP_ENTRY_STDIO}
path.write_text(json.dumps(d, indent=2))
print("✅ copilot")

# OpenCode .mcp.json
path = Path.home() / ".config/opencode/.mcp.json"
d = json.loads(path.read_text())
d["mcpServers"] = {"multi-mcp": {**MULTI_MCP_ENTRY_STDIO, "enabled": True}}
path.write_text(json.dumps(d, indent=4))
print("✅ opencode .mcp.json")

# Claude Desktop
path = Path.home() / ".config/Claude/claude_desktop_config.json"
d = json.loads(path.read_text())
d["mcpServers"] = {"multi-mcp": MULTI_MCP_ENTRY_STDIO}
path.write_text(json.dumps(d, indent=2))
print("✅ claude desktop")

print("\nDone. Restart each tool to pick up changes.")
```

```bash
python /tmp/update_configs.py
```

### Step 3: Update Claude Code (`~/.claude.json`) via python

```bash
python3 -c "
import json
from pathlib import Path

path = Path.home() / '.claude.json'
d = json.loads(path.read_text())
d['projects']['/home/tanner']['mcpServers'] = {
    'multi-mcp': {
        'type': 'stdio',
        'command': 'uv',
        'args': ['run', '--project', '/home/tanner/Projects/multi-mcp', 'python', 'main.py', 'start'],
        'env': {}
    }
}
path.write_text(json.dumps(d, indent=2))
print('✅ claude.json')
"
```

### Step 4: Update Codex config

```toml
# Add to ~/.codex/config.toml, replacing all individual mcp_servers entries:
[mcp_servers.multi-mcp]
command = 'uv'
args = ['run', '--project', '/home/tanner/Projects/multi-mcp', 'python', 'main.py', 'start']
```

### Step 5: Verify end-to-end

```bash
# Trigger first-run discovery
cd /home/tanner/Projects/multi-mcp
uv run python main.py refresh

# Check what was discovered
uv run python main.py status
uv run python main.py list
```
Expected: servers listed with tool counts, YAML written to `~/.config/multi-mcp/servers.yaml`

### Step 6: Commit

```bash
git add .
git commit -m "feat: complete multi-mcp redesign — YAML cache, lazy loading, CLI, all tools routed"
```

---

## Final Verification

```bash
# Full test suite
uv run --project /home/tanner/Projects/multi-mcp python -m pytest -v

# YAML config exists and looks right
cat ~/.config/multi-mcp/servers.yaml

# Status check
uv run --project /home/tanner/Projects/multi-mcp python main.py status

# List all tools with enabled/disabled
uv run --project /home/tanner/Projects/multi-mcp python main.py list
```

All tests pass. All tool configs point at multi-mcp. YAML is populated. Done.
