#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/native/native-defaults.sh
source "${SCRIPT_DIR}/native-defaults.sh"

show_help() {
  cat <<'USAGE'
Usage: scripts/native/setup-runtime.sh [--skip-playwright-browser]

Prepare the native Python runtime in the current checkout.

Environment overrides:
  KT_NATIVE_UV_BIN
  KT_NATIVE_PYTHON_BIN
  KT_NATIVE_APP_DIR
  KT_NATIVE_DATA_DIR
  KT_NATIVE_LOG_DIR
  KT_NATIVE_CACHE_DIR
  KT_NATIVE_ATTACHMENT_DIR
  KT_NATIVE_PLAYWRIGHT_BROWSERS_PATH
  KT_NATIVE_INSTALL_PLAYWRIGHT_DEPS=1

This script does not install OS packages and does not start or stop services.
USAGE
}

skip_playwright_browser="${KT_NATIVE_SKIP_PLAYWRIGHT_BROWSER:-0}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-playwright-browser)
      skip_playwright_browser="1"
      shift
      ;;
    --help|-h)
      show_help
      exit 0
      ;;
    *)
      native_fail "Unknown argument: $1"
      ;;
  esac
done

repo_root="$(native_repo_root)"
cd "${repo_root}"

command -v "${KT_NATIVE_UV_BIN}" >/dev/null 2>&1 || native_fail "uv command not found: ${KT_NATIVE_UV_BIN}"
command -v "${KT_NATIVE_PYTHON_BIN}" >/dev/null 2>&1 || native_fail "Python command not found: ${KT_NATIVE_PYTHON_BIN}"

"${KT_NATIVE_PYTHON_BIN}" - <<'PY'
import sys

if sys.version_info < (3, 12):
    raise SystemExit("Python 3.12 or newer is required")
PY

[[ -f pyproject.toml ]] || native_fail "pyproject.toml not found in ${repo_root}"
[[ -f uv.lock ]] || native_fail "uv.lock not found in ${repo_root}"

native_info "Syncing production dependencies from uv.lock"
"${KT_NATIVE_UV_BIN}" sync --frozen --no-dev

native_info "Preparing runtime directories"
mkdir -p \
  "${KT_NATIVE_DATA_DIR}" \
  "${KT_NATIVE_LOG_DIR}" \
  "${KT_NATIVE_CACHE_DIR}" \
  "${KT_NATIVE_ATTACHMENT_DIR}/route_images" \
  "${KT_NATIVE_ATTACHMENT_DIR}/protest_images" \
  "${KT_NATIVE_PLAYWRIGHT_BROWSERS_PATH}"

if [[ "${skip_playwright_browser}" == "1" ]]; then
  native_info "Skipping Playwright browser download by request"
elif [[ "${KT_NATIVE_INSTALL_PLAYWRIGHT_DEPS:-0}" == "1" ]]; then
  native_info "Installing Chromium and supported OS dependencies through Playwright"
  PLAYWRIGHT_BROWSERS_PATH="${KT_NATIVE_PLAYWRIGHT_BROWSERS_PATH}" \
    "${KT_NATIVE_UV_BIN}" run --no-dev playwright install chromium --with-deps
else
  native_info "Installing Chromium browser only; run OS dependency preflight separately"
  PLAYWRIGHT_BROWSERS_PATH="${KT_NATIVE_PLAYWRIGHT_BROWSERS_PATH}" \
    "${KT_NATIVE_UV_BIN}" run --no-dev playwright install chromium
fi

[[ -x .venv/bin/uvicorn ]] || native_fail "Expected executable missing: ${repo_root}/.venv/bin/uvicorn"

native_info "Native runtime setup completed"
