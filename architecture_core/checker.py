from fnmatch import fnmatchcase

from .model import Region, Violation


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
    return Violation(rule, message, fields)


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

    return violations


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
            "unparsed source: "
            + item.reason
            + f" ({item.source}:{item.line})",
            source=item.source,
            line=item.line,
            reason=item.reason,
        )
        for item in facts.unparsed
    ]


def check(facts, policy):
    return check_edges(facts, policy) + find_cycles(facts) + check_unparsed(facts)
