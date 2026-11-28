"""Tree-sitter Rust analyzer emitting normalized source facts."""

import re

import tree_sitter as ts
import tree_sitter_rust as tsr

from lintel.core.checker import module_name_from_path
from lintel.core.model import (
    BoundaryConcernUse,
    CallSite,
    Entrypoint,
    ImportBinding,
    SemanticReview,
    SourceAnalysis,
    Symbol,
)

_LANGUAGE = ts.Language(tsr.language())
_PARSER = ts.Parser(_LANGUAGE)

_EXACT_PATHS = {
    "std::env::args": ("argv_parse", "entrypoint_only"),
    "std::env::args_os": ("argv_parse", "entrypoint_only"),
    "std::process::exit": ("exit", "entrypoint_only"),
    "std::env::var": ("env", "mechanism"),
    "std::env::var_os": ("env", "mechanism"),
    "std::io::stdout": ("terminal_io", "mechanism"),
    "std::io::stderr": ("terminal_io", "mechanism"),
}
_MACRO_CONCERNS = {
    "println": ("terminal_io", "mechanism"),
    "print": ("terminal_io", "mechanism"),
    "eprintln": ("terminal_io", "mechanism"),
    "eprint": ("terminal_io", "mechanism"),
    "std::println": ("terminal_io", "mechanism"),
    "std::print": ("terminal_io", "mechanism"),
    "std::eprintln": ("terminal_io", "mechanism"),
    "std::eprint": ("terminal_io", "mechanism"),
    "info": ("logging", "mechanism"),
    "warn": ("logging", "mechanism"),
    "error": ("logging", "mechanism"),
    "log::info": ("logging", "mechanism"),
    "log::warn": ("logging", "mechanism"),
    "log::error": ("logging", "mechanism"),
}
_BENIGN_MACROS = frozenset(
    {
        "assert", "assert_eq", "assert_ne", "debug_assert", "debug_assert_eq",
        "debug_assert_ne", "cfg", "cfg_attr", "column", "concat", "file",
        "format", "format_args", "include", "include_bytes", "include_str",
        "line", "matches", "module_path", "panic", "select", "stringify",
        "todo", "unimplemented", "unreachable", "vec",
    }
)
_MACRO_RE = re.compile(r"(?<![A-Za-z0-9_:])[A-Za-z_][A-Za-z0-9_]*\s*!(?=\s*[({])")
_CLI_DERIVE_CONCERN_RE = re.compile(
    r"(?i)#\s*\[\s*derive\s*\([^)]*\bParser\b[^)]*\)\s*\]"
)
_CLI_UNENUMERATED_RE = re.compile(
    r"(?i)#\s*\[\s*(?:derive\s*\([^)]*\bArgs\b[^)]*\)|command\b|clap\b)"
)
_BOUNDARY_TOKENS = tuple(_EXACT_PATHS) + ("println", "eprintln", "print", "eprint")


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
    if node.type in {"identifier", "type_identifier", "field_identifier"}:
        return _text(node, source_bytes)
    named = node.child_by_field_name("name")
    if named is not None:
        return _text(named, source_bytes)
    for child in node.named_children:
        if child.type == "identifier":
            return _text(child, source_bytes)
        break
    return ""


def _path_of(node, source_bytes):
    if node is None:
        return ""
    if node.type in {"scoped_identifier", "identifier"}:
        return re.sub(r"\s*::\s*", "::", _text(node, source_bytes))
    return ""


def _use_aliases(node, source_bytes, prefix=""):
    kind = node.type
    if kind in {"identifier", "scoped_identifier"}:
        raw = re.sub(r"\s*::\s*", "::", _text(node, source_bytes))
        if raw == "self" and prefix:
            path = prefix.rstrip("::")
            local = path.rsplit("::", 1)[-1]
        else:
            path = prefix + raw
            local = path.rsplit("::", 1)[-1]
        return [(local, path)]
    if kind == "scoped_use_list":
        children = list(node.named_children)
        if not children:
            return []
        next_prefix = prefix + _text(children[0], source_bytes) + "::"
        result = []
        for child in children[1:]:
            result.extend(_use_aliases(child, source_bytes, next_prefix))
        return result
    if kind == "use_list":
        result = []
        for child in node.named_children:
            result.extend(_use_aliases(child, source_bytes, prefix))
        return result
    if kind == "use_as_clause":
        children = list(node.named_children)
        if len(children) < 2:
            return []
        alias = _text(children[-1], source_bytes)
        return [(alias, path) for _, path in _use_aliases(children[0], source_bytes, prefix)]
    return []


