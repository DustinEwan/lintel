"""Tree-sitter Python analyzer matching the normalized default Python facts."""

import tree_sitter as ts
import tree_sitter_python as tsp

from lintel.core import source_patterns as _patterns
from lintel.core.checker import module_name_from_path
from lintel.core.model import (
    BoundaryConcernUse,
    CallSite,
    Entrypoint,
    ImportBinding,
    SemanticReview,
    SourceAnalysis,
    Symbol,
    UnparsedSource,
    WrapperOperation,
)
from lintel.core.source_patterns import (
    AMBIGUOUS_ANNOTATIONS,
    BOUNDARY_ATTRIBUTES,
    BOUNDARY_IMPORT_MODULES,
    BOUNDARY_IMPORTS,
    CORE_PATH_PREFIXES,
    ENTRYPOINT_ONLY_IMPORTS,
    GOVERNED_REFLECTION_BASES,
    INJECTED_PARAMETER_NAMES,
    LIVE_ARGV_ANNOTATIONS,
    LIVE_ENV_ANNOTATIONS,
    MECHANISM_IMPORTS,
    ENTRYPOINT_PATH_PREFIXES,
    PLAIN_ANNOTATIONS,
    REFLECTED_ATTRIBUTE_NAMES,
    SUBPROCESS_CALLS,
    UNRESOLVED_CLI_MARKERS,
)

_LANGUAGE = ts.Language(tsp.language())
_PARSER = ts.Parser(_LANGUAGE)


def _text(node, source_bytes):
    if node is None:
        return ""
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _line(node):
    return 0 if node is None else node.start_point[0] + 1


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


def _field(node, name):
    return node.child_by_field_name(name) if node is not None else None


def _dotted_name(node, source_bytes):
    if node is None:
        return ""
    if node.type == "identifier":
        return _text(node, source_bytes)
    return _text(node, source_bytes).replace(" ", "").lstrip(".")

def _module_of(node, source_bytes):
    if node is None:
        return ""
    if node.type == "future_import_statement":
        return "__future__"
    return _dotted_name(_field(node, "module_name"), source_bytes)


def _string_value(node, source_bytes):
    if node is None or node.type != "string":
        return None
    parts = [
        _text(child, source_bytes)
        for child in _walk(node)
        if child.type == "string_content"
    ]
    return "".join(parts) if parts else None


def _arguments(node):
    args = _field(node, "arguments")
    if args is None:
        return [], []
    positional = [
        child
        for child in args.named_children
        if child.type != "keyword_argument"
    ]
    keywords = [
        child for child in args.named_children if child.type == "keyword_argument"
    ]
    return positional, keywords


def _same_node(left, right):
    return (
        left is not None
        and right is not None
        and (left.type, left.start_byte, left.end_byte)
        == (right.type, right.start_byte, right.end_byte)
    )


def _import_items(node, source_bytes):
    items = []
    if node.type == "import_statement":
        children = list(node.named_children)
    else:
        module_node = _field(node, "module_name")
        children = [
            child
            for child in node.named_children
            if not _same_node(child, module_node)
        ]
    for child in children:
        if child.type == "import_list":
            items.extend(_import_items_from_children(child.named_children, source_bytes))
        elif child.type in {"aliased_import", "dotted_name", "identifier"}:
            items.extend(_import_items_from_children([child], source_bytes))
    return items


def _import_items_from_children(children, source_bytes):
    items = []
    for child in children:
        if child.type == "aliased_import":
            name = _dotted_name(_field(child, "name"), source_bytes)
            alias = _text(_field(child, "alias"), source_bytes)
        elif child.type in {"dotted_name", "identifier"}:
            name = _dotted_name(child, source_bytes)
            alias = ""
        else:
            continue
        items.append((name, alias))
    return items


