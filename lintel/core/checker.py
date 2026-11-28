from fnmatch import fnmatchcase
from posixpath import splitext

from . import review
from .callgraph import concern_symbols, relevant_unresolved_reviews, resolve_calls
from .model import BoundaryConcernUse, Dependency, Region, SemanticReview, Violation, replace
from .ratchet import violation_fingerprint
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


def check_semantic_review(facts, policy, decisions=None):
    result = []
    selected = () if decisions is None else decisions
    by_fingerprint = {item.fingerprint: item for item in selected}
    threshold = float(policy.semantic_decision.get("min_confidence", 0.85))

    for item in facts.reviews:
        if _excluded_source(item.source, facts, policy):
            continue
        finding = violation(
            "semantic_review",
            "semantic review: " + item.reason + f" ({item.source}:{item.line})",
            module=item.module,
            source=item.source,
            line=item.line,
            location=f"{item.source}:{item.line}",
            reason=item.reason,
        )
        fingerprint = violation_fingerprint(finding)
        decision = by_fingerprint.get(fingerprint)
        if (
            decision is None
            or not review.is_decision(decision.decision)
            or float(decision.confidence) < threshold
        ):
            result.append(finding)
            continue
        if decision.decision == "compliant":
            continue
        result.append(
            violation(
                "semantic_review",
                f"semantic decision {decision.decision}: {decision.reason} "
                f"({item.source}:{item.line})",
                module=item.module,
                source=item.source,
                line=item.line,
                location=f"{item.source}:{item.line}",
                reason=item.reason,
                decision=decision.decision,
                decision_confidence=float(decision.confidence),
                decision_model=decision.model,
                decision_schema_version=decision.schema_version,
                evidence_hash=decision.evidence_hash,
                state_hash=decision.state_hash,
            )
        )
    return tuple(result)


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
        if _excluded_source(item.source, facts, policy):
            continue
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
        "lintel.core.ports",
        "lintel.core.model",
        "typing*",
        "dataclasses*",
    )
    violations = []
    for dep in facts.dependencies:
        if not dep.source_module.startswith("lintel.core.use_cases."):
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


MAX_TRANSITIVE_DEPTH = 3
BOUNDARY_REVIEW_CHARS = 200
_DEFAULT_MECHANISM_REGIONS = ("adapters", "infrastructure", "entrypoints", "external")


def _bounded_reason(reason):
    text = " ".join(str(reason).split())
    if len(text) <= BOUNDARY_REVIEW_CHARS:
        return text
    return text[: BOUNDARY_REVIEW_CHARS - 3] + "..."


def _normalized_path(path):
    return str(path or "").replace("\\", "/").lstrip("./")


def _wrapper_module(facts, wrapper):
    names = {wrapper, module_name_from_path(wrapper)}
    candidates = []
    for module in facts.modules:
        path_name = module_name_from_path(module.path)
        if (
            module.name in names
            or path_name in names
            or module.name.endswith("." + wrapper)
            or path_name.endswith("." + wrapper)
        ):
            candidates.append(module)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (0 if item.path.endswith(".py") else 1, item.path),
    )


def _declared_wrapper_target(target, policy):
    normalized = _normalized_path(target)
    artifacts = {_normalized_path(item.source) for item in policy.build_artifacts}
    stems = {splitext(item)[0] for item in artifacts}
    wrappers = {item.wrapper for item in policy.build_artifacts}
    commands = set(policy.wrapper_allowed_commands)
    return target in wrappers or normalized in artifacts | stems or target in commands


def _artifact_concerns(facts, source):
    normalized = _normalized_path(source)
    module = next(
        (item for item in facts.modules if _normalized_path(item.path) == normalized),
        None,
    )
    names = {module_name_from_path(source)}
    if module is not None:
        names.add(module.name)
    return [
        item
        for item in facts.concerns
        if _normalized_path(item.source) == normalized or item.module in names
    ]


def _is_wrapper_invocation(item, wrapper_module, wrapper, artifact_source, policy):
    if item.operation != "subprocess" or item.target == "unknown":
        return False
    names = {wrapper, module_name_from_path(wrapper)}
    if wrapper_module is not None:
        names.update(
            (wrapper_module.name, module_name_from_path(wrapper_module.path))
        )
    if item.module not in names and module_name_from_path(item.source) not in names:
        return False
    target = _normalized_path(item.target)
    artifact = _normalized_path(artifact_source)
    stem = splitext(artifact)[0]
    basename = artifact.rsplit("/", 1)[-1]
    stem_name = stem.rsplit("/", 1)[-1]
    if target in {artifact, stem} or target.endswith(
        ("/" + basename, "/" + stem_name)
    ):
        return True
    return target in set(policy.wrapper_allowed_commands)


def _wrapper_extra_concern(facts, wrapper_module, wrapper):
    names = {wrapper, module_name_from_path(wrapper)}
    paths = {_normalized_path(wrapper)}
    if wrapper_module is not None:
        names.update(
            (wrapper_module.name, module_name_from_path(wrapper_module.path))
        )
        paths.add(_normalized_path(wrapper_module.path))
    for item in facts.concerns:
        if item.module not in names and _normalized_path(item.source) not in paths:
            continue
        if item.concern in {"argv_parse", "exit"}:
            continue
        return item
    return None


