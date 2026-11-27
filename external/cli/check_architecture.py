#!/usr/bin/env python3
"""CLI entrypoint for checking extracted architecture facts."""

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
from architecture_core.model import CheckFactsRequest, violation_to_dict
from architecture_core.use_cases.check_facts import run_check_facts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("facts", help="JSON facts file from an extractor")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", help="TOML architecture configuration")
    source.add_argument("--policy", help="JSON architecture policy")
    parser.add_argument("--json", action="store_true", help="emit JSON violations")
    args = parser.parse_args()

    runtime = ArchitectureRuntime(ROOT)
    request = CheckFactsRequest(
        facts_path=args.facts, config_path=args.config, policy_path=args.policy
    )
    violations = [
        violation_to_dict(item)
        for item in run_check_facts(runtime, runtime, runtime, request)
    ]

    if args.json:
        print(json.dumps(violations, indent=2))
    elif violations:
        for item in violations:
            print(f"{item['rule']}: {item['message']}")
    else:
        print("OK: no architecture violations")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
