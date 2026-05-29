#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/native/native-defaults.sh
source "${SCRIPT_DIR}/native-defaults.sh"

repo_root="$(native_repo_root)"
template_path="${1:-${repo_root}/deploy/systemd/kt-demo-alarm.service.template}"
output_path="${2:-}"

[[ -f "${template_path}" ]] || native_fail "Template not found: ${template_path}"

rendered="$(
  KT_NATIVE_SERVICE_NAME="${KT_NATIVE_SERVICE_NAME}" \
  KT_NATIVE_APP_DIR="${KT_NATIVE_APP_DIR}" \
  KT_NATIVE_ENV_FILE="${KT_NATIVE_ENV_FILE}" \
  KT_NATIVE_SERVICE_USER="${KT_NATIVE_SERVICE_USER}" \
  KT_NATIVE_SERVICE_GROUP="${KT_NATIVE_SERVICE_GROUP}" \
  KT_NATIVE_HOST="${KT_NATIVE_HOST}" \
  KT_NATIVE_PORT="${KT_NATIVE_PORT}" \
  KT_NATIVE_UVICORN_APP="${KT_NATIVE_UVICORN_APP}" \
  KT_NATIVE_RESTART_SEC="${KT_NATIVE_RESTART_SEC}" \
  KT_NATIVE_DATA_DIR="${KT_NATIVE_DATA_DIR}" \
  KT_NATIVE_LOG_DIR="${KT_NATIVE_LOG_DIR}" \
  KT_NATIVE_CACHE_DIR="${KT_NATIVE_CACHE_DIR}" \
  KT_NATIVE_ATTACHMENT_DIR="${KT_NATIVE_ATTACHMENT_DIR}" \
  KT_NATIVE_DATABASE_PATH="${KT_NATIVE_DATABASE_PATH}" \
  KT_NATIVE_CACHE_FILE="${KT_NATIVE_CACHE_FILE}" \
  KT_NATIVE_PLAYWRIGHT_BROWSERS_PATH="${KT_NATIVE_PLAYWRIGHT_BROWSERS_PATH}" \
  "${KT_NATIVE_PYTHON_BIN}" - "${template_path}" <<'PY'
import os
import pathlib
import sys

template = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
keys = [
    "KT_NATIVE_SERVICE_NAME",
    "KT_NATIVE_APP_DIR",
    "KT_NATIVE_ENV_FILE",
    "KT_NATIVE_SERVICE_USER",
    "KT_NATIVE_SERVICE_GROUP",
    "KT_NATIVE_HOST",
    "KT_NATIVE_PORT",
    "KT_NATIVE_UVICORN_APP",
    "KT_NATIVE_RESTART_SEC",
    "KT_NATIVE_DATA_DIR",
    "KT_NATIVE_LOG_DIR",
    "KT_NATIVE_CACHE_DIR",
    "KT_NATIVE_ATTACHMENT_DIR",
    "KT_NATIVE_DATABASE_PATH",
    "KT_NATIVE_CACHE_FILE",
    "KT_NATIVE_PLAYWRIGHT_BROWSERS_PATH",
]

rendered = template
for key in keys:
    rendered = rendered.replace("{{" + key + "}}", os.environ[key])

if "{{" in rendered or "}}" in rendered:
    raise SystemExit("Unresolved placeholder remains in rendered unit")

print(rendered, end="")
PY
)"

if [[ -n "${output_path}" ]]; then
  printf '%s' "${rendered}" > "${output_path}"
else
  printf '%s' "${rendered}"
fi
