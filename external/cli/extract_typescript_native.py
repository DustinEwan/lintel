#!/usr/bin/env python3
"""CLI surface for the TypeScript native extractor build artifact."""

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, "adapters", "extract_typescript_native.mjs")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="project root to scan")
    parser.add_argument("--out", required=True, help="output JSON facts path")
    args = parser.parse_args()

    return subprocess.call(
        [
            "node",
            SCRIPT,
            "--root",
            os.path.abspath(args.root),
            "--out",
            os.path.abspath(args.out),
        ],
        cwd=ROOT,
    )


if __name__ == "__main__":
    raise SystemExit(main())
