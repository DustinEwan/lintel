"""Python implementation of the source analyzer port.

The ``[analysis].env_call_patterns`` key lists dotted call names known to read
the environment (for example ``"Config.from_env"``). The config adapter
installs those patterns through ``configure_env_call_patterns`` before facts
are collected; no library call is assumed to read the environment by default.
"""

import ast

from lintel.core.checker import module_name_from_path
from lintel.core.model import (
    BoundaryConcernUse,
    CallSite,
    Entrypoint,
    ImportBinding,
    SourceAnalysis,
    SemanticReview,
    Symbol,
    UnparsedSource,
    WrapperOperation,
)

ENTRYPOINT_ONLY_IMPORTS = {"argparse", "typer", "click"}
MECHANISM_IMPORTS = {"logging"}
SUBPROCESS_CALLS = {"run", "call", "Popen", "check_call", "check_output"}

BOUNDARY_IMPORTS = {
    ("sys", "argv"): ("argv", "entrypoint_only"),
    ("sys", "exit"): ("exit", "entrypoint_only"),
    ("os", "environ"): ("env", "mechanism"),
    ("os", "_exit"): ("exit", "entrypoint_only"),
}
BOUNDARY_ATTRIBUTES = {
    "sys.argv": ("argv", "entrypoint_only"),
    "sys.exit": ("exit", "entrypoint_only"),
    "os.environ": ("env", "mechanism"),
    "os._exit": ("exit", "entrypoint_only"),
}
REFLECTED_ATTRIBUTE_NAMES = frozenset(
    name.rsplit(".", 1)[-1] for name in BOUNDARY_ATTRIBUTES
)
GOVERNED_REFLECTION_BASES = frozenset({"os", "sys", "os.environ"})
INJECTED_PARAMETER_NAMES = frozenset({"args", "argv", "env"})
CORE_PATH_PREFIXES = ("lintel/core/", "core/")
LIVE_ENV_ANNOTATIONS = frozenset({"_Environ", "os._Environ"})
LIVE_ARGV_ANNOTATIONS = frozenset(
    {
        "ArgumentParser",
        "argparse.ArgumentParser",
        "ModuleType",
        "types.ModuleType",
    }
)
PLAIN_ANNOTATIONS = frozenset(
    {
        "Any",
        "Iterable",
        "Literal",
        "Mapping",
        "MutableMapping",
        "Namespace",
        "Optional",
        "Sequence",
        "Union",
        "bool",
        "bytes",
        "dict",
        "float",
        "frozenset",
        "int",
        "list",
        "set",
        "str",
        "tuple",
    }
)
AMBIGUOUS_ANNOTATIONS = frozenset({"Any", "object"})

_configured_env_call_patterns = frozenset()


def configure_env_call_patterns(patterns):
    """Install configured env-reading call names for default analyzers."""
    global _configured_env_call_patterns
    _configured_env_call_patterns = frozenset(patterns or ())


def _main_guard(tree):
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if isinstance(test, ast.Compare) and ast.unparse(test).replace("'", '"') in {
            '__name__ == "__main__"',
            '"__main__" == __name__',
        }:
            return node.lineno
    return 0


def _import_context(tree):
    aliases = {}
    bindings = {}
    cli_frameworks = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                aliases[alias.asname or root] = root
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".", 1)[0]
            if root in {"typer", "click"}:
                cli_frameworks.add(root)
            for alias in node.names:
                if alias.name == "*":
                    continue
                target = f"{module}.{alias.name}" if module else alias.name
                bindings[alias.asname or alias.name] = target
    return aliases, bindings, cli_frameworks


def _canonical_name(node, aliases, bindings):
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return bindings.get(node.id, aliases.get(node.id, node.id))
    if isinstance(node, ast.Attribute):
        base = _canonical_name(node.value, aliases, bindings)
        return f"{base}.{node.attr}" if base else None
    if isinstance(node, ast.Call):
        if _canonical_name(node.func, aliases, bindings) == "importlib.import_module":
            if (
                len(node.args) == 1
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                return node.args[0].value
    return None


def _canonical_attribute(node, aliases):
    return _canonical_name(node, aliases, {})


def _value_bindings(tree, aliases, imported):
    """Resolve simple alias/re-export assignments to canonical dotted names."""
    resolved = dict(imported)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target, value = node.targets[0].id, node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            target, value = node.target.id, node.value
        else:
            continue
        canonical = _canonical_name(value, aliases, resolved)
        if canonical is None:
            resolved.pop(target, None)
        else:
            resolved[target] = canonical
    return resolved


def _boundary_concern(node, aliases, bindings):
    return BOUNDARY_ATTRIBUTES.get(_canonical_name(node, aliases, bindings))


def _reflection_target(node, aliases, bindings):
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
    ):
        return None
    base = _canonical_name(node.args[0], aliases, bindings)
    attribute = node.args[1]
    if base and isinstance(attribute, ast.Constant) and isinstance(attribute.value, str):
        return f"{base}.{attribute.value}"
    return None


def _in_core_module(relative_path):
    normalized = str(relative_path).replace("\\", "/")
    return normalized.startswith(CORE_PATH_PREFIXES)


