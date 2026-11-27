#!/usr/bin/env python3
"""Load and validate architecture.toml, then derive checker policy data."""

import os
import tomllib

from architecture_core.model import Violation
from architecture_core.rules import rule_spec

TOP_LEVEL_KEYS = {
    "version",
    "default_layer",
    "default_scope",
    "paths",
    "scopes",
    "layers",
    "executables",
    "build_artifacts",
    "boundary_concerns",
    "scope_rules",
    "wrapper_rules",
    "use_cases",
    "analysis",
}

PATH_KEYS = {"core_root", "adapters_root", "entrypoints_root"}
SCOPE_KEYS = {"patterns", "priority"}
LAYER_KEYS = {"priority", "core", "patterns", "allowed", "forbidden"}
EXECUTABLE_KEYS = {"name", "path", "owner"}
BUILD_ARTIFACT_KEYS = {"source", "wrapper"}
BOUNDARY_KEYS = {"allowed_regions"}
SCOPE_RULE_KEYS = {"forbidden_edges", "conventions", "excluded_scopes"}
WRAPPER_KEYS = {"allowed_imports", "forbidden_imports", "allowed_commands"}
USE_CASE_KEYS = {"allowed_imports"}

ANALYSIS_KEYS = {"source_suffixes"}


def load_config(path):
    with open(path, "rb") as handle:
        try:
            return tomllib.load(handle)
        except tomllib.TOMLDecodeError as error:
            raise SystemExit(f"invalid config {path}: {error}")


def _string_list(value, field, table):
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) for item in value
    ):
        raise SystemExit(f"config {table}: {field} must be an array of strings")
    return list(value)


def _make_violation(rule, message, **fields):
    spec = rule_spec(rule)
    if spec:
        fields.setdefault("fix", spec.fix)
    return Violation(rule, message, fields)


def _check_keys(value, allowed, table, violations):
    if not isinstance(value, dict):
        return
    for key in sorted(value):
        if key not in allowed:
            violations.append(
                _make_violation(
                    "config_unknown_key",
                    f"config {table}: unknown key {key}",
                    location=f"{table}.{key}",
                )
            )


