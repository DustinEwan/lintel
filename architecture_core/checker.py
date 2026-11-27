from fnmatch import fnmatchcase
from posixpath import splitext

from .model import Region, Violation
from .rules import rule_spec


def match_any(value, patterns):
    return any(fnmatchcase(value, pattern) for pattern in patterns or [])


def region_for(module, policy):
    for region in policy.regions:
        if match_any(module, region.patterns):
            return region
    return Region(policy.default_region, False, ())


def forbidden_patterns(policy, region):
    forbidden = policy.forbidden
    patterns = list(forbidden.get("global", ()))
    patterns.extend(forbidden.get(region.name, ()))
    if region.core:
        patterns.extend(forbidden.get("core", ()))
    return patterns


def violation(rule, message, **fields):
    spec = rule_spec(rule)
    if spec:
        fields.setdefault("fix", spec.fix)
    return Violation(rule, message, fields)


def module_name_from_path(path):
    normalized = str(path or "").replace("\\", "/")
    stem = splitext(normalized)[0]
    name = stem.replace("/", ".").replace("-", "_")
    if name.endswith(".__init__"):
        name = name[: -len(".__init__")]
    return name


def _scope_assignments(path, facts):
    return [item for item in facts.scopes if item.path == path]


def _scope_names(path, facts):
    return {item.scope for item in _scope_assignments(path, facts)}


def _module_paths(facts):
    return {module.name: module.path for module in facts.modules}


def check_edges(facts, policy):
    violations = []
    allowed = policy.allowed

    for dep in facts.dependencies:
        source = dep.source_module
        target = dep.target_module
        source_region = region_for(source, policy)
        target_region = region_for(target, policy)
        location = f"{dep.source or '?'}:{dep.line or '?'}"

        if source_region.core and not target_region.core:
            violations.append(
                violation(
                    "core_outward",
                    f"core module {source} depends on outer module {target} ({location})",
                    **{"from": source, "to": target, "location": location},
                )
            )

        if source_region.core and match_any(
            target, forbidden_patterns(policy, source_region)
        ):
            violations.append(
                violation(
                    "forbidden_import",
                    f"core module {source} imports forbidden {target} ({location})",
                    **{"from": source, "to": target, "location": location},
                )
            )

        if target_region.name not in allowed.get(source_region.name, ()):
            violations.append(
                violation(
                    "edge_not_allowed",
                    f"{source_region.name} module {source} may not depend on "
                    f"{target_region.name} module {target} ({location})",
                    **{
                        "from": source,
                        "to": target,
                        "source_region": source_region.name,
                        "target_region": target_region.name,
                        "location": location,
                    },
                )
            )

    return tuple(violations)


def find_cycles(facts):
    graph = {}
    for dep in facts.dependencies:
        graph.setdefault(dep.source_module, set()).add(dep.target_module)

    color = {}
    stack = []
    seen = set()
    cycles = []

    def visit(node):
        color[node] = 1
        stack.append(node)
        for nxt in sorted(graph.get(node, ())):
            state = color.get(nxt, 0)
            if state == 0:
                visit(nxt)
            elif state == 1:
                start = stack.index(nxt) if nxt in stack else 0
                cycle = stack[start:] + [nxt]
                key = tuple(cycle)
                if key not in seen:
                    seen.add(key)
                    cycles.append(cycle)
        stack.pop()
        color[node] = 2

    for node in sorted(graph):
        if color.get(node, 0) == 0:
            visit(node)

    return [
        violation(
            "cycle",
            "dependency cycle: " + " -> ".join(cycle),
            cycle=cycle,
        )
        for cycle in cycles
    ]


def check_unparsed(facts):
    return [
        violation(
            "unparsed_source",
            "unparsed source: " + item.reason + f" ({item.source}:{item.line})",
            source=item.source,
            line=item.line,
            reason=item.reason,
        )
        for item in facts.unparsed
    ]


def _excluded_source(source, facts, policy):
    return any(
        item.path == source and item.scope in policy.excluded_scopes
        for item in facts.scopes
    )


