"""Rust module, use-edge, and unsupported-construct facts from tree-sitter ASTs."""

import os

import tree_sitter as ts
import tree_sitter_rust as tsr

from lintel.adapters.extract_common import iter_files, rel
from lintel.adapters.rust_graph import crate_name, literal_target, module_name, resolve

_LANGUAGE = ts.Language(tsr.language())
_PARSER = ts.Parser(_LANGUAGE)
_SUFFIXES = (".rs",)


def _text(node, source_bytes):
    if node is None:
        return ""
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _find(node, kind):
    for child in node.children:
        if child.type == kind:
            return child
        found = _find(child, kind)
        if found is not None:
            return found
    return None


def _string_value(node, source_bytes):
    if node is None:
        return None
    content = _find(node, "string_content")
    return _text(content, source_bytes) if content is not None else ""


def _use_paths(node, source_bytes):
    target = next(
        (
            child
            for child in node.children
            if child.type
            in (
                "scoped_use_list",
                "scoped_identifier",
                "identifier",
                "use_as_clause",
                "self",
                "crate",
                "super",
            )
        ),
        None,
    )
    return _collect_use_paths(target, source_bytes)


def _collect_use_paths(node, source_bytes):
    if node is None:
        return []
    if node.type == "use_as_clause":
        named = node.named_children
        return [_text(named[0], source_bytes)] if named else []
    if node.type == "scoped_use_list":
        prefix = _text(node, source_bytes).split("{", 1)[0].strip().rstrip(":")
        listing = _find(node, "use_list")
        paths = []

        def join(value):
            return f"{prefix}::{value}" if prefix else value

        if listing is not None:
            for child in listing.named_children:
                if child.type == "self":
                    paths.append(prefix)
                elif child.type == "use_as_clause":
                    named = child.named_children
                    if named:
                        paths.append(join(_text(named[0], source_bytes)))
                elif child.type == "scoped_use_list":
                    paths.extend(_collect_use_paths(child, source_bytes))
                elif child.type in ("identifier", "scoped_identifier"):
                    paths.append(join(_text(child, source_bytes)))
        if prefix:
            paths.append(prefix)
        return paths
    return [_text(node, source_bytes)]


def _attribute_path(node, source_bytes):
    attribute = next((child for child in node.children if child.type == "attribute"), None)
    if attribute is None:
        return None
    identifier = next((child for child in attribute.children if child.type == "identifier"), None)
    if identifier is None or _text(identifier, source_bytes) != "path":
        return None
    return _string_value(_find(attribute, "string_literal"), source_bytes)


def _is_path_attribute(node, source_bytes):
    attribute = next((child for child in node.children if child.type == "attribute"), None)
    if attribute is None:
        return False
    identifier = next((child for child in attribute.children if child.type == "identifier"), None)
    return identifier is not None and _text(identifier, source_bytes) == "path"


def _mod_name(node, source_bytes):
    identifier = next((child for child in node.children if child.type == "identifier"), None)
    return _text(identifier, source_bytes) if identifier is not None else None


def _following_mod(node, source_bytes):
    parent = node.parent
    if parent is None:
        return None
    children = list(parent.children)
    target = next(
        (child for child in children[children.index(node) + 1 :] if child.type == "mod_item"),
        None,
    )
    if target is None:
        return None
    names = []
    ancestor = target.parent
    while ancestor is not None:
        if ancestor.type == "mod_item" and any(
            child.type == "declaration_list" for child in ancestor.children
        ):
            name = _mod_name(ancestor, source_bytes)
            if name:
                names.append(name)
        ancestor = ancestor.parent
    names.reverse()
    name = _mod_name(target, source_bytes)
    if name:
        names.append(name)
    return "::".join(names) if names else None


def _include_path(node, source_bytes):
    token_tree = _find(node, "token_tree")
    if token_tree is None:
        return None
    literal = next(
        (child for child in token_tree.children if child.type == "string_literal"), None
    )
    return _string_value(literal, source_bytes)


