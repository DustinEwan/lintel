# Agentic semantic evaluation scenarios

Status: inventory and decision-model decision contract; implemented scenarios use deterministic facts or bounded semantic reviews.

Implementation status and deterministic extractor gaps live in [docs/limitations.md](docs/limitations.md).

## Purpose

Deterministic analyzers are good at syntax-shaped facts: imports, call names,
main guards, literal attributes, and declared executable paths. They are weak
at intent. This document records scenarios where a syntax or token detector
cannot reliably decide whether a boundary rule is satisfied.

The decision-model checker evaluates only these ambiguous cases. It must not
replace deterministic checks, the contract lock, or the violation ratchet.

## Judge contract

Input:

- rule ID and boundary category under evaluation;
- candidate source location and excerpt;
- module, layer, scope, and declared executable context;
- resolved imports/aliases and call graph when available;
- relevant policy excerpts, especially allowed regions and declared wrappers;
- whether the file is generated, vendored, tested, or a build artifact.

Output:

- `compliant`, `violating`, or `needs-human-review`;
- confidence;
- rationale tied to concrete evidence;
- suggested fix when the result is `violation`.

Invariants:

- the judge is read-only;
- uncertainty must produce `needs-human-review`, never a silent pass;
- config, lock, baseline, and checker artifacts are outside its authority;
- model decisions resolve per-finding reviews only under locked policy; config,
  lock, baseline, and checker artifacts remain authority-gated.

## Scenarios

### SEM-01 Aliased standard-library access

```python
import sys as s
args = s.argv[1:]
```

Why semantic: token matching for `sys.argv` misses the alias. A resolver must
know that `s` binds to `sys`.

Expected judgment: `argv_parse`; if the owning module is not an entrypoint or
an allowed region, `violation`.

### SEM-02 Re-exported or rebound names

```python
from os import environ as env
home = env["HOME"]
```

Why semantic: the boundary concern is environment access even though the
literal token `os.environ` is absent.

Expected judgment: `env`; apply the configured `mechanism` allowed-region rule.

### SEM-03 Dynamic attribute or module access

```python
getattr(os, "environ")
importlib.import_module("sys").argv
```

Why semantic: the concern is hidden behind reflection. Deterministic AST
matching sees a call, not the boundary operation.

Expected judgment: identify the accessed symbol; treat unresolved dynamic
access as `needs-human-review`.

### SEM-04 Helper-function laundering

```python
def parse_cli():
    return argparse.ArgumentParser().parse_args()

# adapter module
settings = parse_cli()
```

Why semantic: `argparse` is imported in one place but used as an entrypoint
concern from another. The judge must follow the call relationship and decide
which module owns the concern.

Current behavior: Python `ast` facts emit symbols, import bindings, and call
sites; the core resolver follows uniquely resolved local calls through helper
chains and applies the normal boundary rule at each caller. Concerns are
attributed by symbol span, so a concern after a nested function belongs to the
outer function. An unresolved call is reported as `semantic_review` only when
its name matches a locally defined concern-bearing helper; unrelated external
or dynamic calls stay silent.

Expected judgment: attribute the concern to the module that invokes the helper
unless ownership is explicitly declared. Resolved Python cases are deterministic;
unresolved or cross-language cases still need a decision or human review.

### SEM-05 Declarative framework CLIs

```rust
#[derive(Parser)]
struct Args { ... }
```

```python
@app.command()
def run(name: str): ...
```

Why semantic: no explicit `parse()` call is necessarily present. Framework
conventions turn declarations into argv parsing.

Expected judgment: recognize the framework idiom as `argv_parse`; if confidence
is low, return `needs-human-review`.

### SEM-06 Configuration libraries that read the environment

```python
settings = Config.from_env()
```

Why semantic: the code contains no `os.environ`, but the library performs
environment access. The judge needs dependency knowledge or library metadata.

Expected judgment: `env` when the library behavior is known; otherwise
`needs-human-review`, not an automatic pass.

### SEM-07 Native tokens inside strings or comments

```go
// fmt.Print is intentionally mentioned in this comment.
```

Why semantic: native substring matching treats text as code. A parser-aware
detector can distinguish them, but generated or unusual syntax may still be
ambiguous.

Expected judgment: `allowed` for comments/strings; `violation` only for real
code execution.

### SEM-08 Macros and generated code

```rust
info!("started");
```

Why semantic: `println!`/`log!` macros expand into terminal or logging behavior
through macro rules. Generated clients may contain boundary operations not
written by the project.

Expected judgment: resolve macro/generated origin; if origin is external and the
file is declared generated/vendor, skip; otherwise apply the normal rule.

### SEM-09 Dependency-injected boundary values

```python
class Service:
    def __init__(self, args, env):
        self.args = args
        self.env = env
```

Why semantic: reading `sys.argv` in the CLI wrapper and passing plain data into
a use case is valid. Injecting live `sys.argv` or `os.environ` objects into core
is not.

Expected judgment: `allowed` for plain immutable data; `violation` for live
process-boundary objects or accessors that read them later.

### SEM-10 Wrapper calls into native boundary code

```python
subprocess.run(["./native-tool"])
```

and the native tool reads `std::env::args`.

Why semantic: the Python wrapper looks thin, but boundary work is delegated
across a build artifact boundary.

Expected judgment: `argv_parse` belongs to the wrapper surface only; if the
native artifact is undeclared or the wrapper has extra logic, `violation`.

### SEM-11 Conditional or platform-specific code

```rust
#[cfg(windows)]
fn main() { ... }
```

Why semantic: a literal detector sees a concern in code that may not compile on
the analyzed platform. The judge needs configuration context before deciding.

Expected judgment: evaluate the active configuration; unresolved conditions go
to `needs-human-review`.

### SEM-12 Terminal I/O through injected loggers

```python
logger.info("status")
```

Why semantic: logging may be a configured mechanism concern or a terminal I/O
concern depending on the handler and layer.

Expected judgment: use the boundary-concern configuration and handler context;
do not assume all logging is terminal output.

### SEM-13 Test, fixture, and example intent

```python
# tests/fixtures/fake_cli.py
import argparse
```

Why semantic: fixtures intentionally imitate production shapes. Deterministic
scope exclusion handles known prefixes, but unusual paths or generated copies
need intent judgment.

Expected judgment: `allowed` when the scope is genuinely excluded; otherwise
apply the production rule.

### SEM-14 New or unsupported language

A `.zig` or `.java` source file appears in a governed project.

Why semantic: the analyzer registry has no deterministic adapter for it. A
silent skip would fail open.

Expected judgment: `needs-human-review` with an explicit unsupported-source
finding; never an automatic pass.

### SEM-15 Third-party transitive boundary access

A core module imports a package whose internals read `os.environ`.

Why semantic: direct-import rules cannot see transitive behavior. The judge
needs package metadata or source analysis, plus intent about whether the
dependency is a port implementation.

Expected judgment: `violation` if core depends on a mechanism leaking through;
`allowed` only when the dependency is declared as an adapter mechanism.

### SEM-16 Policy change that tries to legalize a concern

A commit weakens `boundary_concerns.entrypoint_only.allowed_regions` while also
adding argv parsing to an adapter.

Why semantic: each edit may be individually valid, but together they weaken the
contract to hide a violation.

Expected judgment: flag the combined diff for review. The judge cannot accept
the new contract on behalf of a human.

## Out of scope for the judge

- Verifying config, lock, baseline, or checker hashes; those are deterministic.
- Deciding whether a new rule should exist; that is a policy change.
- Editing source, config, lock, or baseline.
- Replacing native dependency extraction with guesswork.
