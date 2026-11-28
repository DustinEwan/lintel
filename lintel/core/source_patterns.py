"""Language-agnostic boundary pattern catalogs shared by source analyzers."""

ENTRYPOINT_ONLY_IMPORTS = frozenset({"argparse", "typer", "click"})
MECHANISM_IMPORTS = frozenset({"logging"})
SUBPROCESS_CALLS = frozenset(
    {"run", "call", "Popen", "check_call", "check_output"}
)

BOUNDARY_IMPORTS = {
    ("sys", "argv"): ("argv", "entrypoint_only"),
    ("sys", "exit"): ("exit", "entrypoint_only"),
    ("os", "environ"): ("env", "mechanism"),
    ("os", "_exit"): ("exit", "entrypoint_only"),
}
BOUNDARY_ATTRIBUTES = {
    "sys.argv": ("argv", "entrypoint_only"),
    "sys.exit": ("exit", "entrypoint_only"),
    "os.environ": ("env", "mechanism"),
    "os._exit": ("exit", "entrypoint_only"),
}
REFLECTED_ATTRIBUTE_NAMES = frozenset(
    name.rsplit(".", 1)[-1] for name in BOUNDARY_ATTRIBUTES
)
GOVERNED_REFLECTION_BASES = frozenset({"os", "sys", "os.environ"})
BOUNDARY_IMPORT_MODULES = frozenset({"os", "sys"})
ENTRYPOINT_PATH_PREFIXES = ("lintel/cli/", "cli/")
UNRESOLVED_CLI_MARKERS = ("cli", "command")
REVIEW_EXEMPT_PATH_PARTS = ("tests", "fixtures", "examples")
INJECTED_PARAMETER_NAMES = frozenset({"args", "argv", "env"})
CORE_PATH_PREFIXES = ("lintel/core/", "core/")
LIVE_ENV_ANNOTATIONS = frozenset({"_Environ", "os._Environ"})
LIVE_ARGV_ANNOTATIONS = frozenset(
    {
        "ArgumentParser",
        "argparse.ArgumentParser",
        "ModuleType",
        "types.ModuleType",
    }
)
PLAIN_ANNOTATIONS = frozenset(
    {
        "Any",
        "Iterable",
        "Literal",
        "Mapping",
        "MutableMapping",
        "Namespace",
        "Optional",
        "Sequence",
        "Union",
        "bool",
        "bytes",
        "dict",
        "float",
        "frozenset",
        "int",
        "list",
        "set",
        "str",
        "tuple",
    }
)
AMBIGUOUS_ANNOTATIONS = frozenset({"Any", "object"})

_configured_env_call_patterns = frozenset()


def configure_env_call_patterns(patterns):
    """Install configured env-reading call names shared by Python analyzers."""
    global _configured_env_call_patterns
    _configured_env_call_patterns = frozenset(patterns or ())


def env_call_patterns():
    """Return configured env-reading call names."""
    return _configured_env_call_patterns
