#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/native/native-defaults.sh
source "${SCRIPT_DIR}/native-defaults.sh"

show_help() {
  cat <<'USAGE'
Usage: scripts/native/preflight.sh [--skip-port-check]

Run non-mutating checks for the native runtime path.

Checks:
  - Python and uv availability
  - uv lockfile and virtualenv runtime command
  - writable runtime directory configuration
  - port and active runtime conflict signals
  - Playwright package/browser dependency readiness notes

This script does not stop/start Docker, systemd, or remote services.
USAGE
}

skip_port_check="${KT_NATIVE_SKIP_PORT_CHECK:-0}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-port-check)
      skip_port_check="1"
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

native_info "Checking commands"
command -v "${KT_NATIVE_UV_BIN}" >/dev/null 2>&1 || native_fail "uv command not found: ${KT_NATIVE_UV_BIN}"
command -v "${KT_NATIVE_PYTHON_BIN}" >/dev/null 2>&1 || native_fail "Python command not found: ${KT_NATIVE_PYTHON_BIN}"

"${KT_NATIVE_PYTHON_BIN}" - <<'PY'
import sys

if sys.version_info < (3, 12):
    raise SystemExit("Python 3.12 or newer is required")
PY

[[ -f pyproject.toml ]] || native_fail "pyproject.toml not found"
[[ -f uv.lock ]] || native_fail "uv.lock not found"
[[ -x .venv/bin/uvicorn ]] || native_fail "Run scripts/native/setup-runtime.sh first; .venv/bin/uvicorn is missing"

native_info "Checking configured runtime directories"
for required_dir in \
  "${KT_NATIVE_DATA_DIR}" \
  "${KT_NATIVE_LOG_DIR}" \
  "${KT_NATIVE_CACHE_DIR}" \
  "${KT_NATIVE_ATTACHMENT_DIR}"; do
  if [[ ! -d "${required_dir}" ]]; then
    native_fail "Required runtime directory is missing: ${required_dir}"
  fi
  if [[ ! -w "${required_dir}" ]]; then
    native_fail "Required runtime directory is not writable: ${required_dir}"
  fi
done

if [[ "${skip_port_check}" != "1" ]]; then
  native_info "Checking port availability on ${KT_NATIVE_HEALTH_HOST}:${KT_NATIVE_PORT}"
  KT_NATIVE_HEALTH_HOST="${KT_NATIVE_HEALTH_HOST}" KT_NATIVE_PORT="${KT_NATIVE_PORT}" "${KT_NATIVE_PYTHON_BIN}" - <<'PY'
import os
import socket
import sys

host = os.environ["KT_NATIVE_HEALTH_HOST"]
port = int(os.environ["KT_NATIVE_PORT"])

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.settimeout(1.0)
    result = sock.connect_ex((host, port))

if result == 0:
    raise SystemExit(f"Port already accepts connections: {host}:{port}")
PY
fi

if command -v docker >/dev/null 2>&1; then
  if docker compose ps --status running --services 2>/dev/null | grep -qx "${KT_NATIVE_SERVICE_NAME}"; then
    native_fail "Docker compose service is already running: ${KT_NATIVE_SERVICE_NAME}"
  fi
fi

if command -v systemctl >/dev/null 2>&1; then
  if systemctl is-active --quiet "${KT_NATIVE_SERVICE_NAME}" 2>/dev/null; then
    native_fail "systemd service is already active: ${KT_NATIVE_SERVICE_NAME}"
  fi
fi

native_info "Checking Playwright Python package import"
"${KT_NATIVE_UV_BIN}" run --no-dev python - <<'PY'
from playwright.sync_api import sync_playwright

assert sync_playwright
PY

if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  os_id="${ID:-unknown}"
  os_like="${ID_LIKE:-}"
else
  os_id="unknown"
  os_like=""
fi

case " ${os_id} ${os_like} " in
  *" ubuntu "*|*" debian "*)
    native_info "Ubuntu/Debian family detected; setup can run Playwright with --with-deps when KT_NATIVE_INSTALL_PLAYWRIGHT_DEPS=1"
    ;;
  *" rhel "*|*" fedora "*|*" centos "*|*" rocky "*|*" amzn "*)
    native_info "RHEL/Rocky/Amazon family detected; confirm Chromium shared libraries through host package policy before cutover"
    ;;
  *)
    native_info "Unknown OS family; keep this run as readiness preflight only"
    ;;
esac

native_info "Native runtime preflight completed"
