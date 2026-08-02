#!/bin/bash
set -euo pipefail

# HTTPD service to display quadstick data
# Copyright 2024 felipe.dos.santos

CURRENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

cd "$CURRENT_DIR"

if [[ ! -f venv/bin/activate ]]; then
  echo "Error: virtual environment not found in $CURRENT_DIR" >&2
  exit 1
fi

source "venv/bin/activate"

python qs_display.py httpd
