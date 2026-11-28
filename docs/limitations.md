# Limitations

This is the status catalog for Lintel's known limits. It is not the place to define exception mechanisms or semantic-judge cases.

- Exception mechanisms live in [ESCAPE_HATCHES.md](../ESCAPE_HATCHES.md).
- Ambiguity scenarios live in [SEMANTIC_SCENARIOS.md](../SEMANTIC_SCENARIOS.md).
- Formal-model claims live in [docs/formal-spec.md](formal-spec.md), summarized in [README.md](../README.md).
- Decision-model scope and audit fields live in [semantic-decisions.md](semantic-decisions.md).

## 1. Already mitigated

These limits remain true, but Lintel fails closed or provides a reviewed path instead of silently passing.

| Limit | Mitigation | Residual behavior |
| --- | --- | --- |
| Unsupported syntax or language | Required `[analysis] source_suffixes` plus registered analyzers | `unparsed_source`; non-baselineable |
| Unparseable Python source | Tree-sitter Python analyzer records syntax errors | `unparsed_source` with source and line |
| Unrecognized Rust visibility forms, `macro_rules!`, and non-literal `include!`/`#[path]` | Rust source graph contributor reports them explicitly | `unparsed_source` |
| Rust literal `#[path]` and `include!` | Rust source graph contributor resolves literal module redirects and include chains | `macro_rules!` and non-literal paths remain unparsed |
| Rust workspace roots | Workspace roots require per-package extraction | `unparsed_source` |
| Build-tagged Go files | Go source graph contributor evaluates `//go:build` and `// +build` against host `GOOS`/`GOARCH` and excludes fully evaluated inactive files | Indeterminate constraints remain `unparsed_source` |
| Multi-line TypeScript `from` clauses | Tree-sitter TypeScript analyzer parses multi-line import/export clauses | Non-literal dynamic dependencies remain unparsed |
| Toolchain-backed extraction unavailable | Fact collection runs in process; tree-sitter has a boot-safe native fallback | Unsupported suffixes fail closed |
| Reflection, generated code, runtime dependency injection | Detected cases become `semantic_review` with fingerprints and reasons; the decision-model checker can resolve bounded cases | Low-confidence or failed model calls remain pending |
| SEM-01 aliased stdlib boundary access | Python analyzer canonicalizes import aliases; aliases rebound from unknown expressions emit `semantic_review` | Cross-language aliases remain unresolved |
| SEM-07 native tokens in comments/strings | Tree-sitter analyzers and the retained native fallback parse comments and strings as syntax nodes | Other unusual quoting remains heuristic |
| SEM-05 declarative CLI idioms | Known frameworks and Rust `Parser` derives stay deterministic; unknown command/group decorators and unenumerated clap idioms emit `semantic_review` | Truly unknown DSLs remain bounded reviews |
| SEM-04 helper laundering in Python | Tree-sitter Python analyzer emits symbols, import bindings, and call sites; the core resolver follows uniquely resolved calls and emits `semantic_review` only for calls that may reach a locally defined concern-bearing helper | Dynamic, ambiguous, and cross-language helpers remain unresolved |
| SEM-02 local re-export/rebind chains | Literal assignment chains resolve deterministically; boundary names rebound from unknown expressions emit `semantic_review`; wildcard imports from boundary modules are reviewed | Cross-language aliases remain unresolved |
| SEM-03 literal reflection | `getattr(module, "name")` and literal `importlib.import_module(...).name` resolve to concerns | Dynamic attribute names remain `semantic_review` |
| SEM-06 configured env-reading calls | `[analysis].env_call_patterns` installs dotted call names as `env` mechanisms | No library is assumed to read env without configuration |
| SEM-08 Rust macro origins | Known terminal/logging macros emit concerns; `macro_rules!` bodies with boundary-shaped tokens emit one bounded review at the definition; generated/vendor scopes are skipped | Bodies are not expanded |
| SEM-09 injected boundary values | Core functions with live parser/environment/module annotations emit concerns; ambiguous values with self-storage or parser use emit `semantic_review` | Plain immutable data and name-only parameters stay silent |
| SEM-10 wrapper-to-native attribution | Declared build artifacts attribute native concerns to their wrapper invocation; undeclared artifacts are violations | Indirect invocation chains remain unresolved |
| SEM-11 Rust `#[cfg]` | Host-known `unix`/`windows` predicates exclude inactive code; custom and feature predicates are unresolved but fail closed with one bounded review when they guard a boundary concern | Feature values are not evaluated from `Cargo.toml` |
| SEM-12 logging stream handlers | `logging.StreamHandler` and `basicConfig(stream=...)` emit `terminal_io` | Plain logging stays a mechanism concern |
| SEM-13 test, fixture, and example intent | Known scope prefixes and analyzer review exemptions keep boundary-shaped imports and decorators silent in those paths | Unusual or generated copies still need scope declaration |
| SEM-15 transitive boundary access | Mechanism concerns propagate over deterministic dependencies and declared wrapper subprocess targets; unresolved declared core wrapper targets emit `semantic_review` | Metadata-only cross-language chains remain outside the fact set |
| SEM-16 combined policy/concern diff | `git diff HEAD` plus untracked paths pair weakened config with any added concern, including staged and untracked changes | Non-git worktrees and ambiguous diffs stay silent |

The scenarios in `SEMANTIC_SCENARIOS.md` are covered by deterministic facts or
bounded semantic reviews where syntax and available facts permit. Dynamic
reflection, ambiguous injection, unexpanded macros, unresolvable cfg
predicates, and mixed-path transitive chains still fail closed through
`semantic_review` or `unparsed_source`; none are silently treated as compliant.

## 2. Intentional formal-model trust boundaries

The generated Lean instance proves deterministic fact/policy checks only. These are inputs or assumptions to the model, not properties the model can prove about the repository:

- extraction completeness;
- runtime behavior;
- semantic judgment and decision-model correctness;
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
