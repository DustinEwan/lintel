"""Go module and dependency facts from tree-sitter ASTs.

Build constraints remain comment-level metadata and reuse the existing Go
target evaluator. Package identities and import edges come from tree-sitter.
"""

import os
import re

import tree_sitter as ts
import tree_sitter_go as tsg

from lintel.adapters.extract_common import iter_files, rel
from lintel.adapters.go_build import build_constraint_status, host_target

_LANGUAGE = ts.Language(tsg.language())
_PARSER = ts.Parser(_LANGUAGE)
_MODULE_RE = re.compile(r"(?m)^module\s+(\S+)")


def _text(node, source_bytes):
    if node is None:
        return ""
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _children(node, kind):
    return [child for child in node.children if child.type == kind]


def _find(node, kind):
    for child in node.children:
        if child.type == kind:
            return child
        found = _find(child, kind)
        if found is not None:
            return found
    return None



def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)

def _module_prefix(root):
    go_mod = os.path.join(root, "go.mod")
    if not os.path.isfile(go_mod):
        return None
    with open(go_mod, encoding="utf-8") as handle:
        match = _MODULE_RE.search(handle.read())
    return match.group(1) if match else None


def _module_name(path, root, prefix):
    directory = os.path.dirname(rel(path, root))
    parts = [] if directory in ("", ".") else directory.split("/")
    if prefix:
        return "/".join([prefix] + parts)
    return "/".join(parts) if parts else rel(path, root)


def _package_name(root_node, source_bytes):
    clause = next((child for child in root_node.children if child.type == "package_clause"), None)
    if clause is None:
        return None
    identifier = next(
        (child for child in clause.children if child.type == "package_identifier"), None
    )
    return _text(identifier, source_bytes) if identifier is not None else None


def _literal(node, source_bytes):
    if node is None:
        return None
    if node.type == "raw_string_literal":
        return _text(node, source_bytes).strip("`")
    if node.type != "interpreted_string_literal":
        return None
    content = _find(node, "interpreted_string_literal_content")
    return _text(content, source_bytes) if content is not None else ""


def _imports(root_node, source_bytes):
    result = []
    for node in root_node.children:
        if node.type != "import_declaration":
            continue
        specs = _children(node, "import_spec")
        for spec in _children(node, "import_spec_list"):
            specs.extend(_children(spec, "import_spec"))
        for spec in specs:
            literal = next(
                (
                    child
                    for child in spec.children
                    if child.type in ("interpreted_string_literal", "raw_string_literal")
                ),
                None,
            )
            value = _literal(literal, source_bytes)
            if value:
                result.append((value, spec.start_point[0] + 1))
    return result


def extract(root, target=None):
    """Return normalized Go module, dependency, and unparsed facts."""
    target = tuple(target) if target is not None else host_target()
    prefix = _module_prefix(root)
    texts = {}
    for path in iter_files(root, (".go",)):
        with open(path, "r", encoding="utf-8") as handle:
            texts[path] = handle.read()

    unparsed = []
    active_files = []
    for path, text in texts.items():
        status, line = build_constraint_status(text, target)
        if status is False:
            continue
        if status is None:
            unparsed.append(
                {
                    "source": rel(path, root),
                    "line": line or 1,
                    "reason": "indeterminate build constraint",
                }
            )
        active_files.append(path)

    module_by_file = {path: _module_name(path, root, prefix) for path in active_files}
    package_by_file = {}
    dependencies = []
    for path in active_files:
        with open(path, "rb") as handle:
            source_bytes = handle.read()
        tree = _PARSER.parse(source_bytes)
        if tree.root_node.has_error:
            error = next((item for item in _walk(tree.root_node) if item.type == "ERROR"), None)
            unterminated = any(
                child.type == "import_declaration"
                and "(" in _text(child, source_bytes)
                and ")" not in _text(child, source_bytes)
                for child in tree.root_node.children
            )
            reason = "unterminated import block" if unterminated else "unparsed Go syntax"
            line = error.start_point[0] + 1 if error is not None else 1
            unparsed.append({"source": rel(path, root), "line": line, "reason": reason})
            continue
        package_by_file[path] = _package_name(tree.root_node, source_bytes)
        source = rel(path, root)
        current = module_by_file[path]
        for imported, line in _imports(tree.root_node, source_bytes):
            if imported != current:
                dependencies.append(
                    {
                        "from": current,
                        "to": imported,
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
                "package": package_by_file.get(path),
            }
            for path, name in sorted(module_by_file.items(), key=lambda item: item[1])
        ],
        "dependencies": dependencies,
        "unparsed": unparsed,
    }
