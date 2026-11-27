#!/usr/bin/env python3
"""Extract Rust module dependencies as architecture facts."""

import os
import re
import tomllib

from adapters.extract_common import iter_files, rel, write_json

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
    module_by_file = {path: module_name(path, root, crate) for path in files}
    modules = sorted(set(module_by_file.values()))
    local_top = {
        name.split("::")[1]
        for name in modules
        if name.startswith(crate + "::") and len(name.split("::")) > 1
    }

    dependencies = []
    unparsed = []
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        current = module_by_file[path]
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
                {
                    "source": source,
                    "line": text.count("\n", 0, start) + 1,
                    "reason": reason,
                }
            )
        for pattern, reason in UNSUPPORTED_RUST:
            for match in pattern.finditer(text):
                unparsed.append(
                    {
                        "source": source,
                        "line": text.count("\n", 0, match.start()) + 1,
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
                    "line": text.count("\n", 0, match.start()) + 1,
                }
            )
        for match in USE_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            for use_path in split_use_paths(match.group(1)):
                target = resolve(use_path, current, crate, set(modules), local_top)
                if target and target != current:
                    dependencies.append(
                        {
                            "from": current,
                            "to": target,
                            "kind": "use",
                            "source": source,
                            "line": text.count("\n", 0, match.start()) + 1,
                        }
                    )

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


