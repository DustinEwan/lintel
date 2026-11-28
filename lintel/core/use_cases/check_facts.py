"""Check extracted facts against a configured architecture policy."""

from dataclasses import replace

from ..model import (
    CheckFactsRequest,
    FactSet,
    SelfCheckResult,
    merge_decisions,
)
from ..ports import (
    CheckerPort,
    ContractPort,
    FactSourcePort,
    PolicySourcePort,
    SemanticDecisionPort,
    advisory_decisions,
    is_accepting,
    semantic_stage,
)


def run_check_facts(
    fact_source: FactSourcePort,
    policy_source: PolicySourcePort,
    checker: CheckerPort,
    contract: ContractPort,
    decision_source: SemanticDecisionPort,
    request: CheckFactsRequest,
) -> SelfCheckResult:
    contract_violations = ()
    if request.config_path:
        contract_violations += contract.validate_config(request.config_path)
        contract_violations += contract.verify_lock(request.config_path, request.locked)
    if contract_violations:
        return SelfCheckResult(
            facts=FactSet(), violations=tuple(contract_violations)
        )

    facts = fact_source.load_facts(request.facts_path)
    policy = policy_source.load_policy(request.config_path, request.policy_path)
    findings, proposals = semantic_stage(
        facts, policy, decision_source, request.stages
    )
    decisions = merge_decisions(
        facts.decisions, advisory_decisions(findings, proposals, facts)
    )
    checked_facts = replace(facts, decisions=decisions)
    violations = tuple(checker.check(checked_facts, policy, decisions))
    if request.config_path and request.locked:
        live = frozenset(
            item.fingerprint for item in decisions if is_accepting(item.decision)
        )
        violations += contract.apply_baseline(violations, live)
    return SelfCheckResult(
        facts=checked_facts, violations=violations, proposals=proposals
    )
