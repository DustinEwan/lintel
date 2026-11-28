"""Facade for derived graph queries over normalized facts."""

from .graph_index import GraphIndex


def concern_symbols(facts):
    return GraphIndex(facts).concern_symbols()


def resolve_calls(facts):
    return GraphIndex(facts).resolve_calls()


def relevant_unresolved_reviews(facts):
    return GraphIndex(facts).relevant_unresolved_reviews()
