# Escape Hatches

The architecture control plane has exactly four exception mechanisms. A fifth
case, policy evolution, is normal use of the contract, not an exception.

The rule: an exception must be explicit, bounded, reviewable, and visible in
checker output. Silent skipping is not an exception; it is a defect.

Implementation status and deterministic extractor gaps live in [docs/limitations.md](docs/limitations.md).

| Case | Mechanism | Baselineable | Review authority | Status |
| --- | --- | --- | --- | --- |
| Bootstrapping | `init` scaffold | N/A | scaffold config in version control | Implemented |
| Known debt | accepted baseline | Yes | baseline diff + CODEOWNERS | Implemented |
| Unsupported syntax/language | `unparsed_source` | No | analyzer implementation | Implemented via declared suffixes |
| Semantic ambiguity | `semantic_review` | Yes | semantic judge or human review | Detectable flags implemented |
| Policy evolution | `update-lock` | N/A | config diff + CODEOWNERS | Implemented, intended use |

## 1. Bootstrapping

`lintel --root <dir> init --preset <name> --output <dir>` is the bootstrap hatch.
It creates the layer directories, a minimal `lintel.toml`, an empty
`lintel.baseline.json`, `lintel.lock`, and the agent instruction files. A scaffolded project
must pass `lintel --root <dir> check` with zero violations.

The command is preset-driven and non-interactive so it is deterministic and
usable in CI. "Walking the user through" means choosing a named structure; it
does not mean adding prompts that cannot be reviewed or replayed.

## 2. Known debt

`lintel.baseline.json` is the exclusion list. Each entry is a full
violation identity: rule, message, and fields. `accept-baseline` is explicit,
rewrites the baseline, and relocks the config. The ratchet enforces:

- new violations fail as `baseline_violation`;
- stale accepted entries fail as `baseline_stale`;
- contract errors, contract drift, unparsed source, and baseline errors are
  never baselineable;
- semantic review findings are baselineable only after review.

The baseline is debt, not permission. It must shrink or be justified in review.

## 3. Unsupported syntax or language

`[analysis] source_suffixes` is required and declares which suffixes in a
governed project are source code that must be understood. A declared suffix
with no registered `SourceAnalyzerPort` adapter produces `unparsed_source`.
A syntax that an adapter cannot parse completely produces the same rule.

The checker also has a built-in set of known source suffixes. A file with a
known source suffix that is not declared in the config produces
`unparsed_source` as `undeclared source suffix`. Only suffixes outside both
sets are treated as data and skipped. This makes an unsupported `.rb` file an
error by default rather than a silent pass.

This rule is non-baselineable. The fix is to add or extend an analyzer, or
rewrite the construct. Declaring more suffixes is a policy change and must be
reviewed.

## 4. Semantic ambiguity

Some constructs are syntactically valid but need intent or runtime judgment:
dynamic attribute lookup, dynamic module loading, and similar reflection.
Detected cases produce `semantic_review` with the source location and reason.

`semantic_review` is baselineable because the outcome of review is a human or
judge decision, not an automatic pass. `lintel --root <dir> review <fingerprint>
--decision compliant|violating|needs-human-review --reason <reason>` records that decision.
`compliant` accepts the finding and records its source for generated Lean; the
other decisions leave it pending. Every decision requires a reason and relocks
the baseline. The deterministic checker does not guess.

## 5. Policy evolution

Changing allowed edges, scopes, region ownership, executables, or declared
source suffixes is intended use of the contract, not an escape hatch.
`update-lock` records the reviewed change. CODEOWNERS protects the config and
lock so the change cannot bypass review.

## 6. Incremental cache bypass

`check --no-cache` and `generate-lean --no-cache` force full extraction and
rechecking. The default cache is derived, untracked state in
`lintel.cache.json`; it never narrows the checked universe. A stale,
missing, or malformed cache falls back to full extraction, and global rules are
always re-run on the merged facts.

## Non-goals

- No global disable switch for violations.
- No blanket directory exclusions beyond explicit scope declarations.
- No baseline acceptance for extraction failures.
- No silent pass for a declared source suffix without an analyzer.
- No CI use of `--no-lock`.
