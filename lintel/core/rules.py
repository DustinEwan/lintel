"""Stable rule catalog for the architecture checker."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RuleSpec:
    id: str
    summary: str
    fix: str
    baselineable: bool = True


RULES = (
    RuleSpec("config_invalid", "Configuration is structurally invalid.", "Correct the configuration field.", False),
    RuleSpec("config_unknown_key", "Configuration contains an unknown key.", "Remove the key or update the schema.", False),
    RuleSpec("config_bad_reference", "Configuration references an undeclared name.", "Declare the target or correct the reference.", False),
    RuleSpec("config_pattern_overlap", "Configuration patterns overlap ambiguously.", "Give one scope a distinct priority or pattern.", False),
    RuleSpec("config_missing_executable", "Declared executable path does not exist.", "Create the file or remove the declaration.", False),
    RuleSpec("contract_drift", "Committed contract does not match current inputs.", "Run the explicit lock update command and review the diff.", False),
    RuleSpec("baseline_violation", "Violation is not in the accepted baseline.", "Fix the violation or explicitly accept the new baseline entry.", False),
    RuleSpec("baseline_stale", "Accepted baseline entry no longer matches.", "Run the explicit baseline acceptance command to tighten the ratchet.", False),
    RuleSpec("missing_executable", "Declared executable produced no module facts.", "Check the executable path and its source language."),
    RuleSpec("undeclared_executable", "Discovered executable surface is not declared.", "Declare the surface in [[executables]] or scope it as a build artifact with a wrapper."),
    RuleSpec("executable_owner_mismatch", "Executable owner does not match its layer.", "Move the surface or correct the owner declaration."),
    RuleSpec("entrypoint_root_mismatch", "Executable is outside the configured entrypoints root.", "Move the surface or correct paths.entrypoints_root."),
    RuleSpec("direct_artifact_invocation", "Build artifact has no declared wrapper surface.", "Declare a wrapper for the artifact in [[build_artifacts]]."),
    RuleSpec("adapter_cli_concern", "Adapter owns an entrypoint-only concern.", "Move argv/help/exit handling into lintel/cli and inject parsed input through a port."),
    RuleSpec("core_cli_concern", "Core owns a boundary concern.", "Move boundary I/O behind a port; core should use plain data."),
    RuleSpec("use_case_dependency", "Use case depends on a mechanism outside ports.", "Depend on a core port instead of a concrete adapter or I/O mechanism."),
    RuleSpec("scope_convention_mismatch", "Path is assigned to an unexpected scope.", "Correct the scope pattern or move the file."),
    RuleSpec("scope_overlap", "Path matches multiple scopes with equal priority.", "Give one scope a higher priority."),
    RuleSpec("forbidden_scope_edge", "Dependency between scopes is forbidden.", "Move the code or remove the forbidden edge."),
    RuleSpec("unscoped_build_artifact", "Build artifact has no build_artifact scope.", "Add the source path to the build_artifact scope."),
    RuleSpec("fat_entrypoint", "Entrypoint contains logic beyond composition.", "Move extraction, policy, or workflow logic into the correct layer."),
    RuleSpec("core_outward", "Core depends on an outer layer.", "Invert the dependency through a port."),
    RuleSpec("forbidden_import", "Core imports a forbidden module.", "Remove the import or introduce a port."),
    RuleSpec("edge_not_allowed", "Layer dependency is not allowed.", "Move code or update an intentional, reviewed policy."),
    RuleSpec("cycle", "Dependency cycle detected.", "Break the cycle by introducing a port or moving shared data."),
    RuleSpec("unparsed_source", "Source could not be parsed completely.", "Add support for the syntax or rewrite it into a supported construct.", False),
    RuleSpec("semantic_review", "Code requires semantic review.", "Resolve the ambiguity or record a reviewed baseline entry."),
)

RULE_INDEX = {item.id: item for item in RULES}


def rule_spec(rule_id):
    return RULE_INDEX.get(rule_id)


def is_baselineable(rule_id):
    spec = rule_spec(rule_id)
    return True if spec is None else spec.baselineable


def catalog_data():
    return [asdict(item) for item in RULES]
