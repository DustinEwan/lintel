# Architecture Tooling Plan

## Thesis

This repository is becoming an architecture control plane for agentic coders.

The product loop is:

```text
architecture contract -> deterministic fact extraction -> decidable enforcement -> actionable feedback
```

Agents should not infer structure from prose. They should receive a machine-readable contract, run a deterministic checker, and get exact violations with locations, stable rule IDs, and fix hints.

The checker must remain boring and structural. A rule belongs in the checker only if it can be derived from facts and evaluated without manual judgment.

## Current state

Implemented:

- language-neutral Lean model and boundary proofs;
- deterministic Python, Rust, Go, and TypeScript fact extraction;
- Python parse-error handling via non-baselineable `unparsed_source`;
- TOML config with layers, scopes, and executable declarations;
- core ports and use cases;
- adapter runtime;
- `external/cli` executable wrappers;
- native extractor build-artifact wrappers;
- self-check dogfooding.

Missing:

- the checker does not enforce most of the declared contract;
- the contract itself can be weakened by the agent being governed;
- there is no ratchet against newly introduced violations;
- there is no generic project-facing workflow.

## Operating rules for every new rule

A rule is accepted only if it has:

1. a stable rule ID;
2. a deterministic fact source;
3. a config surface where behavior is configurable;
4. a file/line location in every violation;
5. a fixture that produces the violation;
6. a fixture that proves the compliant case passes;
7. a machine-readable fix hint;
8. no dependence on agentic judgment, naming taste, or fuzzy semantics.

If a concern cannot satisfy this checklist, it stays in docs or Lean commentary.

## Phase 0 — Contract integrity and ratchet

Do this first. Every later rule makes the contract more powerful, so an agent must not be able to pass by weakening the contract.

### Problem

`architecture.toml` is trusted by the checker. A governed agent can currently “fix” a violation by:

- widening `allowed`;
- adding an executable declaration;
- loosening a scope pattern;
- removing a forbidden pattern;
- changing a rule threshold;
- editing a baseline.

That is not enforcement.

### Design

Add three committed artifacts:

- `architecture.lock`
- `architecture.baseline.json`
- CODEOWNERS or CI protection for contract files.

`architecture.lock` contains:

version = 1
schema_version = 1
config_sha256 = "..."
rule_catalog_sha256 = "..."
checker_artifact_sha256 = "..."
baseline_sha256 = "..."

Canonicalization:

- parse TOML instead of hashing raw bytes;
- drop comments;
- sort keys;
- serialize deterministically;
- hash the resulting bytes.

Comment-only edits should not invalidate the lock. Semantic config edits should.

`rule_catalog_sha256` covers stable IDs, parameters, summaries, and fix hints. `checker_artifact_sha256` covers the bytes of every file that implements extraction, validation, rule evaluation, and baseline handling. A code change that weakens a rule therefore changes the lock and is visible in review. CI may additionally run an immutable pinned checker for stronger assurance.

`architecture.baseline.json` contains accepted existing violations keyed by a stable fingerprint:

```text
rule_id + normalized path + symbol or location + relevant message context
```

Line numbers should not be part of the fingerprint unless no stable symbol exists.

### Ratchet semantics

- New violation not in baseline: fail.
- Only architecture violations are baselineable; config errors, contract drift, unparsed source, and baseline errors always fail.
- Existing violation removed: check may pass, but CI requires baseline acceptance so the ratchet stays clean.
- Baseline additions require an explicit command and produce a visible diff.
- Policy changes require an explicit lock update and produce a visible diff.
- Default CLI mode is `--locked`.
- `--update-lock` and `--accept-baseline` are explicit, reviewable operations.

This is tamper-evident, not cryptographically tamper-proof. A governed agent can still edit both policy and lock, but the change is visible in review and can be restricted with CODEOWNERS:

```text
/architecture.toml @architecture-owners
/architecture.lock @architecture-owners
/architecture.baseline.json @architecture-owners
```

Optional stronger mode: sign the lock outside the repository and verify the signature in CI.

### Acceptance

