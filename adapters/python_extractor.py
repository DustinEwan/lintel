#!/usr/bin/env python3
"""Extract Python module dependencies as architecture facts."""

import ast
import os

from adapters.extract_common import iter_files, rel, write_json

SUFFIXES = (".py",)


def module_from_relative(relative):
    value = relative[: -len(".py")] if relative.endswith(".py") else relative
    parts = [part for part in value.split("/") if part and part != "."]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def module_name(path, root, source_root):
    absolute = os.path.abspath(path)
    source = os.path.abspath(source_root)
    try:
        in_source_root = os.path.commonpath([absolute, source]) == source
    except ValueError:
        in_source_root = False
    relative = os.path.relpath(absolute, source if in_source_root else root)
    relative = relative.replace(os.sep, "/")
    name = module_from_relative(relative)
    return name or os.path.basename(os.path.abspath(root))


def nearest_module(name, modules):
    target = name
    while target and target not in modules and "." in target:
        target = target.rsplit(".", 1)[0]
    return target if target in modules else None


def resolve_dotted(name, modules, local_top):
    first = name.split(".")[0]
    if first in local_top:
        return nearest_module(name, modules)
    return name


def current_package(current, is_package):
    if is_package:
        return current
    return current.rpartition(".")[0]


def resolve_from(module, names, level, current, is_package, modules, local_top):
    if level == 0:
        prefix = module or ""
    else:
        package = current_package(current, is_package)
        parts = package.split(".") if package else []
        parts = parts[: len(parts) - (level - 1)] if level > 1 else parts
        prefix = ".".join(parts)
        if module:
            prefix = f"{prefix}.{module}" if prefix else module

    targets = []
    for name in names:
        target = f"{prefix}.{name}" if prefix else name
        resolved = resolve_dotted(target, modules, local_top)
        if resolved:
            targets.append(resolved)
    return targets

def literal_int(node):
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    ):
        return node.value
    return None


def keyword_value(call, name):
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def resolve_relative(name, level, package, current, is_package, modules, local_top):
    base = package or current_package(current, is_package)
    parts = base.split(".") if base else []
    if level > 1:
        parts = parts[: max(0, len(parts) - (level - 1))]
    if not parts:
        return None
    dotted = name.lstrip(".")
    target = ".".join(parts + ([dotted] if dotted else []))
    return resolve_dotted(target, modules, local_top)


def dynamic_aliases(tree):
    importlib_names = {"importlib"}
    import_module_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib" or alias.name.startswith("importlib."):
                    importlib_names.add(alias.asname or "importlib")
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("importlib"):
            for alias in node.names:
                if alias.name in ("import_module", "find_spec"):
                    import_module_names.add(alias.asname or alias.name)
    return importlib_names, import_module_names


def dynamic_call_kind(node, importlib_names, import_module_names):
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        if func.id == "__import__":
            return "builtin"
        if func.id in import_module_names:
            return "importlib"
    if isinstance(func, ast.Attribute) and func.attr in ("import_module", "find_spec"):
        if isinstance(func.value, ast.Name) and func.value.id in importlib_names:
            return "importlib"
    return None


def literal_string(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def extract(root):
    source_root = os.path.join(root, "src") if os.path.isdir(os.path.join(root, "src")) else root
    files = list(iter_files(root, SUFFIXES))
    module_by_file = {path: module_name(path, root, source_root) for path in files}
    modules = sorted({name for name in module_by_file.values() if name})
    local_top = {name.split(".")[0] for name in modules}

    dependencies = []
    unparsed = []
    seen = set()

    for path in files:
        source = rel(path, root)
        current = module_by_file[path]
        is_package = os.path.basename(path) == "__init__.py"

        try:
            with open(path, "r", encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
        except SyntaxError as error:
            unparsed.append(
                {
                    "source": source,
                    "line": error.lineno or 1,
                    "reason": f"parse error: {error.msg}",
                }
            )
            continue
        except (OSError, ValueError) as error:
            unparsed.append(
                {"source": source, "line": 1, "reason": f"unreadable source: {error}"}
            )
            continue

        importlib_names, import_module_names = dynamic_aliases(tree)

        def record(target, line, kind):
            if not target or target == current:
                return
            key = (current, target, source, line, kind)
            if key in seen:
                return
            seen.add(key)
            dependencies.append(
                {
                    "from": current,
                    "to": target,
                    "kind": kind,
                    "source": source,
                    "line": line,
                }
            )

        for node in ast.walk(tree):
            dynamic_kind = dynamic_call_kind(node, importlib_names, import_module_names)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    record(resolve_dotted(alias.name, modules, local_top), node.lineno, "import")
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module == "__future__":
                    continue
                names = [alias.name for alias in node.names]
                for target in resolve_from(
                    node.module,
                    names,
                    node.level,
                    current,
                    is_package,
                    modules,
                    local_top,
                ):
                    record(target, node.lineno, "import")
            elif dynamic_kind:
                argument = node.args[0] if node.args else None
                name = literal_string(argument)
                if not name:
                    unparsed.append(
                        {
                            "source": source,
                            "line": node.lineno,
                            "reason": "non-literal dynamic import",
                        }
                    )
                    continue

                leading = len(name) - len(name.lstrip("."))
                resolved = None
                if dynamic_kind == "importlib":
                    if leading:
                        package_node = keyword_value(node, "package")
                        package = (
                            literal_string(package_node)
                            if package_node is not None
                            else None
                        )
                        if package_node is not None and package is None:
                            unparsed.append(
                                {
                                    "source": source,
                                    "line": node.lineno,
                                    "reason": "non-literal dynamic import package",
                                }
                            )
                            continue
                        if package is None:
                            unparsed.append(
                                {
                                    "source": source,
                                    "line": node.lineno,
                                    "reason": "relative dynamic import without package",
                                }
                            )
                            continue
                        resolved = resolve_relative(
                            name,
                            leading,
                            package,
                            current,
                            is_package,
                            modules,
                            local_top,
                        )
                    else:
                        resolved = resolve_dotted(name, modules, local_top)
                else:
                    level_node = keyword_value(node, "level")
                    if level_node is None and len(node.args) >= 5:
                        level_node = node.args[4]
                    level = literal_int(level_node) if level_node is not None else 0
                    if level_node is not None and level is None:
                        unparsed.append(
                            {
                                "source": source,
                                "line": node.lineno,
                                "reason": "non-literal dynamic import level",
                            }
                        )
                        continue
                    if level > 0 or leading:
                        resolved = resolve_relative(
                            name,
                            level or leading,
                            None,
                            current,
                            is_package,
                            modules,
                            local_top,
                        )
                    else:
                        resolved = resolve_dotted(name, modules, local_top)

                if resolved:
                    record(resolved, node.lineno, "dynamic_import")
                else:
                    unparsed.append(
                        {
                            "source": source,
                            "line": node.lineno,
                            "reason": "unresolved relative dynamic import",
                        }
                    )
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("eval", "exec")
            ):
                unparsed.append(
                    {
                        "source": source,
                        "line": node.lineno,
                        "reason": "dynamic code execution can inject imports",
                    }
                )

    return {
        "version": 1,
        "language": "python",
        "modules": [
            {"name": name, "path": rel(path, root)}
            for path, name in sorted(module_by_file.items(), key=lambda item: item[1])
        ],
        "dependencies": dependencies,
        "unparsed": unparsed,
    }