def validate_config(config, root=None):
    violations = []
    _check_keys(config, TOP_LEVEL_KEYS, "config", violations)

    if config.get("version") != 1:
        violations.append(
            _make_violation(
                "config_invalid", "config version must be 1", location="version"
            )
        )

    analysis = config.get("analysis")
    _check_keys(analysis, ANALYSIS_KEYS, "analysis", violations)
    if not isinstance(analysis, dict):
        violations.append(
            _make_violation("config_invalid", "analysis must be a table", location="analysis")
        )
        analysis = {}
    suffixes = analysis.get("source_suffixes")
    if suffixes is None:
        violations.append(
            _make_violation(
                "config_invalid",
                "analysis.source_suffixes is required",
                location="analysis.source_suffixes",
            )
        )
    elif not isinstance(suffixes, list) or not all(
        isinstance(item, str) for item in suffixes
    ):
        violations.append(
            _make_violation(
                "config_invalid",
                "analysis.source_suffixes must be an array of strings",
                location="analysis.source_suffixes",
            )
        )

    paths = config.get("paths", {})
    _check_keys(paths, PATH_KEYS, "paths", violations)
    if not isinstance(paths, dict):
        violations.append(
            _make_violation("config_invalid", "paths must be a table", location="paths")
        )

    layers = config.get("layers", {})
    scopes = config.get("scopes", {})
    if not isinstance(layers, dict) or not layers:
        violations.append(
            _make_violation("config_invalid", "layers must be a table", location="layers")
        )
        layers = {}

    for name, layer in layers.items():
        _check_keys(layer, LAYER_KEYS, f"layers.{name}", violations)
        if not isinstance(layer, dict):
            violations.append(
                _make_violation(
                    "config_invalid", f"layer {name} must be a table",
                    location=f"layers.{name}",
                )
            )
            continue
        priority = layer.get("priority", 1000)
        if not isinstance(priority, int) or isinstance(priority, bool):
            violations.append(
                _make_violation(
                    "config_invalid", f"layer {name} priority must be an integer",
                    location=f"layers.{name}.priority",
                )
            )
        patterns = layer.get("patterns", [])
        if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
            violations.append(
                _make_violation(
                    "config_invalid", f"layer {name} patterns must be strings",
                    location=f"layers.{name}.patterns",
                )
            )

    priorities = {}
    for name, layer in layers.items():
        if not isinstance(layer, dict):
            continue
        priority = layer.get("priority", 1000)
        if priority in priorities:
            violations.append(
                _make_violation(
                    "config_invalid",
                    f"layers {priorities[priority]} and {name} share priority {priority}",
                    location=f"layers.{name}.priority",
                )
            )
        priorities[priority] = name

    for name, scope in scopes.items():
        _check_keys(scope, SCOPE_KEYS, f"scopes.{name}", violations)
        if not isinstance(scope, dict) or not isinstance(scope.get("patterns"), list):
            violations.append(
                _make_violation(
                    "config_invalid", f"scope {name} needs a patterns array",
                    location=f"scopes.{name}",
                )
            )

    seen_patterns = {}
    for scope_name, scope in scopes.items():
        if not isinstance(scope, dict):
            continue
        for pattern in scope.get("patterns", []):
            if pattern in seen_patterns and seen_patterns[pattern] != scope_name:
                violations.append(
                    _make_violation(
                        "config_pattern_overlap",
                        f"pattern {pattern} is shared by scopes "
                        f"{seen_patterns[pattern]} and {scope_name}",
                        location=f"scopes.{scope_name}.patterns",
                    )
                )
            seen_patterns[pattern] = scope_name

    default_layer = config.get("default_layer", "external")
    if default_layer not in layers:
        violations.append(
            _make_violation(
                "config_bad_reference",
                f"default layer {default_layer} is not declared",
                location="default_layer",
            )
        )
    default_scope = config.get("default_scope", "external")
    if default_scope not in scopes:
        violations.append(
            _make_violation(
                "config_bad_reference",
                f"default scope {default_scope} is not declared",
                location="default_scope",
            )
        )

    for name, layer in layers.items():
        if not isinstance(layer, dict):
            continue
        for target in layer.get("allowed", []):
            if target not in layers and target != default_layer:
                violations.append(
                    _make_violation(
                        "config_bad_reference",
                        f"layer {name} allows undeclared layer {target}",
                        location=f"layers.{name}.allowed",
                    )
                )

    executables = config.get("executables", [])
    if not isinstance(executables, list):
        violations.append(
            _make_violation(
                "config_invalid", "executables must be an array", location="executables"
            )
        )
        executables = []
    executable_names = set()
    for item in executables:
        _check_keys(item, EXECUTABLE_KEYS, "executables", violations)
        if not isinstance(item, dict):
            continue
        name = item.get("name", "")
        executable_names.add(name)
        if item.get("owner") not in layers:
            violations.append(
                _make_violation(
                    "config_bad_reference",
                    f"executable {name} has undeclared owner {item.get('owner')}",
                    location=f"executables.{name}",
                )
            )
        if root and not os.path.isfile(os.path.join(root, item.get("path", ""))):
            violations.append(
                _make_violation(
                    "config_missing_executable",
                    f"executable path does not exist: {item.get('path')}",
                    location=f"executables.{name}",
                )
            )

    artifacts = config.get("build_artifacts", [])
    if not isinstance(artifacts, list):
        artifacts = []
    for item in artifacts:
        _check_keys(item, BUILD_ARTIFACT_KEYS, "build_artifacts", violations)
        if not isinstance(item, dict):
            continue
        if item.get("wrapper") not in executable_names:
            violations.append(
                _make_violation(
                    "config_bad_reference",
                    f"build artifact wrapper is not declared: {item.get('wrapper')}",
                    location=f"build_artifacts.{item.get('source')}",
                )
            )

    boundary = config.get("boundary_concerns", {})
    _check_keys(boundary, {"entrypoint_only", "mechanism"}, "boundary_concerns", violations)
    for category in ("entrypoint_only", "mechanism"):
        table = boundary.get(category, {})
        _check_keys(table, BOUNDARY_KEYS, f"boundary_concerns.{category}", violations)

    scope_rules = config.get("scope_rules", {})
    _check_keys(scope_rules, SCOPE_RULE_KEYS, "scope_rules", violations)
    conventions = scope_rules.get("conventions", {})
    if not isinstance(conventions, dict):
        violations.append(
            _make_violation(
                "config_invalid", "scope conventions must be a table",
                location="scope_rules.conventions",
            )
        )
    for scope in conventions.values() if isinstance(conventions, dict) else []:
        if scope not in scopes:
            violations.append(
                _make_violation(
                    "config_bad_reference",
                    f"scope convention names undeclared scope {scope}",
                    location="scope_rules.conventions",
                )
            )

    wrapper_rules = config.get("wrapper_rules", {})
    _check_keys(wrapper_rules, WRAPPER_KEYS, "wrapper_rules", violations)
    use_cases = config.get("use_cases", {})
    _check_keys(use_cases, USE_CASE_KEYS, "use_cases", violations)

    return tuple(violations)


