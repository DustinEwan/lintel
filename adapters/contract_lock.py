#!/usr/bin/env python3
"""Committed lock data for the architecture contract."""

import hashlib
import json
import os
import tomllib

from architecture_core.model import Violation
from architecture_core.rules import catalog_data, rule_spec

CHECKER_ARTIFACTS = (
    "Architecture.lean",
    "architecture_core/model.py",
    "architecture_core/checker.py",
    "architecture_core/rules.py",
    "architecture_core/ratchet.py",
    "architecture_core/ports.py",
    "architecture_core/presets.py",
    "architecture_core/use_cases/__init__.py",
    "architecture_core/use_cases/check_facts.py",
    "architecture_core/use_cases/self_check.py",
    "adapters/architecture_config.py",
    "adapters/contract_facts.py",
    "adapters/contract_lock.py",
    "adapters/extract_common.py",
    "adapters/go_extractor.py",
    "adapters/python_extractor.py",
    "adapters/runtime.py",
    "adapters/rust_extractor.py",
    "adapters/typescript_extractor.py",
    "adapters/language/__init__.py",
    "adapters/language/native_analyzer.py",
    "adapters/language/python_analyzer.py",
    "adapters/lean_generator.py",
    "external/cli/architecture.py",
    "external/cli/check_architecture.py",
    "external/cli/check_self.py",
    "external/cli/extract_go.py",
    "external/cli/extract_go_native.py",
    "external/cli/extract_python.py",
    "external/cli/extract_rust.py",
    "external/cli/extract_rust_native.py",
    "external/cli/extract_typescript.py",
    "external/cli/extract_typescript_native.py",
    "adapters/extract_typescript_native.mjs",
    "adapters/go-extractor/go.mod",
    "adapters/go-extractor/main.go",
    "adapters/rust-extractor/Cargo.lock",
    "adapters/rust-extractor/Cargo.toml",
    "adapters/rust-extractor/src/main.rs",
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
    path = os.path.join(root, "architecture.baseline.json")
    if not os.path.isfile(path):
        return ""
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return digest(canonical_bytes(data))


def lock_path(root):
    return os.path.join(root, "architecture.lock")


def baseline_path(root):
    return os.path.join(root, "architecture.baseline.json")


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
            "location": "architecture.lock",
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
