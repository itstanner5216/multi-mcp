"""
Root-level pytest configuration.

Adds backward-compatible context-manager and connect_to_server() support to
langchain-mcp-adapters >= 0.1.0, which removed these in that release.

In 0.2.x the constructor stores connections in self.connections dict and
get_tools() creates sessions on-the-fly from that dict.  The shim simply:
  1. Makes __aenter__/__aexit__ no-ops (return self / pass).
  2. Implements connect_to_server() by adding the entry to self.connections.

get_tools() then works exactly as intended by 0.2.x.
"""

from langchain_mcp_adapters.client import MultiServerMCPClient


async def _compat_aenter(self):
    return self


async def _compat_aexit(self, exc_type, exc_val, exc_tb):
    pass


async def _compat_connect_to_server(
    self,
    server_name: str,
    *,
    transport: str,
    url: str | None = None,
    command: str | None = None,
    args: list[str] | None = None,
    **kwargs,
) -> None:
    """Add a server connection (0.0.x compatibility shim).

    Stores the connection in self.connections so that get_tools() can
    retrieve tools from it using the 0.2.x session-per-call model.
    """
    connection: dict = {"transport": transport}
    if url is not None:
        connection["url"] = url
    if command is not None:
        connection["command"] = command
    if args is not None:
        connection["args"] = args
    connection.update(kwargs)
    self.connections[server_name] = connection  # type: ignore[index]


# Patch MultiServerMCPClient only if these methods are missing / raise NotImplementedError
if not hasattr(MultiServerMCPClient, "connect_to_server"):
    MultiServerMCPClient.connect_to_server = _compat_connect_to_server  # type: ignore[attr-defined]
    MultiServerMCPClient.__aenter__ = _compat_aenter  # type: ignore[attr-defined]
    MultiServerMCPClient.__aexit__ = _compat_aexit  # type: ignore[attr-defined]
else:
    # In case the methods exist but raise NotImplementedError (0.1.x transition)
    import inspect

    _orig_aenter = MultiServerMCPClient.__aenter__

    async def _safe_aenter(self):
        try:
            return await _orig_aenter(self)
        except NotImplementedError:
            return self

    _orig_aexit = MultiServerMCPClient.__aexit__

    async def _safe_aexit(self, exc_type, exc_val, exc_tb):
        try:
            return await _orig_aexit(self, exc_type, exc_val, exc_tb)
        except NotImplementedError:
            pass

    MultiServerMCPClient.__aenter__ = _safe_aenter  # type: ignore[attr-defined]
    MultiServerMCPClient.__aexit__ = _safe_aexit  # type: ignore[attr-defined]
    MultiServerMCPClient.connect_to_server = _compat_connect_to_server  # type: ignore[attr-defined]
