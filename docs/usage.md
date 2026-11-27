# Lintel usage

Lintel is installed from this source checkout; no published distribution exists yet. It requires Python 3.11+.

## Install

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
```

## Everyday commands

`--root` defaults to the current directory. Prefix any command with `--root /path/to/project` when the governed project is elsewhere.

| Task | Command |
| --- | --- |
| Check the current project | `lintel check` |
| Check with JSON output | `lintel check --format json` |
| Write merged facts | `lintel check --out facts.json` |
| Recheck a facts file | `lintel check facts.json --config lintel.toml` |
| Generate from saved facts | `lintel generate-lean --facts facts.json` |
| Resolve semantic reviews with a decision model | `lintel semantic-check` |
| Explain a rule | `lintel explain adapter_cli_concern` |
| Relock after a contract change | `lintel update-lock` |
| Accept a clean baseline update | `lintel accept-baseline` |
| Generate and check a Lean instance | `lintel generate-lean --out /path/to/LintelFacts.lean` |
| Generate without the Lean toolchain | `lintel generate-lean --out /path/to/LintelFacts.lean --no-check` |

`check --out facts.json` writes merged facts only after config and lock validation succeed. Rechecking a facts file with `--config`—the default `lintel.toml` or an explicit path—validates the lock and applies the baseline. `--policy` is fixture compatibility and skips lock and baseline handling.

## New projects

`lintel init` rewrites config and baseline files, so use it only when scaffolding a new project:

```sh
lintel init --preset clean --output /path/to/new-project
```

## Harness hooks

Wire the generated hooks into a harness using [HARNESS_SETUP.md](../HARNESS_SETUP.md). The installed CLI uses dependency-free Python analyzers by default; native extractors are optional source-checkout tools.

## Source-checkout extractors

These surfaces are available from a source checkout. Language-toolchain-backed extractors are not auto-selected by the installed CLI.

```sh
python3 lintel/cli/extract_rust.py --root /path/to/project --out rust-facts.json
python3 lintel/cli/extract_rust_native.py --root /path/to/project --out rust-native-facts.json
python3 lintel/cli/extract_go.py --root /path/to/project --out go-facts.json
python3 lintel/cli/extract_go_native.py --root /path/to/project --out go-native-facts.json
python3 lintel/cli/extract_typescript.py --root /path/to/project --out ts-facts.json
python3 lintel/cli/extract_python.py --root /path/to/project --out py-facts.json
npm ci --prefix lintel
python3 lintel/cli/extract_typescript_native.py --root /path/to/project --out ts-native-facts.json
python3 lintel/cli/check_facts.py rust-facts.json --config lintel.toml
python3 lintel/cli/check_facts.py rust-facts.json --policy tests/fixtures/policy.json
python3 lintel/cli/check_self.py
```

| Extractor | Backend |
| --- | --- |
| Python | Standard-library `ast` parser; dependency-free |
| Rust | Python scanner plus native `cargo metadata` and `syn` extractor |
| Go | Python scanner plus native `go list -json` and `go/parser` extractor |
| TypeScript | Python scanner plus native TypeScript compiler API extractor |

Prefer native extractors when their toolchains are available in CI. Native extractor programs inside `lintel/adapters/` are build artifacts invoked by `lintel/cli` wrappers. `lintel.toml` records them under `[scopes.build_artifact]` and declares the wrapper surfaces under `[[executables]]`; their argv parsing is internal to the artifact, not the repository's public boundary.

## Lean generation

`generate-lean` emits a finite Lean module that imports `Lintel` and instantiates its structures and theorems from the facts. Accepted `semantic_review` findings come from `lintel.baseline.json` (override with `--baseline`); all other findings are pending. By default it then runs `lake build` and checks the generated module with `lake env lean`; use `--no-check` when the Lean toolchain is unavailable.

## Contract, baseline, and cache

Checks are locked by default. `lintel.toml` is the contract; the supporting artifacts are:

| Artifact | Role |
| --- | --- |
| `lintel.toml` | Layers, scopes, executables, source suffixes, and allowed edges |
| `lintel.lock` | Semantic hash of the contract, rule catalog, checker artifact digests, and baseline hash |
| `lintel.baseline.json` | Ratchet of existing architecture violations |
| `lintel.cache.json` | Untracked, content-addressed derived cache |

New violations fail. Removed violations require explicit acceptance to keep the baseline clean. Only architecture violations are baselineable: config errors, contract drift, unparsed source, and baseline errors cannot be accepted away. Use `--no-lock` only for bootstrap and debugging. Contract files are review-protected through `.github/CODEOWNERS`.

Validation is incremental by default. The cache is keyed by lock digests, policy, Python version, tool-root artifacts, and per-file hashes. A cache hit reuses extracted facts; a change re-extracts only when required and always re-runs the full global `check()` on the merged `FactSet`. `generate-lean` also skips repeated generated-instance checks when the generated file, `lintel/Lintel.lean`, and `lintel/lean-toolchain` are unchanged. Use `--no-cache` with `check` or `generate-lean` to force full extraction and rechecking. Delete `lintel.cache.json` at any time.

## Implementation layout

| Area | Responsibility |
| --- | --- |
| `lintel/core/` | Pure fact types, policy matching, checker rules, ports, hooks, review decisions, and use cases |
| `lintel/adapters/` | Source syntax translation, file/process I/O, and runtime composition behind core ports |
| `lintel/cli/` | Executable surfaces only |

Dependencies point inward: entrypoints -> adapters -> core. Core has no CLI, subprocess, JSON-I/O, or filesystem dependencies. Boundary-concern and wrapper-operation detection lives behind `SourceAnalyzerPort`. `lintel/adapters/language/` contains one analyzer per supported source language, registered by suffix; `lintel/adapters/contract_facts.py` only composes their normalized facts with scope assignments.

Python parse failures are recorded in an `unparsed` array and reported as `unparsed_source` violations. Native analyzers use language-specific token detection without parser-level `unparsed` facts. Every source suffix in a governed project must be declared in `[analysis] source_suffixes`; undeclared or unsupported suffixes fail closed as `unparsed_source`.

## Related documents

- [README.md](../README.md) — overview and quickstart.
- [docs/limitations.md](limitations.md) — durable limits and extractor-gap status.
- [ESCAPE_HATCHES.md](../ESCAPE_HATCHES.md) — exception mechanisms.
- [SEMANTIC_SCENARIOS.md](../SEMANTIC_SCENARIOS.md) — ambiguity cases requiring judgment.
- [semantic-decisions.md](semantic-decisions.md) — decision-model contract and trust boundary.
