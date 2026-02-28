"""Tests for security validation: env vars, command allowlist, SSRF protection."""
import os
import pytest
import unittest.mock as mock
from src.multimcp.mcp_client import _filter_env, _validate_command, _validate_url, PROTECTED_ENV_VARS


class TestEnvVarProtection:
    """Verify PROTECTED_ENV_VARS blocks all dangerous environment variables."""

    def test_blocks_node_options(self):
        """NODE_OPTIONS allows --require to execute arbitrary code in Node.js."""
        env = {"NODE_OPTIONS": "--require /tmp/evil.js", "SAFE_VAR": "ok"}
        filtered = _filter_env(env)
        assert "NODE_OPTIONS" not in filtered
        assert "SAFE_VAR" in filtered

    def test_blocks_node_path(self):
        """NODE_PATH redirects module resolution."""
        env = {"NODE_PATH": "/tmp/evil_modules"}
        filtered = _filter_env(env)
        assert "NODE_PATH" not in filtered

    def test_blocks_bash_env(self):
        """BASH_ENV is executed on non-interactive bash startup."""
        env = {"BASH_ENV": "/tmp/evil.sh"}
        filtered = _filter_env(env)
        assert "BASH_ENV" not in filtered

    def test_blocks_env(self):
        """ENV is executed on sh startup."""
        env = {"ENV": "/tmp/evil.sh"}
        filtered = _filter_env(env)
        assert "ENV" not in filtered

    def test_blocks_dyld_insert_libraries(self):
        """DYLD_INSERT_LIBRARIES is macOS equivalent of LD_PRELOAD."""
        env = {"DYLD_INSERT_LIBRARIES": "/tmp/evil.dylib"}
        filtered = _filter_env(env)
        assert "DYLD_INSERT_LIBRARIES" not in filtered

    def test_blocks_http_proxy(self):
        """http_proxy can redirect all HTTP traffic through attacker proxy."""
        env = {"http_proxy": "http://evil.com:8080", "https_proxy": "http://evil.com:8080"}
        filtered = _filter_env(env)
        assert "http_proxy" not in filtered
        assert "https_proxy" not in filtered

    def test_blocks_existing_protected_vars(self):
        """Verify all originally-protected vars are still blocked."""
        for var in ["PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "HOME", "USER", "PYTHONPATH", "PYTHONHOME"]:
            env = {var: "/malicious"}
            filtered = _filter_env(env)
            assert var not in filtered, f"{var} should be blocked"

    def test_allows_safe_vars(self):
        """Safe application vars should pass through."""
        env = {"API_KEY": "abc123", "DATABASE_URL": "postgres://...", "LOG_LEVEL": "DEBUG"}
        filtered = _filter_env(env)
        assert filtered == env


class TestCommandValidationSecurity:
    """Verify _validate_command rejects path traversal and unknown commands."""

    def test_allows_bare_allowed_command(self):
        """Bare command names in allowlist should pass."""
        # Should not raise
        _validate_command("node")
        _validate_command("npx")
        _validate_command("python")
        _validate_command("uv")

    def test_rejects_unknown_command(self):
        """Commands not in allowlist should be rejected."""
        with pytest.raises(ValueError, match="not in allowed"):
            _validate_command("malicious_binary")

    def test_allows_full_path_to_known_command(self):
        """Full paths to known commands should pass — basename is in allowlist."""
        # These all have basenames in the allowed list
        _validate_command("/tmp/node")  # basename 'node' is allowed
        _validate_command("/usr/bin/npx")  # basename 'npx' is allowed
        _validate_command("/home/user/.nvm/versions/node/v24/bin/npx")  # real-world nvm path
        _validate_command("../node")  # basename 'node' is allowed
        _validate_command("./local/python")  # basename 'python' is allowed

    def test_rejects_relative_unknown_command(self):
        """Relative paths to unknown commands should be rejected."""
        with pytest.raises(ValueError):
            _validate_command("subdir/evil_binary")

    def test_allows_full_path_to_allowed_basename(self):
        """Full paths with allowed basenames pass even with path separators."""
        _validate_command("/usr/bin/python")  # basename 'python' is allowed
        _validate_command("/usr/local/bin/node")  # basename 'node' is allowed

    def test_rejects_full_path_to_unknown_nonexistent_command(self):
        """Full paths to unknown basenames that don't exist on disk are rejected."""
        with pytest.raises(ValueError, match="not in allowed commands"):
            _validate_command("/tmp/evil_binary")

        with pytest.raises(ValueError, match="not in allowed commands"):
            _validate_command("/nonexistent/path/to/malware")

    def test_discover_stdio_calls_validate_command(self):
        """Verify _validate_command is invoked in the _discover_stdio code path.

        Uses unittest.mock.patch to intercept the _validate_command call made
        inside _discover_stdio when a command is present in the server dict.
        """
        import asyncio
        from unittest.mock import patch, AsyncMock, MagicMock
        from src.multimcp.mcp_client import MCPClientManager

        manager = MCPClientManager()
        server_dict = {"command": "/some/path/node", "args": [], "env": {}}

        # Patch _validate_command to verify it's called
        with patch("src.multimcp.mcp_client._validate_command") as mock_validate:
            server_config = MagicMock()
            server_config.always_on = False

            async def run():
                result = await manager._discover_stdio("test_server", server_dict, server_config)
                return result

            asyncio.run(run())
            mock_validate.assert_called_once_with("/some/path/node")

    def test_bash_and_sh_are_allowed(self):
        """bash and sh should be in DEFAULT_ALLOWED_COMMANDS for wrapper scripts."""
        _validate_command("bash")
        _validate_command("sh")
        _validate_command("/bin/bash")
        _validate_command("/bin/sh")
        _validate_command("/usr/bin/env bash"  .split()[0])  # just 'bash'

    def test_full_path_executable_file_allowed(self):
        """Full path to an executable file the user configured should pass,
        even if its basename isn't in the standard allowlist."""
        import tempfile
        import stat
        with tempfile.NamedTemporaryFile(suffix="_server.sh", delete=False) as f:
            f.write(b"#!/bin/bash\necho hello")
            f.flush()
            os.chmod(f.name, stat.S_IRWXU)
            try:
                _validate_command(f.name)  # Should pass — exists and is executable
            finally:
                os.unlink(f.name)

    def test_full_path_nonexecutable_file_rejected(self):
        """Full path to a non-executable file should be rejected."""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix="_notexec", delete=False) as f:
            f.write(b"not executable")
            f.flush()
            os.chmod(f.name, 0o644)  # Not executable
            try:
                with pytest.raises(ValueError):
                    _validate_command(f.name)
            finally:
                os.unlink(f.name)

    def test_error_message_includes_env_var_hint(self):
        """Error message should tell user how to extend the allowlist."""
        with pytest.raises(ValueError, match="MULTI_MCP_ALLOWED_COMMANDS"):
            _validate_command("custom_tool")

    def test_env_var_overrides_allowlist(self):
        """MULTI_MCP_ALLOWED_COMMANDS env var replaces (not extends) the default list."""
        os.environ["MULTI_MCP_ALLOWED_COMMANDS"] = "custom_tool,another_tool"
        try:
            _validate_command("custom_tool")
            _validate_command("another_tool")
            # Defaults should NOT work when env var is set (it replaces, not extends)
            with pytest.raises(ValueError):
                _validate_command("node")
        finally:
            del os.environ["MULTI_MCP_ALLOWED_COMMANDS"]