def _artifact_sources(facts, policy):
    declared = {_normalized_path(item.source) for item in policy.build_artifacts}
    scoped = {
        _normalized_path(item.path)
        for item in facts.scopes
        if item.scope == "build_artifact"
    }
    return sorted(declared | scoped)


def wrapper_concern_attributions(facts, policy):
    """Attribute native artifact concerns to their declared wrapper surface."""
    declarations = {
        _normalized_path(item.source): item.wrapper for item in policy.build_artifacts
    }
    result = []
    for source in _artifact_sources(facts, policy):
        wrapper = declarations.get(source)
        if not wrapper:
            continue
        concerns = _artifact_concerns(facts, source)
        if not concerns:
            continue
        module = _wrapper_module(facts, wrapper)
        invocations = [
            item
            for item in facts.wrapper_operations
            if _is_wrapper_invocation(item, module, wrapper, source, policy)
        ]
        if not invocations:
            continue
        invocation = min(invocations, key=lambda item: (item.source, item.line))
        owner = module.name if module is not None else wrapper
        for concern in concerns:
            result.append(
                BoundaryConcernUse(
                    owner,
                    concern.concern,
                    concern.category,
                    invocation.source,
                    invocation.line,
                )
            )
    return tuple(result)


def wrapper_boundary_reviews(facts, policy):
    """Return bounded SEM-10 reviews for uncovered or over-broad wrappers."""
    declarations = {
        _normalized_path(item.source): item.wrapper for item in policy.build_artifacts
    }
    reviews = []
    for source in _artifact_sources(facts, policy):
        concerns = _artifact_concerns(facts, source)
        if not concerns or source not in declarations:
            continue
        wrapper = declarations[source]
        module = _wrapper_module(facts, wrapper)
        owner = module.name if module is not None else wrapper
        invocations = [
            item
            for item in facts.wrapper_operations
            if _is_wrapper_invocation(item, module, wrapper, source, policy)
        ]
        if not invocations:
            first = min(concerns, key=lambda item: (item.source, item.line))
            reviews.append(
                SemanticReview(
                    owner,
                    first.source,
                    first.line,
                    _bounded_reason(
                        f"SEM-10 declared wrapper {owner} has no matching "
                        f"invocation for native artifact {source}"
                    ),
                )
            )
            continue
        extra = _wrapper_extra_concern(facts, wrapper_module=module, wrapper=wrapper)
        if extra is not None:
            reviews.append(
                SemanticReview(
                    owner,
                    extra.source,
                    extra.line,
                    _bounded_reason(
                        f"SEM-10 declared wrapper {owner} has extra boundary "
                        f"concern {extra.concern} at {extra.source}:{extra.line}"
                    ),
                )
            )
    return tuple(reviews)


def check_native_wrapper_boundaries(facts, policy, decisions=()):
    violations = []
    declarations = {_normalized_path(item.source) for item in policy.build_artifacts}
    for source in _artifact_sources(facts, policy):
        if source in declarations:
            continue
        concerns = _artifact_concerns(facts, source)
        if not concerns:
            continue
        first = min(concerns, key=lambda item: (item.source, item.line))
        violations.append(
            violation(
                "direct_artifact_invocation",
                f"native build artifact {source} owns {first.concern} "
                "without a declared wrapper",
                source=source,
                location=f"{first.source}:{first.line}",
                concern=first.concern,
            )
        )

    attributed = wrapper_concern_attributions(facts, policy)
    if attributed:
        violations.extend(
            check_boundary_concerns(replace(facts, concerns=attributed), policy)
        )
    reviews = wrapper_boundary_reviews(facts, policy)
    if reviews:
        violations.extend(
            check_semantic_review(replace(facts, reviews=reviews), policy, decisions)
        )
    return tuple(violations)


def _mechanism_regions(policy):
    return set(
        policy.boundary_allowed_regions.get("mechanism", _DEFAULT_MECHANISM_REGIONS)
    )


def _concern_region_allowed(module, category, policy, facts):
    region = region_for(module, policy)
    if region.name == "entrypoints":
        return True
    paths = _module_paths(facts)
    if "build_artifact" in _scope_names(paths.get(module, ""), facts):
        return True
    return category == "mechanism" and region.name in _mechanism_regions(policy)


