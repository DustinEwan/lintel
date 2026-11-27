#!/usr/bin/env python3
"""Extract Rust module dependencies as architecture facts."""

import os
import re
import tomllib

from lintel.adapters.extract_common import iter_files, rel, write_json

VISIBILITY_RE = r"(?:pub(?:\s*\((?:crate|self|super|in\s+[^)]+)\))?\s+)?"
USE_RE = re.compile(r"(?m)^\s*" + VISIBILITY_RE + r"use\s+([^;]+);")
USE_START_RE = re.compile(r"(?m)^\s*(?:pub(?:\s*\([^)]*\))?\s+)?use\b")
ANY_PUB_USE_RE = re.compile(r"(?m)^\s*pub\b[^\n;]*\buse\b")
EXTERN_CRATE_RE = re.compile(r"(?m)^\s*extern\s+crate\s+([A-Za-z_][A-Za-z0-9_]*)\s*;")
UNSUPPORTED_RUST = [
    (re.compile(r"\binclude!\s*\("), "include! can inject dependencies"),
    (re.compile(r"#\s*\[\s*path\s*="), "#[path] changes module paths"),
    (re.compile(r"\bmacro_rules!\s*"), "macro_rules! can generate imports"),
]

PATH_REDIRECT_RE = re.compile(
    r'#\s*\[\s*path\s*=\s*(?P<quote>["\'])(?P<path>[^"\']+)\1\s*\]'
    r'\s*\bmod\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*;'
)
INCLUDE_LITERAL_RE = re.compile(
    r'\binclude!\s*\(\s*(?P<quote>["\'])(?P<path>[^"\']+)\1\s*\)\s*;'
)


def line_of(text, offset):
    return text.count("\n", 0, offset) + 1


def literal_target(path, spec, known_files, root, unparsed, line, reason):
    target = os.path.normpath(os.path.join(os.path.dirname(path), spec))
    if target not in known_files:
        unparsed.append({"source": rel(path, root), "line": line, "reason": reason})
        return None
    return target



def crate_name(root):
    cargo = os.path.join(root, "Cargo.toml")
    if os.path.exists(cargo):
        with open(cargo, "rb") as f:
            data = tomllib.load(f)
        return data.get("package", {}).get("name", os.path.basename(root)).replace("-", "_")
    return os.path.basename(root).replace("-", "_")


def module_name(path, root, crate):
    relative = rel(path, root)
    if relative.startswith("src/"):
        relative = relative[4:]
        if relative in ("lib.rs", "main.rs"):
            parts = []
        else:
            if relative.endswith("/mod.rs"):
                relative = relative[: -len("/mod.rs")]
            elif relative.endswith(".rs"):
                relative = relative[: -len(".rs")]
            parts = [p for p in relative.split("/") if p]
    else:
        relative = relative[: -len(".rs")] if relative.endswith(".rs") else relative
        parts = [p for p in relative.split("/") if p]
    return "::".join([crate] + parts) if parts else crate


def split_use_paths(text):
    text = text.strip()
    if text.startswith("::"):
        text = text[2:]
    if "{" in text:
        prefix, rest = text.split("{", 1)
        inner = rest.rsplit("}", 1)[0] if "}" in rest else rest
        prefix = prefix.strip().rstrip(":")
        paths = []
        for item in inner.split(","):
            item = item.strip()
            if not item or item == "self":
                continue
            item = item.split(" as ", 1)[0].strip()
            paths.append(f"{prefix}::{item}" if prefix else item)
        if prefix:
            paths.append(prefix)
        return paths
    path = text.split(" as ", 1)[0].strip()
    return [path.rstrip("*").rstrip(":")] if path else []


def resolve(path, current, crate, modules, local_top):
    path = path.strip().lstrip(":")
    if not path:
        return None
    parts = path.split("::")

    if parts[0] == "crate":
        candidate = "::".join([crate] + parts[1:])
    elif parts[0] == "self":
        candidate = current
        if len(parts) > 1:
            candidate += "::" + "::".join(parts[1:])
    elif parts[0] == "super":
        base = current.split("::")[:-1]
        index = 0
        while index < len(parts) and parts[index] == "super":
            if base:
                base.pop()
            index += 1
        candidate = "::".join(base + parts[index:]) or crate
    elif parts[0] in local_top:
        candidate = "::".join([crate] + parts)
    else:
        return parts[0]

    while candidate not in modules and "::" in candidate:
        candidate = candidate.rsplit("::", 1)[0]
    return candidate