def _import_context(root, source_bytes):
    aliases = {}
    bindings = {}
    cli_frameworks = set()
    for node in _walk(root):
        if node.type == "import_statement":
            for name, alias in _import_items(node, source_bytes):
                root_name = name.split(".", 1)[0]
                if root_name in {"typer", "click"}:
                    cli_frameworks.add(root_name)
                aliases[alias or root_name] = root_name
        elif node.type in {"import_from_statement", "future_import_statement"}:
            module = _module_of(node, source_bytes)
            root_name = module.split(".", 1)[0]
            if root_name in {"typer", "click"}:
                cli_frameworks.add(root_name)
            for name, alias in _import_items(node, source_bytes):
                target = f"{module}.{name}" if module else name
                bindings[alias or name] = target
    return aliases, bindings, cli_frameworks


def _canonical(node, aliases, bindings, source_bytes):
    if node is None:
        return None
    if node.type == "identifier":
        name = _text(node, source_bytes)
        return bindings.get(name, aliases.get(name, name))
    if node.type == "attribute":
        base = _canonical(_field(node, "object"), aliases, bindings, source_bytes)
        attribute = _text(_field(node, "attribute"), source_bytes)
        return f"{base}.{attribute}" if base and attribute else None
    if node.type == "call":
        callee = _canonical(_field(node, "function"), aliases, bindings, source_bytes)
        positional, _ = _arguments(node)
        if (
            callee == "importlib.import_module"
            and len(positional) == 1
            and positional[0].type == "string"
        ):
            return _string_value(positional[0], source_bytes)
    return None


def _value_root(node):
    current = node
    while current is not None and current.type in {"attribute", "subscript"}:
        current = _field(current, "object") or _field(current, "value")
    return current


def _assignment_pairs(root, source_bytes):
    pairs = []
    for node in _walk(root):
        if node.type != "assignment":
            continue
        target = _field(node, "left")
        value = _field(node, "right")
        if value is None:
            named = list(node.named_children)
            value = named[-1] if len(named) >= 2 else None
        if target is None or value is None or target.type != "identifier":
            continue
        pairs.append((_line(node), _text(target, source_bytes), value))
    return pairs


def _unresolved_boundary_bindings(root, aliases, imported, source_bytes):
    initial = {
        name
        for name, target in {**aliases, **imported}.items()
        if target in BOUNDARY_IMPORT_MODULES or target in BOUNDARY_ATTRIBUTES
    }
    resolved = dict(imported)
    unresolved = set()
    for _, target, value in sorted(
        _assignment_pairs(root, source_bytes), key=lambda item: item[0]
    ):
        canonical = _canonical(value, aliases, resolved, source_bytes)
        if canonical is None:
            resolved.pop(target, None)
            if target in initial:
                unresolved.add(target)
        else:
            resolved[target] = canonical
            if target in initial and canonical in BOUNDARY_ATTRIBUTES:
                unresolved.discard(target)
    return frozenset(unresolved)


def _value_bindings(root, aliases, imported, unresolved, source_bytes):
    resolved = dict(imported)
    for _, target, value in _assignment_pairs(root, source_bytes):
        root_node = _value_root(value)
        stale = (
            root_node is not None
            and root_node.type == "identifier"
            and _text(root_node, source_bytes) in unresolved
        )
        canonical = _canonical(value, aliases, resolved, source_bytes)
        if canonical is None or stale:
            resolved.pop(target, None)
        else:
            resolved[target] = canonical
    return resolved


def _main_guard(root, source_bytes):
    for node in _walk(root):
        if node.type != "if_statement":
            continue
        condition = _field(node, "condition")
        if condition is None or condition.type != "comparison_operator":
            continue
        children = list(condition.named_children)
        if len(children) < 2:
            continue
        left, right = children[0], children[1]
        left_name = (
            left.type == "identifier" and _text(left, source_bytes) == "__name__"
        )
        right_name = (
            right.type == "identifier" and _text(right, source_bytes) == "__name__"
        )
        left_main = _string_value(left, source_bytes) == "__main__"
        right_main = _string_value(right, source_bytes) == "__main__"
        if (left_name and right_main) or (right_name and left_main):
            return _line(node)
    return 0


def _function_of(node, parents):
    if node is None:
        return None
    if node.type in {"function_definition", "class_definition"}:
        return node
    return None


