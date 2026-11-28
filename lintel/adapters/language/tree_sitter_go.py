"""Tree-sitter Go analyzer emitting normalized source facts."""

import re

import tree_sitter as ts
import tree_sitter_go as tsgo

from lintel.core.checker import module_name_from_path
from lintel.core.model import (
    BoundaryConcernUse,
    CallSite,
    Entrypoint,
    ImportBinding,
    SourceAnalysis,
    Symbol,
)

_LANGUAGE = ts.Language(tsgo.language())
_PARSER = ts.Parser(_LANGUAGE)

_EXACT_SELECTORS = {
    ("flag", "Parse"): ("argv_parse", "entrypoint_only"),
    ("os", "Exit"): ("exit", "entrypoint_only"),
    ("os", "Getenv"): ("env", "mechanism"),
}
_IDENTIFIER_TYPES = {
    "identifier",
    "field_identifier",
    "package_identifier",
    "type_identifier",
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


def _qualified_selector(node, source_bytes):
    if node is None or node.type != "selector_expression":
        return ""
    base_node = node.child_by_field_name("operand")
    field_node = node.child_by_field_name("field")
    if base_node is None or field_node is None:
        return ""
    base = _qualified_selector(base_node, source_bytes) or _name_of(
        base_node, source_bytes
    )
    return f"{base}.{_text(field_node, source_bytes)}" if base else ""


def _import_bindings(node, module, relative_path, source_bytes):
    bindings = []
    for spec in _walk(node):
        if spec.type != "import_spec":
            continue
        children = list(spec.named_children)
        if not children:
            continue
        path_node = children[-1]
        path = _text(path_node, source_bytes).strip('"`')
        alias = _text(children[0], source_bytes) if len(children) > 1 else ""
        local_name = alias or path.rsplit("/", 1)[-1]
        bindings.append(
            ImportBinding(
                module,
                local_name,
                path.replace("/", "."),
                "",
                relative_path,
                _line(spec),
            )
        )
    return bindings


class TreeSitterGoAnalyzer:
    suffixes = (".go",)

    def analyze(self, relative_path, source):
        module = module_name_from_path(relative_path)
        source_bytes = source.encode("utf-8")
        root = _PARSER.parse(source_bytes).root_node
        parents = _parents(root)

        symbols = []
        symbol_by_node = {}
        entrypoint = None
        for node in _walk(root):
            if node.type not in {"function_declaration", "method_declaration"}:
                continue
            name = _name_of(node, source_bytes)
            if not name:
                continue
            if node.type == "method_declaration":
                receiver = node.child_by_field_name("receiver_type")
                receiver_text = _text(receiver, source_bytes) if receiver else ""
                owner = re.sub(r"^\*", "", receiver_text).split(".")[-1]
                name = f"{owner}.{name}" if owner else name
                kind = "method"
            else:
                kind = "function"
                if name == "main":
                    entrypoint = Entrypoint(module, relative_path, "go")
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
        for node in _walk(root):
            if node.type == "import_declaration":
                import_bindings.extend(
                    _import_bindings(node, module, relative_path, source_bytes)
                )
            elif node.type == "selector_expression":
                qualified = _qualified_selector(node, source_bytes)
                parts = tuple(qualified.split("."))
                concern = _EXACT_SELECTORS.get(parts) if len(parts) == 2 else None
                if concern is None and len(parts) == 2:
                    if parts[0] == "log":
                        concern = ("logging", "mechanism")
                    elif parts[0] == "fmt" and parts[1].startswith("Print"):
                        concern = ("terminal_io", "mechanism")
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
            elif node.type == "call_expression":
                callee_node = node.child_by_field_name("function")
                callee = _qualified_selector(callee_node, source_bytes) or _name_of(
                    callee_node, source_bytes
                )
                if not callee:
                    continue
                caller = module_symbol.key
                for parent in _ancestors(node, parents):
                    if parent in symbol_by_node:
                        caller = symbol_by_node[parent].key
                        break
                call_sites.append(
                    CallSite(
                        caller,
                        callee,
                        "qualified" if "." in callee else "name",
                        relative_path,
                        _line(node),
                    )
                )

        return SourceAnalysis(
            entrypoint=entrypoint,
            concerns=tuple(concerns),
            symbols=tuple(symbols),
            import_bindings=tuple(import_bindings),
            call_sites=tuple(call_sites),
        )
