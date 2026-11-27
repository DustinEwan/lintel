"""Generate finite Lean instances from architecture facts."""

import heapq
import json

from architecture_core.checker import match_any, module_name_from_path, region_for


def _constructor_map(names, prefix):
    return {name: f"{prefix}{index}" for index, name in enumerate(sorted(names))}


def _emit_predicate(lines, name, params, rows, exhaustive=False):
    param_sig = " → ".join(type_name for _, type_name in params)
    vars_decl = " ".join(f"({var} : {type_name})" for var, type_name in params)
    vars_use = " ".join(var for var, _ in params)
    lines.append(f"def {name}Bool : {param_sig} → Bool")
    for row in sorted(rows):
        lines.append(
            "  | "
            + ", ".join(
                value if "." in value else f"{params[index][1]}.{value}"
                for index, value in enumerate(row)
            )
            + " => true"
        )
    if not exhaustive:
        lines.append("  | _, _ => false" if len(params) == 2 else "  | _ => false")
    lines.append(f"def {name} {vars_decl} : Prop := {name}Bool {vars_use} = true")
    lines.append(
        f"instance {name}Decidable {vars_decl} : Decidable ({name} {vars_use}) :="
    )
    lines.append(f"  inferInstanceAs (Decidable ({name}Bool {vars_use} = true))")
    lines.append("")


