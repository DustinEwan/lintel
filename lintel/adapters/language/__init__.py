"""Language-specific source analyzers registered by file suffix."""

from .native_analyzer import (
    GoSourceAnalyzer,
    JavaScriptSourceAnalyzer,
    RustSourceAnalyzer,
)
from .python_analyzer import PythonSourceAnalyzer

TreeSitterGoAnalyzer = None
TreeSitterPythonAnalyzer = None
TreeSitterRustAnalyzer = None
TreeSitterTypeScriptAnalyzer = None
try:
    from .tree_sitter_analyzer import (
        TreeSitterTypeScriptAnalyzer as _TreeSitterTypeScriptAnalyzer,
    )
    from .tree_sitter_go import TreeSitterGoAnalyzer as _TreeSitterGoAnalyzer
    from .tree_sitter_python import TreeSitterPythonAnalyzer as _TreeSitterPythonAnalyzer
    from .tree_sitter_rust import TreeSitterRustAnalyzer as _TreeSitterRustAnalyzer
except ImportError:
    _TreeSitterGoAnalyzer = None
    _TreeSitterPythonAnalyzer = None
    _TreeSitterRustAnalyzer = None
    _TreeSitterTypeScriptAnalyzer = None

TreeSitterGoAnalyzer = _TreeSitterGoAnalyzer
TreeSitterPythonAnalyzer = _TreeSitterPythonAnalyzer
TreeSitterRustAnalyzer = _TreeSitterRustAnalyzer
TreeSitterTypeScriptAnalyzer = _TreeSitterTypeScriptAnalyzer

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

if TreeSitterTypeScriptAnalyzer is not None:
    ANALYZERS[".ts"] = TreeSitterTypeScriptAnalyzer()
if TreeSitterGoAnalyzer is not None:
    ANALYZERS[".go"] = TreeSitterGoAnalyzer()
if TreeSitterRustAnalyzer is not None:
    ANALYZERS[".rs"] = TreeSitterRustAnalyzer()
if TreeSitterPythonAnalyzer is not None:
    ANALYZERS[".py"] = TreeSitterPythonAnalyzer()

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
    "TreeSitterGoAnalyzer",
    "TreeSitterPythonAnalyzer",
    "TreeSitterRustAnalyzer",
    "TreeSitterTypeScriptAnalyzer",
    "analyzer_for_suffix",
    "registry",
]
