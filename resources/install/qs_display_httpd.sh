#!/bin/bash

# HTTPD service to display quadstick data
# Copyright 2024 felipe.dos.santos

CURRENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

cd "$CURRENT_DIR" || exit 1

source "venv/bin/activate"

python qs_display.py httpd