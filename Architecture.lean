/-!
# Formal architecture spec

This spec formalizes the common philosophy behind Clean, Hexagonal, Onion,
and related approaches: stable policy is protected from volatile mechanisms.

The model deliberately avoids a single privileged "core module" and avoids
rank-based isolation. `Core` is a set of modules closed under dependencies.
That supports multiple core modules and prevents same-rank outer modules from
being reachable from the core.
-/

universe u v w

/-- Predicate type used for the core membership set. -/
abbrev Set (α : Type u) := α → Prop

/-- A source-code dependency `a -> b`: module `a` names or requires module `b`. -/
structure Architecture where
  Module : Type u
  dep : Module → Module → Prop
  Core : Set Module
  core_closed : ∀ {a b : Module}, Core a → dep a b → Core b

/-- Transitive closure of a dependency relation. -/
inductive Path {α : Type u} (r : α → α → Prop) : α → α → Prop where
  | step {a b : α} : r a b → Path r a b
  | trans {a b c : α} : Path r a b → r b c → Path r a c

/-- A dependency relation is acyclic when no module reaches itself. -/
def Acyclic {α : Type u} (r : α → α → Prop) : Prop :=
  ∀ a : α, ¬ Path r a a

/-- Every path starting in the core stays in the core. -/
theorem core_closed_path (A : Architecture) {a b : A.Module}
    (ha : A.Core a) (h : Path A.dep a b) : A.Core b := by
  induction h with
  | step hdep =>
      exact A.core_closed ha hdep
  | trans hp hd ih =>
      exact A.core_closed ih hd

/-- No core module can transitively reach an outer module. -/
theorem core_cannot_reach_outer (A : Architecture) {a b : A.Module}
    (ha : A.Core a) (hb : ¬ A.Core b) : ¬ Path A.dep a b := by
  intro h
  exact hb (core_closed_path A ha h)

/-- A purpose boundary owned by the core. -/
structure Port (A : Architecture) where
  contract : A.Module
  owned_by_core : A.Core contract

/-- An outer adapter implements a core-owned port. -/
structure Adapter (A : Architecture) (p : Port A) where
  module : A.Module
  outer : ¬ A.Core module
  implements : A.dep module p.contract

/-- No core module can reach an adapter. -/
theorem adapter_unreachable_from_core (A : Architecture) (p : Port A)
    (adapter : Adapter A p) {c : A.Module} (hc : A.Core c) :
    ¬ Path A.dep c adapter.module :=
  core_cannot_reach_outer A hc adapter.outer

/-- An inner architecture embedded as modules of an outer architecture. -/
structure NestedArchitecture where
  outer : Architecture
  inner : Architecture
  embed : inner.Module → outer.Module
  embed_core : ∀ m : inner.Module, inner.Core m → outer.Core (embed m)
  embed_dep : ∀ {a b : inner.Module}, inner.dep a b → outer.dep (embed a) (embed b)

/-- A direct inner-core dependency maps into the outer core. -/
theorem nested_core_image_closed (N : NestedArchitecture) {a b : N.inner.Module}
    (ha : N.inner.Core a) (h : N.inner.dep a b) : N.outer.Core (N.embed b) :=
  N.embed_core b (N.inner.core_closed ha h)

/-- A path from an inner core module maps into the outer core. -/
theorem nested_core_path_stays_core (N : NestedArchitecture) {a b : N.inner.Module}
    (ha : N.inner.Core a) (h : Path N.inner.dep a b) : N.outer.Core (N.embed b) := by
  induction h with
  | step hdep =>
      exact nested_core_image_closed N ha hdep
  | trans hp hd ih =>
      exact N.outer.core_closed ih (N.embed_dep hd)

/-- A path from an inner core module cannot land outside the outer core. -/
theorem nested_core_cannot_reach_outer (N : NestedArchitecture) {a b : N.inner.Module}
    (ha : N.inner.Core a) (hout : ¬ N.outer.Core (N.embed b)) :
    ¬ Path N.inner.dep a b := by
  intro h
  exact hout (nested_core_path_stays_core N ha h)

