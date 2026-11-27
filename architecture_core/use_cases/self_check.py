"""Repository self-check workflow, independent of CLI and I/O adapters."""

from ..model import SelfCheckRequest, SelfCheckResult
from ..ports import (
    CheckerPort,
    FactCollectionPort,
    FactSinkPort,
    SelfConfigPort,
)


def run_self_check(
    config_source: SelfConfigPort,
    fact_collector: FactCollectionPort,
    fact_sink: FactSinkPort,
    checker: CheckerPort,
    request: SelfCheckRequest,
) -> SelfCheckResult:
    config = config_source.load_self_config(
        request.config_path, request.config_required
    )
    facts = fact_collector.collect_self_facts(config, request.overrides)
    if request.out:
        fact_sink.write_facts(request.out, facts)
    violations = checker.check(facts, config.policy)
    return SelfCheckResult(facts=facts, violations=tuple(violations))
