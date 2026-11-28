"""Python module and dependency facts from tree-sitter ASTs.

This contributor emits the same normalized ``Module``, ``Dependency``, and
``UnparsedSource`` shapes as the legacy Python extractor. It is the first
language contributor built directly on tree-sitter.
"""

import os

import tree_sitter as ts
import tree_sitter_python as tsp

from lintel.adapters.extract_common import iter_files, rel

_LANGUAGE = ts.Language(tsp.language())
_PARSER = ts.Parser(_LANGUAGE)
_SUFFIXES = (".py",)


def _text(node, source_bytes):
    if node is None:
        return ""
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


def _module_from_relative(relative):
    value = relative[: -len(".py")] if relative.endswith(".py") else relative
    parts = [part for part in value.split("/") if part and part != "."]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _module_name(path, root, source_root):
    absolute = os.path.abspath(path)
    source = os.path.abspath(source_root)
    try:
        in_source_root = os.path.commonpath([absolute, source]) == source
    except ValueError:
        in_source_root = False
    relative = os.path.relpath(absolute, source if in_source_root else root)
    name = _module_from_relative(relative.replace(os.sep, "/"))
    return name or os.path.basename(os.path.abspath(root))


def _nearest_module(name, modules):
    target = name
    while target and target not in modules and "." in target:
        target = target.rsplit(".", 1)[0]
    return target if target in modules else None


def _resolve_dotted(name, modules, local_top):
    if name.split(".")[0] in local_top:
        return _nearest_module(name, modules)
    return name


def _current_package(current, is_package):
    return current if is_package else current.rpartition(".")[0]


def _resolve_from(module, names, level, current, is_package, modules, local_top):
    if level == 0:
        prefix = module or ""
    else:
        package = _current_package(current, is_package)
        parts = package.split(".") if package else []
        parts = parts[: len(parts) - (level - 1)] if level > 1 else parts
        prefix = ".".join(parts)
        if module:
            prefix = f"{prefix}.{module}" if prefix else module
    targets = []
    for name in names:
        target = f"{prefix}.{name}" if prefix else name
        resolved = _resolve_dotted(target, modules, local_top)
        if level == 0 and resolved and resolved.split(".", 1)[0] not in local_top:
            resolved = resolved.split(".", 1)[0]
        if resolved:
            targets.append(resolved)
    return targets


def _resolve_relative(name, level, package, current, is_package, modules, local_top):
    base = package or _current_package(current, is_package)
    parts = base.split(".") if base else []
    if level > 1:
        parts = parts[: max(0, len(parts) - (level - 1))]
    if not parts:
        return None
    dotted = name.lstrip(".")
    return _resolve_dotted(
        ".".join(parts + ([dotted] if dotted else [])), modules, local_top
    )


def _aliased_name(node, source_bytes):
    for child in node.named_children:
        return _text(child, source_bytes)
    return ""


def _name_and_alias(node, source_bytes):
    children = node.named_children
    if not children:
        return "", ""
    name = _text(children[0], source_bytes)
    alias = _text(children[-1], source_bytes) if len(children) > 1 else name
    return name, alias


def _find(node, kind):
    for child in node.children:
        if child.type == kind:
            return child
        found = _find(child, kind)
        if found is not None:
            return found
    return None


def _import_aliases(node, source_bytes):
    if node.type not in ("import_statement", "import_from_statement"):
        return []
    pairs = []
    for child in node.children:
        if child.type == "aliased_import":
            pairs.append(_name_and_alias(child, source_bytes))
        elif child.type == "dotted_name":
            name = _text(child, source_bytes)
            pairs.append((name, name))
        elif child.type == "import_list":
            for item in child.named_children:
                if item.type == "aliased_import":
                    pairs.append(_name_and_alias(item, source_bytes))
                elif item.type == "dotted_name":
                    name = _text(item, source_bytes)
                    pairs.append((name, name))
    return pairs


