# Lintel

Lintel checks and governs inward architecture boundaries for agentic codebases. It provides deterministic checks, a Lean formalization, and harness-neutral hook and review commands.

The architecture philosophy behind the policy—Clean, Hexagonal, Onion, and adjacent patterns—is in [docs/philosophy.md](docs/philosophy.md).

## Formal Lean spec

`lintel/Lintel.lean` formalizes the common philosophy in Lean 4. The spec models a system as:

- `Module`: a set of modules or components.
- `dep`: a source-code dependency relation.
- `Core : Set Module`: a predicate identifying core modules.
- `core_closed`: every dependency of a core module is also core.

The model deliberately avoids a unique core module or rank-based isolation. `Core` is a set, so multiple core modules are supported, and an outer module cannot become reachable from the core merely by sharing a rank or region.

Proven properties:

- `core_closed_path`: every transitive dependency path from the core remains in the core.
- `core_cannot_reach_outer`: no core module can transitively reach a non-core module.
- `adapter_unreachable_from_core`: no core module can reach an outer adapter.
- `region_path_non_outward`: dependency paths are non-outward in a layered region order.
- `core_region_path`: a dependency path from the core remains in the core's region.
- `substitution`: equivalent implementations of a core-owned capability can be exchanged without changing a core program's result.
- `path_allowed`: every dependency path obeys a transitive region-edge policy.
- `strict_region_path`: every dependency path in a strict layered architecture moves inward.
- `strict_acyclic`: a strictly layered dependency graph is acyclic.
- `capability_adapter_substitution`: equivalent adapters for the same capability port are substitutable.
- `nested_core_image_closed`: a direct inner-core dependency maps into the outer core.
- `nested_core_path_stays_core`: a path from an inner core module maps into the outer core.
- `nested_core_cannot_reach_outer`: an inner core path cannot land outside the outer core.
- `embedded_path`: inner dependency paths embed as outer dependency paths.
- `inverted_call_avoids_adapter`: runtime calls through a port do not create core-to-adapter source dependencies.
- `test_transfers`: a passing core test with a mock transfers to an equivalent production implementation.
- `typed_op_not_forbidden`: a typed capability's operation type cannot be forbidden data.
- `typed_result_not_forbidden`: a typed capability's result type cannot be forbidden data.
- `allowed_pair` and `allowed_sum`: allowed values stay allowed when composed into products or sums.
- `typed_program_result_not_forbidden`: a typed core program cannot return forbidden data.
- `typed_capability_adapter_substitution`: equivalent typed adapters are substitutable.
- Concrete `demoArchitecture`: an application module cannot reach a Postgres adapter, and `demo_acyclic` proves the example graph has no dependency cycle.

The spec also defines `Port`, `Adapter`, `CapabilityPort`, `CapabilityAdapter`, `RegionOrder`, `EdgePolicy`, `PolicyArchitecture`, `StrictLayeredArchitecture`, `NestedArchitecture`, `InvertedCall`, `Capability`, `BoundaryDataLanguage`, `TypedCapability`, `TypedProgram`, `TypedCapabilityPort`, and `TypedCapabilityAdapter` to connect the dependency model with boundary contracts, composition, dependency inversion, substitutability, and boundary-data typing.

`BoundaryDataLanguage` is an abstract parameter: a project defines `Allowed` as its DTO/value types and `Forbidden` as framework-owned types such as ORM rows, HTTP requests, or UI models, then supplies the disjointness proof. Typed capabilities, ports, and programs make that choice part of the contract rather than a convention.

Acyclicity is scoped to dependency graphs extracted below the package or project-reference level. Cargo rejects ordinary package dependency cycles and TypeScript project references reject reference cycles; the remaining practical gaps are module-level cycles inside a crate/project and dev/test-only edges.

This verifies the **formal model**. The adapters in `lintel/adapters/` bridge real source code to that model: extractors emit `Module` and `dep` facts, and the checker enforces the same rules in decidable form.

`generate-lean` instantiates every executable-fact category from the checker in the generated module: core and policy architecture, acyclicity, nested embedding, ports/adapters/inverted calls, multi-core layered regions, use-case purity, declared entrypoints, scope assignments, boundary concerns, wrapper operations, and semantic review state. `MultiCoreLayeredArchitecture` is used because the current policy has several core regions. The current policy also permits same-region edges and multiple core regions, so no strict layered instance is emitted. Typed capability structures and extraction/runtime semantics remain abstract or outside the generated instance.

Trust boundaries: generated Lean proves the deterministic fact/policy checks only. Extraction completeness, runtime behavior, semantic judgment, typed capability choices, strict layering, and runtime/nested subsystem embeddings are not claimed as Lean theorems. `generatedNestedArchitecture` is an identity-embedding sanity instance, not a claim about repository subsystems. Scope coverage includes all scoped paths, including documentation and configuration files, not only source modules.

Toolchain: Lean 4.36.0, pinned in `lintel/lean-toolchain`.

