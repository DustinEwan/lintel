"""Check extracted facts against a configured architecture policy."""

from ..model import CheckFactsRequest, Violation
from ..ports import CheckerPort, ContractPort, FactSourcePort, PolicySourcePort


def run_check_facts(
    fact_source: FactSourcePort,
    policy_source: PolicySourcePort,
    checker: CheckerPort,
    contract: ContractPort,
    request: CheckFactsRequest,
) -> tuple[Violation, ...]:
    contract_violations = ()
    if request.config_path:
        contract_violations += contract.validate_config(request.config_path)
        contract_violations += contract.verify_lock(request.config_path, request.locked)
    if contract_violations:
        return tuple(contract_violations)

    facts = fact_source.load_facts(request.facts_path)
    policy = policy_source.load_policy(request.config_path, request.policy_path)
    violations = tuple(checker.check(facts, policy))
    if request.config_path and request.locked:
        violations += contract.apply_baseline(violations)
    return violations
