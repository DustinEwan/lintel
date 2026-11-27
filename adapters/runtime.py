#!/usr/bin/env python3
"""Concrete adapters for architecture workflows."""

import json
import os
import subprocess
import tempfile

from adapters import architecture_config
from architecture_core.checker import check
from architecture_core.model import (
    FactSet,
    Policy,
    SelfConfig,
    facts_from_dict,
    facts_to_dict,
    policy_from_dict,
)

DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CORE_ROOT = "architecture_core"
DEFAULT_ADAPTERS_ROOT = "adapters"
DEFAULT_CONFIG = "architecture.toml"
EXCLUDED_PREFIX = "tests/fixtures/"


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def excluded(source):
    return source.startswith(EXCLUDED_PREFIX)


def merge_facts(paths):
    modules = {}
    dependencies = {}
    unparsed = {}

    for path, include_prefix in paths:
        facts = load_json(path)

        def keep(source):
            return not excluded(source) and (
                include_prefix is None or source.startswith(include_prefix)
            )

        for module in facts.get("modules", []):
            if not keep(module["path"]):
                continue
            modules[(module["name"], module["path"])] = module

        for dependency in facts.get("dependencies", []):
            if not keep(dependency["source"]):
                continue
            key = (
                dependency["from"],
                dependency["to"],
                dependency["kind"],
                dependency["source"],
                dependency["line"],
            )
            dependencies[key] = dependency

        for item in facts.get("unparsed", []):
            if not keep(item["source"]):
                continue
            key = (item["source"], item["line"], item["reason"])
            unparsed[key] = item

    return {
        "version": 1,
        "language": "self",
        "modules": sorted(modules.values(), key=lambda item: item["name"]),
        "dependencies": sorted(
            dependencies.values(),
            key=lambda item: (item["source"], item["line"], item["to"]),
        ),
        "unparsed": sorted(
            unparsed.values(), key=lambda item: (item["source"], item["line"])
        ),
    }


class ArchitectureRuntime:
    """Implements workflow ports with files, processes, and TOML config."""

    def __init__(self, root=DEFAULT_ROOT):
        self.root = os.path.abspath(root)
        self.entrypoints_root = os.path.join(self.root, "external", "cli")

    def resolve(self, path):
        return path if os.path.isabs(path) else os.path.join(self.root, path)

    def run(self, command):
        result = subprocess.run(
            command, cwd=self.root, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise SystemExit(result.stderr.strip() or result.stdout.strip())
        return result

    def load_self_config(self, path, required):
        full = self.resolve(path or DEFAULT_CONFIG)
        if not os.path.isfile(full):
            if required:
                raise SystemExit(f"config not found: {full}")
            return SelfConfig(
                core_root=self.resolve(DEFAULT_CORE_ROOT),
                adapters_root=self.resolve(DEFAULT_ADAPTERS_ROOT),
                policy=Policy("external", (), {}, {}),
            )
        config = architecture_config.load_config(full)
        path_config = config.get("paths", {})
        if not isinstance(path_config, dict):
            raise SystemExit("config: paths must be a table")
        return SelfConfig(
            core_root=self.resolve(
                path_config.get("core_root", DEFAULT_CORE_ROOT)
            ),
            adapters_root=self.resolve(
                path_config.get("adapters_root", DEFAULT_ADAPTERS_ROOT)
            ),
            policy=policy_from_dict(architecture_config.policy_from_config(config)),
        )

    def collect_self_facts(self, config, overrides):
        core_root = self.resolve(overrides.core_root or config.core_root)
        adapters_root = self.resolve(
            overrides.adapters_root or config.adapters_root
        )
        rust_dir = os.path.join(adapters_root, "rust-extractor")
        go_dir = os.path.join(adapters_root, "go-extractor")

        with tempfile.TemporaryDirectory() as directory:
            paths = []

            def output_path(name, include_prefix=None):
                path = os.path.join(directory, name + ".json")
                paths.append((path, include_prefix))
                return path

            self.run(
                [
                    "python3",
                    os.path.join(self.entrypoints_root, "extract_python.py"),
                    "--root",
                    self.root,
                    "--out",
                    output_path("python"),
                ]
            )
            self.run(
                [
                    "python3",
                    os.path.join(self.entrypoints_root, "extract_typescript.py"),
                    "--root",
                    adapters_root,
                    "--out",
                    output_path("typescript"),
                ]
            )
            self.run(
                [
                    "cargo",
                    "build",
                    "--quiet",
                    "--manifest-path",
                    os.path.join(rust_dir, "Cargo.toml"),
                ]
            )
            self.run(
                [
                    os.path.join(rust_dir, "target", "debug", "rust-extractor"),
                    "--root",
                    rust_dir,
                    "--out",
                    output_path("rust"),
                ]
            )

            go_binary = os.path.join(directory, "go-extractor")
            self.run(
                [
                    "go",
                    "build",
                    "-o",
                    go_binary,
                    os.path.join(go_dir, "main.go"),
                ]
            )
            self.run(
                [
                    go_binary,
                    "--root",
                    go_dir,
                    "--out",
                    output_path("go"),
                ]
            )

            return facts_from_dict(merge_facts(paths))

    def write_facts(self, path, facts):
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(facts_to_dict(facts), handle, indent=2)
            handle.write("\n")

    def load_facts(self, path):
        return facts_from_dict(load_json(self.resolve(path)))

    def load_policy(self, config_path, policy_path):
        if config_path:
            config = architecture_config.load_config(self.resolve(config_path))
            return policy_from_dict(architecture_config.policy_from_config(config))
        return policy_from_dict(load_json(self.resolve(policy_path)))

    def check(self, facts, policy):
        return tuple(check(facts, policy))
