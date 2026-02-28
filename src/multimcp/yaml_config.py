from __future__ import annotations
from pathlib import Path
from typing import Literal, Optional
import yaml
from pydantic import BaseModel, Field, ValidationError
from src.utils.logger import get_logger

logger = get_logger("multi_mcp.config")


class ToolEntry(BaseModel):
    enabled: bool = True
    stale: bool = False
    description: str = ""


class ServerConfig(BaseModel):
    command: Optional[str] = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: Optional[str] = None
    type: Literal["stdio", "sse", "http", "streamablehttp"] = "stdio"
    always_on: bool = False
    idle_timeout_minutes: int = 5
    tools: dict[str, ToolEntry] = Field(default_factory=dict)
    triggers: list[str] = Field(default_factory=list)


class MultiMCPConfig(BaseModel):
    servers: dict[str, ServerConfig] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)


def load_config(path: Path) -> MultiMCPConfig:
    """Load YAML config from path. Returns empty config if file doesn't exist or is invalid."""
    if not path.exists():
        return MultiMCPConfig()
    try:
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        return MultiMCPConfig.model_validate(raw)
    except yaml.YAMLError as e:
        logger.error(f"❌ Invalid YAML in {path}: {e}")
        return MultiMCPConfig()
    except (ValidationError, TypeError, ValueError) as e:
        logger.error(f"❌ Invalid config schema at {path}: {e}")
        return MultiMCPConfig()
    except Exception as e:
        logger.error(f"❌ Unexpected error loading config from {path}: {e}")
        return MultiMCPConfig()


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
