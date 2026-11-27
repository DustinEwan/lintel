"""Language-specific native analyzers for boundary concerns."""

import re

from lintel.core.checker import module_name_from_path
from lintel.core.model import BoundaryConcernUse, Entrypoint, SourceAnalysis

GO_PATTERNS = (
    ("flag.Parse", "argv_parse", "entrypoint_only"),
    ("os.Exit", "exit", "entrypoint_only"),
    ("os.Getenv", "env", "mechanism"),
    ("log.", "logging", "mechanism"),
    ("fmt.Print", "terminal_io", "mechanism"),
)

RUST_PATTERNS = (
    ("std::env::args", "argv_parse", "entrypoint_only"),
    (r"re:#\[derive\([^)]*\bParser\b[^)]*\)]", "argv_parse", "entrypoint_only"),
    ("std::process::exit", "exit", "entrypoint_only"),
    ("std::env::var", "env", "mechanism"),
    ("println!", "terminal_io", "mechanism"),
    ("log::", "logging", "mechanism"),
)

JAVASCRIPT_PATTERNS = (
    ("process.argv", "argv_parse", "entrypoint_only"),
    ("process.exit", "exit", "entrypoint_only"),
    ("process.env", "env", "mechanism"),
    ("console.log", "terminal_io", "mechanism"),
)

_GO_MAIN = re.compile(r"func\s+main\s*\(")
_RUST_MAIN = re.compile(r"(?:pub\s+)?fn\s+main\s*\(")

_RUST_CHAR = re.compile(r"'(\\[^\n]|[^'\\\n])'")


def _mask_comments_and_strings(source, kind):
    state = {"block": 0, "quote": None}
    masked = []
    for raw in source.splitlines():
        chars = list(raw)
        result = []
        index = 0
        while index < len(chars):
            char = chars[index]
            if state["block"]:
                if char == "/" and chars[index + 1 : index + 2] == ["*"]:
                    if kind == "rust":
                        state["block"] += 1
                    result.extend("  ")
                    index += 2
                    continue
                if char == "*" and chars[index + 1 : index + 2] == ["/"]:
                    state["block"] -= 1
                    result.extend("  ")
                    index += 2
                    continue
                result.append(" ")
                index += 1
                continue
            if state["quote"]:
                if char == "\\" and state["quote"] != "`":
                    result.append(" ")
                    if index + 1 < len(chars):
                        result.append(" ")
                        index += 2
                    else:
                        index += 1
                    continue
                if char == state["quote"]:
                    state["quote"] = None
                result.append(" ")
                index += 1
                continue
            if char == "/" and chars[index + 1 : index + 2] == ["/"]:
                result.extend(" " * (len(chars) - index))
                break
            if char == "/" and chars[index + 1 : index + 2] == ["*"]:
                state["block"] = 1
                result.extend("  ")
                index += 2
                continue
            if char == "'" and kind == "rust":
                if not _RUST_CHAR.match(raw, index):
                    result.append(char)
                    index += 1
                    continue
            if char in ('"', "'") or (char == "`" and kind in ("go", "javascript")):
                state["quote"] = char
                result.append(" ")
                index += 1
                continue
            result.append(char)
            index += 1
        if state["quote"] and state["quote"] != "`":
            state["quote"] = None
        masked.append("".join(result))
    return masked


class NativeSourceAnalyzer:
    def __init__(self, suffixes, kind, patterns, main_test):
        self.suffixes = suffixes
        self.kind = kind
        self.patterns = patterns
        self.main_test = main_test

    def analyze(self, relative_path, source):
        module = module_name_from_path(relative_path)
        lines = _mask_comments_and_strings(source, self.kind)
        entrypoint = None
        concerns = []

        for number, line in enumerate(lines, 1):
            stripped = line.strip()
            if entrypoint is None and self.main_test(stripped):
                entrypoint = Entrypoint(module, relative_path, self.kind)
            for token, concern, category in self.patterns:
                matched = (
                    re.search(token[3:], stripped) is not None
                    if token.startswith("re:")
                    else token in stripped
                )
                if matched:
                    concerns.append(
                        BoundaryConcernUse(
                            module, concern, category, relative_path, number
                        )
                    )

        return SourceAnalysis(entrypoint, tuple(concerns))


def GoSourceAnalyzer():
    return NativeSourceAnalyzer(
        (".go",), "go", GO_PATTERNS, lambda line: bool(_GO_MAIN.match(line))
    )


def RustSourceAnalyzer():
    return NativeSourceAnalyzer(
        (".rs",), "rust", RUST_PATTERNS, lambda line: bool(_RUST_MAIN.match(line))
    )


def JavaScriptSourceAnalyzer():
    return NativeSourceAnalyzer(
        (".mjs", ".js", ".ts", ".tsx"),
        "javascript",
        JAVASCRIPT_PATTERNS,
        lambda line: "process.argv" in line,
    )
