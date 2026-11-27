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
class Entrypoint:
    module: str
    path: str
    kind: str = "python"


@dataclass(frozen=True)
class BoundaryConcernUse:
    module: str
    concern: str
    category: str
    source: str
    line: int


@dataclass(frozen=True)
class ScopeAssignment:
    path: str
    scope: str
    pattern: str = ""
    priority: int = 100
    expected_scope: str = ""


@dataclass(frozen=True)
class WrapperOperation:
    module: str
    operation: str
    target: str
    source: str
    line: int



@dataclass(frozen=True)
class SourceAnalysis:
    entrypoint: Entrypoint | None = None
    concerns: tuple[BoundaryConcernUse, ...] = ()
    wrapper_operations: tuple[WrapperOperation, ...] = ()
    unparsed: tuple[UnparsedSource, ...] = ()


@dataclass(frozen=True)
class BuildArtifact:
    source: str
    wrapper: str


@dataclass(frozen=True)
class ExecutableDeclaration:
    name: str
    path: str
    owner: str


@dataclass(frozen=True)
class FactSet:
    modules: tuple[Module, ...] = ()
    dependencies: tuple[Dependency, ...] = ()
    unparsed: tuple[UnparsedSource, ...] = ()
    entrypoints: tuple[Entrypoint, ...] = ()
    concerns: tuple[BoundaryConcernUse, ...] = ()
    scopes: tuple[ScopeAssignment, ...] = ()
    wrapper_operations: tuple[WrapperOperation, ...] = ()


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
    entrypoints_root: str = "external/cli"
    scopes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    scope_priorities: dict[str, int] = field(default_factory=dict)
    scope_conventions: dict[str, str] = field(default_factory=dict)
    excluded_scopes: tuple[str, ...] = ("fixture", "test", "example", "generated", "vendor")
    forbidden_scope_edges: tuple[tuple[str, str], ...] = ()
    boundary_allowed_regions: dict[str, tuple[str, ...]] = field(default_factory=dict)
    executables: tuple[ExecutableDeclaration, ...] = ()
    build_artifacts: tuple[BuildArtifact, ...] = ()
    use_case_allowed_imports: tuple[str, ...] = ()
    wrapper_allowed_imports: tuple[str, ...] = ()
    wrapper_forbidden_imports: tuple[str, ...] = ()
    wrapper_allowed_commands: tuple[str, ...] = ()


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
    entrypoints_root: str = "external/cli"
    excluded_scopes: tuple[str, ...] = ("fixture", "test", "example", "generated", "vendor")
    scope_conventions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SelfCheckRequest:
    config_path: str
    config_required: bool = False
    overrides: PathOverrides = field(default_factory=PathOverrides)
    out: str | None = None
    locked: bool = True


@dataclass(frozen=True)
class SelfCheckResult:
    facts: FactSet
    violations: tuple[Violation, ...]


@dataclass(frozen=True)
class CheckFactsRequest:
    facts_path: str
    config_path: str | None = None
    policy_path: str | None = None
    locked: bool = True


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
        "entrypoints": [
            {"module": item.module, "path": item.path, "kind": item.kind}
            for item in facts.entrypoints
        ],
        "concerns": [
            {
                "module": item.module,
                "concern": item.concern,
                "category": item.category,
                "source": item.source,
                "line": item.line,
            }
            for item in facts.concerns
        ],
        "scopes": [
            {
                "path": item.path,
                "scope": item.scope,
                "pattern": item.pattern,
                "priority": item.priority,
                "expected_scope": item.expected_scope,
            }
            for item in facts.scopes
        ],
        "wrapper_operations": [
            {
                "module": item.module,
                "operation": item.operation,
                "target": item.target,
                "source": item.source,
                "line": item.line,
            }
            for item in facts.wrapper_operations
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
        entrypoints=tuple(
            Entrypoint(
                item.get("module", ""),
                item.get("path", ""),
                item.get("kind", "python"),
            )
            for item in data.get("entrypoints", [])
        ),
        concerns=tuple(
            BoundaryConcernUse(
                item.get("module", ""),
                item.get("concern", ""),
                item.get("category", ""),
                item.get("source", ""),
                int(item.get("line") or 0),
            )
            for item in data.get("concerns", [])
        ),
        scopes=tuple(
            ScopeAssignment(
                item.get("path", ""),
                item.get("scope", ""),
                item.get("pattern", ""),
                int(item.get("priority") or 0),
                item.get("expected_scope", ""),
            )
            for item in data.get("scopes", [])
        ),
        wrapper_operations=tuple(
            WrapperOperation(
                item.get("module", ""),
                item.get("operation", ""),
                item.get("target", ""),
                item.get("source", ""),
                int(item.get("line") or 0),
            )
            for item in data.get("wrapper_operations", [])
        ),
    )


def _artifacts(items, first="path", second="owner"):
    return tuple(
        BuildArtifact(item.get(first, ""), item.get(second, ""))
        for item in items or []
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
        entrypoints_root=data.get("entrypoints_root", "external/cli"),
        scopes={
            name: tuple(patterns)
            for name, patterns in data.get("scopes", {}).items()
        },
        scope_priorities={
            name: int(priority)
            for name, priority in data.get("scope_priorities", {}).items()
        },
        scope_conventions={
            key: value
            for key, value in data.get("scope_conventions", {}).items()
        },
        excluded_scopes=tuple(data.get("excluded_scopes", ())),
        forbidden_scope_edges=tuple(
            tuple(edge) for edge in data.get("forbidden_scope_edges", ()) if len(edge) >= 2
        ),
        boundary_allowed_regions={
            name: tuple(regions)
            for name, regions in data.get("boundary_allowed_regions", {}).items()
        },
        executables=tuple(
            ExecutableDeclaration(
                item.get("name", ""), item.get("path", ""), item.get("owner", "")
            )
            for item in data.get("executables", ())
        ),
        build_artifacts=_artifacts(data.get("build_artifacts", ()), "source", "wrapper"),
        use_case_allowed_imports=tuple(data.get("use_case_allowed_imports", ())),
        wrapper_allowed_imports=tuple(data.get("wrapper_allowed_imports", ())),
        wrapper_forbidden_imports=tuple(data.get("wrapper_forbidden_imports", ())),
        wrapper_allowed_commands=tuple(data.get("wrapper_allowed_commands", ())),
    )


def violation_to_dict(violation):
    result = {"rule": violation.rule, "message": violation.message}
    result.update(violation.fields)
    if violation.rule:
        from .rules import rule_spec

        spec = rule_spec(violation.rule)
        if spec:
            result.setdefault("fix", spec.fix)
    return result
