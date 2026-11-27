#!/usr/bin/env python3
"""Discover executable surfaces, boundary concerns, scopes, and wrapper operations."""

import ast
import os
import re
from fnmatch import fnmatchcase

from architecture_core.checker import module_name_from_path

from adapters.extract_common import SKIP_DIRS, rel

PY_SUFFIXES = (".py",)
NATIVE_SUFFIXES = (".go", ".rs", ".mjs", ".js", ".ts", ".tsx")

PY_ENTRYPOINT_ONLY_IMPORTS = {"argparse", "typer", "click"}
PY_MECHANISM_IMPORTS = {"logging"}

NATIVE_PATTERNS = (
    ("flag.Parse", "argv_parse", "entrypoint_only"),
    ("std::env::args", "argv_parse", "entrypoint_only"),
    ("process.argv", "argv_parse", "entrypoint_only"),
    ("os.Exit", "exit", "entrypoint_only"),
    ("std::process::exit", "exit", "entrypoint_only"),
    ("SystemExit", "exit", "mechanism"),
    ("process.exit", "exit", "entrypoint_only"),
    ("os.Getenv", "env", "mechanism"),
    ("std::env::var", "env", "mechanism"),
    ("process.env", "env", "mechanism"),
    ("log.", "logging", "mechanism"),
    ("fmt.Print", "terminal_io", "mechanism"),
    ("println!", "terminal_io", "mechanism"),
    ("console.log", "terminal_io", "mechanism"),
)

LEADING_NUMBER = re.compile(r"^(?:\d+):")


def _walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in SKIP_DIRS
            and not name.startswith(".")
            and not name.endswith(".egg-info")
        )
        for name in sorted(filenames):
            yield os.path.join(dirpath, name)


def _read_lines(path):
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.readlines()


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


def _python_concerns(tree):
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_name = alias.name.split(".", 1)[0]
                if root_name in PY_ENTRYPOINT_ONLY_IMPORTS:
                    found.add(("argv_parse", "entrypoint_only", node.lineno, alias.name))
                elif root_name in PY_MECHANISM_IMPORTS:
                    found.add(("logging", "mechanism", node.lineno, alias.name))
            continue
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if module == "sys" and alias.name == "argv":
                    found.add(("argv", "entrypoint_only", node.lineno, "sys.argv"))
                elif module == "sys" and alias.name == "exit":
                    found.add(("exit", "entrypoint_only", node.lineno, "sys.exit"))
                elif module == "os" and alias.name == "environ":
                    found.add(("env", "mechanism", node.lineno, "os.environ"))
                elif module == "os" and alias.name == "_exit":
                    found.add(("exit", "entrypoint_only", node.lineno, "os._exit"))
                elif module in PY_ENTRYPOINT_ONLY_IMPORTS:
                    found.add(("argv_parse", "entrypoint_only", node.lineno, module))
            continue
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            if getattr(node.exc.func, "id", "") == "SystemExit":
                found.add(("exit", "mechanism", node.lineno, "SystemExit"))
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                found.add(("terminal_io", "mechanism", node.lineno, "print"))
            expression = ast.unparse(node)
            if expression.startswith("sys.exit(") or expression.startswith("os._exit("):
                found.add(("exit", "entrypoint_only", node.lineno, expression))
    return sorted(found)


def _python_wrapper_operations(tree, module):
    operations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                operations.append(
                    (module, "import", alias.name, node.lineno)
                )
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            for alias in node.names:
                target = f"{module_name}.{alias.name}" if module_name else alias.name
                operations.append((module, "import", target, node.lineno))
        elif isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Attribute):
                name = node.func.attr
            elif isinstance(node.func, ast.Name):
                name = node.func.id
            if name in {"run", "call", "Popen", "check_call", "check_output"}:
                target = "unknown"
                if node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
                    first = node.args[0].elts[0] if node.args[0].elts else None
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        target = first.value
                operations.append((module, "subprocess", target, node.lineno))
            elif name == "Policy" or name == "policy_from_dict":
                operations.append((module, "policy_construction", name, node.lineno))
            elif name == "walk":
                operations.append((module, "source_walk", name, node.lineno))
            elif name == "parse" and isinstance(node.func, ast.Attribute):
                if getattr(node.func.value, "id", "") == "ast":
                    operations.append((module, "parse_source", name, node.lineno))
    return operations