def transitive_boundary_concerns(facts, policy):
    """Propagate owned mechanism concerns backwards along dependency edges."""
    concerns = [
        item
        for item in facts.concerns
        if item.category == "mechanism" and not _excluded_source(item.source, facts, policy)
    ]
    reviews = []
    local_dependencies = []
    known_edges = {
        (dep.source_module, dep.target_module) for dep in facts.dependencies
    }
    for item in facts.wrapper_operations:
        if item.operation != "subprocess" or item.target == "unknown":
            continue
        if not _declared_wrapper_target(item.target, policy):
            continue
        target_module = _wrapper_module(facts, item.target)
        if target_module is None:
            if region_for(item.module, policy).core:
                reviews.append(
                    SemanticReview(
                        item.module,
                        item.source,
                        item.line,
                        _bounded_reason(
                            f"SEM-15 wrapper target '{item.target}' cannot be resolved"
                        ),
                    )
                )
            continue
        if not any(
            concern.module == target_module.name and concern.category == "mechanism"
            for concern in concerns
        ):
            continue
        edge = (item.module, target_module.name)
        if edge in known_edges:
            continue
        known_edges.add(edge)
        local_dependencies.append(
            Dependency(
                item.module,
                target_module.name,
                source=item.source,
                line=item.line,
            )
        )

    reverse = {}
    for dep in (*facts.dependencies, *local_dependencies):
        if dep.source_module and dep.target_module and dep.source_module != dep.target_module:
            reverse.setdefault(dep.target_module, []).append(dep)
    arrivals = {}
    allowed_mechanism = _mechanism_regions(policy)
    for concern in concerns:
        frontier = {concern.module}
        seen = set(frontier)
        for _ in range(MAX_TRANSITIVE_DEPTH):
            following = set()
            for owner in sorted(frontier):
                owner_region = region_for(owner, policy)
                if not owner_region.core and owner_region.name not in allowed_mechanism:
                    continue
                for dep in sorted(
                    reverse.get(owner, ()),
                    key=lambda item: (item.source, item.line, item.source_module),
                ):
                    importer = dep.source_module
                    if importer in seen or _excluded_source(dep.source, facts, policy):
                        continue
                    source_region = region_for(importer, policy)
                    target_region = region_for(dep.target_module, policy)
                    if (
                        not source_region.core
                        and target_region.name
                        not in policy.allowed.get(source_region.name, ())
                    ):
                        continue
                    following.add(importer)
                    key = (importer, concern.concern, concern.category)
                    compliant = _concern_region_allowed(
                        importer, concern.category, policy, facts
                    )
                    arrivals.setdefault(key, set()).add(
                        (source_region.name, compliant, dep.source, dep.line)
                    )
            frontier = following - seen
            seen |= frontier
            if not frontier:
                break

    synthetic = {}
    for key, options in sorted(arrivals.items()):
        importer, concern_name, category = key
        chosen = min(options, key=lambda item: (item[2], item[3], item[0]))
        source, line = chosen[2], chosen[3]
        if len({item[1] for item in options}) > 1:
            reviews.append(
                SemanticReview(
                    importer,
                    source,
                    line,
                    _bounded_reason(
                        f"SEM-15 mixed policy paths carry {concern_name} "
                        f"into {importer}; human review required"
                    ),
                )
            )
            continue
        fact = BoundaryConcernUse(importer, concern_name, category, source, line)
        if fact not in facts.concerns:
            synthetic[key] = fact
    return tuple(synthetic.values()), tuple(reviews)


def check_transitive_boundary_access(facts, policy, decisions=()):
    synthetic, reviews = transitive_boundary_concerns(facts, policy)
    result = []
    if synthetic:
        result.extend(
            check_boundary_concerns(replace(facts, concerns=synthetic), policy)
        )
    if reviews:
        result.extend(
            check_semantic_review(replace(facts, reviews=reviews), policy, decisions)
        )
    return tuple(result)

MAX_HELPER_CALL_DEPTH = 4


def check_helper_laundering(facts, policy, decisions=()):
    symbols = {item.key: item for item in facts.symbols}
    edges, _ = resolve_calls(facts)

    frontier = concern_symbols(facts)

    if not frontier:
        return ()

    synthetic = []
    seen = set(frontier)
    for _ in range(MAX_HELPER_CALL_DEPTH):
        next_frontier = {}
        for edge in edges:
            concern = frontier.get(edge.callee)
            if concern is None or edge.caller in seen or edge.caller not in symbols:
                continue
            seen.add(edge.caller)
            caller = symbols[edge.caller]
            synthetic.append(
                BoundaryConcernUse(
                    caller.module,
                    concern.concern,
                    concern.category,
                    edge.source,
                    edge.line,
                )
            )
            next_frontier[edge.caller] = concern
        frontier = next_frontier
        if not frontier:
            break

    result = list(
        check_boundary_concerns(replace(facts, concerns=tuple(synthetic)), policy)
    )
    unresolved = relevant_unresolved_reviews(facts)
    if unresolved:
        result.extend(
            check_semantic_review(replace(facts, reviews=unresolved), policy, decisions)
        )
    return tuple(result)


def check(facts, policy, decisions=()):
    result = []
    result.extend(check_native_wrapper_boundaries(facts, policy, decisions))
    result.extend(check_transitive_boundary_access(facts, policy, decisions))
    result.extend(check_edges(facts, policy))
    result.extend(find_cycles(facts))
    result.extend(check_unparsed(facts))
    result.extend(check_executables(facts, policy))
    result.extend(check_scopes(facts, policy))
    result.extend(check_boundary_concerns(facts, policy))
    result.extend(check_helper_laundering(facts, policy, decisions))
    result.extend(check_semantic_review(facts, policy, decisions))
    result.extend(check_use_cases(facts, policy))
    result.extend(check_wrapper_operations(facts, policy))
    return tuple(result)
