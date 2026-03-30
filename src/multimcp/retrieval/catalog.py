"""Immutable versioned tool catalog snapshots.

build_snapshot() converts the live tool_to_server registry into a
ToolCatalogSnapshot with a stable schema_hash. The hash is SHA-256 of a
sorted canonical JSON representation — identical registries always produce
the same hash; any schema change produces a new hash.

retrieval_aliases is left empty here — populated by BMXFRetriever._generate_aliases()
when it builds the field index. The catalog snapshot is schema-only; alias
generation is scorer-side logic.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import time
from typing import TYPE_CHECKING

from .models import ToolCatalogSnapshot, ToolDoc

if TYPE_CHECKING:
    from src.multimcp.mcp_proxy import ToolMapping

_version_counter = itertools.count(1)


def _extract_param_names(input_schema: object) -> list[str]:
    """Extract property keys from a tool's inputSchema dict.

    Returns sorted list for deterministic hashing. Returns empty list if
    schema is None, not a dict, or has no 'properties'.
    """
    if not isinstance(input_schema, dict):
        return []
    props = input_schema.get("properties", {})
    if not isinstance(props, dict):
        return []
    return sorted(props.keys())


def build_snapshot(registry: "dict[str, ToolMapping]") -> ToolCatalogSnapshot:
    """Build an immutable catalog snapshot from the live tool_to_server registry.

    Sorted by tool_key so hash is stable regardless of dict insertion order.
    schema_hash is SHA-256 of the sorted canonical JSON encoding of
    (tool_key, description, parameter_names) for each doc.

    Args:
        registry: MCPProxyServer.tool_to_server dict mapping tool_key -> ToolMapping.

    Returns:
        ToolCatalogSnapshot with incrementing version, stable schema_hash, and
        one ToolDoc per registry entry.
    """
    version_num = next(_version_counter)

    docs: list[ToolDoc] = []
    for key, mapping in sorted(registry.items()):
        ns, name = key.split("__", 1) if "__" in key else ("", key)
        param_names = _extract_param_names(mapping.tool.inputSchema)
        docs.append(ToolDoc(
            tool_key=key,
            tool_name=name,
            namespace=ns,
            description=mapping.tool.description or "",
            parameter_names=" ".join(param_names),
            retrieval_aliases="",   # Populated by BMXFRetriever._generate_aliases()
        ))

    # Canonical JSON: sorted by tool_key (already sorted above), deterministic keys
    canonical = json.dumps(
        [
            {"k": d.tool_key, "d": d.description, "p": d.parameter_names}
            for d in docs
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    schema_hash = hashlib.sha256(canonical.encode()).hexdigest()

    return ToolCatalogSnapshot(
        version=str(version_num),
        schema_hash=schema_hash,
        built_at=time.time(),
        docs=docs,
    )
