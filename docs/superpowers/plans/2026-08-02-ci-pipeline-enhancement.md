# CI Pipeline Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the GitHub Actions pipeline around one reusable verify workflow with full check coverage (ruff, matrix tests, packaging), Poetry caching, and a polished release path.

**Architecture:** A single reusable workflow `_verify.yml` (`workflow_call`) defines the whole verify block — `static-checks` → `tests` (3.10–3.12 matrix) → `package` — called by `verify.yml` (PRs/pushes, `contents: read`) and `release.yml` (`v*` tags), which adds a publish job consuming the packaged artifact. Ruff is adopted repo-wide first so the new lint/format gates pass.

**Tech Stack:** GitHub Actions (reusable workflows, matrix, artifacts, concurrency), Poetry + pipx, ruff, `gh` CLI, GNU make.

**Spec:** `docs/superpowers/specs/2026-08-02-ci-pipeline-enhancement-design.md`

## Global Constraints

- Verify workflow triggers: `pull_request` + `push` with `tags-ignore: ['v*']` — unchanged.
- Release workflow trigger: `push` with `tags: ['v*']` — unchanged.
- Permissions: verify workflow stays `contents: read` (it must structurally not publish); only the release job gets `contents: write`.
- Artifact contract: name `shell-installer`, paths `dist/quadstick-display.sh` and `dist/3d_case.zip`, `retention-days: 7`.
- Release contract: attaches `dist/quadstick-display.sh` only, title `Quadstick Display <tag>`, `--generate-notes`, `--prerelease` iff the tag contains a hyphen.
- Python matrix exactly `['3.10', '3.11', '3.12']` with `fail-fast: false`; `static-checks` and `package` run on `'3.12'`.
- Every job that runs `poetry install` uses `actions/setup-python@v5` with `cache: 'poetry'`.
- Concurrency: verify `cancel-in-progress: true`; release `cancel-in-progress: false`.
- Ruff: `target-version = "py310"`, default rules and line length; gate commands are `ruff check .` and `ruff format --check .`.
- Do not touch shipped contracts: port 8080, routes, installer filename, `qs_display_httpd.service` unit name, `/usr/local/quadstick-display` path, CSV persistence.
- **Every `git commit` / `git push` step requires the user's explicit confirmation immediately before running it. Do not commit autonomously.**

---

### Task 1: Adopt ruff repo-wide

**Files:**
- Modify: `pyproject.toml` (dev deps + `[tool.ruff]` section)
- Modify: `poetry.lock` (via `poetry add`)
- Modify: any Python files ruff flags under `quadstick_display/`, `tests/`, `qs_display.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `poetry run ruff check .` and `poetry run ruff format --check .` both exit 0 — required by Tasks 2 and 3.

- [ ] **Step 1: Add ruff to the dev dependency group**

```bash
poetry add --group dev ruff
```

Expected: `pyproject.toml` gains a `ruff = "^<version>"` line under `[tool.poetry.group.dev.dependencies]`; `poetry.lock` updates.

- [ ] **Step 2: Add minimal ruff configuration**

Append to `pyproject.toml`:

```toml
[tool.ruff]
target-version = "py310"
```

- [ ] **Step 3: Auto-fix lint violations and reformat**

```bash
poetry run ruff check --fix .
poetry run ruff format .
```

Expected: ruff rewrites files in place and prints a summary of fixed/remaining issues.

- [ ] **Step 4: Manually fix any remaining violations**

```bash
poetry run ruff check .
```

For each remaining violation: fix the code directly (e.g. remove an unused import, bind an unused variable to `_`), or — only if the violation is intentional — add a targeted `# noqa: <CODE>` comment with a one-line justification. Do not broaden the rule ignore list in `pyproject.toml`.

- [ ] **Step 5: Verify lint, format, and the full test suite are green**

```bash
poetry run ruff check .
poetry run ruff format --check .
poetry run pytest -q
```

Expected: all three exit 0; test count unchanged from before the reformat.

- [ ] **Step 6: Commit (ask user for confirmation first)**

```bash
git add pyproject.toml poetry.lock quadstick_display tests qs_display.py
git commit -m "chore: adopt ruff lint and format repo-wide"
```

---

### Task 2: Wire ruff into the Makefile

**Files:**
- Modify: `Makefile` (`check` target, `.PHONY`, new `format` target)

**Interfaces:**
- Consumes: Task 1's green ruff state (`poetry run ruff check .` exits 0).
- Produces: `make check` runs ruff gates; `make format` auto-fixes. CI (Task 3) mirrors these exact commands.

- [ ] **Step 1: Update the `check` target and add `format`**

In `Makefile`, replace the `check` target block (lines 44-47):

