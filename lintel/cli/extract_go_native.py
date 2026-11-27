#!/usr/bin/env python3
"""CLI surface for the Go native extractor build artifact."""

import argparse
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOURCE = os.path.join(ROOT, "lintel", "adapters", "go-extractor", "main.go")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="project root to scan")
    parser.add_argument("--out", required=True, help="output JSON facts path")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as directory:
        binary = os.path.join(directory, "go-extractor")
        subprocess.run(
            ["go", "build", "-o", binary, SOURCE], cwd=ROOT, check=True
        )
        return subprocess.call(
            [binary, "--root", os.path.abspath(args.root), "--out", os.path.abspath(args.out)],
            cwd=ROOT,
        )


if __name__ == "__main__":
    raise SystemExit(main())