/-- Inner dependency paths embed as outer dependency paths. -/
theorem embedded_path (N : NestedArchitecture) {a b : N.inner.Module}
    (h : Path N.inner.dep a b) : Path N.outer.dep (N.embed a) (N.embed b) := by
  induction h with
  | step hdep =>
      exact Path.step (N.embed_dep hdep)
  | trans hp hd ih =>
      exact Path.trans ih (N.embed_dep hd)

/-- Runtime call from core to an outer adapter through a core-owned port. -/
structure InvertedCall (A : Architecture) (p : Port A) (adapter : Adapter A p) where
  caller : A.Module
  core_caller : A.Core caller
  calls_through_port : A.dep caller p.contract

/-- An inverted call does not create a source dependency from core to adapter. -/
theorem inverted_call_avoids_adapter (A : Architecture) (p : Port A)
    (adapter : Adapter A p) (call : InvertedCall A p adapter) :
    ¬ A.dep call.caller adapter.module := by
  intro hdep
  exact adapter.outer (A.core_closed call.core_caller hdep)

/-- A weak order for layers outside the core. -/
structure RegionOrder (ρ : Type u) where
  le : ρ → ρ → Prop
  refl : ∀ r : ρ, le r r
  trans : ∀ {r s t : ρ}, le r s → le s t → le r t

/-- A layered architecture with a core set and inward region dependencies. -/
structure LayeredArchitecture where
  Module : Type u
  Region : Type v
  dep : Module → Module → Prop
  Core : Set Module
  core_closed : ∀ {a b : Module}, Core a → dep a b → Core b
  region : Module → Region
  order : RegionOrder Region
  core_region : Region
  region_of_core : ∀ m : Module, Core m → region m = core_region
  inward_region : ∀ {a b : Module}, dep a b → order.le (region b) (region a)

/-- Forget the region structure and view a layered architecture as an architecture. -/
def LayeredArchitecture.arch (A : LayeredArchitecture) : Architecture :=
  { Module := A.Module
    dep := A.dep
    Core := A.Core
    core_closed := A.core_closed }

/-- Every dependency path is non-outward in the region order. -/
theorem region_path_non_outward (A : LayeredArchitecture) {a b : A.Module}
    (h : Path A.dep a b) : A.order.le (A.region b) (A.region a) := by
  induction h with
  | step hdep =>
      exact A.inward_region hdep
  | trans hp hd ih =>
      exact A.order.trans (A.inward_region hd) ih

/-- A dependency path from the core remains in the core's region. -/
theorem core_region_path (A : LayeredArchitecture) {a b : A.Module}
    (ha : A.Core a) (h : Path A.dep a b) : A.region b = A.core_region := by
  have hb : A.Core b := core_closed_path A.arch ha h
  exact A.region_of_core b hb

/-- A transitive policy describing which region edges are allowed. -/
structure EdgePolicy (ρ : Type u) where
  allowed : ρ → ρ → Prop
  allowed_refl : ∀ r : ρ, allowed r r
  allowed_trans : ∀ {r s t : ρ}, allowed r s → allowed s t → allowed r t

/-- An architecture whose dependency edges obey a region policy. -/
structure PolicyArchitecture where
  Module : Type u
  Region : Type v
  dep : Module → Module → Prop
  region : Module → Region
  policy : EdgePolicy Region
  dep_allowed : ∀ {a b : Module}, dep a b → policy.allowed (region b) (region a)

/-- Every dependency path obeys the transitive edge policy. -/
theorem path_allowed (A : PolicyArchitecture) {a b : A.Module}
    (h : Path A.dep a b) : A.policy.allowed (A.region b) (A.region a) := by
  induction h with
  | step hdep =>
      exact A.dep_allowed hdep
  | trans hp hd ih =>
      exact A.policy.allowed_trans (A.dep_allowed hd) ih

