#!/usr/bin/env python3
"""Untracked content-addressed cache for architecture validation."""

import hashlib
import json
import os
import sys
import tempfile
from dataclasses import asdict

from lintel.adapters import contract_lock
from lintel.adapters.extract_common import SKIP_DIRS

CACHE_VERSION = 1
CACHE_FILE = "lintel.cache.json"


def canonical_bytes(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def cache_path(root):
    return os.path.join(root, CACHE_FILE)


def _file_digest(path):
    if not os.path.isfile(path):
        return ""
    with open(path, "rb") as handle:
        return digest(handle.read())


def _walk(root, skip_paths):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in SKIP_DIRS
            and not name.startswith(".")
            and not name.endswith(".egg-info")
        )
        for name in sorted(filenames):
            path = os.path.abspath(os.path.join(dirpath, name))
            if path not in skip_paths:
                yield path


def source_manifest(root):
    skip = {os.path.abspath(cache_path(root))}
    manifest = {}
    for path in _walk(root, skip):
        relative = os.path.relpath(path, root).replace(os.sep, "/")
        manifest[relative] = _file_digest(path)
    return manifest


def _read_state(root):
    path = cache_path(root)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _write_state(root, state):
    path = cache_path(root)
    parent = os.path.dirname(path) or "."
    descriptor, temporary = tempfile.mkstemp(prefix=".architecture-cache-", dir=parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def fact_key(root, config, overrides, tool_root):
    return digest(
        canonical_bytes(
            {
                "version": CACHE_VERSION,
                "python": list(sys.version_info[:3]),
                "contract": {
                    "policy": asdict(config.policy),
                    "roots": [
                        config.core_root,
                        config.adapters_root,
                        config.entrypoints_root,
                    ],
                    "lock": _file_digest(contract_lock.lock_path(root)),
                    "baseline": _file_digest(contract_lock.baseline_path(root)),
                    "checker": contract_lock.checker_artifact_digest(tool_root),
                    "catalog": contract_lock.rule_catalog_digest(),
                },
                "overrides": asdict(overrides),
                "files": source_manifest(root),
            }
        )
    )


def load_facts(root, key):
    state = _read_state(root)
    if state.get("version") != CACHE_VERSION or state.get("fact_key") != key:
        return None
    facts = state.get("facts")
    return facts if isinstance(facts, dict) else None


def save_facts(root, key, facts):
    state = _read_state(root)
    state.update({"version": CACHE_VERSION, "fact_key": key, "facts": facts})
    _write_state(root, state)


def lean_key(root, generated_path, tool_root):
    paths = (
        generated_path,
        os.path.join(tool_root, "Lintel.lean"),
        os.path.join(tool_root, "lean-toolchain"),
    )
    return digest(
        canonical_bytes(
            {
                "version": CACHE_VERSION,
                "files": {
                    os.path.basename(path): _file_digest(path) for path in paths
                },
            }
        )
    )


def lean_ok(root, key):
    state = _read_state(root)
    return state.get("version") == CACHE_VERSION and state.get("lean_ok") == key


def mark_lean_ok(root, key):
    state = _read_state(root)
    state.update({"version": CACHE_VERSION, "lean_ok": key})
    _write_state(root, state)
