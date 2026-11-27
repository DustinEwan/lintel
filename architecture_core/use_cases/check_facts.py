"""Check extracted facts against a configured architecture policy."""

from ..model import CheckFactsRequest, Violation
from ..ports import CheckerPort, FactSourcePort, PolicySourcePort


def run_check_facts(
    fact_source: FactSourcePort,
    policy_source: PolicySourcePort,
    checker: CheckerPort,
    request: CheckFactsRequest,
) -> tuple[Violation, ...]:
    facts = fact_source.load_facts(request.facts_path)
    policy = policy_source.load_policy(request.config_path, request.policy_path)
    return tuple(checker.check(facts, policy))
