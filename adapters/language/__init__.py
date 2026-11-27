"""Language-specific source analyzers registered by file suffix."""

from .native_analyzer import (
    GoSourceAnalyzer,
    JavaScriptSourceAnalyzer,
    RustSourceAnalyzer,
)
from .python_analyzer import PythonSourceAnalyzer

_ANALYZER_INSTANCES = (
    PythonSourceAnalyzer(),
    GoSourceAnalyzer(),
    RustSourceAnalyzer(),
    JavaScriptSourceAnalyzer(),
)

ANALYZERS = {
    suffix: analyzer
    for analyzer in _ANALYZER_INSTANCES
    for suffix in analyzer.suffixes
}


def analyzer_for_suffix(suffix):
    return ANALYZERS.get(str(suffix).lower())


def registry():
    return tuple(sorted(ANALYZERS))


__all__ = [
    "ANALYZERS",
    "GoSourceAnalyzer",
    "JavaScriptSourceAnalyzer",
    "PythonSourceAnalyzer",
    "RustSourceAnalyzer",
    "analyzer_for_suffix",
    "registry",
]
