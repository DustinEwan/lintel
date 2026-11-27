#!/usr/bin/env python3
"""CLI entrypoint for Python dependency extraction."""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lintel.adapters.extract_common import write_json
from lintel.adapters.python_extractor import extract

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="project root to scan")
    parser.add_argument("--out", required=True, help="output JSON facts path")
    args = parser.parse_args()
    write_json(args.out, extract(os.path.abspath(args.root)))


if __name__ == "__main__":
    raise SystemExit(main())
