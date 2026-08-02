# Quadstick Display MVC Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-file application with a testable MVC package while preserving Raspberry Pi deployment and user-visible behavior.

**Architecture:** Incrementally extract the model, Pillow view, display controller, Flask adapter, and Waveshare adapter behind characterization tests. Keep `qs_display.py httpd` as a compatibility entrypoint.

**Tech Stack:** Python 3.10+, Flask, Pillow, Werkzeug, pytest, Poetry, standard-library `csv`, dataclasses, pathlib, and threading.

## Global Constraints

- Preserve port `8080`, current routes, form fields, installer name, unit name, and installation path.
- Keep `resources/` adjacent to the application.
- Preserve 16 bindings for `ad_infinitum.csv` and 24 for `alan_wake_II.csv`.
- Sip points left; puff points right.
- Hardware access must be serialized.
- No ORM, form framework, MVC framework, or dependency-injection container.
- Do not commit unless explicitly requested.

---

## M0: Characterization Tests

**Files:** Modify `pyproject.toml`; create `tests/conftest.py`, `tests/characterization/test_profiles.py`, `tests/characterization/test_rendering.py`, and `tests/characterization/test_http.py`.

- [ ] Add pytest under `[tool.poetry.group.dev.dependencies]`.
- [ ] Add a fake e-paper display recording black/red frames.
- [ ] Characterize both sample profile names, ordered rows, duplicate bindings, and counts.
- [ ] Characterize command formatting, mouthpiece mappings, image dimensions, planes, overflow resizing, and arrow orientation.
- [ ] Characterize `GET /`, `POST /upload`, `POST /render`, form names, and redirects.
- [ ] Run `poetry run pytest -q tests/characterization`.
- [ ] Run `git diff --check`.

**Definition of done:** Characterization tests pass without production behavior changes.

**Graph:** Pass to `M1`; failure remains on `M0`.

---

## M1: Model Extraction

**Files:** Create `quadstick_display/__init__.py`, `quadstick_display/model.py`, and `tests/unit/test_model.py`; modify `.gitignore`.

**Interfaces:**

```python
@dataclass(frozen=True)
class Binding:
    command: str
    quadstick_input: str

@dataclass(frozen=True)
class Profile:
    name: str
    bindings: tuple[Binding, ...]

def parse_quadstick_csv(stream: TextIO) -> Profile: ...

class ProfileStore:
    def list_names(self) -> tuple[str, ...]: ...
    def load(self, name: str) -> Profile: ...
    def save_upload(self, filename: str, stream: BinaryIO) -> str: ...
```

- [ ] Remove the `quadstick_display/**` ignore rule.
- [ ] Write failing tests for both fixtures, malformed headers, missing mapping sections, unsafe paths, non-CSV files, and missing profiles.
- [ ] Add `InvalidProfile`, `InvalidProfileName`, and `ProfileNotFound`.
- [ ] Parse with `csv.reader`; locate `Output or Function`, read columns 0 and 2, and stop at `Preferences`.
- [ ] Preserve row order and duplicates.
- [ ] Reject absolute paths, parent traversal, directory separators, and non-CSV suffixes.
- [ ] Run `poetry run pytest -q tests/unit/test_model.py tests/characterization`.

**Definition of done:** Model code imports neither Flask, Pillow, pandas, nor hardware modules; fixture parity and error behavior pass.

**Graph:** Pass to `M2`; failure remains on `M1`.

---

## M2: View and Hardware Extraction

**Files:** Create `quadstick_display/view.py`, `quadstick_display/hardware.py`, `quadstick_display/controller.py`, `tests/fakes.py`, `tests/unit/test_view.py`, and `tests/unit/test_hardware.py`.

**Interfaces:**

```python
@dataclass(frozen=True)
class DisplaySize:
    width: int
    height: int

@dataclass(frozen=True)
class DisplayFrame:
    black: Image.Image
    red: Image.Image

class ProfileRenderer:
    def render(self, profile: Profile, size: DisplaySize) -> DisplayFrame: ...
    def render_startup(self, url: str, size: DisplaySize) -> DisplayFrame: ...

class DisplayDevice(Protocol):
    @property
    def size(self) -> DisplaySize: ...
    def initialize(self) -> None: ...
    def show(self, frame: DisplayFrame) -> None: ...
```

- [ ] Write failing renderer tests for planes, dimensions, separators, overflow, text fallback, soft actions, and all mouthpiece mappings.
- [ ] Move formatting and Pillow drawing into `ProfileRenderer`.
- [ ] Rename the fourth mouthpiece bit to `is_puff`; preserve the tested visual direction.
- [ ] Implement `WaveshareDisplay` with a lazy Waveshare import.
- [ ] Preserve `width = epd.height` and `height = epd.width`.
- [ ] Ensure importing `quadstick_display.view` and `quadstick_display.controller` works without Raspberry Pi packages.
- [ ] Run `poetry run pytest -q tests/unit/test_view.py tests/unit/test_hardware.py tests/characterization`.

**Definition of done:** Rendering is hardware-independent; only `hardware.py` imports Waveshare; all image invariants pass.

**Graph:** Pass to `M3`; failure remains on `M2`.

---

## M3: Display Controller

**Files:** Complete `quadstick_display/controller.py`; create `tests/unit/test_controller.py`; temporarily modify `qs_display.py` to delegate rendering synchronously.

**Interfaces:**

```python
@dataclass(frozen=True)
class DisplayStatus:
    current_profile: str | None
    last_error: str | None

class DisplayFailure(RuntimeError): ...

class DisplayController:
    @property
    def status(self) -> DisplayStatus: ...
    def show_profile(self, name: str) -> DisplayStatus: ...
```

