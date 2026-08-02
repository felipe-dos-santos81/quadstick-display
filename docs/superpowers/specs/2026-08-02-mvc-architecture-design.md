# MVC Architecture Design

## Goal

Restructure the single-file application into a compact MVC package that separates domain logic, rendering, HTTP handling, and Raspberry Pi hardware access. Preserve deployed behavior while making each layer reusable and testable without physical hardware.

## Assumptions

- Preserve port `8080`, current routes and form fields, QuadStick CSV semantics, two-plane e-paper output, installer filename, systemd unit, and `/usr/local/quadstick-display` installation root.
- Keep `python qs_display.py httpd` as a compatibility entrypoint because the shipped service invokes it.
- Continue supporting Raspberry Pi Zero W 32-bit and Raspberry Pi Zero 2 W 64-bit while both remain documented.
- Treat path traversal, unsafe uploads, render races, and hidden render failures as defects rather than compatibility requirements.
- Keep rendering synchronous and serialize access to the single physical display.
- Keep the existing `resources/` tree during this restructuring; asset relocation is not required for MVC separation.

## Decision

Use incremental extraction behind characterization tests. A big-bang rewrite is too risky without an existing test suite or routine hardware access. A class-per-file split is also rejected because it would create shallow pass-through modules without improving reuse.

The design follows Flask's documented application-factory and Blueprint patterns. Flask's documented pytest fixtures and test client provide route, upload, and redirect coverage without starting a live server. Documentation was verified through Context7 using `/pallets/flask/3_1_1`.

## Target Structure

```text
quadstick_display/
  __init__.py       # Exposes create_app
  model.py          # Profile, Binding, parser, and ProfileStore
  view.py           # Pillow rendering and DisplayFrame
  controller.py     # Render transaction, state, locking, and display interface
  web.py            # Blueprint and HTTP request handlers
  hardware.py       # WaveshareDisplay adapter
  __main__.py       # Production composition and server startup
qs_display.py       # Compatibility entrypoint
resources/          # Existing templates, fonts, images, and CSVs
tests/
  characterization/
  unit/
  integration/
```

The existing `.gitignore` entry for `quadstick_display/**` must be removed when the package is introduced.

## Module Interfaces

### Model

`model.py` owns the domain representation, explicit CSV parsing, normalization, and safe filesystem access.

```python
ProfileStore.list_names() -> tuple[str, ...]
ProfileStore.load(name: str) -> Profile
ProfileStore.save_upload(filename: str, stream: BinaryIO) -> str
parse_quadstick_csv(stream: TextIO) -> Profile
```

`Profile` and `Binding` are immutable. Parsing uses the standard-library `csv` module and preserves profile name, binding order, duplicate bindings, and the `Preferences` boundary. The model has no Flask, Pillow, pandas, or hardware imports.

### View

`view.py` owns both startup and profile rendering. It returns data instead of touching hardware.

```python
ProfileRenderer.render(profile: Profile, size: DisplaySize) -> DisplayFrame
ProfileRenderer.render_startup(url: str, size: DisplaySize) -> DisplayFrame
```

`DisplayFrame` contains the black and red monochrome Pillow images. Rendering preserves the current display dimension swap, overflow behavior, included fonts, and the documented left-arrow sip and right-arrow puff meanings.

The Jinja template remains the HTTP view. It uses `url_for`, displays current status and actionable errors, and handles empty profile lists without exposing model or hardware details.

### Controller

`controller.py` owns the complete display transaction and current display state.

```python
DisplayController.show_profile(name: str) -> DisplayStatus
DisplayController.status -> DisplayStatus
```

`show_profile` validates the name through `ProfileStore`, loads and renders the profile, writes the frame through `DisplayDevice`, and updates status only after successful hardware output. A lock surrounds the full transaction so concurrent requests cannot interleave panel writes.

The display seam is intentionally small:

```python
class DisplayDevice(Protocol):
    @property
    def size(self) -> DisplaySize: ...
    def initialize(self) -> None: ...
    def show(self, frame: DisplayFrame) -> None: ...
```

Production uses `WaveshareDisplay`; tests use a recording or failing adapter. Only `hardware.py` imports `waveshare_epd`.

### Web And Composition

`web.py` defines one Blueprint. Its handlers translate request data, call the model or controller, and translate known errors into HTTP responses. They do not parse CSV files, draw images, create hardware, or own mutable display state.

`create_app(config=None, *, display: DisplayDevice) -> Flask` configures paths, upload limits, the store, renderer, controller, and Blueprint. Creating a test app must not initialize Waveshare hardware.

`__main__.py` is the production composition root. It initializes the Waveshare adapter, renders the startup screen, constructs the Flask application, and starts the server. The root `qs_display.py` delegates to this module and retains the legacy `httpd` argument.

## Error Semantics

