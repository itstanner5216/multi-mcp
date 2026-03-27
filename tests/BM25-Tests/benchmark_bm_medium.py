#!/usr/bin/env python3
"""Benchmark BM variants on medium-size synthetic MCP corpora.

This script targets a medium regime (hundreds to low thousands of tools)
with heavier overlap and a mix of anchored and generic queries.
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import random
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# -----------------------------------------------------------------------------
# Dynamic loader
# -----------------------------------------------------------------------------


def load_class(module_path: str, class_name: str):
    path = Path(module_path).resolve()
    module_name = f"bench_{path.stem}_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        return getattr(module, class_name)
    except AttributeError as e:
        raise RuntimeError(f"{path.name} does not expose {class_name}") from e


# -----------------------------------------------------------------------------
# Metrics
# -----------------------------------------------------------------------------


def reciprocal_rank(results: list[tuple[str, float]], relevant_id: str) -> float:
    for rank, (doc_id, _) in enumerate(results, start=1):
        if doc_id == relevant_id:
            return 1.0 / rank
    return 0.0


def ndcg_at_k_single(results: list[tuple[str, float]], relevant_id: str, k: int = 10) -> float:
    for rank, (doc_id, _) in enumerate(results[:k], start=1):
        if doc_id == relevant_id:
            return 1.0 / math.log2(rank + 1)
    return 0.0


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(
        len(ordered) - 1,
        max(0, int(math.ceil((pct / 100.0) * len(ordered))) - 1),
    )
    return ordered[idx]


# -----------------------------------------------------------------------------
# MCP-style corpora (medium)
# -----------------------------------------------------------------------------

VERBS = [
    "read", "write", "create", "update", "delete", "search", "list", "open",
    "fetch", "sync", "run", "deploy", "inspect", "compare", "label", "route",
]
DOMAINS = [
    "github", "filesystem", "calendar", "gmail", "contacts", "drive", "slack",
    "notion", "obsidian", "docker", "shell", "python", "spreadsheet", "slides",
]
OBJECTS = [
    "repo", "issue", "pull_request", "file", "folder", "event", "message",
    "thread", "document", "note", "vault", "container", "sheet", "deck",
]
NOISE = [
    "safe", "reliable", "deterministic", "scalable", "fast", "grounded", "typed",
    "batched", "incremental", "hybrid", "semantic", "lexical", "tooling", "policy",
]


@dataclass
class QueryCase:
    query: str
    relevant_id: str


@dataclass
class CorpusBundle:
    docs: list[dict]
    queries: list[QueryCase]
    name: str


def make_medium_registry(
    seed: int = 19,
    n_tools: int = 1200,
    n_queries: int = 250,
    anchored: bool = False,
) -> CorpusBundle:
    rng = random.Random(seed)
    docs: list[dict] = []
    queries: list[QueryCase] = []

    for i in range(n_tools):
        verb = VERBS[i % len(VERBS)]
        domain = DOMAINS[(i // 3) % len(DOMAINS)]
        obj = OBJECTS[(i // 5) % len(OBJECTS)]
        anchor = f"uid_{i:05d}"
        family = f"family_{domain}_{i % 30}"
        fluff = rng.sample(NOISE, 4)
        text = " ".join(
            [
                f"tool {anchor} {family}",
                f"{verb} {obj} {domain}",
                "mcp server dynamic loading conversational context agent router selection registry",
                *fluff,
            ]
        )
        docs.append({"chunk_id": f"md_{i:05d}", "text": text})

    for _ in range(n_queries):
        i = rng.randrange(n_tools)
        verb = VERBS[i % len(VERBS)]
        domain = DOMAINS[(i // 3) % len(DOMAINS)]
        obj = OBJECTS[(i // 5) % len(OBJECTS)]
        anchor = f"uid_{i:05d}"
        doc_id = f"md_{i:05d}"
        if anchored:
            q = f"mcp {verb} {obj} {domain} {anchor} dynamic tool"
        else:
            q = f"mcp {verb} {obj} {domain} tool dynamic context router"
        queries.append(QueryCase(query=q, relevant_id=doc_id))

    name = "medium_anchored" if anchored else "medium_generic"
    return CorpusBundle(docs=docs, queries=queries, name=name)


def make_medium_overlap(
    seed: int = 31,
    n_groups: int = 18,
    per_group: int = 25,
) -> CorpusBundle:
    rng = random.Random(seed)
    docs: list[dict] = []
    queries: list[QueryCase] = []

    shared_phrases = [
        "mcp server tool router",
        "dynamic loading based on conversational context",
        "agent chooses best tool",
        "registry selection workflow",
        "hybrid semantic lexical routing",
    ]

    for g in range(n_groups):
        verb = VERBS[g % len(VERBS)]
        domain = DOMAINS[g % len(DOMAINS)]
        obj = OBJECTS[g % len(OBJECTS)]
        for j in range(per_group):
            i = g * per_group + j
            variant = f"variant_{g}_{j % 5}"
            rare = (
                f"discriminator_{g}_{j:03d}"
                if j % 3 == 0
                else f"soft_{g}_{j % 7}"
            )
            repeated = " ".join(rng.choices(shared_phrases, k=4))
            text = " ".join(
                [
                    repeated,
                    f"{verb} {obj} {domain}",
                    f"tool {variant} handles {verb} and search and list and update",
                    f"generic generic generic {rare}",
                    f"{domain} integration {obj} orchestration",
                ]
            )
            doc_id = f"ovm_{i:05d}"
            docs.append({"chunk_id": doc_id, "text": text})

            # Queries mix generic patterns and the rare discriminator
            qs = [
                QueryCase(
                    query=f"mcp {domain} {verb} {obj} tool router dynamic context",
                    relevant_id=doc_id,
                ),
                QueryCase(
                    query=f"{verb} {obj} {domain} {rare} mcp server",
                    relevant_id=doc_id,
                ),
            ]
            queries.extend(qs)

    return CorpusBundle(docs=docs, queries=queries, name="medium_overlap")


# -----------------------------------------------------------------------------
# Benchmark runner
# -----------------------------------------------------------------------------


def evaluate_index(
    index_factory: Callable[[], object],
    docs: list[dict],
    queries: list[QueryCase],
    top_k: int = 10,
) -> dict:
    idx = index_factory()
    idx.build_index(docs)

    # Warmup
    for q in queries[: min(10, len(queries))]:
        idx.search(q.query, top_k=top_k)

    top1 = 0
    rr_values = []
    ndcg_values = []
    latencies = []

    for q in queries:
        t0 = time.perf_counter()
        results = idx.search(q.query, top_k=top_k)
        latencies.append((time.perf_counter() - t0) * 1000.0)

        if results and results[0][0] == q.relevant_id:
            top1 += 1
        rr_values.append(reciprocal_rank(results, q.relevant_id))
        ndcg_values.append(ndcg_at_k_single(results, q.relevant_id, k=top_k))

    return {
        "top1": 100.0 * top1 / len(queries) if queries else 0.0,
        "mrr": 100.0 * statistics.fmean(rr_values) if rr_values else 0.0,
        "ndcg@10": 100.0 * statistics.fmean(ndcg_values) if ndcg_values else 0.0,
        "latency_ms": statistics.fmean(latencies) if latencies else 0.0,
        "p95_ms": percentile(latencies, 95.0) if latencies else 0.0,
        "queries": len(queries),
        "docs": len(docs),
    }


def print_table(title: str, rows: list[dict], key_order: list[str]) -> None:
    print(f"\n=== {title} ===")
    headers = ["variant", *key_order]
    str_rows = []
    for row in rows:
        vals = [row.get("variant", "")]
        for key in key_order:
            val = row.get(key, "")
            if isinstance(val, float):
                vals.append(f"{val:.3f}")
            else:
                vals.append(str(val))
        str_rows.append(vals)

    widths = [max(len(h), *(len(r[i]) for r in str_rows)) for i, h in enumerate(headers)]
    print(" | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print("-+-".join("-" * w for w in widths))
    for row in str_rows:
        print(" | ".join(row[i].ljust(widths[i]) for i in range(len(headers))))


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Medium-scale MCP BM benchmark")
    parser.add_argument("--bm25", default="./bm25.py")
    parser.add_argument("--bmx-old", default="./BM.X.py")
    parser.add_argument("--bmx-new", default="./bmx.py")
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()

    BM25Index = load_class(args.bm25, "BM25Index")
    BMXOldIndex = load_class(args.bmx_old, "BMXIndex")
    BMXNewIndex = load_class(args.bmx_new, "BMXIndex")

    variants = [
        ("bm25", lambda: BM25Index()),
        ("bm_x", lambda: BMXOldIndex()),
        ("bmx", lambda: BMXNewIndex()),
    ]

    bundles = [
        make_medium_registry(anchored=False),
        make_medium_registry(anchored=True),
        make_medium_overlap(),
    ]

    for bundle in bundles:
        rows = []
        for name, factory in variants:
            metrics = evaluate_index(factory, bundle.docs, bundle.queries, top_k=args.top_k)
            metrics["variant"] = name
            rows.append(metrics)
        print_table(
            bundle.name,
            rows,
            ["docs", "queries", "top1", "mrr", "ndcg@10", "latency_ms", "p95_ms"],
        )

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

