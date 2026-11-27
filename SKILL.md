---
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