- Editing `allowed` without updating the lock fails with `contract_drift`.
- Updating the lock produces a diff that names what changed.
- Adding a new violation without baseline acceptance fails with `baseline_violation`.
- Removing a violation and accepting the baseline makes the ratchet tighter.
- CI runs in locked mode by default.

## Phase 1 — Config schema validation

### Goal

Treat `architecture.toml` as a validated contract before any facts are checked.

### Checks

- required top-level keys exist;
- unknown keys are rejected;
- `version` and `schema_version` are supported;
- default layer and default scope are declared;
- layer priorities are unique;
- every allowed-target name is a declared layer;
- every glob pattern compiles;
- every executable path exists;
- every executable owner is a declared layer;
- scope patterns do not overlap ambiguously;
- `entrypoints_root` agrees with executable paths.

### Rules

- `config_invalid`
- `config_unknown_key`
- `config_bad_reference`
- `config_pattern_overlap`
- `config_missing_executable`

### Acceptance

A malformed config fails before extraction with a precise location and message.

## Phase 2 — Executable and surface enforcement

### Goal

Make `[[executables]]` and `entrypoints_root` real constraints.

### Facts

- `ExecutableDeclaration(name, path, owner)`
- `DiscoveredEntrypoint(path, kind, evidence)`
- `ExecutableInvocation(command, target, location)`

Entry point discovery:

- Python: `if __name__ == "__main__"`;
- Go: `func main`;
- Rust: `fn main`;
- JS/TS: `process.argv`, package `bin`, known CLI artifacts;
- shell/Make/CI commands: later phase, if needed.

### Rules

- `undeclared_executable`
- `missing_executable`
- `executable_owner_mismatch`
- `entrypoint_root_mismatch`
- `direct_artifact_invocation`

### Acceptance

- Every discovered source entrypoint is declared.
- Every declared executable path exists and is under `entrypoints_root`.
- Owner always matches computed layer.
- Native sources under `build_artifact` are not treated as public surfaces unless wrapped.

## Phase 3 — Boundary concerns and use-case port purity

### Goal

Enforce the central philosophy in code, not only in Lean.

### Boundary-concern facts

Split concerns by ownership, not by "anything touching the outside world":

- entrypoint-only: `argparse`, `typer`, `click`, `sys.argv`, `flag.Parse`,
  `std::env::args`, `process.argv`, `os.Exit`, `SystemExit`, `process.exit`;
- mechanism concerns: `os.environ`, `logging`, `print`, `process.env`,
  `std::env::var`, `fmt.Print`.

Entrypoint-only concerns are forbidden outside `entrypoints` and declared
build artifacts. Mechanism concerns are allowed in adapters and infrastructure
by default and are configurable. Core and ports must not own either category.

Policies live under `[boundary_concerns.entrypoint_only]` and
`[boundary_concerns.mechanism]`.

### Source analyzer boundary

Boundary-concern detection is a mechanism, not a core rule. `SourceAnalyzerPort`
defines what a language analyzer must emit: executable surface, boundary
concerns, wrapper operations, and unparsed source. Language-specific adapters
implement that port and are registered by suffix. The checker consumes only the
normalized facts.

Ambiguous cases that require intent or whole-program reasoning are recorded in
`SEMANTIC_SCENARIOS.md` for a future agentic semantic judge. They are not
silently treated as passes.

### Rules

- `adapter_cli_concern`
- `core_cli_concern`
- `use_case_dependency`

Allowed:

- entrypoint-only concerns in `entrypoints`;
- build-artifact concerns in `build_artifact` scope;
- configured mechanism concerns in adapters and infrastructure;
- use cases importing `ports`, `model`, and stdlib typing.

Forbidden:

- entrypoint-only concerns in `adapters` or `core`;
- any boundary concern in `ports` or `core` unless explicitly allowed;
- use cases importing adapters, subprocess, JSON I/O, filesystem, or concrete extractors.

### Acceptance

A core or adapter module using CLI/env/exit APIs fails. A use case importing an adapter fails.

## Phase 4 — Scope enforcement

### Goal