def _native_entrypoint(lines, suffix):
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if suffix == ".go" and re.match(r"func\s+main\s*\(", stripped):
            return number
        if suffix == ".rs" and re.match(r"(?:pub\s+)?fn\s+main\s*\(", stripped):
            return number
        if suffix in {".mjs", ".js", ".ts", ".tsx"} and "process.argv" in stripped:
            return number
    return 0


def _native_concerns(lines):
    found = set()
    for number, line in enumerate(lines, 1):
        for token, concern, category in NATIVE_PATTERNS:
            if token in line:
                found.add((concern, category, number, token))
    return sorted(found)


def _expected_scope(path, conventions):
    best = ""
    scope = ""
    for prefix, candidate in conventions.items():
        if path.startswith(prefix) and len(prefix) > len(best):
            best = prefix
            scope = candidate
    return scope


def discover(root, policy, entrypoints_root):
    entrypoints = []
    concerns = []
    wrapper_operations = []
    unparsed = []
    entrypoint_prefix = entrypoints_root.rstrip("/") + "/"

    for path in _walk(root):
        relative = rel(path, root)
        suffix = os.path.splitext(relative)[1]
        module = module_name_from_path(relative)
        if suffix in PY_SUFFIXES:
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    tree = ast.parse(handle.read(), filename=relative)
            except (SyntaxError, UnicodeDecodeError) as error:
                message = getattr(error, "msg", str(error))
                unparsed.append(
                    {"source": relative, "line": getattr(error, "lineno", 0) or 0, "reason": message}
                )
                continue

            guard_line = _main_guard(tree)
            if guard_line:
                entrypoints.append(
                    {"module": module, "path": relative, "kind": "python"}
                )
            for concern, category, line, target in _python_concerns(tree):
                concerns.append(
                    {
                        "module": module,
                        "concern": concern,
                        "category": category,
                        "source": relative,
                        "line": line,
                    }
                )
            if relative.startswith(entrypoint_prefix):
                for operation_module, operation, target, line in _python_wrapper_operations(
                    tree, module
                ):
                    wrapper_operations.append(
                        {
                            "module": operation_module,
                            "operation": operation,
                            "target": target,
                            "source": relative,
                            "line": line,
                        }
                    )
            continue

        if suffix in NATIVE_SUFFIXES:
            lines = _read_lines(path)
            main_line = _native_entrypoint(lines, suffix)
            if main_line:
                entrypoints.append(
                    {"module": module, "path": relative, "kind": suffix.lstrip(".")}
                )
            for concern, category, line, target in _native_concerns(lines):
                concerns.append(
                    {
                        "module": module,
                        "concern": concern,
                        "category": category,
                        "source": relative,
                        "line": line,
                    }
                )

    assignments = []
    for path in _walk(root):
        relative = rel(path, root)
        expected = _expected_scope(relative, policy.scope_conventions)
        for scope, patterns in policy.scopes.items():
            for pattern in patterns:
                if fnmatchcase(relative, pattern):
                    assignments.append(
                        {
                            "path": relative,
                            "scope": scope,
                            "pattern": pattern,
                            "priority": policy.scope_priorities.get(scope, 100),
                            "expected_scope": expected,
                        }
                    )

    return {
        "entrypoints": entrypoints,
        "concerns": concerns,
        "wrapper_operations": wrapper_operations,
        "scopes": assignments,
        "unparsed": unparsed,
    }