def _annotation_kind(annotation, aliases, bindings):
    if annotation is None:
        return "ambiguous"
    parts = set()
    for child in ast.walk(annotation):
        if isinstance(child, ast.Name):
            parts.add(bindings.get(child.id, aliases.get(child.id, child.id)))
        elif isinstance(child, ast.Attribute):
            name = _canonical_name(child, aliases, bindings)
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


def _stored_on_self(function, name):
    for node in ast.walk(function):
        targets = []
        value = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and target.attr == name
                and isinstance(value, ast.Name)
                and value.id == name
            ):
                return True
    return False


def _injected_boundary(tree, aliases, bindings, relative_path):
    concerns = set()
    reviews = set()
    if not _in_core_module(relative_path):
        return concerns, reviews
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        arguments = [
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ]
        for argument in arguments:
            if argument.arg not in INJECTED_PARAMETER_NAMES:
                continue
            kind = _annotation_kind(argument.annotation, aliases, bindings)
            if kind == "env":
                concerns.add(("env", "mechanism", node.lineno))
            elif kind == "argv":
                concerns.add(("argv_parse", "entrypoint_only", node.lineno))
            elif kind == "ambiguous" and _stored_on_self(node, argument.arg):
                reviews.add((node.lineno, f"unresolved injected boundary value {argument.arg}"))
    return concerns, reviews


def _concerns(tree, relative_path, env_call_patterns):
    aliases, imported, cli_frameworks = _import_context(tree)
    bindings = _value_bindings(tree, aliases, imported)
    found = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in ENTRYPOINT_ONLY_IMPORTS:
                    found.add(("argv_parse", "entrypoint_only", node.lineno))
                elif root in MECHANISM_IMPORTS:
                    found.add(("logging", "mechanism", node.lineno))
            continue
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imported_concern = BOUNDARY_IMPORTS.get((module, alias.name))
                if imported_concern is not None:
                    found.add((*imported_concern, node.lineno))
                elif module in ENTRYPOINT_ONLY_IMPORTS:
                    found.add(("argv_parse", "entrypoint_only", node.lineno))
                elif module in MECHANISM_IMPORTS:
                    found.add(("logging", "mechanism", node.lineno))
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                expression = ast.unparse(decorator)
                explicit_cli = expression.startswith(("click.command", "typer.command"))
                framework_command = bool(cli_frameworks) and (
                    expression in {"command", "command()"}
                    or expression.endswith((".command", ".command()"))
                )
                if explicit_cli or framework_command:
                    found.add(("argv_parse", "entrypoint_only", node.lineno))

        concern = _boundary_concern(node, aliases, bindings)
        if concern is not None:
            found.add((*concern, node.lineno))
        reflected = _reflection_target(node, aliases, bindings)
        if reflected is not None:
            concern = BOUNDARY_ATTRIBUTES.get(reflected)
            if concern is not None:
                found.add((*concern, node.lineno))

        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            if getattr(node.exc.func, "id", "") == "SystemExit":
                found.add(("exit", "mechanism", node.lineno))
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                found.add(("terminal_io", "mechanism", node.lineno))
            call_name = _canonical_name(node.func, aliases, bindings)
            if call_name == "logging.StreamHandler" or (
                call_name == "logging.basicConfig"
                and any(keyword.arg == "stream" for keyword in node.keywords)
            ):
                found.add(("terminal_io", "mechanism", node.lineno))
            for pattern in env_call_patterns:
                if call_name == pattern or (
                    call_name is not None and call_name.endswith(f".{pattern}")
                ):
                    found.add(("env", "mechanism", node.lineno))
                    break
            expression = ast.unparse(node)
            if expression.startswith("sys.exit(") or expression.startswith("os._exit("):
                found.add(("exit", "entrypoint_only", node.lineno))

    injected, _ = _injected_boundary(tree, aliases, bindings, relative_path)
    found.update(injected)
    return sorted(found)


