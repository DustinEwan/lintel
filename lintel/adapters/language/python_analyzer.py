"""Python implementation of the source analyzer port."""

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


def _canonical_attribute(node, aliases):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return ".".join((aliases.get(node.id, node.id), *reversed(parts)))


def _concerns(tree):
    found = set()
    aliases = {}
    cli_frameworks = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                aliases[alias.asname or root] = root
                if root in {"typer", "click"}:
                    cli_frameworks.add(root)
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root in {"typer", "click"}:
                cli_frameworks.add(root)

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
                if module == "sys" and alias.name == "argv":
                    found.add(("argv", "entrypoint_only", node.lineno))
                elif module == "sys" and alias.name == "exit":
                    found.add(("exit", "entrypoint_only", node.lineno))
                elif module == "os" and alias.name == "environ":
                    found.add(("env", "mechanism", node.lineno))
                elif module == "os" and alias.name == "_exit":
                    found.add(("exit", "entrypoint_only", node.lineno))
                elif module in ENTRYPOINT_ONLY_IMPORTS:
                    found.add(("argv_parse", "entrypoint_only", node.lineno))
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
        if isinstance(node, ast.Attribute):
            expression = _canonical_attribute(node, aliases) or ast.unparse(node)
            if expression == "sys.argv":
                found.add(("argv", "entrypoint_only", node.lineno))
            elif expression == "os.environ":
                found.add(("env", "mechanism", node.lineno))
            elif expression == "sys.exit":
                found.add(("exit", "entrypoint_only", node.lineno))
            elif expression == "os._exit":
                found.add(("exit", "entrypoint_only", node.lineno))
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            if getattr(node.exc.func, "id", "") == "SystemExit":
                found.add(("exit", "mechanism", node.lineno))
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                found.add(("terminal_io", "mechanism", node.lineno))
            expression = ast.unparse(node)
            if expression.startswith("sys.exit(") or expression.startswith("os._exit("):
                found.add(("exit", "entrypoint_only", node.lineno))
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
    reviews = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            target = f"{node.args[0].id}.{node.args[1].value}"
            if target in {"os.environ", "sys.argv", "sys.exit", "os._exit"}:
                reviews.append((node.lineno, f"dynamic access to {target}"))
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "importlib.import_module":
            reviews.append((node.lineno, "dynamic module loading"))
    return tuple(
        SemanticReview(module, relative_path, line, reason)
        for line, reason in sorted(set(reviews))
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
            for concern, category, line in _concerns(tree)
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