/-- A strict order for regions with no self-dependencies. -/
structure StrictOrder (ρ : Type u) where
  lt : ρ → ρ → Prop
  irrefl : ∀ r : ρ, ¬ lt r r
  trans : ∀ {r s t : ρ}, lt r s → lt s t → lt r t

/-- A layered architecture where every direct edge is strictly inward. -/
structure StrictLayeredArchitecture where
  Module : Type u
  Region : Type v
  dep : Module → Module → Prop
  region : Module → Region
  order : StrictOrder Region
  inward_strict : ∀ {a b : Module}, dep a b → order.lt (region b) (region a)

/-- Every dependency path is strictly inward. -/
theorem strict_region_path (A : StrictLayeredArchitecture) {a b : A.Module}
    (h : Path A.dep a b) : A.order.lt (A.region b) (A.region a) := by
  induction h with
  | step hdep =>
      exact A.inward_strict hdep
  | trans hp hd ih =>
      exact A.order.trans (A.inward_strict hd) ih

/-- A strictly layered dependency graph is acyclic. -/
theorem strict_acyclic (A : StrictLayeredArchitecture) : Acyclic A.dep := by
  intro a h
  exact A.order.irrefl (A.region a) (strict_region_path A h)

/-- A capability describes the operations a core may require from an adapter. -/
structure Capability where
  Op : Type u
  Result : Op → Type v

/-- One implementation of a capability. -/
structure Implementation (C : Capability) where
  run : (op : C.Op) → C.Result op

/-- A core program is parameterized by an implementation of its required capability. -/
def Program (C : Capability) (R : Type w) := Implementation C → R

/-- Two implementations are equivalent when they agree on every operation. -/
def equivalent {C : Capability} (i j : Implementation C) : Prop :=
  ∀ op : C.Op, i.run op = j.run op

/-- Equivalent implementations can be substituted into any core program. -/
theorem substitution {C : Capability} {R : Type w} (program : Program C R)
    {i j : Implementation C} (h : equivalent i j) : program i = program j := by
  have hij : i = j := by
    cases i with
    | mk ri =>
      cases j with
      | mk rj =>
        simp [equivalent] at h
        have hfun : ri = rj := by
          funext op
          exact h op
        cases hfun
        rfl
  exact congrArg program hij

/-- A port that also declares the capability provided by its adapters. -/
structure CapabilityPort (A : Architecture) (C : Capability) extends Port A

/-- An outer adapter with an implementation of the port's capability. -/
structure CapabilityAdapter (A : Architecture) (C : Capability)
    (p : CapabilityPort A C) extends Adapter A p.toPort where
  implementation : Implementation C

/-- Equivalent capability adapters are substitutable in a core program. -/
theorem capability_adapter_substitution {A : Architecture} {C : Capability}
    {p : CapabilityPort A C} {R : Type w} (program : Program C R)
    (a b : CapabilityAdapter A C p)
    (h : equivalent a.implementation b.implementation) :
    program a.implementation = program b.implementation :=
  substitution program h

/-- If a mock is equivalent to production, a passing core test transfers. -/
theorem test_transfers {C : Capability} {R : Type w} (program : Program C R)
    (expected : R) (mock production : Implementation C)
    (h : equivalent mock production)
    (test : program mock = expected) : program production = expected := by
  rw [← substitution program h, test]


/-- A language of values allowed to cross a boundary. -/
structure BoundaryDataLanguage where
  Allowed : Type u → Prop
  Forbidden : Type u → Prop
  disjoint : ∀ {α : Type u}, Allowed α → Forbidden α → False
  unit : Allowed PUnit
  prod : ∀ {α β : Type u}, Allowed α → Allowed β → Allowed (α × β)
  sum : ∀ {α β : Type u}, Allowed α → Allowed β → Allowed (α ⊕ β)

