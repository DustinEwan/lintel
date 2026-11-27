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
