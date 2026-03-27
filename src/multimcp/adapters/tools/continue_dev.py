"""Continue.dev MCP config adapter."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import yaml

from src.multimcp.adapters.base import MCPConfigAdapter


class ContinueDevAdapter(MCPConfigAdapter):
    """Adapter for the Continue.dev VS Code / JetBrains extension."""

    tool_name = "continue_dev"
    display_name = "Continue.dev"
    config_format = "yaml"
    supported_platforms = ["macos", "linux", "windows"]

    def _servers_dir(self) -> Path:
        """Return the directory that holds per-server YAML files."""
        return Path.home() / ".continue" / "mcpServers"

    def config_path(self) -> Optional[Path]:
        """Return the mcpServers directory path."""
        return self._servers_dir()

    def read_config(self) -> Dict:
        """Read all server YAML files, returning {} if the directory is absent."""
        servers_dir = self._servers_dir()
        if not servers_dir.exists():
            return {}
        result: Dict = {}
        for yaml_file in sorted(servers_dir.glob("*.yaml")):
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
            name = data.pop("name", yaml_file.stem)
            result[name] = data
        return result

    def write_config(self, data: Dict) -> None:
        """Write per-server YAML files for every entry in *data*."""
        servers_dir = self._servers_dir()
        servers_dir.mkdir(parents=True, exist_ok=True)
        for name, config in data.items():
            yaml_file = servers_dir / f"{name}.yaml"
            entry = {"name": name, **config}
            yaml_file.write_text(
                yaml.dump(entry, default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )

    def register_server(self, name: str, config: Dict) -> None:
        """Write or overwrite a single server YAML file."""
        servers_dir = self._servers_dir()
        servers_dir.mkdir(parents=True, exist_ok=True)
        yaml_file = servers_dir / f"{name}.yaml"
        entry = {"name": name, **config}
        yaml_file.write_text(
            yaml.dump(entry, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

    def discover_servers(self) -> Dict[str, Dict]:
        """Return a name→config mapping from all YAML files in the servers dir."""
        return self.read_config()