Replace hardcoded exclusions and documentation-only scopes with extracted facts.

### Facts

- `ScopeAssignment(path, scope, evidence)`
- `ScopeOverlap(path, scopes)`
- `ScopedDependency(from_scope, to_scope)`

### Rules

- `scope_convention_mismatch`
- `scope_overlap`
- `forbidden_scope_edge`
- `unscoped_build_artifact`

### Scope semantics

- `fixture`: intentionally invalid examples, excluded from production checks;
- `test`: test code, may import production but is not part of production graph;
- `example`: illustrative code, not production;
- `generated`: machine-generated code, fail-closed or ignored by explicit policy;
- `vendor`: third-party code, not owned;
- `build_artifact`: native CLI sources invoked only through declared wrappers.

### Acceptance

Fixture exclusion comes from config, not hardcoded runtime paths. Scoped paths produce scope facts. Production code importing fixture or generated code can be rejected by policy.

## Phase 5 — Wrapper thinness

### Goal

Prevent business logic from creeping into entrypoints without forbidding legitimate composition.

### Permitted in entrypoints

- argument parsing;
- calling `adapters.runtime`;
- calling adapter extractor libraries;
- invoking declared build subprocesses;
- serializing output;
- process exit.

### Forbidden in entrypoints

- importing `architecture_core.checker`;
- constructing `Policy`;
- walking source trees;
- parsing source syntax;
- implementing extraction rules;
- implementing self-check or fact-check workflows;
- undeclared subprocess execution.

### Rule

- `fat_entrypoint`

### Acceptance

`external/cli/extract_python.py` importing `adapters.python_extractor` passes. `external/cli/extract_rust_native.py` invoking `cargo build` passes. A CLI module containing extraction or policy logic fails.

## Phase 6 — Rule registry, tests, and actionable output

### Goal

Make the checker usable by agents and maintainable by humans.

### Artifacts

- stable rule registry;
- JSON violation schema;
- fixture matrix per rule;
- fix hints per rule;
- `list-rules`;
- `explain <rule>`.

### Violation shape

```json
{
  "rule": "adapter_cli_concern",
  "message": "...",
  "from": "adapters.foo",
  "location": "adapters/foo.py:12",
  "fix": "Move argv parsing to external/cli and inject parsed input through a port."
}
```

### Acceptance

Every enforced rule has a passing fixture, a failing fixture, a stable ID, and a fix hint. JSON output is stable enough for agent tooling.

## Phase 7 — Generic project workflow

### Goal

Make the tool usable on projects other than this repository.

### Commands

- `architecture init` — scaffold config, lock, baseline, and expected directories;
- `architecture check` — run configured extraction and checking;
- `architecture explain <rule>`;
- `architecture list-rules`;
- `architecture update-lock`;
- `architecture accept-baseline`.

### Principles

- explicit config, no magic auto-detection;
- fail closed on unsupported syntax;
- preserve stable JSON output;
- CI-friendly exit codes;
- presets for Clean, Hexagonal, and Onion layouts.

### Acceptance

A fresh project can be scaffolded, checked, and integrated into CI without copying this repository’s internals.

## Deferred work

Do not implement yet:

- call-graph and community-mismatch analysis;
- boundary-data type checking;
- semantic proof of wrapper thinness;
- broad README/CI command scanning;
- automatic config generation from existing projects;
- policy inference from history.
- agentic semantic judge for the scenarios recorded in `SEMANTIC_SCENARIOS.md`;

These are either expensive, brittle across languages, or dependent on richer fact models. Add them only when a concrete invariant cannot be enforced with imports, scopes, executable declarations, and API-use facts.

## Rule acceptance checklist

Before adding any rule, answer:

1. What exact fact makes it fire?
2. How is that fact extracted deterministically?
3. What config controls it?
4. What is the stable rule ID?
5. What fixture fails?
6. What fixture passes?
7. What is the fix hint?
8. Can an agent bypass it by editing config?
9. If yes, does the lock/ratchet make that bypass visible?
10. Can it produce false positives from valid code?

If any answer is weak, defer the rule.