def _definition(node):
    if node.type != "decorated_definition":
        return node
    for child in node.named_children:
        if child.type in {"function_definition", "class_definition"}:
            return child
    return None


def _decorators(node):
    if node.type != "decorated_definition":
        return []
    return [child for child in node.named_children if child.type == "decorator"]


def _decorator_expression(node, source_bytes):
    children = list(node.named_children)
    if not children:
        return "", None
    expression = children[0]
    return _text(expression, source_bytes), expression


def _decorator_root(expression, source_bytes):
    node = expression
    if node is not None and node.type == "call":
        node = _field(node, "function")
    if node is not None and node.type == "attribute":
        node = _field(node, "object")
    if node is not None and node.type == "identifier":
        return _text(node, source_bytes)
    return ""


def _parameters(node, source_bytes):
    params = _field(node, "parameters")
    if params is None:
        return []
    result = []
    for child in params.named_children:
        if child.type == "identifier":
            result.append((_text(child, source_bytes), None, child))
            continue
        name_node = _field(child, "name")
        if name_node is None:
            for candidate in child.named_children:
                if candidate.type == "identifier":
                    name_node = candidate
                    break
        if name_node is None:
            continue
        annotation = _field(child, "type")
        result.append(
            (_text(name_node, source_bytes), annotation, name_node)
        )
    return result


def _in_core_module(relative_path):
    normalized = str(relative_path).replace("\\", "/")
    return normalized.startswith(CORE_PATH_PREFIXES)


def _is_entrypoint_path(relative_path):
    normalized = str(relative_path).replace("\\", "/")
    return normalized.startswith(ENTRYPOINT_PATH_PREFIXES)


def _is_review_exempt_path(relative_path):
    normalized = "/" + str(relative_path).replace("\\", "/") + "/"
    if _is_entrypoint_path(relative_path):
        return True
    return any(
        f"/{part}/" in normalized for part in _patterns.REVIEW_EXEMPT_PATH_PARTS
    )


def _annotation_kind(annotation, aliases, bindings, source_bytes):
    if annotation is None:
        return "ambiguous"
    parts = set()
    for child in _walk(annotation):
        if child.type == "identifier":
            name = _text(child, source_bytes)
            parts.add(bindings.get(name, aliases.get(name, name)))
        elif child.type == "attribute":
            name = _canonical(child, aliases, bindings, source_bytes)
            if name:
                parts.add(name)
    if any(name in LIVE_ENV_ANNOTATIONS or name.endswith("._Environ") for name in parts):
        return "env"
    if any(
        name in LIVE_ARGV_ANNOTATIONS
        or name.endswith(".ArgumentParser")
        or name.endswith(".ModuleType")
        for name in parts
    ):
        return "argv"
    if not parts or parts & AMBIGUOUS_ANNOTATIONS:
        return "ambiguous"
    if all(name.rsplit(".", 1)[-1] in PLAIN_ANNOTATIONS for name in parts):
        return "plain"
    return "ambiguous"


def _stored_on_self(function, name, source_bytes):
    for node in _walk(function):
        if node.type != "assignment":
            continue
        target = _field(node, "left")
        value = _field(node, "right")
        if (
            target is not None
            and target.type == "attribute"
            and _text(_field(target, "object"), source_bytes) == "self"
            and _text(_field(target, "attribute"), source_bytes) == name
            and value is not None
            and value.type == "identifier"
            and _text(value, source_bytes) == name
        ):
            return True
    return False


def _live_injected_use(function, name, source_bytes):
    for node in _walk(function):
        if node.type != "call":
            continue
        callee = _field(node, "function")
        if (
            callee is not None
            and callee.type == "attribute"
            and _text(_field(callee, "object"), source_bytes) == name
            and _text(_field(callee, "attribute"), source_bytes)
            in {"parse_args", "parse_known_args"}
        ):
            return True
    return False


