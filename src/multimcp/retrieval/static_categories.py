"""Static category defaults for Tier 4 fallback.

When no scorer is available but project type is confidently guessed,
these provide a curated tool selection per workspace type.
Source: docs/PHASE2-SYNTHESIZED-PLAN.md lines 901-918.
"""

STATIC_CATEGORIES: dict[str, dict[str, list[str]]] = {
    "node_web": {
        "always": ["filesystem", "shell", "web_search"],
        "likely": ["github", "npm", "docker", "jest"],
    },
    "python_web": {
        "always": ["filesystem", "shell", "web_search"],
        "likely": ["github", "pip", "docker", "pytest"],
    },
    "rust_cli": {
        "always": ["filesystem", "shell", "web_search"],
        "likely": ["github", "cargo"],
    },
    "infrastructure": {
        "always": ["filesystem", "shell", "web_search"],
        "likely": ["terraform", "kubectl", "docker", "helm"],
    },
    "generic": {
        "always": ["filesystem", "shell", "web_search", "github"],
    },
}

TIER6_NAMESPACE_PRIORITY: list[str] = [
    "filesystem", "shell", "web_search", "github",
    "docker", "npm", "pip", "cargo",
    "kubectl", "terraform", "slack", "context7",
]
"""Tier 6: namespace priority order for universal 12-tool fallback set."""
