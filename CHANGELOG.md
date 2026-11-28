## 0.1.0 (2026-11-28)

### Feat

- **cli**: render source-anchored diagnostics
- **graph**: add derived graph query index
- unify normalized source graph facts
- prototype tree-sitter TypeScript fact extraction
- add order-pricing examples and harden analyzer facts
- unify staged semantic checks and harden scenarios
- harden remaining semantic scenarios
- cover semantic architecture scenarios
- detect helper laundering through call facts
- cover more semantic scenarios
- add configurable decision-model semantic review
- add direct omp review-decision command
- surface lintel review requests in omp
- wire lintel into omp harness
- rename project to Lintel and add agent integration

### Fix

- resolve inline Rust path attributes correctly
- close source graph coverage gaps
- preserve lintel hook findings on blocked checks
- fail closed on indeterminate legacy build tags
- evaluate Go build constraints from host target
- accept visibility after literal #[path]
- resolve literal Rust path and include directives
- parse TypeScript multi-line import/export clauses
- restore runtime import ban in forbidden lists
- tighten Lintel naming, review fingerprints, and agent setup

### Refactor

- build all graph facts from tree-sitter ASTs
