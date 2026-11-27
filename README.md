# Software Architecture Pattern Research Notes

## Scope

These notes compare **Clean Architecture**, **Hexagonal Architecture (Ports and Adapters)**, and **Onion Architecture**, then survey adjacent patterns with the same design philosophy. Primary sources are used where available.

## Bottom line

These three are variants of one family: **inside-out, dependency-inversion architectures**. They keep business knowledge independent of UI, databases, frameworks, and other external technology.

Robert C. Martin explicitly lists Hexagonal and Onion among the architectures he integrated into Clean Architecture and notes that they "all have the same objective" and are "very similar" despite differing details. Source: [The Clean Architecture](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html).

The practical differences are mostly **emphasis and vocabulary**:

- **Hexagonal**: boundary-and-interaction view—ports and adapters around an application.
- **Onion**: core-and-layering view—an independent object model protected by inward coupling.
- **Clean**: dependency-rule-and-policy view—concentric rings organized by business policy level.

## What they share

1. **Dependencies point toward the business core.**
   - Hexagonal: the application communicates through ports; external technology stays outside.
   - Onion: "all coupling is toward the center."
   - Clean: "source code dependencies can only point inwards."

2. **Inners define contracts; outers implement them.**
   Interfaces, ports, and abstractions belong near the core. Controllers, repository implementations, database code, message clients, and test harnesses live at the edge.

3. **Dependency inversion makes inward dependencies possible.**
   Runtime control may flow outward—for example, a use case calls a repository—but the interface is owned by the core, so the *source-code dependency* still points inward.

4. **The core runs without infrastructure.**
   Business behavior can be tested with a test driver and in-memory substitutes instead of a real UI, web server, or database.

5. **UI and persistence are replaceable details.**
   A CLI, web UI, batch job, or test harness can drive the same application; SQL, files, or an in-memory store can implement the same port.

6. **Layer counts are schematic.**
   The hexagon's six sides and Clean's four circles are diagrams, not mandatory layer counts.

## Boundary surfaces

An executable is an **outer boundary surface**, not an adapter implementation. `external/cli/` owns argv parsing, environment access, process exit codes, and terminal I/O. Those concerns never move inward: a CLI wrapper parses input, composes concrete adapters, and calls a core use case.

```text
external/cli/*       argv, env, exit status, composition
        ↓
adapters/*           files, subprocesses, JSON, language toolchains
        ↓
architecture_core/* facts, policy, rules, workflows behind ports
```

If an adapter imports `argparse`, reads `sys.argv`, or owns process exit behavior, that is evidence of inverted dependency direction. Tests, examples, fixtures, generated code, and vendor code are **scopes**, not architectural layers. `external` means unowned dependency or outside system, not a peer layer for owned code.

The Lean spec encodes this as `BoundaryConcern`, `BoundarySurface`, `EntrypointBoundary`, `surface_unreachable_from_core`, and `adapter_not_cli_concern`.

## Comparison

