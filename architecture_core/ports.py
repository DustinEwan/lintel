"""Ports for executable workflows.

Core use cases depend on these interfaces, never on CLI parsers, filesystems,
subprocesses, or concrete extractors.
"""

from typing import Any, Protocol

from .model import (
    CheckFactsRequest,
    FactSet,
    PathOverrides,
    Policy,
    SelfCheckRequest,
    SelfConfig,
    SourceAnalysis,
    Violation,
)


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
    def check(self, facts: FactSet, policy: Policy) -> tuple[Violation, ...]: ...


class ContractPort(Protocol):
    def validate_config(self, path: str) -> tuple[Violation, ...]: ...

    def verify_lock(self, path: str, locked: bool) -> tuple[Violation, ...]: ...

    def apply_baseline(
        self, violations: tuple[Violation, ...]
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
    "SourceAnalyzerPort",
    "PolicySourcePort",
    "SelfConfigPort",
]
