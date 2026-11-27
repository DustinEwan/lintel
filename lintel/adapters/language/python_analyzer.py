"""Python implementation of the source analyzer port."""

import ast

from lintel.core.checker import module_name_from_path
from lintel.core.model import (
    BoundaryConcernUse,
    Entrypoint,
    SourceAnalysis,
    SemanticReview,
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


def _concerns(tree):
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_name = alias.name.split(".", 1)[0]
                if root_name in ENTRYPOINT_ONLY_IMPORTS:
                    found.add(("argv_parse", "entrypoint_only", node.lineno))
                elif root_name in MECHANISM_IMPORTS:
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
        if isinstance(node, ast.Attribute):
            expression = ast.unparse(node)
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
        return SourceAnalysis(
            entrypoint=entrypoint,
            concerns=concerns,
            wrapper_operations=operations,
            reviews=_semantic_reviews(tree, module, relative_path),
        )
