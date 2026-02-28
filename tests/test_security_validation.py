"""Tests for security validation: env vars, command allowlist, SSRF protection."""
import pytest
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
