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

KNOWN_SOURCE_SUFFIXES = frozenset(
    {
        ".py", ".go", ".rs", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
        ".mts", ".cts", ".java", ".kt", ".kts", ".scala", ".swift", ".c",
        ".h", ".cc", ".cpp", ".hpp", ".cs", ".rb", ".php", ".pl", ".pm",
        ".sh", ".bash", ".zsh", ".fish", ".sql", ".lua", ".r", ".m", ".mm",
        ".dart", ".ex", ".exs", ".erl", ".hs", ".clj", ".cljs", ".zig",
        ".nim", ".vue", ".svelte", ".elm", ".groovy", ".gradle", ".ps1",
        ".bat",
    }
)


def analyzer_for_suffix(suffix):
    return ANALYZERS.get(str(suffix).lower())


def registry():
    return tuple(sorted(ANALYZERS))


__all__ = [
    "KNOWN_SOURCE_SUFFIXES",
    "ANALYZERS",
    "GoSourceAnalyzer",
    "JavaScriptSourceAnalyzer",
    "PythonSourceAnalyzer",
    "RustSourceAnalyzer",
    "analyzer_for_suffix",
    "registry",
]
