"""Pure decisions for semantic-review findings."""

DECISIONS = ("compliant", "violating", "needs-human-review")
_ACCEPTING = frozenset({"compliant"})


def is_decision(value):
    return value in DECISIONS


def is_accepting(decision):
    return decision in _ACCEPTING


def validate_reason(reason):
    value = reason.strip() if isinstance(reason, str) else ""
    if not value:
        raise ValueError("a review reason is required")
    return value


_ALIASES = {
    "allowed": "compliant",
    "violation": "violating",
    "violate": "violating",
}


def normalize_decision(value):
    if not isinstance(value, str):
        return value
    key = value.strip().lower()
    return _ALIASES.get(key, key)


def validate_confidence(value):
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        raise ValueError("a decision confidence is required") from None
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("decision confidence must be between 0 and 1")
    return confidence