def _import_parts(node, source_bytes):
    """Return (module, level, names) for a Python import statement node."""
    if node.type == "import_statement":
        names = []
        for child in node.children:
            if child.type == "dotted_name":
                names.append(_text(child, source_bytes))
            elif child.type == "aliased_import":
                names.append(_aliased_name(child, source_bytes))
        return "", 0, names
    if node.type != "import_from_statement":
        return "", 0, []
    prefix = _find(node, "import_prefix")
    level = len(prefix.children) if prefix is not None else 0
    seen_import = False
    module = ""
    names = []
    for child in node.children:
        if child.type == "import":
            seen_import = True
            continue
        if child.type in ("from", ",", "import_prefix"):
            continue
        if not seen_import:
            if child.type == "relative_import":
                dotted = _find(child, "dotted_name")
                if dotted is not None:
                    module = _text(dotted, source_bytes)
            elif child.type in ("dotted_name", "identifier"):
                module = _text(child, source_bytes)
            continue
        if child.type == "import_list":
            for item in child.named_children:
                if item.type == "dotted_name":
                    names.append(_text(item, source_bytes))
                elif item.type == "aliased_import":
                    names.append(_aliased_name(item, source_bytes))
        elif child.type in ("dotted_name", "aliased_import"):
            names.append(_aliased_name(child, source_bytes))
    return module, level, names


def _literal_string(node, source_bytes):
    if node is None or node.type != "string":
        return None
    content = next(
        (child for child in node.named_children if child.type == "string_content"), None
    )
    return _text(content, source_bytes) if content is not None else ""


def _literal_int(node, source_bytes):
    if node is None or node.type != "integer":
        return None
    try:
        return int(_text(node, source_bytes).replace("_", ""))
    except ValueError:
        return None


def _call_parts(node, source_bytes):
    function = next(
        (child for child in node.named_children if child.type in ("identifier", "attribute")),
        None,
    )
    arguments = next(
        (child for child in node.named_children if child.type == "argument_list"), None
    )
    positional = []
    keywords = {}
    if arguments is not None:
        for child in arguments.named_children:
            if child.type == "keyword_argument":
                identifier = next(
                    (item for item in child.named_children if item.type == "identifier"),
                    None,
                )
                value = child.named_children[-1] if child.named_children else None
                if identifier is not None and value is not identifier:
                    keywords[_text(identifier, source_bytes)] = value
            else:
                positional.append(child)
    return function, positional, keywords


def _dynamic_kind(function, source_bytes, importlib_names, import_module_names):
    if function is None:
        return None
    text = _text(function, source_bytes)
    if function.type == "identifier":
        if text == "__import__":
            return "builtin"
        if text in import_module_names:
            return "importlib"
        return None
    if function.type == "attribute":
        base = function.named_children[0] if function.named_children else None
        attribute = function.named_children[-1] if function.named_children else None
        if (
            base is not None
            and base.type == "identifier"
            and attribute is not None
            and _text(base, source_bytes) in importlib_names
            and _text(attribute, source_bytes) in ("import_module", "find_spec")
        ):
            return "importlib"
    return None


