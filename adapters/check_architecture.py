#!/usr/bin/env python3
"""Check extracted dependency facts against an architecture policy."""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADAPTERS_ROOT = os.path.dirname(os.path.abspath(__file__))
for path in (ROOT, ADAPTERS_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

import architecture_config
from architecture_core.checker import check
from architecture_core.model import facts_from_dict, policy_from_dict, violation_to_dict


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_policy(args):
    if args.config:
        data = architecture_config.policy_from_config(
            architecture_config.load_config(args.config)
        )
        return policy_from_dict(data)
    return policy_from_dict(load_json(args.policy))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("facts", help="JSON facts file from an extractor")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", help="TOML architecture configuration")
    source.add_argument("--policy", help="JSON architecture policy")
    parser.add_argument("--json", action="store_true", help="emit JSON violations")
    args = parser.parse_args()

    facts = facts_from_dict(load_json(args.facts))
    policy = load_policy(args)
    violations = [violation_to_dict(item) for item in check(facts, policy)]

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