def _injected_boundary(root, aliases, bindings, relative_path, source_bytes):
    concerns = set()
    reviews = set()
    if not _in_core_module(relative_path):
        return concerns, reviews
    for node in _walk(root):
        if node.type != "function_definition":
            continue
        for name, annotation, _ in _parameters(node, source_bytes):
            if name not in INJECTED_PARAMETER_NAMES:
                continue
            kind = _annotation_kind(annotation, aliases, bindings, source_bytes)
            if kind == "env":
                concerns.add(("env", "mechanism", _line(node)))
            elif kind == "argv":
                concerns.add(("argv_parse", "entrypoint_only", _line(node)))
            elif kind == "ambiguous" and (
                _stored_on_self(node, name, source_bytes)
                or _live_injected_use(node, name, source_bytes)
            ):
                reviews.add((_line(node), f"unresolved injected boundary value {name}"))
    return concerns, reviews


def _first_arg_target(call_node, source_bytes):
    positional, _ = _arguments(call_node)
    if not positional:
        return "unknown"
    first = positional[0]
    if first.type in {"list", "tuple"} and first.named_children:
        first = first.named_children[0]
    value = _string_value(first, source_bytes)
    return value if value is not None else "unknown"


def _concerns(root, relative_path, env_call_patterns, source_bytes):
    aliases, imported, cli_frameworks = _import_context(root, source_bytes)
    unresolved = _unresolved_boundary_bindings(
        root, aliases, imported, source_bytes
    )
    bindings = _value_bindings(root, aliases, imported, unresolved, source_bytes)
    found = set()

    for node in _walk(root):
        if node.type == "import_statement":
            for name, _ in _import_items(node, source_bytes):
                root_name = name.split(".", 1)[0]
                if root_name in ENTRYPOINT_ONLY_IMPORTS:
                    found.add(("argv_parse", "entrypoint_only", _line(node)))
                elif root_name in MECHANISM_IMPORTS:
                    found.add(("logging", "mechanism", _line(node)))
            continue
        if node.type in {"import_from_statement", "future_import_statement"}:
            module = _module_of(node, source_bytes)
            for name, _ in _import_items(node, source_bytes):
                concern = BOUNDARY_IMPORTS.get((module, name))
                if concern is not None:
                    found.add((*concern, _line(node)))
                elif module in ENTRYPOINT_ONLY_IMPORTS:
                    found.add(("argv_parse", "entrypoint_only", _line(node)))
                elif module in MECHANISM_IMPORTS:
                    found.add(("logging", "mechanism", _line(node)))
            continue
        if node.type == "decorated_definition":
            definition = _definition(node)
            if definition is not None and definition.type == "function_definition":
                for decorator in _decorators(node):
                    expression, _ = _decorator_expression(decorator, source_bytes)
                    explicit_cli = expression.startswith(
                        ("click.command", "typer.command")
                    )
                    framework_command = bool(cli_frameworks) and (
                        expression in {"command", "command()"}
                        or expression.endswith((".command", ".command()"))
                    )
                    if explicit_cli or framework_command:
                        found.add(("argv_parse", "entrypoint_only", _line(definition)))

        attribute_base = _field(node, "object")
        if not (
            node.type == "attribute"
            and attribute_base is not None
            and attribute_base.type == "identifier"
            and _text(attribute_base, source_bytes) in unresolved
        ):
            concern = BOUNDARY_ATTRIBUTES.get(
                _canonical(node, aliases, bindings, source_bytes) or ""
            )
            if concern is not None:
                found.add((*concern, _line(node)))

        if node.type == "call":
            callee = _field(node, "function")
            positional, keywords = _arguments(node)
            if (
                callee is not None
                and callee.type == "identifier"
                and _text(callee, source_bytes) == "getattr"
                and len(positional) >= 2
            ):
                base = _canonical(positional[0], aliases, bindings, source_bytes)
                attribute = _string_value(positional[1], source_bytes)
                if base and attribute is not None:
                    reflected = f"{base}.{attribute}"
                    concern = BOUNDARY_ATTRIBUTES.get(reflected)
                    if concern is not None:
                        found.add((*concern, _line(node)))
            if (
                callee is not None
                and callee.type == "identifier"
                and _text(callee, source_bytes) == "print"
            ):
                found.add(("terminal_io", "mechanism", _line(node)))
            call_name = _canonical(callee, aliases, bindings, source_bytes)
            if call_name == "logging.StreamHandler" or (
                call_name == "logging.basicConfig"
                and any(
                    _text(_field(keyword, "name"), source_bytes) == "stream"
                    for keyword in keywords
                )
            ):
                found.add(("terminal_io", "mechanism", _line(node)))
            for pattern in env_call_patterns:
                if call_name == pattern or (
                    call_name is not None and call_name.endswith(f".{pattern}")
                ):
                    found.add(("env", "mechanism", _line(node)))
                    break
            if call_name in {"sys.exit", "os._exit"}:
                found.add(("exit", "entrypoint_only", _line(node)))

        if node.type == "raise_statement":
            exception = _field(node, "exception")
            if exception is None and node.named_children:
                exception = node.named_children[0]
            if (
                exception is not None
                and exception.type == "call"
                and _text(_field(exception, "function"), source_bytes) == "SystemExit"
            ):
                found.add(("exit", "mechanism", _line(node)))

    injected, _ = _injected_boundary(
        root, aliases, bindings, relative_path, source_bytes
    )
    found.update(injected)
    return sorted(found)