def _canonical_path(path, aliases):
    parts = path.split("::")
    if len(parts) > 1 and parts[0] in aliases:
        return aliases[parts[0]] + "::" + "::".join(parts[1:])
    return aliases.get(path, path)


class TreeSitterRustAnalyzer:
    suffixes = (".rs",)

    def analyze(self, relative_path, source):
        module = module_name_from_path(relative_path)
        source_bytes = source.encode("utf-8")
        root = _PARSER.parse(source_bytes).root_node
        parents = _parents(root)

        aliases = {}
        import_bindings = []
        for node in _walk(root):
            if node.type != "use_declaration":
                continue
            for child in node.named_children:
                for local, path in _use_aliases(child, source_bytes):
                    aliases[local] = path
                    import_bindings.append(
                        ImportBinding(
                            module,
                            local,
                            path.rsplit("::", 1)[0] if "::" in path else path,
                            path.rsplit("::", 1)[-1],
                            relative_path,
                            _line(node),
                        )
                    )

        symbols = []
        symbol_by_node = {}
        entrypoint = None
        for node in _walk(root):
            if node.type not in {"function_item", "struct_item", "enum_item", "trait_item"}:
                continue
            name = _name_of(node, source_bytes)
            if not name:
                continue
            if node.type == "function_item":
                owner = ""
                for parent in _ancestors(node, parents):
                    if parent.type in {"impl_item", "trait_item"}:
                        owner = _name_of(parent, source_bytes)
                        break
                kind = "method" if owner else "function"
                if owner:
                    name = f"{owner}.{name}"
                elif name == "main":
                    entrypoint = Entrypoint(module, relative_path, "rust")
            else:
                kind = {
                    "struct_item": "class",
                    "enum_item": "enum",
                    "trait_item": "trait",
                }[node.type]
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

        concerns = []
        reviews = []
        for node in _walk(root):
            if node.type == "macro_definition":
                body = _text(node, source_bytes)
                if _MACRO_RE.search(body) or any(
                    token in body for token in _BOUNDARY_TOKENS
                ):
                    reviews.append(
                        SemanticReview(
                            module,
                            relative_path,
                            _line(node),
                            "macro_rules! body contains boundary-shaped token",
                        )
                    )
            elif node.type == "macro_invocation":
                callee_node = node.child_by_field_name("function")
                if callee_node is None:
                    callee_node = next(iter(node.named_children), None)
                macro_path = _canonical_path(_path_of(callee_node, source_bytes), aliases)
                concern = _MACRO_CONCERNS.get(macro_path)
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
                elif macro_path and "::" not in macro_path and macro_path not in _BENIGN_MACROS:
                    reviews.append(
                        SemanticReview(
                            module,
                            relative_path,
                            _line(node),
                            f"unknown macro '{macro_path}' "
                            "may expand to a boundary operation",
                        )
                    )
            elif node.type == "call_expression":
                callee_node = node.child_by_field_name("function")
                path = _canonical_path(_path_of(callee_node, source_bytes), aliases)
                concern = _EXACT_PATHS.get(path)
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
            elif node.type == "attribute_item":
                attribute = _text(node, source_bytes)
                if _CLI_DERIVE_CONCERN_RE.search(attribute):
                    concerns.append(
                        BoundaryConcernUse(
                            module,
                            "argv_parse",
                            "entrypoint_only",
                            relative_path,
                            _line(node),
                        )
                    )
                elif _CLI_UNENUMERATED_RE.search(attribute):
                    reviews.append(
                        SemanticReview(
                            module,
                            relative_path,
                            _line(node),
                            "unresolved CLI framework idiom may parse argv",
                        )
                    )

        call_sites = []
        for node in _walk(root):
            if node.type != "call_expression":
                continue
            callee_node = node.child_by_field_name("function")
            callee = _canonical_path(_path_of(callee_node, source_bytes), aliases)
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
                    "qualified" if "::" in callee else "name",
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
            reviews=tuple(reviews),
        )
