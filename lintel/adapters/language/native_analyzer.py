"""Language-specific native analyzers for boundary concerns."""

import os
import re

from lintel.core.checker import module_name_from_path
from lintel.core.model import (
    BoundaryConcernUse,
    Entrypoint,
    SemanticReview,
    SourceAnalysis,
)


GO_PATTERNS = (
    ("flag.Parse", "argv_parse", "entrypoint_only"),
    ("os.Exit", "exit", "entrypoint_only"),
    ("os.Getenv", "env", "mechanism"),
    ("log.", "logging", "mechanism"),
    ("fmt.Print", "terminal_io", "mechanism"),
)

RUST_PATTERNS = (
    ("std::env::args", "argv_parse", "entrypoint_only"),
    ("std::env::args_os", "argv_parse", "entrypoint_only"),
    (r"re:#\[derive\([^)]*\bParser\b[^)]*\)]", "argv_parse", "entrypoint_only"),
    ("std::process::exit", "exit", "entrypoint_only"),
    ("std::env::var", "env", "mechanism"),
    ("std::env::var_os", "env", "mechanism"),
    ("std::io::stdout", "terminal_io", "mechanism"),
    ("std::io::stderr", "terminal_io", "mechanism"),
    ("io::stdout", "terminal_io", "mechanism"),
    ("io::stderr", "terminal_io", "mechanism"),
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

_RUST_TERMINAL_MACROS = frozenset(
    {
        "println",
        "print",
        "eprintln",
        "eprint",
        "std::println",
        "std::print",
        "std::eprintln",
        "std::eprint",
    }
)
_RUST_LOGGING_MACROS = frozenset(
    {
        "info",
        "warn",
        "error",
        "log::info",
        "log::warn",
        "log::error",
    }
)
# Macros with no process-boundary behavior; keeping them out of the review
# stream avoids noise from ordinary Rust collection and assertion syntax.
_RUST_BENIGN_MACROS = frozenset(
    {
        "assert",
        "assert_eq",
        "assert_ne",
        "debug_assert",
        "debug_assert_eq",
        "debug_assert_ne",
        "cfg",
        "cfg_attr",
        "column",
        "concat",
        "file",
        "format",
        "format_args",
        "include",
        "include_bytes",
        "include_str",
        "line",
        "matches",
        "module_path",
        "panic",
        "select",
        "stringify",
        "todo",
        "unimplemented",
        "unreachable",
        "vec",
    }
)

_RUST_MACRO_RE = re.compile(
    r"(?<![A-Za-z0-9_:])"
    r"(?P<path>[A-Za-z_][A-Za-z0-9_]*(?:\s*::\s*[A-Za-z_][A-Za-z0-9_]*)*)"
    r"\s*!(?=\s*[({])"
)
_RUST_MACRO_RULES_RE = re.compile(r"(?<![A-Za-z0-9_:])macro_rules\s*!")

_RUST_CFG_START_RE = re.compile(r"^#\s*\[\s*(?P<name>cfg|cfg_attr)\s*\(")
_CFG_TOKEN_RE = re.compile(r"\s*(?P<token>&&|\|\||[(),=!]|[A-Za-z_][A-Za-z0-9_]*)")


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


def _bounded_text(value, limit=64):
    compact = " ".join(str(value).split())
    return compact if len(compact) <= limit else compact[: limit - 3] + "..."


def _cfg_and(left, right):
    if left is False or right is False:
        return False
    if left is None or right is None:
        return None
    return True


def _cfg_or(left, right):
    if left is True or right is True:
        return True
    if left is None or right is None:
        return None
    return False


def _cfg_not(value):
    return None if value is None else not value


def _cfg_tokens(expression):
    tokens = []
    index = 0
    while index < len(expression):
        match = _CFG_TOKEN_RE.match(expression, index)
        if match is None:
            if expression[index].isspace():
                index += 1
                continue
            return None
        tokens.append(match.group("token"))
        index = match.end()
    return tokens


def _parse_cfg_primary(tokens, position):
    if position >= len(tokens):
        return None, position
    token = tokens[position]
    if token == "!":
        value, position = _parse_cfg_primary(tokens, position + 1)
        return _cfg_not(value), position
    if token == "(":
        value, position = _parse_cfg_or(tokens, position + 1)
        if position < len(tokens) and tokens[position] == ")":
            position += 1
        return value, position
    if token in {"&&", "||", ",", "=", ")"}:
        return None, position + 1
    if position + 1 < len(tokens) and tokens[position + 1] == "=":
        position += 2
        if position < len(tokens) and tokens[position] not in {"&&", "||", ",", ")"}:
            position += 1
        return None, position
    if position + 1 < len(tokens) and tokens[position + 1] == "(":
        values, position = _parse_cfg_args(tokens, position + 2)
        if token == "all":
            value = True
            for item in values:
                value = _cfg_and(value, item)
        elif token == "any":
            value = False
            for item in values:
                value = _cfg_or(value, item)
        elif token == "not":
            value = _cfg_not(values[0]) if values else None
        else:
            value = None
        return value, position
    if token == "unix":
        return os.name == "posix", position + 1
    if token == "windows":
        return os.name == "nt", position + 1
    # `test` and all other predicates are not knowable from source alone.
    return None, position + 1


def _parse_cfg_args(tokens, position):
    values = []
    if position < len(tokens) and tokens[position] == ")":
        return values, position + 1
    while position < len(tokens):
        value, position = _parse_cfg_or(tokens, position)
        values.append(value)
        if position < len(tokens) and tokens[position] == ",":
            position += 1
            continue
        break
    if position < len(tokens) and tokens[position] == ")":
        position += 1
    return values, position


def _parse_cfg_or(tokens, position):
    value, position = _parse_cfg_and(tokens, position)
    while position < len(tokens) and tokens[position] == "||":
        right, position = _parse_cfg_and(tokens, position + 1)
        value = _cfg_or(value, right)
    return value, position


def _parse_cfg_and(tokens, position):
    value, position = _parse_cfg_primary(tokens, position)
    while position < len(tokens) and tokens[position] == "&&":
        right, position = _parse_cfg_primary(tokens, position + 1)
        value = _cfg_and(value, right)
    return value, position


def _cfg_predicate_expression(name, expression):
    if name != "cfg_attr":
        return expression
    depth = 0
    for index, char in enumerate(expression):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            return expression[:index]
    return expression


def _take_rust_cfg(line):
    """Split a leading Rust cfg attribute from the code that follows it."""
    match = _RUST_CFG_START_RE.match(line)
    if match is None:
        return None, line
    depth = 1
    index = match.end()
    while index < len(line):
        char = line[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                expression = line[match.end() : index]
                remainder = line[index + 1 :].lstrip()
                if remainder.startswith("]"):
                    remainder = remainder[1:].strip()
                return (match.group("name"), expression), remainder
        index += 1
    return (match.group("name"), line[match.end() :]), ""


def _evaluate_rust_cfg(name, expression):
    tokens = _cfg_tokens(_cfg_predicate_expression(name, expression))
    if not tokens:
        return None
    value, position = _parse_cfg_or(tokens, 0)
    return None if position != len(tokens) else value


def _rust_char_braces(raw_line):
    """Braces inside char literals are not scope delimiters."""
    opening = closing = 0
    for match in _RUST_CHAR.finditer(raw_line):
        if match.group(1) == "{":
            opening += 1
        elif match.group(1) == "}":
            closing += 1
    return opening, closing


def _rust_macro_kind(path):
    if path in _RUST_LOGGING_MACROS:
        return "logging"
    if path in _RUST_TERMINAL_MACROS:
        return "terminal_io"
    if "::" in path:
        return None
    if path in _RUST_LOGGING_MACROS:
        return "logging"
    if path in _RUST_TERMINAL_MACROS:
        return "terminal_io"
    return None


class NativeSourceAnalyzer:
    def __init__(self, suffixes, kind, patterns, main_test):
        self.suffixes = suffixes
        self.kind = kind
        self.patterns = patterns
        self.main_test = main_test

    def analyze(self, relative_path, source):
        module = module_name_from_path(relative_path)
        lines = _mask_comments_and_strings(source, self.kind)
        if self.kind == "rust":
            return self._analyze_rust(module, relative_path, source.splitlines(), lines)

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

    def _analyze_rust(self, module, relative_path, raw_lines, lines):
        entrypoint = None
        concerns = []
        reviews = []
        seen_concerns = set()
        seen_reviews = set()
        seen_macros = set()

        # `scopes` holds the cfg state of brace-delimited items; `pending`
        # carries attributes on their own lines to the next item or statement.
        depth = 0
        scopes = []
        pending = True
        pending_reason = ""

        for number, (raw, line) in enumerate(zip(raw_lines, lines), 1):
            cfg_attribute, code = _take_rust_cfg(line.strip())
            if cfg_attribute is None:
                line_cfg, line_reason = pending, pending_reason
                pending, pending_reason = True, ""
            else:
                name, expression = cfg_attribute
                value = _evaluate_rust_cfg(name, expression)
                line_cfg = _cfg_and(pending, value)
                line_reason = (
                    f"unresolved cfg predicate "
                    f"'{_bounded_text(expression)}' guards boundary operation"
                    if value is None
                    else pending_reason
                )
                if not code:
                    pending, pending_reason = line_cfg, line_reason
                    continue
                pending, pending_reason = True, ""

            effective = line_cfg
            effective_reason = line_reason
            for _, state, scope_reason in scopes:
                effective = _cfg_and(effective, state)
                effective_reason = effective_reason or scope_reason
            opening, closing = _rust_char_braces(raw)
            delta = code.count("{") - opening - (code.count("}") - closing)
            if delta > 0 and line_cfg is not True:
                scopes.append((depth, line_cfg, line_reason))
            depth = max(0, depth + delta)
            while scopes and scopes[-1][0] >= depth:
                scopes.pop()

            if effective is False:
                continue

            stripped = code.strip()
            # macro_rules! expansion is already an unparsed_source fact from the
            # Rust dependency extractor. Skip its text here instead of
            # double-reporting or treating an unexpanded body as executable code.
            if _RUST_MACRO_RULES_RE.search(code) is None:
                if (
                    entrypoint is None
                    and effective is True
                    and self.main_test(stripped)
                ):
                    entrypoint = Entrypoint(module, relative_path, self.kind)

                found = []
                for token, concern, category in self.patterns:
                    matched = (
                        re.search(token[3:], stripped) is not None
                        if token.startswith("re:")
                        else token in stripped
                    )
                    if matched:
                        found.append((concern, category))

                for match in _RUST_MACRO_RE.finditer(code):
                    path = re.sub(r"\s*::\s*", "::", match.group("path"))
                    kind = _rust_macro_kind(path)
                    if kind is not None:
                        found.append((kind, "mechanism"))
                        continue
                    if "::" not in path and path in _RUST_BENIGN_MACROS:
                        continue
                    if path not in seen_macros:
                        seen_macros.add(path)
                        reviews.append(
                            SemanticReview(
                                module,
                                relative_path,
                                number,
                                f"unknown macro '{_bounded_text(path)}' "
                                "may expand to a boundary operation",
                            )
                        )

                for concern, category in found:
                    key = (number, concern, category)
                    if key not in seen_concerns:
                        seen_concerns.add(key)
                        concerns.append(
                            BoundaryConcernUse(
                                module, concern, category, relative_path, number
                            )
                        )
                        if effective is None and effective_reason:
                            review_key = (number, effective_reason)
                            if review_key not in seen_reviews:
                                seen_reviews.add(review_key)
                                reviews.append(
                                    SemanticReview(
                                        module, relative_path, number, effective_reason
                                    )
                                )


        return SourceAnalysis(entrypoint, tuple(concerns), reviews=tuple(reviews))


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