def _wrapper_operations(root, module, source_bytes):
    operations = []
    for node in _walk(root):
        if node.type == "import_statement":
            for name, _ in _import_items(node, source_bytes):
                operations.append((module, "import", name, _line(node)))
        elif node.type in {"import_from_statement", "future_import_statement"}:
            imported_from = _module_of(node, source_bytes)
            for name, _ in _import_items(node, source_bytes):
                target = f"{imported_from}.{name}" if imported_from else name
                operations.append((module, "import", target, _line(node)))
        elif node.type == "call":
            callee = _field(node, "function")
            if callee is None:
                continue
            if callee.type == "attribute":
                name = _text(_field(callee, "attribute"), source_bytes)
                base = _text(_field(callee, "object"), source_bytes)
            elif callee.type == "identifier":
                name = _text(callee, source_bytes)
                base = ""
            else:
                continue
            if name in SUBPROCESS_CALLS:
                operations.append(
                    (module, "subprocess", _first_arg_target(node, source_bytes), _line(node))
                )
            elif name in {"Policy", "policy_from_dict"}:
                operations.append((module, "policy_construction", name, _line(node)))
            elif name == "walk":
                operations.append((module, "source_walk", name, _line(node)))
            elif name == "parse" and base == "ast":
                operations.append((module, "parse_source", name, _line(node)))
    return operations


