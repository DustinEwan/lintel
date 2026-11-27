#!/usr/bin/env python3
"""Generic Lintel workflow for agentic coders."""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lintel.adapters.runtime import LintelRuntime
from lintel.adapters import decision_model

from lintel.adapters import lean_generator
from lintel.core.model import (
    CheckFactsRequest,
    PathOverrides,
    SelfCheckRequest,
    violation_to_dict,
    merge_decisions,
)

from lintel.core.use_cases.check_facts import run_check_facts
from lintel.core.use_cases.self_check import run_self_check

from lintel.core import hooks, review

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



def _hook(args, runtime):
    violations = ()
    if args.event != "session-start":
        request = SelfCheckRequest(
            config_path=args.config,
            config_required=True,
            locked=True,
        )
        violations = run_self_check(
            runtime, runtime, runtime, runtime, runtime, request
        ).violations
    result = hooks.build(args.event, violations)
    print(json.dumps(result, indent=2))
    return 1 if result["block"] else 0


def _review(args, runtime):
    try:
        reason = review.validate_reason(args.reason)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    record = runtime.record_review(args.fingerprint, args.decision, reason)
    print(json.dumps(record, indent=2))
    return 0


def _semantic_check(args, runtime):
    contract_violations = tuple(runtime.validate_config(args.config))
    contract_violations += tuple(runtime.verify_lock(args.config, True))
    if contract_violations:
        return _emit(contract_violations, args.format)
    config = runtime.load_self_config(args.config, True)
    facts = runtime.collect_self_facts(config, PathOverrides())
    findings = runtime.semantic_review_findings(facts, config.policy)
    try:
        decisions = runtime.decision_model_decisions(findings, config.policy)
    except decision_model.DecisionModelError as error:
        print(f"semantic-check failed: {error}", file=sys.stderr)
        return 2
    if not args.no_record:
        runtime.record_model_decisions(decisions, findings)
    merged = merge_decisions(facts.decisions, decisions)
    live = runtime.live_decision_fingerprints(findings, merged)
    violations = runtime.apply_baseline(
        runtime.check(facts, config.policy, merged), live
    )
    return _emit(violations, args.format)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.getcwd(), help="governed project root")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="check architecture facts")
    check.add_argument("facts", nargs="?", help="optional JSON facts file")
    check.add_argument("--config", default="lintel.toml")
    check.add_argument("--policy", help="JSON policy for fixture compatibility")
    check.add_argument("--out", help="write merged self-check facts")
    check.add_argument("--format", choices=("text", "json"), default="text")
    check.add_argument("--locked", dest="locked", action="store_true", default=True)
    check.add_argument("--no-lock", dest="locked", action="store_false")
    check.add_argument("--no-cache", action="store_true", help="rebuild all facts")

    init = commands.add_parser("init", help="scaffold a governed project")
    init.add_argument("--preset", default="clean")
    init.add_argument("--output", default=".")

    list_rules = commands.add_parser("list-rules", help="list checker rules")
    list_rules.add_argument("--format", choices=("text", "json"), default="text")

    explain = commands.add_parser("explain", help="explain one rule")
    explain.add_argument("rule")

    lock = commands.add_parser("update-lock", help="rewrite the contract lock")
    lock.add_argument("--config", default="lintel.toml")

    baseline = commands.add_parser("accept-baseline", help="accept current violations")
    baseline.add_argument("--config", default="lintel.toml")

    hook = commands.add_parser("hook", help="emit a harness-neutral hook result")
    hook.add_argument("event", choices=hooks.EVENTS)
    hook.add_argument("--config", default="lintel.toml")
    hook.add_argument(
        "--root", dest="hook_root", default=None, help="governed project root"
    )

    decision = commands.add_parser("review", help="record a semantic-review decision")
    decision.add_argument("fingerprint")
    decision.add_argument("--decision", required=True, choices=review.DECISIONS)
    decision.add_argument("--reason", required=True)

    semantic = commands.add_parser(
        "semantic-check", help="resolve semantic reviews with a decision model"
    )
    semantic.add_argument("--config", default="lintel.toml")
    semantic.add_argument("--format", choices=("text", "json"), default="text")
    semantic.add_argument(
        "--no-record", action="store_true", help="evaluate without changing the baseline"
    )

    generate = commands.add_parser(
        "generate-lean", help="generate a finite Lean instance from facts"
    )
    generate.add_argument("--facts", help="JSON facts file; default collects self facts")
    generate.add_argument("--config", default="lintel.toml")
    generate.add_argument("--out", default="generated/LintelFacts.lean")
    generate.add_argument(
        "--no-check", action="store_true", help="skip lake build and generated-instance check"
    )
    generate.add_argument("--no-cache", action="store_true", help="rebuild facts and recheck Lean")
    generate.add_argument(
        "--baseline",
        default="lintel.baseline.json",
        help="accepted baseline used to mark semantic reviews accepted",
    )

    args = parser.parse_args()
    runtime = LintelRuntime(getattr(args, "hook_root", None) or args.root)
    runtime.use_cache = not getattr(args, "no_cache", False)

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
    if args.command == "hook":
        return _hook(args, runtime)
    if args.command == "review":
        return _review(args, runtime)
    if args.command == "semantic-check":
        return _semantic_check(args, runtime)
    if args.command == "generate-lean":
        policy = runtime.load_policy(args.config, None)
        if args.facts:
            facts = runtime.load_facts(args.facts)
        else:
            config = runtime.load_self_config(args.config, True)
            facts = runtime.collect_self_facts(config, PathOverrides())
        output = runtime.resolve(args.out)
        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
        accepted = runtime.accepted_review_sources(args.baseline, facts, policy)
        lean_generator.write_instance(facts, policy, output, accepted)
        print(f"Generated Lean instance at {args.out}.")
        if not args.no_check:
            key = runtime.lean_check_key(output)
            runtime.run(["lake", "build"], cwd=runtime.tool_root)
            if not runtime.lean_check_is_cached(key):
                runtime.run(["lake", "env", "lean", output], cwd=runtime.tool_root)
                runtime.mark_lean_check(key)
            print("Checked generated Lean instance.")
        return 0
    if args.command == "update-lock":
        runtime.update_lock(args.config)
        print("Updated lintel.lock.")
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
