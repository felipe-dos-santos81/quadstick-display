# Makefile for Quadstick Display — MVC e-ink display application
# Targets are grouped by workflow stage:
#   env → check → test → build → verify → clean
SERVICE = Quadstick Display

# Variables
POETRY ?= poetry
PYTHON = $(POETRY) run python
PYTEST = $(POETRY) run pytest -q
EXPORT_PLUGIN = poetry-plugin-export
DIST_DIR = dist
APP_ZIP = $(DIST_DIR)/quadstick-display.zip

.PHONY: help install install-export-plugin check \
        test test-unit test-integration test-characterization \
        build verify clean

# ── Environment ──────────────────────────────────────────────────────────────

help: ## Print this help message
	@printf '\033[01;32m${SERVICE} — MVC e-ink display application\033[00;37m\n\n'
	@printf "\033[33mUsage:\033[0m\n  make [target] [arg=\"val\"...]\n\n\033[33mTargets:\033[0m\n"
	@grep -E '^[-a-zA-Z0-9_\.\/]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; \
		{printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'

install: ## Install all dependencies, including dev, via Poetry
	$(POETRY) install --with dev --no-interaction

# `poetry export` needs the plugin: pipx-managed Poetry uses
# `pipx inject poetry poetry-plugin-export`, self-managed uses
# `poetry self add poetry-plugin-export`. Skips if already available.
install-export-plugin: ## Install poetry-plugin-export (required by make build)
	@if $(POETRY) export --help >/dev/null 2>&1; then \
		echo "poetry-plugin-export already available."; \
	elif pipx list --short 2>/dev/null | grep -q '^poetry '; then \
		pipx inject poetry $(EXPORT_PLUGIN); \
	else \
		$(POETRY) self add $(EXPORT_PLUGIN); \
	fi

# ── Static checks ────────────────────────────────────────────────────────────

check: install ## Run poetry check, bytecode compilation, and shell syntax checks
	$(POETRY) check
	$(PYTHON) -m compileall -q quadstick_display qs_display.py
	bash -n scripts/build_installer.sh resources/install/*.sh

# ── Tests (no Raspberry Pi hardware required) ────────────────────────────────

test: install ## Run the full pytest suite (unit + integration + characterization)
	$(PYTEST)

test-unit: install ## Run unit tests only
	$(PYTEST) tests/unit

test-integration: install ## Run Flask integration tests only
	$(PYTEST) tests/integration

test-characterization: install ## Run characterization tests only
	$(PYTEST) tests/characterization

# ── Packaging ────────────────────────────────────────────────────────────────

build: install ## Assemble installer artifacts into dist/ and verify archive integrity
	scripts/build_installer.sh
	@unzip -t $(APP_ZIP)

# ── Full verification (mirrors the CI verify workflow) ───────────────────────

verify: check test build ## Run the complete local verification block
	@git diff --check
	@echo "Verification complete."

# ── Cleanup ──────────────────────────────────────────────────────────────────

clean: ## Remove dist/, pytest cache, and all bytecode caches
	rm -rf $(DIST_DIR)
	rm -rf .pytest_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +
	@echo "Cleanup complete."
