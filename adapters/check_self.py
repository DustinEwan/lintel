#!/usr/bin/env python3
"""Check this repository's own architecture with the project's extractors."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CORE_ROOT = "architecture_core"
DEFAULT_ADAPTERS_ROOT = "adapters"
DEFAULT_CONFIG = "architecture.toml"
EXCLUDED_PREFIX = "tests/fixtures/"


def run(command):
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return result


def excluded(source):
    return source.startswith(EXCLUDED_PREFIX)


def resolve_path(path):
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


def relative_prefix(path):
    relative = os.path.relpath(path, ROOT).replace(os.sep, "/")
    return "" if relative == "." else relative.rstrip("/") + "/"


def load_config(path, required):
    full = resolve_path(path)
    if not os.path.isfile(full):
        if required:
            raise SystemExit(f"config not found: {full}")
        return {}
    with open(full, "rb") as handle:
        try:
            data = tomllib.load(handle)
        except tomllib.TOMLDecodeError as error:
            raise SystemExit(f"invalid config {full}: {error}")
    config = data.get("paths", {})
    if not isinstance(config, dict):
        raise SystemExit(f"config {full}: paths must be a table")
    return config


def merge_facts(paths):
    modules = {}
    dependencies = {}
    unparsed = {}

    for path, include_prefix in paths:
        with open(path, "r", encoding="utf-8") as handle:
            facts = json.load(handle)

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="TOML config path")
    parser.add_argument("--core-root", help="core source root")
    parser.add_argument("--adapters-root", help="adapter source root")
    parser.add_argument("--policy", help="architecture policy JSON")
    parser.add_argument("--out", help="write merged facts to this path")
    args = parser.parse_args()

    config = load_config(args.config or DEFAULT_CONFIG, args.config is not None)
    core_root = resolve_path(
        args.core_root or config.get("core_root", DEFAULT_CORE_ROOT)
    )
    adapters_root = resolve_path(
        args.adapters_root or config.get("adapters_root", DEFAULT_ADAPTERS_ROOT)
    )
    policy = resolve_path(
        args.policy
        or config.get("policy")
        or os.path.join(adapters_root, "self_policy.json")
    )
    core_prefix = relative_prefix(core_root)

    with tempfile.TemporaryDirectory() as directory:
        paths = []

        def output_path(name, include_prefix=None):
            path = os.path.join(directory, name + ".json")
            paths.append((path, include_prefix))
            return path

        python_extractor = os.path.join(adapters_root, "extract_python.py")
        typescript_extractor = os.path.join(
            adapters_root, "extract_typescript.py"
        )
        rust_dir = os.path.join(adapters_root, "rust-extractor")
        go_dir = os.path.join(adapters_root, "go-extractor")

        run(
            [
                sys.executable,
                python_extractor,
                "--root",
                adapters_root,
                "--out",
                output_path("python"),
            ]
        )
        run(
            [
                sys.executable,
                python_extractor,
                "--root",
                ".",
                "--out",
                output_path("core", core_prefix),
            ]
        )
        run(
            [
                sys.executable,
                typescript_extractor,
                "--root",
                adapters_root,
                "--out",
                output_path("typescript"),
            ]
        )

        run(
            [
                "cargo",
                "build",
                "--quiet",
                "--manifest-path",
                os.path.join(rust_dir, "Cargo.toml"),
            ]
        )
        run(
            [
                os.path.join(rust_dir, "target", "debug", "rust-extractor"),
                "--root",
                rust_dir,
                "--out",
                output_path("rust"),
            ]
        )

        go_binary = os.path.join(directory, "go-extractor")
        run(
            [
                "go",
                "build",
                "-o",
                go_binary,
                os.path.join(go_dir, "main.go"),
            ]
        )
        run(
            [
                go_binary,
                "--root",
                go_dir,
                "--out",
                output_path("go"),
            ]
        )

        facts = merge_facts(paths)

        def write_facts(path):
            parent = os.path.dirname(os.path.abspath(path))
            os.makedirs(parent, exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(facts, handle, indent=2)
                handle.write("\n")

        facts_path = os.path.join(directory, "facts.json")
        write_facts(facts_path)
        if args.out:
            write_facts(args.out)

        result = subprocess.run(
            [
                sys.executable,
                os.path.join(adapters_root, "check_architecture.py"),
                facts_path,
                "--policy",
                policy,
                "--json",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode not in (0, 1):
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
            return result.returncode

        violations = json.loads(result.stdout)
        if violations:
            print(json.dumps(violations, indent=2))
            return 1

        print("OK: repository architecture has no violations")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