```make
check: install ## Run poetry check, bytecode compilation, and shell syntax checks
	$(POETRY) check
	$(PYTHON) -m compileall -q quadstick_display qs_display.py
	bash -n scripts/build_installer.sh resources/install/*.sh
```

with:

```make
check: install ## Run poetry check, ruff lint/format checks, bytecode compilation, and shell syntax checks
	$(POETRY) check
	$(POETRY) run ruff check .
	$(POETRY) run ruff format --check .
	$(PYTHON) -m compileall -q quadstick_display qs_display.py
	bash -n scripts/build_installer.sh resources/install/*.sh

format: install ## Auto-fix ruff lint violations and reformat the codebase
	$(POETRY) run ruff check --fix .
	$(POETRY) run ruff format .
```

And update `.PHONY` (line 14) from:

```make
.PHONY: help install install-export-plugin check \
        test test-unit test-integration test-characterization \
        build verify clean
```

to:

```make
.PHONY: help install install-export-plugin check format \
        test test-unit test-integration test-characterization \
        build verify clean
```

- [ ] **Step 2: Verify the targets**

```bash
make check
make help
```

Expected: `make check` exits 0 (ruff steps included); `make help` lists `check` and `format` with their descriptions.

- [ ] **Step 3: Commit (ask user for confirmation first)**

```bash
git add Makefile
git commit -m "build: add ruff lint/format gates to make check, add make format"
```

---

### Task 3: Create the reusable verify workflow

**Files:**
- Create: `.github/workflows/_verify.yml`

**Interfaces:**
- Consumes: Task 2's `make check` command set (mirrored as CI steps).
- Produces: reusable workflow referenced by Tasks 4 and 5 as `./.github/workflows/_verify.yml`; artifact `shell-installer` consumed by Task 5's release job.

- [ ] **Step 1: Write `.github/workflows/_verify.yml`**

```yaml
# Custom app to Display Quadstick key settings on an e-ink display
# 2024 felipe.dos.santos

name: "Verify Quadstick Display (reusable)"

on:
  workflow_call:

permissions:
  contents: read

env:
  APP_NAME: "quadstick-display"

jobs:
  static-checks:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Install Poetry
        run: pipx install poetry

      - name: Install the Poetry export plugin
        run: pipx inject poetry poetry-plugin-export

      - name: Set up Python environment
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'poetry'

      - name: Install dependencies
        run: poetry install --with dev --no-interaction

      - name: Check Poetry project configuration
        run: poetry check

      - name: Lint with ruff
        run: poetry run ruff check .

      - name: Check formatting with ruff
        run: poetry run ruff format --check .

      - name: Bytecode-compile the application
        run: poetry run python -m compileall -q quadstick_display qs_display.py

      - name: Syntax-check shell scripts
        run: bash -n scripts/build_installer.sh resources/install/*.sh

      - name: Check for whitespace errors
        if: github.event_name == 'pull_request'
        run: git diff --check ${{ github.event.pull_request.base.sha }}...HEAD

  tests:
    needs: static-checks
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ['3.10', '3.11', '3.12']
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Install Poetry
        run: pipx install poetry

      - name: Install the Poetry export plugin
        run: pipx inject poetry poetry-plugin-export

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: 'poetry'

      - name: Install dependencies
        run: poetry install --with dev --no-interaction

      - name: Run tests
        run: poetry run pytest -q

  package:
    needs: tests
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Install Poetry
        run: pipx install poetry

      - name: Install the Poetry export plugin
        run: pipx inject poetry poetry-plugin-export

      - name: Set up Python environment
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'poetry'

      - name: Build the installer package
        run: scripts/build_installer.sh

      - name: Verify the installer archive integrity
        run: unzip -t dist/${{ env.APP_NAME }}.zip

      - name: Upload the installer artifacts
        uses: actions/upload-artifact@v4
        with:
          name: shell-installer
          retention-days: 7
          path: |
            ./dist/${{ env.APP_NAME }}.sh
            ./dist/3d_case.zip
```

Note: Poetry is installed *before* `setup-python` so the `cache: 'poetry'`
lookup can resolve Poetry's cache directory (documented setup-python order).

- [ ] **Step 2: Validate the YAML parses**

```bash
ruby -ryaml -e 'YAML.load_file(".github/workflows/_verify.yml"); puts "OK"'
```

Expected: `OK`. (If `actionlint` is installed, run `actionlint .github/workflows/_verify.yml` too and expect no findings.)

- [ ] **Step 3: Commit (ask user for confirmation first)**

```bash
git add .github/workflows/_verify.yml
git commit -m "ci: add reusable verify workflow with ruff gates, 3.10-3.12 matrix, and cached Poetry"
```

