"""Signal -> typed sparse token generation for telemetry scanner."""
from __future__ import annotations

import re
from typing import Optional

TOKEN_WEIGHTS: dict[str, float] = {
    "manifest:": 3.0,
    "lock:": 2.5,
    "framework:": 2.5,
    "lang:": 2.0,
    "ci:": 1.5,
    "container:": 1.5,
    "infra:": 1.5,
    "db:": 1.5,
    "vcs:": 1.0,
    "layout:": 0.75,
    "readme:": 0.5,
}

MANIFEST_LANGUAGE_MAP: dict[str, list[str]] = {
    "package.json": ["javascript", "typescript", "npm", "node"],
    "Cargo.toml": ["rust", "cargo", "crate"],
    "pyproject.toml": ["python", "pip", "pypi"],
    "go.mod": ["golang", "go"],
    "pom.xml": ["java", "maven"],
    "build.gradle": ["java", "kotlin", "gradle"],
    "Gemfile": ["ruby", "gem", "bundler"],
    "composer.json": ["php", "composer"],
}

LOCKFILE_NAMES: set[str] = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "go.sum",
    "Gemfile.lock",
}

CI_PATTERN_MAP: dict[str, str] = {
    ".github/workflows": "github-actions",
    ".gitlab-ci.yml": "gitlab-ci",
    "Jenkinsfile": "jenkins",
    ".circleci": "circleci",
    ".travis.yml": "travis",
    "azure-pipelines.yml": "azure-pipelines",
    "Makefile": "make",
}

CONTAINER_FILES: set[str] = {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"}
INFRA_FILES: set[str] = {"terraform.tf", "main.tf", "variables.tf", "cloudformation.yaml"}
DB_FILES: set[str] = {"schema.prisma", "schema.sql", "migrations", "alembic.ini"}

MAX_FAMILY_CONTRIBUTION: float = 0.35  # No single family > 35% of total token weight sum
MAX_README_TOKENS: int = 20            # Cap readme-derived tokens


def build_tokens(
    found_files: set[str],
    readme_lines: Optional[list[str]] = None,
) -> dict[str, float]:
    """Convert found allowlisted files to typed sparse tokens with abuse resistance.

    Args:
        found_files: Set of relative filenames/paths found in root scan.
        readme_lines: Up to 40 lines from README (if found and allowed).

    Returns:
        Dict of token -> weight. Token format: "family:value".
    """
    raw: dict[str, float] = {}

    # Manifests
    for filename in found_files:
        basename = filename.split("/")[-1]
        if basename in MANIFEST_LANGUAGE_MAP:
            raw[f"manifest:{basename}"] = TOKEN_WEIGHTS["manifest:"]
            for lang in MANIFEST_LANGUAGE_MAP[basename]:
                raw[f"lang:{lang}"] = TOKEN_WEIGHTS["lang:"]

    # Lockfiles
    for filename in found_files:
        basename = filename.split("/")[-1]
        if basename in LOCKFILE_NAMES:
            raw[f"lock:{basename}"] = TOKEN_WEIGHTS["lock:"]

    # CI/CD
    for pattern, ci_name in CI_PATTERN_MAP.items():
        for f in found_files:
            if pattern in f:
                raw[f"ci:{ci_name}"] = TOKEN_WEIGHTS["ci:"]
                break

    # Containers
    for f in found_files:
        basename = f.split("/")[-1]
        if basename in CONTAINER_FILES:
            raw[f"container:{basename}"] = TOKEN_WEIGHTS["container:"]

    # Infra
    for f in found_files:
        basename = f.split("/")[-1]
        if basename in INFRA_FILES:
            raw[f"infra:{basename}"] = TOKEN_WEIGHTS["infra:"]

    # DB
    for f in found_files:
        basename = f.split("/")[-1]
        if basename in DB_FILES:
            raw[f"db:{basename}"] = TOKEN_WEIGHTS["db:"]

    # README tokens (capped)
    if readme_lines:
        readme_tokens = _extract_readme_tokens(readme_lines)
        for tok in list(readme_tokens.keys())[:MAX_README_TOKENS]:
            raw[f"readme:{tok}"] = TOKEN_WEIGHTS["readme:"]

    return _apply_family_cap(raw)


def _extract_readme_tokens(lines: list[str]) -> dict[str, float]:
    """Extract keyword tokens from README lines (tech-stack words only)."""
    TECH_WORDS = re.compile(
        r"\b(docker|kubernetes|k8s|postgres|mysql|redis|mongodb|react|vue|angular"
        r"|django|flask|fastapi|rails|spring|rust|golang|typescript|python|node)\b",
        re.IGNORECASE,
    )
    found: dict[str, float] = {}
    for line in lines:
        for match in TECH_WORDS.finditer(line):
            word = match.group(0).lower()
            found[word] = 1.0
    return found


def _apply_family_cap(tokens: dict[str, float]) -> dict[str, float]:
    """Ensure no token family exceeds MAX_FAMILY_CONTRIBUTION of total weight."""
    if not tokens:
        return tokens

    total = sum(tokens.values())
    if total == 0:
        return tokens

    # Group by family prefix (before ":")
    families: dict[str, list[tuple[str, float]]] = {}
    for tok, w in tokens.items():
        family = tok.split(":")[0] + ":"
        families.setdefault(family, []).append((tok, w))

    max_per_family = total * MAX_FAMILY_CONTRIBUTION
    result: dict[str, float] = {}
    for family_tokens in families.values():
        family_sum = sum(w for _, w in family_tokens)
        if family_sum > max_per_family:
            # Scale down proportionally
            scale = max_per_family / family_sum
            for tok, w in family_tokens:
                result[tok] = w * scale
        else:
            for tok, w in family_tokens:
                result[tok] = w
    return result