/-- A capability whose operation and result types are boundary data. -/
structure TypedCapability (L : BoundaryDataLanguage) where
  Op : Type u
  Result : Op → Type u
  op_allowed : L.Allowed Op
  result_allowed : ∀ op, L.Allowed (Result op)

/-- Forget boundary typing and view a typed capability as a capability. -/
def TypedCapability.toCapability {L : BoundaryDataLanguage}
    (C : TypedCapability L) : Capability :=
  { Op := C.Op
    Result := C.Result }

/-- Forbidden data cannot be used as a typed capability operation. -/
theorem typed_op_not_forbidden {L : BoundaryDataLanguage} (C : TypedCapability L) :
    ¬ L.Forbidden C.Op := by
  intro h
  exact L.disjoint C.op_allowed h

/-- Forbidden data cannot be returned by a typed capability operation. -/
theorem typed_result_not_forbidden {L : BoundaryDataLanguage}
    (C : TypedCapability L) (op : C.Op) : ¬ L.Forbidden (C.Result op) := by
  intro h
  exact L.disjoint (C.result_allowed op) h

/-- Allowed values compose into allowed products. -/
theorem allowed_pair {L : BoundaryDataLanguage} {α β : Type u}
    (ha : L.Allowed α) (hb : L.Allowed β) : ¬ L.Forbidden (α × β) := by
  intro h
  exact L.disjoint (L.prod ha hb) h

/-- Allowed values compose into allowed sums. -/
theorem allowed_sum {L : BoundaryDataLanguage} {α β : Type u}
    (ha : L.Allowed α) (hb : L.Allowed β) : ¬ L.Forbidden (α ⊕ β) := by
  intro h
  exact L.disjoint (L.sum ha hb) h

/-- A core program whose result is boundary data cannot return forbidden data. -/
structure TypedProgram (L : BoundaryDataLanguage) (C : TypedCapability L) where
  Result : Type u
  result_allowed : L.Allowed Result
  run : Program C.toCapability Result

/-- A typed core program cannot return forbidden data. -/
theorem typed_program_result_not_forbidden {L : BoundaryDataLanguage}
    {C : TypedCapability L} (p : TypedProgram L C) : ¬ L.Forbidden p.Result := by
  intro h
  exact L.disjoint p.result_allowed h

/-- A port that carries only boundary data. -/
structure TypedCapabilityPort (A : Architecture) (L : BoundaryDataLanguage)
    (C : TypedCapability L) extends Port A

/-- An outer adapter implementing a typed boundary-data port. -/
structure TypedCapabilityAdapter (A : Architecture) (L : BoundaryDataLanguage)
    (C : TypedCapability L) (p : TypedCapabilityPort A L C)
    extends Adapter A p.toPort where
  implementation : Implementation C.toCapability

/-- Equivalent typed adapters are substitutable. -/
theorem typed_capability_adapter_substitution {A : Architecture} {L : BoundaryDataLanguage}
    {C : TypedCapability L} {p : TypedCapabilityPort A L C} {R : Type w}
    (program : Program C.toCapability R) (a b : TypedCapabilityAdapter A L C p)
    (h : equivalent a.implementation b.implementation) :
    program a.implementation = program b.implementation :=
  substitution program h
/-- Volatile concerns that belong exclusively to a process entrypoint. -/
inductive BoundaryConcern where
  | argv
  | environment
  | exitCode
  | terminalIO

/-- An outer module that serves as the system boundary surface. -/
structure BoundarySurface (A : Architecture) where
  module : A.Module
  outer : ¬ A.Core module

/-- An entrypoint surface that owns boundary concerns only at that surface. -/
structure EntrypointBoundary (A : Architecture) where
  surface : BoundarySurface A
  owns : BoundaryConcern → Set A.Module
  surface_only : ∀ {c m}, owns c m → m = surface.module

/-- No core module can reach the entrypoint surface. -/
theorem surface_unreachable_from_core (A : Architecture) (entry : EntrypointBoundary A)
    {c : A.Module} (hc : A.Core c) : ¬ Path A.dep c entry.surface.module :=
  core_cannot_reach_outer A hc entry.surface.outer

