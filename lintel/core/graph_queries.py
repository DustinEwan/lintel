"""Read-only architecture queries derived from the canonical fact graph."""

from dataclasses import asdict, is_dataclass

from . import checker, review
from .graph_index import GraphIndex
from .model import FactSet, Policy, violation_to_dict
from .ratchet import violation_fingerprint

_MODULE_EDGE_KINDS = frozenset(
    {"depends_on", "reviews", "has_entrypoint", "has_wrapper"}
)


def _module_names(nodes):
    names = set()
    for node in nodes:
        if node.kind != "module":
            continue
        name = getattr(node.value, "name", None)
        names.add(str(name) if name is not None else str(node.id[-1]))
    return tuple(sorted(names))


def _symbol_keys(nodes):
    keys = set()
    for node in nodes:
        if node.kind != "symbol":
            continue
        key = getattr(node.value, "key", None)
        keys.add(str(key) if key is not None else str(node.id[-1]))
    return tuple(sorted(keys))


def _edge_dict(edge):
    return dict(edge._asdict())


def _node_dict(node):
    data = dict(node._asdict())
    data["value"] = asdict(data["value"]) if is_dataclass(data["value"]) else data["value"]
    return data


def _relevant_violations(facts, policy, modules):
    modules = set(modules)
    result = []
    for item in checker.check(facts, policy):
        fields = item.fields
        references = set()
        for key in ("from", "to", "module", "target"):
            value = fields.get(key)
            if isinstance(value, str) and value:
                references.add(value)
        for key in ("path", "cycle"):
            value = fields.get(key)
            if isinstance(value, (tuple, list)):
                references.update(str(part) for part in value)
        if references & modules:
            result.append(violation_to_dict(item))
    return tuple(result)


def _entrypoints(facts, modules):
    return tuple(
        sorted(
            (asdict(item) for item in facts.entrypoints if item.module in modules),
            key=lambda item: (item["module"], item["path"]),
        )
    )


def module_impact(facts: FactSet, policy: Policy, module: str, index=None):
    """Return the reverse dependency impact of one module."""
    index = index or GraphIndex(facts)
    node = index.node(("module", module))
    if node is None:
        return {
            "target": {"kind": "module", "name": module},
            "affected_modules": (),
            "direct_importers": (),
            "paths": (),
            "entrypoints": (),
            "violations": (),
        }

    upstream = _module_names(
        index.reachable(node.id, kinds="depends_on", reverse=True)
    )
    affected = tuple(name for name in upstream if name != module)
    incoming = index.incoming_edges(node.id, kinds="depends_on")
    direct = tuple(sorted({edge.source_id[-1] for edge in incoming}))
    paths = []
    for source in direct:
        chain = index.path(("module", source), node.id, kinds="depends_on")
        if chain is not None:
            paths.append(tuple(step[-1] for step in chain))
    context_modules = set(affected) | {module}
    return {
        "target": {"kind": "module", "name": module},
        "affected_modules": affected,
        "direct_importers": direct,
        "paths": tuple(paths),
        "entrypoints": _entrypoints(facts, context_modules),
        "violations": _relevant_violations(facts, policy, context_modules),
    }


def symbol_impact(facts: FactSet, policy: Policy, key: str, index=None):
    """Return direct and transitive callers of one symbol."""
    index = index or GraphIndex(facts)
    node = index.node(("symbol", key))
    if node is None:
        return {
            "target": {"kind": "symbol", "name": key},
            "callers": (),
            "transitive_callers": (),
            "modules": (),
            "paths": (),
            "entrypoints": (),
            "violations": (),
        }

    callers = index.callers_of(key)
    transitive = _symbol_keys(
        index.reachable(node.id, kinds="calls", reverse=True)
    )
    modules = tuple(
        sorted(
            {
                module
                for symbol_key in set(callers) | set(transitive)
                if (module := index.module_of(symbol_key)) is not None
            }
        )
    )
    paths = []
    for caller in sorted(set(callers)):
        chain = index.path(("symbol", caller), node.id, kinds="calls")
        if chain is not None:
            paths.append(tuple(step[-1] for step in chain))
    return {
        "target": {
            "kind": "symbol",
            "name": key,
            "module": getattr(node.value, "module", None),
        },
        "callers": tuple(callers),
        "transitive_callers": transitive,
        "modules": modules,
        "paths": tuple(paths),
        "entrypoints": _entrypoints(facts, modules),
        "violations": _relevant_violations(facts, policy, modules),
    }


