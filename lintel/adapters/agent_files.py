"""Harness-neutral instruction files written by `lintel init`."""

AGENTS_MD = """# Lintel architecture rules

- Keep source dependencies pointing inward: entrypoints -> adapters -> core.
- `core` owns facts, policy, rules, ports, and use cases. It must not own argv,
  environment access, filesystem access, subprocesses, or JSON I/O.
- Language-specific source syntax belongs in an analyzer registered by suffix.
- Run `lintel --root . check` after each edit and before declaring work complete.
- New violations fail. Baseline entries cover debt only; config errors, contract
  drift, unparsed source, and baseline errors cannot be accepted away.
- `lintel --root . review` records semantic judgments by fingerprint with a reason.
- Use `lintel --root . hook <event>` for editor and harness integration.
"""

SKILL_MD = """---
name: lintel
description: Check and review architecture boundaries with the Lintel CLI.
---

# Lintel

Use this procedure when architecture boundaries may have changed.

1. Run `lintel --root . check --format json` and read every finding.
2. Fix new violations in source or policy; never edit `lintel.lock` by hand.
3. For `semantic_review` findings, run `lintel --root . hook review-request`
   to get the available decisions, then record one with:
   `lintel --root . review <fingerprint> --decision compliant|violating|needs-human-review --reason <reason>`.
4. Re-run `lintel --root . check`. A clean result is required before finishing.
5. When the contract changes intentionally, run `lintel --root . update-lock` and
   review the resulting diff.
"""

HARNESS_SETUP_MD = """# Lintel harness setup

Lintel exposes one harness-neutral command:

```sh
lintel --root . hook <session-start|post-edit|stop|review-request>
```

It prints JSON with `block`, `context`, `findings`, and `commands`. Treat
`block: true` as a failed in-loop check and surface the findings to the user.

Claude Code: add a `PostToolUse` hook with matcher `Edit|Write` whose command is
`lintel --root . hook post-edit`. Add a `Stop` hook with
`lintel --root . hook stop`.

OpenCode: reference `AGENTS.md` as a project instruction file and call the same
hook command from an extension event handler.

Pi: call `lintel --root . hook session-start` on `session_start` and
`lintel --root . hook stop` on `session_shutdown`.

Generic harnesses: run the hook command after edits and before completion; treat
a nonzero exit or `block: true` as a failed check.
"""

FILES = {
    "AGENTS.md": AGENTS_MD,
    "SKILL.md": SKILL_MD,
    "HARNESS_SETUP.md": HARNESS_SETUP_MD,
}
