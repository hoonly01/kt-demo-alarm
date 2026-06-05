#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/native/native-defaults.sh
source "${SCRIPT_DIR}/../native/native-defaults.sh"

REPO_ROOT="$(native_repo_root)"

APP_NAME="${APP_NAME:-${KT_NATIVE_SERVICE_NAME}}"
APP_ROOT="${APP_ROOT:-${KT_NATIVE_APP_ROOT}}"
SRC_APP_ROOT="${SRC_APP_ROOT:-${APP_ROOT}}"
DEST_APP_ROOT="${DEST_APP_ROOT:-${APP_ROOT}}"

SRC_HOST="${SRC_HOST:-}"
SRC_USER="${SRC_USER:-}"
DEST_HOST="${DEST_HOST:-}"
DEST_USER="${DEST_USER:-}"

RELEASE_ID="${RELEASE_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
ARTIFACT_DIR="${ARTIFACT_DIR:-${PWD}/release-artifact/manual-${RELEASE_ID}}"
INCOMING_DIR="${INCOMING_DIR:-${DEST_APP_ROOT}/incoming/${RELEASE_ID}}"

BUNDLE_NAME="${BUNDLE_NAME:-source-bundle.tar.gz}"
CHECKSUM_NAME="${CHECKSUM_NAME:-source-bundle.sha256}"
SHARED_STATE_NAME="${SHARED_STATE_NAME:-shared-state.tar.gz}"
PREPARE_ARTIFACT_SYNTAX_CMD="${PREPARE_ARTIFACT_SYNTAX_CMD:-bash -n deploy/native/*.sh scripts/native/*.sh}"
PREPARE_ARTIFACT_NATIVE_TEST_CMD="${PREPARE_ARTIFACT_NATIVE_TEST_CMD:-uv run pytest tests/test_native_runtime_assets.py -q}"
PREPARE_ARTIFACT_FULL_TEST_CMD="${PREPARE_ARTIFACT_FULL_TEST_CMD:-uv run pytest -q}"

DEST_SHARED_DIR="${DEST_SHARED_DIR:-${DEST_APP_ROOT}/shared}"
DEST_ENV_FILE="${DEST_ENV_FILE:-${DEST_SHARED_DIR}/.env}"
SOURCE_LAYOUT="${SOURCE_LAYOUT:-}"

DRY_RUN="${DRY_RUN:-0}"
ALLOW_DOCKER_CUTOVER="${ALLOW_DOCKER_CUTOVER:-false}"
ALLOW_PORT_TAKEOVER="${ALLOW_PORT_TAKEOVER:-false}"
LOCAL_HOST_SENTINEL="${LOCAL_HOST_SENTINEL:-local}"

SSH_BIN="${SSH_BIN:-ssh}"
SCP_BIN="${SCP_BIN:-scp}"
LOCAL_BASH_BIN="${LOCAL_BASH_BIN:-bash}"

manual_fail() {
  echo "❌ $*" >&2
  exit 1
}

manual_info() {
  echo "==> $*"
}

manual_quote() {
  printf '%q' "$1"
}

manual_is_truthy() {
  case "${1,,}" in
    1|true|yes|y|on) return 0 ;;
    *) return 1 ;;
  esac
}

manual_is_local_host() {
  [[ "${1}" == "${LOCAL_HOST_SENTINEL}" ]]
}

manual_require_command() {
  command -v "$1" >/dev/null 2>&1 || manual_fail "Required command not found: $1"
}

manual_require_value() {
  local value="$1"
  local label="$2"
  [[ -n "${value}" ]] || manual_fail "Missing ${label}"
}

