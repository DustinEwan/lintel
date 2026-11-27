#!/usr/bin/env python3
"""Check extracted dependency facts against an architecture policy."""

import argparse
import fnmatch
import json
import sys


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def match_any(value, patterns):
    return any(fnmatch.fnmatchcase(value, pattern) for pattern in patterns or [])


def region_for(module, policy):
    for region in policy.get("regions", []):
        if match_any(module, region.get("patterns", [])):
            return region
    return {"name": policy.get("default_region", "external"), "core": False}


def forbidden_patterns(policy, region):
    forbidden = policy.get("forbidden", {})
    patterns = list(forbidden.get("global", []))
    patterns.extend(forbidden.get(region["name"], []))
    if region.get("core"):
        patterns.extend(forbidden.get("core", []))
    return patterns


def make_violation(rule, message, **fields):
    result = {"rule": rule, "message": message}
    result.update(fields)
    return result


def check_edges(facts, policy):
    violations = []
    allowed = policy.get("allowed", {})

    for dep in facts.get("dependencies", []):
        source = dep["from"]
        target = dep["to"]
        source_region = region_for(source, policy)
        target_region = region_for(target, policy)
        location = f"{dep.get('source', '?')}:{dep.get('line', '?')}"

        if source_region.get("core") and not target_region.get("core"):
            violations.append(
                make_violation(
                    "core_outward",
                    f"core module {source} depends on outer module {target} ({location})",
                    **{"from": source, "to": target, "location": location},
                )
            )

        if source_region.get("core") and match_any(
            target, forbidden_patterns(policy, source_region)
        ):
            violations.append(
                make_violation(
                    "forbidden_import",
                    f"core module {source} imports forbidden {target} ({location})",
                    **{"from": source, "to": target, "location": location},
                )
            )

        if target_region["name"] not in allowed.get(source_region["name"], []):
            violations.append(
                make_violation(
                    "edge_not_allowed",
                    f"{source_region['name']} module {source} may not depend on "
                    f"{target_region['name']} module {target} ({location})",
                    **{
                        "from": source,
                        "to": target,
                        "source_region": source_region["name"],
                        "target_region": target_region["name"],
                        "location": location,
                    },
                )
            )

    return violations


def find_cycles(facts):
    graph = {}
    for dep in facts.get("dependencies", []):
        graph.setdefault(dep["from"], set()).add(dep["to"])

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
        make_violation(
            "cycle", "dependency cycle: " + " -> ".join(cycle), cycle=cycle
        )
        for cycle in cycles
    ]


def check_unparsed(facts):
    return [
        make_violation(
            "unparsed_source",
            "unparsed source: "
            + str(item.get("reason", "unsupported syntax"))
            + f" ({item.get('source', '?')}:{item.get('line', '?')})",
            **item,
        )
        for item in facts.get("unparsed", [])
    ]

def check(facts, policy):
    return check_edges(facts, policy) + find_cycles(facts) + check_unparsed(facts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("facts", help="JSON facts file from an extractor")
    parser.add_argument("--policy", required=True, help="JSON architecture policy")
    parser.add_argument("--json", action="store_true", help="emit JSON violations")
    args = parser.parse_args()

    violations = check(load_json(args.facts), load_json(args.policy))
    if args.json:
        print(json.dumps(violations, indent=2))
    elif violations:
        for item in violations:
            print(f"{item['rule']}: {item['message']}")
    else:
        print("OK: no architecture violations")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