import pytest
import asyncio
from unittest.mock import patch, AsyncMock


class TestURLValidation:
    """Verify _validate_url SSRF protection and async-safety."""

    @pytest.mark.asyncio
    async def test_rejects_private_ip_127(self):
        """Must reject 127.0.0.1 direct IP."""
        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.getaddrinfo = AsyncMock(
                return_value=[(None, None, None, None, ("127.0.0.1", 0))]
            )
            with pytest.raises(ValueError, match="private|internal"):
                await _validate_url("http://127.0.0.1:8080/api")
            mock_loop.return_value.getaddrinfo.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejects_private_ip_localhost(self):
        """Must reject localhost (resolves to 127.x)."""
        # Mock loop.getaddrinfo to return loopback
        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.getaddrinfo = AsyncMock(
                return_value=[(None, None, None, None, ("127.0.0.1", 0))]
            )
            with pytest.raises(ValueError, match="private|internal"):
                await _validate_url("http://localhost:8080/api")
            mock_loop.return_value.getaddrinfo.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejects_link_local(self):
        """Must reject 169.254.x.x (link-local / cloud metadata)."""
        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.getaddrinfo = AsyncMock(
                return_value=[(None, None, None, None, ("169.254.169.254", 0))]
            )
            with pytest.raises(ValueError, match="private|internal"):
                await _validate_url("http://169.254.169.254/metadata")
            mock_loop.return_value.getaddrinfo.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejects_private_ranges(self):
        """Must reject 10.x.x.x, 172.16-31.x.x, 192.168.x.x."""
        for ip in ["10.0.0.1", "172.16.0.1", "192.168.1.1"]:
            with patch("asyncio.get_running_loop") as mock_loop:
                mock_loop.return_value.getaddrinfo = AsyncMock(
                    return_value=[(None, None, None, None, (ip, 0))]
                )
                with pytest.raises(ValueError, match="private|internal"):
                    await _validate_url(f"http://{ip}:8080/api")
                assert mock_loop.return_value.getaddrinfo.await_count > 0

    @pytest.mark.asyncio
    async def test_allows_public_ip(self):
        """Public IPs should pass validation."""
        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.getaddrinfo = AsyncMock(
                return_value=[(None, None, None, None, ("8.8.8.8", 0))]
            )
            # Should not raise
            await _validate_url("http://example.com:8080/api")
            mock_loop.return_value.getaddrinfo.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejects_non_http_scheme(self):
        """Must reject non-http(s) schemes."""
        with pytest.raises(ValueError):
            await _validate_url("ftp://example.com/file")
        with pytest.raises(ValueError):
            await _validate_url("file:///etc/passwd")


