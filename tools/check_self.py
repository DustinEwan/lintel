#!/usr/bin/env python3
"""Check this repository's own architecture with the project's extractors."""

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

    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            facts = json.load(handle)

        for module in facts.get("modules", []):
            if excluded(module["path"]):
                continue
            modules[(module["name"], module["path"])] = module

        for dependency in facts.get("dependencies", []):
            if excluded(dependency["source"]):
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
            if excluded(item["source"]):
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
    with tempfile.TemporaryDirectory() as directory:
        paths = []

        def output_path(name):
            path = os.path.join(directory, name + ".json")
            paths.append(path)
            return path

        run(
            [
                sys.executable,
                "tools/extract_python.py",
                "--root",
                ".",
                "--out",
                output_path("python"),
            ]
        )
        run(
            [
                sys.executable,
                "tools/extract_typescript.py",
                "--root",
                ".",
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

        facts_path = os.path.join(directory, "facts.json")
        with open(facts_path, "w", encoding="utf-8") as handle:
            json.dump(merge_facts(paths), handle, indent=2)
            handle.write("\n")

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
