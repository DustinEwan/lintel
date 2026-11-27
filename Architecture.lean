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
