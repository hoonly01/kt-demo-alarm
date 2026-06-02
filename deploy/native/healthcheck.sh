#!/usr/bin/env bash
set -euo pipefail

APP_BIND_HOST="${APP_BIND_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8000}"
HEALTH_URL="${HEALTH_URL:-http://${APP_BIND_HOST}:${APP_PORT}/}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-180}"
HEALTH_INTERVAL_SECONDS="${HEALTH_INTERVAL_SECONDS:-3}"
CURL_BIN="${CURL_BIN:-curl}"

if ! [[ "${HEALTH_TIMEOUT_SECONDS}" =~ ^[0-9]+$ ]] || [[ "${HEALTH_TIMEOUT_SECONDS}" -lt 1 ]]; then
  echo "HEALTH_TIMEOUT_SECONDS must be a positive integer" >&2
  exit 2
fi

if ! [[ "${HEALTH_INTERVAL_SECONDS}" =~ ^[0-9]+$ ]] || [[ "${HEALTH_INTERVAL_SECONDS}" -lt 1 ]]; then
  echo "HEALTH_INTERVAL_SECONDS must be a positive integer" >&2
  exit 2
fi

deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
attempt=1

while (( SECONDS <= deadline )); do
  remaining_time=$((deadline - SECONDS))
  if (( remaining_time < 1 )); then
    break
  fi

  if "${CURL_BIN}" \
    --connect-timeout "${remaining_time}" \
    --max-time "${remaining_time}" \
    -fsS "${HEALTH_URL}" >/dev/null; then
    echo "Local health check succeeded: ${HEALTH_URL}"
    exit 0
  fi

  echo "Health attempt ${attempt} failed; retrying in ${HEALTH_INTERVAL_SECONDS}s"
  attempt=$((attempt + 1))

  remaining_time=$((deadline - SECONDS))
  if (( remaining_time < 1 )); then
    break
  fi

  sleep_seconds="${HEALTH_INTERVAL_SECONDS}"
  if (( sleep_seconds > remaining_time )); then
    sleep_seconds="${remaining_time}"
  fi
  sleep "${sleep_seconds}"
done

echo "Local health check failed within ${HEALTH_TIMEOUT_SECONDS}s: ${HEALTH_URL}" >&2
exit 1
