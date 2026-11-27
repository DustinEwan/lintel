"""Pure, harness-neutral hook decisions."""

from .model import violation_to_dict
from .ratchet import violation_fingerprint

EVENTS = ("session-start", "post-edit", "stop", "review-request")
_BLOCKING_EVENTS = frozenset({"post-edit", "stop"})

_CONTEXT = {
    "session-start": (
        "Lintel governs this project's architecture. Keep dependencies inward: "
        "entrypoints -> adapters -> core. Use `lintel check` for deterministic checks."
    ),
    "post-edit": (
        "Lintel checked the governed project after the edit. Fix new findings before "
        "continuing; use `lintel review` only for semantic-review findings."
    ),
    "stop": (
        "Lintel is running the final architecture check. Unresolved findings must be "
        "fixed or explicitly reviewed before work is considered complete."
    ),
    "review-request": (
        "Lintel can record semantic judgments with `lintel review <fingerprint> "
        "--decision compliant|violating|needs-human-review --reason <reason>`."
    ),
}

_COMMANDS = {
    "session-start": ("lintel --root . check --format json",),
    "post-edit": ("lintel --root . check --format json",),
    "stop": ("lintel --root . check --format json",),
    "review-request": (
        "lintel --root . hook post-edit",
        "lintel --root . check --format json",
    ),
}


def is_event(value):
    return value in EVENTS


def build(event, violations=()):
    """Return one JSON-ready hook result without performing any I/O."""
    findings = [
        {**violation_to_dict(item), "fingerprint": violation_fingerprint(item)}
        for item in violations
    ]
    return {
        "block": event in _BLOCKING_EVENTS and bool(findings),
        "context": _CONTEXT[event],
        "findings": findings,
        "commands": list(_COMMANDS[event]),
    }
