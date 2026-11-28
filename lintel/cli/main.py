#!/usr/bin/env python3
"""Generic Lintel workflow for agentic coders."""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lintel.adapters.runtime import LintelRuntime, SemanticDecisionError
from lintel.adapters import release as release_adapter
from lintel.core.version import version_status
from lintel.adapters import lean_generator
from lintel.adapters.diagnostics import render_text
from lintel.core.model import (
    CheckFactsRequest,
    DEFAULT_STAGES,
    PathOverrides,
    STAGE_NAMES,
    SelfCheckRequest,
    violation_to_dict,
)

from lintel.core.use_cases.check_facts import run_check_facts
from lintel.core.use_cases.self_check import run_self_check
from lintel.core.use_cases.semantic_stage import semantic_stage
from lintel.core import hooks, review


def _parse_stages(value):
    stages = tuple(part.strip() for part in value.split(",") if part.strip())
    if not stages or any(stage not in STAGE_NAMES for stage in stages):
        raise argparse.ArgumentTypeError(
            "stages must be a non-empty subset of " + ", ".join(STAGE_NAMES)
        )
    return stages

def _emit(violations, output_format, proposals=(), facts=None, root="."):
    data = [violation_to_dict(item) for item in violations]
    proposal_data = [
        {
            "fingerprint": item.fingerprint,
            "decision": item.decision,
            "reason": item.reason,
            "confidence": item.confidence,
            "model": item.model,
            "schema_version": item.schema_version,
            "evidence_hash": item.evidence_hash,
            "state_hash": item.state_hash,
        }
        for item in proposals
    ]
    if output_format == "json":
        if proposals:
            print(json.dumps({"violations": data, "proposals": proposal_data}, indent=2))
        else:
            print(json.dumps(data, indent=2))
    elif data:
        print(render_text(data, root=root, facts=facts), end="")
        for item in proposals:
            print(
                f"proposal: {item.fingerprint}: {item.decision} "
                f"({item.confidence:.2f}) {item.reason}"
            )
    elif proposals:
        for item in proposals:
            print(
                f"proposal: {item.fingerprint}: {item.decision} "
                f"({item.confidence:.2f}) {item.reason}"
            )
    else:
        print("OK: no architecture violations")
    return 1 if data else 0



def _check(args, runtime):
    request = SelfCheckRequest(
        config_path=args.config,
        config_required=args.config is not None,
        out=args.out,
        locked=args.locked,
        stages=args.stages,
    )
    try:
        if args.facts:
            facts_request = CheckFactsRequest(
                facts_path=args.facts,
                config_path=None if args.policy else args.config,
                policy_path=args.policy,
                locked=args.locked,
                stages=args.stages,
            )
            result = run_check_facts(
                runtime, runtime, runtime, runtime, runtime, facts_request
            )
        else:
            result = run_self_check(
                runtime, runtime, runtime, runtime, runtime, runtime, request
            )
    except SemanticDecisionError as error:
        print(str(error), file=sys.stderr)
        return 2
    return _emit(
        result.violations,
        args.format,
        result.proposals,
        facts=result.facts,
        root=runtime.root,
    )



def _hook(args, runtime):
    violations = ()
    if args.event != "session-start":
        request = SelfCheckRequest(
            config_path=args.config,
            config_required=True,
            locked=True,
            stages=("deterministic",),
        )
        violations = run_self_check(
            runtime, runtime, runtime, runtime, runtime, runtime, request
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
    proposal = None
    try:
        config = runtime.load_self_config("lintel.toml", True)
        facts = runtime.collect_self_facts(config, PathOverrides())
        _, proposals = semantic_stage(
            facts, config.policy, runtime, ("semantic",)
        )
        proposal = next(
            (item for item in proposals if item.fingerprint == args.fingerprint),
            None,
        )
    except SemanticDecisionError as error:
        print(f"proposal unavailable: {error}", file=sys.stderr)
    record = runtime.record_review(
        args.fingerprint, args.decision, reason, proposal
    )
    print(json.dumps(record, indent=2))
    return 0

def _version(args, runtime):
    info = release_adapter.install_info(ROOT)
    latest = None
    error = None
    if args.check:
        try:
            latest = release_adapter.latest_release()
        except release_adapter.ReleaseError as exc:
            error = str(exc)
    status = version_status(
        info["version"], latest["version"] if latest else None, error
    )
    data = {**info, **status, **release_adapter.embedded_build_info()}
    if latest:
        data["release_url"] = latest["url"]
        data["published_at"] = latest["published_at"]
    if args.format == "json":
        print(json.dumps(data, indent=2))
        return 0
    print(f"lintel {info['version']} ({info['channel']})")
    if args.check:
        if latest:
            state = "update available" if status["update_available"] else "up to date"
            print(f"latest release: {latest['version']} ({state})")
            if latest["url"]:
                print(f"release: {latest['url']}")
        elif error:
            print(f"release check: {error}")
    return 0


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
    check.add_argument(
        "--stages",
        type=_parse_stages,
        default=DEFAULT_STAGES,
        help="comma-separated stages: deterministic,semantic",
    )

    version = commands.add_parser("version", help="show installed version")
    version.add_argument(
        "--check", action="store_true", help="check GitHub Releases for a newer version"
    )
    version.add_argument("--format", choices=("text", "json"), default="text")
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
    if args.command == "version":
        return _version(args, runtime)
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
            runtime, runtime, runtime, runtime, runtime, runtime, request
        ).violations
        runtime.accept_baseline(args.config, violations)
        print(f"Accepted {len(violations)} baseline violations.")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