def extract(root):
    """Return normalized Rust module, dependency, and unparsed facts."""
    crate = crate_name(root)
    files = list(iter_files(root, _SUFFIXES))
    texts = {}
    trees = {}
    bytes_by_file = {}
    for path in files:
        with open(path, "rb") as handle:
            bytes_by_file[path] = handle.read()
        trees[path] = _PARSER.parse(bytes_by_file[path])
        texts[path] = bytes_by_file[path].decode("utf-8", "replace")

    module_by_file = {path: module_name(path, root, crate) for path in files}
    unparsed = []
    handled = {path: set() for path in files}
    redirects = {}
    includes = {}

    for path in files:
        source_bytes = bytes_by_file[path]
        path_specs = []
        include_specs = []
        nodes = []
        stack = [trees[path].root_node]
        while stack:
            node = stack.pop()
            nodes.append(node)
            stack.extend(reversed(node.children))
        for node in nodes:
            line = node.start_point[0] + 1
            if node.type == "attribute_item" and _is_path_attribute(node, source_bytes):
                handled[path].add(node.start_byte)
                spec = _attribute_path(node, source_bytes)
                if spec is None:
                    unparsed.append(
                        {"source": rel(path, root), "line": line, "reason": "#[path] changes module paths"}
                    )
                    continue
                target = literal_target(
                    path, spec, set(module_by_file), root, unparsed,
                    line, "#[path] target not found",
                )
                if target is not None:
                    name = _following_mod(node, source_bytes)
                    if name:
                        path_specs.append((name, target))
                    else:
                        unparsed.append(
                            {"source": rel(path, root), "line": line, "reason": "#[path] changes module paths"}
                        )
            elif node.type == "macro_invocation":
                function = next((child for child in node.children if child.type == "identifier"), None)
                if function is None or _text(function, source_bytes) != "include":
                    continue
                handled[path].add(node.start_byte)
                spec = _include_path(node, source_bytes)
                if spec is None:
                    unparsed.append(
                        {"source": rel(path, root), "line": line, "reason": "include! can inject dependencies"}
                    )
                    continue
                target = literal_target(
                    path, spec, set(files), root, unparsed,
                    line, "include! target not found",
                )
                if target is not None:
                    include_specs.append((target, line))
        redirects[path] = path_specs
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

    def scan(path, current, stack, nodes):
        if path in stack:
            unparsed.append(
                {"source": rel(path, root), "line": 1, "reason": "include cycle"}
            )
            return
        source_bytes = bytes_by_file[path]
        source = rel(path, root)
        for node in nodes:
            line = node.start_point[0] + 1
            if node.type == "use_declaration":
                if node.start_byte in handled[path]:
                    continue
                for use_path in _use_paths(node, source_bytes):
                    target = resolve(use_path, current, crate, set(modules), local_top)
                    if target and target != current:
                        dependencies.append(
                            {
                                "from": current,
                                "to": target,
                                "kind": "use",
                                "source": source,
                                "line": line,
                            }
                        )
            elif node.type == "extern_crate_declaration":
                identifier = next(
                    (child for child in node.children if child.type == "identifier"), None
                )
                if identifier is not None:
                    dependencies.append(
                        {
                            "from": current,
                            "to": _text(identifier, source_bytes),
                            "kind": "extern_crate",
                            "source": source,
                            "line": line,
                        }
                    )
            elif node.type == "macro_definition":
                unparsed.append(
                    {"source": source, "line": line, "reason": "macro_rules! can generate imports"}
                )
        for pattern, reason in (
            ("include!", "include! can inject dependencies"),
            ("#[path]", "#[path] changes module paths"),
        ):
            for node in nodes:
                matched = False
                if pattern == "include!":
                    matched = node.type == "macro_invocation" and any(
                        child.type == "identifier"
                        and _text(child, source_bytes) == "include"
                        for child in node.children
                    )
                elif node.type == "attribute_item":
                    matched = _attribute_path(node, source_bytes) is not None
                if matched and node.start_byte not in handled[path]:
                    unparsed.append(
                        {"source": source, "line": node.start_point[0] + 1, "reason": reason}
                    )
        for target, _ in includes[path]:
            scan(target, current, stack | {path}, _all_nodes(trees[target].root_node))

    def _all_nodes(root_node):
        result = []
        stack = [root_node]
        while stack:
            node = stack.pop()
            result.append(node)
            stack.extend(reversed(node.children))
        return result

    for path in files:
        if path in included_files:
            continue
        scan(path, module_by_file[path], set(), _all_nodes(trees[path].root_node))

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
