#!/usr/bin/env python3
"""Committed lock data for the architecture contract."""

import hashlib
import json
import os
import tomllib

from lintel.core.model import Violation
from lintel.core.rules import catalog_data, rule_spec

CHECKER_ARTIFACTS = (
    "Lintel.lean",
    "lean-toolchain",
    "lakefile.toml",
    "lake-manifest.json",
    "core/model.py",
    "core/checker.py",
    "core/callgraph.py",
    "core/rules.py",
    "core/ratchet.py",
    "core/ports.py",
    "core/presets.py",
    "core/use_cases/__init__.py",
    "core/use_cases/check_facts.py",
    "core/use_cases/self_check.py",
    "core/hooks.py",
    "adapters/release.py",
    "core/review.py",
    "adapters/config.py",
    "adapters/decision_model.py",
    "adapters/agent_files.py",
    "adapters/contract_facts.py",
    "adapters/contract_lock.py",
    "adapters/incremental_cache.py",
    "adapters/diagnostics.py",
    "adapters/extract_common.py",
    "adapters/runtime.py",
    "adapters/source_graph.py",
    "adapters/source_graph_go.py",
    "adapters/source_graph_python.py",
    "adapters/source_graph_rust.py",
    "adapters/source_graph_typescript.py",
    "adapters/go_build.py",
    "adapters/rust_graph.py",
    "core/graph_facts.py",
    "core/graph_index.py",
    "core/source_patterns.py",
    "core/version.py",
    "adapters/language/tree_sitter_analyzer.py",
    "adapters/language/tree_sitter_go.py",
    "adapters/language/tree_sitter_python.py",
    "adapters/language/tree_sitter_rust.py",
    "adapters/language/__init__.py",
    "adapters/language/native_analyzer.py",
    "adapters/language/python_analyzer.py",
    "adapters/lean_generator.py",
    "cli/main.py",
    "cli/check_facts.py",
    "cli/check_self.py",
)


def canonical_bytes(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def config_digest(config_path):
    with open(config_path, "rb") as handle:
        config = tomllib.load(handle)
    return digest(canonical_bytes(config))


def rule_catalog_digest():
    return digest(canonical_bytes(catalog_data()))


def checker_artifact_digest(root):
    hasher = hashlib.sha256()
    for relative in CHECKER_ARTIFACTS:
        path = os.path.join(root, relative)
        with open(path, "rb") as handle:
            content = handle.read()
        hasher.update(relative.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(str(len(content)).encode("ascii"))
        hasher.update(b"\0")
        hasher.update(content)
        hasher.update(b"\0")
    return hasher.hexdigest()


def baseline_digest(root):
    path = os.path.join(root, "lintel.baseline.json")
    if not os.path.isfile(path):
        return ""
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return digest(canonical_bytes(data))


def lock_path(root):
    return os.path.join(root, "lintel.lock")


def baseline_path(root):
    return os.path.join(root, "lintel.baseline.json")


def build_lock_data(root, config_path, checker_root=None):
    return {
        "version": 1,
        "schema_version": 1,
        "config_sha256": config_digest(config_path),
        "rule_catalog_sha256": rule_catalog_digest(),
        "checker_artifact_sha256": checker_artifact_digest(checker_root or root),
        "baseline_sha256": baseline_digest(root),
    }


def write_lock(root, config_path, checker_root=None):
    path = lock_path(root)
    with open(path, "w", encoding="utf-8") as handle:
        for key, value in build_lock_data(root, config_path, checker_root).items():
            handle.write(f"{key} = {json.dumps(value)}\n")


def _violation(field, expected, actual):
    spec = rule_spec("contract_drift")
    return Violation(
        "contract_drift",
        f"contract lock mismatch for {field}",
        {
            "field": field,
            "expected": expected,
            "actual": actual,
            "location": "lintel.lock",
            "fix": spec.fix if spec else "Update the lock explicitly and review the diff.",
        },
    )


def verify_lock(root, config_path, locked, checker_root=None):
    if not locked:
        return ()
    path = lock_path(root)
    if not os.path.isfile(path):
        return (_violation("lock", "committed lock file", "missing"),)
    with open(path, "rb") as handle:
        try:
            current = tomllib.load(handle)
        except tomllib.TOMLDecodeError:
            return (_violation("lock", "valid TOML", "invalid TOML"),)

    expected = build_lock_data(root, config_path, checker_root)
    violations = []
    for key, value in expected.items():
        if current.get(key) != value:
            violations.append(_violation(key, value, current.get(key)))
    return tuple(violations)
