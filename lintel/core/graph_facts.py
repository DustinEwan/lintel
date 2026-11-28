"""Language-neutral normalization for module/dependency graph facts.

Tree-sitter adapters and project metadata readers emit fragments with the
same normalized shapes as :class:`lintel.core.model.FactSet`. This module only
merges and deduplicates those fragments; it intentionally adds no second graph
model. Callers query :class:`lintel.core.graph_index.GraphIndex` through the
``lintel.core.callgraph`` façade for edge resolution.
"""

from collections.abc import Iterable, Mapping
from typing import Any

FACT_KEYS = ("modules", "dependencies", "unparsed")

_KEYS = {
    "modules": lambda item: (item["name"], item.get("path", "")),
    "dependencies": lambda item: (
        item.get("from", ""),
        item.get("to", ""),
        item.get("kind", ""),
        item.get("source", ""),
        item.get("line", 0),
    ),
    "unparsed": lambda item: (
        item.get("source", ""),
        item.get("line", 0),
        item.get("reason", ""),
    ),
}


def empty_graph_facts() -> dict[str, list[dict[str, Any]]]:
    """Return an empty normalized graph fragment."""
    return {key: [] for key in FACT_KEYS}


def merge_graph_facts(
    contributions: Iterable[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Merge normalized fragments by identity, with deterministic ordering."""
    merged = empty_graph_facts()
    seen = {key: set() for key in FACT_KEYS}
    for contribution in contributions:
        for key in FACT_KEYS:
            for item in contribution.get(key, []):
                identity = _KEYS[key](item)
                if identity in seen[key]:
                    continue
                seen[key].add(identity)
                merged[key].append(dict(item))
    merged["modules"].sort(key=lambda item: (item["name"], item.get("path", "")))
    merged["dependencies"].sort(
        key=lambda item: (
            item.get("source", ""),
            item.get("line", 0),
            item.get("to", ""),
        )
    )
    merged["unparsed"].sort(
        key=lambda item: (item.get("source", ""), item.get("line", 0))
    )
    return merged
