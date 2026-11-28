"""Repository self-check workflow, independent of CLI and I/O adapters."""

from dataclasses import replace

from ..model import FactSet, SelfCheckRequest, SelfCheckResult, merge_decisions
from ..ports import (
    CheckerPort,
    ContractPort,
    FactCollectionPort,
    FactSinkPort,
    SelfConfigPort,
    SemanticDecisionPort,
    advisory_decisions,
    is_accepting,
    semantic_stage,
)


def run_self_check(
    config_source: SelfConfigPort,
    fact_collector: FactCollectionPort,
    fact_sink: FactSinkPort,
    checker: CheckerPort,
    contract: ContractPort,
    decision_source: SemanticDecisionPort,
    request: SelfCheckRequest,
) -> SelfCheckResult:
    config_violations = contract.validate_config(request.config_path)
    lock_violations = contract.verify_lock(request.config_path, request.locked)
    if config_violations or lock_violations:
        return SelfCheckResult(
            facts=FactSet(),
            violations=tuple(config_violations + lock_violations),
        )

    config = config_source.load_self_config(
        request.config_path, request.config_required
    )
    facts = fact_collector.collect_self_facts(config, request.overrides)
    if request.out:
        fact_sink.write_facts(request.out, facts)
    findings, proposals = semantic_stage(
        facts, config.policy, decision_source, request.stages
    )
    decisions = merge_decisions(
        facts.decisions, advisory_decisions(findings, proposals, facts)
    )
    checked_facts = replace(facts, decisions=decisions)
    violations = tuple(checker.check(checked_facts, config.policy, decisions))
    if request.locked:
        live = frozenset(
            item.fingerprint for item in decisions if is_accepting(item.decision)
        )
        violations += contract.apply_baseline(violations, live)
    return SelfCheckResult(
        facts=checked_facts, violations=violations, proposals=proposals
    )
