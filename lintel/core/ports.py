"""Ports for executable workflows.

Core use cases depend on these interfaces, never on CLI parsers, filesystems,
subprocesses, or concrete extractors.
"""

from dataclasses import replace
from typing import Any, Protocol

from .model import (
    CheckFactsRequest,
    FactSet,
    PathOverrides,
    Policy,
    SelfCheckRequest,
    SelfConfig,
    SemanticDecision,
    SourceAnalysis,
    Violation,
    merge_decisions,
)
from .review import is_accepting
from .ratchet import violation_fingerprint


class SelfConfigPort(Protocol):
    def load_self_config(self, path: str, required: bool) -> SelfConfig: ...


class FactCollectionPort(Protocol):
    def collect_self_facts(
        self, config: SelfConfig, overrides: PathOverrides
    ) -> FactSet: ...


class SourceAnalyzerPort(Protocol):
    suffixes: tuple[str, ...]

    def analyze(self, relative_path: str, source: str) -> SourceAnalysis: ...


class FactSourcePort(Protocol):
    def load_facts(self, path: str) -> FactSet: ...


class FactSinkPort(Protocol):
    def write_facts(self, path: str, facts: FactSet) -> None: ...


class PolicySourcePort(Protocol):
    def load_policy(
        self, config_path: str | None, policy_path: str | None
    ) -> Policy: ...


class CheckerPort(Protocol):
    def check(
        self,
        facts: FactSet,
        policy: Policy,
        decisions: tuple[SemanticDecision, ...] = (),
    ) -> tuple[Violation, ...]: ...




class SemanticDecisionError(RuntimeError):
    """A semantic/model stage could not produce trustworthy decisions."""


class SemanticDecisionPort(Protocol):
    def semantic_review_findings(
        self, facts: FactSet, policy: Policy
    ) -> tuple[Violation, ...]: ...

    def propose_decisions(
        self, findings: tuple[Violation, ...], policy: Policy
    ) -> tuple[SemanticDecision, ...]: ...


def advisory_decisions(
    findings: tuple[Violation, ...],
    proposals: tuple[SemanticDecision, ...],
    facts: FactSet,
) -> tuple[SemanticDecision, ...]:
    """Keep model proposals from accepting a finding before human review."""
    accepted = {item.fingerprint for item in facts.decisions}
    return tuple(
        replace(item, decision="needs-human-review")
        for item in proposals
        if item.fingerprint not in accepted
    )


def semantic_stage(
    facts: FactSet,
    policy: Policy,
    decision_source: SemanticDecisionPort,
    stages: tuple[str, ...],
) -> tuple[tuple[Violation, ...], tuple[SemanticDecision, ...]]:
    """Return findings and advisory proposals for the semantic stage."""
    if "semantic" not in stages:
        return (), ()
    findings = decision_source.semantic_review_findings(facts, policy)
    accepted = {
        item.fingerprint
        for item in facts.decisions
        if is_accepting(item.decision)
    }
    pending = tuple(
        item
        for item in findings
        if violation_fingerprint(item) not in accepted
    )
    proposals = decision_source.propose_decisions(pending, policy)
    return findings, proposals


class ContractPort(Protocol):
    def validate_config(self, path: str) -> tuple[Violation, ...]: ...

    def verify_lock(self, path: str, locked: bool) -> tuple[Violation, ...]: ...

    def apply_baseline(
        self,
        violations: tuple[Violation, ...],
        live_fingerprints: frozenset[str] = frozenset(),
    ) -> tuple[Violation, ...]: ...

    def list_rules(self) -> tuple[dict[str, Any], ...]: ...

    def explain_rule(self, rule_id: str) -> dict[str, Any] | None: ...

    def update_lock(self, path: str) -> None: ...

    def accept_baseline(
        self, path: str, violations: tuple[Violation, ...]
    ) -> None: ...

    def scaffold(self, preset: str, output: str) -> None: ...


__all__ = [
    "SelfCheckRequest",
    "CheckerPort",
    "ContractPort",
    "FactCollectionPort",
    "FactSinkPort",
    "FactSourcePort",
    "SemanticDecisionPort",
    "SemanticDecisionError",
    "advisory_decisions",
    "semantic_stage",
    "is_accepting",
    "SourceAnalyzerPort",
    "PolicySourcePort",
    "SelfConfigPort",
]
