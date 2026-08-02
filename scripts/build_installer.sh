#!/usr/bin/env bash
# Build the Quadstick Display installer package.
#
# Stages the application tree under dist/, verifies every required
# packaged path, checks the ZIP archive integrity, and prepends the
# self-extracting installer script.
#
# Outputs:
#   dist/quadstick-display.zip  - the staged application archive
#   dist/quadstick-display.sh   - the self-extracting installer
#   dist/3d_case.zip            - the printable case models
set -euo pipefail

APP_NAME="quadstick-display"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"
STAGE_DIR="$DIST_DIR/$APP_NAME"
ZIP_FILE="$DIST_DIR/$APP_NAME.zip"
INSTALLER_FILE="$DIST_DIR/$APP_NAME.sh"
CASE_ZIP_FILE="$DIST_DIR/3d_case.zip"

log() {
  echo
  echo "==> $*"
}

die() {
  echo "Error: $*" >&2
  exit 1
}

for cmd in poetry python3 unzip; do
  command -v "$cmd" >/dev/null 2>&1 || die "required command '$cmd' not found in PATH"
done
poetry export --help >/dev/null 2>&1 ||
  die "poetry export is unavailable; install it with 'pipx inject poetry poetry-plugin-export'"

cd "$REPO_ROOT"

log "Cleaning previous build artifacts"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"

log "Generating requirements.txt"
poetry export --no-interaction --without-hashes \
  --output="$STAGE_DIR/requirements.txt"

log "Copying application files"
cp qs_display.py "$STAGE_DIR/qs_display.py"
cp resources/install/qs_display_httpd.sh "$STAGE_DIR/qs_display_httpd.sh"
cp resources/install/qs_display_httpd.service "$STAGE_DIR/qs_display_httpd.service"
cp -R quadstick_display "$STAGE_DIR/quadstick_display"
mkdir -p "$STAGE_DIR/resources"
cp -R resources/templates "$STAGE_DIR/resources/templates"
cp -R resources/fonts "$STAGE_DIR/resources/fonts"
cp -R resources/images "$STAGE_DIR/resources/images"
cp -R resources/quadstick_csvs "$STAGE_DIR/resources/quadstick_csvs"

log "Removing bytecode caches from the staged tree"
find "$STAGE_DIR" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$STAGE_DIR" -type f -name '*.py[co]' -delete

REQUIRED_PATHS=(
  qs_display.py
  qs_display_httpd.sh
  qs_display_httpd.service
  requirements.txt
  quadstick_display/__init__.py
  quadstick_display/__main__.py
  quadstick_display/model.py
  quadstick_display/view.py
  quadstick_display/controller.py
  quadstick_display/hardware.py
  quadstick_display/web.py
  resources/templates/index.html
  'resources/fonts/Arial Black.ttf'
  resources/fonts/GeForce-Bold.ttf
  resources/fonts/GeneraleMonoA.ttf
  'resources/fonts/Verdana Bold.ttf'
  resources/images/airflow_arrow_ltr.png
  resources/images/qs_logo.png
  resources/quadstick_csvs/ad_infinitum.csv
  resources/quadstick_csvs/alan_wake_II.csv
)

log "Checking required packaged paths"
for rel_path in "${REQUIRED_PATHS[@]}"; do
  [[ -e "$STAGE_DIR/$rel_path" ]] || die "missing required packaged path: $rel_path"
done

log "Creating $ZIP_FILE"
rm -f "$ZIP_FILE"
(cd "$DIST_DIR" && python3 -m zipfile -c "$ZIP_FILE" "$APP_NAME")

log "Checking required archive paths"
for rel_path in "${REQUIRED_PATHS[@]}"; do
  python3 -m zipfile -l "$ZIP_FILE" | grep -qF "$APP_NAME/$rel_path" ||
    die "missing required archive path: $APP_NAME/$rel_path"
done

log "Verifying archive integrity"
unzip -t "$ZIP_FILE" >/dev/null

log "Creating the self-extracting installer $INSTALLER_FILE"
cat resources/install/base_install.sh "$ZIP_FILE" >"$INSTALLER_FILE"
chmod +x "$INSTALLER_FILE"

log "Creating $CASE_ZIP_FILE"
rm -f "$CASE_ZIP_FILE"
python3 -m zipfile -c "$CASE_ZIP_FILE" 3d_case
unzip -t "$CASE_ZIP_FILE" >/dev/null

log "Removing the staging tree"
rm -rf "$STAGE_DIR"

echo
echo "Build complete:"
echo "  $ZIP_FILE"
echo "  $INSTALLER_FILE"
echo "  $CASE_ZIP_FILE"
