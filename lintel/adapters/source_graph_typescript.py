"""TypeScript and JavaScript graph facts from tree-sitter ASTs."""

import posixpath

import tree_sitter as ts
import tree_sitter_typescript as tsts

from lintel.adapters.extract_common import iter_files, rel

_LANGUAGE = ts.Language(tsts.language_typescript())
_PARSER = ts.Parser(_LANGUAGE)
_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs")


def _text(node, source_bytes):
    if node is None:
        return ""
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


def _find(node, kind):
    for child in node.children:
        if child.type == kind:
            return child
        found = _find(child, kind)
        if found is not None:
            return found
    return None


def _strip_extension(path):
    if path.endswith(".d.ts"):
        return path[: -len(".d.ts")]
    if path.endswith((".d.mts", ".d.cts")):
        return path[: -len(path[-6:])]
    for suffix in sorted(_SUFFIXES, key=len, reverse=True):
        if path.endswith(suffix):
            return path[: -len(suffix)]
    return path


def _module_name(path, root):
    return _strip_extension(rel(path, root))


def _resolve(specifier, source_module, source_path):
    if specifier.startswith("."):
        directory = posixpath.dirname(source_path)
        joined = posixpath.normpath(posixpath.join(directory, specifier))
        target = _strip_extension(joined)
        return target if target != source_module else None
    if specifier.startswith("@"):
        return "/".join(specifier.split("/")[:2])
    return specifier.split("/")[0]


def _string_value(node, source_bytes):
    if node is None or node.type != "string":
        return None
    fragment = _find(node, "string_fragment")
    return _text(fragment, source_bytes) if fragment is not None else ""


def _static_specifier(node, source_bytes):
    if node.type not in ("import_statement", "export_statement"):
        return None, False
    has_from = any(child.type == "from" for child in node.children)
    if not has_from:
        return None, False
    string_node = next((child for child in node.children if child.type == "string"), None)
    return _string_value(string_node, source_bytes), True


def _dynamic_specifier(node, source_bytes):
    if node.type != "call_expression":
        return None, False
    function = next((child for child in node.children if child.type in ("identifier", "import")), None)
    if function is None:
        return None, False
    text = _text(function, source_bytes)
    if text == "import" and function.type == "import":
        dynamic = True
    elif text == "require" and function.type == "identifier":
        dynamic = True
    else:
        return None, False
    arguments = next((child for child in node.children if child.type == "arguments"), None)
    literal = next(
        (
            child
            for child in arguments.children
            if child.type in ("string", "template_string")
        ),
        None,
    ) if arguments is not None else None
    return _string_value(literal, source_bytes), dynamic


def extract(root):
    """Return normalized TypeScript module, dependency, and unparsed facts."""
    files = list(iter_files(root, _SUFFIXES))
    module_by_file = {path: _module_name(path, root) for path in files}
    dependencies = []
    unparsed = []

    for path in files:
        with open(path, "rb") as handle:
            source_bytes = handle.read()
        tree = _PARSER.parse(source_bytes)
        current = module_by_file[path]
        source = rel(path, root)
        seen = set()

        for node in _walk(tree.root_node):
            if node.type == "ERROR":
                if node.parent is not None and node.parent.type in (
                    "import_statement",
                    "export_statement",
                ):
                    unparsed.append(
                        {
                            "source": source,
                            "line": node.start_point[0] + 1,
                            "reason": "unterminated or unsupported import/export",
                        }
                    )
                continue
            specifier, supported = _static_specifier(node, source_bytes)
            if not supported and specifier is None:
                specifier, supported = _dynamic_specifier(node, source_bytes)
            if not supported:
                continue
            line = node.start_point[0] + 1
            if specifier is None:
                if node.type == "call_expression":
                    unparsed.append(
                        {
                            "source": source,
                            "line": line,
                            "reason": "dynamic dependency with non-literal specifier",
                        }
                    )
                continue
            target = _resolve(specifier, current, source)
            if target and target != current and (target, line) not in seen:
                seen.add((target, line))
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
        "language": "typescript",
        "modules": [
            {"name": name, "path": rel(path, root)}
            for path, name in sorted(module_by_file.items(), key=lambda item: item[1])
        ],
        "dependencies": dependencies,
        "unparsed": unparsed,
    }
