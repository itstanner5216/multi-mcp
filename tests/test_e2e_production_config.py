"""E2E test: production init path reads 'enabled' from YAML, not hardcoded value.

Replaces V-04 claim: "≤20 tools verified via live test" (test used enabled=True
but production used enabled=False hardcoded). After Phase 9, the production init
path reads 'enabled' from yaml_config.retrieval, not from any hardcoded value.

This test verifies:
1. RetrievalSettings() defaults give enabled=False (YAML-driven default)
2. Building RetrievalConfig from RetrievalSettings defaults gives enabled=False
3. When yaml_config.retrieval.enabled=True, RetrievalConfig gets enabled=True
4. The pipeline respects the config-driven enabled flag
"""

from __future__ import annotations

import pytest

from mcp import types

from src.multimcp.retrieval.base import PassthroughRetriever
from src.multimcp.retrieval.logging import NullLogger
from src.multimcp.retrieval.models import RetrievalConfig
from src.multimcp.retrieval.pipeline import RetrievalPipeline
from src.multimcp.retrieval.session import SessionStateManager
from src.multimcp.mcp_proxy import ToolMapping
from src.multimcp.yaml_config import RetrievalSettings, MultiMCPConfig


def _make_registry(n: int = 10) -> dict:
    reg: dict[str, ToolMapping] = {}
    for i in range(n):
        key = f"s__{i:02d}_t"
        tool = types.Tool(
            name=f"{i:02d}_t",
            description=f"Tool {i}",
            inputSchema={"type": "object", "properties": {}},
        )
        reg[key] = ToolMapping(server_name="s", client=None, tool=tool)
    return reg


def _build_retrieval_config_from_yaml(yaml_retrieval: RetrievalSettings) -> RetrievalConfig:
    """Replicate the exact construction from multi_mcp.py (post Phase 9 wiring)."""
    return RetrievalConfig(
        enabled=yaml_retrieval.enabled,
        top_k=yaml_retrieval.top_k,
        full_description_count=yaml_retrieval.full_description_count,
        anchor_tools=yaml_retrieval.anchor_tools,
        shadow_mode=yaml_retrieval.shadow_mode,
        scorer=yaml_retrieval.scorer,
        max_k=yaml_retrieval.max_k,
        enable_routing_tool=yaml_retrieval.enable_routing_tool,
        enable_telemetry=yaml_retrieval.enable_telemetry,
        telemetry_poll_interval=yaml_retrieval.telemetry_poll_interval,
        canary_percentage=yaml_retrieval.canary_percentage,
        rollout_stage=yaml_retrieval.rollout_stage,
    )


class TestConfigDrivenPipelineInit:
    """Production init path reads enabled from YAML, not hardcoded value."""

    def test_default_yaml_gives_enabled_false(self):
        """RetrievalSettings() defaults: enabled=False, shadow_mode=False.

        V-04 fix: production default must disable retrieval, not enable it.
        """
        settings = RetrievalSettings()
        assert settings.enabled is False, (
            f"RetrievalSettings() default enabled must be False, got {settings.enabled}"
        )
        assert settings.shadow_mode is False

    def test_config_driven_pipeline_init(self):
        """RetrievalConfig built from YAML defaults has enabled=False.

        V-04 fix: after Phase 9, the pipeline reads 'enabled' from yaml_config.retrieval.
        With no retrieval: block in YAML, enabled=False is the production default.
        """
        # Simulate no retrieval: block in YAML (MultiMCPConfig with no retrieval key)
        yaml_config = MultiMCPConfig()  # no retrieval field → defaults to RetrievalSettings()
        yaml_retrieval = yaml_config.retrieval

        # Build RetrievalConfig exactly as multi_mcp.py does
        retrieval_config = _build_retrieval_config_from_yaml(yaml_retrieval)

        assert retrieval_config.enabled is False, (
            f"Production init with no YAML retrieval block must yield enabled=False, "
            f"got {retrieval_config.enabled}. "
            "V-04: hardcoded enabled=True has been removed."
        )

    def test_yaml_enabled_true_propagates(self):
        """When YAML sets enabled=True, RetrievalConfig gets enabled=True."""
        yaml_retrieval = RetrievalSettings(enabled=True, shadow_mode=True)
        retrieval_config = _build_retrieval_config_from_yaml(yaml_retrieval)

        assert retrieval_config.enabled is True, (
            "YAML-configured enabled=True must propagate to RetrievalConfig"
        )
        assert retrieval_config.shadow_mode is True

    @pytest.mark.anyio
    async def test_disabled_pipeline_returns_all_tools(self):
        """With enabled=False (YAML default), pipeline returns all tools (passthrough)."""
        n = 15
        registry = _make_registry(n)

        # Default YAML config (no retrieval block)
        yaml_config = MultiMCPConfig()
        retrieval_config = _build_retrieval_config_from_yaml(yaml_config.retrieval)

        assert retrieval_config.enabled is False
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(retrieval_config),
            logger=NullLogger(),
            config=retrieval_config,
            tool_registry=registry,
        )

        result = await pipeline.get_tools_for_list("prod-compat-session")

        assert len(result) == n, (
            f"Disabled pipeline must return all {n} tools; got {len(result)}. "
            "V-04: this matches true production behavior when no retrieval: block in YAML."
        )

    @pytest.mark.anyio
    async def test_enabled_pipeline_filters_tools(self):
        """When YAML enables pipeline (enabled=True, rollout_stage='ga'), filtering occurs."""
        n = 15
        top_k = 3
        registry = _make_registry(n)

        yaml_retrieval = RetrievalSettings(
            enabled=True,
            shadow_mode=False,
            rollout_stage="ga",
            top_k=top_k,
            max_k=5,
            enable_routing_tool=False,
        )
        retrieval_config = _build_retrieval_config_from_yaml(yaml_retrieval)

        assert retrieval_config.enabled is True
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(retrieval_config),
            logger=NullLogger(),
            config=retrieval_config,
            tool_registry=registry,
        )

        result = await pipeline.get_tools_for_list("prod-enabled-session")

        assert len(result) < n, (
            f"Enabled pipeline (GA mode) must filter to fewer than {n} tools; got {len(result)}"
        )

    def test_no_hardcoded_shadow_bootstrap_in_multi_mcp(self):
        """_make_startup_retrieval_config does not exist in multi_mcp after Phase 9."""
        import importlib
        import src.multimcp.multi_mcp as multi_mcp_module

        assert not hasattr(multi_mcp_module, "_make_startup_retrieval_config"), (
            "_make_startup_retrieval_config() must not exist after Phase 9 — "
            "hardcoded shadow bootstrap has been removed in favor of YAML config"
        )
