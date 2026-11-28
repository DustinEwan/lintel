"""Render check findings as source-anchored text diagnostics.

This module stays in adapters because it reads source files. The core checker
and the JSON output remain unchanged; only the human-readable text renderer
uses these spans.
"""

from dataclasses import dataclass
import os
import re


@dataclass(frozen=True)
class DiagnosticSpan:
    path: str
    line: int
    start: int
    end: int
    label: str

_RULE_TOKENS = {
    "core_outward": ("to", "outer dependency"),
    "forbidden_import": ("to", "forbidden import"),
    "edge_not_allowed": ("to", "disallowed dependency"),
    "use_case_dependency": ("to", "concrete dependency"),
    "fat_entrypoint": ("target", "wrapper operation"),
    "core_cli_concern": ("concern", "boundary concern"),
    "adapter_cli_concern": ("concern", "boundary concern"),
    "scope_convention_mismatch": ("scope", "scope label"),
    "forbidden_scope_edge": ("target_scope", "scope edge"),
    "semantic_review": (None, "review site"),
    "unparsed_source": (None, "unparsed construct"),
    "direct_artifact_invocation": (None, "artifact site"),
}
_DEFAULT_LABEL = "violation"


def render_text(entries, root=".", facts=None):
    """Return text diagnostics for flattened violation dictionaries."""
    blocks = [
        render_diagnostic(entry, root=root, facts=facts)
        for entry in entries
    ]
    return "\n".join(blocks) + ("\n" if blocks else "")


def render_diagnostic(entry, root=".", facts=None):
    """Return one rust-style diagnostic block for a flattened violation."""
    rule = entry.get("rule", "")
    message = entry.get("message", "")
    header = f"error[{rule}]: {message}" if rule else f"error: {message}"
    location = _resolve_location(entry, facts)
    notes = _notes(entry)

    if location is None:
        return "\n".join([header, *notes, *_fix(entry)])

    path, line = location
    source = _source_line(root, path, line)
    if source is None:
        return "\n".join([header, f" --> {path}:{line}", *notes, *_fix(entry)])

    span = _span(source, entry, rule)
    gutter = " " * len(str(line))
    output = [
        header,
        f" --> {path}:{line}:{span.start + 1}",
        f"{gutter} |",
        f"{line} | {source}",
        f"{gutter} | {' ' * span.start}{'^' * max(1, span.end - span.start)} {span.label}",
        gutter + " |",
        *notes,
        *_fix(entry),
    ]
    return "\n".join(output)


def _resolve_location(entry, facts):
    raw = entry.get("location", "")
    if isinstance(raw, str) and ":" in raw:
        path, _, tail = raw.rpartition(":")
        if path and tail.isdigit():
            return path, int(tail)

    if entry.get("rule") == "cycle":
        cycle = entry.get("cycle") or ()
        if len(cycle) >= 2:
            for dep in getattr(facts, "dependencies", ()):
                if (
                    dep.source_module == cycle[0]
                    and dep.target_module == cycle[1]
                    and dep.source
                    and dep.line
                ):
                    return dep.source, int(dep.line)
    return None


def _source_line(root, path, line):
    if line <= 0 or not path:
        return None
    candidate = path if os.path.isabs(path) else os.path.join(root or ".", path)
    try:
        with open(candidate, encoding="utf-8", errors="replace") as handle:
            for current, text in enumerate(handle, 1):
                if current == line:
                    return text.rstrip("\r\n")
    except OSError:
        return None
    return None


def _span(source, entry, rule):
    key, label = _RULE_TOKENS.get(rule, (None, _DEFAULT_LABEL))
    token = entry.get(key) if key else ""
    start = len(source) - len(source.lstrip())
    end = len(source.rstrip())
    if end <= start:
        end = min(len(source), start + 1)

    for candidate in _token_candidates(token):
        match = re.search(
            r"(?<![A-Za-z0-9_])" + re.escape(candidate) + r"(?![A-Za-z0-9_])",
            source[start:end],
        )
        if match:
            return DiagnosticSpan(
                path="",
                line=0,
                start=start + match.start(),
                end=start + match.end(),
                label=label,
            )
    return DiagnosticSpan(path="", line=0, start=start, end=end, label=label)


def _token_candidates(token):
    if not isinstance(token, str) or not token:
        return ()
    candidates = [token]
    for separator in ("/", ".", ":", "::"):
        if separator in token:
            candidates.append(token.rsplit(separator, 1)[-1])
    return tuple(dict.fromkeys(item for item in candidates if item))


def _notes(entry):
    notes = []
    path = entry.get("path")
    if isinstance(path, (list, tuple)) and path:
        notes.append("  = path: " + " -> ".join(str(item) for item in path))
    cycle = entry.get("cycle")
    if isinstance(cycle, (list, tuple)) and cycle:
        notes.append("  = cycle: " + " -> ".join(str(item) for item in cycle))
    decision = entry.get("decision")
    if decision:
        notes.append("  = decision: " + str(decision))
    return tuple(notes)


def _fix(entry):
    fix = entry.get("fix")
    return ("  = fix: " + str(fix),) if fix else ()
