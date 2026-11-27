from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Module:
    name: str
    path: str = ""


@dataclass(frozen=True)
class Dependency:
    source_module: str
    target_module: str
    kind: str = "import"
    source: str = ""
    line: int = 0


@dataclass(frozen=True)
class UnparsedSource:
    source: str
    line: int
    reason: str


@dataclass(frozen=True)
class FactSet:
    modules: tuple[Module, ...] = ()
    dependencies: tuple[Dependency, ...] = ()
    unparsed: tuple[UnparsedSource, ...] = ()


@dataclass(frozen=True)
class Region:
    name: str
    core: bool
    patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class Policy:
    default_region: str
    regions: tuple[Region, ...]
    allowed: dict[str, tuple[str, ...]]
    forbidden: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class Violation:
    rule: str
    message: str
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PathOverrides:
    core_root: str | None = None
    adapters_root: str | None = None


@dataclass(frozen=True)
class SelfConfig:
    core_root: str
    adapters_root: str
    policy: Policy


@dataclass(frozen=True)
class SelfCheckRequest:
    config_path: str
    config_required: bool
    overrides: PathOverrides
    out: str | None = None


@dataclass(frozen=True)
class SelfCheckResult:
    facts: FactSet
    violations: tuple[Violation, ...]


@dataclass(frozen=True)
class CheckFactsRequest:
    facts_path: str
    config_path: str | None = None
    policy_path: str | None = None


def facts_to_dict(facts):
    return {
        "version": 1,
        "language": "self",
        "modules": [
            {"name": module.name, "path": module.path} for module in facts.modules
        ],
        "dependencies": [
            {
                "from": dep.source_module,
                "to": dep.target_module,
                "kind": dep.kind,
                "source": dep.source,
                "line": dep.line,
            }
            for dep in facts.dependencies
        ],
        "unparsed": [
            {"source": item.source, "line": item.line, "reason": item.reason}
            for item in facts.unparsed
        ],
    }


def facts_from_dict(data):
    return FactSet(
        modules=tuple(
            Module(item["name"], item.get("path", ""))
            for item in data.get("modules", [])
        ),
        dependencies=tuple(
            Dependency(
                item["from"],
                item["to"],
                item.get("kind", "import"),
                item.get("source", ""),
                int(item.get("line") or 0),
            )
            for item in data.get("dependencies", [])
        ),
        unparsed=tuple(
            UnparsedSource(
                item.get("source", "?"),
                int(item.get("line") or 0),
                item.get("reason", "unsupported syntax"),
            )
            for item in data.get("unparsed", [])
        ),
    )


def policy_from_dict(data):
    return Policy(
        default_region=data.get("default_region", "external"),
        regions=tuple(
            Region(
                item["name"],
                bool(item.get("core", False)),
                tuple(item.get("patterns", [])),
            )
            for item in data.get("regions", [])
        ),
        allowed={
            name: tuple(targets)
            for name, targets in data.get("allowed", {}).items()
        },
        forbidden={
            name: tuple(patterns)
            for name, patterns in data.get("forbidden", {}).items()
        },
    )


def violation_to_dict(violation):
    result = {"rule": violation.rule, "message": violation.message}
    result.update(violation.fields)
    return result
