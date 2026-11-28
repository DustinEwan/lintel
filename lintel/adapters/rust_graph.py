"""Rust module identity and use-path resolution shared by graph contributors."""

import os
import tomllib

from lintel.adapters.extract_common import rel


def crate_name(root):
    cargo = os.path.join(root, "Cargo.toml")
    if os.path.isfile(cargo):
        with open(cargo, "rb") as handle:
            data = tomllib.load(handle)
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
            parts = [part for part in relative.split("/") if part]
    else:
        relative = relative[: -len(".rs")] if relative.endswith(".rs") else relative
        parts = [part for part in relative.split("/") if part]
    return "::".join([crate] + parts) if parts else crate


def literal_target(path, spec, known_files, root, unparsed, line, reason):
    target = os.path.normpath(os.path.join(os.path.dirname(path), spec))
    if target not in known_files:
        unparsed.append({"source": rel(path, root), "line": line, "reason": reason})
        return None
    return target


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
        candidate = current + ("::" + "::".join(parts[1:]) if len(parts) > 1 else "")
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
