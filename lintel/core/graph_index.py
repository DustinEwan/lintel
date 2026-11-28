"""Derived query graph over :class:`lintel.core.model.FactSet`.

This module is not a second fact model. It builds keys, references, and
deterministic traversals from the canonical facts once per check so callers can
ask graph questions without rebuilding dictionaries or parser-specific loops.
"""

import hashlib
from collections.abc import Callable, Iterable
from typing import NamedTuple

from .model import (
    BoundaryConcernUse,
    CallEdge,
    CallSite,
    Dependency,
    FactSet,
    ImportBinding,
    SemanticReview,
    Symbol,
    UnresolvedCall,
    WrapperOperation,
)


class GraphNode(NamedTuple):
    """A derived graph node: stable identity, kind, and a canonical fact reference."""

    id: tuple[str, ...]
    kind: str
    value: object


class GraphEdge(NamedTuple):
    """A labeled edge with enough provenance to explain a finding."""

    id: tuple[str, ...]
    kind: str
    source_id: tuple[str, ...]
    target_id: tuple[str, ...]
    origin: str
    line: int
    detail: str


class GraphDiff(NamedTuple):
    """Node and edge identity differences between two graph views."""

    added_nodes: tuple[GraphNode, ...]
    removed_nodes: tuple[GraphNode, ...]
    added_edges: tuple[GraphEdge, ...]
    removed_edges: tuple[GraphEdge, ...]


class GraphView(NamedTuple):
    """A filtered projection of a graph."""

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]


_NODE_KINDS = frozenset(
    {
        "module",
        "symbol",
        "concern",
        "entrypoint",
        "wrapper",
        "external",
        "unparsed",
        "review",
        "unresolved",
    }
)


def _edge_id(
    kind: str,
    source: tuple[str, ...],
    target: tuple[str, ...],
    origin: str,
    line: int,
    detail: str,
) -> tuple[str, ...]:
    return (kind, *source, *target, origin or "", str(line), detail or "")


def _module_name_from_target(target: object) -> str:
    text = str(target or "").replace("\\", "/")
    head, separator, tail = text.rpartition("/")
    if "." in tail:
        tail = tail.rsplit(".", 1)[0]
    normalized = f"{head}{separator}{tail}" if separator else tail
    return normalized.replace("/", ".").replace("-", "_")


def _kinds(kinds: Iterable[str] | str | None) -> frozenset[str] | None:
    if kinds is None:
        return None
    if isinstance(kinds, str):
        return frozenset({kinds})
    return frozenset(kinds)