- [ ] Test successful state updates and preservation of the previous profile after parser or display failure.
- [ ] Test two concurrent requests with a blocking fake display and assert maximum concurrent writes is one.
- [ ] Lock the complete load-render-show-state transaction.
- [ ] Wrap hardware errors as `DisplayFailure` while retaining exception chaining.
- [ ] Replace `HttpMenu`'s async render path with synchronous controller delegation.
- [ ] Remove `asyncio`, `render_csv()`, and event-loop state.
- [ ] Run `poetry run pytest -q tests/unit/test_controller.py tests/characterization`.

**Definition of done:** Display writes are atomic and serialized; failed writes do not change the current profile; no asynchronous route code remains.

**Graph:** Pass to `M4`; failure remains on `M3`.

---

## M4: Flask MVC Shell

**Files:** Create `quadstick_display/web.py` and `quadstick_display/__main__.py`; replace `quadstick_display/__init__.py`; reduce `qs_display.py` to a shim; update `resources/templates/index.html`; create `tests/integration/test_web.py`.

**Factory:**

```python
def create_app(
    config: Mapping[str, object] | None = None,
    *,
    display: DisplayDevice,
) -> Flask: ...
```

**Default configuration:**

```python
PROFILE_DIR = resources / "quadstick_csvs"
RESOURCE_DIR = resources
MAX_CONTENT_LENGTH = 2 * 1024 * 1024
```

- [ ] Test factory creation with no hardware initialization.
- [ ] Test profile listing, selected status, upload, render, redirects, and empty state.
- [ ] Test `400`, `404`, `413`, `422`, and `503` responses from the approved error mapping.
- [ ] Implement one Blueprint and keep `/`, `/upload`, `/render`, and `/uploads/<filename>`.
- [ ] Use `url_for` in the template.
- [ ] Keep route handlers limited to HTTP translation and controller/store calls.
- [ ] Put hardware initialization, startup-screen rendering, and `app.run()` in `__main__.py`.
- [ ] Make root `qs_display.py` delegate to `quadstick_display.__main__.main()` while accepting `httpd`.
- [ ] Remove the legacy classes after characterization tests target the package interfaces.
- [ ] Run `poetry run pytest -q`.

**Definition of done:** The production entrypoint uses the MVC package; all routes are covered by Flask's test client; test app creation has no Pi side effects.

**Graph:** Pass to `M5`; failure remains on `M4`.

---

## M5: Dependencies, Packaging, CI, and Documentation

**Files:** Modify `pyproject.toml`, `.gitignore`, `.github/workflows/main.yml`, installer scripts, `README.md`, and `AGENTS.md`; create `scripts/build_installer.sh`, `.github/workflows/verify.yml`, `.github/workflows/release.yml`, and `poetry.lock`.

- [ ] Remove pandas, `flask-uploads`, and Flask's async extra after confirming no imports remain.
- [ ] Keep direct Werkzeug, Pillow, Flask, and hardware dependencies.
- [ ] Configure Poetry to include `quadstick_display`.
- [ ] Stop ignoring `poetry.lock` and generate it.
- [ ] Move package assembly into `scripts/build_installer.sh`.
- [ ] Include `quadstick_display/`, `qs_display.py`, resources, requirements, launcher, and unit files explicitly.
- [ ] Replace hard-coded directory counts with required-path and ZIP-integrity checks.
- [ ] Install `poetry-plugin-export` explicitly in CI.
- [ ] Run tests and packaging on pull requests with read-only permissions.
- [ ] Publish only from an explicit `v*` tag workflow.
- [ ] Make installer prerequisites fail fast and ensure reinstall does not prompt or remove custom CSVs.
- [ ] Document local commands, architecture, package flow, and hardware-only acceptance in `README.md` and `AGENTS.md`.
- [ ] Run the complete verification block:

```bash
poetry check
poetry install --with dev --no-interaction
poetry run pytest -q
python -m compileall -q quadstick_display qs_display.py
bash -n scripts/build_installer.sh resources/install/*.sh
scripts/build_installer.sh
unzip -t dist/quadstick-display.zip
git diff --check
```

**Definition of done:** A clean installation passes tests; artifacts contain every module and resource; the legacy command works; PR validation cannot publish; dependency export is reproducible.

**Graph:** Pass to `M6`; failure remains on `M5`.

---

## M6: Raspberry Pi Acceptance

**Targets:** Raspberry Pi Zero W 32-bit and Raspberry Pi Zero 2 W 64-bit.

- [ ] Test fresh installation from the generated self-extracting installer.
- [ ] Test reinstall and upgrade with a custom uploaded CSV already present.
- [ ] Reboot and verify:

```bash
sudo systemctl is-enabled qs_display_httpd.service
sudo systemctl is-active qs_display_httpd.service
curl -fsS http://127.0.0.1:8080/
sudo journalctl -u qs_display_httpd.service -b --no-pager
```

- [ ] Render both bundled profiles and compare black/red output and arrow orientation with reference photographs.
- [ ] Submit concurrent render requests and confirm serialized, uncorrupted updates.
- [ ] Record OS image, architecture, Python version, install duration, and package footprint.

**Definition of done:** Both supported targets pass fresh install, upgrade, reboot, HTTP, physical rendering, and concurrency checks while preserving custom CSVs.

**Graph:** Pass to `COMPLETE`; unavailable hardware reports `BLOCKED` with `next: STOP`.

## Report Contract

```yaml
milestone: M0
status: DONE | FAILED | BLOCKED
evidence:
  - exact command and result
changes:
  - exact paths
blockers: none
next: M1
```

Only report `DONE` when the milestone's full definition of done has fresh evidence. Report `FAILED` with the same milestone as `next`. Report `BLOCKED` with `next: STOP`.
