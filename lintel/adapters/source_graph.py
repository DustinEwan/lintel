"""Project-level source graph facts.

Per-file tree-sitter adapters emit normalized ``SourceAnalysis`` facts. This
module turns those facts plus project metadata into the module, dependency, and
unparsed facts consumed by the existing checker graph. Language contributors
are registered here; runtime and checkers never branch on language.
"""

import os
import posixpath
import tomllib

from lintel.core.graph_facts import merge_graph_facts

from . import (
    go_extractor,
    rust_extractor,
    source_graph_python,
    typescript_extractor,
)


def _python(root):
    """Python module identities and import edges from tree-sitter ASTs."""
    return source_graph_python.extract(root)


def _typescript(root):
    """TypeScript module identities and import edges from its graph reader."""
    return typescript_extractor.extract(root)


def _go_modules(modules):
    """Collapse per-file Go package modules to one module per directory."""
    result = {}
    for item in modules:
        normalized = dict(item)
        normalized["path"] = posixpath.dirname(item["path"]) or "."
        result[(item["name"], normalized["path"])] = normalized
    return list(result.values())


def _go(root):
    """Go module identities and import edges, including build-tag constraints."""
    facts = go_extractor.extract(root)
    return {**facts, "modules": _go_modules(facts.get("modules", []))}


def _rust_workspace_unparsed(root):
    cargo = os.path.join(root, "Cargo.toml")
    if not os.path.isfile(cargo):
        return []
    with open(cargo, "rb") as handle:
        data = tomllib.load(handle)
    members = data.get("workspace", {}).get("members", [])
    if "package" in data and len(members) <= 1:
        return []
    return [
        {
            "source": "Cargo.toml",
            "line": 1,
            "reason": "workspace roots require per-package extraction",
        }
    ]


def _rust(root):
    """Rust crate module identities, use edges, and unsupported constructs."""
    facts = rust_extractor.extract(root)
    unparsed = facts.get("unparsed", []) + _rust_workspace_unparsed(root)
    return {**facts, "unparsed": unparsed}


CONTRIBUTORS = (_python, _typescript, _go, _rust)


def extract_all(root):
    """Return normalized module, dependency, and unparsed facts for ``root``."""
    merged = merge_graph_facts(contributor(root) for contributor in CONTRIBUTORS)
    return {"version": 1, "language": "self", **merged}
