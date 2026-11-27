"""Ports for executable workflows.

Core use cases depend on these interfaces, never on CLI parsers, filesystems,
subprocesses, or concrete extractors.
"""

from typing import Protocol

from .model import (
    CheckFactsRequest,
    FactSet,
    PathOverrides,
    Policy,
    SelfCheckRequest,
    SelfConfig,
    Violation,
)


class SelfConfigPort(Protocol):
    def load_self_config(self, path: str, required: bool) -> SelfConfig: ...


class FactCollectionPort(Protocol):
    def collect_self_facts(
        self, config: SelfConfig, overrides: PathOverrides
    ) -> FactSet: ...


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


__all__ = [
    "SelfCheckRequest",
    "CheckerPort",
    "FactCollectionPort",
    "FactSinkPort",
    "FactSourcePort",
    "PolicySourcePort",
    "SelfConfigPort",
]
