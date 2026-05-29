#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/native/native-defaults.sh
source "${SCRIPT_DIR}/native-defaults.sh"

health_url="$(native_health_url)"

native_info "Checking ${health_url}"
for attempt in $(seq 1 "${KT_NATIVE_HEALTH_RETRIES}"); do
  if command -v curl >/dev/null 2>&1; then
    if curl -fsS "${health_url}" >/dev/null; then
      native_info "Health check passed"
      exit 0
    fi
  else
    KT_NATIVE_HEALTH_URL="${health_url}" "${KT_NATIVE_PYTHON_BIN}" - <<'PY' && exit 0 || true
import os
import urllib.request

with urllib.request.urlopen(os.environ["KT_NATIVE_HEALTH_URL"], timeout=5) as response:
    if response.status >= 400:
        raise SystemExit(response.status)
PY
  fi

  if [[ "${attempt}" -lt "${KT_NATIVE_HEALTH_RETRIES}" ]]; then
    sleep "${KT_NATIVE_HEALTH_INTERVAL_SECONDS}"
  fi
done

native_fail "Health check failed after ${KT_NATIVE_HEALTH_RETRIES} attempts: ${health_url}"
