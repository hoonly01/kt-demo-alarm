#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/native/native-defaults.sh
source "${SCRIPT_DIR}/native-defaults.sh"

repo_root="$(native_repo_root)"
template_path="${1:-${repo_root}/deploy/native/kt-demo-alarm.service.template}"
output_path="${2:-}"

[[ -f "${template_path}" ]] || native_fail "Template not found: ${template_path}"

rendered="$(
  KT_NATIVE_SERVICE_USER="${KT_NATIVE_SERVICE_USER}" \
  KT_NATIVE_SERVICE_GROUP="${KT_NATIVE_SERVICE_GROUP}" \
  KT_NATIVE_CURRENT_LINK="${KT_NATIVE_CURRENT_LINK}" \
  KT_NATIVE_ENV_FILE="${KT_NATIVE_ENV_FILE}" \
  KT_NATIVE_BIND_HOST="${KT_NATIVE_BIND_HOST}" \
  KT_NATIVE_PORT="${KT_NATIVE_PORT}" \
  KT_NATIVE_DATABASE_PATH="${KT_NATIVE_DATABASE_PATH}" \
  KT_NATIVE_CACHE_FILE="${KT_NATIVE_CACHE_FILE}" \
  KT_NATIVE_ATTACHMENT_DIR="${KT_NATIVE_ATTACHMENT_DIR}" \
  KT_NATIVE_LOG_DIR="${KT_NATIVE_LOG_DIR}" \
  KT_NATIVE_PLAYWRIGHT_BROWSERS_PATH="${KT_NATIVE_PLAYWRIGHT_BROWSERS_PATH}" \
  KT_NATIVE_TZ="${KT_NATIVE_TZ}" \
  KT_NATIVE_ENV_BIN="${KT_NATIVE_ENV_BIN}" \
  KT_NATIVE_UV_BIN="${KT_NATIVE_UV_BIN}" \
  KT_NATIVE_SHARED_DIR="${KT_NATIVE_SHARED_DIR}" \
  "${KT_NATIVE_PYTHON_BIN}" - "${template_path}" <<'PY'
import os
import pathlib
import sys

template = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
replacements = {
    "__APP_USER__": os.environ["KT_NATIVE_SERVICE_USER"],
    "__APP_GROUP__": os.environ["KT_NATIVE_SERVICE_GROUP"],
    "__CURRENT_LINK__": os.environ["KT_NATIVE_CURRENT_LINK"],
    "__ENV_FILE__": os.environ["KT_NATIVE_ENV_FILE"],
    "__APP_BIND_HOST__": os.environ["KT_NATIVE_BIND_HOST"],
    "__APP_PORT__": os.environ["KT_NATIVE_PORT"],
    "__DATABASE_PATH__": os.environ["KT_NATIVE_DATABASE_PATH"],
    "__CACHE_FILE__": os.environ["KT_NATIVE_CACHE_FILE"],
    "__ATTACHMENT_FOLDER__": os.environ["KT_NATIVE_ATTACHMENT_DIR"],
    "__LOG_DIR__": os.environ["KT_NATIVE_LOG_DIR"],
    "__PLAYWRIGHT_BROWSERS_PATH__": os.environ["KT_NATIVE_PLAYWRIGHT_BROWSERS_PATH"],
    "__TZ__": os.environ["KT_NATIVE_TZ"],
    "__ENV_BIN__": os.environ["KT_NATIVE_ENV_BIN"],
    "__UV_BIN__": os.environ["KT_NATIVE_UV_BIN"],
    "__SHARED_DIR__": os.environ["KT_NATIVE_SHARED_DIR"],
}

rendered = template
for key, value in replacements.items():
    rendered = rendered.replace(key, value)

if "__" in rendered:
    raise SystemExit("Unresolved placeholder remains in rendered unit")

print(rendered, end="")
PY
)"

if [[ -n "${output_path}" ]]; then
  printf '%s' "${rendered}" > "${output_path}"
else
  printf '%s' "${rendered}"
fi
