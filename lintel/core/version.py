#!/usr/bin/env python3
"""Pure version comparison for release advisories."""

import re

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


def parse_version(value):
    """Return a numeric version tuple, or None for an unparseable value."""
    match = _VERSION.match(str(value).strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def is_newer(current, candidate):
    """Return True when candidate is a newer release than current."""
    current_parts = parse_version(current)
    candidate_parts = parse_version(candidate)
    if current_parts is None or candidate_parts is None:
        return False
    return candidate_parts > current_parts


def version_status(current, latest=None, error=None):
    """Build an advisory-only update status without performing I/O."""
    return {
        "version": current,
        "latest": latest,
        "update_available": bool(latest and is_newer(current, latest)),
        "advisory": True,
        "error": error,
    }