---

### Task 4: Slim `verify.yml` down to a thin caller

**Files:**
- Modify: `.github/workflows/verify.yml` (full rewrite)

**Interfaces:**
- Consumes: Task 3's `_verify.yml`.
- Produces: the everyday CI entry point; must contain no publish-capable permissions.

- [ ] **Step 1: Rewrite `.github/workflows/verify.yml`**

Replace the entire file with:

```yaml
# Custom app to Display Quadstick key settings on an e-ink display
# 2024 felipe.dos.santos

name: "Verify Quadstick Display"

on:
  pull_request:
  push:
    tags-ignore:
      - 'v*'

permissions:
  contents: read

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  verify:
    uses: ./.github/workflows/_verify.yml
```

- [ ] **Step 2: Validate the YAML parses**

```bash
ruby -ryaml -e 'YAML.load_file(".github/workflows/verify.yml"); puts "OK"'
```

Expected: `OK`.

- [ ] **Step 3: Commit (ask user for confirmation first)**

```bash
git add .github/workflows/verify.yml
git commit -m "ci: make verify workflow a thin caller of the reusable workflow"
```

---

### Task 5: Rebuild `release.yml` as caller + publish job

**Files:**
- Modify: `.github/workflows/release.yml` (full rewrite)

**Interfaces:**
- Consumes: Task 3's `_verify.yml`; the `shell-installer` artifact uploaded by its `package` job (artifacts from a called reusable workflow live in the same run and are downloadable by the caller's later jobs).
- Produces: the release entry point; publishes `dist/quadstick-display.sh`.

- [ ] **Step 1: Rewrite `.github/workflows/release.yml`**

Replace the entire file with:

```yaml
# Custom app to Display Quadstick key settings on an e-ink display
# 2024 felipe.dos.santos

name: "Release Quadstick Display"

on:
  push:
    tags:
      - 'v*'

permissions:
  contents: read

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: false

env:
  APP_NAME: "quadstick-display"

jobs:
  verify:
    uses: ./.github/workflows/_verify.yml

  release:
    needs: verify
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Check the tag matches the project version
        run: |
          project_version="$(grep -m1 '^version = ' pyproject.toml | cut -d'"' -f2)"
          tag_version="${GITHUB_REF_NAME#v}"
          if [ "$project_version" != "$tag_version" ]; then
            echo "Error: tag $GITHUB_REF_NAME does not match pyproject.toml version $project_version" >&2
            exit 1
          fi

      - name: Download the installer artifacts
        uses: actions/download-artifact@v4
        with:
          name: shell-installer
          path: dist

      - name: Mark prerelease tags
        if: contains(github.ref_name, '-')
        run: echo "PRERELEASE_FLAG=--prerelease" >> "$GITHUB_ENV"

      - name: Create GitHub Release
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: >-
          gh release create "${{ github.ref_name }}"
          --generate-notes
          --title "Quadstick Display ${{ github.ref_name }}"
          ${PRERELEASE_FLAG}
          "./dist/${{ env.APP_NAME }}.sh"
```

- [ ] **Step 2: Validate the YAML parses**

```bash
ruby -ryaml -e 'YAML.load_file(".github/workflows/release.yml"); puts "OK"'
```

Expected: `OK`.

- [ ] **Step 3: Sanity-check the version-extraction shell logic locally**

```bash
grep -m1 '^version = ' pyproject.toml | cut -d'"' -f2
```

Expected: prints exactly the project version (e.g. `0.1.0`) with no quotes or whitespace.

- [ ] **Step 4: Commit (ask user for confirmation first)**

```bash
git add .github/workflows/release.yml
git commit -m "ci: rebuild release workflow on reusable verify, auto notes, version check, prereleases"
```

---

### Task 6: Add Dependabot for GitHub Actions

**Files:**
- Create: `.github/dependabot.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: weekly PRs bumping action versions (e.g. `actions/checkout`).

- [ ] **Step 1: Write `.github/dependabot.yml`**

```yaml
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

- [ ] **Step 2: Validate the YAML parses**

```bash
ruby -ryaml -e 'YAML.load_file(".github/dependabot.yml"); puts "OK"'
```

Expected: `OK`.

- [ ] **Step 3: Commit (ask user for confirmation first)**

```bash
git add .github/dependabot.yml
git commit -m "ci: add dependabot for github-actions updates"
```

---

### Task 7: Sync AGENTS.md with the new pipeline

**Files:**
- Modify: `AGENTS.md` ("Make targets", "Verified local commands", "CI" sections)

**Interfaces:**
- Consumes: Tasks 1-6 as implemented reality.
- Produces: documentation that matches the repo; required by the AGENTS.md maintenance rule.

