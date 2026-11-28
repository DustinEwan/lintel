"""Tree-sitter TypeScript analyzer that emits normalized source facts.

This adapter is not registered by default yet. It exists to validate that
tree-sitter output can populate the existing ``SourceAnalysis`` fact fields
without changing rule IDs or fingerprints.
"""

import posixpath

import tree_sitter as ts
import tree_sitter_typescript as tsts

from lintel.core.checker import module_name_from_path
from lintel.core.model import (
    BoundaryConcernUse,
    CallSite,
    Entrypoint,
    ImportBinding,
    SourceAnalysis,
    Symbol,
)

from .native_analyzer import _javascript_entrypoint_path

_LANGUAGE = ts.Language(tsts.language_typescript())
_PARSER = ts.Parser(_LANGUAGE)

_MEMBER_CONCERNS = {
    ("process", "argv"): ("argv_parse", "entrypoint_only"),
    ("process", "env"): ("env", "mechanism"),
    ("console", "log"): ("terminal_io", "mechanism"),
}
_DEFINITION_TYPES = (
    "function_declaration",
    "generator_function_declaration",
    "method_definition",
    "class_declaration",
)
_RELATIVE_SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".mts")
_IDENTIFIER_TYPES = {
    "identifier",
    "property_identifier",
    "type_identifier",
    "shorthand_property_identifier",
}


def _text(node, source_bytes):
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _line(node):
    return node.start_point[0] + 1


def _walk(root):
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.named_children))


def _parents(root):
    result = {}
    stack = [root]
    while stack:
        node = stack.pop()
        for child in node.named_children:
            result[child] = node
            stack.append(child)
    return result


def _ancestors(node, parents):
    current = parents.get(node)
    while current is not None:
        yield current
        current = parents.get(current)


def _name_of(node, source_bytes):
    if node is None:
        return ""
    if node.type in _IDENTIFIER_TYPES:
        return _text(node, source_bytes)
    named = node.child_by_field_name("name")
    if named is not None:
        return _text(named, source_bytes)
    for child in node.named_children:
        if child.type in _IDENTIFIER_TYPES:
            return _text(child, source_bytes)
        break
    return ""


def _qualified_member(node, source_bytes):
    if node is None or node.type != "member_expression":
        return ""
    base_node = node.child_by_field_name("object")
    property_node = node.child_by_field_name("property")
    if base_node is None or property_node is None:
        return ""
    base = _qualified_member(base_node, source_bytes) or _name_of(
        base_node, source_bytes
    )
    if not base:
        return ""
    return f"{base}.{_text(property_node, source_bytes)}"


def _target_module(specifier, relative_path):
    clean = specifier.strip("'\"")
    if not clean.startswith("."):
        return clean
    base = posixpath.dirname(relative_path.replace("\\", "/"))
    resolved = posixpath.normpath(posixpath.join(base, clean))
    for suffix in _RELATIVE_SUFFIXES:
        if resolved.endswith(suffix):
            resolved = resolved[: -len(suffix)]
            break
    return module_name_from_path(resolved)


def _import_bindings(node, module, relative_path, source_bytes):
    bindings = []
    clause = next(
        (item for item in node.named_children if item.type == "import_clause"),
        None,
    )
    if clause is None:
        return bindings
    source_node = node.child_by_field_name("source")
    if source_node is None:
        return bindings
    target_module = _target_module(_text(source_node, source_bytes), relative_path)
    line = _line(node)
    for child in clause.named_children:
        if child.type == "identifier":
            bindings.append(
                ImportBinding(
                    module,
                    _text(child, source_bytes),
                    target_module,
                    "default",
                    relative_path,
                    line,
                )
            )
        elif child.type == "namespace_import":
            bindings.append(
                ImportBinding(
                    module,
                    _name_of(child, source_bytes),
                    target_module,
                    "",
                    relative_path,
                    line,
                )
            )
        elif child.type == "named_imports":
            for specifier in child.named_children:
                if specifier.type != "import_specifier":
                    continue
                parts = _text(specifier, source_bytes).split(" as ", 1)
                target_symbol = parts[0].strip()
                local_name = parts[1].strip() if len(parts) == 2 else target_symbol
                bindings.append(
                    ImportBinding(
                        module,
                        local_name,
                        target_module,
                        target_symbol,
                        relative_path,
                        line,
                    )
                )
    return bindings


class TreeSitterTypeScriptAnalyzer:
    suffixes = (".ts",)

    def analyze(self, relative_path, source):
        module = module_name_from_path(relative_path)
        source_bytes = source.encode("utf-8")
        tree = _PARSER.parse(source_bytes)
        root = tree.root_node
        parents = _parents(root)

        symbols = []
        symbol_by_node = {}
        for node in _walk(root):
            if node.type not in _DEFINITION_TYPES:
                continue
            name = _name_of(node, source_bytes)
            if not name:
                continue
            if node.type == "class_declaration":
                kind = "class"
            elif node.type == "method_definition":
                parent = parents.get(node)
                owner = _name_of(parent, source_bytes) if parent is not None else ""
                name = f"{owner}.{name}" if owner else name
                kind = "method"
            else:
                kind = "function"
            key = f"{module}::{name}#{kind}#0"
            symbol = Symbol(
                key,
                module,
                name,
                kind,
                relative_path,
                _line(node),
                node.end_point[0] + 1,
            )
            symbols.append(symbol)
            symbol_by_node[node] = symbol

        module_end = max((item.end_line for item in symbols), default=1)
        module_symbol = Symbol(
            f"{module}::<module>#module#0",
            module,
            "<module>",
            "module",
            relative_path,
            1,
            module_end,
        )
        symbols.append(module_symbol)

        import_bindings = []
        concerns = []
        call_sites = []
        has_process_argv = False

        for node in _walk(root):
            if node.type == "import_statement":
                import_bindings.extend(
                    _import_bindings(node, module, relative_path, source_bytes)
                )
            elif node.type == "member_expression":
                qualified = _qualified_member(node, source_bytes)
                parts = tuple(qualified.split("."))
                concern = _MEMBER_CONCERNS.get(parts) if len(parts) == 2 else None
                if (
                    concern is None
                    and parts[:1] == ("process",)
                    and len(parts) >= 2
                    and parts[1].startswith("exit")
                ):
                    concern = ("exit", "entrypoint_only")
                if concern is not None:
                    concerns.append(
                        BoundaryConcernUse(
                            module,
                            concern[0],
                            concern[1],
                            relative_path,
                            _line(node),
                        )
                    )
                    if concern[0] == "argv_parse":
                        has_process_argv = True
            elif node.type in {"call_expression", "new_expression"}:
                callee_node = node.child_by_field_name("function")
                if callee_node is None:
                    callee_node = node.named_children[0] if node.named_children else None
                callee = _qualified_member(callee_node, source_bytes) or _name_of(
                    callee_node, source_bytes
                )
                if not callee:
                    continue
                caller = module_symbol.key
                for parent in _ancestors(node, parents):
                    if parent in symbol_by_node:
                        caller = symbol_by_node[parent].key
                        break
                sites_append = CallSite(
                    caller,
                    callee,
                    "qualified" if "." in callee else "name",
                    relative_path,
                    _line(node),
                )
                call_sites.append(sites_append)

        entrypoint = None
        if has_process_argv and _javascript_entrypoint_path(relative_path):
            entrypoint = Entrypoint(module, relative_path, "javascript")

        return SourceAnalysis(
            entrypoint=entrypoint,
            concerns=tuple(concerns),
            symbols=tuple(symbols),
            import_bindings=tuple(import_bindings),
            call_sites=tuple(call_sites),
        )