/-- An adapter away from the entrypoint surface cannot own boundary concerns. -/
theorem adapter_not_cli_concern (A : Architecture) (p : Port A)
    (adapter : Adapter A p) (entry : EntrypointBoundary A)
    (hne : adapter.module ≠ entry.surface.module) (c : BoundaryConcern) :
    ¬ entry.owns c adapter.module := by
  intro h
  exact hne (entry.surface_only h)

/-- An architecture whose dependency graph is acyclic. -/
structure AcyclicArchitecture where
  arch : Architecture
  acyclic : Acyclic arch.dep

/-- A decreasing rank proves acyclicity. -/
theorem acyclic_of_rank {α : Type u} (r : α → α → Prop) (rank : α → Nat)
    (h : ∀ {a b : α}, r a b → rank b < rank a) : Acyclic r := by
  intro a hp
  have hrank : ∀ {a b : α}, Path r a b → rank b < rank a := by
    intro a b path
    induction path with
    | step hd => exact h hd
    | trans hp hd ih => exact Nat.lt_trans (h hd) ih
  exact Nat.lt_irrefl _ (hrank hp)

/-- A core use case may depend only on allowed target modules. -/
structure UseCaseBoundary (A : Architecture) where
  UseCase : Set A.Module
  AllowedTarget : Set A.Module
  pure : ∀ {a b : A.Module}, UseCase a → A.dep a b → AllowedTarget b

/-- Declared and discovered process entrypoints, with their owning region. -/
structure EntrypointInventory (A : Architecture) (ρ : Type v) where
  regionOf : A.Module → ρ
  entryRegion : ρ
  declared : Set A.Module
  wrapped : Set A.Module
  discovered : Set A.Module
  governed : Set A.Module
  discovered_declared : ∀ m : A.Module, governed m → discovered m →
    declared m ∨ wrapped m
  outer : ∀ m : A.Module, discovered m → ¬ A.Core m
  owned : ∀ m : A.Module, declared m → regionOf m = entryRegion

/-- Scope assignments and their expected conventions. -/
structure ScopeInventory (A : Architecture) (σ : Type v) where
  scopeOf : A.Module → σ
  expectedOf : A.Module → σ
  assigned : Set A.Module
  conforms : ∀ m : A.Module, assigned m → scopeOf m = expectedOf m

/-- Boundary concerns observed in source modules. -/
structure BoundaryConcernInventory (A : Architecture) where
  argv : Set A.Module
  environment : Set A.Module
  exitCode : Set A.Module
  terminalIO : Set A.Module
  entrypointOnly : Set A.Module
  outer : ∀ m : A.Module,
    argv m ∨ environment m ∨ exitCode m ∨ terminalIO m → ¬ A.Core m
  entrypointOnly_outer : ∀ m : A.Module, entrypointOnly m → ¬ A.Core m

/-- Kinds of operation an entrypoint wrapper may perform. -/
inductive WrapperOperationKind where
  | importOp
  | subprocess
  | policyConstruction
  | sourceWalk
  | parseSource
  deriving DecidableEq, Repr

/-- Operations observed in entrypoints and their declared command surface. -/
structure WrapperInventory (A : Architecture) where
  operations : WrapperOperationKind → Set A.Module
  declaredCommands : Set A.Module
  outer : ∀ (k : WrapperOperationKind) (m : A.Module),
    operations k m → ¬ A.Core m
  subprocess_declared : ∀ m : A.Module,
    operations WrapperOperationKind.subprocess m → declaredCommands m

/-- Review state for semantically ambiguous source facts. -/
inductive ReviewState where
  | pending
  | accepted
  deriving DecidableEq, Repr

/-- Flagged reviews cannot also be accepted. -/
structure ReviewInventory (A : Architecture) where
  state : ReviewState → Set A.Module
  disjoint : ∀ (m : A.Module), state ReviewState.pending m →
    state ReviewState.accepted m → False