def concern_context(facts: FactSet, module: str | None = None, index=None):
    """Return declared, symbol-bound, propagated, and wrapper concerns."""
    index = index or GraphIndex(facts)
    declared = tuple(
        sorted(
            (
                asdict(item)
                for item in facts.concerns
                if module is None or item.module == module
            ),
            key=lambda item: (item["module"], item["source"], item["line"]),
        )
    )
    origins = []
    for key, concern in sorted(index.concern_symbols().items()):
        node = index.node(("symbol", key))
        owner = getattr(node.value, "module", None) if node is not None else None
        if module is not None and owner != module:
            continue
        origins.append(
            {
                "symbol": key,
                "module": owner,
                "concern": concern.concern,
                "category": concern.category,
                "source": concern.source,
                "line": concern.line,
            }
        )
    carriers = tuple(
        sorted(
            (
                asdict(item)
                for item in index.concern_carriers(checker.MAX_HELPER_CALL_DEPTH)
                if module is None or item.module == module
            ),
            key=lambda item: (item["module"], item["source"], item["line"]),
        )
    )
    wrappers = tuple(_edge_dict(edge) for edge in index.wrapper_invocations(module))
    return {
        "module": module,
        "declared": declared,
        "origins": tuple(origins),
        "carriers": carriers,
        "wrappers": wrappers,
    }


def _review_fingerprint(review, index):
    finding = checker.violation(
        "semantic_review",
        f"semantic review: {review.reason} ({review.source}:{review.line})",
        module=review.module,
        source=review.source,
        line=review.line,
        location=f"{review.source}:{review.line}",
        reason=review.reason,
        graph_state_hash=index.review_state_hash(review),
    )
    return violation_fingerprint(finding)


def _review_context(index, review):
    review_id = (
        "review",
        review.module,
        review.source,
        review.line,
        review.reason,
    )
    module_id = ("module", review.module)
    anchors = {
        node_id
        for node_id in (review_id, module_id)
        if index.node(node_id) is not None
    }
    symbol_ids = set()
    for node in index.nodes("symbol"):
        value = node.value
        source = getattr(value, "source", None)
        line = getattr(value, "line", None)
        end_line = getattr(value, "end_line", None)
        if source != review.source or line is None:
            continue
        if end_line is None or end_line < line:
            end_line = line
        if line <= review.line <= end_line:
            symbol_ids.add(node.id)
    node_ids = set(anchors) | symbol_ids
    edge_ids = set()
    for edge in index.edges():
        located = edge.origin == review.source and edge.line == review.line
        touches_review = review_id in (edge.source_id, edge.target_id)
        module_edge = (
            module_id in (edge.source_id, edge.target_id)
            and edge.kind in _MODULE_EDGE_KINDS
        )
        touches_symbol = (
            edge.source_id in symbol_ids or edge.target_id in symbol_ids
        )
        if located or touches_review or module_edge or touches_symbol:
            edge_ids.add(edge.id)
            node_ids.add(edge.source_id)
            node_ids.add(edge.target_id)
    return node_ids, edge_ids


def review_drift(before_facts: FactSet, facts: FactSet, index=None, before_index=None):
    """Return accepted reviews whose graph context changed since ``before_facts``."""
    index = index or GraphIndex(facts)
    before_index = before_index or GraphIndex(before_facts)
    current = {}
    for item in facts.reviews:
        current[_review_fingerprint(item, index)] = item
    previous = {}
    for item in before_facts.reviews:
        previous[_review_fingerprint(item, before_index)] = item

    diff = index.diff(before_index)
    result = []
    for decision in facts.decisions:
        if not review.is_accepting(decision.decision):
            continue
        item = current.get(decision.fingerprint)
        if item is None:
            result.append(
                {
                    "fingerprint": decision.fingerprint,
                    "decision": asdict(decision),
                    "review": None,
                    "reason": "accepted review is no longer present",
                }
            )
            continue
        old = previous.get(decision.fingerprint)
        if old is None:
            result.append(
                {
                    "fingerprint": decision.fingerprint,
                    "decision": asdict(decision),
                    "review": asdict(item),
                    "reason": "accepted review was not present in before facts",
                }
            )
            continue
        old_nodes, old_edges = _review_context(before_index, old)
        new_nodes, new_edges = _review_context(index, item)
        added_nodes = tuple(
            _node_dict(node)
            for node in diff.added_nodes
            if node.id in new_nodes or node.id in old_nodes
        )
        removed_nodes = tuple(
            _node_dict(node)
            for node in diff.removed_nodes
            if node.id in new_nodes or node.id in old_nodes
        )
        added_edges = tuple(
            _edge_dict(edge)
            for edge in diff.added_edges
            if edge.id in new_edges or edge.id in old_edges
        )
        removed_edges = tuple(
            _edge_dict(edge)
            for edge in diff.removed_edges
            if edge.id in new_edges or edge.id in old_edges
        )
        if not any((added_nodes, removed_nodes, added_edges, removed_edges)):
            continue
        result.append(
            {
                "fingerprint": decision.fingerprint,
                "decision": asdict(decision),
                "review": asdict(item),
                "graph_state_hash": index.review_state_hash(item),
                "before_graph_state_hash": before_index.review_state_hash(old),
                "added_nodes": added_nodes,
                "removed_nodes": removed_nodes,
                "added_edges": added_edges,
                "removed_edges": removed_edges,
            }
        )
    return tuple(sorted(result, key=lambda item: item["fingerprint"]))
