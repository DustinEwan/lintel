"""Pure resolution of normalized call facts."""

from .model import CallEdge, SemanticReview, UnresolvedCall


def concern_symbols(facts):
    result = {}
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
        chosen = min(candidates, key=lambda item: (item.end_line - item.line, item.line))
        result.setdefault(chosen.key, concern)
    return result



def _bindings(facts):
    module_names = {item.name for item in facts.modules}
    result = {}
    for item in facts.import_bindings:
        target_module = item.target_module
        target_symbol = item.target_symbol
        candidate = f"{target_module}.{target_symbol}" if target_symbol else ""
        if candidate and candidate in module_names:
            target_module, target_symbol = candidate, ""
        result[(item.module, item.local_name)] = (target_module, target_symbol)
    return result

def resolve_calls(facts):
    symbols = {item.key: item for item in facts.symbols}
    by_name = {}
    for item in facts.symbols:
        by_name.setdefault((item.module, item.name), []).append(item)
    bindings = _bindings(facts)

    edges = []
    unresolved = []
    for site in facts.call_sites:
        caller = symbols.get(site.caller)
        if caller is None:
            continue
        module = caller.module

        if site.hint == "qualified" and "." in site.callee:
            base, member = site.callee.split(".", 1)
            binding = bindings.get((module, base))
            if binding is not None and binding[0]:
                candidates = by_name.get((binding[0], member), ())
            elif base in {"self", "cls"} and "." in caller.name:
                prefix = caller.name.rsplit(".", 1)[0]
                candidates = by_name.get((module, f"{prefix}.{member}"), ())
            else:
                candidates = ()
        else:
            candidates = by_name.get((module, site.callee), ())
            if not candidates:
                binding = bindings.get((module, site.callee))
                if binding is not None and binding[1]:
                    candidates = by_name.get((binding[0], binding[1]), ())

        if len(candidates) == 1:
            edges.append(
                CallEdge(
                    site.caller,
                    candidates[0].key,
                    "EXTRACTED",
                    site.source,
                    site.line,
                )
            )
            continue

        reason = "ambiguous_call" if candidates else "unresolved_call"
        unresolved.append(
            UnresolvedCall(site.caller, site.callee, reason, site.source, site.line)
        )

    return tuple(edges), tuple(unresolved)


def relevant_unresolved_reviews(facts):
    origins = concern_symbols(facts)
    symbols = {item.key: item for item in facts.symbols}
    origin_names = {
        symbols[key].name.rsplit(".", 1)[-1]
        for key in origins
        if key in symbols
    }
    if not origin_names:
        return ()

    bindings = _bindings(facts)
    _, unresolved = resolve_calls(facts)
    reviews = []
    for item in unresolved:
        caller = symbols.get(item.caller)
        if caller is None:
            continue
        if "." in item.name:
            base, member = item.name.split(".", 1)
            binding = bindings.get((caller.module, base))
            if binding is None:
                continue
            target_module, target_symbol = binding
            if target_symbol:
                name = target_symbol
            elif any(
                item.module == target_module and item.name == member
                for item in facts.symbols
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