| Aspect | Hexagonal Architecture | Onion Architecture | Clean Architecture |
|---|---|---|---|
| Origin | Alistair Cockburn, 2005 ([original article](https://alistair.cockburn.us/hexagonal-architecture)) | Jeffrey Palermo, 2008 ([part 1](https://jeffreypalermo.com/2008/07/the-onion-architecture-part-1)) | Robert C. Martin, 2012 ([article](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)) |
| Main perspective | The application as a component surrounded by interchangeable external actors | Concentric layers protecting an independent domain model | Concentric rings organized by policy level and the dependency rule |
| Center | "The application"; internal layering is deliberately not prescribed | An independent object model/domain model representing the business | **Entities**: enterprise-wide business rules, surrounded by application-specific use cases |
| Boundary vocabulary | **Ports** are purposeful conversations; **adapters** translate technologies | Inner layers define **interfaces**; outer layers implement them | Input/output **ports**, controllers, presenters, gateways, and interface adapters |
| Direction distinction | Explicitly distinguishes **driving ports**—who calls the application—and **driven ports**—what the application calls ([Cockburn's 2023 slides](https://alistaircockburn.com/Hexagonal%20Budapest%2023-05-18.pdf)) | Emphasizes repository interfaces and dependency injection at the core boundary | Emphasizes the universal inward dependency rule and simple data structures crossing boundaries |
| Distinctive detail | Rejects a single "top UI, bottom database" stack; all external actors are treated symmetrically | Formulated for long-lived enterprise applications and originally biased toward object-oriented design | Separates enterprise-wide entities from application-specific use cases and forbids inner code from naming outer code |

### Onion's original tenets

Palermo's 2008 summary:

- The application is built around an independent object model.
- Inner layers define interfaces; outer layers implement interfaces.
- Direction of coupling is toward the center.
- All application core code can be compiled and run separately from infrastructure.

Source: [Onion Architecture, part 3](https://jeffreypalermo.com/2008/08/the-onion-architecture-part-3) and [part 4](https://jeffreypalermo.com/2013/08/onion-architecture-part-4-after-four-years).

### Clean's four example rings

1. **Entities** — enterprise-wide business rules.
2. **Use Cases** — application-specific business rules.
3. **Interface Adapters** — controllers, presenters, gateways, and format conversion.
4. **Frameworks and Drivers** — databases, web frameworks, tools, and glue code.

The rings are schematic; more or fewer may be appropriate. The dependency rule always applies.

## Rough conceptual mapping

These are analogies, not exact equivalences:

| Concern | Hexagonal | Onion | Clean |
|---|---|---|---|
| Pure business logic | Application core | Domain model at the center | Entities |
| Application workflow | Application core | Application/domain services around the model | Use cases |
| Incoming boundary | Driving port | Interface consumed by UI/controllers | Input port/controller boundary |
| Outgoing boundary | Driven port | Repository or gateway interface | Output port/gateway interface |
| Technology implementations | Adapters | UI and infrastructure implementations | Interface adapters plus frameworks/drivers |

Hexagonal intentionally says less about internal application layering than Onion or Clean do.

## Related architectures and patterns

| Approach | Shared philosophy | Distinctive twist |
|---|---|---|
| **Domain-Driven Design's layered architecture** | Evans says to isolate the domain model from UI, infrastructure, and non-business application logic; he explicitly notes that Hexagonal can serve the same purpose ([DDD Reference](https://www.domainlanguage.com/wp-content/uploads/2016/05/DDD_Reference_2015-03.pdf)). | DDD is primarily about modeling the business—ubiquitous language, bounded contexts, aggregates—not just dependency direction. |
| **EBI / ECB / BCE** — Entity, Boundary, Interactor/Control | Separates domain entities, use-case behavior, and system boundaries. Introduced by Ivar Jacobson in 1992 ([overview with source quotations](https://herbertograca.com/2017/08/24/ebi-architecture); [original book](https://www.ivarjacobson.com/publications/books/object-oriented-software-engineering-book)). | Classifies objects by role: what they are, how the outside world reaches them, and what a use case orchestrates. |
| **DCI** — Data, Context, Interaction | Separates relatively stable domain data from use-case behavior; contexts bind objects to roles at runtime ([Reenskaug and Coplien](https://www.artima.com/articles/the-dci-architecture-a-new-vision-of-object-oriented-programming); [DCI overview](https://dci.github.io/)). | Keeps domain objects simple and places use-case algorithms in roles and contexts. Its focus is making user actions legible in code. |
| **Screaming Architecture** | Top-level structure should reveal the business and use cases, not frameworks; frameworks and databases are deferrable details ([Martin](https://blog.cleancoder.com/uncle-bob/2011/09/30/Screaming-Architecture.html)). | A structural heuristic rather than a complete layering model. |
| **Functional Core, Imperative Shell** | Pure decision logic lives in the core; external interaction lives in a thin shell. The core is "heavy on paths, light on dependencies" ([Boundaries talk](https://www.destroyallsoftware.com/talks/boundaries), [transcript](https://bparanj.blogspot.com/2016/10/ruby-conf-2012-boundaries-by-gary.html)). | The dividing line is purity versus effects, not business layers. Values cross the boundary; the shell handles databases, networks, clocks, and UI. |
| **Component + Strategy / Configurable Receiver** | Define a component boundary, declare what it provides and requires, and configure implementations externally ([Cockburn](https://alistaircockburn.com/Component%20plus%20strategy.pdf)). | Applies at nested subsystem boundaries, not only at an application's technology boundary. Hexagonal is a special case. |
| **VIPER** | Explicitly described as Clean Architecture applied to iOS. Interactors contain use-case logic independent of UI; entities and framework objects stay behind boundaries ([Gilbert and Stoll](https://www.objc.io/issues/13-architecture/viper)). | Platform-specific roles: View, Interactor, Presenter, Entity, Routing. |

## Adjacent but not equivalent

- **MVC, MVP, MVVM**: presentation patterns. They can occupy the outer layer, but do not by themselves protect the domain from infrastructure.
- **CQRS and event sourcing**: change how state is written, read, and persisted. Orthogonal to dependency direction; commonly combined with Clean or Hexagonal.
- **Microservices**: a deployment and team-boundary style. Each service may use any internal architecture.
- **Vertical-slice architecture**: organizes code by feature rather than technical layer. Compatible with clean boundaries, but not itself an inward-dependency rule.
- **Classic layered architecture**: similar vocabulary, but dependencies often point downward toward data access. It shares this family's philosophy only when dependencies are inverted.

## Practical synthesis

These patterns are complementary lenses rather than mutually exclusive choices:

- **DDD** tells you what belongs in the domain model.
- **Clean/Onion** tells you how dependencies should be directed.
- **Hexagonal** gives vocabulary for boundaries and plug-in actors.
- **EBI/DCI** help organize use-case behavior.
- **Functional core/imperative shell** provides a testing and side-effect boundary.
- **MVC/MVVM/VIPER** organizes the delivery mechanism at the edge.

A service can therefore have a DDD domain model, Clean-style use cases, Hexagonal ports, MVC at the web edge, and a mostly functional core without contradiction.

## Formal Lean spec

`Architecture.lean` formalizes the common philosophy in Lean 4. The spec models a system as:

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

This verifies the **formal model**. The adapters in `adapters/` bridge real source code to that model: extractors emit `Module` and `dep` facts, and the checker enforces the same core-closure and acyclicity rules in decidable form.

Toolchain: Lean 4.36.0, pinned in `lean-toolchain`.

Verify with:

```sh
source "$HOME/.elan/env"
lake build
```

## Extractors and checker

`external/cli/extract_*.py` are CLI entrypoints. They call the extractor libraries in `adapters/*_extractor.py`, which scan a project root and emit JSON facts:

- `modules`: `{name, path, package?}` entries.
- `dependencies`: `{from, to, kind, source, line}` entries.

`external/cli/check_architecture.py` reads facts plus architecture configuration from `architecture.toml` (`--config`) or a JSON policy file (`--policy`). It reports:

- `core_outward`: a core module depends on a non-core module.
- `forbidden_import`: a core module imports a forbidden target.
- `edge_not_allowed`: a source region has no permission for the target region.
- `cycle`: a module dependency cycle.

Layer patterns use shell-style `fnmatch`; layers are sorted by `priority` and the first matching layer wins. `default_layer` catches dependencies with no matching layer; it is an unowned fallback, not an owned layer. Layers with `core = true` correspond to `Core` in the Lean model. `tests/fixtures/policy.json` remains an example JSON policy covering Rust, Go, and TypeScript module names.
`architecture.toml` separates three concepts: `[layers.*]` defines inward dependency rings, `[scopes.*]` identifies test/example/fixture/generated/vendor contexts, and `[[executables]]` declares CLI surfaces with their owning layer. `ports` and `core` are core; `platform` covers language runtime primitives; `entrypoints`, `adapters`, and `infrastructure` are outer rings. Ports are contracts and boundary data owned by core.

Usage:

```sh
python3 external/cli/extract_rust.py --root /path/to/project --out rust-facts.json
cargo run --manifest-path adapters/rust-extractor/Cargo.toml -- --root /path/to/project --out rust-native-facts.json
python3 external/cli/extract_go.py --root /path/to/project --out go-facts.json
python3 external/cli/extract_typescript.py --root /path/to/project --out ts-facts.json
python3 external/cli/extract_python.py --root /path/to/project --out py-facts.json
go run ./adapters/go-extractor/main.go --root /path/to/project --out go-native-facts.json
npm install
node adapters/extract_typescript_native.mjs --root /path/to/project --out ts-native-facts.json
python3 external/cli/check_architecture.py rust-facts.json --config architecture.toml
python3 external/cli/check_architecture.py rust-facts.json --policy tests/fixtures/policy.json
python3 external/cli/check_self.py
```

The Python extractor libraries are dependency-free. `adapters/python_extractor.py` uses the standard-library `ast` parser. `rust-extractor` uses `cargo metadata` plus `syn`, `go-extractor` uses `go list -json` plus `go/parser`, and `adapters/extract_typescript_native.mjs` uses the TypeScript compiler API. Prefer native extractors when their toolchains are available in CI.
Core logic lives in `architecture_core/`: pure fact types, policy matching, checker rules, ports, and use cases. `adapters/` contains concrete mechanisms that translate source syntax into facts and perform file/process I/O; `adapters/runtime.py` composes those mechanisms behind core ports. `external/cli/` contains executable surfaces only. Dependencies point inward: entrypoints -> adapters -> core; core has no CLI, subprocess, JSON-I/O, or filesystem dependencies.

Extraction is fail-closed: unsupported constructs are recorded in an `unparsed` array, and the checker reports them as `unparsed_source` violations. CI therefore cannot silently pass on source code the scanner did not understand.

Dogfooding: `python3 external/cli/check_self.py` parses CLI arguments, builds the runtime adapter, and calls the self-check use case. The use case asks ports for config, facts, and checking; `adapters/runtime.py` performs extraction, merging, and file I/O behind those ports. Fixtures under `tests/fixtures/` are excluded because they deliberately contain violations. The check needs Python, Rust, and Go toolchains; the TypeScript source is scanned by the Python scanner.
Dogfood configuration and policy live in `architecture.toml` at the repo root:

```toml
version = 1
default_layer = "external"
default_scope = "external"

[paths]
core_root = "architecture_core"
adapters_root = "adapters"
entrypoints_root = "external/cli"

[[executables]]
name = "check_self"
path = "external/cli/check_self.py"
owner = "entrypoints"

[layers.core]
priority = 20
core = true
patterns = ["architecture_core.*"]
allowed = ["ports", "core", "platform"]
```

CLI flags override path values. Layer patterns and allowed edges are independent of folder names, but executable surfaces are declared explicitly in `[[executables]]`.

Limits:

- Python extractors are static source scanners; native extractors use language toolchains. Reflection, generated code, and runtime dependency injection remain out of scope.
- `adapters/python_extractor.py` handles absolute and relative imports, `__init__.py` packages, `src/` layouts, and literal `importlib`/`__import__` calls. Relative dynamic imports are resolved against `package=` or the current package; parse errors, non-literal or unresolved dynamic imports, and `eval`/`exec` are reported as unparsed.
- Rust `use` items are resolved to the nearest known local module; `pub use`, `pub(crate) use`, `pub(super) use`, `pub(in path) use`, and `extern crate` are included. Unrecognized visibility forms are reported as unparsed, as are `include!`, `#[path]`, and `macro_rules!`. The native extractor parses Rust ASTs with `syn`, reads the package name from `cargo metadata`, and reports workspace roots as unparsed instead of attributing all members to the first package.
- The Python Go scanner parses import declarations from source. `go-extractor` uses `go list -json` plus `go/parser` for package paths and import positions. Build-tagged and unparseable files are reported as unparsed.
- The Python TypeScript scanner handles single-line static imports/exports, `require()`, and `import()` including import attributes across `.ts`, `.tsx`, `.mts`, `.cts`, `.mjs`, and `.cjs`; multi-line `from` clauses and non-literal dynamic dependencies are reported as unparsed.
- `adapters/extract_typescript_native.mjs` parses TypeScript ASTs, honors `tsconfig.json`, resolves relative imports, and covers multi-line imports, type-only imports, re-exports, `import type`, dynamic imports with import attributes, and non-literal dynamic dependencies. Parse errors, unresolved relative specifiers, and unsupported extra dynamic arguments are reported as unparsed.
- Python scanners remain available when language toolchains are not installed; Python extraction needs only Python 3, while the other native extractors require Rust, Go 1.22+, and TypeScript/Node toolchains respectively.

The fixtures under `tests/fixtures/` contain deliberate violations and are useful for smoke-testing the pipeline.
