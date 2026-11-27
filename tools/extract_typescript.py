#!/usr/bin/env python3
"""Extract TypeScript and JavaScript module dependencies as architecture facts."""

import argparse
import os
import posixpath
import re

from extract_common import iter_files, rel, write_json

SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts")
IMPORT_FROM_RE = re.compile(
    r'\b(?:import|export)\s+(?:[^;\n]*?\sfrom\s*)?["\']([^"\']+)["\']'
)
DYNAMIC_RE = re.compile(r'\bimport\s*\(\s*["\']([^"\']+)["\']\s*\)')
REQUIRE_RE = re.compile(r'\brequire\s*\(\s*["\']([^"\']+)["\']\s*\)')
DYNAMIC_CALL_RE = re.compile(r"\b(?:import|require)\s*\(([^)]*)\)")
IMPORT_START_RE = re.compile(r"^\s*import\b")
EXPORT_FROM_RE = re.compile(r"^\s*export\b")

def strip_extension(path):
    if path.endswith(".d.ts"):
        return path[: -len(".d.ts")]
    if path.endswith((".d.mts", ".d.cts")):
        return path[: -len(path[-6:])]
    for suffix in sorted(SUFFIXES, key=len, reverse=True):
        if path.endswith(suffix):
            return path[: -len(suffix)]
    return path


def module_name(path, root):
    return strip_extension(rel(path, root))


def resolve(specifier, source_module, source_path):
    if specifier.startswith("."):
        directory = posixpath.dirname(source_path)
        joined = posixpath.normpath(posixpath.join(directory, specifier))
        target = strip_extension(joined)
        return target if target != source_module else None
    if specifier.startswith("@"):
        return "/".join(specifier.split("/")[:2])
    return specifier.split("/")[0]


def extract(root):
    files = list(iter_files(root, SUFFIXES))
    module_by_file = {path: module_name(path, root) for path in files}
    modules = sorted(set(module_by_file.values()))

    dependencies = []
    unparsed = []
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        current = module_by_file[path]
        source = rel(path, root)
        seen = set()
        for line_number, line in enumerate(text.splitlines(), 1):
            code = line.split("//", 1)[0]
            specs = []
            for pattern in (IMPORT_FROM_RE, DYNAMIC_RE, REQUIRE_RE):
                specs.extend(match.group(1) for match in pattern.finditer(code))
            if not specs and (
                (IMPORT_START_RE.match(code) and ("{" in code or "*" in code))
                or (
                    EXPORT_FROM_RE.match(code)
                    and (" from " in code or re.search(r"\bexport\s+\*", code))
                )
            ):
                unparsed.append(
                    {
                        "source": source,
                        "line": line_number,
                        "reason": "unterminated or unsupported import/export",
                    }
                )
            for match in DYNAMIC_CALL_RE.finditer(code):
                argument = match.group(1).strip()
                if argument and not argument.startswith(("'", '"')):
                    unparsed.append(
                        {
                            "source": source,
                            "line": line_number,
                            "reason": "dynamic dependency with non-literal specifier",
                        }
                    )
            for specifier in specs:
                target = resolve(specifier, current, source)
                if target and target != current and (target, line_number) not in seen:
                    seen.add((target, line_number))
                    dependencies.append(
                        {
                            "from": current,
                            "to": target,
                            "kind": "import",
                            "source": source,
                            "line": line_number,
                        }
                    )

    return {
        "version": 1,
        "language": "typescript",
        "modules": [
            {"name": name, "path": rel(path, root)}
            for path, name in sorted(module_by_file.items(), key=lambda item: item[1])
        ],
        "dependencies": dependencies,
        "unparsed": unparsed,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="project root to scan")
    parser.add_argument("--out", required=True, help="output JSON facts path")
    args = parser.parse_args()
    write_json(args.out, extract(os.path.abspath(args.root)))


if __name__ == "__main__":
    main()
