# Contributing

## Development setup

Requires Python 3.11 or newer.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Install the local commit hook:

```sh
git config core.hooksPath .githooks
```

## Workflow

1. Create a branch for the change.
2. Make the smallest change that preserves existing rule IDs, fingerprints, and
   violation ordering unless the change explicitly alters them.
3. Run the checks below.
4. Regenerate locks with `lintel update-lock` when checker artifacts change.
5. Open a pull request with a Conventional Commit title.

## Checks

```sh
python3 -m py_compile lintel/*.py lintel/adapters/*.py lintel/adapters/language/*.py lintel/core/*.py lintel/core/use_cases/*.py lintel/cli/*.py tests/*.py
python3 -m unittest discover -s tests -v
python3 lintel/cli/main.py check --format json
```

Architecture findings must be fixed or explicitly reviewed with
`lintel review <fingerprint> --decision ... --reason ...`. Contract drift is
resolved by `lintel update-lock`, never by hand-editing `lintel.lock`.

## Commit convention

Commit subjects follow Conventional Commits:

```text
type(scope): summary
type(scope)!: summary for a breaking change
```

Allowed types: `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`,
`refactor`, `revert`, `style`, `test`.

Examples:

```text
feat(graph): add derived graph query index
fix: resolve inline Rust path attributes correctly
docs: document release checklist
chore(release): v1.0.0
```

Breaking changes use `!` or a `BREAKING CHANGE:` footer. Commitizen validates
commit subjects through `.githooks/commit-msg` and generates `CHANGELOG.md`;
use `cz commit` if you want an interactive commit helper.

## Pull request checklist

- [ ] New behavior has regression tests.
- [ ] Existing rule IDs and fingerprints are unchanged, or the change is called out.
- [ ] Locks were regenerated, not hand-edited.
- [ ] `lintel check --format json` is clean.
- [ ] Commit subjects are Conventional Commits.
