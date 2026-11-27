#!/usr/bin/env python3
"""Extract Go package dependencies as architecture facts."""

import argparse
import os
import re

from extract_common import iter_files, rel, write_json

MODULE_RE = re.compile(r"(?m)^module\s+(\S+)")
PACKAGE_RE = re.compile(r"(?m)^package\s+([A-Za-z_][A-Za-z0-9_]*)")
STRING_RE = re.compile(r'"([^"\n]+)"|`([^`]+)`')


def module_prefix(root):
    go_mod = os.path.join(root, "go.mod")
    if os.path.exists(go_mod):
        with open(go_mod, "r", encoding="utf-8") as f:
            match = MODULE_RE.search(f.read())
        if match:
            return match.group(1)
    return None


def package_name(text):
    match = PACKAGE_RE.search(text)
    return match.group(1) if match else None


def import_strings(text):
    imports = []
    in_block = False
    for line_number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("import ("):
            in_block = True
            continue
        if in_block:
            if stripped.startswith(")"):
                in_block = False
                continue
            matches = STRING_RE.findall(stripped)
        elif stripped.startswith("import "):
            matches = STRING_RE.findall(stripped)
        else:
            continue
        for double, backtick in matches:
            value = double or backtick
            if value:
                imports.append((value, line_number))
    return imports


def module_name(path, root, prefix):
    relative = rel(path, root)
    directory = os.path.dirname(relative)
    parts = [] if directory in ("", ".") else directory.split("/")
    if prefix:
        return "/".join([prefix] + parts)
    return "/".join(parts) if parts else relative


def extract(root):
    prefix = module_prefix(root)
    files = list(iter_files(root, (".go",)))
    module_by_file = {path: module_name(path, root, prefix) for path in files}
    modules = sorted(set(module_by_file.values()))

    package_by_file = {}
    dependencies = []
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        package_by_file[path] = package_name(text)
        current = module_by_file[path]
        for imported, line in import_strings(text):
            if prefix and (imported == prefix or imported.startswith(prefix + "/")):
                target = imported
            else:
                target = imported
            if target != current:
                dependencies.append(
                    {
                        "from": current,
                        "to": target,
                        "kind": "import",
                        "source": rel(path, root),
                        "line": line,
                    }
                )

    return {
        "version": 1,
        "language": "go",
        "modules": [
            {
                "name": name,
                "path": rel(path, root),
                "package": package_by_file[path],
            }
            for path, name in sorted(module_by_file.items(), key=lambda item: item[1])
        ],
        "dependencies": dependencies,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="project root to scan")
    parser.add_argument("--out", required=True, help="output JSON facts path")
    args = parser.parse_args()
    write_json(args.out, extract(os.path.abspath(args.root)))


if __name__ == "__main__":
    main()
