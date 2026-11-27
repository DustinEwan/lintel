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