- Unknown or unsafe profile names are rejected before filesystem access.
- Invalid QuadStick files return a model validation error and do not change display status.
- Hardware failures preserve the previously successful profile and are visible in logs and the HTTP view.
- Uploads accept only sanitized `.csv` filenames and obey `MAX_CONTENT_LENGTH`.
- Successful uploads retain the `/uploads/<filename>` redirect and successful renders redirect to `/`.
- Unsafe or invalid requests return `400`, missing profiles return `404`, invalid CSV content returns `422`, oversized uploads return `413`, and hardware failures return `503`. Error responses render the index view with an actionable message.

## Dependency Strategy

- Retain Flask, Werkzeug, Pillow, and the Waveshare/Raspberry Pi runtime dependencies until device acceptance proves they are valid.
- Replace pandas with `csv` after parser parity tests pass.
- Remove unused `flask-uploads` and Flask's async extra after the web handlers are synchronous.
- Add pytest as the only required test dependency for the restructuring.
- Commit `poetry.lock` for reproducible application builds.
- Install `poetry-plugin-export` explicitly anywhere `poetry export` is used.
- Do not add an ORM, MVC framework, form framework, dependency-injection container, or repository interface for the single filesystem implementation.

## Milestones

### M0: Characterization Safety Net

Capture sample CSV semantics, formatting, route contracts, image planes, dimensions, and sip/puff orientation with a fake display.

**Definition of done:** `ad_infinitum.csv` produces 16 ordered bindings and `alan_wake_II.csv` produces 24; both titles and duplicate bindings are preserved; HTTP and rendering invariants are covered; all characterization tests pass; production behavior is unchanged.

**Graph transition:** Pass to `M1`; otherwise remain on `M0` with failing evidence.

### M1: Model Extraction

Introduce immutable domain models, explicit standard-library CSV parsing, safe profile storage, and unit tests.

**Definition of done:** The model has no web, image, pandas, or hardware dependencies; valid fixtures retain semantic parity; malformed files and path traversal have explicit tested errors.

**Graph transition:** Pass to `M2`; otherwise remain on `M1`.

### M2: View And Hardware Extraction

Move Pillow rendering behind `ProfileRenderer` and hardware access behind `DisplayDevice`.

**Definition of done:** Rendering runs on non-Pi hosts; only the hardware adapter imports Waveshare; black/red planes, dimensions, overflow, and arrow orientation are tested.

**Graph transition:** Pass to `M3`; otherwise remain on `M2`.

### M3: Controller Extraction

Add the atomic, serialized display transaction and explicit status/error handling.

**Definition of done:** Concurrent renders are serialized; state changes only after successful display output; controller tests need neither Flask nor physical hardware; asynchronous route code is gone.

**Graph transition:** Pass to `M4`; otherwise remain on `M3`.

### M4: Flask MVC Shell

Replace `HttpMenu` with the application factory, Blueprint, dependency injection, and thin request handlers.

**Definition of done:** Flask test-client coverage includes listing, uploads, renders, redirects, validation, and hardware failures; creating a test app performs no hardware side effects; compatible routes and form fields remain available.

**Graph transition:** Pass to `M5`; otherwise remain on `M4`.

### M5: Packaging, Dependencies, And CI

Package every MVC module, retain the compatibility entrypoint, remove verified unused dependencies, make exports reproducible, and replace hard-coded artifact counts with explicit integrity checks. Run validation on pull requests and publish only from an explicit release action.

**Definition of done:** A clean environment installs and passes the full suite; the installer contains every required module and resource; the legacy invocation remains valid; PR validation cannot create releases; removed dependencies are no longer required.

**Graph transition:** Pass to `M6`; otherwise remain on `M5`.

### M6: Raspberry Pi Acceptance

Validate fresh install, reinstall, upgrade, reboot, service operation, uploads, physical output, and serialized rendering on the documented targets.

**Definition of done:** Custom CSVs survive upgrade; the service starts after reboot; both sample profiles render correctly on black/red planes; sip/puff orientation matches the reference; concurrent requests cannot corrupt output.

**Graph transition:** Pass to `COMPLETE`; unavailable hardware or unsupported images report `BLOCKED`, not complete.

## Agent Reporting

Every milestone reports the same graph payload:

```yaml
milestone: M0
status: DONE | FAILED | BLOCKED
evidence: commands and summarized results
changes: files changed
blockers: none or an explicit blocker
next: M1 | COMPLETE | STOP
```

An agent may report `DONE` only when every definition-of-done statement has fresh evidence. `FAILED` sets `next` to the same milestone. `BLOCKED` sets `next` to `STOP` until the blocker is resolved or the design is explicitly changed.

## Out Of Scope

- Database-backed profile storage
- Authentication or public internet exposure
- A visual redesign of the web page
- A replacement hardware driver
- A full installer redesign unrelated to packaging the MVC application
