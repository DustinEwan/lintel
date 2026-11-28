"""Go build-constraint evaluation shared by graph contributors."""

import platform
import re
import subprocess
import sys

GOOS_VALUES = {
    "aix", "android", "darwin", "dragonfly", "freebsd", "hurd", "illumos",
    "ios", "js", "linux", "nacl", "netbsd", "openbsd", "plan9", "solaris",
    "wasip1", "windows", "zos",
}
GOARCH_VALUES = {
    "386", "amd64", "amd64p32", "arm", "arm64", "loong64", "mips", "mipsle",
    "mips64", "mips64le", "mips64p32", "mips64p32le", "ppc", "ppc64",
    "ppc64le", "riscv", "riscv64", "s390", "s390x", "sparc", "sparc64", "wasm",
}
UNIX_GOOS = GOOS_VALUES - {"js", "plan9", "wasip1", "windows", "zos"}
TAG_RE = re.compile(r"[A-Za-z0-9_.]+")
BUILD_TOKEN_RE = re.compile(r"\s*(?P<token>&&|\|\||[!()]|[A-Za-z0-9_.]+)")
BUILD_TAG_RE = re.compile(r"^//\s*(?:go:build|\+build)\b")


def host_target():
    try:
        result = subprocess.run(
            ["go", "env", "GOOS", "GOARCH", "CGO_ENABLED"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        values = result.stdout.split()
        if len(values) >= 2:
            cgo = None
            if len(values) >= 3 and values[2] in ("0", "1"):
                cgo = values[2] == "1"
            return values[0], values[1], cgo
    except (OSError, subprocess.SubprocessError):
        pass
    goos = {
        "linux": "linux",
        "darwin": "darwin",
        "win32": "windows",
        "cygwin": "windows",
    }.get(sys.platform, sys.platform)
    machine = platform.machine().lower()
    goarch = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
        "i386": "386",
        "i686": "386",
    }.get(machine, machine)
    return goos, goarch, None


def tag_value(tag, target):
    goos, goarch, cgo = target
    if tag == goos:
        return True
    if tag in GOOS_VALUES:
        return False
    if tag == goarch:
        return True
    if tag in GOARCH_VALUES:
        return False
    if tag == "unix":
        return goos in UNIX_GOOS
    if tag == "cgo":
        return cgo
    return None


def and_value(left, right):
    if left is False or right is False:
        return False
    if left is None or right is None:
        return None
    return True


def or_value(left, right):
    if left is True or right is True:
        return True
    if left is None or right is None:
        return None
    return False


def not_value(value):
    return None if value is None else not value


def build_tokens(text):
    tokens = []
    index = 0
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue
        match = BUILD_TOKEN_RE.match(text, index)
        if not match:
            return None
        tokens.append(match.group("token"))
        index = match.end()
    return tokens


def parse_build_atom(tokens, index, target):
    if index >= len(tokens):
        return None, index
    token = tokens[index]
    if token == "!":
        value, index = parse_build_atom(tokens, index + 1, target)
        return not_value(value), index
    if token == "(":
        value, index = parse_build_or(tokens, index + 1, target)
        if index >= len(tokens) or tokens[index] != ")":
            return None, index
        return value, index + 1
    if TAG_RE.fullmatch(token):
        return tag_value(token, target), index + 1
    return None, index + 1


def parse_build_and(tokens, index, target):
    value, index = parse_build_atom(tokens, index, target)
    while index < len(tokens) and tokens[index] == "&&":
        right, index = parse_build_atom(tokens, index + 1, target)
        value = and_value(value, right)
    return value, index


def parse_build_or(tokens, index, target):
    value, index = parse_build_and(tokens, index, target)
    while index < len(tokens) and tokens[index] == "||":
        right, index = parse_build_and(tokens, index + 1, target)
        value = or_value(value, right)
    return value, index


def evaluate_go_build(text, target):
    tokens = build_tokens(text)
    if tokens is None:
        return None
    value, index = parse_build_or(tokens, 0, target)
    return value if index == len(tokens) else None


def evaluate_plus_build(lines, target):
    result = True
    for line in lines:
        terms = line.split()
        if not terms:
            return None
        line_value = False
        for term in terms:
            term_value = True
            for raw_tag in term.split(","):
                negated = raw_tag.startswith("!")
                tag = raw_tag[1:] if negated else raw_tag
                if not TAG_RE.fullmatch(tag):
                    return None
                value = tag_value(tag, target)
                if negated and value is not None:
                    value = not_value(value)
                term_value = and_value(term_value, value)
            line_value = or_value(line_value, term_value)
        result = and_value(result, line_value)
    return result


def build_constraint_status(text, target):
    go_build = []
    plus_build = []
    first_line = None
    for line_number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not BUILD_TAG_RE.match(stripped):
            continue
        if first_line is None:
            first_line = line_number
        if stripped.startswith("//go:build"):
            go_build.append(stripped[len("//go:build"):].strip())
        elif stripped.startswith("// +build"):
            plus_build.append(stripped[len("// +build"):].strip())
    if not go_build and not plus_build:
        return True, None

    value = evaluate_go_build(go_build[0], target) if len(go_build) == 1 else None
    if plus_build:
        plus_value = evaluate_plus_build(plus_build, target)
        if plus_value is None:
            value = None
        elif value is None:
            value = plus_value
        elif value != plus_value:
            value = None
    return value, first_line