def _semantic_reviews(root, module, relative_path, source_bytes):
    aliases, imported, _ = _import_context(root, source_bytes)
    unresolved = _unresolved_boundary_bindings(
        root, aliases, imported, source_bytes
    )
    bindings = _value_bindings(root, aliases, imported, unresolved, source_bytes)
    parents = _parents(root)
    reviews = set()
    if not _is_review_exempt_path(relative_path):
        for node in _walk(root):
            name = None
            if node.type == "attribute":
                base = _field(node, "object")
                if (
                    base is not None
                    and base.type == "identifier"
                    and _text(_field(node, "attribute"), source_bytes)
                    in REFLECTED_ATTRIBUTE_NAMES
                ):
                    name = _text(base, source_bytes)
            elif node.type == "subscript":
                base = _field(node, "value")
                if (
                    base is not None
                    and base.type == "identifier"
                    and imported.get(_text(base, source_bytes)) in BOUNDARY_ATTRIBUTES
                ):
                    name = _text(base, source_bytes)
            if name in unresolved:
                reviews.add(
                    (
                        _line(node),
                        f"unresolved alias '{name}' may expose boundary state",
                    )
                )
        for node in _walk(root):
            if node.type not in {"import_from_statement", "future_import_statement"}:
                continue
            module_name = _module_of(node, source_bytes)
            if module_name in BOUNDARY_IMPORT_MODULES and any(
                child.type == "wildcard_import" for child in node.named_children
            ):
                reviews.add(
                    (
                        _line(node),
                        f"wildcard import from {module_name} may expose boundary state",
                    )
                )

        known_frameworks = frozenset(
            name
            for name, target in {**aliases, **imported}.items()
            if target.split(".", 1)[0] in ENTRYPOINT_ONLY_IMPORTS
        )
        unknown_frameworks = {
            name
            for name, target in {**aliases, **imported}.items()
            if target.split(".", 1)[0] not in ENTRYPOINT_ONLY_IMPORTS
            and any(marker in target.split(".", 1)[0] for marker in UNRESOLVED_CLI_MARKERS)
        }
        for node in _walk(root):
            if node.type != "decorated_definition":
                continue
            definition = _definition(node)
            if definition is None or definition.type != "function_definition":
                continue
            for decorator in _decorators(node):
                expression, expression_node = _decorator_expression(
                    decorator, source_bytes
                )
                normalized = expression.replace(" ", "")
                is_command = normalized in {
                    "command",
                    "command()",
                    "group",
                    "group()",
                } or normalized.endswith(
                    (".command", ".command()", ".group", ".group()")
                )
                if not is_command:
                    continue
                root_name = _decorator_root(expression_node, source_bytes)
                if root_name in known_frameworks:
                    continue
                if root_name in unknown_frameworks:
                    reviews.add(
                        (
                            _line(definition),
                            "unresolved CLI framework decorator may parse argv",
                        )
                    )

    for node in _walk(root):
        if node.type == "call":
            callee = _field(node, "function")
            positional, _ = _arguments(node)
            if (
                callee is not None
                and callee.type == "identifier"
                and _text(callee, source_bytes) == "getattr"
                and len(positional) >= 2
            ):
                base = _canonical(positional[0], aliases, bindings, source_bytes)
                literal = _string_value(positional[1], source_bytes) is not None
                if base in GOVERNED_REFLECTION_BASES and not literal:
                    reviews.add(
                        (_line(node), f"unresolved dynamic attribute on {base}")
                    )
            if (
                _canonical(callee, aliases, bindings, source_bytes)
                == "importlib.import_module"
                and not (
                    positional
                    and positional[0].type == "string"
                    and _string_value(positional[0], source_bytes) is not None
                )
            ):
                current = node
                parent = parents.get(current)
                while parent is not None:
                    if (
                        parent.type == "attribute"
                        and _text(_field(parent, "attribute"), source_bytes)
                        in REFLECTED_ATTRIBUTE_NAMES
                    ):
                        reviews.add(
                            (_line(node), "unresolved dynamic module access")
                        )
                        break
                    if parent.type == "call":
                        parent_callee = _field(parent, "function")
                        parent_args, _ = _arguments(parent)
                        if (
                            parent_callee is not None
                            and parent_callee.type == "identifier"
                            and _text(parent_callee, source_bytes) == "getattr"
                            and len(parent_args) >= 2
                            and parent_args[0] is current
                            and _string_value(parent_args[1], source_bytes)
                            in REFLECTED_ATTRIBUTE_NAMES
                        ):
                            reviews.add(
                                (_line(node), "unresolved dynamic module access")
                            )
                            break
                    if parent.type == "subscript":
                        current = parent
                        parent = parents.get(parent)
                        continue
                    break

    _, injected = _injected_boundary(
        root, aliases, bindings, relative_path, source_bytes
    )
    reviews.update(injected)
    return tuple(
        SemanticReview(module, relative_path, line, reason)
        for line, reason in sorted(reviews)
    )


def _relative_name(node, parents, source_bytes):
    parts = []
    current = node
    while current is not None:
        if current.type in {"class_definition", "function_definition"}:
            name_node = _field(current, "name")
            parts.append(_text(name_node, source_bytes))
        current = parents.get(current)
    return ".".join(reversed(parts))


