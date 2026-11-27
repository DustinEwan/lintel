#!/usr/bin/env python3
"""Discover executable surfaces, boundary concerns, scopes, and wrapper operations."""

import os
from dataclasses import asdict
from fnmatch import fnmatchcase

from adapters.extract_common import SKIP_DIRS, rel
from adapters.language import KNOWN_SOURCE_SUFFIXES, analyzer_for_suffix


def _walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in SKIP_DIRS
            and not name.startswith(".")
            and not name.endswith(".egg-info")
        )
        for name in sorted(filenames):
            yield os.path.join(dirpath, name)


def _expected_scope(path, conventions):
    best = ""
    scope = ""
    for prefix, candidate in conventions.items():
        if path.startswith(prefix) and len(prefix) > len(best):
            best = prefix
            scope = candidate
    return scope


def discover(root, policy, entrypoints_root):
    entrypoints = []
    concerns = []
    wrapper_operations = []
    unparsed = []
    reviews = []
    entrypoint_prefix = entrypoints_root.rstrip("/") + "/"

    for path in _walk(root):
        relative = rel(path, root)
        suffix = os.path.splitext(relative)[1].lower()
        if suffix in KNOWN_SOURCE_SUFFIXES and suffix not in policy.source_suffixes:
            unparsed.append(
                {"source": relative, "line": 1, "reason": f"undeclared source suffix: {suffix}"}
            )
            continue
        analyzer = analyzer_for_suffix(suffix)
        if analyzer is None:
            if suffix not in policy.source_suffixes:
                continue
            unparsed.append(
                {"source": relative, "line": 1, "reason": f"unsupported source suffix: {suffix}"}
            )
            continue
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            source = handle.read()
        analysis = analyzer.analyze(relative, source)

        if analysis.entrypoint is not None:
            entrypoints.append(asdict(analysis.entrypoint))
        concerns.extend(asdict(item) for item in analysis.concerns)
        if relative.startswith(entrypoint_prefix):
            wrapper_operations.extend(
                asdict(item) for item in analysis.wrapper_operations
            )
        unparsed.extend(asdict(item) for item in analysis.unparsed)
        reviews.extend(asdict(item) for item in analysis.reviews)

    assignments = []
    for path in _walk(root):
        relative = rel(path, root)
        expected = _expected_scope(relative, policy.scope_conventions)
        for scope, patterns in policy.scopes.items():
            for pattern in patterns:
                if fnmatchcase(relative, pattern):
                    assignments.append(
                        {
                            "path": relative,
                            "scope": scope,
                            "pattern": pattern,
                            "priority": policy.scope_priorities.get(scope, 100),
                            "expected_scope": expected,
                        }
                    )

    return {
        "entrypoints": entrypoints,
        "concerns": concerns,
        "wrapper_operations": wrapper_operations,
        "scopes": assignments,
        "unparsed": unparsed,
        "reviews": reviews,
    }
