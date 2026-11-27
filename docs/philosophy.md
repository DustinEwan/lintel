# Architecture philosophy notes

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

An executable is an **outer boundary surface**, not an adapter implementation. `lintel/cli/` owns argv parsing, environment access, process exit codes, and terminal I/O. Those concerns never move inward: a CLI wrapper parses input, composes concrete adapters, and calls a core use case.

```text
lintel/cli/*         argv, env, exit status, composition
        ↓
lintel/adapters/*    files, subprocesses, JSON, language toolchains
        ↓
lintel/core/*        facts, policy, rules, workflows behind ports
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