Requires `lake` on `PATH`. Verify with:

```sh
cd lintel && lake build
```

CI runs both `lake build` and the Python checker pipeline on pushes and pull requests.

## Extractors and checker

`lintel/cli/extract_*.py` are CLI entrypoints. They call the extractor libraries in `lintel/adapters/*_extractor.py`, which scan a project root and emit JSON facts:

- `modules`: `{name, path, package?}` entries.
- `dependencies`: `{from, to, kind, source, line}` entries.

`lintel/cli/check_facts.py` reads facts plus architecture configuration from `lintel.toml` (`--config`) or a JSON policy file (`--policy`). It reports:

- `core_outward`: a core module depends on a non-core module.
- `forbidden_import`: a core module imports a forbidden target.
- `edge_not_allowed`: a source region has no permission for the target region.
- `cycle`: a module dependency cycle.

- `unparsed_source`: declared source could not be parsed or has no analyzer.
- `semantic_review`: detectable ambiguity needs a judge or human review.
Layer patterns use shell-style `fnmatch`; layers are sorted by `priority` and the first matching layer wins. `default_layer` catches dependencies with no matching layer; it is an unowned fallback, not an owned layer. Layers with `core = true` correspond to `Core` in the Lean model. `tests/fixtures/policy.json` remains an example JSON policy covering Rust, Go, and TypeScript module names.
`lintel.toml` separates three concepts: `[layers.*]` defines inward dependency rings, `[scopes.*]` identifies test/example/fixture/generated/vendor contexts, and `[[executables]]` declares CLI surfaces with their owning layer. `ports` and `core` are core; `platform` covers language runtime primitives; `entrypoints`, `adapters`, and `infrastructure` are outer rings. Ports are contracts and boundary data owned by core.
`[analysis] source_suffixes` is required and declares which file suffixes are governed source. A declared suffix without an analyzer, or a known source suffix that is not declared, is an `unparsed_source` error. Exception rules are formalized in `ESCAPE_HATCHES.md`; semantic ambiguity scenarios are listed in `SEMANTIC_SCENARIOS.md`.

### Install and usage