def check_semantic_review(facts, policy):
    return [
        violation(
            "semantic_review",
            "semantic review: " + item.reason + f" ({item.source}:{item.line})",
            module=item.module,
            source=item.source,
            line=item.line,
            reason=item.reason,
        )
        for item in facts.reviews
        if not _excluded_source(item.source, facts, policy)
    ]


def check_executables(facts, policy):
    violations = []
    root = policy.entrypoints_root.rstrip("/")
    declared_paths = {item.path for item in policy.executables}
    module_paths = {module.path for module in facts.modules}

    for item in policy.executables:
        location = item.path
        if root and not (item.path == root or item.path.startswith(root + "/")):
            violations.append(
                violation(
                    "entrypoint_root_mismatch",
                    f"executable {item.name} is outside {policy.entrypoints_root}",
                    **{"executable": item.name, "location": location},
                )
            )
        owner = region_for(module_name_from_path(item.path), policy).name
        if owner != item.owner:
            violations.append(
                violation(
                    "executable_owner_mismatch",
                    f"executable {item.name} is owned by {owner}, declared {item.owner}",
                    **{
                        "executable": item.name,
                        "owner": item.owner,
                        "actual": owner,
                        "location": location,
                    },
                )
            )
        if item.path in module_paths:
            continue
        if splitext(item.path)[1].lower() in {".py", ".js", ".mjs", ".ts", ".tsx"}:
            violations.append(
                violation(
                    "missing_executable",
                    f"declared executable has no module facts: {item.path}",
                    **{"executable": item.name, "location": location},
                )
            )

    artifact_wrappers = {
        item.source: item.wrapper for item in policy.build_artifacts
    }
    for item in facts.entrypoints:
        if item.path in declared_paths:
            continue
        scopes = _scope_names(item.path, facts)
        if scopes & set(policy.excluded_scopes):
            continue
        if "build_artifact" in scopes:
            if item.path not in artifact_wrappers:
                violations.append(
                    violation(
                        "direct_artifact_invocation",
                        f"build artifact has no declared wrapper: {item.path}",
                        **{"location": item.path},
                    )
                )
            continue
        violations.append(
            violation(
                "undeclared_executable",
                f"discovered executable is not declared: {item.path}",
                **{"location": item.path, "kind": item.kind},
            )
        )

    return tuple(violations)


def check_scopes(facts, policy):
    violations = []
    grouped = {}
    for item in facts.scopes:
        grouped.setdefault(item.path, []).append(item)

    for path, items in grouped.items():
        max_priority = max((item.priority for item in items), default=0)
        seen = set()
        for item in items:
            key = (item.scope, item.priority)
            if key in seen:
                continue
            seen.add(key)
            if item.priority != max_priority:
                continue
            if item.expected_scope and item.scope != item.expected_scope:
                violations.append(
                    violation(
                        "scope_convention_mismatch",
                        f"{path} is scoped {item.scope}, expected {item.expected_scope}",
                        **{
                            "location": path,
                            "scope": item.scope,
                            "expected": item.expected_scope,
                        },
                    )
                )
        priorities = {}
        for item in items:
            priorities.setdefault(item.priority, set()).add(item.scope)
        if any(len(scopes) > 1 for scopes in priorities.values()):
            violations.append(
                violation(
                    "scope_overlap",
                    f"path matches ambiguous scopes: {path}",
                    **{"location": path, "scopes": sorted({i.scope for i in items})},
                )
            )

    module_paths = _module_paths(facts)
    forbidden = {tuple(edge) for edge in policy.forbidden_scope_edges}
    seen_edges = set()
    for dep in facts.dependencies:
        source_path = dep.source
        target_path = module_paths.get(dep.target_module, "")
        source_scopes = _scope_names(source_path, facts)
        target_scopes = _scope_names(target_path, facts)
        for source_scope in source_scopes:
            for target_scope in target_scopes:
                edge = (source_scope, target_scope)
                if edge in forbidden and edge not in seen_edges:
                    seen_edges.add(edge)
                    violations.append(
                        violation(
                            "forbidden_scope_edge",
                            f"scope {source_scope} may not depend on {target_scope}",
                            **{
                                "from": dep.source_module,
                                "to": dep.target_module,
                                "source_scope": source_scope,
                                "target_scope": target_scope,
                                "location": f"{dep.source}:{dep.line}",
                            },
                        )
                    )

    for artifact in policy.build_artifacts:
        if "build_artifact" not in _scope_names(artifact.source, facts):
            violations.append(
                violation(
                    "unscoped_build_artifact",
                    f"build artifact is missing build_artifact scope: {artifact.source}",
                    **{"location": artifact.source},
                )
            )

    return tuple(violations)


