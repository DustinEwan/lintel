# Escape Hatches

The architecture control plane has exactly four exception mechanisms. A fifth
case, policy evolution, is normal use of the contract, not an exception.

The rule: an exception must be explicit, bounded, reviewable, and visible in
checker output. Silent skipping is not an exception; it is a defect.

| Case | Mechanism | Baselineable | Review authority | Status |
| --- | --- | --- | --- | --- |
| Bootstrapping | `init` scaffold | N/A | scaffold config in version control | Implemented |
| Known debt | accepted baseline | Yes | baseline diff + CODEOWNERS | Implemented |
| Unsupported syntax/language | `unparsed_source` | No | analyzer implementation | Implemented via declared suffixes |
| Semantic ambiguity | `semantic_review` | Yes | semantic judge or human review | Detectable flags implemented |
| Policy evolution | `update-lock` | N/A | config diff + CODEOWNERS | Implemented, intended use |

## 1. Bootstrapping

`architecture.py init --preset <name> --output <dir>` is the bootstrap hatch.
It creates the layer directories, a minimal `architecture.toml`, an empty
`architecture.baseline.json`, and `architecture.lock`. A scaffolded project
must pass `architecture.py --root <dir> check` with zero violations.

The command is preset-driven and non-interactive so it is deterministic and
usable in CI. "Walking the user through" means choosing a named structure; it
does not mean adding prompts that cannot be reviewed or replayed.

## 2. Known debt

`architecture.baseline.json` is the exclusion list. Each entry is a full
violation identity: rule, message, and fields. `accept-baseline` is explicit,
rewrites the baseline, and relocks the config. The ratchet enforces:

- new violations fail as `baseline_violation`;
- stale accepted entries fail as `baseline_stale`;
- contract errors, contract drift, unparsed source, and baseline errors are
  never baselineable;
- semantic review findings are baselineable only after review.

The baseline is debt, not permission. It must shrink or be justified in review.

## 3. Unsupported syntax or language

`[analysis] source_suffixes` declares which suffixes in a governed project are
source code that must be understood. A declared suffix with no registered
`SourceAnalyzerPort` adapter produces `unparsed_source`. A syntax that an
adapter cannot parse completely produces the same rule.

This rule is non-baselineable. The fix is to add or extend an analyzer, or
rewrite the construct. Undeclared suffixes are data, not source, and are not
scanned. Declaring more suffixes is a policy change and must be reviewed.

## 4. Semantic ambiguity

Some constructs are syntactically valid but need intent or runtime judgment:
dynamic attribute lookup, dynamic module loading, and similar reflection.
Detected cases produce `semantic_review` with the source location and reason.

`semantic_review` is baselineable because the outcome of review is a human or
judge decision, not an automatic pass. Accepting one records that the case was
reviewed. A future semantic judge may classify these as compliant, violating,
or `needs-human-review`; the deterministic checker does not guess.

## 5. Policy evolution

Changing allowed edges, scopes, region ownership, executables, or declared
source suffixes is intended use of the contract, not an escape hatch.
`update-lock` records the reviewed change. CODEOWNERS protects the config and
lock so the change cannot bypass review.

## Non-goals

- No global disable switch for violations.
- No blanket directory exclusions beyond explicit scope declarations.
- No baseline acceptance for extraction failures.
- No silent pass for a declared source suffix without an analyzer.
- No CI use of `--no-lock`.
