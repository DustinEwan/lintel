"""Bounded detection of policy weakening paired with new boundary concerns."""

import os
import re
import subprocess
import tomllib

from lintel.core.model import SemanticReview

_HUNK_RE = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)")


def _git_text(root, *arguments):
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _added_locations(diff):
    """Yield (path, line) for added lines in a unified diff."""
    path = None
    line = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            value = raw[4:].strip()
            path = value[2:] if value.startswith("b/") else value
            if (
                path == "/dev/null"
                or path.endswith("policy_diff.py")
                or path.startswith("tests/")
            ):
                path = None
            continue
        if raw.startswith("@@"):
            match = _HUNK_RE.search(raw)
            line = int(match.group(1)) if match else 0
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            if path and line:
                yield path, line
            line += 1
            continue
        if raw.startswith("-") or not raw.startswith(" "):
            continue
        if path and line:
            line += 1


def _hashable(value):
    if isinstance(value, dict):
        return tuple(sorted((key, _hashable(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_hashable(item) for item in value)
    return value


def _values(data, *keys):
    value = data
    for key in keys:
        if not isinstance(value, dict):
            return ()
        value = value.get(key, ())
    return tuple(_hashable(item) for item in value) if isinstance(value, (list, tuple)) else ()


def _expanded(before, after):
    return not (set(before) - set(after)) and bool(set(after) - set(before))


def _narrowed(before, after):
    return bool(set(before) - set(after))


def _policy_weakened(before, after):
    if _narrowed(_values(before, "build_artifacts"), _values(after, "build_artifacts")):
        return True
    for section in ("wrapper_rules", "use_cases"):
        if _narrowed(
            _values(before, section, "forbidden_imports"),
            _values(after, section, "forbidden_imports"),
        ):
            return True
    for category in ("mechanism", "entrypoint_only"):
        if _expanded(
            _values(before, "boundary_concerns", category, "allowed_regions"),
            _values(after, "boundary_concerns", category, "allowed_regions"),
        ):
            return True
    if _expanded(
        _values(before, "scope_rules", "excluded_scopes"),
        _values(after, "scope_rules", "excluded_scopes"),
    ):
        return True
    before_layers = before.get("layers", {})
    after_layers = after.get("layers", {})
    for name, layer in before_layers.items():
        if not isinstance(layer, dict) or not layer.get("core"):
            continue
        if _narrowed(layer.get("forbidden", ()), _values(after_layers, name, "forbidden")):
            return True
    return False


def detect(root, facts, config_path="lintel.toml"):
    """Return a review when policy is weakened together with new boundary use."""
    config_diff = _git_text(root, "diff", "--no-ext-diff", "--unified=0", "--", config_path)
    if not config_diff:
        return ()
    baseline = _git_text(root, "show", f"HEAD:{config_path}")
    current_path = (
        config_path if os.path.isabs(config_path) else os.path.join(root, config_path)
    )
    try:
        with open(current_path, "r", encoding="utf-8") as handle:
            current = handle.read()
    except OSError:
        return ()
    if not baseline:
        return ()
    try:
        before_data, after_data = tomllib.loads(baseline), tomllib.loads(current)
    except tomllib.TOMLDecodeError:
        return ()
    if not _policy_weakened(before_data, after_data):
        return ()

    source_diff = _git_text(
        root, "diff", "--no-ext-diff", "--unified=0", "--", "lintel", "adapters", "cli"
    )
    if not source_diff:
        return ()
    added = set(_added_locations(source_diff))
    matches = [
        item
        for item in facts.concerns
        if item.concern == "argv_parse"
        and not item.source.startswith(("cli/", "lintel/cli/"))
        and ((item.source, item.line) in added or (item.module, item.line) in added)
    ]
    if not matches:
        return ()
    first = min(matches, key=lambda item: (item.source, item.line, item.concern))
    reason = (
        f"SEM-16 policy weakened while {first.concern} was added "
        f"at {first.source}:{first.line}"
    )
    return (SemanticReview(first.module, first.source, first.line, reason),)