def check_boundary_concerns(facts, policy):
    violations = []
    seen = set()
    for item in facts.concerns:
        region = region_for(item.module, policy)
        scopes = _scope_names(item.source, facts)
        key = (item.module, item.concern, item.source, item.line)
        if key in seen:
            continue
        seen.add(key)
        if region.name == "entrypoints" or "build_artifact" in scopes:
            continue
        if item.category == "entrypoint_only":
            rule = "core_cli_concern" if region.core else "adapter_cli_concern"
        else:
            allowed = policy.boundary_allowed_regions.get(
                item.category, ("adapters", "infrastructure", "entrypoints")
            )
            if region.name in allowed:
                continue
            rule = "core_cli_concern" if region.core else "adapter_cli_concern"
        violations.append(
            violation(
                rule,
                f"{region.name} module {item.module} owns {item.category} concern {item.concern}",
                **{
                    "from": item.module,
                    "concern": item.concern,
                    "category": item.category,
                    "location": f"{item.source}:{item.line}",
                },
            )
        )
    return tuple(violations)


def check_use_cases(facts, policy):
    allowed = policy.use_case_allowed_imports or (
        "architecture_core.ports",
        "architecture_core.model",
        "typing*",
        "dataclasses*",
    )
    violations = []
    for dep in facts.dependencies:
        if not dep.source_module.startswith("architecture_core.use_cases."):
            continue
        if match_any(dep.target_module, allowed):
            continue
        violations.append(
            violation(
                "use_case_dependency",
                f"use case {dep.source_module} depends on {dep.target_module}",
                **{
                    "from": dep.source_module,
                    "to": dep.target_module,
                    "location": f"{dep.source}:{dep.line}",
                },
            )
        )
    return tuple(violations)


def check_wrapper_operations(facts, policy):
    violations = []
    allowed_imports = policy.wrapper_allowed_imports
    forbidden_imports = policy.wrapper_forbidden_imports
    allowed_commands = policy.wrapper_allowed_commands

    for item in facts.wrapper_operations:
        location = f"{item.source}:{item.line}"
        if item.operation == "import":
            if match_any(item.target, forbidden_imports):
                violations.append(
                    violation(
                        "fat_entrypoint",
                        f"entrypoint {item.module} imports forbidden {item.target}",
                        **{"from": item.module, "target": item.target, "location": location},
                    )
                )
            elif allowed_imports and not match_any(item.target, allowed_imports):
                violations.append(
                    violation(
                        "fat_entrypoint",
                        f"entrypoint {item.module} imports unmapped {item.target}",
                        **{"from": item.module, "target": item.target, "location": location},
                    )
                )
            continue

        if item.operation == "subprocess" and item.target != "unknown":
            command = item.target.split("/", 1)[-1]
            if not match_any(command, allowed_commands):
                violations.append(
                    violation(
                        "fat_entrypoint",
                        f"entrypoint {item.module} runs undeclared command {command}",
                        **{"from": item.module, "target": command, "location": location},
                    )
                )
            continue

        if item.operation in {"policy_construction", "source_walk", "parse_source"}:
            violations.append(
                violation(
                    "fat_entrypoint",
                    f"entrypoint {item.module} contains {item.operation}",
                    **{
                        "from": item.module,
                        "operation": item.operation,
                        "location": location,
                    },
                )
            )

    return tuple(violations)


def check(facts, policy):
    result = []
    result.extend(check_edges(facts, policy))
    result.extend(find_cycles(facts))
    result.extend(check_unparsed(facts))
    result.extend(check_executables(facts, policy))
    result.extend(check_scopes(facts, policy))
    result.extend(check_boundary_concerns(facts, policy))
    result.extend(check_semantic_review(facts, policy))
    result.extend(check_use_cases(facts, policy))
    result.extend(check_wrapper_operations(facts, policy))
    return tuple(result)
