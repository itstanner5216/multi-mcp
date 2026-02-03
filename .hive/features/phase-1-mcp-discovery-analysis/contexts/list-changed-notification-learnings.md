# tools/list_changed Notification Implementation Learnings

## Date: 2026-02-03
## Task: 07-fix-list-changed-notification

## Implementation Summary

Implemented MCP `notifications/tools/list_changed` emission when backend servers are dynamically added or removed from the multi-mcp proxy.

## Problem Statement

The MCP protocol specifies that servers should emit `notifications/tools/list_changed` when their tool list changes. For the multi-mcp proxy, this notification needs to be sent when:
- A backend server with tools capability is added (register_client)
- A backend server with tools capability is removed (unregister_client)

## Key Challenges

### Challenge 1: Accessing ServerSession Outside Request Context

**Problem:** The MCP Server class provides `request_context` property, but it only works inside request handlers (raises `LookupError` otherwise). The `register_client()` and `unregister_client()` methods are called outside of request contexts.

**Solution:** Store a reference to the `ServerSession` when the server starts running:
- Override the `run()` method
- Capture the `ServerSession` instance and store in `self._server_session`
- Use this reference to send notifications
- Clear the reference when the server shuts down

### Challenge 2: Sending Notifications

**Problem:** How to properly send the `tools/list_changed` notification?

**Solution:** The `ServerSession` class provides `send_tool_list_changed()` method:
```python
async def send_tool_list_changed(self) -> None:
    """Send a tool list changed notification."""
    await self.send_notification(
        types.ServerNotification(
            types.ToolListChangedNotification(
                method="notifications/tools/list_changed",
            )
        )
    )
```

## Implementation Details

### 1. Added ServerSession Storage

**Location:** `src/multimcp/mcp_proxy.py` __init__

```python
from mcp.server.session import ServerSession

# In __init__
self._server_session: Optional[ServerSession] = None
```

### 2. Override run() Method

**Purpose:** Capture the session reference during server operation

```python
async def run(
    self,
    read_stream,
    write_stream,
    initialization_options,
    raise_exceptions: bool = False,
):
    """Override run to capture the server session for notifications."""
    from mcp.server.session import ServerSession
    from contextlib import AsyncExitStack
    import anyio
    
    async with AsyncExitStack() as stack:
        lifespan_context = await stack.enter_async_context(self.lifespan(self))
        session = await stack.enter_async_context(
            ServerSession(read_stream, write_stream, initialization_options)
        )
        
        # Store session reference
        self._server_session = session
        self.logger.debug("🔗 Server session stored for notifications")
        
        # Run message handling loop
        async with anyio.create_task_group() as tg:
            async for message in session.incoming_messages:
                self.logger.debug(f"Received message: {message}")
                
                tg.start_soon(
                    self._handle_message,
                    message,
                    session,
                    lifespan_context,
                    raise_exceptions,
                )
        
        # Clear session when done
        self._server_session = None
```

### 3. Added Notification Sending Method

```python
async def _send_tools_list_changed(self) -> None:
    """Send tools/list_changed notification if a session is active."""
    if self._server_session:
        try:
            await self._server_session.send_tool_list_changed()
            self.logger.info("📢 Sent tools/list_changed notification")
        except Exception as e:
            self.logger.error(f"❌ Failed to send tools/list_changed notification: {e}")
    else:
        self.logger.debug("⚠️ No active session to send tools/list_changed notification")
```

### 4. Integration with register_client()

**Location:** `src/multimcp/mcp_proxy.py` line ~98

```python
async def register_client(self, name: str, client: ClientSession) -> None:
    """Add a new client and register its capabilities."""
    async with self._register_lock:
        self.client_manager.clients[name] = client
        await self.initialize_single_client(name, client)
        
        # Send notification if server has tools capability
        caps = self.capabilities.get(name)
        if caps and caps.tools:
            await self._send_tools_list_changed()
```

### 5. Integration with unregister_client()

**Location:** `src/multimcp/mcp_proxy.py` line ~105

```python
async def unregister_client(self, name: str) -> None:
    """Remove a client and clean up all its associated mappings."""
    async with self._register_lock:
        client = self.client_manager.clients.get(name)
        if not client:
            self.logger.warning(f"⚠️ Tried to unregister unknown client: {name}")
            return

        # Check if client had tools capability before removing
        caps = self.capabilities.get(name)
        had_tools = caps and caps.tools if caps else False

        self.logger.info(f"🗑️ Unregistering client: {name}")
        # ... removal logic ...
        
        # Send notification if client had tools capability
        if had_tools:
            await self._send_tools_list_changed()
```