class GraphIndex:
    """Immutable derived graph and indexes over one ``FactSet``."""

    def __init__(self, facts: FactSet) -> None:
        self._facts = facts

        self._symbols = {symbol.key: symbol for symbol in facts.symbols}

        by_name: dict[tuple[str, str], list[Symbol]] = {}
        for symbol in facts.symbols:
            by_name.setdefault((symbol.module, symbol.name), []).append(symbol)
        self._symbols_by_name = {
            key: tuple(values) for key, values in by_name.items()
        }

        self._modules = {module.name for module in facts.modules}
        self._bindings: dict[tuple[str, str], tuple[str, str]] = {}
        for item in facts.import_bindings:
            target_module = item.target_module
            target_symbol = item.target_symbol
            candidate = f"{target_module}.{target_symbol}" if target_symbol else ""
            if candidate and candidate in self._modules:
                target_module, target_symbol = candidate, ""
            self._bindings[(item.module, item.local_name)] = (
                target_module,
                target_symbol,
            )

        self._concerns_by_symbol: dict[str, BoundaryConcernUse] = {}
        for concern in facts.concerns:
            candidates = [
                item
                for item in facts.symbols
                if item.source == concern.source
                and item.kind in {"function", "method"}
                and item.line <= concern.line <= item.end_line
            ]
            if not candidates:
                continue
            chosen = min(
                candidates, key=lambda item: (item.end_line - item.line, item.line)
            )
            self._concerns_by_symbol.setdefault(chosen.key, concern)

        self._call_edges, self._unresolved = self._resolve_calls()

        reverse_calls: dict[str, list[str]] = {}
        for edge in self._call_edges:
            reverse_calls.setdefault(edge.callee, []).append(edge.caller)
        self._reverse_calls = {
            key: tuple(callers) for key, callers in reverse_calls.items()
        }

        incoming: dict[str, list[Dependency]] = {}
        for dep in facts.dependencies:
            if (
                not dep.source_module
                or not dep.target_module
                or dep.source_module == dep.target_module
            ):
                continue
            incoming.setdefault(dep.target_module, []).append(dep)
        self._incoming = {
            key: tuple(sorted(values, key=self._dependency_order))
            for key, values in incoming.items()
        }

        self._outgoing: dict[str, set[str]] = {}
        for dep in facts.dependencies:
            self._outgoing.setdefault(dep.source_module, set()).add(dep.target_module)

        self._build_graph()

    @classmethod
    def from_facts(cls, facts: FactSet) -> "GraphIndex":
        return cls(facts)

    @staticmethod
    def _dependency_order(dep: Dependency) -> tuple[int, str, str]:
        return (dep.line, dep.source, dep.source_module)

    def _build_graph(self) -> None:
        nodes: dict[tuple[str, ...], GraphNode] = {}
        edges: dict[tuple[str, ...], GraphEdge] = {}

        def add_node(kind: str, parts: Iterable[object], value: object) -> tuple[str, ...]:
            node_id = (kind, *(str(part) for part in parts))
            nodes.setdefault(node_id, GraphNode(node_id, kind, value))
            return node_id

        def module_id(name: object) -> tuple[str, ...]:
            text = str(name)
            declared = next(
                (module for module in self._facts.modules if module.name == text), None
            )
            return add_node("module", (text,), declared if declared is not None else text)

        def symbol_id(key: str) -> tuple[str, ...]:
            return add_node("symbol", (key,), self._symbols.get(key, key))

        def external_id(name: object) -> tuple[str, ...]:
            return add_node("external", (str(name),), str(name))

        def add_edge(
            kind: str,
            source: tuple[str, ...],
            target: tuple[str, ...],
            origin: str = "",
            line: int = 0,
            detail: str = "",
        ) -> None:
            edge_id = _edge_id(kind, source, target, origin, line, detail)
            edges.setdefault(
                edge_id,
                GraphEdge(edge_id, kind, source, target, origin, line, detail),
            )

        def concern_id(concern: BoundaryConcernUse) -> tuple[str, ...]:
            return add_node(
                "concern",
                (
                    concern.module,
                    concern.concern,
                    concern.category,
                    concern.source,
                    concern.line,
                ),
                concern,
            )

        for module in self._facts.modules:
            module_id(module.name)
        for symbol in self._facts.symbols:
            symbol_id(symbol.key)

        for dep in self._facts.dependencies:
            add_edge(
                "depends_on",
                module_id(dep.source_module),
                module_id(dep.target_module),
                dep.source,
                dep.line,
                dep.kind,
            )

        for symbol in self._facts.symbols:
            add_edge(
                "defines",
                module_id(symbol.module),
                symbol_id(symbol.key),
                symbol.source,
                symbol.line,
                symbol.kind,
            )

        for concern in self._facts.concerns:
            add_edge(
                "has_concern",
                module_id(concern.module),
                concern_id(concern),
                concern.source,
                concern.line,
                concern.category,
            )
        for symbol_key, concern in self._concerns_by_symbol.items():
            add_edge(
                "marks",
                concern_id(concern),
                symbol_id(symbol_key),
                concern.source,
                concern.line,
                concern.concern,
            )

        for item in self._facts.import_bindings:
            source = module_id(item.module)
            target_module, target_symbol = self._bindings[
                (item.module, item.local_name)
            ]
            if target_symbol:
                candidates = self._symbols_by_name.get(
                    (target_module, target_symbol), ()
                )
                if candidates:
                    for candidate in candidates:
                        add_edge(
                            "binds",
                            source,
                            symbol_id(candidate.key),
                            item.source,
                            item.line,
                            item.local_name,
                        )
                else:
                    add_edge(
                        "binds",
                        source,
                        external_id(f"{target_module}.{target_symbol}"),
                        item.source,
                        item.line,
                        item.local_name,
                    )
            elif target_module in self._modules:
                add_edge(
                    "binds",
                    source,
                    module_id(target_module),
                    item.source,
                    item.line,
                    item.local_name,
                )
            else:
                add_edge(
                    "binds",
                    source,
                    external_id(target_module),
                    item.source,
                    item.line,
                    item.local_name,
                )

        for edge in self._call_edges:
            add_edge(
                "calls",
                symbol_id(edge.caller),
                symbol_id(edge.callee),
                edge.source,
                edge.line,
                edge.provenance,
            )

        for item in self._unresolved:
            unresolved_node = add_node(
                "unresolved",
                (item.caller, item.name, item.source, item.line, item.reason),
                item,
            )
            add_edge(
                "unresolved_call",
                symbol_id(item.caller),
                unresolved_node,
                item.source,
                item.line,
                item.reason,
            )

        for item in self._facts.entrypoints:
            entry_node = add_node(
                "entrypoint", (item.module, item.path, item.kind), item
            )
            add_edge(
                "has_entrypoint",
                module_id(item.module),
                entry_node,
                item.path,
                0,
                item.kind,
            )

        for item in self._facts.wrapper_operations:
            wrapper_node = add_node(
                "wrapper",
                (item.module, item.operation, item.target, item.source, item.line),
                item,
            )
            add_edge(
                "has_wrapper",
                module_id(item.module),
                wrapper_node,
                item.source,
                item.line,
                item.operation,
            )
            target_name = _module_name_from_target(item.target)
            target = (
                module_id(target_name)
                if target_name in self._modules
                else external_id(target_name)
            )
            add_edge(
                "invokes",
                wrapper_node,
                target,
                item.source,
                item.line,
                item.target,
            )

        for item in self._facts.unparsed:
            add_node("unparsed", (item.source, item.line, item.reason), item)

        for item in self._facts.reviews:
            review_node = add_node(
                "review", (item.module, item.source, item.line, item.reason), item
            )
            add_edge(
                "reviews",
                module_id(item.module),
                review_node,
                item.source,
                item.line,
                item.reason,
            )

        self._nodes_by_id = nodes
        self._nodes = tuple(nodes[key] for key in sorted(nodes))
        self._edges_by_id = edges
        self._edges = tuple(edges[key] for key in sorted(edges))
        self._out_edges: dict[tuple[str, ...], list[GraphEdge]] = {}
        self._in_edges: dict[tuple[str, ...], list[GraphEdge]] = {}
        for edge in self._edges:
            self._out_edges.setdefault(edge.source_id, []).append(edge)
            self._in_edges.setdefault(edge.target_id, []).append(edge)

    def _coerce_node(self, node: object) -> tuple[str, ...] | None:
        if isinstance(node, GraphNode):
            return node.id
        if isinstance(node, tuple):
            if node and node[0] in _NODE_KINDS:
                return tuple(str(part) for part in node)
            if len(node) == 1:
                return ("module", str(node[0]))
            return None
        value = str(node)
        for kind in ("module", "symbol", "external"):
            candidate = (kind, value)
            if candidate in self._nodes_by_id:
                return candidate
        return ("module", value)

    def nodes(self, kind: str | None = None) -> tuple[GraphNode, ...]:
        if kind is None:
            return self._nodes
        return tuple(node for node in self._nodes if node.kind == kind)

    def node(self, node: object) -> GraphNode | None:
        node_id = self._coerce_node(node)
        return None if node_id is None else self._nodes_by_id.get(node_id)

    def edges(self, kind: str | Iterable[str] | None = None) -> tuple[GraphEdge, ...]:
        selected = _kinds(kind)
        if selected is None:
            return self._edges
        return tuple(edge for edge in self._edges if edge.kind in selected)

    def out(
        self, node: object, kinds: str | Iterable[str] | None = None
    ) -> tuple[GraphEdge, ...]:
        node_id = self._coerce_node(node)
        selected = _kinds(kinds)
        if node_id is None:
            return ()
        return tuple(
            edge
            for edge in self._out_edges.get(node_id, ())
            if selected is None or edge.kind in selected
        )

    def incoming_edges(
        self, node: object, kinds: str | Iterable[str] | None = None
    ) -> tuple[GraphEdge, ...]:
        node_id = self._coerce_node(node)
        selected = _kinds(kinds)
        if node_id is None:
            return ()
        return tuple(
            edge
            for edge in self._in_edges.get(node_id, ())
            if selected is None or edge.kind in selected
        )

    def reachable(
        self,
        start: object,
        kinds: str | Iterable[str] | None = None,
        reverse: bool = False,
        predicate: Callable[[GraphNode], bool] | None = None,
    ) -> tuple[GraphNode, ...]:
        start_id = self._coerce_node(start)
        selected = _kinds(kinds)
        if start_id is None or start_id not in self._nodes_by_id:
            return ()
        queue = [start_id]
        seen = {start_id}
        result: list[GraphNode] = []
        while queue:
            current = queue.pop(0)
            adjacent = (
                self._in_edges.get(current, ())
                if reverse
                else self._out_edges.get(current, ())
            )
            for edge in adjacent:
                if selected is not None and edge.kind not in selected:
                    continue
                next_id = edge.source_id if reverse else edge.target_id
                if next_id in seen:
                    continue
                candidate = self._nodes_by_id.get(next_id)
                if candidate is None:
                    continue
                seen.add(next_id)
                queue.append(next_id)
                if predicate is None or predicate(candidate):
                    result.append(candidate)
        return tuple(result)

    def path(
        self, start: object, goal: object, kinds: str | Iterable[str] | None = None
    ) -> tuple[tuple[str, ...], ...] | None:
        start_id = self._coerce_node(start)
        goal_id = self._coerce_node(goal)
        selected = _kinds(kinds)
        if start_id is None or goal_id is None:
            return None
        if start_id == goal_id:
            return (start_id,)
        previous: dict[tuple[str, ...], tuple[str, ...] | None] = {start_id: None}
        queue = [start_id]
        while queue:
            current = queue.pop(0)
            for edge in self._out_edges.get(current, ()):
                if selected is not None and edge.kind not in selected:
                    continue
                if edge.target_id in previous:
                    continue
                previous[edge.target_id] = current
                if edge.target_id == goal_id:
                    chain: list[tuple[str, ...]] = []
                    step: tuple[str, ...] | None = goal_id
                    while step is not None:
                        chain.append(step)
                        step = previous[step]
                    return tuple(reversed(chain))
                queue.append(edge.target_id)
        return None

    def subgraph(
        self,
        predicate: Callable[[GraphNode | GraphEdge], bool] | None = None,
        edge_predicate: Callable[[GraphEdge], bool] | None = None,
    ) -> GraphView:
        def matches(item: GraphNode | GraphEdge) -> bool:
            if predicate is None:
                return False
            try:
                return bool(predicate(item))
            except (AttributeError, TypeError):
                return False

        matched_node_ids = {node.id for node in self._nodes if matches(node)}
        matched_edges = tuple(
            edge
            for edge in self._edges
            if matches(edge)
            or (edge_predicate is not None and edge_predicate(edge))
        )
        node_ids = set(matched_node_ids)
        for edge in matched_edges:
            node_ids.add(edge.source_id)
            node_ids.add(edge.target_id)
        selected_nodes = tuple(node for node in self._nodes if node.id in node_ids)
        selected_edges = (
            matched_edges
            if matched_edges
            else tuple(
                edge
                for edge in self._edges
                if edge.source_id in node_ids and edge.target_id in node_ids
            )
        )
        return GraphView(selected_nodes, selected_edges)

    def symbols_in(self, module: str) -> tuple[Symbol, ...]:
        return tuple(
            sorted(
                (symbol for symbol in self._symbols.values() if symbol.module == module),
                key=lambda symbol: symbol.key,
            )
        )

    def module_of(self, symbol: Symbol | str) -> str | None:
        if isinstance(symbol, Symbol):
            return symbol.module
        found = self._symbols.get(symbol)
        return None if found is None else found.module

    def resolve_call(
        self, site: CallSite
    ) -> tuple[CallEdge | None, UnresolvedCall | None, tuple[Symbol, ...]]:
        caller = self._symbols.get(site.caller)
        if caller is None:
            return None, None, ()
        module = caller.module

        if site.hint == "qualified" and "." in site.callee:
            base, member = site.callee.split(".", 1)
            binding = self._bindings.get((module, base))
            if binding is not None and binding[0]:
                candidates = self._symbols_by_name.get((binding[0], member), ())
            elif base in {"self", "cls"} and "." in caller.name:
                prefix = caller.name.rsplit(".", 1)[0]
                candidates = self._symbols_by_name.get(
                    (module, f"{prefix}.{member}"), ()
                )
            else:
                candidates = ()
        else:
            candidates = self._symbols_by_name.get((module, site.callee), ())
            if not candidates:
                binding = self._bindings.get((module, site.callee))
                if binding is not None and binding[1]:
                    candidates = self._symbols_by_name.get(
                        (binding[0], binding[1]), ()
                    )

        if len(candidates) == 1:
            return (
                CallEdge(
                    site.caller,
                    candidates[0].key,
                    "EXTRACTED",
                    site.source,
                    site.line,
                ),
                None,
                candidates,
            )

        reason = "ambiguous_call" if candidates else "unresolved_call"
        return (
            None,
            UnresolvedCall(site.caller, site.callee, reason, site.source, site.line),
            candidates,
        )

    def _resolve_calls(
        self,
    ) -> tuple[tuple[CallEdge, ...], tuple[UnresolvedCall, ...]]:
        edges: list[CallEdge] = []
        unresolved: list[UnresolvedCall] = []
        for site in self._facts.call_sites:
            edge, missing, _ = self.resolve_call(site)
            if edge is not None:
                edges.append(edge)
            if missing is not None:
                unresolved.append(missing)
        return tuple(edges), tuple(unresolved)

    def dependencies(self) -> tuple[Dependency, ...]:
        return self._facts.dependencies

    def incoming(
        self, module: str, extra: Iterable[Dependency] = ()
    ) -> tuple[Dependency, ...]:
        items = list(self._incoming.get(module, ()))
        for dep in extra:
            if (
                dep.source_module
                and dep.target_module == module
                and dep.source_module != dep.target_module
            ):
                items.append(dep)
        return tuple(sorted(items, key=self._dependency_order))

    def callers_of(self, symbol_key: str) -> tuple[str, ...]:
        return self._reverse_calls.get(symbol_key, ())

    def symbols_named(self, module: str, name: str) -> tuple[Symbol, ...]:
        return self._symbols_by_name.get((module, name), ())

    def binding(self, module: str, local_name: str) -> tuple[str, str] | None:
        return self._bindings.get((module, local_name))

    def resolve_calls(
        self,
    ) -> tuple[tuple[CallEdge, ...], tuple[UnresolvedCall, ...]]:
        return self._call_edges, self._unresolved

    def concern_symbols(self) -> dict[str, BoundaryConcernUse]:
        return dict(self._concerns_by_symbol)

    def concern_carriers(self, max_depth: int) -> tuple[BoundaryConcernUse, ...]:
        frontier = self.concern_symbols()
        if not frontier:
            return ()

        synthetic: list[BoundaryConcernUse] = []
        seen = set(frontier)
        for _ in range(max_depth):
            next_frontier: dict[str, BoundaryConcernUse] = {}
            for edge in self._call_edges:
                concern = frontier.get(edge.callee)
                if (
                    concern is None
                    or edge.caller in seen
                    or edge.caller not in self._symbols
                ):
                    continue
                seen.add(edge.caller)
                caller = self._symbols[edge.caller]
                synthetic.append(
                    BoundaryConcernUse(
                        caller.module,
                        concern.concern,
                        concern.category,
                        edge.source,
                        edge.line,
                    )
                )
                next_frontier[edge.caller] = concern
            frontier = next_frontier
            if not frontier:
                break
        return tuple(synthetic)

    def relevant_unresolved_reviews(self) -> tuple[SemanticReview, ...]:
        origins = self.concern_symbols()
        origin_names = {
            self._symbols[key].name.rsplit(".", 1)[-1]
            for key in origins
            if key in self._symbols
        }
        if not origin_names:
            return ()

        reviews: list[SemanticReview] = []
        for item in self._unresolved:
            caller = self._symbols.get(item.caller)
            if caller is None:
                continue
            if "." in item.name:
                base, member = item.name.split(".", 1)
                binding = self._bindings.get((caller.module, base))
                if binding is None:
                    continue
                target_module, target_symbol = binding
                if target_symbol:
                    name = target_symbol
                elif any(
                    symbol.module == target_module and symbol.name == member
                    for symbol in self._symbols.values()
                ):
                    name = member
                else:
                    continue
            else:
                name = item.name
            if name.rsplit(".", 1)[-1] not in origin_names:
                continue
            reviews.append(
                SemanticReview(
                    caller.module,
                    item.source,
                    item.line,
                    f"unresolved call may reach concern-bearing helper {item.name}",
                )
            )
        return tuple(reviews)

    def wrapper_invocations(
        self, wrapper_module: str | None = None
    ) -> tuple[GraphEdge, ...]:
        result: list[GraphEdge] = []
        for edge in self.edges("invokes"):
            if wrapper_module is None:
                result.append(edge)
                continue
            node = self._nodes_by_id.get(edge.source_id)
            owner = getattr(node.value, "module", None) if node is not None else None
            if owner == wrapper_module:
                result.append(edge)
        return tuple(result)

    def review_state_hash(self, item: SemanticReview) -> str:
        payload = "|".join(
            (
                "review",
                item.module,
                item.source,
                str(item.line),
                item.reason,
                item.source,
                str(item.line),
                item.reason,
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def diff(self, other: "GraphIndex") -> GraphDiff:
        other_nodes = {node.id: node for node in other.nodes()}
        other_edges = {edge.id: edge for edge in other.edges()}
        self_nodes = {node.id for node in self._nodes}
        self_edges = {edge.id for edge in self._edges}
        return GraphDiff(
            tuple(
                node for node in self._nodes if node.id not in other_nodes
            ),
            tuple(
                other_nodes[key] for key in sorted(other_nodes.keys() - self_nodes)
            ),
            tuple(
                edge for edge in self._edges if edge.id not in other_edges
            ),
            tuple(
                other_edges[key] for key in sorted(other_edges.keys() - self_edges)
            ),
        )

    def cycles(self) -> tuple[tuple[str, ...], ...]:
        color: dict[str, int] = {}
        stack: list[str] = []
        seen: set[tuple[str, ...]] = set()
        cycles: list[tuple[str, ...]] = []

        def visit(node: str) -> None:
            color[node] = 1
            stack.append(node)
            for nxt in sorted(self._outgoing.get(node, ())):
                state = color.get(nxt, 0)
                if state == 0:
                    visit(nxt)
                elif state == 1:
                    start = stack.index(nxt) if nxt in stack else 0
                    cycle = tuple(stack[start:] + [nxt])
                    if cycle not in seen:
                        seen.add(cycle)
                        cycles.append(cycle)
            stack.pop()
            color[node] = 2

        for node in sorted(self._outgoing):
            if color.get(node, 0) == 0:
                visit(node)

        return tuple(cycles)
