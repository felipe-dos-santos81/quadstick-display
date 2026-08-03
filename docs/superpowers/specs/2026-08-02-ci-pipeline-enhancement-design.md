# Enhanced CI/CD Pipeline — Design

**Date:** 2026-08-02
**Status:** Approved by user, pending implementation

## Context

Current state of `.github/workflows/`:

- `verify.yml` — on PRs and non-tag pushes: install Poetry → `pytest` → build
  installer → `unzip -t` → upload artifact. `permissions: contents: read`.
- `release.yml` — on `v*` tags: the same steps, then
  `gh release create --notes-file README.md` attaching
  `dist/quadstick-display.sh`.

Pain points:

1. CI runs only a subset of the local `make verify` block — `poetry check`,
   `python -m compileall`, `bash -n` on shell scripts, and `git diff --check`
   run locally but not in CI. AGENTS.md claims they mirror each other; today
   they do not.
2. `verify.yml` and `release.yml` duplicate ~90% of their steps.
3. No dependency caching — every run re-downloads all wheels and re-clones
   the `waveshare-epd` git dependency.
4. No lint/format tooling anywhere (dev dependencies contain only `pytest`).
5. Release notes are the entire README dumped into every release; no check
   that the tag matches `pyproject.toml` version; no prerelease handling.
6. No concurrency control — rapid pushes pile up redundant runs.

## Goals

Decided through user interview:

- **Speed via caching** — cache Poetry dependencies keyed on `poetry.lock`.
- **Check coverage** — CI runs the full local `make verify` block (and more).
- **Deduplicate workflows** — one shared definition of the verify block.
- **Release polish** — auto-generated notes, tag/version consistency check,
  prerelease handling.
- **Ruff check + format** — enforced in CI and locally.
- **Python matrix** — test 3.10 (supported floor), 3.11 (Pi bookworm target),
  3.12 (current).
- **Structure: reusable workflow** (chosen over single-workflow-with-
  conditional-release and composite-action alternatives).

## Design

### Workflow architecture

Three workflow files; the verify block is defined exactly once.

**`.github/workflows/_verify.yml`** — reusable workflow (`on: workflow_call`),
three jobs:

1. `static-checks` (ubuntu-latest, Python 3.12):
   - checkout (`fetch-depth: 0`, needed for the PR whitespace check)
   - `actions/setup-python@v5` with `cache: 'poetry'`
   - `pipx install poetry` + `pipx inject poetry poetry-plugin-export`
   - `poetry install --with dev --no-interaction`
   - `poetry check`
   - `poetry run ruff check .`
   - `poetry run ruff format --check .`
   - `python -m compileall -q quadstick_display qs_display.py` (via
     `poetry run`)
   - `bash -n scripts/build_installer.sh resources/install/*.sh`
   - `git diff --check <base>...HEAD` — `pull_request` events only, against
     the PR base SHA
2. `tests` (`needs: static-checks`; matrix Python 3.10/3.11/3.12,
   `fail-fast: false`):
   - checkout → setup-python (with cache) → pipx poetry + export plugin →
     `poetry install --with dev --no-interaction` → `poetry run pytest -q`
3. `package` (`needs: tests`):
   - same setup → `scripts/build_installer.sh` →
     `unzip -t dist/quadstick-display.zip`
   - `actions/upload-artifact@v4` named `shell-installer` (name unchanged)
     with `dist/quadstick-display.sh` + `dist/3d_case.zip`,
     `retention-days: 7`

**`.github/workflows/verify.yml`** — on PRs and non-tag pushes;
`permissions: contents: read`; a single job that calls `_verify.yml`. The
"cannot publish" guarantee stays structural: no job in this workflow holds
write permissions.

**`.github/workflows/release.yml`** — on `v*` tags:

1. `verify` job — calls `_verify.yml` (`permissions: contents: read`).
2. `release` job (`needs: verify`, `permissions: contents: write`):
   - checkout
   - tag/version consistency check: fail unless the version in
     `pyproject.toml` equals the tag name with the leading `v` stripped
     (plain `grep`/`cut`, no Poetry needed)
   - download the `shell-installer` artifact into `dist/`
   - `gh release create` with `--generate-notes` (replaces
     `--notes-file README.md`), title `Quadstick Display <tag>`, attaching
     `dist/quadstick-display.sh` (shipped contract — unchanged)
   - tags containing a hyphen (e.g. `v1.0.0-rc.1`) are created with
     `--prerelease`

The installer is built once in `package` and flows to the release via the
artifact — never rebuilt.

### Caching and concurrency

- Every job that installs dependencies uses `actions/setup-python@v5` with
  `cache: 'poetry'`, which caches Poetry's cache directory keyed on the
  `poetry.lock` hash. Repeat runs skip wheel downloads (including the
  `waveshare-epd` git clone).
- Poetry itself is installed via `pipx` in each job (fast, no extra action
  dependency).
- `verify.yml`: `concurrency` group keyed on workflow + ref,
  `cancel-in-progress: true`.
- `release.yml`: `concurrency` group keyed on workflow + ref,
  `cancel-in-progress: false` — never cancel a publish mid-flight.

### Ruff adoption

- Add `ruff` to `[tool.poetry.group.dev.dependencies]`.
- Minimal config in `pyproject.toml`: `[tool.ruff] target-version = "py310"`,
  default rule set and line length.
- One-time mechanical pass: `ruff check --fix .` + `ruff format .` across the
  codebase as its own commit; manually fix anything not auto-fixable.
- Makefile: `check` gains `ruff check .` and `ruff format --check .`; new
  `format` target runs `ruff check --fix .` + `ruff format .`. Local
  `make verify` remains a true mirror of CI.

### Maintenance

- `.github/dependabot.yml`: weekly version updates for the `github-actions`
  ecosystem.

### Documentation

- Update AGENTS.md: CI section describes the new three-file layout and job
  split; "Verified local commands" gains the ruff invocations.

### Failure semantics

- Job chain `static-checks` → `tests` → `package` via `needs:`; a lint
  failure does not burn three matrix jobs.
- Matrix runs with `fail-fast: false` so one failing Python version does not
  hide the results of the others.
- The release publishes only when the whole verify block passes.

## Validation

- YAML parse of all workflow files locally (`python -c "yaml.safe_load"` per
  file, or `actionlint` if available).
- `make verify` passes locally after the ruff adoption.
- The verify path is proven by opening a PR and watching it run.
- The release path cannot be exercised without pushing a real tag; it is
  validated by static review and proven on the next release (optionally a
  throwaway prerelease tag, deleted afterward, at the user's discretion).

## Out of scope (YAGNI)

- SHA-pinning actions (Dependabot covers version drift).
- Test coverage reporting, Docker builds, hardware-in-the-loop tests.
- Curated `CHANGELOG.md`-driven release notes.