def extract(root):
    crate = crate_name(root)
    files = list(iter_files(root, (".rs",)))
    texts = {}
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            texts[path] = f.read()

    module_by_file = {path: module_name(path, root, crate) for path in files}
    unparsed = []
    handled = {path: set() for path in files}
    redirects = {}
    includes = {}

    for path in files:
        text = texts[path]
        path_specs = []
        for match in PATH_REDIRECT_RE.finditer(text):
            handled[path].add(match.start())
            target = literal_target(
                path,
                match.group("path"),
                set(module_by_file),
                root,
                unparsed,
                line_of(text, match.start()),
                "#[path] target not found",
            )
            if target:
                path_specs.append((match.group("name"), target))
        redirects[path] = path_specs

        include_specs = []
        for match in INCLUDE_LITERAL_RE.finditer(text):
            handled[path].add(match.start())
            target = literal_target(
                path,
                match.group("path"),
                set(texts),
                root,
                unparsed,
                line_of(text, match.start()),
                "include! target not found",
            )
            if target:
                include_specs.append((target, line_of(text, match.start())))
        includes[path] = include_specs

    for _ in range(len(files) + 1):
        changed = False
        for path, specs in redirects.items():
            parent = module_by_file[path]
            for name, target in specs:
                new_name = f"{parent}::{name}"
                if module_by_file[target] != new_name:
                    module_by_file[target] = new_name
                    changed = True
        if not changed:
            break

    included_files = {target for specs in includes.values() for target, _ in specs}
    module_by_file = {
        path: name for path, name in module_by_file.items() if path not in included_files
    }
    modules = sorted(set(module_by_file.values()))
    local_top = {
        name.split("::")[1]
        for name in modules
        if name.startswith(crate + "::") and len(name.split("::")) > 1
    }

    dependencies = []

    def scan(path, current, stack):
        if path in stack:
            unparsed.append(
                {
                    "source": rel(path, root),
                    "line": 1,
                    "reason": "include cycle",
                }
            )
            return
        text = texts[path]
        source = rel(path, root)
        matched_uses = {match.start() for match in USE_RE.finditer(text)}
        use_starts = {match.start() for match in USE_START_RE.finditer(text)}
        pub_use_starts = {match.start() for match in ANY_PUB_USE_RE.finditer(text)}
        for start in sorted(use_starts | pub_use_starts):
            if start in matched_uses:
                continue
            reason = (
                "unrecognized visibility form before use"
                if start in pub_use_starts
                else "unterminated or unsupported use statement"
            )
            unparsed.append(
                {"source": source, "line": line_of(text, start), "reason": reason}
            )
        for pattern, reason in UNSUPPORTED_RUST:
            for match in pattern.finditer(text):
                if match.start() in handled[path]:
                    continue
                unparsed.append(
                    {
                        "source": source,
                        "line": line_of(text, match.start()),
                        "reason": reason,
                    }
                )
        for match in EXTERN_CRATE_RE.finditer(text):
            dependencies.append(
                {
                    "from": current,
                    "to": match.group(1),
                    "kind": "extern_crate",
                    "source": source,
                    "line": line_of(text, match.start()),
                }
            )
        for match in USE_RE.finditer(text):
            for use_path in split_use_paths(match.group(1)):
                target = resolve(use_path, current, crate, set(modules), local_top)
                if target and target != current:
                    dependencies.append(
                        {
                            "from": current,
                            "to": target,
                            "kind": "use",
                            "source": source,
                            "line": line_of(text, match.start()),
                        }
                    )
        for target, _ in includes[path]:
            scan(target, current, stack | {path})

    for path in files:
        if path in included_files:
            continue
        scan(path, module_by_file[path], set())

    return {
        "version": 1,
        "language": "rust",
        "modules": [
            {"name": name, "path": rel(path, root)}
            for path, name in sorted(module_by_file.items(), key=lambda item: item[1])
        ],
        "dependencies": dependencies,
        "unparsed": unparsed,
    }