def _call_facts(root, module, relative_path, source_bytes):
    parents = _parents(root)
    symbols = []
    bindings = []
    sites = []
    symbol_by_node = {}
    definitions = []

    for node in _walk(root):
        if node.type not in {"class_definition", "function_definition"}:
            continue
        name = _relative_name(node, parents, source_bytes)
        if node.type == "class_definition":
            kind = "class"
        else:
            parent = parents.get(node)
            while parent is not None and parent.type in {
                "decorated_definition",
                "block",
            }:
                parent = parents.get(parent)
            kind = (
                "method"
                if parent is not None and parent.type == "class_definition"
                else "function"
            )
        definitions.append((node, name, kind))

    base_counts = {}
    for _, name, kind in definitions:
        base = f"{module}::{name}#{kind}"
        base_counts[base] = base_counts.get(base, 0) + 1
    used = {}
    for node, name, kind in definitions:
        base = f"{module}::{name}#{kind}"
        index = used.get(base, 0)
        used[base] = index + 1
        key = base if base_counts[base] == 1 else f"{base}#{index}"
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
        wrapper = parents.get(node)
        while wrapper is not None and wrapper.type == "decorated_definition":
            symbol_by_node[wrapper] = symbol
            wrapper = parents.get(wrapper)

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

    for node in _walk(root):
        if node.type == "import_statement":
            for name, alias in _import_items(node, source_bytes):
                root_name = name.split(".", 1)[0]
                bindings.append(
                    ImportBinding(
                        module,
                        alias or root_name,
                        root_name,
                        "",
                        relative_path,
                        _line(node),
                    )
                )
        elif node.type in {"import_from_statement", "future_import_statement"}:
            target = _module_of(node, source_bytes)
            for name, alias in _import_items(node, source_bytes):
                bindings.append(
                    ImportBinding(
                        module,
                        alias or name,
                        target,
                        name,
                        relative_path,
                        _line(node),
                    )
                )

    for node in _walk(root):
        if node.type != "call":
            continue
        callee = _field(node, "function")
        if callee is None:
            continue
        if callee.type == "identifier":
            callee_name = _text(callee, source_bytes)
            hint = "name"
        elif callee.type == "attribute":
            base = _field(callee, "object")
            attribute = _field(callee, "attribute")
            if base is None or base.type != "identifier" or attribute is None:
                continue
            callee_name = (
                f"{_text(base, source_bytes)}.{_text(attribute, source_bytes)}"
            )
            hint = "qualified"
        else:
            continue
        caller = module_symbol.key
        for parent in _ancestors(node, parents):
            if parent in symbol_by_node and symbol_by_node[parent].kind != "class":
                caller = symbol_by_node[parent].key
                break
        sites.append(
            CallSite(caller, callee_name, hint, relative_path, _line(node))
        )

    return tuple(symbols), tuple(bindings), tuple(sites)


class TreeSitterPythonAnalyzer:
    suffixes = (".py",)

    def __init__(self, env_call_patterns=None):
        self._env_call_patterns = (
            None if env_call_patterns is None else frozenset(env_call_patterns)
        )

    @property
    def env_call_patterns(self):
        if self._env_call_patterns is None:
            return _patterns.env_call_patterns()
        return self._env_call_patterns

    def analyze(self, relative_path, source):
        module = module_name_from_path(relative_path)
        source_bytes = source.encode("utf-8")
        root = _PARSER.parse(source_bytes).root_node
        if root.has_error:
            return SourceAnalysis(
                unparsed=(
                    UnparsedSource(relative_path, _line(root) or 1, "invalid syntax"),
                )
            )

        entrypoint = (
            Entrypoint(module, relative_path, "python")
            if _main_guard(root, source_bytes)
            else None
        )
        concerns = tuple(
            BoundaryConcernUse(module, concern, category, relative_path, line)
            for concern, category, line in _concerns(
                root, relative_path, self.env_call_patterns, source_bytes
            )
        )
        operations = tuple(
            WrapperOperation(module, operation, target, relative_path, line)
            for operation_module, operation, target, line in _wrapper_operations(
                root, module, source_bytes
            )
            if operation_module == module
        )
        symbols, bindings, sites = _call_facts(root, module, relative_path, source_bytes)
        return SourceAnalysis(
            entrypoint=entrypoint,
            concerns=concerns,
            wrapper_operations=operations,
            reviews=_semantic_reviews(root, module, relative_path, source_bytes),
            symbols=symbols,
            import_bindings=bindings,
            call_sites=sites,
        )
