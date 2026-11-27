"""Pure baseline comparison for the architecture violation ratchet."""

import json
import re

from .model import Violation
from .rules import is_baselineable

_TRAILING_LINE = re.compile(r"(?::\d+)+$")


def canonical_bytes(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def normalize_location(location):
    return _TRAILING_LINE.sub("", str(location or ""))


def fingerprint(item):
    data = dict(item)
    data["location"] = normalize_location(data.get("location", ""))
    keys = ("rule", "from", "to", "location", "source", "module", "target")
    if data.get("rule") == "semantic_review":
        keys += ("line", "reason")
    import hashlib

    stable = {key: data[key] for key in keys if key in data}
    return hashlib.sha256(canonical_bytes(stable)).hexdigest()


def violation_fingerprint(violation):
    return fingerprint(
        {"rule": violation.rule, **violation.fields}
    )


def compare_baseline(violations, accepted):
    accepted_map = {
        item.get("fingerprint", fingerprint(item)): item
        for item in accepted
        if is_baselineable(item.get("rule", item.get("violation_rule", "")))
    }
    current_map = {
        violation_fingerprint(item): item for item in violations
    }
    result = []

    for key, item in current_map.items():
        if not is_baselineable(item.rule):
            result.append(item)
            continue
        if key in accepted_map:
            continue
        result.append(
            Violation(
                "baseline_violation",
                "new violation is not in the accepted baseline: "
                + item.rule
                + f" ({normalize_location(item.fields.get('location', ''))})",
                {
                    "violation_rule": item.rule,
                    "fingerprint": key,
                    "location": normalize_location(item.fields.get("location", "")),
                },
            )
        )

    for key, item in accepted_map.items():
        if key in current_map:
            continue
        result.append(
            Violation(
                "baseline_stale",
                "accepted baseline entry no longer matches: "
                + item.get("rule", "unknown"),
                {"fingerprint": key},
            )
        )

    return tuple(result)
