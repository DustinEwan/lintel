"""Repository self-check workflow, independent of CLI and I/O adapters."""

from ..model import SelfCheckRequest, SelfCheckResult
from ..ports import (
    CheckerPort,
    ContractPort,
    FactCollectionPort,
    FactSinkPort,
    SelfConfigPort,
)


def run_self_check(
    config_source: SelfConfigPort,
    fact_collector: FactCollectionPort,
    fact_sink: FactSinkPort,
    checker: CheckerPort,
    contract: ContractPort,
    request: SelfCheckRequest,
) -> SelfCheckResult:
    config_violations = contract.validate_config(request.config_path)
    lock_violations = contract.verify_lock(request.config_path, request.locked)
    if config_violations or lock_violations:
        return SelfCheckResult(
            facts=(),
            violations=tuple(config_violations + lock_violations),
        )

    config = config_source.load_self_config(
        request.config_path, request.config_required
    )
    facts = fact_collector.collect_self_facts(config, request.overrides)
    if request.out:
        fact_sink.write_facts(request.out, facts)
    violations = tuple(checker.check(facts, config.policy))
    if request.locked:
        violations += contract.apply_baseline(violations)
    return SelfCheckResult(facts=facts, violations=violations)