def policy_from_config(config):
    layers = config.get("layers")
    if not isinstance(layers, dict) or not layers:
        raise SystemExit("config: layers must be a non-empty table")

    default_layer = config.get("default_layer", "external")
    if not isinstance(default_layer, str):
        raise SystemExit("config: default_layer must be a string")

    for name, layer in layers.items():
        if not isinstance(layer, dict):
            raise SystemExit(f"config layer {name}: must be a table")
        priority = layer.get("priority", 1000)
        if not isinstance(priority, int):
            raise SystemExit(f"config layer {name}: priority must be an integer")

    ordered = sorted(
        layers.items(), key=lambda item: (item[1].get("priority", 1000), item[0])
    )

    regions = []
    allowed = {}
    forbidden = {}
    for name, layer in ordered:
        regions.append(
            {
                "name": name,
                "core": bool(layer.get("core", False)),
                "patterns": _string_list(layer.get("patterns"), "patterns", name),
            }
        )
        allowed[name] = _string_list(layer.get("allowed"), "allowed", name)
        targets = _string_list(layer.get("forbidden"), "forbidden", name)
        if targets:
            forbidden[name] = targets

    if default_layer not in allowed:
        regions.append({"name": default_layer, "core": False, "patterns": []})
        allowed[default_layer] = [default_layer]

    paths = config.get("paths", {})
    scopes = config.get("scopes", {})
    scope_rules = config.get("scope_rules", {})
    boundary = config.get("boundary_concerns", {})
    wrapper_rules = config.get("wrapper_rules", {})
    use_cases = config.get("use_cases", {})
    analysis = config.get("analysis")
    if not isinstance(analysis, dict) or "source_suffixes" not in analysis:
        raise SystemExit("config analysis: source_suffixes is required")
    return {
        "version": 1,
        "default_region": default_layer,
        "regions": regions,
        "allowed": allowed,
        "forbidden": forbidden,
        "entrypoints_root": paths.get("entrypoints_root", "external/cli"),
        "scopes": {
            name: _string_list(item.get("patterns"), "patterns", f"scopes.{name}")
            for name, item in scopes.items()
            if isinstance(item, dict)
        },
        "scope_priorities": {
            name: int(item.get("priority", 100))
            for name, item in scopes.items()
            if isinstance(item, dict)
        },
        "scope_conventions": dict(scope_rules.get("conventions", {})),
        "excluded_scopes": tuple(
            scope_rules.get(
                "excluded_scopes",
                ("fixture", "test", "example", "generated", "vendor"),
            )
        ),
        "forbidden_scope_edges": [
            list(edge) for edge in scope_rules.get("forbidden_edges", [])
        ],
        "boundary_allowed_regions": {
            category: _string_list(
                boundary.get(category, {}).get("allowed_regions"),
                "allowed_regions",
                f"boundary_concerns.{category}",
            )
            for category in ("entrypoint_only", "mechanism")
        },
        "executables": config.get("executables", []),
        "build_artifacts": config.get("build_artifacts", []),
        "use_case_allowed_imports": _string_list(
            use_cases.get("allowed_imports"), "allowed_imports", "use_cases"
        ),
        "wrapper_allowed_imports": _string_list(
            wrapper_rules.get("allowed_imports"), "allowed_imports", "wrapper_rules"
        ),
        "wrapper_forbidden_imports": _string_list(
            wrapper_rules.get("forbidden_imports"), "forbidden_imports", "wrapper_rules"
        ),
        "wrapper_allowed_commands": _string_list(
            wrapper_rules.get("allowed_commands"), "allowed_commands", "wrapper_rules"
        ),
        "source_suffixes": tuple(
            _string_list(analysis.get("source_suffixes"), "source_suffixes", "analysis")
        ),
    }