/-- A layered architecture with a set of core regions instead of one. -/
structure MultiCoreLayeredArchitecture where
  Module : Type u
  Region : Type v
  dep : Module → Module → Prop
  Core : Set Module
  core_closed : ∀ {a b : Module}, Core a → dep a b → Core b
  region : Module → Region
  order : RegionOrder Region
  coreRegions : Set Region
  region_of_core : ∀ m : Module, Core m → coreRegions (region m)
  inward_region : ∀ {a b : Module}, dep a b → order.le (region b) (region a)

/-- A dependency path from a core module stays in a core region. -/
theorem multi_core_region_path (A : MultiCoreLayeredArchitecture) {a b : A.Module}
    (ha : A.Core a) (h : Path A.dep a b) : A.coreRegions (A.region b) := by
  have hb : A.Core b := core_closed_path
    { Module := A.Module
      dep := A.dep
      Core := A.Core
      core_closed := A.core_closed } ha h
  exact A.region_of_core b hb

/-!
## Concrete finite instance

A small graph demonstrates the abstract rules on decidable data.
-/

inductive DemoModule where
  | domain
  | application
  | postgresRepo
  | httpAdapter
  | cli

def demoDep : DemoModule → DemoModule → Prop
  | .application, .domain => True
  | .postgresRepo, .application => True
  | .httpAdapter, .application => True
  | .cli, .application => True
  | _, _ => False

def demoCore : Set DemoModule
  | .domain => True
  | .application => True
  | .postgresRepo => False
  | .httpAdapter => False
  | .cli => False

def demoArchitecture : Architecture :=
  { Module := DemoModule
    dep := demoDep
    Core := demoCore
    core_closed := by
      intro a b ha hdep
      cases a <;> cases b <;> simp [demoCore, demoDep] at * }

example : ¬ Path demoArchitecture.dep DemoModule.application DemoModule.postgresRepo := by
  exact core_cannot_reach_outer demoArchitecture
    (by simp [demoArchitecture, demoCore])
    (by simp [demoArchitecture, demoCore])

inductive DemoRegion where
  | domain
  | application
  | adapters
  deriving DecidableEq

def demoLt : DemoRegion → DemoRegion → Prop
  | .domain, .application => True
  | .domain, .adapters => True
  | .application, .adapters => True
  | _, _ => False

def demoStrict : StrictLayeredArchitecture :=
  { Module := DemoModule
    Region := DemoRegion
    dep := demoDep
    region := fun m => match m with
      | .domain => .domain
      | .application => .application
      | .postgresRepo => .adapters
      | .httpAdapter => .adapters
      | .cli => .adapters
    order :=
      { lt := demoLt
        irrefl := by
          intro r
          cases r <;> simp [demoLt]
        trans := by
          intro r s t h1 h2
          cases r <;> cases s <;> cases t <;> simp [demoLt] at * }
    inward_strict := by
      intro a b hdep
      cases a <;> cases b <;> simp [demoDep, demoLt] at * }


/-- The cli entrypoint is the sole owner of process boundary concerns. -/
def demoBoundary : EntrypointBoundary demoArchitecture where
  surface :=
    { module := DemoModule.cli
      outer := by simp [demoArchitecture, demoCore] }
  owns := fun _ m => m = DemoModule.cli
  surface_only := by
    intro c m h
    exact h

example : ¬ demoBoundary.owns BoundaryConcern.argv DemoModule.postgresRepo := by
  exact adapter_not_cli_concern demoArchitecture
    { contract := DemoModule.application
      owned_by_core := by simp [demoArchitecture, demoCore] }
    { module := DemoModule.postgresRepo
      outer := by simp [demoArchitecture, demoCore]
      implements := by simp [demoArchitecture, demoDep] }
    demoBoundary (by
      change DemoModule.postgresRepo ≠ DemoModule.cli
      intro h
      cases h) BoundaryConcern.argv
