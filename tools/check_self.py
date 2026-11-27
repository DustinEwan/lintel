#!/usr/bin/env python3
"""Check this repository's own architecture with the project's extractors."""

import argparse
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY = os.path.join("tools", "self_policy.json")
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
    parser.add_argument("--out", help="write merged facts to this path")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as directory:
        paths = []

        def output_path(name, include_prefix=None):
            path = os.path.join(directory, name + ".json")
            paths.append((path, include_prefix))
            return path
        run(
            [
                sys.executable,
                "tools/extract_python.py",
                "--root",
                "tools",
                "--out",
                output_path("python"),
            ]
        )
        run(
            [
                sys.executable,
                "tools/extract_python.py",
                "--root",
                ".",
                "--out",
                output_path("core", "architecture_core/"),
            ]
        )
        run(
            [
                sys.executable,
                "tools/extract_typescript.py",
                "--root",
                "tools",
                "--out",
                output_path("typescript"),
            ]
        )

        run(["cargo", "build", "--quiet", "--manifest-path", "rust-extractor/Cargo.toml"])
        run(
            [
                os.path.join("rust-extractor", "target", "debug", "rust-extractor"),
                "--root",
                "rust-extractor",
                "--out",
                output_path("rust"),
            ]
        )

        go_binary = os.path.join(directory, "go-extractor")
        run(["go", "build", "-o", go_binary, "./go-extractor/main.go"])
        run(
            [
                go_binary,
                "--root",
                "go-extractor",
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
                "tools/check_architecture.py",
                facts_path,
                "--policy",
                POLICY,
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