## Test Coverage

### New Test File: tests/test_list_changed_notification.py (3 tests)

**Test 1: Register sends notification**
- Registers a server with tools capability
- Verifies `_send_tools_list_changed()` is called

**Test 2: Unregister sends notification**
- Registers then unregisters a server with tools capability
- Verifies notification sent on unregister

**Test 3: No notification for servers without tools**
- Registers a server with only prompts capability (no tools)
- Verifies notification is NOT sent

**All tests pass:** ✅ 3/3

**No regressions:** ✅ 3/3 existing proxy tests still pass

## Design Decisions

### 1. Why Store ServerSession Reference?

**Choice:** Store `self._server_session` in proxy

**Reasons:**
- `request_context` only works inside request handlers
- `register/unregister_client` called outside request context
- Need persistent reference to send notifications
- Safely cleared when server shuts down

**Alternative Considered:** Use `request_context` everywhere - rejected because it's not available outside request handlers

### 2. Why Check Tools Capability?

**Choice:** Only send notification when tools capability affected

**Reasons:**
- Notification is specifically `tools/list_changed`
- Adding server with only prompts/resources doesn't affect tools
- Reduces unnecessary notifications
- Follows principle of least surprise

**Alternative Considered:** Always send notification on any server change - rejected as too noisy

### 3. Why Override run() Method?

**Choice:** Override `run()` to capture session

**Reasons:**
- Session is created inside `run()` and passed to handlers
- No other way to get session reference outside request handlers
- Allows us to maintain the reference for the server's lifetime
- Clean integration point

**Alternative Considered:** Pass session through constructor - rejected because session doesn't exist until server runs

### 4. Graceful Handling When No Session

**Choice:** Log debug message but don't raise exception

**Reasons:**
- Server might not be running yet (initialization phase)
- Prevents crashes during testing
- Notifications are "best effort" - missing one isn't fatal
- Proper logging helps debugging

## Verification Checklist

✅ Tests written following TDD (RED → GREEN → REFACTOR)
✅ All 3 new tests passing
✅ No regressions (3/3 existing proxy tests pass)
✅ Notification sent when server with tools added
✅ Notification sent when server with tools removed
✅ No notification for servers without tools capability
✅ Graceful handling when session not available
✅ Code committed to task branch (96bc22d)

## Integration Pattern

```python
# When dynamically adding a server
await proxy.register_client(server_name, client_session)
# → Notification automatically sent if server has tools

# When dynamically removing a server
await proxy.unregister_client(server_name)
# → Notification automatically sent if server had tools

# Clients listening to notifications will receive:
# {
#   "jsonrpc": "2.0",
#   "method": "notifications/tools/list_changed"
# }
```

## MCP Protocol Details

### Notification Format

**Method:** `notifications/tools/list_changed`

**Purpose:** Informs clients that the list of available tools has changed

**When to Send:**
- Tools added
- Tools removed
- Tool definitions modified

**Client Response:**
- Client should call `tools/list` again to get updated tool list

### Related MCP Methods

- `notifications/prompts/list_changed` - For prompt changes
- `notifications/resources/list_changed` - For resource changes
- These follow the same pattern and could be implemented similarly

## Known Limitations

1. **Single Session Support:** Currently assumes one active session. Multiple concurrent sessions would need a list of sessions.

2. **No Buffering:** Notifications sent immediately. High-frequency changes could cause notification spam.

3. **Best Effort:** If session isn't available, notification is skipped with debug log.

## Future Enhancements

1. **Multi-Session Support:** Store list of active sessions, send to all

2. **Notification Coalescing:** Buffer rapid changes, send single notification

3. **Prompt/Resource Notifications:** Extend pattern to `prompts/list_changed` and `resources/list_changed`

4. **Notification History:** Track sent notifications for debugging

5. **Client Capability Check:** Only send if client supports notifications (check capabilities)

## Files Modified

1. `src/multimcp/mcp_proxy.py` - Added session storage, notification sending, run() override
2. `tests/test_list_changed_notification.py` - New comprehensive test suite

## Related Tasks

- **Task 05**: Deferred backend init - register_client called for lazy-loaded servers
- **Task 06**: Server-level visibility - this notification informs clients of visibility changes
- **Task 07**: Keyword triggers - auto-enabled servers trigger this notification

## MCP Spec References

- MCP Protocol Specification v1.0 - Notifications section
- `notifications/tools/list_changed` - Tool list change notification
- ServerSession API - `send_tool_list_changed()` method
