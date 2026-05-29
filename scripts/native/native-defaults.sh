#!/usr/bin/env bash

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "native-defaults.sh must be sourced by another native runtime script." >&2
  exit 64
fi

KT_NATIVE_SERVICE_NAME="${KT_NATIVE_SERVICE_NAME:-kt-demo-alarm}"
KT_NATIVE_APP_DIR="${KT_NATIVE_APP_DIR:-/opt/kt-demo-alarm}"
KT_NATIVE_ENV_FILE="${KT_NATIVE_ENV_FILE:-/etc/kt-demo-alarm/kt-demo-alarm.env}"
KT_NATIVE_SERVICE_USER="${KT_NATIVE_SERVICE_USER:-kt-demo-alarm}"
KT_NATIVE_SERVICE_GROUP="${KT_NATIVE_SERVICE_GROUP:-kt-demo-alarm}"
KT_NATIVE_HOST="${KT_NATIVE_HOST:-0.0.0.0}"
KT_NATIVE_PORT="${KT_NATIVE_PORT:-8000}"
KT_NATIVE_HEALTH_HOST="${KT_NATIVE_HEALTH_HOST:-127.0.0.1}"
KT_NATIVE_HEALTH_PATH="${KT_NATIVE_HEALTH_PATH:-/}"
KT_NATIVE_UV_BIN="${KT_NATIVE_UV_BIN:-uv}"
KT_NATIVE_PYTHON_BIN="${KT_NATIVE_PYTHON_BIN:-python3}"
KT_NATIVE_UVICORN_APP="${KT_NATIVE_UVICORN_APP:-main:app}"
KT_NATIVE_RESTART_SEC="${KT_NATIVE_RESTART_SEC:-5}"
KT_NATIVE_HEALTH_RETRIES="${KT_NATIVE_HEALTH_RETRIES:-30}"
KT_NATIVE_HEALTH_INTERVAL_SECONDS="${KT_NATIVE_HEALTH_INTERVAL_SECONDS:-2}"

KT_NATIVE_DATA_DIR="${KT_NATIVE_DATA_DIR:-${KT_NATIVE_APP_DIR}/data}"
KT_NATIVE_LOG_DIR="${KT_NATIVE_LOG_DIR:-${KT_NATIVE_APP_DIR}/logs}"
KT_NATIVE_CACHE_DIR="${KT_NATIVE_CACHE_DIR:-${KT_NATIVE_APP_DIR}/topis_cache}"
KT_NATIVE_ATTACHMENT_DIR="${KT_NATIVE_ATTACHMENT_DIR:-${KT_NATIVE_APP_DIR}/topis_attachments}"
KT_NATIVE_DATABASE_PATH="${KT_NATIVE_DATABASE_PATH:-${KT_NATIVE_DATA_DIR}/kt_demo_alarm.db}"
KT_NATIVE_CACHE_FILE="${KT_NATIVE_CACHE_FILE:-${KT_NATIVE_CACHE_DIR}/topis_cache.json}"
KT_NATIVE_PLAYWRIGHT_BROWSERS_PATH="${KT_NATIVE_PLAYWRIGHT_BROWSERS_PATH:-${KT_NATIVE_APP_DIR}/.cache/ms-playwright}"

native_repo_root() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "${script_dir}/../.." && pwd
}

native_fail() {
  echo "❌ $*" >&2
  exit 1
}

native_info() {
  echo "==> $*"
}

native_health_url() {
  printf 'http://%s:%s%s' \
    "${KT_NATIVE_HEALTH_HOST}" \
    "${KT_NATIVE_PORT}" \
    "${KT_NATIVE_HEALTH_PATH}"
}
