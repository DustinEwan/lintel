#!/usr/bin/env python3
"""Extract Go package dependencies as architecture facts."""

import os
import re

from adapters.extract_common import iter_files, rel, write_json

MODULE_RE = re.compile(r"(?m)^module\s+(\S+)")
PACKAGE_RE = re.compile(r"(?m)^package\s+([A-Za-z_][A-Za-z0-9_]*)")
STRING_RE = re.compile(r'"([^"\n]+)"|`([^`]+)`')
BUILD_TAG_RE = re.compile(r"^//\s*(?:go:build|\+build)\b")

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
    unparsed = []
    in_block = False
    block_line = None
    for line_number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("import ("):
            if in_block:
                unparsed.append({"line": line_number, "reason": "nested import block"})
            in_block = True
            block_line = line_number
            continue
        if in_block:
            if stripped.startswith(")"):
                in_block = False
                continue
            matches = STRING_RE.findall(stripped)
            if not matches and stripped and not stripped.startswith("//"):
                unparsed.append(
                    {"line": line_number, "reason": "unsupported import block entry"}
                )
        elif stripped.startswith("import "):
            matches = STRING_RE.findall(stripped)
            if not matches:
                unparsed.append(
                    {"line": line_number, "reason": "unsupported import statement"}
                )
        else:
            matches = []
        for double, backtick in matches:
            value = double or backtick
            if value:
                imports.append((value, line_number))
    if in_block:
        unparsed.append({"line": block_line or 1, "reason": "unterminated import block"})
    return imports, unparsed


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
    unparsed = []
    dependencies = []
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        package_by_file[path] = package_name(text)
        source = rel(path, root)
        for line_number, line in enumerate(text.splitlines(), 1):
            if BUILD_TAG_RE.match(line.strip()):
                unparsed.append(
                    {
                        "source": source,
                        "line": line_number,
                        "reason": "build-constrained file requires explicit policy",
                    }
                )
        imports, import_unparsed = import_strings(text)
        for item in import_unparsed:
            unparsed.append({"source": source, **item})
        current = module_by_file[path]
        for imported, line in imports:
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
                        "source": source,
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
        "unparsed": unparsed,
    }


