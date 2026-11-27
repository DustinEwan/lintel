#!/usr/bin/env python3
"""Generic architecture workflow for agentic coders."""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ADAPTERS_ROOT = os.path.join(ROOT, "adapters")
for path in (ROOT, ADAPTERS_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from adapters.runtime import ArchitectureRuntime
from adapters import lean_generator
from architecture_core.model import (
    CheckFactsRequest,
    PathOverrides,
    SelfCheckRequest,
    violation_to_dict,
)
from architecture_core.use_cases.check_facts import run_check_facts
from architecture_core.use_cases.self_check import run_self_check


def _emit(violations, output_format):
    data = [violation_to_dict(item) for item in violations]
    if output_format == "json":
        print(json.dumps(data, indent=2))
    elif data:
        for item in data:
            print(f"{item['rule']}: {item['message']}")
    else:
        print("OK: no architecture violations")
    return 1 if data else 0


def _check(args, runtime):
    request = SelfCheckRequest(
        config_path=args.config,
        config_required=args.config is not None,
        out=args.out,
        locked=args.locked,
    )
    if args.facts:
        facts_request = CheckFactsRequest(
            facts_path=args.facts,
            config_path=None if args.policy else args.config,
            policy_path=args.policy,
            locked=args.locked,
        )
        violations = run_check_facts(
            runtime, runtime, runtime, runtime, facts_request
        )
    else:
        violations = run_self_check(
            runtime, runtime, runtime, runtime, runtime, request
        ).violations
    return _emit(violations, args.format)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.getcwd(), help="governed project root")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="check architecture facts")
    check.add_argument("facts", nargs="?", help="optional JSON facts file")
    check.add_argument("--config", default="architecture.toml")
    check.add_argument("--policy", help="JSON policy for fixture compatibility")
    check.add_argument("--out", help="write merged self-check facts")
    check.add_argument("--format", choices=("text", "json"), default="text")
    check.add_argument("--locked", dest="locked", action="store_true", default=True)
    check.add_argument("--no-lock", dest="locked", action="store_false")

    init = commands.add_parser("init", help="scaffold a governed project")
    init.add_argument("--preset", default="clean")
    init.add_argument("--output", default=".")

    list_rules = commands.add_parser("list-rules", help="list checker rules")
    list_rules.add_argument("--format", choices=("text", "json"), default="text")

    explain = commands.add_parser("explain", help="explain one rule")
    explain.add_argument("rule")

    lock = commands.add_parser("update-lock", help="rewrite the contract lock")
    lock.add_argument("--config", default="architecture.toml")

    baseline = commands.add_parser("accept-baseline", help="accept current violations")
    baseline.add_argument("--config", default="architecture.toml")

    generate = commands.add_parser(
        "generate-lean", help="generate a finite Lean instance from facts"
    )
    generate.add_argument("--facts", help="JSON facts file; default collects self facts")
    generate.add_argument("--config", default="architecture.toml")
    generate.add_argument("--out", default="generated/ArchitectureFacts.lean")
    generate.add_argument(
        "--no-check", action="store_true", help="skip lake build and generated-instance check"
    )

    args = parser.parse_args()
    runtime = ArchitectureRuntime(args.root)

    if args.command == "check":
        return _check(args, runtime)
    if args.command == "init":
        runtime.scaffold(args.preset, args.output)
        print(f"Scaffolded {args.output} with the {args.preset} preset.")
        return 0
    if args.command == "list-rules":
        items = runtime.list_rules()
        if args.format == "json":
            print(json.dumps(items, indent=2))
        else:
            for item in items:
                print(f"{item['id']}: {item['summary']}")
        return 0
    if args.command == "explain":
        item = runtime.explain_rule(args.rule)
        if not item:
            print(f"unknown rule: {args.rule}", file=sys.stderr)
            return 2
        print(json.dumps(item, indent=2))
        return 0
    if args.command == "generate-lean":
        policy = runtime.load_policy(args.config, None)
        if args.facts:
            facts = runtime.load_facts(args.facts)
        else:
            config = runtime.load_self_config(args.config, True)
            facts = runtime.collect_self_facts(config, PathOverrides())
        output = runtime.resolve(args.out)
        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
        lean_generator.write_instance(facts, policy, output)
        print(f"Generated Lean instance at {args.out}.")
        if not args.no_check:
            runtime.run(["lake", "build"], cwd=runtime.tool_root)
            runtime.run(["lake", "env", "lean", output], cwd=runtime.tool_root)
            print("Checked generated Lean instance.")
        return 0
    if args.command == "update-lock":
        runtime.update_lock(args.config)
        print("Updated architecture.lock.")
        return 0
    if args.command == "accept-baseline":
        request = SelfCheckRequest(
            config_path=args.config,
            config_required=True,
            locked=False,
        )
        violations = run_self_check(
            runtime, runtime, runtime, runtime, runtime, request
        ).violations
        runtime.accept_baseline(args.config, violations)
        print(f"Accepted {len(violations)} baseline violations.")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