manual_normalize_path() {
  local path="$1"
  if [[ "${path}" == /* ]]; then
    printf '%s\n' "${path}"
  else
    printf '%s\n' "${PWD}/${path}"
  fi
}

ARTIFACT_DIR="$(manual_normalize_path "${ARTIFACT_DIR}")"

manual_bundle_path() {
  printf '%s/%s\n' "${ARTIFACT_DIR}" "${BUNDLE_NAME}"
}

manual_checksum_path() {
  printf '%s/%s\n' "${ARTIFACT_DIR}" "${CHECKSUM_NAME}"
}

manual_shared_state_path() {
  printf '%s/%s\n' "${ARTIFACT_DIR}" "${SHARED_STATE_NAME}"
}

manual_preview_command() {
  local parts=()
  local arg
  for arg in "$@"; do
    parts+=("$(manual_quote "${arg}")")
  done
  printf '[dry-run] %s\n' "${parts[*]}"
}

manual_run_command() {
  if manual_is_truthy "${DRY_RUN}"; then
    manual_preview_command "$@"
    return 0
  fi
  "$@"
}

manual_run_local_script() {
  local script="$1"
  if manual_is_truthy "${DRY_RUN}"; then
    echo "[dry-run] ${LOCAL_BASH_BIN} -lc $(manual_quote "${script}")"
    return 0
  fi
  "${LOCAL_BASH_BIN}" -lc "${script}"
}

manual_host_target() {
  local user="$1"
  local host="$2"
  if manual_is_local_host "${host}"; then
    printf '%s\n' "${LOCAL_HOST_SENTINEL}"
    return 0
  fi
  manual_require_value "${user}" "remote user for host ${host}"
  printf '%s@%s\n' "${user}" "${host}"
}

manual_run_host_script() {
  local user="$1"
  local host="$2"
  local script="$3"

  if manual_is_local_host "${host}"; then
    manual_run_local_script "${script}"
    return 0
  fi

  local target
  target="$(manual_host_target "${user}" "${host}")"
  if manual_is_truthy "${DRY_RUN}"; then
    echo "[dry-run] ${SSH_BIN} $(manual_quote "${target}") bash -lc $(manual_quote "${script}")"
    return 0
  fi
  "${SSH_BIN}" "${target}" "bash -lc $(manual_quote "${script}")"
}

manual_capture_host_output() {
  local user="$1"
  local host="$2"
  local script="$3"

  if manual_is_truthy "${DRY_RUN}"; then
    manual_fail "Cannot capture remote output in --dry-run mode; set SOURCE_LAYOUT explicitly for preview-only runs."
  fi

  if manual_is_local_host "${host}"; then
    "${LOCAL_BASH_BIN}" -lc "${script}"
    return 0
  fi

  local target
  target="$(manual_host_target "${user}" "${host}")"
  "${SSH_BIN}" "${target}" "bash -lc $(manual_quote "${script}")"
}

manual_copy_to_destination() {
  local host="$1"
  shift
  local destination="$1"
  shift

  if manual_is_local_host "${host}"; then
    manual_run_command mkdir -p "${destination}"
    manual_run_command cp "$@" "${destination}/"
    return 0
  fi

  local target
  target="$(manual_host_target "${DEST_USER}" "${host}")"
  if manual_is_truthy "${DRY_RUN}"; then
    manual_preview_command "${SCP_BIN}" "$@" "${target}:${destination}/"
    return 0
  fi
  "${SCP_BIN}" "$@" "${target}:${destination}/"
}

manual_show_help() {
  cat <<'USAGE'
Usage: scripts/manual/public-server-cutover.sh <subcommand> [options]

Phase-based manual migration wrapper for public/scp-constrained environments.
This script intentionally has no default "all" or one-shot cutover action.

Subcommands:
  prepare-artifact      Run local verification, package source bundle, and verify checksum
  detect-source-layout  Print native-shared or legacy-flat for the source host
  export-shared-state   Export data/topis_cache/topis_attachments/(optional) logs to shared-state tar.gz
  preflight-dest        Show destination-host blocker checks
  push                  Upload artifact bundle, checksum, shared state, and deploy helpers via scp
  restore-shared        Restore shared-state tar into the destination shared directory
  deploy                Execute deploy-release.sh once on the destination host
  postcheck             Gather minimal-cutover evidence from the destination host
  followup-checklist    Print the public/TLS/Playwright/outbound follow-up checklist
  help                  Show this help

Options:
  --dry-run             Print the command(s) without executing them
  --source-layout <v>   Force source layout for export-shared-state (native-shared|legacy-flat)
  --allow-docker-cutover
                        Pass ALLOW_DOCKER_CUTOVER=true to the remote deploy command
  --allow-port-takeover
                        Pass ALLOW_PORT_TAKEOVER=true to the remote deploy command
  --help, -h            Show this help

Variable conventions:
  APP_NAME=kt-demo-alarm
  APP_ROOT=/opt/kt-demo-alarm
  SRC_APP_ROOT=${APP_ROOT}          # override when source and destination roots differ
  DEST_APP_ROOT=${APP_ROOT}
  RELEASE_ID=$(date -u +%Y%m%dT%H%M%SZ)
  ARTIFACT_DIR=$PWD/release-artifact/manual-${RELEASE_ID}
  INCOMING_DIR=${DEST_APP_ROOT}/incoming/${RELEASE_ID}

Transport notes:
  - Production path uses ssh/scp.
  - For local integration checks, set SRC_HOST=local and/or DEST_HOST=local.
USAGE
}

manual_parse_common_flags() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      --source-layout)
        SOURCE_LAYOUT="${2:-}"
        shift 2
        ;;
      --allow-docker-cutover)
        ALLOW_DOCKER_CUTOVER=true
        shift
        ;;
      --allow-port-takeover)
        ALLOW_PORT_TAKEOVER=true
        shift
        ;;
      --help|-h)
        manual_show_help
        exit 0
        ;;
      *)
        manual_fail "Unknown option: $1"
        ;;
    esac
  done
}

manual_resolve_source_layout() {
  if [[ -n "${SOURCE_LAYOUT}" ]]; then
    case "${SOURCE_LAYOUT}" in
      native-shared|legacy-flat)
        printf '%s\n' "${SOURCE_LAYOUT}"
        return 0
        ;;
      *)
        manual_fail "Invalid SOURCE_LAYOUT: ${SOURCE_LAYOUT}"
        ;;
    esac
  fi

  manual_require_value "${SRC_HOST}" "SRC_HOST"
  local detect_script
  detect_script=$(
    cat <<EOF
set -euo pipefail
if [[ -d $(manual_quote "${SRC_APP_ROOT}/shared") ]]; then
  echo native-shared
else
  echo legacy-flat
fi
EOF
  )
  manual_capture_host_output "${SRC_USER}" "${SRC_HOST}" "${detect_script}"
}

manual_cmd_prepare_artifact() {
  manual_require_command bash

  mkdir -p "${ARTIFACT_DIR}"
  (
    cd "${REPO_ROOT}"
    manual_run_local_script "${PREPARE_ARTIFACT_SYNTAX_CMD}"
    manual_run_local_script "${PREPARE_ARTIFACT_NATIVE_TEST_CMD}"
    manual_run_local_script "${PREPARE_ARTIFACT_FULL_TEST_CMD}"
    manual_run_command bash deploy/native/package-source-bundle.sh "${ARTIFACT_DIR}"
    manual_run_command bash deploy/native/verify-source-bundle.sh \
      "$(manual_bundle_path)" \
      "$(manual_checksum_path)"
  )

  manual_info "Artifact bundle: $(manual_bundle_path)"
  manual_info "Artifact checksum: $(manual_checksum_path)"
}

manual_cmd_detect_source_layout() {
  manual_require_value "${SRC_HOST}" "SRC_HOST"
  local layout
  layout="$(manual_resolve_source_layout)"
  printf '%s\n' "${layout}"
}

manual_cmd_export_shared_state() {
  manual_require_value "${SRC_HOST}" "SRC_HOST"
  mkdir -p "${ARTIFACT_DIR}"

  local layout
  layout="$(manual_resolve_source_layout)"

  local source_root
  case "${layout}" in
    native-shared)
      source_root="${SRC_APP_ROOT}/shared"
      ;;
    legacy-flat)
      source_root="${SRC_APP_ROOT}"
      ;;
    *)
      manual_fail "Unsupported source layout: ${layout}"
      ;;
  esac

  local export_script
  export_script=$(
    cat <<EOF
set -euo pipefail
source_root=$(manual_quote "${source_root}")
declare -a entries=()
for candidate in data topis_cache topis_attachments logs; do
  if [[ -e "\${source_root}/\${candidate}" ]]; then
    entries+=("\${candidate}")
  fi
done
(( \${#entries[@]} > 0 )) || { echo "No shared-state entries found under \${source_root}" >&2; exit 1; }
tar -C "\${source_root}" -czf - "\${entries[@]}"
EOF
  )

  local output_path
  output_path="$(manual_shared_state_path)"

  if manual_is_truthy "${DRY_RUN}"; then
    if manual_is_local_host "${SRC_HOST}"; then
      echo "[dry-run] ${LOCAL_BASH_BIN} -lc $(manual_quote "${export_script}") > $(manual_quote "${output_path}")"
    else
      local target
      target="$(manual_host_target "${SRC_USER}" "${SRC_HOST}")"
      echo "[dry-run] ${SSH_BIN} $(manual_quote "${target}") bash -lc $(manual_quote "${export_script}") > $(manual_quote "${output_path}")"
    fi
    return 0
  fi

  if manual_is_local_host "${SRC_HOST}"; then
    "${LOCAL_BASH_BIN}" -lc "${export_script}" > "${output_path}"
  else
    local target
    target="$(manual_host_target "${SRC_USER}" "${SRC_HOST}")"
    "${SSH_BIN}" "${target}" "bash -lc $(manual_quote "${export_script}")" > "${output_path}"
  fi

  manual_info "Shared state archive: ${output_path}"
}

manual_cmd_preflight_dest() {
  manual_require_value "${DEST_HOST}" "DEST_HOST"

  local preflight_script
  preflight_script=$(
    cat <<EOF
set -euo pipefail
systemctl --version
uv --version
id $(manual_quote "${APP_NAME}")
stat -c '%a %U %G %n' $(manual_quote "${DEST_ENV_FILE}")
docker ps --format '{{.Names}}' || true
ss -ltn 'sport = :${KT_NATIVE_PORT}' || true
EOF
  )

  manual_run_host_script "${DEST_USER}" "${DEST_HOST}" "${preflight_script}"
}

manual_cmd_push() {
  manual_require_value "${DEST_HOST}" "DEST_HOST"
  [[ -f "$(manual_bundle_path)" ]] || manual_fail "Missing source bundle: $(manual_bundle_path)"
  [[ -f "$(manual_checksum_path)" ]] || manual_fail "Missing source bundle checksum: $(manual_checksum_path)"
  [[ -f "$(manual_shared_state_path)" ]] || manual_fail "Missing shared state archive: $(manual_shared_state_path)"

  local mkdir_script
  mkdir_script=$(
    cat <<EOF
set -euo pipefail
mkdir -p $(manual_quote "${INCOMING_DIR}")
EOF
  )
  manual_run_host_script "${DEST_USER}" "${DEST_HOST}" "${mkdir_script}"

  manual_copy_to_destination "${DEST_HOST}" "${INCOMING_DIR}" \
    "$(manual_bundle_path)" \
    "$(manual_checksum_path)" \
    "$(manual_shared_state_path)" \
    "${REPO_ROOT}/deploy/native/deploy-release.sh" \
    "${REPO_ROOT}/deploy/native/verify-source-bundle.sh"
}

manual_cmd_restore_shared() {
  manual_require_value "${DEST_HOST}" "DEST_HOST"

  local restore_script
  restore_script=$(
    cat <<EOF
set -euo pipefail
mkdir -p \
  $(manual_quote "${DEST_SHARED_DIR}/data") \
  $(manual_quote "${DEST_SHARED_DIR}/logs") \
  $(manual_quote "${DEST_SHARED_DIR}/topis_cache") \
  $(manual_quote "${DEST_SHARED_DIR}/topis_attachments")
tar -C $(manual_quote "${DEST_SHARED_DIR}") -xzf $(manual_quote "${INCOMING_DIR}/${SHARED_STATE_NAME}")
EOF
  )

  manual_run_host_script "${DEST_USER}" "${DEST_HOST}" "${restore_script}"
}

manual_cmd_deploy() {
  manual_require_value "${DEST_HOST}" "DEST_HOST"

  local docker_override=""
  local port_override=""
  if manual_is_truthy "${ALLOW_DOCKER_CUTOVER}"; then
    docker_override=$'\n'"ALLOW_DOCKER_CUTOVER=true"
  fi
  if manual_is_truthy "${ALLOW_PORT_TAKEOVER}"; then
    port_override=$'\n'"ALLOW_PORT_TAKEOVER=true"
  fi

  local deploy_script
  deploy_script=$(
    cat <<EOF
set -euo pipefail
APP_NAME=$(manual_quote "${APP_NAME}")
APP_ROOT=$(manual_quote "${DEST_APP_ROOT}")
RELEASE_ID=$(manual_quote "${RELEASE_ID}")
BUNDLE_PATH=$(manual_quote "${INCOMING_DIR}/${BUNDLE_NAME}")
CHECKSUM_PATH=$(manual_quote "${INCOMING_DIR}/${CHECKSUM_NAME}")
VERIFY_SOURCE_BUNDLE_BIN=$(manual_quote "${INCOMING_DIR}/verify-source-bundle.sh")${docker_override}${port_override}
bash $(manual_quote "${INCOMING_DIR}/deploy-release.sh")
EOF
  )

  manual_run_host_script "${DEST_USER}" "${DEST_HOST}" "${deploy_script}"
}

manual_cmd_postcheck() {
  manual_require_value "${DEST_HOST}" "DEST_HOST"

  local postcheck_script
  postcheck_script=$(
    cat <<EOF
set -euo pipefail
readlink -f $(manual_quote "${DEST_APP_ROOT}/current")
systemctl status $(manual_quote "${APP_NAME}") --no-pager
curl -fsS $(manual_quote "$(native_health_url)")
journalctl -u $(manual_quote "${APP_NAME}") -n 100 --no-pager
EOF
  )

  manual_run_host_script "${DEST_USER}" "${DEST_HOST}" "${postcheck_script}"
}

manual_cmd_followup_checklist() {
  cat <<EOF
minimal-cutover 이후 follow-up checklist

- Public/TLS: 기관 reverse proxy 또는 public domain 이 destination host 를 향하는지 확인
- Playwright/Chromium: SPATIC 수집용 browser/runtime 이 준비됐는지 확인
- Runtime outbound: Kakao/TOPIS/TMAP/BizRouter/SPATIC/SMPA allowlist 확인
- Public smoke: 필요 시 https://<public-domain>/ health 확인
EOF
}

main() {
  if [[ $# -eq 0 ]]; then
    manual_show_help
    exit 0
  fi

  local subcommand="$1"
  shift
  manual_parse_common_flags "$@"

  case "${subcommand}" in
    help)
      manual_show_help
      ;;
    prepare-artifact)
      manual_cmd_prepare_artifact
      ;;
    detect-source-layout)
      manual_cmd_detect_source_layout
      ;;
    export-shared-state)
      manual_cmd_export_shared_state
      ;;
    preflight-dest)
      manual_cmd_preflight_dest
      ;;
    push)
      manual_cmd_push
      ;;
    restore-shared)
      manual_cmd_restore_shared
      ;;
    deploy)
      manual_cmd_deploy
      ;;
    postcheck)
      manual_cmd_postcheck
      ;;
    followup-checklist)
      manual_cmd_followup_checklist
      ;;
    *)
      manual_fail "Unknown subcommand: ${subcommand}"
      ;;
  esac
}

main "$@"
