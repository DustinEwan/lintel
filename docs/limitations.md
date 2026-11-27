# Limitations

This is the status catalog for Lintel's known limits. It is not the place to define exception mechanisms or semantic-judge cases.

- Exception mechanisms live in [ESCAPE_HATCHES.md](../ESCAPE_HATCHES.md).
- Ambiguity scenarios live in [SEMANTIC_SCENARIOS.md](../SEMANTIC_SCENARIOS.md).
- Formal-model claims live in [docs/formal-spec.md](formal-spec.md), summarized in [README.md](../README.md).
- Implementable extractor gaps are candidates for GitHub issues. Trust boundaries and intentional ambiguity cases are not.

## 1. Already mitigated

These limits remain true, but Lintel fails closed or provides a reviewed path instead of silently passing.

| Limit | Mitigation | Residual behavior |
| --- | --- | --- |
| Unsupported syntax or language | Required `[analysis] source_suffixes` plus registered analyzers | `unparsed_source`; non-baselineable |
| Unparseable Python source | Python `ast` analyzer records parse errors | `unparsed_source` with source and line |
| Unrecognized Rust visibility forms, `macro_rules!`, and non-literal `include!`/`#[path]` | Python scanner reports them explicitly | `unparsed_source` |
| Rust literal `#[path]` and `include!` | Python scanner resolves literal module redirects and include chains | `macro_rules!` and non-literal paths remain unparsed |
| Rust workspace roots | Native extractor refuses to attribute all members to one package | `unparsed_source` |
| Build-tagged Go files | Python scanner evaluates `//go:build` and `// +build` against host `GOOS`/`GOARCH` and excludes fully evaluated inactive files | Indeterminate constraints remain `unparsed_source` |
| Multi-line TypeScript `from` clauses | Python scanner now joins multi-line import/export clauses before scanning (PR #4); native extractor also handles them | Non-literal dynamic dependencies remain unparsed |
| Toolchain-backed extraction unavailable | Python scanners are dependency-free and are the installed default | Native extractors remain source-checkout tools requiring Rust, Go, or Node/TypeScript |
| Reflection, generated code, runtime dependency injection | Detected cases become `semantic_review` with fingerprints and reasons | Review decision is required; no automatic pass |

## 2. Intentional formal-model trust boundaries

The generated Lean instance proves deterministic fact/policy checks only. These are inputs or assumptions to the model, not properties the model can prove about the repository:

- extraction completeness;
- runtime behavior;
- semantic judgment;
- typed capability choices;
- strict layering under a policy that permits same-region edges and multiple core regions;
- runtime/nested subsystem embeddings.

`generatedNestedArchitecture` is an identity-embedding sanity instance, not a claim about repository subsystems. Scope coverage includes all scoped paths, including documentation and configuration files, not only source modules. Do not open implementation issues to “prove” these trust boundaries; that would change what Lintel claims.

Concrete demo instances for strict layering, typed capabilities, or nesting would prove examples, not the repository policy. They are only worth adding if the goal is theorem-exercise coverage.

## 3. Implementable extractor gaps

These are local, testable changes in language adapters. Only these gaps have GitHub issues; trust boundaries and ambiguity scenarios stay documentation-only.

| Gap | Issue | Current behavior | Location | Work required |
| --- | --- | --- | --- | --- |

Not quick wins:

- `macro_rules!` expansion and generated code require macro expansion, not a regex change.
- Reflection and runtime DI need explicit declared edges or semantic judgment; see [SEMANTIC_SCENARIOS.md](../SEMANTIC_SCENARIOS.md).
- Cross-package dependency cycles are already rejected by Cargo and TypeScript project references; module-level cycles inside a crate/project are checked by the extractors.
