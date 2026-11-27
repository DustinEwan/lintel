# Formal Lean spec

`lintel/Lintel.lean` formalizes the common philosophy in Lean 4. The spec models a system as:

- `Module`: a set of modules or components.
- `dep`: a source-code dependency relation.
- `Core : Set Module`: a predicate identifying core modules.
- `core_closed`: every dependency of a core module is also core.

The model deliberately avoids a unique core module or rank-based isolation. `Core` is a set, so multiple core modules are supported, and an outer module cannot become reachable from the core merely by sharing a rank or region.

Proven properties:

- `core_closed_path`: every transitive dependency path from the core remains in the core.
- `core_cannot_reach_outer`: no core module can transitively reach a non-core module.
- `adapter_unreachable_from_core`: no core module can reach an outer adapter.
- `region_path_non_outward`: dependency paths are non-outward in a layered region order.
- `core_region_path`: a dependency path from the core remains in the core's region.
- `substitution`: equivalent implementations of a core-owned capability can be exchanged without changing a core program's result.
- `path_allowed`: every dependency path obeys a transitive region-edge policy.
- `strict_region_path`: every dependency path in a strict layered architecture moves inward.
- `strict_acyclic`: a strictly layered dependency graph is acyclic.
- `capability_adapter_substitution`: equivalent adapters for the same capability port are substitutable.
- `nested_core_image_closed`: a direct inner-core dependency maps into the outer core.
- `nested_core_path_stays_core`: a path from an inner core module maps into the outer core.
- `nested_core_cannot_reach_outer`: an inner core path cannot land outside the outer core.
- `embedded_path`: inner dependency paths embed as outer dependency paths.
- `inverted_call_avoids_adapter`: runtime calls through a port do not create core-to-adapter source dependencies.
- `test_transfers`: a passing core test with a mock transfers to an equivalent production implementation.
- `typed_op_not_forbidden`: a typed capability's operation type cannot be forbidden data.
- `typed_result_not_forbidden`: a typed capability's result type cannot be forbidden data.
- `allowed_pair` and `allowed_sum`: allowed values stay allowed when composed into products or sums.
- `typed_program_result_not_forbidden`: a typed core program cannot return forbidden data.
- `typed_capability_adapter_substitution`: equivalent typed adapters are substitutable.
- Concrete `demoArchitecture`: an application module cannot reach a Postgres adapter, and `demo_acyclic` proves the example graph has no dependency cycle.

The spec also defines `Port`, `Adapter`, `CapabilityPort`, `CapabilityAdapter`, `RegionOrder`, `EdgePolicy`, `PolicyArchitecture`, `StrictLayeredArchitecture`, `NestedArchitecture`, `InvertedCall`, `Capability`, `BoundaryDataLanguage`, `TypedCapability`, `TypedProgram`, `TypedCapabilityPort`, and `TypedCapabilityAdapter` to connect the dependency model with boundary contracts, composition, dependency inversion, substitutability, and boundary-data typing.

`BoundaryDataLanguage` is an abstract parameter: a project defines `Allowed` as its DTO/value types and `Forbidden` as framework-owned types such as ORM rows, HTTP requests, or UI models, then supplies the disjointness proof. Typed capabilities, ports, and programs make that choice part of the contract rather than a convention.

Acyclicity is scoped to dependency graphs extracted below the package or project-reference level. Cargo rejects ordinary package dependency cycles and TypeScript project references reject reference cycles; the remaining practical gaps are module-level cycles inside a crate/project and dev/test-only edges.

This verifies the **formal model**. The adapters in `lintel/adapters/` bridge real source code to that model: extractors emit `Module` and `dep` facts, and the checker enforces the same rules in decidable form.

`generate-lean` instantiates every executable-fact category from the checker in the generated module: core and policy architecture, acyclicity, nested embedding, ports/adapters/inverted calls, multi-core layered regions, use-case purity, declared entrypoints, scope assignments, boundary concerns, wrapper operations, and semantic review state. `MultiCoreLayeredArchitecture` is used because the current policy has several core regions. The current policy also permits same-region edges and multiple core regions, so no strict layered instance is emitted. Typed capability structures and extraction/runtime semantics remain abstract or outside the generated instance.

For the trust boundary, build instructions, and CI coverage, see [README.md](../README.md). For durable limitations, see [docs/limitations.md](limitations.md).