def generate(facts, policy, accepted_review_sources=()):
    module_names = {item.name for item in facts.modules}
    edges = set()
    for edge in facts.dependencies:
        module_names.add(edge.source_module)
        module_names.add(edge.target_module)
        edges.add((edge.source_module, edge.target_module))
    for item in facts.concerns:
        module_names.add(item.module)
    for item in facts.entrypoints:
        module_names.add(item.module)
    for item in facts.wrapper_operations:
        module_names.add(item.module)
    for item in facts.reviews:
        module_names.add(item.module)
    for item in policy.executables:
        module_names.add(module_name_from_path(item.path))
    for item in policy.build_artifacts:
        module_names.add(module_name_from_path(item.wrapper))
    if not module_names:
        module_names.add("__empty__")

    regions = {item.name for item in policy.regions}
    regions.add(policy.default_region)
    regions.update(policy.allowed)
    for targets in policy.allowed.values():
        regions.update(targets)
    for module in module_names:
        regions.add(region_for(module, policy).name)

    modules = _constructor_map(module_names, "m")
    region_index = _constructor_map(regions, "r")
    source_to_region = {
        name: region_for(name, policy).name for name in module_names
    }
    module_paths = {item.path: item.name for item in facts.modules}
    module_paths.update({item.path: item.module for item in facts.entrypoints})

    source_edges = {
        (modules[source], modules[target])
        for source, target in edges
        if source in modules and target in modules
    }
    allowed = {(region, region) for region in region_index.values()}
    for source, targets in policy.allowed.items():
        if source not in region_index:
            continue
        for target in targets:
            if target in region_index:
                allowed.add((region_index[target], region_index[source]))

    core_region_names = {item.name for item in policy.regions if item.core}
    non_core_region_names = {item.name for item in policy.regions if not item.core}
    core_modules = {
        module for module in module_names if source_to_region[module] in core_region_names
    }
    port_modules = {
        module for module in module_names if source_to_region[module] == "ports"
    }
    adapter_modules = {
        source
        for source, target in edges
        if target in port_modules
        and source_to_region.get(source) in non_core_region_names
    }
    caller_edges = {
        (source, target)
        for source, target in edges
        if target in port_modules and source in core_modules
    }

    ranks = {module: 0 for module in module_names}
    successors = {module: [] for module in module_names}
    indegree = {module: 0 for module in module_names}
    for source, target in edges:
        successors[source].append(target)
        indegree[target] += 1
    ready = sorted(module for module in module_names if indegree[module] == 0)
    heapq.heapify(ready)
    order = 0
    while ready:
        module = heapq.heappop(ready)
        ranks[module] = len(module_names) - 1 - order
        order += 1
        for target in sorted(successors[module]):
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready, target)
    if order != len(module_names):
        ranks = {module: 0 for module in module_names}

    scope_names = set(policy.scopes)
    scope_names.update({"none"})
    scope_assignments = {}
    scope_expected = {}
    for item in facts.scopes:
        current = scope_assignments.get(item.path)
        if current is None or item.priority > current[0] or (
            item.priority == current[0] and item.scope < current[1]
        ):
            scope_assignments[item.path] = (item.priority, item.scope)
        if item.expected_scope:
            scope_expected[item.path] = item.expected_scope
    scope_names.update(scope for _, scope in scope_assignments.values())
    scope_names.update(scope_expected.values())
    scopes = _constructor_map(scope_names, "s")
    path_index = _constructor_map(scope_assignments, "p")
    path_priorities = {}
    path_ambiguous = set()
    for item in facts.scopes:
        by_priority = path_priorities.setdefault(item.path, {})
        by_priority.setdefault(item.priority, set()).add(item.scope)
    for path, by_priority in path_priorities.items():
        if any(len(names) > 1 for names in by_priority.values()):
            path_ambiguous.add(path)

    assigned_modules = {}
    expected_modules = {}
    for module in sorted(module_names):
        path = next(
            (item.path for item in facts.modules if item.name == module), ""
        )
        if path in scope_assignments:
            scope = scope_assignments[path][1]
            assigned_modules[module] = scope
            expected_modules[module] = scope_expected.get(path, scope)
        else:
            assigned_modules[module] = "none"
            expected_modules[module] = "none"

    concern_modules = {
        "argv": set(),
        "environment": set(),
        "exitCode": set(),
        "terminalIO": set(),
    }
    entrypoint_concern_modules = set()
    concern_map = {
        "argv": "argv",
        "argv_parse": "argv",
        "env": "environment",
        "exit": "exitCode",
        "terminal_io": "terminalIO",
    }
    for item in facts.concerns:
        if item.category == "entrypoint_only":
            entrypoint_concern_modules.add(item.module)
        kind = concern_map.get(item.concern)
        if kind:
            concern_modules[kind].add(item.module)

    declared_executable_modules = {
        module_name_from_path(item.path) for item in policy.executables
    }
    wrapped_modules = {
        module_name_from_path(item.wrapper) for item in policy.build_artifacts
    }
    discovered_modules = {item.module for item in facts.entrypoints}
    excluded_scopes = set(policy.excluded_scopes)
    excluded_scopes.add("build_artifact")
    governed_modules = set()
    for item in facts.entrypoints:
        scopes_for_path = {
            scope.scope for scope in facts.scopes if scope.path == item.path
        }
        if not (scopes_for_path & excluded_scopes):
            governed_modules.add(item.module)
    entry_region = "entrypoints" if "entrypoints" in region_index else policy.default_region

    operation_modules = {kind: set() for kind in (
        "importOp",
        "subprocess",
        "policyConstruction",
        "sourceWalk",
        "parseSource",
    )}
    subprocess_targets = {module: set() for module in module_names}
    for item in facts.wrapper_operations:
        kind = {
            "import": "importOp",
            "subprocess": "subprocess",
            "policy_construction": "policyConstruction",
            "policyConstruction": "policyConstruction",
            "source_walk": "sourceWalk",
            "sourceWalk": "sourceWalk",
            "parse_source": "parseSource",
            "parseSource": "parseSource",
        }.get(item.operation)
        if kind:
            operation_modules[kind].add(item.module)
        if item.operation == "subprocess":
            subprocess_targets.setdefault(item.module, set()).add(item.target)
    declared_command_modules = {
        module
        for module, targets in subprocess_targets.items()
        if targets
        and all(
            match_any(target.split("/", 1)[-1], policy.wrapper_allowed_commands)
            for target in targets
            if target != "unknown"
        )
    }

    review_modules = set()
    for item in facts.reviews:
        scopes_for_path = {
            scope.scope for scope in facts.scopes if scope.path == item.source
        }
        if not (scopes_for_path & set(policy.excluded_scopes)):
            review_modules.add(item.module)
    accepted_review_modules = {
        module_paths[source]
        for source in accepted_review_sources
        if source in module_paths
    }
    pending_review_modules = review_modules - accepted_review_modules

    lines = [
        "import Architecture",
        "",
        "set_option maxHeartbeats 2000000",
        "/-! Generated by architecture.py generate-lean. Do not edit. -/",
        "",
        "",
        "inductive GeneratedModule where",
    ]
    lines.extend(f"  | {ctor}" for ctor in modules.values())
    lines.extend(
        [
            "  deriving DecidableEq, Repr",
            "",
            "inductive GeneratedRegion where",
        ]
    )
    lines.extend(f"  | {ctor}" for ctor in region_index.values())
    lines.extend(
        [
            "  deriving DecidableEq, Repr",
            "",
            "inductive GeneratedScope where",
        ]
    )
    lines.extend(f"  | {ctor}" for ctor in scopes.values())
    lines.extend(
        [
            "  deriving DecidableEq, Repr",
            "",
            "inductive GeneratedPath where",
        ]
    )
    lines.extend(f"  | {ctor}" for ctor in path_index.values())
    lines.extend(
        [
            "  deriving DecidableEq, Repr",
            "",
            "def generatedModuleLabel : GeneratedModule → String",
        ]
    )
    for name, ctor in modules.items():
        lines.append(f"  | GeneratedModule.{ctor} => {json.dumps(name)}")
    lines.extend(["", "def generatedRegionLabel : GeneratedRegion → String"])
    for name, ctor in region_index.items():
        lines.append(f"  | GeneratedRegion.{ctor} => {json.dumps(name)}")
    lines.extend(["", "def generatedPathLabel : GeneratedPath → String"])
    for name, ctor in path_index.items():
        lines.append(f"  | GeneratedPath.{ctor} => {json.dumps(name)}")
    lines.extend(["", "def generatedPathScopeOf : GeneratedPath → GeneratedScope"])
    for name, ctor in path_index.items():
        scope = scope_assignments[name][1]
        lines.append(f"  | GeneratedPath.{ctor} => GeneratedScope.{scopes[scope]}")
    lines.extend(
        ["", "def generatedPathExpectedScopeOf : GeneratedPath → GeneratedScope"]
    )
    for name, ctor in path_index.items():
        scope = scope_expected.get(name, scope_assignments[name][1])
        lines.append(f"  | GeneratedPath.{ctor} => GeneratedScope.{scopes[scope]}")
    lines.extend(["", "def generatedRegion : GeneratedModule → GeneratedRegion"])
    for module in sorted(module_names):
        lines.append(
            f"  | GeneratedModule.{modules[module]} => "
            f"GeneratedRegion.{region_index[source_to_region[module]]}"
        )
    lines.extend(["", "def generatedRank : GeneratedModule → Nat"])
    for module in sorted(module_names):
        lines.append(f"  | GeneratedModule.{modules[module]} => {ranks[module]}")
    lines.extend([""])

    dep_rows = {(modules[source], modules[target]) for source, target in edges}
    _emit_predicate(
        lines,
        "generatedDep",
        (("a", "GeneratedModule"), ("b", "GeneratedModule")),
        dep_rows,
    )
    _emit_predicate(
        lines,
        "generatedCore",
        (("a", "GeneratedModule"),),
        {(modules[module],) for module in core_modules},
    )
    _emit_predicate(
        lines,
        "generatedAllowed",
        (("a", "GeneratedRegion"), ("b", "GeneratedRegion")),
        allowed,
    )
    _emit_predicate(
        lines,
        "generatedCoreRegion",
        (("a", "GeneratedRegion"),),
        {(region_index[name],) for name in core_region_names if name in region_index},
    )
    _emit_predicate(
        lines,
        "generatedPortModule",
        (("a", "GeneratedModule"),),
        {(modules[module],) for module in port_modules},
    )
    _emit_predicate(
        lines,
        "generatedAdapterModule",
        (("a", "GeneratedModule"),),
        {(modules[module],) for module in adapter_modules},
    )
    _emit_predicate(
        lines,
        "generatedCoreCallerModule",
        (("a", "GeneratedModule"), ("b", "GeneratedModule")),
        {(modules[source], modules[target]) for source, target in caller_edges},
    )
    _emit_predicate(
        lines,
        "generatedUseCase",
        (("a", "GeneratedModule"),),
        {
            (modules[module],)
            for module in module_names
            if module.startswith("architecture_core.use_cases.")
        },
    )
    _emit_predicate(
        lines,
        "generatedUseCaseAllowed",
        (("a", "GeneratedModule"),),
        {
            (modules[target],)
            for target in module_names
            if match_any(target, policy.use_case_allowed_imports)
        },
    )
    _emit_predicate(
        lines,
        "generatedAssignedScope",
        (("a", "GeneratedModule"),),
        {
            (modules[module],)
            for module in module_names
            if assigned_modules[module] != "none"
        },
    )
    _emit_predicate(
        lines,
        "generatedScopeOfBool",
        (
            ("a", "GeneratedModule"),
            ("s", "GeneratedScope"),
        ),
        {
            (modules[module], scopes[assigned_modules[module]])
            for module in module_names
            if assigned_modules[module] != "none"
        },
    )
    _emit_predicate(
        lines,
        "generatedExpectedScopeOfBool",
        (
            ("a", "GeneratedModule"),
            ("s", "GeneratedScope"),
        ),
        {
            (modules[module], scopes[expected_modules[module]])
            for module in module_names
            if assigned_modules[module] != "none"
        },
    )
    lines.extend(
        [
            "def generatedScopeOf : GeneratedModule → GeneratedScope",
        ]
    )
    for module in sorted(module_names):
        lines.append(
            f"  | GeneratedModule.{modules[module]} => GeneratedScope.{scopes[assigned_modules[module]]}"
        )
    lines.extend(
        [
            "def generatedExpectedScopeOf : GeneratedModule → GeneratedScope",
        ]
    )
    for module in sorted(module_names):
        lines.append(
            f"  | GeneratedModule.{modules[module]} => GeneratedScope.{scopes[expected_modules[module]]}"
        )
    lines.extend([""])
    _emit_predicate(
        lines,
        "generatedPathAmbiguous",
        (("p", "GeneratedPath"),),
        {(path_index[path],) for path in path_ambiguous},
    )

    for kind, ctor in (
        ("argv", "generatedConcernArgv"),
        ("environment", "generatedConcernEnvironment"),
        ("exitCode", "generatedConcernExitCode"),
        ("terminalIO", "generatedConcernTerminalIO"),
    ):
        _emit_predicate(
            lines,
            ctor,
            (("a", "GeneratedModule"),),
            {(modules[module],) for module in concern_modules[kind]},
        )
    _emit_predicate(
        lines,
        "generatedEntrypointConcern",
        (("a", "GeneratedModule"),),
        {(modules[module],) for module in entrypoint_concern_modules},
    )
    _emit_predicate(
        lines,
        "generatedDeclaredEntry",
        (("a", "GeneratedModule"),),
        {(modules[module],) for module in declared_executable_modules},
    )
    _emit_predicate(
        lines,
        "generatedWrappedArtifact",
        (("a", "GeneratedModule"),),
        {(modules[module],) for module in wrapped_modules},
    )
    _emit_predicate(
        lines,
        "generatedDiscoveredEntry",
        (("a", "GeneratedModule"),),
        {(modules[module],) for module in discovered_modules},
    )
    _emit_predicate(
        lines,
        "generatedGovernedEntry",
        (("a", "GeneratedModule"),),
        {(modules[module],) for module in governed_modules},
    )
    _emit_predicate(
        lines,
        "generatedEntryRegion",
        (("a", "GeneratedModule"),),
        {
            (modules[module],)
            for module in module_names
            if source_to_region[module] == entry_region
        },
    )
    _emit_predicate(
        lines,
        "generatedWrapperOp",
        (
            ("op", "WrapperOperationKind"),
            ("m", "GeneratedModule"),
        ),
        {
            (f"WrapperOperationKind.{kind}", modules[module])
            for kind, modules_for_kind in operation_modules.items()
            for module in modules_for_kind
        },
    )
    _emit_predicate(
        lines,
        "generatedWrapperDeclared",
        (("a", "GeneratedModule"),),
        {(modules[module],) for module in declared_command_modules},

    )
    _emit_predicate(
        lines,
        "generatedReviewState",
        (
            ("state", "ReviewState"),
            ("m", "GeneratedModule"),
        ),
        (
            {(("ReviewState.pending"), modules[module]) for module in pending_review_modules}
            | {
                (("ReviewState.accepted"), modules[module])
                for module in accepted_review_modules
            }
        ),
    )

    lines.extend(
        [
            "def generatedArchitecture : Architecture where",
            "  Module := GeneratedModule",
            "  dep := generatedDep",
            "  Core := generatedCore",
            "  core_closed := by",
            "    intro a b ha h",
            "    revert ha h",
            "    cases a <;> cases b <;> decide",
            "instance generatedArchitectureCoreDecidable (a : GeneratedModule) : Decidable (generatedArchitecture.Core a) :=",
            "  generatedCoreDecidable a",
            "instance generatedArchitectureDepDecidable (a b : GeneratedModule) : Decidable (generatedArchitecture.dep a b) :=",
            "  generatedDepDecidable a b",
            "",
            "",
            "",
            "def generatedEdgePolicy : EdgePolicy GeneratedRegion where",
            "  allowed := generatedAllowed",
            "  allowed_refl := by",
            "    intro r",
            "    cases r <;> decide",
            "  allowed_trans := by",
            "    intro r s t hrs hst",
            "    revert hrs hst",
            "    cases r <;> cases s <;> cases t <;> decide",
            "",
            "instance generatedEdgePolicyDecidable (a b : GeneratedRegion) : Decidable (generatedEdgePolicy.allowed a b) :=",
            "  generatedAllowedDecidable a b",
            "",
            "def generatedPolicyArchitecture : PolicyArchitecture where",
            "  Module := GeneratedModule",
            "  Region := GeneratedRegion",
            "  dep := generatedDep",
            "  region := generatedRegion",
            "  policy := generatedEdgePolicy",
            "  dep_allowed := by",
            "    intro a b h",
            "    revert h",
            "    cases a <;> cases b <;> decide",
            "",
            "theorem generated_rank_strict {a b : GeneratedModule} (h : generatedDep a b) :",
            "    generatedRank b < generatedRank a := by",
            "  revert h",
            "  cases a <;> cases b <;> decide",
            "",
            "theorem generated_acyclic : Acyclic generatedDep :=",
            "  acyclic_of_rank generatedDep generatedRank generated_rank_strict",
            "",
            "def generatedAcyclicArchitecture : AcyclicArchitecture where",
            "  arch := generatedArchitecture",
            "  acyclic := generated_acyclic",
            "",
            "def generatedNestedArchitecture : NestedArchitecture where",
            "  outer := generatedArchitecture",
            "  inner := generatedArchitecture",
            "  embed := id",
            "  embed_core := by",
            "    intro m h",
            "    exact h",
            "  embed_dep := by",
            "    intro a b h",
            "    exact h",
            "",
            "def generatedPortOf (m : GeneratedModule) (h : generatedPortModule m) :",
            "    Port generatedArchitecture where",
            "  contract := m",
            "  owned_by_core := by",
            "    revert h",
            "    cases m <;> decide",
            "",
            "def generatedAdapterOf (a p : GeneratedModule)",
            "    (ha : generatedAdapterModule a) (hp : generatedPortModule p)",
            "    (h : generatedDep a p) : Adapter generatedArchitecture (generatedPortOf p hp) where",
            "  module := a",
            "  outer := by",
            "    revert ha",
            "    cases a <;> decide",
            "  implements := h",
            "",
            "theorem generated_adapter_unreachable_from_core {c a p : GeneratedModule}",
            "    (hc : generatedCore c) (ha : generatedAdapterModule a)",
            "    (hp : generatedPortModule p) (h : generatedDep a p) :",
            "    ¬ Path generatedDep c a :=",
            "  adapter_unreachable_from_core generatedArchitecture",
            "    (generatedPortOf p hp) (generatedAdapterOf a p ha hp h) hc",
            "",
            "def generatedInvertedCallOf (c p a : GeneratedModule)",
            "    (hc : generatedCore c) (hp : generatedPortModule p)",
            "    (ha : generatedAdapterModule a) (hcp : generatedDep c p)",
            "    (h : generatedDep a p) :",
            "    InvertedCall generatedArchitecture (generatedPortOf p hp)",
            "      (generatedAdapterOf a p ha hp h) where",
            "  caller := c",
            "  core_caller := hc",
            "  calls_through_port := hcp",
            "",
            "theorem generated_core_caller_calls_port {c p : GeneratedModule}",
            "    (hcp : generatedCoreCallerModule c p) : generatedDep c p := by",
            "  revert hcp",
            "  cases c <;> cases p <;> decide",
            "",
            "theorem generated_inverted_call_avoids_adapter (c p a : GeneratedModule)",
            "    (hc : generatedCore c) (hp : generatedPortModule p)",
            "    (ha : generatedAdapterModule a) (hcp : generatedDep c p)",
            "    (h : generatedDep a p) : ¬ generatedDep c a := ",
            "  inverted_call_avoids_adapter generatedArchitecture",
            "    (generatedPortOf p hp) (generatedAdapterOf a p ha hp h)",
            "    (generatedInvertedCallOf c p a hc hp ha hcp h)",
            "",
            "def generatedRegionOrder : RegionOrder GeneratedRegion where",
            "  le := generatedAllowed",
            "  refl := generatedEdgePolicy.allowed_refl",
            "  trans := generatedEdgePolicy.allowed_trans",
            "instance generatedRegionOrderDecidable (a b : GeneratedRegion) : Decidable (generatedRegionOrder.le a b) :=",
            "  generatedAllowedDecidable a b",
            "",
            "",
            "def generatedLayered : MultiCoreLayeredArchitecture where",
            "  Module := GeneratedModule",
            "  Region := GeneratedRegion",
            "  dep := generatedDep",
            "  Core := generatedCore",
            "  core_closed := generatedArchitecture.core_closed",
            "  region := generatedRegion",
            "  order := generatedRegionOrder",
            "  coreRegions := generatedCoreRegion",
            "  region_of_core := by",
            "    intro m h",
            "    revert h",
            "    cases m <;> decide",
            "  inward_region := by",
            "    intro a b h",
            "    revert h",
            "    cases a <;> cases b <;> decide",
            "",
            "theorem generated_core_region_path {a b : GeneratedModule}",
            "    (ha : generatedCore a) (h : Path generatedDep a b) :",
            "    generatedCoreRegion (generatedRegion b) :=",
            "  multi_core_region_path generatedLayered ha h",
            "",
            "def generatedUseCaseBoundary : UseCaseBoundary generatedArchitecture where",
            "  UseCase := generatedUseCase",
            "  AllowedTarget := generatedUseCaseAllowed",
            "  pure := by",
            "    intro a b ha h",
            "    revert ha h",
            "    cases a <;> cases b <;> decide",
            "",
            "def generatedEntrypoints : EntrypointInventory generatedArchitecture GeneratedRegion where",
            "  regionOf := generatedRegion",
            f"  entryRegion := GeneratedRegion.{region_index[entry_region]}",
            "  declared := generatedDeclaredEntry",
            "  wrapped := generatedWrappedArtifact",
            "  discovered := generatedDiscoveredEntry",
            "  governed := generatedGovernedEntry",
            "  discovered_declared := by",
            "    intro m hg hd",
            "    revert hg hd",
            "    cases m <;> decide",
            "  outer := by",
            "    intro m h",
            "    revert h",
            "    cases m <;> decide",
            "  owned := by",
            "    intro m h",
            "    revert h",
            "    cases m <;> decide",
            "",
            "def generatedScopes : ScopeInventory generatedArchitecture GeneratedScope where",
            "  scopeOf := generatedScopeOf",
            "  expectedOf := generatedExpectedScopeOf",
            "  assigned := generatedAssignedScope",
            "  conforms := by",
            "    intro m h",
            "    revert h",
            "    cases m <;> decide",
            "",
            "def generatedPathScopes : PathScopeInventory GeneratedScope where",
            "  Path := GeneratedPath",
            "  scopeOf := generatedPathScopeOf",
            "  expectedOf := generatedPathExpectedScopeOf",
            "  ambiguous := generatedPathAmbiguous",
            "  unambiguous := by",
            "    intro p h",
            "    revert h",
            "    cases p <;> decide",
            "  conforms := by",
            "    intro p",
            "    cases p <;> decide",
            "",
            "def generatedBoundaryConcerns : BoundaryConcernInventory generatedArchitecture where",
            "  argv := generatedConcernArgv",
            "  environment := generatedConcernEnvironment",
            "  exitCode := generatedConcernExitCode",
            "  terminalIO := generatedConcernTerminalIO",
            "  entrypointOnly := generatedEntrypointConcern",
            "  outer := by",
            "    intro m h",
            "    revert h",
            "    cases m <;> decide",
            "  entrypointOnly_outer := by",
            "    intro m h",
            "    revert h",
            "    cases m <;> decide",
            "",
            "def generatedWrappers : WrapperInventory generatedArchitecture where",
            "  operations := generatedWrapperOp",
            "  declaredCommands := generatedWrapperDeclared",
            "  outer := by",
            "    intro k m h",
            "    revert h",
            "    cases k <;> cases m <;> decide",
            "  subprocess_declared := by",
            "    intro m h",
            "    revert h",
            "    cases m <;> decide",
            "",
            "def generatedReviews : ReviewInventory generatedArchitecture where",
            "  state := generatedReviewState",
            "  disjoint := by",
            "    intro m hp ha",
            "    revert hp ha",
            "    cases m <;> decide",
            "",
            "theorem generated_core_cannot_reach_outer {a b : GeneratedModule}",
            "    (ha : generatedCore a) (hb : ¬ generatedCore b) :",
            "    ¬ Path generatedDep a b :=",
            "  core_cannot_reach_outer generatedArchitecture ha hb",
            "",
            "theorem generated_path_allowed {a b : GeneratedModule}",
            "    (h : Path generatedDep a b) :",
            "    generatedEdgePolicy.allowed (generatedRegion b) (generatedRegion a) :=",
            "  path_allowed generatedPolicyArchitecture h",
            "",
        ]
    )
    return "\n".join(lines)


def write_instance(facts, policy, path, accepted_review_sources=()):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(generate(facts, policy, accepted_review_sources))