def _wrapper_operations(tree, module):
    operations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                operations.append((module, "import", alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            imported_from = node.module or ""
            for alias in node.names:
                target = (
                    f"{imported_from}.{alias.name}" if imported_from else alias.name
                )
                operations.append((module, "import", target, node.lineno))
        elif isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Attribute):
                name = node.func.attr
            elif isinstance(node.func, ast.Name):
                name = node.func.id
            if name in SUBPROCESS_CALLS:
                target = "unknown"
                if node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
                    first = node.args[0].elts[0] if node.args[0].elts else None
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        target = first.value
                operations.append((module, "subprocess", target, node.lineno))
            elif name in {"Policy", "policy_from_dict"}:
                operations.append((module, "policy_construction", name, node.lineno))
            elif name == "walk":
                operations.append((module, "source_walk", name, node.lineno))
            elif name == "parse" and isinstance(node.func, ast.Attribute):
                if getattr(node.func.value, "id", "") == "ast":
                    operations.append((module, "parse_source", name, node.lineno))
    return operations


def _semantic_reviews(tree, module, relative_path):
    aliases, imported, _ = _import_context(tree)
    bindings = _value_bindings(tree, aliases, imported)
    parents = _parents(tree)
    reviews = set()

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
        ):
            base = _canonical_name(node.args[0], aliases, bindings)
            attribute = node.args[1]
            literal = (
                isinstance(attribute, ast.Constant)
                and isinstance(attribute.value, str)
            )
            if base in GOVERNED_REFLECTION_BASES and not literal:
                reviews.add((node.lineno, f"unresolved dynamic attribute on {base}"))

        if (
            isinstance(node, ast.Call)
            and _canonical_name(node.func, aliases, bindings)
            == "importlib.import_module"
            and not (
                node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            )
        ):
            current = node
            parent = parents.get(current)
            while parent is not None:
                if (
                    isinstance(parent, ast.Attribute)
                    and parent.attr in REFLECTED_ATTRIBUTE_NAMES
                ):
                    reviews.add((node.lineno, "unresolved dynamic module access"))
                    break
                if (
                    isinstance(parent, ast.Call)
                    and isinstance(parent.func, ast.Name)
                    and parent.func.id == "getattr"
                    and len(parent.args) >= 2
                    and parent.args[0] is current
                    and isinstance(parent.args[1], ast.Constant)
                    and isinstance(parent.args[1].value, str)
                    and parent.args[1].value in REFLECTED_ATTRIBUTE_NAMES
                ):
                    reviews.add((node.lineno, "unresolved dynamic module access"))
                    break
                if isinstance(parent, ast.Subscript):
                    current = parent
                    parent = parents.get(parent)
                    continue
                break

    _, injected = _injected_boundary(tree, aliases, bindings, relative_path)
    reviews.update(injected)
    return tuple(
        SemanticReview(module, relative_path, line, reason)
        for line, reason in sorted(reviews)
    )


def _parents(tree):
    return {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }


def _relative_name(node, parents):
    parts = []
    current = node
    while current is not None:
        if isinstance(current, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            parts.append(current.name)
        current = parents.get(current)
    return ".".join(reversed(parts))


def _enclosing_function(node, parents):
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
        current = parents.get(current)
    return None


def _call_facts(tree, module, relative_path):
    parents = _parents(tree)
    symbols = []
    bindings = []
    sites = []
    symbol_by_node = {}
    definitions = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = _relative_name(node, parents)
        if isinstance(node, ast.ClassDef):
            kind = "class"
        elif isinstance(parents.get(node), ast.ClassDef):
            kind = "method"
        else:
            kind = "function"
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
            node.lineno,
            getattr(node, "end_lineno", None) or node.lineno,
        )
        symbols.append(symbol)
        symbol_by_node[id(node)] = symbol

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

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                bindings.append(
                    ImportBinding(
                        module, alias.asname or root, root, "", relative_path, node.lineno
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            target = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                bindings.append(
                    ImportBinding(
                        module,
                        alias.asname or alias.name,
                        target,
                        alias.name,
                        relative_path,
                        node.lineno,
                    )
                )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            callee = func.id
            hint = "name"
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            callee = f"{func.value.id}.{func.attr}"
            hint = "qualified"
        else:
            continue
        caller_node = _enclosing_function(node, parents)
        caller = (
            symbol_by_node[id(caller_node)].key
            if caller_node is not None and id(caller_node) in symbol_by_node
            else module_symbol.key
        )
        sites.append(CallSite(caller, callee, hint, relative_path, node.lineno))

    return tuple(symbols), tuple(bindings), tuple(sites)


class PythonSourceAnalyzer:
    suffixes = (".py",)

    def __init__(self, env_call_patterns=None):
        self._env_call_patterns = (
            None if env_call_patterns is None else frozenset(env_call_patterns)
        )

    @property
    def env_call_patterns(self):
        if self._env_call_patterns is None:
            return _configured_env_call_patterns
        return self._env_call_patterns

    def analyze(self, relative_path, source):
        module = module_name_from_path(relative_path)
        try:
            tree = ast.parse(source, filename=relative_path)
        except (SyntaxError, UnicodeDecodeError) as error:
            message = getattr(error, "msg", str(error))
            return SourceAnalysis(
                unparsed=(
                    UnparsedSource(
                        relative_path, getattr(error, "lineno", 0) or 0, message
                    ),
                )
            )

        entrypoint = None
        if _main_guard(tree):
            entrypoint = Entrypoint(module, relative_path, "python")

        concerns = tuple(
            BoundaryConcernUse(module, concern, category, relative_path, line)
            for concern, category, line in _concerns(
                tree, relative_path, self.env_call_patterns
            )
        )
        operations = tuple(
            WrapperOperation(module, operation, target, relative_path, line)
            for operation_module, operation, target, line in _wrapper_operations(
                tree, module
            )
            if operation_module == module
        )
        symbols, bindings, sites = _call_facts(tree, module, relative_path)
        return SourceAnalysis(
            entrypoint=entrypoint,
            concerns=concerns,
            wrapper_operations=operations,
            reviews=_semantic_reviews(tree, module, relative_path),
            symbols=symbols,
            import_bindings=bindings,
            call_sites=sites,
        )
