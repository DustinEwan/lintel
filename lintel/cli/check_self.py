#!/usr/bin/env python3
"""CLI entrypoint for the repository Lintel self-check."""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lintel.adapters.runtime import LintelRuntime
from lintel.core.model import PathOverrides, SelfCheckRequest, violation_to_dict
from lintel.core.use_cases.self_check import run_self_check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="TOML config path")
    parser.add_argument("--core-root", help="core source root")
    parser.add_argument("--adapters-root", help="adapter source root")
    parser.add_argument("--out", help="write merged facts to this path")
    parser.add_argument("--locked", dest="locked", action="store_true", default=True)
    parser.add_argument("--no-lock", dest="locked", action="store_false")
    args = parser.parse_args()

    runtime = LintelRuntime(ROOT)
    request = SelfCheckRequest(
        config_path=args.config or "lintel.toml",
        config_required=args.config is not None,
        overrides=PathOverrides(
            core_root=args.core_root, adapters_root=args.adapters_root
        ),
        out=args.out,
        locked=args.locked,
    )
    result = run_self_check(runtime, runtime, runtime, runtime, runtime, request)
    violations = [violation_to_dict(item) for item in result.violations]
    if violations:
        print(json.dumps(violations, indent=2))
        return 1
    print("OK: repository architecture has no violations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
