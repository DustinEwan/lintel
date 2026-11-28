# Releasing

## Preconditions

- Working tree is clean.
- CI is green.
- `python3 lintel/cli/main.py check --format json` reports `[]`.
- Commit subjects pass validation:
  ```sh
  cz check --rev-range <previous-tag>..HEAD
  ```
  For the first release, use a recent range instead:
  ```sh
  cz check --rev-range HEAD~20..HEAD
  ```

## Release commit

Commitizen derives the version bump and changelog from Conventional Commits.

1. Preview the release:

   ```sh
   cz bump --dry-run --yes
   ```

2. Apply the release:

   ```sh
   cz bump --yes
   ```

   This updates `pyproject.toml` and `CHANGELOG.md`, commits the change with
   the configured bump message, and creates the `vX.Y.Z` tag.

3. Review the generated changelog. Breaking changes come from `!` headers or
   `BREAKING CHANGE:` footers.

4. Push the release:

   ```sh
   git push origin main --follow-tags
   ```

5. Pushing the tag triggers `.github/workflows/release.yml`. It builds standalone
   binaries, publishes them with `SHA256SUMS` to GitHub Releases, and publishes
   `lintel-architecture` to PyPI using `PYPI_API_TOKEN`.

Before the first tag, run this workflow with `workflow_dispatch` and `publish`
unchecked to validate every build target without publishing artifacts.

## Verification

After publishing artifacts:

```sh
cz version -p
lintel check --format json
lintel version --check
```

Run the installed CLI against each example project and confirm all checks
return `[]`.