- [ ] **Step 1: Update the "Make targets" paragraph**

In `AGENTS.md`, change the target list from:

```
the targets (`make install`, `make check`, `make test`, `make build`,
`make verify`, `make clean`). `make verify` runs the full CI-equivalent block
(static checks, the test suite, packaging, and `git diff --check`).
```

to:

```
the targets (`make install`, `make check`, `make format`, `make test`,
`make build`, `make verify`, `make clean`). `make verify` runs the full
CI-equivalent block (static checks including ruff, the test suite, packaging,
and `git diff --check`).
```

- [ ] **Step 2: Update the "Verified local commands" block**

In `AGENTS.md`, change:

```bash
poetry check
poetry install --with dev --no-interaction
poetry run pytest -q
```

to:

```bash
poetry check
poetry install --with dev --no-interaction
poetry run ruff check .
poetry run ruff format --check .
poetry run pytest -q
```

- [ ] **Step 3: Rewrite the "CI" section**

In `AGENTS.md`, replace:

```
- `.github/workflows/verify.yml` — pull requests and non-tag pushes run tests
  and packaging with `contents: read`; it cannot publish.
- `.github/workflows/release.yml` — `v*` tag pushes run the same checks and
  create the GitHub release with `quadstick-display.sh` attached.
```

with:

```
- `.github/workflows/_verify.yml` — reusable workflow (`workflow_call`)
  holding the whole verify block: `static-checks` (poetry check, ruff lint +
  format, compileall, shell syntax, PR whitespace check), `tests` (Python
  3.10/3.11/3.12 matrix, fail-fast off), and `package` (installer build +
  `shell-installer` artifact). Jobs cache Poetry dependencies via
  `actions/setup-python` (`cache: 'poetry'`).
- `.github/workflows/verify.yml` — pull requests and non-tag pushes call the
  reusable verify workflow with `contents: read`; it cannot publish.
- `.github/workflows/release.yml` — `v*` tag pushes call the reusable verify
  workflow, then a `contents: write` job checks the tag matches the
  pyproject version and creates the GitHub release with auto-generated
  notes (`--prerelease` for hyphenated tags) and `quadstick-display.sh`
  attached.
```

- [ ] **Step 4: Commit (ask user for confirmation first)**

```bash
git add AGENTS.md
git commit -m "docs: sync AGENTS.md with the rebuilt CI pipeline"
```

---

### Task 8: Final local verification and PR proof

**Files:**
- None modified; verification only.

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Run the full local verification block**

```bash
make verify
```

Expected: `Verification complete.` — check (incl. ruff), test, build, and `git diff --check` all pass.

- [ ] **Step 2: Parse every workflow file**

```bash
for f in .github/workflows/_verify.yml .github/workflows/verify.yml .github/workflows/release.yml .github/dependabot.yml; do
  ruby -ryaml -e "YAML.load_file('$f'); puts \"OK $f\""
done
```

Expected: four `OK` lines.

- [ ] **Step 3: Cross-check CI↔local parity by eye**

Confirm every command in `make check`/`make test`/`make build` appears as a step in `.github/workflows/_verify.yml` (ruff check, ruff format --check, poetry check, compileall, bash -n, pytest, build_installer.sh, unzip -t) — the only intentional differences are `git diff --check` (CI runs it against the PR base; locally it checks the working tree) and the artifact upload (CI-only).

- [ ] **Step 4: Push the branch and open a PR to prove the verify path (ask user for confirmation first)**

```bash
git push -u origin <branch>
gh pr create --fill
```

Expected: the "Verify Quadstick Display" workflow runs on the PR with three jobs (`static-checks`, `tests` ×3, `package`) all green; the `shell-installer` artifact appears on the run. The release path is validated statically only — it runs on the next real `v*` tag.

---

## Self-Review Results

- **Spec coverage:** caching (Tasks 3/4/5 — setup-python `cache: 'poetry'` everywhere), check coverage (Task 3 static-checks), ruff check+format (Tasks 1/2/3), matrix 3.10–3.12 (Task 3), dedup via reusable workflow (Tasks 3/4/5), release polish — auto notes, version check, prerelease (Task 5), dependabot (Task 6), AGENTS.md sync (Task 7), validation + PR proof (Task 8). All spec sections covered.
- **Placeholder scan:** none — every file's full content is in the plan; Task 1 Step 4's manual fixes are inherently unknown until ruff runs and carry concrete disposition rules.
- **Type/name consistency:** workflow filename `_verify.yml`, artifact name `shell-installer`, make targets `check`/`format`, and env var `APP_NAME` are spelled identically across all tasks and in AGENTS.md.