No published distribution exists yet; install from this source checkout. Lintel requires Python 3.11+.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
lintel --root /path/to/project check
lintel --root /path/to/project check --format json
lintel list-rules
lintel explain adapter_cli_concern
lintel --root /path/to/project update-lock
lintel --root /path/to/project accept-baseline
lintel --root /path/to/project generate-lean --out /path/to/LintelFacts.lean [--no-check]
```

When the governed project is the current directory, omit `--root`; it defaults there:

```sh
lintel check
lintel check --out facts.json
lintel check facts.json --config lintel.toml
lintel generate-lean --facts facts.json
```

`check --out facts.json` writes merged facts only after config and lock validation succeed. Rechecking a facts file with `--config` (the default `lintel.toml` or an explicit path) validates the lock and applies the baseline; `--policy` is fixture compatibility and skips lock and baseline handling.

`lintel init` rewrites config and baseline files, so use it only for new projects:

```sh
lintel init --preset clean --output /path/to/new-project
```

Wire the generated hooks into your harness using `HARNESS_SETUP.md`. The installed CLI uses dependency-free Python analyzers by default.

Source checkout only: extractor surfaces backed by language toolchains.

```sh
python3 lintel/cli/extract_rust.py --root /path/to/project --out rust-facts.json
python3 lintel/cli/extract_rust_native.py --root /path/to/project --out rust-native-facts.json
python3 lintel/cli/extract_go.py --root /path/to/project --out go-facts.json
python3 lintel/cli/extract_typescript.py --root /path/to/project --out ts-facts.json
python3 lintel/cli/extract_python.py --root /path/to/project --out py-facts.json
python3 lintel/cli/extract_go_native.py --root /path/to/project --out go-native-facts.json
npm ci --prefix lintel
python3 lintel/cli/extract_typescript_native.py --root /path/to/project --out ts-native-facts.json
python3 lintel/cli/check_facts.py rust-facts.json --config lintel.toml
python3 lintel/cli/check_facts.py rust-facts.json --policy tests/fixtures/policy.json
python3 lintel/cli/check_self.py
```

`generate-lean` emits a finite Lean module that imports `Lintel` and instantiates its structures and theorems from the facts. Accepted `semantic_review` findings come from `lintel.baseline.json` (override with `--baseline`); all other findings are pending. By default it then runs `lake build` and checks the generated module with `lake env lean`; use `--no-check` when the Lean toolchain is unavailable.

The Python extractor libraries are dependency-free. `lintel/adapters/python_extractor.py` uses the standard-library `ast` parser. `rust-extractor` uses `cargo metadata` plus `syn`, `go-extractor` uses `go list -json` plus `go/parser`, and `lintel/adapters/extract_typescript_native.mjs` uses the TypeScript compiler API. Prefer native extractors when their toolchains are available in CI.
Native extractor programs inside `lintel/adapters/` are build artifacts invoked by `lintel/cli` wrappers. `lintel.toml` records them under `[scopes.build_artifact]` and declares the wrapper surfaces under `[[executables]]`; their argv parsing is internal to the artifact, not the repository's public boundary.
Checks are locked by default. `lintel.toml` is the contract; `lintel.lock` binds its semantic hash, the rule catalog, the checker implementation artifacts, and the baseline hash. `lintel.baseline.json` ratchets existing violations: new violations fail, and removed violations require an explicit acceptance to keep the baseline clean. Only architecture violations are baselineable; config errors, contract drift, unparsed source, and baseline errors cannot be accepted away. Use `--no-lock` only for bootstrap and debugging. Contract files are review-protected through `.github/CODEOWNERS`.

Validation is incremental by default. `lintel.cache.json` is an untracked, content-addressed cache keyed by the lock digests, policy, Python version, tool-root artifacts, and per-file hashes. A cache hit reuses extracted facts; a change re-extracts only when required and always re-runs the full global `check()` on the merged `FactSet`. `generate-lean` also skips repeated generated-instance checks when the generated file, `lintel/Lintel.lean`, and `lintel/lean-toolchain` are unchanged. Use `--no-cache` with `check` or `generate-lean` to force full extraction and rechecking. The cache is derived state: delete it at any time.
Core logic lives in `lintel/core/`: pure fact types, policy matching, checker rules, ports, hooks, review decisions, and use cases. `lintel/adapters/` contains concrete mechanisms that translate source syntax into facts and perform file/process I/O; `lintel/adapters/runtime.py` composes those mechanisms behind core ports. `lintel/cli/` contains executable surfaces only. Dependencies point inward: entrypoints -> adapters -> core; core has no CLI, subprocess, JSON-I/O, or filesystem dependencies.

Boundary-concern and wrapper-operation detection lives behind `SourceAnalyzerPort`. `lintel/adapters/language/` contains one analyzer per supported source language, registered by suffix; `lintel/adapters/contract_facts.py` only composes their normalized facts with scope assignments. Ambiguous cases requiring intent are listed in `SEMANTIC_SCENARIOS.md`.

Python parse failures are recorded in an `unparsed` array and reported as `unparsed_source` violations. Native analyzers use language-specific token detection without parser-level `unparsed` facts. Every source suffix in a governed project must be declared in `[analysis] source_suffixes`; undeclared or unsupported suffixes fail closed as `unparsed_source`.

## Agent and harness integration

`lintel init` writes short `AGENTS.md`, procedural `SKILL.md`, and fallback `HARNESS_SETUP.md` files into the scaffolded project. They describe the same deterministic workflow without importing any harness SDK.

Every harness calls one command:

```sh
lintel hook <session-start|post-edit|stop|review-request>
```

It prints JSON with `block`, `context`, `findings`, and `commands`. Findings carry stable fingerprints. `block` is true for `post-edit` and `stop` when unresolved violations exist. `HARNESS_SETUP.md` shows hook wiring for Claude Code, OpenCode, Pi, and a generic shell fallback.

Semantic decisions are explicit:

```sh
lintel review <fingerprint> --decision compliant --reason "port is intentionally typed"
```

`compliant` accepts the finding and records its source for generated Lean. `violating` and `needs-human-review` leave the finding pending. Every decision requires a reason and updates the baseline and lock through a reviewable diff.

Dogfooding: `python3 lintel/cli/check_self.py` parses CLI arguments, builds the runtime adapter, and calls the self-check use case. The use case asks ports for config, facts, and checking; `lintel/adapters/runtime.py` performs extraction, merging, and file I/O behind those ports. Fixtures under `tests/fixtures/` are excluded because they deliberately contain violations. The check needs Python, Rust, and Go toolchains; the TypeScript source is scanned by the Python scanner.
Dogfood configuration and policy live in `lintel.toml` at the repo root:

```toml
version = 1
default_layer = "external"
default_scope = "external"

[paths]
core_root = "lintel/core"
adapters_root = "lintel/adapters"
entrypoints_root = "lintel/cli"

[[executables]]
name = "check_self"
path = "lintel/cli/check_self.py"
owner = "entrypoints"

[layers.core]
priority = 20
core = true
patterns = ["lintel.core.*"]
allowed = ["ports", "core", "platform"]
```

CLI flags override path values. Layer patterns and allowed edges are independent of folder names, but executable surfaces are declared explicitly in `[[executables]]`.

Limits are summarized here; the status catalog is [docs/limitations.md](docs/limitations.md). Unsupported syntax fails closed as `unparsed_source`, ambiguous cases produce `semantic_review`, and native extractors extend coverage where toolchains exist. Exception mechanisms are in [ESCAPE_HATCHES.md](ESCAPE_HATCHES.md); ambiguity cases are in [SEMANTIC_SCENARIOS.md](SEMANTIC_SCENARIOS.md).

The fixtures under `tests/fixtures/` contain deliberate violations and are useful for smoke-testing the pipeline.
