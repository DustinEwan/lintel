#!/usr/bin/env python3
"""Load architecture.toml and derive checker policy data."""

import tomllib


def load_config(path):
    with open(path, "rb") as handle:
        try:
            return tomllib.load(handle)
        except tomllib.TOMLDecodeError as error:
            raise SystemExit(f"invalid config {path}: {error}")


def _string_list(value, field, layer):
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) for item in value
    ):
        raise SystemExit(f"config layer {layer}: {field} must be an array of strings")
    return list(value)


def policy_from_config(config):
    layers = config.get("layers")
    if not isinstance(layers, dict) or not layers:
        raise SystemExit("config: layers must be a non-empty table")

    default_layer = config.get("default_layer", "external")
    if not isinstance(default_layer, str):
        raise SystemExit("config: default_layer must be a string")
    if default_layer not in layers:
        raise SystemExit(f"config: default_layer {default_layer!r} has no layer definition")

    for name, layer in layers.items():
        if not isinstance(layer, dict):
            raise SystemExit(f"config layer {name}: must be a table")
        priority = layer.get("priority", 1000)
        if not isinstance(priority, int):
            raise SystemExit(f"config layer {name}: priority must be an integer")

    ordered = sorted(layers.items(), key=lambda item: (item[1].get("priority", 1000), item[0]))

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

    return {
        "version": 1,
        "default_region": default_layer,
        "regions": regions,
        "allowed": allowed,
        "forbidden": forbidden,
    }