class TestSSRFEdgeCases:
    """Edge cases for SSRF protection."""

    @pytest.mark.asyncio
    async def test_rejects_ipv6_loopback(self):
        """IPv6 loopback ::1 must be rejected."""
        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.getaddrinfo = AsyncMock(
                return_value=[(None, None, None, None, ("::1", 0))]
            )
            with pytest.raises(ValueError, match="private|internal"):
                await _validate_url("http://[::1]:8080/api")
            mock_loop.return_value.getaddrinfo.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejects_zero_ip(self):
        """0.0.0.0 must be rejected."""
        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.getaddrinfo = AsyncMock(
                return_value=[(None, None, None, None, ("0.0.0.0", 0))]
            )
            with pytest.raises(ValueError, match="private|internal"):
                await _validate_url("http://0.0.0.0:8080/api")

    @pytest.mark.asyncio
    async def test_rejects_empty_hostname(self):
        """Empty hostname must raise ValueError before DNS resolution."""
        with pytest.raises(ValueError):
            await _validate_url("http://:8080/api")

    @pytest.mark.asyncio
    async def test_rejects_fc00_ipv6_ula(self):
        """IPv6 ULA (fc00::/7, e.g., fd00::1) must be rejected."""
        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.getaddrinfo = AsyncMock(
                return_value=[(None, None, None, None, ("fd00::1", 0))]
            )
            with pytest.raises(ValueError, match="private|internal"):
                await _validate_url("http://[fd00::1]:8080/api")
            mock_loop.return_value.getaddrinfo.assert_awaited_once()