def extract(root):
    """Return normalized Python module, dependency, and unparsed facts."""
    source_root = os.path.join(root, "src")
    if not os.path.isdir(source_root):
        source_root = root
    files = list(iter_files(root, _SUFFIXES))
    module_by_file = {path: _module_name(path, root, source_root) for path in files}
    modules = sorted({name for name in module_by_file.values() if name})
    local_top = {name.split(".")[0] for name in modules}
    dependencies = []
    unparsed = []
    seen = set()

    for path in files:
        source = rel(path, root)
        current = module_by_file[path]
        is_package = os.path.basename(path) == "__init__.py"
        with open(path, "rb") as handle:
            source_bytes = handle.read()
        tree = _PARSER.parse(source_bytes)
        if tree.root_node.has_error:
            unparsed.append(
                {"source": source, "line": 1, "reason": "unparsed Python syntax"}
            )
            continue
        nodes = list(_walk(tree.root_node))

        def record(target, line, kind):
            if not target or target == current:
                return
            key = (current, target, source, line, kind)
            if key in seen:
                return
            seen.add(key)
            dependencies.append(
                {
                    "from": current,
                    "to": target,
                    "kind": kind,
                    "source": source,
                    "line": line,
                }
            )

        importlib_names = {"importlib"}
        import_module_names = set()
        for node in nodes:
            if node.type not in ("import_statement", "import_from_statement"):
                continue
            module, _, _ = _import_parts(node, source_bytes)
            for name, alias in _import_aliases(node, source_bytes):
                if node.type == "import_statement":
                    if name.split(".")[0] == "importlib":
                        importlib_names.add(alias)
                elif module.startswith("importlib") and name in ("import_module", "find_spec"):
                    import_module_names.add(alias)

        for node in nodes:
            if node.type == "import_statement":
                module, _, names = _import_parts(node, source_bytes)
                for name in names:
                    record(
                        _resolve_dotted(name, modules, local_top),
                        node.start_point[0] + 1,
                        "import",
                    )
            elif node.type == "import_from_statement":
                module, level, names = _import_parts(node, source_bytes)
                if level == 0 and module == "__future__":
                    continue
                for target in _resolve_from(
                    module, names, level, current, is_package, modules, local_top
                ):
                    record(target, node.start_point[0] + 1, "import")
            elif node.type != "call":
                continue
            function, positional, keywords = _call_parts(node, source_bytes)
            kind = _dynamic_kind(function, source_bytes, importlib_names, import_module_names)
            function_text = _text(function, source_bytes) if function is not None else ""
            line = node.start_point[0] + 1
            if kind is None:
                if function is not None and function.type == "identifier" and function_text in ("eval", "exec"):
                    unparsed.append(
                        {
                            "source": source,
                            "line": line,
                            "reason": "dynamic code execution can inject imports",
                        }
                    )
                continue
            name = _literal_string(positional[0], source_bytes) if positional else None
            if name is None:
                unparsed.append(
                    {"source": source, "line": line, "reason": "non-literal dynamic import"}
                )
                continue
            leading = len(name) - len(name.lstrip("."))
            resolved = None
            if kind == "importlib":
                if leading:
                    package_node = keywords.get("package")
                    package = (
                        _literal_string(package_node, source_bytes)
                        if package_node is not None
                        else None
                    )
                    if package_node is not None and package is None:
                        unparsed.append(
                            {
                                "source": source,
                                "line": line,
                                "reason": "non-literal dynamic import package",
                            }
                        )
                        continue
                    if package is None:
                        unparsed.append(
                            {
                                "source": source,
                                "line": line,
                                "reason": "relative dynamic import without package",
                            }
                        )
                        continue
                    resolved = _resolve_relative(
                        name, leading, package, current, is_package, modules, local_top
                    )
                else:
                    resolved = _resolve_dotted(name, modules, local_top)
            else:
                level_node = keywords.get("level")
                if level_node is None and len(positional) >= 5:
                    level_node = positional[4]
                level = _literal_int(level_node, source_bytes) if level_node is not None else 0
                if level_node is not None and level is None:
                    unparsed.append(
                        {
                            "source": source,
                            "line": line,
                            "reason": "non-literal dynamic import level",
                        }
                    )
                    continue
                if level > 0 or leading:
                    resolved = _resolve_relative(
                        name, level or leading, None, current, is_package, modules, local_top
                    )
                else:
                    resolved = _resolve_dotted(name, modules, local_top)
            if resolved:
                record(resolved, line, "dynamic_import")
            else:
                unparsed.append(
                    {
                        "source": source,
                        "line": line,
                        "reason": "unresolved relative dynamic import",
                    }
                )

    return {
        "version": 1,
        "language": "python",
        "modules": [
            {"name": name, "path": rel(path, root)}
            for path, name in sorted(module_by_file.items(), key=lambda item: item[1])
        ],
        "dependencies": dependencies,
        "unparsed": unparsed,
    }
