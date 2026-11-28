# Decision-model semantic decisions

Lintel's deterministic checker still owns imports, layers, scopes, executables,
wrappers, and extraction completeness. A decision model is used only for the
narrow `semantic_review` class: cases where syntax is valid but intent cannot be
proved from facts alone.

Lintel uses a configurable Decisions API endpoint. The example configuration
uses OpenRouter with `liquid/d1.2`; any endpoint implementing the same
Jev/SystemOne-style request and response shape can be used. The configured
`model` value is passed verbatim.

## Trust boundary

The decision model is an untrusted semantic input:

- It cannot edit config, lock, baseline, facts, or source.
- It cannot replace deterministic rules or extraction.
- It cannot legalize a policy change.
- Missing facts, provider errors, malformed responses, and low confidence fail
  closed; they never become `compliant`.
- Config and lock changes remain authority-gated through CODEOWNERS and normal
  review. Per-finding review can be automated for accepted decision classes.

This keeps the formal claim intact: Lean facts prove deterministic checks over
declared facts. Model decisions are inputs to those facts, not proofs of model
correctness.

## Decision contract

For each `semantic_review` finding, Lintel sends one typed question:

```json
{
  "decision": {
    "type": "choice",
    "instructions": "Decide this Lintel semantic-review finding.",
    "criteria": {
      "compliant": "The construct is allowed under the declared policy.",
      "violating": "The construct crosses a governed boundary.",
      "needs-human-review": "The evidence is insufficient for an automatic decision."
    }
  }
}
```

The question ID is `<answer_key>:<fingerprint>`, so each finding gets a stable
typed answer keyed by the configured prefix and fingerprint.

The `state` contains the rule, module, source path, line, reason, a bounded
source excerpt, and relevant policy context. It never contains credentials or
raw `semantic_decision` settings. Policy context includes regions, allowed and
forbidden edges, boundary allowed regions, excluded scopes, declared
executables, build artifacts, wrapper rules, use-case imports, and governed
source suffixes.

The response should include a `rationale` string. Lintel normalizes model
vocabulary (`allowed` → `compliant`, `violation` → `violating`) before
validation. Providers that omit rationale remain valid: Lintel derives a
bounded, evidence-based rationale from the chosen criterion, finding reason,
source, and line. The audit reason also records confidence. A supplied rationale
must be a non-empty string;
malformed values fail closed.

A decision below `semantic_decision.min_confidence` is downgraded to
`needs-human-review`, which leaves the finding pending.

## Audit record

Every model decision written to `lintel.baseline.json` records:

- stable finding fingerprint;
- rationale, supplied or derived, included in the audit reason;
- decision and confidence;
- schema version `2`;
- evidence hash of the submitted state;
- state hash of the complete request.

Human decisions remain valid and are treated as confidence `1.0` records.
`compliant` decisions add the finding to the accepted baseline, matching the
existing `lintel review` behavior. `violating` and undecided findings remain
visible findings.

Accepted entries remain in the baseline while their finding fingerprint is live.
If the source changes and the fingerprint no longer matches, the entry becomes
`baseline_stale`; a decision never hides that change permanently.

## Fact-first decomposition

The model is never asked to reconstruct source-of-truth facts. Extractors must
provide or fail closed on:

- aliases, call graphs, and declared helper ownership;
- generated/vendor markers and macro origin;
- wrapper-to-artifact declarations and wrapper operations;
- dependency graphs and declared adapter mechanisms;
- config diffs and pre-authorization.

See [SEMANTIC_SCENARIOS.md](../SEMANTIC_SCENARIOS.md) for the scenario catalog
and [limitations.md](limitations.md) for extractor status. Replacing native
extraction with guesswork remains out of scope.

## Commands

```sh
lintel semantic-check
lintel semantic-check --format json
lintel semantic-check --no-record
```

`model` is passed verbatim to the configured endpoint; no provider or model
allowlist is hardcoded.

`semantic-check` collects facts, asks the decision model about current
`semantic_review` findings, validates the typed answers, and records
high-confidence decisions. `--no-record` evaluates without mutating the
baseline. Provider failures exit nonzero and leave the baseline unchanged.

The aggregate checker receives decisions explicitly. Ordinary `lintel check`
passes none, so deterministic checks stay independent of recorded decisions.

The API key is read from the environment variable named by
`semantic_decision.api_key_env`; no key is stored in config, facts, or lock.

## Configuration

```toml
[semantic_decision]
model = "liquid/d1.2"
endpoint = "https://openrouter.ai/api/alpha/decisions"
api_key_env = "OPENROUTER_API_KEY"
answer_key = "decision"
min_confidence = 0.85
timeout = 20
max_findings = 64
```

Changing this table changes the contract digest and requires
`lintel update-lock`.
