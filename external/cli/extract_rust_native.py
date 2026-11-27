#!/usr/bin/env python3
"""CLI surface for the Rust native extractor build artifact."""

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MANIFEST = os.path.join(ROOT, "adapters", "rust-extractor", "Cargo.toml")
BINARY = os.path.join(
    ROOT, "adapters", "rust-extractor", "target", "debug", "rust-extractor"
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="project root to scan")
    parser.add_argument("--out", required=True, help="output JSON facts path")
    args = parser.parse_args()

    subprocess.run(
        ["cargo", "build", "--quiet", "--manifest-path", MANIFEST],
        cwd=ROOT,
        check=True,
    )
    return subprocess.call(
        [BINARY, "--root", os.path.abspath(args.root), "--out", os.path.abspath(args.out)],
        cwd=ROOT,
    )


if __name__ == "__main__":
    raise SystemExit(main())
