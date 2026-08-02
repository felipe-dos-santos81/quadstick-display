# Quadstick Display

Displays the current Quadstick key configuration on a Waveshare 4.2" e-ink
display attached to a Raspberry Pi, with a Flask web interface on port 8080.

## Layout

- `quadstick_display/` — the application package (MVC split):
  - `model.py` — pure domain model and profile store (no Flask/Pillow/hardware)
  - `view.py` — pure Pillow renderer
  - `controller.py` — serialized display transactions and the `DisplayDevice`
    protocol
  - `hardware.py` — Waveshare adapter (imports the driver lazily)
  - `web.py` — Flask blueprint and the `create_app` factory
  - `__main__.py` — production composition root
- `qs_display.py` — compatibility entrypoint (`python qs_display.py httpd`)
- `resources/` — templates, fonts, images, default CSV profiles, installer scripts
- `scripts/build_installer.sh` — assembles the installer into `dist/`
- `tests/` — unit, integration, and characterization tests (no hardware required)

## Make targets

A Makefile at the repo root wraps the local workflow; run `make help` to list
the targets (`make install`, `make check`, `make format`, `make test`,
`make build`, `make verify`, `make clean`). `make verify` runs the full
CI-equivalent block (static checks including ruff, the test suite, packaging,
and `git diff --check`).

## Verified local commands

```bash
poetry check
poetry install --with dev --no-interaction
poetry run ruff check .
poetry run ruff format --check .
poetry run pytest -q
python -m compileall -q quadstick_display qs_display.py
bash -n scripts/build_installer.sh resources/install/*.sh
scripts/build_installer.sh
unzip -t dist/quadstick-display.zip
```

`poetry export` requires `poetry-plugin-export`; install it once with
`poetry self add poetry-plugin-export` (pipx installs:
`pipx inject poetry poetry-plugin-export`).

## CI

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

## Hardware constraints

- Production runs on a Raspberry Pi (Zero 2 W) with the Waveshare 4.2" e-ink
  display; Pi-only dependencies (spidev, gpiozero, rpi-gpio, lgpio,
  waveshare-epd) install on Linux only — tests must never import them.
- Port 8080, the routes/form fields, the installer filename, the
  `qs_display_httpd.service` unit name, and the `/usr/local/quadstick-display`
  installation path are shipped contracts — do not change them.
- Custom uploaded CSVs in `resources/quadstick_csvs/` must survive
  reinstall/upgrade.
- Hardware acceptance runs on the Pi only; the host test suite and the
  packaging checks are the safety net before tagging a `v*` release.
